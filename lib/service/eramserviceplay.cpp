#include "eramserviceplay.h"
#include <algorithm>
#include <lib/base/cfile.h>
#include <lib/base/esettings.h>
#include <lib/base/esimpleconfig.h>
#include <lib/dvb/csasession.h>
#include <unistd.h>

DEFINE_REF(eRamServicePlay);

eRamServicePlay::eRamServicePlay(const eServiceReference& ref, eDVBService* service, int delay_seconds) : eDVBServicePlay(ref, service, true) {
	m_ts_source = nullptr;
	m_ram_recorder = nullptr;
	m_frozen_play_position = 0;

	// At least 32 MB or delay_seconds * 2.5 MB (~20 Mbit/s average bitrate).
	int cap_mb = std::max(32, (int)(delay_seconds * 2.5));
	m_capacity_bytes = (size_t)cap_mb * 1024 * 1024;
	eDebug("[eRamServicePlay] cap=%dMB", cap_mb);
}

eRamServicePlay::~eRamServicePlay() {
	stopTimeshift(false);
}

RESULT eRamServicePlay::startTimeshift() {
	if (m_timeshift_enabled)
		return -1;
	ePtr<iDVBDemux> demux;
	if (m_service_handler.getDataDemux(demux))
		return -2;

	m_ram_ring = std::make_shared<eRamRingBuffer>(m_capacity_bytes, 8192);
	if (!m_ram_ring->isValid()) {
		eWarning("[eRamServicePlay] RAM buffer allocation failed");
		m_ram_ring.reset();
		return -3;
	}

	demux->createTSRecorder(m_record, 188, false);

	// RTTI is disabled (-fno-rtti); use static_cast to access eDVBTSRecorder methods.
	eDVBTSRecorder* recorder = static_cast<eDVBTSRecorder*>(m_record.operator->());
	if (!recorder) {
		eWarning("[eRamServicePlay] Failed to get recorder - RAM timeshift aborted");
		m_ram_ring.reset();
		m_record = 0;
		return -3;
	}

	eRamRecorder* ram_rec = new eRamRecorder(m_ram_ring.get(), 188);
	m_ram_recorder = ram_rec;
	recorder->replaceThread(ram_rec);
	m_record->setTargetFD(-1);

	// Access points remain enabled so eRamRecorder can tag ring-buffer blocks
	// with I-frame flags, allowing findNearestAccessPoint() to snap seeks to
	// clean boundaries. No .ap file is written (m_structure_write_fd stays -1).

	m_record->connectEvent(sigc::mem_fun(*this, &eRamServicePlay::recordEvent), m_con_record_event);

	// StreamRelay / CSA-ALT channels need per-session descrambling.
	if (m_csa_session && m_csa_session->isActive()) {
		eServiceReferenceDVB dvb_ref = (eServiceReferenceDVB&)m_reference;
		m_timeshift_csa_session = new eDVBCSASession(dvb_ref);
		if (m_timeshift_csa_session && m_timeshift_csa_session->init()) {
			m_timeshift_csa_session->forceActivate();
			m_record->setDescrambler(static_cast<iServiceScrambled*>(m_timeshift_csa_session.operator->()));
		}
	}

	// Use /tmp/ram_timeshift as the base path; write an empty .ap sentinel
	// so tstools doesn't log ENOENT warnings.
	m_timeshift_file = "/tmp/ram_timeshift";
	CFile::writeStr("/tmp/ram_timeshift.ap", "");
	m_timeshift_enabled = 1;
	updateTimeshiftPids();

	const int sret = m_record->start();
	if (sret < 0) {
		eWarning("[eRamServicePlay] record->start() failed: %d", sret);
		if (m_timeshift_csa_session) {
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_ram_recorder = nullptr;
		m_record = 0;
		m_ram_ring.reset();
		::unlink("/tmp/ram_timeshift.ap");
		m_timeshift_file.clear();
		m_timeshift_enabled = 0;
		return sret;
	}

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "1");
	CFile::writeStr("/proc/stb/lcd/symbol_record", "1");
	eDebug("[eRamServicePlay] recording started (%zuMB)", m_capacity_bytes >> 20);
	return 0;
}

RESULT eRamServicePlay::activateTimeshift() {
	RESULT r = eDVBServicePlay::activateTimeshift();
	if (r != 0)
		return r;

	// 200 ms watchdog: detects ring-buffer lap events and jumps the push
	// thread to a safe read position.
	m_watchdog_timer = eTimer::create(eApp);
	m_watchdog_timer->timeout.connect(sigc::mem_fun(*this, &eRamServicePlay::checkLapAndSeek));
	m_watchdog_timer->start(200, false);
	return 0;
}

void eRamServicePlay::checkLapAndSeek() {
	if (!m_timeshift_active)
		return;

	// Do not move the read position while PRS is paused waiting for corruption
	// to clear — a position jump here would break PRS recovery.
	if (m_stream_corruption_detected)
		return;

	ePtr<eRamTsSource> src = m_ts_source;
	if (!src)
		return;

	off_t lapped_at = 0;
	if (!src->getLappedOffset(lapped_at))
		return;

	if (!m_ram_ring)
		return;

	off_t min_off = m_ram_ring->getMinOffset();

	// Align up to 188-byte packet boundary for clean decode.
	off_t safe = min_off + (188 - min_off % 188) % 188;
	eDebug("[eRamServicePlay] watchdog: lap at %lld, jumping to min_off=%lld", (long long)lapped_at, (long long)safe);

	ePtr<iDVBPVRChannel> pvr_channel;
	if (m_service_handler_timeshift.getPVRChannel(pvr_channel) == 0)
		pvr_channel->forceSourcePosition(safe);
}

void eRamServicePlay::recordEvent(int event) {
	if (event == iDVBTSRecorder::eventStreamCorrupt) {
		if (!m_stream_corruption_detected) {
			eWarning("[eRamServicePlay] Stream corrupt: letting decoder play through valid buffer.");

			// Capture delay fingerprint immediately — PTS is still valid here.
			// The base class would call pause() and set m_stream_corruption_detected,
			// but we intercept to allow the decoder to consume remaining good data.
			if (m_record) {
				pts_t live_pts = 0, playback_pts = 0;
				if (m_record->getCurrentPCR(live_pts) == 0 &&
				    getPlayPosition(playback_pts) == 0) {
					pts_t first_pts = 0;
					if (m_record->getFirstPTS(first_pts) == 0) {
						pts_t abs_play = (first_pts + playback_pts) & 0x1FFFFFFFF;
						m_original_timeshift_delay = pts_delta(live_pts, abs_play);
						m_delay_calculated = true;
						eTrace("[eRamServicePlay] Delay fingerprint: %lld PTS",
						       (long long)m_original_timeshift_delay);
					}
				}
			}

			// Freeze position for UI (not for PRS — decoder still moving).
			getPlayPosition(m_frozen_play_position);

			// Mark corruption and start PRS timer — do NOT call base class
			// (which would issue m_decoder->pause() immediately).
			m_stream_corruption_detected = true;
			if (!m_precise_recovery_timer->isActive())
				m_precise_recovery_timer->start(100, false);
		}
		// Do NOT forward eventStreamCorrupt to base class — that would trigger
		// the immediate pause() in eDVBServicePlay::recordEvent().
		return;
	}

	// All other events (evtWriteError, etc.) pass through normally.
	eDVBServicePlay::recordEvent(event);
}

// RAM-specific PRS override with two states:
//
// State 1 (decoder paused): wait until delay >= original_delay + safety,
//         then unpause.
//
// State 2 (decoder still playing): after a short corruption the stream may
//         recover before the decoder reaches the live edge. In this case the
//         delay stays constant (both live and decoder advance at 1x). We must
//         issue a Soft Pause explicitly so delay can grow again.
void eRamServicePlay::startPreciseRecoveryCheck() {
	if (!m_stream_corruption_detected || !m_record || !m_delay_calculated) {
		m_precise_recovery_timer->stop();
		return;
	}

	pts_t live_pts = 0;
	if (m_record->getCurrentPCR(live_pts) != 0 || live_pts == 0) {
		m_precise_recovery_timer->start(100, false);
		return;
	}

	pts_t first_pts = 0;
	if (m_record->getFirstPTS(first_pts) != 0) {
		m_precise_recovery_timer->start(100, false);
		return;
	}

	pts_t playback_pts = 0;
	if (getPlayPosition(playback_pts) != 0) {
		m_precise_recovery_timer->start(100, false);
		return;
	}

	pts_t abs_play     = (first_pts + playback_pts) & 0x1FFFFFFFF;
	pts_t current_delay = pts_delta(live_pts, abs_play);

	int recovery_ms = eSimpleConfig::getInt("config.timeshift.recoveryBufferDelay", 300);
	const pts_t safety_pts       = (pts_t)(recovery_ms * 90);
	const pts_t final_target_pts = m_original_timeshift_delay + safety_pts;

	bool recovery_complete = false;

	if (m_is_paused) {
		// ── State 1: decoder paused, wait for buffer to rebuild ──
		if (current_delay >= final_target_pts)
			recovery_complete = true;
	} else {
		// ── State 2: decoder still playing ──
		// Soft-pause in two sub-cases:
		// A) Stream recovered but delay is stuck constant (both sides advancing at 1x):
		//    current_delay >= safety_pts — pause so delay can grow to target.
		// B) Decoder approaching live edge on long corruption (starvation risk):
		//    current_delay < 1 second — pause before decoder hits the wall.
		const pts_t STARVATION_THRESHOLD = 90000LL; // 1 second
		if (current_delay >= safety_pts || current_delay < STARVATION_THRESHOLD) {
			eWarning("[eRamServicePlay] PRS State 2: soft-pausing decoder (delay=%lld PTS).",
			         (long long)current_delay);
			getPlayPosition(m_frozen_play_position);
			if (m_decoder && !m_is_paused) {
				m_decoder->pause();
				m_is_paused = 1;
			}
		}
		// Stay in timer loop — will hit State 1 on next tick.
	}

	if (recovery_complete) {
		m_precise_recovery_timer->stop();
		m_stream_corruption_detected = false;
		if (m_is_paused)
			unpause();
		m_event((iPlayableService*)this, evSeekableStatusChanged);
	} else {
		m_precise_recovery_timer->start(100, false);
	}
}

// On RAM timeshift there is no end-of-file: eventEOF from the push thread means
// either a ring-buffer lap (handled by checkLapAndSeek) or reaching the live
// edge (normal — wait for data). Suppress switchToLive() in both cases.
void eRamServicePlay::serviceEventTimeshift(int event) {
	if (event == eDVBServicePMTHandler::eventEOF) {
		eTrace("[eRamServicePlay] ignoring eventEOF — watchdog handles lap/live-edge");
		return;
	}
	eDVBServicePlay::serviceEventTimeshift(event);
}

RESULT eRamServicePlay::stopTimeshift(bool swToLive) {
	if (!m_timeshift_enabled)
		return -1;

	// Stop watchdog first — prevents callbacks on partially torn-down state.
	if (m_watchdog_timer) {
		m_watchdog_timer->stop();
		m_watchdog_timer = nullptr;
	}
	resetRecoveryState();

	if (m_record) {
		// Stop the push thread BEFORE releasing the source to avoid a
		// use-after-free: eFilePushThread holds a raw pointer to the source
		// and may be mid-read.
		m_record->stop();
		if (m_timeshift_csa_session) {
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_record = 0;
	}

	// Safe to release now — push thread is guaranteed stopped (stop() joins).
	m_ts_source = nullptr;
	m_ram_recorder = nullptr;
	m_ram_ring.reset();
	m_timeshift_enabled = 0;

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "0");
	CFile::writeStr("/proc/stb/lcd/symbol_record", "0");

	::unlink("/tmp/ram_timeshift.ap");
	m_timeshift_file.clear();

	if (swToLive)
		switchToLive();

	eDebug("[eRamServicePlay] stopped");
	return 0;
}

RESULT eRamServicePlay::seekTo(pts_t to) {
	// Seek disabled for RAM timeshift to prevent issues with 4K channels
	// and to offload PCR history searches. Does not affect PRS.
	if (m_timeshift_active && m_ram_recorder) {
		eTrace("[eRamServicePlay] seekTo: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekTo(to);
}

RESULT eRamServicePlay::seekRelative(int direction, pts_t to) {
	// Seek disabled for RAM timeshift to prevent issues with 4K channels
	// and to offload PCR history searches. Does not affect PRS.
	if (m_timeshift_active && m_ram_recorder) {
		eTrace("[eRamServicePlay] seekRelative: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekRelative(direction, to);
}

RESULT eRamServicePlay::saveTimeshiftFile() {
	// RAM timeshift has no disk file to save.
	return 0;
}

ePtr<iTsSource> eRamServicePlay::createTsSource(eServiceReferenceDVB& ref, int /*packetsize*/) {
	if (!m_ram_ring)
		return eDVBServicePlay::createTsSource(ref);
	eRamTsSource* src = new eRamTsSource(m_ram_ring);
	m_ts_source = src;
	return ePtr<iTsSource>(src);
}

// Returns total elapsed time from recording start, not just the buffered window,
// so the seekbar stays consistent with getPlayPosition() (both use m_first_pts).
RESULT eRamServicePlay::getLength(pts_t& len) {
	if (!m_ram_recorder)
		return eDVBServicePlay::getLength(len);

	pts_t first_pts = 0, last_pts = 0;
	if (m_record->getFirstPTS(first_pts) != 0)
		return -1;
	if (m_record->getCurrentPCR(last_pts) != 0)
		return -1;

	pts_t d = pts_delta(last_pts, first_pts);
	if (d <= 0)
		return -1;
	len = d;
	return 0;
}

// Returns RELATIVE position (decoder PTS delta from first PTS) to match
// disk-timeshift behaviour and keep pos/len on the same reference for the seekbar.
RESULT eRamServicePlay::getPlayPosition(pts_t& pos) {
	if (!m_timeshift_active || !m_ram_recorder || !m_decoder || !m_record)
		return eDVBServicePlay::getPlayPosition(pos);

	// Freeze play position only when decoder is actually paused during recovery.
	// While the decoder is still consuming valid buffer data (m_is_paused == 0),
	// let getPlayPosition() advance normally so the seekbar tracks the video.
	if (m_stream_corruption_detected && m_is_paused) {
		pos = m_frozen_play_position;
		return 0;
	}

	pts_t first_pts = 0;
	if (m_record->getFirstPTS(first_pts) != 0)
		return -1;
	
	pts_t dec = 0;
	if (m_decoder->getPTS(0, dec) != 0)
		if (m_decoder->getPTS(1, dec) != 0)
			return -1;
	
	dec &= 0x1FFFFFFFF;          // Enforce 33-bit wrap-around
	pos = pts_delta(dec, first_pts);
	return 0;
}

bool eRamServicePlay::isRamBufferReady() const {
	return m_ram_ring && m_ram_ring->getWriteOffset() > 0;
}

float eRamServicePlay::ramBufferedSeconds() const {
	return m_ram_ring ? (float)(m_ram_ring->bufferedMs() / 1000.0) : 0.f;
}

int eRamServicePlay::ramFillPercent() const {
	if (!m_ram_ring)
		return 0;
	off_t filled = m_ram_ring->getWriteOffset() - m_ram_ring->getMinOffset();
	return (int)(filled * 100 / (off_t)(m_capacity_bytes));
}

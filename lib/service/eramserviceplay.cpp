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
	m_frozen_play_position.store(0, std::memory_order_relaxed);
	m_late_pause_logged.store(false, std::memory_order_relaxed);

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

	// RTTI is disabled (-fno-rtti); use static_cast
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

	// Connect ramCorrupt for drain-first handling
	ram_rec->ramCorrupt.connect(sigc::mem_fun(*this, &eRamServicePlay::onRamCorrupt));

	// Connect record events (eventStreamCorrupt blocked in recordEvent override)
	m_record->connectEvent(sigc::mem_fun(*this, &eRamServicePlay::recordEvent), m_con_record_event);

	if (m_csa_session && m_csa_session->isActive()) {
		eServiceReferenceDVB dvb_ref = (eServiceReferenceDVB&)m_reference;
		m_timeshift_csa_session = new eDVBCSASession(dvb_ref);
		if (m_timeshift_csa_session && m_timeshift_csa_session->init()) {
			m_timeshift_csa_session->forceActivate();
			m_record->setDescrambler(static_cast<iServiceScrambled*>(m_timeshift_csa_session.operator->()));
		}
	}

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

	m_watchdog_timer = eTimer::create(eApp);
	m_watchdog_timer->timeout.connect(sigc::mem_fun(*this, &eRamServicePlay::checkLapAndSeek));
	m_watchdog_timer->start(200, false);
	return 0;
}

// ============================================================================
// Watchdog — lap detection + late-pause (drain-first)
// ============================================================================
void eRamServicePlay::checkLapAndSeek() {
	if (!m_timeshift_active)
		return;

	ePtr<eRamTsSource> src = m_ts_source;
	if (!src)
		return;

	// --- Late-pause: drain-first during corruption ---
	if (m_stream_corruption_detected && m_decoder && !m_is_paused) {
		pts_t dec_pts = 0, first_pts = 0;
		if (m_decoder->getPTS(0, dec_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0) {
			dec_pts &= 0x1FFFFFFFF;
			pts_t dec_relative = pts_delta(dec_pts, first_pts);

			pts_t live_pts = 0;
			if (m_record->getCurrentPCR(live_pts) == 0) {
				pts_t live_relative = pts_delta(live_pts, first_pts);
				pts_t current_delay = pts_delta(live_relative, dec_relative);

				// Log once
				if (!m_late_pause_logged.load(std::memory_order_relaxed)) {
					eWarning("[eRamServicePlay] DRAINING: delay=%.2fs", current_delay / 90000.0);
					m_late_pause_logged.store(true, std::memory_order_relaxed);
				}

				// When delay < 500ms → decoder drained to live edge → pause now.
				// Update m_frozen_play_position to the actual drain endpoint
				// so startPreciseRecoveryCheck waits from this position,
				// not from the pre-drain position captured at corruption start.
				if (current_delay <= 500 * 90) {
					// Freeze the push thread BEFORE pausing the decoder so
					// its ring read offset stays at the drain endpoint.
					// unfreeze() is called in startPreciseRecoveryCheck just
					// before unpause(), letting the push thread resume from
					// exactly this offset and restoring the original delay.
					src->freeze();
					eWarning("[eRamServicePlay] LATE PAUSE: delay=%.2fs", current_delay / 90000.0);
					eWarning("[DIAG-2] late_pause: current=%.2fs dec_rel=%.2fs live_rel=%.2fs frozen_before=%.2fs", current_delay / 90000.0, dec_relative / 90000.0, live_relative / 90000.0,
							 m_frozen_play_position.load(std::memory_order_relaxed) / 90000.0);
					m_frozen_play_position.store(dec_relative, std::memory_order_relaxed);
					eWarning("[DIAG-2] frozen_pos updated to=%.2fs", m_frozen_play_position.load(std::memory_order_relaxed) / 90000.0);
					m_decoder->pause();
					m_is_paused = 1;
				}
			}
		}
		return; // Don't do lap detection while draining
	}

	// --- Lap detection (normal operation) ---
	if (m_stream_corruption_detected)
		return; // Skip lap detection during recovery

	off_t lapped_at = 0;
	if (!src->getLappedOffset(lapped_at))
		return;

	if (!m_ram_ring)
		return;

	off_t min_off = m_ram_ring->getMinOffset();
	off_t safe = min_off + (188 - min_off % 188) % 188;
	eDebug("[eRamServicePlay] watchdog: lap at %lld, jumping to min_off=%lld", (long long)lapped_at, (long long)safe);

	ePtr<iDVBPVRChannel> pvr_channel;
	if (m_service_handler_timeshift.getPVRChannel(pvr_channel) == 0)
		pvr_channel->forceSourcePosition(safe);
}

// ============================================================================
// onRamCorrupt — fingerprint only, NO pause
// ============================================================================
void eRamServicePlay::onRamCorrupt() {
	// Guard: ignore repeated calls
	if (m_stream_corruption_detected) {
		return;
	}

	eWarning("[RAM] CORRUPT detected");

	if (m_ts_source && m_ram_ring) {
		off_t read_off = m_ts_source->getLastReadOffset();
		off_t write_off = m_ram_ring->getWriteOffset();
		off_t min_off = m_ram_ring->getMinOffset();
		eWarning("[RAM] CORRUPT read_offset=%lld write_offset=%lld buffered_bytes=%lld", (long long)read_off, (long long)write_off, (long long)(write_off - min_off));
	}

	// Capture fingerprint BEFORE setting the flag — getPlayPosition() returns
	// m_frozen_play_position (=0) once the flag is set, so order matters.
	// Use same relative calculation as checkLapAndSeek: both dec_pts and
	// live_pts are absolute stream timestamps, subtract first_pts to make
	// them relative to the start of the recording, then take the difference.
	if (m_decoder && m_record) {
		pts_t dec_pts = 0, first_pts = 0, live_pts = 0;
		if (m_decoder->getPTS(0, dec_pts) == 0 && m_record->getFirstPTS(first_pts) == 0 && m_record->getCurrentPCR(live_pts) == 0) {
			pts_t dec_rel = pts_delta(dec_pts, first_pts);
			pts_t live_rel = pts_delta(live_pts, first_pts);
			if (live_rel > dec_rel) {
				m_original_timeshift_delay = pts_delta(live_rel, dec_rel);
				m_delay_calculated = true;
				m_frozen_play_position.store(dec_rel, std::memory_order_relaxed); // relative — matches getPlayPosition() format
				eWarning("[eRamServicePlay] onRamCorrupt fingerprint: delay=%.2fs", m_original_timeshift_delay / 90000.0);
				eWarning("[DIAG-1] corruption: original_delay=%.2fs frozen_pos=%.2fs", m_original_timeshift_delay / 90000.0, m_frozen_play_position.load(std::memory_order_relaxed) / 90000.0);
			}
		}
	}

	// Set flag AFTER captures — watchdog will do late-pause
	m_stream_corruption_detected = true;
	m_late_pause_logged.store(false, std::memory_order_relaxed);

	// Start PRS timer — base class will call startPreciseRecoveryCheck()
	m_precise_recovery_timer->start(100, false);
}

// ============================================================================
// handleEofRecovery — override: fingerprint only, NO pause
// ============================================================================
void eRamServicePlay::handleEofRecovery() {
	eWarning("[eRamServicePlay] handleEofRecovery: fingerprint only (no pause)");

	// Capture fingerprint — same relative calculation as checkLapAndSeek
	if (m_decoder && m_record) {
		pts_t dec_pts = 0, first_pts = 0, live_pts = 0;
		if (m_decoder->getPTS(0, dec_pts) == 0 && m_record->getFirstPTS(first_pts) == 0 && m_record->getCurrentPCR(live_pts) == 0) {
			pts_t dec_rel = pts_delta(dec_pts, first_pts);
			pts_t live_rel = pts_delta(live_pts, first_pts);
			if (live_rel > dec_rel) {
				m_original_timeshift_delay = pts_delta(live_rel, dec_rel);
				m_delay_calculated = true;
				m_frozen_play_position.store(dec_rel, std::memory_order_relaxed); // relative — matches getPlayPosition() format
				eWarning("[eRamServicePlay] handleEofRecovery fingerprint: delay=%.2fs", m_original_timeshift_delay / 90000.0);
			}
		}
	}

	// Set flag — watchdog will do late-pause
	m_stream_corruption_detected = true;
	m_late_pause_logged.store(false, std::memory_order_relaxed);

	// Start PRS timer
	m_precise_recovery_timer->start(100, false);

	// NO pause — let decoder drain first
}

// ============================================================================
// startPreciseRecoveryCheck — override: relative formula
// ============================================================================
// Base class uses live_pts(absolute) - getPlayPosition()(relative) which gives
// a huge wrong value. We override to use consistent relative values so the
// recovery fires exactly when the ring buffer has accumulated original_delay
// worth of content after the decoder's paused position.
void eRamServicePlay::startPreciseRecoveryCheck() {
	if (!m_stream_corruption_detected || !m_record) {
		m_precise_recovery_timer->stop();
		return;
	}

	pts_t live_pts = 0;
	if (m_record->getCurrentPCR(live_pts) != 0 || live_pts == 0) {
		// Signal not yet recovered — keep waiting
		m_precise_recovery_timer->start(100, false);
		return;
	}

	pts_t first_pts = 0;
	if (m_record->getFirstPTS(first_pts) != 0) {
		m_precise_recovery_timer->start(100, false);
		return;
	}

	if (!m_delay_calculated) {
		// Fingerprint not captured yet (e.g. signal was dead at corruption time)
		// Try now using the same relative formula
		if (m_decoder) {
			pts_t dec_pts = 0;
			if (m_decoder->getPTS(0, dec_pts) == 0) {
				dec_pts &= 0x1FFFFFFFF;
				pts_t dec_rel = pts_delta(dec_pts, first_pts);
				pts_t live_rel = pts_delta(live_pts, first_pts);
				if (live_rel > dec_rel) {
					m_original_timeshift_delay = pts_delta(live_rel, dec_rel);
					m_frozen_play_position.store(dec_rel, std::memory_order_relaxed);
					m_delay_calculated = true;
					eWarning("[eRamServicePlay] PRS late fingerprint: delay=%.2fs", m_original_timeshift_delay / 90000.0);
				}
			}
		}
		if (!m_delay_calculated) {
			m_precise_recovery_timer->start(100, false);
			return;
		}
	}

	// Both values relative to first_pts — consistent with getPlayPosition().
	// m_frozen_play_position was updated at late-pause time in checkLapAndSeek,
	// so it reflects where the decoder stopped after draining.
	pts_t live_rel = pts_delta(live_pts, first_pts);
	pts_t current_delay = pts_delta(live_rel, m_frozen_play_position.load(std::memory_order_relaxed));

	int recovery_delay_ms = eSimpleConfig::getInt("config.timeshift.recoveryBufferDelay", 300);
	pts_t target = m_original_timeshift_delay + (pts_t)(recovery_delay_ms * 90);

	eDebug("[eRamServicePlay] PRS: current=%.2fs target=%.2fs", current_delay / 90000.0, target / 90000.0);
	eWarning("[DIAG-3] PRS: current=%.2fs target=%.2fs frozen=%.2fs original=%.2fs", current_delay / 90000.0, target / 90000.0, m_frozen_play_position.load(std::memory_order_relaxed) / 90000.0,
			 m_original_timeshift_delay / 90000.0);

	if (current_delay >= target) {
		m_precise_recovery_timer->stop();
		// Unfreeze before resetRecoveryState / unpause so the push
		// thread resumes from the frozen offset, not the live edge.
		ePtr<eRamTsSource> src = m_ts_source;
		if (src)
			src->unfreeze();
		resetRecoveryState();
		m_late_pause_logged.store(false, std::memory_order_relaxed);
		if (m_is_paused) {
			pts_t d2 = 0, f2 = 0;
			if (m_decoder && m_decoder->getPTS(0, d2) == 0 && m_record->getFirstPTS(f2) == 0) {
				pts_t dec_rel_now = pts_delta(d2 & 0x1FFFFFFFF, f2);
				pts_t eff_delay = pts_delta(live_rel, dec_rel_now);
				eWarning("[DIAG-4] unpause: live=%.2fs dec=%.2fs eff_delay=%.2fs", live_rel / 90000.0, dec_rel_now / 90000.0, eff_delay / 90000.0);
			}
			unpause();
		}
		m_event((iPlayableService*)this, evSeekableStatusChanged);
	} else {
		m_precise_recovery_timer->start(100, false);
	}
}


void eRamServicePlay::recordEvent(int event) {
	if (event == iDVBTSRecorder::eventStreamCorrupt) {
		// BLOCK: Don't let base class do immediate pause
		if (m_ram_recorder) {
			eDebug("[eRamServicePlay] BLOCKING eventStreamCorrupt (RAM mode)");
			return;
		}
		eDVBServicePlay::recordEvent(event);
		return;
	}
	eDVBServicePlay::recordEvent(event);
}

// ============================================================================
// serviceEventTimeshift — block EOF during recovery
// ============================================================================
void eRamServicePlay::serviceEventTimeshift(int event) {
	if (event == eDVBServicePMTHandler::eventEOF) {
		if (m_stream_corruption_detected) {
			eDebug("[eRamServicePlay] Blocking EOF during recovery");
			return;
		}
		eDebug("[eRamServicePlay] Ignoring EOF — live edge");
		return;
	}
	eDVBServicePlay::serviceEventTimeshift(event);
}

// ============================================================================
// Stop Timeshift
// ============================================================================
RESULT eRamServicePlay::stopTimeshift(bool swToLive) {
	if (!m_timeshift_enabled)
		return -1;

	if (m_watchdog_timer) {
		m_watchdog_timer->stop();
		m_watchdog_timer = nullptr;
	}

	// Ensure push thread is not frozen before teardown.
	ePtr<eRamTsSource> src = m_ts_source;
	if (src)
		src->unfreeze();

	resetRecoveryState();
	m_late_pause_logged.store(false, std::memory_order_relaxed);

	if (m_record) {
		m_record->stop();
		if (m_timeshift_csa_session) {
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_record = 0;
	}

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

// ============================================================================
// Seek — disabled for RAM timeshift
// ============================================================================
RESULT eRamServicePlay::seekTo(pts_t to) {
	if (m_timeshift_active && m_ram_recorder) {
		eDebug("[eRamServicePlay] seekTo: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekTo(to);
}

RESULT eRamServicePlay::seekRelative(int direction, pts_t to) {
	if (m_timeshift_active && m_ram_recorder) {
		eDebug("[eRamServicePlay] seekRelative: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekRelative(direction, to);
}

// ============================================================================
// Unpause — abort recovery
// ============================================================================
RESULT eRamServicePlay::unpause() {
	if (m_stream_corruption_detected) {
		eWarning("[eRamServicePlay] User unpaused during recovery. Aborting.");
		ePtr<eRamTsSource> src = m_ts_source;
		if (src)
			src->unfreeze();
		resetRecoveryState();
		m_late_pause_logged.store(false, std::memory_order_relaxed);
	}
	return eDVBServicePlay::unpause();
}

RESULT eRamServicePlay::saveTimeshiftFile() {
	return 0;
}

// ============================================================================
// Source creation
// ============================================================================
ePtr<iTsSource> eRamServicePlay::createTsSource(eServiceReferenceDVB& ref, int /*packetsize*/) {
	if (!m_ram_ring)
		return eDVBServicePlay::createTsSource(ref);

	eRamTsSource* src = new eRamTsSource(m_ram_ring);
	m_ts_source = src;
	return ePtr<iTsSource>(src);
}

// ============================================================================
// Length / Position
// ============================================================================
RESULT eRamServicePlay::getLength(pts_t& len) {
	if (!m_ram_recorder || !m_record)
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

RESULT eRamServicePlay::getPlayPosition(pts_t& pos) {
	if (!m_timeshift_active || !m_ram_recorder || !m_decoder || !m_record)
		return eDVBServicePlay::getPlayPosition(pos);

	// During corruption, return frozen position
	if (m_stream_corruption_detected) {
		pos = m_frozen_play_position.load(std::memory_order_relaxed);
		return 0;
	}

	pts_t first_pts = 0;
	if (m_record->getFirstPTS(first_pts) != 0)
		return -1;

	pts_t dec = 0;
	if (m_decoder->getPTS(0, dec) != 0)
		if (m_decoder->getPTS(1, dec) != 0)
			return -1;

	dec &= 0x1FFFFFFFF;
	pos = pts_delta(dec, first_pts);
	return 0;
}

// ============================================================================
// Status helpers
// ============================================================================
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

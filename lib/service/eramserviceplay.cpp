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
	m_delay_state.store(RamDelayState::NORMAL, std::memory_order_relaxed);
	m_original_timeshift_delay.store(0, std::memory_order_relaxed);
	m_frozen_play_position.store(0, std::memory_order_relaxed);
	m_recovery_first_pts.store(0, std::memory_order_relaxed);
	m_exhaustion_live_pts.store(0, std::memory_order_relaxed);
	m_signal_present.store(false, std::memory_order_relaxed);
	m_recovery_captured.store(false, std::memory_order_relaxed);
	m_fingerprint_pending.store(false, std::memory_order_relaxed);
	m_drain_start_ms.store(0, std::memory_order_relaxed);

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

	eDVBTSRecorder* recorder = static_cast<eDVBTSRecorder*>(m_record.operator->());
	if (!recorder) {
		eWarning("[eRamServicePlay] Failed to get recorder - "
				 "RAM timeshift aborted");
		m_ram_ring.reset();
		m_record = 0;
		return -3;
	}

	eRamRecorder* ram_rec = new eRamRecorder(m_ram_ring.get(), 188);
	m_ram_recorder = ram_rec;
	recorder->replaceThread(ram_rec);
	m_record->setTargetFD(-1);

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
// Watchdog — lap detection + phase-locked drain-first recovery
// ============================================================================

void eRamServicePlay::checkLapAndSeek() {
	if (!m_timeshift_active)
		return;

	ePtr<eRamTsSource> src = m_ts_source;
	if (!src)
		return;

	RamDelayState state = m_delay_state.load(std::memory_order_acquire);

	// ----------------------------------------------------------------
	// Retry fingerprint capture if corruption flagged but not yet captured.
	// This is a SIDE-EFFECT, not an early return: the rest of the watchdog
	// continues below so exhaustion detection, gate close, and phase-lock
	// all keep running even while the fingerprint is pending.
	// ----------------------------------------------------------------
	if (state == RamDelayState::STARVED && m_fingerprint_pending.load(std::memory_order_relaxed)) {
		pts_t live_pts = 0;
		pts_t first_pts = 0;

		if (m_record && m_record->getCurrentPCR(live_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0) {
			pts_t dec_relative = 0;
			if (m_decoder && m_decoder->getPTS(0, dec_relative) == 0) {
				dec_relative &= 0x1FFFFFFFF;
				dec_relative = pts_delta(dec_relative, first_pts);
				pts_t live_relative = pts_delta(live_pts, first_pts);
				pts_t delay = pts_delta(live_relative, dec_relative);
				m_original_timeshift_delay.store(delay, std::memory_order_relaxed);
				m_fingerprint_pending.store(false, std::memory_order_relaxed);
				eTrace("[eRamServicePlay] Fingerprint captured (relative): "
					   "live_rel=%lld dec_rel=%lld delay=%lld PTS (%.2fs)",
					   (long long)live_relative, (long long)dec_relative, (long long)delay, delay / 90000.0);
			} else {
				eTrace("[eRamServicePlay] Fingerprint not ready yet, retrying...");
			}
		}

		// Bailout: if the decoder never delivers a PTS (dead decoder,
		// broken stream), the fingerprint stays pending indefinitely and
		// the buffer silently overflows.  After 5s use bufferedMs() as a
		// best-effort fallback so the state machine can continue.
		if (m_fingerprint_pending.load(std::memory_order_relaxed)) {
			uint64_t start = m_drain_start_ms.load(std::memory_order_relaxed);
			if (start > 0 && (uint64_t)eRamRingBuffer::nowMs() - start > 5000) {
				pts_t best_effort = m_ram_ring ? (pts_t)(m_ram_ring->bufferedMs()) * 90 : 10 * 90000;
				m_original_timeshift_delay.store(best_effort, std::memory_order_relaxed);
				m_fingerprint_pending.store(false, std::memory_order_relaxed);
				eWarning("[eRamServicePlay] Fingerprint timeout (5s). "
						 "Using best-effort delay: %.2fs",
						 best_effort / 90000.0);
			}
		}
		// No early return — fall through to the full watchdog logic below.
	}

	// ----------------------------------------------------------------
	// 1. Ring buffer lap detection (skip during recovery)
	// ----------------------------------------------------------------
	if (state != RamDelayState::STARVED && state != RamDelayState::DRAINING) {
		off_t lapped_at = 0;
		if (src->getLappedOffset(lapped_at)) {
			if (m_ram_ring) {
				off_t min_off = m_ram_ring->getMinOffset();
				off_t safe = min_off + (188 - min_off % 188) % 188;
				eDebug("[eRamServicePlay] watchdog: lap at %lld, "
					   "jumping to min_off=%lld",
					   (long long)lapped_at, (long long)safe);
				ePtr<iDVBPVRChannel> pvr_channel;
				if (m_service_handler_timeshift.getPVRChannel(pvr_channel) == 0) {
					pvr_channel->forceSourcePosition(safe);
				}
			}
			m_delay_state.store(RamDelayState::NORMAL, std::memory_order_release);
			src->setGateClosed(false);
			return;
		}
	}

	// ----------------------------------------------------------------
	// 2. STARVED state: decoder is draining the remaining buffer.
	//
	// Phase-lock tracking with signal flap detection:
	// Capture recovery_first_pts at the FIRST moment signal returns,
	// but INVALIDATE it if signal is lost again before DRAINING begins.
	// This prevents building delay on a stale/phantom recovery window.
	// ----------------------------------------------------------------
	if (state == RamDelayState::STARVED) {
		bool gate_is_closed = src->isGateClosed();

		if (!gate_is_closed && src->isExhausted()) {
			eTrace("[eRamServicePlay] Source reports exhaustion (live edge). "
				   "Closing gate + pausing decoder (late freeze).");
			src->setGateClosed(true);
			src->clearExhausted();
			gate_is_closed = true;

			/* Record the live edge PTS at exhaustion.
			 * missing_gap = pts_delta(exhaustion_live_pts, recovery_first_pts)
			 * This is the only interval the DRAINING phase needs to refill —
			 * the remaining (original_delay - gap) was already buffered
			 * while the decoder drained the old data. */
			pts_t exhaustion_live = 0;
			if (m_record && m_record->getCurrentPCR(exhaustion_live) == 0)
				m_exhaustion_live_pts.store(exhaustion_live, std::memory_order_relaxed);

			pts_t dec_pts = 0;
			pts_t first_pts = 0;
			if (m_decoder && m_decoder->getPTS(0, dec_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0) {
				dec_pts &= 0x1FFFFFFFF;
				m_frozen_play_position.store(pts_delta(dec_pts, first_pts), std::memory_order_relaxed);
			}

			if (m_decoder && !m_is_paused) {
				m_decoder->pause();
				m_is_paused = 1;
				eTrace("[eRamServicePlay] Decoder paused at exhaustion.");
			}
		}

		pts_t current_live_pts = 0;
		bool signal_ok = (m_record && m_record->getCurrentPCR(current_live_pts) == 0 && current_live_pts != 0);

		// Phase-lock: detect signal edges with flap invalidation
		if (!m_signal_present.load(std::memory_order_relaxed) && signal_ok) {
			// RISING EDGE: first signal after loss
			m_signal_present.store(true, std::memory_order_relaxed);
			if (!m_recovery_captured.load(std::memory_order_relaxed)) {
				pts_t recovery_pts = 0;
				if (m_record && m_record->getCurrentPCR(recovery_pts) == 0) {
					m_recovery_first_pts.store(recovery_pts, std::memory_order_relaxed);
					m_recovery_captured.store(true, std::memory_order_relaxed);
					eTrace("[eRamServicePlay] Phase-lock: rising edge, "
						   "first_new_pts=%lld",
						   (long long)recovery_pts);
				}
			}
		} else if (m_signal_present.load(std::memory_order_relaxed) && !signal_ok) {
			// FALLING EDGE: signal lost again before DRAINING
			// INVALIDATE the recovery boundary — it was premature.
			// The next rising edge will establish a fresh boundary.
			m_signal_present.store(false, std::memory_order_relaxed);
			if (m_recovery_captured.load(std::memory_order_relaxed)) {
				m_recovery_captured.store(false, std::memory_order_relaxed);
				m_recovery_first_pts.store(0, std::memory_order_relaxed);
				eTrace("[eRamServicePlay] Phase-lock: falling edge, "
					   "recovery boundary invalidated (signal flap)");
			}
		}

		if (gate_is_closed) {
			if (signal_ok && m_recovery_captured.load(std::memory_order_relaxed)) {
				eTrace("[eRamServicePlay] Signal recovered while gate "
					   "CLOSED -> DRAINING.");
				// Stamp DRAINING entry time for 30s timeout safety.
				m_drain_start_ms.store((uint64_t)eRamRingBuffer::nowMs(), std::memory_order_relaxed);
				m_delay_state.store(RamDelayState::DRAINING, std::memory_order_release);
			}
		} else {
			if (signal_ok) {
				eTrace("[eRamServicePlay] Signal recovered before gate "
					   "closed. Continuing drain to preserve exact delay.");
			}
		}
	}

	// ----------------------------------------------------------------
	// 3. DRAINING state: signal is back, buffer is filling.
	//
	// CRITICAL: After PCR discontinuity, live - frozen includes the gap.
	// We must also ensure actual new data (live - recovery_first) >= target.
	//
	// Using recovery_first captured at signal onset (not gate close)
	// preserves the phase offset: final_delay = target + gap_only,
	// not target + gap + drain_time.
	// ----------------------------------------------------------------
	if (state == RamDelayState::DRAINING) {
		// ---- DRAINING timeout safety (30s) ----
		// If PCR stops advancing (frozen tuner, dropped lock without
		// getCurrentPCR() failing), current_delay never grows and the
		// resume condition is never met → user sees a permanently paused
		// decoder.  Force-resume after 30s as a last resort.
		{
			uint64_t drain_start = m_drain_start_ms.load(std::memory_order_relaxed);
			if (drain_start > 0 && (uint64_t)eRamRingBuffer::nowMs() - drain_start > 30000) {
				eWarning("[eRamServicePlay] DRAINING timeout (30s). "
						 "Forcing resume to prevent permanent freeze.");

				m_delay_state.store(RamDelayState::NORMAL, std::memory_order_release);
				m_fingerprint_pending.store(false, std::memory_order_relaxed);
				m_original_timeshift_delay.store(0, std::memory_order_relaxed);
				m_frozen_play_position.store(0, std::memory_order_relaxed);
				m_recovery_first_pts.store(0, std::memory_order_relaxed);
				m_exhaustion_live_pts.store(0, std::memory_order_relaxed);
				m_signal_present.store(false, std::memory_order_relaxed);
				m_recovery_captured.store(false, std::memory_order_relaxed);
				m_drain_start_ms.store(0, std::memory_order_relaxed);

				// Open gate BEFORE decoder unpause so data flows
				// immediately when the decoder resumes.
				src->setGateClosed(false);
				if (m_decoder && m_is_paused)
					unpause();
				return;
			}
		}

		// ---- Signal re-loss rollback: DRAINING → STARVED ----
		// If signal is lost again during DRAINING, return to STARVED
		// WITHOUT touching m_original_timeshift_delay or m_frozen_play_position.
		// Those represent the original phase fingerprint and must survive
		// multiple recovery flaps.
		pts_t check_pts = 0;
		bool signal_ok = (m_record && m_record->getCurrentPCR(check_pts) == 0 && check_pts != 0);
		if (!signal_ok) {
			eWarning("[eRamServicePlay] Signal lost again during DRAINING. "
					 "Returning to STARVED state.");
			m_delay_state.store(RamDelayState::STARVED, std::memory_order_release);
			m_recovery_captured.store(false, std::memory_order_relaxed);
			m_recovery_first_pts.store(0, std::memory_order_relaxed);
			m_signal_present.store(false, std::memory_order_relaxed);
			return;
		}

		pts_t current_live_pts = 0;
		pts_t first_pts = 0;
		if (m_record && m_record->getCurrentPCR(current_live_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0 && current_live_pts > 0) {
			pts_t live_relative = pts_delta(current_live_pts, first_pts);
			pts_t frozen_relative = m_frozen_play_position.load(std::memory_order_relaxed);

			pts_t current_delay = pts_delta(live_relative, frozen_relative);

			/* Incremental Phase Compensation:
			 * We only need to refill the missing gap — NOT the full original
			 * delay.  While the decoder drained the old buffer (e.g. 176s),
			 * the recorder was already writing new data.  At exhaustion the
			 * buffer already contains ~176s of new data.  The only missing
			 * piece is the gap interval itself (e.g. 4s).
			 *
			 * missing_gap = pts_delta(exhaustion_live_pts, recovery_first_pts)
			 *
			 * This gives:
			 *   outage 1s  → freeze ~1s  → resume immediately
			 *   outage 4s  → freeze ~4s  → resume immediately
			 *   outage 20s → freeze ~20s → resume immediately
			 * while preserving the original delay exactly. */
			pts_t exhaustion_pts = m_exhaustion_live_pts.load(std::memory_order_relaxed);
			pts_t recovery_pts = m_recovery_first_pts.load(std::memory_order_relaxed);

			pts_t missing_gap = 0;
			if (exhaustion_pts > 0 && recovery_pts > 0)
				missing_gap = pts_delta(exhaustion_pts, recovery_pts);

			pts_t new_buffer_duration = 0;
			if (recovery_pts > 0) {
				pts_t recovery_relative = pts_delta(recovery_pts, first_pts);
				new_buffer_duration = pts_delta(live_relative, recovery_relative);
			}

			/* Fallback: if phase-lock data is unavailable, use original delay */
			pts_t required_refill = (missing_gap > 0) ? missing_gap : m_original_timeshift_delay.load(std::memory_order_relaxed);

			if (required_refill == 0) {
				const pts_t MIN_FALLBACK = 3 * 90000;
				required_refill = std::max(new_buffer_duration, MIN_FALLBACK);
				eWarning("[eRamServicePlay] Phase-lock data unavailable. "
						 "Using fallback refill: %lld PTS (%.2fs)",
						 (long long)required_refill, required_refill / 90000.0);
			}

			eTrace("[eRamServicePlay] DRAINING: current_delay=%lld "
				   "new_buffer=%lld missing_gap=%lld required_refill=%lld",
				   (long long)current_delay, (long long)new_buffer_duration, (long long)missing_gap, (long long)required_refill);

			if (current_delay >= m_original_timeshift_delay.load(std::memory_order_relaxed) && new_buffer_duration >= required_refill) {
				eTrace("[eRamServicePlay] Delay restored via incremental "
					   "phase compensation: gap=%.2fs refilled=%.2fs. "
					   "Resuming playback.",
					   missing_gap / 90000.0, new_buffer_duration / 90000.0);

				m_delay_state.store(RamDelayState::NORMAL, std::memory_order_release);
				m_fingerprint_pending.store(false, std::memory_order_relaxed);
				m_recovery_first_pts.store(0, std::memory_order_relaxed);
				m_exhaustion_live_pts.store(0, std::memory_order_relaxed);
				m_signal_present.store(false, std::memory_order_relaxed);
				m_recovery_captured.store(false, std::memory_order_relaxed);
				m_drain_start_ms.store(0, std::memory_order_relaxed);

				// Open gate BEFORE decoder unpause: the push thread must
				// be feeding data by the time the decoder starts consuming.
				src->setGateClosed(false);

				if (m_decoder && m_is_paused) {
					unpause();
					eTrace("[eRamServicePlay] Decoder resumed via unpause().");
				}
			}
		}
	}
}

// ============================================================================
// recordEvent — EARLY FINGERPRINTING at corruption onset (RELATIVE MODEL)
// ============================================================================

void eRamServicePlay::recordEvent(int event) {
	if (event == iDVBTSRecorder::eventStreamCorrupt) {
		// CAS: only allow NORMAL → STARVED.  During a prolonged outage
		// eventStreamCorrupt can fire multiple times.  Without this guard
		// each subsequent call overwrites m_original_timeshift_delay with
		// a stale measurement (decoder already paused → delay is growing),
		// destroying the original fingerprint.
		RamDelayState expected = RamDelayState::NORMAL;
		if (!m_delay_state.compare_exchange_strong(expected, RamDelayState::STARVED, std::memory_order_release, std::memory_order_relaxed)) {
			eTrace("[eRamServicePlay] recordEvent: already in state %d, "
				   "skipping.",
				   (int)expected);
			return;
		}

		// Clear stale m_exhausted: live-edge EAGAIN in NORMAL state can
		// set this flag during a normal live-edge stall.  If corruption
		// fires immediately after, the first STARVED watchdog tick sees
		// isExhausted()=true and closes the gate instantly — bypassing
		// the entire drain-first design.
		ePtr<eRamTsSource> src = m_ts_source;
		if (src)
			src->clearExhausted();

		// Stamp recovery start time used by the fingerprint bailout (5s)
		// in checkLapAndSeek.
		m_drain_start_ms.store((uint64_t)eRamRingBuffer::nowMs(), std::memory_order_relaxed);

		m_signal_present.store(false, std::memory_order_relaxed);
		m_recovery_captured.store(false, std::memory_order_relaxed);

		pts_t live_pts = 0;
		pts_t dec_pts = 0;
		pts_t first_pts = 0;

		if (m_record && m_record->getCurrentPCR(live_pts) == 0 && m_decoder && m_decoder->getPTS(0, dec_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0) {
			dec_pts &= 0x1FFFFFFFF;
			pts_t live_relative = pts_delta(live_pts, first_pts);
			pts_t dec_relative = pts_delta(dec_pts, first_pts);
			pts_t delay = pts_delta(live_relative, dec_relative);

			m_original_timeshift_delay.store(delay, std::memory_order_relaxed);

			m_fingerprint_pending.store(false, std::memory_order_relaxed);

			eTrace("[eRamServicePlay] Stream corruption detected (relative). "
				   "Captured delay fingerprint: %lld PTS (%.2fs). "
				   "Transitioning to STARVED (drain-first).",
				   (long long)delay, delay / 90000.0);
		} else {
			m_fingerprint_pending.store(true, std::memory_order_relaxed);
			eTrace("[eRamServicePlay] Stream corruption detected but "
				   "fingerprint not ready. Will retry...");
		}
	} else {
		eDVBServicePlay::recordEvent(event);
	}
}


// ============================================================================
// handleEofRecovery — centralized drain-first entry with CAS idempotency
// ============================================================================

void eRamServicePlay::handleEofRecovery() {
	RamDelayState expected = RamDelayState::NORMAL;
	if (!m_delay_state.compare_exchange_strong(expected, RamDelayState::STARVED, std::memory_order_release, std::memory_order_relaxed)) {
		eTrace("[eRamServicePlay] handleEofRecovery: already in state %d, "
			   "skipping.",
			   (int)expected);
		return;
	}

	eTrace("[eRamServicePlay] handleEofRecovery: transitioning to STARVED "
		   "(drain-first).");

	// Clear stale m_exhausted from normal live-edge stalls (same race
	// as in recordEvent — see comment there).
	ePtr<eRamTsSource> src_ref = m_ts_source;
	if (src_ref)
		src_ref->clearExhausted();

	// Stamp recovery start time for fingerprint timeout tracking.
	m_drain_start_ms.store((uint64_t)eRamRingBuffer::nowMs(), std::memory_order_relaxed);

	// Reset phase-lock tracking for this recovery cycle
	m_recovery_first_pts.store(0, std::memory_order_relaxed);
	m_signal_present.store(false, std::memory_order_relaxed);
	m_recovery_captured.store(false, std::memory_order_relaxed);

	pts_t live_pts = 0;
	pts_t dec_pts = 0;
	pts_t first_pts = 0;

	if (m_record && m_record->getCurrentPCR(live_pts) == 0 && m_decoder && m_decoder->getPTS(0, dec_pts) == 0 && m_record && m_record->getFirstPTS(first_pts) == 0) {
		dec_pts &= 0x1FFFFFFFF;
		pts_t live_relative = pts_delta(live_pts, first_pts);
		pts_t dec_relative = pts_delta(dec_pts, first_pts);
		pts_t delay = pts_delta(live_relative, dec_relative);

		m_original_timeshift_delay.store(delay, std::memory_order_relaxed);
		m_fingerprint_pending.store(false, std::memory_order_relaxed);
		eTrace("[eRamServicePlay] Captured delay fingerprint (relative): "
			   "%lld PTS (%.2fs)",
			   (long long)delay, delay / 90000.0);
	} else {
		m_fingerprint_pending.store(true, std::memory_order_relaxed);
		eTrace("[eRamServicePlay] handleEofRecovery: fingerprint not ready, "
			   "watchdog will retry.");
	}
}

// ============================================================================
// serviceEventTimeshift — block EOF during recovery
// ============================================================================

void eRamServicePlay::serviceEventTimeshift(int event) {
	if (event == eDVBServicePMTHandler::eventEOF) {
		RamDelayState state = m_delay_state.load(std::memory_order_acquire);
		if (state == RamDelayState::DRAINING || state == RamDelayState::STARVED) {
			eDebug("[eRamServicePlay] Blocking eventEOF during %s state "
				   "to maintain timeshift session.",
				   state == RamDelayState::DRAINING ? "DRAINING" : "STARVED");
			return;
		}
		eDebug("[eRamServicePlay] ignoring eventEOF in NORMAL state — "
			   "live edge reached.");
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

	m_delay_state.store(RamDelayState::NORMAL, std::memory_order_relaxed);
	m_original_timeshift_delay.store(0, std::memory_order_relaxed);
	m_frozen_play_position.store(0, std::memory_order_relaxed);
	m_recovery_first_pts.store(0, std::memory_order_relaxed);
	m_exhaustion_live_pts.store(0, std::memory_order_relaxed);
	m_signal_present.store(false, std::memory_order_relaxed);
	m_recovery_captured.store(false, std::memory_order_relaxed);
	m_fingerprint_pending.store(false, std::memory_order_relaxed);
	m_drain_start_ms.store(0, std::memory_order_relaxed);

	if (m_decoder && m_is_paused) {
		unpause();
	}

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
		eTrace("[eRamServicePlay] seekTo: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekTo(to);
}

RESULT eRamServicePlay::seekRelative(int direction, pts_t to) {
	if (m_timeshift_active && m_ram_recorder) {
		eTrace("[eRamServicePlay] seekRelative: disabled on RAM timeshift");
		return -1;
	}
	return eDVBServicePlay::seekRelative(direction, to);
}

// ============================================================================
// Unpause — manual abort of recovery cycle (user pressed Play during recovery)
// ============================================================================

RESULT eRamServicePlay::unpause() {
	RamDelayState state = m_delay_state.load(std::memory_order_acquire);
	if (state == RamDelayState::STARVED || state == RamDelayState::DRAINING) {
		eWarning("[eRamServicePlay] User unpaused during %s recovery. "
				 "Aborting RAM recovery cycle and opening gate.",
				 state == RamDelayState::STARVED ? "STARVED" : "DRAINING");

		// ---- Full state reset ----
		m_delay_state.store(RamDelayState::NORMAL, std::memory_order_release);
		m_fingerprint_pending.store(false, std::memory_order_relaxed);
		m_original_timeshift_delay.store(0, std::memory_order_relaxed);
		m_frozen_play_position.store(0, std::memory_order_relaxed);
		m_recovery_first_pts.store(0, std::memory_order_relaxed);
		m_signal_present.store(false, std::memory_order_relaxed);
		m_recovery_captured.store(false, std::memory_order_relaxed);
		m_drain_start_ms.store(0, std::memory_order_relaxed);

		// ---- Open gate BEFORE calling base unpause ----
		// This prevents decoder starvation: the push thread must
		// resume data flow immediately, not after the decoder leaves pause.
		if (m_ts_source) {
			m_ts_source->setGateClosed(false);
			eTrace("[eRamServicePlay] Gate opened for immediate resume.");
		}
	}

	// Delegate to base class for actual decoder unpause()
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
// Length / Position (RELATIVE MODEL — matches original stable behaviour)
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

	RamDelayState state = m_delay_state.load(std::memory_order_acquire);
	if (state == RamDelayState::STARVED || state == RamDelayState::DRAINING) {
		// During recovery, return the LATE-FROZEN RELATIVE position.
		// This ensures the seekbar matches the exact frame where the
		// decoder stopped. Early freeze would show e.g. 90s while the
		// decoder is actually at 100s, causing visual desync.
		pos = m_frozen_play_position.load(std::memory_order_relaxed);
		return 0;
	}

	// Normal operation: live relative position (same as original)
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

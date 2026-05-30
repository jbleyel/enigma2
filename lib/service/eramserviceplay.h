#ifndef __lib_service_eramserviceplay_h
#define __lib_service_eramserviceplay_h

#include <atomic>
#include <lib/base/ebase.h>
#include <lib/dvb/eramtimeshift.h>
#include <lib/service/servicedvb.h>
#include <memory>

// States to control delay synchronization during corruption recovery.
//
// NORMAL:   Standard streaming. Push thread reads from ring buffer,
//           decoder plays normally.
//
// STARVED:  Corruption detected (ramCorrupt signal or TuneFailed).
//           The decoder continues playing until the buffer is fully
//           drained (drain-first). Only then is the gate closed and
//           the decoder paused (late freeze). This preserves the
//           original delay when the signal returns.
//
// DRAINING: Signal has recovered and new data is filling the buffer.
//           We wait until both:
//             1. current_delay >= target_delay (decoder is far enough
//                behind live), AND
//             2. buffer_duration >= target_delay (buffer has enough data
//                to sustain the target without running dry).
//           Only then is the gate opened and playback resumed.
//
// The state machine ensures the exact original delay is rebuilt after
// any outage, preventing permanent delay reduction or live-edge jumps.
//
// ALL timing calculations use the RELATIVE model (pts_delta relative
// to first_pts), matching the original stable behaviour that has
// worked reliably on all hardware including HiSilicon.
enum class RamDelayState {
	NORMAL,
	STARVED,
	DRAINING
};

class eRamServicePlay : public eDVBServicePlay {
	DECLARE_REF(eRamServicePlay);

public:
	eRamServicePlay(const eServiceReference& ref, eDVBService* service, int delay_seconds = 10);
	~eRamServicePlay() override;

	// Status metrics for the UI and diagnostics.
	bool isRamBufferReady() const;
	float ramBufferedSeconds() const;
	int ramFillPercent() const;

	// PTS-based length and position for the seek bar.
	// Both use RELATIVE timing (pts_delta relative to first_pts),
	// matching the original stable model.
	RESULT getLength(pts_t& len) override;
	RESULT getPlayPosition(pts_t& pos) override;

	// Seek is disabled for RAM timeshift to avoid PCR history searches
	// and 4K channel issues. PRS (Precise Recovery System) is unaffected.
	RESULT seekTo(pts_t to) override;
	RESULT seekRelative(int direction, pts_t to) override;

	// Manual unpause during recovery: abort RAM recovery cycle and
	// open gate immediately to prevent decoder starvation.
	RESULT unpause() override;

	// Timeshift lifecycle.
	RESULT activateTimeshift() override;
	RESULT saveTimeshiftFile() override;
	void serviceEventTimeshift(int event) override;

	RESULT timeshift(ePtr<iTimeshiftService>& ptr) override {
		ptr = this;
		return 0;
	}

protected:
	RESULT startTimeshift() override;
	RESULT stopTimeshift(bool swToLive = false) override;
	ePtr<iTsSource> createTsSource(eServiceReferenceDVB& ref, int packetsize = 188) override;

	// Centralized drain-first recovery entry with CAS idempotency.
	void handleEofRecovery() override;

private:
	// 200ms watchdog: lap detection and drain-first state machine.
	void checkLapAndSeek();

	// Intercept eventStreamCorrupt for early fingerprint capture.
	// BLOCKS the event from reaching eDVBServicePlay to prevent
	// immediate decoder pause. Only non-corrupt events are delegated.
	void recordEvent(int event) override;

	// RAM-specific corruption handler — connected to eRamRecorder::ramCorrupt.
	// Bypasses eDVBServicePlay::recordEvent() completely. Enters STARVED
	// state for drain-first recovery without pausing the decoder.
	void onRamCorrupt();

	// 33-bit PTS delta with wrap-around handling.
	static inline pts_t pts_delta(pts_t newer, pts_t older) { return (newer - older) & ((1LL << 33) - 1); }

	// Ring buffer and source.
	std::shared_ptr<eRamRingBuffer> m_ram_ring;
	ePtr<eTimer> m_watchdog_timer;
	size_t m_capacity_bytes;
	ePtr<eRamTsSource> m_ts_source;
	eRamRecorder* m_ram_recorder;

	// ---- Recovery state machine (all atomic for thread safety) ----

	// Current state of the drain-first recovery machine.
	std::atomic<RamDelayState> m_delay_state{RamDelayState::NORMAL};

	// Target delay captured EARLY at corruption onset.
	// Stored in RELATIVE domain (pts_delta relative to first_pts),
	// matching the original stable model.
	std::atomic<pts_t> m_original_timeshift_delay{0};

	// RELATIVE play position captured LATE at buffer exhaustion.
	//
	// Why RELATIVE (not absolute)?
	//   The original stable model used getPlayPosition() which returns
	//   pts_delta(dec, first_pts). All PRS calculations stayed in this
	//   domain, avoiding the "absolute minus relative = garbage" trap
	//   that produced 7322-second delays in logs.
	//
	// Used for:
	//   - getPlayPosition() during STARVED/DRAINING (UI seekbar stable)
	//   - delay calculation in DRAINING (current_delay = live_rel - frozen_rel)
	std::atomic<pts_t> m_frozen_play_position{0};

	// Phase-lock tracking for signal flap invalidation.
	std::atomic<pts_t> m_recovery_first_pts{0};
	std::atomic<pts_t> m_exhaustion_live_pts{0}; // live_pts at gate close (exhaustion)
	std::atomic<bool> m_signal_present{false};
	std::atomic<bool> m_recovery_captured{false};

	// Dedicated atomic corruption flag (isolated from base class
	// m_stream_corruption_detected which may be a plain bool).
	std::atomic<bool> m_fingerprint_pending{false};

	// Recovery timer — stamped at two points:
	//   1. STARVED entry  : used to bail out fingerprint retry after 5s
	//                       (decoder dead / no PTS → best-effort capture).
	//   2. DRAINING entry : used to force-resume after 30s if PCR stops
	//                       advancing (frozen tuner, dropped lock).
	std::atomic<uint64_t> m_drain_start_ms{0};
};

#endif // __lib_service_eramserviceplay_h

#ifndef __lib_service_eramserviceplay_h
#define __lib_service_eramserviceplay_h

#include <atomic>
#include <lib/base/ebase.h>
#include <lib/dvb/eramtimeshift.h>
#include <lib/service/servicedvb.h>
#include <memory>

// Extends eDVBServicePlay to store timeshift data in RAM instead of disk.
// Pause triggers startTimeshift() into a ring buffer; unpause calls
// activateTimeshift() to play back at the accumulated delay.
// Seeking is disabled to avoid PCR history search issues on high-bitrate channels.
// Enabled when eSettings::ram_timeshift_delay_seconds > 0.
class eRamServicePlay : public eDVBServicePlay {
	DECLARE_REF(eRamServicePlay);

public:
	eRamServicePlay(const eServiceReference& ref, eDVBService* service, int delay_seconds = 10);
	~eRamServicePlay() override;

	// Status helpers
	bool isRamBufferReady() const;
	float ramBufferedSeconds() const;
	int ramFillPercent() const;

	// Position / length (PTS-based)
	RESULT getLength(pts_t& len) override;
	RESULT getPlayPosition(pts_t& pos) override;

	// Seek disabled for RAM timeshift
	RESULT seekTo(pts_t to) override;
	RESULT seekRelative(int direction, pts_t to) override;

	// Timeshift management
	RESULT activateTimeshift() override;
	RESULT saveTimeshiftFile() override;
	void serviceEventTimeshift(int event) override;

	RESULT timeshift(ePtr<iTimeshiftService>& ptr) override {
		ptr = this;
		return 0;
	}

	RESULT unpause() override;

protected:
	RESULT startTimeshift() override;
	RESULT stopTimeshift(bool swToLive = false) override;
	ePtr<iTsSource> createTsSource(eServiceReferenceDVB& ref, int packetsize = 188) override;

	// Override base class PRS — fingerprint only, no immediate pause
	void handleEofRecovery() override;
	void startPreciseRecoveryCheck() override;

private:
	// 200ms watchdog: lap detection + late-pause (drain-first)
	void checkLapAndSeek();

	// Block eventStreamCorrupt from reaching base class (prevents immediate pause)
	void recordEvent(int event) override;

	// RAM-specific corruption handler — connected to eRamRecorder::ramCorrupt
	void onRamCorrupt();

	// 33-bit PTS delta with wrap-around handling
	static inline pts_t pts_delta(pts_t newer, pts_t older) { return (newer - older) & ((1LL << 33) - 1); }

	std::shared_ptr<eRamRingBuffer> m_ram_ring;
	ePtr<eTimer> m_watchdog_timer;
	size_t m_capacity_bytes;
	ePtr<eRamTsSource> m_ts_source;
	eRamRecorder* m_ram_recorder;

	// Frozen play position for seekbar during corruption.
	// Written by onRamCorrupt() (recorder thread) and checkLapAndSeek()
	// (main thread). Read by getPlayPosition() (main thread).
	// pts_t = int64_t: torn read possible on ARM32 without atomic.
	std::atomic<pts_t> m_frozen_play_position{0};

	// One-shot log flag for late-pause to avoid log spam.
	// Written by onRamCorrupt() (recorder thread), read/written by
	// checkLapAndSeek() and startPreciseRecoveryCheck() (main thread).
	std::atomic<bool> m_late_pause_logged{false};
};

#endif // __lib_service_eramserviceplay_h

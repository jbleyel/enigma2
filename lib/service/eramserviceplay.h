#ifndef __lib_service_eramserviceplay_h
#define __lib_service_eramserviceplay_h

#include <lib/base/ebase.h>
#include <lib/dvb/eramtimeshift.h>
#include <lib/service/servicedvb.h>
#include <memory>

/*
 * eRamServicePlay
 *
 * Extends eDVBServicePlay to store timeshift data in RAM instead of
 * disk. All playback controls (pause, unpause) work identically to
 * the normal disk timeshift. Seeking is disabled on RAM timeshift
 * to avoid PCR history search issues with high-bitrate channels.
 *
 * Pause triggers startTimeshift() which records into a ring buffer.
 * Unpause calls activateTimeshift() to start playback from the RAM
 * buffer at the accumulated delay.
 *
 * Enabled via: eSettings::ram_timeshift_delay_seconds > 0
 * Instantiated by eServiceFactoryDVB::play() when that config is set.
 */
class eRamServicePlay : public eDVBServicePlay {
	DECLARE_REF(eRamServicePlay);

public:
	eRamServicePlay(const eServiceReference& ref, eDVBService* service, int delay_seconds = 10);
	~eRamServicePlay() override;

	// --- Status helpers ---
	bool isRamBufferReady() const; // ring buffer has received at least one write
	float ramBufferedSeconds() const; // seconds elapsed since first data
	int ramFillPercent() const; // percentage of ring buffer currently used

	// --- Position and length overrides (PTS based) ---
	RESULT getLength(pts_t& len) override;
	RESULT getPlayPosition(pts_t& pos) override;

	// --- Seek disabled for RAM timeshift ---
	RESULT seekTo(pts_t to) override;
	RESULT seekRelative(int direction, pts_t to) override;

	// --- Timeshift activation and management ---
	RESULT activateTimeshift() override;
	RESULT saveTimeshiftFile() override; // no‑op: nothing to save
	void serviceEventTimeshift(int event) override;

protected:
	RESULT startTimeshift() override;
	RESULT stopTimeshift(bool swToLive = false) override;
	ePtr<iTsSource> createTsSource(eServiceReferenceDVB& ref, int packetsize = 188) override;

	// Override pause/unpause to maintain wall‑clock reference for muted audio
	RESULT pause() override;
	RESULT unpause() override;

private:
	void checkLapAndSeek(); // watchdog: detects ring buffer lap and recovers
	void recordEvent(int event) override; // handles stream corruption freeze
	void updateWallClockRef(); // (re)captures wall‑clock reference for muted audio

	/*
	 * Safe PTS delta with 33‑bit wrap‑around (DVB/MPEG standard).
	 * Linear subtraction masked to 33 bits avoids overflow.
	 */
	static inline pts_t pts_delta(pts_t newer, pts_t older) { return (newer - older) & ((1LL << 33) - 1); }

	// Shared ring buffer – also held by eRamTsSource for reading.
	std::shared_ptr<eRamRingBuffer> m_ram_ring;

	/*
	 * 200 ms periodic watchdog that detects when the ring buffer wraps
	 * past the current read position (lap) and forces the push thread
	 * to jump to the first valid byte.
	 */
	ePtr<eTimer> m_watchdog_timer;

	// Total capacity of the ring buffer in bytes (aligned down to a
	// multiple of 188).
	size_t m_capacity_bytes;

	// iTsSource wrapper that provides eFilePushThread access to the ring buffer.
	ePtr<eRamTsSource> m_ts_source;

	/*
	 * Raw pointer to the RAM recorder thread. Owned by m_record through
	 * replaceThread(); must NOT be deleted directly.
	 */
	eRamRecorder* m_ram_recorder;

	/*
	 * Frozen play position (PTS delta from first PTS) captured at the
	 * moment stream corruption is detected. On HiSilicon, the hardware
	 * decoder's getPTS() keeps advancing even during pause, so we must
	 * freeze this value to prevent the Precise Recovery System (PRS)
	 * from loosening its delay condition prematurely.
	 */
	pts_t m_frozen_play_position;

	// ---------- Wall‑clock reference for muted audio ----------
	// On platforms where the video clock free-runs when audio is muted
	// (e.g. HiSilicon), we substitute a monotonic clock to keep the
	// playback position advancing at a steady 90 kHz.
	// We strictly avoid reading getPTS() while audio is muted to prevent
	// importing the free-running hardware clock into our reference.

	bool m_wc_valid; // true after a successful reference capture
	pts_t m_wc_ref_pts; // PTS at the reference moment
	int64_t m_wc_ref_ms; // monotonic time (ms) at the reference moment
};

#endif /* __lib_service_eramserviceplay_h */

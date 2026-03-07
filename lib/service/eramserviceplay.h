#ifndef __lib_service_eramserviceplay_h
#define __lib_service_eramserviceplay_h

#include <lib/service/servicedvb.h>
#include <lib/dvb/eramtimeshift.h>
#include <lib/base/ebase.h>
#include <memory>

/*
 * eRamServicePlay
 *
 * Extends eDVBServicePlay to store timeshift data in RAM instead of
 * disk.  Pause, unpause, and seek all work exactly as in the normal
 * disk timeshift.
 *
 * After startTimeshift() a 100ms polling timer fires until
 * bufferedMs() >= delay_ms, then calls activateTimeshift()
 * automatically so the viewer sees the delayed picture.
 *
 * Enabled via: config.timeshift.ram_mode = true
 * Instantiated by eServiceFactoryDVB::play() when that config is set.
 */
class eRamServicePlay : public eDVBServicePlay
{
	DECLARE_REF(eRamServicePlay);
public:
	eRamServicePlay(const eServiceReference &ref,
	                eDVBService *service,
	                int delay_seconds = 10);
	virtual ~eRamServicePlay();

	bool	isRamBufferReady() const;
	float	ramBufferedSeconds() const;
	int	ramFillPercent() const;

	RESULT	getLength(pts_t &len) override;
	RESULT	getPlayPosition(pts_t &pos) override;

protected:
	RESULT	startTimeshift() override;
	RESULT	stopTimeshift(bool swToLive = false) override;

	ePtr<iTsSource> createTsSource(eServiceReferenceDVB &ref,
	                               int packetsize = 188) override;

private:
	void	checkDelayReached();

	std::shared_ptr<eRamRingBuffer>	m_ram_ring;
	ePtr<eTimer>			m_activate_timer;
	int64_t				m_delay_ms;
	size_t				m_capacity_bytes;
};

#endif /* __lib_service_eramserviceplay_h */

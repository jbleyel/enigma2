#include "eramserviceplay.h"
#include <lib/base/cfile.h>
#include <lib/dvb/csasession.h>
#include <lib/base/esimpleconfig.h>
#include <algorithm>

DEFINE_REF(eRamServicePlay);

eRamServicePlay::eRamServicePlay(const eServiceReference &ref,
                                 eDVBService *service,
                                 int delay_seconds)
	: eDVBServicePlay(ref, service, true)
{
	m_delay_ms            = (int64_t)delay_seconds * 1000;
	m_ts_source           = nullptr;
	m_realign_in_progress = false;
	m_last_realign_ms     = 0;

	int cap_mb       = std::max(32, delay_seconds * 4);
	m_capacity_bytes = (size_t)cap_mb * 1024 * 1024;

	eDebug("[eRamServicePlay] delay=%ds cap=%dMB", delay_seconds, cap_mb);
}

eRamServicePlay::~eRamServicePlay()
{
	stopTimeshift(false);
}

RESULT eRamServicePlay::startTimeshift()
{
	if (m_timeshift_enabled)
		return -1;

	ePtr<iDVBDemux> demux;
	if (m_service_handler.getDataDemux(demux))
		return -2;

	m_ram_ring = std::make_shared<eRamRingBuffer>(m_capacity_bytes, 8192);

	/* Use the interface factory method to avoid the type mismatch between
	 * ePtr<iDVBDemux> and the eDVBDemux* that eDVBTSRecorder's constructor
	 * requires.  After creation we cast to call replaceThread(). */
	demux->createTSRecorder(m_record, 188, false);
	eDVBTSRecorder *recorder =
		static_cast<eDVBTSRecorder *>(static_cast<iDVBTSRecorder *>(m_record));
	recorder->replaceThread(new eRamRecorder(m_ram_ring.get(), 188));

	m_record->setTargetFD(-1);
	m_record->enableAccessPoints(false);
	m_record->connectEvent(
		sigc::mem_fun(*this, &eRamServicePlay::recordEvent),
		m_con_record_event);

	/* StreamRelay / CSA-ALT channels arrive scrambled - descramble in recorder.
	 * CI and SoftCAM channels arrive already clear at the demux level. */
	if (m_csa_session && m_csa_session->isActive())
	{
		eServiceReferenceDVB dvb_ref = (eServiceReferenceDVB &)m_reference;
		m_timeshift_csa_session      = new eDVBCSASession(dvb_ref);
		if (m_timeshift_csa_session && m_timeshift_csa_session->init())
		{
			m_timeshift_csa_session->forceActivate();
			m_record->setDescrambler(
				static_cast<iServiceScrambled *>(
					m_timeshift_csa_session.operator->()));
		}
	}

	/* Set a sentinel so switchToTimeshift() sees a non-empty path.
	 * Without this, r.path stays empty and tuneExt() enters the
	 * live-channel branch instead of the PVR/timeshift path,
	 * completely ignoring our eRamTsSource. */
	m_timeshift_file = "/ram_timeshift";

	m_timeshift_enabled = 1;
	updateTimeshiftPids();

	const int sret = m_record->start();
	if (sret < 0)
	{
		eWarning("[eRamServicePlay] record->start() failed: %d", sret);
		if (m_timeshift_csa_session)
		{
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_record            = 0;
		m_ram_ring.reset();
		m_timeshift_file.clear();
		m_timeshift_enabled = 0;
		return sret;
	}

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "1");
	CFile::writeStr("/proc/stb/lcd/symbol_record",    "1");

	m_activate_timer = eTimer::create(eApp);
	m_activate_timer->timeout.connect(
		sigc::mem_fun(*this, &eRamServicePlay::checkDelayReached));
	m_activate_timer->start(100, false);

	eDebug("[eRamServicePlay] recording started (%zuMB delay=%lldms)",
		m_capacity_bytes >> 20, (long long)m_delay_ms);
	return 0;
}

void eRamServicePlay::checkDelayReached()
{
	if (!m_ram_ring || !m_timeshift_enabled)
	{
		m_activate_timer->stop();
		return;
	}

	if (m_ram_ring->bufferedMs() < m_delay_ms)
		return;

	m_activate_timer->stop();
	eDebug("[eRamServicePlay] delay reached, activating timeshift");

	/* Switch decoder to read from RAM.  From this point pause/unpause/seek
	 * all work via the normal e2 machinery. */
	eDVBServicePlay::activateTimeshift();

	m_watchdog_timer = eTimer::create(eApp);
	m_watchdog_timer->timeout.connect(
		sigc::mem_fun(*this, &eRamServicePlay::checkLapAndSeek));
	m_watchdog_timer->start(200, false);
}

void eRamServicePlay::checkLapAndSeek()
{
	if (!m_timeshift_active)
		return;

	int64_t now_ms = eRamRingBuffer::nowMs();

	ePtr<eRamTsSource> src = m_ts_source;
	if (!src)
	{
		if (!m_realign_in_progress && (now_ms - m_last_realign_ms >= 2000))
		{
			eDebug("[eRamServicePlay] watchdog: no source, retrying doRealign()");
			doRealign();
		}
		return;
	}

	off_t lapped_at = 0;
	if (!src->getLappedOffset(lapped_at))
		return;

	eDebug("[eRamServicePlay] watchdog: lap detected (lapped_at=%lld)",
	       (long long)lapped_at);

	if (m_realign_in_progress)
		return;

	if (now_ms - m_last_realign_ms < 2000)
		return;

	doRealign();
}

void eRamServicePlay::doRealign()
{
	eDebug("[eRamServicePlay] doRealign: rebuilding push pipeline");

	m_realign_in_progress = true;
	m_last_realign_ms     = eRamRingBuffer::nowMs();

	struct Guard { bool &f; Guard(bool&f):f(f){} ~Guard(){f=false;} }
		guard(m_realign_in_progress);

	resetRecoveryState();

	int recovery_ms   = eSimpleConfig::getInt(
		"config.timeshift.recoveryBufferDelay", 300);
	pts_t seek_target = -(pts_t)(m_original_timeshift_delay
	                              + (pts_t)recovery_ms * 90);
	m_cue->seekTo(0, seek_target);

	eServiceReferenceDVB r = (eServiceReferenceDVB &)m_reference;
	r.path = m_timeshift_file;

	ePtr<eRamTsSource> old_source = m_ts_source;
	ePtr<iTsSource>    source     = createTsSource(r);

	int ret = m_service_handler_timeshift.tuneExt(
		r, source, m_timeshift_file.c_str(),
		m_cue, 0, m_dvb_service,
		eDVBServicePMTHandler::timeshift_playback, false);

	if (ret != 0)
	{
		eWarning("[eRamServicePlay] doRealign: tuneExt failed (%d) -- "
		         "restoring old source, watchdog will retry after cooldown", ret);
		m_ts_source = old_source;
		return;
	}

	eDebug("[eRamServicePlay] doRealign: done");
}

RESULT eRamServicePlay::stopTimeshift(bool swToLive)
{
	if (!m_timeshift_enabled)
		return -1;

	if (m_watchdog_timer) { m_watchdog_timer->stop(); m_watchdog_timer = nullptr; }
	if (m_activate_timer) { m_activate_timer->stop(); m_activate_timer = nullptr; }
	m_ts_source           = nullptr;
	m_realign_in_progress = false;

	resetRecoveryState();

	if (m_record)
	{
		m_record->stop();
		if (m_timeshift_csa_session)
		{
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_record = 0;
	}

	/* shared_ptr reset: eRamTsSource may still hold a reference -
	 * the buffer stays alive until the decoder releases it. */
	m_ram_ring.reset();
	m_timeshift_file.clear();
	m_timeshift_enabled = 0;

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "0");
	CFile::writeStr("/proc/stb/lcd/symbol_record",    "0");

	if (swToLive)
		switchToLive();

	eDebug("[eRamServicePlay] stopped");
	return 0;
}

RESULT eRamServicePlay::getLength(pts_t &len)
{
	if (!m_timeshift_enabled || !m_record)
		return eDVBServicePlay::getLength(len);

	pts_t first = 0, last = 0;
	if (m_record->getFirstPTS(first) || m_record->getCurrentPCR(last))
		return -1;
	if (first == 0 || last <= first)
		return -1;

	len = last - first;
	return 0;
}

ePtr<iTsSource> eRamServicePlay::createTsSource(eServiceReferenceDVB &ref,
                                                int /*packetsize*/)
{
	if (!m_ram_ring)
		return eDVBServicePlay::createTsSource(ref);
	ePtr<eRamTsSource> src = new eRamTsSource(m_ram_ring);
	m_ts_source = src;
	return src;
}

bool eRamServicePlay::isRamBufferReady() const
{
	return m_ram_ring && m_ram_ring->bufferedMs() >= m_delay_ms;
}

float eRamServicePlay::ramBufferedSeconds() const
{
	return m_ram_ring ? (float)(m_ram_ring->bufferedMs() / 1000.0) : 0.f;
}

int eRamServicePlay::ramFillPercent() const
{
	if (!m_ram_ring) return 0;
	off_t filled = m_ram_ring->getWriteOffset() - m_ram_ring->getMinOffset();
	return (int)(filled * 100 / (off_t)(m_capacity_bytes));
}

RESULT eRamServicePlay::getPlayPosition(pts_t &pos)
{
	if (!m_timeshift_active || !m_record)
		return eDVBServicePlay::getPlayPosition(pos);

	pts_t first = 0, live = 0;
	bool has_first = (m_record->getFirstPTS(first)  == 0 && first > 0);
	bool has_live  = (m_record->getCurrentPCR(live) == 0 && live  > 0);

	RESULT r = eDVBServicePlay::getPlayPosition(pos);
	if (r)
		return r;

	if (has_first)
	{
		if (pos >= first)
		{
			pos -= first;
		}
		else if (pos == 0 && has_live)
		{
			if (pts_delta(live, first) > 2 * 90000)
				return -1;
		}
		else
		{
			pos = 0;
		}
	}

	return 0;
}

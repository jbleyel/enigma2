#include "eramserviceplay.h"
#include <lib/base/cfile.h>
#include <algorithm>

DEFINE_REF(eRamServicePlay);

eRamServicePlay::eRamServicePlay(const eServiceReference &ref,
                                 eDVBService *service,
                                 int delay_seconds)
	: eDVBServicePlay(ref, service, true)
{
	m_delay_ms = (int64_t)delay_seconds * 1000;

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
		sigc::mem_fun(*this, &eDVBServicePlay::recordEvent),
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
}

RESULT eRamServicePlay::stopTimeshift(bool swToLive)
{
	if (!m_timeshift_enabled)
		return -1;

	if (m_activate_timer)
		m_activate_timer->stop();

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
	if (m_ram_ring)
		return ePtr<iTsSource>(new eRamTsSource(m_ram_ring));
	return eDVBServicePlay::createTsSource(ref);
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

#include "eramserviceplay.h"
#include <lib/base/cfile.h>
#include <lib/dvb/csasession.h>
#include <lib/base/esimpleconfig.h>
#include <algorithm>
#include <unistd.h>

DEFINE_REF(eRamServicePlay);

eRamServicePlay::eRamServicePlay(const eServiceReference &ref,
                                 eDVBService *service,
                                 int delay_seconds)
	: eDVBServicePlay(ref, service, true)
{
	m_ts_source           = nullptr;
	m_ram_recorder        = nullptr;

	int cap_mb       = std::max(32, delay_seconds * 4);
	m_capacity_bytes = (size_t)cap_mb * 1024 * 1024;

	eDebug("[eRamServicePlay] cap=%dMB", cap_mb);
}

eRamServicePlay::~eRamServicePlay()
{
	stopTimeshift(false);
}

/* ------------------------------------------------------------------ */
/* startTimeshift                                                      */
/* ------------------------------------------------------------------ */

RESULT eRamServicePlay::startTimeshift()
{
	if (m_timeshift_enabled)
		return -1;

	ePtr<iDVBDemux> demux;
	if (m_service_handler.getDataDemux(demux))
		return -2;

	m_ram_ring = std::make_shared<eRamRingBuffer>(m_capacity_bytes, 8192);

	demux->createTSRecorder(m_record, 188, false);
	eDVBTSRecorder *recorder =
		static_cast<eDVBTSRecorder *>(static_cast<iDVBTSRecorder *>(m_record));
	eRamRecorder *ram_rec = new eRamRecorder(m_ram_ring.get(), 188);
	m_ram_recorder = ram_rec;
	recorder->replaceThread(ram_rec);

	m_record->setTargetFD(-1);
	m_record->enableAccessPoints(true);
	m_record->connectEvent(
		sigc::mem_fun(*this, &eRamServicePlay::recordEvent),
		m_con_record_event);

	/* StreamRelay / CSA-ALT channels need per-session descrambling */
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

	/* Use the ap base path as the "file" so eDVBTSTools finds our .ap.
	 * createTsSource() returns eRamTsSource (ring buffer), not a real file. */
	m_timeshift_file = "/tmp/ram_ts";

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
		m_ram_recorder      = nullptr;
		m_record            = 0;
		m_ram_ring.reset();
		m_timeshift_file.clear();
		m_timeshift_enabled = 0;
		return sret;
	}

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "1");
	CFile::writeStr("/proc/stb/lcd/symbol_record",    "1");

	eDebug("[eRamServicePlay] recording started (%zuMB)", m_capacity_bytes >> 20);
	return 0;
}

/* ------------------------------------------------------------------ */
/* activateTimeshift — start watchdog after parent activates          */
/* ------------------------------------------------------------------ */

RESULT eRamServicePlay::activateTimeshift()
{
	eDVBServicePlay::activateTimeshift();

	m_watchdog_timer = eTimer::create(eApp);
	m_watchdog_timer->timeout.connect(
		sigc::mem_fun(*this, &eRamServicePlay::checkLapAndSeek));
	m_watchdog_timer->start(200, false);
	return 0;
}

/* ------------------------------------------------------------------ */
/* checkLapAndSeek (watchdog, every 200ms)                            */
/* ------------------------------------------------------------------ */

void eRamServicePlay::checkLapAndSeek()
{
	if (!m_timeshift_active)
		return;

	/* --- Lap detection (ring buffer overtook read position) ---
	 *
	 * m_streaminfo in eDVBTSTools is loaded ONCE at tuneExt time from the
	 * .ap file — it NEVER re-reads it.  After ring wrap, entries in
	 * m_access_points point to byte offsets that no longer exist.
	 * A normal seekTo(0) through tstools would resolve to an old, invalid
	 * offset → EAGAIN loop.
	 *
	 * Fix: bypass tstools entirely.  Set the start offset in eRamTsSource
	 * directly to min_offset (first valid byte in the ring buffer).
	 * The push thread calls offset() once on its next wakeup and starts
	 * reading from there — no pipeline rebuild needed. */
	ePtr<eRamTsSource> src = m_ts_source;
	if (!src)
		return;

	off_t lapped_at = 0;
	if (!src->getLappedOffset(lapped_at))
		return;

	if (!m_ram_ring)
		return;

	off_t min_off = m_ram_ring->getMinOffset();
	/* Align up to 188-byte packet boundary */
	off_t safe = min_off + (188 - min_off % 188) % 188;

	eDebug("[eRamServicePlay] watchdog: lap at %lld, jumping to min_off=%lld",
	       (long long)lapped_at, (long long)safe);

	src->setStartOffset(safe);
}

/* ------------------------------------------------------------------ */
/* stopTimeshift                                                       */
/* ------------------------------------------------------------------ */

RESULT eRamServicePlay::stopTimeshift(bool swToLive)
{
	if (!m_timeshift_enabled)
		return -1;

	if (m_watchdog_timer) { m_watchdog_timer->stop(); m_watchdog_timer = nullptr; }

	resetRecoveryState();

	if (m_record)
	{
		/* Stop the push thread FIRST — guarantees eRamTsSource::read() /
		 * offset() are no longer executing before we release the source.
		 * Reversing this order (nulling m_ts_source before stop()) would
		 * create a use-after-free window because eFilePushThread holds a
		 * raw pointer to the source and may be mid-read. */
		m_record->stop();

		if (m_timeshift_csa_session)
		{
			m_record->setDescrambler(nullptr);
			m_timeshift_csa_session = nullptr;
		}
		m_record = 0;
	}

	/* Safe to release now — push thread is guaranteed stopped. */
	m_ts_source    = nullptr;
	m_ram_recorder = nullptr;

	m_ram_ring.reset();
	m_timeshift_enabled = 0;

	m_timeshift_file.clear();

	CFile::writeStr("/proc/stb/lcd/symbol_timeshift", "0");
	CFile::writeStr("/proc/stb/lcd/symbol_record",    "0");

	if (swToLive)
		switchToLive();

	eDebug("[eRamServicePlay] stopped");
	return 0;
}

/* ------------------------------------------------------------------ */
/* seekTo — bypass tstools, resolve offset directly from PCR history  */
/* ------------------------------------------------------------------ */
/*
 * eDVBTSTools::setSource() loads the .ap file ONCE into m_access_points
 * in memory and never re-reads it.  After ring buffer wrap-around, those
 * stored offsets are stale/invalid, so any tstools-based seek would give
 * wrong results or an EAGAIN loop.
 *
 * Fix: resolve the target byte offset ourselves from the PCR history
 * inside eRamRecorder, then set it directly on eRamTsSource.
 * The push thread picks it up on its next wakeup — no pipeline rebuild.
 */
RESULT eRamServicePlay::seekTo(pts_t to)
{
	if (!m_timeshift_active || !m_ram_recorder)
		return eDVBServicePlay::seekTo(to);

	/* Get current window [first, last] PCR values */
	pts_t first = 0, last = 0;
	if (m_ram_recorder->getPTSWindow(first, last) != 0)
		return -1;

	/* Clamp relative seek position to window size */
	pts_t win = pts_delta(last, first);
	if (to < 0)   to = 0;
	if (to > win) to = win;

	/* Convert relative PTS offset → absolute PCR value in the ring */
	pts_t abs_target = (first + to) & ((1LL << 33) - 1);

	/* Find the nearest byte offset for this PCR in the ring buffer */
	off_t byte_offset = m_ram_recorder->findOffsetForPTS(abs_target);

	if (byte_offset >= 0 && m_ts_source)
	{
		eDebug("[eRamServicePlay] seekTo: pts=%lld → offset=%lld",
		       (long long)to, (long long)byte_offset);
		m_ts_source->setStartOffset(byte_offset);
		return 0;
	}

	/* Fallback: guard against empty PCR history */
	eWarning("[eRamServicePlay] seekTo: findOffsetForPTS failed, falling back");
	return eDVBServicePlay::seekTo(to);
}

/* ------------------------------------------------------------------ */
/* createTsSource — return ring buffer source, not a real file        */
/* ------------------------------------------------------------------ */

ePtr<iTsSource> eRamServicePlay::createTsSource(eServiceReferenceDVB &ref,
                                                int /*packetsize*/)
{
	if (!m_ram_ring)
		return eDVBServicePlay::createTsSource(ref);
	eRamTsSource *src = new eRamTsSource(m_ram_ring);
	m_ts_source = src;
	return ePtr<iTsSource>(src);
}

/* ------------------------------------------------------------------ */
/* getLength — use PCR window, not pvr_channel / .ap                  */
/* ------------------------------------------------------------------ */

RESULT eRamServicePlay::getLength(pts_t &len)
{
	if (!m_ram_recorder)
		return eDVBServicePlay::getLength(len);

	pts_t first_pcr = 0, last = 0;
	if (m_ram_recorder->getFirstPCR(first_pcr) != 0)
		return -1;

	pts_t dummy = 0;
	if (m_ram_recorder->getPTSWindow(dummy, last) != 0)
		return -1;

	pts_t d = pts_delta(last, first_pcr);
	if (d <= 0)
		return -1;

	len = d;
	return 0;
}

/* ------------------------------------------------------------------ */
/* getPlayPosition — use decoder PTS + PCR window                     */
/* ------------------------------------------------------------------ */

RESULT eRamServicePlay::getPlayPosition(pts_t &pos)
{
	if (!m_timeshift_active || !m_ram_recorder || !m_decoder)
		return eDVBServicePlay::getPlayPosition(pos);

	/* Use m_first_pcr as fixed reference — identical to how disk timeshift
	 * uses pts_begin (first entry in .ap file).  This keeps the reference
	 * frame stable across ring wraps so the Precise Recovery System's
	 *   delay = getCurrentPCR() - getPlayPosition()
	 * remains consistent regardless of how many times the buffer has wrapped.
	 *
	 * Ring wrap invariance:
	 *   m_first_pcr is set once when the first PCR arrives and never changes.
	 *   getPlayPosition() = pts_delta(dec, m_first_pcr) always grows with dec.
	 *   getCurrentPCR()   = abs_pcr (absolute, also never shifted by wrap).
	 *   delay = abs_pcr - (dec - m_first_pcr) = real_delay + m_first_pcr ✓
	 *
	 * getLength() still uses the sliding window (last - first) for the
	 * seek bar — that's correct and unaffected. */
	pts_t first_pcr = 0;
	if (m_ram_recorder->getFirstPCR(first_pcr) != 0)
		return -1;

	pts_t dec = 0;
	if (m_decoder->getPTS(0, dec) != 0)
		if (m_decoder->getPTS(1, dec) != 0)
			return -1;

	pos = pts_delta(dec, first_pcr);
	return 0;
}

/* ------------------------------------------------------------------ */
/* Status helpers                                                      */
/* ------------------------------------------------------------------ */

bool eRamServicePlay::isRamBufferReady() const
{
	return m_ram_ring && m_ram_ring->getWriteOffset() > 0;
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

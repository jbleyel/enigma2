#ifndef __lib_dvb_eramtimeshift_h
#define __lib_dvb_eramtimeshift_h

#include <lib/dvb/demux.h>
#include <lib/base/itssource.h>
#include <memory>
#include <pthread.h>
#include <stdint.h>

struct eRamBlock
{
	off_t	offset;		/* absolute write offset at this block */
	bool	is_access_point;
};

/*
 * eRamRingBuffer
 *
 * Seekable circular RAM buffer for DVB TS data.
 * Addressed by absolute byte offset (like a file), so the standard
 * e2 timeshift machinery (eFilePushThread, cuesheet, seek) works
 * without modification.
 *
 * read(offset, ...) maps the absolute offset to the physical ring
 * position via offset % capacity.  Reads from overwritten regions
 * return EAGAIN.
 */
class eRamRingBuffer
{
public:
	eRamRingBuffer(size_t capacity_bytes, size_t max_blocks);
	~eRamRingBuffer();

	int	write(const uint8_t *data, size_t len, bool is_access_point = false);
	int	read(off_t offset, uint8_t *buf, size_t len);

	off_t	getWriteOffset() const;
	off_t	getMinOffset() const;
	int64_t	bufferedMs() const;

	off_t	findNearestAccessPoint(off_t from_offset) const;

	static int64_t nowMs();

private:
	uint8_t		*m_buf;
	size_t		 m_capacity;

	size_t		 m_max_blocks;
	off_t		 m_write_offset;
	int64_t		 m_first_write_ms;

	eRamBlock	*m_blocks;
	size_t		 m_block_write_idx;
	size_t		 m_total_blocks;

	mutable pthread_mutex_t	m_mutex;
};

/*
 * eRamTsSource
 *
 * iTsSource backed by eRamRingBuffer.
 * Implements read(offset, ...) so eFilePushThread can seek within
 * the recorded RAM data.  length() returns the current write offset
 * so the push thread knows how far it can read.
 */
class eRamTsSource : public iTsSource
{
	DECLARE_REF(eRamTsSource);
public:
	explicit eRamTsSource(std::shared_ptr<eRamRingBuffer> buf);
	virtual ~eRamTsSource() {}

	ssize_t	read(off_t offset, void *buf, size_t count) override;
	off_t	length() override;
	int	valid()  override { return m_buf ? 1 : 0; }
	off_t	offset() override;

private:
	std::shared_ptr<eRamRingBuffer>	m_buf;
};

/*
 * eRamRecorder
 *
 * Subclass of eDVBRecordScrambledThread that writes into eRamRingBuffer
 * instead of a disk file.
 *
 * PCR Fix for encrypted channels:
 * The adaptation field (which contains PCR) is ALWAYS unencrypted in
 * the TS standard, even for scrambled channels. We scan it in writeData()
 * and expose it via getCurrentPCR() so the precise recovery system works
 * correctly for encrypted channels.
 */
class eRamRecorder : public eDVBRecordScrambledThread
{
public:
	explicit eRamRecorder(eRamRingBuffer *buf, int packetsize = 188);
	virtual ~eRamRecorder() { pthread_mutex_destroy(&m_pcr_mutex); }

	eRamRingBuffer *getRingBuffer() { return m_ring; }

	/* Override to provide live PCR from the recording side.
	 * Required by the precise recovery system (handleEofRecovery /
	 * startPreciseRecoveryCheck) which calls m_record->getCurrentPCR().
	 * The base class returns m_last_pts which is never updated when we
	 * bypass the parent writeData(), so we track PCR ourselves. */
	int getCurrentPCR(pts_t &pcr) override;

	/* Override to provide the first PTS seen (for seek bar). */
	int getFirstPTS(pts_t &pts) override;

protected:
	int  writeData(int len) override;
	void flush() override;

private:
	/* Scan a single 188-byte TS packet for PCR.
	 * Returns true and sets pcr if found. */
	static bool extractPCR(const uint8_t *pkt, pts_t &pcr);

	/* PCR values are written by the recorder thread and read by the
	 * recovery thread — protect with a dedicated mutex to avoid
	 * torn/stale reads on 64-bit pts_t (critical on ARM 32-bit). */
	void updatePCR(pts_t pcr);

	mutable pthread_mutex_t m_pcr_mutex;
	eRamRingBuffer *m_ring;
	pts_t	m_last_pcr;
	bool	m_last_pcr_valid;

	pts_t	m_first_pcr;
	bool	m_first_pcr_valid;
};

#endif /* __lib_dvb_eramtimeshift_h */

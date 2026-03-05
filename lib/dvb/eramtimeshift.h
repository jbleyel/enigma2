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
 * instead of a disk file.  Descrambling (CI, SoftCAM, StreamRelay) and
 * I-frame detection work identically to the disk path.
 */
class eRamRecorder : public eDVBRecordScrambledThread
{
public:
	explicit eRamRecorder(eRamRingBuffer *buf, int packetsize = 188);

	eRamRingBuffer *getRingBuffer() { return m_ring; }

protected:
	int  writeData(int len) override;
	void flush() override;

private:
	eRamRingBuffer *m_ring;
};

#endif /* __lib_dvb_eramtimeshift_h */

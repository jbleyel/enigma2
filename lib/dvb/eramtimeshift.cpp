#include "eramtimeshift.h"
#include <lib/base/eerror.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>

/* ------------------------------------------------------------------ */
/* eRamRingBuffer                                                      */
/* ------------------------------------------------------------------ */

int64_t eRamRingBuffer::nowMs()
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)(ts.tv_sec * 1000) + (ts.tv_nsec / 1000000);
}

eRamRingBuffer::eRamRingBuffer(size_t capacity_bytes, size_t max_blocks)
	: m_max_blocks(max_blocks)
	, m_write_offset(0)
	, m_first_write_ms(0)
	, m_block_write_idx(0)
	, m_total_blocks(0)
{
	m_capacity = capacity_bytes - (capacity_bytes % 188);

	m_buf = static_cast<uint8_t *>(malloc(m_capacity));
	if (!m_buf)
		eFatal("[eRamRingBuffer] malloc failed (%zu MB)", m_capacity >> 20);

	m_blocks = static_cast<eRamBlock *>(calloc(m_max_blocks, sizeof(eRamBlock)));
	if (!m_blocks)
		eFatal("[eRamRingBuffer] blocks calloc failed");

	pthread_mutex_init(&m_mutex, nullptr);

	eDebug("[eRamRingBuffer] ready: %zu MB, %zu blocks",
		m_capacity >> 20, m_max_blocks);
}

eRamRingBuffer::~eRamRingBuffer()
{
	pthread_mutex_destroy(&m_mutex);
	free(m_blocks);
	free(m_buf);
}

int eRamRingBuffer::write(const uint8_t *data, size_t len, bool is_access_point)
{
	len -= len % 188;
	if (!data || len == 0 || len > m_capacity)
		return 0;

	pthread_mutex_lock(&m_mutex);

	const int64_t now = nowMs();
	if (m_first_write_ms == 0)
		m_first_write_ms = now;

	size_t ring_pos = (size_t)(m_write_offset % (off_t)m_capacity);

	size_t part1 = m_capacity - ring_pos;
	if (part1 >= len)
	{
		memcpy(m_buf + ring_pos, data, len);
	}
	else
	{
		memcpy(m_buf + ring_pos, data, part1);
		memcpy(m_buf,            data + part1, len - part1);
	}

	eRamBlock &blk      = m_blocks[m_block_write_idx];
	blk.offset          = m_write_offset;
	blk.is_access_point = is_access_point;

	m_block_write_idx = (m_block_write_idx + 1) % m_max_blocks;
	if (m_total_blocks < m_max_blocks)
		m_total_blocks++;

	m_write_offset += (off_t)len;

	pthread_mutex_unlock(&m_mutex);
	return (int)len;
}

int eRamRingBuffer::read(off_t offset, uint8_t *buf, size_t len)
{
	len -= len % 188;
	if (!buf || len == 0)
	{
		errno = EAGAIN;
		return -1;
	}

	pthread_mutex_lock(&m_mutex);

	off_t min_off = (m_write_offset > (off_t)m_capacity)
	              ? m_write_offset - (off_t)m_capacity
	              : 0;
	off_t avail   = m_write_offset - offset;

	if (offset < min_off || avail <= 0)
	{
		pthread_mutex_unlock(&m_mutex);
		errno = EAGAIN;
		return -1;
	}

	if ((off_t)len > avail)
		len = (size_t)(avail - (avail % 188));

	if (len == 0)
	{
		pthread_mutex_unlock(&m_mutex);
		errno = EAGAIN;
		return -1;
	}

	size_t ring_pos = (size_t)(offset % (off_t)m_capacity);
	size_t part1    = m_capacity - ring_pos;

	if (part1 >= len)
	{
		memcpy(buf, m_buf + ring_pos, len);
	}
	else
	{
		memcpy(buf,         m_buf + ring_pos, part1);
		memcpy(buf + part1, m_buf,            len - part1);
	}

	pthread_mutex_unlock(&m_mutex);
	return (int)len;
}

off_t eRamRingBuffer::getWriteOffset() const
{
	pthread_mutex_lock(&m_mutex);
	off_t v = m_write_offset;
	pthread_mutex_unlock(&m_mutex);
	return v;
}

off_t eRamRingBuffer::getMinOffset() const
{
	pthread_mutex_lock(&m_mutex);
	off_t v = (m_write_offset > (off_t)m_capacity)
	        ? m_write_offset - (off_t)m_capacity
	        : 0;
	pthread_mutex_unlock(&m_mutex);
	return v;
}

int64_t eRamRingBuffer::bufferedMs() const
{
	pthread_mutex_lock(&m_mutex);
	int64_t v = (m_first_write_ms == 0) ? 0 : (nowMs() - m_first_write_ms);
	pthread_mutex_unlock(&m_mutex);
	return v;
}

off_t eRamRingBuffer::findNearestAccessPoint(off_t from_offset) const
{
	pthread_mutex_lock(&m_mutex);

	off_t min_off = (m_write_offset > (off_t)m_capacity)
	              ? m_write_offset - (off_t)m_capacity
	              : 0;

	off_t best = -1;
	for (size_t i = 0; i < m_total_blocks; i++)
	{
		const eRamBlock &b = m_blocks[i];
		if (b.offset >= from_offset && b.offset >= min_off && b.is_access_point)
		{
			if (best == -1 || b.offset < best)
				best = b.offset;
		}
	}

	pthread_mutex_unlock(&m_mutex);
	return best;
}

/* ------------------------------------------------------------------ */
/* eRamTsSource                                                        */
/* ------------------------------------------------------------------ */

DEFINE_REF(eRamTsSource);

eRamTsSource::eRamTsSource(std::shared_ptr<eRamRingBuffer> buf)
	: m_buf(buf)
{
}

ssize_t eRamTsSource::read(off_t offset, void *buf, size_t count)
{
	if (!m_buf || !buf || count == 0)
		return 0;
	return (ssize_t)m_buf->read(offset, static_cast<uint8_t *>(buf), count);
}

off_t eRamTsSource::length()
{
	return m_buf ? m_buf->getWriteOffset() : -1;
}

off_t eRamTsSource::offset()
{
	/* RAM source has no file descriptor -- return current write position
	 * so callers see a sensible "current" offset. */
	return m_buf ? m_buf->getWriteOffset() : 0;
}

/* ------------------------------------------------------------------ */
/* eRamRecorder                                                        */
/* ------------------------------------------------------------------ */

eRamRecorder::eRamRecorder(eRamRingBuffer *buf, int packetsize)
	: eDVBRecordScrambledThread(packetsize, 188 * 256, false, false)
	, m_ring(buf)
{
}

int eRamRecorder::writeData(int len)
{
	if (len <= 0 || !m_ring)
		return 0;

	if (m_serviceDescrambler)
		m_serviceDescrambler->descramble(m_buffer, len);

	size_t ap_before = m_ts_parser.getAccessPointCount();
	if (!getProtocol())
		m_ts_parser.parseData(m_current_offset, m_buffer, len);
	bool is_ap = (m_ts_parser.getAccessPointCount() > ap_before);

	int written = m_ring->write(m_buffer, (size_t)len, is_ap);
	if (written > 0)
		m_current_offset += written;
	return written;
}

void eRamRecorder::flush()
{
}

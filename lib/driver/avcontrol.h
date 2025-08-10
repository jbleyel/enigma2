/*
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License

Copyright (c) 2023-2025 OpenATV, jbleyel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
1. Non-Commercial Use: You may not use the Software or any derivative works
   for commercial purposes without obtaining explicit permission from the
   copyright holder.
2. Share Alike: If you distribute or publicly perform the Software or any
   derivative works, you must do so under the same license terms, and you
   must make the source code of any derivative works available to the
   public.
3. Attribution: You must give appropriate credit to the original author(s)
   of the Software by including a prominent notice in your derivative works.
THE SOFTWARE IS PROVIDED "AS IS," WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE,
ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more details about the CC BY-NC-SA 4.0 License, please visit:
https://creativecommons.org/licenses/by-nc-sa/4.0/
*/

#ifndef __avcontrol_h
#define __avcontrol_h

#include <errno.h>
#include <fcntl.h>
#include <linux/dvb/dmx.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/time.h>
#include <unistd.h>

#include <iostream>
#include <vector>

#include <lib/base/object.h>
#include <lib/python/connections.h>

#define BUFFER_SIZE (256 * 1024)

#ifndef SWIG

class BitrateCalculator {
private:
	std::vector<int> fds;
	std::vector<unsigned long long> b_total, b_tot1, min_kb_s, max_kb_s, avg_kb_s, curr_kb_s;

	static unsigned long timevalToMs(const struct timeval* tv) {
		return (tv->tv_sec * 1000) + ((tv->tv_usec + 500) / 1000);
	}

	static long deltaTimeMs(struct timeval* tv, struct timeval* last_tv) {
		return timevalToMs(tv) - timevalToMs(last_tv);
	}

	static int Select(int maxfd, fd_set* readfds, fd_set* writefds, fd_set* exceptfds, struct timeval* timeout) {
		int retval;
		fd_set rset, wset, xset;
		timeval interval;
		timerclear(&interval);

		/* make a backup of all fd_set's and timeval struct */
		if (readfds)
			rset = *readfds;
		if (writefds)
			wset = *writefds;
		if (exceptfds)
			xset = *exceptfds;
		if (timeout)
			interval = *timeout;

		while (1) {
			retval = select(maxfd, readfds, writefds, exceptfds, timeout);

			if (retval < 0) {
				/* restore the backup before we continue */
				if (readfds)
					*readfds = rset;
				if (writefds)
					*writefds = wset;
				if (exceptfds)
					*exceptfds = xset;
				if (timeout)
					*timeout = interval;
				if (errno == EINTR)
					continue;
				eDebug("[BitrateCalculator] select failed %d", errno);
				break;
			}

			break;
		}
		return retval;
	}

	static ssize_t Read(int fd, void* buf, size_t count) {
		int retval;
		char* ptr = (char*)buf;
		size_t handledcount = 0;
		while (handledcount < count) {
			retval = read(fd, &ptr[handledcount], count - handledcount);

			if (retval == 0)
				return handledcount;
			if (retval < 0) {
				if (errno == EINTR)
					continue;
				eDebug("[BitrateCalculator] read failed %d", errno);
				return retval;
			}
			handledcount += retval;
		}
		return handledcount;
	}

	static ssize_t NBRead(int fd, void* buf, size_t count) {
		int retval;
		while (1) {
			retval = ::read(fd, buf, count);
			if (retval < 0) {
				if (errno == EINTR)
					continue;
				eDebug("[BitrateCalculator] read failed %d", errno);
			}
			return retval;
		}
	}

public:
	PyObject* measureBitrate(int adapter, int demux, int videoPid, int audioPid) {
		char filename[128];
		snprintf(filename, 128, "/dev/dvb/adapter%d/demux%d", adapter, demux);

		// Initialize vectors for video and audio
		std::vector<int> pids = {videoPid, audioPid};

		// Setup demux for each PID
		for (int pid : pids) {
			int fd = ::open(filename, O_RDONLY);
			::fcntl(fd, F_SETFL, O_NONBLOCK);
			::ioctl(fd, DMX_SET_BUFFER_SIZE, 1024 * 1024);

			dmx_pes_filter_params flt;
			flt.pes_type = DMX_PES_OTHER;
			flt.pid = pid;
			flt.input = DMX_IN_FRONTEND;
			flt.output = DMX_OUT_TAP;
			flt.flags = DMX_IMMEDIATE_START;
			::ioctl(fd, DMX_SET_PES_FILTER, &flt);
			fds.push_back(fd);

			b_total.push_back(0);
			b_tot1.push_back(0);
			min_kb_s.push_back(50000ULL);
			max_kb_s.push_back(0);
			curr_kb_s.push_back(0);
			avg_kb_s.push_back(0);
		}

		struct timeval first_tv, last_print_tv, tv;
		gettimeofday(&first_tv, 0);
		last_print_tv = first_tv;

		while (1) {
			unsigned char buf[BUFFER_SIZE];
			int maxfd = 0;
			fd_set rset;
			FD_ZERO(&rset);
			struct timeval timeout;
			timeout.tv_sec = 1;
			timeout.tv_usec = 0;
			for (unsigned int i = 0; i < fds.size(); i++) {
				if (fds[i] >= 0)
					FD_SET(fds[i], &rset);
				if (fds[i] >= maxfd)
					maxfd = fds[i] + 1;
			}

			int result = Select(maxfd, &rset, NULL, NULL, &timeout);
			if (result <= 0)
				break;

			for (unsigned int i = 0; i < fds.size(); i++) {
				if (fds[i] >= 0 && FD_ISSET(fds[i], &rset)) {
					int b_len = NBRead(fds[i], buf, sizeof(buf));
					int b_start = 0;
					int b = b_len - b_start;
					if (b <= 0)
						continue;
					b_total[i] += b;
					b_tot1[i] += b;
				}
			}
			gettimeofday(&tv, 0);
			int d_print_ms = deltaTimeMs(&tv, &last_print_tv);
			if (d_print_ms >= 1000) {
				for (unsigned int i = 0; i < fds.size(); i++) {
					int d_tim_ms = deltaTimeMs(&tv, &first_tv);
					avg_kb_s[i] = (b_total[i] * 8ULL) / (unsigned long long)d_tim_ms;
					curr_kb_s[i] = (b_tot1[i] * 8ULL) / (unsigned long long)d_print_ms;
					/* compensate for PES overhead */
					avg_kb_s[i] = avg_kb_s[i] * 99ULL / 100ULL;
					curr_kb_s[i] = curr_kb_s[i] * 99ULL / 100ULL;
					b_tot1[i] = 0;

					if (curr_kb_s[i] < min_kb_s[i]) {
						min_kb_s[i] = curr_kb_s[i];
					}
					if (curr_kb_s[i] > max_kb_s[i]) {
						max_kb_s[i] = curr_kb_s[i];
					}
					last_print_tv.tv_sec = tv.tv_sec;
					last_print_tv.tv_usec = tv.tv_usec;
				}
			}
		}
		// Create Python return object
		PyObject* resultList = PyList_New(2);

		for (size_t i = 0; i < fds.size(); i++) {
			PyObject* tuple = PyTuple_New(4);
			if (!tuple) {
				Py_DECREF(resultList);
				return NULL;
			}
			PyTuple_SET_ITEM(tuple, 0, PyLong_FromUnsignedLong(min_kb_s[i]));
			PyTuple_SET_ITEM(tuple, 1, PyLong_FromUnsignedLong(max_kb_s[i]));
			PyTuple_SET_ITEM(tuple, 2, PyLong_FromUnsignedLong(avg_kb_s[i]));
			PyTuple_SET_ITEM(tuple, 3, PyLong_FromUnsignedLong(curr_kb_s[i]));
			PyList_SET_ITEM(resultList, i, tuple);
		}

		// Cleanup
		for (int fd : fds) {
			close(fd);
		}
		fds.clear();
		b_total.clear();
		b_tot1.clear();
		min_kb_s.clear();
		max_kb_s.clear();
		avg_kb_s.clear();
		curr_kb_s.clear();

		return resultList;
	}
};

#endif

class eSocketNotifier;

class eAVControl : public sigc::trackable {
	void fp_event(int what);

#ifdef SWIG
	eAVControl();
	~eAVControl();
#endif

public:
#ifndef SWIG
	eAVControl();
	~eAVControl();
#endif

	static eAVControl* getInstance() {
		return m_instance;
	}
	int getAspect(int defaultVal = 0, int flags = 0) const;
	int getFrameRate(int defaultVal = 50000, int flags = 0) const;
	bool getProgressive(int flags = 0) const;
	int getResolutionX(int defaultVal = 0, int flags = 0) const;
	int getResolutionY(int defaultVal = 0, int flags = 0) const;
	std::string getVideoMode(const std::string& defaultVal = "", int flags = 0) const;
	std::string getPreferredModes(int flags = 0) const;
	std::string getAvailableModes() const;
	bool isEncoderActive() const;

	void setAspectRatio(int ratio, int flags = 0) const;
	void setAspect(const std::string& newFormat, int flags = 0) const;
	void setColorFormat(const std::string& newFormat, int flags = 0) const;

	void setVideoMode(const std::string& newMode, int flags = 0) const;
	void setInput(const std::string& newMode, int flags = 0);
	void startStopHDMIIn(bool on, bool audio, int flags = 0);
	void disableHDMIIn(int flags = 0) const;
	void setOSDAlpha(int alpha, int flags = 0) const;

	bool hasProcHDMIRXMonitor() const {
		return m_b_has_proc_hdmi_rx_monitor;
	}
	bool hasProcVideoMode50() const {
		return m_b_has_proc_videomode_50;
	}
	bool hasProcVideoMode60() const {
		return m_b_has_proc_videomode_60;
	}
	bool hasScartSwitch() const;
	bool has24hz() const {
		return m_b_has_proc_videomode_24;
	}
	bool hasOSDAlpha() const {
		return m_b_has_proc_osd_alpha;
	}

	void setWSS(int val, int flags = 0) const;
	void setPolicy43(const std::string& newPolicy, int flags = 0) const;
	void setPolicy169(const std::string& newPolicy, int flags = 0) const;

	void setVideoSize(int top, int left, int width, int height, int flags = 0) const;

	std::string getEDIDPath() const;

	enum { FLAGS_DEBUG = 1, FLAGS_SUPPRESS_NOT_EXISTS = 2, FLAGS_SUPPRESS_READWRITE_ERROR = 4 };
	PSignal1<void, int> vcr_sb_notifier;
	int getVCRSlowBlanking();

private:
	static eAVControl* m_instance;
	std::string m_video_mode;
	std::string m_video_mode_50;
	std::string m_video_mode_60;
	std::string m_videomode_choices;

	bool m_b_has_proc_osd_alpha;
	bool m_b_has_proc_hdmi_rx_monitor;
	bool m_b_has_proc_videomode_50;
	bool m_b_has_proc_videomode_60;
	bool m_b_has_proc_videomode_24;
	bool m_encoder_active;
	bool m_b_has_scartswitch;
	bool m_b_hdmiin_fhd;
	int m_fp_fd;

	ePtr<eSocketNotifier> m_fp_notifier;

	std::string readAvailableModes(int flags = 0) const;
	bool checkScartSwitch(int flags = 0) const;

	static PyObject* measure_bitrate(int adapter, int demux, int videoPid, int audioPid) {
		BitrateCalculator calc;
		return calc.measureBitrate(adapter, demux, videoPid, audioPid);
	}
};


#endif

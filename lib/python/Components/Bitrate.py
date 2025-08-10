from enigma import eAVControl, iServiceInformation


def getBitrate(session):
	"""
	Retrieve the current bitrate statistics for video and audio of the active service.

	This function accesses the current service from the session's navigation,
	extracts streaming data to determine the adapter and demux values, and
	obtains video and audio PIDs. It then measures the bitrates for both streams.

	Args:
		session: The current Enigma2 session object containing navigation and service information.

	Returns:
		list or None: A list containing two tuples (video, audio) with bitrate measurements,
					or None if the bitrate could not be determined.
					Each tuple contains 4 values in kb/s:
					- [0]: Minimum bitrate measured
					- [1]: Maximum bitrate measured
					- [2]: Average bitrate
					- [3]: Current bitrate

	Example:
		>>> result = getBitrate(session)
		>>> if result:
		>>>     video_min, video_max, video_avg, video_curr = result[0]
		>>>     audio_min, audio_max, audio_avg, audio_curr = result[1]
	"""
	service = session.nav.getCurrentService()
	if service:
		adapter = 0
		demux = 0
		try:
			stream = service.stream()
			if stream:
				streamdata = stream.getStreamingData()
				if streamdata:
					demux = int(streamdata.get("demux", demux))
					adapter = int(streamdata.get("adapter", adapter))
		except Exception:
			pass
		info = service.info()
		if info:
			vpid = info.getInfo(iServiceInformation.sVideoPID)
			apid = info.getInfo(iServiceInformation.sAudioPID)
			return eAVControl.measure_bitrate(adapter, demux, vpid, apid)
	return None

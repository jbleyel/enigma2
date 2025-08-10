from enigma import eAVControl, iServiceInformation


def getBitrate(session):
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

from datetime import datetime
from os import rename, remove, stat, sync
from os.path import exists, split
from time import localtime, mktime, time


from enigma import eTimer, eServiceReference, eServiceCenter, iServiceInformation, iRecordableService, quitMainloop

from Components.config import config
from Components.UsageConfig import preferredInstantRecordPath, defaultMoviePath
from Components.VirtualVideoDir import VirtualVideoDir

from RecordTimer import RecordTimerEntry
from Screens.MessageBox import MessageBox
from ServiceReference import ServiceReference

from Tools.Directories import fileExists
from Tools.Notifications import AddNotification


def calculateTime(hours, minutes, day_offset=0):
	cur_time = localtime()
	unix_time = mktime((cur_time.tm_year, cur_time.tm_mon, cur_time.tm_mday, hours, minutes, 0, cur_time.tm_wday, cur_time.tm_yday, cur_time.tm_isdst)) + day_offset
	return unix_time


def checkTimeSpan(begin_config, end_config):
	(begin_h, begin_m) = begin_config
	(end_h, end_m) = end_config
	cur_time = time()
	begin = calculateTime(begin_h, begin_m)
	end = calculateTime(end_h, end_m)
	if begin >= end:
		if cur_time < end:
			day_offset = -24.0 * 3600.0
			begin = calculateTime(begin_h, begin_m, day_offset)
		elif cur_time > end:
			day_offset = 24.0 * 3600.0
			end = calculateTime(end_h, end_m, day_offset)
		else:
			return False
	if cur_time > begin and cur_time < end:
		return True
	return False


def secondsToTimespanBegin(begin_config, end_config):
	sec = 300
	(begin_h, begin_m) = begin_config
	(end_h, end_m) = end_config
	cur_time = time()
	begin = calculateTime(begin_h, begin_m)
	end = calculateTime(end_h, end_m)
	if cur_time <= begin:
		sec = int(begin - cur_time)
	else:
		day_offset = +24.0 * 3600.0
		next_begin = calculateTime(begin_h, begin_m, day_offset)
		sec = int(next_begin - cur_time)
	sec += 10
	return sec


# lib/dvb/pmt.h
SERVICETYPE_PVR_DESCRAMBLE = 11


# iStaticServiceInformation


class StubInfo:
	def getName(self, sref):
		return split(sref.getPath())[1]

	def getLength(self, sref):
		return -1

	def getEvent(self, sref, *args):
		return None

	def isPlayable(self):
		return True

	def getInfo(self, sref, w):
		if w == iServiceInformation.sTimeCreate:
			return stat(sref.getPath()).st_ctime
		if w == iServiceInformation.sFileSize:
			return stat(sref.getPath()).st_size
		if w == iServiceInformation.sDescription:
			return sref.getPath()
		return 0

	def getInfoString(self, sref, w):
		return ''


stubInfo = StubInfo()


class PVRDescrambleConvertInfos:
	def __init__(self):
		self.navigation = None

	def getNavigation(self):
		if not self.navigation:
			import NavigationInstance
			if NavigationInstance:
				self.navigation = NavigationInstance.instance

		return self.navigation

	def getRecordings(self):
		recordings = []
		nav = self.getNavigation()
		if nav:
			recordings = nav.getRecordings()
			print("getRecordings : ", recordings)

		return recordings

	def getInstandby(self):
		from Screens.Standby import inStandby
		return inStandby

	def getCurrentMoviePath(self):
		if not fileExists(config.movielist.last_videodir.value):
			config.movielist.last_videodir.value = defaultMoviePath()
			config.movielist.last_videodir.save()

		curMovieRef = eServiceReference("2:0:1:0:0:0:0:0:0:0:" + config.movielist.last_videodir.value)
		return curMovieRef


class PVRDescrambleConvert(PVRDescrambleConvertInfos):
	def __init__(self):
		PVRDescrambleConvertInfos.__init__(self)
		config.misc.standbyCounter.addNotifier(self.enterStandby, initial_call=False)

		self.convertTimer = eTimer()
		self.convertTimer.callback.append(self.prepareConvert)

		self.stopConvertTimer = eTimer()
		self.stopConvertTimer.callback.append(self.stopConvert)

		self.timeIntervallTimer = eTimer()
		self.timeIntervallTimer.callback.append(self.recheckTimeIntervall)

		self.prepareTimer = eTimer()
		self.prepareTimer.callback.append(self.prepareFinished)

		self.second_prepareTimer = eTimer()
		self.second_prepareTimer.callback.append(self.second_prepareFinished)

		self.converting = None
		self.convertFilename = None
		self.currentPvr = None

		self.pvrLists = []
		self.pvrLists_tried = []
		self.descr_error = False

		self.oldService = None

		self.want_shutdown = False

		self.virtual_video_dir = VirtualVideoDir()

	def recheckTimeIntervall(self):
		self.timeIntervallTimer.stop()
		self.beginConvert()

	def scrambledRecordsLeft(self):
		scrambled_videos = self.virtual_video_dir.getSList()
		if not len(scrambled_videos):
			return False
		pvrlist_tried = 0
		self.want_shutdown = True
		for sref in scrambled_videos:
			if not sref.valid():
				continue
			if sref.flags & eServiceReference.mustDescent:
				continue
			if not sref.getPath():
				continue
			path = sref.getPath()
			if path in self.pvrLists_tried:
				pvrlist_tried += 1
		if len(scrambled_videos) == pvrlist_tried:
			return False
		return True

	def enterStandby(self, configElement):
		self.pvrLists_tried = []
		if config.recording.enable_descramble_in_standby.value:
			instandby = self.getInstandby()
			if not self.leaveStandby in instandby.onClose:
				instandby.onClose.append(self.leaveStandby)
			print("[PVRDescramble] enterStandby")
			self.beginConvert()

	def beginConvert(self):
		begin = config.recording.decrypt_start_time.value
		end = config.recording.decrypt_end_time.value
		if not checkTimeSpan(begin, end):
			print("[PVRDescramble] not in allowed time intervall --> skip descrambling")
			t_sec = secondsToTimespanBegin(begin, end)
			t_date = datetime.fromtimestamp(int(time() + t_sec)).strftime('%Y-%m-%d %H:%M:%S')
			print("[PVRDescramble] next check in %d seconds (%s)" % (t_sec, t_date))
			self.timeIntervallTimer.startLongTimer(t_sec)
			return

		# register record callback
		self.appendRecordEventCB()

		self.startConvertTimer()

	def leaveStandby(self):
		self.want_shutdown = False
		self.removeRecordEventCB()
		self.convertTimer.stop()
		self.prepareTimer.stop()
		self.second_prepareTimer.stop()
		self.timeIntervallTimer.stop()
		self.stopConvert()

	def startConvertTimer(self):
		self.convertTimer.start(3000, True)

	def startStopConvertTimer(self):
		self.stopConvertTimer.start(500, True)

	def appendRecordEventCB(self):
		nav = self.getNavigation()
		if nav:
			if self.gotRecordEvent not in nav.record_event:
				nav.record_event.append(self.gotRecordEvent)

	def removeRecordEventCB(self):
		nav = self.getNavigation()
		if nav:
			if self.gotRecordEvent in nav.record_event:
				nav.record_event.remove(self.gotRecordEvent)

	def gotRecordEvent(self, service, event):
		if service.getServiceType() == SERVICETYPE_PVR_DESCRAMBLE:
			if self.converting:
				if self.convertFilename:
					pvr_ori = self.convertFilename[0]
					if pvr_ori not in self.pvrLists_tried:
						self.pvrLists_tried.append(pvr_ori)
			if event == iRecordableService.evEnd:
				if self.getInstandby():
					self.beginConvert()
			elif event == iRecordableService.evPvrEof:
				self.stopConvert(convertFinished=True)
			elif event == iRecordableService.evRecordFailed:
				self.descr_error = True
				self.startStopConvertTimer()
		else:
			if event in (iRecordableService.evPvrTuneStart, iRecordableService.evTuneStart):
				if self.currentPvr:
					self.pvrLists.insert(0, self.currentPvr)
					self.currentPvr = None
					self.startStopConvertTimer()
			elif event == iRecordableService.evEnd:
				if self.getInstandby():
					self.beginConvert()

	def loadScrambledPvrList(self):
		self.pvrLists = []

		serviceHandler = eServiceCenter.getInstance()

		scrambled_videos = self.virtual_video_dir.getSList()
		for sref in scrambled_videos:

			if not sref.valid():
				continue

			if sref.flags & eServiceReference.mustDescent:
				continue

			path = sref.getPath()
			if not path:
				continue

			info = serviceHandler.info(sref)

			real_sref = "1:0:0:0:0:0:0:0:0:0:"
			if info is not None:
				real_sref = info.getInfoString(sref, iServiceInformation.sServiceref)

			if info is None:
				info = stubInfo

			begin = info.getInfo(sref, iServiceInformation.sTimeCreate)

			# convert separe-separated list of tags into a set
			name = info.getName(sref)
			scrambled = info.getInfo(sref, iServiceInformation.sIsScrambled)
			length = info.getLength(sref)
			if path in self.pvrLists_tried:
				continue

			if scrambled == 1:
				if False:
					print("====" * 20)
					print("[loadScrambledPvrList] sref.toString() : ", sref.toString())
					print("[loadScrambledPvrList] sref.getPath() : ", path)
					print("[loadScrambledPvrList] name : ", name)
					print("[loadScrambledPvrList] begin : ", begin)
					print("[loadScrambledPvrList] length : ", length)
					print("[loadScrambledPvrList] scrambled : ", scrambled)
					print("")
					print("====" * 20)
				rec = (begin, sref, name, length, real_sref)
				if rec not in self.pvrLists:
					self.pvrLists.append(rec)

		self.pvrLists.sort()

	def checkBeforeStartConvert(self):
		return self.pvrLists and (not bool(self.getRecordings())) and (not self.converting) and self.getInstandby()

	def prepareConvert(self):

		print("[PVRDescramble] get unscrambled recordings")
		self.loadScrambledPvrList()

		if not self.checkBeforeStartConvert():
			return

		self.currentPvr = self.pvrLists.pop(0)
		if self.currentPvr is None:
			if self.want_shutdown:
				quitMainloop(1)
			return

		(_begin, sref, name, length, real_ref) = self.currentPvr
		self.my_nav = self.getNavigation()
		if self.my_nav and self.my_nav is not None:
			self.my_nav.playService(eServiceReference(real_ref))
			self.prepareTimer.start(10000, True)

	def prepareFinished(self):
		if self.my_nav and self.my_nav is not None:
			self.my_nav.stopService()
		self.prepareTimer.stop()
		self.second_prepareTimer.start(1000, True)

	def second_prepareFinished(self):
		self.second_prepareTimer.stop()
		self.startConvert()

	def startConvert(self):

		(_begin, sref, name, length, real_ref) = self.currentPvr

		m_path = sref.getPath()
		sref = eServiceReference(real_ref + m_path)

		begin = int(time())
		end = begin + 3600  # dummy
		#end = begin + int(length) + 2
		description = ""
		eventid = None

		if isinstance(sref, eServiceReference):
			sref = ServiceReference(sref)

		if m_path.endswith('.ts'):
			m_path = m_path[:-3]

		filename = m_path + "_pvrdesc"

		recording = RecordTimerEntry(sref, begin, end, name, description, eventid, dirname=preferredInstantRecordPath(), filename=filename)
		recording.dontSave = True
		recording.autoincrease = True
		recording.setAutoincreaseEnd()
		recording.pvrConvert = True  # do not handle evStart event

		nav = self.getNavigation()
		simulTimerList = nav.RecordTimer.record(recording)
		if simulTimerList is None:  # no conflict
			recordings = self.getRecordings()
			if len(recordings) == 1:
				self.converting = recording
				self.convertFilename = (sref.getPath(), filename + ".ts")
			else:
				print("[PVRDescrambleConvert] error, wrong recordings info.")
		else:
			self.currentPvr = None
			self.beginConvert()

			if len(simulTimerList) > 1:  # with other recording
				print("[PVRDescrambleConvert] conflicts !")
			else:
				print("[PVRDescrambleConvert] Couldn't record due to invalid service %s" % sref)
			recording.autoincrease = False

		print("[PVRDescrambleConvert] startConvert, self.converting : ", self.converting)

	def removeStr(self, fileName, s):
		if fileName.find(s) == -1:
			return fileName

		sp = fileName.split(s)

		return sp[0] + sp[1]

	def renameDelPvr(self, pvrName, subName):
		targetName = pvrName + subName
		outName = self.removeStr(pvrName, ".ts") + "_del" + ".ts" + subName

		if fileExists(targetName, "w"):
			#print("RENAME %s -> %s" % (targetName, outName))
			rename(targetName, outName)
			return outName

		return None

	def renameConvertPvr(self, pvrName, subName):
		targetName = pvrName + subName
		outName = self.removeStr(pvrName, "_pvrdesc") + subName

		if fileExists(targetName, "w"):
			#print("RENAME %s -> %s" % (targetName, outName))
			rename(targetName, outName)
			return outName

		return None

	def renamePvr(self, pvr_ori, pvr_convert):
		pvr_ori_del = self.renameDelPvr(pvr_ori, "")
		if not pvr_ori_del:
			return None

		self.renameDelPvr(pvr_ori, ".meta")
		self.renameDelPvr(pvr_ori, ".ap")
		self.renameDelPvr(pvr_ori, ".sc")
		self.renameDelPvr(pvr_ori, ".cuts")

		pvr_convert_fixed = self.renameConvertPvr(pvr_convert, "")
		if not pvr_convert_fixed:
			return None

		self.renameConvertPvr(pvr_convert, ".meta")
		self.renameConvertPvr(pvr_convert, ".ap")
		self.renameConvertPvr(pvr_convert, ".sc")
		self.renameConvertPvr(pvr_convert, ".cuts")

		if exists(pvr_convert[:-3] + '.eit'):
			remove(pvr_convert[:-3] + '.eit')

		return pvr_ori_del

	def stopConvert(self, convertFinished=False):
		name = "Unknown"
		if self.currentPvr:
			(_begin, sref, name, length, real_ref) = self.currentPvr
			self.currentPvr = None

		if self.converting:
			nav = self.getNavigation()
			nav.RecordTimer.removeEntry(self.converting)
			convertFilename = self.convertFilename
			self.converting = None
			self.convertFilename = None

			if convertFilename:
				(pvr_ori, pvr_convert) = convertFilename
				if convertFinished:
					# check size
					if exists(pvr_convert) and stat(pvr_convert).st_size:
						pvr_ori_del = self.renamePvr(pvr_ori, pvr_convert)
						self.keepMetaData(pvr_ori)
						if pvr_ori_del:
							self.deletePvr(pvr_ori_del)
						self.addNotification(_("A PVR descramble converting is finished.\n%s") % name)
					else:
						self.deletePvr(pvr_convert)
				else:
					if convertFilename[0] in self.pvrLists_tried and not self.descr_error:
						self.pvrLists_tried.remove(convertFilename[0])
					self.descr_error = False
					self.deletePvr(pvr_convert)
			self.virtual_video_dir.writeSList()

		sync()

	def keepMetaData(self, pvr_ori):
		del_meta = pvr_ori[:-3] + "_del" + ".ts.meta"
		new_meta = pvr_ori + ".meta"
		orig_content = []
		tmp_content = []
		if exists(new_meta) and exists(del_meta):
			with open(del_meta) as f:
				orig_content = f.readlines()
			with open(new_meta) as f:
				tmp_content = f.readlines()
		if len(orig_content) >= 9 and len(tmp_content) >= 9:
			orig_content[8] = tmp_content[8]
			new_content = ""
			for x in orig_content:
				new_content += x
			with open(new_meta, "w") as f:
				f.write(new_content)

	def deletePvr(self, filename):
		serviceHandler = eServiceCenter.getInstance()
		ref = eServiceReference(1, 0, filename)
		offline = serviceHandler.offlineOperations(ref)
		if offline.deleteFromDisk(0):
			print("[PVRDescrambleConvert] delete failed : ", filename)

	def addNotification(self, text):
		AddNotification(MessageBox, text, type=MessageBox.TYPE_INFO, timeout=5)


pvr_descramble_convert = PVRDescrambleConvert()

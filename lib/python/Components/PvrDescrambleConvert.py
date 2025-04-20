from datetime import datetime
from os import rename, remove, stat, sync
from os.path import exists, split
from time import localtime, mktime, time


from enigma import eTimer, eServiceReference, eServiceCenter, iServiceInformation, iRecordableService, quitMainloop

from Components.config import config
from Components.ScrambledRecordings import ScrambledRecordings
from Components.UsageConfig import preferredInstantRecordPath, defaultMoviePath

from RecordTimer import RecordTimerEntry
from Screens.MessageBox import MessageBox
from ServiceReference import ServiceReference

from Tools.Directories import fileExists, fileReadLines, fileWriteLines
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
		return ""


stubInfo = StubInfo()


class PVRDescrambleConvert():
	def __init__(self):
		config.misc.standbyCounter.addNotifier(self.enterStandby, initial_call=False)
		self.convertTimer = eTimer()
		self.convertTimer.callback.append(self.prepareConvert)
		self.stopConvertTimer = eTimer()
		self.stopConvertTimer.callback.append(self.stopConvert)
		self.timeIntervallTimer = eTimer()
		self.timeIntervallTimer.callback.append(self.recheckTimeIntervall)
		self.prepareTimer = eTimer()
		self.prepareTimer.callback.append(self.prepareFinished)
		self.secondPrepareTimer = eTimer()
		self.secondPrepareTimer.callback.append(self.secondPrepareFinished)
		self.converting = None
		self.convertFilename = None
		self.currentPvr = None
		self.pvrLists = []
		self.pvrListsTried = []
		self.descrableError = False
		self.oldService = None
		self.wantShutdown = False
		self.navigation = None
		self.scrambledRecordings = ScrambledRecordings()

	def getRecordings(self):
		recordings = []
		nav = self.getNavigation()
		if nav:
			recordings = nav.getRecordings()
		return recordings

	def getInstandby(self):
		from Screens.Standby import inStandby
		return inStandby

	def getNavigation(self):
		if not self.navigation:
			import NavigationInstance
			if NavigationInstance:
				self.navigation = NavigationInstance.instance
		return self.navigation

	def recheckTimeIntervall(self):
		self.timeIntervallTimer.stop()
		self.beginConvert()

	def scrambledRecordsLeft(self):
		scrambledFiles = self.scrambledRecordings.readList()
		print("[PVRDescramble] scrambledRecordsLeft : ", scrambledFiles)
		if scrambledFiles:
			tried = 0
			self.wantShutdown = True
			for sref in scrambledFiles:
				if not sref.valid():
					continue
				if sref.flags & eServiceReference.mustDescent:
					continue
				if not sref.getPath():
					continue
				path = sref.getPath()
				if path in self.pvrListsTried:
					tried += 1
			return len(scrambledFiles) != tried
		return False

	def enterStandby(self, configElement):
		print("[PVRDescramble] enterStandby")
		self.pvrListsTried = []
		if config.recording.enable_descramble_in_standby.value:
			instandby = self.getInstandby()
			if not self.leaveStandby in instandby.onClose:
				instandby.onClose.append(self.leaveStandby)
			print("[PVRDescramble] enterStandby")
			self.beginConvert()

	def beginConvert(self):
		print("[PVRDescrambleConvert] beginConvert")
		begin = config.recording.decrypt_start_time.value
		end = config.recording.decrypt_end_time.value
		if not checkTimeSpan(begin, end):
			print("[PVRDescramble] not in allowed time intervall --> skip descrambling")
			seconds = secondsToTimespanBegin(begin, end)
			startDate = datetime.fromtimestamp(int(time() + seconds)).strftime("%Y-%m-%d %H:%M:%S")
			print("[PVRDescramble] next check in %d seconds (%s)" % (seconds, startDate))
			self.timeIntervallTimer.startLongTimer(seconds)
			return

		# register record callback
		self.appendRecordEventCB()

		self.startConvertTimer()

	def leaveStandby(self):
		print("[PVRDescramble] leaveStandby")
		self.wantShutdown = False
		self.removeRecordEventCB()
		self.convertTimer.stop()
		self.prepareTimer.stop()
		self.secondPrepareTimer.stop()
		self.timeIntervallTimer.stop()
		self.stopConvert()

	def startConvertTimer(self):
		print("[PVRDescrambleConvert] startConvertTimer")
		self.convertTimer.start(3000, True)

	def startStopConvertTimer(self):
		print("[PVRDescrambleConvert] startStopConvertTimer")
		self.stopConvertTimer.start(500, True)

	def appendRecordEventCB(self):
		print("[PVRDescrambleConvert] appendRecordEventCB")
		nav = self.getNavigation()
		if nav:
			if self.gotRecordEvent not in nav.record_event:
				nav.record_event.append(self.gotRecordEvent)

	def removeRecordEventCB(self):
		print("[PVRDescrambleConvert] removeRecordEventCB")
		nav = self.getNavigation()
		if nav:
			if self.gotRecordEvent in nav.record_event:
				nav.record_event.remove(self.gotRecordEvent)

	def gotRecordEvent(self, service, event):
		print("[PVRDescrambleConvert] gotRecordEvent : ", service, event, service.getServiceType())
		if service.getServiceType() == SERVICETYPE_PVR_DESCRAMBLE:
			print("[PVRDescrambleConvert] gotRecordEvent SERVICETYPE_PVR_DESCRAMBLE self.converting / self.convertFilename", self.converting, self.convertFilename)
			if self.converting:
				if self.convertFilename:
					print("[PVRDescrambleConvert] gotRecordEvent SERVICETYPE_PVR_DESCRAMBLE self.convertFilename[0]", self.convertFilename[0])
					print("[PVRDescrambleConvert] gotRecordEvent SERVICETYPE_PVR_DESCRAMBLE self.pvrListsTried", self.pvrListsTried)
					pvrOri = self.convertFilename[0]
					if pvrOri not in self.pvrListsTried:
						self.pvrListsTried.append(pvrOri)
			if event == iRecordableService.evEnd:
				if self.getInstandby():
					self.beginConvert()
			elif event == iRecordableService.evPvrEof:
				self.stopConvert(convertFinished=True)
			elif event == iRecordableService.evRecordFailed:
				self.descrableError = True
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
		print("[PVRDescramble] loadScrambledPvrList")
		print("[PVRDescramble] loadScrambledPvrList self.pvrListsTried:", self.pvrListsTried)
		self.pvrLists = []
		serviceHandler = eServiceCenter.getInstance()
		for sref in self.scrambledRecordings.readList():
			if not sref.valid() or sref.flags & eServiceReference.mustDescent:
				continue
			path = sref.getPath()
			if not path:
				continue

			print("[PVRDescramble] loadScrambledPvrList path=", path)

			info = serviceHandler.info(sref)

			realServiceRef = "1:0:0:0:0:0:0:0:0:0:"
			if info is not None:
				realServiceRef = info.getInfoString(sref, iServiceInformation.sServiceref)
				realServiceRef = eServiceReference(realServiceRef).toReferenceString()  # Remove name

			if info is None:
				info = stubInfo

			begin = info.getInfo(sref, iServiceInformation.sTimeCreate)

			name = info.getName(sref)
			scrambled = info.getInfo(sref, iServiceInformation.sIsCrypted)
			length = info.getLength(sref)

			if path in self.pvrListsTried:
				continue

			if scrambled == 1:
				if True:
					print("====" * 20)
					print("[loadScrambledPvrList] sref.toString() : ", sref.toString())
					print("[loadScrambledPvrList] sref.getPath() : ", path)
					print("[loadScrambledPvrList] name : ", name)
					print("[loadScrambledPvrList] begin : ", begin)
					print("[loadScrambledPvrList] length : ", length)
					print("[loadScrambledPvrList] scrambled : ", scrambled)
					print("")
					print("====" * 20)
				rec = (begin, sref, name, length, realServiceRef)
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
			if self.wantShutdown:
				quitMainloop(1)
			return

		(_begin, sref, name, length, real_ref) = self.currentPvr
		self.my_nav = self.getNavigation()
		if self.my_nav and self.my_nav is not None:
			self.my_nav.playService(eServiceReference(real_ref))
			self.prepareTimer.start(10000, True)

	def prepareFinished(self):
		print("[PVRDescrambleConvert] prepareFinished")
		if self.my_nav and self.my_nav is not None:
			self.my_nav.stopService()
		self.prepareTimer.stop()
		self.secondPrepareTimer.start(1000, True)

	def secondPrepareFinished(self):
		print("[PVRDescrambleConvert] second_prepareFinished")
		self.secondPrepareTimer.stop()
		self.startConvert()

	def startConvert(self):
		print("[PVRDescrambleConvert] startConvert")

		(_begin, sref, name, length, real_ref) = self.currentPvr

		m_path = sref.getPath()
		sref = eServiceReference(real_ref)
		sref.setPath(m_path)

		begin = int(time())
		end = begin + 3600  # dummy
		#end = begin + int(length) + 2
		description = ""
		eventid = None

		if isinstance(sref, eServiceReference):
			sref = ServiceReference(sref)

		if m_path.endswith(".ts"):
			m_path = m_path[:-3]

		filename = f"{m_path}_pvrdesc"

		recording = RecordTimerEntry(sref, begin, end, name, description, eventid, dirname=preferredInstantRecordPath(), filename=filename)
		recording.dontSave = True
		recording.autoincrease = True
		recording.marginAfter = 0
		recording.marginBefore = 0
		recording.eventBegin = begin
		recording.eventEnd = end
		recording.setAutoincreaseEnd()
		recording.pvrConvert = True  # do not handle evStart event

		nav = self.getNavigation()
		simulTimerList = nav.RecordTimer.record(recording)
		if simulTimerList is None:  # no conflict
			recordings = self.getRecordings()
			if len(recordings) == 1:
				self.converting = recording
				self.convertFilename = (sref.getPath(), f"{filename}.ts")
			else:
				print("[PVRDescrambleConvert] error, wrong recordings info.")
		else:
			self.currentPvr = None
			self.beginConvert()

			if len(simulTimerList) > 1:  # with other recording
				print("[PVRDescrambleConvert] conflicts !")
			else:
				print(f"[PVRDescrambleConvert] Couldn't record due to invalid service {sref}")
			recording.autoincrease = False

		print(f"[PVRDescrambleConvert] startConvert, self.converting : {self.converting}")

	def removeStr(self, fileName, s):
		if fileName.find(s) == -1:
			return fileName
		sp = fileName.split(s)
		return sp[0] + sp[1]

	def renameDelPvr(self, pvrName, subName):
		targetName = pvrName + subName
		outName = self.removeStr(pvrName, ".ts") + f"_del.ts{subName}"

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

	def renamePvr(self, originalFileName, convertedFileName):
		originalDeleteFilename = self.renameDelPvr(originalFileName, "")
		if not originalDeleteFilename:
			return None

		self.renameDelPvr(originalFileName, ".meta")
		self.renameDelPvr(originalFileName, ".ap")
		self.renameDelPvr(originalFileName, ".sc")
		self.renameDelPvr(originalFileName, ".cuts")

		if not self.renameConvertPvr(convertedFileName, ""):
			return None

		self.renameConvertPvr(convertedFileName, ".meta")
		self.renameConvertPvr(convertedFileName, ".ap")
		self.renameConvertPvr(convertedFileName, ".sc")
		self.renameConvertPvr(convertedFileName, ".cuts")

		if exists(f"{convertedFileName[:-3]}.eit"):
			remove(f"{convertedFileName[:-3]}.eit")

		return originalDeleteFilename

	def stopConvert(self, convertFinished=False):
		print("[PVRDescrambleConvert] stopConvert")
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
				(originalFileName, convertedFileName) = convertFilename
				if convertFinished:
					# check size
					if exists(convertedFileName) and stat(convertedFileName).st_size:
						originalDeleteFilename = self.renamePvr(originalFileName, convertedFileName)
						self.keepMetaData(originalFileName)
						if originalDeleteFilename:
							self.deletePvr(originalDeleteFilename)
						self.addNotification(_("A PVR descramble converting is finished.\n%s") % name)
					else:
						self.deletePvr(convertedFileName)
				else:
					if originalFileName in self.pvrListsTried and not self.descrableError:
						self.pvrListsTried.remove(originalFileName)
					self.descrableError = False
					self.deletePvr(convertedFileName)
			self.scrambledRecordings.writeList()

		sync()

	def keepMetaData(self, originalFileName):
		originalMetaFileName = f"{originalFileName[:-3]}_del.ts.meta"
		newMetaFileName = f"{originalFileName}.meta"
		origMetaContent = []
		newMetaContent = []

		print(f"[PVRDescrambleConvert] keepMetaData newMetaFileName {newMetaFileName}")
		print(f"[PVRDescrambleConvert] keepMetaData originalMetaFileName {originalMetaFileName}")

		if exists(newMetaFileName) and exists(originalMetaFileName):
			origMetaContent = fileReadLines(originalMetaFileName, default=[])
			newMetaContent = fileReadLines(newMetaFileName, default=[])

		print(f"[PVRDescrambleConvert] keepMetaData origMetaContent {origMetaContent}")
		print(f"[PVRDescrambleConvert] keepMetaData newMetaContent {newMetaContent}")

		if len(origMetaContent) >= 10 and len(newMetaContent) >= 10:
			origMetaContent[9] = newMetaContent[9]
			fileWriteLines(newMetaFileName, origMetaContent)
		else:
			print("[PVRDescrambleConvert] keepMetaData NOT write")

	def deletePvr(self, filename):
		serviceHandler = eServiceCenter.getInstance()
		ref = eServiceReference(1, 0, filename)
		offline = serviceHandler.offlineOperations(ref)
		if offline.deleteFromDisk(0):
			print(f"[PVRDescrambleConvert] delete failed : {filename}")

	def addNotification(self, text):
		AddNotification(MessageBox, text, type=MessageBox.TYPE_INFO, timeout=5)


pvr_descramble_convert = PVRDescrambleConvert()

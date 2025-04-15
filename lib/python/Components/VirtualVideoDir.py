from os import remove
from os.path import exists, join
from struct import unpack
from time import sleep, time
from enigma import eServiceReference, eServiceCenter, iServiceInformation

from Components.config import config
from Tools.Directories import fileReadLines, fileWriteLines


class VirtualVideoDir:

	NEWEST_VIDEOS = 1
	VIDEO_HOME = 2
	LOCAL_LIST = 3
	GROUPED_LIST = 4
	MOVIEDB_LIST = 5
	SCRAMBLE_LIST_FILE = "/etc/enigma2/.scrambled_video_list"
	LOCAL_LIST_FILE = "/tmp/.video_list"

	def __init__(self):
		self.infofile = join(config.usage.default_path.value, ".vdirinfo")
		self.isLocked = 0
		self.updateTime()

	def setInfoFile(self, info_file=None):
		self.infofile = info_file or self.LOCAL_LIST_FILE

	def deleteInfoFile(self, info_file=None):
		try:
			remove(info_file or self.LOCAL_LIST_FILE)
		except OSError as e:
			pass

	def updateTime(self):
		self.max_time = int(time()) - config.usage.days_mark_as_new.value * 86400

	def getMovieTimeDiff(self, ref):
		serviceHandler = eServiceCenter.getInstance()
		info = serviceHandler.info(ref)
		time = info.getInfo(ref, iServiceInformation.sTimeCreate) if info else 0
		return time - self.max_time

	def isUnseen(self, moviename):
		ret = True
		moviename = moviename + ".cuts"
		if exists(moviename):
			f = open(moviename, "rb")
			packed = f.read()
			f.close()
			while len(packed) > 0:
				packedCue = packed[:12]
				packed = packed[12:]
				cue = unpack(">QI", packedCue)
				if cue[1] == 3:
					ret = False
					break
		return ret

	def getServiceRef(self, movie):
		return eServiceReference(f"{"1" if movie.endswith("ts") else "4097"}:0:0:0:0:0:0:0:0:0:{movie}")

	def getServiceRefDir(self, folder):
		return eServiceReference(eServiceReference.idFile, eServiceReference.flagDirectory, folder)

	def stripMovieName(self, movie):
		movie = movie.rstrip("\n")
		return movie.replace("\x00", "")

	def getVList(self, list_type=VIDEO_HOME):  # NEWEST_VIDEOS):
		vlist = []
		if list_type in (self.NEWEST_VIDEOS, self.LOCAL_LIST):
			self.updateTime()
			lines = fileReadLines(self.infofile, default=[])
			for line in lines:
				movie = self.stripMovieName(line)
				if exists(movie):
					ref = self.getServiceRef(movie)
					if list_type == self.LOCAL_LIST:
						vlist.append(ref)
					elif self.getMovieTimeDiff(ref) >= 0:
						if not config.usage.only_unseen_mark_as_new.value:
							vlist.append(ref)
						elif config.usage.only_unseen_mark_as_new.value and self.isUnseen(movie):
							vlist.append(ref)
		elif list_type == self.VIDEO_HOME:
			for video_dir in config.movielist.videodirs.value:
				if exists(video_dir):
					video_dir = join(video_dir, "")
					ref = self.getServiceRefDir(video_dir)
					vlist.append(ref)
		return vlist

	def writeVList(self, append="", overwrite=False):
		self.updateTime()
		result = []
		if not overwrite:
			lines = fileReadLines(self.infofile, default=[])
			for x in lines:
				movie = self.stripMovieName(x)
				if movie and exists(str(movie)):
					ref = self.getServiceRef(movie)
					if self.getMovieTimeDiff(ref) >= 0:
						if not config.usage.only_unseen_mark_as_new.value:
							result.append(x)
						elif config.usage.only_unseen_mark_as_new.value and self.isUnseen(movie):
							result.append(x)
		if isinstance(append, list):
			result.extend(append)
		elif append != "":
			result.append(append)
		if not fileWriteLines(self.infofile, result):
			if self.isLocked < 11:
				sleep(.300)
				self.isLocked += 1
				self.writeVList(append=append)
			else:
				self.isLocked = 0

	def getSList(self):
		vlist = []
		lines = fileReadLines(self.SCRAMBLE_LIST_FILE, default=[])
		for line in lines:
			movie = self.stripMovieName(line)
			if exists(movie) and not exists(movie + ".del"):
				ref = self.getServiceRef(movie)
				vlist.append(ref)
		print("[VirtualVideoDir] getSList", vlist)
		return vlist

	def writeSList(self, append="", overwrite=False):
		result = []
		serviceHandler = eServiceCenter.getInstance()
		if not overwrite:
			lines = fileReadLines(self.SCRAMBLE_LIST_FILE, default=[])
			for x in lines:
				movie = self.stripMovieName(x)
				if movie and exists(str(movie)):
					sref = self.getServiceRef(movie)
					info = serviceHandler.info(sref)
					scrambled = info.getInfo(sref, iServiceInformation.sIsCrypted)
					if scrambled == 1:
						result.append(x)
		if isinstance(append, list):
			result.extend(append)
		elif append != "":
			result.append(append)
		print("[VirtualVideoDir] writeSList", result)
		if not fileWriteLines(self.SCRAMBLE_LIST_FILE, result):
			if self.isLocked < 11:
				sleep(.300)
				self.isLocked += 1
				self.writeSList(append=append)
			else:
				self.isLocked = 0

from os.path import exists
from time import sleep
from enigma import eServiceCenter, iServiceInformation

from Tools.Directories import fileReadLines, fileWriteLines


class ScrambledRecordings:
	SCRAMBLE_LIST_FILE = "/etc/enigma2/.scrambled_video_list"

	def __init__(self):
		self.isLocked = 0

	def stripMovieName(self, movie):
		movie = movie.rstrip("\n")
		return movie.replace("\x00", "")

	def readList(self):
		files = []
		lines = fileReadLines(self.SCRAMBLE_LIST_FILE, default=[])
		for line in lines:
			movie = self.stripMovieName(line)
			if exists(movie) and not exists(movie + ".del"):
				ref = self.getServiceRef(movie)
				files.append(ref)
		print("[ScrambledRecordings] getreadListSList", files)
		return files

	def writeList(self, append="", overwrite=False):
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
		print("[ScrambledRecordings] writeList", result)
		if not fileWriteLines(self.SCRAMBLE_LIST_FILE, result):
			if self.isLocked < 11:
				sleep(.300)
				self.isLocked += 1
				self.writeList(append=append)
			else:
				self.isLocked = 0

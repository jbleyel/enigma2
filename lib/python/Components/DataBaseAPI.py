from difflib import SequenceMatcher
from os import remove, stat, walk
from os.path import exists, dirname, realpath, isdir, join, basename, split
from sqlite3 import connect, ProgrammingError, OperationalError, DatabaseError
from struct import unpack
from threading import Thread, Lock, current_thread
from enigma import eServiceCenter, eServiceReference, iServiceInformation, eTimer
from Components.Task import Task, Job, job_manager
from Components.config import config, ConfigDirectory, ConfigYesNo, ConfigSelection
from Scheduler import functionTimers
from Screens.MessageBox import MessageBox
from Tools.Notifications import AddPopup
from Tools.MovieInfoParser import getExtendedMovieDescription

BASEINIT = None
lock = Lock()


config.misc.movielist_use_moviedb_autoupdate = ConfigYesNo(default=False)
config.misc.db_path = ConfigDirectory(default="/media/hdd/")
config.misc.db_enabled = ConfigYesNo(default=True)
config.misc.timer_show_movie_available = ConfigSelection(choices=[
	(0, _("Off")),
	(1, _("Title")),
	(2, _("Title / Description")),
	], default=2)


class LOGLEVEL:
	ERROR = 4
	WARN = 3
	INFO = 2
	ALL = 1

	def __init__(self):
		pass


logLevel = LOGLEVEL()
curLevel = logLevel.ALL


def debugPrint(str, level=0):
	if level >= curLevel:
		print(f"[DataBase] {str}")


class DatabaseJob(Job):
	def __init__(self, fnc, args, title):
		Job.__init__(self, title)
		self.databaseJob = DatabaseTask(self, fnc, args, title)

	def abort(self):
		self.databaseJob.abort()

	def stop(self):
		self.databaseJob.stop()


class DatabaseTask(Task):
	def __init__(self, job, fnc, args, title=""):
		Task.__init__(self, job, "")
		self.dbthread = Thread(target=fnc, args=args[1])
		self.stopFunction = args[0]
		self.end = 100
		self.name = title
		self.msgtxt = _("Database update was finished")

	def prepare(self):
		self.error = None

	def run(self, callback):
		self.callback = callback
		self.dbthread.start()

	def stop(self):
		Task.processFinished(self, 0)
		if self.stopFunction and callable(self.stopFunction):
			self.stopFunction()
		debugPrint("job finished", LOGLEVEL.INFO)
# from Screens.Standby import inStandby
# if not inStandby:
# AddPopup(text = self.msgtxt, type = MessageBox.TYPE_INFO, timeout = 20, id = "db_update_stopped")

	def abort(self):
		self.msgtxt = _("Database update was cancelled")
		debugPrint("job cancelled", LOGLEVEL.INFO)
		self.stop()


class CommonDataBase():
	def __init__(self, dbFile=None):
		dbPath = join(config.misc.db_path.value, "")
		if not exists(dbPath):
			dbPath = "/media/hdd/"
		self.dbFile = join(dbPath, dbFile or "media.db")
		debugPrint(f"init database: {self.dbFile}", LOGLEVEL.INFO)
		self.cursor = None
		self.table = None
		self.locked = False
		self.tableStructure = None
		self.dbthreadKill = False
		self.dbthreadRunning = False
		self.dbthreadName = _("Update Database")
		self.dbthreadId = None
		self.isInitiated = False
		self.ignoreThreadCheck = False
		self.db = None

	def doInit(self):
		pass

	def connectDataBase(self, readonly=False):
		if not config.misc.db_enabled.value:
			return False
		if not self.isInitiated:
			self.doInit()
		if not self.ignoreThreadCheck and self.dbthreadId is not None and not readonly:
			cur_id = current_thread().ident
			if cur_id != self.dbthreadId:
				debugPrint("connecting failed --> THREAD error! another thread is using the database", LOGLEVEL.ERROR)
				return False
		if self.locked and not readonly:
			debugPrint("connecting failed --> database locked !", LOGLEVEL.ERROR)
			return False
		if not self.cursor:
			# TODO LockDB
			debugPrint(f"connect table {self.table} of database: {self.dbFile}", LOGLEVEL.ALL)
			db_dir = dirname(self.dbFile)
			if not exists(db_dir):
				debugPrint(f"connect table failed --> {db_dir} does not exist", LOGLEVEL.ERROR)
				return False
			chk_same_thread = not self.ignoreThreadCheck and True or False
			self.db = connect(self.dbFile, check_same_thread=chk_same_thread)
			self.cursor = self.db.cursor()
			sqlcmd = "PRAGMA case_sensitive_like=ON;"
			self.executeSQL(sqlcmd, readonly=True)
		if self.cursor and self.table is not None:
			return True
		return False

	def commitDB(self):
		txt = ""
		if not hasattr(self, "db"):
			txt = "not opened --> skip committing"
			debugPrint(txt, LOGLEVEL.ERROR)
		hasError = True
		try:
			lock.acquire(True)
			if self.db:
				self.db.commit()
			hasError = False
		except ProgrammingError as errmsg:
			txt = _("ERROR at committing database changes: ProgrammingError")
		except OperationalError as errmsg:
			txt = _("ERROR at committing database changes: OperationalError")
		finally:
			errmsg = ""
			lock.release()
		if hasError:
			txt += "\n"
			txt += str(errmsg)
			debugPrint(txt, LOGLEVEL.ERROR)
			txt = _("Error during committing changes")
			AddPopup(text=txt, type=MessageBox.TYPE_ERROR, timeout=0, id="db_error")
		return not hasError

	def closeDB(self):
		txt = ""
		if not hasattr(self, "db"):
			txt = "not opened --> skip  closing"
			debugPrint(txt, LOGLEVEL.ERROR)
		hasError = True
		try:
			lock.acquire(True)
			self.cursor = None
			if self.db:
				self.db.close()
			hasError = False
		except ProgrammingError as errmsg:
			txt = _("Programming ERROR at closing database")
		except OperationalError as errmsg:
			txt = _("Operational ERROR at closing database")
		finally:
			errmsg = ""
			lock.release()
		if hasError:
			txt += "\n"
			txt += str(errmsg)
			debugPrint(txt, LOGLEVEL.ERROR)
			txt = _("Error at closing database")
			AddPopup(text=txt, type=MessageBox.TYPE_ERROR, timeout=0, id="db_error")
		return not hasError

	def executeSQL(self, sqlcmd, args=[], readonly=False):
		if self.connectDataBase(readonly):
			ret = []
			debugPrint(f"SQL cmd: {sqlcmd}", LOGLEVEL.ALL)
			txt = "\n"
			for i in args:
				txt += f"{i}\n"
			debugPrint(f"SQL arguments: {txt}", LOGLEVEL.ALL)
			if not readonly:
				self.locked = True
			hasError = True
			try:
				lock.acquire(True)
				if self.cursor:
					self.cursor.execute(sqlcmd, args)
					ret = self.cursor.fetchall()
				hasError = False
			except ProgrammingError as errmsg:
				txt = f"Programming ERROR at SQL command: {sqlcmd}"
				if len(args):
					txt += "\n"
					for arg in args:
						txt += f"{arg}\n"
			except DatabaseError as errmsg:
				txt = f"Database ERROR at SQL command: {sqlcmd}"
				if len(args):
					txt += "\n"
					for arg in args:
						txt += f"{arg}\n"
				try:
					self.closeDB()
				except OSError:
					pass
				if str(errmsg).find("malformed") != -1:
					txt += "\n---> try to delete malformed database"
					try:
						remove(self.dbFile)
					except OSError:
						pass
					self.isInitiated = False
			except Exception as errmsg:
				txt = f"Database ERROR at SQL command: {sqlcmd}"
			finally:
				errmsg = ""
				lock.release()
			if hasError:
				txt += "\n"
				txt += str(errmsg)
				debugPrint(txt, LOGLEVEL.ERROR)
				self.disconnectDataBase()
				txt = _("Error during database transaction")
			if not readonly:  # AddPopup(text = txt, type = MessageBox.TYPE_ERROR, timeout = 0, id = "db_error")
				self.locked = False
			return (not hasError, ret)

	def disconnectDataBase(self, readonly=False):
		if self.cursor is not None:
			debugPrint(f"disconnect table {self.table} of database: {self.dbFile}", LOGLEVEL.ALL)
			if self.dbthreadId is not None:
				cur_id = current_thread().ident
				if cur_id != self.dbthreadId:
					debugPrint("connecting failed --> THREAD error! another thread is using the database", LOGLEVEL.ERROR)
					return False
			if not readonly:
				self.commitDB()
			self.closeDB()
			self.cursor = None
			# TODO unlockDB

	def doVacuum(self):
		if self.connectDataBase():
			self.executeSQL("VACUUM")

	def createTable(self, fields):
		if self.table and self.connectDataBase():
			field_str = "("
			for name in fields:
				field_str += f"{name} {fields[name]},"
			if field_str.endswith(","):
				field_str = field_str[:-1] + ")"
			self.executeSQL(f"CREATE TABLE if not exists {self.table} {field_str}")
			self.commitDB()

	def createTableIndex(self, idx_name, fields, unique=True):
		if self.table and self.connectDataBase():
			unique_txt = "UNIQUE"
			if not unique:
				unique_txt = ""
			idxFields = ""
			if isinstance(fields, str):
				idxFields = fields
			else:
				for field in fields:
					idxFields += f"{field}, "
			if idxFields.endswith(", "):
				idxFields = idxFields[:-2]
			sqlcmd = f"CREATE {unique_txt} INDEX IF NOT EXISTS {idx_name} ON {self.table} ({idxFields});"
			self.executeSQL(sqlcmd)

	def getTableStructure(self):
		if self.tableStructure is None or not len(self.tableStructure):
			structure = {}
			if self.table and self.connectDataBase():
				sqlret = self.executeSQL(f"PRAGMA table_info('{self.table}');")
				if sqlret and sqlret[0]:
					rows = sqlret[1]
				else:
					return structure
				for row in rows:
					structure[str(row[1])] = str(row[2])
				debugPrint(f"Data structure of table: {self.table}\n{str(structure)}", LOGLEVEL.ALL)
			self.tableStructure = structure
		return self.tableStructure

	def searchDBContent(self, data, fields="*", query_type="AND", exactmatch=False, compareoperator=""):
		rows = []
		content = []
		if exactmatch or compareoperator in ("<", "<=", ">", ">="):
			wildcard = ""
			compare = compareoperator + " " if compareoperator in ("<", "<=", ">", ">=") else "="
		else:
			compare = "LIKE "
			wildcard = "%"
		if query_type not in ("AND", "OR"):
			query_type = "AND"
		if not isinstance(data, dict):
			return content
		struc = self.getTableStructure()
		for field in data:
			if field not in struc:
				return content
		return_fields = ""
		if fields != "*":
			if (isinstance(fields, tuple) or isinstance(fields, list)) and len(fields):
				for field in fields:
					if field in struc:
						return_fields += field + ", "
			elif isinstance(fields, str):
				if fields in struc:
					return_fields = fields
		if return_fields.endswith(", "):
			return_fields = return_fields[:-2]
		if self.table and self.connectDataBase():
			sqlcmd = f"SELECT {return_fields or "*"} FROM {self.table} WHERE "
			args = []
			for key in data:
				sqlcmd += f"{key} {compare}? {query_type} "
				args.append(wildcard + data[key] + wildcard)
			if sqlcmd.endswith(f" {query_type} "):
				sqlcmd = sqlcmd[:-(len(query_type) + 2)] + ";"
			if not sqlcmd.endswith(";"):
				sqlcmd += ";"
			if not exactmatch:
				sqlcmd = f"PRAGMA case_sensitive_like=OFF;{sqlcmd}PRAGMA case_sensitive_like=ON;"
			sqlret = self.executeSQL(sqlcmd, readonly=True)
			if sqlret and sqlret[0]:
				rows = sqlret[1]
			else:
				return content
			self.disconnectDataBase(True)
			i = 1
			for row in rows:
				tmp_row = []
				for field in row:
					tmp_field = field
					tmp_row.append(tmp_field)
				content.append(tmp_row)
				debugPrint(f"Found row ({str(i)}):{str(tmp_row)}", LOGLEVEL.ALL)
				i += 1
		return content

	def insertRow(self, data, uniqueFields=""):
		if self.connectDataBase():
			struc = self.getTableStructure()
			is_valid = True
			fields = []
			for field in data:
				if field not in struc:
					is_valid = False
					break
			if self.table and is_valid:
				args = []
				sqlcmd = f"INSERT INTO {self.table}("
				for key in data:
					sqlcmd += f"{key},"
				if sqlcmd.endswith(","):
					sqlcmd = sqlcmd[:-1]
				sqlcmd += ") SELECT "
				for key in data:
					sqlcmd += '"' + data[key] + '",'
				if sqlcmd.endswith(","):
					sqlcmd = sqlcmd[:-1] + " "
				if uniqueFields != "":
					if isinstance(uniqueFields, str) and uniqueFields in data:
						sqlcmd += f"WHERE NOT EXISTS(SELECT 1 FROM {self.table} WHERE {uniqueFields} =?)"
						args = [data[uniqueFields],]
					elif isinstance(uniqueFields, tuple) or isinstance(uniqueFields, list):
						if len(uniqueFields) == 1:
							if uniqueFields[0] in data:
								sqlcmd += f"WHERE NOT EXISTS(SELECT 1 FROM {self.table} WHERE {uniqueFields[0]} =?)"
								args = [data[uniqueFields[0]],]
						elif len(uniqueFields) > 1:
							sql_limit = ""
							for uniqueField in uniqueFields:
								if uniqueField in data:
									sql_limit += f"{uniqueField} =? AND "
									args.append(data[uniqueField])
							if sql_limit.endswith(" AND "):
								sql_limit = sql_limit[:-5]
							if sql_limit != "":
								sqlcmd += f"WHERE NOT EXISTS(SELECT 1 FROM {self.table} WHERE {sql_limit})"
				self.executeSQL(sqlcmd, args)

	def insertUniqueRow(self, data, replace=False):
		if self.table and self.connectDataBase():
			struc = self.getTableStructure()
			for field in data:
				if field not in struc:
					is_valid = False
					return
			method = "IGNORE"
			if replace:
				method = "REPLACE"
			args = []
			sqlcmd = f"INSERT OR {method} INTO {self.table}("
			for key in data:
				sqlcmd += f"{key},"
				args.append(data[key])
			if sqlcmd.endswith(","):
				sqlcmd = sqlcmd[:-1]
			sqlcmd += ") VALUES ("
			for key in data:
				sqlcmd += "?,"
			if sqlcmd.endswith(","):
				sqlcmd = sqlcmd[:-1]
			sqlcmd += ");"
			self.executeSQL(sqlcmd, args)

	def updateUniqueData(self, data, idxFields):
		for field in idxFields:
			if field not in data:
				return
		struc = self.getTableStructure()
		for field in data:
			if field not in struc:
				return
		self.insertUniqueRow(data, replace=False)
		if not self.cursor:
			return
		if self.cursor.rowcount > 0:
			return
		args = []
		if self.table:
			sqlcmd = f"UPDATE {self.table} SET "
			for key in data:
				sqlcmd += f"{key} = ?, "
				args.append(data[key])
			if sqlcmd.endswith(", "):
				sqlcmd = sqlcmd[:-2]
			sqlcmd += " WHERE "
			for key in idxFields:
				sqlcmd += f"{key} = ? AND "
				args.append(data[key])
			if sqlcmd.endswith("AND "):
				sqlcmd = sqlcmd[:-4]
			sqlcmd += ";"
			self.executeSQL(sqlcmd, args)

	def deleteDataSet(self, fields, exactmatch=True):
		if self.connectDataBase():
			args = []
			struc = self.getTableStructure()
			wildcard = ""
			operator = "="
			if not exactmatch:
				wildcard = "%"
				operator = " LIKE "
			whereStr = " WHERE "
			for column in fields:
				if column not in struc:
					return
				whereStr += f"{column}{operator}? AND "
				args.append(f"{wildcard}{fields[column]}{wildcard}")
			if whereStr.endswith(" AND "):
				whereStr = f"{whereStr[:-5]};"
			sqlcmd = f"DELETE FROM {self.table}{whereStr}"
			self.executeSQL(sqlcmd, args)

	def doActionInBackground(self, fnc, job_name, args=[]):
		if not self.dbthreadRunning:
			self.dbthreadRunning = True
			self.dbthreadKill = False
			job_manager.AddJob(DatabaseJob(fnc, [self.stopBackgroundAction, args], self.dbthreadName))

	def stopBackgroundAction(self):
		self.dbthreadKill = True
		if self.dbthreadRunning:
			jobs = len(job_manager.getPendingJobs())
			if jobs:
				joblist = job_manager.getPendingJobs()
				for job in joblist:
					if job.name == self.dbthreadName:
						job.stop()
						if self.timerEntry:
							self.timerEntry.state == 3  # END
		self.dbthreadRunning = False
		self.disconnectDataBase()
		self.dbthreadId = None


class MovieDataBase(CommonDataBase):

	def __init__(self):
		CommonDataBase.__init__(self)
		self.ignoreThreadCheck = True
		self.table = "media"
		self.fields = {"path": "TEXT",
			"fname": "TEXT",
			"ref": "TEXT",
			"title": "TEXT",
			"shortDesc": "TEXT",
			"extDesc": "TEXT",
			"tags": "TEXT",
			"duration": "REAL",
			"begin": "REAL",
			"fsize": "INTEGER"
		}

	def doInit(self):
		self.isInitiated = True
		self.createTable(self.fields)
		self.createTableIndex("idx_fname_fsize", ("fname", "fsize"))
		self.disconnectDataBase()

	def reInitializeDB(self):
		if exists(self.dbFile):
			try:
				remove(self.dbFile)
			except OSError:
				pass
		self.isInitiated = False
		self.__init__()

	def backgroundDBUpdate(self, fnc, fnc_args=[], timerEntry=None):
		self.dbthreadName = _("Database Update")
		self.timerEntry = timerEntry
		self.doActionInBackground(fnc, self.dbthreadName, fnc_args)

	def BackgroundDBCleanUp(self):
		self.dbthreadName = _("Database Cleanup")
		self.doActionInBackground(self.removeDeprecated, self.dbthreadName)

	def getVideoDirs(self):
		dirs = []
		for x in config.movielist.videodirs.value:
			if not exists(x):
				continue
			x = join(x, "")
			dirs.append((len(x), x))
		dirs.sort(reverse=True)
		return [x[1] for x in dirs]

	def removeDeprecated(self):
		self.dbthreadId = current_thread().ident
		items = self.searchDBContent({"path": ""}, ("path", "fsize"))
		thisJob = None
		joblist = job_manager.getPendingJobs()
		for job in joblist:
			if job.name == self.dbthreadName and hasattr(job, "databaseJob"):
				thisJob = job
				break
		i = 0
		j = 0
		count = len(items)
		for item in items:
			if self.dbthreadKill:
					break
			i += 1
			if count:
				progress = int(float(i) / float(count) * 100.0)
				if thisJob:
					thisJob.databaseJob.setProgress(progress)
			deleteData = False
			if not exists(item[0]):
				deleteData = True
			else:
				if item[1] is not None and float(item[1]) != self.getFileSize(item[0]):
					deleteData = True
			if deleteData:
				self.deleteDataSet({"path": item[0]})
			if j >= 100:
				self.commitDB()
				j = 0
			j += 1
		self.doVacuum()
		self.stopBackgroundAction()

	def removeSingleEntry(self, service_path):
		items = self.searchDBContent({"path": service_path}, ("path", "title", "shortDesc", "extDesc"))
		for item in items:
			self.deleteDataSet({"path": item[0]})
		self.doVacuum()
		self.disconnectDataBase()

	def getFileSize(self, fpath):
		try:
			fsize = stat(fpath).st_size
		except OSError:
			fsize = -1
		return fsize

	def isTitleInDatabase(self, title, shortDesc="", extDesc="", ratioShortDesc=0.95, ratioExtDesc=0.85):
		"""
		Checks whether a given movie title (with optional short and extended descriptions)
		already exists in the database, based on string similarity.

		Parameters:
			title (str): The title of the movie to check.
			shortDesc (str): Optional short description of the movie.
			extDesc (str): Optional extended description of the movie.
			ratioShortDesc (float): Similarity threshold for the short description comparison.
			ratioExtDesc (float): Similarity threshold for the extended description comparison.

		Returns:
			int or None:
				- Returns 1 if a sufficiently similar entry is found in the database.
				- Returns None if no matching entry is found or config disables checking.
		"""
		configValue = config.misc.timer_show_movie_available.value
		result = None

		if configValue:
			content = self.getTitles(title)
			if content:
				# If configValue > 1, use full comparison logic
				if configValue > 1:
					for row in content:  # row = [ref, title, shortDesc, extDesc]
						if shortDesc:
							if row[2] == shortDesc:
								result = 1
							else:
								# Compare shortDesc similarity using SequenceMatcher
								sequenceMatcher = SequenceMatcher(" ".__eq__, shortDesc, row[2])
								if sequenceMatcher.ratio() > ratioShortDesc:
									result = 1

						if result:
							# If extended description is not provided, match is confirmed
							if extDesc == "":
								break
							else:
								if row[3] == extDesc:
									break
								else:
									# Compare extDesc similarity
									sequenceMatcher = SequenceMatcher(" ".__eq__, extDesc, row[3])
									if sequenceMatcher.ratio() > ratioExtDesc:
										break
							result = None  # Reset if extDesc check fails
				else:
					# If configValue <= 1, skip detailed checks and return match
					result = 1

		return result

	def getTitles(self, title):
		sqlcmd = f"SELECT ref,title,shortDesc, extDesc FROM {self.table} WHERE title =?"
		sqlret = self.executeSQL(sqlcmd, args=[title], readonly=True)
		content = []
		if sqlret and sqlret[0]:
			rows = sqlret[1]
			self.disconnectDataBase(True)
			for row in rows:
				tmp_row = []
				for field in row:
					tmp_field = field
					tmp_row.append(tmp_field)
				content.append(tmp_row)
		return content

	def searchContent(self, data, fields="*", query_type="AND", exactmatch=False, compareoperator="", skipCheckExists=False):
		s_fields = ["path", "fname", "ref"]
		if (isinstance(fields, tuple) or isinstance(fields, list)) and len(fields):
			for field in fields:
				s_fields.append(field)
		elif isinstance(fields, str) and fields == "*":
			for key in self.fields:
				s_fields.append(key)
		elif isinstance(fields, str):
			s_fields.append(fields)
		searchstr = None
		if "title" in data:
			searchstr = data["title"]
		elif "shortDesc" in data:
			searchstr = data["shortDesc"]
		elif "extDesc" in data:
			searchstr = data["extDesc"]
		if searchstr is not None:
			data["path"] = searchstr
		res = self.searchDBContent(data, fields=s_fields, query_type=query_type, exactmatch=exactmatch, compareoperator=compareoperator)
		checked_res = []
		fields_count = len(s_fields)
		ref_idx = False
		video_dirs = self.getVideoDirs()
		for x in range(4, fields_count):
			if s_fields[x] == "ref":
				ref_idx = x
				break
		if res:
			for movie in res:
				ret = []
				if skipCheckExists and movie[0] is not None:
					for x in range(4, fields_count):
						if ref_idx and ref_idx == x:
							if movie[3]:
								ret.append(movie[3] + movie[0])
						else:
							ret.append(movie[x])
					if ret not in checked_res:
						checked_res.append(ret)
				elif movie[0] is not None and exists(movie[0]):
					for x in range(4, fields_count):
						if ref_idx and ref_idx == x:
							if movie[3]:
								ret.append(movie[3] + movie[0])
							elif isdir(movie[0]):
								m = eServiceReference(eServiceReference.idFile, eServiceReference.flagDirectory, "")
								m.setPath(join(movie[0], ""))
								ret.append(m.toString())
						else:
							ret.append(movie[x])
					if ret not in checked_res:
						checked_res.append(ret)
				else:
					do_update = False
					for y in video_dirs:
						if not movie[2] or not movie[1]:
							break
						pp = y + movie[2]
						p = y + movie[1]
						p = join(p, "")
						p += movie[2]
						if exists(p):
							do_update = True
						elif exists(pp):
							do_update = True
							p = pp
						if do_update:
							self.updateSingleEntry(movie[3] + p)
							for x in range(4, fields_count):
								if ref_idx and ref_idx == x:
									ret.append(movie[3] + p)
								else:
									ret.append(movie[x])
							if ret not in checked_res:
								checked_res.append(ret)
							break
		return checked_res

	def updateMovieDB(self):
		self.dbthreadId = current_thread().ident
		debugPrint(f"updateMovieDB self.dbthreadId : {self.dbthreadId}", LOGLEVEL.ALL)
		pathes = []
		is_killed = False
		thisJob = None
		joblist = job_manager.getPendingJobs()
		for job in joblist:
			if job.name == self.dbthreadName and hasattr(job, "databaseJob"):
				thisJob = job
				break
		debugPrint(f"updateMovieDB config.movielist.videodirs.value : {config.movielist.videodirs.value}", LOGLEVEL.ALL)
		for folder in config.movielist.videodirs.value:
			debugPrint(f"Check folder : {folder}", LOGLEVEL.ALL)
			if self.dbthreadKill:
				is_killed = True
				break
			for root, subFolders, files in walk(folder):
				if self.dbthreadKill:
					is_killed = True
					break
				pathes.append(root)
		if not is_killed:
			count = len(pathes)
			i = 0
			for folder in pathes:
				if self.dbthreadKill:
					break
				i += 1
				if count and thisJob:
					progress = int(float(i) / float(count) * 100.0)
					thisJob.databaseJob.setProgress(progress)
				path = join(folder, "")
				debugPrint(f"Add items of folder : {path}", LOGLEVEL.ALL)
				self.updateMovieDBPath(path, isThread=True)
		self.stopBackgroundAction()

	def updateMovieDBPath(self, path, isThread=False):
		m_list = []
		root = eServiceReference(eServiceReference.idFile, eServiceReference.flagDirectory, join(path, ""))
		serviceHandler = eServiceCenter.getInstance()

		m_list = serviceHandler.list(root)
		if m_list is None:
			debugPrint("updating of movie database failed", LOGLEVEL.ERROR)
			return
		videoDirs = self.getVideoDirs()
		while 1:
			if self.dbthreadKill:
				break
			serviceref = m_list.getNext()
			if not serviceref.valid():
				break
			if serviceref.flags & eServiceReference.mustDescent:
				continue
			self.updateSingleEntry(serviceref, isThread, videoDirs)

	def updateSingleEntry(self, serviceref, isThread=False, video_dirs=[]):
		debugPrint("updateSingleEntry for %s" % serviceref.getPath(), LOGLEVEL.ALL)
		if not config.misc.db_enabled.value:
			return
		if not video_dirs:
			video_dirs = self.getVideoDirs()
		if isinstance(serviceref, str):
			if not exists(serviceref):
				return
			filepath = realpath(serviceref)
			serviceref = eServiceReference(1, 0, filepath) if filepath.endswith(".ts") else eServiceReference(4097, 0, filepath)
		serviceHandler = eServiceCenter.getInstance()
		filepath = realpath(serviceref.getPath())
		debugPrint("updateSingleEntry filepath %s" % filepath, LOGLEVEL.ALL)
		# trashfile = f"{filepath}.del"
		if filepath.endswith("_pvrdesc.ts"):
			return
		file_path = serviceref.getPath()
		file_extension = file_path.split(".")[-1].lower()
		if file_extension == "iso":
			serviceref = eServiceReference(4097, 0, file_path)
		if file_extension in ("dat",):
			return
		cur_item = basename(filepath)
		if cur_item.lower().startswith("timeshift_"):
			return
		info = serviceHandler.info(serviceref)
		if info is None:
			return

		debugPrint("updateSingleEntry get info for filepath %s" % filepath, LOGLEVEL.ALL)

		m_db_begin = info.getInfo(serviceref, iServiceInformation.sTimeCreate)
		m_db_tags = info.getInfoString(serviceref, iServiceInformation.sTags)
		m_db_fullpath = filepath
		m_db_path, m_db_fname = split(filepath)
		m_db_title = info.getName(serviceref)
		m_db_evt = info.getEvent(serviceref)
		m_db_shortDesc = ""
		if m_db_evt is not None:
			m_db_shortDesc = m_db_evt.getShortDescription()
			m_db_extDesc = m_db_evt.getExtendedDescription()
		else:
			m_db_title, m_db_extDesc = getExtendedMovieDescription(serviceref)
		m_db_ref = serviceref.toString().replace(serviceref.getPath(), "")
		m_db_begin = info.getInfo(serviceref, iServiceInformation.sTimeCreate)
		m_db_f_size = self.getFileSize(m_db_fullpath)
		m_db_duration = info.getLength(serviceref)
		if m_db_duration < 0:
			m_db_duration = self.calcMovieLen(f"{m_db_fullpath}.cuts")
		fields = {"path": m_db_fullpath,
				"fname": m_db_fname,
				"title": m_db_title,
				"extDesc": m_db_extDesc,
				"shortDesc": m_db_shortDesc,
				"tags": m_db_tags,
				"ref": m_db_ref,
				"duration": str(m_db_duration),
				"fsize": str(m_db_f_size),
				"begin": str(m_db_begin)
			}

		self.updateUniqueData(fields, ("fname", "fsize"))
		if not isThread:
			self.disconnectDataBase()

	def calcMovieLen(self, fname):
		if exists(fname):
			try:
				with open(fname, "rb") as f:
					packed = f.read()
				while len(packed) > 0:
					packedCue = packed[:12]
					packed = packed[12:]
					cue = unpack(">QI", packedCue)
					if cue[1] == 5:
						movie_len = cue[0] / 90000
						return movie_len
			except Exception as ex:
				debugPrint("failure at getting movie length from cut list", LOGLEVEL.ERROR)
		return -1


moviedb = MovieDataBase()


def isMovieinDatabase(title_name, shortdesc, extdesc, short_ratio=0.95, ext_ratio=0.85):
	movie = None
	movie_found = False
	s = {"title": str(title_name)}
	print(f"[MovieDB] search for existing media file with title: {str(title_name)}")
	for x in moviedb.searchContent(s, ("title", "shortDesc", "extDesc"), query_type="OR", exactmatch=False):
		movie_found = False
		if shortdesc and shortdesc != "" and x[1]:
			sequenceMatcher = SequenceMatcher(" ".__eq__, shortdesc, str(x[1]))
			ratio = sequenceMatcher.ratio()
			print(f"[MovieDB] shortdesc movie ratio {ratio:f} - {len(shortdesc)} - {len(x[1])}")
			if shortdesc in x[1] or (short_ratio < ratio):
				movie = x
				movie_found = True
				print("[MovieDB] found movie with similiar short description -> skip this event")
		if movie_found:
			if extdesc and x[2]:
				sequenceMatcher = SequenceMatcher(" ".__eq__, extdesc, str(x[2]))
				ratio = sequenceMatcher.ratio()
				print(f"[MovieDB] extdesc movie ratio {ratio:f} - {len(extdesc)} - {len(x[1])}")
				if ratio < ext_ratio:
					movie = None
					movie_found = False
				else:
					movie_found = True
					movie = x
					print("[MovieDB] found movie with similiar short and extended description -> skip this event")
					break
			else:
				print("[MovieDB] found movie with similiar short description -> skip this event")
				movie_found = True
				movie = x
				break
		if extdesc and x[2] and not movie_found:
			sequenceMatcher = SequenceMatcher(" ".__eq__, extdesc, str(x[2]))
			ratio = sequenceMatcher.ratio()
			print(f"[MovieDB] extdesc movie ratio {ratio:f} - {len(extdesc)} - {len(x[1])}")
			if extdesc in x[2] or (ext_ratio < ratio):
				movie = x
				movie_found = True
				print("[MovieDB] found movie with similiar extended description -> skip this event")
				break
	if movie_found:
		real_path = realpath(eServiceReference(movie[0]).getPath()) if movie else ""
		movie_found = True if real_path or exists(f"{real_path}.del") else False
	return movie_found


class MovieDBUpdate():

	def __init__(self):
		self.navigation = None
		self.updateTimer = eTimer()
		self.updateTimer.callback.append(self.startUpdate)
		self.timerintervall = 30
		self.longtimerintervall = 30
		config.misc.movielist_use_moviedb_autoupdate.addNotifier(self.updateMovieDBAuto)

	def updateMovieDBAuto(self, configElement):
		if config.misc.movielist_use_moviedb_autoupdate.value:
			self.updateTimer.startLongTimer(self.timerintervall)

	def startUpdate(self):
		self.updateTimer.stop()
		if self.getRecordings():
			debugPrint("update cancelled - there are running records", LOGLEVEL.INFO)
			self.updateTimer.startLongTimer(self.longtimerintervall)
			return
		jobs = (job_manager.getPendingJobs())
		if jobs:
			for job in jobs:
				if job.name.lower().find("database") != -1:
					debugPrint("update cancelled - there is still a running  database job", LOGLEVEL.INFO)
					return
		if True:  # self.getInstandby():
			debugPrint("start auto update of moviedb", LOGLEVEL.INFO)
			moviedb.backgroundDBUpdate(moviedb.updateMovieDB)
		else:
			debugPrint("update cancelled - not in Standby", LOGLEVEL.INFO)

	def getNavigation(self):
		if not self.navigation:
			import NavigationInstance
			if NavigationInstance:
				self.navigation = NavigationInstance.instance
		return self.navigation

	def getRecordings(self):
		nav = self.getNavigation()
		return nav.getRecordings() if nav else []

	def getInstandby(self):
		from Screens.Standby import inStandby
		return inStandby


moviedbupdate = MovieDBUpdate()


def backgroundDBUpdate(**kwargs):
	moviedb.backgroundDBUpdate(moviedb.updateMovieDB, timerEntry=kwargs["timerEntry"])


def backgroundDBUpdateCancel():
	print("backgroundDBUpdateCancel")
	pass


# functionTimers.add(("moviedbupdate", {"name": _("Update movie database (full)"), "entryFunction": backgroundDBUpdate, "cancelFunction": backgroundDBUpdateCancel, "isThreaded": True}))

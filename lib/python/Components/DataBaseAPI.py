from fcntl import ioctl
from socket import socket, AF_INET, SOCK_DGRAM
from struct import pack
from bisect import bisect_left, insort
from ctypes import py_object, pythonapi, c_long
from difflib import SequenceMatcher
from os import remove, stat, walk, mknod
from os.path import exists, dirname, realpath, isdir, join, basename, split
from sqlite3 import connect, ProgrammingError, OperationalError, DatabaseError
from struct import unpack
from threading import Thread, Lock, current_thread
from time import sleep, time
from enigma import eServiceCenter, eServiceReference, iServiceInformation, eTimer
from Components.Task import Task, Job, job_manager
from Components.config import config, ConfigDirectory, ConfigYesNo, ConfigSelection
from Scheduler import functionTimer
from Screens.MessageBox import MessageBox
from Tools.Directories import fileWriteLine
from Tools.Notifications import AddPopup
from Tools.MovieInfoParser import getExtendedMovieDescription
from Components.SystemInfo import BoxInfo

BASEINIT = None
lock = Lock()


config.misc.movielist_use_moviedb_autoupdate = ConfigYesNo(default=True)
config.misc.db_path = ConfigDirectory(default="/media/hdd/")
config.misc.db_enabled = ConfigYesNo(default=True)
config.misc.timer_show_movie_available = ConfigSelection(choices=[
	(0, _("Off")),
	(1, _("Title")),
	(2, _("Title / Description")),
	], default=2)


def getUniqueID(device="eth0"):
	model = BoxInfo.getItem("model")
	sock = socket(AF_INET, SOCK_DGRAM)
	info = ioctl(sock.fileno(), 0x8927, pack("256s", bytes(device[:15], "UTF-8")))
	key = "".join([f"{char:02x}" for char in info[18:24]])
	keyid = ""
	j = len(key) - 1
	for i in range(0, len(key)):
		keyid += f"{key[j]}{model[i]}{key[i]}" if i < len(model) else f"{key[j]}{key[i]}"
		j -= 1
	return keyid[:12]


class LOGLEVEL:
	ERROR = 4
	WARN = 3
	INFO = 2
	ALL = 1

	def __init__(self):
		pass


logLevel = LOGLEVEL()


def debugPrint(str, level=0):
	curLevel = logLevel.INFO
	if level >= curLevel:
		print(f"[DataBase] {str}")


class globalThreads():

	def __init__(self):
		self.registeredThreads = []

	def terminateThread(self, myThread):
		if not myThread.isAlive():
			return
		exc = py_object(SystemExit)
		res = pythonapi.PyThreadState_SetAsyncExc(c_long(myThread.ident), exc)
		if res == 0:
			print("[DataBaseAPI] can not kill list update")
		elif res > 1:
			pythonapi.PyThreadState_SetAsyncExc(myThread.ident, None)
			print("[DataBaseAPI] can not terminate list update")
		elif res == 1:
			print("[DataBaseAPI] successfully terminate thread")
		del exc
		del res
		return 0

	def registerThread(self, myThread):
		if myThread not in self.registeredThreads:
			self.registeredThreads.append(myThread)

	def unregisterThread(self, myThread):
		if myThread in self.registeredThreads:
			self.registeredThreads.remove(myThread)

	def shutDown(self):
		for t in self.registeredThreads:
			self.terminateThread(t)


globalthreads = globalThreads()


class databaseJob(Job):
	def __init__(self, fnc, args, title):
		Job.__init__(self, title)
		self.databaseJob = databaseTask(self, fnc, args, title)

	def abort(self):
		self.databaseJob.abort()

	def stop(self):
		self.databaseJob.stop()


class databaseTask(Task):
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
#		from Screens.Standby import inStandby
#		if not inStandby:
#			AddPopup(text = self.msgtxt, type = MessageBox.TYPE_INFO, timeout = 20, id = "db_update_stopped")

	def abort(self):
		self.msgtxt = _("Database update was cancelled")
		debugPrint("job cancelled", LOGLEVEL.INFO)
		self.stop()


class DatabaseState(object):
	def __init__(self, dbfile, boxid):
		self.lockfile = f"{dbfile}.lock"
		self.boxid = boxid
		self.lockFileCleanUp()
		self.checkRemoteLock = False
		self.availableStbs = []
		global BASEINIT
		if BASEINIT is None:
			BASEINIT = True
			self.unlockDB()

	def lockFileCleanUp(self):
		content = ""
		if exists(self.lockfile):
			try:
				with open(self.lockfile, "r") as f:
					content = f.readlines()
			except OSError as e:
				pass
			if content and len(content) >= 1:
				lockid = content[0]
				if lockid.startswith(self.boxid):
					self.removeLockFile()

	def isRemoteLocked(self):
		ret = False
		if not self.checkRemoteLock:
			return ret
		max_recursion = 5
		for i in range(0, max_recursion):
			lockid = ""
			ret = False
			if exists(self.lockfile):
				try:
					with open(self.lockfile, "r") as f:
						content = f.readlines()
				except OSError as e:
					break
				if content and len(content) >= 1:
					lockid = content[0]
					if not lockid.startswith(self.boxid):
						if lockid in self.availableStbs or len(self.availableStbs) <= 0:
							if i >= max_recursion - 1:
								#txt = _("The database is currently used by another Vu+ STB, please try again later")
								#AddPopup(text = txt, type = MessageBox.TYPE_INFO, timeout = 20, id = "db_locked")
								ret = True
							else:
								sleep(0.1)
						else:
							self.removeLockFile()
							break
					else:
						break
				else:
					self.removeLockFile()
					break
			else:
				break
		return ret

	def lockDB(self):
		if self.checkRemoteLock:
			fileWriteLine(self.lockfile, self.boxid)

	def removeLockFile(self):
		try:
			remove(self.lockfile)
		except OSError as e:
			pass

	def unlockDB(self):
		if self.checkRemoteLock and not self.isRemoteLocked():
			self.removeLockFile()


class CommonDataBase():
	def __init__(self, dbFile=None):
		dbPath = join(config.misc.db_path.value, "")
		if not exists(dbPath):
			dbPath = "/media/hdd/"
		self.dbFile = join(dbPath, dbFile or "moviedb.db")
		self.boxid = getUniqueID()
		self.dbstate = DatabaseState(self.dbFile, self.boxid)
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
			if self.dbstate.isRemoteLocked():
				if len(self.dbstate.available_stbs):
					return False
			else:
				self.dbstate.lockDB()
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
			self.dbstate.unlockDB()

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

	def checkTableColumns(self, fields, force_remove=False):
		if self.table and self.connectDataBase():
			struc = self.getTableStructure()
			for column in fields:
				if column not in struc:
					sqlcmd = f"ALTER TABLE {self.table} ADD COLUMN {column} {fields[column]};"
					self.executeSQL(sqlcmd)
			if force_remove:
				columns_str = ""
				for column in fields:
					columns_str += f"{column} {fields[column]},"
				if columns_str.endswith(","):
					columns_str = columns_str[:-1]
				b_table = f"{self.table}_backup"
				sqlcmd = f"CREATE TEMPORARY TABLE {b_table}({columns_str});"
				self.executeSQL(sqlcmd)
				sqlcmd = f"INSERT INTO {b_table} SELECT {columns_str} FROM {self.table};"
				self.executeSQL(sqlcmd)
				sqlcmd = f"DROP TABLE {self.table};"
				self.executeSQL(sqlcmd)
				self.createTable(fields)
				sqlcmd = f"INSERT INTO {self.table} SELECT {columns_str} FROM {b_table};"
				self.executeSQL(sqlcmd)
				sqlcmd = f"DROP TABLE {b_table};"
				self.executeSQL(sqlcmd)
				self.tableStructure = None
			self.commitDB()
		self.tableStructure = None

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

	def dropTable(self):
		if self.table and self.connectDataBase():
			self.tableStructure = None
			self.executeSQL(f"DROP TABLE IF EXISTS {self.table};")

	def getTables(self):
		tables = []
		if self.connectDataBase():
			sqlret = self.executeSQL("SELECT name FROM sqlite_master WHERE type='table';")
			if sqlret and sqlret[0]:
				res = sqlret[1]
			else:
				return tables
			for t in res:
				debugPrint(f"found table: {t[0]}", LOGLEVEL.ALL)
				tables.append(t[0])
		return tables

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
			if self.dbstate.checkRemoteLock:
				for x in structure:
					if x.startswith("fp_"):
						r_stb = str(x.lstrip("fp_"))
						if r_stb not in self.dbstate.available_stbs:
							self.dbstate.available_stbs.append(r_stb)
		return self.tableStructure

	def addColumn(self, column, c_type="TEXT"):
		if self.connectDataBase():
			struc = self.getTableStructure()
			if self.table and column not in struc:
				sqlcmd = f"ALTER TABLE {self.table} ADD COLUMN {column} {c_type};"
				self.executeSQL(sqlcmd)
				self.tableStructure = None

	def getTableContent(self):
		rows = []
		content = []
		if self.table and self.connectDataBase():
			sqlret = self.executeSQL(f"SELECT * FROM {self.table};")
			if sqlret and sqlret[0]:
				rows = sqlret[1]
			else:
				return content
			i = 1
			for row in rows:
				tmp_row = []
				for field in row:
					tmp_field = field
#					if field and isinstance(field.encode("utf-8"), str):
#						tmp_field = field
					tmp_row.append(tmp_field)
				content.append(tmp_row)
				debugPrint(f"Found row ({str(i)}):{str(tmp_row)}", LOGLEVEL.ALL)
				i += 1
		return content

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
		if return_fields == "":
			return_fields = "*"
		if return_fields.endswith(", "):
			return_fields = return_fields[:-2]
		if self.table and self.connectDataBase():
			sqlcmd = f"SELECT {return_fields} FROM {self.table} WHERE "
			args = []
			for key in data:
				sqlcmd += f"{key} {compare}? {query_type} "
				args.append(wildcard + data[key] + wildcard)
			if sqlcmd.endswith(f" {query_type} "):
				sqlcmd = sqlcmd[:-(len(query_type) + 2)] + ";"
			if not exactmatch:
				sqlpragmacmd = "PRAGMA case_sensitive_like=OFF;"
				self.executeSQL(sqlpragmacmd, readonly=True)
			sqlret = self.executeSQL(sqlcmd, args, readonly=True)
			if not exactmatch:
				sqlpragmacmd = "PRAGMA case_sensitive_like=ON;"
				self.executeSQL(sqlpragmacmd, readonly=True)
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
#					if field and isinstance(str(field).encode("utf-8"), str):
#						tmp_field = str(field).encode("utf-8")
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

	def updateData(self, data, uniqueFields):
		if self.table and self.connectDataBase():
			self.insertRow(data, uniqueFields)
			if not self.cursor:
				return
			if self.cursor.rowcount > 0:
				return
			struc = self.getTableStructure()
			for field in data:
				if field not in struc:
					return
			if isinstance(uniqueFields, tuple) or isinstance(uniqueFields, list):
				for field in uniqueFields:
					if field not in struc:
						return
			else:
				if uniqueFields not in struc:
						return
			args = []
			sqlcmd = f"UPDATE {self.table} SET "
			for key in data:
				sqlcmd += f"{key}=?, "
				args.append(data[key])
			if sqlcmd.endswith(", "):
				sqlcmd = sqlcmd[:-2]
			if uniqueFields is None or uniqueFields == "":
				return
			if isinstance(uniqueFields, str):
				sqlcmd += f" WHERE {uniqueFields} =?"
				args.append(data[uniqueFields])
			elif isinstance(uniqueFields, tuple) or isinstance(uniqueFields, list):
				if len(uniqueFields) == 1:
					if uniqueFields[0] in data:
						sqlcmd += f" WHERE {uniqueFields[0]} =?"
						args.append(data[uniqueFields[0]])
				elif len(uniqueFields) > 1:
					sql_limit = ""
					for uniqueField in uniqueFields:
						if uniqueField in data:
							sql_limit += f"{uniqueField} =? AND "
							args.append(data[uniqueField])
					if sql_limit.endswith(" AND "):
						sql_limit = sql_limit[:-5]
					if sql_limit != "":
						sqlcmd += f" WHERE {sql_limit}"
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
			job_manager.AddJob(databaseJob(fnc, [self.stopBackgroundAction, args], self.dbthreadName))

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
		self.boxPath = f"fp_{self.boxid}"
		self.boxLpos = f"lpos_{self.boxid}"
		dbVersion = "_v0001"
		self.dbstate.checkRemoteLock = True
		self.ignoreThreadCheck = True
		self.table = f"moviedb{dbVersion}"
		self.fields = {"path": "TEXT",
			self.boxPath: "TEXT",
			"fname": "TEXT",
			"ref": "TEXT",
			"title": "TEXT",
			"shortDesc": "TEXT",
			"extDesc": "TEXT",
			"genre": "TEXT",
			"tags": "TEXT",
			"autotags": "TEXT",
			"duration": "REAL",
			"begin": "REAL",
			"lastpos": "REAL",
			self.boxLpos: "REAL",
			"fsize": "INTEGER",
			"progress": "REAL",
			"AudioChannels": "INTEGER",
			"ContentType": "INTEGER",
			"AudioFormat": "TEXT",
			"VideoFormat": "TEXT",
			"VideoResoltuion": "TEXT",
			"AspectRatio": "TEXT",
			"TmdbID": "INTEGER",
			"TvdbID": "INTEGER",
			"CollectionID": "INTEGER",
			"ListID": "INTEGER",
			"IsRecording": "INTEGER DEFAULT 0",
			"IsTrash": "INTEGER DEFAULT 0",
			"TrashTime": "REAL",
			"IsDir": "INTEGER",
			"Season": "INTEGER",
			"Episode": "INTEGER",
		}
		self.titlelist = {}
		self.titlelist_list = []

	def doInit(self):
		if not self.dbstate.isRemoteLocked():
			self.isInitiated = True
			self.createTable(self.fields)
			self.checkTableColumns(self.fields, force_remove=False)
			self.createTableIndex("idx_fname_fsize", ("fname", "fsize"))
			idx_name = f"idx_fname_fsize_{self.boxid}"
			self.createTableIndex(idx_name, ("fname", "fsize", self.boxPath))
			self.disconnectDataBase()

	def reInitializeDB(self):
		if exists(self.dbFile):
			try:
				remove(self.dbFile)
			except OSError:
				pass
		self.isInitiated = False
		self.titlelist = {}
		self.titlelist_list = []
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
		items = self.searchDBContent({self.boxPath: ""}, (self.boxPath, "fsize"))
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
				self.deleteDataSet({self.boxPath: item[0]})
			if j >= 100:
				self.commitDB()
				j = 0
			j += 1
		self.doVacuum()
		self.stopBackgroundAction()

	def removeSingleEntry(self, service_path):
		items = self.searchDBContent({self.boxPath: service_path}, (self.boxPath, "title", "shortDesc", "extDesc"))
		for item in items:
			if len(item) >= 4:
				search_fields = {self.boxPath: service_path}
				isInDB = self.searchContent(search_fields, fields=("fname",), query_type="AND", exactmatch=False, skipCheckExists=True)
				if len(isInDB):
					self.removeFromTitleList(item[1], item[2], item[3])
			self.deleteDataSet({self.boxPath: item[0]})
		self.doVacuum()
		self.disconnectDataBase()

	def getFileSize(self, fpath):
		try:
			fsize = stat(fpath).st_size
		except OSError:
			fsize = -1
		return fsize

	def inTitleList(self, mytitle, shortDesc="", extDesc="", ratio_short_desc=0.95, ratio_ext_desc=0.85):
		if config.misc.timer_show_movie_available.value > 1:
			if shortDesc is None:
				shortDesc = ""
			if extDesc is None:
				extDesc = ""
			if shortDesc == "" and extDesc == "":
				return 1 if mytitle in self.titlelist else None
			else:
				if mytitle in self.titlelist:
					short_descs = self.titlelist[mytitle][0]
					short_compared = False
					movie_found = False
					if shortDesc != "":
						short_compared = True
						for short_desc in short_descs:
							sequenceMatcher = SequenceMatcher(" ".__eq__, shortDesc, short_desc)
							if sequenceMatcher.ratio() > ratio_short_desc:
								movie_found = True
								break
							if short_desc == shortDesc:
								movie_found = True
								break
					if extDesc == "" and movie_found:
						return 1
					if not movie_found and short_compared:
						return None
					ext_descs = self.titlelist[mytitle][1]
					for ext_desc in ext_descs:
						sequenceMatcher = SequenceMatcher(" ".__eq__, extDesc, ext_desc)
						if sequenceMatcher.ratio() > ratio_ext_desc:
							return 1
						if ext_desc == extDesc:
							return 1
				return None
		elif config.misc.timer_show_movie_available.value == 1:
			pos = bisect_left(self.titlelist_list, mytitle)
			try:
				return pos if self.titlelist_list[pos] == mytitle else None
			except IndexError:
				return None
		else:
			return None

	def removeFromTitleList(self, mytitle, shortDesc="", extDesc=""):
		if config.misc.timer_show_movie_available.value > 1:
			is_in_short_desc_list = False
			is_in_ext_desc_list = False
			if mytitle in self.titlelist:
				x = self.titlelist[mytitle][0]
				if len(x):
					for short_desc in x:
						if short_desc == shortDesc:
							is_in_short_desc_list = True
							break
					if is_in_short_desc_list:
						x.remove(short_desc)
				y = self.titlelist[mytitle][1]
				if len(y):
					for ext_desc in y:
						if ext_desc == extDesc:
							is_in_ext_desc_list = True
							break
					if is_in_ext_desc_list:
						y.remove(ext_desc)
				if len(x):
					self.titlelist[mytitle][0] = x
				if len(y):
					self.titlelist[mytitle][1] = y
				if not len(x) and not len(y):
					del self.titlelist[mytitle]
		elif config.misc.timer_show_movie_available.value == 1:
			idx = self.inTitleList(mytitle)
			if idx is not None:
				try:
					self.titlelist_list.pop(idx)
				except Exception:
					pass

	def addToTitleList(self, mytitle, shortDesc="", extDesc=""):
		if config.misc.timer_show_movie_available.value > 1:
			if mytitle in self.titlelist:
				if isinstance(self.titlelist[mytitle][0], list) and shortDesc not in self.titlelist[mytitle][0]:
					x = self.titlelist[mytitle][0]
					x.append(shortDesc)
					self.titlelist[mytitle][0] = x
				else:
					self.titlelist[mytitle][0] = [shortDesc]
				if isinstance(self.titlelist[mytitle][1], list) and extDesc not in self.titlelist[mytitle][1]:
					x = self.titlelist[mytitle][1]
					x.append(extDesc)
					self.titlelist[mytitle][1] = x
				else:
					self.titlelist[mytitle][1] = [extDesc]
			else:
				self.titlelist[mytitle] = [[shortDesc], [extDesc]]
		elif config.misc.timer_show_movie_available.value == 1:
			insort(self.titlelist_list, mytitle)

	def BackgroundTitleListUpdate(self):
		if config.misc.timer_show_movie_available.value > 0:
			t = Thread(target=self.getTitleList, args=[])
			t.start()
			globalthreads.registerThread(t)

	def getTitleList(self):
		sqlcmd = f"SELECT ref,title,shortDesc, extDesc FROM {self.table} WHERE IsTrash != 1"
		sqlret = self.executeSQL(sqlcmd, args=[], readonly=True)
		if sqlret and sqlret[0]:
			content = []
			rows = sqlret[1]
			self.disconnectDataBase(True)
			for row in rows:
				tmp_row = []
				for field in row:
					tmp_field = field
#					if field and isinstance(str(field).encode("utf-8"), str):
#						tmp_field = str(field).encode("utf-8")
					tmp_row.append(tmp_field)
				content.append(tmp_row)
			for x in content:
				if x[0]:
					orig_path = eServiceReference(x[0]).getPath()
					real_path = realpath(orig_path)
					if real_path[-3:] not in ("mp3", "ogg", "wav"):
						self.addToTitleList(x[1], x[2], x[3])

	def searchContent(self, data, fields="*", query_type="AND", exactmatch=False, compareoperator="", skipCheckExists=False):
		s_fields = [self.boxPath, "path", "fname", "ref"]
		if (isinstance(fields, tuple) or isinstance(fields, list)) and len(fields):
			for field in fields:
				s_fields.append(field)
		elif isinstance(fields, str) and fields == "*":
			for key in self.fields:
				s_fields.append(key)
		elif isinstance(fields, str):
			s_fields.append(fields)
		s_fields.append(self.boxPath)
		searchstr = None
		if "title" in data:
			searchstr = data["title"]
		elif "shortDesc" in data:
			searchstr = data["shortDesc"]
		elif "extDesc" in data:
			searchstr = data["extDesc"]
		if searchstr is not None:
			data[self.boxPath] = searchstr
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
#						p = str(p.encode("utf-8"))
#						pp = str(pp.encode("utf-8"))
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

	def getTrashEntries(self, as_ref=False):
		fields = ["ref", "fsize"] if as_ref else [self.boxPath, "fsize"]
		entries = self.searchContent({"IsTrash": "1"}, fields=fields)
		ret = []
		fsize = 0.0
		for entry in entries:
			if entry[1]:
				fsize += float(entry[1])
			ret.append(eServiceReference(entry[0]) if as_ref else entry[0])
		return (ret, fsize)

	def getDeprecatedTrashEntries(self, as_ref=False):
		now = time()
		diff_rec = config.usage.movielist_use_autodel_trash.value * 60.0 * 60.0 * 24.0
		diff_trash = config.usage.movielist_use_autodel_in_trash.value * 60.0 * 60.0 * 24.0
		fields = ["ref", "begin", "TrashTime"] if as_ref else [self.boxPath, "begin", "TrashTime"]
		entries = self.searchContent({"IsTrash": "1"}, fields=fields)
		ret = []
		rec_t = 0.0
		trash_t = 0.0
		link = config.usage.movielist_link_autodel_config.value == "and" and True or False
		for entry in entries:
			rec_t = float(entry[1] or 0.0)
			trash_t = float(entry[2] or 0.0)
			append = False
			if link and diff_rec > 0 and diff_trash > 0 and rec_t > 0 and trash_t > 0:
				if now - rec_t >= diff_rec and now - trash_t >= diff_trash:
					append = True
			else:
				if now - rec_t >= diff_rec and diff_rec > 0 and rec_t > 0:
					append = True
				elif now - trash_t >= diff_trash and diff_trash > 0 and trash_t > 0:
					append = True
			if append:
				ret.append(eServiceReference(entry[0]) if as_ref else entry[0])
		return ret

	def updateMovieDB(self):
		self.dbthreadId = current_thread().ident
		pathes = []
		is_killed = False
		thisJob = None
		joblist = job_manager.getPendingJobs()
		for job in joblist:
			if job.name == self.dbthreadName and hasattr(job, "databaseJob"):
				thisJob = job
				break
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

	def updateMovieDBSinglePath(self, path, isThread=False):
		self.updateMovieDBPath(path, isThread)
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
			self.updateSingleEntry(serviceref, isThread, videoDirs)

	def updateSingleEntry(self, serviceref, isThread=False, video_dirs=[], withBoxPath=False, isTrash=(False, 0)):
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
		trashfile = f"{filepath}.del"
		if filepath.endswith("_pvrdesc.ts"):
			return
		if isTrash[0]:
			if isTrash[1] == 1 and not exists(trashfile):
				try:
					mknod(trashfile)
				except OSError:
					pass
			else:
				if exists(trashfile):
					try:
						remove(trashfile)
					except OSError:
						pass
		is_dvd = None
		if serviceref.flags & eServiceReference.mustDescent:
			possible_path = ("VIDEO_TS", "video_ts", "VIDEO_TS.IFO", "video_ts.ifo")
			for mypath in possible_path:
				if exists(join(filepath, mypath)):
					is_dvd = True
					serviceref = eServiceReference(4097, 0, filepath)
					break
		if is_dvd is None and serviceref.flags & eServiceReference.mustDescent:
			fields = {self.boxPath: filepath, "IsDir": "1", "fname": filepath, "fsize": "0", "ref": "2:47:1:0:0:0:0:0:0:0:", }
			if isTrash[0]:
				fields["IsTrash"] = str(isTrash[1])
				fields["TrashTime"] = str(0) if isTrash[1] == 0 else str(time())
			else:
				if exists(trashfile):
					fields["IsTrash"] = str(1)
					try:
						fields["TrashTime"] = str(stat(trashfile).st_mtime)
					except OSError:
						fields["TrashTime"] = str(time())
				else:
					return
			if withBoxPath:
				self.updateUniqueData(fields, (self.boxPath,))
			else:
				self.updateUniqueData(fields, ("fname", "fsize"))
			if not isThread:
				self.disconnectDataBase()
			return
		file_path = serviceref.getPath()
		file_extension = file_path.split(".")[-1].lower()
		if file_extension == "iso":
			serviceref = eServiceReference(4097, 0, file_path)
		if file_extension in ("dat",):
			return
		is_rec = 0
		if exists(f"{file_path}.rec"):
			is_rec = 1
		cur_item = basename(filepath)
		if cur_item.lower().startswith("timeshift_"):
			return
		info = serviceHandler.info(serviceref)
		if info is None:
			return
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
		if is_rec:
			rec_file_c = []
			with open(f"{file_path}.rec") as f:
				rec_file_c = f.readlines()
			ret = str(rec_file_c[0]) if len(rec_file_c) >= 1 else ""
			ret = ret.strip()
			m_db_f_size = int(ret)
		else:
			m_db_f_size = self.getFileSize(m_db_fullpath)
		m_db_lastpos = -1
		m_db_progress = -1
		m_db_duration = info.getLength(serviceref)
		if video_dirs:
			for x in video_dirs:
				if m_db_path.startswith(x) or m_db_path == x[:-1]:
					m_db_path = m_db_path.lstrip(x)
					break
		m_db_autotags = ""
		autotags = []  # config.movielist.autotags.value.split(";") # TODO
		desc = f"{m_db_shortDesc.lower()}{m_db_extDesc.lower()}"
		for tag in autotags:
			if desc[:80].find(tag.lower()) != -1 or desc[80:].find(tag.lower()) != -1:
				m_db_autotags += f"{tag};"
		if m_db_duration < 0:
			m_db_duration = self.calcMovieLen(f"{m_db_fullpath}.cuts")
		if m_db_duration >= 0:
			m_db_lastpos, m_db_progress = self.getPlayProgress(f"{m_db_fullpath}.cuts", m_db_duration)
		fields = {"path": m_db_path,
				self.boxPath: m_db_fullpath,
				"fname": m_db_fname,
				"title": m_db_title,
				"extDesc": m_db_extDesc,
				"shortDesc": m_db_shortDesc,
				"tags": m_db_tags,
				"ref": m_db_ref,
				"duration": str(m_db_duration),
				"lastpos": str(m_db_lastpos),
				self.boxLpos: str(m_db_lastpos),
				"progress": str(m_db_progress),
				"fsize": str(m_db_f_size),
				"begin": str(m_db_begin),
				"autotags": str(m_db_autotags),
				"IsRecording": str(is_rec),
			}

		search_fields = {self.boxPath: m_db_fullpath, "fname": m_db_fname, "title": m_db_title, }
		is_in_db = self.searchContent(search_fields, fields=("fname",), query_type="AND", exactmatch=False, skipCheckExists=True)
		if isTrash[0]:
			fields["IsTrash"] = str(isTrash[1])
			if isTrash[1] == 0:
				fields["TrashTime"] = str(0)
				self.addToTitleList(m_db_title, m_db_shortDesc, m_db_extDesc)
			else:
				fields["TrashTime"] = str(time())
				if len(is_in_db):
					self.removeFromTitleList(m_db_title, m_db_shortDesc, m_db_extDesc)
		else:
			if exists(trashfile):
				fields["IsTrash"] = str(1)
				if len(is_in_db):
					self.removeFromTitleList(m_db_title, m_db_shortDesc, m_db_extDesc)
				try:
					fields["TrashTime"] = str(stat(trashfile).st_mtime)
				except OSError:
					fields["TrashTime"] = str(time())
			else:
				self.addToTitleList(m_db_title, m_db_shortDesc, m_db_extDesc)
		if withBoxPath:
			self.updateUniqueData(fields, (self.boxPath,))
		else:
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

	def getPlayProgress(self, moviename, movie_len):
		cut_list = []
		if exists(moviename):
			try:
				f = open(moviename, "rb")
				packed = f.read()
				f.close()

				while len(packed) > 0:
					packedCue = packed[:12]
					packed = packed[12:]
					cue = unpack(">QI", packedCue)
					cut_list.append(cue)
			except Exception as ex:
				debugPrint("failure at downloading cut list", LOGLEVEL.ERROR)
		last_end_point = None
		if len(cut_list):
			for (pts, what) in cut_list:
				if what == 3:
					last_end_point = pts / 90000
		try:
			movie_len = int(movie_len)
		except ValueError:
			play_progress = 0
			movie_len = -1
		if movie_len > 0 and last_end_point is not None:
			play_progress = (last_end_point * 100) / movie_len
		else:
			play_progress = 0
			last_end_point = 0
		if play_progress > 100:
			play_progress = 100
		return (last_end_point, play_progress)


moviedb = MovieDataBase()
moviedb.BackgroundTitleListUpdate()


def isMovieinDatabase(title_name, shortdesc, extdesc, short_ratio=0.95, ext_ratio=0.85):
	movie = None
	movie_found = False
	s = {"title": str(title_name)}
	trash_movies = []
#	if config.usage.movielist_use_moviedb_trash.value:
#		trash_movies = moviedb.getTrashEntries()[0]
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
		movie_found = True if real_path not in trash_movies or exists(f"{real_path}.del") else False
	return movie_found


class MovieDBUpdateBase:
	def __init__(self):
		self.navigation = None

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


class MovieDBUpdate(MovieDBUpdateBase):

	def __init__(self):
		MovieDBUpdateBase.__init__(self)
		self.updateTimer = eTimer()
		self.updateTimer.callback.append(self.startUpdate)
		self.timerintervall = 30
		self.longtimerintervall = 180
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
		if self.getInstandby():
			debugPrint("start auto update of moviedb", LOGLEVEL.INFO)
			moviedb.backgroundDBUpdate(moviedb.updateMovieDB)
		else:
			debugPrint("update cancelled - not in Standby", LOGLEVEL.INFO)


moviedbupdate = MovieDBUpdate()


def backgroundDBUpdate(timerEntry):
	moviedb.backgroundDBUpdate(moviedb.updateMovieDB, timerEntry=timerEntry)


functionTimer.add(("moviedbupdate", {"name": _("Update movie database (full)"), "fnc": backgroundDBUpdate}))

# TODO
#functionTimer.add(("movietrashclean", {"name": _("clear movie trash"), "imports": "Components.MovieTrash", "fnc": "movietrash.cleanAll"}))

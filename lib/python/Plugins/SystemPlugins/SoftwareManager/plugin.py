from os import F_OK, R_OK, W_OK, access, makedirs, mkdir, stat  # noqa F401
from os.path import dirname, isdir
from stat import ST_MTIME
from pickle import dump, load
from time import time

from Components.config import config
from Components.SystemInfo import BoxInfo

from Screens.BackupRestore import InitConfig as BackupRestore_InitConfig

boxType = BoxInfo.getItem("machinebuild")
config.plugins.configurationbackup = BackupRestore_InitConfig()


def write_cache(cache_file, cache_data):  # Does a cPickle dump.
	if not isdir(dirname(cache_file)):
		try:
			mkdir(dirname(cache_file))
		except OSError:
			print("%s is a file" % dirname(cache_file))
	with open(cache_file, "wb") as fd:
		dump(cache_data, fd, protocol=5)


def valid_cache(cache_file, cache_ttl):  # See if the cache file exists and is still living.
	try:
		mtime = stat(cache_file)[ST_MTIME]
	except OSError:
		return 0
	curr_time = time()
	if (curr_time - mtime) > cache_ttl:
		return 0
	else:
		return 1


def load_cache(cache_file):  # Does a cPickle load.
	cache_data = None
	with open(cache_file, "rb") as fd:
		cache_data = load(fd)
	return cache_data


def Plugins(path, **kwargs):
	return []

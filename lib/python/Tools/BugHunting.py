from inspect import getargvalues  # WARNING! Don't use inspect.stack()! its very very very slow.
from sys import _getframe


def getFrames(deep=2):
	deep = deep or 1
	frames = []
	for frame in range(2, 3 + deep):
		try:
			frames.append(_getframe(frame))
		except Exception:
			break
	return frames


# printCallSequence(5)
# 14:13:01.164 /usr/lib/enigma2/python/Components/TimerSanityCheck.py:9 __init__(Navigation.py:46) --> __init__(RecordTimer.py:958) --> loadTimer(RecordTimer.py:1048) --> record(RecordTimer.py:1184) --> __init__
# printCallSequence(-5)
# 14:13:01.166 /usr/lib/enigma2/python/Components/TimerSanityCheck.py:20 check <-- record(RecordTimer.py:1185) <-- loadTimer(RecordTimer.py:1048) <-- __init__(RecordTimer.py:958) <-- __init__(Navigation.py:46)
#
def printCallSequence(deep=1):
	deep = deep or 1
	frames = getFrames(abs(deep))
	print(f"[BugHunting] {frames[0].f_code.co_filename}:{frames[0].f_code.co_firstlineno}")
	if deep >= 0:
		for frame in range(0, len(frames)):
			if frame:
				print(f"[BugHunting] <-- {frames[frame].f_code.co_name} ({frames[frame].f_code.co_filename.split("/")[-1]}:{frames[frame].f_lineno})")
			else:
				print(f"[BugHunting] {frames[frame].f_code.co_name}")
	else:
		for frame in range(len(frames) - 1, -1, -1):
			if frame:
				print(f"[BugHunting] {frames[frame].f_code.co_name} ({frames[frame].f_code.co_filename.split("/")[-1]}:{frames[frame].f_lineno}) -->")
			else:
				print(f"[BugHunting] {frames[frame].f_code.co_name}")
	del frames


def printCallSequenceRawData(deep=1):
	deep = abs(deep or 1)
	frames = getFrames(deep)
	print(f"[BugHunting] {frames[0].f_code.co_filename}:{frames[0].f_code.co_firstlineno}")
	for frame in range(0, len(frames)):
		if frame:
			print(f"[BugHunting] <-- {frames[frame].f_code.co_name} ({frames[frame].f_code.co_filename.split("/")[-1]}:{frames[frame].f_lineno}) {getargvalues(frames[frame])}")
		else:
			print(f"[BugHunting] {frames[frame].f_code.co_name} {getargvalues(frames[frame])}")
	del frames

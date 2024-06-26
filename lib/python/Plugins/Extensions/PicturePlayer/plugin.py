from Plugins.Plugin import PluginDescriptor
from enigma import getDesktop

#------------------------------------------------------------------------------------------


def Pic_Thumb(*args, **kwa):
	from . import ui
	return ui.Pic_Thumb(*args, **kwa)


def picshow(*args, **kwa):
	from . import ui
	return ui.picshow(*args, **kwa)


def main(session, **kwargs):
	from .ui import picshow
	session.open(picshow)


def filescan_open(list, session, **kwargs):
	# Recreate List as expected by PicView
	filelist = [((file.path, False), None) for file in list]
	from .ui import Pic_Full_View
	p = filelist[0][0][0]
	session.open(Pic_Full_View, filelist, 0, p)


def filescan(**kwargs):
	from Components.Scanner import Scanner, ScanPath
	import os

	# Overwrite checkFile to only detect local
	class LocalScanner(Scanner):
		def checkFile(self, file):
			return os.path.exists(file.path)

	return \
		LocalScanner(mimetypes=["image/jpeg", "image/png", "image/gif", "image/bmp"],
			paths_to_scan=[
					ScanPath(path="DCIM", with_subdirs=True),
					ScanPath(path="", with_subdirs=False),
				],
			name="Pictures",
			description=_("View photos..."),
			openfnc=filescan_open,
		)


def Plugins(**kwargs):
	screenwidth = getDesktop(0).size().width()
	icon = "pictureplayerhd.png" if screenwidth and screenwidth == 1920 else "pictureplayer.png"

	return [
			PluginDescriptor(name=_("Picture player"), description=_("fileformats (BMP, PNG, JPG, GIF)"), icon=icon, where=PluginDescriptor.WHERE_PLUGINMENU, needsRestart=False, fnc=main),
			PluginDescriptor(name=_("Picture player"), where=PluginDescriptor.WHERE_FILESCAN, needsRestart=False, fnc=filescan)
		]

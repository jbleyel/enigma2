from os import listdir, makedirs, stat, statvfs
from os.path import join, isdir
from re import search

from enigma import eTimer

from Components.AVSwitch import avSwitch
from Components.config import ConfigBoolean, config, configfile
from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Components.Storage import EXPANDER_MOUNT
from Components.SystemInfo import BoxInfo
from Components.Pixmap import Pixmap
from Screens.FlashExpander import MOUNT_DEVICE, MOUNT_MOUNTPOINT, MOUNT_FILESYSTEM
from Screens.HarddiskSetup import HarddiskSelection
from Screens.HelpMenu import ShowRemoteControl
from Screens.MessageBox import MessageBox
from Screens.Standby import TryQuitMainloop, QUIT_RESTART
from Screens.VideoWizard import VideoWizard
from Screens.Wizard import wizardManager, Wizard
from Tools.Directories import fileReadLine, fileReadLines, fileWriteLines

MODULE_NAME = __name__.split(".")[-1]

config.misc.firstrun = ConfigBoolean(default=True)
config.misc.videowizardenabled = ConfigBoolean(default=True)
config.misc.wizardLanguageEnabled = ConfigBoolean(default=True)


class StartWizard(Wizard, ShowRemoteControl):
	_nwPollIntervalMs = 1500
	_nwPollMaxAttempts = 12  # 18 s total

	def __init__(self, session, silent=True, showSteps=False, neededTag=None):
		self.xmlfile = ["startwizard.xml"]
		Wizard.__init__(self, session, showSteps=False)
		ShowRemoteControl.__init__(self)
		self.deviceData = {}
		self.mountData = None
		self.swapDevice = None
		self.swapDeviceIndex = -1
		self.console = Console()
		flashSize = statvfs('/')
		flashSize = (flashSize.f_frsize * flashSize.f_blocks) // 2 ** 20
		self.smallFlashSize = BoxInfo.getItem("SmallFlash") and flashSize < 130
		self.swapExists = "/dev/" in "".join(fileReadLines("/proc/swaps", default=[], source=MODULE_NAME))
		self["wizard"] = Pixmap()
		self["HelpWindow"] = Pixmap()
		self["HelpWindow"].hide()
		self.setTitle(_("Start Wizard"))
		self.nwSelectedIface = None
		self.nwIpFound = ""
		self._nwPollTimer = None
		self._nwPollCount = 0
		self._nwSetupSaved = False

	def markDone(self):
		# Setup remote control, all STBs have same settings except dm8000 which uses a different setting.
		config.misc.rcused.value = 0 if BoxInfo.getItem("machinebuild") == 'dm8000' else 1
		config.misc.rcused.save()
		config.misc.firstrun.value = False
		config.misc.firstrun.save()
		configfile.save()

	def createSwapFileFlashExpander(self, callback):
		def messageBoxCallback(*res):
			if callback and callable(callback):
				callback()

		def isSwapActive(path):
			swaps = fileReadLines("/proc/swaps", default=[], source=MODULE_NAME)
			for line in swaps[1:]:
				parts = line.split()
				if parts and parts[0] == path:
					return True
			return False

		def creataSwapFileCallback(result=None, retVal=None, extraArgs=None):
			print("[FlashExpander] createSwapFile callback DEBUG: retVal=%s, result=%s" % (retVal, result))
			if retVal not in (0, None) and not isSwapActive(fileName):
				if messageBox:
					messageBox.close()
				self.session.open(MessageBox, _("Creating or activating the swap file failed.\n\n%s") % (result or ""), type=MessageBox.TYPE_ERROR)
				return
			fstab = fileReadLines("/etc/fstab", default=[], source=MODULE_NAME)
			print("[FlashExpander] fstabUpdate DEBUG: Begin fstab:\n%s" % "\n".join(fstab))
			fstabNew = [line for line in fstab if "swap" not in line]
			fstabNew.append("%s swap swap defaults 0 0" % fileName)
			fstabNew.append("")
			fileWriteLines("/etc/fstab", "\n".join(fstabNew), source=MODULE_NAME)
			print("[FlashExpander] fstabUpdate DEBUG: Ending fstab:\n%s" % "\n".join(fstabNew))
			messageBox.close()

		print("[StartWizard] DEBUG createSwapFileFlashExpander")
		messageBox = self.session.openWithCallback(messageBoxCallback, MessageBox, _("Please wait, swap is being created. This could take a few minutes to complete."), MessageBox.TYPE_INFO, enable_input=False, windowTitle=_("Create swap"))
		fileName = join("/.FlashExpander", "swapfile")
		commands = []
		commands.append("/bin/dd if=/dev/zero of='%s' bs=1024 count=131072 2>/dev/null" % fileName)  # Use 128 MB because creation of bigger swap is very slow.
		commands.append("/bin/chmod 600 '%s'" % fileName)
		commands.append("/sbin/mkswap '%s'" % fileName)
		commands.append("/sbin/swapon '%s'" % fileName)
		self.console.eBatch(commands, creataSwapFileCallback, debug=True)

	def createSwapFile(self, callback):
		def getPathMountData(path):
			mounts = fileReadLines("/proc/mounts", [], source=MODULE_NAME)
			print("[StartWizard] getPathMountData DEBUG: path=%s." % path)
			for mount in mounts:
				data = mount.split()
				if data[MOUNT_DEVICE] == path:
					status = stat(data[MOUNT_MOUNTPOINT])
					return (data[MOUNT_MOUNTPOINT], status, data)
			return None

		def isSwapActive(path):
			swaps = fileReadLines("/proc/swaps", default=[], source=MODULE_NAME)
			for line in swaps[1:]:
				parts = line.split()
				if parts and parts[0] == path:
					return True
			return False

		def creataSwapFileCallback(result=None, retVal=None, extraArgs=None):
			print("[StartWizard] createSwapFile callback DEBUG: retVal=%s, result=%s" % (retVal, result))
			if retVal not in (0, None) and not isSwapActive(fileName):
				self.session.open(MessageBox, _("Creating or activating the swap file failed.\n\n%s") % (result or ""), type=MessageBox.TYPE_ERROR)
				return
			if callback and callable(callback):
				callback()

		print("[StartWizard] DEBUG createSwapFile: %s" % self.swapDevice)
		fileName = "/.swap/swapfile"
		path = self.deviceData[self.swapDevice][0]
		self.mountData = getPathMountData(path)
		if self.mountData:
			fstab = fileReadLines("/etc/fstab", default=[], source=MODULE_NAME)
			print("[StartWizard] fstabUpdate DEBUG: Starting fstab:\n%s" % "\n".join(fstab))
			fstabNew = [line for line in fstab if "swap" not in line]
			mountData = self.mountData[2]
			line = " ".join(("UUID=%s" % self.swapDevice, "/.swap", mountData[MOUNT_FILESYSTEM], "defaults", "0", "0"))
			fstabNew.append(line)
			fstabNew.append("%s swap swap defaults 0 0" % fileName)
			fstabNew.append("")
			fileWriteLines("/etc/fstab", "\n".join(fstabNew), source=MODULE_NAME)
			print("[StartWizard] fstabUpdate DEBUG: Ending fstab:\n%s" % "\n".join(fstabNew))
			makedirs("/.swap", mode=0o755, exist_ok=True)
			if isSwapActive(fileName):
				print("[StartWizard] DEBUG: Swap already active, skipping swapon.")
				if callback and callable(callback):
					callback()
				return
			commands = []
			commands.append("/bin/mount -a")
			commands.append("/bin/dd if=/dev/zero of='%s' bs=1024 count=131072 2>/dev/null" % fileName)  # Use 128 MB because creation of bigger swap is very slow.
			commands.append("/bin/chmod 600 '%s'" % fileName)
			commands.append("/sbin/mkswap '%s'" % fileName)
			commands.append("/sbin/swapon '%s'" % fileName)
			self.console.eBatch(commands, creataSwapFileCallback, debug=True)
		else:
			self.session.open(MessageBox, _("No valid mount for '%s' found!") % path, type=MessageBox.TYPE_ERROR)

	def swapDeviceList(self):  # Called by startwizard.xml.
		choiceList = []
		for deviceID, deviceData in self.deviceData.items():
			choiceList.append(("%s (%s)" % (deviceData[1], deviceData[0]), deviceID))
		# DEBUG
		print("[StartWizard] DEBUG swapDeviceList: %s" % str(choiceList))

		if len(choiceList) == 0:
			choiceList.append((_("No valid device detected - Press OK"), "."))
		return choiceList

	def swapDeviceSelectionMade(self, index):  # Called by startwizard.xml.
		print("[StartWizard] swapDeviceSelectionMade DEBUG: index='%s'." % index)
		self.swapDeviceIndex = index

	def swapDeviceSelectionMoved(self):  # Called by startwizard.xml.
		print("[StartWizard] DEBUG swapDeviceSelectionMoved: %s" % self.selection)
		self.swapDevice = self.selection

	def readSwapDevices(self, callback=None):
		black = BoxInfo.getItem("mtdblack")
		self.deviceData = {}
		uuids = {}
		for fileName in listdir("/dev/uuid"):
			if black not in fileName:
				m = search(r"(?P<A>mmcblk\d)p1$|(?P<B>sd\w)1$", fileName)
				if m:
					disk = m.group("A") or m.group("B")
					if disk:
						uuids[disk] = (fileReadLine(join("/dev/uuid", fileName)), f"/dev/{fileName}")

		print("[StartWizard] DEBUG readSwapDevices uuids", uuids)

		for (name, hdd) in harddiskmanager.HDDList():
			uuid, device = uuids.get(hdd.device, (None, None))
			if uuid:
				self.deviceData[uuid] = (device, name)

		print("[StartWizard] DEBUG readSwapDevicesCallback: %s" % str(self.deviceData))
		if callback and callable(callback):
			callback()

	def getFreeMemory(self):
		memInfo = fileReadLines("/proc/meminfo", source=MODULE_NAME)
		return int([line for line in memInfo if "MemFree" in line][0].split(":")[1].strip().split(maxsplit=1)[0]) // 1024

	def isFlashExpanderActive(self):
		return isdir(join("/%s/%s" % (EXPANDER_MOUNT, EXPANDER_MOUNT), "bin"))

	def hasPartitions(self):
		partitions = fileReadLines("/proc/partitions", source=MODULE_NAME)
		count = 0
		black = BoxInfo.getItem("mtdblack")
		for line in partitions:
			parts = line.strip().split()
			if parts:
				device = parts[3]
				if not device.startswith(black) and (search(r"^sd[a-z][1-9][\d]*$", device) or search(r"^mmcblk[\d]p[\d]*$", device)):
					count += 1
		return count > 1

	def keyYellow(self):
		if self.wizard[self.currStep]["name"] == "swap":
			if not self.isFlashExpanderActive():
				def formatCallback():
					harddiskmanager.enumerateBlockDevices()
					self.updateValues()
				self.session.openWithCallback(formatCallback, HarddiskSelection)
		else:
			Wizard.keyYellow(self)

	# ------------------------------------------------------------------
	# Network setup steps (nwifaceselect → nwconfig → nwstatus)
	# ------------------------------------------------------------------

	def nwListInterfaces(self):
		result = []
		try:
			from Components.NetworkManager import iNetworkManager as _nm
			for iface, adapter in _nm.adapters.items():
				typeLabel = _("WLAN") if adapter.isWlan else _("LAN")
				name = _nm.getFriendlyAdapterName(iface)
				desc = _nm.getFriendlyAdapterDescription(iface)
				result.append(("%s  %s  (%s)  –  %s" % (typeLabel, name, iface, desc), iface))
		except Exception:
			pass
		result.append((_("Skip network setup"), "skip"))
		return result

	def nwIfaceSelected(self, value):
		self.nwSelectedIface = None if value == "skip" else value

	def nwIfaceMoved(self):
		pass

	def nwAdvanceFromSelect(self):
		if self.nwSelectedIface is None:
			self.currStep = self.getStepWithID("network")
		else:
			self.currStep = self.getStepWithID("nwconfig")
		self.afterAsyncCode()

	def nwOpenSetup(self):
		try:
			from Components.NetworkManager import iNetworkManager as _nm, Connection
			adapter = _nm.adapters.get(self.nwSelectedIface) if self.nwSelectedIface else None
			if adapter is None:
				self._nwDone()
				return
			if adapter.isWlan:
				from Screens.NetworkSetup2 import WiFiAddFlow
				WiFiAddFlow.start(self.session, adapter=adapter, callback=self._nwWlanDone)
			else:
				from Screens.NetworkSetup2 import NetworkConnectionSetup
				if adapter.connections:
					conn = adapter.connections[0]
				else:
					conn = Connection(adapter=adapter.name, name=_("LAN"), enabled=True, dhcp=True)
					adapter.connections.append(conn)
				self.session.openWithCallback(self._nwLanSetupDone, NetworkConnectionSetup, conn, adapter)
			print("[NW-WIZ] nwOpenSetup: openWithCallback returned, updateValues_in_onShown=%s" % (self.updateValues in self.onShown))
		except Exception as e:
			print("[NW-WIZ] nwOpenSetup: EXCEPTION %s -> _nwDone" % e)
			self._nwDone()

	def _nwLanSetupDone(self, saved=False):
		print("[NW-WIZ] _nwLanSetupDone: saved=%s currStep=%s codeAfter=%s updateValues_in_onShown=%s" % (saved, self.currStep, self.codeAfter, self.updateValues in self.onShown))
		self._nwSetupSaved = saved
		self._nwGoToDns()

	def _nwWlanDone(self):
		print("[NW-WIZ] _nwWlanDone called")
		self._nwSetupSaved = True
		self._nwGoToDns()

	def _nwGoToDns(self):
		self.currStep = self.getStepWithID("nwdns") + 1
		self.updateValues()

	def nwActivateAndPoll(self):
		if self._nwSetupSaved:
			try:
				from Components.NetworkManager import iNetworkManager as _nm
				_nm.activateInterface(self.nwSelectedIface, lambda ok: self._nwStartIpPoll())
			except Exception:
				self._nwStartIpPoll()
		else:
			self._nwStartIpPoll()

	def _nwStartIpPoll(self):
		self._nwPollCount = 0
		self.nwIpFound = ""
		if self._nwPollTimer:
			self._nwPollTimer.stop()
		self._nwPollTimer = eTimer()
		self._nwPollTimer.callback.append(self._nwPollIp)
		self._nwPollTimer.start(self._nwPollIntervalMs, True)

	def _nwPollIp(self):
		try:
			import netifaces
			addrs = netifaces.ifaddresses(self.nwSelectedIface or "")
			ip = addrs.get(netifaces.AF_INET, [{}])[0].get("addr", "")
			if ip and ip != "0.0.0.0":
				self.nwIpFound = ip
				self._nwDone()
				return
		except Exception:
			pass
		self._nwPollCount += 1
		if self._nwPollCount >= self._nwPollMaxAttempts:
			self._nwDone()
			return
		self._nwPollTimer.start(self._nwPollIntervalMs, True)

	def _nwDone(self):
		if self._nwPollTimer:
			self._nwPollTimer.stop()
			self._nwPollTimer = None
		self.currStep = self.getStepWithID("nwstatus") + 1
		self.updateValues()

	def nwShowStatus(self):
		if self._nwPollTimer:
			self._nwPollTimer.stop()
			self._nwPollTimer = None
		if self.nwIpFound:
			self["text"].setText(_("Network connected successfully.\n\nInterface: %s\nIP address: %s") % (self.nwSelectedIface or "", self.nwIpFound))
		else:
			self["text"].setText(_("No IP address was received.\n\nThe network connection could not be established."))


class WizardLanguage(Wizard, ShowRemoteControl):
	def __init__(self, session, silent=True, showSteps=False, neededTag=None):
		self.xmlfile = ["wizardlanguage.xml"]
		Wizard.__init__(self, session, showSteps=False)
		ShowRemoteControl.__init__(self)
		self.skinName = ["WizardLanguage", "StartWizard"]
		self.oldLanguage = config.osd.language.value
		self.mode = "720p"
		self.modeList = [(mode[0], mode[0]) for mode in avSwitch.getModeList("HDMI")]
		self["wizard"] = Pixmap()
		self["HelpWindow"] = Pixmap()
		self["HelpWindow"].hide()
		self.setTitle(_("Start Wizard"))
		self.resolutionTimer = eTimer()
		self.resolutionTimer.callback.append(self.resolutionTimeout)
		# preferred = avSwitch.readPreferredModes(saveMode=True)
		preferred = ["720p"]  # Use only 720p because some TV sends wrong edid info
		available = avSwitch.readAvailableModes()
		preferred = list(set(preferred) & set(available))

		if preferred:
			if "2160p50" in preferred:
				self.mode = "2160p"
			elif "2160p30" in preferred:
				self.mode = "2160p30"
			elif "1080p" in preferred:
				self.mode = "1080p"

		self.setMode()

		if not preferred:
			ports = [port for port in avSwitch.getPortList() if avSwitch.isPortUsed(port)]
			if len(ports) > 1:
				self.resolutionTimer.start(20000)
				print("[WizardLanguage] DEBUG start resolutionTimer")

	def setMode(self):
		print("[WizardLanguage] DEBUG setMode %s" % self.mode)
		if self.mode in ("720p", "1080p") and not BoxInfo.getItem("AmlogicFamily"):
			rate = "multi"
		else:
			rate = self.getVideoRate()
		avSwitch.setMode(port="HDMI", mode=self.mode, rate=rate)

	def getVideoRate(self):
		def sortKey(name):
			return {
				"multi": 1,
				"auto": 2
			}.get(name[0], 3)

		rates = []
		for modes in avSwitch.getModeList("HDMI"):
			if modes[0] == self.mode:
				for rate in modes[1]:
					if rate == "auto" and not BoxInfo.getItem("have24hz"):
						continue
					rates.append((rate, rate))
		rates.sort(key=sortKey)
		return rates[0][0]

	def resolutionTimeout(self):
		if self.mode == "720p":
			self.mode = "576i"
		if self.mode == "576i":
			self.mode = "480i"
			self.resolutionTimer.stop()
		self.setMode()

	def saveWizardChanges(self):
		self.resolutionTimer.stop()
		config.misc.wizardLanguageEnabled.value = 0
		config.misc.wizardLanguageEnabled.save()
		configfile.save()
		if config.osd.language.value != self.oldLanguage:
			self.session.open(TryQuitMainloop, QUIT_RESTART)
		self.close()


# StartEnigma.py#L528ff - RestoreSettings
if config.misc.firstrun.value:
	wizardManager.registerWizard(WizardLanguage, config.misc.wizardLanguageEnabled.value, priority=0)
wizardManager.registerWizard(VideoWizard, config.misc.videowizardenabled.value, priority=1)
# wizardManager.registerWizard(LocaleWizard, config.misc.languageselected.value, priority=2)
# FrontprocessorUpgrade FPUpgrade priority = 8
# FrontprocessorUpgrade SystemMessage priority = 9
wizardManager.registerWizard(StartWizard, config.misc.firstrun.value, priority=30)
# StartWizard calls InstallWizard
# NetworkWizard priority = 25

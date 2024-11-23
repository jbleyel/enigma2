from os import mkdir
from os.path import exists, isfile, join, realpath
from re import search, sub

from Components.ActionMap import HelpableActionMap
from Components.ConfigList import ConfigListScreen
from Components.config import ConfigSelection, NoSave
from Components.Console import Console
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo, getBoxDisplayName
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import QUIT_REBOOT, TryQuitMainloop
from Tools.Conversions import scaleNumber
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import SCOPE_GUISKIN, fileReadLine, fileReadLines, fileWriteLines, resolveFilename

MODULE_NAME = __name__.split(".")[-1]


class MountManager(Screen):
	BLKID = "/sbin/blkid"
	MOUNT = "/bin/mount"
	UMOUNT = "/bin/umount"

	DEVICE_TYPES = {
		0: ("USB: ", "icons/dev_usbstick.png"),
		1: ("MMC: ", "icons/dev_mmc.png"),
		2: (_("HARD DISK: "), "icons/dev_hdd.png")
	}
	DEVICE_TYPES_NAME = 0
	DEVICE_TYPES_ICON = 1

	skin = """
	<screen name="MountManager" title="Mount Manager" position="center,center" size="980,465" resolution="1280,720">
		<widget source="devicelist" render="Listbox" position="0,0" size="980,425">
			<convert type="TemplatedMultiContent">
				{"template": [
					MultiContentEntryText(pos = (90, 0), size = (600, 30), font=0, text = 0),
					MultiContentEntryText(pos = (110, 30), size = (600, 50), font=1, flags = RT_VALIGN_TOP, text = 1),
					MultiContentEntryPixmapAlphaBlend(pos = (0, 0), size = (80, 80), png = 2),
				],
				"fonts": [gFont("Regular", 24),gFont("Regular", 20)],
				"itemHeight": 85
				}
			</convert>
		</widget>
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session, mandatoryWidgets=["mounts"], enableHelp=True)
		self.setTitle(_("Mount Manager"))
		self.onChangedEntry = []
		self.deviceList = []
		indexNames = {
			"A": 0,
			"B": 1
		}
		self["devicelist"] = List(self.deviceList, indexNames=indexNames)
		self["devicelist"].onSelectionChanged.append(self.selectionChanged)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Mount Point"))
		self["key_yellow"] = StaticText(_("Unmount"))
		self["key_blue"] = StaticText()
		self["actions"] = HelpableActionMap(self, ["CancelActions", "ColorActions"], {
			"cancel": (self.close, _("Close the Mount Manager screen")),
			"close": (self.keyClose, _("Close the Mount Manager screen and exit all menus")),
			"red": (self.close, _("Close the Mount Manager screen")),
			"green": (self.keyMountPoint, _("Select a permanent mount point for the current device")),
			"yellow": (self.keyToggleMount, _("Toggle a temporary mount for the current device"))
			# "blue": (self.keyBlue _("Reserved for future use"))
		}, prio=0, description=_("Mount Manager Actions"))
		self.console = Console()
		self.mounts = []
		self.partitions = []
		self.fstab = []
		self.knownDevices = []
		self.swapDevices = []
		self.deviceUUID = {}
		self.readDevices()

	def selectionChanged(self):
		if self.deviceList:
			current = self["devicelist"].getCurrent()
			# mountPoint = current[3]
			isMounted = current[5]
			if current:
				try:
					name = str(current[0])
					description = str(current[1].replace("\t", "  "))
				except Exception:
					name = ""
					description = ""
			else:
				name = ""
				description = ""
			self["key_yellow"].setText(_("Unmount") if isMounted else _("Mount"))
			for callback in self.onChangedEntry:
				if callback and callable(callback):
					callback(name, description)

	def readDevices(self):
		def readDevicesCallback(output=None, retVal=None, extraArgs=None):
			self.deviceUUID = {}
			lines = output.splitlines()
			lines = [line for line in lines if "UUID=" in line and ("/dev/sd" in line or "/dev/cf" in line)]
			for line in lines:
				data = line.split()
				UUID = [x.split("UUID=")[1] for x in data if "UUID=" in x][0].replace("\"", "")
				self.deviceUUID[data[0][:-1]] = UUID
			self.swapdevices = [x for x in fileReadLines("/proc/swaps", default=[], source=MODULE_NAME) if x.startswith("/")]
			self.updateDevices()

		self.console.ePopen([self.BLKID, self.BLKID], callback=readDevicesCallback)

	def updateDevices(self, result=None, retval=None, extra_args=None):
		self.partitions = fileReadLines("/proc/partitions", default=[], source=MODULE_NAME)
		self.mounts = fileReadLines("/proc/mounts", default=[], source=MODULE_NAME)
		self.fstab = fileReadLines("/etc/fstab", default=[], source=MODULE_NAME)
		self.knownDevices = fileReadLines("/etc/udev/known_devices", default=[], source=MODULE_NAME)
		self.deviceList = []
		seenDevices = []
		for line in self.partitions:
			parts = line.strip().split()
			if not parts:
				continue
			device = parts[3]
			if not search(r"^sd[a-z][1-9][\d]*$", device) and not search(r"^mmcblk[\d]p[\d]*$", device):
				continue
			if BoxInfo.getItem("mtdrootfs").startswith("mmcblk0p") and device.startswith("mmcblk0p"):
				continue
			if BoxInfo.getItem("mtdrootfs").startswith("mmcblk1p") and device.startswith("mmcblk1p"):
				continue
			if device in seenDevices:
				continue
			seenDevices.append(device)
			self.buildList(device)
		self["devicelist"].list = self.deviceList

	def buildList(self, device):
		def getDeviceTypeModel():
			devicePath = realpath(join("/sys/block", device2, "device"))
			deviceType = 0
			if device2.startswith("mmcblk"):
				model = fileReadLine(join("/sys/block", device2, "device/name"), default="", source=MODULE_NAME)
				deviceType = 1
			else:
				model = fileReadLine(join("/sys/block", device2, "device/model"), default="", source=MODULE_NAME)
			if devicePath.find("/devices/pci") != -1 or devicePath.find("ahci") != -1:
				deviceType = 2
			return deviceType, model

		device2 = device[:7] if device.startswith("mmcblk") else sub(r"[\d]", "", device)
		deviceType, model = getDeviceTypeModel()
		devicePixmap = LoadPixmap(resolveFilename(SCOPE_GUISKIN, self.DEVICE_TYPES[deviceType][self.DEVICE_TYPES_ICON]))
		deviceName = self.DEVICE_TYPES[deviceType][self.DEVICE_TYPES_NAME]
		deviceName = f"{deviceName}{model}"
		for line in self.mounts:
			if line.find(device) != -1:
				parts = line.strip().split()
				d1 = parts[1]
				dtype = parts[2]
				rw = parts[3]
				break
			else:
				if device in self.swapDevices:
					parts = line.strip().split()
					d1 = _("None")
					dtype = "swap"
					rw = _("None")
					break
				else:
					d1 = _("None")
					dtype = _("unavailable")
					rw = _("None")

		size = 0
		for line in self.partitions:
			if line.find(device) != -1:
				parts = line.strip().split()
				size = int(parts[2]) * 1024
				break
		if not size:
			size = fileReadLine(join("/sys/block", device2, device, "size"), default=None, source=MODULE_NAME)
			try:
				size = int(size) * 512
			except ValueError:
				size = 0
		if size:
			size = f"{_("Size")}: {scaleNumber(size, format="%.2f")}"
			if rw.startswith("rw"):
				rw = " R/W"
			elif rw.startswith("ro"):
				rw = " R/O"
			else:
				rw = ""
			des = f"{size}\t{_("Mount: ")}{d1}\n{_("Device: ")}{join("/dev", device)}\t{_("Type: ")}{dtype}{rw}"
			mountP = d1
			deviceP = f"/dev/{device}"
			isMounted = len([m for m in self.mounts if mountP in m])
			UUID = self.deviceUUID.get(deviceP)
			UUIDMount = ""
			devMount = ""
			knownDevice = ""
			for known in self.knownDevices:
				if UUID in known:
					knownDevice = known
			for fstab in self.fstab:
				fstabData = fstab.split()
				if fstabData:
					if UUID in fstabData:
						UUIDMount = (fstabData[0], fstabData[1])
					elif deviceP in fstabData:
						devMount = (fstabData[0], fstabData[1])
			res = (deviceName, des, devicePixmap, mountP, deviceP, isMounted, UUID, UUIDMount, devMount, knownDevice, deviceType, model)
			print(res)
			self.deviceList.append(res)

	def keyClose(self):
		self.close((True, ))

	def keyMountPoint(self):
		def keyMountPointCallback(answer):
			if answer:
				newFstab = fileReadLines("/etc/fstab", default=[], source=MODULE_NAME)
				newFstab = [l for l in newFstab if answer[1] not in l]
				newFstab = [l for l in newFstab if deviceP not in l]
				newFstab = [l for l in newFstab if deviceUuid not in l]
				newFstab.append(f"UUID={deviceUuid}\t{answer[1]}\tauto\tdefaults\t0 0\n")
				fileWriteLines("/etc/fstab", newFstab, source=MODULE_NAME)
				if not exists(answer[1]):
					mkdir(answer[1], 0o755)
				self.console.ePopen([self.MOUNT, self.MOUNT, "-a"], self.updateDevices)

		if self.deviceList:
			current = self["devicelist"].getCurrent()
			if current:
				deviceP = current[4]
				deviceUuid = self.deviceUUID.get(deviceP)
				title = _("Select the new mount point for: '%s'") % current[11]
				choiceList = [(f"/media/{x}", f"/media/{x}") for x in self.getMountPoints(current[10])]
				self.session.openWithCallback(keyMountPointCallback, ChoiceBox, choiceList=choiceList, buttonList=[], windowTitle=title)

	def keyToggleMount(self):
		def keyYellowCallback(answer):
			def checkMount(data, retVal, extraArgs):
				if retVal:
					print(f"[MountManager] mount failed for device:{device} / RC:{retVal}")
				self.updateDevices()
				mountok = False
				for line in self.mounts:
					if line.find(device) != -1:
						mountok = True
				if not mountok:
					self.session.open(MessageBox, _("Mount failed"), MessageBox.TYPE_INFO, timeout=5)
			if answer:
				if not exists(answer[1]):
					mkdir(answer[1], 0o755)
				self.console.ePopen([self.MOUNT, self.MOUNT, device, f"{answer[1]}/"], checkMount)

		current = self["devicelist"].getCurrent()
		if current:
			isMounted = current[5]
			mountp = current[3]
			device = current[4]
			if isMounted:
				self.console.ePopen([self.UMOUNT, self.UMOUNT, mountp])
				try:
					mounts = open("/proc/mounts")
				except OSError:
					return -1
				mountcheck = mounts.readlines()
				mounts.close()
				for line in mountcheck:
					parts = line.strip().split(" ")
					if realpath(parts[0]).startswith(device):
						self.session.open(MessageBox, _("Can't unmount partition, make sure it is not being used for swap or record/time shift paths"), MessageBox.TYPE_INFO)
			else:
				title = _("Select the new mount point for: '%s'") % current[11]
				choiceList = [(f"/media/{x}", f"/media/{x}") for x in self.getMountPoints(current[10])]
				self.session.openWithCallback(keyYellowCallback, ChoiceBox, choiceList=choiceList, buttonList=[], windowTitle=title)
			self.updateDevices()

	def keyBlue(self):
		pass

	def getMountPoints(self, deviceType):
		match deviceType:
			case 0:
				result = ["usb", "usb2", "usb3"]
			case 1:
				result = ["mmc", "mmc2", "mmc3"]
			case _:
				result = ["hdd", "hdd2", "hdd3"]
		return result

	def createSummary(self):
		return DevicesPanelSummary


class HddMount(MountManager):
	pass


class DevicesPanelSummary(Screen):
	def __init__(self, session, parent):
		Screen.__init__(self, session, parent=parent)
		self.skinName = "SetupSummary"
		self["entry"] = StaticText("")
		self["value"] = StaticText("")
		self.onShow.append(self.addWatcher)
		self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		self.parent.onChangedEntry.append(self.selectionChanged)
		self.parent.selectionChanged()

	def removeWatcher(self):
		self.parent.onChangedEntry.remove(self.selectionChanged)

	def selectionChanged(self, name, desc):
		self["entry"].text = name
		self["value"].text = desc

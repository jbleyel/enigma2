from os import mkdir
from os.path import exists, isfile, join, realpath
from re import search, sub

from enigma import getDeviceDB

from Components.ActionMap import HelpableActionMap
#from Components.ConfigList import ConfigListScreen
from Components.config import ConfigSelection, ConfigText, NoSave
from Components.Console import Console
from Components.Sources.List import List
from Components.Label import Label
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo  # , getBoxDisplayName
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import QUIT_REBOOT, TryQuitMainloop
from Tools.Conversions import scaleNumber
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import SCOPE_GUISKIN, fileReadLine, fileReadLines, fileWriteLines, resolveFilename

MODULE_NAME = __name__.split(".")[-1]


class StorageDevices():
	BLKID = "/sbin/blkid"
	DEVICE_TYPES = {
		0: ("USB: ", "icons/dev_usbstick.png"),
		1: ("MMC: ", "icons/dev_mmc.png"),
		2: (_("HARD DISK: "), "icons/dev_hdd.png")
	}
	DEVICE_TYPES_NAME = 0
	DEVICE_TYPES_ICON = 1

	INDEX_NAME = 0
	INDEX_DESC = 1
	INDEX_PIXMAP = 2
	INDEX_MOUNT_POINT = 3
	INDEX_DEVICE_POINT = 4
	INDEX_ISMOUNTED = 5
	INDEX_DATA = 6

	def __init__(self):
		self.widget = None
		self.mounts = []
		self.partitions = []
		self.fstab = []
		self.knownDevices = []
		self.swapDevices = []
		self.deviceUUID = {}
		self.deviceList = []
		self.console = Console()

	def readDevices(self):
		def readDevicesCallback(output=None, retVal=None, extraArgs=None):
			self.deviceUUID = {}
			lines = output.splitlines()
			lines = [line for line in lines if "UUID=" in line and ("/dev/sd" in line or "/dev/cf" in line or "/dev/mmc" in line)]
			for line in lines:
				data = line.split()
				UUID = [x.split("UUID=")[1] for x in data if "UUID=" in x][0].replace("\"", "")
				self.deviceUUID[data[0][:-1]] = UUID
			self.swapdevices = [x for x in fileReadLines("/proc/swaps", default=[], source=MODULE_NAME) if x.startswith("/")]
			self.updateDevices()

		self.console.ePopen([self.BLKID, self.BLKID], callback=readDevicesCallback)

	def updateDevices(self):
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
		if self.widget:
			self.widget.list = self.deviceList

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
			return devicePath[4:], deviceType, model

		device2 = device[:7] if device.startswith("mmcblk") else sub(r"[\d]", "", device)
		physdev, deviceType, model = getDeviceTypeModel()
		devicePixmap = LoadPixmap(resolveFilename(SCOPE_GUISKIN, self.DEVICE_TYPES[deviceType][self.DEVICE_TYPES_ICON]))
		deviceName = self.DEVICE_TYPES[deviceType][self.DEVICE_TYPES_NAME]
		deviceName = f"{deviceName}{model}"
		deviceLocation = ""
		for physdevprefix, pdescription in list(getDeviceDB().items()):
			if physdev.startswith(physdevprefix):
				deviceLocation = pdescription

		deviceMounts = []

		for line in [line for line in self.mounts if line.find(device) != -1]:
			parts = line.strip().split()
			d1 = parts[1]
			dtype = parts[2]
			rw = parts[3]
			deviceMounts.append((d1, dtype, rw))

		if not deviceMounts:
			for line in [line for line in self.mounts if line.find(device) == -1]:
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
			mountP = d1
			deviceP = f"/dev/{device}"
			isMounted = len([m for m in self.mounts if mountP in m])
			UUID = self.deviceUUID.get(deviceP)
			knownDevice = ""
			for known in self.knownDevices:
				if UUID and UUID in known:
					knownDevice = known
			if ":None" in knownDevice:
				d1 = "Ignore"
			des = f"{size}\t{_("Mount")}: {d1}\n{_("Device: ")}{join("/dev", device)}\t{_("Type")}: {dtype}{rw}"
			fstabMountPoint = ""
			for fstab in self.fstab:
				fstabData = fstab.split()
				if fstabData:
					if UUID and UUID in fstabData:
						fstabMountPoint = fstabData[1]
					elif deviceP in fstabData:
						fstabMountPoint = fstabData[1]

			description = []
			description.append(f"{_("Device: ")}{join("/dev", device)}")
			description.append(f"{_("Size")}: {size}")
			description.append(f"{_("Mount")}: {d1}")
			description.append(f"{_("Type")}: {dtype}{rw}")
			description.append(f"{_("Name")}: {model}")
			description.append(f"{_("Path")}: {physdev}")
			if deviceLocation:
				description.append(f"{_("Position")}: {deviceLocation}")
			description = "\n".join(description)
			deviceData = {
				"name": deviceName,
				"device": device,
				"disk": device2,
				"UUID": UUID,
				"mountPoint": mountP,
				"devicePoint": deviceP,
				"fstabMountPoint": fstabMountPoint,
				"isMounted": isMounted,
				"knownDevice": knownDevice,
				"model": model,
				"location": deviceLocation,
				"description": description,
				"deviceType": deviceType
			}
			#										3		4			5		6		7			8			9			10		11	     12		    		13
			# res = (deviceName, des, devicePixmap, mountP, deviceP, isMounted, UUID, UUIDMount, devMount, knownDevice, deviceType, model, deviceLocation, description)
			res = (deviceName, des, devicePixmap, mountP, deviceP, isMounted, deviceData)
			print(res)
			self.deviceList.append(res)

	def buildDevices(self, deviceIndex=-1):
		devices = []
		for index, device in enumerate(self.deviceList):
			if deviceIndex == -1 or index == deviceIndex:
				deviceData = device[self.INDEX_DATA]
				name = deviceData.get("name")
				deviceLocation = deviceData.get("location")
				if deviceLocation:
					name = f"{name} ({deviceLocation})"
				isMounted = deviceData.get("isMounted")
				fstabMountPoint = deviceData.get("fstabMountPoint")
				deviceP = deviceData.get("devicePoint")
				deviceUuid = deviceData.get("UUID")
				deviceType = deviceData.get("deviceType")
				choiceList = [("None", "None"), ("", "Custom")]
				if "sr" in deviceP:
					choiceList.extend([("/media/cdrom", "/media/cdrom")], [("/media/dvd", "/media/dvd")])
				else:
					choiceList.extend([(f"/media/{x}", f"/media/{x}") for x in self.getMountPoints(deviceType)])
				if fstabMountPoint not in [x[0] for x in choiceList]:
					choiceList.insert(0, (fstabMountPoint, fstabMountPoint))
				devices.append((deviceP, fstabMountPoint, isMounted, deviceUuid, name, choiceList))
		return devices

	def getMountPoints(self, deviceType):
		match deviceType:
			case 0:
				result = ["usb", "usb2", "usb3"]
			case 1:
				result = ["mmc", "mmc2", "mmc3"]
			case _:
				result = []
		result.extend(["hdd", "hdd2", "hdd3"])
		for dev in result[:]:
			for fstab in self.fstab:
				if fstab:
					fstabData = fstab.split()
					if fstabData[1] == f"/media/{dev}" and dev in result:
						result.remove(dev)
		return result


class MountManager(Screen):
	MOUNT = "/bin/mount"
	UMOUNT = "/bin/umount"

	skin = """
	<screen name="MountManager" title="Mount Manager" position="center,center" size="1080,465" resolution="1280,720">
		<widget source="devicelist" render="Listbox" position="0,0" size="680,425">
				<templates>
					<template name="Default" fonts="Regular;24,Regular;20" itemHeight="85">
						<mode name="default">
							<text index="0" position="90,0" size="600,30" font="0" />
							<text index="1" position="110,30" size="600,50" font="1" verticalAlignment="top" />
							<pixmap index="2" position="0,0" size="80,80" alpha="blend" scale="centerScaled" />
						</mode>
				</template>
			</templates>
		</widget>
		<widget name="description" position="680,0" size="400,e-60" font="Regular;20" verticalAlignment="top" horizontalAlignment="left" />
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
		self.devices = StorageDevices()
		indexNames = {
			"A": 0,
			"B": 1
		}
		self["devicelist"] = List(self.devices.deviceList, indexNames=indexNames)
		self["devicelist"].onSelectionChanged.append(self.selectionChanged)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Mount Point"))
		self["key_yellow"] = StaticText(_("Unmount"))
		self["key_blue"] = StaticText()
		self["description"] = Label()
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"cancel": (self.close, _("Close the Mount Manager screen")),
			"ok": (self.keyMountPoint, _("Select a permanent mount point for the current device")),
			"close": (self.keyClose, _("Close the Mount Manager screen and exit all menus")),
			"red": (self.close, _("Close the Mount Manager screen")),
			"green": (self.keyMountPoints, _("Select a permanent mount point for all devices")),
			"yellow": (self.keyToggleMount, _("Toggle a temporary mount for the current device"))
			# "blue": (self.keyBlue _("Reserved for future use"))
		}, prio=0, description=_("Mount Manager Actions"))
		self.needReboot = False
		self.devices.widget = self["devicelist"]
		self.devices.readDevices()
		self.console = Console()

	def selectionChanged(self):
		if self.devices.deviceList:
			current = self["devicelist"].getCurrent()
			deviceData = current[self.devices.INDEX_DATA]
			isMounted = deviceData.get("isMounted")
			# mountPoint = current[3]
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
			fstabMountPoint = deviceData.get("fstabMountPoint")
			knownDevice = deviceData.get("knownDevice")
			if fstabMountPoint:
				self["key_yellow"].setText("")
			elif ":None" in knownDevice:
				self["key_yellow"].setText(_("Activate"))
			else:
				self["key_yellow"].setText(_("Unmount") if isMounted else _("Mount"))
			for callback in self.onChangedEntry:
				if callback and callable(callback):
					callback(name, description)

			description = deviceData.get("description")
			self["description"].setText(description)

	def keyClose(self):
		if self.needReboot:
			self.session.open(TryQuitMainloop, QUIT_REBOOT)
		else:
			self.close((True, ))

	def keyMountPoints(self):
		def keyMountPointsCallback(needsReboot=False):
			self.updateDevices()

		devices = self.devices.buildDevices()
		self.session.openWithCallback(keyMountPointsCallback, MountManagerMountPoints, devices)

	def keyMountPoint(self):
		def keyMountPointCallback(needsReboot=False):
			self.updateDevices()

		devices = self.devices.buildDevices(self["devicelist"].getCurrentIndex())
		self.session.openWithCallback(keyMountPointCallback, MountManagerMountPoints, devices)

		return

		def keyMountPointCallback(answer):
			def keyMountPointCallback2(result=None, retval=None, extra_args=None):
				print("keyMountPointCallback2")
				print(retval)
				print(result)
				isMounted = current[5]
				mountp = current[3]
				device = current[4]
				self.updateDevices()
				if answer[0] == "None" or device != current[4] or current[5] != isMounted or mountp != current[3]:
					self.needReboot = True

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
			deviceData = current[self.devices.INDEX_DATA]
			fstabMountPoint = deviceData.get("fstabMountPoint")
			knownDevice = deviceData.get("knownDevice")
			if fstabMountPoint:
				return
			elif ":None" in knownDevice:
				self.knownDevices.remove(knownDevice)
				fileWriteLines("/etc/udev/known_devices", self.knownDevices, source=MODULE_NAME)
			else:
				isMounted = deviceData.get("isMounted")
				mountPoint = deviceData.get("mountPoint")
				deviceType = deviceData.get("deviceType")
				model = deviceData.get("model")
				device = deviceData.get("devicePoint")
				if isMounted:
					self.console.ePopen([self.UMOUNT, self.UMOUNT, mountPoint])
					try:
						mounts = open("/proc/mounts")
					except OSError:
						return -1
					mountcheck = mounts.readlines()
					mounts.close()
					for line in mountcheck:
						parts = line.strip().split(" ")
						if parts[1] == mountPoint:
							self.session.open(MessageBox, _("Can't unmount partition, make sure it is not being used for swap or record/time shift paths"), MessageBox.TYPE_INFO)
				else:
					title = _("Select the new mount point for: '%s'") % model
					choiceList = [(f"/media/{x}", f"/media/{x}") for x in self.devices.getMountPoints(deviceType)]
					self.session.openWithCallback(keyYellowCallback, ChoiceBox, choiceList=choiceList, buttonList=[], windowTitle=title)
			self.updateDevices()

	def keyBlue(self):
		pass

	def createSummary(self):
		return DevicesPanelSummary


class MountManagerMountPoints(Setup):
	defaultOptions = {
		"auto": "",
		"ext4": "defaults,noatime",
		"vfat": "rw,iocharset=utf8,uid=0,gid=0,umask=0022",
		"extfat": "rw,iocharset=utf8,uid=0,gid=0,umask=0022",
		"ntfs-3g": "defaults,uid=0,gid=0,umask=0022",
		"iso9660": "ro,defaults",
		"udf": "ro,defaults",
		"hfsplus": "rw,force,uid=0,gid=0",
		"btrfs": "defaults,noatime",
		"xfs": "defaults,compress=zstd,noatime",
		"fuseblk": "defaults,uid=0,gid=0"
	}

	def __init__(self, session, devices=None):
		if devices is None:
			devicesObj = StorageDevices()
			devicesObj.readDevices()
			devices = devicesObj.buildDevices()

		self.devices = devices
		self.mountPoints = []
		self.customMountPoints = []
		self.fileSystems = []
		self.options = []
		self.defaultMountpoints = []

		defaults = [
			"usb7", "usb6", "usb5", "usb4", "usb3", "usb2", "usb", "hdd"
		]

		# device , fstabmountpoint, isMounted , deviceUuid, name, choiceList
		for device in devices:
			if "sr" in device[0]:
				self.defaultMountpoints.append("/media/cdrom")
			else:
				deviceName = device[1].replace("/media/", "")
				if device[1]:
					self.defaultMountpoints.append(device[1])
				else:
					self.defaultMountpoints.append(f"/media/{defaults.pop()}")
				if deviceName in defaults:
					defaults.remove(deviceName)

		for index, device in enumerate(devices):
			self.mountPoints.append(NoSave(ConfigSelection(default=self.defaultMountpoints[index], choices=device[5])))
			self.customMountPoints.append(NoSave(ConfigText()))
			if "sr" in device[0]:
				fileSystems = ["auto", "iso9660", "udf"]
			else:
				fileSystems = ["auto", "ext4", "vfat"]
				if exists("/sbin/mount.exfat"):
					fileSystems.append("exfat")
				if exists("/sbin/mount.ntfs-3g"):
					fileSystems.append("ntfs-3g")
				if exists("/sbin/mount.fuse"):
					fileSystems.append("fuseblk")
				fileSystems.extend(["hfsplus", "btrfs", "xfs"])
			fileSystemChoices = [(x, x) for x in fileSystems]
			self.fileSystems.append(NoSave(ConfigSelection(default=fileSystems[0], choices=fileSystemChoices)))
			self.options.append(NoSave(ConfigText("defaults")))

		Setup.__init__(self, session=session, setup="")
		self.setTitle(_("Select the mount points"))

	def appendEntries(self, index, device):
		items = []
		items.append(("%s - %s" % (device[0], device[4]),))
		items.append((_("Mountpoint"), self.mountPoints[index], _("Select the mountpoint for the device."), index))
		if self.mountPoints[index].value != "None":
			if self.mountPoints[index].value == "":
				items.append((_("Custom mountpoint"), self.customMountPoints[index], _("Define the custom ountpoint for the device."), index))
			items.append((_("Filesystem"), self.fileSystems[index], _("Select the filesystem for the device."), index))
			items.append((_("Options"), self.options[index], _("Define the filesystem mount options."), index))
		return items

	def createSetup(self):  # NOSONAR silence S2638
		items = []
		for index, device in enumerate(self.devices):
			items = items + self.appendEntries(index, device)
		print(items)
		Setup.createSetup(self, appendItems=items)

	def changedEntry(self):
		current = self["config"].getCurrent()[1]
		index = self["config"].getCurrent()[3]
		if current == self.fileSystems[index]:
			self.options[index].value = self.defaultOptions.get(self.fileSystems[index].value)
		Setup.changedEntry(self)

	def keySave(self):
		def keySaveCallback(result=None, retval=None, extra_args=None):
			needReboot = False
#			isMounted = current[5]
#			mountp = current[3]
#			device = current[4]
#			self.updateDevices()
#			if answer[0] == "None" or device != current[4] or current[5] != isMounted or mountp != current[3]:
#				self.needReboot = True

			self.close(needReboot)

		oldFstab = fileReadLines("/etc/fstab", default=[], source=MODULE_NAME)
		newFstab = oldFstab[:]
		for index, device in enumerate(self.devices):
			mountPoint = self.mountPoints[index].value or self.customMountPoints[index].value
			fileSystem = self.fileSystems[index].value
			options = self.options[index].value
			# device , fstabmountpoint, isMounted , deviceUuid, name, choiceList
			# deviceName = device[0]
			currentMountPoint = device[1]
			UUID = device[3]
			newFstab = [l for l in newFstab if currentMountPoint not in l]
			newFstab = [l for l in newFstab if UUID not in l]
			newFstab = [l for l in newFstab if mountPoint not in l]
			if mountPoint != "None":
				newFstab.append(f"UUID={UUID}\t{mountPoint}\t{fileSystem}\t{options}\t0 0")
			if mountPoint != "None":
				if not exists(mountPoint):
					mkdir(mountPoint, 0o755)

		if newFstab != oldFstab:
			fileWriteLines("/etc/fstab", newFstab, source=MODULE_NAME)
			self.console.ePopen([self.MOUNT, self.MOUNT, "-a"], keySaveCallback)
		else:
			self.close(False)

	def keyCancel(self):
		self.close(False)


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

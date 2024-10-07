# -*- coding: utf-8 -*-
from os import remove
from os.path import isfile
from twisted.internet.protocol import Protocol, Factory

from Plugins.Plugin import PluginDescriptor
from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Screens.MessageBox import MessageBox, ModalMessageBox
from Tools.Directories import fileReadLines, fileWriteLines

# globals
hotplugNotifier = []
audiocd = False


def AudiocdAdded():
	global audiocd
	if audiocd:
		return True
	else:
		return False


def processHotplugData(self, v):
	mode = v.get("mode")
	print("[Hotplug.plugin.py]:", v)
	action = v.get("ACTION")
	if mode == 1:
		if action == "add":
			ID_TYPE = v.get("ID_TYPE")
			DEVTYPE = v.get("DEVTYPE")
			if ID_TYPE == "disk" and DEVTYPE == "partition":
				device = v.get("DEVPATH")
				DEVNAME = v.get("DEVNAME")
				ID_FS_TYPE = v.get("ID_FS_TYPE")
				ID_BUS = v.get("ID_BUS")
				ID_FS_UUID = v.get("ID_FS_UUID")
				ID_MODEL = v.get("ID_MODEL")
				ID_PART_ENTRY_SIZE = v.get("ID_PART_ENTRY_SIZE")
				notFound = True
				knownDevices = fileReadLines("/etc/udev/known_devices")
				if knownDevices:
					for device in knownDevices:
						deviceData = device.split(":")
						if len(deviceData) == 2 and deviceData[0] == ID_FS_UUID and deviceData[1]:
							notFound = False
							break
				if notFound:
					# TODO Text
					text = f"{ID_MODEL} - {DEVNAME}\n"
					text = _("A new device has been pluged-in:\n%s") % text
					mountPoint = "/media/usb"  # TODO

					def newDeviceCallback(answer):
						if answer:
							fstab = fileReadLines("/etc/fstab")
							if answer == 1:
								knownDevices.append(f"{ID_FS_UUID}:None")
							elif answer == 2:
								knownDevices.append(f"{ID_FS_UUID}:{mountPoint}")
								fstab.append(f"{ID_FS_UUID} {mountPoint} {ID_FS_TYPE} defaults 0 0")
								fileWriteLines("/etc/fstab", fstab)
								Console().ePopen(("/bin/mount", "-a"))
							elif answer == 3:
								Console().ePopen(("/bin/mount", "-t", ID_FS_TYPE, DEVNAME, mountPoint))

							if answer in (1, 2):
								fileWriteLines("/etc/udev/known_devices", knownDevices)
						harddiskmanager.enumerateBlockDevices()

					choiceList = [
						(_("Do nothing"), 0),
						(_("Ignore this device"), 1),
						(_("Mount as %s") % mountPoint, 2),
						(_("Temporary mount as %s" % mountPoint), 3)
					]
					ModalMessageBox.instance.showMessageBox(text=text, list=choiceList, windowTitle=_("New Device detected"), callback=newDeviceCallback)
				else:
					harddiskmanager.enumerateBlockDevices()

		elif action == "remove":
			ID_TYPE = v.get("ID_TYPE")
			DEVTYPE = v.get("DEVTYPE")
			if ID_TYPE == "disk" and DEVTYPE == "partition":
				#device = v.get("DEVNAME")
				#harddiskmanager.removeHotplugPartition(device)
				harddiskmanager.enumerateBlockDevices()  # TODO
		elif action == "ifup":
			interface = v.get("INTERFACE")
		elif action == "ifdown":
			interface = v.get("INTERFACE")
		elif action == "online":
			state = v.get("STATE")

	else:
		device = v.get("DEVPATH")
		physdevpath = v.get("PHYSDEVPATH")
		media_state = v.get("X_E2_MEDIA_STATUS")
		global audiocd

		dev = device.split("/")[-1]

		if action == "add":
			error, blacklisted, removable, is_cdrom, partitions, medium_found = harddiskmanager.addHotplugPartition(dev, physdevpath)
		elif action == "remove":
			harddiskmanager.removeHotplugPartition(dev)
		elif action == "audiocdadd":
			audiocd = True
			media_state = "audiocd"
			error, blacklisted, removable, is_cdrom, partitions, medium_found = harddiskmanager.addHotplugAudiocd(dev, physdevpath)
			print("[Hotplug.plugin.py] AUDIO CD ADD")
		elif action == "audiocdremove":
			audiocd = False
			file = []
			# Removing the invalid playlist.e2pls If its still the audio cd's list
			# Default setting is to save last playlist on closing Mediaplayer.
			# If audio cd is removed after Mediaplayer was closed,
			# the playlist remains in if no other media was played.
			if isfile("/etc/enigma2/playlist.e2pls"):
				with open("/etc/enigma2/playlist.e2pls") as f:
					file = f.readline().strip()
			if file and ".cda" in file:
				try:
					remove("/etc/enigma2/playlist.e2pls")
				except OSError:
					pass
			harddiskmanager.removeHotplugPartition(dev)
			print("[Hotplug.plugin.py] REMOVING AUDIOCD")
		elif media_state is not None:
			if media_state == "1":
				harddiskmanager.removeHotplugPartition(dev)
				harddiskmanager.addHotplugPartition(dev, physdevpath)
			elif media_state == "0":
				harddiskmanager.removeHotplugPartition(dev)

		for callback in hotplugNotifier:
			try:
				callback(dev, action or media_state)
			except AttributeError:
				hotplugNotifier.remove(callback)


class Hotplug(Protocol):
	def __init__(self):
		pass

	def connectionMade(self):
		print("[Hotplug.plugin.py] connection!")
		self.received = ""

	def dataReceived(self, data):
		if isinstance(data, bytes):
			data = data.decode()
		self.received += data

	def connectionLost(self, reason):
		print("[Hotplug.plugin.py] connection lost!")
		v = {}
		if "\n" in self.received:
			data = self.received[:-1].split("\n")
			v["mode"] = 1
		else:
			data = self.received.split("\0")[:-1]
			v["mode"] = 0
		for x in data:
			i = x.find("=")
			var, val = x[:i], x[i + 1:]
			v[var] = val
		processHotplugData(self, v)


def autostart(reason, **kwargs):
	if reason == 0:
		from twisted.internet import reactor
		try:
			remove("/tmp/hotplug.socket")
		except OSError:
			pass
		factory = Factory()
		factory.protocol = Hotplug
		reactor.listenUNIX("/tmp/hotplug.socket", factory)


def Plugins(**kwargs):
	return PluginDescriptor(name="Hotplug", description="listens to hotplug events", where=PluginDescriptor.WHERE_AUTOSTART, needsRestart=True, fnc=autostart)

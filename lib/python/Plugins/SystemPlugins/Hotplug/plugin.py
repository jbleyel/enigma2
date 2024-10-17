from os import remove
from os.path import exists, isfile
from twisted.internet import reactor
from twisted.internet.protocol import Factory, Protocol

from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import ModalMessageBox
from Tools.Directories import fileReadLines, fileWriteLines

HOTPLUG_SOCKET = "/tmp/hotplug.socket"

# globals
hotplugNotifier = []
audiocd = False


class Hotplug(Protocol):
	def __init__(self):
		self.received = ""

	def connectionMade(self):
		print("[Hotplug] Connection made.")
		self.received = ""

	def dataReceived(self, data):
		if isinstance(data, bytes):
			data = data.decode()
		self.received += data
		print(f"[Hotplug] Data received: '{", ".join(self.received.split("\0")[:-1])}'.")

	def connectionLost(self, reason):
		print(f"[Hotplug] Connection lost reason '{reason}'.")
		eventData = {}
		if "\n" in self.received:
			data = self.received[:-1].split("\n")
			eventData["mode"] = 1
		else:
			data = self.received.split("\0")[:-1]
			eventData["mode"] = 0
		for values in data:
			variable, value = values.split("=", 1)
			eventData[variable] = value
		processHotplugData(eventData)


def AudiocdAdded():
	global audiocd
	return audiocd


def processHotplugData(eventData):
	mode = eventData.get("mode")
	print("[Hotplug.plugin.py]:", eventData)
	action = eventData.get("ACTION")
	if mode == 1:
		if action == "add":
			ID_TYPE = eventData.get("ID_TYPE")
			DEVTYPE = eventData.get("DEVTYPE")
			if ID_TYPE == "disk" and DEVTYPE == "partition":
				device = eventData.get("DEVPATH")
				DEVNAME = eventData.get("DEVNAME")
				ID_FS_TYPE = eventData.get("ID_FS_TYPE")
				ID_BUS = eventData.get("ID_BUS")
				ID_FS_UUID = eventData.get("ID_FS_UUID")
				ID_MODEL = eventData.get("ID_MODEL")
				ID_PART_ENTRY_SIZE = eventData.get("ID_PART_ENTRY_SIZE")
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
			ID_TYPE = eventData.get("ID_TYPE")
			DEVTYPE = eventData.get("DEVTYPE")
			if ID_TYPE == "disk" and DEVTYPE == "partition":
				#device = v.get("DEVNAME")
				#harddiskmanager.removeHotplugPartition(device)
				harddiskmanager.enumerateBlockDevices()  # TODO
		elif action == "ifup":
			interface = eventData.get("INTERFACE")
		elif action == "ifdown":
			interface = eventData.get("INTERFACE")
		elif action == "online":
			state = eventData.get("STATE")

	else:
		device = eventData.get("DEVPATH", "").split("/")[-1]
		physicalDevicePath = eventData.get("PHYSDEVPATH")
		mediaState = eventData.get("X_E2_MEDIA_STATUS")
		global audiocd

		if action == "add":
			error, blacklisted, removable, is_cdrom, partitions, medium_found = harddiskmanager.addHotplugPartition(device, physicalDevicePath)
		elif action == "remove":
			harddiskmanager.removeHotplugPartition(device)
		elif action == "audiocdadd":
			audiocd = True
			mediaState = "audiocd"
			error, blacklisted, removable, is_cdrom, partitions, medium_found = harddiskmanager.addHotplugAudiocd(device, physicalDevicePath)
			print("[Hotplug] Adding AudioCD.")
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
			harddiskmanager.removeHotplugPartition(device)
			print("[Hotplug] Removing AudioCD.")
		elif mediaState is not None:
			if mediaState == "1":
				harddiskmanager.removeHotplugPartition(device)
				harddiskmanager.addHotplugPartition(device, physicalDevicePath)
			elif mediaState == "0":
				harddiskmanager.removeHotplugPartition(device)

		for callback in hotplugNotifier:
			try:
				callback(device, action or mediaState)
			except AttributeError:
				hotplugNotifier.remove(callback)


def autostart(reason, **kwargs):
	if reason == 0:
		print("[Hotplug] Starting hotplug handler.")
		try:
			if exists(HOTPLUG_SOCKET):
				remove(HOTPLUG_SOCKET)
		except OSError:
			pass
		factory = Factory()
		factory.protocol = Hotplug
		reactor.listenUNIX(HOTPLUG_SOCKET, factory)


def Plugins(**kwargs):
	return PluginDescriptor(name="Hotplug", description="Hotplug handler.", where=PluginDescriptor.WHERE_AUTOSTART, needsRestart=True, fnc=autostart)

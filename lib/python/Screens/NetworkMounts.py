from os import chmod, makedirs, remove
from os.path import exists
from pickle import dump as pickleDump, load as pickleLoad
from re import sub
from tempfile import NamedTemporaryFile
from uuid import uuid4
from enigma import eTimer, gRGB

from Components.ActionMap import HelpableActionMap
from Components.config import ConfigNumber, ConfigPassword, ConfigSelection, ConfigText, ConfigYesNo, NoSave, config
from Components.Console import Console
from Components.Input import Input
from Components.Label import Label
from Components.NetworkManager import discoveryManager
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Screens.ChoiceBox import ChoiceBox
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen, ScreenSummary
from Screens.Setup import Setup
from Tools.Directories import fileReadLines, fileReadXML, fileWriteLines

MODULE_NAME = __name__.split(".")[-1]


class NetworkMountsOverview(Screen):
	LIST_SHARE_NAME = 0
	LIST_SERVER = 1
	LIST_REMOTE_PATH = 2
	LIST_PROTOCOL = 3
	LIST_MODE = 4
	LIST_MOUNTED = 5
	LIST_ACTIVE = 6
	LIST_DESCRIPTION = 7
	LIST_DATA = 8

	skin = """
	<screen name="NetworkMountsOverview" title="Network Mounts Overview" position="center,center" size="970,465" resolution="1280,720">
		<widget source="mountList" render="Listbox" position="10,10" size="e-20,e-190">
			<templates>
				<template name="Default" fonts="Regular;22,Regular;18" itemHeight="50">
					<mode name="default">
						<text index="ShareName" position="0,0" size="500,28" font="0" padding="5,0" verticalAlignment="center" />
						<text index="Description" position="20,28" size="480,20" font="1" padding="5,0" foregroundColor="=DC-Gray" />
						<text index="Mounted" position="500,0" size="200,50" font="0" padding="5,0" verticalAlignment="center" />
						<text index="Active" position="700,0" size="200,50" font="0" horizontalAlignment="right" padding="5,0" verticalAlignment="center" />
					</mode>
				</template>
			</templates>
		</widget>
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_menu" render="Label" position="e-170,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	MOUNT = "/bin/mount"
	UMOUNT = "/bin/umount"

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Mounts Overview"))
		indexNames = {
			"ShareName": self.LIST_SHARE_NAME,
			"Server": self.LIST_SERVER,
			"RemotePath": self.LIST_REMOTE_PATH,
			"Protocol": self.LIST_PROTOCOL,
			"Mode": self.LIST_MODE,
			"Mounted": self.LIST_MOUNTED,
			"Active": self.LIST_ACTIVE,
			"Description": self.LIST_DESCRIPTION
		}
		self["mountList"] = List([], indexNames=indexNames)
		self["mountList"].onSelectionChanged.append(self.selectionChanged)
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Add"))
		self["key_yellow"] = StaticText(_("Delete"))
		self["key_blue"] = StaticText("")
		self["key_menu"] = StaticText("MENU")
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions", "MenuActions"], {
			"ok": (self.keyEdit, _("Edit the selected network mount")),
			"cancel": (self.close, _("Close the screen")),
			"close": (self.keyCloseRecursive, _("Close the screen and exit all menus")),
			"red": (self.close, _("Close the screen")),
			"green": (self.keyGreen, _("Add a new network mount")),
			"yellow": (self.keyYellow, _("Delete the selected mount definition")),
			"blue": (self.keyBlue, _("Mount or unmount the selected share")),
			"menu": (self.keyMenu, _("Mount actions")),
		}, prio=0, description=_("Network Mount Manager Actions"))
		self.repository = NetworkMountRepository()
		self.console = Console()
		self.onChangedEntry = []
		self.buildList()
		self.onShown.append(self.selectionChanged)
		self.onClose.append(self.console.killAll)

	def selectionChanged(self):
		current = self["mountList"].getCurrent()
		if current:
			shareName = current[self.LIST_SHARE_NAME]
			description = current[self.LIST_DESCRIPTION]
			mount = current[self.LIST_DATA]
			self["key_blue"].setText(_("Unmount") if self.repository.isMounted(mount) else _("Mount"))
		else:
			shareName = ""
			description = ""
			self["key_blue"].setText("")
		for callback in self.onChangedEntry:
			if callable(callback):
				callback(shareName, description)

	def buildList(self):
		# Saved mounts only carry "server" (the address, see keyGreen()), not
		# a hostname - resolve it from discoveryManager's cache if available,
		# same "hostname or address" fallback used elsewhere in this file.
		def hostnameFor(mount):
			server = mount.get("server") or ""
			return discoveryManager.hosts.get(server, {}).get("hostname") or server

		def sortKey(mount):
			if config.network.mountsSortByIP.value:
				server = mount.get("server") or ""
				try:
					key = tuple(int(x) for x in server.split("."))
				except ValueError:
					key = (999, 999, 999, 999)
			else:
				key = hostnameFor(mount).lower()
			return key

		self.mounts = sorted(self.repository.load(), key=sortKey)
		mountList = []
		for mount in self.mounts:
			shareName = mount.get("shareName") or mount.get("id")
			server = mount.get("server", "")
			remotePath = mount.get("remotePath", "")
			protocol = mount.get("protocol", "")
			mode = mount.get("mode", "")
			mounted = f"{_("Mounted") if self.repository.isMounted(mount) else _('Not mounted')}"
			active = f"{_("Enabled") if mount.get("enabled") else _("Disabled")}"
			description = f"{server}/{remotePath}  ({protocol}, {mode})" if server or remotePath else f"({protocol}, {mode})"
			mountList.append((shareName, server, remotePath, protocol, mode, mounted, active, description, mount))
		self["mountList"].setList(mountList)

	def keyEdit(self):
		current = self["mountList"].getCurrent()
		if current:
			self.session.openWithCallback(self.keySetupClosed, NetworkMountSetup, mount=current[self.LIST_DATA])

	def keySetupClosed(self, *args):
		if args and isinstance(args[0], bool) and args[0]:  # Special case for close recursive.
			self.close(True)
			return
		self.buildList()

	# Mounts or unmounts the selected share right now, using whatever is
	# already in /etc/fstab or /etc/auto.network - it does not touch the
	# NetworkMountRepository, so this has no effect on the saved "enabled"
	# state or on what happens at boot.

	def keyBlue(self):
		def onMountResult(unmounting, data, retVal, extra=None):
			action = "umount" if unmounting else "mount"
			print(f"[{MODULE_NAME}] keyBlue: {action} {mountPoint!r} finished, retVal={retVal}, output={data!r}")
			if retVal:
				self.session.showError((_("Unmounting '%s' failed.") if unmounting else _("Mounting '%s' failed.")) % mountPoint)
			else:
				self.session.showInfo((_("'%s' unmounted.") if unmounting else _("'%s' mounted.")) % mountPoint)
			self.buildList()
			self.selectionChanged()

		current = self["mountList"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			mountPoint = self.repository.mountPointFor(mount)
			if self.repository.isMounted(mount):
				print(f"[{MODULE_NAME}] keyBlue: unmounting {mountPoint!r}")
				self.console.ePopen((self.UMOUNT, self.UMOUNT, mountPoint), lambda data, retVal, extra=None: onMountResult(True, data, retVal, extra))
			else:
				if not exists(mountPoint):
					makedirs(mountPoint, exist_ok=True)
				protocol = mount.get("protocol") or "nfs"
				server = mount.get("server") or ""
				remotePath = mount.get("remotePath") or ""
				if protocol == "nfs":
					source = f"{server}:/{remotePath}"
					options = self.repository.buildNfsOptions(mount)
				else:
					username = mount.get("username") or ""
					password = mount.get("password") or ""
					source = f"//{server}/{remotePath}"
					options = f"user={username},pass={password},{self.repository.sanitizeOptions(mount.get('options'))}"
				loggedOptions = sub(r"pass=[^,]*", "pass=***", options)
				print(f"[{MODULE_NAME}] keyBlue: mounting protocol={protocol!r} source={source!r} mountPoint={mountPoint!r} options={loggedOptions!r}")
				self.console.ePopen((self.MOUNT, self.MOUNT, "-t", protocol, source, mountPoint, "-o", options), lambda data, retVal, extra=None: onMountResult(False, data, retVal, extra))

	def keyMenu(self):
		def toggleEnable():
			mount = current[self.LIST_DATA]
			mount["enabled"] = not mount.get("enabled")
			self.repository.save(self.mounts)
			self.buildList()

		def editCredentials():
			mount = current[self.LIST_DATA]
			self.session.open(NetworkCredentials, mount.get("server") or "", self.repository)

		def removeCredentials():
			mount = current[self.LIST_DATA]
			self.repository.credentialsClear(mount.get("server") or "")
			self.session.showInfo(_("Stored credentials deleted for this server."))

		def toggleSort():
			config.network.mountsSortByIP.value = not config.network.mountsSortByIP.value
			config.network.mountsSortByIP.save()
			self.buildList()

		def keyMenuCallback(choice=None):
			if choice:
				if choice[1] == "toggle_enable":
					toggleEnable()
				elif choice[1] == "edit_credentials":
					editCredentials()
				elif choice[1] == "remove_credentials":
					removeCredentials()
				elif choice[1] == "toggle_sort":
					toggleSort()

		current = self["mountList"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			toggleLabel = _("Disable") if mount.get("enabled") else _("Enable")
			sortLabel = _("Sort by Name") if config.network.mountsSortByIP.value else _("Sort by IP Address")
			self.session.openWithCallback(keyMenuCallback, ChoiceBox, title=_("Mount actions"), list=[
				(toggleLabel, "toggle_enable"),
				(_("Edit Credentials"), "edit_credentials"),
				(_("Remove Credentials"), "remove_credentials"),
				(sortLabel, "toggle_sort"),
			])

	def keyGreen(self):
		def keyGreenCallback(picked=None):
			if isinstance(picked, bool) and picked:  # Special case for close recursive.
				self.close(True)
				return
			mount = None
			if picked:
				mount = {
					"server": picked.get("address") or ""
				}
				if picked.get("protocol"):
					mount["protocol"] = picked["protocol"]
				if picked.get("remotePath"):
					mount["remotePath"] = picked["remotePath"]
				if picked.get("shareName"):
					mount["shareName"] = picked["shareName"]
				self.session.openWithCallback(self.keySetupClosed, NetworkMountSetup, mount=mount)

		self.session.openWithCallback(keyGreenCallback, NetworkShares)

	def keyYellow(self):
		def keyYellowCallback(answer):
			if answer:
				self.mounts = [mount for mount in self.mounts if mount is not current[self.LIST_DATA]]
				self.repository.save(self.mounts)
				self.buildList()

		current = self["mountList"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			name = mount.get("shareName") or mount.get("id")
			if self.repository.isMounted(mount):
				self.session.open(MessageBox, _("This mount is currently active. Unmounting is not supported yet - only remove the definition, not the live mount."), MessageBox.TYPE_INFO, timeout=10, windowTitle=self.getTitle())
			else:
				self.session.openWithCallback(keyYellowCallback, MessageBox, _("Do you really want to delete the '%s' network mount?") % name, MessageBox.TYPE_YESNO, default=False, windowTitle=self.getTitle())

	def createSummary(self):
		return NetworkMountsSummary

	def keyCloseRecursive(self):
		self.close(True)


class NetworkMountsSummary(ScreenSummary):
	def __init__(self, session, parent):
		ScreenSummary.__init__(self, session, parent=parent)
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


# Add/edit one network mount definition. Fields are declared in
# data/setup.xml under key "NetworkMounts" and resolved there via self.<name>
# - scratch values that only matter for the duration of this dialog, not
# saved as global config.* entries.
class NetworkMountSetup(Setup):
	def __init__(self, session, mount=None):
		def default(key, default=""):
			return mount.get(key, default) if mount else default

		self.repository = NetworkMountRepository()
		self.mountId = mount.get("id") if mount else None
		self.enabled = NoSave(ConfigYesNo(default=default("enabled", True)))
		self.protocol = NoSave(ConfigSelection(default=default("protocol", "cifs") or "cifs", choices=[
			("cifs", "SMB / CIFS"),
			("nfs", "NFS")
		]))
		self.server = NoSave(ConfigText(default=default("server"), fixed_size=False))
		self.remotePath = NoSave(ConfigText(default=default("remotePath"), fixed_size=False))
		self.mode = NoSave(ConfigSelection(default=default("mode", "autofs") or "autofs", choices=[
			("autofs", _("Mount on first access (autofs)")),
			("fstab", _("Mount at boot time (fstab)"))
		]))
		self.username = NoSave(ConfigText(default=default("username"), fixed_size=False))
		self.password = NoSave(ConfigPassword(default=default("password")))
		self.shareName = NoSave(ConfigText(default=default("shareName"), fixed_size=False))
		self.options = NoSave(ConfigText(default=default("options"), fixed_size=False))
		self.nfsVersion = NoSave(ConfigSelection(default=default("nfsVersion", "auto") or "auto", choices=[
			("auto", _("Automatic")),
			("3", "NFSv3"),
			("4", "NFSv4")
		]))
		self.nfsReadOnly = NoSave(ConfigYesNo(default=default("nfsReadOnly", False)))
		self.nfsLocking = NoSave(ConfigYesNo(default=default("nfsLocking", True)))
		NFS_SIZE_CHOICES = [("0", _("Automatic")), ("8192", "8192"), ("32768", "32768"), ("65536", "65536"), ("131072", "131072")]
		self.nfsRsize = NoSave(ConfigSelection(default=str(default("nfsRsize", "0")) or "0", choices=NFS_SIZE_CHOICES))
		self.nfsWsize = NoSave(ConfigSelection(default=str(default("nfsWsize", "0")) or "0", choices=NFS_SIZE_CHOICES))
		self.nfsTimeo = NoSave(ConfigNumber(default=int(default("nfsTimeo", 0) or 0)))
		self.nfsSoft = NoSave(ConfigYesNo(default=default("nfsSoft", False)))
		self.hddReplacement = NoSave(ConfigYesNo(default=default("hddReplacement", False)))
		Setup.__init__(self, session=session, setup="NetworkMounts")
		self.setTitle(_("Network Mount Settings"))

	def keySave(self):
		server = self.server.value.strip()
		remotePath = self.remotePath.value.strip().lstrip("/")
		if not server or not remotePath:
			self.session.open(MessageBox, _("Error: Both 'server' and 'remote path' are required!"), MessageBox.TYPE_ERROR, timeout=5, windowTitle=self.getTitle())
			return
		options = self.options.value.strip()
		optionsError = self.repository.validateExtraOptions(options, self.protocol.value)
		if optionsError:
			self.session.open(MessageBox, optionsError, MessageBox.TYPE_ERROR, timeout=5, windowTitle=self.getTitle())
			return
		# Used to build the local mount path further down the line, so it
		# must never be empty: use what the user typed, or fall back to a
		# cleaned-up version of the server address.
		shareName = self.shareName.value.strip() or sub(r"\W", "", server)
		mount = {
			"id": self.mountId or self.repository.newId(),
			"enabled": self.enabled.value,
			"shareName": shareName,
			"server": server,
			"remotePath": remotePath,
			"protocol": self.protocol.value,
			"mode": self.mode.value,
			"options": options,
			"username": self.username.value if self.protocol.value == "cifs" else "",
			"password": self.password.value if self.protocol.value == "cifs" else "",
			"nfsVersion": self.nfsVersion.value if self.protocol.value == "nfs" else "",
			"nfsReadOnly": self.nfsReadOnly.value if self.protocol.value == "nfs" else False,
			"nfsLocking": self.nfsLocking.value if self.protocol.value == "nfs" else True,
			"nfsRsize": self.nfsRsize.value if self.protocol.value == "nfs" else "",
			"nfsWsize": self.nfsWsize.value if self.protocol.value == "nfs" else "",
			"nfsTimeo": self.nfsTimeo.value if self.protocol.value == "nfs" else "",
			"nfsSoft": self.nfsSoft.value if self.protocol.value == "nfs" else False,
			"hddReplacement": self.hddReplacement.value,
		}
		mounts = [x for x in self.repository.load() if x.get("id") != mount["id"]]
		mounts.append(mount)
		self.repository.save(mounts)
		Setup.keySave(self)


# Shows discovered network hosts, expandable to list their shares. Host
# discovery runs continuously in the background (Avahi/mDNS and the neighbor
# table). Share enumeration (showmount/smbclient) only happens when a host is
# actually expanded, or via Rescan - never automatically for hosts that are
# just listed, so an idle NAS isn't woken up by browsing this screen.
class NetworkShares(Screen):
	skin = """
	<screen name="NetworkShares" title="Network Shares" position="center,center" size="1080,465" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="1080,370" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;28,Regular;22,Regular;18" itemHeight="50">
				<rowtemplate>
					<text index="Glyph" position="10,0" size="40,50" font="0" horizontalAlignment="center" verticalAlignment="center" />
					<text index="IPAddress" position="60,0" size="220,50" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Name" position="290,0" size="770,50" font="1" horizontalAlignment="left" verticalAlignment="center" />
				</rowtemplate>
				<rowtemplate>
					<text index="Type" position="60,0" size="80,50" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Glyph" position="150,0" size="40,50" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="+GlyphColor" />
					<text index="Name" position="200,2" size="350,28" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Description" position="200,30" size="350,18" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="LocalPath" position="560,0" size="500,50" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
				</rowtemplate>
			</template>
		</widget>
		<eRectangle position="0,373" size="e,1" />
		<widget name="description" position="0,378" size="e,52" font="Regular;20" verticalAlignment="top" horizontalAlignment="left" />
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
		<widget source="key_menu" render="Label" position="e-180,e-40" size="100,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	GLYPH_HOST = "\uEA6D"       # Host icon.
	GLYPH_MOUNTED = "\uE914"     # Green checkmark.
	GLYPH_NOT_MOUNTED = "\uE918"  # Red cross.
	COLOR_MOUNTED = gRGB(0x0000CC00).argb()
	COLOR_NOT_MOUNTED = gRGB(0x00808080).argb()  # Gray, not red - "not configured yet" isn't an error.
	TEMPLATE_HOST = 0
	TEMPLATE_SHARE = 1

	REFRESH_DEBOUNCE_MS = 300  # Coalesce bursts of discovery updates into one list rebuild instead of redrawing on every single one.
	NFS_SHOWMOUNT_BIN = "/usr/sbin/showmount"
	SMB_SMBCLIENT_BIN = "/usr/bin/smbclient"

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Shares"))
		# Index 0 is reserved for the row template selector (which of the two
		# row layouts below to use), not a real data field.
		indexNames = {
			"Reserved_for_rowTemplate": 0,
			"Glyph": 1,       # Host row: host glyph; share row: mounted/not-mounted glyph.
			"GlyphColor": 2,  # Share row only.
			"IPAddress": 3,   # Host row only.
			"Type": 4,        # Share row only: "NFS"/"CIFS".
			"Name": 5,        # Host row: hostname; share row: share name.
			"LocalPath": 6,   # Share row only, when already configured.
			"Description": 7,  # Share row only, e.g. the SMB share comment.
			"Data": 8,
		}
		self["list"] = List([], indexNames=indexNames)
		self["description"] = Label()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Credentials"))
		self["key_yellow"] = StaticText(_("Rescan"))
		self["key_blue"] = StaticText(_("Enter Manually"))
		self["key_menu"] = StaticText(_("MENU"))
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "MenuActions", "ColorActions"], {
			"ok": (self.keySelect, _("Expand/collapse the selected host, or use the selected share")),
			"cancel": (self.close, _("Close the screen")),
			"close": (self.keyCloseRecursive, _("Close the screen and exit all menus")),
			"menu": (self.keyMenu, _("Host actions and sort order")),
			"red": (self.close, _("Close the screen")),
			"green": (self.keyGreen, _("Edit stored username/password for the selected host")),
			"yellow": (self.keyRescan, _("Rescan for available network shares")),
			"blue": (self.keyManual, _("Enter a hostname or IP address manually")),
		}, prio=0, description=_("Network Share Actions"))
		self.expanded = set()
		self.shares = {}         # address -> [share dict, ...]
		self.shareState = {}     # address -> "loading" | "done" | "empty"
		self.pendingProtocols = {}  # address -> {"nfs", "smb"} remaining
		self.configuredShares = {}  # (server, remotePath) -> local mount path, for already-configured shares
		self.repository = NetworkMountRepository()
		self.menuAddress = None
		self.menuHostname = None
		self.console = Console()
		self.refreshTimer = eTimer()
		self.refreshTimer.callback.append(self.buildList)
		self.onShow.append(self.startDiscovery)
		self.onClose.append(self.stopDiscovery)

	# Discovery only runs while this screen is open, so it stops as soon as
	# the user leaves instead of scanning the network in the background.
	def startDiscovery(self):
		self.configuredShares = {(mount.get("server"), (mount.get("remotePath") or "").lstrip("/")): self.repository.mountPointFor(mount) for mount in self.repository.load()}
		discoveryManager.onChanged.append(self.onHostsChanged)
		discoveryManager.start(runMs=None)
		self["description"].setText(_("Scanning..."))
		self.buildList()

	def stopDiscovery(self):
		self.refreshTimer.stop()
		# Guard against removing a callback that was never registered - that
		# would otherwise skip stopping discovery below.
		try:
			discoveryManager.onChanged.remove(self.onHostsChanged)
		except ValueError:
			pass
		discoveryManager.stop()
		self.console.killAll()

	def keyRescan(self):
		discoveryManager.stop()
		discoveryManager.reset()
		self.expanded = set()
		self.shares = {}
		self.shareState = {}
		self.pendingProtocols = {}
		self["description"].setText(_("Scanning..."))
		discoveryManager.start(runMs=None)
		# Explicit callback, not just the normal onChanged -> onHostsChanged
		# flow: that one never fires if the scan found zero hosts, and a
		# failed rescan (e.g. no default-route interface) would otherwise
		# leave the screen stuck on "Scanning...".
		discoveryManager.rescan(self.onRescanDone)
		self.buildList()

	def onRescanDone(self, ok):
		if "list" in self:
			if ok:
				self.buildList()
			else:
				self["description"].setText(_("Rescan failed."))

	def keyManual(self):
		self.session.openWithCallback(self.manualEntered, InputBox, title=_("Enter the host name or IP address of the server:"), text="", maxSize=False, type=Input.TEXT)

	def manualEntered(self, text=None):
		text = (text or "").strip()
		if text:
			self.close({"address": text, "hostname": "", "protocol": None, "remotePath": "", "shareName": ""})

	# Stored credentials are keyed by hostname; fall back to the address if
	# no hostname is known for this host.
	def hostnameFor(self, address):
		host = discoveryManager.hosts.get(address) or {}
		return host.get("hostname") or address

	def keyGreen(self):
		current = self["list"].getCurrent()
		if not current or current[-1].get("kind") != "host":
			return
		self.menuAddress = current[-1]["address"]
		self.menuHostname = self.hostnameFor(self.menuAddress)
		self.session.openWithCallback(self.credentialsClosed, NetworkCredentials, self.menuHostname, self.repository)

	def keyMenu(self):
		current = self["list"].getCurrent()
		isHost = bool(current) and current[-1].get("kind") == "host"
		if isHost:
			self.menuAddress = current[-1]["address"]
			self.menuHostname = self.hostnameFor(self.menuAddress)
		else:
			self.menuAddress = None
			self.menuHostname = None
		choices = []
		if isHost:
			choices.append((_("Edit Username/Password"), "credentials"))
			choices.append((_("Clear Stored Credentials"), "clear_credentials"))
		sortLabel = _("Sort by Name") if config.network.browserSortByIP.value else _("Sort by IP Address")
		choices.append((sortLabel, "toggle_sort"))
		self.session.openWithCallback(self.menuChoiceClosed, ChoiceBox, title=_("Network Share Context Menu"), list=choices)

	def menuChoiceClosed(self, choice=None):
		if not choice:
			return
		if choice[1] == "credentials":
			self.session.openWithCallback(self.credentialsClosed, NetworkCredentials, self.menuHostname, self.repository)
		elif choice[1] == "clear_credentials":
			self.repository.credentialsClear(self.menuHostname)
			self.session.open(MessageBox, _("Stored credentials for this server have been deleted."), MessageBox.TYPE_INFO, timeout=3)
		elif choice[1] == "toggle_sort":
			config.network.browserSortByIP.value = not config.network.browserSortByIP.value
			config.network.browserSortByIP.save()
			self.buildList()

	def credentialsClosed(self, *args):
		# Re-enumerate with the (possibly new) credentials if this host is
		# currently expanded, so the share list picks them up right away.
		if self.menuAddress in self.expanded:
			self.startShareEnumeration(self.menuAddress)

	def keySelect(self):
		current = self["list"].getCurrent()
		if current:
			data = current[-1]
			if data["kind"] == "host":
				self.toggleExpand(data["address"])
			elif data["kind"] == "share":
				self.pickShare(data)

	def keyCloseRecursive(self):
		self.close(True)

	def toggleExpand(self, address):
		if address in self.expanded:
			self.expanded.discard(address)
			self.buildList()
			return
		self.expanded.add(address)
		self.buildList()
		# Many servers refuse or limit anonymous share listing, so without
		# credentials the SMB shares just silently don't show up - ask for
		# them up front instead. Leaving it blank still proceeds anonymously;
		# it just asks again next time since nothing got saved.
		hostname = self.hostnameFor(address)
		if self.repository.credentialsGet(hostname).get("username"):
			self.startShareEnumeration(address)
		else:
			self.session.openWithCallback(lambda *args: self.startShareEnumeration(address), NetworkCredentials, hostname, self.repository)

	def pickShare(self, share):
		host = discoveryManager.hosts.get(share["address"]) or {}

		self.close({
			"address": share["address"],
			"hostname": host.get("hostname") or "",
			"protocol": {
				"smb": "cifs",
				"nfs": "nfs"
			}.get(share["protocol"], share["protocol"]),
			"remotePath": share["path"].lstrip("/"),
			"shareName": share["name"],
		})

	# Share enumeration only ever runs from here, i.e. only when a host is
	# explicitly expanded - never automatically for a host that's merely listed.

	def startShareEnumeration(self, address):
		if self.shareState.get(address) == "loading":
			return
		self.shareState[address] = "loading"
		# Some NAS vendors (e.g. Synology) announce one share per mDNS
		# service instance, so Avahi may already know the share names before
		# showmount/smbclient even run. Show those immediately with an empty
		# path, then mergeShare() fills in the real path once the actual
		# enumeration confirms it. This also covers NFSv4-only servers,
		# where showmount often returns nothing at all.
		host = discoveryManager.hosts.get(address) or {}
		# print(f"[{MODULE_NAME}] DEBUG startShareEnumeration {address} protocols={host.get('protocols')} avahiShares={host.get('avahiShares')}")
		self.shares[address] = [
			{"address": address, "protocol": info["protocol"], "name": info["name"], "path": "", "description": ""}
			for info in (host.get("avahiShares") or {}).values()
		]
		self.pendingProtocols[address] = {"nfs", "smb"}

		if "nfs" in host.get("protocols", set()):
			self.enumerateNfs(address)
		else:
			self.finishProtocol(address, "nfs")
		if "smb" in host.get("protocols", set()):
			self.enumerateSmb(address)
		else:
			self.finishProtocol(address, "smb")

	# Fills a matching Avahi-seeded hint in place instead of adding a
	# duplicate row, or appends a new entry if there's no hint to match.
	def mergeShare(self, address, protocol, name, path, description):
		shares = self.shares.setdefault(address, [])
		for share in shares:
			if share["protocol"] == protocol and not share["path"] and share["name"].lower() == name.lower():
				share["path"] = path
				share["description"] = description or share["description"]
				return
		shares.append({"address": address, "protocol": protocol, "name": name, "path": path, "description": description})

	def enumerateNfs(self, address):
		if not exists(self.NFS_SHOWMOUNT_BIN):
			self.finishProtocol(address, "nfs")
			return
		self.console.ePopen((self.NFS_SHOWMOUNT_BIN, self.NFS_SHOWMOUNT_BIN, "-e", address), callback=lambda data, retVal, extra=None: self.onNfsResult(address, data, retVal))

	def onNfsResult(self, address, data, retVal):
		if "list" in self:
			if retVal == 0 and data:
				for line in data.splitlines()[1:]:
					parts = line.split()
					if not parts:
						continue
					path = parts[0]
					name = path.rsplit("/", 1)[-1] or path
					self.mergeShare(address, "nfs", name, path, "")
			self.finishProtocol(address, "nfs")

	def enumerateSmb(self, address):
		if not exists(self.SMB_SMBCLIENT_BIN):
			self.finishProtocol(address, "smb")
			return
		# Anonymous (-N) unless a real (non-guest) username was stored for
		# this host, in which case a temporary credentials file is used
		# instead (-A) so the password never appears in the process list.
		# The file is removed again in onSmbResult() once the command
		# finishes, either way.
		credentials = self.repository.credentialsGet(self.hostnameFor(address))
		credentialFile = None
		if credentials.get("username") and credentials["username"] != NetworkCredentials.GUEST_USERNAME:
			credentialFile = NamedTemporaryFile(mode="w", prefix="smbcreds-", delete=False)
			credentialFile.write(f"username={credentials['username']}\npassword={credentials.get('password', '')}\n")
			credentialFile.close()
			chmod(credentialFile.name, 0o600)
			authArgs = ("-A", credentialFile.name)
		else:
			authArgs = ("-N",)
		cmd = (self.SMB_SMBCLIENT_BIN, self.SMB_SMBCLIENT_BIN, "-m", "SMB3", "-g", *authArgs, "-L", address)
		credentialPath = credentialFile.name if credentialFile else None
		self.console.ePopen(cmd, callback=lambda data, retVal, extra=None: self.onSmbResult(address, data, retVal, credentialPath))

	def onSmbResult(self, address, data, retVal, credentialPath=None):
		# print(f"[{MODULE_NAME}] DEBUG onSmbResult: {data}")
		# credentialPath is the temporary smbclient credentials file from
		# enumerateSmb() - smbclient is done with it now, so delete it before
		# its plaintext password can linger on disk.
		if credentialPath:
			try:
				remove(credentialPath)
			except OSError:
				pass
		if "list" in self:
			if data:
				for line in data.splitlines():
					parts = line.split("|")
					if len(parts) == 3 and parts[0] == "Disk" and not parts[1].endswith("$"):
						self.mergeShare(address, "smb", parts[1], parts[1], parts[2])
			self.finishProtocol(address, "smb")

	def finishProtocol(self, address, protocol):
		if "list" in self:
			# Some servers announce a single _smb._tcp/_nfs._tcp instance for
			# the whole host rather than one per share - if the Avahi-seeded
			# hint for this protocol never got matched to a real share by
			# mergeShare(), it wasn't a share after all, so drop it instead
			# of leaving a phantom empty-path entry in the list.
			self.shares[address] = [share for share in self.shares.get(address, []) if not (share["protocol"] == protocol and not share["path"])]
			pending = self.pendingProtocols.get(address)
			if pending is not None:
				pending.discard(protocol)
				if not pending:
					self.shareState[address] = "done" if self.shares.get(address) else "empty"
			self.buildList()

	# -- discovery (hosts, not shares) - DiscoveryManager owns the merged
	# host list, this screen just displays it --

	def onHostsChanged(self):
		if "list" in self and not self.refreshTimer.isActive():
			self.refreshTimer.start(self.REFRESH_DEBOUNCE_MS, True)

	def buildList(self):
		if "list" in self:
			entries = []
			protocolLabels = {
				"smb": "SMB",
				"nfs": "NFS"
			}

			def ipKey(address):
				try:
					return tuple(int(x) for x in address.split("."))
				except ValueError:
					return (999, 999, 999, 999)

			def sortKey(host):
				return (not host["protocols"], ipKey(host["address"]) if config.network.browserSortByIP.value else (host["hostname"] or host["address"]).lower())

			for host in sorted(discoveryManager.hosts.values(), key=sortKey):
				address = host["address"]
				name = host["hostname"] or address
				entries.append((self.TEMPLATE_HOST, self.GLYPH_HOST, 0, address, "", name, "", "", {"kind": "host", "address": address}))
				if address not in self.expanded:
					continue
				state = self.shareState.get(address)
				if state == "loading":
					entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("Scanning for shares…"), "", "", {"kind": "status"}))
				elif state == "empty":
					entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("No shares found."), "", "", {"kind": "status"}))

				for share in self.shares.get(address, []):
					typeLabel = protocolLabels.get(share["protocol"], share["protocol"])
					localPath = self.configuredShares.get((address, share["path"].lstrip("/")))
					glyph = self.GLYPH_MOUNTED if localPath else self.GLYPH_NOT_MOUNTED
					glyphColor = self.COLOR_MOUNTED if localPath else self.COLOR_NOT_MOUNTED
					entries.append((self.TEMPLATE_SHARE, glyph, glyphColor, "", typeLabel, share["name"], localPath or "", share.get("description") or "", dict(share, kind="share")))
			self["list"].setList(entries)
			count = len(discoveryManager.hosts)
			self["description"].setText((ngettext("%d host found.", "%d hosts found.", count) % count) if count else _("No hosts found yet - still scanning…"))


# Username/password prompt for one host's share-listing credentials -
# opened from NetworkShares' MENU action. Keyed by hostname; the caller
# falls back to the address if no hostname is known for that host.
class NetworkCredentials(Setup):
	GUEST_USERNAME = "guest"

	def __init__(self, session, hostname, repository):
		self.hostname = hostname
		self.repository = repository
		credentials = repository.credentialsGet(hostname)
		username = credentials.get("username", "")
		self.useGuest = NoSave(ConfigYesNo(default=username == self.GUEST_USERNAME))
		self.username = NoSave(ConfigText(default=username, fixed_size=False))
		self.password = NoSave(ConfigPassword(default=credentials.get("password", "")))
		Setup.__init__(self, session=session, setup="NetworkCredentials")
		self.setTitle(_("Credentials for %s") % hostname)

	def keySave(self):
		# Password is intentionally not stripped - unlike a username, it may
		# legitimately start or end with a space.
		username = self.GUEST_USERNAME if self.useGuest.value else self.username.value.strip()
		password = "" if self.useGuest.value else self.password.value
		self.repository.credentialsSave(self.hostname, username, password)
		Setup.keySave(self)


# The actual system-of-record for network mounts is /etc/fstab and
# /etc/auto.network, both read and written directly by this class.
# automounts.xml (the old plugin's config file) is only read, and only to
# migrate an existing old-plugin setup once - we never write to it.
class NetworkMountRepository:

	READ_MODE_WRAPPERS = ("autofs", "fstab", "enigma2")
	WRITE_MODES = ("autofs", "fstab")
	NORMALIZE_MODE = {
		"enigma2": "fstab",
		"old_enigma2": "fstab"
	}
	PROTOCOLS = ("nfs", "cifs")

	# Off by default, only meant for an explicit migration pass - enabling
	# it can show a mount twice, once from automounts.xml and once from the
	# matching fstab/auto.network entry it was written to. Kept as a flag
	# rather than removed outright since migrating an old-plugin setup still
	# needs it.
	READ_XML = False

	AUTOMOUNTS_PATH = "/etc/enigma2/automounts.xml"
	AUTO_NETWORK_PATH = "/etc/auto.network"
	FSTAB_PATH = "/etc/fstab"

	# A disabled mount is still written to fstab/auto.network, just commented
	# out with this marker, so it survives a reload instead of vanishing -
	# those two files are the only place a mount's definition lives (see
	# above), so simply omitting a disabled entry would delete it for good.
	DISABLED_PREFIX = "#DISABLED# "

	# Username/password are stored in plaintext directly on the entry, same
	# as the old plugin did. Kept reasonably safe by chmod'ing the file 600
	# after every save() (see below).

	def load(self):
		def readMode(node, wrapperMode):
			def readMount(node, wrapperMode, protocol):
				def text(tag, default=""):
					child = node.find(tag)
					return child.text if child is not None and child.text is not None else default

				mode = self.NORMALIZE_MODE.get(wrapperMode, wrapperMode)
				server = text("ip", "192.168.0.0")
				remotePath = text("sharedir", "/media/hdd/" if wrapperMode in ("autofs", "fstab") else "/exports/")
				shareName = text("shareName", "MEDIA")
				mount = {
					# The old format has no <id>/<display_name> field, so a
					# stable id is synthesized here, the same way the
					# fstab/auto.network parsers below do, so edit/delete
					# actions have something stable to key on.
					"id": f"{mode}:{protocol}:{server}:{remotePath}",
					"mode": mode,
					"protocol": protocol,
					"enabled": text("enabled", "False") in ("True", "true", "1"),
					"hddReplacement": text("hdd_replacement", "False") in ("True", "true", "1"),
					"shareName": shareName,
					"server": server,
					"remotePath": remotePath,
					"options": text("options", "rw,nolock,tcp,utf8" if protocol == "nfs" else "rw,utf8"),
					"username": text("username", "guest") if protocol == "cifs" else "",
					"password": text("password") if protocol == "cifs" else "",
					"unmanaged": True,
				}
				return mount

			mounts = []
			for protocol in self.PROTOCOLS:
				for protoNode in node.findall(protocol):
					for mountNode in protoNode.findall("mount"):
						mounts.append(readMount(mountNode, wrapperMode, protocol))
			return mounts

		# automounts.xml isn't necessarily the full story - /etc/fstab and
		# /etc/auto.network may contain NFS/CIFS lines that were never
		# written by us (added manually, or left over from something else).
		# Surface those too instead of hiding them. Their id is derived from
		# the share identity (mode:protocol:server:remotePath) so reloading
		# doesn't keep minting new ones, and they're marked "unmanaged": True
		# so callers can tell them apart - editing and saving one adopts it
		# into automounts.xml going forward, like any other entry.
		def parseFstabLine(line):
			line = line.strip()
			if not line:
				return None
			enabled = True
			if line.startswith(self.DISABLED_PREFIX):
				enabled = False
				line = line[len(self.DISABLED_PREFIX):].strip()
			elif line.startswith("#"):
				return None
			fields = line.split()
			if len(fields) < 4:
				return None
			device, mountpoint, fstype, options = fields[0], fields[1], fields[2], fields[3]
			if fstype in ("nfs", "nfs4") and ":" in device:
				protocol = "nfs"
				server, remotePath = device.split(":", 1)
				remotePath = remotePath.lstrip("/")
			elif fstype == "cifs" and device.startswith("//") and "/" in device[2:]:
				protocol = "cifs"
				server, remotePath = device[2:].split("/", 1)
			else:
				return None
			if not server or not remotePath:
				return None
			shareName = remotePath.rstrip("/").rsplit("/", 1)[-1] or mountpoint.rstrip("/").rsplit("/", 1)[-1] or "MEDIA"
			return {
				"id": f"fstab:{protocol}:{server}:{remotePath}",
				"mode": "fstab",
				"protocol": protocol,
				"enabled": enabled,
				"hddReplacement": mountpoint.rstrip("/") == "/media/hdd",
				"shareName": shareName,
				"server": server,
				"remotePath": remotePath,
				"options": options,
				"username": "",
				"password": "",
				"nfsVersion": "",
				"unmanaged": True
			}

		def parseAutoNetworkLine(line):
			line = line.strip()
			if not line:
				return None
			enabled = True
			if line.startswith(self.DISABLED_PREFIX):
				enabled = False
				line = line[len(self.DISABLED_PREFIX):].strip()
			elif line.startswith("#"):
				return None
			fields = line.split(None, 2)
			if len(fields) < 3 or not fields[1].startswith("-fstype="):
				return None
			shareName, location = fields[0], fields[2]
			typeAndOptions = fields[1][len("-fstype="):].split(",")
			fstype, options = typeAndOptions[0], ",".join(typeAndOptions[1:])
			if fstype == "nfs" and ":" in location:
				protocol = "nfs"
				server, remotePath = location.split(":", 1)
				remotePath = remotePath.lstrip("/")
			elif fstype == "cifs" and location.startswith("://") and "/" in location[3:]:
				protocol = "cifs"
				server, remotePath = location[3:].split("/", 1)
			else:
				return None
			if not server or not remotePath:
				return None
			return {
				"id": f"autofs:{protocol}:{server}:{remotePath}",
				"mode": "autofs",
				"protocol": protocol,
				"enabled": enabled,
				"hddReplacement": False,
				"shareName": shareName,
				"server": server,
				"remotePath": remotePath,
				"options": options,
				"username": "",
				"password": "",
				"nfsVersion": "",
				"unmanaged": True
			}

		def mergeUnmanaged(mounts, path, parseLine):
			known = {(mount["mode"], mount["protocol"], mount["server"], mount["remotePath"].lstrip("/")) for mount in mounts}
			for line in fileReadLines(path, default=[], source=MODULE_NAME):
				extra = parseLine(line)
				if extra is None:
					continue
				key = (extra["mode"], extra["protocol"], extra["server"], extra["remotePath"].lstrip("/"))
				if key not in known:
					mounts.append(extra)
					known.add(key)

		mounts = []
		if self.READ_XML:
			root = fileReadXML(self.AUTOMOUNTS_PATH, default="<mountmanager />", source=MODULE_NAME)
			if root is not None:
				for wrapperMode in self.READ_MODE_WRAPPERS:
					for modeNode in root.findall(wrapperMode):
						mounts += readMode(modeNode, wrapperMode)
				mounts += readMode(root, "old_enigma2")
		mergeUnmanaged(mounts, self.FSTAB_PATH, parseFstabLine)
		mergeUnmanaged(mounts, self.AUTO_NETWORK_PATH, parseAutoNetworkLine)
		return mounts

	def save(self, mounts):
		def writeMountFiles(effective):
			def lineIsManaged(line, separator, nfsShares, cifsShares, cifsColonPrefix):
				if line.startswith(self.DISABLED_PREFIX):
					line = line[len(self.DISABLED_PREFIX):]
				tokens = line.split(separator) if separator else line.split()
				if any(share in tokens for share in nfsShares):
					return True
				if cifsColonPrefix:
					return any((":" + share) in tokens for share in cifsShares)
				return any(share in tokens for share in cifsShares)

			nfsShares = set()
			cifsShares = set()
			for mount, _mode in effective:
				server = mount.get("server") or ""
				remotePath = mount.get("remotePath") or ""
				if (mount.get("protocol") or "nfs") == "nfs":
					nfsShares.add(f"{server}:/{remotePath}")
				else:
					cifsShares.add(f"//{server}/{remotePath}")
			autoNetworkLines = [line for line in fileReadLines(self.AUTO_NETWORK_PATH, default=[], source=MODULE_NAME)
				if not lineIsManaged(line, " ", nfsShares, cifsShares, cifsColonPrefix=True)]
			fstabLines = [line for line in fileReadLines(self.FSTAB_PATH, default=[], source=MODULE_NAME)
				if not lineIsManaged(line, None, nfsShares, cifsShares, cifsColonPrefix=False)]
			for mount, mode in effective:
				prefix = "" if mount.get("enabled") else self.DISABLED_PREFIX
				protocol = mount.get("protocol") or "nfs"
				server = mount.get("server") or ""
				remotePath = mount.get("remotePath") or ""
				shareName = mount.get("shareName") or ""
				options = mount.get("options") or ""
				if mode == "autofs":
					if protocol == "nfs":
						autoNetworkLines.append(f"{prefix}{shareName} -fstype=nfs,{self.buildNfsOptions(mount)} {server}:/{remotePath}")
					else:
						username = (mount.get("username") or "").replace(" ", "\\ ")
						password = (mount.get("password") or "").replace(" ", "\\ ")
						autoNetworkLines.append(f"{prefix}{shareName} -fstype=cifs,user={username},pass={password},{self.sanitizeOptions(options)} ://{server}/{remotePath}")
				elif mode == "fstab":
					path = self.mountPointFor(mount)
					if protocol == "nfs":
						fstabLines.append(f"{prefix}{server}:/{remotePath}\t{path}\tnfs\t_netdev,{self.buildNfsOptions(mount)}\t0 0")
					else:
						username = mount.get("username") or ""
						password = mount.get("password") or ""
						fstabLines.append(f"{prefix}//{server}/{remotePath}\t{path}\tcifs\tuser={username},pass={password},_netdev,{self.sanitizeOptions(options)}\t0 0")
			fileWriteLines(self.AUTO_NETWORK_PATH, autoNetworkLines, source=MODULE_NAME)
			fileWriteLines(self.FSTAB_PATH, fstabLines, source=MODULE_NAME)

		effective = []
		for mount in mounts:
			mode = mount.get("mode")
			if mode not in self.WRITE_MODES:
				mode = "fstab"
			effective.append((mount, mode))
		writeMountFiles(effective)

	# Option keys already covered by a dedicated NetworkMountSetup field (see
	# buildNfsOptions()/sanitizeOptions() and NetworkMountSetup.keySave()) -
	# entering one of these in the free-text "Mount options" field would just
	# be silently overridden by the dedicated setting, so it's rejected
	# instead by validateExtraOptions() below.
	NFS_RESERVED_OPTION_KEYS = frozenset(("ro", "rw", "nolock", "lock", "proto", "nfsvers", "rsize", "wsize", "timeo", "soft", "hard"))
	CIFS_RESERVED_OPTION_KEYS = frozenset(("user", "username", "pass", "password"))

	# Checks the raw "Mount options" free-text field for anything already
	# covered by a dedicated setting, and for options repeated within the
	# field itself. Returns an error message to show the user, or None if the
	# field is fine as-is.
	@classmethod
	def validateExtraOptions(cls, rawOptions, protocol):
		reserved = cls.NFS_RESERVED_OPTION_KEYS if protocol == "nfs" else cls.CIFS_RESERVED_OPTION_KEYS
		seen = set()
		for token in (rawOptions or "").split(","):
			token = token.strip()
			if not token:
				continue
			key = token.split("=", 1)[0].strip().lower()
			if key in reserved:
				return _("'%s' is already set by a dedicated setting above - remove it from 'Mount options'.") % token
			if key in seen:
				return _("'%s' is listed more than once in 'Mount options'.") % token
			seen.add(key)
		return None

	# CIFS options only - NFS is built explicitly by buildNfsOptions() below
	# from structured per-field Setup values rather than a free-text string.
	@staticmethod
	def sanitizeOptions(origOptions):
		options = (origOptions or "").strip()
		options = options.replace("utf8", "iocharset=utf8")
		return options or "rw"

	# Builds the actual mount.nfs/autofs option string from the structured
	# per-mount fields NetworkMountSetup exposes (rw/ro, locking, nfsVersion,
	# rsize, wsize, timeo). proto=tcp is always added - NFS over UDP isn't
	# offered as an option. Anything the user still put in the free-text
	# "options" field is appended last, for anything not covered by a
	# dedicated field.
	def buildNfsOptions(self, mount):
		parts = ["ro" if mount.get("nfsReadOnly") else "rw"]
		# NFSv3 uses normal server-side (NLM) locking unless told otherwise -
		# "nolock" is a legacy opt-in for servers without NLM support, not a
		# default.
		if not mount.get("nfsLocking", True):
			parts.append("nolock")
		parts.append("proto=tcp")
		version = mount.get("nfsVersion") or ""
		if version and version != "auto":
			parts.append(f"nfsvers={version}")
		# 0 means "Automatic": let the kernel/server negotiate a size or
		# timeout themselves, so omit the option entirely instead of forcing
		# a fixed value.
		rsize = mount.get("nfsRsize") or "0"
		if str(rsize) != "0":
			parts.append(f"rsize={rsize}")
		wsize = mount.get("nfsWsize") or "0"
		if str(wsize) != "0":
			parts.append(f"wsize={wsize}")
		timeo = mount.get("nfsTimeo") or 0
		if timeo:
			parts.append(f"timeo={timeo}")
		if mount.get("nfsSoft"):
			parts.append("soft")
		extra = (mount.get("options") or "").strip()
		if extra:
			parts.append(extra)
		return ",".join(parts)

	def newId(self):
		return f"mount-{uuid4().hex[:12]}"

	# autofs mounts always go under /media/autofs/<shareName>; a
	# hddReplacement mount (any other mode) replaces /media/hdd itself;
	# everything else mounts under /media/net/<shareName>.
	def mountPointFor(self, mount):
		shareName = mount.get("shareName") or mount.get("id", "")
		if mount.get("mode") == "autofs":
			return f"/media/autofs/{shareName}"
		if mount.get("hddReplacement"):
			return "/media/hdd"
		return f"/media/net/{shareName}"

	def isMounted(self, mount):
		mountPoint = self.mountPointFor(mount)
		if mount.get("mode") == "autofs":
			return exists(mountPoint)

		try:
			with open("/proc/self/mountinfo") as procFile:
				for line in procFile:
					fields = line.split(" ")
					if len(fields) > 4 and fields[4] == mountPoint:
						return True
		except OSError:
			pass
		return False

	# -- SMB share-enumeration credentials --
	# Separate from a mount's own username/password: these are needed just
	# to LIST a host's shares, before a share has even been picked to mount.
	# Stored the same way the old plugin did - one pickle file per host at
	# /etc/enigma2/<hostname>.cache, so credentials entered via the old
	# plugin still work here. Keyed by hostname, so a host with no known
	# hostname can't use stored credentials at all.

	@staticmethod
	def credentialsPath(hostname):
		return f"/etc/enigma2/{hostname.strip()}.cache"

	def credentialsGet(self, hostname):
		if not hostname:
			return {}
		try:
			with open(self.credentialsPath(hostname), "rb") as fd:
				data = pickleLoad(fd)
		except Exception:
			return {}
		if not isinstance(data, dict):
			return {}
		username = data.get("username", "")
		password = data.get("password", "")
		return {"username": username, "password": password} if username or password else {}

	def credentialsSave(self, hostname, username, password):
		if not hostname:
			return
		path = self.credentialsPath(hostname)
		try:
			with open(path, "wb") as fd:
				pickleDump({"username": username, "password": password}, fd, -1)
			chmod(path, 0o600)  # contains a plaintext password
		except OSError as err:
			print(f"[{MODULE_NAME}] Error {err.errno}: Error writing '{path}'!  ({err.strerror})")

	def credentialsClear(self, hostname):
		if not hostname:
			return
		try:
			remove(self.credentialsPath(hostname))
		except OSError:
			pass

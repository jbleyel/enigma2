from os import chmod, remove
from os.path import exists
from pickle import dump as pickleDump, load as pickleLoad
from re import sub
from tempfile import NamedTemporaryFile
from uuid import uuid4
from enigma import eTimer, gRGB

from Components.ActionMap import HelpableActionMap
from Components.config import ConfigNumber, ConfigPassword, ConfigSelection, ConfigText, ConfigYesNo, NoSave
from Components.Console import Console
from Components.Input import Input
from Components.Label import Label
from Components.NetworkManager import discoveryManager
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Screens.ChoiceBox import ChoiceBox
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
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
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

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
		self["key_green"] = StaticText(_("Toggle Active"))
		self["key_yellow"] = StaticText(_("Add"))
		self["key_blue"] = StaticText(_("Delete"))
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"ok": (self.keyEdit, _("Edit the selected network mount")),
			"cancel": (self.close, _("Close the Network Mount Manager screen")),
			"red": (self.close, _("Close the Network Mount Manager screen")),
			"green": (self.keyToggleActive, _("Toggle the selected mount between active and inactive")),
			"yellow": (self.keyAdd, _("Add a new network mount")),
			"blue": (self.keyDelete, _("Delete the selected mount definition")),
		}, prio=0, description=_("Network Mount Manager Actions"))
		self.repository = NetworkMountRepository()
		self.onChangedEntry = []
		self.buildList()
		self.onShown.append(self.selectionChanged)

	def selectionChanged(self):
		current = self["mountList"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			shareName = current[self.LIST_SHARE_NAME]
			description = current[self.LIST_DESCRIPTION]
		else:
			shareName = ""
			description = ""
		for callback in self.onChangedEntry:
			if callable(callback):
				callback(shareName, description)

	def buildList(self):
		self.mounts = self.repository.load()
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
		self.buildList()

	def keyToggleActive(self):
		current = self["mountList"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			mount["enabled"] = not mount.get("enabled")
			self.repository.save(self.mounts)
			self.buildList()

	def keyAdd(self):
		def keyAddCallback(picked=None):
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

		self.session.openWithCallback(keyAddCallback, NetworkShares)

	def keyDelete(self):
		def keyDeleteCallback(answer):
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
				self.session.openWithCallback(keyDeleteCallback, MessageBox, _("Do you really want to delete the '%s' network mount?") % name, MessageBox.TYPE_YESNO, default=False, windowTitle=self.getTitle())

	def createSummary(self):
		return NetworkMountsSummary


class NetworkMountsSummary(Screen):
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


class NetworkMountSetup(Setup):
	"""Add/edit one network mount definition. Fields are declared in
	data/setup.xml under key "NetworkMountSetup" and resolved there via
	self.<name> and not global config.* entries. These are scratch values
	that only matter for the duration of this dialog."""

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
			("autofs", _("Autofs (mount on first access)")),
			("fstab", _("fstab (mount at boot)"))
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
			self.session.open(MessageBox, _("Server and remote path are required."), MessageBox.TYPE_ERROR, timeout=5, windowTitle=self.getTitle())
			return
		# Stable local key: explicit (Expert field) if set, else derived from
		# the server - never left empty, it's used to build the local mount
		# path (see NetworkMountRepository.mountPointFor()).
		shareName = self.shareName.value.strip() or sub(r"\W", "", server)
		mount = {
			"id": self.mountId or self.repository.newId(),
			"enabled": self.enabled.value,
			"shareName": shareName,
			"server": server,
			"remotePath": remotePath,
			"protocol": self.protocol.value,
			"mode": self.mode.value,
			"options": self.options.value.strip(),
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


class NetworkShares(Screen):
	"""Host list with shares nested underneath, expand/collapse per host.
	Same tree shape as the old plugin's NetworkBrowser.py screen, rebuilt
	completely from scratch.
	Host discovery comes from the real discoveryManager (Avahi +
	neighbor-table observations, see Components/NetworkManager.py)
	instead of netscan/nmblookup. Share enumeration runs async via Console
	(showmount/smbclient) instead of the old code's blocking
	subprocess.Popen().communicate() call in the GUI thread. The
	list/action/skin structure follows NetworkWiFiScanScreen
	(Screens/NetworkSetup.py) - List/indexNames, HelpableActionMap,
	Red/Green/Yellow/Blue keys, onShow starts the scan.
	Two <rowtemplate>s (see NetworkOverview in NetworkSetup.py for the same
	multi-template/"_rowTemplate" selector pattern) - no pixmap icons, only
	enigma2icons glyphs, same convention as the rest of NetworkSetup.py:
	host rows show a glyph, then IP and name; share rows show the protocol
	as text, a mounted/not-mounted glyph, the share name, and - once
	already configured - its local automounts.xml path.
	Standby-safety (doc section 6.1): share enumeration only runs when a
	host is explicitly expanded (OK/Green on a host row) or re-expanded via
	Rescan - never automatically for hosts that are merely listed."""

	skin = """
	<screen name="NetworkShares" title="Network Shares" position="center,center" size="1080,465" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="1080,370" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;28,Regular;22,Regular;18" itemHeight="44">
				<rowtemplate>
					<text index="Glyph" position="10,0" size="40,44" font="0" horizontalAlignment="center" verticalAlignment="center" />
					<text index="IPAddress" position="60,0" size="220,44" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Name" position="290,0" size="770,44" font="1" horizontalAlignment="left" verticalAlignment="center" />
				</rowtemplate>
				<rowtemplate>
					<text index="Type" position="60,0" size="80,44" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Glyph" position="150,0" size="40,44" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="+GlyphColor" />
					<text index="Name" position="200,0" size="350,44" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="LocalPath" position="560,0" size="500,44" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
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

	GLYPH_HOST = "\uEA6D"  # Host.
	GLYPH_MOUNTED = "\uE914"  # Check_circle - same glyph/meaning as NetworkSetup.py's STATE_OK.
	GLYPH_NOT_MOUNTED = "\uE918"  # Cancel - same glyph/meaning as NetworkSetup.py's STATE_FAIL.
	COLOR_MOUNTED = gRGB(0x0000CC00).argb()  # Green, matches NetworkSetup.py's STATE_OK.
	COLOR_NOT_MOUNTED = gRGB(0x00808080).argb()  # Gray - "not configured yet" isn't an error.
	TEMPLATE_HOST = 0
	TEMPLATE_SHARE = 1

	# Avahi's "smb"/"nfs" (see AVAHI_SERVICE_TYPES) vs. the mount protocol
	# values NetworkMountSetup actually uses ("cifs"/"nfs") - shares found
	# via enumeration are tagged "nfs"/"smb" the same way, mapped once here.
	REFRESH_DEBOUNCE_MS = 300  # coalesce bursts of observations (esp. Avahi resending its full snapshot) into one list rebuild
	NFS_SHOWMOUNT_BIN = "/usr/sbin/showmount"
	SMB_SMBCLIENT_BIN = "/usr/bin/smbclient"

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Shares"))
		# Position 0 is data[0], the <rowtemplate> selector (see TEMPLATE_* /
		# elistboxcontent.cpp's selectTemplate(), same convention as
		# NetworkOverview.ADAPTER_INDEX_NAMES in NetworkSetup.py) - reserved
		# here (not a real field) so indexNames stays contiguous from 0.
		indexNames = {
			"Reserved_for_rowTemplate": 0,
			"Glyph": 1,       # Host row: host glyph; share row: mounted/not-mounted glyph.
			"GlyphColor": 2,  # Share row only.
			"IPAddress": 3,   # Host row only.
			"Type": 4,        # Share row only: "NFS"/"CIFS".
			"Name": 5,        # Host row: hostname; share row: share name.
			"LocalPath": 6,   # Share row only, when already configured.
			"Data": 7,
		}
		self["list"] = List([], indexNames=indexNames)
		self["description"] = Label()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Select"))
		self["key_yellow"] = StaticText(_("Rescan"))
		self["key_blue"] = StaticText(_("Enter Manually"))
		self["key_menu"] = StaticText(_("MENU"))
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "MenuActions", "ColorActions"], {
			"ok": (self.keySelect, _("Expand/collapse the selected host, or use the selected share")),
			"cancel": (self.keyClose, _("Close")),
			"menu": (self.keyMenu, _("Host actions - edit or clear stored credentials")),
			"red": (self.keyClose, _("Close")),
			"green": (self.keySelect, _("Expand/collapse the selected host, or use the selected share")),
			"yellow": (self.keyRescan, _("Restart discovery")),
			"blue": (self.keyManual, _("Enter a hostname or IP address manually")),
		}, prio=0, description=_("Network Share Discovery Actions"))
		self.expanded = set()
		self.shares = {}         # address -> [share dict, ...]
		self.shareState = {}     # address -> "loading" | "done" | "empty"
		self.pendingProtocols = {}  # address -> {"nfs", "smb"} remaining
		self.configuredShares = {}  # (server, remotePath) -> local mount path, for already-configured shares
		self.repository = NetworkMountRepository()
		self.legacyHostnames = {}  # address -> hostname, from the old plugin's networkbrowser.cache (see startDiscovery())
		self.menuAddress = None
		self.menuHostname = None
		self.console = Console()
		self.closed = False
		self.refreshTimer = eTimer()
		self.refreshTimer.callback.append(self.rebuildList)
		self.onShow.append(self.startDiscovery)
		self.onClose.append(self.stopDiscovery)

	# Runs discovery only while this screen is open (standby-safety rule,
	# see doc section 3.2/6.1 - passive host discovery is fine to run
	# continuously, but nothing here should linger once the user leaves).
	# runMs=None requests an unbounded live scan, overriding the bounded
	# once-per-boot pass DiscoveryManager may already be running.
	def startDiscovery(self):
		self.configuredShares = {(mount.get("server"), (mount.get("remotePath") or "").lstrip("/")): self.repository.mountPointFor(mount) for mount in self.repository.load()}
		# Hostname hint only, for hosts already found live this run (see
		# rebuildList()) - not injected as new rows, they may be stale/
		# offline by now.
		self.legacyHostnames = {host["address"]: host["hostname"] for host in self.repository.legacyDiscoveredHosts() if host["hostname"]}
		discoveryManager.onChanged.append(self.onHostsChanged)
		discoveryManager.start(runMs=None)
		self["description"].setText(_("Scanning…"))
		self.rebuildList()

	def stopDiscovery(self):
		self.closed = True
		self.refreshTimer.stop()
		# .remove() raises ValueError if this instance's onChanged callback
		# was never registered (e.g. discoveryClosed() ran before onShow
		# ever fired) - must not skip stop()/killAll() below because of that.
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
		self["description"].setText(_("Scanning…"))
		discoveryManager.start(runMs=None)
		self.rebuildList()

	def keyManual(self):
		self.session.openWithCallback(self.manualEntered, InputBox, title=_("Enter a hostname or IP address"), text="", maxSize=False, type=Input.TEXT)

	def manualEntered(self, text=None):
		text = (text or "").strip()
		if text:
			self.close({"address": text, "hostname": "", "protocol": None, "remotePath": "", "shareName": ""})

	# Credentials (NetworkMountRepository.credentialsGet() et al) are keyed
	# by hostname, same as the old plugin - falls back to the address when
	# no hostname is known for this host (live-discovered or from the old
	# plugin's networkbrowser.cache, see startDiscovery()).
	def hostnameFor(self, address):
		host = discoveryManager.hosts.get(address) or {}
		return host.get("hostname") or self.legacyHostnames.get(address, "") or address

	def keyMenu(self):
		current = self["list"].getCurrent()
		if not current or current[-1].get("kind") != "host":
			return
		self.menuAddress = current[-1]["address"]
		self.menuHostname = self.hostnameFor(self.menuAddress)
		self.session.openWithCallback(self.menuChoiceClosed, ChoiceBox, title=_("Host actions"), list=[
			(_("Edit Username/Password"), "credentials"),
			(_("Clear Stored Credentials"), "clear_credentials"),
		])

	def menuChoiceClosed(self, choice=None):
		if not choice:
			return
		if choice[1] == "credentials":
			self.session.openWithCallback(self.credentialsClosed, NetworkCredentials, self.menuHostname, self.repository)
		elif choice[1] == "clear_credentials":
			self.repository.credentialsClear(self.menuHostname)
			self.session.open(MessageBox, _("Stored credentials deleted for this server."), MessageBox.TYPE_INFO, timeout=3)

	def credentialsClosed(self, *args):
		# Re-enumerate with the (possibly new) credentials if this host is
		# currently expanded, so the share list picks them up right away.
		if self.menuAddress in self.expanded:
			self.startShareEnumeration(self.menuAddress)

	def keySelect(self):
		current = self["list"].getCurrent()
		if not current:
			return
		data = current[-1]
		if data["kind"] == "host":
			self.toggleExpand(data["address"])
		elif data["kind"] == "share":
			self.pickShare(data)

	def keyClose(self):
		self.close(None)

	def toggleExpand(self, address):
		if address in self.expanded:
			self.expanded.discard(address)
			self.rebuildList()
			return
		self.expanded.add(address)
		self.rebuildList()
		# Anonymous smbclient -L is often refused/limited by real servers,
		# so without credentials the SMB shares just silently don't show up
		# - ask up front on first expand instead, same as the old plugin's
		# UserDialog on the first attempt. Leaving it blank still proceeds
		# (anonymous), it just asks again next time since nothing got saved.
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

	# -- share enumeration (only reached via explicit expand, see toggleExpand) --

	def startShareEnumeration(self, address):
		if self.shareState.get(address) == "loading":
			return
		self.shareState[address] = "loading"
		# Seed with whatever Avahi already told us before showmount/smbclient
		# even ran - some NAS vendors (confirmed: Synology) register one
		# mDNS service instance per export/share, not per host, so the share
		# name is already known at discovery time (see DiscoveryManager.
		# parseAvahiShareName() in Components/NetworkManager.py). Shown
		# immediately with an empty path, then mergeShare() below fills in
		# the real path once/if the actual enumeration confirms it - this
		# also covers NFSv4-only servers where showmount often returns
		# nothing at all (doc section 6.3 "enumeration_unsupported").
		host = discoveryManager.hosts.get(address) or {}
		self.shares[address] = [
			{"address": address, "protocol": info["protocol"], "name": info["name"], "path": "", "description": ""}
			for info in (host.get("avahiShares") or {}).values()
		]
		self.pendingProtocols[address] = {"nfs", "smb"}
		self.enumerateNfs(address)
		self.enumerateSmb(address)

	# Merges one confirmed share into self.shares[address]: updates a
	# matching Avahi-seeded hint (same protocol/name, no path yet) in place
	# instead of appending a duplicate row, else appends a new entry.
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
		if getattr(self, "closed", True):
			return
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
		# Anonymous (-N) unless credentials were stored for this host (see
		# NetworkMountRepository.credentialsGet()/keyMenu) - then use -A
		# <credential-file>, per doc section 6.2: never the password in argv
		# or via stdin, both leak it (argv: visible in the process list; a
		# second stdin codepath is its own risk). File is written 0600 and
		# removed again in onSmbResult() once the command has finished
		# either way.
		credentials = self.repository.credentialsGet(self.hostnameFor(address))
		credentialFile = None
		if credentials.get("username"):
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
		if credentialPath:
			try:
				remove(credentialPath)
			except OSError:
				pass
		if getattr(self, "closed", True):
			return
		if data:
			for line in data.splitlines():
				parts = line.split("|")
				if len(parts) == 3 and parts[0] == "Disk" and not parts[1].endswith("$"):
					self.mergeShare(address, "smb", parts[1], parts[1], parts[2])
		self.finishProtocol(address, "smb")

	def finishProtocol(self, address, protocol):
		if getattr(self, "closed", True):
			return
		pending = self.pendingProtocols.get(address)
		if pending is not None:
			pending.discard(protocol)
			if not pending:
				self.shareState[address] = "done" if self.shares.get(address) else "empty"
		self.rebuildList()

	# -- discovery (hosts, not shares - DiscoveryManager owns the merged
	# host array; this screen just displays it, see discoveryManager.hosts) --

	def onHostsChanged(self):
		# Defends against a stale registration outliving this screen (see
		# stopDiscovery()'s comment): Screen teardown can clear this
		# instance's __dict__ entirely, so even "self.closed" would itself
		# raise AttributeError - getattr's default sidesteps that.
		if getattr(self, "closed", True):
			return
		if not self.refreshTimer.isActive():
			self.refreshTimer.start(self.REFRESH_DEBOUNCE_MS, True)

	def rebuildList(self):
		if getattr(self, "closed", True):
			return
		entries = []
		protocolLabels = {
			"smb": "SMB",
			"nfs": "NFS"
		}

		for host in sorted(discoveryManager.hosts.values(), key=lambda h: (not h["protocols"], h["hostname"] or h["address"])):
			address = host["address"]
			name = host["hostname"] or self.legacyHostnames.get(address, "") or address
			entries.append((self.TEMPLATE_HOST, self.GLYPH_HOST, 0, address, "", name, "", {"kind": "host", "address": address}))
			if address not in self.expanded:
				continue
			state = self.shareState.get(address)
			if state == "loading":
				entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("Scanning for shares…"), "", {"kind": "status"}))
			elif state == "empty":
				entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("No shares found."), "", {"kind": "status"}))

			for share in self.shares.get(address, []):
				typeLabel = protocolLabels.get(share["protocol"], share["protocol"])
				localPath = self.configuredShares.get((address, share["path"].lstrip("/")))
				glyph = self.GLYPH_MOUNTED if localPath else self.GLYPH_NOT_MOUNTED
				glyphColor = self.COLOR_MOUNTED if localPath else self.COLOR_NOT_MOUNTED
				entries.append((self.TEMPLATE_SHARE, glyph, glyphColor, "", typeLabel, share["name"], localPath or "", dict(share, kind="share")))
		self["list"].setList(entries)
		count = len(discoveryManager.hosts)
		self["description"].setText((ngettext("%d host found.", "%d hosts found.", count) % count) if count else _("No hosts found yet - still scanning…"))


class NetworkCredentials(Setup):
	"""Small standalone Setup screen (username/password, same ConfigText/
	ConfigPassword + virtual-keyboard editing NetworkMountSetup already gets
	for free from Setup) for one host's share-enumeration credentials (see
	NetworkMountRepository.credentialsGet()/credentialsSave()) - opened from
	NetworkShares's MENU action on a host row. Keyed by
	hostname, same as the old plugin's UserDialog - the caller resolves
	that (falling back to the address if no hostname is known, see
	NetworkShares.hostnameFor())."""

	def __init__(self, session, hostname, repository):
		self.hostname = hostname
		self.repository = repository
		credentials = repository.credentialsGet(hostname)
		self.username = NoSave(ConfigText(default=credentials.get("username", ""), fixed_size=False))
		self.password = NoSave(ConfigPassword(default=credentials.get("password", "")))
		Setup.__init__(self, session=session, setup="NetworkCredentials")
		self.setTitle(_("Credentials for %s") % hostname)

	def keySave(self):
		self.repository.credentialsSave(self.hostname, self.username.value.strip(), self.password.value)  # IS: Shouldn't the password also be stripped?
		Setup.keySave(self)


class NetworkMountRepository:
	"""Reads /etc/enigma2/automounts.xml - the exact XML format the old
	NetworkBrowser plugin's AutoMount.py used (root <mountmanager>, 4
	"mountusing" modes: autofs/fstab/enigma2 as <mountmanager><MODE><nfs|
	cifs><mount>..., old_enigma2 as bare <nfs|cifs><mount> directly under
	<mountmanager>). Read-only, and only for one-time migration of an
	existing old-plugin config - we never write our own extended schema
	into this file (nothing reads automounts.xml but us, and fstab/
	auto.network, which this class also reads/writes directly, are the
	actual system-of-record now). Only the fields the old plugin actually
	wrote are parsed; no invented <id>/<display_name>/<nfs_*> elements."""

	READ_MODE_WRAPPERS = ("autofs", "fstab", "enigma2")
	WRITE_MODES = ("autofs", "fstab")
	NORMALIZE_MODE = {
		"enigma2": "fstab",
		"old_enigma2": "fstab"
	}
	PROTOCOLS = ("nfs", "cifs")

	# Off by default - see class docstring, only meant for an explicit
	# migration pass. mount() shown twice was READ_XML merging an
	# automounts.xml entry with its own fstab/auto.network-derived
	# duplicate; kept as a flag rather than deleting the read path outright
	# since migrating an existing old-plugin config still needs it.
	READ_XML = False

	AUTOMOUNTS_PATH = "/etc/enigma2/automounts.xml"
	AUTO_NETWORK_PATH = "/etc/auto.network"
	FSTAB_PATH = "/etc/fstab"

	# Plaintext username/password directly on the entry for now - same
	# approach the old plugin used, until a real credential-profile store
	# (doc section 9) exists to upgrade to. Kept safe the same way: the file
	# is chmod 600 after every save(), see below.

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
					# No <id>/<display_name> in the old format - synthesize a
					# stable id the same way the fstab/auto.network parsers
					# below do, for the same reason (edit/delete identity).
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
		# written by us (manually added, or left over from something else).
		# Surface those too instead of silently hiding them, same idea as
		# the "unmanaged" mounts from /proc/self/mountinfo in doc section
		# 13.2. Synthesized entries get a stable id derived from their
		# share identity (mode:protocol:server:remotePath) so re-loading
		# doesn't keep minting new ones, and "unmanaged": True so callers
		# can tell them apart from automounts.xml-tracked entries - editing
		# and saving one adopts it into automounts.xml going forward, same
		# as any other entry once it's in the returned list.
		def parseFstabLine(line):
			line = line.strip()
			if not line or line.startswith("#"):
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
				"enabled": True,
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
			if not line or line.startswith("#"):
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
				"enabled": True,
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
				if not mount.get("enabled"):
					continue
				protocol = mount.get("protocol") or "nfs"
				server = mount.get("server") or ""
				remotePath = mount.get("remotePath") or ""
				shareName = mount.get("shareName") or ""
				options = mount.get("options") or ""
				if mode == "autofs":
					if protocol == "nfs":
						autoNetworkLines.append(f"{shareName} -fstype=nfs,{self.buildNfsOptions(mount)} {server}:/{remotePath}")
					else:
						username = (mount.get("username") or "").replace(" ", "\\ ")
						password = (mount.get("password") or "").replace(" ", "\\ ")
						autoNetworkLines.append(f"{shareName} -fstype=cifs,user={username},pass={password},{self.sanitizeOptions(options)} ://{server}/{remotePath}")
				elif mode == "fstab":
					path = self.mountPointFor(mount)
					if protocol == "nfs":
						fstabLines.append(f"{server}:/{remotePath}\t{path}\tnfs\t_netdev,{self.buildNfsOptions(mount)}\t0 0")
					else:
						username = mount.get("username") or ""
						password = mount.get("password") or ""
						fstabLines.append(f"//{server}/{remotePath}\t{path}\tcifs\tuser={username},pass={password},_netdev,{self.sanitizeOptions(options)}\t0 0")
			fileWriteLines(self.AUTO_NETWORK_PATH, autoNetworkLines, source=MODULE_NAME)
			fileWriteLines(self.FSTAB_PATH, fstabLines, source=MODULE_NAME)

		effective = []
		for mount in mounts:
			mode = mount.get("mode")
			if mode not in self.WRITE_MODES:
				mode = "fstab"
			effective.append((mount, mode))
		writeMountFiles(effective)

	# CIFS-only (NFS is built explicitly by buildNfsOptions() below, from
	# structured per-field Setup values instead of free-text string
	# mangling) - direct/enigma2 mode no longer exists (autofs/fstab are
	# the only write modes, see WRITE_MODES), so unlike the old plugin's
	# sanitizeOptions() there is no separate "direct mount" branch to keep:
	# CIFS behaves the same for both autofs and fstab.
	@staticmethod
	def sanitizeOptions(origOptions):
		options = (origOptions or "").strip()
		options = options.replace("utf8", "iocharset=utf8")
		return options or "rw"

	# Builds the actual `mount.nfs`/autofs option string from the
	# structured per-mount fields NetworkMountSetup exposes (rw/ro, nolock,
	# nfsvers via nfsVersion, rsize, wsize, timeo, soft) instead of the old
	# plugin's approach of pattern-matching/augmenting a free-text string.
	# proto=tcp is always added (matches old plugin default, NFS over UDP
	# isn't offered as an option). The free-text "options" field, if the
	# user still put anything in it, is appended last for anything not
	# covered by a dedicated field.
	def buildNfsOptions(self, mount):
		parts = ["ro" if mount.get("nfsReadOnly") else "rw"]
		# NFSv3 uses normal server-side (NLM) locking unless told otherwise -
		# "nolock" is a deliberate legacy opt-in for servers without NLM, not
		# a default (see .claude/NETWORK_MOUNT_SETUP_NOTES.md section 1).
		# Named/defaulted the "positive" way (locking ON by default) to match
		# the Setup field's "Use NFS file locking" label - the old
		# "nfsNoLock" name meant True displayed as "Yes" while actually
		# adding nolock (locking OFF), backwards from what the label said.
		if not mount.get("nfsLocking", True):
			parts.append("nolock")
		parts.append("proto=tcp")
		version = mount.get("nfsVersion") or ""
		if version and version != "auto":
			parts.append(f"nfsvers={version}")
		# 0 means "Automatic" - the kernel/server negotiate a size resp.
		# use their own default timeout, so it's omitted from the string
		# entirely rather than forcing a fixed value (see
		# .claude/NETWORK_MOUNT_SETUP_NOTES.md section 1/3).
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

	# Matches the old plugin's CheckMountPoint()/CheckMountPointFinished()
	# path convention exactly, since that's what actually ends up mounted
	# once mount execution is built (doc section 11): autofs always mounts
	# under /media/autofs/<shareName>; hdd_replacement mounts (any other
	# mode) replace /media/hdd itself; everything else mounts under
	# /media/net/<shareName>.
	def mountPointFor(self, mount):
		shareName = mount.get("shareName") or mount.get("id", "")
		if mount.get("mode") == "autofs":
			return f"/media/autofs/{shareName}"
		if mount.get("hddReplacement"):
			return "/media/hdd"
		return f"/media/net/{shareName}"

	def isMounted(self, mount):
		mountPoint = self.mountPointFor(mount)
		try:
			with open("/proc/self/mountinfo") as procFile:
				for line in procFile:
					fields = line.split(" ")
					if len(fields) > 4 and fields[4] == mountPoint:
						return True
		except OSError:
			pass
		return False

	# -- SMB share-enumeration credentials (NetworkShares) --
	# Separate from a mount's own username/password (used by the actual
	# mount command, see NetworkMountSetup) - you need these to be able to
	# LIST a host's shares before you've even picked one to mount. Exactly
	# the old plugin's own storage (NetworkBrowser/UserDialog.py): one
	# pickle file per host at /etc/enigma2/<hostname>.cache, {"username":
	# ..., "password": ...} - no separate new store, so credentials entered
	# via the old plugin already work here, and vice versa. Deliberately
	# still pickle, not converted - these files are written/read on this
	# same box, same trust boundary as the rest of /etc/enigma2, not
	# untrusted input. Keyed by hostname like the old plugin, so callers
	# without a resolved hostname for a host can't use this at all - same
	# limitation the old plugin had.

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
			print(f"[{MODULE_NAME}] Error writing '{path}': {err}")

	def credentialsClear(self, hostname):
		if not hostname:
			return
		try:
			remove(self.credentialsPath(hostname))
		except OSError:
			pass

	# Old plugin's cached nmap scan results (NetworkBrowser.py's
	# networkbrowser.cache, pickled list of ["host", hostname, ip, mac]) -
	# read-only migration aid, same spirit as the credentials above: don't
	# throw away hostnames the old plugin already knew just because the new
	# discovery pipeline (Avahi/neighbor-table/port-probe) hasn't announced
	# them yet this run. Consumer decides how to use these (see
	# NetworkShares: used as a display-name hint for hosts
	# already found live, not to inject possibly-stale/offline hosts as new
	# rows outright).
	NETWORKBROWSER_CACHE_PATH = "/etc/enigma2/networkbrowser.cache"

	def legacyDiscoveredHosts(self):
		try:
			with open(self.NETWORKBROWSER_CACHE_PATH, "rb") as fd:
				data = pickleLoad(fd)
		except Exception:
			return []
		hosts = []
		for entry in data if isinstance(data, list) else []:
			if not isinstance(entry, (list, tuple)) or len(entry) < 4 or entry[0] != "host":
				continue
			hostname, address = entry[1], entry[2]
			if not address:
				continue
			hosts.append({"address": address, "hostname": "" if hostname == address else hostname})
		return hosts

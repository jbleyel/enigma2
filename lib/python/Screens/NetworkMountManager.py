from os import chmod
from os.path import exists
from re import sub
from uuid import uuid4
from xml.etree.ElementTree import Element, ElementTree, SubElement

from enigma import eTimer, gRGB

from Components.ActionMap import HelpableActionMap
from Components.config import ConfigPassword, ConfigSelection, ConfigText, ConfigYesNo, NoSave
from Components.Console import Console
from Components.Input import Input
from Components.Label import Label
from Components.NetworkManager import discoveryManager
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Directories import fileReadLines, fileReadXML, fileWriteLines

MODULE_NAME = __name__.split(".")[-1]


class NetworkMountRepository:
	"""Reads/writes /etc/enigma2/automounts.xml - the same file and XML
	format the old NetworkBrowser plugin's AutoMount.py used, so mounts it
	configured keep working here and vice versa. The old format has 4
	"mountusing" modes (root element is <mountmanager>):
	- autofs / fstab / enigma2: <mountmanager><MODE><nfs|cifs><mount>...
	- old_enigma2: bare <nfs|cifs><mount> directly under <mountmanager>,
	only written by very old plugin versions.
	Going forward only autofs and fstab are real, selectable modes here -
	enigma2 and old_enigma2 entries are read fine for compatibility but
	normalized to "fstab" on load, and never written back out as their own
	wrapper again (save() only ever emits <autofs>/<fstab>).
	Two elements not in the old format (<id>, <display_name>, and
	<nfs_version> for nfs mounts) are written into each <mount> for our own
	use; old parsers just ignore unknown child elements, so this stays
	compatible both ways."""

	READ_MODE_WRAPPERS = ("autofs", "fstab", "enigma2")
	WRITE_MODES = ("autofs", "fstab")
	NORMALIZE_MODE = {"enigma2": "fstab", "old_enigma2": "fstab"}
	PROTOCOLS = ("nfs", "cifs")

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

				sharename = text("sharename", "MEDIA")
				mode = self.NORMALIZE_MODE.get(wrapperMode, wrapperMode)
				defaultDir = "/media/hdd/" if wrapperMode in ("autofs", "fstab") else "/exports/"
				defaultOptions = "rw,nolock,tcp,utf8" if protocol == "nfs" else "rw,utf8"
				return {
					"id": text("id") or f"{mode}:{protocol}:{sharename}",
					"mode": mode,
					"protocol": protocol,
					"active": text("active", "False") in ("True", "true", "1"),
					"hddReplacement": text("hdd_replacement", "False") in ("True", "true", "1"),
					"sharename": sharename,
					"displayName": text("display_name"),
					"server": text("ip", "192.168.0.0"),
					"remotepath": text("sharedir", defaultDir),
					"options": text("options", defaultOptions),
					"username": text("username", "guest") if protocol == "cifs" else "",
					"password": text("password") if protocol == "cifs" else "",
					"nfsVersion": text("nfs_version") if protocol == "nfs" else "",
				}
			mounts = []
			for protocol in self.PROTOCOLS:
				for protoNode in node.findall(protocol):
					for mountNode in protoNode.findall("mount"):
						mounts.append(readMount(mountNode, wrapperMode, protocol))
			return mounts
		mounts = []
		root = fileReadXML(self.AUTOMOUNTS_PATH, default="<mountmanager></mountmanager>", source=MODULE_NAME)
		if root is None:
			return mounts
		for wrapperMode in self.READ_MODE_WRAPPERS:
			for modeNode in root.findall(wrapperMode):
				mounts += readMode(modeNode, wrapperMode)
		mounts += readMode(root, "old_enigma2")
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
				remotepath = mount.get("remotepath") or ""
				if (mount.get("protocol") or "nfs") == "nfs":
					nfsShares.add(f"{server}:/{remotepath}")
				else:
					cifsShares.add(f"//{server}/{remotepath}")

			autoNetworkLines = [line for line in fileReadLines(self.AUTO_NETWORK_PATH, default=[], source=MODULE_NAME)
				if not lineIsManaged(line, " ", nfsShares, cifsShares, cifsColonPrefix=True)]
			fstabLines = [line for line in fileReadLines(self.FSTAB_PATH, default=[], source=MODULE_NAME)
				if not lineIsManaged(line, None, nfsShares, cifsShares, cifsColonPrefix=False)]

			for mount, mode in effective:
				if not mount.get("active"):
					continue
				protocol = mount.get("protocol") or "nfs"
				server = mount.get("server") or ""
				remotepath = mount.get("remotepath") or ""
				sharename = mount.get("sharename") or ""
				options = mount.get("options") or ""
				if mode == "autofs":
					if protocol == "nfs":
						autoNetworkLines.append(f"{sharename} -fstype=nfs,{self.sanitizeOptions(options, autofs=True)} {server}:/{remotepath}")
					else:
						username = (mount.get("username") or "").replace(" ", "\\ ")
						password = (mount.get("password") or "").replace(" ", "\\ ")
						autoNetworkLines.append(f"{sharename} -fstype=cifs,user={username},pass={password},{self.sanitizeOptions(options, cifs=True, autofs=True)} ://{server}/{remotepath}")
				elif mode == "fstab":
					path = self.mountPointFor(mount)
					if protocol == "nfs":
						fstabLines.append(f"{server}:/{remotepath}\t{path}\tnfs\t_netdev,{self.sanitizeOptions(options, fstab=True)}\t0 0")
					else:
						username = mount.get("username") or ""
						password = mount.get("password") or ""
						fstabLines.append(f"//{server}/{remotepath}\t{path}\tcifs\tuser={username},pass={password},_netdev,{self.sanitizeOptions(options, cifs=True, fstab=True)}\t0 0")

			fileWriteLines(self.AUTO_NETWORK_PATH, autoNetworkLines, source=MODULE_NAME)
			fileWriteLines(self.FSTAB_PATH, fstabLines, source=MODULE_NAME)

		def writeMount(protoNode, mount, protocol):
			node = SubElement(protoNode, "mount")
			SubElement(node, "id").text = str(mount.get("id") or self.newId())
			SubElement(node, "active").text = "True" if mount.get("active") else "False"
			SubElement(node, "hdd_replacement").text = "True" if mount.get("hddReplacement") else "False"
			SubElement(node, "ip").text = str(mount.get("server") or "")
			SubElement(node, "sharename").text = str(mount.get("sharename") or "")
			SubElement(node, "display_name").text = str(mount.get("displayName") or "")
			SubElement(node, "sharedir").text = str(mount.get("remotepath") or "")
			SubElement(node, "options").text = str(mount.get("options") or "")
			if protocol == "cifs":
				SubElement(node, "username").text = str(mount.get("username") or "")
				SubElement(node, "password").text = str(mount.get("password") or "")
			elif mount.get("nfsVersion"):
				SubElement(node, "nfs_version").text = str(mount.get("nfsVersion") or "")

		effective = []
		for mount in mounts:
			mode = mount.get("mode")
			if mode not in self.WRITE_MODES:
				mode = "fstab"
			effective.append((mount, mode))

		root = Element("mountmanager")
		groups = {}
		for mount, mode in effective:
			protocol = mount.get("protocol") or "nfs"
			groups.setdefault(mode, {}).setdefault(protocol, []).append(mount)
		for mode in self.WRITE_MODES:
			if mode not in groups:
				continue
			modeNode = SubElement(root, mode)
			for protocol in self.PROTOCOLS:
				for mount in groups[mode].get(protocol, []):
					writeMount(SubElement(modeNode, protocol), mount, protocol)
		try:
			ElementTree(root).write(self.AUTOMOUNTS_PATH, encoding="UTF-8", xml_declaration=True)
			chmod(self.AUTOMOUNTS_PATH, 0o600)  # contains plaintext passwords, see above
		except OSError as err:
			print(f"[{MODULE_NAME}] Error writing '{self.AUTOMOUNTS_PATH}': {err}")

		writeMountFiles(effective)

	@staticmethod
	# Direct port of the old plugin's sanitizeOptions() - same quirky
	# per-protocol option-string building (nfsvers/rsize/wsize/proto/timeo
	# defaults differ slightly between fstab and autofs, see AutoMount.py),
	# kept as-is for compatibility with what mount/autofs actually expect.
	def sanitizeOptions(self, origOptions, cifs=False, fstab=False, autofs=False):
		options = (origOptions or "").strip()
		options = options.replace("utf8", "iocharset=utf8")
		if fstab:
			if not options:
				options = "rw"
				if not cifs:
					options += ",nfsvers=3,rsize=8192,wsize=8192,proto=tcp"
			elif not cifs:
				options += ",nfsvers=3"
				if "rsize" not in options:
					options += ",rsize=8192"
				if "wsize" not in options:
					options += ",wsize=8192"
				if "tcp" not in options and "udp" not in options:
					options += ",proto=tcp"
				options += ",timeo=14,soft"
		elif autofs:
			if not options:
				options = "rw"
				if not cifs:
					options += ",nfsvers=3,rsize=8192,wsize=8192"
			elif not cifs:
				options += ",nfsvers=3"
				if "rsize" not in options:
					options += ",rsize=8192"
				if "wsize" not in options:
					options += ",wsize=8192"
				if "tcp" not in options and "udp" not in options:
					options += ",proto=tcp"
				options += ",timeo=14,soft"
		else:
			if not options:
				options = "rw,rsize=8192,wsize=8192"
				if not cifs:
					options += ",proto=tcp"
			elif not cifs:
				if "rsize" not in options:
					options += ",rsize=8192"
				if "wsize" not in options:
					options += ",wsize=8192"
				if "tcp" not in options and "udp" not in options:
					options += ",proto=tcp"
		return options

	def newId(self):
		return f"mount-{uuid4().hex[:12]}"

	# Matches the old plugin's CheckMountPoint()/CheckMountPointFinished()
	# path convention exactly, since that's what actually ends up mounted
	# once mount execution is built (doc section 11): autofs always mounts
	# under /media/autofs/<sharename>; hdd_replacement mounts (any other
	# mode) replace /media/hdd itself; everything else mounts under
	# /media/net/<sharename>.
	def mountPointFor(self, mount):
		sharename = mount.get("sharename") or mount.get("id", "")
		if mount.get("mode") == "autofs":
			return f"/media/autofs/{sharename}"
		if mount.get("hddReplacement"):
			return "/media/hdd"
		return f"/media/net/{sharename}"

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


class NetworkMountSetup(Setup):
	"""Add/edit one network mount definition. Fields are declared in
	data/setup.xml under key "NetworkMountSetup" and resolved there via
	self.<name> (see Setup.py's eval(element.text) and NetworkNFSSetup in
	NetworkServices.py for the same pattern) - not global config.* entries,
	these are scratch values that only matter for the duration of this dialog.
	Basic fields are always visible; level="2" fields in the XML only show up
	when the user's global Setup Level (Menu > Setup > User Interface) is
	Expert, same mechanism every other Setup screen in Enigma2 already uses -
	no separate "Expert" toggle invented just for this screen."""

	PROTOCOL_CHOICES = (("cifs", _("SMB / CIFS")), ("nfs", _("NFS")))
	MODE_CHOICES = (
		("autofs", _("Autofs (mount on first access)")),
		("fstab", _("fstab (mount at boot)")),
	)
	NFS_VERSION_CHOICES = (("auto", _("Automatic")), ("3", "NFSv3"), ("4", "NFSv4"))

	def __init__(self, session, mount=None):
		self.repository = NetworkMountRepository()
		self.mountId = mount.get("id") if mount else None

		def field(key, default=""):
			return mount.get(key, default) if mount else default

		self.active = NoSave(ConfigYesNo(default=field("active", True)))
		self.displayName = NoSave(ConfigText(default=field("displayName"), fixed_size=False))
		self.protocol = NoSave(ConfigSelection(default=field("protocol", "cifs") or "cifs", choices=list(self.PROTOCOL_CHOICES)))
		self.server = NoSave(ConfigText(default=field("server"), fixed_size=False))
		self.remotepath = NoSave(ConfigText(default=field("remotepath"), fixed_size=False))
		self.mode = NoSave(ConfigSelection(default=field("mode", "autofs") or "autofs", choices=list(self.MODE_CHOICES)))
		self.username = NoSave(ConfigText(default=field("username"), fixed_size=False))
		self.password = NoSave(ConfigPassword(default=field("password")))
		self.sharename = NoSave(ConfigText(default=field("sharename"), fixed_size=False))
		self.options = NoSave(ConfigText(default=field("options"), fixed_size=False))
		self.nfsVersion = NoSave(ConfigSelection(default=field("nfsVersion", "auto") or "auto", choices=list(self.NFS_VERSION_CHOICES)))
		# hdd_replacement mounts /media/hdd itself instead of a dedicated
		# /media/net/<sharename> path - risky if the share isn't reliably
		# available, hence Expert-only, see doc section 10.3.
		self.hddReplacement = NoSave(ConfigYesNo(default=field("hddReplacement", False)))

		Setup.__init__(self, session=session, setup="NetworkMountSetup")
		# Checks self.mountId, not just "mount" being truthy - a discovery
		# pick (see NetworkMountDiscoveryScreen) prefills server/protocol/etc.
		# on a *new* entry without an "id", so it must still say "Add".
		self.setTitle(_("Edit Network Mount") if self.mountId else _("Add Network Mount"))

	def keySave(self):
		server = self.server.value.strip()
		remotepath = self.remotepath.value.strip().lstrip("/")
		if not server or not remotepath:
			self.session.open(MessageBox, _("Server and remote path are required."), MessageBox.TYPE_ERROR, timeout=5)
			return
		# Stable local key: explicit (Expert field) if set, else derived from
		# the display name, else from the server - never left empty, it's
		# used to build the local mount path (see NetworkMountRepository.mountPointFor()).
		sharename = self.sharename.value.strip() or sub(r"\W", "", self.displayName.value) or sub(r"\W", "", server)
		mount = {
			"id": self.mountId or self.repository.newId(),
			"active": self.active.value,
			"sharename": sharename,
			"displayName": self.displayName.value.strip(),
			"server": server,
			"remotepath": remotepath,
			"protocol": self.protocol.value,
			"mode": self.mode.value,
			"options": self.options.value.strip(),
			"username": self.username.value if self.protocol.value == "cifs" else "",
			"password": self.password.value if self.protocol.value == "cifs" else "",
			"nfsVersion": self.nfsVersion.value if self.protocol.value == "nfs" else "",
			"hddReplacement": self.hddReplacement.value,
		}
		mounts = [existing for existing in self.repository.load() if existing.get("id") != mount["id"]]
		mounts.append(mount)
		self.repository.save(mounts)
		Setup.keySave(self)


class NetworkMountDiscoveryScreen(Screen):
	"""Host list with shares nested underneath, expand/collapse per host -
	same tree shape as the old plugin's NetworkBrowser.py screen, rebuilt
	completely fresh: host discovery comes from the real discoveryManager
	(Avahi + neighbor-table observations, see Components/NetworkManager.py)
	instead of netscan/nmblookup, share enumeration runs async via Console
	(showmount/smbclient) instead of the old code's blocking
	subprocess.Popen().communicate() call in the GUI thread, and the
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

	GLYPH_HOST = "\uEA6D"          # host
	GLYPH_MOUNTED = "\uE914"       # check_circle - same glyph/meaning as NetworkSetup.py's STATE_OK
	GLYPH_NOT_MOUNTED = "\uE918"   # cancel - same glyph/meaning as NetworkSetup.py's STATE_FAIL
	COLOR_MOUNTED = gRGB(0x0000CC00).argb()    # green, matches NetworkSetup.py's STATE_OK
	COLOR_NOT_MOUNTED = gRGB(0x00808080).argb()  # grey - "not configured yet" isn't an error

	TEMPLATE_HOST = 0
	TEMPLATE_SHARE = 1

	# Position 0 is data[0], the <rowtemplate> selector (see TEMPLATE_* /
	# elistboxcontent.cpp's selectTemplate(), same convention as
	# NetworkOverview.ADAPTER_INDEX_NAMES in NetworkSetup.py) - reserved
	# here (not a real field) so indexNames stays contiguous from 0.
	INDEX_NAMES = {
		"_rowTemplate": 0,
		"Glyph": 1,          # host row: host glyph; share row: mounted/not-mounted glyph
		"GlyphColor": 2,      # share row only
		"IPAddress": 3,       # host row only
		"Type": 4,            # share row only: "NFS"/"CIFS"
		"Name": 5,            # host row: hostname; share row: share name
		"LocalPath": 6,       # share row only, when already configured
		"Data": 7,
	}

	skin = """
	<screen name="NetworkMountDiscoveryScreen" title="Discover Network Shares" position="center,center" size="1080,465" resolution="1280,720">
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
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" noWrap="1" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	# Avahi's "smb"/"nfs" (see AVAHI_SERVICE_TYPES) vs. the mount protocol
	# values NetworkMountSetup actually uses ("cifs"/"nfs") - shares found
	# via enumeration are tagged "nfs"/"smb" the same way, mapped once here.
	PROTOCOL_LABELS = {"smb": _("SMB"), "nfs": _("NFS")}
	AVAHI_TO_MOUNT_PROTOCOL = {"smb": "cifs", "nfs": "nfs"}
	REFRESH_DEBOUNCE_MS = 300  # coalesce bursts of observations (esp. Avahi resending its full snapshot) into one list rebuild

	NFS_SHOWMOUNT_BIN = "/usr/sbin/showmount"
	SMB_SMBCLIENT_BIN = "/usr/bin/smbclient"

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Discover Network Shares"))
		self["list"] = List([], indexNames=self.INDEX_NAMES)
		self["description"] = Label()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Select"))
		self["key_yellow"] = StaticText(_("Rescan"))
		self["key_blue"] = StaticText(_("Enter manually"))
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"ok": (self.keySelect, _("Expand/collapse the selected host, or use the selected share")),
			"cancel": (self.keyClose, _("Close")),
			"red": (self.keyClose, _("Close")),
			"green": (self.keySelect, _("Expand/collapse the selected host, or use the selected share")),
			"yellow": (self.keyRescan, _("Restart discovery")),
			"blue": (self.keyManual, _("Enter a hostname or IP address manually")),
		}, prio=0, description=_("Network Share Discovery Actions"))
		self.hosts = {}
		self.expanded = set()
		self.shares = {}         # address -> [share dict, ...]
		self.shareState = {}     # address -> "loading" | "done" | "empty"
		self.pendingProtocols = {}  # address -> {"nfs", "smb"} remaining
		self.configuredShares = {}  # (server, remotepath) -> local mount path, for already-configured shares
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
		repository = NetworkMountRepository()
		self.configuredShares = {(mount.get("server"), (mount.get("remotepath") or "").lstrip("/")): repository.mountPointFor(mount) for mount in repository.load()}
		discoveryManager.onObservation.append(self.onObservation)
		discoveryManager.start(runMs=None)
		self["description"].setText(_("Scanning…"))
		self.rebuildList()

	def stopDiscovery(self):
		self.closed = True
		self.refreshTimer.stop()
		# .remove() raises ValueError if this instance's onObservation was
		# never registered (e.g. discoveryClosed() ran before onShow ever
		# fired) - must not skip stop()/killAll() below because of that.
		try:
			discoveryManager.onObservation.remove(self.onObservation)
		except ValueError:
			pass
		discoveryManager.stop()
		self.console.killAll()

	def keyRescan(self):
		self.hosts = {}
		self.expanded = set()
		self.shares = {}
		self.shareState = {}
		self.pendingProtocols = {}
		self["description"].setText(_("Scanning…"))
		self.rebuildList()

	def keyManual(self):
		self.session.openWithCallback(self.manualEntered, InputBox, title=_("Enter a hostname or IP address"), text="", maxSize=False, type=Input.TEXT)

	def manualEntered(self, text=None):
		text = (text or "").strip()
		if text:
			self.close({"address": text, "hostname": "", "protocol": None, "remotepath": "", "sharename": ""})

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
		else:
			self.expanded.add(address)
			self.startShareEnumeration(address)
		self.rebuildList()

	def pickShare(self, share):
		host = self.hosts.get(share["address"]) or {}
		self.close({
			"address": share["address"],
			"hostname": host.get("hostname") or "",
			"protocol": self.AVAHI_TO_MOUNT_PROTOCOL.get(share["protocol"], share["protocol"]),
			"remotepath": share["path"].lstrip("/"),
			"sharename": share["name"],
		})

	# -- share enumeration (only reached via explicit expand, see toggleExpand) --

	def startShareEnumeration(self, address):
		if self.shareState.get(address) == "loading":
			return
		self.shareState[address] = "loading"
		self.shares[address] = []
		self.pendingProtocols[address] = {"nfs", "smb"}
		self.enumerateNfs(address)
		self.enumerateSmb(address)

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
				self.shares.setdefault(address, []).append({"address": address, "protocol": "nfs", "name": name, "path": path, "description": ""})
		self.finishProtocol(address, "nfs")

	def enumerateSmb(self, address):
		if not exists(self.SMB_SMBCLIENT_BIN):
			self.finishProtocol(address, "smb")
			return
		self.console.ePopen((self.SMB_SMBCLIENT_BIN, self.SMB_SMBCLIENT_BIN, "-m", "SMB3", "-N", "-g", "-L", address), callback=lambda data, retVal, extra=None: self.onSmbResult(address, data, retVal))

	def onSmbResult(self, address, data, retVal):
		if getattr(self, "closed", True):
			return
		if data:
			for line in data.splitlines():
				parts = line.split("|")
				if len(parts) == 3 and parts[0] == "Disk" and not parts[1].endswith("$"):
					self.shares.setdefault(address, []).append({"address": address, "protocol": "smb", "name": parts[1], "path": parts[1], "description": parts[2]})
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

	# -- discovery observations (hosts, not shares - see onObservation) --

	def onObservation(self, observation):
		# Defends against a stale registration outliving this screen (see
		# stopDiscovery()'s comment): Screen teardown can clear this
		# instance's __dict__ entirely, so even "self.closed" would itself
		# raise AttributeError - getattr's default sidesteps that.
		if getattr(self, "closed", True):
			return
		source = observation.get("source")
		if source == "avahi":
			protocol = observation.get("protocol")
			hostname = observation.get("hostname") or ""
			interface = observation.get("interface")
			for address in observation.get("addresses") or []:
				host = self.hosts.setdefault(address, {"address": address, "hostname": "", "protocols": set(), "interface": interface, "state": ""})
				host["hostname"] = hostname or host["hostname"]
				host["interface"] = interface
				if protocol:
					host["protocols"].add(protocol)
		elif source == "neighbor":
			address = observation.get("address")
			if not address:
				return
			if observation.get("action") == "REMOVE":
				host = self.hosts.get(address)
				# Only drop it if we don't also know it from Avahi - an
				# actual mDNS-announced share is worth keeping even if the
				# neighbor-table entry aged out.
				if host and not host["protocols"]:
					del self.hosts[address]
				return
			host = self.hosts.setdefault(address, {"address": address, "hostname": "", "protocols": set(), "interface": observation.get("interface"), "state": ""})
			host["state"] = observation.get("state") or host["state"]
			host["interface"] = observation.get("interface") or host["interface"]
		else:
			return
		if not self.refreshTimer.isActive():
			self.refreshTimer.start(self.REFRESH_DEBOUNCE_MS, True)

	def rebuildList(self):
		if getattr(self, "closed", True):
			return
		entries = []
		for host in sorted(self.hosts.values(), key=lambda h: (not h["protocols"], h["hostname"] or h["address"])):
			address = host["address"]
			name = host["hostname"] or address
			entries.append((self.TEMPLATE_HOST, self.GLYPH_HOST, 0, address, "", name, "", {"kind": "host", "address": address}))
			if address not in self.expanded:
				continue
			state = self.shareState.get(address)
			if state == "loading":
				entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("Scanning for shares…"), "", {"kind": "status"}))
			elif state == "empty":
				entries.append((self.TEMPLATE_SHARE, "", 0, "", "", _("No shares found."), "", {"kind": "status"}))
			for share in self.shares.get(address, []):
				typeLabel = self.PROTOCOL_LABELS.get(share["protocol"], share["protocol"])
				localPath = self.configuredShares.get((address, share["path"].lstrip("/")))
				glyph = self.GLYPH_MOUNTED if localPath else self.GLYPH_NOT_MOUNTED
				glyphColor = self.COLOR_MOUNTED if localPath else self.COLOR_NOT_MOUNTED
				entries.append((self.TEMPLATE_SHARE, glyph, glyphColor, "", typeLabel, share["name"], localPath or "", dict(share, kind="share")))
		self["list"].setList(entries)
		count = len(self.hosts)
		self["description"].setText((ngettext("%d host found.", "%d hosts found.", count) % count) if count else _("No hosts found yet - still scanning…"))


class NetworkMountManager(Screen):
	LIST_NAME = 0
	LIST_DESCRIPTION = 1
	LIST_STATUS = 2
	LIST_DATA = 3

	skin = """
	<screen name="NetworkMountManager" title="Network Mount Manager" position="center,center" size="1080,465" resolution="1280,720">
		<widget source="mountlist" render="Listbox" position="0,0" size="1080,325">
			<templates>
				<template name="Default" fonts="Regular;22,Regular;18" itemHeight="50">
					<mode name="default">
						<text index="Name" position="10,4" size="600,28" font="0" />
						<text index="Description" position="10,30" size="700,20" font="1" foregroundColor="grey" />
						<text index="Status" position="620,4" size="450,28" font="0" horizontalAlignment="right" />
					</mode>
				</template>
			</templates>
		</widget>
		<eRectangle position="0,328" size="e,1" />
		<widget name="description" position="0,330" size="e,100" font="Regular;20" verticalAlignment="top" horizontalAlignment="left" />
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
		Screen.__init__(self, session, mandatoryWidgets=["mountlist"], enableHelp=True)
		self.setTitle(_("Network Mount Manager"))
		self.onChangedEntry = []
		self.mountList = []
		self.repository = NetworkMountRepository()
		indexNames = {
			"Name": self.LIST_NAME,
			"Description": self.LIST_DESCRIPTION,
			"Status": self.LIST_STATUS
		}
		self["mountlist"] = List(self.mountList, indexNames=indexNames)
		self["mountlist"].onSelectionChanged.append(self.selectionChanged)
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Toggle Active"))
		self["key_yellow"] = StaticText(_("Add"))
		self["key_blue"] = StaticText(_("Delete"))
		self["description"] = Label()
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"ok": (self.keyEdit, _("Edit the selected network mount")),
			"cancel": (self.close, _("Close the Network Mount Manager screen")),
			"red": (self.close, _("Close the Network Mount Manager screen")),
			"green": (self.keyToggleActive, _("Toggle the selected mount between active and inactive")),
			"yellow": (self.keyAdd, _("Add a new network mount")),
			"blue": (self.keyDelete, _("Delete the selected mount definition")),
		}, prio=0, description=_("Network Mount Manager Actions"))
		self.updateList()
		self.onShown.append(self.selectionChanged)

	def keyAdd(self):
		self.session.openWithCallback(self.discoveryClosed, NetworkMountDiscoveryScreen)

	def discoveryClosed(self, picked=None):
		mount = None
		if picked:
			mount = {
				"displayName": picked.get("hostname") or picked.get("address") or "",
				"server": picked.get("address") or "",
			}
			if picked.get("protocol"):
				mount["protocol"] = picked["protocol"]
			if picked.get("remotepath"):
				mount["remotepath"] = picked["remotepath"]
			if picked.get("sharename"):
				mount["sharename"] = picked["sharename"]
		self.session.openWithCallback(self.keySetupClosed, NetworkMountSetup, mount=mount)

	def keyEdit(self):
		current = self["mountlist"].getCurrent()
		if current:
			self.session.openWithCallback(self.keySetupClosed, NetworkMountSetup, mount=current[self.LIST_DATA])

	def keySetupClosed(self, *args):
		self.updateList()

	def buildList(self):
		self.mounts = self.repository.load()
		self.mountList = []
		for mount in self.mounts:
			name = mount.get("displayName") or mount.get("sharename") or mount.get("id")
			server = mount.get("server", "")
			remotepath = mount.get("remotepath", "")
			protocol = mount.get("protocol", "")
			mode = mount.get("mode", "")
			description = f"{server}/{remotepath}  ({protocol}, {mode})" if server or remotepath else f"({protocol}, {mode})"
			mounted = self.repository.isMounted(mount)
			activeText = _("active") if mount.get("active") else _("inactive")
			statusText = f"{_('mounted') if mounted else _('not mounted')} / {activeText}"
			self.mountList.append((name, description, statusText, mount))
		self["mountlist"].list = self.mountList

	def updateList(self):
		self.buildList()

	def selectionChanged(self):
		current = self["mountlist"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			name = current[self.LIST_NAME]
			description = current[self.LIST_DESCRIPTION]
			self["description"].setText(f"{current[self.LIST_STATUS]}\n{mount.get('id', '')}")
		else:
			name = ""
			description = ""
			self["description"].setText("")
		for callback in self.onChangedEntry:
			if callable(callback):
				callback(name, description)

	def keyToggleActive(self):
		current = self["mountlist"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			mount["active"] = not mount.get("active")
			self.repository.save(self.mounts)
			self.updateList()

	def keyDelete(self):
		def keyDeleteCallback(answer):
			if answer:
				self.mounts = [mount for mount in self.mounts if mount is not current[self.LIST_DATA]]
				self.repository.save(self.mounts)
				self.updateList()

		current = self["mountlist"].getCurrent()
		if current:
			mount = current[self.LIST_DATA]
			name = mount.get("displayName") or mount.get("sharename") or mount.get("id")
			if self.repository.isMounted(mount):
				self.session.open(MessageBox, _("This mount is currently active. Unmounting is not supported yet - only remove the definition, not the live mount."), MessageBox.TYPE_INFO, timeout=6)
				return
			self.session.openWithCallback(keyDeleteCallback, MessageBox, _("Do you really want to delete this network mount definition?\n%s") % name, MessageBox.TYPE_YESNO, default=False)

	def createSummary(self):
		return NetworkMountManagerSummary


class NetworkMountManagerSummary(Screen):
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

"""
NetworkManager.py – Unified network configuration layer for Enigma2 / OpenATV

Replaces:
	Components/Network.py                               (iNetwork)
	Plugins/SystemPlugins/WirelessLan/Wlan.py           (wpaSupplicant, brcmWLConfig)
	Plugins/SystemPlugins/WirelessLan/plugin.py         (configStrings, ifaceSupported)

Coding conventions (OpenATV):
	Indentation  : tabs
	Variables    : camelCase (first letter lower)
	Functions    : camelCase (first letter lower)
	Classes      : PascalCase (first letter upper)
	Private      : _camelCase prefix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from json import JSONDecodeError, loads
from os import chmod, listdir, makedirs, remove, rmdir
from os.path import basename, exists, isdir, ismount, realpath
from pickle import dump as pickleDump, load as pickleLoad
from re import compile, match
from shutil import copy2
from socket import AF_UNIX, SOCK_STREAM, gethostbyname, gethostname, socket
from subprocess import DEVNULL, check_output
from uuid import uuid4
from collections.abc import Callable
from twisted.internet import reactor

from enigma import e2avahi_set_debug, eNetworkServiceBrowser, eTimer

from Components.config import config
from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Components.PluginComponent import plugins
from Components.SystemInfo import BoxInfo
from Plugins.Plugin import PluginDescriptor
from Tools.Directories import fileReadLine, fileReadLines, fileReadXML, fileWriteLine, fileWriteLines
from Tools.ServiceAction import ServiceAction

# Path constants.
#
interfacesFile = "/etc/network/interfaces"
resolvFile = "/etc/resolv.conf"
nameserverFile = "/etc/enigma2/nameserversdns.conf"
wpaSupplicantDir = "/etc"
sysfsNet = "/sys/class/net"
procNetWireless = "/proc/net/wireless"
ifconfigBin = "/sbin/ifconfig"
ifupBin = "/sbin/ifup"
ifdownBin = "/sbin/ifdown"
wpaSupplicantBin = "/usr/sbin/wpa_supplicant"
wpaCliBin = "/usr/sbin/wpa_cli"
socketDaemonPath = "/var/run/daemon.socket"
netEventSocketPath = "/var/run/daemon_net.socket"
netinfoPath = "/var/run/netinfo"
netscanPath = "/var/run/netscan"
netrestarterBin = "/usr/sbin/netrestarter"

MODULE_NAME = __name__.split(".")[-1]


# Wi-Fi encryption modes. Old plugin used "Unencrypted" / "WPA/WPA2" – mapped
# on load, never stored.
class Encryption(StrEnum):
	NONE = "none"
	WEP = "wep"
	WPA = "wpa"
	WPA2 = "wpa2"
	WPA_WPA2 = "wpa+wpa2"  # Legacy combined mode stored as wpa2 in wpa_supplicant.
	WPA3 = "wpa3"


# Deferred via lambda so translation happens at display time, not import time.
encryptionLabels = {
	Encryption.NONE: lambda: _("None"),
	Encryption.WEP: lambda: "WEP",
	Encryption.WPA: lambda: "WPA",
	Encryption.WPA2: lambda: "WPA2",
	Encryption.WPA_WPA2: lambda: "WPA/WPA2",
	Encryption.WPA3: lambda: "WPA3"
}

# Driver-API identifiers.
apiNl80211 = "nl80211"
apiWext = "wext"
apiMadwifi = "madwifi"
apiRalink = "ralink"
apiZydas = "zydas"


# Central access point for all network configuration.
class NetworkManager:
	ADAPTER_BLACKLIST = frozenset((
		"ip6_vti0",
		"ip6tnl0",
		"ip_vti0",
		"lo",
		"p2p0",
		"sit0",
		"sys0",
		"tap0",
		"tun0",
		"tunl0",
		"wg0",
		"wifi0",
		"wmaster0"
	))

	ROUTE_METRIC_FILE = "/etc/default/e2-route-metric"
	ROUTE_METRIC_CHOICES = [(x, str(x)) for x in range(100, 901, 100)]
	NETINFO_UPDATE_DEBOUNCE_MS = 250  # coalesce bursts of "UPDATE" events from socketdaemon into one apply/notify
	# Legacy ethtool SUPPORTED_* bitmask (struct ethtool_cmd), capped at
	# 1000baseT/Full because that's all socketdaemon reports (main.c reads
	# ecmd.supported via the old ETHTOOL_GSET, not ETHTOOL_GLINKSETTINGS) –
	# a 2.5G/5G/10G adapter would need socketdaemon extended first, there's
	# nothing more to parse here in the meantime.
	LINKSPEED_BITS = {
		"10baseT/Half": (0x01, "10 Mbps Half Duplex"),
		"10baseT/Full": (0x02, "10 Mbps Full Duplex"),
		"100baseT/Half": (0x04, "100 Mbps Half Duplex"),
		"100baseT/Full": (0x08, "100 Mbps Full Duplex"),
		"1000baseT/Half": (0x10, "1000 Mbps Half Duplex"),
		"1000baseT/Full": (0x20, "1000 Mbps Full Duplex"),
	}

	def __init__(self):
		self._debug = config.crash.debugNetwork.value
		e2avahi_set_debug(self._debug)
		self.adapters: dict[str, Adapter] = {}
		self.connections: dict[str, list[Connection]] = {}
		self.vpnInterfaces: dict[str, VpnInfo] = {}
		self.nameserverConfig = NameserverConfig()
		self.interfacesFile = InterfacesFile()
		self.nsFiles = NameserverFiles()
		self.pendingRestart = None
		self.networkCheck = None
		self.onAdaptersChanged: list[Callable] = []
		self.netinfoUpdateTimer = eTimer()
		self.netinfoUpdateTimer.callback.append(self.onNetinfoUpdateDebounced)
		self.load()
		self._eventReader = NetEventReader(self)

	def log(self, msg: str):
		if self._debug:
			print(f"[NetworkManager] {msg}")

	def startNetworkCheck(self):  # Called once by InitNetwork() during Enigma2 startup.
		self.networkCheck = NetworkCheck()
		self.networkCheck.start()

	def load(self):
		self.log("load: Starting full configuration/state load.")
		self.discoverAdapters()
		self.loadInterfacesFile()
		self.loadWpaSupplicantFiles()
		self.nsFiles.load(self.nameserverConfig)
		self.applyNetinfo()
		self.log(f"load: Done, adapters={sorted(self.adapters.keys())}.")

	def discoverAdapters(self):
		def isBroadcomWl(interface: str, module: str) -> bool:
			return exists(f"/tmp/bcm/{interface}") or module in ("brcm-systemport", "brcmfmac", "brcmsmac")

		def detectDriverApi(interface: str, module: str) -> str:
			driver = apiNl80211
			if isBroadcomWl(interface, module):
				driver = apiWext
			elif isdir(f"{sysfsNet}/{interface}/device/ieee80211"):
				driver = apiNl80211
			elif module in ("ath_pci", "ath5k", "ar6k_wlan"):
				driver = apiMadwifi
			elif module in ("rt73", "rt73usb", "rt3070sta", "rt2800usb"):
				driver = apiRalink
			elif module == "zd1211b":
				driver = apiZydas
			elif exists(procNetWireless):
				try:
					if f"{interface}:" in open(procNetWireless).read():
						driver = apiWext
				except OSError:
					driver = apiNl80211
			return driver

		def isBlacklisted(interface: str) -> bool:
			return interface in self.ADAPTER_BLACKLIST or interface in vpnNames

		def detectModule(interface: str) -> str:
			devDir = f"{sysfsNet}/{interface}/device"
			modLink = f"{devDir}/driver/module"
			if isdir(modLink):
				return basename(realpath(modLink))
			try:
				for entry in listdir(devDir):
					if entry.startswith("1-"):
						deep = f"{devDir}/{entry}/driver/module"
						if isdir(deep):
							return basename(realpath(deep))
				fallback = f"{devDir}/driver"
				if isdir(fallback):
					return basename(realpath(fallback))
			except OSError:
				pass
			return ""

		def canWakeOnWiFi(interface: str) -> bool:
			return interface == "wlan3" and bool(BoxInfo.getItem("wwol"))

		vpnNames = {name for name, data in readNetinfoInterfaces().items() if data.get("type") == "vpn"}
		try:
			names = [x for x in listdir(sysfsNet) if not isBlacklisted(x)]
		except OSError:
			names = []

		def isWireless(interface: str) -> bool:
			if isWirelessName(interface):
				return True
			if isdir(f"{sysfsNet}/{interface}/wireless"):
				return True
			if exists(procNetWireless):
				try:
					return f"{interface}:" in open(procNetWireless).read()
				except OSError:
					pass
			return False

		for name in names:
			isWiFi = isWireless(name)
			module = detectModule(name)
			api = detectDriverApi(name, module)
			# Rediscovery (restartNetwork(), onIfaceAdd()) replaces the Adapter
			# object outright. Carry its live netInfo over so it doesn't go
			# blank until the next netinfo update arrives.
			existing = self.adapters.get(name)
			adapter = Adapter(
				name=name,
				isWiFi=isWiFi,
				module=module,
				driverApi=api,
				isBroadcomWl=isBroadcomWl(name, module),
				canWakeOnWiFi=canWakeOnWiFi(name),
				mac=fileReadLine(f"{sysfsNet}/{name}/address", default=""),
				netInfo=existing.netInfo if existing else NetInfo(),
			)
			netInfo = adapter.netInfo
			try:
				flags = int(open(f"{sysfsNet}/{name}/flags").read().strip(), 16)
				netInfo.up = bool(flags & 1)
			except OSError:
				pass
			self.adapters[name] = adapter
			self.log(f"discoverAdapters: {name} isWiFi={isWiFi} module={module} driverApi={api} up={netInfo.up}.")

	def loadInterfacesFile(self):
		self.interfacesFile.load()
		parsed, autoIfaces, wakeOnWiFiIfaces = self.interfacesFile.parse()
		self.log(f"loadInterfacesFile: autoIfaces={sorted(autoIfaces)} wakeOnWiFiIfaces={sorted(wakeOnWiFiIfaces)}.")
		for interface, conns in parsed.items():
			if interface not in self.adapters:
				self.adapters[interface] = Adapter(
					name=interface,
					isWiFi=isWirelessName(interface),
					driverApi=apiNl80211,
				)
			self.connections[interface] = conns
			self.adapters[interface].adapterEnabled = interface in autoIfaces
			if interface in wakeOnWiFiIfaces:
				for conn in conns:
					conn.wakeOnWiFi = True
			self.log(f"loadInterfacesFile: {interface} adapterEnabled={self.adapters[interface].adapterEnabled} connections={len(conns)}.")
		for interface, adapter in self.adapters.items():
			if not self.connections.get(interface):
				self.connections[interface] = [Connection(
					adapter=interface,
					name=interface,
					dhcp=True,
					wifi=WiFiConfig() if adapter.isWiFi else None,
				)]

	def loadWpaSupplicantFiles(self):
		for interface, adapter in self.adapters.items():
			if not adapter.isWiFi:
				continue
			wpf = WpaSupplicantFile(interface)
			if not wpf.exists():
				self.log(f"loadWpaSupplicantFiles: {interface} No '{wpf.path}'.")
				continue
			for wifi in wpf.parse():
				self.log(f"loadWpaSupplicantFiles: {interface} SSID={wifi.ssid!r} disabled={wifi.disabled} encryption={wifi.encryption}.")
				self.mergeWiFiConfig(interface, wifi)

	def mergeWiFiConfig(self, interface: str, wifi: WiFiConfig):
		conns = self.getConnections(interface)
		bySsid = {x.wifi.ssid: x for x in conns if x.wifi and x.wifi.ssid}
		if wifi.ssid in bySsid:
			conn = bySsid[wifi.ssid]
			conn.wifi = wifi
			conn.enabled = not wifi.disabled
			conn.priority = wifi.priority
		else:
			conns.append(Connection(
				adapter=interface,
				name=wifi.ssid,
				dhcp=True,
				enabled=not wifi.disabled,
				priority=wifi.priority,
				wifi=wifi,
			))

	# Writes wpa_supplicant.conf for onlyIface, or every Wi-Fi adapter if None.
	# Does NOT touch /etc/network/interfaces — saving one Wi-Fi profile must
	# not trigger an adapter-level ifup/ifdown/restart.
	def saveWpaSupplicant(self, onlyIface: str | None = None) -> bool:
		ok = True
		interfaces = [onlyIface] if onlyIface else list(self.adapters.keys())
		for interface in interfaces:
			adapter = self.adapters.get(interface)
			if not adapter or not adapter.isWiFi:
				continue
			conns = self.getConnections(interface)
			for conn in conns:
				if conn.wifi is not None and conn.wifi.ssid:
					conn.wifi.disabled = not conn.enabled
					conn.wifi.priority = conn.priority
			wifiConfigs = [x.wifi for x in conns if x.wifi is not None and x.wifi.ssid]
			if not wifiConfigs:
				continue
			self.log(f"saveWpaSupplicant: {interface} writing {len(wifiConfigs)} wifi config(s): {", ".join(f"{x.ssid!r}(disabled={x.disabled})" for x in wifiConfigs)}.")
			wpf = WpaSupplicantFile(interface)
			wpf.ensureDir()
			ok = wpf.save(wifiConfigs) and ok
			self.reconfigureWifi(interface)
		return ok

	# Tells a running wpa_supplicant to re-read its config file — it never
	# does this on its own. No-op if wpa_supplicant isn't running yet.
	def reconfigureWifi(self, interface: str) -> None:
		if not self.wpaSupplicantRunning(interface):
			return
		self.log(f"reconfigureWifi: {interface}.")
		Console().ePopen(f"{wpaCliBin} -i{interface} reconfigure 2>/dev/null; true")

	def save(self) -> bool:
		# ===========================================================================
		# Wi-Fi configStrings (interfaces pre-up / pre-down)
		# ===========================================================================

		def buildWiFiConfigStrings(adapter: Adapter) -> list[str]:
			# Generic wpa_supplicant startup, not tied to a specific profile.
			# Always starts wpa_supplicant, even with zero configured
			# networks — it just stays idle until one is added.
			interface = adapter.name
			api = adapter.driverApi
			driverFlags = f"-D {api}" if api != apiNl80211 else ""
			return [
				f"pre-up {ifconfigBin} {interface} up || true",
				f"pre-up {wpaSupplicantBin} -i{interface} -c{adapter.wpaConfPath} -B {driverFlags} -P{adapter.wpaPidPath} || true",
				f"pre-down {wpaCliBin} -i{interface} terminate 2>/dev/null; true",
			]

		self.log("save: Starting.")
		ok = True
		for interface, adapter in self.adapters.items():
			if not adapter.isWiFi:
				continue
			cs = buildWiFiConfigStrings(adapter)
			for conn in self.getConnections(interface):
				if conn.wifi:
					conn.extraLines = list(cs)

		# Wi-Fi writes exactly one base Connection to interfaces (IP/DHCP/DNS/
		# WOL). SSID profiles live only in wpa_supplicant.conf and just
		# contribute pre-up/pre-down commands (extraLines) here.
		connMap = {}
		for interface, adapter in self.adapters.items():
			conns = self.getConnections(interface)
			if adapter.isWiFi:
				baseConn = self.getBaseConnection(interface)
				# adapterEnabled is the master switch, except WoW-Only mode keeps
				# the stanza written (for its wowl pre-up hooks) even while the
				# adapter is otherwise off.
				wowOnly = baseConn.wakeOnWiFi and not adapter.adapterEnabled
				baseConn.enabled = adapter.adapterEnabled or wowOnly
				# Must not depend on conns being non-empty — an earlier version
				# did, so an empty profile list silently dropped the
				# wpa_supplicant pre-up line and it never started, even though
				# the adapter was enabled.
				baseConn.extraLines = buildWiFiConfigStrings(adapter)
				connMap[interface] = [baseConn]
			else:
				# adapterEnabled is the master switch here too — keep
				# conn.enabled in sync or serializeConnection() only comments
				# out the "auto" line, not the rest of the stanza.
				for conn in conns:
					conn.enabled = adapter.adapterEnabled
				connMap[interface] = conns
		adapterEnabledMap = {interface: adapter.adapterEnabled for interface, adapter in self.adapters.items()}
		self.log(f"save: adapterEnabledMap={adapterEnabledMap}.")
		ok = self.interfacesFile.save(connMap, adapterEnabledMap) and ok
		ok = self.saveWpaSupplicant() and ok

		anyDhcp = any(conn.dhcp for conns in connMap.values() for conn in conns if conn.enabled)
		self.nsFiles.save(self.nameserverConfig, anyDhcp)
		# save() only writes files, it doesn't call notifyNetworkPlugins()
		# itself — that's applyAdapterChange()'s job (NetworkSetup.py),
		# paired with the matching reason=True once applied.
		self.log(f"save: Done, status={ok}.")
		return ok

	# ------------------------------------------------------------------
	# Runtime
	# ------------------------------------------------------------------

	def activateCommands(self, interface: str) -> list[str]:
		adapter = self.adapters.get(interface)
		if not adapter:
			return []
		conn = self.activeConnection(interface)
		if not conn:
			return [f"{ifupBin} {interface}"]
		if adapter.isWiFi:
			return WiFiRuntime(adapter).commandsActivate(conn)
		return [f"{ifupBin} {interface}"]

	def deactivateCommands(self, interface: str) -> list[str]:
		adapter = self.adapters.get(interface)
		if adapter and adapter.isWiFi:
			return WiFiRuntime(adapter).commandsDeactivate()
		return [
			f"{ifdownBin} {interface} 2>/dev/null; true",
			f"ip addr flush dev {interface} scope global 2>/dev/null; true",
		]

	# Restart via socketdaemon NETRESTART.
	def restartNetwork(self, interface: str = "", callback: Callable | None = None):
		self.log(f"restartNetwork: interface={interface or "all"}.")

		def done(retval: int = 0):
			self.log(f"restartNetwork: {interface or "all"} done, returned {retval}.")
			# discoverAdapters() resets each Adapter to defaults
			# (adapterEnabled=False) — restore persisted config on top, same
			# as load() does at startup.
			self.discoverAdapters()
			self.loadInterfacesFile()
			self.loadWpaSupplicantFiles()
			# discoverAdapters() carries over the old netInfo so the UI
			# doesn't go blank, but it's stale. The daemon's async UPDATE
			# event may lag, so refresh /var/run/netinfo synchronously too.
			self.applyNetinfo()
			# Restart plugins stopped earlier (e.g. OpenWebif). If another
			# adapter kept the box reachable, the matching reason=False call
			# was skipped, so this one is too.
			self.notifyNetworkPlugins(True, interface=interface)
			if callback:
				callback()
		self.pendingRestart = ServiceAction.netrestart(done, iface=interface)

	# ------------------------------------------------------------------
	# Accessors
	# ------------------------------------------------------------------

	def getAdapter(self, interface: str) -> Adapter | None:
		return self.adapters.get(interface)

	def getNetInfo(self, interface: str) -> NetInfo:
		adapter = self.adapters.get(interface)
		return adapter.netInfo if adapter else NetInfo()

	def getConnections(self, interface: str) -> list[Connection]:
		return self.connections.setdefault(interface, [])

	# Highest-priority enabled connection for this adapter.
	def activeConnection(self, interface: str) -> Connection | None:
		enabled = [x for x in self.getConnections(interface) if x.enabled]
		return max(enabled, key=lambda conn: conn.priority, default=None)

	# The non-SSID Connection carrying IP/DHCP/DNS/WOL config — the only one
	# ever written to interfaces for a Wi-Fi adapter (for LAN, just the one
	# Connection). Created on demand if it doesn't exist yet.
	def getBaseConnection(self, interface: str) -> Connection:
		conns = self.getConnections(interface)
		if not conns:
			adapter = self.adapters.get(interface)
			isWiFi = adapter.isWiFi if adapter else isWirelessName(interface)
			base = Connection(adapter=interface, name=interface, dhcp=True, wifi=WiFiConfig() if isWiFi else None)
			conns.append(base)
			return base
		base = next((x for x in conns if not (x.wifi and x.wifi.ssid)), None)
		if base is None:
			adapter = self.adapters.get(interface)
			isWiFi = adapter.isWiFi if adapter else isWirelessName(interface)
			base = Connection(adapter=interface, name=interface, dhcp=True, wifi=WiFiConfig() if isWiFi else None)
			conns.append(base)
		return base

	def getActiveConnection(self, interface: str) -> Connection | None:
		return self.activeConnection(interface)

	def getWiFiConnections(self, interface: str) -> list[Connection]:
		return [x for x in self.getConnections(interface) if x.isWiFi]

	def addConnection(self, conn: Connection):
		self.getConnections(conn.adapter).append(conn)

	def removeConnection(self, interface: str, ssid: str) -> bool:
		conns = self.connections.get(interface)
		if not conns:
			self.log(f"removeConnection: {interface} not found.")
			return False
		before = len(conns)
		self.connections[interface] = [x for x in conns if not (x.wifi and x.wifi.ssid == ssid)]
		removed = len(self.connections[interface]) < before
		self.log(f"removeConnection: {interface} SSID='{ssid!r}', removed={removed}.")
		return removed

	def setNameservers(self, servers: list):
		self.nameserverConfig.servers = list(servers)

	# Returns a human-readable adapter label.
	def getFriendlyAdapterName(self, interface: str) -> str:
		adapter = self.adapters.get(interface)
		if adapter is None:
			return interface
		wifiAdapters = sorted(name for name, other in self.adapters.items() if other.isWiFi)
		lanAdapters = sorted(name for name, other in self.adapters.items() if not other.isWiFi)
		if adapter.isWiFi:
			idx = wifiAdapters.index(interface) if interface in wifiAdapters else 0
			return _("Wi-Fi connection") + (f" {idx + 1}" if idx else "")
		idx = lanAdapters.index(interface) if interface in lanAdapters else 0
		return _("LAN connection") + (f" {idx + 1}" if idx else "")

	# Compatibility shim – returns a short adapter description.
	def getFriendlyAdapterDescription(self, interface: str) -> str:
		adapter = self.adapters.get(interface)
		if adapter is None:
			return interface
		if adapter.isWiFi:
			return f"{adapter.module or 'Unknown'} {_('wireless network interface')}"
		return _("Ethernet network interface")

	# Fires WHERE_NETWORKCONFIG_READ plugins (e.g. OpenWebif's
	# HttpdStart/HttpdStop). reason=False: network is about to change,
	# plugins stop. reason=True: change is done, plugins restart. Plugins
	# are expected to handle redundant calls cheaply.
	#
	# If `interface` is given and some OTHER adapter is already up with a
	# real IP, the box stays reachable regardless, so nothing is notified
	# (e.g. disabling wlan0 while eth0 serves OpenWebif shouldn't bounce it).
	def notifyNetworkPlugins(self, reason: bool, interface: str = ""):
		self.log(f"notifyNetworkPlugins: reason={reason} interface={interface!r} states={", ".join(f"{other}(up={adapter.netInfo.up}, ip={adapter.netInfo.ip})" for other, adapter in self.adapters.items())}.")
		if interface:
			otherAdapterUp = any(
				adapter.netInfo.up and any(octet != 0 for octet in adapter.netInfo.ip)
				for other, adapter in self.adapters.items() if other != interface
			)
			if otherAdapterUp:
				self.log(f"notifyNetworkPlugins: {interface} changed but another adapter is still up -> skipped.")
				return
		try:
			notified = [str(plugin) for plugin in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKCONFIG_READ)]
			self.log(f"notifyNetworkPlugins: Calling {notified} with reason={reason}.")
			for plugin in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKCONFIG_READ):
				plugin(reason=reason)
		except Exception as err:
			self.log(f"notifyNetworkPlugins: Error '{err}'!")

	def activateInterface(self, interface, callback=None):
		adapter = self.adapters.get(interface)
		if adapter and not adapter.isWiFi:
			def lanUp(retval: int):
				self.log(f"activateInterface: {interface} (LAN) ifup returned {retval}.")
				self.notifyNetworkPlugins(True)
				if callback:
					callback(retval == 0)
			self.log(f"activateInterface: {interface} (LAN) ifup.")
			self.pendingRestart = ServiceAction.ifup(interface, lanUp)
			return

		def wlanUp(retval: bool = True):
			self.log(f"activateInterface: {interface} (Wi-Fi) done.")
			self.notifyNetworkPlugins(True)
			if callback:
				callback(True)
		try:
			cmds = self.activateCommands(interface)
			self.log(f"activateInterface: {interface} (Wi-Fi) commands='{cmds}'.")
			Console().eBatch(cmds, lambda result: wlanUp(), debug=True)
		except Exception as err:
			self.log(f"activateInterface: {interface} (Wi-Fi) failed '{err}'!")
			if callback:
				callback(False)

	def getWiFiNetworkList(self, interface: str) -> list[str]:
		return [f"{wpaCliBin} -i{interface} list_networks"]

	def wpaSupplicantRunning(self, interface: str) -> bool:
		adapter = self.adapters.get(interface)
		running = exists(adapter.wpaCtrlPath) if adapter else False
		self.log(f"wpaSupplicantRunning: {interface} = {running}.")
		return running

	def getWiFiStatus(self, interface: str) -> dict:
		"""Parsed `wpa_cli status` (wpa_state, bssid, …) – used to explain *why* a
		Wi-Fi connection attempt failed (wrong key, AP not found, DHCP only, …).
		Empty dict if wpa_supplicant isn't reachable."""
		result = {}
		try:
			out = check_output([wpaCliBin, "-i", interface, "status"], stderr=DEVNULL, timeout=2).decode(errors="replace")
			for line in out.splitlines():
				key, sep, val = line.partition("=")
				if sep:
					result[key.strip()] = val.strip()
		except Exception as err:
			self.log(f"getWiFiStatus: {interface} wpa_cli failed '{err}'!")
		self.log(f"getWiFiStatus: {interface} = {result}.")
		return result

	def setBgscan(self, interface: str, bgscan: str):
		for conn in self.getWiFiConnections(interface):
			if conn.wifi:
				conn.wifi.bgscan = bgscan

	def getRoamingMode(self, interface: str) -> str:
		conn = self.getActiveConnection(interface)
		return conn.wifi.bgscan if (conn and conn.wifi) else ""

	def setRoamingMode(self, interface: str, mode: str):
		presets = {"auto": "simple:30:-70:3600", "fast": "simple:10:-65:300", "off": ""}
		self.setBgscan(interface, presets.get(mode, mode))

	# ------------------------------------------------------------------
	# Wake-on-WiFi
	# ------------------------------------------------------------------

	def setWakeOnWiFiCommands(self, interface: str, enable: bool) -> list[str]:
		adapter = self.adapters.get(interface)
		if adapter is None or not adapter.canWakeOnWiFi:
			return []
		self.getBaseConnection(interface).wakeOnWiFi = enable
		cmds: list[str] = []
		if enable:
			cmds.append(f"wl -i {interface} wowl 0x100")
			cmds.append(f"wl -i {interface} wowl_activate")
		else:
			cmds.append(f"wl -i {interface} wowl 0")
		procPath = BoxInfo.getItem("WakeOnLAN") or ""
		if procPath and exists(procPath):
			cmds.append(f"echo '{'enable' if enable else 'disable'}' > {procPath}")
		self.updateWowPreup(adapter, enable)
		return cmds

	def updateWowPreup(self, adapter: Adapter, enable: bool):
		baseConn = self.getBaseConnection(adapter.name)
		interface = adapter.name
		baseConn.extraLines = [x for x in baseConn.extraLines if "wowl" not in x]
		if enable:
			baseConn.extraLines.insert(0, f"pre-up wl -i {interface} wowl_activate || true")
			baseConn.extraLines.insert(0, f"pre-up wl -i {interface} wowl 0x100 || true")

	def getWakeOnWiFi(self, interface: str) -> bool:
		if interface not in self.adapters:
			return False
		return self.getBaseConnection(interface).wakeOnWiFi

	# ------------------------------------------------------------------
	# Link speed (forced, non-auto-negotiated)
	# ------------------------------------------------------------------

	def getSupportedLinkSpeeds(self, interface: str) -> list[tuple[str, str]]:
		choices = [("auto", _("Auto"))]
		adapter = self.adapters.get(interface)
		if adapter is None or adapter.isWiFi:
			return choices
		mask = adapter.netInfo.linkSupported
		for _ethtoolMode, (bits, label) in self.LINKSPEED_BITS.items():
			if mask & bits:
				choices.append((f"{bits:#04x}", label))
		return choices

	@staticmethod
	def getLinkSpeed(interface: str) -> str:
		return fileReadLine(f"/etc/enigma2/{interface}_linkspeed", default="auto") or "auto"

	@staticmethod
	def setLinkSpeed(interface: str, value: str) -> None:
		path = f"/etc/enigma2/{interface}_linkspeed"
		if value == "auto":
			try:
				remove(path)
			except OSError:
				pass
		else:
			fileWriteLine(path, value)

	# ------------------------------------------------------------------
	# Route metric (/etc/default/e2-route-metric – LAN_METRIC/WLAN_METRIC
	# only; every other line/setting in that file is left untouched)
	# ------------------------------------------------------------------

	@staticmethod
	def parseMetricValue(raw: str) -> int | None:
		value = raw.split("#", 1)[0].strip().strip('"').strip("'")
		try:
			return int(value)
		except ValueError:
			return None

	@classmethod
	def getRouteMetrics(cls) -> tuple[int | None, int | None]:
		"""Returns (lanMetric, wlanMetric), or (None, None) if
		ROUTE_METRIC_FILE doesn't exist."""
		if not exists(cls.ROUTE_METRIC_FILE):
			return None, None
		lan = wlan = None
		for line in fileReadLines(cls.ROUTE_METRIC_FILE, default=[], source=MODULE_NAME):
			stripped = line.strip()
			if stripped.startswith("LAN_METRIC="):
				lan = cls.parseMetricValue(stripped.split("=", 1)[1])
			elif stripped.startswith("WLAN_METRIC="):
				wlan = cls.parseMetricValue(stripped.split("=", 1)[1])
		return lan, wlan

	@classmethod
	def setRouteMetrics(cls, lanMetric: int | None = None, wlanMetric: int | None = None) -> None:
		"""Rewrites only the LAN_METRIC/WLAN_METRIC lines in ROUTE_METRIC_FILE,
		leaving every other line untouched. No-op if the file doesn't exist."""
		if exists(cls.ROUTE_METRIC_FILE):
			newLines = []
			for line in fileReadLines(cls.ROUTE_METRIC_FILE, default=[], source=MODULE_NAME):
				stripped = line.strip()
				if lanMetric is not None and stripped.startswith("LAN_METRIC="):
					newLines.append(f"LAN_METRIC={lanMetric}")
				elif wlanMetric is not None and stripped.startswith("WLAN_METRIC="):
					newLines.append(f"WLAN_METRIC={wlanMetric}")
				else:
					newLines.append(line)
			fileWriteLines(cls.ROUTE_METRIC_FILE, newLines, source=MODULE_NAME)

	# ------------------------------------------------------------------
	# Event handlers (called by NetEventReader)
	# ------------------------------------------------------------------

	def notifyAdaptersChanged(self):
		for cb in self.onAdaptersChanged:
			try:
				cb()
			except Exception:
				pass

	# Update adapter runtime state from /var/run/netinfo without a full rescan.

	def applyNetinfo(self):
		interfaces = readNetinfoInterfaces()
		self.vpnInterfaces = {
			interface: VpnInfo(
				name=interface,
				up=data.get("up", False),
				running=data.get("running", False),
				mac=data.get("mac", ""),
				rxBytes=data.get("rx_bytes", 0),
				txBytes=data.get("tx_bytes", 0),
				mtu=data.get("mtu", 0),
				ip=parseIp4(data.get("ip4", "")) if data.get("ip4") else [0, 0, 0, 0],
				netmask=parseIp4(data.get("mask", "")) if data.get("mask") else [0, 0, 0, 0],
				prefix=data.get("prefix4", 0),
				bcast=parseIp4(data.get("brd", "")) if data.get("brd") else [0, 0, 0, 0],
				link=data.get("link", False),
			)
			for interface, data in interfaces.items() if data.get("type") == "vpn"
		}
		for interface, data in interfaces.items():
			adapter = self.adapters.get(interface)
			if adapter is None:
				continue
			netInfo = adapter.netInfo
			netInfo.up = data.get("up", False)
			# Always assign, with an empty default when absent — "only assign
			# if truthy" left stale values in place after a restart.
			ip4 = data.get("ip4", "")
			netInfo.ip = parseIp4(ip4) if ip4 else [0, 0, 0, 0]
			mask = data.get("mask", "")
			netInfo.netmask = parseIp4(mask) if mask else [0, 0, 0, 0]
			gw = data.get("gw", "")
			netInfo.gateway = parseIp4(gw) if gw else [0, 0, 0, 0]
			netInfo.isDefaultGateway = bool(data.get("defgw", False))
			brd = data.get("brd", "")
			netInfo.bcast = parseIp4(brd) if brd else [0, 0, 0, 0]
			netInfo.driver = data.get("driver", "")
			netInfo.hwId = data.get("hw_id", "")
			netInfo.bus = data.get("bus", "")
			netInfo.rxBytes = data.get("rx_bytes", 0)
			netInfo.txBytes = data.get("tx_bytes", 0)
			netInfo.mtu = data.get("mtu", 0)
			netInfo.ip6 = data.get("ip6", [])
			if adapter.isWiFi:
				netInfo.ssid = data.get("ssid", "")
				netInfo.link = netInfo.up and bool(netInfo.ssid)  # link = up and associated to AP
				netInfo.bssid = data.get("bssid", "")
				netInfo.freqMhz = data.get("freq_mhz", 0)
				netInfo.channel = data.get("channel", 0)
				netInfo.bitrateBps = data.get("bitrate_bps", 0)
				netInfo.signal = data.get("signal_dbm", 0)
			else:
				netInfo.link = netInfo.up and data.get("link", False)
				netInfo.speed = data.get("speed", -1)
				netInfo.duplex = data.get("duplex", "")
				netInfo.port = data.get("port", "")
				netInfo.transceiver = data.get("transceiver", "")
				netInfo.autoneg = data.get("autoneg", False)
				netInfo.linkSupported = data.get("link_supported", 0)

	def onNetinfoUpdate(self):
		self.log("onNetinfoUpdate: Started.")
		self.netinfoUpdateTimer.start(self.NETINFO_UPDATE_DEBOUNCE_MS, True)

	def onNetinfoUpdateDebounced(self):
		self.log("onNetinfoUpdate: De-bounced.")
		self.applyNetinfo()
		self.notifyAdaptersChanged()

	def onLinkChange(self, interface: str, up: bool, running: bool):
		self.log(f"onLinkChange: {interface} up={up} running={running}.")
		adapter = self.adapters.get(interface)
		if adapter:
			netInfo = adapter.netInfo
			netInfo.up = up
			if adapter.isWiFi:
				# Wi-Fi link = up and associated to AP; only clear here (on not-running or
				# not-up) — actually setting it True happens on the next netinfo update.
				if not running or not up:
					netInfo.link = False
					netInfo.ssid = ""
				# The daemon always sends an UPDATE right after LINK (same read
				# cycle), which is debounced in onNetinfoUpdate() – skip the
				# immediate notify here so Wi-Fi association flapping doesn't
				# cause a GUI refresh per flap.
				return
			netInfo.link = up and running
			self.showToast(interface, running)
		self.notifyAdaptersChanged()

	def showToast(self, interface: str, up: bool):
		from Screens.Toast import Toast
		text = _("Network cable connected (%s)") % interface if up else _("Network cable disconnected (%s)") % interface
		icon = "\uF003" if up else "\uF004"
		Toast.instance.showToast(text=text, toasttype=Toast.TYPE_INFO, timeout=4, customIcon=icon)

	def onIpChange(self, interface: str, ipPrefix: str):
		self.log(f"onIpChange: {interface} ipPrefix={ipPrefix}.")
		adapter = self.adapters.get(interface)
		if adapter:
			adapter.netInfo.ip = parseIp4(ipPrefix.split("/")[0])
		self.notifyAdaptersChanged()

	# Pings 8.8.8.8 (fallback 1.1.1.1) per adapter with link, writes the
	# result to Adapter.hasInternet, then calls callback() once.
	def checkConnectionInternet(self, callback: Callable[[], None]):
		for adapter in self.adapters.values():
			adapter.hasInternet = False
		candidates = [
			interface
			for interface, adapter in self.adapters.items()
			if adapter.netInfo.link and adapter.netInfo.isDefaultGateway and self.activeConnection(interface) is not None
		]
		self.log(f"checkConnectionInternet: candidates={candidates}.")
		if not candidates:
			callback()
			return

		remaining = [len(candidates)]

		def onResult(interface: str, ok: bool):
			self.adapters[interface].hasInternet = ok
			remaining[0] -= 1
			if remaining[0] == 0:
				results = {interface: self.adapters[interface].hasInternet for interface in candidates}
				self.log(f"checkConnectionInternet: results={results}.")
				callback()

		def fallbackDone(interface: str, exitCode: int):
			onResult(interface, exitCode == 0)

		def primaryDone(interface: str, exitCode: int):
			if exitCode == 0:
				onResult(interface, True)
			else:
				ServiceAction.ping(interface, "1.1.1.1", lambda ec, iface=interface: fallbackDone(interface, ec))

		for interface in candidates:
			ServiceAction.ping(interface, "8.8.8.8", lambda ec, iface=interface: primaryDone(interface, ec))

	def onIfaceAdd(self, interface: str):
		self.log(f"onIfaceAdd: {interface}.")
		if interface not in self.adapters:
			# Same as restartNetwork(): discoverAdapters() resets
			# adapterEnabled, so restore persisted config on top (e.g. a
			# re-plugged USB Wi-Fi dongle).
			self.discoverAdapters()
			self.loadInterfacesFile()
			self.loadWpaSupplicantFiles()
		self.notifyAdaptersChanged()

	def onIfaceRemove(self, interface: str):
		self.log(f"onIfaceRemove: {interface}.")
		self.adapters.pop(interface, None)
		self.notifyAdaptersChanged()

	def onScanTrigger(self, interface: str):
		self.log(f"onScanTrigger: {interface}.")
		pass  # placeholder: trigger wpa_cli scan when Wi-Fi comes up


# Wi-Fi-specific parameters for one Connection.
@dataclass
class WiFiConfig:
	ssid: str = ""
	hidden: bool = False
	encryption: Encryption = Encryption.NONE
	key: str = ""
	wepKeyType: str = "ASCII"  # "ASCII" | "HEX".
	wpaId: int | None = None
	priority: int = 0  # Wpa_supplicant priority (higher = preferred), synced from Connection.priority on save.
	disabled: bool = False  # Wpa_supplicant disabled=1.
	# Background scan – enables auto-roaming between known networks.
	# 	Format: "simple:<shortInterval>:<signalThreshold>:<longInterval>"
	# 	Set to "" to disable.
	bgscan: str = "simple:30:-70:3600"

	@property
	def needsKey(self) -> bool:
		return self.encryption != Encryption.NONE


# Logical network configuration attached to one physical Adapter.
@dataclass
class Connection:
	adapter: str = ""
	name: str = ""
	enabled: bool = False  # False -> Every line of this connection's stanza in /etc/network/interfaces is commented out with "# " (see serializeConnection()), not just "auto <iface>".
	priority: int = 0  # Higher = preferred, also wpa_supplicant priority.
	dhcp: bool = True
	ip: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	netmask: list[int] = field(default_factory=lambda: [255, 255, 255, 0])
	gateway: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	ipMode: int = 0  # 0=IPv4 only, 1=IPv6 only, 2=IPv4+IPv6.
	ipv6Dhcp: bool = True
	dnsServers: list = field(default_factory=list)  # [int,int,int,int] | "::addr".
	extraLines: list[str] = field(default_factory=list)
	wifi: WiFiConfig | None = None
	wakeOnWiFi: bool = False

	@property
	def isWiFi(self) -> bool:
		return self.wifi is not None

	def ipStr(self) -> str:
		return ".".join(str(x) for x in self.ip)

	def netmaskStr(self) -> str:
		return ".".join(str(x) for x in self.netmask)

	def gatewayStr(self) -> str:
		return ".".join(str(x) for x in self.gateway)


# Live/kernel state for one interface. Refreshed from socketdaemon's
# /var/run/netinfo JSON, sysfs and /proc/net/dev. Never persisted, held
# directly on Adapter.netInfo (a plain field, not a lookup).
@dataclass
class NetInfo:
	up: bool = False
	link: bool = False  # Physical link (cable/Wi-Fi association).
	ip: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	netmask: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	gateway: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	isDefaultGateway: bool = False  # True on the one interface currently owning the system's default route.
	bcast: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	ip6: list = field(default_factory=list)  # [{"addr": "…", "prefix": 64}, …].
	speed: int = -1  # LAN only, Mbps; -1 = unknown.
	duplex: str = ""  # LAN only: "full" | "half" | "".
	port: str = ""  # LAN only: "TP" | "MII" | "FIBRE" | ….
	transceiver: str = ""  # LAN only: "internal" | "external".
	autoneg: bool = False  # LAN only.
	linkSupported: int = 0  # LAN only, ETHTOOL SUPPORTED_* bitmask from socketdaemon.
	ssid: str = ""  # Wi-Fi only.
	bssid: str = ""  # Wi-Fi only, AP MAC address.
	freqMhz: int = 0  # Wi-Fi only, channel frequency in MHz.
	channel: int = 0  # Wi-Fi only, channel number.
	bitrateBps: int = 0  # Wi-Fi only, TX bitrate in bps.
	signal: int = 0  # Wi-Fi only, dBm.
	driver: str = ""  # Kernel module name (e.g. "r8168", "mt76x2u").
	hwId: str = ""  # "VVVV:DDDD" PCI or USB vendor:product hex.
	bus: str = ""  # Physical bus from socketdaemon (e.g. "usb", "pci", "platform").
	rxBytes: int = 0  # Received data counter from /proc/net/dev.
	txBytes: int = 0  # Transmitted data counter from /proc/net/dev.
	mtu: int = 0


# Read-only snapshot of one "type": "vpn" interface (e.g. "wg0") from
# socketdaemon's /var/run/netinfo, display only. VPN interfaces are
# ADAPTER_BLACKLIST'd and never become an Adapter: no interfaces stanza,
# no configuration UI, nothing writable here.
@dataclass
class VpnInfo:
	name: str
	up: bool = False
	running: bool = False
	mac: str = ""
	rxBytes: int = 0
	txBytes: int = 0
	mtu: int = 0
	ip: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	netmask: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	prefix: int = 0
	bcast: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	link: bool = False


# Physical network interface identity/config, as discovered in
# /sys/class/net, plus its live NetInfo. Holds no Connections (see
# NetworkManager.connections) — those are linked only via adapter name.
@dataclass
class Adapter:
	name: str
	mac: str = ""
	isWiFi: bool = False
	module: str = ""
	driverApi: str = apiNl80211
	isBroadcomWl: bool = False  # Has the vendor "wl" tool available (needed to kick iwlist scans alive).
	canWakeOnWiFi: bool = False
	adapterEnabled: bool = False  # False -> Every line of this adapter's stanza in /etc/network/interfaces is commented out with "# " (see serializeConnection()), not just "auto <iface>".
	netInfo: NetInfo = field(default_factory=NetInfo)
	hasInternet: bool | None = None  # None = Not checked (yet) by NetworkManager.checkConnectionInternet().

	@property
	def wpaConfPath(self) -> str:
		return f"{wpaSupplicantDir}/wpa_supplicant.{self.name}.conf"

	@property
	def wpaPidPath(self) -> str:
		return f"/var/run/wpa_supplicant-{self.name}.pid"

	@property
	def wpaCtrlPath(self) -> str:
		return f"/var/run/wpa_supplicant/{self.name}"

	@property
	def metric(self) -> int | None:
		"""LAN_METRIC or WLAN_METRIC (depending on this adapter's type) from
		e2-route-metric, clamped to NetworkManager.ROUTE_METRIC_CHOICES. None
		if the daemon config file doesn't exist."""
		lanMetric, wlanMetric = networkManager.getRouteMetrics()
		if lanMetric is None:
			return None
		value = wlanMetric if self.isWiFi else lanMetric
		if value not in dict(NetworkManager.ROUTE_METRIC_CHOICES):
			value = 600 if self.isWiFi else 100
		return value


# Global DNS (Dynamic Name Server) configuration.
@dataclass
class NameserverConfig:

	mode: str = "dhcp-router"
	servers: list = field(default_factory=list)
	rotate: bool = False
	suffix: str = ""
	ipMode: int = 0  # 0=IPv4 + IPv6, 1=IPv6 + IPv4, 2=IPv4 only, 3=IPv6 only.


# Lossless parser and writer for /etc/network/interfaces.
class InterfacesFile:
	_header = [
		"# Automatically generated by Enigma2.",
		"# Do NOT change manually!",
	]
	_stanzaKw = frozenset(("auto", "allow-auto", "allow-hotplug", "iface"))

	def __init__(self, path: str = interfacesFile):
		self.path = path
		self.writePath = path
		self.raw: list[str] = []
		self.load()

	def load(self):
		self.raw = fileReadLines(self.path, default=[], source=MODULE_NAME)

	def parse(self) -> tuple[dict[str, list[Connection]], set[str], set[str]]:
		result: dict[str, list[Connection]] = {}
		autoIfaces: set = set()
		wakeOnWiFiIfaces: set = set()
		current: Connection | None = None
		disabled = False
		inetSet: set[int] = set()  # Id(conn) for connections that have had inet (IPv4) stanza set.
		for raw in self.raw:
			line = raw.strip()
			if line.startswith("#"):
				inner = line[1:].strip()
				tokens_inner = inner.split()
				first = tokens_inner[0] if tokens_inner else ""
				if first in self._stanzaKw:
					line = inner
					disabled = True
				elif len(tokens_inner) >= 3 and tokens_inner[0] == "Only" and tokens_inner[1] == "WakeOnWiFi":
					wakeOnWiFiIfaces.add(tokens_inner[2])
					continue
				else:
					disabled = False
					continue
			else:
				disabled = False
			tokens = line.split()
			if not tokens:
				continue
			kw = tokens[0]
			if kw in ("auto", "allow-auto", "allow-hotplug") and len(tokens) >= 2:
				if not disabled:
					for iface in tokens[1:]:
						autoIfaces.add(iface)
				continue
			if kw == "iface" and len(tokens) >= 4:
				iface = tokens[1]
				inet = tokens[2]
				mode = tokens[3]
				if iface == "lo":
					current = None
					continue
				if inet == "inet6":
					# A commented-out "# iface ... inet6 dhcp" means IPv6 is not
					# configured. Treat it as absent instead of upgrading ipMode,
					# otherwise a disabled ipv6 stanza would come back enabled.
					if disabled:
						continue
					# IPv6 stanza, update the existing Connection for this iface,
					# do NOT create a second one.
					existing = result.get(iface, [])
					if existing:
						# 0 (IPv4 only) -> 2 (both), 1 (IPv6 placeholder) stays 1.
						existing[-1].ipMode = 2 if existing[-1].ipMode == 0 else existing[-1].ipMode
						existing[-1].ipv6Dhcp = mode == "dhcp"
						current = existing[-1]
					# If no inet stanza seen yet, create a placeholder Connection
					# (inet stanza may follow later in the file – rare but valid).
					else:
						conn = Connection(
							adapter=iface,
							name=iface,
							dhcp=True,
							ipMode=1,
							ipv6Dhcp=mode == "dhcp",
							enabled=not disabled,
							wifi=WiFiConfig() if isWirelessName(iface) else None,
						)
						result.setdefault(iface, []).append(conn)
						current = conn
					continue
				# Inet (IPv4) stanza – this is the primary Connection record.
				existing = result.get(iface, [])
				if existing and id(existing[-1]) not in inetSet:
					# Update the inet6-only placeholder with IPv4 data -> now both.
					conn = existing[-1]
					conn.ipMode = 2
				else:
					# No existing connection, or existing one already has inet data
					# (second block for the same iface) -> create a new Connection.
					conn = Connection(
						adapter=iface,
						name=iface,
						dhcp=True,
						ipMode=0,
						ipv6Dhcp=False,
						enabled=not disabled,
						wifi=WiFiConfig() if isWirelessName(iface) else None,
					)
					result.setdefault(iface, []).append(conn)
				conn.dhcp = mode == "dhcp"
				conn.enabled = not disabled
				inetSet.add(id(conn))
				current = conn
				continue
			if current is None:
				continue
			if kw == "address" and len(tokens) >= 2:
				current.ip = parseIp4(tokens[1])
			elif kw == "netmask" and len(tokens) >= 2:
				current.netmask = parseIp4(tokens[1])
			elif kw == "gateway" and len(tokens) >= 2:
				current.gateway = parseIp4(tokens[1])
			elif kw == "dns-nameservers":
				for tok in tokens[1:]:
					ip = parseIp4(tok)
					if ip:
						current.dnsServers.append(ip)
			elif kw in ("pre-up", "pre-down", "post-up", "post-down", "up", "down"):
				current.extraLines.append(raw.strip())
		return result, autoIfaces, wakeOnWiFiIfaces

	def serialize(self, connectionsByAdapter: dict[str, list[Connection]], adapterEnabledMap: dict[str, bool] | None = None) -> list[str]:
		lines: list[str] = list(self._header)
		lines.append("")
		lines.append("auto lo")
		lines.append("iface lo inet loopback")
		lines.append("")
		for interface in sorted(connectionsByAdapter):
			adapterEnabled = (adapterEnabledMap or {}).get(interface, False)
			for connection in connectionsByAdapter[interface]:
				lines.extend(serializeConnection(connection, adapterEnabled))
				lines.append("")
		return lines

	def save(self, connectionsByAdapter: dict[str, list[Connection]], adapterEnabledMap: dict[str, bool] | None = None) -> bool:
		lines = self.serialize(connectionsByAdapter, adapterEnabledMap)
		if exists(self.writePath):
			try:
				copy2(self.writePath, self.writePath + ".bak")
			except OSError as err:
				print(f"[NetworkManager] Error {err.errno}: Cannot backup '{self.writePath}'!  ({err.strerror})")

		status = fileWriteLines(self.writePath, lines, source=MODULE_NAME)
		if status:
			self.raw = lines
		return bool(status)


# Serializes one Connection to interfaces-file lines.
def serializeConnection(conn: Connection, adapterEnabled: bool) -> list[str]:
	lines: list[str] = []
	connectionPrefix = "" if conn.enabled else "# "
	lines.append(f"# Only WakeOnWiFi {conn.adapter}" if conn.wakeOnWiFi else f"{"" if adapterEnabled else "# "}auto {conn.adapter}")
	hasIpv4 = conn.ipMode in (0, 2)
	hasIpv6 = conn.ipMode in (1, 2)
	lines.append(f"iface {conn.adapter} inet6 dhcp" if hasIpv6 and conn.enabled else f"# iface {conn.adapter} inet6 dhcp")
	if hasIpv4:
		if conn.dhcp:
			lines.append(f"{connectionPrefix}iface {conn.adapter} inet dhcp")
		else:
			lines.append(f"{connectionPrefix}iface {conn.adapter} inet static")
			lines.append(f"{connectionPrefix}\thostname $(hostname)")
			lines.append(f"{connectionPrefix}\taddress {conn.ipStr()}")
			lines.append(f"{connectionPrefix}\tnetmask {conn.netmaskStr()}")
			if conn.gateway != [0, 0, 0, 0]:
				lines.append(f"{connectionPrefix}\tgateway {conn.gatewayStr()}")
	else:
		lines.append(f"# iface {conn.adapter} inet dhcp")
	if conn.dnsServers:
		serversText = " ".join(".".join(str(octet) for octet in x) if isinstance(x, list) else x for x in conn.dnsServers)
		lines.append(f"{connectionPrefix}\tdns-nameservers {serversText}")
	for extra in conn.extraLines:
		lines.append(f"{connectionPrefix}\t{extra}")
	return lines


# Parser and writer for /etc/wpa_supplicant.<iface>.conf.
class WpaSupplicantFile:
	WPA_DEFAULT_HEADER = [
		"ctrl_interface=/var/run/wpa_supplicant",
		"update_config=1",
		"",
	]

	def __init__(self, iface: str):
		self.iface = iface
		self.path = f"{wpaSupplicantDir}/wpa_supplicant.{iface}.conf"
		self.writePath = self.path
		self.raw = fileReadLines(self.path, default=[], source=MODULE_NAME)
		self.header: list[str] = self.extractHeader()

	def exists(self) -> bool:
		return exists(self.path)

	def extractHeader(self) -> list[str]:
		header: list[str] = []
		for line in self.raw:
			if line.strip().startswith("network"):
				break
			header.append(line)
		return header

	def parse(self) -> list[WiFiConfig]:
		configs: list[WiFiConfig] = []
		current: dict[str, str] | None = None
		depth = 0
		blockId = 0
		for line in self.raw:
			stripped = line.strip()
			if stripped.startswith("#"):
				continue
			if stripped.startswith("network") and "{" in stripped:
				current = {}
				depth = stripped.count("{") - stripped.count("}")
				continue
			if current is None:
				continue
			depth += stripped.count("{") - stripped.count("}")
			if "=" in stripped and depth > 0:
				key, sep, value = stripped.partition("=")
				current[key.strip()] = value.strip().strip('"')
			if depth <= 0 and current is not None:
				wifi = wpaDictToWiFiConfig(current, blockId)
				if wifi.ssid:
					configs.append(wifi)
				blockId += 1
				current = None
				depth = 0
		return configs

	def serialize(self, configs: list[WiFiConfig]) -> list[str]:
		header = self.header if self.header else list(self.WPA_DEFAULT_HEADER)
		lines: list[str] = list(header)
		if lines and lines[-1].strip():
			lines.append("")
		for wifi in configs:
			lines.extend(wifiConfigToWpaBlock(wifi))
			lines.append("")
		return lines

	def save(self, configs: list[WiFiConfig]) -> bool:
		if exists(self.writePath):
			try:
				copy2(self.writePath, self.writePath + ".bak")
			except OSError as err:
				print(f"[NetworkManager] Error {err.errno}: Cannot backup '{self.writePath}'!  ({err.strerror})")

		return bool(fileWriteLines(self.writePath, self.serialize(configs), source=MODULE_NAME))

	def ensureDir(self):
		makedirs(wpaSupplicantDir, exist_ok=True)


def wpaDictToWiFiConfig(fields: dict[str, str], blockId: int) -> WiFiConfig:
	keyMgmt = fields.get("key_mgmt", "NONE").upper()
	proto = fields.get("proto", "").upper()
	pairwise = fields.get("pairwise", "").upper()
	if keyMgmt == "NONE":
		enc = Encryption.NONE if not fields.get("wep_key0") else Encryption.WEP
	elif "SAE" in keyMgmt:
		enc = Encryption.WPA3
	elif "WPA" in keyMgmt:
		enc = Encryption.WPA2 if ("CCMP" in pairwise or "WPA2" in proto or "RSN" in proto) else Encryption.WPA
	else:
		enc = Encryption.NONE
	try:
		priority = int(fields.get("priority", "0"))
	except ValueError:
		priority = 0
	return WiFiConfig(
		ssid=fields.get("ssid", ""),
		hidden=fields.get("scan_ssid", "0") == "1",
		encryption=enc,
		key=fields.get("psk", fields.get("wep_key0", "")),
		bgscan=fields.get("bgscan", "simple:30:-70:3600"),
		wpaId=blockId,
		priority=priority,
		disabled=fields.get("disabled", "0") == "1"
	)


def wifiConfigToWpaBlock(wifi: WiFiConfig) -> list[str]:
	lines = ["network={"]
	lines.append(f'\tssid="{wifi.ssid}"')
	if wifi.hidden:
		lines.append("\tscan_ssid=1")
	lines.append(f"\tpriority={wifi.priority}")
	if wifi.bgscan:
		lines.append(f'\tbgscan="{wifi.bgscan}"')
	match wifi.encryption:
		case Encryption.NONE:
			lines.append("\tkey_mgmt=NONE")
		case Encryption.WEP:
			lines.append("\tkey_mgmt=NONE")
			lines.append(f"\twep_key0={wifi.key}" if wifi.wepKeyType == "HEX" else f"\twep_key0=\"{wifi.key}\"")
			lines.append("\twep_tx_keyidx=0")
		case Encryption.WPA:
			lines.append("\tkey_mgmt=WPA-PSK")
			lines.append("\tproto=WPA")
			lines.append(f'\tpsk="{wifi.key}"')
		case Encryption.WPA2 | Encryption.WPA_WPA2:
			lines.append("\tkey_mgmt=WPA-PSK")
			lines.append("\tproto=RSN")
			lines.append(f'\tpsk="{wifi.key}"')
		case Encryption.WPA3:
			lines.append("\tkey_mgmt=SAE")
			lines.append("\tproto=RSN")
			lines.append(f'\tpsk="{wifi.key}"')
	if wifi.disabled:
		lines.append("\tdisabled=1")
	lines.append("}")
	return lines


# Read and write /etc/resolv.conf + /etc/enigma2/nameserversdns.conf.
class NameserverFiles:
	RE_NS4 = compile(r"nameserver\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
	RE_NS6 = compile(r"nameserver\s+(([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4})")

	def load(self, ns: NameserverConfig):
		path = resolvFile if ns.mode == "dhcp-router" else nameserverFile
		ns.servers = self.parse(path)

	def parse(self, path: str) -> list:
		servers: list = []
		for line in fileReadLines(path, default=[], source=MODULE_NAME):
			m4 = self.RE_NS4.match(line.strip())
			if m4:
				servers.append([int(x) for x in m4.group(1).split(".")])
				continue
			m6 = self.RE_NS6.match(line.strip())
			if m6:
				servers.append(m6.group(1))
		return servers

	def save(self, ns: NameserverConfig, anyDhcpActive: bool):
		def build(ns: NameserverConfig) -> list[str]:
			v4 = ["nameserver " + ".".join(str(octet) for octet in x) for x in ns.servers if isinstance(x, list) and x != [0, 0, 0, 0]]
			v6 = [f"nameserver {x}" for x in ns.servers if isinstance(x, str) and x]
			match ns.ipMode:
				case 0:
					nsLines = v4 + v6
				case 1:
					nsLines = v6 + v4
				case 2:
					nsLines = v4
				case _:
					nsLines = v6
			prefix: list[str] = []
			if ns.rotate:
				prefix.append("options rotate")
			if ns.suffix:
				prefix.append(f"domain {ns.suffix}")
			return prefix + nsLines

		lines = build(ns)
		if not anyDhcpActive:
			fileWriteLines(resolvFile, lines, source=MODULE_NAME)
		if ns.mode != "dhcp-router":
			fileWriteLines(nameserverFile, lines, source=MODULE_NAME)
		elif exists(nameserverFile):
			try:
				remove(nameserverFile)
			except OSError:
				pass


# Builds shell command lists for WiFi bring-up / tear-down.
class WiFiRuntime:
	def __init__(self, adapter: Adapter):
		self.adapter = adapter

	@property
	def _iface(self) -> str:
		return self.adapter.name

	def commandsActivate(self, conn: Connection) -> list[str]:
		iface = self.adapter.name
		cmds: list[str] = []
		cmds.extend(self.commandsDeactivate())
		cmds.append(f"{ifconfigBin} {iface} up || true")
		if conn.wifi and conn.wifi.encryption != Encryption.NONE:
			cmds.append(f"{wpaSupplicantBin} -B -D {self.adapter.driverApi} -i{iface} -c{self.adapter.wpaConfPath} -P{self.adapter.wpaPidPath} || true")
		elif conn.wifi:
			ssid = conn.wifi.ssid.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
			cmds.append(f'iwconfig {iface} essid "{ssid}" || true')
		cmds.append(f"{ifupBin} {iface}")
		return cmds

	def commandsDeactivate(self) -> list[str]:
		iface = self.adapter.name
		return [
			f"{wpaCliBin} -i{iface} terminate 2>/dev/null; true",
			f"{ifdownBin} {iface} 2>/dev/null; true",
			f"ip addr flush dev {iface} scope global 2>/dev/null; true",
		]

	def statusCommands(self) -> list[str]:
		return [f"iwconfig {self.adapter.name}"]


def readNetinfoInterfaces() -> dict:
	"""Raw "interfaces" dictionary from socketdaemon's /var/run/netinfo, {} if missing/invalid."""
	try:
		with open(netinfoPath, encoding="utf-8") as fd:
			info = loads(fd.read())
	except (OSError, JSONDecodeError):
		return {}
	return info.get("interfaces", {})


def isWirelessName(iface: str) -> bool:
	return bool(match(r"(wlan|ath|ra|wl)\d+", iface))


def parseIp4(text: str) -> list[int]:
	try:
		parts = [int(x) for x in text.split(".")]
		if len(parts) != 4 and not all(0 <= x <= 255 for x in parts):
			parts = [0, 0, 0, 0]
	except (ValueError, AttributeError):
		parts = [0, 0, 0, 0]
	return parts


# Connects to /var/run/daemon_net.socket (AF_UNIX SOCK_STREAM) and reads.
class NetEventReader:
	def __init__(self, manager: NetworkManager):
		self.manager = manager
		self.sock = None
		self.buffer = b""
		self.retryTimer = None
		self.connect()

	# -- Twisted FileDescriptor interface. --

	def fileno(self) -> int:
		return self.sock.fileno() if self.sock else -1

	def doRead(self):
		try:
			data = self.sock.recv(4096)
		except OSError:
			data = b""
		if data:
			self.buffer += data
			while b"\n" in self.buffer:
				line, self.buffer = self.buffer.split(b"\n", 1)
				self.dispatch(line.decode("ascii", errors="replace").strip())
		else:
			self.disconnect()

	def connectionLost(self, failure=None):
		self.disconnect()

	def logPrefix(self) -> str:
		return "NetEventReader"

	# -- Internal. --

	def connect(self):
		try:
			sock = socket(AF_UNIX, SOCK_STREAM)
			sock.connect(netEventSocketPath)
			sock.setblocking(False)
			self.sock = sock
			reactor.addReader(self)
			print(f"[NetworkManager] NetEventReader connected to '{netEventSocketPath}'.")
		except OSError:
			self.scheduleRetry()

	def disconnect(self):
		if self.sock:
			try:
				reactor.removeReader(self)
			except Exception:
				pass
			try:
				self.sock.close()
			except OSError:
				pass
			self.sock = None
		self.scheduleRetry()

	def scheduleRetry(self):
		if self.retryTimer is not None:
			return
		self.retryTimer = eTimer()
		self.retryTimer.callback.append(self.retry)
		self.retryTimer.start(5000, True)

	def retry(self):
		self.retryTimer = None
		self.connect()

	def dispatch(self, line: str):
		if not line:
			return
		self.manager.log(f"NetEventReader: Received {line!r}.")
		parts = line.split(",")
		evt = parts[0]
		if evt == "UPDATE":
			self.manager.onNetinfoUpdate()
		elif evt == "LINK" and len(parts) == 4:
			self.manager.onLinkChange(parts[1], parts[2] == "up", parts[3] == "up")
		elif evt == "IP" and len(parts) == 3:
			self.manager.onIpChange(parts[1], parts[2])
		elif evt == "IFACE_ADD" and len(parts) == 2:
			self.manager.onIfaceAdd(parts[1])
		elif evt == "IFACE_REMOVE" and len(parts) == 2:
			self.manager.onIfaceRemove(parts[1])
		elif evt == "SCAN_TRIGGER" and len(parts) == 2:
			self.manager.onScanTrigger(parts[1])


# The actual system-of-record for network mounts is /etc/fstab and
# /etc/auto.network, both read and written directly by this class.
# automounts.xml (the old plugin's config file) is only read, and only to
# migrate an existing old-plugin setup once - we never write to it.
# Lives here (not in Screens/NetworkMounts.py, which just displays/edits
# this data) because NetworkCheck below needs it too, to know each enabled
# fstab share's local mount point directory before "mount -a" at Enigma2
# startup - see mountPendingShares().
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

	MOUNT_BIN = "/bin/mount"

	# A disabled mount is still written to fstab/auto.network, just commented
	# out with this marker, so it survives a reload instead of vanishing -
	# those two files are the only place a mount's definition lives (see
	# above), so simply omitting a disabled entry would delete it for good.
	DISABLED_PREFIX = "#DISABLED# "

	# Username/password are stored in plaintext directly on the entry, same
	# as the old plugin did. Kept reasonably safe by chmod'ing the file 600
	# after every save() (see below).

	# Parses one /etc/fstab line into a mount dict, or None if it isn't one
	# of ours (not nfs/nfs4/cifs, or a malformed device field). Used both by
	# load() to surface every NFS/CIFS line in fstab (see mergeUnmanaged()
	# below) and by save() to recognize - and always regenerate - every such
	# line, whether or not it's still in the set being saved (see
	# writeMountFiles() below; a share that isn't in that set anymore is
	# exactly what deletion looks like, so its old line must never survive
	# just because it doesn't currently match anything).
	def parseFstabLine(self, line):
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
		# shareName must match the mountpoint's own basename, not a guess
		# off remotePath - mountPointFor() reconstructs the path as
		# /media/net/<shareName>, so getting this wrong here silently
		# points isMounted()/save() at a different directory than the one
		# actually configured in this very fstab line.
		shareName = mountpoint.rstrip("/").rsplit("/", 1)[-1] or remotePath.rstrip("/").rsplit("/", 1)[-1] or "MEDIA"
		return {
			"id": f"fstab:{protocol}:{server}:{remotePath}",
			"mode": "fstab",
			"protocol": protocol,
			"enabled": enabled,
			"hddReplacement": mountpoint.rstrip("/") == "/media/hdd",
			"shareName": shareName,
			"server": server,
			"remotePath": remotePath,
			"unmanaged": True,
			**self.splitOptions(options, protocol),
		}

	# Same as parseFstabLine() above, but for /etc/auto.network lines.
	def parseAutoNetworkLine(self, line):
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
			"unmanaged": True,
			**self.splitOptions(options, protocol),
		}

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
					"unmanaged": True,
					**self.splitOptions(text("options", "rw,nolock,tcp,utf8" if protocol == "nfs" else "rw,utf8"), protocol),
				}
				if protocol == "cifs":
					# The old format stored these in their own tags, not
					# embedded in "options" - they take priority over
					# anything splitOptions() might've pulled out above.
					mount["username"] = text("username", "guest")
					mount["password"] = text("password")
				return mount

			mounts = []
			for protocol in self.PROTOCOLS:
				for protoNode in node.findall(protocol):
					for mountNode in protoNode.findall("mount"):
						mounts.append(readMount(mountNode, wrapperMode, protocol))
			return mounts

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
		mergeUnmanaged(mounts, self.FSTAB_PATH, self.parseFstabLine)
		mergeUnmanaged(mounts, self.AUTO_NETWORK_PATH, self.parseAutoNetworkLine)
		return mounts

	def save(self, mounts):
		def writeMountFiles(effective):
			# A line surviving here isn't decided by whether it currently
			# matches something in "effective" - that set never contains a
			# just-deleted share, so its old line would never match and would
			# be kept forever. Instead: any line that parses as one of ours
			# (parseFstabLine()/parseAutoNetworkLine() - same ones load() uses
			# to discover unmanaged NFS/CIFS lines) is always dropped here and
			# only re-added below if it's still in "effective". A line that
			# doesn't parse at all (/boot, swap, an unrelated manual mount, …)
			# is left untouched either way.
			autoNetworkLines = [line for line in fileReadLines(self.AUTO_NETWORK_PATH, default=[], source=MODULE_NAME)
				if self.parseAutoNetworkLine(line) is None]
			fstabLines = [line for line in fileReadLines(self.FSTAB_PATH, default=[], source=MODULE_NAME)
				if self.parseFstabLine(line) is None]
			for mount, mode in effective:
				prefix = "" if mount.get("enabled") else self.DISABLED_PREFIX
				protocol = mount.get("protocol") or "nfs"
				server = mount.get("server") or ""
				remotePath = mount.get("remotePath") or ""
				shareName = mount.get("shareName") or ""
				if mode == "autofs":
					if protocol == "nfs":
						autoNetworkLines.append(f"{prefix}{shareName} -fstype=nfs,{self.buildNfsOptions(mount)} {server}:/{remotePath}")
					else:
						username = (mount.get("username") or "").replace(" ", "\\ ")
						password = (mount.get("password") or "").replace(" ", "\\ ")
						autoNetworkLines.append(f"{prefix}{shareName} -fstype=cifs,user={username},pass={password},{self.sanitizeOptions(mount)} ://{server}/{remotePath}")
				elif mode == "fstab":
					path = self.mountPointFor(mount)
					if protocol == "nfs":
						fstabLines.append(f"{prefix}{server}:/{remotePath}\t{path}\tnfs\t_netdev,{self.buildNfsOptions(mount)}\t0 0")
					else:
						username = mount.get("username") or ""
						password = mount.get("password") or ""
						fstabLines.append(f"{prefix}//{server}/{remotePath}\t{path}\tcifs\tuser={username},pass={password},_netdev,{self.sanitizeOptions(mount)}\t0 0")

			print("[NetworkMountRepository] autoNetworkLines:", autoNetworkLines)
			print("[NetworkMountRepository] fstabLines:", fstabLines)
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
	CIFS_RESERVED_OPTION_KEYS = frozenset(("user", "username", "pass", "password", "ro", "rw"))

	# proto=tcp and _netdev are always added by save() itself (see
	# buildNfsOptions()/writeMountFiles()), never something the user typed -
	# drop them rather than showing them back as "extra" options.
	ALWAYS_IMPLIED_OPTION_KEYS = frozenset(("proto", "_netdev"))

	# Splits a raw options string - as read back from an existing fstab/
	# auto.network line or automounts.xml - into the structured per-field
	# values NetworkMountSetup exposes, plus whatever's left over for the
	# free-text "Mount options" field. Without this, re-editing an existing
	# mount would show every dedicated setting a second time in "Mount
	# options", since the file only ever stores one combined string.
	@classmethod
	def splitOptions(cls, rawOptions, protocol):
		tokens = [token.strip() for token in (rawOptions or "").split(",") if token.strip()]
		extra = []
		if protocol == "nfs":
			fields = {"accessMode": "rw", "nfsLocking": True, "nfsVersion": "", "nfsRsize": "0", "nfsWsize": "0", "nfsTimeo": 0, "nfsSoft": False}
			for token in tokens:
				parts = token.split("=", 1)
				key = parts[0].strip().lower()
				value = parts[1].strip() if len(parts) > 1 else ""
				if key == "ro":
					fields["accessMode"] = "ro"
				elif key == "rw":
					fields["accessMode"] = "rw"
				elif key == "nolock":
					fields["nfsLocking"] = False
				elif key == "lock":
					fields["nfsLocking"] = True
				elif key == "nfsvers":
					fields["nfsVersion"] = value
				elif key == "rsize":
					fields["nfsRsize"] = value
				elif key == "wsize":
					fields["nfsWsize"] = value
				elif key == "timeo":
					fields["nfsTimeo"] = int(value) if value.isdigit() else 0
				elif key == "soft":
					fields["nfsSoft"] = True
				elif key == "hard":
					fields["nfsSoft"] = False
				elif key in cls.ALWAYS_IMPLIED_OPTION_KEYS:
					pass
				else:
					extra.append(token)
		else:
			fields = {"username": "", "password": "", "accessMode": "rw"}
			for token in tokens:
				parts = token.split("=", 1)
				key = parts[0].strip().lower()
				value = parts[1].strip() if len(parts) > 1 else ""
				if key in ("user", "username"):
					fields["username"] = value
				elif key in ("pass", "password"):
					fields["password"] = value
				elif key == "ro":
					fields["accessMode"] = "ro"
				elif key == "rw":
					fields["accessMode"] = "rw"
				elif key == "iocharset" and value == "utf8":
					pass
				elif key in cls.ALWAYS_IMPLIED_OPTION_KEYS:
					pass
				else:
					extra.append(token)
		fields["options"] = ",".join(extra)
		return fields

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
	def sanitizeOptions(mount):
		parts = [mount.get("accessMode") or "rw"]
		extra = (mount.get("options") or "").strip().replace("utf8", "iocharset=utf8")
		if extra:
			parts.append(extra)
		return ",".join(parts)

	# Builds the actual mount.nfs/autofs option string from the structured
	# per-mount fields NetworkMountSetup exposes (rw/ro, locking, nfsVersion,
	# rsize, wsize, timeo). proto=tcp is always added - NFS over UDP isn't
	# offered as an option. Anything the user still put in the free-text
	# "options" field is appended last, for anything not covered by a
	# dedicated field.
	def buildNfsOptions(self, mount):
		parts = ["ro" if mount.get("accessMode") == "ro" else "rw"]
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

	def ensureMountPoint(self, mount):
		if mount.get("mode") == "fstab":
			mountPoint = self.mountPointFor(mount)
			if not exists(mountPoint):
				print(f"[NetworkManager] ensureMountPoint create dir '{mountPoint}'")
				makedirs(mountPoint, exist_ok=True)

	# Builds the argv for a manual "mount -t <protocol> <source> <mountPoint>
	# -o <options>" call, creating the mount point directory first if it
	# doesn't exist yet. Shared by the interactive manual mount action
	# (NetworkMountsOverview.keyYellow()) and the startup pass that mounts
	# any enabled fstab share still missing once the network is up
	# (NetworkCheck.mountPendingShares()) - one place building the command
	# instead of two copies drifting apart.
	def buildMountCommand(self, mount):
		mountPoint = self.mountPointFor(mount)
		self.ensureMountPoint(mount)
		protocol = mount.get("protocol") or "nfs"
		server = mount.get("server") or ""
		remotePath = mount.get("remotePath") or ""
		if protocol == "nfs":
			source = f"{server}:/{remotePath}"
			options = self.buildNfsOptions(mount)
		else:
			username = mount.get("username") or ""
			password = mount.get("password") or ""
			source = f"//{server}/{remotePath}"
			options = f"user={username},pass={password},{self.sanitizeOptions(mount)}"
		return (self.MOUNT_BIN, self.MOUNT_BIN, "-t", protocol, source, mountPoint, "-o", options), mountPoint

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


# Polls up to 10x (1s apart) until the hostname resolves off 127.0.0.1, then
# runs "mount -a" to pick up any fstab share that couldn't mount before the
# network was up, and rescans network mounts into the harddiskmanager.
class NetworkCheck:
	MOUNT_BIN = "/bin/mount"

	def __init__(self):
		self.timer = eTimer()
		self.timer.callback.append(self.check)
		self.retry = 0
		self.console = Console()

	def start(self):
		self.retry = 10
		self.timer.start(1000, True)

	def check(self):
		self.timer.stop()
		if self.retry <= 0:
			return
		try:
			if gethostbyname(gethostname()) != "127.0.0.1":
				print("[NetworkManager] NetworkCheck: Done.")
				self.mountPendingShares()
				return
			self.retry -= 1
			self.timer.start(1000, True)
		except Exception as err:
			print(f"[NetworkManager] NetworkCheck: Error {err}!")

	def mountPendingShares(self):
		repository = NetworkMountRepository()
		mounts = repository.load()
		known = {mount.get("shareName") for mount in mounts if mount.get("mode") == "fstab" and not mount.get("hddReplacement")}
		self.removeOrphanedMountPoints(known)

		pending = False
		for mount in mounts:
			if mount.get("mode") == "fstab" and mount.get("enabled") and not repository.isMounted(mount):
				pending = True
				repository.ensureMountPoint(mount)

		if not pending:
			harddiskmanager.enumerateNetworkMounts(refresh=True)
			return

		def done(data, retVal, extra=None):
			if retVal:
				print(f"[NetworkManager] NetworkCheck: 'mount -a' finished with errors, retVal={retVal}, output={data!r}")
			harddiskmanager.enumerateNetworkMounts(refresh=True)

		self.console.ePopen((self.MOUNT_BIN, self.MOUNT_BIN, "-a"), done)

	def removeOrphanedMountPoints(self, knownShareNames):
		base = "/media/net"
		if isdir(base):
			for name in listdir(base):
				if name not in knownShareNames:
					path = f"{base}/{name}"
					if not isdir(path) or ismount(path):
						continue
					try:
						rmdir(path)
						print(f"[NetworkManager] NetworkCheck: removed orphaned mount point {path!r}")
					except OSError as err:
						print(f"[NetworkManager] NetworkCheck: could not remove orphaned mount point {path!r}: {err}")


# mDNS/DNS-SD discovery for SMB/NFS hosts (NetworkMounts). Not started
# automatically, only on demand by whoever needs SMB/NFS discovery.
class AvahiProvider:
	def __init__(self):
		self.typeToProtocol = {"_smb._tcp": "smb", "_nfs._tcp": "nfs"}
		self.serviceTypes = tuple(self.typeToProtocol)
		self.browser = None
		self.started = False
		self.onObservation: list[Callable] = []

	def start(self):
		if not self.started:
			self.browser = eNetworkServiceBrowser()
			for serviceType in self.serviceTypes:
				self.browser.addServiceType(serviceType)
			self.browser.changed.get().append(self.changed)
			self.browser.start()
			self.started = True

	def stop(self):
		if self.started:
			self.browser.changed.get().remove(self.changed)
			self.browser.stop()
			self.browser = None
			self.started = False

	def changed(self):
		# changed carries no payload - re-read the full snapshot and
		# re-dispatch it (cheap: an in-memory list, not a network round-trip).
		for entry in self.browser.getServices():
			self.dispatch(entry)

	def dispatch(self, entry: dict):
		# entry["protocol"] is the IP address family ("inet"/"inet6"), not
		# the share protocol - keep it under a different key so it doesn't
		# collide with our own "protocol" (smb/nfs).
		networkManager.log(f"AvahiProvider: found {entry["name"]} / {entry["hostname"]}")
		observation = {
			"source": "avahi",
			"protocol": self.typeToProtocol.get(entry["type"], entry["type"]),
			"name": entry["name"],
			"hostname": entry["hostname"],
			"addresses": entry["addresses"],
			"addressFamily": entry["protocol"],
			"port": entry["port"],
			"interface": entry["interface"],
			"domain": entry["domain"],
			"txt": entry["txt"],
		}
		for callback in self.onObservation:
			callback(observation)


# Discovers SMB (445) / NFS (2049) hosts that don't speak mDNS, by reading /var/run/netscan
class NetscanProvider:
	PORTS = {445: "smb", 2049: "nfs"}

	def __init__(self):
		self.started = False
		self.onObservation: list[Callable] = []  # callback(observation) - one per {address, port}

	# dispatchAll() just re-reads a local file (cheap), unlike an actual
	# rescan() - always re-dispatch on start() so a screen opening after the
	# one-shot boot pass (StartEnigma.py) sees whatever socketdaemon's
	# unattended autoscan has since written, instead of replaying whatever
	# was (or wasn't) in the file at that first, possibly-too-early read.
	def start(self):
		self.started = True
		self.dispatchAll()

	def stop(self):
		self.started = False

	@staticmethod
	def defaultRouteCidr() -> str | None:
		for iface in readNetinfoInterfaces().values():
			if iface.get("defgw") and iface.get("ip4") and iface.get("prefix4") is not None:
				return f"{iface['ip4']}/{iface['prefix4']}"
		return None

	def rescan(self, callback: Callable | None = None):
		cidr = self.defaultRouteCidr()
		if not cidr:
			networkManager.log("NetscanProvider: rescan: no default-route interface with an IPv4 address.")
			if callback:
				callback(False)
			return

		def done(exitCode):
			ok = exitCode == 0
			if ok:
				self.dispatchAll()
			if callback:
				callback(ok)

		ServiceAction.netscan(cidr, list(self.PORTS), done)

	def dispatchAll(self):
		try:
			with open(netscanPath, encoding="utf-8") as fd:
				info = loads(fd.read())
		except (OSError, JSONDecodeError):
			info = {}
		for entry in info.get("scan", []):
			self.dispatch(entry)

	def dispatch(self, entry: dict):
		protocol = self.PORTS.get(entry.get("port"))
		if protocol:
			observation = {
				"source": "netscan",
				"protocol": protocol,
				"address": entry.get("address"),
				"hostname": entry.get("hostname") or "",
			}
			for callback in self.onObservation:
				callback(observation)


# Owns discovery end to end: hosts, a plain {address: host} dict, host =
# {"address", "hostname", "protocols" (set, e.g. {"smb", "nfs"}), "source"
# ("avahi" | "netscan"), "avahiShares"}. Kept deliberately simple, no
# per-candidate state-tracking (see git history for a previous, "clever"
# delayed-probe design that got too hard to follow).
#   - Avahi always wins "source" and merges in protocol, even over an
#     existing netscan entry.
#   - hostname is the exception: a real netscan hostname (reverse-DNS,
#     already ISP-wildcard-filtered in socketdaemon) always wins over
#     Avahi's regardless of arrival order - hostnameSource tracks which one
#     set it last so this stays correct either way.
# Runs one bounded pass per boot (DEFAULT_RUN_MS), auto-stopping - a
# Discovery screen can call start()/stop() itself later for on-demand live.
class DiscoveryManager:
	DEFAULT_RUN_MS = 30000   # one discovery pass per boot runs this long, then auto-stops

	def __init__(self):
		self.started = False
		self.hosts = {}
		self.onChanged: list[Callable] = []  # callback() - no payload, re-read self.hosts
		self.avahi = AvahiProvider()
		self.netscan = NetscanProvider()
		self.avahi.onObservation.append(self.onAvahiObservation)
		self.netscan.onObservation.append(self.onNetscanObservation)
		self.stopTimer = eTimer()
		self.stopTimer.callback.append(self.stop)

	# No early return on self.started - a caller wanting an unbounded scan
	# (runMs=None) must be able to cancel an already-running bounded pass's
	# auto-stop, not just no-op. provider.start() is idempotent anyway.
	# self.started must already be True before either provider.start() runs -
	# netscan.start() dispatches /var/run/netscan synchronously, and
	# onNetscanObservation() below drops observations while not started, so
	# setting the flag afterwards silently lost that first, synchronous batch.
	def start(self, runMs: int | None = DEFAULT_RUN_MS):
		self.started = True
		self.avahi.start()
		self.netscan.start()  # synchronous dispatchAll() - notify once now that it's fully in, not once per entry (see onNetscanObservation())
		self.notify()
		self.stopTimer.stop()
		if runMs:
			self.stopTimer.start(runMs, True)

	def stop(self):
		self.stopTimer.stop()
		if self.started:
			self.avahi.stop()
			self.netscan.stop()
			self.started = False

	# Never clears hosts up front - a rescan can take a few seconds (active
	# TCP connect-scan), and blanking self.hosts before it completes would
	# make already-known netscan hosts disappear from the list for that
	# whole window. Only prunes at the very end, once the fresh scan is in,
	# and only netscan-sourced addresses that didn't reappear in this pass -
	# avahi-sourced hosts are never touched here.
	def rescan(self, callback: Callable | None = None):
		before = {address for address, host in self.hosts.items() if host["source"] == "netscan"}
		seen = set()

		def onObservationDuringRescan(observation):
			address = observation.get("address")
			if address:
				seen.add(address)

		self.netscan.onObservation.append(onObservationDuringRescan)

		def done(ok):
			self.netscan.onObservation.remove(onObservationDuringRescan)
			if ok:
				for address in before - seen:
					host = self.hosts.get(address)
					if host and host["source"] == "netscan":
						del self.hosts[address]
				self.notify()
			if callback:
				callback(ok)

		self.netscan.rescan(done)

	@staticmethod
	def newHost(address, source):
		return {"address": address, "hostname": "", "hostnameSource": None, "protocols": set(), "source": source, "avahiShares": {}}

	# Some NAS vendors (confirmed: Synology) register one _nfs._tcp/_smb._tcp
	# service INSTANCE PER EXPORT/SHARE instead of one per host, encoding the
	# share name in the instance name, e.g. "nas1 - NFS [Disk4]". This is not
	# a standard, just a convention worth trying: if the name ends in
	# "[...]", use the bracketed part as the share name, else fall back to
	# the raw name. Keyed by full name in avahiShares to naturally dedupe
	# repeat ADD events for the same instance.
	@staticmethod
	def parseAvahiShareName(name):
		if name.endswith("]") and "[" in name:
			return name[name.rindex("[") + 1:-1]
		return name

	# changed() (AvahiProvider) re-dispatches its *entire* current snapshot on
	# every single underlying ADD/REMOVE, so most observations here just
	# repeat a host we already know unchanged - only notify if something in
	# self.hosts actually ends up different, not on every re-dispatch.
	def onAvahiObservation(self, observation):
		protocol = observation.get("protocol")
		hostname = observation.get("hostname") or ""
		name = observation.get("name") or ""
		changed = False
		for address in observation.get("addresses") or []:
			host = self.hosts.get(address)
			if host is None:
				host = self.hosts[address] = self.newHost(address, "avahi")
				changed = True
			if host["source"] != "avahi":
				host["source"] = "avahi"  # always leading, even if a netscan entry already existed
				changed = True
			if hostname and host["hostnameSource"] != "netscan" and (host["hostname"] != hostname or host["hostnameSource"] != "avahi"):
				host["hostname"] = hostname
				host["hostnameSource"] = "avahi"
				changed = True
			if protocol:
				if protocol not in host["protocols"]:
					host["protocols"].add(protocol)
					changed = True
				if protocol in ("nfs", "smb") and name:
					share = {"protocol": protocol, "name": self.parseAvahiShareName(name), "fullName": name}
					if host["avahiShares"].get(name) != share:
						host["avahiShares"][name] = share
						changed = True
		if changed:
			self.notify()

	# No self.notify() here, deliberately - a netscan dispatch is always a
	# full batch of entries (dispatchAll()), not one observation at a time,
	# so notifying per-entry would fire onChanged many times for what's
	# conceptually a single update. Callers notify once the batch is fully
	# in instead - see start() and rescan()'s done() above.
	def onNetscanObservation(self, observation):
		if self.started:
			address = observation.get("address")
			if address:
				# Never downgrade an "avahi" entry's source - hostname still takes
				# priority for netscan though, see class comment.
				host = self.hosts.setdefault(address, self.newHost(address, "netscan"))
				if host["source"] != "avahi":
					host["source"] = "netscan"
				hostname = observation.get("hostname")
				if hostname:
					host["hostname"] = hostname
					host["hostnameSource"] = "netscan"
				host["protocols"].add(observation["protocol"])

	def notify(self):
		for callback in self.onChanged:
			callback()


discoveryManager = DiscoveryManager()
networkManager = NetworkManager()

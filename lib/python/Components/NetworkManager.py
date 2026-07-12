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
import json
from os import listdir, makedirs, remove
from os.path import basename, exists, isdir, realpath
from re import compile, match
from shutil import copy2
import socket
from subprocess import check_output, DEVNULL
from collections.abc import Callable
from twisted.internet import reactor

from enigma import eTimer

from Components.config import config
from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Components.PluginComponent import plugins
from Components.SystemInfo import BoxInfo
from Plugins.Plugin import PluginDescriptor
from Tools.Directories import fileReadLine, fileWriteLine, fileWriteLines
from Tools.ServiceAction import ServiceAction

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

interfacesFile = "/etc/network/interfaces"
resolvFile = "/etc/resolv.conf"
nameserverFile = "/etc/enigma2/nameserversdns.conf"
wpaSupplicantDir = "/etc"
sysfsNet = "/sys/class/net"
procNetWireless = "/proc/net/wireless"
wlConfigScript = "/usr/sbin/wl-config.sh"
ifconfigBin = "/sbin/ifconfig"
ifupBin = "/sbin/ifup"
ifdownBin = "/sbin/ifdown"
wpaSupplicantBin = "/usr/sbin/wpa_supplicant"
wpaCliBin = "/usr/sbin/wpa_cli"
socketDaemonPath = "/var/run/daemon.socket"
netEventSocketPath = "/var/run/daemon_net.socket"
netinfoPath = "/var/run/netinfo"
netrestarterBin = "/usr/sbin/netrestarter"

# Linux kernel ETHTOOL_ADVERTISED_* bitmask values, used by some drivers to
# force a specific link speed/duplex instead of auto-negotiation.


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Encryption constants
# Old plugin used "Unencrypted" / "WPA/WPA2" – mapped on load, never stored.
# ---------------------------------------------------------------------------

encNone = "none"
encWep = "wep"
encWpa = "wpa"
encWpa2 = "wpa2"
encWpaWpa2 = "wpa+wpa2"   # legacy combined mode → stored as wpa2 in wpa_supplicant
encWpa3 = "wpa3"

# Deferred via lambda so translation happens at display time, not import time.
encryptionLabels = {
	encNone: lambda: _("None"),
	encWep: lambda: "WEP",
	encWpa: lambda: "WPA",
	encWpa2: lambda: "WPA2",
	encWpaWpa2: lambda: "WPA/WPA2",
	encWpa3: lambda: "WPA3"
}

# Driver-API identifiers
apiNl80211 = "nl80211"
apiWext = "wext"
apiMadwifi = "madwifi"
apiRalink = "ralink"
apiZydas = "zydas"
apiBrcmWl = "brcm-wl"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass
class WiFiConfig:
	"""WLAN-specific parameters for one Connection."""

	ssid: str = ""
	hidden: bool = False
	encryption: str = encNone
	key: str = ""
	wepKeyType: str = "ASCII"    # "ASCII" | "HEX"
	wpaId: int | None = None
	disabled: bool = False  # wpa_supplicant disabled=1
	# Background scan – enables auto-roaming between known networks.
	# Format: "simple:<shortInterval>:<signalThreshold>:<longInterval>"
	# Set to "" to disable.
	bgscan: str = "simple:30:-70:3600"

	@property
	def needsKey(self) -> bool:
		return self.encryption != encNone


@dataclass
class Connection:
	"""Logical network configuration attached to one physical Adapter."""

	adapter: str = ""
	name: str = ""
	enabled: bool = False        # False -> every line of this connection's stanza in /etc/network/interfaces is commented out with "# " (see serialiseConnection()), not just "auto <iface>"
	priority: int = 0            # higher = preferred; also wpa_supplicant priority
	dhcp: bool = True
	ip: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	netmask: list[int] = field(default_factory=lambda: [255, 255, 255, 0])
	gateway: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	ipMode: int = 0          # 0=IPv4 only, 1=IPv6 only, 2=IPv4+IPv6
	ipv6Dhcp: bool = True
	dnsServers: list = field(default_factory=list)   # [int,int,int,int] | "::addr"
	extraLines: list[str] = field(default_factory=list)
	wlan: WiFiConfig | None = None
	wakeOnWiFi: bool = False

	@property
	def isWlan(self) -> bool:
		return self.wlan is not None

	def ipStr(self) -> str:
		return ".".join(str(x) for x in self.ip)

	def netmaskStr(self) -> str:
		return ".".join(str(x) for x in self.netmask)

	def gatewayStr(self) -> str:
		return ".".join(str(x) for x in self.gateway)


@dataclass
class NetInfo:
	"""Live/kernel state for one interface – refreshed from socketdaemon's
	/var/run/netinfo JSON, sysfs and /proc/net/dev. Never persisted, held
	directly on Adapter.netInfo (a plain field, not a lookup)."""

	up: bool = False
	link: bool = False   # physical link (cable/WLAN association)
	ip: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	netmask: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	gateway: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	bcast: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	ip6: list = field(default_factory=list)  # [{"addr": "…", "prefix": 64}, …]
	speed: int = -1        # LAN only, Mbps; -1 = unknown
	duplex: str = ""       # LAN only: "full" | "half" | ""
	port: str = ""         # LAN only: "TP" | "MII" | "FIBRE" | …
	transceiver: str = ""  # LAN only: "internal" | "external"
	autoneg: bool = False  # LAN only
	linkSupported: int = 0  # LAN only, ETHTOOL SUPPORTED_* bitmask from socketdaemon
	ssid: str = ""         # WLAN only
	bssid: str = ""        # WLAN only, AP MAC address
	freqMhz: int = 0       # WLAN only, channel frequency in MHz
	channel: int = 0       # WLAN only, channel number
	bitrateBps: int = 0    # WLAN only, TX bitrate in bps
	signal: int = 0        # WLAN only, dBm
	driver: str = ""       # kernel module name (e.g. "r8168", "mt76x2u")
	hwId: str = ""         # "VVVV:DDDD" PCI or USB vendor:product hex
	bus: str = ""          # physical bus from socketdaemon (e.g. "usb", "pci", "platform")
	rxBytes: int = 0       # /proc/net/dev counter
	txBytes: int = 0       # /proc/net/dev counter
	mtu: int = 0


@dataclass
class Adapter:
	"""Physical network interface identity/config, as discovered in
	/sys/class/net, plus its live NetInfo. Holds no Connections (see
	NetworkManager.connections) – those are linked only via adapter name."""

	name: str
	mac: str = ""
	isWlan: bool = False
	module: str = ""
	driverApi: str = apiNl80211
	canWakeOnWiFi: bool = False
	adapterEnabled: bool = False  # False -> every line of this adapter's stanza in /etc/network/interfaces is commented out with "# " (see serialiseConnection()), not just "auto <iface>"
	netInfo: NetInfo = field(default_factory=NetInfo)

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
		value = wlanMetric if self.isWlan else lanMetric
		if value not in dict(NetworkManager.ROUTE_METRIC_CHOICES):
			value = 600 if self.isWlan else 100
		return value


@dataclass
class NameserverConfig:
	"""Global DNS / nameserver configuration."""

	mode: str = "dhcp-router"
	servers: list = field(default_factory=list)
	rotate: bool = False
	suffix: str = ""
	ipMode: int = 0   # 0=v4+v6  1=v6+v4  2=v4only  3=v6only


# ===========================================================================
# File I/O helpers
# ===========================================================================

def _readLines(path: str) -> list[str]:
	try:
		with open(path, encoding="utf-8", errors="replace") as fh:
			return fh.read().splitlines()
	except OSError:
		return []


# fileWriteLines() appends "" to the given list in place before joining it,
# so a copy is passed to keep the caller's list untouched.
def _writeLines(path: str, lines: list[str], backup: bool = False) -> bool:
	if backup and exists(path):
		try:
			copy2(path, path + ".bk")
		except OSError as exc:
			print(f"[NetworkManager] Cannot backup {path}: {exc}")
	return bool(fileWriteLines(path, list(lines)))


# ===========================================================================
# /etc/network/interfaces – parser + serialiser
# ===========================================================================

class InterfacesFile:
	"""Lossless parser and writer for /etc/network/interfaces."""

	_header = [
		"# Automatically generated by Enigma2.",
		"# Do NOT change manually!",
	]
	_stanzaKw = frozenset(("auto", "allow-auto", "allow-hotplug", "iface"))

	def __init__(self, path: str = interfacesFile):
		self.path = path
		self._writePath = path
		self._raw: list[str] = []
		self.load()

	def load(self):
		self._raw = _readLines(self.path)

	# Parse /etc/network/interfaces.
	def parse(self) -> tuple[dict[str, list[Connection]], set[str]]:
		result: dict[str, list[Connection]] = {}
		autoIfaces: set = set()
		wakeOnWiFiIfaces: set = set()
		current: Connection | None = None
		disabled = False
		inetSet: set[int] = set()  # id(conn) for connections that have had inet (IPv4) stanza set

		for raw in self._raw:
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
					# configured – treat it as absent instead of upgrading ipMode,
					# otherwise a disabled ipv6 stanza would come back enabled.
					if disabled:
						continue
					# IPv6 stanza – update the existing Connection for this iface,
					# do NOT create a second one.
					existing = result.get(iface, [])
					if existing:
						# 0 (IPv4 only) → 2 (both); 1 (IPv6 placeholder) stays 1
						existing[-1].ipMode = 2 if existing[-1].ipMode == 0 else existing[-1].ipMode
						existing[-1].ipv6Dhcp = mode == "dhcp"
						current = existing[-1]
					# If no inet stanza seen yet, create a placeholder Connection
					# (inet stanza may follow later in the file – rare but valid)
					else:
						conn = Connection(
							adapter=iface,
							name=iface,
							dhcp=True,
							ipMode=1,
							ipv6Dhcp=mode == "dhcp",
							enabled=not disabled,
							wlan=WiFiConfig() if _isWirelessName(iface) else None,
						)
						result.setdefault(iface, []).append(conn)
						current = conn
					continue

				# inet (IPv4) stanza – this is the primary Connection record.
				existing = result.get(iface, [])
				if existing and id(existing[-1]) not in inetSet:
					# Update the inet6-only placeholder with IPv4 data → now both
					conn = existing[-1]
					conn.ipMode = 2
				else:
					# No existing connection, or existing one already has inet data
					# (second block for the same iface) → create a new Connection.
					conn = Connection(
						adapter=iface,
						name=iface,
						dhcp=True,
						ipMode=0,
						ipv6Dhcp=False,
						enabled=not disabled,
						wlan=WiFiConfig() if _isWirelessName(iface) else None,
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
				current.ip = _parseIp4(tokens[1])
			elif kw == "netmask" and len(tokens) >= 2:
				current.netmask = _parseIp4(tokens[1])
			elif kw == "gateway" and len(tokens) >= 2:
				current.gateway = _parseIp4(tokens[1])
			elif kw == "dns-nameservers":
				for tok in tokens[1:]:
					ip = _parseIp4(tok)
					if ip:
						current.dnsServers.append(ip)
			elif kw in ("pre-up", "pre-down", "post-up", "post-down", "up", "down"):
				current.extraLines.append(raw.strip())

		return result, autoIfaces, wakeOnWiFiIfaces

	def serialise(self, connectionsByAdapter: dict[str, list[Connection]], adapterEnabledMap: dict[str, bool] | None = None) -> list[str]:
		lines: list[str] = list(self._header)
		lines.append("")
		lines.append("auto lo")
		lines.append("iface lo inet loopback")
		lines.append("")
		for iface in sorted(connectionsByAdapter):
			adapterEnabled = (adapterEnabledMap or {}).get(iface, False)
			for conn in connectionsByAdapter[iface]:
				lines.extend(serialiseConnection(conn, adapterEnabled))
				lines.append("")
		return lines

	def save(self, connectionsByAdapter: dict[str, list[Connection]], adapterEnabledMap: dict[str, bool] | None = None) -> bool:
		lines = self.serialise(connectionsByAdapter, adapterEnabledMap)
		ok = _writeLines(self._writePath, lines, backup=True)
		if ok:
			self._raw = lines
		return ok


# Serialise one Connection to interfaces-file lines.
def serialiseConnection(conn: Connection, adapterEnabled: bool) -> list[str]:
	lines: list[str] = []
	autoPfx = "" if adapterEnabled else "# "
	connPfx = "" if conn.enabled else "# "

	if conn.wakeOnWiFi:
		lines.append(f"# Only WakeOnWiFi {conn.adapter}")
	else:
		lines.append(f"{autoPfx}auto {conn.adapter}")

	hasIpv4 = conn.ipMode in (0, 2)
	hasIpv6 = conn.ipMode in (1, 2)

	if hasIpv6 and conn.enabled:
		lines.append(f"iface {conn.adapter} inet6 dhcp")
	else:
		lines.append(f"# iface {conn.adapter} inet6 dhcp")

	if hasIpv4:
		if conn.dhcp:
			lines.append(f"{connPfx}iface {conn.adapter} inet dhcp")
		else:
			lines.append(f"{connPfx}iface {conn.adapter} inet static")
			lines.append(f"{connPfx}\thostname $(hostname)")
			lines.append(f"{connPfx}\taddress {conn.ipStr()}")
			lines.append(f"{connPfx}\tnetmask {conn.netmaskStr()}")
			if conn.gateway != [0, 0, 0, 0]:
				lines.append(f"{connPfx}\tgateway {conn.gatewayStr()}")
	else:
		lines.append(f"# iface {conn.adapter} inet dhcp")

	if conn.dnsServers:
		serversStr = " ".join(
			".".join(str(octet) for octet in x) if isinstance(x, list) else x
			for x in conn.dnsServers
		)
		lines.append(f"{connPfx}\tdns-nameservers {serversStr}")

	for extra in conn.extraLines:
		lines.append(f"{connPfx}\t{extra}")

	return lines


# ===========================================================================
# wpa_supplicant.conf – parser + serialiser
# ===========================================================================

class WpaSupplicantFile:
	"""Parser and writer for /etc/wpa_supplicant.<iface>.conf."""

	WPA_DEFAULT_HEADER = [
		"ctrl_interface=/var/run/wpa_supplicant",
		"update_config=1",
		"",
	]

	def __init__(self, iface: str):
		self.iface = iface
		self.path = f"{wpaSupplicantDir}/wpa_supplicant.{iface}.conf"
		self._writePath = self.path
		self.raw: list[str] = _readLines(self.path)
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
				wlan = wpaDictToWlanConfig(current, blockId)
				if wlan.ssid:
					configs.append(wlan)
				blockId += 1
				current = None
				depth = 0

		return configs

	def serialise(self, configs: list[WiFiConfig]) -> list[str]:
		header = self.header if self.header else list(self.WPA_DEFAULT_HEADER)
		lines: list[str] = list(header)
		if lines and lines[-1].strip():
			lines.append("")
		for idx, wlan in enumerate(configs):
			lines.extend(wlanConfigToWpaBlock(wlan, idx))
			lines.append("")
		return lines

	def save(self, configs: list[WiFiConfig]) -> bool:
		return _writeLines(self._writePath, self.serialise(configs), backup=True)

	def ensureDir(self):
		makedirs(wpaSupplicantDir, exist_ok=True)


def wpaDictToWlanConfig(fields: dict[str, str], blockId: int) -> WiFiConfig:
	keyMgmt = fields.get("key_mgmt", "NONE").upper()
	proto = fields.get("proto", "").upper()
	pairwise = fields.get("pairwise", "").upper()

	if keyMgmt == "NONE":
		enc = encNone if not fields.get("wep_key0") else encWep
	elif "SAE" in keyMgmt:
		enc = encWpa3
	elif "WPA" in keyMgmt:
		enc = encWpa2 if ("CCMP" in pairwise or "WPA2" in proto or "RSN" in proto) else encWpa
	else:
		enc = encNone

	return WiFiConfig(
		ssid=fields.get("ssid", ""),
		hidden=fields.get("scan_ssid", "0") == "1",
		encryption=enc,
		key=fields.get("psk", fields.get("wep_key0", "")),
		bgscan=fields.get("bgscan", "simple:30:-70:3600"),
		wpaId=blockId,
		disabled=fields.get("disabled", "0") == "1",
	)


def wlanConfigToWpaBlock(wlan: WiFiConfig, blockId: int) -> list[str]:
	lines = ["network={"]
	lines.append(f'\tssid="{wlan.ssid}"')
	if wlan.hidden:
		lines.append("\tscan_ssid=1")
	lines.append(f"\tpriority={blockId}")
	if wlan.bgscan:
		lines.append(f'\tbgscan="{wlan.bgscan}"')

	enc = wlan.encryption
	if enc == encNone:
		lines.append("\tkey_mgmt=NONE")
	elif enc == encWep:
		lines.append("\tkey_mgmt=NONE")
		if wlan.wepKeyType == "HEX":
			lines.append(f"\twep_key0={wlan.key}")
		else:
			lines.append(f'\twep_key0="{wlan.key}"')
		lines.append("\twep_tx_keyidx=0")
	elif enc == encWpa:
		lines.append("\tkey_mgmt=WPA-PSK")
		lines.append("\tproto=WPA")
		lines.append(f'\tpsk="{wlan.key}"')
	elif enc in (encWpa2, encWpaWpa2):
		lines.append("\tkey_mgmt=WPA-PSK")
		lines.append("\tproto=RSN")
		lines.append(f'\tpsk="{wlan.key}"')
	elif enc == encWpa3:
		lines.append("\tkey_mgmt=SAE")
		lines.append("\tproto=RSN")
		lines.append(f'\tpsk="{wlan.key}"')

	if wlan.disabled:
		lines.append("\tdisabled=1")
	lines.append("}")
	return lines


# ===========================================================================
# Broadcom wl-config format
# ===========================================================================


# ===========================================================================
# Driver / module detection
# ===========================================================================


def reEscape(text: str) -> str:
	return text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


# ===========================================================================
# DNS / nameserver files
# ===========================================================================

class NameserverFiles:
	"""Read and write /etc/resolv.conf + /etc/enigma2/nameserversdns.conf."""

	RE_NS4 = compile(r"nameserver\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
	RE_NS6 = compile(r"nameserver\s+(([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4})")

	def load(self, ns: NameserverConfig):
		path = resolvFile if ns.mode == "dhcp-router" else nameserverFile
		ns.servers = self.parse(path)

	def parse(self, path: str) -> list:
		servers: list = []
		for line in _readLines(path):
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
			mode = ns.ipMode
			v4 = ["nameserver " + ".".join(str(octet) for octet in x) for x in ns.servers if isinstance(x, list) and x != [0, 0, 0, 0]]
			v6 = [f"nameserver {x}" for x in ns.servers if isinstance(x, str) and x]
			if mode == 0:
				nsLines = v4 + v6
			elif mode == 1:
				nsLines = v6 + v4
			elif mode == 2:
				nsLines = v4
			else:
				nsLines = v6
			prefix: list[str] = []
			if ns.rotate:
				prefix.append("options rotate")
			if ns.suffix:
				prefix.append(f"domain {ns.suffix}")
			return prefix + nsLines

		lines = build(ns)
		if not anyDhcpActive:
			_writeLines(resolvFile, lines)
		if ns.mode != "dhcp-router":
			_writeLines(nameserverFile, lines)
		elif exists(nameserverFile):
			try:
				remove(nameserverFile)
			except OSError:
				pass


# ===========================================================================
# WlanRuntime – shell command builders for WLAN operations
# ===========================================================================

class WlanRuntime:
	"""Builds shell command lists for WLAN bring-up / tear-down."""

	def __init__(self, adapter: Adapter):
		self.adapter = adapter

	@property
	def _iface(self) -> str:
		return self.adapter.name

	def commandsActivate(self, conn: Connection) -> list[str]:
		iface = self._iface
		cmds: list[str] = []
		cmds.extend(self.commandsDeactivate())
		cmds.append(f"{ifconfigBin} {iface} up || true")
		if conn.wlan and conn.wlan.encryption != encNone:
			if self.adapter.driverApi == apiBrcmWl:
				cmds.extend(self.bcmUpCmds(conn))
			else:
				cmds.append(
					f"{wpaSupplicantBin} -B -D {self.adapter.driverApi} "
					f"-i{iface} -c{self.adapter.wpaConfPath} "
					f"-P{self.adapter.wpaPidPath} || true"
				)
		elif conn.wlan:
			cmds.append(f'iwconfig {iface} essid "{reEscape(conn.wlan.ssid)}" || true')
		cmds.append(f"{ifupBin} {iface}")
		return cmds

	def commandsDeactivate(self) -> list[str]:
		iface = self._iface
		return [
			f"{wpaCliBin} -i{iface} terminate 2>/dev/null; true",
			f"{ifdownBin} {iface} 2>/dev/null; true",
			f"ip addr flush dev {iface} scope global 2>/dev/null; true",
		]

	def bcmUpCmds(self, conn: Connection) -> list[str]:
		wlan = conn.wlan
		if wlan is None:
			return []
		encStr = {encWep: "WEP", encWpa: "WPA", encWpa2: "WPA2", encWpaWpa2: "WPA2"}.get(wlan.encryption, "NONE")
		return [f"{wlConfigScript} -m {encStr} -k {wlan.key} -s \"{reEscape(wlan.ssid)}\" || true"]

	def statusCommands(self) -> list[str]:
		iface = self._iface
		if self.adapter.driverApi == apiBrcmWl:
			return [f"wl -i {iface} status"]
		return [f"iwconfig {iface}"]


# ===========================================================================
# Interface detection helpers
# ===========================================================================

def _isWirelessName(iface: str) -> bool:
	return bool(match(r"(wlan|ath|ra|wl)\d+", iface))


def _isWireless(iface: str) -> bool:
	if _isWirelessName(iface):
		return True
	if isdir(f"{sysfsNet}/{iface}/wireless"):
		return True
	if exists(procNetWireless):
		try:
			return f"{iface}:" in open(procNetWireless).read()
		except OSError:
			pass
	return False


def _parseIp4(text: str) -> list[int]:
	try:
		parts = [int(x) for x in text.split(".")]
		if len(parts) == 4 and all(0 <= x <= 255 for x in parts):
			return parts
	except (ValueError, AttributeError):
		pass
	return [0, 0, 0, 0]


# ===========================================================================
# NetEventReader – Twisted reader for socketdaemon event push socket
# ===========================================================================

class NetEventReader:
	"""Connects to /var/run/daemon_net.socket (AF_UNIX SOCK_STREAM) and reads"""

	_RETRY_MS = 5000

	def __init__(self, manager: NetworkManager):
		self.manager = manager
		self._sock = None
		self._buf = b""
		self._retryTimer = None
		self._connect()

	# -- Twisted FileDescriptor interface --

	def fileno(self) -> int:
		return self._sock.fileno() if self._sock else -1

	def doRead(self):
		try:
			data = self._sock.recv(4096)
		except OSError:
			data = b""
		if not data:
			self._disconnect()
			return
		self._buf += data
		while b"\n" in self._buf:
			line, self._buf = self._buf.split(b"\n", 1)
			self._dispatch(line.decode("ascii", errors="replace").strip())

	def connectionLost(self, failure=None):
		self._disconnect()

	def logPrefix(self) -> str:
		return "NetEventReader"

	# -- internal --

	def _connect(self):
		try:
			sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			sock.connect(netEventSocketPath)
			sock.setblocking(False)
			self._sock = sock
			reactor.addReader(self)
			print(f"[NetEventReader] connected to {netEventSocketPath}")
		except OSError:
			self._scheduleRetry()

	def _disconnect(self):
		if self._sock:
			try:
				reactor.removeReader(self)
			except Exception:
				pass
			try:
				self._sock.close()
			except OSError:
				pass
			self._sock = None
		self._scheduleRetry()

	def _scheduleRetry(self):
		if self._retryTimer is not None:
			return
		self._retryTimer = eTimer()
		self._retryTimer.callback.append(self._retry)
		self._retryTimer.start(self._RETRY_MS, True)

	def _retry(self):
		self._retryTimer = None
		self._connect()

	# TODO: During Wi-Fi association retries the daemon can fire bursts of several
	# LINK/SCAN_TRIGGER/UPDATE events within a few milliseconds (driver flapping).
	# Each is processed immediately below, causing redundant adapter updates/GUI
	# refreshes. Debounce this: buffer incoming events and only actually process
	# them once no further event has arrived within X ms, instead of acting on
	# every single line as it comes in.
	def _dispatch(self, line: str):
		if not line:
			return
		self.manager.log(f"NetEventReader: recv {line!r}")
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


# Polls (up to 10 x 1s) until the hostname resolves to something other than
# 127.0.0.1, then triggers a rescan of network mounts (NFS/CIFS) that couldn't
# be mounted before the network came up.
class NetworkCheck:
	def __init__(self):
		self._timer = eTimer()
		self._timer.callback.append(self._check)
		self._retry = 0

	def start(self):
		self._retry = 10
		self._timer.start(1000, True)

	def _check(self):
		self._timer.stop()
		if self._retry <= 0:
			return
		try:
			if socket.gethostbyname(socket.gethostname()) != "127.0.0.1":
				print("[NetworkManager] NetworkCheck: Done.")
				harddiskmanager.enumerateNetworkMounts(refresh=True)
				return
			self._retry -= 1
			self._timer.start(1000, True)
		except Exception as err:
			print(f"[NetworkManager] NetworkCheck: Error {err}!")


# ===========================================================================
# What changed as a result of a save() call – the caller already knows this
# (it's the one making the change), so it passes the right code to
# NetworkSetup.applyAdapterChange() itself instead of save() trying to guess it.
# ===========================================================================

CHANGE_NONE = 0              # nothing that needs activating changed
CHANGE_WPA_SUPPLICANT = 1    # only wpa_supplicant config changed
CHANGE_ADAPTER_ENABLED = 2   # only adapter/connection enable state changed (LAN)
CHANGE_GENERAL = 3           # anything else (IP/gateway/DNS/... changed)


# ===========================================================================
# NetworkManager – central singleton
# ===========================================================================

class NetworkManager:
	"""Central access point for all network configuration."""

	ADAPTER_BLACKLIST = frozenset((
		"lo", "wifi0", "wmaster0", "sit0", "tap0", "tun0",
		"wg0", "sys0", "p2p0", "tunl0", "ip6tnl0", "ip_vti0", "ip6_vti0",
	))

	ROUTE_METRIC_FILE = "/etc/default/e2-route-metric"
	ROUTE_METRIC_CHOICES = [(x, str(x)) for x in range(100, 901, 100)]

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
		self.adapters: dict[str, Adapter] = {}
		self.connections: dict[str, list[Connection]] = {}
		self.nameserverConfig = NameserverConfig()
		self.ifacesFile = InterfacesFile()
		self.nsFiles = NameserverFiles()
		self.pendingRestart = None
		self.networkCheck = None
		self.onAdaptersChanged: list[Callable] = []
		self.load()
		self._eventReader = NetEventReader(self)

	def log(self, msg: str):
		if self._debug:
			print(f"[NetworkManager] {msg}")

	# Called once by InitNetwork() during Enigma2 startup.
	def startNetworkCheck(self):
		self.networkCheck = NetworkCheck()
		self.networkCheck.start()

	# ------------------------------------------------------------------
	# Loading
	# ------------------------------------------------------------------

	def load(self):
		self.log("load(): starting full config/state load")
		self.discoverAdapters()
		self.loadInterfacesFile()
		self.loadWpaSupplicantFiles()
		self.nsFiles.load(self.nameserverConfig)
		self.applyNetinfo()
		self.log(f"load(): done, adapters={sorted(self.adapters.keys())}")

	def bcmConfPath(self, iface: str) -> str:
		return f"/etc/wl.conf.{iface}"

	def discoverAdapters(self):
		def detectDriverApi(iface: str, module: str) -> str:
			if exists(f"/tmp/bcm/{iface}"):
				return apiBrcmWl
			if module in ("brcm-systemport", "brcmfmac", "brcmsmac"):
				return apiBrcmWl
			if isdir(f"{sysfsNet}/{iface}/device/ieee80211"):
				return apiNl80211
			if module in ("ath_pci", "ath5k", "ar6k_wlan"):
				return apiMadwifi
			if module in ("rt73", "rt73usb", "rt3070sta", "rt2800usb"):
				return apiRalink
			if module == "zd1211b":
				return apiZydas
			if exists(procNetWireless):
				try:
					if f"{iface}:" in open(procNetWireless).read():
						return apiWext
				except OSError:
					pass
			return apiNl80211

		def isBlacklisted(iface: str) -> bool:
			return iface in self.ADAPTER_BLACKLIST

		def detectModule(iface: str) -> str:
			devDir = f"{sysfsNet}/{iface}/device"
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

		def canWakeOnWiFi(iface: str) -> bool:
			return iface == "wlan3" and bool(BoxInfo.getItem("wwol"))

		try:
			names = [x for x in listdir(sysfsNet) if not isBlacklisted(x)]
		except OSError:
			names = []

		for name in names:
			isWlan = _isWireless(name)
			module = detectModule(name)
			api = detectDriverApi(name, module)
			# Rediscovery (restartNetwork(), onIfaceAdd()) replaces the Adapter
			# object outright – carry its live netInfo over so it doesn't go
			# blank until the next netinfo update arrives.
			existing = self.adapters.get(name)
			adapter = Adapter(
				name=name,
				isWlan=isWlan,
				module=module,
				driverApi=api,
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
			self.log(f"discoverAdapters(): {name} isWlan={isWlan} module={module} driverApi={api} up={netInfo.up}")

	def loadInterfacesFile(self):
		self.ifacesFile.load()
		parsed, autoIfaces, wakeOnWiFiIfaces = self.ifacesFile.parse()
		self.log(f"loadInterfacesFile(): autoIfaces={sorted(autoIfaces)} wakeOnWiFiIfaces={sorted(wakeOnWiFiIfaces)}")
		for iface, conns in parsed.items():
			if iface not in self.adapters:
				self.adapters[iface] = Adapter(
					name=iface,
					isWlan=_isWirelessName(iface),
					driverApi=apiNl80211,
				)
			self.connections[iface] = conns
			self.adapters[iface].adapterEnabled = iface in autoIfaces
			if iface in wakeOnWiFiIfaces:
				for conn in conns:
					conn.wakeOnWiFi = True
			self.log(f"loadInterfacesFile(): {iface} adapterEnabled={self.adapters[iface].adapterEnabled} connections={len(conns)}")
		for iface, adapter in self.adapters.items():
			if not self.connections.get(iface):
				self.connections[iface] = [Connection(
					adapter=iface,
					name=iface,
					dhcp=True,
					wlan=WiFiConfig() if adapter.isWlan else None,
				)]

	def loadWpaSupplicantFiles(self):

		legacyEncMap: dict[str, str] = {
			"unencrypted": encNone,
			"none": encNone,
			"wep": encWep,
			"wpa": encWpa,
			"wpa/wpa2": encWpaWpa2,
			"wpa2": encWpa2,
			"wpa3": encWpa3,
		}

		def bcmLoadWiFiConfig(iface: str) -> WiFiConfig:
			wlan = WiFiConfig()
			for line in _readLines(self.bcmConfPath(iface)):
				line = line.strip()
				if not line or line.startswith("#"):
					continue
				key, sep, value = line.partition("=")
				key, value = key.strip(), value.strip()
				if key == "ssid":
					wlan.ssid = value
				elif key == "method":
					wlan.encryption = legacyEncMap.get(value.lower(), encNone)
				elif key == "key":
					wlan.key = value
			return wlan

		for iface, adapter in self.adapters.items():
			if not adapter.isWlan:
				continue
			if adapter.driverApi == apiBrcmWl:
				self.mergeWiFiConfig(iface, bcmLoadWiFiConfig(iface))
			else:
				wpf = WpaSupplicantFile(iface)
				if not wpf.exists():
					self.log(f"loadWpaSupplicantFiles(): {iface} no {wpf.path}")
					continue
				for wlan in wpf.parse():
					self.log(f"loadWpaSupplicantFiles(): {iface} ssid={wlan.ssid!r} disabled={wlan.disabled} encryption={wlan.encryption}")
					self.mergeWiFiConfig(iface, wlan)

	def mergeWiFiConfig(self, iface: str, wlan: WiFiConfig):
		conns = self.getConnections(iface)
		bySsid = {x.wlan.ssid: x for x in conns if x.wlan and x.wlan.ssid}
		if wlan.ssid in bySsid:
			conn = bySsid[wlan.ssid]
			conn.wlan = wlan
			conn.enabled = not wlan.disabled
		else:
			conns.append(Connection(
				adapter=iface,
				name=wlan.ssid,
				dhcp=True,
				enabled=not wlan.disabled,
				priority=wlan.wpaId or 0,
				wlan=wlan,
			))

	# ------------------------------------------------------------------
	# Saving
	# ------------------------------------------------------------------

	def bcmSaveWlanConfig(self, iface: str, wlan: WiFiConfig) -> bool:
		encStr = {
			encNone: "None", encWep: "WEP", encWpa: "WPA",
			encWpa2: "WPA2", encWpaWpa2: "WPA2", encWpa3: "WPA2",
		}.get(wlan.encryption, "None")
		return _writeLines(self.bcmConfPath(iface), [
			f"ssid={wlan.ssid}",
			f"method={encStr}",
			f"key={wlan.key}",
		])

	# Write wpa_supplicant.conf (or the Broadcom wl config) for one adapter's –
	# or, if onlyIface is None, every WLAN adapter's – Wi-Fi SSID profiles.
	# Deliberately does NOT touch /etc/network/interfaces: NetworkConnectionWiFi
	# (adding/editing/toggling a single SSID) calls this directly so saving one
	# profile never triggers an adapter-level ifup/ifdown/restart – that only
	# happens through NetworkAdapterSetup/applyAdapterChange(), which call the
	# full save() below instead.
	def saveWifiProfiles(self, onlyIface: str | None = None) -> bool:
		ok = True
		ifaces = [onlyIface] if onlyIface else list(self.adapters.keys())
		for iface in ifaces:
			adapter = self.adapters.get(iface)
			if not adapter or not adapter.isWlan:
				continue
			conns = self.getConnections(iface)
			for conn in conns:
				if conn.wlan is not None and conn.wlan.ssid:
					conn.wlan.disabled = not conn.enabled
			wlanConfigs = [x.wlan for x in conns if x.wlan is not None and x.wlan.ssid]
			if not wlanConfigs:
				continue
			self.log(f"saveWifiProfiles(): {iface} writing {len(wlanConfigs)} wlan profile(s): " + ", ".join(f"{w.ssid!r}(disabled={w.disabled})" for w in wlanConfigs))
			if adapter.driverApi == apiBrcmWl:
				active = self.activeConnection(iface)
				if active and active.wlan:
					ok = self.bcmSaveWlanConfig(iface, active.wlan) and ok
			else:
				wpf = WpaSupplicantFile(iface)
				wpf.ensureDir()
				ok = wpf.save(wlanConfigs) and ok
		return ok

	def save(self) -> bool:
		# ===========================================================================
		# WLAN configStrings (interfaces pre-up / pre-down)
		# ===========================================================================

		def buildWlanConfigStrings(adapter: Adapter, conn: Connection) -> str:
			if not conn.isWlan or not conn.wlan:
				return ""

			iface = adapter.name
			wlan = conn.wlan
			api = adapter.driverApi
			lines: list[str] = []

			if api == apiBrcmWl:
				encStr = {
					encNone: "NONE", encWep: "WEP", encWpa: "WPA",
					encWpa2: "WPA2", encWpaWpa2: "WPA2", encWpa3: "WPA2",
				}.get(wlan.encryption, "NONE")
				lines.append(f"pre-up {wlConfigScript} -m {encStr} -k {wlan.key} -s \"{reEscape(wlan.ssid)}\" || true")
				lines.append(f"pre-up {ifconfigBin} {iface} up || true")
				lines.append(f"pre-up iwconfig {iface} essid \"{reEscape(wlan.ssid)}\" || true")
				lines.append(f"post-down {wlConfigScript} -m NONE || true")
			else:
				driverFlags = f"-D {api}" if api != apiNl80211 else ""
				lines.append(f"pre-up {ifconfigBin} {iface} up || true")
				if wlan.encryption != encNone:
					lines.append(f"pre-up {wpaSupplicantBin} -i{iface} -c{adapter.wpaConfPath} -B {driverFlags} -P{adapter.wpaPidPath} || true")
				else:
					lines.append(f"pre-up iwconfig {iface} essid \"{reEscape(wlan.ssid)}\" || true")
				lines.append(f"pre-down {wpaCliBin} -i{iface} terminate 2>/dev/null; true")

			return "\n".join(lines)

		self.log("save(): starting")
		ok = True
		for iface, adapter in self.adapters.items():
			if not adapter.isWlan:
				continue
			for conn in self.getConnections(iface):
				# Only real SSID profiles carry a usable wlan config; the base
				# (non-SSID) placeholder's WifiConfig is always empty and must
				# not be used to build pre-up/pre-down commands.
				if conn.wlan and conn.wlan.ssid:
					cs = buildWlanConfigStrings(adapter, conn)
					conn.extraLines = [x for x in cs.splitlines() if x] if cs else []

		# For WLAN: write exactly ONE base block to interfaces (IP/DHCP/DNS/WOL/WWOL,
		# edited directly on this base Connection via NetworkAdapterSetup). SSID
		# connections are managed exclusively via wpa_supplicant.conf and only
		# contribute their pre-up/pre-down commands (extraLines) here.
		connMap = {}
		for iface, adapter in self.adapters.items():
			conns = self.getConnections(iface)
			if adapter.isWlan:
				baseConn = self.getBaseConnection(iface)
				# adapterEnabled is the master switch, except WoW-Only mode keeps
				# the iface stanza written (for its wowl pre-up hooks) even while
				# the adapter is otherwise off.
				wowOnly = baseConn.wakeOnWiFi and not adapter.adapterEnabled
				baseConn.enabled = adapter.adapterEnabled or wowOnly
				# The wpa_supplicant pre-up/pre-down lines must always be written
				# whenever at least one Wi-Fi profile is configured, regardless of
				# whether that profile is individually enabled – for nl80211 they're
				# generic (just "start wpa_supplicant against wpa_supplicant.conf",
				# not tied to any one SSID) and enabling/disabling is handled
				# entirely by serialiseConnection()'s connPfx comment-out (driven
				# by baseConn.enabled above), the same way LAN/WLAN adapters and
				# individual SSID profiles in wpa_supplicant.conf are switched
				# on/off by commenting, not by omitting lines. Gating this on
				# `.enabled` used to mean: no enabled SSID -> extraLines=[] -> the
				# whole wpa_supplicant pre-up line silently disappears from
				# interfaces -> wpa_supplicant never starts on ifup at all.
				wpaConns = [x for x in conns if x.wlan and x.wlan.ssid]
				activeWpa = max(wpaConns, key=lambda conn: conn.priority, default=None)
				baseConn.extraLines = activeWpa.extraLines if activeWpa else []
				connMap[iface] = [baseConn]
			else:
				# adapterEnabled is the master switch here too – NetworkAdapterSetup
				# only sets it, not conn.enabled directly, so keep them in sync or
				# serialiseConnection() would only comment out the "auto" line and
				# leave the iface/address/dns lines active.
				for conn in conns:
					conn.enabled = adapter.adapterEnabled
				connMap[iface] = conns
		adapterEnabledMap = {iface: adapter.adapterEnabled for iface, adapter in self.adapters.items()}
		self.log(f"save(): adapterEnabledMap={adapterEnabledMap}")
		ok = self.ifacesFile.save(connMap, adapterEnabledMap) and ok
		ok = self.saveWifiProfiles() and ok

		anyDhcp = any(conn.dhcp for conns in connMap.values() for conn in conns if conn.enabled)
		self.nsFiles.save(self.nameserverConfig, anyDhcp)
		# save() only writes config files now – it doesn't know whether the
		# caller is actually going to apply anything afterward (a plain Save
		# with no changes is a no-op), so it no longer calls
		# notifyNetworkPlugins(False) itself. That's applyAdapterChange()'s job
		# (NetworkSetup.py), paired with the matching reason=True once the
		# change has actually applied – otherwise a plugin (e.g. OpenWebif)
		# got stopped on every save and never came back if nothing else
		# happened to restart it.
		self.log(f"save(): done, ok={ok}")
		return ok

	# ------------------------------------------------------------------
	# Runtime
	# ------------------------------------------------------------------

	def activateCommands(self, iface: str) -> list[str]:
		adapter = self.adapters.get(iface)
		if not adapter:
			return []
		conn = self.activeConnection(iface)
		if not conn:
			return [f"{ifupBin} {iface}"]
		if adapter.isWlan:
			return WlanRuntime(adapter).commandsActivate(conn)
		return [f"{ifupBin} {iface}"]

	def deactivateCommands(self, iface: str) -> list[str]:
		adapter = self.adapters.get(iface)
		if adapter and adapter.isWlan:
			return WlanRuntime(adapter).commandsDeactivate()
		return [
			f"{ifdownBin} {iface} 2>/dev/null; true",
			f"ip addr flush dev {iface} scope global 2>/dev/null; true",
		]

	# Restart via socketdaemon NETRESTART;
	def restartNetwork(self, iface: str = "", callback: Callable | None = None):
		self.log(f"restartNetwork(): iface={iface or 'all'}")

		def done(retval: int = 0):
			self.log(f"restartNetwork(): {iface or 'all'} done, retval={retval}")
			# discoverAdapters() rebuilds each Adapter from scratch (dataclass
			# defaults, so adapterEnabled=False) – restore the persisted config
			# on top, same as load() does at startup. self.connections is a
			# separate dict, untouched by discoverAdapters().
			self.discoverAdapters()
			self.loadInterfacesFile()
			self.loadWpaSupplicantFiles()
			# discoverAdapters() deliberately carries the *old* netInfo (incl.
			# gateway/ip/mask) over so the UI doesn't go blank while waiting –
			# but that means it's stale until refreshed. The daemon does push an
			# "UPDATE" event over the socket eventually (-> applyNetinfo() via
			# onNetinfoUpdate()), but that's async and may lag behind this
			# callback, so re-read /var/run/netinfo synchronously right now too
			# instead of leaving old values (e.g. a gateway eth0 no longer has)
			# on screen until whenever that event happens to arrive.
			self.applyNetinfo()
			# The network just came back – restart plugins that were stopped
			# earlier (e.g. OpenWebif). iface=iface mirrors applyAdapterChange()'s
			# reason=False call further up the chain: if another adapter kept
			# the box reachable, that call was skipped, so this one is too.
			self.notifyNetworkPlugins(True, iface=iface)
			if callback:
				callback()
		self.pendingRestart = ServiceAction.netrestart(done, iface=iface)

	# ------------------------------------------------------------------
	# Accessors
	# ------------------------------------------------------------------

	def getAdapter(self, iface: str) -> Adapter | None:
		return self.adapters.get(iface)

	def getNetInfo(self, iface: str) -> NetInfo:
		adapter = self.adapters.get(iface)
		return adapter.netInfo if adapter else NetInfo()

	def getConnections(self, iface: str) -> list[Connection]:
		return self.connections.setdefault(iface, [])

	# Highest-priority enabled connection for this adapter.
	def activeConnection(self, iface: str) -> Connection | None:
		enabled = [x for x in self.getConnections(iface) if x.enabled]
		return max(enabled, key=lambda conn: conn.priority, default=None)

	# The non-SSID placeholder Connection that carries IP config (DHCP/IP/
	# netmask/gateway/DNS) and WOL/WWOL – the only Connection ever written to
	# /etc/network/interfaces for a WLAN adapter. For LAN, simply the (only)
	# Connection. Created on demand if it doesn't exist yet.
	def getBaseConnection(self, iface: str) -> Connection:
		conns = self.getConnections(iface)
		if not conns:
			adapter = self.adapters.get(iface)
			isWlan = adapter.isWlan if adapter else _isWirelessName(iface)
			base = Connection(adapter=iface, name=iface, dhcp=True, wlan=WiFiConfig() if isWlan else None)
			conns.append(base)
			return base
		base = next((x for x in conns if not (x.wlan and x.wlan.ssid)), None)
		if base is None:
			adapter = self.adapters.get(iface)
			isWlan = adapter.isWlan if adapter else _isWirelessName(iface)
			base = Connection(adapter=iface, name=iface, dhcp=True, wlan=WiFiConfig() if isWlan else None)
			conns.append(base)
		return base

	def getActiveConnection(self, iface: str) -> Connection | None:
		return self.activeConnection(iface)

	def getWlanConnections(self, iface: str) -> list[Connection]:
		return [x for x in self.getConnections(iface) if x.isWlan]

	def addConnection(self, conn: Connection):
		self.getConnections(conn.adapter).append(conn)

	def removeConnection(self, iface: str, ssid: str) -> bool:
		conns = self.connections.get(iface)
		if not conns:
			self.log(f"removeConnection(): {iface} not found")
			return False
		before = len(conns)
		self.connections[iface] = [x for x in conns if not (x.wlan and x.wlan.ssid == ssid)]
		removed = len(self.connections[iface]) < before
		self.log(f"removeConnection(): {iface} ssid={ssid!r} removed={removed}")
		return removed

	def setNameservers(self, servers: list):
		self.nameserverConfig.servers = list(servers)

	# Returns a human-readable adapter label.
	def getFriendlyAdapterName(self, iface: str) -> str:
		adapter = self.adapters.get(iface)
		if adapter is None:
			return iface
		wlanAdapters = sorted(name for name, other in self.adapters.items() if other.isWlan)
		lanAdapters = sorted(name for name, other in self.adapters.items() if not other.isWlan)
		if adapter.isWlan:
			idx = wlanAdapters.index(iface) if iface in wlanAdapters else 0
			return _("WLAN connection") + (f" {idx + 1}" if idx else "")
		idx = lanAdapters.index(iface) if iface in lanAdapters else 0
		return _("LAN connection") + (f" {idx + 1}" if idx else "")

	# Compatibility shim – returns a short adapter description.
	def getFriendlyAdapterDescription(self, iface: str) -> str:
		adapter = self.adapters.get(iface)
		if adapter is None:
			return iface
		if adapter.isWlan:
			return f"{adapter.module or 'Unknown'} {_('wireless network interface')}"
		return _("Ethernet network interface")

	# Fire WHERE_NETWORKCONFIG_READ plugins – save()/applyAdapterChange() only ever
	# run from user-initiated UI actions, never during early boot, so there's
	# no "too early" case to guard against here. An earlier version skipped
	# the call unless some adapter's *current* netInfo already showed a real
	# IP, but that's exactly the state that's in flux because of the change
	# being notified about (e.g. on disable, netInfo may still show the old
	# "up" state, or on enable it may not have caught up yet via the async
	# socketdaemon event) – so it silently dropped notifications in both
	# directions. Plugins (e.g. OpenWebif's HttpdStart/HttpdStop) are
	# idempotent and expected to handle redundant calls cheaply.
	#
	# `iface`, when given, is the ONE adapter actually being changed – if some
	# OTHER adapter is already up with a real IP, the box stays reachable
	# through it regardless of what happens to `iface`, so there's nothing
	# for plugins to stop/restart (e.g. disabling wlan0 while eth0 is up and
	# serving OpenWebif shouldn't bounce OpenWebif). Checking *other* adapters
	# this way is safe against the staleness problem above, since their
	# netInfo isn't the one in flux.
	#
	# reason=False: the network config is about to change – plugins must
	#   stop their internal services (they'd otherwise keep running against
	#   a socket/IP that's going away).
	# reason=True: the change is done, the network is available again –
	#   plugins (re)start.
	#
	# Example (OpenWebif, Plugins/Extensions/OpenWebif/plugin.py):
	#   PluginDescriptor(where=[PluginDescriptor.WHERE_NETWORKCONFIG_READ], fnc=IfUpIfDown)
	#   def IfUpIfDown(reason, **kwargs):
	#       if reason is True:
	#           HttpdStart(global_session)
	#       else:
	#           HttpdStop(global_session)
	def notifyNetworkPlugins(self, reason: bool, iface: str = ""):
		self.log(f"notifyNetworkPlugins(): reason={reason} iface={iface!r} states=" + ", ".join(
			f"{other}(up={adapter.netInfo.up}, ip={adapter.netInfo.ip})" for other, adapter in self.adapters.items()
		))
		if iface:
			otherAdapterUp = any(
				adapter.netInfo.up and any(octet != 0 for octet in adapter.netInfo.ip)
				for other, adapter in self.adapters.items() if other != iface
			)
			if otherAdapterUp:
				self.log(f"notifyNetworkPlugins(): {iface} changed but another adapter is still up -> skipped")
				return
		try:
			notified = [str(plugin) for plugin in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKCONFIG_READ)]
			self.log(f"notifyNetworkPlugins(): calling {notified} with reason={reason}")
			for plugin in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKCONFIG_READ):
				plugin(reason=reason)
		except Exception as e:
			self.log(f"notifyNetworkPlugins(): EXCEPTION {e}")

	def activateInterface(self, iface, callback=None):
		adapter = self.adapters.get(iface)
		if adapter and not adapter.isWlan:
			def lanUp(retval: int):
				self.log(f"activateInterface(): {iface} (LAN) ifup retval={retval}")
				self.notifyNetworkPlugins(True)
				if callback:
					callback(retval == 0)
			self.log(f"activateInterface(): {iface} (LAN) ifup")
			self.pendingRestart = ServiceAction.ifup(iface, lanUp)
			return

		def wlanUp(retval: bool = True):
			self.log(f"activateInterface(): {iface} (WLAN) done")
			self.notifyNetworkPlugins(True)
			if callback:
				callback(True)
		try:
			cmds = self.activateCommands(iface)
			self.log(f"activateInterface(): {iface} (WLAN) commands={cmds}")
			Console().eBatch(cmds, lambda result: wlanUp(), debug=True)
		except Exception as e:
			self.log(f"activateInterface(): {iface} (WLAN) failed: {e}")
			if callback:
				callback(False)

	# ------------------------------------------------------------------
	# WLAN switch
	# ------------------------------------------------------------------

	# Manually activate a specific WLAN Connection via wpa_cli or full bring-up.
	def switchWlanConnection(self, iface: str, targetConn: Connection) -> list[str]:
		adapter = self.adapters.get(iface)
		if adapter is None or not adapter.isWlan:
			return []
		others = [x for x in self.getConnections(iface) if x is not targetConn]
		maxOther = max((x.priority for x in others), default=0)
		targetConn.priority = maxOther + 10
		cmds: list[str] = []
		wpaId = targetConn.wlan.wpaId if targetConn.wlan else None
		ctrl = adapter.wpaCtrlPath
		viaWpaCli = exists(ctrl) and wpaId is not None
		if viaWpaCli:
			cmds.append(f"{wpaCliBin} -i{iface} disable_network all 2>/dev/null; true")
			cmds.append(f"{wpaCliBin} -i{iface} enable_network {wpaId}")
			cmds.append(f"{wpaCliBin} -i{iface} select_network {wpaId}")
			cmds.append(f"{wpaCliBin} -i{iface} reassociate")
		else:
			cmds.extend(WlanRuntime(adapter).commandsActivate(targetConn))
		self.log(f"switchWlanConnection(): {iface} ssid={targetConn.wlan.ssid if targetConn.wlan else '?'!r} viaWpaCli={viaWpaCli} cmds={cmds}")
		return cmds

	def getWlanNetworkList(self, iface: str) -> list[str]:
		return [f"{wpaCliBin} -i{iface} list_networks"]

	def wpaSupplicantRunning(self, iface: str) -> bool:
		adapter = self.adapters.get(iface)
		running = exists(adapter.wpaCtrlPath) if adapter else False
		self.log(f"wpaSupplicantRunning(): {iface} = {running}")
		return running

	def getWlanStatus(self, iface: str) -> dict:
		"""Parsed `wpa_cli status` (wpa_state, bssid, …) – used to explain *why* a
		Wi-Fi connection attempt failed (wrong key, AP not found, DHCP only, …).
		Empty dict if wpa_supplicant isn't reachable."""
		result = {}
		try:
			out = check_output([wpaCliBin, "-i", iface, "status"], stderr=DEVNULL, timeout=2).decode(errors="replace")
			for line in out.splitlines():
				key, sep, val = line.partition("=")
				if sep:
					result[key.strip()] = val.strip()
		except Exception as e:
			self.log(f"getWlanStatus(): {iface} wpa_cli failed: {e}")
		self.log(f"getWlanStatus(): {iface} = {result}")
		return result

	def setBgscan(self, iface: str, bgscan: str):
		for conn in self.getWlanConnections(iface):
			if conn.wlan:
				conn.wlan.bgscan = bgscan

	def getRoamingMode(self, iface: str) -> str:
		conn = self.getActiveConnection(iface)
		return conn.wlan.bgscan if (conn and conn.wlan) else ""

	def setRoamingMode(self, iface: str, mode: str):
		presets = {"auto": "simple:30:-70:3600", "fast": "simple:10:-65:300", "off": ""}
		self.setBgscan(iface, presets.get(mode, mode))

	# ------------------------------------------------------------------
	# Wake-on-WiFi
	# ------------------------------------------------------------------

	def setWakeOnWiFiCommands(self, iface: str, enable: bool) -> list[str]:
		adapter = self.adapters.get(iface)
		if adapter is None or not adapter.canWakeOnWiFi:
			return []
		self.getBaseConnection(iface).wakeOnWiFi = enable
		cmds: list[str] = []
		if enable:
			cmds.append(f"wl -i {iface} wowl 0x100")
			cmds.append(f"wl -i {iface} wowl_activate")
		else:
			cmds.append(f"wl -i {iface} wowl 0")
		procPath = BoxInfo.getItem("WakeOnLAN") or ""
		if procPath and exists(procPath):
			cmds.append(f"echo '{'enable' if enable else 'disable'}' > {procPath}")
		self.updateWowPreup(adapter, enable)
		return cmds

	def updateWowPreup(self, adapter: Adapter, enable: bool):
		baseConn = self.getBaseConnection(adapter.name)
		iface = adapter.name
		baseConn.extraLines = [x for x in baseConn.extraLines if "wowl" not in x]
		if enable:
			baseConn.extraLines.insert(0, f"pre-up wl -i {iface} wowl_activate || true")
			baseConn.extraLines.insert(0, f"pre-up wl -i {iface} wowl 0x100 || true")

	def getWakeOnWiFi(self, iface: str) -> bool:
		if iface not in self.adapters:
			return False
		return self.getBaseConnection(iface).wakeOnWiFi

	# ------------------------------------------------------------------
	# Link speed (forced, non-auto-negotiated)
	# ------------------------------------------------------------------

	def getSupportedLinkSpeeds(self, iface: str) -> list[tuple[str, str]]:
		choices = [("auto", _("Auto"))]
		adapter = self.adapters.get(iface)
		if adapter is None or adapter.isWlan:
			return choices
		mask = adapter.netInfo.linkSupported
		for _ethtoolMode, (bits, label) in self.LINKSPEED_BITS.items():
			if mask & bits:
				choices.append((f"{bits:#04x}", label))
		return choices

	@staticmethod
	def getLinkSpeed(iface: str) -> str:
		return fileReadLine(f"/etc/enigma2/{iface}_linkspeed", default="auto") or "auto"

	@staticmethod
	def setLinkSpeed(iface: str, value: str) -> None:
		path = f"/etc/enigma2/{iface}_linkspeed"
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
		for line in _readLines(cls.ROUTE_METRIC_FILE):
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
		if not exists(cls.ROUTE_METRIC_FILE):
			return
		lines = _readLines(cls.ROUTE_METRIC_FILE)
		newLines = []
		for line in lines:
			stripped = line.strip()
			if lanMetric is not None and stripped.startswith("LAN_METRIC="):
				newLines.append(f"LAN_METRIC={lanMetric}")
			elif wlanMetric is not None and stripped.startswith("WLAN_METRIC="):
				newLines.append(f"WLAN_METRIC={wlanMetric}")
			else:
				newLines.append(line)
		_writeLines(cls.ROUTE_METRIC_FILE, newLines)

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
		try:
			with open(netinfoPath, encoding="utf-8") as fh:
				info = json.loads(fh.read())
		except (OSError, json.JSONDecodeError):
			info = {}
		ifaces = info.get("interfaces", {})
		for iface, data in ifaces.items():
			adapter = self.adapters.get(iface)
			if adapter is None:
				continue
			netInfo = adapter.netInfo
			netInfo.up = data.get("up", False)
			# Always assign, with an explicit empty default when the field is
			# absent – "only assign if truthy" left stale values in place (e.g.
			# eth0's gateway from before a restart survived even after netinfo
			# reported no gateway for eth0 anymore, since the field was simply
			# never touched instead of being cleared).
			ip4 = data.get("ip4", "")
			netInfo.ip = _parseIp4(ip4) if ip4 else [0, 0, 0, 0]
			mask = data.get("mask", "")
			netInfo.netmask = _parseIp4(mask) if mask else [0, 0, 0, 0]
			gw = data.get("gw", "")
			netInfo.gateway = _parseIp4(gw) if gw else [0, 0, 0, 0]
			brd = data.get("brd", "")
			netInfo.bcast = _parseIp4(brd) if brd else [0, 0, 0, 0]
			netInfo.driver = data.get("driver", "")
			netInfo.hwId = data.get("hw_id", "")
			netInfo.bus = data.get("bus", "")
			netInfo.rxBytes = data.get("rx_bytes", 0)
			netInfo.txBytes = data.get("tx_bytes", 0)
			netInfo.mtu = data.get("mtu", 0)
			netInfo.ip6 = data.get("ip6", [])
			if adapter.isWlan:
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
		self.log("onNetinfoUpdate()")
		self.applyNetinfo()
		self.notifyAdaptersChanged()

	def onLinkChange(self, iface: str, up: bool, running: bool):
		self.log(f"onLinkChange(): {iface} up={up} running={running}")
		adapter = self.adapters.get(iface)
		if adapter:
			netInfo = adapter.netInfo
			netInfo.up = up
			if adapter.isWlan:
				# WLAN link = up and associated to AP; only clear here (on not-running or
				# not-up) — actually setting it True happens on the next netinfo update.
				if not running or not up:
					netInfo.link = False
					netInfo.ssid = ""
			else:
				netInfo.link = up and running
				self.showToast(iface, running)
		self.notifyAdaptersChanged()

	# TODO: Wenn der user an der Config was ändert oder wenn man was an den Socket als Befehl schickt sollte dieser Toast nicht kommen.
	def showToast(self, iface: str, up: bool):
		from Screens.Toast import Toast
		text = _("Network cable connected (%s)") % iface if up else _("Network cable disconnected (%s)") % iface
		icon = "\uF003" if up else "\uF004"
		Toast.instance.showToast(text=text, toasttype=Toast.TYPE_INFO, timeout=4, customIcon=icon)

	def onIpChange(self, iface: str, ipPrefix: str):
		self.log(f"onIpChange(): {iface} ipPrefix={ipPrefix}")
		adapter = self.adapters.get(iface)
		if adapter:
			adapter.netInfo.ip = _parseIp4(ipPrefix.split("/")[0])
		self.notifyAdaptersChanged()

	# Ping 8.8.8.8 (fallback 1.1.1.1) for each adapter that has physical link
	def checkConnectionInternet(self, callback: Callable[[dict[str, bool]], None]):
		candidates = [
			iface
			for iface, adapter in self.adapters.items()
			if adapter.netInfo.link and (
				conn := self.activeConnection(iface)
			) is not None and (conn.dhcp or conn.gateway != [0, 0, 0, 0])
		]
		self.log(f"checkConnectionInternet(): candidates={candidates}")
		if not candidates:
			callback({})
			return

		results: dict[str, bool] = {}
		remaining = [len(candidates)]

		def onResult(iface: str, ok: bool):
			results[iface] = ok
			remaining[0] -= 1
			if remaining[0] == 0:
				self.log(f"checkConnectionInternet(): results={results}")
				callback(results)

		def fallbackDone(iface: str, exitCode: int):
			onResult(iface, exitCode == 0)

		def primaryDone(iface: str, exitCode: int):
			if exitCode == 0:
				onResult(iface, True)
			else:
				ServiceAction.ping(iface, "1.1.1.1", lambda ec, iface=iface: fallbackDone(iface, ec))

		for iface in candidates:
			ServiceAction.ping(iface, "8.8.8.8", lambda ec, iface=iface: primaryDone(iface, ec))

	def onIfaceAdd(self, iface: str):
		self.log(f"onIfaceAdd(): {iface}")
		if iface not in self.adapters:
			# Same reasoning as restartNetwork(): discoverAdapters() alone
			# resets adapterEnabled to its dataclass default – restore the
			# persisted config on top (e.g. a re-plugged USB WiFi dongle).
			self.discoverAdapters()
			self.loadInterfacesFile()
			self.loadWpaSupplicantFiles()
		self.notifyAdaptersChanged()

	def onIfaceRemove(self, iface: str):
		self.log(f"onIfaceRemove(): {iface}")
		self.adapters.pop(iface, None)
		self.notifyAdaptersChanged()

	def onScanTrigger(self, iface: str):
		self.log(f"onScanTrigger(): {iface}")
		pass  # placeholder: trigger wpa_cli scan when WLAN comes up


# ===========================================================================
# Module-level singleton
# ===========================================================================

networkManager = NetworkManager()

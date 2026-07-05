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
from os import getpid, listdir, makedirs, remove
from os.path import basename, exists, isdir, realpath
from re import compile, match, search
from shutil import copy2
import socket
from struct import pack, unpack
from subprocess import check_output, DEVNULL
from time import monotonic
from collections.abc import Callable
from twisted.internet import reactor

from enigma import eTimer

from Components.Console import Console
from Components.Harddisk import harddiskmanager
from Components.PluginComponent import plugins
from Components.SystemInfo import BoxInfo
from Plugins.Plugin import PluginDescriptor
from Tools.Directories import fileReadLine, fileWriteLine
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
wpaCliBin = "/usr/bin/wpa_cli"
ethtoolBin = "/usr/sbin/ethtool"
socketDaemonPath = "/var/run/daemon.socket"
netEventSocketPath = "/var/run/daemon_net.socket"
netinfoPath = "/var/run/netinfo"
netrestarterBin = "/usr/sbin/netrestarter"

# Linux kernel ETHTOOL_ADVERTISED_* bitmask values, used by some drivers to
# force a specific link speed/duplex instead of auto-negotiation.
_LINKSPEED_BITS = {
	"10baseT/Half": (0x01, "10 Mbit/s Half Duplex"),
	"10baseT/Full": (0x02, "10 Mbit/s Full Duplex"),
	"100baseT/Half": (0x04, "100 Mbit/s Half Duplex"),
	"100baseT/Full": (0x08, "100 Mbit/s Full Duplex"),
	"1000baseT/Half": (0x10, "1000 Mbit/s Half Duplex"),
	"1000baseT/Full": (0x20, "1000 Mbit/s Full Duplex"),
}


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

ADAPTER_BLACKLIST = frozenset((
	"lo", "wifi0", "wmaster0", "sit0", "tap0", "tun0",
	"wg0", "sys0", "p2p0", "tunl0", "ip6tnl0", "ip_vti0", "ip6_vti0",
))

_bcmTmpPrefix = "/tmp/bcm"

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

# Driver-API identifiers
apiNl80211 = "nl80211"
apiWext = "wext"
apiMadwifi = "madwifi"
apiRalink = "ralink"
apiZydas = "zydas"
apiBrcmWl = "brcm-wl"

_legacyEncMap: dict[str, str] = {
	"unencrypted": encNone,
	"none": encNone,
	"wep": encWep,
	"wpa": encWpa,
	"wpa/wpa2": encWpaWpa2,
	"wpa2": encWpa2,
	"wpa3": encWpa3,
}

_wpaDefaultHeader = [
	"ctrl_interface=/var/run/wpa_supplicant",
	"update_config=1",
	"",
]

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
	idStr: str = ""      # wpa_supplicant id_str – persists the user-defined profile name
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
	enabled: bool = False        # "auto <iface>" in /etc/network/interfaces
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
	wakeOnLan: str = "off"       # "off" | "g" | "u" | "b"
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
class Adapter:
	"""Physical network interface as discovered in /sys/class/net."""

	name: str
	mac: str = ""
	isWlan: bool = False
	module: str = ""
	driverApi: str = apiNl80211
	canWakeOnWiFi: bool = False
	canWakeOnLan: bool = False
	wolProcPath: str = ""
	wolProcType: str = ""
	adapterEnabled: bool = False  # "auto <iface>" in /etc/network/interfaces
	kernelUp: bool = False
	kernelLink: bool = False   # physical link (cable/WLAN association)
	kernelIp: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	kernelNetmask: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	kernelGateway: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	kernelBcast: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
	kernelSpeed: int = -1        # LAN only, Mbps; -1 = unknown
	kernelDuplex: str = ""       # LAN only: "full" | "half" | ""
	kernelPort: str = ""         # LAN only: "TP" | "MII" | "FIBRE" | …
	kernelTransceiver: str = ""  # LAN only: "internal" | "external"
	kernelAutoneg: bool = False  # LAN only
	kernelLinkSupported: int = 0  # LAN only, ETHTOOL SUPPORTED_* bitmask from socketdaemon
	kernelSsid: str = ""         # WLAN only
	kernelBssid: str = ""        # WLAN only, AP MAC address
	kernelFreqMhz: int = 0       # WLAN only, channel frequency in MHz
	kernelChannel: int = 0       # WLAN only, channel number
	kernelBitrateBps: int = 0    # WLAN only, TX bitrate in bps
	kernelSignal: int = 0        # WLAN only, dBm
	kernelIp6: list = field(default_factory=list)  # [{"addr": "…", "prefix": 64}, …]
	kernelDriver: str = ""       # kernel module name (e.g. "r8168", "mt76x2u")
	kernelHwId: str = ""         # "VVVV:DDDD" PCI or USB vendor:product hex
	kernelWolSupported: int = 0  # ethtool WoL bitmask; 0 = not supported
	connections: list[Connection] = field(default_factory=list)

	# Highest-priority enabled connection.
	def activeConnection(self) -> Connection | None:
		enabled = [x for x in self.connections if x.enabled]
		return max(enabled, key=lambda conn: conn.priority, default=None)

	@property
	def wpaConfPath(self) -> str:
		return f"{wpaSupplicantDir}/wpa_supplicant-{self.name}.conf"

	@property
	def wpaPidPath(self) -> str:
		return f"/var/run/wpa_supplicant-{self.name}.pid"

	@property
	def wpaCtrlPath(self) -> str:
		return f"/var/run/wpa_supplicant/{self.name}"


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
		with open(path, "r", encoding="utf-8", errors="replace") as fh:
			return fh.read().splitlines()
	except OSError:
		return []


def _writeLines(path: str, lines: list[str], backup: bool = False) -> bool:
	if backup and exists(path):
		try:
			copy2(path, path + ".bk")
		except OSError as exc:
			print(f"[NetworkManager] Cannot backup {path}: {exc}")
	try:
		with open(path + "2", "w", encoding="utf-8") as fh:
			fh.write("\n".join(lines))
			if lines:
				fh.write("\n")
		return True
	except OSError as exc:
		print(f"[NetworkManager] Cannot write {path}: {exc}")
		return False


# Read and parse /var/run/netinfo written by socketdaemon. Returns {} on error.
def _readNetinfo() -> dict:
	try:
		with open(netinfoPath, encoding="utf-8") as fh:
			return json.loads(fh.read())
	except (OSError, json.JSONDecodeError):
		return {}


def _readSys(path: str) -> str:
	try:
		return open(path).read().strip()
	except OSError:
		return ""


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
				# The ethtool Wake-on-LAN pre-up is regenerated from
				# conn.wakeOnLan on save (gated on hardware support), not
				# carried over verbatim – otherwise a stale line would
				# survive forever even if WoL is unsupported/disabled.
				wolTag = f"pre-up {ethtoolBin} -s {current.adapter} wol "
				if line.startswith(wolTag) and line.endswith(" || true"):
					current.wakeOnLan = line[len(wolTag):-len(" || true")].strip()
				else:
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
				lines.extend(_serialiseConnection(conn, adapterEnabled))
				lines.append("")
		return lines

	def save(self, connectionsByAdapter: dict[str, list[Connection]], adapterEnabledMap: dict[str, bool] | None = None) -> bool:
		lines = self.serialise(connectionsByAdapter, adapterEnabledMap)
		ok = _writeLines(self._writePath, lines, backup=True)
		if ok:
			self._raw = lines
		return ok


# Serialise one Connection to interfaces-file lines.
def _serialiseConnection(conn: Connection, adapterEnabled: bool) -> list[str]:
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
	"""Parser and writer for /etc/wpa_supplicant/wpa_supplicant-<iface>.conf."""

	def __init__(self, iface: str):
		self.iface = iface
		self.path = f"{wpaSupplicantDir}/wpa_supplicant-{iface}.conf"
		self._writePath = self.path
		self._raw: list[str] = _readLines(self.path)
		self._header: list[str] = self._extractHeader()

	def exists(self) -> bool:
		return exists(self.path)

	def _extractHeader(self) -> list[str]:
		header: list[str] = []
		for line in self._raw:
			if line.strip().startswith("network"):
				break
			header.append(line)
		return header

	def parse(self) -> list[WiFiConfig]:
		configs: list[WiFiConfig] = []
		current: dict[str, str] | None = None
		depth = 0
		blockId = 0

		for line in self._raw:
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
				wlan = _wpaDictToWlanConfig(current, blockId)
				if wlan.ssid:
					configs.append(wlan)
				blockId += 1
				current = None
				depth = 0

		return configs

	def serialise(self, configs: list[WiFiConfig]) -> list[str]:
		header = self._header if self._header else list(_wpaDefaultHeader)
		lines: list[str] = list(header)
		if lines and lines[-1].strip():
			lines.append("")
		for idx, wlan in enumerate(configs):
			lines.extend(_wlanConfigToWpaBlock(wlan, idx))
			lines.append("")
		return lines

	def save(self, configs: list[WiFiConfig]) -> bool:
		return _writeLines(self._writePath, self.serialise(configs), backup=True)

	def ensureDir(self):
		makedirs(wpaSupplicantDir, exist_ok=True)


def _wpaDictToWlanConfig(fields: dict[str, str], blockId: int) -> WiFiConfig:
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
		idStr=fields.get("id_str", ""),
		disabled=fields.get("disabled", "0") == "1",
	)


def _wlanConfigToWpaBlock(wlan: WiFiConfig, blockId: int) -> list[str]:
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

	if wlan.idStr:
		lines.append(f'\tid_str="{wlan.idStr}"')
	if wlan.disabled:
		lines.append("\tdisabled=1")
	lines.append("}")
	return lines


# ===========================================================================
# Broadcom wl-config format
# ===========================================================================

def _bcmConfPath(iface: str) -> str:
	return f"/etc/wl.conf.{iface}"


def _bcmLoadWiFiConfig(iface: str) -> WiFiConfig:
	wlan = WiFiConfig()
	for line in _readLines(_bcmConfPath(iface)):
		line = line.strip()
		if not line or line.startswith("#"):
			continue
		key, sep, value = line.partition("=")
		key, value = key.strip(), value.strip()
		if key == "ssid":
			wlan.ssid = value
		elif key == "method":
			wlan.encryption = _legacyEncMap.get(value.lower(), encNone)
		elif key == "key":
			wlan.key = value
	return wlan


def _bcmSaveWlanConfig(iface: str, wlan: WiFiConfig) -> bool:
	encStr = {
		encNone: "None", encWep: "WEP", encWpa: "WPA",
		encWpa2: "WPA2", encWpaWpa2: "WPA2", encWpa3: "WPA2",
	}.get(wlan.encryption, "None")
	return _writeLines(_bcmConfPath(iface), [
		f"ssid={wlan.ssid}",
		f"method={encStr}",
		f"key={wlan.key}",
	])


# ===========================================================================
# Driver / module detection
# ===========================================================================

def _detectModule(iface: str) -> str:
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


def _detectDriverApi(iface: str, module: str) -> str:
	if exists(f"{_bcmTmpPrefix}/{iface}"):
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


def _canWakeOnWiFi(iface: str) -> bool:
	return iface == "wlan3" and bool(BoxInfo.getItem("wwol"))


# ===========================================================================
# WLAN configStrings (interfaces pre-up / pre-down)
# ===========================================================================

def _buildWlanConfigStrings(adapter: Adapter, conn: Connection) -> str:
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
		lines.append(f"pre-up {wlConfigScript} -m {encStr} -k {wlan.key} -s \"{_reEscape(wlan.ssid)}\" || true")
		lines.append(f"pre-up {ifconfigBin} {iface} up || true")
		lines.append(f"pre-up iwconfig {iface} essid \"{_reEscape(wlan.ssid)}\" || true")
		lines.append(f"post-down {wlConfigScript} -m NONE || true")
	else:
		driverFlags = f"-D {api}" if api != apiNl80211 else ""
		lines.append(f"pre-up {ifconfigBin} {iface} up || true")
		if wlan.encryption != encNone:
			lines.append(f"pre-up {wpaSupplicantBin} -i{iface} -c{adapter.wpaConfPath} -B {driverFlags} -P{adapter.wpaPidPath} || true")
		else:
			lines.append(f"pre-up iwconfig {iface} essid \"{_reEscape(wlan.ssid)}\" || true")
		lines.append(f"pre-down {wpaCliBin} -i{iface} terminate 2>/dev/null; true")

	return "\n".join(lines)


def _reEscape(text: str) -> str:
	return text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


# ===========================================================================
# DNS / nameserver files
# ===========================================================================

class NameserverFiles:
	"""Read and write /etc/resolv.conf + /etc/enigma2/nameserversdns.conf."""

	_reNs4 = compile(r"nameserver\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
	_reNs6 = compile(r"nameserver\s+(([0-9a-fA-F]{0,4}:){1,7}[0-9a-fA-F]{0,4})")

	def load(self, ns: NameserverConfig):
		path = resolvFile if ns.mode == "dhcp-router" else nameserverFile
		ns.servers = self._parse(path)

	def _parse(self, path: str) -> list:
		servers: list = []
		for line in _readLines(path):
			m4 = self._reNs4.match(line.strip())
			if m4:
				servers.append([int(x) for x in m4.group(1).split(".")])
				continue
			m6 = self._reNs6.match(line.strip())
			if m6:
				servers.append(m6.group(1))
		return servers

	def save(self, ns: NameserverConfig, anyDhcpActive: bool):
		lines = self._build(ns)
		if not anyDhcpActive:
			_writeLines(resolvFile, lines)
		if ns.mode != "dhcp-router":
			_writeLines(nameserverFile, lines)
		elif exists(nameserverFile):
			try:
				remove(nameserverFile)
			except OSError:
				pass

	def _build(self, ns: NameserverConfig) -> list[str]:
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


# ===========================================================================
# WlanRuntime – shell command builders for WLAN operations
# ===========================================================================

class WlanRuntime:
	"""Builds shell command lists for WLAN bring-up / tear-down."""

	def __init__(self, adapter: Adapter):
		self._adapter = adapter

	@property
	def _iface(self) -> str:
		return self._adapter.name

	def commandsActivate(self, conn: Connection) -> list[str]:
		iface = self._iface
		cmds: list[str] = []
		cmds.extend(self.commandsDeactivate())
		cmds.append(f"{ifconfigBin} {iface} up || true")
		if conn.wlan and conn.wlan.encryption != encNone:
			if self._adapter.driverApi == apiBrcmWl:
				cmds.extend(self._bcmUpCmds(conn))
			else:
				cmds.append(
					f"{wpaSupplicantBin} -B -D {self._adapter.driverApi} "
					f"-i{iface} -c{self._adapter.wpaConfPath} "
					f"-P{self._adapter.wpaPidPath} || true"
				)
		elif conn.wlan:
			cmds.append(f'iwconfig {iface} essid "{_reEscape(conn.wlan.ssid)}" || true')
		cmds.append(f"{ifupBin} {iface}")
		return cmds

	def commandsDeactivate(self) -> list[str]:
		iface = self._iface
		return [
			f"{wpaCliBin} -i{iface} terminate 2>/dev/null; true",
			f"{ifdownBin} {iface} 2>/dev/null; true",
			f"ip addr flush dev {iface} scope global 2>/dev/null; true",
		]

	def _bcmUpCmds(self, conn: Connection) -> list[str]:
		wlan = conn.wlan
		if wlan is None:
			return []
		encStr = {encWep: "WEP", encWpa: "WPA", encWpa2: "WPA2", encWpaWpa2: "WPA2"}.get(wlan.encryption, "NONE")
		return [f"{wlConfigScript} -m {encStr} -k {wlan.key} -s \"{_reEscape(wlan.ssid)}\" || true"]

	def statusCommands(self) -> list[str]:
		iface = self._iface
		if self._adapter.driverApi == apiBrcmWl:
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


def _isBlacklisted(iface: str) -> bool:
	return iface in ADAPTER_BLACKLIST


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
		self._manager = manager
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

	def _dispatch(self, line: str):
		if not line:
			return
		parts = line.split(",")
		evt = parts[0]
		if evt == "UPDATE":
			self._manager._onNetinfoUpdate()
		elif evt == "LINK" and len(parts) == 3:
			self._manager._onLinkChange(parts[1], parts[2] == "up")
		elif evt == "IP" and len(parts) == 3:
			self._manager._onIpChange(parts[1], parts[2])
		elif evt == "IFACE_ADD" and len(parts) == 2:
			self._manager._onIfaceAdd(parts[1])
		elif evt == "IFACE_REMOVE" and len(parts) == 2:
			self._manager._onIfaceRemove(parts[1])
		elif evt == "SCAN_TRIGGER" and len(parts) == 2:
			self._manager._onScanTrigger(parts[1])


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
# NetworkManager – central singleton
# ===========================================================================

class NetworkManager:
	"""Central access point for all network configuration."""

	def __init__(self):
		self.adapters: dict[str, Adapter] = {}
		self.nameserverConfig = NameserverConfig()
		self._ifacesFile = InterfacesFile()
		self._nsFiles = NameserverFiles()
		self._pendingRestart = None
		self._networkCheck = None
		self.onAdaptersChanged: list[Callable] = []
		self.load()
		self._eventReader = NetEventReader(self)

	# Called once by InitNetwork() during Enigma2 startup.
	def startNetworkCheck(self):
		self._networkCheck = NetworkCheck()
		self._networkCheck.start()

	# ------------------------------------------------------------------
	# Loading
	# ------------------------------------------------------------------

	def load(self):
		self._discoverAdapters()
		self._loadInterfacesFile()
		self._loadWpaSupplicantFiles()
		self._nsFiles.load(self.nameserverConfig)
		self._applyNetinfo()

	def _discoverAdapters(self):
		try:
			names = [x for x in listdir(sysfsNet) if not _isBlacklisted(x)]
		except OSError:
			names = []

		for name in names:
			isWlan = _isWireless(name)
			module = _detectModule(name)
			api = _detectDriverApi(name, module)
			adapter = Adapter(
				name=name,
				isWlan=isWlan,
				module=module,
				driverApi=api,
				canWakeOnWiFi=_canWakeOnWiFi(name),
				mac=_readSys(f"{sysfsNet}/{name}/address"),
			)
			try:
				flags = int(open(f"{sysfsNet}/{name}/flags").read().strip(), 16)
				adapter.kernelUp = bool(flags & 1)
			except OSError:
				pass
			self.adapters[name] = adapter
			self._detectWol(adapter)

	@staticmethod
	# Detect WoL capability at startup. socketdaemon will refine via _applyNetinfo().
	def _detectWol(adapter: Adapter):
		if adapter.isWlan:
			return
		try:
			proc = BoxInfo.getItem("WakeOnLAN")
			procType = BoxInfo.getItem("WakeOnLANType")
			if proc and exists(proc):
				adapter.canWakeOnLan = True
				adapter.wolProcPath = proc
				adapter.wolProcType = (procType or {}).get(True, "enabled")
		except Exception:
			pass

	def _loadInterfacesFile(self):
		self._ifacesFile.load()
		parsed, autoIfaces, wakeOnWiFiIfaces = self._ifacesFile.parse()
		for iface, conns in parsed.items():
			if iface not in self.adapters:
				self.adapters[iface] = Adapter(
					name=iface,
					isWlan=_isWirelessName(iface),
					driverApi=apiNl80211,
				)
			self.adapters[iface].connections = conns
			self.adapters[iface].adapterEnabled = iface in autoIfaces
			if iface in wakeOnWiFiIfaces:
				for conn in conns:
					conn.wakeOnWiFi = True
		for iface, adapter in self.adapters.items():
			if not adapter.connections:
				adapter.connections = [Connection(
					adapter=iface,
					name=iface,
					dhcp=True,
					wlan=WiFiConfig() if adapter.isWlan else None,
				)]

	def _loadWpaSupplicantFiles(self):
		for iface, adapter in self.adapters.items():
			if not adapter.isWlan:
				continue
			if adapter.driverApi == apiBrcmWl:
				self._mergeWiFiConfig(adapter, _bcmLoadWiFiConfig(iface))
			else:
				wpf = WpaSupplicantFile(iface)
				if not wpf.exists():
					continue
				for wlan in wpf.parse():
					self._mergeWiFiConfig(adapter, wlan)

	@staticmethod
	def _mergeWiFiConfig(adapter: Adapter, wlan: WiFiConfig):
		bySsid = {x.wlan.ssid: x for x in adapter.connections if x.wlan and x.wlan.ssid}
		profileName = wlan.idStr if wlan.idStr else wlan.ssid
		if wlan.ssid in bySsid:
			conn = bySsid[wlan.ssid]
			conn.wlan = wlan
			conn.enabled = not wlan.disabled
			if wlan.idStr:
				conn.name = profileName
		else:
			adapter.connections.append(Connection(
				adapter=adapter.name,
				name=profileName,
				dhcp=True,
				enabled=not wlan.disabled,
				priority=wlan.wpaId or 0,
				wlan=wlan,
			))

	# ------------------------------------------------------------------
	# Saving
	# ------------------------------------------------------------------

	def save(self) -> bool:
		ok = True
		for iface, adapter in self.adapters.items():
			if adapter.isWlan:
				continue
			# Only emit the ethtool WoL pre-up if the hardware actually
			# supports it and it's actually turned on – never carry over a
			# stale/unsupported setting from a previously parsed file.
			# canWakeOnLan alone is not proof: it's also set from a generic
			# per-model /proc control path (_detectWol) that may exist even
			# when the NIC chip has no real WoL support. kernelWolSupported
			# is the actual ethtool-reported capability bitmask.
			activeConn = adapter.activeConnection()
			hwSupportsWol = adapter.canWakeOnLan and adapter.kernelWolSupported != 0
			mode = activeConn.wakeOnLan if (activeConn and hwSupportsWol) else "off"
			self._updateWolPreup(adapter, mode)
		for iface, adapter in self.adapters.items():
			if not adapter.isWlan:
				continue
			for conn in adapter.connections:
				# Only real SSID profiles carry a usable wlan config; the base
				# (non-SSID) placeholder's WifiConfig is always empty and must
				# not be used to build pre-up/pre-down commands.
				if conn.wlan and conn.wlan.ssid:
					cs = _buildWlanConfigStrings(adapter, conn)
					conn.extraLines = [x for x in cs.splitlines() if x] if cs else []

		# For WLAN: write exactly ONE base block to interfaces (IP config + pre-up/pre-down).
		# SSID connections are managed exclusively via wpa_supplicant.conf.
		# Multiple base connections can accumulate from legacy files — collapse to one.
		connMap = {}
		for iface, adapter in self.adapters.items():
			if adapter.isWlan:
				baseConns = [x for x in adapter.connections if not (x.wlan and x.wlan.ssid)]
				if baseConns:
					enabled = [x for x in baseConns if x.enabled]
					baseConn = enabled[0] if enabled else baseConns[0]
					# Sync base connection enabled with active SSID state.
					# Exception: WoW-Only mode keeps base enabled so the iface stanza stays active.
					wpaConns = [x for x in adapter.connections if x.wlan and x.wlan.ssid]
					if wpaConns:
						wowOnly = any(x.wakeOnWifi and not x.enabled for x in wpaConns)
						baseConn.enabled = wowOnly or any(x.enabled for x in wpaConns)
						# The base connection is the only one written to
						# /etc/network/interfaces, so it must carry the
						# active SSID's pre-up/pre-down commands.
						activeWpa = max((x for x in wpaConns if x.enabled), key=lambda conn: conn.priority, default=None)
						baseConn.extraLines = activeWpa.extraLines if activeWpa else []
					else:
						baseConn.extraLines = []
					connMap[iface] = [baseConn]
				else:
					connMap[iface] = []
			else:
				connMap[iface] = adapter.connections
		adapterEnabledMap = {}
		for iface, adapter in self.adapters.items():
			enabled = adapter.adapterEnabled
			if adapter.isWlan and enabled:
				# In wpa_supplicant mode: only mark adapter enabled if an SSID is active.
				wpaConns = [x for x in adapter.connections if x.wlan and x.wlan.ssid]
				if wpaConns and not any(x.enabled for x in wpaConns):
					enabled = False
			adapterEnabledMap[iface] = enabled
		ok = self._ifacesFile.save(connMap, adapterEnabledMap) and ok

		for iface, adapter in self.adapters.items():
			if not adapter.isWlan:
				continue
			for conn in adapter.connections:
				if conn.wlan is not None and conn.name and conn.name != conn.wlan.ssid:
					conn.wlan.idStr = conn.name
				if conn.wlan is not None and conn.wlan.ssid:
					conn.wlan.disabled = not conn.enabled
			wlanConfigs = [x.wlan for x in adapter.connections if x.wlan is not None and x.wlan.ssid]
			if not wlanConfigs:
				continue
			if adapter.driverApi == apiBrcmWl:
				active = adapter.activeConnection()
				if active and active.wlan:
					ok = _bcmSaveWlanConfig(iface, active.wlan) and ok
			else:
				wpf = WpaSupplicantFile(iface)
				wpf.ensureDir()
				ok = wpf.save(wlanConfigs) and ok

		anyDhcp = any(conn.dhcp for adapter in self.adapters.values() for conn in adapter.connections if conn.enabled)
		self._nsFiles.save(self.nameserverConfig, anyDhcp)
		self._notifyNetworkPlugins(True)
		return ok

	# ------------------------------------------------------------------
	# Runtime
	# ------------------------------------------------------------------

	def activateCommands(self, iface: str) -> list[str]:
		adapter = self.adapters.get(iface)
		if not adapter:
			return []
		conn = adapter.activeConnection()
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
		def _done(retval: int = 0):
			self._discoverAdapters()
			if callback:
				callback()
		self._pendingRestart = ServiceAction.netrestart(_done, iface=iface)

	# ------------------------------------------------------------------
	# Accessors
	# ------------------------------------------------------------------

	def getAdapter(self, iface: str) -> Adapter | None:
		return self.adapters.get(iface)

	def getConnections(self, iface: str) -> list[Connection]:
		adapter = self.adapters.get(iface)
		return adapter.connections if adapter else []

	def getActiveConnection(self, iface: str) -> Connection | None:
		adapter = self.adapters.get(iface)
		return adapter.activeConnection() if adapter else None

	def getWlanConnections(self, iface: str) -> list[Connection]:
		return [x for x in self.getConnections(iface) if x.isWlan]

	def addConnection(self, conn: Connection):
		adapter = self.adapters.get(conn.adapter)
		if adapter:
			adapter.connections.append(conn)

	def removeConnection(self, iface: str, ssid: str) -> bool:
		adapter = self.adapters.get(iface)
		if not adapter:
			return False
		before = len(adapter.connections)
		adapter.connections = [x for x in adapter.connections if not (x.wlan and x.wlan.ssid == ssid)]
		return len(adapter.connections) < before

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

	# Fire WHERE_NETWORKCONFIG_READ plugins – but ONLY when at least one
	def _notifyNetworkPlugins(self, reason: bool):
		active = any(
			x.kernelUp and any(octet != 0 for octet in x.kernelIp)
			for x in self.adapters.values()
		)
		if not active:
			return
		try:
			for plugin in plugins.getPlugins(PluginDescriptor.WHERE_NETWORKCONFIG_READ):
				plugin(reason=reason)
		except Exception:
			pass

	def activateInterface(self, iface, callback=None):
		adapter = self.adapters.get(iface)
		if adapter and not adapter.isWlan:
			def _lanUp(retval: int):
				self._notifyNetworkPlugins(False)
				if callback:
					callback(retval == 0)
			self._pendingRestart = ServiceAction.ifup(iface, _lanUp)
			return

		def _wlanUp(retval: bool = True):
			self._notifyNetworkPlugins(False)
			if callback:
				callback(True)
		try:
			cmds = self.activateCommands(iface)
			Console().eBatch(cmds, lambda result: _wlanUp(), debug=True)
		except Exception:
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
		others = [x for x in adapter.connections if x is not targetConn]
		maxOther = max((x.priority for x in others), default=0)
		targetConn.priority = maxOther + 10
		cmds: list[str] = []
		wpaId = targetConn.wlan.wpaId if targetConn.wlan else None
		ctrl = adapter.wpaCtrlPath
		if exists(ctrl) and wpaId is not None:
			cmds.append(f"{wpaCliBin} -i{iface} disable_network all 2>/dev/null; true")
			cmds.append(f"{wpaCliBin} -i{iface} enable_network {wpaId}")
			cmds.append(f"{wpaCliBin} -i{iface} select_network {wpaId}")
			cmds.append(f"{wpaCliBin} -i{iface} reassociate")
		else:
			cmds.extend(WlanRuntime(adapter).commandsActivate(targetConn))
		return cmds

	def getWlanNetworkList(self, iface: str) -> list[str]:
		return [f"{wpaCliBin} -i{iface} list_networks"]

	def wpaSupplicantRunning(self, iface: str) -> bool:
		adapter = self.adapters.get(iface)
		return exists(adapter.wpaCtrlPath) if adapter else False

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
	# Wake-on-LAN
	# ------------------------------------------------------------------

	def getWakeOnLan(self, iface: str) -> str:
		try:
			out = check_output([ethtoolBin, iface], stderr=DEVNULL, timeout=2).decode(errors="replace")
			match = search(r"Wake-on:\s*(\S+)", out)
			return match.group(1) if match else "off"
		except Exception:
			return "off"

	def setWakeOnLanCommands(self, iface: str, mode: str) -> list[str]:
		adapter = self.adapters.get(iface)
		if adapter is None or adapter.isWlan:
			return []
		cmds: list[str] = [f"{ethtoolBin} -s {iface} wol {mode}"]
		if adapter.wolProcPath and exists(adapter.wolProcPath):
			procVal = (adapter.wolProcType.replace("enabled", "disabled") if mode == "off" else adapter.wolProcType) or ("0" if mode == "off" else "enabled")
			cmds.append(f"echo '{procVal}' > {adapter.wolProcPath}")
		conn = adapter.activeConnection()
		if conn:
			conn.wakeOnLan = mode
		self._updateWolPreup(adapter, mode)
		return cmds

	def _updateWolPreup(self, adapter: Adapter, mode: str):
		conn = adapter.activeConnection()
		if conn is None:
			return
		tag = f"pre-up {ethtoolBin} -s {adapter.name} wol "
		conn.extraLines = [x for x in conn.extraLines if not x.startswith(tag)]
		if mode != "off":
			conn.extraLines.insert(0, f"{tag}{mode} || true")

	# ------------------------------------------------------------------
	# Wake-on-WiFi
	# ------------------------------------------------------------------

	def setWakeOnWifiCommands(self, iface: str, enable: bool) -> list[str]:
		adapter = self.adapters.get(iface)
		if adapter is None or not adapter.canWakeOnWifi:
			return []
		for conn in adapter.connections:
			conn.wakeOnWifi = enable
		cmds: list[str] = []
		if enable:
			cmds.append(f"wl -i {iface} wowl 0x100")
			cmds.append(f"wl -i {iface} wowl_activate")
		else:
			cmds.append(f"wl -i {iface} wowl 0")
		procPath = BoxInfo.getItem("WakeOnLAN") or ""
		if procPath and exists(procPath):
			cmds.append(f"echo '{'enable' if enable else 'disable'}' > {procPath}")
		self._updateWowPreup(adapter, enable)
		return cmds

	def _updateWowPreup(self, adapter: Adapter, enable: bool):
		baseConn = next((x for x in adapter.connections if not (x.wlan and x.wlan.ssid)), None)
		if baseConn is None:
			return
		iface = adapter.name
		baseConn.extraLines = [x for x in baseConn.extraLines if "wowl" not in x]
		if enable:
			baseConn.extraLines.insert(0, f"pre-up wl -i {iface} wowl_activate || true")
			baseConn.extraLines.insert(0, f"pre-up wl -i {iface} wowl 0x100 || true")

	def getWakeOnWifi(self, iface: str) -> bool:
		adapter = self.adapters.get(iface)
		if adapter is None:
			return False
		conn = adapter.activeConnection()
		return conn.wakeOnWifi if conn else False

	# ------------------------------------------------------------------
	# Link speed (forced, non-auto-negotiated)
	# ------------------------------------------------------------------

	def getSupportedLinkSpeeds(self, iface: str) -> list[tuple[str, str]]:
		choices = [("auto", _("Auto"))]
		adapter = self.adapters.get(iface)
		if adapter is None or adapter.isWlan:
			return choices
		mask = adapter.kernelLinkSupported
		for _ethtoolMode, (bits, label) in _LINKSPEED_BITS.items():
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
	# Event handlers (called by NetEventReader)
	# ------------------------------------------------------------------

	def _notifyAdaptersChanged(self):
		for cb in self.onAdaptersChanged:
			try:
				cb()
			except Exception:
				pass

	# Update adapter runtime state from /var/run/netinfo without a full rescan.
	def _applyNetinfo(self):
		info = _readNetinfo()
		ifaces = info.get("interfaces", {})
		for iface, data in ifaces.items():
			adapter = self.adapters.get(iface)
			if adapter is None:
				continue
			adapter.kernelUp = data.get("up", False)
			ip4 = data.get("ip4", "")
			if ip4:
				adapter.kernelIp = _parseIp4(ip4)
				mask = data.get("mask", "")
				if mask:
					adapter.kernelNetmask = _parseIp4(mask)
				gw = data.get("gw", "")
				if gw:
					adapter.kernelGateway = _parseIp4(gw)
			adapter.kernelDriver = data.get("driver", "")
			adapter.kernelHwId = data.get("hw_id", "")
			adapter.kernelIp6 = data.get("ip6", [])
			if adapter.isWlan:
				adapter.kernelSsid = data.get("ssid", "")
				adapter.kernelLink = bool(adapter.kernelSsid)  # link = associated to AP
				adapter.kernelBssid = data.get("bssid", "")
				adapter.kernelFreqMhz = data.get("freq_mhz", 0)
				adapter.kernelChannel = data.get("channel", 0)
				adapter.kernelBitrateBps = data.get("bitrate_bps", 0)
				adapter.kernelSignal = data.get("signal_dbm", 0)
			else:
				adapter.kernelLink = data.get("link", False)
				adapter.kernelSpeed = data.get("speed", -1)
				adapter.kernelDuplex = data.get("duplex", "")
				adapter.kernelPort = data.get("port", "")
				adapter.kernelTransceiver = data.get("transceiver", "")
				adapter.kernelAutoneg = data.get("autoneg", False)
				adapter.kernelLinkSupported = data.get("link_supported", 0)
				wol = data.get("wol_supported", 0)
				if wol:
					adapter.kernelWolSupported = wol
					adapter.canWakeOnLan = True

	def _onNetinfoUpdate(self):
		self._applyNetinfo()
		self._notifyAdaptersChanged()

	def _onLinkChange(self, iface: str, up: bool):
		adapter = self.adapters.get(iface)
		if adapter:
			adapter.kernelUp = up
			if adapter.isWlan:
				# WLAN link = AP association; only clear on down — set on netinfo update
				if not up:
					adapter.kernelLink = False
					adapter.kernelSsid = ""
			else:
				adapter.kernelLink = up
		self._notifyAdaptersChanged()

	def _onIpChange(self, iface: str, ipPrefix: str):
		adapter = self.adapters.get(iface)
		if adapter:
			adapter.kernelIp = _parseIp4(ipPrefix.split("/")[0])
		self._notifyAdaptersChanged()

	# Ping 8.8.8.8 (fallback 1.1.1.1) for each adapter that has physical link
	def checkConnectionInternet(self, callback: Callable[[dict[str, bool]], None]):
		candidates = [
			iface
			for iface, adapter in self.adapters.items()
			if adapter.kernelLink and (
				conn := adapter.activeConnection()
			) is not None and (conn.dhcp or conn.gateway != [0, 0, 0, 0])
		]
		if not candidates:
			callback({})
			return

		results: dict[str, bool] = {}
		remaining = [len(candidates)]

		def _onResult(iface: str, ok: bool):
			results[iface] = ok
			remaining[0] -= 1
			if remaining[0] == 0:
				callback(results)

		def _check(iface: str):
			ok = pingHost("8.8.8.8", iface) or pingHost("1.1.1.1", iface)
			reactor.callFromThread(_onResult, iface, ok)

		for iface in candidates:
			reactor.callInThread(_check, iface)

	def _onIfaceAdd(self, iface: str):
		if iface not in self.adapters:
			self._discoverAdapters()
		self._notifyAdaptersChanged()

	def _onIfaceRemove(self, iface: str):
		self.adapters.pop(iface, None)
		self._notifyAdaptersChanged()

	def _onScanTrigger(self, iface: str):
		pass  # placeholder: trigger wpa_cli scan when WLAN comes up


# ===========================================================================
# Internet connectivity check (ICMP via raw socket, threaded)
# ===========================================================================

def _icmpChecksum(data: bytes) -> int:
	checksum = 0
	for idx in range(0, len(data) - len(data) % 2, 2):
		checksum += data[idx] + (data[idx + 1] << 8)
	if len(data) % 2:
		checksum += data[-1]
	while checksum >> 16:
		checksum = (checksum & 0xFFFF) + (checksum >> 16)
	return ~checksum & 0xFFFF


# Send one ICMP Echo Request to host bound to iface. Returns True on reply.
def pingHost(host: str, iface: str, timeout: float = 2.0) -> bool:
	sock = None
	try:
		sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, (iface + "\0").encode())
		pid = getpid() & 0xFFFF
		hdr = pack("!BBHHH", 8, 0, 0, pid, 1)
		payload = b"e2net"
		cs = _icmpChecksum(hdr + payload)
		sock.sendto(pack("!BBHHH", 8, 0, cs, pid, 1) + payload, (host, 0))
		deadline = monotonic() + timeout
		while monotonic() < deadline:
			sock.settimeout(max(0.05, deadline - monotonic()))
			try:
				data, _addr = sock.recvfrom(1024)
				if len(data) >= 28:
					rtype, _code, _checksum, rid, _seq = unpack("!BBHHH", data[20:28])
					if rtype == 0 and rid == pid:
						return True
			except socket.timeout:
				break
	except Exception:
		pass
	finally:
		if sock:
			try:
				sock.close()
			except Exception:
				pass
	return False


# Ping host bound to iface in a background thread; calls callback(ok: bool) on main thread.
def pingAsync(host: str, iface: str, callback):
	try:
		reactor.callInThread(lambda: reactor.callFromThread(callback, pingHost(host, iface)))
	except Exception:
		callback(False)


# ===========================================================================
# Module-level singleton
# ===========================================================================

networkManager = NetworkManager()

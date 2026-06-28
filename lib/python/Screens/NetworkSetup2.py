"""
NetworkSetup2.py – Network connection screens for Enigma2 / OpenATV

Screens:
	NetworkConnections          – lists all connections; MENU/OK opens context menu
	NetworkConnectionSetup      – Setup subclass for one Connection (BLUE → per-connection DNS)
	DnsSettings                 – global system DNS (config.usage.dns.*, iNetworkManager)
	NetworkConnectionDnsSetup   – optional per-connection DNS override
	ScanResult                  – dataclass for one iwlist scan result
	WlanScanScreen              – live iwlist scan, sorted by signal strength
	WlanActivator               – ifup + wpa_supplicant + IP poll
	WlanAddFlow                 – stateless coordinator / entry point

Coding conventions (OpenATV):
	Indentation  : tabs
	Variables    : camelCase (first letter lower)
	Functions    : camelCase (first letter lower)
	Classes      : PascalCase (first letter upper)
	Private      : _camelCase prefix
"""

from __future__ import annotations

import re
import netifaces

from dataclasses import dataclass
from os import rename
from os.path import exists, realpath

from ipaddress import ip_address

from enigma import eTimer, gRGB

from Components.ActionMap import HelpableActionMap
from Components.Label import Label
from Components.Console import Console
from Components.config import (
	ConfigIP, ConfigNumber, ConfigPassword, ConfigSelection,
	ConfigText, ConfigYesNo, NoSave, ReadOnly, config, getConfigListEntry,
)
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo
from Screens.ChoiceBox import ChoiceBox
from Screens.Information import InformationBase, formatLine
from Screens.MessageBox import MessageBox
from Screens.RestartNetwork import RestartNetworkNew
from Screens.Screen import Screen
from Screens.Setup import Setup
from skin import parseColor
from Tools.Conversions import formatNetworkSpeed
from Tools.Directories import SCOPE_GUISKIN, SCOPE_SKINS, fileReadLines, fileReadXML, fileWriteLines, resolveFilename
from Tools.LoadPixmap import LoadPixmap
from Tools.ServiceAction import ServiceAction
from Components.NetworkManager import (
	Adapter, Connection, WlanConfig,
	iNetworkManager as nm,
	encNone, encWep, encWpa, encWpa2, encWpa3, pingAsync
)


MODULE_NAME = __name__.split(".")[-1]

_COLOR_LINK = gRGB(0x0000CC00).argb()  # green  – physical link up
_COLOR_ENABLED = gRGB(0x00FFFFFF).argb()  # white  – enabled, no link
_COLOR_GRAY = gRGB(0x00808080).argb()  # gray   – disabled

_DUPLEX_LABELS = {"full": lambda: _("Full duplex"), "half": lambda: _("Half duplex")}

# ---------------------------------------------------------------------------
# Encryption choices
# ---------------------------------------------------------------------------

encryptionChoices = [
	(encNone, _("None")),
	(encWep, _("WEP")),
	(encWpa, _("WPA")),
	(encWpa2, _("WPA2")),
	(encWpa3, _("WPA3 (SAE)")),
]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_ENC_SHORT = {encNone: "open", encWep: "WEP", encWpa: "WPA", encWpa2: "WPA2", encWpa3: "WPA3"}
_ICON_LAN = chr(0xEA5A)   # settings_ethernet
_ICON_WLAN = chr(0xE9FE)  # wifi
_ICON_INET = chr(0xEA5B)  # globe
_ICON_CHECKBOX_ON = chr(0xE91B)   # check_box
_ICON_CHECKBOX_OFF = chr(0xE91F)  # check_box_outline_blank
_ICON_LINK_ACTIVE = chr(0xEA62)    # arrow_circle_up
_ICON_LINK_INACTIVE = chr(0xEA5C)  # arrow_circle_down
_ICON_BRANCH = chr(0xF001)         # branch (tree connector)
_ICON_LAST_CHILD = chr(0xF002)     # last_child (tree connector)


def _connLabel(conn: Connection, adapter: Adapter) -> str:
	if conn.isWlan and conn.wlan and conn.wlan.ssid:
		return f"{conn.adapter}  │  {conn.wlan.ssid}  [{_ENC_SHORT.get(conn.wlan.encryption, conn.wlan.encryption)}]"
	mode = "DHCP" if conn.dhcp else conn.ipStr()
	return f"{conn.adapter}  │  {mode}"


def _connLiveIp(adapter: Adapter) -> str:
	ip = ".".join(str(b) for b in adapter.kernelIp)
	return "" if ip == "0.0.0.0" else ip


def _adapterLocation(adapter: Adapter) -> str:
	if adapter.kernelTransceiver == "internal":
		return _("Intern")
	if adapter.kernelTransceiver == "external":
		return _("Extern")
	link = f"/sys/class/net/{adapter.name}/device"
	if exists(link):
		return _("Extern") if "usb" in realpath(link).lower() else _("Intern")
	return ""


def _connLine1(conn: Connection, adapter: Adapter) -> str:
	liveIp = _connLiveIp(adapter)
	liveIp = f"  IP: {liveIp}" if liveIp else ""
	if conn.isWlan:
		profileName = conn.name or (conn.wlan.ssid if conn.wlan else "") or conn.adapter
		return f"{_('Profile')}: {profileName}" + liveIp
	return _("LAN connection") + liveIp


def _connLine2(conn: Connection, adapter: Adapter) -> str:
	parts = []
	if adapter.isWlan:
		if adapter.kernelBitrateBps:
			parts.append(f"{adapter.kernelBitrateBps // 1000000} Mbit/s")
		if adapter.kernelSignal:
			parts.append(f"{adapter.kernelSignal} dBm")
	else:
		if adapter.kernelSpeed > 0:
			parts.append(formatNetworkSpeed(adapter.kernelSpeed))
	mask = _ip4Str(adapter.kernelNetmask)
	gw = _ip4Str(adapter.kernelGateway)
	if adapter.adapterEnabled:
		if mask:
			parts.append(f"Mask: {mask}")
		if gw and _connLiveIp(adapter):
			parts.append(f"GW: {gw}")
	return "   ".join(parts)


def _ip4Str(addr: list) -> str:
	s = ".".join(str(b) for b in addr)
	return "" if s == "0.0.0.0" else s


# ===========================================================================
# DnsSettings – global system DNS (drop-in replacement for DNSSettings)
# ===========================================================================
class DnsSettings(Setup):
	"""Global system DNS configuration. Uses iNetworkManager (NetworkManager.py)."""

	def __init__(self, session):
		dnsInitial = list(nm.nameserverConfig.servers) if nm is not None else []
		self.dnsOptions = {}
		self.dnsServers = []
		self.dnsServerItems = []

		if BoxInfo and BoxInfo.getItem("DNSCrypt"):
			self.dnsOptions["dnscrypt"] = [[127, 0, 0, 1]]

		fileDom = fileReadXML(resolveFilename(SCOPE_SKINS, "dnsservers.xml"), source=MODULE_NAME)
		if fileDom is not None:
			for dns in fileDom.findall("dnsserver"):
				key = dns.get("key", "")
				if not key:
					continue
				addresses = []
				for ipv4 in [x.strip() for x in (dns.get("ipv4", "") or "").split(",") if x.strip()]:
					addresses.append([int(x) for x in ipv4.split(".")])
				for ipv6 in [x.strip() for x in (dns.get("ipv6", "") or "").split(",") if x.strip()]:
					addresses.append(ipv6)
				if addresses:
					self.dnsOptions[key] = addresses

		gw = self._defaultGw()
		self.dnsOptions["custom"] = [gw, [0, 0, 0, 0], "", ""]
		self.dnsOptions["dhcp-router"] = [gw, [0, 0, 0, 0], "", ""]

		if config.usage.dns.value not in self.dnsOptions:
			config.usage.dns.value = "custom"

		v4pos = 0
		v6pos = 2
		for addr in dnsInitial:
			if isinstance(addr, list) and len(addr) == 4 and v4pos < 2:
				self.dnsOptions["custom"][v4pos] = addr
				self.dnsOptions["dhcp-router"][v4pos] = addr
				v4pos += 1
			elif isinstance(addr, str):
				try:
					if ip_address(addr).version == 6 and v6pos < 4:
						self.dnsOptions["custom"][v6pos] = addr
						self.dnsOptions["dhcp-router"][v6pos] = addr
						v6pos += 1
				except ValueError:
					pass

		Setup.__init__(self, session=session, setup="DNS")
		self["key_yellow"] = StaticText()
		self["key_blue"] = StaticText()
		self["moveActions"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.moveItemUp, _("Move item up")),
			"blue": (self.moveItemDown, _("Move item down")),
		}, prio=0, description=_("DNS Settings Actions"))

	def _defaultGw(self) -> list[int]:
		if nm is None:
			return [0, 0, 0, 0]
		for iface in sorted(nm.adapters.keys()):
			adapter = nm.adapters[iface]
			if adapter.kernelUp:
				conn = adapter.activeConnection()
				if conn:
					return list(conn.gateway)
		return [0, 0, 0, 0]

	def createSetup(self):  # noqa
		if config.usage.dns.value != "dnscrypt":
			self.dnsServers = self.dnsOptions[config.usage.dns.value][:]
			v4 = config.usage.dnsMode.value != 3
			v6 = config.usage.dnsMode.value != 2
			self.dnsServerItems = []
			if config.usage.dns.value == "custom":
				items = []
				if v4:
					items.append(NoSave(ConfigIP(self.dnsServers[0])))
					items.append(NoSave(ConfigIP(self.dnsServers[1])))
				if v6:
					items.append(NoSave(ConfigText(default=self.dnsServers[2], fixed_size=False)))
					items.append(NoSave(ConfigText(default=self.dnsServers[3], fixed_size=False)))
			else:
				items = []
				for addr in self.dnsServers:
					if v4 and isinstance(addr, list) and len(addr) == 4:
						items.append(ReadOnly(NoSave(ConfigIP(default=addr))))
					elif v6 and isinstance(addr, str):
						items.append(ReadOnly(NoSave(ConfigText(default=addr, fixed_size=False))))
			for item, entry in enumerate(items, start=1):
				name = _("Name server %d") % item
				if config.usage.dns.value != "custom":
					name = (name, 0)
				self.dnsServerItems.append(getConfigListEntry(
					name, entry,
					_("Enter DNS (Dynamic Name Server) %d's IP address.") % item,
				))
		else:
			self.dnsServerItems = []
		Setup.createSetup(self, appendItems=self.dnsServerItems)

	def changedEntry(self):
		if config.usage.dns.value == "custom":
			current = self["config"].getCurrent()
			if current in self.dnsServerItems:
				idx = self.dnsServerItems.index(current)
				if config.usage.dnsMode.value == 3:
					idx += 2
				self.dnsServers[idx] = current[1].value
		result = Setup.changedEntry(self)
		self._updateMoveActions()
		return result

	def _updateMoveActions(self):
		current = self["config"].getCurrent()
		canMove = current in self.dnsServerItems and config.usage.dns.value not in ("dnscrypt", "dhcp-router")
		self["moveActions"].setEnabled(canMove)
		self["key_yellow"].setText(_("Move Up") if canMove else "")
		self["key_blue"].setText(_("Move Down") if canMove else "")

	def moveItemUp(self):
		current = self["config"].getCurrent()
		if current in self.dnsServerItems:
			idx = self.dnsServerItems.index(current)
			if idx > 0:
				servers = self.dnsOptions[config.usage.dns.value]
				servers[idx], servers[idx - 1] = servers[idx - 1], servers[idx]
				self.createSetup()

	def moveItemDown(self):
		current = self["config"].getCurrent()
		if current in self.dnsServerItems:
			idx = self.dnsServerItems.index(current)
			if idx < len(self.dnsServerItems) - 1:
				servers = self.dnsOptions[config.usage.dns.value]
				servers[idx], servers[idx + 1] = servers[idx + 1], servers[idx]
				self.createSetup()

	def keySave(self):
		if nm is not None:
			servers: list = []
			if config.usage.dns.value == "dnscrypt":
				servers = [[127, 0, 0, 1]]
			elif config.usage.dns.value == "custom":
				for item in self.dnsServerItems:
					val = item[1].value
					if val:
						servers.append(val)
			else:
				for val in self.dnsServers:
					if val:
						servers.append(val)
			nm.setNameservers(servers)
			nm.save()
			if config.usage.dns.value == "dnscrypt":
				self.writeDnsCryptToml()
		hasChanges = False
		for notifier in self.onSave:
			notifier()
		for item in self["config"].list:
			if len(item) > 1 and item[1].isChanged():
				hasChanges = True
				break
		if hasChanges:
			self.saveAll()
			RestartNetworkNew.start(callback=self.close)
		else:
			self.close()

	# ------------------------------------------------------------------
	# DNSCrypt TOML helpers
	# ------------------------------------------------------------------

	def _tomlBool(self, val):
		return "true" if bool(val) else "false"

	def _tomlStr(self, val):
		return '"' + str(val).replace("\\", "\\\\").replace('"', '\\"') + '"'

	def _tomlInt(self, val, default=0):
		try:
			return str(int(val))
		except Exception:
			return str(int(default))

	def _replaceKeyLine(self, line, key, newRhs, foundSet):
		ls = line.lstrip()
		indent = line[:len(line) - len(ls)]
		if ls.startswith(f"{key} ") or ls.startswith(f"{key}=") or ls.startswith(f"#{key} ") or ls.startswith(f"#{key}="):
			foundSet.add(key)
			return f"{indent}{key} = {newRhs}"
		return line

	def _findGlobalEnd(self, lines):
		for i, line in enumerate(lines):
			s = line.lstrip()
			if s.startswith("[") and s.rstrip().endswith("]") and not s.startswith("#"):
				return i
		return len(lines)

	def _insertGlobalKey(self, lines, key, rhs, anchorKeys, foundSet):
		if key in foundSet:
			return
		endGlobal = self._findGlobalEnd(lines)
		insertAt = None
		for i in range(endGlobal):
			s = lines[i].lstrip()
			for a in anchorKeys:
				if s.startswith(f"{a} ") or s.startswith(f"{a}=") or s.startswith(f"#{a} ") or s.startswith(f"#{a}="):
					insertAt = i + 1
		lines.insert(insertAt if insertAt is not None else endGlobal, f"{key} = {rhs}")
		foundSet.add(key)

	def _findSectionRange(self, lines, sectionName):
		start = None
		for i, line in enumerate(lines):
			s = line.lstrip()
			if s.startswith("[") and s.rstrip().endswith("]") and not s.startswith("#"):
				name = s.strip()[1:-1].strip()
				if start is None and name == sectionName:
					start = i + 1
					continue
				if start is not None:
					return (start, i)
		return (start, len(lines)) if start is not None else (None, None)

	def _insertSectionKey(self, lines, sectionName, key, rhs, anchorKeys, foundSet):
		token = f"{sectionName}.{key}"
		if token in foundSet:
			return
		start, end = self._findSectionRange(lines, sectionName)
		if start is None:
			return
		insertAt = None
		for i in range(start, end):
			s = lines[i].lstrip()
			for a in anchorKeys:
				if s.startswith(f"{a} ") or s.startswith(f"{a}=") or s.startswith(f"#{a} ") or s.startswith(f"#{a}="):
					insertAt = i + 1
		lines.insert(insertAt if insertAt is not None else end, f"{key} = {rhs}")
		foundSet.add(token)

	def writeDnsCryptToml(self):
		tomlPath = "/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
		oldLines = fileReadLines(tomlPath, source=MODULE_NAME)
		if not oldLines:
			return
		found = set()
		newLines = []
		currentSection = None
		for line in oldLines:
			ls = line.lstrip()
			if ls.startswith("[") and ls.rstrip().endswith("]") and not ls.startswith("#"):
				currentSection = ls.strip()[1:-1].strip()
				newLines.append(line)
				continue
			if currentSection is None:
				line = self._replaceKeyLine(line, "ipv4_servers", self._tomlBool(config.usage.dnsMode.value != 3), found)
				line = self._replaceKeyLine(line, "ipv6_servers", self._tomlBool(config.usage.dnsMode.value != 2), found)
				line = self._replaceKeyLine(line, "dnscrypt_servers", self._tomlBool(config.usage.DNSCryptProtocol.value), found)
				line = self._replaceKeyLine(line, "doh_servers", self._tomlBool(config.usage.DNSCryptDoH.value), found)
				line = self._replaceKeyLine(line, "odoh_servers", self._tomlBool(config.usage.DNSCryptODoH.value), found)
				line = self._replaceKeyLine(line, "require_dnssec", self._tomlBool(config.usage.DNSCryptDNSSEC.value), found)
				line = self._replaceKeyLine(line, "require_nolog", self._tomlBool(config.usage.DNSCryptNoLog.value), found)
				line = self._replaceKeyLine(line, "require_nofilter", self._tomlBool(config.usage.DNSCryptNoFilter.value), found)
				line = self._replaceKeyLine(line, "cache", self._tomlBool(config.usage.DNSCryptCache.value), found)
				newLines.append(line)
				continue
			if currentSection == "monitoring_ui":
				for attr, key, val in [
					("DNSCryptUI", "enabled", self._tomlBool(config.usage.DNSCryptUI.value)),
					(None, "listen_address", self._tomlStr(f"0.0.0.0:{self._tomlInt(config.usage.DNSCryptPort.value, 9012)}")),
					("DNSCryptUsername", "username", self._tomlStr(config.usage.DNSCryptUsername.value.strip())),
					("DNSCryptPassword", "password", self._tomlStr(config.usage.DNSCryptPassword.value.strip())),
					("DNSCryptPrivacy", "privacy_level", self._tomlInt(config.usage.DNSCryptPrivacy.value, 1)),
				]:
					tmpFound = set()
					line2 = self._replaceKeyLine(line, key, val, tmpFound)
					if key in tmpFound:
						found.add(f"monitoring_ui.{key}")
						line = line2
			newLines.append(line)

		self._insertSectionKey(newLines, "monitoring_ui", "enabled", self._tomlBool(config.usage.DNSCryptUI.value), ["enabled"], found)
		self._insertSectionKey(newLines, "monitoring_ui", "listen_address", self._tomlStr(f"0.0.0.0:{self._tomlInt(config.usage.DNSCryptPort.value, 9012)}"), ["enabled", "listen_address"], found)
		self._insertSectionKey(newLines, "monitoring_ui", "username", self._tomlStr(config.usage.DNSCryptUsername.value.strip()), ["listen_address", "username"], found)
		self._insertSectionKey(newLines, "monitoring_ui", "password", self._tomlStr(config.usage.DNSCryptPassword.value.strip()), ["username", "password"], found)
		self._insertSectionKey(newLines, "monitoring_ui", "privacy_level", self._tomlInt(config.usage.DNSCryptPrivacy.value, 1), ["password", "privacy_level"], found)

		tmpPath = f"{tomlPath}.tmp"
		fileWriteLines(tmpPath, newLines)
		if exists(tmpPath):
			rename(tmpPath, tomlPath)


# ===========================================================================
# NetworkConnectionDnsSetup – optional per-connection DNS override
#
# Same UI as DnsSettings but:
#   - Saves into conn.dnsServers instead of the global nameserverConfig
#   - Does NOT touch config.usage.dns (always uses "custom" mode internally)
#   - Does NOT offer dnscrypt or predefined server presets
#     (those are global concerns; per-connection DNS is always custom or off)
#   - "Use global DNS" option: when enabled, conn.dnsServers is cleared
#     so the system falls back to the global DNS settings
# ===========================================================================

class NetworkConnectionDnsSetup(Setup):
	"""Per-connection DNS override."""

	def __init__(self, session, conn: Connection):
		self._conn = conn
		self._buildConfigObjects()
		Setup.__init__(self, session=session, setup="DNSNetworkConnection")
		self.setTitle(_("DNS – %s") % conn.adapter)

	def _buildConfigObjects(self):
		conn = self._conn
		hasOwn = bool(conn.dnsServers)
		self.cfgUseGlobal = NoSave(ConfigYesNo(default=not hasOwn))
		dnsV4 = [s for s in conn.dnsServers if isinstance(s, list)]
		dnsV6 = [s for s in conn.dnsServers if isinstance(s, str)]
		self.cfgDns1v4 = NoSave(ConfigIP(default=dnsV4[0] if len(dnsV4) > 0 else [0, 0, 0, 0]))
		self.cfgDns2v4 = NoSave(ConfigIP(default=dnsV4[1] if len(dnsV4) > 1 else [0, 0, 0, 0]))
		self.cfgDns1v6 = NoSave(ConfigText(default=dnsV6[0] if len(dnsV6) > 0 else "", fixed_size=False))
		self.cfgDns2v6 = NoSave(ConfigText(default=dnsV6[1] if len(dnsV6) > 1 else "", fixed_size=False))

	def keySave(self):
		conn = self._conn
		if self.cfgUseGlobal.value:
			# Clear per-connection DNS → fall back to global
			conn.dnsServers = []
		else:
			servers: list = []
			for cfgV4 in (self.cfgDns1v4, self.cfgDns2v4):
				val = list(cfgV4.value)
				if val != [0, 0, 0, 0]:
					servers.append(val)
			for cfgV6 in (self.cfgDns1v6, self.cfgDns2v6):
				val = cfgV6.value.strip()
				if val:
					servers.append(val)
			conn.dnsServers = servers
		if nm is not None:
			nm.save()
		self.close(True)

	def keyCancel(self):
		self.close(False)


# ===========================================================================
# InformationNetworkConnection – scrollable info screen for one connection
# ===========================================================================


class InformationNetworkConnection(InformationBase):
	def __init__(self, session, conn, adapter):
		InformationBase.__init__(self, session)
		self._conn = conn
		self._adapter = adapter
		title = _("Network Connection Information") if conn is not None else _("Network Adapter Information")
		self.setTitle(title)
		self.skinName.insert(0, "InformationNetworkConnection")
		self["key_green"] = StaticText(_("Refresh"))

	def displayInformation(self):
		conn = self._conn
		adapter = self._adapter
		info = []

		if conn is not None:
			info.append(formatLine("S", _("Network Connection")))
			info.append(formatLine("P1", _("Interface"), adapter.name))
			if conn.isWlan:
				info.append(formatLine("P1", _("Profile name"), conn.name))
			info.append(formatLine("P1", _("Enabled"), _("Yes") if conn.enabled else _("No")))
			if conn.isWlan:
				info.append(formatLine("P1", _("Priority"), str(conn.priority)))

			info.append("")
			info.append(formatLine("S", _("Configuration")))
			if conn.isWlan and conn.wlan:
				info.append(formatLine("P1", _("SSID"), conn.wlan.ssid or "-"))
				encLabel = _ENC_SHORT.get(conn.wlan.encryption, conn.wlan.encryption) if conn.wlan.encryption else _("None")
				info.append(formatLine("P1", _("Encryption"), encLabel))
			info.append(formatLine("P1", "DHCP", _("Yes") if conn.dhcp else _("No")))
			if not conn.dhcp:
				info.append(formatLine("P1", _("IP address"), ".".join(str(x) for x in conn.ip)))
				info.append(formatLine("P1", _("Netmask"), ".".join(str(x) for x in conn.netmask)))
				info.append(formatLine("P1", _("Gateway"), ".".join(str(x) for x in conn.gateway)))
			if conn.dnsServers:
				info.append(formatLine("P1", "DNS", ", ".join(conn.dnsServers)))

		info.append("")
		info.append(formatLine("S", _("Live Status")))
		if adapter.isWlan:
			info.append(formatLine("P1", _("Associated SSID"), adapter.kernelSsid or "-"))
			if adapter.kernelBssid:
				info.append(formatLine("P1", _("AP (BSSID)"), adapter.kernelBssid))
			if adapter.kernelFreqMhz:
				ch = f"  CH {adapter.kernelChannel}" if adapter.kernelChannel else ""
				info.append(formatLine("P1", _("Frequency"), f"{adapter.kernelFreqMhz} MHz{ch}"))
			if adapter.kernelBitrateBps:
				info.append(formatLine("P1", _("TX rate"), f"{adapter.kernelBitrateBps / 1_000_000:.1f} Mbit/s"))
			if adapter.kernelSignal:
				info.append(formatLine("P1", _("Signal"), f"{adapter.kernelSignal} dBm"))
		else:
			info.append(formatLine("P1", _("Link"), _("Yes") if adapter.kernelLink else _("No")))
			if adapter.kernelSpeed > 0:
				duplexStr = _DUPLEX_LABELS.get(adapter.kernelDuplex, lambda: adapter.kernelDuplex)()
				info.append(formatLine("P1", _("Speed"), f"{formatNetworkSpeed(adapter.kernelSpeed)} {duplexStr}"))
			if adapter.kernelPort:
				info.append(formatLine("P1", _("Port"), adapter.kernelPort))
			if adapter.kernelTransceiver:
				info.append(formatLine("P1", _("Transceiver"), adapter.kernelTransceiver))
			if adapter.kernelLink:
				info.append(formatLine("P1", _("Auto-negotiation"), _("Yes") if adapter.kernelAutoneg else _("No")))

		ip4 = adapter.kernelIp
		if ip4 and ip4 != [0, 0, 0, 0]:
			info.append(formatLine("P1", _("IPv4 address"), ".".join(str(x) for x in ip4)))
		for entry in adapter.kernelIp6:
			addr = entry.get("addr", "")
			prefix = entry.get("prefix", "")
			if addr:
				info.append(formatLine("P1", _("IPv6 address"), f"{addr}/{prefix}"))

		if adapter.kernelDriver or adapter.kernelHwId:
			info.append("")
			info.append(formatLine("S", _("Hardware")))
			if adapter.kernelDriver:
				info.append(formatLine("P1", _("Driver"), adapter.kernelDriver))
			if adapter.kernelHwId:
				info.append(formatLine("P1", _("HW ID"), adapter.kernelHwId))

		self["information"].setText("\n".join(info))


# ===========================================================================
# NetworkConnections – Screen 1
# ===========================================================================

class NetworkConnections(Screen):
	"""Lists every Connection from every Adapter."""

	INDEX_ADAPTER_ICON = 0
	INDEX_ENABLED_ICON = 1
	INDEX_LABEL = 2
	INDEX_CONNECTOR = 3
	INDEX_LINE1 = 4
	INDEX_LINE2 = 5
	INDEX_STATE_COLOR = 6
	INDEX_INET_ICON = 7
	INDEX_ADAPTER_PIXMAP = 8
	INDEX_ENABLED_PIXMAP = 9
	INDEX_LINK_ICON = 10
	INDEX_ADAPTER = 11
	INDEX_CONN = 12
	skin = """
	<screen name="NetworkConnections" title="Network Connections" position="center,center" size="980,600" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="980,520" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;42,Regular;28,Regular;20,enigma2icons;24,Regular;30" itemHeight="80" itemWidth="980" colorStateLink="#0000CC00" colorStateEnabled="#00FFFFFF" colorStateDisabled="#00808080">
				<mode name="default">
					<!-- adapter icon (large, left) -->
					<text index="0" position="5,4" size="58,72" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=6" foregroundColorSelected="=6" />
					<!-- enabled/disabled checkbox placeholder -->
					<text index="1" position="66,26" size="30,30" font="3" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=6" foregroundColorSelected="=6" />
					<!-- adapter label "eth0 / Intern" -->
					<text index="2" position="104,15" size="780,50" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="=6" foregroundColorSelected="=6" />
					<!-- tree connector branch/last_child (enigma2icons) -->
					<text index="3" position="5,4" size="58,72" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=6" foregroundColorSelected="=6" />
					<!-- connection line 1: profile/LAN + IP -->
					<text index="4" position="104,8" size="780,34" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="=6" foregroundColorSelected="=6" />
					<!-- connection line 2: speed / mask / gw -->
					<text index="5" position="104,44" size="780,28" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<!-- internet icon top-right (connection rows only) -->
					<text index="7" position="e-50,4" size="34,34" font="3" horizontalAlignment="center" verticalAlignment="center" />
				</mode>
			</template>
		</widget>
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="200,e-50" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="390,e-50" size="180,40" backgroundColor="key_yellow" conditional="key_yellow" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="580,e-50" size="180,40" backgroundColor="key_blue" conditional="key_blue" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-100,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Connections"))
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Add Wi-Fi"))
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")
		# Tuple indices (see class INDEX_* constants):
		#   0=adapterIcon    adapter: WLAN/LAN iconfont;  connection: ""
		#   1=enabledIcon    adapter: enabled indicator;  connection: ""
		#   2=label          adapter: "eth0 / Intern";    connection: ""
		#   3=connector      adapter: "";                 connection: "├" or "└"
		#   4=line1          adapter: "";                 connection: "Profile: SSID  IP: ..."
		#   5=line2          adapter: "";                 connection: "speed / mask / gw"
		#   6=stateColor     color int (both rows)
		#   7=inetIcon       adapter: "";                 connection: globe char if internet
		#   8=adapterPixmap  adapter: wired/wireless-active/inactive;  connection: None
		#   9=enabledPixmap  adapter: None;               connection: lock_on/lock_error (checkbox as image)
		#  10=linkIcon       adapter: "";                 connection: link active/inactive glyph
		#  11=adapter        always the Adapter object
		#  12=conn           None for adapter row, Connection for connection row
		indexNames = {
			"adapterIcon": self.INDEX_ADAPTER_ICON,
			"enabledIcon": self.INDEX_ENABLED_ICON,
			"label": self.INDEX_LABEL,
			"connector": self.INDEX_CONNECTOR,
			"line1": self.INDEX_LINE1,
			"line2": self.INDEX_LINE2,
			"stateColor": self.INDEX_STATE_COLOR,
			"inetIcon": self.INDEX_INET_ICON,
			"adapterPixmap": self.INDEX_ADAPTER_PIXMAP,
			"enabledPixmap": self.INDEX_ENABLED_PIXMAP,
			"linkIcon": self.INDEX_LINK_ICON,
		}
		self["list"] = List([], indexNames=indexNames)
		self["list"].onSelectionChanged.append(self._updateYellowKey)
		self["actions"] = HelpableActionMap(
			self,
			["OkCancelActions", "ColorActions", "MenuActions", "InfoActions"],
			{
				"ok": (self._keyOK, _("Open settings for selected network connection")),
				"cancel": (self.close, _("Close network connection list")),
				"red": (self.close, _("Close network connection list")),
				"green": (self._keyGreen, _("Add a new network connection")),
				"yellow": (self._keyYellow, _("Activate/Deactivate adapter")),
				"info": (self._showInfo, _("Show network connection info")),
				# "blue": (self._keyBlue, _("Open global DNS settings")),
				"menu": (self._keyMenu, _("Open context menu for selected network connection")),
			},
			prio=0,
			description=_("Network Connection Actions"),
		)
		self._colorLink = _COLOR_LINK
		self._colorEnabled = _COLOR_ENABLED
		self._colorDisabled = _COLOR_GRAY
		self.onLayoutFinish.append(self._readSkinColors)
		self.onLayoutFinish.append(self._buildList)
		self._internetChecked = False
		self._internetResult = None
		self.onShown.append(self.checkInternet)
		if nm:
			nm.onAdaptersChanged.append(self._buildList)
			self.onClose.append(lambda: nm.onAdaptersChanged.remove(self._buildList) if self._buildList in nm.onAdaptersChanged else None)

	def _readSkinColors(self):
		attrs = self["list"].additionalTemplateAttributes
		self._colorLink = parseColor(attrs["colorStateLink"]).argb() if "colorStateLink" in attrs else _COLOR_LINK
		self._colorEnabled = parseColor(attrs["colorStateEnabled"]).argb() if "colorStateEnabled" in attrs else _COLOR_ENABLED
		self._colorDisabled = parseColor(attrs["colorStateDisabled"]).argb() if "colorStateDisabled" in attrs else _COLOR_GRAY

	def checkInternet(self):
		def checkInternetCallback(result):
			if hasattr(self, "_internetResult"):
				self._internetResult = result
				self._buildList()
				self._internetChecked = True

		if not self._internetChecked:
			nm.checkConnectionInternet(callback=checkInternetCallback)

	@staticmethod
	def _adapterPixmap(adapter: Adapter):
		if adapter.isWlan:
			name = "network_wireless-active.png" if adapter.kernelLink else "network_wireless-inactive.png" if adapter.adapterEnabled else "network_wireless.png"
		else:
			name = "network_wired-active.png" if adapter.kernelLink else "network_wired-inactive.png" if adapter.adapterEnabled else "network_wired.png"
		return LoadPixmap(resolveFilename(SCOPE_GUISKIN, f"icons/{name}"))

	@staticmethod
	def _connPixmap(conn: Connection):
		name = "lock_on.png" if conn.enabled else "lock_error.png"
		return LoadPixmap(cached=True, path=resolveFilename(SCOPE_GUISKIN, f"icons/{name}"))

	def _buildList(self):
		if nm is None:
			return
		entries: list[tuple] = []
		for iface in sorted(nm.adapters.keys()):
			adapter = nm.adapters[iface]
			internet = self._internetResult and self._internetResult.get(iface)
			adapterIcon = _ICON_WLAN if adapter.isWlan else _ICON_LAN
			checkBox = _ICON_CHECKBOX_ON if adapter.adapterEnabled else _ICON_CHECKBOX_OFF
			loc = _adapterLocation(adapter)
			adapterLabel = f"Adapter {iface}   /   {loc}" if loc else f"Adapter {iface}"
			adapterColor = self._colorLink if adapter.kernelLink else self._colorEnabled if adapter.adapterEnabled else self._colorDisabled
			entries.append((adapterIcon, checkBox, adapterLabel, "", "", "", adapterColor, "", self._adapterPixmap(adapter), None, "", adapter, None))
			# For WLAN: skip the base connection (no SSID) when wpa_supplicant
			# connections with SSIDs are present — the base only carries IP config.
			conns = adapter.connections
			if adapter.isWlan and any(c.wlan and c.wlan.ssid for c in conns):
				conns = [c for c in conns if c.wlan and c.wlan.ssid]
			for idx, conn in enumerate(conns):
				isLast = idx == len(conns) - 1
				connColor = self._colorEnabled if conn.enabled else self._colorDisabled
				inetIcon = _ICON_INET if (internet and conn.enabled) else ""
				linkIcon = _ICON_LINK_ACTIVE if adapter.kernelLink else _ICON_LINK_INACTIVE
				entries.append(("", "", "", _ICON_LAST_CHILD if isLast else _ICON_BRANCH, _connLine1(conn, adapter), _connLine2(conn, adapter), connColor, inetIcon, None, self._connPixmap(conn), linkIcon, adapter, conn))
		self["list"].setList(entries)
		self._updateYellowKey()

	def _current(self) -> tuple | None:
		return self["list"].getCurrent()

	def _keyOK(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		if conn is None:
			return
		self._openSetup(conn, adapter)

	def _keyYellow(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		if conn is None:
			self._toggleAdapter(adapter)

	def _showInfo(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		self.session.open(InformationNetworkConnection, conn, adapter)

	def _updateYellowKey(self):
		entry = self._current()
		if entry is None or entry[self.INDEX_CONN] is not None:
			self["key_yellow"].setText("")
		else:
			adapter = entry[self.INDEX_ADAPTER]
			self["key_yellow"].setText(_("Deactivate") if adapter.adapterEnabled else _("Activate"))

	def _keyMenu(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		if conn is None:
			self._showAdapterMenu(adapter)
		else:
			self._showContextMenu(conn, adapter)

	def _showAdapterMenu(self, adapter: Adapter):
		isEnabled = adapter.adapterEnabled
		label = _("Disable adapter") if isEnabled else _("Enable adapter")
		self.session.openWithCallback(
			lambda choice: self._adapterMenuCb(choice, adapter),
			ChoiceBox,
			title=adapter.name,
			list=[(label, "toggle")],
		)

	def _adapterMenuCb(self, choice, adapter: Adapter):
		if choice is None:
			return
		if choice[1] == "toggle":
			self._toggleAdapter(adapter)

	def _showContextMenu(self, conn: Connection, adapter: Adapter):
		menu = [
			(_("Settings"), "setup"),
			(_("Enable connection") if not conn.enabled else _("Disable connection"), "toggle"),
			(_("Network connection DNS"), "connDns"),
			(_("Network test"), "test"),
			(_("Delete network connection"), "delete"),
		]
		if conn.isWlan:
			menu.append((_("Scan for WLAN networks"), "scan"))
			menu.append((_("Add WLAN manually"), "addManual"))
		self.session.openWithCallback(
			lambda choice: self._contextCb(choice, conn, adapter),
			ChoiceBox,
			title=_("Network connection: %s") % _connLabel(conn, adapter),
			list=[(item[0], item[1]) for item in menu],
		)

	def _contextCb(self, choice, conn: Connection, adapter: Adapter):
		if choice is None:
			return
		action = choice[1]
		if action == "setup":
			self._openSetup(conn, adapter)
		elif action == "toggle":
			self._toggleConnection(conn, adapter)
		elif action == "connDns":
			self._openConnectionDns(conn)
		elif action == "test":
			self.session.open(NetworkAdapterTest2, adapter.name)
		elif action == "delete":
			self._confirmDelete(conn, adapter)
		elif action == "scan":
			self._openWlanScan(adapter.name)
		elif action == "addManual":
			self._openWlanManual(adapter)

	def _openSetup(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(
			lambda saved: self._buildList() if saved else None,
			NetworkConnectionSetup,
			conn,
			adapter,
		)

	def _openConnectionDns(self, conn: Connection):
		self.session.openWithCallback(
			lambda saved: self._buildList() if saved else None,
			NetworkConnectionDnsSetup,
			conn,
		)

	def _keyBlue(self):
		pass

	def _toggleAdapter(self, adapter: Adapter):
		adapter.adapterEnabled = not adapter.adapterEnabled
		if nm:
			nm.save()
		self._buildList()
		state = _("enabled") if adapter.adapterEnabled else _("disabled")
		self.session.open(MessageBox, _("Adapter %s %s") % (adapter.name, state), type=MessageBox.TYPE_INFO, timeout=3)

	def _toggleConnection(self, conn: Connection, adapter: Adapter):
		if adapter.isWlan:
			if conn.enabled:
				for c in adapter.connections:
					c.enabled = False
			else:
				for c in adapter.connections:
					c.enabled = (c is conn)
		else:
			conn.enabled = not conn.enabled
			adapter.adapterEnabled = conn.enabled
		if nm:
			nm.save()
		self._buildList()
		self.session.open(
			MessageBox,
			_("Network connection %s") % (_("enabled") if conn.enabled else _("disabled")),
			type=MessageBox.TYPE_INFO,
			timeout=3,
		)

	def _confirmDelete(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(
			lambda confirmed: self._doDelete(confirmed, conn, adapter),
			MessageBox,
			_("Delete network connection '%s'?") % _connLabel(conn, adapter),
			type=MessageBox.TYPE_YESNO,
		)

	def _doDelete(self, confirmed: bool, conn: Connection, adapter: Adapter):
		if not confirmed:
			return
		if conn.isWlan and conn.wlan:
			nm.removeConnection(adapter.name, conn.wlan.ssid)
		else:
			adapter.connections = [c for c in adapter.connections if c is not conn]
		if nm:
			nm.save()
		self._buildList()

	def _keyGreen(self):
		if nm is None or not nm.adapters:
			return
		wlanAdapters = [a for a in nm.adapters.values() if a.isWlan]
		lanAdapters = [a for a in nm.adapters.values() if not a.isWlan]
		if wlanAdapters:
			WlanAddFlow.start(self.session, callback=self._buildList)
		elif lanAdapters:
			adapter = lanAdapters[0]
			newConn = Connection(adapter=adapter.name, name=_("New LAN connection"), dhcp=True)
			self.session.openWithCallback(
				lambda changed: self._newLanConnClosed(changed, newConn, adapter),
				NetworkConnectionSetup,
				newConn,
				adapter,
			)

	def _newLanConnClosed(self, changed: bool, conn: Connection, adapter: Adapter):
		if changed:
			existingIds = {id(c) for c in adapter.connections}
			if id(conn) not in existingIds:
				adapter.connections.append(conn)
				if nm:
					nm.save()
			self._buildList()

	def _openWlanScan(self, iface: str):
		if nm is None:
			return
		adapter = nm.getAdapter(iface)
		if adapter is None or not adapter.isWlan:
			return
		self.session.openWithCallback(
			lambda result: self._wlanScanDone(result, adapter),
			WlanScanScreen,
			adapter,
		)

	def _wlanScanDone(self, result: ScanResult | None, adapter: Adapter):
		if result is None:
			return
		conn = _scanResultToConnection(result, adapter.name)
		self.session.openWithCallback(
			lambda saved: self._wlanSetupDone(saved, conn, adapter),
			NetworkConnectionSetup,
			conn,
			adapter,
		)

	def _wlanSetupDone(self, saved: bool, conn: Connection, adapter: Adapter):
		if not saved:
			return
		if not any(c.wlan and c.wlan.ssid == (conn.wlan.ssid if conn.wlan else "") for c in adapter.connections):
			adapter.connections.append(conn)
			if nm:
				nm.save()
		self._buildList()

	def _openWlanManual(self, adapter: Adapter):
		conn = Connection(adapter=adapter.name, name=_("New WLAN"), dhcp=True, enabled=False, wlan=WlanConfig())
		self.session.openWithCallback(
			lambda saved: self._wlanSetupDone(saved, conn, adapter),
			NetworkConnectionSetup,
			conn,
			adapter,
		)


# ===========================================================================
# NetworkConnectionSetup – Screen 2 (Setup subclass)
# ===========================================================================

class NetworkConnectionSetup(Setup):
	"""Setup screen for one Connection."""

	def __init__(self, session, conn: Connection, adapter: Adapter):
		self._conn = conn
		self._adapter = adapter
		self._buildConfigObjects()
		xmlSection = "NetworkConnectionWlan" if conn.isWlan else "NetworkConnection"
		Setup.__init__(self, session=session, setup=xmlSection)
		self.setTitle(_("Network Connection Settings – %s") % conn.adapter)
		self["key_yellow"] = StaticText("DNS")
		self["key_blue"] = StaticText(_("Info"))
		self["yellowActions"] = HelpableActionMap(
			self,
			["ColorActions"],
			{"yellow": (self._openDns, _("Configure per-connection DNS"))},
			prio=0,
		)
		self["blueActions"] = HelpableActionMap(
			self,
			["ColorActions"],
			{"blue": (self._showInfo, _("Show network connection info"))},
			prio=0,
		)

	def _showInfo(self):
		self.session.open(InformationNetworkConnection, self._conn, self._adapter)

	def _buildConfigObjects(self):
		conn = self._conn
		adapter = self._adapter  # noqa

		self.cfgName = NoSave(ConfigText(default=conn.name, fixed_size=False))
		self.cfgEnabled = NoSave(ConfigYesNo(default=conn.enabled))
		if conn.isWlan:
			wlanConns = [c for c in adapter.connections if c.isWlan and c.wlan and c.wlan.ssid]
			self._hasMultiplePriorities = len(wlanConns) > 1
			if self._hasMultiplePriorities:
				self._wlanConnsSorted = sorted(wlanConns, key=lambda c: c.priority, reverse=True)
				currentRank = next((i + 1 for i, c in enumerate(self._wlanConnsSorted) if c is conn), 1)
				rankChoices = [(i + 1, _("1st (highest)") if i == 0 else _("%d.") % (i + 1)) for i in range(len(wlanConns))]
				self.cfgPriority = NoSave(ConfigSelection(choices=rankChoices, default=currentRank))
			else:
				self._wlanConnsSorted = []
				self.cfgPriority = NoSave(ConfigNumber(default=conn.priority))
		else:
			self._hasMultiplePriorities = False
			self._wlanConnsSorted = []
			self.cfgPriority = NoSave(ConfigNumber(default=conn.priority))
		self.cfgDhcp = NoSave(ConfigYesNo(default=conn.dhcp))
		self.cfgIp = NoSave(ConfigIP(default=conn.ip))
		self.cfgNetmask = NoSave(ConfigIP(default=conn.netmask))
		self.cfgGateway = NoSave(ConfigIP(default=conn.gateway))
		self.cfgIpMode = NoSave(ConfigSelection(
			default=conn.ipMode,
			choices=[
				(0, _("IPv4 only")),
				(1, _("IPv6 only")),
				(2, _("IPv4 and IPv6")),
			]
		))

		if conn.isWlan and conn.wlan:
			w = conn.wlan
			self.cfgSsid = NoSave(ConfigText(default=w.ssid, fixed_size=False))
			self.cfgHidden = NoSave(ConfigYesNo(default=w.hidden))
			self.cfgEncryption = NoSave(ConfigSelection(choices=encryptionChoices, default=w.encryption))
			self.cfgKey = NoSave(ConfigPassword(default=w.key, fixed_size=False))
		else:
			self.cfgSsid = NoSave(ConfigText(default="", fixed_size=False))
			self.cfgHidden = NoSave(ConfigYesNo(default=False))
			self.cfgEncryption = NoSave(ConfigSelection(choices=encryptionChoices, default=encNone))
			self.cfgKey = NoSave(ConfigPassword(default="", fixed_size=False))

		# Wake-on-LAN (LAN adapters only, when hardware supports it)
		wolChoices = [
			("off", _("Disabled")),
			("g", _("Magic Packet")),
			("u", _("Unicast")),
			("b", _("Broadcast")),
		]
		liveWol = conn.wakeOnLan
		if not conn.isWlan and adapter.canWakeOnLan and nm is not None:
			liveWol = nm.getWakeOnLan(adapter.name)
		self.cfgWakeOnLan = NoSave(ConfigSelection(
			choices=wolChoices,
			default=liveWol if not conn.isWlan else "off",
		))

		# Wake-on-WiFi (Broadcom wlan3 only)
		self.cfgWakeOnWifi = NoSave(ConfigYesNo(default=conn.wakeOnWifi))

		# Read-only DNS indicator shown when a per-connection override is active
		self.cfgDnsHint = NoSave(ConfigText(default=_("Custom (BLUE to change)"), fixed_size=False))

	def _openDns(self):
		self.session.openWithCallback(
			lambda saved: Setup.createSetup(self) if saved else None,
			NetworkConnectionDnsSetup,
			self._conn,
		)

	def keySave(self):
		conn = self._conn
		adapter = self._adapter

		conn.name = self.cfgName.value
		conn.enabled = self.cfgEnabled.value
		if self._hasMultiplePriorities:
			chosenRank = self.cfgPriority.value
			others = [c for c in self._wlanConnsSorted if c is not conn]
			newOrder = others[:chosenRank - 1] + [conn] + others[chosenRank - 1:]
			for i, c in enumerate(newOrder):
				c.priority = (len(newOrder) - i) * 10
		else:
			conn.priority = int(self.cfgPriority.value)
		conn.dhcp = self.cfgDhcp.value
		conn.ipMode = self.cfgIpMode.value

		if not conn.dhcp:
			conn.ip = list(self.cfgIp.value)
			conn.netmask = list(self.cfgNetmask.value)
			conn.gateway = list(self.cfgGateway.value)
			# dnsServers managed separately via NetworkConnectionDnsSetup

		if conn.isWlan and conn.wlan:
			w = conn.wlan
			w.ssid = self.cfgSsid.value.strip()
			w.hidden = self.cfgHidden.value
			w.encryption = self.cfgEncryption.value
			if w.encryption != encNone:
				w.key = self.cfgKey.value

		# Apply Wake-on-LAN via ethtool + optional /proc path
		if not conn.isWlan and adapter.canWakeOnLan:
			newWolMode = self.cfgWakeOnLan.value
			if newWolMode != conn.wakeOnLan and nm is not None:
				cmds = nm.setWakeOnLanCommands(adapter.name, newWolMode)
				if cmds:
					Console().eBatch(cmds, lambda _: None, debug=False)

		# Apply Wake-on-WiFi (Broadcom)
		if conn.isWlan and adapter.canWakeOnWifi:
			newWow = self.cfgWakeOnWifi.value
			if newWow != conn.wakeOnWifi and nm is not None:
				cmds = nm.setWakeOnWifiCommands(adapter.name, newWow)
				if cmds:
					Console().eBatch(cmds, lambda _: None, debug=False)

		if nm is not None:
			nm.save()
		self.close(True)

	def keyCancel(self):
		self.close(False)


# ===========================================================================
# ScanResult – one discovered wireless network
# ===========================================================================

@dataclass
class ScanResult:
	ssid: str = ""
	bssid: str = ""
	frequency: str = ""
	channel: int = 0
	signalDbm: int = -100
	signalPct: int = 0
	encryption: str = encNone
	encDetails: str = ""

	@property
	def signalBars(self) -> int:
		if self.signalPct >= 80:
			return 4
		if self.signalPct >= 60:
			return 3
		if self.signalPct >= 35:
			return 2
		if self.signalPct >= 10:
			return 1
		return 0

	@property
	def encLabel(self) -> str:
		return {
			encNone: _("Open"),
			encWep: "WEP",
			encWpa: "WPA",
			encWpa2: "WPA2",
			encWpa3: "WPA3",
		}.get(self.encryption, self.encryption.upper())


# ---------------------------------------------------------------------------
# iwlist parser
# ---------------------------------------------------------------------------

def _dbmToPct(dbm: int) -> int:
	dbm = max(-100, min(-30, dbm))
	return int((dbm + 100) * 100 / 70)


def _parseIwlist(raw: str) -> list[ScanResult]:
	results: list[ScanResult] = []
	current: ScanResult | None = None

	reCell = re.compile(r"Cell \d+ - Address:\s*([0-9A-Fa-f:]{17})")
	reSsid = re.compile(r'ESSID:"(.*?)"')
	reFreq = re.compile(r"Frequency:([\d.]+ \w+Hz).*?Channel:?(\d+)?")
	reQuality = re.compile(r"Quality=(\d+)/(\d+)\s+Signal level=(-?\d+) dBm")
	reEncOn = re.compile(r"Encryption key:on")
	reEncOff = re.compile(r"Encryption key:off")
	reIeWpa1 = re.compile(r"IE:.*WPA Version 1", re.IGNORECASE)
	reIeWpa2 = re.compile(r"IE:.*WPA2|IE:.*RSN", re.IGNORECASE)
	reIeWpa3 = re.compile(r"IE:.*SAE|IE:.*WPA3", re.IGNORECASE)

	for line in raw.splitlines():
		line = line.strip()
		m = reCell.search(line)
		if m:
			current = ScanResult(bssid=m.group(1))
			results.append(current)
			continue
		if current is None:
			continue
		m = reSsid.search(line)
		if m:
			current.ssid = m.group(1)
		m = reFreq.search(line)
		if m:
			current.frequency = m.group(1)
			if m.group(2):
				current.channel = int(m.group(2))
		m = reQuality.search(line)
		if m:
			qVal, qMax = int(m.group(1)), int(m.group(2))
			current.signalPct = int(qVal * 100 / qMax) if qMax else 0
			current.signalDbm = int(m.group(3))
		if reIeWpa3.search(line):
			current.encryption = encWpa3
			current.encDetails = line
		elif reIeWpa2.search(line):
			if current.encryption != encWpa3:
				current.encryption = encWpa2
				current.encDetails = line
		elif reIeWpa1.search(line):
			if current.encryption == encNone:
				current.encryption = encWpa
				current.encDetails = line
		elif reEncOn.search(line):
			if current.encryption == encNone:
				current.encryption = encWep
		elif reEncOff.search(line):
			current.encryption = encNone

	seen: dict = {}
	for r in results:
		if not r.ssid:
			continue
		if r.ssid not in seen or r.signalPct > seen[r.ssid].signalPct:
			seen[r.ssid] = r

	return sorted(seen.values(), key=lambda x: -x.signalPct)


def _scanResultToConnection(r: ScanResult, iface: str) -> Connection:
	return Connection(
		adapter=iface,
		name=r.ssid,
		dhcp=True,
		enabled=False,
		priority=0,
		wlan=WlanConfig(ssid=r.ssid, encryption=r.encryption),
	)


# ===========================================================================
# WlanScanScreen – live iwlist scan
# ===========================================================================

class WlanScanScreen(Screen):
	"""Runs iwlist scan and shows results sorted by signal strength."""

	skin = """
	<screen name="WlanScanScreen" title="WLAN Scan" position="center,center" size="980,600" resolution="1280,720">
		<widget name="description" position="10,10" size="960,40" font="Regular;22" halign="left" valign="center" />
		<widget source="list" render="Listbox" position="0,60" size="980,450" scrollbarMode="showOnDemand">
			<template name="Default" fonts="Regular;26,Regular;20" itemHeight="50">
				<mode name="default">
					<text index="0" position="10,0" size="490,50" font="0" horizontalAlignment="left" verticalAlignment="center" />
					<text index="1" position="510,0" size="200,50" font="1" horizontalAlignment="center" verticalAlignment="center" />
					<text index="2" position="720,0" size="150,50" font="1" horizontalAlignment="center" verticalAlignment="center" />
					<text index="3" position="880,0" size="90,50" font="1" horizontalAlignment="right" verticalAlignment="center" />
				</mode>
			</template>
		</widget>
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="200,e-50" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="390,e-50" size="180,40" backgroundColor="key_yellow" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	_bars = ["▁", "▃", "▅", "▇", "█"]

	def __init__(self, session, adapter: Adapter):
		Screen.__init__(self, session, enableHelp=True)
		self._adapter = adapter
		self._console = Console()
		self._scanning = False
		self._results: list[ScanResult] = []
		self.setTitle(_("WLAN Scan – %s") % adapter.name)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Select"))
		self["key_yellow"] = StaticText(_("Rescan"))
		self["key_blue"] = StaticText("")
		self["description"] = Label(_("Scanning…"))
		self["list"] = List([])
		self["actions"] = HelpableActionMap(
			self,
			["OkCancelActions", "ColorActions"],
			{
				"ok": (self._select, _("Use selected network")),
				"green": (self._select, _("Use selected network")),
				"yellow": (self._startScan, _("Scan again")),
				"red": (self._cancel, _("Cancel")),
				"cancel": (self._cancel, _("Cancel")),
			},
			prio=0,
			description=_("WLAN Scan Actions"),
		)
		self.onLayoutFinish.append(self._startScan)

	def _startScan(self):
		if self._scanning:
			return
		self._scanning = True
		self["description"].setText(_("Scanning…"))
		self["list"].setList([])
		self._console.ePopen(f"ifconfig {self._adapter.name} up", lambda *_: self._runIwlist())

	def _runIwlist(self):
		self._console.ePopen(f"iwlist {self._adapter.name} scan", self._scanDoneCb)

	def _scanDoneCb(self, result: str, retval: int, extraArgs=None):
		self._scanning = False
		if isinstance(result, bytes):
			result = result.decode("utf-8", errors="replace")
		self._results = _parseIwlist(result)
		if not self._results:
			self["description"].setText(_("No networks found.  Press YELLOW to scan again."))
			return
		self["description"].setText(_("%d network(s) found.  Press OK to select.") % len(self._results))
		self._populateList()

	def _populateList(self):
		rows = []
		for r in self._results:
			bars = self._bars[min(r.signalBars, 4)]
			sig = f"{bars} {r.signalPct}% ({r.signalDbm} dBm)"
			freq = r.frequency if r.frequency else (f"CH{r.channel}" if r.channel else "")
			rows.append((r.ssid, sig, r.encLabel, freq, r))
		self["list"].setList(rows)

	def _select(self):
		current = self["list"].getCurrent()
		if current is None:
			return
		self.close(current[-1])

	def _cancel(self):
		if self._console:
			self._console.killAll()
		self.close(None)


# ===========================================================================
# WlanActivator – brings up a WLAN connection
# ===========================================================================

class WlanActivator(Screen):
	"""Runs ifup + wpa_supplicant and polls for an IP address."""

	skin = """
	<screen name="WlanActivator" title="Connecting…" position="center,center" size="980,200" resolution="1280,720">
		<widget name="status" position="10,10" size="960,160" font="Regular;26" halign="center" valign="center" />
	</screen>"""

	_pollIntervalMs = 1500
	_pollMaxAttempts = 20

	def __init__(self, session, conn: Connection, adapter: Adapter):
		Screen.__init__(self, session)
		self._conn = conn
		self._adapter = adapter
		self._serviceAction = None
		self._pollTimer = None
		self._closeTimer = None
		self._pollCount = 0
		self["status"] = Label(_("Connecting…"))
		self.onLayoutFinish.append(self._start)

	def _start(self):
		self["status"].setText(_("Connecting…"))
		self._serviceAction = ServiceAction.wlanActivate(self._adapter.name, self._connectedCb)

	def _connectedCb(self, retval: int):
		if retval != 0:
			self["status"].setText(_("Connection failed (code %d).\nCheck your settings and try again.") % retval)
			self._scheduleClose(4000)
			return
		self._pollCount = 0
		self["status"].setText(_("Waiting for IP address…"))
		self._pollTimer = eTimer()
		self._pollTimer.callback.append(self._checkIp)
		self._pollTimer.start(self._pollIntervalMs, True)

	def _checkIp(self):
		iface = self._adapter.name
		self._pollCount += 1
		ip = self._getKernelIp(iface)
		if ip and ip not in ("0.0.0.0", ""):
			self._pollTimer.stop()
			ssid = self._conn.wlan.ssid if self._conn.wlan else iface
			self["status"].setText(_("Connected to '%s'\nIP: %s") % (ssid, ip))
			self._scheduleClose(2500)
			return
		if self._pollCount >= self._pollMaxAttempts:
			self._pollTimer.stop()
			self["status"].setText(_("Connection timed out.\nNetwork saved – will retry automatically at next boot."))
			self._scheduleClose(4000)
			return
		self._pollTimer.start(self._pollIntervalMs, True)

	@staticmethod
	def _getKernelIp(iface: str) -> str:
		addrs = netifaces.ifaddresses(iface)
		if netifaces.AF_INET in addrs:
			return addrs[netifaces.AF_INET][0].get("addr", "")
		return ""

	def _scheduleClose(self, delayMs: int):
		self._closeTimer = eTimer()
		self._closeTimer.callback.append(lambda: self.close(True))
		self._closeTimer.start(delayMs, True)


# ===========================================================================
# WlanAddFlow – coordinator / entry point
# ===========================================================================

class WlanAddFlow:
	"""Stateless coordinator. Call WlanAddFlow.start() to begin the flow."""

	@staticmethod
	def start(session, adapter: Adapter | None = None, callback=None):
		if nm is None:
			return
		if adapter is None:
			wlanAdapters = [a for a in nm.adapters.values() if a.isWlan]
			if not wlanAdapters:
				session.open(MessageBox, _("No WLAN adapter found."), type=MessageBox.TYPE_INFO, timeout=4)
				return
			if len(wlanAdapters) == 1:
				adapter = wlanAdapters[0]
			else:
				WlanAddFlow._pickAdapter(session, wlanAdapters, callback)
				return
		WlanAddFlow._openScan(session, adapter, callback)

	@staticmethod
	def _openScan(session, adapter: Adapter, callback):
		def _scanned(result: ScanResult | None):
			if result is None:
				if callback:
					callback()
				return
			conn = _scanResultToConnection(result, adapter.name)

			def _setupDone(saved: bool):
				if saved:
					if not any(c.wlan and c.wlan.ssid == (conn.wlan.ssid if conn.wlan else "") for c in adapter.connections):
						adapter.connections.append(conn)
						if nm:
							nm.save()
				if callback:
					callback()
			session.openWithCallback(_setupDone, NetworkConnectionSetup, conn, adapter)
		session.openWithCallback(_scanned, WlanScanScreen, adapter)

	@staticmethod
	def _pickAdapter(session, adapters: list[Adapter], callback):
		choices = [(a.name, a) for a in adapters]

		def _chosen(choice):
			if choice is None:
				if callback:
					callback()
				return
			WlanAddFlow._openScan(session, choice[1], callback)

		session.openWithCallback(_chosen, ChoiceBox, title=_("Select WLAN adapter"), list=choices)


# ===========================================================================
# NameserverSetup – backward-compat alias (some screens still import this)
# ===========================================================================

class NameserverSetup(DnsSettings):
	def __init__(self, session):
		DnsSettings.__init__(self, session=session)


# ===========================================================================
# NetworkAdapterTest2 – list-based adapter test (replaces NetworkAdapterTest)
# ===========================================================================


class NetworkAdapterTest2(Screen):
	"""Sequential network adapter tests displayed as a simple list."""

	skin = """
	<screen name="NetworkAdapterTest2" title="Network Test" position="center,center" size="900,510" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="900,420" scrollbarMode="showNever">
			<template name="Default" fonts="Regular;24,Regular;22,Regular;18" itemHeight="60" itemWidth="900">
				<mode name="default">
					<text index="0" position="10,10" size="40,40" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=4" foregroundColorSelected="=4" />
					<text index="1" position="60,10" size="280,40" font="0" horizontalAlignment="left" verticalAlignment="center" />
					<text index="2" position="350,10" size="210,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="=4" foregroundColorSelected="=4" />
					<text index="3" position="570,10" size="320,40" font="2" horizontalAlignment="left" verticalAlignment="center" />
				</mode>
			</template>
		</widget>
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="200,e-50" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	_ROW_ADAPTER = 0
	_ROW_LINK = 1
	_ROW_IP = 2
	_ROW_GATEWAY = 3
	_ROW_INTERNET = 4
	_ROW_DNS = 5

	_COL_PENDING = gRGB(0x00808080).argb()
	_COL_OK = gRGB(0x0000CC00).argb()
	_COL_FAIL = gRGB(0x00CC0000).argb()

	_ICON_OK = "✓"
	_ICON_FAIL = "✗"
	_ICON_SKIP = "—"
	_ICON_BUSY = "…"

	_T_NOT_FOUND = _("not found")
	_T_NA = _("n/a")
	_T_ASSOCIATED = _("associated")
	_T_NOT_ASSOC = _("not associated")
	_T_CONNECTED = _("connected")
	_T_DISCONNECTED = _("disconnected")
	_T_NO_ADDRESS = _("no address")
	_T_NO_GATEWAY = _("no gateway")
	_T_PINGING = _("pinging…")
	_T_REACHABLE = _("reachable")
	_T_UNREACHABLE = _("unreachable")
	_T_RESOLVING = _("resolving…")
	_T_CONFIRMED = _("confirmed")
	_T_UNCONFIRMED = _("unconfirmed")
	_T_STATIC = _("Static")

	def __init__(self, session, iface: str):
		Screen.__init__(self, session)
		self._iface = iface
		self._rows: list[tuple] = []
		self._generation = 0
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Restart"))
		self["list"] = List([])
		self["actions"] = HelpableActionMap(
			self,
			["OkCancelActions", "ColorActions"],
			{
				"cancel": (self.close, _("Close network test")),
				"red": (self.close, _("Close network test")),
				"green": (self._restart, _("Restart test")),
			},
			prio=0,
			description=_("Network Test Actions"),
		)
		self.onLayoutFinish.append(self._start)

	def _restart(self):
		self._generation += 1
		self._start()

	def _start(self):
		adapterName = nm.getFriendlyAdapterName(self._iface) if nm else self._iface
		self.setTitle(_("Network Test – %s") % adapterName)
		adapter = nm.adapters.get(self._iface) if nm else None
		isWlan = adapter.isWlan if adapter else False
		labels = [
			_("Adapter"),
			_("Wireless link") if isWlan else _("LAN link"),
			_("IP address"),
			_("Gateway"),
			_("Internet"),
			"DNS",
		]
		self._rows = [(self._ICON_BUSY, label, "", "", self._COL_PENDING) for label in labels]
		self["list"].setList(list(self._rows))
		self._testAdapter()

	def _setRow(self, idx: int, icon: str, result: str, detail: str, color: int):
		r = list(self._rows[idx])
		r[0], r[2], r[3], r[4] = icon, result, detail, color
		self._rows[idx] = tuple(r)
		self["list"].setList(list(self._rows))

	def _pingRow(self, row: int, host: str, okText: str, failText: str, detail: str, nextFn):
		self._setRow(row, self._ICON_BUSY, self._T_PINGING, detail, self._COL_PENDING)
		gen = self._generation

		def _done(ok: bool):
			if self._generation != gen:
				return
			self._setRow(row, self._ICON_OK if ok else self._ICON_FAIL, okText if ok else failText, detail, self._COL_OK if ok else self._COL_FAIL)
			nextFn()
		pingAsync(host, self._iface, _done)

	def _testAdapter(self):
		adapter = nm.adapters.get(self._iface) if nm else None
		if adapter is None:
			self._setRow(self._ROW_ADAPTER, self._ICON_FAIL, self._T_NOT_FOUND, "", self._COL_FAIL)
			self._setRow(self._ROW_LINK, self._ICON_SKIP, self._T_NA, "", self._COL_PENDING)
			self._setRow(self._ROW_IP, self._ICON_SKIP, self._T_NA, "", self._COL_PENDING)
			self._testGateway()
			return
		self._setRow(self._ROW_ADAPTER, self._ICON_OK, nm.getFriendlyAdapterName(self._iface), adapter.kernelDriver or "", self._COL_OK)
		self._testLink(adapter)

	def _testLink(self, adapter):
		if adapter.isWlan:
			ssid = adapter.kernelSsid or ""
			if ssid:
				sig = f"{adapter.kernelSignal} dBm" if adapter.kernelSignal else ""
				self._setRow(self._ROW_LINK, self._ICON_OK, self._T_ASSOCIATED, f"{ssid}  {sig}".strip(), self._COL_OK)
			else:
				self._setRow(self._ROW_LINK, self._ICON_FAIL, self._T_NOT_ASSOC, "", self._COL_FAIL)
		else:
			if adapter.kernelLink:
				speed = f"{adapter.kernelSpeed} Mbit/s" if adapter.kernelSpeed > 0 else ""
				self._setRow(self._ROW_LINK, self._ICON_OK, self._T_CONNECTED, speed, self._COL_OK)
			else:
				self._setRow(self._ROW_LINK, self._ICON_FAIL, self._T_DISCONNECTED, "", self._COL_FAIL)
		self._testIp(adapter)

	def _testIp(self, adapter):
		ip = adapter.kernelIp or []
		ipStr = ".".join(str(b) for b in ip) if ip else ""
		if ipStr and ipStr != "0.0.0.0":
			conn = adapter.activeConnection()
			hint = "DHCP" if (conn and conn.dhcp) else self._T_STATIC
			self._setRow(self._ROW_IP, self._ICON_OK, ipStr, hint, self._COL_OK)
		else:
			self._setRow(self._ROW_IP, self._ICON_FAIL, self._T_NO_ADDRESS, "", self._COL_FAIL)
		self._testGateway()

	def _testGateway(self):
		adapter = nm.adapters.get(self._iface) if nm else None
		gw = ""
		if adapter:
			conn = adapter.activeConnection()
			if conn:
				gw = _ip4Str(conn.gateway)
		if not gw:
			self._setRow(self._ROW_GATEWAY, self._ICON_SKIP, self._T_NO_GATEWAY, "", self._COL_PENDING)
			self._testInternet()
			return
		self._pingRow(self._ROW_GATEWAY, gw, self._T_REACHABLE, self._T_UNREACHABLE, gw, self._testInternet)

	def _testInternet(self):
		self._pingRow(self._ROW_INTERNET, "1.1.1.1", self._T_REACHABLE, self._T_UNREACHABLE, "1.1.1.1", self._testDns)

	def _testDns(self):
		self._pingRow(self._ROW_DNS, "google.com", self._T_CONFIRMED, self._T_UNCONFIRMED, "google.com", lambda: None)

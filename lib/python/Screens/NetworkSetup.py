"""
NetworkSetup.py – Network connection screens for Enigma2 / OpenATV

Screens:
	NetworkConnections          – lists all connections; MENU/OK opens context menu
	NetworkConnectionSetup      – Setup subclass for one Connection (BLUE → per-connection DNS)
	DnsSettings                 – global system DNS (config.usage.dns.*, networkManager)
	ScanResult                  – dataclass for one iwlist scan result
	NetworkWiFiScanScreen       – live iwlist scan, sorted by signal strength
	NetworkWiFiActivator        – ifup + wpa_supplicant + IP poll
	NetworkWiFiAddFlow          – stateless coordinator / entry point

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
from os.path import exists

from ipaddress import ip_address

from enigma import eTimer, gRGB

from Components.ActionMap import HelpableActionMap
from Components.Label import Label
from Components.Console import Console
from Components.config import (
	ConfigIP, ConfigNumber, ConfigPassword, ConfigSelection,
	ConfigText, ConfigYesNo, NoSave, ReadOnly, config, getConfigListEntry,
)
from Components.Converter.XmlMultiContent import SHAPE_STROKE_WIDTH, buildShapeRects
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo
from Screens.ChoiceBox import ChoiceBox
from Screens.Information import InformationBase, formatLine
from Screens.MessageBox import MessageBox
from Screens.Processing import Processing
from Screens.RestartNetwork import RestartNetworkNew
from Screens.Screen import Screen
from Screens.Setup import Setup
from skin import parseColor
from Tools.Conversions import formatNetworkSpeed
from Tools.Directories import SCOPE_GUISKIN, SCOPE_SKINS, fileReadLines, fileReadXML, fileWriteLines, resolveFilename
from Tools.LoadPixmap import LoadPixmap
from Tools.ServiceAction import ServiceAction
from Components.NetworkManager import Adapter, Connection, WiFiConfig, networkManager, encNone, encWep, encWpa, encWpa2, encWpa3, pingAsync


MODULE_NAME = __name__.split(".")[-1]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_ENC_SHORT = {encNone: "open", encWep: "WEP", encWpa: "WPA", encWpa2: "WPA2", encWpa3: "WPA3"}


def _ip4Str(addr: list) -> str:
	joined = ".".join(str(x) for x in addr)
	return "" if joined == "0.0.0.0" else joined


# ===========================================================================
# DnsSettings – global system DNS (drop-in replacement for DNSSettings)
# ===========================================================================
class DnsSettings(Setup):
	"""Global system DNS configuration. Uses networkManager (NetworkManager.py)."""

	def __init__(self, session):
		dnsInitial = list(networkManager.nameserverConfig.servers) if networkManager is not None else []
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
		result = [0, 0, 0, 0]
		if networkManager is not None:
			for iface in sorted(networkManager.adapters.keys()):
				adapter = networkManager.adapters[iface]
				if adapter.kernelUp:
					conn = adapter.activeConnection()
					if conn:
						result = list(conn.gateway)
						break
		return result

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
		if networkManager is not None:
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
			networkManager.setNameservers(servers)
			networkManager.save()
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
			result = str(int(val))
		except Exception:
			result = str(int(default))
		return result

	def _replaceKeyLine(self, line, key, newRhs, foundSet):
		ls = line.lstrip()
		indent = line[:len(line) - len(ls)]
		result = line
		if ls.startswith(f"{key} ") or ls.startswith(f"{key}=") or ls.startswith(f"#{key} ") or ls.startswith(f"#{key}="):
			foundSet.add(key)
			result = f"{indent}{key} = {newRhs}"
		return result

	def _findGlobalEnd(self, lines):
		result = len(lines)
		for idx, line in enumerate(lines):
			stripped = line.lstrip()
			if stripped.startswith("[") and stripped.rstrip().endswith("]") and not stripped.startswith("#"):
				result = idx
				break
		return result

	def _insertGlobalKey(self, lines, key, rhs, anchorKeys, foundSet):
		if key in foundSet:
			return
		endGlobal = self._findGlobalEnd(lines)
		insertAt = None
		for idx in range(endGlobal):
			stripped = lines[idx].lstrip()
			for anchor in anchorKeys:
				if stripped.startswith(f"{anchor} ") or stripped.startswith(f"{anchor}=") or stripped.startswith(f"#{anchor} ") or stripped.startswith(f"#{anchor}="):
					insertAt = idx + 1
		lines.insert(insertAt if insertAt is not None else endGlobal, f"{key} = {rhs}")
		foundSet.add(key)

	def _findSectionRange(self, lines, sectionName):
		start = None
		result = None
		for idx, line in enumerate(lines):
			stripped = line.lstrip()
			if stripped.startswith("[") and stripped.rstrip().endswith("]") and not stripped.startswith("#"):
				name = stripped.strip()[1:-1].strip()
				if start is None and name == sectionName:
					start = idx + 1
					continue
				if start is not None:
					result = (start, idx)
					break
		if result is None:
			result = (start, len(lines)) if start is not None else (None, None)
		return result

	def _insertSectionKey(self, lines, sectionName, key, rhs, anchorKeys, foundSet):
		token = f"{sectionName}.{key}"
		if token not in foundSet:
			start, end = self._findSectionRange(lines, sectionName)
			if start is not None:
				insertAt = None
				for idx in range(start, end):
					stripped = lines[idx].lstrip()
					for anchor in anchorKeys:
						if stripped.startswith(f"{anchor} ") or stripped.startswith(f"{anchor}=") or stripped.startswith(f"#{anchor} ") or stripped.startswith(f"#{anchor}="):
							insertAt = idx + 1
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
				info.append(formatLine("P1", _("TX rate"), f"{adapter.kernelBitrateBps / 1_000_000:.1f} Mbps"))
			if adapter.kernelSignal:
				info.append(formatLine("P1", _("Signal"), f"{adapter.kernelSignal} dBm"))
		else:
			info.append(formatLine("P1", _("Link"), _("Yes") if adapter.kernelLink else _("No")))
			if adapter.kernelSpeed > 0:
				duplexLabels = {
					"full": _("Full duplex"),
					"half": _("Half duplex")
				}
				info.append(formatLine("P1", _("Speed"), f"{formatNetworkSpeed(adapter.kernelSpeed)} {duplexLabels.get(adapter.kernelDuplex, adapter.kernelDuplex)}"))
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
	INDEX_ADAPTER_PIXMAP = 1
	INDEX_ENABLED_ICON = 2
	INDEX_ENABLED_COLOR = 3
	INDEX_ENABLED_PIXMAP = 4
	INDEX_LINK_ICON = 5
	INDEX_LINK_PIXMAP = 6
	INDEX_LINK_TEXT = 7
	INDEX_INET_ICON = 8
	INDEX_INET_PIXMAP = 9
	INDEX_STATE_COLOR = 10
	INDEX_STATE_COLOR_SELECTED = 11
	INDEX_ADAPTER_TEXT1 = 12
	INDEX_ADAPTER_TEXT2 = 13
	INDEX_CONNECTION_TEXT1 = 14
	INDEX_CONNECTION_TEXT2 = 15
	INDEX_CONNECTION_TEXT3 = 16
	INDEX_CONNECTION_TEXT4 = 17
	INDEX_CONNECTOR = 18
	INDEX_ADAPTER = 19
	INDEX_CONN = 20

	COLOR_LINK = gRGB(0x0000CC00).argb()  # green  – physical link up
	COLOR_ENABLED = gRGB(0x00FFFFFF).argb()  # white  – enabled, no link
	COLOR_GRAY = gRGB(0x00808080).argb()  # gray   – disabled
	COLOR_LINK_SELECTED = COLOR_LINK
	COLOR_ENABLED_SELECTED = COLOR_ENABLED
	COLOR_GRAY_SELECTED = COLOR_GRAY

	COLOR_ON = gRGB(0x0000CC00).argb()   # green – enabledColor when adapter/connection is enabled
	COLOR_OFF = gRGB(0x00CC0000).argb()  # red   – enabledColor when disabled

	ICON_LAN = "\uEA5A"   # settings_ethernet
	ICON_WIFI = "\uE9FE"  # wifi
	ICON_INET = "\uEA5B"  # globe
	ICON_CHECKBOX_ON = "\uE91B"   # check_box
	ICON_CHECKBOX_OFF = "\uE935" 	# check_box_outline_blank
	ICON_LINK_ACTIVE = "\uEA62"    # arrow_circle_up
	ICON_LINK_INACTIVE = "\uEA5C"  # arrow_circle_down

	# TOOD:
	# Adapter row / UP/DOWN.  -- text or glyph

	skin = """
	<screen name="NetworkConnections" title="Network Connections" position="center,center" size="980,570">
        <widget source="list" render="Listbox" position="10,10" size="e-20,e-70">
			<template name="Default" fonts="enigma2icons;46,Regular;25,Regular;20,enigma2icons;25" itemHeight="50" shapeStroke="2" colorStateLink="#0000CC00" colorStateEnabled="#00FFFFFF" colorStateDisabled="#00808080" colorStateLinkSelected="#0000CC00" colorStateEnabledSelected="#00FFFFFF" colorStateDisabledSelected="#00808080">
				<mode name="default">
                    <!-- adapter icon (large, left) -->
                    <text index="adapterIcon" position="10,2" size="46,46" font="0" horizontalAlignment="center" verticalAlignment="center" />
                    <!-- enabled/disabled glyph placeholder -->
                    <text index="enabledIcon" position="65,10" size="30,30" font="3" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=3" foregroundColorSelected="=3" />
                    <!-- up/down glyph placeholder -->
                    <text index="linkIcon" position="100,10" size="30,30" font="3" horizontalAlignment="center" verticalAlignment="center" />
                    <!-- adapterText1/adapterText2 -->
                    <text index="adapterText1" position="140,0" size="740,50" font="1" horizontalAlignment="left" verticalAlignment="center" />
                    <!-- <text index="adapterText2" position="110,0" size="840,50" font="1" horizontalAlignment="left" verticalAlignment="center" /> -->
                    <!-- connection connectionText1: profile/LAN + IP -->
                    <text index="connectionText1" position="130,0" size="820,25" font="2" horizontalAlignment="left" verticalAlignment="center" />
                    <!-- connection connectionText2: speed / mask / gw -->
                    <text index="connectionText2" position="130,25" size="820,25" font="2" horizontalAlignment="left" verticalAlignment="center" />
                    <!--<text index="connectionText3" position="130,25" size="820,25" font="2" horizontalAlignment="left" verticalAlignment="center" /> -->
                    <!--<text index="connectionText4" position="130,25" size="820,25" font="2" horizontalAlignment="left" verticalAlignment="center" /> -->
					<!-- tree connector branch/last_child -->
					<shape index="connector" position="10,0" size="50,50" foregroundColor="white" foregroundColorSelected="white" />
                    <!-- internet icon top-right (connection rows only) -->
                    <text index="inetIcon" position="e-50,4" size="34,34" font="3" horizontalAlignment="center" verticalAlignment="center" />
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
    </screen>
	"""

	skinA = """
	<screen name="NetworkConnections" title="Network Connections" position="center,center" size="980,600" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="980,520" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;42,Regular;28,Regular;20,enigma2icons;24,Regular;30" itemHeight="80" shapeStroke="8" colorStateLink="#0000CC00" colorStateEnabled="#00FFFFFF" colorStateDisabled="#00808080" colorStateLinkSelected="#0000CC00" colorStateEnabledSelected="#00FFFFFF" colorStateDisabledSelected="#00808080">
				<mode name="default">
					<!-- adapter icon (large, left) -->
					<text index="adapterIcon" position="6,4" size="58,72" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=9" foregroundColorSelected="=10" />
					<!-- enabled/disabled checkbox placeholder -->
					<text index="enabledIcon" position="66,26" size="30,30" font="3" horizontalAlignment="center" verticalAlignment="center" foregroundColor="=3" foregroundColorSelected="=3" />
					<!-- TODO: adapterText1/adapterText2, connectionText1..4 widgets — positioning follows later -->
					<!-- tree connector branch/last_child -->
					<shape index="connector" position="0,0" size="80,80" foregroundColor="=9" foregroundColorSelected="=10" />
					<!-- internet icon top-right (connection rows only) -->
					<text index="inetIcon" position="e-50,4" size="34,34" font="3" horizontalAlignment="center" verticalAlignment="center" />
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
		Screen.__init__(self, session, enableHelp=True, mandatoryWidgets=["test"])
		self.setTitle(_("Network Connections"))
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText("")
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")
		# Tuple indices (see class INDEX_* constants):
		#   0=adapterIcon    adapter: WLAN/LAN iconfont;  connection: ""
		#   1=adapterPixmap  adapter: wired/wireless-active/inactive;  connection: None
		#   2=enabledIcon    adapter: enabled indicator;  connection: ""
		#   3=enabledColor   COLOR_ON (green) if enabled else COLOR_OFF (red), both rows
		#   4=enabledPixmap  adapter: None;               connection: lock_on/lock_error (checkbox as image)
		#   5=linkIcon       adapter: link active/inactive glyph;  connection: ""
		#   6=linkPixmap     adapter: None;               connection: None
		#   7=linkText       adapter: _("Up")/_("Down");  connection: ""
		#   8=inetIcon       adapter: "";                 connection: globe char if internet
		#   9=inetPixmap     adapter: "";                 connection: None
		#  10=stateColor     color int (both rows)
		#  11=stateColorSelected  color int, used when row is selected (both rows)
		#  12=adapterText1     adapter: "eth0 / Intern";    connection: ""
		#  13=adapterText2     adapter: "";                 connection: ""
		#  14=connectionText1  adapter: "";                 connection: "Profile: SSID  IP: ..."
		#  15=connectionText2  adapter: "";                 connection: "speed / mask / gw"
		#  16=connectionText3  adapter: "";                 connection: ""
		#  17=connectionText4  adapter: "";                 connection: ""
		#  18=connector      adapter: None;               connection: buildShapeRects("branch"/"lastchild")
		#  19=adapter        always the Adapter object
		#  20=conn           None for adapter row, Connection for connection row
		indexNames = {
			"adapterIcon": self.INDEX_ADAPTER_ICON,
			"adapterPixmap": self.INDEX_ADAPTER_PIXMAP,
			"enabledIcon": self.INDEX_ENABLED_ICON,
			"enabledColor": self.INDEX_ENABLED_COLOR,
			"enabledPixmap": self.INDEX_ENABLED_PIXMAP,
			"linkIcon": self.INDEX_LINK_ICON,
			"linkPixmap": self.INDEX_LINK_PIXMAP,
			"linkText": self.INDEX_LINK_TEXT,
			"inetIcon": self.INDEX_INET_ICON,
			"inetPixmap": self.INDEX_INET_PIXMAP,
			"stateColor": self.INDEX_STATE_COLOR,
			"stateColorSelected": self.INDEX_STATE_COLOR_SELECTED,
			"adapterText1": self.INDEX_ADAPTER_TEXT1,
			"adapterText2": self.INDEX_ADAPTER_TEXT2,
			"connectionText1": self.INDEX_CONNECTION_TEXT1,
			"connectionText2": self.INDEX_CONNECTION_TEXT2,
			"connectionText3": self.INDEX_CONNECTION_TEXT3,
			"connectionText4": self.INDEX_CONNECTION_TEXT4,
			"connector": self.INDEX_CONNECTOR,
		}
		self["list"] = List([], indexNames=indexNames)
		self["list"].onSelectionChanged.append(self.updateGreenKey)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions", "MenuActions", "InfoActions"], {
			"ok": (self.keyOK, _("Open settings for selected network connection")),
			"cancel": (self.close, _("Close network connection list")),
			"close": (self.keyCloseRecursive, _("Close the screen and exit all menus")),
			"red": (self.close, _("Close network connection list")),
			"green": (self.keyGreen, _("Activate/Deactivate adapter or connection")),
			"yellow": (self.keyYellow, _("Add a new WiFi connection")),
			"info": (self.keyInfo, _("Show network connection info")),
			"menu": (self.keyMenu, _("Open context menu for selected network connection")),
		}, prio=0, description=_("Network Connection Actions"))
		self._colorLink = self.COLOR_LINK
		self._colorEnabled = self.COLOR_ENABLED
		self._colorDisabled = self.COLOR_GRAY
		self._colorLinkSelected = self.COLOR_LINK_SELECTED
		self._colorEnabledSelected = self.COLOR_ENABLED_SELECTED
		self._colorDisabledSelected = self.COLOR_GRAY_SELECTED
		self.onLayoutFinish.append(self._readSkinColors)
		self.onLayoutFinish.append(self._buildList)
		self._internetChecked = False
		self._internetResult = None
		self.onShown.append(self.checkInternet)
		if networkManager:
			networkManager.onAdaptersChanged.append(self._buildList)
			self.onClose.append(lambda: networkManager.onAdaptersChanged.remove(self._buildList) if self._buildList in networkManager.onAdaptersChanged else None)

	def _readSkinColors(self):
		attrs = self["list"].additionalTemplateAttributes
		self._colorLink = parseColor(attrs["colorStateLink"]).argb() if "colorStateLink" in attrs else self.COLOR_LINK
		self._colorEnabled = parseColor(attrs["colorStateEnabled"]).argb() if "colorStateEnabled" in attrs else self.COLOR_ENABLED
		self._colorDisabled = parseColor(attrs["colorStateDisabled"]).argb() if "colorStateDisabled" in attrs else self.COLOR_GRAY
		self._colorLinkSelected = parseColor(attrs["colorStateLinkSelected"]).argb() if "colorStateLinkSelected" in attrs else self.COLOR_LINK_SELECTED
		self._colorEnabledSelected = parseColor(attrs["colorStateEnabledSelected"]).argb() if "colorStateEnabledSelected" in attrs else self.COLOR_ENABLED_SELECTED
		self._colorDisabledSelected = parseColor(attrs["colorStateDisabledSelected"]).argb() if "colorStateDisabledSelected" in attrs else self.COLOR_GRAY_SELECTED
		self._shapeStroke = int(attrs["shapeStroke"]) if "shapeStroke" in attrs else SHAPE_STROKE_WIDTH
		self._formats = self["list"].templateDataFormats

	def checkInternet(self):
		def checkInternetCallback(result):
			if hasattr(self, "_internetResult"):
				self._internetResult = result
				self._buildList()
				self._internetChecked = True

		if not self._internetChecked:
			networkManager.checkConnectionInternet(callback=checkInternetCallback)

	@staticmethod
	def _adapterPixmap(adapter: Adapter):
		if adapter.isWlan:
			name = "network_wireless-active.png" if adapter.kernelLink else "network_wireless-inactive.png" if adapter.effectiveEnabled else "network_wireless.png"
		else:
			name = "network_wired-active.png" if adapter.kernelLink else "network_wired-inactive.png" if adapter.effectiveEnabled else "network_wired.png"
		return LoadPixmap(resolveFilename(SCOPE_GUISKIN, f"icons/{name}"))

	@staticmethod
	def _connPixmap(conn: Connection):
		name = "lock_on.png" if conn.enabled else "lock_error.png"
		return LoadPixmap(cached=True, path=resolveFilename(SCOPE_GUISKIN, f"icons/{name}"))

	def _buildList(self):
		# Default format strings for the 6 free-form text items (see templateDataFormats /
		# applyFormat) — used whenever the skin doesn't set its own "format" attribute.
		# Not wrapped in _() here: this module executes once at import time, which would
		# freeze the translation instead of re-evaluating it on every language switch.
		_ADAPTER_TEXT1_FORMAT = "{adapterName}"
		_ADAPTER_TEXT2_FORMAT = "{busName}"
		_CONNECTION_TEXT1_FORMAT = "{profileName}"
		_CONNECTION_TEXT2_FORMAT = "{ip}"
		_CONNECTION_TEXT3_FORMAT = "{speed}"
		_CONNECTION_TEXT4_FORMAT = "{netmask} {gateway}"

		def applyFormat(formats: dict, key: str, default: str, **kwargs) -> str:
			"""Applies the skin-provided format string for 'key' (see templateDataFormats),
			falling back to 'default' if none is set or it references an unknown variable."""
			template = formats.get(key, default)
			try:
				return template.format(**kwargs)
			except (KeyError, IndexError) as err:
				print(f"[NetworkSetup] Error: format for '{key}' ('{template}') references unknown variable {err}!")
				return default.format(**kwargs)

		def connectionFields(conn: Connection, adapter: Adapter) -> dict:
			"""Named values available to a connection row's format strings (connectionText1..4)."""

			def connLiveIp(adapter: Adapter) -> str:
				ip = ".".join(str(x) for x in adapter.kernelIp)
				return "" if ip == "0.0.0.0" else ip

			if conn.isWlan:
				profileValue = conn.name or (conn.wlan.ssid if conn.wlan else "") or conn.adapter
				profileName = f"{_('Profile')}: {profileValue}"
			else:
				profileName = _("LAN connection")
			speedParts = []
			if adapter.isWlan:
				if adapter.kernelBitrateBps:
					speedParts.append(f"{adapter.kernelBitrateBps // 1000000} Mbps")
				if adapter.kernelSignal:
					speedParts.append(f"{adapter.kernelSignal} dBm")
			elif adapter.kernelSpeed > 0:
				speedParts.append(formatNetworkSpeed(adapter.kernelSpeed))
			liveIp = connLiveIp(adapter)
			return {
				"profileName": profileName,
				"ip": f"IP: {liveIp}" if liveIp else "",
				"speed": "   ".join(speedParts),
				"netmask": f"Mask: {_ip4Str(adapter.kernelNetmask)}" if adapter.adapterEnabled else "",
				"gateway": f"GW: {_ip4Str(adapter.kernelGateway)}" if adapter.adapterEnabled and liveIp else "",
			}

		entries: list[tuple] = []
		for iface in sorted(networkManager.adapters.keys()):
			adapter = networkManager.adapters[iface]
			internet = self._internetResult and self._internetResult.get(iface)
			adapterIcon = self.ICON_WIFI if adapter.isWlan else self.ICON_LAN
			checkBox = self.ICON_CHECKBOX_ON if adapter.effectiveEnabled else self.ICON_CHECKBOX_OFF
			adapterColor = self._colorLink if adapter.kernelLink else self._colorEnabled if adapter.effectiveEnabled else self._colorDisabled
			adapterColorSelected = self._colorLinkSelected if adapter.kernelLink else self._colorEnabledSelected if adapter.effectiveEnabled else self._colorDisabledSelected
			enabledColor = self.COLOR_ON if adapter.effectiveEnabled else self.COLOR_OFF
			adapterKwargs = {
				"adapterName": iface,
				"busName": "USB" if adapter.kernelBus == "usb" else _("Internal"),
				"driver": adapter.kernelDriver,
				"mac": adapter.mac,
			}
			adapterText1 = applyFormat(self._formats, "adapterText1", _ADAPTER_TEXT1_FORMAT, **adapterKwargs)
			adapterText2 = applyFormat(self._formats, "adapterText2", _ADAPTER_TEXT2_FORMAT, **adapterKwargs)
			linkIcon = self.ICON_LINK_ACTIVE if adapter.kernelLink else self.ICON_LINK_INACTIVE
			linkText = _("Up") if adapter.kernelLink else _("Down")
			entries.append((
				adapterIcon,                    # adapterIcon
				self._adapterPixmap(adapter),   # adapterPixmap
				checkBox,                       # enabledIcon
				enabledColor,                   # enabledColor
				None,                           # enabledPixmap
				linkIcon,                       # linkIcon
				None,                           # linkPixmap
				linkText,                       # linkText
				"",                             # inetIcon
				None,                           # inetPixmap
				adapterColor,                   # stateColor
				adapterColorSelected,           # stateColorSelected
				adapterText1,                   # adapterText1
				adapterText2,                   # adapterText2
				"",                             # connectionText1
				"",                             # connectionText2
				"",                             # connectionText3
				"",                             # connectionText4
				None,                           # connector
				adapter,                        # adapter
				None,                           # conn
			))
			# For Wi-Fi: skip the base connection (no SSID) when wpa_supplicant
			# connections with SSIDs are present — the base only carries IP config.
			conns = adapter.connections
			if adapter.isWlan and any(x.wlan and x.wlan.ssid for x in conns):
				conns = [x for x in conns if x.wlan and x.wlan.ssid]
			for idx, conn in enumerate(conns):
				isLast = idx == len(conns) - 1
				connColor = self._colorEnabled if conn.enabled else self._colorDisabled
				connColorSelected = self._colorEnabledSelected if conn.enabled else self._colorDisabledSelected
				enabledColor = self.COLOR_ON if conn.enabled else self.COLOR_OFF
				inetIcon = self.ICON_INET if (internet and conn.enabled) else ""
				connectionKwargs = connectionFields(conn, adapter)
				connectionText1 = applyFormat(self._formats, "connectionText1", _CONNECTION_TEXT1_FORMAT, **connectionKwargs)
				connectionText2 = applyFormat(self._formats, "connectionText2", _(_CONNECTION_TEXT2_FORMAT), **connectionKwargs)
				connectionText3 = applyFormat(self._formats, "connectionText3", _CONNECTION_TEXT3_FORMAT, **connectionKwargs)
				connectionText4 = applyFormat(self._formats, "connectionText4", _(_CONNECTION_TEXT4_FORMAT), **connectionKwargs)
				entries.append((
					"",                                                              # adapterIcon
					None,                                                            # adapterPixmap
					"",                                                              # enabledIcon
					enabledColor,                                                    # enabledColor
					self._connPixmap(conn),                                          # enabledPixmap
					"",                                                              # linkIcon
					None,                                                            # linkPixmap
					"",                                                              # linkText
					inetIcon,                                                        # inetIcon
					None,                                                            # inetPixmap
					connColor,                                                       # stateColor
					connColorSelected,                                               # stateColorSelected
					"",                                                              # adapterText1
					"",                                                              # adapterText2
					connectionText1,                                                 # connectionText1
					connectionText2,                                                 # connectionText2
					connectionText3,                                                 # connectionText3
					connectionText4,                                                 # connectionText4
					buildShapeRects("lastchild" if isLast else "branch", self._shapeStroke),  # connector
					adapter,                                                         # adapter
					conn,                                                            # conn
				))
		self["list"].setList(entries)
		text = _("Add Wi-Fi") if any(x.isWlan for x in networkManager.adapters.values()) else ""
		self["key_yellow"].setText(text)
		self["actions"].setEnabledAction("yellow", text != "")
		self.updateGreenKey()

	def _current(self) -> tuple | None:
		return self["list"].getCurrent()

	def keyOK(self):
		entry = self._current()
		if entry is not None:
			conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
			if conn is not None:
				self._openSetup(conn, adapter)

	def keyCloseRecursive(self):
		self.close(True)

	def keyGreen(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		if conn is None:
			self._toggleAdapter(adapter)
		else:
			self._toggleConnection(conn, adapter)

	def keyInfo(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		self.session.open(InformationNetworkConnection, conn, adapter)

	def updateGreenKey(self):
		entry = self._current()
		if entry is None:
			text = ""
		else:
			conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
			if conn is None:
				text = _("Deactivate") if adapter.effectiveEnabled else _("Activate")
			else:
				text = _("Disable connection") if conn.enabled else _("Enable connection")
		self["key_green"].setText(text)
		self["actions"].setEnabledAction("green", text != "")

	def keyMenu(self):
		entry = self._current()
		if entry is None:
			return
		conn, adapter = entry[self.INDEX_CONN], entry[self.INDEX_ADAPTER]
		if conn is None:
			self._showAdapterMenu(adapter)
		else:
			self._showContextMenu(conn, adapter)

	def _showAdapterMenu(self, adapter: Adapter):
		isEnabled = adapter.effectiveEnabled
		label = _("Disable adapter") if isEnabled else _("Enable adapter")
		self.session.openWithCallback(
			lambda choice: self._adapterMenuCb(choice, adapter),
			ChoiceBox,
			title=adapter.name,
			list=[(label, "toggle")],
		)

	def _adapterMenuCb(self, choice, adapter: Adapter):
		if choice and choice[1] == "toggle":
			self._toggleAdapter(adapter)

	def _connLabel(self, conn: Connection, adapter: Adapter) -> str:
		if conn.isWlan and conn.wlan and conn.wlan.ssid:
			result = f"{conn.adapter}  │  {conn.wlan.ssid}  [{_ENC_SHORT.get(conn.wlan.encryption, conn.wlan.encryption)}]"
		else:
			mode = "DHCP" if conn.dhcp else conn.ipStr()
			result = f"{conn.adapter}  │  {mode}"
		return result

	def _showContextMenu(self, conn: Connection, adapter: Adapter):
		menu = [
			(_("Settings"), "setup"),
			(_("Enable connection") if not conn.enabled else _("Disable connection"), "toggle"),
			(_("Enable adapter") if not adapter.effectiveEnabled else _("Disable adapter"), "toggleAdapter"),
			(_("Network test"), "test"),
			(_("Delete network connection"), "delete"),
		]
		if conn.isWlan:
			menu.append((_("Scan for Wi-Fi networks"), "scan"))
			menu.append((_("Add Wi-Fi manually"), "addManual"))
		self.session.openWithCallback(
			lambda choice: self._contextCb(choice, conn, adapter),
			ChoiceBox,
			title=_("Network connection: %s") % self._connLabel(conn, adapter),
			list=[(item[0], item[1]) for item in menu],
		)

	def _contextCb(self, choice, conn: Connection, adapter: Adapter):
		if choice:
			action = choice[1]
			if action == "setup":
				self._openSetup(conn, adapter)
			elif action == "toggle":
				self._toggleConnection(conn, adapter)
			elif action == "toggleAdapter":
				self._toggleAdapter(adapter)
			elif action == "test":
				self.session.open(NetworkTest, adapter.name)
			elif action == "delete":
				self._confirmDelete(conn, adapter)
			elif action == "scan":
				self._openWlanScan(adapter.name)
			elif action == "addManual":
				self._openWlanManual(adapter)

	def _openSetup(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(
			self._setupClosed,
			NetworkConnectionSetup,
			conn,
			adapter,
		)

	def _setupClosed(self, *result):
		if len(result) == 1 and isinstance(result[0], tuple):
			recursive, saved = result[0]
		else:
			recursive = bool(result[0]) if result else False
			saved = False
		if saved:
			self._buildList()
		elif recursive:
			self.keyCloseRecursive()

	def _toggleAdapter(self, adapter: Adapter):
		Processing.instance.setDescription(_("Please wait..."))
		Processing.instance.showProgress(endless=True)
		adapter.adapterEnabled = not adapter.effectiveEnabled
		if networkManager:
			networkManager.save()
		Processing.instance.hideProgress()
		self._buildList()
		self.session.showInfo(_("Network adapter enabled") if adapter.effectiveEnabled else _("Network adapter disabled"))

	def _toggleConnection(self, conn: Connection, adapter: Adapter):
		Processing.instance.setDescription(_("Please wait..."))
		Processing.instance.showProgress(endless=True)
		if adapter.isWlan:
			if conn.enabled:
				for other in adapter.connections:
					other.enabled = False
			else:
				for other in adapter.connections:
					other.enabled = (other is conn)
		else:
			conn.enabled = not conn.enabled
			adapter.adapterEnabled = conn.enabled
		if networkManager:
			networkManager.save()
		Processing.instance.hideProgress()
		self._buildList()
		if adapter.isWlan and conn.enabled:
			self.session.openWithCallback(lambda *_: self._buildList(), NetworkWiFiActivator, conn, adapter)
		else:
			self.session.showInfo(_("Network connection enabled") if conn.enabled else _("Network connection disabled"))

	def _confirmDelete(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(
			lambda confirmed: self._doDelete(confirmed, conn, adapter),
			MessageBox,
			_("Delete network connection '%s'?") % self._connLabel(conn, adapter),
			type=MessageBox.TYPE_YESNO,
		)

	def _doDelete(self, confirmed: bool, conn: Connection, adapter: Adapter):
		if confirmed:
			Processing.instance.setDescription(_("Please wait..."))
			Processing.instance.showProgress(endless=True)
			if conn.isWlan and conn.wlan:
				networkManager.removeConnection(adapter.name, conn.wlan.ssid)
			else:
				adapter.connections = [x for x in adapter.connections if x is not conn]
			if networkManager:
				networkManager.save()
			Processing.instance.hideProgress()
			self._buildList()

	def keyYellow(self):
		if networkManager.adapters:
			wlanAdapters = [x for x in networkManager.adapters.values() if x.isWlan]
			if wlanAdapters:
				entry = self._current()
				selected = entry[self.INDEX_ADAPTER] if entry is not None else None
				preselected = selected if selected is not None and selected.isWlan else None
				NetworkWiFiAddFlow.start(self.session, adapter=preselected, callback=self._buildList)

	def _openWlanScan(self, iface: str):
		if networkManager is not None:
			adapter = networkManager.getAdapter(iface)
			if adapter is not None and adapter.isWlan:
				self.session.openWithCallback(
					lambda result: self._wlanScanDone(result, adapter),
					NetworkWiFiScanScreen,
					adapter,
				)

	def _wlanScanDone(self, result: ScanResult | None, adapter: Adapter):
		if result:
			conn = _scanResultToConnection(result, adapter.name)
			self.session.openWithCallback(
				self._setupClosed,
				NetworkConnectionSetup,
				conn,
				adapter,
			)

	def _openWlanManual(self, adapter: Adapter):
		conn = Connection(adapter=adapter.name, name=_("New Wi-Fi"), dhcp=True, enabled=False, wlan=WiFiConfig())
		self.session.openWithCallback(
			self._setupClosed,
			NetworkConnectionSetup,
			conn,
			adapter,
		)


# ===========================================================================
# NetworkConnectionSetup – Screen 2 (Setup subclass)
# ===========================================================================

class NetworkConnectionSetup(Setup):
	"""Setup screen for one Connection."""

	RANK_LABELS = (
		_("1st (Highest)"),
		_("2nd"),
		_("3rd"),
		_("4th"),
		_("5th"),
		_("6th"),
		_("7th"),
		_("8th"),
		_("9th"),
		_("10th (Lowest)"),
	)

	def __init__(self, session, conn: Connection, adapter: Adapter):
		self._conn = conn
		self._adapter = adapter
		self._buildConfigObjects()
		xmlSection = "NetworkWiFi" if conn.isWlan else "NetworkLAN"
		Setup.__init__(self, session=session, setup=xmlSection)
		self.setTitle(_("Network Connection Settings – %s") % conn.adapter)
		self["key_info"] = StaticText(_("Info"))
		self["blueActions"] = HelpableActionMap(self, ["InfoActions"], {
			"info": (self.keyShowInfo, _("Show network connection info"))
		}, prio=0)

	def keyShowInfo(self):
		self.session.open(InformationNetworkConnection, self._conn, self._adapter)

	def _buildConfigObjects(self):
		conn = self._conn
		adapter = self._adapter  # noqa

		self.cfgName = NoSave(ConfigText(default=conn.name, fixed_size=False))
		self.cfgEnabled = NoSave(ConfigYesNo(default=conn.enabled))
		if conn.isWlan:
			wlanConns = [x for x in adapter.connections if x.isWlan and x.wlan and x.wlan.ssid]
			if not any(x is conn for x in wlanConns):
				wlanConns = wlanConns + [conn]
			self._hasMultiplePriorities = len(wlanConns) > 1
			if self._hasMultiplePriorities:
				self._wlanConnsSorted = sorted(wlanConns, key=lambda wlanConn: wlanConn.priority, reverse=True)
				currentRank = next((idx + 1 for idx, x in enumerate(self._wlanConnsSorted) if x is conn), 1)
				rankChoices = [(x + 1, self.RANK_LABELS[x] if x < len(self.RANK_LABELS) else _("%d.") % (x + 1)) for x in range(len(wlanConns))]
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

		encryptionChoices = [
			(encNone, _("None")),
			(encWep, "WEP"),
			(encWpa, "WPA"),
			(encWpa2, "WPA2"),
		]
		if BoxInfo.getItem("wpa3") or (conn.isWlan and conn.wlan and conn.wlan.encryption == encWpa3):
			encryptionChoices.append((encWpa3, "WPA3"))

		if conn.isWlan and conn.wlan:
			wlan = conn.wlan
			self.cfgSsid = NoSave(ConfigText(default=wlan.ssid, fixed_size=False))
			self.cfgHidden = NoSave(ConfigYesNo(default=wlan.hidden))
			self.cfgEncryption = NoSave(ConfigSelection(choices=encryptionChoices, default=wlan.encryption))
			self.cfgKey = NoSave(ConfigPassword(default=wlan.key, fixed_size=False))
		else:
			self.cfgSsid = NoSave(ConfigText(default="", fixed_size=False))
			self.cfgHidden = NoSave(ConfigYesNo(default=False))
			self.cfgEncryption = NoSave(ConfigSelection(choices=encryptionChoices, default=encNone))
			self.cfgKey = NoSave(ConfigPassword(default="", fixed_size=False))

		# Wake-on-LAN (LAN adapters only, when hardware supports it)
		self.cfgWakeOnLan = NoSave(ConfigYesNo(default=conn.wakeOnLan != "off"))

		# Forced link speed (LAN adapters only)
		if not conn.isWlan and networkManager is not None:
			linkSpeedChoices = networkManager.getSupportedLinkSpeeds(adapter.name)
			currentLinkSpeed = networkManager.getLinkSpeed(adapter.name)
			if currentLinkSpeed not in dict(linkSpeedChoices):
				currentLinkSpeed = "auto"
			self._hasLinkSpeedChoices = len(linkSpeedChoices) > 1
			self.cfgLinkSpeed = NoSave(ConfigSelection(choices=linkSpeedChoices, default=currentLinkSpeed))
		else:
			self._hasLinkSpeedChoices = False
			self.cfgLinkSpeed = NoSave(ConfigSelection(choices=[("auto", _("Auto"))], default="auto"))

		# Wake-on-WiFi (Broadcom wlan3 only)
		# cfgWakeOnWiFi: WoW while normally active (activate=True)
		# cfgWowOnly:    WoW only, no normal connection (activate=False)
		self.cfgWakeOnWiFi = NoSave(ConfigYesNo(default=conn.wakeOnWiFi and conn.enabled))
		self.cfgWowOnly = NoSave(ConfigYesNo(default=conn.wakeOnWiFi and not conn.enabled))

		# Per-connection DNS (inline, replaces separate DNS setup screen)
		hasOwn = bool(conn.dnsServers)
		self.cfgDnsOverride = NoSave(ConfigYesNo(default=hasOwn))
		dnsV4 = [x for x in conn.dnsServers if isinstance(x, list)]
		dnsV6 = [x for x in conn.dnsServers if isinstance(x, str)]
		self.cfgDns1v4 = NoSave(ConfigIP(default=dnsV4[0] if len(dnsV4) > 0 else [0, 0, 0, 0]))
		self.cfgDns2v4 = NoSave(ConfigIP(default=dnsV4[1] if len(dnsV4) > 1 else [0, 0, 0, 0]))
		self.cfgDns1v6 = NoSave(ConfigText(default=dnsV6[0] if len(dnsV6) > 0 else "", fixed_size=False))
		self.cfgDns2v6 = NoSave(ConfigText(default=dnsV6[1] if len(dnsV6) > 1 else "", fixed_size=False))

	def keySave(self):
		conn = self._conn
		adapter = self._adapter

		Processing.instance.setDescription(_("Please wait..."))
		Processing.instance.showProgress(endless=True)

		conn.name = self.cfgName.value
		conn.enabled = self.cfgEnabled.value
		if self._hasMultiplePriorities:
			chosenRank = self.cfgPriority.value
			others = [x for x in self._wlanConnsSorted if x is not conn]
			newOrder = others[:chosenRank - 1] + [conn] + others[chosenRank - 1:]
			for idx, wlanConn in enumerate(newOrder):
				wlanConn.priority = (len(newOrder) - idx) * 10
		else:
			conn.priority = int(self.cfgPriority.value)
		conn.dhcp = self.cfgDhcp.value
		conn.ipMode = self.cfgIpMode.value

		if not conn.dhcp:
			conn.ip = list(self.cfgIp.value)
			conn.netmask = list(self.cfgNetmask.value)
			conn.gateway = list(self.cfgGateway.value)

		if not self.cfgDnsOverride.value:
			conn.dnsServers = []
		else:
			servers = []
			for cfgV4 in (self.cfgDns1v4, self.cfgDns2v4):
				ipValue = list(cfgV4.value)
				if ipValue != [0, 0, 0, 0]:
					servers.append(ipValue)
			for cfgV6 in (self.cfgDns1v6, self.cfgDns2v6):
				textValue = cfgV6.value.strip()
				if textValue:
					servers.append(textValue)
			conn.dnsServers = servers

		if conn.isWlan and conn.wlan:
			wlan = conn.wlan
			wlan.ssid = self.cfgSsid.value.strip()
			wlan.hidden = self.cfgHidden.value
			wlan.encryption = self.cfgEncryption.value
			if wlan.encryption != encNone:
				wlan.key = self.cfgKey.value

		# Apply Wake-on-LAN via ethtool + optional /proc path
		if not conn.isWlan and adapter.canWakeOnLan:
			newWolMode = "g" if self.cfgWakeOnLan.value else "off"
			if newWolMode != conn.wakeOnLan and networkManager is not None:
				cmds = networkManager.setWakeOnLanCommands(adapter.name, newWolMode)
				if cmds:
					Console().eBatch(cmds, lambda result: None, debug=False)

		# Apply Wake-on-WiFi (Broadcom)
		if conn.isWlan and adapter.canWakeOnWiFi:
			if conn.enabled:
				conn.wakeOnWiFi = self.cfgWakeOnWiFi.value
			else:
				conn.wakeOnWiFi = self.cfgWowOnly.value
			if networkManager is not None:
				cmds = networkManager.setWakeOnWiFiCommands(adapter.name, conn.wakeOnWiFi)
				if cmds:
					Console().eBatch(cmds, lambda result: None, debug=False)

		# Apply forced link speed (LAN adapters only)
		if not conn.isWlan and networkManager is not None:
			networkManager.setLinkSpeed(adapter.name, self.cfgLinkSpeed.value)

		if not any(x is conn for x in adapter.connections):
			adapter.connections.append(conn)
		if networkManager is not None:
			networkManager.save()
		Processing.instance.hideProgress()
		if conn.isWlan and conn.enabled:
			self.session.openWithCallback(lambda *_: self.close((False, True)), NetworkWiFiActivator, conn, adapter)
		else:
			self.close((False, True))


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
			result = 4
		elif self.signalPct >= 60:
			result = 3
		elif self.signalPct >= 35:
			result = 2
		elif self.signalPct >= 10:
			result = 1
		else:
			result = 0
		return result

	@property
	def encLabel(self) -> str:
		return {
			encNone: _("None"),
			encWep: "WEP",
			encWpa: "WPA",
			encWpa2: "WPA2",
			encWpa3: "WPA3",
		}.get(self.encryption, self.encryption.upper())


def _scanResultToConnection(scanResult: ScanResult, iface: str) -> Connection:
	return Connection(
		adapter=iface,
		name=scanResult.ssid,
		dhcp=True,
		enabled=False,
		priority=0,
		wlan=WiFiConfig(ssid=scanResult.ssid, encryption=scanResult.encryption),
	)


# ===========================================================================
# NetworkWiFiScanScreen – live iwlist scan
# ===========================================================================

class NetworkWiFiScanScreen(Screen):
	"""Runs iwlist scan and shows results sorted by signal strength."""

	skin = """
	<screen name="NetworkWiFiScanScreen" title="Wi-Fi Scan" position="center,center" size="1000,455" resolution="1280,720">
		<widget source="list" render="Listbox" position="10,10" size="e-20,e-105">
			<template name="Default" fonts="Regular;25,Regular;20,enigma2icons;20" itemHeight="35">
				<mode name="default">
					<panel position="0,0" size="e,e" layout="horizontal">
						<text index="Name" position="left" size="460,35" flags="scroll" font="0" horizontalAlignment="left" padding="5,0" verticalAlignment="center" />
						<text index="Glyph" position="left" size="30,35" font="2" horizontalAlignment="center" padding="5,0" verticalAlignment="center" />
						<text index="Percentage" position="left" size="70,35" font="1" horizontalAlignment="right" padding="5,0" verticalAlignment="center" />
						<text index="dBm" position="left" size="100,35" font="1" horizontalAlignment="right" padding="5,0" verticalAlignment="center" />
						<text index="Encryption" position="left" size="110,35" font="1" horizontalAlignment="center" padding="5,0" verticalAlignment="center" />
						<text index="Channel" position="left" size="90,35" font="1" horizontalAlignment="right" padding="5,0" verticalAlignment="center" />
						<text index="Frequency" position="right" size="120,35" font="1" horizontalAlignment="right" padding="5,0" verticalAlignment="center" />
					</panel>
				</mode>
			</template>
		</widget>
		<widget name="description" position="10,e-85" size="e-20,25" font="Regular;20" padding="5,0" verticalAlignment="center" />
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="200,e-50" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="390,e-50" size="180,40" backgroundColor="key_yellow" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-100,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	STRENGTH_GLYPHS = ["", "\uEA66", "\uEA67", "\uEA64", "\uEA65"]

	def __init__(self, session, adapter: Adapter):
		Screen.__init__(self, session, enableHelp=True)
		self.adapter = adapter.name
		self.setTitle(_("Wi-Fi Scan – %s") % self.adapter)
		indexNames = {
			"Name": 0,
			"SSID": 1,
			"BSSID": 2,
			"Glyph": 3,
			"Strength": 4,
			"Percentage": 5,
			"dBm": 6,
			"Encryption": 7,
			"ChannelFrequency": 8,
			"Channel": 9,
			"Frequency": 10
		}
		self["list"] = List([], indexNames=indexNames)
		self["description"] = Label()
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Select"))
		self["key_yellow"] = StaticText(_("Rescan"))
		self["key_blue"] = StaticText("")
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"ok": (self.keySelect, _("Use selected Wi-Fi network")),
			"cancel": (self.keyClose, _("Close")),
			"red": (self.keyClose, _("Close")),
			"green": (self.keySelect, _("Use selected Wi-Fi network")),
			"yellow": (self.keyStartScan, _("Rescan for any available Wi-Fi networks"))
		}, prio=0, description=_("Wi-Fi Scan Actions"))
		self.console = Console()
		self.scanning = False
		self.accessPoints: dict[str, ScanResult] = {}
		self.onLayoutFinish.append(self.keyStartScan)

	def keySelect(self):
		current = self["list"].getCurrent()
		if current:
			self.close(current[-1])

	def keyClose(self):
		if self.console:
			self.console.killAll()
		self.close(None)

	def keyStartScan(self):
		def startScanCallback(results: str, retVal: int, extraArgs=None):
			def scanCompleteCallback(results: str, retVal: int, extraArgs=None):
				self.scanning = False
				if isinstance(results, bytes):
					results = results.decode("UTF-8", errors="replace")
				for accessPoint in self._parseIwlist(results):
					self.accessPoints[accessPoint.bssid] = accessPoint
				if self.accessPoints:
					accessPointList = []
					for accessPoint in sorted(self.accessPoints.values(), key=lambda ap: -ap.signalPct):
						accessPointList.append((
							f"{accessPoint.ssid}  ({accessPoint.bssid})",  # Name.
							accessPoint.ssid,  # SSID.
							accessPoint.bssid,  # BSSID.
							self.STRENGTH_GLYPHS[min(accessPoint.signalBars, 4)],  # Glyph.
							f"{accessPoint.signalPct}%  ({accessPoint.signalDbm} dBm)",  # Strength.
							f"{accessPoint.signalPct}%",  # Percent.
							f"{accessPoint.signalDbm} dBm",  # dBM.
							accessPoint.encLabel,  # Encryption.
							f"Ch-{accessPoint.channel}  ({accessPoint.frequency})",  # ChannelFrequency.
							f"Ch-{accessPoint.channel}",  # Channel.
							accessPoint.frequency,  # Frequency.
							accessPoint  # AccessPoint data record.
						))
					self["list"].setList(accessPointList)
					count = len(self.accessPoints)
					self["description"].setText(ngettext("%d network found.", "%d networks found.", count) % count)
				else:
					self["list"].setList([])
					self["description"].setText(_("No networks found."))

			self.console.ePopen(("/sbin/iwlist", "/sbin/iwlist", self.adapter, "scanning"), callback=scanCompleteCallback)

		if not self.scanning:
			self.scanning = True
			self["description"].setText(_("Scanning…"))
			self.console.ePopen(("/sbin/ifconfig", "/sbin/ifconfig", self.adapter, "up"), callback=startScanCallback)

	def _parseIwlist(self, raw: str) -> list[ScanResult]:
		results: list[ScanResult] = []
		current: ScanResult | None = None

		reCell = re.compile(r"Cell \d+ - Address:\s*([0-9A-Fa-f:]{17})")
		reSsid = re.compile(r'ESSID:"(.*?)"')
		reFreq = re.compile(r"Frequency:([\d.]+ \w+Hz).*?Channel:?\s*(\d+)?")
		reQuality = re.compile(r"Quality=(\d+)/(\d+)\s+Signal level=(-?\d+) dBm")
		reEncOn = re.compile(r"Encryption key:on")
		reEncOff = re.compile(r"Encryption key:off")
		reIeWpa1 = re.compile(r"IE:.*WPA Version 1", re.IGNORECASE)
		reIeWpa2 = re.compile(r"IE:.*WPA2|IE:.*RSN", re.IGNORECASE)
		reIeWpa3 = re.compile(r"IE:.*SAE|IE:.*WPA3", re.IGNORECASE)

		for line in raw.splitlines():
			line = line.strip()
			match = reCell.search(line)
			if match:
				current = ScanResult(bssid=match.group(1))
				results.append(current)
				continue
			if current is None:
				continue
			match = reSsid.search(line)
			if match:
				current.ssid = match.group(1)
			match = reFreq.search(line)
			if match:
				current.frequency = match.group(1)
				if match.group(2):
					current.channel = int(match.group(2))
			match = reQuality.search(line)
			if match:
				qVal, qMax = int(match.group(1)), int(match.group(2))
				current.signalPct = int(qVal * 100 / qMax) if qMax else 0
				current.signalDbm = int(match.group(3))
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

		return sorted((x for x in results if x.ssid), key=lambda x: -x.signalPct)


# ===========================================================================
# NetworkWiFiActivator – brings up a Wi-Fi connection
# ===========================================================================

class NetworkWiFiActivator(Screen):
	"""Runs ifup + wpa_supplicant (scoped to this one adapter, via wlanactivator)
	and polls for an IP address, so the user gets feedback if the connection
	attempt fails or times out."""

	skin = """
	<screen name="NetworkWiFiActivator" title="Connecting…" position="center,center" size="980,200" resolution="1280,720">
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
			self["status"].setText(self._diagnoseFailure())
			self._scheduleClose(6000)
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
		elif self._pollCount >= self._pollMaxAttempts:
			self._pollTimer.stop()
			self["status"].setText(self._diagnoseFailure())
			self._scheduleClose(6000)
		else:
			self._pollTimer.start(self._pollIntervalMs, True)

	def _diagnoseFailure(self) -> str:
		"""Best-effort explanation of *why* the connection attempt failed, based on
		wpa_supplicant's association state (wpa_cli status) – distinguishes a
		missing/unreachable AP, a wrong key, and DHCP-only failures instead of a
		single generic "failed" message."""
		iface = self._adapter.name
		ssid = self._conn.wlan.ssid if self._conn.wlan else iface
		if networkManager is None or not networkManager.wpaSupplicantRunning(iface):
			reason = _("Could not connect to '%s'.\nWi-Fi driver (wpa_supplicant) did not start – check your Wi-Fi settings.") % ssid
		else:
			state = networkManager.getWlanStatus(iface).get("wpa_state", "")
			if state == "COMPLETED":
				reason = _("Connected to '%s', but no IP address was received.\nCheck your router's DHCP settings.") % ssid
			elif state in ("4WAY_HANDSHAKE", "GROUP_HANDSHAKE"):
				reason = _("Could not connect to '%s'.\nWrong Wi-Fi password?") % ssid
			elif state in ("SCANNING", "DISCONNECTED", "INACTIVE", ""):
				reason = _("Access point '%s' not found.\nCheck that it is in range and the SSID is correct.") % ssid
			else:
				reason = _("Could not connect to '%s' (status: %s).") % (ssid, state)
		return reason + "\n" + _("Configuration saved – will retry automatically at next boot.")

	@staticmethod
	def _getKernelIp(iface: str) -> str:
		addrs = netifaces.ifaddresses(iface)
		result = ""
		if netifaces.AF_INET in addrs:
			result = addrs[netifaces.AF_INET][0].get("addr", "")
		return result

	def _scheduleClose(self, delayMs: int):
		self._closeTimer = eTimer()
		self._closeTimer.callback.append(lambda: self.close(True))
		self._closeTimer.start(delayMs, True)


# ===========================================================================
# NetworkWiFiAddFlow – coordinator / entry point
# ===========================================================================

class NetworkWiFiAddFlow:
	"""Stateless coordinator. Call NetworkWiFiAddFlow.start() to begin the flow."""

	@staticmethod
	def start(session, adapter: Adapter | None = None, callback=None):
		if networkManager is not None:
			if adapter is not None:
				NetworkWiFiAddFlow._openScan(session, adapter, callback)
			else:
				wlanAdapters = [x for x in networkManager.adapters.values() if x.isWlan]
				if not wlanAdapters:
					session.showWarning(_("No Wi-Fi adapter found."))
				elif len(wlanAdapters) == 1:
					NetworkWiFiAddFlow._openScan(session, wlanAdapters[0], callback)
				else:
					NetworkWiFiAddFlow._pickAdapter(session, wlanAdapters, callback)

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
					if not any(x.wlan and x.wlan.ssid == (conn.wlan.ssid if conn.wlan else "") for x in adapter.connections):
						adapter.connections.append(conn)
						if networkManager:
							networkManager.save()
				if callback:
					callback()
			session.openWithCallback(_setupDone, NetworkConnectionSetup, conn, adapter)
		session.openWithCallback(_scanned, NetworkWiFiScanScreen, adapter)

	@staticmethod
	def _pickAdapter(session, adapters: list[Adapter], callback):
		choices = [(x.name, x) for x in adapters]

		def _chosen(adapter):
			if not adapter:
				if callback:
					callback()
				return
			NetworkWiFiAddFlow._openScan(session, adapter, callback)

		session.openWithCallback(_chosen, MessageBox, _("Select Wi-Fi adapter"), type=MessageBox.TYPE_YESNO, list=choices)


# ===========================================================================
# NameserverSetup – backward-compat alias (some screens still import this)
# ===========================================================================

class NameserverSetup(DnsSettings):
	def __init__(self, session):
		DnsSettings.__init__(self, session=session)


# ===========================================================================
# NetworkTest – list-based adapter test (replaces NetworkAdapterTest)
# ===========================================================================


class NetworkTest(Screen):
	"""Sequential network adapter tests displayed as a simple list."""

	skin = """
	<screen name="NetworkTest" title="Network Test" position="center,center" size="900,510" resolution="1280,720">
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
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"cancel": (self.close, _("Close network test")),
			"red": (self.close, _("Close network test")),
			"green": (self._restart, _("Restart test")),
		}, prio=0, description=_("Network Test Actions"))
		self.onLayoutFinish.append(self._start)

	def _restart(self):
		self._generation += 1
		self._start()

	def _start(self):
		adapterName = networkManager.getFriendlyAdapterName(self._iface) if networkManager else self._iface
		self.setTitle(_("Network Test – %s") % adapterName)
		adapter = networkManager.adapters.get(self._iface) if networkManager else None
		isWlan = adapter.isWlan if adapter else False
		labels = [
			_("Adapter"),
			_("Wireless link") if isWlan else _("LAN link"),
			_("IP address"),
			_("Gateway"),
			"Internet",
			"DNS",
		]
		self._rows = [(self._ICON_BUSY, label, "", "", self._COL_PENDING) for label in labels]
		self["list"].setList(list(self._rows))
		self._testAdapter()

	def _setRow(self, idx: int, icon: str, result: str, detail: str, color: int):
		row = list(self._rows[idx])
		row[0], row[2], row[3], row[4] = icon, result, detail, color
		self._rows[idx] = tuple(row)
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
		adapter = networkManager.adapters.get(self._iface) if networkManager else None
		if adapter is None:
			self._setRow(self._ROW_ADAPTER, self._ICON_FAIL, self._T_NOT_FOUND, "", self._COL_FAIL)
			self._setRow(self._ROW_LINK, self._ICON_SKIP, self._T_NA, "", self._COL_PENDING)
			self._setRow(self._ROW_IP, self._ICON_SKIP, self._T_NA, "", self._COL_PENDING)
			self._testGateway()
			return
		self._setRow(self._ROW_ADAPTER, self._ICON_OK, networkManager.getFriendlyAdapterName(self._iface), adapter.kernelDriver or "", self._COL_OK)
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
				speed = f"{adapter.kernelSpeed} Mbps" if adapter.kernelSpeed > 0 else ""
				self._setRow(self._ROW_LINK, self._ICON_OK, self._T_CONNECTED, speed, self._COL_OK)
			else:
				self._setRow(self._ROW_LINK, self._ICON_FAIL, self._T_DISCONNECTED, "", self._COL_FAIL)
		self._testIp(adapter)

	def _testIp(self, adapter):
		ip = adapter.kernelIp or []
		ipStr = ".".join(str(x) for x in ip) if ip else ""
		if ipStr and ipStr != "0.0.0.0":
			conn = adapter.activeConnection()
			hint = "DHCP" if (conn and conn.dhcp) else self._T_STATIC
			self._setRow(self._ROW_IP, self._ICON_OK, ipStr, hint, self._COL_OK)
		else:
			self._setRow(self._ROW_IP, self._ICON_FAIL, self._T_NO_ADDRESS, "", self._COL_FAIL)
		self._testGateway()

	def _testGateway(self):
		adapter = networkManager.adapters.get(self._iface) if networkManager else None
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

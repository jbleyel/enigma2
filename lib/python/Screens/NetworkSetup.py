"""
NetworkSetup.py – Network connection screens for Enigma2 / OpenATV

Screens:
	NetworkOverview             – adapters + Wi-Fi connections, two XmlMultiContent listboxes
	NetworkAdapterSetup         – per-adapter DHCP/IP/DNS/WOL/WWOL/link speed (interfaces file)
	NetworkConnectionWiFi       – per-SSID profile settings (wpa_supplicant.conf only)
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
from Components.config import ConfigIP, ConfigNumber, ConfigPassword, ConfigSelection, ConfigText, ConfigYesNo, NoSave, ReadOnly, config, getConfigListEntry
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo
from Screens.ChoiceBox import ChoiceBox
from Screens.Information import InformationNetwork as InformationNetworkOriginal
from Screens.MessageBox import MessageBox
from Screens.Processing import Processing
from Screens.Screen import Screen
from Screens.Setup import Setup
from skin import parseColor
from Tools.Conversions import formatNetworkSpeed
from Tools.Directories import SCOPE_SKINS, fileReadLines, fileReadXML, fileWriteLines, resolveFilename
from Tools.ServiceAction import ServiceAction
from Components.NetworkManager import Adapter, Connection, VpnInfo, WiFiConfig, networkManager, encNone, encWep, encWpa, encWpa2, encWpa3, encryptionLabels, wpaCliBin, CHANGE_NONE, CHANGE_ADAPTER_ENABLED, CHANGE_GENERAL


MODULE_NAME = __name__.split(".")[-1]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_ENC_SHORT = {encNone: "open", encWep: "WEP", encWpa: "WPA", encWpa2: "WPA2", encWpa3: "WPA3"}


def _ip4Str(addr: list) -> str:
	joined = ".".join(str(x) for x in addr)
	return "" if joined == "0.0.0.0" else joined


# Apply the minimal action an adapter (LAN or WLAN) needs after
# networkManager.save() (nothing / ifup-ifdown / full restart), with a
# visible progress indicator while it runs, then call callback(). The caller
# passes `change` because it already knows what it just changed – save()
# itself stays a plain writer.
def applyAdapterChange(iface: str, change: int, callback):
	if change == CHANGE_NONE:
		# Nothing is actually going to happen to the network, so don't touch
		# plugins either – save() used to unconditionally call
		# notifyNetworkPlugins(False) on every save regardless of `change`,
		# which stopped plugins (e.g. OpenWebif) even for a no-op Save with
		# nothing to bring back up afterward, leaving them stopped for good.
		callback()
		return

	# The network is genuinely about to change (ifup/ifdown/restart below) –
	# tell plugins to stop now. Every notifyNetworkPlugins(False) here MUST be
	# paired with exactly one matching notifyNetworkPlugins(True) once that
	# same change has finished applying (doneNotify below for ifup/ifdown, or
	# inside restartNetwork() itself for CHANGE_GENERAL) – regardless of
	# whether this was an enable or a disable, so a plugin that was stopped
	# never gets left stopped forever. iface=iface: if another adapter is
	# already up, the box stays reachable through it, so this specific
	# adapter's change doesn't need to bounce plugins at all – but that
	# decision is symmetric for both the False and the True call, so pairing
	# still holds (both fire, or both are skipped).
	networkManager.notifyNetworkPlugins(False, iface=iface)

	Processing.instance.setDescription(_("Please wait..."))
	Processing.instance.showProgress(endless=True)

	def done(*_args):
		Processing.instance.hideProgress()
		callback()

	def doneNotify(*_args):
		# restartNetwork() (CHANGE_GENERAL) notifies plugins itself (it needs
		# to re-run discoverAdapters()/applyNetinfo() first); plain ifup/ifdown
		# don't refresh adapter state on their own, so do it here for both –
		# matching the notifyNetworkPlugins(False) above.
		networkManager.notifyNetworkPlugins(True, iface=iface)
		done(*_args)

	if change == CHANGE_GENERAL:
		networkManager.restartNetwork(iface=iface, callback=done)
	elif change == CHANGE_ADAPTER_ENABLED:
		adapter = networkManager.adapters.get(iface)
		if adapter and adapter.adapterEnabled:
			ServiceAction.ifup(iface, doneNotify)
		else:
			ServiceAction.ifdown(iface, doneNotify)
	else:
		done()


# ===========================================================================
# DnsSettings – global system DNS (drop-in replacement for DNSSettings)
# ===========================================================================
class DnsSettings(Setup):
	"""Global system DNS configuration. Uses networkManager (NetworkManager.py)."""

	def __init__(self, session):
		dnsInitial = list(networkManager.nameserverConfig.servers)
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
		for iface in sorted(networkManager.adapters.keys()):
			if networkManager.adapters[iface].netInfo.up:
				conn = networkManager.activeConnection(iface)
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
		self.close()

	# ------------------------------------------------------------------
	# DNSCrypt TOML helpers
	# ------------------------------------------------------------------

	def writeDnsCryptToml(self):
		def insertSectionKey(lines, sectionName, key, rhs, anchorKeys, foundSet):
			def findSectionRange(lines, sectionName):
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

			token = f"{sectionName}.{key}"
			if token not in foundSet:
				start, end = findSectionRange(lines, sectionName)
				if start is not None:
					insertAt = None
					for idx in range(start, end):
						stripped = lines[idx].lstrip()
						for anchor in anchorKeys:
							if stripped.startswith(f"{anchor} ") or stripped.startswith(f"{anchor}=") or stripped.startswith(f"#{anchor} ") or stripped.startswith(f"#{anchor}="):
								insertAt = idx + 1
					lines.insert(insertAt if insertAt is not None else end, f"{key} = {rhs}")
					foundSet.add(token)

		def tomlBool(val):
			return "true" if bool(val) else "false"

		def tomlStr(val):
			return '"' + str(val).replace("\\", "\\\\").replace('"', '\\"') + '"'

		def tomlInt(val, default=0):
			try:
				result = str(int(val))
			except Exception:
				result = str(int(default))
			return result

		def replaceKeyLine(line, key, newRhs, foundSet):
			ls = line.lstrip()
			indent = line[:len(line) - len(ls)]
			result = line
			if ls.startswith(f"{key} ") or ls.startswith(f"{key}=") or ls.startswith(f"#{key} ") or ls.startswith(f"#{key}="):
				foundSet.add(key)
				result = f"{indent}{key} = {newRhs}"
			return result

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
				line = replaceKeyLine(line, "ipv4_servers", tomlBool(config.usage.dnsMode.value != 3), found)
				line = replaceKeyLine(line, "ipv6_servers", tomlBool(config.usage.dnsMode.value != 2), found)
				line = replaceKeyLine(line, "dnscrypt_servers", tomlBool(config.usage.DNSCryptProtocol.value), found)
				line = replaceKeyLine(line, "doh_servers", tomlBool(config.usage.DNSCryptDoH.value), found)
				line = replaceKeyLine(line, "odoh_servers", tomlBool(config.usage.DNSCryptODoH.value), found)
				line = replaceKeyLine(line, "require_dnssec", tomlBool(config.usage.DNSCryptDNSSEC.value), found)
				line = replaceKeyLine(line, "require_nolog", tomlBool(config.usage.DNSCryptNoLog.value), found)
				line = replaceKeyLine(line, "require_nofilter", tomlBool(config.usage.DNSCryptNoFilter.value), found)
				line = replaceKeyLine(line, "cache", tomlBool(config.usage.DNSCryptCache.value), found)
				newLines.append(line)
				continue
			if currentSection == "monitoring_ui":
				for attr, key, val in [
					("DNSCryptUI", "enabled", tomlBool(config.usage.DNSCryptUI.value)),
					(None, "listen_address", tomlStr(f"0.0.0.0:{tomlInt(config.usage.DNSCryptPort.value, 9012)}")),
					("DNSCryptUsername", "username", tomlStr(config.usage.DNSCryptUsername.value.strip())),
					("DNSCryptPassword", "password", tomlStr(config.usage.DNSCryptPassword.value.strip())),
					("DNSCryptPrivacy", "privacy_level", tomlInt(config.usage.DNSCryptPrivacy.value, 1)),
				]:
					tmpFound = set()
					line2 = replaceKeyLine(line, key, val, tmpFound)
					if key in tmpFound:
						found.add(f"monitoring_ui.{key}")
						line = line2
			newLines.append(line)

		insertSectionKey(newLines, "monitoring_ui", "enabled", tomlBool(config.usage.DNSCryptUI.value), ["enabled"], found)
		insertSectionKey(newLines, "monitoring_ui", "listen_address", tomlStr(f"0.0.0.0:{tomlInt(config.usage.DNSCryptPort.value, 9012)}"), ["enabled", "listen_address"], found)
		insertSectionKey(newLines, "monitoring_ui", "username", tomlStr(config.usage.DNSCryptUsername.value.strip()), ["listen_address", "username"], found)
		insertSectionKey(newLines, "monitoring_ui", "password", tomlStr(config.usage.DNSCryptPassword.value.strip()), ["username", "password"], found)
		insertSectionKey(newLines, "monitoring_ui", "privacy_level", tomlInt(config.usage.DNSCryptPrivacy.value, 1), ["password", "privacy_level"], found)

		tmpPath = f"{tomlPath}.tmp"
		fileWriteLines(tmpPath, newLines)
		if exists(tmpPath):
			rename(tmpPath, tomlPath)


# ===========================================================================
# InformationNetwork – Subclass of the InformationNetwork
# ===========================================================================


class InformationNetwork(InformationNetworkOriginal):
	def __init__(self, session, adapter, conn):
		InformationNetworkOriginal.__init__(self, session)
		self.conn = conn
		self.adapter = adapter
		#self["geolocationActions"].setEnabled(False)
		#self["key_yellow"].setText("")
		self["key_green"] = StaticText(_("Refresh"))

	def displayInformation(self):
		InformationNetworkOriginal.displayInformation(self, selectedAdapter=self.adapter)


# ===========================================================================
# NetworkOverview – adapters (top list) + Wi-Fi connections of the selected
# adapter (bottom list), as two independent XmlMultiContent listboxes rather
# than a single indented tree – LAN never gets a connection row of its own.
# ===========================================================================


class NetworkOverview(Screen):
	"""Adapters on top, Wi-Fi connections of the selected adapter below. 'conn'
	comes from the connection list only while it has focus: None while an
	adapter row is current, set while a connection row is."""

	GLYPH_LAN = "\uEA5A"   # settings_ethernet
	GLYPH_WIFI = "\uE9FE"  # wifi
	GLYPH_INET = "\uEA5B"  # globe
	GLYPH_VPN = "\uE9AF"   # vpn_key

	OVERVIEW_COLOR_GOOD = gRGB(0x0000CC00).argb()  # green – connected
	OVERVIEW_COLOR_BAD = gRGB(0x00CC0000).argb()   # red   – LAN without link
	OVERVIEW_COLOR_IDLE = gRGB(0x00808080).argb()  # gray  – disabled / not associated / saved connection

	# data[0] of every row selects which <rowtemplate> renders it (see setTemplates()/
	# selectTemplate() in elistboxcontent.cpp) – it does not shift the other fields'
	# indices, so all *_INDEX_NAMES below start at 1, not 0.
	OVERVIEW_TEMPLATE_HEADER = 0
	OVERVIEW_TEMPLATE_ROW = 1

	# Position 0 is data[0], the <rowtemplate> selector (see OVERVIEW_TEMPLATE_*) –
	# reserved here (not a real field) so indexNames still covers 0..len-1
	# contiguously, which XmlMultiContent's index-name bounds check requires.
	ADAPTER_INDEX_NAMES = {
		"_rowTemplate": 0,
		"AdapterGlyph": 1,
		"AdapterName": 2,
		"AdapterType": 3,
		"StatusText": 4,
		"StatusColor": 5,
		"MAC": 6,
		"IPAddress": 7,
		"Gateway": 8,
		"Speed": 9,
		"InternetGlyph": 10,
	}
	INDEX_ADAPTER = 11

	# Position 0 is data[0], the <rowtemplate> selector (see OVERVIEW_TEMPLATE_*) –
	# reserved here (not a real field) so indexNames still covers 0..len-1
	# contiguously, which XmlMultiContent's index-name bounds check requires.
	CONNECTION_INDEX_NAMES = {
		"_rowTemplate": 0,
		"SSID": 1,
		"BSSID": 2,
		"Frequency": 3,
		"Channel": 4,
		"Encryption": 5,
		"StatusText": 6,
		"StatusColor": 7,
	}
	INDEX_CONNECTION = 8

	TEXT_SAVED_NETWORKS = _("Saved Wireless Networks")

	skin = """
	<screen name="NetworkOverview" title="Network Overview" position="center,center" size="1220,660" resolution="1280,720">
		<widget source="adapterList" render="Listbox" position="10,8" size="1200,300" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;34,Regular;24,Regular;18,enigma2icons;20" itemHeight="60" colors="#0000CC00,#00CC0000,#00808080">
				<rowtemplate>
					<text index="AdapterName" position="14,0" size="470,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="MAC" position="490,0" size="190,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="IPAddress" position="690,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Gateway" position="840,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Speed" position="990,0" size="200,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
				</rowtemplate>
				<rowtemplate>
					<text index="AdapterGlyph" position="14,7" size="46,46" font="0" horizontalAlignment="center" verticalAlignment="center" />
					<text index="AdapterName" position="74,6" size="230,26" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="AdapterType" position="74,32" size="230,22" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="InternetGlyph" position="280,20" size="20,20" font="3" horizontalAlignment="center" verticalAlignment="center" />
					<text index="StatusText" position="320,0" size="160,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="+StatusColor" foregroundColorSelected="+StatusColor" />
					<text index="MAC" position="490,0" size="190,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="IPAddress" position="690,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Gateway" position="840,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Speed" position="990,0" size="200,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
				</rowtemplate>
			</template>
		</widget>
		<widget source="networksLabel" render="Label" position="10,340" size="700,30" font="Regular;20" foregroundColor="grey" transparent="1" halign="left" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="networksList" render="Listbox" position="10,374" size="1200,160" scrollbarMode="showOnDemand">
			<template name="Default" fonts="Regular;22,Regular;18" itemHeight="40" colors="#0000CC00,#00CC0000,#00808080">
				<rowtemplate>
					<text index="SSID" position="20,0" size="280,40" font="0" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="BSSID" position="310,0" size="220,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Frequency" position="540,0" size="120,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Channel" position="670,0" size="140,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="Encryption" position="820,0" size="190,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
					<text index="StatusText" position="1020,0" size="180,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="grey" />
				</rowtemplate>
				<rowtemplate>
					<text index="SSID" position="20,0" size="280,40" font="0" horizontalAlignment="left" verticalAlignment="center" />
					<text index="BSSID" position="310,0" size="220,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Frequency" position="540,0" size="120,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Channel" position="670,0" size="140,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Encryption" position="820,0" size="190,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="StatusText" position="1020,0" size="180,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="+StatusColor" foregroundColorSelected="+StatusColor" />
				</rowtemplate>
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
		<widget source="key_menu" render="Label" position="e-300,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-200,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_info" render="Label" position="e-100,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>
	"""

	def __init__(self, session):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Overview"))
		self["networksLabel"] = StaticText("")  # shown via ConditionalShowHide once updateConnections() picks a WLAN adapter
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText("")
		self["key_yellow"] = StaticText("")
		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))
		self["adapterList"] = List([], indexNames=self.ADAPTER_INDEX_NAMES)
		self["networksList"] = List([], indexNames=self.CONNECTION_INDEX_NAMES)
		self.currentList = "adapterList"  # "adapterList" | "networksList" – which list up/down/OK/green/etc. act on
		self["adapterList"].onSelectionChanged.append(self.updateConnections)
		self["networksList"].onSelectionChanged.append(self.updateKeyGreen)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions", "MenuActions", "InfoActions", "NavigationActions"], {
			"ok": (self.keyOK, _("Open settings for the selected item")),
			"cancel": (self.close, _("Close network overview")),
			"close": (self.keyCloseRecursive, _("Close the screen and exit all menus")),
			"red": (self.close, _("Close network overview")),
			"green": (self.keyGreen, _("Activate/Deactivate adapter or Wi-Fi connection")),
			"yellow": (self.keyYellow, _("Add a new WiFi connection")),
			"info": (self.keyInfo, _("Show network connection info")),
			"menu": (self.keyMenu, _("Open context menu for the selected item")),
			"left": (self.keyLeft, _("Jump to the adapter list")),
			"right": (self.keyRight, _("Jump to the Wi-Fi connection list")),
			"up": (self.keyUp, _("Move up")),
			"down": (self.keyDown, _("Move down")),
		}, prio=0, description=_("Network Overview Actions"))
		self.onLayoutFinish.append(self.layoutFinished)
		self.internetChecked = False
		self.onShown.append(self.checkInternet)
		networkManager.onAdaptersChanged.append(self.refreshAdapters)

		def doClose():
			networkManager.onAdaptersChanged.remove(self.refreshAdapters)
		self.onClose.append(doClose)

	def refreshAdapters(self):
		if "adapterList" in self:
			oldGateways = {x[self.INDEX_ADAPTER].name: x[self.INDEX_ADAPTER].netInfo.gateway for x in self["adapterList"].getList() if x[self.INDEX_ADAPTER] is not None}
			newGateways = {name: adapter.netInfo.gateway for name, adapter in networkManager.adapters.items()}
			if oldGateways != newGateways:
				self.internetChecked = False
				self.checkInternet()
				return
			oldRows = self["adapterList"].getList()
			newRows = self.buildAdapterRows()
			if len(oldRows) != len(newRows):
				# Structural change (adapter/VPN added or removed) – row indices shift, so
				# a per-row diff can't be trusted. Fall back to the full rebuild.
				adapterIndex = self["adapterList"].getCurrentIndex() if self["adapterList"].count() else -1
				networkIndex = self["networksList"].getCurrentIndex() if self["networksList"].count() else -1
				self.buildAdapters()
				try:
					if adapterIndex != -1:
						self["adapterList"].setCurrentIndex(adapterIndex)
				except Exception:
					pass
				if self.currentList == "networksList":
					try:
						if networkIndex != -1:
							self["networksList"].setCurrentIndex(networkIndex)
					except Exception:
						pass
			else:
				for index, (oldRow, newRow) in enumerate(zip(oldRows, newRows)):
					if oldRow != newRow:
						self["adapterList"].updateEntry(index, newRow)
				self.updateConnections(preserveSelection=True)

	def layoutFinished(self):
		self["adapterList"].enableAutoNavigation(False)
		self["adapterList"].setLockFirstRow(True)
		self["networksList"].enableAutoNavigation(False)
		self["networksList"].setLockFirstRow(True)
		self.markHeaderNotSelectable("adapterList")
		self.markHeaderNotSelectable("networksList")
		self.buildAdapters()
		self.setListFocus("adapterList")

	def setListFocus(self, sourceName: str):
		self.currentList = sourceName
		self["adapterList"].selectionEnabled(sourceName == "adapterList")
		self["networksList"].selectionEnabled(sourceName == "networksList")
		self.updateKeyGreen()

	def checkInternet(self):
		def checkInternetCallback():
			self.internetChecked = True
			self.refreshAdapters()

		if not self.internetChecked:
			networkManager.checkConnectionInternet(callback=checkInternetCallback)

	def keyLeft(self):
		if self.currentList == "networksList":
			self.setListFocus("adapterList")

	def keyRight(self):
		if self.currentList == "adapterList" and self["networksList"].count():
			self.setListFocus("networksList")

	def keyUp(self):
		self[self.currentList].goLineUp()

	def keyDown(self):
		self[self.currentList].goLineDown()

	def currentAdapter(self) -> Adapter | None:
		entry = self["adapterList"].getCurrent()
		return entry[self.INDEX_ADAPTER] if entry is not None else None

	def currentConnection(self) -> Connection | None:
		if self.currentList == "networksList":
			entry = self["networksList"].getCurrent()
			return entry[self.INDEX_CONNECTION] if entry is not None else None
		else:
			return None

	def overviewColors(self, sourceName: str) -> tuple:
		"""Reads the <template>'s 'colors' attribute (good,bad,idle – same order
		as OVERVIEW_COLOR_GOOD/BAD/IDLE), falling back to those class defaults
		if the skin doesn't set one. additionalTemplateAttributes is populated
		by XmlMultiContent from any template attribute it doesn't itself know
		about."""
		colors = self[sourceName].additionalTemplateAttributes.get("colors")
		if not colors:
			return self.OVERVIEW_COLOR_GOOD, self.OVERVIEW_COLOR_BAD, self.OVERVIEW_COLOR_IDLE
		parts = [parseColor(part.strip()).argb() for part in colors.split(",")]
		if len(parts) != 3:
			print(f"[NetworkOverview] Error: template 'colors' must have exactly 3 entries (good,bad,idle), got {len(parts)}!")
			return self.OVERVIEW_COLOR_GOOD, self.OVERVIEW_COLOR_BAD, self.OVERVIEW_COLOR_IDLE
		return tuple(parts)

	def markHeaderNotSelectable(self, sourceName: str):
		def isOverviewRowSelectable(kind, *_):
			return kind != self.OVERVIEW_TEMPLATE_HEADER

		# .master.content (the eListboxPythonMultiContent) is only created once
		# setList() has run at least once on this source, so this must run
		# right after – not from onLayoutFinish, which would be too late for
		# the very first buildAdapters() -> updateConnections() -> currentAdapter().
		self[sourceName].master.content.setSelectableFunc(isOverviewRowSelectable)

	def buildAdapterRows(self) -> list[tuple]:
		good, bad, idle = self.overviewColors("adapterList")

		def buildOverviewAdapterHeaderRow() -> tuple:
			"""First row of the adapter listbox, rendered via <rowtemplate> #0 – the
			"Interfaces" section title (via AdapterName) plus column titles for the
			Mac/IpAddress/Gateway/Speed columns, not selectable (see isOverviewRowSelectable)."""
			return (
				self.OVERVIEW_TEMPLATE_HEADER,
				None,                # AdapterGlyph
				_("Adapter"),        # AdapterName
				None,                # AdapterType
				_("Status"),         # StatusText
				None,                # StatusColor
				_("MAC Address"),    # MAC
				_("IP Address"),     # IPAddress
				_("Gateway"),        # Gateway
				_("Speed"),          # Speed
				None,                # InternetGlyph
				None,                # -> INDEX_ADAPTER
			)

		def buildOverviewAdapterRow(adapter: Adapter) -> tuple:
			"""Row for the adapter listbox. Same template for LAN and WLAN – no per-type extra line."""
			net = adapter.netInfo
			kind = _("Wireless Adapter") if adapter.isWlan else _("Ethernet Adapter")
			if not adapter.adapterEnabled:
				statusText, statusColor = _("Disabled"), idle
			elif net.link:
				statusText, statusColor = _("Connected"), good
			elif adapter.isWlan:
				statusText, statusColor = _("Not Connected"), idle
			else:
				statusText, statusColor = _("Cable Unplugged"), bad
			if adapter.isWlan:
				speed = f"{net.bitrateBps // 1000000} Mbit/s" if net.bitrateBps else "—"
			else:
				speed = formatNetworkSpeed(net.speed) if net.speed > 0 else "—"

			internet = adapter.adapterEnabled and adapter.hasInternet
			inetGlyph = self.GLYPH_INET if internet else ""
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				self.GLYPH_WIFI if adapter.isWlan else self.GLYPH_LAN,  # AdapterGlyph
				adapter.name,                                                 # AdapterName
				kind,                                                         # AdapterKind
				statusText,                                                   # StatusText
				statusColor,                                                  # StatusColor
				adapter.mac.upper(),                                          # Mac
				_ip4Str(net.ip) or "—",                                  # IpAddress
				_ip4Str(net.gateway) or "—",                             # Gateway
				speed,                                                        # Speed
				inetGlyph,                                                    # InetGlyph
				adapter,                                                      # -> INDEX_ADAPTER
			)

		def buildOverviewVpnRow(vpn: VpnInfo) -> tuple:
			"""Row for a VPN interface (e.g. wg0) – display only, never configurable
			here (ADAPTER_BLACKLIST'd, no /etc/network/interfaces stanza). INDEX_ADAPTER
			is None so OK/green/menu/info all no-op via the existing is-None guards."""
			if vpn.up and vpn.link:
				statusText, statusColor = _("Connected"), good
			elif vpn.up:
				statusText, statusColor = _("Up"), idle
			else:
				statusText, statusColor = _("Down"), bad
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				self.GLYPH_VPN,           # AdapterGlyph
				vpn.name,                 # AdapterName
				_("VPN"),                 # AdapterKind
				statusText,               # StatusText
				statusColor,              # StatusColor
				vpn.mac.upper(),          # Mac
				_ip4Str(vpn.ip) or "—",   # IpAddress
				"—",                      # Gateway
				"—",                      # Speed
				"",                       # InetGlyph
				None,                     # -> INDEX_ADAPTER
			)

		rows = [buildOverviewAdapterRow(networkManager.adapters[iface]) for iface in sorted(networkManager.adapters.keys())]
		rows += [buildOverviewVpnRow(networkManager.vpnInterfaces[iface]) for iface in sorted(networkManager.vpnInterfaces.keys())]
		if rows:
			rows.insert(0, buildOverviewAdapterHeaderRow())
		return rows

	def buildAdapters(self):
		rows = self.buildAdapterRows()
		hasRows = bool(rows)
		self["adapterList"].setList(rows)
		if hasRows:
			self["adapterList"].index = 1  # setList() resets the cursor to 0 (the header) – skip past it
		self.updateConnections()
		text = _("Add Wi-Fi") if any(x.isWlan for x in networkManager.adapters.values()) else ""
		self["key_yellow"].setText(text)
		self["actions"].setEnabledAction("yellow", text != "")

	def overviewWlanConnections(self, adapter: Adapter) -> list[Connection]:
		return [conn for conn in networkManager.getConnections(adapter.name) if conn.wlan and conn.wlan.ssid]

	def buildConnectionRows(self, adapter: Adapter | None) -> tuple[list[Connection], list[tuple]]:
		good, _bad, idle = self.overviewColors("networksList")

		def buildOverviewConnectionHeaderRow() -> tuple:
			"""First row of the connection listbox, rendered via <rowtemplate> #0 – column
			titles, not selectable (see isOverviewRowSelectable). All texts are a
			static grey in the skin, so unlike the data row's StatusText this one
			doesn't need a real StatusColor."""
			return (
				self.OVERVIEW_TEMPLATE_HEADER,
				_("SSID"),       # Ssid
				_("BSSID"),      # Bssid
				_("Frequency"),  # Frequency
				_("Channel"),    # Channel
				_("Encryption"),  # Encryption
				_("Status"),     # StatusText
				None,            # StatusColor
				None,            # -> INDEX_CONNECTION
			)

		def buildOverviewConnectionRow(conn: Connection, adapter: Adapter) -> tuple:
			"""Row for the Wi-Fi connection listbox. BSSID/frequency/channel are only known
			while this connection is the one currently associated – wpa_supplicant.conf
			doesn't persist them for connections that aren't connected right now."""
			ssid = conn.wlan.ssid
			net = adapter.netInfo
			isLive = net.link and net.ssid == ssid
			if isLive:
				statusText, statusColor = _("Connected"), good
			elif conn.enabled:
				# Configured as the active connection, just not associated right now
				# (e.g. the adapter itself is off) – distinct from a genuinely
				# disabled connection, which toggleAdapter() must never touch.
				statusText, statusColor = _("Not Connected"), idle
			else:
				statusText, statusColor = _("Disabled"), idle
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				ssid,                                                                                     # Ssid
				net.bssid.upper() if isLive and net.bssid else "—",                                 # Bssid
				f"{net.freqMhz / 1000:.2f} GHz" if isLive and net.freqMhz else "—",                  # Frequency
				str(net.channel) if isLive and net.channel else "—",                                 # Channel
				encryptionLabels.get(conn.wlan.encryption, lambda: "")(),                                  # Encryption
				statusText,                                                                               # StatusText
				statusColor,                                                                              # StatusColor
				conn,                                                                                     # -> INDEX_CONNECTION
			)

		if adapter is None or not adapter.isWlan:
			return [], []
		connections = self.overviewWlanConnections(adapter)
		rows = [buildOverviewConnectionRow(conn, adapter) for conn in connections]
		if rows:
			rows.insert(0, buildOverviewConnectionHeaderRow())
		return connections, rows

	def updateConnections(self, preserveSelection: bool = False):
		"""Rebuilds the connection list for the currently selected adapter. By default
		(adapter selection actually changed) this resets the cursor to the first row.
		Called from refreshAdapters()'s periodic poll with preserveSelection=True instead,
		which diffs against the current rows and only touches changed ones via
		updateEntry() – so the user's cursor in networksList isn't reset every poll."""
		adapter = self.currentAdapter()
		connections, rows = self.buildConnectionRows(adapter)
		if adapter is None or not adapter.isWlan:
			self["networksList"].setList([])
			self["networksLabel"].setText("")  # hidden via ConditionalShowHide – only relevant for a WLAN adapter
		else:
			if preserveSelection and len(rows) == self["networksList"].count():
				oldRows = self["networksList"].getList()
				for index, (oldRow, newRow) in enumerate(zip(oldRows, rows)):
					if oldRow != newRow:
						self["networksList"].updateEntry(index, newRow)
			else:
				hasRows = bool(rows)
				self["networksList"].setList(rows)
				if hasRows:
					self["networksList"].index = 1  # setList() resets the cursor to 0 (the header) – skip past it
			self["networksLabel"].setText(f"{self.TEXT_SAVED_NETWORKS} · {adapter.name} · {len(connections)}")
		if self.currentList == "networksList" and not self["networksList"].count():
			self.setListFocus("adapterList")
		else:
			self.updateKeyGreen()

	def keyOK(self):
		adapter = self.currentAdapter()
		if adapter is None:
			return
		conn = self.currentConnection()
		if conn is None:
			# Adapter row (LAN, or WLAN with no/unselected connection row) –
			# DHCP/IP/DNS/WOL/WWOL/link speed all live on the adapter now.
			self.openAdapterSetup(adapter)
		else:
			self.openSetup(conn, adapter)

	def keyCloseRecursive(self):
		self.close(True)

	def keyGreen(self):
		adapter = self.currentAdapter()
		if adapter:
			conn = self.currentConnection()
			if conn is None or not adapter.isWlan:
				self.toggleAdapter(adapter)
			else:
				self._activateWlanConnection(conn, adapter)

	def keyInfo(self):
		adapter = self.currentAdapter()
		if adapter:
			self.session.open(InformationNetwork, adapter, self.currentConnection())

	def updateKeyGreen(self):
		adapter = self.currentAdapter()
		if adapter is None:
			text = ""
		else:
			conn = self.currentConnection()
			if conn is None or not adapter.isWlan:
				text = _("Deactivate") if adapter.adapterEnabled else _("Activate")
			else:
				connections = self.overviewWlanConnections(adapter)
				text = _("Activate") if len(connections) > 1 and not conn.enabled else ""
		self["key_green"].setText(text)
		self["actions"].setEnabledAction("green", text != "")

	def keyMenu(self):
		adapter = self.currentAdapter()
		if adapter:
			self.showContextMenu(self.currentConnection(), adapter)

	def keyYellow(self):
		if networkManager.adapters:
			wlanAdapters = [x for x in networkManager.adapters.values() if x.isWlan]
			if wlanAdapters:
				adapter = self.currentAdapter()
				preselected = adapter if adapter is not None and adapter.isWlan else None
				NetworkWiFiAddFlow.start(self.session, adapter=preselected, callback=lambda *_: self.buildAdapters())

	def connLabel(self, conn: Connection, adapter: Adapter) -> str:
		if conn.isWlan and conn.wlan and conn.wlan.ssid:
			result = f"{conn.adapter}  │  {conn.wlan.ssid}  [{_ENC_SHORT.get(conn.wlan.encryption, conn.wlan.encryption)}]"
		else:
			mode = "DHCP" if conn.dhcp else conn.ipStr()
			result = f"{conn.adapter}  │  {mode}"
		return result

	def contextCb(self, choice, conn: Connection | None, adapter: Adapter):
		def confirmDelete(conn: Connection, adapter: Adapter):
			def doDelete(confirmed: bool, conn: Connection, adapter: Adapter):
				if confirmed:
					if conn.isWlan and conn.wlan:
						networkManager.removeConnection(adapter.name, conn.wlan.ssid)
					else:
						networkManager.connections[adapter.name] = [x for x in networkManager.getConnections(adapter.name) if x is not conn]
					networkManager.save()
					if conn.isWlan:
						self.buildAdapters()
					else:
						applyAdapterChange(adapter.name, CHANGE_GENERAL, self.buildAdapters)

			self.session.openWithCallback(lambda confirmed: doDelete(confirmed, conn, adapter), MessageBox, _("Delete network connection '%s'?") % self.connLabel(conn, adapter), type=MessageBox.TYPE_YESNO)

		def restartAdapter(adapter: Adapter):
			Processing.instance.setDescription(_("Please wait, restarting adapter..."))
			Processing.instance.showProgress(endless=True)

			def done():
				Processing.instance.hideProgress()
				self.buildAdapters()
			networkManager.restartNetwork(iface=adapter.name, callback=done)

		def openWlanScan(iface: str):
			def wlanScanDone(result: ScanResult | None, adapter: Adapter):
					if result:
						self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, scanResultToConnection(result, adapter.name), adapter)
			adapter = networkManager.getAdapter(iface)
			if adapter is not None and adapter.isWlan:
				self.session.openWithCallback(lambda result: wlanScanDone(result, adapter), NetworkWiFiScanScreen, adapter)

		def openWlanManual(adapter: Adapter):
			conn = Connection(adapter=adapter.name, name=_("New Wi-Fi"), dhcp=True, enabled=False, wlan=WiFiConfig())
			self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, conn, adapter)

		if choice:
			action = choice[1]
			if action == "setup":
				self.openSetup(conn, adapter)
			elif action == "adapterSetup":
				self.openAdapterSetup(adapter)
			elif action == "toggle":
				self.toggleConnection(conn, adapter)
			elif action == "toggleAdapter":
				self.toggleAdapter(adapter)
			elif action == "test":
				self.session.open(NetworkTest, adapter.name)
			elif action == "delete":
				confirmDelete(conn, adapter)
			elif action == "restartAdapter":
				restartAdapter(adapter)
			elif action == "scan":
				openWlanScan(adapter.name)
			elif action == "addManual":
				openWlanManual(adapter)

	def showContextMenu(self, conn: Connection | None, adapter: Adapter):
		if conn is None:
			menu = [
				(_("Adapter settings"), "adapterSetup"),
				(_("Disable adapter") if adapter.adapterEnabled else _("Enable adapter"), "toggleAdapter"),
				(_("Network test"), "test"),
				(_("Restart adapter"), "restartAdapter"),
			]
			title = adapter.name
		else:
			menu = [
				(_("Settings"), "setup"),
				(_("Disable network") if conn.enabled else _("Enable network"), "toggle"),
			]
			menu.append((_("Delete network"), "delete"))
			title = _("Network: %s") % self.connLabel(conn, adapter)
		if adapter.isWlan:
			menu.append((_("Scan for Wi-Fi networks"), "scan"))
			menu.append((_("Add Wi-Fi manually"), "addManual"))
		self.session.openWithCallback(lambda choice: self.contextCb(choice, conn, adapter), ChoiceBox, windowTitle=title, choiceList=menu)

	def setupClosed(self, *result):
		if len(result) == 1 and isinstance(result[0], tuple):
			recursive, saved = result[0][0], result[0][1]
		else:
			recursive = bool(result[0]) if result else False
			saved = False
		if saved:
			self.buildAdapters()
		elif recursive:
			self.keyCloseRecursive()

	def openSetup(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, conn, adapter)

	def openAdapterSetup(self, adapter: Adapter):
		self.session.openWithCallback(self.setupClosed, NetworkAdapterSetup, adapter)

	def toggleAdapter(self, adapter: Adapter):
		adapter.adapterEnabled = not adapter.adapterEnabled
		if not adapter.isWlan:
			for conn in networkManager.getConnections(adapter.name):
				conn.enabled = adapter.adapterEnabled
		networkManager.save()

		def done():
			self.refreshAdapters()
			self.session.showInfo(_("Network adapter enabled") if adapter.adapterEnabled else _("Network adapter disabled"))
		applyAdapterChange(adapter.name, CHANGE_ADAPTER_ENABLED, done)

	def toggleConnection(self, conn: Connection, adapter: Adapter):
		if adapter.isWlan:
			conns = networkManager.getConnections(adapter.name)
			if conn.enabled:
				for other in conns:
					other.enabled = False
			else:
				for other in conns:
					other.enabled = (other is conn)
			adapter.adapterEnabled = any(x.enabled for x in conns)
		else:
			conn.enabled = not conn.enabled
			adapter.adapterEnabled = conn.enabled
		networkManager.save()

		def done():
			self.refreshAdapters()
			if adapter.isWlan and conn.enabled:
				self.session.openWithCallback(lambda *_: self.refreshAdapters(), NetworkWiFiActivator, conn, adapter)
			else:
				self.session.showInfo(_("Network connection enabled") if conn.enabled else _("Network connection disabled"))
		if adapter.isWlan:
			done()
		else:
			applyAdapterChange(adapter.name, CHANGE_ADAPTER_ENABLED, done)

	# Green button on a WLAN connection row: switch to this connection (never a
	# toggle – deactivating the active connection happens via the context menu).
	def _activateWlanConnection(self, conn: Connection, adapter: Adapter):
		for other in networkManager.getConnections(adapter.name):
			other.enabled = (other is conn)
		adapter.adapterEnabled = True
		networkManager.save()
		self.refreshAdapters()
		self.session.openWithCallback(lambda *_: self.refreshAdapters(), NetworkWiFiActivator, conn, adapter)


# ===========================================================================
# NetworkAdapterSetup – per-adapter settings (DHCP/IP/DNS/WOL/WWOL/link speed),
# written to /etc/network/interfaces. Same screen for LAN and WLAN adapters;
# operates on the adapter's base Connection (networkManager.getBaseConnection).
# ===========================================================================

class NetworkAdapterSetup(Setup):
	"""Setup screen for one Adapter's IP config, Wake-on-LAN/WiFi and link speed."""

	def __init__(self, session, adapter: Adapter):
		self.adapter = adapter
		self.conn = networkManager.getBaseConnection(adapter.name)
		self.buildConfigObjects()
		self.hasWakeOnLan = adapter.name == "eth0" and BoxInfo.getItem("wol") and BoxInfo.getItem("WakeOnLAN")
		Setup.__init__(self, session=session, setup="NetworkAdapter")
		self.setTitle(_("Network Adapter Settings – %s") % adapter.name)
		self["key_info"] = StaticText(_("Info"))
		self["blueActions"] = HelpableActionMap(self, ["InfoActions"], {
			"info": (self.keyShowInfo, _("Show network connection info"))
		}, prio=0)

	def keyShowInfo(self):
		self.session.open(InformationNetwork, self.adapter, self.conn)

	def buildConfigObjects(self):
		adapter = self.adapter
		conn = self.conn

		self.cfgEnabled = NoSave(ConfigYesNo(default=adapter.adapterEnabled))
		self.cfgIpMode = NoSave(ConfigSelection(
			default=conn.ipMode,
			choices=[
				(0, _("IPv4 only")),
				(1, _("IPv6 only")),
				(2, _("IPv4 and IPv6")),
			]
		))
		self.cfgDhcp = NoSave(ConfigYesNo(default=conn.dhcp))
		self.cfgIp = NoSave(ConfigIP(default=conn.ip))
		self.cfgNetmask = NoSave(ConfigIP(default=conn.netmask))
		self.cfgGateway = NoSave(ConfigIP(default=conn.gateway))

		# Route metric (only while the e2-route-metric daemon config exists
		# and more than one adapter is present – that's the only situation
		# where more than one gateway, and thus a metric, is relevant)
		currentMetric = adapter.metric
		self.hasMetric = currentMetric is not None and len(networkManager.adapters) > 1
		self.cfgMetric = NoSave(ConfigSelection(choices=networkManager.ROUTE_METRIC_CHOICES, default=currentMetric if currentMetric is not None else (600 if adapter.isWlan else 100)))

		# Per-adapter DNS (inline, replaces separate DNS setup screen)
		hasOwn = bool(conn.dnsServers)
		self.cfgDnsOverride = NoSave(ConfigYesNo(default=hasOwn))
		dnsV4 = [x for x in conn.dnsServers if isinstance(x, list)]
		dnsV6 = [x for x in conn.dnsServers if isinstance(x, str)]
		self.cfgDns1v4 = NoSave(ConfigIP(default=dnsV4[0] if len(dnsV4) > 0 else [0, 0, 0, 0]))
		self.cfgDns2v4 = NoSave(ConfigIP(default=dnsV4[1] if len(dnsV4) > 1 else [0, 0, 0, 0]))
		self.cfgDns1v6 = NoSave(ConfigText(default=dnsV6[0] if len(dnsV6) > 0 else "", fixed_size=False))
		self.cfgDns2v6 = NoSave(ConfigText(default=dnsV6[1] if len(dnsV6) > 1 else "", fixed_size=False))

		# Forced link speed (LAN adapters only)
		if not adapter.isWlan:
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
		self.cfgWakeOnWiFi = NoSave(ConfigYesNo(default=conn.wakeOnWiFi and adapter.adapterEnabled))
		self.cfgWowOnly = NoSave(ConfigYesNo(default=conn.wakeOnWiFi and not adapter.adapterEnabled))

	def keySave(self):
		adapter = self.adapter
		conn = self.conn

		# Snapshot the fields that matter for connectivity before we overwrite
		# them, so we know afterwards whether this needs a full restart
		# (settings changed) or just ifup/ifdown (enable state only).
		wasEnabled = adapter.adapterEnabled
		wasGeneral = (conn.dhcp, conn.ipMode, list(conn.ip), list(conn.netmask), list(conn.gateway), list(conn.dnsServers))
		wasLinkSpeed = networkManager.getLinkSpeed(adapter.name)
		wasMetric = adapter.metric if self.hasMetric else None

		adapter.adapterEnabled = self.cfgEnabled.value
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

		# Apply Wake-on-WiFi (Broadcom)
		if adapter.isWlan and adapter.canWakeOnWiFi:
			conn.wakeOnWiFi = self.cfgWakeOnWiFi.value if adapter.adapterEnabled else self.cfgWowOnly.value
			cmds = networkManager.setWakeOnWiFiCommands(adapter.name, conn.wakeOnWiFi)
			if cmds:
				Console().eBatch(cmds, lambda result: None, debug=False)

		# Apply forced link speed (LAN adapters only)
		if not adapter.isWlan:
			networkManager.setLinkSpeed(adapter.name, self.cfgLinkSpeed.value)

		# Apply route metric (e2-route-metric). Was built into the config list
		# (buildConfigObjects()) but never actually written out on save.
		if self.hasMetric and self.cfgMetric.value != wasMetric:
			if adapter.isWlan:
				networkManager.setRouteMetrics(wlanMetric=self.cfgMetric.value)
			else:
				networkManager.setRouteMetrics(lanMetric=self.cfgMetric.value)

		networkManager.save()

		# Metric alone (self.cfgMetric, applied above) deliberately does NOT
		# factor into `change` – it's just a route preference for e2-route-metric
		# to pick up, not something that needs the adapter itself ifup/ifdown'd
		# or restarted.
		nowGeneral = (conn.dhcp, conn.ipMode, list(conn.ip), list(conn.netmask), list(conn.gateway), list(conn.dnsServers))
		if nowGeneral != wasGeneral or self.cfgLinkSpeed.value != wasLinkSpeed:
			change = CHANGE_GENERAL
		elif adapter.adapterEnabled != wasEnabled:
			change = CHANGE_ADAPTER_ENABLED
		else:
			change = CHANGE_NONE
		applyAdapterChange(adapter.name, change, lambda: self.close((False, True)))

		if self.hasWakeOnLan:
			config.network.wol.save()


# ===========================================================================
# NetworkConnectionWiFi – one Wi-Fi profile (SSID). Only what's actually
# written to wpa_supplicant.conf: SSID, hidden, encryption, key, priority,
# enabled (disabled=). DHCP/IP/DNS/WOL/WWOL live on NetworkAdapterSetup.
# ===========================================================================

class NetworkConnectionWiFi(Setup):
	"""Setup screen for one Wi-Fi profile (SSID)."""

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
		self.conn = conn
		self.adapter = adapter
		self.buildConfigObjects()
		Setup.__init__(self, session=session, setup="NetworkConnectionWiFi")
		self.setTitle(_("Wi-Fi Connection Settings – %s") % conn.adapter)
		self["key_info"] = StaticText(_("Info"))
		self["blueActions"] = HelpableActionMap(self, ["InfoActions"], {
			"info": (self.keyShowInfo, _("Show network connection info"))
		}, prio=0)

	def keyShowInfo(self):
		self.session.open(InformationNetwork, self.adapter, self.conn)

	def buildConfigObjects(self):
		conn = self.conn
		adapter = self.adapter
		self.cfgEnabled = NoSave(ConfigYesNo(default=conn.enabled))

		wlanConns = [x for x in networkManager.getConnections(adapter.name) if x.isWlan and x.wlan and x.wlan.ssid]
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

		encryptionChoices = [
			(encNone, _("None")),
			(encWep, "WEP"),
			(encWpa, "WPA"),
			(encWpa2, "WPA2"),
		]
		# WPA3/SAE disabled for now – the Broadcom "wl" driver (brcm-wl) can't do it.
		# if BoxInfo.getItem("wpa3") or (conn.wlan and conn.wlan.encryption == encWpa3):
		# 	encryptionChoices.append((encWpa3, "WPA3"))

		wlan = conn.wlan
		self.cfgSsid = NoSave(ConfigText(default=wlan.ssid, fixed_size=False))
		self.cfgHidden = NoSave(ConfigYesNo(default=wlan.hidden))
		self.cfgEncryption = NoSave(ConfigSelection(choices=encryptionChoices, default=wlan.encryption))
		self.cfgKey = NoSave(ConfigPassword(default=wlan.key, fixed_size=False))

	def keySave(self):
		conn = self.conn
		adapter = self.adapter

		conn.enabled = self.cfgEnabled.value
		if self._hasMultiplePriorities:
			chosenRank = self.cfgPriority.value
			others = [x for x in self._wlanConnsSorted if x is not conn]
			newOrder = others[:chosenRank - 1] + [conn] + others[chosenRank - 1:]
			for idx, wlanConn in enumerate(newOrder):
				wlanConn.priority = (len(newOrder) - idx) * 10
		else:
			conn.priority = int(self.cfgPriority.value)

		wlan = conn.wlan
		wlan.ssid = self.cfgSsid.value.strip()
		wlan.hidden = self.cfgHidden.value
		wlan.encryption = self.cfgEncryption.value
		if wlan.encryption != encNone:
			wlan.key = self.cfgKey.value

		conns = networkManager.getConnections(adapter.name)
		if not any(x is conn for x in conns):
			conns.append(conn)
		wasEnabled = adapter.adapterEnabled
		if conn.enabled:
			adapter.adapterEnabled = True
		# Only wpa_supplicant.conf, never /etc/network/interfaces – saving one
		# SSID profile must not trigger an adapter-level ifup/ifdown/restart.
		networkManager.saveWpaSupplicant(adapter.name)
		if not wasEnabled and adapter.adapterEnabled:
			# The adapter itself was off before this save – its stanza in
			# interfaces is still fully commented out (or missing the pre-up/
			# post-down lines entirely). Write it now so the connection survives
			# a reboot/restart, not just the live activation below. Must happen
			# here, before wasEnabled's only reader (NetworkWiFiActivator) sees
			# adapter.adapterEnabled already flipped to True.
			networkManager.save()
		if conn.enabled:
			self.session.openWithCallback(self.wifiConnectionVerified, NetworkWiFiActivator, conn, adapter)
		else:
			self.close((False, True))

	def wifiConnectionVerified(self, ip=""):
		# NetworkWiFiActivator closes with the IP it found, or "" if the
		# connection could not be verified (wrong password, AP out of range, ...).
		if ip:
			self.close((False, True, ip))
		else:
			self.session.openWithCallback(self.wifiRetryChoice, MessageBox, _("Could not verify the Wi-Fi connection.\n\nDo you want to change the settings again?"), type=MessageBox.TYPE_YESNO)

	def wifiRetryChoice(self, retry):
		if not retry:
			self.close((False, True, ""))


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


def scanResultToConnection(scanResult: ScanResult, iface: str) -> Connection:
	# enabled=True: the user is actively picking this network from the scan to
	# use it now. NetworkConnectionWiFi's "Enabled" field defaults to this
	# value, so a plain scan -> enter password -> Save (without touching that
	# field) used to save a *disabled* profile – save()'s interfaces-file
	# writer only emits the wpa_supplicant pre-up lines for an enabled
	# connection, so wpa_supplicant never started and Wi-Fi stayed dead.
	return Connection(adapter=iface, name=scanResult.ssid, dhcp=True, enabled=True, priority=0, wlan=WiFiConfig(ssid=scanResult.ssid, encryption=scanResult.encryption))


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
		self.adapterObj = adapter
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
		def finishScan(results, parser):
			self.scanning = False
			if isinstance(results, bytes):
				results = results.decode("UTF-8", errors="replace")
			for accessPoint in parser(results or ""):
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

		def scanViaIwlist(results=None, retVal=0, extraArgs=None):
			self.console.ePopen(("/sbin/iwlist", "/sbin/iwlist", self.adapter, "scanning"), callback=lambda r, rv, ea=None: finishScan(r, self.parseIwlist))

		def scanViaWpaCli():
			# wpa_supplicant already owns the radio for this iface (it's associated
			# to a network) – a concurrent "iwlist scanning" ioctl typically fails
			# with "Device or resource busy" on nl80211 drivers in that state, so
			# route the scan through wpa_supplicant's own control interface instead.
			def scanResultsCallback(results, retVal, extraArgs=None):
				finishScan(results, self.parseWpaCliScanResults)

			def triggerScanCallback(results=None, retVal=0, extraArgs=None):
				self.scanTimer = eTimer()
				self.scanTimer.callback.append(lambda: self.console.ePopen((wpaCliBin, wpaCliBin, "-i", self.adapter, "scan_results"), callback=scanResultsCallback))
				self.scanTimer.start(3000, True)

			self.console.ePopen((wpaCliBin, wpaCliBin, "-i", self.adapter, "scan"), callback=triggerScanCallback)

		def ifUpCallback(results=None, retVal=0, extraArgs=None):
			if networkManager.wpaSupplicantRunning(self.adapter):
				scanViaWpaCli()
			elif self.adapterObj.isBroadcomWl:
				self.console.ePopen(("/usr/bin/wl", "/usr/bin/wl", "up"), callback=scanViaIwlist)
			else:
				scanViaIwlist()

		if not self.scanning:
			self.scanning = True
			self["description"].setText(_("Scanning…"))
			if self.adapterObj.netInfo.up:
				ifUpCallback()
			else:
				self.console.ePopen(("/sbin/ifconfig", "/sbin/ifconfig", self.adapter, "up"), callback=ifUpCallback)

	def parseIwlist(self, raw: str) -> list[ScanResult]:
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
		# reIeWpa3 = re.compile(r"IE:.*SAE|IE:.*WPA3", re.IGNORECASE)  # WPA3/SAE disabled for now

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
			# WPA3/SAE detection disabled for now – the Broadcom "wl" driver (brcm-wl) can't do it.
			if reIeWpa2.search(line):
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

	@staticmethod
	def channelFromFreq(freqMhz: int) -> int:
		if freqMhz == 2484:
			return 14
		if 2412 <= freqMhz <= 2472:
			return (freqMhz - 2407) // 5
		if 5000 <= freqMhz <= 5900:
			return (freqMhz - 5000) // 5
		return 0

	# "wpa_cli scan_results" output: one tab-separated line per AP –
	# "bssid / frequency / signal level / flags / ssid" (no quality/percent,
	# unlike iwlist – signalDbm is converted to a percentage below).
	def parseWpaCliScanResults(self, raw: str) -> list[ScanResult]:
		results: list[ScanResult] = []
		reBssid = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
		for line in raw.splitlines():
			fields = line.strip().split("\t")
			if len(fields) < 5 or not reBssid.match(fields[0]):
				continue
			bssid, freqStr, signalStr, flags, ssid = fields[0], fields[1], fields[2], fields[3], fields[4]
			if not ssid:
				continue
			try:
				freqMhz = int(freqStr)
				signalDbm = int(signalStr)
			except ValueError:
				continue
			if "WPA2" in flags or "RSN" in flags:
				encryption = encWpa2
			elif "WPA" in flags:
				encryption = encWpa
			elif "WEP" in flags:
				encryption = encWep
			else:
				encryption = encNone
			results.append(ScanResult(
				ssid=ssid,
				bssid=bssid,
				frequency=f"{freqMhz / 1000:.3f} GHz",
				channel=self.channelFromFreq(freqMhz),
				signalDbm=signalDbm,
				signalPct=max(0, min(100, 2 * (signalDbm + 100))),
				encryption=encryption,
				encDetails=flags,
			))
		return sorted(results, key=lambda x: -x.signalPct)


# ===========================================================================
# NetworkWiFiActivator – brings up a Wi-Fi connection
# ===========================================================================

class NetworkWiFiActivator(Screen):
	"""Runs ifup + wpa_supplicant (scoped to this one adapter, via wlanactivator)
	and polls for an IP address, so the user gets feedback if the connection
	attempt fails or times out."""

	skin = """
	<screen name="NetworkWiFiActivator" title="Connecting…" position="center,center" size="500,190" resolution="1280,720">
		<widget name="status" position="10,10" size="480,170" font="Regular;22" halign="center" valign="center" />
	</screen>"""

	_pollIntervalMs = 1500
	_pollMaxAttempts = 20

	def __init__(self, session, conn: Connection, adapter: Adapter):
		Screen.__init__(self, session)
		self.conn = conn
		self.adapter = adapter
		self.ssid = conn.wlan.ssid if conn.wlan else adapter.name
		self.serviceAction = None
		self.pollTimer = None
		self.closeTimer = None
		self.pollCount = 0
		self.setTitle(_("Connecting – %s") % adapter.name)
		self["status"] = Label()
		self.setStatus(_("Connecting…"))
		self.onLayoutFinish.append(self.start)

	# All status updates go through here so every message stays anchored to
	# which connection (SSID) and adapter it's actually about – there's only
	# ever the one "status" label in this screen.
	def setStatus(self, text: str):
		self["status"].setText(_("%s  (%s)\n\n%s") % (self.ssid, self.adapter.name, text))

	def start(self):
		def connectedCb(retval: int):
			if retval != 0:
				self.setStatus(self.diagnoseFailure())
				self.scheduleClose(6000, "")
				return
			self.pollCount = 0
			self.setStatus(_("Waiting for IP address…"))
			self.pollTimer = eTimer()
			self.pollTimer.callback.append(self.checkIp)
			self.pollTimer.start(self._pollIntervalMs, True)

		# wlanActivate() below runs "wlanactivator start <iface>" directly
		# (ifconfig up + wpa_supplicant against wpa_supplicant.conf) – it does
		# NOT go through ifup/etc/network/interfaces. Writing interfaces for a
		# previously-disabled adapter (so the connection survives a reboot, not
		# just this live activation) is NetworkConnectionWiFi.keySave()'s job –
		# it must happen there, before adapter.adapterEnabled gets flipped to
		# True, or the "was it already enabled" check is meaningless by the
		# time this screen opens.
		self.setStatus(_("Connecting…"))
		self.serviceAction = ServiceAction.wlanActivate(self.adapter.name, connectedCb)

	def checkIp(self):
		iface = self.adapter.name
		self.pollCount += 1
		ip = self.getKernelIp(iface)
		if ip and ip not in ("0.0.0.0", ""):
			self.pollTimer.stop()
			self.setStatus(_("Connected, IP address: %s") % ip)
			self.scheduleClose(4000, ip)
		elif self.pollCount >= self._pollMaxAttempts:
			self.pollTimer.stop()
			self.setStatus(self.diagnoseFailure())
			self.scheduleClose(6000, "")
		else:
			self.pollTimer.start(self._pollIntervalMs, True)

	def diagnoseFailure(self) -> str:
		"""Best-effort explanation of *why* the connection attempt failed, based on
		wpa_supplicant's association state (wpa_cli status) – distinguishes a
		missing/unreachable AP, a wrong key, and DHCP-only failures instead of a
		single generic "failed" message. The SSID/adapter is already shown by
		setStatus()'s header, so these messages don't repeat it."""
		iface = self.adapter.name
		if not networkManager.wpaSupplicantRunning(iface):
			reason = _("Could not connect.\nWi-Fi driver (wpa_supplicant) did not start – check your Wi-Fi settings.")
		else:
			state = networkManager.getWlanStatus(iface).get("wpa_state", "")
			if state == "COMPLETED":
				reason = _("Connected, but no IP address was received.\nCheck your router's DHCP settings.")
			elif state in ("4WAY_HANDSHAKE", "GROUP_HANDSHAKE"):
				reason = _("Could not connect.\nWrong Wi-Fi password?")
			elif state in ("SCANNING", "DISCONNECTED", "INACTIVE", ""):
				reason = _("Access point not found.\nCheck that it is in range and the SSID is correct.")
			else:
				reason = _("Could not connect (status: %s).") % state
		return reason + "\n" + _("Configuration saved – will retry automatically at next boot.")

	@staticmethod
	def getKernelIp(iface: str) -> str:
		addrs = netifaces.ifaddresses(iface)
		result = ""
		if netifaces.AF_INET in addrs:
			result = addrs[netifaces.AF_INET][0].get("addr", "")
		return result

	def scheduleClose(self, delayMs: int, ip: str):
		self.closeTimer = eTimer()
		self.closeTimer.callback.append(lambda: self.close(ip))
		self.closeTimer.start(delayMs, True)


# ===========================================================================
# NetworkWiFiAddFlow – coordinator / entry point
# ===========================================================================

class NetworkWiFiAddFlow:
	"""Stateless coordinator. Call NetworkWiFiAddFlow.start() to begin the flow."""

	@staticmethod
	def start(session, adapter: Adapter | None = None, callback=None):
		if adapter is not None:
			NetworkWiFiAddFlow.openScan(session, adapter, callback)
		else:
			wlanAdapters = [x for x in networkManager.adapters.values() if x.isWlan]
			if not wlanAdapters:
				session.showWarning(_("No Wi-Fi adapter found."))
			elif len(wlanAdapters) == 1:
				NetworkWiFiAddFlow.openScan(session, wlanAdapters[0], callback)
			else:
				NetworkWiFiAddFlow.pickAdapter(session, wlanAdapters, callback)

	@staticmethod
	def openScan(session, adapter: Adapter, callback):
		def scanned(result: ScanResult | None):
			if result is None:
				if callback:
					callback()
				return
			# Reuse the existing profile if this SSID is already configured (e.g.
			# already in wpa_supplicant.conf) instead of building a fresh, blank
			# Connection – otherwise NetworkConnectionWiFi.keySave()'s identity
			# check (`x is conn`) doesn't recognise it as the same profile, appends
			# a second Connection with the same SSID, and both get written to
			# wpa_supplicant.conf as separate network={} blocks, so the existing
			# one's key/priority/enabled state is effectively ignored.
			existing = next((x for x in networkManager.getConnections(adapter.name) if x.wlan and x.wlan.ssid == result.ssid), None)
			conn = existing if existing is not None else scanResultToConnection(result, adapter.name)

			def setupDone(*result):
				# NetworkConnectionWiFi.close() shape varies: no args (cancel), a bare
				# bool, or a (recursive, saved, ip) tuple (see setupClosed).
				# For Wi-Fi, "ip" is the address NetworkWiFiActivator already verified,
				# or "" if the connection could not be verified.
				ip = ""
				if len(result) == 1 and isinstance(result[0], tuple):
					saved = bool(result[0][1]) if len(result[0]) > 1 else False
					ip = result[0][2] if len(result[0]) > 2 else ""
				else:
					saved = bool(result[0]) if result else False
				if saved:
					conns = networkManager.getConnections(adapter.name)
					if not any(x.wlan and x.wlan.ssid == (conn.wlan.ssid if conn.wlan else "") for x in conns):
						conns.append(conn)
						networkManager.saveWpaSupplicant(adapter.name)
				if callback:
					callback(ip)
			session.openWithCallback(setupDone, NetworkConnectionWiFi, conn, adapter)
		session.openWithCallback(scanned, NetworkWiFiScanScreen, adapter)

	@staticmethod
	def pickAdapter(session, adapters: list[Adapter], callback):
		choices = [(x.name, x) for x in adapters]

		def chosen(adapter):
			if not adapter:
				if callback:
					callback()
				return
			NetworkWiFiAddFlow.openScan(session, adapter, callback)

		session.openWithCallback(chosen, MessageBox, _("Select Wi-Fi adapter"), type=MessageBox.TYPE_YESNO, list=choices)


# ===========================================================================
# NameserverSetup – backward-compat alias (some screens still import this)
# ===========================================================================

NameserverSetup = DnsSettings


# ===========================================================================
# NetworkTest – list-based adapter test (replaces NetworkAdapterTest)
# ===========================================================================


class NetworkTest(Screen):
	"""Sequential network adapter tests displayed as a simple list."""

	skin = """
	<screen name="NetworkTest" title="Network Test" position="center,center" size="900,510" resolution="1280,720">
		<widget source="list" render="Listbox" position="0,0" size="900,420" scrollbarMode="showNever">
			<template name="Default" fonts="enigma2icons;24,Regular;24,Regular;22,Regular;18" itemHeight="60" itemWidth="900">
				<mode name="default">
					<text index="Glyph" position="10,10" size="40,40" font="0" horizontalAlignment="center" verticalAlignment="center" foregroundColor="+Color" foregroundColorSelected="+Color" />
					<text index="Label" position="60,10" size="280,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Result" position="350,10" size="210,40" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="+Color" foregroundColorSelected="+Color" />
					<text index="Detail" position="570,10" size="320,40" font="3" horizontalAlignment="left" verticalAlignment="center" />
				</mode>
			</template>
		</widget>
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="200,e-50" size="180,40" backgroundColor="key_green" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-100,e-50" size="90,40" backgroundColor="key_back" font="Regular;20" conditional="key_help" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	ROW_ADAPTER = 0
	ROW_LINK = 1
	ROW_IP = 2
	ROW_GATEWAY = 3
	ROW_INTERNET = 4
	ROW_DNS = 5

	INDEX_GLYPH = 0
	INDEX_LABEL = 1
	INDEX_RESULT = 2
	INDEX_DETAIL = 3
	INDEX_COLOR = 4

	STATE_OK = "ok"
	STATE_FAIL = "fail"
	STATE_SKIP = "skip"
	STATE_BUSY = "busy"

	# state -> (glyph, color)
	STATES = {
		STATE_OK: ("\uE914", gRGB(0x0000CC00).argb()),    # check_circle, green
		STATE_FAIL: ("\uE918", gRGB(0x00CC0000).argb()),  # cancel, red
		STATE_SKIP: ("\uE92B", gRGB(0x00808080).argb()),  # do_not_disturb_on, grey
		STATE_BUSY: ("\uE9F8", gRGB(0x00808080).argb()),  # hourglass_empty, grey
	}

	T_NOT_FOUND = _("Not found")
	T_NA = _("N/A")
	T_ASSOCIATED = _("Associated")
	T_NOT_ASSOC = _("Not associated")
	T_CONNECTED = _("Connected")
	T_DISCONNECTED = _("Disconnected")
	T_NO_ADDRESS = _("No IP address")
	T_NO_GATEWAY = _("No gateway")
	T_PINGING = _("Pinging…")
	T_REACHABLE = _("Reachable")
	T_UNREACHABLE = _("Unreachable")
	T_RESOLVING = _("Resolving…")
	T_CONFIRMED = _("Confirmed")
	T_UNCONFIRMED = _("Unconfirmed")
	T_STATIC = _("Static")

	def __init__(self, session, iface: str):
		Screen.__init__(self, session, enableHelp=True)
		self.iface = iface
		self.rows: list[tuple] = []
		self.generation = 0
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Restart"))
		indexNames = {
			"Glyph": self.INDEX_GLYPH,
			"Label": self.INDEX_LABEL,
			"Result": self.INDEX_RESULT,
			"Detail": self.INDEX_DETAIL,
			"Color": self.INDEX_COLOR,
		}
		self["list"] = List([], indexNames=indexNames)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"cancel": (self.close, _("Close network test")),
			"red": (self.close, _("Close network test")),
			"green": (self.keyRestart, _("Restart test")),
		}, prio=0, description=_("Network Test Actions"))
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self["list"].enableAutoNavigation(False)
		self.start()

	def keyRestart(self):
		self.generation += 1
		self.start()

	def start(self):
		def setRow(idx: int, state: str, result: str, detail: str):
			glyph, color = self.STATES[state]
			row = list(self.rows[idx])
			row[self.INDEX_GLYPH], row[self.INDEX_RESULT], row[self.INDEX_DETAIL], row[self.INDEX_COLOR] = glyph, result, detail, color
			self.rows[idx] = tuple(row)
			self["list"].setList(list(self.rows))

		def pingRow(row: int, host: str, okText: str, failText: str, detail: str, nextFn):
			setRow(row, self.STATE_BUSY, self.T_PINGING, detail)
			gen = self.generation

			def done(exitCode: int):
				ok = exitCode == 0
				if not hasattr(self, "generation") or self.generation != gen:
					return
				setRow(row, self.STATE_OK if ok else self.STATE_FAIL, okText if ok else failText, detail)
				nextFn()
			ServiceAction.ping(self.iface, host, done)

		def testDns():
			setRow(self.ROW_DNS, self.STATE_BUSY, self.T_RESOLVING, "google.com")
			gen = self.generation

			def done(exitCode: int):
				ok = exitCode == 0
				if not hasattr(self, "generation") or self.generation != gen:
					return
				setRow(self.ROW_DNS, self.STATE_OK if ok else self.STATE_FAIL, self.T_CONFIRMED if ok else self.T_UNCONFIRMED, "google.com")
			ServiceAction.resolve("google.com", done)

		def testInternet():
			pingRow(self.ROW_INTERNET, "1.1.1.1", self.T_REACHABLE, self.T_UNREACHABLE, "1.1.1.1", testDns)

		def testGateway():
			gw = _ip4Str(net.gateway) if net.gateway else ""
			if not gw:
				setRow(self.ROW_GATEWAY, self.STATE_SKIP, self.T_NO_GATEWAY, "")
				# No gateway means no route out – the Internet ping can't
				# succeed, so skip it instead of waiting out a guaranteed
				# timeout. DNS still runs (e.g. a local/cached resolver may work).
				setRow(self.ROW_INTERNET, self.STATE_SKIP, self.T_NA, "")
				testDns()
			else:
				pingRow(self.ROW_GATEWAY, gw, self.T_REACHABLE, self.T_UNREACHABLE, gw, testInternet)

		def testIp():
			ip = net.ip or []
			ipStr = ".".join(str(x) for x in ip) if ip else ""
			if ipStr and ipStr != "0.0.0.0":
				conn = networkManager.activeConnection(self.iface)
				hint = "DHCP" if (conn and conn.dhcp) else self.T_STATIC
				setRow(self.ROW_IP, self.STATE_OK, ipStr, hint)
			else:
				setRow(self.ROW_IP, self.STATE_FAIL, self.T_NO_ADDRESS, "")
			testGateway()

		def testLink():
			if adapter.isWlan:
				ssid = net.ssid or ""
				if ssid:
					sig = f"{net.signal} dBm" if net.signal else ""
					setRow(self.ROW_LINK, self.STATE_OK, self.T_ASSOCIATED, f"{ssid}  {sig}".strip())
				else:
					setRow(self.ROW_LINK, self.STATE_FAIL, self.T_NOT_ASSOC, "")
			else:
				if net.link:
					speed = f"{net.speed} Mbps" if net.speed > 0 else ""
					setRow(self.ROW_LINK, self.STATE_OK, self.T_CONNECTED, speed)
				else:
					setRow(self.ROW_LINK, self.STATE_FAIL, self.T_DISCONNECTED, "")
			testIp()

		adapterName = networkManager.getFriendlyAdapterName(self.iface)
		self.setTitle(_("Network Test – %s") % adapterName)
		adapter = networkManager.adapters.get(self.iface)
		net = networkManager.getNetInfo(self.iface)
		isWlan = adapter.isWlan if adapter else False
		labels = [
			_("Adapter"),
			_("Wireless link") if isWlan else _("LAN link"),
			_("IP address"),
			_("Gateway"),
			"Internet",
			"DNS",
		]
		glyph, color = self.STATES[self.STATE_BUSY]
		self.rows = [(glyph, label, "", "", color) for label in labels]
		self["list"].setList(list(self.rows))
		if adapter:
			setRow(self.ROW_ADAPTER, self.STATE_OK, networkManager.getFriendlyAdapterName(self.iface), net.driver or "")
			testLink()
		else:
			setRow(self.ROW_ADAPTER, self.STATE_FAIL, self.T_NOT_FOUND, "")
			setRow(self.ROW_LINK, self.STATE_SKIP, self.T_NA, "")
			setRow(self.ROW_IP, self.STATE_SKIP, self.T_NA, "")
			testGateway()

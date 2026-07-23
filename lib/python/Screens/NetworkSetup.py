"""
NetworkSetup.py – Network connection screens for Enigma2 / OpenATV

Screens:
	NetworkOverview             – adapters + Wi-Fi connections, two XmlMultiContent listboxes
	NetworkAdapterSetup         – per-adapter DHCP/IP/DNS/WOL/WWOL/link speed (interfaces file)
	NetworkConnectionWiFi       – per-SSID profile settings (wpa_supplicant.conf only)
	DNSSettings                 – global system DNS (config.usage.dns.*, networkManager)
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

from dataclasses import dataclass
from ipaddress import ip_address

from os import rename
from os.path import exists
from re import IGNORECASE, compile

from enigma import eTimer, gRGB

from skin import parseColor
from Components.ActionMap import HelpableActionMap
from Components.config import ConfigIP, ConfigNumber, ConfigPassword, ConfigSelection, ConfigText, ConfigYesNo, NoSave, ReadOnly, config, getConfigListEntry
from Components.Console import Console
from Components.Label import Label
from Components.NetworkManager import Adapter, Connection, VpnInfo, WiFiConfig, networkManager, encNone, encWep, encWpa, encWpa2, encWpa3, encryptionLabels, wpaCliBin, CHANGE_NONE, CHANGE_ADAPTER_ENABLED, CHANGE_GENERAL
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo
from Screens.ChoiceBox import ChoiceBox
from Screens.Information import InformationNetwork
from Screens.MessageBox import MessageBox
from Screens.Processing import Processing
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Conversions import formatNetworkSpeed
from Tools.Directories import SCOPE_SKINS, fileReadLines, fileReadXML, fileWriteLines, resolveFilename
from Tools.ServiceAction import ServiceAction

MODULE_NAME = __name__.split(".")[-1]


def ip4Str(addr: list) -> str:
	joined = ".".join(str(x) for x in addr)
	return "" if joined == "0.0.0.0" else joined


# Apply the minimal action an adapter (LAN or Wi-Fi) needs after
# networkManager.save() (nothing / ifup-ifdown / full restart), with a
# visible progress indicator while it runs, then call callback(). The
# caller passes 'change' because it already knows what it just changed.
# The save() itself stays a plain writer.
#
def applyAdapterChange(interface: str, change: int, callback):
	def done(*_args):
		Processing.instance.hideProgress()
		callback()

	def doneNotify(*_args):
		# The restartNetwork() CHANGE_GENERAL notifies plugins if they need to
		# re-run discoverAdapters()/applyNetinfo() first.  Plain ifup/ifdown
		# actions don't refresh adapter state on their own, so do it here,
		# matching the notifyNetworkPlugins(False) above.
		networkManager.notifyNetworkPlugins(True, iface=interface)
		done(*_args)

	if change == CHANGE_NONE:
		# Nothing is actually going to happen to the network, so don't touch
		# plugins either. The save() used to unconditionally call
		# notifyNetworkPlugins(False) on every save regardless of 'change',
		# which stopped plugins (e.g. OpenWebif) even for a no-op save with
		# nothing to bring back up afterward, leaving them stopped for good.
		if callable(callback):
			callback()
		return
	# The network is about to change (ifup/ifdown/restart below). Tell plugins
	# to stop now.
	#
	# Every notifyNetworkPlugins(False) here MUST be paired with exactly one
	# matching notifyNetworkPlugins(True). Once that same change has finished
	# applying the changes, doneNotify below for ifup/ifdown, or
	# inside restartNetwork() itself for CHANGE_GENERAL, regardless of
	# whether this was an enable or a disable so that a plugin that was
	# stopped never gets left stopped forever.
	#
	# iface=interface: If another adapter is already up, the box stays
	# reachable, so this specific adapter's change doesn't need
	# to bounce the plugins at all. The decision is symmetric for both the
	# False and the True call, so pairing still holds (both activate, or both
	# are skipped).
	if change in (CHANGE_GENERAL, CHANGE_ADAPTER_ENABLED):
		networkManager.notifyNetworkPlugins(False, iface=interface)
	Processing.instance.setDescription(_("Please wait..."))
	Processing.instance.showProgress(endless=True)
	if change == CHANGE_GENERAL:
		networkManager.restartNetwork(iface=interface, callback=done)
	elif change == CHANGE_ADAPTER_ENABLED:
		adapter = networkManager.adapters.get(interface)
		if adapter and adapter.adapterEnabled:
			ServiceAction.ifup(interface, doneNotify)
		else:
			ServiceAction.ifdown(interface, doneNotify)
	else:
		done()


def scanResultToConnection(scanResult: ScanResult, iface: str) -> Connection:
	# enabled=True: the user is actively picking this network from the scan to
	# use it now. NetworkConnectionWiFi's "Enabled" field defaults to this
	# value, so a plain scan -> enter password -> Save (without touching that
	# field) used to save a *disabled* profile – save()'s interfaces-file
	# writer only emits the wpa_supplicant pre-up lines for an enabled
	# connection, so wpa_supplicant never started and Wi-Fi stayed dead.
	return Connection(adapter=iface, name=scanResult.ssid, dhcp=True, enabled=True, priority=0, wlan=WiFiConfig(ssid=scanResult.ssid, encryption=scanResult.encryption))


# NetworkOverview – Adapters (top list) and Saved Wi-Fi Networks for the
# selected adapter (bottom list).  These are two independent XmlMultiContent
# list boxes rather than a single indented tree.  The LAN adapters never gets
# a connection row.
#
class NetworkOverview(Screen):
	"""Adapters (top list) and Saved Wi-Fi Networks for the selected adapter (bottom list)."""

	# The data[0] of every row selects which <rowtemplate> renders it (see setTemplates()/
	# selectTemplate() in elistboxcontent.cpp). It does not shift the other fields'
	# indices so all indexNames below start at 1, not 0.
	OVERVIEW_TEMPLATE_HEADER = 0
	OVERVIEW_TEMPLATE_ROW = 1
	OVERVIEW_COLOR_CONNECTED = gRGB(0x0000CC00).argb()  # Green – Connected.
	OVERVIEW_COLOR_NO_LINK = gRGB(0x00CC0000).argb()   # Red – LAN without link.
	OVERVIEW_COLOR_IDLE = gRGB(0x00808080).argb()  # Gray – Disabled / Not associated / Saved connection.
	OVERVIEW_COLOR_CONNECTED_SELECTED = gRGB(0x0000CC00).argb()  # Green – Connected, row selected.
	OVERVIEW_COLOR_NO_LINK_SELECTED = gRGB(0x00CC0000).argb()   # Red – LAN without link, row selected.
	OVERVIEW_COLOR_IDLE_SELECTED = gRGB(0x00808080).argb()  # Gray – Disabled / Not Associated / Saved connection, row selected.

	skin = """
	<screen name="NetworkOverview" title="Network Overview" position="center,center" size="1220,660" resolution="1280,720">
		<widget source="adapterList" render="Listbox" position="10,8" size="1200,300" scrollbarMode="showOnDemand">
			<template name="Default" fonts="enigma2icons;34,Regular;24,Regular;18,enigma2icons;20" itemHeight="60" colors="#0000CC00,#00CC0000,#00808080,#0000CC00,#00CC0000,#00808080">
				<rowtemplate>
					<text index="AdapterName" position="14,0" size="470,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="MAC" position="490,0" size="190,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="IPAddress" position="690,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="Gateway" position="840,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="Speed" position="990,0" size="200,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
				</rowtemplate>
				<rowtemplate>
					<text index="AdapterGlyph" position="14,7" size="46,46" font="0" horizontalAlignment="center" verticalAlignment="center" />
					<text index="AdapterName" position="74,6" size="230,26" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="AdapterType" position="74,32" size="230,22" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="InternetGlyph" position="280,20" size="20,20" font="3" horizontalAlignment="center" verticalAlignment="center" />
					<text index="StatusText" position="320,0" size="160,60" font="2" horizontalAlignment="left" verticalAlignment="center" foregroundColor="+StatusColor" foregroundColorSelected="+StatusColorSelected" />
					<text index="MAC" position="490,0" size="190,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="IPAddress" position="690,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Gateway" position="840,0" size="140,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Speed" position="990,0" size="200,60" font="2" horizontalAlignment="left" verticalAlignment="center" />
				</rowtemplate>
			</template>
		</widget>
		<widget source="savedLabel" render="Label" position="10,340" size="700,30" font="Regular;20" foregroundColor="gray" transparent="1" halign="left" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="savedList" render="Listbox" position="10,374" size="1200,160" scrollbarMode="showOnDemand">
			<template name="Default" fonts="Regular;22,Regular;18" itemHeight="40" colors="#0000CC00,#00CC0000,#00808080,#0000CC00,#00CC0000,#00808080">
				<rowtemplate>
					<text index="SSID" position="20,0" size="280,40" font="0" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="BSSID" position="310,0" size="220,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="Frequency" position="540,0" size="120,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="Channel" position="670,0" size="140,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="Encryption" position="820,0" size="190,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
					<text index="StatusText" position="1020,0" size="180,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="gray" />
				</rowtemplate>
				<rowtemplate>
					<text index="SSID" position="20,0" size="280,40" font="0" horizontalAlignment="left" verticalAlignment="center" />
					<text index="BSSID" position="310,0" size="220,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Frequency" position="540,0" size="120,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Channel" position="670,0" size="140,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="Encryption" position="820,0" size="190,40" font="1" horizontalAlignment="left" verticalAlignment="center" />
					<text index="StatusText" position="1020,0" size="180,40" font="1" horizontalAlignment="left" verticalAlignment="center" foregroundColor="+StatusColor" foregroundColorSelected="+StatusColorSelected" />
				</rowtemplate>
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
		<widget source="key_blue" render="Label" position="580,e-50" size="180,40" backgroundColor="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" wrap="off" verticalAlignment="center">
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
		def greeHelp():
			return self.helpTextGreen

		def doClose():
			networkManager.onAdaptersChanged.remove(self.refreshAdapters)

		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Network Overview"))
		self["savedLabel"] = StaticText("")  # Shown via ConditionalShowHide once buildSaved() picks a Wi-Fi adapter.
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText("")
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")
		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))
		indexNames = {
			"Reserved_for_rowTemplate": 0,
			"AdapterGlyph": 1,
			"AdapterName": 2,
			"AdapterType": 3,
			"StatusText": 4,
			"StatusColor": 5,
			"StatusColorSelected": 6,
			"MAC": 7,
			"IPAddress": 8,
			"Gateway": 9,
			"Speed": 10,
			"InternetGlyph": 11
		}
		self.indexAdapter = 12
		self["adapterList"] = List([], indexNames=indexNames)
		indexNames = {
			"Reserved_for_rowTemplate": 0,
			"SSID": 1,
			"BSSID": 2,
			"Frequency": 3,
			"Channel": 4,
			"Encryption": 5,
			"StatusText": 6,
			"StatusColor": 7,
			"StatusColorSelected": 8
		}
		self.indexSaved = 9
		self["savedList"] = List([], indexNames=indexNames)
		self.currentList = "adapterList"  # "adapterList" | "savedList" – The list UP/DOWN/OK/GREEN/etc. act upon.
		self["adapterList"].onSelectionChanged.append(self.buildSaved)
		self["savedList"].onSelectionChanged.append(self.updateButtons)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "MenuActions", "InfoActions", "ColorActions", "NavigationActions"], {
			"ok": (self.keyOK, _("Open settings for the selected item")),
			"cancel": (self.close, _("Close the screen")),
			"close": (self.keyCloseRecursive, _("Close the screen and exit all menus")),
			"menu": (self.keyMenu, _("Open context menu for the selected item")),
			"info": (self.keyInfo, _("Show Adapter info")),
			"red": (self.close, _("Close the screen")),
			"green": (self.keyGreen, greeHelp),
			"yellow": (self.keyYellow, _("Add a new Wi-Fi connection")),
			"blue": (self.keyBlue, _("Connect to the selected Saved Wi-Fi network")),
			"top": (self.keyTop, _("Move to first line / screen")),
			"pageUp": (self.keyPageUp, _("Move up a screen")),
			"up": (self.keyUp, _("Move up a line")),
			"first": (self.keyLeft, _("Move to the Adapter list")),
			"left": (self.keyLeft, _("Move to the Adapter list")),
			"right": (self.keyRight, _("Move to the saved Wi-Fi networks list")),
			"last": (self.keyRight, _("Move to the saved Wi-Fi networks list")),
			"down": (self.keyDown, _("Move down a line")),
			"pageDown": (self.keyPageDown, _("Move down a screen")),
			"bottom": (self.keyBottom, _("Move to last line / screen"))
		}, prio=0, description=_("Network Overview Actions"))
		self.internetChecked = False
		self.helpTextGreen = ""
		self.onLayoutFinish.append(self.layoutFinished)
		self.onShown.append(self.checkInternet)
		self.onClose.append(doClose)

	def layoutFinished(self):
		self["adapterList"].enableAutoNavigation(False)
		self["adapterList"].setLockFirstRow(True)
		self.markHeaderNotSelectable("adapterList")
		self["savedList"].enableAutoNavigation(False)
		self["savedList"].setLockFirstRow(True)
		self.markHeaderNotSelectable("savedList")
		networkManager.onAdaptersChanged.append(self.refreshAdapters)
		self.buildAdapters()
		self.setListFocus("adapterList")

	def buildAdapters(self):
		rows = self.buildAdapterRows()
		hasRows = bool(rows)
		self["adapterList"].setList(rows)
		if hasRows:
			self["adapterList"].index = 1  # A setList() resets the cursor to 0 (the header) so skip past it.
		self.buildSaved()
		text = _("Add Wi-Fi") if any(x.isWlan for x in networkManager.adapters.values()) else ""
		self["key_yellow"].setText(text)
		self["actions"].setEnabledAction("yellow", text != "")

	def buildAdapterRows(self) -> list[tuple]:
		def buildOverviewAdapterRow(adapter: Adapter) -> tuple:
			"""Row for the adapter listbox. Same template for LAN and Wi-Fi. No per-type extra line."""
			netInfo = adapter.netInfo
			if not adapter.adapterEnabled:
				statusText, statusColor, statusColorSelected = _("Deactivated"), idle, idleSelected
			elif netInfo.link:
				statusText, statusColor, statusColorSelected = _("Connected"), connected, connectedSelected
			elif adapter.isWlan:
				statusText, statusColor, statusColorSelected = _("Not Connected"), idle, idleSelected
			else:
				statusText, statusColor, statusColorSelected = _("Cable Unplugged"), noLink, noLinkSelected
			if adapter.isWlan:
				speed = f"{netInfo.bitrateBps // 1000000} Mbps" if netInfo.bitrateBps else "—"
			else:
				speed = formatNetworkSpeed(netInfo.speed) if netInfo.speed > 0 else "—"
			internet = adapter.adapterEnabled and adapter.hasInternet
			inetGlyph = "\uEA68" if internet else ""  # Glyph is Cloud.
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				"\uE9FE" if adapter.isWlan else "\uEA5A",                         # AdapterGlyph (Glyphs are Wi-fi and Settings_ethernet).
				adapter.name,                                                     # AdapterName.
				_("Wi-Fi Adapter") if adapter.isWlan else _("Ethernet Adapter"),  # AdapterType.
				statusText,                                                       # StatusText.
				statusColor,                                                      # StatusColor.
				statusColorSelected,                                              # StatusColorSelected.
				adapter.mac.upper(),                                              # MAC.
				ip4Str(netInfo.ip) or "—",                                        # IPAddress.
				ip4Str(netInfo.gateway) or "—",                                   # Gateway.
				speed,                                                            # Speed.
				inetGlyph,                                                        # InternetGlyph.
				adapter,                                                          # -> indexAdapter.
			)

		def buildOverviewVpnRow(vpn: VpnInfo) -> tuple:
			"""Row for a VPN interface (e.g. wg0). Display only, never configurable
			here (ADAPTER_BLACKLIST'd, no /etc/network/interfaces stanza). indexAdapter
			is None so OK/GREEN/MENU/INFO all no-op via the existing is-None guards."""
			if vpn.up and vpn.link:
				statusText, statusColor, statusColorSelected = _("Connected"), connected, connectedSelected
			elif vpn.up:
				statusText, statusColor, statusColorSelected = _("Up"), idle, idleSelected
			else:
				statusText, statusColor, statusColorSelected = _("Down"), noLink, noLinkSelected
			inetGlyph = "\uEA69" if vpn.up and vpn.link else ""  # Cloud Locked.
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				"\uE9AF",               # AdapterGlyph (Glyph is Vpn_key).
				vpn.name,               # AdapterName.
				_("VPN"),               # AdapterType.
				statusText,             # StatusText.
				statusColor,            # StatusColor.
				statusColorSelected,    # StatusColorSelected.
				vpn.mac.upper(),        # MAC.
				ip4Str(vpn.ip) or "—",  # IPAddress.
				"—",                    # Gateway.
				"—",                    # Speed.
				inetGlyph,              # InternetGlyph.
				None,                   # -> indexAdapter.
			)

		def buildOverviewAdapterHeaderRow() -> tuple:
			"""First row of the adapter listbox, rendered via <rowtemplate> #0. The
			"Interfaces" section title (via AdapterName) plus column titles for the
			MAC/IPAddress/Gateway/Speed columns are not selectable
			(see isOverviewRowSelectable)."""
			return (
				self.OVERVIEW_TEMPLATE_HEADER,
				None,              # AdapterGlyph.
				_("Adapter"),      # AdapterName.
				None,              # AdapterType.
				_("Status"),       # StatusText.
				None,              # StatusColor.
				None,              # StatusColorSelected.
				_("MAC Address"),  # MAC.
				_("IP Address"),   # IPAddress.
				_("Gateway"),      # Gateway.
				_("Speed"),        # Speed.
				None,              # InternetGlyph.
				None,              # -> indexAdapter.
			)

		connected, noLink, idle, connectedSelected, noLinkSelected, idleSelected = self.overviewColors("adapterList")
		rows = [buildOverviewAdapterRow(networkManager.adapters[iface]) for iface in sorted(networkManager.adapters.keys())]
		rows += [buildOverviewVpnRow(networkManager.vpnInterfaces[iface]) for iface in sorted(networkManager.vpnInterfaces.keys())]
		if rows:
			rows.insert(0, buildOverviewAdapterHeaderRow())
		return rows

	def overviewColors(self, sourceName: str) -> tuple:
		"""Reads the <template>'s 'colors' attribute (connected, noLink, idle, then the
		same three again for the selected state. The same order as
		OVERVIEW_COLOR_CONNECTED/NO_LINK/IDLE[_SELECTED]), falling back to those class
		defaultColors if the skin doesn't set one, or if it only sets the first 3
		(selected falls back to the unselected values). additionalTemplateAttributes
		is populated by XmlMultiContent from any template attribute it doesn't
		itself know about."""
		defaultColors = (self.OVERVIEW_COLOR_CONNECTED, self.OVERVIEW_COLOR_NO_LINK, self.OVERVIEW_COLOR_IDLE, self.OVERVIEW_COLOR_CONNECTED_SELECTED, self.OVERVIEW_COLOR_NO_LINK_SELECTED, self.OVERVIEW_COLOR_IDLE_SELECTED)
		colors = self[sourceName].additionalTemplateAttributes.get("colors")
		if not colors:
			return defaultColors
		parts = [parseColor(part.strip()).argb() for part in colors.split(",")]
		if len(parts) == 3:
			parts += parts
		if len(parts) != 6:
			print(f"[NetworkOverview] Error: Template 'colors' must have 3 or 6 entries (connected, noLink, idle[, connectedSelected, noLinkSelected, idleSelectedected]), got {len(parts)}!")
			return defaultColors
		return tuple(parts)

	def buildSaved(self, preserveSelection: bool = False):
		"""Rebuilds the saved networks list for the currently selected adapter. By default
		(adapter selection actually changed) this resets the cursor to the first row.
		Called from refreshAdapters()'s periodic poll with preserveSelection=True instead,
		which diffs against the current rows and only touches changed ones via
		updateEntry().  The user's cursor in savedList isn't reset every poll."""
		adapter = self.currentAdapter()
		connections, rows = self.buildSavedRows(adapter)
		if adapter is None or not adapter.isWlan:
			self["savedList"].setList([])
			self["savedLabel"].setText("")  # Hidden via ConditionalShowHide, only relevant for a Wi-Fi adapter.
		else:
			if preserveSelection and len(rows) == self["savedList"].count():
				oldRows = self["savedList"].getList()
				for index, (oldRow, newRow) in enumerate(zip(oldRows, rows)):
					if oldRow != newRow:
						self["savedList"].updateEntry(index, newRow)
			else:
				hasRows = bool(rows)
				self["savedList"].setList(rows)
				if hasRows:
					self["savedList"].index = 1  # A setList() resets the cursor to 0 (the header) so skip past it.
			self["savedLabel"].setText(f"{_("Saved Wi-Fi Networks")} · {adapter.name} · {len(connections)}")
		if self.currentList == "savedList" and not self["savedList"].count():
			self.setListFocus("adapterList")
		else:
			self.updateButtons()

	def buildSavedRows(self, adapter: Adapter | None) -> tuple[list[Connection], list[tuple]]:
		def buildOverviewSavedRow(conn: Connection, adapter: Adapter) -> tuple:
			"""Row for the saved Wi-Fi listbox. BSSID/frequency/channel are only known
			while this connection is the one currently associated in wpa_supplicant.conf.
			Doesn't persist for saved networks that aren't connected right now."""
			ssid = conn.wlan.ssid
			netInfo = adapter.netInfo
			isLive = netInfo.link and netInfo.ssid == ssid
			if isLive:
				statusText, statusColor, statusColorSelected = _("Connected"), connected, connectedSelected
			elif conn.enabled:
				# Configured as the active connection, just not associated right now
				# (e.g. the adapter itself is off) – distinct from a genuinely
				# disabled connection, which toggleAdapter() must never touch.
				statusText, statusColor, statusColorSelected = _("Not Connected"), idle, idleSelected
			else:
				statusText, statusColor, statusColorSelected = _("Disabled"), idle, idleSelected
			return (
				self.OVERVIEW_TEMPLATE_ROW,
				ssid,                                                                        # SSID.
				netInfo.bssid.upper() if isLive and netInfo.bssid else "—",                  # BSSID.
				f"{netInfo.freqMhz / 1000:.2f} GHz" if isLive and netInfo.freqMhz else "—",  # Frequency.
				str(netInfo.channel) if isLive and netInfo.channel else "—",                 # Channel.
				encryptionLabels.get(conn.wlan.encryption, lambda: "")(),                    # Encryption.
				statusText,                                                                  # StatusText.
				statusColor,                                                                 # StatusColor.
				statusColorSelected,                                                         # StatusColorSelected.
				conn,                                                                        # -> indexSaved.
			)

		def buildOverviewSavedHeaderRow() -> tuple:
			"""First row of the saved Wi-Fi listbox, rendered via <rowtemplate> #0.
			Column titles are not selectable (see isOverviewRowSelectable). All
			texts are a static gray in the skin.  Unlike the data row's StatusText
			this one doesn't need a real StatusColor."""
			return (
				self.OVERVIEW_TEMPLATE_HEADER,
				_("SSID"),        # SSID.
				_("BSSID"),       # BSSID.
				_("Frequency"),   # Frequency.
				_("Channel"),     # Channel.
				_("Encryption"),  # Encryption.
				_("Status"),      # StatusText.
				None,             # StatusColor.
				None,             # StatusColorSelected.
				None,             # -> indexSaved.
			)

		connected, noLink, idle, connectedSelected, noLinkSelected, idleSelected = self.overviewColors("savedList")
		if adapter is None or not adapter.isWlan:
			return [], []
		connections = self.overviewWlanConnections(adapter)
		rows = [buildOverviewSavedRow(x, adapter) for x in connections]
		if rows:
			rows.insert(0, buildOverviewSavedHeaderRow())
		return connections, rows

	def setListFocus(self, listName: str):
		self.currentList = listName
		self["adapterList"].selectionEnabled(listName == "adapterList")
		self["savedList"].selectionEnabled(listName == "savedList")
		self.updateButtons()

	def updateButtons(self):
		infoText = ""
		greenText = ""
		blueText = ""
		adapter = self.currentAdapter()
		if adapter:
			if self.currentList == "adapterList":
				infoText = "INFO"
				greenText = _("Deactivate") if adapter.adapterEnabled else _("Activate")
				self.helpTextGreen = _("Deactivate Adapter") if adapter.adapterEnabled else _("Activate Adapter")
			else:
				conn = self.currentSaved()
				greenText = _("Disable") if conn.enabled else _("Enable")
				self.helpTextGreen = _("Disable Network") if conn.enabled else _("Enable Network")
				if conn.enabled and not self.isConnectionLive(conn, adapter):
					blueText = _("Connect")
		self["key_info"].setText(infoText)
		self["key_green"].setText(greenText)
		self["key_blue"].setText(blueText)
		self["actions"].setEnabledAction("info", infoText != "")
		self["actions"].setEnabledAction("green", greenText != "")
		self["actions"].setEnabledAction("blue", blueText != "")
		self["actions"].setEnabledAction("first", self.currentList == "savedList")
		self["actions"].setEnabledAction("left", self.currentList == "savedList")
		self["actions"].setEnabledAction("right", self.currentList == "adapterList" and self["savedList"].count())
		self["actions"].setEnabledAction("last", self.currentList == "adapterList" and self["savedList"].count())

	def isConnectionLive(self, conn: Connection, adapter: Adapter) -> bool:
		"""True if saved entry is the Wi-Fi connection the adapter is currently
		associated with, same check as buildOverviewConnectionRow()'s isLive."""
		return adapter.netInfo.link and adapter.netInfo.ssid == conn.wlan.ssid

	def currentAdapter(self) -> Adapter | None:
		entry = self["adapterList"].getCurrent()
		return entry[self.indexAdapter] if entry else None

	def currentSaved(self) -> Connection | None:
		entry = None
		if self.currentList == "savedList":
			entry = self["savedList"].getCurrent()
		return entry[self.indexSaved] if entry else None

	def checkInternet(self):
		def checkInternetCallback():
			self.internetChecked = True
			self.refreshAdapters()

		if not self.internetChecked:
			networkManager.checkConnectionInternet(callback=checkInternetCallback)

	def refreshAdapters(self):
		if "adapterList" in self:
			oldGateways = {x[self.indexAdapter].name: x[self.indexAdapter].netInfo.gateway for x in self["adapterList"].getList() if x[self.indexAdapter] is not None}
			newGateways = {name: adapter.netInfo.gateway for name, adapter in networkManager.adapters.items()}
			if oldGateways != newGateways:
				self.internetChecked = False
				self.checkInternet()
				return
			oldRows = self["adapterList"].getList()
			newRows = self.buildAdapterRows()
			if len(oldRows) != len(newRows):
				# Structural change (Adapter/VPN added or removed), row indices can shift,
				# so a per-row diff can't be trusted. Fall back to the full rebuild.
				adapterIndex = self["adapterList"].getCurrentIndex() if self["adapterList"].count() else -1
				savedIndex = self["savedList"].getCurrentIndex() if self["savedList"].count() else -1
				self.buildAdapters()
				try:
					if adapterIndex != -1:
						self["adapterList"].setCurrentIndex(adapterIndex)
				except Exception:
					pass
				if self.currentList == "savedList":
					try:
						if savedIndex != -1:
							self["savedList"].setCurrentIndex(savedIndex)
					except Exception:
						pass
			else:
				for index, (oldRow, newRow) in enumerate(zip(oldRows, newRows)):
					if oldRow != newRow:
						self["adapterList"].updateEntry(index, newRow)
				self.buildSaved(preserveSelection=True)

	def keyOK(self):
		adapter = self.currentAdapter()
		if adapter is None:
			return
		conn = self.currentSaved()
		if conn is None:
			# Adapter row (LAN, or Wi-Fi with no/unselected connection row).
			# DHCP/IP/DNS/WOL/WWOL/link speed all live on the adapter now.
			self.openAdapterSetup(adapter)
		else:
			self.openSetup(conn, adapter)

	def keyCloseRecursive(self):
		self.close(True)

	def keyMenu(self):
		def showContextMenu(conn: Connection | None, adapter: Adapter):
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
					(_("Disable network") if conn.enabled else _("Enable network"), "toggleSaved"),
				]
				menu.append((_("Delete network"), "delete"))
				title = _("Network: %s") % self.connLabel(conn, adapter)
			if adapter.isWlan:
				menu.append((_("Scan for Wi-Fi networks"), "scan"))
				menu.append((_("Add Wi-Fi manually"), "addManual"))
			self.session.openWithCallback(lambda choice: self.contextCb(choice, conn, adapter), ChoiceBox, windowTitle=title, choiceList=menu)

		adapter = self.currentAdapter()
		if adapter:
			showContextMenu(self.currentSaved(), adapter)

	def keyInfo(self):
		if self.currentList == "adapterList":
			adapter = self.currentAdapter()
			if adapter:
				self.session.open(NetworkInformation, adapter, self.currentSaved())

	def keyGreen(self):
		adapter = self.currentAdapter()
		if adapter:
			if self.currentList == "adapterList":
				self.toggleAdapter(adapter)
			else:
				conn = self.currentSaved()
				if conn:
					self.toggleSaved(conn, adapter)

	def keyYellow(self):
		if networkManager.adapters:
			wlanAdapters = [x for x in networkManager.adapters.values() if x.isWlan]
			if wlanAdapters:
				adapter = self.currentAdapter()
				preselected = adapter if adapter is not None and adapter.isWlan else None
				NetworkWiFiAddFlow.start(self.session, adapter=preselected, callback=lambda *_: self.buildAdapters())

	def keyBlue(self):
		conn = self.currentSaved()
		adapter = self.currentAdapter()
		if adapter and conn and conn.enabled and not self.isConnectionLive(conn, adapter):
			self.session.openWithCallback(lambda *_: self.refreshAdapters(), NetworkWiFiActivator, conn, adapter)

	def keyTop(self):
		self[self.currentList].goTop()

	def keyPageUp(self):
		self[self.currentList].goPageUp()

	def keyUp(self):
		self[self.currentList].goLineUp()

	def keyLeft(self):
		self.setListFocus("adapterList")

	def keyRight(self):
		self.setListFocus("savedList")

	def keyDown(self):
		self[self.currentList].goLineDown()

	def keyPageDown(self):
		self[self.currentList].goPageDown()

	def keyBottom(self):
		self[self.currentList].goBottom()

	def markHeaderNotSelectable(self, sourceName: str):
		def isOverviewRowSelectable(kind, *_):
			return kind != self.OVERVIEW_TEMPLATE_HEADER

		# The .master.content (the eListboxPythonMultiContent) is only created
		# once setList() has run at least once on this source, so this must run
		# right after, and not from onLayoutFinish, which would be too late for
		# the very first buildAdapters() -> buildSaved() -> currentAdapter().
		self[sourceName].master.content.setSelectableFunc(isOverviewRowSelectable)

	def overviewWlanConnections(self, adapter: Adapter) -> list[Connection]:
		return [conn for conn in networkManager.getConnections(adapter.name) if conn.wlan and conn.wlan.ssid]

	def connLabel(self, conn: Connection, adapter: Adapter) -> str:
		encShort = {
			encNone: "open",
			encWep: "WEP",
			encWpa: "WPA",
			encWpa2: "WPA2",
			encWpa3: "WPA3"
		}
		if conn.isWlan and conn.wlan and conn.wlan.ssid:
			result = f"{conn.adapter}  │  {conn.wlan.ssid}  [{encShort.get(conn.wlan.encryption, conn.wlan.encryption)}]"
		else:
			mode = "DHCP" if conn.dhcp else conn.ipStr()
			result = f"{conn.adapter}  │  {mode}"
		return result

	def contextCb(self, choice, conn: Connection | None, adapter: Adapter):
		def openWlanManual(adapter: Adapter):
			conn = Connection(adapter=adapter.name, name=_("New Wi-Fi"), dhcp=True, enabled=False, wlan=WiFiConfig())
			self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, conn, adapter)

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
			def done():
				Processing.instance.hideProgress()
				self.buildAdapters()

			Processing.instance.setDescription(_("Restarting adapter..."))
			Processing.instance.showProgress(endless=True)
			networkManager.restartNetwork(iface=adapter.name, callback=done)

		def openWlanScan(iface: str):
			def wlanScanDone(result: ScanResult | None, adapter: Adapter):
				if result:
					self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, scanResultToConnection(result, adapter.name), adapter)

			adapter = networkManager.getAdapter(iface)
			if adapter is not None and adapter.isWlan:
				self.session.openWithCallback(lambda result: wlanScanDone(result, adapter), NetworkWiFiScanScreen, adapter)

		if choice:
			match choice[1]:
				case "adapterSetup":
					self.openAdapterSetup(adapter)
				case "addManual":
					openWlanManual(adapter)
				case "delete":
					confirmDelete(conn, adapter)
				case "restartAdapter":
					restartAdapter(adapter)
				case "scan":
					openWlanScan(adapter.name)
				case "setup":
					self.openSetup(conn, adapter)
				case "test":
					self.session.open(NetworkTest, adapter.name)
				case "toggleAdapter":
					self.toggleAdapter(adapter)
				case "toggleSaved":
					self.toggleSaved(conn, adapter)

	def openAdapterSetup(self, adapter: Adapter):
		self.session.openWithCallback(self.setupClosed, NetworkAdapterSetup, adapter)

	def openSetup(self, conn: Connection, adapter: Adapter):
		self.session.openWithCallback(self.setupClosed, NetworkConnectionWiFi, conn, adapter)

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

	def toggleAdapter(self, adapter: Adapter):
		def done():
			self.refreshAdapters()
			self.session.showInfo(_("Network adapter enabled") if adapter.adapterEnabled else _("Network adapter disabled"))

		adapter.adapterEnabled = not adapter.adapterEnabled
		networkManager.save()
		applyAdapterChange(adapter.name, CHANGE_ADAPTER_ENABLED, done)

	def toggleSaved(self, conn: Connection, adapter: Adapter):
		def done(*_args):
			self.refreshAdapters()
			self.session.showInfo(_("Network connection enabled") if conn.enabled else _("Network connection disabled"))

		if conn.enabled:
			wasLive = self.isConnectionLive(conn, adapter)
			conn.enabled = False
			networkManager.save()
			if wasLive and conn.wlan and conn.wlan.wpaId is not None:
				Console().ePopen((wpaCliBin, wpaCliBin, "-i", adapter.name, "disable_network", str(conn.wlan.wpaId)), callback=done)
			else:
				done()
		else:
			conn.enabled = True
			networkManager.save()
			done()

	# Green button on a Wi-Fi connection row: switch to this connection (never a
	# toggle – deactivating the active connection happens via the context menu).
	#
	# This method is not used at the moment but it may be used later.
	#
	def activateWlanConnection(self, conn: Connection, adapter: Adapter):
		for connection in networkManager.getConnections(adapter.name):
			connection.enabled = (connection is conn)
		adapter.adapterEnabled = True
		networkManager.save()
		self.refreshAdapters()
		self.session.openWithCallback(lambda *_: self.refreshAdapters(), NetworkWiFiActivator, conn, adapter)


# NetworkAdapterSetup – Per-adapter settings (DHCP/IP/DNS/WOL/WWOL/link speed),
# written to /etc/network/interfaces. Same screen for LAN and Wi-Fi adapters;
# operates on the adapter's base Connection (networkManager.getBaseConnection).
#
class NetworkAdapterSetup(Setup):
	"""Setup screen for one Adapter's IP configuration, Wake-on-LAN/WiFi and link speed."""

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
		self.session.open(NetworkInformation, self.adapter, self.conn)

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
		# Route metric. (Only while the e2-route-metric daemon config exists
		# and more than one adapter is present. That's the only situation
		# where more than one gateway, and thus a metric, is relevant.)
		currentMetric = adapter.metric
		self.hasMetric = currentMetric is not None and len(networkManager.adapters) > 1
		self.cfgMetric = NoSave(ConfigSelection(choices=networkManager.ROUTE_METRIC_CHOICES, default=currentMetric if currentMetric is not None else (600 if adapter.isWlan else 100)))
		# Per-adapter DNS (inline, replaces separate DNS setup screen).
		hasOwn = bool(conn.dnsServers)
		self.cfgDnsOverride = NoSave(ConfigYesNo(default=hasOwn))
		dnsV4 = [x for x in conn.dnsServers if isinstance(x, list)]
		dnsV6 = [x for x in conn.dnsServers if isinstance(x, str)]
		self.cfgDns1v4 = NoSave(ConfigIP(default=dnsV4[0] if len(dnsV4) > 0 else [0, 0, 0, 0]))
		self.cfgDns2v4 = NoSave(ConfigIP(default=dnsV4[1] if len(dnsV4) > 1 else [0, 0, 0, 0]))
		self.cfgDns1v6 = NoSave(ConfigText(default=dnsV6[0] if len(dnsV6) > 0 else "", fixed_size=False))
		self.cfgDns2v6 = NoSave(ConfigText(default=dnsV6[1] if len(dnsV6) > 1 else "", fixed_size=False))
		# Forced link speed (LAN adapters only).
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
		# Wake-on-WiFi (Broadcom wlan3 only).
		# cfgWakeOnWiFi: WoW while normally active (activate=True).
		# cfgWowOnly:    WoW only, no normal connection (activate=False).
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
		# Apply Wake-on-WiFi (Broadcom).
		if adapter.isWlan and adapter.canWakeOnWiFi:
			conn.wakeOnWiFi = self.cfgWakeOnWiFi.value if adapter.adapterEnabled else self.cfgWowOnly.value
			cmds = networkManager.setWakeOnWiFiCommands(adapter.name, conn.wakeOnWiFi)
			if cmds:
				Console().eBatch(cmds, lambda result: None, debug=False)
		# Apply forced link speed (LAN adapters only).
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
		# factor into 'change'. It is just a route preference for e2-route-metric
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


class NetworkConnectionWiFi(Setup):
	"""Setup screen for one Wi-Fi profile (SSID)."""

	ENCRYPTION_CHOICES = [
		(encNone, _("None")),
		(encWep, "WEP"),
		(encWpa, "WPA"),
		(encWpa2, "WPA2"),
	]
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
		self.session.open(NetworkInformation, self.adapter, self.conn)

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
		# WPA3/SAE disabled for now – the Broadcom "wl" driver (brcm-wl) can't do it.
		# if BoxInfo.getItem("wpa3") or (conn.wlan and conn.wlan.encryption == encWpa3):
		# 	self.ENCRYPTION_CHOICES.append((encWpa3, "WPA3"))
		wlan = conn.wlan
		self.cfgSsid = NoSave(ConfigText(default=wlan.ssid, fixed_size=False))
		self.cfgHidden = NoSave(ConfigYesNo(default=wlan.hidden))
		self.cfgEncryption = NoSave(ConfigSelection(choices=self.ENCRYPTION_CHOICES, default=wlan.encryption))
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
			# The adapter itself was off before this save. Its stanza in
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


# NetworkInformation – Subclass of the InformationNetwork.
#
class NetworkInformation(InformationNetwork):
	def __init__(self, session, adapter, conn):
		InformationNetwork.__init__(self, session)
		self.adapter = adapter
		self.conn = conn

	def displayInformation(self):
		InformationNetwork.displayInformation(self, selectedAdapter=self.adapter)


# ScanResult – One discovered Wi-Fi network.
#
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


# NetworkWiFiScanScreen – Live iwlist scan.
#
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
						f"{accessPoint.ssid}  ({accessPoint.bssid})",                # Name.
						accessPoint.ssid,                                            # SSID.
						accessPoint.bssid,                                           # BSSID.
						self.STRENGTH_GLYPHS[min(accessPoint.signalBars, 4)],        # Glyph.
						f"{accessPoint.signalPct}%  ({accessPoint.signalDbm} dBm)",  # Strength.
						f"{accessPoint.signalPct}%",                                 # Percent.
						f"{accessPoint.signalDbm} dBm",                              # dBM.
						accessPoint.encLabel,                                        # Encryption.
						f"Ch-{accessPoint.channel}  ({accessPoint.frequency})",      # ChannelFrequency.
						f"Ch-{accessPoint.channel}",                                 # Channel.
						accessPoint.frequency,                                       # Frequency.
						accessPoint                                                  # AccessPoint data record.
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
			def scanResultsCallback(results, retVal, extraArgs=None):
				finishScan(results, self.parseWpaCliScanResults)

			def triggerScanCallback(results=None, retVal=0, extraArgs=None):
				self.scanTimer = eTimer()
				self.scanTimer.callback.append(lambda: self.console.ePopen((wpaCliBin, wpaCliBin, "-i", self.adapter, "scan_results"), callback=scanResultsCallback))
				self.scanTimer.start(3000, True)

			# The wpa_supplicant already owns the radio for this iface (it is associated
			# to a network). A concurrent "iwlist scanning" ioctl typically fails
			# with "Device or resource busy" on nl80211 drivers in that state, so
			# route the scan through wpa_supplicant's own control interface instead.
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
			self["description"].setText(_("Scanning..."))
			if self.adapterObj.netInfo.up:
				ifUpCallback()
			else:
				self.console.ePopen(("/sbin/ifconfig", "/sbin/ifconfig", self.adapter, "up"), callback=ifUpCallback)

	def parseIwlist(self, raw: str) -> list[ScanResult]:
		results: list[ScanResult] = []
		current: ScanResult | None = None
		reCell = compile(r"Cell \d+ - Address:\s*([0-9A-Fa-f:]{17})")
		reSsid = compile(r"ESSID:\"(.*?)\"")
		reFreq = compile(r"Frequency:([\d.]+ \w+Hz).*?Channel:?\s*(\d+)?")
		reQuality = compile(r"Quality=(\d+)/(\d+)\s+Signal level=(-?\d+) dBm")
		reEncOn = compile(r"Encryption key:on")
		reEncOff = compile(r"Encryption key:off")
		reIeWpa1 = compile(r"IE:.*WPA Version 1", IGNORECASE)
		reIeWpa2 = compile(r"IE:.*WPA2|IE:.*RSN", IGNORECASE)
		# reIeWpa3 = compile(r"IE:.*SAE|IE:.*WPA3", IGNORECASE)  # WPA3/SAE is disabled for now.
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

	# "wpa_cli scan_results" output: one tab-separated line per AP.
	# "bssid / frequency / signal level / flags / ssid" (no quality/percent,
	# unlike iwlist – signalDbm is converted to a percentage below).
	#
	def parseWpaCliScanResults(self, raw: str) -> list[ScanResult]:
		results: list[ScanResult] = []
		reBssid = compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
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


# NetworkWiFiActivator – Brings up a Wi-Fi connection.
#
class NetworkWiFiActivator(Screen):
	"""Runs ifup + wpa_supplicant (scoped to this one adapter, via
	wlanactivator script) and polls for an IP address, so the user
	gets feedback if the connection attempt fails or times out."""

	skin = """
	<screen name="NetworkWiFiActivator" title="Connecting..." position="center,center" size="480,260" resolution="1280,720">
		<widget name="status" position="10,10" size="e-20,e-70" font="Regular;22" horizontalAlignment="center" verticalAlignment="center" />
		<widget source="key_red" render="Label" position="10,e-50" size="180,40" backgroundColor="key_red" font="Regular;20" foregroundColor="key_text" halign="center" noWrap="1" valign="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session, conn: Connection, adapter: Adapter):
		Screen.__init__(self, session, enableHelp=True)
		self.conn = conn
		self.adapter = adapter
		self.ssid = conn.wlan.ssid if conn.wlan else adapter.name
		self.serviceAction = None
		self.pollTimer = None
		self.closeTimer = None
		self.pollCount = 0
		self.setTitle(_("Connecting – %s") % adapter.name)
		self["status"] = Label()
		self["key_red"] = StaticText("")
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"cancel": (self.keyClose, _("Close")),
			"red": (self.keyClose, _("Close")),
		}, prio=0, description=_("Wi-Fi Activation Actions"))
		self.pollIntervalMs = 1500
		self.pollMaxAttempts = 20
		self.onLayoutFinish.append(self.start)
		print(f"[NetworkWiFiActivator] DEBUG __init__: iface={adapter.name} ssid={self.ssid!r}")

	def keyClose(self):
		self.close("")

	# Errors don't auto-close – give the user something to read and a way to
	# dismiss it themselves instead of the screen just vanishing on a timer.
	#
	def showCloseButton(self):
		self["key_red"].setText(_("Close"))

	# All status updates go through here so every message stays anchored to
	# which connection (SSID) and adapter it's actually about – there's only
	# ever the one "status" label in this screen.
	#
	def setStatus(self, text: str):
		self["status"].setText(_("%s  (%s)\n\n%s") % (self.ssid, self.adapter.name, text))

	def start(self):
		def connectedCb(retval: int):
			print(f"[NetworkWiFiActivator] DEBUG connectedCb: iface={self.adapter.name} retval={retval}")
			if retval != 0:
				self.setStatus(self.diagnoseFailure())
				self.showCloseButton()
				return
			self.beginPolling()

		# The wlanActivate() below runs "wlanactivator start <iface>" directly
		# (ifconfig up + wpa_supplicant against wpa_supplicant.conf). It does
		# NOT go through ifup/etc/network/interfaces. Writing interfaces for a
		# previously-disabled adapter (so the connection survives a reboot, not
		# just this live activation) is NetworkConnectionWiFi.keySave()'s job.
		# It must happen there, before adapter.adapterEnabled gets flipped to
		# True, or the "was it already enabled" check is meaningless by the
		# time this screen opens.
		self.setStatus(_("Connecting..."))
		networkId = self.conn.wlan.wpaId if self.conn.wlan else None
		print(f"[NetworkWiFiActivator] DEBUG start: dispatching wlanActivate for iface={self.adapter.name} networkId={networkId}")
		self.serviceAction = ServiceAction.wlanActivate(self.adapter.name, connectedCb, networkId=networkId)

	def beginPolling(self):
		self.pollCount = 0
		self.setStatus(_("Waiting for IP address..."))
		self.pollTimer = eTimer()
		self.pollTimer.callback.append(self.checkIp)
		self.pollTimer.start(self.pollIntervalMs, True)

	def checkIp(self):
		iface = self.adapter.name
		self.pollCount += 1
		# netifaces/ifaddresses() reads the kernel address table regardless of
		# link state – a stale address can survive on a down/disassociated
		# interface and would read as "connected" before anything really is.
		# netInfo (socketdaemon's /var/run/netinfo) ties the IP to link state,
		# so re-read it synchronously here rather than trust ifaddresses().
		networkManager.applyNetinfo()
		netInfo = self.adapter.netInfo
		ip = ip4Str(netInfo.ip)
		print(f"[NetworkWiFiActivator] DEBUG checkIp: iface={iface} attempt={self.pollCount}/{self.pollMaxAttempts} link={netInfo.link} ip={ip!r}")
		if netInfo.link and ip:
			self.pollTimer.stop()
			self.setStatus(_("Connected.\nIP address: %s") % ip)
			self.scheduleClose(5000, ip)
		elif self.pollCount >= self.pollMaxAttempts:
			self.pollTimer.stop()
			self.setStatus(self.diagnoseFailure())
			self.showCloseButton()
		else:
			self.pollTimer.start(self.pollIntervalMs, True)

	def diagnoseFailure(self) -> str:
		"""Best-effort explanation of *why* the connection attempt failed, based on
		wpa_supplicant's association state (wpa_cli status). Distinguishes a
		missing/unreachable AP, a wrong key, and DHCP-only failures instead of a
		single generic "failed" message. The SSID/adapter is already shown by
		setStatus()'s header, so these messages don't repeat it."""
		interface = self.adapter.name
		running = networkManager.wpaSupplicantRunning(interface)
		print(f"[NetworkWiFiActivator] DEBUG diagnoseFailure: iface={interface} wpaSupplicantRunning={running}")
		if not running:
			reason = _("Could not connect.\nWi-Fi driver (wpa_supplicant) did not start, check the Wi-Fi settings.")
		else:
			state = networkManager.getWlanStatus(interface).get("wpa_state", "")
			print(f"[NetworkWiFiActivator] DEBUG diagnoseFailure: iface={interface} wpa_state={state!r}")
			if state == "COMPLETED":
				reason = _("Connected, but no IP address was received.\nCheck the router's DHCP settings.")
			elif state in ("4WAY_HANDSHAKE", "GROUP_HANDSHAKE"):
				reason = _("Could not connect.\nWrong Wi-Fi password?")
			elif state in ("SCANNING", "DISCONNECTED", "INACTIVE", ""):
				reason = _("Access point not found.\nCheck it is in range and the SSID is correct.")
			else:
				reason = _("Could not connect (status: %s).") % state
		return f"{reason}\n{_("Configuration saved and will be retried automatically at next boot.")}"

	def scheduleClose(self, delayMs: int, ip: str):
		def doClose():
			print(f"[NetworkWiFiActivator] DEBUG scheduleClose: firing close() now for iface={self.adapter.name} ip={ip!r}")
			self.close(ip)

		print(f"[NetworkWiFiActivator] DEBUG scheduleClose: iface={self.adapter.name} delayMs={delayMs} ip={ip!r}")
		self.closeTimer = eTimer()
		self.closeTimer.callback.append(doClose)
		self.closeTimer.start(delayMs, True)

	def close(self, *args, **kwargs):
		print(f"[NetworkWiFiActivator] DEBUG close: iface={self.adapter.name} args={args}")
		return Screen.close(self, *args, **kwargs)


# NetworkWiFiAddFlow – Coordinator / entry point.
#
class NetworkWiFiAddFlow:
	"""Stateless coordinator. Call NetworkWiFiAddFlow.start() to begin
	the work flow of adding the adaptor and the saved network connection."""

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

			if result is None:
				if callback:
					callback()
				return
			# Reuse the existing profile if this SSID is already configured (e.g.
			# already in wpa_supplicant.conf) instead of building a fresh, blank
			# Connection – otherwise NetworkConnectionWiFi.keySave()'s identity
			# check ('x is conn') doesn't recognise it as the same profile, appends
			# a second Connection with the same SSID, and both get written to
			# wpa_supplicant.conf as separate network={} blocks, so the existing
			# one's key/priority/enabled state is effectively ignored.
			existing = next((x for x in networkManager.getConnections(adapter.name) if x.wlan and x.wlan.ssid == result.ssid), None)
			conn = existing if existing is not None else scanResultToConnection(result, adapter.name)

			session.openWithCallback(setupDone, NetworkConnectionWiFi, conn, adapter)

		session.openWithCallback(scanned, NetworkWiFiScanScreen, adapter)

	@staticmethod
	def pickAdapter(session, adapters: list[Adapter], callback):
		def chosen(adapter):
			if not adapter:
				if callback:
					callback()
				return
			NetworkWiFiAddFlow.openScan(session, adapter, callback)

		choices = [(x.name, x) for x in adapters]
		session.openWithCallback(chosen, MessageBox, _("Select Wi-Fi adapter"), type=MessageBox.TYPE_YESNO, list=choices)


# NetworkTest – List-based adapter test (replaces NetworkAdapterTest).
#
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
	STATES = {  # State -> (Glyph, Color)
		STATE_OK: ("\uE914", gRGB(0x0000CC00).argb()),  # Check_circle, Green.
		STATE_FAIL: ("\uE918", gRGB(0x00CC0000).argb()),  # Cancel, Red.
		STATE_SKIP: ("\uE92B", gRGB(0x00808080).argb()),  # Do_not_disturb_on, Gray.
		STATE_BUSY: ("\uE9F8", gRGB(0x00808080).argb()),  # Hourglass_empty, Gray.
	}

	def __init__(self, session, interface: str):
		Screen.__init__(self, session, enableHelp=True)
		self.interface = interface
		self.rows: list[tuple] = []
		self.generation = 0
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Retest"))
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
		self["list"].master.content.setSelectableFunc(lambda *_: False)
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
			def done(exitCode: int):
				ok = exitCode == 0
				if not hasattr(self, "generation") or self.generation != gen:
					return
				setRow(row, self.STATE_OK if ok else self.STATE_FAIL, okText if ok else failText, detail)
				nextFn()

			setRow(row, self.STATE_BUSY, _("Pinging..."), detail)
			gen = self.generation
			ServiceAction.ping(self.interface, host, done)

		def testDns():
			def done(exitCode: int):
				ok = exitCode == 0
				if not hasattr(self, "generation") or self.generation != gen:
					return
				setRow(self.ROW_DNS, self.STATE_OK if ok else self.STATE_FAIL, _("Available") if ok else _("Unavailable"), "Found Google")

			setRow(self.ROW_DNS, self.STATE_BUSY, _("Resolving..."), "google.com")
			gen = self.generation
			ServiceAction.resolve("google.com", done)

		def testInternet():
			pingRow(self.ROW_INTERNET, "1.1.1.1", reachableText, unreachableText, "Cloudflare accessible", testDns)

		def testGateway():
			gateway = ip4Str(net.gateway) if net.gateway else ""
			if not gateway:
				setRow(self.ROW_GATEWAY, self.STATE_SKIP, _("No gateway"), "")
				# No gateway means no route out. The Internet ping can't succeed,
				# so skip it instead of waiting out a guaranteed timeout. DNS
				# still runs (e.g. a local/cached resolver may work).
				setRow(self.ROW_INTERNET, self.STATE_SKIP, notAvailableText, "")
				testDns()
			else:
				pingRow(self.ROW_GATEWAY, gateway, reachableText, unreachableText, gateway, testInternet)

		def testIp():
			ip = net.ip or []
			ipStr = ".".join(str(x) for x in ip) if ip else ""
			if ipStr and ipStr != "0.0.0.0":
				conn = networkManager.activeConnection(self.interface)
				hint = "DHCP" if (conn and conn.dhcp) else _("Static")
				setRow(self.ROW_IP, self.STATE_OK, ipStr, hint)
			else:
				setRow(self.ROW_IP, self.STATE_FAIL, _("No IP address"), "")
			testGateway()

		def testLink():
			if adapter.isWlan:
				ssid = net.ssid or ""
				if ssid:
					sig = f"{net.signal} dBm" if net.signal else ""
					setRow(self.ROW_LINK, self.STATE_OK, _("Associated"), f"{ssid}  {sig}".strip())
				else:
					setRow(self.ROW_LINK, self.STATE_FAIL, _("Not associated"), "")
			else:
				if net.link:
					setRow(self.ROW_LINK, self.STATE_OK, _("Connected"), formatNetworkSpeed(net.speed) if net.speed > 0 else "")
				else:
					setRow(self.ROW_LINK, self.STATE_FAIL, _("Disconnected"), "")
			testIp()

		self.setTitle(_("Network Test – %s") % self.interface)
		adapter = networkManager.adapters.get(self.interface)
		adapterName = networkManager.getFriendlyAdapterName(self.interface)
		net = networkManager.getNetInfo(self.interface)
		isWlan = adapter.isWlan if adapter else False
		labels = [
			_("Adapter"),
			_("Wi-Fi link") if isWlan else _("LAN link"),
			_("IP address"),
			_("Gateway"),
			"Internet",
			"DNS",
		]
		glyph, color = self.STATES[self.STATE_BUSY]
		self.rows = [(glyph, label, "", "", color) for label in labels]
		reachableText = _("Reachable")  # This is done to optimize translation time.
		unreachableText = _("Unreachable")
		notAvailableText = _("N/A")
		self["list"].setList(list(self.rows))
		if adapter:
			setRow(self.ROW_ADAPTER, self.STATE_OK, self.interface, adapterName)
			testLink()
		else:
			setRow(self.ROW_ADAPTER, self.STATE_FAIL, _("Not found"), "")
			setRow(self.ROW_LINK, self.STATE_SKIP, notAvailableText, "")
			setRow(self.ROW_IP, self.STATE_SKIP, notAvailableText, "")
			testGateway()


# Global system DNS.
#
class DNSSettings(Setup):
	"""Global system DNS configuration. Uses networkManager in NetworkManager.py."""

	def __init__(self, session):
		def defaultGateway() -> list[int]:
			result = [0, 0, 0, 0]
			for interface in sorted(networkManager.adapters.keys()):
				if networkManager.adapters[interface].netInfo.up:
					connection = networkManager.activeConnection(interface)
					if connection:
						result = list(connection.gateway)
						break
			return result

		# IPv4 and IPv6 are never mixed into one list: each preset (and "custom"/
		# "dhcp-router") is {"v4": [...], "v6": [...]}, and every place that
		# builds/reorders/saves entries operates on exactly one of those two
		# lists. Which group(s) are shown/used and in what order they end up in
		# resolv.conf is entirely config.usage.dnsMode's job (see
		# NameserverFiles.save()) - never something Move Up/Down touches.
		dnsInitial = list(networkManager.nameserverConfig.servers)
		self.dnsOptions = {}
		self.dnsServersV4 = []
		self.dnsServersV6 = []
		self.dnsServerItems = []
		self.dnsServerGroups = []
		if BoxInfo and BoxInfo.getItem("DNSCrypt"):
			self.dnsOptions["dnscrypt"] = {"v4": [[127, 0, 0, 1]], "v6": []}
		fileDom = fileReadXML(resolveFilename(SCOPE_SKINS, "dnsservers.xml"), source=MODULE_NAME)
		if fileDom is not None:
			for dns in fileDom.findall("dnsserver"):
				key = dns.get("key", "")
				if not key:
					continue
				v4 = [[int(x) for x in ipv4.split(".")] for ipv4 in [x.strip() for x in (dns.get("ipv4", "") or "").split(",") if x.strip()]]
				v6 = [x.strip() for x in (dns.get("ipv6", "") or "").split(",") if x.strip()]
				if v4 or v6:
					self.dnsOptions[key] = {"v4": v4, "v6": v6}
		gateway = defaultGateway()
		self.dnsOptions["custom"] = {"v4": [gateway, [0, 0, 0, 0]], "v6": ["", ""]}
		self.dnsOptions["dhcp-router"] = {"v4": [gateway, [0, 0, 0, 0]], "v6": ["", ""]}
		if config.usage.dns.value not in self.dnsOptions:
			config.usage.dns.value = "custom"
		v4pos = 0
		v6pos = 0
		for addr in dnsInitial:
			if isinstance(addr, list) and len(addr) == 4 and v4pos < 2:
				self.dnsOptions["custom"]["v4"][v4pos] = addr
				self.dnsOptions["dhcp-router"]["v4"][v4pos] = addr
				v4pos += 1
			elif isinstance(addr, str):
				try:
					if ip_address(addr).version == 6 and v6pos < 2:
						self.dnsOptions["custom"]["v6"][v6pos] = addr
						self.dnsOptions["dhcp-router"]["v6"][v6pos] = addr
						v6pos += 1
				except ValueError:
					pass
		Setup.__init__(self, session=session, setup="DNS")
		self["key_yellow"] = StaticText()
		self["key_blue"] = StaticText()
		self["moveActions"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.keyMoveItemUp, _("Move item up")),
			"blue": (self.keyMoveItemDown, _("Move item down")),
		}, prio=0, description=_("DNS Settings Actions"))

	def createSetup(self):  # noqa
		self.dnsServerItems = []
		self.dnsServerGroups = []
		if config.usage.dns.value != "dnscrypt":
			current = self.dnsOptions[config.usage.dns.value]
			self.dnsServersV4 = current["v4"][:]
			self.dnsServersV6 = current["v6"][:]
			v4 = config.usage.dnsMode.value != 3
			v6 = config.usage.dnsMode.value != 2
			isCustom = config.usage.dns.value == "custom"
			entries = []
			if v4:
				for addr in self.dnsServersV4:
					entry = NoSave(ConfigIP(addr)) if isCustom else ReadOnly(NoSave(ConfigIP(default=addr)))
					entries.append(("v4", entry))
			if v6:
				for addr in self.dnsServersV6:
					entry = NoSave(ConfigText(default=addr, fixed_size=False)) if isCustom else ReadOnly(NoSave(ConfigText(default=addr, fixed_size=False)))
					entries.append(("v6", entry))
			for item, (group, entry) in enumerate(entries, start=1):
				name = _("Name server %d") % item
				if not isCustom:
					name = (name, 0)
				self.dnsServerItems.append(getConfigListEntry(
					name,
					entry,
					_("Enter DNS (Dynamic Name Server) %d's IP address.") % item
				))
				self.dnsServerGroups.append(group)
		Setup.createSetup(self, appendItems=self.dnsServerItems)

	# groupIndex(): how many earlier entries share this one's v4/v6 group -
	# i.e. this entry's index within its own dnsServersV4/dnsServersV6 list,
	# regardless of how the other group is currently filtered in/out.
	def groupIndex(self, index: int) -> int:
		return self.dnsServerGroups[:index].count(self.dnsServerGroups[index])

	def changedEntry(self):
		if config.usage.dns.value == "custom":
			current = self["config"].getCurrent()
			if current in self.dnsServerItems:
				index = self.dnsServerItems.index(current)
				group = self.dnsServerGroups[index]
				servers = self.dnsServersV4 if group == "v4" else self.dnsServersV6
				servers[self.groupIndex(index)] = current[1].value
		result = Setup.changedEntry(self)
		current = self["config"].getCurrent()
		canMove = current in self.dnsServerItems and config.usage.dns.value not in ("dnscrypt", "dhcp-router")
		self["moveActions"].setEnabled(canMove)
		self["key_yellow"].setText(_("Move Up") if canMove else "")
		self["key_blue"].setText(_("Move Down") if canMove else "")
		return result

	# Move only ever swaps within the same v4 or v6 list - reordering across
	# groups is meaningless (NameserverFiles.save() re-derives the v4-vs-v6
	# group order from config.usage.dnsMode at write time regardless of how
	# they're interleaved here) and used to silently corrupt the *other*,
	# currently-hidden group whenever dnsMode hid one of them.
	def moveItem(self, direction: int):
		current = self["config"].getCurrent()
		if current not in self.dnsServerItems:
			return
		index = self.dnsServerItems.index(current)
		group = self.dnsServerGroups[index]
		servers = self.dnsServersV4 if group == "v4" else self.dnsServersV6
		groupIdx = self.groupIndex(index)
		otherIdx = groupIdx + direction
		if 0 <= otherIdx < len(servers):
			servers[groupIdx], servers[otherIdx] = servers[otherIdx], servers[groupIdx]
			self.createSetup()

	def keyMoveItemUp(self):
		self.moveItem(-1)

	def keyMoveItemDown(self):
		self.moveItem(1)

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
			for val in self.dnsServersV4 + self.dnsServersV6:
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

	def writeDnsCryptToml(self):  # DNSCrypt TOML helpers.
		def insertSectionKey(lines, sectionName, key, rhs, anchorKeys, foundSet):
			def findSectionRange(lines, sectionName):
				start = None
				result = None
				for index, line in enumerate(lines):
					lineStripped = line.strip()
					if lineStripped.startswith("[") and lineStripped.endswith("]"):
						name = lineStripped.strip()[1:-1].strip()
						if start is None and name == sectionName:
							start = index + 1
							continue
						if start is not None:
							result = (start, index)
							break
				if result is None:
					result = (start, len(lines)) if start is not None else (None, None)
				return result

			token = f"{sectionName}.{key}"
			if token not in foundSet:
				start, end = findSectionRange(lines, sectionName)
				if start is not None:
					insertAt = None
					for index in range(start, end):
						lineStripped = lines[index].lstrip()
						for anchor in anchorKeys:
							if lineStripped.startswith((f"{anchor} ", f"{anchor}=", f"#{anchor} ", f"#{anchor}=")):
								insertAt = index + 1
					lines.insert(insertAt if insertAt is not None else end, f"{key} = {rhs}")
					foundSet.add(token)

		def tomlBool(val):
			return "true" if bool(val) else "false"

		def tomlInt(val, default=0):
			try:
				result = str(int(val))
			except Exception:
				result = str(int(default))
			return result

		def tomlStr(val):
			return f"\"{str(val).replace("\\", "\\\\").replace('"', '\\"')}\""

		def replaceKeyLine(line, key, newRhs, foundSet):
			lineStripped = line.lstrip()
			indent = line[:len(line) - len(lineStripped)]
			result = line
			if lineStripped.startswith((f"{key} ", f"{key}=", f"#{key} ", f"#{key}=")):
				foundSet.add(key)
				result = f"{indent}{key} = {newRhs}"
			return result

		tomlPath = "/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
		oldLines = fileReadLines(tomlPath, default=[], source=MODULE_NAME)
		if oldLines:
			found = set()
			newLines = []
			currentSection = None
			for line in oldLines:
				lineStripped = line.strip()
				if lineStripped.startswith("[") and lineStripped.endswith("]"):
					currentSection = lineStripped.strip()[1:-1].strip()
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
					for attribute, key, value in [
						("DNSCryptUI", "enabled", tomlBool(config.usage.DNSCryptUI.value)),
						(None, "listen_address", tomlStr(f"0.0.0.0:{tomlInt(config.usage.DNSCryptPort.value, 9012)}")),
						("DNSCryptUsername", "username", tomlStr(config.usage.DNSCryptUsername.value.strip())),
						("DNSCryptPassword", "password", tomlStr(config.usage.DNSCryptPassword.value.strip())),
						("DNSCryptPrivacy", "privacy_level", tomlInt(config.usage.DNSCryptPrivacy.value, 1)),
					]:
						tmpFound = set()
						replacement = replaceKeyLine(line, key, value, tmpFound)
						if key in tmpFound:
							found.add(f"monitoring_ui.{key}")
							line = replacement
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

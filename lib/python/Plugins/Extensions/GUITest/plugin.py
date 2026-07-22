# ===========================================================================
#
# GUITest  -  GUI code and skin test plugin
#
# Version Date - 18-Aug-2025
# Remember to change version number variable below!!!
#
# Repository - https://github.com/openatv/GUITest
# Coding by IanSav, jbleyel (c) 2025
#
# This plugin was originally developed for the openATV distribution of
# Enigma2.  This code is free to use and may be distributed and used on open
# sourced Enigma2 based firmware.
#
# This plugin is NOT free software, it is open source.  You are allowed to
# use and modify it so long as you attribute and acknowledge the source and
# original author.  That is, the license and original author details must be
# retained at all times.
#
# This plugin was developed and enhanced as open source software it may not
# be commercially distributed or included in any commercial software or used
# for commercial benefit.
#
# If you wish to contribute fixes or enhancements to the plugin then please
# drop me a line at IS.OzPVR (at) gmail.com.  If you wish to use this plugin
# as part of a commercial product please contact me.
#
# ===========================================================================

from os.path import isfile
from xml.etree.ElementTree import fromstring as xml_fromstring
from enigma import ePicLoad, eListboxPythonMultiContent, eListbox, eRect, eTimer, gFont, RT_HALIGN_LEFT, RT_HALIGN_CENTER, RT_VALIGN_CENTER, RT_WRAP
from skin import domScreens

from Components.ActionMap import HelpableActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.PluginComponent import plugins
from Components.ScrollLabel import ScrollLabel
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.HelpMenu import HelpableScreen
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.Directories import SCOPE_CONFIG, SCOPE_GUISKIN, SCOPE_PLUGIN, SCOPE_PLUGIN_ABSOLUTE, SCOPE_SKINS, resolveFilename
from Tools.LoadPixmap import LoadPixmap
from Tools.BoundFunction import boundFunction
from Components.MultiContent import MultiContentEntryPixmapAlphaBlend, MultiContentEntryText, MultiContentEntryProgress, MultiContentEntryRectangle
from Components.MenuList import MenuList
from Components.ConfigList import ConfigList
from Components.config import ConfigBoolean, ConfigNumber, ConfigSelection, ConfigText

PLUGIN_VERSION_NUMBER = "18-Aug-2025"

PLUGINPNG = LoadPixmap(cached=False, path=resolveFilename(SCOPE_GUISKIN, "icons/plugin.png"))


def ensureTestIncludePanels():
	if "_KeyButtons" not in domScreens:
		domScreens["_KeyButtons"] = (
			xml_fromstring("""
			<screen name="_KeyButtons">
				<panel position="0,0" size="e,e" layout="horizontal" spacing="10">
					<eLabel position="left" size="130,40" text="HELP" backgroundColor="#00333333" horizontalAlignment="center" verticalAlignment="center" />
					<eLabel position="left" size="130,40" text="TEXT" backgroundColor="#00444444" horizontalAlignment="center" verticalAlignment="center" />
					<eLabel position="right" size="130,40" text="INFO" backgroundColor="#00555555" horizontalAlignment="center" verticalAlignment="center" />
					<eLabel position="right" size="130,40" text="MENU" backgroundColor="#00666666" horizontalAlignment="center" verticalAlignment="center" />
				</panel>
			</screen>
			"""),
			""
		)


ensureTestIncludePanels()


class GUITest(Screen, HelpableScreen):
	skin = """
	<screen name="GUITest" title="GUI Test Main Menu" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<eLabel position="10,44" size="e-20,36" text="Press a number key 1–8 to open a test screen   |   OK / Red: Close" backgroundColor="#00222222" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" />
		<!-- Left column: keys 1–4 -->
		<eLabel position="50,100" size="60,52" text="1" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="118,100" size="500,52" text="eRectangle and eLabel widgets" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="50,160" size="60,52" text="2" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="118,160" size="500,52" text="Panel alignment and include panels" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="50,220" size="60,52" text="3" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="118,220" size="500,52" text="ScrollLabel widget" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="50,280" size="60,52" text="4" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="118,280" size="500,52" text="Image / Pixmap alphatest" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<!-- Right column: keys 5–8 -->
		<eLabel position="660,100" size="60,52" text="5" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="728,100" size="510,52" text="Listbox: grid and plugin list" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="660,160" size="60,52" text="6" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="728,160" size="510,52" text="eStack: variants and nesting" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="660,220" size="60,52" text="7" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="728,220" size="510,52" text="Label: alignment, scrollText, fontScale" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="660,280" size="60,52" text="8" backgroundColor="#00335577" font="Regular;28" horizontalAlignment="center" verticalAlignment="center" cornerRadius="6" />
		<eLabel position="728,280" size="510,52" text="Listbox: StringList, ConfigList, MultiContent" backgroundColor="#001a2a3a" font="Regular;22" horizontalAlignment="left" verticalAlignment="center" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""
	# 	<widget source="tests" render="Listbox" position="400,80" size="830,420" backgroundColor="MenuBackground" backgroundColorSelected="MenuSelected" enableWrapAround="1" foregroundColor="MenuText" foregroundColorSelected="MenuTextSelected" scrollbarMode="showOnDemand" transparent="0">
	# 		<convert type="TemplatedMultiContent">
	# 			{
	# 			"template":
	# 				[
	# 				MultiContentEntryText(pos = (20, 0), size = (790, 35), font = 0, flags = RT_HALIGN_LEFT | RT_VALIGN_CENTER, text = 0),
	# 				],
	# 			"fonts": [parseFont("MenuFont;25)],
	# 			"itemHeight": 35
	# 			}
	# 		</convert>
	# 	</widget>

	def __init__(self, session):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions", "NumberActions"], {
			"ok": (self.close, _("Close the GUI Test menu screen")),
			"cancel": (self.close, _("Close the GUI Test menu screen")),
			"red": (self.close, _("Close the GUI Test menu screen")),
			"1": (self.keyGUITestScreen1, _("Display GUI Test Screen 1")),
			"2": (self.keyGUITestScreen2, _("Display GUI Test Screen 2")),
			"3": (self.keyGUITestScreen3, _("Display GUI Test Screen 3")),
			"4": (self.keyGUITestScreen4, _("Display GUI Test Screen 4")),
			"5": (self.keyGUITestScreen5, _("Display GUI Test Screen 5")),
			"6": (self.keyGUITestScreen6, _("Display GUI Test Screen 6")),
			"7": (self.keyGUITestScreen7, _("Display GUI Test Screen 7")),
			"8": (self.keyGUITestScreen8, _("Display GUI Test Screen 8")),
			# "9": (self.keyGUITestScreen9, _("Display GUI Test Screen 9")),
			# "0": (self.keyGUITestScreen10, _("Display GUI Test Screen 10"))
		}, prio=0, description=_("GUI Test Actions"))
		self["key_red"] = StaticText(_("Close"))
		self["tests"] = List()
		# self["tests"].updateList(self.listThemes())
		# self["tests"].onSelectionChanged.append(self.clearDescription)

	def keyGUITestScreen1(self):
		self.session.open(GUITestScreen1)

	def keyGUITestScreen2(self):
		self.session.open(GUITestScreen2)

	def keyGUITestScreen3(self):
		self.session.open(GUITestScreen3)

	def keyGUITestScreen4(self):
		self.session.open(GUITestScreen4)

	def keyGUITestScreen5(self):
		self.session.open(GUITestScreen5)

	def keyGUITestScreen6(self):
		self.session.open(GUITestScreen6)

	def keyGUITestScreen7(self):
		self.session.open(GUITestScreen7)

	def keyGUITestScreen8(self):
		self.session.open(GUITestScreen8)


class GUITestScreenBase(Screen, HelpableScreen):
	def __init__(self, session, screenID):
		Screen.__init__(self, session)
		HelpableScreen.__init__(self)
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"cancel": (self.close, _("Close test screen %s") % screenID),
			"red": (self.close, _("Close test screen %s") % screenID)
		}, prio=0, description=_("GUI Test Screen %s Actions") % screenID)
		self["imageActions"] = HelpableActionMap(self, ["OkCancelActions", "ColorActions"], {
			"ok": (self.toggle, _("Toggle between skin and expected skin image")),
			"green": (self.toggle, _("Toggle between skin and expected skin image"))
		}, prio=0, description=_("GUI Test Screen %s Actions") % screenID)
		self["imageActions"].setEnabled(False)
		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText()
		self["image"] = Pixmap()
		self["image"].hide()
		imagePath = resolveFilename(SCOPE_PLUGIN_ABSOLUTE, f"screen{screenID}.png")
		print(f"[GUITest] DEBUG: Test screen {screenID} image '{imagePath}'.")
		self.referenceImage = None
		if isfile(imagePath):
			self.referenceImage = LoadPixmap(imagePath)
			if self.referenceImage:
				self["imageActions"].setEnabled(True)
				self["key_green"].setText(_("Show Image"))
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		if self.referenceImage:
			self["image"].instance.setPixmap(self.referenceImage)

	def toggle(self):
		if self["image"].getVisible():
			self["image"].hide()
			self["key_green"].setText(_("Show Image"))
		else:
			self["image"].show()
			self["key_green"].setText(_("Show GUI"))


class GUITestScreen1(GUITestScreenBase):
	skin = """
	<screen name="GUITestScreen1" title="GUI Test Screen 1" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,25"  font="Regular;20" transparent="1" />
		<eRectangle position="0,100" size="100,100" backgroundColor="blue" cornerRadius="10;topLeft" />
		<eRectangle position="120,100" size="100,100" backgroundColor="blue" borderColor="red" borderWidth="4" cornerRadius="10;topRight" />
		<eRectangle position="240,100" size="100,100" backgroundGradient="blue,red,horizontal" cornerRadius="10;bottomLeft" />
		<eRectangle position="360,100" size="100,100" backgroundGradient="blue,red,vertical" cornerRadius="10;bottomRight" />
		<eRectangle position="480,100" size="100,100" backgroundGradient="blue,yellow,red,horizontal" cornerRadius="10;left" />
		<eRectangle position="600,100" size="100,100" backgroundGradient="blue,yellow,red,vertical" cornerRadius="10;right" />
		<eRectangle position="720,100" size="100,100" backgroundGradient="blue,yellow,red,vertical" cornerRadius="10;top" />
		<eRectangle position="840,100" size="100,100" backgroundGradient="blue,yellow,red,vertical" cornerRadius="10;bottom" />
		<eRectangle position="0,220" size="100,100" backgroundColor="blue" borderColor="red" borderWidth="4" cornerRadius="0" />
		<eRectangle position="120,220" size="100,100" backgroundGradient="blue,red,horizontal" borderColor="red" borderWidth="4" />
		<eRectangle position="240,220" size="100,100" backgroundColor="blue" cornerRadius="50" borderColor="red" borderWidth="4" />
		<eRectangle position="360,220" size="100,100" backgroundGradient="blue,red,horizontal" borderColor="red" borderWidth="4" cornerRadius="50" />
		<eRectangle position="480,220" size="100,100" backgroundColor="blue" cornerRadius="10" borderColor="red" borderWidth="4" />
		<eRectangle position="600,220" size="100,100" backgroundGradient="blue,red,horizontal" borderColor="red" borderWidth="4" cornerRadius="10" />
		<eRectangle position="0,340" size="100,100" backgroundColor="blue" cornerRadius="0" borderColor="red" borderWidth="0" />
		<eRectangle position="120,340" size="100,100" backgroundGradient="blue,red,horizontal" borderColor="red" borderWidth="0" />
		<eRectangle position="240,340" size="100,100" backgroundColor="blue" borderColor="red" borderWidth="0" cornerRadius="50" />
		<eRectangle position="360,340" size="100,100" backgroundGradient="blue,red,horizontal" borderColor="red" borderWidth="0" cornerRadius="50" />
		<eRectangle position="480,340" size="100,100" backgroundColor="blue" borderColor="red" borderWidth="0" cornerRadius="10" />
		<eLabel position="0,460" size="100,100" text="TEST Text" backgroundColor="blue" borderColor="red" borderWidth="4" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="120,460" size="100,100" text="TEST Text" backgroundColor="blue" horizontalAlignment="center" verticalAlignment="center" widgetBorderColor="red" widgetBorderWidth="4" />
		<eLabel position="240,460" size="100,100" text="TEST Text" backgroundGradient="blue,red,horizontal" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="360,460" size="100,100" text="TEST Text" backgroundGradient="blue,yellow,red,vertical" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="480,460" size="100,100" text="TEST Text" backgroundColor="blue" cornerRadius="8" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="600,460" size="100,100" text="TEST Text" backgroundColor="blue" cornerRadius="8" horizontalAlignment="center" verticalAlignment="center" widgetBorderColor="red" widgetBorderWidth="4" />
		<eLabel position="720,460" size="100,100" text="TEST Text" backgroundColor="blue" foregroundColor="yellow" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="840,460" size="100,100" text="TEST Text" backgroundColor="blue" horizontalAlignment="center" verticalAlignment="center" />

		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "1")
		self["item1"] = Label(_("This screen demonstrates the eRectangle and eLabel widgets."))


class GUITestScreen2(GUITestScreenBase):
	skin = """
	<screen name="GUITestScreen2" title="GUI Test Screen 2" position="fill" size="1280,720" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,25" font="Regular;20" transparent="1" />

		<eRectangle position="10,70" size="e-20,200" backgroundColor="#10101010" cornerRadius="8" />
		<eLabel position="20,80" size="560,30" text="Panel horizontal / vertical alignment" backgroundColor="#00333333" horizontalAlignment="center" verticalAlignment="center" />

		<panel position="20,120" size="e-40,50" layout="horizontal" spacing="10">
			<eLabel position="left" size="140,40" text="Left" backgroundColor="#00337755" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="left" size="180,40" text="Left 2" backgroundColor="#00448866" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="center" size="220,40" text="Center" backgroundColor="#00559977" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="right" size="180,40" text="Right" backgroundColor="#0066AA88" horizontalAlignment="center" verticalAlignment="center" />
		</panel>

		<panel position="20,180" size="420,80" layout="vertical" spacing="6">
			<eLabel position="top" size="420,24" text="Top" backgroundColor="#00335577" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="center" size="420,24" text="Center" backgroundColor="#00446688" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="bottom" size="420,24" text="Bottom" backgroundColor="#00557799" horizontalAlignment="center" verticalAlignment="center" />
		</panel>

		<eRectangle position="10,290" size="e-20,300" backgroundColor="#10101010" cornerRadius="8" />
		<eLabel position="20,300" size="e-40,30" text="Relative include panel test (should render equal)" backgroundColor="#00333333" horizontalAlignment="center" verticalAlignment="center" />

		<eLabel position="20,340" size="610,30" text="A: Wrapper include panel" backgroundColor="#00335566" horizontalAlignment="center" verticalAlignment="center" />
		<eRectangle position="20,375" size="610,140" backgroundColor="#08222222" cornerRadius="8" />
		<panel position="40,420" size="570,40">
			<panel name="_KeyButtons" layout="horizontal" spacing="10" />
		</panel>

		<eLabel position="650,340" size="610,30" text="B: Inline include panel" backgroundColor="#00335566" horizontalAlignment="center" verticalAlignment="center" />
		<eRectangle position="650,375" size="610,140" backgroundColor="#08222222" cornerRadius="8" />
		<panel position="670,420" size="570,40" name="_KeyButtons" layout="horizontal" spacing="10" />

		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "2")
		self["item1"] = Label(_("This screen demonstrates panel alignment and relative include-panel behavior."))


class GUITestScreen3(GUITestScreenBase):
	skin = """
	<screen name="GUITestScreen3" title="GUI Test Screen 3" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,25"  font="Regular;20" transparent="1" />
		<!--
		<widget name="text" position="0,100" size="400,400" backgroundColor="#00333333" font="Regular;20" scrollbarMode="showOnDemand" />
		-->
		<widget name="text" position="0,100" size="1220,550" backgroundColor="#00333333" font="Console;22" scrollbarMode="showOnDemand" scrollbarScroll="byLine" />
		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" conditional="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" conditional="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "3")
		self["item1"] = Label(_("This screen demonstrates the ScrollLabel widgets."))
		self["text"] = ScrollLabel("This is some initial text.")
		self["key_yellow"] = StaticText(_("Show Size"))
		# self["key_blue"] = StaticText(_("Expand Text"))
		self["key_blue"] = StaticText()
		self["textAction"] = HelpableActionMap(self, ["ColorActions"], {
			"yellow": (self.showSize, _("Show the size information in a pop up window")),
			"blue": (self.toggleText, _("Toggle between the short and long text sample")),
		}, prio=0, description=_("GUI Test Screen %s Actions") % 3)
		self["navigationActions"] = HelpableActionMap(self, ["NavigationActions"], {
			"top": (self["text"].goTop, _("Move to first line / screen")),
			"pageUp": (self["text"].goPageUp, _("Move up a screen")),
			"up": (self["text"].goLineUp, _("Move up a line")),
			"down": (self["text"].goLineDown, _("Move down a line")),
			"pageDown": (self["text"].goPageDown, _("Move down a screen")),
			"bottom": (self["text"].goBottom, _("Move to last line / screen"))
		}, prio=0, description=_("GUI Test Screen Navigation Actions"))
		self.toggle = False

	def layoutFinished(self):
		GUITestScreenBase.layoutFinished(self)
		# self.showText(self.toggle)
		self.showBugText()

	def showSize(self):
		labelSize = self["text"].leftText.calculateSize()
		totalTextHeight = self["text"].totalTextHeight
		self.session.open(MessageBox, f"{labelSize.width()} x {labelSize.height()} | {totalTextHeight}", MessageBox.TYPE_INFO, timeout=60)

	def toggleText(self):
		self.toggle = not self.toggle
		self.showText(self.toggle)

	def showText(self, mode):
		shortText = []
		shortText.append("This is some text to test the ScrollLabel component. The more text we have the more chance that the ScrollLabel will scroll and have wrapping issues.")
		shortText.append("")
		shortText.append("This is a text line.")
		shortText.append("This is a text line.")
		shortText.append("This is a text line.")
		shortText.append("This is a text line.")
		longText = []
		longText.append("")
		longText.append("This is some some longer text to test the ScrollLabel component with a scroll bar. The more text we have the more chance that the ScrollLabel will scroll and have wrapping issues.")
		longText.append("")
		longText.append("This is a text line.")
		longText.append("This is a text line.")
		longText.append("This is a text line.")
		longText.append("This is a text line.")
		self["text"].setText("\n".join(shortText + longText) if mode else "\n".join(shortText))

	def showBugText(self):
		_text = """Python 3

 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema1 Ad1
 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema1 Ad12
-1 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema1 Ad123
-1 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema1 Ad1234

 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema12 Ad1
-1 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema12 Ad12
-1 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema12 Ad123
 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zema12 Ad1234

-1 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zeman123 Ad1
 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zeman123 Ad12
 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zeman123 Ad123
 0 azskeho, od r. 1968), rady Korejse (Panoptikum Mesta prazskeho, od r. 1987) a majora Zemana (3 pripadu majora Zemana, od r. Zeman123 Ad1234

The last line has the number 000
Line -007 (7 lines missing)
Line -006 (6 lines missing)
Line -005 (5 lines missing)
Line -004 (4 lines missing)
Line -003 (3 lines missing)
Line -002 (2 lines missing)
Line -001 (1 line missing)
Line 000 (no line missing)"""
		text = """Line1	:A
Line2	:B
LongLine3	:B
LongLongLongLine4	:B
ABCDEFGHI	J
A		B
"""

		self["text"].setText(text)


class GUITestScreen4(GUITestScreenBase):

	images = [
		"24", "32", "cmyk", "g8", "i8", "it8", "favouriteslogo"
	]

	def getImages():
		txt = ""
		for x in range(8):
			txt += '<widget name="aimage%d" position="%d,50" size="100,40" alphatest="off" scale="scale" transparent="0" zPosition="1" />' % (x, (x + 1) * 114)
		for x in range(8):
			txt += '<widget name="bimage%d" position="%d,150" size="100,40" alphatest="on" scale="scale" transparent="0" zPosition="1" />' % (x, (x + 1) * 114)
		for x in range(8):
			txt += '<widget name="cimage%d" position="%d,250" size="100,40" alphatest="blend" scale="scale" transparent="0" zPosition="1" />' % (x, (x + 1) * 114)
		return txt
	skin = """
	<screen name="GUITestScreen3" title="GUI Test Screen 3" position="fill" backgroundColor="black" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<eLabel name="layer2" position="0,40" zPosition="-10" size="1040,450" backgroundColor="#0000FFFF" />
		%s
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" conditional="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" conditional="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>""" % getImages()

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "4")
		self.toggle = False

		self.picloads = []
		for x in range(8):
			self[f"aimage{x}"] = Pixmap()
			self[f"bimage{x}"] = Pixmap()
			self[f"cimage{x}"] = Pixmap()
			self.picloads.append(ePicLoad())
			self.picloads[x].PictureData.get().append(boundFunction(self.setPictureCB, x))
			self.picloads[x].setPara((100, 40, 1, 1, False, 0, '#00000000'))

	def layoutFinished(self):
		GUITestScreenBase.layoutFinished(self)
		for x, i in enumerate(self.images):
			imagePath = resolveFilename(SCOPE_PLUGIN_ABSOLUTE, f"{i}.png")
			print(imagePath)
			self.picloads[x].startDecode(imagePath)

	def setPictureCB(self, x, picInfo=None):
		print("setPictureCB", x)
		ptr = self.picloads[x].getData()
		if ptr is not None:
			self[f"aimage{x}"].instance.setPixmap(ptr)
			self[f"aimage{x}"].show()
			self[f"bimage{x}"].instance.setPixmap(ptr)
			self[f"bimage{x}"].show()
			self[f"cimage{x}"].instance.setPixmap(ptr)
			self[f"cimage{x}"].show()


class MList(MenuList):
	def __init__(self, list, enableWrapAround=False):
		MenuList.__init__(self, list, enableWrapAround, eListboxPythonMultiContent)
		self.l.setOrientation(eListbox.orHorizontal)

		self.spacing_sides = 10
		self.iconWidth = 100
		self.iconHeight = 200
		self.itemWidth = self.iconWidth + self.spacing_sides * 2
		self.itemHeight = self.iconHeight + 20

		self.l.setItemHeight(self.itemHeight)
		self.l.setItemWidth(self.itemWidth)
		self.l.setBuildFunc(self.buildEntry)
		self.onSelectionChanged.append(self.selectionChanged)
		self.selectedIndex = 0

	def postWidgetCreate(self, instance):
		instance.setContent(self.l)
		instance.selectionChanged.get().append(self.selectionChanged)
		self.l.setSelectionClip(eRect(0, 0, 0, 0), False)

	def buildEntry(self, item_index, X=None):
		print(item_index, self.getCurrentIndex(), self.selectedIndex)
		res = [None]
		selected = self.selectedIndex == item_index
		if selected:
			print(selected)
			res.append(MultiContentEntryRectangle(
				pos=(self.spacing_sides - 3, self.spacing_sides - 3), size=(self.iconWidth + 6, self.iconHeight + 6),
				cornerRadius=8,
				borderWidth=3, borderColor=0x37772b,
				backgroundColor=0x37772b, backgroundColorSelected=0x37772b))

		res.append(MultiContentEntryRectangle(
				pos=(self.spacing_sides, self.spacing_sides), size=(self.iconWidth, self.iconHeight),
				cornerRadius=8,
				backgroundColor=0x00222222, backgroundColorSelected=0x00222222))

		return res

	def selectionChanged(self):
		self.selectedIndex = self.l.getCurrentSelectionIndex()


class GUITestScreen5(GUITestScreenBase):

	skin = """
	<screen name="GUITestScreen5" title="GUITestScreen5" position="fill" backgroundColor="black" flags="wfNoBorder" resolution="1280,720" transparent="0">

		<!--<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />-->
		<eLabel name="layer2" position="0,0" size="e,e" zPosition="-10" backgroundColor="#00888888" />

		<widget source="glist" position="10,50" size="e-320,e-300" selectionZoomSize="154,135,1" borderWidth="0" borderColor="green" scrollbarLength="auto" itemGradientSelected="red,blue,horizontal,1" itemGradient="blue,green,vertical,1" itemCornerRadius="10" itemAlignment="center" cornerRadius="10" spacingColor="yellow" itemSpacing="10,10" render="Listbox" scrollbarOffset="0" scrollbarBorderWidth="2" scrollbarBorderColor="red" scrollbarMode="showAlways" listOrientation="grid" scrollbarScroll="byLine" scrollbarForegroundColor="blue" transparent="0">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(26, 9), size=(102,42),  backgroundColor=0x00000000, backgroundColorSelected=0x0000FF00, cornerRadius=8),
						MultiContentEntryPixmapAlphaBlend(pos=(27, 10), size=(100, 40), png=2, flags=BT_SCALE),
						MultiContentEntryText(pos=(1, 54), size=(152, 45), font=0, flags=RT_VALIGN_CENTER | RT_HALIGN_CENTER | RT_WRAP | RT_BLEND, text=0, backcolor=0x00000000, backcolor_sel=0x000000CC, cornerRadius=8),
					],
					"fonts": [gFont("Regular", 18),gFont("Regular", 14)],
					"itemWidth" : 152,
					"itemHeight" : 105
				}
			</convert>
		</widget>
		<widget source="hlist" position="e-300,390" size="280,250" selectionZoomSize="170,150,1" borderWidth="0" borderColor="green" scrollbarLength="auto" itemGradientSelected="red,blue,horizontal,1" itemGradient="blue,green,vertical,1" itemCornerRadius="10" itemAlignment="center" cornerRadius="10" spacingColor="yellow" itemSpacing="8,8" render="Listbox" scrollbarOffset="0" scrollbarBorderWidth="2" scrollbarBorderColor="red" scrollbarMode="showAlways" listOrientation="horizontal" scrollbarScroll="byLine" scrollbarForegroundColor="blue" transparent="1" enableWrapAround="1">
			<convert type="TemplatedMultiContent">
				{
			"template": [
				MultiContentEntryRectangle(pos=(0, 0), size=(160,140), backgroundColor=0x00003366, backgroundColorSelected=0x0033772b, cornerRadius=8, borderWidth=2, borderColor=0x0033772b),
				MultiContentEntryRectangle(pos=(2, 2), size=(156,136), backgroundColor=0x00222222, backgroundColorSelected=0x002f2f2f, cornerRadius=8),
				MultiContentEntryPixmapAlphaBlend(pos=(8, 8), size=(144, 72), png=2, cornerRadius=6, flags=BT_SCALE),
				MultiContentEntryText(pos=(8, 84), size=(144, 48), font=0, flags=RT_VALIGN_CENTER | RT_HALIGN_CENTER | RT_WRAP | RT_BLEND, text=0, backcolor=0x00000000, backcolor_sel=0x000000CC),
			],
					"fonts": [gFont("Regular", 18),gFont("Regular", 14)],
					"itemWidth" : 160,
					"itemHeight" : 140
				}
			</convert>
		</widget>
		<widget source="vlist" position="e-300,50" size="280,320" selectionZoomSize="160,120,1" borderWidth="0" borderColor="green" scrollbarLength="auto" itemGradientSelected="red,blue,horizontal,1" itemGradient="blue,green,vertical,1" itemCornerRadius="10" itemAlignment="center" cornerRadius="10" spacingColor="yellow" itemSpacing="8,8" render="Listbox" scrollbarOffset="0" scrollbarBorderWidth="2" scrollbarBorderColor="red" scrollbarMode="showAlways" listOrientation="vertical" scrollbarScroll="byLine" scrollbarForegroundColor="blue" transparent="1" enableWrapAround="1">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(26, 8), size=(100,44), backgroundColor=0x00000000, backgroundColorSelected=0x0000FF00, cornerRadius=10),
						MultiContentEntryPixmapAlphaBlend(pos=(27, 10), size=(100, 40), png=2, flags=BT_SCALE),
						MultiContentEntryText(pos=(1, 58), size=(152, 42), font=0, flags=RT_VALIGN_CENTER | RT_HALIGN_CENTER | RT_WRAP | RT_BLEND, text=0, backcolor=0x00000000, backcolor_sel=0x000000CC, cornerRadius=8),
					],
					"fonts": [gFont("Regular", 18),gFont("Regular", 14)],
					"itemWidth" : 152,
					"itemHeight" : 105
				}
			</convert>
		</widget>
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" conditional="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" conditional="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "5")
		self.toggle = False
		self["glist"] = List([])
		self["hlist"] = List([])
		self["vlist"] = List([])
#		self["mlist"] = MList([])
		self["backdrop"] = Pixmap()

	def layoutFinished(self):
		GUITestScreenBase.layoutFinished(self)

		self.pluginlist = plugins.getPlugins(PluginDescriptor.WHERE_PLUGINMENU)
		self.list = []
		i = 10
		for plugin in self.pluginlist:
			plugin.listweight = i
			self.list.append(plugin)
			i += 10

		menu_list = []
		locked = (10,)

		for i, plugin in enumerate(self.list[:18]):
			if i in locked:
				menu_list.append((None, plugin.description, plugin.icon or PLUGINPNG, "", 50))
			else:
				menu_list.append((str(i), plugin.description, plugin.icon or PLUGINPNG, "", 50))

		self["glist"].updateList(menu_list)
		self["hlist"].updateList(menu_list)
		self["vlist"].updateList(menu_list)
		#self["mlist"].l.setList([(0, "A",), (1, "A",), (2, "A",)])


class GUITestScreen6(GUITestScreenBase):

	skin = """
	<screen name="GUITestScreen6" title="GUI Test Screen 6 (eStack)" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,25" font="Regular;20" transparent="1" />

		<!-- Horizontal stack, mixed left/right/center alignment. -->
		<eStack position="10,80" size="e-20,70" layout="horizontal" spacing="10">
			<eLabel position="left" size="180,60" text="H Left" backgroundColor="#00336699" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="left" size="220,60" text="H Left 2" backgroundColor="#004466AA" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="center" size="220,60" text="H Center" backgroundColor="#005577BB" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="right" size="180,60" text="H Right" backgroundColor="#006688CC" horizontalAlignment="center" verticalAlignment="center" />
		</eStack>

		<!-- Vertical stack, mixed top/bottom/center alignment. -->
		<eStack position="10,170" size="420,420" layout="vertical" spacing="8">
			<eLabel position="top" size="400,50" text="V Top" backgroundColor="#00337755" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="top" size="400,50" text="V Top 2" backgroundColor="#00448866" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="center" size="400,50" text="V Center" backgroundColor="#00559977" horizontalAlignment="center" verticalAlignment="center" />
			<eLabel position="bottom" size="400,50" text="V Bottom" backgroundColor="#0066AA88" horizontalAlignment="center" verticalAlignment="center" />
		</eStack>

		<!-- Nested stack test: vertical root, horizontal rows. -->
		<eStack position="450,170" size="e-460,420" layout="vertical" spacing="10">
			<eLabel position="top" size="e-20,38" text="Nested eStack rows" backgroundColor="#00333333" horizontalAlignment="center" verticalAlignment="center" />
			<eStack position="top" size="e-20,100" layout="horizontal" spacing="12">
				<eRectangle position="left" size="120,90" backgroundColor="#00993333" cornerRadius="8" />
				<eRectangle position="left" size="120,90" backgroundColor="#00339933" cornerRadius="8" />
				<eRectangle position="left" size="120,90" backgroundColor="#00333399" cornerRadius="8" />
				<eRectangle position="right" size="120,90" backgroundColor="#00999933" cornerRadius="8" />
			</eStack>
			<eStack position="top" size="e-20,100" layout="horizontal" spacing="12">
				<eLabel position="left" size="200,90" text="row2-left" backgroundColor="#004444AA" horizontalAlignment="center" verticalAlignment="center" />
				<eLabel position="center" size="200,90" text="row2-center" backgroundColor="#005555BB" horizontalAlignment="center" verticalAlignment="center" />
				<eLabel position="right" size="200,90" text="row2-right" backgroundColor="#006666CC" horizontalAlignment="center" verticalAlignment="center" />
			</eStack>
			<eLabel position="bottom" size="e-20,120" text="Bottom block" backgroundColor="#003A3A3A" horizontalAlignment="center" verticalAlignment="center" />
		</eStack>

		<eLabel position="10,605" size="e-20,25" text="Dynamic eStack test (auto cycle every 2s)" backgroundColor="#00333333" horizontalAlignment="center" verticalAlignment="center" />
		<eStack position="10,635" size="e-20,40" layout="horizontal" spacing="10">
			<widget name="dyn_left" position="left" size="220,40" backgroundColor="#00445588" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" />
			<widget name="dyn_mid" position="left" size="260,40" backgroundColor="#00556699" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" />
			<widget name="dyn_right" position="right" size="220,40" backgroundColor="#006677AA" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" />
		</eStack>

		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "6")
		self["item1"] = Label(_("This screen demonstrates multiple eStack variants and nesting."))
		self["dyn_left"] = Label("dyn-left")
		self["dyn_mid"] = Label("dyn-mid")
		self["dyn_right"] = Label("dyn-right")
		self._dynPhase = -1
		self._dynTimer = eTimer()
		self._dynTimer.callback.append(self._updateDynamicStack)
		self._dynTimer.start(2000, False)
		self.onClose.append(self._stopDynamicStackTimer)
		self._updateDynamicStack()

	def _updateDynamicStack(self):
		self._dynPhase = (self._dynPhase + 1) % 5
		if self._dynPhase == 0:
			self["dyn_left"].setText("left + mid + right")
			self["dyn_mid"].setText("all visible")
			self["dyn_right"].setText("phase 0")
			self["dyn_left"].show()
			self["dyn_mid"].show()
			self["dyn_right"].show()
		elif self._dynPhase == 1:
			self["dyn_left"].setText("left")
			self["dyn_mid"].setText("mid")
			self["dyn_right"].setText("right")
			self["dyn_left"].show()
			self["dyn_mid"].hide()
			self["dyn_right"].show()
		elif self._dynPhase == 2:
			self["dyn_left"].setText("left")
			self["dyn_mid"].setText("mid")
			self["dyn_right"].setText("right")
			self["dyn_left"].hide()
			self["dyn_mid"].show()
			self["dyn_right"].show()
		elif self._dynPhase == 3:
			self["dyn_left"].setText("left")
			self["dyn_mid"].setText("mid")
			self["dyn_right"].setText("right")
			self["dyn_left"].show()
			self["dyn_mid"].show()
			self["dyn_right"].hide()
		else:
			self["dyn_left"].setText("L")
			self["dyn_mid"].setText("LONG mid text: dynamic reflow / spacing / visibility stress test @ phase 4")
			self["dyn_right"].setText("R")
			self["dyn_left"].show()
			self["dyn_mid"].show()
			self["dyn_right"].show()

	def _stopDynamicStackTimer(self):
		if self._dynTimer is not None:
			self._dynTimer.stop()


class GUITestScreen7(GUITestScreenBase):
	skin = """
	<screen name="GUITestScreen7" title="GUI Test Screen 7 (Label)" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,22" font="Regular;20" transparent="1" />

		<!-- ── Alignment  horizontalAlignment × verticalAlignment ── -->
		<eLabel position="10,60" size="1260,20" text="Alignment  (horizontalAlignment × verticalAlignment)" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<!-- row: verticalAlignment top -->
		<eLabel position="10,82"  size="305,55" text="left + top"                          backgroundColor="#00224455" horizontalAlignment="left"   verticalAlignment="top"    />
		<eLabel position="320,82" size="305,55" text="center + top"                        backgroundColor="#00334455" horizontalAlignment="center" verticalAlignment="top"    />
		<eLabel position="630,82" size="305,55" text="right + top"                         backgroundColor="#00444455" horizontalAlignment="right"  verticalAlignment="top"    />
		<eLabel position="940,82" size="305,55" text="block + top — justified text sample" backgroundColor="#00554455" horizontalAlignment="block"  verticalAlignment="top"    />
		<!-- row: verticalAlignment center -->
		<eLabel position="10,140"  size="305,55" text="left + center"                          backgroundColor="#00225566" horizontalAlignment="left"   verticalAlignment="center" />
		<eLabel position="320,140" size="305,55" text="center + center"                        backgroundColor="#00335566" horizontalAlignment="center" verticalAlignment="center" />
		<eLabel position="630,140" size="305,55" text="right + center"                         backgroundColor="#00445566" horizontalAlignment="right"  verticalAlignment="center" />
		<eLabel position="940,140" size="305,55" text="block + center — justified text sample" backgroundColor="#00555566" horizontalAlignment="block"  verticalAlignment="center" />
		<!-- row: verticalAlignment bottom -->
		<eLabel position="10,198"  size="305,55" text="left + bottom"                          backgroundColor="#00226677" horizontalAlignment="left"   verticalAlignment="bottom" />
		<eLabel position="320,198" size="305,55" text="center + bottom"                        backgroundColor="#00336677" horizontalAlignment="center" verticalAlignment="bottom" />
		<eLabel position="630,198" size="305,55" text="right + bottom"                         backgroundColor="#00446677" horizontalAlignment="right"  verticalAlignment="bottom" />
		<eLabel position="940,198" size="305,55" text="block + bottom — justified text sample" backgroundColor="#00556677" horizontalAlignment="block"  verticalAlignment="bottom" />

		<!-- ── scrollText  direction, mode, stepDelay, stepSize, startDelay, endDelay ── -->
		<eLabel position="10,264" size="620,20" text="scrollText (horizontal)" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<widget name="scroll1" position="10,286" size="620,32" font="Regular;22" backgroundColor="#00223344" scrollText="direction=left,stepDelay=40,stepSize=2" />
		<widget name="scroll2" position="10,322" size="620,32" font="Regular;22" backgroundColor="#00334455" scrollText="direction=left,stepDelay=20,stepSize=3,mode=bounce" />
		<widget name="scroll3" position="10,358" size="620,32" font="Regular;22" backgroundColor="#00445566" scrollText="direction=left,stepDelay=15,stepSize=4,mode=roll" />

		<!-- ── scrollText direction=up (vertical scroll) ── -->
		<eLabel position="640,264" size="630,20" text="scrollText direction=up (vertical)" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<widget name="scroll_up" position="640,286" size="630,388" font="Regular;20" backgroundColor="#00223344" scrollText="direction=up,stepDelay=40,stepSize=1" />

		<!-- ── fontScale  size:X  /  width:X   (X = minimum in px) ── -->
		<eLabel position="10,402" size="620,20" text="fontScale" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="10,425" size="620,40" text="fontScale=&quot;size:18&quot;  — shrinks to fit, minimum 18 px font size ................................................................"  backgroundColor="#00332233" font="Regular;26" fontScale="size;18"  horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="100" />
		<eLabel position="10,469" size="620,40" text="fontScale=&quot;size:20&quot;  — shrinks to fit, minimum 20 px font size ................................"  backgroundColor="#00332244" font="Regular;26" fontScale="size;20"  horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="101" />
		<eLabel position="10,513" size="620,40" text="fontScale=&quot;size:24&quot;  — shrinks to fit, minimum 24 px font size ................................"  backgroundColor="#00332255" font="Regular;26" fontScale="size;24"  horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="102" />
		<eLabel position="10,557" size="620,40" text="fontScale=&quot;width:24&quot; — width-based scaling, minimum 22 px ................................"        backgroundColor="#00332266" font="Regular;26" fontScale="width;22" horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="103" />
		<eLabel position="10,601" size="620,40" text="fontScale=&quot;width:20&quot; — width-based scaling, minimum 20 px ................................"        backgroundColor="#00332266" font="Regular;26" fontScale="width;20" horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="103" />
		<eLabel position="10,645" size="620,40" text="fontScale=&quot;none&quot; — show the original in 26px width"        backgroundColor="#00332266" font="Regular;26" horizontalAlignment="left" verticalAlignment="center" noWrap="1" tag="104" />

		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "7")
		self["item1"] = Label(_("This screen demonstrates Label alignment, scrollText and fontScale."))
		self["scroll1"] = Label(_("scrollText direction=left — this text scrolls horizontally when it does not fit into the available widget width (stepDelay=40, stepSize=2)."))
		self["scroll2"] = Label(_("scrollText mode=bounce — the quick brown fox jumps over the lazy dog and then bounces back."))
		self["scroll3"] = Label(_("scrollText mode=roll — the quick brown fox jumps over the lazy dog in a continuous roll."))
		self["scroll_up"] = Label(_(
			"Line 1 — The quick brown fox jumps over the lazy dog.\n"
			"Line 2 — Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n"
			"Line 3 — Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
			"Line 4 — Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.\n"
			"Line 5 — Duis aute irure dolor in reprehenderit in voluptate velit esse cillum.\n"
			"Line 6 — Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia.\n"
			"Line 7 — Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit.\n"
			"Line 8 — Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet.\n"
			"Line 9 — Ut labore et dolore magnam aliquam quaerat voluptatem accedunt.\n"
			"Line 10 — Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse.\n"
			"Line 11 — At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis.\n"
			"Line 12 — Nam libero tempore cum soluta nobis eligendi optio cumque nihil impedit.\n"
			"Line 13 — Temporibus autem quibusdam et aut officiis debitis rerum necessitatibus.\n"
			"Line 14 — Itaque earum rerum hic tenetur a sapiente delectus ut aut reiciendis.\n"
			"Line 15 — Quis nostrum exercitationem ullam corporis suscipit laboriosam nisi.\n"
			"Line 16 — Similique sunt in culpa qui officia deserunt mollitia animi id est laborum.\n"
			"Line 17 — Sed perspiciatis unde omnis iste natus error sit voluptatem accusantium.\n"
			"Line 18 — Totam rem aperiam eaque ipsa quae ab illo inventore veritatis et quasi.\n"
			"Line 19 — Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit.\n"
			"Line 20 — End of scroll test — text restarts from the bottom."
		))


class GUITestScreen8(GUITestScreenBase):
	_BASE_NAMES = ["stringlist", "configlist", "vlist", "glist"]

	_STRING_ITEMS = [
		("String item 1 — short", None),
		("String item 2 — This text is long enough to need horizontal scrolling in the listbox widget", None),
		("String item 3 — The quick brown fox jumps over the lazy dog and keeps running far into the distance", None),
		("String item 4 — medium length text for the stringlist", None),
		("String item 5 — Another long entry: Lorem ipsum dolor sit amet consectetur adipiscing elit", None),
		("String item 6 — short again", None),
		("String item 7 — moderately long item with some extra text appended at the end of the line", None),
		("String item 8 — the longest item in this list to really stress test the scrollText feature in enigma2 listbox", None),
		("String item 9 — normal item text here", None),
		("String item 10 — final entry, also quite long to push horizontal scroll to its absolute limit in the widget", None),
	]

	skin = """
	<screen name="GUITestScreen8" title="GUI Test Screen 8 (Listbox)" position="fill" backgroundColor="#00000000" flags="wfNoBorder" resolution="1280,720" transparent="0">
		<widget source="Title" render="Label" position="0,0" size="e,35" font="Regular;25" noWrap="1" transparent="1" verticalAlignment="center" />
		<widget name="item1" position="10,35" size="e-20,22" font="Regular;18" transparent="1" />

		<!-- top row headers -->
		<eLabel position="10,60"  size="615,20" text="StringList" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="645,60" size="615,20" text="ConfigList" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />

		<!-- top lists (Satz 1) -->
		<widget name="stringlist1" position="10,82"  size="615,278" backgroundColor="#001a1a2e" backgroundColorSelected="#00223366" scrollbarMode="showOnDemand" scrollbarWidth="8" scrollText="direction=left,stepDelay=100,startDelay=0,endDelay=0,repeat=-1,stepSize=2,mode=roll" />
		<widget name="stringlist2" position="10,82"  size="615,278" backgroundColor="#001a1a2e" backgroundColorSelected="#00223366" scrollbarMode="showOnDemand" scrollbarWidth="8" fontScale="size;18" />
		<widget name="configlist1" position="645,82" size="615,278" backgroundColor="#001a2e1a" backgroundColorSelected="#00225522" scrollbarMode="showOnDemand" scrollbarWidth="8" scrollText="direction=left,stepDelay=100,startDelay=0,endDelay=0,repeat=-1,stepSize=2,mode=roll" />
		<widget name="configlist2" position="645,82" size="615,278" backgroundColor="#001a2e1a" backgroundColorSelected="#00225522" scrollbarMode="showOnDemand" scrollbarWidth="8" fontScale="size;18" />

		<!-- bottom row headers -->
		<eLabel position="10,368"  size="615,20" text="Vertical MultiContent" backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />
		<eLabel position="645,368" size="615,20" text="Grid MultiContent"     backgroundColor="#00222222" font="Regular;15" horizontalAlignment="left" verticalAlignment="center" />

		<!-- bottom lists: TemplatedMultiContent (Satz 1) -->
		<widget source="vlist1" render="Listbox" position="10,390" size="615,265" scrollbarMode="showOnDemand" scrollbarWidth="8" scrollText="direction=left,stepDelay=100,startDelay=0,endDelay=0,repeat=-1,stepSize=2,mode=roll">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(0, 0), size=(596, 38), backgroundColor=0x00334455, backgroundColorSelected=0x00556688),
						MultiContentEntryText(pos=(6, 0), size=(578, 38), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER | 1024, text=0),
					],
					"fonts": [gFont("Regular", 22)],
					"itemHeight": 38
				}
			</convert>
		</widget>
		<widget source="vlist2" render="Listbox" position="10,390" size="615,265" scrollbarMode="showOnDemand" scrollbarWidth="8">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(0, 0), size=(596, 38), backgroundColor=0x00334455, backgroundColorSelected=0x00556688),
						MultiContentEntryText(pos=(6, 0), size=(578, 38), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER | 1024, text=0),
					],
					"fonts": [gFont("Regular", 22)],
					"itemHeight": 38
				}
			</convert>
		</widget>
		<widget source="glist1" render="Listbox" position="645,390" size="615,265" listOrientation="grid" scrollbarMode="showOnDemand" scrollbarWidth="8" scrollText="direction=left,stepDelay=100,startDelay=0,endDelay=0,repeat=-1,stepSize=2,mode=roll">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(3, 3), size=(124, 74), backgroundColor=0x00334466, backgroundColorSelected=0x00556699, cornerRadius=8),
						MultiContentEntryText(pos=(4, 43), size=(122, 34), font=0, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER | 1024, text=0),
					],
					"fonts": [gFont("Regular", 16)],
					"itemWidth": 130,
					"itemHeight": 80
				}
			</convert>
		</widget>
		<widget source="glist2" render="Listbox" position="645,390" size="615,265" listOrientation="grid" scrollbarMode="showOnDemand" scrollbarWidth="8">
			<convert type="TemplatedMultiContent">
				{
					"template": [
						MultiContentEntryRectangle(pos=(3, 3), size=(124, 74), backgroundColor=0x00334466, backgroundColorSelected=0x00556699, cornerRadius=8),
						MultiContentEntryText(pos=(4, 43), size=(122, 34), font=0, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER | 1024, text=0),
					],
					"fonts": [gFont("Regular", 16)],
					"itemWidth": 130,
					"itemHeight": 80
				}
			</convert>
		</widget>

		<widget name="image" position="0,0" size="e,e" alphatest="off" scale="scale" transparent="0" zPosition="+1" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" zPosition="+2">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	_CONFIG_ITEMS = [
		("Short option — Boolean", ConfigBoolean(default=True)),
		("A longer config label that tests horizontal scrolling of configuration entries in the listbox", ConfigBoolean(default=False)),
		("Text input field", ConfigText(default="Default text value")),
		("A very long text configuration label: the quick brown fox jumps over the lazy dog", ConfigText(default="More text")),
		("Number value (0–999)", ConfigNumber(default=42)),
		("Selection setting", ConfigSelection(default="b", choices=[("a", "Alpha"), ("b", "Beta"), ("c", "Gamma"), ("d", "Delta — a very long option name to test")])),
		("Another long configuration entry label for testing horizontal scrolling of config items", ConfigNumber(default=0)),
		("Boolean toggle at the bottom", ConfigBoolean(default=True)),
	]

	_VERT_ITEMS = [
		("Vert item 1 — short",),
		("Vert item 2 — This is a longer text for testing scrollText in the vertical multicontent list",),
		("Vert item 3 — The quick brown fox jumps over the lazy dog and keeps on running far away",),
		("Vert item 4 — medium length multicontent entry text",),
		("Vert item 5 — A very long multicontent text entry to push horizontal scrollText to its absolute limit",),
		("Vert item 6 — short entry here",),
		("Vert item 7 — moderately long entry for the vertical multicontent list widget test",),
		("Vert item 8 — Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor",),
	]

	def __init__(self, session):
		GUITestScreenBase.__init__(self, session, "8")
		self["item1"] = Label(f"Focus: {self._BASE_NAMES[0]}  |  1-4: Focus  |  5: Variant 1/2")
		self["stringlist1"] = MenuList(self._STRING_ITEMS, enableWrapAround=True)
		self["stringlist2"] = MenuList(self._STRING_ITEMS, enableWrapAround=True)
		self["configlist1"] = ConfigList(self._CONFIG_ITEMS)
		self["configlist2"] = ConfigList(self._CONFIG_ITEMS)
		self["vlist1"] = List(self._VERT_ITEMS)
		self["vlist2"] = List(self._VERT_ITEMS)
		self["glist1"] = List([(f"Grid\nItem {i + 1}",) for i in range(12)])
		self["glist2"] = List([(f"Grid\nItem {i + 1}",) for i in range(12)])
		self._focused = 0
		self._variant = 1
		self._lb = {}
		self["numActions"] = HelpableActionMap(self, ["NumberActions"], {
			"1": (lambda: self._setFocus(0), _("Focus StringList")),
			"2": (lambda: self._setFocus(1), _("Focus ConfigList")),
			"3": (lambda: self._setFocus(2), _("Focus Vertical MultiContent")),
			"4": (lambda: self._setFocus(3), _("Focus Grid MultiContent")),
			"5": (self._toggleVariant, _("Toggle between variant 1 and variant 2")),
		}, prio=0, description=_("GUI Test Screen 8 Actions"))
		self["navActions"] = HelpableActionMap(self, ["NavigationActions"], {
			"up": (self._navUp, _("Move selection up")),
			"down": (self._navDown, _("Move selection down")),
			"pageUp": (self._navPageUp, _("Move selection page up")),
			"pageDown": (self._navPageDown, _("Move selection page down")),
		}, prio=0, description=_("GUI Test Screen 8 Navigation"))

	def layoutFinished(self):
		GUITestScreenBase.layoutFinished(self)
		for suffix in ("1", "2"):
			self[f"stringlist{suffix}"].enableAutoNavigation(False)
			self[f"configlist{suffix}"].enableAutoNavigation(False)
			self[f"glist{suffix}"].enableAutoNavigation(False)
			self[f"vlist{suffix}"].enableAutoNavigation(False)
			# GUIComponent-based: .instance is the eListbox directly
			self._lb[f"stringlist{suffix}"] = self[f"stringlist{suffix}"].instance
			self._lb[f"configlist{suffix}"] = self[f"configlist{suffix}"].instance
			# Source-based: List → TemplatedMultiContent (converter) → Listbox (renderer)
			for base in ("vlist", "glist"):
				key = f"{base}{suffix}"
				converter = self[key].downstream_elements
				renderer = converter[0].downstream_elements if converter else []
				self._lb[key] = renderer[0].instance if renderer else None
		# Variant 2 initial verstecken
		self["stringlist2"].hide()
		self["configlist2"].hide()
		if self._lb.get("vlist2"):
			self._lb["vlist2"].hide()
		if self._lb.get("glist2"):
			self._lb["glist2"].hide()
		self._updateFocus()

	def _setFocus(self, idx):
		self._focused = idx
		self._updateFocus()

	def _toggleVariant(self):
		hide_suffix = str(self._variant)
		self._variant = 2 if self._variant == 1 else 1
		show_suffix = str(self._variant)
		self["stringlist" + hide_suffix].hide()
		self["configlist" + hide_suffix].hide()
		if self._lb.get("vlist" + hide_suffix):
			self._lb["vlist" + hide_suffix].hide()
		if self._lb.get("glist" + hide_suffix):
			self._lb["glist" + hide_suffix].hide()
		self["stringlist" + show_suffix].show()
		self["configlist" + show_suffix].show()
		if self._lb.get("vlist" + show_suffix):
			self._lb["vlist" + show_suffix].show()
		if self._lb.get("glist" + show_suffix):
			self._lb["glist" + show_suffix].show()
		self._updateFocus()

	def _updateFocus(self):
		for base in self._BASE_NAMES:
			for suffix in ("1", "2"):
				inst = self._lb.get(f"{base}{suffix}")
				if inst:
					inst.setSelectionEnable(False)
		inst = self._lb.get(f"{self._BASE_NAMES[self._focused]}{self._variant}")
		if inst:
			inst.setSelectionEnable(True)
		self["item1"].setText(f"Focus: {self._BASE_NAMES[self._focused]}  |  1-4: Focus  |  5: Variant {self._variant}")

	def _nav(self, direction):
		inst = self._lb.get(f"{self._BASE_NAMES[self._focused]}{self._variant}")
		if inst:
			inst.moveSelection(direction)

	def _navUp(self):
		self._nav(eListbox.moveUp)

	def _navDown(self):
		self._nav(eListbox.moveDown)

	def _navPageUp(self):
		self._nav(eListbox.pageUp)

	def _navPageDown(self):
		self._nav(eListbox.pageDown)


def main(session, **kwargs):
	session.open(GUITest)


def startFromMainMenu(menuid, **kwargs):
	if menuid == "mainmenu":  # Starting from main menu.
		return [(_("GUITest"), main, "guitest", 1)]
	return []


def Plugins(**kwargs):
	return [
		PluginDescriptor(name=_("GUITest"), description=_("Plugin to test the functionality of the GUI code. (Version %s)") % PLUGIN_VERSION_NUMBER, icon="GUITest.png", where=[PluginDescriptor.WHERE_PLUGINMENU], fnc=main),
		PluginDescriptor(name=_("GUITest"), description=_("Plugin to test the functionality of the GUI code. (Version %s)") % PLUGIN_VERSION_NUMBER, icon="GUITest.png", where=[PluginDescriptor.WHERE_MENU], fnc=startFromMainMenu)
	]

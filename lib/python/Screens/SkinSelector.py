from os import walk
from os.path import dirname, exists, join as pathjoin, isfile
from enigma import eEnv, eLabel, ePicLoad, eSize
from Components.ActionMap import NumberActionMap
from Components.config import config, ConfigSelection
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import BoxInfo
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import TryQuitMainloop
from Tools.Directories import resolveFilename, SCOPE_GUISKIN


class SkinSetup(Setup):

	DISPLAYSKINS = {
		"skin_display.xml": _("< Default >"),
		"skin_display_picon.xml": _("< Default with Picon >"),
		"skin_display_usr.xml": _("< User Skin >"),
		"skin_display_alternate.xml": _("< Alternate Skin >")
	}
	OSDSKINS = {
		"skin.xml": _("< Default >"),
	}

	ICONS = {
		"skin.xml": "prev.png",
		"skin_display.xml": "prev.png",
		"skin_display_picon.xml": "piconprev.png",
		"skin_display_usr.xml": "userskin.png",
		"skin_display_alternate.xml": "alternate.png"
	}

	METRIX_MYSKIN = "MetrixHD/skin.MySkin.xml"
	skinlist = []

	osdRoot = pathjoin(eEnv.resolve("${datadir}"), "enigma2")
	displayRoot = pathjoin(eEnv.resolve("${datadir}"), "enigma2/display/")

	def __init__(self, session):
		self.skinitems = []
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.showPic)
		self.previewPath = ""
		self.osdSkins = ConfigSelection(choices=[], default=None)
		self.displaySkins = ConfigSelection(choices=[], default=None) if BoxInfo.getItem("LCDSKINSetup") else None
		Setup.__init__(self, session, "SkinSetup")
		self.setupImage = None
#		self.title = _("Skin setup")
		if "setupimage" not in self:
			self["setupimage"] = Pixmap()

	def layoutFinished(self):
		self.picload.setPara((self["setupimage"].instance.size().width(), self["setupimage"].instance.size().height(), 1, 1, False, 1, "#00000000"))
		Setup.layoutFinished(self)
		self.createItems()
		self.createItems()

	def createItems(self):
		osdSkinSelected = config.skin.primary_skin.value
		osdSkinSelected = dirname(osdSkinSelected) if "/" in osdSkinSelected else osdSkinSelected
		displaySkinSelected = config.skin.display_skin.value
		displaySkinSelected = dirname(displaySkinSelected) if "/" in displaySkinSelected else displaySkinSelected
		self.skinitems = []
		choices = []

		for skin in self.OSDSKINS.keys():
			if exists(pathjoin(self.osdRoot, skin)):
				choices.append((skin, self.OSDSKINS[skin]))

		for root, dirs, files in walk(self.osdRoot, followlinks=True):
			for subdir in dirs:
				if subdir == "skin_default":
					continue
				if exists(pathjoin(root, subdir, "skin.xml")):
					choices.append((subdir, subdir))

		self.osdSkins.setChoices(choices=choices, default=osdSkinSelected)
		text = _("Select Skin")
		textWidth = self["config"].l.calculateEntryTextSize(text, False).width()
		leftOffset = self["config"].l.getEntryLeftOffset()
		self.skinitems.append(("Header",))
		self.skinitems.append((text, self.osdSkins, _("Choose the OSD Skin and press GREEN to activate the skin.")))
		self.skinitems.append(((textWidth, leftOffset, 1, 2),))
		if self.displaySkins:
			choices = []
			self.skinitems.append(("**************************",))

			for skin in self.DISPLAYSKINS.keys():
				if exists(pathjoin(self.displayRoot, skin)):
					choices.append((skin, self.DISPLAYSKINS[skin]))

			for root, dirs, files in walk(self.displayRoot, followlinks=True):
				for subdir in dirs:
					if subdir == "skin_default":
						continue
					if exists(pathjoin(root, subdir, "skin_display.xml")):
						choices.append((subdir, subdir))

			self.displaySkins.setChoices(choices=choices, default=displaySkinSelected)
			self.skinitems.append((_("Select Display Skin"), self.displaySkins, _("Choose the Display Skin and press GREEN to activate the skin.")))
		self.createSetup()

	def createSetup(self):  # NOSONAR silence S2638
		Setup.createSetup(self, appendItems=self.skinitems)
#		self.setTitle(self.title)
		self.previewPath = ""
		self.loadPreview()

	def changedEntry(self):
		Setup.changedEntry(self)
		self.loadPreview()

	def selectionChanged(self):
		Setup.selectionChanged(self)
		self.loadPreview()

	def keySave(self):
		if self.osdSkins.value != config.skin.primary_skin.value or (self.displaySkins and self.displaySkins.value != config.skin.display_skin.value):
			restartbox = self.session.openWithCallback(self.restartGUI, MessageBox, _("GUI needs a restart to apply a new skin\nDo you want to restart the GUI now?"), MessageBox.TYPE_YESNO)
			restartbox.setTitle(_("Restart GUI now?"))
		else:
			Setup.keySave(self)

	def restartGUI(self, answer):
		if answer is True:
			if self.osdSkins.value != config.skin.primary_skin.value:
				try:
					if config.skin.primary_skin.value == self.METRIX_MYSKIN:
						from Plugins.Extensions.MyMetrixLite.ActivateSkinSettings import ActivateSkinSettings
						ActivateSkinSettings().RefreshIcons(True)  # Restore default icons if old skin is metrix
				except:
					pass
				config.skin.primary_skin.value = self.osdSkins.value
				# Restore MySkin setting if skin.MySkin.xml exists
				if config.skin.primary_skin.value == "MetrixHD/skin.xml" and isfile(resolveFilename(SCOPE_GUISKIN, self.METRIX_MYSKIN)):
					config.skin.primary_skin.value = self.METRIX_MYSKIN
				config.skin.primary_skin.save()
			if self.displaySkins and self.displaySkins.value != config.skin.display_skin.value:
				config.skin.display_skin.value = self.displaySkins.value
				config.skin.display_skin.save()

			self.session.open(TryQuitMainloop, 3)

	def showPic(self, picInfo=""):
		ptr = self.picload.getData()
		if ptr is not None:
			self["setupimage"].instance.setPixmap(ptr.__deref__())
			self["setupimage"].show()

	def loadPreview(self):
		print("loadPreview")
		if self.getCurrentItem() == self.osdSkins:
			currentItem = self.osdSkins.value
			root = self.osdRoot
		elif self.displaySkins and self.getCurrentItem() == self.displaySkins:
			currentItem = self.displaySkins.value
			root = self.displayRoot
		else:
			return

		print("loadPreview", currentItem)

		icon = self.ICONS.get(currentItem, "")
		if not icon:
			try:
				pngpath = pathjoin(pathjoin(root, currentItem), "prev.png")
			except OSError:
				pass
		else:
			pngpath = pathjoin(pathjoin(root, "."), icon)

		print("loadPreview", pngpath)

		if not exists(pngpath):
			pngpath = resolveFilename(SCOPE_GUISKIN, "noprev.png")

		if self.previewPath != pngpath:
			self.previewPath = pngpath

		self.picload.startDecode(self.previewPath)


class SkinSelector(SkinSetup):
	def __init__(self, session, args=None):
		SkinSetup.__init__(self, session)


class LcdSkinSelector(SkinSetup):
	def __init__(self, session, args=None):
		SkinSetup.__init__(self, session)


class SkinSelectorBase:
	DEFAULTSKIN = _("< Default >")
	METRIX_MYSKIN = "MetrixHD/skin.MySkin.xml"

	def __init__(self, session, args=None):
		self.skinName = "SkinSelector"
		self.setTitle(_("Skin Selector"))
		self.skinlist = []
		self.previewPath = ""
		if self.SKINXML and exists(pathjoin(self.root, self.SKINXML)):
			self.skinlist.append(self.DEFAULTSKIN)
		if self.PICONSKINXML and exists(pathjoin(self.root, self.PICONSKINXML)):
			self.skinlist.append(self.PICONDEFAULTSKIN)
		if self.ALTERNATESKINXML and exists(pathjoin(self.root, self.ALTERNATESKINXML)):
			self.skinlist.append(self.ALTERNATESKIN)
		if self.USERSKINXML and exists(pathjoin(self.root, self.USERSKINXML)):
			self.skinlist.append(self.USERSKIN)
		for root, dirs, files in walk(self.root, followlinks=True):
			for subdir in dirs:
				if subdir == "skin_default":
					continue
				if exists(pathjoin(root, subdir, self.SKINXML)):
					self.skinlist.append(subdir)
			dirs = []

		self["key_red"] = StaticText(_("Close"))
		self["key_green"] = StaticText(_("Save"))
		self["introduction"] = StaticText(_("Press OK to activate the selected skin."))
		self["SkinList"] = MenuList(self.skinlist)
		self["Preview"] = Pixmap()
		self.skinlist.sort()

		self["actions"] = NumberActionMap(["SetupActions", "DirectionActions", "TimerEditActions", "ColorActions"],
		{
			"ok": self.ok,
			"cancel": self.close,
			"red": self.close,
			"green": self.ok,
			"up": self.up,
			"down": self.down,
			"left": self.left,
			"right": self.right,
			"log": self.info,
		}, -1)

		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.showPic)
		self.onLayoutFinish.append(self.layoutFinished)

	def showPic(self, picInfo=""):
		ptr = self.picload.getData()
		if ptr is not None:
			self["Preview"].instance.setPixmap(ptr.__deref__())
			self["Preview"].show()

	def layoutFinished(self):
		self.picload.setPara((self["Preview"].instance.size().width(), self["Preview"].instance.size().height(), 1, 1, False, 1, "#00000000"))
		tmp = self.config.value.find("/" + self.SKINXML)
		if tmp != -1:
			tmp = self.config.value[:tmp]
			idx = 0
			for skin in self.skinlist:
				if skin == tmp:
					break
				idx += 1
			if idx < len(self.skinlist):
				self["SkinList"].moveToIndex(idx)
		self.loadPreview()

	def ok(self):
		if self["SkinList"].getCurrent() == self.DEFAULTSKIN:
			self.skinfile = pathjoin("", self.SKINXML)
		elif self["SkinList"].getCurrent() == self.PICONDEFAULTSKIN:
			self.skinfile = pathjoin("", self.PICONSKINXML)
		elif self["SkinList"].getCurrent() == self.ALTERNATESKIN:
			self.skinfile = pathjoin("", self.ALTERNATESKINXML)
		elif self["SkinList"].getCurrent() == self.USERSKIN:
			self.skinfile = pathjoin("", self.USERSKINXML)
		else:
			self.skinfile = pathjoin(self["SkinList"].getCurrent(), self.SKINXML)

		print("Skinselector: Selected Skin: %s" % pathjoin(self.root, self.skinfile))
		restartbox = self.session.openWithCallback(self.restartGUI, MessageBox, _("GUI needs a restart to apply a new skin\nDo you want to restart the GUI now?"), MessageBox.TYPE_YESNO)
		restartbox.setTitle(_("Restart GUI now?"))

	def up(self):
		self["SkinList"].up()
		self.loadPreview()

	def down(self):
		self["SkinList"].down()
		self.loadPreview()

	def left(self):
		self["SkinList"].pageUp()
		self.loadPreview()

	def right(self):
		self["SkinList"].pageDown()
		self.loadPreview()

	def info(self):
		aboutbox = self.session.open(MessageBox, _("Enigma2 skin selector"), MessageBox.TYPE_INFO)
		aboutbox.setTitle(_("About..."))

	def loadPreview(self):
		if self["SkinList"].getCurrent() == self.DEFAULTSKIN:
			pngpath = pathjoin(pathjoin(self.root, "."), "prev.png")
		elif self["SkinList"].getCurrent() == self.PICONDEFAULTSKIN:
			pngpath = pathjoin(pathjoin(self.root, "."), "piconprev.png")
		elif self["SkinList"].getCurrent() == self.ALTERNATESKIN:
			pngpath = pathjoin(pathjoin(self.root, "."), "alternate.png")
		elif self["SkinList"].getCurrent() == self.USERSKIN:
			pngpath = pathjoin(pathjoin(self.root, "."), "userskin.png")
		else:
			try:
				pngpath = pathjoin(pathjoin(self.root, self["SkinList"].getCurrent()), "prev.png")
			except OSError:
				pass

		if not exists(pngpath):
			pngpath = resolveFilename(SCOPE_GUISKIN, "noprev.png")

		if self.previewPath != pngpath:
			self.previewPath = pngpath

		self.picload.startDecode(self.previewPath)

	def restartGUI(self, answer):
		if answer is True:
			if isinstance(self, LcdSkinSelector):
				self.config.value = self.skinfile
				self.config.save()
			else:
				try:
					if self.config.value == self.METRIX_MYSKIN:
						from Plugins.Extensions.MyMetrixLite.ActivateSkinSettings import ActivateSkinSettings
						ActivateSkinSettings().RefreshIcons(True)  # restore default icons
				except:
					pass
				self.config.value = self.skinfile
				# Restore MySkin setting if skin.MySkin.xml exists
				if self.skinfile == "MetrixHD/skin.xml" and isfile(resolveFilename(SCOPE_GUISKIN, self.METRIX_MYSKIN)):
					self.config.value = self.METRIX_MYSKIN
				self.config.save()
			self.session.open(TryQuitMainloop, 3)


class _SkinSelector(Screen, SkinSelectorBase):
	SKINXML = "skin.xml"
	PICONSKINXML = None
	PICONDEFAULTSKIN = None
	ALTERNATESKINXML = None
	ALTERNATESKIN = None
	USERSKINXML = None
	USERSKIN = None

	skinlist = []
	root = pathjoin(eEnv.resolve("${datadir}"), "enigma2")

	def __init__(self, session, args=None):
		Screen.__init__(self, session)
		SkinSelectorBase.__init__(self, args)
		self.setTitle(_("Skin setup"))
		self.config = config.skin.primary_skin


class _LcdSkinSelector(Screen, SkinSelectorBase):
	SKINXML = "skin_display.xml"
	PICONSKINXML = "skin_display_picon.xml"
	PICONDEFAULTSKIN = _("< Default with Picon >")
	ALTERNATESKINXML = "skin_display_alternate.xml"
	ALTERNATESKIN = _("< Alternate Skin >")
	USERSKINXML = "skin_display_usr.xml"
	USERSKIN = _("< User Skin >")

	skinlist = []
	root = pathjoin(eEnv.resolve("${datadir}"), "enigma2/display/")

	def __init__(self, session, args=None):
		Screen.__init__(self, session)
		SkinSelectorBase.__init__(self, args)
		self.setTitle(_("LCD Skin Settings"))
		self.config = config.skin.display_skin

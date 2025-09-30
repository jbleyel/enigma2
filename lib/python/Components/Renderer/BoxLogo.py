from enigma import ePixmap, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_HALIGN_CENTER, BT_SCALE, BT_KEEP_ASPECT_RATIO, BT_HALIGN_CENTER, BT_VALIGN_CENTER, BT_HALIGN_RIGHT, BT_HALIGN_LEFT
from Components.Renderer.Renderer import Renderer
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import SCOPE_GUISKIN, resolveFilename, fileExists

def getLogoPath(logoType, logoVersion):
	def findLogo(logo):
		return (f := resolveFilename(SCOPE_GUISKIN, logo)) and fileExists(f) and f or ""
	pixAddon = ""
	if logoVersion:
		if logoVersion == "large":
			pixAddon = "_large"
		elif logoVersion == "medium":
			pixAddon == "_medium"
	if logoType == "model":
		if (f := findLogo("logos/boxlogo%s.svg" % pixAddon)):
			return f
		elif (f := findLogo("logos/distrologo%s.svg" % pixAddon)):
			return f
	elif logoType == "brand":
		return findLogo("logos/brandlogo%s.svg" % pixAddon)
	elif logoType == "distro":
		return findLogo("logos/distrologo%s.svg" % pixAddon)
	return ""

def getDefaultLogo(logoType, width, height, halign):
		if logoType == "model":
			defaultLogoPath = resolveFilename(SCOPE_GUISKIN, "skinlogo.svg")
		elif logoType == "brand":
			defaultLogoPath = resolveFilename(SCOPE_GUISKIN, "skinlogo_small.svg")
		else:
			defaultLogoPath = resolveFilename(SCOPE_GUISKIN, "skinlogo.svg")

		return detectAndFitPix(defaultLogoPath, width=width, height=height, align=halign)

def detectAndFitPix(path, width, height, align):
	align_enum = RT_HALIGN_CENTER
	if align == "right":
		align_enum = RT_HALIGN_RIGHT
	elif align == "left":
		align_enum = RT_HALIGN_LEFT
	return path and LoadPixmap(path, width=width, height=height, scaletoFit=True, align=align_enum)


def setLogo(px, logoType, width, height, halign="center", logoVersion=""):
	logoPath = getLogoPath(logoType, logoVersion)
	pix = detectAndFitPix(logoPath, width=width, height=height, align=halign)
	if pix:
		if logoPath.endswith(".png"):
			flags = BT_SCALE | BT_KEEP_ASPECT_RATIO
			if halign == "center":
				flags = flags | BT_HALIGN_CENTER | BT_VALIGN_CENTER
			elif halign == "right":
				flags = flags | BT_HALIGN_RIGHT | BT_VALIGN_CENTER
			elif halign == "left":
				flags = flags | BT_HALIGN_LEFT | BT_VALIGN_CENTER
			px.setPixmapScale(flags)
		px.setPixmap(pix)
	else:
		defaultLogo = getDefaultLogo(logoType, width, height, halign)
		if defaultLogo:
			px.setPixmap(defaultLogo)

class BoxLogo(Renderer):
	def __init__(self):
		Renderer.__init__(self)
		self.logoType = "model"
		self.halign = "center"
		self.logoVersion = ""
		
	GUI_WIDGET = ePixmap

	def applySkin(self, desktop, parent):
		attribs = self.skinAttributes[:]
		for (attrib, value) in self.skinAttributes:
			if attrib == "logoType":
				self.logoType = value
				attribs.remove((attrib, value))
			elif attrib == "halign":
				self.halign = value
				attribs.remove((attrib, value))
			elif attrib == "logoVersion": # can be large, medium. Defaults to small(not set)
				self.logoVersion = value
				attribs.remove((attrib, value))
		self.skinAttributes = attribs
		return Renderer.applySkin(self, desktop, parent)

	def changed(self, what):
		pass
				
	def onShow(self):
		if self.instance:
			x,y = self.position
			print("LOGO PosX: %d" % (x))
			setLogo(self.instance, self.logoType, self.instance.size().width(), self.instance.size().height(), self.halign, self.logoVersion)
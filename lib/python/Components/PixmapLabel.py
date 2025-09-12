from enigma import eLabel, ePixmap
from skin import applyAllAttributes

from Components.GUIComponent import GUIComponent


class PixmapLabel(GUIComponent):
	GUI_WIDGET_PIXMAP = ePixmap
	GUI_WIDGET_LABEL = eLabel

	def __init__(self, text=""):
		GUIComponent.__init__(self)
		self.xOffset = 0
		self.yOffset = 0
		self.isLabel = True
		self.message = text

	def setInstance(self, label=True):
		self.isLabel = label
		self.instance = self.instanceLabel if label else self.instancePixmap

	def getSize(self):  # pixmap
		size = self.instanceLabel.calculateSize() if self.isLabel else self.instancePixmap.size()
		return size.width(), size.height()

	def applySkin(self, desktop, screen):
		print("DEBUG PixmapLabel applySkin")
		if self.skinAttributes is not None:
			attribs = []
			attribsLabel = []
			attribsPixmap = []
			for (attrib, value) in self.skinAttributes:
				if attrib == "offset":
					self.xOffset, self.yOffset = map(int, value.split(","))
				elif attrib in ("font", "text", "horizontalAlignment"):
					attribsLabel.append((attrib, value))
				elif attrib in ("pixmap", "scale", "alphatest"):
					attribsPixmap.append((attrib, value))
				else:
					attribs.append((attrib, value))

			self.skinAttributes = attribs
			self.skinAttributesLabel = attribsLabel
			self.skinAttributesPixmap = attribsPixmap
		if not self.visible:
			self.instance.hide()
		if self.skinAttributes is None:
			result = False
		else:
			print("DEBUG PixmapLabel applyAllAttributes")
			applyAllAttributes(self.instanceLabel, desktop, self.skinAttributes + self.skinAttributesLabel, screen.scale)
			applyAllAttributes(self.instancePixmap, desktop, self.skinAttributes + self.skinAttributesPixmap, screen.scale)
			result = True
		return result

	def move(self, x, y=None):
		if y is None:
			y = x.y()
			x = x.x()
		GUIComponent.move(self, x - self.xOffset, y - self.yOffset)

	def setPosition(self, x, y):
		self.move(x, y)

	def getPosition(self):
		x, y = GUIComponent.getPosition(self)
		return x + self.xOffset, y + self.yOffset

	def setOffset(self, x, y):
		oldx, oldy = self.getPosition()
		self.xOffset, self.yOffset = x, y
		self.move(oldx, oldy)

	def getOffset(self):
		return self.xOffset, self.yOffset

	def GUIcreate(self, parent):  # Default implementation for only one widget per component.  Feel free to override!
		print("DEBUG PixmapLabel GUIcreate")
		self.instancePixmap = self.GUI_WIDGET_PIXMAP(parent)
		self.instanceLabel = self.GUI_WIDGET_LABEL(parent)
		self.postWidgetCreate(self.instanceLabel)

	def GUIdelete(self):
		# self.preWidgetRemove(self.instance)
		self.instancePixmap = None
		self.instanceLabel = None

	def postWidgetCreate(self, instance):
		print("DEBUG PixmapLabel postWidgetCreate")
		try:
			instance.setText(self.message or "")
		except:
			pass

	def createWidget(self, parent):  # Default for argument less widget constructor.
		return None

# fake Source methods:
	def connectDownstream(self, downstream):
		pass

	def checkSuspend(self):
		pass

	def disconnectDownstream(self, downstream):
		pass

	def setText(self, text):
		try:
			self.message = text
			if self.instanceLabel:
				self.instanceLabel.setText(self.message or "")
		except:
			self.message = ""
			self.instanceLabel.setText(self.message or "")

	def getText(self):
		return self.message

	text = property(getText, setText)

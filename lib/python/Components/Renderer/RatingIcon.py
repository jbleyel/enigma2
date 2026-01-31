from Components.Renderer.Renderer import Renderer
from Tools.Directories import SCOPE_GUISKIN, resolveFilename

from enigma import ePixmap


class RatingIcon(Renderer):
	def __init__(self):
		Renderer.__init__(self)
		self.small = False

	GUI_WIDGET = ePixmap

	def postWidgetCreate(self, instance):
		self.changed((self.CHANGED_DEFAULT,))

	def applySkin(self, desktop, parent):
		newAttribs = []
		for attrib, value in self.skinAttributes:
			if attrib == "small":
				self.small = value == "1"
			else:
				newAttribs.append((attrib, value))
		self.skinAttributes = newAttribs
		rc = Renderer.applySkin(self, desktop, parent)
		self.changed((self.CHANGED_DEFAULT,))
		return rc

	def changed(self, what):
		if self.source and hasattr(self.source, "text") and self.instance:
			if what[0] == self.CHANGED_CLEAR:
				self.instance.setPixmap(None)
			else:
				if self.source.text:
					age = int(self.source.text.replace("+", ""))
					if age == 0:
						self.instance.setPixmap(None)
						self.instance.hide()
						return
					if age <= 15:
						age += 3

					pngEnding = f"ratings/{age}{"_s" if self.small else ""}.png"
					pngname = resolveFilename(SCOPE_GUISKIN, pngEnding)
					self.instance.setPixmapFromFile(pngname)
					self.instance.show()
				else:
					self.instance.setPixmap(None)

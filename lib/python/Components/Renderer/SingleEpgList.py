from time import localtime
from enigma import eLabel, eEPGCache
from Components.Renderer.Renderer import Renderer
from Components.VariableText import VariableText


class SingleEpgList(Renderer, VariableText):
	GUI_WIDGET = eLabel

	def __init__(self):
		self.maxEvents = 4
		self.minEvent = 1
		self.ignoreNA = False
		Renderer.__init__(self)
		VariableText.__init__(self)
		self.epgcache = eEPGCache.getInstance()

	def applySkin(self, desktop, parent):
		attribs = self.skinAttributes[:]
		for (attrib, value) in self.skinAttributes:
			if attrib == "maxEvents":
				self.maxEvents = int(value)
				attribs.remove((attrib, value))
			if attrib == "minEvent":
				self.minEvent = int(value)
				attribs.remove((attrib, value))
			if attrib == "ignoreNA":
				self.ignoreNA = value.toLower() in ("true", "1", "enabled", "yes", "on", attrib.toLower())
				attribs.remove((attrib, value))
		if self.maxEvents < self.minEvent:
			self.minEvent = 1
		if self.maxEvents > 10:
			self.maxEvents = 10
		self.skinAttributes = attribs
		return Renderer.applySkin(self, desktop, parent)

	def changed(self, what):
		event = self.source.event
		text = []
		if event:
			service = self.source.service
			if self.epgcache:
				events = self.epgcache.lookupEvent(['IBDCTM', (service.toString(), 0, -1, -1)])
				if events:
					eventCount = 0
					for event in events:
						if eventCount > 0 and eventCount >= self.minEvent:
							if event[4]:
								localTime = localtime(event[1])
								text.append(f"{localTime[3]:02d}:{localTime[4]:02d} {event[4]}")
							elif not self.ignoreNA:
								text.append(_("N/A"))

						eventCount += 1
						if eventCount > self.maxEvents:
							break

		self.text = "\n".join(text)

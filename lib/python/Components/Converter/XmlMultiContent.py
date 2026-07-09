from enigma import eListboxPythonMultiContent

from skin import SkinContext, SkinContextStack, TemplateParser, parseFont, parsePadding
from Components.Converter.StringList import StringList

# Default stroke width in pixels for shapes built without an explicit strokeWidth
# (e.g. via the skin's "shapeStroke" template attribute).
SHAPE_STROKE_WIDTH = 6

# Each TYPE_RECTS rect field is an (fraction, pixelOffset) pair, resolved in C++
# at paint time as round(fraction * dimension) + pixelOffset. That lets a shape
# stay centered/full-length relative to the item's actual size while still using
# a fixed pixel stroke width, without Python ever needing to know that size.


def buildShapeRects(name, strokeWidth=SHAPE_STROKE_WIDTH):
	half = strokeWidth / 2.0
	center = (0.5, -half)         # centered offset along the cross axis
	toFar = (0.5, half)           # from the centered stroke to the far edge
	thickness = (0.0, strokeWidth)  # fixed pixel thickness, independent of item size
	full = (1.0, 0.0)             # full dimension
	zero = (0.0, 0.0)
	vertical_full = (center, zero, thickness, full)    # branch: full-height vertical bar
	vertical_half = (center, zero, thickness, toFar)   # lastchild: vertical bar down to the branch point
	horizontal = (center, center, toFar, thickness)    # the rightward branch stub, both shapes
	match name:
		case "branch":  # tree connector "├": vertical line spans the full height
			return [vertical_full, horizontal]
		case "lastchild":  # tree connector "└": vertical line stops at the branch
			return [vertical_half, horizontal]
		case _:
			print(f"[XmlMultiContent] Error: Unknown shape name '{name}'!")
			return None


class MultiContentTemplateParser(TemplateParser):
	_KNOWN_TEMPLATE_ATTRS = {"name", "fonts", "itemWidth", "itemHeight"}

	def __init__(self, debug=False):
		TemplateParser.__init__(self, debug=debug)
		self.template = {}
		self.indexNames = {}
		self.additionalTemplateAttributes = {}
		self.templateDataFormats = {}

	def scaleWithHeight(self, itemWidth, itemHeight):
		scaleFactorVertical = self.scale[1][0] / self.scale[1][1]
		scaleFactorHorizontal = self.scale[0][0] / self.scale[0][1]
		return (int(itemWidth * scaleFactorHorizontal), int(itemHeight * scaleFactorVertical))

	def scalePadding(self, padding):
		return (int(padding[0] * self.scale[0][0] / self.scale[0][1]),
				int(padding[1] * self.scale[1][0] / self.scale[1][1]),
				int(padding[2] * self.scale[0][0] / self.scale[0][1]),
				int(padding[3] * self.scale[1][0] / self.scale[1][1]))

	def readTemplate(self, templateName):
		def parseIndexColor(color):
			if self.indexNames and isinstance(color, str) and color[0] == "+":
				index = self.indexNames.get(color[1:], -1)
				if index < 0 or index >= len(self.indexNames):
					print(f"[XmlMultiContent] Error: Index name must resolve to a number between 0 and {len(self.indexNames) - 1} inclusive!")
					color = None
				else:
					color = 0xff000000 | index
			return color

		def parseTemplateModes(template):
			modes = {}
			modesItems = {}
			for mode in template.findall("mode"):
				items = []
				modeName = mode.get("name")
				itemWidth = int(mode.get("itemWidth", self.itemWidth))  # Override from mode.
				itemHeight = int(mode.get("itemHeight", self.itemHeight))  # Override from mode.
				attibutes = {
					"itemWidth": itemWidth,
					"itemHeight": itemHeight
				}
				for name, value in mode.items():
					if name not in ("itemWidth", "itemHeight"):
						attibutes[name] = value
				modes[modeName] = attibutes
				context = SkinContextStack()
				context.x = 0
				context.y = 0
				context.w = itemWidth
				context.h = itemHeight
				context.scale = self.scale  # Set scale from the widget.
				context = SkinContext(context, "0,0", f"{itemWidth},{itemHeight}")
				for element in list(mode):
					processor = self.processors.get(element.tag, self.processNone)
					newItems = processor(element, context)
					if newItems:
						items += newItems
				newItems = []
				for item in items:
					itemsAttibutes = {}
					for name, value in item.items():
						itemsAttibutes[name] = int(value) if name == "font" else value
					newItems.append(itemsAttibutes)
				modesItems[modeName] = newItems
				modes[modeName] = attibutes
				if self.debug:
					print(f"[MultiContentTemplateParser] DEBUG ITEMS {modeName}")
					print(modesItems[modeName])
			return modes, modesItems

		self.template = {}
		self.template["modes"] = {}
		self.template["fonts"] = []
		try:
			for template in self.dom.findall("template"):
				templateStyleName = template.get("name", "Default")
				self.itemWidth = int(template.get("itemWidth", self.itemWidth))
				self.itemHeight = int(template.get("itemHeight", self.itemHeight))
				self.shapeStroke = int(template.get("shapeStroke", SHAPE_STROKE_WIDTH))
				if templateStyleName == templateName:
					self.additionalTemplateAttributes = {k: v for k, v in template.items() if k not in self._KNOWN_TEMPLATE_ATTRS}
					self.templateDataFormats = {}
					templateModes, modesItems = parseTemplateModes(template)
					for index, font in enumerate([x.strip() for x in template.get("fonts", "").split(",")]):
						self.template["fonts"].append(parseFont(font, self.scale))
					for modeName, modeProperties in templateModes.items():
						modeItemWidth = modeProperties.get("itemWidth")
						modeItemHeight = modeProperties.get("itemHeight")
						modeData = []
						for item in modesItems[modeName]:
							index = item.get("index", "-1")
							if index.isdigit() or index == "-1":
								index = int(index)
							elif self.indexNames:
								index = self.indexNames.get(index, -1)
								if index < 0 or index >= len(self.indexNames):
									print(f"[XmlMultiContent] Error: Index name must resolve to a number between 0 and {len(self.indexNames) - 1} inclusive!")
							else:
								index = -1
								print("[XmlMultiContent] Error: Index must be a list item number!")
							pos = item.get("position")
							size = item.get("size")
							backgroundColor = parseIndexColor(item.get("backgroundColor"))
							backgroundColorSelected = parseIndexColor(item.get("backgroundColorSelected"))
							borderColor = parseIndexColor(item.get("borderColor"))
							borderColorSelected = parseIndexColor(item.get("borderColorSelected"))
							borderWidth = int(item.get("borderWidth", "0"))
							cornerRadius, cornerEdges = item.get("_radius", (0, 0))
							flags = item.get("_flags", 0)
							match item["type"]:
								case "text":
									padding = parsePadding("padding", item.get("padding", "0,0,0,0"))
									padding = self.scalePadding(padding)
									textBorderColor = parseIndexColor(item.get("textBorderColor"))
									textBorderWidth = int(item.get("textBorderWidth", "0"))
									foregroundColorSelected = parseIndexColor(item.get("foregroundColorSelected"))
									foregroundColor = parseIndexColor(item.get("foregroundColor"))
									font = int(item.get("font", 0))
									# 'format' is not consumed here — it's collected for the screen to read
									# back (like additionalTemplateAttributes) and apply itself when it
									# builds each row's data, since the named values it references (e.g.
									# adapterName, busName) only exist in the screen's own row-build code.
									formatString = item.get("format")
									if formatString:
										self.templateDataFormats[item.get("index")] = formatString
									if index == -1:
										index = item.get("text", "")
									modeData.append((eListboxPythonMultiContent.TYPE_TEXT, pos[0], pos[1], size[0], size[1], font or 0, flags, index, foregroundColor, foregroundColorSelected, backgroundColor, backgroundColorSelected, borderWidth, borderColor, cornerRadius, cornerEdges, textBorderWidth, textBorderColor, padding[0], padding[1], padding[2], padding[3]))
								case "pixmap":
									padding = parsePadding("padding", item.get("padding", "0,0,0,0"))
									padding = self.scalePadding(padding)
									if index == -1:
										index = item.get("pixmap", "")
									pixmapType = item.get("pixmapType", eListboxPythonMultiContent.TYPE_PIXMAP)
									pixmapFlags = item.get("pixmapFlags", 0)
									modeData.append((pixmapType, pos[0], pos[1], size[0], size[1], self.resolvePixmap(index), backgroundColor, backgroundColorSelected, pixmapFlags, cornerRadius, cornerEdges, padding[0], padding[1], padding[2], padding[3]))
								case "rectangle":
									gradientDirection, gradientAlpha, gradientStart, gradientEnd, gradientMid, gradientStartSelected, gradientEndSelected, gradientMidSelected = item.get("_gradient", (0, 0, None, None, None, None, None, None))
									if gradientDirection:
										if gradientAlpha:
											modeData.append((eListboxPythonMultiContent.TYPE_LINEAR_GRADIENT_ALPHABLEND, pos[0], pos[1], size[0], size[1], gradientDirection, gradientStart, gradientMid, gradientEnd, gradientStartSelected, gradientMidSelected, gradientEndSelected, cornerRadius, cornerEdges))
										else:
											modeData.append((eListboxPythonMultiContent.TYPE_LINEAR_GRADIENT, pos[0], pos[1], size[0], size[1], gradientDirection, gradientStart, gradientMid, gradientEnd, gradientStartSelected, gradientMidSelected, gradientEndSelected, cornerRadius, cornerEdges))
									else:
										modeData.append((eListboxPythonMultiContent.TYPE_RECT, pos[0], pos[1], size[0], size[1], backgroundColor, backgroundColorSelected, borderWidth, borderColor, borderColorSelected, cornerRadius, cornerEdges))
								case "shape":
									shapeName = item.get("name")
									foregroundColorSelected = parseIndexColor(item.get("foregroundColorSelected"))
									foregroundColor = parseIndexColor(item.get("foregroundColor"))
									if index != -1:  # dynamic: the row provides the fractional rect list (or None) at this index
										rects = index
									elif shapeName:  # static: same shape for every row
										rects = buildShapeRects(shapeName, self.shapeStroke)
									else:
										print("[XmlMultiContent] Error: 'shape' requires either an 'index' or a 'name' attribute!")
										rects = None
									modeData.append((eListboxPythonMultiContent.TYPE_RECTS, pos[0], pos[1], size[0], size[1], rects, foregroundColor, foregroundColorSelected))
								case "progress":
									if index == -1:
										index = None
									foregroundColorSelected = parseIndexColor(item.get("foregroundColorSelected", None))
									foregroundColor = parseIndexColor(item.get("foregroundColor", None))
									gradientDirection, gradientAlpha, gradientStart, gradientEnd, gradientMid, gradientStartSelected, gradientEndSelected, gradientMidSelected = item.get("_gradient", (0, 0, None, None, None, None, None, None))
									modeData.append((eListboxPythonMultiContent.TYPE_PROGRESS, pos[0], pos[1], size[0], size[1], index, borderWidth, foregroundColor, foregroundColorSelected, borderColor, gradientStart, gradientMid, gradientEnd, gradientStartSelected, gradientMidSelected, gradientEndSelected, cornerRadius, cornerEdges))
						maxX = 0
						maxIndexX = -1
						for modeItemIndex, modeItem in enumerate(modeData):
							if (modeItem[1] + modeItem[3]) > maxX:
								maxX = modeItem[1] + modeItem[3]
								maxIndexX = modeItemIndex

						if maxIndexX != -1:
							modeItem = list(modeData[maxIndexX])
							if modeItem[0] == eListboxPythonMultiContent.TYPE_TEXT:
								modeItem[3] = -modeItem[3]
								modeData[maxIndexX] = tuple(modeItem)

						self.template["modes"][modeName] = ((modeItemWidth, modeItemHeight), modeData)
		except Exception as err:
			# TODO: DEBUG: Remove the following two lines before publication.
			import traceback
			traceback.print_exc()
			print(f"[TemplateParser] Error: Unable to parse XML template!  {str(err)})")


class XmlMultiContent(StringList, MultiContentTemplateParser):
	"""Turns a python tuple list into a multi-content list which can be used in a listbox renderer."""

	def __init__(self, args):
		StringList.__init__(self, args)
		MultiContentTemplateParser.__init__(self)
		self.activeStyle = None
		self.activeTemplate = "Default"  # This value string is used in the UI.
		self.dom = args.get("dom")
		if self.dom is not None:
			self.scale = args.get("scale")
			self.itemWidth = args.get("itemWidth", 0)
			self.itemHeight = args.get("itemHeight", 0)
		else:
			print("[XmlMultiContent] Error: This is for internal usage and not an argument for a 'converter' tag!")

	def changed(self, what):
		def setTemplate():
			if self.source:
				templateName = self.source.template
				if templateName != self.activeTemplate:
					self.activeTemplate = templateName
					self.readTemplate(self.activeTemplate)
				style = self.source.style
				if style == self.activeStyle:
					return
				modes = self.template.get("modes")
				if modes and modes[style]:
					itemWidth = modes[style][0][0]
					itemHeight = modes[style][0][1]
					template = modes[style][1]
					selectionEnabled = self.template.get("selectionEnabled")
					scrollbarMode = self.template.get("scrollbarMode")
					itemWidth, itemHeight = self.scaleWithHeight(itemWidth, itemHeight)
					self.content.setTemplate(template)
					self.content.setItemWidth(itemWidth)
					self.content.setItemHeight(itemHeight)
					if selectionEnabled is not None:
						self.selectionEnabled = selectionEnabled
					if scrollbarMode is not None:
						self.scrollbarMode = scrollbarMode
					self.activeStyle = style
				else:
					print("[XmlMultiContent] Error: All templates must include a 'mode' entry!")

		if not self.content:
			if self.dom is not None:
				self.indexNames = self.source.indexNames
				self.readTemplate(self.source.template)
				self.source.additionalTemplateAttributes = self.additionalTemplateAttributes
				self.source.templateDataFormats = self.templateDataFormats
				if "fonts" not in self.template:
					print("[XmlMultiContent] Error: All templates must include a 'fonts' entry!")
				if "modes" not in self.template:
					print("[XmlMultiContent] Error: All templates must include a 'mode' entry!")

			self.content = eListboxPythonMultiContent()
			for index, font in enumerate(self.template["fonts"]):  # Setup fonts (also given by source).
				self.content.setFont(index, font)
		if what[0] == self.CHANGED_SPECIFIC and what[1] in ("style", "template"):  # If only template changed, don't reload list.
			pass
		elif self.source:
			try:
				contentList = []
				sourceList = self.source.list
				for item in range(len(sourceList)):
					contentList.append((sourceList[item],) if not isinstance(sourceList[item], (list, tuple)) else sourceList[item])
			except Exception as error:
				print(f"[XmlMultiContent] Error: {error}!")
				contentList = self.source.list
			self.content.setList(contentList)
		setTemplate()
		self.downstream_elements.changed(what)

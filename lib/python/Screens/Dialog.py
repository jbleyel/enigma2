from enigma import eTimer, eSize, ePoint, eRectangle

from Components.ActionMap import HelpableActionMap, HelpableNumberActionMap
from Components.config import ConfigSubsection, ConfigText, config
from Components.Label import Label
from Components.Pixmap import MultiPixmap
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen, ScreenSummary
from Tools.Directories import SCOPE_GUISKIN, resolveFilename
from Tools.LoadPixmap import LoadPixmap

if not hasattr(config.misc, "pluginlist"):  # Shared with Screens.ChoiceBox, registered here too so 'reorderConfig' also works without importing ChoiceBox.
	config.misc.pluginlist = ConfigSubsection()
	config.misc.pluginlist.eventinfoOrder = ConfigText(default="[]")
	config.misc.pluginlist.extensionOrder = ConfigText(default="[]")
	config.misc.pluginlist.fcBookmarksOrder = ConfigText(default=f"['{_("Storage Devices")}']")


def resolveKeyIcon(key):  # Resolve the pixmap (if any) associated with a choice entry's button key.
	if not key or key in ("dummy", "none"):
		return None
	if key == "expandable":
		return LoadPixmap(resolveFilename(SCOPE_GUISKIN, "icons/expandable.png"))
	if key == "expanded":
		return LoadPixmap(resolveFilename(SCOPE_GUISKIN, "icons/expanded.png"))
	if key == "verticalline":
		return LoadPixmap(resolveFilename(SCOPE_GUISKIN, "icons/verticalline.png"))
	return LoadPixmap(resolveFilename(SCOPE_GUISKIN, f"buttons/key_{key}.png"))


class Dialog(Screen):
	skin = """
	<screen name="Dialog" position="center,center" size="600,400" resolution="1280,720">
		<widget name="icon" pixmaps="icons/input_question.png,icons/input_info.png,icons/input_warning.png,icons/input_error.png,icons/input_message.png" position="10,10" size="53,53" alphatest="blend" conditional="icon" scale="1" transparent="1" />
		<widget name="text" position="10,10" size="580,70" font="Regular;22" transparent="1" />
		<widget source="list" render="Listbox" position="10,90" size="580,245" conditional="list" enableWrapAround="1" scrollbarMode="showOnDemand" transparent="1">
			<template name="Default" fonts="Regular;22" itemHeight="30">
				<text index="Text" position="10,0" size="560,30" font="0" horizontalAlignment="left" verticalAlignment="center" />
			</template>
			<template name="IconText" fonts="Regular;22" itemHeight="30">
				<pixmap index="Icon" position="4,2" size="26,26" alpha="blend" scale="centerScaled" />
				<text index="Text" position="40,0" size="530,30" font="0" horizontalAlignment="left" verticalAlignment="center" />
			</template>
		</widget>
		<widget name="description" position="10,e-30" size="580,25" font="Regular;18" foregroundColor="grey" transparent="1" />
	</screen>"""

	IDX_ICON = 0  # Row tuple layout used by the "list" source and its skin templates, see buildRows().
	IDX_TEXT = 1
	IDX_ENTRY = 2

	TYPE_NOICON = 0
	TYPE_YESNO = 1
	TYPE_INFO = 2
	TYPE_WARNING = 3
	TYPE_ERROR = 4
	TYPE_MESSAGE = 5
	TYPE_PREFIX = {
		TYPE_YESNO: _("Question"),
		TYPE_INFO: _("Information"),
		TYPE_WARNING: _("Warning"),
		TYPE_ERROR: _("Error"),
		TYPE_MESSAGE: _("Message")
	}

	MIN_WIDTH = 280
	MAX_WIDTH = 900
	MAX_VISIBLE_ROWS = 12

	def __init__(self, session, text="", type=TYPE_YESNO, timeout=-1, list=None, default=True, closeOnAnyKey=False, enableInput=True, msgBoxID=None, typeIcon=None, timeoutDefault=None, windowTitle=None, skinName=None, choiceList=None, buttonList=None, allowCancel=True, reorderConfig=None):
		Screen.__init__(self, session, mandatoryWidgets=["icon", "text", "list", "description"], enableHelp=True)
		self.text = text
		self["text"] = Label(text)
		self.type = type
		self.choiceMode = choiceList is not None or buttonList is not None
		if self.choiceMode:
			self.list = choiceList if choiceList else []
			if buttonList is None:
				buttonList = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "red", "green", "yellow", "blue", "text"] + (len(self.list) - 14) * [""]
			else:
				buttonList = buttonList + (len(self.list) - len(buttonList)) * [""]
			self.configOrder = getattr(config.misc.pluginlist, reorderConfig) if reorderConfig else None
			if self.configOrder and self.configOrder.value:
				prevList = [x for x in zip(self.list, buttonList)]
				newList = []
				for button in eval(self.configOrder.value):
					for item in prevList:
						if item[0][0] == button:
							prevList.remove(item)
							newList.append(item)
				reordered = [x for x in zip(*(newList + prevList))]
				self.list, buttonList = list(reordered[0]), list(reordered[1])
				number = 1
				newButtons = []
				for button in buttonList:
					if (not button or button.isdigit()) and number <= 10:
						newButtons.append(str(number % 10))
						number += 1
					else:
						newButtons.append(not button.isdigit() and button or "")
				buttonList = newButtons
			self.buttonList = buttonList
			self.buttonMap = {}
			for index, entry in enumerate(self.list):
				button = str(buttonList[index])
				if button:
					self.buttonMap[button] = entry
			self.allowCancel = allowCancel
			self.startIndex = 0
		else:
			self.configOrder = None
			self.buttonList = None
			self.buttonMap = {}
			self.allowCancel = True
			if type == self.TYPE_YESNO:
				self.list = [(_("Yes"), True), (_("No"), False)] if list is None else list
				if isinstance(default, bool):
					self.startIndex = 0 if default else 1
				elif isinstance(default, int):
					self.startIndex = default
				else:
					print(f"[Dialog] Error: The context of the default ({default}) can't be determined!")
			else:
				self.list = None
				self.startIndex = 0
		self["list"] = List(self.buildRows(), templateName=self.listTemplate(), indexNames={"Icon": self.IDX_ICON, "Text": self.IDX_TEXT})
		if not self.list:
			self["list"].hide()
		self["description"] = Label()
		if not self.choiceMode:
			self["description"].hide()
		if self.updateDescription not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.updateDescription)
		self.timeout = timeout
		self.closeOnAnyKey = closeOnAnyKey
		self.msgBoxID = msgBoxID
		self.typeIcon = (self.TYPE_NOICON if self.choiceMode else type) if typeIcon is None else typeIcon
		if self.typeIcon:
			self["icon"] = MultiPixmap()
		self.timeoutDefault = timeoutDefault
		self.windowTitle = windowTitle or (_("Choice Box") if self.choiceMode else self.TYPE_PREFIX.get(type, _("Message")))
		self.baseTitle = self.windowTitle
		self.activeTitle = self.windowTitle
		self.skinName = ["Dialog"]
		if skinName:
			if isinstance(skinName, str):
				self.skinName.insert(0, skinName)
			else:
				self.skinName = skinName + self.skinName
		self.timer = eTimer()
		self.timer.callback.append(self.processTimer)
		if enableInput:
			self.createActionMap(0)
		self.onLayoutFinish.append(self.layoutFinished)

	def buildRows(self):  # Plain data rows for the "list" source; rendering is defined entirely by the skin's XML list template.
		rows = []
		for index, entry in enumerate(self.list or []):
			if self.choiceMode:
				icon = resolveKeyIcon(self.buttonList[index]) if self.buttonList else None
			else:
				icon = entry[2] if len(entry) > 2 and not isinstance(entry[2], str) else None
			rows.append((icon, entry[0], entry))
		return rows

	def listTemplate(self):  # Choice entries always use the icon column (button key icon), plain entries only if they carry a pixmap themselves.
		if self.choiceMode:
			return "IconText"
		return "IconText" if any(len(entry) > 2 and entry[2] and not isinstance(entry[2], str) for entry in self.list or []) else "Default"

	def createActionMap(self, prio):
		if self.choiceMode:
			actionMethods = {"red": self.keyRed, "green": self.keyGreen, "yellow": self.keyYellow, "blue": self.keyBlue, "text": self.keyText}
			actions = {"ok": (self.select, _("Select the current entry"))}
			for button in self.buttonMap:
				actions[button] = (actionMethods.get(button, self.keyNumberGlobal), _("Select the %s entry") % button.upper())
			self["actions"] = HelpableNumberActionMap(self, ["OkActions", "ColorActions", "TextActions", "NumberActions"], actions, prio=prio, description=_("Dialog Choice Actions"))
			self["cancelAction"] = HelpableActionMap(self, ["OkCancelActions"], {
				"cancel": (self.cancel, _("Cancel the selection and exit"))
			}, prio=prio, description=_("Dialog Actions"))
			self["cancelAction"].setEnabled(self.allowCancel)
			self["navigationActions"] = HelpableActionMap(self, ["NavigationActions"], {
				"top": (self.top, _("Move to first line")),
				"pageUp": (self.pageUp, _("Move up a page")),
				"up": (self.up, _("Move up a line")),
				"down": (self.down, _("Move down a line")),
				"pageDown": (self.pageDown, _("Move down a page")),
				"bottom": (self.bottom, _("Move to last line"))
			}, prio=prio, description=_("Dialog Actions"))
			self["navigationActions"].setEnabled(len(self.list) > 1)
			self["moveActions"] = HelpableActionMap(self, ["PreviousNextActions", "MenuActions"], {
				"menu": (self.keyResetList, _("Reset the order of the entries")),
				"previous": (self.keyMoveItemUp, _("Move the current entry up")),
				"next": (self.keyMoveItemDown, _("Move the current entry down")),
			}, prio=prio, description=_("Dialog Order Actions"))
			self["moveActions"].setEnabled(len(self.list) > 1 and bool(self.configOrder))
		elif self.list:
			self["actions"] = HelpableActionMap(self, ["MsgBoxActions", "NavigationActions"], {
				"cancel": (self.cancel, _("Select the No / False response")),
				"select": (self.select, _("Return the current selection response")),
				"selectOk": (self.selectOk, _("Select the Yes / True response")),
				"top": (self.top, _("Move to first line")),
				"pageUp": (self.pageUp, _("Move up a page")),
				"up": (self.up, _("Move up a line")),
				"down": (self.down, _("Move down a line")),
				"pageDown": (self.pageDown, _("Move down a page")),
				"bottom": (self.bottom, _("Move to last line"))
			}, prio=prio, description=_("Dialog Actions"))
		else:
			self["actions"] = HelpableActionMap(self, ["OkCancelActions"], {
				"cancel": (self.cancel, _("Close the window")),
				"ok": (self.select, _("Close the window"))
			}, prio=prio, description=_("Dialog Actions"))

	def __repr__(self):
		return f"{str(type(self))}({self.text})"

	def layoutFinished(self):
		if self.list:
			self["list"].enableAutoNavigation(False)  # Override listbox navigation.
			self["list"].setIndex(self.startIndex)
		if self.typeIcon:
			self["icon"].setPixmapNum(self.typeIcon - 1)
		prefix = self.TYPE_PREFIX.get(self.type, _("Unknown"))
		if self.baseTitle is None:
			title = self.getTitle()
			if title:
				self.baseTitle = title % prefix if "%s" in title else title
			else:
				self.baseTitle = prefix
		elif "%s" in self.baseTitle:
			self.baseTitle = self.baseTitle % prefix
		self.setTitle(self.baseTitle, showPath=False)
		if not hasattr(self, "skinGeometry"):  # Freeze the skin's original geometry once, autoResize must never re-derive it from widgets it has itself already moved/resized.
			self.captureSkinGeometry()
		self.autoResize()
		if self.timeout > 0:
			print(f"[Dialog] Timeout set to {self.timeout} seconds.")
			self.timer.start(25)

	def reloadLayout(self):  # Call this after changing content (text/icon/list/...) on an already shown instance, e.g. from a modal wrapper reusing one instantiated dialog.
		self.layoutFinished()

	def processTimer(self):
		if self.activeTitle is None:  # Check if the title has been externally changed and if so make it the dominant title.
			self.activeTitle = self.getTitle()
			if "%s" in self.activeTitle:
				self.activeTitle = self.activeTitle % self.TYPE_PREFIX.get(self.type, _("Unknown"))
		if self.baseTitle != self.activeTitle:
			self.baseTitle = self.activeTitle
		if self.timeout > 0:
			if self.baseTitle:
				self.setTitle(f"{self.baseTitle} ({self.timeout})", showPath=False)
			self.timer.start(1000)
			self.timeout -= 1
		else:
			self.stopTimer("Timeout!")
			if self.timeoutDefault is not None:
				self.close(self.timeoutDefault)
			else:
				self.select()

	def stopTimer(self, reason):
		print(f"[Dialog] {reason}")
		self.timer.stop()
		self.timeout = 0
		if self.baseTitle is not None:
			self.setTitle(self.baseTitle, showPath=False)

	def cancel(self):
		self.close(None if self.choiceMode else False)

	def select(self):
		if self.choiceMode:
			current = self["list"].getCurrent()
			self.goEntry(current[self.IDX_ENTRY] if current else None)
		elif self.list:
			current = self["list"].getCurrent()
			self.close(current[self.IDX_ENTRY][1] if current else True)
		else:
			self.close(True)

	def selectOk(self):
		self.close(True)

	def goEntry(self, entry):  # Run a specific choice entry, supports the legacy 'CALLFUNC' convention.
		if entry and len(entry) > 3 and isinstance(entry[1], str) and entry[1] == "CALLFUNC":
			entry[2](entry[3])
		elif entry and len(entry) > 2 and isinstance(entry[1], str) and entry[1] == "CALLFUNC":
			entry[2](None)
		else:
			self.close(entry)

	def goKey(self, key):  # Lookup a key in the buttonMap, then run it.
		if key in self.buttonMap:
			self.goEntry(self.buttonMap[key])

	def keyRed(self):  # Run a colored or labeled shortcut.
		self.goKey("red")

	def keyGreen(self):
		self.goKey("green")

	def keyYellow(self):
		self.goKey("yellow")

	def keyBlue(self):
		self.goKey("blue")

	def keyText(self):
		self.goKey("text")

	def keyNumberGlobal(self, number):  # Run a numbered shortcut.
		self.goKey(str(number))

	def keyMoveItemUp(self):
		self.moveItem(-1)

	def keyMoveItemDown(self):
		self.moveItem(1)

	def moveItem(self, direction):
		currentIndex = self["list"].getCurrentIndex()
		swapIndex = (currentIndex + direction) % len(self.list)
		if currentIndex == 0 and swapIndex != 1:
			self.list = self.list[1:] + [self.list[0]]
			self.buttonList = self.buttonList[1:] + [self.buttonList[0]]
		elif swapIndex == 0 and currentIndex != 1:
			self.list = [self.list[-1]] + self.list[:-1]
			self.buttonList = [self.buttonList[-1]] + self.buttonList[:-1]
		else:
			self.list[currentIndex], self.list[swapIndex] = self.list[swapIndex], self.list[currentIndex]
			self.buttonList[currentIndex], self.buttonList[swapIndex] = self.buttonList[swapIndex], self.buttonList[currentIndex]
		self["list"].setList(self.buildRows())
		if direction == 1:
			self["list"].goLineDown()
		else:
			self["list"].goLineUp()
		self.configOrder.value = str([entry[0] for entry in self.list])
		self.configOrder.save()

	def keyResetList(self):
		def keyResetListCallback(answer):
			if answer:
				self.configOrder.value = self.configOrder.default
				self.configOrder.save()

		self.session.openWithCallback(keyResetListCallback, MessageBox, _("Reset list order to the default list order?"), MessageBox.TYPE_YESNO, windowTitle=self.getTitle())

	def top(self):
		self.moveList(self["list"].goTop)

	def pageUp(self):
		self.moveList(self["list"].goPageUp)

	def up(self):
		self.moveList(self["list"].goLineUp)

	def down(self):
		self.moveList(self["list"].goLineDown)

	def pageDown(self):
		self.moveList(self["list"].goPageDown)

	def bottom(self):
		self.moveList(self["list"].goBottom)

	def moveList(self, step):
		step()
		if self.timeout > 0:
			self.stopTimer("Timeout stopped by user input!")
		if self.closeOnAnyKey:
			self.close(True)

	def getListInstance(self):  # The "list" widget is Source based (render="Listbox"), it has no direct '.instance' of its own.
		try:
			return self["list"].master.master.instance
		except AttributeError:
			return None

	def captureSkinGeometry(self):  # Snapshot the geometry the skin laid out, before autoResize starts moving/resizing any of these widgets. Must run exactly once, from the first layoutFinished.
		hasIcon = bool(self.typeIcon)
		iconSize = self["icon"].instance.size() if hasIcon else eSize(0, 0)
		iconPos = self["icon"].instance.position() if hasIcon else ePoint(0, 0)
		textPos = self["text"].instance.position()
		listInstance = self.getListInstance()
		self.skinGeometry = {
			"iconSize": iconSize,
			"margin": iconPos.x() if hasIcon else textPos.x(),  # Icon and text both sit at (margin, margin) in the skin, whichever is present gives the margin.
			"gap": (textPos.x() - (iconPos.x() + iconSize.width())) if hasIcon else 0,  # Icon/text gap, as laid out by the skin.
			"itemHeight": listInstance.getItemHeight() if listInstance else 0,  # The list's item height, as set by the skin template.
			"descriptionHeight": self["description"].instance.size().height()
		}

	def autoResize(self):  # Resize and re-center the dialog to fit the text (and list, if any). Replaces what used to be an onLayoutFinish skin applet.
		hasIcon = bool(self.typeIcon)
		geometry = self.skinGeometry
		iconSize = geometry["iconSize"]
		margin = geometry["margin"]
		gap = geometry["gap"]
		itemHeight = geometry["itemHeight"]
		descriptionHeight = geometry["descriptionHeight"] if self.choiceMode else 0
		orgPos = self.instance.position()
		orgSize = self.instance.size()
		listInstance = self.getListInstance()
		textX = margin + (iconSize.width() + gap if hasIcon else 0)
		self["text"].instance.resize(eSize(self.MAX_WIDTH - textX - margin, 2000))
		textSize = self["text"].instance.calculateSize()
		textWidth, textHeight = textSize.width(), textSize.height()
		topHeight = max(iconSize.height(), textHeight)
		contentWidth = max(textX + textWidth + margin, self.MIN_WIDTH)
		if hasIcon:
			contentWidth = max(contentWidth, margin + iconSize.width() + margin)
		contentWidth = min(contentWidth, self.MAX_WIDTH)
		listY = margin + topHeight + margin
		if self.list:
			listHeight = min(len(self.list), self.MAX_VISIBLE_ROWS) * itemHeight
			totalHeight = listY + listHeight + descriptionHeight + margin
		else:
			listHeight = 0
			totalHeight = listY
		self.instance.resize(eSize(contentWidth, totalHeight))
		self["text"].instance.resize(eSize(textWidth, textHeight))
		self["text"].instance.move(ePoint(textX, margin))
		if hasIcon:
			self["icon"].instance.move(ePoint(margin, margin))
		if listInstance and self.list:
			listInstance.move(ePoint(margin, listY))
			listInstance.resize(eSize(contentWidth - 2 * margin, listHeight))
			if self.choiceMode:
				self["description"].instance.move(ePoint(margin, listY + listHeight))
				self["description"].instance.resize(eSize(contentWidth - 2 * margin, descriptionHeight))
		for widget in self.additionalWidgets:  # Skin extras (background eRectangle etc.) the code has no explicit knowledge of, dock them to the new dialog size.
			if isinstance(widget.instance, eRectangle):
				widget.instance.resize(eSize(contentWidth, totalHeight))
		self.instance.move(ePoint(orgPos.x() + (orgSize.width() - contentWidth) // 2, orgPos.y() + (orgSize.height() - totalHeight) // 2))

	def createSummary(self):
		return DialogSummary

	def updateDescription(self):
		if self.choiceMode:
			current = self["list"].getCurrent()
			entry = current[self.IDX_ENTRY] if current else None
			if entry and len(entry) > 2 and isinstance(entry[2], str):
				self["description"].setText(entry[2])
			else:
				self["description"].setText("")

	def __del__(self):
		if self.updateDescription in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.remove(self.updateDescription)


class DialogSummary(ScreenSummary):
	def __init__(self, session, parent):
		ScreenSummary.__init__(self, session, parent=parent)
		self["text"] = StaticText(parent.text)
		self["option"] = StaticText("")
		self["entry"] = StaticText("")
		self["value"] = StaticText("")
		self.choiceMode = parent.choiceMode
		if self.choiceMode:
			self.entryList = []
			index = 0
			for row in self.parent["list"].getList():
				entry = row[self.parent.IDX_ENTRY]
				if entry:
					index += 1
					self.entryList.append((index, entry[0]))
				else:
					self.entryList.append((0, None))
		if parent.list:
			if self.addWatcher not in self.onShow:
				self.onShow.append(self.addWatcher)
			if self.removeWatcher not in self.onHide:
				self.onHide.append(self.removeWatcher)

	def addWatcher(self):
		if self.selectionChanged not in self.parent["list"].onSelectionChanged:
			self.parent["list"].onSelectionChanged.append(self.selectionChanged)
		self.selectionChanged()

	def removeWatcher(self):
		if self.selectionChanged in self.parent["list"].onSelectionChanged:
			self.parent["list"].onSelectionChanged.remove(self.selectionChanged)

	def selectionChanged(self):
		current = self.parent["list"].getCurrent()
		if not current:
			return
		if self.choiceMode:
			currentIndex = self.parent["list"].getCurrentIndex()
			choiceList = []
			for index, item in enumerate(self.entryList):
				if item[0]:
					if index == currentIndex:
						choiceList.append(f"> {item[1]}")
						self["value"].setText(item[1])
					else:
						choiceList.append(f"{item[0]} {item[1]}")
			index = 0 if currentIndex < 2 else currentIndex - 1
			self["entry"].setText("\n".join(choiceList[index:]))
		else:
			self["option"].setText(current[self.parent.IDX_TEXT])


class ModalDialog:
	instance = None

	def __init__(self, session):
		if ModalDialog.instance:
			print("[ModalDialog] Error: Only one ModalDialog instance is allowed!")
		else:
			ModalDialog.instance = self
			self.dialog = session.instantiateDialog(Dialog, "", enableInput=False, skinName="DialogModal")
			self.dialog.setAnimationMode(0)

	def showDialog(self, text=None, timeout=-1, list=None, default=True, closeOnAnyKey=False, timeoutDefault=None, windowTitle=None, msgBoxID=None, typeIcon=Dialog.TYPE_YESNO, enableInput=True, callback=None):
		self.dialog.text = text
		self.dialog["text"].setText(text)
		self.dialog.typeIcon = typeIcon
		self.dialog.type = typeIcon
		if typeIcon == Dialog.TYPE_YESNO:
			self.dialog.list = [(_("Yes"), True), (_("No"), False)] if list is None else list
			if isinstance(default, bool):
				self.dialog.startIndex = 0 if default else 1
			elif isinstance(default, int):
				self.dialog.startIndex = default
			else:
				print(f"[Dialog] Error: The context of the default ({default}) can't be determined!")
			self.dialog["list"].setTemplate(self.dialog.listTemplate())
			self.dialog["list"].setList(self.dialog.buildRows())
			self.dialog["list"].show()
		else:
			self.dialog["list"].hide()
			self.dialog.list = None
		self.callback = callback
		self.dialog.timeout = timeout
		self.dialog.msgBoxID = msgBoxID
		self.dialog.enableInput = enableInput
		if enableInput:
			self.dialog.createActionMap(-20)
			self.dialog["actions"].execBegin()
		self.dialog.closeOnAnyKey = closeOnAnyKey
		self.dialog.timeoutDefault = timeoutDefault
		self.dialog.windowTitle = windowTitle or self.dialog.TYPE_PREFIX.get(typeIcon, _("Message"))
		self.dialog.baseTitle = self.dialog.windowTitle
		self.dialog.activeTitle = self.dialog.windowTitle
		self.dialog.reloadLayout()
		self.dialog.close = self.close
		self.dialog.show()

	def close(self, *retVal):
		if self.callback and callable(self.callback):
			self.callback(*retVal)
		if self.dialog.enableInput:
			self.dialog["actions"].execEnd()
		self.dialog.hide()

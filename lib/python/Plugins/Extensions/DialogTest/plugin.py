from Components.ActionMap import HelpableActionMap
from Components.MenuList import MenuList
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.Dialog import Dialog
from Screens.Screen import Screen
from Tools.Directories import SCOPE_GUISKIN, resolveFilename
from Tools.LoadPixmap import LoadPixmap


class DialogTest(Screen):
	skin = """
	<screen name="DialogTest" title="Dialog Test" position="center,center" size="600,500" resolution="1280,720">
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget name="list" position="10,10" size="580,440" scrollbarMode="showOnDemand" />
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self["key_red"] = StaticText(_("Close"))
		self.tests = [
			(_("MessageBox: Yes/No question"), self.testYesNo),
			(_("MessageBox: Yes/No, default No"), self.testYesNoDefaultNo),
			(_("MessageBox: Info"), self.testInfo),
			(_("MessageBox: Warning"), self.testWarning),
			(_("MessageBox: Error"), self.testError),
			(_("MessageBox: Plain message"), self.testMessage),
			(_("MessageBox: No icon"), self.testNoIcon),
			(_("MessageBox: Custom list of choices"), self.testCustomList),
			(_("MessageBox: Long text (autoResize)"), self.testLongText),
			(_("MessageBox: Icon + image list entries"), self.testIconEntries),
			(_("MessageBox: Timeout with default"), self.testTimeout),
			(_("MessageBox: Close on any key"), self.testCloseOnAnyKey),
			(_("MessageBox: Custom window title"), self.testCustomTitle),
			(_("ChoiceBox: Default button list"), self.testChoiceDefault),
			(_("ChoiceBox: Custom button list"), self.testChoiceCustomButtons),
			(_("ChoiceBox: Entries with description"), self.testChoiceDescription),
			(_("ChoiceBox: CALLFUNC entry"), self.testChoiceCallfunc),
			(_("ChoiceBox: Cancel disabled"), self.testChoiceNoCancel),
			(_("ChoiceBox: Many entries (scrolling)"), self.testChoiceManyEntries),
		]
		self["list"] = MenuList([x[0] for x in self.tests])
		self["actions"] = HelpableActionMap(self, ["OkCancelActions"], {
			"ok": (self.runTest, _("Run the selected test")),
			"cancel": (self.close, _("Close the Dialog test menu"))
		}, prio=0, description=_("Dialog Test Actions"))
		self["colorActions"] = HelpableActionMap(self, ["ColorActions"], {
			"red": (self.close, _("Close the Dialog test menu"))
		}, prio=0, description=_("Dialog Test Actions"))

	def runTest(self):
		index = self["list"].getSelectedIndex()
		self.tests[index][1]()

	def showResult(self, result):
		self.session.open(Dialog, _("Result: %s") % (result,), Dialog.TYPE_INFO)

	# MessageBox-style tests, all opening Screens.Dialog.Dialog instead of Screens.MessageBox.MessageBox.

	def testYesNo(self):
		self.session.openWithCallback(self.showResult, Dialog, _("Do you want to continue?"), Dialog.TYPE_YESNO)

	def testYesNoDefaultNo(self):
		self.session.openWithCallback(self.showResult, Dialog, _("Do you really want to delete this?"), Dialog.TYPE_YESNO, default=False)

	def testInfo(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This is an informational message."), Dialog.TYPE_INFO)

	def testWarning(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This is a warning message."), Dialog.TYPE_WARNING)

	def testError(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This is an error message."), Dialog.TYPE_ERROR)

	def testMessage(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This is a plain message."), Dialog.TYPE_MESSAGE)

	def testNoIcon(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This message has no icon."), Dialog.TYPE_NOICON)

	def testCustomList(self):
		choices = [(_("Restart"), "restart"), (_("Shutdown"), "shutdown"), (_("Cancel"), "cancel")]
		self.session.openWithCallback(self.showResult, Dialog, _("What do you want to do?"), Dialog.TYPE_YESNO, list=choices, default=0)

	def testLongText(self):
		text = " ".join([_("This is a long text to verify that autoResize grows the dialog width and height correctly.")] * 4)
		self.session.openWithCallback(self.showResult, Dialog, text, Dialog.TYPE_INFO)

	def testIconEntries(self):
		icon = LoadPixmap(resolveFilename(SCOPE_GUISKIN, "icons/input_info.png"))
		choices = [(_("Entry with a pixmap"), "with_icon", icon), (_("Entry without a pixmap"), "without_icon")]
		self.session.openWithCallback(self.showResult, Dialog, _("Plain (non-choice) entries may carry an icon as 3rd tuple element:"), Dialog.TYPE_YESNO, list=choices, default=0)

	def testTimeout(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This dialog closes automatically in 5 seconds."), Dialog.TYPE_YESNO, timeout=5, timeoutDefault=False)

	def testCloseOnAnyKey(self):
		self.session.openWithCallback(self.showResult, Dialog, _("Press any key to close."), Dialog.TYPE_INFO, closeOnAnyKey=True)

	def testCustomTitle(self):
		self.session.openWithCallback(self.showResult, Dialog, _("This dialog has a custom window title."), Dialog.TYPE_INFO, windowTitle=_("Custom Title"))

	# ChoiceBox-style tests, all opening Screens.Dialog.Dialog instead of Screens.ChoiceBox.ChoiceBox. No reorderConfig demo.

	def testChoiceDefault(self):
		choices = [(_("First entry"), "first"), (_("Second entry"), "second"), (_("Third entry"), "third")]
		self.session.openWithCallback(self.showResult, Dialog, _("Choose an entry:"), choiceList=choices)

	def testChoiceCustomButtons(self):
		choices = [(_("Red action"), "red"), (_("Green action"), "green"), (_("Blue action"), "blue")]
		self.session.openWithCallback(self.showResult, Dialog, _("Choose a colored action:"), choiceList=choices, buttonList=["red", "green", "blue"])

	def testChoiceDescription(self):
		choices = [
			(_("Option A"), "a", _("This is the description for option A, shown below the list.")),
			(_("Option B"), "b", _("This is the description for option B, shown below the list.")),
			(_("Option C"), "c", _("This is the description for option C, shown below the list."))
		]
		self.session.openWithCallback(self.showResult, Dialog, _("Choose an option:"), choiceList=choices)

	def testChoiceCallfunc(self):
		choices = [
			(_("Show a popup (dialog stays open)"), "CALLFUNC", self.callfuncDemo),
			(_("Close with 'done'"), "done")
		]
		self.session.openWithCallback(self.showResult, Dialog, _("CALLFUNC entries run a function without closing the dialog:"), choiceList=choices)

	def callfuncDemo(self, dummy):
		self.session.open(Dialog, _("This popup was triggered by a CALLFUNC entry, the choice dialog stayed open behind it."), Dialog.TYPE_INFO)

	def testChoiceNoCancel(self):
		choices = [(_("Only way out"), "ok")]
		self.session.openWithCallback(self.showResult, Dialog, _("Cancel is disabled here, you must pick an entry:"), choiceList=choices, allowCancel=False)

	def testChoiceManyEntries(self):
		choices = [(_("Entry %d") % index, index) for index in range(1, 26)]
		self.session.openWithCallback(self.showResult, Dialog, _("More entries than fit on screen, the list scrolls:"), choiceList=choices)


def main(session, **kwargs):
	session.open(DialogTest)


def Plugins(**kwargs):
	return [PluginDescriptor(name=_("Dialog Test"), description=_("Test plugin for the Screens.Dialog MessageBox/ChoiceBox replacement."), where=[PluginDescriptor.WHERE_PLUGINMENU], fnc=main)]

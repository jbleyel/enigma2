from os.path import exists, isfile, splitext
from time import localtime

from enigma import eConsoleAppContainer

from Components.ActionMap import HelpableActionMap
from Components.ScrollLabel import ScrollLabel
from Components.Sources.StaticText import StaticText
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen


class Console(Screen):
	# The cmdList must be a mixed list or tuple of strings or lists/tuples.
	# Strings are executed by sh -c string, lists/tuples are executed by execvp(list[0], list).
	#
	def __init__(self, session, title=_("Console"), cmdlist=None, finishedCallback=None, closeOnSuccess=False):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(title)
		self.finishedCallback = finishedCallback
		if finishedCallback:
			print("[Console] Warning: Deprecation of finishedCallback. Use openWithCallback instead.")
		self.closeOnSuccess = closeOnSuccess
		self.errorOcurred = False
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Hide"))
		self["key_yellow"] = StaticText("")
		self["text"] = ScrollLabel("")
		self["summary_description"] = StaticText("")
		self["actions"] = HelpableActionMap(self, ["OkCancelActions", "NavigationActions", "ColorActions"], {
			"cancel": (self.cancel, _("Close this screen")),
			"ok": (self.cancel, _("Close this screen")),
			"red": (self.keyRed, _("Close this screen")),
			"green": (self.keyGreen, _("Hide this screen")),
			"yellow": (self.keyYellow, _("Save Log")),
			"top": (self.keyTop, _("Move to first line / screen")),
			"pageUp": (self.keyPageUp, _("Move up a screen")),
			"up": (self.keyLineUp, _("Move up a line")),
			"down": (self.keyLineDown, _("Move down a line")),
			"pageDown": (self.keyPageDown, _("Move down a screen")),
			"bottom": (self.keyBottom, _("Move to last line / screen"))
		}, prio=-1, description=_("Console Actions"))
		self.cmdlist = cmdlist
		self.screenHidden = False
		self.cancelMessage = None
		self.outputFile = ""
		self.container = eConsoleAppContainer()
		self.run = 0
		self.container.appClosed.append(self.runFinished)
		self.container.dataAvail.append(self.dataAvail)
		self.onLayoutFinish.append(self.startRun)  # Don't start before GUI is finished.

	def doExec(self, cmd):
		return self.container.execute(cmd[0], *cmd) if isinstance(cmd, (list, tuple)) else self.container.execute(cmd)

	def startRun(self):
		self["text"].setText(f"{_("Execution progress:")}\n\n")
		self["summary_description"].setText(_("Execution progress:"))
		print(f"[Console] Executing in run {self.run} the command '{self.cmdlist[self.run]}'.")
		if self.doExec(self.cmdlist[self.run]):  # Start of container application failed so we must call runFinished manually.
			self.runFinished(-1)

	def runFinished(self, retval):
		if retval:
			self.errorOcurred = True
			self.keyToggleHideShow(True)
		self.run += 1
		if self.run != len(self.cmdlist):
			if self.doExec(self.cmdlist[self.run]):  # Start of container application failed so we must call runFinished manually.
				self.runFinished(-1)
		else:
			self["key_red"].setText(_("Close"))
			self["key_green"].setText("")
			self["key_yellow"].setText(_("Save"))
			self.keyToggleHideShow(True)
			if self.cancelMessage:
				self.cancelMessage.close()
			# lastpage = self["text"].isAtLastPage()
			self["text"].appendText(f"\n{_("Execution finished!!")}")
			self["summary_description"].setText(f"\n{_("Execution finished!!")}")
			if self.finishedCallback is not None:
				self.finishedCallback()
			if not self.errorOcurred and self.closeOnSuccess:
				self.cancel()

	def keyTop(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goTop()

	def keyPageUp(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goPageUp()

	def keyLineUp(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goLineUp()

	def keyLineDown(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goLineDown()

	def keyPageDown(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goPageDown()

	def keyBottom(self):
		if self.screenHidden:
			self.keyToggleHideShow()
		else:
			self["text"].goBottom()

	def keyGreen(self):
		if self.screenHidden or self.run != len(self.cmdlist):
			self.keyToggleHideShow()

	def keyYellow(self):
		if self.outputFile.startswith("/tmp/"):
			self["text"].setText(self.readFile(self.outputFile))
			self["key_yellow"].setText("")
			self.outputFile = "end"
		elif not self.outputFile and self.run == len(self.cmdlist):
			self.saveOutputText()

	def keyRed(self):
		def cancelCallback(ret=None):
			self.cancelMessage = None
			if ret:
				self.cancel(True)
		if self.screenHidden:
			self.keyToggleHideShow()
			return
		if self.run == len(self.cmdlist):
			self.cancel()
		else:
			self.cancelMessage = self.session.openWithCallback(cancelCallback, MessageBox, _("Cancel execution?"), type=MessageBox.TYPE_YESNO, default=False, windowTitle=self.setTitle())

	def saveOutputText(self):
		def saveOutputTextCallback(ret=None):
			if ret:
				failtext = _("Path to save not exist: '/tmp/'")
				if exists("/tmp/"):
					text = "commands ...\n\n"
					try:
						cmdlist = list(self.formatCmdList(self.cmdlist))
						text += f"command line: {cmdlist[0]}\n\n"
						scriptFileName = ""
						for cmd in cmdlist[0].split():
							if "." in cmd:
								cmdPath, cmdExt = splitext(cmd)
								if cmdExt in (".py", ".pyc" ".sh"):
									scriptFileName = cmd
								break
						if scriptFileName and isfile(scriptFileName):
							text += f"script listing: {scriptFileName}\n\n{self.readFile(scriptFileName)}\n\n"
						if len(cmdlist) > 1:
							text += f"next commands:\n\n{"\n".join(cmdlist[1:])}\n\n"
					except Exception:
						text += "error read commands!!!\n\n"
					text += "-" * 50 + f"\n\noutputs ...\n\n{self['text'].getText()}"
					try:
						with open(self.outputFile, "w") as fd:
							fd.write(text)
						self["key_yellow"].setText(_("Load"))
						return
					except OSError:
						failtext = _("File write error: '%s'") % self.outputFile
				self.outputFile = "end"
				self["key_yellow"].setText("")
				self.session.open(MessageBox, failtext, type=MessageBox.TYPE_ERROR)
			else:
				self.outputFile = ""

		lt = localtime()
		self.outputFile = f"/tmp/{lt[3]:02d}{lt[4]:02d}{lt[5]:02d}_console.txt"
		# self.session.openWithCallback(saveOutputTextCallback, MessageBox, f"{_("Save the commands and the output to a file?")}\n('{self.outputFile}')", type=MessageBox.TYPE_YESNO, default=True, windowTitle=self.getTitle())
		self.session.openWithCallback(saveOutputTextCallback, MessageBox, _("Save the commands and the output to a file?\n('%s')") % self.outputFile, type=MessageBox.TYPE_YESNO, default=True, windowTitle=self.getTitle())

	def formatCmdList(self, source):
		if isinstance(source, (list, tuple)):
			for cmd in source:
				for item in self.formatCmdList(cmd):
					yield item
		else:
			yield source

	def keyToggleHideShow(self, setshow=False):
		if self.screenHidden or setshow:
			self.show()
		else:
			self.hide()
		self.screenHidden = not (self.screenHidden or setshow)

	def readFile(self, fileName):
		try:
			with open(fileName) as fd:
				data = fd.read()
		except OSError:
			if fileName == self.outputFile:
				data = self["text"].getText()
			else:
				data = f"File read error: '{fileName}'\n"
		return data

	def cancel(self, force=False):
		if self.screenHidden:
			self.keyToggleHideShow()
			return
		if force or self.run == len(self.cmdlist):
			del self.container.dataAvail[:]
			del self.container.appClosed[:]
			if self.run != len(self.cmdlist):
				print("[Console] DEBUG kill")
				self.container.kill()
			del self.container
			print("[Console] DEBUG cancel")
			self.close()

	def dataAvail(self, data):
		if isinstance(data, bytes):
			data = data.decode()
		self["text"].appendText(data)

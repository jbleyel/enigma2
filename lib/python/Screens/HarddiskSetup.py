from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Harddisk import harddiskmanager
from Components.MenuList import MenuList
from Components.Pixmap import Pixmap
from Components.Task import job_manager
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
import Screens.InfoBar


class HarddiskSetup(Screen):
	def __init__(self, session, hdd, action, text, question):
		Screen.__init__(self, session)
		self.setTitle(_("Setup Harddisk"))
		self.action = action
		self.question = question
		self.curentservice = None
		self["model"] = Label("%s: %s" % (_("Model"), hdd.model()))
		self["capacity"] = Label("%s: %s" % (_("Capacity"), hdd.capacity()))
		self["bus"] = Label(_("Bus: ") + hdd.bus())
		self["initialize"] = Pixmap()
		self["initializetext"] = Label(text)
		self["actions"] = ActionMap(["OkCancelActions"],
		{
			"ok": self.hddQuestion,
			"cancel": self.close
		})
		self["shortcuts"] = ActionMap(["ShortcutActions"],
		{
			"red": self.hddQuestion
		})

	def hddQuestion(self, answer=False):
		print("answer: %s" % answer)
		if Screens.InfoBar.InfoBar.instance and Screens.InfoBar.InfoBar.instance.timeshiftEnabled():
			message = "%s\n\n%s" % (self.question, _("You seem to be in time shift, the service will briefly stop as time shift stops."))
			message = "%s\n%s" % (message, _("Do you want to continue?"))
			self.session.openWithCallback(self.stopTimeshift, MessageBox, message)
		else:
			message = "%s\n%s" % (self.question, _("You can continue watching TV etc. while this is running."))
			self.session.openWithCallback(self.hddConfirmed, MessageBox, message)

	def stopTimeshift(self, confirmed):
		if confirmed:
			self.curentservice = self.session.nav.getCurrentlyPlayingServiceReference()
			self.session.nav.stopService()
			Screens.InfoBar.InfoBar.instance.stopTimeshiftcheckTimeshiftRunningCallback(True)
			self.hddConfirmed(True)

	def hddConfirmed(self, confirmed):
		if not confirmed:
			return
		try:
			job_manager.AddJob(self.action())
			for job in job_manager.getPendingJobs():
				if job.name in (_("Initializing storage device..."), _("Checking file system..."), _("Converting ext3 to ext4...")):
					self.showJobView(job)
					break
		except Exception as ex:
			self.session.open(MessageBox, str(ex), type=MessageBox.TYPE_ERROR, timeout=10)

		if self.curentservice:
			self.session.nav.playService(self.curentservice)
		self.close()

	def showJobView(self, job):
		from Screens.TaskView import JobView
		job_manager.in_background = False
		self.session.openWithCallback(self.JobViewCB, JobView, job, cancelable=False, afterEventChangeable=False, afterEvent="close")

	def JobViewCB(self, in_background):
		job_manager.in_background = in_background


class HarddiskSelection(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Format Storage Device"))
		self.skinName = "HarddiskSelection"  # For derived classes
		if harddiskmanager.HDDCount() == 0:
			tlist = [(_("no storage devices found"), 0)]
			self["hddlist"] = MenuList(tlist)
		else:
			self["hddlist"] = MenuList(harddiskmanager.HDDList())

		self["actions"] = ActionMap(["OkCancelActions"],
		{
			"ok": self.okbuttonClick,
			"cancel": self.close
		})

	def doIt(self, selection):
		self.session.openWithCallback(self.close, HarddiskSetup, selection,
			action=selection.createInitializeJob,
			text=_("Format"),
			question=_("Do you really want to format the device in the Linux file system?\nAll data on the device will be lost!"))

	def okbuttonClick(self):
		selection = self["hddlist"].getCurrent()
		if selection[1] != 0:
			self.doIt(selection[1])
			self.close(True)

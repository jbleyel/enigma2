from copy import deepcopy

from enigma import eDVBVolumecontrol, eServiceCenter, eServiceReference, eTimer, iPlayableService, iServiceInformation

from GlobalActions import globalActionMap
from ServiceReference import ServiceReference
from Components.ActionMap import HelpableActionMap
from Components.config import ConfigBoolean, ConfigInteger, ConfigSelection, ConfigSelectionNumber, ConfigSubsection, ConfigYesNo, NoSave, config, getConfigListEntry
from Components.Label import Label
from Components.ServiceEventTracker import ServiceEventTracker
from Components.VolumeBar import VolumeBar
from Components.Sources.StaticText import StaticText
from Screens.ChannelSelection import ChannelSelectionBase
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Directories import SCOPE_CONFIG, fileReadXML, fileWriteLines, moveFiles, resolveFilename

MODULE_NAME = __name__.split(".")[-1]


class Mute(Screen):
	pass


class Volume(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self["VolumeText"] = Label()
		self["Volume"] = VolumeBar()

	def setValue(self, volume):
		print(f"[VolumeControl] Volume set to {volume}.")
		self["VolumeText"].setText(str(volume))
		self["Volume"].setValue(volume)


class VolumeAdjustSettings(Setup):
	def __init__(self, session):
		self.volumeOffsets = VolumeAdjust.instance.getVolumeOffsets()
		self.volumeRemembered = VolumeAdjust.instance.getVolumeRemembered()
		self.initialVolumeOffsets = deepcopy(self.volumeOffsets)
		self.initialVolumeRemembered = deepcopy(self.volumeRemembered)
		Setup.__init__(self, session, setup="VolumeAdjust")
		self["key_yellow"] = StaticText()
		self["key_blue"] = StaticText()
		self["offsetActions"] = HelpableActionMap(self, ["ColorActions", "TVRadioActions"], {
			"yellow": (self.keyAddRemoveService, _("Add/Remove the current service to/from the Volume Offsets list")),
			"tvMode": (self.keyAddTVService, _("Add a TV service to the Volume Offsets list")),
			"radioMode": (self.keyAddRadioService, _("Add a RADIO service to the Volume Offsets list")),
			"tvRadioMode": (self.keyAddService, _("Add a service to the Volume Offsets list"))
		}, prio=0, description=_("Volume Adjust Actions"))
		self["currentAction"] = HelpableActionMap(self, ["ColorActions"], {
			"blue": (self.keyAddServiceReference, _("Add the current/active service to the Volume Offsets list"))
		}, prio=0, description=_("Volume Adjust Actions"))
		serviceReference = self.session.nav.getCurrentlyPlayingServiceReference()  # IanSav: Should this be using the VolumeAdjust code?
		self.activeServiceReference = serviceReference.toCompareString() if serviceReference else None
		self.volumeControl = eDVBVolumecontrol.getInstance()
		self.serviceVolume = self.volumeControl.getVolume()

	def layoutFinished(self):
		Setup.layoutFinished(self)
		self.selectionChanged()

	def createSetup(self):  # Redefine the method of the same in in the Setup class.
		self.list = []
		Setup.createSetup(self)
		volumeList = self["config"].getList()
		if config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_OFFSETS and self.volumeOffsets:
			volumeList.append(getConfigListEntry(_("Currently Defined Volume Offsets:")))
			for volumeOffset in self.volumeOffsets.keys():
				[name, delta] = self.volumeOffsets[volumeOffset]
				default = config.volumeAdjust.defaultOffset.value if delta == VolumeAdjust.NEW_VALUE else delta
				entry = NoSave(ConfigSelectionNumber(min=VolumeAdjust.OFFSET_MIN, max=VolumeAdjust.OFFSET_MAX, stepwidth=1, default=default, wraparound=False))
				if delta == VolumeAdjust.NEW_VALUE:
					delta = config.volumeAdjust.defaultOffset.value
					entry.default = VolumeAdjust.NEW_VALUE  # This triggers a cancel confirmation for unedited new entries.
				volumeList.append(getConfigListEntry(f"-   {name}", entry, _("Set the volume offset for the '%s' service.") % name, volumeOffset))
		elif config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_LAST and self.volumeRemembered:
			volumeList.append(getConfigListEntry(_("Currently Remembered Volume Levels:")))
			for volumeRemember in self.volumeRemembered.keys():
				[name, last] = self.volumeRemembered[volumeRemember]
				entry = NoSave(ConfigSelectionNumber(min=VolumeAdjust.LAST_MIN, max=VolumeAdjust.LAST_MAX, stepwidth=1, default=last, wraparound=False))
				volumeList.append(getConfigListEntry(f"-   {name}", entry, _("Set the volume level for the '%s' service.") % name, volumeRemember))
		self["config"].setList(volumeList)

	def selectionChanged(self):  # Redefine the method of the same in in the Setup class.
		if len(self["config"].getCurrent()) > 3:
			if (config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_OFFSETS and self.volumeOffsets) or (config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_LAST and self.volumeRemembered):
				self["key_yellow"].setText(_("Remove Service"))
		elif config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_OFFSETS:
			self["key_yellow"].setText(_("Add Service"))
		else:
			self["key_yellow"].setText("")
		if config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_OFFSETS and self.activeServiceReference not in self.volumeOffsets.keys():
			self["key_blue"].setText(_("Add Current"))
			self["currentAction"].setEnabled(True)
		else:
			self["key_blue"].setText("")
			self["currentAction"].setEnabled(False)
		Setup.selectionChanged(self)

	def changedEntry(self):  # Redefine the method of the same in in the Setup class. Setup method calls createSetup() when a ConfigBoolean or ConfigSelection based class is changed!
		current = self["config"].getCurrent()
		if len(current) > 3:
			value = current[1].value
			serviceReference = current[3]
			match config.volumeAdjust.adjustMode.value:
				case 1:
					name, delta = self.volumeOffsets[serviceReference]
					self.volumeOffsets[serviceReference] = [name, value]
					if serviceReference == self.activeServiceReference:  # Apply the offset if we are setting an offset for the current service.
						volume = VolumeAdjust.DEFAULT_VOLUME + value
						self.volumeControl.setVolume(volume, volume)  # Volume left, volume right.
				case 2:
					name, last = self.volumeRemembered[serviceReference]
					self.volumeRemembered[serviceReference] = [name, value]
					if serviceReference == self.activeServiceReference:  # Apply the offset if we are setting an offset for the current service.
						self.volumeControl.setVolume(value, value)  # Volume left, volume right.
		else:
			Setup.changedEntry(self)

	def keySave(self):  # Redefine the method of the same in in the Setup class.
		# IanSav: Do we need to save the changes now or do it when we shut down like VolumeControl?
		if self.volumeOffsets != self.initialVolumeOffsets or self.volumeRemembered != self.initialVolumeRemembered:  # Save the volume data if there are any changes.
			VolumeAdjust.instance.saveVolumeXML()
		VolumeAdjust.instance.refreshSettings()
		Setup.keySave(self)

	def cancelConfirm(self, result):  # Redefine the method of the same in in the Setup class.
		if not result:
			return
		if self.volumeOffsets != self.initialVolumeOffsets:
			self.volumeOffsets = deepcopy(self.initialVolumeOffsets)
		if self.volumeRemembered != self.initialVolumeRemembered:
			self.volumeRemembered = deepcopy(self.initialVolumeRemembered)
		if self.volumeControl.getVolume() != self.serviceVolume:  # Reset the offset if we were setting an offset for the current service.
			self.volumeControl.setVolume(self.serviceVolume, self.serviceVolume)  # Volume left, volume right.
		Setup.cancelConfirm(self, result)

	def keyAddRemoveService(self):
		current = self["config"].getCurrent()
		if len(current) > 3:
			serviceReference = current[3]
			match config.volumeAdjust.adjustMode.value:
				case 1:
					name = self.volumeOffsets[serviceReference][0]
					del self.volumeOffsets[serviceReference]
				case 2:
					name = self.volumeRemembered[serviceReference][0]
					del self.volumeRemembered[serviceReference]
				case _:
					name = "?"
			index = self["config"].getCurrentIndex()
			self.createSetup()
			configLength = len(self["config"].getList())
			self["config"].setCurrentIndex(index if index < configLength else configLength - 1)
			self.setFootnote(_("Service '%s' deleted.") % name)
		elif config.volumeAdjust.adjustMode.value == VolumeAdjust.MODE_OFFSETS:
			self.keyAddService()

	def keyAddTVService(self):
		self.session.openWithCallback(self.addServiceCallback, VolumeAdjustServiceSelection, "TV")

	def keyAddRadioService(self):
		self.session.openWithCallback(self.addServiceCallback, VolumeAdjustServiceSelection, "RADIO")

	def keyAddService(self):
		from Screens.InfoBar import InfoBar  # This must be here to avoid cyclic imports!
		mode = InfoBar.instance.servicelist.getCurrentMode() if InfoBar and InfoBar.instance and InfoBar.instance.servicelist else "TV"
		self.session.openWithCallback(self.addServiceCallback, VolumeAdjustServiceSelection, mode)

	def addServiceCallback(self, serviceReference):
		if serviceReference:
			serviceReference = serviceReference.toCompareString()
			serviceName = VolumeAdjust.instance.getServiceName(serviceReference)
			if serviceReference in self.volumeOffsets.keys():
				self.setFootnote(_("Service '%s' is already defined.") % serviceName)
			else:
				self.keyAddServiceReference(serviceReference, serviceName)
		else:
			self.setFootnote(_("Service selection canceled."))

	def keyAddServiceReference(self, serviceReference=None, serviceName=None):
		if serviceReference is None:
			serviceReference = self.activeServiceReference
		if serviceName is None:
			serviceName = VolumeAdjust.instance.getServiceName(serviceReference)
		if serviceReference is not None and serviceName is not None:
			self.volumeOffsets[serviceReference] = [serviceName, VolumeAdjust.NEW_VALUE]
			self.createSetup()
			self["config"].goBottom()
			self.setFootnote(_("Service '%s' added.") % serviceName)


class VolumeAdjustServiceSelection(ChannelSelectionBase):
	skin = """
	<screen name="VolumeAdjustServiceSelection" title="Volume Adjust Service Selection" position="center,center" size="560,430" resolution="1280,720">
		<widget name="list" position="0,0" size="e,e-50" scrollbarMode="showOnDemand" />
		<widget source="key_red" render="Label" position="0,e-40" size="180,40" backgroundColor="key_red" conditional="key_red" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_green" render="Label" position="190,e-40" size="180,40" backgroundColor="key_green" conditional="key_green" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_yellow" render="Label" position="380,e-40" size="180,40" backgroundColor="key_yellow" conditional="key_yellow" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_blue" render="Label" position="570,e-40" size="180,40" backgroundColor="key_blue" conditional="key_blue" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
		<widget source="key_help" render="Label" position="e-80,e-40" size="80,40" backgroundColor="key_back" conditional="key_help" font="Regular;20" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center">
			<convert type="ConditionalShowHide" />
		</widget>
	</screen>"""

	def __init__(self, session, mode):
		ChannelSelectionBase.__init__(self, session)
		self.skinName = ["VolumeAdjustServiceSelection", "SmallChannelSelection", "mySmallChannelSelection"]  # The screen "mySmallChannelSelection" is for legacy support only.
		self.setTitle(_("Volume Adjust Service Selection"))
		service = self.session.nav.getCurrentService()
		if service:
			info = service.info()
			if info:
				self.servicelist.setPlayableIgnoreService(eServiceReference(info.getInfoString(iServiceInformation.sServiceref)))
		self["volumeServiceActions"] = HelpableActionMap(self, ["SelectCancelActions", "TVRadioActions"], {
			"select": (self.keySelect, _("Select the currently highlighted service")),
			"cancel": (self.keyCancel, _("Cancel the service selection")),
			"tvRadioMode": (self.keyModeToggle, _("Toggle between the available TV and RADIO services"))
		}, prio=0, description=_("Volume Adjust Service Selection Actions"))
		self["tvAction"] = HelpableActionMap(self, ["TVRadioActions"], {
			"tvMode": (self.keyModeTV, _("Switch to the available TV services"))
		}, prio=0, description=_("Volume Adjust Service Selection Actions"))
		self["radioAction"] = HelpableActionMap(self, ["TVRadioActions"], {
			"radioMode": (self.keyModeRadio, _("Switch to the available RADIO services"))
		}, prio=0, description=_("Volume Adjust Service Selection Actions"))
		match mode:
			case "TV":
				mode = self.MODE_TV
			case "RADIO":
				mode = self.MODE_RADIO
		self.mode = mode
		self.onShown.append(self.setMode)

	def setMode(self, mode=None):
		if mode is None:
			mode = self.mode
		self["tvAction"].setEnabled(mode == self.MODE_RADIO)
		self["radioAction"].setEnabled(mode == self.MODE_TV)
		self.setCurrentMode(mode)
		self.showFavourites()

	def keySelect(self):
		serviceReference = self.getCurrentSelection()
		if (serviceReference.flags & 7) == 7:
			self.enterPath(serviceReference)
		elif not (serviceReference.flags & eServiceReference.isMarker):
			serviceReference = self.getCurrentSelection()
			self.close(serviceReference)

	def keyCancel(self):
		self.close(None)

	def keyModeToggle(self):
		self.mode = self.MODE_RADIO if self.mode == self.MODE_TV else self.MODE_TV
		self.setMode(self.mode)

	def keyModeTV(self):
		self.setMode(self.MODE_TV)

	def keyModeRadio(self):
		self.setMode(self.MODE_RADIO)


class VolumeAdjust:
	VOLUME_FILE = resolveFilename(SCOPE_CONFIG, "volume.xml")
	DEFAULT_VOLUME = 50
	DEFAULT_OFFSET = 10
	OFFSET_MIN = -100
	OFFSET_MAX = 100
	NEW_VALUE = -1000  # NEW_VALUE must not be between OFFSET_MIN and OFFSET_MAX (inclusive).
	LAST_MIN = 0
	LAST_MAX = 100

	MODE_DISABLED = 0
	MODE_OFFSETS = 1
	MODE_LAST = 2

	instance = None

	def __init__(self, session):
		print(f"[VolumeControl] DEBUG: VolumeAdjust instance address {id(self)}.")
		if VolumeAdjust.instance:
			print("[VolumeControl] Error: Only one VolumeAdjust instance is allowed!")
		else:
			VolumeAdjust.instance = self
			self.session = session
			self.volumeControl = eDVBVolumecontrol.getInstance()
			config.volumeAdjust = ConfigSubsection()
			config.volumeAdjust.adjustMode = ConfigSelection(default=self.MODE_DISABLED, choices=[
				(self.MODE_DISABLED, _("Disabled")),
				(self.MODE_OFFSETS, _("Defined volume offsets")),
				(self.MODE_LAST, _("Last used/set volume"))
			])
			config.volumeAdjust.defaultOffset = ConfigSelectionNumber(default=self.DEFAULT_OFFSET, min=self.OFFSET_MIN, max=self.OFFSET_MAX, stepwidth=1, wraparound=False)
			config.volumeAdjust.dolbyEnabled = ConfigYesNo(default=False)
			config.volumeAdjust.dolbyOffset = ConfigSelectionNumber(default=self.DEFAULT_OFFSET, min=self.OFFSET_MIN, max=self.OFFSET_MAX, stepwidth=1, wraparound=False)
			config.volumeAdjust.mpegMax = ConfigSelectionNumber(default=100, min=10, max=100, stepwidth=5)
			config.volumeAdjust.showVolumeBar = ConfigYesNo(default=False)
			self.onClose = []  # This is used by ServiceEventTracker.
			self.eventTracker = ServiceEventTracker(screen=self, eventmap={
				iPlayableService.evStart: self.eventStart,
				iPlayableService.evEnd: self.eventEnd,
				iPlayableService.evUpdatedInfo: self.processVolumeAdjustment
			})
			self.adjustMode = config.volumeAdjust.adjustMode.value  # Pre-load some stable config items to save time.
			self.mpegMax = config.volumeAdjust.mpegMax.value
			self.dolbyEnabled = config.volumeAdjust.dolbyEnabled.value
			self.defaultOffset = config.volumeAdjust.defaultOffset.value
			self.newService = [False, None]
			self.lastAdjustedValue = 0  # Remember delta from last automatic volume up/down.
			self.currentVolume = 0  # Only set when AC3 or DTS is available.
			self.pluginStarted = False  # IanSav: This code is no longer a plugin?!?!
			self.loadVolumeXML()
			self.session.onShutdown.append(self.saveVolumeXML)

	def loadVolumeXML(self):  # Load the volume adjustment configuration data.
		volumeOffsets = {}
		volumeRemembered = {}
		volumeDom = fileReadXML(self.VOLUME_FILE, source=MODULE_NAME)
		if volumeDom is None:
			print(f"[VolumeControl] Volume adjustment data initialized.")
		else:
			print(f"[VolumeControl] Volume adjustment data initialized from '{self.VOLUME_FILE}'.")
			for offsets in volumeDom.findall("offsets"):
				for offset in offsets.findall("offset"):
					reference = offset.get("reference")
					name = offset.get("name")
					delta = int(offset.get("delta", 0))
					if reference and name:
						volumeOffsets[reference] = [name, delta]
			for remembered in volumeDom.findall("remembered"):
				for remember in remembered.findall("remember"):
					reference = remember.get("reference")
					name = remember.get("name")
					last = int(remember.get("last", self.DEFAULT_VOLUME))
					if reference and name:
						volumeRemembered[reference] = [name, last]
		self.volumeOffsets = volumeOffsets
		self.volumeRemembered = volumeRemembered

	def saveVolumeXML(self):  # Save the volume adjustment configuration data.
		xml = []
		xml.append("<?xml version=\"1.0\" encoding=\"utf-8\" ?>")
		xml.append("<volumexml>")
		if self.volumeOffsets:
			xml.append("\t<offsets>")
			for volumeOffset in self.volumeOffsets.keys():
				[name, delta] = self.volumeOffsets[volumeOffset]
				xml.append(f"\t\t<offset reference=\"{volumeOffset}\" name=\"{name}\" delta=\"{delta}\" />")
			xml.append("\t</offsets>")
		if self.volumeRemembered:
			xml.append("\t<remembered>")
			for volumeRemember in self.volumeRemembered.keys():
				[name, last] = self.volumeRemembered[volumeRemember]
				xml.append(f"\t\t<remember reference=\"{volumeRemember}\" name=\"{name}\" last=\"{last}\" />")
			xml.append("\t</remembered>")
		xml.append("</volumexml>")
		if fileWriteLines(self.VOLUME_FILE, xml, source=MODULE_NAME):
			print(f"[VolumeControl] Volume adjustment data saved to '{self.VOLUME_FILE}'.")
		else:
			print(f"[VolumeControl] Volume adjustment data could not be saved to '{self.VOLUME_FILE}'!")

	def eventStart(self):
		print("[VolumeControl] eventStart DEBUG: Service start.")
		self.newService = [True, None]

	def eventEnd(self):
		print("[VolumeControl] eventEnd DEBUG: Service end.")
		if self.adjustMode == self.MODE_OFFSETS:
			# If played service had AC3 or DTS audio and volume value was changed with RC, take new delta value from the config.
			if self.currentVolume and self.volumeControl.getVolume() != self.currentVolume:
				self.lastAdjustedValue = self.newService[1] and self.volumeOffsets.get(self.newService[1].toString(), [self.getServiceName(self.newService[1]), self.defaultOffset])
		elif self.adjustMode == self.MODE_LAST:
			serviceReference = self.newService[1]
			if serviceReference and serviceReference.valid():
				self.volumeRemembered[serviceReference.toString()] = [self.getServiceName(serviceReference), self.volumeControl.getVolume()]
		self.newService = [False, None]

	def processVolumeAdjustment(self):  # This is the routine to change the volume adjustment.
		def isCurrentAudioAC3DTS():
			audioTracks = self.session.nav.getCurrentService().audioTracks()
			result = False
			if audioTracks:
				try:  # Uhh, servicemp3 sometimes leads to OverflowError errors!
					description = audioTracks.getTrackInfo(audioTracks.getCurrentTrack()).getDescription()
					print(f"[VolumeControl] DEBUG: Audio description: '{description}'.")
					if self.dolbyEnabled:
						if "AC3" in description or "DTS" in description or "Dolby Digital" == description:
							result = True
						elif description and description.split()[0] in ("AC3", "AC-3", "A_AC3", "A_AC-3", "A-AC-3", "E-AC-3", "A_EAC3", "DTS", "DTS-HD", "AC4", "AAC-HE"):
							result = True
				except Exception:
					pass
			print("[VolumeControl] DEBUG: AudioAC3Dolby is {result}.")
			return result

		def getPlayingServiceReference():
			serviceReference = self.session.nav.getCurrentlyPlayingServiceReference()
			if serviceReference:
				referenceString = serviceReference.toString()
				if "%3a//" not in referenceString and referenceString.rsplit(":", 1)[1].startswith("/"):  # Check if a movie is playing.
					info = eServiceCenter.getInstance().info(serviceReference)  # Get the eServicereference information if available.
					if info:
						serviceReference = eServiceReference(info.getInfoString(serviceReference, iServiceInformation.sServiceref))  # Get new eServicereference from meta file. No need to know if eServiceReference is valid.
			return serviceReference

		def setVolume(value):
			self.volumeControl.setVolume(value, value)  # Set new volume.
			if VolumeControl.instance:
				VolumeControl.instance.volumeDialog.setValue(value)  # Update volume control progress bar value.
				if config.volumeAdjust.showVolumeBar.value:
					VolumeControl.instance.volumeDialog.show()
					VolumeControl.instance.hideVolTimer.start(config.volumeControl.hideTimer.value * 1000, True)
			# config.volumeControl.volume.value = self.volumeControl.getVolume()  # IanSav: Isn't this now only done when Enigma2 shuts down?
			# config.volumeControl.volume.save()  # IanSav: Isn't this now only done when Enigma2 shuts down?

		if self.adjustMode and self.newService[0]:
			serviceReference = self.session.nav.getCurrentlyPlayingServiceReference()
			if serviceReference:
				print("[VolumeControl] DEBUG: Service changed.")
				self.newService = [False, serviceReference]
				self.currentVolume = 0
				if self.adjustMode == self.MODE_OFFSETS:
					self.currentAC3DTS = isCurrentAudioAC3DTS()
					if self.pluginStarted:
						if self.currentAC3DTS:  # Is this a AC3 or DTS sound track?
							serviceReference = getPlayingServiceReference()
							volume = self.volumeControl.getVolume()
							currentVolume = volume  # Remember current volume.
							volume -= self.lastAdjustedValue  # Go back to original value first.
							[name, delta] = self.volumeOffsets.get(serviceReference.toString(), [self.getServiceName(serviceReference), self.defaultOffset])  # Get the delta from config.
							if delta < 0:  # Adjust volume down.
								if volume + delta < 0:
									delta = volume * -1
							else:  # Adjust volume up.
								if volume >= 100 - delta:  # Check if delta + volume < 100.
									delta = 100 - volume  # Correct delta value.
							self.lastAdjustedValue = delta  # Save delta value.
							if (volume + delta != currentVolume):
								if delta == 0:
									delta = volume - currentVolume  # Correction for debug print only.
								setVolume(volume + self.lastAdjustedValue)
								print(f"[VolumeControl] Adjust volume for service '{self.getServiceName(serviceReference)}' by +{delta} to {self.volumeControl.getVolume()}.")
							self.currentVolume = self.volumeControl.getVolume()  # ac3||dts service , save current volume
						else:  # This must be standar MPED / PCM audio.
							if self.lastAdjustedValue != 0:
								volume = self.volumeControl.getVolume()
								delta = volume - self.lastAdjustedValue  # Restore to original volume.
								if delta > self.mpegMax:
									delta = self.mpegMax
								setVolume(delta)
								print(f"[VolumeControl] Adjust volume for service '{self.getServiceName(self.session.nav.getCurrentlyPlayingServiceReference())}' by -{volume - delta} to {self.volumeControl.getVolume()}.")
								self.lastAdjustedValue = 0  # mpeg audio, no delta here
						return  # Get out of here, nothing more to do.
				elif self.adjustMode == self.MODE_LAST:
					if self.pluginStarted:
						serviceReference = getPlayingServiceReference()
						if serviceReference.valid():
							[name, last] = self.volumeRemembered.get(serviceReference.toString(), [self.getServiceName(serviceReference), -1])
							if last != -1 and last != self.volumeControl.getVolume():
								setVolume(last)
								print(f"[VolumeControl] Set volume for service '{name}' to last saved value of {self.volumeControl.getVolume()}.")  # IanSav: Can we use last to save time?
						return  # Get out of here, nothing more to do.
			if not self.pluginStarted:
				if self.adjustMode == self.MODE_OFFSETS:
					# starting plugin, if service audio is ac3 or dts --> get delta from config...volume value is set by enigma2-system at start
					if self.currentAC3DTS:
						[name, delta] = self.volumeOffsets.get(serviceReference.toString(), [self.getServiceName(serviceReference), self.defaultOffset])
						self.lastAdjustedValue = delta
						self.currentVolume = self.volumeControl.getVolume()  # ac3||dts service , save current volume
				self.pluginStarted = True

	def getServiceName(self, serviceReference):
		return ServiceReference(serviceReference).getServiceName().replace("\xc2\x86", "").replace("\xc2\x87", "") if serviceReference else ""

	def getVolumeOffsets(self):
		return self.volumeOffsets

	def getVolumeRemembered(self):
		return self.volumeRemembered

	def refreshSettings(self):  # Refresh the cached data when the settings are changed.
		self.adjustMode = config.volumeAdjust.adjustMode.value
		self.defaultOffset = config.volumeAdjust.defaultOffset.value
		self.dolbyEnabled = config.volumeAdjust.dolbyEnabled.value
		self.mpegMax = config.volumeAdjust.mpegMax.value


# NOTE: This code does not remember the current volume as other code can change
# 	the volume directly. Always get the current volume from the driver.
#
class VolumeControl:
	"""Volume control, handles volumeUp, volumeDown, volumeMute, and other actions and display a corresponding dialog."""
	instance = None

	def __init__(self, session):
		def updateStep(configElement):
			self.volumeControl.setVolumeSteps(configElement.value)

		print(f"[VolumeControl] DEBUG: VolumeControl instance address {id(self)}.")
		if VolumeControl.instance:
			print("[VolumeControl] Error: Only one VolumeControl instance is allowed!")
		else:
			VolumeControl.instance = self
			self.volumeControl = eDVBVolumecontrol.getInstance()
			config.volumeControl = ConfigSubsection()
			config.volumeControl.volume = ConfigInteger(default=20, limits=(0, 100))
			config.volumeControl.mute = ConfigBoolean(default=False)
			config.volumeControl.pressStep = ConfigSelectionNumber(1, 10, 1, default=1)
			config.volumeControl.pressStep.addNotifier(updateStep, initial_call=True, immediate_feedback=True)
			config.volumeControl.longStep = ConfigSelectionNumber(1, 10, 1, default=5)
			config.volumeControl.hideTimer = ConfigSelectionNumber(1, 10, 1, default=3)
			global globalActionMap
			globalActionMap.actions["volumeUp"] = self.keyVolumeUp
			globalActionMap.actions["volumeDown"] = self.keyVolumeDown
			globalActionMap.actions["volumeUpLong"] = self.keyVolumeLong
			globalActionMap.actions["volumeDownLong"] = self.keyVolumeLong
			globalActionMap.actions["volumeUpStop"] = self.keyVolumeStop
			globalActionMap.actions["volumeDownStop"] = self.keyVolumeStop
			globalActionMap.actions["volumeMute"] = self.keyVolumeMute
			globalActionMap.actions["volumeMuteLong"] = self.keyVolumeMuteLong
			print("[VolumeControl] Volume control settings initialized.")
			self.muteDialog = session.instantiateDialog(Mute)
			self.muteDialog.setAnimationMode(0)
			self.volumeDialog = session.instantiateDialog(Volume)
			self.volumeDialog.setAnimationMode(0)
			self.hideTimer = eTimer()
			self.hideTimer.callback.append(self.hideVolume)
			if config.volumeControl.mute.value:
				self.volumeControl.volumeMute()
				self.muteDialog.show()
			volume = config.volumeControl.volume.value
			self.volumeDialog.setValue(volume)
			self.volumeControl.setVolume(volume, volume)
			# Compatibility interface for shared plugins.
			self.volctrl = self.volumeControl
			self.hideVolTimer = self.hideTimer
			session.onShutdown.append(self.shutdown)

	def keyVolumeUp(self):
		self.updateVolume(self.volumeControl.volumeUp(0, 0))

	def keyVolumeDown(self):
		self.updateVolume(self.volumeControl.volumeDown(0, 0))

	def keyVolumeLong(self):
		self.volumeControl.setVolumeSteps(config.volumeControl.longStep.value)

	def keyVolumeStop(self):
		self.volumeControl.setVolumeSteps(config.volumeControl.pressStep.value)

	def keyVolumeMute(self):  # This will toggle the current mute status.
		print(f"[VolumeControl] DEBUG: keyVolumeMute instance address {id(self)}.")
		isMuted = self.volumeControl.volumeToggleMute()
		if isMuted:
			self.muteDialog.show()
			self.volumeDialog.hide()
		else:
			self.muteDialog.hide()
			self.volumeDialog.setValue(self.volumeControl.getVolume())
			self.volumeDialog.show()
		config.volumeControl.mute.value = isMuted
		self.hideTimer.start(config.volumeControl.hideTimer.value * 1000, True)

	def keyVolumeMuteLong(self):  # Long press MUTE will keep the mute icon on-screen without a timeout.
		if self.volumeControl.isMuted():
			self.hideTimer.stop()

	def updateVolume(self, volume):
		if self.volumeControl.isMuted():
			self.keyVolumeMute()  # Unmute.
		else:
			self.volumeDialog.setValue(volume)
			self.volumeDialog.show()
			self.hideTimer.start(config.volumeControl.hideTimer.value * 1000, True)

	def hideVolume(self):
		self.muteDialog.hide()
		self.volumeDialog.hide()

	def shutdown(self):
		config.volumeControl.volume.setValue(self.volumeControl.getVolume())
		config.volumeControl.save()
		print("[VolumeControl] Volume control settings saved.")

	# These methods are provided for compatibility with shared plugins.
	#
	def setVolume(self):
		self.updateVolume()

	def volUp(self):
		self.keyVolumeUp()

	def volDown(self):
		self.keyVolumeDown()

	def volMute(self):
		self.keyVolumeMute()

	def volSave(self):
		pass  # Volume (and mute) saving is now done when Enigma2 shuts down.

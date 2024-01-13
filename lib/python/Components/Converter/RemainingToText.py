from time import localtime, strftime

from Components.config import config
from Components.Element import cached
from Components.Converter.Converter import Converter
from Components.Converter.Poll import Poll


class RemainingToText(Converter, Poll):
	DEFAULT = 0
	WITH_SECONDS = 2
	NO_SECONDS = 2
	IN_SECONDS = 3
	PERCENTAGE = 4
	ONLY_MINUTE = 5
	ONLY_MINUTE2 = 6
	VFD = 7
	VFD_WITH_SECONDS = 8
	VFD_NO_SECONDS = 9
	VFD_IN_SECONDS = 10
	VFD_PERCENTAGE = 11

	def __init__(self, type):
		Converter.__init__(self, type)
		Poll.__init__(self)
		type = {
			"WithSeconds": (self.WITH_SECONDS, 1000),
			"NoSeconds": (self.NO_SECONDS, 60000),
			"InSeconds": (self.IN_SECONDS, 1000),
			"Percentage": (self.PERCENTAGE, 60000),
			"VFD": (self.VFD, 0),
			"VFDWithSeconds": (self.VFD_WITH_SECONDS, 1000),
			"VFDNoSeconds": (self.VFD_NO_SECONDS, 60000),
			"VFDInSeconds": (self.VFD_IN_SECONDS, 1000),
			"VFDPercentage": (self.VFD_PERCENTAGE, 60000),
			"OnlyMinute": (self.ONLY_MINUTE, 0),
			"OnlyMinute2": (self.ONLY_MINUTE2, 0)
		}.get(type, (self.DEFAULT, 0))
		self.type = type[0]
		pollInterval = type[1]
		if pollInterval:
			self.poll_interval = pollInterval
			self.poll_enabled = True
		if self.type < self.VFD:
			if config.usage.swap_time_display_on_osd.value in ("1", "3", "5"):
				self.poll_interval = 60000
				self.poll_enabled = True
			if config.usage.swap_time_display_on_osd.value in ("2", "4"):
				self.poll_interval = 1000
				self.poll_enabled = True
		else:
			if config.usage.swap_time_display_on_vfd.value in ("1", "3", "5"):
				self.poll_interval = 60000
				self.poll_enabled = True
			if config.usage.swap_time_display_on_vfd.value in ("2", "4"):
				self.poll_interval = 1000
				self.poll_enabled = True

	@cached
	def getText(self):
		def formatDurationSHM():
			return f"{signDuration}{duration // 3600}:{duration % 3600 // 60:02d}"

		def formatDurationSHMS():
			return f"{signDuration}{duration // 3600}:{duration % 3600 // 60:02d}:{duration % 60:02d}"

		time = self.source.time
		if time is None:
			return ""
		duration = 0
		elapsed = 0
		remaining = 0
		if str(time[1]) != "None":
			if self.type < self.VFD:
				if config.usage.swap_time_remaining_on_osd.value == "0":
					duration, remaining = self.source.time
				elif config.usage.swap_time_remaining_on_osd.value == "1":
					duration, elapsed = self.source.time
				elif config.usage.swap_time_remaining_on_osd.value == "2":
					duration, elapsed, remaining = self.source.time
				elif config.usage.swap_time_remaining_on_osd.value == "3":
					duration, remaining, elapsed = self.source.time
			else:
				if config.usage.swap_time_remaining_on_vfd.value == "0":
					duration, remaining = self.source.time
				elif config.usage.swap_time_remaining_on_vfd.value == "1":
					duration, elapsed = self.source.time
				elif config.usage.swap_time_remaining_on_vfd.value == "2":
					duration, elapsed, remaining = self.source.time
				elif config.usage.swap_time_remaining_on_vfd.value == "3":
					duration, remaining, elapsed = self.source.time
		else:
			duration, remaining = self.source.time
		try:
			signDuration = ""
			if self.type < self.VFD:
				if config.usage.elapsed_time_positive_osd.value:
					signElapsed = "+"
					signRemaining = "-"
				else:
					signElapsed = "-"
					signRemaining = "+"
				if config.usage.swap_time_display_on_osd.value == "1":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 60}  {signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 60}  {signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
						else:
							text = f"{signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
					else:
						text = ngettext("%d Min", "%d Mins", (duration // 60)) % (duration // 60)

				elif config.usage.swap_time_display_on_osd.value == "2":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 60}:{elapsed % 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 60}:{elapsed % 60:02d}  {signRemaining}{remaining // 60}:{remaining % 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 60}:{remaining % 60:02d}  {signElapsed}{elapsed // 60}:{elapsed % 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 60}:{remaining % 60:02d}"
					else:
						text = f"{duration // 60}:{duration % 60:02d}"
				elif config.usage.swap_time_display_on_osd.value == "3":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
					else:
						text = formatDurationSHM()
				elif config.usage.swap_time_display_on_osd.value == "4":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
					else:
						text = formatDurationSHMS()
				elif config.usage.swap_time_display_on_osd.value == "5":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%  {signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%  {signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						else:
							text = f"{signRemaining}{(float(elapsed) / float(duration)) * 100}%%"
					else:
						text = formatDurationSHMS()
				else:
					if self.type == self.DEFAULT:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
								text = f"{signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
							elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 60}  {signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
							elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 60}  {signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
							else:
								text = f"{signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
						else:
							text = ngettext("%d Min", "%d Mins", (duration // 60)) % (duration // 60)
					elif self.type == self.ONLY_MINUTE:
						if remaining is not None:
							text = f"{remaining // 60}"
					elif self.type == self.ONLY_MINUTE2:
						now = strftime(_("%-H:%M"), localtime())
						if remaining is None:
							text = now
						if remaining is not None:
							myRestMinuten = "%+6d" % (remaining // 60) if config.usage.elapsed_time_positive_vfd.value else "%+6d" % (remaining // 60 * -1)
							if (remaining // 60) == 0:
								myRestMinuten = " "
							text = f"{now}{myRestMinuten}"
					elif self.type == self.WITH_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
							elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
							elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
							else:
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
						else:
							text = formatDurationSHMS()
					elif self.type == self.NO_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
							elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
							elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
							else:
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
						else:
							text = formatDurationSHM()
					elif self.type == self.IN_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed} "
							elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed}  {signRemaining}{remaining} "
							elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining}  {signElapsed}{elapsed} "
							else:
								text = f"{signRemaining}{remaining} "
						else:
							text = ngettext("%d Min", "%d Mins", duration) % duration
					elif self.type == self.PERCENTAGE:
						if config.usage.swap_time_remaining_on_osd.value == "1":  # Elapsed.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						elif config.usage.swap_time_remaining_on_osd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%  {signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%"
						elif config.usage.swap_time_remaining_on_osd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%  {signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						else:
							text = f"{signRemaining}{(float(elapsed) / float(duration)) * 100}%%"
					else:
						text = f"{signDuration}{duration}"

			else:
				if config.usage.elapsed_time_positive_vfd.value:
					signElapsed = "+"
					signRemaining = "-"
				else:
					signElapsed = "-"
					signRemaining = "+"
				if config.usage.swap_time_display_on_vfd.value == "1":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 60}  {signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 60}  {signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
						else:
							text = f"{signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
					else:
						text = ngettext("%d Min", "%d Mins", (duration // 60)) % (duration // 60)
				elif config.usage.swap_time_display_on_vfd.value == "2":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 60}:{elapsed % 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 60}:{elapsed % 60:02d}  {signRemaining}{remaining // 60}:{remaining % 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 60}:{remaining % 60:02d}  {signElapsed}{elapsed // 60}:{elapsed % 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 60}:{remaining % 60:02d}"
					else:
						text = f"{duration // 60}:{duration % 60:02d}"
				elif config.usage.swap_time_display_on_vfd.value == "3":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
					else:
						text = formatDurationSHM()
				elif config.usage.swap_time_display_on_vfd.value == "4":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
						else:
							text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
					else:
						text = formatDurationSHMS()
				elif config.usage.swap_time_display_on_vfd.value == "5":
					if remaining is not None:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%  {signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%  {signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						else:
							text = f"{signRemaining}{(float(elapsed) / float(duration)) * 100}%%"
					else:
						text = formatDurationSHMS()
				else:
					if self.type == self.VFD:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
								text = f"{signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
							elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 60}  {signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
							elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 60}  {signElapsed}{ngettext('%d Min', '%d Mins', (elapsed // 60)) % (elapsed // 60)}"
							else:
								text = f"{signRemaining}{ngettext('%d Min', '%d Mins', (remaining // 60)) % (remaining // 60)}"
						else:
							text = ngettext("%d Min", "%d Mins", (duration // 60)) % (duration // 60)
					elif self.type == self.VFD_WITH_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
							elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
							elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
							else:
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}"
						else:
							text = formatDurationSHMS()
					elif self.type == self.VFD_NO_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
							elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}  {signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
							elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}  {signElapsed}{elapsed // 3600}:{elapsed % 3600 // 60:02d}"
							else:
								text = f"{signRemaining}{remaining // 3600}:{remaining % 3600 // 60:02d}"
						else:
							text = formatDurationSHM()
					elif self.type == self.VFD_IN_SECONDS:
						if remaining is not None:
							if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
								text = f"{signElapsed}{elapsed} "
							elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
								text = f"{signElapsed}{elapsed}  {signRemaining}{remaining} "
							elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
								text = f"{signRemaining}{remaining}  {signElapsed}{elapsed} "
							else:
								text = f"{signRemaining}{remaining} "
						else:
							text = ngettext("%d Min", "%d Mins", duration) % duration
					elif self.type == self.VFD_PERCENTAGE:
						if config.usage.swap_time_remaining_on_vfd.value == "1":  # Elapsed.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						elif config.usage.swap_time_remaining_on_vfd.value == "2":  # Elapsed & Remaining.
							text = f"{signElapsed}{(float(elapsed) / float(duration)) * 100}%%  {signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%"
						elif config.usage.swap_time_remaining_on_vfd.value == "3":  # Remaining & Elapsed.
							text = f"{signRemaining}{(float(remaining) / float(duration)) * 100 + 1}%%  {signElapsed}{(float(elapsed) / float(duration)) * 100}%%"
						else:
							text = f"{signRemaining}{(float(elapsed) / float(duration)) * 100}%%"
					else:
						text = f"{signDuration}{duration}"
		except Exception:
			text = ""
		return text

	text = property(getText)

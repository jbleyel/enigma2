from enigma import ePoint, gRGB, eSize, eTimer

from Components.Label import Label
from Screens.Screen import Screen


class ToastScreen(Screen):
	skin = """
	<screen name="ToastScreen" position="0,520" size="1280,200" resolution="1280,720" backgroundColor="#FE000000" flags="wfNoBorder" zPosition="101">
		<widget name="border" position="0,0" size="40,40" backgroundColor="#00000000" widgetBorderColor="#FFFFFF" widgetBorderWidth="2" />
		<widget name="icon" position="0,0" size="40,40" font="enigma2icons;34" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#00000000" />
		<widget name="text" position="0,0" size="e,e" font="Regular;25" horizontalAlignment="left" verticalAlignment="center" backgroundColor="#00000000" />
	</screen>"""

	ICON_CHARS = {
		0: chr(59658),  # TYPE_INFO
		1: chr(59659),  # TYPE_WARNING
		2: chr(59657),  # TYPE_ERROR
	}

	def __init__(self, session):
		Screen.__init__(self, session)
		self["border"] = Label()
		self["icon"] = Label()
		self["text"] = Label()
		self.timer = eTimer()
		self.timer.callback.append(self.dohide)
		self.fadeTimer = eTimer()
		self.fadeTimer.callback.append(self.fade)

	def showToast(self, text, toasttype, timeout):
		self.foregroundColor = {
			Toast.TYPE_INFO: (255, 255, 255),  # white
			Toast.TYPE_WARNING: (0, 0, 0),  # black
			Toast.TYPE_ERROR: (255, 255, 255)  # white
		}.get(toasttype, (255, 255, 255))

		self.backgroundColor = {
			Toast.TYPE_INFO: (0, 0, 0),  # black
			Toast.TYPE_WARNING: (255, 165, 0),  # orange
			Toast.TYPE_ERROR: (255, 0, 0)  # red
		}.get(toasttype, (0, 0, 0))

		self["icon"].setText(self.ICON_CHARS.get(toasttype, chr(59658)))
		self["text"].setText(text)
		self.timer.start(timeout * 1000)

		BORDER_PAD = 18
		GAP = 14
		SCREEN_MARGIN = 60

		self.iconSize = self["icon"].instance.calculateSize()
		iconW = self.iconSize.width()
		iconH = self.iconSize.height()

		screenW = self.instance.size().width()
		maxTextW = screenW - SCREEN_MARGIN * 2 - BORDER_PAD * 2 - iconW - GAP
		self["text"].instance.resize(eSize(maxTextW, self.instance.size().height()))
		self.textSize = self["text"].instance.calculateSize()

		textW = self.textSize.width()
		textH = self.textSize.height()
		contentH = max(iconH, textH)
		borderW = BORDER_PAD * 2 + iconW + GAP + textW
		borderH = contentH + BORDER_PAD * 2

		startX = (screenW - borderW) // 2
		posY = self.instance.size().height() - borderH - 20

		self["border"].instance.resize(eSize(borderW, borderH))
		self["border"].instance.move(ePoint(startX, posY))
		self["icon"].instance.resize(eSize(iconW, contentH))
		self["icon"].instance.move(ePoint(startX + BORDER_PAD, posY + BORDER_PAD))
		self["text"].instance.resize(eSize(textW, textH))
		self["text"].instance.move(ePoint(startX + BORDER_PAD + iconW + GAP, posY + BORDER_PAD + (contentH - textH) // 2))

		self.fadeIn = True
		self.alpha = 255
		self._applyColors()
		self.fadeTimer.start(50)
		self.show()

	def _applyColors(self):
		fg = gRGB(*(self.foregroundColor[0], self.foregroundColor[1], self.foregroundColor[2], self.alpha))
		bg = gRGB(*(self.backgroundColor[0], self.backgroundColor[1], self.backgroundColor[2], self.alpha))
		self["border"].instance.setBackgroundColor(bg)
		self["border"].instance.setWidgetBorderColor(fg)
		self["icon"].instance.setBackgroundColor(bg)
		self["icon"].instance.setForegroundColor(fg)
		self["text"].instance.setBackgroundColor(bg)
		self["text"].instance.setForegroundColor(fg)

	def fade(self):
		if self.fadeIn:
			self.alpha -= 5
			if self.alpha <= 0:
				self.alpha = 0
				self.fadeTimer.stop()
				self.fadeIn = False
		else:
			self.alpha += 5
			if self.alpha >= 255:
				self.alpha = 255
				self.fadeTimer.stop()
				self.hide()
		self._applyColors()

	def dohide(self):
		self.timer.stop()
		self.fadeIn = False
		self.fadeTimer.start(50)

	def forceHide(self):
		self.fadeTimer.stop()
		self.timer.stop()
		self.hide()


class Toast:
	TYPE_INFO = 0
	TYPE_WARNING = 1
	TYPE_ERROR = 2
	instance = None

	def __init__(self, session):
		if Toast.instance:
			print("[Toast] Error: Only one Toast instance is allowed!")
		else:
			Toast.instance = self
			self.dialog = session.instantiateDialog(ToastScreen)
			self.dialog.hide()
			self.queue = []
			self.nextTimer = eTimer()
			self.nextTimer.callback.append(self._showNext)
			self.dialog.onHide.append(self._scheduleNext)

	def showToast(self, text, toasttype, timeout):
		timeout = max(3, min(timeout, 10))  # Minimum 3 maximum 10
		self.queue.append((text, toasttype, timeout))
		if not self.dialog.shown and not self.nextTimer.isActive():
			self._showNext()

	def _scheduleNext(self):
		if self.queue:
			self.nextTimer.start(1000, True)  # 1000 ms Pause

	def _showNext(self):
		self.nextTimer.stop()
		if not self.dialog.shown and self.queue:
			text, toasttype, timeout = self.queue.pop(0)
			self.dialog.showToast(text, toasttype, timeout)

	def doShutdown(self):
		self.nextTimer.stop()
		if self.queue:
			self.queue = None
		if self.dialog.shown:
			self.dialog.forceHide()

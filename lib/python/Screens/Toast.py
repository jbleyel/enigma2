from enigma import ePoint, gRGB, eSize, eTimer

from Components.Label import Label
from Screens.Screen import Screen


class ToastScreen(Screen):
	skin = """
	<screen name="ToastScreen" position="0,640" size="1280,80" resolution="1280,720" backgroundColor="#FE000000" flags="wfNoBorder" zPosition="101">
		<widget name="text" position="0,0" size="e,e" padding="10" conditional="text" font="Regular;25" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#00000000" borderColor="#FFFFFF" borderWidth="2" />
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
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

		self["text"].setText(text)
		self.timer.start(timeout * 1000)
		self.textSize = self["text"].instance.calculateSize()
		newsize = (self.textSize.width() + 20, self.textSize.height() + 20)
		self["text"].instance.resize(eSize(*newsize))
		newPos = ePoint((self.instance.size().width() - self.textSize.width()) // 2, self.instance.size().height() - self.textSize.height() - 40)
		self["text"].instance.move(newPos)
		self.fadeIn = True
		self.alpha = 255
		self["text"].instance.setBackgroundColor(gRGB(*(self.backgroundColor[0], self.backgroundColor[1], self.backgroundColor[2], self.alpha)))
		self["text"].instance.setForegroundColor(gRGB(*(self.foregroundColor[0], self.foregroundColor[1], self.foregroundColor[2], self.alpha)))
		self["text"].instance.setBorderColor(gRGB(*(self.foregroundColor[0], self.foregroundColor[1], self.foregroundColor[2], self.alpha)))
		self.fadeTimer.start(50)
		self.show()

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
		self["text"].instance.setBackgroundColor(gRGB(*(self.backgroundColor[0], self.backgroundColor[1], self.backgroundColor[2], self.alpha)))
		self["text"].instance.setForegroundColor(gRGB(*(self.foregroundColor[0], self.foregroundColor[1], self.foregroundColor[2], self.alpha)))
		self["text"].instance.setBorderColor(gRGB(*(self.foregroundColor[0], self.foregroundColor[1], self.foregroundColor[2], self.alpha)))

	def dohide(self):
		self.timer.stop()
		self.fadeIn = False
		self.fadeTimer.start(50)


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

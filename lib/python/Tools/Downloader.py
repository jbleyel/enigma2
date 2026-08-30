from os import unlink

from time import time

from twisted.internet import reactor
from twisted.web.client import Agent, RedirectAgent, BrowserLikePolicyForHTTPS, ResponseDone, PotentialDataLoss
from twisted.web.http_headers import Headers
from twisted.internet.protocol import Protocol


# ------------------------------------------------------------
# USER_AGENTS
# ------------------------------------------------------------
class USER_AGENTS:
	FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0"
	CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
	HBBTV = "HbbTV/1.1.1 (+PVR+RTSP+DL; Sonic; TV44; 1.32.455; 2.002) Bee/3.5"


# ------------------------------------------------------------
# SHARED HELPERS
# ------------------------------------------------------------
# NOTE: no Connection header here - Twisted's HTTP11ClientProtocol manages
# connection persistence itself. Accept-Encoding stays "identity" so the
# response length matches the bytes written to disk.
HTTP_DEFAULT_HEADERS = {
	"User-Agent": USER_AGENTS.CHROME,
	"Accept": "*/*",
	"Accept-Encoding": "identity",
}


def makeAgent(connectTimeout=5):
	base = Agent(reactor, contextFactory=BrowserLikePolicyForHTTPS(), connectTimeout=connectTimeout)
	return RedirectAgent(base)


def normaliseHeaders(headers):
	""" normalise to str """
	return {
		k.decode("utf-8") if isinstance(k, bytes) else str(k):
		v.decode("utf-8") if isinstance(v, bytes) else str(v)
		for k, v in (headers or {}).items()
	}


def buildHeaders(headers=None):
	return Headers({
		k.encode("utf-8"): [v.encode("utf-8")]
		for k, v in {**HTTP_DEFAULT_HEADERS, **(headers or {})}.items()
	})

# ------------------------------------------------------------
# STREAM PROTOCOL (no UI logic)
# ------------------------------------------------------------


class DownloadProtocol(Protocol):
	def __init__(self, downloader):
		self.downloader = downloader
		self.recv = 0

	def dataReceived(self, data):
		if self.downloader.done:
			return

		self.recv += len(data)
		try:
			self.downloader.fd.write(data)
		except OSError as err:
			self.downloader.finalise(error=err)
			return

		self.downloader.progress = self.recv

		self.downloader.pendingProgress = (
			self.recv,
			self.downloader.totalSize
		)

		if not self.downloader.uiScheduled:
			self.downloader.uiScheduled = True
			reactor.callLater(0.2, self.downloader.flushUi)

	def connectionLost(self, reason):
		if self.downloader.done:
			return

		if reason.check(ResponseDone, PotentialDataLoss):
			# PotentialDataLoss: connection closed to signal end of body for a
			# response with no reliable length (e.g. no Content-Length, HTTP/1.0).
			# Twisted can't tell that apart from a truncated transfer, but since
			# it's the only way to end such a response, treat it as complete.
			self.downloader.finalise(success=True)
		else:
			self.downloader.finalise(error=reason)


# ------------------------------------------------------------
# DOWNLOADER
# ------------------------------------------------------------
class DownloadWithProgress:

	def __init__(self, url, outputFile, *args, **kwargs):
		""" url and outputFile should be str type """
		self.url = url
		self.outputFile = outputFile

		self.progress = 0
		self.totalSize = -1  # means size not set

		self.progressCallback = None
		self.endCallback = None
		self.errorCallback = None

		self.protocol = None
		self.fd = None
		self.fileCreated = False  # only a file we opened ourselves may be removed again
		self.done = False

		self.pendingProgress = None
		self.uiScheduled = False
		self.request = None

		# for speed/eta functions
		self.startTime = None

		# headers (stored as strings internally)
		self.rawHeaders = normaliseHeaders(kwargs.get("headers", {}))
		userAgent = kwargs.get("userAgent")
		if userAgent:
			self.rawHeaders.setdefault("User-Agent", normaliseHeaders({"User-Agent": userAgent})["User-Agent"])

		# TCP connect timeout, enforced by the Agent itself
		self.connectTimeout = int(kwargs.get("connectTimeout", 5))

		# time allowed until the response headers arrive. This is a separate
		# budget from the connect timeout above: a reachable but busy mirror may
		# take a while to start answering, and killing it after connectTimeout
		# would abort perfectly good downloads.
		self.responseTimeout = int(kwargs.get("responseTimeout", 30))
		self.responseTimer = None

		self.agent = makeAgent(self.connectTimeout)

	def start(self):
		self.progress = 0
		self.totalSize = -1
		self.startTime = time()

		# No HEAD probe: it would need its own connection and TLS handshake, so
		# its answer does not arrive meaningfully earlier than the GET response
		# headers that response.length is read from anyway.
		self.startGet()
		return self

	# --------------------------------------------------------
	# GET REQUEST
	# --------------------------------------------------------
	def startGet(self):
		try:
			headers = buildHeaders(headers=self.rawHeaders)  # userAgent is already passed by headers

			self.request = self.agent.request(
				b"GET",
				self.url.encode("utf-8"),
				headers,
				None
			)

			self.request.addCallbacks(self.responseReceived, self.requestFailed)

			# RESPONSE HEADER WATCHDOG (the connect phase is the Agent's job)
			if self.responseTimeout:
				self.responseTimer = reactor.callLater(self.responseTimeout, self.onResponseTimeout)

		except Exception as err:
			self.finalise(error=err)

	# --------------------------------------------------------
	# RESPONSE
	# --------------------------------------------------------
	def responseReceived(self, response):
		self.cancelResponseTimeout()

		if self.done:
			return

		# STRICT HTTP GATE
		if not (200 <= response.code < 300):  # if not 2XX code means request failed
			self.finalise(error=Exception(f"HTTP {response.code}"))
			return

		# content-length hint from server
		# NOTE: response.headers never carries Content-Length; Twisted's HTTP/1.1
		# client consumes it internally for framing and exposes it as response.length.
		if isinstance(response.length, int) and response.length > 0:
			self.totalSize = response.length

		try:  # catch any exception while trying to create the local file
			self.fd = open(self.outputFile, "wb")
			self.fileCreated = True
		except Exception as err:
			self.finalise(error=err)
			return

		self.protocol = DownloadProtocol(self)

		response.deliverBody(self.protocol)

	# --------------------------------------------------------
	# RESPONSE TIMEOUT HANDLING
	# --------------------------------------------------------
	def cancelResponseTimeout(self):
		if self.responseTimer and self.responseTimer.active():
			self.responseTimer.cancel()
			self.responseTimer = None

	def onResponseTimeout(self):
		if self.done:
			return

		self.responseTimer = None

		# finalise() itself cancels self.request (step 1 below); doing it here first
		# would fire requestFailed's own CancelledError finalise() call before this
		# one, burying our "Response timeout" message behind the done-guard.
		self.finalise(error=Exception("Response timeout"))

	# --------------------------------------------------------
	# UI FLUSH
	# --------------------------------------------------------
	def flushUi(self):
		self.uiScheduled = False

		if self.done:
			return

		if self.pendingProgress and callable(self.progressCallback):
			progress, total = self.pendingProgress

			if total <= 0:
				total = -1

			self.progressCallback(progress, total)

	# --------------------------------------------------------
	# ERROR HANDLING
	# --------------------------------------------------------
	def requestFailed(self, failure):
		self.cancelResponseTimeout()

		if self.done:
			return

		self.finalise(error=failure)

	# --------------------------------------------------------
	# CONTROL
	# --------------------------------------------------------
	def stop(self):
		self.finalise()

	# --------------------------------------------------------
	# SINGLE EXIT POINT
	# --------------------------------------------------------
	def finalise(self, success=False, error=None):

		# Finalise download lifecycle exactly once.
		# Cleans up network/file resources and dispatches final callbacks.
		# if success=False and error=None means cancelled by stop()

		self.cancelResponseTimeout()

		if self.done:
			return

		self.done = True

		# 1. stop network
		if self.request:
			try:
				# cancel request before response body starts
				self.request.cancel()
			except Exception:
				pass

		if self.protocol and (transport := getattr(self.protocol, "transport", None)):
			try:
				# abort active response body stream
				transport.stopProducing()
			except Exception:
				pass

		# 2. close file descriptor
		if self.fd:
			try:
				self.fd.close()
			except Exception:
				pass
			self.fd = None

		# 3. remove partial file, but only when this download created it. Errors
		# raised before the file was opened (HTTP != 2xx, connect timeout, DNS)
		# must not delete an existing file of the same name left by an earlier,
		# successful download.
		if not success and self.fileCreated:
			try:
				unlink(self.outputFile)
			except OSError:
				pass

		# 4. flush a last pending progress update so fast/small downloads (which can
		# finish before the throttled 0.2s flushUi() timer ever fires) still report
		# their final progress instead of jumping straight from 0% to done.
		if success and self.pendingProgress and callable(self.progressCallback):
			progress, total = self.pendingProgress
			if total <= 0:
				total = -1
			self.progressCallback(progress, total)

		# 5. callbacks ( no callback on cancelled (i.e. forced stop()) )
		if success:
			if callable(self.endCallback):
				self.endCallback(self.outputFile)

		elif error and callable(self.errorCallback):
			self.errorCallback(error.getErrorMessage() if hasattr(error, "getErrorMessage") else str(error))

	# --------------------------------------------------------
	# CALLBACKS
	# --------------------------------------------------------
	def addProgress(self, progressCallback):
		""" progressCallback(bytesReceived, totalSize) - totalSize is -1 while the
			total is unknown (no Content-Length, e.g. a chunked response), so
			callers must guard before dividing by it. """
		self.progressCallback = progressCallback
		return self

	def addEnd(self, endCallback):
		self.endCallback = endCallback
		return self

	def addError(self, errorCallback):
		self.errorCallback = errorCallback
		return self

	def setAgent(self, userAgent):
		self.rawHeaders["User-Agent"] = normaliseHeaders({"User-Agent": userAgent})["User-Agent"]

	def addErrback(self, errorCallback):  # Temporary support for deprecated callbacks.
		print("[Downloader] Warning: DownloadWithProgress 'addErrback' is deprecated use 'addError' instead!")
		return self.addError(errorCallback)

	def addCallback(self, endCallback):  # Temporary support for deprecated callbacks.
		print("[Downloader] Warning: DownloadWithProgress 'addCallback' is deprecated use 'addEnd' instead!")
		return self.addEnd(endCallback)

	# --------------------------------------------------------
	# SPEED / ETA, for use by newer UI
	# --------------------------------------------------------
	def getSpeed(self):
		"""
		Returns current average download speed in bytes/sec.
		Returns 0 if not enough information is available.
		"""
		if not self.startTime:
			return 0

		elapsed = time() - self.startTime

		if elapsed <= 0:
			return 0

		return float(self.progress) / elapsed

	def getEta(self):
		"""
		Returns estimated seconds remaining.
		Returns -1 if total size is unknown.
		"""
		if self.totalSize <= 0:
			return -1

		speed = self.getSpeed()

		if speed <= 0:
			return -1

		remaining = self.totalSize - self.progress

		if remaining <= 0:
			return 0

		return int(remaining / speed)


# ------------------------------------------------------------
# COMPATIBILITY,
# Class names should start with a Capital letter, this
# catches old code until that code can be updated.
# ------------------------------------------------------------
class downloadWithProgress(DownloadWithProgress):
	pass

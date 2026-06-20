
# ===========================================================================
# ServiceAction – Enigma2-native socketdaemon client
#
# Follows the ServiceHelper pattern used throughout OpenATV:
#   - Socket I/O in a Twisted thread (callInThread) → never blocks main loop
#   - eTimer provides timeout fallback
#   - callback(retval: int) called exactly once (on reply or timeout)
#     retval == 0  → success
#     retval != 0  → failure (shell exit code, or 127 on timeout/unknown cmd)
#
# socketdaemon protocol:
#   Client sends:  "<COMMAND>[,<data>]\0"
#   Daemon replies: "RC:<exitcode>"
#
# Commands:
#   RESTART,<service>        → /etc/init.d/<service> restart
#   START,<service>          → /etc/init.d/<service> start
#   STOP,<service>           → /etc/init.d/<service> stop
#   SWITCH_SOFTCAM,<name>    → stop + re-link + start softcam
#   SWITCH_CARDSERVER,<name> → stop + re-link + start cardserver
#   NETRESTART               → netrestarter restart
#   NETRESTART,<iface>       → netrestarter restart <iface>
#   IFUP,<iface>             → /sbin/ifup <iface>
#   IFDOWN,<iface>           → /sbin/ifdown <iface>
#   WLANUP,<iface>           → wlanactivator start <iface>
#   WLANDOWN,<iface>         → wlanactivator stop <iface>
# ===========================================================================
from socket import socket, AF_UNIX, SOCK_STREAM
from twisted.internet.reactor import callInThread

from enigma import eTimer

socketDaemonPath = "/tmp/deamon.socket"    # typo preserved from socketdaemon main.c


class ServiceAction:
	"""Single fire-and-forget operation against the socketdaemon.

	The callback receives one int argument: the shell exit code (0 = success).
	Always keep a reference to the returned instance to prevent GC mid-flight.
	"""

	def __init__(self, serviceName: str):
		self.serviceName = serviceName
		self._socket = None
		self._callback = None
		self._timer = None
		self._timeout = 15000

	def restart(self, callback, timeout: int = 15000) -> None:
		"""RESTART,<serviceName> → callback(retval)"""
		self._callback = callback
		self._timeout = timeout
		self._send("RESTART")

	def start(self, callback, timeout: int = 15000) -> None:
		"""START,<serviceName> → callback(retval)"""
		self._callback = callback
		self._timeout = timeout
		self._send("START")

	def stop(self, callback, timeout: int = 15000) -> None:
		"""STOP,<serviceName> → callback(retval)"""
		self._callback = callback
		self._timeout = timeout
		self._send("STOP")

	@classmethod
	def netrestart(cls, callback, iface: str = "", timeout: int = 15000):
		"""NETRESTART or NETRESTART,<iface> → callback(retval)"""
		obj = cls.__new__(cls)
		obj.serviceName = iface if (iface and iface != "all") else ""
		obj._callback = callback
		obj._timeout = timeout
		obj._socket = None
		obj._timer = None
		obj._send("NETRESTART")
		return obj

	@classmethod
	def ifup(cls, iface: str, callback, timeout: int = 15000):
		"""IFUP,<iface> → /sbin/ifup <iface> → callback(retval)"""
		obj = cls(iface)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("IFUP")
		return obj

	@classmethod
	def ifdown(cls, ifaces: str | list[str], callback, timeout: int = 15000):
		"""IFDOWN,<iface[,iface…]> → /sbin/ifdown for each → callback(retval)"""
		data = ",".join(ifaces) if isinstance(ifaces, list) else ifaces
		obj = cls(data)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("IFDOWN")
		return obj

	@classmethod
	def wlanActivate(cls, iface: str, callback, timeout: int = 30000):
		"""WLANUP,<iface> → wlanactivator start <iface> → callback(retval)"""
		obj = cls(iface)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("WLANUP")
		return obj

	@classmethod
	def wlanDeactivate(cls, iface: str, callback, timeout: int = 15000):
		"""WLANDOWN,<iface> → wlanactivator stop <iface> → callback(retval)"""
		obj = cls(iface)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("WLANDOWN")
		return obj

	@classmethod
	def switchSoftcam(cls, camName: str, callback, timeout: int = 15000):
		"""SWITCH_SOFTCAM,<camName> → callback(retval)"""
		obj = cls(camName)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("SWITCH_SOFTCAM")
		return obj

	@classmethod
	def switchCardserver(cls, serverName: str, callback, timeout: int = 15000):
		"""SWITCH_CARDSERVER,<serverName> → callback(retval)"""
		obj = cls(serverName)
		obj._callback = callback
		obj._timeout = timeout
		obj._send("SWITCH_CARDSERVER")
		return obj

	def _send(self, action: str) -> None:
		self._socket = socket(AF_UNIX, SOCK_STREAM)
		self._socket.connect(socketDaemonPath)
		msg = f"{action},{self.serviceName}" if self.serviceName else action
		self._socket.send(msg.encode())
		self._wait()

	def _wait(self) -> None:
		self._timer = eTimer()
		self._timer.timeout.get().append(self._onTimeout)
		self._timer.start(self._timeout, True)
		callInThread(self._listen)

	def _listen(self) -> None:
		data = b""
		while not data:
			data = self._socket.recv(256)
		retval = 0
		try:
			text = data.decode().strip("\x00").strip()
			retval = int(text[3:]) if text.startswith("RC:") else int(text)
		except (ValueError, UnicodeDecodeError):
			pass
		self._close(retval)

	def _onTimeout(self) -> None:
		print("[ServiceAction] timeout waiting for daemon reply")
		self._close(127)

	def _close(self, retval: int = 0) -> None:
		if self._timer:
			self._timer.stop()
			self._timer = None
		if self._socket:
			self._socket.close()
			self._socket = None
		if self._callback and callable(self._callback):
			callback = self._callback
			self._callback = None
			callback(retval)

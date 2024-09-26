from socket import gethostbyaddr

from enigma import eStreamServer

from ServiceReference import ServiceReference
from Components.Element import cached
from Components.Converter.Converter import Converter
from Components.Converter.Poll import Poll

DEBUG = True


class ClientsStreaming(Converter, Poll):
	ALL = 0
	DATA = 1
	ENCODER = 2
	EXTRA_INFO = 3
	INFO = 4
	INFO_RESOLVE = 5
	INFO_RESOLVE_SHORT = 6
	IP = 7
	NAME = 8
	NUMBER = 9
	REF = 10
	SHORT_ALL = 11

	def __init__(self, token):
		Converter.__init__(self, token)
		Poll.__init__(self)
		self.poll_interval = 30000
		self.poll_enabled = True
		self.token = {
			"ALL": self.ALL,
			"DATA": self.DATA,
			"ENCODER": self.ENCODER,
			"EXTRAINFO": self.EXTRA_INFO,
			"INFO": self.INFO,
			"INFORESOLVE": self.INFO_RESOLVE,
			"INFORESOLVESHORT": self.INFO_RESOLVE_SHORT,
			"IP": self.IP,
			"NAME": self.NAME,
			"NUMBER": self.NUMBER,
			"REF": self.REF,
			"SHORTALL": self.SHORT_ALL
		}.get(token.upper().replace("_",""))  # The upper() and replace() is to maintain compatibility with the original converter even though it is inconsistent with other converters.
		if self.token is None:
			print(f"[ClientsStreaming] Error: Converter argument '{token}' is invalid!")
		self.streamServer = eStreamServer.getInstance()
		self.tokenText = tokens  # DEBUG: This is only for testing purposes.

	@cached
	def getBoolean(self):
		result = False
		if self.streamServer:
			result = self.streamServer.getConnectedClients() and True or False
		if DEBUG:
			print(f"[ClientsStreaming] DEBUG: Converter boolean token '{self.tokenText}' result is '{result}'{"." if isinstance(result, bool) else " TYPE MISMATCH!"}")
		return result

	boolean = property(getBoolean)

	@cached
	def getText(self):
		result = ""
		if self.streamServer:
			ips = []
			serviceReferences = []
			serviceNames = []
			encoders = []
			clients = []
			info = ""
			extraInfo = f"{_("ClientIP")}\t\t{_("Transcode")}\t{_("Channel")}\n\n"
			for connectedClient in self.streamServer.getConnectedClients():
				ip = connectedClient[0]
				ips.append((ip))
				if self.token in (self.INFO_RESOLVE, self.INFO_RESOLVE_SHORT):
					try:
						ip = gethostbyaddr(ip)[0]
					except Exception:
						pass
					if self.token == self.INFO_RESOLVE_SHORT:
						ip, sep, domain = ip.partition(".")  # Here ip is actually the host name.
				serviceReference = connectedClient[1]
				serviceReferences.append((serviceReference))
				serviceName = ServiceReference(serviceReference).getServiceName() or f"({_("Unknown Service")})"
				serviceNames.append((serviceName))
				if int(connectedClient[2]) == 0:
					strType = "S"
					encoder = _("No")
				else:
					strType = "T"
					encoder = _("Yes")
				encoders.append((encoder))
				clients.append((ip, serviceName, encoder))
				info = f"{info}{strType} {ip:8s} {serviceName}\n"
				extraInfo = f"{extraInfo}{ip:8s}\t{encoder}\t{serviceName}\n"
			match self.token:
				case self.ALL:
					result = "\n".join(" ".join(client) for client in clients)
				case self.DATA:
					result = clients
				case self.ENCODER:
					result = f"{_("Transcoding: ")} {" ".join(encoders)}"
				case self.EXTRA_INFO:
					result = extraInfo
				case self.INFO | self.INFO_RESOLVE | self.INFO_RESOLVE_SHORT:
					result = info
				case self.IP:
					result = " ".join(ips)
				case self.NAME:
					result = " ".join(serviceNames)
				case self.NUMBER:
					result = str(len(clients))
				case self.REF:
					result = " ".join(serviceReferences)
				case self.SHORT_ALL:
					result = _("Total clients streaming: %d ( %s )") % (len(clients), " ".join(names))
				case _:
					result = f"({_("Unknown")})"
		if DEBUG:
			print(f"[ClientsStreaming] DEBUG: Converter text token '{self.tokenText}' result is '{result}'{"." if isinstance(result, str) else " TYPE MISMATCH!"}")
		return result

	text = property(getText)

	def changed(self, what):
		Converter.changed(self, (self.CHANGED_POLL,))

	def doSuspend(self, suspended):
		pass

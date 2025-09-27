# Copyright (C) 2025 jbleyel
# This file is part of OpenATV enigma2 <https://github.com/openatv/enigma2>.
#
# RecoveryService.py is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# dogtag is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RecoveryService.py.  If not, see <http://www.gnu.org/licenses/>.

# Changelog:
# 1.0 Initial version

__version__ = "1.0"


from OpenSSL import crypto
#from OpenSSL import SSL
import os
from socket import gethostname
from time import time
from twisted.web import server, resource, proxy
from twisted.internet import reactor, ssl
import html

CA_FILE = "/etc/enigma2/ca.pem"
KEY_FILE = "/etc/enigma2/key.pem"
CERT_FILE = "/etc/enigma2/cert.pem"
CHAIN_FILE = "/etc/enigma2/chain.pem"


def toBinary(s):
	if not isinstance(s, bytes):
		return s.encode(encoding='utf-8', errors='strict')
	return s


def toString(s):
	if isinstance(s, bytes):
		try:
			return s.decode(encoding='utf-8', errors='strict')
		except UnicodeDecodeError:
			return s.decode(encoding='cp1252', errors='strict')
	return s


# This class is taken from OpenWebif with minor modifications
class SSLCertificateGenerator:

	def __init__(self):
		# define some defaults
		self.type = crypto.TYPE_RSA
		self.bits = 2048
		self.digest = 'sha256'
		self.certsubjectoptions = {
			'O': 'Home',
			'OU': gethostname(),
			'CN': gethostname()
		}

	# generate and install a self signed SSL certificate if none exists
	def installCertificates(self):
		if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
			return
		keypair = self.__genKeyPair()
		certificate = self.__genCertificate(keypair)
		print("[OpenWebif] Install newly generated key pair and certificate")
		open(KEY_FILE, "w").write(toString(crypto.dump_privatekey(crypto.FILETYPE_PEM, keypair)))
		open(CERT_FILE, "w").write(toString(crypto.dump_certificate(crypto.FILETYPE_PEM, certificate)))

	# generate a key pair
	def __genKeyPair(self):
		keypair = crypto.PKey()
		keypair.generate_key(self.type, self.bits)
		return keypair

	# create a SSL certificate and sign it
	def __genCertificate(self, keypair):
		certificate = crypto.X509()
		subject = certificate.get_subject()
		for key, val in self.certsubjectoptions.items():
			setattr(subject, key, val)
		certificate.set_serial_number(int(time()))
		certificate.gmtime_adj_notBefore(0)
		certificate.gmtime_adj_notAfter(60 * 60 * 24 * 365 * 5)
		certificate.set_issuer(subject)
		certificate.set_pubkey(keypair)
		certificate.sign(keypair, self.digest)
		return certificate


class RootLeaf(resource.Resource):
	isLeaf = True

	def render_GET(self, request):
		request.setHeader(b"content-type", b"text/html; charset=utf-8")

		html = b"""
		<!DOCTYPE html>
		<html lang=\"de\">
		<head>
			<meta charset=\"utf-8\">
			<title>Twisted HTTPS Server</title>
			<style>
				body { font-family: sans-serif; margin: 2em; }
				button { padding: 1em; margin: 0.5em; font-size: 16px; }
				iframe { width: 100%; height: 500px; border: 1px solid #ccc; margin-top: 2em; }
			</style>
		</head>
		<body>
			<h1>Twisted HTTPS Webserver</h1>
			<form method=\"POST\" action=\"/action\">
				<button name=\"cmd\" value=\"one\">Aktion 1</button>
				<button name=\"cmd\" value=\"two\">Aktion 2</button>
				<button name=\"cmd\" value=\"three\">Aktion 3</button>
			</form>

			<h2>ShellInABox</h2>
			<iframe id="shell" src="/terminal" style="display:inline-block;margin-left:10px;"></iframe>
		</body>
		</html>
		"""
		return html

	def render_POST(self, request):
		cmd = request.args.get(b"cmd", [b""])[0].decode()
		return f"<html><body><h1>Button '{html.escape(cmd)}' gedrückt!</h1><a href='/'>&lt;- zurück</a></body></html>".encode()


class RootResource(resource.Resource):
	isLeaf = False

	def __init__(self):
		resource.Resource.__init__(self)
		self.putChild(b"", RootLeaf())
		if os.path.exists('/usr/bin/shellinaboxd'):
			self.putChild(b"terminal", proxy.ReverseProxyResource('::1', 4200, b'/'))


if __name__ == "__main__":
	site = server.Site(RootResource())

	certgenerator = SSLCertificateGenerator()
	https_available = False
	try:
		certgenerator.installCertificates()
		https_available = True
	except OSError as e:
		print(f"Failed to load install SSL certificate: {e}")

	if https_available:
		try:
			key = crypto.load_privatekey(crypto.FILETYPE_PEM, open(KEY_FILE).read())
			cert = crypto.load_certificate(crypto.FILETYPE_PEM, open(CERT_FILE).read())
			chain = None
			if os.path.exists(CHAIN_FILE):
				chain = [crypto.load_certificate(crypto.FILETYPE_PEM, open(CHAIN_FILE).read())]
			sslContext = ssl.CertificateOptions(privateKey=key, certificate=cert, extraCertChain=chain)
			reactor.listenSSL(443, site, sslContext)
		except Exception as e:
			https_available = False
			print(f"Failed to load SSL certificate: {e}")

	reactor.listenTCP(80, site)
	reactor.run()

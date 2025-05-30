#include <sys/select.h>
#include <unistd.h>
#include <string.h>
#include <sys/types.h>
#include <pwd.h>
#include <shadow.h>
#include <crypt.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>

#include <lib/base/eerror.h>
#include <lib/base/init.h>
#include <lib/base/init_num.h>
#include <lib/base/wrappers.h>
#include <lib/base/esimpleconfig.h>
#include <lib/base/cfile.h>
#include <lib/base/e2avahi.h>
#include <lib/nav/core.h>

#include <lib/dvb/streamserver.h>
#include <lib/dvb/encoder.h>
#include <lib/python/python_helpers.h>

eStreamClient::eStreamClient(eStreamServer *handler, int socket, const std::string remotehost)
 : parent(handler), encoderFd(-1), streamFd(socket), streamThread(NULL), m_remotehost(remotehost), m_timeout(eTimer::create(eApp))
{
	running = false;
}

eStreamClient::~eStreamClient()
{
	rsn->stop();
	stop();
	if (streamThread)
	{
		streamThread->stop();
		delete streamThread;
	}
	if (encoderFd >= 0)
	{
		if (eEncoder::getInstance()) eEncoder::getInstance()->freeEncoder(encoderFd);
	}
	if (streamFd >= 0) ::close(streamFd);
}

void eStreamClient::start()
{
	rsn = eSocketNotifier::create(eApp, streamFd, eSocketNotifier::Read);
	CONNECT(rsn->activated, eStreamClient::notifier);
	CONNECT(m_timeout->timeout, eStreamClient::stopStream);
}

void eStreamClient::set_socket_option(int fd, int optid, int option)
{
	if(::setsockopt(fd, SOL_SOCKET, optid, &option, sizeof(option)))
		eDebug("[eStreamClient] Failed to set socket option: %m");
}

void eStreamClient::set_tcp_option(int fd, int optid, int option)
{
	if(::setsockopt(fd, SOL_TCP, optid, &option, sizeof(option)))
		eDebug("[eStreamClient] Failed to set TCP parameter: %m");
}

void eStreamClient::notifier(int what)
{
	if (!(what & eSocketNotifier::Read))
		return;

	ePtr<eStreamClient> ref = this;
	char buf[512];
	int len;
	if ((len = singleRead(streamFd, buf, sizeof(buf))) <= 0)
	{
		rsn->stop();
		stop();
		parent->connectionLost(this);
		return;
	}
	request.append(buf, len);
	if (running || (request.find('\n') == std::string::npos))
		return;

	if (request.substr(0, 5) == "GET /")
	{
		size_t pos;
		size_t posdur;
		if (eSimpleConfig::getBool("config.streaming.authentication", false))
		{
			bool authenticated = false;
			if ((pos = request.find("Authorization: Basic ")) != std::string::npos)
			{
				std::string authentication, username, password;
				std::string hash = request.substr(pos + 21);
				pos = hash.find('\r');
				hash = hash.substr(0, pos);
				authentication = base64decode(hash);
				pos = authentication.find(':');
				if (pos != std::string::npos)
				{
					char *buffer = (char*)malloc(4096);
					if (buffer)
					{
						struct passwd pwd = {};
						struct passwd *pwdresult = NULL;
						std::string crypt;
						username = authentication.substr(0, pos);
						password = authentication.substr(pos + 1);
						getpwnam_r(username.c_str(), &pwd, buffer, 4096, &pwdresult);
						if (pwdresult)
						{
							struct crypt_data cryptdata = {};
							char *cryptresult = NULL;
							cryptdata.initialized = 0;
							crypt = pwd.pw_passwd;
							if (crypt == "*" || crypt == "x")
							{
								struct spwd spwd = {};
								struct spwd *spwdresult = NULL;
								getspnam_r(username.c_str(), &spwd, buffer, 4096, &spwdresult);
								if (spwdresult)
								{
									crypt = spwd.sp_pwdp;
								}
							}
							cryptresult = crypt_r(password.c_str(), crypt.c_str(), &cryptdata);
							authenticated = cryptresult && cryptresult == crypt;
						}
						free(buffer);
					}
				}
			}
			if (!authenticated)
			{
				const char *reply = "HTTP/1.0 401 Authorization Required\r\nWWW-Authenticate: Basic realm=\"streamserver\"\r\n\r\n";
				writeAll(streamFd, reply, strlen(reply));
				rsn->stop();
				parent->connectionLost(this);
				return;
			}
		}
		pos = request.find(' ', 5);
		if (pos != std::string::npos)
		{
			std::string serviceref = urlDecode(request.substr(5, pos - 5));
			if (!serviceref.empty())
			{
				const char *reply = "HTTP/1.0 200 OK\r\nConnection: Close\r\nContent-Type: video/mpeg\r\nServer: streamserver\r\n\r\n";
				writeAll(streamFd, reply, strlen(reply));
				/* We don't expect any incoming data, so set a tiny buffer */
				set_socket_option(streamFd, SO_RCVBUF, 1 * 1024);
				 /* We like 188k packets, so set the TCP window size to that */
				set_socket_option(streamFd, SO_SNDBUF, 188 * 1024);
				/* activate keepalive */
				set_socket_option(streamFd, SO_KEEPALIVE, 1);
				/* configure keepalive */
				set_tcp_option(streamFd, TCP_KEEPINTVL, 10); // every 10 seconds
				set_tcp_option(streamFd, TCP_KEEPIDLE, 1);	// after 1 second of idle
				set_tcp_option(streamFd, TCP_KEEPCNT, 2);	// drop connection after second miss
				/* also set 10 seconds data push timeout */
				set_tcp_option(streamFd, TCP_USER_TIMEOUT, 10 * 1000);

				if (serviceref.substr(0, 10) == "file?file=") /* convert openwebif stream reqeust back to serviceref */
					serviceref = "1:0:1:0:0:0:0:0:0:0:" + serviceref.substr(10);
				/* Strip session ID from URL if it exists, PLi streaming can not handle it */
				pos = serviceref.find("&sessionid=");
				if (pos != std::string::npos) {
					serviceref.erase(pos, std::string::npos);
				}
				pos = serviceref.find("?sessionid=");
				if (pos != std::string::npos) {
					serviceref.erase(pos, std::string::npos);
				}
				pos = serviceref.find('?');
				if (pos == std::string::npos)
				{
					parent->startStream(serviceref, m_remotehost);

					eDebug("[eDVBServiceStream] stream ref: %s", serviceref.c_str());
					if (eDVBServiceStream::start(serviceref.c_str(), streamFd) >= 0)
					{
						running = true;
						m_serviceref = serviceref;
						m_useencoder = false;
					}
				}
				else
				{
					request = serviceref.substr(pos);
					serviceref = serviceref.substr(0, pos);
					/* BC support for ? instead of & as URL argument seperator */
					while((pos = request.find('?')) != std::string::npos)
					{
						request.replace(pos, 1, "&");
					}
					pos = request.find("&bitrate=");
					posdur = request.find("&duration=");
					eDebug("[eDVBServiceStream] stream ref: %s", serviceref.c_str());
					if (posdur != std::string::npos)
					{

						parent->startStream(serviceref, m_remotehost);

						if (eDVBServiceStream::start(serviceref.c_str(), streamFd) >= 0)
						{
							running = true;
							m_serviceref = serviceref;
							m_useencoder = false;
						}
						int timeout = 0;
						sscanf(request.substr(posdur).c_str(), "&duration=%d", &timeout);
						eDebug("[eDVBServiceStream] duration: %d seconds", timeout);
						if (timeout)
						{
							m_timeout->startLongTimer(timeout);
						}
					}
					else if (pos != std::string::npos)
					{
						/* we need to stream transcoded data */
						int bitrate = 1024 * 1024;
						int width = 720;
						int height = 576;
						int framerate = 25000;
						int interlaced = 0;
						int aspectratio = 0;
						int buffersize;
						std::string vcodec = "h264";
						std::string acodec = "aac";

						sscanf(request.substr(pos).c_str(), "&bitrate=%d", &bitrate);
						pos = request.find("&width=");
						if (pos != std::string::npos)
							sscanf(request.substr(pos).c_str(), "&width=%d", &width);
						pos = request.find("&height=");
						if (pos != std::string::npos)
							sscanf(request.substr(pos).c_str(), "&height=%d", &height);
						pos = request.find("&framerate=");
						if (pos != std::string::npos)
							sscanf(request.substr(pos).c_str(), "&framerate=%d", &framerate);
						pos = request.find("&interlaced=");
						if (pos != std::string::npos)
							sscanf(request.substr(pos).c_str(), "&interlaced=%d", &interlaced);
						pos = request.find("&aspectratio=");
						if (pos != std::string::npos)
							sscanf(request.substr(pos).c_str(), "&aspectratio=%d", &aspectratio);
						pos = request.find("&vcodec=");
						if (pos != std::string::npos)
						{
							vcodec = request.substr(pos + 8);
							pos = vcodec.find('&');
							if (pos != std::string::npos)
							{
								vcodec = vcodec.substr(0, pos);
							}
						}
						pos = request.find("&acodec=");
						if (pos != std::string::npos)
						{
							acodec = request.substr(pos + 8);
							pos = acodec.find('&');
							if (pos != std::string::npos)
							{
								acodec = acodec.substr(0, pos);
							}
						}
						encoderFd = -1;

						if (eEncoder::getInstance())
							encoderFd = eEncoder::getInstance()->allocateEncoder(serviceref, buffersize, bitrate, width, height, framerate, !!interlaced, aspectratio,
									vcodec, acodec);

						if (encoderFd >= 0)
						{
							m_serviceref = serviceref;
							m_useencoder = true;

							streamThread = new eDVBRecordStreamThread(188, buffersize);

							if (streamThread)
							{
								streamThread->setTargetFD(streamFd);
								streamThread->start(encoderFd);
								running = true;
							}
						}
					}
				}
			}
		}
	}
	if (!running)
	{
		const char *reply = "HTTP/1.0 400 Bad Request\r\n\r\n";
		writeAll(streamFd, reply, strlen(reply));
		rsn->stop();
		parent->connectionLost(this);
		return;
	}
	request.clear();
}

void eStreamClient::stopStream()
{
	ePtr<eStreamClient> ref = this;
	rsn->stop();
	parent->connectionLost(this);
}

std::string eStreamClient::getRemoteHost()
{
	return m_remotehost;
}

std::string eStreamClient::getServiceref()
{
	return m_serviceref;
}

bool eStreamClient::isUsingEncoder()
{
	return m_useencoder;
}

DEFINE_REF(eStreamServer);

eStreamServer *eStreamServer::m_instance = NULL;

eStreamServer::eStreamServer()
 : eServerSocket(8001, eApp)
{
	m_instance = this;
	e2avahi_announce(NULL, "_e2stream._tcp", 8001);
}

eStreamServer::~eStreamServer()
{
	for (eSmartPtrList<eStreamClient>::iterator it = clients.begin(); it != clients.end(); )
	{
		it = clients.erase(it);
	}
}

eStreamServer *eStreamServer::getInstance()
{
	return m_instance;
}

void eStreamServer::newConnection(int socket)
{
	ePtr<eStreamClient> client = new eStreamClient(this, socket, RemoteHost());
	clients.push_back(client);
	client->start();
}

void eStreamServer::connectionLost(eStreamClient *client)
{
	eSmartPtrList<eStreamClient>::iterator it = std::find(clients.begin(), clients.end(), client );
	if (it != clients.end())
	{
        std::string serviceref = it->getServiceref();
		if(serviceref.empty())
			serviceref = it->getDVBService().toString();
        std::string client = it->getRemoteHost();
		clients.erase(it);
		streamStatusChanged(2,serviceref.c_str(), client.c_str());
		eNavigation::getInstance()->removeStreamService(serviceref);
	}
}

void eStreamServer::startStream(const std::string serviceref, const std::string remotehost)
{
	streamStatusChanged(0,serviceref.c_str(), remotehost.c_str());
	eNavigation::getInstance()->addStreamService(serviceref);
}

void eStreamServer::stopStream()
{
	eSmartPtrList<eStreamClient>::iterator it = clients.begin();
	if (it != clients.end())
	{
		streamStatusChanged(1,it->getServiceref().c_str(), it->getRemoteHost().c_str());
		eNavigation::getInstance()->removeStreamService(it->getServiceref());
		it->stopStream();
	}
}

bool eStreamServer::stopStreamClient(const std::string remotehost, const std::string serviceref)
{
	for (eSmartPtrList<eStreamClient>::iterator it = clients.begin(); it != clients.end(); ++it)
	{
		if(it->getRemoteHost() == remotehost && it->getServiceref() == serviceref)
		{
			it->stopStream();
			return true;
		}
	}
	return false;
}

PyObject *eStreamServer::getConnectedClientDetails(int index)
{
	ePyObject ret;

	eUsePtr<iDVBChannel> stream_channel;
	eServiceReferenceDVB dvbservice;

	int idx = 0;
	for (eSmartPtrList<eStreamClient>::iterator it = clients.begin(); it != clients.end(); ++it)
	{
		if(idx == index)
		{
			dvbservice = it->getDVBService();
			break;
		}
	}

	if(dvbservice)
	{
		std::list<eDVBResourceManager::active_channel> list;
		ePtr<eDVBResourceManager> res_mgr;
		if ( !eDVBResourceManager::getInstance( res_mgr ) )
		{
			res_mgr->getActiveChannels(list);
		}

		if(list.size()) {
		
			eDVBChannelID channel;
			dvbservice.getChannelID(channel);

			for (std::list<eDVBResourceManager::active_channel>::iterator i(list.begin()); i != list.end(); ++i)
			{
				std::string channelid = i->m_channel_id.toString();
				if (channelid == channel.toString().c_str())
				{
					stream_channel = i->m_channel;
					break;
				}
			}
					
		}

	}

	ret = PyDict_New();

	if(stream_channel)
	{

		ePtr<iDVBFrontend> fe;
		if(!stream_channel->getFrontend(fe))
		{

			ePtr<iDVBFrontendData> fdata;
			fe->getFrontendData(fdata);
			if (fdata)
			{
				ePyObject fret = PyDict_New();;
				frontendDataToDict(fret, fdata);
				PutToDict(ret, "frontend", fret);
			}


			ePtr<iDVBTransponderData> tdata;
			fe->getTransponderData(tdata, true);
			if (tdata)
			{
				ePyObject tret = PyDict_New();;
				transponderDataToDict(tret, tdata);
				PutToDict(ret, "transponder", tret);
			}

		}

	}

	return ret;

}

PyObject *eStreamServer::getConnectedClients()
{
	ePyObject ret;
	int idx = 0;
	int cnt = clients.size();
	ret = PyList_New(cnt);
	for (eSmartPtrList<eStreamClient>::iterator it = clients.begin(); it != clients.end(); ++it)
	{
		ePyObject tuple = PyTuple_New(3);
		PyTuple_SET_ITEM(tuple, 0, PyUnicode_FromString((char *)it->getRemoteHost().c_str()));
		PyTuple_SET_ITEM(tuple, 1, PyUnicode_FromString((char *)it->getServiceref().c_str()));
		PyTuple_SET_ITEM(tuple, 2, PyLong_FromLong(it->isUsingEncoder()));
		PyList_SET_ITEM(ret, idx++, tuple);
	}
	return ret;
}

eAutoInitPtr<eStreamServer> init_eStreamServer(eAutoInitNumbers::service + 1, "Stream server");

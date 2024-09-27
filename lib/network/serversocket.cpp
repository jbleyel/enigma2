#include <errno.h>
#include <string.h>
#include <lib/network/serversocket.h>
#include <arpa/inet.h>

bool eServerSocket::ok()
{
	return okflag;
}

void eServerSocket::notifier(int handle)
{
	eDebug("eServerSocket:notifier handle=%d", handle);

	int clientfd;
	socklen_t clientlen;
// handle multiple socket types...
	union
	{
		sockaddr sock;
		sockaddr_in sock_in;
		sockaddr_in6 sock_in6;
	} client_addr;

	char straddr[INET6_ADDRSTRLEN];

#ifdef DEBUG_SERVERSOCKET
	eDebug("[eServerSocket] incoming connection!");
#endif

	clientlen = sizeof(client_addr);
	clientfd = accept(getDescriptor(), &client_addr.sock, &clientlen);
	if (clientfd < 0)
	{
		eDebug("[eServerSocket] error on accept: %m");
		return;
	}

	switch(client_addr.sock.sa_family)
	{
		case(AF_LOCAL):
		{
			strRemoteHost = "(local)";
			break;
		}

		case(AF_INET):
		{
			strRemoteHost = inet_ntop(AF_INET, &client_addr.sock_in.sin_addr, straddr, sizeof(straddr));
			break;
		}

		case(AF_INET6):
		{
			if(IN6_IS_ADDR_V4MAPPED(&client_addr.sock_in6.sin6_addr))
			{
				 // ugly hack to get real ipv4 address without the ::ffff:, inet_ntop doesn't have an option for it
				strRemoteHost = inet_ntop(AF_INET, (sockaddr_in *)&client_addr.sock_in6.sin6_addr.s6_addr[12], straddr, sizeof(straddr));
			}
			else
				strRemoteHost = inet_ntop(AF_INET6, &client_addr.sock_in6.sin6_addr, straddr, sizeof(straddr));

			break;
		}

		default:
		{
			strRemoteHost = "(error)";
			break;
		}
	}

	eDebug("eServerSocket:newConnection clientfd=%d", clientfd);

	newConnection(clientfd);
}


/*
void eServerSocket::notifier(int)
{
	int clientfd, clientlen;
	struct sockaddr_in6 client_addr;
	char straddr[INET6_ADDRSTRLEN];

#ifdef DEBUG_SERVERSOCKET
	eDebug("[eServerSocket] incoming connection!");
#endif

	clientlen=sizeof(client_addr);
	clientfd=accept(getDescriptor(),
			(struct sockaddr *) &client_addr,
			(socklen_t*)&clientlen);
	if(clientfd<0)
		eDebug("[eServerSocket] error on accept()");


	inet_ntop(AF_INET6, &client_addr.sin6_addr, straddr, sizeof(straddr));
	strRemoteHost=straddr;
	newConnection(clientfd);
}
*/

eServerSocket::eServerSocket(int port, eMainloop *ml): eSocket(ml)
{
	int res;
	struct addrinfo *addr = NULL;
	struct addrinfo hints = {};
	char portnumber[16] = {};

	okflag = 0;
	strRemoteHost = "";

	memset(&hints, 0, sizeof(hints));
	hints.ai_family = AF_UNSPEC; /* both ipv4 and ipv6 */
	hints.ai_socktype = SOCK_STREAM;
	hints.ai_protocol = 0; /* any */
#ifdef AI_ADDRCONFIG
	hints.ai_flags = AI_PASSIVE | AI_NUMERICSERV | AI_ADDRCONFIG; /* only return ipv6 if we have an ipv6 address ourselves, and ipv4 if we have an ipv4 address ourselves */
#else
	hints.ai_flags = AI_PASSIVE | AI_NUMERICSERV; /* AI_ADDRCONFIG is not available */
#endif
	snprintf(portnumber, sizeof(portnumber), "%d", port);

	if ((res = getaddrinfo(NULL, portnumber, &hints, &addr)) || !addr)
	{
		eDebug("[eServerSocket] getaddrinfo: %s", gai_strerror(res));
		return;
	}

	if (startListening(addr) >= 0)
	{
		okflag = 1;
		rsn->setRequested(eSocketNotifier::Read);
	}
	freeaddrinfo(addr);
}



/*
eServerSocket::eServerSocket(int port, eMainloop *ml): eSocket(ml, AF_INET6), m_port(port)
{
	struct sockaddr_in6 serv_addr;
	strRemoteHost = "";

	bzero(&serv_addr, sizeof(serv_addr));
	serv_addr.sin6_family=AF_INET6;
	serv_addr.sin6_addr=in6addr_any;
	serv_addr.sin6_port=htons(port);

	okflag=1;
	int val=1;
	int v6only=0;

	setsockopt(getDescriptor(), SOL_SOCKET, SO_REUSEADDR, &val, sizeof(val));
	setsockopt(getDescriptor(), IPPROTO_IPV6, IPV6_V6ONLY, &v6only, sizeof(v6only));

	if(bind(getDescriptor(),
		(struct sockaddr *) &serv_addr,
		sizeof(serv_addr))<0)
	{
		eDebug("[eServerSocket] ERROR on bind() (%m)");
		okflag=0;
	}
#if HAVE_HISILICON
	listen(getDescriptor(), 10);
#else
	listen(getDescriptor(), 0);
#endif

	rsn->setRequested(eSocketNotifier::Read);
}
*/


eServerSocket::eServerSocket(std::string path, eMainloop *ml) : eSocket(ml)
{
	eDebug("eServerSocket::eServerSocket path=%s", path.c_str());
	struct sockaddr_un serv_addr_un = {};
	struct addrinfo addr = {};

	okflag = 0;
	strRemoteHost = "";

	memset(&serv_addr_un, 0, sizeof(serv_addr_un));
	serv_addr_un.sun_family = AF_LOCAL;
	strcpy(serv_addr_un.sun_path, path.c_str());

	memset(&addr, 0, sizeof(addr));
	addr.ai_family = AF_LOCAL;
	addr.ai_socktype = SOCK_STREAM;
	addr.ai_protocol = 0; /* any */
	addr.ai_addr = (struct sockaddr *)&serv_addr_un;
	addr.ai_addrlen = sizeof(serv_addr_un);

	unlink(path.c_str());

	if (startListening(&addr) >= 0)
	{
		okflag = 1;
		rsn->setRequested(eSocketNotifier::Read);
	}
}
/*
eServerSocket::eServerSocket(std::string path, eMainloop *ml) : eSocket(ml, AF_LOCAL)
{
	struct sockaddr_un serv_addr;
	strRemoteHost = "";
	m_port = 0;

	memset(&serv_addr, 0, sizeof(serv_addr));
	serv_addr.sun_family = AF_LOCAL;
	strcpy(serv_addr.sun_path, path.c_str());

	okflag=1;
	m_port = 0;

	unlink(path.c_str());
#if HAVE_LINUXSOCKADDR
	if(bind(getDescriptor(),
	(struct sockaddr *) &serv_addr,
	strlen(serv_addr.sun_path) + sizeof(serv_addr.sun_family))<0)
#else
	if(bind(getDescriptor(),
		(struct sockaddr *) &serv_addr,
		sizeof(serv_addr))<0)
#endif
	{
		eDebug("[eServerSocket] ERROR on bind() (%m)");
		okflag=0;
	}
#if HAVE_HISILICON
	listen(getDescriptor(), 10);
#else
	listen(getDescriptor(), 0);
#endif

	rsn->setRequested(eSocketNotifier::Read);
}
*/

eServerSocket::~eServerSocket()
{
#ifdef DEBUG_SERVERSOCKET
	eDebug("[eServerSocket] destructed");
#endif
}

int eServerSocket::startListening(struct addrinfo *addr)
{
	eDebug("eServerSocket::startListening");
	struct addrinfo *ptr;

	for (ptr = addr; ptr != NULL; ptr = ptr->ai_next)
	{
		if (setSocket(socket(ptr->ai_family, ptr->ai_socktype, ptr->ai_protocol), 1) < 0)
		{
			continue;
		}

		int val = 1;
		setsockopt(getDescriptor(), SOL_SOCKET, SO_REUSEADDR, &val, sizeof(val));

		if (bind(getDescriptor(), ptr->ai_addr, ptr->ai_addrlen) < 0)
		{
			eDebug("[eServerSocket] ERROR on bind: %m");
			close();
			continue;
		}
	}

	if (getDescriptor() < 0)
	{
		return -1;
	}
#if HAVE_HISILICON
	if (listen(getDescriptor(), 10) < 0)
#else
	if (listen(getDescriptor(), 0) < 0)
#endif
	{
		close();
		return -1;
	}
	return 0;
}

int eServerSocket::bind(int sockfd, struct sockaddr *addr, socklen_t addrlen)
{
	int result;
	while (1)
	{
		if ((result = ::bind(sockfd, addr, addrlen)) < 0 && errno == EINTR) continue;
		break;
	}
	return result;
}

int eServerSocket::listen(int sockfd, int backlog)
{
	int result;
	while (1)
	{
		if ((result = ::listen(sockfd, backlog)) < 0 && errno == EINTR) continue;
		break;
	}
	return result;
}

int eServerSocket::accept(int sockfd, struct sockaddr *addr, socklen_t *addrlen)
{
	int result;
	while (1)
	{
		if ((result = ::accept(sockfd, addr, addrlen)) < 0 && errno == EINTR) continue;
		break;
	}
	return result;
}

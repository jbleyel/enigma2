#pragma once

#include <lib/base/object.h>
#include <lib/python/connections.h>
#include <lib/python/python.h>

#ifndef SWIG
#include <libsig_comp.h>
#include <avahi-client/lookup.h>
#include <map>
#include <string>
#include <utility>
#include <vector>

class eTimer;
#endif

/* Browses one or more mDNS/DNS-SD service types (e.g. "_smb._tcp") and
 * exposes fully resolved instances (address, interface, TXT records) to
 * Python. Complements e2avahi_resolve()/e2avahi.h, which only forwards
 * name/type/hostname/port and cannot be driven from Python directly
 * (a bare C callback pointer isn't usable there). Does not replace the
 * existing API - lib/service/servicepeer.cpp keeps using it unchanged. */
class eNetworkServiceBrowser: public sigc::trackable, public iObject
{
	DECLARE_REF(eNetworkServiceBrowser);

#ifndef SWIG
	struct Instance
	{
		int interfaceIndex;
		int protocol; /* AVAHI_PROTO_INET / AVAHI_PROTO_INET6 */
		std::string serviceName;
		std::string serviceType;
		std::string domain;
		std::string hostname;
		std::vector<std::string> addresses; /* literal, already resolved - no NSS/.local lookup needed */
		unsigned short port;
		std::vector<std::pair<std::string, std::string> > txt;
	};
	/* interfaceIndex:protocol:serviceName:serviceType:domain - the tuple that
	 * uniquely identifies one service instance, not just its name. */
	typedef std::string InstanceKey;

	std::map<InstanceKey, Instance> m_instances;
	std::vector<std::string> m_serviceTypes;
	std::map<std::string, AvahiServiceBrowser*> m_browsers;
	std::map<std::string, bool> m_allForNow;
	bool m_started;
	bool m_failed;
	ePtr<eTimer> m_restartTimer;
	int m_backoffMs;

	static InstanceKey makeKey(int interfaceIndex, int protocol,
		const char *name, const char *type, const char *domain);

	void tryRegister(const std::string &serviceType);
	void handleBrowserEvent(AvahiServiceBrowser *browser, int interfaceIndex, int protocol,
		AvahiBrowserEvent event, const char *name, const char *type,
		const char *domain, AvahiLookupResultFlags flags);
	void handleResolverEvent(int interfaceIndex, int protocol,
		AvahiResolverEvent event, const char *name, const char *type,
		const char *domain, const char *hostName, const AvahiAddress *address,
		unsigned short port, AvahiStringList *txt, AvahiLookupResultFlags flags);
	void scheduleRestart();
	void restartTimeout();

	static void avahiBrowserCallback(AvahiServiceBrowser *browser,
		AvahiIfIndex iface, AvahiProtocol proto, AvahiBrowserEvent event,
		const char *name, const char *type, const char *domain,
		AvahiLookupResultFlags flags, void *userdata);
	static void avahiResolverCallback(AvahiServiceResolver *resolver,
		AvahiIfIndex iface, AvahiProtocol proto, AvahiResolverEvent event,
		const char *name, const char *type, const char *domain,
		const char *hostName, const AvahiAddress *address, uint16_t port,
		AvahiStringList *txt, AvahiLookupResultFlags flags, void *userdata);

	friend void e2avahi_networkservicebrowser_try_register_all();
	friend void e2avahi_networkservicebrowser_reset_all();
	friend void e2avahi_networkservicebrowser_clear_all();
#endif

public:
	eNetworkServiceBrowser();
	~eNetworkServiceBrowser();

	/* Can be called before start() or while already running - a type added
	 * later starts browsing immediately if the browser is already started. */
	void addServiceType(const char *serviceType);

	void start();
	void stop();

	/* Snapshot of all currently known service instances, as a list of dicts
	 * with keys: name, type, domain, hostname, addresses (list of str),
	 * port, interface (int ifindex), protocol ("inet"/"inet6"), txt (dict).
	 * Call after `changed` fires. */
	PyObject *getServices();

	/* Fires on every instance ADD/REMOVE, on ALL_FOR_NOW (initial browse
	 * results for one of the added service types are complete) and on
	 * FAILURE (temporary, browser resubscribes with backoff). No payload -
	 * call getServices() again to get the current snapshot. */
	PSignal0<void> changed;
};

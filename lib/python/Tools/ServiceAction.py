
# ===========================================================================
# ServiceAction – Python wrapper around eServiceActionClient (C++)
#
# Keeps the same public API as before but delegates all I/O to the C++
# singleton which uses eSocketNotifier (non-blocking, no Twisted thread).
#
# Protocol sent to socketdaemon:
#   "ACTION <id> <TYPE> [<data>]\n"
# Response:
#   "DONE <id> <exitcode>\n"  or  "ERROR <id> <exitcode>\n"
#
# callback(exitCode: int) is called exactly once (on reply or timeout).
# exitCode == 0  → success,  exitCode != 0  → failure/timeout.
# ===========================================================================
from enigma import eServiceActionClient as _C


class ServiceAction:
    """Thin Python wrapper around eServiceActionClient.

    Usage is identical to the old Twisted-based version – the callback
    receives one int: the daemon's shell exit code (0 = success).

    Instance methods (restart/start/stop) use self.serviceName.
    Class methods (ifup, ifdown, …) create and return a new instance.
    """

    _cbs: dict[int, object] = {}
    _hooked: bool = False

    def __init__(self, serviceName: str):
        self.serviceName = serviceName
        ServiceAction._ensure_hooked()

    @classmethod
    def _ensure_hooked(cls) -> None:
        if not cls._hooked:
            _C.getInstance().actionResult.get().append(cls._on_result)
            cls._hooked = True

    @classmethod
    def _on_result(cls, reqId: int, exitCode: int) -> None:
        cb = cls._cbs.pop(reqId, None)
        if cb and callable(cb):
            cb(exitCode)

    @classmethod
    def _dispatch(cls, action: str, data: str, callback, timeout: int) -> int:
        cls._ensure_hooked()
        reqId = int(_C.getInstance().sendAction(action, data, timeout))
        if callback and callable(callback):
            cls._cbs[reqId] = callback
        return reqId

    # ---- instance methods ------------------------------------------------

    def restart(self, callback, timeout: int = 15000) -> None:
        """RESTART,<serviceName> → callback(exitCode)"""
        ServiceAction._dispatch("RESTART", self.serviceName, callback, timeout)

    def start(self, callback, timeout: int = 15000) -> None:
        """START,<serviceName> → callback(exitCode)"""
        ServiceAction._dispatch("START", self.serviceName, callback, timeout)

    def stop(self, callback, timeout: int = 15000) -> None:
        """STOP,<serviceName> → callback(exitCode)"""
        ServiceAction._dispatch("STOP", self.serviceName, callback, timeout)

    # ---- class-method factories ------------------------------------------

    @classmethod
    def netrestart(cls, callback, iface: str = "", timeout: int = 15000) -> "ServiceAction":
        """NETRESTART or NETRESTART,<iface> → callback(exitCode)"""
        data = iface if (iface and iface != "all") else ""
        cls._dispatch("NETRESTART", data, callback, timeout)
        obj = cls.__new__(cls)
        obj.serviceName = data
        return obj

    @classmethod
    def ifup(cls, iface: str, callback, timeout: int = 15000) -> "ServiceAction":
        """IFUP,<iface> → /sbin/ifup <iface> → callback(exitCode)"""
        cls._dispatch("IFUP", iface, callback, timeout)
        return cls(iface)

    @classmethod
    def ifdown(cls, ifaces: "str | list[str]", callback, timeout: int = 15000) -> "ServiceAction":
        """IFDOWN,<iface[,iface…]> → /sbin/ifdown for each → callback(exitCode)"""
        data = ",".join(ifaces) if isinstance(ifaces, list) else ifaces
        cls._dispatch("IFDOWN", data, callback, timeout)
        return cls(data)

    @classmethod
    def wlanActivate(cls, iface: str, callback, timeout: int = 30000) -> "ServiceAction":
        """WLANUP,<iface> → wlanactivator start <iface> → callback(exitCode)"""
        cls._dispatch("WLANUP", iface, callback, timeout)
        return cls(iface)

    @classmethod
    def wlanDeactivate(cls, iface: str, callback, timeout: int = 15000) -> "ServiceAction":
        """WLANDOWN,<iface> → wlanactivator stop <iface> → callback(exitCode)"""
        cls._dispatch("WLANDOWN", iface, callback, timeout)
        return cls(iface)

    @classmethod
    def switchSoftcam(cls, camName: str, callback, timeout: int = 15000) -> "ServiceAction":
        """SWITCH_SOFTCAM,<camName> → callback(exitCode)"""
        cls._dispatch("SWITCH_SOFTCAM", camName, callback, timeout)
        return cls(camName)

    @classmethod
    def switchCardserver(cls, serverName: str, callback, timeout: int = 15000) -> "ServiceAction":
        """SWITCH_CARDSERVER,<serverName> → callback(exitCode)"""
        cls._dispatch("SWITCH_CARDSERVER", serverName, callback, timeout)
        return cls(serverName)

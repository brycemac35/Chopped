"""
upnp.py -- politely ask the router to open UDP 27015. Routers say no a lot.
miniupnpc is optional: if it's missing or the router ignores us, we just
tell the host to port-forward manually or play on LAN.
"""

import threading

from . import config as C


class UPnP:
    def __init__(self, port=C.DEFAULT_PORT):
        self.port = port
        self.status = "UPNP: ASKING YOUR ROUTER NICELY..."
        self.public_ip = None
        self.ok = False
        self.done = False
        self._u = None
        self._lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self._run, name="chopped-upnp", daemon=True)
        t.start()
        return self

    def _run(self):
        try:
            import miniupnpc
        except Exception:
            self.status = "UPNP UNAVAILABLE - FORWARD UDP %d OR PLAY ON LAN" % self.port
            self.done = True
            return
        try:
            u = miniupnpc.UPnP()
            u.discoverdelay = 1500     # ms. Long enough for sleepy routers, short enough to not notice.
            if u.discover() <= 0:
                raise RuntimeError("no devices")
            u.selectigd()
            try:
                self.public_ip = u.externalipaddress() or None
            except Exception:
                self.public_ip = None
            try:
                u.deleteportmapping(self.port, "UDP")   # clear a stale mapping from a crashed session
            except Exception:
                pass
            u.addportmapping(self.port, "UDP", u.lanaddr, self.port, "Chopped", "")
            with self._lock:
                self._u = u
                self.ok = True
            self.status = "UPNP OK: UDP %d FORWARDED" % self.port
        except Exception:
            self.status = "UPNP FAILED - FORWARD UDP %d OR PLAY ON LAN" % self.port
        self.done = True

    def close(self):
        with self._lock:
            if self.ok and self._u is not None:
                try:
                    self._u.deleteportmapping(self.port, "UDP")
                except Exception:
                    pass
                self.ok = False

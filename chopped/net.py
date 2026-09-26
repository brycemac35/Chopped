"""
net.py -- plain stdlib UDP. The host runs the Server (authoritative World at
60 Hz); everybody, including the host's own screen, is a Client that sends
button states and draws whatever the server says happened.

Why no networking library: zero dependencies means the Windows .exe packages
cleanly, and UDP + "resend the state, not the deltas" is honestly all a
four-player car-crime game needs.
"""

import math
import random
import socket
import sys
import threading
import time
from collections import deque

from . import config as C
from . import protocol as P
from . import savefile as SF
from .mapgen import CityMap
from .predict import Predictor
from .protocol import ME_FOOT, ME_DRIVER
from .sim import World, InputState, FOOT, DRIVER, T_INFO
from .protocol import PF_MOVING, PF_SPRINT, PF_EXHAUSTED


def _make_socket(bind_host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if sys.platform == "win32":
        # Windows reports "port unreachable" ICMP as ConnectionResetError on
        # the NEXT recvfrom -- one departed client would kill the server loop.
        try:
            s.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (AttributeError, OSError, ValueError):
            pass
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 18)
    except OSError:
        pass
    s.bind((bind_host, port))
    s.setblocking(False)
    return s


def _recv_all(sock, limit=256):
    """Drain the socket. Yields (data, addr). Swallows the assorted OSErrors
    UDP likes to throw for reasons that are never your fault."""
    out = []
    for _ in range(limit):
        try:
            data, addr = sock.recvfrom(2048)
        except (BlockingIOError, InterruptedError):
            break
        except ConnectionResetError:
            continue
        except OSError:
            break
        out.append((data, addr))
    return out


def _route_ip(probe):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((probe, 1))          # UDP "connect" sends nothing; it just picks a route
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def get_lan_ips():
    """Every IPv4 address a friend might reach us on, best guess first: the
    interface with the default route, then the rest (a Tailscale/ZeroTier/
    Radmin address shows up here too, which is exactly what you'd read out
    to a friend on one). Loopback and link-local junk is filtered out."""
    found = []
    for ip in [_route_ip("192.0.2.1"), _route_ip("10.255.255.255")]:
        if ip:
            found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if ip not in out and not ip.startswith(("127.", "169.254.", "0.")):
            out.append(ip)
    return out or ["127.0.0.1"]


def get_lan_ip():
    return get_lan_ips()[0]


def ms_now():
    return int(time.perf_counter() * 1000) & 0xFFFFFFFF


# ===========================================================================
class ClientConn:
    __slots__ = ("addr", "pid", "last_heard", "input_seq", "ack_event", "echo_ms", "local",
                 "snap_every", "nonce")

    def __init__(self, addr, pid, local, nonce):
        self.addr = addr
        self.pid = pid
        self.last_heard = time.perf_counter()
        self.input_seq = -1
        self.ack_event = 0
        self.echo_ms = 0
        self.local = local
        self.nonce = nonce
        self.snap_every = 1 if local else max(1, C.SIM_HZ // C.SNAPSHOT_HZ)


class Server:
    def __init__(self, port=C.DEFAULT_PORT, bind_host="0.0.0.0", map_seed=None, world=None, save_path=None):
        self.sock = _make_socket(bind_host, port)
        self.port = self.sock.getsockname()[1]
        self.world = world or World(map_seed)
        self.clients = {}           # addr -> ClientConn
        self.running = False
        self.thread = None
        self._next_tick = None
        self.dt = 1.0 / C.SIM_HZ
        self.bytes_sent = 0
        self.max_packet = 0
        self.log = []
        self._posted = deque()      # callables to run on the server thread (tests/admin)
        # (save files) --save FILE: load the crew's progress now (a no-op if there's
        # nothing to load yet), then write it back periodically and on a clean stop.
        self.save_path = save_path
        self._next_save = None
        if self.save_path:
            if SF.load_into(self.world, self.save_path):
                self.world.toast("WELCOME BACK. $%d IN THE TIN, DAY %d." % (self.world.cash, self.world.day),
                                 T_INFO)

    def post(self, fn):
        """Run fn(world) on the server thread before the next tick. The only
        thread-safe way to poke the world from outside."""
        self._posted.append(fn)

    # ---- lifecycle --------------------------------------------------------
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="chopped-server", daemon=True)
        self.thread.start()

    def _run(self):
        while self.running:
            wait = self.pump()
            if wait > 0:
                time.sleep(min(wait, 0.004))

    def stop(self):
        if self.thread and self.thread.is_alive():
            self.running = False
            self.thread.join(timeout=2.0)
        self.running = False
        if self.save_path:
            SF.save_to(self.world, self.save_path)      # the world's quiescent now the thread's joined
        for c in list(self.clients.values()):
            for _ in range(3):
                self._send(P.header(P.P_SHUTDOWN) + b"HOST CLOSED THE SHOP", c.addr)
        try:
            self.sock.close()
        except OSError:
            pass

    # ---- one iteration: receive, step as many fixed ticks as are due, send
    def pump(self):
        now = time.perf_counter()
        if self._next_tick is None:
            self._next_tick = now
            if self.save_path:
                self._next_save = now + C.AUTOSAVE_INTERVAL
        for data, addr in _recv_all(self.sock):
            self._handle(data, addr, now)
        while self._posted:
            self._posted.popleft()(self.world)
        steps = 0
        while now >= self._next_tick and steps < 8:
            self.world.step(self.dt)
            self._next_tick += self.dt
            steps += 1
            self._send_snapshots()
        if now - self._next_tick > 0.25:
            self._next_tick = now          # we fell way behind (debugger?); don't fast-forward forever
        self._timeouts(now)
        if self.save_path and now >= self._next_save:
            self._next_save = now + C.AUTOSAVE_INTERVAL
            SF.save_to(self.world, self.save_path)
        return self._next_tick - time.perf_counter()

    def _send(self, data, addr):
        try:
            self.sock.sendto(data, addr)
            self.bytes_sent += len(data)
        except OSError:
            pass

    def _handle(self, data, addr, now):
        h = P.parse_header(data)
        if h is None:
            return
        ver, ptype = h
        off = P.HDR.size
        if ptype == P.P_JOIN:
            if ver != C.VERSION:
                self._send(P.header(P.P_REJECT) + b"VERSION MISMATCH - UPDATE YOUR GAME", addr)
                return
            if len(data) < off + P.JOIN.size:
                return
            nonce, local = P.JOIN.unpack_from(data, off)
            name, _ = P._text(data, off + P.JOIN.size) if len(data) > off + P.JOIN.size else ("", 0)
            conn = self.clients.get(addr)
            if conn is None:
                if len(self.clients) >= C.MAX_PLAYERS:
                    self._send(P.header(P.P_REJECT) + b"SERVER FULL (4/4)", addr)
                    return
                p = self.world.add_player(name.strip() or None)
                if p is None:
                    self._send(P.header(P.P_REJECT) + b"SERVER FULL (4/4)", addr)
                    return
                conn = ClientConn(addr, p.id, bool(local), nonce)
                self.clients[addr] = conn
                self.log.append("join %s pid=%d %s" % (addr, p.id, p.name))
            conn.last_heard = now
            self._send(P.header(P.P_WELCOME) + P.WELCOME.pack(conn.pid, self.world.map_seed, nonce), addr)
            return
        conn = self.clients.get(addr)
        if conn is None:
            return
        conn.last_heard = now
        if ptype == P.P_INPUT and len(data) >= off + P.INPUT.size:
            (seq, cms, ack, buttons, use, drop, ex, yaw, fire, weapon,
             mseq, mop, marg, marg2) = P.INPUT.unpack_from(data, off)
            if seq <= conn.input_seq:
                return                     # stale/out-of-order: newer state already applied
            conn.input_seq = seq
            conn.echo_ms = cms
            conn.ack_event = max(conn.ack_event, ack)
            self.world.set_input(conn.pid, InputState(buttons, use, drop, ex, P.unang16(yaw), fire, weapon,
                                                      mseq, mop, marg, marg2))
        elif ptype == P.P_LEAVE:
            self._drop(conn, "left")

    def _drop(self, conn, why):
        self.clients.pop(conn.addr, None)
        self.world.remove_player(conn.pid)
        self.log.append("drop pid=%d (%s)" % (conn.pid, why))

    def _timeouts(self, now):
        for conn in list(self.clients.values()):
            if now - conn.last_heard > C.TIMEOUT_S:
                self._drop(conn, "timeout")

    def _send_snapshots(self):
        tick = self.world.tick
        for conn in list(self.clients.values()):
            if tick % conn.snap_every:
                continue
            pkt = P.encode_snapshot(self.world, conn.pid, conn.echo_ms, conn.ack_event, conn.input_seq)
            self.max_packet = max(self.max_packet, len(pkt))
            self._send(pkt, conn.addr)

    @property
    def player_count(self):
        return len(self.clients)


# ===========================================================================
def lerp_angle(a, b, t):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + d * t


class View:
    """What the renderer draws this frame: interpolated copies of snapshot
    entity rows (same field layout as protocol.decode_snapshot)."""
    __slots__ = ("snap", "cars", "players", "npcs", "pickups", "dollies", "traps", "me", "my_car")


class Client:
    def __init__(self, host, port=C.DEFAULT_PORT, name="PLAYER", local=False, fake_lag=0.0,
                 fake_jitter=0.0, predict=True):
        self.name = name
        self.local = local
        # --fake-lag: hold every packet this long in each direction, so you can
        # feel (and test) a 150 ms ping on one PC. Jitter keeps packet order.
        self.fake_lag = max(0.0, fake_lag)
        self.fake_jitter = max(0.0, fake_jitter)
        self._lag_out = deque()
        self._lag_in = deque()
        self._lag_rng = random.Random(1)
        self.state = "connecting"
        self.error = ""
        self.pid = None
        self.map = None
        self.map_seed = None
        self.nonce = random.randrange(1, 2 ** 31)
        self.sock = _make_socket("0.0.0.0", 0)
        try:
            ip = socket.gethostbyname(host)
        except OSError:
            self.state = "failed"
            self.error = "CAN'T RESOLVE %s" % host
            ip = "127.0.0.1"
        self.addr = (ip, port)
        self.started = time.perf_counter()
        self.last_join = -1.0
        self.last_rx = self.started
        self.last_input = -1.0
        self.input_seq = 0
        self.inp = InputState()
        self._decode_warned = False
        self.snaps = deque(maxlen=48)
        self.latest = None
        self.offsets = deque(maxlen=60)
        self.offset = None
        self.last_event = 0
        self.new_events = []
        self.ping_ms = 0
        self.delay = C.LOCAL_INTERP_DELAY if local else C.INTERP_DELAY
        self.input_period = 1.0 / C.INPUT_HZ
        self.predict = predict
        self.predictor = None
        self._last_view = None

    # ---- networking ---------------------------------------------------------
    def _send(self, data):
        if self.fake_lag or self.fake_jitter:
            self._lag_out.append((self._lag_release(self._lag_out), data))
            return
        self._send_now(data)

    def _send_now(self, data):
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass

    def _lag_release(self, queue):
        t = time.perf_counter() + self.fake_lag + self._lag_rng.uniform(0.0, self.fake_jitter)
        return max(t, queue[-1][0]) if queue else t

    def _receive(self, now):
        pkts = _recv_all(self.sock)
        if not (self.fake_lag or self.fake_jitter):
            return pkts
        for data, addr in pkts:
            self._lag_in.append((self._lag_release(self._lag_in), data, addr))
        while self._lag_out and self._lag_out[0][0] <= now:
            self._send_now(self._lag_out.popleft()[1])
        out = []
        while self._lag_in and self._lag_in[0][0] <= now:
            _, data, addr = self._lag_in.popleft()
            out.append((data, addr))
        return out

    def update(self, now=None):
        if now is None:
            now = time.perf_counter()
        if self.state in ("failed", "closed"):
            return
        for data, addr in self._receive(now):
            if addr != self.addr:
                continue
            h = P.parse_header(data)
            if h is None:
                continue
            ver, ptype = h
            off = P.HDR.size
            self.last_rx = now
            if ptype == P.P_WELCOME and len(data) >= off + P.WELCOME.size:
                pid, seed, nonce = P.WELCOME.unpack_from(data, off)
                if nonce != self.nonce or self.pid is not None:
                    continue
                self.pid = pid
                self.map_seed = seed
                self.map = CityMap(seed)
                self.state = "connected"
                if self.predict:
                    self.predictor = Predictor(self.map)
            elif ptype == P.P_SNAPSHOT and self.pid is not None:
                try:
                    snap = P.decode_snapshot(data[off:])
                except Exception:
                    if not self._decode_warned:  # say so once (it lands in --log): a real bug looks like this
                        self._decode_warned = True
                        import traceback
                        traceback.print_exc()
                    continue                     # mangled packet; UDP gonna UDP
                self._on_snapshot(snap, now)
            elif ptype == P.P_REJECT:
                self.state = "failed"
                self.error = data[off:].decode("ascii", "replace")
                return
            elif ptype == P.P_SHUTDOWN:
                self.state = "closed"
                self.error = data[off:].decode("ascii", "replace") or "HOST CLOSED THE SHOP"
                return
        if self.state == "connecting":
            if now - self.last_join > 0.5:
                self.last_join = now
                self._send(P.header(P.P_JOIN) + P.JOIN.pack(self.nonce, 1 if self.local else 0) +
                           P.encode_text(self.name, 12))
            if now - self.started > C.TIMEOUT_S:
                self.state = "failed"
                self.error = "NO ANSWER FROM %s:%d" % self.addr
            return
        if now - self.last_rx > C.TIMEOUT_S:
            self.state = "closed"
            self.error = "CONNECTION LOST (NO DATA FOR 10 S)"
            return
        # One input per sim tick, on a fixed 60 Hz clock, and the predictor
        # steps exactly one tick per input -- the same deal the server gets.
        if self.last_input < 0:
            self.last_input = now
        due = 0
        while now - self.last_input >= self.input_period and due < 8:
            self.last_input += self.input_period
            due += 1
            self.input_seq += 1
            i = self.inp
            y16 = P.ang16(i.yaw)
            self._send(P.header(P.P_INPUT) + P.INPUT.pack(
                self.input_seq, ms_now(), self.last_event, i.buttons & 0xFFFF,
                i.use_count & 0xFF, i.drop_count & 0xFF, i.exit_count & 0xFF, y16,
                i.fire_count & 0xFF, i.weapon & 0xFF, i.menu_seq & 0xFF, i.menu_op & 0xFF, i.menu_arg & 0xFF,
                i.menu_arg2 & 0xFF))
            if self.predictor is not None:
                # predict with the yaw exactly as the server will decode it
                self.predictor.push_input(self.input_seq, i.buttons & 0xFFFF, P.unang16(y16))
        if now - self.last_input > 0.25:
            self.last_input = now      # window was dragged / laptop napped: don't machine-gun inputs

    def _on_snapshot(self, snap, now):
        if self.latest is not None and snap.tick <= self.latest.tick:
            return                               # out of order; ignore
        snap.arrival = now
        self.snaps.append(snap)
        self.latest = snap
        # clock sync: the smallest (arrival - server_time) over the last few
        # seconds is our best estimate of "zero-jitter" latency + clock offset
        self.offsets.append(now - snap.time)
        self.offset = min(self.offsets)
        if snap.echo_ms:
            self.ping_ms = (ms_now() - snap.echo_ms) & 0xFFFFFFFF
            if self.ping_ms > 60000:
                self.ping_ms = 0
        if self.predictor is not None:
            self.predictor.reconcile(snap)
        for seq, kind, payload in snap.events:
            if seq > self.last_event:
                self.new_events.append((kind, payload))
        if snap.events:
            self.last_event = max(self.last_event, max(e[0] for e in snap.events))

    def pop_events(self):
        ev, self.new_events = self.new_events, []
        return ev

    def leave(self):
        for _ in range(3):
            self._send_now(P.header(P.P_LEAVE))
        try:
            self.sock.close()
        except OSError:
            pass
        self.state = "closed"

    # ---- interpolation --------------------------------------------------------
    def view(self, now=None):
        if self.latest is None:
            return None
        if now is None:
            now = time.perf_counter()
        server_now = now - self.offset
        rt = server_now - self.delay
        snaps = self.snaps
        s0 = s1 = None
        for i in range(len(snaps) - 1, -1, -1):
            if snaps[i].time <= rt:
                s0 = snaps[i]
                s1 = snaps[i + 1] if i + 1 < len(snaps) else None
                break
        if s0 is None:
            s0, s1 = snaps[0], None
        v = View()
        latest = self.latest
        v.snap = latest
        if s1 is None:
            ext = max(0.0, min(rt - s0.time, 0.2))
            t = 0.0
        else:
            ext = 0.0
            t = (rt - s0.time) / max(1e-6, s1.time - s0.time)
        # everything that exists in the latest snapshot gets drawn; positions
        # come from the bracketing pair when available
        v.cars = self._blend(latest.cars, s0.cars, s1.cars if s1 else None, t, ext, 7, 8, 11, 9, 10)
        v.players = self._blend(latest.players, s0.players, s1.players if s1 else None, t, ext, 4, 5, 8, 6, 7)
        v.npcs = self._blend(latest.npcs, s0.npcs, s1.npcs if s1 else None, t, 0.0, 3, 4, 5, None, None)
        v.pickups = self._blend(latest.pickups, s0.pickups, s1.pickups if s1 else None, t, 0.0, 2, 3, None, None, None)
        v.dollies = self._blend(latest.dollies, s0.dollies, s1.dollies if s1 else None, t, 0.0, 1, 2, 3, None, None)
        v.traps = latest.traps
        v.me = v.players.get(self.pid)
        v.my_car = None
        if v.me is not None and v.me[12]:
            v.my_car = v.cars.get(v.me[12])
        pr = self.predictor
        if pr is not None:
            if self._last_view is not None:
                pr.advance(max(0.0, min(0.1, now - self._last_view)))
            self._last_view = now
        if pr is not None and v.me is not None and self._apply_prediction(v, pr):
            self._carry_dolly(v)
            return v
        # no prediction for this state (tumbling, cuffed, riding shotgun):
        # pull our own avatar/car forward to the freshest data instead
        if not self.local and v.me is not None:
            lat_ext = max(0.0, min(server_now - latest.time, 0.15))
            me_l = latest.players.get(self.pid)
            if me_l is not None:
                row = list(me_l)
                row[4] += row[6] * lat_ext
                row[5] += row[7] * lat_ext
                v.players[self.pid] = v.me = row
            if v.my_car is not None and v.my_car[0] in latest.cars:
                row = list(latest.cars[v.my_car[0]])
                row[7] += row[9] * lat_ext
                row[8] += row[10] * lat_ext
                v.cars[row[0]] = v.my_car = row
        self._carry_dolly(v)
        return v

    def _carry_dolly(self, v):
        """The dolly you're pushing sticks to your (predicted) hands, not to
        where the server thought you were 100 ms ago."""
        me = v.me
        for eid, row in v.dollies.items():
            if row[5] == self.pid and me is not None:
                row = list(row)
                row[1] = me[4] + math.cos(me[8]) * C.DOLLY_OFFSET
                row[2] = me[5] + math.sin(me[8]) * C.DOLLY_OFFSET
                row[3] = me[8]
                v.dollies[eid] = row

    def _apply_prediction(self, v, pr):
        """Swap our own car/avatar in the view for the predicted one."""
        me = v.me
        pose = pr.render_pose()
        if pose is None:
            return False
        x, y, ang = pose
        if pr.mode == ME_DRIVER and me[2] == DRIVER and me[12] == pr.car_id and v.my_car is not None:
            car = pr.car
            row = list(v.my_car)
            row[7], row[8], row[9], row[10], row[11] = x, y, car.vx, car.vy, ang
            v.cars[row[0]] = v.my_car = row
            me = list(me)
            me[4], me[5] = x, y
            v.players[self.pid] = v.me = me
            return True
        if pr.mode == ME_FOOT and me[2] == FOOT:
            b = pr.body
            me = list(me)
            me[4], me[5], me[6], me[7], me[8] = x, y, b.vx, b.vy, ang
            me[3] = (me[3] & ~(PF_MOVING | PF_SPRINT | PF_EXHAUSTED)) | (PF_MOVING if b.moving else 0) | \
                (PF_SPRINT if b.sprinting else 0) | (PF_EXHAUSTED if b.exhausted else 0)
            me[11] = b.stamina
            if len(me) > 15:
                me[15] = b.z                 # your own jump, predicted: no 100 ms hop delay
            v.players[self.pid] = v.me = me
            return True
        return False

    @staticmethod
    def _blend(latest, a, b, t, ext, ix, iy, ia, ivx, ivy):
        out = {}
        for eid, row in latest.items():
            ra = a.get(eid)
            rb = b.get(eid) if b is not None else None
            if ra is None:
                out[eid] = row
                continue
            r = list(rb if rb is not None else ra)
            if rb is not None:
                r[ix] = ra[ix] + (rb[ix] - ra[ix]) * t
                r[iy] = ra[iy] + (rb[iy] - ra[iy]) * t
                if ia is not None:
                    r[ia] = lerp_angle(ra[ia], rb[ia], t)
            elif ext and ivx is not None:
                r[ix] += r[ivx] * ext
                r[iy] += r[ivy] * ext
            # non-positional fields (parts, state, hands...) always from latest
            for k in range(len(row)):
                if k not in (ix, iy, ia):
                    r[k] = row[k]
            out[eid] = r
        return out

"""
protocol.py -- how the world gets squeezed into UDP packets.

Every packet starts with b"CH", a protocol version and a type byte. Snapshots
are struct-packed and zlib'd; positions are 1/16 m fixed point (u16 covers
4 km, our city is 444 m), velocities 1/64 m/s, angles 1/65536 of a turn.
Target: comfortably under ~1150 bytes so nobody's router has to fragment.
"""

import math
import struct
import zlib

from . import config as C
from .parts import SLOTS, PART_INDEX, NO_PART, part_tuned
from .sim import COP, TUMBLE, CUFFED

MAGIC = b"CH"
P_JOIN, P_WELCOME, P_REJECT, P_INPUT, P_SNAPSHOT, P_LEAVE, P_SHUTDOWN = range(1, 8)

HDR = struct.Struct("<2sBB")
JOIN = struct.Struct("<IB")               # nonce, is_local
WELCOME = struct.Struct("<BII")           # pid, map_seed, nonce
INPUT = struct.Struct("<IIIBBBB")         # seq, client_ms, ack_event, buttons, use, drop, exit

SNAP_HDR = struct.Struct("<IIBiHHBBBBHBB")
# tick, echo_ms, your_pid, cash, rent_ds, debt_ds, heat, witness(|128 cooling),
# cops, gameover_ds, run, hold_byte, nplayers_total
COUNTS = struct.Struct("<BBBBB")
CAR = struct.Struct("<HBBBBHHHHhhHBBB")
PLAYER = struct.Struct("<BBBBHHhhHBBBH")
NPC = struct.Struct("<HBBHHB")
PICKUP = struct.Struct("<HBHHB")
EV = struct.Struct("<IB")
EV_SFX = struct.Struct("<BHH")

CF_ALARM, CF_FIRE, CF_HORN, CF_HANDBRAKE, CF_CONFUSED, CF_WANTED = 1, 2, 4, 8, 16, 32
PF_SPRINT, PF_EXHAUSTED, PF_MOVING = 1, 2, 4

SLOT_BITS = {s: 1 << i for i, s in enumerate(SLOTS)}


def header(ptype):
    return HDR.pack(MAGIC, C.VERSION, ptype)


def parse_header(data):
    if len(data) < HDR.size:
        return None
    magic, ver, ptype = HDR.unpack_from(data)
    if magic != MAGIC:
        return None
    return ver, ptype


def _pos(v):
    v = int(v * 16)
    return 0 if v < 0 else 65535 if v > 65535 else v


def _vel(v):
    v = int(v * 64)
    return -32767 if v < -32767 else 32767 if v > 32767 else v


def _ang(a):
    return int((a % (2 * math.pi)) / (2 * math.pi) * 65536) & 0xFFFF


def _ang8(a):
    return int((a % (2 * math.pi)) / (2 * math.pi) * 256) & 0xFF


def encode_text(s, maxlen=80):
    b = s.encode("ascii", "replace")[:maxlen]
    return bytes((len(b),)) + b


# ---------------------------------------------------------------------------
def encode_snapshot(world, pid, echo_ms, ack_event):
    """Build one client's snapshot. Per-client so we can cull by distance and
    tuck in their private prompt text."""
    me = world.players.get(pid)
    px, py = (me.x, me.y) if me else world.map.garage_center
    cops = sum(1 for c in world.cars.values() if c.kind == COP)
    wit = world.witness | (128 if world.witness_rate <= 0 and world.heat > 0 and
                           world.unseen_t >= C.HEAT_COOL_DELAY else 0)
    head = SNAP_HDR.pack(
        world.tick & 0xFFFFFFFF, echo_ms & 0xFFFFFFFF, pid, int(world.cash),
        min(65535, max(0, int(world.rent_t * 10))), min(65535, max(0, int(world.debt_t * 10))),
        int(round(world.heat)), wit, cops, min(255, max(0, int(world.gameover_t * 10))),
        world.run & 0xFFFF, int((me.hold_frac if me else 0) * 255), len(world.players))
    prompt = encode_text(me.prompt if me else "")

    cars = []
    for car in world.cars.values():
        mask = tuned = 0
        for s, part in car.parts.items():
            if part is not None:
                mask |= SLOT_BITS[s]
                if part_tuned(part.type_id):
                    tuned |= SLOT_BITS[s]
        flags = ((CF_ALARM if car.alarm else 0) | (CF_FIRE if car.fire_t > 0 else 0) |
                 (CF_HORN if car.horn else 0) | (CF_HANDBRAKE if car.handbrake and car.driver is not None else 0) |
                 (CF_CONFUSED if car.confused_t > 0 else 0) | (CF_WANTED if car.wanted() else 0))
        cars.append(CAR.pack(car.id, car.kind, car.color, car.state, flags, mask, tuned,
                             _pos(car.x), _pos(car.y), _vel(car.vx), _vel(car.vy), _ang(car.ang),
                             car.driver or 0, car.passenger or 0, car.damage))
    players = []
    for p in world.players.values():
        h0 = PART_INDEX[p.hands[0].type_id] if len(p.hands) > 0 else NO_PART
        h1 = PART_INDEX[p.hands[1].type_id] if len(p.hands) > 1 else NO_PART
        flags = (PF_SPRINT if p.sprinting else 0) | (PF_EXHAUSTED if p.exhausted else 0) | \
                (PF_MOVING if p.moving else 0)
        ang = p.spin if p.state == TUMBLE else p.ang
        players.append(PLAYER.pack(p.id, p.color, p.state, flags, _pos(p.x), _pos(p.y),
                                   _vel(p.vx), _vel(p.vy), _ang(ang), h0, h1,
                                   int(p.stamina * 2.55), p.car_id or 0) + encode_text(p.name, 12))
    r2 = C.NET_CULL_RADIUS ** 2
    npcs = []
    for n in world.npcs.values():
        d2 = (n.x - px) ** 2 + (n.y - py) ** 2
        if d2 < r2:
            state = 1 if n.tumble_t > 0 else 0
            npcs.append((d2, NPC.pack(n.id, n.kind, state, _pos(n.x), _pos(n.y),
                                      _ang8(n.spin if state else n.ang))))
    picks = []
    for pk in world.pickups.values():
        d2 = (pk.x - px) ** 2 + (pk.y - py) ** 2
        if d2 < r2:
            picks.append((d2, PICKUP.pack(pk.id, PART_INDEX[pk.part.type_id], _pos(pk.x), _pos(pk.y),
                                          int(pk.scale() * 255))))
    npcs.sort(key=lambda t: t[0])
    picks.sort(key=lambda t: t[0])
    evs = []
    for (seq, _t, kind, payload) in world.events:
        if seq <= ack_event:
            continue
        if kind == 0:
            evs.append(EV.pack(seq, 0) + bytes((payload[0],)) + encode_text(payload[1], 60))
        else:
            evs.append(EV.pack(seq, 1) + EV_SFX.pack(payload[0], _pos(payload[1]), _pos(payload[2])))
        if len(evs) >= 10:
            break

    n_np, n_pk = min(len(npcs), 60), min(len(picks), 120)
    while True:
        body = b"".join((head, prompt,
                         COUNTS.pack(len(cars), len(players), n_np, n_pk, len(evs)),
                         b"".join(cars), b"".join(players),
                         b"".join(t[1] for t in npcs[:n_np]),
                         b"".join(t[1] for t in picks[:n_pk]),
                         b"".join(evs)))
        packed = header(P_SNAPSHOT) + zlib.compress(body, 6)
        if len(packed) <= C.MAX_PACKET or (n_np == 0 and n_pk == 0):
            return packed
        # too fat: shed the farthest loose parts/peds first; nobody misses them
        n_pk = n_pk * 2 // 3
        n_np = n_np * 2 // 3


class Snapshot:
    __slots__ = ("tick", "time", "echo_ms", "pid", "cash", "rent", "debt", "heat", "witness",
                 "cooling", "cops", "gameover", "run", "hold", "nplayers", "prompt",
                 "cars", "players", "npcs", "pickups", "events", "arrival")


def _text(data, off):
    n = data[off]
    return data[off + 1:off + 1 + n].decode("ascii", "replace"), off + 1 + n


def decode_snapshot(payload):
    data = zlib.decompress(payload)
    s = Snapshot()
    (s.tick, s.echo_ms, s.pid, s.cash, rent, debt, s.heat, wit, s.cops, go, s.run, hold,
     s.nplayers) = SNAP_HDR.unpack_from(data, 0)
    s.time = s.tick / C.SIM_HZ
    s.rent, s.debt, s.gameover = rent / 10.0, debt / 10.0, go / 10.0
    s.witness, s.cooling = wit & 127, bool(wit & 128)
    s.hold = hold / 255.0
    off = SNAP_HDR.size
    s.prompt, off = _text(data, off)
    nc, npl, nn, npk, nev = COUNTS.unpack_from(data, off)
    off += COUNTS.size
    s.cars = {}
    for _ in range(nc):
        f = CAR.unpack_from(data, off)
        off += CAR.size
        # (id, kind, color, state, flags, mask, tuned, x, y, vx, vy, ang, driver, passenger, damage)
        s.cars[f[0]] = [f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7] / 16.0, f[8] / 16.0,
                        f[9] / 64.0, f[10] / 64.0, f[11] / 65536.0 * 2 * math.pi, f[12], f[13], f[14]]
    s.players = {}
    for _ in range(npl):
        f = PLAYER.unpack_from(data, off)
        off += PLAYER.size
        name, off = _text(data, off)
        # (id, color, state, flags, x, y, vx, vy, ang, h0, h1, stamina, car_id, name)
        s.players[f[0]] = [f[0], f[1], f[2], f[3], f[4] / 16.0, f[5] / 16.0, f[6] / 64.0, f[7] / 64.0,
                           f[8] / 65536.0 * 2 * math.pi, f[9], f[10], f[11] / 2.55, f[12], name]
    s.npcs = {}
    for _ in range(nn):
        f = NPC.unpack_from(data, off)
        off += NPC.size
        # (id, kind, state, x, y, ang)
        s.npcs[f[0]] = [f[0], f[1], f[2], f[3] / 16.0, f[4] / 16.0, f[5] / 256.0 * 2 * math.pi]
    s.pickups = {}
    for _ in range(npk):
        f = PICKUP.unpack_from(data, off)
        off += PICKUP.size
        # (id, part_idx, x, y, scale)
        s.pickups[f[0]] = [f[0], f[1], f[2] / 16.0, f[3] / 16.0, f[4] / 255.0]
    s.events = []
    for _ in range(nev):
        seq, kind = EV.unpack_from(data, off)
        off += EV.size
        if kind == 0:
            color = data[off]
            text, off = _text(data, off + 1)
            s.events.append((seq, 0, (color, text)))
        else:
            sid, x, y = EV_SFX.unpack_from(data, off)
            off += EV_SFX.size
            s.events.append((seq, 1, (sid, x / 16.0, y / 16.0)))
    return s

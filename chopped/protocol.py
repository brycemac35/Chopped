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
from .parts import SLOTS, PART_INDEX, PART_IDS, NO_PART
from .garage import encode_menu, decode_menu
from .sim import COP, TRAFFIC, TUMBLE, FOOT, DRIVER, PASSENGER
from . import vehicles as V

MAGIC = b"CH"
P_JOIN, P_WELCOME, P_REJECT, P_INPUT, P_SNAPSHOT, P_LEAVE, P_SHUTDOWN = range(1, 8)

HDR = struct.Struct("<2sBB")
JOIN = struct.Struct("<IB")               # nonce, is_local
WELCOME = struct.Struct("<BII")           # pid, map_seed, nonce
INPUT = struct.Struct("<IIIHBBBHBBBBBB")  # seq, client_ms, ack_event, buttons (16 bits), use, drop, exit,
                                          # yaw16, fire (click counter), weapon slot,
                                          # mod-shop command: counter, op, arg, arg2

SNAP_HDR = struct.Struct("<IIBiHHBBBBHBBIHI")
# tick, echo_ms, your_pid, cash, day_left_ds, debt_ds, heat, witness(|128 cooling),
# cops, gameover_ds, run, hold_byte, nplayers_total, ack_input (last input seq applied for you),
# day, rent_due

# Your own physics state at full precision, for client-side prediction. The
# regular entity rows are 1/16 m fixed point; rewinding to a rounded position
# and replaying 10 inputs on top of it would make your own car shimmer.
SELF_MOTION = struct.Struct("<BBHfffffffffHbB")
# mode (0 none / 1 on foot / 2 driving), walk_load, car_id, x, y, vx, vy, ang, w,
# stamina, regen_delay, speed_mult, power, pull, flags
# ...followed by 6 bytes of arsenal: weapon, arms bitmask, pistol ammo, shotgun ammo, spikes, roadblocks
# ...then (v0.7) the rest of what the tyre model and the jump need:
SELF_EXTRA = struct.Struct("<fffffffB")
# driving: steer angle, grip, mass, top-speed multiplier, NOS fuel, banana spin left, inertia, flags (1 = NOS fitted)
# on foot: height, vertical speed, 0, 0, 0, 0, 0, flags
ME_NONE, ME_FOOT, ME_DRIVER = 0, 1, 2
# ...then 8 bytes of arsenal, then a byte saying which optional blocks follow:
SB_TRUNK, SB_MENU = 1, 2
TRUNK_HDR = struct.Struct("<HBBB")      # car id, capacity, used, item count; then (part, style) per item
SF_EXHAUSTED = 1
SX_NOS = 1
COUNTS = struct.Struct("<BBBBBBB")
CAR = struct.Struct("<HBBBBHIHHhhHBBBBBBB")
# id, kind, colour, state, flags, part mask, style word, x, y, vx, vy, ang, driver, passenger, damage,
# model, livery, extras (horn 0-2, NOS flame 3, glow 4-7), extras2 (see CX_*)
PLAYER = struct.Struct("<BBBBHHhhHBBBHBBB")    # ... + weapon, z (0.1 m), banner
NPC = struct.Struct("<HBBHHBB")           # id, kind, state, x, y, ang8, z (0.1 m)
PICKUP = struct.Struct("<HBHHBBB")        # id, part, x, y, scale, z (0.1 m), style
DOLLY = struct.Struct("<HHHBBB")        # id, x, y, ang8, part_idx (255 empty), holder pid (0 none)
TRAP = struct.Struct("<HBHHBB")         # id, kind, x, y, ang8, life left (255 = fresh)
EV_SHOT = struct.Struct("<BHHHH")       # weapon, from x, y, to x, y
EV = struct.Struct("<IB")
EV_SFX = struct.Struct("<BHH")

CF_ALARM, CF_FIRE, CF_HORN, CF_HANDBRAKE, CF_CONFUSED, CF_WANTED = 1, 2, 4, 8, 16, 32
CF_TRUNK = 64                   # something in the trunk (you only find out what by looking)
CX_GNOME, CX_NOS, CX_EJECTOR, CX_SPIN, CX_DONUT, CX_PATROL = 1, 2, 4, 8, 16, 32
PF_SPRINT, PF_EXHAUSTED, PF_MOVING, PF_DOLLY = 1, 2, 4, 8
PF_CARRY, PF_DANCE, PF_CHARGE, PF_CHUTE = 16, 32, 64, 128
# NPC row states
NS_WALK, NS_DOWN, NS_FLEE, NS_HANDSUP, NS_BRAWL, NS_ARMED, NS_CARRIED, NS_LAUGH = range(8)

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


def ang16(a):
    return int((a % (2 * math.pi)) / (2 * math.pi) * 65536) & 0xFFFF


def unang16(v):
    a = v / 65536.0 * 2 * math.pi
    return a - 2 * math.pi if a > math.pi else a


def _z(v):
    v = int(v * 10)
    return 0 if v < 0 else 255 if v > 255 else v


def _ang8(a):
    return int((a % (2 * math.pi)) / (2 * math.pi) * 256) & 0xFF


def encode_text(s, maxlen=80):
    b = s.encode("ascii", "replace")[:maxlen]
    return bytes((len(b),)) + b


# ---------------------------------------------------------------------------
def encode_self(world, me):
    """The SELF block: exactly what the client's Predictor needs to rewind to,
    plus your arsenal (only you need to know how many bullets you've got), plus
    (v0.7) the trunk you're looking into and, in the mod shop, the menu."""
    arsenal = (me.weapon, me.arms, min(255, me.ammo[1]), min(255, me.ammo[2])) + \
        tuple(min(255, g) for g in (list(me.gear) + [0, 0, 0, 0])[:4]) if me is not None else (0, 1, 0, 0, 0, 0, 0, 0)
    out = [_encode_motion(world, me), _encode_extra(world, me), bytes(arsenal)]
    blocks = 0
    tail = []
    if me is not None:
        tcar = world.cars.get(me.car_id) if me.state in (DRIVER, PASSENGER) else world.cars.get(me.trunk_view)
        if tcar is not None:
            blocks |= SB_TRUNK
            items = tcar.trunk[:12]
            tail.append(TRUNK_HDR.pack(tcar.id, V.model(tcar.model).trunk, tcar.trunk_used(), len(items)) +
                        b"".join(bytes((PART_INDEX[q.type_id], q.style & 255)) for q in items))
        if me.menu:
            blocks |= SB_MENU
            tail.append(encode_menu(world, me))
    out.append(bytes((blocks,)))
    out.extend(tail)
    return b"".join(out)


def _encode_extra(world, me):
    if me is not None and world.gameover_t <= 0:
        if me.state == DRIVER:
            car = world.cars.get(me.car_id)
            if car is not None:
                return SELF_EXTRA.pack(car.delta, car.grip, car.mass, car.top_mult, car.nos_fuel, car.spin_t,
                                       car.inertia, SX_NOS if car.nos else 0)
        if me.state == FOOT:
            return SELF_EXTRA.pack(me.z, me.vz, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    return SELF_EXTRA.pack(0.0, 1.0, 1000.0, 1.0, 0.0, 0.0, 1000.0, 0)


def _encode_motion(world, me):
    if world.gameover_t > 0:
        me = None             # the world is frozen for the SHOP SEIZED banner: nothing to predict
    if me is not None and me.state == DRIVER:
        car = world.cars.get(me.car_id)
        if car is not None:
            return SELF_MOTION.pack(ME_DRIVER, 0, car.id, car.x, car.y, car.vx, car.vy, car.ang, car.w,
                                    0.0, 0.0, 1.0, min(65535, car.power()), -1 if car.pull < 0 else 1, 0)
    if me is not None and me.state == FOOT:
        return SELF_MOTION.pack(ME_FOOT, me.walk_load(), 0, me.x, me.y, me.vx, me.vy, me.ang, 0.0,
                                me.stamina, me.regen_delay, me.speed_mult(), 0, 0,
                                SF_EXHAUSTED if me.exhausted else 0)
    return SELF_MOTION.pack(ME_NONE, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, 0, 0)


def encode_snapshot(world, pid, echo_ms, ack_event, ack_input=0):
    """Build one client's snapshot. Per-client so we can cull by distance and
    tuck in their private prompt text and prediction state."""
    me = world.players.get(pid)
    px, py = (me.x, me.y) if me else world.map.garage_center
    cops = sum(1 for c in world.cars.values() if c.kind == COP and not c.patrol)   # (chasing, not cruising)
    wit = world.witness | (128 if world.witness_rate <= 0 and world.heat > 0 and
                           world.unseen_t >= C.HEAT_COOL_DELAY else 0)
    head = SNAP_HDR.pack(
        world.tick & 0xFFFFFFFF, echo_ms & 0xFFFFFFFF, pid, int(world.cash),
        min(65535, max(0, int(world.day_t * 10))), min(65535, max(0, int(world.debt_t * 10))),
        int(round(world.heat)), wit, cops, min(255, max(0, int(world.gameover_t * 10))),
        world.run & 0xFFFF, int((me.hold_frac if me else 0) * 255), len(world.players),
        max(0, ack_input) & 0xFFFFFFFF, min(65535, world.day), min(0xFFFFFFFF, world.rent_due()))
    prompt = encode_text(me.prompt if me else "") + encode_self(world, me)

    r2 = C.NET_CULL_RADIUS ** 2
    cars = []
    for car in world.cars.values():
        if car.kind == TRAFFIC and (car.x - px) ** 2 + (car.y - py) ** 2 > r2:
            continue          # far-off traffic is scenery; everything stealable is always sent
        mask = 0
        for s, part in car.parts.items():
            if part is not None:
                mask |= SLOT_BITS[s]
        flags = ((CF_ALARM if car.alarm else 0) | (CF_FIRE if car.fire_t > 0 else 0) |
                 (CF_HORN if car.horn else 0) | (CF_HANDBRAKE if car.handbrake and car.driver is not None else 0) |
                 (CF_CONFUSED if car.confused_t > 0 else 0) | (CF_WANTED if car.wanted() else 0) |
                 (CF_TRUNK if car.trunk else 0))
        extras = (car.horn_type & 7) | (8 if car.boosting else 0) | ((car.glow & 15) << 4)
        extras2 = ((CX_GNOME if car.gnome else 0) | (CX_NOS if car.nos else 0) |
                   (CX_EJECTOR if car.ejector else 0) | (CX_SPIN if car.spin_t > 0 else 0) |
                   (CX_DONUT if car.donut_t > 0 else 0) | (CX_PATROL if car.patrol else 0))
        cars.append(CAR.pack(car.id, car.kind, car.color, car.state, flags, mask, V.pack_styles(car.parts),
                             _pos(car.x), _pos(car.y), _vel(car.vx), _vel(car.vy), _ang(car.ang),
                             car.driver or 0, car.passenger or 0, car.damage, car.model, car.livery,
                             extras, extras2))
    players = []
    for p in world.players.values():
        h0 = PART_INDEX[p.hands[0].type_id] if len(p.hands) > 0 else NO_PART
        h1 = PART_INDEX[p.hands[1].type_id] if len(p.hands) > 1 else NO_PART
        flags = (PF_SPRINT if p.sprinting else 0) | (PF_EXHAUSTED if p.exhausted else 0) | \
                (PF_MOVING if p.moving else 0) | (PF_DOLLY if p.dolly is not None else 0) | \
                (PF_CARRY if p.carrying is not None else 0) | (PF_DANCE if p.dancing else 0) | \
                (PF_CHARGE if p.charge_t > 0.15 else 0) | (PF_CHUTE if p.chute else 0)
        ang = p.spin if p.state == TUMBLE else p.ang
        players.append(PLAYER.pack(p.id, p.color, p.state, flags, _pos(p.x), _pos(p.y),
                                   _vel(p.vx), _vel(p.vy), _ang(ang), h0, h1,
                                   int(p.stamina * 2.55), p.car_id or 0, p.weapon, _z(p.z), p.banner)
                       + encode_text(p.name, 12))
    npcs = []
    for n in world.npcs.values():
        d2 = (n.x - px) ** 2 + (n.y - py) ** 2
        if d2 < r2:
            if n.carried_by is not None:
                state = NS_CARRIED
            elif n.tumble_t > 0:
                state = NS_DOWN
            elif n.surrender_t > 0:
                state = NS_HANDSUP
            elif n.hostile_t > 0:
                state = NS_ARMED if n.armed else NS_BRAWL
            elif n.laugh_t > 0:
                state = NS_LAUGH
            elif n.flee_t > 0:
                state = NS_FLEE
            else:
                state = NS_WALK
            npcs.append((d2, NPC.pack(n.id, n.kind, state, _pos(n.x), _pos(n.y),
                                      _ang8(n.spin if state in (NS_DOWN, NS_CARRIED) else n.ang), _z(n.z))))
    picks = []
    for pk in world.pickups.values():
        d2 = (pk.x - px) ** 2 + (pk.y - py) ** 2
        if d2 < r2:
            picks.append((d2, PICKUP.pack(pk.id, PART_INDEX[pk.part.type_id], _pos(pk.x), _pos(pk.y),
                                          int(pk.scale() * 255), _z(pk.z), pk.part.style & 255)))
    npcs.sort(key=lambda t: t[0])
    picks.sort(key=lambda t: t[0])
    dollies = [DOLLY.pack(d.id, _pos(d.x), _pos(d.y), _ang8(d.ang),
                          PART_INDEX[d.part.type_id] if d.part is not None else NO_PART, d.holder or 0)
               for d in world.dollies.values()]
    traps = [TRAP.pack(t.id, t.kind, _pos(t.x), _pos(t.y), _ang8(t.ang),
                       max(0, min(255, int(255 * (1 - t.age / C.TRAP_LIFETIME)))))
             for t in world.traps.values()]
    evs = []
    for (seq, _t, kind, payload) in world.events:
        if seq <= ack_event:
            continue
        if kind == 0:
            evs.append(EV.pack(seq, 0) + bytes((payload[0],)) + encode_text(payload[1], 60))
        elif kind == 1:
            evs.append(EV.pack(seq, 1) + EV_SFX.pack(payload[0], _pos(payload[1]), _pos(payload[2])))
        else:
            w, x0, y0, x1, y1 = payload
            evs.append(EV.pack(seq, 2) + EV_SHOT.pack(w, _pos(x0), _pos(y0), _pos(x1), _pos(y1)))
        if len(evs) >= C.EVENTS_PER_SNAPSHOT:
            break

    n_np, n_pk = min(len(npcs), 60), min(len(picks), 120)
    while True:
        body = b"".join((head, prompt,
                         COUNTS.pack(len(cars), len(players), n_np, n_pk, len(evs), len(dollies), len(traps)),
                         b"".join(cars), b"".join(players), b"".join(dollies), b"".join(traps),
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
                 "cooling", "cops", "gameover", "run", "hold", "nplayers", "prompt", "ack_input", "day",
                 "rent_due",
                 "me", "me2", "arsenal", "trunk", "menu", "cars", "players", "npcs", "pickups", "dollies", "traps", "events", "arrival")


def _text(data, off):
    n = data[off]
    return data[off + 1:off + 1 + n].decode("ascii", "replace"), off + 1 + n


def decode_snapshot(payload):
    data = zlib.decompress(payload)
    s = Snapshot()
    (s.tick, s.echo_ms, s.pid, s.cash, rent, debt, s.heat, wit, s.cops, go, s.run, hold,
     s.nplayers, s.ack_input, s.day, s.rent_due) = SNAP_HDR.unpack_from(data, 0)
    s.time = s.tick / C.SIM_HZ
    s.rent, s.debt, s.gameover = rent / 10.0, debt / 10.0, go / 10.0
    s.witness, s.cooling = wit & 127, bool(wit & 128)
    s.hold = hold / 255.0
    off = SNAP_HDR.size
    s.prompt, off = _text(data, off)
    # (mode, walk_load, car_id, x, y, vx, vy, ang, w, stamina, regen, speed_mult, power, pull, flags)
    s.me = SELF_MOTION.unpack_from(data, off)
    off += SELF_MOTION.size
    s.me2 = SELF_EXTRA.unpack_from(data, off)
    off += SELF_EXTRA.size
    # (weapon, arms bitmask, pistol ammo, shotgun ammo, spike strips, roadblocks, bananas, donuts)
    s.arsenal = tuple(data[off:off + 8])
    off += 8
    blocks = data[off]
    off += 1
    s.trunk = s.menu = None
    if blocks & SB_TRUNK:
        cid, cap, used, n = TRUNK_HDR.unpack_from(data, off)
        off += TRUNK_HDR.size
        items = [(PART_IDS[data[off + 2 * k]], data[off + 2 * k + 1]) for k in range(n)]
        off += 2 * n
        s.trunk = (cid, cap, used, items)
    if blocks & SB_MENU:
        s.menu, off = decode_menu(data, off)
    nc, npl, nn, npk, nev, ndl, ntr = COUNTS.unpack_from(data, off)
    off += COUNTS.size
    s.cars = {}
    for _ in range(nc):
        f = CAR.unpack_from(data, off)
        off += CAR.size
        # (id, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, driver, passenger, damage,
        #  model, livery, extras, extras2)
        s.cars[f[0]] = [f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7] / 16.0, f[8] / 16.0,
                        f[9] / 64.0, f[10] / 64.0, f[11] / 65536.0 * 2 * math.pi, f[12], f[13], f[14],
                        f[15], f[16], f[17], f[18]]
    s.players = {}
    for _ in range(npl):
        f = PLAYER.unpack_from(data, off)
        off += PLAYER.size
        name, off = _text(data, off)
        # (id, color, state, flags, x, y, vx, vy, ang, h0, h1, stamina, car_id, name, weapon, z, banner)
        s.players[f[0]] = [f[0], f[1], f[2], f[3], f[4] / 16.0, f[5] / 16.0, f[6] / 64.0, f[7] / 64.0,
                           f[8] / 65536.0 * 2 * math.pi, f[9], f[10], f[11] / 2.55, f[12], name, f[13],
                           f[14] / 10.0, f[15]]
    s.dollies = {}
    for _ in range(ndl):
        f = DOLLY.unpack_from(data, off)
        off += DOLLY.size
        # (id, x, y, ang, part_idx, holder)
        s.dollies[f[0]] = [f[0], f[1] / 16.0, f[2] / 16.0, f[3] / 256.0 * 2 * math.pi, f[4], f[5]]
    s.traps = {}
    for _ in range(ntr):
        f = TRAP.unpack_from(data, off)
        off += TRAP.size
        # (id, kind, x, y, ang, life 0..1)
        s.traps[f[0]] = [f[0], f[1], f[2] / 16.0, f[3] / 16.0, f[4] / 256.0 * 2 * math.pi, f[5] / 255.0]
    s.npcs = {}
    for _ in range(nn):
        f = NPC.unpack_from(data, off)
        off += NPC.size
        # (id, kind, state, x, y, ang, z)
        s.npcs[f[0]] = [f[0], f[1], f[2], f[3] / 16.0, f[4] / 16.0, f[5] / 256.0 * 2 * math.pi, f[6] / 10.0]
    s.pickups = {}
    for _ in range(npk):
        f = PICKUP.unpack_from(data, off)
        off += PICKUP.size
        # (id, part_idx, x, y, scale, z, style)
        s.pickups[f[0]] = [f[0], f[1], f[2] / 16.0, f[3] / 16.0, f[4] / 255.0, f[5] / 10.0, f[6]]
    s.events = []
    for _ in range(nev):
        seq, kind = EV.unpack_from(data, off)
        off += EV.size
        if kind == 0:
            color = data[off]
            text, off = _text(data, off + 1)
            s.events.append((seq, 0, (color, text)))
        elif kind == 1:
            sid, x, y = EV_SFX.unpack_from(data, off)
            off += EV_SFX.size
            s.events.append((seq, 1, (sid, x / 16.0, y / 16.0)))
        else:
            w, x0, y0, x1, y1 = EV_SHOT.unpack_from(data, off)
            off += EV_SHOT.size
            s.events.append((seq, 2, (w, x0 / 16.0, y0 / 16.0, x1 / 16.0, y1 / 16.0)))
    return s

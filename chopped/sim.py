"""
sim.py -- the authoritative world. Pure Python, no pygame, no sockets: the
host runs it at 60 Hz and everybody else just watches the replays (well,
snapshots). Tests poke it directly.

Rule of thumb for this file: if it decides who gets money, who gets arrested
or who goes flying through a windshield, it lives here and only here.
"""

import math
import random

from . import config as C
from .config import clamp, lerp, wrap_angle
from .mapgen import CityMap, GRASS, SIDEWALK
from .parts import (SLOTS, SLOT_ANCHOR, SLOT_CATEGORY, CATEGORY_SLOTS, WHEEL_SLOTS,
                    PANEL_SLOTS, STRIP_TIME, DOLLY, PART_DEFS, Part, part_power,
                    kei_loadout, cop_loadout, personal_loadout)

# ---- enums (ints so they go straight onto the wire) -------------------------
FOOT, DRIVER, PASSENGER, TUMBLE, CUFFED = range(5)
CIV, PERSONAL, COP, TRAFFIC = range(4)
LOCKED, BROKEN_IN, RUNNING, DELIVERED = range(4)
PED, CLOWN, OWNER = range(3)
W_NONE, W_COP, W_PED, W_OWNER, W_CAMERA = range(5)

B_UP, B_DOWN, B_LEFT, B_RIGHT = 1, 2, 4, 8
B_USE, B_SPRINT, B_HANDBRAKE, B_HORN = 16, 32, 64, 128

# toast colours
T_WHITE, T_MONEY, T_BAD, T_INFO, T_COP = range(5)

# sound ids (client maps these to procedural sfx)
(S_CRASH, S_CRASH_BIG, S_BOOM, S_SELL, S_PICKUP, S_BREAKIN, S_HOTWIRE, S_STRIP,
 S_HONK, S_ARREST, S_RENT, S_CRUSH, S_DELIVER, S_DROP, S_INSTALL, S_YELP,
 S_IGNITE, S_BUY, S_PUNCH, S_PISTOL, S_SHOTGUN, S_EMPTY, S_TIRE, S_TRAP, S_ROB) = range(25)

# what's in your hands when you click: keys 1-5
ARM_FISTS, ARM_PISTOL, ARM_SHOTGUN, ARM_SPIKES, ARM_BLOCK = range(5)
ARM_NAMES = ("FISTS", "PISTOL", "SHOTGUN", "SPIKE STRIP", "ROADBLOCK")
TRAP_SPIKES, TRAP_BLOCK = range(2)


def arsenal_owns(arsenal, slot):
    """Client-side Player.owns(), from the 6-byte arsenal in the SELF block:
    (weapon, arms bitmask, pistol ammo, shotgun ammo, spikes, roadblocks)."""
    if not arsenal:
        return slot == ARM_FISTS
    if slot == ARM_SPIKES:
        return arsenal[4] > 0
    if slot == ARM_BLOCK:
        return arsenal[5] > 0
    return bool(arsenal[1] & (1 << slot))


MARKET = {  # crate -> (label, price)
    "pistol": ("PISTOL (+%d ROUNDS)" % C.PISTOL_AMMO, C.PRICE_PISTOL),
    "shotgun": ("SHOTGUN (+%d SHELLS)" % C.SHOTGUN_AMMO, C.PRICE_SHOTGUN),
    "ammo": ("AMMO FOR YOUR GUNS", C.PRICE_AMMO),
    "spikes": ("SPIKE STRIP", C.PRICE_SPIKES),
    "roadblock": ("ROADBLOCK", C.PRICE_ROADBLOCK),
}

SLOT_LABEL = {
    "Engine": "ENGINE", "Transmission": "GEARBOX", "ECU": "ECU", "Exhaust": "EXHAUST",
    "WheelFL": "FRONT-L WHEEL", "WheelFR": "FRONT-R WHEEL", "WheelRL": "REAR-L WHEEL",
    "WheelRR": "REAR-R WHEEL", "Hood": "HOOD", "DoorL": "LEFT DOOR", "DoorR": "RIGHT DOOR",
    "BumperF": "FRONT BUMPER", "BumperR": "REAR BUMPER", "Seats": "SEATS",
}

PED_COMPLAINTS = [
    "HEY! I'M WALKING HERE!", "MY LATTE!!", "I'M CALLING MY MOM", "THAT'S ASSAULT BY HATCHBACK",
    "I HAVE A PODCAST, YOU KNOW", "RUDE.", "MY SPINE IS NOW A SQUIGGLE", "WATCH IT, JOYRIDER!",
    "I'M WRITING A STRONGLY WORDED YELP REVIEW", "NOT THE KNEES!",
]
OWNER_YELLS = [
    "OWNER: THAT'S MY CAR!!", "OWNER: I JUST PAID IT OFF!", "OWNER: COME BACK HERE!",
    "OWNER: IT HAS MY GYM BAG IN IT!", "OWNER: I KNOW WHERE YOU LIVE! (I DON'T)",
    "OWNER: THAT'S A 2004! IT'S A CLASSIC!",
]
CLOWN_LINES = ["HONK!", "HONK HONK!", "*SAD TROMBONE*", "A CLOWN SQUEAKS ANGRILY"]
PUNCH_LINES = ["PEDESTRIAN: OW! MY EVERYTHING!", "PEDESTRIAN: WHAT WAS THAT FOR?!",
               "PEDESTRIAN: I'M TELLING EVERYONE ON THE BUS", "PEDESTRIAN: THAT'S IT, I'M MOVING TO SURREY"]
SHOT_LINES = ["PEDESTRIAN: I'VE BEEN SHOT! (IT'S A GRAZE) (IT'S FINE)", "PEDESTRIAN: MY GOOD JACKET!",
              "PEDESTRIAN: I'M CALLING 911 AND MY LAWYER", "PEDESTRIAN: WHY?! I'M A DENTIST!"]
SURRENDER_LINES = ["PEDESTRIAN: OKAY OKAY! TAKE IT!", "PEDESTRIAN: DON'T SHOOT! I HAVE A PODCAST!",
                   "PEDESTRIAN: HANDS UP! SEE? HANDS! UP!"]
WALLET_EXTRAS = ["(AND A BUS PASS)", "(AND A GYM CARD, NEVER USED)", "(AND A PHOTO OF SOMEONE'S CAT)",
                 "(AND THREE LOTTERY TICKETS, ALL LOSERS)", "(AND A COUPON FOR TIM'S)"]
BAIL_LINES = ["DRIVER: I'M NOT PAID ENOUGH FOR THIS!", "DRIVER: KEEP IT! IT'S LEASED!",
              "DRIVER: I'M CALLING MY INSURANCE (AND MY MOM)", "DRIVER: NOPE. NOPE NOPE NOPE."]
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))

# parts counter: every category's parts, cheapest first
TIERS = {}
for _tid, _d in sorted(PART_DEFS.items(), key=lambda kv: kv[1][3]):
    TIERS.setdefault(_d[1], []).append(_tid)


def _next_tier(type_id):
    """The next pricier part in the same category, or None at the top."""
    tier = TIERS[PART_DEFS[type_id][1]]
    i = tier.index(type_id)
    return tier[i + 1] if i + 1 < len(tier) else None


def buy_price(type_id):
    return int(round(PART_DEFS[type_id][3] * C.BUY_MARKUP))


class InputState:
    """What a player is pressing, and where they're looking. Counters (not
    booleans) for one-shot keys so a tap survives a dropped packet: if the
    number changed, it happened. yaw is the first-person view direction."""
    __slots__ = ("buttons", "use_count", "drop_count", "exit_count", "yaw", "fire_count", "weapon")

    def __init__(self, buttons=0, use_count=0, drop_count=0, exit_count=0, yaw=0.0, fire_count=0, weapon=0):
        self.buttons = buttons
        self.use_count = use_count
        self.drop_count = drop_count
        self.exit_count = exit_count
        self.yaw = yaw
        self.fire_count = fire_count      # clicks, counted (like E) so a dropped packet can't eat a shot
        self.weapon = weapon              # ARM_* slot you've got selected


class Car:
    __slots__ = ("id", "kind", "color", "x", "y", "vx", "vy", "ang", "w", "state", "parts",
                 "alarm", "driver", "passenger", "special", "stolen", "fire_t", "horn",
                 "handbrake", "throttle", "steer", "crash_cd", "impact_dv", "impact_nx",
                 "impact_ny", "damage", "pull", "mass", "inertia", "confused_t", "confuse_cd",
                 "stuck_t", "rev_t", "abandon_t", "flow_key", "flow_t", "last_target",
                 "special_fired", "route", "route_prev", "tdir", "node", "blocked_t", "shaken_t",
                 "overtake_t", "hits")

    def __init__(self, cid, kind, x, y, ang, parts, color=0):
        self.id = cid
        self.kind = kind
        self.color = color
        self.x, self.y, self.ang = x, y, ang
        self.vx = self.vy = self.w = 0.0
        self.state = RUNNING if kind != CIV else LOCKED
        self.parts = parts
        self.alarm = False
        self.driver = None
        self.passenger = None
        self.special = None           # None | "clown" | "owner"
        self.special_fired = False
        self.stolen = False
        self.fire_t = 0.0
        self.horn = False
        self.handbrake = False
        self.throttle = 0.0
        self.steer = 0.0
        self.crash_cd = 0.0
        self.impact_dv = 0.0
        self.impact_nx = self.impact_ny = 0.0
        self.damage = 0
        self.pull = 1.0
        self.mass = C.COP_MASS if kind == COP else C.CAR_MASS
        self.inertia = self.mass * C.CAR_INERTIA_K
        self.confused_t = 0.0
        self.confuse_cd = 0.0
        self.stuck_t = 0.0
        self.rev_t = 0.0
        self.abandon_t = 0.0
        self.flow_key = None
        self.flow_t = 0.0
        self.last_target = None
        # traffic brain: waypoints, current direction, the intersection it's heading for
        self.route = []
        self.route_prev = None        # last waypoint passed: the lane runs from there to route[0]
        self.tdir = (1, 0)
        self.node = (0, 0)
        self.blocked_t = 0.0
        self.shaken_t = 0.0
        self.overtake_t = 0.0
        self.hits = 0                 # bullets taken (cop cars burn after COP_CAR_HITS)

    def power(self):
        # Sum of every part's power. Worn engine alone = 45 = sad trombone.
        return sum(part_power(p.type_id) for p in self.parts.values() if p is not None)

    def speed(self):
        return math.hypot(self.vx, self.vy)

    def missing_wheels(self):
        return sum(1 for s in WHEEL_SLOTS if self.parts.get(s) is None)

    def to_world(self, lx, ly):
        c, s = math.cos(self.ang), math.sin(self.ang)
        return self.x + c * lx - s * ly, self.y + s * lx + c * ly

    def corners(self):
        hl, hw = C.CAR_LEN / 2, C.CAR_WID / 2
        return [self.to_world(a, b) for a, b in ((hl, hw), (hl, -hw), (-hl, hw), (-hl, -hw))]

    def occupants(self):
        return [p for p in (self.driver, self.passenger) if p is not None]

    def wanted(self):
        return self.kind == CIV and self.stolen and self.state != DELIVERED


class Player:
    __slots__ = ("id", "name", "color", "x", "y", "vx", "vy", "ang", "state", "car_id", "hands",
                 "stamina", "exhausted", "regen_delay", "tumble_t", "spin", "spin_rate",
                 "cuffed_t", "arrest_t", "input", "prev_use", "prev_drop", "prev_exit",
                 "hold_key", "hold", "need_release", "prompt", "hold_frac", "sprinting",
                 "moving", "last_seen", "addr", "dolly", "weapon", "arms", "ammo", "gear", "fire_cd",
                 "prev_fire")

    def __init__(self, pid, name, color):
        self.id = pid
        self.name = name
        self.color = color
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.ang = math.pi / 2
        self.state = FOOT
        self.car_id = None
        self.hands = []
        self.stamina = C.STAMINA_MAX
        self.exhausted = False
        self.regen_delay = 0.0
        self.tumble_t = 0.0
        self.spin = 0.0
        self.spin_rate = 0.0
        self.cuffed_t = 0.0
        self.arrest_t = 0.0
        self.input = InputState()
        self.prev_use = self.prev_drop = self.prev_exit = 0
        self.hold_key = None
        self.hold = 0.0
        self.need_release = False
        self.prompt = ""
        self.hold_frac = 0.0
        self.sprinting = False
        self.moving = False
        self.dolly = None             # the Dolly you're pushing (it takes both hands)
        self.weapon = ARM_FISTS
        self.arms = 1 << ARM_FISTS    # bitmask of what you own; everyone owns fists
        self.ammo = [0, 0, 0]         # per ARM_ slot (fists don't need any)
        self.gear = [0, 0]            # spike strips, roadblocks
        self.fire_cd = 0.0
        self.prev_fire = 0

    def hands_used(self):
        if self.dolly is not None:
            return 2
        return sum(p.bulk for p in self.hands)

    def can_hold(self, part):
        return part.bulk != DOLLY and self.hands_used() + part.bulk <= 2

    def walk_load(self):
        """0..2, how hard walking/sprinting is on your stamina."""
        if self.dolly is not None:
            return 2 if self.dolly.part is not None else 1
        return min(2, self.hands_used())

    def owns(self, slot):
        if slot == ARM_SPIKES:
            return self.gear[0] > 0
        if slot == ARM_BLOCK:
            return self.gear[1] > 0
        return bool(self.arms & (1 << slot))

    def speed_mult(self):
        if self.dolly is not None:
            return C.DOLLY_LOADED_SPEED_MULT if self.dolly.part is not None else C.DOLLY_SPEED_MULT
        return C.TWO_HAND_SPEED_MULT if self.hands_used() >= 2 else 1.0


class NPC:
    __slots__ = ("id", "kind", "x", "y", "vx", "vy", "ang", "tumble_t", "life_t", "dirx", "diry",
                 "turn_t", "target", "yell_t", "complain_cd", "spin", "flee_t", "fx", "fy", "ttl", "wallet",
                 "wallet_t", "surrender_t")

    def __init__(self, nid, kind, x, y):
        self.id = nid
        self.kind = kind
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.ang = 0.0
        self.tumble_t = 0.0
        self.life_t = 0.0
        self.dirx, self.diry = 1.0, 0.0
        self.turn_t = 0.0
        self.target = None
        self.yell_t = 2.0
        self.complain_cd = 0.0
        self.spin = 0.0
        self.flee_t = 0.0             # > 0: running away from something loud and fast
        self.fx, self.fy = 1.0, 0.0
        self.ttl = 0.0                # > 0: temporary extra (a driver who bailed); gone when it runs out
        self.wallet = (C.WALLET_MIN + C.WALLET_MAX) // 2   # World rolls a proper one for pedestrians
        self.wallet_t = 0.0           # counts down to a refilled wallet after a robbery
        self.surrender_t = 0.0        # > 0: hands up, someone's pointing a gun at them


class Dolly:
    """A hand truck. Carries one dolly-only part (an engine); pushing it takes
    both hands."""
    __slots__ = ("id", "x", "y", "ang", "part", "holder", "idle_t")

    def __init__(self, did, x, y):
        self.id = did
        self.x, self.y = x, y
        self.ang = -math.pi / 2
        self.part = None
        self.holder = None            # player id
        self.idle_t = 0.0


class Trap:
    """A spike strip or a roadblock, lying across the road. ang is the way the
    traffic it's meant for is travelling (0 or pi/2 or ...), so the long side
    is across the lane."""
    __slots__ = ("id", "kind", "x", "y", "ang", "age", "uses", "hit")

    def __init__(self, tid, kind, x, y, ang):
        self.id = tid
        self.kind = kind
        self.x, self.y, self.ang = x, y, ang
        self.age = 0.0
        self.uses = C.SPIKE_USES
        self.hit = set()

    def rect(self):
        """Axis-aligned (x, y, w, h): traps only ever go down square to the street grid."""
        long_, short = ((C.SPIKE_LEN, C.SPIKE_WID) if self.kind == TRAP_SPIKES
                        else (C.ROADBLOCK_LEN, C.ROADBLOCK_WID))
        if abs(math.cos(self.ang)) > 0.5:          # traffic runs along x: the trap spans y
            w, h = short, long_
        else:
            w, h = long_, short
        return (self.x - w / 2, self.y - h / 2, w, h)


class Pickup:
    __slots__ = ("id", "part", "x", "y", "vx", "vy", "age")

    def __init__(self, pid, part, x, y, vx=0.0, vy=0.0):
        self.id = pid
        self.part = part
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.age = 0.0

    def scale(self):
        left = C.PICKUP_LIFETIME - self.age
        return clamp(left / C.PICKUP_SHRINK, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Collision helpers
# ---------------------------------------------------------------------------
HL, HW = C.CAR_LEN / 2.0, C.CAR_WID / 2.0     # a car is a 4.4 x 2.4 m box now, corners and all
CAR_BOUND_R = math.hypot(HL, HW)               # ...that fits in a 2.5 m circle for broad-phase checks
CONTACT_TIE = 0.12                             # corners closer than this in depth count as "flush"


def circle_rect_contact(x, y, r, rect):
    """Returns (nx, ny, pen, px, py) if the circle overlaps the AABB, else None.
    (px, py) is the contact point on the rect."""
    rx, ry, rw, rh = rect
    cx = rx if x < rx else rx + rw if x > rx + rw else x
    cy = ry if y < ry else ry + rh if y > ry + rh else y
    dx, dy = x - cx, y - cy
    d2 = dx * dx + dy * dy
    if d2 >= r * r:
        return None
    if d2 > 1e-10:
        d = math.sqrt(d2)
        return dx / d, dy / d, r - d, cx, cy
    # centre is inside the rect: shove out along the shallowest axis
    l, rr, t, b = x - rx, rx + rw - x, y - ry, ry + rh - y
    m = min(l, rr, t, b)
    if m == l:
        return -1.0, 0.0, l + r, rx, y
    if m == rr:
        return 1.0, 0.0, rr + r, rx + rw, y
    if m == t:
        return 0.0, -1.0, t + r, x, ry
    return 0.0, 1.0, b + r, x, ry + rh


def _box_point(x, y, c, s, dx, dy):
    """The corner of a car box that sticks out furthest along (dx, dy). When
    two corners are within CONTACT_TIE of each other (a flush bumper against a
    wall) we take the middle of that edge instead -- otherwise a dead-straight
    hit would spin the car off whichever corner won the rounding lottery."""
    pf = c * dx + s * dy
    pr = -s * dx + c * dy
    lx = 0.0 if 2 * HL * abs(pf) < CONTACT_TIE else (HL if pf > 0 else -HL)
    ly = 0.0 if 2 * HW * abs(pr) < CONTACT_TIE else (HW if pr > 0 else -HW)
    return x + c * lx - s * ly, y + s * lx + c * ly


def _clamp_to_box(px, py, x, y, c, s):
    lx = clamp((px - x) * c + (py - y) * s, -HL, HL)
    ly = clamp(-(px - x) * s + (py - y) * c, -HW, HW)
    return x + c * lx - s * ly, y + s * lx + c * ly


def obb_rect_contact(x, y, ang, rect):
    """Car box vs axis-aligned rect, separating-axis test on the 4 candidate
    axes. Returns (nx, ny, pen, px, py) with the normal pointing from the rect
    towards the car, or None."""
    rx, ry, rw, rh = rect
    ex, ey = rw * 0.5, rh * 0.5
    dx, dy = rx + ex - x, ry + ey - y            # car centre -> rect centre
    c, s = math.cos(ang), math.sin(ang)
    ac, asn = abs(c), abs(s)
    ox = HL * ac + HW * asn + ex - abs(dx)
    if ox <= 0:
        return None
    oy = HL * asn + HW * ac + ey - abs(dy)
    if oy <= 0:
        return None
    df = dx * c + dy * s
    of = HL + ex * ac + ey * asn - abs(df)
    if of <= 0:
        return None
    dr = -dx * s + dy * c
    orr = HW + ex * asn + ey * ac - abs(dr)
    if orr <= 0:
        return None
    # Prefer the rect's own faces unless a car face is clearly shallower:
    # walls are axis-aligned, and a normal that flickers between two
    # candidates is how cars end up vibrating against buildings.
    if min(ox, oy) <= min(of, orr) * 1.05 + 0.02:
        if ox <= oy:
            nx, ny, pen = (-1.0 if dx > 0 else 1.0), 0.0, ox
        else:
            nx, ny, pen = 0.0, (-1.0 if dy > 0 else 1.0), oy
        px, py = _box_point(x, y, c, s, -nx, -ny)          # deepest car corner(s)
        px = clamp(px, rx, rx + rw)
        py = clamp(py, ry, ry + rh)
    else:
        if of <= orr:
            ax, ay, pen, dd = c, s, of, df
        else:
            ax, ay, pen, dd = -s, c, orr, dr
        sg = -1.0 if dd > 0 else 1.0
        nx, ny = ax * sg, ay * sg
        # the rect corner poking deepest into the car (a building corner in the door)
        qx = rx + rw * 0.5 if rw * abs(nx) < CONTACT_TIE else (rx + rw if nx > 0 else rx)
        qy = ry + rh * 0.5 if rh * abs(ny) < CONTACT_TIE else (ry + rh if ny > 0 else ry)
        px, py = _clamp_to_box(qx, qy, x, y, c, s)
    return nx, ny, pen, px, py


def obb_obb_contact(a, b):
    """Car box vs car box. Returns (nx, ny, pen, px, py), normal pointing from
    b to a, or None. Same SAT idea with both cars' axes as candidates."""
    dx, dy = b.x - a.x, b.y - a.y
    ca, sa = math.cos(a.ang), math.sin(a.ang)
    cb, sb = math.cos(b.ang), math.sin(b.ang)
    best = None
    for ux, uy, owner in ((ca, sa, 0), (-sa, ca, 0), (cb, sb, 1), (-sb, cb, 1)):
        ra = HL * abs(ux * ca + uy * sa) + HW * abs(-ux * sa + uy * ca)
        rb = HL * abs(ux * cb + uy * sb) + HW * abs(-ux * sb + uy * cb)
        dd = dx * ux + dy * uy
        ov = ra + rb - abs(dd)
        if ov <= 0:
            return None
        if best is None or ov < best[0] - 0.01:
            best = (ov, ux, uy, dd, owner)
    pen, ux, uy, dd, owner = best
    sg = -1.0 if dd > 0 else 1.0
    nx, ny = ux * sg, uy * sg                     # from b towards a
    if owner == 0:     # a's face: b's corner is doing the poking
        px, py = _box_point(b.x, b.y, cb, sb, nx, ny)
        px, py = _clamp_to_box(px, py, a.x, a.y, ca, sa)
    else:              # b's face: a's corner is doing the poking
        px, py = _box_point(a.x, a.y, ca, sa, -nx, -ny)
        px, py = _clamp_to_box(px, py, b.x, b.y, cb, sb)
    return nx, ny, pen, px, py


def box_distance(car, x, y):
    """Distance from a point to a car's box (0 if inside)."""
    c, s = math.cos(car.ang), math.sin(car.ang)
    lx = abs((x - car.x) * c + (y - car.y) * s) - HL
    ly = abs(-(x - car.x) * s + (y - car.y) * c) - HW
    return math.hypot(max(lx, 0.0), max(ly, 0.0))


def drive_input(car, buttons):
    """Driver's buttons -> pedals and wheel. Shared by the server and the
    client-side predictor so they can't disagree about what W means."""
    car.throttle = (1.0 if buttons & B_UP else 0.0) - (1.0 if buttons & B_DOWN else 0.0)
    car.steer = (1.0 if buttons & B_RIGHT else 0.0) - (1.0 if buttons & B_LEFT else 0.0)
    car.handbrake = bool(buttons & B_HANDBRAKE)


class Physics:
    """Movement and collision maths, shared by the authoritative World and
    the client-side Predictor (predict.py). Same code on both ends is the whole
    trick of prediction: if the client ran different maths, it would predict a
    different car and the server would keep yanking it back.

    Subclasses provide self.map, self.cars, self._rects (a scratch list) and
    self.extra_rects (roadblocks: solid for cars and people alike)."""

    # ------------------------------------------------------------------ cars
    def _drive(self, car, dt):
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        rx, ry = -fy, fx
        vf = car.vx * fx + car.vy * fy
        vr = car.vx * rx + car.vy * ry
        driven = car.driver is not None or car.kind == COP or car.kind == TRAFFIC
        mw = car.missing_wheels()
        on_grass = self.map.tile_at(car.x, car.y) == 3  # GRASS
        if car.kind == COP:
            accel = C.ACCEL_PER_100_POWER * C.COP_ACCEL_MULT
            top = C.COP_TOP_SPEED
        else:
            accel = C.ACCEL_PER_100_POWER * car.power() / 100.0
            top = C.CIV_TOP_SPEED
        if car.state == DELIVERED:
            driven = False            # delivered cars never drive again. RIP.
        top *= (1.0 - C.MISSING_WHEEL_TOP * mw)
        thr = car.throttle if driven else 0.0
        hb = car.handbrake if driven else False
        if thr > 0:
            if vf < -0.5:
                vf = min(0.0, vf + C.BRAKE_DECEL * thr * dt)
            else:
                vf += accel * thr * dt
        elif thr < 0:
            if vf > 0.5:
                vf = max(0.0, vf + C.BRAKE_DECEL * thr * dt)
            else:
                vf += accel * C.REVERSE_FRAC * thr * dt
                vf = max(vf, -C.REVERSE_MAX)
        else:
            dec = (C.ROLL_DECEL if driven else C.PARKED_BRAKE) * dt
            vf = vf - dec if vf > dec else vf + dec if vf < -dec else 0.0
        vf -= C.DRAG_K * vf * abs(vf) * dt
        if on_grass:
            vf -= math.copysign(min(abs(vf), C.GRASS_DRAG * dt), vf)
        if hb:
            vf = max(0.0, vf - C.HANDBRAKE_DECEL * dt) if vf > 0 else min(0.0, vf + C.HANDBRAKE_DECEL * dt)
        vf = clamp(vf, -C.REVERSE_MAX, top)
        grip = C.HANDBRAKE_GRIP if hb else C.GRIP
        if abs(vr) > C.SLIDE_THRESHOLD:
            grip *= C.SLIDE_GRIP_MULT
        if on_grass:
            grip *= C.GRASS_GRIP_MULT
        grip *= max(0.2, 1.0 - C.MISSING_WHEEL_GRIP * mw)
        vr *= math.exp(-grip * dt)
        # steering: full lock at low speed, shrinking as you go faster
        aspd = abs(vf)
        sf = min(1.0, aspd / C.STEER_FULL_AT)
        lock = lerp(C.STEER_RATE_LOW, C.STEER_RATE_HIGH, clamp(aspd / C.CIV_TOP_SPEED, 0.0, 1.0))
        target_w = (car.steer if driven else 0.0) * lock * sf * (1.0 if vf >= 0 else -1.0)
        if hb:
            target_w *= C.HANDBRAKE_YAW_MULT
        if mw:
            target_w += car.pull * C.MISSING_WHEEL_PULL * mw * sf
        resp = C.STEER_RESPONSE * (0.35 if hb else 1.0)
        car.w += (target_w - car.w) * min(1.0, resp * dt)
        car.vx = fx * vf + rx * vr
        car.vy = fy * vf + ry * vr
        car.x += car.vx * dt
        car.y += car.vy * dt
        car.ang = wrap_angle(car.ang + car.w * dt)

    def _apply_static_contact(self, car, px, py, nx, ny, pen, e):
        car.x += nx * pen
        car.y += ny * pen
        rx, ry = px - car.x, py - car.y
        vcx = car.vx - car.w * ry
        vcy = car.vy + car.w * rx
        vn = vcx * nx + vcy * ny
        if vn >= 0:
            return
        rn = rx * ny - ry * nx
        j = -(1.0 + e) * vn / (1.0 / car.mass + rn * rn / car.inertia)
        car.vx += j * nx / car.mass
        car.vy += j * ny / car.mass
        car.w += rn * j / car.inertia
        # scrape friction: walls are not ice rinks
        tx, ty = -ny, nx
        vt = vcx * tx + vcy * ty
        ft = clamp(-vt * car.mass * 0.25, -0.3 * j, 0.3 * j)
        car.vx += ft * tx / car.mass
        car.vy += ft * ty / car.mass
        dv = j / car.mass
        car.impact_dv += dv
        car.impact_nx += nx * dv
        car.impact_ny += ny * dv

    def _car_vs_world(self, car):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(car.x, car.y, CAR_BOUND_R, rects)
        rects.extend(self.extra_rects)             # roadblocks (few; the SAT test rejects far ones fast)
        for rect in rects:
            hit = obb_rect_contact(car.x, car.y, car.ang, rect)
            if hit:
                nx, ny, pen, px, py = hit
                self._apply_static_contact(car, px, py, nx, ny, pen, C.RESTITUTION_WALL)

    def _car_pair(self, a, b):
        """Box-vs-box bump with a proper impulse at the contact point, so a
        T-bone spins the victim and a nudge on the bumper just pushes. Returns
        the closing speed (for "was that hard enough to set a cop on fire?")
        or None if they didn't touch."""
        hit = obb_obb_contact(a, b)
        if hit is None:
            return None
        nx, ny, pen, px, py = hit                  # normal points from b to a
        ima, imb = 1.0 / a.mass, 1.0 / b.mass
        a.x += nx * pen * ima / (ima + imb)
        a.y += ny * pen * ima / (ima + imb)
        b.x -= nx * pen * imb / (ima + imb)
        b.y -= ny * pen * imb / (ima + imb)
        rax, ray = px - a.x, py - a.y
        rbx, rby = px - b.x, py - b.y
        vax = a.vx - a.w * ray
        vay = a.vy + a.w * rax
        vbx = b.vx - b.w * rby
        vby = b.vy + b.w * rbx
        vn = (vax - vbx) * nx + (vay - vby) * ny
        if vn >= 0:
            return None
        rel = math.hypot(a.vx - b.vx, a.vy - b.vy)
        rna = rax * ny - ray * nx
        rnb = rbx * ny - rby * nx
        j = -(1.0 + C.RESTITUTION_CAR) * vn / (ima + imb + rna * rna / a.inertia + rnb * rnb / b.inertia)
        a.vx += j * nx * ima
        a.vy += j * ny * ima
        a.w += rna * j / a.inertia
        b.vx -= j * nx * imb
        b.vy -= j * ny * imb
        b.w -= rnb * j / b.inertia
        dva, dvb = j * ima, j * imb
        a.impact_dv += dva
        a.impact_nx += nx * dva
        a.impact_ny += ny * dva
        b.impact_dv += dvb
        b.impact_nx -= nx * dvb
        b.impact_ny -= ny * dvb
        return rel

    # ------------------------------------------------------------------ people
    def _walk(self, p, b, dt):
        """On-foot controls -> stamina, facing and velocity. The predictor runs
        this too, so it may only read things the client is told about."""
        # first person: W/S along where you're looking, A/D strafe
        fwd = (1 if b & B_UP else 0) - (1 if b & B_DOWN else 0)
        side = (1 if b & B_RIGHT else 0) - (1 if b & B_LEFT else 0)
        ca, sa = math.cos(p.ang), math.sin(p.ang)
        dx, dy = ca * fwd - sa * side, sa * fwd + ca * side
        moving = fwd != 0 or side != 0
        used = p.walk_load()
        want_sprint = bool(b & B_SPRINT) and moving and not p.exhausted and p.stamina > 0
        if want_sprint:
            p.stamina -= C.STAMINA_SPRINT_DRAIN[min(used, 2)] * dt
            p.regen_delay = C.STAMINA_REGEN_DELAY
        elif moving and used >= 2:
            p.stamina -= C.STAMINA_WALK_2H_DRAIN * dt
            p.regen_delay = C.STAMINA_REGEN_DELAY
        else:
            p.regen_delay -= dt
            if p.regen_delay <= 0:
                p.stamina = min(C.STAMINA_MAX, p.stamina + C.STAMINA_REGEN * dt)
        if p.stamina <= 0:
            p.stamina = 0.0
            p.exhausted = True
        elif p.exhausted and p.stamina > C.STAMINA_RECOVER_AT:
            p.exhausted = False
        spd = (C.SPRINT_SPEED if want_sprint else C.WALK_SPEED) * p.speed_mult()
        if p.exhausted:
            spd *= C.EXHAUSTED_SPEED_MULT
        if moving:
            inv = 1.0 / math.hypot(dx, dy)
            tx, ty = dx * inv * spd, dy * inv * spd
        else:
            tx = ty = 0.0
        k = min(1.0, 16.0 * dt)
        p.vx += (tx - p.vx) * k
        p.vy += (ty - p.vy) * k
        p.sprinting = want_sprint
        p.moving = moving

    def _body_vs_world(self, b, r):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(b.x, b.y, r, rects)
        rects.extend(self.extra_rects)
        for rect in rects:
            hit = circle_rect_contact(b.x, b.y, r, rect)
            if hit:
                nx, ny, pen, _, _ = hit
                b.x += nx * pen
                b.y += ny * pen
                vn = b.vx * nx + b.vy * ny
                if vn < 0:
                    b.vx -= vn * nx * 1.3
                    b.vy -= vn * ny * 1.3

    def _body_vs_cars(self, b, r):
        """Circle (a person) vs every car box nearby: shove them out, kill the
        closing velocity, and report the hardest hit as (rel_speed, car_vx,
        car_vy, nx, ny) so the caller can decide who goes ragdoll."""
        result = None
        reach = CAR_BOUND_R + r
        for car in self.cars.values():
            dx, dy = b.x - car.x, b.y - car.y
            if abs(dx) > reach or abs(dy) > reach:
                continue
            c, s = math.cos(car.ang), math.sin(car.ang)
            lx = dx * c + dy * s
            ly = -dx * s + dy * c
            qx = HL if lx > HL else -HL if lx < -HL else lx
            qy = HW if ly > HW else -HW if ly < -HW else ly
            ex, ey = lx - qx, ly - qy
            d2 = ex * ex + ey * ey
            if d2 > 1e-12:
                if d2 >= r * r:
                    continue
                d = math.sqrt(d2)
                nlx, nly, pen = ex / d, ey / d, r - d
            else:
                # centre inside the car (it drove onto you): out the nearest side
                fx, fy = HL - abs(lx), HW - abs(ly)
                if fx < fy:
                    nlx, nly, pen = (1.0 if lx >= 0 else -1.0), 0.0, fx + r
                else:
                    nlx, nly, pen = 0.0, (1.0 if ly >= 0 else -1.0), fy + r
            nx, ny = nlx * c - nly * s, nlx * s + nly * c
            b.x += nx * pen
            b.y += ny * pen
            rel = math.hypot(car.vx - b.vx, car.vy - b.vy)
            vn = (b.vx - car.vx) * nx + (b.vy - car.vy) * ny
            if vn < 0:
                b.vx -= vn * nx
                b.vy -= vn * ny
            if result is None or rel > result[0]:
                result = (rel, car.vx, car.vy, nx, ny)
        return result



class World(Physics):
    def __init__(self, map_seed=None, rng_seed=None):
        if map_seed is None:
            map_seed = random.randrange(1, 2 ** 31)
        self.map_seed = map_seed
        self.map = CityMap(map_seed)
        self.rng = random.Random(rng_seed if rng_seed is not None else map_seed ^ 0x5EED)
        self.tick = 0
        self.time = 0.0
        self._next_id = 1
        self.cars = {}
        self.players = {}
        self.npcs = {}
        self.pickups = {}
        self.dollies = {}
        self.traps = {}
        self.extra_rects = []       # roadblocks, as solid rects (rebuilt when traps change)
        self.give_loadout = False   # --selftest: everyone joins armed, so the bot exercises the guns
        self.events = []            # (seq, time, kind, payload)
        self.event_seq = 0
        self.cash = C.START_CASH
        self.day = 1
        self.day_t = C.DAY_LENGTH       # seconds until midnight (rent)
        self.day_stats = [0, 0, 0]      # cars delivered, parts sold, dollars earned today
        self.debt_t = 0.0
        self.gameover_t = 0.0
        self.run = 1
        self.heat = 0.0
        self.witness = W_NONE
        self.witness_rate = 0.0
        self.unseen_t = 0.0
        self.heat_zero_t = 0.0
        self.cop_spawn_t = 0.0
        self.civ_respawn_t = None
        self.dispatched = False     # latched when heat hits 100; cleared when heat hits 0
        self.witness_accum = 0.0
        self.targets = []           # wanted targets: (x, y, vx, vy, is_car, ref)
        self._rects = []            # scratch list for collision queries (no per-tick allocs)
        self.traffic_t = 0.0
        self.traffic_target = C.TRAFFIC_COUNT    # tests set 0 for a city with no surprises
        self.scare_accum = 0.0
        self.personal_id = None
        self._spawn_personal(personal_loadout())
        for k in range(C.DOLLY_COUNT):
            dx, dy = self.map.dolly_spot
            d = Dolly(self.new_id(), dx - k * 1.6, dy)
            self.dollies[d.id] = d
        for _ in range(C.PED_COUNT):
            self._spawn_ped()
        for _ in range(C.MAX_CIVILIAN_CARS):
            self._spawn_civilian(ignore_players=True)
        for _ in range(self.traffic_target):
            self._spawn_traffic(ignore_players=True)

    # ------------------------------------------------------------------ ids/events
    def new_id(self):
        while True:
            i = self._next_id
            self._next_id = (self._next_id % 65000) + 1
            if (i not in self.cars and i not in self.npcs and i not in self.pickups and i not in self.dollies
                    and i not in self.traps):
                return i

    def toast(self, text, color=T_WHITE):
        self.event_seq += 1
        self.events.append((self.event_seq, self.time, 0, (color, text[:60])))

    def sfx(self, sid, x, y):
        self.event_seq += 1
        self.events.append((self.event_seq, self.time, 1, (sid, x, y)))

    def tracer(self, weapon, x0, y0, x1, y1):
        """A bullet's path, for the muzzle flash and tracer on everyone's screen."""
        self.event_seq += 1
        self.events.append((self.event_seq, self.time, 2, (weapon, x0, y0, x1, y1)))

    def _prune_events(self):
        cutoff = self.time - C.EVENT_KEEP_S
        if self.events and self.events[0][1] < cutoff:
            self.events = [e for e in self.events if e[1] >= cutoff]

    # ------------------------------------------------------------------ spawning
    def _spawn_personal(self, parts):
        bx, by, ba = self.map.bay
        car = Car(self.new_id(), PERSONAL, bx, by, ba, parts, color=0)
        self.cars[car.id] = car
        self.personal_id = car.id
        return car

    def _spawn_civilian(self, ignore_players=False):
        spots = list(self.map.parking)
        self.rng.shuffle(spots)
        for (x, y, a) in spots:
            if not ignore_players and any(math.hypot(p.x - x, p.y - y) < C.CIV_SPAWN_MIN_DIST
                                          for p in self.players.values()):
                continue
            if any(math.hypot(c.x - x, c.y - y) < 6.0 for c in self.cars.values()):
                continue
            car = Car(self.new_id(), CIV, x, y, a, kei_loadout(self.rng),
                      color=self.rng.randrange(1, 9))
            r = self.rng.random()
            if r < C.CLOWN_CHANCE:
                car.special = "clown"
            elif r < C.CLOWN_CHANCE + C.OWNER_CHANCE:
                car.special = "owner"
            car.pull = self.rng.choice((-1.0, 1.0))
            self.cars[car.id] = car
            return car
        return None

    def _spawn_ped(self):
        tx, ty = self.rng.choice(self.map.sidewalk_tiles)
        n = NPC(self.new_id(), PED, (tx + 0.5) * C.TILE_M, (ty + 0.5) * C.TILE_M)
        n.wallet = self.rng.randint(C.WALLET_MIN, C.WALLET_MAX)
        n.dirx, n.diry = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        self.npcs[n.id] = n
        return n

    def spawn_cop(self):
        if not self.targets:
            return None
        tx, ty = self.targets[0][0], self.targets[0][1]
        best = None
        for (x, y, a) in self.map.cop_spawns:
            if any(math.hypot(p.x - x, p.y - y) < C.COP_SPAWN_MIN_DIST for p in self.players.values()):
                continue
            if any(math.hypot(c.x - x, c.y - y) < 6.0 for c in self.cars.values()):
                continue
            d = math.hypot(tx - x, ty - y)
            if best is None or d < best[0]:
                best = (d, x, y, a)
        if best is None:
            return None
        _, x, y, a = best
        car = Car(self.new_id(), COP, x, y, a, cop_loadout(self.rng), color=0)
        self.cars[car.id] = car
        self.toast("COPS ARE ROLLING IN!", T_COP)
        return car

    def add_pickup(self, part, x, y, vx=0.0, vy=0.0):
        pk = Pickup(self.new_id(), part, x, y, vx, vy)
        self.pickups[pk.id] = pk
        if len(self.pickups) > C.MAX_PICKUPS:
            oldest = max(self.pickups.values(), key=lambda q: q.age)
            del self.pickups[oldest.id]
        return pk

    # ------------------------------------------------------------------ players
    def add_player(self, name, pid=None):
        if len(self.players) >= C.MAX_PLAYERS:
            return None
        if pid is None:
            pid = next(i for i in range(1, C.MAX_PLAYERS + 1) if i not in self.players)
        p = Player(pid, (name or "PLAYER%d" % pid)[:12].upper(), (pid - 1) % 4)
        sx, sy = self.map.player_spawns[(pid - 1) % 4]
        p.x, p.y = sx, sy
        if self.give_loadout:
            p.arms |= (1 << ARM_PISTOL) | (1 << ARM_SHOTGUN)
            p.ammo = [0, C.MAX_AMMO, C.MAX_AMMO]
            p.gear = [C.MAX_TRAPS_EACH, C.MAX_TRAPS_EACH]
        self.players[pid] = p
        self.toast("%s JOINED THE CREW" % p.name, T_INFO)
        return p

    def remove_player(self, pid):
        p = self.players.get(pid)
        if not p:
            return
        self._leave_car(p, place=True)
        self._drop_all(p)
        self._release_dolly(p)
        del self.players[pid]
        self.toast("%s LEFT" % p.name, T_INFO)

    def set_input(self, pid, inp):
        p = self.players.get(pid)
        if p:
            p.input = inp

    def _drop_all(self, p):
        for i, part in enumerate(p.hands):
            a = self.rng.uniform(0, 2 * math.pi)
            self.add_pickup(part, p.x + math.cos(a) * 0.6, p.y + math.sin(a) * 0.6,
                            math.cos(a) * 2.5, math.sin(a) * 2.5)
        p.hands = []

    def _enter_car(self, p, car, seat):
        self._release_dolly(p)        # it'd never fit in a Kei anyway
        if seat == DRIVER and car.kind == CIV and not car.stolen and car.state == RUNNING:
            # a car whose driver bailed, engine still running: finders keepers, says nobody
            car.stolen = True
            self._crime(C.HEAT_BREAKIN)
            self.toast("%s TOOK A CAR IN BROAD DAYLIGHT. +%d HEAT" % (p.name, C.HEAT_BREAKIN), T_BAD)
        if seat == DRIVER:
            car.driver = p.id
        else:
            car.passenger = p.id
        p.state = seat
        p.car_id = car.id
        p.vx = p.vy = 0.0

    def _leave_car(self, p, place=True):
        car = self.cars.get(p.car_id) if p.car_id is not None else None
        if car:
            if car.driver == p.id:
                car.driver = None
            if car.passenger == p.id:
                car.passenger = None
            if place:
                self._place_beside(p, car)
        p.car_id = None
        if p.state in (DRIVER, PASSENGER):
            p.state = FOOT

    def _place_beside(self, p, car):
        for lx, ly in ((0, -2.1), (0, 2.1), (-3.0, 0), (3.0, 0), (0, -3.5), (0, 3.5)):
            x, y = car.to_world(lx, ly)
            if not self._blocked(x, y, C.PLAYER_RADIUS, exclude=car):
                p.x, p.y = x, y
                return
        p.x, p.y = car.x, car.y

    def _blocked(self, x, y, r, exclude=None):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(x, y, r, rects)
        for rect in rects:
            if circle_rect_contact(x, y, r, rect):
                return True
        for c in self.cars.values():
            if c is exclude:
                continue
            if math.hypot(c.x - x, c.y - y) < 2.4 + r:
                return True
        return False

    def eject(self, car, dv):
        t = lerp(C.TUMBLE_MIN, C.TUMBLE_MAX, clamp((dv - C.CRASH_EJECT_DV) / 12.0, 0, 1))
        for pid in car.occupants():
            p = self.players.get(pid)
            if not p:
                continue
            self._leave_car(p, place=True)
            self._tumble(p, car.vx * 0.6 + self.rng.uniform(-3, 3),
                         car.vy * 0.6 + self.rng.uniform(-3, 3), t)
            self.toast("%s WENT THROUGH THE WINDSHIELD" % p.name, T_BAD)

    def _tumble(self, p, vx, vy, t):
        self._release_dolly(p)
        p.state = TUMBLE
        p.tumble_t = max(p.tumble_t, t)
        p.vx, p.vy = vx, vy
        p.spin_rate = self.rng.choice((-1, 1)) * self.rng.uniform(8, 16)

    # ------------------------------------------------------------------ main step
    def step(self, dt):
        self.tick += 1
        self.time += dt
        self._prune_events()
        if self.gameover_t > 0:
            self.gameover_t -= dt
            if self.gameover_t <= 0:
                self.reset_run()
            return
        self._economy(dt)
        for car in self.cars.values():
            car.horn = False          # re-latched every tick by whoever is leaning on it
        for p in self.players.values():
            self._update_player_input(p, dt)
        for car in list(self.cars.values()):
            if car.kind == COP:
                self._cop_ai(car, dt)
            elif car.kind == TRAFFIC:
                self._traffic_ai(car, dt)
        self._horns(dt)
        self._physics_cars(dt)
        self._update_traps(dt)
        self._sync_occupants()
        for p in self.players.values():
            self._move_player(p, dt)
        self._update_dollies(dt)
        self._update_npcs(dt)
        self._update_pickups(dt)
        self._fires(dt)
        self._deliveries()
        self._heat(dt)
        self._cops_lifecycle(dt)
        self._arrests(dt)
        self._traffic(dt)
        self._traffic_fleet(dt)

    # ------------------------------------------------------------------ economy
    def rent_due(self):
        return C.rent_for_day(self.day)

    def _earn(self, amount, parts=0):
        self.cash += amount
        self.day_stats[1] += parts
        self.day_stats[2] += amount

    def _economy(self, dt):
        self.day_t -= dt
        if self.day_t <= 0:
            rent = self.rent_due()
            cars, parts, earned = self.day_stats
            self.toast("DAY %d DONE: %d CARS, %d PARTS, +$%d" % (self.day, cars, parts, earned), T_INFO)
            self.cash -= rent
            self.toast("MIDNIGHT. THE LANDLORD TAKES $%d" % rent, T_BAD)
            self.sfx(S_RENT, *self.map.garage_center)
            self.day += 1
            self.day_t += C.DAY_LENGTH
            self.day_stats = [0, 0, 0]
            self.toast("DAY %d. RENT AT MIDNIGHT: $%d" % (self.day, self.rent_due()), T_INFO)
        if self.cash < 0:
            self.debt_t += dt
            if self.debt_t >= C.DEBT_GRACE:
                self.gameover_t = C.GAMEOVER_BANNER
                self.toast("THE LANDLORD CHANGED THE LOCKS. SHOP SEIZED!", T_BAD)
        else:
            self.debt_t = 0.0

    def reset_run(self):
        """New run after SHOP SEIZED. Your personal ride keeps every mod you
        bolted on -- the one thing the landlord can't take is your pride
        (and your 6-speed)."""
        self.run += 1
        self.cash = C.START_CASH
        self.day = 1
        self.day_t = C.DAY_LENGTH
        self.day_stats = [0, 0, 0]
        self.debt_t = 0.0
        self.gameover_t = 0.0
        self.heat = 0.0
        self.dispatched = False
        self.unseen_t = 0.0
        self.witness = W_NONE
        self.witness_rate = 0.0
        self.targets = []
        personal = self.cars.get(self.personal_id)
        for p in self.players.values():
            p.car_id = None
        for cid in list(self.cars):
            if cid != self.personal_id:
                del self.cars[cid]
        if personal:
            personal.driver = personal.passenger = None
            personal.x, personal.y, personal.ang = self.map.bay
            personal.vx = personal.vy = personal.w = 0.0
            personal.fire_t = 0.0
        else:
            self._spawn_personal(personal_loadout())
        self.pickups.clear()
        self.traps.clear()
        self.extra_rects = []
        for k, d in enumerate(self.dollies.values()):
            d.holder, d.part, d.idle_t = None, None, 0.0
            d.x, d.y = self.map.dolly_spot[0] - k * 1.6, self.map.dolly_spot[1]
            d.ang = -math.pi / 2
        for nid in list(self.npcs):
            n = self.npcs[nid]
            if n.kind != PED or n.ttl > 0:
                del self.npcs[nid]
            else:
                n.tumble_t = n.flee_t = 0.0
        for i, p in enumerate(self.players.values()):
            p.state = FOOT
            p.hands = []
            p.stamina = C.STAMINA_MAX
            p.exhausted = False
            p.tumble_t = p.cuffed_t = p.arrest_t = 0.0
            p.vx = p.vy = 0.0
            p.x, p.y = self.map.player_spawns[i % 4]
            p.hold = 0.0
            p.hold_key = None
            p.dolly = None
            p.arms, p.ammo, p.gear, p.weapon = 1 << ARM_FISTS, [0, 0, 0], [0, 0], ARM_FISTS
        for _ in range(C.MAX_CIVILIAN_CARS):
            self._spawn_civilian()
        for _ in range(self.traffic_target):
            self._spawn_traffic()
        self.civ_respawn_t = None
        self.toast("RUN %d: NEW LEASE, SAME BAD DECISIONS. $%d IN THE TIN." % (self.run, C.START_CASH), T_INFO)

    # ------------------------------------------------------------------ input
    def _update_player_input(self, p, dt):
        inp = p.input
        use_tap = inp.use_count != p.prev_use
        drop_tap = inp.drop_count != p.prev_drop
        exit_tap = inp.exit_count != p.prev_exit
        p.prev_use, p.prev_drop, p.prev_exit = inp.use_count, inp.drop_count, inp.exit_count
        fire_tap = inp.fire_count != p.prev_fire
        p.prev_fire = inp.fire_count        # (consumed in every state: no queued-up shots after a car ride)
        p.fire_cd -= dt
        b = inp.buttons
        p.prompt = ""
        p.hold_frac = 0.0

        if p.state == CUFFED:
            p.cuffed_t -= dt
            p.prompt = "BUSTED! CUFFED FOR %d S" % (int(p.cuffed_t) + 1)
            if p.cuffed_t <= 0:
                p.state = FOOT
                p.x, p.y = self.map.player_spawns[(p.id - 1) % 4]
                p.vx = p.vy = 0.0
                self.toast("%s MADE BAIL (SOMEHOW)" % p.name, T_INFO)
            return
        if p.state == TUMBLE:
            p.hold = 0.0
            return

        if p.state in (DRIVER, PASSENGER):
            car = self.cars.get(p.car_id)
            if car is None:
                p.state, p.car_id = FOOT, None
                return
            if exit_tap or (use_tap and car.state == DELIVERED):
                self._leave_car(p, place=True)
                return
            car.horn = car.horn or bool(b & B_HORN)
            if p.state == DRIVER:
                drive_input(car, b)
                p.prompt = "F: GET OUT   SPACE: HANDBRAKE   H: HORN"
            else:
                p.prompt = "RIDING SHOTGUN. F: GET OUT   H: HORN"
            return

        # ---- on foot --------------------------------------------------------
        p.ang = inp.yaw               # you face wherever your mouse points
        p.weapon = inp.weapon if (0 <= inp.weapon <= ARM_BLOCK and p.owns(inp.weapon)) else ARM_FISTS
        if p.weapon in (ARM_PISTOL, ARM_SHOTGUN) and not p.hands and p.dolly is None:
            self._menace(p)
        if fire_tap and p.fire_cd <= 0:
            self._attack(p)
        if drop_tap and p.dolly is not None:
            self._release_dolly(p)
            self.sfx(S_DROP, p.x, p.y)
        elif drop_tap and p.hands:
            part = p.hands.pop()
            fx, fy = math.cos(p.ang), math.sin(p.ang)
            self.add_pickup(part, p.x + fx * 0.9, p.y + fy * 0.9, fx * 1.5, fy * 1.5)
            self.sfx(S_DROP, p.x, p.y)

        key, label, duration, action = self._find_interaction(p)
        p.prompt = label
        held = bool(b & B_USE)
        if not held:
            p.need_release = False
            p.hold = 0.0
            p.hold_key = key
            if use_tap and key is not None and duration <= C.TAP_HOLD:
                action()      # a tap shorter than one input packet still counts
            return
        if key is None or p.need_release:
            p.hold = 0.0
            p.hold_key = key
            return
        if key != p.hold_key:
            p.hold_key = key
            p.hold = 0.0
        p.hold += dt
        p.hold_frac = clamp(p.hold / duration, 0.0, 1.0) if duration > 0 else 1.0
        if p.hold >= duration:
            p.hold = 0.0
            p.need_release = True     # one action per press: no accidental chain-selling
            action()

    # ------------------------------------------------------------------ interactions
    def _find_interaction(self, p):
        """Returns (key, prompt, hold_seconds, action). key None = info only.
        Priority: benches > loose parts > cars. Exactly one prompt at a time."""
        m = self.map
        # first person: you use what you're looking at, measured from a point
        # just in front of your face rather than from your feet
        ax, ay = self._aim(p)
        # benches
        for bench, is_sell in ((m.sell_bench, True), (m.tune_bench, False)):
            bx, by, bw, bh = bench
            cx = clamp(ax, bx, bx + bw)
            cy = clamp(ay, by, by + bh)
            if math.hypot(ax - cx, ay - cy) < C.INTERACT_RANGE_BENCH:
                if p.dolly is not None:
                    return self._dolly_bench(p, p.dolly, is_sell)
                if not p.hands:
                    if is_sell:
                        return (None, "SELL BENCH: BRING PARTS HERE", 0, None)
                    return self._catalogue_interaction(p)
                part = p.hands[-1]
                if is_sell:
                    return (("sell", id(part)), "HOLD E: SELL %s FOR $%d" % (part.name.upper(), part.value),
                            C.SELL_TIME, lambda: self._sell(p))
                slot, replaced = self._install_target(part)
                if slot is None:
                    return (None, "YOUR RIDE ALREADY HAS A BETTER %s" % part.category.upper(), 0, None)
                verb = "SWAP IN" if replaced else "INSTALL"
                return (("install", id(part)), "HOLD E: %s %s ON YOUR RIDE" % (verb, part.name.upper()),
                        C.INSTALL_TIME, lambda: self._install(p, part, slot))
        market = self._market_interaction(p, ax, ay)
        if market is not None:
            return market
        if p.dolly is not None:
            return self._dolly_interaction(p, p.dolly)
        # someone on the floor, or with their hands up: help yourself
        mark = self._robbable_near(ax, ay)
        if mark is not None:
            if mark.wallet <= 0:
                return (None, "THEY'RE BROKE. A BUS PASS AND HALF A SANDWICH.", 0, None)
            return (("rob", mark.id), "HOLD E: ROB THEM", C.ROB_TIME, lambda: self._rob(p, mark))
        # a dolly to grab
        dl = self._nearest_dolly(ax, ay, C.INTERACT_RANGE_DOLLY)
        if dl is not None:
            if p.hands:
                return (None, "DOLLY: EMPTY YOUR HANDS FIRST (SELL OR DROP)", 0, None)
            load = " (%s ON IT)" % dl.part.name.upper() if dl.part is not None else ""
            return (("dolly", dl.id), "E: PUSH THE DOLLY" + load, 0, lambda: self._grab_dolly(p, dl))
        # pickups
        best, bd = None, C.INTERACT_RANGE_PICKUP
        for pk in self.pickups.values():
            d = math.hypot(pk.x - ax, pk.y - ay)
            if d < bd:
                best, bd = pk, d
        if best is not None:
            part = best.part
            if part.bulk == DOLLY:
                return (None, "%s: TOO HEAVY TO LIFT - FETCH THE DOLLY" % part.name.upper(), 0, None)
            if not p.can_hold(part):
                return (None, "HANDS FULL - SELL IT OR DROP (G)", 0, None)
            return (("pick", best.id), "E: PICK UP %s ($%d)" % (part.name.upper(), part.value),
                    C.PICKUP_TIME, lambda: self._pickup(p, best))
        # cars: the one whose bodywork is closest to where you're looking
        best, bd = None, 99.0
        for car in self.cars.values():
            if car.kind == COP:
                continue
            if abs(car.x - ax) > 6 or abs(car.y - ay) > 6:
                continue
            d = box_distance(car, ax, ay)
            if d < bd:
                best, bd = car, d
        car = best
        if car is None or bd > C.CAR_AIM_RANGE + (0.8 if car.state == DELIVERED else 0):
            return (None, "", 0, None)
        if car.kind == TRAFFIC:
            if car.speed() > C.CARJACK_MAX_SPEED:
                return (None, "IT'S MOVING. STOP IT FIRST: STAND IN THE ROAD, SPIKES, A ROADBLOCK...", 0, None)
            return (("carjack", car.id), "HOLD E: DRAG THE DRIVER OUT (CARJACK)", C.CARJACK_TIME,
                    lambda: self._carjack(p, car))
        if car.kind == PERSONAL:
            if car.driver is None:
                return (("drive", car.id), "E: DRIVE YOUR RIDE", 0, lambda: self._enter_car(p, car, DRIVER))
            if car.passenger is None:
                return (("shot", car.id), "E: RIDE SHOTGUN", 0, lambda: self._enter_car(p, car, PASSENGER))
            return (None, "YOUR RIDE IS FULL", 0, None)
        if car.state == LOCKED:
            return (("breakin", car.id), "HOLD E: BREAK IN (SETS OFF ALARM)", C.BREAKIN_TIME,
                    lambda: self._break_in(p, car))
        if car.state == BROKEN_IN:
            return (("hotwire", car.id), "HOLD E: HOTWIRE", C.HOTWIRE_TIME, lambda: self._hotwire(p, car))
        if car.state == RUNNING:
            if car.driver is None:
                return (("drive", car.id), "E: DRIVE", 0, lambda: self._enter_car(p, car, DRIVER))
            if car.passenger is None:
                return (("shot", car.id), "E: RIDE SHOTGUN", 0, lambda: self._enter_car(p, car, PASSENGER))
            return (None, "CAR IS FULL", 0, None)
        # delivered: strip or crush
        return self._strip_interaction(p, car)

    @staticmethod
    def _aim(p):
        return p.x + math.cos(p.ang) * C.AIM_REACH, p.y + math.sin(p.ang) * C.AIM_REACH

    def _strip_interaction(self, p, car):
        remaining = [s for s in SLOTS if car.parts.get(s) is not None]
        liftable = [s for s in remaining if car.parts[s].bulk != DOLLY]
        if not liftable:
            dolly_val = sum(car.parts[s].value for s in remaining)
            pay = C.SHELL_VALUE + int(dolly_val * C.CRUSH_DOLLY_FRACTION)
            return (("crush", car.id), "HOLD E: CRUSH SHELL (+$%d)" % pay, C.CRUSH_TIME,
                    lambda: self._crush(car, pay))
        # the slot you're looking at; the engine hides under the hood until the hood's off
        ax, ay = self._aim(p)
        c, s = math.cos(car.ang), math.sin(car.ang)
        lx = (ax - car.x) * c + (ay - car.y) * s
        ly = -(ax - car.x) * s + (ay - car.y) * c
        best, bd = None, 99.0
        for slot in remaining:
            if slot == "Engine" and car.parts.get("Hood") is not None:
                continue
            ax, ay = SLOT_ANCHOR[slot]
            d = math.hypot(ax - lx, ay - ly)
            if d < bd:
                best, bd = slot, d
        if best is None or bd > C.INTERACT_RANGE_SLOT + 1.0:
            return (None, "", 0, None)
        part = car.parts[best]
        if part.bulk == DOLLY:
            return (None, "%s: TOO HEAVY - FETCH THE DOLLY (OR CRUSH FOR 50%%)" % part.name.upper(), 0, None)
        if not p.can_hold(part):
            return (None, "HANDS FULL - SELL OR DROP (G) FIRST", 0, None)
        cat = SLOT_CATEGORY[best]
        return (("strip", car.id, best), "HOLD E: STRIP %s - %s $%d" % (SLOT_LABEL[best], part.name.upper(), part.value),
                STRIP_TIME[cat], lambda: self._strip(p, car, best))

    def _break_in(self, p, car):
        car.state = BROKEN_IN
        car.alarm = True
        car.stolen = True
        self.heat = min(C.HEAT_MAX, self.heat + C.HEAT_BREAKIN)
        self.sfx(S_BREAKIN, car.x, car.y)
        self.toast("%s SMASHED A WINDOW. ALARM! +%d HEAT" % (p.name, C.HEAT_BREAKIN), T_BAD)
        if car.special == "clown" and not car.special_fired:
            car.special_fired = True
            for i in range(C.CLOWN_COUNT):
                a = self.rng.uniform(0, 2 * math.pi)
                n = NPC(self.new_id(), CLOWN, car.x + math.cos(a), car.y + math.sin(a))
                n.vx, n.vy = math.cos(a) * 7, math.sin(a) * 7
                n.tumble_t = 0.8
                self.npcs[n.id] = n
            self.toast("OH NO. IT'S A CLOWN CAR.", T_INFO)
            self.sfx(S_HONK, car.x, car.y)
        elif car.special == "owner" and not car.special_fired:
            car.special_fired = True
            for _ in range(12):
                a = self.rng.uniform(0, 2 * math.pi)
                x = car.x + math.cos(a) * C.OWNER_SPAWN_DIST
                y = car.y + math.sin(a) * C.OWNER_SPAWN_DIST
                if not self.map.solid_at(x, y):
                    break
            n = NPC(self.new_id(), OWNER, x, y)
            n.target = car.id
            self.npcs[n.id] = n
            self.toast("OWNER: HEY!! THAT'S MY CAR!", T_BAD)

    def _hotwire(self, p, car):
        car.state = RUNNING
        self.sfx(S_HOTWIRE, car.x, car.y)
        self.toast("%s HOTWIRED IT. GO GO GO!" % p.name, T_INFO)
        self._enter_car(p, car, DRIVER)

    def _strip(self, p, car, slot):
        part = car.parts.get(slot)
        if part is None or not p.can_hold(part):
            return
        car.parts[slot] = None
        p.hands.append(part)
        self.sfx(S_STRIP, car.x, car.y)

    def _crush(self, car, pay):
        self._earn(pay)
        self.sfx(S_CRUSH, car.x, car.y)
        self.toast("CRUSHED THE SHELL: +$%d" % pay, T_MONEY)
        for pid in car.occupants():
            p = self.players.get(pid)
            if p:
                self._leave_car(p)
        del self.cars[car.id]

    def _pickup(self, p, pk):
        if pk.id in self.pickups and p.can_hold(pk.part):
            p.hands.append(pk.part)
            del self.pickups[pk.id]
            self.sfx(S_PICKUP, p.x, p.y)

    def _sell(self, p):
        if not p.hands:
            return
        part = p.hands.pop()
        self._earn(part.value, 1)
        self.sfx(S_SELL, p.x, p.y)
        self.toast("SOLD %s: +$%d" % (part.name.upper(), part.value), T_MONEY)

    def _install_target(self, part, by_dolly=False):
        """Where would this part go on the personal car? (slot, replaced?)"""
        car = self.cars.get(self.personal_id)
        if car is None or (part.bulk == DOLLY) != by_dolly:
            return None, False
        slots = CATEGORY_SLOTS.get(part.category, [])
        for s in slots:
            if car.parts.get(s) is None:
                return s, False
        worst = min(slots, key=lambda s: car.parts[s].value)
        if car.parts[worst].value < part.value:
            return worst, True
        return None, False

    def _install(self, p, part, slot):
        car = self.cars.get(self.personal_id)
        if car is None or part not in p.hands:
            return
        old = car.parts.get(slot)
        p.hands.remove(part)
        car.parts[slot] = part
        if old is not None:
            bx, by, bw, bh = self.map.tune_bench
            self.add_pickup(old, bx + bw / 2 + self.rng.uniform(-1, 1), by + bh + 1.2)
        self.sfx(S_INSTALL, p.x, p.y)
        self.toast("INSTALLED %s. YOUR RIDE: %d POWER" % (part.name.upper(), car.power()), T_INFO)


    # ------------------------------------------------------------------ the hand dolly
    def _nearest_dolly(self, x, y, reach):
        best, bd = None, reach
        for d in self.dollies.values():
            if d.holder is None:
                dist = math.hypot(d.x - x, d.y - y)
                if dist < bd:
                    best, bd = d, dist
        return best

    def _grab_dolly(self, p, d):
        if d.holder is None and not p.hands and p.dolly is None:
            d.holder = p.id
            p.dolly = d
            self.sfx(S_PICKUP, p.x, p.y)

    def _release_dolly(self, p):
        d = p.dolly
        if d is not None:
            d.holder = None
            d.idle_t = 0.0
            p.dolly = None

    def _dolly_interaction(self, p, d):
        """What you can do while pushing the dolly, away from the benches."""
        # the dolly's nose is what you line up with things
        if d.part is None:
            best, bd = None, C.INTERACT_RANGE_DOLLY
            for pk in self.pickups.values():
                if pk.part.bulk == DOLLY:
                    dist = min(math.hypot(pk.x - d.x, pk.y - d.y), math.hypot(pk.x - p.x, pk.y - p.y))
                    if dist < bd:
                        best, bd = pk, dist
            if best is not None:
                return (("dload", best.id), "HOLD E: LOAD %s ONTO THE DOLLY ($%d)" % (
                    best.part.name.upper(), best.part.value), C.DOLLY_LOAD_TIME, lambda: self._dolly_load(p, best))
            car, engine_near = self._engine_car_near(p, d)
            if car is not None:
                if car.parts.get("Hood") is not None:
                    return (None, "HOOD'S STILL ON - LET GO (G) AND STRIP IT FIRST", 0, None)
                if engine_near:
                    part = car.parts["Engine"]
                    return (("dstrip", car.id), "HOLD E: STRIP %s ONTO THE DOLLY - $%d" % (
                        part.name.upper(), part.value), STRIP_TIME["engine"], lambda: self._dolly_strip(p, car))
            return (None, "PUSHING THE DOLLY.  G: LET GO", 0, None)
        return (None, "DOLLY: %s ($%d) - TAKE IT TO SELL OR TUNE-UP.  G: LET GO" % (
            d.part.name.upper(), d.part.value), 0, None)

    def _engine_car_near(self, p, d):
        """(delivered car with an engine still in it, is its engine bay in reach?)"""
        for car in self.cars.values():
            if car.state != DELIVERED or car.parts.get("Engine") is None:
                continue
            if math.hypot(car.x - p.x, car.y - p.y) > C.INTERACT_RANGE_CAR + 2.4:
                continue
            ex, ey = car.to_world(*SLOT_ANCHOR["Engine"])
            reach = min(math.hypot(ex - p.x, ey - p.y), math.hypot(ex - d.x, ey - d.y))
            return car, reach < C.INTERACT_RANGE_SLOT + 1.2
        return None, False

    def _dolly_bench(self, p, d, is_sell):
        if d.part is None:
            return (None, "THE DOLLY'S EMPTY.  G: LET GO", 0, None)
        part = d.part
        if is_sell:
            return (("dsell", id(part)), "HOLD E: SELL %s FOR $%d" % (part.name.upper(), part.value),
                    C.SELL_TIME, lambda: self._dolly_sell(p, d))
        slot, replaced = self._install_target(part, by_dolly=True)
        if slot is None:
            return (None, "YOUR RIDE ALREADY HAS A BETTER %s" % part.category.upper(), 0, None)
        verb = "SWAP IN" if replaced else "INSTALL"
        return (("dinstall", id(part)), "HOLD E: %s %s ON YOUR RIDE" % (verb, part.name.upper()),
                C.INSTALL_TIME, lambda: self._dolly_install(p, d, slot))

    def _dolly_load(self, p, pk):
        d = p.dolly
        if d is not None and d.part is None and pk.id in self.pickups:
            d.part = pk.part
            del self.pickups[pk.id]
            self.sfx(S_PICKUP, d.x, d.y)

    def _dolly_strip(self, p, car):
        d = p.dolly
        part = car.parts.get("Engine")
        if d is not None and d.part is None and part is not None:
            car.parts["Engine"] = None
            d.part = part
            self.sfx(S_STRIP, car.x, car.y)
            self.toast("%s WINCHED OUT THE %s" % (p.name, part.name.upper()), T_INFO)

    def _dolly_sell(self, p, d):
        part = d.part
        if part is None:
            return
        d.part = None
        self._earn(part.value, 1)
        self.sfx(S_SELL, p.x, p.y)
        self.toast("SOLD %s: +$%d" % (part.name.upper(), part.value), T_MONEY)

    def _dolly_install(self, p, d, slot):
        car = self.cars.get(self.personal_id)
        part = d.part
        if car is None or part is None:
            return
        d.part = car.parts.get(slot)          # the old engine rides the dolly back out
        car.parts[slot] = part
        self.sfx(S_INSTALL, p.x, p.y)
        self.toast("INSTALLED %s. YOUR RIDE: %d POWER" % (part.name.upper(), car.power()), T_INFO)

    def _update_dollies(self, dt):
        for d in self.dollies.values():
            p = self.players.get(d.holder) if d.holder is not None else None
            if p is not None and p.dolly is d and p.state == FOOT:
                fx, fy = math.cos(p.ang), math.sin(p.ang)
                x, y = p.x + fx * C.DOLLY_OFFSET, p.y + fy * C.DOLLY_OFFSET
                if self.map.solid_at(x, y):
                    x, y = p.x + fx * 0.4, p.y + fy * 0.4     # nose against the wall, not in it
                d.x, d.y, d.ang = x, y, p.ang
                d.idle_t = 0.0
                continue
            if d.holder is not None:
                if p is not None and p.dolly is d:
                    p.dolly = None
                d.holder = None
            if self.map.in_garage(d.x, d.y):
                d.idle_t = 0.0
            else:
                d.idle_t += dt
                if d.idle_t > C.DOLLY_RETURN_TIME:
                    d.x, d.y = self.map.dolly_spot
                    d.idle_t = 0.0
                    self.toast("THE DOLLY FOUND ITS OWN WAY HOME. SPOOKY.", T_INFO)

    # ------------------------------------------------------------------ parts counter
    def _catalogue_offer(self):
        """What the parts counter suggests for your ride, as (slot, part id).
        Missing parts first, then more power (best power per dollar you can
        actually afford), then bling. If you can't afford anything in that
        group, it shows the cheapest one, so you know what to save for."""
        car = self.cars.get(self.personal_id)
        if car is None:
            return None
        missing = [(buy_price(TIERS[SLOT_CATEGORY[s]][0]), s, TIERS[SLOT_CATEGORY[s]][0])
                   for s in SLOTS if car.parts.get(s) is None]
        power = []
        for s in ("Engine", "Transmission", "ECU", "Exhaust"):
            cur = car.parts[s].type_id if car.parts.get(s) is not None else None
            nxt = _next_tier(cur) if cur else None
            if nxt is not None and part_power(nxt) > part_power(cur):
                power.append((buy_price(nxt), s, nxt, (part_power(nxt) - part_power(cur)) / buy_price(nxt)))
        bling = [(buy_price(_next_tier(car.parts[s].type_id)), s, _next_tier(car.parts[s].type_id))
                 for s in SLOTS if car.parts.get(s) is not None and _next_tier(car.parts[s].type_id) is not None
                 and s not in ("Engine", "Transmission", "ECU", "Exhaust")]
        for group, rank in ((missing, lambda o: o[0]), (power, lambda o: -o[3]), (bling, lambda o: o[0])):
            if not group:
                continue
            ok = [o for o in group if o[0] <= self.cash]
            pick = min(ok, key=rank) if ok else min(group, key=lambda o: o[0])
            return pick[1], pick[2]
        return None

    def _catalogue_interaction(self, p):
        offer = self._catalogue_offer()
        if offer is None:
            return (None, "PARTS COUNTER: YOUR RIDE IS FULLY LOADED. SHOW-OFF.", 0, None)
        slot, tid = offer
        price = buy_price(tid)
        name = PART_DEFS[tid][0].upper()
        if self.cash < price:
            return (None, "PARTS COUNTER: %s $%d - CAN'T AFFORD IT (NO CREDIT)" % (name, price), 0, None)
        return (("buy", slot, tid), "HOLD E: BUY %s FOR YOUR RIDE - $%d" % (name, price), C.INSTALL_TIME,
                lambda: self._buy(p, slot, tid, price))

    def _buy(self, p, slot, tid, price):
        car = self.cars.get(self.personal_id)
        if car is None or self.cash < price:
            return
        self.cash -= price
        old = car.parts.get(slot)
        car.parts[slot] = Part(tid, 1.0)
        if old is not None:
            bx, by, bw, bh = self.map.tune_bench
            self.add_pickup(old, bx + bw / 2 + self.rng.uniform(-1, 1), by + bh + 1.2)
        self.sfx(S_BUY, p.x, p.y)
        self.toast("BOUGHT %s: -$%d. YOUR RIDE: %d POWER" % (PART_DEFS[tid][0].upper(), price, car.power()), T_INFO)


    # ------------------------------------------------------------------ violence
    def _crime(self, heat):
        """Something loud and illegal just happened."""
        self.heat = min(C.HEAT_MAX, self.heat + heat)
        self.unseen_t = 0.0

    def _in_front(self, p, x, y, reach, cone):
        dx, dy = x - p.x, y - p.y
        d = math.hypot(dx, dy)
        if d > reach or d < 1e-6:
            return None
        if math.cos(math.atan2(dy, dx) - p.ang) < math.cos(cone):
            return None
        return d

    def _menace(self, p):
        """Point a gun at someone and their hands go up (so you can rob them)."""
        for n in self.npcs.values():
            if n.kind != CLOWN and n.tumble_t <= 0 and \
                    self._in_front(p, n.x, n.y, C.SURRENDER_RANGE, C.SURRENDER_CONE) is not None \
                    and self.map.los(p.x, p.y, n.x, n.y):
                if n.surrender_t <= 0 and n.complain_cd <= 0:
                    n.complain_cd = 5.0
                    self.toast(self.rng.choice(SURRENDER_LINES), T_WHITE)
                n.surrender_t = 0.6

    def _attack(self, p):
        if p.hands or p.dolly is not None:
            p.fire_cd = 0.3
            self.toast("HANDS FULL - DROP IT (G) TO FIGHT", T_INFO)
            return
        w = p.weapon
        if w == ARM_FISTS:
            p.fire_cd = C.PUNCH_COOLDOWN
            self._punch(p)
        elif w in (ARM_PISTOL, ARM_SHOTGUN):
            if p.ammo[w] <= 0:
                p.fire_cd = 0.3
                self.sfx(S_EMPTY, p.x, p.y)
                self.toast("*CLICK* OUT OF AMMO. THE CRATES IN THE SHOP SELL MORE.", T_INFO)
                return
            p.ammo[w] -= 1
            self._shoot(p, w)
        else:
            p.fire_cd = 0.5
            self._place_trap(p, TRAP_SPIKES if w == ARM_SPIKES else TRAP_BLOCK)

    def _punch(self, p):
        best, bd = None, None
        for n in self.npcs.values():
            d = self._in_front(p, n.x, n.y, C.PUNCH_RANGE, C.PUNCH_CONE)
            if d is not None and (bd is None or d < bd):
                best, bd = n, d
        for q in self.players.values():
            if q is not p and q.state in (FOOT, CUFFED):
                d = self._in_front(p, q.x, q.y, C.PUNCH_RANGE, C.PUNCH_CONE)
                if d is not None and (bd is None or d < bd):
                    best, bd = q, d
        if best is None:
            return                     # a mighty swing at thin air
        fx, fy = math.cos(p.ang), math.sin(p.ang)
        self.sfx(S_PUNCH, best.x, best.y)
        if isinstance(best, Player):
            if best.state == FOOT:
                self._tumble(best, fx * 5, fy * 5, C.PUNCH_PLAYER_TUMBLE)
                self.toast("%s DECKED %s. FRIENDSHIP: TESTED." % (p.name, best.name), T_WHITE)
            return
        best.tumble_t = max(best.tumble_t, C.PUNCH_KNOCKDOWN)
        best.vx, best.vy = fx * 5, fy * 5
        best.surrender_t = 0.0
        self._crime(C.PUNCH_HEAT)
        if best.complain_cd <= 0:
            best.complain_cd = 3.0
            self.toast(self.rng.choice(CLOWN_LINES if best.kind == CLOWN else PUNCH_LINES), T_WHITE)

    def _shoot(self, p, w):
        shotgun = w == ARM_SHOTGUN
        p.fire_cd = C.SHOTGUN_COOLDOWN if shotgun else C.PISTOL_COOLDOWN
        self.sfx(S_SHOTGUN if shotgun else S_PISTOL, p.x, p.y)
        rng_ = C.SHOTGUN_RANGE if shotgun else C.PISTOL_RANGE
        pellets = C.SHOTGUN_PELLETS if shotgun else 1
        for k in range(pellets):
            spread = ((k / (pellets - 1)) * 2 - 1) * C.SHOTGUN_SPREAD if pellets > 1 else 0.0
            ang = p.ang + spread + (self.rng.uniform(-0.02, 0.02) if shotgun else 0.0)
            dist, target = self._ray_hit(p, ang, rng_)
            ex, ey = p.x + math.cos(ang) * dist, p.y + math.sin(ang) * dist
            if k == 0 or k == pellets - 1 or k == pellets // 2:
                self.tracer(w, p.x, p.y, ex, ey)
            if target is not None:
                self._shot_hits(p, target, ex, ey, ang, shotgun)
        # gunshots carry: anyone within earshot notices, everyone nearby runs
        near = any((n.x - p.x) ** 2 + (n.y - p.y) ** 2 < C.GUNSHOT_EARSHOT ** 2 for n in self.npcs.values()) or \
            any(c.kind == COP and (c.x - p.x) ** 2 + (c.y - p.y) ** 2 < C.GUNSHOT_EARSHOT ** 2
                for c in self.cars.values())
        if near:
            self._crime(C.GUNSHOT_HEAT)
        self._scare(p.x, p.y, C.PED_FLEE_CRASH_RADIUS * 1.6)

    def _ray_hit(self, p, ang, reach):
        """Hitscan, Doom style: first thing along the ray -> (distance, thing or None)."""
        dx, dy = math.cos(ang), math.sin(ang)
        best_d = self.map.ray_clear(p.x, p.y, ang, reach, step=0.25)
        best = None
        for car in self.cars.values():
            if car.id == p.car_id:
                continue
            ox, oy = p.x - car.x, p.y - car.y
            if ox * ox + oy * oy > (best_d + CAR_BOUND_R) ** 2:
                continue
            c, s_ = math.cos(car.ang), math.sin(car.ang)
            lx, ly = ox * c + oy * s_, -ox * s_ + oy * c
            ldx, ldy = dx * c + dy * s_, -dx * s_ + dy * c
            t0, t1 = 0.0, best_d
            for o, dd, h in ((lx, ldx, HL), (ly, ldy, HW)):
                if abs(dd) < 1e-9:
                    if abs(o) > h:
                        t0, t1 = 1.0, 0.0
                        break
                    continue
                ta, tb = (-h - o) / dd, (h - o) / dd
                if ta > tb:
                    ta, tb = tb, ta
                t0, t1 = max(t0, ta), min(t1, tb)
            if t0 <= t1 and t0 < best_d:
                best_d, best = t0, car
        for q in list(self.npcs.values()) + [q for q in self.players.values()
                                             if q is not p and q.state in (FOOT, CUFFED)]:
            ox, oy = q.x - p.x, q.y - p.y
            t = ox * dx + oy * dy
            if 0 < t < best_d:
                perp = abs(-ox * dy + oy * dx)
                if perp < 0.45:
                    best_d, best = t, q
        return best_d, best

    def _shot_hits(self, p, target, ex, ey, ang, shotgun):
        fx, fy = math.cos(ang), math.sin(ang)
        if isinstance(target, Car):
            car = target
            # which bit did we hit? a wheel if we landed close to one
            c, s_ = math.cos(car.ang), math.sin(car.ang)
            lx, ly = (ex - car.x) * c + (ey - car.y) * s_, -(ex - car.x) * s_ + (ey - car.y) * c
            wheel = min(WHEEL_SLOTS, key=lambda w: (SLOT_ANCHOR[w][0] - lx) ** 2 + (SLOT_ANCHOR[w][1] - ly) ** 2)
            wx, wy = SLOT_ANCHOR[wheel]
            if car.parts.get(wheel) is not None and math.hypot(wx - lx, wy - ly) < C.TIRE_HIT_RADIUS:
                car.parts[wheel].condition *= 0.3            # shredded
                self._knock_off(car, wheel)
                self.sfx(S_TIRE, ex, ey)
            if shotgun:
                car.vx += fx * 0.6
                car.vy += fy * 0.6
            if car.kind == COP:
                car.hits += 1
                self._crime(C.SHOOT_COP_HEAT)
                if car.hits >= C.COP_CAR_HITS and car.fire_t <= 0:
                    car.fire_t = C.COP_BURN_TIME
                    self.sfx(S_IGNITE, car.x, car.y)
                    self.toast("THE COP CAR'S ON FIRE! GET CLEAR!", T_COP)
            elif car.kind == TRAFFIC:
                car.shaken_t = max(car.shaken_t, C.TRAFFIC_SHAKEN_TIME)
            return
        if isinstance(target, Player):
            if target.state == FOOT:
                self._drop_all(target)
                self._release_dolly(target)
                self._tumble(target, fx * 7, fy * 7, C.SHOT_PLAYER_TUMBLE)
                self.toast("%s SHOT %s. THEY'RE FINE. THEY'RE FURIOUS." % (p.name, target.name), T_BAD)
            return
        n = target
        n.tumble_t = max(n.tumble_t, C.SHOT_KNOCKDOWN)
        n.vx, n.vy = fx * 6, fy * 6
        n.surrender_t = 0.0
        self.sfx(S_YELP, n.x, n.y)
        if n.complain_cd <= 0:
            n.complain_cd = 3.0
            self.toast(self.rng.choice(SHOT_LINES), T_WHITE)

    # ------------------------------------------------------------------ robbing people
    def _robbable_near(self, x, y):
        best, bd = None, 1.7
        for n in self.npcs.values():
            if n.tumble_t > 0 or n.surrender_t > 0:
                d = math.hypot(n.x - x, n.y - y)
                if d < bd:
                    best, bd = n, d
        return best

    def _rob(self, p, n):
        if n.id not in self.npcs or n.wallet <= 0:
            return
        cash, n.wallet = n.wallet, 0
        n.wallet_t = C.WALLET_REFILL
        self._earn(cash)
        self._crime(C.ROB_HEAT)
        self.sfx(S_ROB, n.x, n.y)
        self.toast("%s LIFTED A WALLET: +$%d %s" % (p.name, cash, self.rng.choice(WALLET_EXTRAS)), T_MONEY)
        n.surrender_t = 0.0
        self._flee(n, n.x - p.x, n.y - p.y)

    # ------------------------------------------------------------------ carjacking
    def _carjack(self, p, car):
        if car.id not in self.cars or car.kind != TRAFFIC or car.speed() > C.CARJACK_MAX_SPEED:
            return
        x, y = car.to_world(0.0, -2.2)
        if self.map.solid_at(x, y):
            x, y = car.to_world(0.0, 2.2)
        n = NPC(self.new_id(), PED, x, y)
        n.ttl = 40.0
        n.tumble_t = 1.2
        n.vx, n.vy = (x - car.x) * 2, (y - car.y) * 2
        self.npcs[n.id] = n
        self._flee(n, x - car.x, y - car.y)
        car.kind, car.state, car.route = CIV, RUNNING, []
        car.stolen, car.alarm, car.special = True, False, None
        car.throttle = car.steer = 0.0
        car.handbrake = car.horn = False
        self._crime(C.CARJACK_HEAT)
        self.sfx(S_PUNCH, x, y)
        self.toast("%s DRAGGED THE DRIVER OUT. CARJACKED! +%d HEAT" % (p.name, C.CARJACK_HEAT), T_BAD)
        self._enter_car(p, car, DRIVER)

    # ------------------------------------------------------------------ black market
    def _market_interaction(self, p, ax, ay):
        best, bd = None, 1.8            # crates are 1.9 m apart: nearest wins, no mis-buys
        for (x, y, item) in self.map.market:
            d = math.hypot(x - ax, y - ay)
            if d < bd:
                best, bd = item, d
        if best is None:
            return None
        label, price = MARKET[best]
        if best == "pistol" and p.arms & (1 << ARM_PISTOL):
            return (None, "BLACK MARKET: YOU'VE GOT A PISTOL. AMMO'S TWO CRATES DOWN.", 0, None)
        if best == "shotgun" and p.arms & (1 << ARM_SHOTGUN):
            return (None, "BLACK MARKET: YOU'VE GOT A SHOTGUN. AMMO'S NEXT DOOR.", 0, None)
        if best == "ammo" and not (p.arms & ((1 << ARM_PISTOL) | (1 << ARM_SHOTGUN))):
            return (None, "BLACK MARKET: AMMO. BUY A GUN FIRST, GENIUS.", 0, None)
        if best in ("spikes", "roadblock") and p.gear[0 if best == "spikes" else 1] >= C.MAX_TRAPS_EACH:
            return (None, "BLACK MARKET: YOU CAN'T CARRY MORE OF THOSE", 0, None)
        if self.cash < price:
            return (None, "BLACK MARKET: %s $%d - CAN'T AFFORD IT" % (label, price), 0, None)
        return (("buy_" + best, p.id), "HOLD E: BUY %s - $%d" % (label, price), C.BUY_TIME,
                lambda: self._market_buy(p, best, price))

    def _market_buy(self, p, item, price):
        if self.cash < price:
            return
        self.cash -= price
        if item == "pistol":
            p.arms |= 1 << ARM_PISTOL
            p.ammo[ARM_PISTOL] = min(C.MAX_AMMO, p.ammo[ARM_PISTOL] + C.PISTOL_AMMO)
            tip = "PRESS 2 TO DRAW IT"
        elif item == "shotgun":
            p.arms |= 1 << ARM_SHOTGUN
            p.ammo[ARM_SHOTGUN] = min(C.MAX_AMMO, p.ammo[ARM_SHOTGUN] + C.SHOTGUN_AMMO)
            tip = "PRESS 3 TO DRAW IT"
        elif item == "ammo":
            if p.arms & (1 << ARM_PISTOL):
                p.ammo[ARM_PISTOL] = min(C.MAX_AMMO, p.ammo[ARM_PISTOL] + C.PISTOL_AMMO)
            if p.arms & (1 << ARM_SHOTGUN):
                p.ammo[ARM_SHOTGUN] = min(C.MAX_AMMO, p.ammo[ARM_SHOTGUN] + C.SHOTGUN_AMMO)
            tip = "LOCKED AND LOADED"
        elif item == "spikes":
            p.gear[0] += 1
            tip = "PRESS 4, CLICK TO LAY IT ACROSS THE ROAD"
        else:
            p.gear[1] += 1
            tip = "PRESS 5, CLICK TO BLOCK THE ROAD"
        self.sfx(S_BUY, p.x, p.y)
        self.toast("BOUGHT %s: -$%d. %s" % (MARKET[item][0].split(" (")[0], price, tip), T_INFO)

    # ------------------------------------------------------------------ traps
    def _place_trap(self, p, kind):
        slot = 0 if kind == TRAP_SPIKES else 1
        if p.gear[slot] <= 0:
            return
        if len(self.traps) >= C.MAX_TRAPS:
            self.toast("TOO MANY TRAPS OUT ALREADY. THE CITY HAS LIMITS.", T_INFO)
            return
        # square to the street, and centred on the road it's dropped on
        ang = round(p.ang / (math.pi / 2)) * (math.pi / 2)
        x = p.x + math.cos(p.ang) * C.TRAP_PLACE_DIST
        y = p.y + math.sin(p.ang) * C.TRAP_PLACE_DIST
        if self.map.solid_at(x, y):
            self.toast("CAN'T PUT IT THERE", T_INFO)
            return
        along_x = abs(math.cos(ang)) > 0.5
        if kind == TRAP_BLOCK:
            k = round(((y if along_x else x) / C.TILE_M - C.ROAD_TILES / 2.0) / C.PITCH)
            centre = self.map.road_centre(k)
            if along_x and abs(centre - y) < 6.5:
                y = centre
            elif not along_x and abs(centre - x) < 6.5:
                x = centre
        t = Trap(self.new_id(), kind, x, y, ang)
        self.traps[t.id] = t
        p.gear[slot] -= 1
        self._rebuild_trap_rects()
        self.sfx(S_TRAP, x, y)
        if kind == TRAP_SPIKES:
            self.toast("SPIKE STRIP DOWN. TYRES BEWARE.", T_INFO)
        else:
            self.toast("ROADBLOCK UP. NOBODY'S GETTING THROUGH HERE.", T_INFO)

    def _rebuild_trap_rects(self):
        self.extra_rects = [t.rect() for t in self.traps.values() if t.kind == TRAP_BLOCK]

    def _update_traps(self, dt):
        if not self.traps:
            return
        dead = []
        for t in self.traps.values():
            t.age += dt
            if t.age > C.TRAP_LIFETIME:
                dead.append(t.id)
                continue
            rx, ry, rw, rh = t.rect()
            if t.kind == TRAP_SPIKES:
                for car in self.cars.values():
                    if abs(car.x - t.x) > 8 or abs(car.y - t.y) > 8 or car.speed() < 1.5:
                        continue
                    for w in WHEEL_SLOTS:
                        if car.parts.get(w) is None:
                            continue
                        wx, wy = car.to_world(*SLOT_ANCHOR[w])
                        if rx - 0.2 <= wx <= rx + rw + 0.2 and ry - 0.2 <= wy <= ry + rh + 0.2:
                            car.parts[w].condition *= 0.3
                            self._knock_off(car, w)
                            self.sfx(S_TIRE, wx, wy)
                            if car.id not in t.hit:
                                t.hit.add(car.id)
                                if car.kind == COP:
                                    self.toast("SPIKED A COP CAR. BEAUTIFUL.", T_COP)
                if len(t.hit) >= t.uses and t.age < C.TRAP_LIFETIME - 1.0:
                    t.age = C.TRAP_LIFETIME - 1.0          # worn out: gone in a second
            else:
                # anything that ploughs into a roadblock hard enough turns it into kindling
                for car in self.cars.values():
                    if car.impact_dv >= C.ROADBLOCK_BREAK_DV and \
                            obb_rect_contact(car.x, car.y, car.ang, (rx - 0.3, ry - 0.3, rw + 0.6, rh + 0.6)):
                        dead.append(t.id)
                        self.sfx(S_CRASH_BIG, t.x, t.y)
                        self.toast("THE ROADBLOCK IS NOW MATCHSTICKS", T_INFO)
                        break
        if dead:
            for tid in dead:
                self.traps.pop(tid, None)
            self._rebuild_trap_rects()

    # ------------------------------------------------------------------ horns
    def _horns(self, dt):
        cops = [c for c in self.cars.values() if c.kind == COP]
        for c in cops:
            c.confuse_cd -= dt
            c.confused_t -= dt
        for car in self.cars.values():
            if not car.horn or car.driver is None:
                continue              # traffic honking at you is just rude, not a tactic
            for cop in cops:
                if cop.confuse_cd <= 0 and math.hypot(cop.x - car.x, cop.y - car.y) < C.HORN_CONFUSE_RANGE:
                    cop.confused_t = C.HORN_CONFUSE_TIME
                    cop.confuse_cd = C.HORN_CONFUSE_COOLDOWN
                    self.toast("THE COP IS VERY CONFUSED BY YOUR HORN", T_COP)

    # ------------------------------------------------------------------ cop AI
    def _cop_ai(self, cop, dt):
        cop.horn = False
        if cop.fire_t > 0:
            cop.throttle, cop.steer, cop.handbrake = 0.0, 0.0, False
            return
        if cop.confused_t > 0:
            # donuts. Professional, taxpayer-funded donuts.
            cop.throttle, cop.steer, cop.handbrake = 0.8, 1.0, True
            return
        spd = cop.speed()
        target = None
        bd = 1e9
        for t in self.targets:
            d = math.hypot(t[0] - cop.x, t[1] - cop.y)
            if d < bd:
                target, bd = t, d
        if target is None:
            if cop.last_target is None:
                cop.throttle, cop.steer, cop.handbrake = 0.0, 0.0, False
                return
            tx, ty, tvx, tvy, is_car = cop.last_target[0], cop.last_target[1], 0.0, 0.0, True
        else:
            tx, ty, tvx, tvy, is_car = target[0], target[1], target[2], target[3], target[4]
            cop.last_target = (tx, ty)
        # stuck? back up with opposite lock, like a confused shopping trolley
        if cop.rev_t > 0:
            cop.rev_t -= dt
            cop.throttle, cop.handbrake = -1.0, False
            return
        d = math.hypot(tx - cop.x, ty - cop.y)
        if d < 32 and self.map.los(cop.x, cop.y, tx, ty):
            lead = min(d / 30.0, 0.6)
            ax, ay = tx + tvx * lead, ty + tvy * lead
        else:
            T = C.TILE_M
            key = (int(tx // T), int(ty // T))
            cop.flow_t -= dt
            if cop.flow_key != key and cop.flow_t <= 0:
                cop.flow_key = key
                cop.flow_t = 0.5
            field = self.map.flow_field(*cop.flow_key)
            n = self.map.n
            cx, cy = int(cop.x // T), int(cop.y // T)
            # walk 3 tiles downhill and aim there
            for _ in range(3):
                bestv, bestc = None, None
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + ddx, cy + ddy
                    if 0 <= nx < n and 0 <= ny < n:
                        v = field[ny * n + nx]
                        if v >= 0 and (bestv is None or v < bestv):
                            bestv, bestc = v, (nx, ny)
                if bestc is None:
                    break
                cx, cy = bestc
            ax, ay = (cx + 0.5) * T, (cy + 0.5) * T
        desired = math.atan2(ay - cop.y, ax - cop.x)
        diff = wrap_angle(desired - cop.ang)
        steer = clamp(diff * 2.2, -1.0, 1.0)
        # whiskers: three rays, dumb as a bag of doughnuts but it works
        L = 5.0 + spd * 0.45
        wc = self.map.ray_clear(cop.x, cop.y, cop.ang, L)
        wl = self.map.ray_clear(cop.x, cop.y, cop.ang - 0.5, L)
        wr = self.map.ray_clear(cop.x, cop.y, cop.ang + 0.5, L)
        if wl < L * 0.6 and wr >= wl:
            steer += 0.8
        if wr < L * 0.6 and wl > wr:
            steer -= 0.8
        if wc < L * 0.5:
            steer += 0.9 if wr >= wl else -0.9
        throttle = 1.0
        if wc < 5.0 and spd > 16:
            throttle = -1.0
        if not is_car and d < 14:
            # suspect on foot: roll up for the arrest instead of pancaking them
            throttle = 0.5 if spd < 5 else -0.6
        cop.handbrake = abs(diff) > 1.7 and spd > 12
        cop.steer = clamp(steer, -1.0, 1.0)
        cop.throttle = throttle
        if throttle > 0 and spd < 1.5:
            cop.stuck_t += dt
            if cop.stuck_t > 0.8:
                cop.rev_t = 1.1
                cop.stuck_t = 0.0
                cop.steer = -cop.steer    # reversing with opposite lock swings the nose round
        else:
            cop.stuck_t = 0.0

    # ------------------------------------------------------------------ car physics
    def _physics_cars(self, dt):
        cars = list(self.cars.values())
        for car in cars:
            self._drive(car, dt)
        for car in cars:
            car.impact_dv = 0.0
            car.impact_nx = car.impact_ny = 0.0
            car.crash_cd -= dt
            self._car_vs_world(car)
        n = len(cars)
        for i in range(n):
            a = cars[i]
            for j in range(i + 1, n):
                b = cars[j]
                if abs(a.x - b.x) < 2 * CAR_BOUND_R and abs(a.y - b.y) < 2 * CAR_BOUND_R:
                    self._car_vs_car(a, b)
        for car in cars:
            if car.impact_dv >= C.CRASH_DENT_DV and car.crash_cd <= 0 and car.id in self.cars:
                car.crash_cd = C.CRASH_COOLDOWN
                self._crash(car, car.impact_dv, car.impact_nx, car.impact_ny)

    def _car_vs_car(self, a, b):
        rel = self._car_pair(a, b)
        if rel is None:
            return
        # player car T-bones a cop hard enough -> cop catches fire
        for cop, other in ((a, b), (b, a)):
            if cop.kind == COP and other.kind != COP and other.driver is not None \
                    and rel > C.COP_IGNITE_REL_SPEED and cop.fire_t <= 0:
                cop.fire_t = C.COP_BURN_TIME
                self.sfx(S_IGNITE, cop.x, cop.y)
                self.toast("COP CAR IS ON FIRE! GET CLEAR!", T_COP)

    def _crash(self, car, dv, nx, ny):
        m = math.hypot(nx, ny) or 1.0
        nx, ny = nx / m, ny / m
        self.sfx(S_CRASH_BIG if dv >= C.CRASH_EJECT_DV else S_CRASH, car.x, car.y)
        for part in car.parts.values():
            if part is not None:
                part.condition = max(0.0, part.condition - dv * 0.004)
        car.damage = min(3, car.damage + (2 if dv >= C.CRASH_EJECT_DV else 1))
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        nf = nx * fx + ny * fy
        nr = nx * -fy + ny * fx
        # the contact normal pushes the car AWAY from what it hit
        if nf < -0.5:
            side, wheels = ["BumperF", "Hood"], ["WheelFL", "WheelFR"]
        elif nf > 0.5:
            side, wheels = ["BumperR", "Exhaust"], ["WheelRL", "WheelRR"]
        elif nr > 0:
            side, wheels = ["DoorL"], ["WheelFL", "WheelRL"]
        else:
            side, wheels = ["DoorR"], ["WheelFR", "WheelRR"]
        if dv >= C.CRASH_EJECT_DV:
            self._scare(car.x, car.y, C.PED_FLEE_CRASH_RADIUS)
        if dv < C.CRASH_EJECT_DV:
            if self.rng.random() < C.CRASH_PANEL_CHANCE:
                self._knock_panels(car, side, 1)
            if car.kind == TRAFFIC:
                car.shaken_t = C.TRAFFIC_SHAKEN_TIME
        else:
            self._knock_panels(car, side, self.rng.randint(1, 3))
            if car.occupants():
                self.eject(car, dv)
            if car.kind == TRAFFIC:
                self._traffic_bail(car)
        if dv >= C.CRASH_WHEEL_DV:
            ws = [w for w in wheels if car.parts.get(w) is not None]
            self.rng.shuffle(ws)
            for w in ws[:self.rng.randint(1, 2)]:
                self._knock_off(car, w)

    def _knock_panels(self, car, preferred, count):
        for _ in range(count):
            cands = [s for s in preferred if car.parts.get(s) is not None]
            if not cands:
                cands = [s for s in PANEL_SLOTS if car.parts.get(s) is not None]
            if not cands:
                return
            self._knock_off(car, self.rng.choice(cands))

    def _knock_off(self, car, slot):
        part = car.parts.get(slot)
        if part is None:
            return
        car.parts[slot] = None
        ax, ay = SLOT_ANCHOR[slot]
        x, y = car.to_world(ax * 1.3, ay * 1.5)
        ox, oy = x - car.x, y - car.y
        m = math.hypot(ox, oy) or 1.0
        spd = self.rng.uniform(3, 7)
        self.add_pickup(part, x, y, car.vx * 0.5 + ox / m * spd, car.vy * 0.5 + oy / m * spd)

    def _sync_occupants(self):
        for p in self.players.values():
            if p.state in (DRIVER, PASSENGER):
                car = self.cars.get(p.car_id)
                if car is None:
                    p.state, p.car_id = FOOT, None
                    continue
                p.x, p.y, p.ang = car.x, car.y, car.ang
                p.vx, p.vy = car.vx, car.vy

    # ------------------------------------------------------------------ on-foot movement
    def _move_player(self, p, dt):
        if p.state in (DRIVER, PASSENGER):
            return
        b = p.input.buttons
        if p.state == TUMBLE:
            p.tumble_t -= dt
            p.spin += p.spin_rate * dt
            p.spin_rate *= math.exp(-1.5 * dt)
            dec = math.exp(-2.5 * dt)
            p.vx *= dec
            p.vy *= dec
            if p.tumble_t <= 0:
                p.state = FOOT
                p.spin = 0.0
            p.moving = False
        elif p.state == CUFFED:
            p.vx = p.vy = 0.0
            p.moving = False
        else:
            self._walk(p, b, dt)
        p.x += p.vx * dt
        p.y += p.vy * dt
        self._body_vs_world(p, C.PLAYER_RADIUS)
        # cars vs people: bounce off slow cars, go ragdoll off fast ones
        if p.state != CUFFED:
            hit = self._body_vs_cars(p, C.PLAYER_RADIUS)
            if hit is not None and p.state != TUMBLE:
                rel, cvx, cvy, nx, ny = hit
                if rel > C.BODY_HIT_SPEED:
                    self._tumble(p, cvx * 0.8 + nx * 3, cvy * 0.8 + ny * 3,
                                 lerp(1.2, 2.8, clamp(rel / 30.0, 0, 1)))
                    self.sfx(S_YELP, p.x, p.y)

    # ------------------------------------------------------------------ NPCs
    def _update_npcs(self, dt):
        dead = []
        m = self.map
        self.scare_accum += dt
        if self.scare_accum >= 1.0 / C.WITNESS_CHECK_HZ:
            self.scare_accum = 0.0
            self._scare_scan()
        for n in self.npcs.values():
            n.complain_cd -= dt
            if n.ttl > 0:
                n.ttl -= dt
                if n.ttl <= 0:
                    dead.append(n.id)     # rounded a corner and kept running. Forever.
                    continue
            if n.wallet <= 0:
                n.wallet_t -= dt
                if n.wallet_t <= 0:
                    n.wallet = self.rng.randint(C.WALLET_MIN, C.WALLET_MAX)   # payday
            if n.surrender_t > 0:
                n.surrender_t -= dt
                if n.surrender_t <= 0 and n.tumble_t <= 0:
                    # the gun's gone: run for it, away from wherever it was
                    self._flee(n, self.rng.uniform(-1, 1), self.rng.uniform(-1, 1))
            if n.kind != PED:
                n.life_t += dt
                if n.kind == CLOWN and n.life_t > C.CLOWN_LIFETIME:
                    dead.append(n.id)     # poof. Back to the tiny car in the sky.
                    continue
            if n.tumble_t > 0:
                n.tumble_t -= dt
                n.spin += dt * 12
                dec = math.exp(-2.5 * dt)
                n.vx *= dec
                n.vy *= dec
            elif n.surrender_t > 0:
                n.vx = n.vy = 0.0         # frozen, hands up, reconsidering their life choices
            elif n.kind == PED and n.flee_t > 0:
                n.flee_t -= dt
                n.vx, n.vy = self._flee_velocity(n)
                n.spin = 0.0
                if n.flee_t <= 0:
                    n.turn_t = 0.0        # pick a fresh stroll direction
            elif n.kind == PED:
                n.turn_t -= dt
                nxp = n.x + n.dirx * 1.2
                nyp = n.y + n.diry * 1.2
                t = m.tile_at(nxp, nyp)
                if t not in (SIDEWALK, GRASS) or n.turn_t <= 0:
                    opts = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                    self.rng.shuffle(opts)
                    # (look further out too: a ped who panicked into the road wants the kerb back)
                    for reach in (2.5, 6.0, 10.0):
                        hit = next(((ddx, ddy) for ddx, ddy in opts
                                    if m.tile_at(n.x + ddx * reach, n.y + ddy * reach) in (SIDEWALK, GRASS)), None)
                        if hit:
                            n.dirx, n.diry = hit
                            break
                    n.turn_t = self.rng.uniform(3, 9)
                n.vx, n.vy = n.dirx * C.PED_SPEED, n.diry * C.PED_SPEED
                n.spin = 0.0
            elif n.kind == CLOWN:
                n.turn_t -= dt
                if n.turn_t <= 0:
                    a = self.rng.uniform(0, 2 * math.pi)
                    n.vx, n.vy = math.cos(a) * C.CLOWN_SPEED, math.sin(a) * C.CLOWN_SPEED
                    n.turn_t = self.rng.uniform(0.3, 1.0)
                    if self.rng.random() < 0.15:
                        n.tumble_t = 0.6    # clowns fall over for no reason. It's the shoes.
            elif n.kind == OWNER:
                car = self.cars.get(n.target)
                if car is None or car.state == DELIVERED or n.life_t > C.OWNER_GIVE_UP:
                    self.toast("OWNER: FORGET IT. I'M GETTING A BIKE.", T_INFO)
                    dead.append(n.id)
                    continue
                dx, dy = car.x - n.x, car.y - n.y
                d = math.hypot(dx, dy) or 1.0
                if d > 3.0:
                    n.vx, n.vy = dx / d * C.OWNER_SPEED, dy / d * C.OWNER_SPEED
                else:
                    n.vx = n.vy = 0.0
                n.yell_t -= dt
                if n.yell_t <= 0:
                    n.yell_t = self.rng.uniform(6, 10)
                    self.toast(self.rng.choice(OWNER_YELLS), T_BAD)
            if abs(n.vx) + abs(n.vy) > 0.05:
                if n.tumble_t <= 0:
                    n.ang = math.atan2(n.vy, n.vx)
                n.x += n.vx * dt
                n.y += n.vy * dt
                self._body_vs_world(n, 0.35)
            hit = self._body_vs_cars(n, 0.35)
            if hit is not None and hit[0] > C.BODY_HIT_SPEED and n.tumble_t <= 0.3:
                rel, cvx, cvy, nx, ny = hit
                n.tumble_t = C.PED_TUMBLE
                n.vx, n.vy = cvx * 0.8 + nx * 3, cvy * 0.8 + ny * 3
                if n.complain_cd <= 0:
                    n.complain_cd = 4.0
                    if n.kind == CLOWN:
                        self.toast(self.rng.choice(CLOWN_LINES), T_INFO)
                        self.sfx(S_HONK, n.x, n.y)
                    elif n.kind == OWNER:
                        self.toast("OWNER: MY INSURANCE WILL HEAR ABOUT THIS", T_BAD)
                        self.sfx(S_YELP, n.x, n.y)
                    else:
                        self.toast("PEDESTRIAN: " + self.rng.choice(PED_COMPLAINTS), T_WHITE)
                        self.sfx(S_YELP, n.x, n.y)
        for nid in dead:
            self.npcs.pop(nid, None)

    # ------------------------------------------------------------------ pickups
    def _update_pickups(self, dt):
        dead = []
        m = self.map
        for pk in self.pickups.values():
            pk.age += dt
            if pk.age >= C.PICKUP_LIFETIME:
                dead.append(pk.id)
                continue
            if pk.vx or pk.vy:
                nx = pk.x + pk.vx * dt
                if m.solid_at(nx, pk.y):
                    pk.vx = -pk.vx * 0.4
                else:
                    pk.x = nx
                ny = pk.y + pk.vy * dt
                if m.solid_at(pk.x, ny):
                    pk.vy = -pk.vy * 0.4
                else:
                    pk.y = ny
                sp = math.hypot(pk.vx, pk.vy)
                ns = sp - 7.0 * dt      # parts skid to a stop fast
                if ns <= 0.05:
                    pk.vx = pk.vy = 0.0
                else:
                    pk.vx *= ns / sp
                    pk.vy *= ns / sp
        for pid in dead:
            del self.pickups[pid]

    # ------------------------------------------------------------------ fire & explosions
    def _fires(self, dt):
        for car in list(self.cars.values()):
            if car.fire_t > 0:
                car.fire_t -= dt
                if car.fire_t <= 0:
                    self._explode(car)

    def _explode(self, car):
        self.sfx(S_BOOM, car.x, car.y)
        self._scare(car.x, car.y, C.PED_FLEE_CRASH_RADIUS * 1.5)
        self.toast("KA-BOOM! COP CAR PARTS EVERYWHERE!", T_COP)
        for slot, part in car.parts.items():
            if part is None:
                continue
            a = self.rng.uniform(0, 2 * math.pi)
            s = self.rng.uniform(5, 13)
            self.add_pickup(part, car.x + math.cos(a), car.y + math.sin(a), math.cos(a) * s, math.sin(a) * s)
        del self.cars[car.id]
        self.cop_spawn_t = max(self.cop_spawn_t, C.COP_REINFORCE_DELAY)
        for other in self.cars.values():
            dx, dy = other.x - car.x, other.y - car.y
            d = math.hypot(dx, dy)
            if 0 < d < C.EXPLOSION_RADIUS:
                k = C.EXPLOSION_PUSH * (1 - d / C.EXPLOSION_RADIUS)
                other.vx += dx / d * k
                other.vy += dy / d * k
                other.w += self.rng.uniform(-3, 3)
        for p in self.players.values():
            if p.state in (FOOT, TUMBLE):
                dx, dy = p.x - car.x, p.y - car.y
                d = math.hypot(dx, dy)
                if d < C.EXPLOSION_RADIUS:
                    d = d or 0.1
                    self._tumble(p, dx / d * 12, dy / d * 12, 2.5)

    # ------------------------------------------------------------------ delivery
    def _deliveries(self):
        for car in list(self.cars.values()):
            if car.kind != CIV or not car.stolen or car.state not in (BROKEN_IN, RUNNING):
                continue
            if car.speed() >= C.DELIVER_MAX_SPEED:
                continue
            if all(self.map.in_garage(x, y) for x, y in car.corners()):
                self._deliver(car)

    def _deliver(self, car):
        car.state = DELIVERED
        self.day_stats[0] += 1
        car.alarm = False
        for pid in car.occupants():
            p = self.players.get(pid)
            if p:
                self._leave_car(p, place=True)
        self.heat = 0.0
        self.dispatched = False
        self.unseen_t = C.HEAT_COOL_DELAY
        self.witness, self.witness_rate = W_NONE, 0.0
        self.targets = [t for t in self.targets if t[5] is not car]
        self.sfx(S_DELIVER, car.x, car.y)
        self.toast("DELIVERED! HEAT CLEARED. STRIP IT FOR PARTS.", T_MONEY)
        if self.civ_respawn_t is None:
            self.civ_respawn_t = C.CIV_RESPAWN_DELAY

    # ------------------------------------------------------------------ heat & witnesses
    def _collect_targets(self):
        t = []
        for car in self.cars.values():
            if car.wanted():
                t.append((car.x, car.y, car.vx, car.vy, True, car))
        if self.heat > 0:
            for p in self.players.values():
                if p.state in (FOOT, TUMBLE) and not self.map.in_garage(p.x, p.y):
                    t.append((p.x, p.y, p.vx, p.vy, False, p))
        return t

    def _heat(self, dt):
        self.witness_accum += dt
        if self.witness_accum >= 1.0 / C.WITNESS_CHECK_HZ:
            self.witness_accum = 0.0
            self.targets = self._collect_targets()
            self.witness, self.witness_rate = self._witness_scan()
        else:
            # keep target positions fresh for the cop AI without re-raycasting
            self.targets = [(r.x, r.y, r.vx, r.vy, isc, r) for (_, _, _, _, isc, r) in self.targets
                            if (isc and r.id in self.cars and r.wanted()) or
                            (not isc and r.id in self.players and r.state in (FOOT, TUMBLE))]
        if self.witness_rate > 0:
            self.heat = min(C.HEAT_MAX, self.heat + self.witness_rate * dt)
            self.unseen_t = 0.0
        else:
            self.unseen_t += dt
            if self.unseen_t >= C.HEAT_COOL_DELAY:
                self.heat = max(0.0, self.heat - C.HEAT_COOL_RATE * dt)

    def _witness_scan(self):
        """Highest single witness rate wins -- no stacking, so a crowd isn't
        worse than one nosy neighbour (the design doc is merciful)."""
        if not self.targets:
            return W_NONE, 0.0
        los = self.map.los
        best_kind, best = W_NONE, 0.0
        cops = [c for c in self.cars.values() if c.kind == COP and c.fire_t <= 0]
        for cop in cops:
            for t in self.targets:
                dx, dy = t[0] - cop.x, t[1] - cop.y
                if dx * dx + dy * dy < C.WITNESS_RANGE_COP ** 2 and los(cop.x, cop.y, t[0], t[1]):
                    return W_COP, C.WITNESS_RATE_COP
        r2o = C.WITNESS_RANGE_OWNER ** 2
        r2p = C.WITNESS_RANGE_PED ** 2
        for n in self.npcs.values():
            if n.tumble_t > 0 or n.kind == CLOWN:
                continue
            r2 = r2o if n.kind == OWNER else r2p
            for t in self.targets:
                dx, dy = t[0] - n.x, t[1] - n.y
                if dx * dx + dy * dy < r2 and los(n.x, n.y, t[0], t[1]):
                    return (W_OWNER if n.kind == OWNER else W_PED), C.WITNESS_RATE_PED
        r2c = C.WITNESS_RANGE_CAMERA ** 2
        for (cx, cy) in self.map.cameras:
            for t in self.targets:
                if not t[4]:
                    continue          # cameras only care about stolen cars
                dx, dy = t[0] - cx, t[1] - cy
                if dx * dx + dy * dy < r2c and los(cx, cy, t[0], t[1]):
                    best_kind, best = W_CAMERA, C.WITNESS_RATE_CAMERA
        return best_kind, best

    # ------------------------------------------------------------------ cops lifecycle
    def _cops_lifecycle(self, dt):
        cops = [c for c in self.cars.values() if c.kind == COP]
        self.cop_spawn_t -= dt
        if self.heat >= C.HEAT_MAX - 1e-6:
            if not self.dispatched:
                self.toast("HEAT MAXED! DISPATCH IS SENDING UNITS", T_COP)
            self.dispatched = True
        elif self.heat <= 0:
            self.dispatched = False
        # once dispatched, units keep coming (2 s apart, max 2) until heat is 0
        if self.dispatched and len(cops) < C.MAX_COPS and self.cop_spawn_t <= 0:
            if self.spawn_cop():
                self.cop_spawn_t = C.COP_SPAWN_GAP
        if self.heat <= 0:
            self.heat_zero_t += dt
            calm = [c for c in cops if c.fire_t <= 0]
            if self.heat_zero_t >= C.COP_DESPAWN_AT_ZERO and calm:
                for c in calm:
                    del self.cars[c.id]
                self.toast("THE COPS LOST INTEREST. DONUT BREAK.", T_COP)
        else:
            self.heat_zero_t = 0.0

    def _arrests(self, dt):
        cops = [c for c in self.cars.values() if c.kind == COP and c.fire_t <= 0]
        for p in self.players.values():
            if p.state not in (FOOT, TUMBLE) or not cops or self.heat <= 0 or self.map.in_garage(p.x, p.y):
                p.arrest_t = 0.0
                continue
            near = any(math.hypot(c.x - p.x, c.y - p.y) < C.ARREST_RANGE for c in cops)
            if near:
                p.arrest_t += dt
                if p.arrest_t >= C.ARREST_TIME:
                    self.arrest(p)
            else:
                p.arrest_t = 0.0

    def arrest(self, p):
        self._drop_all(p)
        self._release_dolly(p)        # engine and all, right there for your partner
        if p.arms & ~1:
            self.toast("THE COPS KEPT %s'S GUNS" % p.name, T_COP)
        p.arms = 1 << ARM_FISTS       # guns: confiscated. Fists: they tried.
        p.ammo = [0, 0, 0]
        p.weapon = ARM_FISTS
        p.state = CUFFED
        p.cuffed_t = C.CUFFED_TIME
        p.arrest_t = 0.0
        p.vx = p.vy = 0.0
        self.sfx(S_ARREST, p.x, p.y)
        self.toast("%s GOT BUSTED! PARTS DROPPED AT THE SCENE." % p.name, T_COP)


    # ------------------------------------------------------------------ panicking pedestrians
    def _scare(self, x, y, radius):
        """Everyone within radius of (x, y) runs directly away from it."""
        r2 = radius * radius
        for n in self.npcs.values():
            if n.kind == PED and n.tumble_t <= 0:
                dx, dy = n.x - x, n.y - y
                if dx * dx + dy * dy < r2:
                    self._flee(n, dx, dy)

    def _flee(self, n, dx, dy):
        d = math.hypot(dx, dy)
        if d < 1e-3:
            a = self.rng.uniform(0, 2 * math.pi)
            dx, dy, d = math.cos(a), math.sin(a), 1.0
        n.flee_t = C.PED_FLEE_TIME
        n.fx, n.fy = dx / d, dy / d

    def _flee_velocity(self, n):
        """Run along (fx, fy), but swerve round walls rather than into them:
        panic is not the same as stupidity. Mostly."""
        solid = self.map.solid_at
        for turn in (0.0, 0.6, -0.6, 1.2, -1.2, 1.9, -1.9):
            c, s = math.cos(turn), math.sin(turn)
            fx, fy = n.fx * c - n.fy * s, n.fx * s + n.fy * c
            if not solid(n.x + fx * 1.5, n.y + fy * 1.5):
                if turn:
                    n.fx, n.fy = fx, fy
                return fx * C.PED_FLEE_SPEED, fy * C.PED_FLEE_SPEED
        n.fx, n.fy = -n.fx, -n.fy
        return 0.0, 0.0

    def _scare_scan(self):
        """10 Hz: cars bearing down fast, and (with cops rolling) anyone near the
        chase, send pedestrians running. Owners stay angry, clowns stay clowns."""
        fast = [c for c in self.cars.values() if c.vx * c.vx + c.vy * c.vy > C.PED_FLEE_CAR_SPEED ** 2]
        chase = []
        if self.dispatched and any(c.kind == COP for c in self.cars.values()):
            chase = [(t[0], t[1]) for t in self.targets]
        if not fast and not chase:
            return
        rf2 = C.PED_FLEE_RADIUS ** 2
        rc2 = C.PED_FLEE_CHASE_RADIUS ** 2
        for n in self.npcs.values():
            if n.kind != PED or n.tumble_t > 0 or n.flee_t > 1.0:
                continue
            for c in fast:
                dx, dy = n.x - c.x, n.y - c.y
                if dx * dx + dy * dy < rf2 and c.vx * dx + c.vy * dy > 0:
                    # dive sideways out of its path, not straight down the road ahead of it
                    sp = math.hypot(c.vx, c.vy)
                    side = 1.0 if (-c.vy * dx + c.vx * dy) >= 0 else -1.0
                    self._flee(n, -c.vy / sp * side + dx * 0.02, c.vx / sp * side + dy * 0.02)
                    break
            else:
                for tx, ty in chase:
                    dx, dy = n.x - tx, n.y - ty
                    if dx * dx + dy * dy < rc2:
                        self._flee(n, dx, dy)
                        break

    # ------------------------------------------------------------------ moving traffic
    def _lane_point(self, i, j, d, along):
        """A point on the right-hand lane through intersection (i, j) heading d,
        `along` metres past the intersection centre (negative = before it)."""
        cx, cy = self.map.node_pos(i, j)
        lo = C.TRAFFIC_LANE_OFFSET
        return cx + d[0] * along - d[1] * lo, cy + d[1] * along + d[0] * lo

    def _spawn_traffic(self, ignore_players=False):
        m = self.map
        for _ in range(40):
            i, j = self.rng.randrange(C.BLOCKS + 1), self.rng.randrange(C.BLOCKS + 1)
            d = self.rng.choice(DIRS)
            pi, pj = i - d[0], j - d[1]            # the intersection it's coming from
            if not m.node_ok(pi, pj):
                continue
            ax, ay = self._lane_point(pi, pj, d, 0.0)
            bx, by = self._lane_point(i, j, d, 0.0)
            t = self.rng.uniform(0.3, 0.7)          # mid-block, well clear of both junctions
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            if self.players and not ignore_players:
                near = min(math.hypot(p.x - x, p.y - y) for p in self.players.values())
                if near < C.TRAFFIC_SPAWN_MIN_DIST or near > C.TRAFFIC_RECYCLE_DIST - 25.0:
                    continue
            if any(abs(c.x - x) < 9.0 and abs(c.y - y) < 9.0 for c in self.cars.values()):
                continue
            car = Car(self.new_id(), TRAFFIC, x, y, math.atan2(d[1], d[0]), kei_loadout(self.rng),
                      color=self.rng.randrange(1, 9))
            car.pull = self.rng.choice((-1.0, 1.0))
            car.vx, car.vy = d[0] * C.TRAFFIC_SPEED * 0.8, d[1] * C.TRAFFIC_SPEED * 0.8
            car.tdir, car.node = d, (i, j)
            car.route = [self._lane_point(i, j, d, -8.0)]
            car.route_prev = self._lane_point(pi, pj, d, 8.0)
            self.cars[car.id] = car
            return car
        return None

    def _traffic_plan(self, car):
        """Append the next junction's manoeuvre to the route: maybe a turn
        (mostly straight on), the exit, and the approach to the one after."""
        i, j = car.node
        d = car.tdir
        opts = [(d2, 4 if d2 == d else 2) for d2 in DIRS
                if d2 != (-d[0], -d[1]) and self.map.node_ok(i + d2[0], j + d2[1])]
        if not opts:
            opts = [((-d[0], -d[1]), 1)]
        total = sum(wt for _, wt in opts)
        r = self.rng.random() * total
        d2 = opts[-1][0]
        for cand, wt in opts:
            r -= wt
            if r <= 0:
                d2 = cand
                break
        route = car.route
        if d2 != d:
            # where the two lanes cross: go there, then swing onto the new one
            cx, cy = self.map.node_pos(i, j)
            lo = C.TRAFFIC_LANE_OFFSET
            route.append((cx - (d[1] + d2[1]) * lo, cy + (d[0] + d2[0]) * lo))
        route.append(self._lane_point(i, j, d2, 8.0))
        ni, nj = i + d2[0], j + d2[1]
        route.append(self._lane_point(ni, nj, d2, -8.0))
        car.node, car.tdir = (ni, nj), d2

    def _pursuit_point(self, car, reach):
        """Pure pursuit: the point `reach` metres further along the lane from
        wherever the car is now. Aiming at the far waypoint instead would let
        a car that's drifted wide take a whole block to get back in lane."""
        route = car.route
        ax, ay = car.route_prev if car.route_prev is not None else (car.x, car.y)
        bx, by = route[0]
        sx, sy = bx - ax, by - ay
        seg2 = sx * sx + sy * sy
        t = clamp(((car.x - ax) * sx + (car.y - ay) * sy) / seg2, 0.0, 1.0) if seg2 > 1e-6 else 1.0
        qx, qy = ax + sx * t, ay + sy * t
        left = reach
        pts = route[:3]
        for nx, ny in pts:
            d = math.hypot(nx - qx, ny - qy)
            if d >= left:
                k = left / d
                return qx + (nx - qx) * k, qy + (ny - qy) * k
            left -= d
            qx, qy = nx, ny
        return qx, qy

    def _traffic_blocker(self, car, fx, fy):
        """Nearest thing in the lane ahead -- a car, a player or a pedestrian --
        as (thing, clearance in metres from our bumper to it), or (None, 0)."""
        look = 24.0
        passing = car.overtake_t > 0
        car_w = 1.4 if passing else 2.3       # (two 2.4 m cars side by side need 2.4 to not touch)
        best, bf = None, look
        for other in self.cars.values():
            if other is car:
                continue
            dx, dy = other.x - car.x, other.y - car.y
            f = dx * fx + dy * fy
            if 0.5 < f < bf + 2.4:
                # oncoming cars only count if they're properly in our lane
                cosd = math.cos(other.ang - car.ang)
                w = 1.5 if cosd < -0.8 else car_w
                lat = abs(-dx * fy + dy * fx)
                if lat < w:
                    if other.kind == TRAFFIC and cosd < 0.87 and other.id > car.id and lat > 1.0:
                        continue      # right of way at junctions: lower id goes first, no standoffs
                    best, bf = other, f - 2.4          # their half-length, roughly
        for p in self.players.values():
            if p.state in (FOOT, TUMBLE, CUFFED):
                dx, dy = p.x - car.x, p.y - car.y
                f = dx * fx + dy * fy
                if 0.5 < f < bf + 0.5 and abs(-dx * fy + dy * fx) < 1.8:
                    best, bf = p, f - 0.5
        for t in self.traps.values():
            if t.kind != TRAP_BLOCK:
                continue
            rx, ry, rw, rh = t.rect()
            # the nearest point of the barrier to our lane line
            qx = clamp(car.x + fx * 6, rx, rx + rw)
            qy = clamp(car.y + fy * 6, ry, ry + rh)
            dx, dy = qx - car.x, qy - car.y
            f = dx * fx + dy * fy
            if 0.5 < f < bf + 0.5 and abs(-dx * fy + dy * fx) < 2.0:
                best, bf = t, f - 0.5
        for n in self.npcs.values():
            dx, dy = n.x - car.x, n.y - car.y
            f = dx * fx + dy * fy
            if 0.5 < f < bf + 0.5 and abs(-dx * fy + dy * fx) < 1.6:
                best, bf = n, f - 0.5
        if best is None:
            return None, 0.0
        return best, bf - HL

    def _traffic_ai(self, car, dt):
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        vf = car.vx * fx + car.vy * fy
        spd = abs(vf)
        car.handbrake = False
        if car.fire_t > 0:
            car.throttle, car.steer = 0.0, 0.0
            return
        if car.missing_wheels() >= 2:
            self._traffic_bail(car)             # riding on rims: the driver's done
            return
        if car.shaken_t > 0:
            # somebody hit them. They sit there. They honk. It's what we'd all do.
            car.shaken_t -= dt
            car.throttle, car.steer = (-1.0 if vf > 0.5 else 0.0), 0.0
            car.handbrake = vf <= 0.5
            car.horn = True
            return
        if car.rev_t > 0:
            car.rev_t -= dt
            car.throttle = -1.0
            return
        route = car.route
        while route:
            wx, wy = route[0]
            dx, dy = wx - car.x, wy - car.y
            d = math.hypot(dx, dy)
            if d < 3.0 or (d < 7.0 and dx * fx + dy * fy < 0):
                car.route_prev = route.pop(0)
                continue
            break
        if len(route) < 2:
            self._traffic_plan(car)
        wx, wy = route[0]
        # slow down for a bend at the next waypoint
        target = C.TRAFFIC_SPEED
        ax, ay = wx - car.x, wy - car.y
        bx, by = route[1][0] - wx, route[1][1] - wy
        bend = abs(wrap_angle(math.atan2(by, bx) - math.atan2(ay, ax)))
        if bend > 0.5:
            target = lerp(C.TRAFFIC_TURN_SPEED, C.TRAFFIC_SPEED, clamp((math.hypot(ax, ay) - 4.0) / 18.0, 0, 1))
        wx, wy = self._pursuit_point(car, 5.0 + spd * 0.4)
        if car.overtake_t > 0:
            car.overtake_t -= dt
            wx, wy = wx + fy * 3.4, wy - fx * 3.4     # aim into the other lane
            target = min(target, 8.0)
        diff = wrap_angle(math.atan2(wy - car.y, wx - car.x) - car.ang)
        steer = clamp(diff * 2.5, -1.0, 1.0)
        blocker, gap = self._traffic_blocker(car, fx, fy)
        if blocker is not None:
            # never faster than what lets us stop 2 m short of it at a comfortable 6 m/s^2
            target = min(target, math.sqrt(2.0 * 6.0 * max(0.0, gap - 2.0)))
        if blocker is not None and target < 1.0:
            car.blocked_t += dt
            throttle = -1.0 if vf > 0.5 else 0.0
            car.handbrake = vf <= 0.5
            if car.blocked_t > C.TRAFFIC_HONK_AFTER:
                car.horn = True
            if isinstance(blocker, Trap):
                pass                    # a roadblock across the whole road: sit there and honk
            elif math.hypot(blocker.vx, blocker.vy) < 1.0 and car.blocked_t > C.TRAFFIC_OVERTAKE_AFTER:
                # a stalled car or someone loitering in the road: swing out and go round
                car.overtake_t = 3.5
                car.blocked_t = 0.0
        else:
            car.blocked_t = 0.0
            throttle = clamp((target - vf) * 0.6, -1.0, 1.0)
        car.steer = steer
        car.throttle = throttle
        # wedged against something (spun into a wall): reverse out with opposite lock
        if throttle > 0.3 and spd < 0.8:
            car.stuck_t += dt
            if car.stuck_t > 1.2:
                car.stuck_t = 0.0
                car.rev_t = 1.0
                car.steer = -steer
        else:
            car.stuck_t = 0.0

    def _traffic_bail(self, car):
        """A hard enough hit (or two shredded tyres) and the driver has had
        enough: they leg it and leave the engine running. Anyone can hop in --
        and the moment they do, it's a stolen car (+heat, like a break-in)."""
        car.kind = CIV
        car.state = RUNNING
        car.stolen = False
        car.route = []
        car.throttle = car.steer = 0.0
        car.handbrake = car.horn = False
        car.special = None
        x, y = car.to_world(0.0, -2.2)
        if self.map.solid_at(x, y):
            x, y = car.to_world(0.0, 2.2)
        n = NPC(self.new_id(), PED, x, y)
        n.ttl = 40.0
        self.npcs[n.id] = n
        self._flee(n, x - car.x, y - car.y)
        n.flee_t = C.PED_FLEE_TIME * 2
        self.toast(self.rng.choice(BAIL_LINES), T_WHITE)

    def _traffic_fleet(self, dt):
        """Keep TRAFFIC_COUNT cars on the road near the players: cars that
        drift far from everyone (or get hopelessly wedged out of sight) are
        quietly recycled to somewhere more useful."""
        traffic = [c for c in self.cars.values() if c.kind == TRAFFIC]
        if self.players:
            for car in traffic:
                near = min(math.hypot(p.x - car.x, p.y - car.y) for p in self.players.values())
                if near > C.TRAFFIC_RECYCLE_DIST or (near > 60.0 and car.blocked_t > 10.0):
                    del self.cars[car.id]
        count = sum(1 for c in self.cars.values() if c.kind == TRAFFIC)
        if count >= self.traffic_target:
            self.traffic_t = C.TRAFFIC_RESPAWN_DELAY
            return
        self.traffic_t -= dt
        if self.traffic_t <= 0:
            self.traffic_t = 0.5 if self._spawn_traffic() is None else C.TRAFFIC_RESPAWN_DELAY / 4

    # ------------------------------------------------------------------ parked civilian cars
    def _traffic(self, dt):
        civs = [c for c in self.cars.values() if c.kind == CIV and c.state != DELIVERED]
        # tow abandoned stolen cars so the city doesn't run dry
        for car in civs:
            if car.stolen and not car.occupants() and all(
                    math.hypot(p.x - car.x, p.y - car.y) > C.ABANDON_DIST for p in self.players.values()):
                car.abandon_t += dt
                if car.abandon_t > C.ABANDON_TOW_TIME:
                    del self.cars[car.id]
                    self.toast("AN ABANDONED STOLEN CAR GOT TOWED", T_INFO)
                    civs.remove(car)
                    break
            else:
                car.abandon_t = 0.0
        if len(civs) < C.MAX_CIVILIAN_CARS:
            if self.civ_respawn_t is None:
                self.civ_respawn_t = C.CIV_RESPAWN_DELAY
            self.civ_respawn_t -= dt
            if self.civ_respawn_t <= 0:
                if self._spawn_civilian():
                    self.civ_respawn_t = C.CIV_RESPAWN_DELAY if len(civs) + 1 < C.MAX_CIVILIAN_CARS else None
                else:
                    self.civ_respawn_t = 1.0
        else:
            self.civ_respawn_t = None

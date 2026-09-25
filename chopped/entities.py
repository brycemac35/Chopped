"""
entities.py -- the things that exist in the world: cars, crooks, pedestrians,
dollies, traps, loose parts, and what a player is pressing. Plain data with a
few helpers; the World (sim.py) decides what happens to them.
"""

import math

from . import config as C
from .config import clamp
from .enums import *  # noqa: F401,F403
from .parts import WHEEL_SLOTS, DOLLY, PART_DEFS, SLOT_ANCHOR, part_power
from . import vehicles as V

# parts counter: every category's parts, cheapest first
TIERS = {}
for _tid, _d in sorted(PART_DEFS.items(), key=lambda kv: kv[1][3]):
    TIERS.setdefault(_d[1], []).append(_tid)


def next_tier(type_id):
    """The next pricier part in the same category, or None at the top."""
    tier = TIERS[PART_DEFS[type_id][1]]
    i = tier.index(type_id)
    return tier[i + 1] if i + 1 < len(tier) else None


def buy_price(type_id):
    return int(round(PART_DEFS[type_id][3] * C.BUY_MARKUP))



_next_tier = next_tier


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
                 "overtake_t", "hits", "model", "hl", "hw", "bound", "delta", "trunk", "livery", "horn_type",
                 "glow", "nos", "nos_fuel", "boosting", "ejector", "gnome", "grip", "top_mult", "spin_t",
                 "donut_t", "patrol")

    def __init__(self, cid, kind, x, y, ang, parts, color=0, model=None):
        self.id = cid
        self.kind = kind
        self.color = color
        if model is None:
            model = V.COP_MODEL if kind == COP else V.KEI
        self.model = model
        m = V.model(model)
        self.hl, self.hw = m.length / 2.0, m.width / 2.0
        self.bound = math.hypot(self.hl, self.hw)   # broad-phase circle
        self.delta = 0.0              # front wheel angle, rad (v0.7 tyre physics)
        self.trunk = []               # Parts in the boot
        self.livery = 0               # vehicles.livery_byte(pattern, second colour)
        self.horn_type = V.HORN_JINGLE if model == V.ICECREAM else V.HORN_STOCK
        self.glow = 0                 # neon underglow: 0 off, else paint index + 1
        self.nos = False              # nitrous fitted?
        self.nos_fuel = 0.0           # seconds of boost left
        self.boosting = False
        self.ejector = False          # ejector seat fitted? (F at speed = see you in orbit)
        self.gnome = False            # hood ornament
        self.grip = m.grip            # recomputed from parts by refresh()
        self.top_mult = 1.0
        self.spin_t = 0.0             # > 0: skated over a banana peel, the rear has given up
        self.donut_t = 0.0            # cops only: > 0 = eating. Leave them be.
        self.patrol = False           # cops only: cruising the grid, not (yet) chasing
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
        self.mass = C.COP_MASS if kind == COP else float(m.mass)
        self.inertia = self.mass * (m.length ** 2 + m.width ** 2) / 12.0
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
        self.refresh()

    def refresh(self):
        """Re-derive grip, mass and drag from the parts. Call after parts change
        (strip, knock-off, install) -- cheap enough that we also just call it
        every tick in the physics, so nothing can forget."""
        m = V.model(self.model)
        grip, mass, top = V.performance(m, self.parts)
        self.grip = grip * m.grip
        self.top_mult = top
        if self.kind != COP:
            self.mass = mass
            self.inertia = mass * (m.length ** 2 + m.width ** 2) / 12.0

    def anchor(self, slot):
        """SLOT_ANCHOR is drawn on a Kei; stretch it to this body."""
        ax, ay = SLOT_ANCHOR[slot]
        return ax * self.hl / 2.2, ay * self.hw / 1.2

    def trunk_used(self):
        return sum(p.bulk if p.bulk != DOLLY else 3 for p in self.trunk)

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
        hl, hw = self.hl, self.hw
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
                 "prev_fire", "z", "vz")

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
        self.z = 0.0                  # feet off the ground (v0.7: you can jump now)
        self.vz = 0.0

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



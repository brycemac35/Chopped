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
                    PANEL_SLOTS, STRIP_TIME, DOLLY, Part, part_power,
                    kei_loadout, cop_loadout, personal_loadout)

# ---- enums (ints so they go straight onto the wire) -------------------------
FOOT, DRIVER, PASSENGER, TUMBLE, CUFFED = range(5)
CIV, PERSONAL, COP = range(3)
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
 S_IGNITE) = range(17)

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


class InputState:
    """What a player is pressing. Counters (not booleans) for one-shot keys so
    a tap survives a dropped packet: if the number changed, it happened."""
    __slots__ = ("buttons", "use_count", "drop_count", "exit_count")

    def __init__(self, buttons=0, use_count=0, drop_count=0, exit_count=0):
        self.buttons = buttons
        self.use_count = use_count
        self.drop_count = drop_count
        self.exit_count = exit_count


class Car:
    __slots__ = ("id", "kind", "color", "x", "y", "vx", "vy", "ang", "w", "state", "parts",
                 "alarm", "driver", "passenger", "special", "stolen", "fire_t", "horn",
                 "handbrake", "throttle", "steer", "crash_cd", "impact_dv", "impact_nx",
                 "impact_ny", "damage", "pull", "mass", "inertia", "confused_t", "confuse_cd",
                 "stuck_t", "rev_t", "abandon_t", "flow_key", "flow_t", "last_target",
                 "special_fired")

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
                 "moving", "last_seen", "addr")

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

    def hands_used(self):
        return sum(p.bulk for p in self.hands)

    def can_hold(self, part):
        return part.bulk != DOLLY and self.hands_used() + part.bulk <= 2


class NPC:
    __slots__ = ("id", "kind", "x", "y", "vx", "vy", "ang", "tumble_t", "life_t", "dirx", "diry",
                 "turn_t", "target", "yell_t", "complain_cd", "spin")

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


class World:
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
        self.events = []            # (seq, time, kind, payload)
        self.event_seq = 0
        self.cash = C.START_CASH
        self.rent_t = C.RENT_PERIOD
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
        self.personal_id = None
        self._spawn_personal(personal_loadout())
        for _ in range(C.PED_COUNT):
            self._spawn_ped()
        for _ in range(C.MAX_CIVILIAN_CARS):
            self._spawn_civilian(ignore_players=True)

    # ------------------------------------------------------------------ ids/events
    def new_id(self):
        while True:
            i = self._next_id
            self._next_id = (self._next_id % 65000) + 1
            if i not in self.cars and i not in self.npcs and i not in self.pickups:
                return i

    def toast(self, text, color=T_WHITE):
        self.event_seq += 1
        self.events.append((self.event_seq, self.time, 0, (color, text[:60])))

    def sfx(self, sid, x, y):
        self.event_seq += 1
        self.events.append((self.event_seq, self.time, 1, (sid, x, y)))

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
        self.players[pid] = p
        self.toast("%s JOINED THE CREW" % p.name, T_INFO)
        return p

    def remove_player(self, pid):
        p = self.players.get(pid)
        if not p:
            return
        self._leave_car(p, place=True)
        self._drop_all(p)
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
        for car in self.cars.values():
            if car.kind == COP:
                self._cop_ai(car, dt)
        self._horns(dt)
        self._physics_cars(dt)
        self._sync_occupants()
        for p in self.players.values():
            self._move_player(p, dt)
        self._update_npcs(dt)
        self._update_pickups(dt)
        self._fires(dt)
        self._deliveries()
        self._heat(dt)
        self._cops_lifecycle(dt)
        self._arrests(dt)
        self._traffic(dt)

    # ------------------------------------------------------------------ economy
    def _economy(self, dt):
        self.rent_t -= dt
        if self.rent_t <= 0:
            self.rent_t += C.RENT_PERIOD
            self.cash -= C.RENT_AMOUNT
            self.toast("RENT DUE: -$%d" % C.RENT_AMOUNT, T_BAD)
            self.sfx(S_RENT, *self.map.garage_center)
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
        self.rent_t = C.RENT_PERIOD
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
        for nid in list(self.npcs):
            n = self.npcs[nid]
            if n.kind != PED:
                del self.npcs[nid]
            else:
                n.tumble_t = 0.0
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
        for _ in range(C.MAX_CIVILIAN_CARS):
            self._spawn_civilian()
        self.civ_respawn_t = None
        self.toast("RUN %d: NEW LEASE, SAME BAD DECISIONS. $%d IN THE TIN." % (self.run, C.START_CASH), T_INFO)

    # ------------------------------------------------------------------ input
    def _update_player_input(self, p, dt):
        inp = p.input
        use_tap = inp.use_count != p.prev_use
        drop_tap = inp.drop_count != p.prev_drop
        exit_tap = inp.exit_count != p.prev_exit
        p.prev_use, p.prev_drop, p.prev_exit = inp.use_count, inp.drop_count, inp.exit_count
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
                car.throttle = (1.0 if b & B_UP else 0.0) - (1.0 if b & B_DOWN else 0.0)
                car.steer = (1.0 if b & B_RIGHT else 0.0) - (1.0 if b & B_LEFT else 0.0)
                car.handbrake = bool(b & B_HANDBRAKE)
                p.prompt = "F: GET OUT   SPACE: HANDBRAKE   H: HORN"
            else:
                p.prompt = "RIDING SHOTGUN. F: GET OUT   H: HORN"
            return

        # ---- on foot --------------------------------------------------------
        if drop_tap and p.hands:
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
        # benches
        for bench, is_sell in ((m.sell_bench, True), (m.tune_bench, False)):
            bx, by, bw, bh = bench
            cx = clamp(p.x, bx, bx + bw)
            cy = clamp(p.y, by, by + bh)
            if math.hypot(p.x - cx, p.y - cy) < C.INTERACT_RANGE_BENCH:
                if not p.hands:
                    return (None, "SELL BENCH: BRING PARTS HERE" if is_sell else
                            "TUNE-UP BENCH: BRING PARTS FOR YOUR RIDE", 0, None)
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
        # pickups
        best, bd = None, C.INTERACT_RANGE_PICKUP
        for pk in self.pickups.values():
            d = math.hypot(pk.x - p.x, pk.y - p.y)
            if d < bd:
                best, bd = pk, d
        if best is not None:
            part = best.part
            if not p.can_hold(part):
                return (None, "HANDS FULL - SELL IT OR DROP (G)", 0, None)
            return (("pick", best.id), "E: PICK UP %s ($%d)" % (part.name.upper(), part.value),
                    C.PICKUP_TIME, lambda: self._pickup(p, best))
        # cars
        best, bd = None, 99.0
        for car in self.cars.values():
            if car.kind == COP:
                continue
            d = math.hypot(car.x - p.x, car.y - p.y)
            if d < bd:
                best, bd = car, d
        car = best
        if car is None or bd > C.INTERACT_RANGE_CAR + (1.2 if car.state == DELIVERED else 0):
            return (None, "", 0, None)
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

    def _strip_interaction(self, p, car):
        remaining = [s for s in SLOTS if car.parts.get(s) is not None]
        liftable = [s for s in remaining if car.parts[s].bulk != DOLLY]
        if not liftable:
            dolly_val = sum(car.parts[s].value for s in remaining)
            pay = C.SHELL_VALUE + int(dolly_val * C.CRUSH_DOLLY_FRACTION)
            return (("crush", car.id), "HOLD E: CRUSH SHELL (+$%d)" % pay, C.CRUSH_TIME,
                    lambda: self._crush(car, pay))
        # nearest slot; the engine hides under the hood until the hood's off
        c, s = math.cos(car.ang), math.sin(car.ang)
        lx = (p.x - car.x) * c + (p.y - car.y) * s
        ly = -(p.x - car.x) * s + (p.y - car.y) * c
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
            return (None, "%s: DOLLY-ONLY, CAN'T LIFT IT (CRUSH PAYS 50%%)" % part.name.upper(), 0, None)
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
        self.cash += pay
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
        self.cash += part.value
        self.sfx(S_SELL, p.x, p.y)
        self.toast("SOLD %s: +$%d" % (part.name.upper(), part.value), T_MONEY)

    def _install_target(self, part):
        """Where would this part go on the personal car? (slot, replaced?)"""
        car = self.cars.get(self.personal_id)
        if car is None or part.bulk == DOLLY:
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

    # ------------------------------------------------------------------ horns
    def _horns(self, dt):
        cops = [c for c in self.cars.values() if c.kind == COP]
        for c in cops:
            c.confuse_cd -= dt
            c.confused_t -= dt
        for car in self.cars.values():
            if not car.horn or car.kind == COP:
                continue
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
                if abs(a.x - b.x) < 4.6 and abs(a.y - b.y) < 4.6:
                    self._car_vs_car(a, b)
        for car in cars:
            if car.impact_dv >= C.CRASH_DENT_DV and car.crash_cd <= 0 and car.id in self.cars:
                car.crash_cd = C.CRASH_COOLDOWN
                self._crash(car, car.impact_dv, car.impact_nx, car.impact_ny)

    def _drive(self, car, dt):
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        rx, ry = -fy, fx
        vf = car.vx * fx + car.vy * fy
        vr = car.vx * rx + car.vy * ry
        driven = car.driver is not None or car.kind == COP
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
        R = C.CAR_CIRCLE_R
        for off in (C.CAR_CIRCLE_OFF, -C.CAR_CIRCLE_OFF):
            c, s = math.cos(car.ang), math.sin(car.ang)
            cx, cy = car.x + c * off, car.y + s * off
            rects.clear()
            self.map.solid_rects_near(cx, cy, R, rects)
            for rect in rects:
                cx, cy = car.x + c * off, car.y + s * off
                hit = circle_rect_contact(cx, cy, R, rect)
                if hit:
                    nx, ny, pen, px, py = hit
                    self._apply_static_contact(car, px, py, nx, ny, pen, C.RESTITUTION_WALL)

    def _car_vs_car(self, a, b):
        R = C.CAR_CIRCLE_R
        ca, sa = math.cos(a.ang), math.sin(a.ang)
        cb, sb = math.cos(b.ang), math.sin(b.ang)
        best = None
        for oa in (C.CAR_CIRCLE_OFF, -C.CAR_CIRCLE_OFF):
            ax, ay = a.x + ca * oa, a.y + sa * oa
            for ob in (C.CAR_CIRCLE_OFF, -C.CAR_CIRCLE_OFF):
                bx, by = b.x + cb * ob, b.y + sb * ob
                dx, dy = ax - bx, ay - by
                d2 = dx * dx + dy * dy
                if d2 < 4 * R * R and (best is None or d2 < best[0]):
                    best = (d2, ax, ay, bx, by)
        if best is None:
            return
        d2, ax, ay, bx, by = best
        d = math.sqrt(d2) or 1e-4
        nx, ny = (ax - bx) / d, (ay - by) / d      # points from b to a
        pen = 2 * R - d
        ima, imb = 1.0 / a.mass, 1.0 / b.mass
        a.x += nx * pen * ima / (ima + imb)
        a.y += ny * pen * ima / (ima + imb)
        b.x -= nx * pen * imb / (ima + imb)
        b.y -= ny * pen * imb / (ima + imb)
        px, py = (ax + bx) / 2, (ay + by) / 2
        rax, ray = px - a.x, py - a.y
        rbx, rby = px - b.x, py - b.y
        vax = a.vx - a.w * ray
        vay = a.vy + a.w * rax
        vbx = b.vx - b.w * rby
        vby = b.vy + b.w * rbx
        vn = (vax - vbx) * nx + (vay - vby) * ny
        if vn >= 0:
            return
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
        if dv < C.CRASH_EJECT_DV:
            if self.rng.random() < C.CRASH_PANEL_CHANCE:
                self._knock_panels(car, side, 1)
        else:
            self._knock_panels(car, side, self.rng.randint(1, 3))
            if car.occupants():
                self.eject(car, dv)
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
            dx = (1 if b & B_RIGHT else 0) - (1 if b & B_LEFT else 0)
            dy = (1 if b & B_DOWN else 0) - (1 if b & B_UP else 0)
            moving = dx != 0 or dy != 0
            used = p.hands_used()
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
            spd = C.SPRINT_SPEED if want_sprint else C.WALK_SPEED
            if used >= 2:
                spd *= C.TWO_HAND_SPEED_MULT
            if p.exhausted:
                spd *= C.EXHAUSTED_SPEED_MULT
            if moving:
                inv = 1.0 / math.hypot(dx, dy)
                tx, ty = dx * inv * spd, dy * inv * spd
                p.ang = math.atan2(dy, dx)
            else:
                tx = ty = 0.0
            k = min(1.0, 16.0 * dt)
            p.vx += (tx - p.vx) * k
            p.vy += (ty - p.vy) * k
            p.sprinting = want_sprint
            p.moving = moving
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

    def _body_vs_world(self, b, r):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(b.x, b.y, r, rects)
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
        R = C.CAR_CIRCLE_R + r
        result = None
        for car in self.cars.values():
            if abs(car.x - b.x) > 3.5 or abs(car.y - b.y) > 3.5:
                continue
            c, s = math.cos(car.ang), math.sin(car.ang)
            for off in (C.CAR_CIRCLE_OFF, -C.CAR_CIRCLE_OFF):
                cx, cy = car.x + c * off, car.y + s * off
                dx, dy = b.x - cx, b.y - cy
                d2 = dx * dx + dy * dy
                if d2 < R * R:
                    d = math.sqrt(d2) or 1e-4
                    nx, ny = dx / d, dy / d
                    b.x += nx * (R - d)
                    b.y += ny * (R - d)
                    rel = math.hypot(car.vx - b.vx, car.vy - b.vy)
                    vn = (b.vx - car.vx) * nx + (b.vy - car.vy) * ny
                    if vn < 0:
                        b.vx -= vn * nx
                        b.vy -= vn * ny
                    if result is None or rel > result[0]:
                        result = (rel, car.vx, car.vy, nx, ny)
        return result

    # ------------------------------------------------------------------ NPCs
    def _update_npcs(self, dt):
        dead = []
        m = self.map
        for n in self.npcs.values():
            n.complain_cd -= dt
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
            elif n.kind == PED:
                n.turn_t -= dt
                nxp = n.x + n.dirx * 1.2
                nyp = n.y + n.diry * 1.2
                t = m.tile_at(nxp, nyp)
                if t not in (SIDEWALK, GRASS) or n.turn_t <= 0:
                    opts = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                    self.rng.shuffle(opts)
                    for ddx, ddy in opts:
                        if m.tile_at(n.x + ddx * 2.5, n.y + ddy * 2.5) in (SIDEWALK, GRASS):
                            n.dirx, n.diry = ddx, ddy
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
        p.state = CUFFED
        p.cuffed_t = C.CUFFED_TIME
        p.arrest_t = 0.0
        p.vx = p.vy = 0.0
        self.sfx(S_ARREST, p.x, p.y)
        self.toast("%s GOT BUSTED! PARTS DROPPED AT THE SCENE." % p.name, T_COP)

    # ------------------------------------------------------------------ traffic
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

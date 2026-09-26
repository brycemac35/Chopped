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
from .parts import (SLOTS, SLOT_CATEGORY, WHEEL_SLOTS, PANEL_SLOTS, STRIP_TIME, DOLLY, Part,
                    kei_loadout, cop_loadout, personal_loadout, model_loadout, roll_trunk)
from . import vehicles as V
from .brawl import Brawl
from .garage import Garage, Appraisal, ShopDoor
from .sillies import Sillies
from .police import Police
from .quests import Quests
from .story import Story
from .enums import *  # noqa: F401,F403
from .lines import *  # noqa: F401,F403
from .entities import *  # noqa: F401,F403
from .physics import *  # noqa: F401,F403

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_REEXPORTS = (kei_loadout,)   # tests (and old habits) reach for S.kei_loadout


class World(Physics, Brawl, Garage, Appraisal, ShopDoor, Police, Sillies, Quests, Story):
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
        self.stash = []             # the parts locker in the shop (mod shop feeds from it)
        self.extra_rects = []       # roadblocks, as solid rects (rebuilt when traps change)
        self.tall_rects = []        # (v0.9) the ones you can't jump: shut doors and gates
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
        self.patrol_target = C.PATROL_COPS       # (and this: patrol cars that are always about)
        self.patrol_t = 2.0
        self.wanted_level = 0
        self.scare_accum = 0.0
        # (v0.12) shop 1 (home base) is free and always yours; shops 2-4 are fences you buy
        # with crew cash -- see config.SHOP_PRICE/SHOP_RENT and World._buy_shop.
        self.shop_owned = [True] + [False] * (len(C.SHOP_PRICE) - 1)
        self.personal_id = None
        self.player_car = {}        # (v0.10) player id -> their own personal car's id
        self.bay_owner_name = {}    # (save files) bay index -> the name that claimed it, forever
        self._pending_car_mods = {}     # (save files) name -> saved car, claimed on that name's next join
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
        self.gnome_t = 0.0
        for _ in range(C.GNOME_COUNT):
            self._spawn_gnome()
        self._init_door()
        self._init_police()
        self._init_sillies()
        self._init_story()           # (v0.13; before the quests: their first rotation pokes it)
        self._init_quests()

    # ------------------------------------------------------------------ ids/events
    def new_id(self):
        while True:
            i = self._next_id
            self._next_id = (self._next_id % 65000) + 1
            if (i not in self.cars and i not in self.npcs and i not in self.pickups and i not in self.dollies
                    and i not in self.traps and i != C.GATE_ID):
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
    def _spawn_personal(self, parts, bay=0):
        """(v0.10, Bryce: "a bay for each player that joins") one of the shop's N_BAYS bays,
        with nobody's name on it until a player claims it in add_player()."""
        bx, by, ba = self.map.bays[bay]
        car = Car(self.new_id(), PERSONAL, bx, by, ba, parts, color=bay % 4)
        car.bay = bay
        self.cars[car.id] = car
        if bay == 0:
            self.personal_id = car.id     # kept for the many single-player tests that use it
        return car

    def _my_car(self, p):
        """(v0.10) Whichever bay this player claimed when they joined -- their own ride for
        the mod shop, "E: drive your ride", and keeping its mods across a reset."""
        return self.cars.get(self.player_car.get(p.id, self.personal_id))

    def _spawn_civilian(self, ignore_players=False):
        spots = list(self.map.parking)
        self.rng.shuffle(spots)
        for (x, y, a) in spots:
            if not ignore_players and any(math.hypot(p.x - x, p.y - y) < C.CIV_SPAWN_MIN_DIST
                                          for p in self.players.values()):
                continue
            if any(math.hypot(c.x - x, c.y - y) < 6.0 for c in self.cars.values()):
                continue
            mid = V.pick_model(self.rng)
            car = Car(self.new_id(), CIV, x, y, a, model_loadout(self.rng, mid),
                      color=self.rng.randrange(1, len(V.PAINT_NAMES)), model=mid)
            self._dress(car)
            car.trunk = roll_trunk(self.rng, V.model(mid).sporty)
            r = self.rng.random()
            if r < C.CLOWN_CHANCE:
                car.special = "clown"
            elif r < C.CLOWN_CHANCE + C.OWNER_CHANCE:
                car.special = "owner"
            car.pull = self.rng.choice((-1.0, 1.0))
            self.cars[car.id] = car
            return car
        return None

    def _dress(self, car):
        """A paint job to go with the parts: most cars are one boring colour,
        some have stripes, a few have flames, one in fifty has polka dots."""
        r = self.rng
        if car.model == V.ICECREAM:
            car.color, car.livery = 4, V.livery_byte(V.LIV_PASTEL, 10)
            return
        roll = r.random()
        if roll < C.LIVERY_CHANCE:
            pattern = r.choice((V.LIV_STRIPES, V.LIV_STRIPES, V.LIV_TWOTONE, V.LIV_TWOTONE, V.LIV_FLAMES,
                                V.LIV_CHECKER, V.LIV_DOTS, V.LIV_CAMO, V.LIV_BOLT))
            car.livery = V.livery_byte(pattern, r.randrange(1, len(V.PAINT_NAMES)))
        if car.kind == CIV and r.random() < C.CIV_GLOW_CHANCE:
            car.glow = r.randrange(1, 9)
        car.refresh()

    def _spawn_gnome(self):
        """Garden gnomes, standing guard on the grass. Steal them. Sell them
        ($60), throw them (they squeak), or bolt one to your bonnet."""
        tiles = self.map.grass_tiles or self.map.sidewalk_tiles
        for _ in range(20):
            tx, ty = self.rng.choice(tiles)
            x, y = (tx + 0.5) * C.TILE_M, (ty + 0.5) * C.TILE_M
            if any(p.x - 30 < x < p.x + 30 and p.y - 30 < y < p.y + 30 for p in self.players.values()):
                continue
            pk = self.add_pickup(Part("gnome", self.rng.uniform(0.7, 1.0)), x, y)
            pk.fixed = True
            return pk
        return None

    def _roll_wallet(self):
        """(v0.12) one pedestrian in JACKPOT_CHANCE is quietly loaded. No way to tell which
        one from the outside -- you find out the way you find out anything in this game."""
        if self.rng.random() < C.JACKPOT_CHANCE:
            return self.rng.randint(*C.JACKPOT_WALLET)
        return self.rng.randint(C.WALLET_MIN, C.WALLET_MAX)

    def _spawn_ped(self):
        tx, ty = self.rng.choice(self.map.sidewalk_tiles)
        n = NPC(self.new_id(), PED, (tx + 0.5) * C.TILE_M, (ty + 0.5) * C.TILE_M)
        n.wallet = self._roll_wallet()
        n.dirx, n.diry = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        self._roll_bravery(n)
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
        self._radio_tip(car)                    # (v0.12.1) it's been told where to go
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
            for slot in GUN_SLOTS:
                p.arms |= 1 << slot
                p.ammo[slot] = C.MAX_AMMO
            p.gear = [C.MAX_TRAPS_EACH] * len(GEAR_OF_ARM)   # (v0.12.1: was * 4 -- one short since the whoopee cushion)
        self.players[pid] = p
        # (v0.10, Bryce: "a bay for each player that joins") the first player to ever join
        # inherits the car that was already sitting in bay 0 at world creation; everyone
        # after that gets a fresh one in the next free bay, up to N_BAYS.
        if pid not in self.player_car:
            car = None
            if not self.player_car and self.personal_id in self.cars:
                car = self.cars[self.personal_id]
                car.owner = pid
                self.player_car[pid] = car.id
            elif len(self.player_car) < C.N_BAYS:
                car = self._spawn_personal(personal_loadout(), bay=len(self.player_car))
                car.owner = pid
                self.player_car[pid] = car.id
            if car is not None:
                # (save files) a name that owned a bay in a previous session gets its saved
                # car back instead of a fresh Kei; either way, this bay is that name's for
                # good now, so a later save knows whose car it's looking at.
                self._claim_saved_car(p.name, car)
                self.bay_owner_name[car.bay] = p.name
        self.toast("%s JOINED THE CREW" % p.name, T_INFO)
        return p

    def _claim_saved_car(self, name, car):
        """(save files) swap the stock car `car` for one built from `name`'s saved mods,
        if any are waiting. A new Car is built rather than patching fields onto the stock
        one because the saved model can differ (you might have saved with a stolen sports
        coupe as your daily driver, not the Kei you started with) -- and a model's box
        size, mass and drag are all derived once in Car.__init__, not safe to change after."""
        mods = self._pending_car_mods.pop(name, None)
        if mods is None:
            return
        bx, by, ba = self.map.bays[car.bay]
        parts = {slot: Part(*p) if (p := mods["parts"].get(slot)) else None for slot in SLOTS}
        new = Car(self.new_id(), PERSONAL, bx, by, ba, parts, color=mods.get("color", car.color),
                  model=mods.get("model", car.model))
        new.bay, new.owner = car.bay, car.owner
        new.livery = mods.get("livery", 0)
        new.horn_type = mods.get("horn_type", new.horn_type)
        new.glow = mods.get("glow", 0)
        new.nos = mods.get("nos", False)
        new.ejector = mods.get("ejector", False)
        new.gnome = mods.get("gnome", False)
        new.hydraulics = mods.get("hydraulics", False)
        del self.cars[car.id]
        self.cars[new.id] = new
        self.player_car[new.owner] = new.id
        if new.bay == 0:
            self.personal_id = new.id

    def remove_player(self, pid):
        p = self.players.get(pid)
        if not p:
            return
        self._leave_car(p, place=True)
        self._drop_carry(p, throw=False)
        if p.state == CARRIED:
            self._free_carried_player(p)
        for q in self.players.values():
            if q.carrying == ("player", pid):
                q.carrying = None
        self._drop_all(p)
        self._release_dolly(p)
        del self.players[pid]
        self.toast("%s LEFT" % p.name, T_INFO)

    def set_input(self, pid, inp):
        p = self.players.get(pid)
        if p:
            p.input = inp

    def _icecream_lure(self, n):
        """An ice cream van playing its tune, slow or parked: peds within earshot
        wander over and queue. People in a queue are not looking at crimes."""
        best, bd = None, C.ICECREAM_LURE
        for car in self.cars.values():
            if car.model == V.ICECREAM and (car.driver is not None or car.kind == TRAFFIC) and car.speed() < 6.0:
                d = math.hypot(car.x - n.x, car.y - n.y)
                if d < bd:
                    best, bd = car, d
        n.lure = (best.x, best.y) if best is not None else None

    def _drop_all(self, p):
        for i, part in enumerate(p.hands):
            a = self.rng.uniform(0, 2 * math.pi)
            self.add_pickup(part, p.x + math.cos(a) * 0.6, p.y + math.sin(a) * 0.6,
                            math.cos(a) * 2.5, math.sin(a) * 2.5)
        p.hands = []

    def _enter_car(self, p, car, seat):
        self._release_dolly(p)        # it'd never fit in a Kei anyway
        self._drop_carry(p, throw=False)   # (they would, but that's a different game)
        p.z = p.vz = 0.0
        if seat == DRIVER and car.kind == CIV and not car.stolen and car.state == RUNNING:
            # a car whose driver bailed, engine still running: finders keepers, says nobody
            car.stolen = True
            self._crime(C.HEAT_BREAKIN)
            self.toast("%s TOOK A CAR IN BROAD DAYLIGHT. +%d HEAT" % (p.name, C.HEAT_BREAKIN), T_BAD)
            self._quest_on_steal(p, car)
        if seat == DRIVER:
            car.driver = p.id
        else:
            car.passenger = p.id
        p.state = seat
        p.car_id = car.id
        p.vx = p.vy = 0.0
        p.seat_t = 0.0

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
        side, end = car.hw + 0.9, car.hl + 0.8
        for lx, ly in ((0, -side), (0, side), (-end, 0), (end, 0), (0, -side - 1.4), (0, side + 1.4)):
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
            if box_distance(c, x, y) < r + 0.1:
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

    def _eject_seat(self, p, car):
        """F at speed, ejector seat fitted: straight up through the roof,
        parachute out, gently down. The car carries on without you."""
        self._leave_car(p, place=False)
        p.x, p.y = car.x, car.y
        self._tumble(p, car.vx * 0.35, car.vy * 0.35, 0.5)
        p.z, p.vz = 1.6, C.EJECT_SPEED
        p.chute = True
        self._banner(p, BN_EJECT)
        self.sfx(S_EJECT, car.x, car.y)
        self.toast("%s PULLED THE EJECTOR SEAT. WHY WAS THERE AN EJECTOR SEAT." % p.name, T_INFO)

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
        self._update_door(dt)
        self._sync_occupants()
        for p in self.players.values():
            self._move_player(p, dt)
        self._inspect_scan()
        self._update_carries(dt)
        self._update_dollies(dt)
        self._update_npcs(dt)
        self._update_pickups(dt)
        self._fires(dt)
        self._deliveries()
        self._heat(dt)
        self._cops_lifecycle(dt)
        self._police(dt)
        self._sillies(dt)
        self._traffic(dt)
        self._traffic_fleet(dt)
        self._patrol_fleet(dt)
        self._quest_tick(dt)
        self._story_tick(dt)

    # ------------------------------------------------------------------ economy
    def rent_due(self):
        """(v0.12) flat per shop you own, not per day -- see config.SHOP_RENT."""
        return sum(r for r, owned in zip(C.SHOP_RENT, self.shop_owned) if owned)

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
            self.cops_today = 0         # (v0.10) dispatch gets a fresh COPS_PER_DAY budget
            self.cops_exhausted_told = False
            self.toast("DAY %d. RENT AT MIDNIGHT: $%d" % (self.day, self.rent_due()), T_INFO)
            self._rotate_quests()
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
        # (v0.12) the landlord repossesses the fences too -- only the free home base survives
        # SHOP SEIZED, same "the new run resets everything except your personal car" rule as
        # the locker and the city's civilian cars.
        self.shop_owned = [True] + [False] * (len(C.SHOP_PRICE) - 1)
        # (v0.10) every player's own personal car keeps its mods, back in its own bay --
        # not just bay 0's any more. A car nobody's claimed (kind == PERSONAL but no owner
        # yet, or the shared bay-0 one at first launch) survives the reset too.
        for p in self.players.values():
            p.car_id = None
        for cid in list(self.cars):
            if self.cars[cid].kind != PERSONAL:
                del self.cars[cid]
        for car in self.cars.values():
            car.driver = car.passenger = None
            car.x, car.y, car.ang = self.map.bays[car.bay]
            car.vx = car.vy = car.w = 0.0
            car.fire_t = 0.0
        if self.personal_id not in self.cars:
            self._spawn_personal(personal_loadout())
        self.pickups.clear()
        self.traps.clear()
        self._init_door()                 # (the door goes back up: the landlord's got the remote now)
        self._init_police()               # (a fresh gate, and the police calm down)
        self._rotate_quests()             # a fresh day's jobs; story points and rep survive the seizure
        if self.stash:
            self.toast("THE LANDLORD SOLD YOUR PARTS LOCKER ON MARKETPLACE.", T_BAD)
        self.stash = []
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
            # (v0.12.1: gear was [0, 0, 0, 0] -- one slot short since v0.9's whoopee cushion, so
            # after a SHOP SEIZED picking the cushion crashed the host with an IndexError)
            p.arms, p.ammo, p.gear, p.weapon = 1 << ARM_FISTS, [0] * ARM_COUNT, [0] * len(GEAR_OF_ARM), ARM_FISTS
            p.jailed = p.keys = p.jumpsuit = False
            p.head_start_t = 0.0
            p.pants_t = p.tased_t = p.dead_t = p.cuff_prog = 0.0
            p.arrests = 0
            p.rap.clear()
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
        p.dancing = False
        if p.banner_t > 0:
            p.banner_t -= dt
            if p.banner_t <= 0:
                p.banner = BN_NONE
        jump_tap = bool(b & B_JUMP) and not p.prev_jump
        p.prev_jump = bool(b & B_JUMP)
        alt_tap = bool(b & B_HOP) and not p.prev_alt      # (v0.9) X on foot: the prompt's second option
        p.prev_alt = bool(b & B_HOP)
        box_tap = bool(b & B_BOX) and not p.prev_box
        p.prev_box = bool(b & B_BOX)
        if p.boxed and p.state != FOOT:
            p.boxed = False                                # (knocked out of it, cuffed, in a car...)
        if box_tap and p.state == FOOT:
            self._toggle_box(p)
        if p.state == FOOT and not p.moving and math.hypot(p.vx, p.vy) < 0.3:
            p.still_t += dt
        else:
            p.still_t = 0.0

        if p.state == CARRIED:
            p.prompt = "YOU'RE BEING CARRIED. MASH SPACE TO WRIGGLE FREE (%d/%d)" % (p.wriggle, C.WRIGGLE_PRESSES)
            if jump_tap:
                self._wriggle(p)
            return

        if p.state == CUFFED:
            p.cuffed_t -= dt
            p.prompt = "BUSTED! OFF TO THE PRECINCT IN %d..." % (int(p.cuffed_t) + 1)
            if p.cuffed_t <= 0:
                self._jail(p)
            return
        if p.state == DEAD:
            return
        if p.cuff_prog > 0 and jump_tap and p.state in (FOOT, TUMBLE):
            self._cuff_wriggle(p)             # an officer's got you: wriggle!
        if p.state == TUMBLE:
            p.hold = 0.0
            return

        if p.state in (DRIVER, PASSENGER):
            car = self.cars.get(p.car_id)
            if car is None:
                p.state, p.car_id = FOOT, None
                return
            if exit_tap and p.state == DRIVER and car.ejector and car.speed() >= C.EJECT_MIN_SPEED:
                self._eject_seat(p, car)
                return
            if exit_tap or (use_tap and car.state == DELIVERED):
                self._leave_car(p, place=True)
                return
            car.horn = car.horn or bool(b & B_HORN)
            if b & B_HORN and not p.prev_horn and p.state == DRIVER:
                self._door_remote(p, car)      # (v0.9) honk at the shop: the door opens (or shuts)
                self._honk_icecream(car)       # (v0.12) or at the world's most persistent ice cream van
            p.prev_horn = bool(b & B_HORN)
            p.seat_t += dt
            if p.state == DRIVER:
                drive_input(car, b)
                hop = bool(b & B_HOP)
                if hop and not p.prev_hop:
                    self._hop(p, car)
                p.prev_hop = hop
                if car.boosting and not p.prev_nos:
                    # (v0.12) one confetti puff the instant NOS kicks in -- reuses the exact
                    # same event delivery already fires with, so no new wire/client code
                    self.sfx(S_CONFETTI, car.x, car.y)
                p.prev_nos = car.boosting
                if p.seat_t < C.CAR_PROMPT_TIME:
                    p.prompt = "F: OUT  SPACE: HANDBRAKE  W+S: BURNOUT  H: HORN  V: CAMERA" + (
                        "  SHIFT: NOS" if car.nos else "") + ("  X: HOP" if car.hydraulics else "")
            elif p.seat_t < C.CAR_PROMPT_TIME:
                p.prompt = "RIDING SHOTGUN. F: GET OUT   H: HORN   V: CAMERA"
            return

        # ---- on foot --------------------------------------------------------
        p.trunk_view = None
        if p.menu:
            if p.state != FOOT or not self.map.in_garage(p.x, p.y):
                p.menu = False
            else:
                self._modshop_input(p, inp)
                p.prompt = "MOD SHOP"
                return
        p.ang = inp.yaw               # you face wherever your mouse points
        # (v0.9: this said <= ARM_BLOCK, a leftover from v0.6 -- so keys 6 and 7, the banana and the
        # donuts, quietly gave you your fists. Everything up to key 9 now.)
        p.weapon = inp.weapon if (0 <= inp.weapon < ARM_COUNT and p.owns(inp.weapon)) else ARM_FISTS
        if p.weapon in GUN_SLOTS and not p.hands and p.dolly is None:
            self._menace(p)
        if b & B_TAUNT:
            self._dance(p, dt)
        fists = p.weapon == ARM_FISTS and not p.hands and p.dolly is None and p.carrying is None
        charged = self._charge_fists(p, bool(b & B_FIRE) and fists, dt) if fists or p.charge_t else False
        if fire_tap and p.fire_cd <= 0 and not charged:
            if p.carrying is not None:
                self._drop_carry(p, throw=True)           # YEET
                p.fire_cd = C.THROW_COOLDOWN
            elif p.hands:
                self._throw_part(p)
            else:
                self._attack(p)
        if drop_tap and p.carrying is not None:
            self._drop_carry(p, throw=False)
        elif drop_tap and p.dolly is not None:
            self._release_dolly(p)
            self.sfx(S_DROP, p.x, p.y)
        elif drop_tap and p.hands:
            part = p.hands.pop()
            fx, fy = math.cos(p.ang), math.sin(p.ang)
            self.add_pickup(part, p.x + fx * 0.9, p.y + fy * 0.9, fx * 1.5, fy * 1.5)
            self.sfx(S_DROP, p.x, p.y)
        elif drop_tap:
            who = self._grab_target(p)
            if who is not None:
                self._grab(p, who)
        if p.carrying is not None:
            who = self._carried_ref(p)
            p.prompt = "CARRYING %s.  CLICK: THROW   G: PUT DOWN" % (
                who.name if isinstance(who, Player) else "A STRANGER")
            p.hold = 0.0
            return

        found = self._find_interaction(p)
        key, label, duration, action = found[:4]
        p.prompt = label
        if alt_tap and len(found) > 4 and found[4] is not None:
            found[4]()                # X: the other thing (bail, sell it whole, ...)
            return
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
        Priority (v0.10, Bryce: "items take precedent over shops / actions"): whatever's
        already in your hands or right in front of you (a dolly, someone down, a loose part)
        beats a bench or a market crate you merely happen to be standing near; benches and
        the market still beat the gate/door and everything after. Exactly one prompt at a time."""
        m = self.map
        # first person: you use what you're looking at, measured from a point
        # just in front of your face rather than from your feet
        ax, ay = self._aim(p)
        # someone on the floor, or with their hands up: help yourself
        mark = self._robbable_near(ax, ay)
        if mark is not None and mark.kind == CHICKEN:
            return (None, "IT'S A CHICKEN. IT HAS NO POCKETS." + ("   G: PICK UP" if not p.hands else ""), 0, None)
        if mark is not None and mark.kind == KEYGUARD:
            return (("keys", mark.id), "HOLD E: TAKE HIS KEYS", C.ROB_TIME, lambda: self._take_keys(p, mark))
        if mark is not None:
            grab = "   G: PICK UP" if not p.hands else ""
            if mark.wallet <= 0:
                return (None, "THEY'RE BROKE. A BUS PASS AND HALF A SANDWICH." + grab, 0, None)
            return (("rob", mark.id), "HOLD E: ROB THEM" + grab, C.ROB_TIME, lambda: self._rob(p, mark))
        # pickups
        best, bd = None, C.INTERACT_RANGE_PICKUP
        for pk in self.pickups.values():
            d = math.hypot(pk.x - ax, pk.y - ay)
            if d < bd:
                best, bd = pk, d
        if best is not None and not (best.part.bulk == DOLLY and p.dolly is not None):
            part = best.part
            if part.bulk == DOLLY:
                return (None, "%s: TOO HEAVY TO LIFT - FETCH THE DOLLY" % part.name.upper(), 0, None)
            if not p.can_hold(part):
                return (None, "HANDS FULL - SELL IT OR DROP (G)", 0, None)
            return (("pick", best.id), "E: PICK UP %s ($%d)" % (part.name.upper(), part.value),
                    C.PICKUP_TIME, lambda: self._pickup(p, best))
        # (v0.12.1) somebody to talk to: Paige, the Fixer, Tommy, the Kingpin
        talk = self._talk_interaction(p, ax, ay)
        if talk is not None:
            return talk
        # benches
        for bench, is_sell in ((m.sell_bench, True), (m.tune_bench, False)):
            bx, by, bw, bh = bench
            cx = clamp(ax, bx, bx + bw)
            cy = clamp(ay, by, by + bh)
            if math.hypot(ax - cx, ay - cy) < C.INTERACT_RANGE_BENCH:
                if not is_sell:
                    # the mod shop. Anything you're holding goes in the locker on the way in.
                    held = p.hands or (p.dolly is not None and p.dolly.part is not None)
                    return (("modshop",), "E: MOD SHOP" + (" (WHAT YOU'RE HOLDING GOES IN THE LOCKER)" if held else ""),
                            0, lambda: self._open_modshop(p))
                if p.dolly is not None:
                    return self._dolly_bench(p, p.dolly, is_sell)
                if not p.hands:
                    return (None, "SELL BENCH: BRING PARTS HERE (OR SELL FROM THE LOCKER IN THE MOD SHOP)", 0, None)
                part = p.hands[-1]
                return (("sell", id(part)), "HOLD E: SELL %s FOR $%d" % (part.name.upper(), part.value),
                        C.SELL_TIME, lambda: self._sell(p))
        market = self._market_interaction(p, ax, ay)
        if market is not None:
            return market
        fence = self._fence_interaction(p, ax, ay)
        if fence is not None:
            return fence
        if p.dolly is not None:
            return self._dolly_interaction(p, p.dolly)
        gate = self._gate_interaction(p, ax, ay) or self._door_interaction(p, ax, ay)
        if gate is not None:
            return gate
        # a dolly to grab
        dl = self._nearest_dolly(ax, ay, C.INTERACT_RANGE_DOLLY)
        if dl is not None:
            if p.hands:
                return (None, "DOLLY: EMPTY YOUR HANDS FIRST (SELL OR DROP)", 0, None)
            load = " (%s ON IT)" % dl.part.name.upper() if dl.part is not None else ""
            return (("dolly", dl.id), "E: PUSH THE DOLLY" + load, 0, lambda: self._grab_dolly(p, dl))
        # a crewmate within reach: you COULD pick them up. Should you? Yes.
        if not p.hands:
            for q in self.players.values():
                if q is not p and q.state in (FOOT, TUMBLE) and math.hypot(q.x - ax, q.y - ay) < C.GRAB_RANGE * 0.8:
                    return (None, "G: PICK UP %s (THEY'LL HATE IT)" % q.name, 0, None)
        # cars: the one whose bodywork is closest to where you're looking
        best, bd = None, 99.0
        for car in self.cars.values():
            if car.kind == COP and not self._copcar_stealable(car):
                continue
            if abs(car.x - ax) > 6 or abs(car.y - ay) > 6:
                continue
            d = box_distance(car, ax, ay)
            if d < bd:
                best, bd = car, d
        car = best
        if car is None or bd > C.CAR_AIM_RANGE + (0.8 if car.state == DELIVERED else 0):
            return (None, "", 0, None)
        # the back of the car: the trunk (a delivered car's only if there's something in it,
        # otherwise the back is for stripping the bumper)
        c_, s_ = math.cos(car.ang), math.sin(car.ang)
        if (ax - car.x) * c_ + (ay - car.y) * s_ < -car.hl * 0.45 and car.kind != TRAFFIC and \
                (car.state != DELIVERED or car.trunk or p.hands):
            tr = self._trunk_interaction(p, car)
            if tr is not None:
                return tr
        if car.kind == COP:
            return (("copcar", car.id), "HOLD E: STEAL THE COP CAR WHILE HE'S BUSY (+%d HEAT)" % C.COPCAR_STEAL_HEAT,
                    C.COPCAR_STEAL_TIME, lambda: self._steal_cop_car(p, car))
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
            # (v0.10, Bryce: "sneaking / turning off the alarm on a stolen car by cutting
            # wire minigame") X toggles which method E commits to -- smashing the window is
            # fast but always screams; cutting wires is slower and blind (ALARM_CUT_WIRES to
            # one), quiet if you luck into the right one and worse than smashing if you don't.
            if p.sneak:
                return (("cutwires", car.id),
                        "HOLD E: CUT THE WIRES (1 IN %d QUIET)   X: FORGET IT, SMASH IT" % C.ALARM_CUT_WIRES,
                        C.ALARM_CUT_TIME, lambda: self._cut_wires(p, car), lambda: setattr(p, "sneak", False))
            return (("breakin", car.id), "HOLD E: BREAK IN (SETS OFF ALARM)   X: CUT THE WIRES INSTEAD (SLOWER)",
                    C.BREAKIN_TIME, lambda: self._break_in(p, car), lambda: setattr(p, "sneak", True))
        if car.state == BROKEN_IN:
            return (("hotwire", car.id), "HOLD E: HOTWIRE", C.HOTWIRE_TIME, lambda: self._hotwire(p, car))
        if car.state == RUNNING:
            if car.driver is None:
                return (("drive", car.id), "E: DRIVE", 0, lambda: self._enter_car(p, car, DRIVER))
            if car.passenger is None:
                return (("shot", car.id), "E: RIDE SHOTGUN", 0, lambda: self._enter_car(p, car, PASSENGER))
            return (None, "CAR IS FULL", 0, None)
        # delivered: strip or crush -- or (v0.9) X: sell the whole thing to a man called Dave
        res = self._strip_interaction(p, car)
        whole = self.whole_price(car)
        label = res[1] + "   " if res[1] else ""
        return (res[0], label + "X: SELL IT WHOLE $%d" % whole, res[2], res[3], lambda: self._sell_whole(p, car))

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
            ax, ay = car.anchor(slot)
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
        p.sneak = False
        self.heat = min(C.HEAT_MAX, self.heat + C.HEAT_BREAKIN)
        self._charge(p, "gta")
        self.sfx(S_BREAKIN, car.x, car.y)
        self.toast("%s SMASHED A WINDOW. ALARM! +%d HEAT" % (p.name, C.HEAT_BREAKIN), T_BAD)
        self._breakin_specials(p, car, loud=True)
        self._quest_on_steal(p, car)

    def _cut_wires(self, p, car):
        """(v0.10) the slow, quiet way in: one wire in ALARM_CUT_WIRES is the right one.
        Guess it and nobody hears a thing; guess wrong and it's louder than just smashing
        the window would have been -- you had your chance to do this the easy way."""
        car.state = BROKEN_IN
        car.stolen = True
        p.sneak = False
        self._charge(p, "gta")
        quiet = self.rng.randrange(C.ALARM_CUT_WIRES) == 0
        if quiet:
            self.sfx(S_STRIP, car.x, car.y)
            self.toast("%s CUT THE RIGHT WIRE. NOT A PEEP." % p.name, T_INFO)
        else:
            car.alarm = True
            self.heat = min(C.HEAT_MAX, self.heat + C.ALARM_CUT_FAIL_HEAT)
            self.sfx(S_BREAKIN, car.x, car.y)
            self.toast("%s CUT THE WRONG WIRE. ALARM! +%d HEAT" % (p.name, C.ALARM_CUT_FAIL_HEAT), T_BAD)
        self._breakin_specials(p, car, loud=not quiet)
        self._quest_on_steal(p, car)

    def _breakin_specials(self, p, car, loud):
        """Clown cars burst open no matter how quietly you got the door open -- that's the
        joke. An angry owner is a different story: they only come running if they actually
        heard or saw you get in, so a clean wire-cut lets you have their car and their day."""
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
        elif car.special == "owner" and not car.special_fired and loud:
            car.special_fired = True
            for _ in range(12):
                a = self.rng.uniform(0, 2 * math.pi)
                x = car.x + math.cos(a) * C.OWNER_SPAWN_DIST
                y = car.y + math.sin(a) * C.OWNER_SPAWN_DIST
                if not self.map.solid_at(x, y):
                    break
            n = NPC(self.new_id(), OWNER, x, y)
            n.target = car.id
            n.brave = True                        # it's THEIR car. Of course they're going to swing.
            n.foe, n.hostile_t, n.grit = p.id, C.BRAWL_TIME, 2
            self.npcs[n.id] = n
            self.toast("OWNER: HEY!! THAT'S MY CAR!", T_BAD)

    def _hotwire(self, p, car):
        car.state = RUNNING
        self.sfx(S_HOTWIRE, car.x, car.y)
        # (v0.12) one in five stolen cars has a little loose change down the seats. Doesn't
        # apply to your own personal car (nobody's stealing that, hotwiring never runs on it)
        if self.rng.random() < C.SEAT_CHANGE_CHANCE:
            change = self.rng.randint(C.SEAT_CHANGE_MIN, C.SEAT_CHANGE_MAX)
            self._earn(change)
            self.toast("%s HOTWIRED IT. GO GO GO! (+$%d FOUND IN THE SEATS. GROSS BUT FREE.)" %
                       (p.name, change), T_MONEY)
        else:
            self.toast("%s HOTWIRED IT. GO GO GO!" % p.name, T_INFO)
        self._enter_car(p, car, DRIVER)

    def _strip(self, p, car, slot):
        part = car.parts.get(slot)
        if part is None or not p.can_hold(part):
            return
        car.parts[slot] = None
        p.hands.append(part)
        self.sfx(S_STRIP, car.x, car.y)
        self._quest_on_strip(p, part)

    def _crush(self, car, pay):
        self._spill_trunk(car)
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
            if pk.fixed:
                # somebody's garden gnome. The city takes this VERY seriously.
                self._crime(C.GNOME_HEAT)
                self._charge(p, "gnome")
                self.sfx(S_GNOME, p.x, p.y)
                self.toast("%s STOLE A GARDEN GNOME. +%d HEAT. MONSTER." % (p.name, C.GNOME_HEAT), T_BAD)

    def _sell(self, p):
        if not p.hands:
            return
        part = p.hands.pop()
        self._earn(part.value, 1)
        self.sfx(S_SELL, p.x, p.y)
        tip = self._tip_jar()
        if tip:
            self.toast("SOLD %s: +$%d (+$%d TIP FROM A PASSERBY WHO LIKES YOUR HUSTLE)" %
                       (part.name.upper(), part.value, tip), T_MONEY)
        else:
            self.toast("SOLD %s: +$%d" % (part.name.upper(), part.value), T_MONEY)

    def _tip_jar(self):
        """(v0.12) selling at the bench, once in a while somebody walking past chips in.
        Doesn't apply to selling from the mod shop locker -- you're not visibly hustling in
        there, there's nobody to tip you."""
        if self.rng.random() >= C.TIP_JAR_CHANCE:
            return 0
        tip = self.rng.randint(C.TIP_JAR_MIN, C.TIP_JAR_MAX)
        self._earn(tip)
        return tip

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
        for car in self.cars.values():
            if V.model(car.model).bed and box_distance(car, d.x, d.y) < 1.2:
                bx, by = car.to_world(-car.hl, 0.0)
                if (bx - d.x) ** 2 + (by - d.y) ** 2 < 4.0:
                    got = self._trunk_dolly(p, d, car)
                    if got is not None:
                        return got
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
            if math.hypot(car.x - p.x, car.y - p.y) > C.INTERACT_RANGE_CAR + car.hl:
                continue
            ex, ey = car.to_world(*car.anchor("Engine"))
            reach = min(math.hypot(ex - p.x, ey - p.y), math.hypot(ex - d.x, ey - d.y))
            return car, reach < C.INTERACT_RANGE_SLOT + 1.2
        return None, False

    def _dolly_bench(self, p, d, is_sell):
        if d.part is None:
            return (None, "THE DOLLY'S EMPTY.  G: LET GO", 0, None)
        part = d.part
        return (("dsell", id(part)), "HOLD E: SELL %s FOR $%d" % (part.name.upper(), part.value),
                C.SELL_TIME, lambda: self._dolly_sell(p, d))

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
            self._quest_on_dolly_engine(p, car)

    def _dolly_sell(self, p, d):
        part = d.part
        if part is None:
            return
        d.part = None
        self._earn(part.value, 1)
        self.sfx(S_SELL, p.x, p.y)
        self.toast("SOLD %s: +$%d" % (part.name.upper(), part.value), T_MONEY)

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
            if n.kind not in (CLOWN, STREAKER) and n.kind not in LAW and n.tumble_t <= 0 and \
                    self._in_front(p, n.x, n.y, C.SURRENDER_RANGE, C.SURRENDER_CONE) is not None \
                    and self.los(p.x, p.y, n.x, n.y):
                if n.surrender_t <= 0 and n.complain_cd <= 0:
                    n.complain_cd = 5.0
                    self.toast(self.rng.choice(SURRENDER_LINES), T_WHITE)
                n.surrender_t = 0.6

    def _attack(self, p):
        if p.boxed:
            p.fire_cd = 0.5
            self.toast("YOU'RE IN A BOX. BOXES CAN'T PUNCH. (C: GET OUT)", T_INFO)
            return
        if p.hands or p.dolly is not None:
            p.fire_cd = 0.3
            self.toast("HANDS FULL - DROP IT (G) TO FIGHT", T_INFO)
            return
        w = p.weapon
        if w == ARM_FISTS:
            p.fire_cd = C.PUNCH_COOLDOWN
            self._punch(p)
        elif w == ARM_CHICKEN:
            p.fire_cd = C.CHICKEN_COOLDOWN
            self._punch(p, chicken=True)
        elif w in GUN_SLOTS:
            if p.ammo[w] <= 0:
                p.fire_cd = 0.3
                self.sfx(S_EMPTY, p.x, p.y)
                self.toast("*CLICK* OUT OF AMMO. THE CRATES IN THE SHOP SELL MORE.", T_INFO)
                return
            p.ammo[w] -= 1
            self._shoot(p, w)
        else:
            p.fire_cd = 0.5
            self._place_trap(p, TRAP_OF_ARM[w])

    def _punch(self, p, chicken=False):
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
            if chicken:
                self.sfx(S_SQUEAK, p.x, p.y)      # a mighty squeak at thin air
            self._punch_cell_door(p)   # a mighty swing at thin air. Or at a cell door: CLANG
            return
        fx, fy = math.cos(p.ang), math.sin(p.ang)
        shove = C.CHICKEN_KNOCK if chicken else 5.0
        self.sfx(S_SQUEAK if chicken else S_PUNCH, best.x, best.y)
        if isinstance(best, Player):
            if best.state == FOOT:
                self._hurt_player(best, fx * shove, fy * shove, C.PUNCH_PLAYER_TUMBLE, BN_BONKED if chicken else BN_NONE)
                self.toast(("%s SLAPPED %s WITH A RUBBER CHICKEN." if chicken else
                            "%s DECKED %s. FRIENDSHIP: TESTED.") % (p.name, best.name), T_WHITE)
            return
        if best.carried_by is not None:
            return
        self._knock_down_npc(best, fx * shove, fy * shove, C.CHICKEN_KNOCKDOWN if chicken else C.PUNCH_KNOCKDOWN, p)
        silly = best.kind in (STREAKER, CHICKEN, MIME)
        if not p.jailed and best.kind not in LAW and not silly and not chicken:
            self._crime(C.PUNCH_HEAT)            # (assault with a rubber chicken isn't on the statute books)
            self._charge(p, "assault")
        if best.complain_cd <= 0 and best.kind not in LAW and best.kind != STREAKER:
            best.complain_cd = 3.0
            if chicken:
                lines = CHICKEN_SLAP_LINES
            elif best.kind == MIME:
                lines = MIME_PUNCH_LINES
            elif best.kind == CHICKEN:
                lines = CHICKEN_PUNCH_LINES
            else:
                lines = CLOWN_LINES if best.kind == CLOWN else PUNCH_LINES
            self.toast(self.rng.choice(lines), T_WHITE)

    def _shoot(self, p, w):
        """(v0.12) every gun past the shotgun still calls this: the per-weapon numbers come
        out of GUN_STATS instead of a pile of if/elif, so adding gun #8 someday is a config
        entry, not a new branch here. The two launchers (SPLASH_GUNS) hitscan exactly like
        the others, then hand their impact point to _blast instead of _shot_hits -- a mortar
        strike, not a thrown grenade, but at these ranges nobody can tell the difference."""
        rng_, cd, pellets, spread, splash, _ = GUN_STATS[w]
        p.fire_cd = cd
        self.sfx(GUN_SOUND[w], p.x, p.y)
        for k in range(pellets):
            if pellets > 1:
                off = ((k / (pellets - 1)) * 2 - 1) * spread + self.rng.uniform(-0.02, 0.02)
            else:
                off = self.rng.uniform(-spread, spread) if spread else 0.0
            ang = p.ang + off
            dist, target = self._ray_hit(p, ang, rng_)
            ex, ey = p.x + math.cos(ang) * dist, p.y + math.sin(ang) * dist
            if k == 0 or k == pellets - 1 or k == pellets // 2:
                self.tracer(w, p.x, p.y, ex, ey)
            if splash > 0:
                self._blast(p, ex, ey, splash)
            elif target is not None:
                self._shot_hits(p, target, ex, ey, ang, pellets > 1)
        # gunshots carry: anyone within earshot notices, everyone nearby runs
        near = any((n.x - p.x) ** 2 + (n.y - p.y) ** 2 < C.GUNSHOT_EARSHOT ** 2 for n in self.npcs.values()) or \
            any(c.kind == COP and (c.x - p.x) ** 2 + (c.y - p.y) ** 2 < C.GUNSHOT_EARSHOT ** 2
                for c in self.cars.values())
        if near:
            self._crime(C.GUNSHOT_HEAT)
        self._charge(p, "gun")
        self._escalate(p.x, p.y)                # cops who hear it stop reaching for the taser
        self._scare(p.x, p.y, C.PED_FLEE_CRASH_RADIUS * 1.6)

    def _blast(self, p, x, y, radius):
        """Where a grenade or rocket lands. Everything within `radius` gets the same
        treatment _shot_hits gives a direct hit -- lethal to the law and civilians, a tumble
        for a player, a fire for a cop car, a shredded tyre for anything else -- just applied
        to everyone in range instead of whoever the ray happened to touch."""
        self.sfx(S_BOOM, x, y)
        self.toast("KA-BOOM!", T_COP)
        self._scare(x, y, max(C.PED_FLEE_CRASH_RADIUS, radius * 2.5))
        for n in list(self.npcs.values()):
            if n.carried_by is not None or (n.x - x) ** 2 + (n.y - y) ** 2 > radius ** 2:
                continue
            if n.kind == OFFICER:
                self.lethal_t = C.LETHAL_TIME
            if n.kind in (OFFICER, GUARD, KEYGUARD, PED, OWNER, CLOWN):
                self._kill_npc(p, n)
                continue
            fx, fy = n.x - x, n.y - y
            m = math.hypot(fx, fy) or 1.0
            self._knock_down_npc(n, fx / m * 8, fy / m * 8, C.SHOT_KNOCKDOWN * 1.5, p)
        for q in self.players.values():
            if q is p or q.state != FOOT or (q.x - x) ** 2 + (q.y - y) ** 2 > radius ** 2:
                continue
            fx, fy = q.x - x, q.y - y
            m = math.hypot(fx, fy) or 1.0
            self._hurt_player(q, fx / m * 9, fy / m * 9, C.SHOT_PLAYER_TUMBLE * 1.5, BN_HUMBLED)
            self.toast("%s CAUGHT THE BLAST. THEY'RE FINE. THEY'RE FURIOUS." % q.name, T_BAD)
        for car in list(self.cars.values()):
            if car.id == p.car_id or (car.x - x) ** 2 + (car.y - y) ** 2 > (radius + car.bound) ** 2:
                continue
            if car.kind == COP:
                self._crime(C.SHOOT_COP_HEAT)
                self.lethal_t = C.LETHAL_TIME
                if car.fire_t <= 0:
                    car.fire_t = C.COP_BURN_TIME
                    self.sfx(S_IGNITE, car.x, car.y)
                    self.toast("THE COP CAR'S ON FIRE! GET CLEAR!", T_COP)
            else:
                if car.kind == TRAFFIC:
                    car.shaken_t = max(car.shaken_t, C.TRAFFIC_SHAKEN_TIME)
                ws = [w for w in WHEEL_SLOTS if car.parts.get(w) is not None]
                if ws:
                    self._knock_off(car, self.rng.choice(ws))

    def _ray_hit(self, p, ang, reach):
        """Hitscan, Doom style: first thing along the ray -> (distance, thing or None)."""
        dx, dy = math.cos(ang), math.sin(ang)
        best_d = self.map.ray_clear(p.x, p.y, ang, reach, step=0.25)
        best = None
        for car in self.cars.values():
            if car.id == p.car_id:
                continue
            ox, oy = p.x - car.x, p.y - car.y
            if ox * ox + oy * oy > (best_d + car.bound) ** 2:
                continue
            c, s_ = math.cos(car.ang), math.sin(car.ang)
            lx, ly = ox * c + oy * s_, -ox * s_ + oy * c
            ldx, ldy = dx * c + dy * s_, -dx * s_ + dy * c
            t0, t1 = 0.0, best_d
            for o, dd, h in ((lx, ldx, car.hl), (ly, ldy, car.hw)):
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
            wheel = min(WHEEL_SLOTS, key=lambda w: (car.anchor(w)[0] - lx) ** 2 + (car.anchor(w)[1] - ly) ** 2)
            wx, wy = car.anchor(wheel)
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
                self.lethal_t = C.LETHAL_TIME
                if car.hits >= C.COP_CAR_HITS and car.fire_t <= 0:
                    car.fire_t = C.COP_BURN_TIME
                    self.sfx(S_IGNITE, car.x, car.y)
                    self.toast("THE COP CAR'S ON FIRE! GET CLEAR!", T_COP)
            elif car.kind == TRAFFIC:
                car.shaken_t = max(car.shaken_t, C.TRAFFIC_SHAKEN_TIME)
            if car.model == V.ARMOURED and lx < -car.hl * 0.4:
                self._money_hit(car)                  # (v0.9) KLANG. Keep going: the back doors will give
            return
        if isinstance(target, Player):
            if target.state == FOOT:
                self._hurt_player(target, fx * 7, fy * 7, C.SHOT_PLAYER_TUMBLE, BN_HUMBLED)
                self.toast("%s SHOT %s. THEY'RE FINE. THEY'RE FURIOUS." % (p.name, target.name), T_BAD)
            return
        n = target
        if n.carried_by is not None:
            return
        if n.kind == OFFICER:
            self.lethal_t = C.LETHAL_TIME       # you shot a police officer. Of course they're shooting back.
        # (v0.10, Bryce: "when cops die ambulance comes to pick them up... make them die") a
        # bullet is lethal to the law too, not just a knockdown -- and civilians, so a witness
        # can be silenced for good instead of just having a nap. Dogs and the streaker are
        # exempt: taking the K9 unit down is a running joke, not a body count.
        if n.kind in (OFFICER, GUARD, KEYGUARD, PED, OWNER, CLOWN):
            self._kill_npc(p, n)
            return
        self._knock_down_npc(n, fx * 6, fy * 6, C.SHOT_KNOCKDOWN, p)
        self.sfx(S_YELP, n.x, n.y)
        if n.complain_cd <= 0 and n.kind not in LAW:
            n.complain_cd = 3.0
            self.toast(self.rng.choice(SHOT_LINES), T_WHITE)

    def _kill_npc(self, p, n):
        """(v0.10) A bullet is the end of the story for a civilian or a cop, not a nap. No
        witness left to phone it in -- but murder (or "assaulting an officer" the hard way)
        is on the rap sheet either way, and an officer or guard gets the ambulance."""
        self.sfx(S_YELP, n.x, n.y)
        law = n.kind in LAW
        if law:
            self.sfx(S_AMBULANCE, n.x, n.y)
            if not p.jailed:
                self._crime(C.SHOOT_COP_HEAT)
                self._charge(p, "cop")
            if n.kind in (GUARD, KEYGUARD):
                self.jail_alert = True
                self.toast(self.rng.choice(COP_DOWN_LINES) % p.name, T_COP)
            else:
                self.toast("OFFICER DOWN! EVERY COP IN THE CITY IS SHOOTING TO KILL.", T_COP)
        elif not p.jailed:
            self._crime(C.MURDER_HEAT)
            self._charge(p, "murder")
            self.toast(self.rng.choice(MURDER_LINES) % p.name, T_BAD)
        del self.npcs[n.id]

    # ------------------------------------------------------------------ robbing people
    def _robbable_near(self, x, y):
        best, bd = None, 1.7
        for n in self.npcs.values():
            if (n.tumble_t > 0 or n.surrender_t > 0 or n.laugh_t > 0) and n.carried_by is None and \
                    n.kind not in (DOG, STREAKER):
                d = math.hypot(n.x - x, n.y - y)
                if d < bd:
                    best, bd = n, d
        return best

    def _rob(self, p, n):
        if n.id not in self.npcs or n.wallet <= 0:
            return
        if n.kind == MIME:
            n.wallet = 0
            n.wallet_t = C.WALLET_REFILL
            n.surrender_t = 0.0
            self.sfx(S_ROB, n.x, n.y)
            self.toast(MIME_ROB_LINE, T_INFO)      # (it's the thought that counts)
            return
        cash, n.wallet = n.wallet, 0
        n.wallet_t = C.WALLET_REFILL
        self._earn(cash)
        if not p.jailed:
            self._crime(C.ROB_HEAT if n.kind not in LAW else C.ASSAULT_OFFICER_HEAT)
            self._charge(p, "rob")
        self.sfx(S_ROB, n.x, n.y)
        if cash >= C.JACKPOT_WALLET[0]:
            # (v0.12) that wallet was never going to say "average pedestrian" on the label
            self.toast("%s HIT THE JACKPOT: A WALLET WITH $%d IN IT. SOMEONE'S HAVING A BAD DAY." %
                       (p.name, cash), T_MONEY)
        else:
            self.toast("%s LIFTED A WALLET: +$%d %s" % (p.name, cash, self.rng.choice(WALLET_EXTRAS)), T_MONEY)
        n.surrender_t = 0.0
        n.laugh_t = 0.0
        p.robbed_from[n.id] = p.robbed_from.get(n.id, 0) + cash
        if n.kind in LAW:
            pass                      # (a cop's wallet: $12 and a donut voucher. Worth it.)
        elif n.brave:
            self._provoke(n, p)       # they get up. They remember your face.
        else:
            self._flee(n, n.x - p.x, n.y - p.y)

    # ------------------------------------------------------------------ carjacking
    def _carjack(self, p, car):
        if car.id not in self.cars or car.kind != TRAFFIC or car.speed() > C.CARJACK_MAX_SPEED:
            return
        x, y = car.to_world(0.0, -car.hw - 1.0)
        if self.map.solid_at(x, y):
            x, y = car.to_world(0.0, car.hw + 1.0)
        n = NPC(self.new_id(), PED, x, y)
        n.ttl = 40.0
        n.tumble_t = 1.2
        n.vx, n.vy = (x - car.x) * 2, (y - car.y) * 2
        self.npcs[n.id] = n
        if self.rng.random() < C.CARJACK_FIGHT_CHANCE:
            n.brave = True
            n.armed = self.rng.random() < C.ARMED_CHANCE
            self._provoke(n, p, witnesses=False)       # they get up swinging
        else:
            self._flee(n, x - car.x, y - car.y)
        car.kind, car.state, car.route = CIV, RUNNING, []
        car.stolen, car.alarm, car.special = True, False, None
        car.throttle = car.steer = 0.0
        car.handbrake = car.horn = False
        self._crime(C.CARJACK_HEAT)
        self.sfx(S_PUNCH, x, y)
        self.toast("%s DRAGGED THE DRIVER OUT. CARJACKED! +%d HEAT" % (p.name, C.CARJACK_HEAT), T_BAD)
        self._quest_on_steal(p, car)
        self._story_event("carjack", car)
        self._enter_car(p, car, DRIVER)

    # ------------------------------------------------------------------ black market
    def _market_crates(self):
        """(v0.12) every crate you can currently reach: the home shop's, plus whichever
        fences you've bought. An unbought fence's crates aren't in this list at all -- you
        see the "BUY THIS SHOP" sign there instead (_fence_interaction), not empty shelves."""
        crates = list(self.map.market)
        for i, fs in enumerate(self.map.fence_shops):
            if self.shop_owned[i + 1]:
                crates.extend(fs["market"])
        return crates

    def _fence_interaction(self, p, ax, ay):
        """(v0.12, Bryce: "make multiple garages, make them available for purchase") the
        plaque outside an unbought fence shop. Bought shops don't show up here again -- the
        market crates they unlock take over instead (_market_crates)."""
        for i, fs in enumerate(self.map.fence_shops):
            idx = i + 1
            if self.shop_owned[idx]:
                continue
            sx, sy = fs["sign"]
            if math.hypot(ax - sx, ay - sy) >= C.INTERACT_RANGE_BENCH:
                continue
            price = C.SHOP_PRICE[idx]
            if self.cash < price:
                return (None, "SHOP %d: $%d TO BUY - CAN'T AFFORD IT YET" % (idx + 1, price), 0, None)
            return (("buyshop", idx), "HOLD E: BUY SHOP %d - $%d (+$%d/DAY RENT)" % (idx + 1, price, C.SHOP_RENT[idx]),
                    C.BUY_TIME, lambda: self._buy_shop(idx))
        return None

    def _buy_shop(self, idx):
        if self.shop_owned[idx] or self.cash < C.SHOP_PRICE[idx]:
            return
        self.cash -= C.SHOP_PRICE[idx]
        self.shop_owned[idx] = True
        cx, cy = self.map.fence_shops[idx - 1]["center"]
        self.sfx(S_CASH, cx, cy)
        self.toast("SHOP %d IS YOURS. RENT'S UP TO $%d/DAY." % (idx + 1, self.rent_due()), T_MONEY)
        self._story_event("buy")

    def _market_interaction(self, p, ax, ay):
        best, bd = None, 1.7            # crates are 1.75 m apart (v0.9: ten of them): nearest wins
        for (x, y, item) in self._market_crates():
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
        # (v0.12) the 5 new guns get the same "already own it" guard as the pistol/shotgun did
        if best in ITEM_GUN and p.arms & (1 << ITEM_GUN[best]):
            return (None, "BLACK MARKET: YOU'VE ALREADY GOT ONE OF THOSE.", 0, None)
        if best == "ammo" and not any(p.arms & (1 << g) for g in GUN_SLOTS):
            return (None, "BLACK MARKET: AMMO. BUY A GUN FIRST, GENIUS.", 0, None)
        if best == "chicken" and p.arms & (1 << ARM_CHICKEN):
            return (None, "BLACK MARKET: ONE RUBBER CHICKEN PER CUSTOMER. HOUSE RULES.", 0, None)
        if best == "box" and p.has_box:
            return (None, "BLACK MARKET: YOU'VE ALREADY GOT A BOX. PRESS C TO GET IN IT.", 0, None)
        gear = {"spikes": 0, "roadblock": 1, "banana": 2, "donuts": 3, "whoopee": 4}.get(best)
        if gear is not None and p.gear[gear] >= C.MAX_TRAPS_EACH:
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
            # (v0.12) one crate tops up every gun you own now, not just the first two
            for g in GUN_SLOTS:
                if p.arms & (1 << g):
                    p.ammo[g] = min(C.MAX_AMMO, p.ammo[g] + GUN_STATS[g][5])
            tip = "LOCKED AND LOADED"
        elif item in ITEM_GUN:
            slot = ITEM_GUN[item]
            p.arms |= 1 << slot
            p.ammo[slot] = min(C.MAX_AMMO, p.ammo[slot] + GUN_STATS[slot][5])
            tip = "WHEEL OR Q TO DRAW IT"
        elif item == "spikes":
            p.gear[0] += 1
            tip = "PRESS 4, CLICK TO LAY IT ACROSS THE ROAD"
        elif item == "roadblock":
            p.gear[1] += 1
            tip = "PRESS 5, CLICK TO BLOCK THE ROAD"
        elif item == "banana":
            p.gear[2] += 1
            tip = "PRESS 6, CLICK TO DROP IT. WATCH YOUR STEP."
        elif item == "chicken":
            p.arms |= 1 << ARM_CHICKEN
            tip = "PRESS 8. SQUEAK. (NO HEAT: IT'S NOT A WEAPON, OFFICER.)"
        elif item == "whoopee":
            p.gear[4] += 1
            tip = "PRESS 9, CLICK TO LAY IT DOWN. EVERYONE WHO HEARS IT LAUGHS. COPS TOO."
        elif item == "box":
            p.has_box = True
            tip = "PRESS C TO HIDE IN IT. STAND STILL AND NOBODY SEES YOU. MOVE AND... WELL."
        elif item == "ticket":
            self._scratch_ticket(p)
            return
        else:
            p.gear[3] += 1
            tip = "PRESS 7, CLICK TO THROW. COPS CAN'T RESIST."
        self.sfx(S_BUY, p.x, p.y)
        self.toast("BOUGHT %s: -$%d. %s" % (MARKET[item][0].split(" (")[0], price, tip), T_INFO)

    def _scratch_ticket(self, p):
        """(v0.12) a scratch ticket off the black market: TICKET_ODDS is a chance/payout
        table, checked in order. It nets negative on average -- PRICE_TICKET is worth more
        than the expected payout -- same as any real scratch ticket, which is the joke."""
        self.sfx(S_BUY, p.x, p.y)
        roll, acc, payout = self.rng.random(), 0.0, 0
        for chance, amount in C.TICKET_ODDS:
            acc += chance
            if roll < acc:
                payout = amount
                break
        if payout <= 0:
            self.toast("SCRATCH TICKET: NOTHING. THE HOUSE THANKS YOU FOR YOUR SERVICE.", T_INFO)
            return
        self._earn(payout)
        if payout >= 500:
            self.sfx(S_CASH, p.x, p.y)
            self.toast("SCRATCH TICKET: JACKPOT! +$%d. FRAME IT. OR SPEND IT. SPEND IT." % payout, T_MONEY)
        else:
            self.toast("SCRATCH TICKET: +$%d. NOT NOTHING." % payout, T_MONEY)

    def _toggle_box(self, p):
        """(v0.9) C: into the cardboard box, or out of it. Stand still in it and nobody
        -- peds, cameras, cops, officers -- can see you. Move, and you're a box with legs."""
        if not p.has_box:
            return
        if p.boxed:
            p.boxed = False
            self.toast("%s CLIMBED OUT OF A CARDBOARD BOX. NOBODY WAS FOOLED. (EVERYONE WAS FOOLED.)" % p.name,
                       T_INFO)
            return
        if p.hands or p.dolly is not None or p.carrying is not None:
            self.toast("PUT THAT DOWN FIRST. IT'S A BOX, NOT A REMOVALS VAN.", T_INFO)
            return
        p.boxed = True
        p.still_t = 0.0
        self.sfx(S_TRUNK, p.x, p.y)
        self.toast(self.rng.choice(BOX_LINES), T_INFO)

    def _copcar_stealable(self, car):
        return car.kind == COP and car.officer is not None and car.fire_t <= 0 and car.speed() < 1.5

    def _steal_cop_car(self, p, car):
        """(v0.9) The officer got out to chase somebody and left it running. Rude not to."""
        if not self._copcar_stealable(car):
            return
        n = self.npcs.get(car.officer)
        if n is not None:
            n.car_id = None
            self.toast(self.rng.choice(COPCAR_LINES) % p.name, T_COP)
        car.kind = CIV
        car.copcar = True
        car.officer = None
        car.patrol = False
        car.state = RUNNING
        car.stolen = True
        car.horn_type = V.HORN_SIREN               # the good horn
        car.throttle = car.steer = 0.0
        car.handbrake = False
        self._crime(C.COPCAR_STEAL_HEAT)
        self._charge(p, "copcar")
        self.sfx(S_HOTWIRE, car.x, car.y)
        self._quest_on_steal(p, car)
        self._enter_car(p, car, DRIVER)

    # ------------------------------------------------------------------ traps
    def _place_trap(self, p, kind):
        slot = GEAR_OF_TRAP[kind]
        if p.gear[slot] <= 0:
            return
        if sum(1 for t in self.traps.values() if t.kind != TRAP_SMOKE) >= C.MAX_TRAPS:
            self.toast("TOO MANY TRAPS OUT ALREADY. THE CITY HAS LIMITS.", T_INFO)
            return
        # square to the street, and centred on the road it's dropped on
        ang = round(p.ang / (math.pi / 2)) * (math.pi / 2)
        dist = {TRAP_BANANA: C.BANANA_PLACE_DIST, TRAP_DONUT: C.DONUT_THROW_DIST,
                TRAP_WHOOPEE: C.BANANA_PLACE_DIST}.get(kind, C.TRAP_PLACE_DIST)
        x = p.x + math.cos(p.ang) * dist
        y = p.y + math.sin(p.ang) * dist
        if kind == TRAP_DONUT:
            # thrown: it lands where the street lets it
            d = self.map.ray_clear(p.x, p.y, p.ang, dist, step=0.25)
            x, y = p.x + math.cos(p.ang) * max(0.5, d - 0.5), p.y + math.sin(p.ang) * max(0.5, d - 0.5)
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
        if kind == TRAP_WHOOPEE:
            t.uses = C.WHOOPEE_USES
        if kind in (TRAP_BANANA, TRAP_DONUT):
            self._charge(p, "litter" if kind == TRAP_BANANA else "bribe")
        self._rebuild_trap_rects()
        self.sfx(S_TRAP, x, y)
        if kind == TRAP_SPIKES:
            self.toast("SPIKE STRIP DOWN. TYRES BEWARE.", T_INFO)
        elif kind == TRAP_BLOCK:
            self.toast("ROADBLOCK UP. NOBODY'S GETTING THROUGH HERE.", T_INFO)
        elif kind == TRAP_WHOOPEE:
            self.toast("WHOOPEE CUSHION DOWN. ACT NATURAL.", T_INFO)
        elif kind == TRAP_DONUT:
            t.uses = C.DONUT_COPS
            self.sfx(S_WHOOSH, p.x, p.y)
            self.toast("A BOX OF DONUTS LANDS IN THE STREET. SOMEWHERE, A SIREN SLOWS DOWN.", T_INFO)

    def fixtures(self):
        """The trap-shaped bits of the map (the precinct gate, the cell doors, the shop's
        five doors): solid when shut, sent as TRAP rows, never towed. The wall between the
        doors is ordinary map geometry (mapgen._make_shop), not a fixture."""
        out = []
        g = getattr(self, "gate_trap", None)
        if g is not None:
            out.append(g)
        out.extend(getattr(self, "cell_traps", ()))
        out.extend(getattr(self, "shop_doors", ()))
        return out

    def _rebuild_trap_rects(self):
        self.extra_rects = [t.rect() for t in self.traps.values() if t.solid()]
        self.tall_rects = [t.rect() for t in self.fixtures() if t.solid()]
        self.extra_rects.extend(self.tall_rects)

    def _update_traps(self, dt):
        if not self.traps:
            return
        dead = []
        for t in self.traps.values():
            t.age += dt
            if t.kind == TRAP_SMOKE:
                if t.age > C.SMOKE_SCREEN_LIFE:
                    dead.append(t.id)
                continue
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
                        wx, wy = car.to_world(*car.anchor(w))
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
            elif t.kind == TRAP_BANANA:
                if self._banana(t):
                    dead.append(t.id)
            elif t.kind == TRAP_DONUT:
                if t.uses <= 0:
                    dead.append(t.id)
            elif t.kind == TRAP_WHOOPEE:
                if self._whoopee(t):
                    dead.append(t.id)
            else:
                # anything that ploughs into a roadblock hard enough turns it into kindling
                for car in self.cars.values():
                    if car.impact_dv >= C.ROADBLOCK_BREAK_DV and obb_rect_contact(
                            car.x, car.y, car.ang, (rx - 0.3, ry - 0.3, rw + 0.6, rh + 0.6), car.hl, car.hw):
                        dead.append(t.id)
                        self.sfx(S_CRASH_BIG, t.x, t.y)
                        self.toast("THE ROADBLOCK IS NOW MATCHSTICKS", T_INFO)
                        break
        if dead:
            solid = any(self.traps[tid].solid() for tid in dead if tid in self.traps)
            for tid in dead:
                self.traps.pop(tid, None)
            if solid:
                self._rebuild_trap_rects()

    def _whoopee(self, t):
        """(v0.9) A whoopee cushion. Returns True when it's worn out. Anyone who treads
        on it: PFFFFT. Everyone who hears it: helpless. Coppers included."""
        r = C.WHOOPEE_R + 0.3
        who = None
        for p in self.players.values():
            if p.state == FOOT and p.z < 0.3 and (p.x - t.x) ** 2 + (p.y - t.y) ** 2 < r * r:
                who = p
                break
        if who is None:
            for n in self.npcs.values():
                if n.tumble_t <= 0 and n.carried_by is None and n.kind != CHICKEN and \
                        (n.x - t.x) ** 2 + (n.y - t.y) ** 2 < r * r:
                    who = n
                    break
        if who is None:
            t.hit.clear()                                  # (off it: it can go again)
            return False
        if who.id in t.hit:
            return False                                   # (still stood on it: one parp per visit)
        t.hit.add(who.id)
        t.uses -= 1
        self.sfx(S_PFFT, t.x, t.y)
        r2 = C.WHOOPEE_LAUGH_R ** 2
        laughed = 0
        for n in self.npcs.values():
            if n is who or n.kind in (DOG, CHICKEN) or n.tumble_t > 0 or n.carried_by is not None:
                continue
            if (n.x - t.x) ** 2 + (n.y - t.y) ** 2 < r2:
                n.laugh_t = C.WHOOPEE_LAUGH_TIME
                n.hostile_t = 0.0 if n.kind not in (GUARD, KEYGUARD) else n.hostile_t
                laughed += 1
        name = who.name if isinstance(who, Player) else ("AN OFFICER" if who.kind == OFFICER else
                                                          "A GUARD" if who.kind in (GUARD, KEYGUARD) else
                                                          "THE MIME (SILENTLY)" if who.kind == MIME else "SOMEBODY")
        self.toast(self.rng.choice(WHOOPEE_LINES) % name + (" (%d PEOPLE LOST IT)" % laughed if laughed > 1 else ""),
                   T_WHITE)
        return t.uses <= 0

    def _banana(self, t):
        """A banana peel on the road. Returns True once somebody's found it."""
        r = C.BANANA_R
        for car in self.cars.values():
            if car.speed() < 3 or abs(car.x - t.x) > car.bound + r or abs(car.y - t.y) > car.bound + r:
                continue
            if box_distance(car, t.x, t.y) < r:
                car.spin_t = C.BANANA_SPIN_TIME
                car.w += C.BANANA_SPIN_KICK * self.rng.choice((-1, 1))
                self.sfx(S_SLIP, t.x, t.y)
                self.toast("SKRRRRT! %s" % ("A COP CAR HIT A BANANA PEEL. JUSTICE IS BLIND."
                                           if car.kind == COP else "BANANA PEEL. OLDEST TRICK IN THE BOOK."), T_INFO)
                return True
        for p in self.players.values():
            if p.state == FOOT and p.z < 0.3 and (p.x - t.x) ** 2 + (p.y - t.y) ** 2 < (r + 0.3) ** 2 \
                    and math.hypot(p.vx, p.vy) > 1.0:
                self._hurt_player(p, p.vx * 0.8, p.vy * 0.8, C.BANANA_SLIP_TUMBLE, BN_HUMBLED, vz=3.0)
                self.sfx(S_SLIP, t.x, t.y)
                self.toast("%s SLIPPED ON A BANANA PEEL. A CLASSIC." % p.name, T_WHITE)
                return True
        for n in self.npcs.values():
            if n.tumble_t <= 0 and n.carried_by is None and (n.x - t.x) ** 2 + (n.y - t.y) ** 2 < (r + 0.3) ** 2 \
                    and math.hypot(n.vx, n.vy) > 0.5:
                self._knock_down_npc(n, n.vx, n.vy, C.BANANA_SLIP_TUMBLE * 1.5, vz=3.0)
                self.sfx(S_SLIP, t.x, t.y)
                if n.complain_cd <= 0:
                    n.complain_cd = 3.0
                    self.toast("PEDESTRIAN: WHO LEAVES A BANANA ON THE SIDEWALK?!", T_WHITE)
                return True
        return False

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
        cop.gun_cd -= dt
        if cop.fire_t > 0:
            cop.throttle, cop.steer, cop.handbrake = 0.0, 0.0, False
            return
        if cop.confused_t > 0:
            # donuts. Professional, taxpayer-funded donuts.
            cop.throttle, cop.steer, cop.handbrake = 0.8, 1.0, True
            return
        if cop.donut_t > 0:
            # actual donuts. Do not disturb.
            cop.donut_t -= dt
            vf = cop.vx * math.cos(cop.ang) + cop.vy * math.sin(cop.ang)
            cop.throttle, cop.steer, cop.handbrake = (-1.0 if vf > 0.5 else 0.0), 0.0, True
            return
        if cop.officer is not None:
            if cop.officer not in self.npcs:
                cop.officer = None
            else:
                # parked up, door open, lights going, while the officer does the running
                vf = cop.vx * math.cos(cop.ang) + cop.vy * math.sin(cop.ang)
                cop.throttle, cop.steer, cop.handbrake = (-1.0 if vf > 0.5 else 0.0), 0.0, True
                return
        spd = cop.speed()
        box = self._donut_for(cop)
        if box is not None:
            d = math.hypot(box.x - cop.x, box.y - cop.y)
            if d < 4.5 and spd < 4.0:
                cop.donut_t = C.DONUT_EAT_TIME
                box.uses -= 1
                self.sfx(S_MUNCH, cop.x, cop.y)
                self.toast("A COP PULLED OVER FOR DONUTS. OFFICER IS ON A BREAK.", T_COP)
                return
            target = (box.x, box.y, 0.0, 0.0, False, box)
        else:
            target = None
            bd = 1e9
            for t in self.targets:
                d = math.hypot(t[0] - cop.x, t[1] - cop.y)
                if d < bd:
                    target, bd = t, d
            nude = self._streaker_near(cop.x, cop.y)
            if nude is not None and not cop.patrol:
                # a naked man is running through town. Priorities.
                target, bd = (nude.x, nude.y, nude.vx, nude.vy, False, nude), math.hypot(nude.x - cop.x,
                                                                                        nude.y - cop.y)
            if cop.patrol:
                seen = target is not None and self.heat > 0 and bd < C.WITNESS_RANGE_COP and \
                    self.los(cop.x, cop.y, target[0], target[1])
                if not seen:
                    self._traffic_ai(cop, dt)      # just doing laps. Totally not looking for you.
                    return
                cop.patrol = False
                self.toast("A PATROL CAR SPOTTED YOU! LIGHTS ON!", T_COP)
            if target is not None and not target[4] and isinstance(target[5], Player) and bd < C.COP_GUN_RANGE \
                    and self.lethal_t > 0 and cop.gun_cd <= 0 and self.los(cop.x, cop.y, target[0], target[1]):
                cop.gun_cd = C.COP_GUN_COOLDOWN
                self._cop_shoot(cop, target[5], bd)
        # (v0.10, Bryce: "walls need to block cops views better - ray finding from cops view
        # when in pursuit mode") only trust a target's CURRENT position while this cop can
        # actually see it; lose sight and it drives to where it last saw you, then -- after
        # COP_TRACK_LOSE_TIME with nothing found -- gives up on that lead altogether, instead
        # of homing in on your exact live position through every wall in town forever.
        if target is not None and self.los(cop.x, cop.y, target[0], target[1]):
            cop.search_t = 0.0
            tx, ty, tvx, tvy, is_car = target[0], target[1], target[2], target[3], target[4]
            cop.last_target = (tx, ty)
        else:
            cop.search_t += dt
            if cop.search_t >= C.COP_TRACK_LOSE_TIME:
                cop.last_target = None
            if cop.last_target is None and cop.search_t >= C.COP_TRACK_LOSE_TIME + C.COP_TIP_DELAY:
                self._radio_tip(cop)                # (v0.12.1) dispatch: "try round the block"
            if cop.last_target is None:
                cop.throttle, cop.steer, cop.handbrake = 0.0, 0.0, False
                return
            tx, ty, tvx, tvy, is_car = cop.last_target[0], cop.last_target[1], 0.0, 0.0, True
        # stuck? back up with opposite lock, like a confused shopping trolley
        if cop.rev_t > 0:
            cop.rev_t -= dt
            cop.throttle, cop.handbrake = -1.0, False
            return
        d = math.hypot(tx - cop.x, ty - cop.y)
        if d < 32 and self.los(cop.x, cop.y, tx, ty):
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
            if d < 12 and abs(diff) > 1.3:
                # they're beside or behind us: three-point turn (back up with opposite lock)
                throttle = -0.8
                steer = -1.0 if diff > 0 else 1.0
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

    def _donut_for(self, cop):
        """The nearest box of donuts this cop can smell, if any."""
        best, bd = None, C.DONUT_LURE_RADIUS
        for t in self.traps.values():
            if t.kind == TRAP_DONUT and t.uses > 0:
                d = math.hypot(t.x - cop.x, t.y - cop.y)
                if d < bd:
                    best, bd = t, d
        return best

    def _cop_shoot(self, cop, q, d):
        """Lethal mode only (the crew started it): out of the window, to kill."""
        self._police_shot(cop.x, cop.y, q, d, C.COP_GUN_ACCURACY)

    def _patrol_fleet(self, dt):
        """PATROL_COPS cruisers are always somewhere nearby, doing laps."""
        beat = [c for c in self.cars.values() if c.kind == COP and c.beat]
        if self.players:
            for car in beat:
                if car.patrol and min(math.hypot(p.x - car.x, p.y - car.y)
                                      for p in self.players.values()) > C.PATROL_RECYCLE_DIST:
                    del self.cars[car.id]
                    beat.remove(car)
                    break
        if len(beat) >= self.patrol_target or not self.players:
            return
        self.patrol_t -= dt
        if self.patrol_t <= 0:
            self.patrol_t = 3.0
            car = self._spawn_traffic(kind=COP, dist=C.PATROL_SPAWN_DIST)
            if car is not None:
                car.patrol = car.beat = True

    def _back_on_patrol(self, car):
        """Heat's gone: a patrol unit rejoins the grid wherever it happens to be."""
        car.patrol = True
        car.last_target = None
        T = C.TILE_M
        i = int(round((car.x / T - C.ROAD_TILES / 2.0) / C.PITCH))
        j = int(round((car.y / T - C.ROAD_TILES / 2.0) / C.PITCH))
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        for d in sorted(DIRS, key=lambda d: -(d[0] * fx + d[1] * fy)):
            ni, nj = i + d[0], j + d[1]
            if self.map.node_ok(ni, nj):
                car.tdir, car.node = d, (ni, nj)
                car.route = [self._lane_point(ni, nj, d, -8.0)]
                car.route_prev = (car.x, car.y)
                return

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
                reach = a.bound + b.bound
                if abs(a.x - b.x) < reach and abs(a.y - b.y) < reach:
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
        if car.model == V.ARMOURED and nx * math.cos(car.ang) + ny * math.sin(car.ang) > 0.5:
            self._money_hit(car, 2)                   # (v0.9) rammed from behind: the back doors buckle
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
        ax, ay = car.anchor(slot)
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
        if p.state in (DRIVER, PASSENGER, CARRIED):
            return                     # (carried: _update_carries puts you on a shoulder)
        b = p.input.buttons
        if p.menu:
            b = 0                      # browsing spoilers, not walking
        if p.state == TUMBLE:
            p.tumble_t -= dt
            p.spin += p.spin_rate * dt
            p.spin_rate *= math.exp(-1.5 * dt)
            airborne = p.z > 0 or p.vz > 0
            if p.slide_t > 0:
                p.slide_t -= dt
            # no friction in the air; hit by a car, you skid along the tarmac for a while (v0.9)
            dec = math.exp((-0.3 if airborne else -C.CAR_HIT_SLIDE_DECAY if p.slide_t > 0 else -2.5) * dt)
            p.vx *= dec
            p.vy *= dec
            if airborne:
                self._fly_player(p, dt)
            if p.tumble_t <= 0 and p.z <= 0:
                p.state = FOOT
                p.spin = 0.0
                p.grace_t = C.GETUP_GRACE      # (v0.9) nobody decks you again while you find your feet
            p.moving = False
        elif p.state in (CUFFED, DEAD):
            p.vx = p.vy = 0.0
            p.moving = False
        else:
            self._walk(p, b, dt)
        p.x += p.vx * dt
        p.y += p.vy * dt
        self._body_vs_world(p, C.PLAYER_RADIUS)
        # cars vs people: bounce off slow cars, go ragdoll off fast ones
        if p.state not in (CUFFED, DEAD):
            hit = self._body_vs_cars(p, C.PLAYER_RADIUS)
            if hit is not None and p.state != TUMBLE:
                rel, cvx, cvy, nx, ny = hit
                if rel > C.BODY_HIT_SPEED:
                    self._drop_carry(p, throw=False)
                    kick = C.CAR_HIT_KICK + rel * C.CAR_HIT_KICK_PER
                    self._tumble(p, cvx * C.CAR_HIT_CARRY + nx * kick, cvy * C.CAR_HIT_CARRY + ny * kick,
                                 lerp(1.2, 2.8, clamp(rel / 30.0, 0, 1)))
                    p.slide_t = C.CAR_HIT_SLIDE_TIME
                    self.sfx(S_YELP, p.x, p.y)
                    if rel > C.YEET_SPEED:
                        p.vz = min(9.0, rel * 0.3)            # up and over the bonnet
                        p.z = 0.05
                        self._banner(p, BN_YEETED)

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
                    n.wallet = self._roll_wallet()   # payday
            if n.surrender_t > 0:
                n.surrender_t -= dt
                if n.surrender_t <= 0 and n.tumble_t <= 0:
                    # the gun's gone: run for it, away from wherever it was
                    self._flee(n, self.rng.uniform(-1, 1), self.rng.uniform(-1, 1))
            if n.kind in (PED, OFFICER, DOG):
                pass                      # (officers and dogs keep their own clocks)
            else:
                n.life_t += dt
                if n.kind == CLOWN and n.life_t > C.CLOWN_LIFETIME:
                    dead.append(n.id)     # poof. Back to the tiny car in the sky.
                    continue
            if n.carried_by is not None:
                continue                  # over somebody's shoulder, legs kicking (see _update_carries)
            airborne = n.z > 0 or n.vz > 0
            if airborne or n.thrown_by is not None:
                self._fly_npc(n, dt)
            if n.tumble_t > 0 or airborne:
                n.tumble_t = max(0.05, n.tumble_t - dt) if airborne else n.tumble_t - dt
                n.spin += dt * 12
                if n.slide_t > 0:
                    n.slide_t -= dt
                dec = math.exp((-0.3 if airborne else -C.CAR_HIT_SLIDE_DECAY if n.slide_t > 0 else -2.5) * dt)
                n.vx *= dec
                n.vy *= dec
            elif n.laugh_t > 0 and n.kind in (OFFICER, GUARD, KEYGUARD):
                n.laugh_t -= dt           # (v0.9) the whoopee cushion: even the law has to laugh
                n.vx = n.vy = 0.0
            elif n.kind == OFFICER:
                if not self._officer(n, dt):
                    dead.append(n.id)
                    continue
            elif n.kind == CHICKEN:
                self._chicken(n, dt)
            elif n.kind == MIME:
                self._mime(n, dt)
            elif n.kind in (GUARD, KEYGUARD):
                self._guard(n, dt)
            elif n.kind == DOG:
                if not self._dog(n, dt):
                    dead.append(n.id)
                    continue
            elif n.kind == STREAKER:
                self._streaker(n, dt)
            elif n.surrender_t > 0:
                n.vx = n.vy = 0.0         # frozen, hands up, reconsidering their life choices
            elif n.hostile_t > 0 and self._brawler(n, dt):
                n.spin = 0.0              # coming for you
            elif n.laugh_t > 0:
                n.laugh_t -= dt           # pointing and laughing at your dance
                n.vx = n.vy = 0.0
            elif n.kind == PED and n.flee_t > 0:
                n.flee_t -= dt
                n.vx, n.vy = self._flee_velocity(n)
                n.spin = 0.0
                if n.flee_t <= 0:
                    n.turn_t = 0.0        # pick a fresh stroll direction
            elif n.kind == PED and n.lure is not None:
                lx, ly = n.lure
                dx, dy = lx - n.x, ly - n.y
                d = math.hypot(dx, dy) or 1.0
                n.vx, n.vy = ((dx / d * C.PED_SPEED, dy / d * C.PED_SPEED) if d > 3.5 else (0.0, 0.0))
                n.spin = 0.0
                n.turn_t -= dt
                if n.turn_t <= 0:
                    n.turn_t = 1.0
                    self._icecream_lure(n)
            elif n.kind == PED:
                n.turn_t -= dt
                if int(n.turn_t * 4) != int((n.turn_t + dt) * 4):
                    self._icecream_lure(n)               # (~4 times a second, cheaply)
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
            if n.kind == CHICKEN and hit is not None and hit[0] > 3.0:
                self._chicken_splat(n)     # feathers. Everywhere.
                dead.append(n.id)
                continue
            if hit is not None and hit[0] > C.BODY_HIT_SPEED and n.tumble_t <= 0.3:
                rel, cvx, cvy, nx, ny = hit
                n.tumble_t = C.PED_TUMBLE
                kick = C.CAR_HIT_KICK + rel * C.CAR_HIT_KICK_PER
                n.vx, n.vy = cvx * C.CAR_HIT_CARRY + nx * kick, cvy * C.CAR_HIT_CARRY + ny * kick
                n.slide_t = C.CAR_HIT_SLIDE_TIME
                if rel > C.YEET_SPEED:
                    n.vz, n.z = min(9.0, rel * 0.3), 0.05       # (pedestrians get yeeted too)
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
        self._fly_pickups(dt)
        self.gnome_t -= dt
        if self.gnome_t <= 0:
            self.gnome_t = C.GNOME_RESPAWN
            if sum(1 for q in self.pickups.values() if q.fixed) < C.GNOME_COUNT:
                self._spawn_gnome()
        dead = []
        m = self.map
        for pk in self.pickups.values():
            if pk.fixed:
                continue                  # garden gnomes are forever (until stolen)
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
        self._spill_trunk(car, speed=9.0)
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
        self._quest_on_deliver(car, car.driver, car.passenger, self.heat)  # before heat resets below
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
        self.sfx(S_CONFETTI, car.x, car.y)           # (v0.8) the crew deserves a little party
        self.toast("DELIVERED! HEAT CLEARED. STRIP IT FOR PARTS.", T_MONEY)
        if self.civ_respawn_t is None:
            self.civ_respawn_t = C.CIV_RESPAWN_DELAY

    # ------------------------------------------------------------------ heat & witnesses
    def _collect_targets(self):
        t = []
        for car in self.cars.values():
            if car.wanted():
                t.append((car.x, car.y, car.vx, car.vy, True, car))
        for p in self.players.values():
            wanted = self.heat > 0 or (p.jumpsuit and C.JUMPSUIT_WITNESS)   # (orange: wanted on sight)
            if wanted and p.state in (FOOT, TUMBLE) and not p.jailed and not self.map.in_garage(p.x, p.y) \
                    and not p.hidden():                                   # (v0.9) it's just a box
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
                            (not isc and r.id in self.players and r.state in (FOOT, TUMBLE) and not r.jailed)]
        if self.witness_rate > 0:
            self.heat = min(C.HEAT_MAX, self.heat + self.witness_rate * dt)
        if self.witness_rate > 0 or self.witness != W_NONE:
            self.unseen_t = 0.0        # (v0.10) a ped clocking you pauses the cooldown even
        else:                          # before their call lands -- you're still rattled, not safe
            self.unseen_t += dt
            if self.unseen_t >= C.HEAT_COOL_DELAY:
                self.heat = max(0.0, self.heat - C.HEAT_COOL_RATE * dt)
        self._phone_ins(dt)
        self._garage_safehouse()

    def _phone_ins(self, dt):
        """(v0.10, Bryce: "kill civilians to make sure no witness remains, only tells
        cops after 10-15 seconds by phoning them") a ped or owner who clocks you doesn't
        key up a radio like a cop -- they bolt and call it in later. _witness_scan starts
        the clock the moment one gets a look at you; this ticks it down and drops the
        heat in one lump when the call goes through. The countdown lives on the NPC, so
        killing them (they leave self.npcs) silences the call for good."""
        for n in self.npcs.values():
            if n.call_t > 0:
                n.call_t -= dt
                if n.call_t <= 0:
                    n.call_t = 0.0
                    self.heat = min(C.HEAT_MAX, self.heat + C.PHONE_IN_HEAT)
                    self.unseen_t = 0.0
                    for cop in self.cars.values():      # (v0.12.1) and the call gives them a lead
                        if cop.kind == COP and not cop.patrol and cop.last_target is None:
                            self._radio_tip(cop)

    def _garage_safehouse(self):
        """(v0.10, Bryce: "in the garage, cops still see us with the doors close") the LOS
        through a shut door was already solid -- but heat only ever COOLS at HEAT_COOL_RATE,
        so units already dispatched keep loitering outside for a while even once nobody can
        actually see or reach you. If the WHOLE crew (and anything any of you are driving) is
        sealed inside with the door down, that's a hideout, not just "unseen for now": heat
        clears the same way it does on delivery. One player still out there wanted (even a
        teammate elsewhere in the city) means no free pass -- heat is shared."""
        if self.heat <= 0 or not self.door_shut() or not self.players:
            return
        for p in self.players.values():
            if p.state in (FOOT, TUMBLE):
                if not self.map.in_garage(p.x, p.y):
                    return
            elif p.state in (DRIVER, PASSENGER):
                car = self.cars.get(p.car_id)
                if car is None or not self.map.in_garage(car.x, car.y):
                    return
        self.heat = 0.0
        self.dispatched = False
        self.unseen_t = 0.0
        self.witness, self.witness_rate = W_NONE, 0.0

    def _witness_scan(self):
        """Highest single witness rate wins -- no stacking, so a crowd isn't
        worse than one nosy neighbour (the design doc is merciful)."""
        if not self.targets:
            return W_NONE, 0.0
        los = self.los
        if any(t.kind == TRAP_SMOKE for t in self.traps.values()):
            base_los = los
            los = lambda a, b, c, d: base_los(a, b, c, d) and not self._smoky(a, b, c, d)   # noqa: E731
        best_kind, best = W_NONE, 0.0
        cops = [c for c in self.cars.values() if c.kind == COP and c.fire_t <= 0 and c.donut_t <= 0
                and self._streaker_near(c.x, c.y) is None]            # (busy chasing a naked man)
        for cop in cops:
            for t in self.targets:
                dx, dy = t[0] - cop.x, t[1] - cop.y
                if dx * dx + dy * dy < C.WITNESS_RANGE_COP ** 2 and los(cop.x, cop.y, t[0], t[1]):
                    return W_COP, C.WITNESS_RATE_COP
        # (v0.10) an officer on foot, well clear of his car chasing you down, still counts as
        # a cop's eyes on you -- otherwise "lethal ends once no cop's watching" (LETHAL_UNSEEN_TIME)
        # would time out mid-chase just because his car was left behind.
        for n in self.npcs.values():
            if n.kind != OFFICER or n.mode == 4:
                continue
            for t in self.targets:
                dx, dy = t[0] - n.x, t[1] - n.y
                if dx * dx + dy * dy < C.WITNESS_RANGE_COP ** 2 and los(n.x, n.y, t[0], t[1]):
                    return W_COP, C.WITNESS_RATE_COP
        if self.heat >= C.HELI_HEAT and self.players:
            # (v0.10) the chopper: no wall occlusion (it's overhead), roughly over the crew
            hx = sum(p.x for p in self.players.values()) / len(self.players)
            hy = sum(p.y for p in self.players.values()) / len(self.players)
            r2h = C.HELI_RANGE ** 2
            for t in self.targets:
                if (t[0] - hx) ** 2 + (t[1] - hy) ** 2 < r2h:
                    return W_HELI, C.WITNESS_RATE_HELI
        r2o = C.WITNESS_RANGE_OWNER ** 2
        r2p = C.WITNESS_RANGE_PED ** 2
        for n in self.npcs.values():
            if n.tumble_t > 0 or n.kind in (CLOWN, STREAKER, CHICKEN, MIME) or n.kind in LAW or n.lure is not None or \
                    n.laugh_t > 0 or n.carried_by is not None:
                continue              # (queueing for ice cream / laughing at your dance / over your shoulder)
            r2 = r2o if n.kind == OWNER else r2p
            for t in self.targets:
                dx, dy = t[0] - n.x, t[1] - n.y
                if dx * dx + dy * dy < r2 and los(n.x, n.y, t[0], t[1]):
                    # (v0.10) they don't add heat live -- see _phone_ins. Once they've made
                    # up their mind to call they won't re-arm even if they lose you and
                    # spot you again; phoned just means "this witness is spent", not "safe".
                    if not n.phoned:
                        n.call_t = self.rng.uniform(*C.PHONE_IN_DELAY)
                        n.phoned = True
                    return (W_OWNER if n.kind == OWNER else W_PED), 0.0
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
        """A wanted level, GTA-style: more heat, more units (v0.7: up to 5, plus
        the patrols). Units keep coming until heat is 0, then go home -- or,
        if they're a patrol car, back to doing laps."""
        cops = [c for c in self.cars.values() if c.kind == COP]
        units = [c for c in cops if not c.beat]
        self.cop_spawn_t -= dt
        want = 0
        if self.heat > 0:
            for level, n in C.COP_TIERS:
                if self.heat >= level:
                    want = n
            want = max(want, self.wanted_level if self.dispatched else 0)
        if want > self.wanted_level:
            self.toast("WANTED LEVEL %d: %s" % (want, "DISPATCH IS SENDING UNITS" if want > 1 else
                                                "A CAR IS ON ITS WAY"), T_COP)
        self.wanted_level = want
        self.dispatched = want > 0
        # units come 2 s apart until there are enough for this heat -- unless dispatch has
        # already sent COPS_PER_DAY of them today (v0.10, Bryce: "limited number of cops
        # spawn / day"): units already out there keep chasing, there just aren't any more
        if want and len(units) < min(want, C.MAX_COPS) and self.cop_spawn_t <= 0 and \
                self.cops_today < C.COPS_PER_DAY:
            if self.spawn_cop():
                self.cop_spawn_t = C.COP_SPAWN_GAP
                self.cops_today += 1
        elif want and len(units) < min(want, C.MAX_COPS) and self.cops_today >= C.COPS_PER_DAY and \
                self.cop_spawn_t <= 0:
            self.cop_spawn_t = C.COP_SPAWN_GAP
            if not self.cops_exhausted_told:
                self.cops_exhausted_told = True
                self.toast("DISPATCH IS OUT OF CARS FOR TODAY. YOU'RE ON YOUR OWN, OFFICERS.", T_COP)
        if self.heat <= 0:
            self.heat_zero_t += dt
            calm = [c for c in cops if c.fire_t <= 0 and not c.patrol]
            if self.heat_zero_t >= C.COP_DESPAWN_AT_ZERO and calm:
                for c in calm:
                    if c.beat:
                        self._back_on_patrol(c)
                    else:
                        del self.cars[c.id]
                self.toast("THE COPS LOST INTEREST. DONUT BREAK.", T_COP)
        else:
            self.heat_zero_t = 0.0

    def arrest(self, p):
        """Cuffed (v0.8: by an officer on foot). A few seconds on the kerb for the
        mugshot, then the precinct lockup (see police.py)."""
        if p.state == CARRIED:
            self._free_carried_player(p)
        self._drop_carry(p, throw=False)
        self._drop_all(p)
        self._release_dolly(p)        # engine and all, right there for your partner
        if p.arms & ~1:
            self.toast("THE COPS KEPT %s'S GUNS" % p.name, T_COP)
        p.arms = 1 << ARM_FISTS       # guns: confiscated. Fists: they tried.
        p.ammo = [0] * ARM_COUNT
        p.weapon = ARM_FISTS
        p.state = CUFFED
        p.cuffed_t = C.CUFFED_TIME
        p.arrest_t = 0.0
        p.cuff_prog = 0.0
        p.wriggle = 0
        p.tumble_t = 0.0
        p.vx = p.vy = 0.0
        p.arrests += 1
        self._banner(p, BN_BUSTED)
        self.sfx(S_CUFF, p.x, p.y)
        self.sfx(S_ARREST, p.x, p.y)
        self.toast("%s GOT BUSTED! PARTS DROPPED AT THE SCENE." % p.name, T_COP)
        self._mugshot(p)
        self._quest_on_arrest(p)


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

    def _spawn_traffic(self, ignore_players=False, kind=TRAFFIC, dist=None):
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
                lo, hi = dist or (C.TRAFFIC_SPAWN_MIN_DIST, C.TRAFFIC_RECYCLE_DIST - 25.0)
                if near < lo or near > hi:
                    continue
            if any(abs(c.x - x) < 9.0 and abs(c.y - y) < 9.0 for c in self.cars.values()):
                continue
            if kind == COP:
                car = Car(self.new_id(), COP, x, y, math.atan2(d[1], d[0]), cop_loadout(self.rng))
            else:
                mid = V.pick_model(self.rng, traffic=True)
                if self.rng.random() < C.MONEY_TRUCK_CHANCE:
                    mid = V.ARMOURED                      # (v0.9) somebody's takings, on wheels
                car = Car(self.new_id(), TRAFFIC, x, y, math.atan2(d[1], d[0]), model_loadout(self.rng, mid),
                          color=self.rng.randrange(1, len(V.PAINT_NAMES)), model=mid)
                self._dress(car)
                if mid == V.ARMOURED:
                    self._money_truck(car)
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
        car_w = 1.4 if passing else car.hw + 1.1   # (two 2.4 m cars side by side need 2.4 to not touch)
        best, bf = None, look
        for other in self.cars.values():
            if other is car:
                continue
            dx, dy = other.x - car.x, other.y - car.y
            f = dx * fx + dy * fy
            if 0.5 < f < bf + other.hl:
                # oncoming cars only count if they're properly in our lane
                cosd = math.cos(other.ang - car.ang)
                w = 1.5 if cosd < -0.8 else car_w
                lat = abs(-dx * fy + dy * fx)
                if lat < w:
                    if other.kind == TRAFFIC and cosd < 0.87 and other.id > car.id and lat > 1.0:
                        continue      # right of way at junctions: lower id goes first, no standoffs
                    best, bf = other, f - other.hl     # their half-length (roughly: they may be turning)
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
        return best, bf - car.hl

    def _radio_tip(self, cop):
        """(v0.12.1) the dispatcher's best guess: roughly where the nearest wanted crook is,
        give or take COP_TIP_SCATTER. Not a wallhack -- the cop drives there and still has
        to actually SEE you (los) to lock on, and it's only ever as good as a phone call."""
        if not self.targets:
            return
        t = min(self.targets, key=lambda t: math.hypot(t[0] - cop.x, t[1] - cop.y))
        r = C.COP_TIP_SCATTER
        cop.last_target = (t[0] + self.rng.uniform(-r, r), t[1] + self.rng.uniform(-r, r))
        cop.search_t = 0.0

    def _traffic_ai(self, car, dt):
        fx, fy = math.cos(car.ang), math.sin(car.ang)
        vf = car.vx * fx + car.vy * fy
        spd = abs(vf)
        car.handbrake = False
        if car.fire_t > 0:
            car.throttle, car.steer = 0.0, 0.0
            return
        if car.missing_wheels() >= 2:
            if car.kind == TRAFFIC:
                self._traffic_bail(car)         # riding on rims: the driver's done
            else:
                car.throttle, car.steer = 0.0, 0.0   # a patrol car on rims: radioing for a tow
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
        x, y = car.to_world(0.0, -car.hw - 1.0)
        if self.map.solid_at(x, y):
            x, y = car.to_world(0.0, car.hw + 1.0)
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

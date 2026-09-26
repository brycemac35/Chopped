"""
sillies.py -- v0.9's silly department, as a mixin the World inherits. Bryce:
"add 10 more silly features". The host-side half lives here:

  * chickens cross the road near the crew. Why? Nobody knows. Hit one and
    it's feathers and a toast; punch one and it remembers.
  * mimes: trapped in invisible boxes on the pavement, pulling invisible
    ropes. Not witnesses (what would they say?). Their wallets are invisible.
  * stunt ramps in the car parks: hit one fast and you get BIG AIR and money
    from an appreciative crowd. (Cosmetic hang time: the physics stays on the
    ground so prediction doesn't have to learn to fly.)
  * money trucks in traffic: armoured vans. Shoot the back doors or ram them
    and cash bags fall out while the driver carries on, none the wiser.

The rest of the round (the rubber chicken, the whoopee cushion, the cardboard
box, nicking a cop car while the officer's out) is in sim.py where the
punching and the market already were, and the purely cosmetic bits (pigeons,
flying hats) are client-side in fp.py. No pygame.
"""

import math

from . import config as C
from .enums import *  # noqa: F401,F403
from .entities import NPC, Player
from .parts import Part
from .lines import CHICKEN_ROAD_LINES, CHICKEN_SPOT_LINES, MIME_LINES, MIME_BOX_LINE, MONEY_TRUCK_LINES, \
    BIG_AIR_LINES
from . import vehicles as V
from . import mapgen as M


class Sillies:
    def _init_sillies(self):
        self.chicken_t = self.rng.uniform(*C.CHICKEN_EVERY)
        self.mime_t = 0.0
        self.splat_cd = 0.0
        self.highfive_cd = 0.0          # (v0.12) shared cooldown: see Brawl._dance
        self.icecream_honk_cd = 0.0     # (v0.12) shared cooldown: see _honk_icecream
        self.air_total = {}             # car id -> (seconds of air it took off with, who was driving)

    def _sillies(self, dt):
        self.splat_cd -= dt
        self.highfive_cd -= dt
        self.icecream_honk_cd -= dt
        self._chickens(dt)
        self.mime_t -= dt
        if self.mime_t <= 0:
            self.mime_t = 5.0
            self._keep_mimes()
        self._ramps(dt)

    # ------------------------------------------------------------------ chickens
    def _chickens(self, dt):
        if not self.players:
            return
        self.chicken_t -= dt
        if self.chicken_t > 0:
            return
        self.chicken_t = self.rng.uniform(*C.CHICKEN_EVERY)
        if sum(1 for n in self.npcs.values() if n.kind == CHICKEN) >= C.CHICKEN_MAX:
            return
        p = self.rng.choice(list(self.players.values()))
        m = self.map
        T = C.TILE_M
        for _ in range(40):
            tx, ty = self.rng.choice(m.sidewalk_tiles)
            x, y = (tx + 0.5) * T, (ty + 0.5) * T
            if not 20.0 < math.hypot(x - p.x, y - p.y) < 60.0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                # a kerb with a whole road in front of it, and pavement on the far side
                if m.tile(tx + dx, ty + dy) == M.ROAD and m.tile(tx + dx * 4, ty + dy * 4) == M.SIDEWALK:
                    n = NPC(self.new_id(), CHICKEN, x, y)
                    n.dirx, n.diry = dx, dy
                    n.wallet = 0
                    n.ttl = (5 * T) / C.CHICKEN_SPEED + 3.0
                    self.npcs[n.id] = n
                    self.sfx(S_CLUCK, x, y)
                    if math.hypot(x - p.x, y - p.y) < 40.0:
                        self.toast(self.rng.choice(CHICKEN_SPOT_LINES), T_INFO)
                    return

    def _chicken(self, n, dt):
        """Straight across. No looking. That's the whole joke."""
        n.turn_t -= dt
        if n.turn_t <= 0:
            n.turn_t = self.rng.uniform(0.4, 1.2)
            n.mode = 1 if self.rng.random() < 0.25 else 0     # (stops to peck at something)
            if self.rng.random() < 0.2:
                self.sfx(S_CLUCK, n.x, n.y)
        if n.mode == 1:
            n.vx = n.vy = 0.0
        else:
            n.vx, n.vy = n.dirx * C.CHICKEN_SPEED, n.diry * C.CHICKEN_SPEED

    def _chicken_splat(self, n, car=None):
        self.sfx(S_FEATHERS, n.x, n.y)
        if self.splat_cd <= 0:
            self.splat_cd = 6.0
            self.toast(self.rng.choice(CHICKEN_ROAD_LINES), T_WHITE)

    # ------------------------------------------------------------------ mimes
    def _keep_mimes(self):
        have = sum(1 for n in self.npcs.values() if n.kind == MIME)
        if have >= C.MIME_COUNT or not self.map.sidewalk_tiles:
            return
        T = C.TILE_M
        for _ in range(30):
            tx, ty = self.rng.choice(self.map.sidewalk_tiles)
            x, y = (tx + 0.5) * T, (ty + 0.5) * T
            if all(math.hypot(x - p.x, y - p.y) > 45.0 for p in self.players.values()):
                n = NPC(self.new_id(), MIME, x, y)
                n.wallet = 1                    # (it's invisible. See _rob.)
                n.dirx, n.diry = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
                n.turn_t = self.rng.uniform(4, 9)
                self.npcs[n.id] = n
                return

    def _mime(self, n, dt):
        """Wanders the pavement very slowly; now and then gets trapped in an invisible box."""
        n.turn_t -= dt
        if n.mode == 1:
            n.vx = n.vy = 0.0
            n.surrender_t = max(n.surrender_t, 0.15)       # (the renderer draws the palms-flat pose)
            if n.turn_t <= 0:
                n.mode = 0
                n.turn_t = self.rng.uniform(5, 10)
        else:
            if n.turn_t <= 0:
                n.mode = 1
                n.turn_t = self.rng.uniform(3, 6)
            t = self.map.tile_at(n.x + n.dirx * 1.2, n.y + n.diry * 1.2)
            if t not in (M.SIDEWALK, M.GRASS):
                n.dirx, n.diry = -n.diry, n.dirx
            n.vx, n.vy = n.dirx * C.MIME_SPEED, n.diry * C.MIME_SPEED
        if n.complain_cd <= 0:
            for p in self.players.values():
                if p.state == FOOT and (p.x - n.x) ** 2 + (p.y - n.y) ** 2 < 9.0:
                    n.complain_cd = 25.0
                    self.toast(MIME_BOX_LINE if p.boxed else self.rng.choice(MIME_LINES), T_INFO)
                    break

    # ------------------------------------------------------------------ stunt ramps
    def _ramps(self, dt):
        for car in self.cars.values():
            if car.air_t > 0:
                car.air_t -= dt
                if car.air_t <= 0:
                    self._land(car)
                continue
            drv = self.players.get(car.driver) if car.driver is not None else None
            if drv is None:
                continue
            for (x, y, ang) in self.map.ramps:
                if abs(car.x - x) > C.RAMP_LEN or abs(car.y - y) > C.RAMP_LEN:
                    continue
                ca, sa = math.cos(ang), math.sin(ang)
                along = (car.x - x) * ca + (car.y - y) * sa
                side = -(car.x - x) * sa + (car.y - y) * ca
                v = car.vx * ca + car.vy * sa
                if abs(along) < C.RAMP_LEN / 2 and abs(side) < C.RAMP_W / 2 + 0.3 and v >= C.RAMP_MIN_SPEED:
                    car.air_t = v * C.RAMP_AIR_PER_MS
                    self.air_total[car.id] = (car.air_t, drv.id)
                    self.sfx(S_WHOOSH, car.x, car.y)
                    break

    def _land(self, car):
        t, pid = self.air_total.pop(car.id, (0.0, None))
        self.sfx(S_CRASH, car.x, car.y)
        drv = self.players.get(pid)                   # (whoever launched it: sticking the landing is optional)
        if drv is None or t <= 0:
            return
        pay = int(t * C.RAMP_BONUS_PER_S)
        self._earn(pay)
        drv.banner, drv.banner_t = BN_BIGAIR, 2.0
        self.toast(self.rng.choice(BIG_AIR_LINES) % (t, pay), T_MONEY)

    # ------------------------------------------------------------------ money trucks
    def _money_truck(self, car):
        """Dress a fresh traffic car as an armoured van (with the day's takings in the back)."""
        car.color = 9                            # silver-grey: the colour of other people's money
        car.livery = 0
        car.trunk = [Part("cash_bag", 1.0) for _ in range(3)]

    def _money_hit(self, car, n=1):
        if car.model != V.ARMOURED or car.burst:
            return
        car.cash_hits += n
        if car.cash_hits < C.MONEY_TRUCK_HITS:
            self.sfx(S_GATE, car.x, car.y)               # KLANG
            return
        car.burst = True
        c, s = math.cos(car.ang), math.sin(car.ang)
        bx, by = car.x - c * (car.hl + 0.6), car.y - s * (car.hl + 0.6)
        bags = list(car.trunk)
        car.trunk = []
        extra = self.rng.randint(*C.MONEY_TRUCK_BAGS) - len(bags)
        bags.extend(Part("cash_bag", 1.0) for _ in range(max(0, extra)))
        for k, part in enumerate(bags):
            a = car.ang + math.pi + self.rng.uniform(-0.7, 0.7)
            sp = self.rng.uniform(3.0, 7.0)
            self.add_pickup(part, bx + self.rng.uniform(-0.6, 0.6), by + self.rng.uniform(-0.6, 0.6),
                            car.vx * 0.5 + math.cos(a) * sp, car.vy * 0.5 + math.sin(a) * sp)
        self._crime(C.MONEY_TRUCK_HEAT)
        self.sfx(S_CASH, bx, by)
        self.toast(self.rng.choice(MONEY_TRUCK_LINES), T_MONEY)

    # ------------------------------------------------------------------ ice cream jingle
    def _honk_icecream(self, car):
        """(v0.12) honk near the ice cream van and it honks back. It does not play its
        jingle for you -- that's reserved for people actually buying ice cream, apparently."""
        if self.icecream_honk_cd > 0:
            return
        for van in self.cars.values():
            if van.model == V.ICECREAM and (van.x - car.x) ** 2 + (van.y - car.y) ** 2 < C.HORN_CONFUSE_RANGE ** 2:
                self.icecream_honk_cd = 4.0
                self.sfx(S_HONK, van.x, van.y)
                self.toast("THE ICE CREAM VAN HONKS BACK. IT DOES NOT PLAY ITS JINGLE FOR YOU.", T_WHITE)
                return

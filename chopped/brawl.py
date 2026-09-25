"""
brawl.py -- v0.7's slapstick department, as a mixin the World inherits:

  * throwing whatever's in your hands (a door at 16 m/s ends arguments)
  * picking people up (pedestrians, and your mates) and throwing THEM
  * human bowling: thrown people knock over whoever they land on
  * the haymaker: hold the punch, let go, watch them leave the postcode
  * the dance (T): it offends everyone, some of them violently
  * pedestrians who fight back -- with fists, and occasionally a pistol

Everything here is authoritative (host only) and pygame-free. Movement of
your OWN avatar still lives in physics.Physics so prediction stays exact;
this file only ever throws, tumbles or knocks people over, which the client
treats as "the host said so".
"""

import math

from . import config as C
from .enums import *  # noqa: F401,F403
from .entities import NPC, Player
from .lines import (BONK_LINES, BRAWL_LINES, HUMBLED_LINES, REFUND_LINES, LAUGH_LINES,
                    OFFENDED_LINES, HOMERUN_LINES, STRIKE_LINES, WRIGGLE_LINES)


class Brawl:
    # ------------------------------------------------------------------ banners
    def _banner(self, p, which):
        p.banner = which
        p.banner_t = C.BANNER_TIME

    # ------------------------------------------------------------------ getting hurt
    def _hurt_player(self, q, vx, vy, t, banner=BN_NONE, vz=0.0):
        """Knock a crook over: everything in their hands goes flying."""
        if q.state not in (FOOT, CARRIED):
            return False
        if q.state == CARRIED:
            self._free_carried_player(q)
        self._drop_carry(q, throw=False)
        self._drop_all(q)
        self._release_dolly(q)
        self._tumble(q, vx, vy, t)
        if vz:
            q.vz = max(q.vz, vz)
            q.z = max(q.z, 0.05)
        if banner:
            self._banner(q, banner)
        self.sfx(S_YELP, q.x, q.y)
        return True

    def _knock_down_npc(self, n, vx, vy, t, attacker=None, vz=0.0):
        if n.carried_by is not None:
            return
        n.tumble_t = max(n.tumble_t, t)
        n.vx, n.vy = vx, vy
        if vz:
            n.vz = max(n.vz, vz)
            n.z = max(n.z, 0.05)
        n.surrender_t = 0.0
        n.laugh_t = 0.0
        if n.hostile_t > 0:
            if self._npc_hold(n):
                n.brave = False                 # that's enough. They'll run when they get up.
                n.flee_t = C.PED_FLEE_TIME
        elif attacker is not None:
            self._provoke(n, attacker)

    # ------------------------------------------------------------------ fighting back
    def _provoke(self, n, p, witnesses=True):
        """Someone just did something to n. The brave ones remember."""
        if n.kind == CLOWN:
            return
        pid = p.id if isinstance(p, Player) else p
        if n.brave or n.kind == OWNER:
            if n.hostile_t <= 0 and n.complain_cd <= 0:
                n.complain_cd = 3.0
                self.toast(self.rng.choice(BRAWL_LINES), T_BAD)
            n.hostile_t = C.BRAWL_TIME
            n.foe = pid
            n.flee_t = 0.0
            if n.grit <= 0:
                n.grit = self.rng.randint(1, C.BRAWL_GRIT_MAX)
        elif n.tumble_t <= 0:
            self._flee(n, n.x - self.players[pid].x if pid in self.players else 1.0,
                       n.y - self.players[pid].y if pid in self.players else 0.0)
        if witnesses and pid in self.players:
            # have-a-go heroes nearby pile in
            q = self.players[pid]
            r2 = C.BRAWL_RALLY_RADIUS ** 2
            for m in self.npcs.values():
                if m is n or m.kind != PED or not m.brave or m.hostile_t > 0 or m.tumble_t > 0:
                    continue
                if (m.x - q.x) ** 2 + (m.y - q.y) ** 2 < r2 and self.rng.random() < C.BRAWL_RALLY_CHANCE:
                    m.hostile_t = C.BRAWL_TIME
                    m.foe = pid
                    m.flee_t = 0.0
                    m.grit = self.rng.randint(1, C.BRAWL_GRIT_MAX)

    def _brawler(self, n, dt):
        """A pedestrian with a grudge. Returns True if it drove n's movement."""
        q = self.players.get(n.foe)
        n.hostile_t -= dt
        if q is None or n.hostile_t <= 0 or q.state in (CUFFED,) or self.map.in_garage(q.x, q.y):
            n.hostile_t = 0.0
            n.foe = None
            return False
        if q.state in (DRIVER, PASSENGER):
            if n.kind == OWNER:
                return False           # owners go back to chasing their car
            # you got in a car. They stand in the road and shout, which is the most anyone can do.
            n.vx = n.vy = 0.0
            return True
        dx, dy = q.x - n.x, q.y - n.y
        d = math.hypot(dx, dy) or 1.0
        if d > C.BRAWL_GIVE_UP:
            n.hostile_t = 0.0
            n.foe = None
            return False
        n.attack_cd -= dt
        n.ang = math.atan2(dy, dx)
        if n.armed and d < C.PED_GUN_RANGE and self.map.los(n.x, n.y, q.x, q.y):
            n.vx = n.vy = 0.0
            if n.attack_cd <= 0:
                n.attack_cd = C.PED_GUN_COOLDOWN
                self._ped_shoot(n, q, d)
            return True
        if d > C.BRAWL_REACH:
            n.vx, n.vy = dx / d * C.BRAWL_SPEED, dy / d * C.BRAWL_SPEED
            return True
        n.vx = n.vy = 0.0
        if n.attack_cd <= 0 and q.state in (FOOT, TUMBLE) and q.z < 1.0:
            n.attack_cd = C.BRAWL_PUNCH_COOLDOWN
            self.sfx(S_PUNCH, q.x, q.y)
            if q.state == FOOT and self.rng.random() < C.BRAWL_HIT_CHANCE:
                self._hurt_player(q, dx / d * 6, dy / d * 6, C.BRAWL_PUNCH_TUMBLE, BN_HUMBLED)
                self.toast(self.rng.choice(HUMBLED_LINES) % q.name, T_BAD)
                took = q.robbed_from.pop(n.id, 0)
                if took:
                    # the one you robbed takes it back. Fair's fair.
                    self.cash -= took
                    n.wallet += took
                    self.toast(self.rng.choice(REFUND_LINES) % took, T_BAD)
        return True

    def _ped_shoot(self, n, q, d):
        """Armed pedestrians: not great shots, but they only need one."""
        a = math.atan2(q.y - n.y, q.x - n.x)
        self.sfx(S_PISTOL, n.x, n.y)
        hit = self.rng.random() < C.PED_GUN_ACCURACY and q.state == FOOT
        if hit:
            self.tracer(ARM_PISTOL, n.x, n.y, q.x, q.y)
            self._hurt_player(q, math.cos(a) * 7, math.sin(a) * 7, C.SHOT_PLAYER_TUMBLE, BN_HUMBLED)
            self.toast("A PEDESTRIAN SHOT %s. (A GRAZE. THE EGO, MOSTLY.)" % q.name, T_BAD)
        else:
            miss = a + self.rng.uniform(-0.25, 0.25)
            self.tracer(ARM_PISTOL, n.x, n.y, n.x + math.cos(miss) * (d + 6), n.y + math.sin(miss) * (d + 6))

    # ------------------------------------------------------------------ throwing things
    def _throw_part(self, p):
        """Click with something in your hands: it leaves them. Fast."""
        part = p.hands.pop()
        fx, fy = math.cos(p.ang), math.sin(p.ang)
        heavy = part.bulk >= 2
        spd = C.THROW_SPEED * (C.THROW_HEAVY_MULT if heavy else 1.0)
        pk = self.add_pickup(part, p.x + fx * 0.7, p.y + fy * 0.7, p.vx * 0.5 + fx * spd, p.vy * 0.5 + fy * spd)
        pk.z, pk.vz = 1.4, C.THROW_LIFT
        pk.thrower = p.id
        p.fire_cd = C.THROW_COOLDOWN
        self.sfx(S_WHOOSH, p.x, p.y)

    def _fly_pickups(self, dt):
        """Thrown parts in the air: gravity, and whoever they land on."""
        for pk in list(self.pickups.values()):
            if pk.z <= 0 and pk.vz == 0:
                continue
            pk.vz -= C.JUMP_GRAVITY * dt
            pk.z += pk.vz * dt
            if pk.z <= 0:
                pk.z, pk.vz = 0.0, 0.0
                pk.thrower = None
                continue
            if pk.z > 2.2:
                continue
            heavy = pk.part.bulk >= 2
            spd = math.hypot(pk.vx, pk.vy)
            if spd < 4:
                continue
            fx, fy = pk.vx / spd, pk.vy / spd
            for n in self.npcs.values():
                if n.id in pk.hit or n.carried_by is not None or n.z > 2.0:
                    continue
                if (n.x - pk.x) ** 2 + (n.y - pk.y) ** 2 < C.THROW_HIT_R ** 2:
                    pk.hit.add(n.id)
                    thrower = self.players.get(pk.thrower)
                    self._knock_down_npc(n, fx * 5, fy * 5, C.THROW_KNOCKDOWN * (1.4 if heavy else 1.0), thrower)
                    self._bonk(pk, n.x, n.y)
                    if thrower is not None:
                        self._crime(C.PUNCH_HEAT)
                    if n.complain_cd <= 0:
                        n.complain_cd = 3.0
                        self.toast(self.rng.choice(BONK_LINES), T_WHITE)
            for q in self.players.values():
                if q.id in pk.hit or (q.id == pk.thrower and pk.age < 0.4) or q.state != FOOT:
                    continue
                if (q.x - pk.x) ** 2 + (q.y - pk.y) ** 2 < C.THROW_HIT_R ** 2:
                    pk.hit.add(q.id)
                    self._hurt_player(q, fx * 5, fy * 5, C.THROW_PLAYER_TUMBLE, BN_BONKED)
                    self._bonk(pk, q.x, q.y)
            for car in self.cars.values():
                if car.kind == COP and car.id not in pk.hit and \
                        (car.x - pk.x) ** 2 + (car.y - pk.y) ** 2 < (car.hw + 0.5) ** 2:
                    pk.hit.add(car.id)
                    self._bonk(pk, pk.x, pk.y)
                    self._crime(C.PUNCH_HEAT)
                    self.toast("YOU THREW A %s AT A POLICE CAR. BOLD." % pk.part.name.upper(), T_COP)

    def _bonk(self, pk, x, y):
        self.sfx(S_GNOME if pk.part.type_id == "gnome" else S_BONK, x, y)
        pk.part.condition = max(0.0, pk.part.condition - C.THROW_WEAR)
        pk.vx *= -0.3
        pk.vy *= -0.3

    # ------------------------------------------------------------------ picking people up
    def _grab_target(self, p):
        """A person you could pick up from here: someone on the floor, someone
        with their hands up, or any crewmate who's standing still enough."""
        ax, ay = self._aim(p)
        best, bd = None, C.GRAB_RANGE
        for n in self.npcs.values():
            if n.carried_by is not None or n.z > 0.5:
                continue
            if n.tumble_t > 0 or n.surrender_t > 0 or n.laugh_t > 0:
                d = math.hypot(n.x - ax, n.y - ay)
                if d < bd:
                    best, bd = n, d
        for q in self.players.values():
            if q is p or q.state not in (FOOT, TUMBLE) or q.carrying is not None or q.z > 0.5:
                continue
            d = math.hypot(q.x - ax, q.y - ay)
            if d < bd:
                best, bd = q, d
        return best

    def _grab(self, p, target):
        if p.hands or p.dolly is not None or p.carrying is not None:
            return
        if isinstance(target, NPC):
            if target.id not in self.npcs or target.carried_by is not None:
                return
            target.carried_by = p.id
            target.struggle_t = C.CARRY_STRUGGLE
            target.tumble_t = max(target.tumble_t, 1.0)
            target.surrender_t = 0.0
            target.flee_t = 0.0
            p.carrying = ("npc", target.id)
            self._provoke(target, p, witnesses=False)
            self.toast("%s PICKED UP A STRANGER. THEY HAVE QUESTIONS." % p.name, T_WHITE)
        else:
            if target.state not in (FOOT, TUMBLE):
                return
            self._drop_all(target)
            self._release_dolly(target)
            self._drop_carry(target, throw=False)
            target.state = CARRIED
            target.carrier = p.id
            target.wriggle = 0
            target.tumble_t = 0.0
            p.carrying = ("player", target.id)
            self.toast("%s HOISTED %s ONTO A SHOULDER" % (p.name, target.name), T_INFO)
        self.sfx(S_PICKUP, p.x, p.y)

    def _carried_ref(self, p):
        if p.carrying is None:
            return None
        kind, ref = p.carrying
        if kind == "npc":
            n = self.npcs.get(ref)
            return n if (n is not None and n.carried_by == p.id) else None
        q = self.players.get(ref)
        return q if (q is not None and q.state == CARRIED and q.carrier == p.id) else None

    def _drop_carry(self, p, throw=False):
        """Put them down (G) or launch them (click)."""
        who = self._carried_ref(p)
        p.carrying = None
        if who is None:
            return
        fx, fy = math.cos(p.ang), math.sin(p.ang)
        if throw:
            spd = C.THROW_PERSON_SPEED
            vx, vy, vz = p.vx * 0.5 + fx * spd, p.vy * 0.5 + fy * spd, C.THROW_PERSON_LIFT
            self.sfx(S_WHOOSH, p.x, p.y)
        else:
            vx, vy, vz = fx * 1.5, fy * 1.5, 0.0
        x, y = p.x + fx * 0.8, p.y + fy * 0.8
        if self.map.solid_at(x, y):
            x, y = p.x, p.y
        if isinstance(who, NPC):
            who.carried_by = None
            who.x, who.y = x, y
            who.z = 1.3 if throw else 0.0
            who.vz = vz
            who.vx, who.vy = vx, vy
            who.tumble_t = max(who.tumble_t, C.THROWN_TUMBLE if throw else 1.0)
            who.thrown_by = p.id if throw else None
            who.bowled = 0
            if throw:
                self._crime(C.PUNCH_HEAT)
        else:
            who.state = FOOT
            who.carrier = None
            who.x, who.y = x, y
            if throw:
                who.z = 1.3
                self._tumble(who, vx, vy, C.THROWN_TUMBLE)
                who.vz = vz
                self._banner(who, BN_YEETED)
                self.toast("%s THREW %s. FRIENDSHIP: OVER." % (p.name, who.name), T_WHITE)

    def _free_carried_player(self, q):
        carrier = self.players.get(q.carrier)
        if carrier is not None and carrier.carrying == ("player", q.id):
            carrier.carrying = None
        q.state = FOOT
        q.carrier = None

    def _update_carries(self, dt):
        """Carried people ride your shoulder. Pedestrians struggle free after a
        while; crewmates can wriggle (mash Space)."""
        for p in self.players.values():
            if p.carrying is None:
                continue
            who = self._carried_ref(p)
            if who is None or p.state != FOOT:
                self._drop_carry(p, throw=False)
                continue
            fx, fy = math.cos(p.ang), math.sin(p.ang)
            who.x, who.y = p.x - fy * 0.35, p.y + fx * 0.35
            who.vx, who.vy = p.vx, p.vy
            if isinstance(who, NPC):
                who.z = 1.25
                who.tumble_t = max(who.tumble_t, 0.5)
                who.struggle_t -= dt
                if who.struggle_t <= 0:
                    self._drop_carry(p, throw=False)
                    who.tumble_t = 0.3
                    self.toast(self.rng.choice(WRIGGLE_LINES), T_WHITE)
                    self.sfx(S_WRIGGLE, who.x, who.y)
            else:
                who.z = 1.25
                who.ang = p.ang

    def _wriggle(self, q):
        """CARRIED crewmate pressed jump: enough of those and they're free."""
        q.wriggle += 1
        self.sfx(S_WRIGGLE, q.x, q.y)
        if q.wriggle >= C.WRIGGLE_PRESSES:
            carrier = self.players.get(q.carrier)
            if carrier is not None:
                self._drop_carry(carrier, throw=False)
            else:
                self._free_carried_player(q)
            q.z = 0.0
            self.toast("%s WRIGGLED FREE. DIGNITY: PARTIALLY RESTORED." % q.name, T_INFO)

    # ------------------------------------------------------------------ flying people (bowling)
    def _fly_npc(self, n, dt):
        """Gravity for a thrown or launched pedestrian; knock down whoever they
        hit -- in the air, and while they skid along the ground afterwards."""
        if n.z > 0 or n.vz > 0:
            self._fall(n, dt)
        spd = math.hypot(n.vx, n.vy)
        if n.z <= 0 and spd < 4:
            if n.thrown_by is not None and n.bowled >= C.STRIKE_COUNT:
                self._strike(n.thrown_by, n.bowled)
            n.thrown_by = None
            return
        if n.z > 2.0 or spd < 4:
            return
        for m in self.npcs.values():
            if m is n or m.tumble_t > 0 or m.carried_by is not None:
                continue
            if (m.x - n.x) ** 2 + (m.y - n.y) ** 2 < C.BOWL_R ** 2:
                thrower = self.players.get(n.thrown_by)
                self._knock_down_npc(m, n.vx * 0.6, n.vy * 0.6, C.PUNCH_KNOCKDOWN, thrower)
                n.bowled += 1
                self.sfx(S_BONK, m.x, m.y)
        for q in self.players.values():
            if q.state == FOOT and q.id != n.thrown_by and (q.x - n.x) ** 2 + (q.y - n.y) ** 2 < C.BOWL_R ** 2:
                self._hurt_player(q, n.vx * 0.6, n.vy * 0.6, C.THROW_PLAYER_TUMBLE, BN_BONKED)

    def _fly_player(self, p, dt):
        """Players in the air (thrown, ejected, haymakered): gravity and bowling."""
        self._fall(p, dt, chute=p.chute)
        if p.z <= 0:
            if p.chute:
                p.chute = False
                self.toast("%s LANDED. THE PARACHUTE IS NOW A CAPE." % p.name, T_INFO)
            return
        spd = math.hypot(p.vx, p.vy)
        if spd < 4 or p.z > 2.0:
            return
        for m in self.npcs.values():
            if m.tumble_t > 0 or m.carried_by is not None:
                continue
            if (m.x - p.x) ** 2 + (m.y - p.y) ** 2 < C.BOWL_R ** 2:
                self._knock_down_npc(m, p.vx * 0.6, p.vy * 0.6, C.PUNCH_KNOCKDOWN)
                self.sfx(S_BONK, m.x, m.y)

    def _strike(self, pid, count):
        p = self.players.get(pid)
        if p is None:
            return
        self._banner(p, BN_STRIKE)
        self.sfx(S_STRIKE, p.x, p.y)
        self.toast(self.rng.choice(STRIKE_LINES) % (p.name, count), T_MONEY)

    # ------------------------------------------------------------------ the haymaker
    def _charge_fists(self, p, held, dt):
        """Hold the punch to wind up; let go to unleash. Returns True if it fired."""
        if held:
            p.charge_t += dt
            return False
        fired = False
        if p.charge_t >= C.HAYMAKER_CHARGE:
            self._haymaker(p)
            fired = True
        p.charge_t = 0.0
        return fired

    def _haymaker(self, p):
        best, bd = None, None
        for n in self.npcs.values():
            d = self._in_front(p, n.x, n.y, C.PUNCH_RANGE + 0.4, C.PUNCH_CONE)
            if d is not None and n.carried_by is None and (bd is None or d < bd):
                best, bd = n, d
        for q in self.players.values():
            if q is not p and q.state == FOOT:
                d = self._in_front(p, q.x, q.y, C.PUNCH_RANGE + 0.4, C.PUNCH_CONE)
                if d is not None and (bd is None or d < bd):
                    best, bd = q, d
        self.sfx(S_WHOOSH, p.x, p.y)
        p.fire_cd = C.PUNCH_COOLDOWN * 2
        if best is None:
            return
        fx, fy = math.cos(p.ang), math.sin(p.ang)
        v = C.HAYMAKER_SPEED
        self.sfx(S_HOMERUN, best.x, best.y)
        if isinstance(best, Player):
            self._hurt_player(best, fx * v, fy * v, C.HAYMAKER_TUMBLE, BN_YEETED, vz=C.HAYMAKER_LIFT)
            self.toast("%s HAYMAKERED %s INTO NEXT WEEK" % (p.name, best.name), T_WHITE)
            return
        self._knock_down_npc(best, fx * v, fy * v, C.HAYMAKER_TUMBLE, p, vz=C.HAYMAKER_LIFT)
        best.thrown_by = p.id
        best.bowled = 0
        self._crime(C.PUNCH_HEAT)
        self._banner(p, BN_HOMERUN)
        self.toast(self.rng.choice(HOMERUN_LINES) % p.name, T_MONEY)

    # ------------------------------------------------------------------ the dance
    def _dance(self, p, dt):
        """Hold T. Peds nearby either laugh (and stop to watch: easy to rob)
        or take it personally. Cops take it very personally."""
        p.dancing = True
        if self.rng.random() > dt * 2.0:
            return                     # ~twice a second, somebody reacts
        r2 = C.DANCE_RADIUS ** 2
        for n in self.npcs.values():
            if n.kind != PED or n.tumble_t > 0 or n.hostile_t > 0 or n.carried_by is not None:
                continue
            if (n.x - p.x) ** 2 + (n.y - p.y) ** 2 > r2:
                continue
            if n.brave and self.rng.random() < C.DANCE_OFFEND_CHANCE:
                self._provoke(n, p, witnesses=False)
                self.toast(self.rng.choice(OFFENDED_LINES), T_BAD)
            elif n.laugh_t <= 0:
                n.laugh_t = C.DANCE_LAUGH_TIME
                n.flee_t = 0.0
                if self.rng.random() < 0.3:
                    self.toast(self.rng.choice(LAUGH_LINES), T_WHITE)
                    self.sfx(S_LAUGH, n.x, n.y)
            break
        for cop in self.cars.values():
            if cop.kind == COP and (cop.x - p.x) ** 2 + (cop.y - p.y) ** 2 < r2 * 2 and \
                    self.map.los(cop.x, cop.y, p.x, p.y):
                self._crime(C.DANCE_COP_HEAT)
                if self.rng.random() < 0.2:
                    self.toast("THE POLICE FIND YOUR DANCING OFFENSIVE. +HEAT", T_COP)
                break

    # ------------------------------------------------------------------ rolling brave peds
    def _roll_bravery(self, n):
        r = self.rng
        n.brave = r.random() < C.BRAVE_CHANCE
        n.armed = n.brave and r.random() < C.ARMED_CHANCE
        n.grit = r.randint(1, C.BRAWL_GRIT_MAX) if n.brave else 0

    @staticmethod
    def _npc_hold(n):
        """A brawler knocked down gets back up (grit permitting); returns True if
        they're done fighting."""
        n.grit -= 1
        if n.grit <= 0:
            n.hostile_t = 0.0
            n.foe = None
            return True
        return False


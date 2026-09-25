"""
police.py -- v0.8's long arm of the law, as a mixin the World inherits.

Bryce: "instead of the cops shooting you lethally right away have them try to
handcuff you. then you get taken to the precinct where you have to beat your
way out ... and make sure if the cops do decide to lethally shoot you that you
die, lose a/x % of your money depending on how many people are playing."

So:
  * cop cars chase; when one catches a crook on foot it pulls up and an
    OFFICER gets out and runs them down. Stand next to an officer for
    CUFF_TIME and you're cuffed. Punch him, or mash Space, to get loose.
  * from TASER_HEAT, officers tase you from a few metres (you twitch on the
    floor, which makes the cuffs quicker).
  * real bullets only once the crew starts shooting near cops (LETHAL_TIME).
    A police bullet means WASTED: the crew loses DEATH_LOSS / players of its
    cash and you wake up at the shop.
  * busted = the precinct lockup. Guards. One of them has the keys. Knock him
    down, take them, open the gate, run -- in an orange jumpsuit the whole city
    recognises, until you get back to the shop. Or a crewmate picks the lock
    from outside, rams the gate, or you pay bail at the front desk.

Plus the v0.8 silly department's police-flavoured half: K9 dogs that steal
your trousers, the streaker the cops would much rather chase, speed cameras
that post tickets to your own ride, burnout smoke you can hide in, and
hydraulics. No pygame, host-only.
"""

import math

from . import config as C
from .enums import *  # noqa: F401,F403
from .entities import NPC, Player, Trap
from .physics import obb_rect_contact
from .lines import (OFFICER_LINES, TASED_LINES, WASTED_LINES, PHONE_CALL_LINES, GUARD_LINES, BOXERS,
                    STREAKER_LINES, CHARGES)


class Police:
    # ------------------------------------------------------------------ setup
    def _init_police(self):
        self.lethal_t = 0.0             # > 0: the police are shooting to kill
        self.guard_idle_t = 0.0
        self.whistle_cd = 0.0
        self.streaker_t = self.rng.uniform(*C.STREAKER_EVERY)
        self.cam_cd = {}
        self.smoke_mark = {}            # car id -> smoke_t at its last smoke cloud
        self.smoke_told = False
        # the lockup gate: trap-shaped (a solid rect that goes over the wire as a TRAP row)
        # but it isn't anybody's trap, so it lives here rather than in self.traps
        self.gate_trap = None
        if self.map.gate is not None:
            gx, gy, ga = self.map.gate
            self.gate_trap = Trap(C.GATE_ID, TRAP_GATE, gx, gy, ga)
        self._rebuild_trap_rects()

    def gate(self):
        return self.gate_trap

    def _charge(self, p, crime):
        """Put it on the rap sheet (the mugshot reads it out)."""
        if isinstance(p, Player):
            p.rap[crime] = p.rap.get(crime, 0) + 1

    # ------------------------------------------------------------------ per tick
    def _police(self, dt):
        if self.lethal_t > 0:
            self.lethal_t -= dt
            if self.lethal_t <= 0:
                self.toast("THE POLICE HAVE HOLSTERED THEIR GUNS. BACK TO TASERS.", T_COP)
        self.whistle_cd -= dt
        self._deploy_officers()
        self._update_gate(dt)
        self._jail_tick(dt)
        for p in self.players.values():
            if p.tased_t > 0:
                p.tased_t -= dt
            if p.pants_t > 0:
                p.pants_t -= dt
                if p.pants_t <= 0:
                    self.toast("%s FOUND SOME TROUSERS. DIGNITY: PARTIALLY RESTORED." % p.name, T_INFO)
            if p.state == DEAD:
                p.dead_t -= dt
                p.prompt = "WASTED. WAKING UP AT THE SHOP IN %d..." % (int(p.dead_t) + 1)
                if p.dead_t <= 0:
                    self._respawn_dead(p)
            # being cuffed: the officer re-claims you every tick he's got hold of you
            if p.cuffer is not None and p.state in (FOOT, TUMBLE):
                p.prompt = "AN OFFICER IS CUFFING YOU! MASH SPACE OR PUNCH HIM (%d/%d)" % (
                    p.wriggle, C.CUFF_BREAK_PRESSES)
            elif p.cuff_prog > 0:
                p.cuff_prog = max(0.0, p.cuff_prog - 2.0 * dt)
                if p.cuff_prog <= 0 and p.state == FOOT:
                    p.wriggle = 0
            p.cuffer = None
            if p.jumpsuit and self.map.in_garage(p.x, p.y):
                p.jumpsuit = False
                self.toast("%s CHANGED OUT OF THE JUMPSUIT. NOBODY SAW NOTHING." % p.name, T_INFO)
        for car in self.cars.values():
            if car.hop_t > 0:
                car.hop_t -= dt
        self._speed_cameras(dt)
        self._streakers(dt)
        self._smoke_screens(dt)

    def _law_targets(self):
        """Crooks the police would like a word with: on foot, not already in
        custody, outside the shop -- while there's heat, or while wearing orange."""
        out = []
        for p in self.players.values():
            if p.state not in (FOOT, TUMBLE) or p.jailed or self.map.in_garage(p.x, p.y) or \
                    self.map.in_precinct(p.x, p.y):
                continue
            if self.heat > 0 or (p.jumpsuit and C.JUMPSUIT_WITNESS):
                out.append(p)
        return out

    # ------------------------------------------------------------------ officers
    def _deploy_officers(self):
        cands = self._law_targets()
        if not cands:
            return
        for cop in list(self.cars.values()):
            if cop.kind != COP or cop.patrol or cop.fire_t > 0 or cop.donut_t > 0 or cop.confused_t > 0 or \
                    cop.officer is not None or cop.speed() > C.OFFICER_DEPLOY_SPEED or self._donut_for(cop):
                continue                        # (busy: burning, eating, spinning, or smelling donuts)
            best, bd = None, C.OFFICER_DEPLOY_RANGE
            for p in cands:
                d = math.hypot(p.x - cop.x, p.y - cop.y)
                if d < bd and self.map.los(cop.x, cop.y, p.x, p.y):
                    best, bd = p, d
            if best is None:
                continue
            # out of whichever door faces them (if that side isn't a wall)
            c, s = math.cos(cop.ang), math.sin(cop.ang)
            side = 1.0 if (-(best.x - cop.x) * s + (best.y - cop.y) * c) > 0 else -1.0
            spot = None
            for sg in (side, -side):
                x, y = cop.to_world(0.0, sg * (cop.hw + 0.6))
                if not self.map.solid_at(x, y):
                    spot = (x, y, sg)
                    break
            if spot is None:
                continue
            n = NPC(self.new_id(), OFFICER, spot[0], spot[1])
            n.car_id = cop.id
            n.wallet = self.rng.randint(3, 20)          # cops carry very little cash. And a donut.
            n.ang = math.atan2(best.y - n.y, best.x - n.x)
            self.npcs[n.id] = n
            cop.officer = n.id
            self.sfx(S_WHISTLE, n.x, n.y)
            if self.whistle_cd <= 0:
                self.whistle_cd = 6.0
                self.toast(self.rng.choice(OFFICER_LINES), T_COP)
            if self.heat >= C.K9_HEAT and self.rng.random() < C.K9_CHANCE:
                x, y = cop.to_world(-cop.hl - 0.8, 0.0)
                if not self.map.solid_at(x, y):
                    dog = NPC(self.new_id(), DOG, x, y)
                    dog.car_id = cop.id
                    dog.wallet = 0
                    self.npcs[dog.id] = dog
                    self.sfx(S_BARK, x, y)
                    self.toast("K9 UNIT DEPLOYED. IT'S A VERY GOOD BOY. IT WANTS YOUR TROUSERS.", T_COP)

    def _nearest_crook(self, n, reach, prefer=None):
        best, bd = None, reach
        for p in self._law_targets():
            d = math.hypot(p.x - n.x, p.y - n.y) - (2.0 if prefer is not None and p.id == prefer else 0.0)
            if d < bd:
                best, bd = p, d
        return best

    def _officer(self, n, dt):
        """An officer on foot. Returns False when he's back in his car (remove him)."""
        car = self.cars.get(n.car_id)
        n.life_t += dt
        n.attack_cd -= dt
        q = None
        if n.mode != 4 and n.life_t < C.OFFICER_GIVE_UP:
            q = self._nearest_crook(n, C.OFFICER_CHASE_RANGE, prefer=n.foe)
        if q is None:
            n.mode = 4
            if car is None:
                n.vx = n.vy = 0.0
                return n.life_t < C.OFFICER_GIVE_UP + 20.0
            dx, dy = car.x - n.x, car.y - n.y
            d = math.hypot(dx, dy) or 1.0
            if d < car.hl + 1.6:
                car.officer = None                     # back in the car. Radio: "lost him".
                return False
            n.vx, n.vy = dx / d * C.WALK_SPEED, dy / d * C.WALK_SPEED
            return True
        n.foe = q.id
        dx, dy = q.x - n.x, q.y - n.y
        d = math.hypot(dx, dy) or 1.0
        n.ang = math.atan2(dy, dx)
        lethal = self.lethal_t > 0
        tasers = self.heat >= C.TASER_HEAT
        if d > C.CUFF_RANGE and (lethal or tasers) and n.attack_cd <= 0 and q.state == FOOT and \
                d < (C.OFFICER_GUN_RANGE if lethal else C.TASER_RANGE) and (lethal or d > C.TASER_MIN) and \
                self.map.los(n.x, n.y, q.x, q.y):
            n.vx = n.vy = 0.0
            if lethal:
                n.mode = 2
                n.attack_cd = C.OFFICER_GUN_COOLDOWN
                self._police_shot(n.x, n.y, q, d, C.OFFICER_GUN_ACCURACY)
            else:
                n.mode = 1
                n.attack_cd = C.TASER_COOLDOWN
                self._fire_taser(n, q, d)
            return True
        if d > C.CUFF_RANGE:
            n.mode = 2 if lethal else (1 if tasers else 0)
            n.vx, n.vy = dx / d * C.OFFICER_SPEED, dy / d * C.OFFICER_SPEED
            return True
        # got 'em: cuffs out
        n.vx = n.vy = 0.0
        n.mode = 3
        if q.z < 0.6:
            q.cuffer = n.id
            q.cuff_prog += dt * (2.0 if q.state == TUMBLE else 1.0)
            if q.cuff_prog >= C.CUFF_TIME:
                self.arrest(q)
                n.mode = 4
        return True

    def _cuff_wriggle(self, p):
        """Space while an officer's got hold of you: wriggle, wriggle, wriggle."""
        p.wriggle += 1
        self.sfx(S_WRIGGLE, p.x, p.y)
        if p.wriggle >= C.CUFF_BREAK_PRESSES:
            p.wriggle = 0
            p.cuff_prog = 0.0
            for n in self.npcs.values():
                if n.kind == OFFICER and n.foe == p.id and math.hypot(n.x - p.x, n.y - p.y) < C.CUFF_RANGE + 1.0:
                    n.tumble_t = max(n.tumble_t, 1.2)
                    n.attack_cd = 1.0
            self.toast("%s WRIGGLED OUT OF THE CUFFS. LIKE A GREASED EEL." % p.name, T_INFO)

    def _fire_taser(self, n, q, d):
        a = math.atan2(q.y - n.y, q.x - n.x)
        self.sfx(S_TASER, n.x, n.y)
        if self.rng.random() < C.TASER_ACCURACY:
            self.tracer(TRACER_TASER, n.x, n.y, q.x, q.y)
            self._tase(q)
        else:
            miss = a + self.rng.uniform(-0.35, 0.35)
            self.tracer(TRACER_TASER, n.x, n.y, n.x + math.cos(miss) * d, n.y + math.sin(miss) * d)

    def _tase(self, q):
        if self._hurt_player(q, 0.0, 0.0, C.TASER_TIME, BN_TASED):
            q.tased_t = C.TASER_TIME
            self.toast(self.rng.choice(TASED_LINES) % q.name, T_BAD)

    def _police_shot(self, x, y, q, d, accuracy):
        """Live rounds. Only ever fired once the crew has escalated."""
        a = math.atan2(q.y - y, q.x - x)
        self.sfx(S_PISTOL, x, y)
        if self.rng.random() < accuracy and q.state == FOOT:
            self.tracer(ARM_PISTOL, x, y, q.x, q.y)
            self._kill(q)
        else:
            miss = a + self.rng.uniform(-0.3, 0.3)
            self.tracer(ARM_PISTOL, x, y, x + math.cos(miss) * (d + 5), y + math.sin(miss) * (d + 5))

    def _escalate(self, x, y):
        """A gun went off (or a cop got shot): are the police within earshot?"""
        heard = any(c.kind == COP and (c.x - x) ** 2 + (c.y - y) ** 2 < C.COP_HEAR_RANGE ** 2
                    for c in self.cars.values()) or \
            any(n.kind == OFFICER and (n.x - x) ** 2 + (n.y - y) ** 2 < C.COP_HEAR_RANGE ** 2
                for n in self.npcs.values())
        if not heard:
            return
        if self.lethal_t <= 0:
            self.toast("SHOTS FIRED! THE POLICE ARE SHOOTING BACK NOW. FOR REAL.", T_COP)
        self.lethal_t = C.LETHAL_TIME

    # ------------------------------------------------------------------ dying
    def _kill(self, q):
        """WASTED. The crew pays the medical bills: DEATH_LOSS of the cash, split
        by how many of you there are, so it stings the same whoever's playing."""
        if q.state not in (FOOT, TUMBLE, CARRIED, CUFFED):
            return
        if q.state == CARRIED:
            self._free_carried_player(q)
        self._drop_carry(q, throw=False)
        self._drop_all(q)
        self._release_dolly(q)
        q.state = DEAD
        q.dead_t = C.DEATH_TIME
        q.vx = q.vy = 0.0
        q.tumble_t = q.cuff_prog = 0.0
        q.spin = q.ang
        loss = int(max(0, self.cash) * C.DEATH_LOSS / max(1, len(self.players)))
        self.cash -= loss
        self._banner(q, BN_WASTED)
        self.sfx(S_WASTED, q.x, q.y)
        self.toast(self.rng.choice(WASTED_LINES) % (q.name, loss), T_BAD)

    def _respawn_dead(self, p):
        p.state = FOOT
        p.x, p.y = self.map.player_spawns[(p.id - 1) % 4]
        p.vx = p.vy = 0.0
        p.spin = 0.0
        p.jumpsuit = False
        p.pants_t = 0.0
        p.stamina = C.STAMINA_MAX
        self.toast("%s WOKE UP AT THE SHOP. EVERYTHING HURTS." % p.name, T_INFO)

    # ------------------------------------------------------------------ busted -> the precinct
    def _mugshot(self, p):
        """The charge sheet, read out on arrest: two toasts' worth, worst first."""
        items = sorted(p.rap.items(), key=lambda kv: -kv[1])
        if not items:
            self.toast("MUGSHOT: %s. CHARGES: LOITERING. PROBABLY." % p.name, T_COP)
            return
        parts = ["%dX %s" % (n, CHARGES.get(k, k.upper())) if n > 1 else CHARGES.get(k, k.upper())
                 for k, n in items[:4]]
        self.toast("MUGSHOT: %s. CHARGES:" % p.name, T_COP)
        line = ""
        for bit in parts:
            nxt = (line + ", " + bit) if line else bit
            if len(nxt) > 58:
                self.toast(line, T_COP)
                line = bit
            else:
                line = nxt
        if line:
            self.toast(line, T_COP)

    def _jail(self, p):
        """Off the kerb and into the lockup."""
        p.rap.clear()
        if self.map.precinct_outer is None:
            p.state = FOOT
            p.x, p.y = self.map.player_spawns[(p.id - 1) % 4]
            p.vx = p.vy = 0.0
            return
        p.state = FOOT
        p.jailed = True
        p.keys = False
        p.jumpsuit = False
        x, y = self.map.jail_spawns[(p.id - 1) % len(self.map.jail_spawns)]
        p.x, p.y = x, y
        p.vx = p.vy = 0.0
        p.ang = math.pi / 2
        g = self.gate()
        if g is not None and g.open_t > 0:
            g.open_t = 0.0
            self._rebuild_trap_rects()
        self._staff_precinct()
        self.toast("%s IS IN THE LOCKUP. THE BIG GUARD HAS THE KEYS." % p.name, T_COP)
        self.toast(self.rng.choice(PHONE_CALL_LINES) % p.name, T_INFO)

    def _staff_precinct(self):
        if any(n.kind in (GUARD, KEYGUARD) for n in self.npcs.values()):
            return
        for k, (x, y) in enumerate(self.map.guard_posts[:C.JAIL_GUARDS]):
            n = NPC(self.new_id(), KEYGUARD if k == 0 else GUARD, x, y)
            n.home = (x, y)
            n.grit = C.GUARD_GRIT + (1 if k == 0 else 0)     # the one with the keys is the big one
            n.wallet = self.rng.randint(5, 30)
            n.ang = -math.pi / 2
            self.npcs[n.id] = n

    def _jail_tick(self, dt):
        jailed = [p for p in self.players.values() if p.jailed]
        for p in jailed:
            if p.state in (FOOT, TUMBLE) and not self.map.in_precinct(p.x, p.y):
                p.jailed = False
                p.keys = False
                p.jumpsuit = True
                self._charge(p, "break")
                self._banner(p, BN_FREE)
                self._crime(C.JAILBREAK_HEAT)
                self.toast("JAILBREAK! %s IS OUT. RUN FOR THE SHOP!" % p.name, T_MONEY)
                self.toast("(THAT ORANGE JUMPSUIT IS NOT SUBTLE.)", T_INFO)
        if any(p.jailed for p in self.players.values()):
            self.guard_idle_t = 0.0
        else:
            self.guard_idle_t += dt
            if self.guard_idle_t > C.GUARD_RESET_TIME:
                for nid in [n.id for n in self.npcs.values() if n.kind in (GUARD, KEYGUARD)]:
                    del self.npcs[nid]

    def _guard(self, n, dt):
        """A lockup guard: stands at his post, and flattens anyone in orange who
        comes near. The one with the keys is the one you want."""
        n.attack_cd -= dt
        q, bd = None, 30.0
        for p in self.players.values():
            if p.jailed and p.state in (FOOT, TUMBLE) and self.map.in_precinct(p.x, p.y):
                d = math.hypot(p.x - n.x, p.y - n.y)
                if d < bd:
                    q, bd = p, d
        if q is None:
            hx, hy = n.home or (n.x, n.y)
            dx, dy = hx - n.x, hy - n.y
            d = math.hypot(dx, dy)
            n.hostile_t = 0.0
            if d > 0.5:
                n.vx, n.vy = dx / d * C.WALK_SPEED * 0.6, dy / d * C.WALK_SPEED * 0.6
            else:
                n.vx = n.vy = 0.0
            return
        n.hostile_t = 1.0                       # (for the renderer: fists up)
        dx, dy = q.x - n.x, q.y - n.y
        d = math.hypot(dx, dy) or 1.0
        n.ang = math.atan2(dy, dx)
        if d > C.BRAWL_REACH:
            spd = C.GUARD_SPEED * (0.85 if n.kind == KEYGUARD else 1.0)
            n.vx, n.vy = dx / d * spd, dy / d * spd
            return
        n.vx = n.vy = 0.0
        if n.attack_cd <= 0 and q.state == FOOT and q.z < 1.0:
            n.attack_cd = C.GUARD_PUNCH_COOLDOWN
            self.sfx(S_PUNCH, q.x, q.y)
            if self.rng.random() < C.BRAWL_HIT_CHANCE:
                self._hurt_player(q, dx / d * 6, dy / d * 6, C.BRAWL_PUNCH_TUMBLE, BN_HUMBLED)
                if n.complain_cd <= 0:
                    n.complain_cd = 5.0
                    self.toast(self.rng.choice(GUARD_LINES), T_COP)

    def _take_keys(self, p, n):
        if n.id not in self.npcs or n.kind != KEYGUARD:
            return
        n.kind = GUARD                          # he doesn't have them any more
        p.keys = True
        self.sfx(S_KEYS, n.x, n.y)
        self.toast("%s LIFTED THE KEYS. TO THE GATE!" % p.name, T_MONEY)

    def _open_gate(self, t, secs, why=None):
        was = t.open_t > 0
        t.open_t = max(t.open_t, secs)
        if not was:
            self._rebuild_trap_rects()
            self.sfx(S_GATE, t.x, t.y)
            if why:
                self.toast(why, T_MONEY)

    def _update_gate(self, dt):
        t = self.gate()
        if t is None:
            return
        if t.open_t > 0:
            t.open_t -= dt
            if t.open_t <= 0:
                t.open_t = 0.0
                self._rebuild_trap_rects()
                self.sfx(S_GATE, t.x, t.y)
            return
        # the dramatic way in: through it, at speed
        rx, ry, rw, rh = t.rect()
        for car in self.cars.values():
            if abs(car.x - t.x) > 8 or abs(car.y - t.y) > 8:
                continue
            if car.impact_dv >= C.GATE_RAM_DV and obb_rect_contact(
                    car.x, car.y, car.ang, (rx - 0.3, ry - 0.3, rw + 0.6, rh + 0.6), car.hl, car.hw):
                self._open_gate(t, C.GATE_SMASH_TIME, "THE PRECINCT GATE IS IN PIECES. SUBTLE.")
                self.sfx(S_CRASH_BIG, t.x, t.y)
                self._crime(C.JAILBREAK_HEAT * 0.5)
                break

    def _gate_interaction(self, p, ax, ay):
        """The lockup gate and the bail desk (from _find_interaction)."""
        m = self.map
        t = self.gate()
        if t is not None and math.hypot(ax - t.x, ay - t.y) < 2.4:
            if t.open_t > 0:
                return (None, "THE GATE'S OPEN. GO GO GO!", 0, None)
            if p.jailed or m.in_precinct(p.x, p.y):
                if p.keys:
                    return (("unlock",), "E: UNLOCK THE GATE", 0,
                            lambda: (setattr(p, "keys", False),
                                     self._open_gate(t, C.GATE_OPEN_TIME, "THE GATE CLANKS OPEN!")))
                return (None, "LOCKED. THE BIG GUARD HAS THE KEYS (KNOCK HIM DOWN, ROB HIM)", 0, None)
            return (("pick",), "HOLD E: PICK THE LOCK (BREAK YOUR CREW OUT)", C.GATE_PICK_TIME,
                    lambda: (self._crime(C.JAILBREAK_HEAT * 0.5),
                             self._open_gate(t, C.GATE_OPEN_TIME, "%s PICKED THE PRECINCT LOCK!" % p.name)))
        if p.jailed and m.bail_desk is not None:
            bx, by, bw, bh = m.bail_desk
            cx, cy = min(max(ax, bx), bx + bw), min(max(ay, by), by + bh)
            if math.hypot(ax - cx, ay - cy) < C.INTERACT_RANGE_BENCH:
                bail = self._bail(p)
                if self.cash < bail:
                    return (None, "BAIL: $%d. THE CREW CAN'T AFFORD IT. FIGHT!" % bail, 0, None)
                return (("bail",), "HOLD E: POST BAIL ($%d) AND WALK OUT" % bail, 1.0, lambda: self._post_bail(p))
        return None

    def _bail(self, p):
        return C.BAIL_BASE + C.BAIL_PER_ARREST * max(0, p.arrests - 1)

    def _post_bail(self, p):
        bail = self._bail(p)
        if not p.jailed or self.cash < bail:
            return
        self.cash -= bail
        p.jailed = False
        p.keys = False
        self.sfx(S_BUY, p.x, p.y)
        t = self.gate()
        if t is not None:
            self._open_gate(t, 5.0)
        self.toast("%s POSTED BAIL: -$%d. WALK OUT, HEAD HELD LOW." % (p.name, bail), T_INFO)

    # ------------------------------------------------------------------ hitting the law
    def _law_hit(self, n, vx, vy, t, attacker, vz):
        """_knock_down_npc for people on the city's payroll (and the streaker)."""
        n.vx, n.vy = vx, vy
        if vz:
            n.vz = max(n.vz, vz)
            n.z = max(n.z, 0.05)
        who = attacker if isinstance(attacker, Player) else self.players.get(attacker)
        if n.kind in (GUARD, KEYGUARD):
            n.grit -= 1
            n.tumble_t = max(n.tumble_t, C.GUARD_KO_TIME if n.grit <= 0 else C.GUARD_DOWN_TIME)
        elif n.kind == OFFICER:
            n.tumble_t = max(n.tumble_t, C.OFFICER_KO_TIME)
            if who is not None:
                self._crime(C.ASSAULT_OFFICER_HEAT)
                self._charge(who, "cop")
        elif n.kind == DOG:
            n.tumble_t = max(n.tumble_t, 1.2)
            n.mode = 4                          # runs off, tail between legs
            self.sfx(S_YELP, n.x, n.y)
        elif n.kind == STREAKER:
            n.tumble_t = max(n.tumble_t, 3.0)
            if who is not None and n.mode != 4:
                n.mode = 4
                n.ttl = 3.5
                self._earn(C.STREAKER_REWARD)
                self.heat = max(0.0, self.heat - C.STREAKER_HEAT_CUT)
                self.toast("CITIZEN'S ARREST! %s TACKLED THE STREAKER: +$%d, -HEAT" % (who.name, C.STREAKER_REWARD),
                           T_MONEY)

    # ------------------------------------------------------------------ K9
    def _dog(self, n, dt):
        """A police dog. It can't arrest you. It can take your trousers."""
        n.life_t += dt
        if n.life_t > C.K9_LIFETIME:
            return False
        if n.mode == 4:
            # off it goes (with or without your trousers), away from everyone
            if n.home is None:
                a = self.rng.uniform(0, 2 * math.pi)
                n.home = (math.cos(a), math.sin(a))
            n.vx, n.vy = n.home[0] * C.K9_SPEED * 0.8, n.home[1] * C.K9_SPEED * 0.8
            n.ang = math.atan2(n.vy, n.vx)
            return n.life_t < C.K9_LIFETIME
        q = None
        bd = 60.0
        for p in self._law_targets():
            if p.state == FOOT and p.pants_t <= 0:
                d = math.hypot(p.x - n.x, p.y - n.y)
                if d < bd:
                    q, bd = p, d
        if q is None:
            n.mode = 4
            return True
        dx, dy = q.x - n.x, q.y - n.y
        d = math.hypot(dx, dy) or 1.0
        n.ang = math.atan2(dy, dx)
        n.yell_t -= dt
        if n.yell_t <= 0:
            n.yell_t = self.rng.uniform(1.2, 2.5)
            self.sfx(S_BARK, n.x, n.y)
        if d > 0.9:
            n.vx, n.vy = dx / d * C.K9_SPEED, dy / d * C.K9_SPEED
            return True
        # got 'em. By the trousers.
        q.pants_t = C.PANTSED_TIME
        self._hurt_player(q, dx / d * 3, dy / d * 3, 0.7, BN_PANTSED)
        self.toast("THE K9 UNIT TOOK %s'S TROUSERS. BOXERS: %s" % (q.name, self.rng.choice(BOXERS)), T_BAD)
        n.mode = 4
        n.home = (dx / d, dy / d)
        n.life_t = C.K9_LIFETIME - 4.0
        return True

    # ------------------------------------------------------------------ the streaker
    def _streakers(self, dt):
        if not self.players or not self.map.sidewalk_tiles:
            return
        if any(n.kind == STREAKER for n in self.npcs.values()):
            return
        self.streaker_t -= dt
        if self.streaker_t > 0:
            return
        self.streaker_t = self.rng.uniform(*C.STREAKER_EVERY)
        p = self.rng.choice(list(self.players.values()))
        T = C.TILE_M
        for _ in range(30):
            tx, ty = self.rng.choice(self.map.sidewalk_tiles)
            x, y = (tx + 0.5) * T, (ty + 0.5) * T
            if 35.0 < math.hypot(x - p.x, y - p.y) < 70.0:
                n = NPC(self.new_id(), STREAKER, x, y)
                n.ttl = C.STREAKER_LIFETIME
                n.wallet = 0
                self.npcs[n.id] = n
                self.sfx(S_WHEE, x, y)
                self.toast(self.rng.choice(STREAKER_LINES), T_INFO)
                return

    def _streaker(self, n, dt):
        """Runs about, whooping. Cops nearby chase HIM instead of you."""
        n.turn_t -= dt
        if n.mode == 4:
            n.vx = n.vy = 0.0
            return True
        if n.turn_t <= 0:
            n.turn_t = self.rng.uniform(1.0, 2.5)
            a = self.rng.uniform(0, 2 * math.pi)
            n.dirx, n.diry = math.cos(a), math.sin(a)
            if self.rng.random() < 0.3:
                self.sfx(S_WHEE, n.x, n.y)
        if self.map.solid_at(n.x + n.dirx * 1.5, n.y + n.diry * 1.5):
            n.dirx, n.diry = -n.diry, n.dirx
        n.vx, n.vy = n.dirx * C.STREAKER_SPEED, n.diry * C.STREAKER_SPEED
        return True

    def _streaker_near(self, x, y):
        for n in self.npcs.values():
            if n.kind == STREAKER and n.mode != 4 and \
                    (n.x - x) ** 2 + (n.y - y) ** 2 < C.STREAKER_COP_RANGE ** 2:
                return n
        return None

    # ------------------------------------------------------------------ speed cameras
    def _speed_cameras(self, dt):
        for k in list(self.cam_cd):
            self.cam_cd[k] -= dt
            if self.cam_cd[k] <= 0:
                del self.cam_cd[k]
        car = self.cars.get(self.personal_id)
        if car is None or car.driver is None or car.speed() < C.SPEEDCAM_SPEED:
            return
        for k, (cx, cy) in enumerate(self.map.cameras):
            if k in self.cam_cd:
                continue
            if (car.x - cx) ** 2 + (car.y - cy) ** 2 < C.SPEEDCAM_RANGE ** 2:
                self.cam_cd[k] = C.SPEEDCAM_COOLDOWN
                self.cash -= C.SPEEDCAM_FINE
                self.sfx(S_FLASH, cx, cy)
                p = self.players.get(car.driver)
                if p is not None:
                    self._banner(p, BN_SMILE)
                    self._charge(p, "speed")
                self.toast("SMILE! SPEED CAMERA. -$%d TICKET, POSTED TO THE SHOP." % C.SPEEDCAM_FINE, T_BAD)

    # ------------------------------------------------------------------ smoke screens
    def _smoke_screens(self, dt):
        for car in self.cars.values():
            if car.smoke_t < C.SMOKE_SCREEN_AT:
                self.smoke_mark.pop(car.id, None)
                continue
            last = self.smoke_mark.get(car.id, 0.0)
            if car.smoke_t - last < C.SMOKE_SCREEN_EVERY:
                continue
            self.smoke_mark[car.id] = car.smoke_t
            smokes = [t for t in self.traps.values() if t.kind == TRAP_SMOKE]
            if len(smokes) >= C.SMOKE_SCREEN_MAX:
                oldest = max(smokes, key=lambda t: t.age)
                self.traps.pop(oldest.id, None)
            lx = -car.hl * 0.6
            x, y = car.to_world(lx, 0.0)
            t = Trap(self.new_id(), TRAP_SMOKE, x, y, 0.0)
            self.traps[t.id] = t
            if not self.smoke_told:
                self.smoke_told = True
                self.toast("SMOKE SCREEN! NOBODY CAN SEE A THING IN THERE.", T_INFO)

    def _smoky(self, x0, y0, x1, y1):
        """Does the line from (x0, y0) to (x1, y1) pass through a burnout cloud?"""
        r2 = C.SMOKE_SCREEN_R ** 2
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy or 1e-9
        for t in self.traps.values():
            if t.kind != TRAP_SMOKE:
                continue
            k = max(0.0, min(1.0, ((t.x - x0) * dx + (t.y - y0) * dy) / L2))
            px, py = x0 + dx * k - t.x, y0 + dy * k - t.y
            if px * px + py * py < r2:
                return True
        return False

    # ------------------------------------------------------------------ hydraulics
    def _hop(self, p, car):
        if not car.hydraulics or car.hop_t > 0:
            return
        car.hop_t = C.HOP_TIME
        self.sfx(S_HYDRO, car.x, car.y)
        r2 = C.HOP_CROWD_RANGE ** 2
        crowd = 0
        for n in self.npcs.values():
            if n.kind == PED and n.tumble_t <= 0 and n.hostile_t <= 0 and \
                    (n.x - car.x) ** 2 + (n.y - car.y) ** 2 < r2:
                n.laugh_t = max(n.laugh_t, 3.0)       # (they're cheering. Same animation. Same result.)
                n.vx = n.vy = 0.0
                crowd += 1
        if crowd >= 3 and self.rng.random() < 0.3:
            self.toast("LOWRIDER SHOW! THE CROWD GOES WILD.", T_MONEY)

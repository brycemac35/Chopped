"""
garage.py -- v0.7: trunks, the parts locker, and the mod shop, as a mixin the
World inherits.

Trunks: every car has one (a Kei's fits a wheel and a door, a box van fits a
small scrapyard). Put parts in, take them out, and stolen cars sometimes come
with something in the back already -- a bag of cash, a briefcase, a gnome.

The mod shop: the tune-up bench is now a GTA-style garage menu for your ride.
Whatever you walk in holding goes into the shared parts LOCKER; from there
(or straight off the shop's catalogue, for a price) you bolt it on, slot by
slot, style by style. Paint, liveries, joke horns, neon underglow, NOS, an
ejector seat, and a gnome for the bonnet. The client draws the menu
(modshop.py) and sends one numbered command at a time; we do the maths here.
"""

import math

from . import config as C
from .enums import *  # noqa: F401,F403
from .entities import TIERS, buy_price
from .parts import (SLOTS, SLOT_CATEGORY, CATEGORY_SLOTS, PART_DEFS, PART_IDS, PART_INDEX, DOLLY, Part,
                    OPTIONAL_SLOTS)
from . import vehicles as V
from .lines import WHOLE_SALE_LINES, DOOR_BANG_LINES
from .entities import Trap
from .physics import obb_rect_contact, circle_rect_contact

# ---- menu commands (InputState.menu_op) ----------------------------------------------
(OP_NONE, OP_CLOSE, OP_INSTALL, OP_BUY, OP_REMOVE, OP_SELL, OP_TAKE, OP_PAINT, OP_LIVERY, OP_HORN,
 OP_GLOW, OP_EXTRA, OP_SWITCH) = range(13)
EXTRA_NOS, EXTRA_EJECTOR, EXTRA_GNOME, EXTRA_HYDRO = range(4)
EXTRA_NAMES = ("NITROUS (SHIFT)", "EJECTOR SEAT (F AT SPEED)", "GNOME HOOD ORNAMENT", "HYDRAULICS (X: HOP)")

# parts you can't buy new (they come off scooters, out of trunks, or out of gardens)
NOT_FOR_SALE = {"eng_electric", "whl_scooter", "gnome", "cash_bag", "briefcase", "rubber_duck"}


def catalogue(slot):
    """Everything the shop will sell you for this slot: [(type_id, style, price)].
    Same list on the client and the host, so an index means the same thing."""
    cat = SLOT_CATEGORY[slot]
    out = []
    for tid in TIERS.get(cat, []):
        if tid in NOT_FOR_SALE:
            continue
        for style in range(len(V.styles_for(cat))):
            price = int(round(buy_price(tid) * V.style_value(cat, style)))
            out.append((tid, style, price))
    return out


def horn_price(h):
    return C.HORN_PRICES[h] if 0 <= h < len(C.HORN_PRICES) else 0


def extra_price(which):
    return (C.PRICE_NOS, C.PRICE_EJECTOR, C.PRICE_GNOME_MOUNT, C.PRICE_HYDRAULICS)[which]


class Garage:
    # ------------------------------------------------------------------ trunks
    def _trunk_open(self, car):
        """Can you get into this car's trunk right now?"""
        if car.kind == PERSONAL:
            return True
        if car.kind == CIV:
            return car.state != LOCKED
        return False

    def _trunk_fits(self, car, part):
        m = V.model(car.model)
        if part.bulk == DOLLY:
            return m.bed and not any(q.bulk == DOLLY for q in car.trunk) and car.trunk_used() + 3 <= m.trunk
        return car.trunk_used() + part.bulk <= m.trunk

    def _trunk_interaction(self, p, car):
        """(key, prompt, hold, action) for the back of a car, or None if the
        trunk has nothing to offer here."""
        m = V.model(car.model)
        used, cap = car.trunk_used(), m.trunk
        if not self._trunk_open(car):
            return None
        p.trunk_view = car.id
        if p.hands:
            part = p.hands[-1]
            if not self._trunk_fits(car, part):
                return (None, "TRUNK FULL (%d/%d)" % (used, cap), 0, None)
            return (("trunk_in", car.id, id(part)), "E: PUT %s IN THE TRUNK (%d/%d)" % (part.name.upper(), used, cap),
                    0, lambda: self._trunk_put(p, car, part))
        if car.trunk:
            liftable = [q for q in car.trunk if q.bulk != DOLLY and p.can_hold(q)]
            if not liftable:
                return (None, "TRUNK: %s - BRING THE DOLLY" % car.trunk[0].name.upper(), 0, None)
            best = max(liftable, key=lambda q: q.value)
            return (("trunk_out", car.id, id(best)), "E: TAKE %s FROM THE TRUNK ($%d, %d LEFT)" % (
                best.name.upper(), best.value, len(car.trunk) - 1), 0, lambda: self._trunk_take(p, car, best))
        return None

    def _trunk_put(self, p, car, part):
        if part in p.hands and self._trunk_fits(car, part):
            p.hands.remove(part)
            car.trunk.append(part)
            self.sfx(S_TRUNK, car.x, car.y)

    def _trunk_take(self, p, car, part):
        if part in car.trunk and p.can_hold(part):
            car.trunk.remove(part)
            p.hands.append(part)
            self.sfx(S_TRUNK, car.x, car.y)
            if part.category == "loot" and car.kind == CIV:
                self.toast("%s FOUND A %s IN THE TRUNK!" % (p.name, part.name.upper()), T_MONEY)

    def _trunk_dolly(self, p, d, car):
        """The dolly at a pickup's bed or a van's back doors."""
        m = V.model(car.model)
        if not m.bed or not self._trunk_open(car):
            return None
        if d.part is not None:
            if not self._trunk_fits(car, d.part):
                return (None, "NO ROOM IN THE BED FOR THAT", 0, None)
            return (("bed_in", car.id), "HOLD E: LOAD %s INTO THE BED" % d.part.name.upper(), C.DOLLY_LOAD_TIME,
                    lambda: self._bed_load(d, car))
        eng = next((q for q in car.trunk if q.bulk == DOLLY), None)
        if eng is not None:
            return (("bed_out", car.id), "HOLD E: UNLOAD %s ONTO THE DOLLY" % eng.name.upper(), C.DOLLY_LOAD_TIME,
                    lambda: self._bed_unload(d, car, eng))
        return None

    def _bed_load(self, d, car):
        if d.part is not None and self._trunk_fits(car, d.part):
            car.trunk.append(d.part)
            d.part = None
            self.sfx(S_TRUNK, car.x, car.y)

    def _bed_unload(self, d, car, eng):
        if d.part is None and eng in car.trunk:
            car.trunk.remove(eng)
            d.part = eng
            self.sfx(S_TRUNK, car.x, car.y)

    def _spill_trunk(self, car, speed=4.0):
        """The car's going away (crushed, exploded, towed): the trunk empties onto the road."""
        for part in car.trunk:
            a = self.rng.uniform(0, 2 * math.pi)
            self.add_pickup(part, car.x + math.cos(a), car.y + math.sin(a),
                            math.cos(a) * speed, math.sin(a) * speed)
        car.trunk = []

    # ------------------------------------------------------------------ the locker
    def _to_locker(self, part):
        if len(self.stash) >= C.STASH_MAX:
            # full: the oldest junk goes out the back door onto the floor
            old = self.stash.pop(0)
            bx, by, bw, bh = self.map.tune_bench
            self.add_pickup(old, bx + bw / 2, by + bh + 1.2)
        self.stash.append(part)

    # ------------------------------------------------------------------ the mod shop
    def _open_modshop(self, p):
        car = self._my_car(p)
        if car is None:
            return
        stored = 0
        while p.hands:
            self._to_locker(p.hands.pop())
            stored += 1
        if p.dolly is not None and p.dolly.part is not None:
            self._to_locker(p.dolly.part)
            p.dolly.part = None
            stored += 1
        self._release_dolly(p)
        p.menu = True
        p.vx = p.vy = 0.0
        self.sfx(S_MOD, p.x, p.y)
        if stored:
            self.toast("%d PART%s INTO THE LOCKER" % (stored, "S" if stored > 1 else ""), T_INFO)

    def _modshop_input(self, p, inp):
        """Called every tick while p.menu: runs a new command, if there is one."""
        if inp.menu_seq == p.menu_ack:
            return
        p.menu_ack = inp.menu_seq
        op, a, b = inp.menu_op, inp.menu_arg, inp.menu_arg2
        car = self._my_car(p)
        if op == OP_CLOSE or car is None:
            p.menu = False
            return
        if op == OP_INSTALL:
            self._ms_install(p, car, a, b)
        elif op == OP_BUY:
            self._ms_buy(p, car, a, b)
        elif op == OP_REMOVE:
            if 0 <= a < len(SLOTS) and car.parts.get(SLOTS[a]) is not None:
                self._to_locker(car.parts[SLOTS[a]])
                car.parts[SLOTS[a]] = None
                car.refresh()
                self.sfx(S_MOD, p.x, p.y)
        elif op in (OP_SELL, OP_TAKE):
            if 0 <= a < len(self.stash) and PART_INDEX[self.stash[a].type_id] == b:
                part = self.stash.pop(a)
                if op == OP_SELL:
                    self._earn(part.value, 1)
                    self.sfx(S_SELL, p.x, p.y)
                    self.toast("SOLD %s FROM THE LOCKER: +$%d" % (part.name.upper(), part.value), T_MONEY)
                elif part.bulk == DOLLY:
                    self._to_locker(part)          # can't carry an engine out in your arms
                    self.toast("ENGINES LEAVE ON THE DOLLY. PUSH IT TO THE BENCH.", T_INFO)
                else:
                    p.hands = [part]
                    p.menu = False
                    self.sfx(S_PICKUP, p.x, p.y)
        elif op == OP_PAINT:
            if a < len(V.PAINT_NAMES) and a != car.color and self._pay(C.PRICE_PAINT):
                car.color = a
                self.sfx(S_SPRAY, p.x, p.y)
        elif op == OP_LIVERY:
            want = V.livery_byte(a, b)
            if a < len(V.LIVERIES) and want != car.livery and self._pay(C.PRICE_LIVERY if a else 0):
                car.livery = want
                self.sfx(S_SPRAY, p.x, p.y)
        elif op == OP_HORN:
            if a < len(V.HORNS) and a != car.horn_type and self._pay(horn_price(a)):
                car.horn_type = a
                self.sfx(S_MOD, p.x, p.y)
        elif op == OP_GLOW:
            if a <= 15 and a != car.glow and self._pay(C.PRICE_GLOW if a else 0):
                car.glow = a
                self.sfx(S_MOD, p.x, p.y)
        elif op == OP_EXTRA:
            self._ms_extra(p, car, a)
        elif op == OP_SWITCH:
            self._ms_switch(p, car, a | (b << 8))

    def _ms_switch(self, p, old, target_id):
        """(v0.10, Bryce: "add option to switch primary cars once in garage") make a
        delivered car sitting in the shop this player's new personal ride. The old one
        becomes an ordinary car again -- strip it, sell it whole, whatever -- and this one
        takes over its bay and keeps its owner's mods from here on."""
        new = self.cars.get(target_id)
        if new is None or new is old or new.kind != CIV or new.state != DELIVERED:
            return
        if not all(self.map.in_garage(x, y) for x, y in new.corners()):
            return
        old.kind, old.owner, old.state = CIV, None, DELIVERED
        old.stolen = old.alarm = False
        old.driver = old.passenger = None
        new.kind, new.owner, new.bay = PERSONAL, p.id, old.bay
        # (v0.12 fix, Bryce: "after swapping a car i cant start the new one") a delivered car
        # is parked for good -- physics won't drive anything in DELIVERED -- so the new ride
        # has to come out of that state, and stop counting as stolen for the cameras too
        new.state = RUNNING
        new.stolen = new.alarm = False
        # ...and the two swap PLACES. (v0.12.1: the new one used to be dropped into the bay
        # right on top of the old one, which was still parked there -- the physics shoved
        # them into a heap and the old car's strip prompt covered the new one's door, so
        # you couldn't even get in. That was most of "can't start the new one".)
        ox, oy, oang = new.x, new.y, new.ang
        new.x, new.y, new.ang = self.map.bays[old.bay]
        old.x, old.y, old.ang = ox, oy, oang
        new.vx = new.vy = new.w = 0.0
        old.vx = old.vy = old.w = 0.0
        self.player_car[p.id] = new.id
        if old.bay == 0:
            self.personal_id = new.id
        self.sfx(S_MOD, new.x, new.y)
        self.toast("%s: THE %s IS THE NEW RIDE. THE OLD ONE'S UP FOR GRABS." % (
            p.name, V.model(new.model).name), T_MONEY)

    def _pay(self, price):
        if self.cash < price:
            self.toast("CAN'T AFFORD IT. THE MOD SHOP DOES NOT DO CREDIT.", T_BAD)
            return False
        self.cash -= price
        return True

    def _ms_install(self, p, car, i, slot_i):
        if not (0 <= i < len(self.stash) and 0 <= slot_i < len(SLOTS)):
            return
        slot = SLOTS[slot_i]
        part = self.stash[i]
        if part.category != SLOT_CATEGORY[slot]:
            return
        self.stash.pop(i)
        old = car.parts.get(slot)
        car.parts[slot] = part
        if old is not None:
            self._to_locker(old)
        car.refresh()
        self.sfx(S_MOD, p.x, p.y)
        self.toast("BOLTED ON: %s. YOUR RIDE: %d POWER" % (part.name.upper(), car.power()), T_INFO)
        self._quest_on_install(p, car, slot)

    def _ms_buy(self, p, car, k, slot_i):
        if not 0 <= slot_i < len(SLOTS):
            return
        slot = SLOTS[slot_i]
        cat = catalogue(slot)
        if not 0 <= k < len(cat):
            return
        tid, style, price = cat[k]
        if not self._pay(price):
            return
        old = car.parts.get(slot)
        car.parts[slot] = Part(tid, 1.0, style)
        if old is not None:
            self._to_locker(old)
        car.refresh()
        self.sfx(S_BUY, p.x, p.y)
        self.toast("BOUGHT %s: -$%d" % (car.parts[slot].name.upper(), price), T_INFO)

    def _ms_extra(self, p, car, which):
        if which == EXTRA_NOS and not car.nos and self._pay(C.PRICE_NOS):
            car.nos, car.nos_fuel = True, C.NOS_TANK
        elif which == EXTRA_EJECTOR and not car.ejector and self._pay(C.PRICE_EJECTOR):
            car.ejector = True
        elif which == EXTRA_GNOME and not car.gnome:
            g = next((q for q in self.stash if q.type_id == "gnome"), None)
            if g is not None:
                self.stash.remove(g)                        # BYO gnome: fitting's free
            elif not self._pay(C.PRICE_GNOME_MOUNT):
                return
            car.gnome = True
            self.toast("THE GNOME HAS BEEN INSTALLED. IT WATCHES THE ROAD. IT WATCHES YOU.", T_INFO)
        elif which == EXTRA_HYDRO and not car.hydraulics and self._pay(C.PRICE_HYDRAULICS):
            car.hydraulics = True
            self.toast("HYDRAULICS FITTED. PRESS X IN THE CAR. BOUNCE RESPONSIBLY.", T_INFO)
        else:
            return
        self.sfx(S_MOD, p.x, p.y)


def encode_menu(world, me):
    """The mod shop's view of the world, for the SELF block (only while you're
    in the menu): your ride's parts, its paint and extras, and the locker."""
    car = world._my_car(me)                    # (v0.10) your OWN car, not always bay 0's
    out = bytearray()
    out.append(me.menu_ack & 255)
    out += bytes(((car.id if car else 0) & 0xFF, ((car.id if car else 0) >> 8) & 0xFF))
    if car is None:
        out += bytes(6)
    else:
        out += bytes((car.color & 255, car.livery & 255, car.horn_type & 255, car.glow & 255,
                      (1 if car.nos else 0) | (2 if car.ejector else 0) | (4 if car.gnome else 0) |
                      (8 if car.hydraulics else 0), car.model & 255))
    for s in SLOTS:
        part = car.parts.get(s) if car is not None else None
        if part is None:
            out += bytes((255, 0, 0))
        else:
            out += bytes((PART_INDEX[part.type_id], part.style & 255, int(part.condition * 255) & 255))
    items = world.stash[:C.STASH_MAX]
    out.append(len(items))
    for part in items:
        out += bytes((PART_INDEX[part.type_id], part.style & 255, int(part.condition * 255) & 255))
    return bytes(out)


def decode_menu(data, off):
    """-> (menu dict, new offset)"""
    menu = {"ack": data[off]}
    off += 1
    menu["car_id"] = data[off] | (data[off + 1] << 8)
    off += 2
    (menu["color"], menu["livery"], menu["horn"], menu["glow"], ex, menu["model"]) = data[off:off + 6]
    off += 6
    menu["nos"], menu["ejector"], menu["gnome"], menu["hydro"] = bool(ex & 1), bool(ex & 2), bool(ex & 4), \
        bool(ex & 8)
    slots = {}
    for s in SLOTS:
        idx, style, cond = data[off:off + 3]
        off += 3
        slots[s] = None if idx == 255 else (PART_IDS[idx], style, cond / 255.0)
    menu["slots"] = slots
    n = data[off]
    off += 1
    stash = []
    for _ in range(n):
        idx, style, cond = data[off:off + 3]
        off += 3
        stash.append((PART_IDS[idx], style, cond / 255.0))
    menu["stash"] = stash
    return menu, off


def part_value(tid, style, cond):
    """Client-side Part.value without building a Part."""
    return Part(tid, cond, style).value


def slot_for_category(cat):
    return CATEGORY_SLOTS.get(cat, [])


def part_def(tid):
    return PART_DEFS[tid]


class Appraisal:
    """(v0.9, Bryce: "i want to inspect the cars before hijacking / breaking in to get a
    sense of their parts / value"). Look at a car for a moment and you size it up: what's
    under the bonnet, what gearbox, the shiny bits, how knackered it is, and roughly
    what it'd fetch in bits. Also: whether something in the boot is rattling."""

    def _inspect_scan(self):
        if self.tick % C.INSPECT_EVERY:
            return
        for p in self.players.values():
            p.inspect = self._inspect_target(p) if p.state == FOOT and not p.menu and not p.jailed else 0

    def _inspect_target(self, p):
        best, bd = 0, C.INSPECT_RANGE
        ca, sa = math.cos(p.ang), math.sin(p.ang)
        for car in self.cars.values():
            if car.kind in (COP, PERSONAL) or car.state == DELIVERED:
                continue
            dx, dy = car.x - p.x, car.y - p.y
            if abs(dx) > bd + 3 or abs(dy) > bd + 3:
                continue
            d = math.hypot(dx, dy)
            if d >= bd + car.hl * 0.5:
                continue
            fwd = dx * ca + dy * sa
            if fwd <= 0.3:
                continue
            side = abs(-dx * sa + dy * ca)
            if side > car.hw + 0.6 + fwd * 0.08:             # (roughly: is it under your crosshair?)
                continue
            if not self.los(p.x, p.y, car.x, car.y):
                continue
            best, bd = car.id, d
        return best

    def appraise(self, car):
        """(value, engine part, gearbox part, ecu part, average condition 0..1, best bits
        [(part)], flags) -- the numbers the inspect card shows."""
        parts = [pt for pt in car.parts.values() if pt is not None]
        value = sum(pt.value for pt in parts)
        value = int(round(value / 10.0)) * 10                 # "about": nobody quotes you to the dollar
        cond = sum(pt.condition for pt in parts) / len(parts) if parts else 0.0
        shiny = sorted((pt for pt in parts if pt.category not in ("engine", "trans", "ecu")),
                       key=lambda pt: -pt.value)
        best, seen = [], set()
        for pt in shiny:
            if (pt.type_id, pt.style) in seen:
                continue
            seen.add((pt.type_id, pt.style))
            best.append(pt)
            if len(best) == 3:
                break
        flags = (INSP_RATTLE if car.trunk else 0) | (INSP_HONK if car.special == "clown" else 0) | \
                (INSP_OWNER if car.special == "owner" else 0)
        return (value, car.parts.get("Engine"), car.parts.get("Transmission"), car.parts.get("ECU"), cond,
                best, flags)

    # ------------------------------------------------------------------ selling it whole
    def whole_price(self, car):
        """What the fence pays for the lot, no spanners required: WHOLE_SALE_RATE of the
        parts, the shell, and a collector's bonus for a complete sports car or 4x4."""
        parts = [pt for pt in car.parts.values() if pt is not None]
        complete = all(car.parts.get(s_) is not None for s_ in SLOTS if s_ not in OPTIONAL_SLOTS)
        m = V.model(car.model)
        bonus = 0
        if complete:
            bonus = C.WHOLE_SALE_SPORTY if m.sporty else C.WHOLE_SALE_4X4 if m.awd else 0
        return int(sum(pt.value for pt in parts) * C.WHOLE_SALE_RATE) + C.SHELL_VALUE + bonus

    def _sell_whole(self, p, car):
        if self.cars.get(car.id) is not car or car.state != DELIVERED or car.kind == PERSONAL:
            return
        pay = self.whole_price(car)
        self._spill_trunk(car, 2.0)                           # (the boot's contents are yours: keep them)
        for pid in car.occupants():
            q = self.players.get(pid)
            if q:
                self._leave_car(q)
        self._earn(pay)
        self.sfx(S_SELL, car.x, car.y)
        self.sfx(S_CONFETTI, car.x, car.y)
        self.toast(self.rng.choice(WHOLE_SALE_LINES) % (V.model(car.model).name, pay), T_MONEY)
        del self.cars[car.id]


class ShopDoor:
    """(v0.9) The chop shop gets a roof and a roller door across its front. Bryce: "a
    closable door that blocks cops. but it needs to be opened for you to get in." So: shut,
    it's a wall -- to cop cars, officers, bullets of sight (they can't see you through it),
    and to you. E at a door (either side) rolls it up or down; honk within DOOR_REMOTE_R and
    the remote on your sun visor does it for you. It won't come down on anything: there's a
    safety sensor, and it beeps.

    (v0.10, Bryce: "make the garage door smaller, make a walking entrance and a bay for each
    player that joins") one door for the whole 28 m front became FIVE, independently opened
    and closed: a walking door (index 0, DOOR_ID+0) sized for a person, and four bay doors
    (index 1-4, DOOR_ID+1..4) each sized for one car (config.DOOR_COLS says which of the
    shop's 7 front tile-columns each sits in). The two tile-columns left over are ordinary
    WALL tiles (mapgen._make_shop), permanently solid: shutting every door really does seal
    the shop, not just narrow the gaps a witness could see through."""

    def _init_door(self):
        self.shop_doors = []
        self.door_bang_t = {}           # door id -> cooldown, so each one nags independently
        self.door_beep_t = {}
        for (i, x, y) in C.door_specs(self.map.garage_rect):
            t = Trap(C.DOOR_ID + i, TRAP_DOOR, x, y, math.pi / 2)
            t.open_t = t.goal = 1.0     # starts up: open for business
            self.shop_doors.append(t)

    def door_shut(self):
        """Every door down: the shop's fully sealed."""
        return all(d.solid() for d in self.shop_doors)

    def _door_at(self, x, y, reach=0.0):
        """Whichever door (if any) a point at (x, y) is lined up with. The bay doors sit
        edge to edge, so x stays tight to DOOR_W/2 -- widening it would make aiming at bay 1
        able to trigger bay 0's door. reach only forgives distance along y, out from the
        doorway line."""
        for d in self.shop_doors:
            if abs(x - d.x) <= C.DOOR_W / 2 and abs(y - d.y) <= reach:
                return d
        return None

    def los(self, x0, y0, x1, y1):
        """map.los (which already blocks the permanently-solid columns between doors), plus:
        a ray crossing one of the shop's door columns is blocked if that door is shut, and
        passes freely if it's open."""
        if not self.map.los(x0, y0, x1, y1):
            return False
        doors = self.shop_doors
        if not doors:
            return True
        dy = doors[0].y
        if (y0 - dy) * (y1 - dy) >= 0:
            return True                 # both ends on the same side: doesn't cross the front
        t = (dy - y0) / (y1 - y0)
        x = x0 + (x1 - x0) * t
        for d in doors:
            if abs(x - d.x) <= C.DOOR_W / 2:
                if d.id == C.DOOR_ID and abs(x - d.x) > C.WALK_DOOR_W / 2:
                    return False        # (v0.12.1) the walking door's brick jambs: always solid
                return not d.solid()
        return True                     # not a door column: map.los already ruled on it above

    def _door_blocked(self, d):
        """Anything under this particular door? Cars (their boxes), people, the dolly."""
        rx, ry, rw, rh = d.rect()
        rect = (rx, ry - 0.3, rw, rh + 0.6)
        for car in self.cars.values():
            if abs(car.y - d.y) < car.hl + 1.0 and rx - car.hl < car.x < rx + rw + car.hl:
                if obb_rect_contact(car.x, car.y, car.ang, rect, car.hl, car.hw):
                    return True
        bodies = [p for p in self.players.values() if p.state in (FOOT, TUMBLE, CUFFED, CARRIED)]
        bodies.extend(self.npcs.values())
        bodies.extend(self.dollies.values())
        for b in bodies:
            if abs(b.y - d.y) < 1.2 and circle_rect_contact(b.x, b.y, 0.45, rect):
                return True
        return False

    def toggle_door(self, d, who=None, remote=False):
        d.goal = 0.0 if d.goal > 0.5 else 1.0
        self.sfx(S_DOOR, d.x, d.y)
        if who is not None and d.goal < 0.5:
            label = "THE WALKING DOOR" if d.id == C.DOOR_ID else "THEIR BAY DOOR"
            self.toast("%s IS CLOSING %s%s" % (who.name, label, " (BEEP)" if remote else ""), T_INFO)

    def _update_door(self, dt):
        for d in self.shop_doors:
            self.door_bang_t[d.id] = self.door_bang_t.get(d.id, 0.0) - dt
            self.door_beep_t[d.id] = self.door_beep_t.get(d.id, 0.0) - dt
            was = d.solid()
            if d.open_t != d.goal:
                if d.goal < d.open_t and self._door_blocked(d):
                    d.goal = 1.0                     # the sensor: back up it goes
                    if self.door_beep_t[d.id] <= 0:
                        self.door_beep_t[d.id] = 3.0
                        self.sfx(S_DOOR, d.x, d.y)
                        self.toast("BEEP BEEP BEEP. SOMETHING'S UNDER THE DOOR.", T_WHITE)
                step = dt / C.DOOR_TIME
                if d.goal > d.open_t:
                    d.open_t = min(d.goal, d.open_t + step)
                else:
                    d.open_t = max(d.goal, d.open_t - step)
            if d.solid() != was:
                self._rebuild_trap_rects()
            if d.solid() and self.door_bang_t[d.id] <= 0:
                # cops at the door: they bang on it. They don't have a warrant. (They don't need
                # one. They just can't open a roller door. Nobody can find the button.)
                rx, ry, rw, rh = d.rect()
                for car in self.cars.values():
                    if car.kind == COP and abs(car.y - d.y) < car.hl + 1.5 and rx - 2 < car.x < rx + rw + 2:
                        self.door_bang_t[d.id] = C.DOOR_BANG_EVERY
                        self.sfx(S_BANG, car.x, car.y)
                        self.toast(self.rng.choice(DOOR_BANG_LINES), T_COP)
                        break
                else:
                    for n in self.npcs.values():
                        if n.kind == OFFICER and abs(n.y - d.y) < 2.0 and rx < n.x < rx + rw:
                            self.door_bang_t[d.id] = C.DOOR_BANG_EVERY
                            self.sfx(S_BANG, n.x, n.y)
                            self.toast(self.rng.choice(DOOR_BANG_LINES), T_COP)
                            break

    def _door_interaction(self, p, ax, ay):
        d = self._door_at(ax, ay, C.DOOR_REACH)
        if d is None or abs(p.y - d.y) > C.DOOR_REACH + 1.5:
            return None
        label = "WALKING DOOR" if d.id == C.DOOR_ID else "BAY DOOR"
        if d.open_t != d.goal:
            return (None, "THE %s'S ROLLING..." % label, 0, None)
        if d.goal > 0.5:
            return (("door", d.id), "E: SHUT THE %s (COPS CAN'T GET IN, OR SEE IN)" % label, 0,
                    lambda: self.toggle_door(d, p))
        return (("door", d.id), "E: OPEN THE %s" % label, 0, lambda: self.toggle_door(d, p))

    def _door_remote(self, p, car):
        """Honk near the shop: the garage remote on your sun visor does every bay door at
        once (not the walking door -- that one's not on the same fob)."""
        if car.kind == COP or not self.shop_doors:
            return
        near = [d for d in self.shop_doors[1:] if math.hypot(car.x - d.x, car.y - d.y) < C.DOOR_REMOTE_R]
        if not near:
            return
        opening = any(d.goal <= 0.5 for d in near)
        for d in near:
            if d.open_t == d.goal:
                d.goal = 1.0 if opening else 0.0
                self.sfx(S_DOOR, d.x, d.y)
        self.toast("%s: THE GARAGE REMOTE (BEEP)" % p.name, T_INFO)

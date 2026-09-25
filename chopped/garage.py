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
from .parts import (SLOTS, SLOT_CATEGORY, CATEGORY_SLOTS, PART_DEFS, PART_IDS, PART_INDEX, DOLLY, Part)
from . import vehicles as V

# ---- menu commands (InputState.menu_op) ----------------------------------------------
(OP_NONE, OP_CLOSE, OP_INSTALL, OP_BUY, OP_REMOVE, OP_SELL, OP_TAKE, OP_PAINT, OP_LIVERY, OP_HORN,
 OP_GLOW, OP_EXTRA) = range(12)
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
        car = self.cars.get(self.personal_id)
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
        car = self.cars.get(self.personal_id)
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
    car = world.cars.get(world.personal_id)
    out = bytearray()
    out.append(me.menu_ack & 255)
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

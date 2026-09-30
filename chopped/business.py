"""
business.py -- v0.14: the crew goes into business. A World mixin, no pygame.

Bryce: "instead of the other shops you can buy being a shop in the open, make it so they are
other garages that you have to clean out when you buy them (or pay someone to) and then its
upgraded shops (mod shop too). gate some car components from the mod shop behind the shop you
are in. also make it so the dolly needs to be upgraded via the REP points + upgrade quest to
pick up bigger motor. Also please add drop off quests for parts. make the parts seller an
auctioneer, so that the money doesn't come instantly, and you have to price your cars /
deliver them after going to the precinct and buying papers for the car."

Five things, one theme -- nothing's instant any more, and everything's a little errand:

* THE GARAGES. Shops 2-4 are walled, roofed workshops now (mapgen._make_fence), full of the last
  tenant's rubbish: JUNK_PER_SHOP solid piles (TRAP_JUNK fixtures, so they ride the wire like
  the precinct gate does). Buy the place at the sign out front, then hold E on each pile to
  shift it yourself -- a few dollars of scrap each, sometimes a knackered part -- or pay a crew
  at the sign and they carry it all out, a pile every CLEANUP_PILE_TIME. Only once it's clean do
  its crates stock up and its own tune-up counter open (with its own tier of parts:
  config.PART_SHOP_TIER, enforced in garage._ms_buy).

* DAVE THE AUCTIONEER. The sell bench is an auction counter. Whatever you bring (hands, dolly,
  or the locker from the mod shop) goes under the hammer at the price you picked (X cycles
  AUCTION_ASKS) and sells -- or doesn't -- a while later. Unsold parts go in the locker.

* PAPERS AND BUYERS. A car sold whole needs a logbook first, bought at the precinct's records
  hatch (while your face isn't on the wall behind the clerk). Papered, it goes to auction like
  anything else; when it sells, one of the city's contacts has bought it and wants it DRIVEN
  round -- park it by them and you're paid (docked for anything that fell off on the way).

* DROP-OFF ORDERS. The same contacts put in orders for parts ("three wheels, any wheels"): hand
  them over in person for ORDER_RATE x the part's value, a bonus for the full set, and a little
  REP (capped per day, so the daily jobs are still the main way up).

* MO'S DOLLY. The hand truck takes a four-pot, no more (parts.ENGINE_CLASS). Mo, behind the
  tune-up counter, builds a heavy-duty one (sixes) and an engine crane (V8s) -- once the crew's
  got the REP, and brought him what he asks for (config.DOLLY_UPGRADES).
"""

import math

from . import config as C
from .enums import *  # noqa: F401,F403
from .entities import Trap
from .parts import Part, DOLLY, engine_class, ENGINE_CLASS_NAMES
from . import vehicles as V
from .quests import wrap
from .characters import stat
from .lines import (JUNK_LINES, CLEANUP_LINES, SHOP_OPEN_LINES, AUCTION_SOLD_LINES, AUCTION_UNSOLD_LINES,
                    CAR_SOLD_LINES, CAR_UNSOLD_LINES, HANDOVER_LINES, PAPERS_LINES, PAPERS_REFUSED,
                    CONTACT_HELLO, CONTACT_NOTHING, CONTACT_THANKS, MO_MAXED)

# what a drop-off order can ask for: (category, plural label, how many min..max, weight). Order
# matters -- a category's index here is what rides the wire (protocol ORDER rows). Append only.
ORDER_CATS = (("wheel", "WHEELS", 2, 4, 5), ("door", "DOORS", 1, 2, 3), ("bumper", "BUMPERS", 1, 2, 3),
              ("hood", "HOODS", 1, 1, 2), ("exhaust", "EXHAUSTS", 1, 2, 2), ("seat", "SEATS", 1, 2, 2),
              ("ecu", "ECUS", 1, 2, 2), ("trans", "GEARBOXES", 1, 1, 2), ("spoiler", "SPOILERS", 1, 1, 1),
              ("engine", "ENGINES", 1, 1, 1))
ORDER_CAT_INDEX = {c[0]: i for i, c in enumerate(ORDER_CATS)}
# a junk pile sometimes has a part in it: nothing you'd pay money for, but it's free
JUNK_FINDS = ("whl_worn_steel", "whl_stock_alloy", "door_stock", "bmp_stock", "exh_stock", "seat_stock",
              "ecu_stock", "hood_stock", "trn_worn_4mt", "spl_lip")


class Lot:
    """One thing under Dave's hammer: a part, or a whole (papered) car by id."""
    __slots__ = ("part", "car_id", "ask", "tier", "t", "name", "who")

    def __init__(self, part, car_id, ask, tier, t, name, who=None):
        self.part, self.car_id, self.ask, self.tier, self.t, self.name = part, car_id, ask, tier, t, name
        self.who = who              # (v0.16) pid of whoever listed it: a SMOOTH TALKER's lots pay extra


def ask_price(value, tier):
    return int(round(value * C.AUCTION_ASKS[tier][1]))


def order_bonus(cat_i, need):
    """The bonus for filling a whole order (the same sum on the client, so it needn't ride the wire)."""
    return C.ORDER_BONUS_EACH * need * (3 if ORDER_CATS[cat_i][0] == "engine" else 1)


def order_label(cat_i, need):
    cat = ORDER_CATS[cat_i]
    return cat[1] if need > 1 else cat[1][:-2] if cat[1].endswith("XES") else cat[1][:-1]


class Business:
    # ------------------------------------------------------------------ setup
    def _init_business(self):
        self.junk = {}                  # shop index (1..3) -> [Trap] still standing in it
        self.cleanup = {}               # shop index -> s until the crew carries out the next pile
        self.lots = []                  # [Lot] under the hammer
        self.orders = [None] * C.ORDER_SLOTS   # {"contact", "cat", "need", "got", "bonus"} or None
        self.order_t = [0.0] * C.ORDER_SLOTS   # s until an empty slot gets a new order
        self.order_rep_today = 0
        self.dolly_level = 0            # index into what the dolly can lift (ENGINE_CLASS_NAMES)
        self.dolly_job = False          # Mo's told you what he needs for the next one
        self._reset_workshops()
        self._roll_orders()

    def _reset_workshops(self):
        """Every garage you don't own is full of junk again (SHOP SEIZED, or a fresh game)."""
        for i, fs in enumerate(self.map.fence_shops):
            idx = i + 1
            if self.shop_owned[idx] and idx in self.junk and not self.junk[idx]:
                continue                                    # yours and clean: stays clean
            self.junk[idx] = [Trap(C.JUNK_ID_BASE + i * C.JUNK_PER_SHOP + k, TRAP_JUNK, x, y, 0.0)
                              for k, (x, y) in enumerate(fs["junk"][:C.JUNK_PER_SHOP])]
            self.cleanup.pop(idx, None)
        self._rebuild_trap_rects()

    def _business_fixtures(self):
        out = []
        for piles in getattr(self, "junk", {}).values():
            out.extend(piles)
        return out

    def shop_ready(self, idx):
        """Owned, and cleared out: its crates are stocked and its counter is open."""
        if idx == 0:
            return True
        return self.shop_owned[idx] and not self.junk.get(idx)

    def shops_byte(self):
        """(wire) bits 0-3: owned. Bits 4-7: open for business (cleared out)."""
        b = 0
        for i in range(min(4, len(self.shop_owned))):
            if self.shop_owned[i]:
                b |= 1 << i
            if self.shop_ready(i):
                b |= 16 << i
        return b

    def in_shop(self, x, y):
        """The home shop's floor, or one of your cleared-out garages'."""
        if self.map.in_garage(x, y):
            return True
        i = self.map.in_workshop(x, y)
        return i >= 0 and self.shop_ready(i + 1)

    # ------------------------------------------------------------------ per tick
    def _business_tick(self, dt):
        for idx in list(self.cleanup):
            self.cleanup[idx] -= dt
            if self.cleanup[idx] <= 0:
                piles = self.junk.get(idx) or []
                if piles:
                    self._clear_junk(None, idx, piles[0])
                if self.junk.get(idx):
                    self.cleanup[idx] = C.CLEANUP_PILE_TIME
                else:
                    self.cleanup.pop(idx, None)
        self._auction_tick(dt)
        for k in range(C.ORDER_SLOTS):
            if self.orders[k] is None:
                self.order_t[k] -= dt
                if self.order_t[k] <= 0:
                    self.orders[k] = self._new_order()
        self._sale_deliveries()

    def _business_new_day(self):
        """Midnight: fresh orders, and a fresh allowance of drop-off REP."""
        self.order_rep_today = 0
        self._roll_orders()

    # ------------------------------------------------------------------ the garages
    def _junk_interaction(self, p, ax, ay):
        best, bd, where = None, 1.3, 0
        for idx, piles in self.junk.items():
            for t in piles:
                r = C.JUNK_SIZE / 2
                dx = max(abs(ax - t.x) - r, 0.0)
                dy = max(abs(ay - t.y) - r, 0.0)
                d = math.hypot(dx, dy)
                if d < bd:
                    best, bd, where = t, d, idx
        if best is None:
            return None
        what = JUNK_LINES[(best.id - C.JUNK_ID_BASE) % len(JUNK_LINES)]
        if not self.shop_owned[where]:
            return (None, "%s. BUY THE PLACE FIRST (SIGN OUT FRONT)" % what, 0, None)
        if where in self.cleanup:
            return (None, "LEAVE IT: THE CLEAN-UP CREW'S GOT IT", 0, None)
        return (("junk", best.id), "HOLD E: CLEAR OUT %s (%d LEFT)" % (what, len(self.junk[where])),
                C.JUNK_CLEAR_TIME * stat(p.char, "strip_time"), lambda: self._clear_junk(p, where, best))

    def _clear_junk(self, p, idx, t):
        piles = self.junk.get(idx) or []
        if t not in piles:
            return
        piles.remove(t)
        self._rebuild_trap_rects()
        self.sfx(S_DROP, t.x, t.y)
        if p is not None:
            scrap = self.rng.randint(*C.JUNK_SCRAP)
            self._earn(scrap)
            found = ""
            if self.rng.random() < C.JUNK_PART_CHANCE:
                part = Part(self.rng.choice(JUNK_FINDS), self.rng.uniform(0.25, 0.7))
                self.add_pickup(part, t.x, t.y)
                found = " (+ A %s)" % part.name.upper()
            if piles:
                self._tell("%s SHIFTED IT: +$%d SCRAP%s" % (p.name, scrap, found), T_MONEY)
        if not piles:
            self._shop_opened(idx)

    def _shop_opened(self, idx):
        self.cleanup.pop(idx, None)
        cx, cy = self.map.fence_shops[idx - 1]["center"]
        self.sfx(S_CASH, cx, cy)
        self._tell(self.rng.choice(SHOP_OPEN_LINES) % (idx + 1), T_MONEY)
        self._story_event("open")

    def cleanup_price(self, idx):
        left = len(self.junk.get(idx) or ())
        return int(round(C.CLEANUP_PRICE[idx] * left / float(C.JUNK_PER_SHOP)))

    def _fence_interaction(self, p, ax, ay):
        """The sign outside a garage: buy it; then, until it's clean, hire the crew."""
        for i, fs in enumerate(self.map.fence_shops):
            idx = i + 1
            sx, sy = fs["sign"]
            if math.hypot(ax - sx, ay - sy) >= C.INTERACT_RANGE_BENCH:
                continue
            if not self.shop_owned[idx]:
                price = C.SHOP_PRICE[idx]
                if self.cash < price:
                    return (None, "SHOP %d: $%d TO BUY - CAN'T AFFORD IT YET" % (idx + 1, price), 0, None)
                return (("buyshop", idx), "HOLD E: BUY SHOP %d - $%d (+$%d/DAY RENT, FULL OF JUNK)" % (
                    idx + 1, price, C.SHOP_RENT[idx]), C.BUY_TIME, lambda: self._buy_shop(idx))
            if not self.junk.get(idx):
                return None                     # clean and open: the sign's just a sign
            if idx in self.cleanup:
                return (None, "SHOP %d: THE CLEAN-UP CREW'S ON IT. %d PILES TO GO" % (
                    idx + 1, len(self.junk[idx])), 0, None)
            price = self.cleanup_price(idx)
            if self.cash < price:
                return (None, "SHOP %d: A CREW WANTS $%d TO CLEAR IT. OR HOLD E ON THE JUNK YOURSELF" % (
                    idx + 1, price), 0, None)
            return (("cleanup", idx), "HOLD E: PAY A CLEAN-UP CREW $%d (OR CLEAR THE %d PILES YOURSELF)" % (
                price, len(self.junk[idx])), C.BUY_TIME, lambda: self._hire_cleanup(idx))
        return None

    def _buy_shop(self, idx):
        if self.shop_owned[idx] or self.cash < C.SHOP_PRICE[idx]:
            return
        self.cash -= C.SHOP_PRICE[idx]
        self.shop_owned[idx] = True
        cx, cy = self.map.fence_shops[idx - 1]["center"]
        self.sfx(S_CASH, cx, cy)
        self._tell("SHOP %d IS YOURS. RENT'S UP TO $%d/DAY." % (idx + 1, self.rent_due()), T_MONEY)
        if self.junk.get(idx):
            self._tell("IT'S FULL OF THE LAST GUY'S JUNK. CLEAR IT OUT, OR PAY A CREW AT THE SIGN.", T_INFO)
        else:
            self._shop_opened(idx)
        self._story_event("buy")

    def _hire_cleanup(self, idx):
        if not self.shop_owned[idx] or not self.junk.get(idx) or idx in self.cleanup:
            return
        price = self.cleanup_price(idx)
        if self.cash < price:
            return
        self.cash -= price
        self.cleanup[idx] = C.CLEANUP_PILE_TIME
        cx, cy = self.map.fence_shops[idx - 1]["center"]
        self.sfx(S_CASH, cx, cy)
        self._tell(self.rng.choice(CLEANUP_LINES) % (idx + 1), T_INFO)

    def _workshop_bench(self, p, ax, ay):
        """A bought garage's own tune-up counter: the mod shop, at that shop's tier."""
        for i, fs in enumerate(self.map.fence_shops):
            idx = i + 1
            bx, by, bw, bh = fs["bench"]
            cx = min(max(ax, bx), bx + bw)
            cy = min(max(ay, by), by + bh)
            if math.hypot(ax - cx, ay - cy) >= C.INTERACT_RANGE_BENCH:
                continue
            if not self.shop_owned[idx]:
                return (None, "SHOP %d'S TUNE-UP COUNTER. BUY THE PLACE FIRST (SIGN OUT FRONT)" % (idx + 1), 0, None)
            if self.junk.get(idx):
                return (None, "CLEAR THE JUNK OUT FIRST (%d PILES LEFT)" % len(self.junk[idx]), 0, None)
            held = p.hands or (p.dolly is not None and p.dolly.part is not None)
            return (("modshop", idx), "E: SHOP %d MOD SHOP" % (idx + 1) +
                    (" (WHAT YOU'RE HOLDING GOES IN THE LOCKER)" if held else ""),
                    0, lambda: self._open_modshop(p, idx))
        return None

    # ------------------------------------------------------------------ Dave's auction
    def _tell(self, text, color=T_INFO):
        """A toast that might be long (names of cars, of contacts, of parts with a style on
        them): wrapped onto a second line instead of losing its end at the 60-char limit."""
        for line in wrap(text, 58):
            self.toast(line, color)

    def _cycle_ask(self, p):
        p.ask = (p.ask + 1) % len(C.AUCTION_ASKS)
        self.sfx(S_SQUEAK, p.x, p.y)

    def ask_label(self, p):
        return C.AUCTION_ASKS[p.ask][0]

    def next_hammer(self):
        return min((lot.t for lot in self.lots), default=0.0)

    def _auction_interaction(self, p):
        """Dave's counter: whatever you're holding goes under the hammer at your price."""
        if len(self.lots) >= C.AUCTION_MAX_LOTS:
            return (None, "DAVE: THE BOOK'S FULL (%d LOTS). WAIT FOR A HAMMER, %dS" % (
                len(self.lots), int(self.next_hammer()) + 1), 0, None)
        tag = self.ask_label(p)
        cycle = lambda: self._cycle_ask(p)          # noqa: E731
        if p.dolly is not None:
            d = p.dolly
            if d.part is None:
                return (None, "THE DOLLY'S EMPTY.  G: LET GO", 0, None, cycle)
            ask = ask_price(d.part.value, p.ask)
            return (("dsell", id(d.part)), "HOLD E: AUCTION %s AT $%d (%s)   X: PRICE" % (
                d.part.name.upper(), ask, tag), C.SELL_TIME, lambda: self._list_dolly(p, d), cycle)
        if not p.hands:
            lots = " %d LOTS UP, NEXT HAMMER %dS." % (len(self.lots), int(self.next_hammer()) + 1) if self.lots else ""
            return (None, "DAVE'S AUCTION:%s BRING PARTS. X: PRICE (%s)" % (lots, tag), 0, None, cycle)
        part = p.hands[-1]
        ask = ask_price(part.value, p.ask)
        return (("sell", id(part)), "HOLD E: AUCTION %s AT $%d (%s)   X: PRICE" % (part.name.upper(), ask, tag),
                C.SELL_TIME, lambda: self._sell(p), cycle)

    def _sale_pay(self, pid, amount):
        """(v0.16) money from a sale, after the seller's charm (characters: sale_bonus). pid None/gone = 1.0."""
        q = self.players.get(pid)
        return int(amount * stat(q.char, "sale_bonus")) if q is not None else int(amount)

    def _hammer_time(self, tier, car=False):
        return C.AUCTION_ASKS[tier][3] * (C.AUCTION_CAR_TIME if car else 1.0)

    def _list_part(self, part, tier, who=None):
        """Under the hammer. Returns False (and does nothing) if Dave's book is full."""
        if len(self.lots) >= C.AUCTION_MAX_LOTS:
            return False
        ask = ask_price(part.value, tier)
        t = self._hammer_time(tier)
        self.lots.append(Lot(part, None, ask, tier, t, part.name.upper(), getattr(who, "id", None)))
        self.sfx(S_SELL, *self._dave())
        self._tell("DAVE: LOT %d, %s, $%d (%s). HAMMER IN %dS" % (
            len(self.lots), part.name.upper(), ask, C.AUCTION_ASKS[tier][0], int(t)), T_INFO)
        return True

    def _sell(self, p):
        """(v0.14) the old sell bench, now Dave's auction: the part goes under the hammer."""
        if not p.hands:
            return
        if self._list_part(p.hands[-1], p.ask, p):
            p.hands.pop()
            tip = self._tip_jar()
            if tip:
                self._tell("+$%d TIP FROM A PASSERBY WHO LIKES YOUR HUSTLE" % tip, T_MONEY)

    def _list_dolly(self, p, d):
        if d.part is not None and self._list_part(d.part, p.ask, p):
            d.part = None

    def _dave(self):
        bx, by, bw, bh = self.map.sell_bench
        return bx + bw / 2, by + bh / 2

    def _list_car(self, p, car):
        if car.state != DELIVERED or not car.papers or car.lot or len(self.lots) >= C.AUCTION_MAX_LOTS:
            return
        name = V.model(car.model).name.upper()
        ask = ask_price(self.whole_price(car), p.ask)
        t = self._hammer_time(p.ask, car=True)
        self._spill_trunk(car, 2.0)                  # (the boot's contents are yours: keep them)
        car.lot = True
        self.lots.append(Lot(None, car.id, ask, p.ask, t, name, p.id))
        self.sfx(S_SELL, car.x, car.y)
        self._tell("DAVE: LOT %d, ONE %s, PAPERS AND ALL, $%d. HAMMER IN %dS" % (
            len(self.lots), name, ask, int(t)), T_INFO)

    def _lot_of(self, car):
        return next((lot for lot in self.lots if lot.car_id == car.id), None)

    def _auction_tick(self, dt):
        if not self.lots:
            return
        done = []
        for lot in self.lots:
            lot.t -= dt
            if lot.t <= 0:
                done.append(lot)
        for lot in done:
            self.lots.remove(lot)
            sold = self.rng.random() < C.AUCTION_ASKS[lot.tier][2]
            if lot.part is not None:
                if sold:
                    pay = self._sale_pay(lot.who, lot.ask)
                    self._earn(pay, 1)
                    self.sfx(S_CASH, *self._dave())
                    self._tell(self.rng.choice(AUCTION_SOLD_LINES) % (lot.name, pay), T_MONEY)
                else:
                    self._to_locker(lot.part)
                    self._tell(self.rng.choice(AUCTION_UNSOLD_LINES) % (lot.name, lot.ask), T_BAD)
                continue
            car = self.cars.get(lot.car_id)
            if car is None or car.state != DELIVERED:
                continue                             # (crushed, switched, towed: the lot's void)
            car.lot = False
            if not sold:
                self._tell(self.rng.choice(CAR_UNSOLD_LINES) % (lot.name, lot.ask), T_BAD)
                continue
            lot.ask = self._sale_pay(lot.who, lot.ask)   # (the lister's charm goes into the agreed price)
            if not self.map.contacts:
                self._earn(lot.ask)                  # (a city with nobody in it: Dave collects it himself)
                self._tell(self.rng.choice(AUCTION_SOLD_LINES) % (lot.name, lot.ask), T_MONEY)
                del self.cars[car.id]
                continue
            who = self.rng.randrange(len(self.map.contacts))
            car.sale = (who, lot.ask, self.whole_price(car))
            car.state = RUNNING                      # it's a car again: somebody has to drive it over
            car.stolen = car.alarm = False           # (papered: the cameras aren't interested)
            self.sfx(S_CASH, *self._dave())
            self._tell(self.rng.choice(CAR_SOLD_LINES) % (lot.name, self.map.contacts[who][0], lot.ask), T_MONEY)

    # ------------------------------------------------------------------ papers and buyers
    def papers_price(self, car):
        return max(C.PAPERS_MIN, int(self.whole_price(car) * C.PAPERS_RATE))

    def papers_cost(self, p, car):
        """What THIS player pays: the clerk knows a guy (characters: fee_mult)."""
        return int(self.papers_price(car) * stat(p.char, "fee_mult"))

    def _papers_candidate(self):
        best, bv = None, -1
        for car in self.cars.values():
            if car.kind != CIV or car.state != DELIVERED or car.papers or car.lot:
                continue
            v = self.whole_price(car)
            if v > bv:
                best, bv = car, v
        return best

    def _records_interaction(self, p, ax, ay):
        rec = self.map.records
        if rec is None or math.hypot(ax - rec[0], ay - rec[1]) >= C.INTERACT_RANGE_BENCH:
            return None
        if self.heat > C.PAPERS_MAX_HEAT or p.jumpsuit:
            return (None, PAPERS_REFUSED, 0, None)
        car = self._papers_candidate()
        if car is None:
            return (None, "RECORDS: PAPERS FOR A CAR YOU'VE 'BOUGHT'. GET ONE HOME TO THE SHOP FIRST.", 0, None)
        price = self.papers_cost(p, car)
        name = V.model(car.model).name.upper()
        if self.cash < price:
            return (None, "RECORDS: PAPERS FOR THE %s, $%d - CAN'T AFFORD THEM" % (name, price), 0, None)
        return (("papers", car.id), "HOLD E: BUY PAPERS FOR THE %s - $%d" % (name, price), C.PAPERS_TIME,
                lambda: self._buy_papers(p, car, price))

    def _buy_papers(self, p, car, price):
        if self.cars.get(car.id) is not car or car.papers or self.cash < price or self.heat > C.PAPERS_MAX_HEAT:
            return
        self.cash -= price
        car.papers = True
        self.sfx(S_CASH, p.x, p.y)
        line = self.rng.choice(PAPERS_LINES)
        self._tell(line % ((V.model(car.model).name.upper(), price) if line.count("%") == 2 else price), T_MONEY)

    def _delivered_car_prompt(self, p, car, res):
        """A delivered car: strip it, or (papered) put it up for auction whole."""
        cycle = lambda: self._cycle_ask(p)          # noqa: E731
        name = V.model(car.model).name.upper()
        if car.lot:
            lot = self._lot_of(car)
            return (None, "THE %s IS UNDER THE HAMMER: $%d, %dS TO GO" % (
                name, lot.ask if lot else 0, int(lot.t) + 1 if lot else 0), 0, None)
        if car.papers:
            if len(self.lots) >= C.AUCTION_MAX_LOTS:
                return (None, "DAVE'S BOOK IS FULL. WAIT FOR A HAMMER, THEN LIST THE %s" % name, 0, None, cycle)
            ask = ask_price(self.whole_price(car), p.ask)
            return (("listcar", car.id), "HOLD E: AUCTION THE %s WHOLE AT $%d (%s)   X: PRICE" % (
                name, ask, self.ask_label(p)), C.SELL_TIME, lambda: self._list_car(p, car), cycle)
        label = res[1] + "   " if res[1] else ""
        return (res[0], label + "X: SELL WHOLE?", res[2], res[3], lambda: self._no_papers(p, car))

    def _no_papers(self, p, car):
        self._say("DAVE", "NO PAPERS, NO AUCTION. THE PRECINCT'S RECORDS HATCH SELLS THEM. ABOUT $%d FOR THAT."
                  % self.papers_price(car))

    def _sale_deliveries(self):
        for car in list(self.cars.values()):
            if car.sale is None:
                continue
            who, _price, _v0 = car.sale
            if who >= len(self.map.contacts):
                continue
            _n, cx, cy, _f = self.map.contacts[who]
            if (car.x - cx) ** 2 + (car.y - cy) ** 2 < C.CONTACT_HANDOVER_R ** 2 and \
                    car.speed() < C.DELIVER_MAX_SPEED:
                self._hand_over(car)

    def _hand_over(self, car):
        who, price, v0 = car.sale
        name = self.map.contacts[who][0]
        now = self.whole_price(car)
        pay = int(price * min(1.0, now / float(v0))) if v0 > 0 else price
        for pid in car.occupants():
            q = self.players.get(pid)
            if q:
                self._leave_car(q, place=True)
        self._spill_trunk(car, 2.0)
        self._earn(pay)
        self.day_stats[0] += 1
        self.sfx(S_CASH, car.x, car.y)
        self.sfx(S_CONFETTI, car.x, car.y)
        self._tell(self.rng.choice(HANDOVER_LINES) % (name, pay), T_MONEY)
        if pay < price:
            self._tell("(THEY KNOCKED $%d OFF FOR THE BITS THAT FELL OFF ON THE WAY)" % (price - pay), T_BAD)
        del self.cars[car.id]

    def sales(self):
        """Cars sold and waiting to be driven over: [(car, contact index, price)]."""
        return [(c, c.sale[0], c.sale[1]) for c in self.cars.values() if c.sale is not None]

    # ------------------------------------------------------------------ drop-off orders
    def _roll_orders(self):
        self.orders = [None] * C.ORDER_SLOTS
        for k in range(C.ORDER_SLOTS):
            self.orders[k] = self._new_order()

    def _new_order(self):
        contacts = self.map.contacts
        if not contacts:
            return None
        busy = {o["contact"] for o in self.orders if o is not None}
        free = [i for i in range(len(contacts)) if i not in busy]
        if not free:
            return None
        who = self.rng.choice(free)
        total = sum(c[4] for c in ORDER_CATS)
        r = self.rng.uniform(0, total)
        cat_i = 0
        for i, c in enumerate(ORDER_CATS):
            r -= c[4]
            if r <= 0:
                cat_i = i
                break
        need = self.rng.randint(ORDER_CATS[cat_i][2], ORDER_CATS[cat_i][3])
        bonus = order_bonus(cat_i, need)
        return {"contact": who, "cat": cat_i, "need": need, "got": 0, "bonus": bonus}

    def _order_at(self, who):
        for k, o in enumerate(self.orders):
            if o is not None and o["contact"] == who:
                return k, o
        return None, None

    def _order_part(self, p, cat):
        """What you'd hand over for an order of this category: from your hands, or the dolly."""
        for part in reversed(p.hands):
            if part.category == cat:
                return part
        if p.dolly is not None and p.dolly.part is not None and p.dolly.part.category == cat:
            return p.dolly.part
        return None

    def _contact_interaction(self, p, ax, ay):
        best, bd = None, C.TALK_RANGE
        for i, (name, x, y, _f) in enumerate(self.map.contacts):
            d = math.hypot(x - ax, y - ay)
            if d < bd:
                best, bd = i, d
        if best is None:
            return None
        name = self.map.contacts[best][0]
        k, o = self._order_at(best)
        if o is not None:
            part = self._order_part(p, ORDER_CATS[o["cat"]][0])
            if part is not None:
                pay = int(part.value * C.ORDER_RATE)
                return (("order", k, id(part)), "HOLD E: HAND %s THE %s (+$%d) %d/%d" % (
                    name, part.name.upper(), pay, o["got"] + 1, o["need"]), C.ORDER_HANDOVER_TIME,
                    lambda: self._fill_order(p, k, part))
        return (("talk", "c%d" % best), "E: TALK TO %s" % name, 0, lambda: self._contact_talk(p, best))

    def _contact_talk(self, p, who):
        key = "c%d" % who
        if self.time < self.talk_cd.get(key, 0.0):
            return
        self.talk_cd[key] = self.time + C.TALK_COOLDOWN
        name = self.map.contacts[who][0]
        pick = self.rng.choice
        k, o = self._order_at(who)
        sale = next((c for c in self.cars.values() if c.sale is not None and c.sale[0] == who), None)
        said = False
        if sale is not None:
            self._say(name, "WHERE'S MY %s? $%d, AS AGREED. PARK IT RIGHT HERE." % (
                V.model(sale.model).name.upper(), sale.sale[1]))
            said = True
        if o is not None:
            left = o["need"] - o["got"]
            self._say(name, "%s I NEED %d MORE %s. ANY CONDITION. +$%d WHEN I'VE GOT THE LOT." % (
                pick(CONTACT_HELLO), left, order_label(o["cat"], left), o["bonus"]))
            said = True
        if not said:
            self._say(name, pick(CONTACT_NOTHING))

    def _fill_order(self, p, k, part):
        o = self.orders[k]
        if o is None or part.category != ORDER_CATS[o["cat"]][0]:
            return
        if part in p.hands:
            p.hands.remove(part)
        elif p.dolly is not None and p.dolly.part is part:
            p.dolly.part = None
        else:
            return
        name = self.map.contacts[o["contact"]][0]
        pay = self._sale_pay(p.id, part.value * C.ORDER_RATE)
        self._earn(pay, 1)
        o["got"] += 1
        self.sfx(S_SELL, p.x, p.y)
        if o["got"] < o["need"]:
            self._tell("%s TOOK THE %s: +$%d (%d/%d)" % (name, part.name.upper(), pay, o["got"], o["need"]), T_MONEY)
            return
        bonus = self._sale_pay(p.id, o["bonus"])
        self._earn(bonus)
        rep = ""
        if self.order_rep_today < C.ORDER_REP_PER_DAY:
            self.order_rep_today += 1
            self.story_points += 1
            rep = ", +1 REP"
        self.sfx(S_CASH, p.x, p.y)
        self._say(name, self.rng.choice(CONTACT_THANKS))
        self._tell("ORDER FILLED FOR %s: +$%d, +$%d BONUS%s" % (name, pay, bonus, rep), T_MONEY)
        self.orders[k] = None
        self.order_t[k] = C.ORDER_NEW_DELAY
        if rep:
            self._check_act_up()

    # ------------------------------------------------------------------ Mo and the dolly
    def dolly_fits(self, part):
        return part.bulk != DOLLY or engine_class(part.type_id) <= self.dolly_level

    def dolly_refusal(self, part):
        need = engine_class(part.type_id)
        up = C.DOLLY_UPGRADES[need - 1] if 0 < need <= len(C.DOLLY_UPGRADES) else None
        why = "A %s ON THE STOCK DOLLY? IT'D FOLD" % ENGINE_CLASS_NAMES[need] if self.dolly_level == 0 else \
            "TOO MUCH ENGINE FOR THIS DOLLY"
        if up is not None:
            return "%s. MO BUILDS THE %s (REP %d)" % (why, up[4], up[0])
        return why

    def _mo_job(self):
        return C.DOLLY_UPGRADES[self.dolly_level] if self.dolly_level < len(C.DOLLY_UPGRADES) else None

    def _mo_part(self, p):
        """What you've got that Mo's asked for, if anything (hands, or the dolly)."""
        job = self._mo_job()
        if job is None or not self.dolly_job:
            return None
        cat, min_class = job[2], job[3]
        cands = list(reversed(p.hands))
        if p.dolly is not None and p.dolly.part is not None:
            cands.append(p.dolly.part)
        for part in cands:
            if part.category == cat and (cat != "engine" or engine_class(part.type_id) >= min_class):
                return part
        return None

    def _mo_alt(self, p):
        """X at Mo's counter: talk to Mo (start his job, or hand him what he asked for)."""
        part = self._mo_part(p)
        if part is not None:
            self._mo_upgrade(p, part)
        else:
            self._mo_talk(p)

    def mo_hint(self, p):
        """The bit of the tune-up counter's prompt that's about Mo, or ''."""
        job = self._mo_job()
        if job is None:
            return ""
        if self._mo_part(p) is not None:
            return "   X: GIVE MO THE %s" % self._mo_part(p).name.upper()
        if self.story_points >= job[0]:
            return "   X: TALK TO MO (DOLLY)"
        return ""

    def _mo_talk(self, p):
        if self.time < self.talk_cd.get("mo", 0.0):
            return
        self.talk_cd["mo"] = self.time + C.TALK_COOLDOWN
        job = self._mo_job()
        if job is None:
            self._say("MO", MO_MAXED[4:])
            return
        rep, fee, cat, min_class, name = job
        if self.story_points < rep:
            self._say("MO", "THAT DOLLY TAKES A %s, NO MORE. FOR A %s I'D NEED TO KNOW YOU'RE SERIOUS. "
                            "COME BACK AT %d REP." % (ENGINE_CLASS_NAMES[self.dolly_level], name, rep))
            return
        self.dolly_job = True
        if cat == "engine":
            self._say("MO", "A %s NEEDS A TEST WEIGHT. BRING ME A %s ON THAT DOLLY, AND $%d FOR THE STEEL, "
                            "AND YOU'LL NEVER LEAVE A V8 BEHIND AGAIN." % (name, ENGINE_CLASS_NAMES[min_class], fee))
        else:
            self._say("MO", "BRING ME A GEARBOX -- ANY GEARBOX, I NEED THE BEARINGS -- AND $%d FOR THE WELDING. "
                            "I'LL BUILD YOU A %s THAT TAKES A SIX." % (fee, name))

    def _mo_upgrade(self, p, part):
        job = self._mo_job()
        if job is None or not self.dolly_job:
            return
        fee = job[1]
        if self.cash < fee:
            self._say("MO", "AND THE $%d. I DON'T WELD FOR EXPOSURE." % fee)
            return
        if part in p.hands:
            p.hands.remove(part)
        elif p.dolly is not None and p.dolly.part is part:
            p.dolly.part = None
        else:
            return
        self.cash -= fee
        self.dolly_level += 1
        self.dolly_job = False
        self.sfx(S_MOD, p.x, p.y)
        self._say("MO", self.rng.choice(("DONE. TRY NOT TO BEND IT.", "THERE. SHE'S A BEAUTY. DON'T TELL DAVE.")))
        self._tell("DOLLY UPGRADED: %s. %sS FIT NOW (-$%d)" % (job[4], ENGINE_CLASS_NAMES[self.dolly_level], fee),
                   T_MONEY)

    def mo_byte(self):
        """(wire) the dolly's level (bits 0-1) and whether Mo's job is on (bit 2)."""
        return (self.dolly_level & 3) | (4 if self.dolly_job else 0)

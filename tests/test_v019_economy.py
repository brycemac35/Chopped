"""v0.19 economy pass (QA's edits): a bigger auction book, an honest ask ladder with a GREEDY
listing fee, dearer fence-shop rent, smaller drop-off bonuses, the papers errand (direction,
compass hint, choosing which car gets them)."""

import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import business as B
from chopped import vehicles as V
from chopped.parts import Part
from test_v014 import quiet_world, step, delivered, snap, DT


def at_hatch(w, p):
    rx, ry = w.map.records
    p.x, p.y = rx, ry + 1.8
    p.ang = p.input.yaw = -math.pi / 2


class TestBook(unittest.TestCase):
    def test_base_cap_and_growth_per_open_garage(self):
        w = quiet_world()
        self.assertEqual(C.AUCTION_MAX_LOTS, 16)
        self.assertEqual(w.lot_cap(), 16)
        w.shop_owned[1] = True                       # bought but still full of junk: no extra lots
        self.assertEqual(w.lot_cap(), 16)
        w.junk[1] = []                               # cleared out: open
        self.assertEqual(w.lot_cap(), 16 + C.AUCTION_LOTS_PER_SHOP)
        w.shop_owned[2], w.junk[2] = True, []
        self.assertEqual(w.lot_cap(), 16 + 2 * C.AUCTION_LOTS_PER_SHOP)

    def test_full_book_refuses_and_prompts(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        for _ in range(w.lot_cap()):
            self.assertTrue(w._list_part(Part("ecu_stock"), 1))
        self.assertFalse(w._list_part(Part("ecu_stock"), 1))
        self.assertIn("BOOK'S FULL", w._auction_interaction(p)[1])
        w.shop_owned[1], w.junk[1] = True, []
        self.assertTrue(w._list_part(Part("ecu_stock"), 1), "an open garage makes room")


class TestAsks(unittest.TestCase):
    def test_ladder_numbers(self):
        got = [(a[1], a[2], a[3]) for a in C.AUCTION_ASKS]
        self.assertEqual(got, [(0.7, 1.0, 10.0), (1.0, 0.85, 25.0), (1.25, 0.75, 40.0), (1.6, 0.40, 60.0)])
        ev = [a[1] * a[2] for a in C.AUCTION_ASKS]
        self.assertLess(ev[0], ev[1], "QUICK no longer beats FAIR outright")

    def test_unsold_greedy_costs_a_fee_others_free(self):
        w = quiet_world()
        w.rng.random = lambda: 0.99                  # nobody bids
        for tier in (1, 2):                          # (QUICK always sells: nothing to fail)
            w.cash = 1000
            part = Part("door_stock", 1.0)
            w._list_part(part, tier)
            w.lots[0].t = 0.0
            w.step(DT)
            self.assertIn(part, w.stash)
            self.assertEqual(w.cash, 1000, "tier %d returns free" % tier)
        w.cash = 1000
        part = Part("door_stock", 1.0)
        w._list_part(part, 3)
        ask = w.lots[0].ask
        w.lots[0].t = 0.0
        w.step(DT)
        self.assertIn(part, w.stash)
        self.assertEqual(w.cash, 1000 - int(round(ask * 0.10)))
        self.assertTrue(any("LISTING FEE" in t for t in [e[3][1] for e in w.events if e[2] == 0]))

    def test_fee_clamps_at_zero_cash(self):
        w = quiet_world()
        w.rng.random = lambda: 0.99
        w._list_part(Part("eng_bike_600", 1.0), 3)
        w.cash = 3
        w.lots[0].t = 0.0
        w.step(DT)
        self.assertEqual(w.cash, 0)

    def test_sold_greedy_pays_no_fee_and_smooth_applies_once(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        p.char = 3                                   # SMOOTH
        w.rng.random = lambda: 0.0
        part = Part("door_stock", 1.0)
        w._list_part(part, 3, p)
        ask = w.lots[0].ask
        w.cash = 0
        w.lots[0].t = 0.0
        w.step(DT)
        self.assertEqual(w.cash, w._sale_pay(p.id, ask))
        self.assertEqual(w.cash, int(ask * B.stat(3, "sale_bonus")))

    def test_locker_and_dolly_paths_list_at_fair(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        self.assertEqual(p.ask, C.AUCTION_DEFAULT_ASK)
        part = Part("door_stock", 1.0)
        w.stash.append(part)
        self.assertTrue(w._list_part(part, C.AUCTION_DEFAULT_ASK, p))
        self.assertEqual(w.lots[0].ask, B.ask_price(part.value, 1))
        self.assertEqual(w.lots[0].t, C.AUCTION_ASKS[1][3])

    def test_whole_car_listing(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        car = delivered(w)
        car.papers = True
        p.ask = 3
        w._list_car(p, car)
        self.assertTrue(car.lot)
        self.assertEqual(w.lots[0].ask, B.ask_price(w.whole_price(car), 3))
        self.assertEqual(w.lots[0].t, 60.0 * C.AUCTION_CAR_TIME)
        w.rng.random = lambda: 0.99
        cash = w.cash = 5000
        w.lots[0].t = 0.0
        w.step(DT)
        self.assertFalse(car.lot)
        self.assertLess(w.cash, cash, "unsold GREEDY car still costs the fee")


class TestRentAndOrders(unittest.TestCase):
    def test_rent_and_bonus_numbers(self):
        self.assertEqual(C.SHOP_RENT, (100, 300, 600, 1200))
        self.assertEqual(C.ORDER_BONUS_EACH, 30)
        self.assertEqual(B.order_bonus(B.ORDER_CAT_INDEX["wheel"], 2), 60)
        w = quiet_world()
        w.shop_owned[1] = True
        self.assertEqual(w.rent_due(), 100 + 300)


class TestPapersErrand(unittest.TestCase):
    def _sell_prompt(self, w, p, car):
        res = w._delivered_car_prompt(p, car, (None, "", 0, None))
        return res

    def test_refusal_gives_direction_and_sets_hint(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        car = delivered(w)
        self.assertFalse(w.wants_papers(p))
        self._sell_prompt(w, p, car)[4]()
        say = " ".join(e[3][1] for e in w.events if e[2] == 0)
        self.assertIn("RECORDS HATCH", say)
        self.assertIn("M ", say)
        self.assertTrue(any(d in say for d in ("NORTH", "SOUTH", "EAST", "WEST")))
        self.assertTrue(w.wants_papers(p))
        self.assertTrue(snap(w, p).papers_hint)
        # buy them: hint goes
        at_hatch(w, p)
        w.cash = 10_000
        w._find_interaction(p)[3]()
        self.assertTrue(car.papers)
        self.assertFalse(w.wants_papers(p))
        self.assertFalse(snap(w, p).papers_hint)

    def test_x_cycles_the_cars_and_e_buys_the_shown_one(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        a = delivered(w, V.COUPE)
        b = delivered(w, V.KEI) if hasattr(V, "KEI") else delivered(w, V.SEDAN)
        w.cash = 10_000
        at_hatch(w, p)
        res = w._find_interaction(p)
        first = res[0][1]
        self.assertIn("X: NEXT CAR (1/2)", res[1])
        self.assertIn(V.model(w.cars[first].model).name.upper(), res[1])
        res[4]()                                     # X
        res = w._find_interaction(p)
        second = res[0][1]
        self.assertNotEqual(first, second)
        self.assertIn("(2/2)", res[1])
        res[3]()                                     # E
        self.assertTrue(w.cars[second].papers)
        self.assertFalse(w.cars[first].papers)
        res = w._find_interaction(p)
        self.assertEqual(res[0][1], first, "only one left, offered by default")
        self.assertEqual(len(res), 4, "no cycle with a single car")

    def test_default_is_still_the_priciest(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        a = delivered(w, V.COUPE)
        b = delivered(w, V.SEDAN)
        top = max((a, b), key=w.whole_price)
        self.assertIs(w._papers_candidate(p), top)


if __name__ == "__main__":
    unittest.main()

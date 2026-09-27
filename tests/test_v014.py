"""v0.14: the garages you buy (junk, a clean-up crew, their own tier of mod shop), Dave the
auctioneer, papers from the precinct and buyers across town, drop-off orders, Mo's dolly
upgrades, and the arrest ride (carried to the cop car, driven to the station)."""

import math
import os
import random
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import savefile as SF
from chopped import vehicles as V
from chopped import garage as G
from chopped import business as B
from chopped.parts import SLOTS, Part, model_loadout, engine_class
from chopped.predict import trap_row_solid

DT = 1 / 60.0


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


def step(w, secs):
    for _ in range(int(round(secs / DT))):
        w.step(DT)


def toasts(w):
    return [e[3][1] for e in w.events if e[2] == 0]


def delivered(w, model=V.COUPE):
    gx, gy, gw, gh = w.map.garage_rect
    car = S.Car(w.new_id(), S.CIV, gx + gw / 2, gy + gh / 2 + 3, 0.0,
                model_loadout(random.Random(3), model), model=model)
    car.state, car.stolen = S.DELIVERED, True
    w.cars[car.id] = car
    return car


def look(p, x, y, back=1.4):
    """Stand `back` m south of (x, y), facing it."""
    p.x, p.y = x, y + back
    p.ang = p.input.yaw = -math.pi / 2


def snap(w, p):
    return P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])


class TestGarages(unittest.TestCase):
    def test_every_garage_is_walled_roofed_and_full_of_junk(self):
        w = quiet_world()
        self.assertEqual(len(w.map.fence_shops), 3)
        for i, fs in enumerate(w.map.fence_shops):
            fx, fy, fw, fh = fs["rect"]
            self.assertEqual((fw, fh), (20.0, 20.0))
            self.assertTrue(w.map.solid_at(fx - 2.0, fy + fh / 2), "brick walls round the side")
            self.assertFalse(w.map.solid_at(fx + fw / 2, fy + fh + 2.0), "an opening at the front")
            self.assertEqual(len(w.junk[i + 1]), C.JUNK_PER_SHOP)
            self.assertEqual(w.map.in_workshop(fx + 5, fy + 5), i)
        self.assertFalse(w.shop_ready(1))
        self.assertTrue(all(t.solid() for t in w.junk[1]), "junk is in the way")
        self.assertIn(w.junk[1][0].rect(), w.tall_rects)

    def test_buy_then_clear_it_yourself_for_scrap(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.cash = 100_000
        w._buy_shop(1)
        self.assertTrue(w.shop_owned[1])
        self.assertFalse(w.shop_ready(1), "bought, but still full of the last guy's sofa")
        t = w.junk[1][0]
        look(p, t.x, t.y, 1.0 + C.JUNK_SIZE / 2)
        key, label = w._find_interaction(p)[:2]
        self.assertEqual(key, ("junk", t.id))
        self.assertIn("CLEAR OUT", label)
        cash = w.cash
        w._find_interaction(p)[3]()
        self.assertNotIn(t, w.junk[1])
        self.assertGreaterEqual(w.cash - cash, C.JUNK_SCRAP[0])
        for t in list(w.junk[1]):
            w._clear_junk(p, 1, t)
        self.assertTrue(w.shop_ready(1))
        self.assertEqual(w.shops_byte() & 0x22, 0x22, "owned (bit 1) and open (bit 5)")
        self.assertTrue(any("OPEN FOR BUSINESS" in t or "SPOTLESS" in t for t in toasts(w)))

    def test_or_pay_a_crew_who_carry_it_out_one_pile_at_a_time(self):
        w = quiet_world()
        w.cash = 100_000
        w._buy_shop(1)
        price = w.cleanup_price(1)
        self.assertEqual(price, C.CLEANUP_PRICE[1])
        cash = w.cash
        w._hire_cleanup(1)
        self.assertEqual(w.cash, cash - price)
        step(w, C.CLEANUP_PILE_TIME + 0.1)
        self.assertEqual(len(w.junk[1]), C.JUNK_PER_SHOP - 1)
        step(w, C.CLEANUP_PILE_TIME * C.JUNK_PER_SHOP)
        self.assertTrue(w.shop_ready(1))

    def test_unbought_junk_isnt_yours_to_clear(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        t = w.junk[2][0]
        look(p, t.x, t.y, 1.0 + C.JUNK_SIZE / 2)
        key, label = w._find_interaction(p)[:2]
        self.assertIsNone(key)
        self.assertIn("BUY THE PLACE FIRST", label)

    def test_a_garage_you_open_takes_deliveries_and_has_its_own_mod_shop(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.cash = 100_000
        w._buy_shop(2)
        fs = w.map.fence_shops[1]
        bx, by, bw, bh = fs["bench"]
        p.x, p.y = bx - 1.5, by + bh / 2
        p.ang = p.input.yaw = 0.0
        self.assertIn("CLEAR THE JUNK OUT FIRST", w._find_interaction(p)[1])
        for t in list(w.junk[2]):
            w._clear_junk(None, 2, t)
        key, label, _, action = w._find_interaction(p)[:4]
        self.assertIn("SHOP 3 MOD SHOP", label)
        action()
        self.assertTrue(p.menu)
        self.assertEqual(p.menu_tier, 2)
        fx, fy, fw, fh = fs["rect"]
        self.assertTrue(w.in_shop(fx + 10, fy + 10))
        step(w, 0.2)
        self.assertTrue(p.menu, "the menu stays open on a garage's floor")

    def test_seizure_fills_them_back_up(self):
        w = quiet_world()
        w.cash = 100_000
        w._buy_shop(1)
        for t in list(w.junk[1]):
            w._clear_junk(None, 1, t)
        w.reset_run()
        self.assertFalse(w.shop_owned[1])
        self.assertEqual(len(w.junk[1]), C.JUNK_PER_SHOP)

    def test_junk_rides_the_wire_and_the_predictor_bumps_into_it(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        t = w.junk[1][0]
        p.x, p.y = t.x, t.y + 6
        s = snap(w, p)
        self.assertIn(t.id, s.traps)
        self.assertTrue(trap_row_solid(s.traps[t.id]))


class TestModShopTiers(unittest.TestCase):
    def test_the_home_counter_wont_sell_the_fancy_stuff(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w.cash = 100_000
        w._open_modshop(p, 0)
        car = w.cars[w.personal_id]
        cat = G.catalogue("Engine")
        k = next(i for i, (tid, _s, _p) in enumerate(cat) if tid == "eng_sc_6_2")
        before = car.parts["Engine"]
        p.input.menu_seq, p.input.menu_op, p.input.menu_arg, p.input.menu_arg2 = 1, G.OP_BUY, k, SLOTS.index("Engine")
        w.step(DT)
        self.assertIs(car.parts["Engine"], before, "the supercharged V8 is shop 4's")
        self.assertEqual(w.cash, 100_000)
        p.menu_tier = 3
        p.input.menu_seq = 2
        w.step(DT)
        self.assertEqual(car.parts["Engine"].type_id, "eng_sc_6_2")

    def test_the_menu_carries_the_counters_tier(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w._open_modshop(p, 2)
        s = snap(w, p)
        self.assertEqual(s.menu["tier"], 2)


class TestAuction(unittest.TestCase):
    def test_dave_lists_it_and_pays_at_the_hammer(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        bx, by, bw, bh = w.map.sell_bench
        wheel = Part("whl_stock_alloy", 1.0)
        p.hands = [wheel]
        look(p, bx + bw / 2, by + bh, 1.2)
        label = w._find_interaction(p)[1]
        self.assertIn("AUCTION ALLOY WHEEL AT $%d (FAIR)" % wheel.value, label)
        w._find_interaction(p)[4]()                      # X: the price
        self.assertEqual(p.ask, 2)
        self.assertIn("(PUNCHY)", w._find_interaction(p)[1])
        p.ask = 0
        cash = w.cash
        w._sell(p)
        tip = w.cash - cash
        self.assertEqual(p.hands, [])
        self.assertEqual(len(w.lots), 1)
        step(w, C.AUCTION_ASKS[0][3] + 0.1)
        self.assertEqual(w.cash, cash + tip + B.ask_price(wheel.value, 0))
        self.assertEqual(w.lots, [])

    def test_no_bid_goes_back_in_the_locker(self):
        w = quiet_world()
        part = Part("door_stock", 1.0)
        w._list_part(part, 3)
        w.lots[0].t = 0.0
        w.rng.random = lambda: 0.99                      # nobody's that keen
        w.step(DT)
        self.assertIn(part, w.stash)

    def test_the_book_fills_up(self):
        w = quiet_world()
        for _ in range(C.AUCTION_MAX_LOTS):
            self.assertTrue(w._list_part(Part("ecu_stock"), 1))
        self.assertFalse(w._list_part(Part("ecu_stock"), 1))


class TestPapersAndBuyers(unittest.TestCase):
    def test_papers_auction_and_a_drive_across_town(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        car = delivered(w)
        w.cash = 10_000
        # the records hatch at the precinct
        rx, ry = w.map.records
        p.x, p.y = rx, ry + 1.8
        p.ang = p.input.yaw = -math.pi / 2
        key, label, _, action = w._find_interaction(p)[:4]
        price = w.papers_price(car)
        self.assertEqual(key, ("papers", car.id))
        self.assertIn("$%d" % price, label)
        w.heat = C.PAPERS_MAX_HEAT + 5
        self.assertIn("FACE IS ON THE WALL", w._find_interaction(p)[1])
        w.heat = 0
        action()
        self.assertTrue(car.papers)
        self.assertEqual(w.cash, 10_000 - price)
        # list it (QUICK SALE: always goes)
        p.ask = 0
        w._list_car(p, car)
        self.assertTrue(car.lot)
        lot = w.lots[0]
        step(w, lot.t + 0.1)
        self.assertIsNotNone(car.sale, "sold: now somebody has to drive it over")
        self.assertEqual(car.state, S.RUNNING)
        self.assertFalse(car.stolen, "papered: the cameras don't care")
        who, agreed, _v = car.sale
        s = snap(w, p)
        self.assertEqual(s.sales, [(car.id, who, agreed)])
        # getting in isn't a theft
        heat = w.heat
        w._enter_car(p, car, S.DRIVER)
        self.assertEqual(w.heat, heat)
        # park it by the buyer
        _n, cx, cy, _f = w.map.contacts[who]
        car.x, car.y = cx + 3.0, cy
        car.vx = car.vy = 0.0
        cash = w.cash
        w.step(DT)
        self.assertNotIn(car.id, w.cars)
        self.assertEqual(w.cash, cash + agreed)
        self.assertEqual(p.state, S.FOOT)

    def test_bits_falling_off_on_the_way_cost_you(self):
        w = quiet_world()
        car = delivered(w)
        car.papers = True
        car.state, car.stolen = S.RUNNING, False
        car.sale = (0, 1000, w.whole_price(car))
        car.parts["DoorL"] = None
        car.parts["BumperF"] = None
        cash = w.cash
        w._hand_over(car)
        self.assertLess(w.cash - cash, 1000)

    def test_no_papers_no_auction(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        car = delivered(w)
        w._list_car(p, car)
        self.assertFalse(car.lot)


class TestOrders(unittest.TestCase):
    def test_hand_a_contact_what_they_ordered(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.orders[0] = {"contact": 0, "cat": B.ORDER_CAT_INDEX["wheel"], "need": 2, "got": 0,
                       "bonus": B.order_bonus(B.ORDER_CAT_INDEX["wheel"], 2)}
        _n, cx, cy, _f = w.map.contacts[0]
        p.x, p.y = cx, cy + 1.6
        p.ang = p.input.yaw = -math.pi / 2
        w1, w2 = Part("whl_stock_alloy", 1.0), Part("whl_stock_alloy", 1.0)
        p.hands = [w1, w2]
        key, label, _, action = w._find_interaction(p)[:4]
        self.assertEqual(key[0], "order")
        self.assertIn("1/2", label)
        cash, rep = w.cash, w.story_points
        action()
        self.assertEqual(w.cash, cash + int(w1.value * C.ORDER_RATE))
        w._find_interaction(p)[3]()
        self.assertIsNone(w.orders[0], "filled")
        self.assertEqual(w.cash, cash + 2 * int(w1.value * C.ORDER_RATE) + B.order_bonus(0, 2))
        self.assertEqual(w.story_points, rep + 1, "a little REP for a filled order")
        step(w, C.ORDER_NEW_DELAY + 0.1)
        self.assertIsNotNone(w.orders[0], "a new one comes in")

    def test_drop_off_rep_is_capped_per_day(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        rep = w.story_points
        for k in range(C.ORDER_REP_PER_DAY + 2):
            w.orders[0] = {"contact": 0, "cat": 0, "need": 1, "got": 0, "bonus": 60}
            part = Part("whl_stock_alloy")
            p.hands = [part]
            w._fill_order(p, 0, part)
        self.assertEqual(w.story_points, rep + C.ORDER_REP_PER_DAY)

    def test_orders_go_over_the_wire(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        s = snap(w, p)
        live = [o for o in w.orders if o is not None]
        self.assertEqual(len(s.orders), len(live))
        self.assertEqual(s.orders[0], (live[0]["contact"], live[0]["cat"], 0, live[0]["need"]))


class TestDolly(unittest.TestCase):
    def test_the_stock_dolly_wont_take_a_v8(self):
        w = quiet_world()
        self.assertTrue(w.dolly_fits(Part("eng_stock_1_6")))
        self.assertFalse(w.dolly_fits(Part("eng_v6_3_0")))
        self.assertFalse(w.dolly_fits(Part("eng_v8_5_7")))
        self.assertIn("MO BUILDS", w.dolly_refusal(Part("eng_v8_5_7")))
        self.assertEqual(engine_class("eng_sc_6_2"), 2)

    def test_mos_jobs_need_the_rep_the_part_and_the_fee(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.cash = 5000
        w._mo_alt(p)
        self.assertFalse(w.dolly_job, "not enough REP yet")
        w.story_points = C.DOLLY_UPGRADES[0][0]
        w.talk_cd.clear()
        w._mo_alt(p)
        self.assertTrue(w.dolly_job)
        box = Part("trn_stock_5mt")
        p.hands = [box]
        self.assertIn("GIVE MO", w.mo_hint(p))
        w._mo_alt(p)
        self.assertEqual(w.dolly_level, 1)
        self.assertEqual(w.cash, 5000 - C.DOLLY_UPGRADES[0][1])
        self.assertEqual(p.hands, [])
        self.assertTrue(w.dolly_fits(Part("eng_v6_3_0")))
        self.assertFalse(w.dolly_fits(Part("eng_v8_5_7")))
        # the crane: a six-cylinder on the dolly, and more REP
        w.story_points = C.DOLLY_UPGRADES[1][0]
        w.talk_cd.clear()
        w._mo_alt(p)
        d = next(iter(w.dollies.values()))
        w._grab_dolly(p, d)
        d.part = Part("eng_v6_3_0")
        w._mo_alt(p)
        self.assertEqual(w.dolly_level, 2)
        self.assertIsNone(d.part)
        self.assertTrue(w.dolly_fits(Part("eng_sc_6_2")))

    def test_the_dolly_level_is_saved(self):
        w = quiet_world()
        w.dolly_level = 2
        w.cash = 100_000
        w._buy_shop(1)
        for t in list(w.junk[1])[:5]:
            w._clear_junk(None, 1, t)
        w.lots.append(B.Lot(Part("ecu_tuned"), None, 500, 1, 10.0, "ECU"))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crew.json")
            SF.save_to(w, path)
            w2 = S.World(map_seed=w.map_seed, rng_seed=5)
            self.assertTrue(SF.load_into(w2, path))
        self.assertEqual(w2.dolly_level, 2)
        self.assertEqual(len(w2.junk[1]), C.JUNK_PER_SHOP - 5, "half-cleared stays half-cleared")
        self.assertEqual(len(w2.junk[2]), C.JUNK_PER_SHOP)
        self.assertTrue(any(q.type_id == "ecu_tuned" for q in w2.stash), "a lot under the hammer goes back on the shelf")


class TestArrestRide(unittest.TestCase):
    def setUp(self):
        self.w = w = quiet_world()
        self.p = p = w.add_player("BRYCE")
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw + 30, gy + gh + 6
        self.cop = S.Car(w.new_id(), S.COP, p.x + 14, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[self.cop.id] = self.cop

    def cuffed(self):
        for _ in range(int(8 / DT)):
            self.w.heat = 30
            self.w.step(DT)
            if self.p.arrests:
                return
        self.fail("never got cuffed")

    def test_carried_to_the_car_and_driven_to_the_precinct(self):
        w, p, cop = self.w, self.p, self.cop
        self.cuffed()
        self.assertEqual(p.state, S.CARRIED)
        n = w.npcs[p.escort]
        self.assertEqual(n.mode, 5)
        self.assertAlmostEqual(p.z, 1.25, places=2)
        for _ in range(int(6 / DT)):
            w.step(DT)
            if p.state == S.PASSENGER:
                break
        self.assertEqual(p.state, S.PASSENGER)
        self.assertEqual(cop.prisoner, p.id)
        w.step(DT)
        self.assertIn("COP CAR", p.prompt)
        p.input.exit_count += 1                           # no door handles in the back
        w.step(DT)
        self.assertEqual(p.state, S.PASSENGER)
        t = 0.0
        while not p.jailed and t < C.ARREST_RIDE_MAX:
            w.step(DT)
            t += DT
        self.assertTrue(p.jailed)
        self.assertLess(t, C.ARREST_RIDE_MAX - 1.0, "he drove there, not the timeout's van")
        self.assertTrue(w.map.in_precinct(p.x, p.y))

    def test_punch_the_officer_and_the_prisoner_drops(self):
        w, p = self.w, self.p
        self.cuffed()
        n = w.npcs[p.escort]
        n.tumble_t = 1.0                                   # a crewmate's haymaker, say
        w.step(DT)
        self.assertIsNone(p.escort)
        self.assertEqual(p.state, S.TUMBLE)

    def test_carjack_the_cop_car_and_the_prisoners_free(self):
        w, p, cop = self.w, self.p, self.cop
        self.cuffed()
        for _ in range(int(6 / DT)):
            w.step(DT)
            if p.state == S.PASSENGER:
                break
        q = w.add_player("CREW")
        cop.vx = cop.vy = 0.0
        w._steal_cop_car(q, cop)
        self.assertIsNone(cop.prisoner)
        self.assertEqual(p.state, S.PASSENGER)
        p.input.exit_count += 1
        w.step(DT)
        self.assertEqual(p.state, S.FOOT, "an ordinary passenger now: out you get")

    def test_no_car_nearby_means_the_old_van(self):
        w, p, cop = self.w, self.p, self.cop
        n = S.NPC(w.new_id(), S.OFFICER, p.x + 1, p.y)
        w.npcs[n.id] = n
        w.arrest(p, officer=n)                             # (a carless officer)
        self.assertEqual(p.state, S.CUFFED)
        step(w, C.CUFFED_TIME + 0.1)
        self.assertTrue(p.jailed)


class TestWire(unittest.TestCase):
    def test_the_business_block_round_trips(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.dolly_level, w.dolly_job, p.ask = 1, True, 3
        w._list_part(Part("ecu_stock"), 1)
        s = snap(w, p)
        self.assertEqual((s.dolly & 3, bool(s.dolly & 4), s.ask, s.lots), (1, True, 3, 1))
        self.assertEqual(s.hammer, int(math.ceil(C.AUCTION_ASKS[1][3])))

    def test_business_is_pygame_free(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chopped", "business.py")
        tree = ast.parse(open(path).read())
        names = [a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names]
        names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any("pygame" in n for n in names))


if __name__ == "__main__":
    unittest.main()

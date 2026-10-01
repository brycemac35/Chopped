"""(v0.19) the jack: bolt a wheel back on a car parked outside the shop, 15 s, crew-owned tool
bought at shop 2's counter or better."""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import garage as G
from chopped import protocol as P
from chopped import savefile as SF
from chopped import vehicles as V
from chopped.parts import Part, SLOTS, wheel_slots, kei_loadout, cop_loadout

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def press(p, buttons):
    i = p.input
    p.input = S.InputState(buttons, i.use_count, i.drop_count, i.exit_count, i.yaw)


def quiet_world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    for cid in [c.id for c in w.cars.values() if c.kind == S.TRAFFIC]:
        del w.cars[cid]
    return w


def parked_car(w, kind=S.CIV, model=V.KEI, state=S.RUNNING):
    """A stationary car out in the street (no shop floor under it), well away from everyone."""
    car = next(c for c in w.cars.values() if c.kind == S.CIV and not w.in_shop(c.x, c.y))
    car.kind, car.model, car.state = kind, model, state
    car.stolen = kind == S.CIV
    car.vx = car.vy = car.w = 0.0
    car.driver = car.passenger = None
    car.parts = cop_loadout(w.rng) if kind == S.COP else kei_loadout(w.rng)
    if V.model(model).wheels == 2:
        car.parts = {s: car.parts.get(s) for s in SLOTS}
        for s in V.model(model).no_slots:
            car.parts[s] = None
    car.patrol = kind == S.COP               # (a parked patrol car isn't 'calm': dispatch won't tow it mid-jack)
    car.refresh()
    return car


def stand_at(p, car, slot):
    """Put the player where their aim point lands on the car's `slot` hub, looking in at it."""
    wx, wy = car.to_world(*car.anchor(slot))
    side = -1.0 if car.anchor(slot)[1] < 0 else 1.0
    if V.model(car.model).wheels == 2:
        side = 1.0
    ang = car.ang - side * math.pi / 2          # looking from the outside towards the car's middle
    p.x, p.y = wx - math.cos(ang) * C.AIM_REACH, wy - math.sin(ang) * C.AIM_REACH
    p.input = S.InputState(0, p.input.use_count, p.input.drop_count, p.input.exit_count, ang)
    p.ang = ang


def setup(kind=S.CIV, model=V.KEI, slot="WheelFL", jack=True, state=S.RUNNING):
    w = quiet_world()
    p = w.add_player("ALICE")
    w.has_jack = jack
    car = parked_car(w, kind, model, state)
    lost = car.parts[slot]
    car.parts[slot] = None
    car.refresh()
    p.hands = [Part("whl_stock_alloy", 1.0)]
    stand_at(p, car, slot)
    return w, p, car


def buy_jack(w, p, tier):
    w._open_modshop(p, tier)
    p.input.menu_seq = (p.menu_ack + 1) & 255
    p.input.menu_op, p.input.menu_arg, p.input.menu_arg2 = G.OP_EXTRA, G.EXTRA_JACK, 0
    w.step(DT)


class TestBuyingTheJack(unittest.TestCase):
    def test_the_home_counter_wont_sell_it(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w.cash = 1000
        buy_jack(w, p, 0)
        self.assertFalse(w.has_jack)
        self.assertEqual(w.cash, 1000)

    def test_shop_2_sells_it_once_and_charges_once(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w.cash = 1000
        buy_jack(w, p, 1)
        self.assertTrue(w.has_jack)
        self.assertEqual(w.cash, 1000 - C.PRICE_JACK)
        buy_jack(w, p, 1)                          # you already own one
        buy_jack(w, p, 3)
        self.assertEqual(w.cash, 1000 - C.PRICE_JACK)

    def test_cant_afford_it(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w.cash = C.PRICE_JACK - 1
        buy_jack(w, p, 1)
        self.assertFalse(w.has_jack)
        self.assertEqual(w.cash, C.PRICE_JACK - 1)

    def test_the_menu_shows_owned_and_the_tier(self):
        from chopped import modshop as M
        import pygame
        w = quiet_world()
        p = w.add_player("BRYCE")
        w._open_modshop(p, 0)
        menu = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]).menu
        self.assertFalse(menu["jack"])
        ms = M.ModShop(None)
        ms.menu, ms.cat = menu, next(i for i, c in enumerate(M.CATS) if c[1] == "extra")
        row = ms.items()[G.EXTRA_JACK]
        self.assertEqual(row.right, "SHOP 2 ONLY")
        self.assertEqual(row.op, G.OP_NONE)
        w.has_jack = True
        menu = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]).menu
        ms.menu = menu
        self.assertEqual(ms.items()[G.EXTRA_JACK].right, "OWNED")
        ms.menu = dict(menu, jack=False, tier=1)
        self.assertEqual(ms.items()[G.EXTRA_JACK].right, "$%d" % C.PRICE_JACK)

    def test_save_and_load_keeps_the_jack(self):
        w = quiet_world()
        w.has_jack = True
        data = SF.dump(w)
        w2 = quiet_world()
        self.assertFalse(w2.has_jack)
        self.assertTrue(SF.apply(w2, data))
        self.assertTrue(w2.has_jack)
        d = tempfile.mkdtemp()
        path = os.path.join(d, "s.json")
        self.assertTrue(SF.save_to(w, path))
        w3 = quiet_world()
        self.assertTrue(SF.load_into(w3, path))
        self.assertTrue(w3.has_jack)

    def test_an_old_save_means_no_jack_and_seizure_takes_it(self):
        w = quiet_world()
        data = SF.dump(w)
        del data["has_jack"]
        w.has_jack = True
        SF.apply(w, data)
        self.assertFalse(w.has_jack)
        w.has_jack = True
        w.reset_run()
        self.assertFalse(w.has_jack)


class TestJackingItUp(unittest.TestCase):
    def test_prompt_then_fit_takes_15_seconds(self):
        w, p, car = setup()
        self.assertEqual(car.missing_wheels(), 1)
        w.step(DT)
        self.assertIn("JACK IT UP AND BOLT ON ALLOY WHEEL (15s)", p.prompt)
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME - 0.5)
        self.assertIsNone(car.parts["WheelFL"])
        self.assertGreater(p.hold_frac, 0.9)
        step(w, 1.0)
        self.assertEqual(car.parts["WheelFL"].type_id, "whl_stock_alloy")
        self.assertEqual(car.missing_wheels(), 0)
        self.assertEqual(p.hands, [])

    def test_the_car_is_drivable_again(self):
        w, p, car = setup()
        bare = car.grip
        w.step(DT)
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 0.5)
        self.assertGreater(car.grip, bare, "four wheels grip better than three")
        self.assertEqual(car.grip, V.performance(V.model(car.model), car.parts)[0] * V.model(car.model).grip)

    def test_letting_go_or_looking_away_starts_it_over(self):
        w, p, car = setup()
        w.step(DT)
        press(p, S.B_USE)
        step(w, 10.0)
        press(p, 0)
        step(w, 0.2)
        self.assertEqual(p.hold, 0.0)
        press(p, S.B_USE)
        w.step(DT)
        step(w, 6.0)                              # 6 + 10 > 15, but the first 10 are gone
        self.assertIsNone(car.parts["WheelFL"])
        # now look away mid-hold
        p.input = S.InputState(S.B_USE, p.input.use_count, p.input.drop_count, p.input.exit_count, p.ang + math.pi)
        p.ang += math.pi
        step(w, 0.2)
        self.assertEqual(p.hold, 0.0)
        self.assertIsNone(car.parts["WheelFL"])

    def test_needs_the_jack(self):
        w, p, car = setup(jack=False)
        w.step(DT)
        self.assertEqual(p.prompt, "NEED A JACK (SHOP 2)")
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 1)
        self.assertIsNone(car.parts["WheelFL"])
        self.assertEqual(len(p.hands), 1)

    def test_needs_a_wheel_in_hand(self):
        w, p, car = setup()
        p.hands = []
        w.step(DT)
        self.assertNotIn("JACK", p.prompt)
        p.hands = [Part("ecu_stock", 1.0)]
        w.step(DT)
        self.assertNotIn("JACK", p.prompt)
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 1)
        self.assertIsNone(car.parts["WheelFL"])

    def test_an_occupied_hub_is_not_a_jack_job(self):
        w, p, car = setup()
        stand_at(p, car, "WheelFR")               # that one's still on
        w.step(DT)
        self.assertNotIn("JACK", p.prompt)

    def test_the_other_bare_hub_is_found_by_aim(self):
        w, p, car = setup()
        car.parts["WheelRR"] = None
        stand_at(p, car, "WheelRR")
        w.step(DT)
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 0.5)
        self.assertIsNotNone(car.parts["WheelRR"])
        self.assertIsNone(car.parts["WheelFL"])
        self.assertEqual(car.missing_wheels(), 1)

    def test_refuses_a_moving_or_occupied_car(self):
        w, p, car = setup()
        car.vx = 5.0
        w.step(DT)
        self.assertIn("MOVING", p.prompt)
        car.vx = 0.0
        car.driver = p
        w.step(DT)
        self.assertIn("SITTING IN IT", p.prompt)

    def test_works_on_every_kind_of_car(self):
        for kind, state in ((S.CIV, S.RUNNING), (S.CIV, S.LOCKED), (S.PERSONAL, S.RUNNING),
                            (S.TRAFFIC, S.RUNNING), (S.COP, S.RUNNING)):
            with self.subTest(kind=kind, state=state):
                w, p, car = setup(kind=kind, state=state)
                w.step(DT)
                self.assertIn("JACK IT UP", p.prompt)
                press(p, S.B_USE)
                step(w, C.JACK_FIT_TIME + 0.5)
                self.assertIsNotNone(car.parts["WheelFL"])

    def test_not_inside_the_shop(self):
        w, p, car = setup()
        bx, by, ba = w.map.bays[1]
        car.x, car.y, car.ang = bx, by, ba
        stand_at(p, car, "WheelFL")
        self.assertTrue(w.in_shop(car.x, car.y))
        w.step(DT)
        self.assertNotIn("JACK", p.prompt)


class TestBikes(unittest.TestCase):
    def test_a_bike_has_two_hubs_and_the_jack_finds_them(self):
        w, p, car = setup(model=V.SPORTBIKE, slot="WheelRL")
        self.assertEqual(wheel_slots(car.model), ("WheelFL", "WheelRL"))
        self.assertEqual(car.missing_wheels(), 1)
        w.step(DT)
        self.assertIn("JACK IT UP", p.prompt)
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 0.5)
        self.assertIsNotNone(car.parts["WheelRL"])
        self.assertEqual(car.missing_wheels(), 0)
        # and a bike has no right-hand hubs to point at: nothing to bolt
        self.assertIsNone(car.parts.get("WheelRR"))


class TestPredictionUntouched(unittest.TestCase):
    def test_the_self_block_does_not_know_about_jacks(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        before = P.encode_self(w, p)
        w.has_jack = True
        self.assertEqual(P.encode_self(w, p), before)

    def test_fitting_a_wheel_is_server_side_grip_only(self):
        # the predictor re-derives grip from the car state it is sent (parts ride the car rows),
        # so there is nothing new to put in SELF: the fitted car's refresh() is the same call
        w, p, car = setup()
        press(p, S.B_USE)
        step(w, C.JACK_FIT_TIME + 0.5)
        car2 = parked_car(w)
        self.assertAlmostEqual(car.grip, car2.grip)


class TestQAFollowUps(unittest.TestCase):
    """(v0.20) found by the jack QA bot."""

    def test_no_jack_doesnt_steal_the_trunk_from_a_spare_wheel(self):
        w, p, car = setup(slot="WheelRL", jack=False)
        w.step(DT)
        self.assertNotIn("NEED A JACK", p.prompt, "the boot should get the first go at the spare wheel")

    def test_no_jack_still_says_so_at_a_front_hub(self):
        w, p, car = setup(slot="WheelFL", jack=False)
        w.step(DT)
        self.assertIn("NEED A JACK", p.prompt)

    def test_a_tumble_needs_a_fresh_press_of_e(self):
        w, p, car = setup()
        press(p, S.B_USE)
        step(w, 2.0)
        p.state, p.tumble_t = S.TUMBLE, 0.5
        p.hands = []
        step(w, 1.5)
        self.assertNotEqual(p.state, S.DRIVER, "still holding E after the tumble mustn't hop you in")


if __name__ == "__main__":
    unittest.main()

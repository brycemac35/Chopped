"""v0.18.2 playtest fixes (sim side): bought garages aren't sanctuary, sold traffic cars aren't towed,
the dolly picks the right engine, held parts don't hijack the rear strip, break-in heat doesn't
cool early, the haymaker lands (and whiffs loudly), and SLIM's locked-car prompt tells the truth."""

import math
import os
import random
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped.lines import WHIFF_LINES
from chopped.parts import model_loadout

DT = 1 / 60.0
DASH, SPANNER, SLIM, SMOOTH = 0, 1, 2, 3


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


def inp(p, **kw):
    i = p.input
    d = dict(buttons=i.buttons, use_count=i.use_count, drop_count=i.drop_count, exit_count=i.exit_count, yaw=i.yaw,
             fire_count=i.fire_count, weapon=i.weapon)
    d.update(kw)
    p.input = S.InputState(**d)


def delivered(w, x=None, y=None, ang=0.0, model=V.COUPE):
    gx, gy, gw, gh = w.map.garage_rect
    car = S.Car(w.new_id(), S.CIV, gx + gw / 2 if x is None else x, gy + gh / 2 + 3 if y is None else y, ang,
                model_loadout(random.Random(3), model), model=model)
    car.state, car.stolen = S.DELIVERED, True
    w.cars[car.id] = car
    return car


def locked_car(w, p):
    car = next(c for c in w.cars.values() if c.kind == S.CIV and c.state == S.LOCKED and c.special is None
               and not V.is_bike(c.model))
    p.x, p.y = car.to_world(0.0, -2.0)
    p.ang = p.input.yaw = math.atan2(car.y - p.y, car.x - p.x)
    return car


def street(w):
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2 + 30, gy + gh + 10.0


def ped(w, x, y):
    n = S.NPC(w.new_id(), S.PED, x, y)
    n.dirx = n.diry = 0
    n.turn_t = 1e9
    w.npcs[n.id] = n
    return n


class TestBoughtGarageIsNotSanctuary(unittest.TestCase):      # bug 2
    def _fence_spot(self, w):
        w.cash = 100_000
        w._buy_shop(1)
        for t in list(w.junk[1]):
            w._clear_junk(None, 1, t)
        fx, fy, fw, fh = w.map.fence_shops[0]["rect"]       # shop_owned[1] is fence_shops[0]
        self.assertTrue(w.shop_ready(1))
        return fx + fw / 2, fy + fh / 2

    def test_cops_and_peds_still_want_you_in_a_bought_garage(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        p.x, p.y = self._fence_spot(w)
        self.assertTrue(w.in_shop(p.x, p.y), "still a shop for crates and deliveries")
        w.heat = 50
        self.assertIn(p, w._law_targets())
        self.assertTrue(any(t[5] is p for t in w._collect_targets()))
        n = ped(w, p.x + 3, p.y)
        n.foe, n.hostile_t = p.id, 5.0
        w._brawler(n, DT)
        self.assertGreater(n.hostile_t, 0, "a brawler follows you in")

    def test_home_shop_is_still_a_sanctuary(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw / 2, gy + gh / 2
        w.heat = 50
        self.assertNotIn(p, w._law_targets())
        self.assertFalse(any(t[5] is p for t in w._collect_targets()))


class TestSoldCarsAreNeverTowed(unittest.TestCase):           # bug 3
    def _bailed(self, w):
        car = delivered(w, 40.0, 40.0)
        car.state, car.kind = S.RUNNING, S.CIV
        car.stolen, car.bailed = False, True
        return car

    def test_clear_lanes_spares_a_sold_car(self):
        w = quiet_world()
        car = self._bailed(w)
        car.sale = (0, 500, 500)
        car.idle_pos, car.idle_t = (car.x, car.y), C.WRECK_CLEAR_TIME + 100
        w.players.clear()
        w._clear_lanes(DT)
        self.assertIn(car.id, w.cars)
        car.sale, car.lot = None, True
        w._clear_lanes(DT)
        self.assertIn(car.id, w.cars, "nor one on the auction block")

    def test_a_wreck_nobody_wants_is_still_towed(self):
        w = quiet_world()
        car = self._bailed(w)
        car.idle_pos, car.idle_t = (car.x, car.y), C.WRECK_CLEAR_TIME + 100
        w.players.clear()
        w._clear_lanes(DT)
        self.assertNotIn(car.id, w.cars)

    def test_taking_the_car_clears_the_bailed_flag(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = self._bailed(w)
        w._enter_car(p, car, S.DRIVER)
        self.assertFalse(car.bailed)
        self.assertTrue(car.stolen)


class TestDollyPicksTheRightEngine(unittest.TestCase):        # bug 4
    def test_nearest_engine_in_reach_wins_over_first_in_range(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        p.x, p.y = 8.0, 8.0
        far = delivered(w, p.x + 3.0, p.y, ang=math.pi)           # its engine is on the far side, out of reach
        near = delivered(w, 0.0, p.y)                              # inserted second, engine right at the dolly
        ex, _ = near.anchor("Engine")
        near.x = p.x + 0.5 - ex
        d = S.Dolly(w.new_id(), p.x + 1.0, p.y) if hasattr(S, "Dolly") else type("D", (), {"x": p.x + 1.0, "y": p.y})()
        got, reach = w._engine_car_near(p, d)
        self.assertIs(got, near)
        self.assertTrue(reach)
        self.assertIsNot(got, far)


class TestHeldPartsDontBlockTheRearStrip(unittest.TestCase):  # bug 5
    def _aim_rear_wheel(self, w, p, car):
        lx, ly = car.anchor("WheelRL")
        x, y = car.to_world(lx, ly - 0.5)                         # just outside the body, at the wheel
        p.x, p.y = x - 0.6, y
        p.ang = p.input.yaw = 0.0
        return x, y

    def test_holding_a_wheel_still_strips_the_rear_wheel(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = delivered(w)
        donor = delivered(w, 0.0, 0.0)
        p.hands = [donor.parts["WheelFL"]]
        self._aim_rear_wheel(w, p, car)
        key = w._find_interaction(p)[0]
        self.assertIsNotNone(key)
        self.assertEqual(key[0], "strip")
        self.assertEqual(key[2], "WheelRL")

    def test_a_full_trunk_prompt_still_wins_when_there_is_loot(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = delivered(w)
        donor = delivered(w, 0.0, 0.0)
        car.trunk.append(donor.parts["WheelFR"])
        p.hands = [donor.parts["WheelFL"]]
        self._aim_rear_wheel(w, p, car)
        self.assertEqual(w._find_interaction(p)[0][0], "trunk_in")


class TestBreakInHeatResetsCooling(unittest.TestCase):        # bug 10
    def test_break_in_resets_the_cooling_timer(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = locked_car(w, p)
        w.unseen_t = 99.0
        w._break_in(p, car)
        self.assertEqual(w.unseen_t, 0.0)
        self.assertGreater(w.heat, 0)

    def test_wrong_wire_resets_the_cooling_timer(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = locked_car(w, p)
        w.unseen_t = 99.0
        w.rng.randrange = lambda n: 1                              # never the right wire
        w._cut_wires(p, car)
        self.assertEqual(w.unseen_t, 0.0)
        self.assertGreater(w.heat, 0)


class TestHaymaker(unittest.TestCase):                        # bug 11
    def _setup(self, with_ped=True):
        w = quiet_world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.ang = p.input.yaw = 0.0
        n = ped(w, p.x + 1.3, p.y) if with_ped else None
        return w, p, n

    def _press(self, w, p):
        inp(p, buttons=S.B_FIRE, fire_count=p.input.fire_count + 1)
        w.step(DT)
        inp(p, buttons=S.B_FIRE)

    def test_the_press_does_not_punch_first(self):
        w, p, n = self._setup()
        self._press(w, p)
        step(w, 0.3)
        self.assertEqual(n.tumble_t, 0.0, "still winding up: nobody's been touched yet")
        self.assertIsNone(n.thrown_by)

    def test_held_to_full_charge_is_a_home_run(self):
        w, p, n = self._setup()
        self._press(w, p)
        step(w, C.HAYMAKER_CHARGE + 0.1)
        inp(p, buttons=0)
        w.step(DT)
        self.assertEqual(p.banner, S.BN_HOMERUN)
        self.assertEqual(n.thrown_by, p.id)

    def test_a_quick_release_is_an_ordinary_punch(self):
        w, p, n = self._setup()
        self._press(w, p)
        step(w, 0.15)
        inp(p, buttons=0)
        step(w, 0.1)
        self.assertGreater(n.tumble_t, 0.0, "the punch landed")
        self.assertNotEqual(p.banner, S.BN_HOMERUN)

    def test_a_click_shorter_than_a_tick_still_punches(self):
        w, p, n = self._setup()
        inp(p, buttons=0, fire_count=p.input.fire_count + 1)
        w.step(DT)
        self.assertGreater(n.tumble_t, 0.0)

    def test_a_whiffed_haymaker_says_so(self):
        w, p, _ = self._setup(with_ped=False)
        self._press(w, p)
        step(w, C.HAYMAKER_CHARGE + 0.1)
        inp(p, buttons=0)
        w.step(DT)
        self.assertTrue(set(l % p.name for l in WHIFF_LINES) & set(toasts(w)), toasts(w))


class TestSlimsPrompt(unittest.TestCase):                     # SMALL
    def _label(self, char):
        w = quiet_world()
        p = w.add_player("X", char)
        locked_car(w, p)
        return w._find_interaction(p)

    def test_slim_is_not_told_it_rings_nor_offered_the_worse_way(self):
        res = self._label(SLIM)
        self.assertNotIn("ALARM", res[1])
        self.assertNotIn("CUT THE WIRES", res[1])
        self.assertIn("SILENT", res[1])
        self.assertTrue(len(res) == 4 or res[4] is None)

    def test_everyone_else_keeps_the_alarm_warning_and_the_x_option(self):
        for char in (DASH, SPANNER, SMOOTH):
            res = self._label(char)
            self.assertIn("SETS OFF ALARM", res[1])
            self.assertIn("X: CUT THE WIRES INSTEAD (SLOWER)", res[1])
            self.assertIsNotNone(res[4])


if __name__ == "__main__":
    unittest.main()

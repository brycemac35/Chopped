"""The hand dolly (engines finally pay full price) and the parts counter."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped.parts import Part, SLOT_ANCHOR

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def press(p, buttons):
    i = p.input
    p.input = S.InputState(buttons, i.use_count, i.drop_count, i.exit_count, i.yaw)


def face(p, x, y):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, math.atan2(y - p.y, x - p.x))
    p.ang = p.input.yaw


def tap(p, field):
    i = p.input
    counts = [i.use_count, i.drop_count, i.exit_count]
    counts[field] += 1
    p.input = S.InputState(i.buttons, *counts, yaw=i.yaw)


USE, DROP, EXIT = 0, 1, 2


def quiet_world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    for cid in [c.id for c in w.cars.values() if c.kind == S.TRAFFIC]:
        del w.cars[cid]
    return w


def the_dolly(w):
    return next(iter(w.dollies.values()))


def grab(w, p):
    d = the_dolly(w)
    p.x, p.y = d.x - 1.0, d.y
    face(p, d.x, d.y)
    tap(p, USE)
    w.step(DT)
    return d


def delivered_car(w):
    car = next(c for c in w.cars.values() if c.kind == S.CIV)
    gx, gy, gw, gh = w.map.garage_rect
    car.x, car.y, car.ang = gx + gw / 2, gy + gh / 2 + 3, 0.0
    car.state, car.stolen = S.DELIVERED, True
    car.parts["Engine"] = Part("eng_stock_1_6", 1.0)
    return car


class TestDolly(unittest.TestCase):
    def test_strip_an_engine_onto_the_dolly_and_sell_it_for_full_price(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        car = delivered_car(w)
        engine = car.parts["Engine"]
        d = grab(w, p)
        self.assertIs(p.dolly, d)
        self.assertEqual(d.holder, p.id)
        self.assertEqual(p.hands_used(), 2, "the dolly takes both hands")
        self.assertFalse(p.can_hold(Part("ecu_stock")))
        # at the engine bay, hood still on: told to take it off first
        ex, ey = car.to_world(*SLOT_ANCHOR["Engine"])
        p.x, p.y = ex + 2.4, ey
        face(p, ex, ey)
        w.step(DT)
        self.assertIn("HOOD", p.prompt)
        car.parts["Hood"] = None
        w.step(DT)
        self.assertIn("STRIP 1.6 ENGINE ONTO THE DOLLY", p.prompt)
        press(p, S.B_USE)
        step(w, S.STRIP_TIME["engine"] - 1.0)     # not yet: engines take ages
        self.assertIsNotNone(car.parts["Engine"])
        step(w, 1.5)
        self.assertIsNone(car.parts["Engine"])
        self.assertIs(d.part, engine)
        press(p, 0)
        w.step(DT)
        # wheel it to the sell bench: full value, not the crusher's 50%
        bx, by, bw, bh = w.map.sell_bench
        p.x, p.y = bx + bw / 2, by + bh + 1.2
        face(p, bx + bw / 2, by)
        cash0 = w.cash
        w.step(DT)
        self.assertIn("SELL 1.6 ENGINE", p.prompt)
        press(p, S.B_USE)
        step(w, C.SELL_TIME + 0.1)
        self.assertEqual(w.cash, cash0 + engine.value)
        self.assertIsNone(d.part)

    def test_dolly_engine_goes_in_the_locker_at_the_mod_shop(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        d = grab(w, p)
        turbo = Part("eng_tuned_2_0t", 1.0)
        d.part = turbo
        tx, ty, tw, th = w.map.tune_bench
        p.x, p.y = tx + tw / 2, ty + th + 1.2
        face(p, tx + tw / 2, ty)
        w.step(DT)
        self.assertIn("MOD SHOP", p.prompt)
        key, _, _, action = w._find_interaction(p)
        action()
        self.assertTrue(p.menu)
        self.assertIn(turbo, w.stash, "the engine goes on the locker shelf")
        self.assertIsNone(d.part)

    def test_loose_engine_needs_the_dolly(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        gx, gy, gw, gh = w.map.garage_rect
        pk = w.add_pickup(Part("eng_tuned_2_0t", 0.8), gx + 8, gy + 20)   # e.g. from an exploded cop
        p.x, p.y = pk.x + 0.5, pk.y
        p.ang = math.pi
        key, label, _, _ = w._find_interaction(p)
        self.assertIsNone(key)
        self.assertIn("FETCH THE DOLLY", label, "the old prompt wrongly said HANDS FULL")
        d = grab(w, p)
        p.x, p.y = pk.x - 1.5, pk.y
        face(p, pk.x, pk.y)
        w.step(DT)
        self.assertIn("LOAD 2.0 TURBO ENGINE", p.prompt)
        press(p, S.B_USE)
        step(w, C.DOLLY_LOAD_TIME + 0.1)
        self.assertIs(d.part, pk.part)
        self.assertNotIn(pk.id, w.pickups)

    def test_pushing_speeds_and_stamina(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        d = grab(w, p)
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + 4, gy + 14
        face(p, gx + 20, gy + 14)
        press(p, S.B_UP)
        step(w, 1.0)
        self.assertAlmostEqual(p.vx, C.WALK_SPEED * C.DOLLY_SPEED_MULT, delta=0.05)
        self.assertEqual(p.stamina, C.STAMINA_MAX, "an empty dolly is no workout")
        d.part = Part("eng_stock_1_6")
        p.x = gx + 4
        step(w, 1.0)
        self.assertAlmostEqual(p.vx, C.WALK_SPEED * C.DOLLY_LOADED_SPEED_MULT, delta=0.05)
        self.assertLess(p.stamina, C.STAMINA_MAX - 5, "a loaded one is")
        self.assertAlmostEqual(math.hypot(d.x - p.x, d.y - p.y), C.DOLLY_OFFSET, delta=0.05)

    def test_let_go_car_and_arrest_all_drop_the_dolly_where_you_stand(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        d = grab(w, p)
        tap(p, DROP)
        w.step(DT)
        self.assertIsNone(p.dolly)
        self.assertIsNone(d.holder)
        d = grab(w, p)
        personal = w.cars[w.personal_id]
        w._enter_car(p, personal, S.DRIVER)
        self.assertIsNone(d.holder, "getting in a car lets go")
        w._leave_car(p)
        d = grab(w, p)
        d.part = Part("eng_stock_1_6")
        w.arrest(p)
        self.assertIsNone(d.holder)
        self.assertIsNotNone(d.part, "the engine stays on the dolly for your partner")

    def test_abandoned_dolly_comes_home(self):
        w = quiet_world()
        d = the_dolly(w)
        d.x, d.y = 20.0, 6.0
        step(w, C.DOLLY_RETURN_TIME + 0.5)
        self.assertEqual((d.x, d.y), w.map.dolly_spot)

    def test_dolly_goes_over_the_wire(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        d = grab(w, p)
        d.part = Part("eng_tuned_2_0t")
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        row = snap.dollies[d.id]
        self.assertEqual(row[5], p.id)
        self.assertNotEqual(row[4], 255)
        self.assertTrue(snap.players[p.id][3] & P.PF_DOLLY)
        self.assertAlmostEqual(snap.me[11], C.DOLLY_LOADED_SPEED_MULT, places=5)
        self.assertEqual(snap.me[1], 2)


if __name__ == "__main__":
    unittest.main()

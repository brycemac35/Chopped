"""v0.7 tyre physics: the things that make drifting feel like drifting, pinned
down so a tuning tweak can't quietly turn it back into a shopping trolley."""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped.parts import Part, model_loadout

DT = 1.0 / C.SIM_HZ


class Lot(S.Physics):
    """An endless empty car park: no walls, no grass, no witnesses."""
    class _Map:
        def tile_at(self, x, y):
            return 1

        def solid_rects_near(self, x, y, r, out):
            pass

    def __init__(self):
        self.map = self._Map()
        self.cars = {}
        self._rects = []
        self.extra_rects = []


def car(model=V.KEI, tuned=False, speed=0.0):
    parts = S.personal_loadout() if model == V.KEI else model_loadout(random.Random(1), model)
    if tuned:
        for slot, tid in (("Engine", "eng_tuned_2_0t"), ("Transmission", "trn_tuned_6mt"), ("ECU", "ecu_tuned")):
            parts[slot] = Part(tid, 1.0)
    c = S.Car(1, S.CIV, 0, 0, 0.0, parts, model=model)
    c.driver, c.state = 1, S.RUNNING
    c.vx = speed
    return c


def drive(c, secs, buttons, lot=None):
    lot = lot or Lot()
    for _ in range(int(round(secs / DT))):
        S.drive_input(c, buttons)
        lot._drive(c, DT)
    return c


def slip_deg(c):
    return abs(math.degrees(Lot().slip_angle(c)))


class TestTyres(unittest.TestCase):
    def test_straight_line_is_straight(self):
        c = drive(car(), 3.0, S.B_UP)
        self.assertLess(abs(c.ang), 1e-6)
        self.assertLess(abs(c.y), 1e-6)
        self.assertGreater(c.speed(), 20)

    def test_handbrake_turn_rotates_harder_than_steering(self):
        steer = drive(car(speed=20.0), 0.6, S.B_RIGHT)
        hand = drive(car(speed=20.0), 0.6, S.B_RIGHT | S.B_HANDBRAKE)
        self.assertGreater(abs(hand.ang), abs(steer.ang) * 1.5, "yank it and the tail comes round")
        self.assertGreater(slip_deg(hand), 12, "...sideways")

    def test_power_oversteer_in_a_tuned_rwd_car(self):
        c = drive(car(V.MUSCLE, tuned=True, speed=12.0), 1.0, S.B_UP | S.B_RIGHT)
        self.assertGreater(slip_deg(c), 15, "boot it mid-corner and the tail steps out")

    def test_hands_off_catches_the_slide(self):
        c = drive(car(speed=20.0), 0.5, S.B_RIGHT | S.B_HANDBRAKE)
        self.assertGreater(slip_deg(c), 10)
        drive(c, 1.5, S.B_UP)                       # throttle, no steering: caster straightens it
        self.assertLess(slip_deg(c), 8, "the front wheels follow the car; it comes back straight")

    def test_front_drive_van_does_not_power_slide(self):
        c = drive(car(V.VAN, tuned=True, speed=12.0), 1.0, S.B_UP | S.B_RIGHT)
        self.assertLess(slip_deg(c), 12, "front-wheel drive understeers instead")

    def test_brakes_stop_you(self):
        c = car(speed=30.0)
        t = 0.0
        lot = Lot()
        while c.speed() > 0.3 and t < 5:
            S.drive_input(c, S.B_DOWN)
            lot._drive(c, DT)
            t += DT
        self.assertLess(t, 2.5)

    def test_parked_cars_stay_put_after_a_shove(self):
        c = car()
        c.driver, c.state = None, S.LOCKED
        c.vy = 6.0
        drive(c, 1.5, 0)
        self.assertLess(c.speed(), 0.05)
        self.assertLess(abs(c.y), 3.0)

    def test_models_have_different_top_speeds(self):
        tops = {}
        for mid in (V.KEI, V.COUPE, V.VAN, V.SCOOTER):
            c = car(mid)
            drive(c, 25.0, S.B_UP)
            tops[mid] = c.speed()
        self.assertGreater(tops[V.COUPE], tops[V.KEI])
        self.assertGreater(tops[V.KEI], tops[V.VAN])
        self.assertLess(tops[V.SCOOTER], 13.0, "the mobility scooter: flat out, at a jog")

    def test_banana_spin(self):
        a = car(speed=18.0)
        b = car(speed=18.0)
        b.spin_t = C.BANANA_SPIN_TIME
        b.w = C.BANANA_SPIN_KICK
        drive(a, 0.8, S.B_UP)
        drive(b, 0.8, S.B_UP)
        self.assertGreater(slip_deg(b), slip_deg(a) + 20)


class TestJumpPrediction(unittest.TestCase):
    def test_predicted_jump_matches_the_host(self):
        from chopped.mapgen import CityMap
        from chopped.predict import Predictor
        from chopped import protocol as P
        w = S.World(map_seed=4242, rng_seed=1)
        w.traffic_target = w.patrol_target = 0
        for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
            del w.cars[cid]
        p = w.add_player("HOPPY")
        pr = Predictor(CityMap(w.map_seed))
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0, 0)[P.HDR.size:]))
        script = [S.B_UP | S.B_JUMP] * 40 + [S.B_UP] * 30
        for seq, b in enumerate(script, 1):
            pr.push_input(seq, b, p.ang)
            w.set_input(p.id, S.InputState(b, yaw=p.ang))
            w.step(DT)
            self.assertAlmostEqual(pr.body.z, p.z, places=4)
            self.assertAlmostEqual(pr.body.x, p.x, places=3)
        self.assertEqual(p.z, 0.0)


if __name__ == "__main__":
    unittest.main()

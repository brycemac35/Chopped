"""v0.8 cars: revs, gears, turbos and superchargers, the engine notes, brake
stands and donuts, a drift you can catch, rice rockets and 4x4s."""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped import drivetrain as DT
from chopped import enginesynth as ES
from chopped import protocol as P
from chopped import parts as PT
from chopped.parts import Part, model_loadout

from test_drift import car, Lot, slip_deg, drive

DTS = 1.0 / C.SIM_HZ


class TestTacho(unittest.TestCase):
    def test_it_shifts_up_through_the_box(self):
        t = DT.Tacho(PT.V_I4, PT.ASP_NA, 5)
        gears, events = [], []
        for k in range(600):
            v = 45.0 * k / 600
            events += t.update(v, 1.0, 45.0, dt=1 / 60)
            gears.append(t.gear)
            self.assertGreaterEqual(t.rpm, t.idle - 1)
            self.assertLessEqual(t.rpm, t.redline * 1.03)
        self.assertEqual(gears[0], 1)
        self.assertEqual(max(gears), 5, "all the way to top gear")
        self.assertEqual(gears, sorted(gears), "never shifts down while accelerating")
        self.assertIn("shift", events)

    def test_brake_stand_bangs_off_the_limiter(self):
        t = DT.Tacho(PT.V_V8, PT.ASP_NA, 4)
        events = []
        for _ in range(120):
            events += t.update(0.3, 1.0, 50.0, spin=1.0, burnout=True, dt=1 / 60)
        self.assertGreater(t.rpm, t.redline * 0.9)
        self.assertIn("limiter", events)

    def test_turbo_spools_then_blows_off(self):
        t = DT.Tacho(PT.V_I4T, PT.ASP_TURBO, 6)
        for _ in range(240):
            t.update(30.0, 1.0, 50.0, dt=1 / 60)
        self.assertGreater(t.boost, 0.6, "spooled")
        ev = t.update(30.0, 0.0, 50.0, dt=1 / 60)
        self.assertIn("bov", ev, "pssssh")
        self.assertIn("lift", ev)

    def test_supercharger_boost_is_the_revs(self):
        t = DT.Tacho(PT.V_V8, PT.ASP_SC, 6)
        for _ in range(60):
            t.update(20.0, 1.0, 50.0, dt=1 / 60)
        self.assertAlmostEqual(t.boost, min(1.0, t.rpm / t.redline), places=5)

    def test_vtec_kicks_in_yo(self):
        t = DT.Tacho(PT.V_VTEC, PT.ASP_NA, 5)
        seen = False
        for k in range(300):
            seen = seen or "vtec" in t.update(3.0 + k * 0.05, 1.0, 48.0, dt=1 / 60)
        self.assertTrue(seen)

    def test_engine_byte_roundtrip(self):
        for voice in range(9):
            for asp in (PT.ASP_NA, PT.ASP_TURBO, PT.ASP_SC):
                for gears in (0, 4, 5, 6):
                    self.assertEqual(DT.unpack_engine_byte(DT.engine_byte(voice, asp, gears)), (voice, asp, gears))

    def test_band_weights_bracket_and_sum_to_one(self):
        rpms = DT.band_rpms(PT.V_V8)
        self.assertEqual(len(rpms), C.ENGINE_BANDS)
        for rpm in (300, rpms[0], 2000, 4321, rpms[-1], 20000):
            i, wi, j, wj = DT.band_weights(rpms, rpm)
            self.assertEqual(j, i + 1)
            self.assertAlmostEqual(wi + wj, 1.0)


class TestEngineNotes(unittest.TestCase):
    def test_every_voice_loops_cleanly_and_is_not_silent(self):
        rate = 22050
        voices = list(ES.VOICES) + [PT.V_ELECTRIC]
        for voice in voices:
            for sc in (False, True):
                for rpm in (900, 4000, 7500):
                    x, actual = ES.render_engine(voice, rpm, rate, supercharged=sc, redline=8000, vtec_rpm=5000)
                    self.assertGreater(len(x), rate * 0.1)
                    self.assertLessEqual(max(abs(v) for v in x), 1.0)
                    self.assertGreater(max(abs(v) for v in x), 0.3, "an engine you can hear")
                    # the loop's seam is no bigger a jump than the waveform makes anyway
                    jumps = sorted(abs(x[i + 1] - x[i]) for i in range(len(x) - 1))
                    seam = abs(x[0] - x[-1])
                    self.assertLessEqual(seam, jumps[-1] + 1e-9, "voice %d rpm %d loops without a click" % (voice, rpm))

    def test_higher_revs_higher_pitch(self):
        rate = 22050

        def fundamental(x):
            # autocorrelation peak between 25 and 400 Hz: the note you hear
            x = x[:3000:2]
            r = rate / 2.0
            best, lag = -1e9, 1
            for L in range(int(r / 400), int(r / 25)):
                c = sum(a * b for a, b in zip(x, x[L:]))
                if c > best:
                    best, lag = c, L
            return r / lag
        for voice in (PT.V_I4, PT.V_V8):
            lo, _ = ES.render_engine(voice, 1500, rate)
            hi, _ = ES.render_engine(voice, 6000, rate)
            self.assertGreater(fundamental(hi), fundamental(lo) * 1.5, "voice %d: rev it, it rises" % voice)

    def test_the_little_noises(self):
        rate = 22050
        for x in (ES.render_bov(rate), ES.render_bov(rate, True), ES.render_pop(rate), ES.render_screech(rate),
                  ES.render_whistle(4000, rate), ES.render_shift(rate)):
            self.assertTrue(x)
            self.assertLessEqual(max(abs(v) for v in x), 1.0)


class TestBurnouts(unittest.TestCase):
    def test_brake_stand_spins_on_the_spot_and_donuts(self):
        c = car(V.MUSCLE, tuned=True)
        drive(c, 2.0, S.B_UP | S.B_DOWN)
        self.assertLess(math.hypot(c.x, c.y), 1.5, "it barely creeps")
        self.assertEqual(c.wheelspin, 1.0)
        self.assertGreater(c.smoke_t, 1.9)
        c2 = car(V.MUSCLE, tuned=True)
        drive(c2, 1.5, S.B_UP | S.B_DOWN | S.B_RIGHT)
        self.assertGreater(abs(c2.ang), 1.0, "donuts")
        self.assertLess(math.hypot(c2.x, c2.y), 4.5)

    def test_both_pedals_at_speed_is_just_braking(self):
        c = car(speed=20.0)
        drive(c, 0.5, S.B_UP | S.B_DOWN)
        self.assertLess(c.speed(), 16.0, "the brake wins")
        self.assertEqual(c.smoke_t, 0.0, "no brake stand at 50 km/h")
        drive(c, 2.0, S.B_UP | S.B_DOWN)
        self.assertGreater(c.smoke_t, 0.0, "...until you've stopped. Then: smoke.")

    def test_a_4x4_cant_do_a_brake_stand(self):
        c = car(V.TRUCK4)
        drive(c, 1.5, S.B_UP | S.B_DOWN | S.B_RIGHT)
        self.assertLess(abs(c.ang), 1e-6)
        self.assertEqual(c.smoke_t, 0.0)

    def test_burnout_predicts(self):
        from chopped.mapgen import CityMap
        from chopped.predict import Predictor
        w = S.World(map_seed=4242, rng_seed=1)
        w.traffic_target = w.patrol_target = 0
        for cid in [k.id for k in w.cars.values() if k.kind != S.PERSONAL]:
            del w.cars[cid]
        p = w.add_player("SMOKEY")
        car_ = w.cars[w.personal_id]
        gx, gy, gw, gh = w.map.garage_rect
        car_.x, car_.y, car_.ang = gx + gw / 2 + 30, gy + gh + 10.0, 0.0
        w._enter_car(p, car_, S.DRIVER)
        pr = Predictor(CityMap(w.map_seed))
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]))
        script = [S.B_UP | S.B_DOWN | S.B_LEFT] * 90 + [S.B_UP] * 30
        for seq, b in enumerate(script, 1):
            pr.push_input(seq, b, 0.0)
            w.set_input(p.id, S.InputState(b))
            w.step(DTS)
            self.assertAlmostEqual(pr.car.x, car_.x, places=3)
            self.assertAlmostEqual(pr.car.ang, car_.ang, places=4)


class TestCatchableDrift(unittest.TestCase):
    def _yank(self, model, after, secs=2.5):
        c = car(model, tuned=True, speed=22.0)
        drive(c, 0.6, S.B_RIGHT | S.B_HANDBRAKE | S.B_UP)
        worst = 0.0
        lot = Lot()
        for _ in range(int(secs / DTS)):
            sl = math.degrees(lot.slip_angle(c))
            b = S.B_UP
            if after == "counter":
                b |= S.B_RIGHT if sl > 4 else S.B_LEFT if sl < -4 else 0
            S.drive_input(c, b)
            lot._drive(c, DTS)
            worst = max(worst, slip_deg(c))
        return c, worst

    def test_countersteer_catches_a_big_handbrake_slide(self):
        for model in (V.KEI, V.COUPE, V.MUSCLE, V.RICE):
            c, worst = self._yank(model, "counter")
            self.assertLess(worst, 70, "%s: no spin" % V.model(model).name)
            self.assertLess(slip_deg(c), 8, "%s: back in a straight line" % V.model(model).name)

    def test_let_go_and_it_straightens(self):
        for model in (V.KEI, V.COUPE, V.MUSCLE):
            c, worst = self._yank(model, "hands")
            self.assertLess(worst, 90, "%s: no spin" % V.model(model).name)
            self.assertLess(slip_deg(c), 10)

    def test_the_handbrake_cant_spin_you_like_a_top(self):
        c = car(V.COUPE, tuned=True, speed=25.0)
        peak = 0.0
        lot = Lot()
        for _ in range(int(1.2 / DTS)):
            S.drive_input(c, S.B_RIGHT | S.B_HANDBRAKE | S.B_UP)
            lot._drive(c, DTS)
            peak = max(peak, abs(c.w))
        self.assertLessEqual(peak, C.HANDBRAKE_MAX_YAW + 1e-6)


class TestNewModels(unittest.TestCase):
    def test_rice_rockets_come_riced(self):
        rng = random.Random(3)
        for _ in range(20):
            parts = model_loadout(rng, V.RICE)
            self.assertIn(parts["Spoiler"].type_id, ("spl_shelf", "spl_wing"), "the wing is mandatory")
            self.assertEqual(parts["Exhaust"].type_id, "exh_tuned")
            self.assertEqual(parts["BumperF"].type_id, "bmp_tuned_aero")
        c = S.Car(1, S.CIV, 0, 0, 0, model_loadout(rng, V.RICE), model=V.RICE)
        self.assertTrue(c.pops(), "rice rockets pop and bang on the overrun")

    def test_4x4s_are_all_wheel_drive_and_ignore_grass(self):
        m = V.model(V.TRUCK4)
        self.assertTrue(m.awd and m.offroad and m.bed)

        class Grass(Lot):
            class _Map(Lot._Map):
                def tile_at(self, x, y):
                    return 3
        truck, kei = car(V.TRUCK4), car(V.KEI)
        g = Grass()
        g.map = Grass._Map()
        for c in (truck, kei):
            for _ in range(int(3.0 / DTS)):
                S.drive_input(c, S.B_UP)
                g._drive(c, DTS)
        on_road = car(V.TRUCK4)
        drive(on_road, 3.0, S.B_UP)
        self.assertAlmostEqual(truck.speed(), on_road.speed(), places=3, msg="grass is just road to a 4x4")
        self.assertLess(kei.speed(), truck.speed(), "the Kei bogs down in the park")

    def test_engines_and_superchargers_on_the_wire(self):
        w = S.World(map_seed=4242, rng_seed=1)
        p = w.add_player("A")
        c = w.cars[w.personal_id]
        c.parts["Engine"] = Part("eng_sc_6_2")
        c.parts["Transmission"] = Part("trn_tuned_6mt")
        row = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]).cars[c.id]
        self.assertEqual(DT.unpack_engine_byte(row[19]), (PT.V_V8, PT.ASP_SC, 6))

    def test_every_engine_has_a_voice_and_the_city_has_them_all(self):
        engines = [tid for tid, d in PT.PART_DEFS.items() if d[1] == "engine"]
        for tid in engines:
            self.assertIn(tid, PT.ENGINE_SPECS)
        rng = random.Random(9)
        seen = set()
        for _ in range(400):
            mid = V.pick_model(rng)
            seen.add(model_loadout(rng, mid)["Engine"].type_id)
        self.assertTrue({"eng_sc_6_2", "eng_sc_1_6", "eng_rotary_13b", "eng_tt_3_0", "eng_diesel_4_5",
                         "eng_vtec_1_8", "eng_v8_5_7", "eng_v6_3_0"} <= seen)


if __name__ == "__main__":
    unittest.main()

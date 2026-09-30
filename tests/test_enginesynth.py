"""v0.18 engine/turbo/supercharger synthesis: the firing frequency of each layout, pipe modes that
don't move with the revs, a turbo that lags and coasts, a supercharger that doesn't, and no clipping."""

import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import drivetrain as DT
from chopped import enginesynth as ES
from chopped import parts as PT

R = 22050


def mag(x, f):
    """Single-bin DFT magnitude (Goertzel-ish): loops are whole engine cycles, so firing harmonics land on bins."""
    w = 2 * math.pi * f / R
    re = sum(v * math.cos(w * i) for i, v in enumerate(x))
    im = sum(v * math.sin(w * i) for i, v in enumerate(x))
    return math.hypot(re, im) / len(x)


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x))


def peak_over_median(x, f0):
    neigh = sorted(mag(x, f0 * (0.6 + 0.05 * k)) for k in range(19) if abs(0.6 + 0.05 * k - 1.0) > 0.08)
    return mag(x, f0) / neigh[len(neigh) // 2]


class TestFiringOrder(unittest.TestCase):
    def test_firing_frequency_per_layout(self):
        # f = rpm/60 * cylinders/2 (four-stroke)
        for name, cyl in (("i4", 4), ("i6", 6), ("v8", 8), ("v6", 6), ("rotary", 4), ("single", 1), ("boxer", 4)):
            self.assertEqual(ES.LAYOUTS[name].cyl, cyl, name)
            self.assertAlmostEqual(ES.firing_hz(name, 3000.0), 3000 / 60.0 * cyl / 2.0)

    def test_the_firing_frequency_is_in_the_sound_and_tracks_rpm(self):
        for name in ("i4", "i6", "v8", "rotary", "boxer", "single", "v6"):
            lay = ES.LAYOUTS[name]
            last = 0.0
            for rpm in (1500, 3000, 5000):
                x, actual = ES.render_engine(name, rpm, R, redline=7000)
                f0 = ES.firing_hz(lay, actual)
                self.assertGreater(f0, last, "%s: the pulse rate rises with the revs" % name)
                last = f0
                # 6 dB over its neighbours (the odd-fire V6 and the one-lunger smear their energy on purpose)
                floor = 1.5 if name in ("v6", "single") else 3.0
                self.assertGreater(peak_over_median(x, f0), floor, "%s at %d rpm: a firing-frequency line" % (name, rpm))

    def test_the_layouts_have_the_orders_they_claim(self):
        v8 = ES.LAYOUTS["v8"]
        self.assertEqual(v8.banks, (0, 1, 1, 0, 1, 0, 0, 1), "cross-plane: L R R L R L L R")
        self.assertEqual([round(a) for a in v8.angles], [0, 90, 180, 270, 360, 450, 540, 630])
        v6 = ES.LAYOUTS["v6"].angles
        gaps = [(v6[(i + 1) % 6] - v6[i]) % 720 for i in range(6)]
        self.assertEqual(sorted(set(gaps)), [90, 150], "odd-fire V6 alternates 90 and 150")
        self.assertEqual(len(set(round(b - a) for a, b in zip(ES.LAYOUTS["i6"].angles, ES.LAYOUTS["i6"].angles[1:]))), 1)
        # a boxer's unequal headers: bank 1's pipe modes are lower than bank 0's
        b0, b1 = ES.pipe_modes("boxer", 0), ES.pipe_modes("boxer", 1)
        self.assertLess(b1[0][0], b0[0][0] * 0.8)

    def test_bikes_are_told_from_hatchbacks_by_redline(self):
        self.assertEqual(ES.layout_name(PT.V_I4, 6800), "i4")
        self.assertEqual(ES.layout_name(PT.V_I4, 13000), "bike_i4")
        self.assertEqual(ES.layout_name(PT.V_I4, 10500), "single")
        self.assertEqual(ES.layout_name(PT.V_V8), "v8")
        self.assertEqual(ES.layout_name(PT.V_ELECTRIC), "electric")
        # every catalogue engine's redline lies inside the band grid of the layout it gets
        for tid, (voice, _asp, red, idle) in PT.ENGINE_SPECS.items():
            rp = DT.band_rpms(voice, red)
            self.assertLessEqual(red, rp[-1] + 1e-6, tid)
            self.assertLessEqual(rp[0], max(idle, rp[0]), tid)


class TestPipes(unittest.TestCase):
    def test_pipe_modes_are_quarter_wave_odd_multiples(self):
        modes = ES.pipe_modes("i4")
        f1 = modes[0][0]
        self.assertAlmostEqual(f1, ES.SOUND_C / (4 * ES.LAYOUTS["i4"].pipe))
        for k, (f, _g) in enumerate(modes):
            self.assertAlmostEqual(f / f1, 2 * k + 1)

    def test_formants_stay_put_while_the_revs_move(self):
        # The exhaust's resonance is the PIPE's: the balance between its 2nd mode (205 Hz) and a quiet
        # region well above the modes must not change with rpm. A pitch-shifted sample would slide it.
        def band(x, lo, hi):
            return sum(mag(x, f) for f in range(lo, hi, 6))
        ratios = []
        for rpm in (1800, 3000, 4500):
            x, _ = ES.render_engine("i4", rpm, R, redline=7000)
            ratios.append(band(x, 150, 260) / band(x, 700, 810))
        self.assertGreater(min(ratios), 2.0, "the pipe's mode is loud at every rpm")
        self.assertLess(max(ratios) / min(ratios), 3.0, "and about as loud relative to the highs: %s" % ratios)

    def test_pulse_response_rings_at_the_pipe_mode(self):
        h = ES._pulse_response(ES.LAYOUTS["i4"], 0, 1.0, R)[0]
        best = max(range(40, 700, 4), key=lambda f: mag(h, f))
        f_modes = [f for f, _ in ES.pipe_modes("i4")]
        self.assertTrue(any(abs(best - f) < 25 for f in f_modes) or best < 90, "peak %d Hz vs %s" % (best, f_modes))


class TestLoudness(unittest.TestCase):
    def test_no_clipping_no_dc_no_silence_anywhere(self):
        for name in list(ES.LAYOUTS) + ["electric"]:
            voice, hint = ES.LAYOUT_VOICE.get(name, (PT.V_I4, 0))
            red = 8000
            for rpm in (700, 2500, 6000, 8200):
                for load in (0.0, 1.0):
                    for sc in (False, True):
                        x, _ = ES.render_engine(name, rpm, R, supercharged=sc, redline=red, load=load,
                                                vtec_rpm=5000)
                        pk = max(abs(v) for v in x)
                        self.assertLess(pk, 1.0, "%s %d load %s" % (name, rpm, load))
                        self.assertGreater(pk, 0.05, "%s %d load %s is silent" % (name, rpm, load))
                        self.assertLess(abs(sum(x) / len(x)), 0.01, "DC")
                        seam = abs(x[0] - x[-1])
                        jumps = max(abs(x[i + 1] - x[i]) for i in range(len(x) - 1))
                        self.assertLessEqual(seam, jumps + 1e-9, "%s %d loops with a click" % (name, rpm))

    def test_idle_is_quieter_than_redline_and_off_throttle_is_thinner(self):
        for name in ("i4", "v8", "diesel", "electric"):
            idle_on, _ = ES.render_engine(name, 800, R, redline=7000, load=1.0)
            red_on, _ = ES.render_engine(name, 7000, R, redline=7000, load=1.0)
            red_off, _ = ES.render_engine(name, 7000, R, redline=7000, load=0.0)
            self.assertLess(rms(idle_on), rms(red_on) * 0.65, name)
            if name != "electric":
                self.assertLess(rms(red_off), rms(red_on) * 0.8, name)

    def test_deterministic_per_seed(self):
        a, _ = ES.render_engine("v8", 3000, R, redline=7000, seed=5)
        b, _ = ES.render_engine("v8", 3000, R, redline=7000, seed=5)
        c, _ = ES.render_engine("v8", 3000, R, redline=7000, seed=6)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c, "another seed is another engine's wobble")

    def test_cycles_differ(self):
        # cycle-to-cycle jitter: a loop of several cycles is not one cycle repeated
        x, _ = ES.render_engine("i4", 900, R, redline=7000)
        half = len(x) // 2
        diff = rms([a - b for a, b in zip(x[:half], x[half:2 * half])])
        self.assertGreater(diff, 0.05 * rms(x))

    def test_renders_stay_cheap(self):
        t0 = time.perf_counter()
        for rpm in (900, 3000, 6500):
            for load in (1.0, 0.0):
                ES.render_engine("v8", rpm, R, redline=7000, load=load)
        self.assertLess(time.perf_counter() - t0, 1.0, "six band renders")


class TestSupercharger(unittest.TestCase):
    def test_whine_is_locked_to_the_revs(self):
        t = DT.Tacho(PT.V_V8, PT.ASP_SC, 6)
        ratios = []
        for k in range(200):
            t.update(30.0, 1.0 if k < 150 else 0.0, 50.0, dt=1 / 60)
            kind, hz, level, air = t.induction()
            self.assertEqual(kind, "sc")
            ratios.append(hz / t.rpm)
        self.assertAlmostEqual(min(ratios), max(ratios), places=6, msg="no lag, no slip: hz is exactly proportional to rpm")
        self.assertAlmostEqual(ratios[0], C.SC_PULLEY * C.SC_LOBES / 60.0)

    def test_whine_gets_louder_with_load_and_revs(self):
        t = DT.Tacho(PT.V_V8, PT.ASP_SC, 6)
        t.rpm, t.load = 3000.0, 0.0
        lo = t.induction()[2]
        t.load = 1.0
        hi = t.induction()[2]
        t.rpm = 6000.0
        higher = t.induction()[2]
        self.assertGreater(hi, lo)
        self.assertGreater(higher, hi)

    def test_the_tone_bank_renders_the_frequency_it_was_asked_for(self):
        for f in (300.0, 700.0):
            x, actual = ES.render_tone(f, R, ES.SC_PARTIALS)
            self.assertLess(abs(actual - f) / f, 0.06)
            fund = mag(x, actual)
            self.assertGreater(mag(x, actual * 2), 0.5 * fund, "lobe-pass harmonics")
            self.assertLess(max(abs(v) for v in x), 1.0)
        bank = ES.tone_bank(*C.SC_WHINE_HZ, C.TONE_RATIO)
        self.assertGreaterEqual(bank[-1], C.SC_WHINE_HZ[1])
        # the top of the range is above a redline rev (7000 rpm through the pulleys)
        self.assertGreater(C.SC_WHINE_HZ[1], ES.sc_hz(7000) * 1.2)

    def test_na_engines_have_no_induction(self):
        self.assertIsNone(DT.Tacho(PT.V_I4, PT.ASP_NA, 5).induction())


class TestTurbo(unittest.TestCase):
    def _floor_it(self, t, secs, speed=30.0):
        out = []
        for _ in range(int(secs * 60)):
            t.update(speed, 1.0, 50.0, dt=1 / 60)
            out.append(t.turbo_n)
        return out

    def test_the_turbine_lags_the_revs(self):
        t = DT.Tacho(PT.V_I4T, PT.ASP_TURBO, 6)
        n = self._floor_it(t, 4.0)
        self.assertLess(n[18], 0.35 * n[-1], "0.3 s in, barely spinning")
        self.assertGreater(n[-1], 0.7, "spooled by 4 s")
        self.assertEqual(n, sorted(n), "monotonic spool-up at constant throttle")
        kind, hz, level, air = t.induction()
        self.assertEqual(kind, "turbo")
        self.assertAlmostEqual(hz, C.TURBO_HZ_TOP * t.turbo_n)
        self.assertGreater(hz, C.TURBO_HZ_FLOOR, "the whistle is audible when spooled")

    def test_spool_down_is_slower_than_spool_up_and_slower_than_boost(self):
        t = DT.Tacho(PT.V_I4T, PT.ASP_TURBO, 6)
        up = self._floor_it(t, 5.0)
        n_top, b_top = t.turbo_n, t.boost
        self.assertGreater(b_top, 0.4)
        # time to fall to half after the lift, versus time to rise to half
        rise_half = next(i for i, v in enumerate(up) if v >= 0.5 * n_top) / 60.0
        fall, boost = [], []
        for _ in range(360):
            t.update(30.0, 0.0, 50.0, dt=1 / 60)
            fall.append(t.turbo_n)
            boost.append(t.boost)
        fall_half = next(i for i, v in enumerate(fall) if v <= 0.5 * n_top) / 60.0
        self.assertGreater(fall_half, rise_half * 0.8, "it freewheels: %.2f s down vs %.2f s up" % (fall_half, rise_half))
        self.assertLess(boost[30], 0.4 * b_top, "the pressure is dumped in half a second...")
        self.assertGreater(fall[30], 0.7 * n_top, "...while the turbine is still spinning: the falling whistle")
        self.assertEqual(sorted(fall, reverse=True), fall)

    def test_lift_fires_bov_with_the_dumped_level(self):
        t = DT.Tacho(PT.V_I4T, PT.ASP_TURBO, 6)
        self._floor_it(t, 4.0)
        before = t.boost
        ev = t.update(30.0, 0.0, 50.0, dt=1 / 60)
        self.assertIn("bov", ev)
        self.assertGreater(t.bov_level, 0.4)
        self.assertLessEqual(t.bov_level, before + 1e-9)
        self.assertLess(t.boost, before * 0.5)

    def test_whistle_level_is_quieter_off_throttle(self):
        t = DT.Tacho(PT.V_I4T, PT.ASP_TURBO, 6)
        t.turbo_n, t.rpm = 0.8, 5000.0
        t.load = 1.0
        on = t.induction()
        t.load = 0.0
        off = t.induction()
        self.assertLess(off[2], on[2])
        self.assertLess(off[3], on[3])
        self.assertEqual(off[1], on[1], "pitch is turbine speed, not throttle")


class TestOneShots(unittest.TestCase):
    def test_bov_flutter_pop_are_tame_and_bov_falls_in_pitch(self):
        for x in (ES.render_bov(R), ES.render_bov(R, flutter=True), ES.render_pop(R, 1.0, 2), ES.render_air(R),
                  ES.render_whistle(4000, R)):
            self.assertTrue(x)
            self.assertLessEqual(max(abs(v) for v in x), 1.0)
            self.assertLess(abs(sum(x) / len(x)), 0.02)

        def zcr(x):
            return sum(1 for a, b in zip(x, x[1:]) if (a < 0) != (b < 0)) / float(len(x))
        bov = ES.render_bov(R)
        n = len(bov)
        self.assertGreater(zcr(bov[n // 20:n // 4]), zcr(bov[n // 2:3 * n // 4]), "the hiss slides down as the pressure falls")

    def test_flutter_chuffs(self):
        x = ES.render_bov(R, flutter=True)
        env = [max(abs(v) for v in x[i:i + 220]) for i in range(0, len(x) - 220, 220)]
        rises = sum(1 for a, b in zip(env, env[1:]) if b > a * 1.4)
        self.assertGreaterEqual(rises, 3, "stu-tu-tu: several separate chuffs")

    def test_tone_bank_loops_cleanly(self):
        for f in (1500.0, 4200.0, 6600.0):
            x, _ = ES.render_tone(f, R, ES.TURBO_PARTIALS)
            self.assertLessEqual(abs(x[0] - x[-1]), max(abs(x[i + 1] - x[i]) for i in range(len(x) - 1)) + 1e-9)


class TestBanks(unittest.TestCase):
    def test_band_grid_covers_idle_to_past_redline_per_layout(self):
        for voice in range(9):
            rp = DT.band_rpms(voice)
            self.assertEqual(len(rp), C.ENGINE_BANDS)
            self.assertEqual(rp, sorted(rp))
            self.assertLess(rp[-1] / rp[-2], 1.6, "neighbouring bands are close enough to crossfade")

    def test_load_rises_with_throttle_and_drops_in_a_shift(self):
        t = DT.Tacho(PT.V_I4, PT.ASP_NA, 5)
        for _ in range(30):
            t.update(10.0, 1.0, 45.0, dt=1 / 60)
        self.assertGreater(t.load, 0.9)
        for _ in range(30):
            t.update(10.0, 0.0, 45.0, dt=1 / 60)
        self.assertLess(t.load, 0.1)


class _Shop:
    """A stand-in map: the shop is everything west of x = 0."""

    def in_garage(self, x, y):
        return x < 0


class TestOcclusion(unittest.TestCase):
    def setUp(self):
        from chopped.audio import Audio
        self.a = Audio(enabled=False)        # the occluder works with no sound card at all
        self.a.occ._cmap = _Shop()

    def test_own_car_is_never_muffled(self):
        self.a.occ.zone, self.a.occ.leak = 1, 0.0          # inside, doors shut
        self.assertEqual(self.a.engine_reach(0.0, 50.0, 0.0, True), 1.0)
        self.assertEqual(self.a.engine_reach(0.0, -5.0, 0.0, True), 1.0)

    def test_other_cars_across_the_shut_doors_are_silent_both_ways(self):
        self.a.occ.zone, self.a.occ.leak = 1, 0.0          # listener in the shop
        self.assertEqual(self.a.engine_reach(10.0, 20.0, 0.0, False), 0.0, "car outside, listener inside")
        self.assertGreater(self.a.engine_reach(10.0, -20.0, 0.0, False), 0.7, "car inside with you")
        self.a.occ.zone = 0                                # listener outside
        self.assertEqual(self.a.engine_reach(10.0, -20.0, 0.0, False), 0.0, "car inside, listener outside")
        self.assertGreater(self.a.engine_reach(10.0, 20.0, 0.0, False), 0.7)

    def test_doors_open_lets_it_leak_through_with_the_same_fade(self):
        self.a.occ.zone, self.a.occ.leak = 1, 0.5
        got = self.a.engine_reach(0.0, 20.0, 0.0, False)
        self.assertAlmostEqual(got, 0.5)
        self.assertAlmostEqual(self.a.engine_reach(0.0, 20.0, 0.0, False), self.a.occlusion(20.0, 0.0))

    def test_distance_still_fades_it(self):
        self.a.occ.zone, self.a.occ.leak = 0, 1.0
        near = self.a.engine_reach(5.0, 5.0, 0.0, False)
        far = self.a.engine_reach(C.ENGINE_HEAR_DIST * 0.9, 40.0, 0.0, False)
        self.assertGreater(near, far)
        self.assertEqual(self.a.engine_reach(C.ENGINE_HEAR_DIST * 2, 90.0, 0.0, False), 0.0)


if __name__ == "__main__":
    unittest.main()

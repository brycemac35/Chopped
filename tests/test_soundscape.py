import os
import time
import unittest
from array import array

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from chopped import config as C
from chopped import sim as S
from chopped import soundscape as SC
from chopped import sfxsynth as SY
from chopped.audio import Audio
from chopped.enums import TRAP_DOOR
from chopped.mapgen import CityMap


class HornBudget(unittest.TestCase):
    def run_jam(self, dists, secs=20.0):
        hb = SC.HornBudget()
        grants, t = [], 0.0
        while t < secs:
            for g in hb.step(t, [(100 + i, d) for i, d in enumerate(dists)]):
                grants.append((t, g))
            t += 1 / 60
        return grants

    def test_budget_caps_events_in_any_window(self):
        grants = self.run_jam([5 + i for i in range(30)])          # 30 cars, all leaning on it
        self.assertGreater(len(grants), 5)                         # not silent...
        times = [t for t, _ in grants]
        for i, t in enumerate(times):
            in_win = [x for x in times if t <= x < t + C.HORN_BUDGET_WINDOW]
            self.assertLessEqual(len(in_win), C.HORN_BUDGET_MAX)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, C.HORN_MIN_GAP - 1e-6)

    def test_far_cars_never_heard_and_falloff_is_steep(self):
        self.assertEqual(self.run_jam([C.HORN_HEAR_DIST + 1, 80, 200]), [])
        near = self.run_jam([3.0])[0][1][1]
        mid = self.run_jam([C.HORN_HEAR_DIST * 0.5])[0][1][1]
        self.assertLess(mid, near * 0.25)                          # half range = under a quarter of the level

    def test_nearest_car_gets_the_slot_and_cars_have_their_own_voice(self):
        hb = SC.HornBudget()
        out = hb.step(0.0, [(1, 30.0), (2, 4.0)])
        self.assertEqual(out[0][0], 2)
        voices = {SC.car_horn_voice(i)[:2] for i in range(50)}
        self.assertGreater(len(voices), 6)
        self.assertEqual(SC.car_horn_voice(7), SC.car_horn_voice(7))

    def test_a_car_waits_its_cooldown(self):
        hb = SC.HornBudget()
        self.assertEqual(len(hb.step(0.0, [(1, 5.0)])), 1)
        self.assertEqual(hb.step(0.5, [(1, 5.0)]), [])
        self.assertEqual(len(hb.step(C.HORN_CAR_COOLDOWN[1] + 0.1, [(1, 5.0)])), 1)


class DeadZone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cmap = CityMap(7)
        gx, gy, gw, gh = cls.cmap.garage_rect
        cls.inside = (gx + gw / 2, gy + gh / 2)
        cls.outside = (gx + gw / 2, gy + gh + 20)

    def doors(self, openness):
        return {C.DOOR_ID + i: (C.DOOR_ID + i, TRAP_DOOR, 0, 0, 0, openness[i]) for i in range(len(C.DOOR_COLS))}

    def settle(self, occ, pos, traps, secs=1.0):
        for _ in range(int(secs * 60)):
            occ.update(self.cmap, pos[0], pos[1], traps, 1 / 60)

    def test_outside_is_silent_inside_with_doors_shut_and_returns_when_one_opens(self):
        occ = SC.Occluder()
        shut = self.doors([0.0] * 5)
        self.settle(occ, self.inside, shut)
        self.assertEqual(occ.factor(*self.outside), 0.0)
        self.assertEqual(occ.factor(*self.inside), 1.0)            # sounds in the shop are unaffected
        one = self.doors([1.0, 0, 0, 0, 0])
        self.settle(occ, self.inside, one)
        self.assertAlmostEqual(occ.factor(*self.outside), C.DEADZONE_LEAK_PER_DOOR)
        two = self.doors([1.0, 1.0, 0, 0, 0])
        self.settle(occ, self.inside, two)
        self.assertEqual(occ.factor(*self.outside), 1.0)           # scaled by how many are open
        self.settle(occ, self.inside, shut)
        self.assertEqual(occ.factor(*self.outside), 0.0)

    def test_fade_is_gradual(self):
        occ = SC.Occluder()
        self.settle(occ, self.inside, self.doors([0.0] * 5))
        occ.update(self.cmap, *self.inside, self.doors([1.0] * 5), 0.1)
        self.assertTrue(0.0 < occ.factor(*self.outside) < 1.0)     # 0.1 s into a 0.3 s fade
        self.settle(occ, self.inside, self.doors([1.0] * 5), C.DEADZONE_FADE + 0.1)
        self.assertEqual(occ.factor(*self.outside), 1.0)

    def test_listener_outside_shut_shop_muffles_the_inside(self):
        occ = SC.Occluder()
        self.settle(occ, self.outside, self.doors([0.0] * 5))
        self.assertEqual(occ.factor(*self.inside), 0.0)
        self.assertEqual(occ.factor(*self.outside), 1.0)

    def test_barely_open_door_counts_as_shut(self):
        occ = SC.Occluder()
        self.settle(occ, self.inside, self.doors([C.DEADZONE_DOOR_SHUT / 2] * 5))
        self.assertEqual(occ.factor(*self.outside), 0.0)

    def test_pan_sign(self):
        self.assertGreater(SC.pan(0, 0, 0.0, 0, 20), 0.5)          # yaw 0 faces +x; +y is on the right
        self.assertLess(SC.pan(0, 0, 0.0, 0, -20), -0.5)
        self.assertEqual(SC.pan(0, 0, 0.0, 1, 0), 0.0)


class Synth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Audio(enabled=True, music=False)
        if cls.a.ok:
            for _ in range(100):
                if cls.a._scape_ready():
                    break
                time.sleep(0.1)

    def peak(self, snd):
        b = array("h")
        b.frombytes(snd.get_raw())
        return max(abs(x) for x in b) / 32767.0

    def test_no_clipping_and_none_silent(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        pool = []
        for s in self.a.sounds.values():
            pool += s if isinstance(s, list) else [s]
        pool += list(self.a.loops.values()) + list(self.a.horns) + list(self.a.blasts.values())
        pool += list(self.a.muffled.values()) + list(self.a.scape_snd or [])
        self.assertGreater(len(pool), 100)
        for s in pool:
            p = self.peak(s)
            self.assertLessEqual(p, C.PEAK_CEIL + 0.001)
            self.assertGreater(p, 0.02)

    def test_variants_and_ambience_arrive(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        self.assertEqual(len(self.a.blasts), len(SC.HORN_PITCHES) * SC.HORN_KINDS)
        self.assertEqual(len(self.a.sounds[S.S_PUNCH]), 3)
        self.assertEqual(len(self.a.scape_snd), 3)                 # day, night, chopper

    def test_ambience_loops_seamlessly(self):
        for night in (False, True):
            b = SY.ambience_bed(22050, night)
            step = max(abs(b[i + 1] - b[i]) for i in range(0, len(b) - 1, 5))
            self.assertLessEqual(abs(b[0] - b[-1]), step)
            self.assertLessEqual(max(abs(v) for v in b), 0.51)

    def test_horn_is_two_tone_and_soft(self):
        w = SY._horn_wave(4410, 22050, 400.0, 500.0, 0.2)
        self.assertLess(max(abs(v) for v in w), 0.6)
        blasts = SY.horn_blasts(22050)
        for k in ((0, 0), (0, 1), (0, 2)):
            self.assertLess(abs(blasts[k][0]), 0.01)               # soft attack: starts from silence
            self.assertLess(abs(blasts[k][-1]), 0.01)

    def test_disabled_audio_is_a_no_op(self):
        a = Audio(enabled=False)
        a.play(S.S_HONK, 3.0, src=(1, 1))
        a.honk_blast(0, 0, 1.0)
        a.update_scape(0.0, False, True)
        a.set_loop("horn", 1.0, pan=0.5)
        a.listen(None, 0, 0, 0, {})
        self.assertFalse(a.ok)

    def test_play_through_shut_doors(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        cmap = CityMap(7)
        gx, gy, gw, gh = cmap.garage_rect
        traps = {C.DOOR_ID + i: (C.DOOR_ID + i, TRAP_DOOR, 0, 0, 0, 0.0) for i in range(5)}
        for _ in range(30):                     # listen() runs on the wall clock: give the fade its 0.3 s
            time.sleep(0.02)
            self.a.listen(cmap, gx + gw / 2, gy + gh / 2, 0.0, traps)
        self.assertEqual(self.a.occlusion(gx + gw / 2, gy + gh + 30), 0.0)
        self.a.play(S.S_BOOM, 30.0, src=(gx + gw / 2, gy + gh + 30))     # thump path: must not raise
        self.a.play(S.S_PUNCH, 30.0, src=(gx + gw / 2, gy + gh + 30))   # silent path
        self.a.update_scape(0.5, False, True)


if __name__ == "__main__":
    unittest.main()

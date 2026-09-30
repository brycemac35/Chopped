import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from chopped import config as C
from chopped.audio import Audio


class VolumeBuses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = Audio(enabled=True, music=False)

    def setUp(self):
        self.a.set_volumes(1, 1, 1, 1)

    def test_defaults_and_roundtrip(self):
        self.assertEqual(set(Audio(enabled=False).get_volumes()), {"master", "music", "sfx", "engine"})
        self.a.set_volumes(master=0.5, music=0.25, sfx=0.75, engine=0.1)
        self.assertEqual(self.a.get_volumes(), {"master": 0.5, "music": 0.25, "sfx": 0.75, "engine": 0.1})

    def test_clamp_and_junk(self):
        self.a.set_volumes(master=2, music=-1, sfx=float("nan"), engine="x")
        v = self.a.get_volumes()
        self.assertEqual((v["master"], v["music"], v["sfx"], v["engine"]), (1.0, 0.0, 0.0, 1.0))

    def test_master_times_bus(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        self.a.set_volumes(master=0.5, music=0.5, sfx=1.0, engine=0.0)
        self.assertAlmostEqual(self.a.gain("music"), 0.25 ** C.VOLUME_CURVE)
        self.assertAlmostEqual(self.a.gain("sfx"), 0.5 ** C.VOLUME_CURVE)
        self.assertEqual(self.a.gain("engine"), 0.0)

    def test_midpoint_is_quieter_than_linear(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        self.a.set_volumes(master=1, sfx=0.5)
        self.assertAlmostEqual(self.a.gain("sfx"), 0.25)

    def test_mute_wins(self):
        m = Audio(enabled=False)
        m.set_volumes(1, 1, 1, 1)
        self.assertFalse(m.ok)
        for bus in ("music", "sfx", "engine"):
            self.assertEqual(m.gain(bus), 0.0)
        m.play(0)
        m.set_loop("siren", 1.0)
        m.engine_note(0, 0, False, 3000, 1.0)   # all silent no-ops

    def test_zero_sfx_loop_stays_stopped(self):
        if not self.a.ok:
            self.skipTest("no dummy audio device")
        self.a.set_volumes(sfx=0.0)
        self.a.set_loop("siren", 1.0)
        self.assertIsNone(self.a.loop_state["siren"])
        self.a.set_volumes(sfx=1.0)
        self.a.set_loop("siren", 1.0)
        self.assertIsNotNone(self.a.loop_state["siren"])
        self.a.set_loop("siren", 0)


if __name__ == "__main__":
    unittest.main()

"""The procedural beat: it has to exist, loop cleanly, and actually bang."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import music


class TestMusic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.street, cls.heat = music.compose(11025)       # half rate: same maths, quicker test

    def test_layers_line_up_for_a_seamless_loop(self):
        self.assertEqual(len(self.street), len(self.heat))
        bars = music.BARS * music.STEPS_PER_BAR * (60.0 / music.BPM / 4)
        self.assertAlmostEqual(len(self.street) / 11025, bars, delta=0.01)

    def test_not_silent_and_not_clipping(self):
        for layer in (self.street, self.heat):
            peak = max(abs(v) for v in layer)
            rms = math.sqrt(sum(v * v for v in layer) / len(layer))
            self.assertLessEqual(peak, 1.0)
            self.assertGreater(rms, 0.02)

    def test_the_808_hits_on_the_one(self):
        """More energy right on the downbeat than just before it (the kick + 808)."""
        n = len(self.street)
        step = n // (music.BARS * music.STEPS_PER_BAR)

        def energy(i0):
            return sum(v * v for v in self.street[i0:i0 + step // 2])
        downbeats = sum(energy(b * 16 * step) for b in range(music.BARS))
        offbeats = sum(energy(b * 16 * step + 4 * step) for b in range(music.BARS))
        self.assertGreater(downbeats, offbeats)


if __name__ == "__main__":
    unittest.main()

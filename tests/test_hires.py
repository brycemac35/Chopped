"""(v0.17) The hi-res pass: the byte-budgeted sprite cache, the sprite mips, set_fov and the
render-scale plumbing. No visuals checked here (there's no automated visual test); these pin the
arithmetic that keeps memory and on-screen size honest."""

import math
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from chopped import config as C
from chopped import fp as FP
from chopped import fpart as FA


def _bare_renderer(vw=1280, ks=2):
    """An FPRenderer without a city: just enough geometry for the FOV and mip maths."""
    r = FP.FPRenderer.__new__(FP.FPRenderer)
    r.vw, r.ks, r.cstep = vw, ks, ks
    r._spx = 0.0
    r.fov = math.radians(C.FP_FOV)
    r._apply_fov(r.fov)
    return r


class TestSpriteCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def test_evicts_by_bytes_lru(self):
        cache = FP.SpriteCache(1)                       # 1 MB
        big = pygame.Surface((256, 256), pygame.SRCALPHA)   # 256 KB each
        for i in range(4):
            cache.put(i, (big, 0, 0))
        cache.get(0)                                    # touch the oldest: it should survive
        cache.put(4, (big, 0, 0))
        self.assertLessEqual(cache.bytes, cache.budget)
        self.assertIsNotNone(cache.get(0))
        self.assertIsNone(cache.get(1))                 # the least recently used went first


class TestMips(unittest.TestCase):
    def test_far_sprites_use_the_old_density(self):
        r = _bare_renderer()
        r._spx = 5.0                                    # a car 100+ m off
        self.assertEqual(r._mip(12), (12, 1))

    def test_close_sprites_use_the_top_mip_with_a_thicker_outline(self):
        r = _bare_renderer()
        r._spx = 400.0
        self.assertEqual(r._mip(12), (12 * C.SPRITE_DETAIL, 2))
        r._spx = 20.0
        self.assertEqual(r._mip(12)[0], 24)             # the smallest mip that covers the screen

    def test_on_screen_size_ignores_the_mip(self):
        """k = D / depth / ppm: a sprite built at 4x the px/m must come out the same size."""
        pygame.init()
        boxes = FA.car_boxes(0, 1, 0xFFFFFFFF, 0, 0, 0)
        lo = FA.render_boxes(boxes, 0.4, 12)[0]
        hi = FA.render_boxes(boxes, 0.4, 48, outline=2)[0]
        self.assertAlmostEqual(lo.get_width() / 12.0, hi.get_width() / 48.0, delta=0.4)


class TestFov(unittest.TestCase):
    def test_set_fov_clamps_and_recomputes(self):
        r = _bare_renderer()
        d90 = r.D
        r.set_fov(200)
        self.assertAlmostEqual(r.fov, math.radians(C.FOV_MAX))
        self.assertLess(r.D, d90)                       # wider view = shorter focal length
        r.set_fov(10)
        self.assertAlmostEqual(r.fov, math.radians(C.FOV_MIN))
        self.assertEqual(len(r.ray_k), r.vw // r.cstep)  # still one ray per 640-wide column

    def test_rays_match_across_scales(self):
        """A ray per 640-wide column at any scale, aimed at the same place."""
        a, b = _bare_renderer(640, 1), _bare_renderer(1920, 3)
        self.assertEqual(len(a.ray_k), len(b.ray_k))
        for x, y in zip(a.ray_k, b.ray_k):
            self.assertAlmostEqual(x, y)


if __name__ == "__main__":
    unittest.main()

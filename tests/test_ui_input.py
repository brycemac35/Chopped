"""(v0.19) Esc never quits from the main menu; MOUSE SENSITIVITY and INVERT Y settings."""
import math
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from chopped import config as C
from chopped import settings as SET


def key(k, **kw):
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=kw.get("unicode", ""), mod=0)


class TestMenuEsc(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.display.set_mode((64, 64))
        from chopped.art import PixelFont
        from chopped.ui import Menu
        self.menu = Menu(PixelFont(), "X")

    def test_esc_on_every_top_level_row_does_not_quit(self):
        for i in range(len(self.menu.ITEMS)):
            self.menu.sel = i
            self.assertIsNone(self.menu.handle(key(pygame.K_ESCAPE)))

    def test_quit_row_still_quits(self):
        self.menu.sel = self.menu.ITEMS.index("QUIT")
        self.assertEqual(self.menu.handle(key(pygame.K_RETURN, unicode="\r")), "quit")

    def test_esc_backs_out_of_text_entry_one_level(self):
        for item, target in (("JOIN GAME", "join"), ("NAME", "name")):
            self.menu.sel = self.menu.ITEMS.index(item)
            self.menu.handle(key(pygame.K_RETURN, unicode="\r"))
            self.assertEqual(self.menu.editing, target)
            self.assertIsNone(self.menu.handle(key(pygame.K_ESCAPE)))
            self.assertIsNone(self.menu.editing)
            self.assertIsNone(self.menu.handle(key(pygame.K_ESCAPE)))   # second Esc: top level, nothing

    def test_esc_in_settings_goes_back_not_quit(self):
        from chopped.ui import SettingsPanel
        p = SettingsPanel(self.menu.font, SET.defaults())
        self.assertEqual(p.handle(key(pygame.K_ESCAPE)), "back")


class TestMouseSettings(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._old = os.environ.get("CHOPPED_SAVE_DIR")
        os.environ["CHOPPED_SAVE_DIR"] = self.dir

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CHOPPED_SAVE_DIR", None)
        else:
            os.environ["CHOPPED_SAVE_DIR"] = self._old
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_defaults(self):
        d = SET.defaults()
        self.assertEqual(d["mouse_sens"], 100)
        self.assertIs(d["invert_y"], False)
        self.assertEqual(SET.mouse_mult(d), 1.0)

    def test_round_trip(self):
        d = SET.defaults()
        d["mouse_sens"], d["invert_y"] = 175, True
        self.assertTrue(SET.save(d))
        back = SET.load()
        self.assertEqual(back["mouse_sens"], 175)
        self.assertIs(back["invert_y"], True)

    def test_clamping_and_junk(self):
        self.assertEqual(SET.sanitize({"mouse_sens": 9999})["mouse_sens"], C.MOUSE_SENS_MAX)
        self.assertEqual(SET.sanitize({"mouse_sens": -5})["mouse_sens"], C.MOUSE_SENS_MIN)
        for junk in ("fast", None, True, float("nan")):
            self.assertEqual(SET.sanitize({"mouse_sens": junk})["mouse_sens"], C.MOUSE_SENS_DEFAULT)
        for junk in ("yes", 1, None, "true"):
            self.assertIs(SET.sanitize({"invert_y": junk})["invert_y"], False)
        self.assertEqual(SET.sanitize({})["mouse_sens"], 100)       # an old file without the keys

    def test_range_is_quarter_to_triple(self):
        self.assertEqual((C.MOUSE_SENS_MIN, C.MOUSE_SENS_MAX), (25, 300))

    def test_sensitivity_scales_yaw(self):
        d = SET.defaults()
        base = SET.yaw_delta(d, 100)
        self.assertAlmostEqual(base, 100 * C.MOUSE_SENS)
        d["mouse_sens"] = 300
        self.assertAlmostEqual(SET.yaw_delta(d, 100), base * 3)
        d["mouse_sens"] = 25
        self.assertAlmostEqual(SET.yaw_delta(d, 100), base / 4)
        self.assertEqual(SET.yaw_delta(d, 0), 0)

    def test_invert_flips_pitch_and_sens_scales_it(self):
        d = SET.defaults()
        up = SET.pitch_delta(d, -10, 328)          # mouse up (negative rel) looks up: positive shear
        self.assertGreater(up, 0)
        d["invert_y"] = True
        self.assertAlmostEqual(SET.pitch_delta(d, -10, 328), -up)
        d["mouse_sens"] = 200
        self.assertAlmostEqual(SET.pitch_delta(d, -10, 328), -2 * up)

    def test_panel_rows_adjust_live(self):
        from chopped.art import PixelFont
        from chopped.ui import SettingsPanel
        d, changes = SET.defaults(), []
        p = SettingsPanel(PixelFont(), d, changes.append)
        keys = [r[0] for r in p.ROWS]
        p.sel = keys.index("mouse_sens")
        p.handle(key(pygame.K_RIGHT))
        self.assertEqual(d["mouse_sens"], 100 + C.MOUSE_SENS_STEP)
        for _ in range(100):
            p.handle(key(pygame.K_LEFT))
        self.assertEqual(d["mouse_sens"], C.MOUSE_SENS_MIN)
        p.sel = keys.index("invert_y")
        p.handle(key(pygame.K_RIGHT))
        self.assertIs(d["invert_y"], True)
        p.handle(key(pygame.K_LEFT))
        self.assertIs(d["invert_y"], False)
        self.assertIn("mouse_sens", changes)
        self.assertIn("invert_y", changes)

    def test_panel_draws_and_fits(self):
        from chopped.art import PixelFont
        from chopped.ui import SettingsPanel
        p = SettingsPanel(PixelFont(), SET.defaults())
        low = pygame.Surface((C.LOW_W, C.LOW_H), pygame.SRCALPHA)
        p.draw(low)
        self.assertLess(p.SLOT_Y0 + C.SAVE_SLOTS * p.SLOT_H + 6 + 5, p.BOX.bottom - 14)   # hint above key line
        self.assertLessEqual(p.BOX.bottom, C.LOW_H)
        for text in list(p.HINTS.values()):
            for ch in text:
                self.assertIn(ch, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;!?'-()/%+=*$#&\"<>[]_", ch)


if __name__ == "__main__":
    unittest.main()

"""(v0.17) settings.json: defaults, clamping, corrupt files, round trip, isolation; the SETTINGS panel."""
import json
import os
import shutil
import tempfile
import types
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from chopped import config as C
from chopped import settings as SET


class TestSettingsFile(unittest.TestCase):
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
        d = SET.load()
        self.assertEqual(d["fov"], int(C.FP_FOV))
        self.assertEqual(d["render_scale"], C.RENDER_SCALE_DEFAULT)
        self.assertEqual((d["master"], d["music"], d["sfx"], d["engine"]),
                         (C.VOL_MASTER_DEFAULT, C.VOL_MUSIC_DEFAULT, C.VOL_SFX_DEFAULT, C.VOL_ENGINE_DEFAULT))
        self.assertEqual(d["name"], "")
        self.assertIsNone(d["char"])

    def test_path_honours_save_dir_override(self):
        self.assertEqual(os.path.dirname(SET.settings_path()), self.dir)
        SET.save({"fov": 100})
        self.assertTrue(os.path.exists(os.path.join(self.dir, "settings.json")))

    def test_real_path_is_beside_the_saves_folder(self):
        os.environ.pop("CHOPPED_SAVE_DIR")
        try:
            from chopped import savefile as SF
            self.assertEqual(os.path.dirname(SET.settings_path()), os.path.dirname(SF.save_dir()))
            self.assertTrue(SET.settings_path().endswith("settings.json"))
        finally:
            os.environ["CHOPPED_SAVE_DIR"] = self.dir

    def test_clamping(self):
        d = SET.sanitize({"fov": 500, "render_scale": 0, "master": -5, "music": 250, "sfx": 49.6, "engine": 1e9})
        self.assertEqual(d["fov"], C.FOV_MAX)
        self.assertEqual(d["render_scale"], C.RENDER_SCALE_MIN)
        self.assertEqual((d["master"], d["music"], d["sfx"], d["engine"]), (0, 100, 50, 100))
        self.assertEqual(SET.sanitize({"fov": 1})["fov"], C.FOV_MIN)

    def test_junk_values_fall_back(self):
        d = SET.sanitize({"fov": "wide", "render_scale": None, "master": True, "music": float("nan"),
                          "name": 7, "char": "x"})
        self.assertEqual(d, SET.defaults())
        self.assertEqual(SET.sanitize([1, 2]), SET.defaults())
        self.assertEqual(SET.sanitize(None), SET.defaults())

    def test_corrupt_and_missing_file(self):
        self.assertEqual(SET.load(), SET.defaults())
        with open(SET.settings_path(), "w") as f:
            f.write("{not json")
        self.assertEqual(SET.load(), SET.defaults())
        with open(SET.settings_path(), "w") as f:
            f.write("[1,2,3]")
        self.assertEqual(SET.load(), SET.defaults())

    def test_round_trip_and_name_char(self):
        want = {"fov": 105, "render_scale": 3, "master": 40, "music": 0, "sfx": 75, "engine": 20,
                "name": "Bryce", "char": 2}
        self.assertTrue(SET.save(want))
        got = SET.load()
        self.assertEqual(got["fov"], 105)
        self.assertEqual(got["render_scale"], 3)
        self.assertEqual((got["master"], got["music"], got["sfx"], got["engine"]), (40, 0, 75, 20))
        self.assertEqual((got["name"], got["char"]), ("BRYCE", 2))
        self.assertFalse(os.path.exists(SET.settings_path() + ".tmp"), "atomic write leaves no temp file")
        with open(SET.settings_path()) as f:
            self.assertIsInstance(json.load(f), dict)

    def test_world_scale_clamps(self):
        lo, hi = SET._world_range()[:2]
        self.assertEqual(SET.sanitize({"world_scale": 99})["world_scale"], hi)
        self.assertEqual(SET.sanitize({"world_scale": -4})["world_scale"], lo)
        self.assertEqual(SET.sanitize({"world_scale": "x"})["world_scale"], SET.defaults()["world_scale"])

    def test_servers_default_empty_and_old_files(self):
        self.assertEqual(SET.defaults()["servers"], [])
        with open(SET.settings_path(), "w") as f:
            json.dump({"fov": 100}, f)                     # a v0.17 file
        self.assertEqual(SET.load()["servers"], [])

    def test_servers_round_trip_dedupe_and_order(self):
        sv = []
        for i, a in enumerate(["10.0.0.1", "HostA.example.com:28000", "10.0.0.1:%d" % C.DEFAULT_PORT, "10.0.0.2"]):
            sv = SET.remember_server(sv, a, name="bob" if i == 1 else None, now=1000 + i)
        self.assertEqual([e["addr"] for e in sv], ["10.0.0.2", "10.0.0.1", "HostA.example.com:28000"])
        self.assertEqual(sv[2]["name"], "BOB")
        sv = SET.remember_server(sv, "hosta.example.com:28000", now=2000)      # same host, any case: moves up, keeps its name
        self.assertEqual(sv[0]["addr"], "hosta.example.com:28000")
        self.assertEqual(sv[0]["name"], "BOB")
        self.assertEqual(len(sv), 3)
        SET.save({"servers": sv})
        self.assertEqual(SET.load()["servers"], sv)

    def test_servers_cap_and_junk(self):
        sv = []
        for i in range(12):
            sv = SET.remember_server(sv, "10.0.0.%d" % i, now=100 + i)
        self.assertEqual(len(sv), SET.SERVERS_MAX)
        self.assertEqual(sv[0]["addr"], "10.0.0.11")
        d = SET.sanitize({"servers": [None, 5, {"addr": ""}, {"addr": "bad addr!"}, {"addr": "x" * 200, "last": "no"},
                                      {"addr": "a.b", "name": 7, "last": -5}, "1.2.3.4"]})
        self.assertEqual(sorted(e["addr"] for e in d["servers"]),
                         sorted(["badaddr", "x" * SET.ADDR_MAX, "a.b", "1.2.3.4"]))
        for e in d["servers"]:
            self.assertGreaterEqual(e["last"], 0)
            self.assertLessEqual(len(e["addr"]), SET.ADDR_MAX)
            self.assertNotIn("name", e)
        self.assertEqual(SET.sanitize({"servers": "nope"})["servers"], [])
        self.assertEqual(SET.remember_server([], "  "), [])

    def test_volumes_are_floats_0_to_1(self):
        v = SET.volumes({"master": 100, "music": 70, "sfx": 0, "engine": 80})
        self.assertEqual(v, (1.0, 0.7, 0.0, 0.8))


class TestSettingsPanel(unittest.TestCase):
    def setUp(self):
        import pygame
        pygame.init()
        pygame.display.set_mode((64, 64))
        from chopped.art import PixelFont
        from chopped.ui import SettingsPanel
        self.pg = pygame
        self.changes = []
        self.data = SET.defaults()
        self.panel = SettingsPanel(PixelFont(), self.data, self.changes.append)

    def key(self, k):
        return self.panel.handle(self.pg.event.Event(self.pg.KEYDOWN, key=k))

    def test_keys_adjust_and_report_live(self):
        self.key(self.pg.K_a)
        self.assertEqual(self.data["fov"], 85)
        self.assertEqual(self.changes, ["fov"])
        for _ in range(20):
            self.key(self.pg.K_d)
        self.assertEqual(self.data["fov"], C.FOV_MAX)
        self.key(self.pg.K_s)
        self.key(self.pg.K_a)
        self.assertEqual(self.data["render_scale"], 1)
        self.key(self.pg.K_a)
        self.assertEqual(self.data["render_scale"], C.RENDER_SCALE_MIN)

    def test_off_grid_fov_lands_on_a_mark(self):
        self.data["fov"] = 87
        self.key(self.pg.K_d)
        self.assertEqual(self.data["fov"], 90)
        self.data["fov"] = 87
        self.key(self.pg.K_a)
        self.assertEqual(self.data["fov"], 85)

    def test_escape_and_enter_go_back(self):
        self.assertEqual(self.key(self.pg.K_ESCAPE), "back")
        self.assertEqual(self.key(self.pg.K_RETURN), "back")

    def test_mouse_click_and_drag_slider(self):
        p = self.panel
        t = p.track_rect([r[0] for r in p.ROWS].index("master"))
        ev = self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(t.x, t.centery))
        p.handle(ev)
        self.assertEqual(self.data["master"], 0)
        p.handle(self.pg.event.Event(self.pg.MOUSEMOTION, pos=(t.right, t.centery), rel=(0, 0), buttons=(1, 0, 0)))
        self.assertEqual(self.data["master"], 100)
        p.handle(self.pg.event.Event(self.pg.MOUSEBUTTONUP, button=1, pos=(t.right, t.centery)))
        p.handle(self.pg.event.Event(self.pg.MOUSEMOTION, pos=(t.x, t.centery), rel=(0, 0), buttons=(0, 0, 0)))
        self.assertEqual(self.data["master"], 100, "released: no more dragging")

    def test_render_scale_buttons(self):
        p = self.panel
        r = p.scale_rects(1)[2]
        p.handle(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=r.center))
        self.assertEqual(self.data["render_scale"], 3)
        self.assertIn("render_scale", self.changes)

    def test_back_button(self):
        ev = self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=self.panel.back_rect.center)
        self.assertEqual(self.panel.handle(ev), "back")

    def test_draws_inside_the_canvas_with_known_glyphs(self):
        from chopped.art import GLYPHS
        low = self.pg.Surface((C.LOW_W, C.LOW_H))
        self.panel.draw(low, (0, 0))
        self.assertTrue(self.panel.BOX.colliderect(low.get_rect()) and low.get_rect().contains(self.panel.BOX))
        for i in range(len(self.panel.ROWS)):
            self.assertTrue(self.panel.BOX.contains(self.panel.row_rect(i)))
        for text in list(self.panel.HINTS.values()) + [r[1] for r in self.panel.ROWS]:
            for ch in text:
                self.assertIn(ch, GLYPHS, "font can't print %r" % ch)

    def test_menu_has_a_settings_row(self):
        from chopped.art import PixelFont
        from chopped.ui import Menu
        m = Menu(PixelFont(), "X")
        m.sel = m.ITEMS.index("SETTINGS")
        self.assertEqual(m.handle(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, unicode="\r")),
                         "settings")

    def test_pause_menu_lists_settings(self):
        from chopped.doomhud import DoomHud
        from chopped.mapgen import CityMap
        from chopped.render import Renderer
        r = Renderer(CityMap(4242))
        hud = DoomHud(self.panel.font, r.bank, r.minimap)
        low = self.pg.Surface((C.LOW_W, C.LOW_H))
        hud.draw_pause(low, {"lines": [], "help": False, "mouse": None})
        self.assertEqual(list(hud.pause_rects), ["resume", "help", "settings", "leave"])
        self.assertLessEqual(max(r_.bottom for r_ in hud.pause_rects.values()), C.LOW_H)
        hud.draw_pause(low, {"lines": [], "settings": self.panel, "mouse": None})


class TestAppSettings(unittest.TestCase):
    def test_app_applies_saves_and_cli_wins(self):
        import pygame
        d = tempfile.mkdtemp()
        old = os.environ.get("CHOPPED_SAVE_DIR")
        os.environ["CHOPPED_SAVE_DIR"] = d
        try:
            SET.save({"fov": 110, "master": 30, "music": 20, "sfx": 10, "engine": 5, "name": "SAVED", "char": 3})
            from chopped.game import App
            args = types.SimpleNamespace(selftest=False, mute=True, no_music=True, name=None, char=None, save=None)
            app = App(args)
            try:
                got = []
                app.audio.set_volumes = lambda *a: got.append(a)
                app._apply_setting()
                self.assertEqual(got[-1], (0.3, 0.2, 0.1, 0.05))
                self.assertEqual((app.menu.name, app.menu.char), ("SAVED", 3))
                app.menu.name, app.menu.char = "NEWNAME", 1
                app._open_settings()
                app.settings["fov"] = 75
                app._close_settings()
                on_disk = SET.load()
                self.assertEqual((on_disk["fov"], on_disk["name"], on_disk["char"]), (75, "NEWNAME", 1))
            finally:
                pygame.quit()
            args2 = types.SimpleNamespace(selftest=False, mute=True, no_music=True, name="CLIGUY", char=2, save=None)
            app2 = App(args2)
            try:
                self.assertEqual((app2.menu.name, app2.menu.char), ("CLIGUY", 2))
                app2._save_settings()
                self.assertEqual(SET.load()["name"], "NEWNAME", "a --name isn't remembered as your choice")
            finally:
                pygame.quit()
        finally:
            if old is None:
                os.environ.pop("CHOPPED_SAVE_DIR", None)
            else:
                os.environ["CHOPPED_SAVE_DIR"] = old
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

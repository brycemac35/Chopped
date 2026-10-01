"""(v0.20) The 3D renderer's pure parts: boxes -> meshes, the camera maths, cache keys, the
collision-footprint fit, the stub city, the RENDERER setting and the no-OpenGL fallback.
(The GPU itself isn't tested here: the suite runs on the dummy video driver, which has no GL.)"""

import math
import os
import random
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from chopped import config as C
from chopped import fp as FP
from chopped import fpart as FA
from chopped import gl3d as G
from chopped import settings as SET
from chopped import sim as S
from chopped import vehicles as V
from chopped.mapgen import CityMap


def _row(model=V.KEI, color=3, ang=0.0, kind=S.CIV):
    """A decoded car row, just the fields the look reads."""
    return (7, kind, color, 0, 0, 0xFFFFFFFF, 0, 10.0, 20.0, 0.0, 0.0, ang, 0, 0, 0, model, 0, 0, 0, 0, 0)


class TestMesh(unittest.TestCase):
    def test_one_box_is_twelve_triangles(self):
        m = G.boxes_to_mesh([(0, 1, 0, 2, 0, 3, (255, 0, 0))])
        self.assertEqual(m.shape, (36, G.MESH_STRIDE))
        self.assertAlmostEqual(float(m[:, 6].max()), 1.0)          # colour is 0..1

    def test_faces_without_colour_are_skipped(self):
        open_top = G.boxes_to_mesh([(0, 1, 0, 1, 0, 1, {"*": (9, 9, 9), "+z": None})])
        self.assertEqual(len(open_top), 30)
        one_face = G.boxes_to_mesh([(0, 1, 0, 1, 0, 1, {"+x": (9, 9, 9)})])
        self.assertEqual(len(one_face), 6)
        self.assertEqual(G.boxes_to_mesh([]).shape, (0, G.MESH_STRIDE))

    def test_edge_coords_span_each_face(self):
        m = G.boxes_to_mesh([(0, 2, 0, 3, 0, 4, (1, 2, 3))])
        edge, size = m[:, 9:11], m[:, 11:13]
        self.assertTrue((edge >= 0).all() and (edge <= size + 1e-6).all())
        self.assertEqual({tuple(s) for s in size.tolist()}, {(3.0, 4.0), (2.0, 4.0), (2.0, 3.0)})

    def test_real_models_mesh_and_top(self):
        boxes = FA.car_boxes(S.CIV, 1, 0xFFFFFFFF, 0, 0, 0, V.VAN)
        m = G.boxes_to_mesh(boxes)
        self.assertEqual(len(m) % 3, 0)
        self.assertGreater(len(m), 36 * 10)
        self.assertAlmostEqual(G.mesh_top(m), max(b[5] for b in boxes), places=4)


class TestFootprint(unittest.TestCase):
    def test_every_car_fits_its_collision_box(self):
        """What you see is what you hit: the drawn car's plan is exactly Car.hl x Car.hw."""
        r = G.GLRenderer.__new__(G.GLRenderer)
        r._car_fit = {}
        for model in range(V.DIRTBIKE + 1):
            m = V.model(model)
            boxes = r._fit_car(model, FA.car_boxes(S.CIV, 2, 0xFFFFFFFF, 0, 0, 0, model))
            x0, x1, y0, y1 = G.box_extent(boxes)
            self.assertAlmostEqual(x0, -m.length / 2, places=4, msg=m.name)
            self.assertAlmostEqual(x1, m.length / 2, places=4, msg=m.name)
            self.assertAlmostEqual(y0, -m.width / 2, places=4, msg=m.name)
            self.assertAlmostEqual(y1, m.width / 2, places=4, msg=m.name)

    def test_stripped_car_does_not_grow(self):
        r = G.GLRenderer.__new__(G.GLRenderer)
        r._car_fit = {}
        stripped = r._fit_car(V.SEDAN, FA.car_boxes(S.CIV, 2, 0, 0, 0, 0, V.SEDAN))
        x0, x1, _y0, _y1 = G.box_extent(stripped)
        self.assertLessEqual(x1 - x0, V.model(V.SEDAN).length + 1e-6)


class TestCamera(unittest.TestCase):
    def test_matches_the_raycasters_projection(self):
        """Labels are drawn with fp's 2D maths over the GPU's picture: they must agree."""
        rng = random.Random(4)
        for _ in range(50):
            cx, cy, yaw, eye = rng.uniform(0, 500), rng.uniform(0, 500), rng.uniform(-4, 4), rng.uniform(0.3, 2.5)
            fov = math.radians(rng.uniform(60, 120))
            vw, vh = 1280, 656
            hor = rng.randint(60, 600)
            m = G.view_proj(cx, cy, yaw, eye, fov, vw, vh, hor)
            x, y, z = cx + rng.uniform(-30, 30), cy + rng.uniform(-30, 30), rng.uniform(0, 5)
            ca, sa = math.cos(yaw), math.sin(yaw)
            depth = (x - cx) * ca + (y - cy) * sa
            if depth < 0.5:
                continue
            lat = -(x - cx) * sa + (y - cy) * ca
            D = (vw / 2) / math.tan(fov / 2)
            sx, sy, w = G.project(m, x, y, z, vw, vh)
            self.assertAlmostEqual(w, depth, places=6)
            self.assertAlmostEqual(sx, vw / 2 + lat / depth * D, places=4)
            self.assertAlmostEqual(sy, hor + (eye - z) * D / depth, places=4)


class TestKeys(unittest.TestCase):
    def _renderer(self):
        r = G.GLRenderer.__new__(G.GLRenderer)
        r._phase, r.big_heads, r._car_fit = 0, False, {}
        return r

    def test_mesh_key_ignores_the_angle(self):
        """One mesh per look, whatever angle it's seen from -- that's the end of 'textures rotating'."""
        r = self._renderer()
        a = r._car_sprite(_row(), 0.3)
        b = r._car_sprite(_row(ang=2.0), -2.9)
        self.assertEqual(a.key, b.key)
        self.assertNotEqual(a.az, b.az)
        self.assertNotEqual(a.key, r._car_sprite(_row(color=5), 0.3).key)
        p1 = r._person_sprite((1, 2, 3), None, None, 0, None, False, 0.1)
        p2 = r._person_sprite((1, 2, 3), None, None, 0, None, False, 2.1)
        self.assertEqual(p1.key, p2.key)
        self.assertEqual(r._model_sprite("ramp", FA.ramp_boxes, 1.0).key, ("model", "ramp"))

    def test_sprite_key_is_look_plus_angle(self):
        """The classic renderer and gl3d share _car_look, so they agree on which car is which."""
        r = FP.FPRenderer.__new__(FP.FPRenderer)
        r._phase = 0
        look, make = r._car_look(_row())
        self.assertEqual(len(look), 10)
        self.assertTrue(make())


class TestStubWorld(unittest.TestCase):
    def test_contract(self):
        pygame.init()
        w = G.stub_build_world(CityMap(5))
        self.assertEqual(w.vertices.dtype.name, "float32")
        self.assertEqual(w.vertices.size % (6 * 3), 0)             # x y z u v shade, whole triangles
        self.assertEqual(len(w.dynamic), len(C.DOOR_COLS))
        door = w.dynamic[1]
        self.assertEqual(door.id, C.DOOR_ID + 1)
        shut, half, up = door.boxes(0.0), door.boxes(0.5), door.boxes(1.0)
        self.assertEqual(len(shut), 1)
        self.assertGreater(half[0][4], shut[0][4])                 # rolls up from the bottom
        self.assertEqual(up, [])


class TestSettingAndFallback(unittest.TestCase):
    def test_renderer_setting(self):
        self.assertEqual(SET.defaults()["renderer"], "3d")
        self.assertEqual(SET.sanitize({"renderer": "classic"})["renderer"], "classic")
        self.assertEqual(SET.sanitize({"renderer": "vulkan"})["renderer"], "3d")

    def test_no_gl_on_the_dummy_driver(self):
        pygame.init()
        pygame.display.set_mode((64, 36))
        self.assertFalse(G.gl_available())

    def test_falls_back_to_classic_when_gl_fails(self):
        """A player whose PC can't do OpenGL 3.3 still gets a game: the raycaster, and one log line."""
        from chopped import game as GM
        old_env = os.environ.get("CHOPPED_SAVE_DIR")
        os.environ["CHOPPED_SAVE_DIR"] = tempfile.mkdtemp(prefix="chopped_gl3d_")
        real = G.gl_available
        G.gl_available = lambda: True                              # pretend: the dummy driver then refuses
        try:
            args = SimpleNamespace(selftest=False, mute=True, no_music=True)
            app = GM.App(args)
            self.assertIsNone(app.gl)
            self.assertEqual(app.settings["renderer"], "3d")       # (the wish is kept for a PC that can)
            app._present()                                         # classic present still works
        finally:
            G.gl_available = real
            if old_env is None:
                os.environ.pop("CHOPPED_SAVE_DIR", None)
            else:
                os.environ["CHOPPED_SAVE_DIR"] = old_env
            pygame.quit()


if __name__ == "__main__":
    unittest.main()

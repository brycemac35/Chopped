"""The static 3D city (world3d.py): contract shape, and that what you SEE is what you COLLIDE with.
Headless: no window, no GL, numpy and pygame Surfaces only."""

import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from chopped import config as C
from chopped import mapgen as M
from chopped import world3d as W

SEEDS = (1234, 7, 99)
SOLID_GROUPS = ("walls", "parapets", "trees", "props_solid", "edge")
_cache = {}


def world(seed=1234, night=False):
    key = (seed, night)
    if key not in _cache:
        cm = M.CityMap(seed)
        t = time.time()
        w = W.build_world(cm, night)
        _cache[key] = (cm, w, time.time() - t)
    return _cache[key]


def tris_of(w, groups=None):
    """(T, 3, 6) triangles (optionally only some groups)."""
    v = w.vertices
    if groups is None:
        return v.reshape(-1, 3, 6)
    out = []
    for g in groups:
        s, n = w.groups[g]
        if n:
            out.append(v[s:s + n].reshape(-1, 3, 6))
    return np.concatenate(out) if out else np.zeros((0, 3, 6), dtype=np.float32)


def ray_hit_dist(tris, origins, dirs):
    """Moller-Trumbore, many rays against many triangles: nearest hit distance per ray (inf if none)."""
    p = tris[:, :, :3].astype(np.float64)
    v0, e1, e2 = p[:, 0], p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    best = np.full(len(origins), np.inf)
    for i in range(0, len(origins), 64):
        o = origins[i:i + 64, None, :]
        d = dirs[i:i + 64, None, :]
        h = np.cross(d, e2[None])
        a = (e1[None] * h).sum(-1)
        ok = np.abs(a) > 1e-9
        f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
        s = o - v0[None]
        u = f * (s * h).sum(-1)
        q = np.cross(s, e1[None])
        v = f * (d * q).sum(-1)
        t = f * (e2[None] * q).sum(-1)
        hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 1e-6)
        best[i:i + 64] = np.where(hit, t, np.inf).min(axis=1)
    return best


def exposed_edges(cm, only_rects=False):
    """(midpoint xy, outward normal) of every tile edge between a solid tile and an open one."""
    T = C.TILE_M
    out = []
    n = cm.n
    for ty in range(n):
        for tx in range(n):
            if not cm.solid_tile(tx, ty):
                continue
            for nx, ny in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                if cm.solid_tile(tx + nx, ty + ny):
                    continue
                mx = (tx + 0.5 + nx * 0.5) * T
                my = (ty + 0.5 + ny * 0.5) * T
                out.append(((mx, my), (nx, ny)))
    return out


def point_is_solid(cm, w, x, y, tol=0.05):
    if cm.solid_at(x, y):
        return True
    for (rx, ry, rw, rh) in list(cm.static_rects) + list(cm.edge_rects):
        if rx - tol <= x <= rx + rw + tol and ry - tol <= y <= ry + rh + tol:
            return True
    for dobj in w.dynamic:
        r = dobj.rect
        if r is not None and r[0] - tol <= x <= r[0] + r[2] + tol and r[1] - tol <= y <= r[1] + r[3] + tol:
            return True
    return False


class TestContract(unittest.TestCase):
    def test_shapes_and_ranges(self):
        cm, w, _t = world()
        v = w.vertices
        self.assertEqual(v.dtype, np.float32)
        self.assertEqual(v.ndim, 2)
        self.assertEqual(v.shape[1], 6)
        self.assertEqual(v.shape[0] % 3, 0)
        self.assertGreater(v.shape[0], 10000)
        self.assertLess(v.shape[0], 400000)
        self.assertTrue(np.isfinite(v).all())
        self.assertGreaterEqual(float(v[:, 3:5].min()), 0.0)
        self.assertLessEqual(float(v[:, 3:5].max()), 1.0)
        self.assertGreater(float(v[:, 5].min()), 0.0)
        self.assertLessEqual(float(v[:, 5].max()), 1.0)
        self.assertEqual(sum(n for _s, n in w.groups.values()), v.shape[0])

    def test_atlas_is_opaque_rgba(self):
        _cm, w, _t = world()
        a = w.atlas
        self.assertTrue(a.get_flags() & 0x00010000)           # SRCALPHA
        W_, H_ = a.get_size()
        self.assertLessEqual(max(W_, H_), 4096)
        import pygame
        alpha = pygame.surfarray.array_alpha(a)
        self.assertEqual(int(alpha.min()), 255)

    def test_uv_samples_real_texels(self):
        # every vertex lands inside the atlas, and none of them on the magenta unused-palette colour
        import pygame
        _cm, w, _t = world()
        rgb = pygame.surfarray.array3d(w.atlas)
        Wd, Hd = w.atlas.get_size()
        v = w.vertices
        px = np.clip((v[:, 3] * Wd).astype(int), 0, Wd - 1)
        py = np.clip((v[:, 4] * Hd).astype(int), 0, Hd - 1)
        col = rgb[px, py]
        self.assertFalse(((col[:, 0] == 255) & (col[:, 1] == 0) & (col[:, 2] == 255)).any())

    def test_bounds_and_version(self):
        cm, w, _t = world()
        self.assertEqual(len(w.bounds), 6)
        self.assertAlmostEqual(w.bounds[0], 0.0, places=3)
        self.assertAlmostEqual(w.bounds[3], C.MAP_M, places=3)
        self.assertGreaterEqual(w.bounds[5], 12.0)             # a three-storey building at least
        self.assertIn(str(cm.seed), w.version)
        self.assertTrue(w.version.startswith("world3d-"))
        self.assertNotEqual(world(1234, False)[1].version, world(1234, True)[1].version)

    def test_deterministic(self):
        cm = M.CityMap(321)
        a, b = W.build_world(cm), W.build_world(M.CityMap(321))
        self.assertTrue(np.array_equal(a.vertices, b.vertices))
        import pygame
        self.assertEqual(pygame.image.tobytes(a.atlas, "RGBA"), pygame.image.tobytes(b.atlas, "RGBA"))
        c = W.build_world(M.CityMap(322))
        self.assertFalse(c.vertices.shape == a.vertices.shape and np.array_equal(c.vertices, a.vertices))

    def test_build_time(self):
        _cm, _w, took = world(7)
        self.assertLess(took, 2.0, "build_world took %.2f s" % took)

    def test_winding(self):
        # frame is left-handed (y south), authored for the player's view: (v1-v0)x(v2-v0) points INWARD
        _cm, w, _t = world()
        for g, sign in (("tops", -1), ("roofs", -1), ("ceilings", 1)):
            t = tris_of(w, (g,))[:, :, :3].astype(np.float64)
            nz = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])[:, 2]
            self.assertTrue((nz * sign > 0).all(), g)
        # a building's south face: outward is +y, so the cross product points -y
        t = tris_of(w, ("walls",))[:, :, :3].astype(np.float64)
        cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        south = (np.abs(t[:, :, 1] - t[:, 0:1, 1]).max(axis=1) < 1e-6) & (np.abs(cr[:, 0]) < 1e-6)
        self.assertTrue(south.any())
        # for a face in a plane y = c, outward is +y if the thing is south of its tile...: check by tile
        cm = world()[0]
        T = C.TILE_M
        checked = 0
        for k in np.nonzero(south)[0][:4000]:
            y = t[k, 0, 1]
            cx = t[k, :, 0].mean()
            out_south = not cm.solid_at(cx, y + 0.05) and cm.solid_at(cx, y - 0.05)
            out_north = not cm.solid_at(cx, y - 0.05) and cm.solid_at(cx, y + 0.05)
            if out_south:
                self.assertLess(cr[k, 1], 0)
                checked += 1
            elif out_north:
                self.assertGreater(cr[k, 1], 0)
                checked += 1
        self.assertGreater(checked, 100)

    def test_gl_vertices_swaps_y_z(self):
        _cm, w, _t = world()
        g = w.gl_vertices()
        self.assertTrue(np.array_equal(g[:, 1], w.vertices[:, 2]))
        self.assertTrue(np.array_equal(g[:, 2], w.vertices[:, 1]))
        # ...and the swap flips handedness, so the stored order is now ordinary CCW from outside
        t = tris_of(w, ("tops",))
        tg = g[:t.shape[0] * 0 + 3 * 0 + 1]  # (keep numpy happy about slicing)
        s, n = w.groups["tops"]
        p = g[s:s + n].reshape(-1, 3, 6)[:, :, :3].astype(np.float64)
        cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        self.assertTrue((cr[:, 1] > 0).all())                  # tops face +Y (up) in GL


class TestWhatYouSeeIsWhatYouHit(unittest.TestCase):
    def test_every_solid_edge_has_a_wall(self):
        for seed in SEEDS:
            cm, w, _t = world(seed)
            tris = tris_of(w, SOLID_GROUPS)
            edges = exposed_edges(cm)
            # a spread of them (every one is slow and they are all the same code path)
            step = max(1, len(edges) // 600)
            sel = edges[::step]
            o = np.array([[mx + nx * 0.5, my + ny * 0.5, 1.0] for (mx, my), (nx, ny) in sel])
            d = np.array([[-nx, -ny, 0.0] for _p, (nx, ny) in sel])
            hit = ray_hit_dist(tris, o, d)
            bad = [sel[i][0] for i in range(len(sel)) if not hit[i] < 0.7]
            self.assertFalse(bad, "seed %d: solid edges with no wall in front: %r" % (seed, bad[:5]))

    def test_every_collision_rect_is_walled_on_every_open_side(self):
        cm, w, _t = world(1234)
        tris = tris_of(w, SOLID_GROUPS)
        T = C.TILE_M
        o, d, tag = [], [], []
        for (rx, ry, rw, rh) in cm.solid_rects:
            for k in range(int(rw // T)):                       # north and south faces, a probe per tile
                x = rx + (k + 0.5) * T
                for (y, ny) in ((ry, -1), (ry + rh, 1)):
                    if not cm.solid_at(x, y + ny * 0.1):
                        o.append((x, y + ny * 0.5, 1.0))
                        d.append((0.0, -ny, 0.0))
                        tag.append((rx, ry, rw, rh))
            for k in range(int(rh // T)):
                y = ry + (k + 0.5) * T
                for (x, nx) in ((rx, -1), (rx + rw, 1)):
                    if not cm.solid_at(x + nx * 0.1, y):
                        o.append((x + nx * 0.5, y, 1.0))
                        d.append((-nx, 0.0, 0.0))
                        tag.append((rx, ry, rw, rh))
        self.assertGreater(len(o), 300)
        hit = ray_hit_dist(tris, np.array(o), np.array(d))
        miss = [tag[i] for i in range(len(o)) if not hit[i] < 0.7]
        self.assertFalse(miss, "collision rects with an open side and no wall: %r" % (miss[:5],))

    def test_no_wall_where_physics_says_open(self):
        for seed in SEEDS:
            cm, w, _t = world(seed)
            t = tris_of(w, SOLID_GROUPS)[:, :, :3].astype(np.float64)
            cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
            vertical = np.abs(cr[:, 2]) < 1e-9 * (1 + np.abs(cr).max())
            zlo, zhi = t[:, :, 2].min(axis=1), t[:, :, 2].max(axis=1)
            span = vertical & (zlo <= 1.0) & (zhi >= 1.0)
            idx = np.nonzero(span)[0]
            bad = []
            for k in idx:
                n_xy = cr[k, :2]
                ln = math.hypot(*n_xy)
                if ln < 1e-12:
                    continue
                nx, ny = -n_xy[0] / ln, -n_xy[1] / ln           # stored order points IN, so outward is the other way
                xs, ys = t[k, :, 0], t[k, :, 1]
                for s in (0.25, 0.5, 0.75):
                    # a point along the longest horizontal edge of the triangle
                    pts = [(xs[i], ys[i]) for i in range(3)]
                    best = max(((pts[a], pts[b]) for a in range(3) for b in range(a + 1, 3)),
                               key=lambda e: (e[0][0] - e[1][0]) ** 2 + (e[0][1] - e[1][1]) ** 2)
                    px = best[0][0] + (best[1][0] - best[0][0]) * s
                    py = best[0][1] + (best[1][1] - best[0][1]) * s
                    if not point_is_solid(cm, w, px - nx * 0.05, py - ny * 0.05):
                        bad.append((round(px, 2), round(py, 2)))
            self.assertFalse(bad, "seed %d: wall faces over open ground: %r" % (seed, bad[:5]))

    def test_static_props_cover_their_rects(self):
        cm, w, _t = world(1234)
        tris = tris_of(w, ("props_solid", "walls"))
        r_npc = C.STORY_NPC_R
        checked = 0
        for (rx, ry, rw, rh) in cm.static_rects:
            if abs(rw - 2 * r_npc) < 1e-6 and abs(rh - 2 * r_npc) < 1e-6:
                continue                                         # a standing person: drawn as a person
            cx, cy = rx + rw / 2, ry + rh / 2
            probes = [((rx - 0.5, cy, 0.5), (1, 0, 0)), ((rx + rw + 0.5, cy, 0.5), (-1, 0, 0)),
                      ((cx, ry - 0.5, 0.5), (0, 1, 0)), ((cx, ry + rh + 0.5, 0.5), (0, -1, 0))]
            hits = 0
            for o, d in probes:
                dist = ray_hit_dist(tris, np.array([o]), np.array([d], dtype=float))[0]
                far = (rw if d[0] else rh)
                if dist < far / 2 + 0.5 + 0.3:
                    hits += 1
            self.assertGreaterEqual(hits, 2, "static rect %r has no visible thing in it" % ((rx, ry, rw, rh),))
            checked += 1
        self.assertGreater(checked, 10)

    def test_trees_fill_their_tiles(self):
        cm, w, _t = world(1234)
        tris = tris_of(w, ("trees",))
        T = C.TILE_M
        n = cm.n
        trees = [(tx, ty) for ty in range(n) for tx in range(n) if cm.tiles[ty * n + tx] == M.TREE]
        self.assertGreater(len(trees), 10)
        o = np.array([[(tx + 0.5) * T + T, (ty + 0.5) * T, 0.8] for tx, ty in trees])
        d = np.tile(np.array([[-1.0, 0.0, 0.0]]), (len(trees), 1))
        hit = ray_hit_dist(tris, o, d)
        self.assertTrue((hit < T / 2 + 0.2).all())               # the blob reaches within ~10 cm of the tile edge


class TestShopFront(unittest.TestCase):
    def test_doors_are_open_air_and_lintels_close_the_sky(self):
        cm, w, _t = world(1234)
        gx, gy, gw, gh = cm.garage_rect
        yl = gy + gh
        T = C.TILE_M
        tris = tris_of(w)
        for col in C.DOOR_COLS[1:]:
            x = gx + (col + 0.5) * T
            # at head height a ray from the street straight into the door opening goes through the (dynamic) door line
            hit = ray_hit_dist(tris, np.array([[x, yl + T + 3, 1.0]]), np.array([[0.0, -1.0, 0.0]]))[0]
            self.assertGreater(hit, T + 3 + 1.0)               # nothing static in the way of an open bay: it reaches the interior
            # ...but straight up the front you can't see sky: brick over the opening
            up = ray_hit_dist(tris, np.array([[x, yl + 1.0, 3.0]]), np.array([[0.0, 0.0, 1.0]]))[0]
            self.assertLess(up, 3.5)
        # the piers (solid wall tiles between the pairs of bays) are walls
        px = gx + 3.5 * T
        hit = ray_hit_dist(tris, np.array([[px, yl + T + 3, 1.0]]), np.array([[0.0, -1.0, 0.0]]))[0]
        self.assertLess(hit, 3.5)

    def test_ceiling_and_roof(self):
        cm, w, _t = world(1234)
        gx, gy, gw, gh = cm.garage_rect
        tris = tris_of(w, ("ceilings",))
        hit = ray_hit_dist(tris, np.array([[gx + gw / 2, gy + gh / 2, 1.6]]), np.array([[0.0, 0.0, 1.0]]))[0]
        self.assertAlmostEqual(hit, C.ROOF_H - 1.6, places=3)
        self.assertEqual(len(w.roofed), 1 + len(cm.fence_shops))
        for fs in cm.fence_shops:
            fx, fy, fw, fh = fs["rect"]
            hit = ray_hit_dist(tris, np.array([[fx + fw / 2, fy + fh / 2, 1.6]]), np.array([[0.0, 0.0, 1.0]]))[0]
            self.assertAlmostEqual(hit, C.ROOF_H - 1.6, places=3)

    def test_parapets_sit_above_the_ceiling(self):
        _cm, w, _t = world(1234)
        s, n = w.groups["parapets"]
        self.assertGreater(n, 0)
        p = w.vertices[s:s + n]
        self.assertGreaterEqual(float(p[:, 2].min()), C.ROOF_H - 1e-4)


class TestDynamic(unittest.TestCase):
    def test_ids_match_the_sim(self):
        cm, w, _t = world(1234)
        byid = {d.id: d for d in w.dynamic if d.id is not None}
        for i in range(5):
            self.assertIn(C.DOOR_ID + i, byid)
        self.assertEqual(byid[C.DOOR_ID].kind, "walkdoor")
        self.assertEqual(byid[C.DOOR_ID + 1].kind, "door")
        self.assertIn(C.GATE_ID, byid)
        for k in range(len(cm.cell_doors)):
            self.assertIn(C.CELL_ID_BASE + k, byid)
        junk = [d for d in w.dynamic if d.kind == "junk"]
        self.assertEqual(len(junk), C.JUNK_PER_SHOP * len(cm.fence_shops))
        for d in junk:
            self.assertGreaterEqual(d.id, C.JUNK_ID_BASE)
        self.assertEqual(len(set(byid)), len(byid))
        kinds = {d.kind for d in w.dynamic}
        self.assertTrue({"door", "walkdoor", "gate", "celldoor", "junk", "lever", "sale_board", "crate"} <= kinds)

    def test_door_boxes_follow_the_state(self):
        cm, w, _t = world(1234)
        d = {x.id: x for x in w.dynamic if x.id is not None}[C.DOOR_ID + 1]
        shut, open_ = d.boxes_for(0.0), d.boxes_for(1.0)
        self.assertGreater(len(shut), 0)
        self.assertEqual(open_, [])
        self.assertAlmostEqual(min(b[4] for b in shut), 0.0)
        self.assertAlmostEqual(max(b[5] for b in shut), C.ROOF_H)
        half = d.boxes_for(0.5)
        self.assertAlmostEqual(min(b[4] for b in half), 0.5 * C.ROOF_H, places=3)
        gx, gy, gw, gh = cm.garage_rect
        for b in shut:                                           # world coordinates, on the door line
            self.assertTrue(b[0] >= d.pos[0] - C.DOOR_W / 2 - 0.1 and b[1] <= d.pos[0] + C.DOOR_W / 2 + 0.1)
            self.assertTrue(abs((b[2] + b[3]) / 2 - (gy + gh)) < 0.1)

    def test_box_shapes_everywhere(self):
        _cm, w, _t = world(1234)
        states = {"door": (0.0, 0.5, 1.0), "walkdoor": (0.0, 1.0), "gate": (0, 1), "celldoor": (0.0, 0.5, 1.0),
                  "junk": (False, True), "lever": (False, True), "sale_board": (0, 1, 2), "crate": (False, True)}
        for d in w.dynamic:
            for st in states[d.kind]:
                for b in d.boxes_for(st):
                    self.assertEqual(len(b), 7)
                    self.assertLessEqual(b[0], b[1])
                    self.assertLessEqual(b[2], b[3])
                    self.assertLessEqual(b[4], b[5])
                    self.assertTrue(abs(b[0] - d.pos[0]) < 8 and abs(b[2] - d.pos[1]) < 8, (d, b))
                self.assertEqual(d.boxes_for(st), d.boxes_for(st))
        self.assertEqual(len([d for d in w.dynamic if d.kind == "gate"][0].boxes_for(0)), 0)
        self.assertGreater(len([d for d in w.dynamic if d.kind == "gate"][0].boxes_for(1)), 4)

    def test_meshing_dynamic_boxes_and_quads(self):
        _cm, w, _t = world(1234)
        for d in w.dynamic:
            st = d.default_state
            v = w.mesh_boxes(d.boxes_for(1 if d.kind in ("junk", "crate") else st if d.kind != "door" else 0.0))
            self.assertEqual(v.shape[1], 6)
            self.assertEqual(v.shape[0] % 3, 0)
            if len(v):
                self.assertTrue(np.isfinite(v).all())
                self.assertTrue(((v[:, 3:5] >= 0) & (v[:, 3:5] <= 1)).all())
        board = [d for d in w.dynamic if d.kind == "sale_board"][0]
        q = board.quads_for(0)
        self.assertEqual(q.shape, (12, 6))
        self.assertNotEqual(board.quads_for(0).tolist(), board.quads_for(2).tolist())
        u, v = w.palette_uv((214, 58, 58))
        self.assertTrue(0 <= u <= 1 and 0 <= v <= 1)


class TestOtherStyles(unittest.TestCase):
    def test_night_builds_and_differs(self):
        _cm, day, _t = world(1234, False)
        _cm2, night, _t2 = world(1234, True)
        self.assertEqual(day.vertices.shape, night.vertices.shape)
        import pygame
        self.assertNotEqual(pygame.image.tobytes(day.atlas, "RGBA"), pygame.image.tobytes(night.atlas, "RGBA"))

    def test_vertex_budget(self):
        for seed in SEEDS:
            _cm, w, _t = world(seed)
            self.assertLess(w.vertex_count(), 400000)

    def test_no_pygame_display_needed_and_no_moderngl(self):
        import inspect
        src = inspect.getsource(W)
        self.assertNotIn("import moderngl", src)


if __name__ == "__main__":
    unittest.main()

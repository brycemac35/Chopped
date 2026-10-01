"""
world3d.py -- the static city, as real triangles. (v0.20, the 3D move.)

The raycaster (fp.py) turns tiles into walls one ray at a time; the GL renderer wants the whole
city as one vertex buffer and one texture atlas, built once from the CityMap. This module is
that builder. It is deliberately PURE: numpy plus pygame Surfaces, no moderngl, no window, so
the geometry can be unit-tested headless and the same build feeds the viewer in
tools/view_world3d.py and the real renderer. Every texture is still generated in code (fpart.py
facades, brick, doors, roofs) at the raycaster's own 8 px per metre, so the city keeps its
chunky look: the renderer samples NEAREST and never mips.

THE CONTRACT (build_world(cmap, night=False) -> World3D)
  .vertices  float32 (N, 6) interleaved x, y, z, u, v, shade. Triangles, 3 vertices each.
  .atlas     pygame RGBA Surface, fully opaque (alpha 255 everywhere: no alpha test needed).
             u, v in 0..1 with v = 0 at the TOP row of the surface. Sample NEAREST.
  .dynamic   list of Dynamic: things that move or change (doors, gate, cell doors, junk, lever,
             sale boards, fence crates). Each has .id (the sim's trap/fixture id, or None),
             .kind, .default_state and .boxes_for(state) -> fpart-style boxes in WORLD coords.
  .bounds    (xmin, ymin, zmin, xmax, ymax, zmax) of everything in .vertices.
  .version   str, "world3d-<format>:<seed>:<day|night>".
  Extras (additive, ignore freely): .groups (name -> (first_vertex, vertex_count), see GROUPS),
  .lamps (x, y, z) of every street lamp's bulb (for night lights), .roofed (the roofed
  buildings, so the renderer can cull ceilings/parapets), .palette_uv(rgb), .mesh_boxes(boxes),
  .gl_vertices() and Dynamic.quads_for(state).

COORDINATES (read this one twice, it bit the raycaster in v0.8 too)
  World metres in SIM coordinates: x east, y SOUTH (down the automap), z up, the same x, y
  that physics uses for cars and people. That frame is LEFT-handed. Winding and UVs are
  authored for what the PLAYER sees (the raycaster's camera: right = forward turned +90 deg in
  xy), so text reads the right way round and faces are counter-clockwise from outside AS THE
  PLAYER SEES THEM. In raw numbers that means (v1-v0) x (v2-v0) points INWARD. Two ways to
  render it:  (a) feed (x, y, z) as is, with a camera whose right vector is forward turned +90
  deg in xy (a left-handed view basis) and cull the way that basis implies; or (b) call
  .gl_vertices(), which hands back (x, z, y): a normal right-handed Y-up GL space where the
  unmirrored city is correct with ordinary CCW front faces and a standard lookAt (GL x = sim x,
  GL z = sim y, so "south" is toward the viewer, as on a map).

WHAT IS HERE (static meshes)   -- everything the raycaster drew from tile data
  walls       every exposed face of every solid tile (BUILDING, WALL), so what you see is exactly
              what the physics rectangles (CityMap.solid_rects, greedy-merged from the same
              tiles) collide with. Per-building heights (3-6 storeys of 4 m), facades, the shop's
              brick, piers, signs, the walking-door jambs, the precinct, the map's edge wall.
  parapets    the 6..8 m strip of the shop and garage walls above their ceiling (separate group
              so a renderer indoors can skip it).
  tops        building roofs (a coloured gravel tile per tile) and wall coping.
  ceilings    the shop and garage ceilings (fpart.roof_texture), seen from below.
  roofs       the flat tarred roof above those ceilings, seen from above.
  trees       the park trees (leafy blobs filling their 4 m tile, like their collision does).
  lamps       street lamps; cameras: the camera poles.
  props_solid the things physics is solid about: the counters, the bail desk, the records hatch,
              the cell bars. props_free: things you can walk through (market crates, ramps).
  Lintels: the brick over the shop's bays and walking door, the fence garages' fronts and the
  precinct doorway are full-depth slabs (the raycaster's were paper-thin planes that left a
  sky-coloured hole in the street-side view; a slab closes it).
  The raycaster never drew the precinct's doorway lintel (it was a hole to the sky); it has one now.

WHAT IS NOT HERE: the ground and street (the renderer paints those from the live map surface),
  cars, people, pickups, traps other than the fixtures listed in .dynamic, the chute (a
  cosmetic effect, not map data), pigeons, the sky.
  The story NPCs and the staff have solid invisible squares in CityMap.static_rects: they are
  people, and the renderer draws people.

Tuning numbers live up here (not in config.py: nothing on the wire or in the sim reads them).
"""

import math

import numpy as np
import pygame

from . import config as C
from . import mapgen as M
from . import fpart as FA
from .art import P, ROOF_COLORS, CAR_COLORS, PLAYER_COLORS, SKINS, HAIRS, SHIRTS, PixelFont, shade

FORMAT = 1
T = C.TILE_M
PX_M = FA.TEX / T                     # texels per metre: 8, the raycaster's own density
FACADE_H = C.SHOP_FACADE_H            # 8 m: the top of the shop's parapet
ROOF_H = C.ROOF_H                     # 6 m: the shop ceiling
EDGE_H = 6.0                          # the world-edge wall: concrete_wall is 48 texels = 6 m of texture
PRECINCT_LINTEL = 3.2                 # m: the gate is 2.45 m tall; brick over it from here, up to the 8 m coping

# Per-face brightness, multiplied in by the shader. Cheap fake sunlight: tops full, the east
# and south faces a touch lit, the west and north faces sulking, undersides the dimmest.
# (The raycaster only knew "x faces" and "y faces", one shade level apart; this is that, plus
# a sun, because real 3D gets to have opinions.)
FACE_SHADE = {"+z": 1.0, "+x": 0.94, "-x": 0.86, "+y": 0.90, "-y": 0.80, "-z": 0.68}
CEIL_PPM = 8                          # the shop roof's texels per metre: the raycaster's ROOF_PPM (it's right above you)
CEIL_SHADE = 0.95                    # the shop ceiling's own lights do the lighting; keep it flat
LAMP_H = 5.6                          # m: street lamp pole
CAM_POLE_H = 4.3                      # m: camera pole
TREE_SKIRT = 3.8                      # m: the tree's dense lower blob (its tile is 4: physics is solid to the edge)

GROUPS = ("walls", "parapets", "tops", "ceilings", "roofs", "edge", "trees", "lamps", "cameras",
          "props_solid", "props_free")
PAL_W, PAL_H = 128, 16                # palette block in the atlas (2048 flat-colour texels)
FACE_DIRS = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}


# ---------------------------------------------------------------------------
# Box placement (fpart models live in a model frame: x forward, y to the right, z up)
# ---------------------------------------------------------------------------
_ROT = ((1, 0), (0, 1), (-1, 0), (0, -1))


def place(boxes, x, y, ang=0.0, z=0.0):
    """fpart-style boxes (model frame) to world coordinates: turned by `ang` (rounded to the
    nearest quarter turn: boxes are axis-aligned, and everything the map places is square to
    the grid anyway), then moved to (x, y, z). Face names in colour dicts turn with them."""
    k = int(round(ang / (math.pi / 2))) % 4
    c, s = _ROT[k]
    out = []
    for (x0, x1, y0, y1, z0, z1, col) in boxes:
        xa, xb = c * x0 - s * y0, c * x1 - s * y1
        ya, yb = s * x0 + c * y0, s * x1 + c * y1
        if isinstance(col, dict) and k:
            nc = {}
            for key, v in col.items():
                if key in FACE_DIRS:
                    fx, fy = FACE_DIRS[key]
                    wx, wy = c * fx - s * fy, s * fx + c * fy
                    key = "+x" if wx > 0 else "-x" if wx < 0 else "+y" if wy > 0 else "-y"
                nc[key] = v
            col = nc
        out.append((x + min(xa, xb), x + max(xa, xb), y + min(ya, yb), y + max(ya, yb), z + z0, z + z1, col))
    return out


# ---------------------------------------------------------------------------
# The atlas: shelf-packed, one-texel extruded gutters, a flat-colour palette block
# ---------------------------------------------------------------------------
class _Atlas:
    def __init__(self):
        self.items = {}               # key -> Surface (opaque RGB)
        self.hz = {}                  # key -> how many metres tall the texture is
        self.colours = {}             # (r, g, b) -> palette index
        self.colour_list = []
        self.regions = None           # key -> (x, y, w, h) once packed
        self.size = None
        self.surface = None
        self._pal_np = None

    def add(self, key, surf, hz=None):
        if key not in self.items:
            self.items[key] = surf
            self.hz[key] = hz if hz is not None else surf.get_height() / PX_M

    def colour(self, rgb):
        rgb = tuple(int(v) for v in rgb[:3])
        i = self.colours.get(rgb)
        if i is None:
            if self.regions is not None:               # packed: nearest palette entry will do
                if self._pal_np is None:
                    self._pal_np = np.array(self.colour_list, dtype=np.int32)
                d = ((self._pal_np - np.array(rgb, dtype=np.int32)) ** 2).sum(axis=1)
                return int(d.argmin())
            if len(self.colour_list) >= PAL_W * PAL_H:
                raise ValueError("world3d palette is full")
            i = self.colours[rgb] = len(self.colour_list)
            self.colour_list.append(rgb)
        return i

    def pack(self):
        pal = pygame.Surface((PAL_W, PAL_H))
        pal.fill((255, 0, 255))
        for i, rgb in enumerate(self.colour_list):
            pal.set_at((i % PAL_W, i // PAL_W), rgb)
        items = dict(self.items)
        items["__pal__"] = pal
        order = sorted(items, key=lambda k: (-items[k].get_height(), -items[k].get_width(), str(k)))
        width = 1024
        for k in order:
            width = max(width, items[k].get_width() + 2)
        while True:
            x = y = row_h = 0
            pos = {}
            for k in order:
                w, h = items[k].get_size()
                if x + w + 2 > width:
                    x, y, row_h = 0, y + row_h, 0
                pos[k] = (x + 1, y + 1, w, h)
                x += w + 2
                row_h = max(row_h, h + 2)
            total_h = y + row_h
            if total_h <= width * 2:
                break
            width *= 2
        height = 1
        while height < total_h:
            height *= 2
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 255))
        for k, (x, y, w, h) in pos.items():
            s = items[k]
            surf.blit(s, (x, y))
            surf.blit(s, (x - 1, y), (0, 0, 1, h))                    # extrude the edge texels one pixel out,
            surf.blit(s, (x + w, y), (w - 1, 0, 1, h))                # so a uv a hair outside a region
            surf.blit(s, (x, y - 1), (0, 0, w, 1))                    # still samples that region's colour
            surf.blit(s, (x, y + h), (0, h - 1, w, 1))
        self.regions = pos
        self.size = (width, height)
        self.surface = surf
        return surf


# ---------------------------------------------------------------------------
# The mesh accumulator: quads in, triangles out
# ---------------------------------------------------------------------------
class _Mesh:
    def __init__(self, atlas):
        self.atlas = atlas
        self.g = {n: ([], [], [], [], []) for n in GROUPS}   # pos, local uv, key, normal, shade
        self.keys = {}

    def _key(self, key):
        i = self.keys.get(key)
        if i is None:
            i = self.keys[key] = len(self.keys)
        return i

    def quad(self, group, pts, uvs, key, n, sh):
        pos, uv, ks, ns, ss = self.g[group]
        pos.append(pts)
        uv.append(uvs)
        ks.append(self._key(key))
        ns.append(n)
        ss.append(sh)

    # --- textured vertical face. a, b: xy endpoints; u runs the way a player outside reads (left to right)
    def vface(self, group, a, b, z0, z1, n, key, sh=None, anchor=None, uw=T, hz=None, zb=0.0):
        ux, uy = n[1], -n[0]
        if (b[0] - a[0]) * ux + (b[1] - a[1]) * uy < 0:
            a, b = b, a
        if anchor is None:
            anchor = a
        ua = ((a[0] - anchor[0]) * ux + (a[1] - anchor[1]) * uy) / uw
        ub = ((b[0] - anchor[0]) * ux + (b[1] - anchor[1]) * uy) / uw
        if hz is None:
            hz = self.atlas.hz[key]
        # (zb: where the texture's bottom row sits. v0.20 fix: the records/sale boards hang 1.25 m up,
        # and with v counted from the ground they sampled whatever was above them in the atlas -- brick)
        va, vb = 1.0 - (z0 - zb) / hz, 1.0 - (z1 - zb) / hz
        if sh is None:
            sh = FACE_SHADE["+x" if n[0] > 0 else "-x" if n[0] < 0 else "+y" if n[1] > 0 else "-y"]
        self.quad(group, ((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)),
                  ((ua, va), (ub, va), (ub, vb), (ua, vb)), key, (n[0], n[1], 0.0), sh)

    # --- horizontal face, the whole texture stretched over the rectangle
    def hface(self, group, x0, x1, y0, y1, z, up, key, sh=None):
        if sh is None:
            sh = FACE_SHADE["+z" if up else "-z"]
        self.quad(group, ((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)),
                  ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), key, (0.0, 0.0, 1.0 if up else -1.0), sh)

    def colour_key(self, rgb):
        i = self.atlas.colour(rgb)
        return ("pal", i), ((i % PAL_W) + 0.5) / PAL_W, ((i // PAL_W) + 0.5) / PAL_H

    def cface(self, group, pts, n, col, sh):
        """A flat face in a palette colour (or, if col is a str, in that atlas texture)."""
        if isinstance(col, str):
            key, lu, lv = col, None, None
            uvs = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
        else:
            key, lu, lv = self.colour_key(col)
            uvs = ((lu, lv),) * 4
        self.quad(group, pts, uvs, "__pal__" if lu is not None else key, n, sh)

    def box(self, group, x0, x1, y0, y1, z0, z1, col, skip=()):
        """An axis-aligned box. col: RGB, {face: RGB, "*": RGB} (fpart style) or an atlas key."""
        faces = (
            ("+x", ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)), (1.0, 0.0, 0.0)),
            ("-x", ((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)), (-1.0, 0.0, 0.0)),
            ("+y", ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)), (0.0, 1.0, 0.0)),
            ("-y", ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)), (0.0, -1.0, 0.0)),
            ("+z", ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), (0.0, 0.0, 1.0)),
            ("-z", ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)), (0.0, 0.0, -1.0)))
        for name, pts, n in faces:
            if name in skip:
                continue
            c = col.get(name, col.get("*")) if isinstance(col, dict) else col
            if c is None:
                continue
            self.cface(group, pts, n, c, FACE_SHADE[name])

    def boxes(self, group, boxes, skip_floor=True):
        for (x0, x1, y0, y1, z0, z1, col) in boxes:
            self.box(group, x0, x1, y0, y1, z0, z1, col, skip=("-z",) if skip_floor and z0 <= 1e-6 else ())

    # --- the end of the line: arrays
    def finalize(self, regions, size, order=GROUPS):
        W, H = size
        kn = len(self.keys)
        rr = np.zeros((max(kn, 1), 4), dtype=np.float64)
        for key, i in self.keys.items():
            rr[i] = regions["__pal__"] if (isinstance(key, tuple) and key[0] == "pal") or key == "__pal__" else regions[key]
        chunks, groups, start = [], {}, 0
        for name in order:
            pos, uv, ks, ns, ss = self.g[name]
            if not pos:
                groups[name] = (start, 0)
                continue
            p = np.asarray(pos, dtype=np.float64)                 # (q, 4, 3)
            t = np.asarray(uv, dtype=np.float64)                  # (q, 4, 2)
            kidx = np.asarray(ks, dtype=np.int64)
            n = np.asarray(ns, dtype=np.float64)
            s = np.asarray(ss, dtype=np.float64)
            r = rr[kidx]
            u = (r[:, 0:1] + t[:, :, 0] * r[:, 2:3]) / W
            v = (r[:, 1:2] + t[:, :, 1] * r[:, 3:4]) / H
            cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
            flip = (cr * n).sum(axis=1) > 0                       # we want the cross product to point IN (left-handed frame)
            idx_a = np.array([0, 1, 2, 0, 2, 3])
            idx_b = np.array([0, 2, 1, 0, 3, 2])
            idx = np.where(flip[:, None], idx_b[None, :], idx_a[None, :])     # (q, 6)
            q = len(pos)
            rows = np.arange(q)[:, None]
            out = np.empty((q, 6, 6), dtype=np.float32)
            out[:, :, 0:3] = p[rows, idx]
            out[:, :, 3] = u[rows, idx]
            out[:, :, 4] = v[rows, idx]
            out[:, :, 5] = s[:, None]
            chunks.append(out.reshape(-1, 6))
            groups[name] = (start, q * 6)
            start += q * 6
        verts = np.concatenate(chunks) if chunks else np.zeros((0, 6), dtype=np.float32)
        return verts, groups


# ---------------------------------------------------------------------------
# Textures (the same builders fp.py's _wall_tex uses, minus the renderer around them)
# ---------------------------------------------------------------------------
def _sign_surface(font, text, w, h, x, y, col=None, outline=(0, 0, 0)):
    sign = pygame.Surface((w, h), pygame.SRCALPHA)
    font.draw(sign, text, x, y, col or P["gold"], outline, align="center")
    return sign


def _wall_surface(key, night, font, sc=1):
    """The texture for a wall def, built exactly as fp.FPRenderer._wall_tex builds it at world
    scale `sc` (v0.20: gl3d builds the city at the render scale, so 2x shows 2x the brickwork).
    (Kept as a copy rather than a refactor of fp.py: the raycaster is mid-surgery and this is
    the thing that has to keep matching it.)"""
    kind = key[0]
    facade_px = int(FACADE_H * FA.TEX / 4)

    def put(surf, sign, x, y):
        # the lettering stays the 3x5 font at its old size, just in chunkier pixels (as fp does)
        if sc > 1:
            sign = pygame.transform.scale_by(sign, sc)
        surf.blit(sign, (x * sc, y * sc))
    if kind == "bld":
        return FA.facade(key[1], key[2], key[3], night, sc)
    if kind == "precinct":
        surf = FA.precinct_wall(64, night, sc)
        if key[1]:
            sign = pygame.Surface((FA.TEX, 10), pygame.SRCALPHA)
            sign.fill((30, 60, 150))
            font.draw(sign, "POLICE", FA.TEX // 2, 2, P["white"], None, align="center")
            put(surf, sign, 0, 14)
        return surf
    if kind == "brick":
        sy = facade_px - int(4.75 * FA.TEX / 4)
        surf = FA.brick_wall(facade_px, night, sign=key[1] >= 0, sign_y=sy, sc=sc)
        if key[1] >= 0:
            put(surf, _sign_surface(font, "CHOP SHOP", FA.TEX * 3, 12, FA.TEX * 3 // 2, 3), -key[1] * FA.TEX, sy + 2)
        return surf
    if kind == "pier":
        surf = FA.brick_wall(facade_px, night, sign=True, sc=sc)
        put(surf, _sign_surface(font, "CHOP SHOP", FA.TEX * 2, 12, FA.TEX, 3), -key[1] * FA.TEX, 12)
        return surf
    if kind == "walkdoor":
        return FA.walk_door(facade_px, night, sc)
    if kind == "fsign":
        surf = FA.brick_wall(facade_px, night, sign=True, sc=sc)
        put(surf, _sign_surface(font, "SHOP %d" % (key[1] + 1), FA.TEX, 12, FA.TEX // 2, 3), 0, 12)
        return surf
    return FA.concrete_wall(48, night, sc)


def _roof_top_tile(style, night):
    """A 4 m x 4 m patch of building roof seen from above: the style's colour, gravelled."""
    import random
    rng = random.Random(style * 53 + 7)
    base = shade(ROOF_COLORS[style % len(ROOF_COLORS)], 0.62 if not night else 0.38)
    s = pygame.Surface((FA.TEX, FA.TEX))
    s.fill(base)
    for _ in range(150):
        s.set_at((rng.randrange(FA.TEX), rng.randrange(FA.TEX)), shade(base, rng.choice((0.82, 0.9, 1.12, 1.22))))
    for y in (7, 23):                                           # tar seams
        s.fill(shade(base, 0.7), (0, y, FA.TEX, 1))
    s.fill(shade(base, 0.78), (rng.randrange(4, 20), rng.randrange(4, 20), 8, 6))      # an air-con box, from above
    return s


def _gravel_tile(night):
    import random
    rng = random.Random(1994)
    base = (74, 74, 80) if not night else (40, 40, 48)
    s = pygame.Surface((FA.TEX, FA.TEX))
    s.fill(base)
    for _ in range(200):
        s.set_at((rng.randrange(FA.TEX), rng.randrange(FA.TEX)), shade(base, rng.choice((0.75, 0.88, 1.15, 1.3))))
    return s


def _leaf_tile(night):
    import random
    rng = random.Random(77)
    s = pygame.Surface((16, 16))
    s.fill(P["tree"])
    for _ in range(90):
        s.set_at((rng.randrange(16), rng.randrange(16)), rng.choice((P["tree_d"], P["tree_d"], P["tree_l"], P["grass_l"])))
    if night:
        s.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_MULT)
    return s


def _sale_surface(font, idx, state):
    """The face of a fence garage's board (fp._sale_sign's top half, without the post):
    state 0 for sale, 1 bought but full of junk, 2 open for business."""
    w, h = 44, 20
    img = pygame.Surface((w, h))
    board = (40, 110, 60) if state else (230, 226, 214)
    img.fill(P["ink"])
    img.fill(board, (1, 1, w - 2, h - 2))
    if state:
        font.draw(img, "SHOP %d" % (idx + 1), w // 2, 3, P["white"], None, align="center")
        font.draw(img, "OURS NOW" if state == 2 else "CLEAR IT", w // 2, 11, P["gold"], None, align="center")
    else:
        font.draw(img, "FOR SALE", w // 2, 3, (190, 30, 40), None, align="center")
        font.draw(img, "$" + "{:,}".format(C.SHOP_PRICE[idx]), w // 2, 11, P["ink"], None, align="center")
    return img


def _records_surface(font):
    w, h = 44, 20
    img = pygame.Surface((w, h))
    img.fill(P["ink"])
    img.fill((40, 60, 150), (1, 1, w - 2, h - 2))
    font.draw(img, "RECORDS", w // 2, 3, P["white"], None, align="center")
    font.draw(img, "PAPERS", w // 2, 11, P["gold"], None, align="center")
    return img


# ---------------------------------------------------------------------------
# Dynamic things
# ---------------------------------------------------------------------------
class Dynamic:
    """Something that moves or changes. `boxes_for(state)` returns fpart-style boxes in WORLD
    coordinates (x0, x1, y0, y1, z0, z1, colour-or-{face: colour}) for the given state:
      kind "door"        state = open fraction 0..1 (the snapshot's door row / 255; 1 = all the way up)
      kind "walkdoor"    same (the leaf is shut below 0.5, swung open above)
      kind "gate"        state = 1 shut / 0 open (the precinct gate)
      kind "celldoor"    state = health fraction 0..1 (the snapshot's cell-door row / 255; 0 = open)
      kind "junk"        state = truthy while the pile is there
      kind "lever"       state = True when the master lever is DOWN (every door shut)
      kind "crate"       state = truthy once the garage is bought AND cleared out (fp's `shops & (16 << idx)`)
      kind "sale_board"  state = 0 for sale, 1 bought but junky, 2 open (boxes: post and backing;
                         quads_for(state) adds the lettered face as textured quads)
    `pos` is the (x, y) it stands at, `rect` the physics rectangle (x, y, w, h) it blocks while
    solid (or None), `info` any extras. `default_state` is the sim's own starting state."""

    def __init__(self, id_, kind, pos, boxes_fn, default_state, rect=None, quads_fn=None, **info):
        self.id = id_
        self.kind = kind
        self.pos = pos
        self.rect = rect
        self.default_state = default_state
        self._boxes = boxes_fn
        self._quads = quads_fn
        self.info = info

    def boxes_for(self, state):
        return self._boxes(state)

    def quads_for(self, state):
        """Textured quads (float32 (N, 6) vertices in the .vertices layout), or an empty array."""
        if self._quads is None:
            return np.zeros((0, 6), dtype=np.float32)
        return self._quads(state)

    def __repr__(self):
        return "Dynamic(%r, %r, pos=%r)" % (self.id, self.kind, self.pos)


def _door_boxes(cx, yl, up):
    """One 4 m bay door rolled up to `up`: it occupies z = up*H .. H (it rises into the lintel,
    just as the raycaster's _door_slice did), a slatted body between two dark frame posts."""
    if up >= 0.97:
        return []
    H = ROOF_H
    lo = max(0.0, up) * H
    x0, x1 = cx - C.DOOR_W / 2, cx + C.DOOR_W / 2
    d = C.DOOR_T / 2
    post = (84, 80, 86)
    base = (150, 152, 160)
    out = [(x0, x0 + 0.38, yl - d, yl + d, lo, H, post), (x1 - 0.38, x1, yl - d, yl + d, lo, H, post)]
    n = max(1, int(math.ceil((H - lo) / 0.5)))
    for k in range(n):                                         # sectional panels, a seam between each
        za = H - (k + 1) * 0.5
        zb = H - k * 0.5
        za = max(za, lo)
        if zb - za < 0.02:
            continue
        out.append((x0 + 0.38, x1 - 0.38, yl - d, yl + d, za, zb, shade(base, 1.0 if k % 2 == 0 else 0.84)))
    out.append((x0 + 0.38, x1 - 0.38, yl - d - 0.02, yl + d + 0.02, lo, min(H, lo + 0.3), (56, 56, 62)))     # kick bar
    out.append((x0 + 0.5, x1 - 0.5, yl - d - 0.03, yl + d + 0.03, lo + 0.3, min(H, lo + 0.5), P["line_y"]))  # hazard stripe
    return out


def _walk_door_boxes(cx, yl, up):
    """The staff door: an oxblood leaf with a wired-glass window in a steel frame. Shut it fills
    the gap; open (past half, like the raycaster) it stands swung back into the shop."""
    w, h = C.WALK_DOOR_W, C.WALK_DOOR_H
    door, frame, glass = (150, 60, 44), (70, 70, 78), (150, 170, 180)
    out = [(cx - w / 2 - 0.1, cx - w / 2, yl - 0.2, yl + 0.2, 0.0, h, frame),
           (cx + w / 2, cx + w / 2 + 0.1, yl - 0.2, yl + 0.2, 0.0, h, frame)]
    if up < 0.5:
        out.append((cx - w / 2, cx + w / 2, yl - 0.08, yl + 0.08, 0.0, h, {"*": door, "+z": frame}))
        out.append((cx - w / 2 + 0.35, cx + w / 2 - 0.35, yl - 0.1, yl + 0.1, 1.55, 2.1, glass))
        out.append((cx - w / 2 + 0.12, cx + w / 2 - 0.12, yl - 0.11, yl + 0.11, 1.0, 1.1, (200, 200, 206)))   # push bar
    else:
        x = cx + w / 2 - 0.1
        out.append((x - 0.04, x + 0.04, yl - 0.2 - w, yl - 0.2, 0.0, h, door))
        out.append((x - 0.05, x + 0.05, yl - 0.2 - w + 0.3, yl - 0.2 - 0.3, 1.55, 2.1, glass))
    return out


def _gate_boxes_world(gx, gy):
    def fn(shut):
        if not shut:
            return []
        out = []
        for k in range(2):
            off = -C.GATE_LEN / 2 + (k + 0.5) * C.GATE_LEN / 2
            out += place(FA.gate_boxes(C.GATE_LEN / 2), gx + off, gy, math.pi / 2)
        return out
    return fn


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------
class World3D:
    def __init__(self):
        self.vertices = np.zeros((0, 6), dtype=np.float32)
        self.atlas = None
        self.dynamic = []
        self.bounds = (0.0,) * 6
        self.version = ""
        self.groups = {}
        self.lamps = []
        self.roofed = []
        self._atlas = None

    def vertex_count(self):
        return int(self.vertices.shape[0])

    def gl_vertices(self):
        """The same triangles in right-handed Y-up space: (x, z, y, u, v, shade). See the module doc."""
        v = self.vertices.copy()
        v[:, [1, 2]] = v[:, [2, 1]]
        return v

    def palette_uv(self, rgb):
        """The atlas (u, v) of a flat colour (the nearest one the atlas has). Cars, people and
        the dynamic boxes can all be meshed from this one texture."""
        a = self._atlas
        i = a.colour(rgb)
        x, y, w, h = a.regions["__pal__"]
        return ((x + (i % PAL_W) + 0.5) / a.size[0], (y + (i // PAL_W) + 0.5) / a.size[1])

    def mesh_boxes(self, boxes, shade_mul=1.0):
        """fpart-style boxes (WORLD coordinates) to (N, 6) vertices in the same layout as
        .vertices, in this world's atlas palette. For meshing .dynamic objects (and anything
        else made of boxes) the way the static world is meshed."""
        a = self._atlas
        m = _Mesh(a)
        m.boxes("props_free", boxes, skip_floor=True)
        v, _g = m.finalize(a.regions, a.size)
        if shade_mul != 1.0:
            v[:, 5] *= shade_mul
        return v


def _in_rect(x, y, r, pad=0.0):
    return r[0] - pad <= x <= r[0] + r[2] + pad and r[1] - pad <= y <= r[1] + r[3] + pad


def _wall_defs(cm):
    """(tx, ty) -> wall def key for every solid, non-tree tile. The same logic as
    fp.FPRenderer._build_walls: buildings keep one height and style, the shop and precinct
    brick carry their signs."""
    n = cm.n
    defs = {}
    for (tx, ty, tw, th, style) in cm.buildings:
        floors = 3 + (tx * 7 + ty * 13 + cm.seed) % 4
        for y in range(ty, ty + th):
            for x in range(tx, tx + tw):
                defs[(x, y)] = ("bld", style, floors, (x * 5 + y * 3 + cm.seed) % 3)
    ox, oy, b, _ = cm.garage_tiles
    mid = ox + b // 2
    pt = cm.precinct_tiles if cm.precinct_outer is not None else None
    for y in range(n):
        for x in range(n):
            if cm.tiles[y * n + x] != M.WALL:
                continue
            if pt is not None and pt[0] <= x < pt[0] + pt[2] and pt[1] <= y < pt[1] + pt[3]:
                door = pt[0] + pt[2] // 2
                sign = 1 if (y == pt[1] + pt[3] - 1 and abs(x - door) == 1) else 0
                defs[(x, y)] = ("precinct", sign)
                continue
            sign = x - (mid - 1) if (y == oy and mid - 1 <= x <= mid + 1) else -1
            if y == oy + b - 1 and ox < x < ox + b - 1:
                defs[(x, y)] = ("pier", x - (ox + 1) - 3)
                continue
            defs[(x, y)] = ("brick", sign)
    for i, fs in enumerate(getattr(cm, "fence_shops", ())):
        t = fs.get("tiles")
        if t is None:
            continue
        x0, y0, w, h = t
        for x in (x0 + 1, x0 + w - 2):
            defs[(x, y0 + h - 1)] = ("fsign", i + 1)
    return defs


def _plain(key, n):
    """Signs are one-sided: only the street face (outward normal +y) has the lettering."""
    if n == (0, 1):
        return key
    if key[0] in ("pier", "fsign"):
        return ("brick", -1)
    if key == ("precinct", 1):
        return ("precinct", 0)
    return key


def build_world(cmap, night=False, sc=1):
    """Build the whole static city for `cmap`. About a second; deterministic per (seed, night, sc).
    (v0.20) `sc` is the texel scale: the facades, brick, doors and the shop ceilings are painted at
    sc x PX_M texels a metre (fpart's own sc), so a 2x render shows 2x the detail, not 2x the blur.
    The geometry and every uv are the same at any sc; only the atlas grows."""
    cm = cmap
    n = cm.n
    font = PixelFont()
    atlas = _Atlas()
    mesh = _Mesh(atlas)
    # palette first, in a fixed order, so indices (and so the atlas) never depend on build order
    for rgb in list(P.values()) + CAR_COLORS + PLAYER_COLORS + SKINS + HAIRS + SHIRTS:
        atlas.colour(rgb)
    for g in range(0, 256, 8):
        atlas.colour((g, g, g))
    defs = _wall_defs(cm)

    def tex(key):
        if key not in atlas.items:
            surf = _wall_surface(key, night, font, sc)
            atlas.add(key, surf, surf.get_height() / (PX_M * sc))
        return key

    # ---- the roofed buildings: the home shop and the garages you can buy ----------------------
    roofed = [("home", cm.garage_rect)]
    for i, fs in enumerate(getattr(cm, "fence_shops", ())):
        if fs.get("rect") is not None:
            roofed.append((i, fs["rect"]))

    def roofed_at(x, y):
        for _k, (gx, gy, gw, gh) in roofed:
            if gx - T <= x <= gx + gw + T and gy - T <= y <= gy + gh + T:
                return True
        return False

    def solid(tx, ty):
        return cm.solid_tile(tx, ty)

    wall_top = shade(P["wall_l"], 0.7)

    # ---- walls: every exposed face of every solid tile ----------------------------------------
    for (tx, ty), key in sorted(defs.items()):
        kind = key[0]
        x0, y0 = tx * T, ty * T
        x1, y1 = x0 + T, y0 + T
        if kind == "bld":
            H = key[2] * FA.FLOOR_M
        elif kind == "precinct":
            H = 8.0
        else:
            H = FACADE_H
        cx, cy = x0 + T / 2, y0 + T / 2
        parapet = kind in ("brick", "pier", "fsign") and roofed_at(cx, cy)
        for nrm, (a, b) in (((0, 1), ((x0, y1), (x1, y1))), ((0, -1), ((x0, y0), (x1, y0))),
                            ((1, 0), ((x1, y0), (x1, y1))), ((-1, 0), ((x0, y0), (x0, y1)))):
            if solid(tx + nrm[0], ty + nrm[1]):
                continue
            k = tex(_plain(key, nrm))
            if parapet:
                mesh.vface("walls", a, b, 0.0, ROOF_H, nrm, k)
                mesh.vface("parapets", a, b, ROOF_H, H, nrm, k)
            else:
                mesh.vface("walls", a, b, 0.0, H, nrm, k)
        # the top: a coloured gravel tile per tile for buildings, plain coping for walls
        if kind == "bld":
            roof = ("roof", key[1])
            if roof not in atlas.items:
                atlas.add(roof, _roof_top_tile(key[1], night), 4.0)
            mesh.hface("tops", x0, x1, y0, y1, H, True, roof)
        else:
            mesh.cface("tops", ((x0, y0, H), (x1, y0, H), (x1, y1, H), (x0, y1, H)), (0.0, 0.0, 1.0), wall_top, 1.0)

    # ---- the edge of the world: a concrete wall round the map, facing in -----------------------
    m = n * T
    ek = tex(("concrete",))
    for i in range(n):
        a, b = i * T, (i + 1) * T
        mesh.vface("edge", (a, 0.0), (b, 0.0), 0.0, EDGE_H, (0, 1), ek)
        mesh.vface("edge", (a, m), (b, m), 0.0, EDGE_H, (0, -1), ek)
        mesh.vface("edge", (0.0, a), (0.0, b), 0.0, EDGE_H, (1, 0), ek)
        mesh.vface("edge", (m, a), (m, b), 0.0, EDGE_H, (-1, 0), ek)

    # ---- ceilings and flat roofs --------------------------------------------------------------
    gk = ("gravel",)
    atlas.add(gk, _gravel_tile(night), 4.0)
    out_roofed = []
    for key, (gx, gy, gw, gh) in roofed:
        ck = ("ceiling", key)
        atlas.add(ck, FA.roof_texture(gw, gh, CEIL_PPM * sc), gh)
        mesh.quad("ceilings", ((gx, gy, ROOF_H), (gx + gw, gy, ROOF_H), (gx + gw, gy + gh, ROOF_H), (gx, gy + gh, ROOF_H)),
                  ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)), ck, (0.0, 0.0, -1.0), CEIL_SHADE)
        for ty in range(int(round(gy / T)), int(round((gy + gh) / T))):
            for tx in range(int(round(gx / T)), int(round((gx + gw) / T))):
                mesh.hface("roofs", tx * T, tx * T + T, ty * T, ty * T + T, ROOF_H, True, gk)
        out_roofed.append({"key": key, "rect": (gx, gy, gw, gh), "ceiling_z": ROOF_H})

    # ---- the shop's front: five doors, two piers, a walking-door frame ------------------------
    gx, gy, gw, gh = cm.garage_rect
    yl = gy + gh                                                  # the door line
    brick_k = tex(("brick", -1))
    walk_k = tex(("walkdoor",))
    dcols = C.DOOR_COLS
    d = C.DOOR_T / 2
    wdw = C.WALK_DOOR_W
    for col in range(C.BLOCK_TILES - 2):
        if col not in dcols:
            continue
        xa = gx + col * T
        xb = xa + T
        cxm = (xa + xb) / 2
        if col == dcols[0]:                                       # the walking door
            gl, gr = cxm - wdw / 2, cxm + wdw / 2
            for (ja, jb) in ((xa, gl), (gr, xb)):                 # brick jambs, full height
                mesh.vface("walls", (ja, yl + d), (jb, yl + d), 0.0, ROOF_H, (0, 1), walk_k, anchor=(xa, yl + d))
                mesh.vface("parapets", (ja, yl + d), (jb, yl + d), ROOF_H, FACADE_H, (0, 1), walk_k, anchor=(xa, yl + d))
                mesh.vface("walls", (ja, yl - d), (jb, yl - d), 0.0, ROOF_H, (0, -1), brick_k, anchor=(xb, yl - d))
                mesh.vface("parapets", (ja, yl - d), (jb, yl - d), ROOF_H, FACADE_H, (0, -1), brick_k, anchor=(xb, yl - d))
                mesh.cface("tops", ((ja, yl - d, FACADE_H), (jb, yl - d, FACADE_H), (jb, yl + d, FACADE_H), (ja, yl + d, FACADE_H)),
                           (0.0, 0.0, 1.0), wall_top, 1.0)
            frame = (70, 70, 78)
            mesh.cface("walls", ((gl, yl - d, 0.0), (gl, yl + d, 0.0), (gl, yl + d, C.WALK_DOOR_H), (gl, yl - d, C.WALK_DOOR_H)),
                       (1.0, 0.0, 0.0), frame, FACE_SHADE["+x"])
            mesh.cface("walls", ((gr, yl - d, 0.0), (gr, yl + d, 0.0), (gr, yl + d, C.WALK_DOOR_H), (gr, yl - d, C.WALK_DOOR_H)),
                       (-1.0, 0.0, 0.0), frame, FACE_SHADE["-x"])
            # brick over the gap, on the door line
            mesh.vface("walls", (gl, yl + d), (gr, yl + d), C.WALK_DOOR_H, ROOF_H, (0, 1), walk_k, anchor=(xa, yl + d))
            mesh.vface("parapets", (gl, yl + d), (gr, yl + d), ROOF_H, FACADE_H, (0, 1), walk_k, anchor=(xa, yl + d))
            mesh.vface("walls", (gl, yl - d), (gr, yl - d), C.WALK_DOOR_H, ROOF_H, (0, -1), brick_k, anchor=(xb, yl - d))
            mesh.vface("parapets", (gl, yl - d), (gr, yl - d), ROOF_H, FACADE_H, (0, -1), brick_k, anchor=(xb, yl - d))
            mesh.cface("walls", ((gl, yl - d, C.WALK_DOOR_H), (gr, yl - d, C.WALK_DOOR_H), (gr, yl + d, C.WALK_DOOR_H),
                                 (gl, yl + d, C.WALK_DOOR_H)), (0.0, 0.0, -1.0), frame, FACE_SHADE["-z"])
            mesh.cface("tops", ((gl, yl - d, FACADE_H), (gr, yl - d, FACADE_H), (gr, yl + d, FACADE_H), (gl, yl + d, FACADE_H)),
                       (0.0, 0.0, 1.0), wall_top, 1.0)
            low = C.WALK_DOOR_H                                    # the porch slab in front of the door
        else:
            low = ROOF_H
        # the lintel slab over the 4 m of apron in front of this door (street edge back to the door line)
        ys, yn = yl + T, yl - d
        mesh.vface("walls", (xa, ys), (xb, ys), low, FACADE_H, (0, 1), brick_k, hz=FACADE_H)
        mesh.vface("parapets", (xa, yn), (xb, yn), max(low, ROOF_H), FACADE_H, (0, -1), brick_k, anchor=(xb, yn), hz=FACADE_H)
        for (xe, nx) in ((xa, -1), (xb, 1)):
            mesh.vface("walls", (xe, yn), (xe, ys), low, FACADE_H, (nx, 0), brick_k, uw=T + d, hz=FACADE_H)
        mesh.cface("walls", ((xa, yn, low), (xb, yn, low), (xb, ys, low), (xa, ys, low)), (0.0, 0.0, -1.0),
                   shade(P["wall_l"], 0.55), FACE_SHADE["-z"])
        mesh.cface("tops", ((xa, yn, FACADE_H), (xb, yn, FACADE_H), (xb, ys, FACADE_H), (xa, ys, FACADE_H)),
                   (0.0, 0.0, 1.0), wall_top, 1.0)

    # ---- the fence garages' fronts and the precinct doorway ----------------------------------
    for i, fs in enumerate(getattr(cm, "fence_shops", ())):
        t = fs.get("tiles")
        if t is None:
            continue
        x0, y0, w, h = t
        ya, yb = (y0 + h - 1) * T, (y0 + h) * T                   # the front row of the wall ring
        for tx in range(x0 + 2, x0 + w - 2):                      # the opening, tile by tile
            xa, xb = tx * T, tx * T + T
            mesh.vface("walls", (xa, yb), (xb, yb), ROOF_H, FACADE_H, (0, 1), brick_k, hz=FACADE_H)
            mesh.vface("parapets", (xa, ya), (xb, ya), ROOF_H, FACADE_H, (0, -1), brick_k, hz=FACADE_H)
            mesh.cface("walls", ((xa, ya, ROOF_H), (xb, ya, ROOF_H), (xb, yb, ROOF_H), (xa, yb, ROOF_H)), (0.0, 0.0, -1.0),
                       shade(P["wall_l"], 0.55), FACE_SHADE["-z"])
            mesh.cface("tops", ((xa, ya, FACADE_H), (xb, ya, FACADE_H), (xb, yb, FACADE_H), (xa, yb, FACADE_H)),
                       (0.0, 0.0, 1.0), wall_top, 1.0)
        for (xe, nx) in ((x0 + 2) * T, -1), ((x0 + w - 2) * T, 1):
            mesh.vface("walls", (xe, ya), (xe, yb), ROOF_H, FACADE_H, (nx, 0), brick_k, hz=FACADE_H)
    if cm.precinct_outer is not None:
        px0, py0, pw, ph = cm.precinct_tiles
        door = px0 + pw // 2
        xa, xb = door * T, door * T + T
        ya, yb = (py0 + ph - 1) * T, (py0 + ph) * T
        pk = tex(("precinct", 0))
        low = PRECINCT_LINTEL
        mesh.vface("walls", (xa, yb), (xb, yb), low, 8.0, (0, 1), pk, hz=8.0)
        mesh.vface("walls", (xa, ya), (xb, ya), low, 8.0, (0, -1), pk, hz=8.0)
        for (xe, nx) in ((xa, -1), (xb, 1)):
            mesh.vface("walls", (xe, ya), (xe, yb), low, 8.0, (nx, 0), pk, hz=8.0)
        mesh.cface("walls", ((xa, ya, low), (xb, ya, low), (xb, yb, low), (xa, yb, low)), (0.0, 0.0, -1.0),
                   shade(P["wall_l"], 0.55), FACE_SHADE["-z"])
        mesh.cface("tops", ((xa, ya, 8.0), (xb, ya, 8.0), (xb, yb, 8.0), (xa, yb, 8.0)), (0.0, 0.0, 1.0), wall_top, 1.0)

    # ---- trees ---------------------------------------------------------------------------------
    atlas.add("leaf", _leaf_tile(night), 2.0)
    for ty in range(n):
        for tx in range(n):
            if cm.tiles[ty * n + tx] != M.TREE:
                continue
            cx, cy = (tx + 0.5) * T, (ty + 0.5) * T
            var = (tx * 3 + ty) % 4
            jx, jy = ((-0.2, 0.15), (0.15, 0.2), (0.2, -0.15), (-0.15, -0.2))[var]
            s = TREE_SKIRT / 2
            mesh.box("trees", cx - s, cx + s, cy - s, cy + s, 0.0, 2.6, "leaf", skip=("-z",))
            s2 = 1.4
            mesh.box("trees", cx + jx - s2, cx + jx + s2, cy + jy - s2, cy + jy + s2, 2.6, 4.4, "leaf", skip=("-z",))
            s3 = 0.8 + 0.1 * (var % 2)
            mesh.box("trees", cx - jx - s3, cx - jx + s3, cy - jy - s3, cy - jy + s3, 4.4, 5.5 + 0.2 * var, "leaf", skip=("-z",))

    # ---- street lamps and camera poles ---------------------------------------------------------
    lamp_col = P["light"] if night else (200, 196, 170)
    lamps = []
    for (lx, ly) in cm.lamps:
        tx, ty = int(lx // T), int(ly // T)
        dx, dy = lx - (tx + 0.5) * T, ly - (ty + 0.5) * T          # which way the road is
        if abs(dx) >= abs(dy):
            sx, sy = (1 if dx > 0 else -1), 0
        else:
            sx, sy = 0, (1 if dy > 0 else -1)
        h = 0.08
        mesh.box("lamps", lx - h, lx + h, ly - h, ly + h, 0.0, LAMP_H, P["metal"], skip=("-z", "+z"))
        hx, hy = lx + sx * 0.45, ly + sy * 0.45
        ex, ey = (0.55, 0.16) if sx else (0.16, 0.55)
        mesh.box("lamps", hx - ex, hx + ex, hy - ey, hy + ey, LAMP_H - 0.15, LAMP_H, {"*": P["metal_l"], "-z": lamp_col},
                 skip=())
        lamps.append((hx, hy, LAMP_H - 0.2))
    for (cx, cy) in cm.cameras:
        h = 0.07
        mesh.box("cameras", cx - h, cx + h, cy - h, cy + h, 0.0, CAM_POLE_H, P["metal"], skip=("-z", "+z"))
        mesh.box("cameras", cx - 0.28, cx + 0.28, cy - 0.16, cy + 0.16, CAM_POLE_H, CAM_POLE_H + 0.26, {"*": P["ink"], "+y": P["metal_l"]})
        mesh.box("cameras", cx + 0.16, cx + 0.26, cy + 0.16, cy + 0.2, CAM_POLE_H + 0.1, CAM_POLE_H + 0.18, P["red"], skip=())

    # ---- props ---------------------------------------------------------------------------------
    gap = C.COUNTER_GAP
    for rect, is_sell in ((cm.sell_bench, True), (cm.tune_bench, False)):
        bx, by, bw, bh = rect
        mesh.boxes("props_solid", place(FA.bench_boxes(is_sell, bw, bh), bx + bw / 2, by + bh / 2, math.pi / 2))
        wood = P["wood_d"]
        for xe in (bx, bx + bw - 0.12):                             # end panels round the staff's pen
            mesh.box("props_solid", xe, xe + 0.12, gy, by + bh, 0.0, 1.0, wood, skip=("-z",))
    for fs in getattr(cm, "fence_shops", ()):
        if fs.get("bench") is not None:
            bx, by, bw, bh = fs["bench"]
            mesh.boxes("props_solid", place(FA.bench_boxes(False, bh, bw), bx + bw / 2, by + bh / 2, math.pi))
            fx, fy, fw, fh = fs["rect"]
            mesh.box("props_solid", bx + bw, fx + fw, by, by + bh, 0.0, 0.95, P["metal_l"], skip=("-z",))
    for (bx, by, bw, bh) in getattr(cm, "cell_bars", ()):
        along_x = bw > bh
        length = bw if along_x else bh
        k = max(1, int(math.ceil(length / 2.0)))
        seg = length / k
        for j in range(k):
            if along_x:
                mesh.boxes("props_solid", place(FA.bars_boxes(round(seg, 2)), bx + (j + 0.5) * seg, by + bh / 2, math.pi / 2))
            else:
                mesh.boxes("props_solid", place(FA.bars_boxes(round(seg, 2)), bx + bw / 2, by + (j + 0.5) * seg, 0.0))
    if getattr(cm, "bail_desk", None) is not None:
        bx, by, bw, bh = cm.bail_desk
        mesh.boxes("props_solid", place(FA.desk_boxes(bw, bh), bx + bw / 2, by + bh / 2, 0.0))
    rec = getattr(cm, "records", None)
    if rec is not None:
        mesh.boxes("props_solid", place(FA.records_desk_boxes(), rec[0], rec[1], math.pi / 2))
        atlas.add("records_board", _records_surface(font), 0.9)
        bxm, bym = rec[0] - 2.0, rec[1] + 0.1
        mesh.box("props_free", bxm - 0.05, bxm + 0.05, bym - 0.05, bym + 0.05, 0.0, 1.3, P["metal"], skip=("-z",))
        mesh.box("props_free", bxm - 0.95, bxm + 0.95, bym - 0.06, bym + 0.06, 1.2, 2.15, P["ink"])
        for (yy, nrm) in ((bym + 0.065, (0, 1)), (bym - 0.065, (0, -1))):
            mesh.vface("props_free", (bxm - 0.9, yy), (bxm + 0.9, yy), 1.25, 2.1, nrm, "records_board", hz=0.85, zb=1.25,
                       anchor=(bxm - 0.9, yy) if nrm[1] > 0 else (bxm + 0.9, yy), uw=1.8)
    for (x, y, item) in getattr(cm, "market", ()):
        mesh.boxes("props_free", place(FA.crate_boxes(item), x, y, 0.0))
    for (x, y, ang) in getattr(cm, "ramps", ()):
        mesh.boxes("props_free", place(FA.ramp_boxes(), x, y, ang))

    # ---- the dynamic things --------------------------------------------------------------------
    dyn = []
    for i, (_i, dx_, dy_) in enumerate(C.door_specs(cm.garage_rect)):
        if i == 0:
            rect = (dx_ - wdw / 2, dy_ - d, wdw, C.DOOR_T)
            dyn.append(Dynamic(C.DOOR_ID + i, "walkdoor", (dx_, dy_), lambda up, x=dx_, y=dy_: _walk_door_boxes(x, y, up),
                               1.0, rect=rect))
        else:
            rect = (dx_ - C.DOOR_W / 2, dy_ - d, C.DOOR_W, C.DOOR_T)
            dyn.append(Dynamic(C.DOOR_ID + i, "door", (dx_, dy_), lambda up, x=dx_, y=dy_: _door_boxes(x, y, up),
                               1.0, rect=rect, bay=i - 1))
    if cm.gate is not None:
        gx_, gy_, _ga = cm.gate
        dyn.append(Dynamic(C.GATE_ID, "gate", (gx_, gy_), _gate_boxes_world(gx_, gy_), 1.0,
                           rect=(gx_ - C.GATE_LEN / 2, gy_ - C.GATE_WID / 2, C.GATE_LEN, C.GATE_WID)))
    for k, (x, y, a) in enumerate(getattr(cm, "cell_doors", ())):
        L = C.CELL_DOOR_W

        def cell(life, x=x, y=y, L=L):
            if life > 0:
                return place(FA.bars_boxes(L, True, True, round(1.0 - life, 1)), x, y, math.pi / 2)
            return place(FA.bars_boxes(L, True, False), x - L / 2, y + L / 2, 0.0)
        dyn.append(Dynamic(C.CELL_ID_BASE + k, "celldoor", (x, y), cell, 1.0,
                           rect=(x - L / 2, y - C.CELL_BAR_T / 2, L, C.CELL_BAR_T)))
    for i, fs in enumerate(getattr(cm, "fence_shops", ())):
        r = C.JUNK_SIZE / 2
        for k, (x, y) in enumerate(fs["junk"][:C.JUNK_PER_SHOP]):
            def junk(present, x=x, y=y, k=k):
                return place(FA.junk_boxes(k), x, y, k * 0.8) if present else []
            dyn.append(Dynamic(C.JUNK_ID_BASE + i * C.JUNK_PER_SHOP + k, "junk", (x, y), junk, True,
                               rect=(x - r, y - r, 2 * r, 2 * r), shop=i + 1))
    hd = getattr(cm, "door_handle", None)
    if hd is not None:
        dyn.append(Dynamic(None, "lever", (hd[0], hd[1]),
                           lambda down, hd=hd: place(FA.door_handle_boxes(bool(down)), hd[0], hd[1], hd[2]), False))
    for i, fs in enumerate(getattr(cm, "fence_shops", ())):
        idx = i + 1
        for st in (0, 1, 2):
            atlas.add(("sale", idx, st), _sale_surface(font, idx, st), 0.85)
        sx, sy = fs["sign"]

        def sale_boxes(state, sx=sx, sy=sy):
            board = (40, 110, 60) if state else (230, 226, 214)
            return [(sx - 0.05, sx + 0.05, sy - 0.05, sy + 0.05, 0.0, 1.3, P["metal"]),
                    (sx - 0.95, sx + 0.95, sy - 0.06, sy + 0.06, 1.2, 2.15, {"*": P["ink"], "+z": board})]

        def sale_quads(state, sx=sx, sy=sy, idx=idx):
            m2 = _Mesh(atlas)
            key = ("sale", idx, int(state))
            for (yy, nrm) in ((sy + 0.065, (0, 1)), (sy - 0.065, (0, -1))):
                m2.vface("props_solid", (sx - 0.9, yy), (sx + 0.9, yy), 1.25, 2.1, nrm, key, hz=0.85, zb=1.25,
                         anchor=(sx - 0.9, yy) if nrm[1] > 0 else (sx + 0.9, yy), uw=1.8)
            v, _g = m2.finalize(atlas.regions, atlas.size)
            return v
        dyn.append(Dynamic(None, "sale_board", (sx, sy), sale_boxes, 0, quads_fn=sale_quads, shop=idx))
        for (x, y, item) in fs["market"]:
            dyn.append(Dynamic(None, "crate", (x, y), lambda vis, x=x, y=y, item=item:
                               place(FA.crate_boxes(item), x, y, 0.0) if vis else [], False, shop=idx, item=item))
    # every colour the dynamic boxes can show goes in the palette now, while it can still grow
    for obj in dyn:
        states = {"door": (0.0, 0.5), "walkdoor": (0.0, 1.0), "gate": (1,), "celldoor": (1.0, 0.0), "junk": (True,),
                  "lever": (True, False), "sale_board": (0, 1, 2), "crate": (True,)}[obj.kind]
        for st in states:
            for (_a, _b, _c, _d, _e, _f, col) in obj.boxes_for(st):
                for c in (col.values() if isinstance(col, dict) else (col,)):
                    atlas.colour(c)

    # ---- pack and finish -----------------------------------------------------------------------
    surf = atlas.pack()
    vertices, groups = mesh.finalize(atlas.regions, atlas.size)
    w = World3D()
    w.vertices = vertices
    w.atlas = surf
    w.dynamic = dyn
    w.groups = groups
    w.lamps = lamps
    w.roofed = out_roofed
    w._atlas = atlas
    if len(vertices):
        lo, hi = vertices[:, :3].min(axis=0), vertices[:, :3].max(axis=0)
        w.bounds = (float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2]))
    w.version = "world3d-%d:%s:%s:%dx" % (FORMAT, cm.seed, "night" if night else "day", sc)
    return w

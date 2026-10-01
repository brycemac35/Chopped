"""
gl3d.py -- (v0.20) the first-person view in real 3D, on the GPU, still looking like Doom.

Bryce: "have the vehicles render in more close approximation to 3d. lets transition to a 3d game,
but use the stylized look of doom." And the bug that made it urgent: billboards picked a sprite
angle per car and drew it as a flat card, so walking up to a car made it spin ("the textures
rotate severely when the player's distance becomes too close") and a card's rectangle never
matched the car's real footprint ("a clear passageway looks not clear or vice versa").

So here every car, person, dog and prop is its REAL box model (the same fpart.*_boxes the
sprites were painted from) as a triangle mesh, drawn at its real position and heading. The
walls are world3d's mesh, the street is the live top-down map on a ground quad, the sky is the
same panorama as before. What makes it Doom and not a tech demo:
  - it renders into a LOW-RES framebuffer (render scale k x 640x328) blown up nearest-neighbour;
  - flat colours, one light, every box face outlined in a darker shade (like the sprites were);
  - Doom's light diminishing: things get darker in bands with distance and at night;
  - colours snapped to GL_COLOR_LEVELS steps a channel, for a palette-ish crunch;
  - NEAREST sampling everywhere. No smoothing, no MSAA, nothing a 1993 PC couldn't dream of.

WHAT is drawn is still decided by fp.FPRenderer (GLRenderer inherits it): _collect lists the
same entities the classic view draws, the particles/skids/pigeons/hats/trunk lids all run the
same code, and only the HOW changes -- _car_sprite and friends return mesh references instead
of sprites. Labels, markers, tracers and explosions are 2D, drawn on a see-through overlay the
size of the view (the hands and the dashboard go on it too, see game._draw_fp).

Client-only, like all rendering: nothing here touches the sim or the wire. If moderngl or an
OpenGL 3.3 context isn't there (the tests' dummy video driver, an old laptop), game.py stays on
the classic raycaster. The pure parts (boxes_to_mesh, the matrices) need no GL and are tested.
"""

import math
import time
from collections import OrderedDict

import numpy as np
import pygame

from . import config as C
from . import fp as FP
from . import fpart as FA
from . import sim as S
from . import vehicles as V
from . import mapgen as M
try:                                   # (v0.20) A2's textured city; until it lands, the grey stub below
    from . import world3d as W3
except ImportError:
    W3 = None
from .art import P, shade

try:                                   # optional: no moderngl, no 3D (the classic view still works)
    import moderngl
except Exception:                      # pragma: no cover - depends on the install
    moderngl = None

TWO_PI = 2 * math.pi
T = C.TILE_M

# ---------------------------------------------------------------------------- pure parts (no GL)
# Per vertex: position (3), normal (3), colour 0..1 (3), edge coords on the face in metres (2),
# the face's size in metres (2). The fragment shader darkens within GL_OUTLINE_PX of a face's
# edge: the same dark outline render_boxes put round every polygon, for no extra geometry.
MESH_STRIDE = 13
# (normal, key, the face's 4 corners as indices into (x0|x1, y0|y1, z0|z1), which two axes span it)
_FACE_SPEC = (
    ((1, 0, 0), "+x", ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), (1, 2)),
    ((-1, 0, 0), "-x", ((0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)), (1, 2)),
    ((0, 1, 0), "+y", ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)), (0, 2)),
    ((0, -1, 0), "-y", ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), (0, 2)),
    ((0, 0, 1), "+z", ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), (0, 1)),
    ((0, 0, -1), "-z", ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), (0, 1)),
)
_TRI = (0, 1, 2, 0, 2, 3)


def face_colour(col, key):
    """A box's colour for one face: a plain colour, or {face: colour} with "*" as the default.
    None means "no face here" (an open bed, a missing door's hole is a colour, not None)."""
    if isinstance(col, dict):
        return col.get(key, col.get("*"))
    return col


def boxes_to_mesh(boxes):
    """Axis-aligned boxes (x0, x1, y0, y1, z0, z1, colour or {face: colour}) in model space
    (x forward, y right, z up, metres) -> float32 array (n_verts, MESH_STRIDE), two triangles a
    face, faces with no colour skipped. Done once per look (see GLRenderer._mesh)."""
    out = []
    for box in boxes:
        x0, x1, y0, y1, z0, z1, col = box
        lo, hi = (x0, y0, z0), (x1, y1, z1)
        size = (x1 - x0, y1 - y0, z1 - z0)
        for n, key, corners, (a0, a1) in _FACE_SPEC:
            c = face_colour(col, key)
            if c is None:
                continue
            r, g, b = c[0] / 255.0, c[1] / 255.0, c[2] / 255.0
            pts = [tuple(hi[i] if k[i] else lo[i] for i in range(3)) for k in corners]
            for vi in _TRI:
                k = corners[vi]
                p = pts[vi]
                out.append((p[0], p[1], p[2], n[0], n[1], n[2], r, g, b,
                            size[a0] * k[a0], size[a1] * k[a1], size[a0], size[a1]))
    if not out:
        return np.zeros((0, MESH_STRIDE), dtype=np.float32)
    return np.asarray(out, dtype=np.float32)


def box_extent(boxes):
    """(x0, x1, y0, y1) the boxes cover in plan (metres, model space)."""
    return (min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes), max(b[3] for b in boxes))


def fit_boxes(boxes, ext, hl, hw):
    """Squeeze boxes in plan so the extent `ext` lands exactly on the collision box (+-hl, +-hw).
    Bryce: "a clear passageway looks not clear". The car models overhang their physics boxes by
    ~25 cm at each bumper, so a gap between two parked cars looked half a metre narrower than it
    was. Now what you see is what you hit. (A uniform ~10% squash per model; heights untouched.)"""
    x0, x1, y0, y1 = ext
    sx, cx = 2.0 * hl / max(1e-6, x1 - x0), (x0 + x1) / 2.0
    sy, cy = 2.0 * hw / max(1e-6, y1 - y0), (y0 + y1) / 2.0
    return [((b[0] - cx) * sx, (b[1] - cx) * sx, (b[2] - cy) * sy, (b[3] - cy) * sy) + tuple(b[4:])
            for b in boxes]


# world3d's per-face shading (its FACE_SHADE): divided back out of each world face, so the city is
# lit by the cars' light model instead (see world_edges)
WORLD_FACE_SHADE = {"+z": 1.0, "+x": 0.94, "-x": 0.86, "+y": 0.90, "-y": 0.80, "-z": 0.68}
WORLD_STRIDE = 14


def world_edges(verts, face_shade=None):
    """(v0.20, Bryce: "make the background visuals like the cars") world3d's (N, 6) triangles
    (x y z u v shade, two triangles a quad, in its 0-1-2 0-2-3 / 0-2-1 0-3-2 order) -> (N, 14):
    x y z u v shade, outward normal (3), edge coords on the quad in metres (2), the quad's size
    (2), and an outline mask (1). The city then goes through the same shading as the box models:
      - lighting: the face's shade with world3d's per-direction factor divided out, so the world
        light (GL_LIGHT, 0.6 + 0.4 n.L) does the shading for walls exactly as for car panels;
      - outlines: the cars outline every box face; a wall is many 4 m quads, and outlining each
        would draw a grid on every facade, so an edge is outlined only when no other quad facing
        the same way shares it -- building corners, roof lines, the foot of every wall, where a
        lower block meets a taller one. Mask bits: 1 = the s axis's first edge (t = 0),
        2 = s far side (s = size), 4 = t far side (t = size), 8 = s = 0."""
    fs = WORLD_FACE_SHADE if face_shade is None else face_shade
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 6)
    nq = len(v) // 6
    out = np.zeros((nq * 6, WORLD_STRIDE), dtype=np.float32)
    if not nq:
        return out
    q = v[:nq * 6].reshape(nq, 6, 6).astype(np.float64)
    P = q[:, :, :3]
    a_order = np.all(np.abs(P[:, 2] - P[:, 4]) < 1e-6, axis=1)[:, None]     # 0 1 2 0 2 3 (else 0 2 1 0 3 2)
    p0 = P[:, 0]
    p1 = np.where(a_order, P[:, 1], P[:, 2])
    p2 = np.where(a_order, P[:, 2], P[:, 1])
    p3 = np.where(a_order, P[:, 5], P[:, 4])
    e1, e3 = p1 - p0, p3 - p0
    l1 = np.maximum(np.linalg.norm(e1, axis=1), 1e-9)
    l3 = np.maximum(np.linalg.norm(e3, axis=1), 1e-9)
    d = P - p0[:, None, :]
    s_ = (d * (e1 / l1[:, None])[:, None, :]).sum(axis=2)
    t_ = (d * (e3 / l3[:, None])[:, None, :]).sum(axis=2)
    nrm = -np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])                     # (world3d winds them inward)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)[:, None]
    ax = np.abs(nrm).argmax(axis=1)
    sign = np.take_along_axis(nrm, ax[:, None], axis=1)[:, 0] > 0
    names = np.array([["-x", "+x"], ["-y", "+y"], ["-z", "+z"]])
    base = np.vectorize(lambda k: fs.get(k, 1.0))(names[ax, sign.astype(int)])
    # edges: (p0 p1) (p1 p2) (p2 p3) (p3 p0). An axis-aligned segment is fixed by its endpoints'
    # sum and absolute difference; add the normal and it's a key two coplanar neighbours share.
    corners = (p0, p1, p2, p3)
    ni = np.round(nrm * 100).astype(np.int64)
    keys = []
    for k in range(4):
        A, B = corners[k], corners[(k + 1) % 4]
        ka = np.round((A + B) * 100).astype(np.int64)
        kd = np.round(np.abs(A - B) * 100).astype(np.int64)
        keys.append(np.concatenate([ka, kd, ni], axis=1))
    allk = np.concatenate(keys)                                          # (4 nq, 9), edge-major
    _u, inv, cnt = np.unique(allk, axis=0, return_inverse=True, return_counts=True)
    lone = (cnt[inv.reshape(-1)] == 1).reshape(4, nq)
    mask = lone[0] * 1 + lone[1] * 2 + lone[2] * 4 + lone[3] * 8
    o = out.reshape(nq, 6, WORLD_STRIDE)
    o[:, :, 0:5] = q[:, :, 0:5]
    o[:, :, 5] = q[:, :, 5] / base[:, None]
    o[:, :, 6:9] = nrm[:, None, :]
    o[:, :, 9] = s_
    o[:, :, 10] = t_
    o[:, :, 11] = l1[:, None]
    o[:, :, 12] = l3[:, None]
    o[:, :, 13] = mask[:, None]
    return out


def mesh_top(arr):
    """Highest z in a mesh (metres above its origin): where its label goes."""
    return float(arr[:, 2].max()) if len(arr) else 0.0


def view_proj(cx, cy, yaw, eye, fov, vw, vh, hor, near=None, far=None):
    """The camera as one 4x4 (row-major numpy; transpose for GL). Built to match fp's projection
    exactly, so 2D labels (drawn with fp's maths) land on the 3D things they belong to:
        screen x = vw/2 + lat / depth * D,   screen y = hor + (eye - z) * D / depth,
        D = (vw/2) / tan(fov/2)
    `hor` is the horizon row: pitch shears it up and down (Build-engine look-up, no tilt), so
    walls stay vertical whatever you're looking at -- that's the Doom feel, and it matches fp."""
    near = C.GL_NEAR if near is None else near
    far = C.GL_FAR if far is None else far
    ca, sa = math.cos(yaw), math.sin(yaw)
    tanh = math.tan(fov / 2)
    view = np.array([[-sa, ca, 0.0, -(-sa * cx + ca * cy)],      # x_eye: right ("lat")
                     [0.0, 0.0, 1.0, -eye],                      # y_eye: up
                     [-ca, -sa, 0.0, ca * cx + sa * cy],         # z_eye: -forward ("depth")
                     [0.0, 0.0, 0.0, 1.0]])
    o = (vh / 2.0 - hor) / (vh / 2.0)
    proj = np.array([[1.0 / tanh, 0.0, 0.0, 0.0],
                     [0.0, vw / (vh * tanh), -o, 0.0],
                     [0.0, 0.0, -(far + near) / (far - near), -2.0 * far * near / (far - near)],
                     [0.0, 0.0, -1.0, 0.0]])
    return proj @ view


def project(m, x, y, z, vw, vh):
    """World point -> (screen x, screen y, depth) with view_proj's matrix (tests use it)."""
    c = m @ np.array([x, y, z, 1.0])
    w = c[3]
    return (c[0] / w + 1.0) * vw / 2.0, (1.0 - c[1] / w) * vh / 2.0, w


def gl_available():
    """Can we even try? (moderngl installed and a video driver that might do OpenGL.)"""
    if moderngl is None:
        return False
    try:
        drv = pygame.display.get_driver()
    except pygame.error:
        drv = None
    import os
    return (drv or os.environ.get("SDL_VIDEODRIVER", "")).lower() not in ("dummy", "offscreen")


# ---------------------------------------------------------------------------- the stub city
# Until chopped/world3d.py (feat/world3d) is here: plain boxes extruded from the solid tiles, with
# exactly world3d's contract -- build(cmap, night) -> object with .vertices (float32, x y z u v
# shade per vertex, sim metres, triangles), .atlas (RGBA Surface, NEAREST), .dynamic (objects with
# .id and .boxes(open_t) -> world-space boxes). The street isn't in it: gl3d draws that itself.


# the stub's whole "atlas": one texel per colour, picked by uv. (A2's has real facades.)
STUB_COLS = [(150, 146, 140),      # 0 building concrete
             (150, 80, 62),        # 1 brick (the shop, the precinct)
             (96, 92, 100),        # 2 roof / ceiling underside
             (120, 118, 112)]      # 3 building variant


def _uv(i):
    return ((i + 0.5) / len(STUB_COLS), 0.5)


class StubDoor:
    """A roller door (or the walking door): `open_t` 0 shut .. 1 all the way up."""

    kind = "door"
    default_state = 1.0
    info = {}

    def __init__(self, did, x, y, w, h):
        self.id, self.x, self.y, self.w, self.h = did, x, y, w, h
        self.pos = (x, y)

    def boxes_for(self, state):
        return self.boxes(state)

    def boxes(self, open_t):
        lo = max(0.0, min(1.0, open_t)) * self.h          # rolls up into its housing
        if self.h - lo < 0.02:
            return []
        hw, ht = self.w / 2, C.DOOR_T / 2
        return [(self.x - hw, self.x + hw, self.y - ht, self.y + ht, lo, self.h, (170, 168, 160))]


class StubWorld3D:
    def __init__(self, vertices, atlas, dynamic):
        self.vertices = vertices
        self.atlas = atlas
        self.dynamic = dynamic


def _quad(out, a, b, c, d, uv, shade):
    u, v = uv
    for p in (a, b, c, a, c, d):
        out.extend((p[0], p[1], p[2], u, v, shade))


def _box(out, x0, x1, y0, y1, z0, z1, uv, sides=(True, True, True, True), top=True, bottom=False):
    """Sides (-x, +x, -y, +y) and caps of a box; shade is Doom's 'one side's darker' trick."""
    if sides[0]:
        _quad(out, (x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), uv, 0.8)
    if sides[1]:
        _quad(out, (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), uv, 0.8)
    if sides[2]:
        _quad(out, (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), uv, 1.0)
    if sides[3]:
        _quad(out, (x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), uv, 1.0)
    if top:
        _quad(out, (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), uv, 0.9)
    if bottom:
        _quad(out, (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), uv, 0.6)


def _stub_tile_heights(cmap):
    """Height (m) of every wall-ish tile, 0 for open ground (trees are billboards in gl3d)."""
    n = cmap.n
    h = [0.0] * (n * n)
    for (tx, ty, tw, th, _style) in cmap.buildings:
        floors = 3 + (tx * 7 + ty * 13 + cmap.seed) % 4          # (fp._build_walls' heights)
        for y in range(ty, ty + th):
            for x in range(tx, tx + tw):
                h[y * n + x] = floors * FA.FLOOR_M
    for i, t in enumerate(cmap.tiles):
        if t == M.WALL and not h[i]:
            h[i] = C.SHOP_FACADE_H
    return h


def stub_build_world(cmap, night=False):
    n = cmap.n
    hts = _stub_tile_heights(cmap)
    out = []
    bld_tiles = set()
    for (tx, ty, tw, th, _s) in cmap.buildings:
        bld_tiles.update((x, y) for y in range(ty, ty + th) for x in range(tx, tx + tw))

    def H(x, y):
        return hts[y * n + x] if 0 <= x < n and 0 <= y < n else 0.0

    for y in range(n):
        for x in range(n):
            h = hts[y * n + x]
            if not h:
                continue
            uv = _uv(0 if (x, y) in bld_tiles and (x + y) % 2 else 3 if (x, y) in bld_tiles else 1)
            # only faces that something shorter is next to (a city is mostly hidden walls)
            sides = (H(x - 1, y) < h, H(x + 1, y) < h, H(x, y - 1) < h, H(x, y + 1) < h)
            _box(out, x * T, (x + 1) * T, y * T, (y + 1) * T, 0.0, h, uv, sides)
    # the brick bits that aren't tiles: the walking door's jambs, lintels over every door
    for (rx, ry, rw, rh) in cmap.static_rects:
        if abs(rh - C.DOOR_T) < 1e-6:
            _box(out, rx, rx + rw, ry, ry + rh, 0.0, C.SHOP_FACADE_H, _uv(1))
    dyn = []
    for (i, x, y) in C.door_specs(cmap.garage_rect):
        w = C.WALK_DOOR_W if i == 0 else C.DOOR_W
        top = C.WALK_DOOR_H if i == 0 else C.ROOF_H
        _box(out, x - C.DOOR_W / 2, x + C.DOOR_W / 2, y - C.DOOR_T / 2, y + C.DOOR_T / 2, top, C.SHOP_FACADE_H,
             _uv(1), bottom=True)
        dyn.append(StubDoor(C.DOOR_ID + i, x, y, w, top))
    # roofs: a slab at ROOF_H over every covered floor, seen from under it as a ceiling
    roofs = [cmap.garage_rect] + [fs["rect"] for fs in getattr(cmap, "fence_shops", ()) if fs.get("rect")]
    for (gx, gy, gw, gh) in roofs:
        _box(out, gx, gx + gw, gy, gy + gh, C.ROOF_H, C.ROOF_H + 0.3, _uv(2), bottom=True)
    atlas = pygame.Surface((len(STUB_COLS), 1), pygame.SRCALPHA)
    for i, c in enumerate(STUB_COLS):
        atlas.set_at((i, 0), c + (255,))
    return StubWorld3D(np.asarray(out, dtype=np.float32), atlas, dyn)


def build_world(cmap, night=False, sc=1):
    """world3d's city (A2's: textured facades, trees, counters, crates...), or -- if it isn't
    there or it throws -- the grey stub, so a broken city build never costs you the game.
    `sc` is the texel scale (see GLRenderer._tex_scale). Returns (world, real?)."""
    if W3 is not None:
        try:
            return W3.build_world(cmap, night=night, sc=sc), True
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("WORLD3D: build failed (%s: %s), drawing the grey stub city" % (e.__class__.__name__, e))
    return stub_build_world(cmap, night), False


# ---------------------------------------------------------------------------- shaders
_LIGHT_GLSL = """
uniform float u_dark;        // 0 day .. 1 midnight
uniform float u_levels;      // colour steps per channel (the palette crunch)
// Doom's light diminishing, the same numbers as the raycaster's walls (fp._walls / fpart.SHADES):
// a level per 11 m and per fifth of the night, each 6.8% darker, never below 12%.
float lightf(float depth, float side) {
    float lv = floor(u_dark * 5.0) + floor(depth / 11.0) + side;
    return max(0.12, 1.0 - min(lv, 13.0) * 0.068);
}
vec3 crunch(vec3 c) { return floor(clamp(c, 0.0, 1.0) * u_levels + 0.5) / u_levels; }
"""

BOX_VS = """
#version 330
uniform mat4 u_vp;
uniform vec3 u_light;
in vec3 in_pos; in vec3 in_nrm; in vec3 in_col; in vec2 in_edge; in vec2 in_size;
in vec4 in_inst;                       // per instance: x, y, z, heading
out vec3 v_col; out vec2 v_edge; flat out vec2 v_size; out float v_depth;
void main() {
    float c = cos(in_inst.w), s = sin(in_inst.w);
    vec3 p = vec3(in_inst.x + in_pos.x * c - in_pos.y * s, in_inst.y + in_pos.x * s + in_pos.y * c,
                  in_inst.z + in_pos.z);
    vec3 n = vec3(in_nrm.x * c - in_nrm.y * s, in_nrm.x * s + in_nrm.y * c, in_nrm.z);
    v_col = in_col * (0.6 + 0.4 * max(0.0, dot(n, u_light)));   // render_boxes' flat shading
    v_edge = in_edge; v_size = in_size;
    gl_Position = u_vp * vec4(p, 1.0);
    v_depth = gl_Position.w;
}
"""
BOX_FS = """
#version 330
uniform float u_outline;     // px
""" + _LIGHT_GLSL + """
in vec3 v_col; in vec2 v_edge; flat in vec2 v_size; in float v_depth;
out vec4 f_col;
void main() {
    vec2 fw = max(fwidth(v_edge), vec2(1e-5));
    vec2 px = min(v_edge, v_size - v_edge) / fw;          // px to the nearest edge, each way
    float face = min(v_size.x / fw.x, v_size.y / fw.y);  // how many px the face is across
    vec3 c = v_col;
    if (min(px.x, px.y) < min(u_outline, face * 0.2)) c *= 0.6;   // (tiny far faces aren't all edge)
    f_col = vec4(crunch(c * lightf(v_depth, 0.0)), 1.0);
}
"""

WORLD_VS = """
#version 330
uniform mat4 u_vp;
uniform vec3 u_light;
in vec3 in_pos; in vec2 in_uv; in float in_shade; in vec3 in_nrm; in vec2 in_edge; in vec2 in_size; in float in_mask;
out vec2 v_uv; out float v_shade; out float v_depth; out vec2 v_edge; flat out vec2 v_size; flat out float v_mask;
void main() {
    v_uv = in_uv;
    v_shade = in_shade * (0.6 + 0.4 * max(0.0, dot(in_nrm, u_light)));   // the cars' light (BOX_VS)
    v_edge = in_edge; v_size = in_size; v_mask = in_mask;
    gl_Position = u_vp * vec4(in_pos, 1.0);
    v_depth = gl_Position.w;
}
"""
WORLD_FS = """
#version 330
uniform sampler2D u_tex;
uniform float u_outline;     // px, the same as the cars'
""" + _LIGHT_GLSL + """
in vec2 v_uv; in float v_shade; in float v_depth; in vec2 v_edge; flat in vec2 v_size; flat in float v_mask;
out vec4 f_col;
void main() {
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.5) discard;
    vec3 c = t.rgb * v_shade;
    int m = int(v_mask + 0.5);
    if (m != 0) {
        vec2 fw = max(fwidth(v_edge), vec2(1e-5));
        float w = min(u_outline, min(v_size.x / fw.x, v_size.y / fw.y) * 0.2);
        float d = 1e9;
        if ((m & 1) != 0) d = min(d, v_edge.y / fw.y);
        if ((m & 2) != 0) d = min(d, (v_size.x - v_edge.x) / fw.x);
        if ((m & 4) != 0) d = min(d, (v_size.y - v_edge.y) / fw.y);
        if ((m & 8) != 0) d = min(d, v_edge.x / fw.x);
        if (d < w) c *= 0.6;                                 // render_boxes' outline shade
    }
    f_col = vec4(crunch(c * lightf(v_depth, 0.0)), 1.0);
}
"""

GROUND_VS = """
#version 330
uniform mat4 u_vp;
uniform vec4 u_place;        // in_pos -> metres: origin xy, scale xy (the whole street: 0 0 1 1)
uniform vec4 u_texmap;       // where the texture lies, metres: origin xy, size xy
in vec2 in_pos;
out vec2 v_uv; out float v_depth;
void main() {
    vec2 p = u_place.xy + in_pos * u_place.zw;
    v_uv = (p - u_texmap.xy) / u_texmap.zw;
    gl_Position = u_vp * vec4(p, 0.0, 1.0);
    v_depth = gl_Position.w;
}
"""
GROUND_FS = """
#version 330
uniform sampler2D u_tex;
uniform vec3 u_haze;
uniform float u_fog_dist;
uniform vec3 u_tint;         // F10 disco (1,1,1 when off)
""" + _LIGHT_GLSL + """
in vec2 v_uv; in float v_depth;
out vec4 f_col;
void main() {
    vec3 c = texture(u_tex, v_uv).rgb * u_tint;
    // fp._floor_fog's haze: thicker with distance, and the night's in it too
    float a = min(1.0, clamp(v_depth / u_fog_dist, 0.0, 1.0) * 0.9 + u_dark * 0.55);
    f_col = vec4(crunch(mix(c, u_haze, a)), 1.0);
}
"""

BILL_VS = """
#version 330
uniform mat4 u_vp;
in vec3 in_pos; in vec2 in_uv;
out vec2 v_uv; out float v_depth;
void main() {
    v_uv = in_uv;
    gl_Position = u_vp * vec4(in_pos, 1.0);
    v_depth = gl_Position.w;
}
"""
BILL_FS = """
#version 330
uniform sampler2D u_tex;
""" + _LIGHT_GLSL + """
in vec2 v_uv; in float v_depth;
out vec4 f_col;
void main() {
    vec4 t = texture(u_tex, v_uv);
    if (t.a < 0.5) discard;
    f_col = vec4(crunch(t.rgb * lightf(v_depth, 0.0)), 1.0);
}
"""

PART_VS = """
#version 330
uniform mat4 u_vp;
in vec3 in_pos; in vec4 in_col;              // rgb + 1 if it glows (fire, sparks)
out vec4 v_col; out float v_depth;
void main() { v_col = in_col; gl_Position = u_vp * vec4(in_pos, 1.0); v_depth = gl_Position.w; }
"""
PART_FS = """
#version 330
""" + _LIGHT_GLSL + """
in vec4 v_col; in float v_depth;
out vec4 f_col;
void main() {
    // (QA: night smoke round a burning car was a pale grey wall: it was drawn unlit.) Smoke, dust,
    // debris and confetti take the night and the distance like everything else; fire and sparks
    // make their own light, so they stay at full brightness -- that's what makes them pop at night
    vec3 c = v_col.a > 0.5 ? v_col.rgb : v_col.rgb * lightf(v_depth, 0.0);
    f_col = vec4(crunch(c), 1.0);
}
"""

SKY_VS = """
#version 330
in vec2 in_pos;
void main() { gl_Position = vec4(in_pos, 0.999, 1.0); }
"""
SKY_FS = """
#version 330
uniform sampler2D u_sky_a;
uniform sampler2D u_sky_b;
uniform float u_mix;
uniform float u_u0;          // yaw / 2pi
uniform float u_vw;          // view px across: 360 degrees of sky is 4 of these (fp._sky)
uniform float u_vh;
uniform float u_hor;         // horizon row, px from the top
uniform float u_texel;       // view px per sky texel (row)
uniform float u_rows;        // sky texels tall
out vec4 f_col;
void main() {
    float row = u_vh - gl_FragCoord.y;
    float up = (u_hor - row) / u_texel;                  // sky rows above the horizon
    float v = clamp(1.0 - up / u_rows, 0.0, 1.0);
    vec2 uv = vec2(fract(u_u0 + gl_FragCoord.x / (4.0 * u_vw)), v);
    f_col = vec4(mix(texture(u_sky_a, uv).rgb, texture(u_sky_b, uv).rgb, u_mix), 1.0);
}
"""

FLAT_VS = """
#version 330
in vec2 in_pos;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); }
"""
FLAT_FS = """
#version 330
uniform vec4 u_col;
out vec4 f_col;
void main() { f_col = u_col; }
"""

BLIT_VS = """
#version 330
uniform vec4 u_rect;         // x0, y0, x1, y1 in NDC
uniform float u_flip;        // 1: a pygame upload (row 0 at the top)
in vec2 in_pos;              // 0..1
out vec2 v_uv;
void main() {
    v_uv = vec2(in_pos.x, u_flip > 0.5 ? 1.0 - in_pos.y : in_pos.y);
    gl_Position = vec4(mix(u_rect.xy, u_rect.zw, in_pos), 0.0, 1.0);
}
"""
BLIT_FS = """
#version 330
uniform sampler2D u_tex;
in vec2 v_uv;
out vec4 f_col;
void main() { f_col = texture(u_tex, v_uv); }
"""


def _surf_bytes(surf):
    """A pygame Surface as RGBA bytes, top row first."""
    return pygame.image.tobytes(surf, "RGBA")


# ---------------------------------------------------------------------------- the display
class Display:
    """The window's GL side, made once per OpenGL window: the context, and the pass that puts
    the 3D frame, its overlay and the 640x360 HUD/menu canvas on the screen. Every 2D thing in
    the game still draws to pygame Surfaces exactly as before; they're uploaded here."""

    def __init__(self):
        if moderngl is None:
            raise RuntimeError("moderngl isn't installed")
        self.ctx = moderngl.create_context(require=330)
        self.ctx.gc_mode = "auto"              # GL objects go when Python forgets them
        self.blit = self.ctx.program(vertex_shader=BLIT_VS, fragment_shader=BLIT_FS)
        quad = np.array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], dtype="f4")
        self._quad = self.ctx.buffer(quad.tobytes())
        self.blit_vao = self.ctx.vertex_array(self.blit, [(self._quad, "2f", "in_pos")])
        self.textures = {}                     # name -> Texture, for the per-frame uploads
        self.renderer = self.ctx.info.get("GL_RENDERER", "?")

    def upload(self, name, surf):
        """(Re)fill the named texture from a pygame Surface (same size: reused)."""
        w, h = surf.get_size()
        tex = self.textures.get(name)
        if tex is None or tex.size != (w, h):
            if tex is not None:
                tex.release()
            tex = self.textures[name] = self.ctx.texture((w, h), 4)
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.repeat_x = tex.repeat_y = False
        tex.write(_surf_bytes(surf))
        return tex

    def begin(self, win):
        """Start a frame on the window (w, h): black letterbox."""
        ctx = self.ctx
        ctx.screen.use()
        ctx.viewport = (0, 0, win[0], win[1])
        ctx.disable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._win = win

    def draw(self, tex, rect, flip, blend=False):
        """A texture over a window rect (x, y, w, h; y down from the top, like pygame)."""
        ww, wh = self._win
        x, y, w, h = rect
        x0, x1 = x / ww * 2 - 1, (x + w) / ww * 2 - 1
        y0, y1 = 1 - (y + h) / wh * 2, 1 - y / wh * 2
        self.blit["u_rect"].value = (x0, y0, x1, y1)
        self.blit["u_flip"].value = 1.0 if flip else 0.0
        if blend:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        tex.use(0)
        self.blit["u_tex"].value = 0
        self.blit_vao.render(moderngl.TRIANGLES)
        if blend:
            self.ctx.disable(moderngl.BLEND)

    def close(self):
        """Free this window's GL objects, then make the context inert: gc_mode None means a
        moderngl object of THIS context that's garbage-collected later (after a new context
        exists) does nothing, instead of deleting whatever the new context has under its id."""
        for tex in self.textures.values():
            tex.release()
        self.textures.clear()
        for o in (self.blit_vao, self._quad, self.blit):
            o.release()
        self.ctx.gc_mode = None
        try:
            self.ctx.release()
        except Exception:
            pass

    release = close


WORLD_FMT = "3f 2f 1f 3f 2f 2f 1f"
WORLD_ATTRS = ("in_pos", "in_uv", "in_shade", "in_nrm", "in_edge", "in_size", "in_mask")


class MeshRef:
    """What GLRenderer's _car_sprite & co hand back instead of a sprite: which look, how to
    build it, and the angle fp worked out (relative to the camera, like a sprite's)."""
    __slots__ = ("key", "make", "az")

    def __init__(self, key, make, az):
        self.key, self.make, self.az = key, make, az


class _Mesh:
    __slots__ = ("vbo", "vao", "n", "top", "inst", "cap")


# ---------------------------------------------------------------------------- the 3D view
class GLRenderer(FP.FPRenderer):
    """fp.FPRenderer with a GPU instead of a raycaster. Same constructor and draw() call as the
    classic one (plus the Display), so game.py treats them alike; draw() returns the overlay
    surface (see the module notes) and the 3D picture stays on the GPU in self.color."""
    is_gl = True

    def __init__(self, display, cmap, map_surf, vw, vh, scale=1):
        super().__init__(cmap, map_surf, vw, vh, scale)
        self.display = display
        ctx = self.ctx = display.ctx
        self.box_prog = ctx.program(vertex_shader=BOX_VS, fragment_shader=BOX_FS)
        self.world_prog = ctx.program(vertex_shader=WORLD_VS, fragment_shader=WORLD_FS)
        self.ground_prog = ctx.program(vertex_shader=GROUND_VS, fragment_shader=GROUND_FS)
        self.bill_prog = ctx.program(vertex_shader=BILL_VS, fragment_shader=BILL_FS)
        self.part_prog = ctx.program(vertex_shader=PART_VS, fragment_shader=PART_FS)
        self.sky_prog = ctx.program(vertex_shader=SKY_VS, fragment_shader=SKY_FS)
        self.flat_prog = ctx.program(vertex_shader=FLAT_VS, fragment_shader=FLAT_FS)
        lx, ly, lz = C.GL_LIGHT
        ln = math.sqrt(lx * lx + ly * ly + lz * lz)
        self.box_prog["u_light"].value = (lx / ln, ly / ln, lz / ln)
        self.world_prog["u_light"].value = (lx / ln, ly / ln, lz / ln)
        full = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")          # one triangle covers the screen
        self._full = ctx.buffer(full.tobytes())
        self.sky_vao = ctx.vertex_array(self.sky_prog, [(self._full, "2f", "in_pos")])
        self.flat_vao = ctx.vertex_array(self.flat_prog, [(self._full, "2f", "in_pos")])
        # the street: the top-down map, a copy with the same edits fp makes to its floor (benches
        # scrubbed off, the shops' floors in the shade) and the skid marks drawn in as they happen
        self.ground_ppm = C.PPM
        self.ground = map_surf.copy()
        for (rx, ry, rw, rh), col, flags in self._floor_edits:
            k = self.ground_ppm
            self.ground.fill(col, pygame.Rect(int(rx * k), int(ry * k), int(math.ceil(rw * k)),
                                              int(math.ceil(rh * k))), special_flags=flags)
        gw, gh = self.ground.get_size()
        self.ground_tex = ctx.texture((gw, gh), 4, _surf_bytes(self.ground))
        self.ground_tex.build_mipmaps()
        # far street: the mip below the one you'd need, so it doesn't sparkle (still no blur up close)
        self.ground_tex.filter = (moderngl.NEAREST_MIPMAP_NEAREST, moderngl.NEAREST)
        self.ground_tex.repeat_x = self.ground_tex.repeat_y = False
        self._ground_dirty = None
        self._ground_mip_t = 0.0
        m = 60.0                                            # past the map edge: the edge walls hide it
        size = (gw / self.ground_ppm, gh / self.ground_ppm)
        g = np.array([-m, -m, size[0] + m, -m, size[0] + m, size[1] + m,
                      -m, -m, size[0] + m, size[1] + m, -m, size[1] + m], dtype="f4")
        self._ground_vbo = ctx.buffer(g.tobytes())
        self.ground_vao = ctx.vertex_array(self.ground_prog, [(self._ground_vbo, "2f", "in_pos")])
        self.ground_prog["u_fog_dist"].value = C.FP_FLOOR_DIST
        # the near street at the texel scale: fp's own hi-res floor chunks (FLOOR_CHUNK_M squares at
        # 5 x kw px/m, detail tiles, the skids replayed), uploaded as they're built
        self._unit = ctx.buffer(np.array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], dtype="f4").tobytes())
        self.chunk_vao = ctx.vertex_array(self.ground_prog, [(self._unit, "2f", "in_pos")])
        self._chunk_tex = {}                   # (ix, iy, kw) -> Texture
        self._chunk_dirty = set()
        self._ground_size = size
        FP.FPRenderer.set_world_scale(self, self._tex_scale())
        # the static city (world3d), day and night
        self._dyn_quads = {}
        self.worlds = {}
        self._world_mesh(False)
        self._world_mesh(True)                 # (now, not at dusk: a ~0.2 s build mid-chase is a hitch you'd feel)
        self.meshes = OrderedDict()            # look key -> _Mesh, LRU (GL_MESH_CACHE)
        self._car_fit = {}                     # model -> (stock extent, hl, hw)
        self._dyn_seen = {}                    # fixture id -> last state a trap row said
        self.bill_tex = {}                     # id(surface) -> (surface, Texture)
        self.sky_tex = {}
        self._dyn_cap = 6 * 2048                  # billboard vertices (5 floats each); grows if a forest needs it
        self._dyn_buf = ctx.buffer(reserve=20 * self._dyn_cap)
        self.bill_vao = ctx.vertex_array(self.bill_prog, [(self._dyn_buf, "3f 2f", "in_pos", "in_uv")])
        self._wx_buf = ctx.buffer(reserve=4 * WORLD_STRIDE * 600)   # the sale boards' lettered faces, per frame
        self._wx_vao = ctx.vertex_array(self.world_prog, [(self._wx_buf, WORLD_FMT) + WORLD_ATTRS])
        self._part_buf = ctx.buffer(reserve=4 * 7 * 6 * 700)
        self.part_vao = ctx.vertex_array(self.part_prog, [(self._part_buf, "3f 4f", "in_pos", "in_col")])
        self._zero_inst = None
        self._make_targets()
        self.stats = {}

    # -- targets ----------------------------------------------------------------------------
    def _make_targets(self):
        ctx = self.ctx
        for name in ("color", "depth", "fbo"):
            old = self.__dict__.get(name)
            if old is not None:
                old.release()
        self.color = ctx.texture((self.vw, self.vh), 4)
        self.color.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.depth = ctx.depth_renderbuffer((self.vw, self.vh))
        self.fbo = ctx.framebuffer(color_attachments=[self.color], depth_attachment=self.depth)
        self.overlay = pygame.Surface((self.vw, self.vh), pygame.SRCALPHA)

    def set_scale(self, scale):
        super().set_scale(scale)
        if self.color.size != (self.vw, self.vh):
            self._make_targets()
        self.set_world_scale(None)

    def _tex_scale(self):
        """(v0.20, Bryce: "ensure the scaling factor applies to both types of drawn planes") the
        city's and the near street's texel density follows the render scale k: walls, ceilings
        and the street within FLOOR_DETAIL_DIST are painted at k x their 1x texels a metre, the
        same factor the cars and people get from simply being drawn into a k x frame. So 2x shows
        twice the brickwork, not the same bricks blown up. (Capped at GL_TEX_SCALE_MAX.)"""
        return max(1, min(self.ks, C.GL_TEX_SCALE_MAX, C.WORLD_SCALE_MAX))

    def set_world_scale(self, w):
        """WORLD DETAIL is the raycaster's knob; in 3D the texel scale follows the render scale
        instead (_tex_scale), so whatever's asked for, this is what's used. Changing it rebuilds
        the city's atlas (~0.2 s) and drops the near-street chunks; returns the scale in use."""
        sc = self._tex_scale()
        if sc != self.kw:
            FP.FPRenderer.set_world_scale(self, sc)       # (fp's floor chunks and sky caches, at sc)
            if "worlds" in self.__dict__:
                self._rebuild_world()
        return self.kw

    def _rebuild_world(self):
        for wm in self.worlds.values():
            if wm["vao"] is not None:
                wm["vao"].release()
            wm["tex"].release()
        self.worlds.clear()
        self._dyn_quads.clear()
        for t in self._chunk_tex.values():
            t.release()
        self._chunk_tex.clear()
        self._chunk_dirty.clear()
        self._world_mesh(False)
        self._world_mesh(True)

    # -- the street's skid marks --------------------------------------------------------------
    def _skid_hires(self, a, b):
        """(fp._skids calls this for every new segment, in metres) draw it into our street."""
        k = self.ground_ppm
        pa, pb = (int(a[0] * k), int(a[1] * k)), (int(b[0] * k), int(b[1] * k))
        r = pygame.draw.line(self.ground, (38, 38, 46), pa, pb, 1)
        self._ground_dirty = r if self._ground_dirty is None else self._ground_dirty.union(r)
        if self.kw > 1:                                # ...and into the hi-res chunks (fp logs and draws them)
            FP.FPRenderer._skid_hires(self, a, b)
            cm = C.FLOOR_CHUNK_M
            for x, y in (a, b):
                self._chunk_dirty.add((int(x // cm), int(y // cm), self.kw))

    def _flush_ground(self, now):
        r = self._ground_dirty
        if r is None:
            return
        r = r.clip(self.ground.get_rect())
        self._ground_dirty = None
        if r.w <= 0 or r.h <= 0:
            return
        self.ground_tex.write(_surf_bytes(self.ground.subsurface(r)), viewport=(r.x, r.y, r.w, r.h))
        if now - self._ground_mip_t > C.GL_GROUND_MIP_EVERY:
            self._ground_mip_t = now
            self.ground_tex.build_mipmaps()

    # -- the static city ----------------------------------------------------------------------
    def _world_mesh(self, night):
        wm = self.worlds.get(night)
        if wm is None:
            t0 = time.perf_counter()
            world, real = build_world(self.map, night=night, sc=self.kw)
            ctx = self.ctx
            raw = np.ascontiguousarray(world.vertices, dtype=np.float32)
            verts = world_edges(raw)
            vbo = ctx.buffer(verts.tobytes()) if verts.size else None
            vao = ctx.vertex_array(self.world_prog, [(vbo, WORLD_FMT) + WORLD_ATTRS]) if vbo is not None else None
            atlas = world.atlas
            tex = ctx.texture(atlas.get_size(), 4, _surf_bytes(atlas))
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            # draw ranges: everything but the parapets as its own list, so indoors (where the
            # ceiling hides them anyway) they're skipped, as fp's cam_inside did
            nv = len(verts)
            groups = getattr(world, "groups", None) or {}
            par = groups.get("parapets")
            if par and par[1]:
                a, n = par
                inside = [r for r in ((0, a), (a + n, nv - a - n)) if r[1] > 0]
            else:
                inside = [(0, nv)]
            wm = self.worlds[night] = {"vao": vao, "n": nv, "tex": tex, "world": world,
                                       "dyn": list(getattr(world, "dynamic", ()) or ()),
                                       "ranges": {"out": [(0, nv)], "in": inside},
                                       "real": real, "build_ms": (time.perf_counter() - t0) * 1000.0}
            # with the real city the trees, lamps, counters and crates are in the mesh: fp mustn't
            # draw them again (only their labels, see fp._collect's `fix`)
            self.static_in_world = real
        return wm

    # -- the moving bits of the world (world3d's .dynamic) ------------------------------------------
    def _dyn_state(self, obj, rows, me_xy, shops, lever_down):
        """What state a world3d Dynamic is in, from the snapshot. Fixtures only come as trap rows
        within NET_CULL_RADIUS of you; past that the last state seen is kept (or the default)."""
        kind = obj.kind
        if kind == "lever":
            return lever_down
        if kind in ("crate", "sale_board"):
            idx = obj.info.get("shop", 0)
            if kind == "crate":
                return bool(shops & (16 << idx))
            return 2 if shops & (16 << idx) else 1 if shops & (1 << idx) else 0
        t = rows.get(obj.id)
        seen = self._dyn_seen
        if t is not None:
            if kind in ("door", "walkdoor", "celldoor"):
                st = round(C.clamp(t[5], 0.0, 1.0) * C.GL_DOOR_STEPS) / C.GL_DOOR_STEPS
            elif kind == "gate":
                st = 1 if t[5] > 0 else 0
            else:                                              # junk: its row is there, so the pile is
                st = True
            seen[obj.id] = st
            return st
        x, y = obj.pos
        near = (x - me_xy[0]) ** 2 + (y - me_xy[1]) ** 2 < (C.NET_CULL_RADIUS - 3.0) ** 2
        if kind == "junk" and (near or shops & (16 << obj.info.get("shop", 0))):
            seen[obj.id] = False                               # in range and no row: cleared
            return False
        return seen.get(obj.id, obj.default_state)

    def _dynamic(self, wm, view, cx, cy, groups, extra_quads):
        """Pose every Dynamic near enough to see: boxes go into the mesh groups (the same shading
        and outlines as the cars), the lettered sale boards' faces into extra_quads (atlas)."""
        rows = {t[0]: t for t in getattr(view, "traps", {}).values()}
        snap = getattr(view, "snap", None)
        shops = (getattr(snap, "shops", 1) or 1) if snap is not None else 1
        doors = [t[5] for t in rows.values() if t[1] == S.TRAP_DOOR]
        lever_down = bool(doors) and all(life < C.DOOR_PASSABLE for life in doors)
        me = getattr(view, "me", None)
        me_xy = (me[4], me[5]) if me is not None else (cx, cy)
        r2 = (C.FP_SPRITE_DIST + 10.0) ** 2
        for i, obj in enumerate(wm["dyn"]):
            x, y = obj.pos
            if (x - cx) ** 2 + (y - cy) ** 2 > r2:
                continue
            st = self._dyn_state(obj, rows, me_xy, shops, lever_down)
            key = ("dyn", wm["real"], i, st)
            m = self._mesh(key, lambda o=obj, s_=st: o.boxes_for(s_))
            if m.n:
                groups.setdefault(key, (m, []))[1].extend((0.0, 0.0, 0.0, 0.0))
            if obj.kind == "sale_board" and hasattr(obj, "quads_for"):
                q = self._dyn_quads.get((i, st))
                if q is None:
                    q = self._dyn_quads[(i, st)] = world_edges(obj.quads_for(st))
                if len(q):
                    extra_quads.append(q)

    # -- meshes ------------------------------------------------------------------------------
    def _car_sprite(self, row, az, steps=None, base=12):
        look, make = self._car_look(row)
        model = row[15]
        return MeshRef(("car",) + look, lambda: self._fit_car(model, make()), az)

    def _fit_car(self, model, boxes):
        """The car's boxes, fitted to its collision footprint (see fit_boxes). The fit is worked
        out once per model from the stock car, so a stripped bumper doesn't stretch what's left."""
        fit = self._car_fit.get(model)
        if fit is None:
            stock = FA.car_boxes(S.CIV, 0, 0xFFFFFFFF, 0, 0, 0, model)
            m = V.model(model)
            fit = self._car_fit[model] = (box_extent(stock), m.length / 2.0, m.width / 2.0)
        return fit_boxes(boxes, *fit)

    def _person_sprite(self, shirt, skin, hair, frame, extra, down, az, gun=0, outfit=None, char=None):
        key = ("person", shirt, skin, hair, frame, extra, down, gun, self.big_heads, outfit, char)
        return MeshRef(key, lambda: self._person_boxes(shirt, skin, hair, frame, extra, down, gun, outfit, char), az)

    def _dog_sprite(self, frame, trousers, down, az):
        return MeshRef(("dog", frame, trousers, down), lambda: self._dog_boxes(frame, trousers, down), az)

    def _model_sprite(self, name, boxes_fn, az, steps=None, base=16):
        return MeshRef(("model", name), boxes_fn, az)

    def _mesh(self, key, make):
        m = self.meshes.get(key)
        if m is not None:
            self.meshes.move_to_end(key)
            return m
        arr = boxes_to_mesh(make())
        m = _Mesh()
        m.n = len(arr)
        m.top = mesh_top(arr)
        m.vbo = m.vao = m.inst = None
        m.cap = 0
        if m.n:
            m.vbo = self.ctx.buffer(arr.tobytes())
            self._mesh_inst(m, 16)
        self.meshes[key] = m
        while len(self.meshes) > C.GL_MESH_CACHE:
            _k, old = self.meshes.popitem(last=False)
            for o in (old.vao, old.inst, old.vbo):
                if o is not None:
                    o.release()
        return m

    def _mesh_inst(self, m, cap):
        if m.vao is not None:
            m.vao.release()
            m.inst.release()
        m.cap = cap
        m.inst = self.ctx.buffer(reserve=cap * 16)
        m.vao = self.ctx.vertex_array(self.box_prog, [
            (m.vbo, "3f 3f 3f 2f 2f", "in_pos", "in_nrm", "in_col", "in_edge", "in_size"),
            (m.inst, "4f/i", "in_inst")])

    def _billboard_tex(self, surf):
        e = self.bill_tex.get(id(surf))
        if e is None or e[0] is not surf:
            if len(self.bill_tex) > 512:
                for _s, t in self.bill_tex.values():
                    t.release()
                self.bill_tex.clear()
            tex = self.ctx.texture(surf.get_size(), 4, _surf_bytes(surf))
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.repeat_x = tex.repeat_y = False
            e = self.bill_tex[id(surf)] = (surf, tex)       # (holding the surface keeps its id unique)
        return e[1]

    def _sky(self, key):
        tex = self.sky_tex.get(key)
        if tex is None:
            sc = max(1, min(self.ks, C.GL_SKY_SCALE))
            img = FA.make_sky(key, 4 * C.LOW_W, int(self.vh // self.ks * 0.95), sc)
            tex = self.ctx.texture(img.get_size(), 4, _surf_bytes(img))
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            tex.repeat_x, tex.repeat_y = True, False
            self.sky_tex[key] = (tex, sc, img.get_height())
            tex = self.sky_tex[key]
        return tex

    # -- the frame ---------------------------------------------------------------------------
    def draw(self, view, cam, me_pid, now, dt, day_left, bank, hide_car=None, pitch=0, hires=None):
        """Same call as FPRenderer.draw. Renders the 3D view into self.fbo and returns the
        overlay (labels, tracers; the caller adds the hands) for the compositor."""
        t0 = time.perf_counter()
        cx, cy, yaw, eye = cam
        self.hor = int(C.clamp(self.hor0 + pitch, 6, self.vh - 6))
        self.hires = hires
        want_fov = min(math.radians(170.0), self.fov + math.radians(35.0 + 18.0 * math.sin(time.perf_counter() * 1.3))) \
            if self.fisheye else self.fov
        if want_fov != self._cur_fov:
            self._apply_fov(want_fov)
        if self.shake > 0.05:
            yaw += self.rng.uniform(-0.01, 0.01) * self.shake
            eye += self.rng.uniform(-0.02, 0.02) * self.shake
            self.shake *= math.exp(-dt * 8)
        self._phase = int(now * 6) % 2
        self._chunk_budget = C.FLOOR_CHUNKS_PER_FRAME
        tod = FP.time_of_day(day_left)
        dark = FP.darkness(tod)
        night = dark > 0.55
        self._skids(view)
        self._flush_ground(now)
        ov = self.overlay
        ov.fill((0, 0, 0, 0))
        vp = view_proj(cx, cy, yaw, eye, self._cur_fov, self.vw, self.vh, self.hor)
        vp_gl = vp.T.astype("f4").tobytes()                      # (GL wants column-major)
        items = self._collect(view, cx, cy, yaw, me_pid, now, dt, night, bank, hide_car,
                              behind=-C.GL_CULL_BEHIND, margin=C.GL_CULL_MARGIN)
        t1 = time.perf_counter()
        # ---- sort what came back into GPU work and 2D work
        groups = {}                     # mesh key -> (mesh, [instance floats])
        bills = {}                      # texture -> [vertex floats]
        tags = []                       # (tag, x, y, z, height, depth, lat)
        ca, sa = math.cos(yaw), math.sin(yaw)
        rx, ry = -sa, ca
        for depth, lat, img_fn, z, tag, x, y in items:
            if img_fn is None:
                if tag is not None:
                    tags.append((tag, x, y, z, 0.0, depth, lat))
                continue
            res = img_fn()
            if isinstance(res, FP.LabelOnly):
                if tag is not None:
                    tags.append((tag, x, y, z, res.h, depth, lat))
                continue
            if isinstance(res, MeshRef):
                m = self._mesh(res.key, res.make)
                if m.n:
                    heading = math.atan2(y - cy, x - cx) - res.az
                    g = groups.get(res.key)
                    if g is None:
                        g = groups[res.key] = (m, [])
                    g[1].extend((x, y, z, heading))
                if tag is not None:
                    tags.append((tag, x, y, z, m.top, depth, lat))
                continue
            img, ppm = res
            if isinstance(img, tuple):
                img, ax, ay = img
            else:
                ax, ay = img.get_width() / 2.0, img.get_height()
            w, h = img.get_size()
            tex = self._billboard_tex(img)
            l0, l1 = -ax / ppm, (w - ax) / ppm
            zb, zt = z - (h - ay) / ppm, z + ay / ppm
            ax0, ay0 = x + rx * l0, y + ry * l0
            ax1, ay1 = x + rx * l1, y + ry * l1
            v = bills.get(tex)
            if v is None:
                v = bills[tex] = []
            v.extend((ax0, ay0, zb, 0.0, 1.0, ax1, ay1, zb, 1.0, 1.0, ax1, ay1, zt, 1.0, 0.0,
                      ax0, ay0, zb, 0.0, 1.0, ax1, ay1, zt, 1.0, 0.0, ax0, ay0, zt, 0.0, 0.0))
            if tag is not None:
                tags.append((tag, x, y, z, ay / ppm, depth, lat))
        parts = []
        self._particles(None, cx, cy, yaw, eye, dt, sink=parts)
        # ---- GPU
        ctx = self.ctx
        self.fbo.use()
        ctx.viewport = (0, 0, self.vw, self.vh)
        ctx.disable(moderngl.BLEND | moderngl.CULL_FACE)
        ctx.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        levels = float(C.GL_COLOR_LEVELS)
        self._draw_sky(tod, yaw)
        ctx.enable(moderngl.DEPTH_TEST)
        # ground: pushed back a hair so a puddle of underglow 1 cm up never fights it
        gp = self.ground_prog
        gp["u_vp"].write(vp_gl)
        gp["u_dark"].value = dark
        gp["u_levels"].value = levels
        hz = shade((150, 150, 160), 1.0 - 0.8 * dark)
        gp["u_haze"].value = (hz[0] / 255.0, hz[1] / 255.0, hz[2] / 255.0)
        gp["u_tint"].value = self._disco_tint()
        self.ground_tex.use(0)
        gp["u_tex"].value = 0
        gp["u_place"].value = (0.0, 0.0, 1.0, 1.0)
        gp["u_texmap"].value = (0.0, 0.0) + tuple(self._ground_size)
        ctx.polygon_offset = (2.0, 8.0)
        self.ground_vao.render(moderngl.TRIANGLES)
        ctx.polygon_offset = (1.0, 4.0)                       # (the near chunks lie over it, a hair nearer)
        self._near_ground(cx, cy)
        ctx.polygon_offset = (0.0, 0.0)
        wm = self._world_mesh(night)
        wp = self.world_prog
        wp["u_vp"].write(vp_gl)
        wp["u_dark"].value = dark
        wp["u_levels"].value = levels
        wp["u_outline"].value = float(max(1.0, C.GL_OUTLINE_PX * self.ks))
        if wm["vao"] is not None:
            wm["tex"].use(0)
            wp["u_tex"].value = 0
            # indoors (under a roof) the parapets are behind the ceiling: don't draw them
            for first, n in wm["ranges"]["in" if self._roof_box(cx, cy) is not None else "out"]:
                wm["vao"].render(moderngl.TRIANGLES, first=first, vertices=n)
        # the moving bits of the world: doors, gate, cells, junk, the lever, boards, fence crates
        extra = []
        self._dynamic(wm, view, cx, cy, groups, extra)
        if extra:
            data = np.ascontiguousarray(np.concatenate(extra), dtype=np.float32)
            if data.nbytes > self._wx_buf.size:
                self._wx_buf.orphan(data.nbytes * 2)
            self._wx_buf.write(data.tobytes())
            self._wx_vao.render(moderngl.TRIANGLES, vertices=len(data))
        bp = self.box_prog
        bp["u_vp"].write(vp_gl)
        bp["u_dark"].value = dark
        bp["u_levels"].value = levels
        bp["u_outline"].value = float(max(1.0, C.GL_OUTLINE_PX * self.ks))
        draws = 0
        for m, inst in groups.values():
            n = len(inst) // 4
            if n > m.cap:
                self._mesh_inst(m, max(n, m.cap * 2))
            m.inst.write(np.asarray(inst, dtype="f4").tobytes())
            m.vao.render(moderngl.TRIANGLES, vertices=m.n, instances=n)
            draws += 1
        if bills:
            data = []
            spans = []
            for tex, v in bills.items():
                spans.append((tex, len(data) // 5, len(v) // 5))
                data.extend(v)
            nv = len(data) // 5
            if nv > self._dyn_cap:
                self._dyn_cap = nv * 2
                self._dyn_buf.orphan(20 * self._dyn_cap)
            self._dyn_buf.write(np.asarray(data, dtype="f4").tobytes())
            bl = self.bill_prog
            bl["u_vp"].write(vp_gl)
            bl["u_dark"].value = dark
            bl["u_levels"].value = levels
            bl["u_tex"].value = 0
            for tex, first, n in spans:
                tex.use(0)
                self.bill_vao.render(moderngl.TRIANGLES, vertices=n, first=first)
                draws += 1
        if parts:
            self._draw_particles(parts, vp_gl, rx, ry, dark, levels)
        ctx.disable(moderngl.DEPTH_TEST)
        if self.flash is not None:
            col, a = self.flash
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self.flat_prog["u_col"].value = (col[0] / 255.0, col[1] / 255.0, col[2] / 255.0, min(255, a) / 255.0)
            self.flat_vao.render(moderngl.TRIANGLES)
            ctx.disable(moderngl.BLEND)
            a -= dt * 400
            self.flash = (col, a) if a > 4 else None
        t2 = time.perf_counter()
        # ---- 2D on top: tracers, labels, booms
        self._tracers(ov, cx, cy, yaw, eye, dt)
        self._overlay_tags(ov, tags, cx, cy, eye, now, dt, bank)
        self.stats = {"collect_ms": (t1 - t0) * 1000.0, "gpu_ms": (t2 - t1) * 1000.0,
                      "overlay_ms": (time.perf_counter() - t2) * 1000.0, "draws": draws,
                      "items": len(items), "meshes": len(self.meshes), "parts": len(parts)}
        return ov

    def _near_ground(self, cx, cy):
        """The street within FLOOR_DETAIL_DIST at the texel scale (fp's floor chunks), over the
        whole-map 5 px/m street. Nothing to do at 1x: the base street is already that."""
        if self.kw <= 1:
            return
        cm, r = C.FLOOR_CHUNK_M, C.FLOOR_DETAIL_DIST
        last = int(math.ceil(self.map.n * T / cm)) - 1
        gp = self.ground_prog
        for ix in range(max(0, int((cx - r) // cm)), min(last, int((cx + r) // cm)) + 1):
            for iy in range(max(0, int((cy - r) // cm)), min(last, int((cy + r) // cm)) + 1):
                key = (ix, iy, self.kw)
                tex = self._chunk_tex.get(key)
                if tex is None or key in self._chunk_dirty or key not in self._chunks:
                    surf = self._floor_chunk(ix, iy)
                    if surf is None:
                        continue                               # (built next frame: the base street meanwhile)
                    if tex is None or tex.size != surf.get_size():
                        if tex is not None:
                            tex.release()
                        tex = self._chunk_tex[key] = self.ctx.texture(surf.get_size(), 4)
                        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
                        tex.repeat_x = tex.repeat_y = False
                    tex.write(_surf_bytes(surf))
                    self._chunk_dirty.discard(key)
                x0, y0, w, h = self._chunk_rect_m(ix, iy)
                gp["u_place"].value = (x0, y0, w, h)
                gp["u_texmap"].value = (x0, y0, w, h)
                tex.use(0)
                self.chunk_vao.render(moderngl.TRIANGLES)
        for k in [k for k in self._chunk_tex if k not in self._chunks]:
            self._chunk_tex.pop(k).release()                   # (fp's LRU dropped the surface)

    def _disco_tint(self):
        if not self.disco:
            return (1.0, 1.0, 1.0)
        import colorsys
        hue = (time.perf_counter() * 0.25) % 1.0
        return colorsys.hsv_to_rgb(hue, 0.85, 1.0)

    def _draw_sky(self, tod, yaw):
        a, b, t = FP.sky_mix(tod)
        ta, sc, rows = self._sky(a)
        tb = self._sky(b)[0] if t > 0.01 else ta
        sp = self.sky_prog
        ta.use(0)
        tb.use(1)
        sp["u_sky_a"].value = 0
        sp["u_sky_b"].value = 1
        sp["u_mix"].value = t if t > 0.01 else 0.0
        sp["u_u0"].value = (yaw % TWO_PI) / TWO_PI
        sp["u_vw"].value = float(self.vw)
        sp["u_vh"].value = float(self.vh)
        sp["u_hor"].value = float(self.hor)
        sp["u_texel"].value = self.ks / float(sc)
        sp["u_rows"].value = float(rows)
        self.sky_vao.render(moderngl.TRIANGLES)

    def _draw_particles(self, parts, vp_gl, rx, ry, dark, levels):
        look = self.particle_look
        glow = (FP.SPARK, FP.FIRE)
        data = []
        for p in parts[:700]:
            c, s = look(p)
            h = s / 2.0
            x, y, z = p[0], p[1], p[2]
            r, g, b, e = c[0] / 255.0, c[1] / 255.0, c[2] / 255.0, 1.0 if p[8] in glow else 0.0
            x0, y0, x1, y1 = x - rx * h, y - ry * h, x + rx * h, y + ry * h
            data.extend((x0, y0, z - h, r, g, b, e, x1, y1, z - h, r, g, b, e, x1, y1, z + h, r, g, b, e,
                         x0, y0, z - h, r, g, b, e, x1, y1, z + h, r, g, b, e, x0, y0, z + h, r, g, b, e))
        self._part_buf.write(np.asarray(data, dtype="f4").tobytes())
        pp = self.part_prog
        pp["u_vp"].write(vp_gl)
        pp["u_dark"].value = dark
        pp["u_levels"].value = levels
        self.part_vao.render(moderngl.TRIANGLES, vertices=len(data) // 7)

    def _overlay_tags(self, surf, tags, cx, cy, eye, now, dt, bank):
        """The labels, markers and dolly icons fp draws over its sprites, in the same places
        (fp's own _draw_tag, with fp's projection: view_proj is built to agree with it). A wall
        between you and the thing hides its label, as the raycaster's zbuf did."""
        hor, D, vw = self.hor, self.D, self.vw
        ks = self.ks
        los = self.map.los
        for tag, x, y, z, top_m, depth, lat in tags:
            if depth < 0.3:
                continue
            sx = vw / 2 + lat / depth * D
            if tag[0] == "boom":
                self._draw_boom(surf, tag[1], sx, depth, eye, dt)
                continue
            if depth > 90 or not los(cx, cy, x, y):
                continue
            ground = hor + (eye - z) * D / depth
            if tag[0] == "say":
                if depth < 50:
                    self.font.draw(surf, tag[1], int(sx), int(ground), P["gold"], scale=ks, align="center")
                continue
            top = int(ground - top_m * D / depth)
            self._draw_tag(surf, tag, sx, top, ground, depth, now, bank, True)

    def snapshot(self):
        """The 3D view plus its overlay, as a pygame Surface (the mod shop's frozen backdrop)."""
        data = self.fbo.read(components=3)
        img = pygame.image.frombytes(data, (self.vw, self.vh), "RGB", True)
        img.blit(self.overlay, (0, 0))
        return img

    def release(self):
        """Give the GPU its memory back (leaving a game, switching renderer)."""
        for m in self.meshes.values():
            for o in (m.vao, m.inst, m.vbo):
                if o is not None:
                    o.release()
        self.meshes.clear()
        for _s, t in self.bill_tex.values():
            t.release()
        self.bill_tex.clear()
        for t in self.sky_tex.values():
            t[0].release()
        self.sky_tex.clear()
        for wm in self.worlds.values():
            if wm["vao"] is not None:
                wm["vao"].release()
            wm["tex"].release()
        self.worlds.clear()
        for t in self._chunk_tex.values():
            t.release()
        self._chunk_tex.clear()
        for o in (self.fbo, self.color, self.depth, self.ground_tex):
            o.release()

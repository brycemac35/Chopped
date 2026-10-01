"""
fp.py -- the Doom-style first-person view. A classic grid raycaster: one ray
per screen column finds the nearest wall tile, and a 1-pixel slice of its
texture is stretched to the right height. The street under your feet is the
top-down city map, rotated and sliced into rows ("mode 7", like an old SNES
racer). Cars, people and loose parts are sprites, clipped per column against
the walls. All of it in plain pygame, so it runs from the same one-file exe.

Performance notes: ~4 ms a frame at 480x238 on a laptop. The expensive
things (texture shading, sprite rotations) are done once and cached; the
per-frame work is arithmetic, subsurface() and transform.scale().

(v0.17) Hi-res: the view is `scale` x 640x328 (config.RENDER_SCALE_DEFAULT). Sprites,
particles and tracers get the full resolution.
(v0.19) The static world -- walls, street, ceilings, sky -- draws at its own WORLD scale
`kw` (1..ks, set_world_scale): kw x 640 columns and rows, with textures built at kw x their
old texel density, then blown up to the view if kw < ks. kw = 1 is the v0.17 look.
"""

import colorsys
import math
import random
import time
from collections import OrderedDict, deque

import pygame

from . import config as C
from .config import clamp
from . import mapgen as M
from . import fpart as FA
from . import art as ART
from . import sim as S
from . import protocol as PR
from .art import P, PLAYER_COLORS, SKINS, HAIRS, SHIRTS, PixelFont, shade
from .parts import SLOT_ANCHOR, NO_PART, PART_IDS
from . import vehicles as V

GNOME_IDX = PART_IDS.index("gnome")
FACADE_PX = int(C.SHOP_FACADE_H * FA.TEX / 4)   # texture rows for the shop's full-height walls (8 px/m)

T = C.TILE_M
FLOOR_PPM = 4
ROOF_PPM = 8                  # (v0.9) the shop roof's texture: sharper than the street, it's right above you
ROOF_KEY = (255, 0, 255)      # "no roof here" in the roof layer
TWO_PI = 2 * math.pi

# particle kinds (same idea as render.py, but in 3D)
SPARK, SMOKE, FIRE, DEBRIS, CONFETTI, DUST = range(6)
CONFETTI_COLS = [(255, 80, 80), (80, 200, 255), (255, 230, 60), (120, 230, 110), (236, 90, 206)]
MARK_STEAL = (120, 236, 90)     # green arrow: nobody's driving it, go on
MARK_JACK = (255, 150, 40)      # orange arrow: traffic that's stopped. Drag them out.
TRACER_COL = (255, 240, 170)


PLAYER_ROW_LEN = 19          # decode_snapshot's player tuple before (v0.16) `char` was appended as its LAST item


def _pchar(p):
    """A decoded player row's character id (0 if the row predates the char field)."""
    return p[-1] if len(p) > PLAYER_ROW_LEN else 0


def time_of_day(day_left):
    """0 = dawn ... 1 = midnight. Days run from morning to midnight."""
    return C.clamp(1.0 - day_left / C.DAY_LENGTH, 0.0, 1.0)


def sky_mix(tod):
    """Which two skies to show and how much of the second."""
    stops = ((0.0, "dawn"), (0.18, "day"), (0.62, "day"), (0.78, "dusk"), (0.9, "night"), (1.01, "night"))
    for (t0, a), (t1, b) in zip(stops, stops[1:]):
        if t0 <= tod < t1:
            return a, b, (tod - t0) / (t1 - t0)
    return "night", "night", 0.0


def darkness(tod):
    """0 = broad daylight, 1 = midnight. Drives shading and the night textures."""
    if tod < 0.12:
        return 0.35 * (1 - tod / 0.12)
    if tod < 0.62:
        return 0.0
    return C.clamp((tod - 0.62) / 0.3, 0.0, 1.0)


class SpriteCache:
    """(v0.17) Every rendered sprite angle, evicted least-recently-used by pixel bytes rather
    than by count: at 4x detail one chase-cam car angle weighs as much as a hundred far-away
    people, so "4000 entries" could mean 40 MB or 4 GB depending on what you'd been looking at."""

    def __init__(self, budget_mb):
        self.budget = int(budget_mb * 1024 * 1024)
        self.bytes = 0
        self.d = OrderedDict()           # key -> (sprite, bytes)

    def __len__(self):
        return len(self.d)

    def get(self, key):
        hit = self.d.get(key)
        if hit is None:
            return None
        self.d.move_to_end(key)
        return hit[0]

    def put(self, key, spr):
        surf = spr[0] if isinstance(spr, tuple) else spr
        n = surf.get_width() * surf.get_height() * surf.get_bytesize()
        old = self.d.pop(key, None)
        if old is not None:
            self.bytes -= old[1]
        self.d[key] = (spr, n)
        self.bytes += n
        while self.bytes > self.budget and len(self.d) > 1:
            _k, (_s, m) = self.d.popitem(last=False)
            self.bytes -= m
        return spr

    def clear(self):
        self.d.clear()
        self.bytes = 0


class FPRenderer:
    def __init__(self, cmap, map_surf, vw, vh, scale=1):
        self.map = cmap
        self.cam_inside = False       # (v0.12.1) camera under the shop roof: skip what the ceiling hides
        self.vw, self.vh = vw, vh
        self.ks = max(1, int(scale))  # (v0.17) render scale: vw is ks x 640. Text, lines and marks grow by it
        self.kw = 1                   # (v0.19) world scale: walls/street/sky at kw x 640 (set_world_scale)
        self.cstep = self.ks          # view columns per zbuf step (one wall ray per world column)
        self.hor0 = vh // 2
        self.hor = self.hor0          # moves with pitch (looking up/down: Build-engine y-shearing)
        self.fov = math.radians(C.FP_FOV)
        self._cur_fov = None          # (v0.12) F8 fisheye wobbles this away from self.fov and back
        self._apply_fov(self.fov)
        self._spx = 0.0               # (v0.17) screen px per metre of the sprite being fetched: picks its mip
        self.view = pygame.Surface((vw, vh)).convert()
        self.font = PixelFont()
        self.rng = random.Random(9)
        self._build_walls()
        n = cmap.n
        size = int(n * T * FLOOR_PPM)
        self.floor_map = pygame.transform.scale(map_surf, (size, size)).convert()
        # (v0.19) the same edits in metres, for the hi-res floor chunks: (rect, colour, blend flags)
        self._floor_edits = []
        # the benches are 3D objects here; scrub their flat top-down drawings off the floor
        for bx, by, bw, bh in (cmap.sell_bench, cmap.tune_bench) + tuple(
                fs["bench"] for fs in getattr(cmap, "fence_shops", ()) if fs.get("bench") is not None):
            self.floor_map.fill(P["concrete"], (int(bx * FLOOR_PPM) - 2, int(by * FLOOR_PPM) - 2,
                                                int(bw * FLOOR_PPM) + 6, int(bh * FLOOR_PPM) + 6))
            self._floor_edits.append(((bx - 0.5, by - 0.5, bw + 1.5, bh + 1.5), P["concrete"], 0))
        if getattr(cmap, "bail_desk", None) is not None:      # (and the precinct desk: it's 3D too)
            bx, by, bw, bh = cmap.bail_desk
            self.floor_map.fill(FA.PRECINCT_LINO, (int(bx * FLOOR_PPM) - 2, int(by * FLOOR_PPM) - 2,
                                                  int(bw * FLOOR_PPM) + 6, int(bh * FLOOR_PPM) + 12))
            self._floor_edits.append(((bx - 0.5, by - 0.5, bw + 1.5, bh + 3.0), FA.PRECINCT_LINO, 0))
        # (v0.9) the shop has a roof now: its floor is in the shade
        gx, gy, gw, gh = cmap.garage_rect
        shadow = pygame.Rect(int(gx * FLOOR_PPM), int(gy * FLOOR_PPM), int(gw * FLOOR_PPM), int(gh * FLOOR_PPM))
        self.floor_map.fill((200, 200, 212), shadow, special_flags=pygame.BLEND_RGB_MULT)
        self._floor_edits.append(((gx, gy, gw, gh), (200, 200, 212), pygame.BLEND_RGB_MULT))
        # (v0.14) the garages you can buy are proper buildings now, roofs and all: every roof is
        # (key, floor rect) -- "home", or the fence shop's index into cmap.fence_shops. (v0.19) The
        # textures are made per world scale by _roofs()
        self._roof_rects = [("home", cmap.garage_rect)]
        for i, fs in enumerate(getattr(cmap, "fence_shops", ())):
            if fs.get("rect") is None:
                continue
            fx, fy, fw, fh = fs["rect"]
            self.floor_map.fill((200, 200, 212), pygame.Rect(int(fx * FLOOR_PPM), int(fy * FLOOR_PPM),
                                int(fw * FLOOR_PPM), int(fh * FLOOR_PPM)), special_flags=pygame.BLEND_RGB_MULT)
            self._floor_edits.append(((fx, fy, fw, fh), (200, 200, 212), pygame.BLEND_RGB_MULT))
            self._roof_rects.append((i, fs["rect"]))
        self._roof_sets = {}
        # (v0.19) the hi-res street: the automap's own 5 px/m surface (live: its skid marks and
        # labels come along), cut into FLOOR_CHUNK_M chunks at 5 x kw px/m on demand, LRU by bytes
        self._map_src = map_surf
        self._chunks = OrderedDict()          # (ix, iy, kw) -> Surface
        self._chunk_bytes = 0
        self._chunk_budget = 0                # chunks still allowed to be built this frame
        self._detail_tiles = {}               # (tile kind, variant, px) -> Surface
        self._skid_log = {}                   # (ix, iy) -> deque of (x0, y0, x1, y1) in metres
        self._crop_cache = {}
        self.cam_box = None           # (v0.14) the building (walls included) whose roof the camera's under
        self.roof_layer = pygame.Surface((vw, vh)).convert()
        self.roof_layer.set_colorkey(ROOF_KEY)
        self.roof_clip = None         # per column: (depth where the roof ends, screen row it ends on)
        # (v0.10) one fraction per front tile-column (7: a walking door, 4 bays, 2 solid
        # piers) instead of one shared value -- each of the shop's 5 doors moves on its own.
        self.door_open = [1.0] * (C.BLOCK_TILES - 2)
        # tall enough to look up into. (v0.19) Painted at the world scale the first time it's
        # needed (FA.make_sky's sc): same clouds, lit edges and single-pixel stars at 2x/3x
        self._sky_base_h = int(vh // self.ks * 0.95)
        self.sky_h = self._sky_base_h * self.kw
        self.skies = {}
        self.hires = None             # the car the chase camera is following: drawn in more detail
        self.big_heads = False        # F9. You know you want to.
        self.disco = False            # F10: the floor gets a hue-cycling tint. Purely cosmetic.
        self.fisheye = False          # F8: a wider, wobblier FOV, like a cheap dashcam.
        self._build_static_sprites()
        # (v0.17) cars, people and props share one byte-budgeted cache (they used to be three
        # dicts, two of them cleared wholesale at 4000 entries and one never cleared at all)
        self.sprites = SpriteCache(C.SPRITE_CACHE_MB)
        self.car_cache = self.person_cache = self.model_cache = self.sprites
        self.icon_big = {}
        self.particles = []
        self.explosions = []
        self.tracers = []          # [x0, y0, x1, y1, weapon, life]
        self.skid_prev = {}
        self.flash = None          # (colour, strength)
        self.shake = 0.0
        self.zbuf = [1e9] * vw
        # per-frame fog/darkness overlay for the floor and for sprites
        self._fog_rows = None
        self._fog_key = None
        self.person_keys = {}
        self.pops = set()             # cars that backfired since the last frame
        # (v0.9) cosmetic sillies: hats knocked off, pigeons, cars in the air
        self.hat_off = set()          # npc ids whose hat is in the road now
        self.flying_hats = []         # [x, y, z, vx, vy, vz, spin, style, life]
        self.air_t0 = {}              # car id -> (time it left the ramp, hang time)
        self.trunk_pop = {}           # (v0.10) car id -> how open its boot is (0..1), local eye candy only
        self._init_pigeons()

    # ------------------------------------------------------------------ setup
    def set_fov(self, degrees):
        """(v0.17) The settings slider: horizontal field of view in degrees, clamped to
        FOV_MIN..FOV_MAX. The F8 fisheye wobbles around whatever this is."""
        self.fov = math.radians(clamp(float(degrees), C.FOV_MIN, C.FOV_MAX))
        self._apply_fov(self.fov)

    def set_scale(self, scale):
        """(v0.17) Change the render scale in place (the settings screen, mid-game). Keeps the
        skid marks, the particles and the sprite cache (it's keyed by px/m, not screen size)."""
        scale = max(1, int(scale))
        if scale == self.ks:
            return
        bw, bh = self.vw // self.ks, self.vh // self.ks
        self.ks = self.cstep = scale
        self.vw, self.vh = bw * scale, bh * scale
        self.hor0 = self.hor = self.vh // 2
        self.view = pygame.Surface((self.vw, self.vh)).convert()
        self.roof_layer = pygame.Surface((self.vw, self.vh)).convert()
        self.roof_layer.set_colorkey(ROOF_KEY)
        self.roof_clip = None
        self.zbuf = [1e9] * self.vw
        self._fog_key = None
        self._lo = None
        if self.kw > scale:                  # (v0.19) the world can't be sharper than the view
            self.set_world_scale(scale)
        self._apply_fov(self._cur_fov)

    def set_world_scale(self, w):
        """(v0.19) The settings screen's WORLD DETAIL: walls, street, ceilings and sky at w x 640,
        with textures built at w x their old density. Clamped to WORLD_SCALE_MIN..MAX and to the
        render scale. Safe mid-game: textures, skies and floor chunks are made lazily per scale
        (the old scale's floor chunks and skies are dropped; wall textures age out of their LRU).
        Returns the scale actually used."""
        try:
            w = int(w)
        except (TypeError, ValueError):
            w = C.WORLD_SCALE_DEFAULT
        w = max(C.WORLD_SCALE_MIN, min(C.WORLD_SCALE_MAX, self.ks, w))
        if w == self.kw:
            return w
        self.kw = w
        self.sky_h = self._sky_base_h * w
        self.skies = {}
        self._chunks.clear()
        self._chunk_bytes = 0
        self._crop_cache.clear()
        self._lo = None
        self._fog_key = None
        self._apply_fov(self._cur_fov)
        return w

    def _apply_fov(self, fov):
        """Everything that hangs off the FOV: the focal length D and one ray slope per wall column
        (v0.19: one per WORLD column, kw x 640 of them, aimed through the middle of each)."""
        self._cur_fov = fov
        self.tanh = math.tan(fov / 2)
        self.D = (self.vw / 2) / self.tanh
        n = self.vw // self.ks * getattr(self, "kw", 1)
        self.ray_k = [(2.0 * (x + 0.5) / n - 1.0) * self.tanh for x in range(n)]

    def _build_walls(self):
        """Every wall tile gets a texture id and a height. Buildings keep one
        height and style across all their tiles, so they read as buildings."""
        cm = self.map
        n = cm.n
        self.wall_def = [None]                     # index 0 = no wall
        self.inner_plain = {}                      # sign wall -> the same wall without the sign (back face)
        self.wall_of = [0] * (n * n)
        self.tex_cache = OrderedDict()             # (did, night, world scale) -> WallTex, LRU
        defs = {}

        def def_id(key):
            if key not in defs:
                defs[key] = len(self.wall_def)
                self.wall_def.append(key)
            return defs[key]
        for bi, (tx, ty, tw, th, style) in enumerate(cm.buildings):
            floors = 3 + (tx * 7 + ty * 13 + cm.seed) % 4
            for y in range(ty, ty + th):
                for x in range(tx, tx + tw):
                    variant = (x * 5 + y * 3 + cm.seed) % 3
                    self.wall_of[y * n + x] = def_id(("bld", style, floors, variant))
        ox, oy, b, _ = cm.garage_tiles
        mid = ox + b // 2
        pt = cm.precinct_tiles if cm.precinct_outer is not None else None
        for y in range(n):
            for x in range(n):
                if cm.tiles[y * n + x] == M.WALL:
                    if pt is not None and pt[0] <= x < pt[0] + pt[2] and pt[1] <= y < pt[1] + pt[3]:
                        # the police station: POLICE either side of the front gate
                        door = pt[0] + pt[2] // 2
                        sign = 1 if (y == pt[1] + pt[3] - 1 and abs(x - door) == 1) else 0
                        self.wall_of[y * n + x] = def_id(("precinct", sign))
                        if sign:
                            # the sign faces the street; from inside the lockup it's just wall
                            self.inner_plain[def_id(("precinct", 1))] = def_id(("precinct", 0))
                        continue
                    sign = x - (mid - 1) if (y == oy and mid - 1 <= x <= mid + 1) else -1
                    if y == oy + b - 1 and ox < x < ox + b - 1:
                        # (v0.12.1) the two front piers between the bays carry the shop's name on
                        # the parapet, facing the street; from inside they're just brick
                        k = x - (ox + 1) - 3
                        self.wall_of[y * n + x] = def_id(("pier", k))
                        self.inner_plain[def_id(("pier", k))] = def_id(("brick", -1))
                        continue
                    self.wall_of[y * n + x] = def_id(("brick", sign))
        # (v0.14) the garages you buy: their name on the parapet either side of the opening
        # (street side only), and the opening itself, so the ray march can put brick above it
        self.fence_gap = set()
        for i, fs in enumerate(getattr(cm, "fence_shops", ())):
            t = fs.get("tiles")
            if t is None:
                continue
            x0, y0, w, h = t
            row = y0 + h - 1
            for x in range(x0 + 2, x0 + w - 2):
                self.fence_gap.add((x, row))
            for x in (x0 + 1, x0 + w - 2):
                self.wall_of[row * n + x] = def_id(("fsign", i + 1))
            self.inner_plain[def_id(("fsign", i + 1))] = def_id(("brick", -1))
        self.edge_def = def_id(("concrete",))
        self.jamb_def = def_id(("brick", -1))       # (v0.12.1) the walking door's jambs
        self.walk_def = def_id(("walkdoor",))       # ...and the door itself, shut
        gx0 = (ox + 1) * T
        self.walk_col = C.DOOR_COLS[0]
        self.walk_cx = gx0 + (self.walk_col + 0.5) * T
        # (v0.9) the roller door: not a tile, a line between the shop's last covered row and the
        # apron. The ray march checks for it when it steps across that line (see _walls)
        self.door_rows = (oy + b - 2, oy + b - 1)
        self.door_cols = (ox + 1, ox + b - 2)
        # (v0.10) HONK TO OPEN, across bay 0 and bay 1 (config.DOOR_COLS[1], [2] -- the first
        # two bay doors, sitting side by side). It's the remote for every bay door, but a
        # sign across all four would run into the solid pier between the two pairs.
        first, span = C.DOOR_COLS[1], 2
        self.door_defs = []
        for k in range(b - 2):
            sign = 1 if first <= k < first + span else 0
            self.door_defs.append(def_id(("door", k, sign, first)))
            if sign:                                   # ...on the street side only
                self.inner_plain[def_id(("door", k, 1, first))] = def_id(("door", k, 0, first))

    def _wall_tex(self, did, night):
        """(v0.19) At the current world scale kw, cached LRU by bytes (WALL_TEX_MB): a 3x six-storey
        facade shaded at every light level is a few MB, and a long drive sees a lot of facades."""
        sc = self.kw
        key = (did, night, sc)
        cache = self.tex_cache
        wt = cache.get(key)
        if wt is not None:
            cache.move_to_end(key)
            return wt
        d = self.wall_def[did]

        def put_sign(surf, sign, x, y):
            # the lettering stays the 3x5 font at its old size, just in chunkier pixels
            if sc > 1:
                sign = pygame.transform.scale_by(sign, sc)
            surf.blit(sign, (x * sc, y * sc))
        if d[0] == "bld":
            surf = FA.facade(d[1], d[2], d[3], night, sc)
        elif d[0] == "precinct":
            surf = FA.precinct_wall(64, night, sc)
            if d[1]:
                sign = pygame.Surface((FA.TEX, 10), pygame.SRCALPHA)
                sign.fill((30, 60, 150))
                self.font.draw(sign, "POLICE", FA.TEX // 2, 2, P["white"], None, align="center")
                put_sign(surf, sign, 0, 14)
        elif d[0] == "door":
            surf = FA.roller_door(d[1], night, sc)
            first = d[3]
            if d[2]:
                sign = pygame.Surface((FA.TEX * 2, 9), pygame.SRCALPHA)
                self.font.draw(sign, "HONK", FA.TEX * 2 // 2, 1, (250, 232, 80), (0, 0, 0),
                               align="center")
                put_sign(surf, sign, -(d[1] - first) * FA.TEX, 18)
        elif d[0] == "brick":
            # (the back wall's sign faces both ways, so it sits below the ceiling line --
            # 3 to 4.75 m up -- rather than being sliced in half by the roof from inside)
            sy = FACADE_PX - int(4.75 * FA.TEX / 4)
            surf = FA.brick_wall(FACADE_PX, night, sign=d[1] >= 0, sign_y=sy, sc=sc)
            if d[1] >= 0:
                sign = pygame.Surface((FA.TEX * 3, 12), pygame.SRCALPHA)
                self.font.draw(sign, "CHOP SHOP", FA.TEX * 3 // 2, 3, P["gold"], (0, 0, 0), align="center")
                put_sign(surf, sign, -d[1] * FA.TEX, sy + 2)
        elif d[0] == "pier":
            surf = FA.brick_wall(FACADE_PX, night, sign=True, sc=sc)
            sign = pygame.Surface((FA.TEX * 2, 12), pygame.SRCALPHA)
            self.font.draw(sign, "CHOP SHOP", FA.TEX, 3, P["gold"], (0, 0, 0), align="center")
            put_sign(surf, sign, -d[1] * FA.TEX, 12)
        elif d[0] == "walkdoor":
            surf = FA.walk_door(FACADE_PX, night, sc)
        elif d[0] == "fsign":
            surf = FA.brick_wall(FACADE_PX, night, sign=True, sc=sc)
            sign = pygame.Surface((FA.TEX, 12), pygame.SRCALPHA)
            self.font.draw(sign, "SHOP %d" % (d[1] + 1), FA.TEX // 2, 3, P["gold"], (0, 0, 0), align="center")
            put_sign(surf, sign, 0, 12)
        else:
            surf = FA.concrete_wall(48, night, sc)
        wt = cache[key] = FA.WallTex(surf)
        self._trim_tex_cache()
        return wt

    def _trim_tex_cache(self):
        budget = C.WALL_TEX_MB * 1024 * 1024
        cache = self.tex_cache
        total = sum(t.bytes for t in cache.values())
        while total > budget and len(cache) > C.WALL_TEX_KEEP:
            _k, old = cache.popitem(last=False)
            total -= old.bytes

    def wall_tex_bytes(self):
        """(v0.19) What the wall textures weigh right now (tests, the harness)."""
        return sum(t.bytes for t in self.tex_cache.values())

    def wall_height(self, did):
        d = self.wall_def[did]
        if d[0] == "bld":
            return d[2] * FA.FLOOR_M
        if d[0] == "precinct":
            return 8.0
        if d[0] == "door":
            return C.ROOF_H                 # a bay door fills its opening; the lintel sits on top
        return C.SHOP_FACADE_H              # (v0.12.1) the shop's walls rise past the roof as a parapet

    def _build_static_sprites(self):
        cm = self.map
        n = cm.n
        rng = random.Random(cm.seed)
        self.tree_imgs = [FA.make_tree(rng) for _ in range(4)]
        self.lamp_img = {False: FA.make_lamp(False), True: FA.make_lamp(True)}
        self.cam_img = FA.make_camera_pole()
        self.chute_img = FA.make_chute()
        statics = []
        for ty in range(n):
            for tx in range(n):
                if cm.tiles[ty * n + tx] == M.TREE:
                    statics.append(((tx + 0.5) * T, (ty + 0.5) * T, "tree", (tx * 3 + ty) % 4))
        for (x, y) in cm.lamps:
            statics.append((x, y, "lamp", 0))
        for (x, y) in cm.cameras:
            statics.append((x, y, "cam", 0))
        # bucket them in 24 m cells so we only look at the ones nearby
        self.static_cells = {}
        for sp in statics:
            key = (int(sp[0] // 24), int(sp[1] // 24))
            self.static_cells.setdefault(key, []).append(sp)
        self.crates = list(getattr(cm, "market", ()))
        # (v0.12.1) the fence shops were invisible on the client until now: their crate rows and
        # a FOR SALE board by each one. Which ones the crew owns comes in the snapshot header.
        self.fence_crates = [(x, y, item, i + 1) for i, fs in enumerate(getattr(cm, "fence_shops", ()))
                             for (x, y, item) in fs["market"]]
        self.fence_signs = [(fs["sign"][0], fs["sign"][1], i + 1) for i, fs in enumerate(getattr(cm, "fence_shops", ()))]
        self.sign_cache = {}
        # (v0.12.1) the people who stay put: the staff behind the counters, and the story NPCs
        # (name, x, y, facing, outfit, is it somebody you can talk to)
        self.fixed_people = [(nm, x, y, f, o, False) for (nm, x, y, f, o) in getattr(cm, "staff", ())]
        self.fixed_people += [(nm, x, y, f, o, True) for (_k, nm, x, y, f, o) in getattr(cm, "story_npcs", ())]
        self.benches = []
        for rect, is_sell in ((cm.sell_bench, True), (cm.tune_bench, False)):
            bx, by, bw, bh = rect
            self.benches.append((bx + bw / 2, by + bh / 2, is_sell, bw, bh))
        # (v0.14) each garage you can buy has its own tune-up counter, long side down the east wall
        for fs in getattr(cm, "fence_shops", ()):
            if fs.get("bench") is not None:
                bx, by, bw, bh = fs["bench"]
                self.benches.append((bx + bw / 2, by + bh / 2, False, bw, bh))
        # (v0.14) the contacts (drop-off orders, car buyers) and the records clerk at the precinct
        self.contacts = [(nm, x, y, f, FA.contact_outfit(nm), i)
                         for i, (nm, x, y, f) in enumerate(getattr(cm, "contacts", ()))]
        rec = getattr(cm, "records", None)
        if rec is not None:
            self.fixed_people.append(("RECORDS", rec[0], rec[1] - 0.85, math.pi / 2, "records", True))
        self.records = rec
        # (v0.9) the precinct: cell bars in short straight runs, and the front desk
        self.bar_segs = []
        for (bx, by, bw, bh) in getattr(cm, "cell_bars", ()):
            along_x = bw > bh
            length = bw if along_x else bh
            n = max(1, int(math.ceil(length / 2.0)))
            seg = length / n
            for k in range(n):
                if along_x:
                    self.bar_segs.append((bx + (k + 0.5) * seg, by + bh / 2, math.pi / 2, round(seg, 2)))
                else:
                    self.bar_segs.append((bx + bw / 2, by + (k + 0.5) * seg, 0.0, round(seg, 2)))
        self.desk = None
        if getattr(cm, "bail_desk", None) is not None:
            bx, by, bw, bh = cm.bail_desk
            self.desk = (bx + bw / 2, by + bh / 2, bw, bh)

    # ------------------------------------------------------------------ sprites
    def _mip(self, base):
        """(v0.17) Which pixels-per-metre to build a box sprite at: its old density (`base`)
        doubled until it covers what the screen shows (self._spx, set by the draw loop), up to
        SPRITE_DETAIL x. Returns (ppm, outline px): the top mip gets a 2 px outline so the
        boxes keep their dark edges instead of a hairline."""
        want = self._spx * C.SPRITE_MIP_BIAS
        top = base * C.SPRITE_DETAIL
        ppm = base
        while ppm < want and ppm < top:
            ppm *= 2
        ppm = min(ppm, top)
        return ppm, max(1, ppm // (2 * base))

    def _car_sprite(self, row, az, steps=None, base=12):
        ppm, ow = self._mip(base)
        steps = steps or C.CAR_ANGLES
        (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, drv, psg, dmg,
         model, livery, extras, extras2) = row[:19]
        idx = int(round(az / (TWO_PI / steps))) % steps
        lights = 0
        if extras2 & PR.CX_COPCAR:
            kind = S.COP                                 # (v0.9) nicked, but it still looks the part...
            if flags & PR.CF_HORN:
                lights |= self._phase                    # ...and the siren's the horn now
        elif kind == S.COP and not extras2 & PR.CX_PATROL:
            lights |= self._phase
        if flags & PR.CF_ALARM and self._phase:
            lights |= 2
        if extras & 8:
            lights |= 4                                  # NOS: blue fire out the back
        key = (kind, color, mask, styles, dmg, lights, idx, model, livery, extras & 0xF8, extras2 & 1, steps, ppm)
        # (the hop: hydraulics are drawn as the whole sprite bouncing, see the car loop)
        spr = self.sprites.get(key)
        if spr is None:
            spr = self.sprites.put(key, FA.render_boxes(
                FA.car_boxes(kind, color, mask, styles, dmg, lights, model, livery, extras, extras2),
                idx * TWO_PI / steps, ppm, outline=ow))
        return spr, ppm

    OUTFIT_OF = {S.OFFICER: "officer", S.GUARD: "guard", S.KEYGUARD: "keyguard", S.STREAKER: "streaker"}

    def _person_look(self, eid, kind):
        k = self.person_keys.get((eid, kind))
        if k is None:
            r = random.Random(eid * 7919)
            if kind == S.CLOWN:
                k = ((250, 250, 250), (250, 240, 235), (255, 120, 40), "clown", None)
            elif kind == S.OWNER:
                k = ((236, 150, 190), r.choice(SKINS), r.choice(HAIRS), "owner", None)
            elif kind == S.MIME:
                k = ((240, 240, 240), (246, 246, 246), (20, 20, 24), None, "mime")
            else:
                outfit = self.OUTFIT_OF.get(kind)
                if kind == S.PED and r.random() < 0.35:
                    outfit = "hat%d" % r.randrange(FA.CIV_HATS)      # (v0.9) and it'll come off
                k = (r.choice(SHIRTS), r.choice(SKINS), r.choice(HAIRS), None, outfit)
            self.person_keys[(eid, kind)] = k
        return k

    def _board(self, which):
        """(v0.14) a sandwich board on a post: the records hatch's."""
        img = self.sign_cache.get(which)
        if img is None:
            w, h = 44, 40
            img = pygame.Surface((w, h), pygame.SRCALPHA)
            img.fill(P["metal"], (w // 2 - 1, 18, 3, h - 18))
            img.fill(P["ink"], (0, 0, w, 20))
            img.fill((40, 60, 150), (1, 1, w - 2, 18))
            self.font.draw(img, "RECORDS", w // 2, 3, P["white"], None, align="center")
            self.font.draw(img, "PAPERS", w // 2, 11, P["gold"], None, align="center")
            img = self.sign_cache[which] = img
        return img

    def _sale_sign(self, idx, owned):
        """(v0.12.1) the board outside a fence shop: FOR SALE and the price, or whose it is.
        (v0.14: owned is 0 for sale, 1 bought but still full of junk, 2 open)"""
        key = (idx, owned)
        img = self.sign_cache.get(key)
        if img is None:
            w, h = 44, 46
            img = pygame.Surface((w, h), pygame.SRCALPHA)
            img.fill(P["metal"], (w // 2 - 1, 18, 3, h - 18))                     # the post
            board = (40, 110, 60) if owned else (230, 226, 214)
            img.fill(P["ink"], (0, 0, w, 20))
            img.fill(board, (1, 1, w - 2, 18))
            if owned:
                self.font.draw(img, "SHOP %d" % (idx + 1), w // 2, 3, P["white"], None, align="center")
                self.font.draw(img, "OURS NOW" if owned == 2 else "CLEAR IT", w // 2, 11, P["gold"], None,
                               align="center")
            else:
                self.font.draw(img, "FOR SALE", w // 2, 3, (190, 30, 40), None, align="center")
                self.font.draw(img, "$" + "{:,}".format(C.SHOP_PRICE[idx]), w // 2, 11, P["ink"], None,
                               align="center")
            img = self.sign_cache[key] = img
        return img

    def _person_sprite(self, shirt, skin, hair, frame, extra, down, az, gun=0, outfit=None, char=None):
        n = C.PERSON_ANGLES
        idx = int(round(az / (TWO_PI / n))) % n
        ppm, ow = self._mip(16)
        key = (shirt, skin, hair, frame, extra, down, idx, gun, self.big_heads, outfit, char, ppm)
        spr = self.sprites.get(key)
        if spr is None:
            boxes = FA.person_boxes(shirt, skin, hair, 0 if frame == 2 else frame, extra, gun=gun, outfit=outfit, char=char)
            if frame == 2:
                boxes = FA.seated(boxes)                # (v0.13) frame 2 = on a motorbike
            if self.big_heads:
                boxes = FA.big_head(boxes)
            if down:
                boxes = FA.lying(boxes)
            spr = self.sprites.put(key, FA.render_boxes(boxes, idx * TWO_PI / n, ppm, outline=ow))
        return spr, ppm

    def _dog_sprite(self, frame, trousers, down, az):
        n = C.PERSON_ANGLES
        idx = int(round(az / (TWO_PI / n))) % n
        ppm, ow = self._mip(20)
        key = ("dog", frame, trousers, down, idx, ppm)
        spr = self.sprites.get(key)
        if spr is None:
            boxes = FA.dog_boxes(frame, trousers)
            if down:
                boxes = [(x0, x1, y0, y1, z0 * 0.4, z1 * 0.4, c) for x0, x1, y0, y1, z0, z1, c in boxes]
            spr = self.sprites.put(key, FA.render_boxes(boxes, idx * TWO_PI / n, ppm, outline=ow))
        return spr, ppm

    def _model_sprite(self, name, boxes_fn, az, steps=None, base=16):
        """A prop's box model from the angle it's seen at. `base` is its old px per metre:
        (v0.17) the mip it's actually built at is up to SPRITE_DETAIL x that (see _mip)."""
        steps = C.PROP_ANGLES if not steps or steps == 8 else steps     # (v0.8: 8 was choppy up close)
        idx = int(round(az / (TWO_PI / steps))) % steps
        ppm, ow = self._mip(base)
        key = (name, idx, steps, ppm)
        spr = self.sprites.get(key)
        if spr is None:
            spr = self.sprites.put(key, FA.render_boxes(boxes_fn(), idx * TWO_PI / steps, ppm, outline=ow))
        return spr, ppm

    def _icon(self, bank, idx):
        ic = self.icon_big.get(idx)
        if ic is None:
            ic = self.icon_big[idx] = bank.icons[idx]
        return ic

    # ------------------------------------------------------------------ effects
    def on_sfx(self, sid, x, y, me_x, me_y, me_car):
        d = math.hypot(x - me_x, y - me_y)
        near = max(0.0, 1.0 - d / 40.0)
        if sid in (S.S_CRASH, S.S_CRASH_BIG):
            big = sid == S.S_CRASH_BIG
            self.burst(SPARK, x, y, 1.0, 16 if big else 8, 12, 0.4)
            self.burst(DEBRIS, x, y, 0.8, 6 if big else 2, 6, 0.8, P["metal_l"])
            self.shake = max(self.shake, (6 if big else 3) * near)
            if near > 0.8:
                self.flash = ((255, 40, 30), 120 if big else 60)
        elif sid == S.S_BOOM:
            self.explosions.append([x, y, 0.0])
            self.burst(FIRE, x, y, 1.0, 50, 14, 0.9)
            self.burst(SMOKE, x, y, 1.5, 30, 5, 2.2)
            self.burst(SPARK, x, y, 1.0, 30, 20, 0.6)
            self.shake = max(self.shake, 10 * max(near, 0.3))
            if near > 0.5:
                self.flash = ((255, 180, 60), 150)
        elif sid == S.S_BREAKIN:
            self.burst(DEBRIS, x, y, 1.2, 12, 4, 0.5, P["glass"])
        elif sid == S.S_HONK:
            for c in CONFETTI_COLS:
                self.burst(CONFETTI, x, y, 1.2, 4, 6, 1.2, c)
        elif sid in (S.S_STRIP, S.S_INSTALL):
            self.burst(SPARK, x, y, 0.7, 6, 5, 0.25)
        elif sid == S.S_CRUSH:
            self.burst(DUST, x, y, 0.5, 30, 7, 1.2)
            self.shake = max(self.shake, 4 * near)
        elif sid == S.S_IGNITE:
            self.burst(FIRE, x, y, 1.2, 20, 5, 0.6)
        elif sid in (S.S_SELL, S.S_PICKUP, S.S_BUY):
            if d < 4:
                self.flash = ((255, 220, 90), 55)          # the classic "you picked something up" glow
            if sid == S.S_SELL:
                self.burst(CONFETTI, x, y, 1.2, 8, 4, 0.8, P["money"])
        elif sid == S.S_YELP and d < 2.5:
            self.flash = ((255, 40, 30), 90)
        elif sid == S.S_ARREST and d < 3:
            self.flash = ((80, 120, 255), 140)
        elif sid == S.S_TIRE:
            self.burst(DEBRIS, x, y, 0.4, 10, 5, 0.8, P["tire"])
            self.burst(SMOKE, x, y, 0.4, 4, 2, 0.8)
        elif sid == S.S_TRAP:
            self.burst(DUST, x, y, 0.3, 10, 3, 0.6)
        elif sid == S.S_PUNCH and d < 2.5:
            self.shake = max(self.shake, 1.5)
        elif sid == S.S_ROB:
            self.burst(CONFETTI, x, y, 1.0, 6, 3, 0.7, P["money"])
        elif sid == S.S_CONFETTI:
            for col in ((255, 80, 80), (80, 200, 255), (255, 220, 60), (120, 255, 120), (255, 120, 220)):
                self.burst(CONFETTI, x, y, 2.2, 14, 6, 2.2, col)
        elif sid == S.S_FLASH and d < 25:
            self.flash = ((255, 255, 255), 200)            # SMILE!
        elif sid == S.S_TASER:
            self.burst(SPARK, x, y, 1.2, 6, 3, 0.2)
        elif sid in (S.S_PISTOL, S.S_SHOTGUN) and d < 1.0:
            self.shake = max(self.shake, 2.5 if sid == S.S_SHOTGUN else 1.0)    # your own shot
        elif sid == S.S_FEATHERS:
            self.burst(CONFETTI, x, y, 0.5, 26, 5, 2.4, (246, 244, 236))    # (v0.9) feathers. So many feathers
            self.burst(CONFETTI, x, y, 0.5, 4, 4, 1.5, (220, 40, 40))
        elif sid == S.S_CASH:
            self.burst(CONFETTI, x, y, 1.4, 30, 6, 2.0, P["money"])
        elif sid == S.S_PFFT:
            self.burst(DUST, x, y, 0.2, 8, 1.5, 0.9)
        if sid in (S.S_PISTOL, S.S_SHOTGUN, S.S_BOOM, S.S_HONK, S.S_CRASH_BIG, S.S_PFFT):
            self._scare_pigeons(x, y, 30.0)

    def on_shot(self, weapon, x0, y0, x1, y1):
        """A bullet's path, from the server. A streak, sparks where it landed."""
        self.tracers.append([x0, y0, x1, y1, weapon, 0.07 if weapon == S.ARM_PISTOL else
                             0.35 if weapon == S.TRACER_TASER else 0.05])
        self.burst(SPARK, x1, y1, 1.1, 3 if weapon == S.ARM_SHOTGUN else 5, 5, 0.25)
        self.emit(FIRE, x0, y0, 1.35, 0, 0, 0, 0.06)          # muzzle flash (for other people's guns)

    def emit(self, kind, x, y, z, vx, vy, vz, life, color=None):
        if len(self.particles) < 600:
            self.particles.append([x, y, z, vx, vy, vz, life, life, kind, color])

    def burst(self, kind, x, y, z, n, speed, life, color=None):
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, TWO_PI)
            s = r.uniform(0.3, 1.0) * speed
            self.emit(kind, x, y, z, math.cos(a) * s, math.sin(a) * s, r.uniform(0.5, 1.2) * speed * 0.5,
                      life * r.uniform(0.6, 1.2), color)

    # ------------------------------------------------------------------ main draw
    def draw(self, view, cam, me_pid, now, dt, day_left, bank, hide_car=None, pitch=0, hires=None):
        """cam = (x, y, yaw, eye_height); pitch = pixels the horizon moves down
        (looking up) or up (negative, looking down). Draws into self.view."""
        cx, cy, yaw, eye = cam
        self.hor = int(clamp(self.hor0 + pitch, 6, self.vh - 6))
        self.hires = hires
        # (v0.12, F8) fisheye: a wider FOV that wobbles like a cheap dashcam suction mount.
        # Recomputing ray_k (one float per column) is cheap enough to do every frame; snaps
        # straight back to self.fov -- and only rebuilds once more -- the moment it's off.
        # (v0.17: around the settings FOV, and capped at 170 -- tan() of 180 is a very bad day)
        want_fov = min(math.radians(170.0), self.fov + math.radians(35.0 + 18.0 * math.sin(time.perf_counter() * 1.3))) \
            if self.fisheye else self.fov
        if want_fov != self._cur_fov:
            self._apply_fov(want_fov)
        if self.shake > 0.05:
            yaw += self.rng.uniform(-0.01, 0.01) * self.shake
            eye += self.rng.uniform(-0.02, 0.02) * self.shake
            self.shake *= math.exp(-dt * 8)
        self._phase = int(now * 6) % 2
        tod = time_of_day(day_left)
        dark = darkness(tod)
        night = dark > 0.55
        self._skids(view)
        surf = self.view
        for t in getattr(view, "traps", {}).values():
            if t[1] == S.TRAP_DOOR:
                i = t[0] - C.DOOR_ID
                if 0 <= i < len(C.DOOR_COLS):
                    self.door_open[C.DOOR_COLS[i]] = t[5]
        # (v0.12.1) under the roof, nothing above ROOF_H can be seen -- the ceiling's in the
        # way -- so the parapet and the bay lintels needn't be drawn at all (they were ~40% of
        # the frame in there, all of it painted over a moment later by _roof)
        self.cam_box = self._roof_box(cx, cy)
        self.cam_inside = self.cam_box is not None
        self._chunk_budget = C.FLOOR_CHUNKS_PER_FRAME
        self._world_pass(cx, cy, yaw, eye, dark, night, tod)
        self._sprites(surf, view, cx, cy, yaw, eye, me_pid, now, dt, dark, night, bank, hide_car)
        self._tracers(surf, cx, cy, yaw, eye, dt)
        self._particles(surf, cx, cy, yaw, eye, dt)
        if self.flash is not None:
            col, a = self.flash
            ov = pygame.Surface((self.vw, self.vh), pygame.SRCALPHA)
            ov.fill(col + (int(a),))
            surf.blit(ov, (0, 0))
            a -= dt * 400
            self.flash = (col, a) if a > 4 else None
        return surf

    def _world(self, surf, cx, cy, yaw, eye, dark, night, tod):
        """The static world: sky, street, walls, ceilings. Fills self.zbuf and roof_clip."""
        self._sky(surf, yaw, tod)
        self._floor(surf, cx, cy, yaw, eye, dark)
        self._walls(surf, cx, cy, yaw, eye, dark, night)
        self._roof(surf, cx, cy, yaw, eye)

    def _world_pass(self, cx, cy, yaw, eye, dark, night, tod):
        """(v0.19) The static world at the world scale kw: straight into the view when kw == ks,
        otherwise at kw x 640 into a side surface that's blown up to the view (kw = 1 is v0.17's
        _world_lowres: the old 640x328 world under full-res sprites). Works by pointing the
        renderer's screen geometry at the small surface for the duration. Afterwards zbuf and
        roof_clip are in view columns again, with self.cstep view columns per wall ray."""
        ks, kw = self.ks, self.kw
        if kw >= ks:
            self.cstep = 1
            self._world(self.view, cx, cy, yaw, eye, dark, night, tod)
            return
        bw, bh = self.vw // ks * kw, self.vh // ks * kw
        lo = self.__dict__.get("_lo")
        if lo is None or lo["surf"].get_size() != (bw, bh):
            lo = self._lo = {"surf": pygame.Surface((bw, bh)).convert(), "zbuf": [1e9] * bw,
                             "roof": pygame.Surface((bw, bh)).convert(), "fog": (None, None)}
            lo["roof"].set_colorkey(ROOF_KEY)
        hi = (self.vw, self.vh, self.hor, self.D, self.zbuf, self.roof_layer, self.sky_h,
              self._fog_key, self._fog_rows)
        hor_lo = self.hor * kw // ks
        self.vw, self.vh, self.hor, self.D = bw, bh, hor_lo, self.D * kw / ks
        self.zbuf, self.roof_layer, self.sky_h = lo["zbuf"], lo["roof"], self._sky_base_h * kw
        self._fog_key, self._fog_rows = lo["fog"]
        self.cstep = 1                           # (ray_k is already one ray per world column)
        try:
            self._world(lo["surf"], cx, cy, yaw, eye, dark, night, tod)
        finally:
            lo["fog"] = (self._fog_key, self._fog_rows)
            (self.vw, self.vh, _h, self.D, self.zbuf, self.roof_layer, self.sky_h,
             self._fog_key, self._fog_rows) = hi
        self.hor = hor_lo * ks // kw             # the sprites plant themselves on the same horizon
        pygame.transform.scale(lo["surf"], (self.vw, self.vh), self.view)
        zlo = lo["zbuf"]
        if ks % kw == 0:
            r = self.cstep = ks // kw
            self.zbuf = [z for z in zlo for _ in range(r)]
            if self.roof_clip is not None:
                ends, rows = self.roof_clip
                self.roof_clip = (ends, [y * r for y in rows])
        else:                                    # (3x view, 2x world: a zbuf entry per view column)
            self.cstep = 1
            src = [x * kw // ks for x in range(self.vw)]
            self.zbuf = [zlo[i] for i in src]
            if self.roof_clip is not None:
                ends, rows = self.roof_clip
                self.roof_clip = ([ends[i] for i in src], [rows[i] * ks // kw for i in src])
        self.lintels = {x * ks // kw: (d, y * ks // kw) for x, (d, y) in self.lintels.items()}

    def _sky_img(self, key):
        """The panorama at the world scale, made on first use. Only the (at most two) skies on
        show are kept: at 3x one is 30 MB."""
        sky = self.skies.get((key, self.kw))
        if sky is None:
            sky = FA.make_sky(key, 4 * (self.vw // self.kw), self._sky_base_h, self.kw)
            if len(self.skies) >= 2:
                self.skies.clear()
            self.skies[(key, self.kw)] = sky
        return sky

    def _sky(self, surf, yaw, tod):
        a, b, t = sky_mix(tod)
        sw = 4 * self.vw
        off = int((yaw % TWO_PI) / TWO_PI * sw)
        for key, alpha in ((a, 255), (b, int(255 * t))):
            if alpha <= 3:
                continue
            sky = self._sky_img(key)
            sky.set_alpha(None if alpha >= 255 else alpha)
            # the sky's bottom edge sits on the horizon, wherever pitch put it
            h = min(self.hor, self.sky_h)
            sy, dy = self.sky_h - h, self.hor - h
            if dy > 0 and alpha >= 255:
                surf.fill(sky.get_at((0, 0))[:3], (0, 0, self.vw, dy))       # above the top of the gradient
            surf.blit(sky, (0, dy), pygame.Rect(off, sy, min(self.vw, sw - off), h))
            if sw - off < self.vw:
                surf.blit(sky, (sw - off, dy), pygame.Rect(0, sy, self.vw - (sw - off), h))
            sky.set_alpha(None)

    def _floor(self, surf, cx, cy, yaw, eye, dark):
        hor, vw, vh, D, th = self.hor, self.vw, self.vh, self.D, self.tanh
        haze = shade((150, 150, 160), 1.0 - 0.8 * dark)
        # (v0.19) at world scale 2+ the rows nearer than FLOOR_DETAIL_DIST come from the hi-res
        # chunks; the far rows (a screen row per metre or worse) stay on the 4 px/m map
        split = vh
        if self.kw > 1:
            near = self._near_floor(cx, cy, yaw)
            if near is not None:
                rot_n, oxn, oyn, ppm_n, dn = near
                split = max(hor + 1, min(vh, int(math.ceil(hor + eye * D / dn - 0.5))))
                self._floor_rows(surf, rot_n, oxn, oyn, ppm_n, split, vh, eye, haze)
        if split > hor + 1:
            R = int(C.FP_FLOOR_DIST * FLOOR_PPM)
            px, py = int(cx * FLOOR_PPM), int(cy * FLOOR_PPM)
            crop = self._crop_cache.get(("base", R))
            if crop is None:
                crop = self._crop_cache[("base", R)] = pygame.Surface((2 * R, 2 * R)).convert()
            crop.fill(P["void"])
            crop.blit(self.floor_map, (0, 0), pygame.Rect(px - R, py - R, 2 * R, 2 * R))
            rot = pygame.transform.rotate(crop, math.degrees(yaw) + 90.0)
            rw, rh = rot.get_size()
            self._floor_rows(surf, rot, rw / 2.0, rh / 2.0, FLOOR_PPM, hor + 1, split, eye, haze)
        self._floor_fog(surf, eye, dark, haze)

    def _floor_rows(self, surf, rot, ox, oy, ppm, r0, r1, eye, haze):
        """Mode 7: screen rows r0..r1-1, each a 1-px slice of the rotated ground `rot` (ppm px/m,
        the camera at (ox, oy), forward = up) stretched across the view."""
        hor, vw, D, th = self.hor, self.vw, self.D, self.tanh
        maxd = C.FP_FLOOR_DIST - 2
        rw, rh = rot.get_size()
        scale = pygame.transform.scale
        sub = rot.subsurface
        blit = surf.blit
        k = eye * D
        hwk = th * ppm
        for r in range(r0, r1):
            d = k / (r - hor + 0.5)
            if d > maxd:
                surf.fill(haze, (0, r, vw, 1))
                continue
            hw = d * hwk
            y = int(oy - d * ppm)
            x0 = int(ox - hw)
            w = max(1, int(2 * hw))
            if y < 0 or x0 < 0 or x0 + w > rw:
                surf.fill(haze, (0, r, vw, 1))
                continue
            blit(scale(sub((x0, y, w, 1)), (vw, 1)), (0, r))

    def _near_floor(self, cx, cy, yaw):
        """(v0.19) The hi-res street around the camera, rotated: (rot, cam x, cam y, px/m, how far
        it reaches) or None. Only a disc covering the view out to FLOOR_DETAIL_DIST is cut out --
        centred ahead of you when that's smaller than centred on you -- so the rotate costs about
        what the 4 px/m one does."""
        ppm = C.PPM * self.kw
        t = self.tanh
        dn = C.FLOOR_DETAIL_DIST
        ahead = dn * (1.0 + t * t) / 2.0          # the circle through the camera and the view's far corners
        around = dn * math.sqrt(1.0 + t * t)
        r, off = (ahead, ahead) if ahead < around else (around, 0.0)
        cap = C.FLOOR_DETAIL_DIST * 1.5            # (F8's 170-degree fisheye: pull the detail in instead)
        if r > cap:
            dn *= cap / r
            off *= cap / r
            r = cap
        r += 1.0
        ca, sa = math.cos(yaw), math.sin(yaw)
        mx, my = cx + ca * off, cy + sa * off      # the disc's centre, in metres
        S = int(2 * r * ppm)
        X0, Y0 = int(mx * ppm) - S // 2, int(my * ppm) - S // 2
        crop = self._crop_cache.get(("near", S))
        if crop is None:
            crop = self._crop_cache[("near", S)] = pygame.Surface((S, S)).convert()
        crop.fill(P["void"])
        cm = C.FLOOR_CHUNK_M
        cpx = int(cm * ppm)
        size_m = self.map.n * T
        ix0, iy0 = max(0, int(X0 // cpx)), max(0, int(Y0 // cpx))
        ix1 = min(int(math.ceil(size_m / cm)) - 1, int((X0 + S) // cpx))
        iy1 = min(int(math.ceil(size_m / cm)) - 1, int((Y0 + S) // cpx))
        for iy in range(iy0, iy1 + 1):
            for ix in range(ix0, ix1 + 1):
                ch = self._floor_chunk(ix, iy)
                if ch is None:                     # (not built yet: the blurry map for a frame or two)
                    ch = self._chunk_stand_in(ix, iy, ppm)
                crop.blit(ch, (ix * cpx - X0, iy * cpx - Y0))
        rot = pygame.transform.rotate(crop, math.degrees(yaw) + 90.0)
        RW, RH = rot.get_size()
        vx, vy = (X0 + S / 2.0) - cx * ppm, (Y0 + S / 2.0) - cy * ppm
        ox = RW / 2.0 - (-vx * sa + vy * ca)
        oy = RH / 2.0 + (vx * ca + vy * sa)
        return rot, ox, oy, ppm, dn

    def _chunk_rect_m(self, ix, iy):
        cm = C.FLOOR_CHUNK_M
        size_m = self.map.n * T
        x0, y0 = ix * cm, iy * cm
        return x0, y0, min(cm, size_m - x0), min(cm, size_m - y0)

    def _chunk_stand_in(self, ix, iy, ppm):
        x0, y0, w, h = self._chunk_rect_m(ix, iy)
        src = self.floor_map.subsurface((int(x0 * FLOOR_PPM), int(y0 * FLOOR_PPM),
                                         int(w * FLOOR_PPM), int(h * FLOOR_PPM)))
        return pygame.transform.scale(src, (int(w * ppm), int(h * ppm)))

    def _detail_tile(self, kind, var, px):
        key = (kind, var, px)
        t = self._detail_tiles.get(key)
        if t is None:
            t = self._detail_tiles[key] = ART.floor_detail_tile(kind, var, px).convert()
        return t

    def _floor_chunk(self, ix, iy):
        """(v0.19) One FLOOR_CHUNK_M square of street at 5 x kw px/m: the automap's pixels blown up
        kw x (so every line, label and skid mark is where it was), with a hi-res detail tile
        showing through wherever the map is plain ground colour, then the same scrubs and shop
        shade as the 4 px/m floor, then this chunk's skid marks replayed. None if this frame has
        already built its FLOOR_CHUNKS_PER_FRAME."""
        kw = self.kw
        key = (ix, iy, kw)
        ch = self._chunks.get(key)
        if ch is not None:
            self._chunks.move_to_end(key)
            return ch
        if self._chunk_budget <= 0:
            return None
        self._chunk_budget -= 1
        ppm = C.PPM * kw
        mp = C.PPM                                  # the automap's px/m
        x0, y0, w, h = self._chunk_rect_m(ix, iy)
        src = self._map_src.subsurface((int(x0 * mp), int(y0 * mp), int(w * mp), int(h * mp)))
        up = pygame.transform.scale_by(src, kw)
        ch = pygame.Surface(up.get_size()).convert()
        ch.blit(up, (0, 0))
        cm = self.map
        n = cm.n
        tp = int(T * ppm)                           # px per tile
        base = ART.tile_base()
        kinds = ART.FLOOR_DETAIL_KINDS
        tx0, ty0 = int(round(x0 / T)), int(round(y0 / T))
        for ty in range(ty0, ty0 + int(round(h / T))):
            for tx in range(tx0, tx0 + int(round(w / T))):
                kind = cm.tiles[ty * n + tx]
                if kind not in kinds:
                    continue
                lx, ly = (tx - tx0) * tp, (ty - ty0) * tp
                ch.blit(self._detail_tile(kind, (tx * 7 + ty * 13) % 4, tp), (lx, ly))
                up.set_colorkey(base[kind])         # ...and the map's own pixels back on top of it
                ch.blit(up, (lx, ly), (lx, ly, tp, tp))
        for (ex, ey, ew, eh), col, flags in self._floor_edits:
            r = pygame.Rect(int((ex - x0) * ppm), int((ey - y0) * ppm), int(ew * ppm), int(eh * ppm))
            ch.fill(col, r, special_flags=flags)
        lw = max(1, int(round(0.25 * ppm)))
        for (ax, ay, bx, by) in self._skid_log.get((ix, iy), ()):
            pygame.draw.line(ch, (38, 38, 46), ((ax - x0) * ppm, (ay - y0) * ppm), ((bx - x0) * ppm, (by - y0) * ppm), lw)
        self._chunks[key] = ch
        nb = ch.get_width() * ch.get_height() * ch.get_bytesize()
        self._chunk_bytes += nb
        budget = C.FLOOR_DETAIL_MB * 1024 * 1024
        while self._chunk_bytes > budget and len(self._chunks) > 9:
            _k, old = self._chunks.popitem(last=False)
            self._chunk_bytes -= old.get_width() * old.get_height() * old.get_bytesize()
        return ch

    def floor_detail_bytes(self):
        """(v0.19) What the hi-res floor chunks weigh right now (tests, the harness)."""
        return self._chunk_bytes

    def _floor_fog(self, surf, eye, dark, haze):
        hor, vw, vh, D = self.hor, self.vw, self.vh, self.D
        # distance haze + night: one pre-made gradient, rebuilt only when the light changes
        key = (round(dark, 2), round(eye, 2), hor)
        if self._fog_key != key:
            self._fog_key = key
            fog = pygame.Surface((1, vh - hor), pygame.SRCALPHA)
            for r in range(vh - hor):
                d = eye * D / (r + 1.5)
                k = C.clamp(d / C.FP_FLOOR_DIST, 0.0, 1.0)
                a = int(255 * min(1.0, k * 0.9 + dark * 0.55))
                fog.set_at((0, r), haze + (a,))
            self._fog_rows = pygame.transform.scale(fog, (vw, vh - hor))
        surf.blit(self._fog_rows, (0, hor + 1))
        if self.disco:
            # (v0.12, F10) a hue-cycling multiply over the floor only -- cheap (one fill, no
            # new surface) and keeps the street's own shading, just recoloured like a dance
            # floor. Doesn't touch the walls or sky: full disco was a bit much even for this.
            hue = (time.perf_counter() * 0.25) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
            surf.fill((int(r * 255), int(g * 255), int(b * 255)), (0, hor + 1, vw, vh - hor - 1),
                     special_flags=pygame.BLEND_RGB_MULT)

    def _walls(self, surf, cx, cy, yaw, eye, dark, night):
        """One ray per world column finds the nearest wall; a 1-px texture column is stretched
        to its height. (v0.19) Two things keep 2x/3x affordable:
          - the grid march (the expensive, Python-heavy bit) runs on every other ray; a ray
            between two that hit the same wall plane can't have been blocked by anything (a
            4 m tile can't hide in a 2-column wedge), so it's solved with one division;
          - neighbouring columns showing the same texel at the same height (a wall up close
            is 5-20 columns per texel) are scaled and blitted as one strip."""
        cm = self.map
        n = cm.n
        wall_of = self.wall_of
        ca, sa = math.cos(yaw), math.sin(yaw)
        rx, ry = -sa, ca
        hor, vh, D = self.hor, self.vh, self.D
        zbuf = self.zbuf
        scale = pygame.transform.scale
        blit = surf.blit
        base_level = int(dark * 5)
        mx0, my0 = int(cx // T), int(cy // T)
        fx0, fy0 = cx / T - mx0, cy / T - my0
        door_open = self.door_open           # (v0.10) one fraction per front column, not one shared value
        dra, drb = self.door_rows
        dc0, dc1 = self.door_cols
        door_defs = self.door_defs
        walk_col, walk_cx, half_walk = self.walk_col, self.walk_cx, C.WALK_DOOR_W / 2
        jamb_def, walk_def, edge_def = self.jamb_def, self.walk_def, self.edge_def
        self.lintels = {}                    # (v0.12.1) column -> (lintel distance, its bottom row)
        fence_gap = self.fence_gap
        cs = self.cstep                      # (v0.17) screen columns per ray: each slice is cs wide

        def cast(dx, dy):
            """The grid march: (did, side, dist, door_at, lintel, plane). plane = (side, step,
            grid line) of a plain wall hit, for the in-between rays; None if anything odd
            (a door, a lintel, the map's edge) was on the way."""
            mx, my = mx0, my0
            ddx = abs(1.0 / dx) if dx else 1e30
            ddy = abs(1.0 / dy) if dy else 1e30
            if dx < 0:
                sx, sdx = -1, fx0 * ddx
            else:
                sx, sdx = 1, (1.0 - fx0) * ddx
            if dy < 0:
                sy, sdy = -1, fy0 * ddy
            else:
                sy, sdy = 1, (1.0 - fy0) * ddy
            side = 0
            door_at = None
            lintel = None                  # (v0.12.1) (distance, bottom height, front column) over a doorway
            for _ in range(160):
                if sdx < sdy:
                    sdx += ddx
                    mx += sx
                    side = 0
                else:
                    sdy += ddy
                    my += sy
                    side = 1
                    if dc0 <= mx <= dc1 and ((sy > 0 and my == drb) or (sy < 0 and my == dra)):
                        fc = mx - dc0
                        up = door_open[fc]                   # (v0.10) THIS column's own door
                        cross = (sdy - ddy) * T
                        if fc == walk_col:
                            # (v0.12.1) the walking door: brick jambs either side of a person-
                            # sized gap, a real door in it, and brick over it up to the parapet
                            if abs(cx + cross * dx - walk_cx) > half_walk:
                                return jamb_def, 1, cross, door_at, lintel, None
                            if up < 0.5:
                                return walk_def, 1, cross, door_at, lintel, None
                            lintel = (cross, C.WALK_DOOR_H, fc)
                        else:
                            lintel = (cross, C.ROOF_H, fc)
                        if fc != walk_col and up < 0.98:
                            if up <= 0.01:
                                return door_defs[fc], 1, cross, door_at, lintel, None   # (all the way down: a wall)
                            # half up: remember it, keep marching to whatever's behind it, and
                            # draw the door over that afterwards (so the gap isn't sky)
                            door_at = (door_defs[fc], cross, up)
                    elif sy < 0 and lintel is None and (mx, my) in fence_gap:
                        # (v0.14) walking up to a bought garage's open front: brick over the gap
                        lintel = ((sdy - ddy) * T, C.ROOF_H, None)
                if 0 <= mx < n and 0 <= my < n:
                    did = wall_of[my * n + mx]
                    if did:
                        if side == 0:
                            dist = (sdx - ddx) * T
                            plane = (0, sx, mx if sx > 0 else mx + 1)
                        else:
                            dist = (sdy - ddy) * T
                            plane = (1, sy, my if sy > 0 else my + 1)
                        return did, side, dist, door_at, lintel, (plane if door_at is None and lintel is None else None)
                else:
                    dist = ((sdx - ddx) if side == 0 else (sdy - ddy)) * T
                    return edge_def, side, dist, door_at, lintel, None
            return 0, side, 0.0, door_at, lintel, None

        rays = self.ray_k
        nr = len(rays)
        hits = [None] * nr
        stride = 2 if nr > 800 else 1        # (world scale 2+: every other ray marches, see above)
        for i in range(0, nr, stride):
            k = rays[i]
            hits[i] = cast(ca + rx * k, sa + ry * k)
        if stride == 2:
            for i in range(1, nr, 2):
                k = rays[i]
                dx, dy = ca + rx * k, sa + ry * k
                a = hits[i - 1][5]
                if a is not None and i + 1 < nr and hits[i + 1][5] == a:
                    side, step, line = a
                    if side == 0:
                        dist = (line * T - cx) / dx
                        mx, my = (line if step > 0 else line - 1), int((cy + dist * dy) // T)
                    else:
                        dist = (line * T - cy) / dy
                        mx, my = int((cx + dist * dx) // T), (line if step > 0 else line - 1)
                    if dist > 0 and 0 <= mx < n and 0 <= my < n:
                        did = wall_of[my * n + mx]
                        if did:
                            hits[i] = (did, side, dist, None, None, a)
                            continue
                hits[i] = cast(dx, dy)

        # ---- draw. `run` is a strip waiting to be blitted: [key, x, width, src col, (y, h)]
        run = None
        inner_plain = self.inner_plain
        wall_def = self.wall_def
        shades = FA.SHADES
        cam_inside = self.cam_inside
        for i in range(nr):
            did, side, dist, door_at, lintel, _pl = hits[i]
            x = i * cs
            k = rays[i]
            dx, dy = ca + rx * k, sa + ry * k
            if not did:
                zbuf[x:x + cs] = (1e9,) * cs
                if door_at is not None or lintel is not None:
                    if run is not None:
                        blit(scale(run[3], (run[2], run[4][1])), (run[1], run[4][0]))
                        run = None
                    if door_at is not None:
                        self._door_slice(surf, x, dx, dy, door_at, cx, cy, eye, base_level, night)
                    if lintel is not None:
                        self._lintel_slice(surf, x, dx, lintel, cx, eye, base_level, night)
                continue
            if dist < 0.05:
                dist = 0.05
            zbuf[x:x + cs] = (dist,) * cs
            hit = (cy + dist * dy) if side == 0 else (cx + dist * dx)
            if did in inner_plain and not (side == 1 and dy < 0):
                did = inner_plain[did]                      # (a one-sided sign: only the street face has it)
            wt = self._wall_tex(did, night)
            tw = wt.tw
            u = int((hit % T) / T * tw)                     # (v0.19: tw = TEX x the world scale)
            if (side == 0 and dx < 0) or (side == 1 and dy > 0):
                u = tw - 1 - u                              # so text reads the right way round (v0.8: it
                                                            # didn't -- CHOP SHOP had been POHS POHC for ages)
            H = self.wall_height(did)
            level = base_level + int(dist / 11.0) + side
            col = wt.level(level if level < shades else shades - 1)[u]
            th = wt.h
            c0 = 0                                          # first texture row in use
            if H > C.ROOF_H and cam_inside and wall_def[did][0] in ("brick", "pier", "walkdoor", "fsign") \
                    and self._in_shop_box(cx + dist * dx, cy + dist * dy):
                c0 = int(th * (1.0 - C.ROOF_H / H))        # (the parapet's above the ceiling)
                H = C.ROOF_H
            top = hor - (H - eye) * D / dist
            bot = hor + eye * D / dist
            h = bot - top
            if h < 1:
                continue
            if True:
                r0 = None
                if top >= 0 and bot <= vh:
                    r0, r1 = c0, th
                    y, hh = int(top), int(bot) - int(top) or 1
                else:
                    # up close: only scale the part of the texture that's on screen
                    y0, y1 = max(0.0, top), min(float(vh), bot)
                    if y1 > y0:
                        tn = th - c0
                        ti0 = min(tn - 1, int((y0 - top) / h * tn))
                        ti1 = max(ti0 + 1, min(tn, int(math.ceil((y1 - top) / h * tn))))
                        r0, r1 = c0 + ti0, c0 + ti1
                        # stretch so texel edges land where they should
                        y, hh = int(top + ti0 / tn * h), max(1, int((ti1 - ti0) / tn * h))
                if r0 is not None:
                    key = (col, r0, r1, y, hh)
                    if run is not None and run[0] == key and run[1] + run[2] == x:
                        run[2] += cs
                    else:
                        if run is not None:
                            blit(scale(run[3], (run[2], run[4][1])), (run[1], run[4][0]))
                        src = col if (r0 == 0 and r1 == th) else col.subsurface((0, r0, 1, r1 - r0))
                        run = [key, x, cs, src, (y, hh)]
            if door_at is not None or lintel is not None or wall_def[did][0] == "door":
                if run is not None:
                    blit(scale(run[3], (run[2], run[4][1])), (run[1], run[4][0]))
                    run = None
                if door_at is not None:
                    self._door_slice(surf, x, dx, dy, door_at, cx, cy, eye, base_level, night)
                if lintel is not None or wall_def[did][0] == "door":
                    if lintel is None:
                        lintel = (dist, C.ROOF_H, None)      # a shut bay door: brick above it too
                    self._lintel_slice(surf, x, dx, lintel, cx, eye, base_level, night)
        if run is not None:
            blit(scale(run[3], (run[2], run[4][1])), (run[1], run[4][0]))

    def _roof_box(self, cx, cy):
        """(v0.14) the roofed building the camera's standing in, walls included, or None."""
        for _k, (gx, gy, gw, gh) in self._roof_rects:
            if gx <= cx <= gx + gw and gy <= cy <= gy + gh:
                return (gx - T, gy - T, gw + 2 * T, gh + 2 * T)
        return None

    @property
    def roofs(self):
        """(key, floor rect, ceiling texture) per roofed building, the textures at ROOF_PPM x the
        world scale (v0.19), made the first time that scale's needed."""
        rs = self._roof_sets.get(self.kw)
        if rs is None:
            rs = []
            for key, (gx, gy, gw, gh) in self._roof_rects:
                tex = FA.roof_texture(gw, gh, ROOF_PPM * self.kw).convert()
                tex.set_colorkey(ROOF_KEY)
                rs.append((key, (gx, gy, gw, gh), tex))
            self._roof_sets = {self.kw: rs}           # (only one scale's worth kept)
        return rs

    def _in_shop_box(self, x, y):
        """The footprint of the building the camera's inside, walls included (a fence shop
        across the road is still 8 m of brick when you look at it through an open bay door)."""
        b = self.cam_box
        return b is not None and b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3]

    def _lintel_slice(self, surf, x, dx, lintel, cx, eye, base_level, night):
        """(v0.12.1) the brick over a doorway, from the top of the opening up to the parapet --
        without it a raycaster column through an open door has nothing above the opening, and
        the shop looked like a roofless box from the street. From inside it's under the ceiling
        (the roof layer is drawn after the walls), so only the street ever sees it."""
        dist, h0, fc = lintel
        top_h = C.ROOF_H if self.cam_inside else C.SHOP_FACADE_H
        if h0 >= top_h:
            return                           # (indoors, a bay's lintel is all above the ceiling)
        dist = max(0.05, dist)
        hor, vh, D = self.hor, self.vh, self.D
        top = hor - (top_h - eye) * D / dist
        bot = hor - (h0 - eye) * D / dist
        y0, y1 = max(0, int(top)), min(vh, int(bot))
        if y1 - y0 < 1:
            return
        self.lintels[x] = (dist, y1)         # the roof mustn't show through it (see _roof)
        cs = self.cstep
        did = self.walk_def if h0 < C.ROOF_H else self.jamb_def
        wt = self._wall_tex(did, night)
        u = int(((cx + dist * dx) % T) / T * wt.tw)
        level = min(FA.SHADES - 1, base_level + int(dist / 11.0) + 1)
        col = wt.level(level)[u]
        th = wt.h
        t0 = int((1.0 - top_h / C.SHOP_FACADE_H) * th)          # texture row at the top edge
        t1 = max(t0 + 1, min(th, int(round((1.0 - h0 / C.SHOP_FACADE_H) * th))))
        h = bot - top
        ta = t0 + max(0, int((y0 - top) / h * (t1 - t0)))
        tb = max(ta + 1, min(t1, t0 + int(math.ceil((y1 - top) / h * (t1 - t0)))))
        surf.blit(pygame.transform.scale(col.subsurface((0, ta, 1, tb - ta)), (cs, y1 - y0)), (x, y0))

    def _door_slice(self, surf, x, dx, dy, door_at, cx, cy, eye, base_level, night):
        """A half-open roller door, drawn over whatever the ray found behind it."""
        did, dist, up = door_at
        dist = max(0.05, dist)
        cs = self.cstep
        self.zbuf[x:x + cs] = (min(self.zbuf[x], dist),) * cs
        if did in self.inner_plain and not dy < 0:
            did = self.inner_plain[did]
        wt = self._wall_tex(did, night)
        u = int(((cx + dist * dx) % T) / T * wt.tw)
        if dy > 0:
            u = wt.tw - 1 - u                  # (the same flip rule as the walls: side 1)
        H = self.wall_height(did)
        level = min(FA.SHADES - 1, base_level + int(dist / 11.0) + 1)
        col = wt.level(level)[u]
        th = wt.h
        cut = min(th - 1, int(up * th))
        col = col.subsurface((0, cut, 1, th - cut))
        hor, vh, D = self.hor, self.vh, self.D
        top = hor - (H - eye) * D / dist
        bot = hor - (up * H - eye) * D / dist
        y0, y1 = max(0, int(top)), min(vh, int(bot))
        if y1 - y0 < 1:
            return
        if top >= 0 and bot <= vh:
            surf.blit(pygame.transform.scale(col, (cs, y1 - y0)), (x, y0))
        else:
            h = bot - top
            t0 = int((y0 - top) / h * (th - cut))
            t1 = max(t0 + 1, min(th - cut, int(math.ceil((y1 - top) / h * (th - cut)))))
            piece = col.subsurface((0, t0, 1, t1 - t0))
            surf.blit(pygame.transform.scale(piece, (cs, y1 - y0)), (x, y0))

    def _roof(self, surf, cx, cy, yaw, eye):
        """(v0.9) The shop's roof: a mode-7 ceiling, the floor trick upside down. Drawn
        after the walls, but only where it's nearer than them (a tall building seen out
        of the front of the shop is behind the roof's edge, not in front of it). From
        outside you only see it through the front, and only if the door's up.
        (v0.14) ...and the same for every garage you can buy (they open to the south too)."""
        self.roof_clip = None
        for key, rect, tex in self.roofs:
            self._one_roof(surf, cx, cy, yaw, eye, key, rect, tex)

    def _one_roof(self, surf, cx, cy, yaw, eye, key, rect, tex):
        gx, gy, gw, gh = rect
        inside = gx <= cx <= gx + gw and gy <= cy <= gy + gh
        ca, sa = math.cos(yaw), math.sin(yaw)
        if not inside:
            # (v0.12.1: 60/45 m -> the full floor draw distance, so the ceiling doesn't pop out of
            # existence when you back off down the street and look in through the doors)
            if cy < gy + gh or abs(cx - (gx + gw / 2)) > C.FP_FLOOR_DIST or cy > gy + gh + C.FP_FLOOR_DIST:
                return
            if key == "home" and max(self.door_open) < 0.3:
                return
            # (v0.14) off to one side of the view entirely: nothing to draw, skip the rotate
            left = right = behind = 0
            for x, y in ((gx, gy), (gx + gw, gy), (gx, gy + gh), (gx + gw, gy + gh)):
                dx, dy = x - cx, y - cy
                depth, lat = dx * ca + dy * sa, -dx * sa + dy * ca
                if depth < 0.3:
                    behind += 1
                elif lat > depth * self.tanh:
                    right += 1
                elif lat < -depth * self.tanh:
                    left += 1
            if behind == 4 or right + behind == 4 and right or left + behind == 4 and left:
                return
        rh = C.ROOF_H - eye
        if rh <= 0.2:
            return
        hor, vw, D, th = self.hor, self.vw, self.D, self.tanh
        far = max(math.hypot(cx - x, cy - y) for x in (gx, gx + gw) for y in (gy, gy + gh))
        r_lo = 0
        r_hi = min(hor, int(hor - rh * D / far))
        if r_hi <= r_lo:
            return
        rot = pygame.transform.rotate(tex, math.degrees(yaw) + 90.0)
        RW, RHt = rot.get_size()
        # where the camera lands in the rotated texture (forward = up the image, right = right)
        rp = ROOF_PPM * self.kw                  # (v0.19) the texture's px/m at this world scale
        vx, vy = (gx + gw / 2 - cx) * rp, (gy + gh / 2 - cy) * rp
        ox = RW / 2.0 - (-vx * sa + vy * ca)
        oy = RHt / 2.0 + (vx * ca + vy * sa)
        layer = self.roof_layer
        layer.fill(ROOF_KEY, (0, r_lo, vw, r_hi - r_lo))
        scale = pygame.transform.scale
        drawn = False
        for r in range(r_lo, r_hi):
            d = rh * D / (hor - r + 0.5)
            y = int(oy - d * rp)
            if y < 0 or y >= RHt:
                continue
            hw = d * th * rp
            x0 = ox - hw
            w = 2 * hw
            a, b = max(0, int(x0)), min(RW, int(x0 + w) + 1)
            if b <= a:
                continue
            sx0 = int((a - x0) / w * vw)
            sx1 = int((b - x0) / w * vw)
            if sx1 <= sx0:
                continue
            layer.blit(scale(rot.subsurface((a, y, b - a, 1)), (sx1 - sx0, 1)), (sx0, r))
            drawn = True
        if not drawn:
            return
        # the walls that are nearer than the roof keep their pixels
        zbuf = self.zbuf
        cs = self.cstep                        # (v0.17) the walls come in cs-wide slices
        for x in range(0, vw, cs):
            z = zbuf[x]
            if z < 1e8:
                rz = int(hor - rh * D / z)
                if rz < r_hi:
                    rz = max(r_lo, rz)
                    layer.fill(ROOF_KEY, (x, rz, cs, r_hi - rz))
        # (v0.12.1) ...and so does the brick over a doorway: ceiling that's further off than the
        # lintel is behind it (from the street you only see the ceiling *under* the lintel)
        for x, (d0, bot) in getattr(self, "lintels", {}).items():
            a = max(r_lo, int(hor - rh * D / d0))
            b = min(r_hi, bot)
            if b > a:
                layer.fill(ROOF_KEY, (x, a, cs, b - a))
        surf.blit(layer, (0, r_lo), pygame.Rect(0, r_lo, vw, r_hi - r_lo))
        if inside:
            # and the sprites out past the front edge (lamp posts, trees) go behind it
            ends, rows = [], []
            rx, ry = -sa, ca
            for k in self.ray_k:
                dx, dy = ca + rx * k, sa + ry * k
                tx = ((gx + gw - cx) / dx) if dx > 1e-9 else ((gx - cx) / dx) if dx < -1e-9 else 1e9
                ty = ((gy + gh - cy) / dy) if dy > 1e-9 else ((gy - cy) / dy) if dy < -1e-9 else 1e9
                t = max(0.05, min(tx, ty))
                ends.append(t)
                rows.append(int(hor - rh * D / t))
            self.roof_clip = (ends, rows)

    def _sprites(self, surf, view, cx, cy, yaw, eye, me_pid, now, dt, dark, night, bank, hide_car):
        ca, sa = math.cos(yaw), math.sin(yaw)
        maxd = C.FP_SPRITE_DIST
        items = []                                     # (depth, lat, img, anchor_x, anchor_y, ppm, z, extra)

        def add(x, y, img_fn, z=0.0, tag=None):
            dx, dy = x - cx, y - cy
            depth = dx * ca + dy * sa
            if depth < 0.3 or depth > maxd:
                return
            lat = -dx * sa + dy * ca
            if abs(lat) > depth * self.tanh + 4.0:
                return
            items.append((depth, lat, img_fn, z, tag))

        # scenery
        gx, gy = int(cx // 24), int(cy // 24)
        rr = int(maxd // 24) + 1
        for ix in range(gx - rr, gx + rr + 1):
            for iy in range(gy - rr, gy + rr + 1):
                for (x, y, kind, var) in self.static_cells.get((ix, iy), ()):
                    if kind == "tree":
                        add(x, y, lambda v=var: (self.tree_imgs[v], 12))
                    elif kind == "lamp":
                        add(x, y, lambda: (self.lamp_img[night], 8))
                    else:
                        add(x, y, lambda: (self.cam_img, 8))
        for (bx, by, is_sell, bw, bh) in self.benches:
            # (v0.12.1, Bryce: "make the mod shop and parts counter turn about 90 deg so the long
            # side is visible normally") the model's long side runs along its own y axis, but the
            # counter's footprint is long in world x -- it was being drawn end-on, poking out
            # into the room. A quarter turn lines the model up with what you actually bump into.
            # (v0.14: the bought garages' counters run along y already: no turn for those)
            if abs(bx - cx) > maxd or abs(by - cy) > maxd:
                continue
            az = math.atan2(by - cy, bx - cx) - (math.pi / 2 if bw > bh else 0.0)
            L, W = max(bw, bh), min(bw, bh)
            add(bx, by, lambda a=az, s=is_sell, w=L, h=W: self._model_sprite(
                ("bench", s), lambda: FA.bench_boxes(s, w, h), a, 8, 10))
        if self.records is not None and abs(self.records[0] - cx) < maxd and abs(self.records[1] - cy) < maxd:
            rx_, ry_ = self.records
            az = math.atan2(ry_ - cy, rx_ - cx) - math.pi / 2
            add(rx_, ry_, lambda a=az: self._model_sprite("records", FA.records_desk_boxes, a, None, 16))
            add(rx_ - 2.0, ry_ + 0.1, lambda: (self._board("records"), 16))
        snap = getattr(view, "snap", None)
        busy = {}
        for o in (getattr(snap, "orders", None) or ()):
            busy[o[0]] = "order"
        for sl in (getattr(snap, "sales", None) or ()):
            busy[sl[1]] = "sale"
        for (nm, x, y, face, outfit, i) in self.contacts:
            if abs(x - cx) > maxd or abs(y - cy) > maxd:
                continue
            az = math.atan2(y - cy, x - cx) - face
            h = sum(map(ord, nm))
            mark = None if i not in busy else P["gold"] if busy[i] == "order" else (90, 230, 120)
            add(x, y, lambda a=az, h=h, o=outfit: self._person_sprite(
                None, SKINS[h % len(SKINS)], HAIRS[h % len(HAIRS)], 0, None, False, a, 0, o),
                tag=("contact", nm, mark, i))
        shops = getattr(view.snap, "shops", 1) if getattr(view, "snap", None) is not None else 1
        for (nm, x, y, face, outfit, talks) in self.fixed_people:
            if abs(x - cx) > maxd or abs(y - cy) > maxd:
                continue
            az = math.atan2(y - cy, x - cx) - face
            h = sum(map(ord, nm))
            extra = "owner" if outfit == "tommy" and int(now / 2.5) % 3 == 0 else None
            add(x, y, lambda a=az, h=h, o=outfit, e=extra: self._person_sprite(
                None, SKINS[h % len(SKINS)], HAIRS[h % len(HAIRS)], 0, e, False, a, 0, o),
                tag=("label", nm, talks))
        for (x, y, item, idx) in self.fence_crates:
            # (v0.14) only once the place is bought AND cleared out: until then it's junk in there
            if abs(x - cx) > maxd or abs(y - cy) > maxd or not shops & (16 << idx):
                continue
            az = math.atan2(y - cy, x - cx) + math.pi / 2     # facing into the room (they're on the back wall)
            add(x, y, lambda a=az, it=item: self._model_sprite(("crate", it), lambda: FA.crate_boxes(it), a, None, 16),
                tag=("crate", item))
        for (x, y, idx) in self.fence_signs:
            if abs(x - cx) > maxd or abs(y - cy) > maxd:
                continue
            state = 2 if shops & (16 << idx) else 1 if shops & (1 << idx) else 0
            add(x, y, lambda i=idx, o=state: (self._sale_sign(i, o), 16))
        for (x, y, ang) in self.map.ramps:
            if abs(x - cx) < maxd and abs(y - cy) < maxd:
                az = math.atan2(y - cy, x - cx) - ang
                add(x, y, lambda a=az: self._model_sprite("ramp", FA.ramp_boxes, a, None, 12))
        self._pigeons(view, cx, cy, now, dt, add)
        self._hats(dt, cx, cy, add)
        for (x, y, along, seg) in self.bar_segs:
            if abs(x - cx) < maxd and abs(y - cy) < maxd:
                az = math.atan2(y - cy, x - cx) - along
                add(x, y, lambda a=az, L=seg: self._model_sprite(("bars", L), lambda: FA.bars_boxes(L), a, None, 16))
        if self.desk is not None and abs(self.desk[0] - cx) < maxd and abs(self.desk[1] - cy) < maxd:
            dx_, dy_, dw_, dh_ = self.desk
            az = math.atan2(dy_ - cy, dx_ - cx)
            add(dx_, dy_, lambda a=az: self._model_sprite("desk", lambda: FA.desk_boxes(dw_, dh_), a, None, 16))
        for (x, y, item) in self.crates:
            az = math.atan2(y - cy, x - cx) - math.pi       # the crates face into the shop
            add(x, y, lambda a=az, it=item: self._model_sprite(("crate", it), lambda: FA.crate_boxes(it), a, None, 16),
                tag=("crate", item))
        hd = getattr(self.map, "door_handle", None)
        if hd is not None and abs(hd[0] - cx) < maxd and abs(hd[1] - cy) < maxd:
            # (v0.17.1) the master door handle: lever down when every door in the snapshot is shut
            rows = [t[5] for t in getattr(view, "traps", {}).values() if t[1] == S.TRAP_DOOR]
            down = bool(rows) and all(life < C.DOOR_PASSABLE for life in rows)
            az = math.atan2(hd[1] - cy, hd[0] - cx) - hd[2]
            add(hd[0], hd[1], lambda a=az, dn=down: self._model_sprite(
                ("handle", dn), lambda: FA.door_handle_boxes(dn), a, None, 24), tag=("label", "ALL DOORS", True))
        for t in getattr(view, "traps", {}).values():
            if t[1] in (S.TRAP_SMOKE, S.TRAP_DOOR):
                # (smoke is particles: see smoke_clouds. The shop's doors are drawn by the
                # raycaster -- before v0.12.1 they fell through to the roadblock branch below,
                # so every bay had a row of orange traffic barriers parked across it)
                continue
            if t[1] == S.TRAP_JUNK:
                k = (t[0] - C.JUNK_ID_BASE) % C.JUNK_PER_SHOP
                az = math.atan2(t[3] - cy, t[2] - cx) - k * 0.8
                add(t[2], t[3], lambda a=az, k_=k: self._model_sprite(("junk", k_), lambda: FA.junk_boxes(k_),
                                                                       a, None, 16))
                continue
            if t[1] == S.TRAP_CELL:
                L = C.CELL_DOOR_W
                if t[5] > 0:                                    # shut (and maybe dented): bars and a padlock
                    bent = round(1.0 - t[5], 1)
                    az = math.atan2(t[3] - cy, t[2] - cx) - math.pi / 2
                    add(t[2], t[3], lambda a=az, bt=bent: self._model_sprite(
                        ("celldoor", bt), lambda: FA.bars_boxes(L, True, True, bt), a, None, 16))
                else:                                           # open: swung back on its hinge, into the hall
                    x, y = t[2] - L / 2, t[3] + L / 2
                    az = math.atan2(y - cy, x - cx)
                    add(x, y, lambda a=az: self._model_sprite(
                        ("celldoor", "open"), lambda: FA.bars_boxes(L, True, False), a, None, 16))
                continue
            if t[1] == S.TRAP_GATE:
                if t[5] > 0:                                    # shut: a row of bars across the doorway
                    for k in range(2):
                        off = -C.GATE_LEN / 2 + (k + 0.5) * C.GATE_LEN / 2
                        x, y = t[2] + off, t[3]
                        az = math.atan2(y - cy, x - cx) - math.pi / 2
                        add(x, y, lambda a=az: self._model_sprite("gate", lambda: FA.gate_boxes(C.GATE_LEN / 2),
                                                                  a, None, 16))
                continue
            if t[5] < 0.1 and int(now * 6) % 2:
                continue                                        # about to be towed: blink
            if t[1] == S.TRAP_WHOOPEE:
                az = math.atan2(t[3] - cy, t[2] - cx)
                add(t[2], t[3], lambda a=az: self._model_sprite("whoopee", FA.whoopee_boxes, a, None, 24))
                continue
            if t[1] in (S.TRAP_BANANA, S.TRAP_DONUT):
                az = math.atan2(t[3] - cy, t[2] - cx)
                name = "banana" if t[1] == S.TRAP_BANANA else "donutbox"
                fn = FA.banana_boxes if t[1] == S.TRAP_BANANA else FA.donut_box_boxes
                add(t[2], t[3], lambda a=az, nm=name, f=fn: self._model_sprite(nm, f, a, None, 24))
                continue
            spikes = t[1] == S.TRAP_SPIKES
            along = 0.0 if abs(math.cos(t[4])) > 0.5 else math.pi / 2   # which way the traffic runs
            length = C.SPIKE_LEN if spikes else C.ROADBLOCK_LEN
            segs = 2 if spikes else 4
            seg = length / segs
            px, py = -math.sin(along), math.cos(along)
            for k in range(segs):
                off = -length / 2 + (k + 0.5) * seg
                x, y = t[2] + px * off, t[3] + py * off
                az = math.atan2(y - cy, x - cx) - along
                if spikes:
                    add(x, y, lambda a=az, L=seg: self._model_sprite(("spikes", L), lambda: FA.spike_boxes(L), a, None, 16))
                else:
                    lamp = k % 2 == 1
                    add(x, y, lambda a=az, L=seg, lp=lamp: self._model_sprite(
                        ("barrier", L, lp), lambda: FA.barrier_boxes(L, lp), a, 8, 16))
        # the living
        for row in view.cars.values():
            if row[0] == hide_car:
                continue
            az = math.atan2(row[8] - cy, row[7] - cx) - row[11]
            if row[15] == V.SCOOTER and row[12]:
                # the mobility scooter doesn't hide its rider. That's the whole joke.
                drv = view.players.get(row[12])
                if drv is not None:
                    col = PLAYER_COLORS[drv[1] % 4]
                    az2 = math.atan2(row[8] - cy, row[7] - cx) - row[11]
                    add(row[7] - math.cos(row[11]) * 0.2, row[8] - math.sin(row[11]) * 0.2,
                        lambda s=col, c=_pchar(drv), a=az2:
                        self._person_sprite(s, None, None, 0, None, False, a, 0, None, c), z=0.25)
            elif V.is_bike(row[15]) and row[0] != hide_car:
                # (v0.13) a bike's rider (and pillion) sit on top of it, hunched over the bars
                seat_z = 0.42 if row[15] == V.SPORTBIKE else 0.5
                az2 = math.atan2(row[8] - cy, row[7] - cx) - row[11]
                for pid, back in ((row[12], 0.25), (row[13] if len(row) > 13 else 0, 0.75)):
                    rider = view.players.get(pid) if pid else None
                    if rider is None:
                        continue
                    col = PLAYER_COLORS[rider[1] % 4]
                    add(row[7] - math.cos(row[11]) * back, row[8] - math.sin(row[11]) * back,
                        lambda s=col, c=_pchar(rider), a=az2:
                        self._person_sprite(s, None, None, 2, "fists", False, a, 0, None, c), z=seat_z)
            if row[1] == S.COP and row[18] & PR.CX_DONUT:
                add(row[7], row[8], None, z=2.2, tag=("say", "NOM NOM"))
            hop = 0.0
            if len(row) > 20 and row[20] & PR.DR_HOP:
                hop = abs(math.sin(now * 9.0 + row[0])) * 0.9      # boing. boing. boing.
            if row[4] & PR.CF_AIR:
                hop += self._air_height(row, now)                   # (v0.9) BIG AIR
            elif row[0] in self.air_t0:
                del self.air_t0[row[0]]
            if row[0] == self.hires:
                # the chase cam's car: more angles, more pixels (it's right there, being drifted)
                add(row[7], row[8], lambda r=row, a=az: self._car_sprite(r, a, C.CHASE_CAR_ANGLES, 20),
                    z=hop, tag=("smoke", row))
            else:
                add(row[7], row[8], lambda r=row, a=az: self._car_sprite(r, a), z=hop, tag=self._car_marker(row))
        self._trunk_pop(view, dt, cx, cy, add)
        frame = int(now * 7) % 2
        for n in view.npcs.values():
            az = math.atan2(n[4] - cy, n[3] - cx) - n[5]
            st = n[2]
            fr = frame if st in (PR.NS_WALK, PR.NS_FLEE, PR.NS_BRAWL, PR.NS_TASER, PR.NS_RUNOFF) else 0
            down = st in (PR.NS_DOWN, PR.NS_CARRIED)
            z = n[6] if len(n) > 6 else 0.0
            if st == PR.NS_CARRIED:
                z -= 0.55                              # draped over a shoulder, not floating above it
            if n[1] == S.DOG:
                add(n[3], n[4], lambda f=fr, tr=(st == PR.NS_RUNOFF), dn=down, a=az: self._dog_sprite(f, tr, dn, a),
                    z=z)
                continue
            if n[1] == S.CHICKEN:
                pk = st == PR.NS_WALK and (int(now * 3 + n[0]) % 5 == 0)
                add(n[3], n[4], lambda f=fr, p_=pk, a=az, dn=down: self._model_sprite(
                    ("chicken", f, p_, dn), lambda: FA.chicken_boxes(f, p_) if not dn else FA.lying(
                        FA.chicken_boxes(0, False)), a, None, 32), z=z)
                continue
            shirt, skin, hair, extra, outfit = self._person_look(n[0], n[1])
            if outfit and outfit.startswith("hat"):
                if n[0] in self.hat_off:
                    outfit = None
                elif down and st != PR.NS_CARRIED:
                    self._hat_flies(n[0], n[3], n[4], int(outfit[3]))     # (v0.9) off it comes
                    outfit = None
            gun = 0
            if st == PR.NS_HANDSUP:
                extra = "handsup"
            elif st in (PR.NS_BRAWL, PR.NS_CUFFING) and extra is None:
                extra = "fists"
            elif st == PR.NS_ARMED:
                gun = 1
            elif st == PR.NS_TASER:
                gun = 3
            elif st == PR.NS_LAUGH and extra is None:
                extra = "laugh"
            add(n[3], n[4], lambda s=shirt, k=skin, h=hair, e=extra, f=fr, dn=down, a=az, g=gun, o=outfit:
                self._person_sprite(s, k, h, f, e, dn, a, g, o), z=z)
        for p in view.players.values():
            if p[0] == me_pid or p[2] in (S.DRIVER, S.PASSENGER):
                continue
            shirt = PLAYER_COLORS[p[1] % 4]
            extra = "cuffed" if p[2] == S.CUFFED else None
            az = math.atan2(p[5] - cy, p[4] - cx) - p[8]
            fr = frame if p[3] & PR.PF_MOVING else 0
            flags = p[3]
            gun = {S.ARM_PISTOL: 1, S.ARM_SHOTGUN: 2}.get(p[14] if len(p) > 14 else 0, 0) \
                if p[2] == S.FOOT and p[9] == NO_PART and not flags & (PR.PF_DOLLY | PR.PF_CARRY) else 0
            if flags & PR.PF_DANCE:
                extra, gun = ("dance0" if int(now * 5) % 2 else "dance1"), 0
            elif flags & PR.PF_CHARGE:
                extra = "windup"
            z = p[15] if len(p) > 15 else 0.0
            down = p[2] in (S.TUMBLE, S.CARRIED, S.DEAD)
            if p[2] == S.CARRIED:
                z -= 0.55
            f2 = p[17] if len(p) > 17 else 0
            outfit = "jumpsuit" if f2 & (PR.PF2_JUMPSUIT | PR.PF2_JAILED) else ("pantsed" if f2 & PR.PF2_PANTSED
                                                                                else None)
            if f2 & PR.PF2_TASED and p[2] == S.TUMBLE:
                z += 0.05 * (int(now * 30) % 2)          # twitching. It's not funny. (It's a bit funny.)
                if self.rng.random() < 0.4:
                    self.emit(SPARK, p[4] + self.rng.uniform(-0.4, 0.4), p[5] + self.rng.uniform(-0.4, 0.4),
                              0.3, 0, 0, 1.5, 0.15)
            if f2 & PR.PF2_BOX and p[2] == S.FOOT:
                # (v0.9) it's just a box. A box with a name tag, if it's your mate. (And feet, if it moves.)
                mv = bool(flags & PR.PF_MOVING)
                add(p[4], p[5], lambda f=fr, m_=mv, a=az: self._model_sprite(
                    ("cbox", f if m_ else 0, m_), lambda: FA.cardboard_box_boxes(f, m_), a, None, 16), z=z,
                    tag=None if f2 & PR.PF2_HIDDEN else ("name", p))
                continue
            add(p[4], p[5], lambda s=shirt, c=_pchar(p), f=fr, e=extra,
                dn=down, a=az, g=gun, o=outfit: self._person_sprite(s, None, None, f, e, dn, a, g, o, c), z=z,
                tag=("name", p))
            if flags & PR.PF_CHUTE:
                add(p[4], p[5], lambda: (self.chute_img, 12), z=z + 1.9)
        for pk in view.pickups.values():
            pz = pk[5] if len(pk) > 5 else 0.0
            if pk[1] == GNOME_IDX:
                # gnomes don't bob like loot; they stand there and judge you
                az = math.atan2(pk[3] - cy, pk[2] - cx) - pk[0] * 0.7
                add(pk[2], pk[3], lambda a=az: self._model_sprite("gnome", FA.gnome_boxes, a, None, 40),
                    z=pz, tag=("pickup", pk[4]))
                continue
            ic = self._icon(bank, pk[1])
            bob = 0.12 + 0.06 * math.sin(now * 3 + pk[0])
            add(pk[2], pk[3], lambda i=ic: (i, 12), z=bob + pz, tag=("pickup", pk[4]))
        for d in view.dollies.values():
            if d[5] == me_pid:
                continue
            az = math.atan2(d[2] - cy, d[1] - cx) - d[3]
            lvl = (getattr(view.snap, "dolly", 0) or 0) & 3 if getattr(view, "snap", None) is not None else 0
            add(d[1], d[2], lambda a=az, lv=lvl: self._model_sprite(("dolly", lv), lambda: FA.dolly_boxes(lv),
                                                                     a, None, 16),
                tag=("dolly", d[4]))
        for e in self.explosions:
            add(e[0], e[1], None, z=1.2, tag=("boom", e))

        items.sort(key=lambda it: -it[0])
        zbuf = self.zbuf
        hor, D, vw = self.hor, self.D, self.vw
        ks = self.ks                                   # (v0.17) labels, arrows and outlines grow with it
        cs = self.cstep
        text = self.font.draw
        for depth, lat, img_fn, z, tag in items:
            sx = vw / 2 + lat / depth * D
            if tag is not None and tag[0] == "boom":
                self._draw_boom(surf, tag[1], sx, depth, eye, dt)
                continue
            if img_fn is None:
                # floating words over something ("NOM NOM"), if it's not behind a wall
                col_ = int(sx)
                if tag is not None and tag[0] == "say" and depth < 50 and 0 <= col_ < vw and depth < zbuf[col_]:
                    text(surf, tag[1], col_, int(hor + (eye - z) * D / depth), P["gold"], scale=ks, align="center")
                continue
            self._spx = D / depth                      # (v0.17) screen px per metre here: picks the mip
            img, ppm = img_fn()
            if isinstance(img, tuple):                 # (surface, anchor_x, anchor_y)
                img, ax, ay = img
            else:                                      # plain billboard, planted by its bottom middle
                ax, ay = img.get_width() / 2, img.get_height()
            k = D / depth / ppm
            sw, sh = int(img.get_width() * k), int(img.get_height() * k)
            if sw < 1 or sh < 1 or sw > vw * 3:
                continue
            left = int(sx - ax * k)
            ground = hor + (eye - z) * D / depth
            top = int(ground - ay * k)
            x0, x1 = max(0, left), min(vw, left + sw)
            if x0 >= x1:
                continue
            # which columns are in front of the walls? (v0.17: the zbuf only changes every cs
            # columns -- one wall ray each -- so step through it a slice at a time)
            runs = []
            start = None
            for col in range(x0 - x0 % cs, x1, cs):
                if depth < zbuf[col]:
                    if start is None:
                        start = max(x0, col)
                elif start is not None:
                    runs.append((start, col))
                    start = None
            if start is not None:
                runs.append((start, x1))
            if not runs:
                continue
            scaled = pygame.transform.scale(img, (sw, sh))
            # darker with distance and at night, like the walls (Doom's "light diminishing")
            f = (1.0 - 0.6 * dark) * (1.0 - 0.45 * min(1.0, depth / maxd))
            if f < 0.97:
                v = int(255 * f)
                scaled.fill((v, v, min(255, int(v * 1.06))), special_flags=pygame.BLEND_RGB_MULT)
            clip = self.roof_clip
            for a, b in runs:
                cut = 0
                if clip is not None:
                    mid = (a + b) // 2 // cs              # (one clip entry per wall ray)
                    if depth > clip[0][mid]:
                        cut = clip[1][mid] - top          # (v0.9) behind the roof's edge up there
                        if cut >= sh:
                            continue
                        cut = max(0, cut)
                surf.blit(scaled, (a, top + cut), pygame.Rect(a - left, cut, b - a, sh - cut))
            if tag is not None:
                if tag[0] == "name" and depth < 40 and runs:
                    p = tag[1]
                    col = PLAYER_COLORS[p[1] % 4]
                    text(surf, p[13], int(sx), top - 8 * ks, col, scale=ks, align="center")
                    if p[2] == S.CUFFED:
                        text(surf, "BUSTED", int(sx), top - 15 * ks, P["danger"], scale=ks, align="center")
                elif tag[0] == "mark" and depth < 70:
                    bob = math.sin(now * 4 + tag[2]) * 0.12
                    my = int(ground - (2.3 + bob) * D / depth)
                    r = max(3 * ks, min(8 * ks, int(0.35 * D / depth)))
                    pygame.draw.polygon(surf, P["ink"], [(sx - r - ks, my - r - ks), (sx + r + ks, my - r - ks), (sx, my + ks)])
                    pygame.draw.polygon(surf, tag[1], [(sx - r, my - r), (sx + r, my - r), (sx, my)])
                elif tag[0] == "contact":
                    # (v0.14) a contact: their name up close, and a marker from down the street if
                    # they've got an order in (gold) or a car coming to them (green)
                    if depth < 22:
                        text(surf, tag[1], int(sx), top - 8 * ks, P["gold"], scale=ks, align="center")
                    if tag[2] is not None and depth < 90:
                        bob = math.sin(now * 4 + tag[3]) * 0.12
                        my = int(ground - (2.5 + bob) * D / depth)
                        r = max(3 * ks, min(8 * ks, int(0.35 * D / depth)))
                        pygame.draw.polygon(surf, P["ink"], [(sx - r - ks, my - r - ks), (sx + r + ks, my - r - ks),
                                                             (sx, my + ks)])
                        pygame.draw.polygon(surf, tag[2], [(sx - r, my - r), (sx + r, my - r), (sx, my)])
                elif tag[0] == "label" and depth < 22:
                    text(surf, tag[1], int(sx), top - 8 * ks, P["gold"] if tag[2] else P["white"],
                         scale=ks, align="center")
                elif tag[0] == "locked" and depth < 4.5:
                    text(surf, "LOCKED - BUY THE LOT", int(sx), int(ground - 1.3 * D / depth),
                         P["danger"], scale=ks, align="center")
                elif tag[0] == "crate" and depth < 9:
                    label, price = S.MARKET[tag[1]]
                    text(surf, "%s $%d" % (label.split(" (")[0], price), int(sx),
                         int(ground - 1.3 * D / depth), P["gold"], scale=ks, align="center")
                elif tag[0] == "dolly" and tag[1] != 255:
                    ic = self._icon(bank, tag[1])
                    kk = D / depth / 14
                    iw = max(1, int(ic.get_width() * kk))
                    icon = pygame.transform.scale(ic, (iw, iw))
                    surf.blit(icon, (int(sx - iw / 2), int(ground - 0.9 * D / depth) - iw))

    # ------------------------------------------------------------------ (v0.9) cosmetic sillies
    def _air_height(self, row, now):
        """Off a stunt ramp: a parabola, hang time from the speed it took off at."""
        t0 = self.air_t0.get(row[0])
        if t0 is None:
            T = max(0.3, math.hypot(row[9], row[10]) * C.RAMP_AIR_PER_MS)
            t0 = self.air_t0[row[0]] = (now, T)
        t = (now - t0[0]) / t0[1]
        if not 0.0 <= t <= 1.0:
            return 0.0
        return 9.8 * t0[1] * t0[1] / 2.0 * t * (1.0 - t)

    def _trunk_pop(self, view, dt, cx, cy, add):
        """(v0.10, Bryce: "popping trunk animaiton") purely cosmetic: whichever car's
        trunk the SELF block says you're currently looking into eases its lid open
        over TRUNK_POP_TIME, and eases it shut again once you walk off. Rides the
        trunk data every trunk prompt already sends -- no new bytes on the wire."""
        tr = getattr(view.snap, "trunk", None)
        target_id = tr[0] if tr is not None else None
        if target_id is not None and target_id not in self.trunk_pop:
            self.trunk_pop[target_id] = 0.0
        rate = dt / max(0.05, C.TRUNK_POP_TIME)
        dead = []
        for cid, t in self.trunk_pop.items():
            goal = 1.0 if cid == target_id else 0.0
            t = clamp(t + rate if goal > t else t - rate, 0.0, 1.0)
            self.trunk_pop[cid] = t
            row = view.cars.get(cid)
            if row is None or (t <= 0.0 and goal <= 0.0):
                dead.append(cid)
                continue
            mdl = V.model(row[15])
            bx = row[7] - math.cos(row[11]) * mdl.length / 2
            by = row[8] - math.sin(row[11]) * mdl.length / 2
            az = math.atan2(by - cy, bx - cx) - row[11]
            stage = min(3, int(t * 4))
            add(bx, by, lambda a=az, s=stage: self._model_sprite(("trunklid", s), lambda: FA.trunk_lid_boxes(s),
                                                                  a, None, 20), z=0.6)
        for cid in dead:
            del self.trunk_pop[cid]

    def _hat_flies(self, nid, x, y, style):
        if len(self.hat_off) > 400:
            self.hat_off.clear()
        self.hat_off.add(nid)
        r = self.rng
        a = r.uniform(0, TWO_PI)
        sp = r.uniform(1.5, 3.5)
        self.flying_hats.append([x, y, 1.7, math.cos(a) * sp, math.sin(a) * sp, r.uniform(3.5, 5.5),
                                 r.uniform(0, TWO_PI), style, 14.0])

    def _hats(self, dt, cx, cy, add):
        keep = []
        for h in self.flying_hats:
            h[8] -= dt
            if h[8] <= 0:
                continue
            if h[2] > 0 or h[5] > 0:
                h[0] += h[3] * dt
                h[1] += h[4] * dt
                h[5] -= 9.8 * dt
                h[2] = max(0.0, h[2] + h[5] * dt)
                h[6] += dt * 9.0
                if h[2] <= 0:
                    h[5] = 0.0
            keep.append(h)
            az = math.atan2(h[1] - cy, h[0] - cx) - h[6]
            add(h[0], h[1], lambda a=az, s=h[7]: self._model_sprite(("civhat", s), lambda: FA.civ_hat_boxes(s),
                                                                    a, None, 20), z=h[2] + 0.04)
        self.flying_hats = keep[-30:]

    def _init_pigeons(self):
        """A few flocks on the pavement by the lamp posts. Deterministic, client-only."""
        r = random.Random(self.map.seed * 31 + 5)
        self.pigeons = []
        self.pigeon_img = {(f, fl): FA.pigeon_img(f, fl) for f in (0, 1) for fl in (False, True)}
        lamps = list(self.map.lamps)
        r.shuffle(lamps)
        for (lx, ly) in lamps[:18]:
            flock = []
            for _ in range(r.randint(3, 7)):
                flock.append([lx + r.uniform(-1.8, 1.8), ly + r.uniform(-1.8, 1.8), 0.0, 0.0, 0.0, 0.0,
                              r.uniform(0, 5)])
            # [x, y, z, vx, vy, vz, phase]; plus the flock's home and when it's safe to come back
            self.pigeons.append({"home": [(p[0], p[1]) for p in flock], "birds": flock, "gone_t": 0.0})

    def _scare_pigeons(self, x, y, r):
        for fl in self.pigeons:
            hx, hy = fl["home"][0]
            if fl["gone_t"] <= 0 and (hx - x) ** 2 + (hy - y) ** 2 < r * r:
                fl["gone_t"] = 20.0
                for b_ in fl["birds"]:
                    a = self.rng.uniform(0, TWO_PI)
                    b_[3], b_[4], b_[5] = math.cos(a) * 4.0, math.sin(a) * 4.0, self.rng.uniform(3.0, 5.0)

    def _pigeons(self, view, cx, cy, now, dt, add):
        """Pigeons: peck peck peck until anything comes near (a person, a car, a bang), then
        the whole flock goes up at once. They come back 20 seconds later. They always come back."""
        movers = [(p[4], p[5]) for p in view.players.values() if p[2] in (S.FOOT, S.TUMBLE)]
        movers += [(c[7], c[8]) for c in view.cars.values() if abs(c[9]) + abs(c[10]) > 2.0]
        movers.append((cx, cy))
        for fl in self.pigeons:
            hx, hy = fl["home"][0]
            if abs(hx - cx) > 60 or abs(hy - cy) > 60:
                continue
            birds = fl["birds"]
            if fl["gone_t"] > 0:
                fl["gone_t"] -= dt
                if fl["gone_t"] <= 0:
                    for b_, (x, y) in zip(birds, fl["home"]):
                        b_[:6] = [x, y, 0.0, 0.0, 0.0, 0.0]
            elif any((mx - hx) ** 2 + (my - hy) ** 2 < 25.0 for mx, my in movers):
                self._scare_pigeons(hx, hy, 0.5)
            for b_ in birds:
                if b_[5] != 0.0 or b_[2] > 0:
                    b_[0] += b_[3] * dt
                    b_[1] += b_[4] * dt
                    b_[2] += b_[5] * dt
                    if b_[2] > 25.0:
                        continue                                   # (gone: over the rooftops)
                flying = b_[2] > 0.05
                f = int(now * (14 if flying else 2) + b_[6]) % 2
                img = self.pigeon_img[(f, flying)]
                add(b_[0], b_[1], lambda i=img: (i, 24), z=b_[2])

    @staticmethod
    def _car_marker(row):
        """A bobbing arrow over anything you could drive off in right now."""
        kind, state, flags, drv = row[1], row[3], row[4], row[12]
        if kind == S.CIV and state != S.DELIVERED and not drv:
            col = P["gold"] if flags & PR.CF_WANTED else MARK_STEAL
            return ("mark", col, row[0])
        if kind == S.TRAFFIC and math.hypot(row[9], row[10]) < C.CARJACK_MAX_SPEED:
            return ("mark", MARK_JACK, row[0])
        return None

    def _tracers(self, surf, cx, cy, yaw, eye, dt):
        if not self.tracers:
            return
        ca, sa = math.cos(yaw), math.sin(yaw)
        hor, D, vw = self.hor, self.D, self.vw
        near = 0.3
        keep = []
        for tr in self.tracers:
            tr[5] -= dt
            if tr[5] <= 0:
                continue
            keep.append(tr)
            x0, y0, x1, y1 = tr[0], tr[1], tr[2], tr[3]
            length = math.hypot(x1 - x0, y1 - y0)
            if math.hypot(x0 - cx, y0 - cy) < 1.2 and length > 0.1:
                # your own shot: from your eyes it's a line from under your chin to the
                # target. Only draw the far end, where you can see the round land.
                k = min(0.5, 2.0 / length)
                x0, y0 = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
            ends = []
            for x, y, z in ((x0, y0, 1.35), (x1, y1, 1.15)):
                dx, dy = x - cx, y - cy
                ends.append([dx * ca + dy * sa, -dx * sa + dy * ca, z])
            (d0, l0, z0), (d1, l1, z1) = ends
            if d0 < near and d1 < near:
                continue
            if d0 < near or d1 < near:                   # clip to the near plane
                t = (near - d0) / (d1 - d0)
                clipped = (near, l0 + (l1 - l0) * t, z0 + (z1 - z0) * t)
                if d0 < near:
                    d0, l0, z0 = clipped
                else:
                    d1, l1, z1 = clipped
            pts = []
            for d, l, z in ((d0, l0, z0), (d1, l1, z1)):
                pts.append((max(-5000, min(5000, int(vw / 2 + l / d * D))),
                            max(-5000, min(5000, int(hor + (eye - z) * D / d)))))
            if tr[4] == S.TRACER_TASER:
                # two wiggly yellow wires
                mx = (pts[0][0] + pts[1][0]) // 2 + self.rng.randint(-3, 3) * self.ks
                my = (pts[0][1] + pts[1][1]) // 2 + self.rng.randint(-3, 3) * self.ks
                pygame.draw.lines(surf, (255, 230, 80), False, [pts[0], (mx, my), pts[1]], self.ks)
            else:
                pygame.draw.line(surf, TRACER_COL, pts[0], pts[1], self.ks)
        self.tracers = keep

    def _draw_boom(self, surf, e, sx, depth, eye, dt):
        t = e[2]                                   # (aged in _particles)
        r = int((1.0 + t * 12) * self.D / depth)
        sy = int(self.hor + (eye - 1.2) * self.D / depth)
        col = P["white"] if t < 0.1 else P["fire1"] if t < 0.25 else P["fire2"] if t < 0.45 else P["smoke"]
        if 0 < r < 600:
            pygame.draw.circle(surf, col, (int(sx), sy), r, 0 if t < 0.3 else max(1, int(r * 0.2)))

    def _particles(self, surf, cx, cy, yaw, eye, dt):
        ca, sa = math.cos(yaw), math.sin(yaw)
        hor, D, vw, vh = self.hor, self.D, self.vw, self.vh
        zbuf = self.zbuf
        fill = surf.fill
        alive = []
        fire_cols = (P["fire1"], P["fire2"], P["fire3"])
        for p in self.particles:
            p[6] -= dt
            if p[6] <= 0:
                continue
            kind = p[8]
            p[0] += p[3] * dt
            p[1] += p[4] * dt
            p[2] += p[5] * dt
            if kind in (SPARK, DEBRIS, CONFETTI):
                p[5] -= 9.8 * dt
                if p[2] < 0:
                    p[2], p[5] = 0.0, -p[5] * 0.3
                d = math.exp(-2 * dt)
            else:
                p[5] = 0.8 if kind in (SMOKE, FIRE) else p[5]
                d = math.exp(-1.2 * dt)
            p[3] *= d
            p[4] *= d
            alive.append(p)
            dx, dy = p[0] - cx, p[1] - cy
            depth = dx * ca + dy * sa
            if depth < 0.3:
                continue
            sx = int(vw / 2 + (-dx * sa + dy * ca) / depth * D)
            if not (0 <= sx < vw) or depth > zbuf[sx]:
                continue
            sy = int(hor + (eye - p[2]) * D / depth)
            if not (0 <= sy < vh):
                continue
            t = p[6] / p[7]
            size = max(1, int((0.12 if kind in (SPARK, DEBRIS) else 0.4 if kind != CONFETTI else 0.15)
                              * D / depth * (1.0 + (1 - t) * (2.0 if kind == SMOKE else 0.0))))
            if kind == SPARK:
                c = P["fire1"] if t > 0.5 else P["fire2"]
            elif kind == FIRE:
                c = fire_cols[min(2, int((1 - t) * 3))]
            elif kind == SMOKE:
                c = P["smoke"] if t < 0.5 else P["smoke_l"]
            elif kind == DUST:
                c = (150, 146, 140)
            else:
                c = p[9] or P["metal_l"]
            fill(c, (sx - size // 2, sy - size // 2, size, size))
        self.particles = alive
        keep = []
        for e in self.explosions:
            e[2] += dt
            if e[2] < 0.7:
                keep.append(e)
        self.explosions = keep

    def smoke_clouds(self, view):
        """Burnout smoke screens (server-side TRAP_SMOKE): keep them billowing."""
        r = self.rng
        for t in getattr(view, "traps", {}).values():
            if t[1] != S.TRAP_SMOKE or r.random() > 0.35 + 0.4 * t[5]:
                continue
            a, d = r.uniform(0, TWO_PI), r.uniform(0, C.SMOKE_SCREEN_R)
            self.emit(SMOKE, t[2] + math.cos(a) * d, t[3] + math.sin(a) * d, r.uniform(0.2, 1.5),
                      r.uniform(-0.4, 0.4), r.uniform(-0.4, 0.4), 0.3, 1.8)

    def exhaust_pop(self, cid, now):
        """A backfire: a gout of flame out of this car's exhaust (next car_emitters)."""
        self.pops.add(cid)

    def car_emitters(self, view, dt):
        """Fire, smoke and dragging hubs, emitted in world space."""
        r = self.rng
        for c in view.cars.values():
            (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, drv, psg, dmg) = c[:15]
            drive = c[20] if len(c) > 20 else 0
            if cid in self.pops or drive & PR.DR_BURNOUT:
                mdl = V.model(c[15])
                fx, fy = math.cos(ang), math.sin(ang)
                if cid in self.pops:
                    # pops and bangs: flame out the back, then it's gone
                    lx = -mdl.length / 2 - 0.3
                    for _ in range(5):
                        self.emit(FIRE, x + fx * lx - fy * 0.5, y + fy * lx + fx * 0.5, 0.35,
                                  -fx * r.uniform(3, 7) + vx, -fy * r.uniform(3, 7) + vy, 0.6, 0.18)
                if drive & PR.DR_BURNOUT:
                    # a brake stand: the driven wheels vanish into their own weather system
                    lx = mdl.length * (0.32 if mdl.fwd else -0.32)
                    for ly in (-mdl.width * 0.42, mdl.width * 0.42):
                        if r.random() < 0.55:          # (smoke is opaque pixels: a little goes a long way)
                            self.emit(SMOKE, x + fx * lx - fy * ly, y + fy * lx + fx * ly, 0.3,
                                      r.uniform(-1.5, 1.5) - fx * 1.5, r.uniform(-1.5, 1.5) - fy * 1.5, 1.0, 1.5)
            if flags & PR.CF_FIRE:
                for _ in range(2):
                    self.emit(FIRE, x + r.uniform(-1, 1), y + r.uniform(-1, 1), 1.0, r.uniform(-1, 1),
                              r.uniform(-1, 1), 2.0, 0.5)
                if r.random() < 0.4:
                    self.emit(SMOKE, x, y, 1.5, r.uniform(-1, 1), r.uniform(-1, 1), 1.5, 1.6)
            elif dmg >= 3 and r.random() < 0.1:
                self.emit(SMOKE, x + math.cos(ang) * 1.5, y + math.sin(ang) * 1.5, 1.0, 0, 0, 1.0, 1.0)
            spd = math.hypot(vx, vy)
            if spd > 6 and not (kind == S.COP and flags & PR.CF_FIRE):
                slip = abs((math.atan2(vy, vx) - ang + math.pi) % TWO_PI - math.pi)
                if 0.25 < slip < 2.6 or (flags & PR.CF_HANDBRAKE and spd > 8):
                    # tyre smoke off the rear wheels: the drift's calling card
                    mdl = V.model(c[15])
                    fx, fy = math.cos(ang), math.sin(ang)
                    for ly in (-mdl.width * 0.4, mdl.width * 0.4):
                        if r.random() < 0.55:
                            lx = -mdl.length * 0.32
                            self.emit(SMOKE, x + fx * lx - fy * ly, y + fy * lx + fx * ly, 0.3,
                                      r.uniform(-1, 1), r.uniform(-1, 1), 0.6, 1.3)
            if spd > 3:
                fx, fy = math.cos(ang), math.sin(ang)
                for slot in ("WheelFL", "WheelFR", "WheelRL", "WheelRR"):
                    if not (mask & PR.SLOT_BITS[slot]) and r.random() < 0.5:
                        mdl = V.model(c[15])
                        lx, ly = SLOT_ANCHOR[slot]
                        lx, ly = lx * mdl.length / 4.4, ly * mdl.width / 2.4
                        self.emit(SPARK, x + fx * lx - fy * ly, y + fy * lx + fx * ly, 0.2,
                                  -vx * 0.3 + r.uniform(-3, 3), -vy * 0.3 + r.uniform(-3, 3), 1.0, 0.25)

    def _clear_pops(self):
        self.pops.clear()

    def _skids(self, view):
        """Skid marks get painted onto the floor texture itself, forever."""
        seen = set()
        for c in view.cars.values():
            vx, vy, ang = c[9], c[10], c[11]
            spd = math.hypot(vx, vy)
            if spd < 7:
                continue
            fx, fy = math.cos(ang), math.sin(ang)
            lat = abs(-fy * vx + fx * vy)
            if lat < 4.5 and not (c[4] & PR.CF_HANDBRAKE):
                continue
            seen.add(c[0])
            pts = []
            for lx, ly in ((-1.4, -1.0), (-1.4, 1.0)):
                wx = c[7] + fx * lx - fy * ly
                wy = c[8] + fy * lx + fx * ly
                pts.append((wx, wy))
            prev = self.skid_prev.get(c[0])
            if prev:
                for a, b in zip(prev, pts):
                    pa = (int(a[0] * FLOOR_PPM), int(a[1] * FLOOR_PPM))
                    pb = (int(b[0] * FLOOR_PPM), int(b[1] * FLOOR_PPM))
                    if abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) < 10:
                        pygame.draw.line(self.floor_map, (38, 38, 46), pa, pb, 1)
                        self._skid_hires(a, b)
            self.skid_prev[c[0]] = pts
            if self.rng.random() < 0.35:
                self.emit(DUST, c[7] - fx * 2, c[8] - fy * 2, 0.2, -vx * 0.05, -vy * 0.05, 0.3, 0.6)
        for k in list(self.skid_prev):
            if k not in seen:
                del self.skid_prev[k]

    def _skid_hires(self, a, b):
        """(v0.19) A skid segment (metres) for the hi-res street: logged against every chunk it
        touches (so a chunk built later still has it) and drawn into any that are built now.
        The log is bounded: SKID_LOG_PER_CHUNK segments a chunk, oldest dropped first."""
        cm = C.FLOOR_CHUNK_M
        seg = (a[0], a[1], b[0], b[1])
        keys = {(int(x // cm), int(y // cm)) for x, y in (a, b)}
        for ix, iy in keys:
            log = self._skid_log.get((ix, iy))
            if log is None:
                log = self._skid_log[(ix, iy)] = deque(maxlen=C.SKID_LOG_PER_CHUNK)
            log.append(seg)
            ch = self._chunks.get((ix, iy, self.kw))
            if ch is not None:
                ppm = C.PPM * self.kw
                x0, y0 = ix * cm, iy * cm
                pygame.draw.line(ch, (38, 38, 46), ((a[0] - x0) * ppm, (a[1] - y0) * ppm),
                                 ((b[0] - x0) * ppm, (b[1] - y0) * ppm), max(1, int(round(0.25 * ppm))))

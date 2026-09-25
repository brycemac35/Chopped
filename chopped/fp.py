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
"""

import math
import random

import pygame

from . import config as C
from .config import clamp
from . import mapgen as M
from . import fpart as FA
from . import sim as S
from . import protocol as PR
from .art import P, PLAYER_COLORS, SKINS, HAIRS, SHIRTS, PixelFont, shade
from .parts import SLOT_ANCHOR, NO_PART, PART_IDS
from . import vehicles as V

GNOME_IDX = PART_IDS.index("gnome")

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


class FPRenderer:
    def __init__(self, cmap, map_surf, vw, vh):
        self.map = cmap
        self.vw, self.vh = vw, vh
        self.hor0 = vh // 2
        self.hor = self.hor0          # moves with pitch (looking up/down: Build-engine y-shearing)
        self.fov = math.radians(C.FP_FOV)
        self.tanh = math.tan(self.fov / 2)
        self.D = (vw / 2) / self.tanh
        self.view = pygame.Surface((vw, vh)).convert()
        self.font = PixelFont()
        self.rng = random.Random(9)
        self._build_walls()
        n = cmap.n
        size = int(n * T * FLOOR_PPM)
        self.floor_map = pygame.transform.scale(map_surf, (size, size)).convert()
        # the benches are 3D objects here; scrub their flat top-down drawings off the floor
        for bx, by, bw, bh in (cmap.sell_bench, cmap.tune_bench):
            self.floor_map.fill(P["concrete"], (int(bx * FLOOR_PPM) - 2, int(by * FLOOR_PPM) - 2,
                                                int(bw * FLOOR_PPM) + 6, int(bh * FLOOR_PPM) + 6))
        if getattr(cmap, "bail_desk", None) is not None:      # (and the precinct desk: it's 3D too)
            bx, by, bw, bh = cmap.bail_desk
            self.floor_map.fill(FA.PRECINCT_LINO, (int(bx * FLOOR_PPM) - 2, int(by * FLOOR_PPM) - 2,
                                                  int(bw * FLOOR_PPM) + 6, int(bh * FLOOR_PPM) + 12))
        # (v0.9) the shop has a roof now: its floor is in the shade
        gx, gy, gw, gh = cmap.garage_rect
        shadow = pygame.Rect(int(gx * FLOOR_PPM), int(gy * FLOOR_PPM), int(gw * FLOOR_PPM), int(gh * FLOOR_PPM))
        self.floor_map.fill((200, 200, 212), shadow, special_flags=pygame.BLEND_RGB_MULT)
        self.roof_tex = FA.roof_texture(gw, gh, ROOF_PPM).convert()
        self.roof_tex.set_colorkey(ROOF_KEY)
        self.roof_layer = pygame.Surface((vw, vh)).convert()
        self.roof_layer.set_colorkey(ROOF_KEY)
        self.roof_clip = None         # per column: (depth where the roof ends, screen row it ends on)
        self.door_open = 1.0          # the shop's roller door: 0 down .. 1 up (from its TRAP row)
        self.sky_h = int(vh * 0.95)   # tall enough to look up into
        self.skies = {k: FA.make_sky(k, 4 * vw, self.sky_h) for k in FA.SKY_KEYS}
        self.hires = None             # the car the chase camera is following: drawn in more detail
        self.big_heads = False        # F9. You know you want to.
        self._build_static_sprites()
        self.car_cache = {}
        self.person_cache = {}
        self.model_cache = {}
        self.icon_big = {}
        self.particles = []
        self.explosions = []
        self.tracers = []          # [x0, y0, x1, y1, weapon, life]
        self.skid_prev = {}
        self.flash = None          # (colour, strength)
        self.shake = 0.0
        self.zbuf = [1e9] * vw
        self.ray_k = [(2.0 * (x + 0.5) / vw - 1.0) * self.tanh for x in range(vw)]
        # per-frame fog/darkness overlay for the floor and for sprites
        self._fog_rows = None
        self._fog_key = None
        self.person_keys = {}
        self.pops = set()             # cars that backfired since the last frame
        # (v0.9) cosmetic sillies: hats knocked off, pigeons, cars in the air
        self.hat_off = set()          # npc ids whose hat is in the road now
        self.flying_hats = []         # [x, y, z, vx, vy, vz, spin, style, life]
        self.air_t0 = {}              # car id -> (time it left the ramp, hang time)
        self._init_pigeons()

    # ------------------------------------------------------------------ setup
    def _build_walls(self):
        """Every wall tile gets a texture id and a height. Buildings keep one
        height and style across all their tiles, so they read as buildings."""
        cm = self.map
        n = cm.n
        self.wall_def = [None]                     # index 0 = no wall
        self.inner_plain = {}                      # sign wall -> the same wall without the sign (back face)
        self.wall_of = [0] * (n * n)
        self.tex_cache = {}
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
                    self.wall_of[y * n + x] = def_id(("brick", sign))
        self.edge_def = def_id(("concrete",))
        # (v0.9) the roller door: not a tile, a line between the shop's last covered row and the
        # apron. The ray march checks for it when it steps across that line (see _walls)
        self.door_rows = (oy + b - 2, oy + b - 1)
        self.door_cols = (ox + 1, ox + b - 2)
        first = (b - 2 - 3) // 2                       # HONK TO OPEN, across the middle three bays...
        self.door_defs = []
        for k in range(b - 2):
            sign = 1 if first <= k < first + 3 else 0
            self.door_defs.append(def_id(("door", k, sign, first)))
            if sign:                                   # ...on the street side only
                self.inner_plain[def_id(("door", k, 1, first))] = def_id(("door", k, 0, first))

    def _wall_tex(self, did, night):
        key = (did, night)
        wt = self.tex_cache.get(key)
        if wt is None:
            d = self.wall_def[did]
            if d[0] == "bld":
                surf = FA.facade(d[1], d[2], d[3], night)
            elif d[0] == "precinct":
                surf = FA.precinct_wall(64, night)
                if d[1]:
                    sign = pygame.Surface((FA.TEX, 10), pygame.SRCALPHA)
                    sign.fill((30, 60, 150))
                    self.font.draw(sign, "POLICE", FA.TEX // 2, 2, P["white"], None, align="center")
                    surf.blit(sign, (0, 14))
            elif d[0] == "door":
                surf = FA.roller_door(d[1], night)
                first = d[3]
                if d[2]:
                    sign = pygame.Surface((FA.TEX * 3, 9), pygame.SRCALPHA)
                    self.font.draw(sign, "HONK TO OPEN", FA.TEX * 3 // 2, 1, (250, 232, 80), (0, 0, 0),
                                   align="center")
                    surf.blit(sign, (-(d[1] - first) * FA.TEX, 18))
            elif d[0] == "brick":
                surf = FA.brick_wall(48, night, sign=d[1] >= 0)
                if d[1] >= 0:
                    sign = pygame.Surface((FA.TEX * 3, 12), pygame.SRCALPHA)
                    self.font.draw(sign, "CHOP SHOP", FA.TEX * 3 // 2, 3, P["gold"], (0, 0, 0), align="center")
                    surf.blit(sign, (-d[1] * FA.TEX, 12))
            else:
                surf = FA.concrete_wall(48, night)
            wt = self.tex_cache[key] = FA.WallTex(surf)
        return wt

    def wall_height(self, did):
        d = self.wall_def[did]
        if d[0] == "bld":
            return d[2] * FA.FLOOR_M
        if d[0] == "precinct":
            return 8.0
        return C.ROOF_H                     # the shop's walls (and its door) hold up its roof

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
        self.benches = []
        for rect, is_sell in ((cm.sell_bench, True), (cm.tune_bench, False)):
            bx, by, bw, bh = rect
            self.benches.append((bx + bw / 2, by + bh / 2, is_sell, bw, bh))
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
    def _car_sprite(self, row, az, steps=None, ppm=12):
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
        spr = self.car_cache.get(key)
        if spr is None:
            if len(self.car_cache) > C.SPRITE_CACHE_CARS:
                self.car_cache.clear()
            spr = self.car_cache[key] = FA.render_boxes(
                FA.car_boxes(kind, color, mask, styles, dmg, lights, model, livery, extras, extras2),
                idx * TWO_PI / steps, ppm)
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

    def _person_sprite(self, shirt, skin, hair, frame, extra, down, az, gun=0, outfit=None):
        n = C.PERSON_ANGLES
        idx = int(round(az / (TWO_PI / n))) % n
        key = (shirt, skin, hair, frame, extra, down, idx, gun, self.big_heads, outfit)
        spr = self.person_cache.get(key)
        if spr is None:
            if len(self.person_cache) > C.SPRITE_CACHE_PEOPLE:
                self.person_cache.clear()
            boxes = FA.person_boxes(shirt, skin, hair, frame, extra, gun=gun, outfit=outfit)
            if self.big_heads:
                boxes = FA.big_head(boxes)
            if down:
                boxes = FA.lying(boxes)
            spr = self.person_cache[key] = FA.render_boxes(boxes, idx * TWO_PI / n, 16)
        return spr, 16

    def _dog_sprite(self, frame, trousers, down, az):
        n = C.PERSON_ANGLES
        idx = int(round(az / (TWO_PI / n))) % n
        key = ("dog", frame, trousers, down, idx)
        spr = self.model_cache.get(key)
        if spr is None:
            boxes = FA.dog_boxes(frame, trousers)
            if down:
                boxes = [(x0, x1, y0, y1, z0 * 0.4, z1 * 0.4, c) for x0, x1, y0, y1, z0, z1, c in boxes]
            spr = self.model_cache[key] = FA.render_boxes(boxes, idx * TWO_PI / n, 20)
        return spr, 20

    def _model_sprite(self, name, boxes_fn, az, steps=None, ppm=16):
        steps = C.PROP_ANGLES if not steps or steps == 8 else steps     # (v0.8: 8 was choppy up close)
        idx = int(round(az / (TWO_PI / steps))) % steps
        key = (name, idx, steps)
        spr = self.model_cache.get(key)
        if spr is None:
            spr = self.model_cache[key] = FA.render_boxes(boxes_fn(), idx * TWO_PI / steps, ppm)
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
        self._sky(surf, yaw, tod)
        self._floor(surf, cx, cy, yaw, eye, dark)
        for t in getattr(view, "traps", {}).values():
            if t[1] == S.TRAP_DOOR:
                self.door_open = t[5]
        self._walls(surf, cx, cy, yaw, eye, dark, night)
        self._roof(surf, cx, cy, yaw, eye)
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

    def _sky(self, surf, yaw, tod):
        a, b, t = sky_mix(tod)
        sw = 4 * self.vw
        off = int((yaw % TWO_PI) / TWO_PI * sw)
        for key, alpha in ((a, 255), (b, int(255 * t))):
            if alpha <= 3:
                continue
            sky = self.skies[key]
            sky.set_alpha(None if alpha >= 255 else alpha)
            # the sky's bottom edge sits on the horizon, wherever pitch put it
            h = min(self.hor, self.sky_h)
            sy, dy = self.sky_h - h, self.hor - h
            if dy > 0 and alpha >= 255:
                surf.fill(sky.get_at((0, 0))[:3], (0, 0, self.vw, dy))       # above the top of the gradient
            surf.blit(sky, (0, dy), pygame.Rect(off, sy, min(self.vw, sw - off), h))
            if sw - off < self.vw:
                surf.blit(sky, (sw - off, dy), pygame.Rect(0, sy, self.vw - (sw - off), h))
        self.skies[b].set_alpha(None)

    def _floor(self, surf, cx, cy, yaw, eye, dark):
        R = int(C.FP_FLOOR_DIST * FLOOR_PPM)
        px, py = int(cx * FLOOR_PPM), int(cy * FLOOR_PPM)
        crop = pygame.Surface((2 * R, 2 * R)).convert()
        crop.fill(P["void"])
        crop.blit(self.floor_map, (0, 0), pygame.Rect(px - R, py - R, 2 * R, 2 * R))
        rot = pygame.transform.rotate(crop, math.degrees(yaw) + 90.0)
        rw, rh = rot.get_size()
        ox, oy = rw / 2.0, rh / 2.0
        hor, vw, vh, D, th = self.hor, self.vw, self.vh, self.D, self.tanh
        haze = shade((150, 150, 160), 1.0 - 0.8 * dark)
        maxd = C.FP_FLOOR_DIST - 2
        scale = pygame.transform.scale
        for r in range(hor + 1, vh):
            d = eye * D / (r - hor + 0.5)
            if d > maxd:
                surf.fill(haze, (0, r, vw, 1))
                continue
            hw = d * th * FLOOR_PPM
            y = int(oy - d * FLOOR_PPM)
            x0 = int(ox - hw)
            w = max(1, int(2 * hw))
            if y < 0 or x0 < 0 or x0 + w > rw:
                surf.fill(haze, (0, r, vw, 1))
                continue
            surf.blit(scale(rot.subsurface((x0, y, w, 1)), (vw, 1)), (0, r))
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

    def _walls(self, surf, cx, cy, yaw, eye, dark, night):
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
        up = self.door_open
        door_on = up < 0.98                                  # (all the way up: nothing to hit)
        dra, drb = self.door_rows
        dc0, dc1 = self.door_cols
        door_defs = self.door_defs
        for x, k in enumerate(self.ray_k):
            dx, dy = ca + rx * k, sa + ry * k
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
            did = 0
            side = 0
            door_at = None
            for _ in range(160):
                if sdx < sdy:
                    sdx += ddx
                    mx += sx
                    side = 0
                else:
                    sdy += ddy
                    my += sy
                    side = 1
                    if door_on and dc0 <= mx <= dc1 and ((sy > 0 and my == drb) or (sy < 0 and my == dra)):
                        # the shop's roller door, across the front
                        if up <= 0.01:
                            did = door_defs[mx - dc0]      # (all the way down: it's a wall)
                            break
                        # half up: remember it, keep marching to whatever's behind it, and draw
                        # the door over that afterwards (so the gap under it isn't sky)
                        door_at = (door_defs[mx - dc0], (sdy - ddy) * T)
                if 0 <= mx < n and 0 <= my < n:
                    did = wall_of[my * n + mx]
                    if did:
                        break
                else:
                    did = self.edge_def
                    break
            if not did:
                zbuf[x] = 1e9
                if door_at is not None:
                    self._door_slice(surf, x, dx, dy, door_at, cx, cy, eye, base_level, night)
                continue
            dist = ((sdx - ddx) if side == 0 else (sdy - ddy)) * T
            if dist < 0.05:
                dist = 0.05
            zbuf[x] = dist
            hit = (cy + dist * dy) if side == 0 else (cx + dist * dx)
            u = int((hit % T) / T * FA.TEX)
            if (side == 0 and dx < 0) or (side == 1 and dy > 0):
                u = FA.TEX - 1 - u                          # so text reads the right way round (v0.8: it
                                                            # didn't -- CHOP SHOP had been POHS POHC for ages)
            if did in self.inner_plain and not (side == 1 and dy < 0):
                did = self.inner_plain[did]                 # (a one-sided sign: only the street face has it)
            wt = self._wall_tex(did, night)
            H = self.wall_height(did)
            level = base_level + int(dist / 11.0) + side
            col = wt.cols[level if level < FA.SHADES else FA.SHADES - 1][u]
            th = wt.h
            top = hor - (H - eye) * D / dist
            bot = hor + eye * D / dist
            h = bot - top
            if h < 1:
                continue
            if top >= 0 and bot <= vh:
                blit(scale(col, (1, int(bot) - int(top) or 1)), (x, int(top)))
            else:
                # up close: only scale the part of the texture that's on screen
                y0, y1 = max(0.0, top), min(float(vh), bot)
                if y1 <= y0:
                    continue
                t0 = (y0 - top) / h * th
                t1 = (y1 - top) / h * th
                ti0 = min(th - 1, int(t0))
                ti1 = max(ti0 + 1, min(th, int(math.ceil(t1))))
                piece = col.subsurface((0, ti0, 1, ti1 - ti0))
                # stretch so texel edges land where they should
                py0 = top + ti0 / th * h
                ph = (ti1 - ti0) / th * h
                blit(scale(piece, (1, max(1, int(ph)))), (x, int(py0)))
            if door_at is not None:
                self._door_slice(surf, x, dx, dy, door_at, cx, cy, eye, base_level, night)

    def _door_slice(self, surf, x, dx, dy, door_at, cx, cy, eye, base_level, night):
        """A half-open roller door, drawn over whatever the ray found behind it."""
        did, dist = door_at
        dist = max(0.05, dist)
        self.zbuf[x] = min(self.zbuf[x], dist)
        u = int(((cx + dist * dx) % T) / T * FA.TEX)
        if dy > 0:
            u = FA.TEX - 1 - u                 # (the same flip rule as the walls: side 1)
        if did in self.inner_plain and not dy < 0:
            did = self.inner_plain[did]
        wt = self._wall_tex(did, night)
        H = self.wall_height(did)
        level = min(FA.SHADES - 1, base_level + int(dist / 11.0) + 1)
        col = wt.cols[level][u]
        th = wt.h
        cut = min(th - 1, int(self.door_open * th))
        col = col.subsurface((0, cut, 1, th - cut))
        hor, vh, D = self.hor, self.vh, self.D
        top = hor - (H - eye) * D / dist
        bot = hor - (self.door_open * H - eye) * D / dist
        y0, y1 = max(0, int(top)), min(vh, int(bot))
        if y1 - y0 < 1:
            return
        if top >= 0 and bot <= vh:
            surf.blit(pygame.transform.scale(col, (1, y1 - y0)), (x, y0))
        else:
            h = bot - top
            t0 = int((y0 - top) / h * (th - cut))
            t1 = max(t0 + 1, min(th - cut, int(math.ceil((y1 - top) / h * (th - cut)))))
            piece = col.subsurface((0, t0, 1, t1 - t0))
            surf.blit(pygame.transform.scale(piece, (1, y1 - y0)), (x, y0))

    def _roof(self, surf, cx, cy, yaw, eye):
        """(v0.9) The shop's roof: a mode-7 ceiling, the floor trick upside down. Drawn
        after the walls, but only where it's nearer than them (a tall building seen out
        of the front of the shop is behind the roof's edge, not in front of it). From
        outside you only see it through the front, and only if the door's up."""
        self.roof_clip = None
        gx, gy, gw, gh = self.map.garage_rect
        inside = gx <= cx <= gx + gw and gy <= cy <= gy + gh
        if not inside:
            if cy < gy + gh or self.door_open < 0.3 or abs(cx - (gx + gw / 2)) > 60 or cy > gy + gh + 45:
                return
        rh = C.ROOF_H - eye
        if rh <= 0.2:
            return
        hor, vw, D, th = self.hor, self.vw, self.D, self.tanh
        ca, sa = math.cos(yaw), math.sin(yaw)
        far = max(math.hypot(cx - x, cy - y) for x in (gx, gx + gw) for y in (gy, gy + gh))
        r_lo = 0
        r_hi = min(hor, int(hor - rh * D / far))
        if r_hi <= r_lo:
            return
        rot = pygame.transform.rotate(self.roof_tex, math.degrees(yaw) + 90.0)
        RW, RHt = rot.get_size()
        # where the camera lands in the rotated texture (forward = up the image, right = right)
        vx, vy = (gx + gw / 2 - cx) * ROOF_PPM, (gy + gh / 2 - cy) * ROOF_PPM
        ox = RW / 2.0 - (-vx * sa + vy * ca)
        oy = RHt / 2.0 + (vx * ca + vy * sa)
        layer = self.roof_layer
        layer.fill(ROOF_KEY, (0, r_lo, vw, r_hi - r_lo))
        scale = pygame.transform.scale
        drawn = False
        for r in range(r_lo, r_hi):
            d = rh * D / (hor - r + 0.5)
            y = int(oy - d * ROOF_PPM)
            if y < 0 or y >= RHt:
                continue
            hw = d * th * ROOF_PPM
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
        for x in range(vw):
            z = zbuf[x]
            if z < 1e8:
                rz = int(hor - rh * D / z)
                if rz < r_hi:
                    rz = max(r_lo, rz)
                    layer.fill(ROOF_KEY, (x, rz, 1, r_hi - rz))
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
            az = math.atan2(by - cy, bx - cx)
            add(bx, by, lambda a=az, s=is_sell, w=bw, h=bh: self._model_sprite(
                ("bench", s), lambda: FA.bench_boxes(s, w, h), a, 8, 10))
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
        for t in getattr(view, "traps", {}).values():
            if t[1] == S.TRAP_SMOKE:
                continue                                        # (smoke is particles: see smoke_clouds)
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
                        lambda s=col, k=SKINS[drv[0] % 4], h=HAIRS[drv[0] % 6], a=az2:
                        self._person_sprite(s, k, h, 0, None, False, a), z=0.25)
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
            add(p[4], p[5], lambda s=shirt, k=SKINS[p[0] % 4], h=HAIRS[p[0] % 6], f=fr, e=extra,
                dn=down, a=az, g=gun, o=outfit: self._person_sprite(s, k, h, f, e, dn, a, g, o), z=z, tag=("name", p))
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
            add(d[1], d[2], lambda a=az: self._model_sprite("dolly", FA.dolly_boxes, a, None, 16),
                tag=("dolly", d[4]))
        for e in self.explosions:
            add(e[0], e[1], None, z=1.2, tag=("boom", e))

        items.sort(key=lambda it: -it[0])
        zbuf = self.zbuf
        hor, D, vw = self.hor, self.D, self.vw
        for depth, lat, img_fn, z, tag in items:
            sx = vw / 2 + lat / depth * D
            if tag is not None and tag[0] == "boom":
                self._draw_boom(surf, tag[1], sx, depth, eye, dt)
                continue
            if img_fn is None:
                # floating words over something ("NOM NOM"), if it's not behind a wall
                col_ = int(sx)
                if tag is not None and tag[0] == "say" and depth < 50 and 0 <= col_ < vw and depth < zbuf[col_]:
                    self.font.draw(surf, tag[1], col_, int(hor + (eye - z) * D / depth), P["gold"], align="center")
                continue
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
            # which columns are in front of the walls?
            runs = []
            start = None
            for col in range(x0, x1):
                if depth < zbuf[col]:
                    if start is None:
                        start = col
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
                    mid = (a + b) // 2
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
                    self.font.draw(surf, p[13], int(sx), top - 8, col, align="center")
                    if p[2] == S.CUFFED:
                        self.font.draw(surf, "BUSTED", int(sx), top - 15, P["danger"], align="center")
                elif tag[0] == "mark" and depth < 70:
                    bob = math.sin(now * 4 + tag[2]) * 0.12
                    my = int(ground - (2.3 + bob) * D / depth)
                    r = max(3, min(8, int(0.35 * D / depth)))
                    pygame.draw.polygon(surf, P["ink"], [(sx - r - 1, my - r - 1), (sx + r + 1, my - r - 1), (sx, my + 1)])
                    pygame.draw.polygon(surf, tag[1], [(sx - r, my - r), (sx + r, my - r), (sx, my)])
                elif tag[0] == "crate" and depth < 9:
                    label, price = S.MARKET[tag[1]]
                    self.font.draw(surf, "%s $%d" % (label.split(" (")[0], price), int(sx),
                                   int(ground - 1.3 * D / depth), P["gold"], align="center")
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
                mx = (pts[0][0] + pts[1][0]) // 2 + self.rng.randint(-3, 3)
                my = (pts[0][1] + pts[1][1]) // 2 + self.rng.randint(-3, 3)
                pygame.draw.lines(surf, (255, 230, 80), False, [pts[0], (mx, my), pts[1]], 1)
            else:
                pygame.draw.line(surf, TRACER_COL, pts[0], pts[1], 1)
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
                pts.append((int(wx * FLOOR_PPM), int(wy * FLOOR_PPM)))
            prev = self.skid_prev.get(c[0])
            if prev:
                for a, b in zip(prev, pts):
                    if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 10:
                        pygame.draw.line(self.floor_map, (38, 38, 46), a, b, 1)
            self.skid_prev[c[0]] = pts
            if self.rng.random() < 0.35:
                self.emit(DUST, c[7] - fx * 2, c[8] - fy * 2, 0.2, -vx * 0.05, -vy * 0.05, 0.3, 0.6)
        for k in list(self.skid_prev):
            if k not in seen:
                del self.skid_prev[k]

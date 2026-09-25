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
from .parts import SLOT_ANCHOR, NO_PART
from . import vehicles as V

T = C.TILE_M
FLOOR_PPM = 4
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

    # ------------------------------------------------------------------ setup
    def _build_walls(self):
        """Every wall tile gets a texture id and a height. Buildings keep one
        height and style across all their tiles, so they read as buildings."""
        cm = self.map
        n = cm.n
        self.wall_def = [None]                     # index 0 = no wall
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
        for y in range(n):
            for x in range(n):
                if cm.tiles[y * n + x] == M.WALL:
                    sign = x - (mid - 1) if (y == oy and mid - 1 <= x <= mid + 1) else -1
                    self.wall_of[y * n + x] = def_id(("brick", sign))
        self.edge_def = def_id(("concrete",))

    def _wall_tex(self, did, night):
        key = (did, night)
        wt = self.tex_cache.get(key)
        if wt is None:
            d = self.wall_def[did]
            if d[0] == "bld":
                surf = FA.facade(d[1], d[2], d[3], night)
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
        return 6.0

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

    # ------------------------------------------------------------------ sprites
    def _car_sprite(self, row, az, steps=16, ppm=12):
        (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, drv, psg, dmg,
         model, livery, extras, extras2) = row[:19]
        idx = int(round(az / (TWO_PI / steps))) % steps
        lights = 0
        if kind == S.COP and not extras2 & PR.CX_PATROL:
            lights |= self._phase
        if flags & PR.CF_ALARM and self._phase:
            lights |= 2
        if extras & 8:
            lights |= 4                                  # NOS: blue fire out the back
        key = (kind, color, mask, styles, dmg, lights, idx, model, livery, extras & 0xF8, extras2 & 1, steps, ppm)
        spr = self.car_cache.get(key)
        if spr is None:
            if len(self.car_cache) > 1500:
                self.car_cache.clear()
            spr = self.car_cache[key] = FA.render_boxes(
                FA.car_boxes(kind, color, mask, styles, dmg, lights, model, livery, extras, extras2),
                idx * TWO_PI / steps, ppm)
        return spr, ppm

    def _person_look(self, eid, kind):
        k = self.person_keys.get((eid, kind))
        if k is None:
            r = random.Random(eid * 7919)
            if kind == S.CLOWN:
                k = ((250, 250, 250), (250, 240, 235), (255, 120, 40), "clown")
            elif kind == S.OWNER:
                k = ((236, 150, 190), r.choice(SKINS), r.choice(HAIRS), "owner")
            else:
                k = (r.choice(SHIRTS), r.choice(SKINS), r.choice(HAIRS), None)
            self.person_keys[(eid, kind)] = k
        return k

    def _person_sprite(self, shirt, skin, hair, frame, extra, down, az, gun=0):
        idx = int(round(az / (TWO_PI / 8))) % 8
        key = (shirt, skin, hair, frame, extra, down, idx, gun, self.big_heads)
        spr = self.person_cache.get(key)
        if spr is None:
            if len(self.person_cache) > 2000:
                self.person_cache.clear()
            boxes = FA.person_boxes(shirt, skin, hair, frame, extra, gun=gun)
            if self.big_heads:
                boxes = FA.big_head(boxes)
            if down:
                boxes = FA.lying(boxes)
            spr = self.person_cache[key] = FA.render_boxes(boxes, idx * TWO_PI / 8, 16)
        return spr, 16

    def _model_sprite(self, name, boxes_fn, az, steps=8, ppm=16):
        idx = int(round(az / (TWO_PI / steps))) % steps
        key = (name, idx)
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
        elif sid in (S.S_PISTOL, S.S_SHOTGUN) and d < 1.0:
            self.shake = max(self.shake, 2.5 if sid == S.S_SHOTGUN else 1.0)    # your own shot

    def on_shot(self, weapon, x0, y0, x1, y1):
        """A bullet's path, from the server. A streak, sparks where it landed."""
        self.tracers.append([x0, y0, x1, y1, weapon, 0.07 if weapon == S.ARM_PISTOL else 0.05])
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
        self._walls(surf, cx, cy, yaw, eye, dark, night)
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
            for _ in range(160):
                if sdx < sdy:
                    sdx += ddx
                    mx += sx
                    side = 0
                else:
                    sdy += ddy
                    my += sy
                    side = 1
                if 0 <= mx < n and 0 <= my < n:
                    did = wall_of[my * n + mx]
                    if did:
                        break
                else:
                    did = self.edge_def
                    break
            if not did:
                zbuf[x] = 1e9
                continue
            dist = ((sdx - ddx) if side == 0 else (sdy - ddy)) * T
            if dist < 0.05:
                dist = 0.05
            zbuf[x] = dist
            hit = (cy + dist * dy) if side == 0 else (cx + dist * dx)
            u = int((hit % T) / T * FA.TEX)
            if (side == 0 and dx > 0) or (side == 1 and dy < 0):
                u = FA.TEX - 1 - u                          # so text reads the right way round
            wt = self._wall_tex(did, night)
            H = self.wall_height(did)
            level = base_level + int(dist / 11.0) + side
            col = wt.cols[level if level < FA.SHADES else FA.SHADES - 1][u]
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
                t0 = (y0 - top) / h * wt.h
                t1 = (y1 - top) / h * wt.h
                ti0 = int(t0)
                ti1 = max(ti0 + 1, min(wt.h, int(math.ceil(t1))))
                piece = col.subsurface((0, ti0, 1, ti1 - ti0))
                # stretch so texel edges land where they should
                py0 = top + ti0 / wt.h * h
                ph = (ti1 - ti0) / wt.h * h
                blit(scale(piece, (1, max(1, int(ph)))), (x, int(py0)))

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
        for (x, y, item) in self.crates:
            az = math.atan2(y - cy, x - cx) - math.pi       # the crates face into the shop
            add(x, y, lambda a=az, it=item: self._model_sprite(("crate", it), lambda: FA.crate_boxes(it), a, 8, 16),
                tag=("crate", item))
        for t in getattr(view, "traps", {}).values():
            if t[5] < 0.1 and int(now * 6) % 2:
                continue                                        # about to be towed: blink
            if t[1] in (S.TRAP_BANANA, S.TRAP_DONUT):
                az = math.atan2(t[3] - cy, t[2] - cx)
                name = "banana" if t[1] == S.TRAP_BANANA else "donutbox"
                fn = FA.banana_boxes if t[1] == S.TRAP_BANANA else FA.donut_box_boxes
                add(t[2], t[3], lambda a=az, nm=name, f=fn: self._model_sprite(nm, f, a, 8, 24))
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
                    add(x, y, lambda a=az, L=seg: self._model_sprite(("spikes", L), lambda: FA.spike_boxes(L), a, 8, 16))
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
            if row[0] == self.hires:
                # the chase cam's car: more angles, more pixels (it's right there, being drifted)
                add(row[7], row[8], lambda r=row, a=az: self._car_sprite(r, a, 64, 20), tag=("smoke", row))
            else:
                add(row[7], row[8], lambda r=row, a=az: self._car_sprite(r, a), tag=self._car_marker(row))
        frame = int(now * 7) % 2
        for n in view.npcs.values():
            shirt, skin, hair, extra = self._person_look(n[0], n[1])
            az = math.atan2(n[4] - cy, n[3] - cx) - n[5]
            st = n[2]
            fr = frame if st in (PR.NS_WALK, PR.NS_FLEE, PR.NS_BRAWL) else 0
            gun = 0
            if st == PR.NS_HANDSUP:
                extra = "handsup"
            elif st == PR.NS_BRAWL and extra is None:
                extra = "fists"
            elif st == PR.NS_ARMED:
                gun = 1
            elif st == PR.NS_LAUGH and extra is None:
                extra = "laugh"
            down = st in (PR.NS_DOWN, PR.NS_CARRIED)
            z = n[6] if len(n) > 6 else 0.0
            if st == PR.NS_CARRIED:
                z -= 0.55                              # draped over a shoulder, not floating above it
            add(n[3], n[4], lambda s=shirt, k=skin, h=hair, e=extra, f=fr, dn=down, a=az, g=gun:
                self._person_sprite(s, k, h, f, e, dn, a, g), z=z)
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
            down = p[2] in (S.TUMBLE, S.CARRIED)
            if p[2] == S.CARRIED:
                z -= 0.55
            add(p[4], p[5], lambda s=shirt, k=SKINS[p[0] % 4], h=HAIRS[p[0] % 6], f=fr, e=extra,
                dn=down, a=az, g=gun: self._person_sprite(s, k, h, f, e, dn, a, g), z=z, tag=("name", p))
            if flags & PR.PF_CHUTE:
                add(p[4], p[5], lambda: (self.chute_img, 12), z=z + 1.9)
        for pk in view.pickups.values():
            ic = self._icon(bank, pk[1])
            bob = 0.12 + 0.06 * math.sin(now * 3 + pk[0])
            pz = pk[5] if len(pk) > 5 else 0.0
            add(pk[2], pk[3], lambda i=ic: (i, 12), z=bob + pz, tag=("pickup", pk[4]))
        for d in view.dollies.values():
            if d[5] == me_pid:
                continue
            az = math.atan2(d[2] - cy, d[1] - cx) - d[3]
            add(d[1], d[2], lambda a=az: self._model_sprite("dolly", FA.dolly_boxes, a, 8, 16),
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
            for a, b in runs:
                surf.blit(scaled, (a, top), pygame.Rect(a - left, 0, b - a, sh))
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

    def car_emitters(self, view, dt):
        """Fire, smoke and dragging hubs, emitted in world space."""
        r = self.rng
        for c in view.cars.values():
            (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, drv, psg, dmg) = c[:15]
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

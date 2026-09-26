"""
render.py -- draws a View (interpolated snapshot) onto the 480x270 canvas.

Performance notes, since Python + 60 fps is a knife fight:
 * the whole city is one pre-rendered surface; a frame starts with ONE blit
 * sprites + rotations are cached in art.SpriteBank
 * particles are plain lists recycled in place, drawn with surface.fill
"""

import math
import random

import pygame

from . import config as C
from . import art
from .art import P
from . import sim as S
from . import protocol as PR
from .parts import SLOT_ANCHOR
from . import vehicles as V

PPM = C.PPM
W, H = C.LOW_W, C.LOW_H

# particle kinds
SPARK, SMOKE, FIRE, DEBRIS, CONFETTI, DUST = range(6)
MAX_PARTICLES = 700
CONFETTI_COLS = [(255, 80, 80), (80, 200, 255), (255, 230, 60), (120, 230, 110), (236, 90, 206)]


class Renderer:
    def __init__(self, cmap, map_surf=None):
        self.map = cmap
        self.map_surf = map_surf if map_surf is not None else art.render_map(cmap)
        try:
            self.map_surf = self.map_surf.convert()
        except pygame.error:
            pass
        self.minimap = art.render_minimap(cmap)
        self.bank = art.SpriteBank()
        self.font = art.PixelFont()
        self.cam_x, self.cam_y = cmap.garage_center[0] * PPM, cmap.garage_center[1] * PPM
        self.shake = 0.0
        self.particles = []
        self.explosions = []       # [x, y, t]
        self.tracers = []          # [x0, y0, x1, y1, life]
        self.skid_prev = {}
        self.rng = random.Random(5)
        self.smoke_acc = 0.0
        self.person_keys = {}
        self.ox = self.oy = 0

    # ------------------------------------------------------------------ helpers
    def to_screen(self, x, y):
        return int(x * PPM - self.cam_x + W / 2 + self.ox), int(y * PPM - self.cam_y + H / 2 + self.oy)

    def on_screen(self, x, y, margin=24):
        sx, sy = self.to_screen(x, y)
        return -margin < sx < W + margin and -margin < sy < H + margin

    def emit(self, kind, x, y, vx, vy, life, color=None):
        if len(self.particles) >= MAX_PARTICLES:
            return
        self.particles.append([x, y, vx, vy, life, life, kind, color])

    def burst(self, kind, x, y, n, speed, life, color=None):
        r = self.rng
        for _ in range(n):
            a = r.uniform(0, 2 * math.pi)
            s = r.uniform(0.3, 1.0) * speed
            self.emit(kind, x, y, math.cos(a) * s, math.sin(a) * s, life * r.uniform(0.6, 1.2), color)

    def on_sfx(self, sid, x, y, me_x, me_y):
        d = math.hypot(x - me_x, y - me_y)
        near = max(0.0, 1.0 - d / 60.0)
        if sid in (S.S_CRASH, S.S_CRASH_BIG):
            big = sid == S.S_CRASH_BIG
            self.burst(SPARK, x, y, 16 if big else 8, 14, 0.4)
            self.burst(DEBRIS, x, y, 6 if big else 2, 6, 0.8, P["metal_l"])
            self.shake = max(self.shake, (5 if big else 2) * near)
        elif sid == S.S_BOOM:
            self.explosions.append([x, y, 0.0])
            self.burst(FIRE, x, y, 50, 16, 0.9)
            self.burst(SMOKE, x, y, 30, 6, 2.2)
            self.burst(SPARK, x, y, 30, 24, 0.6)
            self.burst(DEBRIS, x, y, 16, 12, 1.2, P["ink2"])
            self.shake = max(self.shake, 10 * max(near, 0.3))
        elif sid == S.S_BREAKIN:
            self.burst(DEBRIS, x, y, 10, 5, 0.5, P["glass"])
        elif sid == S.S_HONK:
            for c in CONFETTI_COLS:
                self.burst(CONFETTI, x, y, 4, 7, 1.2, c)
        elif sid == S.S_STRIP or sid == S.S_INSTALL:
            self.burst(SPARK, x, y, 5, 6, 0.25)
        elif sid == S.S_CRUSH:
            self.burst(DUST, x, y, 30, 8, 1.2)
            self.burst(DEBRIS, x, y, 12, 8, 0.8, P["metal_l"])
            self.shake = max(self.shake, 4 * near)
        elif sid == S.S_IGNITE:
            self.burst(FIRE, x, y, 20, 6, 0.6)
        elif sid == S.S_SELL:
            self.burst(CONFETTI, x, y, 6, 4, 0.8, P["money"])
        elif sid == S.S_TIRE:
            self.burst(DEBRIS, x, y, 8, 5, 0.8, P["tire"])
        elif sid == S.S_ROB:
            self.burst(CONFETTI, x, y, 5, 3, 0.7, P["money"])

    def on_shot(self, weapon, x0, y0, x1, y1):
        self.tracers.append([x0, y0, x1, y1, 0.3 if weapon == S.TRACER_TASER else 0.08, weapon])
        self.burst(SPARK, x1, y1, 3, 5, 0.2)

    # ------------------------------------------------------------------ camera
    def update_camera(self, view, dt):
        me = view.me
        if me is None:
            return
        car = view.my_car
        if car is not None:
            tx, ty = car[7] + car[9] * 0.45, car[8] + car[10] * 0.45     # look ahead where you're going
        else:
            tx, ty = me[4], me[5]
        tx, ty = tx * PPM, ty * PPM
        k = min(1.0, dt * 6.0)
        self.cam_x += (tx - self.cam_x) * k
        self.cam_y += (ty - self.cam_y) * k
        if self.shake > 0.05:
            self.ox = int(self.rng.uniform(-self.shake, self.shake))
            self.oy = int(self.rng.uniform(-self.shake, self.shake))
            self.shake *= math.exp(-dt * 8)
        else:
            self.ox = self.oy = 0
            self.shake = 0.0

    # ------------------------------------------------------------------ draw
    def draw(self, low, view, now, dt):
        self.update_camera(view, dt)
        mw, mh = self.map_surf.get_size()
        left = int(self.cam_x - W / 2 - self.ox)
        top = int(self.cam_y - H / 2 - self.oy)
        if left < 0 or top < 0 or left + W > mw or top + H > mh:
            low.fill(P["void"])
        low.blit(self.map_surf, (0, 0), pygame.Rect(left, top, W, H))
        phase = int(now * 6) % 2
        self._skids(view)
        self._traps_and_crates(low, view, now)
        self._pickups(low, view, now)
        self._dollies(low, view)
        self._npcs(low, view, now)
        self._cars(low, view, now, dt, phase)
        self._players(low, view, now)
        self._tracers(low, dt)
        self._particles(low, dt)
        self._explosions(low, dt)
        self._cameras(low, now)
        self._labels(low, view, now)
        self._shop_arrow(low, view, now)

    def _shop_arrow(self, low, view, now):
        """When you're holding the goods (a hot car or parts in hand) and the
        shop is off-screen, a blinking arrow on the screen edge points home."""
        me = view.me
        if me is None:
            return
        car = view.my_car
        hot = (car is not None and car[4] & PR.CF_WANTED) or (car is None and me[9] != 255)
        gx, gy = self.map.garage_center
        if not hot or self.map.in_garage(me[4], me[5]):
            return
        sx, sy = self.to_screen(gx, gy)
        if 8 < sx < W - 8 and 8 < sy < H - 8:
            return
        cx, cy = W / 2, H / 2
        dx, dy = sx - cx, sy - cy
        k = min((W / 2 - 16) / max(abs(dx), 1e-6), (H / 2 - 16) / max(abs(dy), 1e-6))
        ax, ay = cx + dx * k, cy + dy * k
        a = math.atan2(dy, dx)
        col = P["gold"] if int(now * 3) % 2 else P["white"]
        tip = (ax + math.cos(a) * 7, ay + math.sin(a) * 7)
        l = (ax + math.cos(a + 2.5) * 6, ay + math.sin(a + 2.5) * 6)
        r = (ax + math.cos(a - 2.5) * 6, ay + math.sin(a - 2.5) * 6)
        pygame.draw.polygon(low, P["ink"], [(tip[0] + 1, tip[1] + 1), (l[0] + 1, l[1] + 1), (r[0] + 1, r[1] + 1)])
        pygame.draw.polygon(low, col, [tip, l, r])
        dist = math.hypot(gx - me[4], gy - me[5])
        self.font.draw(low, "SHOP %dM" % dist, int(ax - math.cos(a) * 12), int(ay - math.sin(a) * 12) - 2,
                       col, align="center")

    def _skids(self, view):
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
                pts.append((int(wx * PPM), int(wy * PPM)))
            prev = self.skid_prev.get(c[0])
            if prev:
                for a, b in zip(prev, pts):
                    if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 12:
                        pygame.draw.line(self.map_surf, (40, 40, 50), a, b, 1)
            self.skid_prev[c[0]] = pts
            if self.rng.random() < 0.35:
                self.emit(DUST, c[7] - fx * 2, c[8] - fy * 2, -vx * 0.05, -vy * 0.05, 0.6)
        for k in list(self.skid_prev):
            if k not in seen:
                del self.skid_prev[k]

    def _traps_and_crates(self, low, view, now):
        for (x, y, item) in getattr(self.map, "market", ()):
            sx, sy = self.to_screen(x, y)
            if -10 < sx < W + 10 and -10 < sy < H + 10:
                low.fill(P["wood_d"], (sx - 4, sy - 4, 9, 9))
                low.fill(P["wood"], (sx - 3, sy - 3, 7, 7))
                low.fill(P["ink"], (sx - 3, sy, 7, 1))
        blink = int(now * 6) % 2
        for t in getattr(view, "traps", {}).values():
            if t[1] == S.TRAP_SMOKE:
                sx, sy = self.to_screen(t[2], t[3])
                pygame.draw.circle(low, (150, 150, 158), (sx, sy), max(2, int(C.SMOKE_SCREEN_R * PPM * (0.6 + 0.4 * t[5]))))
                continue
            if t[1] == S.TRAP_CELL:
                if t[5] > 0:
                    tr = S.Trap(t[0], t[1], t[2], t[3], t[4]).rect()
                    x0, y0 = self.to_screen(tr[0], tr[1])
                    w = max(1, int(tr[2] * PPM))
                    low.fill((50, 52, 60), (x0, y0, w, 2))
                    for k in range(0, w, 3):
                        low.fill((150, 154, 166), (x0 + k, y0, 1, 2))
                    low.fill(P["gold"], (x0 + w - 3, y0 - 1, 2, 3))          # the padlock
                continue
            if t[1] == S.TRAP_DOOR:
                # one of the shop's five doors: a shutter line across its bay, gone when it's up
                if t[5] < 0.98:
                    x0, y0 = self.to_screen(t[2] - C.DOOR_W / 2, t[3] - C.DOOR_T / 2)
                    w = max(1, int(C.DOOR_W * PPM))
                    shut = t[5] < C.DOOR_PASSABLE
                    col = (170, 172, 180) if shut else (110, 112, 120)
                    low.fill(col, (x0, y0, w, max(2, int(C.DOOR_T * PPM))))
                    for k in range(0, w, 8):
                        low.fill((90, 92, 100), (x0 + k, y0, 1, max(2, int(C.DOOR_T * PPM))))
                continue
            if t[1] == S.TRAP_GATE:
                if t[5] > 0:
                    tr = S.Trap(t[0], t[1], t[2], t[3], t[4]).rect()
                    x0, y0 = self.to_screen(tr[0], tr[1])
                    w = max(1, int(tr[2] * PPM))
                    for k in range(0, w, 3):
                        low.fill((150, 154, 166), (x0 + k, y0, 1, max(2, int(tr[3] * PPM))))
                continue
            if t[5] < 0.1 and blink:
                continue
            if t[1] in (S.TRAP_BANANA, S.TRAP_DONUT, S.TRAP_WHOOPEE):
                sx, sy = self.to_screen(t[2], t[3])
                low.fill({S.TRAP_BANANA: (250, 220, 70), S.TRAP_DONUT: (236, 130, 190)}.get(t[1], (240, 110, 170)),
                         (sx - 1, sy - 1, 3, 3))
                continue
            tr = S.Trap(t[0], t[1], t[2], t[3], t[4]).rect()
            x0, y0 = self.to_screen(tr[0], tr[1])
            w, h = max(1, int(tr[2] * PPM)), max(1, int(tr[3] * PPM))
            if x0 > W or y0 > H or x0 + w < 0 or y0 + h < 0:
                continue
            if t[1] == S.TRAP_SPIKES:
                low.fill((26, 24, 30), (x0, y0, w, h))
                step = 2
                for k in range(0, max(w, h), step):
                    px, py = (x0 + k, y0 + h // 2) if w > h else (x0 + w // 2, y0 + k)
                    low.fill(P["chrome"], (px, py, 1, 1))
            else:
                for k in range(0, max(w, h), 3):
                    col = (255, 120, 20) if (k // 3) % 2 == 0 else (245, 245, 240)
                    if w > h:
                        low.fill(col, (x0 + k, y0, min(3, w - k), h))
                    else:
                        low.fill(col, (x0, y0 + k, w, min(3, h - k)))

    def _tracers(self, low, dt):
        keep = []
        for tr in self.tracers:
            tr[4] -= dt
            if tr[4] > 0:
                keep.append(tr)
                col = (255, 230, 80) if len(tr) > 5 and tr[5] == S.TRACER_TASER else (255, 240, 170)
                pygame.draw.line(low, col, self.to_screen(tr[0], tr[1]), self.to_screen(tr[2], tr[3]))
        self.tracers = keep

    def _pickups(self, low, view, now):
        icons = self.bank.icons
        for pk in view.pickups.values():
            sx, sy = self.to_screen(pk[2], pk[3])
            if not (-10 < sx < W + 10 and -10 < sy < H + 10):
                continue
            ic = icons[pk[1]] if pk[1] < len(icons) else icons[0]
            sc = pk[4]
            if sc < 0.98:
                size = max(1, int(10 * sc))
                ic = pygame.transform.scale(ic, (size, size))
            bob = 1 if math.sin(now * 3 + pk[0]) > 0 else 0
            low.fill((20, 18, 26), (sx - 3, sy + 3, 7, 2))
            low.blit(ic, (sx - ic.get_width() // 2, sy - ic.get_height() // 2 - bob))

    def _dollies(self, low, view):
        for d in view.dollies.values():
            sx, sy = self.to_screen(d[1], d[2])
            if not (-12 < sx < W + 12 and -12 < sy < H + 12):
                continue
            spr = self.bank.dolly_at(d[3])
            low.fill((20, 18, 26), (sx - 4, sy + 3, 9, 2))
            low.blit(spr, (sx - spr.get_width() // 2, sy - spr.get_height() // 2))
            if d[4] != 255:
                ic = self.bank.icons[d[4]]
                low.blit(ic, (sx - ic.get_width() // 2, sy - ic.get_height() // 2 - 1))

    def _person_key(self, eid, kind):
        k = self.person_keys.get((eid, kind))
        if k is None:
            r = random.Random(eid * 7919)
            if kind == S.CLOWN:
                k = ((250, 250, 250), (250, 240, 235), (255, 120, 40), "clown")
            elif kind == S.OWNER:
                k = ((236, 150, 190), r.choice(art.SKINS), r.choice(art.HAIRS), "owner")
            elif kind == S.OFFICER:
                k = ((34, 44, 96), r.choice(art.SKINS), (26, 32, 70), None)        # navy, peaked cap
            elif kind in (S.GUARD, S.KEYGUARD):
                k = ((96, 104, 124), r.choice(art.SKINS), (60, 66, 84), None)
            elif kind == S.STREAKER:
                sk = r.choice(art.SKINS)
                k = (sk, sk, r.choice(art.HAIRS), None)
            elif kind == S.MIME:
                k = ((240, 240, 240), (246, 246, 246), (20, 20, 24), None)
            else:
                k = (r.choice(art.SHIRTS), r.choice(art.SKINS), r.choice(art.HAIRS), None)
            self.person_keys[(eid, kind)] = k
        return k

    def _npcs(self, low, view, now):
        frame = int(now * 6) % 2
        panic = int(now * 14) % 2
        for n in view.npcs.values():
            sx, sy = self.to_screen(n[3], n[4])
            if not (-10 < sx < W + 10 and -10 < sy < H + 10):
                continue
            if n[1] == S.DOG:
                c, sn = math.cos(n[5]), math.sin(n[5])
                low.fill((150, 100, 55), (sx - 2, sy - 2, 4, 4))
                low.fill((60, 40, 26), (int(sx + c * 3) - 1, int(sy + sn * 3) - 1, 2, 2))
                continue
            if n[1] == S.CHICKEN:
                low.fill((246, 244, 236), (sx - 1, sy - 1, 3, 3))          # (v0.9) a chicken, from above
                low.fill((220, 40, 40), (sx, sy - 2, 1, 1))
                continue
            shirt, skin, hair, extra = self._person_key(n[0], n[1])
            fr = frame if n[2] in (0, 4, 5) else panic if n[2] == 2 else 0
            z = n[6] if len(n) > 6 else 0.0
            if z > 0.1:
                low.fill((20, 18, 26), (sx - 2, sy + 2, 5, 2))            # shadow on the ground
                sy -= int(z * PPM)
            spr = self.bank.person((shirt, skin, hair, fr, extra), n[5])
            low.blit(spr, (sx - spr.get_width() // 2, sy - spr.get_height() // 2))
            if n[2] in (4, 5) and frame:
                self.font.draw(low, "!", sx, sy - 10, P["danger"], align="center")
            if n[1] == S.OWNER and frame:
                self.font.draw(low, "!", sx, sy - 10, P["danger"], align="center")
            elif n[2] == 2 and panic and (n[0] + int(now * 2)) % 3 == 0:
                self.font.draw(low, "!!", sx, sy - 10, P["white"], align="center")

    def _cars(self, low, view, now, dt, phase):
        bank = self.bank
        emit = self.emit
        r = self.rng
        for c in view.cars.values():
            (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, ang, drv, psg, dmg) = c[:15]
            if not self.on_screen(x, y, 30):
                continue
            sx, sy = self.to_screen(x, y)
            sh = bank.car_shadow_at(ang)
            low.blit(sh, (sx - sh.get_width() // 2 + 2, sy - sh.get_height() // 2 + 2))
            spr = bank.car(c, phase, ang)
            low.blit(spr, (sx - spr.get_width() // 2, sy - spr.get_height() // 2))
            spd = math.hypot(vx, vy)
            fx, fy = math.cos(ang), math.sin(ang)
            # sparks from bare hubs dragging on asphalt
            if spd > 3:
                for slot in ("WheelFL", "WheelFR", "WheelRL", "WheelRR"):
                    if not (mask & PR.SLOT_BITS[slot]) and r.random() < 0.6:
                        m = V.model(c[15])
                        lx, ly = SLOT_ANCHOR[slot]
                        lx, ly = lx * m.length / 4.4, ly * m.width / 2.4
                        wx, wy = x + fx * lx - fy * ly, y + fy * lx + fx * ly
                        emit(SPARK, wx, wy, -vx * 0.3 + r.uniform(-3, 3), -vy * 0.3 + r.uniform(-3, 3), 0.25)
            if flags & PR.CF_FIRE:
                for _ in range(3):
                    emit(FIRE, x + r.uniform(-1, 1), y + r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(-4, -1), 0.5)
                if r.random() < 0.4:
                    emit(SMOKE, x, y, r.uniform(-1, 1), r.uniform(-3, -1), 1.6)
            elif dmg >= 3 and r.random() < 0.12:
                emit(SMOKE, x + fx * 1.5, y + fy * 1.5, r.uniform(-0.5, 0.5), -1.0, 1.0)
            if (flags & PR.CF_ALARM) and phase:
                # hazards blinking. The universal signal for "crime in progress".
                for lx, ly in ((2.0, -1.0), (2.0, 1.0), (-2.0, -1.0), (-2.0, 1.0)):
                    px, py = self.to_screen(x + fx * lx - fy * ly, y + fy * lx + fx * ly)
                    low.fill((255, 170, 40), (px, py, 2, 2))
            if kind == S.COP and phase == 0:
                # a bit of flashing light spill on the road
                low.fill((255, 60, 60), (sx - 7, sy - 2, 2, 2))
                low.fill((70, 120, 255), (sx + 6, sy + 1, 2, 2))
            if flags & PR.CF_CONFUSED:
                self.font.draw(low, "?", sx + 6, sy - 14, P["gold"])
            if flags & PR.CF_HORN:
                self.font.draw(low, "HONK", sx, sy - 18, P["white"], align="center")

    def _players(self, low, view, now):
        frame = int(now * 8) % 2
        for p in view.players.values():
            (pid, color, state, flags, x, y, vx, vy, ang, h0, h1, stam, car_id, name) = p[:14]
            if state in (S.DRIVER, S.PASSENGER):
                continue
            sx, sy = self.to_screen(x, y)
            if not (-12 < sx < W + 12 and -12 < sy < H + 12):
                continue
            shirt = art.PLAYER_COLORS[color % 4]
            extra = "cuffed" if state == S.CUFFED else None
            fr = frame if (flags & PR.PF_MOVING) else 0
            if len(p) > 17 and p[17] & PR.PF2_BOX and state == S.FOOT:
                low.fill((150, 115, 75), (sx - 4, sy - 4, 9, 9))           # (v0.9) a box. Definitely a box
                low.fill((190, 150, 100), (sx - 3, sy - 3, 7, 7))
                low.fill((220, 200, 150), (sx - 3, sy, 7, 1))
                continue
            z = p[15] if len(p) > 15 else 0.0
            if z > 0.1:
                low.fill((20, 18, 26), (sx - 2, sy + 2, 5, 2))
                sy -= int(z * PPM)
            spr = self.bank.person((shirt, art.SKINS[pid % 4], art.HAIRS[pid % 6], fr, extra), ang)
            low.blit(spr, (sx - spr.get_width() // 2, sy - spr.get_height() // 2))
            # carried parts float in front of you (it's a stylistic choice)
            if h0 != 255 and state != S.TUMBLE:
                fx, fy = math.cos(ang), math.sin(ang)
                ic = self.bank.icons_small[h0]
                low.blit(ic, (sx + int(fx * 5) - 3, sy + int(fy * 5) - 3))
                if h1 != 255:
                    ic = self.bank.icons_small[h1]
                    low.blit(ic, (sx + int(fx * 5 - fy * 4) - 3, sy + int(fy * 5 + fx * 4) - 3))
            elif state == S.FOOT and len(p) > 14 and p[14] in S.GUN_SLOTS:
                fx, fy = math.cos(ang), math.sin(ang)
                n = S.GUN_LINE_LEN[p[14]]
                pygame.draw.line(low, (40, 40, 48), (sx + int(fx * 2), sy + int(fy * 2)),
                                 (sx + int(fx * n), sy + int(fy * n)), 2)
            if flags & PR.PF_SPRINT and self.rng.random() < 0.3:
                self.emit(DUST, x, y, -vx * 0.1, -vy * 0.1, 0.4)

    def _particles(self, low, dt):
        fill = low.fill
        alive = []
        cx = self.cam_x - W / 2 - self.ox
        cy = self.cam_y - H / 2 - self.oy
        fire_cols = (P["fire1"], P["fire2"], P["fire3"])
        for p in self.particles:
            p[4] -= dt
            if p[4] <= 0:
                continue
            kind = p[6]
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            if kind in (SPARK, DEBRIS, CONFETTI):
                d = math.exp(-3 * dt)
                p[2] *= d
                p[3] *= d
            else:
                d = math.exp(-1.2 * dt)
                p[2] *= d
                p[3] *= d
            alive.append(p)
            sx = int(p[0] * PPM - cx)
            sy = int(p[1] * PPM - cy)
            if not (0 <= sx < W and 0 <= sy < H):
                continue
            t = p[4] / p[5]
            if kind == SPARK:
                fill(P["fire1"] if t > 0.5 else P["fire2"], (sx, sy, 1, 1))
            elif kind == FIRE:
                fill(fire_cols[min(2, int((1 - t) * 3))], (sx, sy, 2, 2))
            elif kind == SMOKE:
                s = 2 + int((1 - t) * 4)
                fill(P["smoke"] if t < 0.5 else P["smoke_l"], (sx - s // 2, sy - s // 2, s, s))
            elif kind == DUST:
                fill((150, 146, 140), (sx, sy, 2, 2))
            else:
                fill(p[7] or P["metal_l"], (sx, sy, 1 if kind == DEBRIS else 2, 1))
        self.particles = alive

    def _explosions(self, low, dt):
        keep = []
        for e in self.explosions:
            e[2] += dt
            t = e[2]
            if t > 0.7:
                continue
            keep.append(e)
            sx, sy = self.to_screen(e[0], e[1])
            r = int(4 + t * 60)
            col = P["white"] if t < 0.1 else P["fire1"] if t < 0.25 else P["fire2"] if t < 0.45 else P["smoke"]
            pygame.draw.circle(low, col, (sx, sy), r, 0 if t < 0.25 else max(1, int(6 * (1 - t))))
        self.explosions = keep

    def _cameras(self, low, now):
        blink = int(now * 2) % 2
        for (x, y) in self.map.cameras:
            sx, sy = self.to_screen(x, y)
            if 0 <= sx < W and 0 <= sy < H:
                low.fill(P["ink"], (sx - 2, sy - 1, 5, 3))
                low.fill(P["metal_l"], (sx - 1, sy - 1, 3, 1))
                if blink:
                    low.fill(P["red"], (sx + 2, sy, 1, 1))

    def _labels(self, low, view, now):
        """Name tags in player colours so you can tell who just yeeted the Kei."""
        for p in view.players.values():
            pid, color, state = p[0], p[1], p[2]
            x, y = p[4], p[5]
            if state in (S.DRIVER, S.PASSENGER):
                car = view.cars.get(p[12])
                if car is not None:
                    x, y = car[7], car[8]
                    if state == S.PASSENGER:
                        y -= 1.4
            sx, sy = self.to_screen(x, y)
            if -40 < sx < W + 40 and -20 < sy < H + 20:
                col = art.PLAYER_COLORS[color % 4]
                self.font.draw(low, p[13], sx, sy - 16, col, align="center")
                if state == S.CUFFED:
                    self.font.draw(low, "BUSTED", sx, sy - 23, P["danger"], align="center")
                elif state == S.TUMBLE:
                    self.font.draw(low, "@#!%", sx, sy - 23, P["white"], align="center")

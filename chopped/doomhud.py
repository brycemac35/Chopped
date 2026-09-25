"""
doomhud.py -- the Doom-style status bar and first-person overlays.

Bottom bar, left to right: CASH | HEAT% | HANDS | the face | STAMINA% (or
KM/H in a car) | COPS | DAY / RENT. The face gets sweatier as the heat goes
up, grins when money comes in, and goes cross-eyed when you get run over.
Above the bar: your hands (and whatever's in them), the dolly's handles, or
the inside of whatever car you're in.
"""

import math
import random
import time
from collections import deque

import pygame

from . import config as C
from . import sim as S
from . import protocol as PR
from . import fpart as FA
from .art import P, PixelFont, PLAYER_COLORS, CAR_COLORS, GLYPHS, SKINS, shade
from .parts import PART_IDS, PART_DEFS, NO_PART

W, H = C.LOW_W, C.LOW_H
BAR_H = 32
VIEW_H = H - BAR_H
BX = (W - 480) // 2      # the classic 480-wide bar sits in the middle; ARMS and GEAR panels flank it
TOAST_COLORS = {S.T_WHITE: P["white"], S.T_MONEY: P["money"], S.T_BAD: P["danger"],
                S.T_INFO: P["gold"], S.T_COP: (130, 170, 255)}
WITNESS_TEXT = {
    S.W_COP: ("A COP SEES YOU +5/S", (130, 170, 255)),
    S.W_PED: ("A WITNESS SEES YOU +3/S", P["gold"]),
    S.W_OWNER: ("THE OWNER SEES YOU +3/S", P["danger"]),
    S.W_CAMERA: ("STREET CAMERA SEES THE CAR +2/S", P["gold"]),
}
# the big red digits: top rows bright, bottom rows dark, like they were chiselled
BIG_RED = ((255, 80, 60), (236, 50, 40), (200, 30, 30), (160, 20, 20), (120, 14, 14))
BIG_GOLD = ((255, 236, 120), (240, 200, 70), (220, 170, 50), (190, 140, 40), (150, 100, 30))
BIG_BLUE = ((170, 200, 255), (130, 170, 255), (90, 130, 240), (60, 100, 210), (40, 70, 170))


WEAPON_LABELS = ("HANDS", "PISTOL", "SHOTGUN", "SPIKES", "BLOCKS")


class Pen:
    """Draws in the original 480-wide coordinates and scales to whatever the
    real view is (640 wide since v0.7), so the fists and guns grow with the
    screen instead of shrinking into the corner. Whole pixels, no blur."""
    BASE_W = 480

    def __init__(self, surf):
        self.s = surf
        self.k = k = surf.get_width() / float(self.BASE_W)
        self.size = (self.BASE_W, int(round(surf.get_height() / k)))

    def _pt(self, p):
        return (int(round(p[0] * self.k)), int(round(p[1] * self.k)))

    def _len(self, v):
        return max(1, int(round(v * self.k)))

    def poly(self, col, pts, width=0):
        pygame.draw.polygon(self.s, col, [self._pt(p) for p in pts], width and self._len(width))

    def rect(self, col, r, width=0, border_radius=-1):
        x, y, w, h = r
        pygame.draw.rect(self.s, col, (*self._pt((x, y)), self._len(w), self._len(h)),
                         width and self._len(width), border_radius=self._len(border_radius) if border_radius > 0 else -1)

    def fill(self, col, r):
        x, y, w, h = r
        x0, y0 = self._pt((x, y))
        x1, y1 = self._pt((x + w, y + h))
        self.s.fill(col, (x0, y0, max(1, x1 - x0), max(1, y1 - y0)))

    def circle(self, col, c, r, width=0):
        pygame.draw.circle(self.s, col, self._pt(c), self._len(r), width and self._len(width))

    def line(self, col, a, b, width=1):
        pygame.draw.line(self.s, col, self._pt(a), self._pt(b), self._len(width))

    def blit(self, img, pos):
        self.s.blit(img, self._pt(pos))

    def text(self, font, text, x, y, col, **kw):
        font.draw(self.s, text, *self._pt((x, y)), col, **kw)


def mmss(t):
    t = max(0, int(math.ceil(t)))
    return "%d:%02d" % (t // 60, t % 60)


class DoomHud:
    def __init__(self, font, bank, minimap):
        self.font = font
        self.bank = bank
        self.minimap = minimap
        self.toasts = deque(maxlen=5)
        self.help_until = time.perf_counter() + 20.0
        self.bar = self._make_bar()
        self._big = {}
        self._faces = {}
        self._panels = {}
        self.look, self.look_t = 0, 0.0
        self.grin_until = 0.0
        self.last_cash = None
        self.day_seen = None
        self.day_banner_until = 0.0
        self.rng = random.Random(3)
        self.icons2 = [pygame.transform.scale(i, (16, 16)) for i in bank.icons]
        self.icons6 = {}

    # ------------------------------------------------------------------ pieces
    def _make_bar(self):
        s = pygame.Surface((W, BAR_H))
        s.fill((92, 90, 96))
        rng = random.Random(42)
        for _ in range(W * BAR_H // 5):
            s.set_at((rng.randrange(W), rng.randrange(BAR_H)),
                     rng.choice(((80, 78, 84), (106, 104, 110), (72, 70, 76))))
        s.fill((130, 128, 134), (0, 0, W, 1))
        s.fill((50, 48, 54), (0, BAR_H - 1, W, 1))
        for x in (0, 96, 168, 228, 262, 330, 372, 480):
            s.fill((50, 48, 54), (BX + x, 2, 1, BAR_H - 4))
            s.fill((130, 128, 134), (BX + x + 1, 2, 1, BAR_H - 4))
        s.fill((30, 28, 34), (BX + 230, 1, 30, BAR_H - 2))       # face well
        return s

    def big(self, text, ramp=BIG_RED):
        key = (text, ramp)
        s = self._big.get(key)
        if s is not None:
            return s
        text = text.upper()
        w = sum(len(GLYPHS.get(ch, GLYPHS["?"])[0]) * 3 + 2 for ch in text) + 2
        s = pygame.Surface((max(1, w), 17), pygame.SRCALPHA)
        x = 0
        for ch in text:
            g = GLYPHS.get(ch, GLYPHS["?"])
            for gy, row in enumerate(g):
                for gx, c in enumerate(row):
                    if c == "#":
                        s.fill((40, 8, 8), (x + gx * 3 + 1, gy * 3 + 1, 3, 3))
            for gy, row in enumerate(g):
                for gx, c in enumerate(row):
                    if c == "#":
                        s.fill(ramp[gy], (x + gx * 3, gy * 3, 3, 3))
                        s.fill(shade(ramp[gy], 1.15), (x + gx * 3, gy * 3, 3, 1))
            x += len(g[0]) * 3 + 2
        self._big[key] = s
        return s

    def _panel(self, w, h, alpha=150):
        key = (w, h, alpha)
        s = self._panels.get(key)
        if s is None:
            s = self._panels[key] = pygame.Surface((w, h), pygame.SRCALPHA)
            s.fill((20, 18, 30, alpha))
        return s

    def face(self, mood, color, flash):
        key = (mood, self.look, color, flash)
        s = self._faces.get(key)
        if s is None:
            s = self._faces[key] = FA.make_face(mood, self.look, color, flash)
        return s

    def add_toast(self, text, color, now):
        self.toasts.append((text, TOAST_COLORS.get(color, P["white"]), now))

    # ------------------------------------------------------------------ first-person overlays
    def draw_overlay(self, surf, view, now, speed_bob, steer, weapon=S.ARM_FISTS, fire_t=-9.0):
        """Hands / held parts / dolly / weapon / car interior, over the 3D view."""
        me = view.me
        if me is None:
            return
        state = me[2]
        pen = Pen(surf)
        vw, vh = pen.size
        if state in (S.DRIVER, S.PASSENGER) and view.my_car is not None:
            self._dashboard(pen, view.my_car, state == S.DRIVER, steer, now)
            return
        if state == S.CUFFED:
            for x in range(0, vw, 26):
                pen.fill((70, 70, 80), (x, 0, 6, vh))
                pen.fill((130, 130, 140), (x + 1, 0, 2, vh))
            return
        if state != S.FOOT:
            return
        bob = math.sin(now * 9.0) * 3 * speed_bob
        sway = math.cos(now * 4.5) * 4 * speed_bob
        sleeve = PLAYER_COLORS[me[1] % 4]
        skin = SKINS[me[0] % 4]
        if me[3] & PR.PF_DOLLY:
            d = next((d for d in view.dollies.values() if d[5] == me[0]), None)
            self._dolly_view(pen, d, bob, sway, skin, sleeve)
            return
        hands = [h for h in (me[9], me[10]) if h != NO_PART]
        by = vh - 24 + int(bob)
        if not hands:
            self._weapon_view(pen, view, weapon, now - fire_t, bob, sway, skin, sleeve)
            return
        if len(hands) == 1 and PART_DEFS[PART_IDS[hands[0]]][2] == 2:
            ic = self._icon6(hands[0])
            pen.blit(ic, (vw // 2 - 24 + int(sway), by - 48 + 12))
            self._fist(pen, vw // 2 - 34 + int(sway), by, skin, sleeve, -1)
            self._fist(pen, vw // 2 + 34 + int(sway), by, skin, sleeve, 1)
            return
        for i, side in enumerate((-1, 1)):
            x = vw // 2 + side * 120 + int(sway * side)
            held = hands[i] if i < len(hands) else None
            if held is not None:
                ic = self._icon6(held)
                pen.blit(ic, (x - 24, by - 48 + 6))
            self._fist(pen, x, by, skin, sleeve, side)

    def _weapon_view(self, pen, view, weapon, since, bob, sway, skin, sleeve):
        """Doom's weapon sprites, done with rectangles. `since` = seconds since
        you last pulled the trigger (locally, so it feels instant)."""
        vw, vh = pen.size
        cx = vw // 2 + int(sway)
        ars = view.snap.arsenal if view.snap is not None else None
        ammo = 1
        if ars and weapon in (S.ARM_PISTOL, S.ARM_SHOTGUN):
            ammo = ars[2] if weapon == S.ARM_PISTOL else ars[3]
        if weapon == S.ARM_PISTOL:
            # seen from behind and a bit above: the slide's top recedes toward the horizon
            kick = max(0.0, 1.0 - since / 0.14) if ammo or since < 0.02 else 0.0
            base = vh - 26 + int(bob) + int(kick * 12)
            top = base - 38 + int(kick * 6)
            if kick > 0.55 and ammo:
                self._flash(pen, cx, top - 4, 12)
            pen.poly((26, 26, 32), [(cx - 13, base), (cx + 13, base), (cx + 7, top), (cx - 7, top)])
            pen.poly((58, 58, 70), [(cx - 13, base), (cx - 8, base), (cx - 4, top), (cx - 7, top)])
            pen.poly((44, 44, 54), [(cx - 9, base - 2), (cx + 9, base - 2), (cx + 5, top + 2), (cx - 5, top + 2)])
            pen.fill((70, 70, 84), (cx - 1, top + 3, 2, base - top - 8))                   # the rib down the middle
            pen.fill((20, 20, 26), (cx - 9, base - 7, 5, 5))                               # rear sight, left
            pen.fill((20, 20, 26), (cx + 4, base - 7, 5, 5))                               # rear sight, right
            pen.fill((230, 230, 230), (cx - 1, top - 3, 2, 4))                             # front sight dot
            self._fist(pen, cx, base + 14, skin, sleeve, 1)
            return
        if weapon == S.ARM_SHOTGUN:
            kick = max(0.0, 1.0 - since / 0.25) if ammo or since < 0.02 else 0.0
            pump = math.sin(min(1.0, max(0.0, (since - 0.25) / 0.4)) * math.pi) if ammo else 0.0
            top = vh - 104 + int(bob) + int(kick * 24)
            if kick > 0.7 and ammo:
                self._flash(pen, cx, top - 10, 26)
            pen.poly((30, 30, 38), [(cx - 22, vh), (cx + 22, vh), (cx + 9, top), (cx - 9, top)])
            pen.poly((62, 62, 76), [(cx - 22, vh), (cx - 14, vh), (cx - 5, top), (cx - 9, top)])
            pen.fill((18, 18, 22), (cx - 5, top, 10, 3))                                   # the business end
            py_ = top + 40 + int(pump * 22)
            pen.poly(FA.GUN_WOOD, [(cx - 20, py_ + 26), (cx + 20, py_ + 26), (cx + 15, py_), (cx - 15, py_)])
            for k in range(3):
                pen.fill(shade(FA.GUN_WOOD, 0.7), (cx - 14, py_ + 5 + k * 7, 28, 2))
            self._fist(pen, cx - 44, vh - 6 + int(bob) + int(kick * 12), skin, sleeve, -1)
            self._fist(pen, cx + 26, py_ + 30, skin, sleeve, 1)
            return
        if weapon in (S.ARM_SPIKES, S.ARM_BLOCK):
            top = vh - 58 + int(bob)
            if weapon == S.ARM_SPIKES:
                pen.rect((26, 24, 30), (cx - 60, top, 120, 26))
                pen.fill((230, 190, 40), (cx - 60, top + 22, 120, 4))
                for k in range(12):
                    pen.poly(P["chrome"], [(cx - 56 + k * 10, top), (cx - 50 + k * 10, top),
                                                            (cx - 53 + k * 10, top - 8)])
            else:
                for k in range(8):
                    col = FA.BARRIER_ORANGE if k % 2 == 0 else FA.BARRIER_WHITE
                    pen.fill(col, (cx - 64 + k * 16, top + 6, 16, 22))
                pen.fill((60, 60, 70), (cx - 64, top + 28, 128, 3))
            self._fist(pen, cx - 60, vh - 12 + int(bob), skin, sleeve, -1)
            self._fist(pen, cx + 60, vh - 12 + int(bob), skin, sleeve, 1)
            return
        # fists: the right one jabs at the middle of the screen
        by = vh - 24 + int(bob)
        jab = math.sin(min(1.0, since / 0.22) * math.pi) if since < 0.22 else 0.0
        self._fist(pen, vw // 2 - 120 - int(sway), by, skin, sleeve, -1)
        self._fist(pen, vw // 2 + 120 + int(sway) - int(jab * 100), by - int(jab * 46), skin, sleeve, 1)

    @staticmethod
    def _flash(pen, x, y, r):
        pen.circle((255, 200, 60), (x, y), r)
        pen.circle((255, 250, 210), (x, y), max(2, r // 2))
        for a in range(0, 360, 45):
            t = math.radians(a)
            pen.line((255, 230, 120), (x, y), (x + int(math.cos(t) * r * 1.6),
                                                             y + int(math.sin(t) * r * 1.6)), 2)

    def _icon6(self, idx):
        ic = self.icons6.get(idx)
        if ic is None:
            n = int(48 * W / Pen.BASE_W)
            ic = self.icons6[idx] = pygame.transform.scale(self.bank.icons[idx], (n, n))
        return ic

    @staticmethod
    def _fist(pen, x, y, skin, sleeve, side):
        pen.poly(shade(sleeve, 0.7), [(x - 16, y + 30), (x - 10, y + 6), (x + 12, y + 6), (x + 18, y + 30)])
        pen.poly(sleeve, [(x - 13, y + 30), (x - 8, y + 8), (x + 10, y + 8), (x + 15, y + 30)])
        pen.rect(shade(skin, 0.8), (x - 11, y - 12, 22, 20), border_radius=4)
        pen.rect(skin, (x - 10, y - 12, 20, 18), border_radius=4)
        for k in range(4):
            pen.fill(shade(skin, 0.75), (x - 9 + k * 5, y - 12, 1, 7))
        pen.fill(shade(skin, 1.1), (x - 8, y - 11, 14, 2))
        tx = x + 7 * side
        pen.fill(shade(skin, 0.85), (tx - 3, y - 4, 6, 7))

    def _dolly_view(self, pen, d, bob, sway, skin, sleeve):
        vw, vh = pen.size
        cx = vw // 2 + int(sway)
        top = vh - 70 + int(bob)
        for side in (-1, 1):
            gx = cx + side * 130
            pen.line(P["metal"], (gx, vh), (cx + side * 44, top), 6)
            pen.line(P["metal_l"], (gx, vh), (cx + side * 44, top), 2)
        pen.rect(P["metal"], (cx - 50, top - 4, 100, 8))
        pen.rect(P["chrome"], (cx - 50, top - 4, 100, 2))
        if d is not None and d[4] != 255:
            ic = self._icon6(d[4])
            pen.blit(ic, (cx - 24, top - 48))
        for side in (-1, 1):
            self._fist(pen, cx + side * 128, vh - 14 + int(bob), skin, sleeve, side)

    def _dashboard(self, pen, car, driving, steer, now):
        vw, vh = pen.size
        kind, color = car[1], car[2]
        body = (36, 36, 48) if kind == S.COP else CAR_COLORS[color % len(CAR_COLORS)]
        # hood, sloping away from you
        pen.poly(shade(body, 0.8), [(40, vh), (vw - 40, vh), (vw - 130, vh - 58), (130, vh - 58)])
        pen.poly(body, [(80, vh), (vw - 80, vh), (vw - 150, vh - 56), (150, vh - 56)])
        if kind == S.PERSONAL:
            pen.poly((40, 90, 30), [(vw // 2 - 22, vh), (vw // 2 + 22, vh), (vw // 2 + 8, vh - 56),
                                                     (vw // 2 - 8, vh - 56)])
        # A-pillars and roof edge
        pen.poly((24, 22, 30), [(0, 0), (34, 0), (96, vh - 40), (0, vh - 40)])
        pen.poly((24, 22, 30), [(vw, 0), (vw - 34, 0), (vw - 96, vh - 40), (vw, vh - 40)])
        pen.fill((24, 22, 30), (0, 0, vw, 10))
        pen.fill((40, 38, 46), (vw // 2 - 26, 10, 52, 12))           # mirror
        pen.fill((90, 110, 130), (vw // 2 - 24, 11, 48, 9))
        # dash
        pen.fill((30, 28, 36), (0, vh - 40, vw, 40))
        pen.fill((50, 48, 58), (0, vh - 40, vw, 3))
        spd = math.hypot(car[9], car[10]) * 3.6
        dx, dy = vw - 150, vh - 18
        pen.circle((14, 14, 20), (dx, dy), 17)
        pen.circle((120, 120, 130), (dx, dy), 17, 1)
        a = math.radians(210 - min(240, spd * 1.2))
        pen.line((255, 90, 60), (dx, dy), (dx + int(math.cos(a) * 14), dy - int(math.sin(a) * 14)), 2)
        pen.text(self.font, "%d" % spd, dx, dy + 6, P["white"], align="center")
        if not driving:
            return
        # steering wheel, turning with your inputs
        wx, wy, r = 170, vh + 10, 44
        pen.circle((18, 18, 22), (wx, wy), r, 9)
        pen.circle((60, 58, 66), (wx, wy), r, 2)
        rot = -steer * 1.3
        for k in (0, 2.3, -2.3):
            a = math.pi / 2 + k + rot
            pen.line((30, 30, 36), (wx, wy), (wx + int(math.cos(a) * r), wy - int(math.sin(a) * r)), 7)
        pen.circle((40, 40, 48), (wx, wy), 10)

    # ------------------------------------------------------------------ the bar
    def draw(self, low, view, now, info):
        f = self.font
        snap = view.snap
        me = view.me
        flash = int(now * 4) % 2 == 0
        by = H - BAR_H
        low.blit(self.bar, (0, by))
        # CASH
        if self.last_cash is not None and snap.cash > self.last_cash:
            self.grin_until = now + 1.6
        self.last_cash = snap.cash
        cash = ("-$%d" % -snap.cash) if snap.cash < 0 else "$%d" % snap.cash
        num = self.big(cash, BIG_RED if snap.cash >= 0 else BIG_BLUE)
        if num.get_width() > 92:
            num = pygame.transform.scale(num, (92, num.get_height()))
        low.blit(num, (BX + 48 - num.get_width() // 2, by + 3))
        f.draw(low, "CASH", BX + 48, by + 23, P["white"], align="center")
        # HEAT
        heat_ramp = BIG_BLUE if snap.cops and flash else BIG_RED
        num = self.big("%d%%" % snap.heat, heat_ramp)
        low.blit(num, (BX + 132 - num.get_width() // 2, by + 3))
        f.draw(low, "HEAT", BX + 132, by + 23, P["white"], align="center")
        # HANDS
        hx = BX + 172
        if me is not None:
            hands = [h for h in (me[9], me[10]) if h != NO_PART]
            dolly = next((d for d in view.dollies.values() if d[5] == me[0]), None) \
                if me[3] & PR.PF_DOLLY else None
            for i in range(2):
                low.fill((30, 28, 34), (hx + i * 26, by + 3, 22, 18))
                pygame.draw.rect(low, (60, 58, 66), (hx + i * 26, by + 3, 22, 18), 1)
            if dolly is not None:
                low.blit(pygame.transform.scale(self.bank.dolly, (20, 16)), (hx + 1, by + 4))
                if dolly[4] != NO_PART:
                    low.blit(self.icons2[dolly[4]], (hx + 29, by + 4))
            elif len(hands) == 1 and PART_DEFS[PART_IDS[hands[0]]][2] == 2:
                pygame.draw.rect(low, P["gold"], (hx, by + 3, 48, 18), 1)
                low.blit(self.icons2[hands[0]], (hx + 16, by + 4))
            elif not hands and info.get("weapon", S.ARM_FISTS) != S.ARM_FISTS and snap.arsenal:
                w = info["weapon"]
                n = {S.ARM_PISTOL: snap.arsenal[2], S.ARM_SHOTGUN: snap.arsenal[3],
                     S.ARM_SPIKES: snap.arsenal[4], S.ARM_BLOCK: snap.arsenal[5]}[w]
                low.fill((92, 90, 96), (hx, by + 2, 52, 20))
                num = self.big("%d" % n, BIG_RED if n else BIG_BLUE)
                low.blit(num, (BX + 198 - num.get_width() // 2, by + 3))
            else:
                for i, h in enumerate(hands):
                    low.blit(self.icons2[h], (hx + 3 + i * 26, by + 4))
        label = "HANDS"
        if me is not None and me[3] & PR.PF_DOLLY:
            label = "DOLLY"
        elif me is not None and me[9] == NO_PART and info.get("weapon", S.ARM_FISTS) != S.ARM_FISTS:
            label = WEAPON_LABELS[info["weapon"]]
        f.draw(low, label, BX + 198, by + 23, P["white"], align="center")
        # FACE
        if me is not None:
            if now > self.look_t:
                self.look_t = now + self.rng.uniform(0.8, 2.2)
                self.look = self.rng.choice((-1, 0, 0, 1))
            state = me[2]
            if state == S.CUFFED:
                mood = "busted"
            elif state == S.TUMBLE:
                mood = "dazed"
            elif now < self.grin_until:
                mood = "grin"
            elif me[3] & PR.PF_EXHAUSTED:
                mood = "winded"
            elif snap.heat >= 80 or snap.cops:
                mood = "panic"
            elif snap.heat >= 40:
                mood = "sweaty"
            elif snap.heat > 0:
                mood = "tense"
            else:
                mood = "calm"
            fl = (1 if flash else 2) if snap.cops else 0
            low.blit(self.face(mood, me[1], fl), (BX + 232, by + 1))
        # STAMINA / SPEED
        car = view.my_car
        if car is not None and me is not None and me[2] in (S.DRIVER, S.PASSENGER):
            num = self.big("%d" % (math.hypot(car[9], car[10]) * 3.6))
            low.blit(num, (BX + 296 - num.get_width() // 2, by + 3))
            f.draw(low, "KM/H", BX + 296, by + 23, P["white"], align="center")
        elif me is not None:
            winded = me[3] & PR.PF_EXHAUSTED
            num = self.big("%d%%" % me[11], BIG_BLUE if winded else BIG_RED)
            low.blit(num, (BX + 296 - num.get_width() // 2, by + 3))
            f.draw(low, "WINDED!" if winded else "STAMINA", BX + 296, by + 23,
                   P["danger"] if winded and flash else P["white"], align="center")
        # COPS
        for i in range(min(snap.cops, 2)):
            c = (255, 60, 60) if (flash ^ bool(i)) else (80, 120, 255)
            low.fill(P["ink"], (BX + 338 + i * 16, by + 5, 12, 14))
            low.fill(c, (BX + 339 + i * 16, by + 6, 10, 5))
            low.fill(P["white"], (BX + 339 + i * 16, by + 12, 10, 6))
        f.draw(low, "COPS", BX + 351, by + 23, (130, 170, 255) if snap.cops else P["white"], align="center")
        # DAY / RENT
        dx = BX + 378
        f.draw(low, "DAY %d" % snap.day, dx, by + 3, P["gold"])
        f.draw(low, "RENT $%d" % snap.rent_due, dx, by + 11, P["white"])
        due = snap.rent
        f.draw(low, "DUE %s" % mmss(due), dx, by + 19,
               P["danger"] if (due < 30 and flash) else P["white"])
        if snap.cash < 0:
            f.draw(low, "IN THE RED %s" % mmss(C.DEBT_GRACE - snap.debt), dx + 44, by + 3,
                   P["danger"] if flash else P["gold"])
        self._arms_panel(low, snap, me, info, by)
        self._gear_panel(low, snap, me, view, by)
        # ---- above the bar -------------------------------------------------
        self._toasts(low, now)
        self._status_line(low, snap, now)
        self._minimap(low, view, info, flash)
        if me is not None:
            self._prompt(low, snap)
            if info.get("fp") and me[2] == S.FOOT and not info.get("paused"):
                low.fill(P["white"], (W // 2, VIEW_H // 2 - 1, 1, 3))
                low.fill(P["white"], (W // 2 - 1, VIEW_H // 2, 3, 1))
            if info.get("fp"):
                self._shop_compass(low, view, info, now)
                self._car_compass(low, view, info, now)
        self._banners(low, snap, me, now, flash)
        if now < self.help_until and not info.get("paused"):
            lines = ["MOUSE LOOK  WASD MOVE/DRIVE  SHIFT SPRINT  E USE (HOLD)  G DROP  F EXIT CAR",
                     "CLICK/CTRL PUNCH/SHOOT/PLACE  1-5, WHEEL OR Q: WEAPONS  SPACE HANDBRAKE  H HORN",
                     "TAB MAP  M MUSIC  ESC MENU  F11 FULLSCREEN",
                     "STEAL CARS (FOLLOW THE GREEN ARROWS). PARK THEM IN THE SHOP. STRIP. SELL.",
                     "GUNS AND TRAPS: THE CRATES IN THE SHOP. RENT'S DUE AT MIDNIGHT."]
            low.blit(self._panel(370, 43, 170), (W // 2 - 185, 30))
            for i, l in enumerate(lines):
                f.draw(low, l, W // 2, 33 + i * 8, P["white"] if i < 3 else P["gold"], align="center")

    def _toasts(self, low, now):
        y = 3
        for text, col, t0 in list(self.toasts):
            if now - t0 > C.TOAST_TIME:
                continue
            self.font.draw(low, text, 4, y, col)
            y += 8
        while self.toasts and now - self.toasts[0][2] > C.TOAST_TIME:
            self.toasts.popleft()

    def _status_line(self, low, snap, now):
        if snap.witness in WITNESS_TEXT:
            text, col = WITNESS_TEXT[snap.witness]
        elif snap.cooling:
            text, col = "NOBODY SEES YOU - COOLING OFF", P["money"]
        elif snap.heat > 0:
            text, col = "OUT OF SIGHT... STAY HIDDEN", P["white"]
        else:
            return
        self.font.draw(low, text, W // 2, VIEW_H - 10, col, align="center")

    def _prompt(self, low, snap):
        prompt = snap.prompt
        if not prompt:
            return
        pw = PixelFont.width(prompt) + 10
        y = VIEW_H // 2 + 14
        low.blit(self._panel(pw, 18 if snap.hold > 0 else 11), (W // 2 - pw // 2, y))
        self.font.draw(low, prompt, W // 2, y + 3, P["white"], align="center")
        if snap.hold > 0:
            low.fill(P["ink"], (W // 2 - 50, y + 11, 100, 4))
            low.fill(P["gold"], (W // 2 - 50, y + 11, int(100 * snap.hold), 4))

    def _minimap(self, low, view, info, flash):
        if not info.get("fp"):
            return
        mm = self.minimap
        s = 0.5                                             # half size: it's a radar, not the automap
        mw, mh = int(mm.get_width() * s), int(mm.get_height() * s)
        key = ("mm", mw)
        small = self._panels.get(key)
        if small is None:
            small = self._panels[key] = pygame.transform.scale(mm, (mw, mh))
        mx, my = W - mw - 3, 3
        low.fill(P["ink"], (mx - 1, my - 1, mw + 2, mh + 2))
        low.blit(small, (mx, my))
        k = s / (C.TILE_M * 2)
        for c in view.cars.values():
            if c[1] == S.COP:
                low.fill((255, 60, 60) if flash else (80, 120, 255), (mx + int(c[7] * k) - 1, my + int(c[8] * k) - 1, 2, 2))
            elif c[1] == S.PERSONAL:
                low.fill((150, 222, 64), (mx + int(c[7] * k), my + int(c[8] * k), 2, 2))
            elif c[1] == S.CIV and c[3] != S.DELIVERED:
                low.fill(P["gold"] if c[4] & PR.CF_WANTED else P["white"], (mx + int(c[7] * k), my + int(c[8] * k), 1, 1))
        for p in view.players.values():
            low.fill(PLAYER_COLORS[p[1] % 4], (mx + int(p[4] * k), my + int(p[5] * k), 2, 2))
        me = view.me
        if me is not None:
            yaw = info.get("yaw", 0.0)
            px, py = mx + me[4] * k, my + me[5] * k
            pygame.draw.line(low, P["white"], (px, py), (px + math.cos(yaw) * 5, py + math.sin(yaw) * 5))

    def _shop_compass(self, low, view, info, now):
        me = view.me
        car = view.my_car
        hot = (car is not None and car[4] & PR.CF_WANTED) or (car is None and (me[9] != 255 or me[3] & PR.PF_DOLLY))
        gm = info.get("garage")
        if not hot or gm is None or info.get("in_garage"):
            return
        gx, gy = gm
        yaw = info.get("yaw", 0.0)
        bearing = (math.atan2(gy - me[5], gx - me[4]) - yaw + math.pi) % (2 * math.pi) - math.pi
        half = math.radians(C.FP_FOV) / 2
        x = W / 2 + max(-1.0, min(1.0, bearing / half)) * (W / 2 - 30)
        col = P["gold"] if int(now * 3) % 2 else P["white"]
        dist = math.hypot(gx - me[4], gy - me[5])
        arrow = "<" if bearing < -half else ">" if bearing > half else "V"
        self.font.draw(low, "%s SHOP %dM %s" % (arrow if arrow == "<" else "", dist, arrow if arrow == ">" else ""),
                       int(x), 14, col, align="center")
        if arrow == "V":
            pygame.draw.polygon(low, col, [(x - 4, 22), (x + 4, 22), (x, 27)])

    def _arms_panel(self, low, snap, me, info, by):
        """Left of the bar, Doom's ARMS box: 1-5, lit if you own it, gold in hand."""
        if BX < 40:
            return
        f = self.font
        ars = snap.arsenal
        cur = info.get("weapon", S.ARM_FISTS)
        for k in range(5):
            owned = S.arsenal_owns(ars, k)
            col = P["gold"] if k == cur and owned else P["white"] if owned else (70, 68, 76)
            f.draw(low, str(k + 1), BX // 2 - 28 + k * 14, by + 4, col, scale=1)
        name = S.ARM_NAMES[cur] if S.arsenal_owns(ars, cur) else "FISTS"
        f.draw(low, name, BX // 2, by + 13, P["gold"], align="center")
        f.draw(low, "ARMS", BX // 2, by + 23, P["white"], align="center")

    def _gear_panel(self, low, snap, me, view, by):
        """Right of the bar: what's in your pockets (traps) -- or your trunk, in a car."""
        if BX < 40:
            return
        f = self.font
        x0 = BX + 480
        cx = x0 + (W - x0) // 2
        ars = snap.arsenal or (0, 1, 0, 0, 0, 0)
        rows = []
        if ars[4]:
            rows.append("SPIKES x%d" % ars[4])
        if ars[5]:
            rows.append("BLOCKS x%d" % ars[5])
        for i, r in enumerate(rows[:2]):
            f.draw(low, r, cx, by + 4 + i * 8, P["gold"], align="center")
        if not rows:
            f.draw(low, "-", cx, by + 8, (70, 68, 76), align="center")
        f.draw(low, "GEAR", cx, by + 23, P["white"], align="center")

    def _car_compass(self, low, view, info, now):
        """Can't find anything to steal? Follow the green arrow."""
        me = view.me
        if me[2] != S.FOOT or me[9] != NO_PART or me[3] & PR.PF_DOLLY:
            return
        best, bd = None, None
        for c in view.cars.values():
            if c[1] == S.CIV and c[3] != S.DELIVERED and not c[12] and not c[4] & PR.CF_WANTED:
                d = math.hypot(c[7] - me[4], c[8] - me[5])
                if bd is None or d < bd:
                    best, bd = c, d
        if best is None or bd < 7:
            return
        yaw = info.get("yaw", 0.0)
        bearing = (math.atan2(best[8] - me[5], best[7] - me[4]) - yaw + math.pi) % (2 * math.pi) - math.pi
        half = math.radians(C.FP_FOV) / 2
        x = W / 2 + max(-1.0, min(1.0, bearing / half)) * (W / 2 - 40)
        col = (120, 236, 90)
        if bearing < -half:
            text = "< CAR TO STEAL %dM" % bd
        elif bearing > half:
            text = "CAR TO STEAL %dM >" % bd
        else:
            text = "CAR TO STEAL %dM" % bd
            pygame.draw.polygon(low, col, [(x - 4, 22), (x + 4, 22), (x, 27)])
        self.font.draw(low, text, int(x), 14, col, align="center")

    def _banners(self, low, snap, me, now, flash):
        f = self.font
        if self.day_seen != snap.day:
            if self.day_seen is not None:
                self.day_banner_until = now + 3.5
            self.day_seen = snap.day
        if now < self.day_banner_until and snap.gameover <= 0:
            low.blit(self._panel(W, 40, 170), (0, 60))
            num = self.big("DAY %d" % snap.day, BIG_GOLD)
            num = pygame.transform.scale(num, (num.get_width() * 2, num.get_height() * 2))
            low.blit(num, (W // 2 - num.get_width() // 2, 62))
            f.draw(low, "RENT AT MIDNIGHT: $%d" % snap.rent_due, W // 2, 90, P["white"], align="center")
        if me is not None and me[2] == S.CUFFED:
            f.draw(low, "BUSTED", W // 2, VIEW_H // 2 - 50, P["danger"] if flash else (130, 170, 255),
                   scale=5, align="center")
            f.draw(low, "YOUR PARTS ARE ON THE PAVEMENT. YOUR PARTNER CAN GRAB THEM.", W // 2, VIEW_H // 2 - 18,
                   P["white"], align="center")
        if snap.gameover > 0:
            low.blit(self._panel(W, 60, 190), (0, VIEW_H // 2 - 40))
            f.draw(low, "SHOP SEIZED", W // 2, VIEW_H // 2 - 34, P["danger"], scale=5, align="center")
            f.draw(low, "TWO MINUTES IN THE RED. THE LANDLORD HAS YOUR KEYS.", W // 2, VIEW_H // 2 - 2,
                   P["white"], align="center")
            f.draw(low, "NEW RUN IN %d... (YOUR RIDE KEEPS ITS MODS)" % (int(snap.gameover) + 1), W // 2,
                   VIEW_H // 2 + 8, P["gold"], align="center")

    def draw_pause(self, low, info):
        f = self.font
        low.blit(self._panel(W, H, 222), (0, 0))
        f.draw(low, "PAUSED", W // 2, 14, P["gold"], None, scale=4, align="center")
        f.draw(low, "(THE CITY KEEPS MOVING. SO DOES THE CLOCK.)", W // 2, 40, P["metal_l"], align="center")
        y = 54
        for line, col in info.get("lines", []):
            f.draw(low, line, W // 2, y, col, align="center")
            y += 9
        y += 6
        for l in ("MOUSE / ARROWS LOOK     WASD MOVE (IN A CAR: DRIVE)     SHIFT SPRINT",
                  "E USE (HOLD FOR TIMED ACTIONS)     G DROP / LET GO OF THE DOLLY     F EXIT CAR",
                  "SPACE HANDBRAKE     H HORN (CONFUSES COPS)     TAB MAP     M MUSIC ON/OFF",
                  "CLICK / CTRL: PUNCH, SHOOT OR DROP A TRAP     1-5 / WHEEL / Q: PICK A WEAPON",
                  "PUNCH SOMEONE OR POINT A GUN AT THEM, THEN HOLD E TO ROB THEM",
                  "TRAFFIC WON'T STOP FOR YOU: SPIKES OR A ROADBLOCK, THEN HOLD E TO CARJACK",
                  "SHOOT THE TYRES OUT. SHOOTING COPS IS... AN OPTION",
                  "ENGINES ARE TOO HEAVY TO CARRY: USE THE DOLLY IN THE SHOP",
                  "TUNE-UP BENCH WITH EMPTY HANDS = PARTS COUNTER (NO CREDIT)",
                  "RENT IS DUE AT MIDNIGHT AND GOES UP EVERY DAY",
                  "",
                  "ESC: RESUME        Q: LEAVE TO MAIN MENU"):
            f.draw(low, l, W // 2, y, P["white"], align="center")
            y += 9

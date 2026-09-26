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
from .parts import PART_IDS, PART_DEFS, PART_INDEX, NO_PART, Part
from . import vehicles as V
from .quests import QUESTS, QUEST_ORDER, ACT_NAMES

W, H = C.LOW_W, C.LOW_H
BAR_H = 32
VIEW_H = H - BAR_H
BX = (W - 480) // 2      # the classic 480-wide bar sits in the middle; ARMS and GEAR panels flank it
TOAST_COLORS = {S.T_WHITE: P["white"], S.T_MONEY: P["money"], S.T_BAD: P["danger"],
                S.T_INFO: P["gold"], S.T_COP: (130, 170, 255)}
WITNESS_TEXT = {
    S.W_COP: ("A COP SEES YOU +3/S", (130, 170, 255)),
    # (v0.10) peds/owners don't add heat live any more -- they're calling it in. No
    # rate to show, just the warning: silence them before the call lands.
    S.W_PED: ("A WITNESS SAW YOU - SHUT THEM UP OR RUN", P["gold"]),
    S.W_OWNER: ("THE OWNER SAW YOU - SHUT THEM UP OR RUN", P["danger"]),
    S.W_CAMERA: ("STREET CAMERA SEES THE CAR +1.2/S", P["gold"]),
    S.W_HELI: ("THE CHOPPER'S GOT YOU +2.5/S", (130, 170, 255)),          # (v0.10)
}
# the big red digits: top rows bright, bottom rows dark, like they were chiselled
BIG_RED = ((255, 80, 60), (236, 50, 40), (200, 30, 30), (160, 20, 20), (120, 14, 14))
BIG_GOLD = ((255, 236, 120), (240, 200, 70), (220, 170, 50), (190, 140, 40), (150, 100, 30))
BIG_BLUE = ((170, 200, 255), (130, 170, 255), (90, 130, 240), (60, 100, 210), (40, 70, 170))


WEAPON_LABELS = ("HANDS", "PISTOL", "SHOTGUN", "SPIKES", "BLOCKS", "BANANAS", "DONUTS", "CHICKEN", "WHOOPEE",
                  "SMG", "RIFLE", "SNIPER", "LAUNCHER", "RPG")


INSPECT_CONDITION = ("SCRAP", "ROUGH", "USED", "TIDY", "MINT")

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
        self.speech = deque(maxlen=8)  # (v0.12.1) T_SAY lines: Paige, the Fixer, Tommy talking to you
        self.help_until = time.perf_counter() + 20.0
        self.bar = self._make_bar()
        self._big = {}
        self._faces = {}
        self._panels = {}
        self.look, self.look_t = 0, 0.0
        self.grin_until = 0.0
        self.insp_id, self.insp_since = 0, 0.0     # (v0.9) the car you're sizing up, and since when
        self.last_cash = None
        self.day_seen = None
        self.day_banner_until = 0.0
        self.rng = random.Random(3)
        self.icons2 = [pygame.transform.scale(i, (16, 16)) for i in bank.icons]
        self.icons_small6 = [pygame.transform.scale(i, (12, 12)) for i in bank.icons]
        self.icons6 = {}
        # drift meter: [seconds sideways, score, seconds since it last counted, banner text, banner until]
        self.drift = [0.0, 0.0, 9.0, "", 0.0]

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
        if color == S.T_SAY:
            name, sep, _ = text.partition(": ")
            if sep and not text.startswith(" "):
                if name != getattr(self, "speaker", None):
                    self.speech.clear()      # somebody new talking: they get the box to themselves
                self.speaker = name
            self.speech.append((text, now))
            return
        self.toasts.append((text, TOAST_COLORS.get(color, P["white"]), now))

    # ------------------------------------------------------------------ first-person overlays
    def draw_overlay(self, surf, view, now, speed_bob, steer, weapon=S.ARM_FISTS, fire_t=-9.0, chase=False,
                     tacho=None):
        """Hands / held parts / dolly / weapon / car interior, over the 3D view."""
        me = view.me
        if me is None:
            return
        state = me[2]
        pen = Pen(surf)
        vw, vh = pen.size
        if state in (S.DRIVER, S.PASSENGER) and view.my_car is not None:
            if not chase:
                self._dashboard(pen, view.my_car, state == S.DRIVER, steer, now, tacho)
            elif tacho is not None:
                # chase cam: no dashboard to put it on, so the gauges float bottom-right
                spd = math.hypot(view.my_car[9], view.my_car[10]) * 3.6
                self._tacho(pen, vw - 36, vh - 36, 26, tacho, now)
                pen.text(self.font, "%d" % spd, vw - 70, vh - 22, P["white"], scale=2, align="right")
                pen.text(self.font, "KM/H", vw - 70, vh - 8, P["metal_l"], align="right")
            return
        if state == S.CUFFED:
            for x in range(0, vw, 26):
                pen.fill((70, 70, 80), (x, 0, 6, vh))
                pen.fill((130, 130, 140), (x + 1, 0, 2, vh))
            return
        if state != S.FOOT:
            return
        orange = len(me) > 17 and me[17] & (PR.PF2_JUMPSUIT | PR.PF2_JAILED)
        sleeve0 = (240, 120, 30) if orange else PLAYER_COLORS[me[1] % 4]
        skin0 = SKINS[me[0] % 4]
        if me[3] & PR.PF_CARRY:
            # a pair of legs over your left shoulder, kicking; your hands on their knees
            kick = math.sin(now * 11) * 6
            for k, dx in enumerate((0, 22)):
                pen.poly((52, 56, 78), [(40 + dx, 0), (62 + dx, 0), (70 + dx + kick * (1 if k else -1), 120),
                                         (48 + dx + kick * (1 if k else -1), 120)])
                pen.fill((30, 26, 30), (46 + dx + int(kick * (1 if k else -1)), 116, 28, 12))
            self._fist(pen, 70, vh - 60, skin0, sleeve0, -1)
            self._fist(pen, vw // 2 + 120, vh - 24, skin0, sleeve0, 1)
            return
        if me[3] & PR.PF_DANCE:
            # both hands up, waving. You look ridiculous. That's the point.
            wave = math.sin(now * 10) * 30
            self._fist(pen, vw // 2 - 110 + int(wave), vh - 120 - int(abs(wave)), skin0, sleeve0, -1)
            self._fist(pen, vw // 2 + 110 + int(wave), vh - 120 - int(abs(-wave)), skin0, sleeve0, 1)
            return
        bob = math.sin(now * 9.0) * 3 * speed_bob
        sway = math.cos(now * 4.5) * 4 * speed_bob
        sleeve = sleeve0
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
        if ars and weapon in S.GUN_SLOTS:
            idx = S.AMMO_BYTE_OF_ARM[weapon]
            ammo = ars[idx] if len(ars) > idx else 0
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
        # (v0.12) four more guns. Same recipe as the pistol/shotgun above -- a few polys and a
        # muzzle flash -- just enough silhouette to tell them apart at a glance.
        if weapon == S.ARM_SMG:
            kick = max(0.0, 1.0 - since / 0.09) if ammo or since < 0.02 else 0.0     # fastest kick: it's automatic
            top = vh - 66 + int(bob) + int(kick * 9)
            if kick > 0.45 and ammo:
                self._flash(pen, cx + 34, top + 4, 9)
            pen.rect((34, 34, 42), (cx - 12, top, 66, 15))                          # receiver
            pen.rect((22, 22, 28), (cx + 40, top + 2, 22, 10))                      # short barrel shroud
            pen.fill((16, 16, 20), (cx + 2, top + 15, 9, 24))                       # stick mag hanging down
            pen.poly((52, 42, 32), [(cx - 34, top + 30), (cx - 12, top + 4), (cx - 12, top + 13), (cx - 30, top + 34)])
            self._fist(pen, cx - 28, top + 26, skin, sleeve, -1)
            self._fist(pen, cx + 32, top + 8, skin, sleeve, 1)
            return
        if weapon == S.ARM_AR:
            kick = max(0.0, 1.0 - since / 0.12) if ammo or since < 0.02 else 0.0
            top = vh - 86 + int(bob) + int(kick * 11)
            if kick > 0.5 and ammo:
                self._flash(pen, cx + 46, top + 6, 12)
            pen.rect((36, 38, 34), (cx - 16, top, 78, 18))                          # upper receiver
            pen.rect((24, 26, 22), (cx + 50, top + 3, 22, 12))                      # front sight post + barrel
            pen.fill((44, 46, 40), (cx - 4, top + 18, 10, 6))                       # front pistol grip
            pen.fill((16, 16, 16), (cx - 6, top + 20, 8, 22))                       # curved magazine
            pen.poly((60, 62, 56), [(cx - 40, top + 36), (cx - 16, top + 6), (cx - 16, top + 16), (cx - 36, top + 40)])
            self._fist(pen, cx - 32, top + 30, skin, sleeve, -1)
            self._fist(pen, cx + 40, top + 10, skin, sleeve, 1)
            return
        if weapon == S.ARM_SNIPER:
            kick = max(0.0, 1.0 - since / 0.5) if ammo or since < 0.02 else 0.0      # bolt-action: a long, slow kick
            top = vh - 90 + int(bob) + int(kick * 16)
            if kick > 0.75 and ammo:
                self._flash(pen, cx + 70, top + 6, 13)
            pen.rect((30, 30, 34), (cx - 20, top, 100, 14))                         # barrel + stock, one long line
            pen.rect((18, 18, 20), (cx + 70, top + 2, 20, 10))                      # muzzle brake
            pen.fill((20, 20, 24), (cx - 10, top - 16, 40, 12))                     # scope body
            pen.circle((60, 90, 70), (int(cx + 22), top - 10), 5)                   # objective lens, catching the light
            self._fist(pen, cx - 34, top + 24, skin, sleeve, -1)
            self._fist(pen, cx + 20, top + 8, skin, sleeve, 1)
            return
        if weapon == S.ARM_GRENADE:
            kick = max(0.0, 1.0 - since / 0.3) if ammo or since < 0.02 else 0.0
            top = vh - 78 + int(bob) + int(kick * 14)
            if kick > 0.6 and ammo:
                self._flash(pen, cx + 40, top + 8, 18)
            pen.rect((50, 46, 30), (cx - 18, top, 58, 26))                          # a chunky single-shot barrel
            pen.fill((30, 28, 18), (cx - 18, top + 20, 58, 6))                      # under-rail
            pen.circle((26, 24, 16), (int(cx + 40), top + 13), 13)                  # the business end, nice and round
            pen.fill((70, 64, 40), (cx - 26, top + 6, 10, 16))                      # break-action hinge
            self._fist(pen, cx - 22, top + 26, skin, sleeve, -1)
            self._fist(pen, cx + 30, top + 12, skin, sleeve, 1)
            return
        if weapon == S.ARM_RPG:
            kick = max(0.0, 1.0 - since / 0.6) if ammo or since < 0.02 else 0.0      # the biggest, slowest kick in the game
            top = vh - 96 + int(bob) + int(kick * 20)
            if kick > 0.7 and ammo:
                self._flash(pen, cx + 76, top + 10, 24)                             # backblast up front, not behind you
            pen.rect((58, 54, 34), (cx - 40, top, 120, 22))                         # the tube, slung under the arm
            pen.fill((36, 34, 22), (cx + 60, top - 4, 20, 30))                      # the warhead's flare at the front
            pen.poly((80, 76, 50), [(cx - 40, top + 22), (cx - 10, top - 6), (cx - 10, top + 6), (cx - 34, top + 28)])
            pen.fill((20, 20, 20), (cx - 4, top + 4, 30, 4))                        # the sight, roughly where you'd want it
            self._fist(pen, cx - 30, top + 24, skin, sleeve, -1)
            self._fist(pen, cx + 50, top + 6, skin, sleeve, 1)
            return
        if weapon == S.ARM_BANANA:
            top = vh - 70 + int(bob)
            pen.poly((250, 220, 70), [(cx - 6, top + 40), (cx + 6, top + 40), (cx + 22, top), (cx + 10, top + 4)])
            pen.poly((230, 190, 50), [(cx - 6, top + 40), (cx - 22, top + 6), (cx - 12, top + 8)])
            pen.poly((230, 190, 50), [(cx + 6, top + 40), (cx + 2, top + 2), (cx + 10, top + 6)])
            pen.fill((110, 80, 40), (cx - 3, top + 38, 6, 8))
            self._fist(pen, cx, vh - 12 + int(bob), skin, sleeve, 1)
            return
        if weapon == S.ARM_DONUT:
            top = vh - 64 + int(bob)
            pen.rect((236, 130, 190), (cx - 44, top, 88, 34))
            pen.rect((250, 250, 245), (cx - 44, top, 88, 8))
            for k in range(5):
                pen.circle((190, 120, 70), (cx - 32 + k * 16, top + 20), 6)
                pen.circle((236, 90, 150), (cx - 32 + k * 16, top + 19), 4)
            pen.text(self.font, "DONUTS", cx, top + 1, (180, 40, 120), align="center")
            self._fist(pen, cx - 60, vh - 12 + int(bob), skin, sleeve, -1)
            self._fist(pen, cx + 60, vh - 12 + int(bob), skin, sleeve, 1)
            return
        if weapon == S.ARM_CHICKEN:
            # (v0.9) held by the neck. Click and it goes WHAP across the screen, squeaking
            swing = max(0.0, 1.0 - since / 0.3)
            ang = -0.6 + 2.2 * math.sin(swing * math.pi) if swing > 0 else -0.35
            hx, hy = cx + 40, vh - 20 + int(bob)
            L = 70
            tx, ty = hx - math.sin(ang) * L, hy - math.cos(ang) * L
            px, py = math.cos(ang) * 9, -math.sin(ang) * 9
            yel = (250, 214, 60)
            pen.poly(yel, [(hx - px * 0.4, hy - py * 0.4), (hx + px * 0.4, hy + py * 0.4),
                           (tx + px, ty + py), (tx - px, ty - py)])
            pen.circle(yel, (int(tx), int(ty)), 14)
            pen.circle((236, 190, 40), (int(tx - px * 0.6), int(ty - py * 0.6)), 6)        # a sad wing
            pen.fill((230, 60, 40), (int(hx - 4), int(hy - 12), 8, 6))                    # the comb (upside down)
            pen.fill((240, 150, 40), (int(hx - 3), int(hy - 4), 6, 5))
            self._fist(pen, hx, vh - 8 + int(bob), skin, sleeve, 1)
            return
        if weapon == S.ARM_WHOOPEE:
            top = vh - 60 + int(bob)
            pen.circle((240, 110, 170), (cx, top + 20), 26)
            pen.circle((255, 150, 200), (cx - 8, top + 12), 8)
            pen.fill((200, 80, 140), (cx + 22, top + 16, 16, 8))                          # the nozzle
            pen.text(self.font, "PFFT", cx, top + 17, (150, 40, 100), align="center")
            self._fist(pen, cx - 30, vh - 10 + int(bob), skin, sleeve, -1)
            self._fist(pen, cx + 30, vh - 10 + int(bob), skin, sleeve, 1)
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
        me = view.me
        if me is not None and me[3] & PR.PF_CHARGE:
            # winding up the haymaker: right fist pulled way back, trembling with intent
            shake = math.sin(time.perf_counter() * 60) * 2
            pen.fill((255, 220, 120), (vw // 2 - 30, vh - 12, 60, 3))
            self._fist(pen, vw // 2 - 120 - int(sway), by, skin, sleeve, -1)
            self._fist(pen, vw // 2 + 170 + int(shake), by + 30, skin, sleeve, 1)
            return
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

    def drift_meter(self, surf, view, now, dt):
        """Points for style. Pure bragging rights: no cash, no heat, just a
        number your mates will dispute."""
        me, car = view.me, view.my_car
        d = self.drift
        sideways = False
        if me is not None and car is not None and me[2] == S.DRIVER:
            spd = math.hypot(car[9], car[10])
            if spd > C.DRIFT_MIN_SPEED:
                slip = (math.atan2(car[10], car[9]) - car[11] + math.pi) % (2 * math.pi) - math.pi
                ang = abs(math.degrees(slip))
                if C.DRIFT_MIN_ANGLE < ang < 120:
                    sideways = True
                    d[0] += dt
                    d[1] += dt * spd * ang * 0.35 * (1.0 + min(3.0, d[0]) * 0.5)
                    d[2] = 0.0
        if not sideways:
            d[2] += dt
            if d[0] > 0 and d[2] > 0.5:
                if d[0] > 0.8:
                    words = ("NICE DRIFT", "TOKYO WOULD BE PROUD", "SIDEWAYS SENSEI", "THE TYRES FILED A COMPLAINT")
                    word = words[min(len(words) - 1, int(d[1] // 1500))]
                    d[3], d[4] = "%s! +%d" % (word, int(d[1])), now + 2.0
                d[0] = d[1] = 0.0
        vw, vh = surf.get_size()
        if d[0] > 0.3:
            num = self.big("%d" % int(d[1]), BIG_GOLD)
            surf.blit(num, (vw // 2 - num.get_width() // 2, 30))
            self.font.draw(surf, "DRIFT x%.1f  %.1fS" % (1.0 + min(3.0, d[0]) * 0.5, d[0]), vw // 2, 50,
                           P["gold"], align="center")
        elif now < d[4]:
            self.font.draw(surf, d[3], vw // 2, 36, P["gold"], scale=2, align="center")

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

    def _tacho(self, pen, cx, cy, r, tacho, now):
        """The rev counter (v0.8): redline in red, a needle that bounces off the
        limiter, the gear in the middle, and a boost gauge if there's a turbo or
        a blower to brag about."""
        rpm, red, gear, gears, boost, asp, vtec = tacho
        top = max(1000, int(math.ceil(red * 1.08 / 1000.0)) * 1000)
        pen.circle((14, 14, 20), (cx, cy), r)
        pen.circle((120, 120, 130), (cx, cy), r, 1)
        a0, sweep = 225.0, 270.0

        def ang(v):
            return math.radians(a0 - sweep * min(1.0, v / float(top)))
        # redline arc, as a row of ticks
        steps = 18
        for k in range(steps + 1):
            v = red + (top - red) * k / steps
            a = ang(v)
            pen.line((210, 40, 40), (cx + int(math.cos(a) * (r - 4)), cy - int(math.sin(a) * (r - 4))),
                     (cx + int(math.cos(a) * (r - 1)), cy - int(math.sin(a) * (r - 1))), 1)
        for k in range(0, top // 1000 + 1):
            a = ang(k * 1000)
            pen.line((200, 200, 210), (cx + int(math.cos(a) * (r - 6)), cy - int(math.sin(a) * (r - 6))),
                     (cx + int(math.cos(a) * (r - 1)), cy - int(math.sin(a) * (r - 1))), 1)
        a = ang(rpm)
        pen.line((255, 90, 60), (cx, cy), (cx + int(math.cos(a) * (r - 3)), cy - int(math.sin(a) * (r - 3))), 2)
        pen.circle((60, 60, 70), (cx, cy), 3)
        shift = rpm > red * 0.93 and gear < gears
        gtxt = "N" if gears == 0 and rpm < 10 else (str(gear) if gears else "E")
        pen.text(self.font, gtxt, cx, cy + r // 3, (255, 80, 60) if shift and int(now * 12) % 2 else P["gold"],
                 align="center")
        pen.text(self.font, "x1000", cx, cy - r // 2 - 2, (140, 140, 150), align="center")
        if vtec:
            pen.text(self.font, "VTEC", cx, cy + r + 2, (255, 60, 60), align="center")
        if asp:
            # the boost gauge: a little bar under the dial
            bw = r * 2 - 8
            pen.fill((30, 30, 40), (cx - bw // 2, cy + r + (10 if vtec else 3), bw, 4))
            pen.fill((80, 200, 255) if asp == 1 else (255, 200, 60),
                     (cx - bw // 2, cy + r + (10 if vtec else 3), int(bw * boost), 4))

    def _dashboard(self, pen, car, driving, steer, now, tacho=None):
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
        if tacho is not None:
            self._tacho(pen, dx - 44, dy - 2, 19, tacho, now)
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
            elif not hands and info.get("weapon", S.ARM_FISTS) not in (S.ARM_FISTS, S.ARM_CHICKEN) and snap.arsenal:
                w = info["weapon"]
                n = snap.arsenal[S.AMMO_BYTE_OF_ARM[w]] if w in S.AMMO_BYTE_OF_ARM \
                    else snap.arsenal[4 + S.GEAR_OF_ARM[w]]
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
            if state in (S.CUFFED, S.DEAD):
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
        lethal = getattr(snap, "alert", 0) & PR.AL_LETHAL
        f.draw(low, "LETHAL" if lethal else "COPS", BX + 351, by + 23,
               (P["danger"] if flash else P["white"]) if lethal else (130, 170, 255) if snap.cops else P["white"],
               align="center")
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
        self._speech(low, now)
        self._status_line(low, snap, now)
        self._box_status(low, me, now)
        self._minimap(low, view, info, flash)
        if me is not None:
            self._prompt(low, snap)
            if info.get("fp") and me[2] == S.FOOT and not info.get("paused"):
                low.fill(P["white"], (W // 2, VIEW_H // 2 - 1, 1, 3))
                low.fill(P["white"], (W // 2 - 1, VIEW_H // 2, 3, 1))
            if info.get("fp"):
                self._shop_compass(low, view, info, now)
                self._car_compass(low, view, info, now)
                self._crew_compass(low, view, info, now)
        self._law_overlay(low, snap, me, now, flash)
        if not info.get("paused") and not info.get("menu"):
            self._inspect_card(low, snap, now)
        self._banners(low, snap, me, now, flash)
        self._comedy_banner(low, me, now)
        if now < self.help_until and not info.get("paused") and not info.get("menu"):
            lines = ["MOUSE LOOK  WASD MOVE/DRIVE  SPACE JUMP/HANDBRAKE  SHIFT SPRINT/NOS  E USE (HOLD)",
                     "CLICK/CTRL PUNCH/SHOOT/THROW (HOLD: HAYMAKER)  1-7 WEAPONS  G GRAB/DROP  F EXIT CAR",
                     "V CHASE CAM  W+S BURNOUT  X HOP  TAB MAP  H HORN  T DANCE  M MUSIC  ESC MENU",
                     "STEAL CARS (FOLLOW THE GREEN ARROWS). PARK THEM IN THE SHOP. STRIP. SELL.",
                     "TUNE-UP BENCH = MOD SHOP.  GUNS, TRAPS, BANANAS: THE CRATES.  RENT'S DUE AT MIDNIGHT."]
            low.blit(self._panel(440, 43, 170), (W // 2 - 220, 30))
            for i, l in enumerate(lines):
                f.draw(low, l, W // 2, 33 + i * 8, P["white"] if i < 3 else P["gold"], align="center")

    def _inspect_card(self, low, snap, now):
        """(v0.9) Look at a car and size it up: the engine, the box, the good bits, how
        rough it is, what it'd fetch. Half a second of looking first -- you're a pro,
        but you're not psychic."""
        ins = getattr(snap, "inspect", None)
        if ins is None:
            self.insp_id = 0
            return
        cid, value, model, eng, trn, ecu, cond, flags, best = ins
        if cid != self.insp_id:
            self.insp_id, self.insp_since = cid, now
        age = now - self.insp_since
        f = self.font
        # (v0.12.1) under the (now twice as big) radar and today's jobs, not on top of them
        x, y, w = W - 186, getattr(self, "quest_bottom", 72) + 4, 180
        if age < C.INSPECT_DELAY:
            low.blit(self._panel(w, 11, 150), (x, y))
            dots = "." * (1 + int(age * 8) % 3)
            f.draw(low, "SIZING IT UP" + dots, x + 4, y + 2, P["gold"])
            return
        lines = [("%s" % V.model(model).name, P["gold"])]
        name = lambda tid: PART_DEFS[tid][0].upper() if tid else "NONE (!)"      # noqa: E731
        lines.append(("ENGINE:  " + name(eng), P["white"] if eng is None or not PART_DEFS[eng][5] else P["money"]))
        lines.append(("GEARBOX: " + name(trn), P["white"] if trn is None or not PART_DEFS[trn][5] else P["money"]))
        if ecu is not None and PART_DEFS[ecu][5]:
            lines.append(("ECU:     " + name(ecu), P["money"]))
        for k, (tid, style) in enumerate(best):
            lines.append((("NICE:    " if k == 0 else "         ") + Part(tid, 1.0, style).name.upper(),
                          P["money"] if style or PART_DEFS[tid][5] else P["white"]))
        stars = max(1, min(5, int(round(cond * 5))))
        lines.append(("NICK:    " + "#" * stars + "-" * (5 - stars) + "  " + INSPECT_CONDITION[stars - 1],
                      P["white"]))
        lines.append(("WORTH ABOUT $%s IN PARTS" % "{:,}".format(value), P["money"]))
        if flags & S.INSP_RATTLE:
            lines.append(("SOMETHING RATTLES IN THE BOOT", P["gold"]))
        if flags & S.INSP_HONK:
            lines.append(("...IS THE BOOT HONKING?", (255, 150, 200)))
        if flags & S.INSP_OWNER:
            lines.append(("SOMEONE'S WATCHING IT FROM A WINDOW", P["danger"]))
        shown = min(len(lines), 1 + int((age - C.INSPECT_DELAY) * 40))          # (types itself out)
        h = 4 + 8 * len(lines)
        low.blit(self._panel(w, h, 160), (x, y))
        low.fill(P["gold"], (x, y, w, 1))
        for i, (text, col) in enumerate(lines[:shown]):
            f.draw(low, text[:44], x + 4, y + 3 + i * 8, col)

    def _law_overlay(self, low, snap, me, now, flash):
        """v0.8: WASTED, the lockup objective, the keys, and the lethal-force warning."""
        f = self.font
        if me is None:
            return
        f2 = me[17] if len(me) > 17 else 0
        if me[2] == S.DEAD:
            # GTA's grey-out, with our own sad word on it
            grey = pygame.Surface((W, VIEW_H), pygame.SRCALPHA)
            grey.fill((40, 40, 44, 150))
            low.blit(grey, (0, 0))
            f.draw(low, "WASTED", W // 2 + 3, VIEW_H // 2 - 27, P["ink"], scale=7, align="center")
            f.draw(low, "WASTED", W // 2, VIEW_H // 2 - 30, (200, 40, 40), scale=7, align="center")
            f.draw(low, "THE CREW PAYS THE HOSPITAL. YOU WAKE UP AT THE SHOP.", W // 2, VIEW_H // 2 + 12,
                   P["white"], align="center")
            return
        oy = 62                                 # (under the toasts, over the action)
        if f2 & PR.PF2_JAILED:
            low.blit(self._panel(400, 12, 170), (W // 2 - 200, oy - 2))
            msg = "IN THE LOCKUP: OPEN THE GATE!" if f2 & PR.PF2_KEYS else \
                "LOCKED UP: GET OUT OF THE CELL (PICK IT OR PUNCH IT), THEN THE BIG GUARD'S KEYS. X: BAIL"
            f.draw(low, msg, W // 2, oy, P["gold"], align="center")
        elif f2 & PR.PF2_JUMPSUIT:
            f.draw(low, "ESCAPED CONVICT: GET BACK TO THE SHOP AND CHANGE", W // 2, oy,
                   (255, 140, 40) if flash else P["white"], align="center")
        if f2 & PR.PF2_KEYS:
            low.fill(P["ink"], (W // 2 - 10, oy + 12, 20, 12))
            f.draw(low, "KEYS", W // 2, oy + 15, P["gold"], align="center")
        if f2 & PR.PF2_CUFFING and me[2] in (S.FOOT, S.TUMBLE):
            f.draw(low, "CUFFS GOING ON! MASH SPACE!", W // 2, VIEW_H // 2 + 24,
                   P["danger"] if flash else P["white"], scale=2, align="center")
        if getattr(snap, "alert", 0) & PR.AL_LETHAL and int(now * 2) % 2:
            f.draw(low, "SHOTS FIRED: THE POLICE ARE SHOOTING TO KILL", W // 2, VIEW_H - 12, P["danger"],
                   align="center")

    def _toasts(self, low, now):
        y = 3
        for text, col, t0 in list(self.toasts):
            if now - t0 > C.TOAST_TIME:
                continue
            self.font.draw(low, text, 4, y, col)
            y += 8
        while self.toasts and now - self.toasts[0][2] > C.TOAST_TIME:
            self.toasts.popleft()

    def _speech(self, low, now):
        """(v0.12.1) someone talking to you: a box low in the middle of the view, lasting
        long enough to actually read a job brief (the ticker's TOAST_TIME isn't)."""
        while self.speech and now - self.speech[0][1] > C.SAY_TIME:
            self.speech.popleft()
        if not self.speech:
            return
        lines = [t for t, _ in self.speech]
        w = min(W - 20, max(self.font.width(t) for t in lines) + 10)
        h = 8 * len(lines) + 5
        x, y = W // 2 - w // 2, VIEW_H - 22 - h
        low.blit(self._panel(w, h, 190), (x, y))
        low.fill(P["gold"], (x, y, w, 1))
        for i, t in enumerate(lines):
            name, sep, rest = t.partition(": ")
            if sep and not t.startswith(" "):
                self.font.draw(low, name + ":", x + 5, y + 3 + i * 8, P["gold"])
                self.font.draw(low, rest, x + 5 + self.font.width(name + ": "), y + 3 + i * 8, P["white"])
            else:
                self.font.draw(low, t, x + 5, y + 3 + i * 8, P["white"])

    def _box_status(self, low, me, now):
        """(v0.10, Bryce: "add overlay for in box vs out") the box only actually
        hides you once you've stood still for BOX_STILL_TIME -- without this you'd
        have no way to tell "invisible" from "wearing a very obvious cardboard box"
        until a cop walked straight up to you."""
        if me is None or not (len(me) > 17 and me[17] & PR.PF2_BOX):
            return
        hidden = me[17] & PR.PF2_HIDDEN
        text = "BOXED UP - HIDDEN" if hidden else "BOXED UP - HOLD STILL TO HIDE"
        col = P["money"] if hidden else P["gold"]
        self.font.draw(low, text, W // 2, VIEW_H - 20, col, align="center")

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
        # (Bryce, twice: "make the minimap bigger", then "double the minimap size") 0.5 -> 0.75
        # -> 1.5: about 100 px square now, the whole city at a glance without opening Tab
        s = 1.5
        mw, mh = int(mm.get_width() * s), int(mm.get_height() * s)
        key = ("mm", mw)
        small = self._panels.get(key)
        if small is None:
            small = self._panels[key] = pygame.transform.scale(mm, (mw, mh))
        mx, my = W - mw - 3, 3
        self.mm_left = mx - 1          # top-right text (compasses, crewmates) stops short of this
        low.fill(P["ink"], (mx - 1, my - 1, mw + 2, mh + 2))
        low.blit(small, (mx, my))
        k = s / (C.TILE_M * 2)
        for c in view.cars.values():
            if c[1] == S.COP:
                low.fill((255, 60, 60) if flash else (80, 120, 255), (mx + int(c[7] * k) - 1, my + int(c[8] * k) - 1, 3, 3))
            elif c[1] == S.PERSONAL:
                low.fill((150, 222, 64), (mx + int(c[7] * k) - 1, my + int(c[8] * k) - 1, 3, 3))
            elif c[1] == S.CIV and c[3] != S.DELIVERED:
                low.fill(P["gold"] if c[4] & PR.CF_WANTED else P["white"], (mx + int(c[7] * k), my + int(c[8] * k), 2, 2))
        for p in view.players.values():
            # (v0.10, Bryce: "can't spot teammates on the radar/map") a plain 2x2 dot got
            # lost among all the car blips; an outline and an extra pixel make it read as
            # a person, not scenery, and drawing it last keeps it from being buried.
            bx, by = mx + int(p[4] * k), my + int(p[5] * k)
            low.fill(P["ink"], (bx - 1, by - 1, 4, 4))
            low.fill(PLAYER_COLORS[p[1] % 4], (bx, by, 2, 2))
        me = view.me
        if me is not None:
            yaw = info.get("yaw", 0.0)
            px, py = mx + me[4] * k, my + me[5] * k
            pygame.draw.line(low, P["white"], (px, py), (px + math.cos(yaw) * 7, py + math.sin(yaw) * 7))
        self._quest_panel(low, view.snap, W - 3, my + mh + 3)

    def _quest_panel(self, low, snap, x, y):
        """Under the radar: today's 3 jobs and the crew's reputation/act. Nothing but
        ids and a done bitmask rides the wire (protocol.SNAP_HDR) -- names, briefs and
        rewards come from quests.QUESTS, the same fixed table on both ends. Right-aligned
        to the screen edge (v0.12.1: it used to start at the radar's left edge and run off
        the right side of the screen -- Bryce: "the daily quests are off the screen")."""
        f = self.font
        rows = []
        act = ("I", "II", "III")[max(0, min(2, snap.act - 1))]
        rows.append(("REP %d - ACT %s" % (snap.story_points, act), P["gold"]))
        for i, idx in enumerate(snap.today_quests):
            if idx == PR.NO_QUEST or idx >= len(QUEST_ORDER):
                continue
            name, brief, diff, cash, rep, minp, tlim, coop = QUESTS[QUEST_ORDER[idx]]
            done = bool(snap.quest_done & (1 << i))
            rows.append((("%s $%d" % (name, cash)) if not done else "%s DONE" % name,
                         P["money"] if done else P["white"]))
        width = max(f.width(t) for t, _ in rows) + 6
        low.blit(self._panel(width, 8 * len(rows) + 3, 150), (x - width + 2, y - 2))
        for t, col in rows:
            f.draw(low, t, x, y, col, align="right")
            y += 8
        self.quest_bottom = y

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
        text = "%s SHOP %dM %s" % (arrow if arrow == "<" else "", dist, arrow if arrow == ">" else "")
        x = self._clear_of_radar(x, text)
        y = self._compass_y(now)
        self.font.draw(low, text, int(x), y, col, align="center")
        if arrow == "V":
            pygame.draw.polygon(low, col, [(x - 4, y + 8), (x + 4, y + 8), (x, y + 13)])

    def _arms_panel(self, low, snap, me, info, by):
        """Left of the bar, Doom's ARMS box: 1-9, lit if you own it, gold in hand.
        (v0.12: 5 more guns past the number row -- SMG through the RPG -- live only on the
        mouse wheel/Q now; there's no room left in this strip for two-digit pips, so it still
        only numbers the original 9. The name below reads correctly for all 14 regardless.)"""
        if BX < 40:
            return
        f = self.font
        ars = snap.arsenal
        cur = info.get("weapon", S.ARM_FISTS)
        for k in range(min(S.ARM_COUNT, 9)):
            owned = S.arsenal_owns(ars, k)
            col = P["gold"] if k == cur and owned else P["white"] if owned else (70, 68, 76)
            f.draw(low, str(k + 1), BX // 2 - 36 + k * 9, by + 4, col, scale=1)
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
        me2 = getattr(snap, "me2", None)
        if me is not None and me[2] == S.DRIVER and me2 is not None and me2[7] & PR.SX_NOS:
            # nitrous gauge along the top of the panel
            frac = max(0.0, min(1.0, me2[4] / C.NOS_TANK))
            low.fill((30, 28, 34), (x0 + 6, by + 1, W - x0 - 12, 3))
            low.fill((90, 170, 255), (x0 + 6, by + 1, int((W - x0 - 12) * frac), 3))
        tr = getattr(snap, "trunk", None)
        if tr is not None and me is not None and me[2] in (S.DRIVER, S.PASSENGER, S.FOOT):
            # (v0.10, Bryce: "show assets for items in back of trunks") on foot this
            # fires the moment you're stood at the bumper -- popping the trunk shows
            # you what you're about to strip before you commit to holding E
            cid, cap, used, items = tr
            f.draw(low, "%d/%d" % (used, cap), cx, by + 4, P["gold"], align="center")
            for k, (tid, style) in enumerate(items[:5]):
                low.blit(self.icons_small6[PART_INDEX[tid]], (x0 + 6 + k * 14, by + 12))
            f.draw(low, "TRUNK", cx, by + 23, P["white"], align="center")
            return
        ars = snap.arsenal or (0, 1) + (0,) * (S.ARSENAL_LEN - 2)
        names = ("SPIKES", "BLOCKS", "BANANA", "DONUTS", "WHOOPEE")
        rows = ["%s x%d" % (names[k], ars[4 + k]) for k in range(5) if len(ars) > 4 + k and ars[4 + k]]
        if len(ars) > 9 and ars[9]:
            rows.insert(0, "BOX (C)")
        for i, r in enumerate(rows[:3]):
            f.draw(low, r, cx, by + 2 + i * 7, P["gold"], align="center")
        if not rows:
            f.draw(low, "-", cx, by + 8, (70, 68, 76), align="center")
        f.draw(low, "GEAR", cx, by + 23, P["white"], align="center")

    def _compass_y(self, now):
        """(v0.12.1) the compass line sat at y=14 -- which is exactly where the SECOND toast
        goes, so any busy moment ("HOTWIRED IT" + "JOB DONE" + ...) printed two lines on top
        of each other. It now ducks under however many toasts are showing."""
        live = sum(1 for t in self.toasts if now - t[2] <= C.TOAST_TIME)
        return 14 if live <= 1 else 3 + 8 * live + 3

    def _clear_of_radar(self, x, text):
        """(v0.12.1) the radar doubled in size and now owns the top-right corner: a centred
        compass label that would run under it slides left until it doesn't."""
        half_w = self.font.width(text) / 2 + 3
        return max(half_w, min(x, getattr(self, "mm_left", W) - half_w))

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
        x = self._clear_of_radar(x, text)
        y = self._compass_y(now)
        if -half <= bearing <= half:
            pygame.draw.polygon(low, col, [(x - 4, y + 8), (x + 4, y + 8), (x, y + 13)])
        self.font.draw(low, text, int(x), y, col, align="center")

    def _crew_compass(self, low, view, info, now):
        """(v0.10, Bryce: "better visibility for multiplayer", clarified as "can't spot
        teammates on the radar/map") one line per teammate, in their own colour, naming
        them and how far and which way -- so the crew can regroup without alt-tabbing to
        the automap. Skips anyone close enough and in frame that you can just look at them."""
        me = view.me
        if me is None:
            return
        yaw = info.get("yaw", 0.0)
        half = math.radians(C.FP_FOV) / 2
        row = 0
        for p in view.players.values():
            if p[0] == me[0]:
                continue
            dist = math.hypot(p[4] - me[4], p[5] - me[5])
            if dist < 10:
                continue                          # close enough to just look at them
            bearing = (math.atan2(p[5] - me[5], p[4] - me[4]) - yaw + math.pi) % (2 * math.pi) - math.pi
            if dist < 60 and -half < bearing < half:
                continue                          # already in frame and near
            col = PLAYER_COLORS[p[1] % 4]
            y = self._compass_y(now) + 20 + row * 8
            row += 1
            if row > 3:
                break
            name = p[13][:10]
            if bearing < -half:
                self.font.draw(low, "< %s %dM" % (name, dist), 6, y, col)
            elif bearing > half:
                self.font.draw(low, "%s %dM >" % (name, dist), getattr(self, "mm_left", W) - 4, y, col,
                               align="right")
            else:
                self.font.draw(low, "%s %dM" % (name, dist), W // 2, y, col, align="center")

    def _comedy_banner(self, low, me, now):
        """YEETED. HUMBLED. STRIKE! Big letters, a wobble, and your dignity."""
        if me is None or len(me) < 17 or not me[16]:
            self.banner_seen = 0
            return
        if me[16] != getattr(self, "banner_seen", 0):
            self.banner_seen = me[16]
            self.banner_t0 = now
        t = now - self.banner_t0
        text = S.BANNER_TEXT[me[16] % len(S.BANNER_TEXT)]
        good = me[16] in (S.BN_HOMERUN, S.BN_STRIKE, S.BN_FREE)
        if me[16] == S.BN_WASTED:
            return                              # (the WASTED screen has it covered)
        scale = 5 if t > 0.15 else 8
        col = P["gold"] if good else P["danger"]
        wob = int(math.sin(now * 14) * 2)
        y = VIEW_H // 2 - 60 + wob
        self.font.draw(low, text, W // 2 + 2, y + 2, P["ink"], scale=scale, align="center")
        self.font.draw(low, text, W // 2, y, col, scale=scale, align="center")

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
            f.draw(low, "NEXT STOP: THE PRECINCT LOCKUP.", W // 2, VIEW_H // 2 - 8, P["gold"], align="center")
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
        for l in ("MOUSE / ARROWS LOOK (UP AND DOWN TOO)     WASD MOVE / DRIVE     SPACE JUMP (IN A CAR: HANDBRAKE)",
                  "SHIFT SPRINT (IN A CAR WITH NOS: BOOST)     E USE (HOLD FOR TIMED ACTIONS)     F EXIT CAR",
                  "V CHASE CAM     TAB MAP     H HORN (CONFUSES COPS)     T DANCE     M MUSIC",
                  "F5 SAVE (HOST)     F8 FISHEYE LENS     F9 BIG HEADS     F10 DISCO FLOOR",
                  "IN A CAR: W+S TOGETHER = BURNOUT (+STEER: DONUTS)     X = HYDRAULIC HOP (IF FITTED)",
                  "CLICK / CTRL: PUNCH, SHOOT, PLACE A TRAP OR THROW WHATEVER'S IN YOUR HANDS",
                  "HOLD CLICK WITH EMPTY FISTS, LET GO: HAYMAKER.  1-9 / WHEEL / Q: PICK A WEAPON",
                  "G: DROP A PART / LET GO OF THE DOLLY / PICK UP A PERSON (THEN CLICK TO THROW THEM)",
                  "PUNCH SOMEONE OR POINT A GUN AT THEM, THEN HOLD E TO ROB THEM. SOME PUNCH BACK.",
                  "TRAFFIC WON'T STOP: SPIKES, A ROADBLOCK OR A BANANA, THEN HOLD E TO CARJACK",
                  "E AT THE BOOT OF YOUR RIDE (OR ANY CAR YOU BROKE INTO): TRUNK. STASH PARTS, FIND LOOT",
                  "E AT THE TUNE-UP BENCH: MOD SHOP. FIT PARTS, PAINT, LIVERIES, JOKE HORNS, NOS",
                  "ENGINES ARE TOO HEAVY TO CARRY: USE THE DOLLY IN THE SHOP",
                  "COPS CAN'T RESIST A BOX OF DONUTS.  RENT IS DUE AT MIDNIGHT AND GOES UP EVERY DAY",
                  "OFFICERS CUFF YOU ON FOOT: PUNCH THEM OR MASH SPACE.  SHOOT AT COPS AND THEY SHOOT BACK",
                  "BUSTED = A CELL: PICK THE LOCK OR PUNCH THE DOOR, THEN KNOCK OUT THE BIG GUARD FOR HIS KEYS",
                  "X ON FOOT: THE PROMPT'S OTHER OPTION (BAIL, SELL A CAR WHOLE, ...)",
                  "",
                  "ESC: RESUME        Q: LEAVE TO MAIN MENU"):
            f.draw(low, l, W // 2, y, P["white"], align="center")
            y += 9

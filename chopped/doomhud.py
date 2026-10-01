"""
doomhud.py -- the Doom-style status bar and first-person overlays.

Top of the view: the DAY BAR (day, a sun-to-moon clock track, CASH vs RENT DUE, the
strike pips) -- the lose condition is the most important thing on screen, so it's the
biggest. Bottom bar, left to right: CASH | HEAT% | the face | HANDS | STAMINA% (or
KM/H in a car) | COPS (cash and heat get the room). The face gets sweatier as the heat goes
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
from . import ui as U
from .art import P, PixelFont, PLAYER_COLORS, CAR_COLORS, GLYPHS, shade
from .parts import PART_IDS, PART_DEFS, PART_INDEX, NO_PART, Part
from . import vehicles as V
from .quests import QUESTS, QUEST_ORDER, ACT_NAMES
from . import story as ST
from . import business as BIZ
from .parts import ENGINE_CLASS_NAMES
from .characters import stamina_max

W, H = C.LOW_W, C.LOW_H
BAR_H = 32
VIEW_H = H - BAR_H
TOP_H = 30               # the day bar across the top of the view (Bryce: "a big bar at the top")
TOP_PAD = TOP_H + 3      # first free row under the day bar: toasts, compass lines and the radar start here
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
BIG_GREEN = ((190, 255, 170), (140, 240, 120), (90, 210, 80), (56, 170, 56), (34, 120, 40))
BIG_BLUE = ((170, 200, 255), (130, 170, 255), (90, 130, 240), (60, 100, 210), (40, 70, 170))


WEAPON_LABELS = ("HANDS", "PISTOL", "SHOTGUN", "SPIKES", "BLOCKS", "BANANAS", "DONUTS", "CHICKEN", "WHOOPEE",
                  "SMG", "RIFLE", "SNIPER", "LAUNCHER", "RPG")


INSPECT_CONDITION = ("SCRAP", "ROUGH", "USED", "TIDY", "MINT")

class Pen:
    """Draws in the original 480-wide coordinates and scales to whatever the
    real view is (640 wide since v0.7), so the fists and guns grow with the
    screen instead of shrinking into the corner. Whole pixels, no blur.
    (v0.17) On the hi-res view (render scale ks x 640 wide) the shapes just get more pixels;
    text and pasted images are pixel art, so they're blown up by the whole number ks."""
    BASE_W = 480

    def __init__(self, surf):
        self.s = surf
        self.k = k = surf.get_width() / float(self.BASE_W)
        self.size = (self.BASE_W, int(round(surf.get_height() / k)))
        self.ks = max(1, int(round(surf.get_width() / float(W))))

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
        if self.ks > 1:
            img = pygame.transform.scale_by(img, self.ks)
        self.s.blit(img, self._pt(pos))

    def text(self, font, text, x, y, col, **kw):
        kw["scale"] = kw.get("scale", 1) * self.ks
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
        # (v0.13) the dialogue box's queue: [speaker, [lines]] blocks, played one at a time.
        # T_SAY lines (small talk) and T_STORY scenes (story.BEATS, by key) both land here.
        self.dialogue = deque()
        self.dlg = None                # the block on screen: [speaker, lines, shown_at]
        self.help_until = time.perf_counter() + 10.0
        self.bar = self._make_bar()
        self.topbar = self._make_topbar()
        self.sky = self._make_sky(self.SKY_W, self.SKY_H)
        self.card_run = None           # (v0.15) which run the day-1 rules card was shown for
        self.card_t0 = 0.0
        self.top_extra = 0             # px the day-1 card pushes the top-left/centre text down
        self.quests_full = False
        self._portraits = {}
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
        # (v0.15) CASH and HEAT get the wide cells (the day/rent block moved to the top bar)
        for x in (0, 140, 224, 256, 318, 396, 480):
            s.fill((50, 48, 54), (BX + x, 2, 1, BAR_H - 4))
            s.fill((130, 128, 134), (BX + x + 1, 2, 1, BAR_H - 4))
        s.fill((30, 28, 34), (BX + 225, 1, 30, BAR_H - 2))       # face well
        return s

    # ---- the day bar's geometry. Why these numbers: DAY is ~66 px of big type, the money
    # block needs ~230 for "$12345 / $300" plus SHORT/COVERED, the pips + legend ~130, and the
    # sky track gets what's left. The radar sits right under the strikes block, so nothing
    # here needs to know about it.
    SKY_X, SKY_W, SKY_Y, SKY_H = 76, 176, 4, 11
    MONEY_X = 262
    STRIKE_X = 506

    def _make_topbar(self):
        s = pygame.Surface((W, TOP_H))
        s.fill((30, 26, 52))
        rng = random.Random(7)
        for _ in range(W * TOP_H // 6):
            s.set_at((rng.randrange(W), rng.randrange(TOP_H)),
                     rng.choice(((24, 20, 44), (38, 34, 62), (20, 18, 38))))
        for x in (72, 256, 500):                                  # chunky dividers between the blocks
            s.fill((14, 12, 26), (x, 2, 2, TOP_H - 5))
            s.fill((70, 64, 100), (x + 2, 2, 1, TOP_H - 5))
        s.fill((90, 84, 130), (0, 0, W, 1))
        s.fill((10, 8, 18), (0, TOP_H - 2, W, 2))
        s.fill((150, 140, 60), (0, TOP_H - 3, W, 1))              # a thin gold rule: it's the important bar
        return s

    def _make_sky(self, w, h):
        """Dawn to midnight, left to right: the track's sky colour shifts along it."""
        keys = ((0.0, (250, 170, 120)), (0.15, (150, 190, 236)), (0.5, (110, 176, 250)),
                (0.68, (244, 150, 80)), (0.8, (120, 60, 110)), (0.9, (36, 30, 84)), (1.0, (12, 10, 40)))
        s = pygame.Surface((w, h))
        rng = random.Random(11)
        for x in range(w):
            t = x / float(w - 1)
            col = keys[-1][1]
            for (t0, c0), (t1, c1) in zip(keys, keys[1:]):
                if t <= t1:
                    u = (t - t0) / (t1 - t0)
                    col = tuple(int(c0[i] + (c1[i] - c0[i]) * u) for i in range(3))
                    break
            s.fill(col, (x, 0, 1, h))
            s.fill(shade(col, 0.82), (x, h - 3, 1, 3))            # a darker "ground" band, chunky
            if t > 0.78 and rng.random() < 0.09:
                s.set_at((x, rng.randrange(0, h - 4)), (240, 240, 210))     # stars
        return s

    def _tint(self, w, h, rgb, alpha):
        key = ("tint", w, h, rgb, alpha)
        s = self._panels.get(key)
        if s is None:
            s = self._panels[key] = pygame.Surface((w, h), pygame.SRCALPHA)
            s.fill((*rgb, alpha))
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

    def face(self, mood, color, flash, char=0):
        key = (mood, self.look, color, flash, char)
        s = self._faces.get(key)
        if s is None:
            try:
                s = FA.make_face(mood, self.look, color, flash, char=char)
            except TypeError:                   # (fpart without the char kwarg yet)
                s = FA.make_face(mood, self.look, color, flash)
            self._faces[key] = s
        return s

    def add_toast(self, text, color, now):
        if color == S.T_SAY:
            name, sep, rest = text.partition(": ")
            if sep and not text.startswith(" "):
                self._dlg_add(name, rest)
            else:
                self._dlg_add(None, text.strip())          # (the rest of a wrapped line)
            return
        if color == S.T_STORY:
            for speaker, line in ST.BEATS.get(text[2:] if text.startswith("B:") else text, ()):
                self.dialogue.append([speaker, [line]])
            while len(self.dialogue) > 40:
                self.dialogue.popleft()                    # (somebody's been spamming E at Paige)
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
        skin0 = FA.char_look(me[-1] if len(me) > 19 else 0)["skin"]
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
        skin = FA.char_look(me[-1] if len(me) > 19 else 0)["skin"]
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
            surf.blit(num, (vw // 2 - num.get_width() // 2, TOP_PAD + 30))
            self.font.draw(surf, "DRIFT x%.1f  %.1fS" % (1.0 + min(3.0, d[0]) * 0.5, d[0]), vw // 2, TOP_PAD + 50,
                           P["gold"], align="center")
        elif now < d[4]:
            self.font.draw(surf, d[3], vw // 2, TOP_PAD + 36, P["gold"], scale=2, align="center")

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
        if len(car) > 15 and V.is_bike(car[15]):
            self._handlebars(pen, car, driving, steer, now, tacho)
            return
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
        if not driving and kind == S.COP:
            # (v0.14) the back of a police car, from the wrong side of the cage: a steel grille
            # between you and the officer, who is humming. Badly.
            for gx in range(20, vw, 22):
                pen.fill((20, 20, 26), (gx, 18, 3, vh - 58))
            for gy in range(30, vh - 40, 26):
                pen.fill((20, 20, 26), (0, gy, vw, 2))
            pen.fill((40, 40, 50), (0, vh - 42, vw, 4))
            return
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

    def _handlebars(self, pen, car, driving, steer, now, tacho=None):
        """(v0.13) on a motorbike there's no dashboard: a tank between your knees, bars in your
        fists (they turn with you), a pair of clocks, and a very clear view of how much danger
        you are in."""
        vw, vh = pen.size
        body = CAR_COLORS[car[2] % len(CAR_COLORS)]
        cx = vw // 2
        pen.poly(shade(body, 0.75), [(cx - 70, vh), (cx + 70, vh), (cx + 40, vh - 34), (cx - 40, vh - 34)])
        pen.poly(body, [(cx - 52, vh), (cx + 52, vh), (cx + 30, vh - 30), (cx - 30, vh - 30)])
        pen.fill(shade(body, 1.2), (cx - 6, vh - 30, 12, 30))                           # the tank's stripe
        if not driving:                                                                # (pillion: a back to hug)
            pen.fill((40, 40, 50), (cx - 60, vh - 70, 120, 70))
            return
        rot = -steer * 0.35
        c, s = math.cos(rot), math.sin(rot)
        by = vh - 46
        ends = []
        for side in (-1, 1):
            x, y = side * 150, 8
            ends.append((cx + int(x * c - y * s), by + int(x * s + y * c)))
        pen.line((30, 30, 38), (cx, by), ends[0], 6)
        pen.line((30, 30, 38), (cx, by), ends[1], 6)
        for ex, ey in ends:
            pen.fill((16, 16, 20), (ex - 14, ey - 5, 28, 10))                           # grips
        spd = math.hypot(car[9], car[10]) * 3.6
        dx, dy = cx + 22, by - 18
        pen.circle((14, 14, 20), (dx, dy), 15)
        pen.circle((120, 120, 130), (dx, dy), 15, 1)
        a = math.radians(210 - min(240, spd * 1.0))
        pen.line((255, 90, 60), (dx, dy), (dx + int(math.cos(a) * 12), dy - int(math.sin(a) * 12)), 2)
        pen.text(self.font, "%d" % spd, dx, dy + 5, P["white"], align="center")
        if tacho is not None:
            self._tacho(pen, cx - 22, dy, 15, tacho, now)

    # ------------------------------------------------------------------ the bar
    def draw(self, low, view, now, info):
        f = self.font
        snap = view.snap
        me = view.me
        flash = int(now * 4) % 2 == 0
        by = H - BAR_H
        low.blit(self.bar, (0, by))
        self._card_state(snap, now, info)
        self.quests_full = bool(info.get("in_garage") or info.get("quests_open"))
        # CASH and HEAT: the two things the bottom bar is about, in the widest cells
        if self.last_cash is not None and snap.cash > self.last_cash:
            self.grin_until = now + 1.6
        self.last_cash = snap.cash
        cash = ("-$%d" % -snap.cash) if snap.cash < 0 else "$%d" % snap.cash
        num = self.big(cash, BIG_RED if snap.cash >= 0 else BIG_BLUE)
        if num.get_width() > 128:
            num = pygame.transform.scale(num, (128, num.get_height()))
        low.blit(num, (BX + 70 - num.get_width() // 2, by + 3))
        f.draw(low, "CASH", BX + 70, by + 23, P["white"], align="center")
        heat_ramp = BIG_BLUE if snap.cops and flash else BIG_RED
        num = self.big("%d%%" % snap.heat, heat_ramp)
        low.blit(num, (BX + 182 - num.get_width() // 2, by + 3))
        f.draw(low, "HEAT", BX + 182, by + 23, P["white"], align="center")
        # everything below is secondary: small type, dim labels
        dim = (214, 212, 222)          # (readable on the grey bar; the SIZE is what marks them secondary)
        hx = BX + 263
        hc = hx + 24
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
                low.fill((92, 90, 96), (hx - 3, by + 2, 54, 20))
                f.draw(low, "%d" % n, hc, by + 7, P["white"] if n else P["danger"], scale=2, align="center")
            else:
                for i, h in enumerate(hands):
                    low.blit(self.icons2[h], (hx + 3 + i * 26, by + 4))
        label = "HANDS"
        if me is not None and me[3] & PR.PF_DOLLY:
            label = "DOLLY"
        elif me is not None and me[9] == NO_PART and info.get("weapon", S.ARM_FISTS) != S.ARM_FISTS:
            label = WEAPON_LABELS[info["weapon"]]
        f.draw(low, label, hc, by + 23, dim, align="center")
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
            low.blit(self.face(mood, me[1], fl, me[-1] if len(me) >= 20 and isinstance(me[-1], int) else 0),
                     (BX + 227, by + 1))
        # STAMINA / SPEED
        car = view.my_car
        sx = BX + 357
        if car is not None and me is not None and me[2] in (S.DRIVER, S.PASSENGER):
            f.draw(low, "%d" % (math.hypot(car[9], car[10]) * 3.6), sx, by + 7, P["white"], scale=2, align="center")
            f.draw(low, "KM/H", sx, by + 23, dim, align="center")
        elif me is not None:
            winded = me[3] & PR.PF_EXHAUSTED
            # (v0.16) a percentage of YOUR pool: DASH's bigger lungs shouldn't read 210%
            pool = stamina_max(me[-1] if len(me) >= 20 and isinstance(me[-1], int) else 0)
            f.draw(low, "%d%%" % (100 * me[11] / pool), sx, by + 7, P["danger"] if winded else P["white"], scale=2, align="center")
            f.draw(low, "WINDED!" if winded else "STAMINA", sx, by + 23,
                   P["danger"] if winded and flash else dim, align="center")
        # COPS
        cx = BX + 438
        for i in range(min(snap.cops, 2)):
            c = (255, 60, 60) if (flash ^ bool(i)) else (80, 120, 255)
            low.fill(P["ink"], (cx - 14 + i * 16, by + 5, 12, 14))
            low.fill(c, (cx - 13 + i * 16, by + 6, 10, 5))
            low.fill(P["white"], (cx - 13 + i * 16, by + 12, 10, 6))
        lethal = getattr(snap, "alert", 0) & PR.AL_LETHAL
        f.draw(low, "LETHAL" if lethal else "COPS", cx, by + 23,
               (P["danger"] if flash else P["white"]) if lethal else (130, 170, 255) if snap.cops else dim,
               align="center")
        self._arms_panel(low, snap, me, info, by)
        self._gear_panel(low, snap, me, view, by)
        # ---- above the bar -------------------------------------------------
        self._day_bar(low, snap, now, flash)
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
                self._story_compass(low, view, info, now)
                self._story_compass(low, view, info, now, "biz_target", 24, (90, 230, 120))
        self._law_overlay(low, snap, me, now, flash)
        if not info.get("paused") and not info.get("menu"):
            self._inspect_card(low, snap, now)
        self._banners(low, snap, me, now, flash)
        self._comedy_banner(low, me, now)
        if now < self.help_until and not info.get("paused") and not info.get("menu") and self.dlg is None:
            # (v0.13) the controls live behind the pause menu's INSTRUCTIONS button now; the
            # first few seconds of a session just say where to find them
            t = "ESC: PAUSE / INSTRUCTIONS"
            low.blit(self._panel(f.width(t) + 12, 12, 170), (W // 2 - f.width(t) // 2 - 6, VIEW_H - 40))
            f.draw(low, t, W // 2, VIEW_H - 37, P["gold"], align="center")

    CARD_TIME = 25.0        # s the day-1 rules card stays up
    CARD_H = 24

    def _card_state(self, snap, now, info):
        """(v0.15) once per run, on day 1: the rules card under the day bar. Keyed on snap.run so a
        fresh run after a seizure gets it again."""
        run = getattr(snap, "run", 0)
        if snap.day == 1 and run != self.card_run:
            self.card_run, self.card_t0 = run, now
        self.card_on = bool(snap.day == 1 and now - self.card_t0 < self.CARD_TIME and snap.gameover <= 0
                            and not info.get("paused") and not info.get("menu"))
        self.top_extra = self.CARD_H if self.card_on else 0

    def _day_bar(self, low, snap, now, flash):
        """(v0.15, Bryce: "make the lose condition much more apparent") the Majora's-Mask-style band
        across the top: DAY, a dawn-to-midnight track with a sun that turns into a moon, CASH against
        RENT DUE, the countdown, and the strike pips. It escalates: pulses when you're short and
        the clock's under RENT_WARN_TIME, and goes full alarm in the last 15 s with a strike standing."""
        f = self.font
        smax = getattr(C, "RENT_STRIKES_MAX", 2)
        strikes = max(0, int(getattr(snap, "strikes", 0) or 0))
        back = int(getattr(snap, "back_rent", 0) or 0)
        due, cash = int(snap.rent_due), snap.cash
        left = max(0.0, snap.rent)
        seized = snap.gameover > 0
        if seized:
            strikes = smax
        short = cash < due
        warn = short and left <= getattr(C, "RENT_WARN_TIME", 45.0)
        final = seized or (short and strikes >= smax - 1 and strikes > 0 and left <= 15.0)
        ox = 1 if (final and int(now * 24) % 2) else 0            # the alarm makes the whole bar judder
        low.blit(self.topbar, (0, 0))
        if final:
            low.blit(self._tint(W, TOP_H, (230, 20, 20), 150 if flash else 90), (0, 0))
            for r in ((0, TOP_H, 3, VIEW_H - TOP_H), (W - 3, TOP_H, 3, VIEW_H - TOP_H), (0, VIEW_H - 3, W, 3)):
                low.blit(self._tint(r[2], r[3], (230, 20, 20), 110 if flash else 50), r[:2])
        elif warn:
            a = int((22 + 80 * (0.5 + 0.5 * math.sin(now * 6))) // 10) * 10
            low.blit(self._tint(W, TOP_H, (220, 30, 30), a), (0, 0))
        # DAY
        num = self.big("DAY %d" % snap.day, BIG_GOLD)
        if num.get_width() > 64:
            num = pygame.transform.scale(num, (64, num.get_height()))
        low.blit(num, (6 + ox, 6))
        # the track: elapsed time darkens behind the sun
        p = max(0.0, min(1.0, 1.0 - left / C.DAY_LENGTH))
        kx, ky, kw, kh = self.SKY_X + ox, self.SKY_Y, self.SKY_W, self.SKY_H
        low.fill((10, 8, 18), (kx - 2, ky - 2, kw + 4, kh + 4))
        low.fill((110, 104, 150), (kx - 1, ky - 1, kw + 2, kh + 2))
        low.blit(self.sky, (kx, ky))
        done_w = int(p * kw) // 2 * 2
        if done_w:
            low.blit(self._tint(done_w, kh, (0, 0, 20), 70), (kx, ky))
        for i in range(1, 6):
            low.fill((10, 8, 18), (kx + kw * i // 6, ky, 1, 2))
        endc = (255, 60, 50) if (warn and flash) else (170, 30, 30)
        low.fill(endc, (kx + kw - 2, ky, 2, kh))                   # midnight
        sx = max(kx + 4, min(kx + kw - 5, kx + int(p * kw)))
        cy = ky + 6 - int(math.sin(math.pi * p) * 2)
        if p < 0.72:
            body = (255, 230, 90) if p < 0.55 else (255, 170, 60)
            pygame.draw.circle(low, (255, 250, 190) if p < 0.55 else (255, 200, 110), (sx, cy), 5)
            pygame.draw.circle(low, body, (sx, cy), 4)
            for a, b in ((-7, 0), (7, 0), (0, -7), (0, 7)):        # chunky rays
                low.fill(body, (sx + a - (a == 0), cy + b - (b == 0), 1 + 0, 1 + 0))
        else:
            pygame.draw.circle(low, (236, 236, 214), (sx, cy), 4)
            bx, by_ = min(kx + kw - 1, sx + 2), cy - 1
            pygame.draw.circle(low, self.sky.get_at((max(0, min(kw - 1, bx - kx)), 2)), (bx, by_), 3)
        # countdown
        if seized:
            text, col = "SHOP SEIZED", (P["white"] if flash else (255, 90, 70))
        elif final:
            text, col = "FINAL HOURS %s" % mmss(left), (P["white"] if flash else (255, 90, 70))
        else:
            text = "MIDNIGHT IN %s" % mmss(left)
            col = (P["danger"] if flash else P["white"]) if warn else P["white"]
        f.draw(low, text, kx, 16, col, scale=2)
        # CASH vs RENT DUE
        mx = self.MONEY_X + 8 + ox
        cash_txt = ("-$%d" % -cash) if cash < 0 else "$%d" % cash
        cs = self.big(cash_txt, BIG_RED if short else BIG_GREEN)
        ds = self.big("/ $%d" % due, BIG_GOLD)
        total = cs.get_width() + 6 + ds.get_width()
        if total > 150:                                            # a ridiculous fortune: squash, don't overflow
            k = 150.0 / total
            cs = pygame.transform.scale(cs, (max(1, int(cs.get_width() * k)), 17))
            ds = pygame.transform.scale(ds, (max(1, int(ds.get_width() * k)), 17))
            total = cs.get_width() + 6 + ds.get_width()
        low.blit(cs, (mx, 10))
        low.blit(ds, (mx + cs.get_width() + 6, 10))
        f.draw(low, "CASH", mx, 2, P["metal_l"])
        lab = "RENT DUE" + (" (INCL $%d BACK RENT)" % back if back > 0 else "")
        f.draw(low, lab, mx + cs.get_width() + 6, 2, P["gold"] if back > 0 else P["metal_l"])
        if short:
            st, sc = "SHORT $%d" % (due - cash), (P["danger"] if (warn and flash) else (255, 90, 70))
        else:
            st, sc = "COVERED", P["money"]
        scale = 2 if mx + total + 8 + len(st) * 8 <= self.STRIKE_X - 8 else 1
        f.draw(low, st, self.STRIKE_X - 8, 13 if scale == 2 else 16, sc, scale=scale, align="right")
        # STRIKES
        px = self.STRIKE_X + 8 + ox
        f.draw(low, "MISSED RENT", px, 2, P["metal_l"])
        for i in range(smax):
            x = px + i * 20
            hit = i < strikes
            edge = (255, 90, 70) if hit else (110, 104, 150)
            if hit or (i == strikes and warn):
                low.fill(edge if (hit or flash) else (110, 104, 150), (x - 1, 9, 18, 17))
            else:
                low.fill(edge, (x - 1, 9, 18, 17))
            low.fill((200, 30, 30) if hit else (22, 18, 36), (x, 10, 16, 15))
            if hit:
                pygame.draw.line(low, P["white"], (x + 3, 13), (x + 12, 21), 2)
                pygame.draw.line(low, P["white"], (x + 12, 13), (x + 3, 21), 2)
        lx = px + smax * 20 + 4
        f.draw(low, "%d MISSES =" % smax, lx, 10, P["metal_l"])
        f.draw(low, "SHOP SEIZED", lx, 18, (255, 90, 70) if (strikes or final) else P["danger"])
        # the day-1 card, hung off the bar
        if self.card_on:
            l1, l2 = "PAY THE RENT BY MIDNIGHT.", "MISS IT TWICE AND YOU LOSE THE SHOP."
            w = max(f.width(l1), f.width(l2)) + 14
            low.blit(self._panel(w, self.CARD_H - 1, 225), (6, TOP_H))
            low.fill(P["gold"], (6, TOP_H, w, 1))
            low.fill(P["gold"], (6, TOP_H, 1, self.CARD_H - 1))
            f.draw(low, l1, 12, TOP_H + 4, P["gold"])
            f.draw(low, l2, 12, TOP_H + 13, P["white"])

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
        if flags & getattr(S, "INSP_HOT", 0):
            lines.append(("HOT: DRAWS HEAT", P["danger"]))    # (v0.19) sporty models cost double to take
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
        oy = 80                                 # (under the toasts and the compass lines, over the action)
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
        y = TOP_PAD + self.top_extra
        for text, col, t0 in list(self.toasts):
            if now - t0 > C.TOAST_TIME:
                continue
            self.font.draw(low, text, 4, y, col)
            y += 8
        while self.toasts and now - self.toasts[0][2] > C.TOAST_TIME:
            self.toasts.popleft()

    def _dlg_add(self, speaker, text):
        """Small talk arrives a line at a time: the same speaker keeps adding to their
        block (up to a screenful), a new speaker gets a new one."""
        last = self.dialogue[-1] if self.dialogue else self.dlg
        if last is not None and (speaker is None or speaker == last[0]) and len(last[1]) < 6:
            last[1].append(text)
            return
        self.dialogue.append([speaker or "", [text]])

    def skip_speech(self):
        """(v0.13) ENTER: done reading, next line please."""
        self.dlg = None

    def _dlg_time(self, block):
        chars = sum(len(t) for t in block[1])
        return max(3.0, min(C.SAY_TIME, 1.2 + chars * 0.055))

    def _wrap_px(self, text, width):
        f = self.font
        out, line = [], ""
        for word in text.split():
            trial = (line + " " + word) if line else word
            if line and f.width(trial) > width:
                out.append(line)
                line = word
            else:
                line = trial
        if line:
            out.append(line)
        return out

    def _portrait(self, speaker):
        """(v0.15) the speaker's face, 24x24, from fpart.portrait (cached; None if there isn't one)."""
        if not speaker:
            return None
        if speaker not in self._portraits:
            fn = getattr(FA, "portrait", None)
            img = None
            if fn is not None:
                try:
                    img = fn(speaker, 24)
                except Exception:
                    img = None
            self._portraits[speaker] = img
        return self._portraits[speaker]

    def _speech(self, low, now):
        """(v0.12.1) someone talking to you: a box low in the middle of the view. (v0.13) a
        queue: a story scene is a conversation, so each speaker gets the box in turn, paced
        by how much they've got to say, and ENTER skips ahead."""
        if self.dlg is not None and now - self.dlg[2] > self._dlg_time(self.dlg):
            self.dlg = None
        if self.dlg is None:
            if not self.dialogue:
                return
            sp, lines = self.dialogue.popleft()
            self.dlg = [sp, lines, now]
        f = self.font
        speaker, lines = self.dlg[0], self.dlg[1]
        width = W - 60
        face = self._portrait(speaker)
        tx = 36 if face is not None else 5            # text column: past the 24 px portrait and its frame
        body = []
        for t in lines:
            body.extend(self._wrap_px(t, width - tx - 6))
        h = max(8 * len(body) + 14, 34 if face is not None else 0)
        x, y = W // 2 - width // 2, VIEW_H - 22 - h
        low.blit(self._panel(width, h, 200), (x, y))
        low.fill(P["gold"], (x, y, width, 1))
        if face is not None:
            low.fill(P["ink"], (x + 4, y + 4, 26, 26))                       # the same 1 px frame as the HUD face
            low.fill(P["gold"], (x + 4, y + 4, 26, 1))
            low.blit(face, (x + 5, y + 5))
        f.draw(low, speaker, x + tx, y + 3, P["gold"])
        for i, t in enumerate(body):
            f.draw(low, t, x + tx, y + 12 + i * 8, P["white"])
        if self.dialogue:
            f.draw(low, "ENTER: NEXT (%d)" % len(self.dialogue), x + width - 5, y + 3, P["metal_l"], align="right")

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
        mx, my = W - mw - 3, TOP_PAD             # (v0.15) under the day bar
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
        self.last_cars = view.cars
        self._quest_panel(low, view.snap, W - 3, my + mh + 3)

    def _quest_panel(self, low, snap, x, y):
        """Under the radar. (v0.15) Compact by default -- the story goal, one line of job/REP
        count and at most two business rows -- and the whole list (today's 3 jobs, every order)
        while you're in the shop or holding J. Old text: today's 3 jobs and the crew's reputation/act. Nothing but
        ids and a done bitmask rides the wire (protocol.SNAP_HDR) -- names, briefs and
        rewards come from quests.QUESTS, the same fixed table on both ends. Right-aligned
        to the screen edge (v0.12.1: it used to start at the radar's left edge and run off
        the right side of the screen -- Bryce: "the daily quests are off the screen")."""
        f = self.font
        rows = self._story_rows(snap)
        act = ("I", "II", "III")[max(0, min(2, snap.act - 1))]
        full = self.quests_full
        if not full:
            rows = [r for r in rows if r[0]]
            valid = [i for i, idx in enumerate(snap.today_quests) if idx != PR.NO_QUEST and idx < len(QUEST_ORDER)]
            n_done = sum(1 for i in valid if snap.quest_done & (1 << i))
            rows.append(("JOBS %d/%d - REP %d - ACT %s" % (n_done, len(valid), snap.story_points, act),
                         P["money"] if valid and n_done == len(valid) else P["metal_l"]))
            biz = [r for r in self._biz_rows(snap) if r[0]]
            rows.extend(biz[:2])
            if len(biz) > 2:
                rows.append(("+%d MORE" % (len(biz) - 2), P["metal_l"]))
            rows.append(("HOLD J: ALL JOBS", (110, 108, 120)))
        else:
            rows.append(("REP %d - ACT %s" % (snap.story_points, act), P["gold"]))
            for i, idx in enumerate(snap.today_quests):
                if idx == PR.NO_QUEST or idx >= len(QUEST_ORDER):
                    continue
                name, brief, diff, cash, rep, minp, tlim, coop = QUESTS[QUEST_ORDER[idx]]
                done = bool(snap.quest_done & (1 << i))
                rows.append((("%s $%d" % (name, cash)) if not done else "%s DONE" % name,
                             P["money"] if done else P["white"]))
            rows.extend(self._biz_rows(snap))
        width = max(f.width(t) for t, _ in rows) + 6
        low.blit(self._panel(width, 8 * len(rows) + 3, 150 if full else 115), (x - width + 2, y - 2))
        for t, col in rows:
            if t:
                f.draw(low, t, x, y, col, align="right")
            y += 8
        self.quest_bottom = y

    def _biz_rows(self, snap):
        """(v0.14) the business, under the daily jobs: Mo's dolly job, drop-off orders, what's
        under Dave's hammer, and sold cars waiting to be driven over."""
        rows = []
        contacts = getattr(self, "contacts", ())
        dolly = getattr(snap, "dolly", 0) or 0
        lvl = dolly & 3
        if dolly & 4 and lvl < len(C.DOLLY_UPGRADES):
            rep, fee, cat, mc, name = C.DOLLY_UPGRADES[lvl]
            want = ("A %s ENGINE" % ENGINE_CLASS_NAMES[mc]) if cat == "engine" else "A GEARBOX"
            rows.append(("MO: %s + $%d = %s" % (want, fee, name), P["metal_l"]))
        orders = getattr(snap, "orders", None) or ()
        sales = getattr(snap, "sales", None) or ()
        if orders or sales or getattr(snap, "lots", 0):
            rows.append(("", None))
        for (who, cat_i, got, need) in orders:
            nm = contacts[who][0] if who < len(contacts) else "?"
            if cat_i < len(BIZ.ORDER_CATS):
                rows.append(("%s: %d/%d %s +$%d" % (nm, got, need, BIZ.order_label(cat_i, need),
                                                    BIZ.order_bonus(cat_i, need)), P["gold"]))
        cars = getattr(self, "last_cars", {})
        for (cid, who, price) in sales:
            nm = contacts[who][0] if who < len(contacts) else "?"
            row = cars.get(cid)
            what = V.model(row[15]).name.upper() if row is not None and len(row) > 15 else "CAR"
            rows.append(("DRIVE THE %s TO %s: $%d" % (what, nm, price), (90, 230, 120)))
        if getattr(snap, "lots", 0):
            rows.append(("DAVE'S AUCTION: %d LOT%s, NEXT %dS" % (snap.lots, "S" if snap.lots > 1 else "", snap.hammer),
                         P["money"]))
        return rows

    def _story_rows(self, snap):
        """(v0.13) the main story, above the daily jobs: which chapter, and what to do about it
        -- earn REP, go and talk to somebody, or the objective itself (with a count)."""
        st = getattr(snap, "story_st", ST.ST_DONE)
        ch = ST.chapter(getattr(snap, "story_ch", len(ST.CHAPTERS)))
        if ch is None or st == ST.ST_DONE:
            return [("STORY: THE END", P["gold"]), ("", None)]
        rows = [("STORY %d/%d: %s" % (snap.story_ch + 1, len(ST.CHAPTERS), ch.title), P["gold"])]
        if st == ST.ST_LOCKED:
            rows.append(("NEEDS %d REP (HAVE %d): DO THE DAILY JOBS" % (ch.rep, snap.story_points),
                         P["metal_l"]))
        elif st == ST.ST_TALK:
            rows.append(("> TALK TO %s %s" % (ST.GIVERS[ch.giver], ST.GIVER_WHERE[ch.giver]), P["money"]))
        else:
            for line in self._wrap_px("> " + ch.goal(snap.story_n), 200):
                rows.append((line, P["white"]))
        rows.append(("", None))
        return rows

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
        f.draw(low, "ARMS", BX // 2, by + 23, (214, 212, 222), align="center")

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
            f.draw(low, "TRUNK", cx, by + 23, (214, 212, 222), align="center")
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
        f.draw(low, "GEAR", cx, by + 23, (214, 212, 222), align="center")

    def _compass_y(self, now):
        """(v0.12.1) the compass line sat at y=14 -- which is exactly where the SECOND toast
        goes, so any busy moment ("HOTWIRED IT" + "JOB DONE" + ...) printed two lines on top
        of each other. It now ducks under however many toasts are showing."""
        live = sum(1 for t in self.toasts if now - t[2] <= C.TOAST_TIME)
        # (v0.15) the toasts now start under the day bar (and under the day-1 card while it's up)
        return TOP_PAD + self.top_extra + (11 if live <= 1 else 8 * live + 3)

    def _story_compass(self, low, view, info, now, key="story_target", dy=16, col=None):
        """(v0.13) a gold arrow to whoever the story wants you to talk to next. (v0.14: also,
        with key="biz_target", a green one to the buyer or the contact who ordered what you've got.)"""
        tgt = info.get(key)
        me = view.me
        if tgt is None or me is None:
            return
        tx, ty, label = tgt
        dist = math.hypot(tx - me[4], ty - me[5])
        if dist < 6.0:
            return
        yaw = info.get("yaw", 0.0)
        bearing = (math.atan2(ty - me[5], tx - me[4]) - yaw + math.pi) % (2 * math.pi) - math.pi
        half = math.radians(C.FP_FOV) / 2
        x = W / 2 + max(-1.0, min(1.0, bearing / half)) * (W / 2 - 40)
        if bearing < -half:
            text = "< %s %dM" % (label, dist)
        elif bearing > half:
            text = "%s %dM >" % (label, dist)
        else:
            text = "%s %dM" % (label, dist)
        x = self._clear_of_radar(x, text)
        y = self._compass_y(now) + dy
        self.font.draw(low, text, int(x), y, col or P["gold"], align="center")

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
            y = self._compass_y(now) + 28 + row * 8
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
            strikes = int(getattr(snap, "strikes", 0) or 0)
            low.blit(self._panel(W, 53 if strikes else 43, 170), (0, 76))
            num = self.big("DAY %d" % snap.day, BIG_GOLD)
            num = pygame.transform.scale(num, (num.get_width() * 2, num.get_height() * 2))
            low.blit(num, (W // 2 - num.get_width() // 2, 78))
            f.draw(low, "RENT AT MIDNIGHT: $%d" % snap.rent_due, W // 2, 109, P["white"], align="center")
            if strikes:
                f.draw(low, "YOU ALREADY MISSED ONE. MISS THE NEXT AND THE SHOP IS GONE.", W // 2, 119,
                       P["danger"] if flash else P["gold"], align="center")
        if me is not None and me[2] == S.CUFFED:
            f.draw(low, "BUSTED", W // 2, VIEW_H // 2 - 50, P["danger"] if flash else (130, 170, 255),
                   scale=5, align="center")
            f.draw(low, "YOUR PARTS ARE ON THE PAVEMENT. YOUR PARTNER CAN GRAB THEM.", W // 2, VIEW_H // 2 - 18,
                   P["white"], align="center")
            f.draw(low, "NEXT STOP: THE PRECINCT LOCKUP.", W // 2, VIEW_H // 2 - 8, P["gold"], align="center")
        if snap.gameover > 0:
            low.blit(self._panel(W, 86, 190), (0, VIEW_H // 2 - 40))
            f.draw(low, "SHOP SEIZED", W // 2, VIEW_H // 2 - 34, P["danger"], scale=5, align="center")
            f.draw(low, "MISSED RENT TWICE", W // 2, VIEW_H // 2 + 0, P["white"], scale=2, align="center")
            f.draw(low, "THE LANDLORD HAS YOUR KEYS.", W // 2, VIEW_H // 2 + 20, P["white"], align="center")
            f.draw(low, "NEW RUN IN %d... (YOUR RIDE KEEPS ITS MODS)" % (int(snap.gameover) + 1), W // 2,
                   VIEW_H // 2 + 30, P["gold"], align="center")

    # (v0.13, Bryce: "put the instructions in a hidden window unless you press on the instructions
    # button in the paused screen") the pause screen is a menu now -- three buttons -- and the
    # wall of controls lives behind INSTRUCTIONS instead of being the first thing you see.
    PAUSE_BUTTONS = (("resume", "RESUME", "ESC"), ("help", "INSTRUCTIONS", "I"),
                     ("settings", "SETTINGS", "S"), ("leave", "LEAVE TO MENU", "Q"))
    HELP_SECTIONS = (
        ("THE RENT (HOW YOU LOSE)",
         ("RENT IS TAKEN AT MIDNIGHT. THE BAR AT THE TOP SHOWS YOUR CASH AGAINST THE BILL, AND HOW LONG YOU'VE GOT",
          "CAN'T COVER IT? THAT'S A STRIKE, AND THE BILL CARRIES OVER. PAY IT IN FULL AND THE STRIKES GO AWAY",
          "TWO STRIKES IN A ROW AND THE SHOP IS SEIZED: NEW RUN (YOUR OWN CAR KEEPS ITS MODS)")),
        ("MOVING", ("MOUSE / ARROWS: LOOK (UP AND DOWN TOO)     WASD: MOVE / DRIVE     SPACE: JUMP",
                    "SHIFT: SPRINT (IN A CAR WITH NOS: BOOST)     E: USE (HOLD FOR TIMED ACTIONS)     F: EXIT CAR",
                    "IN A CAR: SPACE HANDBRAKE, W+S BURNOUT (+STEER: DONUTS), X HYDRAULIC HOP (IF FITTED)",
                    "BIKES: SAME KEYS. FAST, TINY, AND YOU FALL OFF IF YOU SO MUCH AS SNEEZE AT A LAMPPOST")),
        ("CRIME", ("CLICK / CTRL: PUNCH, SHOOT, PLACE A TRAP OR THROW WHATEVER'S IN YOUR HANDS",
                   "HOLD CLICK WITH EMPTY FISTS, LET GO: HAYMAKER.     1-9 / WHEEL / Q: PICK A WEAPON",
                   "G: DROP A PART / LET GO OF THE DOLLY / PICK UP A PERSON (THEN CLICK TO THROW THEM)",
                   "PUNCH SOMEONE OR POINT A GUN AT THEM, THEN HOLD E TO ROB THEM. SOME PUNCH BACK.",
                   "TRAFFIC WON'T STOP: SPIKES, A ROADBLOCK OR A BANANA, THEN HOLD E TO CARJACK",
                   "X AT A LOCKED CAR: CUT THE WIRES (QUIET, IF YOU GUESS RIGHT). X ON FOOT: THE PROMPT'S OTHER OPTION")),
        ("THE SHOP", ("PARK A STOLEN CAR INSIDE TO DELIVER IT. HOLD E ON IT TO STRIP PARTS. ENGINES NEED THE DOLLY",
                      "E AT THE TUNE-UP COUNTER: MOD SHOP (X: TALK TO MO ABOUT A BIGGER DOLLY). E AT A BOOT: TRUNK",
                      "E AT A CRATE: THE BLACK MARKET.  F5: SAVE (HOST)",
                      "E AT THE RED HANDLE BY THE WALKING DOOR: SHUT (OR OPEN) EVERY DOOR AT ONCE")),
        ("BUSINESS", ("DAVE AUCTIONS WHAT YOU BRING HIM: X SETS THE PRICE. THE MONEY COMES WHEN THE HAMMER FALLS",
                      "SELL A CAR WHOLE: PAPERS FROM THE PRECINCT'S RECORDS HATCH, AUCTION IT, DRIVE IT TO THE BUYER",
                      "CONTACTS ROUND TOWN WANT PARTS (GOLD MARKERS): HAND THEM OVER IN PERSON FOR BETTER MONEY",
                      "BUY A GARAGE AT ITS SIGN, CLEAR THE JUNK (OR PAY A CREW): BETTER CRATES, A BETTER MOD SHOP")),
        ("STORY", ("THE STORY PANEL (UNDER THE RADAR) SAYS WHO TO TALK TO NEXT. HOLD J FOR TODAY'S FULL JOB LIST.",
                   "WALK UP AND PRESS E. DAILY JOBS EARN REP, AND REP OPENS THE NEXT CHAPTER.  ENTER: SKIP A LINE OF DIALOGUE",
                   "CHARACTERS: PICK ONE ON THE MAIN MENU (A/D). EACH HAS A PERK, SHOWN ON THE PAUSE SCREEN")),
        ("THE LAW", ("OFFICERS CUFF YOU ON FOOT: PUNCH THEM OR MASH SPACE.  SHOOT AT COPS AND THEY SHOOT BACK",
                     "BUSTED: HE CARRIES YOU TO HIS CAR AND DRIVES YOU IN. YOUR CREW CAN STOP THE CAR ON THE WAY",
                     "THEN A CELL: PICK THE LOCK OR PUNCH THE DOOR, AND KNOCK OUT THE BIG GUARD FOR HIS KEYS",
                     "COP CARS CARJACK LIKE TRAFFIC: STOP ONE, HOLD E, DRAG THE OFFICER OUT (+30 HEAT)",
                     "THE IMPOUND BIKES OUTSIDE THE PRECINCT HAVE THE KEYS IN.  H: HORN (CONFUSES COPS)")),
        ("SILLY", ("V CHASE CAM   TAB MAP   T DANCE   M MUSIC   F8 FISHEYE   F9 BIG HEADS   F10 DISCO   C BOX",
                  "PAUSE (ESC): I INSTRUCTIONS   S SETTINGS (FOV, MOUSE SENSITIVITY, INVERT Y, RENDER, VOLUMES, SAVES)   Q LEAVE TO MENU")),
    )

    def pause_hit(self, pos):
        """Which pause button (if any) is under this canvas point."""
        for name, rect in getattr(self, "pause_rects", {}).items():
            if rect.collidepoint(pos):
                return name
        return None

    def draw_pause(self, low, info):
        f = self.font
        low.blit(self._panel(W, H, 222), (0, 0))
        if info.get("settings") is not None:          # (v0.17) ui.SettingsPanel draws and handles itself
            self.pause_rects = {}
            info["settings"].draw(low, info.get("mouse"))
            return
        if info.get("help"):
            self._draw_instructions(low, info)
            return
        f.draw(low, "PAUSED", W // 2, 30, P["gold"], None, scale=4, align="center")
        f.draw(low, "(THE CITY KEEPS MOVING. SO DOES THE CLOCK.)", W // 2, 58, P["metal_l"], align="center")
        y = 74
        for line, col in info.get("lines", []):
            f.draw(low, line, W // 2, y, col, align="center")
            y += 9
        y = max(y + 14, 150)
        self._pause_perk(low, info.get("char", 0), y - 12)
        y += 30
        mouse = info.get("mouse")
        self.pause_rects = {}
        for name, label, key in self.PAUSE_BUTTONS:
            r = pygame.Rect(W // 2 - 90, y, 180, 22)
            self.pause_rects[name] = r
            hot = mouse is not None and r.collidepoint(mouse)
            low.fill((70, 60, 100) if hot else (40, 36, 58), r)
            low.fill(P["gold"] if hot else (90, 84, 110), (r.x, r.y, r.w, 1))
            f.draw(low, label, W // 2, y + 8, P["gold"] if hot else P["white"], align="center")
            f.draw(low, key, r.right - 6, y + 8, P["metal_l"], align="right")
            y += 28

    def _pause_perk(self, low, char, y):
        """(v0.16) who you are and what your perk does: a 32 px portrait, NAME - TITLE, the perk."""
        ch = U.char_info(char)
        w = 260
        x = W // 2 - w // 2
        low.fill((40, 36, 58), (x, y, w, 36))
        low.fill(P["gold"], (x, y, w, 1))
        low.fill(P["ink"], (x + 3, y + 2, 32, 32))
        low.blit(U.char_portrait(char, 30), (x + 4, y + 3))
        self.font.draw(low, "%s - %s" % (ch["name"], ch["title"]), x + 42, y + 7, P["gold"])
        self.font.draw(low, ("PERK: " + ch["perk"])[:52], x + 42, y + 19, P["money"])

    def _draw_instructions(self, low, info):
        f = self.font
        w, h = W - 40, H - 12          # (v0.17: 6 px more room for the pause-keys line)
        x0, y0 = 20, 6
        low.blit(self._panel(w, h, 235), (x0, y0))
        low.fill(P["gold"], (x0, y0, w, 1))
        f.draw(low, "INSTRUCTIONS", W // 2, y0 + 6, P["gold"], scale=2, align="center")
        y = y0 + 20
        for title, lines in self.HELP_SECTIONS:
            f.draw(low, title, x0 + 10, y, P["gold"])
            y += 9
            for l in lines:
                f.draw(low, l, x0 + 18, y, P["white"])
                y += 8
            y += 1          # (was 2; the CHARACTERS line needed the room to keep SILLY on the page)
        mouse = info.get("mouse")
        r = pygame.Rect(x0 + 8, y0 + 4, 96, 14)          # (top-left: the bottom is full of sections now)
        self.pause_rects = {"back": r}
        hot = mouse is not None and r.collidepoint(mouse)
        low.fill((70, 60, 100) if hot else (40, 36, 58), r)
        f.draw(low, "BACK (ESC)", r.centerx, r.y + 4, P["gold"] if hot else P["white"], align="center")

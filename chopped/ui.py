"""
ui.py -- the HUD, the menus and the "you have made poor choices" banners.
Everything is drawn on the 480x270 canvas with the pixel font.
"""

import math
import time
from collections import deque

import pygame

from . import config as C
from . import sim as S
from . import protocol as PR
from .art import P, PixelFont, PLAYER_COLORS
from .parts import PART_IDS, PART_DEFS, NO_PART

W, H = C.LOW_W, C.LOW_H
TOAST_COLORS = {S.T_WHITE: P["white"], S.T_MONEY: P["money"], S.T_BAD: P["danger"],
                S.T_INFO: P["gold"], S.T_COP: (130, 170, 255)}
WITNESS_TEXT = {
    S.W_COP: ("A COP SEES YOU  +5/S", (130, 170, 255)),
    S.W_PED: ("A WITNESS SEES YOU  +3/S", P["gold"]),
    S.W_OWNER: ("THE OWNER SEES YOU  +3/S", P["danger"]),
    S.W_CAMERA: ("STREET CAMERA SEES THE CAR  +2/S", P["gold"]),
}


def mmss(t):
    t = max(0, int(math.ceil(t)))
    return "%d:%02d" % (t // 60, t % 60)


def panel(surf, rect, alpha=150):
    s = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    s.fill((20, 18, 30, alpha))
    surf.blit(s, (rect[0], rect[1]))


class Hud:
    def __init__(self, font, bank, minimap):
        self.font = font
        self.bank = bank
        self.minimap = minimap
        self.toasts = deque(maxlen=7)
        self.help_until = time.perf_counter() + 25.0
        self._panels = {}

    def add_toast(self, text, color, now):
        self.toasts.append((text, TOAST_COLORS.get(color, P["white"]), now))

    def _panel(self, rect, alpha=150):
        key = (rect[2], rect[3], alpha)
        s = self._panels.get(key)
        if s is None:
            s = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
            s.fill((20, 18, 30, alpha))
            self._panels[key] = s
        return s

    def draw(self, low, view, now, info):
        f = self.font
        snap = view.snap
        me = view.me
        flash = int(now * 4) % 2 == 0
        # ---- money ---------------------------------------------------------
        low.blit(self._panel((0, 0, 128, 28)), (2, 2))
        cash_col = P["danger"] if snap.cash < 0 else P["money"]
        cash = ("-$%s" % "{:,}".format(-snap.cash)) if snap.cash < 0 else "$%s" % "{:,}".format(snap.cash)
        f.draw(low, "CASH", 5, 5, P["white"])
        f.draw(low, cash, 26, 3, cash_col, scale=2)
        f.draw(low, "RENT $%d IN %s" % (C.RENT_AMOUNT, mmss(snap.rent)), 5, 16, P["white"])
        if snap.cash < 0:
            left = C.DEBT_GRACE - snap.debt
            f.draw(low, "IN THE RED! SEIZED IN %s" % mmss(left), 5, 23,
                   P["danger"] if flash else P["gold"])
        # ---- heat ----------------------------------------------------------
        bx, bw = W // 2 - 60, 120
        low.blit(self._panel((0, 0, bw + 44, 26)), (bx - 22, 2))
        f.draw(low, "HEAT", bx - 19, 5, P["white"])
        low.fill(P["ink"], (bx, 4, bw, 7))
        fillw = int(bw * snap.heat / 100.0)
        if fillw:
            col = P["gold"] if snap.heat < 50 else P["fire2"] if snap.heat < 90 else (
                P["danger"] if flash else P["fire2"])
            low.fill(col, (bx, 4, fillw, 7))
        for k in range(1, 4):
            low.fill(P["ink2"], (bx + k * bw // 4, 4, 1, 7))
        f.draw(low, "%d" % snap.heat, bx + bw + 3, 5, P["white"])
        if snap.witness in WITNESS_TEXT:
            text, col = WITNESS_TEXT[snap.witness]
        elif snap.cooling:
            text, col = "NOBODY SEES YOU - COOLING OFF", P["money"]
        elif snap.heat > 0:
            text, col = "OUT OF SIGHT... STAY HIDDEN", P["white"]
        else:
            text, col = "CLEAN. NOBODY'S LOOKING.", shade_c(P["white"])
        f.draw(low, text, W // 2, 13, col, align="center")
        if snap.cops:
            c = (255, 70, 70) if flash else (90, 130, 255)
            f.draw(low, "COPS: %d" % snap.cops, W // 2, 20, c, align="center")
        # ---- toasts (top-right) ---------------------------------------------
        y = 4
        for text, col, t0 in list(self.toasts):
            age = now - t0
            if age > C.TOAST_TIME:
                continue
            f.draw(low, text, W - 4, y, col, align="right")
            y += 8
        while self.toasts and now - self.toasts[0][2] > C.TOAST_TIME:
            self.toasts.popleft()
        if me is None:
            return
        state = me[2]
        # ---- hands + stamina (bottom-left) -------------------------------------
        low.blit(self._panel((0, 0, 176, 30)), (2, H - 32))
        f.draw(low, "HANDS", 5, H - 30, P["white"])
        hands = [h for h in (me[9], me[10]) if h != NO_PART]
        two = len(hands) == 1 and PART_DEFS[PART_IDS[hands[0]]][2] == 2
        for i in range(2):
            x = 5 + i * 14
            low.fill(P["ink"], (x, H - 23, 12, 12))
            pygame.draw.rect(low, P["metal_l"], (x, H - 23, 12, 12), 1)
        if two:
            pygame.draw.rect(low, P["gold"], (5, H - 23, 26, 12), 1)
            low.blit(self.bank.icons[hands[0]], (14, H - 21))
        else:
            for i, h in enumerate(hands):
                low.blit(self.bank.icons[h], (7 + i * 14, H - 21))
        names = [PART_DEFS[PART_IDS[h]][0].upper() for h in hands]
        f.draw(low, " + ".join(names) if names else "EMPTY", 35, H - 21, P["white"] if names else P["metal_l"])
        if hands:
            f.draw(low, "G: DROP", 35, H - 14, P["metal_l"])
        # stamina
        stam = me[11]
        exhausted = me[3] & PR.PF_EXHAUSTED
        low.fill(P["ink"], (35 + 45, H - 30, 60, 4))
        low.fill(P["danger"] if exhausted else P["money"], (35 + 45, H - 30, int(60 * stam / 100), 4))
        f.draw(low, "WINDED!" if exhausted else "STAMINA", 35 + 108, H - 31, P["danger"] if exhausted else P["white"])
        # ---- speedo (bottom-right, above minimap) ------------------------------
        car = view.my_car
        mm = self.minimap
        mx, my = W - mm.get_width() - 4, H - mm.get_height() - 4
        if car is not None and state in (S.DRIVER, S.PASSENGER):
            spd = math.hypot(car[9], car[10]) * 3.6
            low.blit(self._panel((0, 0, 58, 16)), (mx - 2, my - 19))
            f.draw(low, "%3d" % spd, mx + 1, my - 17, P["white"], scale=2)
            f.draw(low, "KM/H", mx + 30, my - 12, P["metal_l"])
        # ---- minimap -------------------------------------------------------------
        low.fill(P["ink"], (mx - 2, my - 2, mm.get_width() + 4, mm.get_height() + 4))
        low.blit(mm, (mx, my))
        k = 1.0 / (C.TILE_M * 2)
        for c in view.cars.values():
            px, py = mx + int(c[7] * k), my + int(c[8] * k)
            if c[1] == S.COP:
                low.fill((255, 60, 60) if flash else (80, 120, 255), (px - 1, py - 1, 3, 3))
            elif c[1] == S.PERSONAL:
                low.fill((150, 222, 64), (px - 1, py - 1, 2, 2))
            elif c[3] == S.DELIVERED or c[1] == S.TRAFFIC:
                continue          # the minimap shows things worth stealing, not rush hour
            elif c[4] & PR.CF_WANTED:
                low.fill(P["gold"] if flash else P["white"], (px - 1, py - 1, 2, 2))
            else:
                low.fill(P["white"], (px, py, 1, 1))
        for p in view.players.values():
            px, py = mx + int(p[4] * k), my + int(p[5] * k)
            low.fill(PLAYER_COLORS[p[1] % 4], (px - 1, py - 1, 3, 3) if p[0] == me[0] else (px, py, 2, 2))
        # ---- prompt + progress (bottom-centre) -----------------------------------
        prompt = snap.prompt
        if prompt:
            pw = PixelFont.width(prompt) + 10
            low.blit(self._panel((0, 0, pw, 18 if snap.hold > 0 else 11)), (W // 2 - pw // 2, H - 52))
            f.draw(low, prompt, W // 2, H - 49, P["white"], align="center")
            if snap.hold > 0:
                low.fill(P["ink"], (W // 2 - 50, H - 41, 100, 4))
                low.fill(P["gold"], (W // 2 - 50, H - 41, int(100 * snap.hold), 4))
        # ---- banners -------------------------------------------------------------
        if state == S.CUFFED:
            f.draw(low, "BUSTED", W // 2, H // 2 - 40, P["danger"] if flash else (130, 170, 255), scale=5, align="center")
            f.draw(low, "YOUR PARTS ARE ON THE PAVEMENT. YOUR PARTNER CAN GRAB THEM.", W // 2, H // 2 - 8,
                   P["white"], align="center")
        if snap.gameover > 0:
            low.blit(self._panel((0, 0, W, 60), 190), (0, H // 2 - 40))
            f.draw(low, "SHOP SEIZED", W // 2, H // 2 - 34, P["danger"], scale=5, align="center")
            f.draw(low, "TWO MINUTES IN THE RED. THE LANDLORD HAS YOUR KEYS.", W // 2, H // 2 - 2,
                   P["white"], align="center")
            f.draw(low, "NEW RUN IN %d... (YOUR RIDE KEEPS ITS MODS)" % (int(snap.gameover) + 1), W // 2, H // 2 + 8,
                   P["gold"], align="center")
        # ---- help ------------------------------------------------------------------
        if now < info.get("help_until", self.help_until) and not info.get("paused"):
            lines = ["WASD MOVE/DRIVE  SHIFT SPRINT  E INTERACT (HOLD)  G DROP  F EXIT CAR",
                     "SPACE HANDBRAKE  H HORN (CONFUSES COPS)  ESC MENU  F11 FULLSCREEN",
                     "STEAL CARS, PARK THEM IN THE SHOP, STRIP, SELL. PAY RENT. DON'T GET BUSTED."]
            low.blit(self._panel((0, 0, 330, 26), 170), (W // 2 - 165, 34))
            for i, l in enumerate(lines):
                f.draw(low, l, W // 2, 37 + i * 8, P["white"] if i < 2 else P["gold"], align="center")

    def draw_pause(self, low, info):
        f = self.font
        low.blit(self._panel((0, 0, W, H), 222), (0, 0))
        f.draw(low, "PAUSED", W // 2, 18, P["gold"], None, scale=4, align="center")
        f.draw(low, "(THE CITY KEEPS MOVING. SO DOES THE RENT.)", W // 2, 46, P["metal_l"], align="center")
        y = 62
        for line, col in info.get("lines", []):
            f.draw(low, line, W // 2, y, col, align="center")
            y += 9
        y += 6
        for l in ("WASD MOVE / DRIVE     SHIFT SPRINT     E INTERACT (HOLD FOR TIMED ACTIONS)",
                  "G DROP HELD PART     F EXIT CAR     SPACE HANDBRAKE     H HORN",
                  "F11 FULLSCREEN",
                  "",
                  "ESC: RESUME        Q: LEAVE TO MAIN MENU"):
            f.draw(low, l, W // 2, y, P["white"], align="center")
            y += 9


def shade_c(c):
    return tuple(int(v * 0.7) for v in c)


class Menu:
    """Main menu: Host / Join / Name / Quit. Text fields edited in place."""
    ITEMS = ["HOST GAME", "JOIN GAME", "NAME", "QUIT"]

    def __init__(self, font, name):
        self.font = font
        self.sel = 0
        self.name = name
        self.join_addr = "127.0.0.1"
        self.editing = None       # None | "name" | "join"
        self.error = ""
        self.error_t = 0.0

    def set_error(self, msg):
        self.error = msg
        self.error_t = time.perf_counter()

    def handle(self, ev):
        """Returns an action string or None."""
        if ev.type == pygame.KEYDOWN:
            if self.editing:
                target = self.editing
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.editing = None
                    if target == "join":
                        return "join"
                    return None
                if ev.key == pygame.K_ESCAPE:
                    self.editing = None
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    if target == "name":
                        self.name = self.name[:-1]
                    else:
                        self.join_addr = self.join_addr[:-1]
                    return None
                ch = ev.unicode
                if ch and 32 <= ord(ch) < 127:
                    if target == "name" and len(self.name) < 12 and (ch.isalnum() or ch in "-_ "):
                        self.name += ch.upper()
                    elif target == "join" and len(self.join_addr) < 60 and (ch.isalnum() or ch in ".:-"):
                        self.join_addr += ch
                return None
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.ITEMS)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.ITEMS)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
                item = self.ITEMS[self.sel]
                if item == "HOST GAME":
                    return "host"
                if item == "JOIN GAME":
                    self.editing = "join"
                elif item == "NAME":
                    self.editing = "name"
                elif item == "QUIT":
                    return "quit"
            elif ev.key == pygame.K_ESCAPE:
                return "quit"
        return None

    def draw(self, low, now):
        f = self.font
        low.blit(_shade_overlay(), (0, 0))
        wob = int(math.sin(now * 2) * 2)
        f.draw(low, "CHOPPED", W // 2 + 3, 26 + wob + 3, P["ink"], None, scale=8, align="center")
        f.draw(low, "CHOPPED", W // 2 + 1, 26 + wob + 1, P["red_d"], None, scale=8, align="center")
        f.draw(low, "CHOPPED", W // 2, 26 + wob, P["gold"], None, scale=8, align="center")
        f.draw(low, "A CO-OP CAR THEFT CHOP-SHOP DISASTER FOR 1-4 CROOKS", W // 2, 80, P["white"], align="center")
        y = 104
        for i, item in enumerate(self.ITEMS):
            selected = i == self.sel
            label = item
            if item == "NAME":
                cur = "_" if (self.editing == "name" and int(now * 3) % 2) else ""
                label = "NAME: %s%s" % (self.name, cur)
            if item == "JOIN GAME" and self.editing == "join":
                cur = "_" if int(now * 3) % 2 else ""
                label = "JOIN IP[:PORT]: %s%s" % (self.join_addr, cur)
            col = P["gold"] if selected else P["white"]
            if selected:
                f.draw(low, ">", W // 2 - PixelFont.width(label) - 12, y, col, scale=2)
            f.draw(low, label, W // 2, y, col, scale=2, align="center")
            y += 18
        if self.editing == "join":
            f.draw(low, "TYPE THE HOST'S IP (DEFAULT PORT %d), ENTER TO CONNECT, ESC TO CANCEL" % C.DEFAULT_PORT,
                   W // 2, y + 4, P["metal_l"], align="center")
        elif self.editing == "name":
            f.draw(low, "TYPE YOUR NAME, ENTER TO SAVE", W // 2, y + 4, P["metal_l"], align="center")
        else:
            f.draw(low, "W/S OR ARROWS TO PICK, ENTER TO GO", W // 2, y + 4, P["metal_l"], align="center")
        if self.error and now - self.error_t < 8:
            f.draw(low, self.error, W // 2, H - 22, P["danger"], align="center")
        f.draw(low, "HOST: UDP PORT %d. UPNP IS TRIED AUTOMATICALLY." % C.DEFAULT_PORT, W // 2, H - 10,
               P["metal_l"], align="center")


_overlay = None


def _shade_overlay():
    global _overlay
    if _overlay is None:
        _overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        _overlay.fill((16, 14, 24, 150))
    return _overlay

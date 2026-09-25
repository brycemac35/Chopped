"""
ui.py -- the main menu. (The in-game HUD is the Doom-style status bar in
doomhud.py.) Everything is drawn on the 480x270 canvas with the pixel font.
"""

import math
import time

import pygame

from . import config as C
from .art import P, PixelFont

W, H = C.LOW_W, C.LOW_H


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
        f.draw(low, "V%d.%d.%d" % C.RELEASE, W - 4, H - 10, P["metal_l"], align="right")
        f.draw(low, "HOST: UDP PORT %d. UPNP IS TRIED AUTOMATICALLY." % C.DEFAULT_PORT, W // 2, H - 10,
               P["metal_l"], align="center")


_overlay = None


def _shade_overlay():
    global _overlay
    if _overlay is None:
        _overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        _overlay.fill((16, 14, 24, 150))
    return _overlay

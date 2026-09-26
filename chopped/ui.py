"""
ui.py -- the main menu. (The in-game HUD is the Doom-style status bar in
doomhud.py.) Everything is drawn on the 480x270 canvas with the pixel font.
"""

import math
import time

import pygame

from . import config as C
from . import savefile as SF
from .art import P, PixelFont

W, H = C.LOW_W, C.LOW_H


class Menu:
    """Main menu: Host / Join / Name / Quit. Text fields edited in place."""
    ITEMS = ["HOST GAME", "SAVE SLOT", "JOIN GAME", "NAME", "QUIT"]

    def __init__(self, font, name, save_file=None):
        self.font = font
        self.sel = 0
        self.name = name
        self.join_addr = "127.0.0.1"
        self.editing = None       # None | "name" | "join"
        self.error = ""
        self.error_t = 0.0
        # (v0.12.1) save slots: 1..SAVE_SLOTS, or 0 = don't save at all. --save FILE on
        # the command line still wins (it's shown as the slot, and the row's locked).
        self.save_file = save_file
        self.slot = 1
        self.wipe_armed = False
        self.refresh_slots()

    def refresh_slots(self):
        """Re-read every slot's headline (after a game, so DAY/CASH are current)."""
        self.slots = {n: SF.peek(SF.slot_path(n)) for n in range(1, C.SAVE_SLOTS + 1)}
        self.file_info = SF.peek(self.save_file) if self.save_file else None

    def save_path(self):
        """The file HOST GAME should load from and autosave to, or None."""
        if self.save_file:
            return self.save_file
        return SF.slot_path(self.slot) if self.slot else None

    def slot_info(self):
        return self.file_info if self.save_file else self.slots.get(self.slot)

    def _slot_label(self):
        if self.save_file:
            return "SAVE FILE: %s" % self.save_file.replace("\\", "/").rsplit("/", 1)[-1].upper()[:24]
        if not self.slot:
            return "SAVE SLOT: OFF (NOTHING IS SAVED)"
        info = self.slots.get(self.slot)
        if info is None:
            return "SAVE SLOT %d: EMPTY" % self.slot
        return "SAVE SLOT %d: DAY %d  $%d  ACT %d" % (self.slot, info["day"], info["cash"], info["act"])

    def _cycle_slot(self, d):
        if self.save_file:
            return
        self.slot = (self.slot + d) % (C.SAVE_SLOTS + 1)
        self.wipe_armed = False

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
            item = self.ITEMS[self.sel]
            if ev.key not in (pygame.K_DELETE, pygame.K_x):
                self.wipe_armed = False          # (anything else means "no, keep it")
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.ITEMS)
                self.wipe_armed = False
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.ITEMS)
                self.wipe_armed = False
            elif item == "SAVE SLOT" and ev.key in (pygame.K_LEFT, pygame.K_a):
                self._cycle_slot(-1)
            elif item == "SAVE SLOT" and ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._cycle_slot(1)
            elif item == "SAVE SLOT" and ev.key in (pygame.K_DELETE, pygame.K_x) and not self.save_file \
                    and self.slots.get(self.slot):
                if self.wipe_armed:              # second press: it's gone
                    SF.wipe(SF.slot_path(self.slot))
                    self.wipe_armed = False
                    self.refresh_slots()
                else:
                    self.wipe_armed = True
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
                if item == "HOST GAME":
                    return "host"
                if item == "SAVE SLOT":
                    self._cycle_slot(1)
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
            if item == "HOST GAME":
                label = "CONTINUE THE RUN" if self.slot_info() else "HOST NEW GAME"
            if item == "SAVE SLOT":
                label = self._slot_label()
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
        elif self.ITEMS[self.sel] in ("SAVE SLOT", "HOST GAME"):
            info = self.slot_info()
            if self.save_file:
                hint = "--SAVE ON THE COMMAND LINE PICKED THIS FILE. AUTOSAVES EVERY %d S." % C.AUTOSAVE_INTERVAL
            elif self.wipe_armed:
                hint = "PRESS DEL AGAIN TO WIPE SLOT %d FOR GOOD. ANY OTHER KEY: KEEP IT." % self.slot
            elif not self.slot:
                hint = "A/D: PICK A SLOT. OFF = A ONE-NIGHT STAND, NOTHING IS WRITTEN."
            elif info is None:
                hint = "A/D: PICK A SLOT. HOST TO START A NEW CREW HERE; AUTOSAVES EVERY %d S, F5 SAVES NOW." % \
                    C.AUTOSAVE_INTERVAL
            else:
                crew = ", ".join(info["crew"][:4]) or "NOBODY YET"
                hint = "REP %d  CREW: %s  -  A/D: OTHER SLOTS, DEL: WIPE" % (info["rep"], crew)
            f.draw(low, hint[:100], W // 2, y + 4, P["metal_l"], align="center")
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

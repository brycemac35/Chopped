"""
ui.py -- the main menu. (The in-game HUD is the Doom-style status bar in
doomhud.py.) Everything is drawn on the 480x270 canvas with the pixel font.
"""

import math
import os
import time

import pygame

from . import config as C
from . import savefile as SF
from . import settings as SET
from .story import CHAPTERS as STORY_CHAPTERS
from .art import P, PixelFont

W, H = C.LOW_W, C.LOW_H

# (v0.16) choosable characters. characters.py is the source of truth; this fallback keeps the
# menu working if it's missing (and pins the roster Bryce approved).
_FALLBACK_ROSTER = (
    {"id": 0, "name": "DASH", "title": "ATHLETE", "perk": "+50% STAMINA, RECOVERS FASTER",
     "blurb": "BORN TO RUN. ESPECIALLY FROM COPS."},
    {"id": 1, "name": "SPANNER", "title": "GREASE MONKEY", "perk": "STRIPS PARTS 40% FASTER",
     "blurb": "HAS A SPANNER FOR EVERY OCCASION."},
    {"id": 2, "name": "SLIM", "title": "LIGHT FINGERS", "perk": "BREAKS IN + HOTWIRES 2X FASTER",
     "blurb": "LOCKS ARE JUST SUGGESTIONS."},
    {"id": 3, "name": "SMOOTH", "title": "SMOOTH TALKER", "perk": "+15% ON SALES, BAIL + PAPERS HALF PRICE",
     "blurb": "COULD SELL YOU YOUR OWN CAR."},
)


def roster():
    """The character list: characters.CHARACTERS if it exists, else the fallback."""
    try:
        from . import characters as CH
        r = tuple(getattr(CH, "CHARACTERS", ()))
        if r:
            return r
    except Exception:
        pass
    return _FALLBACK_ROSTER


def char_info(idx):
    r = roster()
    return r[int(idx) % len(r)] if isinstance(idx, int) or str(idx).isdigit() else r[0]


_portraits = {}


def char_portrait(idx, size=48):
    """A portrait surface for the character (fpart.char_portrait), or a plain coloured block
    with the initial if the graphics half hasn't landed."""
    key = (idx, size)
    s = _portraits.get(key)
    if s is None:
        try:
            from . import fpart as FA
            s = FA.char_portrait(idx, size=size)
        except Exception:
            s = None
        if s is None:
            s = pygame.Surface((size, size))
            s.fill((60, 56, 80))
            PixelFont().draw(s, char_info(idx)["name"][:1], size // 2, size // 2 - 5, P["gold"], scale=3,
                             align="center")
        _portraits[key] = s
    return s


# ---------------------------------------------------------------- (v0.19) shared bits
def clipboard_text():
    """Whatever text is on the clipboard ('' if none, or if pygame.scrap can't start, as on the
    headless test driver). Tests replace this function."""
    try:
        import pygame.scrap as scrap
        try:
            t = scrap.get_text()                 # (pygame-ce 2.2+: no init needed)
        except pygame.error:
            scrap.init()                         # older pygame wants it first
            t = scrap.get_text()
        return t if isinstance(t, str) else ""
    except Exception:
        return ""


def slot_summary(info):
    return "DAY %d, $%d, ACT %d" % (info["day"], info["cash"], info["act"])


def validate_addr(text):
    """'' if the JOIN text is usable, else the error to show. Empty means this machine."""
    t = text.strip()
    if t.count(":") > 1:
        return "USE HOST OR HOST:PORT"
    if ":" in t:
        host, port = t.split(":")
        if not host:
            return "MISSING HOST BEFORE THE :"
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            return "PORT MUST BE A NUMBER FROM 1 TO 65535"
    return ""


class ConfirmDialog:
    """A small modal 'are you sure': two lines and two buttons. Keys: Enter = yes, Esc = no."""
    BOX = pygame.Rect(W // 2 - 190, H // 2 - 40, 380, 80)
    YES = pygame.Rect(W // 2 - 160, H // 2 + 12, 150, 18)
    NO = pygame.Rect(W // 2 + 10, H // 2 + 12, 150, 18)

    def __init__(self, title, sub, yes="DELETE", no="KEEP"):
        self.title, self.sub, self.yes, self.no = title, sub, yes, no

    def key(self, ev):
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return "yes"
        if ev.key == pygame.K_ESCAPE:
            return "no"
        return None

    def click(self, pos):
        if self.YES.collidepoint(pos):
            return "yes"
        if self.NO.collidepoint(pos) or not self.BOX.collidepoint(pos):
            return "no"
        return None

    def draw(self, font, low, mouse=None):
        low.blit(_shade_overlay(), (0, 0))
        b = self.BOX
        low.fill((16, 14, 24), b)
        low.fill(P["danger"], (b.x, b.y, b.w, 1))
        low.fill(P["danger"], (b.x, b.bottom - 1, b.w, 1))
        font.draw(low, self.title, b.centerx, b.y + 10, P["danger"], scale=2, align="center")
        font.draw(low, self.sub, b.centerx, b.y + 28, P["white"], align="center")
        for r, label, key, col in ((self.YES, self.yes, "ENTER", P["danger"]), (self.NO, self.no, "ESC", P["white"])):
            hot = mouse is not None and r.collidepoint(mouse)
            low.fill((70, 60, 100) if hot else (40, 36, 58), r)
            low.fill(col, (r.x, r.y, r.w, 1))
            font.draw(low, "%s (%s)" % (label, key), r.centerx, r.y + 6, col if hot else P["white"], align="center")


class Menu:
    """Main menu: Host / Join / Name / Quit. Text fields edited in place, in fixed boxes."""
    ITEMS = ["HOST GAME", "SAVE SLOT", "JOIN GAME", "NAME", "CHARACTER", "SETTINGS", "QUIT"]
    # the character panel under the rows (canvas px). Rows end near y=212 and the hint line near
    # y=220, so the panel starts at 232 and ends well above the footer lines (H-22).
    PANEL = pygame.Rect(W // 2 - 170, 234, 340, 64)
    ROW_Y0, ROW_H = 102, 16          # (7 rows at 16 px: the hint lands at 218, clear of the panel at 234)
    # (v0.19) NAME and JOIN are fixed boxes: the label and the box never move whatever you type
    # (the old centred text shifted the whole line one character per keypress).
    FIELD_LABEL_X = W // 2 - 134
    FIELD_BOX_X = FIELD_LABEL_X + 48
    FIELD_BOX_W = 204                # fits ~22 glyphs at scale 2: "255.255.255.255:65535"
    NAME_MAX, ADDR_MAX = 12, 60
    SERVER_ROW_H = 11                # the stored-server pick list under the JOIN box
    DEL_BTN_W = 64                   # "[DEL] DELETE" on the save slot row
    BS_DELAY, BS_RATE = 0.4, 0.04    # hold Backspace: wait, then one char every 40 ms

    def __init__(self, font, name, save_file=None, char=0, servers=None):
        self.font = font
        self.char = int(char or 0) % len(roster())
        self.sel = 0
        self.name = name
        self.servers = servers if servers is not None else []     # settings["servers"], shared (newest first)
        self.join_addr = self.servers[0]["addr"] if self.servers else "127.0.0.1"
        self.editing = None       # None | "name" | "join"
        self.replace_next = False  # JOIN text is 'selected': the next key replaces it
        self.pick = -1            # highlighted stored server
        self.del_armed = -1       # stored server that one more Del removes
        self.bs_t = 0.0
        self.mouse = None         # canvas mouse position, set by the game each frame (hover only)
        self.error = ""
        self.error_t = 0.0
        # (v0.12.1) save slots: 1..SAVE_SLOTS, or 0 = don't save at all. --save FILE on
        # the command line still wins (it's shown as the slot, and the row's locked).
        self.save_file = save_file
        self.slot = 1
        self.confirm = None       # ConfirmDialog for DELETE SLOT, when open
        self.confirm_slot = 0
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

    def _cycle_char(self, d):
        self.char = (self.char + d) % len(roster())

    # -- geometry (pure: the same before and after typing)
    def row_y(self, i):
        return self.ROW_Y0 + i * self.ROW_H

    def field_rect(self, item):
        y = self.row_y(self.ITEMS.index(item))
        return pygame.Rect(self.FIELD_BOX_X, y - 2, self.FIELD_BOX_W, 14)

    def del_rect(self):
        """The '[DEL] DELETE' button on the save slot row, or None when there's nothing to delete."""
        if self.save_file or not self.slots.get(self.slot):
            return None
        return pygame.Rect(W // 2 + 158, self.row_y(self.ITEMS.index("SAVE SLOT")) - 1, self.DEL_BTN_W, 12)

    def list_rect(self):
        b = self.field_rect("JOIN GAME")
        return pygame.Rect(self.FIELD_LABEL_X, b.bottom + 2, b.right - self.FIELD_LABEL_X,
                           10 + len(self.servers) * self.SERVER_ROW_H + 2)

    def server_rect(self, k):
        lr = self.list_rect()
        return pygame.Rect(lr.x + 1, lr.y + 11 + k * self.SERVER_ROW_H, lr.w - 2, self.SERVER_ROW_H)

    def server_x_rect(self, k):
        r = self.server_rect(k)
        return pygame.Rect(r.right - 14, r.y, 14, r.h)

    def layout(self):
        """Everything that must not move while typing, for the tests."""
        return {"fields": {i: self.field_rect(i) for i in ("NAME", "JOIN GAME")},
                "rows": [self.row_y(i) for i in range(len(self.ITEMS))], "list": self.list_rect()}

    # -- editing
    def _start_edit(self, which):
        self.editing = which
        self.sel = self.ITEMS.index("JOIN GAME" if which == "join" else "NAME")
        self.del_armed = -1
        self.bs_t = 0.0
        if which == "join":
            self.replace_next = True
            self.pick = next((k for k, e in enumerate(self.servers)
                              if e["addr"].lower() == self.join_addr.lower()), -1)

    def _clean(self, which, text):
        if which == "name":
            return "".join(c.upper() for c in text if c.isalnum() or c in "-_ ")
        return "".join(c for c in text if c.isalnum() or c in ".:-")

    def _add_text(self, text):
        which = self.editing
        text = self._clean(which, text)
        if not text:
            return
        if which == "name":
            self.name = (self.name + text)[:self.NAME_MAX]
        else:
            base = "" if self.replace_next else self.join_addr
            self.join_addr = (base + text)[:self.ADDR_MAX]
            self.replace_next = False
            self.pick = -1
            self.del_armed = -1

    def _backspace(self, everything=False):
        if self.editing == "name":
            self.name = "" if everything else self.name[:-1]
        else:
            self.join_addr = "" if (everything or self.replace_next) else self.join_addr[:-1]
            self.replace_next = False
            self.pick = -1
            self.del_armed = -1

    def _pick_server(self, d):
        n = len(self.servers)
        if not n:
            return
        self.pick = (self.pick + d) % n if self.pick >= 0 else (0 if d > 0 else n - 1)
        self.join_addr = self.servers[self.pick]["addr"]
        self.replace_next = True
        self.del_armed = -1

    def _delete_server(self, k):
        """Del twice (or click [X] twice) on the same stored server removes it. True if it did."""
        if not 0 <= k < len(self.servers):
            return False
        if self.del_armed != k:
            self.del_armed = k
            return False
        del self.servers[k]
        self.del_armed = -1
        self.pick = -1
        return True

    def _try_join(self):
        err = validate_addr(self.join_addr)
        if err:
            self.set_error(err)
            return None
        self.editing = None
        self.replace_next = False
        return "join"

    def tick(self, dt, keys):
        """Held Backspace keeps deleting. `keys` is pygame.key.get_pressed()."""
        if self.editing and keys[pygame.K_BACKSPACE]:
            self.bs_t += dt
            while self.bs_t >= self.BS_DELAY:
                self.bs_t -= self.BS_RATE
                self._backspace()
        else:
            self.bs_t = 0.0

    def click(self, pos):
        """Mouse. Returns an action string or None."""
        if self.confirm is not None:
            return self._answer(self.confirm.click(pos))
        if self.editing == "join" and self.servers and self.list_rect().collidepoint(pos):
            for k in range(len(self.servers)):
                if self.server_x_rect(k).collidepoint(pos):
                    self.pick = k
                    return "save" if self._delete_server(k) else None
                if self.server_rect(k).collidepoint(pos):
                    self.join_addr = self.servers[k]["addr"]
                    return self._try_join()
            return None
        for item, which in (("JOIN GAME", "join"), ("NAME", "name")):
            if self.field_rect(item).collidepoint(pos):
                self._start_edit(which)
                return None
        if self.editing:
            return None
        dr = self.del_rect()
        if dr is not None and dr.collidepoint(pos):
            self.sel = self.ITEMS.index("SAVE SLOT")
            self._ask_delete()
            return None
        r = self.PANEL
        if r.collidepoint(pos):
            self.sel = self.ITEMS.index("CHARACTER")
            self._cycle_char(-1 if pos[0] < r.centerx else 1)
        return None

    def _ask_delete(self):
        info = self.slots.get(self.slot)
        if self.save_file or not info:
            return
        self.confirm_slot = self.slot
        self.confirm = ConfirmDialog("DELETE SLOT %d? %s." % (self.slot, slot_summary(info)),
                                     "THE WHOLE SAVE GOES FOR GOOD. THERE IS NO UNDO.")

    def _answer(self, ans):
        if ans == "yes":
            SF.wipe(SF.slot_path(self.confirm_slot))
            self.refresh_slots()
        if ans:
            self.confirm = None
        return None

    def set_error(self, msg):
        self.error = msg
        self.error_t = time.perf_counter()

    def handle(self, ev):
        """Returns an action string or None."""
        if ev.type == pygame.KEYDOWN:
            if self.confirm is not None:
                return self._answer(self.confirm.key(ev))
            if self.editing:
                target = self.editing
                if ev.key != pygame.K_DELETE:
                    self.del_armed = -1
                if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if target == "join":
                        return self._try_join()
                    self.editing = None
                    return "save"            # (the name is remembered)
                if ev.key == pygame.K_ESCAPE:
                    self.editing = None
                    self.replace_next = False
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    self._backspace(bool(ev.mod & pygame.KMOD_CTRL))
                    return None
                if (ev.key == pygame.K_v and ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)) or \
                        (ev.key == pygame.K_INSERT and ev.mod & pygame.KMOD_SHIFT):
                    txt = clipboard_text().strip().splitlines()
                    self._add_text(txt[0].strip() if txt else "")
                    return None
                if target == "join":
                    if ev.key == pygame.K_UP:
                        self._pick_server(-1)
                        return None
                    if ev.key == pygame.K_DOWN:
                        self._pick_server(1)
                        return None
                    if ev.key == pygame.K_DELETE:
                        return "save" if self._delete_server(self.pick) else None
                ch = ev.unicode
                if ch and 32 <= ord(ch) < 127 and not ev.mod & pygame.KMOD_CTRL:
                    self._add_text(ch)
                return None
            item = self.ITEMS[self.sel]
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.ITEMS)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.ITEMS)
            elif item == "CHARACTER" and ev.key in (pygame.K_LEFT, pygame.K_a):
                self._cycle_char(-1)
            elif item == "CHARACTER" and ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._cycle_char(1)
            elif item == "SAVE SLOT" and ev.key in (pygame.K_LEFT, pygame.K_a):
                self._cycle_slot(-1)
            elif item == "SAVE SLOT" and ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._cycle_slot(1)
            elif item in ("SAVE SLOT", "HOST GAME") and ev.key in (pygame.K_DELETE, pygame.K_x):
                self._ask_delete()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_e):
                if item == "HOST GAME":
                    return "host"
                if item == "SAVE SLOT":
                    self._cycle_slot(1)
                if item == "JOIN GAME":
                    self._start_edit("join")
                elif item == "NAME":
                    self._start_edit("name")
                elif item == "CHARACTER":
                    self._cycle_char(1)
                elif item == "SETTINGS":
                    return "settings"
                elif item == "QUIT":
                    return "quit"
            # (Esc does nothing up here: quitting is the QUIT row or the window's X, never a stray key)
        return None

    # -- drawing
    @staticmethod
    def _fit(text, max_w, scale=2):
        """The tail of `text` that fits max_w px (long input scrolls instead of growing)."""
        while text and PixelFont.width(text) * scale > max_w:
            text = text[1:]
        return text

    def _draw_field(self, low, item, now, selected):
        f = self.font
        i = self.ITEMS.index(item)
        y = self.row_y(i)
        box = self.field_rect(item)
        which = "join" if item == "JOIN GAME" else "name"
        live = self.editing == which
        col = P["gold"] if selected else P["white"]
        if selected:
            f.draw(low, ">", self.FIELD_LABEL_X - 14, y, col, scale=2)
        f.draw(low, "JOIN:" if which == "join" else "NAME:", self.FIELD_LABEL_X, y, col, scale=2)
        low.fill((12, 10, 20) if live else (28, 26, 42), box)
        edge = P["gold"] if live else (150, 130, 70) if selected else (90, 84, 110)
        for r in ((box.x, box.y, box.w, 1), (box.x, box.bottom - 1, box.w, 1),
                  (box.x, box.y, 1, box.h), (box.right - 1, box.y, 1, box.h)):
            low.fill(edge, r)
        text = self.join_addr if which == "join" else self.name
        inner = box.w - 8 - (8 if live else 0)
        shown = self._fit(text, inner)
        tx = box.x + 4
        if shown != text:
            f.draw(low, "<", tx, y, (150, 130, 70), scale=2)       # (scrolled: there's more to the left)
            shown = self._fit(text, inner - 12)
            tx += 12
        tw = PixelFont.width(shown) * 2 if shown else 0
        if live and which == "join" and self.replace_next and shown:
            low.fill((70, 60, 100), (tx - 1, box.y + 2, tw + 2, box.h - 4))
        low.set_clip(box.inflate(-2, -2))
        f.draw(low, shown, tx, y, P["white"] if live or selected else (200, 200, 196), scale=2)
        if live and int(now * 3) % 2:
            low.fill(P["gold"], (tx + tw + 1, y, 6, 10))
        low.set_clip(None)

    def _draw_server_list(self, low, now):
        f = self.font
        lr = self.list_rect()
        low.fill((16, 14, 24), lr)
        low.fill((90, 84, 110), (lr.x, lr.y, lr.w, 1))
        low.fill((90, 84, 110), (lr.x, lr.bottom - 1, lr.w, 1))
        f.draw(low, "RECENT HOSTS  (UP/DOWN PICK, DEL REMOVES)", lr.x + 4, lr.y + 3, P["metal_l"])
        for k, e in enumerate(self.servers):
            r = self.server_rect(k)
            hot = k == self.pick
            armed = k == self.del_armed
            if hot:
                low.fill((48, 42, 70), r)
            col = P["danger"] if armed else P["gold"] if hot else P["white"]
            f.draw(low, ">" if hot else " ", r.x + 2, r.y + 3, col)
            f.draw(low, ("DEL AGAIN TO REMOVE " + e["addr"]) if armed else e["addr"], r.x + 10, r.y + 3, col)
            if e.get("name") and not armed:
                f.draw(low, e["name"], r.right - 18, r.y + 3, P["metal_l"], align="right")
            f.draw(low, "X", self.server_x_rect(k).centerx, r.y + 3, P["danger"] if armed else (120, 110, 140),
                   align="center")

    def draw(self, low, now):
        f = self.font
        low.blit(_shade_overlay(), (0, 0))
        wob = int(math.sin(now * 2) * 2)
        f.draw(low, "CHOPPED", W // 2 + 3, 26 + wob + 3, P["ink"], None, scale=8, align="center")
        f.draw(low, "CHOPPED", W // 2 + 1, 26 + wob + 1, P["red_d"], None, scale=8, align="center")
        f.draw(low, "CHOPPED", W // 2, 26 + wob, P["gold"], None, scale=8, align="center")
        f.draw(low, "A CO-OP CAR THEFT CHOP-SHOP DISASTER FOR 1-4 CROOKS", W // 2, 80, P["white"], align="center")
        pick_list = self.editing == "join" and bool(self.servers)
        for i, item in enumerate(self.ITEMS):
            selected = i == self.sel
            y = self.row_y(i)
            if pick_list and i > self.ITEMS.index("JOIN GAME"):
                break                      # (the recent-hosts list takes the space under the JOIN box)
            if item in ("NAME", "JOIN GAME"):
                self._draw_field(low, item, now, selected)
                continue
            label = item
            if item == "HOST GAME":
                label = "CONTINUE THE RUN" if self.slot_info() else "HOST NEW GAME"
            if item == "SAVE SLOT":
                label = self._slot_label()
            if item == "CHARACTER":
                label = "CHARACTER: < %s >" % char_info(self.char)["name"]
            col = P["gold"] if selected else P["white"]
            if selected:
                f.draw(low, ">", W // 2 - PixelFont.width(label) - 12, y, col, scale=2)
            f.draw(low, label, W // 2, y, col, scale=2, align="center")
            if item == "SAVE SLOT" and self.del_rect() is not None:
                r = self.del_rect()
                low.fill((90, 30, 34) if selected else (52, 30, 40), r)
                f.draw(low, "[DEL] DELETE", r.centerx, r.y + 4, P["white"] if selected else P["metal_l"],
                       align="center")
        y = self.row_y(len(self.ITEMS))
        joining = self.editing == "join"
        hy = y + 4
        if joining and self.servers:
            self._draw_server_list(low, now)
            hy = self.list_rect().bottom + 6
        else:
            self._draw_char_panel(low)
        if joining:
            f.draw(low, "TYPE THE HOST'S IP (DEFAULT PORT %d). CTRL+V PASTES. ENTER: CONNECT, ESC: CANCEL" % C.DEFAULT_PORT,
                   W // 2, hy, P["metal_l"], align="center")
        elif self.editing == "name":
            f.draw(low, "TYPE YOUR NAME. CTRL+V PASTES. ENTER TO SAVE", W // 2, hy, P["metal_l"], align="center")
        elif self.ITEMS[self.sel] == "SETTINGS":
            f.draw(low, "FOV, RENDER SCALE, WORLD DETAIL, VOLUMES, SAVE FILES. SAVED FOR NEXT TIME.", W // 2, hy,
                   P["metal_l"], align="center")
        elif self.ITEMS[self.sel] == "JOIN GAME":
            f.draw(low, "ENTER: TYPE AN IP OR PICK A RECENT HOST. HOSTS YOU'VE JOINED ARE REMEMBERED.", W // 2, hy,
                   P["metal_l"], align="center")
        elif self.ITEMS[self.sel] == "CHARACTER":
            f.draw(low, "A/D OR CLICK THE ARROWS: PICK WHO YOU ARE. THE PERK IS YOURS ALL RUN.", W // 2, hy,
                   P["metal_l"], align="center")
        elif self.ITEMS[self.sel] in ("SAVE SLOT", "HOST GAME"):
            info = self.slot_info()
            if self.save_file:
                hint = "--SAVE ON THE COMMAND LINE PICKED THIS FILE. AUTOSAVES EVERY %d S." % C.AUTOSAVE_INTERVAL
            elif not self.slot:
                hint = "A/D: PICK A SLOT. OFF = A ONE-NIGHT STAND, NOTHING IS WRITTEN."
            elif info is None:
                hint = "A/D: PICK A SLOT. HOST TO START A NEW CREW HERE; AUTOSAVES EVERY %d S, F5 SAVES NOW." % \
                    C.AUTOSAVE_INTERVAL
            else:
                crew = ", ".join(info["crew"][:4]) or "NOBODY YET"
                n = len(STORY_CHAPTERS)
                ch = info.get("story_ch", 0)
                story = ("STORY %d/%d" % (ch + 1, n)) if ch < n else "STORY DONE"
                hint = "%s  REP %d  CREW: %s  -  A/D: OTHER SLOTS, DEL: DELETE" % (story, info["rep"], crew)
            f.draw(low, hint[:100], W // 2, hy, P["metal_l"], align="center")
        else:
            f.draw(low, "W/S OR ARROWS TO PICK, ENTER TO GO", W // 2, hy, P["metal_l"], align="center")
        if self.error and now - self.error_t < 8:
            f.draw(low, self.error, W // 2, H - 22, P["danger"], align="center")
        f.draw(low, "V%d.%d.%d" % C.RELEASE, W - 4, H - 10, P["metal_l"], align="right")
        f.draw(low, "HOST: UDP PORT %d. UPNP IS TRIED AUTOMATICALLY." % C.DEFAULT_PORT, W // 2, H - 10,
               P["metal_l"], align="center")
        if self.confirm is not None:
            self.confirm.draw(f, low, self.mouse)

    def _draw_char_panel(self, low):
        """Portrait, NAME, TITLE and the perk, with arrows either side (A/D or click)."""
        f = self.font
        r = self.PANEL
        ch = char_info(self.char)
        hot = self.ITEMS[self.sel] == "CHARACTER"
        low.blit(_shade_overlay(), r.topleft, pygame.Rect(0, 0, r.w, r.h))
        low.fill(P["gold"] if hot else (90, 84, 110), (r.x, r.y, r.w, 1))
        low.fill(P["gold"] if hot else (90, 84, 110), (r.x, r.bottom - 1, r.w, 1))
        for sx, glyph in ((r.x + 8, "<"), (r.right - 8, ">")):
            f.draw(low, glyph, sx, r.centery - 7, P["gold"] if hot else P["metal_l"], scale=3,
                   align="center")
        px, py = r.x + 26, r.y + 8
        low.fill(P["ink"], (px - 1, py - 1, 50, 50))
        low.blit(char_portrait(self.char, 48), (px, py))
        tx = px + 62
        f.draw(low, ch["name"], tx, r.y + 8, P["gold"], scale=2)
        f.draw(low, ch["title"], tx, r.y + 26, P["white"])
        f.draw(low, ch["perk"], tx, r.y + 38, P["money"])
        f.draw(low, "%d/%d" % (self.char + 1, len(roster())), r.right - 18, r.bottom - 10, P["metal_l"],
               align="right")


_overlay = None


def _shade_overlay():
    global _overlay
    if _overlay is None:
        _overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        _overlay.fill((16, 14, 24, 150))
    return _overlay


class SettingsPanel:
    """(v0.17) the SETTINGS screen, shared by the main menu and the pause menu.

    `data` is the live settings dict (settings.py); every change is written into it and reported
    through on_change(key) so the game can apply it at once. Saving is the caller's job, on leaving.
    Keys: W/S pick a row, A/D adjust (hold to repeat), Esc/Enter back. Mouse: click or drag a slider.
    (v0.19) WORLD DETAIL buttons, and a SAVE FILES section: the three slots, each with a delete
    button (asks first). `locked_path` is the save the running game is hosting: it can't be deleted."""
    # (key, label, lo, hi, step, kind) -- kind picks how the value reads
    ROWS = (
        ("fov", "FOV", C.FOV_MIN, C.FOV_MAX, 5, "deg"),
        ("render_scale", "RENDER SCALE", C.RENDER_SCALE_MIN, C.RENDER_SCALE_MAX, 1, "scale"),
        # (graphics agent's range; fallbacks until config has it) drawn at most at the render scale
        ("world_scale", "WORLD DETAIL", getattr(C, "WORLD_SCALE_MIN", 1), getattr(C, "WORLD_SCALE_MAX", 3), 1, "wscale"),
        ("master", "MASTER", 0, 100, 5, "pct"),
        ("music", "MUSIC", 0, 100, 5, "pct"),
        ("sfx", "SFX", 0, 100, 5, "pct"),
        ("engine", "ENGINES", 0, 100, 5, "pct"),
        # (v0.19) mouse look (last, so the rows above keep their indices): stored as an int percent (100 = 1.00X), shown as a multiplier; INVERT Y is a
        # two-button OFF/ON (lo 0, hi 1) that reuses the 1X/2X/3X button row
        ("mouse_sens", "MOUSE SENSITIVITY", C.MOUSE_SENS_MIN, C.MOUSE_SENS_MAX, C.MOUSE_SENS_STEP, "mult"),
        ("invert_y", "INVERT Y", 0, 1, 1, "toggle"),
        # (v0.20) 3D (gl3d) or CLASSIC (the raycaster), last for the same reason. Stored as a word in
        # settings.json; the two buttons index settings.RENDERERS
        ("renderer", "RENDERER", 0, len(SET.RENDERERS) - 1, 1, "renderer"),
    )
    HINTS = {
        "fov": "WIDER SEES MORE STREET BUT SHRINKS EVERYTHING. 90 IS THE CLASSIC.",
        "mouse_sens": "HOW FAR THE VIEW TURNS PER MOUSE MOVE (LOOK, AIM, CHASE CAM). 1.00X IS STANDARD.",
        "invert_y": "ON: MOUSE UP LOOKS DOWN, LIKE A FLIGHT STICK.",
        "renderer": "3D: REAL 3D CARS AND STREETS (NEEDS OPENGL). CLASSIC: THE OLD RAYCASTER.",
        "render_scale": "HOW SHARP THE 3D VIEW IS. LOWER = FASTER, HIGHER = CRISPER.",
        "world_scale": "CLASSIC: SHARPER WALLS AND STREETS. CAN'T EXCEED RENDER SCALE. 3D: FOLLOWS RENDER SCALE.",
        "master": "EVERYTHING AT ONCE.",
        "music": "THE BEAT (M IN GAME TURNS IT OFF).",
        "sfx": "PUNCHES, CRASHES, SIRENS, THE LOT.",
        "engine": "YOUR ENGINE AND EVERYONE ELSE'S.",
    }
    # Layout (canvas px). The window nearly fills the 360 px canvas: 10 setting rows at 20 px (v0.20: were
    # 22; at 22 the tenth row pushed the hint into the key line), then the SAVE FILES header, three slot
    # rows at 20 px, the hint and the key line, all inside BOX.
    BOX = pygame.Rect(120, 8, 400, 344)
    ROW_Y0, ROW_H = 42, 20                        # first row's top and the pitch between rows
    SLOT_HEAD_Y = ROW_Y0 + len(ROWS) * ROW_H + 4  # the SAVE FILES header line
    SLOT_Y0, SLOT_H = SLOT_HEAD_Y + 14, 20
    TRACK_X, TRACK_W = 250, 190                   # slider track, canvas px
    REPEAT_DELAY, REPEAT_RATE = 0.35, 0.05        # hold A/D: wait, then step every 50 ms

    def __init__(self, font, data, on_change=None, locked_path=None):
        self.font = font
        self.data = data
        self.on_change = on_change
        self.locked_path = locked_path
        self.sel = 0
        self.drag = None           # row index being dragged with the mouse
        self.hold_t = 0.0
        self.hold_dir = 0
        self.confirm = None        # ConfirmDialog, when asking about a slot
        self.confirm_slot = 0
        self.back_rect = pygame.Rect(self.BOX.x + 8, self.BOX.y + 8, 96, 14)
        self.refresh_slots()

    def refresh_slots(self):
        self.slots = {n: SF.peek(SF.slot_path(n)) for n in range(1, C.SAVE_SLOTS + 1)}

    def slot_locked(self, n):
        return bool(self.locked_path) and os.path.abspath(self.locked_path) == os.path.abspath(SF.slot_path(n))

    @property
    def total(self):
        return len(self.ROWS) + C.SAVE_SLOTS

    # -- geometry
    def row_rect(self, i):
        return pygame.Rect(self.BOX.x + 10, self.ROW_Y0 + i * self.ROW_H, self.BOX.w - 20, self.ROW_H - 4)

    def slot_rect(self, n):
        """Row for save slot n (1-based)."""
        return pygame.Rect(self.BOX.x + 10, self.SLOT_Y0 + (n - 1) * self.SLOT_H, self.BOX.w - 20, self.SLOT_H - 4)

    def slot_del_rect(self, n):
        r = self.slot_rect(n)
        return pygame.Rect(r.right - 84, r.y + 2, 80, r.h - 4)

    def track_rect(self, i):
        r = self.row_rect(i)
        return pygame.Rect(self.TRACK_X, r.centery - 3, self.TRACK_W, 6)

    def scale_rects(self, i):
        """The three 1X/2X/3X buttons that stand in for a slider (render scale, world detail)."""
        r = self.row_rect(i)
        lo, hi = self.ROWS[i][2], self.ROWS[i][3]
        n = hi - lo + 1
        w = (self.TRACK_W - 8 * (n - 1)) // n
        return [pygame.Rect(self.TRACK_X + k * (w + 8), r.y + 3, w, r.h - 6) for k in range(n)]

    def _cap(self, i):
        """Highest allowed value for a row: WORLD DETAIL can't exceed the render scale."""
        key, _l, lo, hi, _s, _k = self.ROWS[i]
        if key == "world_scale":
            return max(lo, min(hi, self.data.get("render_scale", hi)))
        return hi

    def _value(self, i):
        if self.ROWS[i][5] == "renderer":
            v = self.data.get(self.ROWS[i][0])
            return SET.RENDERERS.index(v) if v in SET.RENDERERS else 0
        v = int(self.data[self.ROWS[i][0]])
        return min(v, self._cap(i))            # (a saved 3x world under a 2x render reads as 2x)

    # -- values
    def _set(self, i, v):
        key, _l, lo, hi, _s, _k = self.ROWS[i]
        v = max(lo, min(self._cap(i), int(round(v))))
        if self.ROWS[i][5] == "toggle":
            v = bool(v)                      # (settings.json keeps a real true/false)
        elif self.ROWS[i][5] == "renderer":
            v = SET.RENDERERS[v]             # (a word in the file, not a button index)
        if v != self.data.get(key):
            self.data[key] = v
            if self.on_change:
                self.on_change(key)
            if key == "render_scale" and self.data.get("world_scale", 1) > v and self.on_change:
                self.on_change("world_scale")    # (its effective value just dropped: re-apply)

    def _nudge(self, i, d):
        if i >= len(self.ROWS):
            return
        key, _l, lo, hi, step, _k = self.ROWS[i]
        cur = self._value(i)
        if step > 1 and cur % step:
            # off the grid (a dragged FOV of 87): the first press lands on the next mark, 90 or 85
            self._set(i, (cur // step + 1) * step if d > 0 else (cur // step) * step)
        else:
            self._set(i, cur + d * step)

    def _from_x(self, i, x):
        _key, _l, lo, hi, _s, _k = self.ROWS[i]
        t = (x - self.TRACK_X) / float(self.TRACK_W - 1)
        self._set(i, lo + max(0.0, min(1.0, t)) * (hi - lo))

    # -- save files
    def _ask_delete(self, n):
        info = self.slots.get(n)
        if not info or self.slot_locked(n):
            return
        self.confirm_slot = n
        self.confirm = ConfirmDialog("DELETE SLOT %d? %s." % (n, slot_summary(info)),
                                     "THE WHOLE SAVE GOES FOR GOOD. THERE IS NO UNDO.")

    def _answer(self, ans):
        if ans == "yes" and not self.slot_locked(self.confirm_slot):
            SF.wipe(SF.slot_path(self.confirm_slot))
            self.refresh_slots()
            if self.on_change:
                self.on_change("save_files")
        if ans:
            self.confirm = None

    # -- input
    def handle(self, ev, to_canvas=lambda p: p):
        """Returns "back" when the screen should close, else None. Swallows everything."""
        if self.confirm is not None:
            if ev.type == pygame.KEYDOWN:
                self._answer(self.confirm.key(ev))
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self._answer(self.confirm.click(to_canvas(ev.pos)))
            return None
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                return "back"
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % self.total
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % self.total
            elif ev.key in (pygame.K_LEFT, pygame.K_a):
                self._nudge(self.sel, -1)
                self.hold_dir, self.hold_t = -1, 0.0
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._nudge(self.sel, 1)
                self.hold_dir, self.hold_t = 1, 0.0
            elif ev.key in (pygame.K_DELETE, pygame.K_x) and self.sel >= len(self.ROWS):
                self._ask_delete(self.sel - len(self.ROWS) + 1)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = to_canvas(ev.pos)
            if self.back_rect.collidepoint(pos):
                return "back"
            for n in range(1, C.SAVE_SLOTS + 1):
                if self.slot_rect(n).collidepoint(pos):
                    self.sel = len(self.ROWS) + n - 1
                    if self.slot_del_rect(n).collidepoint(pos):
                        self._ask_delete(n)
            for i, row in enumerate(self.ROWS):
                if not self.row_rect(i).collidepoint(pos):
                    continue
                self.sel = i
                if row[5] in ("scale", "wscale", "toggle", "renderer"):
                    for k, r in enumerate(self.scale_rects(i)):
                        if r.collidepoint(pos):
                            if row[2] + k <= self._cap(i):       # (a greyed button does nothing)
                                self._set(i, row[2] + k)
                elif self.track_rect(i).inflate(12, 16).collidepoint(pos):
                    self.drag = i
                    self._from_x(i, pos[0])
        elif ev.type == pygame.MOUSEMOTION and self.drag is not None:
            self._from_x(self.drag, to_canvas(ev.pos)[0])
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.drag = None
        return None

    def tick(self, dt, keys):
        """Held A/D (or arrows) keep stepping after a short delay. `keys` is pygame.key.get_pressed()."""
        d = (1 if (keys[pygame.K_d] or keys[pygame.K_RIGHT]) else 0) - \
            (1 if (keys[pygame.K_a] or keys[pygame.K_LEFT]) else 0)
        if d == 0 or d != self.hold_dir or self.confirm is not None:
            self.hold_dir = d
            self.hold_t = 0.0
            return
        self.hold_t += dt
        while self.hold_t >= self.REPEAT_DELAY:
            self.hold_t -= self.REPEAT_RATE
            self._nudge(self.sel, d)

    # -- drawing
    def _hint(self):
        if self.sel < len(self.ROWS):
            return self.HINTS[self.ROWS[self.sel][0]]
        n = self.sel - len(self.ROWS) + 1
        if self.slot_locked(n):
            return "THIS SLOT IS THE GAME YOU'RE HOSTING. LEAVE TO THE MENU TO DELETE IT."
        if not self.slots.get(n):
            return "NOTHING IN THIS SLOT."
        return "DEL OR CLICK DELETE: WIPES THIS SLOT (IT ASKS FIRST)."

    def draw(self, low, mouse=None, shade=False):
        """shade=True (main menu): dim the backdrop first, since the menu itself isn't drawn under us."""
        f = self.font
        b = self.BOX
        if shade:
            low.blit(_shade_overlay(), (0, 0))
        panel = pygame.Surface(b.size, pygame.SRCALPHA)
        panel.fill((16, 14, 24, 240))
        low.blit(panel, b.topleft)
        low.fill(P["gold"], (b.x, b.y, b.w, 1))
        f.draw(low, "SETTINGS", b.centerx, b.y + 10, P["gold"], scale=3, align="center")
        hot = mouse is not None and self.back_rect.collidepoint(mouse)
        low.fill((70, 60, 100) if hot else (40, 36, 58), self.back_rect)
        f.draw(low, "BACK (ESC)", self.back_rect.centerx, self.back_rect.y + 4,
               P["gold"] if hot else P["white"], align="center")
        for i, (key, label, lo, hi, _st, kind) in enumerate(self.ROWS):
            r = self.row_rect(i)
            sel = i == self.sel
            if sel:
                low.fill((40, 36, 58), r)
                low.fill(P["gold"], (r.x, r.y, r.w, 1))
            col = P["gold"] if sel else P["white"]
            f.draw(low, label, r.x + 10, r.centery - 3, col)
            v = self.data[key]
            if kind in ("scale", "wscale", "toggle", "renderer"):
                cap = self._cap(i)
                cur = self._value(i)
                for k, br in enumerate(self.scale_rects(i)):
                    val = lo + k
                    on = val == cur
                    grey = val > cap
                    over = mouse is not None and br.collidepoint(mouse) and not grey
                    low.fill(P["gold"] if on else (70, 60, 100) if over else (20, 19, 30) if grey else (28, 26, 42), br)
                    f.draw(low, ("OFF", "ON")[val] if kind == "toggle" else SET.RENDERERS[val].upper() if kind == "renderer"
                           else "%dX" % val, br.centerx, br.centery - 3,
                           P["ink"] if on else (80, 76, 96) if grey else P["white"], None, align="center")
                txt = ""          # (the highlighted button already says it)
            else:
                t = self.track_rect(i)
                low.fill((28, 26, 42), t)
                low.fill((90, 84, 110), (t.x, t.y - 1, t.w, 1))
                fw = int((v - lo) / float(hi - lo) * (t.w - 1))
                low.fill(P["gold"] if sel else P["metal_l"], (t.x, t.y, fw + 1, t.h))
                low.fill(P["white"], (t.x + fw - 1, t.y - 3, 3, t.h + 6))
                txt = ("%d DEG" % v) if kind == "deg" else ("%.2fX" % (v / 100.0)) if kind == "mult" else ("%d%%" % v)
            f.draw(low, txt, r.right - 10, r.centery - 3, col, align="right")
        # SAVE FILES
        hy = self.SLOT_HEAD_Y
        low.fill((90, 84, 110), (b.x + 10, hy, b.w - 20, 1))
        f.draw(low, "SAVE FILES", b.x + 20, hy + 4, P["gold"])
        for n in range(1, C.SAVE_SLOTS + 1):
            r = self.slot_rect(n)
            sel = self.sel == len(self.ROWS) + n - 1
            if sel:
                low.fill((40, 36, 58), r)
                low.fill(P["gold"], (r.x, r.y, r.w, 1))
            info = self.slots.get(n)
            col = P["gold"] if sel else P["white"]
            label = "SLOT %d: EMPTY" % n if info is None else "SLOT %d: %s" % (n, slot_summary(info).replace(",", " "))
            f.draw(low, label, r.x + 10, r.centery - 3, col if info else P["metal_l"])
            if info is not None:
                br = self.slot_del_rect(n)
                locked = self.slot_locked(n)
                over = mouse is not None and br.collidepoint(mouse) and not locked
                low.fill((20, 19, 30) if locked else (120, 40, 44) if over else (90, 30, 34) if sel else (52, 30, 40), br)
                f.draw(low, "IN USE" if locked else "[DEL] DELETE", br.centerx, br.centery - 3,
                       (80, 76, 96) if locked else P["white"], align="center")
        f.draw(low, self._hint(), b.centerx, self.SLOT_Y0 + C.SAVE_SLOTS * self.SLOT_H + 6,
               P["metal_l"], align="center")
        f.draw(low, "W/S: PICK   A/D OR DRAG: CHANGE   DEL: DELETE A SAVE   ESC: BACK (SAVES)", b.centerx,
               b.bottom - 14, P["metal_l"], align="center")
        if self.confirm is not None:
            self.confirm.draw(f, low, mouse)

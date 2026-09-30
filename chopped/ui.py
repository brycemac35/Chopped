"""
ui.py -- the main menu. (The in-game HUD is the Doom-style status bar in
doomhud.py.) Everything is drawn on the 480x270 canvas with the pixel font.
"""

import math
import time

import pygame

from . import config as C
from . import savefile as SF
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


class Menu:
    """Main menu: Host / Join / Name / Quit. Text fields edited in place."""
    ITEMS = ["HOST GAME", "SAVE SLOT", "JOIN GAME", "NAME", "CHARACTER", "SETTINGS", "QUIT"]
    # the character panel under the rows (canvas px). Rows end near y=212 and the hint line near
    # y=220, so the panel starts at 232 and ends well above the footer lines (H-22).
    PANEL = pygame.Rect(W // 2 - 170, 234, 340, 64)

    def __init__(self, font, name, save_file=None, char=0):
        self.font = font
        self.char = int(char or 0) % len(roster())
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

    def _cycle_char(self, d):
        self.char = (self.char + d) % len(roster())

    def click(self, pos):
        """Mouse: the arrows on either side of the character panel cycle; so does the CHARACTER row."""
        if self.editing:
            return
        r = self.PANEL
        if r.collidepoint(pos):
            self.sel = self.ITEMS.index("CHARACTER")
            self._cycle_char(-1 if pos[0] < r.centerx else 1)

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
            elif item == "CHARACTER" and ev.key in (pygame.K_LEFT, pygame.K_a):
                self._cycle_char(-1)
            elif item == "CHARACTER" and ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._cycle_char(1)
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
                elif item == "CHARACTER":
                    self._cycle_char(1)
                elif item == "SETTINGS":
                    return "settings"
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
        y = 102          # (7 rows at 16 px: the hint lands at 218, clear of the character panel at 234)
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
            if item == "CHARACTER":
                label = "CHARACTER: < %s >" % char_info(self.char)["name"]
            if item == "JOIN GAME" and self.editing == "join":
                cur = "_" if int(now * 3) % 2 else ""
                label = "JOIN IP[:PORT]: %s%s" % (self.join_addr, cur)
            col = P["gold"] if selected else P["white"]
            if selected:
                f.draw(low, ">", W // 2 - PixelFont.width(label) - 12, y, col, scale=2)
            f.draw(low, label, W // 2, y, col, scale=2, align="center")
            y += 16
        if self.editing == "join":
            f.draw(low, "TYPE THE HOST'S IP (DEFAULT PORT %d), ENTER TO CONNECT, ESC TO CANCEL" % C.DEFAULT_PORT,
                   W // 2, y + 4, P["metal_l"], align="center")
        elif self.editing == "name":
            f.draw(low, "TYPE YOUR NAME, ENTER TO SAVE", W // 2, y + 4, P["metal_l"], align="center")
        elif self.ITEMS[self.sel] == "SETTINGS":
            f.draw(low, "FIELD OF VIEW, RENDER SCALE AND VOLUMES. SAVED FOR NEXT TIME.", W // 2, y + 4,
                   P["metal_l"], align="center")
        elif self.ITEMS[self.sel] == "CHARACTER":
            f.draw(low, "A/D OR CLICK THE ARROWS: PICK WHO YOU ARE. THE PERK IS YOURS ALL RUN.", W // 2, y + 4,
                   P["metal_l"], align="center")
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
                n = len(STORY_CHAPTERS)
                ch = info.get("story_ch", 0)
                story = ("STORY %d/%d" % (ch + 1, n)) if ch < n else "STORY DONE"
                hint = "%s  REP %d  CREW: %s  -  A/D: OTHER SLOTS, DEL: WIPE" % (story, info["rep"], crew)
            f.draw(low, hint[:100], W // 2, y + 4, P["metal_l"], align="center")
        else:
            f.draw(low, "W/S OR ARROWS TO PICK, ENTER TO GO", W // 2, y + 4, P["metal_l"], align="center")
        self._draw_char_panel(low)
        if self.error and now - self.error_t < 8:
            f.draw(low, self.error, W // 2, H - 22, P["danger"], align="center")
        f.draw(low, "V%d.%d.%d" % C.RELEASE, W - 4, H - 10, P["metal_l"], align="right")
        f.draw(low, "HOST: UDP PORT %d. UPNP IS TRIED AUTOMATICALLY." % C.DEFAULT_PORT, W // 2, H - 10,
               P["metal_l"], align="center")

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
    Keys: W/S pick a row, A/D adjust (hold to repeat), Esc/Enter back. Mouse: click or drag a slider."""
    # (key, label, lo, hi, step, kind) -- kind picks how the value reads
    ROWS = (
        ("fov", "FOV", C.FOV_MIN, C.FOV_MAX, 5, "deg"),
        ("render_scale", "RENDER SCALE", C.RENDER_SCALE_MIN, C.RENDER_SCALE_MAX, 1, "scale"),
        ("master", "MASTER", 0, 100, 5, "pct"),
        ("music", "MUSIC", 0, 100, 5, "pct"),
        ("sfx", "SFX", 0, 100, 5, "pct"),
        ("engine", "ENGINES", 0, 100, 5, "pct"),
    )
    HINTS = {
        "fov": "WIDER SEES MORE STREET BUT SHRINKS EVERYTHING. 90 IS THE CLASSIC.",
        "render_scale": "HOW SHARP THE 3D VIEW IS. LOWER = FASTER, HIGHER = CRISPER.",
        "master": "EVERYTHING AT ONCE.",
        "music": "THE BEAT (M IN GAME TURNS IT OFF).",
        "sfx": "PUNCHES, CRASHES, SIRENS, THE LOT.",
        "engine": "YOUR ENGINE AND EVERYONE ELSE'S.",
    }
    BOX = pygame.Rect(120, 34, 400, 292)          # the window, centred on the 640x360 canvas
    ROW_Y0, ROW_H = 84, 28                        # first row's top and the pitch between rows
    TRACK_X, TRACK_W = 250, 190                   # slider track, canvas px
    REPEAT_DELAY, REPEAT_RATE = 0.35, 0.05        # hold A/D: wait, then step every 50 ms

    def __init__(self, font, data, on_change=None):
        self.font = font
        self.data = data
        self.on_change = on_change
        self.sel = 0
        self.drag = None           # row index being dragged with the mouse
        self.hold_t = 0.0
        self.hold_dir = 0
        self.back_rect = pygame.Rect(self.BOX.x + 8, self.BOX.y + 8, 96, 14)

    # -- geometry
    def row_rect(self, i):
        return pygame.Rect(self.BOX.x + 10, self.ROW_Y0 + i * self.ROW_H, self.BOX.w - 20, self.ROW_H - 4)

    def track_rect(self, i):
        r = self.row_rect(i)
        return pygame.Rect(self.TRACK_X, r.centery - 3, self.TRACK_W, 6)

    def scale_rects(self, i):
        """The three 1X/2X/3X buttons that stand in for a slider on the render-scale row."""
        r = self.row_rect(i)
        n = C.RENDER_SCALE_MAX - C.RENDER_SCALE_MIN + 1
        w = (self.TRACK_W - 8 * (n - 1)) // n
        return [pygame.Rect(self.TRACK_X + k * (w + 8), r.y + 3, w, r.h - 6) for k in range(n)]

    # -- values
    def _set(self, i, v):
        key, _l, lo, hi, _s, _k = self.ROWS[i]
        v = max(lo, min(hi, int(round(v))))
        if v != self.data.get(key):
            self.data[key] = v
            if self.on_change:
                self.on_change(key)

    def _nudge(self, i, d):
        key, _l, lo, hi, step, _k = self.ROWS[i]
        cur = self.data[key]
        if step > 1 and cur % step:
            # off the grid (a dragged FOV of 87): the first press lands on the next mark, 90 or 85
            self._set(i, (cur // step + 1) * step if d > 0 else (cur // step) * step)
        else:
            self._set(i, cur + d * step)

    def _from_x(self, i, x):
        _key, _l, lo, hi, _s, _k = self.ROWS[i]
        t = (x - self.TRACK_X) / float(self.TRACK_W - 1)
        self._set(i, lo + max(0.0, min(1.0, t)) * (hi - lo))

    # -- input
    def handle(self, ev, to_canvas=lambda p: p):
        """Returns "back" when the screen should close, else None. Swallows everything."""
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                return "back"
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.sel = (self.sel - 1) % len(self.ROWS)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.sel = (self.sel + 1) % len(self.ROWS)
            elif ev.key in (pygame.K_LEFT, pygame.K_a):
                self._nudge(self.sel, -1)
                self.hold_dir, self.hold_t = -1, 0.0
            elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                self._nudge(self.sel, 1)
                self.hold_dir, self.hold_t = 1, 0.0
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = to_canvas(ev.pos)
            if self.back_rect.collidepoint(pos):
                return "back"
            for i, row in enumerate(self.ROWS):
                if not self.row_rect(i).collidepoint(pos):
                    continue
                self.sel = i
                if row[5] == "scale":
                    for k, r in enumerate(self.scale_rects(i)):
                        if r.collidepoint(pos):
                            self._set(i, C.RENDER_SCALE_MIN + k)
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
        if d == 0 or d != self.hold_dir:
            self.hold_dir = d
            self.hold_t = 0.0
            return
        self.hold_t += dt
        while self.hold_t >= self.REPEAT_DELAY:
            self.hold_t -= self.REPEAT_RATE
            self._nudge(self.sel, d)

    # -- drawing
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
        f.draw(low, "SETTINGS", b.centerx, b.y + 24, P["gold"], scale=3, align="center")
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
            if kind == "scale":
                for k, br in enumerate(self.scale_rects(i)):
                    on = C.RENDER_SCALE_MIN + k == v
                    over = mouse is not None and br.collidepoint(mouse)
                    low.fill(P["gold"] if on else (70, 60, 100) if over else (28, 26, 42), br)
                    f.draw(low, "%dX" % (C.RENDER_SCALE_MIN + k), br.centerx, br.centery - 3,
                           P["ink"] if on else P["white"], None, align="center")
                txt = ""          # (the highlighted button already says it)
            else:
                t = self.track_rect(i)
                low.fill((28, 26, 42), t)
                low.fill((90, 84, 110), (t.x, t.y - 1, t.w, 1))
                fw = int((v - lo) / float(hi - lo) * (t.w - 1))
                low.fill(P["gold"] if sel else P["metal_l"], (t.x, t.y, fw + 1, t.h))
                low.fill(P["white"], (t.x + fw - 1, t.y - 3, 3, t.h + 6))
                txt = ("%d DEG" % v) if kind == "deg" else ("%d%%" % v)
            f.draw(low, txt, r.right - 10, r.centery - 3, col, align="right")
        f.draw(low, self.HINTS[self.ROWS[self.sel][0]], b.centerx, self.ROW_Y0 + len(self.ROWS) * self.ROW_H + 6,
               P["metal_l"], align="center")
        f.draw(low, "W/S: PICK   A/D OR DRAG: CHANGE   ESC: BACK (SAVES)", b.centerx, b.bottom - 14,
               P["metal_l"], align="center")

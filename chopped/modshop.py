"""
modshop.py -- the GTA-style garage menu (client side). The host sends the
state of your ride and the parts locker (garage.encode_menu) while you're in
it; this draws it, lets you browse, and queues one command at a time for the
host (garage.OP_*). The preview car wears whatever you're hovering over, so
you can see the gold mesh wheels before you pay for them.

Keys: W/S or arrows to move, Enter/E/D to go in or do it, A/Backspace to go
back, Esc to leave. In LIVERY, A/D (left/right) picks the second colour. In
the LOCKER, Enter sells and X takes the part out. Mouse: the wheel moves,
click a row to highlight it and click it again to do it, right click goes
back.
"""

import math
from collections import deque

import pygame

from . import config as C
from . import vehicles as V
from . import garage as G
from . import fpart as FA
from .art import P, CAR_COLORS
from .parts import SLOT_CATEGORY, SLOT_INDEX, PART_DEFS, PART_INDEX, Part, part_power

W, H = C.LOW_W, C.LOW_H

CATS = [("ENGINE", "slot", "Engine"), ("GEARBOX", "slot", "Transmission"), ("ECU", "slot", "ECU"),
        ("EXHAUST", "slot", "Exhaust"), ("HOOD", "slot", "Hood"), ("FRONT BUMPER", "slot", "BumperF"),
        ("REAR BUMPER", "slot", "BumperR"), ("SPOILER", "slot", "Spoiler"), ("LEFT DOOR", "slot", "DoorL"),
        ("RIGHT DOOR", "slot", "DoorR"), ("WHEEL FRONT-L", "slot", "WheelFL"), ("WHEEL FRONT-R", "slot", "WheelFR"),
        ("WHEEL REAR-L", "slot", "WheelRL"), ("WHEEL REAR-R", "slot", "WheelRR"), ("SEATS", "slot", "Seats"),
        ("PAINT", "paint", None), ("LIVERY", "livery", None), ("HORN", "horn", None),
        ("UNDERGLOW", "glow", None), ("EXTRAS", "extra", None), ("LOCKER", "locker", None)]
ROWS = 17                         # visible item rows
CAT_X, CAT_Y = 12, 46             # where the category list and the item list start (clicks use these too)
ITEM_X, ITEM_Y = 124, 46


class Item:
    __slots__ = ("label", "right", "op", "a", "b", "preview", "col", "alt")

    def __init__(self, label, right="", op=G.OP_NONE, a=0, b=0, preview=None, col=None, alt=None):
        self.label, self.right = label, right
        self.op, self.a, self.b = op, a, b
        self.preview = preview        # what the preview car wears while this is highlighted
        self.col = col
        self.alt = alt                # (op, a, b) for X (take out of the locker)


class ModShop:
    def __init__(self, font):
        self.font = font
        self.open = False
        self.cat = 0
        self.item = 0
        self.focus = 0                # 0 = categories, 1 = items
        self.second = 5               # livery second colour
        self.pending = deque()
        self.seq = 0                  # the command number currently in flight
        self.cache = {}
        self.menu = None
        self.hover_horn = None        # the client plays a horn preview when this changes

    # ------------------------------------------------------------------ state
    def sync(self, menu):
        """A snapshot arrived. menu is the host's menu dict (or None: closed)."""
        if menu is None:
            if self.open:
                self.open = False
                self.pending.clear()
            return
        if not self.open:
            self.open = True
            self.seq = menu["ack"]                # nothing of ours is in flight yet
            self.pending.clear()
            self.focus = 0
        self.menu = menu

    def next_command(self):
        """(seq, op, a, b) to put in this tick's input. A new command only goes
        out once the host has acknowledged the last one."""
        if self.menu is not None and self.menu["ack"] == self.seq and self.pending:
            op, a, b = self.pending.popleft()
            self.seq = (self.seq + 1) & 255
            self.last = (op, a, b)
        cmd = getattr(self, "last", (G.OP_NONE, 0, 0))
        return self.seq, cmd[0], cmd[1], cmd[2]

    def close(self):
        self.pending.append((G.OP_CLOSE, 0, 0))
        self.open = False

    # ------------------------------------------------------------------ items
    def items(self):
        m = self.menu
        if m is None:
            return []
        label, kind, slot = CATS[self.cat]
        out = []
        if kind == "slot":
            si = SLOT_INDEX[slot]
            cat = SLOT_CATEGORY[slot]
            cur = m["slots"][slot]
            if cur is not None:
                tid, style, cond = cur
                out.append(Item("FITTED: " + Part(tid, cond, style).name.upper(), "%d%%  REMOVE" % (cond * 100),
                                G.OP_REMOVE, si, 0, preview=("slot", slot, cur), col=P["money"]))
            else:
                out.append(Item("(EMPTY)", "", preview=("slot", slot, None), col=(120, 118, 130)))
            for i, (tid, style, cond) in enumerate(m["stash"]):
                if PART_DEFS[tid][1] == cat:
                    out.append(Item("LOCKER: " + Part(tid, cond, style).name.upper(), "%d%%  FIT" % (cond * 100),
                                    G.OP_INSTALL, i, si, preview=("slot", slot, (tid, style, cond)), col=P["gold"]))
            for k, (tid, style, price) in enumerate(G.catalogue(slot)):
                out.append(Item("NEW: " + Part(tid, 1.0, style).name.upper(), "$%d" % price, G.OP_BUY, k, si,
                                preview=("slot", slot, (tid, style, 1.0))))
        elif kind == "paint":
            for c, name in enumerate(V.PAINT_NAMES):
                mine = c == m["color"]
                out.append(Item(name, "FITTED" if mine else "$%d" % C.PRICE_PAINT, G.OP_PAINT, c,
                                preview=("color", c), col=CAR_COLORS[c]))
        elif kind == "livery":
            for pat, name in enumerate(V.LIVERIES):
                mine = V.livery_byte(pat, self.second) == m["livery"] or (pat == 0 and m["livery"] & 15 == 0)
                out.append(Item(name + ("  (A/D: 2ND COLOUR %s)" % V.PAINT_NAMES[self.second] if pat else ""),
                                "FITTED" if mine else ("$%d" % C.PRICE_LIVERY if pat else "FREE"),
                                G.OP_LIVERY, pat, self.second, preview=("livery", V.livery_byte(pat, self.second))))
        elif kind == "horn":
            for h, name in enumerate(V.HORNS):
                out.append(Item(name, "FITTED" if h == m["horn"] else "$%d" % G.horn_price(h), G.OP_HORN, h,
                                preview=("horn", h)))
        elif kind == "glow":
            out.append(Item("OFF", "FITTED" if not m["glow"] else "FREE", G.OP_GLOW, 0, preview=("glow", 0)))
            for c, name in enumerate(V.PAINT_NAMES[:15]):
                out.append(Item(name + " NEON", "FITTED" if m["glow"] == c + 1 else "$%d" % C.PRICE_GLOW,
                                G.OP_GLOW, c + 1, preview=("glow", c + 1), col=CAR_COLORS[c]))
        elif kind == "extra":
            owned = (m["nos"], m["ejector"], m["gnome"], m.get("hydro", False))
            for k, name in enumerate(G.EXTRA_NAMES):
                out.append(Item(name, "FITTED" if owned[k] else "$%d" % G.extra_price(k), G.OP_EXTRA, k,
                                preview=("gnome", True) if k == G.EXTRA_GNOME else None))
        else:
            for i, (tid, style, cond) in enumerate(m["stash"]):
                part = Part(tid, cond, style)
                out.append(Item(part.name.upper(), "$%d  SELL / X: TAKE" % part.value, G.OP_SELL, i,
                                PART_INDEX[tid], alt=(G.OP_TAKE, i, PART_INDEX[tid])))
            if not out:
                out.append(Item("THE LOCKER IS EMPTY. BRING PARTS TO THE BENCH.", ""))
        return out

    # ------------------------------------------------------------------ input
    def handle(self, ev):
        """Menu keys. Returns True if the key was ours."""
        if ev.type == pygame.MOUSEWHEEL:
            self._move(-ev.y)
            return True
        if ev.type != pygame.KEYDOWN:
            return False
        k = ev.key
        if k in (pygame.K_UP, pygame.K_w):
            self._move(-1)
        elif k in (pygame.K_DOWN, pygame.K_s):
            self._move(1)
        elif k in (pygame.K_PAGEUP,):
            self._move(-ROWS)
        elif k in (pygame.K_PAGEDOWN,):
            self._move(ROWS)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_e, pygame.K_SPACE) or \
                (k in (pygame.K_RIGHT, pygame.K_d) and self.focus == 0):
            if self.focus == 0:
                self.focus = 1
                self.item = 0
            else:
                items = self.items()
                if 0 <= self.item < len(items):
                    self._activate(items[self.item])
        elif k in (pygame.K_LEFT, pygame.K_a, pygame.K_RIGHT, pygame.K_d) and CATS[self.cat][1] == "livery":
            self.second = (self.second + (1 if k in (pygame.K_RIGHT, pygame.K_d) else -1)) % len(V.PAINT_NAMES)
        elif k == pygame.K_x and self.focus == 1:
            items = self.items()
            if 0 <= self.item < len(items) and items[self.item].alt:
                self.pending.append(items[self.item].alt)
        elif k in (pygame.K_BACKSPACE, pygame.K_LEFT, pygame.K_a):
            self.focus = 0
        elif k == pygame.K_ESCAPE:
            if self.focus == 1:
                self.focus = 0
            else:
                self.close()
        else:
            return False
        return True

    def _top(self, items):
        """First visible item row: the list scrolls to keep the highlight mid-screen."""
        return max(0, min(self.item - ROWS // 2, len(items) - ROWS))

    def _activate(self, it):
        if it.op != G.OP_NONE:
            self.pending.append((it.op, it.a, it.b))

    def click(self, pos, button):
        """Mouse, in canvas pixels. Returns True if the click was ours."""
        if button == 3:                           # right click: back out, then leave
            if self.focus == 1:
                self.focus = 0
            else:
                self.close()
            return True
        if button != 1:
            return False
        x, y = pos
        if CAT_X - 3 <= x < CAT_X + 101 and CAT_Y - 2 <= y < CAT_Y - 2 + len(CATS) * 12:
            self.cat = (y - CAT_Y + 2) // 12
            self.focus, self.item = 1, 0          # clicking a category opens it
            return True
        items = self.items()
        if ITEM_X - 3 <= x < ITEM_X + 313 and ITEM_Y - 2 <= y < ITEM_Y - 2 + ROWS * 12:
            i = self._top(items) + (y - ITEM_Y + 2) // 12
            if i < len(items):
                if self.focus == 1 and i == self.item:
                    self._activate(items[i])      # second click on the highlight: do it
                else:
                    self.focus, self.item = 1, i
            return True
        return False

    def _move(self, d):
        if self.focus == 0:
            self.cat = (self.cat + d) % len(CATS)
            self.item = 0
        else:
            n = len(self.items())
            self.item = max(0, min(n - 1, self.item + d)) if n else 0

    # ------------------------------------------------------------------ preview + stats
    def _preview_state(self, hovered):
        m = self.menu
        slots = dict(m["slots"])
        color, livery, glow, gnome = m["color"], m["livery"], m["glow"], m["gnome"]
        pv = hovered.preview if hovered is not None and self.focus == 1 else None
        if pv:
            if pv[0] == "slot":
                slots[pv[1]] = pv[2]
            elif pv[0] == "color":
                color = pv[1]
            elif pv[0] == "livery":
                livery = pv[1]
            elif pv[0] == "glow":
                glow = pv[1]
            elif pv[0] == "gnome":
                gnome = True
        parts = {s: (Part(v[0], v[2], v[1]) if v is not None else None) for s, v in slots.items()}
        return parts, color, livery, glow, gnome

    def _stats(self, parts, model):
        mdl = V.model(model)
        power = sum(part_power(p.type_id) for p in parts.values() if p is not None)
        grip, mass, top = V.performance(mdl, parts)
        accel = C.ACCEL_PER_100_POWER * power / 100.0 * mdl.accel
        return {"POWER": power, "TOP SPEED": mdl.top * top * 3.6, "ACCEL": accel,
                "GRIP": grip * mdl.grip, "WEIGHT": mass}

    # ------------------------------------------------------------------ draw
    def draw(self, low, cash, now):
        if not self.open or self.menu is None:
            return
        f = self.font
        m = self.menu
        shade_ = pygame.Surface((W, H), pygame.SRCALPHA)
        shade_.fill((12, 10, 20, 225))
        low.blit(shade_, (0, 0))
        f.draw(low, "MOD SHOP", 12, 8, P["gold"], scale=3)
        f.draw(low, "YOUR %s" % V.model(m["model"]).name, 12, 30, P["white"])
        f.draw(low, "CASH $%d" % cash, W - 12, 10, P["money"] if cash >= 0 else P["danger"], scale=2, align="right")
        # categories
        cx, cy = CAT_X, CAT_Y
        for i, (label, kind, slot) in enumerate(CATS):
            sel = i == self.cat
            col = P["gold"] if sel and self.focus == 0 else P["white"] if sel else (150, 148, 160)
            if sel:
                low.fill((50, 44, 70), (cx - 3, cy + i * 12 - 2, 104, 11))
            f.draw(low, label, cx, cy + i * 12, col)
        # items
        items = self.items()
        ix, iy = ITEM_X, ITEM_Y
        top = self._top(items)
        for row, it in enumerate(items[top:top + ROWS]):
            i = top + row
            sel = self.focus == 1 and i == self.item
            if sel:
                low.fill((60, 52, 84), (ix - 3, iy + row * 12 - 2, 316, 11))
            if it.col is not None and CATS[self.cat][1] in ("paint", "glow"):
                low.fill(it.col, (ix, iy + row * 12, 8, 7))
                tx = ix + 12
            else:
                tx = ix
            col = it.col if (it.col is not None and CATS[self.cat][1] not in ("paint", "glow")) else P["white"]
            f.draw(low, it.label[:52], tx, iy + row * 12, P["gold"] if sel else col)
            f.draw(low, it.right, ix + 308, iy + row * 12, P["money"] if "FIT" in it.right or it.right == "FITTED"
                   else P["white"], align="right")
        if len(items) > ROWS:
            f.draw(low, "%d/%d" % (self.item + 1, len(items)), ix + 308, iy + ROWS * 12 + 2, P["metal_l"], align="right")
        hovered = items[self.item] if (self.focus == 1 and 0 <= self.item < len(items)) else None
        if hovered is not None and hovered.preview and hovered.preview[0] == "horn":
            self.hover_horn = hovered.preview[1]
        else:
            self.hover_horn = None
        # preview car + stats
        parts, color, livery, glow, gnome = self._preview_state(hovered)
        self._draw_car(low, parts, color, livery, glow, gnome, m["model"], now)
        cur = self._stats({s: (Part(v[0], v[2], v[1]) if v is not None else None) for s, v in m["slots"].items()},
                          m["model"])
        new = self._stats(parts, m["model"])
        sx, sy = 454, 196
        for k, (name, lo, hi, better_high) in enumerate((("POWER", 0, 300, True), ("TOP SPEED", 0, 220, True),
                                                         ("ACCEL", 0, 25, True), ("GRIP", 0.5, 1.4, True),
                                                         ("WEIGHT", 400, 2200, False))):
            y = sy + k * 18
            v0, v1 = cur[name], new[name]
            f.draw(low, name, sx, y, P["white"])
            txt = ("%d" % v1) if name != "GRIP" else ("%.2f" % v1)
            f.draw(low, txt, sx + 176, y, P["white"], align="right")
            bw = 176
            low.fill((40, 38, 50), (sx, y + 8, bw, 5))
            a = max(0.0, min(1.0, (v0 - lo) / (hi - lo)))
            b = max(0.0, min(1.0, (v1 - lo) / (hi - lo)))
            low.fill((200, 200, 210), (sx, y + 8, int(bw * min(a, b)), 5))
            if abs(b - a) > 1e-3:
                better = (b > a) == better_high
                low.fill(P["money"] if better else P["danger"], (sx + int(bw * min(a, b)), y + 8,
                                                                 max(1, int(bw * abs(b - a))), 5))
        hint = "W/S OR WHEEL: MOVE   ENTER/E OR CLICK: SELECT   A/BACKSPACE/RIGHT CLICK: BACK   ESC: LEAVE"
        if CATS[self.cat][1] == "locker":
            hint = "W/S: MOVE   ENTER: SELL   X: TAKE OUT   A: BACK   ESC: LEAVE"
        elif CATS[self.cat][1] == "livery":
            hint = "W/S: PATTERN   A/D: SECOND COLOUR   ENTER: PAINT IT   ESC: LEAVE"
        f.draw(low, hint, W // 2, H - 12, P["metal_l"], align="center")
        f.draw(low, "LOCKER: %d/%d PARTS" % (len(m["stash"]), C.STASH_MAX), 12, H - 24, P["metal_l"])

    def _draw_car(self, low, parts, color, livery, glow, gnome, model, now):
        mask = 0
        for s, p in parts.items():
            if p is not None:
                mask |= 1 << SLOT_INDEX[s]
        styles = V.pack_styles(parts)
        step = int(now * 10) % 72
        key = (mask, styles, color, livery, gnome, model, step)
        img = self.cache.get(key)
        if img is None:
            if len(self.cache) > 300:
                self.cache.clear()
            boxes = FA.car_boxes(1, color, mask, styles, 0, 0, model, livery, 0, 1 if gnome else 0)
            img = self.cache[key] = FA.render_boxes(boxes, step * 2 * math.pi / 72, 24, el=0.35)
        surf, ax, ay = img
        cx, cy = 542, 150
        if glow:
            g = pygame.Surface((180, 40), pygame.SRCALPHA)
            pygame.draw.ellipse(g, CAR_COLORS[(glow - 1) % len(CAR_COLORS)] + (90,), (0, 0, 180, 40))
            low.blit(g, (cx - 90, cy - 22))
        low.fill((30, 28, 40), (cx - 110, cy - 4, 220, 10))
        low.blit(surf, (int(cx - ax), int(cy - ay)))


"""
art.py -- every pixel in the game is made right here at startup. No asset
files, no artists harmed. One small palette keeps it all looking like it came
out of the same beige box in 1999.
"""

import math
import random

import pygame

from . import config as C
from . import mapgen as M
from .parts import SLOT_INDEX, PART_IDS, PART_DEFS
from .sim import PERSONAL, COP, TRAFFIC

# ---------------------------------------------------------------------------
# Palette (~40 colours). Reuse these; resist the urge to invent new greys.
# ---------------------------------------------------------------------------
P = {
    "void": (18, 16, 26), "ink": (30, 28, 42), "ink2": (44, 42, 58),
    "asphalt": (62, 62, 74), "asphalt_l": (70, 70, 83), "asphalt_d": (54, 54, 66),
    "line_y": (236, 196, 72), "line_w": (214, 214, 206),
    "sidewalk": (148, 144, 138), "sidewalk_d": (130, 126, 122), "curb": (184, 180, 170),
    "grass": (82, 132, 64), "grass_d": (68, 114, 54), "grass_l": (100, 152, 76),
    "tree_d": (34, 82, 50), "tree": (50, 110, 60), "tree_l": (86, 150, 78),
    "concrete": (122, 122, 120), "concrete_d": (106, 106, 106), "oil": (80, 80, 88),
    "wall": (86, 72, 74), "wall_l": (124, 104, 98),
    "glass": (126, 178, 210), "glass_d": (78, 118, 150),
    "tire": (24, 22, 28), "rim": (168, 170, 182), "gold": (236, 196, 72),
    "chrome": (206, 208, 216), "metal": (64, 66, 78), "metal_l": (98, 100, 112),
    "wood": (138, 92, 58), "wood_d": (104, 68, 44),
    "red": (214, 58, 58), "red_d": (150, 36, 44), "blue": (70, 120, 255), "blue_d": (40, 60, 140),
    "green": (84, 200, 96), "green_d": (44, 120, 60), "white": (238, 238, 232),
    "light": (255, 240, 170), "fire1": (255, 232, 120), "fire2": (255, 150, 40), "fire3": (210, 60, 30),
    "smoke": (96, 96, 104), "smoke_l": (140, 140, 148),
    "hud_bg": (20, 18, 30), "money": (120, 230, 110), "danger": (255, 80, 70),
}
ROOF_COLORS = [(142, 76, 66), (66, 112, 116), (92, 98, 124), (170, 142, 102), (118, 66, 86), (104, 110, 90)]
# v0.7: 16 paints (vehicles.PAINT_NAMES, same order). 0 = your ride's lime.
CAR_COLORS = [(150, 222, 64), (206, 58, 58), (64, 98, 196), (232, 190, 64), (226, 226, 220),
              (44, 44, 52), (224, 126, 54), (60, 164, 160), (126, 64, 160), (160, 166, 178),
              (236, 130, 190), (120, 80, 50), (212, 170, 60), (40, 50, 110), (150, 230, 190),
              (40, 90, 30)]
PAINTS = CAR_COLORS
PLAYER_COLORS = [(255, 150, 40), (60, 220, 230), (236, 90, 206), (250, 232, 80)]
SKINS = [(240, 200, 160), (206, 156, 114), (150, 104, 70), (100, 68, 48)]
HAIRS = [(40, 30, 24), (90, 60, 30), (200, 170, 90), (150, 60, 40), (60, 60, 70), (220, 220, 220)]
SHIRTS = [(90, 120, 180), (180, 80, 80), (80, 150, 100), (200, 180, 120), (120, 90, 150), (70, 70, 80),
          (220, 140, 60), (200, 200, 200)]


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3])


# ---------------------------------------------------------------------------
# Pixel font: 3x5 glyphs (M/W/N wider). Hand-typed, lovingly, badly.
# ---------------------------------------------------------------------------
_GLYPHS = {
    "A": ".#.|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.", "C": ".##|#..|#..|#..|.##",
    "D": "##.|#.#|#.#|#.#|##.", "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..",
    "G": ".##|#..|#.#|#.#|.##", "H": "#.#|#.#|###|#.#|#.#", "I": "###|.#.|.#.|.#.|###",
    "J": "..#|..#|..#|#.#|.#.", "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
    "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#",
    "O": ".#.|#.#|#.#|#.#|.#.", "P": "##.|#.#|##.|#..|#..", "Q": ".#.|#.#|#.#|##.|.##",
    "R": "##.|#.#|##.|#.#|#.#", "S": ".##|#..|.#.|..#|##.", "T": "###|.#.|.#.|.#.|.#.",
    "U": "#.#|#.#|#.#|#.#|###", "V": "#.#|#.#|#.#|#.#|.#.", "W": "#...#|#...#|#.#.#|##.##|#...#",
    "X": "#.#|#.#|.#.|#.#|#.#", "Y": "#.#|#.#|.#.|.#.|.#.", "Z": "###|..#|.#.|#..|###",
    "0": "###|#.#|#.#|#.#|###", "1": ".#.|##.|.#.|.#.|###", "2": "##.|..#|.#.|#..|###",
    "3": "##.|..#|.#.|..#|##.", "4": "#.#|#.#|###|..#|..#", "5": "###|#..|##.|..#|##.",
    "6": ".##|#..|###|#.#|###", "7": "###|..#|.#.|.#.|.#.", "8": "###|#.#|###|#.#|###",
    "9": "###|#.#|###|..#|##.", " ": "..|..|..|..|..", ".": ".|.|.|.|#", ",": ".|.|.|#|#",
    "!": "#|#|#|.|#", "?": "##.|..#|.#.|...|.#.", ":": ".|#|.|#|.", "'": "#|#|.|.|.",
    "-": "...|...|###|...|...", "+": "...|.#.|###|.#.|...", "$": ".##|##.|.#.|.##|##.",
    "%": "#.#|..#|.#.|#..|#.#", "/": "..#|..#|.#.|#..|#..", "(": ".#|#.|#.|#.|.#",
    ")": "#.|.#|.#|.#|#.", "*": "...|#.#|.#.|#.#|...", "[": "##|#.|#.|#.|##", "]": "##|.#|.#|.#|##",
    ">": "#..|.#.|..#|.#.|#..", "<": "..#|.#.|#..|.#.|..#", "=": "...|###|...|###|...",
    "_": "...|...|...|...|###", "#": "#.#|###|#.#|###|#.#", "&": ".#.|#.#|.#.|#.#|.##",
    "\"": "#.#|#.#|...|...|...", "^": ".#.|#.#|...|...|...", "~": "...|.##|##.|...|...",
}
GLYPHS = {k: v.split("|") for k, v in _GLYPHS.items()}


class PixelFont:
    """Renders strings with the glyph table. Results are cached, because the
    HUD re-draws "CASH $300" sixty times a second and we'd rather not."""
    def __init__(self):
        self.cache = {}

    @staticmethod
    def width(text):
        w = 0
        for ch in text.upper():
            g = GLYPHS.get(ch, GLYPHS["?"])
            w += len(g[0]) + 1
        return max(0, w - 1)

    def render(self, text, color, shadow=(0, 0, 0), scale=1):
        key = (text, color, shadow, scale)
        s = self.cache.get(key)
        if s is not None:
            return s
        text = text.upper()
        w = self.width(text) + 1
        surf = pygame.Surface((max(1, w), 6), pygame.SRCALPHA)
        for pass_color, off in ((shadow, 1), (color, 0)):
            if pass_color is None:
                continue
            x = 0
            for ch in text:
                g = GLYPHS.get(ch, GLYPHS["?"])
                for gy, row in enumerate(g):
                    for gx, c in enumerate(row):
                        if c == "#":
                            surf.fill(pass_color, (x + gx + off, gy + off, 1, 1))
                x += len(g[0]) + 1
        if scale != 1:
            surf = pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale))
        if len(self.cache) > 800:
            self.cache.clear()
        self.cache[key] = surf
        return surf

    def draw(self, target, text, x, y, color=(238, 238, 232), shadow=(0, 0, 0), scale=1, align="left"):
        s = self.render(text, color, shadow, scale)
        if align == "center":
            x -= s.get_width() // 2
        elif align == "right":
            x -= s.get_width()
        target.blit(s, (int(x), int(y)))
        return s.get_width()


# ---------------------------------------------------------------------------
# Car sprites: 12 x 22, nose up. Every missing part is visibly missing.
# ---------------------------------------------------------------------------
def _bit(mask, slot):
    return mask & (1 << SLOT_INDEX[slot])


def make_car(kind, color_idx, mask, tuned, damage, phase, seed):
    s = pygame.Surface((12, 22), pygame.SRCALPHA)
    f = s.fill
    if kind == COP:
        body = (36, 36, 48)
    else:
        body = CAR_COLORS[color_idx % len(CAR_COLORS)]
    hi, lo = shade(body, 1.22), shade(body, 0.72)
    # body silhouette with nipped corners
    f(body, (1, 1, 10, 20))
    f(hi, (1, 2, 1, 18))
    f(lo, (10, 2, 1, 18))
    for (x, y) in ((1, 1), (10, 1), (1, 20), (10, 20)):
        s.set_at((x, y), (0, 0, 0, 0))
    # hood / engine bay
    if _bit(mask, "Hood"):
        if _bit(tuned, "Hood"):
            for yy in range(2, 7):
                for xx in range(2, 10):
                    s.set_at((xx, yy), (40, 40, 46) if (xx + yy) % 2 else (58, 58, 66))
        else:
            f(body, (2, 2, 8, 5))
            f(hi, (2, 2, 8, 1))
            f(lo, (2, 6, 8, 1))
    else:
        f(P["ink"], (2, 2, 8, 5))
        if _bit(mask, "Engine"):
            f(P["metal_l"], (4, 3, 4, 3))
            f(P["red"] if _bit(tuned, "Engine") else P["metal"], (4, 3, 4, 1))
    # windshield, roof, rear window, trunk
    f(P["glass"], (2, 7, 8, 2))
    f(shade(P["glass"], 1.15), (3, 7, 3, 1))
    if kind == TRAFFIC:                             # somebody's at the wheel: hands off
        f(HAIRS[seed % len(HAIRS)], (3, 8, 2, 1))
    roof = P["white"] if kind == COP else shade(body, 0.92)
    f(roof, (2, 9, 8, 6))
    f(P["glass_d"], (2, 15, 8, 2))
    f(body, (2, 17, 8, 3))
    f(hi, (2, 17, 8, 1))
    if kind == PERSONAL:                            # personal ride: racing stripes, obviously
        f((40, 90, 30), (5, 2, 1, 18) if _bit(mask, "Hood") else (5, 7, 1, 13))
        f((40, 90, 30), (6, 2, 1, 18) if _bit(mask, "Hood") else (6, 7, 1, 13))
    if kind == COP:                                 # light bar
        l_on, r_on = (phase == 0), (phase == 1)
        f(P["red"] if l_on else P["red_d"], (3, 11, 3, 2))
        f(P["blue"] if r_on else P["blue_d"], (6, 11, 3, 2))
        if l_on:
            f((255, 190, 190), (4, 11, 1, 1))
        if r_on:
            f((190, 210, 255), (7, 11, 1, 1))
    # doors: missing = a notch into the cabin with a seat peeking out
    seats = _bit(mask, "Seats")
    seat_c = P["red_d"] if _bit(tuned, "Seats") else P["wood_d"]
    for slot, x0, xi in (("DoorL", 1, 2), ("DoorR", 9, 9)):
        if _bit(mask, slot):
            dc = P["white"] if kind == COP else body
            f(dc, (x0, 9, 2, 5))
            f(lo, (x0, 8, 2, 1))
            f(lo, (x0, 14, 2, 1))
        else:
            f(P["ink"], (x0, 8, 2, 7))
            if seats:
                f(seat_c, (xi, 10, 1, 3))
    # lights
    f(P["light"], (2, 1, 2, 1))
    f(P["light"], (8, 1, 2, 1))
    f(P["red"], (2, 20, 2, 1))
    f(P["red"], (8, 20, 2, 1))
    # bumpers
    if _bit(mask, "BumperF"):
        if _bit(tuned, "BumperF"):
            f(P["ink2"], (2, 0, 8, 2))
            f(P["gold"], (3, 0, 6, 1))
        else:
            f(P["chrome"], (2, 0, 8, 1))
            f(P["rim"], (2, 1, 8, 1))
    if _bit(mask, "BumperR"):
        if _bit(tuned, "BumperR"):
            f(P["ink2"], (2, 20, 8, 2))
            f(P["gold"], (3, 21, 6, 1))
        else:
            f(P["rim"], (2, 20, 8, 1))
            f(P["chrome"], (2, 21, 8, 1))
    else:
        f(P["ink"], (2, 20, 8, 1))
    if _bit(mask, "Exhaust"):
        if _bit(tuned, "Exhaust"):
            f(P["chrome"], (2, 21, 2, 1))
            f(P["ink"], (2, 21, 1, 1))
        else:
            f(P["metal"], (3, 21, 1, 1))
    # wheels
    for slot, x, y in (("WheelFL", 0, 3), ("WheelFR", 10, 3), ("WheelRL", 0, 15), ("WheelRR", 10, 15)):
        if _bit(mask, slot):
            f(P["tire"], (x, y, 2, 4))
            rx = x if x == 0 else x + 1
            f(P["gold"] if _bit(tuned, slot) else P["rim"], (rx, y + 1, 1, 2))
        else:
            f(P["metal"], (x + (1 if x == 0 else 0), y + 1, 1, 2))    # bare hub. sparks incoming.
    # dents: darker pixels in a pattern that's stable per car
    if damage:
        rng = random.Random(seed * 31 + damage)
        for _ in range(damage * 5):
            x, y = rng.randrange(2, 10), rng.randrange(2, 20)
            c = s.get_at((x, y))
            if c.a:
                s.set_at((x, y), shade(c, 0.7))
    return s


def make_icon(size):
    """Square app icon: the hero hatchback on a dark badge with a gold rim.
    Used for the window icon and (via tools/make_icon.py) the exe icon.
    Integer nearest-neighbour scaling only -- smoothed pixel art looks like
    it went through a car wash."""
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    r = max(2, size // 6)
    pygame.draw.rect(s, P["ink"], (0, 0, size, size), border_radius=r)
    if size >= 24:
        pygame.draw.rect(s, P["gold"], (0, 0, size, size), max(1, size // 24), border_radius=r)
    car = make_car(PERSONAL, 0, (1 << len(SLOT_INDEX)) - 1, 0, 0, 0, 0)
    k = max(1, int((size * 0.86) // car.get_height()))
    big = pygame.transform.scale(car, (car.get_width() * k, car.get_height() * k))
    s.blit(big, ((size - big.get_width()) // 2, (size - big.get_height()) // 2))
    return s


# ---------------------------------------------------------------------------
# People (8x8, facing +x). Rotated at draw time.
# ---------------------------------------------------------------------------
def _outline(surf, color=(20, 18, 26, 255)):
    w, h = surf.get_size()
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        for x in range(w):
            if surf.get_at((x, y)).a:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and 0 <= yy < h and surf.get_at((xx, yy)).a > 200:
                    out.set_at((x, y), color)
                    break
    out.blit(surf, (0, 0))
    return out


def make_person(shirt, skin, hair, frame, extra=None):
    s = pygame.Surface((9, 9), pygame.SRCALPHA)
    f = s.fill
    f(shirt, (3, 1, 3, 7))                      # shoulders (across y since facing +x)
    f(shade(shirt, 0.8), (3, 1, 1, 7))
    # arms swing with the walk frame
    hx1, hx2 = (6, 4) if frame == 0 else (4, 6)
    f(skin, (hx1, 1, 1, 1))
    f(skin, (hx2, 7, 1, 1))
    f(hair, (3, 3, 3, 3))                       # head
    f(skin, (5, 3, 1, 3))                       # face towards +x
    if extra == "clown":
        f((255, 60, 60), (6, 4, 1, 1))          # nose
        f((255, 80, 80), (3, 2, 1, 1)); f((80, 200, 255), (3, 6, 1, 1)); f((255, 230, 60), (2, 4, 1, 1))
        f((230, 40, 40), (7, 1, 2, 2)); f((230, 40, 40), (7, 6, 2, 2))   # comedy shoes
    elif extra == "owner":
        f((255, 90, 90), (5, 3, 1, 3))          # face: furious
        f(skin, (7, 1, 1, 1))                   # fist, raised
    elif extra == "cuffed":
        f(P["chrome"], (2, 3, 1, 3))
    return _outline(s)


# ---------------------------------------------------------------------------
# The hand dolly (10x8, nose facing +x like people). Rotated at draw time.
# ---------------------------------------------------------------------------
def make_dolly():
    s = pygame.Surface((10, 8), pygame.SRCALPHA)
    f = s.fill
    f(P["metal_l"], (1, 1, 8, 1))              # rails
    f(P["metal_l"], (1, 6, 8, 1))
    f(P["metal"], (2, 2, 6, 4))                # deck
    f(P["chrome"], (8, 1, 2, 6))               # toe plate
    f(P["tire"], (5, 0, 3, 1))                 # wheels
    f(P["tire"], (5, 7, 3, 1))
    f(P["red"], (0, 1, 1, 1))                  # grips
    f(P["red"], (0, 6, 1, 1))
    return _outline(s)


# ---------------------------------------------------------------------------
# Part icons (8x8), unrotated so you can always tell what's on the floor
# ---------------------------------------------------------------------------
def make_part_icon(type_id):
    name, cat, bulk, value, power, tuned = PART_DEFS[type_id]
    s = pygame.Surface((8, 8), pygame.SRCALPHA)
    f = s.fill
    acc = P["gold"] if tuned else P["rim"]
    if cat == "wheel":
        pygame.draw.circle(s, P["tire"], (4, 4), 4)
        pygame.draw.circle(s, acc if tuned else (P["metal_l"] if "worn" in type_id else P["rim"]), (4, 4), 2)
        f(P["ink"], (4, 4, 1, 1))
    elif cat == "bumper":
        f(P["ink2"] if tuned else P["chrome"], (0, 3, 8, 3))
        f(acc if tuned else P["rim"], (0, 5, 8, 1))
        f(P["light"], (1, 3, 1, 1)); f(P["light"], (6, 3, 1, 1))
    elif cat == "door":
        f(P["metal_l"], (1, 0, 6, 8))
        f(P["glass"], (2, 1, 4, 3))
        f(P["ink"], (5, 5, 1, 1))
    elif cat == "hood":
        if tuned:
            for y in range(1, 7):
                for x in range(1, 7):
                    s.set_at((x, y), (40, 40, 46) if (x + y) % 2 else (64, 64, 72))
        else:
            f(P["metal_l"], (1, 1, 6, 6))
            f(P["chrome"], (1, 1, 6, 1))
    elif cat == "engine":
        f(P["metal"], (0, 2, 8, 5))
        f(P["red"] if tuned else P["metal_l"], (1, 1, 6, 2))
        for x in (1, 3, 5):
            f(P["ink"], (x + 1, 4, 1, 1))
    elif cat == "trans":
        f(P["metal_l"], (0, 2, 3, 4))
        f(P["metal"], (3, 3, 5, 2))
        f(acc, (7, 3, 1, 2))
    elif cat == "ecu":
        f(P["red_d"] if tuned else P["green_d"], (1, 2, 6, 4))
        f(P["ink"], (3, 3, 2, 2))
        for x in (1, 3, 5):
            f(P["gold"], (x, 1, 1, 1)); f(P["gold"], (x + 1, 6, 1, 1))
    elif cat == "exhaust":
        f(P["chrome"] if tuned else P["metal_l"], (0, 3, 8, 1))
        f(P["chrome"] if tuned else P["metal"], (3, 2, 4, 3))
        f(P["ink"], (7, 3, 1, 1))
    elif cat == "seat":
        c = P["red"] if tuned else P["wood_d"]
        f(c, (1, 3, 6, 4))
        f(shade(c, 1.2), (1, 1, 6, 2))
    return _outline(s)


# ---------------------------------------------------------------------------
# The city, pre-rendered once into one big surface (~2220 px square)
# ---------------------------------------------------------------------------
def render_map(cmap):
    T = C.TILE_PX
    n = cmap.n
    surf = pygame.Surface((n * T, n * T))
    rng = random.Random(cmap.seed * 7 + 1)
    base = {M.ROAD: P["asphalt"], M.SIDEWALK: P["sidewalk"], M.BUILDING: P["ink"], M.GRASS: P["grass"],
            M.TREE: P["grass"], M.WALL: P["wall"], M.GARAGE: P["concrete"], M.LOT: P["asphalt_l"]}
    speck = {M.ROAD: (P["asphalt_d"], P["asphalt_l"]), M.SIDEWALK: (P["sidewalk_d"], P["curb"]),
             M.GRASS: (P["grass_d"], P["grass_l"]), M.TREE: (P["grass_d"], P["grass_l"]),
             M.GARAGE: (P["concrete_d"], P["concrete_d"]), M.LOT: (P["asphalt"], P["asphalt_d"])}
    for ty in range(n):
        for tx in range(n):
            t = cmap.tiles[ty * n + tx]
            x, y = tx * T, ty * T
            surf.fill(base[t], (x, y, T, T))
            sp = speck.get(t)
            if sp:
                for _ in range(7):
                    surf.fill(sp[rng.random() < 0.5], (x + rng.randrange(T), y + rng.randrange(T), 1, 1))
            if t == M.SIDEWALK:
                # paving seams + curb lip where it meets the road
                surf.fill(P["sidewalk_d"], (x, y, T, 1))
                surf.fill(P["sidewalk_d"], (x, y, 1, T))
                if cmap.tile(tx, ty - 1) == M.ROAD: surf.fill(P["curb"], (x, y, T, 2))
                if cmap.tile(tx, ty + 1) == M.ROAD: surf.fill(P["curb"], (x, y + T - 2, T, 2))
                if cmap.tile(tx - 1, ty) == M.ROAD: surf.fill(P["curb"], (x, y, 2, T))
                if cmap.tile(tx + 1, ty) == M.ROAD: surf.fill(P["curb"], (x + T - 2, y, 2, T))
            elif t == M.WALL:
                surf.fill(P["wall_l"], (x, y, T, T - 4))
                surf.fill(P["wall"], (x, y + T - 4, T, 4))
                for k in range(0, T, 5):
                    surf.fill(P["wall"], (x + k, y + (k % 10), 1, 5))
    # ---- lane markings: dashed yellow centre lines, white stop bars, zebras
    P3 = C.PITCH
    for band in range(C.BLOCKS + 1):
        c = int((band * P3 + 1.5) * T)
        for blk in range(C.BLOCKS):
            a = (C.ROAD_TILES + blk * P3) * T
            b = a + C.BLOCK_TILES * T
            for k in range(a + 6, b - 6, 12):
                surf.fill(P["line_y"], (k, c - 1, 6, 2))       # horizontal road
                surf.fill(P["line_y"], (c - 1, k, 2, 6))       # vertical road
            # zebra crossings at both ends of each segment
            r0 = band * P3 * T
            for k in range(r0 + 3, r0 + 3 * T - 3, 4):
                surf.fill(P["line_w"], (a + 2, k, 6, 2))
                surf.fill(P["line_w"], (b - 8, k, 6, 2))
                surf.fill(P["line_w"], (k, a + 2, 2, 6))
                surf.fill(P["line_w"], (k, b - 8, 2, 6))
    # ---- parking lots
    for (tx, ty, tw, th) in cmap.lots:
        x0, y0 = tx * T, ty * T
        for k in range(7):
            xx = int(x0 + (0.8 + k * 4.4) * C.PPM)
            if xx > x0 + tw * T - 4:
                break
            surf.fill(P["line_w"], (xx, y0 + 2, 1, 26))
            surf.fill(P["line_w"], (xx, y0 + th * T - 28, 1, 26))
        surf.fill(P["oil"], (x0 + 30, y0 + 60, 5, 3))
    # ---- buildings: shadow, roof, parapet, rooftop junk
    shadow = pygame.Surface((8, 8), pygame.SRCALPHA)
    for (tx, ty, tw, th, style) in cmap.buildings:
        x, y, w, h = tx * T, ty * T, tw * T, th * T
        sh = pygame.Surface((w, h), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 70))
        surf.blit(sh, (x + 5, y + 5))
    for (tx, ty, tw, th, style) in cmap.buildings:
        x, y, w, h = tx * T, ty * T, tw * T, th * T
        roof = ROOF_COLORS[style % len(ROOF_COLORS)]
        brng = random.Random(tx * 1000 + ty + cmap.seed)
        surf.fill(shade(roof, 0.6), (x, y, w, h))
        surf.fill(roof, (x + 2, y + 2, w - 4, h - 4))
        surf.fill(shade(roof, 1.25), (x, y, w, 2))
        surf.fill(shade(roof, 1.25), (x, y, 2, h))
        surf.fill(shade(roof, 0.8), (x + 3, y + 3, w - 6, 1))
        for _ in range(w * h // 700):
            surf.fill(shade(roof, brng.choice((0.9, 1.1))),
                      (x + brng.randrange(4, w - 4), y + brng.randrange(4, h - 4), 2, 1))
        for _ in range(brng.randint(1, 4)):             # AC units
            ax, ay = x + brng.randrange(8, max(9, w - 16)), y + brng.randrange(8, max(9, h - 14))
            surf.fill((0, 0, 0), (ax + 2, ay + 2, 10, 7))
            surf.fill(P["rim"], (ax, ay, 10, 7))
            surf.fill(P["metal"], (ax + 2, ay + 2, 6, 3))
            surf.fill(P["chrome"], (ax, ay, 10, 1))
        for _ in range(brng.randint(0, 3)):             # vents
            vx, vy = x + brng.randrange(6, max(7, w - 8)), y + brng.randrange(6, max(7, h - 8))
            surf.fill(P["ink"], (vx, vy, 3, 3))
            surf.fill(P["metal_l"], (vx, vy, 3, 1))
        if brng.random() < 0.5:                          # skylight
            sx, sy = x + brng.randrange(10, max(11, w - 30)), y + brng.randrange(10, max(11, h - 24))
            surf.fill(P["glass_d"], (sx, sy, 18, 12))
            for k in range(0, 18, 6):
                surf.fill(P["glass"], (sx + k + 1, sy + 1, 4, 10))
        if brng.random() < 0.3:                          # water tank
            cx, cy = x + brng.randrange(16, max(17, w - 16)), y + brng.randrange(16, max(17, h - 16))
            pygame.draw.circle(surf, (0, 0, 0), (cx + 2, cy + 2), 7)
            pygame.draw.circle(surf, P["wood"], (cx, cy), 7)
            pygame.draw.circle(surf, P["wood_d"], (cx, cy), 7, 1)
            pygame.draw.circle(surf, P["wood_d"], (cx, cy), 3, 1)
    # ---- trees: blobby canopies with a shadow
    for ty in range(n):
        for tx in range(n):
            if cmap.tiles[ty * n + tx] == M.TREE:
                cx, cy = tx * T + T // 2, ty * T + T // 2
                pygame.draw.circle(surf, P["grass_d"], (cx + 3, cy + 3), 10)
                pygame.draw.circle(surf, P["tree_d"], (cx, cy), 10)
                pygame.draw.circle(surf, P["tree"], (cx - 1, cy - 1), 8)
                pygame.draw.circle(surf, P["tree_l"], (cx - 3, cy - 3), 4)
    # ---- lamp posts with a faint pool of light
    pool = pygame.Surface((14, 14), pygame.SRCALPHA)
    pygame.draw.circle(pool, (255, 240, 170, 28), (7, 7), 7)
    for (lx, ly) in cmap.lamps:
        px, py = int(lx * C.PPM), int(ly * C.PPM)
        surf.blit(pool, (px - 7, py - 7))
        surf.fill(P["ink"], (px - 1, py - 1, 3, 3))
        surf.fill(P["light"], (px, py, 1, 1))
    _render_garage(surf, cmap)
    return surf


def _render_garage(surf, cmap):
    S = C.PPM
    T = C.TILE_PX
    ox, oy, b, _ = cmap.garage_tiles
    gx, gy, gw, gh = cmap.garage_rect
    rng = random.Random(99)
    # floor seams + oil stains, because nobody here has ever mopped
    for k in range(0, int(gw * S), T):
        surf.fill(P["concrete_d"], (int(gx * S) + k, int(gy * S), 1, int(gh * S)))
    for k in range(0, int(gh * S), T):
        surf.fill(P["concrete_d"], (int(gx * S), int(gy * S) + k, int(gw * S), 1))
    for _ in range(9):
        x = int(gx * S) + rng.randrange(10, int(gw * S) - 20)
        y = int(gy * S) + rng.randrange(20, int(gh * S) - 10)
        pygame.draw.ellipse(surf, P["oil"], (x, y, rng.randrange(6, 14), rng.randrange(4, 8)))
    # delivery zone outline in yellow paint
    pygame.draw.rect(surf, P["line_y"], (int(gx * S), int(gy * S), int(gw * S), int(gh * S)), 1)
    # hazard stripes across the apron (door line)
    ay = int((gy + gh) * S)
    for k in range(int(gx * S), int((gx + gw) * S), 6):
        surf.fill(P["line_y"], (k, ay - 3, 3, 3))
        surf.fill(P["ink"], (k + 3, ay - 3, 3, 3))
    # dolly parking spot: dashed box, stencilled label
    dx, dy = cmap.dolly_spot
    x0, y0, w, h = int((dx - 1.3) * S), int((dy - 1.3) * S), int(2.6 * S), int(2.6 * S)
    for k in range(0, w, 3):
        surf.fill(P["line_y"], (x0 + k, y0, 2, 1))
        surf.fill(P["line_y"], (x0 + k, y0 + h - 1, 2, 1))
    for k in range(0, h, 3):
        surf.fill(P["line_y"], (x0, y0 + k, 1, 2))
        surf.fill(P["line_y"], (x0 + w - 1, y0 + k, 1, 2))
    # personal bay box
    bx, by, _ = cmap.bay
    pygame.draw.rect(surf, P["white"], (int((bx - 1.8) * S), int((by - 3.2) * S), int(3.6 * S), int(6.4 * S)), 1)
    font = PixelFont()
    font.draw(surf, "YOUR RIDE", int(bx * S), int((by + 3.6) * S), P["white"], None, align="center")
    font.draw(surf, "DOLLY", int(dx * S), int((dy + 1.7) * S), P["line_y"], None, align="center")
    font.draw(surf, "CHOP SHOP", int((gx + gw / 2) * S), int((gy + gh / 2) * S) - 4,
              shade(P["concrete"], 0.8), None, scale=2, align="center")
    font.draw(surf, "PARK STOLEN CARS INSIDE THE LINE", int((gx + gw / 2) * S), int((gy + gh / 2) * S) + 10,
              shade(P["concrete"], 0.8), None, align="center")
    # sell bench: wooden counter + cash register
    x, y, w, h = [int(v * S) for v in cmap.sell_bench]
    surf.fill((0, 0, 0), (x + 2, y + 2, w, h))
    surf.fill(P["wood"], (x, y, w, h))
    surf.fill(P["wood_d"], (x, y + h - 2, w, 2))
    surf.fill(P["metal"], (x + w - 9, y + 1, 7, 5))
    surf.fill(P["green"], (x + w - 8, y + 2, 5, 2))
    font.draw(surf, "$ SELL $", x + w // 2 - 4, y + h + 3, P["money"], (0, 0, 0), align="center")
    # tune-up bench: steel with a red toolbox
    x, y, w, h = [int(v * S) for v in cmap.tune_bench]
    surf.fill((0, 0, 0), (x + 2, y + 2, w, h))
    surf.fill(P["metal_l"], (x, y, w, h))
    surf.fill(P["metal"], (x, y + h - 2, w, 2))
    surf.fill(P["red"], (x + 2, y + 1, 8, 5))
    surf.fill(P["red_d"], (x + 2, y + 4, 8, 1))
    surf.fill(P["chrome"], (x + 14, y + 3, 9, 1))
    font.draw(surf, "TUNE-UP", x + w // 2, y + h + 3, P["gold"], (0, 0, 0), align="center")


def render_minimap(cmap, scale_div=2):
    n = cmap.n
    size = n // scale_div + 1
    mm = pygame.Surface((size, size))
    col = {M.ROAD: (92, 92, 104), M.SIDEWALK: (70, 68, 74), M.BUILDING: (34, 32, 44), M.GRASS: (50, 90, 50),
           M.TREE: (40, 76, 46), M.WALL: (120, 100, 90), M.GARAGE: (200, 170, 70), M.LOT: (80, 80, 92)}
    for ty in range(0, n, scale_div):
        for tx in range(0, n, scale_div):
            mm.set_at((tx // scale_div, ty // scale_div), col[cmap.tiles[ty * n + tx]])
    return mm


class SpriteBank:
    """Caches generated sprites and their rotations. Rotations are quantised
    to 64 steps for cars (5.6 deg) -- smooth enough, and it's a finite cache."""
    CAR_STEPS = 64
    PERSON_STEPS = 32

    def __init__(self):
        self.cars = {}
        self.car_rot = {}
        self.people = {}
        self.person_rot = {}
        self.icons = [make_part_icon(pid) for pid in PART_IDS]
        self.icons_small = [pygame.transform.scale(i, (6, 6)) for i in self.icons]
        self.dolly = make_dolly()
        self.dolly_rot = {}
        self.car_shadow = pygame.Surface((14, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(self.car_shadow, (0, 0, 0, 80), (0, 0, 14, 24))
        self.shadow_rot = {}

    def car(self, row, phase, ang):
        """A snapshot CAR row -> its top-down sprite at this angle."""
        (cid, kind, color, state, flags, mask, styles, x, y, vx, vy, _a, drv, psg, dmg,
         model, livery, extras, extras2) = row[:19]
        lights = (phase if kind == COP else 0) | (2 if flags & 1 and phase else 0) | (4 if extras & 8 else 0)
        key = (kind, color, mask, styles, dmg, lights, model, livery, extras & 0xF8, extras2 & 1)
        base = self.cars.get(key)
        if base is None:
            if len(self.cars) > 400:
                self.cars.clear()
                self.car_rot.clear()
            from . import fpart    # (fpart imports this module; import late to dodge the circle)
            base = self.cars[key] = fpart.topdown_car(kind, color, mask, styles, dmg, lights, model, livery,
                                                      extras, extras2, C.PPM)
        step = int(round((ang + math.pi / 2) / (2 * math.pi) * self.CAR_STEPS)) % self.CAR_STEPS
        rk = (key, step)
        r = self.car_rot.get(rk)
        if r is None:
            r = self.car_rot[rk] = pygame.transform.rotate(base, -step * 360.0 / self.CAR_STEPS)
        return r

    def dolly_at(self, ang):
        step = int(round(ang / (2 * math.pi) * 32)) % 32
        r = self.dolly_rot.get(step)
        if r is None:
            r = self.dolly_rot[step] = pygame.transform.rotate(self.dolly, -step * 360.0 / 32)
        return r

    def car_shadow_at(self, ang):
        step = int(round((ang + math.pi / 2) / (2 * math.pi) * 32)) % 32
        r = self.shadow_rot.get(step)
        if r is None:
            r = self.shadow_rot[step] = pygame.transform.rotate(self.car_shadow, -step * 360.0 / 32)
        return r

    def person(self, key, ang):
        """key = (shirt, skin, hair, frame, extra)"""
        base = self.people.get(key)
        if base is None:
            base = self.people[key] = make_person(*key)
        step = int(round(ang / (2 * math.pi) * self.PERSON_STEPS)) % self.PERSON_STEPS
        rk = (key, step)
        r = self.person_rot.get(rk)
        if r is None:
            if len(self.person_rot) > 3000:
                self.person_rot.clear()
            r = self.person_rot[rk] = pygame.transform.rotate(base, -step * 360.0 / self.PERSON_STEPS)
        return r

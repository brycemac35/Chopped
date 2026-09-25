"""
fpart.py -- art for the first-person (Doom-style) view. Like art.py, every
pixel is generated right here: building facades, brick, skies, and a tiny
box-model renderer that turns a list of coloured boxes into car and person
sprites seen from 16 (or 8) angles. No asset files. id Software had a whole
art team; we have for-loops.
"""

import math
import random

import pygame

from .art import P, ROOF_COLORS, CAR_COLORS, PLAYER_COLORS, SKINS, shade
from .parts import SLOT_INDEX
from .sim import PERSONAL, COP

TEX = 32            # texture pixels per 4 m tile face (8 px per metre, both ways)
FLOOR_M = 4.0       # one storey
SHADES = 14         # distance/darkness levels per wall texture

WINDOW_LIT = [(255, 214, 120), (255, 236, 170), (220, 240, 255), (255, 190, 110)]
AWNINGS = [(180, 40, 50), (40, 110, 70), (40, 70, 150), (200, 150, 40), (120, 50, 120), (30, 30, 36)]
GRAFFITI = [(236, 90, 206), (80, 220, 230), (250, 232, 80), (255, 110, 60), (120, 230, 110)]


def _noise(surf, rng, colors, n):
    w, h = surf.get_size()
    for _ in range(n):
        surf.set_at((rng.randrange(w), rng.randrange(h)), rng.choice(colors))


# ---------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------
def facade(style, floors, variant, night):
    """One 4 m wide slice of a building: shop front at street level, windows
    above, a parapet on top. Seeded per (style, variant) so a building's
    tiles match but the street doesn't look copy-pasted."""
    rng = random.Random(style * 131 + variant * 7 + floors)
    base = ROOF_COLORS[style % len(ROOF_COLORS)]
    wall = shade(base, 0.95 if not night else 0.55)
    dark, light = shade(wall, 0.78), shade(wall, 1.12)
    h = TEX * floors
    s = pygame.Surface((TEX, h))
    s.fill(wall)
    _noise(s, rng, (dark, light), TEX * floors * 2)
    # brick courses
    for y in range(0, h, 4):
        s.fill(dark, (0, y, TEX, 1))
    glass = P["glass_d"] if not night else (26, 30, 48)
    lit_rng = random.Random(style * 977 + variant * 31)
    for f in range(floors):
        top = h - TEX * (f + 1)
        s.fill(shade(wall, 0.65), (0, top + TEX - 2, TEX, 2))      # floor slab line
        if f == 0:
            # street level: awning, shop window, door
            aw = AWNINGS[(style + variant) % len(AWNINGS)]
            if variant == 2:
                s.fill(shade(wall, 0.7), (1, top + 6, 30, 26))          # roller shutter
                for y in range(top + 7, top + 32, 2):
                    s.fill(shade(wall, 0.55), (1, y, 30, 1))
                col = rng.choice(GRAFFITI)
                for k in range(9):                                    # a tag. Art.
                    s.fill(col, (5 + k * 2 + rng.randrange(2), top + 14 + rng.randrange(8), 2, 2))
            else:
                s.fill(aw, (0, top + 3, TEX, 4))
                for x in range(0, TEX, 4):
                    s.fill(shade(aw, 1.3), (x, top + 3, 2, 4))
                win = (WINDOW_LIT[variant % 4] if night else P["glass"])
                s.fill(P["ink"], (2, top + 9, 19, 17))
                s.fill(win, (3, top + 10, 17, 15))
                s.fill(shade(win, 1.15) if not night else win, (3, top + 10, 17, 3))
                s.fill(P["wood_d"], (23, top + 11, 7, 21))                # door
                s.fill(P["gold"], (28, top + 21, 1, 2))
        else:
            for wx in (4, 18):
                lit = night and lit_rng.random() < 0.45
                c = rng.choice(WINDOW_LIT) if lit else glass
                s.fill(P["ink"], (wx - 1, top + 8, 12, 15))
                s.fill(c, (wx, top + 9, 10, 13))
                s.fill(shade(c, 0.8), (wx, top + 15, 10, 1))
                if not lit and not night:
                    s.fill(P["glass"], (wx + 1, top + 10, 3, 2))           # sky glint
                s.fill(light, (wx - 1, top + 22, 12, 1))                   # sill
    s.fill(shade(wall, 0.6), (0, 0, TEX, 3))                              # parapet
    s.fill(light, (0, 3, TEX, 1))
    return s


def brick_wall(height_px, night, sign=None):
    s = pygame.Surface((TEX, height_px))
    base = P["wall_l"] if not night else shade(P["wall_l"], 0.6)
    s.fill(base)
    mortar = shade(base, 0.7)
    for y in range(0, height_px, 4):
        s.fill(mortar, (0, y, TEX, 1))
        off = 0 if (y // 4) % 2 else 4
        for x in range(off, TEX, 8):
            s.fill(mortar, (x, y, 1, 4))
    if sign:
        s.fill(P["ink"], (0, 10, TEX, 14))
        s.fill(P["gold"], (0, 11, TEX, 1))
        s.fill(P["gold"], (0, 22, TEX, 1))
    return s


def concrete_wall(height_px, night):
    s = pygame.Surface((TEX, height_px))
    base = P["concrete"] if not night else shade(P["concrete"], 0.55)
    s.fill(base)
    rng = random.Random(5)
    _noise(s, rng, (shade(base, 0.85), shade(base, 1.1)), TEX * height_px // 6)
    for y in range(0, height_px, 16):
        s.fill(shade(base, 0.75), (0, y, TEX, 1))
    s.fill(shade(base, 0.75), (0, 0, 1, height_px))
    for x in range(0, TEX, 4):                                            # razor wire
        s.fill(P["metal_l"], (x, 0, 2, 2))
    s.fill(P["line_y"], (0, height_px - 10, TEX, 3))                      # hazard stripe
    for x in range(0, TEX, 8):
        s.fill(P["ink"], (x, height_px - 10, 4, 3))
    return s


class WallTex:
    """A wall texture pre-shaded at SHADES darkness levels, sliced into
    1-pixel columns so the raycaster just picks one and scales it."""
    __slots__ = ("h", "cols")

    def __init__(self, surf):
        surf = surf.convert()
        self.h = surf.get_height()
        self.cols = []
        for k in range(SHADES):
            f = int(255 * max(0.12, 1.0 - k * 0.068))
            lv = surf.copy()
            lv.fill((f, f, f), special_flags=pygame.BLEND_MULT)
            self.cols.append([lv.subsurface((u, 0, 1, self.h)) for u in range(TEX)])


# ---------------------------------------------------------------------------
# Sky
# ---------------------------------------------------------------------------
SKY_KEYS = ("dawn", "day", "dusk", "night")
SKY_GRAD = {
    "dawn": ((70, 80, 140), (240, 150, 120)),
    "day": ((70, 120, 200), (170, 205, 235)),
    "dusk": ((50, 40, 90), (230, 110, 70)),
    "night": ((8, 8, 22), (30, 30, 60)),
}


def make_sky(kind, width, height):
    """A 360-degree panorama: gradient, clouds (or stars), and a hazy skyline
    far away so long streets don't end in a flat colour."""
    top, bot = SKY_GRAD[kind]
    s = pygame.Surface((width, height))
    for y in range(height):
        t = y / max(1, height - 1)
        s.fill(tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)), (0, y, width, 1))
    rng = random.Random(hash(kind) & 0xFFFF)
    if kind == "night":
        for _ in range(width // 5):
            c = rng.choice(((255, 255, 255), (200, 200, 255), (255, 240, 200)))
            s.set_at((rng.randrange(width), rng.randrange(int(height * 0.8))), c)
        mx = width // 3
        pygame.draw.circle(s, (240, 240, 220), (mx, height // 4), 6)          # moon
        pygame.draw.circle(s, top, (mx + 3, height // 4 - 2), 5)
    else:
        cloud = shade(bot, 1.12) if kind != "dusk" else (250, 170, 140)
        for _ in range(width // 60):
            cx, cy = rng.randrange(width), rng.randrange(8, max(9, height // 2))
            for k in range(6):
                w = rng.randrange(18, 40)
                s.fill(cloud, (cx + rng.randrange(-20, 20), cy + rng.randrange(-3, 4), w, 3))
    # distant skyline silhouette
    sil = shade(bot, 0.55) if kind != "night" else (18, 18, 36)
    x = 0
    while x < width:
        w = rng.randrange(8, 26)
        hgt = rng.randrange(6, max(7, height // 4))
        s.fill(sil, (x, height - hgt, w, hgt))
        if kind in ("night", "dusk"):
            for _ in range(w * hgt // 30):
                s.set_at((x + rng.randrange(w), height - rng.randrange(1, hgt)), rng.choice(WINDOW_LIT))
        x += w
    return s.convert()


# ---------------------------------------------------------------------------
# Box models -> sprites
# ---------------------------------------------------------------------------
FACES = (((1, 0, 0), "+x"), ((-1, 0, 0), "-x"), ((0, 1, 0), "+y"), ((0, -1, 0), "-y"),
         ((0, 0, 1), "+z"), ((0, 0, -1), "-z"))


def render_boxes(boxes, az, ppm, el=0.24):
    """Draw axis-aligned boxes (x0, x1, y0, y1, z0, z1, colour or {face: colour})
    as seen from direction az (model frame, x forward, y right, z up), looking
    down by el. Orthographic, painter's algorithm, flat shading, 1 px outline.
    Returns (surface, anchor_x, anchor_y) where the anchor is the model origin
    on the ground -- that's the point the renderer plants on the floor."""
    ca, sa, ce, se = math.cos(az), math.sin(az), math.cos(el), math.sin(el)
    f = (ca * ce, sa * ce, -se)
    r = (-sa, ca, 0.0)
    u = (f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0])
    light = (-f[0] * 0.3 + u[0] * 0.8 - r[0] * 0.5, -f[1] * 0.3 + u[1] * 0.8 - r[1] * 0.5,
             -f[2] * 0.3 + u[2] * 0.8 - r[2] * 0.5)
    ln = math.sqrt(sum(v * v for v in light))
    light = tuple(v / ln for v in light)

    def proj(p):
        return (p[0] * r[0] + p[1] * r[1] + p[2] * r[2]) * ppm, -(p[0] * u[0] + p[1] * u[1] + p[2] * u[2]) * ppm

    polys = []
    xs, ys = [0.0], [0.0]
    for box in boxes:
        x0, x1, y0, y1, z0, z1, col = box
        for n, key in FACES:
            if n[0] * f[0] + n[1] * f[1] + n[2] * f[2] > -1e-6:
                continue                      # facing away
            if key == "+x":
                q = ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))
            elif key == "-x":
                q = ((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1))
            elif key == "+y":
                q = ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1))
            elif key == "-y":
                q = ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
            elif key == "+z":
                q = ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
            else:
                q = ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0))
            c = col.get(key, col.get("*")) if isinstance(col, dict) else col
            if c is None:
                continue
            k = 0.6 + 0.4 * max(0.0, n[0] * light[0] + n[1] * light[1] + n[2] * light[2])
            cx = (x0 + x1) / 2 + n[0] * (x1 - x0) / 2
            cy = (y0 + y1) / 2 + n[1] * (y1 - y0) / 2
            cz = (z0 + z1) / 2 + n[2] * (z1 - z0) / 2
            depth = cx * f[0] + cy * f[1] + cz * f[2]
            pts = [proj(p) for p in q]
            xs.extend(p[0] for p in pts)
            ys.extend(p[1] for p in pts)
            polys.append((depth, pts, shade(c, k)))
    pad = 2
    minx, miny = math.floor(min(xs)) - pad, math.floor(min(ys)) - pad
    w, h = int(math.ceil(max(xs)) - minx + pad), int(math.ceil(max(ys)) - miny + pad)
    surf = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
    polys.sort(key=lambda t: -t[0])
    for _, pts, c in polys:
        pts = [(x - minx, y - miny) for x, y in pts]
        pygame.draw.polygon(surf, c, pts)
        pygame.draw.polygon(surf, shade(c, 0.6), pts, 1)
    return surf, -minx, -miny


def _bit(mask, slot):
    return mask & (1 << SLOT_INDEX[slot])


def car_boxes(kind, color, mask, tuned, damage, lights):
    """The Kei as a stack of boxes. Every strippable part is its own box, so a
    stripped car looks stripped from every angle."""
    body = (36, 36, 48) if kind == COP else CAR_COLORS[color % len(CAR_COLORS)]
    if damage:
        body = shade(body, 1.0 - 0.1 * damage)
    door = P["white"] if kind == COP else body
    hole = P["ink"]
    b = []
    hood_top = body if _bit(mask, "Hood") else hole
    if _bit(mask, "Hood") and _bit(tuned, "Hood"):
        hood_top = (48, 48, 56)
    b.append((0.8, 2.2, -1.1, 1.1, 0.3, 1.0, {"*": body, "+z": hood_top}))               # nose
    b.append((-2.2, -1.4, -1.1, 1.1, 0.3, 1.0, body))                                     # tail
    b.append((-1.4, 0.8, -1.1, 1.1, 0.3, 1.0, {"*": body,                                 # doors
                                               "-y": door if _bit(mask, "DoorL") else hole,
                                               "+y": door if _bit(mask, "DoorR") else hole}))
    if not _bit(mask, "Hood") and _bit(mask, "Engine"):
        eng = P["red"] if _bit(tuned, "Engine") else P["metal_l"]
        b.append((1.0, 2.0, -0.6, 0.6, 0.6, 1.02, {"*": P["metal"], "+z": eng}))
    roof = P["white"] if kind == COP else shade(body, 0.92)
    b.append((-1.4, 0.7, -0.95, 0.95, 1.0, 1.58, {"*": P["glass"], "+z": roof, "-x": P["glass_d"],
                                                 "-z": None}))
    if kind == PERSONAL:                                                                  # racing stripes
        b.append((0.8, 2.2, -0.22, 0.22, 1.0, 1.02, (40, 90, 30)))
        b.append((-1.4, 0.7, -0.22, 0.22, 1.58, 1.6, (40, 90, 30)))
    if kind == COP:
        l_on = lights & 1
        b.append((-0.5, 0.1, -0.7, 0.0, 1.58, 1.74, P["red"] if l_on else P["red_d"]))
        b.append((-0.5, 0.1, 0.0, 0.7, 1.58, 1.74, P["blue_d"] if l_on else P["blue"]))
    if _bit(mask, "BumperF"):
        c = P["ink2"] if _bit(tuned, "BumperF") else P["chrome"]
        b.append((2.2, 2.35, -1.05, 1.05, 0.3, 0.55, {"*": c, "+z": P["gold"] if _bit(tuned, "BumperF") else c}))
    if _bit(mask, "BumperR"):
        c = P["ink2"] if _bit(tuned, "BumperR") else P["chrome"]
        b.append((-2.35, -2.2, -1.05, 1.05, 0.3, 0.55, c))
    if _bit(mask, "Exhaust"):
        b.append((-2.45, -2.2, -0.8, -0.6, 0.3, 0.45, P["chrome"] if _bit(tuned, "Exhaust") else P["metal"]))
    hazard = (255, 170, 40) if lights & 2 else None
    front = hazard or P["light"]
    rear = hazard or P["red"]
    for y0, y1 in ((-0.95, -0.55), (0.55, 0.95)):
        b.append((2.2, 2.24, y0, y1, 0.72, 0.88, front))
        b.append((-2.24, -2.2, y0, y1, 0.72, 0.88, rear))
    for slot, x, y in (("WheelFL", 1.35, -1), ("WheelFR", 1.35, 1), ("WheelRL", -1.35, -1), ("WheelRR", -1.35, 1)):
        if _bit(mask, slot):
            rim = P["gold"] if _bit(tuned, slot) else P["rim"]
            outer = "+y" if y > 0 else "-y"
            y0, y1 = (0.85, 1.2) if y > 0 else (-1.2, -0.85)
            b.append((x - 0.35, x + 0.35, y0, y1, 0.0, 0.62, {"*": P["tire"], outer: rim}))
        else:
            y0, y1 = (0.95, 1.1) if y > 0 else (-1.1, -0.95)
            b.append((x - 0.12, x + 0.12, y0, y1, 0.18, 0.42, P["metal"]))
    return b


def person_boxes(shirt, skin, hair, frame, extra=None, pants=(52, 56, 78)):
    """A little blocky crook, about 1.75 m, facing +x. frame 0/1 = legs
    together/apart for the walk cycle."""
    swing = 0.16 if frame else 0.0
    shoe = (30, 26, 30)
    b = []
    if extra == "clown":
        shoe, pants = (230, 40, 40), (80, 200, 255)
    for side, s in ((-1, 1), (1, -1)):
        lx = s * swing
        b.append((lx - 0.09, lx + 0.09, side * 0.2 if side < 0 else 0.03, -0.03 if side < 0 else side * 0.2,
                  0.08, 0.82, pants))
        big = 0.12 if extra == "clown" else 0.0
        b.append((lx - 0.1, lx + 0.14 + big, side * 0.21 if side < 0 else 0.02, -0.02 if side < 0 else side * 0.21,
                  0.0, 0.1, shoe))
    b.append((-0.13, 0.13, -0.24, 0.24, 0.8, 1.4, shirt))                                 # torso
    for side in (-1, 1):
        y0, y1 = (-0.35, -0.24) if side < 0 else (0.24, 0.35)
        if extra == "cuffed":
            b.append((-0.26, -0.12, y0 + side * -0.05, y1 + side * -0.05, 0.9, 1.35, shirt))
        elif extra == "owner" and side > 0:
            b.append((-0.06, 0.08, y0, y1, 1.3, 1.95, shirt))                             # fist in the air
            b.append((-0.06, 0.08, y0, y1, 1.85, 1.98, skin))
        else:
            sw = -side * swing * 0.8
            b.append((sw - 0.07, sw + 0.07, y0, y1, 0.9, 1.38, shirt))
            b.append((sw - 0.06, sw + 0.06, y0, y1, 0.8, 0.9, skin))
    b.append((-0.14, 0.14, -0.13, 0.13, 1.42, 1.72, skin))                                # head
    b.append((0.14, 0.15, -0.08, -0.03, 1.56, 1.61, P["ink"]))                            # eyes
    b.append((0.14, 0.15, 0.03, 0.08, 1.56, 1.61, P["ink"]))
    if extra == "clown":
        b.append((0.15, 0.2, -0.03, 0.03, 1.5, 1.56, (255, 40, 40)))                      # honk
        b.append((-0.2, 0.1, -0.24, 0.24, 1.6, 1.84, (255, 110, 40)))                     # wig
    else:
        b.append((-0.16, 0.08, -0.15, 0.15, 1.66, 1.78, hair))
        b.append((-0.16, -0.12, -0.15, 0.15, 1.46, 1.7, hair))
    return b


def lying(boxes):
    """Rotate a standing model 90 degrees so it's flat on its back (tumbling)."""
    out = []
    for x0, x1, y0, y1, z0, z1, c in boxes:
        out.append((-z1 + 0.9, -z0 + 0.9, y0, y1, x0 + 0.2, x1 + 0.2, c))
    return out


def dolly_boxes():
    return [(-0.45, 0.45, -0.3, -0.24, 0.1, 1.0, P["metal_l"]), (-0.45, 0.45, 0.24, 0.3, 0.1, 1.0, P["metal_l"]),
            (-0.45, 0.45, -0.3, 0.3, 0.1, 0.16, P["metal"]), (0.45, 0.6, -0.3, 0.3, 0.0, 0.08, P["chrome"]),
            (-0.1, 0.2, -0.38, -0.3, 0.0, 0.25, P["tire"]), (-0.1, 0.2, 0.3, 0.38, 0.0, 0.25, P["tire"]),
            (-0.5, -0.4, -0.3, 0.3, 0.95, 1.05, P["red"])]


def bench_boxes(is_sell, length, depth):
    hl, hd = length / 2, depth / 2
    if is_sell:
        return [(-hd, hd, -hl, hl, 0.0, 1.0, {"*": P["wood"], "+z": shade(P["wood"], 1.15)}),
                (-hd * 0.7, hd * 0.2, hl - 1.6, hl - 0.4, 1.0, 1.45, {"*": P["metal"], "+x": P["green"]})]
    return [(-hd, hd, -hl, hl, 0.0, 0.95, {"*": P["metal_l"], "+z": shade(P["metal_l"], 1.2)}),
            (-hd * 0.6, hd * 0.6, -hl + 0.4, -hl + 2.0, 0.95, 1.4, P["red"]),
            (-hd * 0.2, hd * 0.2, 0.0, 1.5, 0.95, 1.02, P["chrome"])]


# ---------------------------------------------------------------------------
# Flat billboards (the same from every side)
# ---------------------------------------------------------------------------
def make_tree(rng):
    s = pygame.Surface((48, 66), pygame.SRCALPHA)
    s.fill(P["wood_d"], (21, 38, 6, 28))
    s.fill(P["wood"], (22, 38, 2, 28))
    for (x, y, r, c) in ((24, 24, 20, P["tree_d"]), (18, 20, 13, P["tree"]), (30, 18, 12, P["tree"]),
                         (24, 12, 11, P["tree_l"]), (16, 26, 8, P["tree"]), (33, 28, 9, P["tree_d"])):
        pygame.draw.circle(s, c, (x + rng.randrange(-2, 3), y + rng.randrange(-2, 3)), r)
    for _ in range(40):
        s.set_at((rng.randrange(8, 40), rng.randrange(4, 38)), P["grass_l"])
    return s, 24, 66


def make_lamp(night):
    s = pygame.Surface((12, 50), pygame.SRCALPHA)
    s.fill(P["metal"], (5, 6, 2, 44))
    s.fill(P["metal_l"], (5, 6, 1, 44))
    s.fill(P["metal"], (2, 3, 9, 3))
    s.fill(P["light"] if night else (200, 196, 170), (3, 6, 7, 2))
    if night:
        glow = pygame.Surface((12, 12), pygame.SRCALPHA)
        pygame.draw.circle(glow, (255, 240, 170, 90), (6, 6), 6)
        s.blit(glow, (0, 2))
    return s, 6, 50


def make_camera_pole():
    s = pygame.Surface((12, 36), pygame.SRCALPHA)
    s.fill(P["metal"], (5, 8, 2, 28))
    s.fill(P["ink"], (2, 3, 9, 5))
    s.fill(P["metal_l"], (2, 3, 9, 1))
    s.fill(P["red"], (9, 5, 1, 1))
    return s, 6, 36


# ---------------------------------------------------------------------------
# The HUD face: our crook, getting more stressed as the heat rises
# ---------------------------------------------------------------------------
def make_face(mood, look, color_idx, t_flash=0):
    """26x30. mood: calm / tense / sweaty / panic / grin / dazed / busted /
    winded. look: -1, 0, 1 (eyes left/centre/right, like a certain space marine)."""
    s = pygame.Surface((26, 30), pygame.SRCALPHA)
    f = s.fill
    skin = SKINS[1]
    if mood in ("sweaty", "panic"):
        skin = (226, 150, 118)
    beanie = PLAYER_COLORS[color_idx % 4]
    f(shade(skin, 0.8), (4, 9, 18, 19))
    f(skin, (5, 8, 16, 19))
    f(shade(skin, 1.08), (6, 9, 6, 6))
    f(beanie, (3, 2, 20, 8))                                  # beanie
    f(shade(beanie, 0.75), (3, 8, 20, 2))
    f(shade(beanie, 1.2), (5, 3, 6, 2))
    f(P["white"], (11, 0, 4, 3))                              # pom-pom
    f(shade(skin, 0.65), (5, 22, 16, 5))                      # stubble
    f(shade(skin, 0.8), (3, 14, 2, 5))                        # ears
    f(shade(skin, 0.8), (21, 14, 2, 5))
    if mood == "dazed":
        for cx in (9, 16):
            f(P["ink"], (cx - 1, 13, 1, 1)); f(P["ink"], (cx + 1, 13, 1, 1))
            f(P["ink"], (cx, 14, 1, 1))
            f(P["ink"], (cx - 1, 15, 1, 1)); f(P["ink"], (cx + 1, 15, 1, 1))
        f(P["gold"], (2, 1, 2, 2)); f(P["gold"], (22, 4, 2, 2))
    else:
        wide = mood in ("panic", "sweaty")
        for bx in (7, 15):
            f(P["white"], (bx, 12, 4, 4 if wide else 3))
            f(P["ink"], (bx + 1 + look, 13, 2, 2))
        # brows
        if mood in ("tense", "sweaty", "panic"):
            f(P["ink"], (6, 10, 5, 1)); f(P["ink"], (15, 10, 5, 1))
            f(P["ink"], (10, 9, 1, 1)); f(P["ink"], (15, 9, 1, 1))
        elif mood == "grin":
            f(P["ink"], (6, 9, 5, 1)); f(P["ink"], (15, 9, 5, 1))
            f(P["ink"], (6, 10, 1, 1)); f(P["ink"], (19, 10, 1, 1))
        else:
            f(P["ink"], (7, 10, 4, 1)); f(P["ink"], (15, 10, 4, 1))
    f(shade(skin, 0.75), (12, 15, 2, 4))                      # nose
    # mouth
    if mood == "grin":
        f(P["ink"], (8, 21, 10, 3)); f(P["white"], (9, 21, 8, 1))
        f(P["ink"], (7, 20, 1, 1)); f(P["ink"], (18, 20, 1, 1))
    elif mood == "panic":
        f(P["ink"], (10, 20, 6, 5)); f(P["red_d"], (11, 23, 4, 1))
    elif mood in ("sweaty", "tense"):
        f(P["ink"], (9, 22, 8, 1)); f(P["ink"], (8, 23, 1, 1)); f(P["ink"], (17, 23, 1, 1))
    elif mood == "winded":
        f(P["ink"], (10, 21, 6, 3)); f((230, 90, 110), (12, 23, 3, 3))
    elif mood == "busted":
        f(P["ink"], (9, 23, 8, 1)); f(P["ink"], (8, 22, 1, 1)); f(P["ink"], (17, 22, 1, 1))
    else:
        f(P["ink"], (9, 22, 8, 1)); f(P["ink"], (17, 21, 1, 1))  # smirk
    if mood in ("sweaty", "panic", "winded"):
        f((150, 200, 255), (4, 11, 1, 3)); f((150, 200, 255), (21, 15, 1, 3))
    if mood == "busted":
        for x in range(1, 26, 5):
            f(P["metal_l"], (x, 0, 2, 30)); f(P["chrome"], (x, 0, 1, 30))
    if t_flash:
        tint = pygame.Surface((26, 30), pygame.SRCALPHA)
        tint.fill((255, 60, 60, 60) if t_flash == 1 else (70, 120, 255, 60))
        s.blit(tint, (0, 0))
    return s

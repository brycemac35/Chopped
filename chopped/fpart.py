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
from .sim import COP
from . import vehicles as V

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


def precinct_wall(height_px, night):
    """The police station: pale concrete, a blue stripe, barred windows. Cheerful."""
    s = pygame.Surface((TEX, height_px))
    base = (196, 198, 206) if not night else (104, 106, 118)
    s.fill(base)
    rng = random.Random(8)
    _noise(s, rng, (shade(base, 0.9), shade(base, 1.06)), TEX * height_px // 8)
    s.fill((40, 70, 170) if not night else (26, 44, 110), (0, height_px - 22, TEX, 5))
    for y in range(0, height_px, 16):
        s.fill(shade(base, 0.8), (0, y, TEX, 1))
    wy = 30
    s.fill((30, 34, 44), (8, wy, 16, 12))                                  # a window...
    for x in range(9, 24, 3):
        s.fill((150, 150, 160), (x, wy, 1, 12))                            # ...with bars
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


def roller_door(panel, night):
    """(v0.9) One 4 m bay of the chop shop's roller door: galvanised slats, guide rails
    each side, a kick bar and a handle at the bottom, and somebody's tag."""
    h = 48
    s = pygame.Surface((TEX, h))
    base = (150, 152, 160) if not night else (88, 90, 100)
    s.fill(base)
    for y in range(0, h, 3):
        s.fill(shade(base, 0.78), (0, y, TEX, 1))
        s.fill(shade(base, 1.08), (0, y + 1, TEX, 1))
    rail = shade(base, 0.45)
    s.fill(rail, (0, 0, 2, h))
    s.fill(rail, (TEX - 2, 0, 2, h))
    s.fill((56, 56, 62), (0, h - 3, TEX, 3))                             # the kick bar
    s.fill(P["line_y"], (2, h - 6, TEX - 4, 2))                          # hazard stripe
    for x in range(2, TEX - 2, 6):
        s.fill(P["ink"], (x, h - 6, 3, 2))
    s.fill((40, 40, 46), (TEX // 2 - 3, h - 9, 6, 2))                    # the handle
    rng = random.Random(panel * 17 + 3)
    if panel in (0, 5, 6) or rng.random() < 0.3:
        col = GRAFFITI[rng.randrange(len(GRAFFITI))]
        x, y = rng.randrange(4, 18), rng.randrange(8, 26)
        for _ in range(26):                                             # a tag. It says "DAVE". Probably.
            s.fill(col if not night else shade(col, 0.6), (x, y, 2, 2))
            x = max(3, min(TEX - 5, x + rng.choice((-2, 0, 2, 2))))
            y = max(4, min(h - 12, y + rng.choice((-2, -1, 1, 2))))
    return s


def roof_texture(w_m, h_m, ppm):
    """(v0.9) The underside of the shop's roof, seen from below: corrugated steel,
    I-beams every 4 m, fluorescent tubes (two of them flickering, obviously), and a
    skylight nobody has cleaned since 1994. Colour (255, 0, 255) = no roof."""
    w, h = int(w_m * ppm), int(h_m * ppm)
    s = pygame.Surface((w, h))
    base = (82, 84, 94)
    s.fill(base)
    for x in range(0, w, 2):
        s.fill(shade(base, 0.8), (x, 0, 1, h))                           # the corrugations
    beam = (40, 40, 48)
    step = int(4 * ppm)
    for y in range(0, h + 1, step):
        s.fill(beam, (0, y - 2, w, 4))
        s.fill(shade(beam, 1.5), (0, y - 2, w, 1))
    for x in range(0, w + 1, step * 2):
        s.fill(beam, (x - 1, 0, 3, h))
    rng = random.Random(1994)
    for y in range(step // 2, h, step):
        for x in range(step // 2, w - step // 2, step * 2):
            lw, lh = int(1.4 * ppm), max(2, int(0.25 * ppm))
            s.fill((150, 160, 170), (x - lw // 2 - 1, y - lh // 2 - 1, lw + 2, lh + 2))
            s.fill((235, 245, 255) if rng.random() > 0.15 else (120, 130, 140), (x - lw // 2, y - lh // 2, lw, lh))
    sx, sy = int(w * 0.62), int(h * 0.3)
    s.fill((60, 62, 70), (sx - 1, sy - 1, int(2.5 * ppm) + 2, int(2.5 * ppm) + 2))
    s.fill((150, 170, 170), (sx, sy, int(2.5 * ppm), int(2.5 * ppm)))    # the skylight (grubby)
    _noise(s, rng, ((90, 100, 96), (120, 130, 120)), int(ppm * ppm * 2))
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


def render_boxes(boxes, az, ppm, el=0.24, outline=True):
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
        if outline:
            pygame.draw.polygon(surf, shade(c, 0.6), pts, 1)
    return surf, -minx, -miny


def topdown_car(kind, color, mask, styles, damage, lights, model, livery, extras, extras2, ppm):
    """The automap's car sprite: the same boxes, seen from straight above,
    nose pointing up the screen (so the old rotation code still works)."""
    boxes = car_boxes(kind, color, mask, styles, damage, lights, model, livery, extras, extras2)
    surf, ax, ay = render_boxes(boxes, 0.0, ppm, el=math.pi / 2 - 1e-3, outline=False)
    # re-centre on the car's middle so rotating the sprite spins it about the right point
    w, h = surf.get_size()
    hw_, hh_ = int(math.ceil(max(ax, w - ax))), int(math.ceil(max(ay, h - ay)))
    out = pygame.Surface((2 * hw_, 2 * hh_), pygame.SRCALPHA)
    out.blit(surf, (hw_ - int(round(ax)), hh_ - int(round(ay))))
    return out


def _bit(mask, slot):
    return mask & (1 << SLOT_INDEX[slot])


# wheel styles (vehicles.STYLES["wheel"]): (rim face, hub cap, tyre side)
WHEEL_LOOK = [((150, 150, 160), (110, 110, 120), None),          # steelie
              ((200, 202, 210), (70, 70, 80), None),             # 5-spoke
              ((236, 196, 72), (190, 150, 40), None),            # gold mesh
              ((30, 30, 36), (206, 208, 216), None),             # deep dish
              ((255, 60, 200), (60, 240, 255), None),            # neon
              ((206, 208, 216), (160, 162, 170), (232, 232, 226)),  # whitewall
              ((226, 228, 236), (236, 196, 72), None),           # spinner
              ((184, 184, 194), (214, 58, 58), None)]            # sawblade
RAINBOW = [(230, 60, 60), (240, 150, 40), (240, 220, 60), (80, 200, 90), (70, 130, 240), (150, 80, 200)]
CARBON = (48, 48, 56)
FLAME_COLS = ((255, 200, 60), (255, 130, 30), (220, 60, 30))
GNOME_BLUE, GNOME_RED = (60, 90, 200), (220, 40, 40)
WOOD = (130, 86, 50)
# per model: (sill height, waistline, wheel radius, front/rear axle as a fraction of half-length)
_BODY = {V.KEI: (0.3, 1.0, 0.31, 0.63), V.SEDAN: (0.3, 0.95, 0.33, 0.62), V.COUPE: (0.26, 0.82, 0.33, 0.64),
         V.MUSCLE: (0.3, 0.9, 0.35, 0.62), V.PICKUP: (0.4, 1.1, 0.4, 0.62), V.VAN: (0.36, 1.05, 0.38, 0.66),
         V.ICECREAM: (0.36, 1.05, 0.38, 0.66), V.SCOOTER: (0.12, 0.25, 0.12, 0.62),
         V.RICE: (0.18, 0.76, 0.3, 0.64),          # slammed. Scrapes on painted lines.
         V.TRUCK4: (0.78, 1.55, 0.56, 0.6),        # lifted. You need a step ladder.
         V.ARMOURED: (0.42, 1.12, 0.44, 0.64)}     # (v0.9) the money truck: a bank vault on wheels
STICKER_COLS = [(255, 255, 255), (240, 60, 60), (40, 200, 240), (250, 220, 60), (30, 30, 36), (255, 110, 200)]


def _decal(b, x0, x1, y0, y1, z0, z1, col):
    b.append((x0, x1, y0, y1, z0, z1, col))


def car_boxes(kind, color, mask, styles, damage, lights, model=V.KEI, livery=0, extras=0, extras2=0):
    """A car as a stack of boxes (x forward, y right, z up). Every strippable
    part is its own box, so a stripped car looks stripped from every angle,
    and every part style (gold mesh, flames, ironing-board wing) shows. The
    top-down automap draws the very same boxes from straight above."""
    m = V.model(model)
    st = V.unpack_styles(styles)
    pattern, second = V.livery_parts(livery)
    body = (36, 36, 48) if kind == COP else CAR_COLORS[color % len(CAR_COLORS)]
    if pattern == V.LIV_TAXI:
        body = (236, 196, 60)
    elif pattern == V.LIV_CAMO:
        body = (96, 110, 70)
    if damage:
        body = shade(body, 1.0 - 0.1 * damage)
    sec = CAR_COLORS[second % len(CAR_COLORS)]
    if model == V.SCOOTER:
        return _scooter_boxes(body, mask, st, lights)
    if model == V.ARMOURED:
        body = (122, 126, 134)                         # armour plate grey, whatever colour it rolled
    hl, hw = m.length / 2.0, m.width / 2.0
    z0, zw, wr, axle = _BODY[model]
    zr = zw + m.roof
    hood_len = m.length * m.hood
    cf = hl - hood_len                      # cabin front
    cr = cf - m.length * m.cab              # cabin rear
    lower = sec if pattern in (V.LIV_TWOTONE, V.LIV_PASTEL) else body
    door = P["white"] if kind == COP else body
    hole = P["ink"]
    b = []
    boxy = model in (V.VAN, V.ICECREAM, V.ARMOURED)
    glow = (extras >> 4) & 15
    if glow:
        # neon underglow: a thin slab of light just under the sills. Tasteful. (It is not tasteful.)
        # Two slabs: a dim halo washed into the asphalt, and a bright strip hugging the sills. One big
        # bright slab read as "car parked on a pink bath mat".
        gc = CAR_COLORS[(glow - 1) % len(CAR_COLORS)]
        halo = tuple(int(c * 0.55 + r * 0.45) for c, r in zip(gc, (70, 70, 80)))
        b.append((-hl - 0.22, hl + 0.22, -hw - 0.22, hw + 0.22, 0.0, 0.01, halo))
        b.append((-hl - 0.08, hl + 0.08, -hw - 0.1, hw + 0.1, 0.0, 0.02, shade(gc, 1.3)))
    # ---- body sections: nose, middle (the doors are its sides), tail -------------
    hood_on = _bit(mask, "Hood")
    hs = st["Hood"] if hood_on else 0
    hood_top = body if hood_on else hole
    if hood_on and hs == 4:
        hood_top = CARBON
    nose_top = zw - (0.1 if boxy else 0.0)
    split = z0 + (zw - z0) * 0.4             # where two-tone changes colour
    for (xa, xb, top, faces) in ((cf, hl, nose_top, {"+z": hood_top}),
                                 (cr, cf, zw, {"-y": door if _bit(mask, "DoorL") else hole,
                                               "+y": door if _bit(mask, "DoorR") else hole}),
                                 (-hl, cr, zw, {})):
        if lower is not body:
            b.append((xa, xb, -hw, hw, z0, split, dict({"*": lower, "+z": None}, **{k: v for k, v in faces.items()
                                                                                     if k != "+z" and v is hole})))
            b.append((xa, xb, -hw, hw, split, top, dict({"*": body, "-z": None}, **faces)))
        else:
            b.append((xa, xb, -hw, hw, z0, top, dict({"*": body}, **faces)))
    if not hood_on and _bit(mask, "Engine"):
        b.append((cf + 0.2, hl - 0.2, -0.6, 0.6, z0 + 0.3, nose_top + 0.02, {"*": P["metal"], "+z": P["metal_l"]}))
    # ---- glasshouse / cab / box -------------------------------------------------------
    roof = P["white"] if kind == COP else shade(body, 0.92)
    gy = hw - 0.14
    if boxy:
        # the cargo box goes from the cab to the back door, full height
        b.append((-hl, cf, -hw, hw, zw, zr + zw * 0.1, {"*": body, "+z": shade(body, 0.95), "-z": None}))
        b.append((cf, cf + 0.03, -gy, gy, zw + 0.1, zr - 0.3, P["glass"]))            # windscreen
        for sgn in (-1, 1):
            b.append((cf - 0.9, cf - 0.1, sgn * hw - 0.02 if sgn > 0 else -hw - 0.0, sgn * hw + 0.02 if sgn > 0
                      else -hw + 0.02, zw + 0.15, zr - 0.35, P["glass"]))
        if model == V.ICECREAM:
            # the serving hatch (right side) and a cone the size of a toddler on the roof
            b.append((-hl + 1.2, cf - 1.3, hw, hw + 0.03, zw + 0.25, zr - 0.25, P["ink2"]))
            b.append((-hl + 1.1, cf - 1.2, hw, hw + 0.25, zw + 0.2, zw + 0.25, (236, 130, 190)))
            cx = -0.3
            top = zr + zw * 0.1
            for k, (rad, col) in enumerate(((0.12, (190, 140, 70)), (0.2, (200, 150, 80)), (0.28, (210, 160, 90)),
                                            (0.36, (240, 236, 220)), (0.3, (236, 130, 190)), (0.18, (120, 70, 40)))):
                zb = top + k * 0.22
                b.append((cx - rad, cx + rad, -rad, rad, zb, zb + 0.22, col))
    elif model in (V.PICKUP, V.TRUCK4):
        b.append((cr + 0.05, cf - 0.05, -gy, gy, zw, zr, {"*": P["glass"], "+z": roof, "-z": None,
                                                          "-x": P["glass_d"]}))
        # the bed: floor and walls, open on top
        b.append((-hl, cr, -hw, hw, z0, z0 + 0.3, {"*": body}))
        for sgn in (-1, 1):
            y0, y1 = (hw - 0.12, hw) if sgn > 0 else (-hw, -hw + 0.12)
            b.append((-hl, cr, y0, y1, z0 + 0.3, zw, body))
        b.append((-hl, -hl + 0.12, -hw, hw, z0 + 0.3, zw, body))
    else:
        cab_len = cf - cr
        ws = cf - cab_len * 0.32                 # windscreen / roof boundary
        rw = cr + cab_len * 0.22                 # roof / rear window boundary
        b.append((ws, cf - 0.05, -gy, gy, zw, zr - 0.04, {"*": P["glass"], "-z": None, "-x": None}))
        b.append((rw, ws, -gy, gy, zw, zr, {"*": P["glass"], "+z": roof, "-z": None, "+x": None, "-x": None}))
        b.append((cr + 0.05, rw, -gy, gy, zw, zr - 0.06, {"*": P["glass_d"], "-z": None, "+x": None}))
    top_z = zr + (zw * 0.1 if boxy else 0.0)
    if model == V.TRUCK4:
        # the lift: a chassis you can see daylight under, a light bar, a snorkel
        b.append((-hl + 0.4, hl - 0.4, -hw + 0.45, hw - 0.45, wr * 0.8, z0, P["ink2"]))
        b.append((cf - 0.45, cf - 0.2, -hw + 0.3, hw - 0.3, zr, zr + 0.14,
                  {"*": P["ink2"], "+x": (255, 240, 170)}))
        b.append((cf - 0.05, cf + 0.1, hw - 0.12, hw + 0.02, zw - 0.3, zr + 0.2, P["ink2"]))
    elif model == V.RICE:
        # stickers: one for every brand of oil the owner has never used
        rng = random.Random(color * 29 + 3)
        for _ in range(9):
            x = rng.uniform(-hl + 0.3, hl - 0.6)
            z = rng.uniform(z0 + 0.08, zw - 0.18)
            sgn = rng.choice((-1, 1))
            y0, y1 = (hw, hw + 0.02) if sgn > 0 else (-hw - 0.02, -hw)
            _decal(b, x, x + rng.uniform(0.2, 0.45), y0, y1, z, z + 0.1, rng.choice(STICKER_COLS))
        # canards on the nose, and a windscreen banner nobody can see out of
        for sgn in (-1, 1):
            y0 = hw - 0.3 if sgn > 0 else -hw + 0.05
            b.append((hl - 0.25, hl + 0.1, y0, y0 + 0.25, z0 + 0.35, z0 + 0.4, CARBON))
        cab_len = cf - cr
        b.append((cf - cab_len * 0.3, cf - cab_len * 0.2, -hw + 0.2, hw - 0.2, zr - 0.12, zr - 0.02,
                  (40, 40, 48)))
    # ---- livery ---------------------------------------------------------------------
    if pattern == V.LIV_STRIPES:
        for yc in (-0.2, 0.2):
            if hood_on:
                _decal(b, cf, hl, yc - 0.09, yc + 0.09, nose_top, nose_top + 0.02, sec)
            _decal(b, -hl, cr, yc - 0.09, yc + 0.09, zw, zw + 0.02, sec)
            if not boxy and model != V.PICKUP:
                _decal(b, cr + 0.2, cf - 0.4, yc - 0.09, yc + 0.09, zr, zr + 0.02, sec)
            elif boxy:
                _decal(b, -hl, cf, yc - 0.09, yc + 0.09, top_z, top_z + 0.02, sec)
    elif pattern in (V.LIV_CHECKER, V.LIV_TAXI):
        n = int(m.length / 0.3)
        zc = zw - 0.28
        for k in range(n):
            if k % 2:
                continue
            x = -hl + k * 0.3
            for sgn in (-1, 1):
                y0, y1 = (hw, hw + 0.02) if sgn > 0 else (-hw - 0.02, -hw)
                _decal(b, x, x + 0.3, y0, y1, zc, zc + 0.14, P["ink"])
                _decal(b, x + 0.3, min(hl, x + 0.6), y0, y1, zc + 0.14, zc + 0.28, P["ink"])
        if pattern == V.LIV_TAXI and not boxy:
            b.append((cr + 0.5, cr + 0.9, -0.35, 0.35, zr, zr + 0.25, {"*": (250, 240, 150), "+x": P["ink"],
                                                                      "-x": P["ink"]}))
    elif pattern in (V.LIV_FLAMES, V.LIV_BOLT):
        for sgn in (-1, 1):
            y0, y1 = (hw, hw + 0.02) if sgn > 0 else (-hw - 0.02, -hw)
            if pattern == V.LIV_FLAMES:
                for k, (dx, h, col) in enumerate(((0.0, 0.4, FLAME_COLS[2]), (0.35, 0.3, FLAME_COLS[1]),
                                                  (0.65, 0.22, FLAME_COLS[0]), (0.9, 0.14, FLAME_COLS[1]))):
                    _decal(b, hl - 1.3 - dx, hl - 0.2 - dx * 0.5, y0, y1, z0 + 0.1, z0 + 0.1 + h, col)
            else:
                for k in range(5):
                    x = hl - 0.6 - k * m.length * 0.15
                    zc = z0 + 0.15 + (0.25 if k % 2 else 0.0)
                    _decal(b, x - m.length * 0.15, x, y0, y1, zc, zc + 0.12, sec)
    elif pattern == V.LIV_DOTS:
        rng = random.Random(color * 131 + second)
        for _ in range(14):
            x = rng.uniform(-hl + 0.2, hl - 0.4)
            z = rng.uniform(z0 + 0.1, zw - 0.25)
            sgn = rng.choice((-1, 1))
            y0, y1 = (hw, hw + 0.02) if sgn > 0 else (-hw - 0.02, -hw)
            _decal(b, x, x + 0.22, y0, y1, z, z + 0.18, sec)
    elif pattern == V.LIV_CAMO:
        rng = random.Random(color * 17 + 5)
        for _ in range(18):
            x = rng.uniform(-hl, hl - 0.6)
            y = rng.uniform(-hw, hw - 0.6)
            col = rng.choice(((70, 84, 50), (130, 120, 80), (50, 56, 40)))
            _decal(b, x, x + 0.6, y, y + 0.5, zw, zw + 0.02, col)
            sgn = rng.choice((-1, 1))
            y0, y1 = (hw, hw + 0.02) if sgn > 0 else (-hw - 0.02, -hw)
            z = rng.uniform(z0, zw - 0.3)
            _decal(b, x, x + 0.6, y0, y1, z, z + 0.3, col)
    # ---- doors ----------------------------------------------------------------------------
    for slot, sgn in (("DoorL", -1), ("DoorR", 1)):
        if not _bit(mask, slot) or kind == COP:
            continue
        ds = st[slot]
        y0, y1 = (hw, hw + 0.025) if sgn > 0 else (-hw - 0.025, -hw)
        xm = (cf + cr) / 2
        if ds == 1:                                                                   # race number
            _decal(b, xm - 0.35, xm + 0.35, y0, y1, z0 + 0.1, zw - 0.08, P["white"])
            y0b, y1b = (y1, y1 + 0.01) if sgn > 0 else (y0 - 0.01, y0)
            _decal(b, xm - 0.08, xm + 0.08, y0b, y1b, z0 + 0.2, zw - 0.18, P["ink"])
        elif ds == 2:                                                                 # flames
            for k, col in enumerate(FLAME_COLS):
                _decal(b, cr + 0.1, cf - 0.1 - k * 0.35, y0, y1, z0 + 0.05, z0 + 0.35 - k * 0.08, col)
        elif ds == 3:                                                                 # wood panel
            _decal(b, cr + 0.08, cf - 0.08, y0, y1, z0 + 0.08, zw - 0.1, WOOD)
    # ---- hood styles -------------------------------------------------------------------
    if hood_on:
        hx = (cf + hl) / 2
        if hs == 1:                                                                   # scoop
            b.append((hx - 0.3, hx + 0.2, -0.3, 0.3, nose_top, nose_top + 0.13, {"*": shade(body, 0.85),
                                                                             "+x": P["ink"]}))
        elif hs == 2:                                                                 # power bulge
            b.append((cf + 0.15, hl - 0.25, -0.45, 0.45, nose_top, nose_top + 0.07, shade(body, 1.05)))
        elif hs == 3:                                                                 # flames
            for k, col in enumerate(FLAME_COLS):
                _decal(b, hl - 0.9 + k * 0.1, hl - 0.05, -0.6 + k * 0.2, 0.6 - k * 0.2, nose_top,
                       nose_top + 0.02 + k * 0.005, col)
        elif hs == 5:                                                                 # shark mouth
            for k in range(7):
                y = -0.75 + k * 0.25
                _decal(b, hl, hl + 0.02, y, y + 0.15, z0 + 0.08, z0 + 0.3, P["white"])
            _decal(b, hl, hl + 0.015, -0.85, 0.85, z0 + 0.05, z0 + 0.34, (180, 30, 40))
        elif hs == 6:                                                                 # blower
            b.append((hx - 0.25, hx + 0.25, -0.22, 0.22, nose_top, nose_top + 0.35, P["chrome"]))
            b.append((hx - 0.2, hx + 0.2, -0.18, 0.18, nose_top + 0.35, nose_top + 0.45, P["ink"]))
        elif hs == 7:                                                                 # gnome plinth
            b.append((hl - 0.5, hl - 0.2, -0.15, 0.15, nose_top, nose_top + 0.05, P["chrome"]))
    if extras2 & 1:                                                                   # the gnome
        gx = hl - 0.35
        gz = nose_top + (0.05 if hs == 7 else 0.0)
        b.append((gx - 0.1, gx + 0.1, -0.1, 0.1, gz, gz + 0.2, GNOME_BLUE))
        b.append((gx + 0.06, gx + 0.12, -0.08, 0.08, gz + 0.1, gz + 0.22, P["white"]))    # beard
        b.append((gx - 0.07, gx + 0.08, -0.07, 0.07, gz + 0.2, gz + 0.3, SKINS[0]))
        b.append((gx - 0.08, gx + 0.08, -0.08, 0.08, gz + 0.3, gz + 0.38, GNOME_RED))
        b.append((gx - 0.04, gx + 0.04, -0.04, 0.04, gz + 0.38, gz + 0.5, GNOME_RED))
    if model == V.ARMOURED:
        # a gold band and a big dollar sign each side, so it's obvious what's in the back. Subtle.
        for y0, y1 in ((-hw - 0.02, -hw), (hw, hw + 0.02)):
            b.append((-hl + 0.3, cf - 0.2, y0, y1, zw * 0.72, zw * 0.8, P["gold"]))
            b.append((-hl * 0.35 - 0.12, -hl * 0.35 + 0.12, y0, y1, zw + 0.2, zw + 0.8, P["gold"]))
        b.append((-hl - 0.05, -hl, -0.04, 0.04, z0 + 0.2, top_z - 0.1, (60, 62, 70)))   # the back doors' seam
    # ---- cop bits -----------------------------------------------------------------------
    if kind == COP:
        l_on = lights & 1
        xm = (cf + cr) / 2
        b.append((xm - 0.3, xm + 0.3, -0.7, 0.0, zr, zr + 0.16, P["red"] if l_on else P["red_d"]))
        b.append((xm - 0.3, xm + 0.3, 0.0, 0.7, zr, zr + 0.16, P["blue_d"] if l_on else P["blue"]))
    # ---- bumpers -------------------------------------------------------------------------
    for slot, x0, x1 in (("BumperF", hl, hl + 0.15), ("BumperR", -hl - 0.15, -hl)):
        if not _bit(mask, slot):
            continue
        bs = st[slot]
        c = P["chrome"] if bs in (0, 3) else shade(body, 0.8) if bs == 1 else P["metal"]
        top = P["gold"] if bs == 3 else c
        b.append((x0, x1, -hw + 0.05, hw - 0.05, z0, z0 + 0.25, {"*": c, "+z": top}))
        if bs == 1:                                                                    # lip / splitter
            xa, xb = (x1, x1 + 0.2) if slot == "BumperF" else (x0 - 0.2, x0)
            b.append((xa, xb, -hw + 0.15, hw - 0.15, z0 - 0.1, z0 - 0.02, CARBON))
        elif bs == 2:                                                                  # bull bar
            xa = x1 + 0.12 if slot == "BumperF" else x0 - 0.2
            for y in (-hw + 0.3, hw - 0.4):
                b.append((xa, xa + 0.08, y, y + 0.1, z0, zw + 0.05, P["chrome"]))
            for z in (z0 + 0.15, zw - 0.1):
                b.append((xa, xa + 0.08, -hw + 0.3, hw - 0.3, z, z + 0.07, P["chrome"]))
    # ---- exhaust -------------------------------------------------------------------------
    if _bit(mask, "Exhaust"):
        es = st["Exhaust"]
        pipes = {0: (-0.7,), 1: (-0.7, 0.7), 2: (-0.8, -0.6, 0.6, 0.8), 3: ()}[es]
        for y in pipes:
            b.append((-hl - 0.25, -hl, y - 0.08, y + 0.08, z0 + 0.02, z0 + 0.16, P["chrome"]))
        if es == 3:                                                                    # stovepipe
            b.append((cr - 0.2, cr - 0.05, -hw + 0.02, -hw + 0.17, z0, zr + 0.5, P["chrome"]))
        if model == V.RICE:                                                            # the fart can
            b.append((-hl - 0.45, -hl, 0.35, 0.75, z0, z0 + 0.4, {"*": P["chrome"], "-x": P["ink"]}))
        if extras & 8 and lights & 4:                                                  # NOS flames
            for y in (pipes or (-0.7,)):
                b.append((-hl - 0.9, -hl - 0.25, y - 0.12, y + 0.12, z0, z0 + 0.2, (90, 170, 255)))
                b.append((-hl - 0.55, -hl - 0.25, y - 0.06, y + 0.06, z0 + 0.04, z0 + 0.14, (220, 240, 255)))
    # ---- spoiler -------------------------------------------------------------------------
    kind_sp = st["spoiler_kind"] if _bit(mask, "Spoiler") else 0
    if kind_sp:
        sp_st = st["spoiler_style"]
        col = [body, CARBON, P["chrome"], None][sp_st]
        xs0, xs1 = -hl + 0.05, -hl + (0.35 if kind_sp == 1 else 0.6 if kind_sp != 4 else 0.95)
        post_h = {1: 0.0, 2: 0.35, 3: 0.2, 4: 0.75}[kind_sp]
        thick = {1: 0.1, 2: 0.06, 3: 0.12, 4: 0.08}[kind_sp]
        span = hw - (0.2 if kind_sp != 4 else 0.0)
        base_z = zw if not boxy else top_z
        if post_h:
            for y in (-span + 0.35, span - 0.45):
                b.append((xs0 + 0.1, xs0 + 0.2, y, y + 0.1, base_z, base_z + post_h, P["metal"]))
        zp = base_z + post_h
        if col is None:                                                                # rainbow
            n = len(RAINBOW)
            for k, rc in enumerate(RAINBOW):
                ya = -span + 2 * span * k / n
                b.append((xs0, xs1, ya, ya + 2 * span / n, zp, zp + thick, rc))
        else:
            b.append((xs0, xs1, -span, span, zp, zp + thick, col))
    # ---- lights ----------------------------------------------------------------------------
    hazard = (255, 170, 40) if lights & 2 else None
    front = hazard or P["light"]
    rear = hazard or P["red"]
    lz = z0 + (zw - z0) * 0.6
    for y0, y1 in ((-hw + 0.2, -hw + 0.6), (hw - 0.6, hw - 0.2)):
        b.append((hl, hl + 0.04, y0, y1, lz, lz + 0.16, front))
        b.append((-hl - 0.04, -hl, y0, y1, lz, lz + 0.16, rear))
    # ---- wheels -------------------------------------------------------------------------------
    ax = hl * axle
    for slot, x, y in (("WheelFL", ax, -1), ("WheelFR", ax, 1), ("WheelRL", -ax, -1), ("WheelRR", -ax, 1)):
        if _bit(mask, slot):
            rim, cap, tyre_side = WHEEL_LOOK[st[slot] % len(WHEEL_LOOK)]
            outer = "+y" if y > 0 else "-y"
            y0, y1 = (hw - 0.34, hw + 0.02) if y > 0 else (-hw - 0.02, -hw + 0.34)
            b.append((x - wr * 1.1, x + wr * 1.1, y0, y1, 0.0, 2 * wr, {"*": P["tire"], outer: tyre_side or rim}))
            if tyre_side:
                ya, yb = (y1, y1 + 0.01) if y > 0 else (y0 - 0.01, y0)
                b.append((x - wr * 0.75, x + wr * 0.75, ya, yb, wr * 0.25, wr * 1.75, rim))
            ya, yb = (y1, y1 + 0.03) if y > 0 else (y0 - 0.03, y0)
            b.append((x - wr * 0.4, x + wr * 0.4, ya, yb, wr * 0.6, wr * 1.4, cap))
        else:
            y0, y1 = (hw - 0.25, hw - 0.1) if y > 0 else (-hw + 0.1, -hw + 0.25)
            b.append((x - 0.12, x + 0.12, y0, y1, wr * 0.6, wr * 1.4, P["metal"]))
    return b


def _scooter_boxes(body, mask, st, lights):
    """The mobility scooter: seat, tiller, basket, and a safety flag on a pole
    so the traffic can see you coming. At 12 m/s. Flat out."""
    b = [(-0.75, 0.6, -0.36, 0.36, 0.12, 0.26, body),
         (0.5, 0.62, -0.06, 0.06, 0.26, 0.95, P["metal"]),                              # tiller
         (0.5, 0.6, -0.32, 0.32, 0.92, 0.98, P["ink2"]),                                  # handlebar
         (0.6, 0.85, -0.28, 0.28, 0.6, 0.86, {"*": P["wood"], "+z": P["wood_d"]}),       # basket
         (-0.62, -0.58, 0.26, 0.3, 0.26, 1.85, P["metal_l"]),                             # flag pole
         (-0.62, -0.5, 0.3, 0.55, 1.6, 1.82, (255, 140, 30))]                             # the flag
    if _bit(mask, "Seats"):
        b.append((-0.5, -0.05, -0.28, 0.28, 0.26, 0.62, (60, 60, 70)))
        b.append((-0.58, -0.45, -0.28, 0.28, 0.62, 1.0, (60, 60, 70)))
    b.append((0.6, 0.64, -0.12, 0.12, 0.3, 0.42, P["light"]))
    for slot, x, y in (("WheelFL", 0.45, -1), ("WheelFR", 0.45, 1), ("WheelRL", -0.55, -1), ("WheelRR", -0.55, 1)):
        if _bit(mask, slot):
            rim = WHEEL_LOOK[st[slot] % len(WHEEL_LOOK)][0]
            y0, y1 = (0.26, 0.4) if y > 0 else (-0.4, -0.26)
            b.append((x - 0.13, x + 0.13, y0, y1, 0.0, 0.25, {"*": P["tire"], "+y" if y > 0 else "-y": rim}))
    return b


GUN_METAL = (44, 44, 52)
GUN_WOOD = (110, 70, 40)


def gun_boxes(gun, x, y, z):
    """A pistol (1), a shotgun (2) or a taser (3) whose grip sits at (x, y, z), barrel along +x."""
    if gun == 3:
        return [(x - 0.03, x + 0.2, y - 0.035, y + 0.035, z + 0.02, z + 0.11, (250, 210, 40)),
                (x - 0.03, x + 0.03, y - 0.03, y + 0.03, z - 0.08, z + 0.05, (30, 30, 36)),
                (x + 0.2, x + 0.23, y - 0.03, y + 0.03, z + 0.03, z + 0.1, (30, 30, 36))]
    if gun == 1:
        return [(x - 0.03, x + 0.22, y - 0.03, y + 0.03, z + 0.03, z + 0.1, GUN_METAL),
                (x - 0.03, x + 0.03, y - 0.03, y + 0.03, z - 0.08, z + 0.05, GUN_METAL)]
    return [(x - 0.3, x - 0.02, y - 0.04, y + 0.04, z - 0.05, z + 0.06, GUN_WOOD),        # stock
            (x - 0.02, x + 0.62, y - 0.03, y + 0.03, z + 0.02, z + 0.08, GUN_METAL),       # barrel
            (x + 0.2, x + 0.42, y - 0.04, y + 0.04, z - 0.03, z + 0.03, GUN_WOOD)]         # pump


OUTFITS = {
    # outfit: (shirt, trousers, hat colour or None)
    "officer": ((34, 44, 96), (26, 30, 60), (26, 32, 70)),
    "guard": ((96, 104, 124), (54, 58, 70), (60, 66, 84)),
    "keyguard": ((96, 104, 124), (54, 58, 70), (60, 66, 84)),
    "jumpsuit": ((240, 120, 30), (240, 120, 30), None),
}
BOXER_WHITE, BOXER_HEART = (240, 236, 240), (220, 50, 80)


def person_boxes(shirt, skin, hair, frame, extra=None, pants=(52, 56, 78), gun=0, outfit=None):
    """A little blocky crook, about 1.75 m, facing +x. frame 0/1 = legs
    together/apart for the walk cycle. gun 1/2 = pistol/shotgun out in front,
    3 = a taser. outfit (v0.8): "officer", "guard", "keyguard", "jumpsuit",
    "streaker" (a censor bar and a smile) or "pantsed" (boxers, trousers at
    the ankles, dignity elsewhere)."""
    swing = 0.16 if frame else 0.0
    shoe = (30, 26, 30)
    b = []
    hat = None
    if extra == "clown":
        shoe, pants = (230, 40, 40), (80, 200, 255)
    civhat = int(outfit[3]) if outfit and outfit.startswith("hat") else None
    if outfit in OUTFITS:
        shirt, pants, hat = OUTFITS[outfit]
        if outfit != "jumpsuit":
            shoe = (16, 16, 20)
    elif outfit == "streaker":
        shirt = pants = shoe = skin
    elif outfit == "mime":
        # (v0.9) white face, white gloves, stripes, black trousers, beret. Silent. Judging you.
        shirt, pants, shoe, skin, hair = (240, 240, 240), (20, 20, 24), (16, 16, 20), (246, 246, 246), (20, 20, 24)
    for side, s in ((-1, 1), (1, -1)):
        lx = s * swing
        y0, y1 = (side * 0.2, -0.03) if side < 0 else (0.03, side * 0.2)
        if outfit == "pantsed":
            b.append((lx - 0.09, lx + 0.09, y0, y1, 0.2, 0.62, skin))                   # bare legs
            b.append((lx - 0.1, lx + 0.1, y0, y1, 0.08, 0.2, pants))                    # trousers, at the ankles
        else:
            b.append((lx - 0.09, lx + 0.09, y0, y1, 0.08, 0.82, pants))
        big = 0.12 if extra == "clown" else 0.0
        b.append((lx - 0.1, lx + 0.14 + big, side * 0.21 if side < 0 else 0.02, -0.02 if side < 0 else side * 0.21,
                  0.0, 0.1, shoe))
    if outfit == "pantsed":
        b.append((-0.12, 0.12, -0.22, 0.22, 0.62, 0.86, BOXER_WHITE))                     # the boxers...
        for y in (-0.14, 0.02):
            b.append((0.12, 0.13, y, y + 0.08, 0.7, 0.78, BOXER_HEART))                   # ...with hearts on
    b.append((-0.13, 0.13, -0.24, 0.24, 0.8, 1.4, shirt))                                 # torso
    if outfit == "keyguard":
        b.append((0.0, 0.2, -0.2, 0.2, 0.85, 1.25, shirt))                                # the big one
        b.append((0.02, 0.1, 0.2, 0.3, 0.82, 0.95, (240, 200, 60)))                       # THE KEYS
    if outfit in ("officer", "guard", "keyguard"):
        b.append((-0.14, 0.14, -0.25, 0.25, 0.8, 0.86, (20, 20, 24)))                    # duty belt
        b.append((0.13, 0.14, -0.14, -0.06, 1.22, 1.3, (230, 196, 70)))                   # badge
    if outfit == "mime":
        for z in (0.88, 1.02, 1.16, 1.3):
            b.append((-0.135, 0.135, -0.245, 0.245, z, z + 0.06, (24, 24, 28)))          # the stripes
        b.append((0.13, 0.14, -0.06, 0.06, 1.46, 1.49, (200, 30, 40)))                    # the sad little mouth
    if outfit == "streaker":
        b.append((0.12, 0.2, -0.16, 0.16, 0.66, 0.88, P["ink"]))                         # [CENSORED]
        b.append((-0.2, -0.12, -0.16, 0.16, 0.66, 0.88, P["ink"]))
    for side in (-1, 1):
        y0, y1 = (-0.35, -0.24) if side < 0 else (0.24, 0.35)
        if extra == "cuffed":
            b.append((-0.26, -0.12, y0 + side * -0.05, y1 + side * -0.05, 0.9, 1.35, shirt))
        elif extra == "handsup":
            b.append((-0.06, 0.08, y0, y1, 1.3, 1.92, shirt))                             # don't shoot
            b.append((-0.06, 0.08, y0, y1, 1.92, 2.04, skin))
        elif extra == "fists":
            # put 'em up: forearms forward, fists at chin height
            b.append((0.0, 0.3, y0 + side * -0.06, y1 + side * -0.06, 1.2, 1.32, shirt))
            b.append((0.3, 0.42, y0 + side * -0.08, y1 + side * -0.08, 1.24, 1.4, skin))
        elif extra == "laugh":
            # clutching their sides
            b.append((0.02, 0.16, y0 - side * 0.06, y1 - side * 0.06, 0.95, 1.3, shirt))
            b.append((0.1, 0.2, y0 - side * 0.12, y1 - side * 0.12, 0.95, 1.05, skin))
        elif extra in ("dance0", "dance1"):
            up = (extra == "dance0") == (side > 0)
            if up:
                b.append((-0.06, 0.08, y0 + side * 0.08, y1 + side * 0.08, 1.35, 1.95, shirt))
                b.append((-0.06, 0.08, y0 + side * 0.1, y1 + side * 0.1, 1.95, 2.07, skin))
            else:
                b.append((-0.06, 0.08, y0 + side * 0.25, y1 + side * 0.25, 1.2, 1.3, shirt))
                b.append((-0.06, 0.08, y0 + side * 0.45, y1 + side * 0.45, 1.2, 1.3, skin))
        elif extra == "windup" and side > 0:
            b.append((-0.45, -0.05, y0 + 0.05, y1 + 0.05, 1.25, 1.36, shirt))                # cocked back
            b.append((-0.58, -0.44, y0 + 0.05, y1 + 0.05, 1.24, 1.38, skin))
        elif gun and side > 0:
            # arm straight out, gun at the end: the international sign for "wallet. Now."
            b.append((0.0, 0.42, 0.18, 0.29, 1.24, 1.35, shirt))
            b.append((0.42, 0.52, 0.18, 0.29, 1.23, 1.35, skin))
            b.extend(gun_boxes(gun, 0.5, 0.23, 1.3))
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
    if hat is not None:
        # a peaked cap. Authority, in box form.
        b.append((-0.16, 0.16, -0.16, 0.16, 1.7, 1.82, hat))
        b.append((0.12, 0.26, -0.14, 0.14, 1.7, 1.74, P["ink"]))
        b.append((0.15, 0.17, -0.04, 0.04, 1.73, 1.79, (230, 196, 70)))
        return b
    if extra == "clown":
        b.append((0.15, 0.2, -0.03, 0.03, 1.5, 1.56, (255, 40, 40)))                      # honk
        b.append((-0.2, 0.1, -0.24, 0.24, 1.6, 1.84, (255, 110, 40)))                     # wig
    elif outfit == "mime":
        b.append((-0.2, 0.12, -0.18, 0.18, 1.72, 1.8, (20, 20, 24)))                      # the beret
        b.append((-0.03, 0.03, -0.03, 0.03, 1.8, 1.86, (20, 20, 24)))
    else:
        b.append((-0.16, 0.08, -0.15, 0.15, 1.66, 1.78, hair))
        b.append((-0.16, -0.12, -0.15, 0.15, 1.46, 1.7, hair))
        if civhat is not None:
            b.extend((x0, x1, y0, y1, z0 + 1.72, z1 + 1.72, c) for x0, x1, y0, y1, z0, z1, c in civ_hat_boxes(civhat))
    return b


CIV_HATS = 5


def civ_hat_boxes(style):
    """(v0.9) Pedestrians' hats, sitting at z = 0 (the head top is added by the caller).
    They come off when you knock someone down. Flat cap, bowler, cowboy, top hat, bobble."""
    if style == 0:
        c = (110, 96, 80)
        return [(-0.17, 0.15, -0.16, 0.16, -0.04, 0.05, c), (0.12, 0.28, -0.14, 0.14, -0.04, 0.0, shade(c, 0.8))]
    if style == 1:
        c = (30, 28, 30)
        return [(-0.22, 0.22, -0.22, 0.22, -0.04, 0.0, c), (-0.14, 0.14, -0.14, 0.14, 0.0, 0.16, c)]
    if style == 2:
        c = (150, 100, 55)
        return [(-0.34, 0.34, -0.3, 0.3, -0.03, 0.01, c), (-0.14, 0.14, -0.13, 0.13, 0.0, 0.18, c),
                (-0.15, 0.15, -0.14, 0.14, 0.02, 0.05, (60, 40, 26))]
    if style == 3:
        c = (22, 22, 26)
        return [(-0.22, 0.22, -0.22, 0.22, -0.04, 0.0, c), (-0.13, 0.13, -0.13, 0.13, 0.0, 0.36, c),
                (-0.135, 0.135, -0.135, 0.135, 0.05, 0.1, (150, 30, 40))]
    c = (200, 40, 60)
    return [(-0.16, 0.16, -0.16, 0.16, -0.04, 0.12, c), (-0.16, 0.16, -0.16, 0.16, 0.0, 0.03, (240, 240, 240)),
            (-0.06, 0.06, -0.06, 0.06, 0.12, 0.22, (240, 240, 240))]


def chicken_boxes(frame=0, peck=False):
    """(v0.9) A chicken, facing +x. It is crossing the road. It will not say why."""
    white, red, yel = (246, 244, 236), (220, 40, 40), (240, 190, 40)
    step = 0.04 if frame else -0.04
    head_dz = -0.14 if peck else 0.0
    hx = 0.14 if not peck else 0.2
    return [(step - 0.015, step + 0.015, -0.06, -0.03, 0.0, 0.14, yel),
            (-step - 0.015, -step + 0.015, 0.03, 0.06, 0.0, 0.14, yel),
            (-0.16, 0.1, -0.1, 0.1, 0.12, 0.3, white),                                   # body
            (-0.22, -0.14, -0.05, 0.05, 0.22, 0.36, white),                              # tail
            (hx - 0.06, hx + 0.04, -0.05, 0.05, 0.28 + head_dz, 0.4 + head_dz, white),   # head
            (hx - 0.04, hx + 0.0, -0.015, 0.015, 0.4 + head_dz, 0.45 + head_dz, red),    # comb
            (hx + 0.04, hx + 0.08, -0.02, 0.02, 0.33 + head_dz, 0.36 + head_dz, yel),    # beak
            (hx + 0.03, hx + 0.05, -0.01, 0.01, 0.28 + head_dz, 0.32 + head_dz, red)]    # wattle


def rubber_chicken_boxes():
    """(v0.9) The rubber chicken: plucked, yellow, floppy, along +x. Squeaks."""
    yel, red = (250, 214, 60), (230, 60, 40)
    return [(-0.3, 0.1, -0.05, 0.05, 0.0, 0.08, yel),              # body (limp)
            (0.1, 0.3, -0.03, 0.03, 0.02, 0.06, yel),              # neck
            (0.3, 0.38, -0.04, 0.04, 0.0, 0.08, yel),              # head
            (0.32, 0.36, -0.01, 0.01, 0.08, 0.12, red),            # comb
            (0.38, 0.44, -0.015, 0.015, 0.02, 0.05, (240, 150, 40)),
            (-0.4, -0.3, -0.06, -0.02, 0.0, 0.03, yel), (-0.4, -0.3, 0.02, 0.06, 0.0, 0.03, yel)]


def whoopee_boxes():
    """(v0.9) A whoopee cushion, flat on the ground, nozzle out. Pfffft pending."""
    pink = (240, 110, 170)
    return [(-0.26, 0.26, -0.22, 0.22, 0.0, 0.06, pink), (-0.2, 0.2, -0.26, 0.26, 0.0, 0.06, pink),
            (0.26, 0.36, -0.04, 0.04, 0.0, 0.03, shade(pink, 0.8))]


def cardboard_box_boxes(frame=0, moving=False):
    """(v0.9) A cardboard box, 1 m a side. Parcel tape. A 'THIS WAY UP' arrow. And if it's
    moving, little feet underneath (the illusion is not perfect)."""
    card, tape, dark = (190, 150, 100), (220, 200, 150), (150, 115, 75)
    lift = 0.14 if moving else 0.0
    b = [(-0.5, 0.5, -0.5, 0.5, lift, lift + 1.0, {"*": card, "+z": shade(card, 1.1)}),
         (-0.5, 0.5, -0.07, 0.07, lift + 1.0, lift + 1.01, tape),                         # the tape
         (-0.3, 0.3, -0.5, -0.49, lift + 0.4, lift + 0.6, dark),                           # the arrow, sort of
         (0.49, 0.5, -0.2, 0.2, lift + 0.5, lift + 0.56, dark)]                            # the eye slit
    if moving:
        s = 0.08 if frame else -0.08
        b.append((s - 0.08, s + 0.1, -0.24, -0.08, 0.0, 0.14, (30, 26, 30)))
        b.append((-s - 0.08, -s + 0.1, 0.08, 0.24, 0.0, 0.14, (30, 26, 30)))
    return b


def ramp_boxes():
    """(v0.9) A plywood stunt ramp rising along +x, in hazard stripes. Somebody's dad built it."""
    hl, hw = 1.6, 1.7
    b = []
    steps = 8
    for k in range(steps):
        x0 = -hl + k * 2 * hl / steps
        x1 = x0 + 2 * hl / steps
        z1 = 0.08 + 0.9 * (k + 1) / steps
        col = (240, 200, 40) if k % 2 == 0 else (30, 30, 34)
        b.append((x0, x1, -hw, hw, 0.0, z1, {"*": (150, 110, 60), "+z": col}))
    return b


def pigeon_img(frame, flying):
    """(v0.9) A pigeon, as a billboard: grey, round, stupid. frame flaps the wings."""
    s = pygame.Surface((8, 7), pygame.SRCALPHA)
    body, dark, neck = (140, 140, 150), (90, 90, 100), (90, 150, 130)
    s.fill(body, (1, 3, 6, 3))
    s.fill(dark, (5, 1, 2, 2))
    s.fill(neck, (5, 3, 2, 1))
    s.fill((230, 170, 60), (7, 2, 1, 1))
    if flying:
        if frame:
            s.fill(dark, (0, 0, 3, 3))
            s.fill(dark, (4, 0, 2, 2))
        else:
            s.fill(dark, (0, 5, 3, 2))
    else:
        s.fill((200, 120, 110), (2, 6, 1, 1))
        s.fill((200, 120, 110), (4, 6, 1, 1))
    return s


DOG_BROWN, DOG_DARK = (150, 100, 55), (60, 40, 26)


def dog_boxes(frame=0, trousers=False):
    """A police dog: German shepherd-ish, facing +x. A very good boy. It wants
    your trousers. Sometimes it has them (trousers=True)."""
    leg = 0.06 if frame else -0.06
    b = []
    for x, s in ((0.28, 1), (-0.28, -1)):
        for y in (-0.12, 0.08):
            b.append((x + leg * s - 0.04, x + leg * s + 0.04, y, y + 0.05, 0.0, 0.34, DOG_DARK))
    b.append((-0.36, 0.34, -0.14, 0.14, 0.3, 0.58, DOG_BROWN))                          # body
    b.append((-0.1, 0.3, -0.15, 0.15, 0.5, 0.6, DOG_DARK))                              # saddle
    b.append((0.3, 0.52, -0.1, 0.1, 0.5, 0.74, DOG_BROWN))                              # head
    b.append((0.5, 0.64, -0.06, 0.06, 0.52, 0.62, DOG_DARK))                            # snout
    for y in (-0.09, 0.05):
        b.append((0.32, 0.38, y, y + 0.04, 0.74, 0.86, DOG_DARK))                       # ears
    b.append((-0.5, -0.36, -0.03, 0.03, 0.5, 0.56, DOG_BROWN))                          # tail
    b.append((0.2, 0.3, -0.15, 0.15, 0.56, 0.6, (40, 60, 150)))                         # POLICE harness
    if trousers:
        b.append((0.58, 0.7, -0.25, 0.25, 0.42, 0.56, (52, 56, 78)))                    # your trousers
    return b


def big_head(boxes, k=2.1):
    """Big-head mode: everything above the shoulders, scaled up around the
    neck. Purely cosmetic. Deeply important."""
    out = []
    for x0, x1, y0, y1, z0, z1, c in boxes:
        if z0 >= 1.4 and z1 <= 2.1 and abs(y0) < 0.2 and abs(y1) < 0.2:
            out.append((x0 * k, x1 * k, y0 * k, y1 * k, 1.42 + (z0 - 1.42) * k, 1.42 + (z1 - 1.42) * k, c))
        else:
            out.append((x0, x1, y0, y1, z0, z1, c))
    return out


def lying(boxes):
    """Rotate a standing model 90 degrees so it's flat on its back (tumbling)."""
    out = []
    for x0, x1, y0, y1, z0, z1, c in boxes:
        out.append((-z1 + 0.9, -z0 + 0.9, y0, y1, x0 + 0.2, x1 + 0.2, c))
    return out


def spike_boxes(length):
    """One stretch of stinger strip, lying across the lane (along model y):
    a black hinged base bristling with steel teeth. Tyres hate this one trick."""
    hl = length / 2
    b = [(-0.32, 0.32, -hl, hl, 0.0, 0.05, (26, 24, 30)),
         (-0.34, -0.3, -hl, hl, 0.0, 0.07, (230, 190, 40))]                               # yellow edge
    n = max(2, int(length / 0.3))
    for k in range(n):
        y = -hl + (k + 0.5) * length / n
        for x in (-0.18, 0.0, 0.18):
            b.append((x - 0.03, x + 0.03, y - 0.03, y + 0.03, 0.05, 0.18, P["chrome"]))
    return b


BARRIER_ORANGE = (255, 120, 20)
BARRIER_WHITE = (245, 245, 240)


def barrier_boxes(length, lamp=False):
    """One stretch of road barrier (along model y): A-frame legs and a striped
    board at knee and chest height. Orange and white, the colours of 'no'."""
    hl = length / 2
    b = []
    for y in (-hl + 0.18, hl - 0.18):
        for x in (-0.32, 0.32):
            b.append((x - 0.05, x + 0.05, y - 0.05, y + 0.05, 0.0, 1.02, P["metal_l"]))
        b.append((-0.34, 0.34, y - 0.05, y + 0.05, 0.0, 0.06, P["metal"]))
    stripes = max(2, int(round(length / 0.5)))
    for k in range(stripes):
        ya = -hl + k * length / stripes
        yb = ya + length / stripes
        col = BARRIER_ORANGE if k % 2 == 0 else BARRIER_WHITE
        b.append((-0.06, 0.06, ya, yb, 0.66, 0.98, col))
        b.append((-0.06, 0.06, ya, yb, 0.26, 0.4, BARRIER_WHITE if k % 2 == 0 else BARRIER_ORANGE))
    if lamp:
        b.append((-0.06, 0.06, hl - 0.34, hl - 0.18, 0.98, 1.14, (255, 200, 40)))
    return b


def gnome_boxes():
    """A garden gnome, full lawn size: blue coat, white beard, red hat, dead eyes."""
    return [(-0.14, 0.14, -0.14, 0.14, 0.0, 0.05, (90, 150, 60)),                   # a tuft of stolen lawn
            (-0.1, 0.1, -0.1, 0.1, 0.05, 0.3, GNOME_BLUE),
            (0.06, 0.12, -0.08, 0.08, 0.14, 0.34, P["white"]),                       # beard
            (-0.07, 0.08, -0.07, 0.07, 0.3, 0.42, SKINS[0]),
            (-0.09, 0.09, -0.09, 0.09, 0.42, 0.5, GNOME_RED),
            (-0.05, 0.05, -0.05, 0.05, 0.5, 0.6, GNOME_RED),
            (-0.02, 0.02, -0.02, 0.02, 0.6, 0.66, GNOME_RED)]


def gate_boxes(length):
    """Half the precinct gate: steel bars across the doorway (along model y)."""
    hl = length / 2
    steel, dark = (120, 124, 136), (60, 62, 72)
    b = [(-0.08, 0.08, -hl, hl, 2.3, 2.45, dark), (-0.08, 0.08, -hl, hl, 0.0, 0.12, dark),
         (-0.06, 0.06, -hl, hl, 1.2, 1.3, steel)]
    n = int(length / 0.28)
    for k in range(n):
        y = -hl + (k + 0.5) * length / n
        b.append((-0.04, 0.04, y - 0.04, y + 0.04, 0.12, 2.3, steel))
    return b


PRECINCT_LINO = (150, 160, 176)     # (art.PRECINCT_FLOOR: the desk's footprint gets painted over with it)


def bars_boxes(length, door=False, locked=True, bent=0.0):
    """(v0.9) A run of cell bars along model y (the cells' walls), or a cell door:
    same bars, a frame, and a big padlock. A punched door leans (bent = 0..1)."""
    hl = length / 2
    steel, dark = (120, 124, 136), (54, 56, 66)
    h = 2.6
    lean = 0.35 * bent
    b = [(-0.07, 0.07, -hl, hl, h - 0.14, h, dark), (-0.07, 0.07, -hl, hl, 0.0, 0.1, dark),
         (-0.05, 0.05, -hl, hl, 1.25, 1.33, steel)]
    n = max(2, int(length / 0.26))
    for k in range(n):
        y = -hl + (k + 0.5) * length / n
        b.append((-0.035 + lean, 0.035 + lean, y - 0.035, y + 0.035, 0.1, h - 0.14, steel))
    if door:
        b.append((-0.08, 0.08, -hl, -hl + 0.1, 0.0, h, dark))
        b.append((-0.08, 0.08, hl - 0.1, hl, 0.0, h, dark))
        if locked:
            b.append((-0.14, 0.14, hl - 0.4, hl - 0.16, 1.05, 1.35, (200, 170, 60)))   # the padlock
    return b


def desk_boxes(w, d):
    """(v0.9) The precinct front desk: a wooden counter, a computer from 1998,
    a bell nobody answers, and a BAIL sign. Along model x = w, y = d."""
    wood, dark = (110, 80, 50), (70, 50, 30)
    hw, hd = w / 2, d / 2
    return [(-hw, hw, -hd, hd, 0.0, 1.05, {"*": wood, "+z": (130, 96, 60)}),
            (-hw, hw, -hd - 0.04, -hd, 0.0, 1.05, dark),
            (-0.6, 0.0, -0.2, 0.25, 1.05, 1.45, (200, 196, 180)),               # the beige monitor
            (-0.5, -0.1, -0.24, -0.2, 1.12, 1.4, (40, 60, 90)),
            (0.8, 0.95, -0.1, 0.05, 1.05, 1.12, (220, 200, 90)),                # ding
            (-0.9, 0.9, -0.04, 0.04, 1.55, 1.95, {"*": (30, 60, 150), "+y": (40, 70, 170)})]


def banana_boxes():
    """A banana peel: four floppy yellow bits and a brown stalk. Deadly."""
    yel, dark = (255, 232, 60), (215, 180, 40)
    return [(-0.1, 0.1, -0.1, 0.1, 0.0, 0.08, dark),
            (0.1, 0.42, -0.07, 0.07, 0.0, 0.04, yel), (-0.42, -0.1, -0.07, 0.07, 0.0, 0.04, yel),
            (-0.07, 0.07, 0.1, 0.4, 0.0, 0.04, yel), (-0.07, 0.07, -0.4, -0.1, 0.0, 0.04, yel),
            (-0.03, 0.03, -0.03, 0.03, 0.06, 0.14, (110, 80, 40))]


def donut_box_boxes():
    """A box of donuts, lid open. Cops can smell it from 35 m."""
    pink = (236, 130, 190)
    b = [(-0.25, 0.25, -0.35, 0.35, 0.0, 0.1, {"*": pink, "+z": (250, 250, 245)}),
         (-0.27, -0.23, -0.35, 0.35, 0.1, 0.4, pink)]                                     # the lid, up
    for x in (-0.1, 0.1):
        for y in (-0.2, 0.0, 0.2):
            b.append((x - 0.07, x + 0.07, y - 0.07, y + 0.07, 0.1, 0.15, {"*": (190, 120, 70),
                                                                        "+z": (236, 90, 150)}))
    return b


CRATE_BANDS = {"pistol": (60, 60, 70), "shotgun": GUN_WOOD, "ammo": (200, 170, 60),
               "spikes": (230, 190, 40), "roadblock": BARRIER_ORANGE, "banana": (250, 220, 70),
               "donuts": (236, 130, 190), "chicken": (250, 220, 60), "whoopee": (240, 110, 170),
               "box": (190, 150, 100)}


def crate_boxes(item):
    """A black-market crate with a sample of the goods on the lid."""
    wood, dark = P["wood"], shade(P["wood"], 0.7)
    band = CRATE_BANDS.get(item, P["metal"])
    b = [(-0.42, 0.42, -0.42, 0.42, 0.0, 0.75, {"*": wood, "+z": shade(wood, 1.15)}),
         (-0.43, 0.43, -0.43, 0.43, 0.3, 0.42, band),
         (-0.43, 0.43, -0.43, 0.43, 0.0, 0.06, dark),
         (-0.43, 0.43, -0.43, 0.43, 0.69, 0.75, dark)]
    if item == "pistol":
        b.extend(gun_boxes(1, -0.1, 0.0, 0.8))
    elif item == "shotgun":
        b.extend(gun_boxes(2, -0.15, 0.0, 0.82))
    elif item == "ammo":
        for k, y in enumerate((-0.2, 0.0, 0.2)):
            b.append((-0.1, 0.1, y - 0.07, y + 0.07, 0.75, 0.9 + 0.04 * k, (60, 90, 50)))
    elif item == "banana":
        b.extend((x0, x1, y0, y1, z0 + 0.75, z1 + 0.75, c) for x0, x1, y0, y1, z0, z1, c in banana_boxes())
    elif item == "donuts":
        b.extend((x0 * 0.9, x1 * 0.9, y0 * 0.9, y1 * 0.9, z0 + 0.75, z1 + 0.75, c)
                 for x0, x1, y0, y1, z0, z1, c in donut_box_boxes())
    elif item == "spikes":
        for y in (-0.25, -0.08, 0.09, 0.26):
            b.append((-0.3, 0.3, y - 0.06, y + 0.06, 0.75, 0.8, (26, 24, 30)))
            b.append((-0.25, 0.25, y - 0.02, y + 0.02, 0.8, 0.86, P["chrome"]))
    elif item == "chicken":
        b.extend((x0 * 1.1, x1 * 1.1, y0 * 1.1, y1 * 1.1, z0 + 0.75, z1 + 0.75, c)
                 for x0, x1, y0, y1, z0, z1, c in rubber_chicken_boxes())
    elif item == "whoopee":
        b.extend((x0, x1, y0, y1, z0 + 0.75, z1 + 0.75, c) for x0, x1, y0, y1, z0, z1, c in whoopee_boxes())
    elif item == "box":
        b.extend((x0 * 0.4, x1 * 0.4, y0 * 0.4, y1 * 0.4, z0 * 0.4 + 0.75, z1 * 0.4 + 0.75, c)
                 for x0, x1, y0, y1, z0, z1, c in cardboard_box_boxes(0, False))
    else:
        b.append((-0.3, 0.3, -0.35, 0.35, 0.75, 0.84, BARRIER_ORANGE))
        b.append((-0.3, 0.3, -0.12, 0.12, 0.75, 0.845, BARRIER_WHITE))
    return b


def dolly_boxes():
    return [(-0.45, 0.45, -0.3, -0.24, 0.1, 1.0, P["metal_l"]), (-0.45, 0.45, 0.24, 0.3, 0.1, 1.0, P["metal_l"]),
            (-0.45, 0.45, -0.3, 0.3, 0.1, 0.16, P["metal"]), (0.45, 0.6, -0.3, 0.3, 0.0, 0.08, P["chrome"]),
            (-0.1, 0.2, -0.38, -0.3, 0.0, 0.25, P["tire"]), (-0.1, 0.2, 0.3, 0.38, 0.0, 0.25, P["tire"]),
            (-0.5, -0.4, -0.3, 0.3, 0.95, 1.05, P["red"])]


def trunk_lid_boxes(stage):
    """(v0.10, Bryce: "popping trunk animation") the boot lid easing open -- stage 0
    shut, 3 fully up. It doesn't hinge so much as grow a vertical panel, same as
    everything else in this low-poly city."""
    top = 0.68 + 0.42 * (stage / 3.0)
    return [(-0.5, 0.5, -0.05, 0.05, 0.64, top, {"*": P["metal"], "+z": shade(P["metal"], 1.25)})]


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


def make_chute():
    """Ejector-seat parachute: a striped canopy and its strings."""
    s = pygame.Surface((40, 34), pygame.SRCALPHA)
    cols = ((236, 70, 60), (245, 245, 240))
    for k in range(8):
        x0 = 2 + k * 4.5
        pygame.draw.polygon(s, cols[k % 2], [(20, 2), (x0, 14), (x0 + 4.5, 14)])
    pygame.draw.ellipse(s, (200, 60, 50), (0, 6, 40, 12), 2)
    for x in (2, 12, 28, 38):
        pygame.draw.line(s, (60, 60, 60), (x, 14), (20, 33))
    return s, 20, 34


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

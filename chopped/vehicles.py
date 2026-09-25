"""
vehicles.py -- what KIND of car it is (v0.7). Until now every car in the
city was the same Kei hatch in a different colour, which made the parts you
stole about as exciting as a spreadsheet. Now there are models (with their
own size, weight, grip, top speed and trunk), and every visible part comes
in styles: gold mesh wheels, flame doors, a spoiler the size of an ironing
board. Put them on your ride and people will notice. Mostly the police.

No pygame in here (the sim and the predictor both import it).
"""

from .config import clamp

# ---- models --------------------------------------------------------------------
KEI, SEDAN, COUPE, MUSCLE, PICKUP, VAN, ICECREAM, SCOOTER = range(8)


class Model:
    """Numbers per body style. Physics reads length/width/mass/grip/top/accel;
    the renderers read the shape numbers; the trunk is how many hands' worth
    of parts fit in the back (a door is 2, a wheel is 1)."""
    __slots__ = ("id", "name", "length", "width", "height", "mass", "grip", "top", "accel", "trunk",
                 "bed", "fwd", "cg_h", "hood", "roof", "cab", "civ_weight", "traffic_weight", "sporty")

    def __init__(self, mid, name, length, width, height, mass, grip, top, accel, trunk, bed=False,
                 fwd=False, cg_h=0.5, hood=0.3, roof=0.5, cab=0.45, civ_weight=0, traffic_weight=0,
                 sporty=False):
        self.id = mid
        self.name = name
        self.length, self.width, self.height = length, width, height
        self.mass = mass
        self.grip = grip              # tyre friction coefficient (1.0 = a decent road tyre)
        self.top = top                # m/s, flat out, stock gearing
        self.accel = accel            # multiplier on the part-power acceleration
        self.trunk = trunk            # hand-units of storage (see Part.bulk)
        self.bed = bed                # open bed / cargo box: engines fit too
        self.fwd = fwd                # front-wheel drive: understeers, won't power-slide
        self.cg_h = cg_h              # centre of gravity height (weight transfer)
        self.hood = hood              # art: fraction of the length that's bonnet
        self.roof = roof              # art: roof height above the waistline, metres
        self.cab = cab                # art: fraction of the length that's cabin
        self.civ_weight = civ_weight
        self.traffic_weight = traffic_weight
        self.sporty = sporty          # rolls the good loot table


# Sizes are real-ish; top speeds are "fun-real". The Kei stays exactly the
# old 4.4 x 2.4 box so every collision test from v0.4 still means something.
MODELS = [
    Model(KEI, "KEI HATCH", 4.4, 2.4, 1.55, 1000, 1.00, 45.0, 1.00, 3, hood=0.22, roof=0.62, cab=0.55,
          civ_weight=30, traffic_weight=30),
    Model(SEDAN, "SEDAN", 4.9, 2.5, 1.45, 1300, 1.00, 47.0, 0.95, 5, hood=0.3, roof=0.5, cab=0.42,
          civ_weight=26, traffic_weight=30),
    Model(COUPE, "SPORTS COUPE", 4.5, 2.4, 1.25, 1150, 1.12, 53.0, 1.18, 2, hood=0.34, roof=0.42, cab=0.36,
          civ_weight=11, traffic_weight=7, sporty=True, cg_h=0.42),
    Model(MUSCLE, "MUSCLE CAR", 5.0, 2.5, 1.35, 1500, 0.94, 51.0, 1.22, 4, hood=0.4, roof=0.45, cab=0.34,
          civ_weight=10, traffic_weight=7, sporty=True),
    Model(PICKUP, "PICKUP", 5.4, 2.6, 1.8, 1800, 0.95, 42.0, 0.9, 8, bed=True, hood=0.28, roof=0.62,
          cab=0.3, civ_weight=10, traffic_weight=12, cg_h=0.65),
    Model(VAN, "BOX VAN", 5.6, 2.7, 2.4, 2000, 0.88, 38.0, 0.76, 10, bed=True, fwd=True, hood=0.14,
          roof=1.2, cab=0.2, civ_weight=7, traffic_weight=10, cg_h=0.9),
    Model(ICECREAM, "ICE CREAM VAN", 5.6, 2.7, 2.5, 2100, 0.86, 34.0, 0.7, 6, bed=True, fwd=True, hood=0.14,
          roof=1.2, cab=0.2, civ_weight=3, traffic_weight=2, cg_h=0.95),
    Model(SCOOTER, "MOBILITY SCOOTER", 1.6, 0.9, 0.9, 160, 0.9, 12.0, 0.55, 1, hood=0.2, roof=0.0,
          cab=0.5, civ_weight=3, traffic_weight=0, cg_h=0.4),
]
MODEL_NAMES = [m.name for m in MODELS]
COP_MODEL = SEDAN             # interceptors are sedans with attitude
PERSONAL_MODEL = KEI          # your ride starts humble


def model(mid):
    return MODELS[mid if 0 <= mid < len(MODELS) else KEI]


def pick_model(rng, traffic=False):
    ms = [(m.id, m.traffic_weight if traffic else m.civ_weight) for m in MODELS]
    total = sum(w for _, w in ms)
    r = rng.random() * total
    for mid, w in ms:
        r -= w
        if r <= 0:
            return mid
    return KEI


# ---- paint -------------------------------------------------------------------------
# 0 is your ride's lime green; the rest are what the city buys
PAINT_NAMES = ["LIME", "RED", "BLUE", "YELLOW", "WHITE", "BLACK", "ORANGE", "TEAL", "PURPLE",
               "SILVER", "PINK", "BROWN", "GOLD", "NAVY", "MINT", "FOREST"]
LIVERIES = ["NONE", "RACING STRIPES", "TWO-TONE", "FLAMES", "CHECKERS", "POLKA DOTS", "CAMO", "TAXI",
            "PASTEL", "LIGHTNING"]
LIV_NONE, LIV_STRIPES, LIV_TWOTONE, LIV_FLAMES, LIV_CHECKER, LIV_DOTS, LIV_CAMO, LIV_TAXI, LIV_PASTEL, \
    LIV_BOLT = range(10)


def livery_byte(pattern, second):
    return (pattern & 15) | ((second & 15) << 4)


def livery_parts(b):
    return b & 15, (b >> 4) & 15


# ---- horns (the mod shop sells worse ones) -------------------------------------------
HORNS = ["STOCK", "CLOWN", "LA CUCARACHA", "WET FART", "GOAT", "AIR HORN", "ICE CREAM JINGLE"]
HORN_STOCK, HORN_CLOWN, HORN_CUCA, HORN_FART, HORN_GOAT, HORN_AIR, HORN_JINGLE = range(7)

# ---- part styles ------------------------------------------------------------------
# style 0 is always the boring factory one. Names show up in the mod shop and
# in the "STRIP ..." prompt, so a gold wheel says so.
STYLES = {
    "wheel": ["STEELIE", "5-SPOKE", "GOLD MESH", "DEEP DISH", "NEON", "WHITEWALL", "SPINNER", "SAWBLADE"],
    "hood": ["PLAIN", "SCOOP", "BULGE", "FLAMES", "CARBON", "SHARK MOUTH", "BLOWER", "GNOME-READY"],
    "bumper": ["PLAIN", "LIP", "BULL BAR", "CHROME"],
    "exhaust": ["SINGLE", "TWIN", "QUAD", "STOVEPIPE"],
    "door": ["PLAIN", "RACE NUMBER", "FLAMES", "WOOD PANEL"],
    "spoiler": ["BODY", "CARBON", "CHROME", "RAINBOW"],
}
# how much more a style fetches than the plain one (gold is gold)
STYLE_VALUE = {
    "wheel": [1.0, 1.15, 1.6, 1.3, 1.25, 1.1, 1.5, 1.35],
    "hood": [1.0, 1.2, 1.15, 1.3, 1.4, 1.25, 1.5, 1.05],
    "bumper": [1.0, 1.15, 1.2, 1.3],
    "exhaust": [1.0, 1.15, 1.3, 1.2],
    "door": [1.0, 1.15, 1.3, 1.1],
    "spoiler": [1.0, 1.3, 1.4, 1.5],
}


def styles_for(category):
    return STYLES.get(category, ["STOCK"])


def style_name(category, style):
    names = STYLES.get(category)
    if not names:
        return ""
    return names[style % len(names)]


def style_value(category, style):
    vals = STYLE_VALUE.get(category)
    if not vals:
        return 1.0
    return vals[style % len(vals)]


def roll_style(rng, category, tuned):
    """Mostly plain; tuned parts come dressed up more often."""
    names = STYLES.get(category)
    if not names:
        return 0
    fancy = 0.55 if tuned else 0.28
    if rng.random() >= fancy:
        return 0
    return rng.randrange(1, len(names))


# ---- the style word: what a car row needs to draw every visible part ---------------
# bits: 4 wheels x 3, hood 3, bumper F 2, bumper R 2, exhaust 2, door L 2, door R 2,
# spoiler kind 3 (0 none), spoiler style 2 = 30 bits
_STYLE_LAYOUT = (("WheelFL", 3), ("WheelFR", 3), ("WheelRL", 3), ("WheelRR", 3), ("Hood", 3),
                 ("BumperF", 2), ("BumperR", 2), ("Exhaust", 2), ("DoorL", 2), ("DoorR", 2))
SPOILER_KINDS = [None, "spl_lip", "spl_wing", "spl_whale", "spl_shelf"]


def pack_styles(parts):
    word, shift = 0, 0
    for slot, bits in _STYLE_LAYOUT:
        p = parts.get(slot)
        v = (p.style if p is not None else 0) & ((1 << bits) - 1)
        word |= v << shift
        shift += bits
    sp = parts.get("Spoiler")
    kind = SPOILER_KINDS.index(sp.type_id) if sp is not None and sp.type_id in SPOILER_KINDS else 0
    word |= (kind & 7) << shift
    word |= ((sp.style if sp is not None else 0) & 3) << (shift + 3)
    return word


def unpack_styles(word):
    """-> dict slot -> style, plus 'spoiler_kind' and 'spoiler_style'."""
    out, shift = {}, 0
    for slot, bits in _STYLE_LAYOUT:
        out[slot] = (word >> shift) & ((1 << bits) - 1)
        shift += bits
    out["spoiler_kind"] = (word >> shift) & 7
    out["spoiler_style"] = (word >> (shift + 3)) & 3
    return out


# ---- performance from parts -----------------------------------------------------------
# The mod shop's bars and the physics read the same numbers. Power still does
# the heavy lifting; wheels, aero and weight shave off the rest.
WHEEL_GRIP = {"whl_worn_steel": 0.93, "whl_stock_alloy": 1.0, "whl_tuned_light": 1.08, "whl_scooter": 0.9}
SPOILER_GRIP = {"spl_lip": 0.02, "spl_wing": 0.05, "spl_whale": 0.06, "spl_shelf": 0.09}
SPOILER_DRAG = {"spl_lip": 0.0, "spl_wing": 0.01, "spl_whale": 0.015, "spl_shelf": 0.05}
MASS_DELTA = {"hood_tuned_cf": -25, "seat_tuned_bkt": -20, "bmp_tuned_aero": -5, "whl_tuned_light": -4,
              "whl_worn_steel": 3}


def performance(mdl, parts):
    """(grip multiplier, mass kg, top-speed multiplier) for this body with these parts."""
    wheels = [parts.get(s) for s in ("WheelFL", "WheelFR", "WheelRL", "WheelRR")]
    present = [w for w in wheels if w is not None]
    grip = sum(WHEEL_GRIP.get(w.type_id, 1.0) for w in present) / len(present) if present else 0.6
    sp = parts.get("Spoiler")
    drag = 0.0
    if sp is not None:
        grip += SPOILER_GRIP.get(sp.type_id, 0.0)
        drag += SPOILER_DRAG.get(sp.type_id, 0.0)
    for s in ("BumperF", "BumperR"):
        b = parts.get(s)
        if b is not None and b.type_id == "bmp_tuned_aero":
            grip += 0.015
    mass = mdl.mass
    for p in parts.values():
        if p is not None:
            mass += MASS_DELTA.get(p.type_id, 0)
    return clamp(grip, 0.5, 1.4), max(100.0, float(mass)), 1.0 - drag

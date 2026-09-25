"""
parts.py -- the catalogue of things you can unscrew from other people's cars.

Every car has the same 15 slots (v0.7 added the Spoiler; most cars don't
have one, which is fine -- an empty spoiler slot isn't damage, it's taste).
Each part has a category, a "bulk" (how many hands it needs: 1, 2, or the
dreaded DOLLY = can't lift it at all), a base value, a power contribution,
and (v0.7) a style: gold mesh, flames, wood panel. Car power = sum of part
power; 100 = stock Kei.
"""

from .config import lerp
from . import vehicles as V

# Slot order is also the bit order in network part masks. Don't reorder
# unless you enjoy debugging invisible doors.
SLOTS = [
    "Engine", "Transmission", "ECU", "Exhaust",
    "WheelFL", "WheelFR", "WheelRL", "WheelRR",
    "Hood", "DoorL", "DoorR", "BumperF", "BumperR", "Seats", "Spoiler",
]
SLOT_INDEX = {s: i for i, s in enumerate(SLOTS)}
WHEEL_SLOTS = ("WheelFL", "WheelFR", "WheelRL", "WheelRR")
PANEL_SLOTS = ("BumperF", "BumperR", "Hood", "DoorL", "DoorR", "Exhaust", "Spoiler")
# slots that are allowed to be empty on a healthy car (you don't "need" a wing)
OPTIONAL_SLOTS = ("Spoiler",)

SLOT_CATEGORY = {
    "Engine": "engine", "Transmission": "trans", "ECU": "ecu", "Exhaust": "exhaust",
    "WheelFL": "wheel", "WheelFR": "wheel", "WheelRL": "wheel", "WheelRR": "wheel",
    "Hood": "hood", "DoorL": "door", "DoorR": "door",
    "BumperF": "bumper", "BumperR": "bumper", "Seats": "seat", "Spoiler": "spoiler",
}
CATEGORY_SLOTS = {}
for _s, _c in SLOT_CATEGORY.items():
    CATEGORY_SLOTS.setdefault(_c, []).append(_s)

# Local-space anchor of each slot, metres, car facing +x (forward), +y = right side.
# Used to decide which slot you're standing next to and where knocked-off parts spawn.
SLOT_ANCHOR = {
    "Engine": (1.3, 0.0), "Transmission": (0.3, 0.0), "ECU": (1.0, -0.9),
    "Exhaust": (-2.2, -0.7),
    "WheelFL": (1.4, -1.3), "WheelFR": (1.4, 1.3), "WheelRL": (-1.4, -1.3), "WheelRR": (-1.4, 1.3),
    "Hood": (1.7, 0.0), "DoorL": (0.0, -1.35), "DoorR": (0.0, 1.35),
    "BumperF": (2.3, 0.0), "BumperR": (-2.3, 0.3), "Seats": (-0.2, 0.6), "Spoiler": (-1.9, -0.4),
}
# How long (s) holding E takes to rip each slot out. Engines take ages on purpose.
# (v0.5: all halved -- faster game.)
STRIP_TIME = {"wheel": 2.0, "hood": 3.0, "door": 3.0, "bumper": 3.0,
              "engine": 10.0, "trans": 2.5, "ecu": 2.5, "exhaust": 2.5, "seat": 2.5, "spoiler": 2.0}

DOLLY = 3  # bulk value meaning "you'd need a dolly"

# id: (display name, category, bulk, base value, power, tuned?)
PART_DEFS = {
    "whl_worn_steel":  ("Worn steelie",      "wheel",   1,     25,   0, False),
    "whl_stock_alloy": ("Alloy wheel",       "wheel",   1,     90,   0, False),
    "whl_tuned_light": ("Lightweight wheel", "wheel",   1,    300,   0, True),
    "bmp_stock":       ("Bumper",            "bumper",  2,     90,   0, False),
    "bmp_tuned_aero":  ("Aero bumper",       "bumper",  2,    380,   0, True),
    "door_stock":      ("Door",              "door",    2,    140,   0, False),
    "ecu_stock":       ("ECU",               "ecu",     1,    150,   0, False),
    "ecu_tuned":       ("Tuned ECU",         "ecu",     1,    650,  20, True),
    "eng_worn_1_0":    ("Worn 1.0 engine",   "engine",  DOLLY, 180, 45, False),
    "eng_stock_1_6":   ("1.6 engine",        "engine",  DOLLY, 600, 90, False),
    "eng_tuned_2_0t":  ("2.0 turbo engine",  "engine",  DOLLY, 2200, 180, True),
    "exh_stock":       ("Exhaust",           "exhaust", 2,     80,   0, False),
    "exh_tuned":       ("Tuned exhaust",     "exhaust", 2,    350,   8, True),
    "hood_stock":      ("Hood",              "hood",    2,    120,   0, False),
    "hood_tuned_cf":   ("Carbon hood",       "hood",    2,    500,   0, True),
    "seat_stock":      ("Seats",             "seat",    2,    110,   0, False),
    "seat_tuned_bkt":  ("Bucket seat",       "seat",    1,    520,   0, True),
    "trn_worn_4mt":    ("Worn 4-speed",      "trans",   2,    120,   0, False),
    "trn_stock_5mt":   ("5-speed gearbox",   "trans",   2,    400,  10, False),
    "trn_tuned_6mt":   ("6-speed gearbox",   "trans",   2,   1400,  25, True),
    # v0.7: spoilers. Grip at speed, and the respect of strangers.
    "spl_lip":         ("Ducktail spoiler",  "spoiler", 1,    120,   0, False),
    "spl_wing":        ("GT wing",           "spoiler", 2,    450,   0, True),
    "spl_whale":       ("Whale tail",        "spoiler", 2,    380,   0, True),
    "spl_shelf":       ("Ironing-board wing", "spoiler", 2,   600,   0, True),
    # the mobility scooter's bits (yes, you can put its motor in your car. No, you shouldn't.)
    "eng_electric":    ("Scooter motor",     "engine",  1,    160,  30, False),
    "whl_scooter":     ("Tiny wheel",        "wheel",   1,     12,   0, False),
    # trunk loot and other things that aren't car parts but sell anyway
    "gnome":           ("Garden gnome",      "junk",    1,     60,   0, False),
    "cash_bag":        ("Bag of cash",       "loot",    1,    180,   0, False),
    "briefcase":       ("Mystery briefcase", "loot",    2,    420,   0, False),
    "rubber_duck":     ("Giant rubber duck", "loot",    2,     90,   0, False),
}
PART_IDS = list(PART_DEFS.keys())          # index = network id
PART_INDEX = {pid: i for i, pid in enumerate(PART_IDS)}
NO_PART = 255


def part_name(type_id):
    return PART_DEFS[type_id][0]


def part_category(type_id):
    return PART_DEFS[type_id][1]


def part_bulk(type_id):
    return PART_DEFS[type_id][2]


def part_power(type_id):
    return PART_DEFS[type_id][4]


def part_tuned(type_id):
    return PART_DEFS[type_id][5]


class Part:
    """One physical part. Condition 0..1 scales value (a wrecked part still
    fetches 15% -- scrap metal is scrap metal). Style (v0.7) is the look:
    0 = factory plain, higher = gold mesh / flames / etc., and worth more."""
    __slots__ = ("type_id", "condition", "style")

    def __init__(self, type_id, condition=1.0, style=0):
        self.type_id = type_id
        self.condition = condition
        self.style = style

    @property
    def value(self):
        d = PART_DEFS[self.type_id]
        return int(round(d[3] * lerp(0.15, 1.0, self.condition) * V.style_value(d[1], self.style)))

    @property
    def name(self):
        base = PART_DEFS[self.type_id][0]
        if self.style:
            return "%s %s" % (V.style_name(PART_DEFS[self.type_id][1], self.style), base)
        return base

    @property
    def category(self):
        return PART_DEFS[self.type_id][1]

    @property
    def bulk(self):
        return PART_DEFS[self.type_id][2]

    def __repr__(self):
        return "Part(%s, %.2f)" % (self.type_id, self.condition)


# ---- Loadouts -------------------------------------------------------------
# (slot -> weighted choices). Kei Hatch: "mostly stock/worn". A ~6% tuned
# jackpot per slot keeps every break-in a little lottery ticket.
KEI_TABLE = {
    "Engine": [("eng_worn_1_0", 40), ("eng_stock_1_6", 56), ("eng_tuned_2_0t", 4)],
    "Transmission": [("trn_worn_4mt", 40), ("trn_stock_5mt", 54), ("trn_tuned_6mt", 6)],
    "ECU": [("ecu_stock", 93), ("ecu_tuned", 7)],
    "Exhaust": [("exh_stock", 93), ("exh_tuned", 7)],
    "wheel": [("whl_worn_steel", 45), ("whl_stock_alloy", 50), ("whl_tuned_light", 5)],
    "Hood": [("hood_stock", 94), ("hood_tuned_cf", 6)],
    "DoorL": [("door_stock", 100)], "DoorR": [("door_stock", 100)],
    "BumperF": [("bmp_stock", 94), ("bmp_tuned_aero", 6)],
    "BumperR": [("bmp_stock", 96), ("bmp_tuned_aero", 4)],
    "Seats": [("seat_stock", 94), ("seat_tuned_bkt", 6)],
    "Spoiler": [(None, 86), ("spl_lip", 9), ("spl_wing", 3), ("spl_whale", 1), ("spl_shelf", 1)],
}
# Coupes and muscle cars: somebody loved this car. Now you do.
SPORT_TABLE = {
    "Engine": [("eng_stock_1_6", 70), ("eng_tuned_2_0t", 30)],
    "Transmission": [("trn_stock_5mt", 70), ("trn_tuned_6mt", 30)],
    "ECU": [("ecu_stock", 70), ("ecu_tuned", 30)],
    "Exhaust": [("exh_stock", 60), ("exh_tuned", 40)],
    "wheel": [("whl_stock_alloy", 70), ("whl_tuned_light", 30)],
    "Hood": [("hood_stock", 75), ("hood_tuned_cf", 25)],
    "DoorL": [("door_stock", 100)], "DoorR": [("door_stock", 100)],
    "BumperF": [("bmp_stock", 65), ("bmp_tuned_aero", 35)],
    "BumperR": [("bmp_stock", 75), ("bmp_tuned_aero", 25)],
    "Seats": [("seat_stock", 65), ("seat_tuned_bkt", 35)],
    "Spoiler": [(None, 35), ("spl_lip", 25), ("spl_wing", 20), ("spl_whale", 12), ("spl_shelf", 8)],
}
# Police interceptors: better bits. Blowing one up is a loot pinata.
COP_TABLE = {
    "Engine": [("eng_stock_1_6", 70), ("eng_tuned_2_0t", 30)],
    "Transmission": [("trn_stock_5mt", 65), ("trn_tuned_6mt", 35)],
    "ECU": [("ecu_stock", 55), ("ecu_tuned", 45)],
    "Exhaust": [("exh_stock", 65), ("exh_tuned", 35)],
    "wheel": [("whl_stock_alloy", 75), ("whl_tuned_light", 25)],
    "Hood": [("hood_stock", 100)], "DoorL": [("door_stock", 100)], "DoorR": [("door_stock", 100)],
    "BumperF": [("bmp_stock", 80), ("bmp_tuned_aero", 20)],
    "BumperR": [("bmp_stock", 100)],
    "Seats": [("seat_stock", 70), ("seat_tuned_bkt", 30)],
    "Spoiler": [(None, 70), ("spl_lip", 20), ("spl_wing", 10)],
}
# Your own ride starts humble: stock engine, worn gearbox, steelies. Upgrade it.
PERSONAL_LOADOUT = {
    "Engine": "eng_stock_1_6", "Transmission": "trn_worn_4mt", "ECU": "ecu_stock",
    "Exhaust": "exh_stock", "WheelFL": "whl_worn_steel", "WheelFR": "whl_worn_steel",
    "WheelRL": "whl_worn_steel", "WheelRR": "whl_worn_steel", "Hood": "hood_stock",
    "DoorL": "door_stock", "DoorR": "door_stock", "BumperF": "bmp_stock",
    "BumperR": "bmp_stock", "Seats": "seat_stock",
}


def _pick(rng, choices):
    total = sum(w for _, w in choices)
    r = rng.random() * total
    for pid, w in choices:
        r -= w
        if r <= 0:
            return pid
    return choices[-1][0]


def roll_loadout(rng, table, cond_lo, cond_hi, styled=True):
    parts = {}
    wheel_style = None
    for slot in SLOTS:
        key = "wheel" if slot in WHEEL_SLOTS else slot
        tid = _pick(rng, table.get(key, [(None, 1)]))
        if tid is None:
            parts[slot] = None
            continue
        part = Part(tid, rng.uniform(cond_lo, cond_hi))
        if styled:
            cat = PART_DEFS[tid][1]
            if slot in WHEEL_SLOTS:
                # a matching set, usually. 1 in 10 has that one odd wheel from the scrapyard.
                if wheel_style is None:
                    wheel_style = V.roll_style(rng, cat, PART_DEFS[tid][5])
                part.style = wheel_style if rng.random() > 0.1 else V.roll_style(rng, cat, False)
            else:
                part.style = V.roll_style(rng, cat, PART_DEFS[tid][5])
        parts[slot] = part
    return parts


def kei_loadout(rng):
    # condition 0.35..1.0 per the design doc: most Keis have seen some things
    return roll_loadout(rng, KEI_TABLE, 0.35, 1.0)


def model_loadout(rng, mid):
    """Parts for a freshly spawned car of this model."""
    if mid == V.SCOOTER:
        parts = {s: None for s in SLOTS}
        parts["Engine"] = Part("eng_electric", rng.uniform(0.4, 1.0))
        parts["Seats"] = Part("seat_stock", rng.uniform(0.3, 0.9))
        for w in WHEEL_SLOTS:
            parts[w] = Part("whl_scooter", rng.uniform(0.4, 1.0))
        return parts
    if V.model(mid).sporty:
        return roll_loadout(rng, SPORT_TABLE, 0.5, 1.0)
    return roll_loadout(rng, KEI_TABLE, 0.35, 1.0)


def cop_loadout(rng):
    return roll_loadout(rng, COP_TABLE, 0.6, 1.0, styled=False)


def personal_loadout():
    parts = {s: Part(t, 0.9) for s, t in PERSONAL_LOADOUT.items()}
    parts["Spoiler"] = None
    return parts


# what turns up in the trunk of a stolen car (v0.7). Weighted; None = empty trunk.
TRUNK_LOOT = [(None, 55), ("cash_bag", 10), ("briefcase", 4), ("gnome", 8), ("rubber_duck", 4),
              ("whl_tuned_light", 5), ("ecu_tuned", 4), ("spl_wing", 3), ("exh_tuned", 3),
              ("seat_tuned_bkt", 4)]


def roll_trunk(rng, sporty=False):
    items = []
    for _ in range(2 if sporty else 1):
        tid = _pick(rng, TRUNK_LOOT)
        if tid is not None:
            cat = PART_DEFS[tid][1]
            items.append(Part(tid, rng.uniform(0.5, 1.0), V.roll_style(rng, cat, True)))
    return items

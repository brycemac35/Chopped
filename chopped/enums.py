"""
enums.py -- the numbers that go over the wire and the names we give them.
Split out of sim.py so the World's helper modules can share them without
importing each other in circles. No pygame, no logic worth mentioning.
"""

from . import config as C

# ---- enums (ints so they go straight onto the wire) -------------------------
FOOT, DRIVER, PASSENGER, TUMBLE, CUFFED = range(5)
CIV, PERSONAL, COP, TRAFFIC = range(4)
LOCKED, BROKEN_IN, RUNNING, DELIVERED = range(4)
PED, CLOWN, OWNER = range(3)
W_NONE, W_COP, W_PED, W_OWNER, W_CAMERA = range(5)

B_UP, B_DOWN, B_LEFT, B_RIGHT = 1, 2, 4, 8
B_USE, B_SPRINT, B_HANDBRAKE, B_HORN = 16, 32, 64, 128

# toast colours
T_WHITE, T_MONEY, T_BAD, T_INFO, T_COP = range(5)

# sound ids (client maps these to procedural sfx)
(S_CRASH, S_CRASH_BIG, S_BOOM, S_SELL, S_PICKUP, S_BREAKIN, S_HOTWIRE, S_STRIP,
 S_HONK, S_ARREST, S_RENT, S_CRUSH, S_DELIVER, S_DROP, S_INSTALL, S_YELP,
 S_IGNITE, S_BUY, S_PUNCH, S_PISTOL, S_SHOTGUN, S_EMPTY, S_TIRE, S_TRAP, S_ROB) = range(25)

# what's in your hands when you click: keys 1-5
ARM_FISTS, ARM_PISTOL, ARM_SHOTGUN, ARM_SPIKES, ARM_BLOCK = range(5)
ARM_NAMES = ("FISTS", "PISTOL", "SHOTGUN", "SPIKE STRIP", "ROADBLOCK")
TRAP_SPIKES, TRAP_BLOCK = range(2)


def arsenal_owns(arsenal, slot):
    """Client-side Player.owns(), from the 6-byte arsenal in the SELF block:
    (weapon, arms bitmask, pistol ammo, shotgun ammo, spikes, roadblocks)."""
    if not arsenal:
        return slot == ARM_FISTS
    if slot == ARM_SPIKES:
        return arsenal[4] > 0
    if slot == ARM_BLOCK:
        return arsenal[5] > 0
    return bool(arsenal[1] & (1 << slot))


MARKET = {  # crate -> (label, price)
    "pistol": ("PISTOL (+%d ROUNDS)" % C.PISTOL_AMMO, C.PRICE_PISTOL),
    "shotgun": ("SHOTGUN (+%d SHELLS)" % C.SHOTGUN_AMMO, C.PRICE_SHOTGUN),
    "ammo": ("AMMO FOR YOUR GUNS", C.PRICE_AMMO),
    "spikes": ("SPIKE STRIP", C.PRICE_SPIKES),
    "roadblock": ("ROADBLOCK", C.PRICE_ROADBLOCK),
}

SLOT_LABEL = {
    "Engine": "ENGINE", "Transmission": "GEARBOX", "ECU": "ECU", "Exhaust": "EXHAUST",
    "WheelFL": "FRONT-L WHEEL", "WheelFR": "FRONT-R WHEEL", "WheelRL": "REAR-L WHEEL",
    "WheelRR": "REAR-R WHEEL", "Hood": "HOOD", "DoorL": "LEFT DOOR", "DoorR": "RIGHT DOOR",
    "BumperF": "FRONT BUMPER", "BumperR": "REAR BUMPER", "Seats": "SEATS",
}

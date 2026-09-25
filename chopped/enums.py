"""
enums.py -- the numbers that go over the wire and the names we give them.
Split out of sim.py so the World's helper modules can share them without
importing each other in circles. No pygame, no logic worth mentioning.
"""

from . import config as C

# ---- enums (ints so they go straight onto the wire) -------------------------
FOOT, DRIVER, PASSENGER, TUMBLE, CUFFED, CARRIED, DEAD = range(7)
CIV, PERSONAL, COP, TRAFFIC = range(4)
LOCKED, BROKEN_IN, RUNNING, DELIVERED = range(4)
PED, CLOWN, OWNER, OFFICER, GUARD, KEYGUARD, DOG, STREAKER = range(8)
LAW = (OFFICER, GUARD, KEYGUARD, DOG)       # (v0.8) on the city's payroll: not witnesses, not wallets
W_NONE, W_COP, W_PED, W_OWNER, W_CAMERA = range(5)

B_UP, B_DOWN, B_LEFT, B_RIGHT = 1, 2, 4, 8
B_USE, B_SPRINT, B_HANDBRAKE, B_HORN = 16, 32, 64, 128
B_FIRE, B_TAUNT = 256, 512          # (v0.7: buttons went 16-bit) fire held = haymaker wind-up; T = dance
B_JUMP = B_HANDBRAKE                # on foot, Space jumps; in a car it's the handbrake
B_HOP = 1024                        # (v0.8) X in a car with hydraulics: boing

# toast colours
T_WHITE, T_MONEY, T_BAD, T_INFO, T_COP = range(5)

# sound ids (client maps these to procedural sfx)
(S_CRASH, S_CRASH_BIG, S_BOOM, S_SELL, S_PICKUP, S_BREAKIN, S_HOTWIRE, S_STRIP,
 S_HONK, S_ARREST, S_RENT, S_CRUSH, S_DELIVER, S_DROP, S_INSTALL, S_YELP,
 S_IGNITE, S_BUY, S_PUNCH, S_PISTOL, S_SHOTGUN, S_EMPTY, S_TIRE, S_TRAP, S_ROB,
 # v0.7
 S_WHOOSH, S_BONK, S_JUMP, S_STRIKE, S_HOMERUN, S_EJECT, S_SLIP, S_MUNCH, S_LAUGH, S_GNOME,
 S_MOD, S_SPRAY, S_TRUNK, S_WRIGGLE, S_NOS,
 # v0.8
 S_TASER, S_BARK, S_FLASH, S_CONFETTI, S_HYDRO, S_WASTED, S_GATE, S_KEYS, S_CUFF, S_WHISTLE,
 S_WHEE) = range(51)
# comedy banners (Player.banner, shown big on that player's screen)
BN_NONE, BN_YEETED, BN_HUMBLED, BN_BONKED, BN_HOMERUN, BN_STRIKE, BN_EJECT, \
    BN_WASTED, BN_BUSTED, BN_TASED, BN_PANTSED, BN_FREE, BN_SMILE = range(13)
BANNER_TEXT = ("", "YEETED", "HUMBLED", "BONKED", "HOME RUN!", "STRIKE!", "EJECT! EJECT!",
               "WASTED", "BUSTED", "TASED", "PANTSED", "JAILBREAK!", "SMILE!")

# what's in your hands when you click: keys 1-5
ARM_FISTS, ARM_PISTOL, ARM_SHOTGUN, ARM_SPIKES, ARM_BLOCK, ARM_BANANA, ARM_DONUT = range(7)
ARM_NAMES = ("FISTS", "PISTOL", "SHOTGUN", "SPIKE STRIP", "ROADBLOCK", "BANANA PEEL", "BOX OF DONUTS")
ARM_COUNT = len(ARM_NAMES)
TRAP_SPIKES, TRAP_BLOCK, TRAP_BANANA, TRAP_DONUT, TRAP_GATE, TRAP_SMOKE = range(6)
SOLID_TRAPS = (TRAP_BLOCK, TRAP_GATE)       # (the gate only while it's shut: see Trap.solid)
TRACER_TASER = 7                            # EV_SHOT "weapon" code for a taser's wires
GEAR_OF_ARM = {ARM_SPIKES: 0, ARM_BLOCK: 1, ARM_BANANA: 2, ARM_DONUT: 3}   # index into Player.gear


def arsenal_owns(arsenal, slot):
    """Client-side Player.owns(), from the 8-byte arsenal in the SELF block:
    (weapon, arms bitmask, pistol ammo, shotgun ammo, spikes, roadblocks, bananas, donuts)."""
    if not arsenal:
        return slot == ARM_FISTS
    if slot in GEAR_OF_ARM:
        return arsenal[4 + GEAR_OF_ARM[slot]] > 0
    return bool(arsenal[1] & (1 << slot))


MARKET = {  # crate -> (label, price)
    "pistol": ("PISTOL (+%d ROUNDS)" % C.PISTOL_AMMO, C.PRICE_PISTOL),
    "shotgun": ("SHOTGUN (+%d SHELLS)" % C.SHOTGUN_AMMO, C.PRICE_SHOTGUN),
    "ammo": ("AMMO FOR YOUR GUNS", C.PRICE_AMMO),
    "spikes": ("SPIKE STRIP", C.PRICE_SPIKES),
    "roadblock": ("ROADBLOCK", C.PRICE_ROADBLOCK),
    "banana": ("BANANA PEEL", C.PRICE_BANANA),
    "donuts": ("BOX OF DONUTS", C.PRICE_DONUTS),
}

SLOT_LABEL = {
    "Engine": "ENGINE", "Transmission": "GEARBOX", "ECU": "ECU", "Exhaust": "EXHAUST",
    "WheelFL": "FRONT-L WHEEL", "WheelFR": "FRONT-R WHEEL", "WheelRL": "REAR-L WHEEL",
    "WheelRR": "REAR-R WHEEL", "Hood": "HOOD", "DoorL": "LEFT DOOR", "DoorR": "RIGHT DOOR",
    "BumperF": "FRONT BUMPER", "BumperR": "REAR BUMPER", "Seats": "SEATS",
}

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
CHICKEN, MIME = 8, 9                        # (v0.9) why did it cross the road; the man in the invisible box
LAW = (OFFICER, GUARD, KEYGUARD, DOG)       # (v0.8) on the city's payroll: not witnesses, not wallets
W_NONE, W_COP, W_PED, W_OWNER, W_CAMERA, W_HELI = range(6)   # (v0.10) W_HELI: the chopper

B_UP, B_DOWN, B_LEFT, B_RIGHT = 1, 2, 4, 8
B_USE, B_SPRINT, B_HANDBRAKE, B_HORN = 16, 32, 64, 128
B_FIRE, B_TAUNT = 256, 512          # (v0.7: buttons went 16-bit) fire held = haymaker wind-up; T = dance
B_JUMP = B_HANDBRAKE                # on foot, Space jumps; in a car it's the handbrake
B_HOP = 1024                        # (v0.8) X in a car with hydraulics: boing. (v0.9) on foot: the prompt's X
B_BOX = 2048                        # (v0.9) C: get in (or out of) your cardboard box

# toast colours
T_WHITE, T_MONEY, T_BAD, T_INFO, T_COP = range(5)
T_SAY = 5       # (v0.12.1) somebody talking to you: the HUD's dialogue box, not the ticker
T_STORY = 6     # (v0.13) a whole story scene by key ("B:<key>"): the client has the script (story.BEATS)

# sound ids (client maps these to procedural sfx)
(S_CRASH, S_CRASH_BIG, S_BOOM, S_SELL, S_PICKUP, S_BREAKIN, S_HOTWIRE, S_STRIP,
 S_HONK, S_ARREST, S_RENT, S_CRUSH, S_DELIVER, S_DROP, S_INSTALL, S_YELP,
 S_IGNITE, S_BUY, S_PUNCH, S_PISTOL, S_SHOTGUN, S_EMPTY, S_TIRE, S_TRAP, S_ROB,
 # v0.7
 S_WHOOSH, S_BONK, S_JUMP, S_STRIKE, S_HOMERUN, S_EJECT, S_SLIP, S_MUNCH, S_LAUGH, S_GNOME,
 S_MOD, S_SPRAY, S_TRUNK, S_WRIGGLE, S_NOS,
 # v0.8
 S_TASER, S_BARK, S_FLASH, S_CONFETTI, S_HYDRO, S_WASTED, S_GATE, S_KEYS, S_CUFF, S_WHISTLE,
 S_WHEE,
 # v0.9
 S_DOOR, S_BANG, S_SQUEAK, S_PFFT, S_CLUCK, S_CASH, S_FEATHERS,
 # v0.10
 S_AMBULANCE,
 # v0.12
 S_SMG, S_RIFLE, S_SNIPER) = range(62)
# comedy banners (Player.banner, shown big on that player's screen)
BN_NONE, BN_YEETED, BN_HUMBLED, BN_BONKED, BN_HOMERUN, BN_STRIKE, BN_EJECT, \
    BN_WASTED, BN_BUSTED, BN_TASED, BN_PANTSED, BN_FREE, BN_SMILE, BN_BIGAIR = range(14)
BANNER_TEXT = ("", "YEETED", "HUMBLED", "BONKED", "HOME RUN!", "STRIKE!", "EJECT! EJECT!",
               "WASTED", "BUSTED", "TASED", "PANTSED", "JAILBREAK!", "SMILE!", "BIG AIR!")

# what's in your hands when you click: keys 1-9, then (v0.12) the wheel/Q only -- SMG through
# the RPG live past the number row; see doomhud._arms_panel for why the pips stop at 9.
ARM_FISTS, ARM_PISTOL, ARM_SHOTGUN, ARM_SPIKES, ARM_BLOCK, ARM_BANANA, ARM_DONUT, ARM_CHICKEN, ARM_WHOOPEE, \
    ARM_SMG, ARM_AR, ARM_SNIPER, ARM_GRENADE, ARM_RPG = range(14)
ARM_NAMES = ("FISTS", "PISTOL", "SHOTGUN", "SPIKE STRIP", "ROADBLOCK", "BANANA PEEL", "BOX OF DONUTS",
             "RUBBER CHICKEN", "WHOOPEE CUSHION", "SMG", "ASSAULT RIFLE", "SNIPER RIFLE",
             "GRENADE LAUNCHER", "RPG")
ARM_COUNT = len(ARM_NAMES)
GUN_SLOTS = (ARM_PISTOL, ARM_SHOTGUN, ARM_SMG, ARM_AR, ARM_SNIPER, ARM_GRENADE, ARM_RPG)
SPLASH_GUNS = (ARM_GRENADE, ARM_RPG)         # these hitscan to a point, then explode there
# slot -> (range, cooldown, pellets, spread radians, splash radius, ammo pack size)
GUN_STATS = {
    ARM_PISTOL:  (C.PISTOL_RANGE, C.PISTOL_COOLDOWN, 1, 0.0, 0.0, C.PISTOL_AMMO),
    ARM_SHOTGUN: (C.SHOTGUN_RANGE, C.SHOTGUN_COOLDOWN, C.SHOTGUN_PELLETS, C.SHOTGUN_SPREAD, 0.0, C.SHOTGUN_AMMO),
    ARM_SMG:     (C.SMG_RANGE, C.SMG_COOLDOWN, 1, C.SMG_SPREAD, 0.0, C.SMG_AMMO),
    ARM_AR:      (C.AR_RANGE, C.AR_COOLDOWN, 1, C.AR_SPREAD, 0.0, C.AR_AMMO),
    ARM_SNIPER:  (C.SNIPER_RANGE, C.SNIPER_COOLDOWN, 1, 0.0, 0.0, C.SNIPER_AMMO),
    ARM_GRENADE: (C.GRENADE_RANGE, C.GRENADE_COOLDOWN, 1, 0.0, C.GRENADE_SPLASH, C.GRENADE_AMMO),
    ARM_RPG:     (C.RPG_RANGE, C.RPG_COOLDOWN, 1, 0.0, C.RPG_SPLASH, C.RPG_AMMO),
}
TRAP_SPIKES, TRAP_BLOCK, TRAP_BANANA, TRAP_DONUT, TRAP_GATE, TRAP_SMOKE = range(6)
TRAP_CELL, TRAP_DOOR, TRAP_WHOOPEE = 6, 7, 8   # (v0.9) cell doors, the shop's roller door, whoopee cushions
SOLID_TRAPS = (TRAP_BLOCK, TRAP_GATE, TRAP_CELL, TRAP_DOOR)   # (the doors only while shut: see Trap.solid)
FIXTURES = (TRAP_GATE, TRAP_CELL, TRAP_DOOR)  # trap-shaped bits of the map: fixed ids, never towed
INSP_RATTLE, INSP_HONK, INSP_OWNER = 1, 2, 4   # (v0.9) inspect card: trunk loot, clown car, owner nearby
TRACER_TASER = 7                            # EV_SHOT "weapon" code for a taser's wires
GEAR_OF_ARM = {ARM_SPIKES: 0, ARM_BLOCK: 1, ARM_BANANA: 2, ARM_DONUT: 3, ARM_WHOOPEE: 4}   # index into Player.gear
TRAP_OF_ARM = {ARM_SPIKES: TRAP_SPIKES, ARM_BLOCK: TRAP_BLOCK, ARM_BANANA: TRAP_BANANA, ARM_DONUT: TRAP_DONUT,
               ARM_WHOOPEE: TRAP_WHOOPEE}
GEAR_OF_TRAP = {TRAP_SPIKES: 0, TRAP_BLOCK: 1, TRAP_BANANA: 2, TRAP_DONUT: 3, TRAP_WHOOPEE: 4}
ARSENAL_LEN = 16                            # bytes of it in the SELF block (see arsenal_owns)


def arsenal_owns(arsenal, slot):
    """Client-side Player.owns(), from the arsenal in the SELF block: (weapon, arms bitmask lo,
    pistol ammo, shotgun ammo, spikes, roadblocks, bananas, donuts, whoopee cushions, has a box,
    (v0.12) arms bitmask hi, SMG/AR/sniper/grenade/RPG ammo). The bitmask needed a second byte
    once there were more than 8 real weapons -- appended at the end so nothing already reading
    arsenal[0..9] by a fixed index had to change."""
    if not arsenal:
        return slot == ARM_FISTS
    if slot in GEAR_OF_ARM:
        return arsenal[4 + GEAR_OF_ARM[slot]] > 0
    bits = arsenal[1] | ((arsenal[10] << 8) if len(arsenal) > 10 else 0)
    return bool(bits & (1 << slot))


MARKET = {  # crate -> (label, price)
    "pistol": ("PISTOL (+%d ROUNDS)" % C.PISTOL_AMMO, C.PRICE_PISTOL),
    "shotgun": ("SHOTGUN (+%d SHELLS)" % C.SHOTGUN_AMMO, C.PRICE_SHOTGUN),
    "ammo": ("AMMO FOR YOUR GUNS", C.PRICE_AMMO),
    "spikes": ("SPIKE STRIP", C.PRICE_SPIKES),
    "roadblock": ("ROADBLOCK", C.PRICE_ROADBLOCK),
    "banana": ("BANANA PEEL", C.PRICE_BANANA),
    "donuts": ("BOX OF DONUTS", C.PRICE_DONUTS),
    # v0.9
    "chicken": ("RUBBER CHICKEN", C.PRICE_CHICKEN),
    "whoopee": ("WHOOPEE CUSHION", C.PRICE_WHOOPEE),
    "box": ("CARDBOARD BOX (C: HIDE IN IT)", C.PRICE_BOX),
    # v0.12
    "smg": ("SMG (+%d ROUNDS)" % C.SMG_AMMO, C.PRICE_SMG),
    "ar": ("ASSAULT RIFLE (+%d ROUNDS)" % C.AR_AMMO, C.PRICE_AR),
    "sniper": ("SNIPER RIFLE (+%d ROUNDS)" % C.SNIPER_AMMO, C.PRICE_SNIPER),
    "grenade": ("GRENADE LAUNCHER (+%d ROUNDS)" % C.GRENADE_AMMO, C.PRICE_GRENADE),
    "rpg": ("RPG (+%d ROCKETS)" % C.RPG_AMMO, C.PRICE_RPG),
    "ticket": ("SCRATCH TICKET", C.PRICE_TICKET),
}
GUN_ITEM = {ARM_SMG: "smg", ARM_AR: "ar", ARM_SNIPER: "sniper", ARM_GRENADE: "grenade", ARM_RPG: "rpg"}
ITEM_GUN = {v: k for k, v in GUN_ITEM.items()}      # market crate name -> ARM_ slot, the other way round
# arsenal byte index carrying each gun's ammo count (see protocol.encode_self / arsenal_owns)
AMMO_BYTE_OF_ARM = {ARM_PISTOL: 2, ARM_SHOTGUN: 3, ARM_SMG: 11, ARM_AR: 12, ARM_SNIPER: 13,
                     ARM_GRENADE: 14, ARM_RPG: 15}
# automap dot: how long a line to draw pointing where a gun-toting player is aiming
GUN_LINE_LEN = {ARM_PISTOL: 4, ARM_SHOTGUN: 6, ARM_SMG: 5, ARM_AR: 7, ARM_SNIPER: 8,
                 ARM_GRENADE: 6, ARM_RPG: 8}
# slot -> the bang it makes; the launchers get a whoosh on the way out and S_BOOM on arrival instead
GUN_SOUND = {ARM_PISTOL: S_PISTOL, ARM_SHOTGUN: S_SHOTGUN, ARM_SMG: S_SMG, ARM_AR: S_RIFLE,
             ARM_SNIPER: S_SNIPER, ARM_GRENADE: S_WHOOSH, ARM_RPG: S_WHOOSH}

SLOT_LABEL = {
    "Engine": "ENGINE", "Transmission": "GEARBOX", "ECU": "ECU", "Exhaust": "EXHAUST",
    "WheelFL": "FRONT-L WHEEL", "WheelFR": "FRONT-R WHEEL", "WheelRL": "REAR-L WHEEL",
    "WheelRR": "REAR-R WHEEL", "Hood": "HOOD", "DoorL": "LEFT DOOR", "DoorR": "RIGHT DOOR",
    "BumperF": "FRONT BUMPER", "BumperR": "REAR BUMPER", "Seats": "SEATS",
}

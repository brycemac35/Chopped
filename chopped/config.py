"""
config.py -- every tuning number in the game lives here, so that when the
game feels wrong at 3 AM you only have to be angry at one file.

Units: metres, seconds, dollars. Screen y points DOWN (like every sane 2D
engine and exactly no maths textbooks).
"""

import math

GAME_TITLE = "Chopped"
VERSION = 3  # bump when the wire protocol changes so old clients get a polite "no"

# --------------------------------------------------------------------------
# Rendering scale
# --------------------------------------------------------------------------
# 5 px per metre makes a 2.4 x 4.4 m hatchback exactly 12 x 22 px -- tiny
# enough to feel GTA2, big enough that you can see its doors are missing.
PPM = 5
LOW_W, LOW_H = 480, 270          # the whole world is drawn at this res, then scaled up
DEFAULT_WINDOW = (1440, 810)     # 3x. 1080p screens get 4x in fullscreen.
FPS = 60

# --------------------------------------------------------------------------
# City layout
# --------------------------------------------------------------------------
TILE_M = 4.0                     # one tile = 4 m = 20 px. Roads are 3 tiles (12 m) wide:
                                 # wide enough to drift, narrow enough to regret it.
TILE_PX = int(TILE_M * PPM)
BLOCKS = 9                       # 9x9 city blocks; odd so the chop shop sits dead centre
ROAD_TILES = 3
BLOCK_TILES = 9                  # sidewalk + 7 building + sidewalk
PITCH = ROAD_TILES + BLOCK_TILES
MAP_TILES = BLOCKS * PITCH + ROAD_TILES   # 111 tiles = 444 m. Crossable in ~10 s at full tilt.
MAP_M = MAP_TILES * TILE_M
PARK_BLOCKS = 5                  # grass + trees: places to hide from cameras (trees block sight)
LOT_BLOCKS = 4                   # open parking lots: extra spots for victims, er, vehicles
CAMERA_COUNT = 12                # street cameras at intersections

# --------------------------------------------------------------------------
# Networking
# --------------------------------------------------------------------------
DEFAULT_PORT = 27015             # the Source-engine port. Your router has seen things.
SIM_HZ = 60                      # authoritative physics rate
INPUT_HZ = 30                    # clients spam inputs this often (inputs are tiny)
SNAPSHOT_HZ = 20                 # remote clients get world state this often
LOCAL_SNAPSHOT_HZ = 60           # the host's own loopback client gets every tick (zero lag for the host)
INTERP_DELAY = 0.10              # remote entities are drawn 100 ms in the past so there's
                                 # always two snapshots to lerp between even with packet loss
LOCAL_INTERP_DELAY = 0.034       # loopback: two ticks is plenty
TIMEOUT_S = 10.0                 # 10 s of silence = you're dead to us
MAX_PLAYERS = 4
MAX_PACKET = 1150                # stay under typical MTU minus VPN/PPPoE overhead
EVENT_KEEP_S = 4.0               # unacked events retried for this long, then we give up
NET_CULL_RADIUS = 95.0           # peds/pickups farther than this aren't sent to you

# --------------------------------------------------------------------------
# On-foot
# --------------------------------------------------------------------------
PLAYER_RADIUS = 0.4
WALK_SPEED = 4.6                 # brisk "I'm definitely not stealing anything" pace
SPRINT_SPEED = 7.8               # Usain Bolt with a car door
TWO_HAND_SPEED_MULT = 0.82       # hoods are awkward, doors are worse
EXHAUSTED_SPEED_MULT = 0.55
STAMINA_MAX = 100.0
STAMINA_SPRINT_DRAIN = (12.0, 22.0, 38.0)   # per second: empty / one-handed / two-handed
STAMINA_WALK_2H_DRAIN = 8.0      # just carrying a bumper is cardio
STAMINA_REGEN = 18.0
STAMINA_REGEN_DELAY = 0.9        # catch your breath before you get it back
STAMINA_RECOVER_AT = 25.0        # exhausted until you're back above this
INTERACT_RANGE_CAR = 3.2         # metres from car centre for door stuff
INTERACT_RANGE_SLOT = 2.4        # metres from a slot anchor for stripping
INTERACT_RANGE_PICKUP = 1.6
INTERACT_RANGE_BENCH = 2.2
TAP_HOLD = 0.2                   # holds shorter than this fire on a single tap

# --------------------------------------------------------------------------
# Car physics (arcade; tuned by feel, not by Newton)
# --------------------------------------------------------------------------
CAR_LEN = 4.4
CAR_WID = 2.4
CAR_CIRCLE_R = 1.2               # a car is two circles in a trench coat
CAR_CIRCLE_OFF = 1.0             # circles sit this far forward/back of centre
CAR_MASS = 1000.0
COP_MASS = 1250.0                # cops are heavier: armour, donuts, attitude
CAR_INERTIA_K = (CAR_LEN ** 2 + CAR_WID ** 2) / 12.0
ACCEL_PER_100_POWER = 8.7        # m/s^2 at 100 part-power; a stock Kei is exactly 100
CIV_TOP_SPEED = 45.0
COP_TOP_SPEED = 48.0             # cops win the straights...
COP_ACCEL_MULT = 1.35            # ...and launch harder, but their steering is dumb, so corners are yours
DRAG_K = ACCEL_PER_100_POWER / (50.0 ** 2)  # quadratic drag: terminal ~50 m/s at 100 power,
                                 # so worn engines top out lower all by themselves
ROLL_DECEL = 1.5                 # coasting slows you, gently
BRAKE_DECEL = 26.0               # brakes are strong: arcade games are about stopping to steal
REVERSE_FRAC = 0.55
REVERSE_MAX = 11.0
HANDBRAKE_DECEL = 9.0
GRIP = 13.0                      # 1/s lateral velocity decay. High = on rails.
HANDBRAKE_GRIP = 1.1             # ...and this is the "oh no, sideways" number
SLIDE_GRIP_MULT = 0.65           # once you're already sliding fast, tyres give up a bit more
SLIDE_THRESHOLD = 7.0
GRASS_GRIP_MULT = 0.55           # parks are for drifting
GRASS_DRAG = 3.0
STEER_RATE_LOW = 3.1             # rad/s at walking pace: park it like a pro
STEER_RATE_HIGH = 1.25           # rad/s at top speed: 90 deg corners need a lift or a handbrake
STEER_FULL_AT = 5.0              # below this speed steering fades out (no spinning on the spot)
STEER_RESPONSE = 10.0            # how fast yaw rate chases the target
HANDBRAKE_YAW_MULT = 1.55
PARKED_BRAKE = 12.0              # driverless cars drag their feet so bumps don't send them to the next suburb
RESTITUTION_WALL = 0.28
RESTITUTION_CAR = 0.35
MISSING_WHEEL_GRIP = 0.22        # per missing wheel
MISSING_WHEEL_TOP = 0.16         # per missing wheel
MISSING_WHEEL_PULL = 0.55        # rad/s of "why is it going left" per missing wheel

# --------------------------------------------------------------------------
# Crashes: judged on delta-v (how hard you STOPPED), not how fast you were going
# --------------------------------------------------------------------------
CRASH_DENT_DV = 6.0              # a firm bump: dents + maybe a panel pops off
CRASH_PANEL_CHANCE = 0.35
CRASH_EJECT_DV = 11.0            # everybody out, the fun way
CRASH_WHEEL_DV = 18.7            # wheels have left the chat
CRASH_COOLDOWN = 0.35            # sustained scraping shouldn't count as 20 crashes per second
TUMBLE_MIN, TUMBLE_MAX = 1.2, 4.0
BODY_HIT_SPEED = 5.0             # cars faster than this relative to you = you go ragdoll
COP_IGNITE_REL_SPEED = 25.0      # T-bone a cop harder than this and it catches fire
COP_BURN_TIME = 3.0
EXPLOSION_RADIUS = 7.0
EXPLOSION_PUSH = 14.0

# --------------------------------------------------------------------------
# Heat & witnesses (shared 0..100)
# --------------------------------------------------------------------------
HEAT_MAX = 100.0
HEAT_BREAKIN = 10.0
WITNESS_RATE_COP = 5.0
WITNESS_RATE_PED = 3.0
WITNESS_RATE_OWNER = 3.0
WITNESS_RATE_CAMERA = 2.0
WITNESS_RANGE_COP = 45.0
WITNESS_RANGE_PED = 24.0
WITNESS_RANGE_OWNER = 40.0
WITNESS_RANGE_CAMERA = 22.0
HEAT_COOL_DELAY = 4.0            # nobody saw you for this long...
HEAT_COOL_RATE = 3.0             # ...then heat drains this fast
WITNESS_CHECK_HZ = 10            # LOS raycasts are the expensive bit; 10 Hz is plenty

# --------------------------------------------------------------------------
# Cops
# --------------------------------------------------------------------------
MAX_COPS = 2
COP_SPAWN_GAP = 2.0
COP_REINFORCE_DELAY = 9.0        # after you blow one up, dispatch takes a moment to stop crying
COP_SPAWN_MIN_DIST = 45.0
COP_DESPAWN_AT_ZERO = 3.0
HORN_CONFUSE_RANGE = 40.0
HORN_CONFUSE_TIME = 3.0
HORN_CONFUSE_COOLDOWN = 7.0      # (our call) a cop can't be re-donut'd for 7 s, or holding H is god mode
ARREST_RANGE = 3.2
ARREST_TIME = 1.0
CUFFED_TIME = 5.0

# --------------------------------------------------------------------------
# Traffic & NPCs
# --------------------------------------------------------------------------
MAX_CIVILIAN_CARS = 4
CIV_RESPAWN_DELAY = 5.0
CIV_SPAWN_MIN_DIST = 25.0
ABANDON_TOW_TIME = 60.0          # (our call) stolen cars left far from everyone get towed so the city refills
ABANDON_DIST = 110.0
PED_COUNT = 26
PED_SPEED = 1.4
PED_TUMBLE = 2.6
CLOWN_CHANCE = 0.12
CLOWN_COUNT = 4
CLOWN_LIFETIME = 40.0
CLOWN_SPEED = 3.2
OWNER_CHANCE = 0.15
OWNER_SPAWN_DIST = 8.0
OWNER_SPEED = 5.5                # faster than walking, slower than sprinting: he's in slippers
OWNER_GIVE_UP = 90.0
BREAKIN_TIME = 8.0
HOTWIRE_TIME = 6.0
DELIVER_MAX_SPEED = 4.0
CRUSH_TIME = 4.0

# --------------------------------------------------------------------------
# Economy (shared wallet)
# --------------------------------------------------------------------------
START_CASH = 300
RENT_AMOUNT = 150
RENT_PERIOD = 60.0
DEBT_GRACE = 120.0               # two minutes in the red and the landlord changes the locks
GAMEOVER_BANNER = 6.0
SHELL_VALUE = 150
CRUSH_DOLLY_FRACTION = 0.5
SELL_TIME = 1.0
INSTALL_TIME = 3.0
PICKUP_TIME = 0.3
PICKUP_LIFETIME = 600.0          # ten minutes, then the raccoons take it
PICKUP_SHRINK = 30.0             # last 30 s it visibly shrinks
MAX_PICKUPS = 90

TOAST_TIME = 3.5


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def wrap_angle(a):
    """Map any angle into (-pi, pi]."""
    a = (a + math.pi) % (2.0 * math.pi) - math.pi
    return a

"""
config.py -- every tuning number in the game lives here, so that when the
game feels wrong at 3 AM you only have to be angry at one file.

Units: metres, seconds, dollars. Screen y points DOWN (like every sane 2D
engine and exactly no maths textbooks).
"""

import math

GAME_TITLE = "Chopped"
VERSION = 7  # bump when the wire protocol changes so old clients get a polite "no"
RELEASE = (0, 7, 0)  # the number on the exe's Properties tab and the menu. Bump per build you hand out.

# --------------------------------------------------------------------------
# Rendering scale
# --------------------------------------------------------------------------
# 5 px per metre makes a 2.4 x 4.4 m hatchback exactly 12 x 22 px -- tiny
# enough to feel GTA2, big enough that you can see its doors are missing.
PPM = 5
LOW_W, LOW_H = 640, 360          # the whole world is drawn at this res, then scaled up by a whole
                                 # number (v0.7, was 480x270: Bryce wanted it smoother). 1080p
                                 # fullscreen is exactly 3x, 1440p is 4x.
DEFAULT_WINDOW = (1280, 720)     # 2x, if we can't ask the desktop how big it is
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
INPUT_HZ = 60                    # one input per sim tick: client-side prediction replays them
                                 # tick-for-tick, so the server must see every one (~3 KB/s up)
SNAPSHOT_HZ = 20                 # remote clients get world state this often
LOCAL_SNAPSHOT_HZ = 60           # the host's own loopback client gets every tick (zero lag for the host)
INTERP_DELAY = 0.10              # remote entities are drawn 100 ms in the past so there's
                                 # always two snapshots to lerp between even with packet loss
LOCAL_INTERP_DELAY = 0.034       # loopback: two ticks is plenty
TIMEOUT_S = 10.0                 # 10 s of silence = you're dead to us
PREDICT_CORRECT_RATE = 12.0      # 1/s: how fast a prediction miss is smoothed away (~80 ms).
                                 # Faster looks like a snap, slower looks like you're on ice.
PREDICT_SNAP_DIST = 4.0          # misses bigger than this (respawn, arrest) teleport instead
PREDICT_MAX_REPLAY = 90          # ticks of unacknowledged input we keep (1.5 s of ping. Please don't.)
PREDICT_OBSTACLE_RANGE = 14.0    # other cars this close are simulated as things to bump into
MAX_PLAYERS = 4
MAX_PACKET = 1150                # stay under typical MTU minus VPN/PPPoE overhead
EVENT_KEEP_S = 4.0               # unacked events retried for this long, then we give up
NET_CULL_RADIUS = 95.0           # peds/pickups farther than this aren't sent to you

# --------------------------------------------------------------------------
# On-foot
# --------------------------------------------------------------------------
PLAYER_RADIUS = 0.4
# (v0.5: everything faster -- Bryce wanted it to play quicker, and first-person
# at jogging pace feels like wading through soup)
WALK_SPEED = 6.0                 # brisk "I'm definitely not stealing anything" pace
SPRINT_SPEED = 10.0              # Usain Bolt with a car door
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
INTERACT_RANGE_DOLLY = 1.8
TAP_HOLD = 0.2                   # holds shorter than this fire on a single tap
AIM_REACH = 1.0                  # you interact with whatever's this far in front of your face
CAR_AIM_RANGE = 1.5              # ...if the car's bodywork is within this of that point

# The hand dolly: the only way to move an engine without crushing the car.
DOLLY_COUNT = 1                  # one hand truck. Co-op means taking turns. And arguing.
DOLLY_SPEED_MULT = 0.85          # pushing an empty dolly is basically a brisk walk
DOLLY_LOADED_SPEED_MULT = 0.62   # an engine on a hand truck: slow, heavy, deeply satisfying
DOLLY_LOAD_TIME = 1.0            # tipping a loose engine onto it
DOLLY_OFFSET = 1.1               # it rolls along this far in front of you
DOLLY_RETURN_TIME = 90.0         # left unattended outside the shop this long -> "someone" brings it back

# --------------------------------------------------------------------------
# Car physics (v0.7: tyres! Newton finally got a say, but feel still has a veto)
# --------------------------------------------------------------------------
# A bicycle model: one tyre per axle, slip angles, a Pacejka-ish grip curve
# that falls off past the peak (that fall-off IS drifting), a friction ellipse
# so throttle steals rear grip (power oversteer), weight transfer, and a
# handbrake that locks the rear. Per-model mass/grip/top speed live in
# vehicles.py; these are the knobs every car shares.
CAR_LEN = 4.4                    # the Kei's box (other models: vehicles.MODELS)
CAR_WID = 2.4
CAR_MASS = 1000.0
COP_MASS = 1250.0                # cops are heavier: armour, donuts, attitude
CAR_INERTIA_K = (CAR_LEN ** 2 + CAR_WID ** 2) / 12.0
GRAVITY = 9.81
ACCEL_PER_100_POWER = 8.7        # m/s^2 of engine push at 100 part-power (tyres permitting)
CIV_TOP_SPEED = 45.0             # (the Kei's; vehicles.MODELS has everyone's)
COP_TOP_SPEED = 48.0             # cops win the straights...
COP_ACCEL_MULT = 1.35            # ...and launch harder, but their steering is dumb, so corners are yours
DRAG_K = ACCEL_PER_100_POWER / (80.0 ** 2)  # quadratic drag: worn engines run out of puff early
ROLL_DECEL = 1.5                 # coasting slows you, gently
BRAKE_DECEL = 26.0               # what the pedal ASKS for; the tyres decide what you get (~12 m/s^2)
REVERSE_FRAC = 0.55
REVERSE_MAX = 11.0
PARKED_BRAKE = 12.0              # driverless cars have the handbrake on AND the wheels chocked
TIRE_GRIP = 1.8                  # arcade tyres: ~1.5 g of cornering. Real road tyres do ~0.9, and
                                 # real city blocks aren't 48 m apart with a chop shop in the middle.
TIRE_B = 9.0                     # grip curve stiffness: peak grip at ~9 degrees of slip...
TIRE_C = 1.55                    # ...then it sags to ~70% as you go sideways. That sag is the drift.
TIRE_LONG = 1.7                  # tyres push/brake harder than they corner (arcade ellipse, not a circle)
TIRE_VMIN = 2.5                  # m/s: slip angles below this speed are "just parking", not physics
WHEELSPIN_AT = 0.8               # throttle using more than this share of rear grip starts to spin it up...
WHEELSPIN_LOSS = 1.8             # ...and lateral grip drops this fast past that point (power oversteer)
HANDBRAKE_MU = 0.55              # locked rear tyres slide at this share of grip: yank it, the tail comes out
HANDBRAKE_DRIVE = 0.35           # (RWD) how much engine still gets through a locked rear. Clutch kick!
WEIGHT_TRANSFER = 1.0            # 1 = real; lift off mid-corner and feel the nose tuck in
FRONT_WEIGHT = 0.52              # share of weight on the front axle (FWD vans: 0.6)
AXLE_FRAC = 0.63                 # axles sit at this share of the half-length from the middle
STEER_LOCK_LOW = 0.72            # rad of front-wheel angle at parking speed (generous: arcade)...
STEER_LOCK_HIGH = 0.12           # ...shrinking to this at 35 m/s, so keyboard taps don't spin you
STEER_LOCK_SPEED = 35.0
STEER_RATE = 4.2                 # rad/s the wheel turns: full lock in about a seventh of a second
STEER_ALIGN = 0.85               # hands off the keys: the fronts follow the car's actual direction
                                 # (caster). That's what lets a keyboard catch a slide.
STEER_ALIGN_MAX = 0.9            # ...up to ~50 degrees of self-countersteer, like a proper drift car
SLIDE_DRAG = 0.9                 # sideways is slow: scrub this share of excess slide energy (per s)
GRASS_GRIP_MULT = 0.55           # parks are for drifting
GRASS_DRAG = 3.0
RESTITUTION_WALL = 0.28
RESTITUTION_CAR = 0.35
MISSING_WHEEL_GRIP = 0.45        # that corner's axle keeps this share of grip per missing wheel
MISSING_WHEEL_TOP = 0.16         # per missing wheel
MISSING_WHEEL_PULL = 0.55        # rad/s of "why is it going left" per missing wheel
AI_TRACTION = 0.8                # cops and traffic have traction control (players don't; players drift)
AI_STEER_LOCK = 0.8              # ...and a bit less lock at speed, so they don't pirouette into shops
BANANA_SPIN_TIME = 1.6           # s the rear tyres are on banana
BANANA_GRIP = 0.12               # what's left of the rear grip while they are
NOS_ACCEL = 9.0                  # m/s^2 extra, like being rear-ended by a rocket
NOS_TOP_MULT = 1.25
NOS_TANK = 4.0                   # seconds of boost when full
NOS_REFILL = 0.25                # s of boost regained per second (fills in 16 s)

LIVERY_CHANCE = 0.3              # v0.7: stripes, flames, polka dots... 30% of the city dresses up
CIV_GLOW_CHANCE = 0.06           # neon underglow on a parked car: someone's pride and joy. Now yours.

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
ARREST_RANGE = 1.0               # m from the cop car's bodywork (v0.7; was 3.2 from its middle, same thing
                                 # for a Kei, fairer now cars come in sizes)
ARREST_TIME = 1.0
CUFFED_TIME = 5.0

# --------------------------------------------------------------------------
# Traffic & NPCs
# --------------------------------------------------------------------------
MAX_CIVILIAN_CARS = 6            # (v0.5: was 4) more marks on the street = less wandering around
CIV_RESPAWN_DELAY = 3.0
CIV_SPAWN_MIN_DIST = 25.0
ABANDON_TOW_TIME = 60.0          # (our call) stolen cars left far from everyone get towed so the city refills
ABANDON_DIST = 110.0
PED_COUNT = 26
PED_SPEED = 1.4
PED_TUMBLE = 2.6
PED_FLEE_SPEED = 5.0             # panic jog: faster than walking, slower than you. They'll live.
PED_FLEE_TIME = 3.0              # how long a scare lasts before they go back to their podcast
PED_FLEE_CAR_SPEED = 14.0        # a car coming at them faster than this (~50 km/h)...
PED_FLEE_RADIUS = 12.0           # ...from this close sends them running
PED_FLEE_CRASH_RADIUS = 18.0     # crashes and explosions scatter everyone this close
PED_FLEE_CHASE_RADIUS = 22.0     # with cops rolling, anyone this near a wanted target bolts

# Moving traffic. Not witnesses (heat stays exactly as tuned) and not
# stealable while someone's driving it -- they're rolling obstacles, crash
# fodder and a reason to keep your eyes on the road.
TRAFFIC_COUNT = 8                # enough to T-bone, not enough to gridlock a 444 m city
TRAFFIC_SPEED = 12.0             # m/s (~43 km/h). Commuting, not fleeing.
TRAFFIC_TURN_SPEED = 6.0         # slow for corners so they don't end up in a cafe
TRAFFIC_LANE_OFFSET = 1.6        # m right of the centre line. Parked cars sit at 4.2, so they fit past.
TRAFFIC_SPAWN_MIN_DIST = 70.0    # never pop in where anyone could see it happen
TRAFFIC_RECYCLE_DIST = 140.0     # drifted this far from every player -> respawn somewhere useful
TRAFFIC_HONK_AFTER = 1.5         # blocked this long -> lean on the horn (doesn't confuse cops)
TRAFFIC_OVERTAKE_AFTER = 2.5     # stuck behind a stopped car this long -> swing out and pass
TRAFFIC_SHAKEN_TIME = 2.0        # after a bump they sit there, stunned, honking
TRAFFIC_RESPAWN_DELAY = 1.0      # replacements appear off-screen, so there's no need to be coy
CLOWN_CHANCE = 0.12
CLOWN_COUNT = 4
CLOWN_LIFETIME = 40.0
CLOWN_SPEED = 3.2
OWNER_CHANCE = 0.15
OWNER_SPAWN_DIST = 8.0
OWNER_SPEED = 7.0                # faster than walking, slower than sprinting: he's in slippers
OWNER_GIVE_UP = 90.0
BREAKIN_TIME = 4.0               # (v0.5: halved from 8) smash, grab, go
HOTWIRE_TIME = 3.0               # (v0.5: halved from 6)
DELIVER_MAX_SPEED = 4.0
CRUSH_TIME = 2.0

# --------------------------------------------------------------------------
# Violence (v0.6: Bryce wants to punch people, rob them, and have guns).
# Nobody dies: everyone just hits the deck, cartoon-style, and gets back up
# furious. Every act of violence is loud, so it all costs heat.
# --------------------------------------------------------------------------
PUNCH_RANGE = 1.9                # metres from you, in front of you
PUNCH_CONE = 0.8                 # radians either side of where you look
PUNCH_COOLDOWN = 0.4
PUNCH_KNOCKDOWN = 3.0            # a punched pedestrian stays down this long: long enough to rob
PUNCH_PLAYER_TUMBLE = 1.0        # punching your mate just knocks them over. Co-op!
PUNCH_HEAT = 5.0                 # they scream. People hear.
ROB_TIME = 0.8                   # rifling through a wallet, hold E
WALLET_MIN, WALLET_MAX = 15, 90  # dollars on an average pedestrian
WALLET_REFILL = 180.0            # a robbed pedestrian hits an ATM eventually
ROB_HEAT = 4.0
SURRENDER_RANGE = 10.0           # point a gun at someone this close and their hands go up
SURRENDER_CONE = 0.22
PISTOL_RANGE = 60.0
PISTOL_COOLDOWN = 0.3
SHOTGUN_RANGE = 25.0
SHOTGUN_COOLDOWN = 0.85
SHOTGUN_PELLETS = 7
SHOTGUN_SPREAD = 0.13            # radians either side
SHOT_KNOCKDOWN = 5.0             # hit by a bullet: down, dazed, very upset
SHOT_PLAYER_TUMBLE = 1.8         # ...and your mate drops whatever they were carrying
GUNSHOT_HEAT = 8.0               # per shot, if any pedestrian or cop is within earshot
GUNSHOT_EARSHOT = 50.0
SHOOT_COP_HEAT = 100.0           # shooting at a police car: straight to maximum. Obviously.
COP_CAR_HITS = 8                 # pistol rounds (pellets count too) until a cop car catches fire
TIRE_HIT_RADIUS = 0.9            # a round landing this close to a wheel shreds that tyre

# --------------------------------------------------------------------------
# Black market (crates along the shop's west wall) and traps
# --------------------------------------------------------------------------
PRICE_PISTOL = 350               # comes loaded with PISTOL_AMMO
PRICE_SHOTGUN = 800
PRICE_AMMO = 60                  # tops up whatever guns you own
PRICE_SPIKES = 120
PRICE_ROADBLOCK = 200
PISTOL_AMMO = 24
SHOTGUN_AMMO = 10
MAX_AMMO = 99
MAX_TRAPS_EACH = 5
BUY_TIME = 0.6
TRAP_PLACE_DIST = 3.5            # traps go down this far in front of you, snapped across the road
SPIKE_LEN, SPIKE_WID = 6.0, 0.7  # half a road: spikes shred the lane they're in
SPIKE_USES = 3                   # cars it can shred before the strip is scrap
ROADBLOCK_LEN, ROADBLOCK_WID = 11.0, 1.0   # the whole road: traffic stops dead and honks
ROADBLOCK_BREAK_DV = 11.0        # hit it this hard and it's matchwood (same as the eject threshold)
TRAP_LIFETIME = 150.0
MAX_TRAPS = 12
CARJACK_TIME = 1.5               # yank the door, yank the driver
CARJACK_MAX_SPEED = 2.0          # it has to be (nearly) stopped
CARJACK_HEAT = 12.0              # worse than a quiet break-in: there's a witness in the gutter

# --------------------------------------------------------------------------
# Economy (shared wallet)
# --------------------------------------------------------------------------
START_CASH = 300
# Rent is due once a day, at midnight, and the landlord gets greedier every day:
# day 1 is $100, day 2 $175, day 3 $250... Early days are a breather, by day 6
# you're paying more than the old $150-a-minute and it only goes up.
DAY_LENGTH = 180.0               # seconds: dawn to midnight
RENT_BASE = 100
RENT_PER_DAY = 75
DEBT_GRACE = 120.0               # two minutes in the red and the landlord changes the locks
GAMEOVER_BANNER = 6.0
SHELL_VALUE = 150
CRUSH_DOLLY_FRACTION = 0.5
SELL_TIME = 0.5                  # (v0.5: halved)
INSTALL_TIME = 1.5               # (v0.5: halved)
PICKUP_TIME = 0.3
BUY_MARKUP = 1.6                 # the parts counter charges 60% over street value: stealing stays
                                 # the better deal, buying is for when you want it NOW
PICKUP_LIFETIME = 600.0          # ten minutes, then the raccoons take it
PICKUP_SHRINK = 30.0             # last 30 s it visibly shrinks
MAX_PICKUPS = 90

TOAST_TIME = 3.5
MUSIC_VOLUME = 0.45              # the beat sits under the engine and the sirens, not on top of them

# --------------------------------------------------------------------------
# First-person view (the Doom-style one)
# --------------------------------------------------------------------------
FP_FOV = 90.0                    # degrees across. Doom's number, and it keeps side streets in view
FP_EYE = 1.6                     # metres: standing eye height
FP_EYE_CAR = 1.2                 # sitting in a Kei, knees round your ears
FP_FLOOR_DIST = 70.0             # metres of textured street before it fades to haze
FP_SPRITE_DIST = 95.0            # beyond this, cars and people aren't drawn (matches the net cull)
FP_TURN_SPEED = 2.8              # rad/s turning with the arrow keys
MOUSE_SENS = 0.0032              # rad per mouse pixel
FP_BOB = 0.06                    # metres of head bob when walking (Doom had lots; this has some)


def rent_for_day(day):
    return RENT_BASE + RENT_PER_DAY * (max(1, day) - 1)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def wrap_angle(a):
    """Map any angle into (-pi, pi]."""
    a = (a + math.pi) % (2.0 * math.pi) - math.pi
    return a

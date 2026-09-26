"""
config.py -- every tuning number in the game lives here, so that when the
game feels wrong at 3 AM you only have to be angry at one file.

Units: metres, seconds, dollars. Screen y points DOWN (like every sane 2D
engine and exactly no maths textbooks).
"""

import math

GAME_TITLE = "Chopped"
VERSION = 13  # bump when the wire protocol changes so old clients get a polite "no"
RELEASE = (0, 12, 1)  # the number on the exe's Properties tab and the menu. Bump per build you hand out.

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
BLOCKS = 11                      # (v0.10, Bryce: "bigger city"; was 9) odd so the chop shop sits centre
ROAD_TILES = 3
BLOCK_TILES = 9                  # sidewalk + 7 building + sidewalk
PITCH = ROAD_TILES + BLOCK_TILES
MAP_TILES = BLOCKS * PITCH + ROAD_TILES   # (v0.10) 135 tiles = 540 m (was 111 = 444 m)
MAP_M = MAP_TILES * TILE_M
PARK_BLOCKS = 6                  # grass + trees: places to hide from cameras (trees block sight)
PRECINCT_MIN_BLOCKS = 3          # (v0.8) the police station is at least this many blocks from the shop
LOT_BLOCKS = 5                   # open parking lots: extra spots for victims, er, vehicles
CAMERA_COUNT = 14                # street cameras at intersections
# (v0.10, Bryce: "back alleys between big building sizes") every ordinary building block gets
# a service alley cut through the middle of it: too narrow to drive down at any speed, but a
# handy foot shortcut and a place to duck out of a witness's line of sight.
ALLEY_W = 1                      # tiles wide (4 m: a tight squeeze, no car is getting down there)

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
MAX_PACKET = 1200                # (v0.10: was 1150) stay under typical MTU minus VPN/PPPoE
                                 # overhead -- nudged up to make room for a personal car per
                                 # player and five shop doors instead of one, worst case
EVENTS_PER_SNAPSHOT = 6          # toasts/sounds per packet; the rest ride the next one (they're resent till acked)
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
STAMINA_MAX = 140.0              # (v0.10, Bryce: "increase stamina"; was 100 -- about 40% more legs)
STAMINA_SPRINT_DRAIN = (12.0, 22.0, 38.0)   # per second: empty / one-handed / two-handed
STAMINA_WALK_2H_DRAIN = 8.0      # just carrying a bumper is cardio
STAMINA_REGEN = 18.0
STAMINA_REGEN_DELAY = 0.9        # catch your breath before you get it back
STAMINA_RECOVER_AT = 25.0        # exhausted until you're back above this
JUMP_SPEED = 6.2                 # m/s straight up: ~0.9 m of air. Doomguy couldn't do this.
JUMP_GRAVITY = 21.0              # snappier than real gravity; floaty jumps feel like the moon
JUMP_STAMINA = 5.0               # per jump (bunny-hopping from the cops is a valid strategy)
AIR_CONTROL = 3.0                # 1/s: how much you can steer mid-air (ground is 16)
HURDLE_HEIGHT = 0.45             # over this, you clear a roadblock (it's 1 m; you tuck your knees)
CAR_ROOF_Z = 1.6                 # people higher than this fly over cars instead of into them
CHUTE_SINK = 2.2                 # m/s: parachute descent (ejector seat)
INTERACT_RANGE_CAR = 3.2         # metres from car centre for door stuff
INTERACT_RANGE_SLOT = 2.4        # metres from a slot anchor for stripping
INTERACT_RANGE_PICKUP = 1.6
INTERACT_RANGE_BENCH = 2.2
INTERACT_RANGE_DOLLY = 1.8
# (v0.12.1, Bryce: "there are no quest NPC's") the people the jobs and the story talk about --
# Paige, the Fixer, Tommy, the Kingpin -- actually standing somewhere now. Talk to them with E.
TALK_RANGE = 1.8                 # m from where you're looking to the person, same feel as a pickup
TALK_COOLDOWN = 4.0              # s before the same person will repeat themselves (E-spam isn't a conversation)
STORY_NPC_R = 0.35               # m: they're solid, you bump into them like anyone else
COUNTER_GAP = 1.4                # m between the back wall and the counters: room for the staff behind them
CAR_PROMPT_TIME = 4.0            # s the driving controls stay on screen after you get in
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
TIRE_C = 1.4                    # ...then it sags to ~70% as you go sideways. That sag is the drift.
TIRE_LONG = 1.7                  # tyres push/brake harder than they corner (arcade ellipse, not a circle)
TIRE_VMIN = 2.5                  # m/s: slip angles below this speed are "just parking", not physics
WHEELSPIN_AT = 0.8               # throttle using more than this share of rear grip starts to spin it up...
WHEELSPIN_LOSS = 1.4             # ...and lateral grip drops this fast past that point (power oversteer)
HANDBRAKE_MU = 0.62              # locked rear tyres slide at this share of grip: yank it, the tail comes out
HANDBRAKE_DRIVE = 0.35           # (RWD) how much engine still gets through a locked rear. Clutch kick!
WEIGHT_TRANSFER = 0.5            # 1 = real. Half: you feel the nose dip and the tail squat, but a
                                 # turbo launch doesn't lift the front off the road (arcade tyres
                                 # pull ~2 g, and real physics at 2 g is a wheelie)
TRANSFER_MAX_G = 1.0             # ...and never more than 1 g's worth of it
FRONT_WEIGHT = 0.52              # share of weight on the front axle (FWD vans: 0.6)
AXLE_FRAC = 0.63                 # axles sit at this share of the half-length from the middle
STEER_LOCK_LOW = 0.72            # rad of front-wheel angle at parking speed (generous: arcade)...
STEER_LOCK_HIGH = 0.12           # ...shrinking to this at 35 m/s, so keyboard taps don't spin you
STEER_LOCK_SPEED = 35.0
STEER_RATE = 4.2                 # rad/s the wheel turns: full lock in about a seventh of a second
STEER_ALIGN = 1.0                # hands off the keys: the fronts follow the car's actual direction
                                 # (caster). That's what lets a keyboard catch a slide.
STEER_ALIGN_MAX = 1.0            # ...up to ~57 degrees of self-countersteer, like a proper drift car
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
# v0.8, Bryce: "the drifting feels too loose, please allow the driver to regain control when
# handbraking". The tyres are the same; these help your hands (see Physics._drift_assist).
DRIFT_ASSIST_START = 0.24        # rad (~17 degrees) of slide before the assist wakes up: small slides are yours
DRIFT_ASSIST_YAW = 7.0           # rad/s^2 per rad past that, turning the nose toward where you're going
DRIFT_ASSIST_DAMP = 8.0          # 1/s: how fast rotation that makes the slide WORSE is bled off
DRIFT_ASSIST_INTO = 0.55         # share of the help you still get while steering INTO the slide
DRIFT_ASSIST_MIN_SPEED = 4.0     # m/s: below this it's parking, not drifting
COUNTERSTEER_FROM = 0.12         # rad (~7 degrees) of slide before countersteer is "catching a slide"...
COUNTERSTEER_MARGIN = 0.08       # ...and then the wheels go this far past the direction of travel, no more
YAW_CAP_K = 1.25                  # yaw-rate cap, as a multiple of what the tyres hold in a steady turn...
YAW_CAP_INTO = 1.6               # ...times this while you're steering with the rotation...
YAW_CAP_RATE = 8.0               # ...and excess rotation is bled off this fast (1/s)
HANDBRAKE_MAX_YAW = 2.0          # rad/s: a handbrake yank swings the tail, it doesn't make a spinning top
AWD_FRONT_SHARE = 0.4            # 4x4s send this much of the push to the front wheels
BURNOUT_MAX_SPEED = 4.0          # m/s: above this, W+S together is just braking
BURNOUT_CREEP = 0.35             # m/s: a brake stand still crawls forward. That's the fun part.
BURNOUT_YAW = 1.8                # rad/s of donut with the wheel on the lock
BURNOUT_GRAB = 6.0               # 1/s: how fast the car settles into the stand
NOS_ACCEL = 9.0                  # m/s^2 extra, like being rear-ended by a rocket
NOS_TOP_MULT = 1.25
NOS_TANK = 4.0                   # seconds of boost when full
NOS_REFILL = 0.25                # s of boost regained per second (fills in 16 s)

# ---- revs and gears (v0.8): the tachometer and the engine note. Cosmetic: the tyre model
# decides how fast you go; drivetrain.Tacho decides what the engine sounds like doing it.
ENGINE_BANDS = 6                 # pre-rendered engine loops per voice, crossfaded by rpm
GEAR_SPREAD = 0.8                # gear n tops out at top * (n / gears) ** this: short first, tall top
GEAR_TOP_OVERRUN = 1.06          # top gear would reach the redline just past top speed
SHIFT_UP_AT = 0.93               # share of the redline where the box shifts up...
SHIFT_DOWN_AT = 0.55             # ...and it drops a gear when the one below would be this far up
SHIFT_TIME = 0.16                # s of throttle cut per shift (the "bwaaa-ap" between gears)
LAUNCH_REVS = 0.45               # pulling away, the clutch holds the revs this high
REV_RISE = 9.0                   # 1/s: revs chase the target this fast going up...
REV_FALL = 5.0                   # ...and this fast falling (flywheels are heavy)
LIMITER_PERIOD = 0.09            # s between rev-limiter cuts: brap-brap-brap
TURBO_SPOOL = 1.6                # 1/s: turbo lag. It's a feature.
TURBO_DUMP = 6.0                 # 1/s: boost falls off this fast when you lift
TURBO_WHISTLE_HZ = (2200, 3300, 4700, 6400)   # turbo whistle pitch bands, crossfaded by boost
ENGINE_HEAR_DIST = 45.0          # m: engines further off than this are just city noise
VTEC_AT = 0.64                   # share of the redline where VTEC kicks in, yo

LIVERY_CHANCE = 0.3              # v0.7: stripes, flames, polka dots... 30% of the city dresses up
CIV_GLOW_CHANCE = 0.06           # neon underglow on a parked car: someone's pride and joy. Now yours.

# --------------------------------------------------------------------------
# v0.7 ridiculous features
# --------------------------------------------------------------------------
EJECT_MIN_SPEED = 12.0           # m/s: below this, F just opens the door like a normal person
EJECT_SPEED = 15.0               # m/s straight up. About six metres. Then the parachute.
YEET_SPEED = 15.0                # m/s: a car hitting you harder than this sends you airborne
GNOME_COUNT = 14                 # (v0.10: was 12) garden gnomes about the city
GNOME_RESPAWN = 30.0             # s between replacement gnomes (gardeners are resilient)
GNOME_HEAT = 3.0                 # heat for pinching one. It's the principle of the thing.
ICECREAM_LURE = 25.0             # m: peds this close to a slow ice cream van go and queue for it
# ---- v0.8 ridiculous features ----
K9_HEAT = 60.0                   # from this heat, some cop cars bring a dog...
K9_CHANCE = 0.4                  # ...this often
K9_SPEED = 11.0                  # m/s: faster than your sprint. You can't outrun the dog.
K9_LIFETIME = 25.0
PANTSED_TIME = 9.0               # s without trousers after the dog gets them
PANTSED_SPEED_MULT = 0.55        # shuffling, ankles bound, dignity gone
STREAKER_EVERY = (90.0, 180.0)   # s between streakers
STREAKER_SPEED = 8.5
STREAKER_LIFETIME = 30.0
STREAKER_COP_RANGE = 45.0        # cops this close would much rather chase HIM
STREAKER_REWARD = 50             # a citizen's arrest: $50 from a grateful city...
STREAKER_HEAT_CUT = 10.0         # ...and the police think you're alright, actually
SPEEDCAM_SPEED = 25.0            # m/s (90 km/h) past a camera in your own clean ride...
SPEEDCAM_RANGE = 12.0
SPEEDCAM_FINE = 40               # ...is a $40 ticket in the post
SPEEDCAM_COOLDOWN = 10.0
SMOKE_SCREEN_AT = 1.5            # s of burnout before the smoke is thick enough to hide in...
SMOKE_SCREEN_EVERY = 0.8         # ...then a new cloud this often...
SMOKE_SCREEN_R = 4.5             # ...this big...
SMOKE_SCREEN_LIFE = 10.0         # ...lasting this long. Witnesses can't see through it.
SMOKE_SCREEN_MAX = 8
HOP_TIME = 0.7                   # s of hydraulic bounce per press of X (and you can't re-hop mid-air)
HOP_CROWD_RANGE = 14.0           # peds this close stop to enjoy the lowrider show (and don't witness)
PRICE_HYDRAULICS = 500

# --------------------------------------------------------------------------
# v0.7 mod shop and parts locker (garage.py)
# --------------------------------------------------------------------------
STASH_MAX = 40                   # parts the locker holds; overflow gets shoved out onto the floor
PRICE_PAINT = 150                # a respray: cheaper than a new car, pricier than a spray can
PRICE_LIVERY = 250               # stripes, flames, polka dots...
HORN_PRICES = [0, 120, 200, 150, 180, 250, 300]   # stock, clown, cucaracha, fart, goat, air, ice cream
PRICE_GLOW = 300                 # neon underglow: the car's personality, made of light
PRICE_NOS = 900                  # nitrous: expensive, because it's the most fun thing in the game
PRICE_EJECTOR = 600              # an ejector seat. In a Kei. For reasons.
PRICE_GNOME_MOUNT = 80           # the gnome ornament, if you didn't bring your own gnome

# --------------------------------------------------------------------------
# v0.7 slapstick: throwing, carrying, bowling, fighting back (brawl.py)
# --------------------------------------------------------------------------
BANNER_TIME = 2.5                # s a YEETED / HUMBLED / STRIKE! banner stays up
THROW_SPEED = 16.0               # m/s a thrown part leaves your hands at
THROW_HEAVY_MULT = 0.8           # doors and bumpers fly slower (they fly, though)
THROW_LIFT = 3.0                 # m/s upward: a flat arc, like a frisbee made of steel
THROW_COOLDOWN = 0.35
THROW_HIT_R = 0.75               # m: how close a flying part has to pass to connect
THROW_KNOCKDOWN = 3.0            # s a pedestrian stays down (x1.4 for a two-hander)
THROW_PLAYER_TUMBLE = 1.2        # s a crewmate stays down (friendly fire is still fire)
THROW_WEAR = 0.08                # condition lost per bonk: throwing parts isn't free
GRAB_RANGE = 1.6                 # m from your aim point to pick someone up (G)
CARRY_STRUGGLE = 7.0             # s before a carried pedestrian wriggles free
WRIGGLE_PRESSES = 5              # Space presses for a carried crewmate to break free
THROW_PERSON_SPEED = 21.0        # m/s (v0.9, "throw people farther": was 13). Hammer throwers weep.
THROWN_SLIDE_TIME = 0.8          # s a thrown person skids on landing (the bowling needs the roll-out)
THROW_PERSON_LIFT = 4.5          # ...and up, but only a little: a flat throw stays under 2 m (bowling
                                 # height) the whole way. ~13 m of flight, then a skid: ~25 m all in
THROWN_TUMBLE = 3.0              # s a thrown person spends rethinking things
BOWL_R = 1.0                     # m: a flying person knocks down anyone this close
STRIKE_COUNT = 3                 # people knocked over by one flying person = STRIKE!
HAYMAKER_CHARGE = 0.7            # s holding the punch before it's a haymaker
HAYMAKER_SPEED = 18.0            # m/s you send them off at...
HAYMAKER_LIFT = 7.0              # ...and up (they come down eventually)
HAYMAKER_TUMBLE = 4.0
DANCE_RADIUS = 14.0              # T: everyone this close has an opinion
DANCE_OFFEND_CHANCE = 0.3        # brave peds who take it personally
DANCE_LAUGH_TIME = 4.0           # s the rest stand there laughing (and can be robbed, or picked up)
DANCE_COP_HEAT = 3.0             # per reaction, if a cop can see you dancing
BRAVE_CHANCE = 0.35              # pedestrians who fight back instead of running
ARMED_CHANCE = 0.3               # ...and of those, how many are carrying (about 1 in 10 overall)
CARJACK_FIGHT_CHANCE = 0.5       # dragged-out drivers who come back swinging
BRAWL_TIME = 25.0                # s a grudge lasts
BRAWL_GRIT_MAX = 3               # knockdowns a brawler takes before they've had enough
BRAWL_RALLY_RADIUS = 14.0        # brave bystanders this close pile in when you start something
BRAWL_RALLY_CHANCE = 0.5
BRAWL_GIVE_UP = 45.0             # m: outrun them this far and they go home
BRAWL_SPEED = 7.4                # m/s: faster than your walk (6), slower than your sprint (10)
BRAWL_REACH = 1.2
BRAWL_PUNCH_COOLDOWN = 0.9
BRAWL_HIT_CHANCE = 0.7
BRAWL_PUNCH_TUMBLE = 0.9         # s on the floor per pedestrian punch (and your hands empty out)
PED_GUN_RANGE = 22.0             # armed pedestrians shoot from here...
PED_GUN_COOLDOWN = 1.3           # ...this often...
PED_GUN_ACCURACY = 0.3           # ...and hit this often. Enough.

# --------------------------------------------------------------------------
# Crashes: judged on delta-v (how hard you STOPPED), not how fast you were going
# --------------------------------------------------------------------------
CRASH_DENT_DV = 6.0              # a firm bump: dents + maybe a panel pops off
CRASH_PANEL_CHANCE = 0.35
CRASH_EJECT_DV = 11.0            # everybody out, the fun way
CRASH_WHEEL_DV = 18.7            # wheels have left the chat
CRASH_COOLDOWN = 0.35            # sustained scraping shouldn't count as 20 crashes per second
TUMBLE_MIN, TUMBLE_MAX = 1.2, 4.0
BODY_HIT_SPEED = 5.0             # bodywork moving INTO you faster than this = you go ragdoll (v0.9: a
                                 # parked car is a wall; your own sprint into it doesn't count)
CAR_HIT_CARRY = 1.0              # (v0.9) you leave with all of the car's speed...
CAR_HIT_KICK = 2.5               # ...plus a shove away from the bumper...
CAR_HIT_KICK_PER = 0.25          # ...that grows with the impact
CAR_HIT_SLIDE_DECAY = 0.8        # 1/s: then you SLIDE (tarmac is not a mattress. Neither is it grippy.)
CAR_HIT_SLIDE_TIME = 2.5         # s of low-friction skid before normal tumble friction takes over
COP_IGNITE_REL_SPEED = 25.0      # T-bone a cop harder than this and it catches fire
COP_BURN_TIME = 3.0
EXPLOSION_RADIUS = 7.0
EXPLOSION_PUSH = 14.0

# --------------------------------------------------------------------------
# Heat & witnesses (shared 0..100)
# --------------------------------------------------------------------------
HEAT_MAX = 100.0
HEAT_BREAKIN = 10.0
# (v0.10, Bryce: "make sure the heat takes longer to come up") witness rates cut by about
# 40% across the board, so a getaway takes longer to go from "fine" to "5 units incoming".
WITNESS_RATE_COP = 3.0
WITNESS_RATE_CAMERA = 1.2
WITNESS_RANGE_COP = 45.0
WITNESS_RANGE_PED = 24.0
WITNESS_RANGE_OWNER = 40.0
WITNESS_RANGE_CAMERA = 22.0
HEAT_COOL_DELAY = 4.0            # nobody saw you for this long...
HEAT_COOL_RATE = 3.0             # ...then heat drains this fast
WITNESS_CHECK_HZ = 15            # (v0.10: was 10) LOS raycasts are the expensive bit, but heat and
                                 # lethal status both hinge on this now, so it's worth polling faster
# (v0.10) a witness who breaks off instead of getting silenced doesn't add heat live any
# more -- they remember your face and phone it in a while later. Kill them first and they
# never make the call. "only tells cops after 10-15 seconds by phoning them."
PHONE_IN_DELAY = (10.0, 15.0)    # s between spotting a wanted crook and the call going out
PHONE_IN_HEAT = 15.0             # the jump when the call lands
MURDER_HEAT = 18.0               # (v0.10) shooting a civilian: it's the quiet way to lose a
                                 # witness, but it's still murder. Costs more than robbing them,
                                 # less than shooting a cop -- and it never wears off on its own.
# (v0.10) helicopters: from HELI_HEAT the chopper turns up. It's airborne, so walls and
# buildings don't stop it seeing you (rooftops would, if we bothered to model them) --
# duck indoors, not just out of an alley. Purely a witness source; nothing chases you from
# the sky. Rendered client-side off the snapshot's AL_HELI bit (see protocol.AL_HELI).
HELI_HEAT = 70.0
HELI_RANGE = 90.0
WITNESS_RATE_HELI = 2.5

# --------------------------------------------------------------------------
# Cops
# --------------------------------------------------------------------------
MAX_COPS = 5                     # dispatched units at 100% heat (v0.7, Bryce: "more plentiful"; was 2)
COP_TIERS = ((25.0, 1), (50.0, 2), (75.0, 3), (99.9, 5))   # heat -> units on the way (a wanted level)
COPS_PER_DAY = 18                # (v0.10, Bryce: "limited number of cops spawn / day") dispatch stops
                                 # sending FRESH units once this many have turned out today, win or
                                 # lose; units already out keep chasing, and patrols don't count
                                 # (they're not "dispatched"). Resets at midnight with the rent.
COP_TRACK_LOSE_TIME = 6.0        # (v0.10) a cop with no visual on anyone stops trusting its last-known
                                 # position after this long of not re-spotting it, and gives up the
                                 # chase instead of beelining forever (see Car.search_t, "walls need
                                 # to block cops' views better")
COP_TIP_DELAY = 5.0              # (v0.12.1) ...but "gives up" used to mean "parks in the middle of the
                                 # road forever": a dispatched car that spawned round a corner never
                                 # saw anyone, so it never moved, and the playtest could stand at 55
                                 # heat for a minute with four cop cars idling a block away. Now, this
                                 # long after losing the lead, dispatch radios a fresh tip.
COP_TIP_SCATTER = 20.0           # m: how vague that tip is ("suspect last seen near the laundromat").
                                 # Close enough to bring them round the block, vague enough that a
                                 # crook who's broken line of sight still has a chance to slip away.
PATROL_COPS = 2                  # cruisers that are ALWAYS out there, doing laps, being witnesses
PATROL_SPAWN_DIST = (60.0, 130.0)   # they turn up this far from the crew, never on top of you
PATROL_RECYCLE_DIST = 170.0
# v0.8, Bryce: "instead of the cops shooting you lethally right away have them try to handcuff
# you". Cars chase; an officer gets out to make the arrest; tasers at high heat; real bullets
# only once the crew has started shooting (see LETHAL_*).
COP_GUN_RANGE = 26.0             # lethal mode: cop cars shoot from the window from this close...
COP_GUN_COOLDOWN = 1.6           # ...this often...
COP_GUN_ACCURACY = 0.22          # ...and hit about this often (v0.10: was 0.28 -- a health bar means
                                 # a hit isn't instant death any more, but a small crowd of cops all
                                 # rolling the dice at once still added up to "wasted" almost every
                                 # time; missing more often spreads the damage out).
OFFICER_DEPLOY_RANGE = 22.0      # m: a cop car this close to a crook on foot lets its officer out
OFFICER_DEPLOY_SPEED = 6.0       # m/s: ...once it's slowed down enough to open the door
OFFICER_SPEED = 7.6              # m/s: faster than your walk (6), slower than your sprint (10). Run!
OFFICER_CHASE_RANGE = 70.0       # m: lose them by this much and they walk back to the car
OFFICER_GIVE_UP = 40.0           # s on foot before the officer gives up and goes back regardless
CUFF_RANGE = 1.3                 # m: close enough to reach for the cuffs
CUFF_TIME = 1.2                  # s of standing there being cuffed (x2 speed if you're on the floor)
CUFF_BREAK_PRESSES = 6           # Space presses to wriggle out of an officer's grip
OFFICER_KO_TIME = 2.2            # s an officer stays down after a punch (they're trained. A bit.)
ASSAULT_OFFICER_HEAT = 15.0      # punching a police officer is noticed. By the police.
TASER_HEAT = 50.0                # from this heat, officers draw tasers...
TASER_RANGE = 9.0                # ...and fire from this close (but not point blank: then it's cuffs)
TASER_MIN = 2.5
TASER_COOLDOWN = 3.0
TASER_ACCURACY = 0.55
TASER_TIME = 2.2                 # s of twitching on the floor. Plenty for the cuffs.
LETHAL_TIME = 45.0               # s the police are authorised to shoot to kill after the crew shoots
LETHAL_UNSEEN_TIME = 8.0         # (v0.10, Bryce: "poll heat value more often for changing lethal to
                                 # not noticed by cops") lethal mode also stands down this much sooner
                                 # once no cop currently has eyes on anyone wanted, instead of always
                                 # running the full LETHAL_TIME regardless of whether they've lost you
COP_HEAR_RANGE = 55.0            # m: a gunshot this close to any cop starts the lethal clock
OFFICER_GUN_RANGE = 20.0         # lethal mode: officers shoot from here...
OFFICER_GUN_COOLDOWN = 1.2
OFFICER_GUN_ACCURACY = 0.26      # (v0.10: was 0.33, same reasoning as COP_GUN_ACCURACY)
# dying (v0.8, Bryce: "if the cops do decide to lethally shoot you... you die, lose a/x % of your
# money depending on how many people are playing"): the crew loses DEATH_LOSS / players of its
# cash: 50% solo, 25% for two, 12.5% for four. Medical bills, split fairly.
DEATH_LOSS = 0.5
DEATH_TIME = 4.0                 # s of WASTED before you wake up at the shop
# (v0.10, Bryce: "wasted too much have a health bar instead of 1 hit") a police bullet is a
# wound, not an instant game-over: it takes BULLET_DAMAGE off a health bar, and only an empty
# bar is WASTED. Health regens on its own once nobody's shot at you for a few seconds --
# there's no first-aid kit to find, just don't get hit again for a bit.
PLAYER_HEALTH_MAX = 100.0
BULLET_DAMAGE = 34.0             # 3 clean hits and you're down; 2 is a serious scare
HEALTH_REGEN_DELAY = 6.0         # s since the last hit before you start mending
HEALTH_REGEN_RATE = 10.0         # HP/s once you do (full recovery from one hit in ~3.4 s)
# the precinct (v0.8): busted = locked up. Punch your way out, or get broken out.
CELL_SIZE = 6.0                  # m: the cells are 6 x 6 m, in the lockup's north corners
CELL_DOOR_W = 2.0                # the cell door: 2 m of bars in the middle of the south side...
CELL_BAR_T = 0.3                 # ...and every bar wall is this thick
CELL_DOOR_HP = 6                 # punches to bend it off its hinges (LOUD: the guards come running)
CELL_PICK_TIME = 7.0             # s to pick the lock with a paperclip (quiet: nobody notices)
CELL_OPEN_TIME = 1.5             # s for a crewmate in the hall to let you out
CELL_ID_BASE = 65400             # the cell doors' fixed entity ids (new_id never goes above 65000)
GUARD_NOTICE_R = 7.0             # m: a quiet escapee this close to a guard gets noticed
JAIL_GUARDS = 3                  # guards in the lockup (one of them has the keys)
GUARD_DOWN_TIME = 3.0            # s a punched guard stays down (v0.9: they get up quicker...)
GUARD_KO_TIME = 25.0             # s once they've had enough (after GUARD_GRIT knockdowns)
GUARD_GRIT = 4                   # ...and take twice the beating (v0.9, "harder to kill"; the key guard +2)
GUARD_RING = 4.5                 # m: only ONE guard fights you at a time; the rest wait this far off
GUARD_BACKOFF = 1.4              # s a guard steps back after landing a punch (no pinning you in a corner)
GETUP_GRACE = 1.5                # s after you get up before anyone may knock you down again
GUARD_RESET_TIME = 30.0          # s with nobody locked up before the guards get back on their feet
GATE_OPEN_TIME = 8.0             # s the gate stays open after the keys turn
GATE_SMASH_TIME = 15.0           # s a rammed gate stays (in pieces, so: open)
GUARD_SPEED = 6.4                # m/s: guards are slower than your sprint (they've had lunch)
GUARD_PUNCH_COOLDOWN = 1.1
GATE_PICK_TIME = 6.0             # s to pick the lock from outside (a crewmate breaking you out)
GATE_RAM_DV = 9.0                # m/s of impact that smashes the gate in (the dramatic way)
GATE_ID = 65500                  # the precinct gate's fixed entity id (new_id never hands it out)
GATE_LEN = 4.0                   # the gate fills one doorway tile
GATE_WID = 0.5
BAIL_BASE = 250                  # bail at the front desk: the cowardly way out...
BAIL_PER_ARREST = 100            # ...and it goes up every time
JAILBREAK_HEAT = 40.0            # walking out of a police station is noticed
JUMPSUIT_WITNESS = True          # escaped convicts in orange are wanted on sight, heat or no heat
JAILBREAK_HEAD_START = 15.0     # (v0.12.1, Bryce: "im spawn locked in jail") seconds after you walk out
                                # of the precinct before any cop may cuff, tase or shoot you. The cops
                                # still SEE the jumpsuit and heat still climbs -- you just get a
                                # sporting chance to reach a car instead of being re-arrested on the
                                # front steps 7 seconds later, which is what the playtest kept doing.
COP_SPAWN_GAP = 2.0
COP_REINFORCE_DELAY = 9.0        # after you blow one up, dispatch takes a moment to stop crying
COP_SPAWN_MIN_DIST = 45.0
COP_DESPAWN_AT_ZERO = 3.0
HORN_CONFUSE_RANGE = 40.0
HORN_CONFUSE_TIME = 3.0
HORN_CONFUSE_COOLDOWN = 7.0      # (our call) a cop can't be re-donut'd for 7 s, or holding H is god mode
CUFFED_TIME = 3.0                # s cuffed on the kerb (the mugshot), then off to the precinct

# --------------------------------------------------------------------------
# Traffic & NPCs
# --------------------------------------------------------------------------
MAX_CIVILIAN_CARS = 8            # (v0.10: was 6, city's bigger now) more marks on the street
CIV_RESPAWN_DELAY = 3.0
CIV_SPAWN_MIN_DIST = 25.0
ABANDON_TOW_TIME = 60.0          # (our call) stolen cars left far from everyone get towed so the city refills
ABANDON_DIST = 110.0
PED_COUNT = 32                   # (v0.10: was 26, city's bigger now)
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
TRAFFIC_COUNT = 9                # (v0.10: was 8) enough to T-bone, not enough to gridlock a 540 m city
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
# (v0.10, Bryce: "sneaking / turning off the alarm on a stolen car by cutting wire minigame")
# X at a locked car instead of E: pop the hood and go for the wires. Slower than just smashing
# the window, but no alarm at all if you cut the right one -- and a proper penalty if you don't.
ALARM_CUT_TIME = 6.0             # s fiddling under the hood (BREAKIN_TIME is 4: this is the slow way)
ALARM_CUT_WIRES = 4              # how many wires; one's the right one
ALARM_CUT_FAIL_HEAT = 20.0       # guess wrong and it screams -- worse than just smashing the window
TRUNK_POP_TIME = 0.35            # s the boot takes to swing up (cosmetic; see FPRenderer._trunk_pop --
                                 # client-local off the trunk data every trunk prompt already sends)

# --------------------------------------------------------------------------
# Violence (v0.6: Bryce wants to punch people, rob them, and have guns).
# Nobody dies: everyone just hits the deck, cartoon-style, and gets back up
# furious. Every act of violence is loud, so it all costs heat.
# --------------------------------------------------------------------------
PUNCH_RANGE = 1.9                # metres from you, in front of you
PUNCH_CONE = 0.8                 # radians either side of where you look
PUNCH_COOLDOWN = 0.4
PUNCH_KNOCKDOWN = 3.0            # a punched pedestrian stays down this long: long enough to rob
# ---- (v0.9) the silly department, round three ---------------------------------------------
CHICKEN_COOLDOWN = 0.45          # the rubber chicken: a touch slower than a jab (it's floppy)...
CHICKEN_KNOCK = 10.0             # ...but it shoves twice as hard (it's the surprise more than the chicken)
CHICKEN_KNOCKDOWN = 2.0          # s on the floor, reconsidering everything
WHOOPEE_R = 0.55                 # m: step here and PFFFFT
WHOOPEE_USES = 3                 # it's a quality cushion
WHOOPEE_LAUGH_R = 14.0           # m: everyone within earshot loses it...
WHOOPEE_LAUGH_TIME = 3.5         # ...for this long. Officers too (they're only human): free escape
BOX_SPEED_MULT = 0.35            # shuffling along inside a cardboard box
BOX_STILL_TIME = 0.6             # s stood still before you're convincingly just a box. Move and you're not
COPCAR_STEAL_TIME = 2.0          # s of E at a cop car whose officer's out chasing somebody
COPCAR_STEAL_HEAT = 30.0         # it's a police car. They notice that
CHICKEN_EVERY = (20.0, 45.0)     # s between chickens crossing the road near the crew
CHICKEN_SPEED = 2.4              # a determined waddle
CHICKEN_MAX = 3
MIME_COUNT = 2                   # mimes in town. Not witnesses (what would they say?)
MIME_SPEED = 1.1
RAMP_COUNT = 4                   # stunt ramps, in the car parks
RAMP_LEN = 3.2                   # m long (up the slope)...
RAMP_W = 3.4                     # ...and wide enough for a van with its eyes shut
RAMP_MIN_SPEED = 14.0            # m/s up the ramp for BIG AIR (about 31 mph)
RAMP_AIR_PER_MS = 0.045          # s of hang time per m/s (30 m/s = 1.35 s: long enough to scream)
RAMP_BONUS_PER_S = 40            # $ per second airborne. The crowd loves it. The suspension doesn't
MONEY_TRUCK_CHANCE = 0.06        # share of new traffic that's an armoured money truck
MONEY_TRUCK_HITS = 5             # bullets (a hard ram counts double) before the back doors pop
MONEY_TRUCK_BAGS = (3, 5)        # bags of cash that fall out the back
MONEY_TRUCK_HEAT = 25.0          # robbing an armoured car is Noticed
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

# (v0.12, Bryce: "add more guns, SMG, AR, Sniper, grenade launcher RPG, etc.") every gun past
# the shotgun fires the same hitscan _ray_hit as always -- no new physics, just different
# numbers. There's no hold-to-fire input model in this game (a "shot" is always one click), so
# the SMG and AR's "automatic" feel comes entirely from a short cooldown between taps, not
# actual full-auto. The launchers don't lob a real projectile either: they hitscan to whatever's
# under the crosshair (or the wall behind it) and blow up there -- a mortar strike, not a thrown
# grenade. Simpler than real ballistics, and at these ranges nobody can tell the difference.
SMG_RANGE = 45.0
SMG_COOLDOWN = 0.18               # fast taps read as automatic
SMG_SPREAD = 0.05                 # radians: sustained fire drifts off target, on purpose
AR_RANGE = 90.0
AR_COOLDOWN = 0.22
AR_SPREAD = 0.025
SNIPER_RANGE = 160.0
SNIPER_COOLDOWN = 1.6             # bolt-action: work the bolt between shots
SNIPER_HEADSHOT_MULT = 3.0        # (cosmetic framing only -- a hit's a hit; this just means "always lethal")
GRENADE_RANGE = 40.0              # (a lob, not a beam: it won't reach as far as the guns)
GRENADE_COOLDOWN = 2.2
GRENADE_SPLASH = 6.0              # metres: everything in this radius of the impact gets caught up
RPG_RANGE = 70.0
RPG_COOLDOWN = 3.5
RPG_SPLASH = 9.0                  # the biggest blast in the game, and priced like it

# ---- (v0.12) the silly department, round four ----------------------------------------------
PRICE_TICKET = 20                 # a scratch ticket from the black market. House always wins. Mostly.
TICKET_ODDS = ((0.55, 0), (0.25, 10), (0.12, 40), (0.06, 100), (0.02, 500))   # (chance, payout $)
JACKPOT_CHANCE = 0.02             # one pedestrian in 50 is having an unusually good day
JACKPOT_WALLET = (400, 900)       # what their wallet's actually carrying, if you find out the hard way
HIGHFIVE_RADIUS = 2.2             # m: two crewmates dancing this close sync up
HIGHFIVE_COOLDOWN = 20.0          # shared, so a packed dance floor doesn't spam toasts
HIGHFIVE_STAMINA = 25.0           # a shared burst of team spirit, straight into the legs
SPEEDCAM_FAME_COUNT = 5           # tickets before the local news van shows up
TIP_JAR_CHANCE = 0.15             # selling a part: one in ~seven passersby likes your hustle
TIP_JAR_MIN, TIP_JAR_MAX = 5, 25  # what they chip in
SEAT_CHANGE_CHANCE = 0.2          # hotwiring a car: one in five has change down the seats
SEAT_CHANGE_MIN, SEAT_CHANGE_MAX = 2, 15   # gross but free

# --------------------------------------------------------------------------
# Black market (crates along the shop's west wall) and traps
# --------------------------------------------------------------------------
PRICE_PISTOL = 350               # comes loaded with PISTOL_AMMO
PRICE_SHOTGUN = 800
PRICE_SMG = 1400
PRICE_AR = 2400
PRICE_SNIPER = 3200
PRICE_GRENADE = 2800
PRICE_RPG = 5500
PRICE_AMMO = 60                  # tops up whatever guns you own (all seven now, one crate)
PRICE_SPIKES = 120
PRICE_ROADBLOCK = 200
PRICE_BANANA = 40                # a banana peel. Cars spin out, people fall over. Classic.
PRICE_DONUTS = 30                # a box of donuts: throw it and every cop nearby takes a break
PRICE_CHICKEN = 25               # (v0.9) a rubber chicken. Squeaks. Floors people. Not legally a weapon
PRICE_WHOOPEE = 15               # (v0.9) a whoopee cushion: lay it down, wait for someone to step on it
PRICE_BOX = 40                   # (v0.9) a cardboard box. Stand still in it and you're furniture
PISTOL_AMMO = 24
SHOTGUN_AMMO = 10
SMG_AMMO = 45                    # a mag and a half
AR_AMMO = 30
SNIPER_AMMO = 5                  # it's a bolt-action hand cannon, not a mag dump
GRENADE_AMMO = 4
RPG_AMMO = 2                     # two rockets. Make them count.
MAX_AMMO = 99
# (v0.12, Bryce: "shop 1 has just basic parts and the pistol") what's for sale at each shop,
# by index into World.shop_owned -- 0 is the home base, 1-3 the fences you buy. Each tier is
# a superset of the last: buy shop 3 and its crates carry everything shop 2 had too, plus the
# new stuff. World._market_buy doesn't care which shop you bought an item at -- this list only
# controls which crates physically exist for you to walk up to.
SHOP_MARKET = (
    ("pistol", "ammo", "spikes", "roadblock", "ticket"),
    ("pistol", "shotgun", "ammo", "spikes", "roadblock", "banana", "donuts", "ticket"),
    ("pistol", "shotgun", "smg", "ar", "ammo", "spikes", "roadblock", "banana", "donuts",
     "chicken", "whoopee", "box", "ticket"),
    ("pistol", "shotgun", "smg", "ar", "sniper", "grenade", "rpg", "ammo", "spikes", "roadblock",
     "banana", "donuts", "chicken", "whoopee", "box", "ticket"),
)
MAX_TRAPS_EACH = 5
BUY_TIME = 0.6
TRAP_PLACE_DIST = 3.5            # traps go down this far in front of you, snapped across the road
SPIKE_LEN, SPIKE_WID = 6.0, 0.7  # half a road: spikes shred the lane they're in
SPIKE_USES = 3                   # cars it can shred before the strip is scrap
ROADBLOCK_LEN, ROADBLOCK_WID = 11.0, 1.0   # the whole road: traffic stops dead and honks
ROADBLOCK_BREAK_DV = 11.0        # hit it this hard and it's matchwood (same as the eject threshold)
BANANA_PLACE_DIST = 2.0          # m ahead of you a peel lands (drop it and step back)
BANANA_R = 0.45                  # m: tread on this and you're on your back
BANANA_SLIP_TUMBLE = 1.4         # s on the floor after a peel
BANANA_SPIN_KICK = 2.6           # rad/s of instant yaw for a car that finds one
DONUT_THROW_DIST = 12.0          # m you can lob a box of donuts
DONUT_R = 0.5
DONUT_LURE_RADIUS = 35.0         # cops this close smell them. They cannot help themselves.
DONUT_EAT_TIME = 8.0             # s a cop spends on a box (not looking at anything else)
DONUT_COPS = 2                   # cops per box (they share. Barely.)
TRAP_LIFETIME = 150.0
MAX_TRAPS = 12
CARJACK_TIME = 1.5               # yank the door, yank the driver
CARJACK_MAX_SPEED = 2.0          # it has to be (nearly) stopped
CARJACK_HEAT = 12.0              # worse than a quiet break-in: there's a witness in the gutter

# --------------------------------------------------------------------------
# Economy (shared wallet)
# --------------------------------------------------------------------------
START_CASH = 300
DAY_LENGTH = 180.0               # seconds: dawn to midnight
# (v0.12, Bryce: "make multiple garages, make them available for purchase... stop increase
# of rent / day and make it on a shop basis") rent used to get steeper every single day
# forever, which meant a long session eventually paid more in rent than it could ever make.
# Now it's flat per shop you own: day 1 costs the same as day 100, and the only way the bill
# goes up is buying another shop yourself. Index 0 is the home base (free, you start with
# it); 1-3 are the fences you can buy from World.shop_owned. SHOP_PRICE is what buying one
# costs, once; SHOP_RENT is what it adds to the daily bill forever after.
SHOP_PRICE = (0, 4000, 12000, 30000)
SHOP_RENT = (100, 150, 250, 400)
DEBT_GRACE = 120.0               # two minutes in the red and the landlord changes the locks
# (save files) how often a hosting server with --save writes the crew's progress to disk,
# real seconds, so a crash or a yanked power cord costs at most this much. Also saved once,
# unconditionally, on a clean shutdown -- this is just the safety net in between.
AUTOSAVE_INTERVAL = 30.0
SAVE_SLOTS = 3                  # (v0.12.1, Bryce: "I cant find the option to open a save file or even
                                # save one") the main menu's SAVE SLOT row. Three: one for the real
                                # crew, one for solo practice, one for the run where you bought
                                # every hubcap in town. More than that and it's a filing cabinet.
GAMEOVER_BANNER = 6.0
SHELL_VALUE = 150
CRUSH_DOLLY_FRACTION = 0.5
# (v0.9) selling a delivered car whole, X at the car (Bryce: "add the ability to sell the vehicle
# whole"). 70% of what the parts would fetch one at a time, plus the shell: you trade ~30% of the
# money for not spending two minutes with a spanner and a dolly. A complete sports car or 4x4
# fetches a collector's bonus on top -- that's the "is it worth stripping?" decision.
WHOLE_SALE_RATE = 0.7
WHOLE_SALE_SPORTY = 400
WHOLE_SALE_4X4 = 250
# (v0.9) inspecting a car you're looking at (Bryce: "i want to inspect the cars before hijacking /
# breaking in to get a sense of their parts / value"): within this range, crosshair on it
INSPECT_RANGE = 12.0             # m: across the street, not across town
INSPECT_EVERY = 6                # ticks between looks (10 Hz is plenty for "what am I looking at")
# (v0.9) the chop shop's roof and roller door (Bryce: "add a roof to the chop shop and a closable
# door that blocks cops. but it needs to be opened for you to get in")
ROOF_H = 6.0                     # m: the roof sits on the shop's 6 m walls
# (v0.12.1, Bryce: "the shops ceiling breaks the visuals, only shows sky from looking outside in
# the direction of the shop") the walls used to stop exactly at the roof, so from the street the
# shop was a 6 m box with sky over it and its ceiling hanging in mid-air behind the doorways. Now
# the outer walls carry on up past the roof as a parapet -- a proper false front, like every
# garage on every industrial estate -- and a brick lintel spans the top of each door opening, so
# from outside it reads as a building and the ceiling is only ever seen through a door, under it.
SHOP_FACADE_H = 8.0              # m: the top of the parapet (2 m above the roof, hiding it)
# (v0.12.1, Bryce: "make an actual door for walking") the walking entrance was a whole 4 m roller
# door, the same as a bay. Now it's a person-sized door in a brick wall: a gap this wide in the
# middle of its tile, the rest of the tile solid brick jambs either side.
WALK_DOOR_W = 1.4                # m: wide enough to carry a door through; nowhere near wide enough for a car
WALK_DOOR_H = 2.4                # m: the frame's height (brick above it, up to the parapet)
# (v0.10, Bryce: "make the garage door smaller, make a walking entrance and a bay for each
# player that joins") one 28 m roller door for the whole crew became five small ones, each
# exactly one tile (TILE_M) wide so they drop cleanly onto the raycaster's tile grid with no
# fractional gaps to plaster over: a walking door and four bay doors, one per player slot.
# Each is its own Trap (kind TRAP_DOOR, its own id, its own open_t and goal), independently
# opened, closed and shut on cops. DOOR_COLS says which of the shop's 7 front tile-columns
# they sit in (0-indexed from the garage's west wall); the two columns left over (3 and 4,
# between the first pair of bays and the second) are ordinary WALL tiles -- see
# mapgen._make_shop -- so shutting every door really does seal the place: there's no gap
# between doors for a witness to see through, because there's no floor there to stand on.
DOOR_T = 0.4                     # m thick (it's a door, not a wall: it doesn't need to be much)
DOOR_TIME = 1.4                  # s to roll all the way up or down. Slow enough to be dramatic in a chase
DOOR_PASSABLE = 0.96             # fraction up before it stops being solid (i.e. only when it's UP)
DOOR_ID = 65510                  # the first door's fixed entity id (walk=+0, bays=+1..+4)
DOOR_REMOTE_R = 30.0             # m: honk within this of a door to open/close it (the remote on your visor)
DOOR_REACH = 2.2                 # m: how close your aim has to be to a door to press its button
DOOR_BANG_EVERY = 4.0            # s between "POLICE! OPEN UP!" toasts (they will bang on any shut one)
DOOR_W = TILE_M                  # every door (walk or bay) is exactly one tile wide
DOOR_COLS = (0, 1, 2, 5, 6)      # front tile-columns that are doors: 0 = walk, 1-4 = bays 0-3
N_BAYS = 4                        # (v0.10) one personal car + bay per player slot (see config.MAX_PLAYERS)
INSPECT_DELAY = 0.45             # s of looking before the card comes up (a glance at a car isn't a survey)
SELL_TIME = 0.5                  # (v0.5: halved)
INSTALL_TIME = 1.5               # (v0.5: halved)
PICKUP_TIME = 0.3
BUY_MARKUP = 1.6                 # the parts counter charges 60% over street value: stealing stays
                                 # the better deal, buying is for when you want it NOW
PICKUP_LIFETIME = 600.0          # ten minutes, then the raccoons take it
PICKUP_SHRINK = 30.0             # last 30 s it visibly shrinks
MAX_PICKUPS = 90

TOAST_TIME = 3.5
SAY_TIME = 9.0                   # (v0.12.1) s a line of NPC dialogue stays up: long enough to read a job brief
MUSIC_VOLUME = 0.45              # the beat sits under the engine and the sirens, not on top of them
MOUSE_PITCH_SENS = 0.0022        # look up/down: share of the view height per mouse count
PITCH_LIMIT = 0.42               # ...up to this share of the view (y-shearing gets weird past it)
# ---- sprite angles (v0.8, Bryce: "make the objects you interact with have more angles so they
# feel more real"). Box models are rendered once per angle and cached, so more angles cost a
# little memory and a little first-sight rendering, not frame time.
CAR_ANGLES = 32                  # was 16: cars turning in front of you no longer "tick" round
CHASE_CAR_ANGLES = 72            # your own car in the chase cam: it's right there, being drifted
PERSON_ANGLES = 16               # was 8
PROP_ANGLES = 16                 # crates, the dolly, gnomes, traps, the gate (was 8)
SPRITE_CACHE_CARS = 4000
SPRITE_CACHE_PEOPLE = 4000
CHASE_BACK = 3.8                 # 3rd-person camera: this far behind, plus 0.75 x the car's length
CHASE_HEIGHT = 2.1               # ...and this high, plus a bit for tall vans
CHASE_PITCH = 0.12               # looking down at the car by this share of the view
CHASE_LAG = 5.0                  # 1/s: how fast the camera swings round behind you
CHASE_FOLLOW_VEL = 0.4           # share of the way it turns toward where you're actually going (drifts!)
CHASE_ORBIT_RETURN = 1.2         # s after you stop mouse-looking before it drifts back behind the car
DRIFT_MIN_ANGLE = 14.0           # degrees of slide that count as a drift on the meter
DRIFT_MIN_SPEED = 8.0

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


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def wrap_angle(a):
    """Map any angle into (-pi, pi]."""
    a = (a + math.pi) % (2.0 * math.pi) - math.pi
    return a


def door_specs(garage_rect):
    """(v0.10) The 5 doors across the shop's front -- (id_offset, x, y) -- id_offset 0 is the
    walking door, 1-4 are the bays (west to east, so bay N-1 is player N's). Pure function of
    the garage's rect, so the host, every client and the predictor all agree on exactly where
    they are without a single byte on the wire. Every door is DOOR_W (one tile) wide; the two
    front tile-columns not in DOOR_COLS are ordinary wall, placed by mapgen._make_shop."""
    gx, gy, gw, gh = garage_rect
    y = gy + gh
    return [(i, gx + (col + 0.5) * TILE_M, y) for i, col in enumerate(DOOR_COLS)]

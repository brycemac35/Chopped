"""
config.py -- every tuning number in the game lives here, so that when the
game feels wrong at 3 AM you only have to be angry at one file.

Units: metres, seconds, dollars. Screen y points DOWN (like every sane 2D
engine and exactly no maths textbooks).
"""

import math

GAME_TITLE = "Chopped"
VERSION = 17  # bump when the wire protocol changes so old clients get a polite "no"
RELEASE = (0, 18, 0)  # the number on the exe's Properties tab and the menu. Bump per build you hand out.

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
# (v0.16, choosable characters) see characters.py; every perk is a multiplier from this block.
CHAR_DASH_STAMINA_MAX = 1.5      # ATHLETE: a lung and a half. Mostly the half is ego.
CHAR_DASH_STAMINA_REGEN = 1.3    # ...and he gets his wind back like he's been reading about breathing
CHAR_SPANNER_STRIP_TIME = 0.6    # GREASE MONKEY: every strip (dolly engines, junk piles too) in 60% of the time. Muscle memory.
CHAR_SLIM_BREAKIN_TIME = 0.5     # LIGHT FINGERS: half the time to smash in...
CHAR_SLIM_HOTWIRE_TIME = 0.5     # ...and half the time to hotwire. He has a lot of practice, and a record.
CHAR_SLIM_ALARM_CUT_TIME = 0.5   # snip snip
CHAR_SLIM_ALARM_WIRES = 0.5      # wires to guess from x0.5: 4 -> 2, so a coin flip instead of a prayer
CHAR_SLIM_THEFT_HEAT = 0.5       # (v0.19) ...and half the heat off every break-in / carjack / hot-seat grab: nobody remembers his face
CHAR_SLIM_BREAKIN_ALARM = 0.0    # (v0.19) x the alarm: his window-smash is silent (no alarm, no owner running out). 0 = never rings
CHAR_SMOOTH_SALE_BONUS = 1.10    # SMOOTH TALKER: +10% on sales he makes (his auction lots, orders he fills). Was 1.15: with half-price bail too he was the strictly-best pick
CHAR_SMOOTH_FEE_MULT = 0.5       # bail and papers cost him half: the clerk "knows a guy"
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
ENGINE_BANDS = 8                 # pre-rendered engine loops per layout (x2 for on/off load), crossfaded by rpm.
                                 # 6 was a 1.7x rpm jump between bands (two engines fading); 8 is ~1.45x
                                 # and, with the on/off pair, still renders in about the old time
ENGINE_RMS = 0.24                # RMS of a full-throttle redline loop, before the tanh limiter. Loops are
                                 # set by RMS (loudness), not peak, so a lumpy V8 isn't quieter than an I4
ENGINE_LEVEL_IDLE = 0.30         # loudness at idle as a share of redline (was ~0.55: idle droned)
ENGINE_LEVEL_OFF = 0.55          # ...and off the throttle as a share of on it: the overrun is thin
ENGINE_LOAD_ATTACK = 9.0         # 1/s: engine load chases the throttle this fast (intake opens quick)...
ENGINE_LOAD_RELEASE = 6.0        # ...and lets go this fast (the manifold empties)
SC_PULLEY = 2.4                  # supercharger rotor revs per crank rev (belt ratio)
SC_LOBES = 3                     # lobes per rotor: the lobe-pass whine is rotor rev/s * lobes
                                 # (a 3-lobe Roots at 7000 rpm: 117 * 2.4 * 3 = 840 Hz, harmonics to 3+ kHz)
SC_WHINE_HZ = (100.0, 1250.0)    # lobe-pass range the tone bank covers (idle .. past the redline)
TONE_RATIO = 1.07                # adjacent whine/whistle bank tones are this far apart (~1.2 semitones)
TURBO_HZ_TOP = 6600.0            # compressor whistle at full turbine speed (blade-pass; proportional to N)
TURBO_HZ_FLOOR = 1300.0          # below this the whistle is too quiet and low to bother rendering
TURBO_COAST = 0.75               # 1/s: a lifted turbine freewheels down this slowly (spool-up is TURBO_SPOOL)
GEAR_SPREAD = 0.8                # gear n tops out at top * (n / gears) ** this: short first, tall top
GEAR_TOP_OVERRUN = 1.06          # top gear would reach the redline just past top speed
SHIFT_UP_AT = 0.93               # share of the redline where the box shifts up...
SHIFT_DOWN_AT = 0.55             # ...and it drops a gear when the one below would be this far up
SHIFT_TIME = 0.16                # s of throttle cut per shift (the "bwaaa-ap" between gears)
LAUNCH_REVS = 0.45               # pulling away, the clutch holds the revs this high
REV_RISE = 9.0                   # 1/s: revs chase the target this fast going up...
REV_FALL = 5.0                   # ...and this fast falling (flywheels are heavy)
LIMITER_PERIOD = 0.09            # s between rev-limiter cuts: brap-brap-brap
TURBO_SPOOL = 1.6                # 1/s: turbine speed chases exhaust energy this fast: turbo lag. It's a feature.
TURBO_DUMP = 6.0                 # 1/s: boost PRESSURE falls off this fast when you lift (the valve vents it)
TURBO_BOOST_RISE = 8.0           # 1/s: pressure builds this fast once the turbine is already spinning
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
# ---- (v0.19) the jack: bolt a wheel back on a car parked OUTSIDE the shop ------------------------
# Bryce: "be able to reinstall wheels when the car is parked outside the shop. Takes 15 seconds and
# requires a new item called jack." A crew tool (like the locker and the dolly: one jack, everybody
# borrows it), bought once at shop 2's counter or better (EXTRA_SHOP_TIER), never used up.
PRICE_JACK = 150                 # $ once. Cheap on purpose: the pain is the 15 s, not the receipt
JACK_FIT_TIME = 15.0             # s of hold-E per wheel. Long enough that you do it with a lookout, not mid-chase
JACK_MAX_SPEED = 1.0             # m/s: a car that's still rolling can't be jacked (traffic you've stopped is fine)

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
BIKE_EJECT_DV = 6.0              # (v0.13) ...and off a motorbike at a bump that'd only dent a car. The
                                 # price of 56 m/s in a 230 kg package: kiss a lamppost at jogging
                                 # speed and you're doing a forward roll into the fruit stand.
IMPOUND_RESTOCK = 75.0           # (v0.13) s between the precinct impound putting a bike back out. (v0.19) was 20: a keys-in ~$1,300 bike every 20 s for ~10 heat was free money, so now it's a slow trickle
IMPOUND_WEAR = 0.5               # (v0.19) impound bikes' parts are worth x this condition: "impounded wrecks". They still run (the solo jail-escape ride), they just aren't a cash machine
IMPOUND_HIDE_DIST = 30.0         # m: ...but never while somebody's close enough to watch it appear
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
SPORTY_HEAT_MULT = 2.0           # (v0.19) x the break-in / carjack / failed-wire heat on a sporty model (coupe, muscle, rice rocket): they're the good loot, and their owners are the ones with friends at the station
HEAT_RUN_MIN_HEAT = 40.0         # (v0.19) HEAT RUN only counts once the crew's heat has actually reached this during the job. Before, a clean quiet delivery paid it for nothing
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
# (v0.18, Bryce: "make the spawn limit of cops / cop car 2, and 1 dog") the city's police budget is
# small again. ONE world cap on cop cars, and it counts patrols: a cruising patrol that spots you IS
# one of the two (and at a high wanted level dispatch waves a cruising patrol in rather than
# spawning a third car). Lockup guards, the helicopter and the impound bikes aren't part of it.
COP_CARS_MAX = 2                 # cop cars in the world at once, patrols included (was 5 dispatched + 2 patrols)
OFFICERS_MAX = 2                 # officers on foot at once (one per car, so this only bites when a
                                 # carjacked officer is still wandering off to explain himself)
K9_MAX = 1                       # police dogs alive at once (they live K9_LIFETIME, so about one per chase)
COP_TIERS = ((25.0, 1), (60.0, 2))   # heat -> units on the way (a wanted level); tops out at the cap
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
PATROL_COPS = 1                  # cruisers that are ALWAYS out there, doing laps, being witnesses (v0.18: was 2;
                                 # counted against COP_CARS_MAX, so a patrol that engages is one of the two)
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
# (v0.14, Bryce: "make the cop pick you up and take you to his car and drive you to jail") no more
# teleporting into the cell: the officer who cuffed you carries you, over his shoulder, back to his
# car, shoves you in the back and drives you to the precinct himself. Which means there's a ride
# for your crew to interrupt: punch him while he's carrying you, stop the car (spikes, a roadblock,
# donuts, the horn, standing at its door), carjack it, or crash it hard enough to throw you out.
ESCORT_SPEED = 3.2               # m/s: walking with a grown adult on your shoulder
ESCORT_MAX_WALK = 45.0           # m: his car's further than this, the precinct sends a van (the old way)
ESCORT_MAX_TIME = 25.0           # s: can't get back to his car in this long (walls, a crowd): the van again
ARREST_RIDE_PULL_IN = 30.0       # m out (in sight of it) he leaves the lanes and pulls in to the kerb
ARREST_RIDE_PULL_SPEED = 7.0     # m/s doing that (the lanes' own speed limits do the rest of the ride)
ARREST_RIDE_KERB = 4.6           # m out from the precinct steps: in the road, just off the pavement
ARREST_RIDE_ARRIVE = 5.0         # m from that spot that counts as "here"
# (v0.18, Bryce: "when I am in the back of a cop car, the cop sometimes gets stuck... just send the
# player to jail after a certain time limit so they aren't stuck there forever") two clocks on the ride:
TRANSPORT_STUCK_TIME = 12.0      # s the cop car makes no real progress toward the station (see below):
                                 # "THE OFFICER RADIOED FOR THE VAN" and you're in a cell. Long enough to
                                 # survive a red-faced three-point turn or a queue at a junction
TRANSPORT_GAIN_M = 1.0           # m: a new closest-so-far to the station by this much is progress...
TRANSPORT_PROGRESS_M = 8.0       # m: ...and so is getting this far from where the last progress was made. (Distance
                                 # alone would jail him for driving round the block, which the lanes make him
                                 # do; a wheel-spinning cop or a reverse-forward shuffle never gets 8 m)
TRANSPORT_MAX_TIME = 75.0        # s: the whole ride, however busy it looks (a lane loop, a pile-up):
                                 # corner to corner of town down the lanes is about 60-70
ARREST_RIDE_MAX = TRANSPORT_MAX_TIME   # (the pre-v0.18 name: was 120 and only checked by the drop-off)

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
TRAFFIC_HONK_AFTER = 1.5         # blocked this long by something that isn't just the car queued ahead -> a beep
                                 # (doesn't confuse cops). (v0.18, Bryce: "the horns are insufferable when there's
                                 # a traffic jam": it used to lean on the horn and hold it. Now: one short beep, then
                                 # a long, random per-car cooldown, and a cap on how many can go off at once.)
TRAFFIC_HONK_LEN = 0.35          # s a beep lasts. A "beep", not a "BEEEEEEEEP".
TRAFFIC_HONK_COOLDOWN = (16.0, 40.0)   # s before that car may honk again; random, so a jam doesn't beep in unison
TRAFFIC_HONK_MAX_NEAR = 2        # at most this many traffic cars honking at once within earshot of a player...
TRAFFIC_HONK_HEARD = 70.0        # ...where "earshot" is this many metres (further off nobody's counting)
TRAFFIC_OVERTAKE_AFTER = 2.5     # stuck behind a stopped car this long -> swing out and pass
TRAFFIC_CROSS_COS = 0.6          # (v0.13) two traffic cars count as "crossing" below this |cos| of heading
TRAFFIC_CROSS_LOOKAHEAD = 2.0    # s ahead a junction conflict is predicted -- enough to brake from 20 m/s
TRAFFIC_CROSS_GAP = 4.0          # m: closer than this at closest approach and whoever's second yields
TRAFFIC_ONCOMING_GAP = 2.4       # m: ...the same for oncoming traffic, tighter: lanes pass 3.2 m apart
TRAFFIC_SHAKEN_TIME = 2.0        # after a bump they sit there, stunned (one beep, see TRAFFIC_HONK_LEN)
# (v0.18, Bryce: "traffic jams and then the cars pile up at one intersection") Unjamming. The pile-ups
# had two causes: queued cars swinging out to "overtake" other queued cars straight into the oncoming
# lane (nose to nose with the other queue, in a junction, forever), and cars entering a junction they
# couldn't leave. So: overtake only what's really stalled and only into a clear lane, never enter a box
# with no room on the far side, and if it all goes wrong anyway, escalate: wait -> lowest id barges
# through -> the rest back out and re-plan -> vanish out of sight.
TRAFFIC_IDLE_RADIUS = 6.0        # m: a car that hasn't got this far from where it started waiting is "stuck"
TRAFFIC_BOX_HOLD_DIST = 9.5      # m from a junction's centre where a car that can't clear the box stops
TRAFFIC_BOX_LOOK = 26.0          # m out from the junction that we start checking the exit lane
TRAFFIC_BOX_ROOM = 9.0           # m of exit lane, from the junction's far kerb, that has to be free of stopped cars
TRAFFIC_OVERTAKE_CLEAR = 40.0    # m of oncoming lane that must be empty before anyone swings out (the pass takes ~3.5 s)
TRAFFIC_OVERTAKE_NODE = 16.0     # m: no pulling out this close to the next junction
TRAFFIC_OVERTAKE_IDLE = 10.0     # s a traffic car must have sat there (with nothing in front of it) before it's a "wreck"
TRAFFIC_PRIORITY_AFTER = 3.5     # s stuck: the lowest id in the knot stops yielding (ignores cross traffic + the box rule)
TRAFFIC_BACK_OUT_AFTER = 6.0     # s stuck: everyone else in the knot reverses a little and picks another way...
TRAFFIC_BACK_OUT_TIME = 1.6      # ...for this long,
TRAFFIC_BACK_OUT_AGAIN = 5.0     # ...and again every this many seconds if that wasn't enough
TRAFFIC_KNOT_RADIUS = 26.0       # m: "the knot" = stuck traffic this close to you
TRAFFIC_STUCK_DESPAWN = 30.0     # s with no real progress: the car is recycled (once nobody is looking)...
TRAFFIC_STUCK_HARD = 60.0        # ...or once it's been this long, in front of everybody
TRAFFIC_SEEN_NEAR = 40.0         # m: a player this close to a car always "sees" it go
TRAFFIC_SEEN_FAR = 130.0         # m: ...and one this close, looking roughly at it, does too
TRAFFIC_SEEN_CONE = 1.0          # rad each side of a player's heading that counts as "looking at it"
WRECK_CLEAR_TIME = 45.0          # s a driverless car a traffic driver bailed out of sits in the road before it's towed
WRECK_CLEAR_NEAR = 25.0          # m: ...unless somebody's standing this close to it (they might want it)
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
CARJACK_HOLD_SPEED = 1.5         # (v0.13.1) m/s: a car going slower than this with a crook stood at
                                 # its door stays put. (A traffic driver doesn't floor it with somebody's
                                 # hand on the handle -- and before this, you couldn't finish a
                                 # carjack: the car drove off as soon as you stepped out of its lane)
CARJACK_DOOR_REACH = 1.6         # m out from the bodywork that counts as "at the door"
COP_CARJACK_MAX_SPEED = 3.0      # (v0.13.1) m/s: a cop car this slow can be carjacked like traffic. A
                                 # touch more forgiving than traffic's 2.0: cops never quite sit still
                                 # (creeping round a corner, or chewing a donut on the handbrake)
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
# (v0.19, QA: "the lose condition never bites mid-game") 150/250/400 was pocket change by the
# time you could afford a second shop, so nobody ever met a strike. 300/600/1200 makes a fully
# owned empire a $2,200/day habit: shops have to be worked, not just bought. Home shop unchanged.
SHOP_RENT = (100, 300, 600, 1200)
# (Bryce, after a playtester asked "can you even lose?") Rent strikes replace the old hidden
# two-minute debt timer, which nobody could see and nobody lost to. Now it is baseball, with
# eviction: miss a midnight (cash can't cover rent PLUS whatever's carried over) and that is a
# strike; the unpaid rent piles onto next night's bill. Pay the whole pile and the slate is clean.
# Two strikes and the landlord changes the locks. Two, because one is a bad night, and three is
# a lease with feelings. Change it and every toast and the HUD follow, they read this number.
RENT_STRIKES_MAX = 2
# Seconds before midnight that the landlord's nice-guy voicemail arrives ("YOU'RE $N SHORT").
# 45 s is a long enough run to sell a few parts or steal one more car, and short enough that the
# toast isn't stale by the time it matters. Once per day, so it's a nudge, not a nag.
RENT_WARN_TIME = 45.0
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
WHOLE_SALE_RATE = 0.85           # (v0.14: was 0.7 when it was instant. It's papers + an auction + a
                                 # drive across town now, so it pays more for the trouble: still less
                                 # than stripping it yourself, a lot less spanner work)
WHOLE_SALE_SPORTY = 400
WHOLE_SALE_4X4 = 250

# --------------------------------------------------------------------------
# (v0.14) the business end. Bryce: "instead of the other shops you can buy being a shop in the
# open, make it so they are other garages that you have to clean out when you buy them (or pay
# someone to) and then its upgraded shops (mod shop too). gate some car components from the mod
# shop behind the shop you are in. also make it so the dolly needs to be upgraded via the REP
# points + upgrade quest to pick up bigger motor. Also please add drop off quests for parts. make
# the parts seller an auctioneer, so that the money doesn't come instantly, and you have to price
# your cars / deliver them after going to the precinct and buying papers for the car."
# --------------------------------------------------------------------------
# ---- the garages you buy: full of the last tenant's rubbish -------------------------------
JUNK_ID_BASE = 65300             # the junk piles' fixed entity ids (3 garages x 8 piles; below the cells)
JUNK_PER_SHOP = 8                # piles per garage (mapgen._make_fence places exactly this many)
JUNK_SIZE = 1.7                  # m square: a sofa, a fridge, forty tyres. Too big to drive through
JUNK_CLEAR_TIME = 3.0            # s of hold-E per pile: shifting a fridge is a proper job
JUNK_SCRAP = (5, 30)             # $ the scrapyard pays for each pile's worth of metal
JUNK_PART_CHANCE = 0.3           # ...and sometimes there's a usable part in there. Knackered, but usable
CLEANUP_PRICE = (0, 400, 900, 1800)   # $ to pay a crew instead (by shop index): cheaper than your time?
CLEANUP_PILE_TIME = 5.0          # s per pile for the crew: 40 s for the lot. They're not rushing
GARAGE_CRATE_GAP = 1.75          # m between the crates along a bought garage's back wall
# ---- which mod-shop parts each shop's counter will sell (index = the shop's number - 1) --------
# Anything not listed is sold everywhere, home counter included. Fitting parts you already have
# works at any counter -- it's only BUYING new that's gated, because the fancy supplier only
# delivers to the fancy address.
PART_SHOP_TIER = {
    # shop 2 (the first garage you buy): the street-tuner catalogue
    "whl_tuned_light": 1, "bmp_tuned_aero": 1, "exh_tuned": 1, "hood_tuned_cf": 1, "seat_tuned_bkt": 1,
    "ecu_tuned": 1, "spl_wing": 1, "spl_whale": 1, "eng_sc_1_6": 1, "eng_vtec_1_8": 1,
    # shop 3: proper engines and the gearbox that goes with them
    "eng_tuned_2_0t": 2, "trn_tuned_6mt": 2, "eng_rotary_13b": 2, "spl_shelf": 2,
    # shop 4: the two engines people get murdered over
    "eng_tt_3_0": 3, "eng_sc_6_2": 3,
}
EXTRA_SHOP_TIER = (1, 2, 0, 1, 1)   # NOS, ejector seat, gnome mount, hydraulics, the jack (garage.EXTRA_*)
# ---- Dave the auctioneer (the old sell bench) --------------------------------------------------
# (label, price x value, chance somebody bids, s to the hammer). Ask more and you wait longer and
# might get nothing: an unsold part goes back in the locker, an unsold car stays in the shop. The
# expected payout peaks at PUNCHY and falls off hard at GREEDY -- greed is a bet, not a free
# upgrade -- but it's not a stupid bet with a car you're happy to re-list.
# (v0.19, QA: "QUICK currently wins": 0.8 x 100% in 15 s beat FAIR's 0.85 x 100% in 30 s outright,
# so nobody ever waited.) Now every rung is a real trade: QUICK 70% for sure and fast, FAIR
# 85% expected, PUNCHY 94% expected but slower, GREEDY only 64% expected AND a listing fee.
AUCTION_ASKS = (("QUICK SALE", 0.7, 1.0, 10.0),
                ("FAIR", 1.0, 0.85, 25.0),
                ("PUNCHY", 1.25, 0.75, 40.0),
                ("GREEDY", 1.6, 0.40, 60.0))
AUCTION_UNSOLD_FEE = (0.0, 0.0, 0.0, 0.10)   # share of the ask Dave keeps when a lot of that tier fails to sell:
                                             # only GREEDY pays it. Dave's time is money, and he's seen you coming
AUCTION_DEFAULT_ASK = 1          # what everyone starts on: FAIR
AUCTION_MAX_LOTS = 16            # (v0.19: was 8) Dave's book: the shop's patter budget...
AUCTION_LOTS_PER_SHOP = 4        # ...plus this many for every extra garage of yours that's open. More
                                 # counters, more lots; Dave hires a temp
AUCTION_CAR_TIME = 1.5           # cars take this much longer to hammer than parts (x the ask's time)
# ---- papers, from the precinct's records hatch ------------------------------------------------
PAPERS_RATE = 0.1                # a logbook costs this share of what the car would fetch...
PAPERS_MIN = 100                 # ...but never less than this. The clerk has standards. Low ones.
PAPERS_MAX_HEAT = 25.0           # above this the clerk recognises you from the wall behind her
PAPERS_TIME = 1.5                # s of hold-E: filling in forms
# ---- contacts: drop-off orders for parts, and buyers for the cars you auction -----------------
CONTACT_COUNT = 8                # people round town who'll buy things off you, no questions asked
CONTACT_HANDOVER_R = 7.0         # m: park a sold car this close to its buyer and it's delivered
ORDER_SLOTS = 3                  # standing orders at once
ORDER_RATE = 1.5                 # they pay this x the part's value (way better than Dave, but a drive)
ORDER_BONUS_EACH = 30            # + this x the count when the whole order's filled (v0.19: was 60; on top of
                                 # 1.5x value the set bonus was making Dave's auction look silly)
ORDER_NEW_DELAY = 25.0           # s before a filled order's slot gets a new one
ORDER_REP_PER_DAY = 2            # REP from drop-offs, capped: the daily jobs are still the main way up
ORDER_HANDOVER_TIME = 0.8        # s of hold-E: "is it hot?" "no." "...it's warm."
# ---- the dolly: Mo's upgrades ------------------------------------------------------------------
# An engine's size class (parts.ENGINE_CLASS): 0 four-pots and smaller, 1 sixes, 2 V8s and the
# diesel. The dolly you start with takes class 0. Each upgrade is a job from Mo: the REP to be
# worth his time, a part he needs handing over at his counter, and his fee for the welding.
# (REP, $ fee, category Mo wants, min engine class of it, the name)
DOLLY_UPGRADES = ((4, 300, "trans", 0, "HEAVY-DUTY DOLLY"),
                  (10, 900, "engine", 1, "ENGINE CRANE"))
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
# (v0.17.1, Bryce: "add a handle to close all the doors at once") a big red knife-switch on the
# shop's west wall, by the walking door, that shuts (or opens) every door in one pull.
DOOR_HANDLE_INSET = 0.2          # m off the west wall's inner face: mounted flush, so nobody can walk behind it
DOOR_HANDLE_FROM_FRONT = 3.0     # m back from the doorway line: close enough that you grab it on the way in,
                                 # far enough that it's not in the walking door's swing (or bay 0's car)
DOOR_HANDLE_REACH = 2.0          # m: how near you stand (a touch over AIM_REACH, so no hugging the wall)
DOOR_HANDLE_AIM = 1.6            # m: how close your aim has to be to the lever itself
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
# Volume sliders (settings screen), each 0..1. Final gain = (master * bus) ** VOLUME_CURVE.
# Curve 2.0: perceived loudness is roughly logarithmic, so slider 0.5 -> gain 0.25 (-12 dB) sounds about
# half as loud; a linear slider would feel like nothing happens until the bottom. 1.0 = the mix exactly
# as tuned before sliders existed (audio.MASTER and MUSIC_VOLUME are the baseline). The ONE set of
# default numbers: settings.py shows them as percent (VOL_*_DEFAULT below are just x100).
VOLUME_DEFAULTS = {"master": 1.0,    # the OS volume knob is the real "quiet", so master starts full
                   "music": 0.7,     # the beat sits under the engines and the crunching, not on top
                   "sfx": 1.0,
                   "engine": 0.8}    # engines run constantly, so a touch under the one-shots
VOLUME_CURVE = 2.0
MUSIC_VOLUME = 0.45              # the beat sits under the engine and the sirens, not on top of them

# ---- (v0.18) soundscape: horns, the shop's dead zone, ambience (soundscape.py, audio.py) ----
# Traffic honks are short beeps under a budget; before, one continuous horn loop played at the loudest
# honking car's volume, so a jam was a solid wall of horn. Your own horn (and a stolen cop car's) is
# still the old continuous loop: that one is gameplay (it confuses cops, opens the shop door).
HORN_HEAR_DIST = 45.0            # m: past this a traffic honk isn't worth a mixer channel (was 60 m of linear fade)
HORN_FALLOFF_EXP = 2.5           # gain = (1 - d/HEAR)**this: steep, so a jam two blocks off is a murmur, not a wall
HORN_BUDGET_MAX = 3              # at most this many audible traffic honks...
HORN_BUDGET_WINDOW = 4.0         # ...per this many seconds, however many cars are leaning on it (nearest win)
HORN_MIN_GAP = 0.25              # s between any two honks: beeps overlap into a chord, not a klaxon
HORN_CAR_COOLDOWN = (1.6, 3.6)   # s a car waits before it may honk again; each car gets its own value from its id
HORN_BLAST_VOL = 0.55            # one traffic honk at point blank, before the sfx bus; the stock loop is ~0.63
SFX_RANGE = 90.0                 # m an ordinary one-shot carries (the old hard-coded 90)
SFX_RANGE_LOUD = 170.0           # m for explosions, shotguns, big crashes: they carry across the city
SFX_FALLOFF_EXP = 1.5            # gain = (1 - d/range)**this; the old straight line kept mid-range sounds too loud
SFX_VOL_JITTER = 0.12            # +-% level wobble per play so a run of punches isn't a machine gun of clones
PAN_STRENGTH = 0.65              # how far the far ear drops when a source is dead to one side (1 = silent)
PEAK_CEIL = 0.92                 # every synthesised sound is scaled down if it would peak above this (no clipping)
DEADZONE_FADE = 0.3              # s to fade the outside in/out when a shop door moves, so it never clicks
DEADZONE_LEAK_PER_DOOR = 0.8     # outside level let in per fully open door: one door = 80%, two = everything
DEADZONE_DOOR_SHUT = 0.04        # a door open less than this counts as shut (the roller's last inch)
DEADZONE_THUD = 0.12             # level of the muffled thump of an explosion / big crash through shut doors
DEADZONE_DOOR_SOUND = 0.7        # the roller door's own noise (and cops banging on it) is on the wall: both sides hear it
AMBIENCE_VOLUME = 0.20           # the city bed: felt more than heard (sirens and the beat sit well above it)
AMBIENCE_CAR_MUFFLE = 0.6        # inside a car the bed drops to this share: doors and glass
HELI_VOLUME = 0.30               # the chopper's thump while heat >= HELI_HEAT: an alarm bell, not a wall
MOUSE_PITCH_SENS = 0.0022        # look up/down: share of the view height per mouse count
PITCH_LIMIT = 0.42               # ...up to this share of the view (y-shearing gets weird past it)
# ---- sprite angles (v0.8, Bryce: "make the objects you interact with have more angles so they
# feel more real"). Box models are rendered once per angle and cached, so more angles cost a
# little memory and a little first-sight rendering, not frame time.
# (v0.17, Bryce: "up the resolution on all objects by 4x... add extra angled frames": doubled again.)
CAR_ANGLES = 64                  # was 32 (16 before that): a car turning in front of you is a smooth swing now
CHASE_CAR_ANGLES = 144           # your own car in the chase cam: 2.5 degrees a frame, you can't see the steps
PERSON_ANGLES = 32               # was 16 (8 before that)
PROP_ANGLES = 32                 # crates, the dolly, gnomes, traps, the gate (was 16)
# ---- (v0.17) the hi-res pass. The 3D view renders at RENDER_SCALE x 640x328; the HUD stays
# 640x360 and is scaled up over it, chunky as ever. 2 = 1280x656, exactly a 1080p desktop's 2x
# window, so the frame goes to the screen 1:1. 3 is for 4K and brave CPUs; 1 is the old look.
RENDER_SCALE_DEFAULT = 2
RENDER_SCALE_MIN, RENDER_SCALE_MAX = 1, 3   # (the settings slider's range) past 3x the sprite blits eat the frame
# (v0.19, Bryce: "update the resolution of the background assets to match the render scaling")
# WORLD SCALE w: walls, street, ceilings and sky draw at w x 640 columns/rows, with textures built at
# w x their old texel density (more mortar, window frames, grime -- not blur). Always <= the render
# scale k (a 3x wall in a 2x view is 3x the work for pixels nobody can see). 1 = the v0.17 look:
# the world at 640 wide, blown up k x under the full-res sprites (fp._world_pass).
WORLD_SCALE_MIN, WORLD_SCALE_MAX = 1, 3
WORLD_SCALE_DEFAULT = 1          # (set from the A/B timing in the v0.19 notes; see FPRenderer.set_world_scale)
FLOOR_DETAIL_DIST = 22.0         # m: street rows nearer than this come from the hi-res floor chunks. Past it a
                                 # screen row covers more than a metre of road, so 4 px/m is already too many
FLOOR_CHUNK_M = 32.0             # m per side of one hi-res floor chunk (8 tiles): small enough that a new one is
                                 # a ~1 ms job when you drive into it, big enough that 9 cover what you can see
FLOOR_DETAIL_MB = 24             # LRU budget for those chunks. 32 m at 15 px/m is 0.9 MB, so ~26 at w=3: a
                                 # 3x3 neighbourhood with room to double back without rebuilding
FLOOR_CHUNKS_PER_FRAME = 2       # new chunks built per frame at most; the rest borrow the blurry base floor for
                                 # a frame or two (a 60 m/s car shouldn't hitch because it outran the cache)
SKID_LOG_PER_CHUNK = 1500        # skid segments remembered per chunk (to redraw one that was evicted). A
                                 # minute of doughnuts in one car park; ~150 KB a chunk at worst
WALL_TEX_MB = 96                # wall textures (every light level of every facade you've driven past), LRU.
                                 # A 3x six-storey facade fully shaded is ~7 MB; a street's worth fits
WALL_TEX_KEEP = 48               # ...but never fewer than this many, so one frame can't evict its own walls
# Box-model sprites are drawn at SPRITE_DETAIL x their old pixels-per-metre when you're up close
# (a car 12 -> 48 px/m). Only up close: each sprite has mips at 1x, 2x, 4x and the renderer picks
# the smallest one that still covers the screen pixels, so a car 80 m away costs what it used to.
SPRITE_DETAIL = 4
SPRITE_MIP_BIAS = 1.0            # a mip must have >= this x the on-screen px/m; <1 trades sharpness for RAM
SPRITE_CACHE_MB = 160            # every cached sprite angle, by pixel bytes (LRU). A 48 px/m car is ~100 KB,
                                 # the chase cam's 80 px/m one ~300 KB: about a busy street's worth, well
                                 # under the 1 GB we promised the process would stay under
FOV_MIN, FOV_MAX = 60, 120       # the FOV slider's range: below 60 is a tube, above 120 the walls bend
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
                                 # (v0.17: the default; the settings slider calls FPRenderer.set_fov)
FP_EYE = 1.6                     # metres: standing eye height
FP_EYE_CAR = 1.2                 # sitting in a Kei, knees round your ears
FP_EYE_BIKE = 1.55               # (v0.13) on a bike: sat up high, hunched over the tank
FP_FLOOR_DIST = 70.0             # metres of textured street before it fades to haze
FP_SPRITE_DIST = 95.0            # beyond this, cars and people aren't drawn (matches the net cull)
FP_TURN_SPEED = 2.8              # rad/s turning with the arrow keys
MOUSE_SENS = 0.0032              # rad per mouse pixel
# (v0.19) the player's MOUSE SENSITIVITY slider multiplies MOUSE_SENS and MOUSE_PITCH_SENS. Stored as an
# integer percent in settings.json (the settings code only deals in ints): 100 = the tuning above.
MOUSE_SENS_MIN = 25              # 0.25x: slow enough for a sniper's patience, or a very large desk
MOUSE_SENS_MAX = 300             # 3x: one flick of the wrist is a U-turn; past this nobody can aim
MOUSE_SENS_DEFAULT = 100         # 1.0x, the feel the game was tuned at
MOUSE_SENS_STEP = 5              # A/D steps the slider 5 points (0.05x)
FP_BOB = 0.06                    # metres of head bob when walking (Doom had lots; this has some)

# --------------------------------------------------------------------------
# (v0.20) The 3D renderer (gl3d.py, Bryce: "lets transition to a 3d game, but use the stylized
# look of doom"). Real meshes from the same box models, a GPU, and every trick that keeps it
# looking like 1993 anyway. RENDERER_DEFAULT is what a fresh settings.json starts on.
# --------------------------------------------------------------------------
RENDERER_DEFAULT = "3d"          # "3d" or "classic" (the raycaster; also the automatic fallback with no OpenGL)
GL_NEAR = 0.05                   # m: the near clip. You can put your nose 5 cm from a bumper and still see it --
                                 # the whole point of the switch was walking right up to cars
GL_FAR = 600.0                   # m: past the far corner of a 540 m city (the fog's long gone by then)
GL_LIGHT = (0.35, -0.55, 0.8)    # the sun's direction (x, y, z up), fixed in the world: high and from the
                                 # south-east, so a car's roof is brightest and its two sides never match
GL_OUTLINE_PX = 1.0              # dark edge round every box face, in 640-wide pixels (x the render scale):
                                 # the one-pixel outline the old sprites had, kept so boxes still read as boxes
GL_COLOR_LEVELS = 32             # steps per colour channel. 256 is smooth modern banding; 32 gives every
                                 # shade a slightly hand-picked palette look without posterising the sky
GL_CULL_BEHIND = 10.0            # m: keep things whose middle is this far BEHIND the camera (a 10 m counter
                                 # beside you still pokes into view; the sprite view dropped at 0.3 m ahead)
GL_CULL_MARGIN = 10.0            # m: ...and this far outside the side edges of the view, for the same reason
GL_MESH_CACHE = 1500             # meshes kept (LRU). A car look is ~60 KB of GPU memory, a person ~20 KB:
                                 # a whole busy district's worth for well under 100 MB
GL_GROUND_MIP_EVERY = 0.5        # s between rebuilding the street's mipmaps after new skid marks (the far
                                 # street can be half a second behind; the near street is updated at once)
GL_SKY_SCALE = 2                 # the sky panorama's detail (fpart.make_sky's sc), capped: 3x is 30 MB and
                                 # the clouds look the same
GL_DOOR_STEPS = 32               # a rolling door's poses: one mesh per 1/32 of its travel (a 1.4 s roll at
                                 # 60 fps is 84 frames, so it still moves smoothly; it can't be 84 meshes)


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


# --------------------------------------------------------------------------
# (v0.17) player settings (settings.py; the SETTINGS screen in the main menu and pause menu)
# --------------------------------------------------------------------------
# (FOV_MIN/MAX and RENDER_SCALE_* live with the rest of the hi-res settings, up by CAR_ANGLES)
# the volume sliders' defaults in percent: VOLUME_DEFAULTS (with the sound settings), x100
VOL_MASTER_DEFAULT = int(round(VOLUME_DEFAULTS["master"] * 100))
VOL_MUSIC_DEFAULT = int(round(VOLUME_DEFAULTS["music"] * 100))
VOL_SFX_DEFAULT = int(round(VOLUME_DEFAULTS["sfx"] * 100))
VOL_ENGINE_DEFAULT = int(round(VOLUME_DEFAULTS["engine"] * 100))

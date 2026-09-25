# CLAUDE.md — Chopped handoff

You're picking up **Chopped**, Bryce MacKenzie's co-op car-theft chop-shop game. Two codebases exist:

1. **This folder — the Python version.** A Doom-style first-person pixel-art game (with a top-down automap) for 1–4 players online. It works and its tests pass. **Your main job is here.**
2. **The Unity version** at `F:\Unity\Projects\Chopped`. It's first-person, uses Unity 6.6 with Netcode for GameObjects (NGO), and its game-loop scripts are written but have never been compiled. See the section at the bottom.

Tone: GTA 2 meets a heist gone wrong. Code comments are funny *and* explain why each tuning value is what it is. Keep that style.

---

## 1. Status and your tasks, in order

### Where things stand (Sept 25, 2026, session 2, fifth round: v0.8)
- **v0.8** (Bryce: "instead of the cops shooting you lethally right away have them try to handcuff you. then you get taken to the precinct where you have to beat your way out. and also make the objects you interact with have more angles ... if the cops do decide to lethally shoot you that you die, lose a/x % of your money depending on how many people are playing. the drifting feels too loose, please allow the driver to regain control when handbraking. add brakestands, spinning tire sounds and a tachometer ... better engine sounds ... turbo noises ... super chargers and a few more engine options. add riced out cars and 4x4 trucks. also add 10 more funny features"). All done:
  - **Police** (`police.py`, a World mixin): cop cars that catch a crook on foot let an **officer** out (NPC kind `OFFICER`, `Car.officer`); he runs you down and cuffs you (`CUFF_TIME`; mash Space or punch him to break free). **Tasers** from `TASER_HEAT`. **Lethal force only after the crew escalates** (`World.lethal_t`, set by `_escalate` when a gunshot is heard by police, or when a cop/cop car is hit). A lethal hit = `DEAD` state, **WASTED**, crew loses `DEATH_LOSS / players` of its cash.
  - **The precinct**: `mapgen._make_precinct` puts a walled lockup on a block >= `PRECINCT_MIN_BLOCKS` from the shop (new tile `PRECINCT`). Busted -> `CUFFED` for 3 s (mugshot toast from `Player.rap`) -> `_jail`: `Player.jailed`, guards (`GUARD`, `KEYGUARD`). Take the keys off the downed key guard, E at the gate (a `Trap` of kind `TRAP_GATE`, kept in `World.gate_trap`, NOT in `World.traps`; solid while shut, sent as a trap row). Or: a crewmate picks the lock, someone rams it, or bail at the desk. Escapees wear the **orange jumpsuit** (wanted on sight) until they reach the shop.
  - **Drift**: `Physics._drift_assist` (nudges the nose toward travel past ~17 degrees, damps rotation that worsens the slide), a keyboard-friendly countersteer limit, a yaw-rate cap (kills tank-slappers) and a handbrake yaw cap. **Brake stands / donuts** (W+S, `Physics._brake_stand`). All of it is in the shared Physics, so it predicts (`test_engines.test_burnout_predicts`).
  - **Engines**: 8 new ones incl. two superchargers (`parts.ENGINE_SPECS`: voice, aspiration, redline, idle), per-model engine tables, `Car.pops()`. **Rice rockets** (`V.RICE`) and **4x4s** (`V.TRUCK4`: `awd`, `offroad`).
  - **Sound**: `enginesynth.py` renders each engine voice at `ENGINE_BANDS` rpm points (background thread at startup, ~0.3 s); `audio.engine_note` crossfades neighbouring bands on two channels. Turbo whistle bands, blow-off/flutter, pops, shift clunk, tyre screech. `drivetrain.Tacho` (client-only, cosmetic) turns speed + pedals into revs/gear/boost for the **tachometer** and the audio. Car rows carry an engine byte and a drive byte (`DR_*`) so you hear everyone's engine.
  - **More angles**: `CAR_ANGLES` 32 (was 16), `CHASE_CAR_ANGLES` 72, `PERSON_ANGLES` 16 and `PROP_ANGLES` 16 (were 8). Sprites render in <1 ms and are cached.
  - **Silly**: K9 dogs (take your trousers), the streaker (cops chase him instead; tackle him for a reward), speed cameras (fines on your own ride), burnout smoke screens (`TRAP_SMOKE`, block witness sight), hydraulics (mod shop extra, X), pops and bangs + two-step, VTEC toast, mugshot charge sheets, one phone call, orange jumpsuit, delivery confetti.
  - Fixed in passing: every wall sign in the raycaster was mirrored (CHOP SHOP read backwards since v0.5).
- **Protocol VERSION 8, RELEASE 0.8.0:** car rows +engine byte +drive byte; player rows +flags2 (`PF2_*`); snapshot header +alert byte (`AL_LETHAL`); NPC states `NS_TASER`, `NS_CUFFING`, `NS_RUNOFF`; trap kinds `TRAP_GATE`, `TRAP_SMOKE`; `B_HOP` button.
- **Tests:** 163, all OK (v0.8 added `test_police.py` and `test_engines.py`). Game-loop selftest about 51 fps.

### v0.7 (earlier this session)
- **v0.7 is the big one.** Bryce asked for: higher resolution, "realistic drifting", a 3rd-person view when driving, "much more fighting back from the people", more cops, storage in cars, other vehicles, "more randomized car styles so it's worth placing the parts you find on your car", a GTA-style car editor, then "10 more silly features" (throwing parts, picking people up and throwing them, looking up/down, jumping, "ridiculous ideas to make the boys laugh"). All done:
  - **Resolution:** the canvas is now 640×360 (was 480×270), integer-scaled. First person draws into 640×328 with the 32 px bar below. HUD drawing goes through `doomhud.Pen`; the bar has new ARMS and GEAR panels.
  - **Tyre model** in `physics.Physics._drive`: bicycle model, a Pacejka-ish slip curve, a friction ellipse, weight transfer (capped at 1 g), handbrake locks the rears, caster self-aligning steer, a DRIFT meter. `tests/test_drift.py` pins down the feel. Traffic/cop AI gets traction control.
  - **Chase cam (V)**, pitch (mouse up/down; the raycaster y-shears), and **jumping** (Space on foot; clears roadblocks above `HURDLE_HEIGHT`). z is in the SELF block, so jumps predict.
  - **8 vehicle models** (`vehicles.py`): Kei, sedan, sports coupe, muscle, pickup, box van, ice cream van, mobility scooter. Each has its own box size (`Car.hl/hw`), mass, grip, top speed, accel, drive layout and trunk. Every styled part (wheels, hood, bumpers, exhaust, doors, the new spoiler slot) rolls a style that shows on the car and changes the price. Paints, liveries, horns and underglow are per car.
  - **Trunks** (`garage.py`): E at the back of your ride or a broken-into civ car. Stolen cars carry loot. Pickups/vans have a bed for dolly engines.
  - **Mod shop** (`garage.py` host side + `modshop.py` client): E at TUNE-UP opens a GTA-style menu over the crew's parts **locker** (`World.stash`). Fit, buy (1.6×, every style), remove, sell, take, paint, livery, horn, underglow, extras (NOS, ejector seat, hood gnome). Keyboard and mouse. **It replaces the old parts counter and bench-install.** Commands ride in the input, one at a time, acked by the host.
  - **Peds fight back** (`brawl.py`): 35% are brave, 30% of those are armed; they rally, take three knockdowns, and take their money back if you robbed them. 50% of carjacked drivers come back swinging.
  - **More cops:** a wanted level (1/2/3/5 units at 25/50/75/100 heat, `COP_TIERS`), 2 patrol cars always cruising, cops shoot at crooks on foot from 75 heat.
  - **Silly stuff:** throw parts (click with full hands), pick up (G) and throw people, human bowling (STRIKE!), haymaker (hold click), ejector seat + parachute, joke horns, NOS, donut boxes (cops stop to eat), banana peels, big-head mode (F9), dance taunt (T), garden gnomes, ice cream van queues, YEETED/HUMBLED/HOME RUN banners.
  - Code split: `enums.py`, `lines.py`, `entities.py`, `physics.py`, `vehicles.py`, `brawl.py` and `garage.py` came out of `sim.py`, which still re-exports the names tests use (`S.Car`, `S.B_UP`, ...). `World(Physics, Brawl, Garage)`.
- **Protocol VERSION 7, RELEASE 0.7.0:** input buttons are u16 plus 4 menu bytes; car rows carry model, livery, extras and packed styles; player/NPC/pickup rows carry z; the SELF block carries grip/mass/top/NOS/spin (`SELF_EXTRA`), an 8-byte arsenal, and optional trunk and menu blocks.
- **Performance:** `fp.draw` is about 8–9 ms at 640×328 in a busy street (was 6 ms at 480×238).

### v0.6 (earlier this session)
- **v0.6 is crime** (Bryce: "i want the ability to punch and rob people also add guns. and please add traps for us to buy to actually stop the cars, currently i cant seem to rob a car"):
  - **Why "can't rob a car":** parked cars worked, but moving traffic showed no prompt at all, and there was nothing to point you at a stealable car. Fixed with carjacking, a "IT'S MOVING. STOP IT FIRST" hint, green arrows over stealable cars (orange over stopped traffic) and a **CAR TO STEAL** compass.
  - **Fists** (click/Ctrl): knock peds down, knock crewmates over. **Robbing:** hold E on a downed or hands-up ped.
  - **Guns** (pistol, shotgun), hitscan (`World._ray_hit`): drop people, shoot out tyres, burn cop cars. Pointing one makes peds surrender.
  - **Black market:** 5 crates in the shop (`CityMap.market`): pistol, shotgun, ammo, spike strip, roadblock.
  - **Traps** (`sim.Trap`, `World.traps`): spikes knock wheels off (traffic with 2 missing wheels bails); roadblocks are solid (`World.extra_rects`, used by `Physics` and so by the predictor) and traffic stops at them.
  - **Carjacking:** hold E on stopped traffic.
  - Weapons select with 1–5 / wheel / Q, client-side; the server validates ownership (`Player.owns`).
- **Protocol VERSION 6:** inputs carry a fire counter and the selected weapon; the SELF block adds 6 arsenal bytes; player rows add the weapon; snapshots carry traps and shot (tracer) events.
- **v0.5 is Doom-style first person**, at Bryce's request ("more of a doom style game"). The top-down view is kept as the Tab automap.
  - `fp.py`: the raycaster (textured walls, mode-7 floor, skies, sprites)
  - `fpart.py`: all first-person art, generated in code
  - `doomhud.py`: status bar, face and overlays
  - Controls: mouse look, WASD with strafe. Interactions use what you're looking at (`World._aim`).
- **Faster pacing** (Bryce: "doesn't play as fast as I want"):
  - walk 6.0 and sprint 10.0 m/s
  - every action timer halved
  - 6 parked cars instead of 4
- **Rent:** once per 3-minute day. $100 on day 1, then $75 more each day.
- **Music** (Bryce asked for "pouya / suicide boys type beat"): `music.py` renders an original dark trap / Memphis beat at startup, with no files. Layers switch at loop boundaries depending on heat. M toggles it; `--no-music` turns it off.
- **Protocol VERSION 5:** inputs carry the view yaw; snapshots carry the day number and rent due.
- **Windows exe:** built by GitHub Actions (`.github/workflows/build.yml`) on every push, and smoke-tested as an exe. Build #1 (v0.4) was green on Windows. Check the Actions tab for the latest run.
- The beat takes about 0.8 s to render in a background thread at startup, while you're in the menu.

### Task 1: Play the exe on a real Windows PC
1. Download the **Chopped-windows** artifact from the latest green **Build** run (Actions tab). If a future run fails, read the **smoke-logs** artifact.
2. By hand on a real PC: run `Chopped.exe --host`, then `Chopped.exe --join 127.0.0.1 --name TWO --fake-lag 150`. With prediction the joiner's own car should feel instant. Compare with `--no-predict`.
   - v0.8 things to feel out: is the drift assist too strong now (`DRIFT_ASSIST_*`, `YAW_CAP_*`, `COUNTERSTEER_*`)? Do the engine notes sound right on real speakers (`enginesynth.VOICES`)? Is the lockup too hard or too easy (`JAIL_GUARDS`, `GUARD_*`)? Is `DEATH_LOSS` too harsh solo?
   - v0.7 things to feel out: does the drifting feel right with a mouse + keyboard (tuning is `TIRE_*`, `STEER_*`, `WEIGHT_TRANSFER` in config)? Is the chase cam too floaty (`CHASE_*`)? Are 5 cops at 100 heat plus 2 patrols too many? Do brave peds make walking around too dangerous (`BRAVE_CHANCE`)?
3. Accept the Windows Firewall prompt (Private networks). SmartScreen will warn because the exe is unsigned: click "More info", then "Run anyway".

### Task 2: Real two-PC test
- Try LAN first, then the internet: UPnP, then a manual forward of UDP 27015, then Tailscale/ZeroTier (the host banner now lists VPN addresses too).
- Watch for:
  - prediction corrections on the joining player (they should only show when something the host knew about hit you)
  - traffic behaving oddly around the shop entrance
  - dolly handoffs between players
  - any disagreement in cash or heat

### Task 3: Remaining gaps / ideas, in rough order of player impact
- **Code signing:** SmartScreen warnings scare friends. An EV certificate or Azure Trusted Signing would fix it; that's Bryce's call because it costs money.
- **Remote entities are drawn 100 ms in the past.** That's fine for most things, but hitting a moving car another player is driving can look late. Lag compensation for car-vs-car would be the next step.
- **Traffic:** there are no traffic lights, and traffic never uses the shop's driveway. Ask Bryce whether traffic drivers should be heat witnesses; they aren't, on purpose (see section 4).
- **Content ideas:**
  - gamepad support (pygame-ce `_sdl2.controller`)
  - a second dolly for 3–4 player crews
  - ~~a proper parts-counter menu~~ (done in v0.7: the mod shop)
  - more weapons/traps (a tow hook? caltrops?), a way to earn guns back after an arrest other than buying them again

---

## 2. Hard rules
- **Networking stays stdlib UDP.** No networking libraries; this keeps PyInstaller packaging trivial. `miniupnpc` is optional and must stay an optional import.
- **No asset files.** All sprites, textures, the pixel font, sounds and the music are generated in code (`art.py`, `fpart.py`, `audio.py`, `music.py`). Keep it that way unless Bryce says otherwise.
- **The sim modules must not import pygame:** `sim.py`, `physics.py`, `brawl.py`, `garage.py`, `police.py`, `entities.py`, `enums.py`, `vehicles.py`, `parts.py`, `lines.py` (and the client-side pure modules `drivetrain.py`, `enginesynth.py`). They're the authoritative, testable simulation.
- **All tuning numbers live in `chopped/config.py`**, each with a comment explaining why.
- **Bump `config.VERSION`** whenever the wire protocol changes. Clients with a different version get rejected politely.
- **Keep packets under `MAX_PACKET` (1150 bytes).** `tests/test_misc.py` checks a worst-case snapshot, rush-hour traffic included.
- **Movement and collision code lives in `physics.Physics`** (`_drive`, `_car_vs_world`, `_car_pair`, `_walk`, `_fall`, `_body_vs_*`; `sim.Physics` is the same class). The client's `predict.Predictor` inherits the same class. If the server's physics reads anything the client doesn't get, prediction silently diverges. Anything new that affects your own movement must go in the SELF block (`protocol.encode_self`). `tests/test_predict.py` fails loudly if the two drift apart.
- **Run the tests before claiming anything works:**
  ```
  set SDL_VIDEODRIVER=dummy & set SDL_AUDIODRIVER=dummy & python -m unittest discover -s tests -v
  ```
  (On Linux/macOS: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v`.) At handoff (session 2, v0.8): **163 tests, all OK**, and the game-loop selftest ran at about 51 fps.

## 3. Architecture (details in README.md)
- `main.py` is the command line: `--host`, `--join IP[:PORT]`, `--server` (headless), `--selftest`, `--port`, `--name`, `--mute`, `--no-upnp`, `--log FILE`, `--fake-lag MS`, `--no-predict`.
- **Networking model (protocol VERSION 8):**
  - The host runs the simulation at 60 Hz in-process.
  - Clients send one input per 60 Hz tick. One-shot keys are sent as counters, so a lost packet can't eat a tap.
  - The server sends each client its own zlib snapshot at 20 Hz. Far-away peds, pickups and traffic are culled beyond 95 m.
  - Each snapshot carries `ack_input` (the last input seq applied) and a SELF block: your full-precision car or avatar state, walk load and speed multiplier.
  - Every client, the host's loopback included, predicts its own entity with `physics.Physics`, rewinds and replays unacked inputs, and decays leftover error at `PREDICT_CORRECT_RATE`.
  - Mod shop commands (`garage.OP_*`) ride in the input as (menu_seq, op, arg, arg2). The client sends the next one only after the snapshot's menu block acks the last, and the host ignores a seq it has already run, so resends never double-bill.
  - Everything else is interpolated 100 ms in the past.
  - Toasts and sound events are resent until acknowledged.
- **Collision:** cars are oriented boxes (SAT) sized by their model (`Car.hl/hw`; the Kei is 4.4 × 2.4 m). The map's solid tiles are greedy-merged into 116 rectangles, so walls have no seams to snag on. People are circles.
- **Traffic:** `TRAFFIC` kind cars follow waypoints on the road grid (right-hand lanes, pure pursuit). Cars that drift more than 140 m from every player are recycled off-screen. `World.traffic_target = 0` turns traffic off (the tests do this).
- **City:** generated deterministically from a seed (`mapgen.py`), so clients rebuild it locally and it's never sent over the network.
- **Rendering:** the game draws to a 640×360 surface and scales it up with nearest-neighbour. F11 toggles fullscreen.
  - First person comes from `fp.FPRenderer`, drawing into a 640×328 view with the 32 px `DoomHud` bar below. Pitch shifts the horizon; V swaps to the chase camera behind your car.
  - Cars, people and props are coloured boxes (`fpart.car_boxes`, `person_boxes`, ...) rendered to sprites from 8–16 angles and cached. The mod shop preview and the automap sprites use the same boxes.
  - Tab switches to the top-down `render.Renderer` as an automap.
  - The first-person floor is the top-down map surface, rotated each frame, so anything drawn on the map (skid marks, labels) shows up on the street.

## 4. Game design and tuning (agreed with Bryce; don't change without asking)
- **Stealing:**
  - Break in by holding E for 4 s (v0.5, was 8). This triggers the alarm and adds +10 heat.
  - Hotwire by holding E for 3 s (v0.5, was 6); whoever hotwires becomes the driver.
  - Only one prompt shows for each car state: Locked → break in; BrokenIn → hotwire; Running → drive / ride shotgun; Delivered → strip; fully stripped → crush shell.
- **Driving:**
  - Top speed: the Kei 45 m/s, cops 48 m/s with 1.35× acceleration. Cops win the straights and lose the corners. (v0.7: the sports coupe, 53, and muscle car, 51, outrun cops on a straight. Deliberately: they're rare and worth stealing.)
  - Crashes are judged on how suddenly the car changes speed (delta-v), not on speed:
    - 6 m/s or more: dents, plus a 35% chance a panel flies off
    - 11 m/s or more: everyone is thrown out and tumbles
    - 18.7 m/s or more: wheels come off
- **Heat (0–100, shared by all players):**
  - Gain: cop sees you +5/s, pedestrian or angry owner +3/s, street camera +2/s (cameras only see stolen cars).
  - Witnesses don't stack; the highest single rate counts.
  - Cooling: −3/s once nobody has seen you for 4 s.
  - At 100 heat, up to 2 cop cars spawn.
  - Horn: cops within 40 m do donuts for 3 s.
  - Ramming a cop at over 25 m/s relative speed sets it on fire; it burns for 3 s, then explodes into loot.
- **Arrest** (changed in v0.8 at Bryce's request, see below):
  - ~~Triggered by standing on foot within 3.2 m of a cop car for 1 s.~~ Now an officer on foot has to reach you and cuff you (`CUFF_TIME` 1.2 s).
  - Your held parts drop at that spot, so a partner can grab them.
  - ~~You're cuffed for 5 s, then respawn at the shop.~~ Now 3 s on the kerb, then the precinct lockup. Cash is kept.
- **Delivery:** the car must be fully inside the garage and moving under 4 m/s. Heat drops to 0, the cops leave, and the car never drives again.
- **Carrying:**
  - Two hands. Wheels, ECUs and bucket seats take one hand; panels, exhausts, gearboxes and stock seats take both.
  - Engines are dolly-only: they can't be carried. Use the hand dolly in the shop.
  - Stamina pool is 100. Sprint drain is 12, 22 or 38 per second (empty, one-handed, two-handed). Walking two-handed drains 8/s.
  - Loose parts vanish after 10 minutes.
- **Money:**
  - Start with $300. **v0.5 (Bryce's request): rent is due once a day at midnight.** A day is 3 minutes. Rent is $100 on day 1 and $75 more each day after (`config.rent_for_day`).
  - 120 s below $0 means SHOP SEIZED. The new run resets cash, city cars, heat and loose parts, but **the personal car keeps its mods**.
  - A stock Kei Hatch is worth about $1,070 in parts.
- **Specials:** 12% of cars are clown cars (4 clowns burst out). 15% have an angry owner who chases at 5.5 m/s and counts as a heat witness.
- **Session 2 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **Traffic drivers are not heat witnesses**, and their horns don't confuse cops. This keeps the agreed heat balance. Making them witnesses would be a one-line change in `_witness_scan`.
  - **Traffic can't be stolen while driven.** A hard crash (at or above the eject delta-v) makes the driver bail and lock it. It becomes a normal LOCKED civilian car: normal break-in, alarm, +10 heat.
  - **Dolly:** there's one. Stripping an engine onto it uses the existing 20 s engine strip time, and the hood must come off first. Speed is ×0.85 empty and ×0.62 loaded. Loaded counts as two-handed for stamina. It returns home after 90 s abandoned outside the shop. Crushing still pays 50% for engines left in.
  - ~~**Parts counter**~~ (replaced by the v0.7 mod shop, same 1.6× price and no credit).
  - Pedestrians flee but still witness.
- **v0.6 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **Changed from session 2:** a traffic driver who bails after a hard crash (or after losing 2 tyres) now **leaves the engine running** instead of locking the car. Getting in counts as a theft: +10 heat (`HEAT_BREAKIN`), no alarm. This was the most direct fix for "I can't rob a car".
  - Punch +5 heat, rob +4, carjack +12, a gunshot +8 if a ped or cop is within 50 m, hitting a cop sets heat to 100. The crime heat is added directly (no line-of-sight check); the normal witness heat still applies on top.
  - Guns need empty hands (same as punching). Getting busted confiscates guns and ammo; traps in your pocket are kept.
  - Shooting a player tumbles them and makes them drop what they're carrying. There's no health anywhere: getting shot is a 1.8 s nap.
  - Traps: at most 12 in the world, towed after 150 s. Spike strips wear out after 3 cars.
- **v0.7 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **Cops (Bryce asked for "more plentiful"):** `MAX_COPS` 5 (was 2), dispatched by wanted level (`COP_TIERS`: 1 at 25 heat, 2 at 50, 3 at 75, 5 at 100), plus `PATROL_COPS` 2 always cruising. Patrols are witnesses but don't arrest until they engage. ~~From 75 heat cops shoot crooks on foot~~ (replaced in v0.8 by tasers and escalation-only lethal force).
  - ~~**Arrest range** 1 m from the cop car's bodywork~~ (replaced in v0.8 by officers on foot).
  - **The parts counter and bench-install are gone**, replaced by the mod shop. Buying is still 1.6× base value (times the style's value), condition 1.0.
  - **The locker (`World.stash`) is shared by the crew** and holds 40 parts; overflow is pushed onto the floor. SHOP SEIZED empties it (the car keeps its mods, as before).
  - **Peds fight back:** `BRAVE_CHANCE` 0.35, `ARMED_CHANCE` 0.3, a hit knocks you down for 0.9 s and empties your hands. Laughing, queueing and carried peds aren't witnesses.
  - Traffic bail behaviour is unchanged from v0.6 (the engine stays running).
  - Big-head mode, the chase camera and pitch are client-side only.
- **v0.8 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **"lose a/x % of your money"** was read as: the crew loses `DEATH_LOSS` (50%) divided by the number of players (50% solo, 25% for two, 12.5% for four). If he meant each player's full share (100% / players), set `DEATH_LOSS = 1.0`.
  - **When cops go lethal:** only after the crew fires a gun within `COP_HEAR_RANGE` (55 m) of any cop or officer, or hits a cop/cop car with a bullet; it lasts `LETHAL_TIME` (45 s) and refreshes on every shot. The v0.7 "cops shoot at 75 heat" rule is gone (tasers from 50 heat instead).
  - **Dying keeps your guns** (the cash is the penalty); **busted still confiscates them.**
  - **Jail has three ways out besides fighting:** a crewmate picks the lock (6 s), a car rams the gate (>= 9 m/s delta-v), or bail ($250 + $100 per previous arrest this run). Bail is there so a solo player who keeps losing to the guards isn't stuck forever.
  - **Jailbreak costs +40 heat** and the jumpsuit makes you a wanted target even at 0 heat until you reach the shop.
  - **Traffic bail behaviour and everything else in the heat model is unchanged.**
  - Drift assist is on for every player-driven car; AI cars keep their traction control instead.
- **Decisions the builder made and flagged** (fine to keep):
  - Cop dispatch stays on until heat reaches 0.
  - The horn has a 7 s cooldown per cop.
  - After a cop explodes, its replacement waits 9 s.
  - Abandoned stolen cars get towed after 60 s if everyone is more than 110 m away.
  - Shift sprints (in a car with NOS, Shift boosts).
  - You keep held parts when you get into a car.

---

## 5. The Unity version (secondary; only if Bryce asks)
Path: `F:\Unity\Projects\Chopped`. Unity 6.6 (6000.6.0f1), URP, NGO 2.13.2, Input System 1.20. Git is at the project root.

**Status:** the game-loop scripts were written on Sept 24, 2026, but **Unity has never compiled them.** They compile cleanly with Roslyn against hand-written API stubs, which only proves they're consistent with each other.

**New scripts under `Assets/_Chopped/Scripts/`:**
- `Vehicles/`: VehicleController, VehicleSeats, CarTheft, CarInteractPoint, VehicleCamera
- `Police/`: HeatManager, HeatWitness, CopSpawner, CopAI, CopChaseZone
- `Shop/`: ShopEconomy, GarageZone, SellBench, TuneUpBench
- `City/`: CitySpawner, ClownDummy, AngryOwnerNPC, PedestrianNPC
- `Player/`: PlayerVehicleLink, PlayerTumble, PlayerArrest
- `UI/GameLoopHud.cs`
- `Core/`: GameEvents, ProcAudio, Fx
- `Cars/PartsDropSystem.cs`
- `Editor/ChoppedGameLoopSetup.cs`

**Existing files that were changed** (review with `git diff`):
- `PlayerInteractor`: skips targets that have no prompt.
- `CarBody` and `SlotStripInteractable`: stripping is locked until delivery.
- `PlayerCarry`: adds drop-all and drops parts on disconnect.
- `DroppedPart`: parts decay after 10 minutes.
- `PlayerInputReader`: optional Honk action.
- `Settings/ChoppedControls.inputactions`: Honk bound to H and to the left stick press.

**Next steps:**
1. Open the project and let it compile. Fix any API mismatches. These are the ones most likely to break:
   - `NetworkTransform.Teleport` and `CanCommitToTransform`
   - `NetworkPrefabsList.PrefabList` and `.Add`
   - `NetworkObject.PrefabIdHash`
   - the `NetworkBehaviour.OnDestroy` override
   - `Rigidbody.automaticCenterOfMass`
2. Run **Chopped › Setup Game Loop**. It's safe to run more than once. It:
   - wires up the KeiHatch and Player prefabs
   - creates and assigns `Settings/ChoppedNetworkPrefabs.asset`. The NetworkManager previously had **no prefab list**, so runtime spawns would fail on remote clients.
   - builds the garage, the benches and a greybox city in `Shop.unity`
3. Press Play; `ChoppedBootstrap` auto-hosts in the editor. `ChoppedBootstrap` only auto-hosts **inside the editor**, so a built player needs a Host/Join menu before it can be played.

**Key decisions:**
- The driver's client owns the car and runs its physics. The server owns all game rules.
- CopAI and a CopKit child sit on every car prefab and wake up only when the car's role is Police.
- The victim's own client detects run-overs, and the server checks arrests by distance. Remote players' CharacterControllers are disabled on other machines, so trigger-based detection wouldn't work.

**Design notes** are in the claude.ai project "ChopShopSim": `claude/chopped-game-loop.md`, `claude/chopped-project-setup.md`, `claude/chopped-inventory-design.md` and `claude/chopped-python-port.md`.

## 6. About Bryce
- IT technician at School District 42 (SD42); based in Mission, BC. Comfortable with hardware, networking and CNC/electronics.
- Works on a Windows PC.
- Prefers imperial units for real-world measurements.
- Wants multiplayer, pixel art and a double-click exe that needs no installs for players.

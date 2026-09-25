# CLAUDE.md — Chopped handoff

You're picking up **Chopped**, Bryce MacKenzie's co-op car-theft chop-shop game. Two codebases exist:

1. **This folder — the Python version.** A top-down pixel-art game for 1–4 players online. It works and its tests pass. **Your main job is here.**
2. **The Unity version** at `F:\Unity\Projects\Chopped`. It's first-person, uses Unity 6.6 with Netcode for GameObjects (NGO), and its game-loop scripts are written but have never been compiled. See the section at the bottom.

Tone: GTA 2 meets a heist gone wrong. Code comments are funny *and* explain why each tuning value is what it is. Keep that style.

---

## 1. Status and your tasks, in order

### Where things stand (Sept 25, 2026, session 2)
- **Windows exe:** it's built by GitHub Actions (`.github/workflows/build.yml`) on `windows-latest`. The workflow:
  - runs all tests on Windows and Linux
  - generates the icon, builds from `Chopped.spec`, and smoke-tests the built exe (`tools/smoke_exe.py`: a solo selftest, then a host exe and a client exe over UDP)
  - uploads the **Chopped-windows** artifact. A `v*` tag also publishes a GitHub Release.
  - **First Windows run (Build #1, Sept 25, 2026): all green.**
    - All 56 tests passed on Windows and Linux.
    - `Chopped.exe` is 15.6 MB and was built with its icon and version info.
    - Smoke test on Windows: the solo selftest, the host and the client all printed SELFTEST OK at about 59–60 fps, and the host saw 2 players.
- **Gaps closed in session 2:**
  - client-side prediction
  - box collision
  - moving traffic and fleeing pedestrians
  - the hand dolly and the parts counter
  - exe icon and version info
  - VPN-proof host IP display
  - racing stripes on the wrong car kind
  - unobtainable exploded-cop engines
- **Tests:** 56, all OK on Linux with Python 3.12, including the 2-process game loop at about 61 fps.

### Task 1: Play the exe on a real Windows PC
1. Download the **Chopped-windows** artifact from the latest green **Build** run (Actions tab). If a future run fails, read the **smoke-logs** artifact.
2. By hand on a real PC: run `Chopped.exe --host`, then `Chopped.exe --join 127.0.0.1 --name TWO --fake-lag 150`. With prediction the joiner's own car should feel instant. Compare with `--no-predict`.
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
  - a proper parts-counter menu instead of "next best upgrade"
  - day/night

---

## 2. Hard rules
- **Networking stays stdlib UDP.** No networking libraries; this keeps PyInstaller packaging trivial. `miniupnpc` is optional and must stay an optional import.
- **No asset files.** All sprites, tiles, the pixel font and sounds are generated in code (`art.py`, `audio.py`). Keep it that way unless Bryce says otherwise.
- **`sim.py` must not import pygame.** It's the authoritative, testable simulation.
- **All tuning numbers live in `chopped/config.py`**, each with a comment explaining why.
- **Bump `config.VERSION`** whenever the wire protocol changes. Clients with a different version get rejected politely.
- **Keep packets under `MAX_PACKET` (1150 bytes).** `tests/test_misc.py` checks a worst-case snapshot, rush-hour traffic included.
- **Movement and collision code lives in `sim.Physics`** (`_drive`, `_car_vs_world`, `_car_pair`, `_walk`, `_body_vs_*`). The client's `predict.Predictor` inherits the same class. If the server's physics reads anything the client doesn't get, prediction silently diverges. Anything new that affects your own movement must go in the SELF block (`protocol.encode_self`). `tests/test_predict.py` fails loudly if the two drift apart.
- **Run the tests before claiming anything works:**
  ```
  set SDL_VIDEODRIVER=dummy & set SDL_AUDIODRIVER=dummy & python -m unittest discover -s tests -v
  ```
  (On Linux/macOS: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v`.) At handoff (session 2): **56 tests, all OK**, and `--selftest` ran at about 61 fps.

## 3. Architecture (details in README.md)
- `main.py` is the command line: `--host`, `--join IP[:PORT]`, `--server` (headless), `--selftest`, `--port`, `--name`, `--mute`, `--no-upnp`, `--log FILE`, `--fake-lag MS`, `--no-predict`.
- **Networking model (protocol VERSION 4):**
  - The host runs the simulation at 60 Hz in-process.
  - Clients send one input per 60 Hz tick. One-shot keys are sent as counters, so a lost packet can't eat a tap.
  - The server sends each client its own zlib snapshot at 20 Hz. Far-away peds, pickups and traffic are culled beyond 95 m.
  - Each snapshot carries `ack_input` (the last input seq applied) and a SELF block: your full-precision car or avatar state, walk load and speed multiplier.
  - Every client, the host's loopback included, predicts its own entity with `sim.Physics`, rewinds and replays unacked inputs, and decays leftover error at `PREDICT_CORRECT_RATE`.
  - Everything else is interpolated 100 ms in the past.
  - Toasts and sound events are resent until acknowledged.
- **Collision:** cars are 4.4 × 2.4 m oriented boxes (SAT). The map's solid tiles are greedy-merged into 116 rectangles, so walls have no seams to snag on. People are circles.
- **Traffic:** `TRAFFIC` kind cars follow waypoints on the road grid (right-hand lanes, pure pursuit). Cars that drift more than 140 m from every player are recycled off-screen. `World.traffic_target = 0` turns traffic off (the tests do this).
- **City:** generated deterministically from a seed (`mapgen.py`), so clients rebuild it locally and it's never sent over the network.
- **Rendering:** the game draws to a 480×270 surface and scales it up with nearest-neighbour. F11 toggles fullscreen.

## 4. Game design and tuning (agreed with Bryce; don't change without asking)
- **Stealing:**
  - Break in by holding E for 8 s. This triggers the alarm and adds +10 heat.
  - Hotwire by holding E for 6 s; whoever hotwires becomes the driver.
  - Only one prompt shows for each car state: Locked → break in; BrokenIn → hotwire; Running → drive / ride shotgun; Delivered → strip; fully stripped → crush shell.
- **Driving:**
  - Top speed: civilian 45 m/s, cops 48 m/s with 1.35× acceleration. Cops win the straights and lose the corners.
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
- **Arrest:**
  - Triggered by standing on foot within 3.2 m of a cop car for 1 s.
  - Your held parts drop at that spot, so a partner can grab them.
  - You're cuffed for 5 s, then respawn at the shop. Cash is kept.
- **Delivery:** the car must be fully inside the garage and moving under 4 m/s. Heat drops to 0, the cops leave, and the car never drives again.
- **Carrying:**
  - Two hands. Wheels, ECUs and bucket seats take one hand; panels, exhausts, gearboxes and stock seats take both.
  - Engines are dolly-only: they can't be carried. Use the hand dolly in the shop.
  - Stamina pool is 100. Sprint drain is 12, 22 or 38 per second (empty, one-handed, two-handed). Walking two-handed drains 8/s.
  - Loose parts vanish after 10 minutes.
- **Money:**
  - Start with $300. Rent is $150 every 60 s.
  - 120 s below $0 means SHOP SEIZED. The new run resets cash, city cars, heat and loose parts, but **the personal car keeps its mods**.
  - A stock Kei Hatch is worth about $1,070 in parts.
- **Specials:** 12% of cars are clown cars (4 clowns burst out). 15% have an angry owner who chases at 5.5 m/s and counts as a heat witness.
- **Session 2 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **Traffic drivers are not heat witnesses**, and their horns don't confuse cops. This keeps the agreed heat balance. Making them witnesses would be a one-line change in `_witness_scan`.
  - **Traffic can't be stolen while driven.** A hard crash (at or above the eject delta-v) makes the driver bail and lock it. It becomes a normal LOCKED civilian car: 8 s break-in, alarm, +10 heat.
  - **Dolly:** there's one. Stripping an engine onto it uses the existing 20 s engine strip time, and the hood must come off first. Speed is ×0.85 empty and ×0.62 loaded. Loaded counts as two-handed for stamina. It returns home after 90 s abandoned outside the shop. Crushing still pays 50% for engines left in.
  - **Parts counter:** at the tune-up bench with empty hands, it sells the next tier at 1.6× base value, condition 1.0. The replaced part drops on the floor. No credit.
  - Pedestrians flee but still witness.
- **Decisions the builder made and flagged** (fine to keep):
  - Cop dispatch stays on until heat reaches 0.
  - The horn has a 7 s cooldown per cop.
  - After a cop explodes, its replacement waits 9 s.
  - Abandoned stolen cars get towed after 60 s if everyone is more than 110 m away.
  - Shift sprints.
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

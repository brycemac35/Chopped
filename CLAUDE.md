# CLAUDE.md — Chopped handoff

You're picking up **Chopped**, Bryce MacKenzie's co-op car-theft chop-shop game. Two codebases exist:

1. **This folder — the Python version.** A top-down pixel-art game for 1–4 players online. It works and its tests pass. **Your main job is here.**
2. **The Unity version** at `F:\Unity\Projects\Chopped`. It's first-person, uses Unity 6.6 with Netcode for GameObjects (NGO), and its game-loop scripts are written but have never been compiled. See the section at the bottom.

Tone: GTA 2 meets a heist gone wrong. Code comments are funny *and* explain why each tuning value is what it is. Keep that style.

---

## 1. Your tasks, in order

### Task 1: Build `dist\Chopped.exe` on Windows (never done yet)
The code was written and tested in a Linux cloud box. PyInstaller only builds for the operating system it runs on, and that box couldn't download a Windows Python, so **no Windows build has ever been made.**

1. Check Python: `py -3.12 --version`. If it's missing, install Python 3.12 from python.org and tick "Add to PATH". Use 3.12 specifically: `miniupnpc` has Windows wheels only up to 3.13, and `pygame-ce` supports 3.10–3.15.
2. Run `build_windows.bat`. It creates `.venv`, installs pinned deps plus `pyinstaller==6.22.3`, builds a one-file windowed exe, then runs `dist\Chopped.exe --selftest --frames 300`.
3. If the selftest fails, the likely causes are:
   - a missing hidden import (check `Chopped.spec` or the `--collect-submodules chopped` flag)
   - SDL audio on a machine without an output device (audio is supposed to disable itself quietly)
   - antivirus quarantining the onefile exe (a false positive that's common with PyInstaller)
4. Test by hand. Run `dist\Chopped.exe --host`, then in a second window `dist\Chopped.exe --join 127.0.0.1 --name TWO`. Two instances on one PC work because the client uses an ephemeral port. Play the loop once: break in, hotwire, drive into the garage, strip, sell.
5. Accept the Windows Firewall prompt (Private networks).

### Task 2: Real two-PC test
- LAN first. Then over the internet: UPnP auto-forwards UDP 27015; the fallbacks are manual port forwarding or Tailscale/ZeroTier.
- Watch for:
  - input lag on the joining player: expected ~1 round trip, since there's no prediction yet (see Task 3)
  - rubber-banding
  - toasts arriving twice
  - any disagreement in cash or heat between players

### Task 3: Known gaps, in rough order of player impact
- **No client-side prediction.** The host feels no lag, but remote players feel a round trip of delay on their own car and avatar. The biggest improvement would be predicting the local player's own car or avatar with `sim.py`'s physics and reconciling it against snapshots.
- **Traffic and AI:** no moving civilian traffic, and pedestrians don't flee chases.
- **Collision:** cars collide as two circles, so buildings feel slightly round.
- **Content:**
  - no hand dolly, so engines only pay out via "crush shell"
  - no buying parts
  - no exe icon

---

## 2. Hard rules
- **Networking stays stdlib UDP.** No networking libraries; this keeps PyInstaller packaging trivial. `miniupnpc` is optional and must stay an optional import.
- **No asset files.** All sprites, tiles, the pixel font and sounds are generated in code (`art.py`, `audio.py`). Keep it that way unless Bryce says otherwise.
- **`sim.py` must not import pygame.** It's the authoritative, testable simulation.
- **All tuning numbers live in `chopped/config.py`**, each with a comment explaining why.
- **Bump `config.VERSION`** whenever the wire protocol changes. Clients with a different version get rejected politely.
- **Keep packets under `MAX_PACKET` (1150 bytes).** `tests/test_misc.py` checks a worst-case snapshot.
- **Run the tests before claiming anything works:**
  ```
  set SDL_VIDEODRIVER=dummy & set SDL_AUDIODRIVER=dummy & python -m unittest discover -s tests -v
  ```
  (On Linux/macOS: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v`.) At handoff: **25 tests, all OK**, and `--selftest` ran at about 61 fps.

## 3. Architecture (details in README.md)
- `main.py` is the command line: `--host`, `--join IP[:PORT]`, `--server` (headless), `--selftest`, `--port`, `--name`, `--mute`, `--no-upnp`.
- **Networking model:**
  - The host runs the simulation at 60 Hz in-process.
  - Clients send inputs at 30 Hz. One-shot keys are sent as counters, so a lost packet can't eat a tap.
  - The server sends each client its own zlib snapshot at 20 Hz, with far-away entities culled beyond 95 m.
  - Remote entities are interpolated 100 ms in the past. The host's own window is a 60 Hz loopback client.
  - Toasts and sound events are resent until acknowledged.
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
  - Engines are dolly-only: they can't be carried.
  - Stamina pool is 100. Sprint drain is 12, 22 or 38 per second (empty, one-handed, two-handed). Walking two-handed drains 8/s.
  - Loose parts vanish after 10 minutes.
- **Money:**
  - Start with $300. Rent is $150 every 60 s.
  - 120 s below $0 means SHOP SEIZED. The new run resets cash, city cars, heat and loose parts, but **the personal car keeps its mods**.
  - A stock Kei Hatch is worth about $1,070 in parts.
- **Specials:** 12% of cars are clown cars (4 clowns burst out). 15% have an angry owner who chases at 5.5 m/s and counts as a heat witness.
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

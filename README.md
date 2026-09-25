# Chopped

A chaotic co-op car-theft chop-shop game for 1-4 players online. First-person
pixel art with Doom energy (plus a top-down automap), and a heist that's
always one pedestrian away from going wrong. The soundtrack is a dark
Memphis-style trap beat, synthesized by the game itself.

Steal cars (or drag drivers out of them), drive them into your shop, strip
them for parts, sell the parts, and pay the rent. Punch people, rob people,
buy guns and spike strips off the crates in the back of the shop. If you fall
behind on rent, the landlord takes the shop.

- Pure Python 3.12 + pygame-ce. **No asset files**: every texture, sprite, font glyph, sound effect and the music are generated when the game starts. (The exe icon too, at build time.)
- Host-authoritative networking over plain stdlib UDP (no networking library), with client-side prediction so joining players don't feel their ping.
- Optional UPnP port forwarding via `miniupnpc`. The game works fine without it.

---

## Getting `Chopped.exe` (no Python needed)

GitHub builds it for you on every push, on a real Windows machine:

1. Open the repo on GitHub, then **Actions**, then the latest **Build** run.
2. At the bottom, under **Artifacts**, download **Chopped-windows**. It's a zip containing `Chopped.exe` and a short `README.txt`.
3. Give your friends the exe. They just double-click it.

The run also tests the game on Windows and Linux and smoke-tests the exe itself: a headless bot session, then a host exe and a client exe playing together over UDP. If any of that fails, the run goes red and no exe is uploaded.

To get a public download link, push a version tag (`git tag v0.6.0 && git push origin v0.6.0`). The workflow then publishes `Chopped.exe` as a **GitHub Release**.

> **SmartScreen:** the exe isn't code-signed, so Windows may say "Windows protected your PC". Click **More info**, then **Run anyway**.

---

## Quick start (from source)

```bash
python -m pip install -r requirements.txt     # pygame-ce 2.5.8, miniupnpc 2.3.3 (optional)
python main.py
```

Windows: `py -3.12 -m pip install -r requirements.txt` then `py -3.12 main.py`.

Command-line shortcuts:

| Command | What it does |
|---|---|
| `python main.py` | Main menu |
| `python main.py --host` | Host immediately on UDP 27015 |
| `python main.py --join 203.0.113.7` | Join immediately (`IP[:PORT]`, default port 27015) |
| `python main.py --name VINNIE` | Set your crook name |
| `python main.py --server` | Headless dedicated host (no window; everyone joins as a client) |
| `python main.py --selftest` | Starts headless, a bot plays for about 5 s, then exits 0 if everything worked |
| `--port N`, `--mute`, `--no-upnp` | Use a different port, turn off audio, skip UPnP |
| `--join 127.0.0.1 --fake-lag 150` | Pretend your ping is 150 ms higher. Try prediction on one PC |
| `--no-predict` | Turn client-side prediction off, to compare |
| `--no-music` | Sound effects only, no beat |
| `--log FILE` | Write everything the game prints, including crash tracebacks, to FILE (the exe has no console) |

---

## Controls

| Key | On foot | In a car |
|---|---|---|
| **Mouse** / **← →** | Look / turn | – (arrows steer) |
| **W S** / **↑ ↓** | Forward / back | Throttle / brake-reverse |
| **A D** | Strafe | Steer |
| **Shift** | Sprint (uses stamina) | – |
| **E** | Use whatever you're looking at. **Hold** it for timed actions; a progress bar appears | – |
| **Left click** / **Ctrl** | Punch, shoot, or put down a trap (hands must be empty) | – |
| **1-5**, **mouse wheel**, **Q** | Fists, pistol, shotgun, spike strip, roadblock (whatever you own) | – |
| **G** | Drop the part you're holding / let go of the dolly | – |
| **F** | – | Get out |
| **Space** | – | Handbrake (break traction and drift) |
| **H** | – | Horn. Cops within 40 m spin donuts for 3 s |
| **Tab** | Automap: the top-down view of the city | |
| **M** | Music on/off | |
| **Esc** | Pause overlay: players, host IP, ping. Releases the mouse. **Q** leaves | |
| **F11** | Toggle fullscreen | |

The status bar reads, left to right: **CASH**, **HEAT %**, **HANDS** (the dolly, or your ammo when a gun is out), your crook's **face** (it sweats as the heat rises, grins when money comes in, and sees stars when you get run over), **STAMINA %** (**KM/H** in a car), **COPS**, and **DAY / RENT**. The radar is top right. When you're carrying loot, a **SHOP** marker at the top of the screen points home; when you're empty-handed, a green **CAR TO STEAL** marker points at the nearest parked car. Bottom left, `1 2 3 4 5` shows the weapons you own.

---

## How to play

1. **Find a car.** Parked civilian cars show as white dots on the radar and have a **green arrow** floating over them; follow the green **CAR TO STEAL** marker at the top of the screen to the nearest one. There are up to six in the city. Traffic that's stopped gets an **orange arrow**: you can carjack it (see [Crime](#crime)).
2. **Break in** by looking at the car and holding E for 4 s. This sets off the alarm and adds **+10 heat**. Then **hotwire** it by holding E for 3 s, and you're the driver. A friend can press E to **ride shotgun**.
   - 12% of cars are **clown cars**. 15% have an **angry owner** who chases you and counts as a witness.
3. **Drive it home.** Follow the SHOP marker. Stop the car (under 4 m/s) fully **inside the yellow line** in the garage to **deliver** it. Delivery turns the alarm off, sets heat to 0, sends the cops away, and a new car appears somewhere in the city.
4. **Strip it.** Look at a part and hold E. Wheels take 2 s; hood, doors and bumpers 3 s; the engine 10 s.
   - You have **two hands**. Wheels, ECUs and bucket seats take one hand. Doors, hoods, bumpers, exhausts, gearboxes and stock seats take both.
   - **Engines are too heavy to carry.** Grab the **hand dolly** from its yellow box in the shop's north-east corner (E, with empty hands; it takes both). Take the hood off first, then push the dolly up to the engine bay and hold E for 10 s to strip the engine onto it. You can also tip a loose engine onto it (1 s), such as one from an exploded cop.
   - Pushing an empty dolly is a brisk walk. A loaded one is slow and tiring. **G** lets go. Getting busted, knocked flat or into a car also lets go, and the engine stays on the dolly for your partner. A dolly left outside the shop for 90 s finds its own way home.
   - When everything you can lift is gone, hold E to **crush the shell**. You get $150 plus 50% of any engine still in it.
5. **Sell** a part by holding E for half a second at the **$ SELL $** bench (engines sell off the dolly, at full price). Or **install** it on your own lime-green car by holding E for 1.5 s at the **TUNE-UP** bench. It goes into an empty slot or replaces a worse part, which drops on the floor. An engine from the dolly swaps in, and your old engine rides the dolly back out.
   - **Parts counter:** at TUNE-UP with empty hands you can **buy** the next part for your ride at 1.6× street value. It suggests missing parts first, then the best power per dollar you can afford (or the cheapest one to save for), then shiny tuned bits. No credit. Stealing is cheaper, but this is faster.
6. **Pay the rent.** A day lasts 3 minutes, from dawn to midnight, and the sky changes with it. At midnight the landlord takes the rent from the shared wallet: **$100 on day 1, then $75 more every day** ($175, $250, $325...). You get a summary of the day's haul. If cash stays below $0 for 2 minutes, you get **SHOP SEIZED** and a new run starts back on day 1. Your personal car **keeps its mods**.

### Crime

- **Punching:** empty hands, fists out (**1**), click. A pedestrian goes down for 3 s (+5 heat: people scream). A crewmate just falls over.
- **Robbing:** look at someone who's on the floor, or who has their hands up, and hold E for 0.8 s. Wallets hold $15-90 and refill after 3 minutes. +4 heat.
- **Hands up:** point a gun at someone within 10 m and they freeze with their hands up. Lower it and they run.
- **Black market:** five crates along the west wall of the shop. Look at one and hold E. Pistol $350 (24 rounds), shotgun $800 (10 shells, 7 pellets), ammo $60 (tops up the guns you own), spike strip $120, roadblock $200. You can carry five of each trap.
- **Guns** are hitscan. Shoot people (they go down for 5 s), **tyres** (a hit near a wheel knocks it clean off), and cop cars (8 hits and it burns, then explodes into loot). Every shot within earshot of a pedestrian or cop adds +8 heat; hitting a cop maxes it out. Getting busted **confiscates your guns**.
- **Traps:** select one (4 or 5) and click to put it down 3.5 m in front of you, square across the road.
  - **Spike strip:** shreds the tyres of anything that drives over it (three cars, then it's blunt). Traffic that loses two wheels stops, and the driver runs off and leaves the engine running.
  - **Roadblock:** a solid barrier the width of the road. Traffic stops in front of it and honks. Ram it at 11 m/s or more and it's matchsticks.
  - Traps get towed after 2.5 minutes. They blink just before.
- **Carjacking:** once traffic has stopped (roadblock, spikes, you standing in the road, a jam), walk up to it and hold E for 1.5 s. The driver gets dragged out and runs, and the car's yours (+12 heat). A driver who bails after a big crash leaves the engine running too: just get in (+10 heat, same as a break-in).

### The city

- **The soundtrack** is an original dark trap beat in the Memphis / phonk lane: sliding 808s, a clap on the three, rattling hi-hat rolls, a pitched cowbell and an eerie music-box bell. It's synthesized at startup (no audio files). The hats and cowbell kick in when you're on a job and hit harder when the heat's on. **M** toggles it.
- **Traffic:** eight cars drive the grid, keeping right. They slow for corners, stop and honk if you stand in the road, and swing around stalled cars. Give one a small bump and the driver sits there, stunned and honking. Hit one hard enough to throw people out (or shred two tyres) and the driver bails and runs, leaving the engine running: get in and it's yours, for +10 heat. Traffic drivers are *not* witnesses, and their horns don't confuse cops.
- **Pedestrians** run from cars coming at them faster than about 50 km/h (they dive sideways), from crashes and explosions, and from anywhere near a stolen car while the cops are rolling. Panicking doesn't stop them from being witnesses.

### Heat and cops

- Heat is shared and runs from 0 to 100. Witnesses raise it while they can see a wanted target: a cop adds +5/s, a pedestrian or angry owner +3/s, and a street camera +2/s (cameras only see stolen cars). Only the highest single rate counts; witnesses don't stack.
- Wanted targets are stolen cars that haven't been delivered, plus anyone on foot outside the shop while heat is above 0. Sitting in your own clean car hides you.
- Crimes add heat on the spot: punching someone +5, robbing +4, a gunshot within earshot +8, carjacking +12, shooting a cop straight to 100.
- If nobody sees you for 4 s, heat cools at 3/s. Parks and buildings block line of sight.
- At **100 heat**, up to two cop cars arrive from the edge of the map. If you stay on foot within 3.2 m of a cop car for 1 s, you're **BUSTED**. You drop whatever you're carrying (your partner can grab it) and sit in cuffs for 5 s.
- Ram a cop at more than 25 m/s relative speed and it catches fire, then explodes after 3 s. All its parts scatter as loot.

### Crashes

Damage is based on **how suddenly you stop** (delta-v), not on top speed:

- **6 m/s or more:** dents, plus a 35% chance that a panel flies off.
- **11 m/s or more:** everyone in the car gets thrown out and tumbles, and 1-3 parts fly off.
- **18.7 m/s or more:** wheels come off, and the car drags and pulls to one side.

Cars hitting people at more than 5 m/s send them tumbling.

---

## Hosting and joining

The host runs the authoritative simulation. Everyone else connects to the host's IP on **UDP port 27015**. Up to 4 players can join.

1. **Same network (LAN):** choose **HOST GAME**. The screen shows `LAN: 192.168.x.y:27015`. Friends choose **JOIN GAME** and type that IP.
2. **Over the internet with UPnP:** hosting automatically asks your router to forward UDP 27015. If the router agrees, the host screen shows `UPNP OK` and your **INTERNET** IP. Give friends that IP.
3. **UPnP failed?** The host screen says `UPNP FAILED - FORWARD UDP 27015 OR PLAY ON LAN`. Log into your router and forward **UDP 27015** to the host PC's LAN IP. Then friends join using your public IP (search "what is my IP").
   - Alternatively, use a virtual-LAN tool such as Tailscale, ZeroTier or Radmin VPN and join on that network's IP.
4. **Windows Firewall:** the first time you host, Windows asks whether *Chopped* (or *Python*) may communicate on networks. Click **Allow**, and tick **Private** networks at least. If you clicked Cancel by mistake, go to *Windows Security → Firewall & network protection → Allow an app through firewall* and enable it.

Other details:

- Press Esc while hosting to see your IP and the player count. If the PC is also on a VPN (Tailscale, ZeroTier, Radmin, work VPN), those addresses are listed too.
- If no packets arrive for 10 s, the connection drops. A host that quits tells its clients.
- A different port works too: host with `--port 28000` and have friends join `IP:28000`.

---

## Building a standalone executable

The easy way is to let GitHub Actions do it (see [Getting `Chopped.exe`](#getting-choppedexe-no-python-needed)). All three routes use the same recipe:

1. `python tools/make_icon.py` draws the icon from the game's own sprite code and writes the Windows version resource into `build/gen/`. Nothing is committed.
2. `python -m PyInstaller --noconfirm --clean Chopped.spec` builds a one-file exe with no console window. UPX is off, because packed exes attract antivirus false positives.
3. `python tools/smoke_exe.py dist/Chopped.exe` runs a headless selftest, then a host exe plus a client exe over UDP. The logs go to `dist/smoke-logs/`.

### Windows, on your own PC (`dist\Chopped.exe`)

Requires Python 3.12 from python.org, which provides the `py` launcher.

```bat
build_windows.bat
```

It creates `.venv`, installs `requirements.txt` plus `pyinstaller==6.22.3`, and runs the three steps above. If `miniupnpc` won't install, it builds without UPnP.

### Linux (`dist/Chopped`)

```bash
./build_linux.sh
```

---

## Tests

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v
```

- `tests/test_sim.py` covers the pure simulation:
  - the full loop: steal, drive into the garage, deliver, strip, sell, tune-up, rent, SHOP SEIZED and reset (personal mods kept)
  - heat from witnesses, cooling, no stacking, cameras seeing only cars
  - cop spawning and despawning, arrests, horn donuts, ramming a cop until it explodes
  - crash delta-v thresholds, dolly-only engines and crushing, stamina, clowns and owners
- `tests/test_net.py` runs a real threaded host and two clients over 127.0.0.1 UDP. Both clients must agree on positions, cash and heat. It also checks reliable toasts, packet size under 1200 bytes, graceful leave, silent timeout, full server and version reject, and host shutdown.
- `tests/test_gameloop.py` runs two real game processes (host plus a client that joins it) on the dummy video driver for about 20 s with bot input.
- `tests/test_misc.py` checks UPnP when `miniupnpc` is missing, address parsing, a worst-case snapshot size (including rush-hour traffic), and part values.
- `tests/test_physics.py` covers box collisions: square corners, flush hits that don't spin you, scraping along a building without snagging, T-bones, and people vs cars.
- `tests/test_predict.py` covers client-side prediction:
  - With 100 ms of lag each way, the predicted car and avatar match the host to within about 0.01 mm, tick for tick, including wall contact, stamina and pushing a loaded dolly.
  - Misses are smoothed, not snapped.
  - Over real UDP with 120 ms ping and jitter, your avatar moves before the host has heard, then converges.
- `tests/test_traffic.py` covers traffic that stays on the road, keeps right, stops, honks and bails, and pedestrians who flee.
- `tests/test_dolly.py` covers the dolly (strip, load, sell, swap, speeds, letting go, coming home) and the parts counter.
- `tests/test_combat.py` covers v0.6 crime: punch and rob, hands up, buying at the black market, shooting people, tyres and cop cars, empty clicks, confiscation on arrest, spike strips making traffic bail, roadblocks stopping traffic, carjacking, ramming a roadblock, and the new protocol fields (arsenal, traps, shot events) within the packet budget.
- `tests/test_music.py` checks that the beat's two layers loop seamlessly, aren't silent or clipping, and hit on the one.

---

## Code map

```
main.py              entry point / CLI (--host --join --server --selftest ...)
chopped/config.py    EVERY tuning number, with comments explaining why
chopped/parts.py     part catalogue, slots, loadouts
chopped/mapgen.py    deterministic procedural city (seeded; clients rebuild it locally)
chopped/sim.py       authoritative world: physics (shared Physics class), crashes, heat, cops,
                     traffic, pedestrians, the dolly, fists/guns/traps/carjacking, economy (no pygame)
chopped/predict.py   client-side prediction: runs sim.Physics on your own car/avatar, reconciles
chopped/protocol.py  packet formats; struct + zlib snapshots, distance culling, prediction block
chopped/net.py       UDP Server (60 Hz sim, 20 Hz snapshots) and Client (60 Hz input, prediction,
                     100 ms interpolation for everyone else, --fake-lag)
chopped/upnp.py      optional miniupnpc port mapping (runs in a background thread)
chopped/art.py       palette, 3x5 pixel font, procedural sprites, pre-rendered city
chopped/render.py    top-down renderer (the Tab automap), particles, skid marks, camera
chopped/ui.py        main menu
chopped/audio.py     procedural square-wave sfx and loops (silently disabled if there's no audio device)
chopped/fp.py        first-person raycaster: textured walls, mode-7 street floor, sky, sprites
chopped/fpart.py     first-person art: facades, skies, box-model cars/people rendered from 16/8 angles
chopped/doomhud.py   status bar, face, messages, first-person hands / dolly / dashboard overlays
chopped/music.py     the procedural beat (pure Python, rendered once at startup)
chopped/game.py      pygame app loop, host/join flow, mouse look, selftest bot
tools/make_icon.py   build-time icon + Windows version resource (from the sprite code)
tools/smoke_exe.py   tests a BUILT exe: selftest + host/client over UDP
.github/workflows/build.yml   tests on Windows + Linux, builds and smoke-tests Chopped.exe
```

### Netcode notes

- **Clients send inputs, not positions.** One input goes out per 60 Hz sim tick. One-shot keys (E, G, F) are sent as counters, so a quick tap still registers if a packet is lost.
- **Your own car or avatar is predicted.** Each client runs the host's exact physics (`sim.Physics`) on its own entity the moment you press a key. Each snapshot says which of your inputs the host has applied, and gives your full-precision physics state. The client rewinds to that, replays the inputs the host hasn't seen yet, and smooths out any leftover miss over about 80 ms. A miss usually means a cop or car the host knew about and you didn't. Tumbling, cuffed or riding shotgun fall back to plain extrapolation.
- **The server sends each client its own snapshot** at 20 Hz. Each one is zlib-compressed and usually 200-800 bytes. Pedestrians, loose parts and traffic farther than 95 m from that player are left out. Stealable cars are always sent.
- **One-off events are delivered reliably.** Toasts and sound events repeat until the client acknowledges their sequence number.
- **The host sees no lag.** The host's own window is a loopback client that receives every server tick.

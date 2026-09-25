# Chopped

A chaotic co-op car-theft chop-shop game for 1-4 players online. Top-down
pixel art, GTA 2 energy, and a heist that's always one pedestrian away from
going wrong.

Steal cars, drive them into your shop, strip them for parts, sell the parts,
and pay the rent. If you fall behind on rent, the landlord takes the shop.

- Pure Python 3.12 + pygame-ce. **No asset files**: every sprite, tile, font glyph and sound is generated when the game starts.
- Host-authoritative networking over plain stdlib UDP (no networking library).
- Optional UPnP port forwarding via `miniupnpc`. The game works fine without it.

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

---

## Controls

| Key | On foot | In a car |
|---|---|---|
| **W A S D** / arrows | Move | Throttle / brake-reverse / steer |
| **Shift** | Sprint (uses stamina) | – |
| **E** | Interact. **Hold** it for timed actions; a progress bar appears | – |
| **G** | Drop the part you're holding | – |
| **F** | – | Get out |
| **Space** | – | Handbrake (break traction and drift) |
| **H** | – | Horn. Cops within 40 m spin donuts for 3 s |
| **Esc** | Pause overlay: players, host IP, ping. **Q** leaves | |
| **F11** | Toggle fullscreen | |

---

## How to play

1. **Find a car.** Parked civilian cars show as white dots on the minimap (bottom right). There are always up to four in the city.
2. **Break in** by holding E at the car for 8 s. This sets off the alarm and adds **+10 heat**. Then **hotwire** it by holding E for 6 s, and you're the driver. A friend can press E to **ride shotgun**.
   - 12% of cars are **clown cars**. 15% have an **angry owner** who chases you and counts as a witness.
3. **Drive it home.** A blinking arrow on the screen edge points to the shop. Stop the car (under 4 m/s) fully **inside the yellow line** in the garage to **deliver** it. Delivery turns the alarm off, sets heat to 0, sends the cops away, and a new car appears somewhere in the city.
4. **Strip it.** Stand next to a part and hold E. Wheels take 4 s; hood, doors and bumpers 6 s; the engine 20 s.
   - You have **two hands**. Wheels, ECUs and bucket seats take one hand. Doors, hoods, bumpers, exhausts, gearboxes and stock seats take both.
   - **Engines are dolly-only**: you can't lift them. When everything else is gone, hold E to **crush the shell**. You get $150 plus 50% of whatever dolly-only parts are left.
5. **Sell** a part by holding E for 1 s at the **$ SELL $** bench. Or **install** it on your own lime-green car by holding E for 3 s at the **TUNE-UP** bench. It goes into an empty slot or replaces a worse part, which drops on the floor.
6. **Pay the rent.** $150 is taken every 60 s from the shared wallet. If cash stays below $0 for 2 minutes, you get **SHOP SEIZED** and a new run starts. Your personal car **keeps its mods**.

### Heat and cops

- Heat is shared and runs from 0 to 100. Witnesses raise it while they can see a wanted target: a cop adds +5/s, a pedestrian or angry owner +3/s, and a street camera +2/s (cameras only see stolen cars). Only the highest single rate counts; witnesses don't stack.
- Wanted targets are stolen cars that haven't been delivered, plus anyone on foot outside the shop while heat is above 0. Sitting in your own clean car hides you.
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

- Press Esc while hosting to see your IP and the player count.
- If no packets arrive for 10 s, the connection drops. A host that quits tells its clients.
- A different port works too: host with `--port 28000` and have friends join `IP:28000`.

---

## Building a standalone executable

### Windows (`dist\Chopped.exe`)

Requires Python 3.12 from python.org, which provides the `py` launcher.

```bat
build_windows.bat
```

The script:

1. Creates `.venv` with `py -3.12`.
2. Installs `requirements.txt` plus `pyinstaller==6.22.3`. If `miniupnpc` won't install, it falls back to building without UPnP.
3. Runs:
   ```
   pyinstaller --onefile --windowed --name Chopped --hidden-import miniupnpc --collect-submodules chopped main.py
   ```
4. Runs `dist\Chopped.exe --selftest` to prove the exe boots.

### Linux (`dist/Chopped`)

```bash
./build_linux.sh
```

This uses the same PyInstaller flags and runs a headless selftest at the end.

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
- `tests/test_misc.py` checks UPnP when `miniupnpc` is missing, address parsing, a worst-case snapshot size, and part values.

---

## Code map

```
main.py              entry point / CLI (--host --join --server --selftest ...)
chopped/config.py    EVERY tuning number, with comments explaining why
chopped/parts.py     part catalogue, slots, loadouts
chopped/mapgen.py    deterministic procedural city (seeded; clients rebuild it locally)
chopped/sim.py       authoritative world: physics, crashes, heat, cops, economy (no pygame)
chopped/protocol.py  packet formats; struct + zlib snapshots, distance culling
chopped/net.py       UDP Server (60 Hz sim, 20 Hz snapshots) and Client (30 Hz input, 100 ms interpolation)
chopped/upnp.py      optional miniupnpc port mapping (runs in a background thread)
chopped/art.py       palette, 3x5 pixel font, procedural sprites, pre-rendered city
chopped/render.py    world renderer, particles, skid marks, camera
chopped/ui.py        HUD, menu, pause overlay
chopped/audio.py     procedural square-wave sfx and loops (silently disabled if there's no audio device)
chopped/game.py      pygame app loop, host/join flow, selftest bot
```

### Netcode notes

- **Clients send inputs, not positions.** Held buttons go out about 30 times a second. One-shot keys (E, G, F) are sent as counters, so a quick tap still registers if a packet is lost.
- **The server sends each client its own snapshot** at 20 Hz. Each one is zlib-compressed and usually 200-800 bytes. Pedestrians and loose parts farther than 95 m from that player are left out.
- **One-off events are delivered reliably.** Toasts and sound events repeat until the client acknowledges their sequence number.
- **The host sees no lag.** The host's own window is a loopback client that receives every server tick.

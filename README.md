# Chopped

A chaotic co-op car-theft chop-shop game for 1-4 players online. First-person
pixel art with Doom energy (plus a top-down automap), and a heist that's
always one pedestrian away from going wrong. The soundtrack is a dark
Memphis-style trap beat, synthesized by the game itself.

Steal cars (or drag drivers out of them, or cut the wires under the dash and
sneak in without the alarm), drive them into your own bay, strip them for
parts, sell the parts, and pay the rent. Or bolt the good bits onto your own
ride in a GTA-style mod shop. Punch people (some punch back), shoot them
(some of them don't get back up), rob people, buy guns, spike strips and
banana peels off the crates in the back of the shop, throw car doors at
pedestrians, pick your mate up and bowl him into a bus queue. Get caught on
foot and an officer cuffs you and throws you in a cell at the precinct, and
you'll have to pick or punch your way out of it and then past the guards --
or shoot your way out, if it's come to that; the ambulance will be along
shortly. Size a car up before you nick it, sell it whole if you can't be
bothered with spanners, and roll your bay's door down when the cops come
knocking. Drift a supercharged V8, do donuts in a 4x4, listen to a rice
rocket's VTEC kick in, hit a stunt ramp, hide in a cardboard box, watch for
the chopper once things get hot enough. If you fall behind on rent, the
landlord takes the shop.

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

To get a public download link, push a version tag (`git tag v0.8.0 && git push origin v0.8.0`). The workflow then publishes `Chopped.exe` as a **GitHub Release**.

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
| `python main.py --host --save crew.json` | Host with persistence: loads `crew.json` if it exists, saves to it every 30 s and on a clean exit (normally you'd just pick a **SAVE SLOT** on the main menu instead, v0.12.1) |
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
| **Mouse** / **arrows** | Look around, up and down too | Look around (in chase cam: swing the camera round) |
| **W S** / **up down** | Forward / back | Throttle / brake-reverse. **Both at once: burnout** (brake stand; steer for donuts) |
| **A D** | Strafe | Steer |
| **Space** | Jump (clear a roadblock, if you tuck your knees) | Handbrake: lock the rear wheels and drift |
| **Shift** | Sprint (uses stamina) | NOS boost, if your ride has it fitted |
| **E** | Use whatever you're looking at. **Hold** it for timed actions; a progress bar appears. At your bay's roller door, or the walking door: open or shut it | - |
| **X** | The prompt's other option: **cut the wires instead of smashing the window** (a locked car), **sell a delivered car whole**, **post bail** from your cell | Hydraulic hop, if your ride has hydraulics fitted |
| **C** | Get into (or out of) your **cardboard box**, if you bought one | - |
| **Left click** / **Ctrl** | Punch, shoot or place a trap. **With something in your hands: throw it.** Hold the click with empty fists, then let go: **haymaker** | - |
| **1-9**, **mouse wheel**, **Q** | Fists, pistol, shotgun, spike strip, roadblock, banana peel, box of donuts, rubber chicken, whoopee cushion (whatever you own) | - |
| **Mouse wheel**, **Q** only | Five more guns past the number row: **SMG, assault rifle, sniper rifle, grenade launcher, RPG** (v0.12) | - |
| **G** | Drop the part you're holding / let go of the dolly / **pick up a person** (then click to throw them, G to put them down) | - |
| **T** | Dance. Everyone nearby has an opinion | - |
| **F** | - | Get out. At speed, with an ejector seat fitted: up through the roof |
| **H** | - | Horn. Cops within 40 m spin donuts for 3 s. Near the shop, it's the **garage remote**: your nearest door opens (or shuts) |
| **V** | - | Cockpit / 3rd-person chase camera |
| **Tab** | Automap: the top-down view of the city | |
| **M** | Music on/off | |
| **F9** | Big head mode (just for you) | |
| **F5** | Save now (host only; see [Save files](#save-files)) (v0.12.1) | |
| **F8** | Fisheye lens: a wider, wobblier FOV, like a cheap dashcam (v0.12) | |
| **F10** | Disco floor: a hue-cycling tint on the street under your feet (v0.12) | |
| **Esc** | Pause menu: players, host IP, ping, and three buttons (click them, or use the keys): **RESUME** (Esc), **INSTRUCTIONS** (I: the full controls list, in its own window, v0.13) and **LEAVE TO MENU** (Q). Releases the mouse | |
| **Enter** | Skip to the next line of dialogue (v0.13) | |
| **F11** | Toggle fullscreen | |

Being carried by a crewmate, or being cuffed by an officer? Mash **Space** to wriggle free.

The status bar reads, left to right: **ARMS** (the weapons you own, 1-9), **CASH**, **HEAT %**, **HANDS** (the dolly, or your ammo when a gun is out), your crook's **face** (it sweats as the heat rises, grins when money comes in, and sees stars when you get run over), **STAMINA %** (**KM/H** in a car), **COPS** (it reads **LETHAL** while the police are shooting to kill), **DAY / RENT**, and **GEAR** (traps in your pocket; in a car, or on foot at its bumper, the trunk contents and the NOS gauge). The radar (bigger now, v0.12) is top right, and every teammate shows on it as an outlined dot in their own colour; if one's too far off to see, small coloured lines name them and point the way. Under the radar: today's 3 jobs and your crew's reputation and act (see [Jobs and the story](#jobs-and-the-story)). When you're carrying loot, a **SHOP** marker at the top of the screen points home; when you're empty-handed, a green **CAR TO STEAL** marker points at the nearest parked car. Look at a car for half a second and an **inspect card** slides in on the right (see below). Hold a slide and the **DRIFT** meter counts it up. In a car, the dashboard has a **tachometer** next to the speedo: revs, redline, the gear you're in, and a boost gauge if there's a turbo (blue) or a supercharger (gold) under the bonnet. Hop in your cardboard box and a line above the bar tells you whether you're actually hidden yet or still an obvious box with legs.

---

## How to play

1. **Find a car.** Parked civilian cars show as white dots on the radar and have a **green arrow** floating over them; follow the green **CAR TO STEAL** marker at the top of the screen to the nearest one. There are up to six in the city. Traffic that's stopped gets an **orange arrow**: you can carjack it (see [Crime](#crime)).
   - **Size it up first (v0.9).** Look at any car within 12 m (parked or in traffic) for half a second and an inspect card comes up: the model, what's under the bonnet, the gearbox, a tuned ECU if it has one, its three best bits (gold mesh wheels, a carbon hood...), how rough it is (SCRAP to MINT), and roughly what it's worth in parts. It also tells you if **something rattles in the boot**, if the boot is... **honking** (a clown car), or if **someone's watching it from a window** (the angry owner).
2. **Break in** by looking at the car and holding E for 4 s. This sets off the alarm and adds **+10 heat**. Or press **X first** to switch to the slow way: **hold E to cut the wires** (6 s). Guess the right one (1 in 4) and you're in without a sound -- no alarm, no heat, and a car with an angry owner never notices. Guess wrong and it's louder and costs more heat than just smashing the window would have. Then **hotwire** it by holding E for 3 s, and you're the driver. A friend can press E to **ride shotgun**.
   - 12% of cars are **clown cars** (they burst open no matter how quietly you got in -- that's the joke). 15% have an **angry owner** who chases you and counts as a witness, if they heard you.
3. **Drive it home.** Follow the SHOP marker. Press **V** for the chase camera if you want to see yourself drift. Stop the car (under 4 m/s) fully **inside the yellow line** in your bay to **deliver** it. Delivery turns the alarm off, sets heat to 0, sends the cops away, and a new car appears somewhere in the city.
4. **Strip it.** Look at a part and hold E. Wheels take 2 s; hood, doors and bumpers 3 s; the engine 10 s.
   - You have **two hands**. Wheels, ECUs and bucket seats take one hand. Doors, hoods, bumpers, exhausts, gearboxes and stock seats take both.
   - **Engines are too heavy to carry.** Grab the **hand dolly** from its yellow box in the shop's north-east corner (E, with empty hands; it takes both). Take the hood off first, then push the dolly up to the engine bay and hold E for 10 s to strip the engine onto it. You can also tip a loose engine onto it (1 s), such as one from an exploded cop.
   - Pushing an empty dolly is a brisk walk. A loaded one is slow and tiring. **G** lets go. Getting busted, knocked flat or into a car also lets go, and the engine stays on the dolly for your partner. A dolly left outside the shop for 90 s finds its own way home.
   - When everything you can lift is gone, hold E to **crush the shell**. You get $150 plus 50% of any engine still in it.
   - **Or sell it whole (v0.9): press X** at a delivered car. A man called Dave pays 70% of what the parts would fetch one at a time, plus the $150 shell, no spanners needed (the engine included, so no dolly either). A **complete** sports car, muscle car or rice rocket fetches a $400 collector's bonus on top, and a complete 4x4 $250. Whatever's in the boot stays with you.
   - **Check the trunk.** Look at the back of your ride, or of any car you've broken into, and press E. Stolen cars sometimes have loot in the back: a bag of cash, a mystery briefcase, a giant rubber duck, a gnome. Trunks also hold your parts on the way home (a Kei takes 3 hands' worth, a box van 10). Pickups and vans have a **bed**: push the loaded dolly up to it and hold E to load the engine.
5. **Sell** a part by holding E for half a second at the **$ SELL $** bench (engines sell off the dolly, at full price). Or take it to the **mod shop** (below).

6. **Mind the doors.** The shop has a roof, and a **roller door for every player's own bay**, plus a separate **walking door** so you're not forever opening a whole bay just to nip out on foot. Each one is independent: E at any door (inside or out) rolls that one down; honk near the shop and the remote on your sun visor does the nearest bay for you. Shut, a door stops cop cars and officers, and nobody can see you through it. It stops you too, so open your bay before you come home at 80 km/h. None of them come down on anything: there's a safety sensor, and it beeps. Everyone's bay has to actually be sealed -- doors down, whole crew and whatever they're driving inside -- for the shop to count as a genuine hideout: heat drops to 0 the moment it is, same as a delivery, and comes right back the moment someone pokes a wheel out.

7. **Pay the rent.** A day lasts 3 minutes, from dawn to midnight, and the sky changes with it. At midnight the landlord takes the rent from the shared wallet. **(v0.12)** rent is flat now, not steeper every day: **$100/day for the home base**, and it only goes up if you buy another shop (see [Shops](#shops) below). You get a summary of the day's haul. If cash stays below $0 for 2 minutes, you get **SHOP SEIZED** and a new run starts back on day 1. Your personal car **keeps its mods** (any fences you bought don't survive the seizure).

### The mod shop

Look at the **TUNE-UP** bench and press E. Whatever you're holding (and the engine on your dolly) goes into the crew's **locker**, and a GTA-style garage menu opens over your lime-green ride:

- **Categories** down the left: every part slot (engine, gearbox, ECU, exhaust, wheels, doors, hood, bumpers, seats, spoiler), then **paint**, **livery**, **horn**, **underglow**, **extras**, **switch car** and the **locker** itself.
- **Switch car:** every player gets their own bay and their own personal ride now. Delivered a nicer car than the one you drive? Pick **SWITCH CAR** and hand your old ride over to the crew (it becomes an ordinary civilian car, up for anyone to steal or strip) in exchange for the one you're standing next to.
- **Fit** a part from the locker, **buy** one new (1.6x street value, condition 100%, every style), **remove** one (it goes to the locker), **sell** straight from the locker, or **take** one back into your hands.
- A rotating preview shows the car with your changes, and bars show **power, top speed, acceleration, grip and weight**. Bigger wheels and a spoiler really do grip harder; a heavier engine really is heavier.
- **Paint** $150 (16 colours). **Liveries** $250: racing stripes, two-tone, flames, checkers, polka dots, camo, taxi, pastel, lightning. **Horns**: stock, clown, La Cucaracha, wet fart, goat, air horn, ice cream jingle (hover one to hear it). **Underglow** $300. **Extras:** NOS $900, ejector seat $600, a hood gnome $80 (free if you bring your own gnome), hydraulics $500.
- **W/S**, the arrows or the mouse wheel move. **Enter** or **E** picks; with the mouse, click a row to highlight it and click it again to buy or fit it. **A**, **Backspace** or right click goes back a level; **Esc** leaves. In **LIVERY**, A/D picks the second colour. In the **LOCKER**, Enter sells and **X** takes the part out.
- The locker holds 40 parts; overflow gets shoved out onto the floor by the bench. **SHOP SEIZED** empties it. The car keeps its mods.

### Shops

**(v0.12, Bryce: "make multiple garages, make them available for purchase")** The home base is Shop 1, and its black market only carries the basics: the pistol, ammo, spike strips and roadblocks. Three more shops sit elsewhere in the city -- open lots with a "BUY THIS SHOP" sign and a locked market stall. Walk up and hold E to buy one:

| Shop | Price | Rent/day | Adds to the market |
|---|---|---|---|
| 1 (home base) | free | $100 | Pistol, ammo, spikes, roadblocks |
| 2 | $4,000 | +$150 | Shotgun, banana peels, donuts |
| 3 | $12,000 | +$250 | SMG, assault rifle, rubber chicken, whoopee cushion, cardboard box |
| 4 | $30,000 | +$400 | Sniper rifle, grenade launcher, RPG |

Buying a shop is permanent (until SHOP SEIZED) and its crates work exactly like the home shop's: look at one and hold E. There are no bays or roller doors at a fence shop -- just the market. Rent is billed once, at midnight, for every shop you own added together.

### Vehicles and styles

Twelve kinds of vehicle turn up, parked and in traffic, each with its own size, weight, grip, top speed and trunk (bikes and the mobility scooter are only ever parked):

| Vehicle | Feel | Trunk |
|---|---|---|
| Kei hatch | The baseline. Your ride is one | 3 |
| Sedan | A bit bigger, a bit faster | 5 |
| Sports coupe | Fastest, grippiest, tail-happy | 2 |
| Muscle car | Huge power, rear-drive: it will slide | 4 |
| Pickup | Heavy; has a bed for engines | 8 |
| Box van | Slow, front-drive, carries everything | 10 |
| Ice cream van | Plays its jingle. Pedestrians queue for it (and stop witnessing) | 6 |
| Mobility scooter | 12 m/s flat out. Steal it anyway | 1 |
| Rice rocket | Slammed, stickered, a wing taller than the roof, a fart-can exhaust. Pops and bangs. Often genuinely quick | 2 |
| 4x4 truck | Lifted, all-wheel drive, a diesel. Parks are just shortcuts to it. Can't do a brake stand | 8 |
| **Sports bike** (v0.13) | 56 m/s flat out -- faster than the cops (48) -- and off the line like a startled cat. You fall off at 6 m/s of impact where a car would shrug it off | 1 |
| **Dirt bike** (v0.13) | Slower, but grass is just more road | 1 |

Every part rolls a **style**: gold mesh, spinner or sawblade wheels, scoop, flame, carbon, shark-mouth or blower hoods, bull bars, quad exhausts, race-number doors, rainbow spoilers. Styles show on the car, in the part's name, and in its price (gold mesh sells for 1.6x a steelie). About 30% of cars wear a livery, and 6% of parked cars have underglow. That's the point: find a car with a part you want, strip it, and fit it to yours.

### Engines

Every engine has its own voice, synthesized at startup: each one is rendered at six points across its rev range and the game crossfades between them as the needle moves, so revving sounds like revving.

| Engine | Sound | Found in |
|---|---|---|
| 1.0 / 1.6 four | Buzzy | Keis, sedans, vans |
| 2.0 turbo | Muffled four + turbo whistle and a **pssh** when you lift | Coupes, rice |
| 1.6 supercharged | Four with a **supercharger whine** that rises with the revs | Keis, sedans, rice |
| 1.8 VTEC | Screams to 8,600. Changes its whole personality at 5,500: **VTEC JUST KICKED IN, YO** | Rice, coupes |
| 13B rotary | **Brap brap** | Coupes, rice |
| 3.0 V6 | Smooth, slightly uneven | Sedans, cops, pickups |
| 5.7 V8 | Burble (a cross-plane V8 doesn't fire evenly) | Muscle cars, pickups, 4x4s |
| 6.2 supercharged V8 | Burble + blower whine. The most powerful thing in the city | Muscle cars, 4x4s |
| 3.0 twin-turbo six | Silky, with the big-turbo **stututu** flutter | Coupes, sedans |
| 4.5 turbo diesel | Clattery tractor | 4x4s, vans, ice cream vans |
| Scooter motor | An electric whine. Terrifying at 12 m/s | The scooter |

Cars with a tuned ECU or exhaust (and every rice rocket) **pop and bang** on the overrun, with flames out of the exhaust, and do a **two-step** brap on a brake stand. Tyres **screech** when they're sliding, spinning or locked.

### Driving and drifting

The cars run on a tyre model now, not a rail:

- Grip builds with slip angle, peaks and then falls off, so a car that breaks away slides until you catch it.
- Braking, accelerating and cornering share one grip budget. Stamp on the throttle mid-corner in a rear-drive car and the tail steps out; in a front-drive van it just pushes wide.
- The weight shifts: lift off in a corner and the nose tucks in.
- **Space** locks the rear wheels: yank it to swing the tail round. It can't spin you like a top: the handbrake is for starting a slide, not ending the run.
- The front wheels self-centre. Let go of the steering mid-slide and the car straightens itself. **Countersteer** and the wheels point exactly where the car's going (a keyboard's full lock would overcook it), so a slide is caught, not turned into a tank-slapper.
- **Drift assist (v0.8):** past about 14 degrees of slide the car is nudged back toward where it's going, and any rotation that would make the slide worse (or snap it back the other way) is bled off. Steer *into* the slide and the help partly steps aside, so you can hold a big angle for as long as your nerve lasts.
- **Tighter (v0.9):** the rears don't let go as easily, the handbrake doesn't spin the car as fast, and the assist pulls harder. A handbrake flick and a quick countersteer now tops out around 30-35 degrees (it was about 40) and is back in line in about half a second; holding a slide on purpose settles around 45 degrees (it was 60-70).
- **Brake stands:** W and S together at a standstill. The brakes hold one axle and the driven wheels spin up into a cloud; steer and you do **donuts**. Keep it up and the smoke gets thick enough to hide in (see below). Front-drive cars do it backwards. All-wheel-drive 4x4s can't do it at all.
- The **DRIFT** meter scores every slide over 14 degrees and 8 m/s.

### Crime

- **Punching:** empty hands, fists out (**1**), click. A pedestrian goes down for 3 s (+5 heat: people scream). A crewmate just falls over. Hold the click for 0.7 s and let go for a **haymaker** that sends them into orbit.
- **People fight back now.** About a third of pedestrians are brave: hit one (or one of their friends nearby) and they come at you swinging, and bystanders pile in. A punch from them puts you on the floor and empties your hands. About one in ten carries a pistol and will use it from 22 m. They take three knockdowns before they've had enough, give up if you outrun them by 45 m, and forget after 25 s. Rob a brave one and they come after you: if they land a punch, they take their money back out of the crew's cash. Half of all carjacked drivers come back for their car.
- **Robbing:** look at someone who's on the floor, or who has their hands up, and hold E for 0.8 s. Wallets hold $15-90 and refill after 3 minutes. +4 heat.
- **Hands up:** point a gun at someone within 10 m and they freeze with their hands up. Lower it and they run.
- **Black market:** crates at each shop you own (see [Shops](#shops)). Look at one and hold E. Pistol $350 (24 rounds), shotgun $800 (10 shells, 7 pellets), ammo $60 (tops up every gun you own), spike strip $120, roadblock $200, banana peel $40, box of donuts $30, a rubber chicken $25, a whoopee cushion $15, a cardboard box $40, and (v0.12) **SMG** $1,400 (45 rounds), **assault rifle** $2,400 (30), **sniper rifle** $3,200 (5), **grenade launcher** $2,800 (4) and **RPG** $5,500 (2 rockets). Scratch tickets are $20 everywhere, even Shop 1 -- mostly nothing, sometimes a few bucks, rarely a $500 jackpot. You can carry five of each trap.
- **Guns** are hitscan -- even the launchers, which land where you're looking and blow up on arrival rather than lobbing a real projectile. Shoot a **pedestrian, an owner, an officer or a guard and they're dead**, not knocked down: it's the quiet way to lose a witness, but it's still murder (+18 heat, on your rap sheet forever, and an ambulance comes for the body). Cops and the law shoot back hard once you've gone that far. Shoot **tyres** (a hit near a wheel knocks it clean off), and cop cars (8 hits and it burns, then explodes into loot). The **grenade launcher and RPG** catch everyone and everything within their blast radius, not just whatever's dead centre -- mind the splash. Every shot within earshot of a pedestrian or cop adds +8 heat; hitting a cop maxes it out. **Any shot the police can hear makes them shoot back, for real** (see [Heat and cops](#heat-and-cops)). Getting busted **confiscates your guns** (dying doesn't).
- **A witness doesn't tell the cops straight away.** A pedestrian or angry owner who clocks you doesn't add heat on the spot any more -- they bolt, and phone it in 10-15 seconds later, a flat **+15 heat** when the call lands. Kill them (or knock them out of the picture some other way) before then and the call never happens. They don't need to keep watching you once they've decided to call, so ducking out of sight isn't enough on its own.
- **Traps:** select one (4-7, 9) and click. Spike strips and roadblocks go down 3.5 m in front of you, square across the road. (v0.9 fixed a bug that had been there since v0.7: keys 6 and 7 used to give you your fists instead of the banana and the donuts.)
  - **Spike strip:** shreds the tyres of anything that drives over it (three cars, then it's blunt). Traffic that loses two wheels stops, and the driver runs off and leaves the engine running.
  - **Roadblock:** a solid barrier the width of the road. Traffic stops in front of it and honks. Ram it at 11 m/s or more and it's matchsticks.
  - **Banana peel:** dropped 2 m ahead. A car that finds it spins out; a person who steps on it goes flat on their back.
  - **Box of donuts:** thrown up to 12 m. The two nearest cops within 35 m pull over and eat for 8 s, seeing nothing. NOM NOM.
  - Traps get towed after 2.5 minutes. They blink just before.
- **Carjacking:** once traffic has stopped (roadblock, spikes, you standing in the road, a jam), walk up to it and hold E for 1.5 s. The driver gets dragged out and runs, and the car's yours (+12 heat). A driver who bails after a big crash leaves the engine running too: just get in (+10 heat, same as a break-in).

### Ridiculous stuff

- **Throw things.** Click with a part in your hands and it flies. A wheel or a car door to the head knocks a pedestrian out (a two-hander keeps them down longer). Parts lose a bit of condition each bonk.
- **Pick people up** (G) and **throw them** (click). A thrown person knocks down everyone they land among: three at once is a **STRIKE!** A carried pedestrian wriggles free after 7 s; a carried crewmate mashes Space to escape.
- **Haymaker:** see above. **HOME RUN!**
- **Ejector seat:** buy one in the mod shop, then press F above 12 m/s. You go 6 m straight up, the parachute opens, and the car carries on without you.
- **Joke horns:** clown, La Cucaracha, wet fart, goat, air horn, ice cream jingle.
- **NOS:** Shift in a car that has it. 4 s of rocket, refills in 16 s.
- **Donuts** and **banana peels:** see the black market.
- **Big head mode:** F9.
- **Dance:** T. Pedestrians within 14 m either laugh (they stand there for 4 s; rob them, pick them up) or take it personally (the brave ones). Cops who see it are not amused.
- **Garden gnomes:** twelve of them stand guard on the city's lawns. Pinching one is +3 heat (it's the principle of the thing). Sell it for $60, or fit it to your hood.
- **Ice cream van:** drive one slowly and pedestrians queue up for it. People in a queue don't witness crimes.
- **The mobility scooter.**
- Get hit by a car doing more than 15 m/s and you're **YEETED** into the air. Other banners: **HUMBLED** (a pedestrian beat you up, or a banana did), **BONKED**, **STRIKE!**, **HOME RUN!**, **EJECTED**, **TASED**, **PANTSED**, **BUSTED**, **JAILBREAK!**, **SMILE!**, **WASTED**.
- **v0.12's additions:**
  - **Scratch tickets.** $20 at any black market crate. Mostly nothing, sometimes a few bucks, once in a while a $500 jackpot. The house always wins on average -- that's the joke.
  - **Some pedestrians are quietly loaded.** About 1 in 50 wallets carries $400-900 instead of the usual $15-90. No way to tell which one from the outside.
  - **Loose change in the seats.** About 1 in 5 stolen cars has a few dollars down the seats, found the moment you hotwire it.
  - **The tip jar.** Selling a part at the bench, about 1 in 7 passersby chips in a few extra dollars for the show.
  - **High fives.** Two crewmates dancing (T) within arm's reach of each other sync up for a shared stamina bonus.
  - **Local celebrity.** Enough speed camera tickets and the local news takes an interest. Purely a toast -- no actual news van shows up. Yet.
  - **Honk at the ice cream van** and it honks back. It will not play its jingle for you.
  - **A confetti puff** goes off the instant your NOS kicks in.
  - **Fisheye lens (F8)** and **disco floor (F10)** -- see [Controls](#controls).
- **v0.10's additions:**
  - **The ambulance.** Kill a member of the law and it's sent for the body, siren and all -- and every cop in the city is now shooting to kill.
  - **The chopper.** Once heat's high enough, a helicopter joins the hunt. Walls stop it seeing you; being outdoors doesn't.
  - **Cutting the wires.** X at a locked car offers the slow, quiet way in instead of smashing the window -- see [How to play](#how-to-play).
  - **A popped trunk swings open** for a moment when you (or anyone) starts looking through one, and what's inside now shows in the GEAR panel on foot too, not just while driving.
  - **Your crew, on the radar.** Every teammate is an outlined dot on the minimap, and small coloured markers name and point toward the ones too far away to see.
- **v0.9's additions:**
  - **The rubber chicken** (8). Squeak. Knocks people over harder than a punch, and it's no heat at all: assault with a rubber chicken isn't on the statute books. Cell doors are unimpressed.
  - **The whoopee cushion** (9). Lay it down. Whoever treads on it goes PFFFFT, and everyone within 14 m (officers and guards included) is helpless with laughter for 3.5 s. Three parps a cushion.
  - **The cardboard box.** C to get in. You shuffle at a third of your speed, and you can't punch, but stand still for a moment and **nobody can see you**: not the cops, not the witnesses, not the officer who was about to cuff you. Move, and you're a box with little legs.
  - **Steal the cop car.** When an officer gets out to chase somebody, his car's sitting there with the engine running. Hold E on it for 2 s. +30 heat, the siren's your horn now, and the officer is left standing in the road.
  - **Chickens cross the road** near you every so often. Why? Nobody knows. Hit one and it's feathers.
  - **Mimes.** Trapped in invisible boxes on the pavement. Not witnesses (what would they say?). Rob one and you get $0: it was an invisible wallet. Punch one and he mimes it, beautifully.
  - **Stunt ramps** in every car park. Hit one at more than 14 m/s (about 31 mph) for **BIG AIR!** and $40 from the crowd for every second you're up there.
  - **Money trucks.** About one in sixteen traffic cars is an armoured van with the day's takings in the back. Shoot its back doors five times (or ram it from behind) and the doors burst: bags of cash all over the road, +25 heat, and the driver doesn't even notice. Or carjack it and check the boot.
  - **Pigeons** peck about under the street lamps and scatter when anything comes near or goes bang.
  - **Hats.** A third of pedestrians wear one (flat cap, bowler, cowboy, top hat, bobble), and it comes off when you knock them down.
- **v0.8's additions:**
  - **The K9 unit.** From 60 heat some cop cars bring a dog. You can't outrun it. It doesn't arrest you; it takes your **trousers**, and you shuffle at half speed in your boxers for 9 s. (The boxers have patterns. The game tells everyone which.)
  - **The streaker.** Every couple of minutes a naked man sprints through town. Cops near him forget all about you, and stop witnessing. Tackle him for a citizen's arrest: +$50 and -10 heat.
  - **Speed cameras** post your own clean ride a $40 ticket if you go past at more than 90 km/h. **SMILE!**
  - **Smoke screens.** Hold a burnout for 1.5 s and the smoke's thick enough to hide in: nobody can see through it for 10 s.
  - **Hydraulics** ($500 in the mod shop): X in the car and it bounces. Pedestrians stop to enjoy the lowrider show (and stop witnessing).
  - **Pops and bangs**, a **two-step** on the brake stand, and **VTEC JUST KICKED IN, YO**.
  - **Mugshots.** When you're busted, the game reads out your charge sheet: 3X GRAND THEFT AUTO, GNOME THEFT, UNLICENSED DANCING, LITTERING (BANANAS), BRIBERY (DONUTS)...
  - **One phone call.** Somebody always uses it to order a pizza.
  - **The orange jumpsuit.** Break out of jail and you're wanted on sight until you get back to the shop and change.
  - **Confetti** and a kazoo fanfare every time a car's delivered.

### The city

- **The soundtrack** is an original dark trap beat in the Memphis / phonk lane: sliding 808s, a clap on the three, rattling hi-hat rolls, a pitched cowbell and an eerie music-box bell. It's synthesized at startup (no audio files). The hats and cowbell kick in when you're on a job and hit harder when the heat's on. **M** toggles it.
- **The city's bigger now**, with a narrow back alley cut through every ordinary building block -- too tight for any car, but a person on foot (or a cop who's lost you around a corner) can use one to disappear. More pedestrians, more traffic, more parked cars and more gnomes to match.
- **Traffic:** nine cars (any of the vehicle types except the scooter) drive the grid, keeping right. They slow for corners, stop and honk if you stand in the road, and swing around stalled cars. Give one a small bump and the driver sits there, stunned and honking. Hit one hard enough to throw people out (or shred two tyres) and the driver bails and runs, leaving the engine running: get in and it's yours, for +10 heat. Traffic drivers are *not* witnesses, and their horns don't confuse cops.
- **Pedestrians** run from cars coming at them faster than about 50 km/h (they dive sideways), from crashes and explosions, and from anywhere near a stolen car while the cops are rolling. Panicking doesn't stop them from being witnesses.
- **The automap (Tab)** scales smoothly to fill your window now, rather than sitting at a fixed size with black bars down the sides on anything that isn't an exact multiple of the game's base resolution.

### Heat and cops

- Heat is shared and runs from 0 to 100, and takes a bit longer to build than it used to. A cop or a chopper still adds heat live (+3/s, +2.5/s), and a street camera +1.2/s (cameras only see stolen cars) -- only the highest single rate counts, so witnesses don't stack. A pedestrian or angry owner doesn't add heat live at all any more: see below.
- **A pedestrian or owner phones it in.** Clock one and they don't call the cops on the spot -- they need 10-15 seconds to actually make the call, and it's a flat **+15 heat** the moment it lands, whether or not you're still in sight by then. Kill them first (see [Crime](#crime)) and the call is cancelled for good.
- Wanted targets are stolen cars that haven't been delivered, plus anyone on foot outside the shop while heat is above 0. Sitting in your own clean car hides you. Sealing every bay of the shop with the whole crew inside clears heat to 0 outright, same as a delivery.
- Crimes add heat on the spot: punching someone +5, robbing +4, a gunshot within earshot +8, carjacking +12, shooting a civilian or a member of the law +18 (murder -- it never wears off the rap sheet), stealing a police car +30, hitting a cop straight to 100.
- If nobody sees you for 4 s, heat cools at 3/s. Parks and buildings block line of sight.
- **Two patrol cars are always out there**, cruising the grid like traffic. They don't chase anyone until they see a wanted target, and then they do.
- Heat is a **wanted level**: 1 cop car on the way at 25 heat, 2 at 50, 3 at 75 and **5** at 100, from the edge of the map -- but only up to a cap of new units per day, so a long enough chase eventually runs the precinct out of spare cars.
- **(v0.12.1) Dispatch gives them a rough idea.** A freshly dispatched car is told roughly where you are (give or take 20 m), a witness's phone call does the same for any car without a lead, and a cop that's lost you gets a fresh vague tip a few seconds later. They still have to actually *see* you to lock on -- but they no longer sit idling round the corner forever because nobody told them where to look.
- **A cop that loses sight of you drives to your last known spot, not straight at you.** Walls and buildings genuinely block a cop's view now; lose them around a corner for a few seconds and they're guessing, not psychic. Give them nothing to go on for long enough and they give up the chase.
- **Cops miss.** Bullets from a cop or an officer land only some of the time, so standing your ground in a shootout isn't instant death -- it's still a very bad idea.
- **Health, not one hit.** You (and now the law) have a health bar. A bullet takes a real bite out of it and you recover on your own a few seconds after the last hit, so a graze isn't the end of a run -- an empty bar is.
- **Officers (v0.8).** When a cop car catches up with a crook on foot, it pulls over and an **officer gets out** and runs you down (faster than you walk, slower than you sprint). Let him stand next to you for 1.2 s and you're cuffed: **BUSTED**. **Punch him** (+15 heat: assaulting an officer) or **mash Space** to wriggle out of his grip. He gives up and walks back to his car if you get away or reach the shop.
- **Tasers.** From 50 heat, officers tase you from a few metres. You twitch on the pavement for 2 s, and the cuffs go on twice as fast while you're down. **DON'T TASE ME, BRO.**
- **A helicopter joins in once heat is high enough.** It sees over walls and buildings (it's airborne), so getting indoors matters more than ducking down an alley once it's up.
- **Lethal force** only happens once *you* escalate: fire a gun anywhere a cop can hear it, or hit a cop or a cop car with a bullet, and the police shoot to kill (officers on foot and out of car windows; the status bar says **LETHAL**) for 45 s -- refreshed by every shot, and it also stands down early if no cop's had eyes on any of the crew for a while. A police bullet that empties your health bar is **WASTED**: you drop everything, and the crew loses **50% ÷ the number of players** of its cash (half solo, a quarter each for two, an eighth for four). You wake up at the shop 4 s later.
- **Shooting an officer or a guard kills them, not just knocks them down**, and an ambulance is sent for the body -- but every other cop in the city is now shooting to kill.
- **Busted = the precinct.** You drop what you're carrying (your partner can grab it), sit on the kerb for the mugshot, then wake up in a **cell** in the precinct lockup, a walled police station a few blocks from the shop. (Two cells, one in each back corner. With two of you busted, you get one each.)
  - **(v0.13) The impound:** five motorbikes are parked nose-out along the outside of the precinct walls with the keys in them (the desk sergeant is having a day). Walk out of the gate, hop on (E), gone. Taking one is a theft (+10 heat), and a new one is put out every 20 s or so when nobody's watching. Made for the solo escapee.
  - **(v0.12.1) The heat drops to 0 the moment you're in a cell** -- as far as the city's concerned, the case is closed -- and when you walk out of the precinct you get a **15-second head start**: cops can see the jumpsuit (and heat climbs), but nobody can cuff, tase or shoot you until it runs out. No more getting re-arrested on the front steps.
  - **Get out of the cell** (v0.9): walk up to the door and **hold E for 7 s to pick the lock** (quiet: the guards don't notice), or **punch the door six times** (loud: they come running). A crewmate in the hall can let you out in 1.5 s. Or press **X** to post bail.
  - **Then the hall.** Three guards; the big one has the **keys**. They're tough now: four knockdowns each, six for the big one, and they're back up in 3 s. But they fight fair. **Only one comes at you at a time**; the others wait their turn a few metres off. Whoever lands a punch steps back. And nobody can knock you down again for 1.5 s after you get up. If you picked your way out quietly, they don't notice you until you get within 7 m of one. If you brought a gun in, a bullet kills a guard same as an officer -- the ambulance comes for them too.
  - Knock the big one down, hold E on him to take the keys, and E at the gate opens it. Then run: you're in an **orange jumpsuit**, a jailbreak is +40 heat, and the whole city knows your face until you get back to the shop and change. Other ways out:
  - a crewmate **picks the gate's lock** from outside (hold E at the gate for 6 s),
  - somebody **rams the gate** with a car,
  - or you **post bail** ($250, and $100 more every time): X in your cell, or E at the front desk in the hall.
- Ram a cop at more than 25 m/s relative speed and it catches fire, then explodes after 3 s. All its parts scatter as loot.
- **The shop's doors:** shut, cops can't drive or walk through them, and they can't see in. They'll bang on it and shout, though.

- **(v0.12.1) The shop's front** is a proper brick facade with a parapet: four sectional roller doors, one per bay, and a steel walking door with a push bar (1.4 m wide -- people only). E at any of them opens or shuts it.

### Crashes

Damage is based on **how suddenly you stop** (delta-v), not on top speed:

- **6 m/s or more:** dents, plus a 35% chance that a panel flies off.
- **11 m/s or more:** everyone in the car gets thrown out and tumbles, and 1-3 parts fly off.
- **18.7 m/s or more:** wheels come off, and the car drags and pulls to one side.

Cars hitting people (v0.9): what counts is how fast the car's **bodywork** is moving into you where it touches you. A **parked car can't knock you over**: run into one and you slide round it. A moving one at more than 5 m/s (a swinging drift tail counts) sends you tumbling, and you leave **at the car's speed** plus a shove, then skid down the tarmac for a couple of seconds. More than 15 m/s and you're airborne as well. Thrown people fly further too (about 12 m).

---

## Jobs and the story

### The main story (v0.13)

Bryce: "can you instate the story quests as a separate persistent quest that updates when you finish it. still have the REP guard rails to progress. but i need story quests and dialogue (written)."

**Ten chapters, one at a time, always shown at the top of the panel under the radar** ("STORY 3/10: WORD ON THE STREET"), above the daily jobs. The line under it says what to do next:

- **"NEEDS 6 REP (HAVE 3): DO THE DAILY JOBS"** -- the REP guard rail. A chapter won't open until the crew's REP (earned only from the daily jobs below) reaches its bar. The story itself pays cash, never REP.
- **"> TALK TO THE FIXER AT THE SHOP"** -- the chapter's ready. A gold arrow on screen points to whoever you need; walk up and press **E** and their opening scene plays in the dialogue box, one speaker at a time (**Enter** skips ahead).
- **"> CARJACK A CAR OUT OF TRAFFIC"** -- the objective itself, with a count where there is one. It tracks on its own; when it's done, the closing scene plays wherever you are, the crew gets paid, and the panel moves on to the next chapter.

| # | Chapter | From | REP | Objective | Pays |
|---|---|---|---|---|---|
| 1 | Opening Hours | Paige | 0 | Steal a car and park it in the shop | $250 |
| 2 | Tools of the Trade | Paige | 0 | Fit a part to your ride at the tune-up bench | $200 |
| 3 | Word on the Street | The Fixer | 1 | Go and say hello to Tommy at his lot | $150 |
| 4 | Moving Target | Paige | 3 | Carjack a car out of traffic, then deliver it | $400 |
| 5 | Feel the Heat | The Fixer | 6 | Get the heat to 50, then lose them (heat back to 0) without getting cuffed | $500 |
| 6 | Hostile Takeover | The Fixer | 8 | Buy Tommy's lot | $600 |
| 7 | The Inside Job | Paige | 10 | Get arrested on purpose, then break out (bail doesn't count) | $750 |
| 8 | Blue Lights | Tommy | 13 | Steal a cop car while its officer's out, and deliver it | $900 |
| 9 | The Audition | The Kingpin | 16 | Deliver 3 cars before midnight | $1,200 |
| 10 | The Big One | The Kingpin | 20 | Deliver a car with 75+ heat on you | $3,000 |

The cast: **Paige** (runs the shop Uncle Rick left her), **Mo** (the mechanic, attached to one particular 10mm socket), **the Fixer** (talks to walls), **Tommy Castellano** (the rival body shop), **the Kingpin** (downtown), and **Captain Dorsey** (the new precinct captain, heard on the scanner). The story is crew-shared, like cash and heat: anyone in the crew can move it on, and every crewmate sees the scenes. Your chapter is kept in your save slot.

### The daily jobs

Under the story, top right, is today's board: **3 jobs**, your crew's **REP**, and the **act** you're in. There's no menu and no start button -- all 3 track in the background off whatever you're already doing. Steal a Kei and, if "HOT WIRE SPECIAL" is one of today's three, you're already working it. A finished job pays out cash and REP the moment its last condition is met, and shows **DONE** on the board until the next rotation (once a day, at midnight, alongside the rent).

- **15 jobs total, in rough order of REP needed to unlock:** Hot Wire Special (steal and deliver a Kei under 40 heat), Heat Run (deliver anything without heat sitting over 60 for more than 20s), Part Collector (strip 3 one-handed parts), Night Job (steal, stay free 90s, deliver uncrashed), The Perfect Steal (zero damage, start to finish), The Repo (steal a car whose owner's watching and get away with it anyway), Clown Car Chaos (find one, deliver it, clowns included) -- then, once your crew's earned some REP: The Engine Pull (deliver with the engine in, winch it out, bolt it to your own ride -- a two-person job, but nothing stops you doing both halves yourself), Body Shop Wars (Tommy's after the same car -- steal and deliver one inside 5 minutes or he beats you to it), The Corporate Contract (deliver something with 5+ styled parts, heat under 30), Family Business (deliver with a passenger aboard, then have them strip 2 parts), Catch & Release (hold 70+ heat for 2 minutes without getting busted, then deliver) -- and at the top: Black Market Deal (two different 5+-styled-part cars, delivered within 5 minutes of each other), The Escape (steal loud on purpose, stay free 3 minutes or reach the shop), King of Downtown (3 deliveries back to back, each within 2 minutes of the last).
- **(v0.12.1) People to talk to.** Walk up and press E. **Paige** stands at the back wall of the shop and reads out today's jobs (brief, pay, time limit, crew jobs). **The Fixer** leans on the shop's west wall and tells you where the next shop's for sale, how far, which way, and what it costs. **Tommy** runs the rival body shop across town and trash-talks accordingly, and **the Kingpin** holds court at the top lot. **Dave** (parts counter) and **Mo** (mod shop) work the counters. What they say pops up in a dialogue box low in the middle of the screen.
- **Reputation moves you through 3 acts** -- Struggling, Growing, Dominance, at 6 and 16 REP -- with a toast when the city's mood shifts. 25 REP and the crew's basically running downtown; the game doesn't end there, it just means you've made it.
- **Story points and which jobs you've ever finished persist in your save file** (see [Save files](#save-files)); today's specific 3 and whatever's mid-progress on them reset fresh each load, same as heat always does.
- This is adapted from a bigger design doc that assumed a quest board, named NPCs and per-quest start/turn-in menus; a few jobs (the ones that leaned on mechanics Chopped doesn't have, like an AI racer or a second drop-off point) were rebuilt around what the game actually does instead. Nothing about it needed new controls -- it's all riding on top of stealing, driving and delivering, same as everything else.

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

## Save files

**(v0.12.1) Save slots, right on the main menu.** Under HOST sits a **SAVE SLOT** row: A/D (or the arrow keys, or Enter) cycles through slots 1-3 and OFF, and it shows what's in each one (day, cash, act, and on the hint line your rep and crew). If the slot has a save, the top item reads **CONTINUE THE RUN**; if it's empty, **HOST NEW GAME** starts a fresh crew in it. Press **Del** (or X) twice on the slot row to wipe it. While hosting, **F5** saves right now, and the pause screen (Esc) says where it's saving. Slots live in `%APPDATA%\Chopped\saves` on Windows (`~/.local/share/chopped/saves` elsewhere). A save also remembers its **city**, so you continue in the same streets with the same shops. OFF means nothing is written.

`--save FILE` on the command line (works with `--host` or `--server`) still picks an exact file instead, and a headless `--server --save FILE` reloads that save's city too:

- **What's saved:** the shared cash, the day and rent clock, the parts locker, **which shops the crew owns (v0.12)**, and every player's own car -- model, every fitted part and its condition, paint, livery, horn, underglow and extras -- keyed by the name they joined with.
- **What isn't:** heat, cops, traffic, pedestrians, and everyone's position. Loading a save always drops the crew back at the shop on a quiet morning, never mid-chase.
- **When it writes:** every 30 seconds while hosting, and once more on a clean shutdown (closing the window, Ctrl+C on `--server`, or leaving to the menu). A crash or a yanked power cord costs at most the last 30 seconds.
- **A returning name gets their car back.** Join under a name that owned a car last time and you're handed that car, mods and all, instead of a fresh Kei -- even if you've since switched to a nicer stolen ride (the mod shop's SWITCH CAR remembers whatever you're driving when the save happens, not what you started with). A new name always gets an ordinary stock car.
- The file's plain JSON, so `cat crew.json` (or open it in a text editor) tells you exactly what's in the tin.

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
  - the full loop: steal, drive into the garage, deliver, strip, sell, fit parts in the mod shop, rent, SHOP SEIZED and reset (personal mods kept)
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
- `tests/test_dolly.py` covers the dolly (strip, load, sell, into the locker, speeds, letting go, coming home).
- `tests/test_combat.py` covers v0.6 crime: punch and rob, hands up, buying at the black market, shooting people, tyres and cop cars, empty clicks, confiscation on arrest, spike strips making traffic bail, roadblocks stopping traffic, carjacking, ramming a roadblock, and the new protocol fields (arsenal, traps, shot events) within the packet budget.
- `tests/test_music.py` checks that the beat's two layers loop seamlessly, aren't silent or clipping, and hit on the one.
- `tests/test_garage.py` covers v0.7 trunks (put, take, a full Kei, loot in stolen cars, an engine in a pickup bed, spilling when the shell is crushed, the trunk in the SELF block), the vehicle models and part styles, and the mod shop (the locker, fit, buy, remove, sell, paint, liveries, horns, extras, no credit, a resent command billing only once, the menu over the wire, and buying with mouse clicks through the real client menu).
- `tests/test_brawl.py` covers peds fighting back (getting up swinging, taking their money back, armed peds), picking up and bowling people, carrying and wriggling free, haymakers, dancing, jumping a roadblock, patrol cars, donuts, cops shooting at high heat, bananas, the ejector seat, gnomes, the ice cream queue and NOS. Throwing parts is in `tests/test_combat.py`.
- `tests/test_police.py` covers v0.8's police: officers deploying and cuffing, walking back, wriggling out, punching an officer, tasers, the lethal clock and what a death costs (per player count), the precinct (every city has one; the gate is solid until it opens, for the predictor too), keys, guards, bail, lock picking, ramming the gate, the mugshot, the K9 unit, the streaker, speed cameras, smoke screens and hydraulics.
- `tests/test_engines.py` covers revs and gears (shifting up, the rev limiter, turbo spool and blow-off, supercharger boost, VTEC), the engine notes (every voice loops without a click and rises in pitch with the revs), brake stands and donuts (and that a burnout predicts exactly), catching a handbrake slide in every rear-drive car, the handbrake yaw cap, rice rockets, 4x4s on grass, and engines on the wire.
- `tests/test_drift.py` pins the tyre model down: straight lines stay straight, handbrake turns rotate, rear-drive power oversteer, front-drive understeer, slides that catch themselves, braking distance, model top speeds, bananas, and a predicted jump that matches the host.
- `tests/test_police.py` also covers v0.9's cells: every city has two, you wake up in one, the bars are solid (and can't be jumped), punching the door open is loud and picking it is quiet, bail with X, a crewmate letting you out, one cell each for two prisoners, tougher guards, and guards that take turns and never hit you while you're getting up.
- `tests/test_v09.py` covers the rest of v0.9 and v0.10's garage redesign: selling a car whole (the price, the collector's bonus, the boot), the inspect card (and not through walls, and not your own car), parked cars not knocking you over, the car-hit slide, longer throws, every silly feature, the arsenal on the wire, that the sim never imports pygame, and each bay door (and the walking door, and the pillars between them) as its own independent trap, shutting, blocking sight and cop cars and officers, and never walkable while shut, for the predictor too.
- v0.10's other additions are folded into the files above: `test_sim.py` covers cutting the wires (the toggle, the right wire, the wrong wire, an angry owner never noticing a clean cut) and the delayed witness call (no live heat from a ped, the call landing after the delay, killing the witness cancelling it, and the ordinary cooldown afterward); `test_combat.py` and `test_police.py` cover shooting civilians and the law dead instead of just knocking them down.

- `tests/test_savefile.py` covers save files: the economy (cash, day, locker) round-tripping through a dump and apply, a returning name getting their exact car back (parts, paint, livery, extras) while a stranger gets an ordinary one, a switched primary car being what actually gets saved, heat/cops/positions never being saved, a missing or corrupt file being a quiet no-op, a foreign save version being ignored, and `net.Server`'s `--save` wiring loading on start and saving on a clean stop.

- `tests/test_quests.py` covers the jobs and the story arc: the daily rotation only offering unlocked jobs, story points moving you through the acts (and campaign victory at 25 without a 4th act), Hot Wire Special (model, heat and damage gates), Heat Run (a blown attempt isn't a permanent lock -- a real bug this suite caught), Part Collector (one-handed parts only), a crash ending The Perfect Steal, an arrest failing Night Job, today's 3 jobs and REP/act surviving the wire in `SNAP_HDR`, and reputation/completed-ever persisting through a save while today's specific rotation resets fresh.

- `tests/test_v013.py` covers v0.13: the story's opening and closing scenes, the REP guard rail (and that the story never hands out REP), every objective type (installing a part, talking to Tommy, carjack-then-deliver, heat up then lose it, buying the lot or already owning it, arrest-then-breakout with bail not counting, a real jailbreak, the cop car, three before midnight, the hot finale and the end), every scene line having glyphs in the pixel font, the story on the wire and in save files; bikes (two wheels, quick off the line, easier to fall off, no doors); the impound (outside the walls, keys in, a theft to take, never restocked in view, culled from far snapshots); and the pause menu's INSTRUCTIONS button.
- `tests/test_v0121.py` covers the v0.12.1 fixes: a switched car being drivable (and trading places with the old one instead of landing on it), heat clearing in a cell plus the jailbreak head start, dispatched cops being given somewhere to go, Paige's prompt and speech (and its cooldown), fence lots sorted by price, the walking door's brick jambs blocking sight, the shops-owned bitmask on the wire, save slots (peek, wipe, atomic writes, the city seed coming back), the whoopee cushion no longer crashing the host after SHOP SEIZED, and the mod shop's close handshake.
- `tests/test_v12.py` covers the round: every new gun burning ammo and hitting lethal (a direct hit for the hitscan guns, everyone in the blast radius for the grenade launcher and RPG, a cop car catching fire), the arsenal's two-byte weapons bitmask and its 5 new ammo counts on the wire, the market selling every new gun and topping all of them up from one ammo crate, arrest confiscating every gun (not just the first three), buying a fence shop through the normal hold-E flow and it unlocking that shop's crates, shop ownership surviving a save/load round trip, and the 10 silly features (scratch tickets, jackpot wallets, loose change in stolen cars, the tip jar, high fives, speed camera fame, the ice cream van honking back, and the NOS backfire puff).

253 tests in total.

---

## Code map

```
main.py              entry point / CLI (--host --join --server --selftest ...)
chopped/config.py    EVERY tuning number, with comments explaining why
chopped/enums.py     states, buttons, sounds, weapons, banners (shared by host and client)
chopped/lines.py     every joke the game tells you
chopped/entities.py  Car, Player, NPC, Dolly, Trap, Pickup, InputState
chopped/parts.py     part catalogue, slots, styles on parts, loadouts, trunk loot
chopped/vehicles.py  the 11 vehicle models, paints, liveries, horns, part styles, performance maths
chopped/mapgen.py    deterministic procedural city (seeded; clients rebuild it locally), including the
                     home shop, the precinct and (v0.12) three purchasable fence shops
chopped/physics.py   the shared Physics mixin: tyre model, collisions, walking, jumping
chopped/brawl.py     fighting back, throwing parts and people, haymakers, dancing (World mixin)
chopped/garage.py    trunks and the mod shop's host side (including switching your personal car), plus
                     its wire codec; sizing cars up and selling them whole; the shop's bay and walking
                     doors (World mixins)
chopped/police.py    officers, tasers, lethal force, health and dying, ambulances and the chopper, the
                     precinct lockup and its cells, K9s, the streaker, speed cameras, smoke screens,
                     hydraulics (World mixin)
chopped/sillies.py   v0.9's chickens, mimes, stunt ramps and money trucks, plus (v0.12) the ice cream
                     van honk-along and the crew high-five (World mixin)
chopped/quests.py    the 15 daily jobs, rotation and the 3-act story arc (World mixin, no pygame)
chopped/story.py     (v0.13) the main story: 10 REP-gated chapters, their written scenes, and the
                     World mixin that tracks them (no pygame)
chopped/drivetrain.py  revs, gears and boost for the tachometer and the engine notes (client, no pygame)
chopped/enginesynth.py the engine voices, turbo whistle, blow-off, pops, screech (pure Python synthesis)
chopped/sim.py       authoritative world: crashes, heat, cops, traffic, pedestrians, the dolly,
                     guns/traps/carjacking, economy (no pygame anywhere in the sim modules)
chopped/predict.py   client-side prediction: runs sim.Physics on your own car/avatar, reconciles
chopped/protocol.py  packet formats; struct + zlib snapshots, distance culling, prediction block
chopped/net.py       UDP Server (60 Hz sim, 20 Hz snapshots) and Client (60 Hz input, prediction,
                     100 ms interpolation for everyone else, --fake-lag), --save load/autosave
chopped/savefile.py  --save FILE: JSON dump/apply of cash, day, locker and each player's car by name
chopped/upnp.py      optional miniupnpc port mapping (runs in a background thread)
chopped/art.py       palette, 3x5 pixel font, procedural sprites, pre-rendered city
chopped/render.py    top-down renderer (the Tab automap), particles, skid marks, camera
chopped/ui.py        main menu
chopped/modshop.py   the mod shop's menu and car preview (client side)
chopped/audio.py     procedural square-wave sfx and loops (silently disabled if there's no audio device)
chopped/fp.py        first-person raycaster: textured walls, mode-7 street floor, the shop's roof (a mode-7
                     ceiling) and its bay/walking doors, the trunk-popping animation, sky, sprites,
                     pigeons, flying hats
chopped/fpart.py     first-person art: facades, skies, box-model cars/people rendered from 16/8 angles
chopped/doomhud.py   status bar, face, messages, first-person hands / dolly / dashboard overlays
chopped/music.py     the procedural beat (pure Python, rendered once at startup)
chopped/game.py      pygame app loop, host/join flow, mouse look, chase camera, selftest bot
tools/make_icon.py   build-time icon + Windows version resource (from the sprite code)
tools/smoke_exe.py   tests a BUILT exe: selftest + host/client over UDP
.github/workflows/build.yml   tests on Windows + Linux, builds and smoke-tests Chopped.exe
```

### Netcode notes

- **Clients send inputs, not positions.** One input goes out per 60 Hz sim tick. One-shot keys (E, G, F, click) are sent as counters, so a quick tap still registers if a packet is lost. Mod shop commands ride along in the same input, one at a time: the client waits for the host to acknowledge each before sending the next.
- **Your own car or avatar is predicted.** Each client runs the host's exact physics (`physics.Physics`, tyres, jumps and all) on its own entity the moment you press a key. Each snapshot says which of your inputs the host has applied, and gives your full-precision physics state. The client rewinds to that, replays the inputs the host hasn't seen yet, and smooths out any leftover miss over about 80 ms. A miss usually means a cop or car the host knew about and you didn't. Tumbling, cuffed or riding shotgun fall back to plain extrapolation.
- **The server sends each client its own snapshot** at 20 Hz. Each one is zlib-compressed and usually 200-800 bytes. Pedestrians, loose parts and traffic farther than 95 m from that player are left out. Stealable cars are always sent.
- **One-off events are delivered reliably.** Toasts and sound events repeat until the client acknowledges their sequence number.
- **The host sees no lag.** The host's own window is a loopback client that receives every server tick.

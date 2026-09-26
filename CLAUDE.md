# CLAUDE.md — Chopped handoff

You're picking up **Chopped**, Bryce MacKenzie's co-op car-theft chop-shop game. Two codebases exist:

1. **This folder — the Python version.** A Doom-style first-person pixel-art game (with a top-down automap) for 1–4 players online. It works and its tests pass. **Your main job is here.**
2. **The Unity version** at `F:\Unity\Projects\Chopped`. It's first-person, uses Unity 6.6 with Netcode for GameObjects (NGO), and its game-loop scripts are written but have never been compiled. See the section at the bottom.

Tone: GTA 2 meets a heist gone wrong. Code comments are funny *and* explain why each tuning value is what it is. Keep that style.

---

## 1. Status and your tasks, in order

### Where things stand (Sept 26, 2026, session 2, RELEASE 0.11.0: jobs and a story arc)
- **Jobs and the story arc** (Bryce uploaded `CHOPPED_QUEST_SYSTEM.md`, a design doc written for
  the Unity side -- NetworkBehaviours, ScriptableObject quest assets, named NPCs. Asked where it
  should go: ported to the Python game, crew-shared, no per-player state). All done:
  - **`chopped/quests.py`** (new, no pygame, `Quests` mixin added to `World`'s bases): 15 jobs as
    plain data (`QUESTS`, keyed by id; `QUEST_ORDER` is the FIXED order a job's index rides the
    wire in -- append only, never reorder). 3 rotate in daily (`_rotate_quests`, hooked into the
    existing midnight rent rollover in `_economy` and into `reset_run`), picked from whatever
    `world.story_points` has unlocked.
  - **No "start quest" button.** All 3 of today's jobs track passively, all the time, off
    whatever you're already doing -- steal a Kei and you're automatically working "Hot Wire
    Special" if it's in today's three. Ten one-line hooks do the watching: `_quest_on_steal`
    (from `_break_in`, `_cut_wires`, `_carjack`, `_steal_cop_car`, and the bailed-traffic branch
    of `_enter_car`), `_quest_on_deliver` (from `_deliver`, called *before* it zeroes heat, so
    heat-gated jobs like Corporate Contract can still read it), `_quest_on_strip` (from `_strip`),
    `_quest_on_dolly_engine` (from `_dolly_strip`), `_quest_on_install` (from `garage._ms_install`)
    and `_quest_on_arrest` (from `arrest`). `_quest_tick`, called last in `World.step`, drives
    everything that's a clock instead of an event (heat thresholds, evasion timers, the two co-op
    jobs' delivery-cadence windows).
  - **Adapted, not copied, where the Unity doc leaned on mechanics Chopped doesn't have** (each
    is a comment on the job in `quests.py`): no AI racer for Body Shop Wars (a timer instead --
    "Tommy beats you to it" if you're too slow); no second drop-off point for The Repo or Black
    Market Deal (both deliver to the shop, same as everything else); no mid-drive stripping from
    the passenger seat for Family Business (the passenger strips after delivery instead); Part
    Collector's "+$40 per part beyond 3" bonus is gone -- it assumed a separate turn-in step that
    doesn't exist here, and without it there's no way to hold more than 3 before the job
    completes.
  - **Story points move the crew through 3 acts** (`ACT_THRESHOLDS` 6/16/25, `_check_act_up`),
    same shape as the Unity doc's Struggling/Growing/Dominance, with a toast standing in for the
    doc's dialogue system -- narrative beats are lines with a name on them (`"PAIGE: ..."`), the
    same way every other line in this game talks to you (`lines.py`). 25 points sets
    `World.campaign_won` (a flag, not a 4th act) and prints a "credits roll" toast; nothing stops
    the run.
  - **Wire cost: 7 bytes, always sent, no optional block.** `SNAP_HDR` (`protocol.py`) gained
    `story_points` (H), `act` (B), today's 3 job indices into `QUEST_ORDER` (B each, `NO_QUEST`
    255 = fewer than 3 unlocked yet) and a done-today bitmask (B) -- jobs are crew-shared like
    cash and heat, so this rides the header everyone already gets, not a per-player SELF block.
    Client renders names/briefs/rewards locally from `quests.QUESTS`: nothing but ids and numbers
    goes over the wire.
  - **HUD:** `doomhud._quest_panel`, drawn just under the radar (`_minimap` calls it) -- REP, act,
    and today's 3 jobs, each turning gold-green and reading DONE once finished.
  - **Save files:** story points, the act and which jobs have *ever* been completed persist like
    the economy does (`savefile.dump`/`apply` gained `story_points`/`act`/`campaign_won`/
    `completed_ever`, additive fields under the same `save_version` -- an old save missing them
    just defaults to a fresh story, no version bump needed); today's specific 3 and whatever's
    mid-progress reset fresh on load, the same way heat always does. Loading a save re-rolls
    today's rotation against the restored story points.
  - **Fixed in passing, caught by the test suite:** the first version of Heat Run tied itself to
    whichever car got delivered first and never let go, so one delivery at bad heat permanently
    blew the job for the rest of the day even though the doc never specified a fail condition for
    it. It doesn't track a specific car at all now -- just watches the clock continuously, so a
    calmer delivery later still counts (`tests/test_quests.py`'s `TestHeatRun`).
  - **Protocol VERSION 11, RELEASE 0.11.0.**
  - **Tests:** `tests/test_quests.py` (new), 17 tests -- rotation respecting story-point locks,
    act transitions (and victory at 25 without a 4th act), Hot Wire Special's model/heat/damage
    gates, Heat Run's no-permanent-lock behaviour, Part Collector's one-handed-only rule, a crash
    ending The Perfect Steal, an arrest failing Night Job, the wire format, and the save file. 233
    tests total, all OK.
- **Decisions flagged for Bryce:**
  - **No quest board, no start/turn-in menu.** All 3 of today's jobs track simultaneously and
    silently. This fits Chopped's fast, prompt-driven pace far better than a menu you'd have to
    stop and click through -- but it does mean there's no in-fiction moment where a job is
    "accepted," and no way to deliberately skip one you don't want. If he'd rather have an actual
    board (E at a noticeboard in the shop, say), that's a real UI addition, not a small tweak.
  - **Killing peds/cops still costs the usual murder/cop heat on top of whatever a job pays** --
    jobs never override or discount the existing crime-and-heat rules, only add cash and REP on
    top of them.
  - **A job whose target car despawns or gets crushed before delivery is stuck for the rest of
    that day** for the handful of jobs with no built-in timeout (The Repo, Clown Car Chaos) --
    matches the original doc, which didn't specify a fail condition for them either. Worth
    revisiting if it turns out to feel bad in practice.

### Where things stand (Sept 26, 2026, session 2, RELEASE 0.10.1: save files)
- **Save files** (Bryce: "can you make save files?", then, clarified: crew progress only, not a
  full mid-heist snapshot). All done:
  - **`chopped/savefile.py`** (new, no pygame): `dump(world)`/`apply(world, data)` convert cash,
    `day`/`day_t`, `run`, the shared `stash` (the parts locker) and every player's own car to and
    from a JSON-safe dict; `load_into`/`save_to` wrap the actual file I/O and never raise -- a
    missing, corrupt or foreign-version file just means a fresh run, same as always.
  - **Cars are keyed by name**, not player id: a pid is just whichever slot you happened to
    connect into this session, but the name you typed is stable. `World.bay_owner_name` (new:
    bay index -> name) is set once in `add_player` the first time a name claims a bay and never
    cleared, even if they disconnect -- that's what a save's `dump()` reads at save time, so it
    always reflects whatever car currently lives in that bay, switched or not.
  - **`World._claim_saved_car`** (called from `add_player` right after a bay's assigned): if
    `World._pending_car_mods` (loaded from the save, name -> mods) has an entry for the joining
    name, it builds a brand new `Car` of the *saved* model with the saved parts/paint/livery/
    horn/glow/extras and swaps it in for the stock one -- a fresh `Car` because a model's box
    size, mass and drag are all derived once in `Car.__init__`, not safe to patch after. A name
    that switched to a stolen car (`garage.OP_SWITCH`) before saving gets that car back, not
    the Kei they started with.
  - **Deliberately NOT saved:** heat, cops, traffic, pedestrians, anyone's position or what
    they're holding. Loading a save always starts the crew back at the shop on a quiet morning.
  - **Wired into `net.Server`** (`--save FILE`, works with `--host` or `--server`): loads once at
    construction (a no-op if nothing's there yet, with a "WELCOME BACK" toast if there was),
    autosaves every `config.AUTOSAVE_INTERVAL` (30 s) from `pump()`, and saves once more,
    unconditionally, in `stop()` after the server thread's joined (so the world's quiescent --
    no torn writes racing the sim thread). Without `--save`, behaviour is bit-for-bit unchanged
    (default `save_path=None` everywhere, so every existing `Server(...)` call site and test is
    untouched).
  - No protocol change: this is host-side-only JSON persistence, nothing rides the wire. `VERSION`
    stays 10; `RELEASE` bumped to 0.10.1.
  - **Tests:** `tests/test_savefile.py` (new), 8 tests -- the economy round-tripping through
    `dump`/`apply`, a returning name getting its exact car back while a stranger gets a fresh
    one, a switched car being what's actually saved, heat/cops/positions never surviving a
    round-trip, a missing/corrupt file and a foreign save version both being quiet no-ops, and
    `net.Server`'s load-on-start/save-on-stop wiring through a real temp file. 216 tests, all OK.
- **Decision flagged for Bryce:** a save is JSON in a file you name (`--save crew.json`), not an
  automatic default path -- picked so nothing changes for `--selftest`/CI or anyone who doesn't
  pass the flag, same "explicit opt-in" pattern as `--log FILE`. If he'd rather it just always
  persist to a fixed file next to the exe with no flag needed, that's a small change to
  `main.py`'s arg defaults, not to `savefile.py` itself.

### Where things stand (Sept 26, 2026, session 2, seventh round: v0.10)
- **v0.10** (Bryce, one big list: "when cops die ambulance comes to pick themup and take them to the hotpital, make them die. add helicopters when fuzz is hot, make sure the heat takes longet to come up. hit boxes, itewms take precident overshops / actions. walls need to block cops views better - ray finding from cops view when in pursduit mode. wasted too much have a health bar instead of 1 hit. make cops miss sometimes. kimited number of cops spawn. / day. add overlay for in box vs out. poll heat value more often for changing lethal to not noticed by cops. kill civilians to make sure no witness remains, only tells cops after 10-15 seconds by phoneing them. Show assetsa for items in back of trunks. I cant change my ppirmary car, add option to switch primary cars once in garage. increase stamina better visibility for multiplayer. MAKE THE MNIN MAP SCALE TO WINDOW SIZE. sneaking / turning off the alarm on a stolen vcar by butting wire minigame, popping trunk animaiton. bigger city, back alleys between big building sizes.", then mid-round: "also make teh garage door smaller, make a walking entrance and a bay for each player that joins"). All done:
  - **Health, not one hit** (`entities.Player.health`/`hurt_t`, `config.PLAYER_HEALTH_MAX`/`BULLET_DAMAGE`/`HEALTH_REGEN_DELAY`/`HEALTH_REGEN_RATE`): a bullet is `police._shoot_player`'s damage, not instant death; you mend on your own once nobody's hit you for a few seconds. `WASTED` (and the cash penalty) only fires at 0 HP. Cops and the law get the same treatment: `sim._kill_npc` makes a gunshot lethal to civilians, officers and guards (dogs and the streaker are exempt -- that's a running joke, not a body count), charges `murder` or `cop` on the rap sheet, and sends an ambulance (`S_AMBULANCE`, a toast) for the law's dead. Killing peds is the quiet way to lose a witness for good; killing a cop makes every other cop in the city shoot to kill.
  - **Cops miss, and lose the scent** (`police._police_shot` already rolled `accuracy`; `COP_GUN_ACCURACY`/`OFFICER_GUN_ACCURACY` turned down now the miss doesn't just mean an extra unscathed second). `Car.last_target`/`search_t` (`sim._cop_ai`): a cop without direct LOS on you drives to your last-seen spot, not straight at your live position, and gives up after `COP_TRACK_LOSE_TIME` with nothing found. `World.los()` genuinely blocks it, so a corner is now cover, not decoration.
  - **Choppers and a slower heat climb**: `W_HELI`/`HELI_HEAT`/`HELI_RANGE`/`WITNESS_RATE_HELI` in `_witness_scan`, no wall occlusion (it's airborne), wire bit `AL_HELI`, client-rendered off that bit. Cop/camera witness rates cut about 40% (`WITNESS_RATE_COP`/`WITNESS_RATE_CAMERA`). `COPS_PER_DAY` caps fresh dispatches so a long chase can run the precinct dry. `WITNESS_CHECK_HZ` 10->15 and `World.lethal_unseen_t`/`LETHAL_UNSEEN_TIME`: lethal mode now also stands down early if no cop (car *or* officer on foot -- `_witness_scan` gained an OFFICER-NPC loop specifically so this doesn't false-trigger mid-chase) has had eyes on any wanted target in a while.
  - **Witnesses phone it in, on a delay** (`entities.NPC.call_t`/`phoned`, `config.PHONE_IN_DELAY`/`PHONE_IN_HEAT`, `sim._phone_ins`): a pedestrian or angry owner who spots you no longer adds heat live -- `_witness_scan` arms a one-shot `call_t` countdown (10-15 s) the first time they get LOS, and `_phone_ins` drops a flat `PHONE_IN_HEAT` lump when it reaches 0, wherever the witness is by then. Kill them (they leave `World.npcs`) and the call is cancelled for good; that's the whole point of "kill civilians to make sure no witness remains." Being currently watched still pauses the ordinary cooldown (`World._heat`'s `unseen_t` reset also fires on `witness != W_NONE`, not just a nonzero rate).
  - **Sneaking in** (`config.ALARM_CUT_TIME`/`ALARM_CUT_WIRES`/`ALARM_CUT_FAIL_HEAT`, `Player.sneak`, `sim._cut_wires`/`_breakin_specials`): X at a locked car toggles what E commits to. Smashing the window is fast and always screams; cutting the wires is slower and blind, one wire in `ALARM_CUT_WIRES` -- quiet (no alarm, no heat) if you guess it, louder than smashing and `ALARM_CUT_FAIL_HEAT` if you don't. A clean cut spares you the angry-owner encounter too (they only come running if they actually heard you); a clown car still bursts open either way, because that's the joke, not a stealth mechanic.
  - **Interaction priority** (`sim._find_interaction`, Bryce: "items take precedent over shops / actions"): a robbable person or a loose pickup now outranks a bench or the market crate you happen to be standing near; benches/market still outrank the gate/door and everything after. The one subtlety: a `DOLLY`-bulk pickup (a loose engine) only shows "TOO HEAVY -- FETCH THE DOLLY" when you don't have one; with your own dolly already there, it falls through to `_dolly_interaction`'s "LOAD X ONTO THE DOLLY" instead.
  - **Trunks, seen, not just implied**: `doomhud._gear_panel`'s trunk icon strip now shows on foot too (it only fired for `DRIVER`/`PASSENGER` before), so popping a trunk you're not driving actually shows you what's in it before you commit to stripping. Purely cosmetic on top: `FPRenderer._trunk_pop`/`fpart.trunk_lid_boxes` ease a lid open over `TRUNK_POP_TIME` off the SELF block's existing trunk data -- no new wire bytes.
  - **Switch your primary car** (`garage.OP_SWITCH`/`_ms_switch`, a new "SWITCH CAR" tab in `modshop.py`): from the mod shop, hand your current ride to the crew (it becomes an ordinary delivered civvy, bay and all) in exchange for a car parked in your bay.
  - **The box, visibly** (`doomhud._box_status`): a line above the bar says `BOXED UP - HIDDEN` once you've stood still long enough, or `HOLD STILL TO HIDE` if you're still just a box with legs -- `PF2_BOX`/`PF2_HIDDEN` were already on the wire from v0.9, nothing new to send.
  - **Bigger city, with alleys** (`config.BLOCKS` 9->11, `ALLEY_W`, and density bumps to `PED_COUNT`/`MAX_CIVILIAN_CARS`/`TRAFFIC_COUNT`/`GNOME_COUNT`; `mapgen._make_buildings` always cuts a `SIDEWALK`-typed alley through every ordinary block). Too narrow for any car; useful for losing a cop who's just lost LOS.
  - **Multiplayer visibility** (Bryce, clarified: "can't spot teammates on the radar/map"): the always-on radar's teammate dots get a dark outline so they read as people, not scrap (`doomhud._minimap`), and a new `doomhud._crew_compass` names and points toward any teammate who's out of frame or far off, same idea as the existing shop/car compasses.
  - **The automap scales to the window** (`game.Game._present`): the Tab automap now scales continuously to fill whatever window you've got, instead of snapping to the next integer multiple and leaving black bars on anything that isn't an exact multiple of 640x360. First-person keeps the old integer-only scaling on purpose -- chunky pixels matter more up close than they do on a schematic overview.
  - **STAMINA_MAX** 100 -> 140 (about 40% more legs before you're winded).
  - **Fixed in passing:** the stamina byte on the wire used a hardcoded 255/100 scale factor, which silently overflowed (`struct.error`) the moment `STAMINA_MAX` went above 100; it's `255.0 / C.STAMINA_MAX` now.
- **Protocol VERSION 10, RELEASE 0.10.0:** `PLAYER` struct +1 byte (health); SELF block's stamina byte scale is dynamic now; `AL_HELI` alert bit; `MAX_PACKET` 1150 -> 1200 for the bigger city and the per-bay doors (see the garage redesign below); car rows carry a `bay`/`owner` (server-side only, no new wire field needed -- switching cars rides the existing car rows plus 2 bytes in the SELF block's menu block for your own car id).
- **Also this round: the garage redesign** (Bryce, mid-list: "also make teh garage door smaller, make a walking entrance and a bay for each player that joins"):
  - **A bay and a car per player**, not one shared car (`World.player_car`: pid -> car id; `Car.owner`/`bay`). `World.personal_id` stays as a live alias for bay 0's car so the ~30 pre-existing single-player tests keep working unchanged.
  - **Five independent doors** across the shop's front instead of one wide one: a walking door plus one per bay (`config.door_specs()`, `DOOR_COLS`, `N_BAYS`; `garage.ShopDoor` rewritten for a list of `Trap` objects, each its own `open_t`/`goal`). The two tile-columns between the two pairs of bay doors are ordinary solid `WALL` tiles, not traps at all -- shutting every door seals the shop with zero extra LOS/wire special-casing for the gaps.
  - **`fp.py`'s raycaster tracks door openness per tile-column** (`self.door_open` went from one scalar to a list) -- the original single-door version would have shown every door in the same state, which a screenshot-based manual check (there's no automated visual test for the raycaster) caught before it shipped.
  - **`World._garage_safehouse()`** (called every tick from `_heat`): if every player -- and whatever they're driving -- is inside `map.in_garage()` with every door shut, heat clears to 0 immediately, same as a delivery, instead of only ever slowly cooling. This was the actual fix for Bryce's bug report "in the garage, cops still see us with the doors close" (the LOS-through-a-shut-door logic was already correct; there was just no instant clear for a genuinely sealed hideout).
- **Tests:** 208, all OK (v0.10 added a `TestWireCut` class and 3 heat tests to `test_sim.py`, rewrote `TestShopDoor` in `test_v09.py` for the multi-door API, and extended `test_combat.py`/`test_police.py` for lethal gunfire). Game-loop selftest about 48-52 fps.

### v0.9 (earlier this session)
- **v0.9** (Bryce: "make the drifting tighter. the hitbox for the vehicles not moving needs to not hit you while its parked ... add velocity when youre being hit so you slide ... throw people farther. make the cops in the precinct harder to kill, but make it so they cant box you in the corner and spawn trap you ... sell the vehicle whole ... inspect the cars before hijacking / breaking in ... a roof to the chop shop and a closable door that blocks cops. but it needs to be opened for you to get in. add 10 more silly features", then mid-round: "instead of just a big open hall in the precinct have a small jail cell you need to break out of first"). All done:
  - **Drift, tighter** (`config.py` block around `TIRE_C`/`HANDBRAKE_*`/`DRIFT_ASSIST_*`/`YAW_CAP_K`; the pre-v0.9 values are in git history). Handbrake flick + countersteer peaks ~31-35 degrees (was ~40), back in ~0.5-0.7 s; a held drift settles ~45 (was 60-70).
  - **People vs cars** (`Physics._body_vs_cars`): the impact is the car's *bodywork point velocity* toward you (spin included), not your own closing speed, so parked cars never floor you. A real hit carries you at the car's speed (`CAR_HIT_CARRY`) plus a kick, then a low-friction skid (`CAR_HIT_SLIDE_*`, `Player.slide_t` / `NPC.slide_t`). Throws: `THROW_PERSON_SPEED` 21 (flat, so bowling still works).
  - **Cells** (`mapgen._make_precinct`: `cells`, `cell_doors`, `cell_bars`, `cell_at`; `police.py`: `World.cell_traps`, kind `TRAP_CELL`, fixed ids from `CELL_ID_BASE`). You wake up in the emptier cell. Pick the lock (quiet, `CELL_PICK_TIME`), punch the door `CELL_DOOR_HP` times (loud: sets `World.jail_alert`), a crewmate lets you out, or X for bail. **Guards** (`_guard`): grit 4 (+2 for the key guard), up in 3 s, but only the nearest attacks, the rest hold at `GUARD_RING`, a guard steps back `GUARD_BACKOFF` after landing a hit, and `Player.grace_t` (`GETUP_GRACE`, also respected by brawlers) stops chain knockdowns. Quiet escapees aren't noticed until within `GUARD_NOTICE_R`. The bail desk (invisible since v0.8!) is now drawn.
  - **Fixtures:** the gate, the cell doors and the shop door are trap-shaped (`World.fixtures()`), sent as TRAP rows when near, and solid while shut. They go in `World.tall_rects` as well as `extra_rects`, and `_body_vs_world` uses `tall_rects` for anyone jumping (you can hurdle a roadblock, not a cell door). The predictor mirrors all of it (`predict.trap_row_solid`; TRAP row life decodes to 0..1).
  - **Sell whole / inspect** (`garage.Appraisal`): X at a delivered car = `whole_price` (70% of parts + shell + collector bonus if complete). Inspect: `_inspect_scan` at 10 Hz sets `Player.inspect`; the SELF block's optional `SB_INSPECT` carries the card; `doomhud._inspect_card` draws it after `INSPECT_DELAY`.
  - **X on foot** now sends `B_HOP`; `_find_interaction` may return a 5th element, the X action (`alt_tap`).
  - **Roof + roller door** (`garage.ShopDoor`, `TRAP_DOOR`, `DOOR_*`): the door spans the whole shop front (`DOOR_W`), E toggles, honk within `DOOR_REMOTE_R` toggles, safety sensor, `World.los()` (door-aware, used everywhere `map.los` was) stops witnesses seeing through it, cops bang on it. Client: the door is a raycast "thin wall" on the tile boundary (half-open doors draw over what's behind), the roof is a mode-7 ceiling layer masked by the zbuf, and sprites outside the front edge get clipped (`FPRenderer._roof`, `roof_clip`). About 1 ms per frame near the shop.
  - **Silly** (`sillies.py` + bits in sim/fp): rubber chicken (`ARM_CHICKEN`, no heat), whoopee cushion (`ARM_WHOOPEE`/`TRAP_WHOOPEE`, officers laugh), cardboard box (`Player.boxed`, `hidden()`, `B_BOX`/C, `PF2_BOX`/`PF2_HIDDEN`, in `speed_mult` so it predicts), steal the cop car while the officer is out (`Car.copcar`, `CX_COPCAR`, `HORN_SIREN`), chickens crossing the road (`CHICKEN`), mimes (`MIME`), stunt ramps (`mapgen.ramps`, cosmetic hang time `Car.air_t`, `CF_AIR`, `BN_BIGAIR`), money trucks (`V.ARMOURED`, `_money_hit`), pigeons and flying hats (client-only, fp.py).
  - **Fixed in passing:** v0.6's weapon clamp (`inp.weapon <= ARM_BLOCK`) meant keys 6/7 (banana, donuts) never worked from the keyboard; the snapshot now also sheds events (oldest kept) if it's still too big after peds and pickups.
- **Protocol VERSION 9, RELEASE 0.9.0:** arsenal is 10 bytes (`ARSENAL_LEN`: + whoopee count, + has-box); SELF optional block `SB_INSPECT`; trap kinds `TRAP_CELL`, `TRAP_DOOR`, `TRAP_WHOOPEE`; `PF2_BOX`, `PF2_HIDDEN`; `CX_COPCAR`, `CF_AIR`; `B_BOX`; NPC kinds `CHICKEN`, `MIME`; model `ARMOURED`; sounds up to `S_FEATHERS` (58); banner `BN_BIGAIR`.
- **Tests:** 199, all OK (v0.9 added `test_v09.py` and a `TestCells` class in `test_police.py`). Game-loop selftest about 51 fps.

### v0.8 (earlier this session)
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
- **Tests at v0.8:** 163.

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
2. By hand on a real PC: run `Chopped.exe --host`, then `Chopped.exe --join 127.0.0.1 --name TWO --fake-lag 150`. With prediction the joiner's own car should feel instant. Compare with `--no-predict`. With a third/fourth `--join`, check everyone actually gets their own bay and car.
   - v0.10 things to feel out: is a health bar too forgiving compared to the old one-hit WASTED (`BULLET_DAMAGE`, `HEALTH_REGEN_*`)? Do cops miss too often or not enough now (`COP_GUN_ACCURACY`, `OFFICER_GUN_ACCURACY`)? Does losing a cop around a corner actually feel possible (`COP_TRACK_LOSE_TIME`)? Is the 10-15 s phone-in window too generous or too tight to reach a witness in time (`PHONE_IN_DELAY`, `PHONE_IN_HEAT`)? Is 1-in-4 fair odds for cutting the wires, and is the penalty for guessing wrong scary enough (`ALARM_CUT_WIRES`, `ALARM_CUT_FAIL_HEAT`)? Does the automap feel right stretched to an ultrawide or a tiny window? Is `COPS_PER_DAY` too stingy on a long session?
   - v0.9 things to feel out: is the drift now too tight or still too loose (`DRIFT_ASSIST_*`, `HANDBRAKE_MU`, `TIRE_C`)? Are the cells too easy to walk out of (`CELL_PICK_TIME`, `GUARD_NOTICE_R`) or the guards too tough (`GUARD_GRIT`, `GUARD_DOWN_TIME`)? Is 70% for a whole car the right trade (`WHOLE_SALE_RATE`)? Is the cardboard box overpowered (`BOX_STILL_TIME`, `BOX_SPEED_MULT`)? Can you hit the ramps at speed without clipping the car park's kerb?
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
- **The sim modules must not import pygame:** `sim.py`, `physics.py`, `brawl.py`, `garage.py`, `police.py`, `sillies.py`, `quests.py`, `entities.py`, `enums.py`, `vehicles.py`, `parts.py`, `lines.py` (and the client-side pure modules `drivetrain.py`, `enginesynth.py`). They're the authoritative, testable simulation. (`tests/test_v09.py` checks this.)
- **All tuning numbers live in `chopped/config.py`**, each with a comment explaining why.
- **Bump `config.VERSION`** whenever the wire protocol changes. Clients with a different version get rejected politely.
- **Keep packets under `MAX_PACKET` (1150 bytes).** `tests/test_misc.py` checks a worst-case snapshot, rush-hour traffic included.
- **Movement and collision code lives in `physics.Physics`** (`_drive`, `_car_vs_world`, `_car_pair`, `_walk`, `_fall`, `_body_vs_*`; `sim.Physics` is the same class). The client's `predict.Predictor` inherits the same class. If the server's physics reads anything the client doesn't get, prediction silently diverges. Anything new that affects your own movement must go in the SELF block (`protocol.encode_self`). `tests/test_predict.py` fails loudly if the two drift apart.
- **Run the tests before claiming anything works:**
  ```
  set SDL_VIDEODRIVER=dummy & set SDL_AUDIODRIVER=dummy & python -m unittest discover -s tests -v
  ```
  (On Linux/macOS: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m unittest discover -s tests -v`.) At handoff (session 2, RELEASE 0.11.0): **233 tests, all OK**, and the game-loop selftest ran at about 45-52 fps.

## 3. Architecture (details in README.md)
- `main.py` is the command line: `--host`, `--join IP[:PORT]`, `--server` (headless), `--selftest`, `--port`, `--name`, `--mute`, `--no-upnp`, `--log FILE`, `--fake-lag MS`, `--no-predict`.
- **Networking model (protocol VERSION 11):**
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
- **v0.9 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **Cells:** two, in the lockup's back corners. Picking the lock takes 7 s and is silent; punching the door takes 6 punches and alerts the guards. Guards only fight prisoners who are out of their cells *and* have been noticed. Bail works from the cell with X (so the solo escape hatch is still there).
  - **Guards:** 4 knockdowns (the key guard 6), back up after 3 s, only one engages at a time, 1.5 s get-up grace for everyone (brawling peds too).
  - **Selling whole** pays 70% of the parts + the $150 shell, +$400 for a complete sports car / muscle car / rice rocket, +$250 for a complete 4x4. The trunk's contents are spilled for you to keep, not sold.
  - **Inspect** shows the parts value rounded to $10, and hints at trunk loot, clown cars and angry owners. It works on traffic too.
  - **The shop door** covers the whole 28 m front (it's drawn as seven bays), starts open, and resets open on SHOP SEIZED. It blocks sight for witnesses both ways. Delivering still needs the car inside the yellow line, so you have to open it to deliver.
  - **Parked cars never knock you over** on foot. Car hits carry you at the car's speed and skid you for 2.5 s.
  - **Rubber chicken:** no heat, no rap sheet. **Stealing a cop car:** +30 heat and a "STEALING A POLICE CAR" charge. **Money truck:** +25 heat when the doors burst. **Big air** pays $40/s even if you crash on landing.
  - **Ramps are cosmetic:** the car's physics stay on the ground (so prediction needs nothing new), it's drawn in the air.
- **v0.8 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **"lose a/x % of your money"** was read as: the crew loses `DEATH_LOSS` (50%) divided by the number of players (50% solo, 25% for two, 12.5% for four). If he meant each player's full share (100% / players), set `DEATH_LOSS = 1.0`.
  - **When cops go lethal:** only after the crew fires a gun within `COP_HEAR_RANGE` (55 m) of any cop or officer, or hits a cop/cop car with a bullet; it lasts `LETHAL_TIME` (45 s) and refreshes on every shot. The v0.7 "cops shoot at 75 heat" rule is gone (tasers from 50 heat instead).
  - **Dying keeps your guns** (the cash is the penalty); **busted still confiscates them.**
  - **Jail has three ways out besides fighting:** a crewmate picks the lock (6 s), a car rams the gate (>= 9 m/s delta-v), or bail ($250 + $100 per previous arrest this run). Bail is there so a solo player who keeps losing to the guards isn't stuck forever.
  - **Jailbreak costs +40 heat** and the jumpsuit makes you a wanted target even at 0 heat until you reach the shop.
  - **Traffic bail behaviour and everything else in the heat model is unchanged.**
  - Drift assist is on for every player-driven car; AI cars keep their traction control instead.
- **v0.10 decisions, flagged for Bryce** (all tunable in `config.py`):
  - **"ambulance comes to pick them up"** was built the same way towing already works in this game: a siren sound and a toast, not a drivable ambulance that pathfinds to the body. There's no precedent anywhere else in Chopped for a vehicle that exists purely to visit a scene and leave (towed cars just vanish with a toast too), so a whole new pathfinding NPC-vehicle felt like scope creep for one flavour line. Easy to build properly later if he wants the spectacle.
  - **A clean wire-cut spares you the angry owner** (they only come running if they actually heard or saw you) but a clown car still bursts open regardless -- that one's a joke, not a stealth mechanic, so it fires either way.
  - **Once a witness has "made up their mind" to call** (`NPC.phoned` flips true the instant `call_t` is armed), losing sight of them again doesn't cancel the call -- only killing them does. This was the more literal reading of "kill civilians to make sure no witness remains": ducking around a corner isn't enough, you have to actually deal with them.
  - **The crew compass** (`doomhud._crew_compass`) only shows a teammate who's more than 10 m away *and* either off-screen or beyond 60 m -- close enough to just look at them, it says nothing. Builder's call on both thresholds.
  - **The automap's window-scaling is automap-only.** First-person keeps the old integer-only scale on purpose: chunky pixels matter more when you're looking at them up close than they do on a schematic top-down overview.
  - **No new vehicle model for the ambulance/chopper** -- both are witness/heat mechanics and sound, same scope decision as above.
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

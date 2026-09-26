"""
savefile.py -- persisting the crew's progress across sessions: cash, the day
and rent clock, the shared parts locker, and each player's own car, by name
(a player id is just whichever slot they happened to connect into this
session, not a stable identity -- the name they typed is).

Deliberately NOT saved: heat, cops, traffic, pedestrians, anyone's position
or what they're carrying. Loading a save always starts the crew back at the
shop on a quiet morning, not mid-chase -- see CLAUDE.md's decision log.

Story points, the act and which jobs have ever been completed persist like
the economy does; today's 3 rotated jobs and whatever's mid-progress on them
don't -- those reset fresh on load, the same way heat always does.

No pygame, stdlib json only -- same "no extra dependencies" rule as
everywhere else in this game. Never raises: a missing, corrupt or foreign
save just means the host starts a fresh run, same as it always has.
"""

import json
import os
import time

from .enums import PERSONAL
from .parts import Part, SLOTS

SAVE_VERSION = 1   # bump if this file's shape changes; an old save is skipped, not crashed on


def _part_to_json(part):
    return None if part is None else [part.type_id, part.condition, part.style]


def _part_from_json(data):
    if not data:
        return None
    type_id, condition, style = data
    return Part(type_id, condition, style)


def _car_to_json(car):
    return {
        "model": car.model, "color": car.color,
        "parts": {slot: _part_to_json(car.parts.get(slot)) for slot in SLOTS},
        "livery": car.livery, "horn_type": car.horn_type, "glow": car.glow,
        "nos": car.nos, "ejector": car.ejector, "gnome": car.gnome, "hydraulics": car.hydraulics,
    }


def dump(world):
    """The world's progress as a JSON-safe dict. See the module docstring for scope."""
    cars = {}
    for car in world.cars.values():
        if car.kind != PERSONAL:
            continue
        name = world.bay_owner_name.get(car.bay)
        if name is not None:
            cars[name] = _car_to_json(car)
    return {
        "save_version": SAVE_VERSION,
        "cash": world.cash, "day": world.day, "day_t": world.day_t, "run": world.run,
        "stash": [_part_to_json(p) for p in world.stash],
        "cars": cars,
        # (quests) reputation and act persist like the economy does; today's rotation and
        # whatever's mid-progress don't -- those reset fresh on load, same as heat does.
        "story_points": world.story_points, "act": world.act, "campaign_won": world.campaign_won,
        "completed_ever": sorted(world.completed_ever),
        # (v0.12) which shops the crew owns -- rent (World.rent_due) is computed from this,
        # so losing it on load would quietly refund every fence the crew ever bought.
        "shop_owned": list(world.shop_owned),
        # (v0.12.1) the city itself. shop_owned is a list of lot INDICES, which only mean
        # anything in the city they were bought in -- load them into a fresh random city
        # and the crew wakes up owning somebody else's warehouse. Also: your city, back.
        "map_seed": world.map_seed,
    }


def apply(world, data):
    """Mutates `world` in place with a previously-dumped save. Cars aren't
    swapped in here -- nobody's joined yet at load time, so there's no bay to
    put them in -- they're queued on `world._pending_car_mods`, keyed by
    name, and claimed by World.add_player the moment that name reconnects."""
    if not isinstance(data, dict) or data.get("save_version") != SAVE_VERSION:
        return False
    world.cash = data.get("cash", world.cash)
    world.day = max(1, int(data.get("day", world.day)))
    world.day_t = max(1.0, float(data.get("day_t", world.day_t)))
    world.run = max(1, int(data.get("run", world.run)))
    world.stash = [p for p in (_part_from_json(x) for x in data.get("stash", [])) if p is not None]
    world._pending_car_mods = dict(data.get("cars", {}))
    world.story_points = max(0, int(data.get("story_points", world.story_points)))
    world.act = max(1, min(3, int(data.get("act", world.act))))
    world.campaign_won = bool(data.get("campaign_won", world.campaign_won))
    world.completed_ever = set(data.get("completed_ever", [])) | world.completed_ever
    saved_shops = data.get("shop_owned")
    if isinstance(saved_shops, list):
        for i in range(1, len(world.shop_owned)):    # shop 0 (home base) is always owned
            if i < len(saved_shops):
                world.shop_owned[i] = bool(saved_shops[i])
    world._rotate_quests()   # a fresh day's 3, now that story points may have unlocked more
    return True


def load_into(world, path):
    """Best-effort load: a missing file is the normal "first time hosting"
    case, and anything unreadable is treated the same way rather than taking
    the host down over a corrupt save."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return apply(world, data)


def save_to(world, path):
    """Written to a temp file and swapped in, so a crash halfway through a save
    leaves the previous save intact instead of half a JSON file."""
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dump(world), f)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- (v0.12.1) slots
def save_dir():
    """Where the main menu's save slots live. %APPDATA%\\Chopped\\saves on Windows
    (next to the exe would be friendlier, but that breaks the day somebody runs it
    out of Program Files or a read-only USB stick), ~/.local/share/chopped/saves
    elsewhere. CHOPPED_SAVE_DIR overrides it (the tests use that)."""
    env = os.environ.get("CHOPPED_SAVE_DIR")
    if env:
        return env
    if os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "Chopped", "saves")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "chopped", "saves")


def slot_path(n):
    return os.path.join(save_dir(), "slot%d.json" % n)


def peek(path):
    """A save's headline numbers for the menu, without touching a world:
    {"day", "cash", "act", "rep", "crew", "map_seed", "age"} -- or None if
    there's nothing (valid) there."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("save_version") != SAVE_VERSION:
            return None
        return {"day": int(data.get("day", 1)), "cash": int(data.get("cash", 0)),
                "act": int(data.get("act", 1)), "rep": int(data.get("story_points", 0)),
                "crew": sorted(data.get("cars", {})), "map_seed": data.get("map_seed"),
                "age": max(0.0, time.time() - os.path.getmtime(path))}
    except (OSError, ValueError, TypeError):
        return None


def wipe(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False

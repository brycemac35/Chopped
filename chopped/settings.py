"""
settings.py -- the player's own settings (FOV, render scale, volumes, name, character).

Client-side only: nothing here touches the sim or the wire. Stored as JSON at
%APPDATA%\\Chopped\\settings.json (next to the saves folder). CHOPPED_SAVE_DIR, which the
tests set, redirects it into that directory instead so a test run never touches the real file.
A missing or corrupt file just means defaults.
"""

import json
import os

from . import config as C
from . import savefile as SF

NAME_MAX = 12          # same cap as the menu's name field
CHAR_MAX = 3           # 4 crooks (ui.roster); clamped again by the menu against the real roster


def settings_path():
    env = os.environ.get("CHOPPED_SAVE_DIR")
    if env:
        return os.path.join(env, "settings.json")
    return os.path.join(os.path.dirname(SF.save_dir()), "settings.json")


def _num(v, lo, hi, default):
    """A number in [lo, hi] as an int; anything unusable (None, text, NaN, bool) is the default."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return default
    return int(max(lo, min(hi, round(v))))


def defaults():
    return {"fov": int(C.FP_FOV), "render_scale": C.RENDER_SCALE_DEFAULT,
            "master": C.VOL_MASTER_DEFAULT, "music": C.VOL_MUSIC_DEFAULT,
            "sfx": C.VOL_SFX_DEFAULT, "engine": C.VOL_ENGINE_DEFAULT,
            "name": "", "char": None}


def sanitize(data):
    """Any dict (or junk) -> a complete, in-range settings dict."""
    d = defaults()
    if not isinstance(data, dict):
        return d
    d["fov"] = _num(data.get("fov"), C.FOV_MIN, C.FOV_MAX, d["fov"])
    d["render_scale"] = _num(data.get("render_scale"), C.RENDER_SCALE_MIN, C.RENDER_SCALE_MAX, d["render_scale"])
    for k in ("master", "music", "sfx", "engine"):
        d[k] = _num(data.get(k), 0, 100, d[k])
    name = data.get("name")
    if isinstance(name, str):
        d["name"] = "".join(c for c in name.upper() if c.isalnum() or c in "-_ ")[:NAME_MAX].strip()
    ch = data.get("char")
    if isinstance(ch, int) and not isinstance(ch, bool):
        d["char"] = max(0, min(CHAR_MAX, ch))
    return d


def load(path=None):
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as f:
            return sanitize(json.load(f))
    except (OSError, ValueError):
        return defaults()


def save(data, path=None):
    """Atomic write (temp file, then replace). True if it landed."""
    path = path or settings_path()
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sanitize(data), f, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def volumes(d):
    """(master, music, sfx, engine) as 0..1 floats, the set_volumes() contract."""
    return tuple(d[k] / 100.0 for k in ("master", "music", "sfx", "engine"))

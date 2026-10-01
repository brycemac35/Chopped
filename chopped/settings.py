"""
settings.py -- the player's own settings (FOV, render scale, volumes, name, character).

Client-side only: nothing here touches the sim or the wire. Stored as JSON at
%APPDATA%\\Chopped\\settings.json (next to the saves folder). CHOPPED_SAVE_DIR, which the
tests set, redirects it into that directory instead so a test run never touches the real file.
A missing or corrupt file just means defaults.
"""

import json
import os
import time

from . import config as C
from . import savefile as SF

NAME_MAX = 12          # same cap as the menu's name field
CHAR_MAX = 3           # 4 crooks (ui.roster); clamped again by the menu against the real roster
SERVERS_MAX = 8        # (v0.19) remembered hosts, most recent first: enough to be useful, short enough to fit under the JOIN field
ADDR_MAX = 60          # same cap as the menu's JOIN field
RENDERERS = ("3d", "classic")   # (v0.20) the RENDERER setting's values, in the settings screen's button order
ADDR_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-"   # what the JOIN field accepts


def settings_path():
    env = os.environ.get("CHOPPED_SAVE_DIR")
    if env:
        return os.path.join(env, "settings.json")
    return os.path.join(os.path.dirname(SF.save_dir()), "settings.json")


def _num(v, lo, hi, default):
    """A number in [lo, hi] as an int; anything unusable (None, text, NaN, +-Infinity, bool) is the default."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return default
    return int(max(lo, min(hi, round(v))))


def _world_range():
    """(lo, hi, default) for WORLD DETAIL; getattr fallbacks until config.py has the names."""
    return (getattr(C, "WORLD_SCALE_MIN", 1), getattr(C, "WORLD_SCALE_MAX", 3),
            getattr(C, "WORLD_SCALE_DEFAULT", 1))


def norm_addr(text):
    """What to store for something typed in the JOIN field: trimmed, junk removed, and the default
    port dropped, so 'host' and 'host:PORT' are one entry. '' if nothing usable is left."""
    if not isinstance(text, str):
        return ""
    t = "".join(c for c in text.strip() if c in ADDR_CHARS)[:ADDR_MAX]
    if t.count(":") == 1:
        host, port = t.split(":")
        if port == str(C.DEFAULT_PORT):
            t = host
    return t.strip(":")


def _clean_name(name):
    if not isinstance(name, str):
        return ""
    return "".join(c for c in name.upper() if c.isalnum() or c in "-_ ")[:NAME_MAX].strip()


def _clean_servers(v):
    """A list of {addr, name?, last}; junk entries dropped, duplicates (any case) merged keeping the
    most recent, newest first, at most SERVERS_MAX."""
    if not isinstance(v, list):
        return []
    items = []
    for e in v:
        if isinstance(e, str):
            e = {"addr": e}
        if not isinstance(e, dict):
            continue
        addr = norm_addr(e.get("addr"))
        if not addr:
            continue
        out = {"addr": addr, "last": _num(e.get("last"), 0, 4102444800, 0)}
        nm = _clean_name(e.get("name"))
        if nm:
            out["name"] = nm
        items.append(out)
    items.sort(key=lambda e: -e["last"])          # (stable: an equal time keeps the file's order)
    seen, res = set(), []
    for e in items:
        k = e["addr"].lower()
        if k not in seen:
            seen.add(k)
            res.append(e)
    return res[:SERVERS_MAX]


def remember_server(servers, addr, name=None, now=None):
    """A new list with `addr` at the front (an old entry for it is replaced; its name is kept if
    we weren't given one). Call it only after a REAL connection, not for typos."""
    addr = norm_addr(addr)
    if not addr:
        return list(servers)
    old = next((e for e in servers if e.get("addr", "").lower() == addr.lower()), None)
    e = {"addr": addr, "last": int(time.time() if now is None else now)}
    nm = _clean_name(name) or (old or {}).get("name", "")
    if nm:
        e["name"] = nm
    return _clean_servers([e] + [x for x in servers if x is not old])


def defaults():
    return {"fov": int(C.FP_FOV), "render_scale": C.RENDER_SCALE_DEFAULT,
            "master": C.VOL_MASTER_DEFAULT, "music": C.VOL_MUSIC_DEFAULT,
            "sfx": C.VOL_SFX_DEFAULT, "engine": C.VOL_ENGINE_DEFAULT,
            "name": "", "char": None,
            "world_scale": getattr(C, "WORLD_SCALE_DEFAULT", 1), "servers": [],
            "mouse_sens": C.MOUSE_SENS_DEFAULT, "invert_y": False,
            "renderer": getattr(C, "RENDERER_DEFAULT", "3d")}


def mouse_mult(d):
    """The MOUSE SENSITIVITY slider as a multiplier (1.0 = the tuned feel), clamped."""
    return _num(d.get("mouse_sens"), C.MOUSE_SENS_MIN, C.MOUSE_SENS_MAX, C.MOUSE_SENS_DEFAULT) / 100.0


def yaw_delta(d, rel):
    """Radians of turn for `rel` mouse counts sideways (mouse-look yaw and the chase-cam orbit)."""
    return rel * C.MOUSE_SENS * mouse_mult(d)


def pitch_delta(d, rely, view_h):
    """Change in the pitch shear (view pixels) for `rely` mouse counts down. Normally mouse up looks
    up (rely < 0 -> positive); INVERT Y flips it, flight-stick style."""
    sign = -1.0 if d.get("invert_y") is True else 1.0
    return -rely * C.MOUSE_PITCH_SENS * view_h * mouse_mult(d) * sign


def sanitize(data):
    """Any dict (or junk) -> a complete, in-range settings dict."""
    d = defaults()
    if not isinstance(data, dict):
        return d
    d["fov"] = _num(data.get("fov"), C.FOV_MIN, C.FOV_MAX, d["fov"])
    d["render_scale"] = _num(data.get("render_scale"), C.RENDER_SCALE_MIN, C.RENDER_SCALE_MAX, d["render_scale"])
    for k in ("master", "music", "sfx", "engine"):
        d[k] = _num(data.get(k), 0, 100, d[k])
    lo, hi, dflt = _world_range()
    d["world_scale"] = _num(data.get("world_scale"), lo, hi, d["world_scale"])
    d["mouse_sens"] = _num(data.get("mouse_sens"), C.MOUSE_SENS_MIN, C.MOUSE_SENS_MAX, d["mouse_sens"])
    d["invert_y"] = data.get("invert_y") is True        # (only a real true; "yes" or 1 is junk)
    d["servers"] = _clean_servers(data.get("servers"))
    if data.get("renderer") in RENDERERS:              # (v0.20) "3d" or "classic"; anything else: the default
        d["renderer"] = data["renderer"]
    d["name"] = _clean_name(data.get("name"))
    ch = data.get("char")
    if isinstance(ch, int) and not isinstance(ch, bool):
        d["char"] = max(0, min(CHAR_MAX, ch))
    return d


def load(path=None):
    try:
        with open(path or settings_path(), "r", encoding="utf-8-sig") as f:     # (-sig: Notepad's BOM)
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

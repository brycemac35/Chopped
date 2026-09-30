"""
soundscape.py (v0.18) -- the client-side rules of the mix, kept free of pygame so they're testable:

  * HornBudget: traffic honks become short beeps under a global budget (a jam is a murmur, not a wall)
  * Occluder:   the shop's dead zone. Listener in the shop with every door shut = the outside is silent
                (and the other way round); open a door and it comes back, faded over DEADZONE_FADE
  * pan():      left/right balance from the listener's yaw

audio.py does the actual playing. Everything here is cosmetic and client-only: nothing rides the wire.
"""

import math

from . import config as C
from .enums import TRAP_DOOR

# semitone-ish pitch steps for the traffic beeps (a fleet of slightly different horns)
HORN_PITCHES = (0.84, 0.90, 0.95, 1.0, 1.07, 1.14)
# beep kinds: 0 = short tap, 1 = long blast, 2 = double tap
HORN_KINDS = 3


def _hash(n):
    return (int(n) * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF


def car_horn_voice(car_id):
    """(pitch index, favourite kind, cooldown seconds) for a car: fixed by its id, so the
    same car always sounds like the same car."""
    h = _hash(car_id)
    lo, hi = C.HORN_CAR_COOLDOWN
    return h % len(HORN_PITCHES), (h >> 8) % HORN_KINDS, lo + (hi - lo) * (((h >> 16) & 255) / 255.0)


class HornBudget:
    """Decides which honking traffic cars get to be heard this frame.

    step(now, honkers) takes [(car_id, distance_m)] for every traffic car whose horn flag is up
    and returns the honks to play: [(car_id, gain, pitch_idx, kind)]. Rules: only cars inside
    HORN_HEAR_DIST count; each car has a cooldown; at most HORN_BUDGET_MAX honks in any
    HORN_BUDGET_WINDOW seconds and HORN_MIN_GAP between two; nearest car wins the slot."""

    def __init__(self):
        self.log = []          # times honks were granted
        self.next_ok = {}      # car id -> earliest time it may honk again
        self.count = {}        # car id -> honks so far (varies its kind)

    def step(self, now, honkers):
        cut = now - C.HORN_BUDGET_WINDOW
        self.log = [t for t in self.log if t > cut]
        live = {cid for cid, _d in honkers}
        for cid in [k for k in self.next_ok if k not in live and self.next_ok[k] < now]:
            del self.next_ok[cid]                      # stopped honking and cooled off: forget it
            self.count.pop(cid, None)
        out = []
        for cid, d in sorted(honkers, key=lambda h: h[1]):
            if d >= C.HORN_HEAR_DIST or self.next_ok.get(cid, 0.0) > now:
                continue
            if len(self.log) >= C.HORN_BUDGET_MAX or (self.log and now - self.log[-1] < C.HORN_MIN_GAP):
                break
            pitch, kind, cool = car_horn_voice(cid)
            n = self.count.get(cid, 0)
            if n % 3 == 2:
                kind = (kind + 1) % HORN_KINDS         # every third honk is a different one: leaning, not looping
            self.count[cid] = n + 1
            self.next_ok[cid] = now + cool
            self.log.append(now)
            gain = C.HORN_BLAST_VOL * max(0.0, 1.0 - d / C.HORN_HEAR_DIST) ** C.HORN_FALLOFF_EXP
            out.append((cid, gain, pitch, kind))
        return out


def pan(lx, ly, yaw, sx, sy):
    """-1 (hard left) .. +1 (hard right) for a source at (sx, sy) heard from (lx, ly) facing yaw.
    Right-hand side is (-sin yaw, cos yaw), same as the raycaster. Sources within 2 m sit centred."""
    dx, dy = sx - lx, sy - ly
    d = math.hypot(dx, dy)
    if d < 2.0:
        return 0.0
    lat = (-dx * math.sin(yaw) + dy * math.cos(yaw)) / d
    return max(-1.0, min(1.0, lat)) * min(1.0, (d - 2.0) / 8.0)


def lr(vol, p):
    """(left, right) channel volumes for a level and a pan: only the far ear ever drops."""
    p *= C.PAN_STRENGTH
    return vol * (1.0 - max(0.0, p)), vol * (1.0 - max(0.0, -p))


class Occluder:
    """The shop dead zone. update() once a frame with the listener and the door traps the snapshot
    carries; factor(x, y) then says how much of a source's level reaches the listener."""

    def __init__(self):
        self.doors = {}                # door index -> last seen open fraction (0 shut .. 1 up)
        self.leak = 1.0                # smoothed share of the outside let through
        self.zone = 0                  # 1 = listener is in the home shop
        self._cmap = None

    def open_sum(self):
        n = len(C.DOOR_COLS)
        return sum(self.doors.get(i, 1.0) if self.doors.get(i, 1.0) > C.DEADZONE_DOOR_SHUT else 0.0
                   for i in range(n))

    def target(self):
        return min(1.0, C.DEADZONE_LEAK_PER_DOOR * self.open_sum())

    def update(self, cmap, lx, ly, traps, dt):
        self._cmap = cmap
        for t in (traps or {}).values():
            if t[1] == TRAP_DOOR:
                i = t[0] - C.DOOR_ID
                if 0 <= i < len(C.DOOR_COLS):
                    self.doors[i] = float(t[5])
        self.zone = 1 if cmap is not None and cmap.in_garage(lx, ly) else 0
        goal = self.target()
        step = max(0.0, dt) / max(1e-3, C.DEADZONE_FADE)
        self.leak = min(goal, self.leak + step) if goal > self.leak else max(goal, self.leak - step)

    def factor(self, sx, sy):
        """1 = same side of the wall as the listener; otherwise whatever the doors let through."""
        if self._cmap is None:
            return 1.0
        z = 1 if self._cmap.in_garage(sx, sy) else 0
        return 1.0 if z == self.zone else self.leak

    def sealed(self):
        return self.leak <= 0.001

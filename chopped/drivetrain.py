"""
drivetrain.py -- revs, gears and boost, for the tachometer and the engine
note (v0.8). None of this touches the physics: the car goes exactly as fast as
the tyre model says, and this works out what the engine would be doing to get
there. That makes it purely client-side and free to be theatrical -- the
needle bounces off the limiter in a brake stand, the turbo spools up late and
sneezes when you lift, a VTEC engine changes its whole personality at 5,600.

No pygame in here: tests poke it directly.
"""

import math

from . import config as C
from . import enginesynth as ES
from .parts import (ENGINE_SPECS, NO_ENGINE_SPEC, ASP_NA, ASP_TURBO, ASP_SC, V_ELECTRIC, V_VTEC,
                    V_DIESEL)

# car-row "engine byte": voice (4 bits) | aspiration << 4 | gearbox code << 6
GEARBOX_CODES = (0, 4, 5, 6)          # code -> gear count (0 = single speed: scooters, electrics)


def engine_byte(voice, asp, gears):
    code = GEARBOX_CODES.index(gears) if gears in GEARBOX_CODES else 2
    return (voice & 15) | ((asp & 3) << 4) | (code << 6)


def unpack_engine_byte(b):
    return b & 15, (b >> 4) & 3, GEARBOX_CODES[(b >> 6) & 3]


def voice_spec(voice, asp):
    """(redline, idle) for a voice as the car row describes it (the row doesn't say
    WHICH V8, so we take the first engine in the catalogue that matches)."""
    for (v, a, red, idle) in ENGINE_SPECS.values():
        if v == voice and a == asp:
            return red, idle
    for (v, a, red, idle) in ENGINE_SPECS.values():
        if v == voice:
            return red, idle
    return NO_ENGINE_SPEC[2], NO_ENGINE_SPEC[3]


class Tacho:
    """One engine's worth of revs. update() once per frame with what the car
    is doing; read rpm / gear / boost. Events (shift, lift-off, VTEC) come
    back from update() as a tuple of strings for the audio to act on."""

    def __init__(self, voice=0, asp=ASP_NA, gears=5):
        self.set_engine(voice, asp, gears)
        self.gear = 1
        self.rpm = float(self.idle)
        self.boost = 0.0              # 0..1 turbo pressure / supercharger speed
        self.shift_t = 0.0            # > 0: mid-shift, throttle cut
        self.prev_thr = 0.0
        self.vtec = False             # above the cam changeover?
        self.limiter_t = 0.0
        self.load = 0.0               # smoothed engine load 0..1: throttle, minus the throttle cut mid-shift
        self.turbo_n = 0.0            # turbine speed 0..1 (lags the revs; coasts down slowly)
        self.bov_level = 0.0          # boost the last "bov" event dumped (how big a pssh)

    def set_engine(self, voice, asp, gears):
        self.voice, self.asp = voice, asp
        self.gears = max(0, gears)
        self.redline, self.idle = voice_spec(voice, asp)
        if voice == V_ELECTRIC:
            self.idle = 0

    def gear_top(self, top, g):
        """Road speed at the redline in gear g. Short gears low down, tall at the top."""
        n = max(1, self.gears)
        return top * (g / float(n)) ** C.GEAR_SPREAD * C.GEAR_TOP_OVERRUN

    def update(self, speed, throttle, top, spin=0.0, burnout=False, dt=1 / 60.0):
        events = []
        red, idle = self.redline, self.idle
        thr = max(0.0, throttle)
        top = max(5.0, top)
        if self.gears == 0:
            # single speed: revs follow the wheels, all the way up
            target = idle + (red - idle) * min(1.0, speed / top)
            self.gear = 1
        else:
            if self.shift_t > 0:
                self.shift_t -= dt
            g = max(1, min(self.gears, self.gear))
            vg = self.gear_top(top, g)
            target = red * speed / vg
            # the box shifts itself (it's an automatic now. Don't tell the purists.)
            if target > red * C.SHIFT_UP_AT and g < self.gears and thr > 0.1 and not burnout:
                self.gear = g + 1
                self.shift_t = C.SHIFT_TIME
                events.append("shift")
            elif g > 1 and speed < self.gear_top(top, g - 1) * C.SHIFT_DOWN_AT:
                self.gear = g - 1
            # pulling away: the clutch slips, so revs sit mid-range rather than at idle
            launch = idle + (red * C.LAUNCH_REVS - idle) * thr
            if self.gear == 1 and target < launch:
                target = launch
        if burnout or spin > 0.3:
            # wheels spinning: bang off the limiter
            target = red * (0.94 + 0.06 * min(1.0, spin if not burnout else 1.0))
        target = max(idle, min(red * 1.02, target))
        if thr < 0.05 and not burnout and spin <= 0.3:
            target = max(idle, min(target, red * 0.98))
        if self.shift_t > 0:
            target *= 0.72                     # the dip between gears
        k = min(1.0, (C.REV_RISE if target > self.rpm else C.REV_FALL) * dt)
        self.rpm += (target - self.rpm) * k
        # the rev limiter: a proper bounce, not a flat line
        if self.rpm >= red * 0.995:
            self.limiter_t += dt
            if self.limiter_t > C.LIMITER_PERIOD:
                self.limiter_t = 0.0
                self.rpm = red * 0.93
                events.append("limiter")
        # engine load: the intake manifold fills and empties, and a shift cuts the throttle
        cut = 0.0 if (self.shift_t > 0 or self.rpm >= red * 0.995) else thr
        lk = min(1.0, (C.ENGINE_LOAD_ATTACK if cut > self.load else C.ENGINE_LOAD_RELEASE) * dt)
        self.load += (cut - self.load) * lk
        # boost
        if self.asp == ASP_TURBO:
            frac = min(1.0, self.rpm / red)
            # the turbine is driven by exhaust ENERGY = flow (rpm) x pressure (load). It has inertia,
            # so it spools up over ~1 s and, with the flow gone, coasts down over ~2: the whistle
            # follows THIS, not the throttle. Below ~20% of the redline there's nothing to spin it.
            flow = min(1.0, max(0.0, (frac - 0.2) / 0.6))
            drive = self.load * (0.15 + 0.85 * flow) + (1.0 - self.load) * 0.12 * frac
            if burnout:
                drive = 0.9
            rate = C.TURBO_SPOOL if drive > self.turbo_n else C.TURBO_COAST
            self.turbo_n += (drive - self.turbo_n) * min(1.0, rate * dt)
            # pressure: whatever the turbine can push, while the throttle is open; vented when you lift
            want = thr * self.turbo_n
            if burnout:
                want = 0.9
            rate = C.TURBO_BOOST_RISE if want > self.boost else C.TURBO_DUMP
            self.boost += (want - self.boost) * min(1.0, rate * dt)
            if self.prev_thr > 0.5 and thr < 0.1 and self.boost > 0.4:
                events.append("bov")
                self.bov_level = self.boost
                self.boost *= 0.3
        elif self.asp == ASP_SC:
            self.boost = min(1.0, self.rpm / red)
            self.turbo_n = 0.0
        else:
            self.boost = 0.0
            self.turbo_n = 0.0
        if self.prev_thr > 0.5 and thr < 0.1 and self.rpm > red * 0.6:
            events.append("lift")               # (pops and bangs, on cars that have them)
        if self.voice == V_VTEC:
            on = self.rpm > red * C.VTEC_AT
            if on and not self.vtec:
                events.append("vtec")
            self.vtec = on
        self.prev_thr = thr
        return tuple(events)

    def frac(self):
        return self.rpm / float(self.redline) if self.redline else 0.0

    def induction(self):
        """What the forced induction sounds like right now: (kind, whine Hz, level 0..1, air 0..1),
        or None for a naturally aspirated engine.
        TURBO: the whistle is the compressor's blade-pass frequency, proportional to TURBINE speed
        (turbo_n, which lags the revs), and it's quieter as the compressor unloads off the throttle;
        the airflow rush follows mass flow (turbine speed x load).
        SUPERCHARGER: a belt drives it, so no lag at all: the whine is exactly crank speed x pulley
        ratio x lobes, and it gets louder as the throttle opens."""
        if self.asp == ASP_TURBO:
            n = self.turbo_n
            hz = C.TURBO_HZ_TOP * n
            level = n ** 2.2 * (0.45 + 0.55 * self.load)
            air = n * (0.2 + 0.8 * self.load) * 0.8
            return "turbo", hz, level, air
        if self.asp == ASP_SC:
            frac = min(1.0, self.rpm / float(self.redline))
            return "sc", ES.sc_hz(self.rpm), frac ** 1.2 * (0.25 + 0.75 * self.load), 0.35 * self.load * frac
        return None


def is_diesel(voice):
    return voice == V_DIESEL


def layout_span(voice, redline=None):
    """(idle, redline) covering every catalogue engine that shares this voice's layout."""
    lname = ES.layout_name(voice, redline or 0)
    specs = [sp for sp in ENGINE_SPECS.values() if sp[0] == voice and ES.layout_name(voice, sp[2]) == lname]
    red = max((sp[2] for sp in specs), default=7000)
    idle = min((sp[3] for sp in specs if sp[3] > 0), default=800)
    if voice == V_ELECTRIC:
        idle = 600
    return idle, red


def band_rpms(voice, redline=None):
    """The rpm points each engine layout is pre-rendered at (the audio crossfades between
    neighbours). Spread evenly on a log scale from idle to past the redline. `redline` picks the
    layout when a voice id covers several engines (the bikes are V_I4 too)."""
    idle, red = layout_span(voice, redline)
    n = C.ENGINE_BANDS
    lo, hi = math.log(idle), math.log(red * 1.03)
    return [math.exp(lo + (hi - lo) * i / (n - 1)) for i in range(n)]


def band_weights(rpms, rpm):
    """(i, weight_i, j, weight_j): the two bands either side of rpm."""
    if rpm <= rpms[0]:
        return 0, 1.0, 1, 0.0
    for i in range(len(rpms) - 1):
        if rpm <= rpms[i + 1]:
            w = (rpm - rpms[i]) / (rpms[i + 1] - rpms[i])
            return i, 1.0 - w, i + 1, w
    n = len(rpms)
    return n - 2, 0.0, n - 1, 1.0

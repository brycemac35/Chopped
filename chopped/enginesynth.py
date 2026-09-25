"""
enginesynth.py -- engine notes from first principles-ish (v0.8, Bryce: "better
engine sounds", "turbo noises on the cars with turbos", "super chargers").

An engine is a row of explosions. Each cylinder firing is a thump that rings
at the exhaust's resonant pitch and dies away; a four-stroke fires every
cylinder once per two revolutions. So a 4-cylinder at 3,000 rpm thumps 100
times a second and an 8-cylinder 200 -- and a cross-plane V8 doesn't space
them evenly, which is where the burble comes from. We render each engine
voice at ENGINE_BANDS rpm points, every loop a whole number of engine cycles
long so it repeats without a click, and audio.py crossfades neighbours as
the revs move. A supercharger's whine is baked into its engine's loops (it's
belt-driven: its pitch IS the revs); a turbo's whistle is its own loop,
because it lags behind the revs and dies when you lift.

Pure Python, no pygame: returns lists of floats in -1..1.
"""

import math
import random

from .parts import (V_I4, V_I4T, V_ELECTRIC, V_V8, V_ROTARY, V_I6, V_DIESEL, V_V6, V_VTEC)
from . import config as C

LOOP_S = 0.3            # target loop length. Whole engine cycles, so it's never exactly this.


class Voice:
    """How one engine layout sounds.
    cyl: firings per engine cycle (2 revs); res: exhaust ring in Hz; decay: 1/s;
    rasp: noise in each thump (diesels clatter, rotaries buzz); body: the plain
    fundamental under it; pattern: relative loudness of successive firings (uneven
    = burble); lp: low-pass smoothing, 0..1 (1 = none)."""
    __slots__ = ("cyl", "res", "decay", "rasp", "body", "pattern", "lp", "gain")

    def __init__(self, cyl, res, decay, rasp, body, pattern, lp, gain=1.0):
        self.cyl, self.res, self.decay, self.rasp = cyl, res, decay, rasp
        self.body, self.pattern, self.lp, self.gain = body, pattern, lp, gain


VOICES = {
    V_I4: Voice(4, 230, 70, 0.18, 0.35, (1.0, 0.92, 0.97, 0.9), 0.55),
    V_I4T: Voice(4, 210, 60, 0.12, 0.4, (1.0, 0.95, 0.98, 0.93), 0.4),      # the turbo muffles it
    V_V8: Voice(8, 140, 42, 0.12, 0.5, (1.0, 0.62, 0.92, 0.55, 0.98, 0.7, 0.88, 0.6), 0.35, 1.1),
    V_ROTARY: Voice(4, 380, 95, 0.4, 0.25, (1.0, 0.85), 0.8),               # two rotors: brap
    V_I6: Voice(6, 280, 75, 0.1, 0.4, (1.0,) * 6, 0.45),                   # smooth as butter
    V_DIESEL: Voice(4, 150, 38, 0.6, 0.45, (1.0, 0.9, 1.0, 0.85), 0.5, 1.1),  # tractor energy
    V_V6: Voice(6, 200, 55, 0.14, 0.4, (1.0, 0.82, 0.95, 0.78, 1.0, 0.86), 0.45),
    V_VTEC: Voice(4, 240, 72, 0.18, 0.35, (1.0, 0.92, 0.97, 0.9), 0.55),
}
SC_WHINE = 0.42          # supercharger whine Hz per rpm (a belt-driven screw: ~2.8 kHz at 6,600)


def _lowpass_loop(x, k):
    """One-pole low-pass, run twice round the loop so the end joins the start."""
    if k >= 0.999:
        return x
    y = 0.0
    for v in x:
        y += (v - y) * k
    out = [0.0] * len(x)
    for i, v in enumerate(x):
        y += (v - y) * k
        out[i] = y
    return out


def _normalise(x, peak):
    m = max(1e-9, max(abs(v) for v in x))
    k = peak / m
    return [v * k for v in x]


def render_engine(voice, rpm, rate, supercharged=False, redline=7000, vtec_rpm=None, seed=0):
    """One loop of an engine at a steady rpm. Returns (samples, actual_rpm)."""
    rng = random.Random(seed * 1000 + int(rpm))
    if voice == V_ELECTRIC:
        return _render_electric(rpm, rate, redline), rpm
    v = VOICES.get(voice, VOICES[V_I4])
    cyc_n = max(8, int(round(120.0 / rpm * rate)))       # samples per engine cycle (two revolutions)
    rpm = 120.0 * rate / cyc_n                             # (the rpm we actually hit, to the sample)
    n_cyc = max(1, int(round(LOOP_S * rate / cyc_n)))
    n = n_cyc * cyc_n
    frac = min(1.0, rpm / redline)
    res, rasp, body, lp = v.res, v.rasp, v.body, v.lp
    if voice == V_VTEC and vtec_rpm and rpm >= vtec_rpm:
        # the second cam: harder, brighter, angrier. This is the bit people film.
        res, rasp, body, lp = res * 1.6, rasp + 0.2, body * 1.2, min(1.0, lp + 0.3)
    decay = v.decay * (0.7 + 0.8 * frac)                   # thumps get shorter as the revs rise...
    res *= 0.8 + 0.5 * frac                                # ...and the pipes sing a little higher
    interval = cyc_n / float(v.cyl)
    plen = int(min(interval * 2.2, rate * 4.0 / decay))
    out = [0.0] * n
    two_pi_res = 2 * math.pi * res / rate
    dk = math.exp(-decay / rate)
    pat = v.pattern
    for f in range(n_cyc * v.cyl):
        start = int(round(f * interval))
        amp = pat[f % len(pat)] * (1.0 + rng.uniform(-0.04, 0.04))
        e = amp
        nz = rasp * amp
        for i in range(plen):
            j = start + i
            if j >= n:
                j -= n
            out[j] += e * (math.sin(two_pi_res * i) + nz * rng.uniform(-1.0, 1.0))
            e *= dk
            nz *= 0.985
    # the fundamental (the bit you feel in your seat), a whole number of cycles per loop
    fire_cycles = n_cyc * v.cyl
    w = 2 * math.pi * fire_cycles / n
    peak = max(1e-9, max(abs(x) for x in out))
    b = body * peak
    for i in range(n):
        out[i] += b * math.sin(w * i) + b * 0.5 * math.sin(w * 0.5 * i) * (1 if v.cyl == 8 else 0)
    out = _lowpass_loop(out, lp + (1.0 - lp) * frac * 0.5)
    if supercharged:
        # belt whine: pure-ish tone locked to the crank, louder the harder it's spun
        cycles = max(1, int(round(SC_WHINE * rpm * n / rate)))
        ww = 2 * math.pi * cycles / n
        pk = max(1e-9, max(abs(x) for x in out))
        a = pk * (0.1 + 0.35 * frac)
        for i in range(n):
            out[i] += a * (math.sin(ww * i) + 0.3 * math.sin(2 * ww * i))
    level = (0.55 + 0.45 * frac) * v.gain
    return _normalise(out, 0.9 * min(1.0, level)), rpm


def _render_electric(rpm, rate, redline):
    """The scooter motor: an inverter whine that climbs with speed. Terrifying at 12 m/s."""
    n = int(LOOP_S * rate)
    f = max(40.0, rpm / 60.0 * 6)
    cycles = max(1, int(round(f * n / rate)))
    w = 2 * math.pi * cycles / n
    rng = random.Random(3)
    frac = min(1.0, rpm / redline)
    out = [0.6 * math.sin(w * i) + 0.2 * math.sin(3 * w * i) + 0.04 * rng.uniform(-1, 1) for i in range(n)]
    return _normalise(out, 0.4 + 0.4 * frac)


def render_whistle(freq, rate):
    """A turbo spooling: a thin whistle over a hiss. One loop per pitch band."""
    n = int(0.25 * rate)
    cycles = max(1, int(round(freq * n / rate)))
    w = 2 * math.pi * cycles / n
    rng = random.Random(int(freq))
    hiss = [rng.uniform(-1, 1) for _ in range(n)]
    hiss = _lowpass_loop(hiss, 0.35)
    out = [0.55 * math.sin(w * i) + 0.12 * math.sin(2 * w * i) + 0.5 * hiss[i] for i in range(n)]
    return _normalise(out, 0.8)


def render_screech(rate):
    """Tyres giving up: a wobbling squeal. One second, whole-Hz tones, so it loops."""
    n = rate
    rng = random.Random(11)
    out = []
    for i in range(n):
        t = i / float(rate)
        wob = math.sin(2 * math.pi * 7 * t) * 0.4
        v = (math.sin(2 * math.pi * 1180 * t + wob * 3) * 0.5 + math.sin(2 * math.pi * 1437 * t + wob * 2) * 0.3
             + math.sin(2 * math.pi * 947 * t) * 0.2 + rng.uniform(-0.3, 0.3))
        out.append(v)
    return _normalise(_lowpass_loop(out, 0.6), 0.8)


def render_bov(rate, flutter=False):
    """A blow-off valve: psssh. Or, on the big turbos, the flutter (stu-tu-tu-tu)."""
    n = int(0.45 * rate)
    rng = random.Random(5 if flutter else 6)
    out, lp = [], 0.0
    for i in range(n):
        t, p = i / float(rate), i / float(n)
        env = min(1.0, t / 0.01) * (1 - p) ** 2
        if flutter:
            env *= 0.45 + 0.55 * (1 if (t * 32) % 1 < 0.5 else 0)
        lp += (rng.uniform(-1, 1) - lp) * (0.55 - 0.3 * p)
        out.append(lp * env + 0.2 * math.sin(2 * math.pi * (2600 - 1800 * p) * t) * env)
    return _normalise(out, 0.8)


def render_pop(rate, pitch=1.0, seed=0):
    """An overrun backfire: a low whump with a crack on top. Pops and bangs."""
    n = int(0.16 * rate)
    rng = random.Random(40 + seed)
    out = []
    for i in range(n):
        t, p = i / float(rate), i / float(n)
        crack = rng.uniform(-1, 1) * max(0.0, 1 - t / 0.006) * 1.2
        whump = math.sin(2 * math.pi * 70 * pitch * (1 - 0.4 * p) * t) * (1 - p) ** 3
        grit = rng.uniform(-1, 1) * 0.35 * (1 - p) ** 5
        out.append(crack + whump + grit)
    return _normalise(out, 0.9)


def render_shift(rate):
    """The clunk-and-breath between gears."""
    n = int(0.12 * rate)
    rng = random.Random(21)
    return _normalise([(math.sin(2 * math.pi * 55 * i / rate) + rng.uniform(-0.3, 0.3)) * (1 - i / n) ** 2
                       for i in range(n)], 0.5)

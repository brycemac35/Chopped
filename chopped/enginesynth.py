"""
enginesynth.py -- engine notes from physics, roughly (v0.8; rebuilt in v0.18, Bryce: "a better
algorithm for the car engine, turbo, and supercharger noises, with realism in mind").

The old voices were "a decaying sine per cylinder, low-passed": fine, but every band was a
different cartoon. What actually makes an engine sound like an OBJECT is this chain:

  1. PULSES. Every time an exhaust valve cracks open, a slug of hot gas hits the pipe: a sharp
     pressure step that decays. A four-stroke fires each cylinder once per two revolutions, so the
     pulse train runs at f = rpm / 60 * cylinders / 2. WHEN each cylinder fires (the firing order and
     crank layout) is the engine's character: an inline-4 is evenly spaced (strong 2nd order), an
     inline-6 is smoother still, a cross-plane V8 fires L R R L R L L R so each header sees
     lumpy spacing (the burble), a 90-degree odd-fire V6 alternates 90 and 150 degrees, a flat-4
     boxer has unequal-length headers (the Subaru rumble), a single fires once per two revs.
  2. PIPES. The pulse rings the exhaust like a quarter-wave organ pipe: modes at c/4L * (1, 3, 5, 7).
     Those frequencies belong to the PIPE, not to the rpm, so they stay put while the firing
     frequency sweeps through them. That is the whole difference between an engine and a
     pitch-shifted sample of one. So the pulse's impulse response (pipe modes + a unipolar
     "pressure step" thump + a blowdown hiss, then the muffler's low-pass) is rendered once per
     layout/load and STAMPED at each firing time. Convolution is linear, so this is the same as
     filtering the pulse train, at a fraction of the cost.
  3. NOISE THAT SCALES WITH REVS: intake roar (air pulled through the throttle in gulps, one per
     cylinder, louder on throttle) and valvetrain/mechanical broadband (grows with rpm, whatever
     the throttle). Off throttle the pulses get small and dull (little gas flow) and the mechanical
     noise is what you hear: that's the overrun.
  4. IMPERFECTION. Cycle-to-cycle combustion varies: small random amplitude and timing wobble per
     firing, worse at idle and off load, plus a rare weak "misfire" at idle. Seeded, so it's the
     same engine every run.

Each layout is rendered at ENGINE_BANDS rpm points, twice (on load, off load), every loop a whole
number of engine cycles so it repeats without a click; audio.py crossfades neighbouring rpm bands
and the on/off pair. (pygame can't pitch-shift a playing Sound, so the alternative -- one loop
resampled across the range -- would drag the pipe modes with it, which is the toy-car failure.)

Forced induction is NOT baked into the engine loops any more, because both are separate physical
sources with their own pitch laws: a turbo's whistle follows the TURBINE's speed, which lags the revs
(drivetrain.Tacho.turbo_n); a supercharger's whine is a belt-driven gear/lobe mesh locked to the
crank (Tacho.sc_hz). Each is a bank of finely spaced pure-ish tones (render_tone) plus a shared
airflow hiss (render_air); audio.py picks the bank by frequency.

Pure Python, no pygame: returns lists of floats in -1..1.
"""

import math
import random

from .parts import (V_I4, V_I4T, V_ELECTRIC, V_V8, V_ROTARY, V_I6, V_DIESEL, V_V6, V_VTEC)
from . import config as C

LOOP_S = 0.3            # target loop length. Whole engine cycles, so it's never exactly this.
SOUND_C = 520.0         # m/s: speed of sound in ~600 C exhaust gas (343 in cold air)
H_MAX_S = 0.06          # s: longest pulse response we stamp (the ring is ~9% left by then; tapered)
JITTER_TAPER = 0.35     # last share of a pulse response that fades to zero (no click at the cut)


class Layout:
    """How one engine is put together.
    angles: crank angle in degrees (0..720) of each firing, in the order they happen; banks: which
    exhaust bank each firing goes to; pipe: tailpipe length in m (sets the quarter-wave modes);
    split: how much longer bank 1's pipe is (a flat-4's unequal headers are 0.35, a cross-plane V8's
    are a hair different); muffle: the exhaust+cabin low-pass corner in Hz; modes: relative gain of
    each odd pipe mode; ring: mode decay 1/s; thump: unipolar pressure-step weight; rasp: blowdown
    hiss weight; intake / mech: broadband noise weights; jit: cycle-to-cycle spread; gain: voice loudness."""
    __slots__ = ("name", "angles", "banks", "pipe", "split", "muffle", "modes", "ring", "thump", "rasp",
                 "intake", "mech", "jit", "gain", "index")

    def __init__(self, name, angles, banks, pipe, muffle, modes=(1.0, 0.6, 0.4, 0.25), ring=48.0,
                 thump=0.8, rasp=0.25, intake=0.5, mech=0.25, jit=0.05, gain=1.0, split=0.02):
        self.name, self.angles, self.banks = name, tuple(angles), tuple(banks)
        self.pipe, self.muffle, self.modes, self.ring = pipe, muffle, modes, ring
        self.thump, self.rasp, self.intake, self.mech = thump, rasp, intake, mech
        self.jit, self.gain, self.split = jit, gain, split
        self.index = 0

    @property
    def cyl(self):
        """Firings per engine cycle (two revolutions)."""
        return len(self.angles)


def _even(n):
    return tuple(720.0 * k / n for k in range(n))


LAYOUTS = {}


def _add(lay):
    lay.index = len(LAYOUTS) + 1
    LAYOUTS[lay.name] = lay
    return lay


_add(Layout("i4", _even(4), (0, 0, 0, 0), 1.9, 2600, ring=52, thump=0.8, rasp=0.22, intake=0.55, mech=0.3, jit=0.05))
_add(Layout("i4t", _even(4), (0, 0, 0, 0), 2.2, 2000, ring=46, thump=0.85, rasp=0.14, intake=0.45, mech=0.22,
            jit=0.04))                                              # the turbine muffles the pipe
# 1-5-3-6-2-4 alternates the two 3-cylinder headers: silky, 3rd order
_add(Layout("i6", _even(6), (0, 1, 0, 1, 0, 1), 2.1, 2300, ring=50, thump=0.7, rasp=0.12, intake=0.5, mech=0.2,
            jit=0.025, gain=1.0))
# 90-degree odd-fire V6 (Buick-style): 90/150 spacing, lumpy
_add(Layout("v6", (0, 90, 240, 330, 480, 570), (0, 1, 0, 1, 0, 1), 2.0, 2400, ring=46, thump=0.85, rasp=0.18,
            intake=0.5, mech=0.25, jit=0.06, split=0.05))
# cross-plane V8, firing order 1-8-4-3-6-5-7-2 with 1,3,5,7 on the left bank: L R R L R L L R.
# Even 90 degrees in time, but each header sees 90/180/270 -- that's the burble
_add(Layout("v8", _even(8), (0, 1, 1, 0, 1, 0, 0, 1), 2.6, 1900, ring=40, thump=1.0, rasp=0.15, intake=0.6,
            mech=0.2, jit=0.07, gain=1.1, split=0.06))
_add(Layout("rotary", _even(4), (0, 1, 0, 1), 1.0, 4200, modes=(1.0, 0.8, 0.6, 0.5), ring=80, thump=0.35, rasp=0.6,
            intake=0.35, mech=0.15, jit=0.05, split=0.1))          # short open pipe: the brap
_add(Layout("diesel", _even(4), (0, 0, 0, 0), 2.8, 1500, ring=34, thump=1.1, rasp=0.85, intake=0.3, mech=0.7,
            jit=0.12, gain=1.1))                                    # combustion knock: rasp, thump, clatter
_add(Layout("vtec", _even(4), (0, 0, 0, 0), 1.7, 2800, ring=54, thump=0.75, rasp=0.2, intake=0.55, mech=0.3,
            jit=0.05))
_add(Layout("vtec_hi", _even(4), (0, 0, 0, 0), 1.3, 4600, modes=(1.0, 0.85, 0.65, 0.45), ring=70, thump=0.65,
            rasp=0.45, intake=0.85, mech=0.4, jit=0.04, gain=1.1))  # the second cam: shorter, brighter, angrier
_add(Layout("bike_i4", _even(4), (0, 0, 0, 0), 0.9, 4400, modes=(1.0, 0.8, 0.6, 0.4), ring=75, thump=0.55,
            rasp=0.4, intake=0.7, mech=0.35, jit=0.04))            # 13,000 rpm of short pipe: the scream
_add(Layout("single", (0.0,), (0,), 1.4, 2200, ring=36, thump=1.1, rasp=0.3, intake=0.6, mech=0.25, jit=0.10,
            gain=1.1))                                              # one bang per two revs: the thumper
# flat-4 boxer, firing order 1-3-2-4 with UNEQUAL-length headers (bank 1 is 35% longer): the two
# banks ring at different pitches and beat against each other. No voice id yet, so nothing plays
# it, but it's here so the next voice slot costs one line.
_add(Layout("boxer", _even(4), (0, 1, 0, 1), 1.7, 2400, ring=44, thump=0.9, rasp=0.2, intake=0.5, mech=0.25,
            jit=0.05, split=0.35))

_VOICE_LAYOUT = {V_I4: "i4", V_I4T: "i4t", V_V8: "v8", V_ROTARY: "rotary", V_I6: "i6", V_DIESEL: "diesel",
                 V_V6: "v6", V_VTEC: "vtec"}
VOICES = {v: LAYOUTS[n] for v, n in _VOICE_LAYOUT.items()}       # (kept: voice id -> layout)
BIKE_REDLINE = 9500.0     # a V_I4 that revs past this is a motorbike, not a hatchback...
SCREAMER_REDLINE = 12000.0   # ...and past this it's a four-cylinder superbike; below it, a thumper


def layout_name(voice, redline=0):
    """Which layout a car row's voice id means. (Voice ids are 4 bits on the wire, and a new one
    would bump the protocol, so the two bike engines -- both V_I4 -- are told apart by redline.)"""
    if voice == V_ELECTRIC:
        return "electric"
    if voice == V_I4 and redline >= BIKE_REDLINE:
        return "bike_i4" if redline >= SCREAMER_REDLINE else "single"
    return _VOICE_LAYOUT.get(voice, "i4")


# what to hand layout_name to get each PLAYED layout back (audio pre-renders these; boxer has no voice id yet;
# vtec_hi is not a bank of its own: the vtec bank switches to it above the cam changeover)
LAYOUT_VOICE = {"i4": (V_I4, 0), "i4t": (V_I4T, 0), "v8": (V_V8, 0), "rotary": (V_ROTARY, 0), "i6": (V_I6, 0),
                "diesel": (V_DIESEL, 0), "v6": (V_V6, 0), "vtec": (V_VTEC, 0), "electric": (V_ELECTRIC, 0),
                "bike_i4": (V_I4, 13000), "single": (V_I4, 10500)}


def firing_hz(layout, rpm):
    """The pulse train's frequency: rpm/60 revs a second, cyl/2 firings per rev (four-stroke)."""
    n = layout.cyl if isinstance(layout, Layout) else LAYOUTS[layout].cyl
    return rpm / 60.0 * n / 2.0


def pipe_modes(layout, bank=0):
    """[(Hz, gain)] of a layout's exhaust: quarter-wave organ pipe, f = c/4L * (1, 3, 5, 7)."""
    lay = layout if isinstance(layout, Layout) else LAYOUTS[layout]
    length = lay.pipe * (1.0 + (lay.split if bank else 0.0))
    f1 = SOUND_C / (4.0 * length)
    return [(f1 * (2 * k + 1), g) for k, g in enumerate(lay.modes)]


# ---------------------------------------------------------------- small DSP helpers
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


def _pole(cut_hz, rate):
    """One-pole coefficient for a corner in Hz."""
    return 1.0 - math.exp(-2.0 * math.pi * cut_hz / rate)


def _normalise(x, peak):
    m = max(1e-9, max(abs(v) for v in x))
    k = peak / m
    return [v * k for v in x]


def _fit_rms(x, rms):
    """Remove DC, scale to an RMS, and soft-limit with tanh: loudness is set by RMS (what you hear),
    and the limiter keeps a crest-heavy V8 from ever clipping the mixer. Peak < 1 by construction."""
    n = len(x)
    mean = sum(x) / n
    x = [v - mean for v in x]
    cur = math.sqrt(sum([v * v for v in x]) / n) or 1e-9
    k = rms / cur
    th = math.tanh
    return [th(v * k) for v in x]


_SINE = {}


def _sine_table(n):
    t = _SINE.get(n)
    if t is None:
        w = 2.0 * math.pi / n
        t = _SINE[n] = [math.sin(w * i) for i in range(n)]
    return t


# ---------------------------------------------------------------- the pulse response
_H_CACHE = {}


def _pulse_response(lay, bank, load, rate):
    """[variants] of one exhaust pulse's response at this load: thump (the pressure step) + pipe modes
    + blowdown hiss, through the muffler. Independent of rpm -- that's the point. Three variants
    differ only in their hiss, so successive firings aren't sample-identical."""
    key = (lay.name, bank, round(load, 2), rate)
    got = _H_CACHE.get(key)
    if got is not None:
        return got
    H = int(H_MAX_S * rate)
    rng = random.Random(9000 + lay.index * 17 + bank * 5)
    modes = [0.0] * H
    for k, (f, g) in enumerate(pipe_modes(lay, bank)):
        if f > rate * 0.45:
            continue
        # damped resonator by recurrence: y[n] = 2 r cos(w) y[n-1] - r^2 y[n-2]. Higher modes die faster.
        r = math.exp(-lay.ring * (1.0 + 0.5 * k) / rate)
        w = 2.0 * math.pi * f / rate
        a1, a2 = 2.0 * r * math.cos(w), -r * r
        y2, y1 = 0.0, r * math.sin(w)                       # y[0], y[1]
        modes[1] += g * y1
        for i in range(2, H):
            y = a1 * y1 + a2 * y2
            y2, y1 = y1, y
            modes[i] += g * y
    tau = 0.004
    ex = math.exp(-1.0 / (tau * rate))
    thump, e = [], 1.0
    for _ in range(H):
        thump.append(e)
        e *= ex
    # load: on throttle the blowdown is violent (big step, full ring, bright); off throttle the
    # cylinders are pumping air, the pulse is a small dull "pft"
    lg = 0.28 + 0.72 * load
    tg = lay.thump * (0.3 + 0.7 * load)
    rg = lay.rasp * (0.25 + 0.75 * load)
    cut = lay.muffle * (0.55 + 0.45 * load)
    k = _pole(cut, rate)
    tap0 = int(H * (1.0 - JITTER_TAPER))
    taper = [1.0] * tap0 + [0.5 + 0.5 * math.cos(math.pi * (i - tap0) / (H - tap0)) for i in range(tap0, H)]
    hx = math.exp(-1.0 / (0.005 * rate))
    variants = []
    for _v in range(3):
        env, h = 1.0, []
        for i in range(H):
            h.append(lg * modes[i] + tg * thump[i] + rg * env * rng.uniform(-1.0, 1.0))
            env *= hx
        y1 = y2 = 0.0
        out = []
        for v, tp in zip(h, taper):
            y1 += (v - y1) * k          # muffler: two poles
            y2 += (y1 - y2) * k
            out.append(y2 * tp)
        variants.append(out)
    peak = max(max(abs(v) for v in h) for h in variants) or 1.0
    variants = [[v / peak for v in h] for h in variants]
    _H_CACHE[key] = variants
    return variants


# ---------------------------------------------------------------- the engine
def render_engine(voice, rpm, rate, supercharged=False, redline=7000, vtec_rpm=None, seed=0, load=1.0):
    """One loop of an engine at a steady rpm and load (1 = flat out, 0 = off the throttle).
    Returns (samples, actual_rpm). `voice` is a parts.V_* id or a layout name.
    supercharged mixes a belt whine into the loop (audio.py doesn't: it plays it as its own layer)."""
    if voice == V_ELECTRIC or voice == "electric":
        return _render_electric(rpm, rate, redline, load), rpm
    name = voice if isinstance(voice, str) else layout_name(voice, redline if voice == V_I4 else 0)
    lay = LAYOUTS.get(name) or LAYOUTS["i4"]
    if name == "vtec" and vtec_rpm and rpm >= vtec_rpm:
        lay = LAYOUTS["vtec_hi"]                     # the second cam: harder, brighter, angrier
    cyc_n = max(8, int(round(120.0 / rpm * rate)))   # samples per engine cycle (two revolutions)
    rpm = 120.0 * rate / cyc_n                       # (the rpm we actually hit, to the sample)
    n_cyc = max(1, int(round(LOOP_S * rate / cyc_n)))
    if n_cyc < 2 and cyc_n * 2 <= rate * 0.5:
        n_cyc = 2                                    # two cycles, so the wobble has something to wobble between
    n = n_cyc * cyc_n
    frac = min(1.0, rpm / float(max(1.0, redline)))
    rng = random.Random(seed * 100003 + lay.index * 7919 + int(rpm) * 31 + int(load * 100))
    on, off = load, 1.0 - load
    # ---- pulses at the firing times
    interval = cyc_n / float(lay.cyl)
    H = min(int(H_MAX_S * rate), n, int(interval * 4.0))
    variants = {}
    for b in (0, 1):
        if b in lay.banks:
            base = _pulse_response(lay, b, load, rate)
            # a shorter stamp than the full response (high revs overlap anyway): re-taper its end
            tap0 = int(H * (1.0 - JITTER_TAPER))
            tp = [1.0] * tap0 + [0.5 + 0.5 * math.cos(math.pi * (i - tap0) / max(1, H - tap0)) for i in range(tap0, H)]
            variants[b] = [[x * t for x, t in zip(h[:H], tp)] for h in base]
    rough = (1.6 - 0.9 * frac) * (1.0 + 0.35 * off)      # idle and lifted engines are lumpier
    jit = lay.jit * rough
    tj = 0.00022 * rate * rough * (lay.jit / 0.05)       # samples of timing wobble (~0.2 ms at idle)
    out = [0.0] * (n + H)
    env_i = [0.0] * (n + int(interval) + 2)
    span = int(max(2.0, interval * 0.6))                  # intake valve's open window per cylinder
    win = [math.sin(math.pi * i / span) ** 2 for i in range(span)]
    last_in_bank = {}
    ncyl = lay.cyl
    for cyc in range(n_cyc):
        cyc_amp = 1.0 + rng.uniform(-jit, jit) * 0.6
        for f, ang in enumerate(lay.angles):
            bank = lay.banks[f]
            t0 = cyc * cyc_n + ang / 720.0 * cyc_n
            # header spacing: a pulse close behind another in the SAME header meets a pipe still
            # pressurised by the last one, so it hits a little softer (the V8 burble comes from this)
            prev = last_in_bank.get(bank)
            gap = 720.0 if prev is None else (cyc * 720.0 + ang - prev) % 1440.0
            spacing = 0.78 + 0.22 * min(1.0, gap / 180.0)
            last_in_bank[bank] = cyc * 720.0 + ang
            amp = cyc_amp * spacing * (1.0 + rng.uniform(-jit, jit))
            if frac < 0.3 and rng.random() < 0.05 * lay.jit / 0.05:
                amp *= 0.45                                   # the odd weak firing at idle
            s = int(round(t0 + rng.gauss(0.0, tj))) % n
            h = variants[bank if bank in variants else 0][rng.randrange(3)]
            seg = out[s:s + H]
            out[s:s + H] = [o + amp * x for o, x in zip(seg, h)]
            # intake gulp for this cylinder
            ia = amp * on ** 1.2
            e0 = s
            seg = env_i[e0:e0 + span]
            env_i[e0:e0 + span] = [o + ia * w for o, w in zip(seg, win)]
    for i in range(H):                                        # wrap the tails round to the start
        out[i] += out[n + i]
    out = out[:n]
    for i in range(min(len(env_i) - n, n)):
        env_i[i] += env_i[n + i]
    env_i = env_i[:n]
    # ---- broadband: intake roar (low, in gulps, on throttle) and mechanical noise (high, with revs)
    w = [rng.random() - 0.5 for _ in range(n)]
    lo = _lowpass_loop(w, _pole(500.0 + 1800.0 * frac, rate))
    intake_g = lay.intake * (0.12 + 0.88 * on) * (0.25 + 0.75 * frac ** 1.2) * 5.0
    mech_g = lay.mech * (0.05 + 0.95 * frac ** 1.3) * 2.2
    # a valve-cracking tick on top of the hiss, at half the crank rate per cylinder
    out = [o + intake_g * l * (0.25 + 0.75 * e) + mech_g * (x - l)
           for o, l, x, e in zip(out, lo, w, env_i)]
    if supercharged:
        out = _add_whine(out, rate, sc_hz(rpm), 0.35 + 0.65 * frac)
    # ---- overall loudness: absolute-ish (idle is quiet), off throttle is quieter than on
    level = (C.ENGINE_LEVEL_IDLE + (1.0 - C.ENGINE_LEVEL_IDLE) * frac ** 0.9) * \
            (C.ENGINE_LEVEL_OFF + (1.0 - C.ENGINE_LEVEL_OFF) * on) * lay.gain
    return _fit_rms(out, C.ENGINE_RMS * level), rpm


def _add_whine(out, rate, f1, level):
    """Mix a Roots-style whine into a loop (whole cycles per loop so it stays seamless)."""
    n = len(out)
    rms = math.sqrt(sum(v * v for v in out) / n) or 1e-9
    tone = [0.0] * n
    for h, g in SC_PARTIALS:
        f = f1 * h
        if f > rate * 0.45:
            continue
        cyc = max(1, int(round(f * n / rate)))
        tab = _sine_table(n)
        tone = [t + g * tab[(cyc * i) % n] for i, t in enumerate(tone)]
    k = rms * level * 0.6
    return [o + k * t for o, t in zip(out, tone)]


# ---------------------------------------------------------------- electric
def _render_electric(rpm, rate, redline, load=1.0):
    """The scooter/EV motor: no pulses at all. A motor's noise is orders of rotor speed (pole-pair
    magnetic hum at 6x, the helical reduction gear at 6x and 12x and a half-order sideband), so it
    tracks the wheels; and the inverter's PWM carrier is a FIXED tone (~5 kHz) whose loudness
    follows torque, with sidebands at plus and minus twice the motor frequency."""
    n = int(LOOP_S * rate)
    tab = _sine_table(n)
    frac = min(1.0, rpm / float(max(1.0, redline)))
    f = max(40.0, rpm / 60.0 * 6.0)
    on = load

    def cyc(hz):
        return max(1, int(round(hz * n / rate)))
    parts = [(cyc(f), 0.6), (cyc(f * 2.0), 0.16), (cyc(f * 3.0), 0.2 * (0.3 + 0.7 * frac)),
             (cyc(f * 0.5), 0.1)]
    carrier = cyc(5200.0)
    side = cyc(2.0 * f)
    rng = random.Random(3 + int(rpm))
    pw = 0.05 * (0.2 + 0.8 * on) * (0.4 + 0.6 * frac)
    out = []
    for i in range(n):
        v = sum(g * tab[(c * i) % n] for c, g in parts)
        v += pw * tab[(carrier * i) % n] + 0.5 * pw * (tab[((carrier + side) * i) % n] + tab[((carrier - side) * i) % n])
        out.append(v + 0.02 * (rng.random() - 0.5))
    level = (0.25 + 0.75 * frac ** 0.8) * (0.6 + 0.4 * on) * 0.8
    return _fit_rms(out, C.ENGINE_RMS * level)


# ---------------------------------------------------------------- turbo and supercharger tones
# Roots/twin-screw lobe-pass whine: a fundamental with strong 2nd-4th harmonics (sharp pulses)
SC_PARTIALS = ((1.0, 0.6), (2.0, 1.0), (3.0, 0.8), (4.0, 0.45), (6.0, 0.2))
# compressor blade-pass whistle: a near-pure tone, a whisper of 2nd, and a detuned sub-synchronous
# partner that beats against it slowly (real compressors shimmer)
TURBO_PARTIALS = ((1.0, 1.0), (2.0, 0.16), (1.0085, 0.4), (0.5, 0.12))


def sc_hz(rpm):
    """Supercharger lobe-pass fundamental for a crank speed: rotor rev/s * lobes. Belt-driven,
    so no lag and no slip: it is EXACTLY proportional to rpm."""
    return rpm / 60.0 * C.SC_PULLEY * C.SC_LOBES


def tone_bank(lo, hi, ratio):
    """Log-spaced frequencies lo..hi, adjacent ones `ratio` apart (audio crossfades neighbours)."""
    n = int(math.ceil(math.log(hi / float(lo)) / math.log(ratio))) + 1
    return [lo * ratio ** i for i in range(n)]


def render_tone(freq, rate, partials, dur=0.1):
    """A short loop of a tone with partials, whole cycles of each so it never clicks. -> (samples, freq)."""
    n = int(dur * rate)
    tab = _sine_table(n)
    cycles = []
    for r, g in partials:
        f = freq * r
        if 20.0 < f < rate * 0.45:
            cycles.append((max(1, int(round(f * n / rate))), g))
    x = [sum(g * tab[(c * i) % n] for c, g in cycles) for i in range(n)]
    return _normalise(x, 0.8), cycles[0][0] * rate / float(n) if cycles else freq


def render_whistle(freq, rate):
    """A turbo compressor at one turbine speed: the blade-pass whistle. Airflow hiss is separate
    (render_air) so its level can follow the mass flow instead of the pitch."""
    return render_tone(freq, rate, TURBO_PARTIALS)[0]


def render_air(rate, seconds=0.8):
    """Airflow rush for the intake/compressor: band-limited noise, seamless. One loop, played
    louder with mass flow."""
    n = int(seconds * rate)
    rng = random.Random(77)
    w = [rng.random() - 0.5 for _ in range(n)]
    hi = _lowpass_loop(w, _pole(4200.0, rate))
    lo = _lowpass_loop(w, _pole(700.0, rate))
    return _normalise([a - b for a, b in zip(hi, lo)], 0.8)


# ---------------------------------------------------------------- one-shots
def _svf_noise(n, rate, fc0, fc1, damp, rng):
    """Noise through a state-variable band-pass whose centre glides fc0 -> fc1 (a falling pressure
    means a falling escape velocity, so the blow-off's hiss slides down)."""
    low = band = 0.0
    out = []
    for i in range(n):
        fc = fc0 + (fc1 - fc0) * i / n
        f = 2.0 * math.sin(math.pi * fc / rate)
        hi = rng.uniform(-1, 1) - low - damp * band
        band += f * hi
        low += f * band
        out.append(band)
    return out


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
    """A blow-off valve: the boost pressure dumps through a small hole -- a band-passed hiss whose
    pitch falls as the pressure does, with the valve's little thump on the front. Or, with no valve
    (the big turbos), the compressor surges: the flow reverses and re-establishes over and over
    (stu-tu-tu-tu) at a rate that slows as the pressure bleeds off."""
    rng = random.Random(5 if flutter else 6)
    if not flutter:
        n = int(0.5 * rate)
        hiss = _svf_noise(n, rate, 3800.0, 1500.0, 0.45, rng)
        out = []
        for i, h in enumerate(hiss):
            t = i / float(rate)
            env = min(1.0, t / 0.004) * (0.7 * math.exp(-t / 0.09) + 0.3 * math.exp(-t / 0.22))
            thump = 0.5 * math.sin(2 * math.pi * 95.0 * t) * math.exp(-t / 0.018)
            out.append(h * env * 0.9 + thump)
        return _normalise(out, 0.8)
    n = int(0.6 * rate)
    hiss = _svf_noise(n, rate, 2600.0, 1100.0, 0.5, rng)
    out, ph, g = [], 0.0, 0.0
    for i, h in enumerate(hiss):
        t = i / float(rate)
        ph += (22.0 - 12.0 * t / 0.6) / rate                # chuff rate slows as the boost bleeds away
        want = 1.0 if (ph % 1.0) < 0.42 else 0.06
        g += (want - g) * 0.05
        env = min(1.0, t / 0.006) * math.exp(-t / 0.28)
        out.append((h * 0.9 + 0.35 * math.sin(2 * math.pi * 140.0 * t)) * g * env)
    return _normalise(out, 0.8)


def render_pop(rate, pitch=1.0, seed=0):
    """An overrun backfire: unburnt fuel lights in the hot pipe. A crack (the shock front), the
    exhaust ringing its lowest pipe mode, and a falling whump."""
    n = int(0.18 * rate)
    rng = random.Random(40 + seed)
    ring = 165.0 * pitch
    out = []
    for i in range(n):
        t, p = i / float(rate), i / float(n)
        crack = rng.uniform(-1, 1) * max(0.0, 1 - t / 0.005) * 1.2
        bark = math.sin(2 * math.pi * ring * t) * math.exp(-t / 0.03) * 0.8
        whump = math.sin(2 * math.pi * 70 * pitch * (1 - 0.4 * p) * t) * (1 - p) ** 3
        grit = rng.uniform(-1, 1) * 0.3 * (1 - p) ** 5
        out.append(crack + bark + whump + grit)
    return _normalise(out, 0.9)


def render_shift(rate):
    """The clunk-and-breath between gears."""
    n = int(0.12 * rate)
    rng = random.Random(21)
    return _normalise([(math.sin(2 * math.pi * 55 * i / rate) + rng.uniform(-0.3, 0.3)) * (1 - i / n) ** 2
                       for i in range(n)], 0.5)

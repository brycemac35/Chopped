"""
sfxsynth.py (v0.18) -- the one-shots, loops, horns and ambience beds, synthesised from raw
samples. Split out of audio.py's _build so the soundscape rework lives in one place; the
`Audio` class inherits this mixin and supplies rate/nch/_mk. No numpy, no files.

The house rules for this file:
  * raw squares and saws go through a one-pole low-pass (`soft=`) -- they were the harsh part
  * frequent sounds have 2-3 pitch/noise variants and audio.play picks one at random
  * loops have whole numbers of cycles in them (seamless) and end where they start
  * everything is scaled under C.PEAK_CEIL by _mk, so nothing here can clip
"""

import math
import random

from . import config as C
from . import sim as S
from . import soundscape as SC

_TAU = 2.0 * math.pi
_N = 2048
# a soft horn cycle: fundamental plus a little 2nd and 3rd, so it's brassy but not a raw square
_HORN_TBL = [math.sin(_TAU * i / _N) + 0.30 * math.sin(2 * _TAU * i / _N) + 0.12 * math.sin(3 * _TAU * i / _N)
             for i in range(_N)]


def _horn_wave(n, rate, f1, f2, amp):
    """n samples of a two-tone car horn (f1 + f2 through the soft table)."""
    tbl, m = _HORN_TBL, _N - 1
    s1, s2 = f1 * _N / rate, f2 * _N / rate
    return [amp * (tbl[int(i * s1) & m] + tbl[int(i * s2) & m]) for i in range(n)]


def _shape(buf, rate, attack=0.012, release=0.03):
    """Soft attack (a raised-cosine ramp) and release on a raw buffer, in place."""
    n = len(buf)
    a, r = min(n // 2, int(attack * rate)), min(n // 2, int(release * rate))
    for i in range(a):
        buf[i] *= 0.5 - 0.5 * math.cos(math.pi * i / a)
    for i in range(r):
        buf[n - 1 - i] *= 0.5 - 0.5 * math.cos(math.pi * i / r)
    return buf


def horn_blasts(rate):
    """The traffic beeps: {(pitch_idx, kind): samples}. Two tones around 400 and 500 Hz, 12 ms
    soft attack. Rendered once per pitch (0.42 s) and cut into a tap, a long blast and a double tap."""
    out = {}
    for pi, ratio in enumerate(SC.HORN_PITCHES):
        base = _horn_wave(int(0.42 * rate), rate, 400.0 * ratio, 500.0 * ratio, 0.2)
        tap_n = int(0.16 * rate)
        out[(pi, 0)] = _shape(base[:tap_n], rate, 0.012, 0.03)
        out[(pi, 1)] = _shape(list(base), rate, 0.015, 0.05)
        half = _shape(base[:int(0.10 * rate)], rate, 0.010, 0.02)
        out[(pi, 2)] = half + [0.0] * int(0.06 * rate) + half
    return out


def _brown(rnd, n, a):
    """n samples of low-passed noise (a = how open the filter is), roughly unit amplitude."""
    y, out = 0.0, []
    k = 1.0 / math.sqrt(a * 0.5 + 1e-3) * 0.55
    for _ in range(n):
        y += (rnd.uniform(-1, 1) - y) * a
        out.append(y * k)
    return out


def _seamless(buf, xf):
    """Make a noise buffer loop: the tail is cross-faded into the head, then dropped."""
    n = len(buf)
    out = buf[:n - xf]
    for i in range(xf):
        w = 0.5 - 0.5 * math.cos(math.pi * i / xf)          # 0 -> 1: head fades in over the tail
        out[i] = buf[i] * w + buf[n - xf + i] * (1.0 - w)
    return out


def _upsample(buf, k):
    """Linear interpolation x k (the beds are all low-frequency, so a low render rate is free)."""
    out, n = [], len(buf)
    for i in range(n):
        a, b = buf[i], buf[(i + 1) % n]
        d = (b - a) / k
        out.extend(a + d * j for j in range(k))
    return out


def ambience_bed(rate, night, seed=5, secs=6.0):
    """The city's quiet bed: distant traffic hum + slow gusts of wind, one seamless loop. Rendered at
    a quarter of the mixer rate and interpolated. Night has less hum, more wind. Peak ~0.5."""
    k = 4
    r = rate // k
    n = int(secs * r)
    xf = int(0.8 * r)
    rnd = random.Random(seed + (100 if night else 0))
    m = n + xf
    hum = _brown(rnd, m, 0.05)                    # ~45 Hz rumble: engines a long way off
    band = _brown(rnd, m, 0.16)                   # ~140 Hz: tyres on tarmac
    wind = _brown(rnd, m, 0.30)                   # ~300 Hz: air over the roofs
    swells = [(rnd.uniform(0, secs), rnd.uniform(0.8, 1.6)) for _ in range(2 if night else 4)]
    L = n                                         # loop length after the crossfade
    hum_g, band_g, wind_g = (0.25, 0.10, 0.55) if night else (0.42, 0.22, 0.30)
    out = []
    for i in range(m):
        t = (i % L) / r
        gust = 0.55 + 0.45 * math.sin(_TAU * t / secs * 1.0 + 1.3)          # one gust per loop
        pas = 0.0
        for c, w in swells:                                                 # a car goes past, far away
            x = (t - c + secs) % secs
            if x < w * 2:
                pas += 0.5 - 0.5 * math.cos(_TAU * x / (w * 2))
        out.append(hum[i] * hum_g + band[i] * band_g * (0.5 + pas * 0.9) + wind[i] * wind_g * gust)
    out = _seamless(out, xf)
    peak = max(max(out), -min(out), 1e-6)
    out = [v * (0.5 / peak) for v in out]
    return _upsample(out, k)


def heli_loop(rate, secs=1.0):
    """A helicopter a couple of blocks off: blade slap at ~11 Hz (whole number per loop) with a
    low turbine hiss underneath. Soft: it's a warning, not a weapon."""
    n = int(secs * rate)
    rnd = random.Random(31)
    hz = 11
    y = 0.0
    out = []
    for i in range(n):
        t = i / rate
        ph = (t * hz) % 1.0
        slap = math.exp(-ph * 14.0) * (0.7 * math.sin(_TAU * 70 * t) + 0.5 * math.sin(_TAU * 130 * t))
        y += (rnd.uniform(-1, 1) - y) * 0.09
        out.append(slap * 0.8 + y * 0.35 * (0.6 + 0.4 * math.sin(_TAU * ph)))
    return out


class SfxSynth:
    """Mixin for audio.Audio. Needs self.rate, self.sounds, self.loops, self._mk, self._tone."""

    # ------------------------------------------------------------------ filters
    @staticmethod
    def _lp(samples, a, loop=False):
        """One-pole low-pass (a = 0..1, bigger is brighter). loop=True pre-rolls the filter from the
        loop's tail so the seam doesn't click."""
        y = 0.0
        if loop:
            for x in samples[-400:]:
                y += (x - y) * a
        out = []
        ap = out.append
        for x in samples:
            y += (x - y) * a
            ap(y)
        return out

    def _sweep(self, dur, ffn, shape, amp=lambda p: 1.0):
        """A tone whose frequency follows ffn(t, p), with a phase that accumulates properly (the old
        `sq(f(t), t)` jumped phase every sample, which is most of why the sirens were so harsh)."""
        n = int(self.rate * dur)
        ph, out = 0.0, []
        for i in range(n):
            t, p = i / self.rate, i / n
            ph += ffn(t, p) / self.rate
            out.append(shape(ph % 1.0) * amp(p))
        return out

    # ------------------------------------------------------------------ the bank
    def _build_sfx(self):
        rnd = random.Random(7)
        tone = self._tone
        mk = lambda smp, vol, soft=None, loop=False: self._mk(smp, vol, soft, fade=not loop)
        sq = lambda f, t: 1.0 if (t * f) % 1.0 < 0.5 else -1.0
        saw = lambda f, t: 2.0 * ((t * f) % 1.0) - 1.0
        sqs = lambda ph: 1.0 if ph < 0.5 else -1.0
        sinw = lambda ph: math.sin(_TAU * ph)
        V3 = (1.0, 0.93, 1.08)                 # the three pitches of a repeated sound

        self.pending_variants = []

        def var(sid, fn, vol, soft=None):
            # the natural pitch now; the other two pitches are rendered by the background thread
            # (audio._render_scape) and appended by the main thread: startup pays for one of the three
            self.sounds[sid] = [mk(fn(V3[0]), vol, soft)]
            self.pending_variants.append((sid, fn, vol, soft, V3[1:]))

        def crunch(dur, low, m=1.0):
            last = [0.0]
            def fn(t, p):
                last[0] += (rnd.uniform(-1, 1) - last[0]) * (0.35 if not low else 0.12) * m
                return (last[0] * 1.6 + 0.5 * math.sin(_TAU * 60 * m * t)) * (1 - p) ** 2
            return tone(dur, fn)
        var(S.S_CRASH, lambda m: crunch(0.25, False, m), 0.7)
        self.sounds[S.S_CRASH_BIG] = mk(crunch(0.5, True), 1.0)
        def boom(t, p):
            return (rnd.uniform(-1, 1) * 0.8 + math.sin(_TAU * (50 - 30 * p) * t)) * (1 - p) ** 1.5
        boom_s = tone(1.1, boom)
        self.sounds[S.S_BOOM] = mk(boom_s, 0.7, 0.6)
        self.sounds[S.S_CRUSH] = mk(crunch(0.8, True), 0.9)
        # what a shut shop door lets through of a big bang: the same sound, low-passed to a thump
        self.muffled = {S.S_BOOM: mk(self._lp(boom_s, 0.03), 1.0),
                        S.S_CRASH_BIG: mk(self._lp(crunch(0.5, True), 0.04), 1.0)}

        self.sounds[S.S_SELL] = mk(tone(0.3, lambda t, p: sq(1320 if p > 0.35 else 990, t) * 0.4 * (1 - p)), 0.6, 0.55)
        var(S.S_PICKUP, lambda m: self._sweep(0.08, lambda t, p: (660 + 600 * p) * m, sqs, lambda p: 0.3 * (1 - p)), 1.02, 0.5)
        var(S.S_DROP, lambda m: self._sweep(0.12, lambda t, p: (300 - 150 * p) * m, sqs, lambda p: 0.3 * (1 - p)), 1.02, 0.45)
        self.sounds[S.S_BREAKIN] = mk(tone(0.35, lambda t, p: (rnd.uniform(-1, 1) * 0.6 + sq(3000, t) * 0.2) * (1 - p) ** 3), 0.8, 0.6)
        self.sounds[S.S_HOTWIRE] = mk(tone(0.7, lambda t, p: saw(40 + 50 * p + 8 * math.sin(40 * t), t) * 0.5 * min(1, p * 4)), 0.7, 0.3)
        var(S.S_STRIP, lambda m: tone(0.3, lambda t, p: sq(180 * m, t) * 0.35 * (1 if (t * 30) % 1 < 0.4 else 0)), 0.6, 0.4)
        self.sounds[S.S_ARREST] = mk(tone(0.9, lambda t, p: sq(880 if int(p * 6) % 2 else 660, t) * 0.3), 0.7, 0.35)
        self.sounds[S.S_RENT] = mk(tone(0.5, lambda t, p: sq(440 if p < 0.5 else 330, t) * 0.3 * (1 - p)), 0.7, 0.4)
        self.sounds[S.S_DELIVER] = mk(tone(0.6, lambda t, p: sq([523, 659, 784, 1046][min(3, int(p * 4))], t) * 0.3), 0.6, 0.5)
        self.sounds[S.S_INSTALL] = mk(tone(0.4, lambda t, p: sq(220 * (1 + int(p * 3)), t) * 0.3 * (1 - p)), 0.6, 0.4)
        var(S.S_YELP, lambda m: self._sweep(0.18, lambda t, p: (900 - 500 * p) * m, sqs, lambda p: 0.25 * min(1, (1 - p) * 4)), 0.85, 0.4)
        # ka-ching... in reverse. The sound of money leaving.
        self.sounds[S.S_BUY] = mk(tone(0.35, lambda t, p: sq(1320 if p < 0.4 else 880, t) * 0.35 * (1 - p)), 0.6, 0.55)
        self.sounds[S.S_IGNITE] = mk(tone(0.4, lambda t, p: rnd.uniform(-1, 1) * 0.5 * p), 0.96, 0.5)
        # v0.6: violence. A punch is a thud with a slap on top.
        var(S.S_PUNCH, lambda m: tone(0.12, lambda t, p: (math.sin(_TAU * (140 - 80 * p) * m * t)
                                                            + rnd.uniform(-1, 1) * 0.6 * (1 - p) ** 6) * (1 - p) ** 2), 0.8)

        # gunshots: a crack of white noise, a low body, and a tail that rings off the buildings
        def shot(dur, body, crack, m=1.0):
            last = [0.0]
            def fn(t, p):
                last[0] += (rnd.uniform(-1, 1) - last[0]) * (0.5 if p < 0.1 else 0.18)
                c = rnd.uniform(-1, 1) * crack * max(0.0, 1 - t / 0.012)
                return (c + last[0] * 1.4 * (1 - p) ** 3 + math.sin(_TAU * body * m * (1 - 0.5 * p) * t)
                        * 0.8 * (1 - p) ** 4)
            return tone(dur, fn)
        var(S.S_PISTOL, lambda m: shot(0.3, 120, 1.0, m), 0.8)
        self.sounds[S.S_SHOTGUN] = mk(shot(0.6, 70, 1.4), 1.0)
        # *click*. The loneliest sound in the game.
        self.sounds[S.S_EMPTY] = mk(tone(0.03, lambda t, p: sq(2400, t) * 0.4 * (1 - p)), 0.8, 0.6)
        # a tyre going: bang, then a hiss that runs out of air
        self.sounds[S.S_TIRE] = mk(tone(0.7, lambda t, p: (rnd.uniform(-1, 1) * (1.0 if p < 0.05 else 0.35) * (1 - p))), 0.8, 0.7)
        self.sounds[S.S_TRAP] = mk(tone(0.25, lambda t, p: (sq(90, t) * 0.3 + rnd.uniform(-1, 1) * 0.3) * (1 - p) ** 2), 0.7, 0.4)
        # the wallet chime: two coins and a guilty conscience
        self.sounds[S.S_ROB] = mk(tone(0.3, lambda t, p: sq(1568 if p < 0.3 else 2093, t) * 0.25 * (1 - p)), 1.02, 0.6)
        # ---- v0.7 slapstick -------------------------------------------------------------
        self.sounds[S.S_WHOOSH] = mk(tone(0.25, lambda t, p: rnd.uniform(-1, 1) * 0.5 * math.sin(p * math.pi)), 0.85, 0.5)
        # bonk: a hollow wooden knock with a little pitch drop, the universal sound of "ow"
        var(S.S_BONK, lambda m: tone(0.18, lambda t, p: math.sin(_TAU * (620 - 300 * p) * m * t) * (1 - p) ** 3), 0.8)
        self.sounds[S.S_GNOME] = mk(self._sweep(0.25, lambda t, p: 1400 + 900 * math.sin(p * 9), sqs,
                                                lambda p: 0.3 * (1 - p)), 1.02, 0.45)                 # *squeak*
        var(S.S_JUMP, lambda m: self._sweep(0.12, lambda t, p: (300 + 500 * p) * m, sqs, lambda p: 0.2 * (1 - p)), 0.8, 0.4)
        # STRIKE: pins going over, then a tiny crowd going "YEAH"
        def strike(t, p):
            clatter = rnd.uniform(-1, 1) * (1 - p) ** 2 * (0.8 if int(t * 40) % 3 else 0.2)
            cheer = (sq(523, t) + sq(659, t) + sq(784, t)) * 0.08 * min(1, max(0, (p - 0.4) * 4)) * (1 - p)
            return clatter + cheer
        self.sounds[S.S_STRIKE] = mk(tone(1.0, strike), 0.8, 0.5)
        # HOME RUN: the crack of a bat and an "ooooh"
        self.sounds[S.S_HOMERUN] = mk(tone(0.9, lambda t, p: (rnd.uniform(-1, 1) * max(0, 1 - t / 0.03))
                                           + saw(200 + 120 * math.sin(p * 3), t) * 0.15 * p * (1 - p) * 4), 1.36, 0.5)
        self.sounds[S.S_EJECT] = mk(tone(0.6, lambda t, p: (rnd.uniform(-1, 1) * 0.7 * max(0, 1 - t / 0.08)
                                                            + sq(200 + 1200 * p, t) * 0.2 * (1 - p))), 0.9, 0.5)
        # slide whistle, going down: the banana peel's theme tune
        self.sounds[S.S_SLIP] = mk(self._sweep(0.6, lambda t, p: 1500 - 1100 * p, sinw, lambda p: 0.4 * (1 - p * 0.5)), 0.7)
        self.sounds[S.S_MUNCH] = mk(tone(0.5, lambda t, p: rnd.uniform(-1, 1) * 0.4 * (1 if int(t * 12) % 2 else 0.1) * (1 - p)), 1.08, 0.5)
        # a laugh: "ha" x4, a formant-ish square that drops in pitch each time
        self.sounds[S.S_LAUGH] = mk(tone(0.8, lambda t, p: sq(330 - int(p * 4) * 25, t) * 0.25
                                         * (1 if (t * 5) % 1 < 0.55 else 0) * (1 - p * 0.6)), 1.0, 0.3)
        var(S.S_MOD, lambda m: tone(0.35, lambda t, p: (rnd.uniform(-1, 1) * 0.5 if (t * 30 * m) % 1 < 0.3 else 0) * (1 - p)), 1.02, 0.55)  # ratchet
        self.sounds[S.S_SPRAY] = mk(tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.3 * min(1, p * 8) * (1 - p)), 1.02, 0.6)
        var(S.S_TRUNK, lambda m: tone(0.2, lambda t, p: math.sin(_TAU * (90 - 30 * p) * m * t) * (1 - p) ** 2
                                      + rnd.uniform(-1, 1) * 0.2 * (1 - p) ** 6), 0.8)
        self.sounds[S.S_WRIGGLE] = mk(tone(0.15, lambda t, p: sq(700 + 300 * math.sin(t * 60), t) * 0.2), 0.72, 0.4)
        self.sounds[S.S_NOS] = mk(tone(0.5, lambda t, p: rnd.uniform(-1, 1) * 0.5 * (1 - p)), 0.7, 0.6)
        # ---- v0.8: the law, and the silly department -----------------------------------
        # taser: a mains-hum buzz with a crackle on top. Ow.
        self.sounds[S.S_TASER] = mk(tone(0.7, lambda t, p: (sq(120, t) * 0.25 + rnd.uniform(-1, 1) * 0.35
                                                            * (1 if (t * 40) % 1 < 0.4 else 0.2)) * (1 - p * 0.5)), 0.7, 0.5)
        # a bark: two quick rough "ruffs"
        self.sounds[S.S_BARK] = mk(tone(0.35, lambda t, p: (saw(260 - 120 * ((t * 6) % 1), t) * 0.4 + rnd.uniform(-1, 1) * 0.25)
                                        * (1 if (t * 6) % 1 < 0.45 else 0)), 0.7, 0.3)
        # the speed camera: a click and a whine, the sound of a fine
        self.sounds[S.S_FLASH] = mk(tone(0.35, lambda t, p: (rnd.uniform(-1, 1) * max(0, 1 - t / 0.01))
                                         + math.sin(_TAU * (3000 + 3000 * p) * t) * 0.2 * (1 - p) ** 2), 0.85)
        # party popper + a little kazoo fanfare (for a delivered car)
        self.sounds[S.S_CONFETTI] = mk(tone(0.9, lambda t, p: (rnd.uniform(-1, 1) * max(0, 1 - t / 0.03))
                                            + saw([523, 659, 784, 1046][min(3, int(p * 4))], t) * 0.18 * min(1, p * 8)), 0.96, 0.35)
        # hydraulics: pssssht-CLUNK
        self.sounds[S.S_HYDRO] = mk(tone(0.45, lambda t, p: rnd.uniform(-1, 1) * 0.35 * (1 - p)
                                         + (math.sin(_TAU * 70 * t) * (1 if p > 0.75 else 0))), 0.49, 0.6)
        # WASTED: a slow falling sting
        self.sounds[S.S_WASTED] = mk(tone(1.6, lambda t, p: (sq(220 - 110 * p, t) * 0.18 + sq(165 - 80 * p, t) * 0.12) * (1 - p)), 0.8, 0.3)
        # the gate: a big metal clank and a rattle
        self.sounds[S.S_GATE] = mk(tone(0.6, lambda t, p: (math.sin(_TAU * 95 * t) + rnd.uniform(-1, 1) * 0.4) * (1 - p) ** 2), 0.6, 0.5)
        # keys: jingle jangle
        self.sounds[S.S_KEYS] = mk(tone(0.4, lambda t, p: math.sin(_TAU * (3200 + 800 * math.sin(t * 90)) * t)
                                        * 0.3 * (1 if (t * 18) % 1 < 0.3 else 0) * (1 - p)), 0.9)
        # cuffs: click-click
        self.sounds[S.S_CUFF] = mk(tone(0.25, lambda t, p: sq(2600, t) * 0.4 * (1 if (t < 0.02 or 0.12 < t < 0.14) else 0)), 1.02, 0.6)
        # the police whistle: FWEEEEET
        self.sounds[S.S_WHISTLE] = mk(tone(0.6, lambda t, p: math.sin(_TAU * (2900 + 120 * math.sin(t * 70)) * t)
                                           * 0.35 * min(1, p * 20) * (1 - p) ** 0.3), 0.8)
        # the streaker: "wheeeee!" (a rising then falling whoop)
        self.sounds[S.S_WHEE] = mk(self._sweep(0.8, lambda t, p: 500 + 700 * math.sin(p * math.pi), sqs,
                                               lambda p: 0.2 * (1 - p * 0.4)), 1.08, 0.4)
        # (v0.9) the roller door: a motor grinding and a chain rattling, then a clunk
        self.sounds[S.S_DOOR] = mk(tone(1.3, lambda t, p: (saw(58 + 6 * math.sin(t * 9), t) * 0.25
                                                           + rnd.uniform(-1, 1) * 0.12 * (1 if (t * 22) % 1 < 0.4 else 0.3))
                                        * min(1, p * 12) * (1 if p < 0.85 else (1 - p) * 6)), 1.08, 0.3)
        # (v0.9) a copper's fist on a roller door: BADANG BADANG BADANG
        self.sounds[S.S_BANG] = mk(tone(0.9, lambda t, p: (math.sin(_TAU * 70 * t) + rnd.uniform(-1, 1) * 0.6)
                                        * max(0.0, 1 - ((t % 0.3) / 0.12)) ** 2), 0.9, 0.5)
        # (v0.9) the rubber chicken: SQUEEEAK (a pitch that bends up then collapses)
        self.sounds[S.S_SQUEAK] = mk(self._sweep(0.35, lambda t, p: 900 + 900 * math.sin(p * math.pi) - 500 * p, sqs,
                                                 lambda p: 0.22 * (1 - p) ** 0.4), 1.19, 0.4)
        # (v0.9) the whoopee cushion: a longer, more committed version of the fart horn
        self.sounds[S.S_PFFT] = mk(self._fart(1.1), 0.75)
        # (v0.9) bawk bawk
        self.sounds[S.S_CLUCK] = mk(tone(0.4, lambda t, p: saw(620 + 380 * ((t * 9) % 1), t) * 0.2
                                         * (1 if (t * 9) % 1 < 0.55 else 0) * (1 - p)), 1.1, 0.3)
        # (v0.9) the chicken meets a bumper: one last BAWK and a thud
        self.sounds[S.S_FEATHERS] = mk(tone(0.45, lambda t, p: (saw(900 - 600 * p, t) * 0.25 * (1 if p < 0.4 else 0)
                                                                + math.sin(_TAU * 60 * t) * 0.5 * (1 if p > 0.4 else 0) * (1 - p))), 0.96, 0.35)
        # (v0.9) cash bags hitting the tarmac: a register ka-ching and a flump
        self.sounds[S.S_CASH] = mk(tone(0.9, lambda t, p: (math.sin(_TAU * 2093 * t) * 0.3 + math.sin(_TAU * 2637 * t) * 0.2)
                                        * max(0.0, 1 - t / 0.5) + rnd.uniform(-1, 1) * 0.3 * max(0.0, 1 - abs(t - 0.5) / 0.1)), 0.7)
        # (v0.10) an ambulance, a couple of streets off: a two-tone siren (nee-naw), distant
        self.sounds[S.S_AMBULANCE] = mk(tone(1.8, lambda t, p: sq(760 if int(t * 2.2) % 2 == 0 else 570, t) * 0.16
                                             * min(1, p * 6) * min(1, (1 - p) * 6)), 0.99, 0.3)

        # ---- horns (the mod shop sells worse ones), indexed by vehicles.HORN_*
        # the stock horn is a soft two-tone: 400 + 500 Hz (a minor-third-ish pair like a real car's),
        # sine + a little harmonic, NOT a raw square. 0.2 s = 80 and 100 whole cycles: a seamless loop.
        stock = _horn_wave(int(0.2 * self.rate), self.rate, 400.0, 500.0, 0.2)
        self.horns = [
            mk(stock, 0.9, None, True),                                                               # stock
            mk(tone(0.5, lambda t, p: sq(700 + 200 * math.sin(p * _TAU), t)
                    * 0.3 * (1 if (p * 2) % 1 < 0.7 else 0)), 0.8, 0.4),                             # clown
            mk(tone(1.2, lambda t, p: sq([392, 392, 392, 523, 659, 392, 392, 392, 523, 659, 0, 0]
                                         [min(11, int(p * 12))], t) * 0.25), 0.8, 0.4),             # la cucaracha-ish
            mk(self._fart(0.7), 1.0),                                                                # wet fart
            mk(tone(0.7, lambda t, p: saw(440 * (1 + 0.06 * math.sin(t * 50)), t) * 0.35
                    * min(1, p * 10) * (1 - p) ** 0.5), 0.8, 0.25),                                  # goat
            mk(tone(0.8, lambda t, p: (saw(233, t) + saw(294, t) + saw(349, t)) * 0.18), 1.0, 0.3),  # air horn
            mk(tone(1.6, lambda t, p: math.sin(_TAU * [784, 659, 698, 784, 880, 784, 698, 659]
                                               [min(7, int(p * 8))] * t) * 0.35), 0.7),              # ice cream
            # (v0.9) the stolen cop car's siren: wee-woo wee-woo
            mk(tone(1.0, lambda t, p: sq(740 if int(t * 4) % 2 == 0 else 587, t) * 0.25), 0.9, 0.3),
        ]
        # the ordinary honk event (clown car, the ice cream van answering): three soft beeps
        self.sounds[S.S_HONK] = [mk(_shape(_horn_wave(int(0.28 * self.rate), self.rate, 400.0 * m, 500.0 * m, 0.2),
                                           self.rate, 0.012, 0.05), 0.8) for m in (1.0, 0.92, 1.1)]

        # the ice cream van's endless jingle: an original four-bar music-box tune
        tune = (523, 659, 784, 659, 698, 880, 784, 0, 587, 698, 880, 698, 659, 784, 523, 0)
        def jingle(t, p):
            k = int(t / 0.22) % len(tune)
            f = tune[k]
            if not f:
                return 0.0
            ph = (t % 0.22) / 0.22
            return (math.sin(_TAU * f * t) * 0.6 + math.sin(2 * _TAU * f * t) * 0.2) * math.exp(-ph * 4) * 0.4
        self.loops["jingle"] = mk(tone(0.22 * len(tune), jingle), 1.6)
        self.loops["nos"] = mk(tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.25), 0.6)
        # loops. Alarm: 1100 Hz then 800 Hz (250 ms each = 275 and 200 whole cycles: seamless), softened.
        self.loops["alarm"] = mk(tone(0.5, lambda t, p: sq(1100 if p < 0.5 else 800, t) * 0.22), 0.7, 0.35, True)
        # Siren: a real wail (phase accumulates), 650 +- 250 Hz, 780 whole cycles in 1.2 s: seamless
        self.loops["siren"] = mk(self._sweep(1.2, lambda t, p: 650 + 250 * math.sin(p * _TAU), sqs, lambda p: 0.18),
                                 0.8, 0.3, True)
        self.loops["horn"] = mk(stock, 0.9, None, True)
        self.loops["fire"] = mk(self._lp(tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.15), 0.5, True), 1.8, None, True)

    def _fart(self, dur):
        """A low, wet, wobbling buzz. Engineering at its finest."""
        rnd = random.Random(99)
        out, ph, lp = [], 0.0, 0.0
        n = int(self.rate * dur)
        for i in range(n):
            t, p = i / self.rate, i / n
            f = 70 + 25 * math.sin(t * 23) + 30 * (1 - p)
            ph += f / self.rate
            buzz = 1.0 if ph % 1.0 < 0.3 else -0.4
            lp += (buzz + rnd.uniform(-0.6, 0.6) - lp) * 0.25
            out.append(lp * 0.7 * min(1, p * 20) * (1 - p) ** 0.6)
        return out

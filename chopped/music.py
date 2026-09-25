"""
music.py -- the soundtrack, composed by for-loop. An original dark Memphis /
phonk-flavoured trap beat (the Pouya / $uicideboy$ lane, not a copy of any of
their songs): 140 BPM half-time, F Phrygian, long sliding 808s, a clap on the
three, rattling hi-hat rolls, a pitched cowbell riff, a detuned music-box bell
and a bit of vinyl crackle.

It's rendered once at startup (in a background thread, ~1 s) into two layers
of exactly the same length that loop in sync:

  layer 0 "street": 808s, kick, clap, bell, crackle  -- always on
  layer 1 "heat":   hi-hats and cowbell              -- louder as the heat rises

No pygame in here: it returns plain lists of floats (-1..1), so it can be
tested headless and the Audio class turns them into Sounds.
"""

import math
import random

BPM = 140
STEPS_PER_BAR = 16
BARS = 8
ROOT_808 = 43.65            # F1: low enough to rattle a laptop, high enough to hear on one
ROOT_BELL = 349.23          # F4
PHRYGIAN = (0, 1, 3, 5, 7, 8, 10)   # the flat 2nd is what makes it sound like a bad idea

# the four-bar bass line (semitones from F), played twice; the last bar slides up for the turnaround
BASS_ROOTS = (0, 0, -4, -2, 0, 0, -4, 1)
# (step, length in steps, slide to next?) within each bar
BASS_HITS = ((0, 6, False), (6, 4, False), (10, 6, True))
# pitched cowbell riff, two bars long: (step, semitone)
COWBELL = ((0, 0), (3, 3), (6, 0), (8, 7), (11, 5), (14, 3),
           (16, 1), (19, 0), (22, -2), (24, 0), (26, 3), (28, 1), (30, 0))
# the bell melody: one note every half bar, over four bars
BELL = (8, 7, 3, 1, 0, 1, 3, -2)


def _semi(base, st):
    return base * 2.0 ** (st / 12.0)


class Beat:
    def __init__(self, rate=22050, seed=140):
        self.rate = rate
        self.rng = random.Random(seed)
        self.step = 60.0 / BPM / 4.0
        self.n = int(round(self.step * STEPS_PER_BAR * BARS * rate))

    def at(self, step):
        return int(round(step * self.step * self.rate))

    # ------------------------------------------------------------------ voices
    def s808(self, f0, f1, length):
        """Sine with a pitch drop at the front (the 'kick' part), a long body,
        a glide from f0 to f1, and a little saturation for grit."""
        r = self.rate
        n = int(length * r)
        out = [0.0] * n
        ph = 0.0
        for i in range(n):
            t = i / r
            glide = min(1.0, max(0.0, (t - length * 0.55) / (length * 0.35))) if f1 != f0 else 0.0
            f = f0 + (f1 - f0) * glide
            f *= 1.0 + 1.6 * math.exp(-t * 38.0)              # the punch
            ph += 2 * math.pi * f / r
            env = min(1.0, t * 400) * math.exp(-t * 1.6) * (1.0 - max(0.0, (t - length + 0.03) / 0.03))
            v = math.sin(ph) * env * 1.6
            out[i] = math.tanh(v)
        return out

    def kick(self):
        r = self.rate
        n = int(0.18 * r)
        out = [0.0] * n
        ph = 0.0
        for i in range(n):
            t = i / r
            ph += 2 * math.pi * (55 + 140 * math.exp(-t * 30)) / r
            out[i] = math.sin(ph) * math.exp(-t * 18)
        return out

    def clap(self):
        """Three quick noise slaps and a tail, high-passed so it cracks."""
        r = self.rate
        rng = self.rng
        n = int(0.35 * r)
        out = [0.0] * n
        prev = 0.0
        for i in range(n):
            t = i / r
            env = 0.0
            for k, t0 in enumerate((0.0, 0.011, 0.022)):
                if t >= t0:
                    env = max(env, math.exp(-(t - t0) * (140 if k < 2 else 18)))
            x = rng.uniform(-1, 1)
            out[i] = (x - prev) * env * 0.8
            prev = x
        return out

    def hat(self, length=0.045, amp=1.0):
        r = self.rate
        rng = self.rng
        n = int(length * r)
        out = [0.0] * n
        prev = 0.0
        for i in range(n):
            x = rng.uniform(-1, 1)
            out[i] = (x - prev) * 0.5 * amp * math.exp(-i / r * (60 / length * 0.05))
            prev = x
        return out

    def cowbell(self, f):
        """The 808 cowbell is two square waves a fifth-ish apart (540/800 Hz
        on the real box). Pitched down here and played as a riff."""
        r = self.rate
        n = int(0.16 * r)
        out = [0.0] * n
        f2 = f * 1.4814
        prev = 0.0
        for i in range(n):
            t = i / r
            a = 1.0 if (t * f) % 1.0 < 0.5 else -1.0
            b = 1.0 if (t * f2) % 1.0 < 0.5 else -1.0
            x = (a + b) * 0.5
            y = x - prev * 0.6                               # crude high-pass: clank, not boom
            prev = x
            out[i] = y * (math.exp(-t * 32) * 0.7 + math.exp(-t * 9) * 0.3)
        return out

    def bell(self, f, length=1.6):
        """Music-box bell: FM sine with a slow detuned twin (wobbly tape feel)."""
        r = self.rate
        n = int(length * r)
        out = [0.0] * n
        p1 = p2 = pm = 0.0
        for i in range(n):
            t = i / r
            env = math.exp(-t * 2.2) * min(1.0, t * 200)
            wob = 1.0 + 0.004 * math.sin(t * 5.5)
            pm += 2 * math.pi * f * 3.5 / r
            mod = math.sin(pm) * 1.2 * math.exp(-t * 6)
            p1 += 2 * math.pi * f * wob / r
            p2 += 2 * math.pi * f * 1.007 / r
            out[i] = (math.sin(p1 + mod) * 0.6 + math.sin(p2) * 0.25) * env
        return out

    # ------------------------------------------------------------------ mixing
    def add(self, buf, sound, start, gain):
        n = self.n
        for i, v in enumerate(sound):
            j = start + i
            if j >= n:
                j -= n                                        # wrap: the loop is seamless
            buf[j] += v * gain

    def compose(self):
        n = self.n
        street = [0.0] * n
        heat = [0.0] * n
        kick = self.kick()
        clap = self.clap()
        hats = {a: self.hat(0.04, a) for a in (0.5, 0.7, 1.0)}
        open_hat = self.hat(0.16, 0.8)
        bar = STEPS_PER_BAR
        for b in range(BARS):
            root = BASS_ROOTS[b]
            nxt = BASS_ROOTS[(b + 1) % BARS]
            for step, length, slide in BASS_HITS:
                f0 = _semi(ROOT_808, root + (12 if (b == 7 and step == 10) else 0))
                f1 = _semi(ROOT_808, nxt) if slide else f0
                self.add(street, self.s808(f0, f1, length * self.step), self.at(b * bar + step), 0.9)
            self.add(street, kick, self.at(b * bar), 0.7)
            self.add(street, kick, self.at(b * bar + 10), 0.55)
            self.add(street, clap, self.at(b * bar + 8), 0.6)
            if b % 4 == 3:
                self.add(street, clap, self.at(b * bar + 15), 0.3)          # ghost clap into the turnaround
            # hats: straight eighths, 32nd-note rolls closing out every other bar,
            # and a triplet stutter at the very end of the loop
            for s in range(0, bar, 2):
                self.add(heat, hats[0.7 if s % 4 == 0 else 0.5], self.at(b * bar + s), 0.5)
            if b % 2 == 1:
                for k in range(8):
                    self.add(heat, hats[1.0 if k % 2 == 0 else 0.5], self.at(b * bar + 12 + k * 0.5), 0.45)
            if b == 7:
                for k in range(6):
                    self.add(heat, hats[1.0], self.at(b * bar + 8 + k * (4 / 3.0)), 0.4)
            self.add(heat, open_hat, self.at(b * bar + 14), 0.25)
        for loop in range(BARS // 2):
            for step, st in COWBELL:
                self.add(heat, self.cowbell(_semi(ROOT_BELL * 1.5, st)), self.at(loop * 2 * bar + step), 0.35)
        for k, st in enumerate(BELL):
            self.add(street, self.bell(_semi(ROOT_BELL, st)), self.at(k * bar // 2), 0.28)
        # vinyl: crackle and a little hiss, because it was definitely recorded in a basement
        rng = self.rng
        for _ in range(int(n / self.rate * 30)):
            i = rng.randrange(n)
            street[i] += rng.uniform(-0.25, 0.25)
        for i in range(0, n, 3):
            street[i] += rng.uniform(-0.01, 0.01)
        return self._normalise(street), self._normalise(heat)

    @staticmethod
    def _normalise(buf, peak=0.92):
        m = max(1e-6, max(abs(v) for v in buf))
        k = peak / m
        return [v * k for v in buf]


def compose(rate=22050):
    """(street layer, heat layer), equal length, loopable."""
    return Beat(rate).compose()

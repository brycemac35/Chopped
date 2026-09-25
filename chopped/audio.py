"""
audio.py -- beeps, boops and crunches synthesised from raw sample buffers at
startup (no numpy, no files). If there's no audio device the whole thing
quietly turns into a very expensive no-op.
"""

import math
import random
import threading
from array import array

import pygame

from . import config as C
from . import music as MU
from . import sim as S

RATE = 22050
MASTER = 0.55          # keep it sane: car alarms are annoying enough at 55%


def _clip(v):
    return -32767 if v < -32767 else 32767 if v > 32767 else int(v)


class Audio:
    def __init__(self, enabled=True, music=True):
        self.ok = False
        self.sounds = {}
        self.loops = {}
        self.channels = {}
        self.loop_state = {}
        self.music_on = music
        self.music_tracks = None      # [calm, groove, hot] once the beat has been rendered
        self._music_bytes = None
        self.music_ch = None
        self.music_level = None
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 1, 512)
            init = pygame.mixer.get_init()
            if not init:
                return
            self.rate, _fmt, self.nch = init
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(8)
            self._build()
            for i, name in enumerate(("engine", "alarm", "siren", "horn", "fire", "jingle", "nos")):
                self.channels[name] = pygame.mixer.Channel(i)
                self.loop_state[name] = None
            self.music_ch = pygame.mixer.Channel(7)
            self.ok = True
            if music:
                threading.Thread(target=self._compose, name="chopped-beat", daemon=True).start()
        except Exception:
            self.ok = False       # no sound card, no problem. Imagine the crunches.

    # ------------------------------------------------------------------ synthesis
    def _mk(self, samples, vol=1.0):
        a = array("h")
        if self.nch == 1:
            a.extend(_clip(s * vol * MASTER * 32767) for s in samples)
        else:
            for s in samples:
                v = _clip(s * vol * MASTER * 32767)
                for _ in range(self.nch):
                    a.append(v)
        return pygame.mixer.Sound(buffer=a.tobytes())

    def _tone(self, dur, fn):
        n = int(self.rate * dur)
        return [fn(i / self.rate, i / n) for i in range(n)]

    def _build(self):
        rnd = random.Random(7)
        sq = lambda f, t: 1.0 if (t * f) % 1.0 < 0.5 else -1.0
        saw = lambda f, t: 2.0 * ((t * f) % 1.0) - 1.0
        env = lambda p, a=0.01, r=0.3: min(1.0, p / a) * (1.0 - p) ** (1.0 / max(r, 0.01)) if p < 1 else 0

        # crunch: filtered noise with a thump
        def crunch(dur, low):
            last = [0.0]
            def fn(t, p):
                last[0] += (rnd.uniform(-1, 1) - last[0]) * (0.35 if not low else 0.12)
                return (last[0] * 1.6 + 0.5 * math.sin(2 * math.pi * 60 * t)) * (1 - p) ** 2
            return self._tone(dur, fn)
        self.sounds[S.S_CRASH] = self._mk(crunch(0.25, False), 0.7)
        self.sounds[S.S_CRASH_BIG] = self._mk(crunch(0.5, True), 1.0)
        def boom(t, p):
            return (rnd.uniform(-1, 1) * 0.8 + math.sin(2 * math.pi * (50 - 30 * p) * t)) * (1 - p) ** 1.5
        self.sounds[S.S_BOOM] = self._mk(self._tone(1.1, boom), 1.0)
        self.sounds[S.S_SELL] = self._mk(self._tone(0.3, lambda t, p: sq(1320 if p > 0.35 else 990, t) * 0.4 * (1 - p)), 0.6)
        self.sounds[S.S_PICKUP] = self._mk(self._tone(0.08, lambda t, p: sq(660 + 600 * p, t) * 0.3 * (1 - p)), 0.6)
        self.sounds[S.S_DROP] = self._mk(self._tone(0.12, lambda t, p: sq(300 - 150 * p, t) * 0.3 * (1 - p)), 0.6)
        self.sounds[S.S_BREAKIN] = self._mk(self._tone(0.35, lambda t, p: (rnd.uniform(-1, 1) * 0.6 + sq(3000, t) * 0.2) * (1 - p) ** 3), 0.8)
        self.sounds[S.S_HOTWIRE] = self._mk(self._tone(0.7, lambda t, p: saw(40 + 50 * p + 8 * math.sin(40 * t), t) * 0.5 * min(1, p * 4)), 0.7)
        self.sounds[S.S_STRIP] = self._mk(self._tone(0.3, lambda t, p: sq(180, t) * 0.35 * (1 if (t * 30) % 1 < 0.4 else 0)), 0.6)
        self.sounds[S.S_HONK] = self._mk(self._tone(0.3, lambda t, p: sq(520 + 200 * math.sin(p * 9), t) * 0.35 * (1 - p)), 0.7)
        self.sounds[S.S_ARREST] = self._mk(self._tone(0.9, lambda t, p: sq(880 if int(p * 6) % 2 else 660, t) * 0.3), 0.7)
        self.sounds[S.S_RENT] = self._mk(self._tone(0.5, lambda t, p: sq(440 if p < 0.5 else 330, t) * 0.3 * (1 - p)), 0.7)
        self.sounds[S.S_CRUSH] = self._mk(crunch(0.8, True), 0.9)
        self.sounds[S.S_DELIVER] = self._mk(self._tone(0.6, lambda t, p: sq([523, 659, 784, 1046][min(3, int(p * 4))], t) * 0.3), 0.6)
        self.sounds[S.S_INSTALL] = self._mk(self._tone(0.4, lambda t, p: sq(220 * (1 + int(p * 3)), t) * 0.3 * (1 - p)), 0.6)
        self.sounds[S.S_YELP] = self._mk(self._tone(0.18, lambda t, p: sq(900 - 500 * p, t) * 0.25), 0.5)
        # ka-ching... in reverse. The sound of money leaving.
        self.sounds[S.S_BUY] = self._mk(self._tone(0.35, lambda t, p: sq(1320 if p < 0.4 else 880, t) * 0.35 * (1 - p)), 0.6)
        self.sounds[S.S_IGNITE] = self._mk(self._tone(0.4, lambda t, p: rnd.uniform(-1, 1) * 0.5 * p), 0.6)
        # v0.6: violence. A punch is a thud with a slap on top.
        self.sounds[S.S_PUNCH] = self._mk(self._tone(0.12, lambda t, p: (math.sin(2 * math.pi * (140 - 80 * p) * t)
                                                                          + rnd.uniform(-1, 1) * 0.6 * (1 - p) ** 6)
                                                     * (1 - p) ** 2), 0.8)

        # gunshots: a crack of white noise, a low body, and a tail that rings off the buildings
        def shot(dur, body, crack):
            last = [0.0]
            def fn(t, p):
                last[0] += (rnd.uniform(-1, 1) - last[0]) * (0.5 if p < 0.1 else 0.18)
                c = rnd.uniform(-1, 1) * crack * max(0.0, 1 - t / 0.012)
                return (c + last[0] * 1.4 * (1 - p) ** 3 + math.sin(2 * math.pi * body * (1 - 0.5 * p) * t)
                        * 0.8 * (1 - p) ** 4)
            return self._tone(dur, fn)
        self.sounds[S.S_PISTOL] = self._mk(shot(0.3, 120, 1.0), 0.8)
        self.sounds[S.S_SHOTGUN] = self._mk(shot(0.6, 70, 1.4), 1.0)
        # *click*. The loneliest sound in the game.
        self.sounds[S.S_EMPTY] = self._mk(self._tone(0.03, lambda t, p: sq(2400, t) * 0.4 * (1 - p)), 0.5)
        # a tyre going: bang, then a hiss that runs out of air
        self.sounds[S.S_TIRE] = self._mk(self._tone(0.7, lambda t, p: (rnd.uniform(-1, 1) * (1.0 if p < 0.05 else 0.35)
                                                                       * (1 - p))), 0.8)
        self.sounds[S.S_TRAP] = self._mk(self._tone(0.25, lambda t, p: (sq(90, t) * 0.3 + rnd.uniform(-1, 1) * 0.3)
                                                    * (1 - p) ** 2), 0.7)
        # the wallet chime: two coins and a guilty conscience
        self.sounds[S.S_ROB] = self._mk(self._tone(0.3, lambda t, p: sq(1568 if p < 0.3 else 2093, t) * 0.25 * (1 - p)), 0.6)
        # ---- v0.7 slapstick -----------------------------------------------------------
        self.sounds[S.S_WHOOSH] = self._mk(self._tone(0.25, lambda t, p: rnd.uniform(-1, 1) * 0.5 * math.sin(p * math.pi)), 0.5)
        # bonk: a hollow wooden knock with a little pitch drop, the universal sound of "ow"
        self.sounds[S.S_BONK] = self._mk(self._tone(0.18, lambda t, p: math.sin(2 * math.pi * (620 - 300 * p) * t)
                                                    * (1 - p) ** 3), 0.8)
        self.sounds[S.S_GNOME] = self._mk(self._tone(0.25, lambda t, p: sq(1400 + 900 * math.sin(p * 9), t) * 0.3
                                                     * (1 - p)), 0.6)                       # *squeak*
        self.sounds[S.S_JUMP] = self._mk(self._tone(0.12, lambda t, p: sq(300 + 500 * p, t) * 0.2 * (1 - p)), 0.4)
        # STRIKE: pins going over, then a tiny crowd going "YEAH"
        def strike(t, p):
            clatter = rnd.uniform(-1, 1) * (1 - p) ** 2 * (0.8 if int(t * 40) % 3 else 0.2)
            cheer = (sq(523, t) + sq(659, t) + sq(784, t)) * 0.08 * min(1, max(0, (p - 0.4) * 4)) * (1 - p)
            return clatter + cheer
        self.sounds[S.S_STRIKE] = self._mk(self._tone(1.0, strike), 0.8)
        # HOME RUN: the crack of a bat and an "ooooh"
        self.sounds[S.S_HOMERUN] = self._mk(self._tone(0.9, lambda t, p: (rnd.uniform(-1, 1) * max(0, 1 - t / 0.03))
                                                       + saw(200 + 120 * math.sin(p * 3), t) * 0.15 * p * (1 - p) * 4), 0.8)
        self.sounds[S.S_EJECT] = self._mk(self._tone(0.6, lambda t, p: (rnd.uniform(-1, 1) * 0.7 * max(0, 1 - t / 0.08)
                                                                       + sq(200 + 1200 * p, t) * 0.2 * (1 - p))), 0.9)
        # slide whistle, going down: the banana peel's theme tune
        self.sounds[S.S_SLIP] = self._mk(self._tone(0.6, lambda t, p: math.sin(2 * math.pi * (1500 - 1100 * p) * t)
                                                    * 0.4 * (1 - p * 0.5)), 0.7)
        self.sounds[S.S_MUNCH] = self._mk(self._tone(0.5, lambda t, p: rnd.uniform(-1, 1) * 0.4
                                                     * (1 if int(t * 12) % 2 else 0.1) * (1 - p)), 0.6)
        # a laugh: "ha" x4, a formant-ish square that drops in pitch each time
        self.sounds[S.S_LAUGH] = self._mk(self._tone(0.8, lambda t, p: sq(330 - int(p * 4) * 25, t) * 0.25
                                                     * (1 if (t * 5) % 1 < 0.55 else 0) * (1 - p * 0.6)), 0.5)
        self.sounds[S.S_MOD] = self._mk(self._tone(0.35, lambda t, p: (rnd.uniform(-1, 1) * 0.5 if (t * 30) % 1 < 0.3
                                                                       else 0) * (1 - p)), 0.6)      # ratchet
        self.sounds[S.S_SPRAY] = self._mk(self._tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.3 * min(1, p * 8)
                                                     * (1 - p)), 0.6)
        self.sounds[S.S_TRUNK] = self._mk(self._tone(0.2, lambda t, p: math.sin(2 * math.pi * (90 - 30 * p) * t)
                                                     * (1 - p) ** 2 + rnd.uniform(-1, 1) * 0.2 * (1 - p) ** 6), 0.8)
        self.sounds[S.S_WRIGGLE] = self._mk(self._tone(0.15, lambda t, p: sq(700 + 300 * math.sin(t * 60), t) * 0.2), 0.4)
        self.sounds[S.S_NOS] = self._mk(self._tone(0.5, lambda t, p: rnd.uniform(-1, 1) * 0.5 * (1 - p)), 0.7)
        # ---- horns (the mod shop sells worse ones), indexed by vehicles.HORN_*
        self.horns = [
            self._mk(self._tone(0.2, lambda t, p: (sq(392, t) + sq(494, t)) * 0.18), 0.9),            # stock
            self._mk(self._tone(0.5, lambda t, p: sq(700 + 200 * math.sin(p * 2 * math.pi), t)
                                * 0.3 * (1 if (p * 2) % 1 < 0.7 else 0)), 0.8),                         # clown
            self._mk(self._tone(1.2, lambda t, p: sq([392, 392, 392, 523, 659, 392, 392, 392, 523, 659, 0, 0]
                                                     [min(11, int(p * 12))], t) * 0.25), 0.8),         # la cucaracha-ish
            self._mk(self._fart(0.7), 1.0),                                                            # wet fart
            self._mk(self._tone(0.7, lambda t, p: saw(440 * (1 + 0.06 * math.sin(t * 50)), t) * 0.35
                                * min(1, p * 10) * (1 - p) ** 0.5), 0.8),                               # goat
            self._mk(self._tone(0.8, lambda t, p: (saw(233, t) + saw(294, t) + saw(349, t)) * 0.18), 1.0),  # air horn
            self._mk(self._tone(1.6, lambda t, p: math.sin(2 * math.pi * [784, 659, 698, 784, 880, 784, 698, 659]
                                                           [min(7, int(p * 8))] * t) * 0.35), 0.7),     # ice cream
        ]
        # the ice cream van's endless jingle: an original four-bar music-box tune
        tune = (523, 659, 784, 659, 698, 880, 784, 0, 587, 698, 880, 698, 659, 784, 523, 0)
        def jingle(t, p):
            k = int(t / 0.22) % len(tune)
            f = tune[k]
            if not f:
                return 0.0
            ph = (t % 0.22) / 0.22
            return (math.sin(2 * math.pi * f * t) * 0.6 + math.sin(4 * math.pi * f * t) * 0.2) * math.exp(-ph * 4) * 0.4
        self.loops["jingle"] = self._mk(self._tone(0.22 * len(tune), jingle), 0.7)
        self.loops["nos"] = self._mk(self._tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.25), 0.6)
        # loops
        self.loops["alarm"] = self._mk(self._tone(0.5, lambda t, p: sq(1100 if p < 0.5 else 750, t) * 0.22), 0.8)
        self.loops["siren"] = self._mk(self._tone(1.2, lambda t, p: sq(650 + 250 * math.sin(p * 2 * math.pi), t) * 0.18), 0.8)
        self.loops["horn"] = self._mk(self._tone(0.2, lambda t, p: (sq(392, t) + sq(494, t)) * 0.18), 0.9)
        self.loops["fire"] = self._mk(self._tone(0.6, lambda t, p: rnd.uniform(-1, 1) * 0.15), 0.6)
        # engine hum: 10 pre-pitched loops; we hop between them with speed
        self.engine = []
        for k in range(10):
            f = 38 + k * 11
            n = max(1, int(round(0.25 * f)))
            dur = n / f                                  # whole cycles -> seamless loop
            self.engine.append(self._mk(self._tone(dur, lambda t, p, f=f: (saw(f, t) * 0.5 + sq(f / 2, t) * 0.25) * 0.5), 0.5))

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

    # ------------------------------------------------------------------ music
    def _compose(self):
        """Background thread: render the beat and pre-mix three intensities.
        Pre-mixing (instead of two layers on two channels) keeps the hats
        locked to the 808s -- two channels can drift a whole audio buffer apart."""
        try:
            street, heat = MU.compose(self.rate)
            out = []
            for hv in (0.0, 0.45, 1.0):
                vals = [a * 0.8 + b * hv * 0.9 for a, b in zip(street, heat)]
                m = max(1e-6, max(abs(v) for v in vals))
                k = 0.95 / m * 32767 * MASTER
                pcm = array("h", (int(v * k) for v in vals))
                if self.nch > 1:
                    wide = array("h")
                    for v in pcm:
                        wide.extend((v,) * self.nch)
                    pcm = wide
                out.append(pcm.tobytes())
            self._music_bytes = out
        except Exception:
            self._music_bytes = None      # no beat is better than no game

    def update_music(self, level):
        """Call every frame. level 0 = menu/calm, 1 = on the job, 2 = heat's on.
        Changes land on the next loop boundary (the beat 'drops'), gaplessly,
        via Channel.queue()."""
        if not self.ok:
            return
        if self.music_tracks is None and self._music_bytes is not None:
            try:
                self.music_tracks = [pygame.mixer.Sound(buffer=b) for b in self._music_bytes]
            except Exception:
                self.music_tracks = []
            self._music_bytes = None
        if not self.music_tracks:
            return
        ch = self.music_ch
        if not self.music_on:
            if ch.get_busy():
                ch.stop()
            self.music_level = None
            return
        level = max(0, min(len(self.music_tracks) - 1, level))
        ch.set_volume(C.MUSIC_VOLUME)
        if not ch.get_busy():
            ch.play(self.music_tracks[level])
            self.music_level = level
        elif ch.get_queue() is None:
            ch.queue(self.music_tracks[level])
            self.music_level = level

    def toggle_music(self):
        self.music_on = not self.music_on
        return self.music_on

    # ------------------------------------------------------------------ playback
    def play(self, sid, dist=0.0):
        if not self.ok:
            return
        snd = self.sounds.get(sid)
        if snd is None:
            return
        vol = max(0.0, 1.0 - dist / 90.0)
        if vol <= 0.02:
            return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(vol)
            ch.play(snd)

    def set_loop(self, name, vol, variant=0):
        """Keep a named loop running at `vol` (0 stops it)."""
        if not self.ok:
            return
        ch = self.channels[name]
        snd = self.engine[variant] if name == "engine" else \
            self.horns[variant % len(self.horns)] if name == "horn" else self.loops[name]
        state = self.loop_state[name]
        if vol <= 0.02:
            if state is not None:
                ch.stop()
                self.loop_state[name] = None
            return
        if state != variant or not ch.get_busy():
            ch.play(snd, loops=-1)
            self.loop_state[name] = variant
        ch.set_volume(min(1.0, vol))

    def play_horn(self, h):
        """One honk of horn type h (the mod shop's try-before-you-buy)."""
        if not self.ok:
            return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(0.8)
            ch.play(self.horns[h % len(self.horns)], maxtime=1400)

    def stop_all(self):
        """Stops the sound effects; the music plays on (it's the menu music too)."""
        if self.ok:
            for ch in self.channels.values():
                ch.stop()
            for i in range(6, pygame.mixer.get_num_channels()):
                pygame.mixer.Channel(i).stop()
            for k in self.loop_state:
                self.loop_state[k] = None

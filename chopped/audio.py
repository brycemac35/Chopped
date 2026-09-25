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
            pygame.mixer.set_num_channels(20)
            pygame.mixer.set_reserved(6)
            self._build()
            for i, name in enumerate(("engine", "alarm", "siren", "horn", "fire")):
                self.channels[name] = pygame.mixer.Channel(i)
                self.loop_state[name] = None
            self.music_ch = pygame.mixer.Channel(5)
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
        snd = self.engine[variant] if name == "engine" else self.loops[name]
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

    def stop_all(self):
        """Stops the sound effects; the music plays on (it's the menu music too)."""
        if self.ok:
            for ch in self.channels.values():
                ch.stop()
            for i in range(6, pygame.mixer.get_num_channels()):
                pygame.mixer.Channel(i).stop()
            for k in self.loop_state:
                self.loop_state[k] = None

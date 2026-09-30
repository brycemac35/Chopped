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
from . import enginesynth as ES
from . import drivetrain as DT
from . import parts as PT
from . import soundscape as SC
from .sfxsynth import SfxSynth

RATE = 22050
MASTER = 0.55          # keep it sane: car alarms are annoying enough at 55%

# (v0.18) sounds that carry across the city, and the ones that ARE the shop door
LOUD_SFX = frozenset((S.S_BOOM, S.S_SHOTGUN, S.S_CRASH_BIG, S.S_GATE, S.S_AMBULANCE))
DOOR_SFX = frozenset((S.S_DOOR, S.S_BANG))


def _clip(v):
    return -32767 if v < -32767 else 32767 if v > 32767 else int(v)


class Audio(SfxSynth):
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
        self.engine_banks = {}        # layout name -> (band rpms, [(on-load Sound, off-load Sound)]) once rendered
        self._engine_bytes = {}       # the same as raw PCM, straight off the render thread
        self._eng_want = []           # layouts/tone banks the game has asked for (rendered first)
        self._eng_failed = False
        self._eng_urgent = False
        self.eng_ch = []              # [4 channels] per engine slot: 0 = your car, 1 = the loudest other.
                                      # index = (band parity) * 2 + (0 on load, 1 off load)
        self.eng_state = [[None] * 4, [None] * 4]
        self.tone_banks = {}          # "turbo" / "sc" -> (Hz list, [Sound]): the whistle and the whine
        self._tone_bytes = {}
        self.air = None               # airflow rush loop (turbo and supercharger share it)
        self._air_bytes = None
        self.whistle_state = [None, None, None]    # (tone A, tone B, air) channel tags
        self.oneshots = {}
        self.vol = dict(C.VOLUME_DEFAULTS)   # slider positions 0..1: master, music, sfx, engine
        # (v0.18) soundscape: the shop's dead zone, traffic honk budget, ambience beds, the chopper
        self.occ = SC.Occluder()
        self.horn_budget = SC.HornBudget()
        self.listener = (0.0, 0.0, 0.0)      # x, y, yaw of whoever's ears these are
        self.muffled = {}                    # sid -> a low-passed copy of a big bang, for the thud through a shut door
        self.blasts = {}                     # (pitch, kind) -> Sound: the traffic beeps, built from _scape_bytes
        self._scape_bytes = None
        self.scape_ch = None                 # (day bed, night bed, chopper) channels, the top three of the 32
        self.scape_snd = None
        self.scape_state = [0.0, 0.0, 0.0]
        self._listen_t = None
        self._jit = random.Random(11)        # per-play level/pick jitter (its own stream: never touches synthesis)
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(RATE, -16, 1, 512)
            init = pygame.mixer.get_init()
            if not init:
                return
            self.rate, _fmt, self.nch = init
            pygame.mixer.set_num_channels(40)      # (v0.18: 32 + 8; the scape keeps 29-31, the one-shot pool is 20-28 and 32-39)
            pygame.mixer.set_reserved(20)
            self._build()
            names = ("engine", "alarm", "siren", "horn", "fire", "jingle", "nos", "screech")
            for i, name in enumerate(names):
                self.channels[name] = pygame.mixer.Channel(i)
                self.loop_state[name] = None
            k = len(names)
            # engine slots take four channels each (two rpm bands x on/off load), the turbo/supercharger
            # tone two and the airflow one; 15-19 are the overflow from the old layout's 8-14
            self.eng_ch = [tuple(pygame.mixer.Channel(i) for i in (k, k + 1, k + 2, k + 3)),
                           tuple(pygame.mixer.Channel(i) for i in (15, 16, 17, 18))]
            self.wh_ch = (pygame.mixer.Channel(k + 4), pygame.mixer.Channel(k + 5), pygame.mixer.Channel(19))
            self.music_ch = pygame.mixer.Channel(k + 6)
            self.scape_ch = tuple(pygame.mixer.Channel(i) for i in (29, 30, 31))   # (unreserved, but always busy)
            self.ok = True
            threading.Thread(target=self._render_scape, name="chopped-scape", daemon=True).start()
            threading.Thread(target=self._render_engines, name="chopped-engines", daemon=True).start()
            if music:
                threading.Thread(target=self._compose, name="chopped-beat", daemon=True).start()
        except Exception:
            self.ok = False       # no sound card, no problem. Imagine the crunches.

    # ------------------------------------------------------------------ volume buses
    def set_volumes(self, master=None, music=None, sfx=None, engine=None):
        """Live volume sliders, 0..1 each (clamped; None leaves a bus alone). Nothing is
        re-synthesised: the gain is applied at Channel.set_volume time, and looping sounds
        are re-set every frame by the game, so changes land within a frame."""
        for k, v in (("master", master), ("music", music), ("sfx", sfx), ("engine", engine)):
            if v is not None:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                self.vol[k] = 0.0 if v != v else max(0.0, min(1.0, v))

    def get_volumes(self):
        return dict(self.vol)

    def gain(self, bus):
        """Final linear gain for a bus ('music'/'sfx'/'engine') = curve(master) * curve(bus).
        Slider -> gain is v**VOLUME_CURVE (2.0): loudness is roughly logarithmic, so a linear
        slider's midpoint (0.5 -> 0.25 = -12 dB) sounds about half as loud. No device or
        --mute means ok is False and nothing ever plays, so mute always wins."""
        if not self.ok:
            return 0.0
        return (self.vol["master"] * self.vol[bus]) ** C.VOLUME_CURVE

    # ------------------------------------------------------------------ synthesis
    def _pack(self, samples, vol=1.0, soft=None, fade=False):
        """Raw float samples -> PCM bytes (mono, or the mixer's channel count). soft = one-pole
        low-pass coefficient to take the edge off a square or saw; fade gives a 3 ms ramp at both
        ends if fade=True (one-shots; loops must not, they'd dip every lap); and the whole buffer is scaled down if it would peak above C.PEAK_CEIL, so
        nothing synthesised can clip. Fast path: no per-sample clamp, slice-assigned channels."""
        if soft:
            samples = self._lp(samples, soft, not fade)      # (a filtered loop pre-rolls, so its seam is clean)
        else:
            samples = list(samples)
        n = len(samples)
        if n == 0:
            return b""
        if fade:
            f = min(n // 4, int(self.rate * 0.003))
            for i in range(f):
                w = i / f
                samples[i] *= w
                samples[n - 1 - i] *= w
        peak = max(max(samples), -min(samples), 1e-9)
        k = vol * MASTER
        if peak * k > C.PEAK_CEIL:
            k = C.PEAK_CEIL / peak
        k *= 32767
        a = array("h", [int(s * k) for s in samples])
        if self.nch > 1:
            wide = array("h", bytes(2 * n * self.nch))
            for c in range(self.nch):
                wide[c::self.nch] = a
            a = wide
        return a.tobytes()

    def _mk(self, samples, vol=1.0, soft=None, fade=False):
        return pygame.mixer.Sound(buffer=self._pack(samples, vol, soft, fade))

    def _tone(self, dur, fn):
        n = int(self.rate * dur)
        return [fn(i / self.rate, i / n) for i in range(n)]

    def _build(self):
        rnd = random.Random(7)
        sq = lambda f, t: 1.0 if (t * f) % 1.0 < 0.5 else -1.0
        saw = lambda f, t: 2.0 * ((t * f) % 1.0) - 1.0
        self._build_sfx()             # (v0.18) every one-shot, horn and alarm loop: sfxsynth.py
        # ---- v0.8 car noises (the engine notes themselves render in the background) ----
        self.loops["screech"] = self._mk(ES.render_screech(self.rate), 0.55)
        self.oneshots["bov"] = self._mk(ES.render_bov(self.rate), 0.6)
        self.oneshots["flutter"] = self._mk(ES.render_bov(self.rate, flutter=True), 0.6)
        self.oneshots["pops"] = [self._mk(ES.render_pop(self.rate, 0.8 + 0.25 * k, k), 0.8) for k in range(3)]
        self.oneshots["shift"] = self._mk(ES.render_shift(self.rate), 0.5)
        # engine hum: 10 pre-pitched loops; we hop between them with speed
        self.engine = []
        for k in range(10):
            f = 38 + k * 11
            n = max(1, int(round(0.25 * f)))
            dur = n / f                                  # whole cycles -> seamless loop
            self.engine.append(self._mk(self._tone(dur, lambda t, p, f=f: (saw(f, t) * 0.5 + sq(f / 2, t) * 0.25) * 0.5), 0.5))

    # ------------------------------------------------------------------ engines (v0.8, rebuilt v0.18)
    # Render order when nobody asks for anything: the common cars first. A layout the game asks
    # for jumps the queue. Each is ~0.12 s of pure Python; the thread naps between them so the
    # game loop isn't starved of the GIL.
    IDLE_NAP = 0.02       # s slept between the bands of a layout nobody has asked for yet
    IDLE_GAP = 0.4        # ... and between such layouts
    ENGINE_JOBS = ("i4", "v8", "i6", "i4t", "v6", "vtec", "rotary", "diesel", "electric", "bike_i4", "single",
                   "turbo", "sc", "air")

    def _render_engines(self):
        """Background thread: engine layouts (each ENGINE_BANDS rpm points x on/off load), the turbo
        and supercharger tone banks and the airflow loop, as raw PCM. Turned into Sounds on the main
        thread (_bank) as they're needed."""
        import time
        try:
            done = set()
            while True:
                want = [w for w in reversed(list(self._eng_want)) if w not in done]
                name = want[0] if want else next((j for j in self.ENGINE_JOBS if j not in done), None)
                if name is None:
                    break
                asked = bool(want)
                self._eng_urgent = False
                # a layout the game is waiting for renders flat out; the read-ahead of the rest is spread
                # thin (a nap per band and between layouts) so it never holds the GIL against the frame loop
                self._render_job(name, 0.0 if asked else self.IDLE_NAP)
                done.add(name)
                if not asked:
                    time.sleep(self.IDLE_GAP)
        except Exception:
            self._eng_failed = True       # the old buzz it is, then

    def _render_job(self, name, nap=0.0):
        """Render one job to PCM. `nap` seconds are slept after each band/tone (background read-ahead)."""
        import time
        rate = self.rate
        if name == "air":
            self._air_bytes = self._pcm(ES.render_air(rate), 0.5)
        elif name in ("turbo", "sc"):
            if name == "turbo":
                freqs, parts, vol = ES.tone_bank(C.TURBO_HZ_FLOOR, C.TURBO_HZ_TOP * 1.03, C.TONE_RATIO), ES.TURBO_PARTIALS, 0.32
            else:
                freqs, parts, vol = ES.tone_bank(C.SC_WHINE_HZ[0], C.SC_WHINE_HZ[1], C.TONE_RATIO), ES.SC_PARTIALS, 0.3
            bands = []
            for f in freqs:
                x, _actual = ES.render_tone(f, rate, parts)
                bands.append(self._pcm(x, vol))
                if nap and not self._eng_urgent:
                    time.sleep(nap)
            self._tone_bytes[name] = (freqs, bands)
        else:
            voice, red_hint = ES.LAYOUT_VOICE[name]
            _idle, red = DT.layout_span(voice, red_hint)
            rpms, bands = [], []
            for r in DT.band_rpms(voice, red_hint):
                pair = []
                for load in (1.0, 0.0):
                    x, actual = ES.render_engine(name, r, rate, redline=red, vtec_rpm=red * C.VTEC_AT,
                                                 seed=voice, load=load)
                    pair.append(self._pcm(x, 0.55))
                    if nap and not self._eng_urgent:
                        time.sleep(nap)
                rpms.append(actual)
                bands.append(tuple(pair))
            self._engine_bytes[name] = (rpms, bands)

    def _pcm(self, samples, vol):
        a = array("h", (_clip(v * vol * MASTER * 32767) for v in samples))
        if self.nch > 1:
            wide = array("h")
            for v in a:
                wide.extend((v,) * self.nch)
            a = wide
        return a.tobytes()

    def _want(self, name):
        if name not in self._eng_want:
            self._eng_want.append(name)
            self._eng_urgent = True        # (the read-ahead in progress stops napping and finishes)

    def _bank(self, name):
        """The engine bank for a layout, or None while it's still rendering (asks for it)."""
        got = self.engine_banks.get(name)
        if got is None:
            pending = self._engine_bytes.pop(name, None)
            if pending is not None:
                try:
                    rpms, bands = pending
                    got = self.engine_banks[name] = (rpms, [tuple(pygame.mixer.Sound(buffer=b) for b in pr)
                                                            for pr in bands])
                except Exception:
                    got = None
            else:
                self._want(name)
        return got

    def _tone_bank(self, name):
        got = self.tone_banks.get(name)
        if got is None:
            pending = self._tone_bytes.pop(name, None)
            if pending is not None:
                try:
                    freqs, bands = pending
                    got = self.tone_banks[name] = (freqs, [pygame.mixer.Sound(buffer=b) for b in bands])
                except Exception:
                    got = None
            else:
                self._want(name)
        return got

    def engine_note(self, slot, voice, sc, rpm, vol, load=1.0, redline=0):
        """Keep engine slot 0 (your car) or 1 (the loudest car near you) singing at rpm.
        Four channels per slot: the two rpm bands either side of rpm (even bands on one pair,
        odd on the other, so the band being swapped out is always the silent one), each as an
        on-load and an off-load loop crossfaded by `load` (the two are rendered with the same
        firing times, so they blend rather than beat). `sc` is unused now: superchargers are
        their own layer (induction). `redline` tells the two bikes from the hatchbacks."""
        if not self.ok:
            return
        chans, state = self.eng_ch[slot], self.eng_state[slot]
        vol *= self.gain("engine")
        name = ES.layout_name(voice, redline)
        bank = self._bank(name) if vol > 0.02 else None
        if bank is None:
            for k in range(4):
                if state[k] is not None:
                    chans[k].stop()
                    state[k] = None
            if slot == 0:
                # not rendered yet (first second of the game): the old buzz
                self.set_loop("engine", vol * 0.8 if vol > 0.02 else 0, min(9, int(rpm / 800)), bus="engine", pregained=True)
            return
        if slot == 0:
            self.set_loop("engine", 0, bus="engine")
        rpms, sounds = bank
        i, wi, j, wj = DT.band_weights(rpms, rpm)
        load = max(0.0, min(1.0, load))
        for band, w in ((i, wi), (j, wj)):
            for L, lw in ((0, load), (1, 1.0 - load)):
                k = (band % 2) * 2 + L
                ch = chans[k]
                tag = (name, band, L)
                if state[k] != tag or not ch.get_busy():
                    ch.play(sounds[band][L], loops=-1)
                    state[k] = tag
                ch.set_volume(min(1.0, vol * (w ** 0.7) * lw))

    def induction(self, info, vol):
        """The turbo's whistle or the supercharger's whine, from drivetrain.Tacho.induction():
        (kind, Hz, level, air) or None. Pitch picks the two nearest tones in a finely spaced bank
        (~1.2 semitones apart) and crossfades them; level and airflow set their volumes."""
        if not self.ok:
            return
        state = self.whistle_state
        vol *= self.gain("engine")
        bank = None
        if info is not None and vol > 0.02:
            bank = self._tone_bank(info[0])
            if self.air is None and self._air_bytes is not None:
                try:
                    self.air = pygame.mixer.Sound(buffer=self._air_bytes)
                except Exception:
                    self._air_bytes = None
            elif self.air is None:
                self._want("air")
        if bank is None or info is None or (info[2] * vol <= 0.004 and info[3] * vol <= 0.004):
            for k in (0, 1, 2):
                if state[k] is not None:
                    self.wh_ch[k].stop()
                    state[k] = None
            return
        kind, hz, level, air = info
        freqs, sounds = bank
        if kind == "turbo" and hz < C.TURBO_HZ_FLOOR:
            level *= (hz / C.TURBO_HZ_FLOOR) ** 2          # too slow to whistle: fade out, don't just stop
        f = max(freqs[0], min(freqs[-1], hz))
        pos = math.log(f / freqs[0]) / math.log(C.TONE_RATIO)
        i = max(0, min(len(freqs) - 2, int(pos)))
        w = max(0.0, min(1.0, pos - i))
        for band, bw in ((i, 1.0 - w), (i + 1, w)):
            k = band % 2
            ch = self.wh_ch[k]
            if state[k] != (kind, band) or not ch.get_busy():
                ch.play(sounds[band], loops=-1)
                state[k] = (kind, band)
            ch.set_volume(min(1.0, vol * level * bw))
        if self.air is not None:
            ch = self.wh_ch[2]
            if state[2] is None or not ch.get_busy():
                ch.play(self.air, loops=-1)
                state[2] = "air"
            ch.set_volume(min(1.0, vol * air))

    def oneshot(self, name, vol=1.0, pick=0):
        """Engine-derived one-shots (pops, shifts, flutter, bov) ride the engine bus."""
        if not self.ok:
            return
        vol *= self.gain("engine")
        if vol <= 0.02:
            return
        snd = self.oneshots.get(name)
        if isinstance(snd, list):
            snd = snd[pick % len(snd)]
        if snd is None:
            return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(min(1.0, vol))
            ch.play(snd)

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
        g = self.gain("music")
        if g <= 0.0005:                    # slider at zero: keep it silent, cost nothing
            if ch.get_busy():
                ch.stop()
            self.music_level = None
            return
        ch.set_volume(min(1.0, C.MUSIC_VOLUME * g))
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
    def play(self, sid, dist=0.0, src=None):
        """One sound event. `src` = (x, y) of where it happened: with it the sound is panned by the
        listener's yaw, and silenced (or thumped, for the big bangs) when it's on the other side of
        the shop's shut doors. Without it, it's just `dist` metres away, dead ahead."""
        if not self.ok:
            return
        snd = self.sounds.get(sid)
        if snd is None:
            return
        rng = C.SFX_RANGE_LOUD if sid in LOUD_SFX else C.SFX_RANGE
        vol = max(0.0, 1.0 - dist / rng) ** C.SFX_FALLOFF_EXP * self.gain("sfx")
        vol *= 1.0 + self._jit.uniform(-C.SFX_VOL_JITTER, C.SFX_VOL_JITTER)
        left = right = vol
        if src is not None:
            f = self.occ.factor(src[0], src[1])
            if sid in DOOR_SFX:
                f = max(f, C.DEADZONE_DOOR_SOUND)          # the roller's noise is on the wall itself
            if f < 0.5 and sid in self.muffled:
                snd = self.muffled[sid]
                f = max(f, C.DEADZONE_THUD)                # a big bang still thumps through the bricks
            elif isinstance(snd, list):
                snd = self._jit.choice(snd)
            vol *= f
            lx, ly, yaw = self.listener
            left, right = SC.lr(vol, SC.pan(lx, ly, yaw, src[0], src[1]))
        if isinstance(snd, list):
            snd = self._jit.choice(snd)
        if max(left, right) <= 0.02:
            return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(min(1.0, left), min(1.0, right))
            ch.play(snd)

    # ------------------------------------------------------------------ the soundscape (v0.18)
    def listen(self, cmap, x, y, yaw, traps):
        """Call once a frame, before the sound events: where the ears are and which way they face.
        Feeds the pan and the shop's dead zone (the door traps in the snapshot say what's open)."""
        import time
        now = time.perf_counter()
        dt = 0.0 if self._listen_t is None else min(0.25, now - self._listen_t)
        self._listen_t = now
        self.listener = (x, y, yaw)
        self.occ.update(cmap, x, y, traps, dt)

    def occlusion(self, x, y):
        """0..1: how much of a sound at (x, y) reaches the listener (0 = behind the shut shop doors)."""
        return self.occ.factor(x, y)

    def engine_reach(self, dist, x, y, is_mine):
        """0..1 loudness weight of a car's engine, blow-offs, backfires and tyre squeal for the listener:
        your own car is always 1; anyone else's fades with distance and is muffled by the shop's walls
        exactly like every other sound (occlusion: 0 across the shut doors, easing in as they open)."""
        if is_mine:
            return 1.0
        return max(0.0, 1.0 - dist / C.ENGINE_HEAR_DIST) * self.occlusion(x, y)

    def honk_blast(self, pitch, kind, gain, src=None):
        """One traffic beep (soundscape.HornBudget picked it). Silent until the beeps have rendered."""
        if not self.ok or not self.blasts:
            return
        snd = self.blasts.get((pitch, kind))
        if snd is None:
            return
        vol = gain * self.gain("sfx")
        left = right = vol
        if src is not None:
            vol *= self.occ.factor(src[0], src[1])
            lx, ly, yaw = self.listener
            left, right = SC.lr(vol, SC.pan(lx, ly, yaw, src[0], src[1]))
        if max(left, right) <= 0.01:
            return
        ch = pygame.mixer.find_channel()
        if ch:
            ch.set_volume(min(1.0, left), min(1.0, right))
            ch.play(snd)

    def _render_scape(self):
        """Background thread: the traffic beeps, the day and night ambience beds and the chopper, as
        raw PCM. Sounds are made from them on the main thread (_scape_ready)."""
        try:
            from . import sfxsynth as SY
            rate = self.rate
            out = {"blasts": {k: self._pack(v, 0.9, None, True) for k, v in SY.horn_blasts(rate).items()}}
            out["beds"] = [self._pack(SY.ambience_bed(rate, night), 0.9) for night in (False, True)]
            out["heli"] = self._pack(SY.heli_loop(rate), 0.8)
            out["variants"] = [(sid, [self._pack(fn(m), vol, soft, True) for m in mults])
                               for sid, fn, vol, soft, mults in getattr(self, "pending_variants", ())]
            self._scape_bytes = out
        except Exception:
            self._scape_bytes = None      # no ambience is better than no game

    def _scape_ready(self):
        if self.scape_snd is None and self._scape_bytes is not None:
            try:
                b = self._scape_bytes
                self.blasts = {k: pygame.mixer.Sound(buffer=v) for k, v in b["blasts"].items()}
                self.scape_snd = [pygame.mixer.Sound(buffer=x) for x in b["beds"]] + [pygame.mixer.Sound(buffer=b["heli"])]
                for sid, datas in b["variants"]:                 # the extra pitches of the repeated one-shots
                    self.sounds[sid].extend(pygame.mixer.Sound(buffer=d) for d in datas)
            except Exception:
                self.scape_snd = []
            self._scape_bytes = None
        return bool(self.scape_snd)

    def update_scape(self, night, in_car, heli):
        """Every frame: the city bed (day/night crossfade, killed by the shop's dead zone, softer inside
        a car) and the chopper's thump while heat has one up (also dead-zoned)."""
        if not self.ok or not self._scape_ready():
            return
        g = self.gain("sfx")
        amb = C.AMBIENCE_VOLUME * g * (C.AMBIENCE_CAR_MUFFLE if in_car else 1.0)
        out = self.occ.leak if self.occ.zone else 1.0       # in the shop the outside is whatever the doors let in
        targets = (amb * out * (1.0 - night), amb * out * night, C.HELI_VOLUME * g * out * (1.0 if heli else 0.0))
        for i, ch in enumerate(self.scape_ch):
            v = self.scape_state[i]
            v += (targets[i] - v) * 0.08                   # ~0.2 s glide at 60 fps: the day/night blend, the chopper coming and going
            if abs(targets[i] - v) < 0.002:
                v = targets[i]
            self.scape_state[i] = v
            if v <= 0.002 and targets[i] <= 0.002:
                if ch.get_busy():
                    ch.stop()
                continue
            if not ch.get_busy():
                ch.play(self.scape_snd[i], loops=-1)
            ch.set_volume(min(1.0, v))

    def set_loop(self, name, vol, variant=0, bus="sfx", pregained=False, pan=0.0):
        """Keep a named loop running at `vol` (0 stops it). Scaled by its bus."""
        if not self.ok:
            return
        if not pregained:
            vol *= self.gain(bus)
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
        if pan:
            ch.set_volume(*[min(1.0, x) for x in SC.lr(vol, pan)])       # (v0.18) left/right by where the source is
        else:
            ch.set_volume(min(1.0, vol))

    def play_horn(self, h):
        """One honk of horn type h (the mod shop's try-before-you-buy)."""
        if not self.ok:
            return
        ch = pygame.mixer.find_channel()
        g = self.gain("sfx")
        if ch and g > 0.0005:
            ch.set_volume(0.8 * g)
            ch.play(self.horns[h % len(self.horns)], maxtime=1400)

    def stop_all(self):
        """Stops the sound effects; the music plays on (it's the menu music too)."""
        if self.ok:
            for ch in self.channels.values():
                ch.stop()
            for pair in list(self.eng_ch) + [self.wh_ch]:
                for ch in pair:
                    ch.stop()
            self.eng_state = [[None] * 4, [None] * 4]
            self.whistle_state = [None, None, None]
            for i in range(15, pygame.mixer.get_num_channels()):
                pygame.mixer.Channel(i).stop()
            for k in self.loop_state:
                self.loop_state[k] = None

"""
game.py -- the pygame application: window, menu, host/join flow, the frame
loop, and the --selftest bot that proves the thing boots without a human.
"""

import math
import os
import random
import sys
import time

import pygame

from . import config as C
from . import sim as S
from . import art
from .art import P, PixelFont
from .audio import Audio
from .mapgen import CityMap
from .net import Server, Client, get_lan_ip
from .render import Renderer
from .ui import Hud, Menu
from .upnp import UPnP

W, H = C.LOW_W, C.LOW_H


def parse_addr(text, default_port=C.DEFAULT_PORT):
    text = text.strip()
    if not text:
        return "127.0.0.1", default_port
    if text.count(":") == 1:
        host, port = text.split(":")
        try:
            return host.strip() or "127.0.0.1", int(port)
        except ValueError:
            return host.strip(), default_port
    return text, default_port


class Bot:
    """Scripted 'player' for --selftest: wanders, sprints, grabs the personal
    car, floors it, handbrakes, honks, gets out. Like a real player, but
    with slightly better impulse control."""
    def __init__(self, seed=1):
        self.rng = random.Random(seed)
        self.t = 0.0
        self.buttons = 0
        self.next_change = 0.0
        self.use = self.drop = self.exit = 0

    def step(self, dt, view):
        self.t += dt
        if self.t >= self.next_change:
            self.next_change = self.t + self.rng.uniform(0.3, 1.2)
            r = self.rng
            b = 0
            b |= S.B_UP if r.random() < 0.6 else 0
            b |= S.B_DOWN if r.random() < 0.1 else 0
            b |= r.choice((0, S.B_LEFT, S.B_RIGHT))
            b |= S.B_SPRINT if r.random() < 0.4 else 0
            b |= S.B_HANDBRAKE if r.random() < 0.15 else 0
            b |= S.B_HORN if r.random() < 0.1 else 0
            b |= S.B_USE if r.random() < 0.3 else 0
            self.buttons = b
            if r.random() < 0.2:
                self.use += 1
            if r.random() < 0.05:
                self.exit += 1
            if r.random() < 0.05:
                self.drop += 1
        return self.buttons, self.use, self.drop, self.exit


class App:
    def __init__(self, args):
        self.args = args
        self.selftest = bool(getattr(args, "selftest", False))
        pygame.init()
        pygame.display.set_caption("Chopped")
        self.fullscreen = False
        self.window_size = self._default_window()
        try:
            pygame.display.set_icon(art.make_icon(32))   # same badge as the exe icon
        except Exception:
            pass
        self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.low = pygame.Surface((W, H)).convert()
        self.scaled = None
        self.clock = pygame.time.Clock()
        self.font = PixelFont()
        self.audio = Audio(enabled=not getattr(args, "mute", False))
        self.menu = Menu(self.font, (getattr(args, "name", None) or os.environ.get("USERNAME")
                                     or os.environ.get("USER") or "CROOK")[:12].upper())
        self.state = "menu"
        self.server = None
        self.client = None
        self.upnp = None
        self.renderer = None
        self.hud = None
        self.paused = False
        self.running = True
        self.lan_ip = get_lan_ip()
        self.use_c = self.drop_c = self.exit_c = 0
        self.bot = Bot() if self.selftest else None
        self.frames = 0
        self.frames_in_play = 0
        self.snapshots_seen = 0
        self.max_players_seen = 0
        self.error = None
        self.connect_started = 0.0
        # menu backdrop: a real city, slowly panning. If we host, we reuse
        # this seed so the big pre-render isn't wasted.
        self.menu_seed = random.randrange(1, 2 ** 31)
        self.menu_map = CityMap(self.menu_seed)
        self.menu_surf = art.render_map(self.menu_map).convert()
        self.host_banner_until = 0.0

    def _default_window(self):
        try:
            dw, dh = pygame.display.get_desktop_sizes()[0]
        except Exception:
            dw, dh = C.DEFAULT_WINDOW
        # biggest whole-number scale that fits with room for the taskbar; up to
        # 6x so a DPI-aware window on a 4K laptop isn't postage-stamp sized
        k = max(1, min((dw - 60) // W, (dh - 120) // H, 6))
        return (W * k, H * k)

    # ------------------------------------------------------------------ flow
    def host(self):
        port = getattr(self.args, "port", None) or C.DEFAULT_PORT
        try:
            self.server = Server(port=port, map_seed=self.menu_seed)
        except OSError as e:
            self.menu.set_error("CAN'T OPEN UDP PORT %d (%s). ALREADY HOSTING?" % (port, e.__class__.__name__.upper()))
            self.server = None
            return
        self.server.start()
        if not self.selftest and not getattr(self.args, "no_upnp", False):
            self.upnp = UPnP(self.server.port).start()
        self.client = Client("127.0.0.1", self.server.port, self.menu.name, local=True)
        self.state = "connecting"
        self.connect_started = time.perf_counter()
        self.host_banner_until = time.perf_counter() + 12.0

    def join(self, text):
        host, port = parse_addr(text)
        self.client = Client(host, port, self.menu.name, local=False)
        if self.client.state == "failed":
            self.menu.set_error(self.client.error)
            self.client = None
            return
        self.state = "connecting"
        self.connect_started = time.perf_counter()

    def leave(self, msg=""):
        if self.client:
            self.client.leave()
            self.client = None
        if self.server:
            self.server.stop()
            self.server = None
        if self.upnp:
            self.upnp.close()
            self.upnp = None
        self.audio.stop_all()
        self.renderer = None
        self.hud = None
        self.paused = False
        self.state = "menu"
        if msg:
            self.menu.set_error(msg)
            if self.selftest:
                self.error = msg

    def _start_play(self):
        cm = self.client.map
        surf = self.menu_surf if cm.seed == self.menu_seed else None
        self.renderer = Renderer(cm, surf)
        self.hud = Hud(self.font, self.renderer.bank, self.renderer.minimap)
        self.state = "play"

    # ------------------------------------------------------------------ main loop
    def run(self, max_frames=None, max_seconds=None):
        t_start = time.perf_counter()
        last = t_start
        if self.selftest:
            join = getattr(self.args, "join", None)
            if join:
                self.join(join)
            else:
                self.host()
        elif getattr(self.args, "join", None):
            self.join(self.args.join)
        elif getattr(self.args, "host", False):
            self.host()
        while self.running:
            now = time.perf_counter()
            dt = min(0.1, now - last)
            last = now
            self._events()
            self._update(now, dt)
            self._draw(now, dt)
            self._present()
            self.frames += 1
            if max_frames is not None and self.frames >= max_frames:
                break
            if max_seconds is not None and now - t_start >= max_seconds:
                break
            self.clock.tick(C.FPS)
        self.leave()
        pygame.quit()

    def _events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.window_size = (max(W, ev.w), max(H, ev.h))
                self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                self.toggle_fullscreen()
            elif self.state == "menu":
                act = self.menu.handle(ev)
                if act == "host":
                    self.host()
                elif act == "join":
                    self.join(self.menu.join_addr)
                elif act == "quit":
                    self.running = False
            elif self.state == "connecting":
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    self.leave("CANCELLED")
            elif self.state == "play" and ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.paused = not self.paused
                elif self.paused and ev.key == pygame.K_q:
                    self.leave("YOU LEFT THE CREW")
                elif not self.paused:
                    if ev.key == pygame.K_e:
                        self.use_c += 1
                    elif ev.key == pygame.K_g:
                        self.drop_c += 1
                    elif ev.key == pygame.K_f:
                        self.exit_c += 1

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.scaled = None

    def _gather_input(self, dt, view):
        if self.bot is not None:
            b, u, d, e = self.bot.step(dt, view)
            return S.InputState(b, u, d, e)
        if self.paused:
            return S.InputState(0, self.use_c, self.drop_c, self.exit_c)
        k = pygame.key.get_pressed()
        b = 0
        if k[pygame.K_w] or k[pygame.K_UP]: b |= S.B_UP
        if k[pygame.K_s] or k[pygame.K_DOWN]: b |= S.B_DOWN
        if k[pygame.K_a] or k[pygame.K_LEFT]: b |= S.B_LEFT
        if k[pygame.K_d] or k[pygame.K_RIGHT]: b |= S.B_RIGHT
        if k[pygame.K_e]: b |= S.B_USE
        if k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT]: b |= S.B_SPRINT
        if k[pygame.K_SPACE]: b |= S.B_HANDBRAKE
        if k[pygame.K_h]: b |= S.B_HORN
        return S.InputState(b, self.use_c, self.drop_c, self.exit_c)

    def _update(self, now, dt):
        if self.state == "connecting":
            self.client.update(now)
            if self.client.state == "connected" and self.client.latest is not None:
                self._start_play()
            elif self.client.state in ("failed", "closed"):
                self.leave(self.client.error or "COULDN'T CONNECT")
            return
        if self.state != "play":
            return
        c = self.client
        view = c.view(now)
        c.inp = self._gather_input(dt, view)
        c.update(now)
        if c.state in ("failed", "closed"):
            self.leave(c.error or "DISCONNECTED")
            return
        self.snapshots_seen = c.latest.tick if c.latest else 0
        if c.latest:
            self.max_players_seen = max(self.max_players_seen, c.latest.nplayers)

    # ------------------------------------------------------------------ draw
    def _draw(self, now, dt):
        low = self.low
        if self.state in ("menu", "connecting"):
            mw, mh = self.menu_surf.get_size()
            t = now * 12
            x = int((mw - W) / 2 + math.sin(t / 97.0) * (mw / 2 - W))
            y = int((mh - H) / 2 + math.cos(t / 131.0) * (mh / 2 - H))
            low.blit(self.menu_surf, (0, 0), pygame.Rect(x, y, W, H))
            if self.state == "menu":
                self.menu.draw(low, now)
            else:
                low.fill(P["ink"], (0, H // 2 - 20, W, 40))
                dots = "." * (int(now * 3) % 4)
                self.font.draw(low, "CONNECTING TO %s:%d%s" % (self.client.addr[0], self.client.addr[1], dots),
                               W // 2, H // 2 - 10, P["gold"], scale=2, align="center")
                self.font.draw(low, "ESC TO CANCEL", W // 2, H // 2 + 8, P["metal_l"], align="center")
            return
        view = self.client.view(now)
        if view is None or view.me is None:
            low.fill(P["void"])
            self.font.draw(low, "WAITING FOR THE WORLD...", W // 2, H // 2, P["gold"], align="center")
            return
        self.frames_in_play += 1
        r = self.renderer
        me = view.me
        for kind, payload in self.client.pop_events():
            if kind == 0:
                self.hud.add_toast(payload[1], payload[0], now)
            else:
                sid, x, y = payload
                r.on_sfx(sid, x, y, me[4], me[5])
                self.audio.play(sid, math.hypot(x - me[4], y - me[5]))
        r.draw(low, view, now, dt)
        info = {"lines": self._info_lines(), "help_until": self.hud.help_until, "paused": self.paused}
        self.hud.draw(low, view, now, info)
        if self.server and now < self.host_banner_until and not self.paused:
            lines = self._host_lines()
            self.hud._panel((0, 0, 300, 8 * len(lines) + 4), 170)
            low.blit(self.hud._panel((0, 0, 300, 8 * len(lines) + 4), 170), (W // 2 - 150, 64))
            for i, (l, col) in enumerate(lines):
                self.font.draw(low, l, W // 2, 67 + i * 8, col, align="center")
        if self.paused:
            self.hud.draw_pause(low, info)
        self._audio_loops(view)

    def _host_lines(self):
        lines = [("YOU ARE HOSTING - TELL YOUR CREW:", P["gold"]),
                 ("LAN: %s:%d" % (self.lan_ip, self.server.port), P["white"])]
        if self.upnp:
            if self.upnp.public_ip:
                lines.append(("INTERNET: %s:%d" % (self.upnp.public_ip, self.server.port), P["white"]))
            lines.append((self.upnp.status, P["money"] if self.upnp.ok else
                          (P["white"] if not self.upnp.done else P["danger"])))
        return lines

    def _info_lines(self):
        c = self.client
        snap = c.latest
        lines = [("PLAYERS: %d / %d" % (snap.nplayers if snap else 0, C.MAX_PLAYERS), P["white"])]
        if self.server:
            lines += self._host_lines()[1:]
        else:
            lines.append(("CONNECTED TO %s:%d   PING %d MS" % (c.addr[0], c.addr[1], c.ping_ms), P["white"]))
        if snap:
            lines.append(("RUN %d" % snap.run, P["metal_l"]))
        return lines

    def _audio_loops(self, view):
        a = self.audio
        if not a.ok:
            return
        me = view.me
        mx, my = me[4], me[5]
        car = view.my_car
        if car is not None and me[2] in (S.DRIVER, S.PASSENGER):
            spd = math.hypot(car[9], car[10])
            a.set_loop("engine", 0.35, min(9, int(spd / 5)))
        else:
            a.set_loop("engine", 0)
        alarm = horn = siren = fire = 0.0
        for c in view.cars.values():
            d = math.hypot(c[7] - mx, c[8] - my)
            v = max(0.0, 1.0 - d / 60.0)
            if c[4] & 1:
                alarm = max(alarm, v)
            if c[4] & 4:
                horn = max(horn, v)
            if c[1] == S.COP:
                siren = max(siren, max(0.0, 1.0 - d / 120.0))
            if c[4] & 2:
                fire = max(fire, v)
        a.set_loop("alarm", alarm * 0.5)
        a.set_loop("horn", horn * 0.7)
        a.set_loop("siren", siren * 0.5)
        a.set_loop("fire", fire * 0.8)

    def _present(self):
        sw, sh = self.screen.get_size()
        k = min(sw // W, sh // H)
        if k >= 1:
            size = (W * k, H * k)
        else:
            s = min(sw / W, sh / H)
            size = (max(1, int(W * s)), max(1, int(H * s)))
        if self.scaled is None or self.scaled.get_size() != size:
            self.scaled = pygame.Surface(size).convert()
            self.screen.fill((0, 0, 0))
        pygame.transform.scale(self.low, size, self.scaled)
        self.screen.blit(self.scaled, ((sw - size[0]) // 2, (sh - size[1]) // 2))
        pygame.display.flip()


def run_selftest(args):
    """Boot the real app headless, host (or join) a game, let the bot play for
    a while, and exit 0 only if we actually got into a game and drew frames."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    if not getattr(args, "port", None):
        args.port = 0 if not getattr(args, "join", None) else C.DEFAULT_PORT
    app = App(args)
    frames = getattr(args, "frames", None)
    seconds = getattr(args, "seconds", None)
    if frames is None and seconds is None:
        frames = 300
    t0 = time.perf_counter()
    try:
        app.run(max_frames=frames, max_seconds=seconds)
    except Exception:
        import traceback
        traceback.print_exc()
        print("SELFTEST FAIL: exception")
        return 1
    dt = time.perf_counter() - t0
    ok = app.frames_in_play > 30 and app.snapshots_seen > 0 and not app.error
    print("SELFTEST %s: frames=%d play_frames=%d last_tick=%d players_seen=%d wall=%.1fs fps=%.1f audio=%s err=%s" % (
        "OK" if ok else "FAIL", app.frames, app.frames_in_play, app.snapshots_seen, app.max_players_seen, dt,
        app.frames / max(dt, 1e-6), app.audio.ok, app.error))
    sys.stdout.flush()
    return 0 if ok else 1

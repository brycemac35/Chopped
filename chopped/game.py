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
from . import protocol as PR
from . import vehicles as V
from . import story as STORY
from . import drivetrain as DT
from .parts import ASP_TURBO, ASP_SC, V_I6, V_DIESEL, SLOT_INDEX
from . import art
from .art import P, PixelFont
from .audio import Audio
from .mapgen import CityMap
from .net import Server, Client, get_lan_ips
from .render import Renderer
from .fp import FPRenderer
from .doomhud import DoomHud, VIEW_H
from .modshop import ModShop
from .ui import Menu
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
        self.fire = 0
        self.weapon = S.ARM_FISTS
        self.yaw = 0.0
        self.turn = 0.0

    def step(self, dt, view):
        self.t += dt
        self.yaw += self.turn * dt
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
            b |= S.B_TAUNT if r.random() < 0.05 else 0
            b |= S.B_FIRE if r.random() < 0.15 else 0
            self.buttons = b
            if r.random() < 0.2:
                self.use += 1
            if r.random() < 0.05:
                self.exit += 1
            if r.random() < 0.05:
                self.drop += 1
            if r.random() < 0.35:
                self.fire += 1                 # trigger discipline: none
            if r.random() < 0.1:
                self.weapon = r.randrange(S.ARM_COUNT)   # the server ignores what it doesn't own
            self.turn = r.choice((0.0, 0.0, -2.0, 2.0))
        return self.buttons, self.use, self.drop, self.exit, self.yaw, self.fire, self.weapon


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
        self.audio = Audio(enabled=not getattr(args, "mute", False),
                           music=not getattr(args, "no_music", False))
        self.menu = Menu(self.font, (getattr(args, "name", None) or os.environ.get("USERNAME")
                                     or os.environ.get("USER") or "CROOK")[:12].upper(),
                         save_file=getattr(args, "save", None))
        self.state = "menu"
        self.server = None
        self.client = None
        self.upnp = None
        self.renderer = None
        self.hud = None
        self.paused = False
        self.running = True
        ips = get_lan_ips()
        self.lan_ip, self.other_ips = ips[0], ips[1:3]
        self.use_c = self.drop_c = self.exit_c = 0
        self.fire_c = 0                # LMB / Ctrl taps, sent as a counter like E
        self.weapon = S.ARM_FISTS      # what you *want* in your hands; the server has the final say
        self.fire_anim = -9.0          # when you last pulled the trigger (for the view-model kick)
        self.bot = Bot() if self.selftest else None
        self.yaw = 0.0                 # where you're looking (first person); sent with every input
        self.pitch = 0.0               # looking up/down, in pixels of horizon shift (client-only)
        self.chase = False             # V: third-person chase camera when driving
        self.modshop = ModShop(self.font)
        self.ms_backdrop = None        # (v0.12.1) the frozen, darkened world behind the mod shop
        self.show_help = False         # (v0.13) the pause menu's INSTRUCTIONS window is open
        self.horn_heard = None
        self.tachos = {}               # car id -> drivetrain.Tacho (your car and the ones you can hear)
        self.tacho_view = None         # what the tachometer shows this frame
        self.pops_due = []             # [(when, volume, car id)] backfires still to go bang
        self.vtec_said = -99.0
        self.cam_yaw = None            # the chase camera's own, lagging, heading
        self.cam_orbit = 0.0           # mouse-look around the car in chase view
        self.orbit_idle = 0.0
        self.fp_mode = True            # Tab flips to the top-down automap
        self.fp = None
        self.last_state = None
        self.last_car_ang = 0.0
        self.mouse_grabbed = False
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
            # (v0.12.1) the main menu's save slot (or --save FILE). The selftest bot never
            # touches your slots -- it'd overwrite the real crew with a robot's bad decisions.
            save = getattr(self.args, "save", None) if self.selftest else self.menu.save_path()
            info = self.menu.slot_info() if save else None
            seed = (info or {}).get("map_seed") or self.menu_seed    # a saved run gets its own city back
            self.server = Server(port=port, map_seed=seed, save_path=save)
        except OSError as e:
            self.menu.set_error("CAN'T OPEN UDP PORT %d (%s). ALREADY HOSTING?" % (port, e.__class__.__name__.upper()))
            self.server = None
            return
        if self.selftest:
            self.server.world.give_loadout = True     # the bot came tooled up so every code path gets a go
        self.server.start()
        if not self.selftest and not getattr(self.args, "no_upnp", False):
            self.upnp = UPnP(self.server.port).start()
        self.client = Client("127.0.0.1", self.server.port, self.menu.name, local=True,
                             predict=not getattr(self.args, "no_predict", False))
        self.state = "connecting"
        self.connect_started = time.perf_counter()
        self.host_banner_until = time.perf_counter() + 12.0

    def join(self, text):
        host, port = parse_addr(text)
        lag = max(0.0, getattr(self.args, "fake_lag", 0.0) or 0.0) / 1000.0
        self.client = Client(host, port, self.menu.name, local=False, fake_lag=lag / 2,
                             predict=not getattr(self.args, "no_predict", False))
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
        self.fp = None
        self.hud = None
        self.paused = False
        self.show_help = False
        self.state = "menu"
        self._grab_mouse(False)
        self.menu.refresh_slots()            # (the slot's DAY/CASH just changed)
        if msg:
            self.menu.set_error(msg)
            if self.selftest:
                self.error = msg

    def _start_play(self):
        cm = self.client.map
        surf = self.menu_surf if cm.seed == self.menu_seed else None
        self.renderer = Renderer(cm, surf)
        self.fp = FPRenderer(cm, self.renderer.map_surf, W, VIEW_H)
        self.hud = DoomHud(self.font, self.renderer.bank, self.renderer.minimap)
        me = self.client.latest.players.get(self.client.pid) if self.client.latest else None
        if me is not None:
            self.yaw = self._facing_shop(me[4], me[5])
        self.state = "play"
        self._grab_mouse(True)

    def _facing_shop(self, x, y):
        """Spawn looking at the benches, so the first thing you see is the job."""
        bx, by, bw, bh = self.client.map.sell_bench
        return math.atan2(by - y, bx + bw / 2 - x)

    def _grab_mouse(self, on):
        """Mouse look: hide + grab the cursor (SDL then gives relative motion).
        Released whenever a menu is up, so the cursor isn't held hostage."""
        on = bool(on) and not self.selftest and self.state == "play" and not self.paused and not self.modshop.open
        if on == self.mouse_grabbed:
            return
        self.mouse_grabbed = on
        try:
            pygame.event.set_grab(on)
            pygame.mouse.set_visible(not on)
            pygame.mouse.get_rel()
        except pygame.error:
            pass

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
            elif self.state == "play" and self.modshop.open and not self.paused and \
                    ev.type in (pygame.KEYDOWN, pygame.MOUSEWHEEL) and self.modshop.handle(ev):
                pass                               # the mod shop ate it
            elif self.state == "play" and self.modshop.open and not self.paused and \
                    ev.type == pygame.MOUSEBUTTONDOWN and self.modshop.click(self._to_canvas(ev.pos), ev.button):
                pass
            elif self.state == "play" and ev.type == pygame.MOUSEBUTTONDOWN and self.paused and ev.button == 1:
                self._pause_action(self.hud.pause_hit(self._to_canvas(ev.pos)))
            elif self.state == "play" and ev.type == pygame.MOUSEBUTTONDOWN and not self.paused:
                if not self.mouse_grabbed:
                    self._grab_mouse(True)      # clicked back into the window; that click isn't a punch
                elif ev.button == 1:
                    self._fire()
            elif self.state == "play" and ev.type == pygame.MOUSEWHEEL and not self.paused:
                self._cycle_weapon(-1 if ev.y > 0 else 1)
            elif self.state == "play" and ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self._pause_action("back" if self.show_help else "resume" if self.paused else "pause")
                elif self.paused and ev.key == pygame.K_q and not self.show_help:
                    self._pause_action("leave")
                elif self.paused and ev.key == pygame.K_i:
                    self._pause_action("back" if self.show_help else "help")
                elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not self.paused:
                    self.hud.skip_speech()              # (v0.13) next line of dialogue, please
                elif ev.key == pygame.K_F5:
                    # (v0.12.1) save now. Only the host has the world to write down.
                    if self.server is not None and self.server.save_now():
                        pass                              # (the host's toast says how it went)
                    else:
                        self.hud.add_toast("ONLY THE HOST SAVES." if self.server is None else
                                           "NO SAVE SLOT PICKED (MAIN MENU: SAVE SLOT).", S.T_INFO,
                                           time.perf_counter())
                elif not self.paused:
                    if ev.key == pygame.K_e:
                        self.use_c += 1
                    elif ev.key == pygame.K_g:
                        self.drop_c += 1
                    elif ev.key == pygame.K_f:
                        self.exit_c += 1
                    elif ev.key == pygame.K_TAB:
                        self.fp_mode = not self.fp_mode
                    elif ev.key == pygame.K_F9 and self.fp is not None:
                        self.fp.big_heads = not self.fp.big_heads
                        self.hud.add_toast("BIG HEAD MODE: %s" % ("ON. OBVIOUSLY." if self.fp.big_heads else "OFF"),
                                           S.T_INFO, time.perf_counter())
                    elif ev.key == pygame.K_F10 and self.fp is not None:
                        self.fp.disco = not self.fp.disco
                        self.hud.add_toast("DISCO MODE: %s" % ("ON. FEEL IT." if self.fp.disco else "OFF"),
                                           S.T_INFO, time.perf_counter())
                    elif ev.key == pygame.K_F8 and self.fp is not None:
                        self.fp.fisheye = not self.fp.fisheye
                        self.hud.add_toast("FISHEYE LENS: %s" % ("ON. VERY EXTREME." if self.fp.fisheye else "OFF"),
                                           S.T_INFO, time.perf_counter())
                    elif ev.key == pygame.K_v:
                        self.chase = not self.chase
                        self.cam_yaw = None
                        if self.hud is not None:
                            self.hud.add_toast("CAMERA: %s" % ("CHASE (3RD PERSON)" if self.chase else "COCKPIT"),
                                               S.T_INFO, time.perf_counter())
                    elif ev.key in (pygame.K_LCTRL, pygame.K_RCTRL):
                        self._fire()
                    elif pygame.K_1 <= ev.key <= pygame.K_9 and ev.key - pygame.K_1 < S.ARM_COUNT:
                        self._select_weapon(ev.key - pygame.K_1)
                    elif ev.key == pygame.K_q:
                        self._cycle_weapon(1)
                    elif ev.key == pygame.K_m:
                        on = self.audio.toggle_music()
                        if self.hud is not None:
                            self.hud.add_toast("MUSIC ON" if on else "MUSIC OFF", S.T_INFO, time.perf_counter())

    # ------------------------------------------------------------------ weapons
    def _arsenal(self):
        snap = self.client.latest if self.client is not None else None
        return snap.arsenal if snap is not None else None

    def _select_weapon(self, slot):
        if S.arsenal_owns(self._arsenal(), slot):
            self.weapon = slot
        elif self.hud is not None:
            self.hud.add_toast("NO %s. THE CRATES IN THE SHOP SELL THEM." % S.ARM_NAMES[slot], S.T_INFO,
                               time.perf_counter())

    def _cycle_weapon(self, step):
        ars = self._arsenal()
        for k in range(1, S.ARM_COUNT + 1):
            slot = (self.weapon + step * k) % S.ARM_COUNT
            if S.arsenal_owns(ars, slot):
                self.weapon = slot
                return

    def _held_weapon(self):
        """What the view model shows: your pick, unless you ran out of it."""
        return self.weapon if S.arsenal_owns(self._arsenal(), self.weapon) else S.ARM_FISTS

    def _fire(self):
        self.fire_c += 1
        self.fire_anim = time.perf_counter()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.scaled = None

    def _gather_input(self, dt, view):
        if self.bot is not None:
            b, u, d, e, yaw, f, w = self.bot.step(dt, view)
            if f != self.fire_c:
                self.fire_c, self.fire_anim = f, time.perf_counter()
            self.weapon = w
            return S.InputState(b, u, d, e, yaw, f, w)
        weapon = self._held_weapon()
        mseq, mop, ma, mb = self.modshop.next_command()
        if self.paused or self.modshop.open:
            return S.InputState(0, self.use_c, self.drop_c, self.exit_c, self.yaw, self.fire_c, weapon,
                                mseq, mop, ma, mb)
        me = view.me if view is not None else None
        in_car = me is not None and me[2] in (S.DRIVER, S.PASSENGER)
        k = pygame.key.get_pressed()
        b = 0
        if k[pygame.K_w] or k[pygame.K_UP]: b |= S.B_UP
        if k[pygame.K_s] or k[pygame.K_DOWN]: b |= S.B_DOWN
        if k[pygame.K_a]: b |= S.B_LEFT
        if k[pygame.K_d]: b |= S.B_RIGHT
        if k[pygame.K_e]: b |= S.B_USE
        if k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT]: b |= S.B_SPRINT
        if k[pygame.K_SPACE]: b |= S.B_HANDBRAKE
        if k[pygame.K_h]: b |= S.B_HORN
        if k[pygame.K_t]: b |= S.B_TAUNT
        if k[pygame.K_x]: b |= S.B_HOP                        # (v0.8) hydraulics: boing. (v0.9) on foot: X option
        if k[pygame.K_c] and not in_car: b |= S.B_BOX         # (v0.9) the cardboard box
        if k[pygame.K_LCTRL] or k[pygame.K_RCTRL] or (self.mouse_grabbed and pygame.mouse.get_pressed()[0]):
            b |= S.B_FIRE                      # held: the haymaker winds up while you hold it
        rel, rely = pygame.mouse.get_rel() if self.mouse_grabbed else (0, 0)
        if in_car:
            # arrows steer too; the view is welded to the car (in chase view the mouse orbits it)
            if k[pygame.K_LEFT]: b |= S.B_LEFT
            if k[pygame.K_RIGHT]: b |= S.B_RIGHT
            if self.chase:
                self.cam_orbit = max(-math.pi, min(math.pi, self.cam_orbit + rel * C.MOUSE_SENS))
                self.orbit_idle = 0.0 if rel else self.orbit_idle + dt
                if self.orbit_idle > C.CHASE_ORBIT_RETURN:
                    self.cam_orbit *= math.exp(-3.0 * dt)
            else:
                self._look_updown(rely)
        else:
            turn = (1 if k[pygame.K_RIGHT] else 0) - (1 if k[pygame.K_LEFT] else 0)
            self.yaw = (self.yaw + turn * C.FP_TURN_SPEED * dt + rel * C.MOUSE_SENS) % (2 * math.pi)
            self._look_updown(rely)
        return S.InputState(b, self.use_c, self.drop_c, self.exit_c, self.yaw, self.fire_c, weapon,
                            mseq, mop, ma, mb)

    def _look_updown(self, rely):
        lim = VIEW_H * C.PITCH_LIMIT
        self.pitch = max(-lim, min(lim, self.pitch - rely * C.MOUSE_PITCH_SENS * VIEW_H))

    def _chase_cam(self, car, dt):
        """Behind and above the car, lagging a little, swinging toward where it's
        actually going so a drift shows as a drift. Pulled in if a wall's behind."""
        x, y, vx, vy, a = car[7], car[8], car[9], car[10], car[11]
        m = V.model(car[15])
        want = a
        spd = math.hypot(vx, vy)
        if spd > 5.0:
            va = math.atan2(vy, vx)
            want = a + ((va - a + math.pi) % (2 * math.pi) - math.pi) * C.CHASE_FOLLOW_VEL
        if self.cam_yaw is None:
            self.cam_yaw = want
        d = (want - self.cam_yaw + math.pi) % (2 * math.pi) - math.pi
        self.cam_yaw += d * min(1.0, C.CHASE_LAG * dt)
        yaw = self.cam_yaw + self.cam_orbit
        dist = C.CHASE_BACK + m.length * 0.75
        clear = self.client.map.ray_clear(x, y, yaw + math.pi, dist + 0.8, step=0.25)
        dist = max(1.2, min(dist, clear - 0.8))
        eye = C.CHASE_HEIGHT + m.height * 0.45
        return (x - math.cos(yaw) * dist, y - math.sin(yaw) * dist, yaw, eye)

    def _update(self, now, dt):
        level = 0
        if self.state == "play" and self.client is not None and self.client.latest is not None:
            snap = self.client.latest
            level = 2 if (snap.heat >= 35 or snap.cops) else 1
        self.audio.update_music(level)
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
        if view is not None and view.me is not None:
            me = view.me
            if me[2] in (S.DRIVER, S.PASSENGER) and view.my_car is not None:
                self.last_car_ang = view.my_car[11]
            elif self.last_state in (S.DRIVER, S.PASSENGER) and me[2] == S.FOOT:
                self.yaw = self.last_car_ang % (2 * math.pi)     # step out looking where you were driving
            self.last_state = me[2]
        c.inp = self._gather_input(dt, view)
        if self.bot is not None:
            self.yaw = c.inp.yaw
        c.update(now)
        if c.state in ("failed", "closed"):
            self.leave(c.error or "DISCONNECTED")
            return
        self.snapshots_seen = c.latest.tick if c.latest else 0
        if c.latest is not None:
            was = self.modshop.open
            self.modshop.sync(getattr(c.latest, "menu", None), getattr(c.latest, "cars", None))
            if self.modshop.open != was:
                self._grab_mouse(not self.modshop.open)
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
            elif kind == 2:
                r.on_shot(*payload)
                self.fp.on_shot(*payload)
            else:
                sid, x, y = payload
                r.on_sfx(sid, x, y, me[4], me[5])
                self.fp.on_sfx(sid, x, y, me[4], me[5], view.my_car)
                self.audio.play(sid, math.hypot(x - me[4], y - me[5]))
        self._engines(view)            # revs first: the tachometer and the engine notes both read them
        info = {"lines": self._info_lines(), "help_until": self.hud.help_until, "paused": self.paused,
                "menu": self.modshop.open,
                "fp": self.fp_mode, "yaw": self.yaw, "garage": self.client.map.garage_center,
                "in_garage": self.client.map.in_garage(me[4], me[5]), "weapon": self._held_weapon(),
                "story_target": self._story_target(view.snap)}
        if not self.modshop.open:
            self.ms_backdrop = None
        if self.ms_backdrop is not None:
            # (v0.12.1, Bryce: "theres a glitch when entering the mod shop, the UI flickers")
            # the menu used to sit on a see-through shade over the LIVE world and HUD, so the
            # radar, compass, toasts and Mo's idle animation all kept twitching away underneath
            # the text. Now the world is photographed once, darkened, and held still like a
            # waiting-room poster. Bonus: no raycasting while you're choosing hubcaps.
            low.blit(self.ms_backdrop, (0, 0))
        else:
            if self.fp_mode:
                self._draw_fp(low, view, now, dt)
            else:
                r.draw(low.subsurface((0, 0, W, VIEW_H)), view, now, dt)
            self.hud.draw(low, view, now, info)
            if self.modshop.open:
                shade_ = pygame.Surface((W, H), pygame.SRCALPHA)
                shade_.fill((12, 10, 20, 225))
                low.blit(shade_, (0, 0))
                self.ms_backdrop = low.copy()
        if self.server and now < self.host_banner_until and not self.paused and not self.modshop.open:
            lines = self._host_lines()
            # just under the help card (which ends at y=73), so neither covers the other
            low.blit(self.hud._panel(300, 8 * len(lines) + 4, 170), (W // 2 - 150, 78))
            for i, (l, col) in enumerate(lines):
                self.font.draw(low, l, W // 2, 81 + i * 8, col, align="center")
        if self.modshop.open:
            self.modshop.draw(low, view.snap.cash, now)
            # the world's frozen now, so the host's replies ("CAN'T AFFORD THAT", "FITTED")
            # get their own line down here instead of the ticker hidden under the title
            fresh = [t for t in self.hud.toasts if now - t[2] <= C.TOAST_TIME]
            for i, (text, col, _) in enumerate(fresh[-2:]):
                self.font.draw(low, text, W - 12, 300 + i * 9, col, align="right")
            if self.modshop.hover_horn != self.horn_heard:
                self.horn_heard = self.modshop.hover_horn
                if self.horn_heard is not None:
                    self.audio.play_horn(self.horn_heard)       # try before you buy
        if self.paused:
            info["help"] = self.show_help
            try:
                info["mouse"] = self._to_canvas(pygame.mouse.get_pos())
            except pygame.error:
                info["mouse"] = None
            self.hud.draw_pause(low, info)
        self._audio_loops(view)

    def _draw_fp(self, low, view, now, dt):
        me = view.me
        car = view.my_car
        state = me[2]
        hide = None
        pitch = self.pitch
        hires = None
        chase = False
        if state in (S.DRIVER, S.PASSENGER) and car is not None and self.chase:
            cam = self._chase_cam(car, dt)
            pitch = -VIEW_H * C.CHASE_PITCH
            hires = car[0]
            moving = 0.0
            chase = True
        elif state in (S.DRIVER, S.PASSENGER) and car is not None:
            a = car[11]
            m = V.model(car[15])
            if V.is_bike(car[15]):
                back = 0.25 if state == S.DRIVER else 0.75          # (pillion sits further back)
                cam = (car[7] - math.cos(a) * back, car[8] - math.sin(a) * back, a, C.FP_EYE_BIKE)
            else:
                cam = (car[7] + math.cos(a) * 0.3, car[8] + math.sin(a) * 0.3, a,
                       C.FP_EYE_CAR * (m.height / 1.55 if car[15] != V.SCOOTER else 1.0))
            hide = car[0] if car[15] != V.SCOOTER else None
            moving = 0.0
        elif state in (S.TUMBLE, S.DEAD):
            cam = (me[4], me[5], me[8], (0.5 if state == S.TUMBLE else 0.3) + me[15])
            pitch = 0
            moving = 0.0
        elif state == S.CARRIED:
            cam = (me[4], me[5], me[8] + math.pi, 1.4)      # upside down over a shoulder, facing backwards
            pitch = -VIEW_H * 0.2
            moving = 0.0
        else:
            spd = math.hypot(me[6], me[7])
            moving = min(1.0, spd / C.WALK_SPEED)
            bob = abs(math.sin(now * 9.0)) * C.FP_BOB * moving
            cam = (me[4], me[5], self.yaw, (C.FP_EYE if state != S.CUFFED else 1.3) + bob + me[15])
        self.fp.car_emitters(view, dt)
        self.fp.smoke_clouds(view)
        self.fp._clear_pops()
        surf = self.fp.draw(view, cam, self.client.pid, now, dt, view.snap.rent, self.renderer.bank, hide,
                            pitch=int(pitch), hires=hires)
        steer = 0.0
        if self.client.inp is not None:
            b = self.client.inp.buttons
            steer = (1.0 if b & S.B_RIGHT else 0.0) - (1.0 if b & S.B_LEFT else 0.0)
        self.hud.draw_overlay(surf, view, now, moving, steer, self._held_weapon(), self.fire_anim, chase=chase,
                              tacho=self.tacho_view)
        self.hud.drift_meter(surf, view, now, dt)
        low.blit(surf, (0, 0))

    def _host_lines(self):
        lines = [("YOU ARE HOSTING - TELL YOUR CREW:", P["gold"]),
                 ("LAN: %s:%d" % (self.lan_ip, self.server.port), P["white"])]
        if self.other_ips:
            lines.append(("ALSO (VPN/OTHER NETWORKS): %s" % ", ".join(self.other_ips), P["metal_l"]))
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
        if self.server and self.server.save_path:
            name = self.server.save_path.replace("\\", "/").rsplit("/", 1)[-1].upper()
            lines.append(("SAVING TO %s EVERY %d S.  F5: SAVE NOW" % (name, C.AUTOSAVE_INTERVAL), P["money"]))
        elif self.server:
            lines.append(("NOT SAVING THIS RUN (PICK A SAVE SLOT ON THE MAIN MENU)", P["metal_l"]))
        return lines

    def _audio_loops(self, view):
        a = self.audio
        if not a.ok:
            return
        me = view.me
        mx, my = me[4], me[5]
        alarm = horn = siren = fire = jingle = 0.0
        horn_type = 0
        for c in view.cars.values():
            d = math.hypot(c[7] - mx, c[8] - my)
            v = max(0.0, 1.0 - d / 60.0)
            if c[4] & 1:
                alarm = max(alarm, v)
            if c[4] & 4 and v > horn:
                horn, horn_type = v, c[17] & 7
            if c[1] == S.COP and not c[18] & PR.CX_PATROL:
                siren = max(siren, max(0.0, 1.0 - d / 120.0))
            if c[4] & 2:
                fire = max(fire, v)
            if c[15] == V.ICECREAM and (c[12] or c[1] == S.TRAFFIC):
                jingle = max(jingle, max(0.0, 1.0 - d / 50.0))    # it never stops. It never, ever stops.
        a.set_loop("alarm", alarm * 0.5)
        a.set_loop("horn", horn * 0.7, horn_type)
        a.set_loop("siren", siren * 0.5)
        a.set_loop("fire", fire * 0.8)
        a.set_loop("jingle", jingle * 0.5)
        mine = view.my_car
        a.set_loop("nos", 0.6 if (mine is not None and me[2] == S.DRIVER and mine[17] & 8) else 0.0)

    def _story_target(self, snap):
        """(v0.13) where the story's gold arrow points: whoever you need to talk to next."""
        ch = STORY.chapter(getattr(snap, "story_ch", 255))
        if ch is None:
            return None
        st = getattr(snap, "story_st", STORY.ST_DONE)
        if st == STORY.ST_TALK:
            key = ch.giver
        elif st == STORY.ST_ACTIVE and ch.kind == STORY.OBJ_TALK:
            key = ch.arg
        elif st == STORY.ST_ACTIVE and ch.kind == STORY.OBJ_BUY:
            key = "tommy"                                   # (his lot's sale sign is right by him)
        else:
            return None
        for npc in self.client.map.story_npcs:
            if npc[0] == key:
                return npc[2], npc[3], STORY.GIVERS[key]
        return None

    def _pause_action(self, what):
        """(v0.13) the pause menu's buttons, by click or by key."""
        if what == "pause":
            self.paused, self.show_help = True, False
        elif what == "resume":
            self.paused, self.show_help = False, False
        elif what == "help":
            self.show_help = True
        elif what == "back":
            self.show_help = False
        elif what == "leave":
            self.leave("YOU LEFT THE CREW")
            return
        else:
            return
        self._grab_mouse(not self.paused)

    def _to_canvas(self, pos):
        """Window pixels -> canvas pixels (undoes _present's scale and letterbox)."""
        sw, sh = self.screen.get_size()
        size = self.scaled.get_size() if self.scaled is not None else (W, H)
        ox, oy = (sw - size[0]) // 2, (sh - size[1]) // 2
        return int((pos[0] - ox) * W / size[0]), int((pos[1] - oy) * H / size[1])

    # ------------------------------------------------------------------ engines (v0.8)
    @staticmethod
    def _car_top(row):
        return C.COP_TOP_SPEED if row[1] == S.COP else V.model(row[15]).top

    def _engines(self, view):
        """Revs for your car and every running car you can hear; engine notes, the
        turbo whistle, blow-off valves, backfires and tyre screech from those."""
        a = self.audio
        now = time.perf_counter()
        dt = min(0.1, max(0.0, now - getattr(self, "_eng_t", now)))
        self._eng_t = now
        me, mine = view.me, view.my_car
        mx, my = me[4], me[5]
        pr = self.client.predictor if self.client is not None else None
        in_car = mine is not None and me[2] in (S.DRIVER, S.PASSENGER)
        seen = set()
        loud, loud_v = None, 0.0
        screech = 0.0
        self.tacho_view = None
        for row in view.cars.values():
            live = row[3] == S.RUNNING and (row[12] or row[1] in (S.COP, S.TRAFFIC)) and \
                row[5] & (1 << SLOT_INDEX["Engine"])
            d = math.hypot(row[7] - mx, row[8] - my)
            if not live or d > C.ENGINE_HEAR_DIST:
                continue
            is_mine = in_car and row[0] == mine[0]
            voice, asp, gears = DT.unpack_engine_byte(row[19])
            drive = row[20]
            thr = 1.0 if drive & PR.DR_THROTTLE else 0.0
            spin = 1.0 if drive & PR.DR_SPIN else 0.0
            burn = bool(drive & PR.DR_BURNOUT)
            spd = math.hypot(row[9], row[10])
            if is_mine and me[2] == S.DRIVER and pr is not None and pr.car is not None and pr.car.id == row[0]:
                c = pr.car                            # our own feet, not 100 ms ago's
                burn = c.burnout and c.wheelspin >= 1.0
                thr = 1.0 if (c.throttle > 0 or c.burnout) else 0.0
                spin = c.wheelspin
                spd = math.hypot(c.vx, c.vy)
            t = self.tachos.get(row[0])
            if t is None or (t.voice, t.asp, t.gears) != (voice, asp, gears):
                t = self.tachos[row[0]] = DT.Tacho(voice, asp, gears)
            seen.add(row[0])
            events = t.update(spd, thr, self._car_top(row), spin, burn, dt)
            near = 1.0 if is_mine else max(0.0, 1.0 - d / C.ENGINE_HEAR_DIST)
            self._engine_events(row, t, events, near, is_mine, now)
            # tyre noise: sideways, spinning, or locked up
            slip = abs(-row[9] * math.sin(row[11]) + row[10] * math.cos(row[11]))
            sq = max(min(1.0, (slip - 3.0) / 8.0), 0.9 if burn else 0.0, 0.6 * spin,
                     0.5 if drive & PR.DR_HANDBRAKE and spd > 4 else 0.0)
            screech = max(screech, sq * near)
            if is_mine:
                a.engine_note(0, voice, asp == ASP_SC, t.rpm, 0.55 * (0.65 + 0.35 * thr) if me[2] == S.DRIVER
                              else 0.4)
                if asp == ASP_TURBO:
                    a.turbo_whistle(t.boost, 0.5)
                self.tacho_view = (t.rpm, t.redline, t.gear, t.gears, t.boost, asp, t.vtec)
            else:
                v = near * (0.5 + 0.5 * thr) * 0.45
                if v > loud_v:
                    loud, loud_v = (voice, asp, t.rpm), v
        if not in_car:
            a.engine_note(0, 0, False, 0, 0.0)
            a.turbo_whistle(0.0, 0.0)
        elif self.tacho_view is None or self.tacho_view[5] != ASP_TURBO:
            a.turbo_whistle(0.0, 0.0)
        if loud is not None:
            a.engine_note(1, loud[0], loud[1] == ASP_SC, loud[2], loud_v)
        else:
            a.engine_note(1, 0, False, 0, 0.0)
        a.set_loop("screech", screech * 0.6)
        for cid in [k for k in self.tachos if k not in seen]:
            del self.tachos[cid]
        # backfires queued by a lift-off go bang one after another
        keep = []
        for when, vol, cid in self.pops_due:
            if when <= now:
                a.oneshot("pops", vol, random.randrange(3))
                if self.fp is not None:
                    self.fp.exhaust_pop(cid, now)
            else:
                keep.append((when, vol, cid))
        self.pops_due = keep

    def _engine_events(self, row, t, events, near, is_mine, now):
        a = self.audio
        drive = row[20]
        for ev in events:
            if ev == "shift" and is_mine:
                a.oneshot("shift", 0.35)
            elif ev == "bov" and t.asp == ASP_TURBO:
                a.oneshot("flutter" if t.voice in (V_I6, V_DIESEL) else "bov", 0.7 * near)
            elif ev == "lift" and drive & PR.DR_POPS:
                for k in range(random.randrange(2, 5)):
                    self.pops_due.append((now + 0.05 + k * random.uniform(0.07, 0.16), 0.8 * near, row[0]))
            elif ev == "limiter" and drive & PR.DR_POPS and drive & PR.DR_BURNOUT and random.random() < 0.5:
                self.pops_due.append((now, 0.7 * near, row[0]))         # two-step: brap-bang-brap
            elif ev == "vtec" and is_mine and now - self.vtec_said > 8.0:
                self.vtec_said = now
                self.hud.add_toast("VTEC JUST KICKED IN, YO!", S.T_MONEY, now)

    def _present(self):
        sw, sh = self.screen.get_size()
        if self.fp_mode:
            k = min(sw // W, sh // H)
            if k >= 1:
                size = (W * k, H * k)
            else:
                s = min(sw / W, sh / H)
                size = (max(1, int(W * s)), max(1, int(H * s)))
        else:
            # (v0.10, Bryce: "make the main map scale to window size") the automap is a
            # schematic overview, not pixel-critical art viewed up close, so it scales
            # smoothly to fill the window instead of snapping to whatever integer
            # multiple fits -- which on most window sizes left most of it black.
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
    music = "off" if not app.audio.music_on else ("ready" if app.audio.music_tracks else "pending")
    print("SELFTEST %s: frames=%d play_frames=%d last_tick=%d players_seen=%d wall=%.1fs fps=%.1f audio=%s music=%s err=%s" % (
        "OK" if ok else "FAIL", app.frames, app.frames_in_play, app.snapshots_seen, app.max_players_seen, dt,
        app.frames / max(dt, 1e-6), app.audio.ok, music, app.error))
    sys.stdout.flush()
    return 0 if ok else 1

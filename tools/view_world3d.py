"""
view_world3d.py -- a tiny standalone fly-camera viewer for chopped/world3d.py's static city.

    python tools/view_world3d.py [--seed N] [--night] [--shot]

Opens a VISIBLE window (moderngl + pygame), uploads World3D.gl_vertices() and the atlas (NEAREST,
no mips: the Doom look), and lets you fly about. The ground is just a flat colour per tile kind
(the real renderer paints the live map surface; this is only so the walls have something to
stand on).

  WASD fly, mouse look (click to grab), Space / Ctrl up / down, Shift fast, Tab toggle mouse grab,
  1..7 jump to a viewpoint, N toggle night (rebuilds), F2 screenshot, Esc quit.

Screenshots go to %TEMP%\\chopped_qa\\world3d\\. `--shot` renders the preset viewpoints from a
hidden window, saves them and exits (so a script can take the pictures).
"""

import argparse
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame
import moderngl

from chopped import config as C
from chopped import mapgen as M
from chopped import art
from chopped import world3d as W3

OUT_DIR = os.path.join(tempfile.gettempdir(), "chopped_qa", "world3d")

VS = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec2 in_uv;
in float in_shade;
out vec2 uv;
out float shade;
out float dist;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    uv = in_uv;
    shade = in_shade;
    dist = gl_Position.w;
}
"""
FS = """
#version 330
uniform sampler2D atlas;
uniform vec3 fog_col;
uniform float fog_k;
uniform float night;
in vec2 uv;
in float shade;
in float dist;
out vec4 frag;
void main() {
    vec3 c = texture(atlas, uv).rgb * shade * mix(1.0, 0.55, night);
    float f = 1.0 - exp(-dist * fog_k);
    frag = vec4(mix(c, fog_col, clamp(f, 0.0, 1.0)), 1.0);
}
"""


def perspective(fov_y, aspect, near, far):
    f = 1.0 / math.tan(fov_y / 2)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look(eye, yaw, pitch):
    """View matrix in GL space (x, z, y of the sim): yaw is the sim's own (forward = cos, sin in xy)."""
    cp = math.cos(pitch)
    fwd = np.array([math.cos(yaw) * cp, math.sin(pitch), math.sin(yaw) * cp])
    up0 = np.array([0.0, 1.0, 0.0])
    r = np.cross(fwd, up0)
    r /= np.linalg.norm(r)
    u = np.cross(r, fwd)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = r, u, -fwd
    m[0, 3], m[1, 3], m[2, 3] = -r @ eye, -u @ eye, fwd @ eye
    return m


class Viewer:
    def __init__(self, seed, night, hidden, size=(1280, 720)):
        self.seed, self.night = seed, night
        pygame.init()
        flags = pygame.OPENGL | pygame.DOUBLEBUF | (pygame.HIDDEN if hidden else 0)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 0)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption("world3d viewer")
        self.size = size
        self.ctx = moderngl.create_context()
        self.prog = self.ctx.program(vertex_shader=VS, fragment_shader=FS)
        self.cm = M.CityMap(seed)
        self.load()
        self.eye = np.array([256.0, 3.0, 300.0])         # GL space: (x, height, y)
        self.yaw, self.pitch = -math.pi / 2, 0.0
        self.views = self.presets()

    def load(self):
        t = time.time()
        self.world = W3.build_world(self.cm, self.night)
        print("built %d vertices in %.2f s (%s)" % (self.world.vertex_count(), time.time() - t, self.world.version))
        ctx = self.ctx
        v = self.world.gl_vertices()
        self.vbo = ctx.buffer(v.tobytes())
        self.vao = ctx.vertex_array(self.prog, [(self.vbo, "3f 2f 1f", "in_pos", "in_uv", "in_shade")])
        a = self.world.atlas
        self.tex = ctx.texture(a.get_size(), 4, pygame.image.tobytes(a, "RGBA", False))
        self.tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.tex.repeat_x = self.tex.repeat_y = False
        self.make_ground()

    def make_ground(self):
        cm, ctx = self.cm, self.ctx
        base = art.tile_base()
        n = cm.n
        img = np.zeros((n, n, 3), dtype=np.uint8)
        for ty in range(n):
            for tx in range(n):
                img[ty, tx] = base[cm.tiles[ty * n + tx]]
        self.gtex = ctx.texture((n, n), 3, img.tobytes())
        self.gtex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        m = n * C.TILE_M
        # GL space: (x, 0, y); uv straight across; one quad, two triangles
        q = np.array([[0, 0, 0, 0, 0, 1], [m, 0, 0, 1, 0, 1], [m, 0, m, 1, 1, 1],
                      [0, 0, 0, 0, 0, 1], [m, 0, m, 1, 1, 1], [0, 0, m, 0, 1, 1]], dtype=np.float32)
        self.gvbo = ctx.buffer(q.tobytes())
        self.gvao = ctx.vertex_array(self.prog, [(self.gvbo, "3f 2f 1f", "in_pos", "in_uv", "in_shade")])

    def presets(self):
        cm = self.cm
        gx, gy, gw, gh = cm.garage_rect
        T = C.TILE_M
        px, py, pw, ph = cm.precinct_outer if cm.precinct_outer else (100, 100, 28, 28)
        fs = cm.fence_shops[0] if cm.fence_shops else None
        fx, fy, fw, fh = fs["tiles"] if fs else (0, 0, 7, 7)
        s = -math.pi / 2
        v = {
            "1_shop_front_street": (gx + gw / 2, 1.8, gy + gh + 22, s, 0.05),
            "2_shop_front_close": (gx + 6, 1.7, gy + gh + 9, s - 0.5, 0.0),
            "3_shop_interior": (gx + gw / 2, 1.7, gy + gh - 5, math.pi * 0.0 + s, 0.05),
            "4_shop_interior_back": (gx + 6, 1.7, gy + 6, math.pi / 2 - 0.4, 0.0),
            "5_aerial": (gx + gw / 2, 130.0, gy + gh + 130, s, -0.75),
            "6_precinct": (px + pw / 2, 2.0, py + ph + 18, s, 0.08),
            "7_fence_garage": (fx * T + 14, 2.0, (fy + fh) * T + 16, s, 0.05),
            "8_alley_and_towers": (gx - 40, 1.8, gy + 60, -0.6, 0.15),
            "9_park": (cm.parks[0][0] * T + 14, 2.0, cm.parks[0][1] * T + 30, s, 0.0) if cm.parks else (50, 2, 50, s, 0),
        }
        return v

    def to_view(self, name):
        x, h, y, yaw, pitch = self.views[name]
        self.eye = np.array([x, h, y], dtype=np.float64)
        self.yaw, self.pitch = yaw, pitch

    def draw(self):
        ctx = self.ctx
        w, h = self.size
        sky = (0.52, 0.66, 0.86) if not self.night else (0.04, 0.05, 0.12)
        ctx.clear(*sky)
        ctx.enable(moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        ctx.front_face = "ccw"
        mvp = perspective(math.radians(78), w / h, 0.1, 900.0) @ look(self.eye, self.yaw, self.pitch)
        self.prog["mvp"].write(mvp.T.astype("f4").tobytes())
        self.prog["fog_col"].value = sky
        self.prog["fog_k"].value = 0.0035
        self.prog["night"].value = 1.0 if self.night else 0.0
        self.tex.use(0)
        self.prog["atlas"].value = 0
        ctx.disable(moderngl.CULL_FACE)
        self.gtex.use(0)
        self.gvao.render()
        ctx.enable(moderngl.CULL_FACE)
        self.tex.use(0)
        self.vao.render()

    def screenshot(self, name):
        os.makedirs(OUT_DIR, exist_ok=True)
        w, h = self.size
        data = self.ctx.screen.read(components=3, alignment=1)
        img = pygame.image.frombytes(data, (w, h), "RGB", True)
        path = os.path.join(OUT_DIR, name + ".png")
        pygame.image.save(img, path)
        print("saved", path)
        return path

    def run(self):
        clock = pygame.time.Clock()
        grab = True
        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        names = sorted(self.views)
        while True:
            dt = clock.tick(60) / 1000.0
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_TAB:
                        grab = not grab
                        pygame.event.set_grab(grab)
                        pygame.mouse.set_visible(not grab)
                    elif e.key == pygame.K_F2:
                        self.screenshot("shot_%d" % int(time.time()))
                    elif e.key == pygame.K_n:
                        self.night = not self.night
                        self.load()
                    elif pygame.K_1 <= e.key <= pygame.K_9:
                        k = e.key - pygame.K_1
                        if k < len(names):
                            self.to_view(names[k])
                if e.type == pygame.MOUSEMOTION and grab:
                    self.yaw += e.rel[0] * 0.0025
                    self.pitch = max(-1.5, min(1.5, self.pitch - e.rel[1] * 0.0025))
            k = pygame.key.get_pressed()
            sp = (60.0 if k[pygame.K_LSHIFT] else 12.0) * dt
            fx, fz = math.cos(self.yaw), math.sin(self.yaw)
            rx, rz = -fz, fx
            mv = np.zeros(3)
            if k[pygame.K_w]:
                mv += (fx, 0, fz)
            if k[pygame.K_s]:
                mv -= (fx, 0, fz)
            if k[pygame.K_d]:
                mv -= (rx, 0, rz)
            if k[pygame.K_a]:
                mv += (rx, 0, rz)
            if k[pygame.K_SPACE]:
                mv[1] += 1
            if k[pygame.K_LCTRL]:
                mv[1] -= 1
            self.eye += mv * sp
            self.eye[1] = max(0.3, self.eye[1])
            self.draw()
            pygame.display.flip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--night", action="store_true")
    ap.add_argument("--shot", action="store_true", help="render the preset viewpoints to PNGs and exit")
    ap.add_argument("--size", default="1280x720")
    a = ap.parse_args()
    size = tuple(int(v) for v in a.size.split("x"))
    v = Viewer(a.seed, a.night, a.shot, size)
    if a.shot:
        for name in sorted(v.views):
            v.to_view(name)
            v.draw()
            v.screenshot(name + ("_night" if a.night else ""))
        return
    v.run()


if __name__ == "__main__":
    main()

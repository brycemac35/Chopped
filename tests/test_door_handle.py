"""(v0.17.1) Bryce: "add a handle to close all the doors at once in the shop." One red lever on
the shop's west wall that shuts every door (walking + bays), or opens them all again."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped.mapgen import CityMap

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    w.streaker_t = 1e9
    for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
        del w.cars[cid]
    return w


def at_handle(w, p):
    """Stand a step off the wall, looking at the lever."""
    hx, hy, _f = w.map.door_handle
    p.x, p.y = hx + 1.0, hy
    p.input.yaw = p.ang = math.pi
    return p


def pull(w, p):
    w.step(DT)
    i = p.input
    p.input = S.InputState(buttons=i.buttons, use_count=i.use_count + 1, drop_count=i.drop_count,
                           exit_count=i.exit_count, yaw=i.yaw, fire_count=i.fire_count, weapon=i.weapon)
    w.step(DT)


class TestDoorHandle(unittest.TestCase):
    def test_pull_shuts_every_door_then_opens_them(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        self.assertEqual(len(w.shop_doors), 1 + C.N_BAYS)
        self.assertFalse(any(d.solid() for d in w.shop_doors))
        pull(w, p)
        step(w, C.DOOR_TIME + 0.2)
        self.assertTrue(all(d.solid() for d in w.shop_doors), "walking door and every bay shut")
        self.assertTrue(w.door_shut())
        pull(w, p)
        step(w, C.DOOR_TIME + 0.2)
        self.assertFalse(any(d.solid() for d in w.shop_doors), "and they all roll back up")

    def test_a_blocked_bay_stays_open_and_the_rest_shut(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        q = w.add_player("MO")
        stuck = w.shop_doors[2]
        q.x, q.y = stuck.x, stuck.y                       # standing right under bay 2's door
        pull(w, p)
        step(w, C.DOOR_TIME + 0.2)
        for d in w.shop_doors:
            self.assertEqual(d.solid(), d is not stuck, "everything but the blocked door is down")
        self.assertFalse(w.door_shut())
        # nothing crushed: q is still under an open door, and can walk away
        self.assertLess(stuck.open_t, 1.01)
        self.assertGreaterEqual(stuck.open_t, C.DOOR_PASSABLE)

    def test_blocked_door_is_named(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        q = w.add_player("MO")
        q.x, q.y = w.shop_doors[0].x, w.shop_doors[0].y
        seen = []
        real = w.toast
        w.toast = lambda text, *a, **k: (seen.append(text), real(text, *a, **k))[1]
        w.pull_handle(p)
        self.assertTrue(any("WALKING DOOR" in t and "BLOCKED" in t for t in seen), seen)

    def test_prompt_follows_the_state(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        w.step(DT)
        self.assertEqual(p.prompt, "PULL: SHUT ALL DOORS")
        pull(w, p)
        step(w, C.DOOR_TIME + 0.2)
        self.assertEqual(p.prompt, "PULL: OPEN ALL DOORS")

    def test_no_prompt_away_from_the_handle(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        p.x += 6.0
        w.step(DT)
        self.assertNotIn("PULL", p.prompt)

    def test_shutting_it_with_everyone_inside_clears_the_heat(self):
        w = world()
        p = at_handle(w, w.add_player("BRYCE"))
        self.assertTrue(w.map.in_garage(p.x, p.y))
        w.heat = 60.0
        pull(w, p)
        step(w, C.DOOR_TIME + 0.3)
        self.assertTrue(w.door_shut())
        self.assertEqual(w.heat, 0.0)

    def test_handle_is_inside_and_reachable_on_every_seed(self):
        for seed in (1, 7, 99, 4242, 31337):
            m = CityMap(seed)
            hx, hy, _f = m.door_handle
            spot = (hx + 1.0, hy)                         # where you stand to pull it
            self.assertTrue(m.in_garage(hx, hy), seed)
            self.assertTrue(m.in_garage(*spot), seed)
            self.assertFalse(m.solid_at(hx, hy), seed)
            self.assertFalse(m.solid_at(*spot), seed)
            for (rx, ry, rw, rh) in m.static_rects:
                for (x, y) in ((hx, hy), spot):
                    self.assertFalse(rx <= x <= rx + rw and ry <= y <= ry + rh,
                                     "seed %d: %s sits inside a solid rect" % (seed, (x, y)))
            walk = C.door_specs(m.garage_rect)[0]
            self.assertLess(math.hypot(hx - walk[1], hy - walk[2]), 5.0, "near the walking door")


if __name__ == "__main__":
    unittest.main()

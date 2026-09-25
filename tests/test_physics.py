"""Box collision: cars are 4.4 x 2.4 m rectangles now, not two circles in a
trench coat. These pin down the things players actually feel."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped.parts import Part

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def empty_world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    for cid in list(w.cars):
        del w.cars[cid]
    return w


def kei(w, x, y, ang, kind=S.CIV):
    car = S.Car(w.new_id(), kind, x, y, ang, {s: Part(q.type_id, 1.0) for s, q in S.personal_loadout().items()})
    car.state = S.RUNNING
    w.cars[car.id] = car
    return car


def south_face(w):
    """(x_left, x_right, y) of a building's south wall with open sidewalk below it."""
    for rx, ry, rw, rh in w.map.solid_rects:
        if rw >= 20 and w.map.tile_at(rx + rw / 2, ry + rh + 1) == 1:   # SIDEWALK below
            return rx, rx + rw, ry + rh
    raise AssertionError("no building face found")


class TestBoxCollision(unittest.TestCase):
    def test_corners_are_square_not_round(self):
        w = empty_world()
        x0, x1, fy = south_face(w)
        # alongside the wall and tilted 15 degrees: the rear corner pokes ~0.23 m
        # into the building, while the old rear circle would still clear it by
        # 4 cm -- exactly the "buildings feel round" complaint.
        car = kei(w, (x0 + x1) / 2, fy + 1.5, 0.0)
        car.ang = math.radians(15)
        top = min(y for _, y in car.corners())
        self.assertLess(top, fy, "setup: a corner should overlap the wall")
        w.step(DT)
        top = min(y for _, y in car.corners())
        self.assertGreaterEqual(top, fy - 0.02, "the box corner must be pushed out of the wall")

    def test_flush_head_on_hit_does_not_spin(self):
        w = empty_world()
        x0, x1, fy = south_face(w)
        car = kei(w, (x0 + x1) / 2, fy + S.HL + 1.0, -math.pi / 2)
        car.vy = -10.0
        step(w, 0.3)
        self.assertGreater(car.vy, 0.0, "bounced off the wall")
        self.assertLess(abs(car.w), 0.05, "a square hit on a flat wall shouldn't spin you")

    def test_scraping_along_a_wall_does_not_snag_on_tile_seams(self):
        w = empty_world()
        x0, x1, fy = south_face(w)
        # nose 4 degrees into the wall, moving along it at 20 m/s
        car = kei(w, x0 + 3.0, fy + 1.25, math.radians(-4))
        car.driver = w.add_player("SCRAPER").id      # driven, coasting (a parked car would brake hard)
        car.vx = 20.0
        worst = 0.0
        orig = w._crash
        crashes = []
        w._crash = lambda c, dv, nx, ny: crashes.append(dv)
        for _ in range(int(0.6 * C.SIM_HZ)):
            w.step(DT)
            worst = max(worst, car.impact_dv)
            if car.x > x1 - 3.0:
                break
        w._crash = orig
        self.assertGreater(car.vx, 12.0, "should keep most of its speed along the wall")
        self.assertEqual(crashes, [], "a glancing scrape isn't a crash (max dv %.1f)" % worst)
        self.assertGreaterEqual(min(y for _, y in car.corners()), fy - 0.05)

    def test_t_bone_moves_and_spins_the_victim(self):
        w = empty_world()
        x0, x1, fy = south_face(w)
        y = fy + 10.0                                   # middle of the road
        victim = kei(w, x0 + 12.0, y, 0.0)
        victim.state = S.LOCKED
        # ram the victim's side, well behind its centre: it should shove AND rotate
        ram = kei(w, x0 + 12.0 - 1.4, y + 5.0, -math.pi / 2)
        ram.vy = -15.0
        a0, peak = victim.ang, 0.0
        for _ in range(int(0.4 * C.SIM_HZ)):
            w.step(DT)
            peak = max(peak, abs(victim.w))
        self.assertLess(victim.y, y - 0.3, "victim gets shoved")
        # (yaw rate chases the steering target fast -- arcade tuning -- so check
        # the peak spin and the heading it left behind, not the spin right now)
        self.assertGreater(peak, 0.5, "off-centre hit spins it")
        self.assertGreater(abs(victim.ang - a0), math.radians(1.0))

    def test_people_bump_into_the_box(self):
        w = empty_world()
        x0, x1, fy = south_face(w)
        car = kei(w, x0 + 12.0, fy + 10.0, 0.0)
        car.state = S.LOCKED
        p = w.add_player("BOB")
        # walk straight into the front-left corner region, which two circles left open
        p.x, p.y = car.x + 2.0, car.y - 1.0
        w.step(DT)
        lx = (p.x - car.x) * math.cos(car.ang) + (p.y - car.y) * math.sin(car.ang)
        ly = -(p.x - car.x) * math.sin(car.ang) + (p.y - car.y) * math.cos(car.ang)
        outside = abs(lx) >= S.HL + C.PLAYER_RADIUS - 0.01 or abs(ly) >= S.HW + C.PLAYER_RADIUS - 0.01
        self.assertTrue(outside, "player ended up inside the car at local (%.2f, %.2f)" % (lx, ly))


if __name__ == "__main__":
    unittest.main()

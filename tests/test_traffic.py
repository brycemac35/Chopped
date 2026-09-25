"""Moving traffic and pedestrians who have the sense to run."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped.mapgen import ROAD, LOT
from chopped.parts import SLOTS

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def traffic(w):
    return [c for c in w.cars.values() if c.kind == S.TRAFFIC]


def lone_traffic_car(w):
    """Exactly one traffic car, heading east mid-block south of the shop."""
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    for c in traffic(w):
        del w.cars[c.id]
    shop_i = C.BLOCKS // 2
    j = shop_i + 1                                  # the road band just south of the shop block
    w.traffic_target = 1
    car = S.Car(w.new_id(), S.TRAFFIC, 0, 0, 0.0, S.kei_loadout(w.rng), color=3)
    car.x, car.y = w._lane_point(shop_i + 1, j, (1, 0), -30.0)
    car.vx = 10.0
    car.tdir, car.node = (1, 0), (shop_i + 1, j)
    car.route = [w._lane_point(shop_i + 1, j, (1, 0), -8.0)]
    car.route_prev = w._lane_point(shop_i, j, (1, 0), 8.0)
    w.cars[car.id] = car
    return car


class TestTraffic(unittest.TestCase):
    def test_traffic_drives_the_grid_without_leaving_the_road(self):
        w = S.World(map_seed=99, rng_seed=5)
        p = w.add_player("WATCHER")
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw / 2, gy + 6                 # safely inside the shop
        crashes = []
        orig = w._crash
        w._crash = lambda car, dv, nx, ny: (crashes.append((car.kind, dv)), orig(car, dv, nx, ny))
        speeds, offroad, samples, counts = [], 0, 0, []
        for _ in range(30 * C.SIM_HZ):
            w.step(DT)
            counts.append(len(traffic(w)))
            for c in traffic(w):
                samples += 1
                speeds.append(c.speed())
                if w.map.tile_at(c.x, c.y) not in (ROAD, LOT):
                    offroad += 1
        self.assertGreaterEqual(sum(counts) / len(counts), C.TRAFFIC_COUNT - 0.6,
                                "the fleet stays topped up (cars far away get recycled nearby)")
        self.assertGreater(sum(speeds) / len(speeds), 7.0, "traffic should actually go places")
        self.assertLess(offroad / samples, 0.01, "no joyriding on the pavement")
        self.assertEqual([k for k, _ in crashes if k == S.TRAFFIC], [], "traffic shouldn't crash on its own")

    def test_keeps_right(self):
        w = S.World(map_seed=99, rng_seed=5)
        car = lone_traffic_car(w)
        road_centre = w.map.road_centre(car.node[1])
        step(w, 1.0)
        self.assertGreater(car.y, road_centre + 0.8, "eastbound traffic drives in the south (right) lane")

    def test_stops_for_a_person_honks_and_does_not_confuse_cops(self):
        w = S.World(map_seed=99, rng_seed=5)
        car = lone_traffic_car(w)
        p = w.add_player("JAYWALKER")
        p.x, p.y = car.x + 18.0, car.y
        cop = S.Car(w.new_id(), S.COP, car.x - 20.0, car.y - 3.0, 0.0, {s: None for s in SLOTS})
        w.cars[cop.id] = cop
        honked, stopped_at = False, None
        x0 = p.x
        for _ in range(int(4.5 * C.SIM_HZ)):
            w.step(DT)
            honked = honked or car.horn
            if stopped_at is None and car.speed() < 0.3:
                stopped_at = p.x - car.x
            p.x = x0                                     # stand still (don't let physics nudge us)
        self.assertIsNotNone(stopped_at, "should have stopped")
        self.assertGreater(stopped_at, S.HL + 1.0, "short of the person, not on them")
        self.assertEqual(p.state, S.FOOT, "and not run anyone over")
        self.assertTrue(honked, "a blocked driver leans on the horn")
        self.assertLessEqual(cop.confused_t, 0, "traffic horns aren't a player tactic")

    def test_no_prompt_to_steal_a_moving_car(self):
        w = S.World(map_seed=99, rng_seed=5)
        car = lone_traffic_car(w)
        p = w.add_player("BOB")
        p.x, p.y = car.to_world(0.0, -2.0)
        p.ang = math.atan2(car.y - p.y, car.x - p.x)
        key, label, _, _ = w._find_interaction(p)
        self.assertIsNone(key)
        self.assertNotIn(str(car.id), label)

    def test_hard_hit_makes_the_driver_bail_and_leave_it_running(self):
        w = S.World(map_seed=99, rng_seed=5)
        car = lone_traffic_car(w)
        n0 = len(w.npcs)
        w._crash(car, C.CRASH_EJECT_DV + 1.0, 0.0, 1.0)
        self.assertEqual(car.kind, S.CIV)
        self.assertEqual(car.state, S.RUNNING, "the driver legged it with the engine running")
        self.assertFalse(car.stolen)
        runners = [n for n in w.npcs.values() if n.ttl > 0]
        self.assertEqual(len(w.npcs), n0 + 1)
        self.assertEqual(len(runners), 1)
        self.assertGreater(runners[0].flee_t, 0)
        w.pickups.clear()                    # (the crash may have dropped a door right there)
        car.vx = car.vy = 0.0
        p = w.add_player("OPPORTUNIST")
        p.x, p.y = car.to_world(0.0, 2.0)
        p.ang = math.atan2(car.y - p.y, car.x - p.x)
        key, label, _, act = w._find_interaction(p)
        self.assertIn("DRIVE", label)
        heat0 = w.heat
        act()
        self.assertEqual(p.state, S.DRIVER)
        self.assertTrue(car.stolen, "hopping in makes it a stolen car")
        self.assertGreaterEqual(w.heat, heat0 + C.HEAT_BREAKIN - 0.01)
        w._leave_car(p)
        step(w, 41.0)
        self.assertNotIn(runners[0].id, w.npcs, "the runner eventually runs off the map")

    def test_small_bump_just_shakes_them(self):
        w = S.World(map_seed=99, rng_seed=5)
        car = lone_traffic_car(w)
        w._crash(car, C.CRASH_DENT_DV + 0.5, 0.0, 1.0)
        self.assertEqual(car.kind, S.TRAFFIC)
        step(w, 1.0)
        self.assertLess(car.speed(), 1.0)
        self.assertTrue(car.horn)
        step(w, C.TRAFFIC_SHAKEN_TIME + 2.0)
        self.assertGreater(car.speed(), 3.0, "then they drive off, muttering")


class TestFleeingPedestrians(unittest.TestCase):
    def _ped_on_sidewalk(self, w):
        ped = next(n for n in w.npcs.values() if n.kind == S.PED)
        for n in list(w.npcs.values()):
            if n is not ped:
                del w.npcs[n.id]
        ped.dirx = ped.diry = 0
        ped.turn_t = 1e9
        return ped

    def test_speeding_car_sends_pedestrian_diving(self):
        w = S.World(map_seed=99, rng_seed=5)
        w.traffic_target = 0
        w.patrol_target = 0
        for c in traffic(w):
            del w.cars[c.id]
        ped = self._ped_on_sidewalk(w)
        car = next(c for c in w.cars.values() if c.kind == S.CIV)
        car.x, car.y, car.ang = ped.x - 10.0, ped.y, 0.0
        car.vx = 20.0
        x0, y0 = ped.x, ped.y
        step(w, 0.15)
        self.assertGreater(ped.flee_t, 0, "a car doing 72 km/h straight at you: run")
        step(w, 0.3)
        self.assertGreater(math.hypot(ped.x - x0, ped.y - y0), 1.0)

    def test_crash_scatters_the_crowd(self):
        w = S.World(map_seed=99, rng_seed=5)
        ped = self._ped_on_sidewalk(w)
        car = next(c for c in w.cars.values() if c.kind == S.CIV)
        car.x, car.y = ped.x + 8.0, ped.y
        w._crash(car, C.CRASH_EJECT_DV + 2, 1.0, 0.0)
        self.assertGreater(ped.flee_t, 0)
        self.assertLess(ped.fx, 0, "runs AWAY from the wreck")

    def test_bystanders_bolt_from_a_cop_chase(self):
        w = S.World(map_seed=99, rng_seed=5)
        ped = self._ped_on_sidewalk(w)
        car = next(c for c in w.cars.values() if c.kind == S.CIV)
        car.x, car.y = ped.x + 12.0, ped.y
        car.state, car.stolen = S.RUNNING, True
        cop = S.Car(w.new_id(), S.COP, ped.x + 60, ped.y + 60, 0.0, {s: None for s in SLOTS})
        cop.confused_t = 99
        w.cars[cop.id] = cop
        step(w, 0.3)
        self.assertEqual(ped.flee_t, 0.0, "no chase yet: they're just nosy")
        w.dispatched = True
        w.heat = 100.0
        step(w, 0.3)
        self.assertGreater(ped.flee_t, 0, "cops rolling + stolen car nearby = leave")


if __name__ == "__main__":
    unittest.main()

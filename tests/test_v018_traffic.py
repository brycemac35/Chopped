"""v0.18 traffic: getting out of jams, stuck cars leaving, and horns with some manners."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def quiet_world():
    w = S.World(map_seed=99, rng_seed=5)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    for c in [c for c in w.cars.values() if c.kind == S.TRAFFIC]:
        del w.cars[c.id]
    return w


def car_on_lane(w, node, d, along, speed=8.0, kind=S.TRAFFIC):
    """A traffic car on the lane through `node` heading d, `along` metres past the junction centre."""
    i, j = node
    car = S.Car(w.new_id(), kind, 0, 0, math.atan2(d[1], d[0]), S.kei_loadout(w.rng), color=3)
    car.x, car.y = w._lane_point(i, j, d, along)
    car.vx, car.vy = d[0] * speed, d[1] * speed
    car.tdir, car.node = d, (i, j)
    car.route = [w._lane_point(i, j, d, -8.0)]
    car.route_prev = w._lane_point(i - d[0], j - d[1], d, 8.0)
    w.cars[car.id] = car
    return car


class TestUnjam(unittest.TestCase):
    def test_four_way_junction_deadlock_resolves(self):
        w = quiet_world()
        w.traffic_target = 4
        node = (C.BLOCKS // 2, C.BLOCKS // 2 + 1)
        cars = [car_on_lane(w, node, d, -16.0, speed=6.0) for d in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        starts = [(c.x, c.y) for c in cars]
        crashes = []
        orig = w._crash
        w._crash = lambda car, dv, nx, ny: (crashes.append(car.id), orig(car, dv, nx, ny))
        step(w, 40.0)
        for c, (x0, y0) in zip(cars, starts):
            self.assertIn(c.id, w.cars, "nobody was recycled: they sorted it out")
            self.assertGreater(math.hypot(c.x - x0, c.y - y0), 30.0, "and everybody got through")
        self.assertEqual(crashes, [], "without a scratch")

    def test_full_exit_lane_holds_the_box(self):
        w = quiet_world()
        node = (C.BLOCKS // 2, C.BLOCKS // 2 + 1)
        car = car_on_lane(w, node, (1, 0), -22.0, speed=8.0)
        car.route = [w._lane_point(*node, (1, 0), -8.0), w._lane_point(*node, (1, 0), 8.0),
                     w._lane_point(node[0] + 1, node[1], (1, 0), -8.0)]
        car.node = (node[0] + 1, node[1])
        jam = car_on_lane(w, node, (1, 0), 12.0, speed=0.0, kind=S.CIV)      # a dead car just past the junction
        jam.state = S.RUNNING
        step(w, 6.0)
        cx, _ = w.map.node_pos(*node)
        self.assertLess(car.x, cx - C.TRAFFIC_BOX_HOLD_DIST + 2.0, "waits at the line rather than block the box")

    def test_lane_blocked_by_a_stopped_car_is_passed(self):
        w = quiet_world()
        w.traffic_target = 1
        node = (C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1)
        car = car_on_lane(w, node, (1, 0), -36.0, speed=10.0)
        wreck = car_on_lane(w, node, (1, 0), -22.0, speed=0.0, kind=S.CIV)
        wreck.state = S.RUNNING
        step(w, 30.0)
        self.assertIn(car.id, w.cars)
        self.assertGreater(car.x, wreck.x + 6.0, "swung out into the empty oncoming lane and went round")

    def test_a_queue_is_not_overtaken(self):
        """Cars waiting at a full junction don't pull into the oncoming lane round each other."""
        w = quiet_world()
        w.traffic_target = 2
        node = (C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1)
        lead = car_on_lane(w, node, (1, 0), -30.0, speed=0.0)
        lead.blocked_t = 3.0                       # itself waiting for something
        car = car_on_lane(w, node, (1, 0), -38.0, speed=0.0)
        self.assertFalse(w._pass_clear(car, lead, 1.0, 0.0))

    def test_oncoming_lane_must_be_clear_to_pass(self):
        w = quiet_world()
        node = (C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1)
        car = car_on_lane(w, node, (1, 0), -36.0)
        wreck = car_on_lane(w, node, (1, 0), -22.0, speed=0.0, kind=S.CIV)
        self.assertTrue(w._pass_clear(car, wreck, 1.0, 0.0))
        car_on_lane(w, node, (-1, 0), 28.0, speed=10.0)          # somebody coming the other way
        self.assertFalse(w._pass_clear(car, wreck, 1.0, 0.0))

    def test_priority_goes_to_the_lowest_id_in_the_knot(self):
        w = quiet_world()
        node = (C.BLOCKS // 2, C.BLOCKS // 2 + 1)
        a = car_on_lane(w, node, (1, 0), -12.0, speed=0.0)
        b = car_on_lane(w, node, (0, 1), -12.0, speed=0.0)
        a.idle_t = b.idle_t = C.TRAFFIC_PRIORITY_AFTER + 1
        self.assertLess(a.id, b.id)
        self.assertTrue(w._has_priority(a))
        self.assertFalse(w._has_priority(b))


class TestStuckCars(unittest.TestCase):
    def setUp(self):
        self.w = quiet_world()
        self.p = self.w.add_player("WATCHER")
        node = (C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1)
        self.car = car_on_lane(self.w, node, (1, 0), -30.0, speed=0.0)
        self.car.handbrake = True
        self.far()

    def far(self):
        """The player is in the shop, a long way from the car."""
        gx, gy, gw, gh = self.w.map.garage_rect
        self.p.x, self.p.y = gx + gw / 2, gy + 6
        self.car.x, self.car.y = self.p.x + 200.0, self.p.y

    def test_unwatched_stuck_car_is_recycled_after_the_timer(self):
        self.car.idle_t = C.TRAFFIC_STUCK_DESPAWN - 1.0
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars, "not yet")
        self.car.idle_t = C.TRAFFIC_STUCK_DESPAWN + 0.1
        self.w._clear_lanes(DT)
        self.assertNotIn(self.car.id, self.w.cars)

    def test_watched_car_waits_for_the_hard_limit(self):
        self.car.x, self.car.y = self.p.x + 20.0, self.p.y            # right in front of somebody
        self.car.idle_t = C.TRAFFIC_STUCK_DESPAWN + 5.0
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars, "not while somebody's looking")
        self.car.idle_t = C.TRAFFIC_STUCK_HARD + 0.1
        self.w._clear_lanes(DT)
        self.assertNotIn(self.car.id, self.w.cars, "but eventually, regardless")

    def test_looking_the_other_way_is_not_watching(self):
        self.car.x, self.car.y = self.p.x + 100.0, self.p.y
        self.car.idle_t = C.TRAFFIC_STUCK_DESPAWN + 1.0
        self.p.ang = 0.0
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars, "a player looking straight at it (100 m off) sees it go")
        self.p.ang = math.pi
        self.w._clear_lanes(DT)
        self.assertNotIn(self.car.id, self.w.cars)

    def test_never_with_a_player_at_the_door(self):
        self.car.idle_t = C.TRAFFIC_STUCK_HARD + 10.0
        self.p.state = S.FOOT
        self.p.x, self.p.y = self.car.to_world(0.0, self.car.hw + 0.8)
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars)
        self.assertEqual(self.car.idle_t, 0.0, "and the clock starts over")

    def test_never_mid_hold(self):
        self.car.idle_t = C.TRAFFIC_STUCK_HARD + 10.0
        self.p.hold_key = ("carjack", self.car.id)
        self.p.hold = 0.5
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars)

    def test_never_a_prisoner_car_or_a_stolen_or_parked_one(self):
        cop = car_on_lane(self.w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), -20.0, speed=0.0, kind=S.COP)
        cop.prisoner = self.p.id
        cop.idle_t = C.TRAFFIC_STUCK_HARD + 10.0
        stolen = car_on_lane(self.w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), -30.0, speed=0.0, kind=S.CIV)
        stolen.stolen, stolen.bailed, stolen.idle_t = True, True, 1e6
        parked = car_on_lane(self.w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), 0.0, speed=0.0, kind=S.CIV)
        parked.idle_t = 1e6
        delivered = car_on_lane(self.w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), 10.0, speed=0.0, kind=S.CIV)
        delivered.state, delivered.bailed, delivered.idle_t = S.DELIVERED, False, 1e6
        for c in (cop, stolen, parked, delivered):
            c.x, c.y = self.car.x + 3.0 * (c.id % 7), self.car.y + 40.0
        self.w._clear_lanes(DT)
        for c in (cop, stolen, parked, delivered):
            self.assertIn(c.id, self.w.cars, "kind %s" % c.kind)

    def test_money_truck_mid_robbery_stays(self):
        self.car.idle_t = C.TRAFFIC_STUCK_HARD + 10.0
        self.car.cash_hits = 2
        self.w._clear_lanes(DT)
        self.assertIn(self.car.id, self.w.cars)

    def test_a_bailed_car_is_towed_quietly_but_not_from_under_somebody(self):
        w = self.w
        car = self.car
        car.kind = S.CIV
        car.state = S.RUNNING
        car.bailed = True
        car.idle_pos = (car.x, car.y)
        n_toasts = len(w.toasts) if hasattr(w, "toasts") else 0
        step(w, 5.0)
        self.assertIn(car.id, w.cars)
        car.idle_t = C.WRECK_CLEAR_TIME + 1.0
        self.p.x, self.p.y = car.x - 10.0, car.y                       # somebody's standing right there
        w._clear_lanes(DT)
        self.assertIn(car.id, w.cars, "they might want it")
        self.p.x, self.p.y = car.x - 100.0, car.y
        self.p.ang = math.pi
        w._clear_lanes(DT)
        self.assertNotIn(car.id, w.cars)
        if hasattr(w, "toasts"):
            self.assertEqual(len(w.toasts), n_toasts, "silent")


class TestHonking(unittest.TestCase):
    def test_a_blocked_driver_beeps_once_then_holds_their_tongue(self):
        w = quiet_world()
        w.traffic_target = 1
        node = (C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1)
        car = car_on_lane(w, node, (1, 0), -40.0, speed=10.0)
        p = w.add_player("JAYWALKER")
        p.x, p.y = car.x + 18.0, car.y
        x0 = p.x
        beeps, on_ticks, was = 0, 0, False
        for _ in range(int(14.0 * C.SIM_HZ)):
            w.step(DT)
            p.x = x0
            if car.horn:
                on_ticks += 1
                if not was:
                    beeps += 1
            was = car.horn
        self.assertEqual(beeps, 1, "one beep in 14 s (the shortest cooldown is %.0f)" % C.TRAFFIC_HONK_COOLDOWN[0])
        self.assertLessEqual(on_ticks / C.SIM_HZ, C.TRAFFIC_HONK_LEN + 0.1, "and it was brief")

    def test_honk_cooldown_is_random_and_long(self):
        w = quiet_world()
        w.add_player("EARS")
        gaps = []
        for _ in range(12):
            car = car_on_lane(w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), -20.0, speed=0.0)
            car.x, car.y = w.players[1].x + 5.0, w.players[1].y + 5.0
            w._honk(car, DT, True)
            self.assertTrue(car.horn)
            gaps.append(car.honk_cd)
            del w.cars[car.id]
        self.assertTrue(all(C.TRAFFIC_HONK_COOLDOWN[0] - 0.1 <= g <= C.TRAFFIC_HONK_COOLDOWN[1] for g in gaps))
        self.assertGreater(len(set(round(g, 3) for g in gaps)), 6, "spread, so a jam doesn't beep in unison")

    def test_cap_on_simultaneous_honkers_near_a_player(self):
        w = quiet_world()
        p = w.add_player("EARS")
        cars = []
        for k in range(6):
            car = car_on_lane(w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), -20.0, speed=0.0)
            car.x, car.y = p.x + 5.0 + k, p.y + 5.0
            cars.append(car)
        for car in cars:
            w._honk(car, DT, True)
        self.assertEqual(sum(1 for c in cars if c.honk_t > 0), C.TRAFFIC_HONK_MAX_NEAR)
        far = car_on_lane(w, (C.BLOCKS // 2, C.BLOCKS // 2 + 1), (1, 0), -20.0, speed=0.0)
        far.x, far.y = p.x + 300.0, p.y
        w._honk(far, DT, True)
        self.assertTrue(far.honk_t > 0, "nobody can hear it, so nobody's counting")

    def test_players_horn_still_confuses_cops(self):
        w = quiet_world()
        p = w.add_player("HONKER")
        car = S.Car(w.new_id(), S.CIV, p.x, p.y, 0.0, S.kei_loadout(w.rng))
        car.driver = p.id
        car.horn = True
        w.cars[car.id] = car
        cop = S.Car(w.new_id(), S.COP, p.x + 10, p.y, 0.0, S.kei_loadout(w.rng))
        w.cars[cop.id] = cop
        w._horns(DT)
        self.assertGreater(cop.confused_t, 0)


if __name__ == "__main__":
    unittest.main()

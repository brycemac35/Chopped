"""v0.18 police: a cop car that can't get a prisoner to the station sends him to jail anyway, a
prisoner's car vanishing never leaves him in limbo, and the police budget is small (2 cop cars
including patrols, 2 officers on foot, 1 dog)."""

import math
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S

DT = 1 / 60.0


def quiet_world(seed=4242, patrols=0):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = patrols
    return w


def step(w, secs):
    for _ in range(int(round(secs / DT))):
        w.step(DT)


def road_point(w):
    bx, by, _ = w.map.bays[0]
    gx, gy, gw, gh = w.map.garage_rect
    return bx, gy + gh + 10.0


def toasts(w):
    return [e[3][1] for e in w.events if e[2] == 0]


def prisoner_ride(w):
    """A cop car with BRYCE cuffed in the back, a long way from the station, exactly as
    police._escort leaves them."""
    p = w.add_player("BRYCE")
    p.x, p.y = road_point(w)
    cop = S.Car(w.new_id(), S.COP, p.x + 40, p.y, math.pi, S.cop_loadout(w.rng))
    w.cars[cop.id] = cop
    p.state = S.CUFFED
    w._enter_car(p, cop, S.PASSENGER)
    cop.prisoner = p.id
    cop.ride_t = 0.0
    cop.patrol = False
    w.riders[p.id] = cop.id
    return p, cop


class TestTransportTimeout(unittest.TestCase):
    def test_a_car_that_cannot_move_jails_the_prisoner_and_is_freed(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        w._traffic_ai = lambda car, dt: None          # wedged: the lanes' AI does nothing at all
        step(w, C.TRANSPORT_STUCK_TIME - 2.0)
        self.assertEqual(p.state, S.PASSENGER, "not yet")
        self.assertEqual(cop.prisoner, p.id)
        step(w, 3.0)
        self.assertTrue(p.jailed)
        self.assertTrue(w.map.in_precinct(p.x, p.y))
        self.assertIsNone(cop.prisoner)
        self.assertIsNone(cop.passenger)
        self.assertIsNone(p.car_id)
        self.assertEqual(w.riders, {})
        self.assertTrue(any("RADIOED FOR THE VAN" in t for t in toasts(w)))
        self.assertEqual(w.rides, {}, "and the car is off the clock (heat's gone, so dispatch recycles it)")

    def test_shuffling_on_the_spot_is_not_progress(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        x0 = cop.x

        def shuffle(car, dt):                          # back and forth over a metre, forever
            car.x = x0 + 0.5 * math.sin(w.time * 3.0)
            car.vx = car.vy = 0.0
        w._traffic_ai = shuffle
        step(w, C.TRANSPORT_STUCK_TIME + 2.0)
        self.assertTrue(p.jailed)

    def test_a_car_that_is_really_driving_is_left_alone(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)

        def crawl(car, dt):                            # 3 m/s toward the station: slow, but real
            ex, ey = w.map.precinct_exit
            a = math.atan2(ey - car.y, ex - car.x)
            car.x += math.cos(a) * 3.0 * dt
            car.y += math.sin(a) * 3.0 * dt
            car.vx = car.vy = 0.0
        w._traffic_ai = crawl
        step(w, C.TRANSPORT_STUCK_TIME * 2.5)
        self.assertEqual(p.state, S.PASSENGER)
        self.assertFalse(p.jailed)

    def test_the_whole_ride_is_capped(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)

        def crawl(car, dt):
            ex, ey = w.map.precinct_exit
            a = math.atan2(ey - car.y, ex - car.x)
            car.x += math.cos(a) * 3.0 * dt
            car.y += math.sin(a) * 3.0 * dt
            car.vx = car.vy = 0.0
        w._traffic_ai = crawl
        cop.ride_t = C.TRANSPORT_MAX_TIME - 0.5        # a very long lap of the city
        step(w, 1.0)
        self.assertTrue(p.jailed)
        self.assertIsNone(cop.prisoner)

    def test_a_beat_car_goes_back_on_patrol_after_the_van(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        cop.beat = True
        w._traffic_ai = lambda car, dt: None
        step(w, C.TRANSPORT_STUCK_TIME + 1.0)
        self.assertTrue(p.jailed)
        self.assertTrue(cop.patrol)

    def test_the_other_ways_out_still_work_before_the_timeout(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        w._traffic_ai = lambda car, dt: None
        step(w, 3.0)
        w.eject(cop, 15.0)                             # a hard crash throws everyone out
        step(w, 0.2)
        self.assertFalse(p.jailed)
        self.assertIsNone(cop.prisoner)
        self.assertEqual(w.riders, {})
        step(w, C.TRANSPORT_STUCK_TIME + 2.0)
        self.assertFalse(p.jailed, "free means free: the transport clock died with the ride")


class TestPrisonerCarVanishes(unittest.TestCase):
    def test_deleted_car_jails_the_prisoner(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        step(w, 1.0)
        del w.cars[cop.id]                             # a despawner, a tow truck, anything
        step(w, 0.3)
        self.assertTrue(p.jailed)
        self.assertNotEqual(p.state, S.PASSENGER)
        self.assertEqual(w.riders, {})

    def test_an_exploding_car_jails_the_prisoner_too(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        w._explode(cop)
        step(w, 0.3)
        self.assertTrue(p.jailed)

    def test_a_carjacked_car_forgets_its_prisoner_instead(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        cop.prisoner = None                            # what _steal_cop_car does
        cop.kind = S.CIV
        step(w, 0.3)
        self.assertEqual(w.riders, {})
        self.assertFalse(p.jailed)

    def test_the_prisoner_leaving_the_game_is_cleaned_up(self):
        w = quiet_world()
        p, cop = prisoner_ride(w)
        w.remove_player(p.id)
        step(w, 0.3)
        self.assertEqual(w.riders, {})
        self.assertIsNone(cop.prisoner)


class TestShoulderCarry(unittest.TestCase):
    def carried(self, w):
        p = w.add_player("BRYCE")
        p.x, p.y = road_point(w)
        cop = S.Car(w.new_id(), S.COP, p.x + 10, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        n = S.NPC(w.new_id(), S.OFFICER, p.x + 1.0, p.y)
        n.car_id = cop.id
        w.npcs[n.id] = n
        cop.officer = n.id
        p.state = S.CUFFED
        self.assertTrue(w._start_escort(p, n))
        return p, cop, n

    def test_an_officer_who_cannot_reach_his_car_hands_over_to_the_van(self):
        w = quiet_world()
        p, cop, n = self.carried(w)
        # he's pinned on a wall: he never gets anywhere
        orig = w._officer

        def pinned(npc, dt):
            r = orig(npc, dt)
            npc.x, npc.y = p.x, p.y
            return r
        w._officer = pinned
        step(w, C.ESCORT_MAX_TIME + 3.0)
        self.assertNotEqual(p.state, S.CARRIED)
        self.assertIsNone(p.escort)
        self.assertTrue(p.jailed or p.state == S.CUFFED, "he's on the kerb waiting for the van, or already in it")
        step(w, C.CUFFED_TIME + 2.0)
        self.assertTrue(p.jailed)

    def test_his_car_stolen_mid_walk_is_the_van(self):
        w = quiet_world()
        p, cop, n = self.carried(w)
        cop.kind = S.CIV
        step(w, C.CUFFED_TIME + 1.0)
        self.assertTrue(p.jailed)

    def test_his_car_gone_mid_walk_is_the_van(self):
        w = quiet_world()
        p, cop, n = self.carried(w)
        del w.cars[cop.id]
        step(w, C.CUFFED_TIME + 1.0)
        self.assertTrue(p.jailed)


class TestPoliceCaps(unittest.TestCase):
    def soak(self, seed, secs=120.0, patrols=C.PATROL_COPS):
        w = quiet_world(seed, patrols)
        w.npcs.clear()
        p = w.add_player("BRYCE")
        px, py = p.x, p.y = road_point(w)
        peak = {"cars": 0, "officers": 0, "dogs": 0}
        for i in range(int(secs / DT)):
            w.heat = 100.0
            if p.jailed or p.state not in (S.FOOT, S.TUMBLE):
                p.jailed, p.state, p.car_id = False, S.FOOT, None
                p.x, p.y = px, py
                w.riders.clear()
                for c in w.cars.values():
                    c.prisoner = None
            w.step(DT)
            if i % 15 == 0:
                cars = sum(1 for c in w.cars.values() if c.kind == S.COP)
                off = sum(1 for n in w.npcs.values() if n.kind == S.OFFICER)
                dogs = sum(1 for n in w.npcs.values() if n.kind == S.DOG)
                peak["cars"], peak["officers"], peak["dogs"] = (
                    max(peak["cars"], cars), max(peak["officers"], off), max(peak["dogs"], dogs))
                self.assertLessEqual(cars, C.COP_CARS_MAX, "seed %d t=%.1f" % (seed, w.time))
                self.assertLessEqual(off, C.OFFICERS_MAX, "seed %d t=%.1f" % (seed, w.time))
                self.assertLessEqual(dogs, C.K9_MAX, "seed %d t=%.1f" % (seed, w.time))
        return peak

    def test_the_numbers_are_what_bryce_asked_for(self):
        self.assertEqual(C.COP_CARS_MAX, 2)
        self.assertEqual(C.OFFICERS_MAX, 2)
        self.assertEqual(C.K9_MAX, 1)
        self.assertLessEqual(C.PATROL_COPS, C.COP_CARS_MAX)
        self.assertLessEqual(max(n for _, n in C.COP_TIERS), C.COP_CARS_MAX)

    def test_caps_hold_at_full_heat_on_a_few_seeds(self):
        with mock.patch.object(C, "K9_CHANCE", 1.0):        # every deployment wants a dog
            peaks = [self.soak(seed) for seed in (1, 7, 4242)]
        self.assertTrue(any(pk["cars"] == C.COP_CARS_MAX for pk in peaks), "the cap is reached, not just respected")

    def test_a_patrol_that_engages_is_one_of_the_two(self):
        w = quiet_world(patrols=1)
        p = w.add_player("BRYCE")
        p.x, p.y = road_point(w)
        step(w, 8.0)                                        # the patrol turns up...
        beat = [c for c in w.cars.values() if c.kind == S.COP and c.beat]
        self.assertEqual(len(beat), 1)
        self.assertTrue(beat[0].patrol)
        for _ in range(int(40 / DT)):                       # ...and at 100 heat there are two cars, not three
            w.heat = 100.0
            w.step(DT)
            p.state, p.jailed = S.FOOT, False
        cops = [c for c in w.cars.values() if c.kind == S.COP]
        self.assertLessEqual(len(cops), C.COP_CARS_MAX)
        self.assertEqual(len(cops), C.COP_CARS_MAX)
        self.assertFalse(any(c.patrol for c in cops), "both are hunting: the patrol was waved in")


if __name__ == "__main__":
    unittest.main()

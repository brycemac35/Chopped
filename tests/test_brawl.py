"""v0.7 slapstick: throwing, carrying, bowling, haymakers, dancing, jumping,
pedestrians who fight back, busier police, and the ridiculous stuff."""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped.parts import Part, model_loadout

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
    for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
        del w.cars[cid]
    for pid in [k for k, pk in w.pickups.items() if pk.fixed]:
        del w.pickups[pid]                 # (the gnomes get their own test)
    return w


def street(w):
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2 + 30, gy + gh + 10.0


def ped(w, x, y, brave=False, armed=False):
    n = S.NPC(w.new_id(), S.PED, x, y)
    n.dirx = n.diry = 0
    n.turn_t = 1e9
    n.brave, n.armed = brave, armed
    n.grit = 3 if brave else 0
    w.npcs[n.id] = n
    return n


def inp(p, **kw):
    i = p.input
    d = dict(buttons=i.buttons, use_count=i.use_count, drop_count=i.drop_count, exit_count=i.exit_count, yaw=i.yaw,
             fire_count=i.fire_count, weapon=i.weapon)
    d.update(kw)
    p.input = S.InputState(**d)


def face(p, x, y):
    inp(p, yaw=math.atan2(y - p.y, x - p.x))
    p.ang = p.input.yaw


def click(p):
    inp(p, fire_count=p.input.fire_count + 1)


def tap_g(p):
    inp(p, drop_count=p.input.drop_count + 1)


def tap_f(p):
    inp(p, exit_count=p.input.exit_count + 1)


class TestThrowingAndCarrying(unittest.TestCase):
    def test_pick_up_a_downed_ped_and_bowl_a_strike(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        victim = ped(w, p.x + 1.2, p.y)
        victim.tumble_t = 5.0
        pins = [ped(w, p.x + 5.5 + k * 0.5, p.y + (k - 1) * 0.35) for k in range(3)]
        face(p, victim.x, victim.y)
        tap_g(p)
        w.step(DT)
        self.assertEqual(p.carrying, ("npc", victim.id))
        self.assertEqual(p.hands_used(), 2, "a whole person takes both hands")
        step(w, 0.2)
        self.assertGreater(victim.z, 1.0, "over the shoulder")
        face(p, pins[1].x, pins[1].y)
        click(p)
        w.step(DT)
        self.assertIsNone(p.carrying)
        self.assertEqual(victim.thrown_by, p.id)
        step(w, 1.5)
        down = sum(1 for n in pins if n.tumble_t > 0)
        self.assertGreaterEqual(down, 2, "human bowling")
        if down >= C.STRIKE_COUNT:
            self.assertEqual(p.banner, S.BN_STRIKE)

    def test_carried_crewmate_wriggles_free(self):
        w = world()
        a, b = w.add_player("A"), w.add_player("B")
        a.x, a.y = street(w)
        b.x, b.y = a.x + 1.2, a.y
        face(a, b.x, b.y)
        tap_g(a)
        w.step(DT)
        self.assertEqual(b.state, S.CARRIED)
        for _ in range(C.WRIGGLE_PRESSES):
            inp(b, buttons=S.B_JUMP)
            w.step(DT)
            inp(b, buttons=0)
            w.step(DT)
        self.assertEqual(b.state, S.FOOT)
        self.assertIsNone(a.carrying)

    def test_throw_your_mate(self):
        w = world()
        a, b = w.add_player("A"), w.add_player("B")
        a.x, a.y = street(w)
        b.x, b.y = a.x + 1.2, a.y
        face(a, b.x, b.y)
        tap_g(a)
        w.step(DT)
        click(a)
        w.step(DT)
        self.assertEqual(b.state, S.TUMBLE)
        self.assertEqual(b.banner, S.BN_YEETED)
        self.assertGreater(b.z, 0.5)
        step(w, 4.0)
        self.assertEqual(b.state, S.FOOT, "lands eventually")
        self.assertGreater(b.x, a.x + 5, "and a fair way off")


class TestHaymakerDanceJump(unittest.TestCase):
    def test_haymaker_is_a_home_run(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = ped(w, p.x + 1.3, p.y)
        face(p, n.x, n.y)
        inp(p, buttons=S.B_FIRE)
        step(w, C.HAYMAKER_CHARGE + 0.1)
        self.assertGreater(p.charge_t, C.HAYMAKER_CHARGE)
        inp(p, buttons=0)
        w.step(DT)
        self.assertEqual(p.banner, S.BN_HOMERUN)
        step(w, 0.2)
        self.assertGreater(n.z, 0.5, "they're airborne")
        step(w, 2.0)
        self.assertGreater(math.hypot(n.x - p.x, n.y - p.y), 8.0)

    def test_the_dance_makes_them_laugh_and_laughers_dont_witness(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        crowd = [ped(w, p.x + 4 + k, p.y + 2) for k in range(4)]
        inp(p, buttons=S.B_TAUNT)
        step(w, 4.0)
        self.assertTrue(p.dancing)
        laughing = [n for n in crowd if n.laugh_t > 0]
        self.assertTrue(laughing, "somebody finds it funny")
        w.heat = 50
        w.targets = w._collect_targets()
        for n in crowd:
            if n.laugh_t <= 0:
                del w.npcs[n.id]
        self.assertEqual(w._witness_scan()[0], S.W_NONE, "too busy laughing to call it in")
        # ...and a laughing ped can be robbed
        n = laughing[0]
        p.x, p.y = n.x - 1.2, n.y
        face(p, n.x, n.y)
        inp(p, buttons=0)
        key, label, _, _ = w._find_interaction(p)
        self.assertIn("ROB", label)

    def test_jump_and_clear_a_roadblock(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        inp(p, buttons=S.B_JUMP)
        w.step(DT)
        self.assertGreater(p.vz, 0)
        step(w, 0.15)
        self.assertGreater(p.z, 0.4)
        inp(p, buttons=0)
        step(w, 1.0)
        self.assertEqual(p.z, 0.0, "and back down")
        # a roadblock is solid on foot... unless you're over it
        p.gear[1] = 1
        p.ang = 0.0
        w._place_trap(p, S.TRAP_BLOCK)
        t = next(iter(w.traps.values()))
        rx, ry, rw, rh = t.rect()
        p.x, p.y = rx - 1.0, ry + rh / 2
        face(p, p.x + 10, p.y)
        inp(p, buttons=S.B_UP)
        step(w, 1.0)
        self.assertLess(p.x, rx, "walking into it: blocked")
        p.x = rx - 1.0
        inp(p, buttons=S.B_UP | S.B_JUMP)
        step(w, 0.8)
        self.assertGreater(p.x, rx + rw, "hurdled it")


class TestFightBack(unittest.TestCase):
    def test_a_brave_ped_gets_up_swinging(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = ped(w, p.x + 1.3, p.y, brave=True)
        face(p, n.x, n.y)
        click(p)
        w.step(DT)
        self.assertGreater(n.hostile_t, 0, "provoked")
        self.assertEqual(n.foe, p.id)
        w.rng = random.Random(1)
        knocked = False
        for _ in range(int(12 / DT)):
            w.step(DT)
            if p.state == S.TUMBLE:
                knocked = True
                break
        self.assertTrue(knocked, "they came back and floored you")
        self.assertEqual(p.banner, S.BN_HUMBLED)

    def test_they_take_their_money_back(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = ped(w, p.x + 1.2, p.y, brave=True)
        n.wallet = 70
        n.tumble_t = 1.5
        face(p, n.x, n.y)
        inp(p, buttons=S.B_USE)
        step(w, C.ROB_TIME + 0.1)
        inp(p, buttons=0)
        self.assertEqual(p.robbed_from.get(n.id), 70)
        cash_after_rob = w.cash
        w.rng = random.Random(4)
        for _ in range(int(15 / DT)):
            w.step(DT)
            if n.id not in p.robbed_from:
                break
        self.assertNotIn(n.id, p.robbed_from)
        self.assertEqual(w.cash, cash_after_rob - 70, "revenge refund")

    def test_armed_peds_shoot(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = ped(w, p.x + 10, p.y, brave=True, armed=True)
        n.hostile_t, n.foe = 20, p.id
        C_acc = C.PED_GUN_ACCURACY
        try:
            C.PED_GUN_ACCURACY = 1.0
            step(w, 1.5)
        finally:
            C.PED_GUN_ACCURACY = C_acc
        self.assertEqual(p.state, S.TUMBLE, "shot by a pedestrian")
        self.assertTrue(any(e[2] == 2 for e in w.events), "with a tracer")


class TestPolice(unittest.TestCase):
    def test_patrol_cars_cruise_and_engage(self):
        w = world()
        w.patrol_target = 2
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        step(w, 8.0)
        patrols = [c for c in w.cars.values() if c.kind == S.COP and c.beat]
        self.assertEqual(len(patrols), 2)
        self.assertTrue(all(c.patrol for c in patrols), "just cruising while you behave")
        cop = patrols[0]
        cop.x, cop.y, cop.ang = p.x - 25, p.y, 0.0
        cop.vx = cop.vy = 0.0
        w.heat = 40
        w.unseen_t = 0
        w.targets = w._collect_targets()
        w._cop_ai(cop, DT)
        self.assertFalse(cop.patrol, "spotted you: lights on")
        # heat gone: back to patrol, not deleted
        w.heat = 0.0
        p.x, p.y = w.map.player_spawns[0]
        step(w, C.COP_DESPAWN_AT_ZERO + 0.5)
        self.assertIn(cop.id, w.cars)
        self.assertTrue(cop.patrol)

    def test_donuts_stop_a_cop(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.gear[3] = 1
        p.ang = 0.0
        w._place_trap(p, S.TRAP_DONUT)
        box = next(iter(w.traps.values()))
        cop = S.Car(w.new_id(), S.COP, box.x + 20, box.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        w.heat = 60
        ate = False
        for _ in range(int(10 / DT)):
            w.heat = 60
            w.step(DT)
            if cop.donut_t > 0:
                ate = True
                break
        self.assertTrue(ate, "the cop pulled over for donuts")
        cops_that_arrest = [c for c in w.cars.values() if c.kind == S.COP and c.donut_t <= 0]
        self.assertNotIn(cop, cops_that_arrest)

    def test_high_heat_cops_shoot_crooks_on_foot(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        cop = S.Car(w.new_id(), S.COP, p.x - 15, p.y, 0.0, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        acc = C.COP_GUN_ACCURACY
        try:
            C.COP_GUN_ACCURACY = 1.0
            for _ in range(int(2.0 / DT)):
                w.heat = 90
                w.step(DT)
                if p.state == S.TUMBLE:
                    break
        finally:
            C.COP_GUN_ACCURACY = acc
        self.assertIn(p.state, (S.TUMBLE, S.CUFFED))


class TestRidiculous(unittest.TestCase):
    def test_banana_peel_spins_a_car(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.gear[2] = 1
        p.ang = 0.0
        w._place_trap(p, S.TRAP_BANANA)
        t = next(iter(w.traps.values()))
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = t.x - 8, t.y, 0.0
        car.vx = 14.0
        w._enter_car(w.add_player("DRIVER"), car, S.DRIVER)
        step(w, 1.0)
        self.assertEqual(w.traps, {}, "one peel, one victim")
        self.assertGreater(abs(car.w) + car.spin_t, 0.5)

    def test_banana_trips_a_walker(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.gear[2] = 1
        p.ang = 0.0
        w._place_trap(p, S.TRAP_BANANA)
        face(p, p.x + 5, p.y)
        inp(p, buttons=S.B_UP)
        step(w, 1.0)
        self.assertEqual(p.state, S.TUMBLE)

    def test_ejector_seat(self):
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        car.x, car.y = street(w)
        car.ang = 0.0
        car.ejector = True
        w._enter_car(p, car, S.DRIVER)
        car.vx = 20.0
        tap_f(p)
        w.step(DT)
        self.assertEqual(p.state, S.TUMBLE)
        self.assertTrue(p.chute)
        self.assertEqual(p.banner, S.BN_EJECT)
        step(w, 0.5)
        self.assertGreater(p.z, 3.0, "up through the roof")
        step(w, 8.0)
        self.assertEqual(p.z, 0.0)
        self.assertFalse(p.chute, "and gently down")

    def test_gnomes_exist_and_stealing_one_is_a_crime(self):
        w = S.World(map_seed=4242, rng_seed=1)
        gnomes = [pk for pk in w.pickups.values() if pk.fixed]
        self.assertEqual(len(gnomes), C.GNOME_COUNT)
        p = w.add_player("BRYCE")
        g = gnomes[0]
        p.x, p.y = g.x - 1.0, g.y
        face(p, g.x, g.y)
        heat0 = w.heat
        w._pickup(p, g)
        self.assertEqual(p.hands[0].type_id, "gnome")
        self.assertGreaterEqual(w.heat, heat0 + C.GNOME_HEAT)

    def test_ice_cream_van_draws_a_queue(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        van = S.Car(w.new_id(), S.CIV, x, y, 0.0, model_loadout(random.Random(2), V.ICECREAM), model=V.ICECREAM)
        van.state = S.RUNNING
        w.cars[van.id] = van
        w._enter_car(p, van, S.DRIVER)
        n = ped(w, x + 15, y + 6)
        n.turn_t = 0.3
        step(w, 1.0)
        self.assertIsNotNone(n.lure, "they heard the jingle")
        step(w, 6.0)
        self.assertLess(S.box_distance(van, n.x, n.y), 4.5, "queueing")

    def test_nos_goes_faster(self):
        w = world()
        car = w.cars[w.personal_id]
        car.x, car.y = street(w)
        car.ang = 0.0
        p = w.add_player("BRYCE")
        w._enter_car(p, car, S.DRIVER)
        car.nos, car.nos_fuel = True, C.NOS_TANK
        inp(p, buttons=S.B_UP | S.B_SPRINT)
        step(w, 1.0)
        boosted = car.speed()
        self.assertLess(car.nos_fuel, C.NOS_TANK)
        w2 = world()
        car2 = w2.cars[w2.personal_id]
        car2.x, car2.y = street(w2)
        car2.ang = 0.0
        q = w2.add_player("BRYCE")
        w2._enter_car(q, car2, S.DRIVER)
        inp(q, buttons=S.B_UP)
        step(w2, 1.0)
        self.assertGreater(boosted, car2.speed() + 3.0)


if __name__ == "__main__":
    unittest.main()

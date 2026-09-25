"""v0.6: fists, guns, robbing people, the black market, traps and carjacking."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped.parts import Part

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def face(p, x, y):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count,
                           math.atan2(y - p.y, x - p.x), i.fire_count, i.weapon)
    p.ang = p.input.yaw


def press(p, buttons):
    i = p.input
    p.input = S.InputState(buttons, i.use_count, i.drop_count, i.exit_count, i.yaw, i.fire_count, i.weapon)


def wield(p, slot):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, i.yaw, i.fire_count, slot)


def click(p):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, i.yaw, i.fire_count + 1, i.weapon)


def world(traffic=False):
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.patrol_target = 0
    if not traffic:
        w.traffic_target = 0
        for cid in [c.id for c in w.cars.values() if c.kind == S.TRAFFIC]:
            del w.cars[cid]
    return w


def street(w):
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2 + 30, gy + gh + 10.0            # middle of the road east of the shop


def ped(w, x, y):
    n = S.NPC(w.new_id(), S.PED, x, y)
    n.dirx = n.diry = 0
    n.turn_t = 1e9
    n.wallet = 50
    w.npcs[n.id] = n
    return n


def armed(p, pistol=True, shotgun=False):
    if pistol:
        p.arms |= 1 << S.ARM_PISTOL
        p.ammo[S.ARM_PISTOL] = 24
    if shotgun:
        p.arms |= 1 << S.ARM_SHOTGUN
        p.ammo[S.ARM_SHOTGUN] = 10


class TestFistsAndRobbing(unittest.TestCase):
    def test_punch_knocks_down_then_rob_them(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        n = ped(w, x + 1.3, y)
        face(p, n.x, n.y)
        click(p)
        w.step(DT)
        self.assertGreater(n.tumble_t, 0, "one punch, one pedestrian on the floor")
        self.assertGreaterEqual(w.heat, C.PUNCH_HEAT - 0.1, "they screamed")
        cash0 = w.cash
        step(w, 1.0)                              # they skid a couple of metres; walk over
        p.x, p.y = n.x - 1.1, n.y
        face(p, n.x, n.y)
        w.step(DT)
        self.assertIn("ROB", p.prompt)
        press(p, S.B_USE)
        step(w, C.ROB_TIME + 0.1)
        self.assertEqual(w.cash, cash0 + 50)
        self.assertEqual(n.wallet, 0)
        press(p, 0)
        n.tumble_t = 2.0
        step(w, 0.05)
        face(p, n.x, n.y)
        w.step(DT)
        self.assertIn("BROKE", p.prompt, "you can't rob the same wallet twice")

    def test_punching_your_mate_just_knocks_them_over(self):
        w = world()
        a, b = w.add_player("A"), w.add_player("B")
        a.x, a.y = street(w)
        b.x, b.y = a.x + 1.2, a.y
        face(a, b.x, b.y)
        click(a)
        w.step(DT)
        self.assertEqual(b.state, S.TUMBLE)

    def test_hands_full_click_throws_it(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = ped(w, p.x + 5.0, p.y)
        door = Part("door_stock")
        p.hands = [door]
        face(p, n.x, n.y)
        click(p)
        w.step(DT)
        self.assertEqual(p.hands, [], "click with full hands: it leaves them")
        step(w, 0.5)
        self.assertGreater(n.tumble_t, 0, "a door to the chest")
        self.assertTrue(any(pk.part is door for pk in w.pickups.values()), "and it's on the floor now")

class TestGuns(unittest.TestCase):
    def test_buy_a_pistol_at_the_black_market(self):
        w = world()
        p = w.add_player("BRYCE")
        w.cash = 1000
        x, y, item = next(m for m in w.map.market if m[2] == "pistol")
        p.x, p.y = x + 1.6, y
        face(p, x, y)
        w.step(DT)
        self.assertIn("BUY PISTOL", p.prompt)
        press(p, S.B_USE)
        step(w, C.BUY_TIME + 0.1)
        self.assertTrue(p.owns(S.ARM_PISTOL))
        self.assertEqual(p.ammo[S.ARM_PISTOL], C.PISTOL_AMMO)
        self.assertEqual(w.cash, 1000 - C.PRICE_PISTOL)
        press(p, 0)
        w.step(DT)
        self.assertIn("YOU'VE GOT A PISTOL", p.prompt)

    def test_ammo_needs_a_gun(self):
        w = world()
        p = w.add_player("BRYCE")
        w.cash = 1000
        x, y, _ = next(m for m in w.map.market if m[2] == "ammo")
        p.x, p.y = x + 1.6, y
        face(p, x, y)
        w.step(DT)
        self.assertIn("BUY A GUN FIRST", p.prompt)

    def test_shooting_someone_puts_them_down_and_costs_heat_and_ammo(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p)
        p.x, p.y = street(w)
        n = ped(w, p.x + 20, p.y)
        face(p, n.x, n.y)
        wield(p, S.ARM_PISTOL)
        click(p)
        w.step(DT)
        self.assertGreater(n.tumble_t, C.PUNCH_KNOCKDOWN)
        self.assertEqual(p.ammo[S.ARM_PISTOL], 23)
        self.assertGreaterEqual(w.heat, C.GUNSHOT_HEAT - 0.1)
        self.assertTrue(any(e[2] == 2 for e in w.events), "a tracer event goes out to clients")
        p.ammo[S.ARM_PISTOL] = 0
        step(w, C.PISTOL_COOLDOWN)
        click(p)
        w.step(DT)
        self.assertEqual(p.ammo[S.ARM_PISTOL], 0)

    def test_pointing_a_gun_makes_them_surrender_and_you_can_rob_them(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p)
        p.x, p.y = street(w)
        n = ped(w, p.x + 4, p.y)
        face(p, n.x, n.y)
        wield(p, S.ARM_PISTOL)
        w.step(DT)
        self.assertGreater(n.surrender_t, 0, "hands up")
        p.x = n.x - 1.2
        face(p, n.x, n.y)
        cash0 = w.cash
        press(p, S.B_USE)
        step(w, C.ROB_TIME + 0.1)
        self.assertEqual(w.cash, cash0 + 50)

    def test_shoot_out_a_tyre(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p)
        car = next(c for c in w.cars.values() if c.kind == S.CIV)
        car.ang = 0.0
        wx, wy = car.to_world(1.4, 1.3)          # front-right wheel
        p.x, p.y = wx, wy + 8
        face(p, wx, wy)
        wield(p, S.ARM_PISTOL)
        n0 = len(w.pickups)
        click(p)
        w.step(DT)
        self.assertIsNone(car.parts["WheelFR"])
        self.assertEqual(len(w.pickups), n0 + 1, "the shredded wheel lands on the road")

    def test_cop_car_burns_after_enough_rounds(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p)
        p.x, p.y = street(w)
        cop = S.Car(w.new_id(), S.COP, p.x + 15, p.y, math.pi / 2, S.cop_loadout(w.rng))
        cop.confused_t = 99
        w.cars[cop.id] = cop
        face(p, cop.x, cop.y)
        wield(p, S.ARM_PISTOL)
        for _ in range(C.COP_CAR_HITS):
            click(p)
            step(w, C.PISTOL_COOLDOWN + 0.02)
            face(p, cop.x, cop.y)
        self.assertEqual(w.heat, C.HEAT_MAX, "shooting at the police: a bold choice")
        self.assertTrue(cop.fire_t > 0 or cop.id not in w.cars)

    def test_arrest_confiscates_guns(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p, shotgun=True)
        w.arrest(p)
        self.assertFalse(p.owns(S.ARM_PISTOL))
        self.assertFalse(p.owns(S.ARM_SHOTGUN))


class TestTrapsAndCarjacking(unittest.TestCase):
    def _lone_traffic(self, w):
        w.traffic_target = 1
        for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
            del w.cars[cid]
        i, j = C.BLOCKS // 2 + 1, C.BLOCKS // 2 + 1
        car = S.Car(w.new_id(), S.TRAFFIC, 0, 0, 0.0, S.kei_loadout(w.rng), color=3)
        car.x, car.y = w._lane_point(i, j, (1, 0), -30.0)
        car.route_prev = w._lane_point(i - 1, j, (1, 0), 8.0)
        car.route = [w._lane_point(i, j, (1, 0), -8.0)]
        car.tdir, car.node = (1, 0), (i, j)
        car.vx = 11.0
        w.cars[car.id] = car
        return car

    def test_spike_strip_shreds_tyres_and_the_driver_bails(self):
        w = world(traffic=True)
        car = self._lone_traffic(w)
        p = w.add_player("BRYCE")
        p.gear[0] = 1
        p.x, p.y = car.x + 12, car.y - 5
        face(p, p.x + 1, p.y)                    # looking along the road; strip goes across it
        # drop it in the car's lane, a few metres ahead of it
        p.ang = 0.0
        w._place_trap(p, S.TRAP_SPIKES)
        t = next(iter(w.traps.values()))
        t.x, t.y = car.x + 14, car.y
        self.assertEqual(p.gear[0], 0)
        step(w, 3.0)
        self.assertGreaterEqual(car.missing_wheels(), 2)
        self.assertEqual(car.kind, S.CIV, "driver bailed")
        self.assertEqual(car.state, S.RUNNING)

    def test_roadblock_stops_traffic_then_carjack_it(self):
        w = world(traffic=True)
        car = self._lone_traffic(w)
        p = w.add_player("BRYCE")
        p.gear[1] = 1
        p.x, p.y = car.x + 22, car.y + 3
        p.ang = math.pi                          # facing back down the road at the oncoming car
        w._place_trap(p, S.TRAP_BLOCK)
        t = next(iter(w.traps.values()))
        self.assertAlmostEqual(abs(math.cos(t.ang)), 1.0, places=5)
        rx, ry, rw, rh = t.rect()
        self.assertGreater(rh, 10, "a roadblock spans the whole road")
        self.assertTrue(w.extra_rects, "roadblocks are solid")
        step(w, 5.0)
        self.assertLess(car.speed(), 0.5, "traffic stops at the roadblock")
        self.assertLess(car.x, rx, "...before it, not through it")
        # walk up to the driver's door and carjack
        p.x, p.y = car.to_world(0.0, -2.2)
        face(p, car.x, car.y)
        w.step(DT)
        self.assertIn("CARJACK", p.prompt)
        heat0 = w.heat
        press(p, S.B_USE)
        step(w, C.CARJACK_TIME + 0.1)
        self.assertEqual(p.state, S.DRIVER)
        self.assertEqual(car.kind, S.CIV)
        self.assertTrue(car.stolen)
        self.assertGreaterEqual(w.heat, heat0 + C.CARJACK_HEAT - 0.5)

    def test_moving_traffic_tells_you_how_to_stop_it(self):
        w = world(traffic=True)
        car = self._lone_traffic(w)
        p = w.add_player("BRYCE")
        p.x, p.y = car.to_world(0.0, -2.3)
        face(p, car.x, car.y)
        key, label, _, _ = w._find_interaction(p)
        self.assertIsNone(key)
        self.assertIn("STOP IT FIRST", label)

    def test_ramming_a_roadblock_hard_breaks_it(self):
        w = world()
        p = w.add_player("BRYCE")
        p.gear[1] = 1
        p.x, p.y = street(w)
        p.ang = 0.0
        w._place_trap(p, S.TRAP_BLOCK)
        t = next(iter(w.traps.values()))
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = t.x - 8, t.y, 0.0
        car.vx = 20.0
        w._enter_car(w.add_player("RAMMER"), car, S.DRIVER)
        step(w, 0.8)
        self.assertEqual(w.traps, {}, "matchsticks")


class TestProtocol(unittest.TestCase):
    def test_arsenal_traps_and_tracers_go_over_the_wire(self):
        w = world()
        p = w.add_player("BRYCE")
        armed(p, shotgun=True)
        p.gear = [2, 1, 0, 0]
        p.weapon = S.ARM_SHOTGUN
        p.x, p.y = street(w)
        p.ang = 0.0
        w._place_trap(p, S.TRAP_SPIKES)
        w.tracer(S.ARM_PISTOL, p.x, p.y, p.x + 10, p.y + 1)
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertEqual(snap.arsenal, (S.ARM_SHOTGUN, p.arms, 24, 10, 1, 1, 0, 0))
        self.assertEqual(len(snap.traps), 1)
        self.assertEqual(snap.players[p.id][14], S.ARM_SHOTGUN)
        shots = [e for e in snap.events if e[1] == 2]
        self.assertEqual(len(shots), 1)
        self.assertAlmostEqual(shots[0][2][3], p.x + 10, delta=0.1)

    def test_worst_case_packet_with_traps_still_fits(self):
        w = S.World(map_seed=99, rng_seed=2)
        for i in range(4):
            w.add_player("PLAYERNAME%d" % i)
        p = w.players[1]
        for k in range(C.MAX_TRAPS):
            t = S.Trap(w.new_id(), k % 2, 200 + k * 3, 200, 0.0)
            w.traps[t.id] = t
        for k in range(30):
            w.tracer(1, 1, 2, 3, 4)
            w.toast("A VERY LONG TOAST MESSAGE NUMBER %d THAT GOES ON AND ON AND ON" % k)
        pkt = P.encode_snapshot(w, p.id, 0, 0)
        self.assertLessEqual(len(pkt), C.MAX_PACKET)


if __name__ == "__main__":
    unittest.main()

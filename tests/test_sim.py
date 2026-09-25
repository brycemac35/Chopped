"""Headless pure-simulation tests. No pygame, no sockets: just the World."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped.parts import Part, SLOTS

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def press(p, buttons):
    i = p.input
    p.input = S.InputState(buttons, i.use_count, i.drop_count, i.exit_count, i.yaw)


def face(p, x, y):
    """First person: look at (x, y)."""
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, math.atan2(y - p.y, x - p.x))
    p.ang = p.input.yaw


def quiet_world(seed=4242):
    """A world with no pedestrians or cameras, so heat only moves when a test says so."""
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    for cid in [c.id for c in w.cars.values() if c.kind == S.TRAFFIC]:
        del w.cars[cid]
    return w


def civ_cars(w):
    return [c for c in w.cars.values() if c.kind == S.CIV]


def road_point(w):
    """Middle of the road just south of the shop entrance."""
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2, gy + gh + 10.0


class TestCoreLoop(unittest.TestCase):
    def test_steal_deliver_strip_sell_rent_gameover_keeps_mods(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        gx, gy, gw, gh = w.map.garage_rect
        car = civ_cars(w)[0]
        self.assertEqual(car.state, S.LOCKED)
        car.special = None
        # --- break in: hold E at the driver door, looking at it
        p.x, p.y = car.to_world(0.0, -2.0)
        face(p, car.x, car.y)
        press(p, S.B_USE)
        step(w, C.BREAKIN_TIME - 0.5)
        self.assertEqual(car.state, S.LOCKED, "break-in finished too early")
        step(w, 0.6)
        self.assertEqual(car.state, S.BROKEN_IN)
        self.assertTrue(car.alarm)
        self.assertGreaterEqual(w.heat, C.HEAT_BREAKIN - 0.5)  # (may have cooled a hair since)
        # --- hotwire: release, then hold E 6 s -> you're the driver
        press(p, 0)
        step(w, DT)
        press(p, S.B_USE)
        step(w, C.HOTWIRE_TIME + 0.1)
        self.assertEqual(car.state, S.RUNNING)
        self.assertEqual(p.state, S.DRIVER)
        self.assertEqual(car.driver, p.id)
        # --- drive into the garage for real: line up on the road, floor it, brake
        press(p, 0)
        car.x, car.y = road_point(w)
        car.ang, car.vx, car.vy, car.w = -math.pi / 2, 0.0, 0.0, 0.0
        press(p, S.B_UP)
        for _ in range(600):
            w.step(DT)
            if car.y < gy + gh - 11:
                press(p, S.B_DOWN)
            if car.state == S.DELIVERED:
                break
        self.assertEqual(car.state, S.DELIVERED, "car never delivered (at %.1f,%.1f)" % (car.x, car.y))
        self.assertFalse(car.alarm)
        self.assertEqual(w.heat, 0.0)
        self.assertEqual(p.state, S.FOOT, "occupants should hop out on delivery")
        press(p, 0)
        step(w, DT)
        # --- replacement city car within ~5 s
        step(w, C.CIV_RESPAWN_DELAY + 0.5)
        self.assertEqual(len([c for c in civ_cars(w) if c.state != S.DELIVERED]), C.MAX_CIVILIAN_CARS)
        # delivered cars never drive again
        self.assertIsNone(car.driver)
        # --- strip the front-left wheel (4 s)
        car.vx = car.vy = car.w = 0.0
        p.x, p.y = car.to_world(1.4, -2.1)
        face(p, *car.to_world(1.4, -1.3))
        wheel = car.parts["WheelFL"]
        press(p, S.B_USE)
        step(w, S.STRIP_TIME["wheel"] + 0.1)
        self.assertIsNone(car.parts["WheelFL"])
        self.assertEqual(p.hands, [wheel])
        press(p, 0)
        step(w, DT)
        # --- sell it (1 s at the sell bench)
        bx, by, bw, bh = w.map.sell_bench
        p.x, p.y = bx + bw / 2, by + bh + 1.0
        face(p, bx + bw / 2, by)
        cash0 = w.cash
        press(p, S.B_USE)
        step(w, C.SELL_TIME + 0.1)
        self.assertEqual(p.hands, [])
        self.assertEqual(w.cash, cash0 + wheel.value)
        press(p, 0)
        step(w, DT)
        # --- tune-up bench: install a tuned ECU on the personal car (3 s)
        personal = w.cars[w.personal_id]
        old_ecu = personal.parts["ECU"]
        p.hands = [Part("ecu_tuned", 1.0)]
        tx, ty, tw, th = w.map.tune_bench
        p.x, p.y = tx + tw / 2, ty + th + 1.0
        face(p, tx + tw / 2, ty)
        n_pick = len(w.pickups)
        press(p, S.B_USE)
        step(w, C.INSTALL_TIME + 0.1)
        self.assertEqual(personal.parts["ECU"].type_id, "ecu_tuned")
        self.assertEqual(p.hands, [])
        self.assertEqual(len(w.pickups), n_pick + 1, "replaced ECU should drop out")
        self.assertIn(old_ecu, [pk.part for pk in w.pickups.values()])
        press(p, 0)
        # --- midnight: rent for day 1, then day 2 costs more
        cash0 = w.cash
        w.day_t = 0.001
        w.step(DT)
        self.assertEqual(w.cash, cash0 - C.RENT_BASE)
        self.assertEqual(w.day, 2)
        self.assertEqual(w.rent_due(), C.RENT_BASE + C.RENT_PER_DAY)
        self.assertAlmostEqual(w.day_t, C.DAY_LENGTH, delta=0.1)
        # --- debt -> SHOP SEIZED -> new run
        personal.x += 30.0          # drive it off somewhere; it should come home
        w.cash = -10
        w.step(DT)
        self.assertGreater(w.debt_t, 0)
        w.debt_t = C.DEBT_GRACE - 0.001
        w.step(DT)
        self.assertGreater(w.gameover_t, 0, "should be in SHOP SEIZED banner")
        step(w, C.GAMEOVER_BANNER + 0.2)
        self.assertEqual(w.run, 2)
        self.assertEqual(w.cash, C.START_CASH)
        self.assertEqual(w.day, 1, "a new run starts back on day 1")
        self.assertEqual(w.heat, 0.0)
        self.assertEqual(len(w.pickups), 0)
        self.assertNotIn(car.id, w.cars, "half-stripped cars are removed on reset")
        self.assertTrue(all(c.state == S.LOCKED for c in civ_cars(w)))
        self.assertEqual(len(civ_cars(w)), C.MAX_CIVILIAN_CARS)
        self.assertEqual(w.cars[w.personal_id].parts["ECU"].type_id, "ecu_tuned", "personal mods must survive")
        self.assertAlmostEqual(w.cars[w.personal_id].x, w.map.bay[0], delta=0.01)
        self.assertEqual(p.hands, [])
        self.assertTrue(w.map.in_garage(p.x, p.y))

    def test_dolly_engine_and_crush(self):
        w = quiet_world()
        p = w.add_player("BOB")
        car = civ_cars(w)[0]
        car.state = S.DELIVERED
        car.stolen = True
        for s in SLOTS:
            if s != "Engine":
                car.parts[s] = None
        engine = car.parts["Engine"]
        p.x, p.y = car.to_world(2.7, 0.0)
        face(p, car.x, car.y)
        key, label, dur, act = w._find_interaction(p)
        self.assertIn("CRUSH", label)
        cash0 = w.cash
        press(p, S.B_USE)
        step(w, C.CRUSH_TIME + 0.1)
        self.assertNotIn(car.id, w.cars)
        self.assertEqual(w.cash, cash0 + C.SHELL_VALUE + int(engine.value * C.CRUSH_DOLLY_FRACTION))

    def test_engine_prompt_says_dolly_only(self):
        w = quiet_world()
        p = w.add_player("BOB")
        car = civ_cars(w)[0]
        car.state = S.DELIVERED
        car.parts["Hood"] = None
        p.x, p.y = car.to_world(2.6, 0.0)     # at the nose, looking into the engine bay
        face(p, car.x, car.y)
        key, label, dur, act = w._find_interaction(p)
        self.assertIsNone(key)
        self.assertIn("DOLLY", label)

    def test_hands_limits_and_stamina(self):
        w = quiet_world()
        p = w.add_player("BOB")
        self.assertTrue(p.can_hold(Part("whl_stock_alloy")))
        p.hands = [Part("whl_stock_alloy"), Part("ecu_stock")]
        self.assertFalse(p.can_hold(Part("whl_stock_alloy")))
        p.hands = [Part("door_stock")]
        self.assertFalse(p.can_hold(Part("ecu_stock")), "a door takes both hands")
        self.assertFalse(S.Player(9, "X", 0).can_hold(Part("eng_stock_1_6")), "engines are dolly-only")
        # sprinting with a two-handed part drains 38/s
        p.x, p.y = road_point(w)
        press(p, S.B_RIGHT | S.B_SPRINT)
        step(w, 1.0)
        self.assertAlmostEqual(p.stamina, 100 - 38, delta=1.5)
        step(w, 2.0)
        self.assertTrue(p.exhausted)
        self.assertFalse(p.sprinting)
        press(p, 0)
        step(w, 0.5)
        self.assertEqual(p.stamina, 0.0, "no regen for 0.9 s")
        step(w, 0.9 + 25 / 18.0)
        self.assertFalse(p.exhausted)


class TestHeat(unittest.TestCase):
    def _stolen_car_with_ped(self):
        w = quiet_world()
        x, y = road_point(w)
        x += 60.0
        car = civ_cars(w)[0]
        car.x, car.y, car.ang = x, y, 0.0
        car.state, car.stolen = S.BROKEN_IN, True
        ped = S.NPC(w.new_id(), S.PED, x + 10.0, y)
        w.npcs[ped.id] = ped
        # freeze the ped so it doesn't wander out of sight mid-test
        ped.dirx = ped.diry = 0.0
        ped.turn_t = 1e9
        return w, car, ped

    def test_witness_raises_heat_then_cools(self):
        w, car, ped = self._stolen_car_with_ped()
        w.heat = 20.0
        step(w, 1.0)
        self.assertEqual(w.witness, S.W_PED)
        self.assertAlmostEqual(w.heat, 23.0, delta=0.4)
        del w.npcs[ped.id]
        step(w, 3.5)                      # unseen, but not yet 4 s
        self.assertAlmostEqual(w.heat, 23.0, delta=0.4)
        self.assertEqual(w.witness, S.W_NONE)
        step(w, 2.5)                      # now ~2 s of cooling at 3/s
        self.assertAlmostEqual(w.heat, 23.0 - 2.0 * C.HEAT_COOL_RATE, delta=0.8)

    def test_cop_outranks_ped_no_stacking(self):
        w, car, ped = self._stolen_car_with_ped()
        cop = S.Car(w.new_id(), S.COP, car.x - 15, car.y, 0.0, {s: None for s in SLOTS})
        cop.confused_t = 999      # keep it parked (well, doing donuts) for the test
        w.cars[cop.id] = cop
        w.heat = 10.0
        step(w, 1.0)
        self.assertEqual(w.witness, S.W_COP)
        self.assertAlmostEqual(w.heat, 15.0, delta=0.6)   # +5/s, not 5+3

    def test_camera_sees_only_cars(self):
        w = quiet_world()
        p = w.add_player("BOB")
        x, y = road_point(w)
        x += 60
        w.map.cameras = [(x + 8, y)]
        p.x, p.y = x, y
        w.heat = 5.0
        step(w, 0.5)
        self.assertNotEqual(w.witness, S.W_CAMERA, "cameras ignore people on foot")
        car = civ_cars(w)[0]
        car.x, car.y = x - 4, y
        car.state, car.stolen = S.BROKEN_IN, True
        step(w, 0.5)
        self.assertEqual(w.witness, S.W_CAMERA)


class TestCops(unittest.TestCase):
    def test_cops_spawn_at_100_far_from_players(self):
        w = quiet_world()
        p = w.add_player("BOB")
        p.x, p.y = road_point(w)
        spawned = []
        orig = w.spawn_cop

        def spy():
            c = orig()
            if c:
                spawned.append((w.time, min(math.hypot(q.x - c.x, q.y - c.y) for q in w.players.values())))
            return c
        w.spawn_cop = spy
        w.heat = 99.0
        step(w, 0.5)
        self.assertEqual(spawned, [], "no cops below 100")
        w.heat = 100.0
        w.unseen_t = 0.0
        step(w, 1.0)
        self.assertEqual(len(spawned), 1)
        step(w, 1.5)
        self.assertEqual(len(spawned), 2)
        self.assertAlmostEqual(spawned[1][0] - spawned[0][0], C.COP_SPAWN_GAP, delta=0.15)
        for _, d in spawned:
            self.assertGreaterEqual(d, C.COP_SPAWN_MIN_DIST)
        step(w, 3.0)
        self.assertEqual(len([c for c in w.cars.values() if c.kind == S.COP]), 2, "max 2 cops")
        # heat to zero -> cops leave after 3 s
        w.heat = 0.0
        p.x, p.y = w.map.player_spawns[0]
        w.heat = 0.0
        step(w, 0.2)
        w.heat = 0.0
        w.witness_rate = 0.0
        for c in [c for c in w.cars.values() if c.kind == S.COP]:
            c.x, c.y = 20, 6            # out of sight, round the ring road
        step(w, C.COP_DESPAWN_AT_ZERO + 0.3)
        self.assertEqual([c for c in w.cars.values() if c.kind == S.COP], [])

    def test_arrest_drops_parts_partner_grabs_them(self):
        w = quiet_world()
        a = w.add_player("ALICE")
        b = w.add_player("BOB")
        x, y = road_point(w)
        x += 40
        a.x, a.y = x, y
        a.hands = [Part("whl_stock_alloy"), Part("ecu_tuned")]
        cop = S.Car(w.new_id(), S.COP, x + 2.8, y, math.pi, {s: None for s in SLOTS})
        w.cars[cop.id] = cop
        w.heat = 50.0
        step(w, 1.15)
        self.assertEqual(a.state, S.CUFFED)
        self.assertEqual(a.hands, [])
        near = [pk for pk in w.pickups.values() if math.hypot(pk.x - x, pk.y - y) < 4.0]
        self.assertEqual(len(near), 2)
        self.assertGreater(w.cash, -1)  # cash untouched
        # partner scoops one up
        del w.cars[cop.id]
        pk = near[0]
        step(w, 0.5)
        b.x, b.y = pk.x + 0.3, pk.y
        face(b, pk.x, pk.y)
        press(b, S.B_USE)
        step(w, C.PICKUP_TIME + 0.1)
        self.assertEqual(len(b.hands), 1)
        step(w, C.CUFFED_TIME)
        self.assertEqual(a.state, S.FOOT)
        self.assertTrue(w.map.in_garage(a.x, a.y), "respawn at the shop")

    def test_horn_confuses_cop(self):
        w = quiet_world()
        p = w.add_player("BOB")
        personal = w.cars[w.personal_id]
        x, y = road_point(w)
        cop = S.Car(w.new_id(), S.COP, x + 30, y, 0.0, {s: None for s in SLOTS})
        w.cars[cop.id] = cop
        personal.x, personal.y = x, y
        w._enter_car(p, personal, S.DRIVER)
        press(p, S.B_HORN)
        step(w, 0.1)
        self.assertGreater(cop.confused_t, 0)
        self.assertEqual(cop.steer, 1.0)
        self.assertTrue(cop.handbrake, "donuts require handbrake")

    def test_ramming_cop_ignites_and_explodes_into_loot(self):
        w = quiet_world()
        p = w.add_player("BOB")
        personal = w.cars[w.personal_id]
        x, y = road_point(w)
        x += 60
        cop = S.Car(w.new_id(), S.COP, x + 7, y, 0.0, S.cop_loadout(w.rng))
        cop.confused_t = 99
        w.cars[cop.id] = cop
        personal.x, personal.y, personal.ang = x, y, 0.0
        personal.vx = 32.0
        w._enter_car(p, personal, S.DRIVER)
        step(w, 0.3)
        self.assertGreater(cop.fire_t, 0, "a 32 m/s hit should set the cop on fire")
        n_parts = sum(1 for q in cop.parts.values() if q is not None)
        before = len(w.pickups)
        step(w, C.COP_BURN_TIME + 0.2)
        self.assertNotIn(cop.id, w.cars)
        self.assertGreaterEqual(len(w.pickups) - before, n_parts)


class TestCrashes(unittest.TestCase):
    def _wall_hit(self, speed):
        w = quiet_world()
        p = w.add_player("CRASHY")
        for cid in [c.id for c in w.cars.values()]:
            del w.cars[cid]
        T = C.TILE_M
        # a building whose south face is open sidewalk (not another building)
        bx, by, bw, bh, _ = next(b for b in w.map.buildings
                                 if w.map.tile_at((b[0] + b[2] / 2) * T, (b[1] + b[3]) * T + 1) == 1)
        face_y = (by + bh) * T
        cx = (bx + bw / 2) * T
        car = S.Car(w.new_id(), S.CIV, cx, face_y + 2.2 + 0.05, -math.pi / 2,
                    {s: (Part(q.type_id, 1.0) if q else None) for s, q in S.personal_loadout().items()})
        car.state = S.RUNNING
        car.stolen = True
        w.cars[car.id] = car
        w._enter_car(p, car, S.DRIVER)
        car.vy = -speed
        crashes = []
        orig = w._crash

        def spy(c, dv, nx, ny):
            crashes.append(dv)
            orig(c, dv, nx, ny)
        w._crash = spy
        step(w, 0.3)
        return w, p, car, crashes

    def test_gentle_bump_no_damage(self):
        w, p, car, crashes = self._wall_hit(3.5)
        self.assertEqual(crashes, [])
        self.assertEqual(p.state, S.DRIVER)

    def test_dent_threshold(self):
        w, p, car, crashes = self._wall_hit(7.0)
        self.assertEqual(len(crashes), 1)
        self.assertGreaterEqual(crashes[0], C.CRASH_DENT_DV)
        self.assertLess(crashes[0], C.CRASH_EJECT_DV)
        self.assertEqual(p.state, S.DRIVER, "a dent doesn't eject you")
        self.assertTrue(all(q.condition < 1.0 for q in car.parts.values() if q is not None))

    def test_eject_threshold(self):
        w, p, car, crashes = self._wall_hit(12.0)
        self.assertTrue(crashes and crashes[0] >= C.CRASH_EJECT_DV)
        self.assertEqual(p.state, S.TUMBLE)
        self.assertGreaterEqual(p.tumble_t, 0.5)
        self.assertGreaterEqual(len(w.pickups), 1, "1-3 parts fly off")
        self.assertEqual(car.missing_wheels(), 0, "wheels survive an 15 m/s dv")

    def test_wheel_threshold(self):
        w, p, car, crashes = self._wall_hit(21.0)
        self.assertTrue(crashes and crashes[0] >= C.CRASH_WHEEL_DV)
        self.assertGreaterEqual(car.missing_wheels(), 1)
        self.assertIsNone(car.parts["WheelFL"] and car.parts["WheelFR"], "front wheel(s) lost in a head-on")

    def test_fast_car_sends_pedestrian_tumbling(self):
        w = quiet_world()
        x, y = road_point(w)
        x += 40
        ped = S.NPC(w.new_id(), S.PED, x + 4, y)
        ped.dirx = ped.diry = 0
        ped.turn_t = 1e9
        w.npcs[ped.id] = ped
        car = civ_cars(w)[0]
        car.x, car.y, car.ang, car.vx = x, y, 0.0, 12.0
        n_toasts = len(w.events)
        step(w, 0.4)
        self.assertGreater(ped.tumble_t, 0)
        self.assertGreater(len(w.events), n_toasts, "pedestrian complains")


class TestSpecials(unittest.TestCase):
    def test_clown_car_and_angry_owner(self):
        w = quiet_world()
        p = w.add_player("BOB")
        a, b = civ_cars(w)[:2]
        a.special, b.special = "clown", "owner"
        w._break_in(p, a)
        clowns = [n for n in w.npcs.values() if n.kind == S.CLOWN]
        self.assertEqual(len(clowns), C.CLOWN_COUNT)
        w._break_in(p, b)
        owners = [n for n in w.npcs.values() if n.kind == S.OWNER]
        self.assertEqual(len(owners), 1)
        self.assertAlmostEqual(math.hypot(owners[0].x - b.x, owners[0].y - b.y), C.OWNER_SPAWN_DIST, delta=0.5)
        step(w, C.CLOWN_LIFETIME + 0.5)
        self.assertEqual([n for n in w.npcs.values() if n.kind == S.CLOWN], [], "clowns vanish after 40 s")


if __name__ == "__main__":
    unittest.main()


class TestDays(unittest.TestCase):
    def test_rent_goes_up_every_day(self):
        w = quiet_world()
        cash = []
        for day in range(1, 5):
            self.assertEqual(w.day, day)
            c0 = w.cash
            w.day_t = 0.001
            w.step(DT)
            cash.append(c0 - w.cash)
        self.assertEqual(cash, [C.rent_for_day(d) for d in range(1, 5)])
        self.assertEqual(cash, sorted(cash), "the landlord only ever gets greedier")
        self.assertLess(cash[0], 150, "day 1 is cheaper than the old $150-a-minute")

    def test_day_summary_counts_the_haul(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        p.hands = [Part("whl_stock_alloy", 1.0)]
        w._sell(p)
        w.day_t = 0.001
        w.step(DT)
        texts = [e[3][1] for e in w.events if e[2] == 0]
        self.assertTrue(any("DAY 1 DONE" in t and "1 PARTS" in t for t in texts), texts)

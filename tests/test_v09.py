"""v0.9: selling a car whole, sizing cars up before you nick them, parked cars
that don't knock you over, getting properly launched by moving ones, longer
throws, the shop's roof and roller door, and this round's silly department."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import vehicles as V
from chopped.parts import Part, model_loadout
from chopped.predict import Predictor
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
    for pid in [k for k, pk in w.pickups.items() if pk.fixed]:
        del w.pickups[pid]
    return w


def inp(p, **kw):
    i = p.input
    d = dict(buttons=i.buttons, use_count=i.use_count, drop_count=i.drop_count, exit_count=i.exit_count, yaw=i.yaw,
             fire_count=i.fire_count, weapon=i.weapon)
    d.update(kw)
    p.input = S.InputState(**d)


def face(p, x, y):
    inp(p, yaw=math.atan2(y - p.y, x - p.x))
    p.ang = p.input.yaw


def street(w):
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2 + 30, gy + gh + 10.0


def civ(w, x, y, model=V.COUPE, ang=0.0):
    import random
    car = S.Car(w.new_id(), S.CIV, x, y, ang, model_loadout(random.Random(3), model), model=model)
    w.cars[car.id] = car
    return car


def snap(w, p):
    return P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])


class TestSellWhole(unittest.TestCase):
    def delivered(self, w, model=V.COUPE):
        gx, gy, gw, gh = w.map.garage_rect
        car = civ(w, gx + gw / 2, gy + gh / 2 + 3, model)
        car.state, car.stolen = S.DELIVERED, True
        return car

    def test_x_sells_it_whole(self):
        w = world()
        p = w.add_player("BRYCE")
        car = self.delivered(w)
        car.trunk.append(Part("cash_bag"))
        price = w.whole_price(car)
        parts = sum(pt.value for pt in car.parts.values() if pt is not None)
        self.assertEqual(price, int(parts * C.WHOLE_SALE_RATE) + C.SHELL_VALUE + C.WHOLE_SALE_SPORTY)
        p.x, p.y = car.x, car.y - car.hw - 1.2
        face(p, car.x, car.y)
        w.step(DT)
        self.assertIn("X: SELL IT WHOLE $%d" % price, p.prompt)
        cash = w.cash
        inp(p, buttons=S.B_HOP)
        w.step(DT)
        self.assertNotIn(car.id, w.cars, "Dave drove it away")
        self.assertEqual(w.cash, cash + price)
        self.assertTrue(any(pk.part.type_id == "cash_bag" for pk in w.pickups.values()),
                        "the boot's contents stay with you")

    def test_whole_is_less_than_stripping_but_the_collector_pays_for_complete(self):
        w = world()
        car = self.delivered(w)
        parts = sum(pt.value for pt in car.parts.values() if pt is not None)
        full = w.whole_price(car)
        self.assertLess(full, parts + C.SHELL_VALUE + C.WHOLE_SALE_SPORTY + 1)
        car.parts["DoorL"] = None
        self.assertLess(w.whole_price(car), full - C.WHOLE_SALE_SPORTY + 1, "no bonus once it's missing a door")

    def test_only_delivered_cars(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        car = civ(w, x, y)
        cash = w.cash
        w._sell_whole(p, car)
        self.assertIn(car.id, w.cars)
        self.assertEqual(w.cash, cash)


class TestInspect(unittest.TestCase):
    def test_look_at_a_car_and_size_it_up(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        car = civ(w, x + 7, y)
        car.trunk.append(Part("briefcase"))
        car.parts["Engine"] = Part("eng_tt_3_0", 0.8)
        face(p, car.x, car.y)
        step(w, 0.2)
        self.assertEqual(p.inspect, car.id)
        s = snap(w, p)
        cid, value, model, eng, trn, ecu, cond, flags, best = s.inspect
        self.assertEqual(cid, car.id)
        self.assertEqual(model, V.COUPE)
        self.assertEqual(eng, "eng_tt_3_0")
        self.assertTrue(flags & S.INSP_RATTLE, "something rattles in the boot")
        self.assertLessEqual(len(best), 3)
        total = sum(pt.value for pt in car.parts.values() if pt is not None)
        self.assertLess(abs(value - total), 10)
        self.assertGreater(cond, 0.0)

    def test_not_behind_you_not_through_walls_not_your_own(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        car = civ(w, x + 7, y)
        face(p, x - 10, y)                              # (looking the other way)
        step(w, 0.2)
        self.assertEqual(p.inspect, 0)
        mine = w.cars[w.personal_id]
        p.x, p.y = mine.x - 5, mine.y
        face(p, mine.x, mine.y)
        step(w, 0.2)
        self.assertNotEqual(p.inspect, mine.id, "you know what's in your own car")
        s = snap(w, p)
        self.assertTrue(s.inspect is None or s.inspect[0] != mine.id)


class TestParkedCarsAndCarHits(unittest.TestCase):
    """Bryce: "the hitbox for the vehicles not moving needs to not hit you while its
    parked / not moving ... also please add velocity when you're being hit so you
    slide if you're hit by a car. also throw people farther." """

    def test_sprinting_into_a_parked_car_doesnt_floor_you(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        car = civ(w, x + 4, y)
        p.x, p.y = x, y
        face(p, car.x, car.y)
        inp(p, buttons=S.B_UP | S.B_SPRINT)
        for _ in range(int(1.5 / DT)):
            w.step(DT)
            self.assertNotEqual(p.state, S.TUMBLE, "a parked car is a wall, not a weapon")
        self.assertLess(abs(p.x - car.x), car.hl + 1.0, "you're up against it")

    def test_a_moving_car_launches_you_down_the_road(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        car = civ(w, x - 6, y)
        car.state, car.driver = S.RUNNING, 999
        car.vx = 20.0
        for _ in range(int(0.6 / DT)):
            car.vx = max(car.vx, 18.0)
            w.step(DT)
            if p.state == S.TUMBLE:
                break
        self.assertEqual(p.state, S.TUMBLE)
        self.assertGreater(p.vx, 15.0, "you leave at the car's speed, give or take")
        x0 = p.x
        step(w, 1.5)
        self.assertGreater(p.x - x0, 12.0, "and you slide")

    def test_thrown_people_go_further(self):
        w = world()
        a, b = w.add_player("A"), w.add_player("B")
        x, y = street(w)
        a.x, a.y = x, y
        b.x, b.y = x + 1.2, y
        face(a, b.x, b.y)
        inp(a, drop_count=a.input.drop_count + 1)
        w.step(DT)
        inp(a, fire_count=a.input.fire_count + 1)
        w.step(DT)
        step(w, 4.0)
        self.assertGreater(b.x, a.x + 11, "a proper yeet")


class TestShopDoor(unittest.TestCase):
    """Bryce: "add a roof to the chop shop and a closable door that blocks cops. but it
    needs to be opened for you to get in." Then (v0.10): "make the garage door smaller,
    make a walking entrance and a bay for each player that joins" -- one door became five:
    a walking door (shop_doors[0]) and four bay doors (shop_doors[1:], one per player)."""

    def shut(self, w, d):
        w.toggle_door(d)
        step(w, C.DOOR_TIME + 0.1)
        self.assertTrue(d.solid())

    def test_open_by_default_shut_on_request(self):
        w = world()
        self.assertEqual(len(w.shop_doors), 1 + C.N_BAYS)
        d = w.shop_doors[1]
        self.assertFalse(w.door_shut())
        self.assertNotIn(d.rect(), w.extra_rects)
        self.shut(w, d)
        self.assertIn(d.rect(), w.tall_rects)
        w.toggle_door(d)
        step(w, C.DOOR_TIME + 0.1)
        self.assertFalse(d.solid())

    def test_e_at_a_bay_door(self):
        w = world()
        p = w.add_player("BRYCE")
        d = w.shop_doors[1]
        p.x, p.y = d.x, d.y - 1.5
        face(p, d.x, d.y + 3)
        w.step(DT)
        self.assertIn("BAY DOOR", p.prompt)
        inp(p, use_count=p.input.use_count + 1)
        w.step(DT)
        self.assertEqual(d.goal, 0.0)

    def test_each_bay_door_is_independent(self):
        w = world()
        d0, d1 = w.shop_doors[1], w.shop_doors[2]
        self.shut(w, d0)
        self.assertTrue(d0.solid())
        self.assertFalse(d1.solid(), "shutting one bay doesn't shut the others")

    def test_the_walking_door_is_its_own_door(self):
        w = world()
        walk = w.shop_doors[0]
        self.assertNotEqual(walk.id, w.shop_doors[1].id)
        self.shut(w, walk)
        for d in w.shop_doors[1:]:
            self.assertFalse(d.solid(), "shutting the walking door leaves every bay open")

    def test_it_stops_cops(self):
        w = world()
        d = w.shop_doors[1]
        self.shut(w, d)
        cop = S.Car(w.new_id(), S.COP, d.x, d.y + 8, -math.pi / 2, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        cop.vy = -15.0
        officer = S.NPC(w.new_id(), S.OFFICER, d.x + 6, d.y + 1.0)
        w.npcs[officer.id] = officer
        for _ in range(int(1.5 / DT)):
            cop.throttle = 1.0
            officer.vy = -5.0
            w.step(DT)
        self.assertGreater(cop.y - cop.hl, d.y - 0.5, "the cop car stays outside")
        self.assertGreater(officer.y, d.y, "and so does the officer")

    def test_they_cant_see_through_it(self):
        w = world()
        d = w.shop_doors[1]
        inside, outside = (d.x, d.y - 6), (d.x, d.y + 10)
        self.assertTrue(w.los(*inside, *outside))
        self.shut(w, d)
        self.assertFalse(w.los(*inside, *outside))
        self.assertTrue(w.los(outside[0] - 3, outside[1], outside[0] + 3, outside[1]), "only through it")

    def test_they_cant_see_through_the_pillars_between_doors_either(self):
        w = world()
        d1, d2 = w.shop_doors[2], w.shop_doors[3]      # bay 1 and bay 2: the pier is between them
        cx, cy = (d1.x + d2.x) / 2, d1.y
        self.assertFalse(w.los(cx, cy - 6, cx, cy + 10))

    def test_you_cant_walk_through_it_either(self):
        w = world()
        p = w.add_player("BRYCE")
        d = w.shop_doors[1]
        self.shut(w, d)
        p.x, p.y = d.x, d.y + 3
        face(p, d.x, d.y - 5)
        inp(p, buttons=S.B_UP)
        step(w, 1.5)
        self.assertGreater(p.y, d.y, "it needs to be opened for you to get in")

    def test_safety_sensor(self):
        w = world()
        d = w.shop_doors[1]
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = d.x, d.y, math.pi / 2          # parked right in its own doorway
        car.vx = car.vy = 0.0
        w.toggle_door(d)
        step(w, C.DOOR_TIME + 0.5)
        self.assertEqual(d.goal, 1.0, "BEEP BEEP BEEP")
        self.assertFalse(d.solid())

    def test_honk_to_open(self):
        w = world()
        for d in w.shop_doors[1:]:
            self.shut(w, d)
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        d = w.shop_doors[1]
        car.x, car.y, car.ang = d.x, d.y + 14, -math.pi / 2
        w._enter_car(p, car, S.DRIVER)
        inp(p, buttons=S.B_HORN)
        w.step(DT)
        inp(p, buttons=0)
        step(w, C.DOOR_TIME + 0.1)
        self.assertFalse(any(d.solid() for d in w.shop_doors[1:]), "the remote on the sun visor")
        self.assertFalse(w.shop_doors[0].solid(), "the walking door was never shut in the first place")

    def test_the_predictor_knows_the_door(self):
        w = world()
        p = w.add_player("BRYCE")
        d = w.shop_doors[1]
        p.x, p.y = d.x, d.y + 5
        pr = Predictor(CityMap(w.map_seed))
        pr.reconcile(snap(w, p))
        self.assertNotIn(d.rect(), pr.extra_rects)
        self.shut(w, d)
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]))
        self.assertIn(d.rect(), pr.extra_rects)
        self.assertIn(d.rect(), pr.tall_rects)


def ped(w, x, y):
    n = S.NPC(w.new_id(), S.PED, x, y)
    n.wallet = 20
    n.brave = False
    n.dirx, n.diry = 0, 0
    w.npcs[n.id] = n
    return n


def click(p):
    inp(p, fire_count=p.input.fire_count + 1)


class TestSillyDepartment(unittest.TestCase):
    """v0.9: "add 10 more silly features"."""

    def test_banana_and_donuts_are_selectable_again(self):
        # (v0.6's weapon clamp stopped at the roadblock, so keys 6 and 7 gave you your fists)
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.gear[2] = 1
        inp(p, weapon=S.ARM_BANANA)
        w.step(DT)
        self.assertEqual(p.weapon, S.ARM_BANANA)
        click(p)
        w.step(DT)
        self.assertTrue(any(t.kind == S.TRAP_BANANA for t in w.traps.values()))

    def test_rubber_chicken(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        w.cash = 500
        w._market_buy(p, "chicken", C.PRICE_CHICKEN)
        self.assertTrue(p.owns(S.ARM_CHICKEN))
        n = ped(w, p.x + 1.2, p.y)
        face(p, n.x, n.y)
        inp(p, weapon=S.ARM_CHICKEN)
        w.step(DT)
        heat = w.heat
        click(p)
        w.step(DT)
        self.assertGreater(n.tumble_t, 0, "SQUEAK. Down they go")
        self.assertGreater(abs(n.vx) + abs(n.vy), 5.0, "harder than a punch")
        self.assertEqual(w.heat, heat, "not a weapon, officer")

    def test_whoopee_cushion_makes_everyone_laugh_even_officers(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        t = S.Trap(w.new_id(), S.TRAP_WHOOPEE, x, y, 0.0)
        t.uses = C.WHOOPEE_USES
        w.traps[t.id] = t
        cop = S.NPC(w.new_id(), S.OFFICER, x + 6, y)
        w.npcs[cop.id] = cop
        n = ped(w, x, y)                                  # stands right on it
        p.x, p.y = x + 30, y
        w.step(DT)
        self.assertEqual(t.uses, C.WHOOPEE_USES - 1)
        self.assertGreater(cop.laugh_t, 0, "PFFFT. Even the law")
        step(w, 0.5)
        self.assertLess(abs(cop.vx) + abs(cop.vy), 0.01, "too busy laughing to chase anyone")

    def test_the_cardboard_box(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        w.cash = 500
        w.heat = 50
        w._market_buy(p, "box", C.PRICE_BOX)
        self.assertTrue(p.has_box)
        inp(p, buttons=S.B_BOX)
        w.step(DT)
        inp(p, buttons=0)
        self.assertTrue(p.boxed)
        self.assertAlmostEqual(p.speed_mult(), C.BOX_SPEED_MULT)
        step(w, C.BOX_STILL_TIME + 0.2)
        self.assertTrue(p.hidden(), "stood still: you're a box")
        self.assertNotIn(p, w._law_targets(), "the police see a box")
        self.assertFalse(any(t[5] is p for t in w._collect_targets()), "so do the witnesses")
        s = snap(w, p)
        self.assertTrue(s.players[p.id][17] & P.PF2_BOX)
        self.assertTrue(s.players[p.id][17] & P.PF2_HIDDEN)
        inp(p, buttons=S.B_UP)
        step(w, 0.3)
        self.assertFalse(p.hidden(), "a box with legs is not a box")
        inp(p, buttons=0)
        click(p)
        w.step(DT)
        self.assertIn("BOXES CAN'T PUNCH", " ".join(e[3][1] for e in w.events if e[2] == 0))

    def test_steal_the_cop_car_while_hes_out(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        cop = S.Car(w.new_id(), S.COP, x + 3, y, 0.0, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        officer = S.NPC(w.new_id(), S.OFFICER, x + 40, y)
        officer.car_id = cop.id
        w.npcs[officer.id] = officer
        cop.officer = officer.id
        p.x, p.y = x + 3, y - cop.hw - 1.0
        face(p, cop.x, cop.y)
        w.step(DT)
        self.assertIn("STEAL THE COP CAR", p.prompt)
        heat = w.heat
        inp(p, buttons=S.B_USE)
        step(w, C.COPCAR_STEAL_TIME + 0.2)
        self.assertEqual(p.state, S.DRIVER)
        self.assertEqual(cop.kind, S.CIV)
        self.assertTrue(cop.copcar)
        self.assertEqual(cop.horn_type, V.HORN_SIREN)
        self.assertGreaterEqual(w.heat, heat + C.COPCAR_STEAL_HEAT - 1)
        s = snap(w, p)
        self.assertTrue(s.cars[cop.id][18] & P.CX_COPCAR)

    def test_why_did_the_chicken_cross_the_road(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        chickens = []
        for _ in range(200):        # each roll only samples 40 candidate tiles; keep rolling
            chickens = [n for n in w.npcs.values() if n.kind == S.CHICKEN]
            if chickens:
                break
            w.chicken_t = 0.0
            w.step(DT)
        self.assertEqual(len(chickens), 1)
        ch = chickens[0]
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = ch.x - 5, ch.y, 0.0
        car.vx, car.vy = 15.0, 0.0
        car.driver = p.id
        for _ in range(int(1.0 / DT)):
            car.vx = max(car.vx, 12.0)
            w.step(DT)
            if ch.id not in w.npcs:
                break
        self.assertNotIn(ch.id, w.npcs, "it didn't")

    def test_mimes_are_not_witnesses_and_their_wallets_are_invisible(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        w.heat = 30
        mime = S.NPC(w.new_id(), S.MIME, x + 4, y)
        mime.wallet = 1
        w.npcs[mime.id] = mime
        w.targets = w._collect_targets()
        self.assertNotEqual(w._witness_scan()[0], S.W_PED, "what would he say?")
        cash = w.cash
        w._rob(p, mime)
        self.assertEqual(w.cash, cash, "$0. It was an invisible wallet")
        w.mime_t = 0.0
        w.step(DT)
        self.assertGreaterEqual(sum(1 for n in w.npcs.values() if n.kind == S.MIME), 1)

    def test_big_air(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y, ang = w.map.ramps[0]
        car = w.cars[w.personal_id]
        w._enter_car(p, car, S.DRIVER)
        car.x, car.y, car.ang = x - math.cos(ang) * 4, y - math.sin(ang) * 4, ang
        car.vx, car.vy = math.cos(ang) * 25, math.sin(ang) * 25
        inp(p, buttons=S.B_UP)
        took_off = False
        for _ in range(int(0.6 / DT)):
            w.step(DT)
            if car.air_t > 0:
                took_off = True
                break
        self.assertTrue(took_off)
        self.assertTrue(snap(w, p).cars[car.id][4] & P.CF_AIR)
        cash = w.cash
        step(w, 2.0)
        self.assertGreater(w.cash, cash, "the crowd pays")

    def test_money_truck(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        import random
        mt = S.Car(w.new_id(), S.TRAFFIC, x, y, 0.0, model_loadout(random.Random(1), V.ARMOURED), model=V.ARMOURED)
        w._money_truck(mt)
        w.cars[mt.id] = mt
        self.assertTrue(any(pt.type_id == "cash_bag" for pt in mt.trunk), "the day's takings")
        ex, ey = mt.x - mt.hl + 0.1, mt.y
        for _ in range(C.MONEY_TRUCK_HITS):
            w._shot_hits(p, mt, ex, ey, 0.0, False)
        self.assertTrue(mt.burst)
        bags = [pk for pk in w.pickups.values() if pk.part.type_id == "cash_bag"]
        self.assertGreaterEqual(len(bags), C.MONEY_TRUCK_BAGS[0])
        self.assertGreater(w.heat, 0)

    def test_arsenal_on_the_wire(self):
        w = world()
        p = w.add_player("BRYCE")
        p.gear = [1, 2, 3, 4, 5]
        p.has_box = True
        p.arms |= 1 << S.ARM_CHICKEN
        s = snap(w, p)
        self.assertEqual(len(s.arsenal), S.ARSENAL_LEN)
        self.assertEqual(s.arsenal[4:], (1, 2, 3, 4, 5, 1))
        for slot in (S.ARM_CHICKEN, S.ARM_WHOOPEE, S.ARM_BANANA):
            self.assertTrue(S.arsenal_owns(s.arsenal, slot))


class TestNoPygameInTheSim(unittest.TestCase):
    def test_sim_modules_dont_import_pygame(self):
        """The simulation is authoritative and testable: it must not need pygame."""
        import subprocess
        mods = ["sim", "physics", "brawl", "garage", "police", "sillies", "quests", "entities", "enums",
                "vehicles", "parts", "lines", "drivetrain", "enginesynth", "mapgen"]
        code = ("import sys; sys.modules['pygame'] = None; sys.path.insert(0, %r)\n"
                "import importlib\n"
                "for m in %r: importlib.import_module('chopped.' + m)\n"
                "print('ok')") % (os.path.dirname(os.path.dirname(os.path.abspath(__file__))), mods)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()

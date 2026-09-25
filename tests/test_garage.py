"""v0.7: the mod shop, the parts locker, trunks, and the car models they hang off."""

import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import garage as G
from chopped import vehicles as V
from chopped.parts import Part, SLOTS, model_loadout, PART_INDEX, roll_trunk

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def quiet_world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
        del w.cars[cid]
    return w


def face(p, x, y):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, math.atan2(y - p.y, x - p.x),
                           i.fire_count, i.weapon, i.menu_seq, i.menu_op, i.menu_arg, i.menu_arg2)
    p.ang = p.input.yaw


def menu(p, op, a=0, b=0):
    i = p.input
    p.input = S.InputState(i.buttons, i.use_count, i.drop_count, i.exit_count, i.yaw, i.fire_count, i.weapon,
                           (i.menu_seq + 1) & 255, op, a, b)


def in_shop(w, p):
    tx, ty, tw, th = w.map.tune_bench
    p.x, p.y = tx + tw / 2, ty + th + 1.0
    face(p, tx + tw / 2, ty)
    w._open_modshop(p)


class TestModShop(unittest.TestCase):
    def test_buy_a_styled_part_off_the_catalogue(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        in_shop(w, p)
        w.cash = 5000
        car = w.cars[w.personal_id]
        old = car.parts["WheelFL"]
        cat = G.catalogue("WheelFL")
        k = next(i for i, (tid, style, price) in enumerate(cat) if tid == "whl_tuned_light" and style == 2)
        price = cat[k][2]
        self.assertGreater(price, S.buy_price("whl_tuned_light"), "gold mesh costs extra")
        menu(p, G.OP_BUY, k, SLOTS.index("WheelFL"))
        w.step(DT)
        self.assertEqual((car.parts["WheelFL"].type_id, car.parts["WheelFL"].style), ("whl_tuned_light", 2))
        self.assertEqual(car.parts["WheelFL"].condition, 1.0)
        self.assertEqual(w.cash, 5000 - price)
        self.assertIn(old, w.stash, "the old wheel goes in the locker, not the bin")

    def test_no_credit(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        in_shop(w, p)
        w.cash = 10
        car = w.cars[w.personal_id]
        before = car.parts["Engine"]
        menu(p, G.OP_BUY, len(G.catalogue("Engine")) - 1, SLOTS.index("Engine"))
        w.step(DT)
        self.assertIs(car.parts["Engine"], before)
        self.assertEqual(w.cash, 10)

    def test_each_command_runs_once(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        in_shop(w, p)
        w.cash = 1000
        menu(p, G.OP_PAINT, 3)
        step(w, 0.5)                      # the same command, resent every tick, must not re-bill
        self.assertEqual(w.cash, 1000 - C.PRICE_PAINT)
        self.assertEqual(w.cars[w.personal_id].color, 3)

    def test_locker_install_remove_sell_take(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        p.hands = [Part("spl_wing", 1.0, 3)]
        in_shop(w, p)
        self.assertEqual(p.hands, [])
        car = w.cars[w.personal_id]
        self.assertIsNone(car.parts["Spoiler"])
        grip0 = car.grip
        menu(p, G.OP_INSTALL, 0, SLOTS.index("Spoiler"))
        w.step(DT)
        self.assertEqual(car.parts["Spoiler"].type_id, "spl_wing")
        self.assertGreater(car.grip, grip0, "a wing buys grip")
        menu(p, G.OP_REMOVE, SLOTS.index("Spoiler"))
        w.step(DT)
        self.assertIsNone(car.parts["Spoiler"])
        self.assertEqual(len(w.stash), 1)
        # can't bolt a wing on as an engine
        menu(p, G.OP_INSTALL, 0, SLOTS.index("Engine"))
        w.step(DT)
        self.assertEqual(car.parts["Engine"].category, "engine")
        # sell it from the locker
        cash0, value = w.cash, w.stash[0].value
        menu(p, G.OP_SELL, 0, PART_INDEX["spl_wing"])
        w.step(DT)
        self.assertEqual(w.cash, cash0 + value)
        self.assertEqual(w.stash, [])
        # take one out: menu closes, part in hand
        w.stash.append(Part("ecu_tuned"))
        menu(p, G.OP_TAKE, 0, PART_INDEX["ecu_tuned"])
        w.step(DT)
        self.assertEqual([q.type_id for q in p.hands], ["ecu_tuned"])
        self.assertFalse(p.menu)

    def test_paint_livery_horn_glow_extras(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        in_shop(w, p)
        w.cash = 10000
        car = w.cars[w.personal_id]
        for op, a, b in ((G.OP_LIVERY, V.LIV_FLAMES, 5), (G.OP_HORN, V.HORN_GOAT, 0), (G.OP_GLOW, 3, 0),
                         (G.OP_EXTRA, G.EXTRA_NOS, 0), (G.OP_EXTRA, G.EXTRA_EJECTOR, 0)):
            menu(p, op, a, b)
            w.step(DT)
        self.assertEqual(V.livery_parts(car.livery), (V.LIV_FLAMES, 5))
        self.assertEqual(car.horn_type, V.HORN_GOAT)
        self.assertEqual(car.glow, 3)
        self.assertTrue(car.nos and car.ejector)
        self.assertAlmostEqual(car.nos_fuel, C.NOS_TANK)
        # a gnome from the locker is fitted for free
        w.stash.append(Part("gnome"))
        cash0 = w.cash
        menu(p, G.OP_EXTRA, G.EXTRA_GNOME)
        w.step(DT)
        self.assertTrue(car.gnome)
        self.assertEqual(w.cash, cash0)
        self.assertEqual(w.stash, [])

    def test_menu_goes_over_the_wire(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        w.stash += [Part("whl_tuned_light", 0.5, 2), Part("gnome")]
        in_shop(w, p)
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertIsNotNone(snap.menu)
        self.assertEqual([t for t, _, _ in snap.menu["stash"]], ["whl_tuned_light", "gnome"])
        self.assertEqual(snap.menu["stash"][0][1], 2)
        self.assertEqual(snap.menu["slots"]["Engine"][0], w.cars[w.personal_id].parts["Engine"].type_id)
        menu(p, G.OP_CLOSE)
        w.step(DT)
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertIsNone(snap.menu)

    def test_markup_means_stealing_is_still_cheaper(self):
        for slot in ("Engine", "WheelFL", "ECU", "Spoiler"):
            for tid, style, price in G.catalogue(slot):
                self.assertGreater(price, Part(tid, 1.0, style).value, "buy-then-sell must lose money")


class TestTrunks(unittest.TestCase):
    def _behind(self, w, p, car):
        x, y = car.to_world(-car.hl - 1.2, 0.0)
        p.x, p.y = x, y
        face(p, car.x, car.y)

    def test_put_it_in_and_take_it_out(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        gx, gy, gw, gh = w.map.garage_rect
        car.x, car.y, car.ang = gx + gw / 2, gy + gh / 2, 0.0
        wheel = Part("whl_stock_alloy")
        p.hands = [wheel]
        self._behind(w, p, car)
        key, label, _, action = w._find_interaction(p)
        self.assertIn("IN THE TRUNK", label)
        action()
        self.assertEqual(car.trunk, [wheel])
        self.assertEqual(p.hands, [])
        key, label, _, action = w._find_interaction(p)
        self.assertIn("FROM THE TRUNK", label)
        action()
        self.assertEqual(p.hands, [wheel])

    def test_a_kei_trunk_fills_up(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        car.trunk = [Part("door_stock"), Part("whl_worn_steel")]      # 3 of 3
        p.hands = [Part("ecu_stock")]
        self._behind(w, p, car)
        key, label, _, _ = w._find_interaction(p)
        self.assertIsNone(key)
        self.assertIn("TRUNK FULL", label)

    def test_stolen_cars_can_have_loot(self):
        rng = random.Random(3)
        found = [x for x in (roll_trunk(rng) for _ in range(200)) if x]
        self.assertTrue(found, "a fair few trunks have something in them")
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = S.Car(w.new_id(), S.CIV, 0, 0, 0.0, model_loadout(rng, V.SEDAN), model=V.SEDAN)
        car.x, car.y = p.x + 10, p.y
        car.trunk = [Part("cash_bag")]
        w.cars[car.id] = car
        self._behind(w, p, car)
        key, label, _, _ = w._find_interaction(p)
        self.assertNotIn("TRUNK", label, "locked car: break in first")
        car.state = S.BROKEN_IN
        key, label, _, action = w._find_interaction(p)
        self.assertIn("BAG OF CASH", label)
        action()
        self.assertEqual(p.hands[0].type_id, "cash_bag")

    def test_engines_ride_in_a_pickup_bed(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        truck = S.Car(w.new_id(), S.CIV, 0, 0, 0.0, model_loadout(random.Random(1), V.PICKUP), model=V.PICKUP)
        truck.state = S.RUNNING
        gx, gy, gw, gh = w.map.garage_rect
        truck.x, truck.y = gx + gw / 2, gy + gh / 2
        w.cars[truck.id] = truck
        d = next(iter(w.dollies.values()))
        d.holder, p.dolly, d.part = p.id, d, Part("eng_tuned_2_0t")
        bx, by = truck.to_world(-truck.hl - 1.6, 0.0)
        p.x, p.y = bx, by
        face(p, truck.x, truck.y)
        w._update_dollies(DT)
        key, label, hold, action = w._find_interaction(p)
        self.assertIn("INTO THE BED", label)
        action()
        self.assertEqual(truck.trunk[0].type_id, "eng_tuned_2_0t")
        self.assertIsNone(d.part)

    def test_the_trunk_spills_when_the_shell_is_crushed(self):
        w = quiet_world()
        car = S.Car(w.new_id(), S.CIV, 200, 200, 0.0, {s: None for s in SLOTS})
        car.trunk = [Part("briefcase"), Part("gnome")]
        w.cars[car.id] = car
        n0 = len(w.pickups)
        w._crush(car, 10)
        self.assertEqual(len(w.pickups), n0 + 2)

    def test_trunk_rides_in_the_self_block(self):
        w = quiet_world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        car.trunk = [Part("gnome"), Part("whl_tuned_light", 1.0, 4)]
        w._enter_car(p, car, S.DRIVER)
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        cid, cap, used, items = snap.trunk
        self.assertEqual((cid, cap, used), (car.id, V.model(car.model).trunk, 2))
        self.assertEqual(items, [("gnome", 0), ("whl_tuned_light", 4)])


class TestModels(unittest.TestCase):
    def test_every_model_spawns_with_its_own_box(self):
        rng = random.Random(7)
        for mid, m in enumerate(V.MODELS):
            car = S.Car(1, S.CIV, 0, 0, 0.0, model_loadout(rng, mid), model=mid)
            self.assertAlmostEqual(car.hl * 2, m.length)
            self.assertAlmostEqual(car.hw * 2, m.width)
            fx, fy = car.anchor("WheelFR")
            self.assertLess(abs(fx), car.hl)
            self.assertLess(abs(fy), car.hw + 0.2)

    def test_the_kei_is_still_the_old_box(self):
        car = S.Car(1, S.CIV, 0, 0, 0.0, S.personal_loadout())
        self.assertAlmostEqual(car.hl, S.HL)
        self.assertAlmostEqual(car.hw, S.HW)

    def test_styles_pack_and_unpack(self):
        rng = random.Random(11)
        for _ in range(40):
            parts = model_loadout(rng, rng.randrange(len(V.MODELS)))
            word = V.pack_styles(parts)
            out = V.unpack_styles(word)
            for slot in ("WheelFL", "WheelRR", "Hood", "DoorL"):
                if parts.get(slot) is not None:
                    self.assertEqual(out[slot], parts[slot].style % (8 if slot != "DoorL" else 4))

    def test_the_city_has_variety(self):
        w = S.World(map_seed=99, rng_seed=5)
        models = {c.model for c in w.cars.values() if c.kind in (S.CIV, S.TRAFFIC)}
        self.assertGreaterEqual(len(models), 3, "more than one kind of car out there")


if __name__ == "__main__":
    unittest.main()

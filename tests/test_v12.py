"""v0.12: five more guns (SMG/AR/sniper/grenade launcher/RPG), purchasable fence shops with
tiered black markets, flat per-shop rent, and the bigger minimap. See CLAUDE.md for the
full decision log; the rent and shop tests live in test_sim.py's TestDays instead, since
that's where the existing economy tests already were."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import savefile as SF

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
    return gx + gw / 2 + 30, gy + gh + 10.0


def ped(w, x, y):
    n = S.NPC(w.new_id(), S.PED, x, y)
    n.dirx = n.diry = 0
    n.turn_t = 1e9
    n.wallet = 50
    w.npcs[n.id] = n
    return n


def arm(p, slot, ammo=None):
    p.arms |= 1 << slot
    p.ammo[slot] = C.MAX_AMMO if ammo is None else ammo


class TestNewGuns(unittest.TestCase):
    def test_every_new_gun_is_hitscan_and_burns_one_round(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        for slot in (S.ARM_SMG, S.ARM_AR, S.ARM_SNIPER):
            n = ped(w, x + 3.0, y)
            arm(p, slot, 5)
            p.fire_cd = 0.0     # each gun has its own cooldown; don't let the last one's linger
            face(p, n.x, n.y)
            wield(p, slot)
            click(p)
            w.step(DT)
            self.assertEqual(p.ammo[slot], 4, "one shot, one round gone (%s)" % S.ARM_NAMES[slot])
            self.assertNotIn(n.id, w.npcs, "a direct hit on a pedestrian is lethal now (v0.10 rule)")
            press(p, 0)

    def test_out_of_ammo_clicks_empty_and_doesnt_fire(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        arm(p, S.ARM_AR, 0)
        n = ped(w, p.x + 3.0, p.y)
        face(p, n.x, n.y)
        wield(p, S.ARM_AR)
        click(p)
        w.step(DT)
        self.assertIn(n.id, w.npcs, "no ammo, no bullet")
        self.assertTrue(any(e[2] == 0 and "OUT OF AMMO" in e[3][1] for e in w.events))

    def test_grenade_launcher_splash_gets_everyone_in_the_radius(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        arm(p, S.ARM_GRENADE, 4)
        # two peds close together, well within GRENADE_SPLASH of each other and of the impact
        n1 = ped(w, x + 8.0, y)
        n2 = ped(w, x + 8.0 + C.GRENADE_SPLASH * 0.5, y)
        face(p, n1.x, n1.y)
        wield(p, S.ARM_GRENADE)
        click(p)
        w.step(DT)
        self.assertNotIn(n1.id, w.npcs, "direct hit")
        self.assertNotIn(n2.id, w.npcs, "close enough to catch the blast too")
        self.assertEqual(p.ammo[S.ARM_GRENADE], 3)

    def test_rpg_ignites_a_cop_car_caught_in_the_blast(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        arm(p, S.ARM_RPG, 2)
        cop = S.Car(w.new_id(), S.COP, x + 12.0, y, 0.0, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        face(p, cop.x, cop.y)
        wield(p, S.ARM_RPG)
        click(p)
        w.step(DT)
        self.assertGreater(cop.fire_t, 0, "the blast should have set it alight")

    def test_market_sells_every_new_gun_and_ammo_tops_all_of_them_up(self):
        w = world()
        p = w.add_player("BRYCE")
        w.cash = 100000
        for slot, item, price in ((S.ARM_SMG, "smg", C.PRICE_SMG), (S.ARM_AR, "ar", C.PRICE_AR),
                                  (S.ARM_SNIPER, "sniper", C.PRICE_SNIPER),
                                  (S.ARM_GRENADE, "grenade", C.PRICE_GRENADE),
                                  (S.ARM_RPG, "rpg", C.PRICE_RPG)):
            cash0 = w.cash
            w._market_buy(p, item, price)
            self.assertTrue(p.owns(slot), item)
            self.assertGreater(p.ammo[slot], 0, item)
            self.assertEqual(w.cash, cash0 - price)
        new_guns = (S.ARM_SMG, S.ARM_AR, S.ARM_SNIPER, S.ARM_GRENADE, S.ARM_RPG)
        for slot in new_guns:
            p.ammo[slot] = 1
        w._market_buy(p, "ammo", C.PRICE_AMMO)
        for slot in new_guns:
            self.assertGreater(p.ammo[slot], 1, "one crate tops up every gun you own now")

    def test_arsenal_wire_carries_the_high_bitmask_bit_and_new_ammo(self):
        w = world()
        p = w.add_player("BRYCE")
        p.arms |= 1 << S.ARM_RPG
        p.ammo[S.ARM_RPG] = 2
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertEqual(len(snap.arsenal), S.ARSENAL_LEN)
        self.assertTrue(S.arsenal_owns(snap.arsenal, S.ARM_RPG), "bit 13 lives in the high byte now")
        self.assertEqual(snap.arsenal[S.AMMO_BYTE_OF_ARM[S.ARM_RPG]], 2)

    def test_arrest_confiscates_every_gun_not_just_the_first_three(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        for slot in S.GUN_SLOTS:
            arm(p, slot)
        w.arrest(p)
        self.assertEqual(p.arms, 1 << S.ARM_FISTS)
        self.assertEqual(p.ammo, [0] * S.ARM_COUNT)


class TestFenceShops(unittest.TestCase):
    def test_buying_a_fence_shop_through_the_normal_interaction_flow(self):
        w = world()
        p = w.add_player("BRYCE")
        w.cash = 1_000_000
        fs = w.map.fence_shops[0]
        sx, sy = fs["sign"]
        p.x, p.y = sx - 1.0, sy
        face(p, sx, sy)
        w.step(DT)
        self.assertIn("BUY SHOP", p.prompt)
        press(p, S.B_USE)
        step(w, C.BUY_TIME + 0.1)
        self.assertTrue(w.shop_owned[1])
        press(p, 0)

    def test_savefile_round_trips_which_shops_you_own(self):
        w = world()
        w.cash = 1_000_000
        w._buy_shop(2)
        data = SF.dump(w)
        w2 = world()
        SF.apply(w2, data)
        self.assertEqual(w2.shop_owned, w.shop_owned)


def toasts(w):
    return [e[3][1] for e in w.events if e[2] == 0]


class TestSillyRoundFour(unittest.TestCase):
    """v0.12's 10 more silly features."""

    def test_scratch_ticket_nothing_and_jackpot(self):
        w = world()
        p = w.add_player("BRYCE")
        w.cash = 1000
        w.rng.random = lambda: 0.0        # first bucket in TICKET_ODDS: nothing
        cash0 = w.cash
        w._market_buy(p, "ticket", C.PRICE_TICKET)
        self.assertEqual(w.cash, cash0 - C.PRICE_TICKET)
        self.assertTrue(any("NOTHING" in t for t in toasts(w)))
        w.events.clear()
        w.rng.random = lambda: 0.999       # last bucket: jackpot
        cash1 = w.cash
        w._market_buy(p, "ticket", C.PRICE_TICKET)
        self.assertEqual(w.cash, cash1 - C.PRICE_TICKET + 500)
        self.assertTrue(any("JACKPOT" in t for t in toasts(w)))

    def test_jackpot_ped_wallet_and_special_toast(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        w.rng.random = lambda: 0.0         # forces the jackpot branch in _roll_wallet
        n = w._spawn_ped()
        self.assertGreaterEqual(n.wallet, C.JACKPOT_WALLET[0])
        cash0 = w.cash
        w._rob(p, n)
        self.assertGreaterEqual(w.cash - cash0, C.JACKPOT_WALLET[0])
        self.assertTrue(any("JACKPOT" in t for t in toasts(w)))

    def test_high_five_between_dancing_crewmates(self):
        w = world()
        a, b = w.add_player("A"), w.add_player("B")
        x, y = street(w)
        a.x, a.y = x, y
        b.x, b.y = x + 1.0, y
        a.stamina = b.stamina = 50.0
        press(a, S.B_TAUNT)
        press(b, S.B_TAUNT)
        step(w, 0.1)
        self.assertGreater(a.stamina, 50.0)
        self.assertGreater(b.stamina, 50.0)
        self.assertTrue(any("SYNCED UP" in t for t in toasts(w)))

    def test_speedcam_fame_milestone_toast(self):
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        x, y = street(w)
        car.x, car.y, car.ang = x, y, 0.0
        w._enter_car(p, car, S.DRIVER)
        w.map.cameras = [(x + 5.0, y)]
        car.vx = C.SPEEDCAM_SPEED + 5.0
        p.rap["speed"] = C.SPEEDCAM_FAME_COUNT - 1
        step(w, 0.5)
        self.assertTrue(any("FAMOUS" in t for t in toasts(w)))

    def test_tip_jar_sometimes_pays_extra_on_a_sale(self):
        from chopped.parts import Part
        w = world()
        p = w.add_player("BRYCE")
        p.hands = [Part("whl_stock_alloy", 1.0)]
        w.rng.random = lambda: 0.0        # forces the tip jar
        cash0 = w.cash
        w._sell(p)
        self.assertGreater(w.cash, cash0 + 1)
        self.assertTrue(any("TIP" in t for t in toasts(w)))

    def test_hotwiring_sometimes_finds_change_in_the_seats(self):
        w = world()
        p = w.add_player("BRYCE")
        x, y = street(w)
        p.x, p.y = x, y
        car = S.Car(w.new_id(), S.CIV, x, y, 0.0, S.kei_loadout(w.rng))
        car.state = S.BROKEN_IN
        w.cars[car.id] = car
        w.rng.random = lambda: 0.0        # forces the seat-change chance
        cash0 = w.cash
        w._hotwire(p, car)
        self.assertGreaterEqual(w.cash - cash0, C.SEAT_CHANGE_MIN)
        self.assertTrue(any("FOUND IN THE SEATS" in t for t in toasts(w)))

    def test_honking_near_the_icecream_van_honks_back(self):
        from chopped import vehicles as V
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = street(w)[0], street(w)[1], 0.0
        w._enter_car(p, car, S.DRIVER)
        van = S.Car(w.new_id(), S.TRAFFIC, car.x + 10.0, car.y, 0.0, S.model_loadout(w.rng, V.ICECREAM), model=V.ICECREAM)
        w.cars[van.id] = van
        press(p, S.B_HORN)
        w.step(DT)
        self.assertTrue(any("ICE CREAM VAN HONKS BACK" in t for t in toasts(w)))

    def test_nos_backfire_confetti_puff_fires_once_per_activation(self):
        w = world()
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = street(w)[0], street(w)[1], 0.0
        p = w.add_player("BRYCE")
        w._enter_car(p, car, S.DRIVER)
        car.nos, car.nos_fuel = True, C.NOS_TANK
        press(p, S.B_SPRINT)
        w.step(DT)
        self.assertTrue(any(e[2] == 1 and e[3][0] == S.S_CONFETTI for e in w.events), "puff on activation")
        w.events.clear()
        w.step(DT)
        self.assertFalse(any(e[2] == 1 and e[3][0] == S.S_CONFETTI for e in w.events),
                         "only on the rising edge, not every tick")


if __name__ == "__main__":
    unittest.main()

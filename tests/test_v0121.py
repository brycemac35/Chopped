"""v0.12.1 fixes: a switched car that actually starts, a jail that isn't a
revolving door, talking NPCs, the fence lots in price order, the walking
door's brick jambs, the shops-owned bitmask, save slots and the mod shop's
close handshake."""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import savefile as SF
from chopped import vehicles as V
from chopped import garage as G
from chopped.parts import SLOTS


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


def says(w):
    return [e[3][1] for e in w.events if e[2] == 0 and e[3][0] == S.T_SAY]


class TestSwitchedCarStarts(unittest.TestCase):
    def test_switched_car_is_running_not_delivered(self):
        """Bryce: "after swapping a car i cant start the new one". A delivered car never
        drives; the one you swap into has to stop being 'delivered'."""
        w = quiet_world()
        p = w.add_player("ALICE")
        gx, gy, gw, gh = w.map.garage_rect
        stolen = S.Car(w.new_id(), S.CIV, gx + gw / 2, gy + gh / 2, 0.0, {s: None for s in SLOTS}, model=V.MUSCLE)
        stolen.state = S.DELIVERED
        stolen.stolen = True
        w.cars[stolen.id] = stolen
        old = w.cars[w.player_car[p.id]]
        was_at = (stolen.x, stolen.y)
        w._ms_switch(p, old, stolen.id)
        car = w.cars[w.player_car[p.id]]
        # they trade places: the old one used to stay put and get the new one dropped on
        # top of it, and then its strip prompt blocked the new car's door
        self.assertEqual((old.x, old.y), was_at)
        self.assertEqual((car.x, car.y), tuple(w.map.bays[car.bay][:2]))
        self.assertIs(car, stolen)
        self.assertEqual(car.state, S.RUNNING)
        self.assertEqual(car.kind, S.PERSONAL)
        self.assertFalse(car.stolen)


class TestJail(unittest.TestCase):
    def _jailed(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.heat = 100.0
        w.dispatched = True
        w.lethal_t = 20.0
        w.arrest(p)
        for _ in range(int(60 * (C.CUFFED_TIME + 0.5))):
            w.step(1 / 60)
        return w, p

    def test_heat_clears_in_a_cell(self):
        w, p = self._jailed()
        self.assertTrue(p.jailed)
        self.assertEqual(w.heat, 0.0)
        self.assertFalse(w.dispatched)
        self.assertEqual(w.lethal_t, 0.0)

    def test_escapee_gets_a_head_start(self):
        """Bryce: "im spawn locked in jail". Just out of the door, the law can look but not touch."""
        w, p = self._jailed()
        x0, y0, x1, y1 = w.map.precinct_outer
        p.x, p.y = x1 + 3, (y0 + y1) / 2
        w.step(1 / 60)
        self.assertFalse(p.jailed)
        self.assertTrue(p.jumpsuit)
        self.assertGreater(p.head_start_t, 0)
        self.assertNotIn(p, w._law_targets())
        for _ in range(int(60 * (C.JAILBREAK_HEAD_START + 0.5))):
            w.step(1 / 60)
        self.assertLessEqual(p.head_start_t, 0)


class TestShopSeized(unittest.TestCase):
    def test_whoopee_cushion_after_a_seizure_doesnt_crash_the_host(self):
        """Soak test: reset_run gave everyone 4 gear slots, not 5, so selecting the
        cushion (gear slot 4) afterwards was an IndexError on the server."""
        w = quiet_world()
        p = w.add_player("ALICE")
        w.reset_run()
        self.assertEqual(len(p.gear), len(S.GEAR_OF_ARM))
        w.set_input(p.id, S.InputState(0, 0, 0, 0, 0.0, 0, S.ARM_WHOOPEE))
        w.step(1 / 60)
        self.assertEqual(p.weapon, S.ARM_FISTS)          # (not owned: fists, not a crash)


class TestDispatch(unittest.TestCase):
    def test_cops_that_never_saw_you_still_come_looking(self):
        """Playtest: 55 heat, four cop cars, and they all sat idling round the corner
        because none of them had ever had line of sight -- nothing to drive to."""
        w = quiet_world()
        p = w.add_player("ALICE")
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw / 2, gy + gh + 30
        w.heat = 55.0
        w.targets = w._collect_targets()
        cop = w.spawn_cop()
        self.assertIsNotNone(cop)
        self.assertIsNotNone(cop.last_target)              # dispatch told it where to go
        tx, ty = cop.last_target
        self.assertLess(math.hypot(tx - p.x, ty - p.y), C.COP_TIP_SCATTER * 1.5)
        cop.last_target = None                             # lost the lead...
        cop.search_t = C.COP_TRACK_LOSE_TIME + C.COP_TIP_DELAY
        w._cop_ai(cop, 1 / 60)
        self.assertIsNotNone(cop.last_target)              # ...and got radioed a new one


class TestTalkingNPCs(unittest.TestCase):
    def test_paige_offers_a_prompt_and_reads_out_the_jobs(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        paige = next(n for n in w.map.story_npcs if n[0] == "paige")
        it = w._talk_interaction(p, paige[2], paige[3] + 0.5)
        self.assertIsNotNone(it)
        self.assertIn("PAIGE", it[1])
        it[3]()
        lines = says(w)
        self.assertTrue(lines)
        self.assertTrue(all(l.startswith("PAIGE: ") or l.startswith(" ") for l in lines))
        n = len(lines)
        it[3]()                                   # (spamming E doesn't re-read the list)
        self.assertEqual(len(says(w)), n)

    def test_nobody_to_talk_to_in_the_street(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        self.assertIsNone(w._talk_interaction(p, -500.0, -500.0))

    def test_fence_lots_are_in_price_order(self):
        """The Fixer points you at 'the next lot', so the list has to be cheapest-first."""
        for seed in (4242, 777, 12345):
            w = quiet_world(seed)
            tiers = [fs["tier"] for fs in w.map.fence_shops]
            self.assertEqual(tiers, sorted(tiers))


class TestWalkingDoor(unittest.TestCase):
    def test_jambs_block_sight_even_with_the_door_open(self):
        w = quiet_world()
        d = next(t for t in w.fixtures() if t.kind == S.TRAP_DOOR and t.id == C.DOOR_ID)
        d.open_t = 1.0
        d.goal = 1.0
        w._rebuild_trap_rects()
        # straight through the doorway: clear. Through the brick beside it: not.
        self.assertTrue(w.los(d.x, d.y - 3, d.x, d.y + 3))
        off = C.WALK_DOOR_W / 2 + 0.25
        self.assertFalse(w.los(d.x + off, d.y - 3, d.x + off, d.y + 3))


class TestWire(unittest.TestCase):
    def test_owned_shops_ride_the_header(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.shop_owned[1] = True
        s = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertTrue(s.shops & 1)
        self.assertTrue(s.shops & 2)
        self.assertFalse(s.shops & 4)


class TestSaveSlots(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = os.environ.get("CHOPPED_SAVE_DIR")
        os.environ["CHOPPED_SAVE_DIR"] = self.dir

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CHOPPED_SAVE_DIR", None)
        else:
            os.environ["CHOPPED_SAVE_DIR"] = self.old

    def test_slot_round_trip_keeps_the_city(self):
        w = quiet_world(seed=31337)
        w.add_player("ALICE")
        w.cash = 4321
        path = SF.slot_path(2)
        self.assertTrue(path.startswith(self.dir))
        self.assertIsNone(SF.peek(path))
        self.assertTrue(SF.save_to(w, path))
        self.assertFalse(os.path.exists(path + ".tmp"))
        info = SF.peek(path)
        self.assertEqual(info["cash"], 4321)
        self.assertEqual(info["map_seed"], 31337)
        self.assertEqual(info["crew"], ["ALICE"])
        self.assertTrue(SF.wipe(path))
        self.assertIsNone(SF.peek(path))

    def test_headless_server_reloads_the_saved_city(self):
        from chopped.net import Server
        w = quiet_world(seed=2468)
        path = SF.slot_path(1)
        SF.save_to(w, path)
        srv = Server(port=0, bind_host="127.0.0.1", save_path=path)
        try:
            self.assertEqual(srv.world.map_seed, 2468)
        finally:
            srv.sock.close()


class TestModShopClose(unittest.TestCase):
    def test_a_stale_snapshot_doesnt_reopen_a_closed_menu(self):
        from chopped import modshop as MS
        shop = MS.ModShop(None)
        menu = {"ack": 0}
        shop.sync(menu)
        self.assertTrue(shop.open)
        shop.close()
        seq, op, a, b = shop.next_command()
        self.assertEqual(op, G.OP_CLOSE)
        shop.sync(menu)                           # the host hasn't read the close yet
        self.assertFalse(shop.open)
        self.assertEqual(shop.next_command()[1], G.OP_CLOSE)
        shop.sync(None)                           # now it has
        shop.sync({"ack": seq})                   # ...and a later visit opens normally
        self.assertTrue(shop.open)


if __name__ == "__main__":
    unittest.main()

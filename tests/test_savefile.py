"""Save files: cash, the day, the shared locker and each player's own car
persist across a save/reload; heat, cops, traffic and positions never do."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import savefile as SF
from chopped import vehicles as V
from chopped.parts import Part, SLOTS


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


class TestSaveRoundTrip(unittest.TestCase):
    def test_economy_survives_a_dump_and_apply(self):
        w = quiet_world()
        w.cash = 1234
        w.day = 5
        w.day_t = 42.0
        w.run = 3
        w.stash = [Part("whl_worn_steel", 0.4, 0), Part("ecu_tuned", 1.0, 2)]
        data = SF.dump(w)

        w2 = quiet_world(seed=9999)
        self.assertTrue(SF.apply(w2, data))
        self.assertEqual(w2.cash, 1234)
        self.assertEqual(w2.day, 5)
        self.assertAlmostEqual(w2.day_t, 42.0)
        self.assertEqual(w2.run, 3)
        self.assertEqual([p.type_id for p in w2.stash], ["whl_worn_steel", "ecu_tuned"])
        self.assertEqual(w2.stash[0].condition, 0.4)
        self.assertEqual(w2.stash[1].style, 2)

    def test_a_players_car_mods_are_claimed_by_name_on_rejoin(self):
        w = quiet_world()
        alice = w.add_player("ALICE")
        car = w.cars[w.player_car[alice.id]]
        car.model = V.RICE
        car.refresh()
        car.color = 9
        car.parts["Engine"] = Part("eng_tuned_2_0t", 0.8, 1)
        car.livery = 3
        car.glow = 5
        car.nos = True
        data = SF.dump(w)
        self.assertIn("ALICE", data["cars"])

        w2 = quiet_world(seed=555)
        self.assertTrue(SF.apply(w2, data))
        bob = w2.add_player("BOB")               # a stranger: gets an ordinary fresh car
        new_car = w2.cars[w2.player_car[bob.id]]
        self.assertEqual(new_car.model, V.KEI)
        alice2 = w2.add_player("ALICE")           # the returning name: gets her car back
        alice_car = w2.cars[w2.player_car[alice2.id]]
        self.assertEqual(alice_car.model, V.RICE)
        self.assertEqual(alice_car.color, 9)
        self.assertEqual(alice_car.parts["Engine"].type_id, "eng_tuned_2_0t")
        self.assertEqual(alice_car.parts["Engine"].condition, 0.8)
        self.assertEqual(alice_car.livery, 3)
        self.assertEqual(alice_car.glow, 5)
        self.assertTrue(alice_car.nos)

    def test_switching_your_primary_car_is_what_gets_saved(self):
        """Save->load only cares about whatever's currently sitting in the bay --
        it doesn't need to know a switch (garage.OP_SWITCH) ever happened."""
        w = quiet_world()
        alice = w.add_player("ALICE")
        bay = w.cars[w.player_car[alice.id]].bay
        gx, gy, gw, gh = w.map.garage_rect
        stolen = S.Car(w.new_id(), S.CIV, gx + gw / 2, gy + gh / 2, 0.0, {s: None for s in SLOTS}, model=V.MUSCLE)
        stolen.state = S.DELIVERED
        w.cars[stolen.id] = stolen
        w._ms_switch(alice, w.cars[w.player_car[alice.id]], stolen.id)
        self.assertEqual(w.cars[w.player_car[alice.id]].model, V.MUSCLE)
        data = SF.dump(w)
        self.assertEqual(data["cars"]["ALICE"]["model"], V.MUSCLE)

        w2 = quiet_world(seed=777)
        SF.apply(w2, data)
        alice2 = w2.add_player("ALICE")
        self.assertEqual(w2.cars[w2.player_car[alice2.id]].model, V.MUSCLE)
        self.assertEqual(w2.cars[w2.player_car[alice2.id]].bay, bay)

    def test_heat_cops_and_positions_are_never_saved(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        p.x, p.y = 123.0, 456.0
        w.heat = 80.0
        data = SF.dump(w)
        self.assertNotIn("heat", data)
        self.assertNotIn("players", data)
        w2 = quiet_world(seed=222)
        SF.apply(w2, data)
        self.assertEqual(w2.heat, 0.0, "loading a save should never start you mid-chase")

    def test_a_missing_or_corrupt_file_is_a_quiet_no_op(self):
        w = quiet_world()
        cash0 = w.cash
        self.assertFalse(SF.load_into(w, "/tmp/this-file-should-not-exist-chopped.json"))
        self.assertEqual(w.cash, cash0)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            path = f.name
        try:
            self.assertFalse(SF.load_into(w, path))
            self.assertEqual(w.cash, cash0)
        finally:
            os.unlink(path)

    def test_a_foreign_save_version_is_ignored(self):
        w = quiet_world()
        cash0 = w.cash
        self.assertFalse(SF.apply(w, {"save_version": 999, "cash": 999999}))
        self.assertEqual(w.cash, cash0)

    def test_save_to_and_load_into_round_trip_through_a_real_file(self):
        w = quiet_world()
        w.add_player("ALICE")
        w.cash = 555
        w.day = 2
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "save.json")
            self.assertTrue(SF.save_to(w, path))
            self.assertTrue(os.path.exists(path))
            w2 = quiet_world(seed=333)
            self.assertTrue(SF.load_into(w2, path))
            self.assertEqual(w2.cash, 555)
            self.assertEqual(w2.day, 2)
            alice2 = w2.add_player("ALICE")
            self.assertEqual(w2.cars[w2.player_car[alice2.id]].model, V.KEI)


class TestServerSaveOnStop(unittest.TestCase):
    """The --save wiring in net.Server: loads on start, writes on a clean stop."""

    def test_a_hosted_server_saves_on_stop_and_loads_on_restart(self):
        from chopped.net import Server
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "save.json")
            srv = Server(port=0, bind_host="127.0.0.1", map_seed=31337, save_path=path)
            p = srv.world.add_player("ALICE")
            srv.world.cash = 4200
            srv.world.cars[srv.world.player_car[p.id]].color = 7
            srv.stop()             # never started -- stop() should still save unconditionally
            self.assertTrue(os.path.exists(path))

            srv2 = Server(port=0, bind_host="127.0.0.1", map_seed=31337, save_path=path)
            self.assertEqual(srv2.world.cash, 4200)
            alice2 = srv2.world.add_player("ALICE")
            self.assertEqual(srv2.world.cars[srv2.world.player_car[alice2.id]].color, 7)
            srv2.stop()


if __name__ == "__main__":
    unittest.main()

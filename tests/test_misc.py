"""Odds and ends: graceful UPnP degradation, address parsing, protocol limits."""

import os
import sys
import time
import random
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped.parts import model_loadout
from chopped import protocol as P
from chopped.parts import Part, PART_IDS
from chopped.upnp import UPnP


class TestMisc(unittest.TestCase):
    def test_upnp_without_miniupnpc_degrades(self):
        saved = sys.modules.get("miniupnpc", "absent")
        sys.modules["miniupnpc"] = None           # makes `import miniupnpc` raise ImportError
        try:
            u = UPnP(27015).start()
            for _ in range(100):
                if u.done:
                    break
                time.sleep(0.02)
            self.assertTrue(u.done)
            self.assertFalse(u.ok)
            self.assertIn("FORWARD UDP 27015 OR PLAY ON LAN", u.status)
            u.close()
        finally:
            if saved == "absent":
                del sys.modules["miniupnpc"]
            else:
                sys.modules["miniupnpc"] = saved

    def test_parse_addr(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from chopped.game import parse_addr
        self.assertEqual(parse_addr("10.0.0.5"), ("10.0.0.5", C.DEFAULT_PORT))
        self.assertEqual(parse_addr("10.0.0.5:4000"), ("10.0.0.5", 4000))
        self.assertEqual(parse_addr(""), ("127.0.0.1", C.DEFAULT_PORT))
        self.assertEqual(parse_addr("myhost:abc"), ("myhost", C.DEFAULT_PORT))

    def test_worst_case_snapshot_fits_and_roundtrips(self):
        w = S.World(map_seed=99, rng_seed=2)
        for i in range(4):
            w.add_player("PLAYERNAME%d" % i)
        rng = random.Random(3)
        gx, gy, gw, gh = w.map.garage_rect
        p = w.players[1]
        p.x, p.y = gx + 14, gy + 14
        p.prompt = "HOLD E: STRIP FRONT BUMPER - AERO BUMPER $999 AND SOME EXTRA WORDS"
        for i in range(16):
            mid = rng.randrange(len(V.MODELS))
            c = S.Car(w.new_id(), S.CIV, gx + rng.uniform(0, 28), gy + rng.uniform(0, 28), rng.uniform(-3, 3),
                      model_loadout(rng, mid), color=rng.randrange(16), model=mid)
            w._dress(c)
            c.livery = rng.randrange(256)
            c.vx = rng.uniform(-40, 40)
            w.cars[c.id] = c
        # v0.7: a full wanted level plus the patrols, all in sight
        for i in range(C.MAX_COPS + C.PATROL_COPS):
            c = S.Car(w.new_id(), S.COP, gx + rng.uniform(0, 28), gy + rng.uniform(0, 28), rng.uniform(-3, 3),
                      S.cop_loadout(rng))
            c.vx = rng.uniform(-40, 40)
            w.cars[c.id] = c
        # ...and the mod shop open with a full locker (the biggest SELF block there is)
        w.stash = [Part(rng.choice(PART_IDS), rng.random(), rng.randrange(8)) for _ in range(C.STASH_MAX)]
        p.menu = True
        for i in range(C.MAX_PICKUPS):
            w.add_pickup(Part(rng.choice(PART_IDS)), gx + rng.uniform(0, 28), gy + rng.uniform(0, 28))
        for i in range(20):
            n = S.NPC(w.new_id(), S.CLOWN, gx + rng.uniform(0, 28), gy + rng.uniform(0, 28))
            w.npcs[n.id] = n
        for i in range(30):
            w.toast("A VERY LONG TOAST MESSAGE NUMBER %d THAT GOES ON AND ON AND ON" % i)
        # rush hour: every traffic car within sight of this player
        for c in w.cars.values():
            if c.kind == S.TRAFFIC:
                c.x, c.y = gx + rng.uniform(0, 28), gy + rng.uniform(0, 28)
        pkt = P.encode_snapshot(w, 1, 12345, 0, 987654)
        self.assertLessEqual(len(pkt), C.MAX_PACKET)
        snap = P.decode_snapshot(pkt[P.HDR.size:])
        self.assertEqual(snap.pid, 1)
        self.assertEqual(snap.cash, w.cash)
        self.assertEqual(snap.ack_input, 987654)
        # (v0.13: every car here is in sight except the precinct's parked impound bikes, which are
        # culled like far-off traffic -- five rows nobody at the shop needs)
        in_sight = [c for c in w.cars.values() if c.special != "impound"]
        self.assertEqual(len(snap.cars), len(in_sight), "nearby cars are all sent")
        # far-off traffic is culled, stealable cars never are
        far = next(c for c in w.cars.values() if c.kind == S.TRAFFIC)
        far.x, far.y = 5.0, 5.0
        civ = next(c for c in w.cars.values() if c.kind == S.CIV)
        civ.x, civ.y = 440.0, 440.0
        snap = P.decode_snapshot(P.encode_snapshot(w, 1, 0, 0)[P.HDR.size:])
        self.assertNotIn(far.id, snap.cars)
        self.assertIn(civ.id, snap.cars)
        self.assertEqual(len(snap.players), 4)
        self.assertTrue(snap.prompt.startswith("HOLD E: STRIP"))
        self.assertIsNotNone(snap.menu)
        self.assertEqual(len(snap.menu["stash"]), C.STASH_MAX)
        p.menu = False             # (with the locker open, loose parts are what gets shed first)
        snap = P.decode_snapshot(P.encode_snapshot(w, 1, 0, 0)[P.HDR.size:])
        self.assertGreater(len(snap.pickups), 10)
        car = next(iter(w.cars.values()))
        row = snap.cars[car.id]
        self.assertAlmostEqual(row[7], car.x, delta=0.07)
        self.assertAlmostEqual(row[8], car.y, delta=0.07)

    def test_part_values(self):
        # value = base * lerp(0.15, 1, condition)
        self.assertEqual(Part("eng_tuned_2_0t", 1.0).value, 2200)
        self.assertEqual(Part("eng_tuned_2_0t", 0.0).value, 330)
        self.assertEqual(Part("whl_stock_alloy", 0.5).value, round(90 * 0.575))
        # a stock Kei at full condition has 100 power (8.7 m/s^2)
        car = S.Car(1, S.CIV, 0, 0, 0, {"Engine": Part("eng_stock_1_6"), "Transmission": Part("trn_stock_5mt"),
                                         "ECU": Part("ecu_stock"), "Exhaust": Part("exh_stock")})
        self.assertEqual(car.power(), 100)


if __name__ == "__main__":
    unittest.main()

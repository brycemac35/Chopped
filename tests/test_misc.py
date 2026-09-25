"""Odds and ends: graceful UPnP degradation, address parsing, protocol limits."""

import os
import sys
import time
import random
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
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
            c = S.Car(w.new_id(), S.CIV, gx + rng.uniform(0, 28), gy + rng.uniform(0, 28), rng.uniform(-3, 3),
                      S.kei_loadout(rng), color=3)
            c.vx = rng.uniform(-40, 40)
            w.cars[c.id] = c
        for i in range(C.MAX_PICKUPS):
            w.add_pickup(Part(rng.choice(PART_IDS)), gx + rng.uniform(0, 28), gy + rng.uniform(0, 28))
        for i in range(20):
            n = S.NPC(w.new_id(), S.CLOWN, gx + rng.uniform(0, 28), gy + rng.uniform(0, 28))
            w.npcs[n.id] = n
        for i in range(30):
            w.toast("A VERY LONG TOAST MESSAGE NUMBER %d THAT GOES ON AND ON AND ON" % i)
        pkt = P.encode_snapshot(w, 1, 12345, 0)
        self.assertLessEqual(len(pkt), C.MAX_PACKET)
        snap = P.decode_snapshot(pkt[P.HDR.size:])
        self.assertEqual(snap.pid, 1)
        self.assertEqual(snap.cash, w.cash)
        self.assertEqual(len(snap.cars), len(w.cars), "cars are never culled")
        self.assertEqual(len(snap.players), 4)
        self.assertTrue(snap.prompt.startswith("HOLD E: STRIP"))
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

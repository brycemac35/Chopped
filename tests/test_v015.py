"""v0.15: rent strikes. Miss a midnight and it's a strike (the rent carries over, your cash
is left alone); pay the whole pile and you're clear; two misses in a row and the landlord
changes the locks. Replaces the old hidden two-minute debt timer."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import savefile as SF

DT = 1.0 / C.SIM_HZ


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


def midnight(w):
    w.day_t = 0.001
    w.step(DT)


def toasts(w):
    return [e[3][1] for e in w.events if e[2] == 0 and e[3][0] == S.T_BAD]


class TestRentStrikes(unittest.TestCase):
    def test_paid_night_clears_strikes(self):
        w = quiet_world()
        w.strikes, w.back_rent = 1, C.SHOP_RENT[0]
        w.cash = 10000
        midnight(w)
        self.assertEqual(w.cash, 10000 - 2 * C.SHOP_RENT[0])
        self.assertEqual((w.strikes, w.back_rent), (0, 0))

    def test_missed_night_is_a_strike_and_cash_is_untouched(self):
        w = quiet_world()
        w.cash = C.SHOP_RENT[0] - 1
        cash0 = w.cash
        midnight(w)
        self.assertEqual(w.cash, cash0, "a missed night doesn't charge you")
        self.assertEqual(w.strikes, 1)
        self.assertEqual(w.back_rent, C.SHOP_RENT[0])
        self.assertEqual(w.rent_owed(), 2 * C.SHOP_RENT[0])
        self.assertEqual(w.gameover_t, 0.0)
        self.assertTrue(any("STRIKE 1 OF %d" % C.RENT_STRIKES_MAX in t and t.endswith("LOSE THE SHOP")
                            for t in toasts(w)), "the whole line survives the toast length cap")

    def test_paying_the_carried_bill_clears_it(self):
        w = quiet_world()
        w.cash = 0
        midnight(w)
        w.cash = w.rent_owed() + 5
        midnight(w)
        self.assertEqual(w.cash, 5)
        self.assertEqual((w.strikes, w.back_rent), (0, 0))
        self.assertEqual(w.gameover_t, 0.0)

    def test_paying_only_tonights_rent_is_not_enough(self):
        w = quiet_world()
        w.cash = 0
        midnight(w)
        w.cash = C.SHOP_RENT[0]
        midnight(w)
        self.assertEqual(w.cash, C.SHOP_RENT[0], "not charged")
        self.assertGreater(w.gameover_t, 0.0, "second strike")

    def test_two_misses_in_a_row_is_shop_seized(self):
        w = quiet_world()
        w.cash = 0
        for _ in range(C.RENT_STRIKES_MAX):
            self.assertEqual(w.gameover_t, 0.0)
            midnight(w)
        self.assertGreater(w.gameover_t, 0.0)
        self.assertTrue(any("SHOP SEIZED" in t for t in toasts(w)))
        w.gameover_t = DT / 2
        w.step(DT)
        self.assertEqual((w.run, w.strikes, w.back_rent, w.day), (2, 0, 0, 1))

    def test_cash_never_goes_negative(self):
        w = quiet_world()
        w.cash = -50                    # e.g. a robbery refund or a speed camera
        w.step(DT)
        self.assertEqual(w.cash, 0)

    def test_warning_once_a_day(self):
        w = quiet_world()
        w.cash = 20
        w.day_t = C.RENT_WARN_TIME - 1
        w.step(DT)
        w.step(DT)
        warns = [t for t in toasts(w) if "RENT DUE IN" in t]
        self.assertEqual(len(warns), 1)
        self.assertIn("$%d SHORT" % (C.SHOP_RENT[0] - 20), warns[0])
        midnight(w)
        self.assertFalse(w.rent_warned, "re-armed for the next day")

    def test_no_warning_when_you_can_pay(self):
        w = quiet_world()
        w.cash = 5000
        w.day_t = C.RENT_WARN_TIME - 1
        w.step(DT)
        self.assertFalse([t for t in toasts(w) if "RENT DUE" in t])

    def test_reset_run_clears(self):
        w = quiet_world()
        w.strikes, w.back_rent, w.rent_warned = 1, 300, True
        w.reset_run()
        self.assertEqual((w.strikes, w.back_rent, w.rent_warned), (0, 0, False))


class TestPersistence(unittest.TestCase):
    def test_save_round_trip(self):
        w = quiet_world()
        w.strikes, w.back_rent = 1, 250
        data = SF.dump(w)
        w2 = quiet_world()
        SF.apply(w2, data)
        self.assertEqual((w2.strikes, w2.back_rent), (1, 250))

    def test_old_save_defaults_to_zero(self):
        w = quiet_world()
        data = SF.dump(w)
        del data["strikes"], data["back_rent"]
        w2 = quiet_world()
        w2.strikes = w2.back_rent = 7
        SF.apply(w2, data)
        self.assertEqual((w2.strikes, w2.back_rent), (0, 0))

    def test_snapshot_carries_strikes_and_full_bill(self):
        w = quiet_world()
        p = w.add_player("BOB")
        w.strikes, w.back_rent = 1, 400
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertEqual((snap.strikes, snap.back_rent), (1, 400))
        self.assertEqual(snap.rent_due, C.SHOP_RENT[0] + 400)
        self.assertFalse(hasattr(snap, "debt"))
        self.assertAlmostEqual(snap.rent, w.day_t, delta=0.1)


if __name__ == "__main__":
    unittest.main()

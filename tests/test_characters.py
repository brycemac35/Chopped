"""v0.16: choosable characters, one perk each (characters.py). Perks are multipliers from config,
the char rides the JOIN packet, the snapshot's player rows and the SELF block (DASH's stamina pool
is bigger, so the predictor has to know)."""

import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import characters as CH
from chopped import business as B
from chopped.parts import Part
from chopped.net import Server, Client
from test_predict import quiet_world as predict_world, lockstep, worst_gap
from test_v014 import quiet_world, delivered, look, step, snap

DASH, SPANNER, SLIM, SMOOTH = range(4)


def near_locked_car(w, p):
    car = next(c for c in w.cars.values() if c.kind == S.CIV and c.state == S.LOCKED and c.special is None)
    p.x, p.y = car.to_world(0.0, -2.0)
    p.ang = p.input.yaw = math.atan2(car.y - p.y, car.x - p.x)
    return car


class TestRoster(unittest.TestCase):
    def test_the_data_is_well_formed(self):
        self.assertEqual([c["id"] for c in CH.CHARACTERS], list(range(len(CH.CHARACTERS))))
        for c in CH.CHARACTERS:
            self.assertLessEqual(len(c["perk"]), 40)
            self.assertLessEqual(len(c["blurb"]), 60)
            self.assertEqual(c["perk"], c["perk"].upper())
            self.assertTrue(c["name"] and c["title"])

    def test_default_and_unknown_are_dash(self):
        for bad in (None, -1, 4, 255, "x"):
            self.assertEqual(CH.clamp_char(bad), 0)
        self.assertEqual(CH.stat(99, "stamina_max"), CH.stat(0, "stamina_max"))
        self.assertEqual(CH.stat(SPANNER, "nonsense"), 1.0)
        w = quiet_world()
        self.assertEqual(w.add_player("A").char, 0)
        self.assertEqual(w.add_player("B", 77).char, 0)


class TestPerks(unittest.TestCase):
    def test_dash_has_the_lungs(self):
        w = quiet_world()
        p = w.add_player("D", DASH)
        self.assertAlmostEqual(p.stamina, C.STAMINA_MAX * C.CHAR_DASH_STAMINA_MAX)
        q = w.add_player("Q", SMOOTH)
        self.assertAlmostEqual(q.stamina, C.STAMINA_MAX)
        p.stamina = q.stamina = 10.0
        p.regen_delay = q.regen_delay = 0.0
        w._walk(p, 0, 1.0)
        w._walk(q, 0, 1.0)
        self.assertAlmostEqual(p.stamina - 10.0, C.STAMINA_REGEN * C.CHAR_DASH_STAMINA_REGEN)
        self.assertAlmostEqual(q.stamina - 10.0, C.STAMINA_REGEN)

    def _hold_times(self, char):
        w = quiet_world()
        p = w.add_player("X", char)
        car = near_locked_car(w, p)
        out = {"breakin": w._find_interaction(p)[2]}
        p.sneak = True
        res = w._find_interaction(p)
        out["cut"], out["wires"] = res[2], res[1]
        car.state = S.BROKEN_IN
        out["hotwire"] = w._find_interaction(p)[2]
        return out

    def test_slim_is_quick_with_locks(self):
        base, slim = self._hold_times(DASH), self._hold_times(SLIM)
        self.assertAlmostEqual(base["breakin"], C.BREAKIN_TIME)
        self.assertAlmostEqual(slim["breakin"], C.BREAKIN_TIME * C.CHAR_SLIM_BREAKIN_TIME)
        self.assertAlmostEqual(slim["hotwire"], C.HOTWIRE_TIME * C.CHAR_SLIM_HOTWIRE_TIME)
        self.assertAlmostEqual(slim["cut"], C.ALARM_CUT_TIME * C.CHAR_SLIM_ALARM_CUT_TIME)
        self.assertIn("1 IN 4", base["wires"])
        self.assertIn("1 IN 2", slim["wires"])

    def test_slims_wire_odds_are_a_coin_flip(self):
        w = quiet_world()
        p = w.add_player("X", SLIM)
        self.assertEqual(CH.alarm_wires(SLIM), 2)
        self.assertEqual(CH.alarm_wires(DASH), C.ALARM_CUT_WIRES)
        car = near_locked_car(w, p)
        hits = 0
        for _ in range(400):
            car.state, car.alarm = S.LOCKED, False
            w._cut_wires(p, car)
            hits += not car.alarm
        self.assertTrue(140 < hits < 260, hits)

    def test_spanner_strips_fast_on_cars_and_junk(self):
        def strip_prompt(char):
            w = quiet_world()
            p = w.add_player("X", char)
            car = delivered(w)
            p.x, p.y = car.to_world(0.0, -3.0)
            p.ang = p.input.yaw = math.atan2(car.y - p.y, car.x - p.x)
            return w._strip_interaction(p, car)
        base, span = strip_prompt(DASH), strip_prompt(SPANNER)
        self.assertEqual(base[0][0], "strip")
        self.assertAlmostEqual(span[2], base[2] * C.CHAR_SPANNER_STRIP_TIME)
        w = quiet_world()
        p = w.add_player("X", SPANNER)
        w.cash = 100_000
        w._buy_shop(1)
        t = w.junk[1][0]
        p.x, p.y = t.x, t.y + 1.0
        res = w._junk_interaction(p, t.x, t.y)
        self.assertAlmostEqual(res[2], C.JUNK_CLEAR_TIME * C.CHAR_SPANNER_STRIP_TIME)

    def test_smooth_talker_gets_more_for_the_same_lot(self):
        part = Part("whl_stock_alloy", 1.0)
        for char, mult in ((DASH, 1.0), (SMOOTH, C.CHAR_SMOOTH_SALE_BONUS)):
            w = quiet_world()
            p = w.add_player("X", char)
            w._list_part(part, 0, p)
            self.assertEqual(w.lots[0].who, p.id)
            cash = w.cash
            step(w, C.AUCTION_ASKS[0][3] + 0.1)
            self.assertEqual(w.cash - cash, int(B.ask_price(part.value, 0) * mult))
        # a lot Y lists pays Y's rate even though SMOOTH is in the room
        w = quiet_world()
        w.add_player("S", SMOOTH)
        y = w.add_player("Y", DASH)
        w._list_part(part, 0, y)
        cash = w.cash
        step(w, C.AUCTION_ASKS[0][3] + 0.1)
        self.assertEqual(w.cash - cash, B.ask_price(part.value, 0))

    def test_whole_car_sale_price_carries_the_charm(self):
        w = quiet_world()
        p = w.add_player("X", SMOOTH)
        car = delivered(w)
        car.papers = True
        p.ask = 0
        w._list_car(p, car)
        ask = B.ask_price(w.whole_price(car), 0)
        step(w, w.lots[0].t + 0.1)
        self.assertIsNotNone(car.sale)
        self.assertEqual(car.sale[1], int(ask * C.CHAR_SMOOTH_SALE_BONUS))

    def test_orders_pay_the_filler(self):
        pays = {}
        cat = B.ORDER_CAT_INDEX["wheel"]
        part = Part("whl_stock_alloy", 1.0)
        for char in (DASH, SMOOTH):
            w = quiet_world()
            p = w.add_player("X", char)
            w.orders[0] = {"contact": 0, "cat": cat, "need": 1, "got": 0, "bonus": B.order_bonus(cat, 1)}
            p.hands = [Part("whl_stock_alloy", 1.0)]
            cash = w.cash
            w._fill_order(p, 0, p.hands[0])
            pays[char] = w.cash - cash
        self.assertEqual(pays[DASH], int(part.value * C.ORDER_RATE) + B.order_bonus(cat, 1))
        self.assertEqual(pays[SMOOTH], int(part.value * C.ORDER_RATE * C.CHAR_SMOOTH_SALE_BONUS) +
                         int(B.order_bonus(cat, 1) * C.CHAR_SMOOTH_SALE_BONUS))

    def test_bail_and_papers_are_half_price_for_smooth(self):
        w = quiet_world()
        a, b = w.add_player("A", DASH), w.add_player("B", SMOOTH)
        self.assertEqual(w._bail(a), C.BAIL_BASE)
        self.assertEqual(w._bail(b), int(C.BAIL_BASE * C.CHAR_SMOOTH_FEE_MULT))
        car = delivered(w)
        self.assertEqual(w.papers_cost(a, car), w.papers_price(car))
        self.assertEqual(w.papers_cost(b, car), int(w.papers_price(car) * C.CHAR_SMOOTH_FEE_MULT))
        rx, ry = w.map.records
        b.x, b.y = rx, ry + 1.8
        b.ang = b.input.yaw = -math.pi / 2
        w.cash = 10_000
        _key, label, _t, action = w._find_interaction(b)[:4]
        self.assertIn("$%d" % w.papers_cost(b, car), label)
        action()
        self.assertEqual(w.cash, 10_000 - w.papers_cost(b, car))


class TestWire(unittest.TestCase):
    def test_version_bumped(self):
        self.assertGreaterEqual(C.VERSION, 17)

    def test_join_round_trips_with_and_without_the_char_byte(self):
        srv = Server(port=0, bind_host="127.0.0.1", map_seed=31337)
        try:
            base = P.header(P.P_JOIN) + P.JOIN.pack(5, 0) + P.encode_text("SLIMMY", 12)
            srv._handle(base + bytes((SLIM,)), ("127.0.0.1", 40001), 0.0)
            srv._handle(base, ("127.0.0.1", 40002), 0.0)               # an older/short packet
            srv._handle(base + bytes((200,)), ("127.0.0.1", 40003), 0.0)
            chars = [p.char for _, p in sorted(srv.world.players.items())]
            self.assertEqual(chars, [SLIM, 0, 0])
        finally:
            srv.stop()

    def test_client_puts_the_char_in_its_join(self):
        c = Client("127.0.0.1", 9, "ALICE", char=SMOOTH)
        try:
            sent = []
            c._send = lambda data: sent.append(data)
            c.update(now=c.started + 1.0)
            self.assertTrue(sent)
            self.assertEqual(sent[0][-1], SMOOTH)
            d = Client("127.0.0.1", 9, "B", char=99)
            self.assertEqual(d.char, 0)
            d.sock.close()
        finally:
            c.sock.close()

    def test_snapshot_carries_char_last_and_dashs_stamina_survives(self):
        w = quiet_world()
        a, b = w.add_player("A", DASH), w.add_player("B", SLIM)
        a.stamina = C.STAMINA_MAX * C.CHAR_DASH_STAMINA_MAX * 0.8
        b.stamina = C.STAMINA_MAX * 0.5
        s = snap(w, a)
        row = s.players[a.id]
        self.assertEqual(len(row), 20)
        self.assertEqual(row[19], DASH)
        self.assertEqual(s.players[b.id][19], SLIM)
        self.assertAlmostEqual(row[11], a.stamina, delta=C.STAMINA_MAX * 1.5 / 255 + 0.01)
        self.assertAlmostEqual(s.players[b.id][11], b.stamina, delta=C.STAMINA_MAX / 255 + 0.01)
        self.assertEqual(s.me[-1], DASH, "the SELF block knows too")

    def test_predicted_dash_matches_the_server(self):
        w = predict_world()
        p = w.add_player("REMOTE", DASH)
        # sprint past a stock pool's worth of stamina, then rest so regen runs too, then sprint again
        script = [S.B_RIGHT | S.B_SPRINT] * 330 + [0] * 200 + [S.B_UP | S.B_SPRINT] * 60
        pred, srv, pr = lockstep(w, p.id, script, lag_up=5, lag_down=7)
        self.assertLess(worst_gap(pred, srv), 0.01)
        self.assertEqual(pr.corrections, 0)
        self.assertAlmostEqual(pr.body.stamina, p.stamina, delta=0.01)
        self.assertEqual(pr.body.char, DASH)


if __name__ == "__main__":
    unittest.main()

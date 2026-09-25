"""Real network test: a threaded host + two clients over 127.0.0.1 UDP.

Checks that both clients agree on entity positions, cash and heat; that
reliable events (toasts) arrive; that packets stay small; and that both a
graceful leave and a silent timeout are handled.
"""

import math
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped.net import Server, Client


def pump_clients(clients, secs, inputs=None):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secs:
        for i, c in enumerate(clients):
            if inputs and inputs[i] is not None:
                c.inp = inputs[i]
            c.update()
        time.sleep(0.004)


class TestNetwork(unittest.TestCase):
    def setUp(self):
        self._timeout = C.TIMEOUT_S
        self.server = Server(port=0, bind_host="127.0.0.1", map_seed=31337)
        self.server.start()

    def tearDown(self):
        C.TIMEOUT_S = self._timeout
        self.server.stop()

    def test_two_clients_agree_and_disconnects_are_handled(self):
        a = Client("127.0.0.1", self.server.port, "ALICE")
        b = Client("127.0.0.1", self.server.port, "BOB")
        pump_clients([a, b], 1.5)
        self.assertEqual((a.state, b.state), ("connected", "connected"))
        self.assertNotEqual(a.pid, b.pid)
        self.assertEqual(a.map_seed, 31337)
        self.assertEqual(a.map.seed, b.map.seed)

        # scripted inputs: Alice walks east, Bob sprints north, for ~3 s
        pa0 = a.latest.players[a.pid][4:6]
        pb0 = a.latest.players[b.pid][4:6]
        # host-side state change folded into snapshots (cash/heat) + a reliable toast
        self.server.post(lambda w: (setattr(w, "cash", 1234), setattr(w, "heat", 42.0),
                                    setattr(w, "unseen_t", 0.0), w.toast("TEST TOAST 123")))
        pump_clients([a, b], 3.0, [S.InputState(S.B_RIGHT), S.InputState(S.B_UP | S.B_SPRINT)])
        pump_clients([a, b], 0.4, [S.InputState(0), S.InputState(0)])

        # 1) same authoritative values on both clients
        self.assertEqual(a.latest.cash, 1234)
        self.assertEqual(b.latest.cash, 1234)
        self.assertLessEqual(abs(a.latest.heat - b.latest.heat), 1)
        self.assertAlmostEqual(a.latest.heat, 42, delta=2)

        # 2) movement happened and both clients see it
        pa1 = a.latest.players[a.pid][4:6]
        pb1 = a.latest.players[b.pid][4:6]
        self.assertGreater(math.hypot(pa1[0] - pa0[0], pa1[1] - pa0[1]), 3.0, "Alice should have walked")
        self.assertGreater(math.hypot(pb1[0] - pb0[0], pb1[1] - pb0[1]), 3.0, "Bob should have run")

        # 3) exact agreement on a snapshot tick both received
        ticks_a = {s.tick: s for s in a.snaps}
        common = [s for s in b.snaps if s.tick in ticks_a]
        self.assertTrue(common, "clients should share at least one snapshot tick")
        sb = common[-1]
        sa = ticks_a[sb.tick]
        for kind in ("cars", "players"):
            ea, eb = getattr(sa, kind), getattr(sb, kind)
            self.assertEqual(set(ea), set(eb))
            ix = 7 if kind == "cars" else 4
            for eid in ea:
                self.assertAlmostEqual(ea[eid][ix], eb[eid][ix], delta=0.07)
                self.assertAlmostEqual(ea[eid][ix + 1], eb[eid][ix + 1], delta=0.07)
        self.assertEqual(sa.cash, sb.cash)
        self.assertEqual(sa.heat, sb.heat)

        # 4) interpolated views (what's actually drawn) agree within tolerance
        now = time.perf_counter()
        va, vb = a.view(now), b.view(now)
        worst = 0.0
        for eid, row in va.cars.items():
            if eid in vb.cars:
                worst = max(worst, math.hypot(row[7] - vb.cars[eid][7], row[8] - vb.cars[eid][8]))
        for pid in (a.pid, b.pid):
            ra, rb = va.players[pid], vb.players[pid]
            # each client pulls its OWN avatar forward (latest data), so allow a
            # little extra for the player the viewer controls
            worst = max(worst, math.hypot(ra[4] - rb[4], ra[5] - rb[5]) - 0.8)
        self.assertLess(worst, 0.8, "interpolated positions diverge by %.2f m" % worst)

        # 5) reliable event delivery (toasts)
        texts_a = [p[1] for k, p in a.pop_events() if k == 0]
        texts_b = [p[1] for k, p in b.pop_events() if k == 0]
        for texts in (texts_a, texts_b):
            self.assertIn("TEST TOAST 123", texts)
            self.assertIn("ALICE JOINED THE CREW", texts)
            self.assertIn("BOB JOINED THE CREW", texts)
        self.assertEqual(texts_a.count("TEST TOAST 123"), 1, "events are de-duplicated")

        # 6) packet size budget
        self.assertLess(self.server.max_packet, 1200)

        # 7) graceful disconnect
        b.leave()
        pump_clients([a], 0.6)
        self.assertEqual(a.latest.nplayers, 1)
        self.assertNotIn(b.pid, a.latest.players)
        self.assertIn("BOB LEFT", [p[1] for k, p in a.pop_events() if k == 0])

        # 8) silent timeout: a client that just vanishes gets dropped
        C.TIMEOUT_S = 1.5
        c = Client("127.0.0.1", self.server.port, "GHOST")
        pump_clients([a, c], 0.8)
        self.assertEqual(c.state, "connected")
        pump_clients([a], 0.3)
        self.assertEqual(a.latest.nplayers, 2)
        c.sock.close()                      # no LEAVE packet: pulled the plug
        pump_clients([a], 2.5)
        self.assertEqual(a.latest.nplayers, 1, "ghost should time out")
        self.assertEqual(self.server.player_count, 1)

        # 9) host shutting down is noticed by the remaining client
        self.server.stop()
        pump_clients([a], 0.3)
        self.assertEqual(a.state, "closed")
        a.leave()

    def test_server_full_and_version_reject(self):
        clients = [Client("127.0.0.1", self.server.port, "P%d" % i) for i in range(5)]
        pump_clients(clients, 1.5)
        states = sorted(c.state for c in clients)
        self.assertEqual(states.count("connected"), 4)
        self.assertEqual(states.count("failed"), 1)
        loser = [c for c in clients if c.state == "failed"][0]
        self.assertIn("FULL", loser.error)
        for c in clients:
            c.leave()
        # an old/new build with a different protocol version gets a polite no
        import socket
        from chopped import protocol as P
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2.0)
        s.sendto(P.HDR.pack(P.MAGIC, C.VERSION + 1, P.P_JOIN) + P.JOIN.pack(1, 0) + P.encode_text("OLDTIMER"),
                 ("127.0.0.1", self.server.port))
        data, _ = s.recvfrom(2048)
        s.close()
        self.assertEqual(P.parse_header(data)[1], P.P_REJECT)
        self.assertIn(b"VERSION", data)

    def test_client_times_out_when_server_dies_silently(self):
        C.TIMEOUT_S = 1.0
        a = Client("127.0.0.1", self.server.port, "ALICE")
        pump_clients([a], 0.6)
        self.assertEqual(a.state, "connected")
        self.server.running = False          # thread stops; no SHUTDOWN packet sent
        self.server.thread.join(1.0)
        pump_clients([a], 1.4)
        self.assertEqual(a.state, "closed")
        self.assertIn("LOST", a.error)
        a.leave()


if __name__ == "__main__":
    unittest.main()

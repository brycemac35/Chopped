"""Client-side prediction: the joining player's own car/avatar must respond
instantly AND end up exactly where the host says it is."""

import math
import os
import sys
import time
import unittest
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped.mapgen import CityMap
from chopped.net import Server, Client
from chopped.predict import Predictor

DT = 1.0 / C.SIM_HZ


def lockstep(world, pid, script, lag_up=6, lag_down=6):
    """Run server + predictor side by side with a fixed network delay (in
    ticks) and no jitter. Returns ({seq: predicted pose}, {seq: server pose}, predictor)."""
    pr = Predictor(CityMap(world.map_seed))          # the client builds its own copy of the city
    to_server = deque()                              # (arrive_tick, seq, buttons)
    to_client = deque()                              # (arrive_tick, snapshot bytes)
    pred, srv = {}, {}
    ack = 0
    p = world.players[pid]
    total = len(script) + lag_up + lag_down + 12
    for t in range(total):
        # --- client: one input + one predicted tick
        if t < len(script):
            seq = t + 1
            pr.push_input(seq, script[t])
            if pr.mode != P.ME_NONE:
                pred[seq] = pr.pose()
            to_server.append((t + lag_up, seq, script[t]))
        # --- server: apply whatever input has arrived, step, maybe snapshot
        while to_server and to_server[0][0] <= t:
            _, seq, b = to_server.popleft()
            world.set_input(pid, S.InputState(b))
            ack = seq
        world.step(DT)
        if ack:
            if p.state == S.DRIVER:
                car = world.cars[p.car_id]
                srv[ack] = (car.x, car.y, car.ang)
            else:
                srv[ack] = (p.x, p.y, p.ang)
        if world.tick % 3 == 0:
            to_client.append((t + lag_down, P.encode_snapshot(world, pid, 0, 0, ack)))
        while to_client and to_client[0][0] <= t:
            pkt = to_client.popleft()[1]
            pr.reconcile(P.decode_snapshot(pkt[P.HDR.size:]))
    return pred, srv, pr


def quiet_world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
        del w.cars[cid]
    return w


def worst_gap(pred, srv):
    common = [k for k in pred if k in srv]
    assert len(common) > 60, "too few comparable ticks (%d)" % len(common)
    return max(math.hypot(pred[k][0] - srv[k][0], pred[k][1] - srv[k][1]) for k in common)


class TestPredictionLockstep(unittest.TestCase):
    def test_predicted_car_matches_server_tick_for_tick(self):
        w = quiet_world()
        p = w.add_player("REMOTE")
        car = w.cars[w.personal_id]
        gx, gy, gw, gh = w.map.garage_rect
        car.x, car.y, car.ang = gx + gw / 2 - 30, gy + gh + 10.0, 0.0     # the road outside the shop
        w._enter_car(p, car, S.DRIVER)
        U, L, R, D, HB = S.B_UP, S.B_LEFT, S.B_RIGHT, S.B_DOWN, S.B_HANDBRAKE
        script = ([U] * 70 + [U | R] * 8 + [U] * 10 + [U | L] * 14 + [U] * 10 + [U | R] * 6 +
                  [HB | L] * 10 + [0] * 12 + [D] * 30 + [0] * 20)
        pred, srv, pr = lockstep(w, p.id, script)
        self.assertEqual(p.state, S.DRIVER, "test drive shouldn't crash out")
        self.assertGreater(math.hypot(car.vx, car.vy) + abs(car.x - (gx + gw / 2 - 30)), 5, "car moved")
        self.assertLess(worst_gap(pred, srv), 0.01, "prediction must match the host exactly")
        self.assertEqual(pr.corrections, 0)

    def test_predicted_walk_matches_server_including_walls_and_stamina(self):
        w = quiet_world()
        p = w.add_player("REMOTE")
        # sprint east until exhausted, then walk north into the garage's back wall
        script = [S.B_RIGHT | S.B_SPRINT] * 200 + [S.B_UP] * 150 + [S.B_UP | S.B_LEFT] * 40 + [0] * 30
        pred, srv, pr = lockstep(w, p.id, script, lag_up=5, lag_down=7)
        self.assertLess(worst_gap(pred, srv), 0.01)
        self.assertEqual(pr.corrections, 0)
        self.assertAlmostEqual(pr.body.stamina, p.stamina, delta=0.01)

    def test_misprediction_is_smoothed_not_snapped(self):
        w = quiet_world()
        p = w.add_player("REMOTE")
        pr = Predictor(CityMap(w.map_seed))
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0, 0)[P.HDR.size:]))
        x0 = pr.render_pose()[0]
        # the server shoves us 1 m east (a car bumped us, say): the view must not jump
        p.x += 1.0
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0, 0)[P.HDR.size:]))
        self.assertAlmostEqual(pr.render_pose()[0], x0, delta=1e-6)
        for _ in range(30):
            pr.advance(DT)
        self.assertAlmostEqual(pr.render_pose()[0], x0 + 1.0, delta=0.02)
        # ...but a respawn-sized jump teleports
        p.x += 20.0
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0, 0)[P.HDR.size:]))
        self.assertAlmostEqual(pr.render_pose()[0], p.x, delta=1e-3)


def pump(clients, secs, inputs=None):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < secs:
        for i, c in enumerate(clients):
            if inputs and inputs[i] is not None:
                c.inp = inputs[i]
            c.update()
        time.sleep(0.002)


class TestPredictionOverUDP(unittest.TestCase):
    def setUp(self):
        self.server = Server(port=0, bind_host="127.0.0.1", map_seed=31337)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_laggy_client_moves_instantly_and_converges(self):
        # 120 ms round trip plus up to 15 ms jitter each way
        c = Client("127.0.0.1", self.server.port, "LAGGY", fake_lag=0.06, fake_jitter=0.015)
        pump([c], 1.5)
        self.assertEqual(c.state, "connected")
        v0 = c.view()
        x0 = v0.me[4]
        server_x0 = c.latest.players[c.pid][4]
        # press RIGHT: within 50 ms (well under one round trip) we should see it
        pump([c], 0.05, [S.InputState(S.B_RIGHT)])
        moved = c.view().me[4] - x0
        self.assertGreater(moved, 0.08, "own avatar should move before the server has even heard")
        self.assertAlmostEqual(c.latest.players[c.pid][4], server_x0, delta=0.01,
                               msg="(sanity) the server's version hasn't moved yet")
        pump([c], 0.8, [S.InputState(S.B_RIGHT)])
        pump([c], 0.8, [S.InputState(0)])
        v = c.view()
        sx = c.latest.players[c.pid][4]
        self.assertGreater(sx - server_x0, 2.0, "the host agrees we walked")
        self.assertAlmostEqual(v.me[4], sx, delta=0.08, msg="prediction converges on the host's answer")
        c.leave()

    def test_no_predict_flag_still_works(self):
        c = Client("127.0.0.1", self.server.port, "OLDSKOOL", predict=False)
        pump([c], 1.0)
        self.assertIsNone(c.predictor)
        pump([c], 0.5, [S.InputState(S.B_DOWN)])
        self.assertIsNotNone(c.view().me)
        c.leave()


if __name__ == "__main__":
    unittest.main()

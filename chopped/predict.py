"""
predict.py -- client-side prediction, a.k.a. "why the joining player no
longer drives like they're steering a shopping trolley through custard".

Every client runs its OWN car (or on-foot crook) through exactly the same
physics the host uses (sim.Physics), one tick per input, the moment the key
goes down. When a snapshot arrives it says "the last input of yours I applied
was #N, and here's precisely where you ended up". We rewind to that, replay
inputs N+1.. on top, and whatever small disagreement is left over (you hit a
cop the server knew about and we didn't) gets smoothed out over ~80 ms
instead of teleporting you.

Only your own entity is predicted. Everyone else is still drawn from
interpolated snapshots, 100 ms in the past, which is what makes it smooth.
No pygame in here, same rule as sim.py.
"""

import math
from collections import deque

from . import config as C
from .sim import Physics, Car, drive_input
from .parts import SLOTS, SLOT_INDEX
from .protocol import ME_NONE, ME_FOOT, ME_DRIVER, SF_EXHAUSTED

DT = 1.0 / C.SIM_HZ


class PredCar(Car):
    """A Car whose power we're told rather than summed from parts (the client
    only knows which slots are filled, not what's in them)."""
    __slots__ = ("_power",)

    def power(self):
        return self._power


class Body:
    """Just enough of a Player for Physics._walk and the collision helpers."""
    __slots__ = ("x", "y", "vx", "vy", "ang", "stamina", "exhausted", "regen_delay",
                 "sprinting", "moving", "load")

    def __init__(self):
        self.x = self.y = self.vx = self.vy = self.ang = 0.0
        self.stamina = C.STAMINA_MAX
        self.exhausted = False
        self.regen_delay = 0.0
        self.sprinting = self.moving = False
        self.load = 0

    def hands_used(self):
        return self.load


def _car_from_row(row, power=100):
    """Rebuild a physics car from a snapshot CAR row
    (id, kind, color, state, flags, mask, tuned, x, y, vx, vy, ang, driver, passenger, damage)."""
    parts = {s: (1 if row[5] & (1 << SLOT_INDEX[s]) else None) for s in SLOTS}
    car = PredCar(row[0], row[1], row[7], row[8], row[11], parts, row[2])
    car.vx, car.vy = row[9], row[10]
    car.state = row[3]
    car.driver = row[12] or None
    car._power = power
    return car


class Predictor(Physics):
    def __init__(self, cmap):
        self.map = cmap
        self.cars = {}
        self._rects = []
        self.mode = ME_NONE
        self.car = None
        self.car_id = 0
        self.body = Body()
        self.err_x = self.err_y = self.err_a = 0.0
        self.pending = deque(maxlen=C.PREDICT_MAX_REPLAY)   # (seq, buttons) the server hasn't applied
        self.corrections = 0          # stats, for tests and the curious
        self.last_miss = 0.0

    # ------------------------------------------------------------------ inputs
    def push_input(self, seq, buttons):
        """A new input just went out: remember it and predict its tick now."""
        self.pending.append((seq, buttons))
        self.tick(buttons)

    def tick(self, buttons):
        if self.mode == ME_DRIVER:
            car = self.car
            drive_input(car, buttons)
            cars = self.cars.values()
            for c in cars:
                self._drive(c, DT)
            for c in cars:
                c.impact_dv = 0.0
                c.impact_nx = c.impact_ny = 0.0
                self._car_vs_world(c)
            reach = 2 * math.hypot(C.CAR_LEN / 2, C.CAR_WID / 2)
            for other in cars:
                if other is not car and abs(other.x - car.x) < reach and abs(other.y - car.y) < reach:
                    self._car_pair(car, other)
        elif self.mode == ME_FOOT:
            for c in self.cars.values():
                self._drive(c, DT)
                self._car_vs_world(c)
            b = self.body
            self._walk(b, buttons, DT)
            b.x += b.vx * DT
            b.y += b.vy * DT
            self._body_vs_world(b, C.PLAYER_RADIUS)
            self._body_vs_cars(b, C.PLAYER_RADIUS)

    # ------------------------------------------------------------------ reconcile
    def pose(self):
        if self.mode == ME_DRIVER:
            return self.car.x, self.car.y, self.car.ang
        if self.mode == ME_FOOT:
            return self.body.x, self.body.y, self.body.ang
        return None

    def reconcile(self, snap):
        """Rewind to the server's word on where we are, then replay every
        input it hasn't applied yet."""
        while self.pending and self.pending[0][0] <= snap.ack_input:
            self.pending.popleft()
        old = self.pose()
        old_mode, old_car = self.mode, self.car_id
        (mode, load, car_id, x, y, vx, vy, ang, w, stamina, regen, power, pull, flags) = snap.me
        row = snap.cars.get(car_id) if mode == ME_DRIVER else None
        if mode == ME_DRIVER and row is None:
            mode = ME_NONE
        self.mode = mode
        self.car_id = car_id if mode == ME_DRIVER else 0
        if mode == ME_NONE:
            self.car = None
            self.err_x = self.err_y = self.err_a = 0.0
            return
        # things to bump into: other cars near us, as of this snapshot
        self.cars = {}
        r2 = C.PREDICT_OBSTACLE_RANGE ** 2
        for crow in snap.cars.values():
            if crow[0] != car_id and (crow[7] - x) ** 2 + (crow[8] - y) ** 2 < r2:
                self.cars[crow[0]] = _car_from_row(crow)
        if mode == ME_DRIVER:
            car = self.car = _car_from_row(row, power)
            car.x, car.y, car.vx, car.vy, car.ang, car.w = x, y, vx, vy, ang, w
            car.pull = float(pull or 1)
            car.driver = snap.pid
            self.cars[car.id] = car
        else:
            self.car = None
            b = self.body
            b.x, b.y, b.vx, b.vy, b.ang = x, y, vx, vy, ang
            b.stamina, b.regen_delay = stamina, regen
            b.exhausted = bool(flags & SF_EXHAUSTED)
            b.load = load
        for _seq, buttons in self.pending:
            self.tick(buttons)
        new = self.pose()
        if old is not None and old_mode == mode and old_car == self.car_id:
            # keep what's on screen continuous: fold the jump into the error
            # offset, which then decays away in advance()
            ex = old[0] + self.err_x - new[0]
            ey = old[1] + self.err_y - new[1]
            miss = math.hypot(old[0] - new[0], old[1] - new[1])
            self.last_miss = miss
            if miss > 1e-3:
                self.corrections += 1
            if math.hypot(ex, ey) > C.PREDICT_SNAP_DIST:
                self.err_x = self.err_y = self.err_a = 0.0
            else:
                self.err_x, self.err_y = ex, ey
                d = (old[2] + self.err_a - new[2] + math.pi) % (2 * math.pi) - math.pi
                self.err_a = d if mode == ME_DRIVER else 0.0
        else:
            self.err_x = self.err_y = self.err_a = 0.0

    def advance(self, dt):
        """Called once per rendered frame: bleed off the correction offset."""
        k = math.exp(-C.PREDICT_CORRECT_RATE * dt)
        self.err_x *= k
        self.err_y *= k
        self.err_a *= k

    def render_pose(self):
        p = self.pose()
        if p is None:
            return None
        return p[0] + self.err_x, p[1] + self.err_y, p[2] + self.err_a

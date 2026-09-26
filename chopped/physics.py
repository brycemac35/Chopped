"""
physics.py -- movement and collision maths, shared by the authoritative
World (sim.py) and the client-side Predictor (predict.py). Same code on both
ends is the whole trick of prediction.
"""

import math

from . import config as C
from .config import clamp, lerp, wrap_angle
from .enums import *  # noqa: F401,F403
from . import vehicles as V

# ---------------------------------------------------------------------------
# Collision helpers
# ---------------------------------------------------------------------------
HL, HW = C.CAR_LEN / 2.0, C.CAR_WID / 2.0     # a Kei is a 4.4 x 2.4 m box, corners and all (other
CAR_BOUND_R = math.hypot(HL, HW)               # models carry their own hl/hw/bound since v0.7)
MAX_BOUND_R = 3.1                              # the biggest box van's circle, for "could these touch?"
CONTACT_TIE = 0.12                             # corners closer than this in depth count as "flush"


def circle_rect_contact(x, y, r, rect):
    """Returns (nx, ny, pen, px, py) if the circle overlaps the AABB, else None.
    (px, py) is the contact point on the rect."""
    rx, ry, rw, rh = rect
    cx = rx if x < rx else rx + rw if x > rx + rw else x
    cy = ry if y < ry else ry + rh if y > ry + rh else y
    dx, dy = x - cx, y - cy
    d2 = dx * dx + dy * dy
    if d2 >= r * r:
        return None
    if d2 > 1e-10:
        d = math.sqrt(d2)
        return dx / d, dy / d, r - d, cx, cy
    # centre is inside the rect: shove out along the shallowest axis
    l, rr, t, b = x - rx, rx + rw - x, y - ry, ry + rh - y
    m = min(l, rr, t, b)
    if m == l:
        return -1.0, 0.0, l + r, rx, y
    if m == rr:
        return 1.0, 0.0, rr + r, rx + rw, y
    if m == t:
        return 0.0, -1.0, t + r, x, ry
    return 0.0, 1.0, b + r, x, ry + rh


def _box_point(x, y, c, s, dx, dy, hl=HL, hw=HW):
    """The corner of a car box that sticks out furthest along (dx, dy). When
    two corners are within CONTACT_TIE of each other (a flush bumper against a
    wall) we take the middle of that edge instead -- otherwise a dead-straight
    hit would spin the car off whichever corner won the rounding lottery."""
    pf = c * dx + s * dy
    pr = -s * dx + c * dy
    lx = 0.0 if 2 * hl * abs(pf) < CONTACT_TIE else (hl if pf > 0 else -hl)
    ly = 0.0 if 2 * hw * abs(pr) < CONTACT_TIE else (hw if pr > 0 else -hw)
    return x + c * lx - s * ly, y + s * lx + c * ly


def _clamp_to_box(px, py, x, y, c, s, hl=HL, hw=HW):
    lx = clamp((px - x) * c + (py - y) * s, -hl, hl)
    ly = clamp(-(px - x) * s + (py - y) * c, -hw, hw)
    return x + c * lx - s * ly, y + s * lx + c * ly


def obb_rect_contact(x, y, ang, rect, hl=HL, hw=HW):
    """Car box vs axis-aligned rect, separating-axis test on the 4 candidate
    axes. Returns (nx, ny, pen, px, py) with the normal pointing from the rect
    towards the car, or None."""
    rx, ry, rw, rh = rect
    ex, ey = rw * 0.5, rh * 0.5
    dx, dy = rx + ex - x, ry + ey - y            # car centre -> rect centre
    c, s = math.cos(ang), math.sin(ang)
    ac, asn = abs(c), abs(s)
    ox = hl * ac + hw * asn + ex - abs(dx)
    if ox <= 0:
        return None
    oy = hl * asn + hw * ac + ey - abs(dy)
    if oy <= 0:
        return None
    df = dx * c + dy * s
    of = hl + ex * ac + ey * asn - abs(df)
    if of <= 0:
        return None
    dr = -dx * s + dy * c
    orr = hw + ex * asn + ey * ac - abs(dr)
    if orr <= 0:
        return None
    # Prefer the rect's own faces unless a car face is clearly shallower:
    # walls are axis-aligned, and a normal that flickers between two
    # candidates is how cars end up vibrating against buildings.
    if min(ox, oy) <= min(of, orr) * 1.05 + 0.02:
        if ox <= oy:
            nx, ny, pen = (-1.0 if dx > 0 else 1.0), 0.0, ox
        else:
            nx, ny, pen = 0.0, (-1.0 if dy > 0 else 1.0), oy
        px, py = _box_point(x, y, c, s, -nx, -ny, hl, hw)  # deepest car corner(s)
        px = clamp(px, rx, rx + rw)
        py = clamp(py, ry, ry + rh)
    else:
        if of <= orr:
            ax, ay, pen, dd = c, s, of, df
        else:
            ax, ay, pen, dd = -s, c, orr, dr
        sg = -1.0 if dd > 0 else 1.0
        nx, ny = ax * sg, ay * sg
        # the rect corner poking deepest into the car (a building corner in the door)
        qx = rx + rw * 0.5 if rw * abs(nx) < CONTACT_TIE else (rx + rw if nx > 0 else rx)
        qy = ry + rh * 0.5 if rh * abs(ny) < CONTACT_TIE else (ry + rh if ny > 0 else ry)
        px, py = _clamp_to_box(qx, qy, x, y, c, s, hl, hw)
    return nx, ny, pen, px, py


def obb_obb_contact(a, b):
    """Car box vs car box. Returns (nx, ny, pen, px, py), normal pointing from
    b to a, or None. Same SAT idea with both cars' axes as candidates."""
    dx, dy = b.x - a.x, b.y - a.y
    ca, sa = math.cos(a.ang), math.sin(a.ang)
    cb, sb = math.cos(b.ang), math.sin(b.ang)
    best = None
    for ux, uy, owner in ((ca, sa, 0), (-sa, ca, 0), (cb, sb, 1), (-sb, cb, 1)):
        ra = a.hl * abs(ux * ca + uy * sa) + a.hw * abs(-ux * sa + uy * ca)
        rb = b.hl * abs(ux * cb + uy * sb) + b.hw * abs(-ux * sb + uy * cb)
        dd = dx * ux + dy * uy
        ov = ra + rb - abs(dd)
        if ov <= 0:
            return None
        if best is None or ov < best[0] - 0.01:
            best = (ov, ux, uy, dd, owner)
    pen, ux, uy, dd, owner = best
    sg = -1.0 if dd > 0 else 1.0
    nx, ny = ux * sg, uy * sg                     # from b towards a
    if owner == 0:     # a's face: b's corner is doing the poking
        px, py = _box_point(b.x, b.y, cb, sb, nx, ny, b.hl, b.hw)
        px, py = _clamp_to_box(px, py, a.x, a.y, ca, sa, a.hl, a.hw)
    else:              # b's face: a's corner is doing the poking
        px, py = _box_point(a.x, a.y, ca, sa, -nx, -ny, a.hl, a.hw)
        px, py = _clamp_to_box(px, py, b.x, b.y, cb, sb, b.hl, b.hw)
    return nx, ny, pen, px, py


def box_distance(car, x, y):
    """Distance from a point to a car's box (0 if inside)."""
    c, s = math.cos(car.ang), math.sin(car.ang)
    lx = abs((x - car.x) * c + (y - car.y) * s) - car.hl
    ly = abs(-(x - car.x) * s + (y - car.y) * c) - car.hw
    return math.hypot(max(lx, 0.0), max(ly, 0.0))


def drive_input(car, buttons):
    """Driver's buttons -> pedals and wheel. Shared by the server and the
    client-side predictor so they can't disagree about what W means."""
    up, down = bool(buttons & B_UP), bool(buttons & B_DOWN)
    car.burnout = up and down                 # (v0.8) both pedals: brake stand. Smoke 'em.
    car.throttle = (1.0 if up and not down else 0.0) - (1.0 if down and not up else 0.0)
    car.steer = (1.0 if buttons & B_RIGHT else 0.0) - (1.0 if buttons & B_LEFT else 0.0)
    car.handbrake = bool(buttons & B_HANDBRAKE)
    car.boosting = bool(buttons & B_SPRINT) and car.nos and car.nos_fuel > 0   # Shift = NOS (if fitted)


class Physics:
    """Movement and collision maths, shared by the authoritative World and
    the client-side Predictor (predict.py). Same code on both ends is the whole
    trick of prediction: if the client ran different maths, it would predict a
    different car and the server would keep yanking it back.

    Subclasses provide self.map, self.cars, self._rects (a scratch list) and
    self.extra_rects (roadblocks: solid for cars and people alike)."""

    # ------------------------------------------------------------------ cars
    def _drive(self, car, dt):
        """One tick of tyre physics (v0.7). A bicycle model: the two front
        tyres act as one at the front axle, the two rears as one at the back.
        Each makes a sideways force from its slip angle (how far the way it's
        pointing differs from the way it's going) on a curve that peaks at
        ~9 degrees and then SAGS -- that sag is the whole art of drifting:
        once the tail is out, it takes less to keep it out. The rear also has
        to share its grip between pushing and cornering (friction ellipse),
        so a boot-full of throttle in a corner steps the tail out, and the
        handbrake locks it outright. Everything here reads only what the
        client-side predictor also knows (see predict.py)."""
        mdl = V.model(car.model)
        car.refresh()
        M, inertia = car.mass, car.inertia
        c, s = math.cos(car.ang), math.sin(car.ang)
        vf = car.vx * c + car.vy * s                  # forward speed
        vr = -car.vx * s + car.vy * c                 # sideways speed (+ = drifting to the right)
        w = car.w
        driven = (car.driver is not None or car.kind == COP or car.kind == TRAFFIC) and car.state != DELIVERED
        ai = car.driver is None and driven
        mw = car.missing_wheels()
        on_grass = self.map.tile_at(car.x, car.y) == 3 and not mdl.offroad   # GRASS (4x4s: what grass?)
        if car.kind == COP:
            accel = C.ACCEL_PER_100_POWER * C.COP_ACCEL_MULT
            top = C.COP_TOP_SPEED
        else:
            accel = C.ACCEL_PER_100_POWER * car.power() / 100.0 * mdl.accel
            top = mdl.top * car.top_mult
        top *= (1.0 - C.MISSING_WHEEL_TOP * mw)
        thr = car.throttle if driven else 0.0
        hb = (car.handbrake if driven else False)
        burn = driven and not ai and car.burnout
        if burn and (abs(car.vx * c + car.vy * s) > C.BURNOUT_MAX_SPEED or mw >= 2):
            burn, thr = False, -1.0                   # both pedals at speed: the brake wins
        boost = driven and car.boosting and car.nos_fuel > 0
        if boost:
            top *= C.NOS_TOP_MULT
        if burn:
            self._brake_stand(car, mdl, dt, top)
            return
        car.smoke_t = 0.0
        # ---- steering: the front wheels turn at a finite rate toward the target
        spd = math.hypot(car.vx, car.vy)
        lock = lerp(C.STEER_LOCK_LOW, C.STEER_LOCK_HIGH, clamp(spd / C.STEER_LOCK_SPEED, 0.0, 1.0))
        if ai and spd > 10.0:
            lock = max(C.STEER_LOCK_HIGH, lock * C.AI_STEER_LOCK)
        hl = car.hl
        a = b = hl * C.AXLE_FRAC                      # CG to front / rear axle
        steer = car.steer if driven else 0.0
        # caster: the front wheels trail into the direction of travel, and your
        # keys steer relative to THAT. Hands off mid-slide = the car holds the
        # drift; tap into it for more angle, tap against it to straighten up.
        # Real drift cars do this with 50 degrees of lock and a lot of practice.
        align = 0.0
        if vf > 3.0:
            align = clamp(math.atan2(vr + w * a, vf), -C.STEER_ALIGN_MAX, C.STEER_ALIGN_MAX) * C.STEER_ALIGN
        target = align + steer * lock
        if driven and not ai and vf > C.DRIFT_ASSIST_MIN_SPEED and steer:
            beta = math.atan2(vr, vf)
            if steer * beta > 0 and abs(beta) > C.COUNTERSTEER_FROM:
                # countersteering a slide on a keyboard: full lock is always too much (that's how
                # tank-slappers start). Point the wheels where the car's going, plus a touch.
                target = align + steer * min(lock, C.COUNTERSTEER_MARGIN)
        step = C.STEER_RATE * dt
        car.delta += clamp(target - car.delta, -step, step)
        delta = car.delta
        cd, sd = math.cos(delta), math.sin(delta)
        # ---- longitudinal demand (what the pedals ask for, before the tyres say no)
        drive = brake = 0.0                           # N at the driven axle / total braking
        if thr > 0:
            if vf < -0.5:
                brake = M * C.BRAKE_DECEL * thr
            else:
                room = max(0.0, 1.0 - (vf / top) ** 6) if top > 0 else 0.0   # fades out just shy of top speed
                drive = M * accel * thr * room
                if boost:
                    drive += M * C.NOS_ACCEL
        elif thr < 0:
            if vf > 0.5:
                brake = M * C.BRAKE_DECEL * -thr
            elif vf > -C.REVERSE_MAX:
                drive = M * accel * C.REVERSE_FRAC * thr
        if not driven:
            brake = M * C.PARKED_BRAKE                # chocked: nothing rolls far on its own
        # ---- weight transfer from the pedals (throttle squats the rear, brakes dive the nose)
        g = C.GRAVITY
        wf = 0.6 if mdl.fwd else C.FRONT_WEIGHT
        long_acc = clamp((drive - (brake if vf > 0 else -brake)) / M, -C.TRANSFER_MAX_G * g, C.TRANSFER_MAX_G * g)
        shift = M * long_acc * mdl.cg_h / (a + b) * C.WEIGHT_TRANSFER
        fz_f = max(0.15 * M * g, M * g * wf - shift)
        fz_r = max(0.15 * M * g, M * g * (1.0 - wf) + shift)
        mu = car.grip * C.TIRE_GRIP * (C.GRASS_GRIP_MULT if on_grass else 1.0)
        mu_f = mu_r = mu
        for slot, front in (("WheelFL", True), ("WheelFR", True), ("WheelRL", False), ("WheelRR", False)):
            if car.parts.get(slot) is None and slot not in mdl.no_slots:   # (v0.13: a bike's "missing" pair)
                if front:
                    mu_f *= C.MISSING_WHEEL_GRIP
                else:
                    mu_r *= C.MISSING_WHEEL_GRIP
        if car.spin_t > 0:
            mu_r *= C.BANANA_GRIP                      # on a banana. Rear-wheel drive, rear-wheel doom.
        # ---- contact-patch velocities
        v_fy = vr + w * a                              # front axle, car frame
        v_ry = vr - w * b
        fl = vf * cd + v_fy * sd                       # front tyre frame: along / across
        fla = -vf * sd + v_fy * cd
        eff_f = 1.0 / (1.0 / M + a * a / inertia)       # mass an axle "feels" sideways (for the no-overshoot cap)
        eff_r = 1.0 / (1.0 / M + b * b / inertia)
        # ---- front tyre
        cap_f = mu_f * fz_f
        ff_long = 0.0
        rear_share = 0.0 if mdl.fwd else (1.0 - C.AWD_FRONT_SHARE if mdl.awd else 1.0)
        if mdl.fwd:
            ff_long += drive
        elif mdl.awd:
            ff_long += drive * C.AWD_FRONT_SHARE
        ff_long -= math.copysign(min(brake * 0.6, cap_f * C.TIRE_LONG, abs(fl) * M / dt * 0.6), fl) if brake else 0.0
        ff_long = clamp(ff_long, -cap_f * C.TIRE_LONG, cap_f * C.TIRE_LONG)
        use_f = abs(ff_long) / (cap_f * C.TIRE_LONG) if cap_f > 0 else 1.0
        alpha_f = math.atan2(fla, max(abs(fl), C.TIRE_VMIN))
        ff_lat = -cap_f * math.sin(C.TIRE_C * math.atan(C.TIRE_B * alpha_f))
        ff_lat *= math.sqrt(max(0.0, 1.0 - use_f * use_f))
        ff_lat = clamp(ff_lat, -abs(fla) * eff_f / dt, abs(fla) * eff_f / dt)
        # ---- rear tyre
        cap_r = mu_r * fz_r
        if hb:
            # locked: pure sliding friction, opposite to however the rear is moving
            sp = math.hypot(vf, v_ry)
            k = min(C.HANDBRAKE_MU * cap_r, sp * eff_r / dt) / sp if sp > 1e-6 else 0.0
            fr_long = -vf * k + drive * rear_share * C.HANDBRAKE_DRIVE
            fr_lat = -v_ry * k
            car.wheelspin = 0.0
        else:
            fr_long = drive * rear_share
            if ai:
                fr_long = clamp(fr_long, -cap_r * C.AI_TRACTION, cap_r * C.AI_TRACTION)   # traction control
            if brake:
                fr_long -= math.copysign(min(brake * 0.4, cap_r * C.TIRE_LONG, abs(vf) * M / dt * 0.4), vf)
            demand = abs(fr_long) / (cap_r * C.TIRE_LONG) if cap_r > 0 else 1.0
            fr_long = clamp(fr_long, -cap_r * C.TIRE_LONG, cap_r * C.TIRE_LONG)
            use_r = min(1.0, demand)
            alpha_r = math.atan2(v_ry, max(abs(vf), C.TIRE_VMIN))
            fr_lat = -cap_r * math.sin(C.TIRE_C * math.atan(C.TIRE_B * alpha_r))
            fr_lat *= math.sqrt(max(0.0, 1.0 - use_r * use_r))
            if demand > C.WHEELSPIN_AT:
                # wheelspin: the rear goes light sideways. Boot it in a corner, hello drift.
                fr_lat *= max(0.2, 1.0 - (demand - C.WHEELSPIN_AT) * C.WHEELSPIN_LOSS)
            car.wheelspin = clamp((demand - C.WHEELSPIN_AT) * 2.5, 0.0, 1.0) if drive > 0 and rear_share else 0.0
            fr_lat = clamp(fr_lat, -abs(v_ry) * eff_r / dt, abs(v_ry) * eff_r / dt)
        # ---- sum up: forces in the car frame, torque about the CG
        f_long = ff_long * cd - ff_lat * sd + fr_long
        f_lat = ff_long * sd + ff_lat * cd + fr_lat
        torque = a * (ff_long * sd + ff_lat * cd) - b * fr_lat
        if mw:
            torque += car.pull * C.MISSING_WHEEL_PULL * mw * min(1.0, spd / 5.0) * inertia * 4.0
        # drag, rolling resistance, grass, and the scrub of going sideways
        f_long -= C.DRAG_K * vf * abs(vf) * M
        roll = (C.ROLL_DECEL * M if thr == 0.0 and driven else 0.0) + (C.GRASS_DRAG * M if on_grass else 0.0)
        f_long -= math.copysign(min(roll, abs(vf) * M / dt), vf) if abs(vf) > 1e-4 else 0.0
        ax = f_long / M
        ay = f_lat / M
        car.vx += (ax * c - ay * s) * dt
        car.vy += (ax * s + ay * c) * dt
        car.w += torque / inertia * dt
        if driven and not ai and car.spin_t <= 0:
            self._drift_assist(car, vf, vr, steer, hb, dt)
        if not driven and spd < 0.5:
            car.w *= math.exp(-6.0 * dt)               # parked cars don't pirouette on the spot
        # hard speed limits (reverse, and a sanity cap on top speed)
        vf2 = car.vx * c + car.vy * s
        if vf2 < -C.REVERSE_MAX - 2.0:
            fix = -C.REVERSE_MAX - 2.0 - vf2
            car.vx += c * fix
            car.vy += s * fix
        car.x += car.vx * dt
        car.y += car.vy * dt
        car.ang = wrap_angle(car.ang + car.w * dt)
        # NOS: burns while you hold it, refills while you don't
        if car.nos:
            if boost:
                car.nos_fuel = max(0.0, car.nos_fuel - dt)
            else:
                car.nos_fuel = min(C.NOS_TANK, car.nos_fuel + C.NOS_REFILL * dt)
        if car.spin_t > 0:
            car.spin_t -= dt

    def _drift_assist(self, car, vf, vr, steer, hb, dt):
        """v0.8 (Bryce: "the drifting feels too loose, please allow the driver
        to regain control"). What a real drift car's diff, caster and a good
        pair of hands do together, done for you: past DRIFT_ASSIST_START of
        slide the car is nudged back toward where it's going, and any spin
        that's making the slide WORSE is damped. Steer INTO the slide and the
        help mostly steps back (you asked for the angle); let go or
        countersteer and it catches you. On the handbrake it only stops the
        car turning into a spinning top."""
        if hb:
            lim = C.HANDBRAKE_MAX_YAW
            if abs(car.w) > lim:
                car.w = math.copysign(lim, car.w)
            return
        if vf < C.DRIFT_ASSIST_MIN_SPEED:
            return
        # yaw stability: no faster rotation than the tyres could hold in a steady turn at this
        # speed (more if you're steering WITH the rotation: you asked for it). This is what stops a
        # caught slide snapping back the other way -- the fishtail every keyboard driver knows.
        spd = math.hypot(vf, vr)
        cap = C.YAW_CAP_K * car.grip * C.TIRE_GRIP * C.GRAVITY / max(spd, 6.0)
        if steer * car.w > 0:
            cap *= C.YAW_CAP_INTO
        if abs(car.w) > cap:
            car.w -= math.copysign((abs(car.w) - cap) * min(1.0, C.YAW_CAP_RATE * dt), car.w)
        beta = math.atan2(vr, vf)                    # direction of travel, relative to the nose
        over = abs(beta) - C.DRIFT_ASSIST_START
        if over <= 0:
            return
        into = steer * beta < 0                      # steering further round: they want the angle
        k = C.DRIFT_ASSIST_INTO if into else 1.0
        # rotate the nose toward the direction of travel...
        car.w += math.copysign(over, beta) * C.DRIFT_ASSIST_YAW * k * dt
        # ...and bleed off rotation that's swinging the tail further out
        if car.w * beta < 0:
            car.w *= math.exp(-C.DRIFT_ASSIST_DAMP * k * min(1.0, over * 3.0) * dt)

    def _brake_stand(self, car, mdl, dt, top):
        """v0.8: W and S together at a standstill. The brakes hold one axle, the
        other one spins itself into a cloud. Add steering and the spinning end
        walks round the held one: donuts. (All-wheel drive can't do this -- it
        just sits there on the rev limiter looking embarrassed.)"""
        c, s = math.cos(car.ang), math.sin(car.ang)
        vf = car.vx * c + car.vy * s
        a = car.hl * C.AXLE_FRAC
        steer = car.steer
        k = min(1.0, C.BURNOUT_GRAB * dt)
        if mdl.awd:
            w_want, creep = 0.0, 0.0
        elif mdl.fwd:
            # front-drive: the fronts spin, the rears are held, the nose swings round
            w_want, creep = steer * C.BURNOUT_YAW * 0.6, C.BURNOUT_CREEP * 0.5
        else:
            # rear-drive: pivot on the held fronts, tail swings out the other way
            w_want, creep = steer * C.BURNOUT_YAW, C.BURNOUT_CREEP
        car.w += (w_want - car.w) * k
        vf += (creep - vf) * k
        # the CG moves on a circle round whichever axle is held
        vr = (-car.w * a) if not mdl.fwd else (car.w * a)
        car.vx, car.vy = vf * c - vr * s, vf * s + vr * c
        car.x += car.vx * dt
        car.y += car.vy * dt
        car.ang = wrap_angle(car.ang + car.w * dt)
        car.delta += clamp(steer * C.STEER_LOCK_LOW - car.delta, -C.STEER_RATE * dt, C.STEER_RATE * dt)
        car.wheelspin = 0.0 if mdl.awd else 1.0
        if not mdl.awd:
            car.smoke_t += dt
        if car.nos:
            car.nos_fuel = min(C.NOS_TANK, car.nos_fuel + C.NOS_REFILL * dt)
        if car.spin_t > 0:
            car.spin_t -= dt

    def slip_angle(self, car):
        """How sideways is it? (rad, 0 = pointing where it's going). For the
        drift meter and the tyre smoke."""
        spd = car.speed()
        if spd < 3.0:
            return 0.0
        return wrap_angle(math.atan2(car.vy, car.vx) - car.ang)

    def _apply_static_contact(self, car, px, py, nx, ny, pen, e):
        car.x += nx * pen
        car.y += ny * pen
        rx, ry = px - car.x, py - car.y
        vcx = car.vx - car.w * ry
        vcy = car.vy + car.w * rx
        vn = vcx * nx + vcy * ny
        if vn >= 0:
            return
        rn = rx * ny - ry * nx
        j = -(1.0 + e) * vn / (1.0 / car.mass + rn * rn / car.inertia)
        car.vx += j * nx / car.mass
        car.vy += j * ny / car.mass
        car.w += rn * j / car.inertia
        # scrape friction: walls are not ice rinks
        tx, ty = -ny, nx
        vt = vcx * tx + vcy * ty
        ft = clamp(-vt * car.mass * 0.25, -0.3 * j, 0.3 * j)
        car.vx += ft * tx / car.mass
        car.vy += ft * ty / car.mass
        dv = j / car.mass
        car.impact_dv += dv
        car.impact_nx += nx * dv
        car.impact_ny += ny * dv

    def _car_vs_world(self, car):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(car.x, car.y, car.bound, rects)
        rects.extend(self.extra_rects)             # roadblocks (few; the SAT test rejects far ones fast)
        hl, hw = car.hl, car.hw
        for rect in rects:
            hit = obb_rect_contact(car.x, car.y, car.ang, rect, hl, hw)
            if hit:
                nx, ny, pen, px, py = hit
                self._apply_static_contact(car, px, py, nx, ny, pen, C.RESTITUTION_WALL)

    def _car_pair(self, a, b):
        """Box-vs-box bump with a proper impulse at the contact point, so a
        T-bone spins the victim and a nudge on the bumper just pushes. Returns
        the closing speed (for "was that hard enough to set a cop on fire?")
        or None if they didn't touch."""
        hit = obb_obb_contact(a, b)
        if hit is None:
            return None
        nx, ny, pen, px, py = hit                  # normal points from b to a
        ima, imb = 1.0 / a.mass, 1.0 / b.mass
        a.x += nx * pen * ima / (ima + imb)
        a.y += ny * pen * ima / (ima + imb)
        b.x -= nx * pen * imb / (ima + imb)
        b.y -= ny * pen * imb / (ima + imb)
        rax, ray = px - a.x, py - a.y
        rbx, rby = px - b.x, py - b.y
        vax = a.vx - a.w * ray
        vay = a.vy + a.w * rax
        vbx = b.vx - b.w * rby
        vby = b.vy + b.w * rbx
        vn = (vax - vbx) * nx + (vay - vby) * ny
        if vn >= 0:
            return None
        rel = math.hypot(a.vx - b.vx, a.vy - b.vy)
        rna = rax * ny - ray * nx
        rnb = rbx * ny - rby * nx
        j = -(1.0 + C.RESTITUTION_CAR) * vn / (ima + imb + rna * rna / a.inertia + rnb * rnb / b.inertia)
        a.vx += j * nx * ima
        a.vy += j * ny * ima
        a.w += rna * j / a.inertia
        b.vx -= j * nx * imb
        b.vy -= j * ny * imb
        b.w -= rnb * j / b.inertia
        dva, dvb = j * ima, j * imb
        a.impact_dv += dva
        a.impact_nx += nx * dva
        a.impact_ny += ny * dva
        b.impact_dv += dvb
        b.impact_nx -= nx * dvb
        b.impact_ny -= ny * dvb
        return rel

    # ------------------------------------------------------------------ people
    def _walk(self, p, b, dt):
        """On-foot controls -> stamina, facing and velocity. The predictor runs
        this too, so it may only read things the client is told about."""
        # first person: W/S along where you're looking, A/D strafe
        fwd = (1 if b & B_UP else 0) - (1 if b & B_DOWN else 0)
        side = (1 if b & B_RIGHT else 0) - (1 if b & B_LEFT else 0)
        ca, sa = math.cos(p.ang), math.sin(p.ang)
        dx, dy = ca * fwd - sa * side, sa * fwd + ca * side
        moving = fwd != 0 or side != 0
        used = p.walk_load()
        want_sprint = bool(b & B_SPRINT) and moving and not p.exhausted and p.stamina > 0
        if want_sprint:
            p.stamina -= C.STAMINA_SPRINT_DRAIN[min(used, 2)] * dt
            p.regen_delay = C.STAMINA_REGEN_DELAY
        elif moving and used >= 2:
            p.stamina -= C.STAMINA_WALK_2H_DRAIN * dt
            p.regen_delay = C.STAMINA_REGEN_DELAY
        else:
            p.regen_delay -= dt
            if p.regen_delay <= 0:
                p.stamina = min(C.STAMINA_MAX, p.stamina + C.STAMINA_REGEN * dt)
        if p.stamina <= 0:
            p.stamina = 0.0
            p.exhausted = True
        elif p.exhausted and p.stamina > C.STAMINA_RECOVER_AT:
            p.exhausted = False
        spd = (C.SPRINT_SPEED if want_sprint else C.WALK_SPEED) * p.speed_mult()
        if p.exhausted:
            spd *= C.EXHAUSTED_SPEED_MULT
        if moving:
            inv = 1.0 / math.hypot(dx, dy)
            tx, ty = dx * inv * spd, dy * inv * spd
        else:
            tx = ty = 0.0
        grounded = p.z <= 0.0
        k = min(1.0, (16.0 if grounded else C.AIR_CONTROL) * dt)
        p.vx += (tx - p.vx) * k
        p.vy += (ty - p.vy) * k
        p.sprinting = want_sprint
        p.moving = moving
        # jumping (v0.7). Hold Space and you bunny-hop. We're not judging.
        if grounded and b & B_JUMP and p.walk_load() < 2 and p.stamina > C.JUMP_STAMINA:
            p.vz = C.JUMP_SPEED * (0.8 if used else 1.0)
            p.stamina -= C.JUMP_STAMINA
            p.regen_delay = C.STAMINA_REGEN_DELAY
            grounded = False
        if not grounded or p.vz:
            self._fall(p, dt)

    @staticmethod
    def _fall(b, dt, chute=False):
        """Gravity for anything with a z: people mid-jump, mid-throw, mid-ejection."""
        b.vz -= C.JUMP_GRAVITY * dt
        if chute:
            b.vz = max(b.vz, -C.CHUTE_SINK)
        b.z += b.vz * dt
        if b.z <= 0.0:
            b.z = 0.0
            b.vz = 0.0

    def _body_vs_world(self, b, r):
        rects = self._rects
        rects.clear()
        self.map.solid_rects_near(b.x, b.y, r, rects)
        # jump high enough and you clear a roadblock. Not a cell door, though (v0.9: the
        # doors and the gate are tall_rects, which are in extra_rects too, for the cars)
        rects.extend(self.extra_rects if b.z < C.HURDLE_HEIGHT else self.tall_rects)
        for rect in rects:
            hit = circle_rect_contact(b.x, b.y, r, rect)
            if hit:
                nx, ny, pen, _, _ = hit
                b.x += nx * pen
                b.y += ny * pen
                vn = b.vx * nx + b.vy * ny
                if vn < 0:
                    b.vx -= vn * nx * 1.3
                    b.vy -= vn * ny * 1.3

    def _body_vs_cars(self, b, r):
        """Circle (a person) vs every car box nearby: shove them out, kill the
        closing velocity, and report the hardest hit as (impact, car_vx,
        car_vy, nx, ny) so the caller can decide who goes ragdoll.

        impact (v0.9) is how fast the CAR's bodywork was moving into you at
        the point it touched you -- not how fast you were moving into it. A
        parked car is a wall: sprint into it and you slide round it, you don't
        fall over. A drifting tail swinging round, on the other hand, counts."""
        result = None
        if b.z > C.CAR_ROOF_Z:
            return None                                # sailing over the traffic
        for car in self.cars.values():
            dx, dy = b.x - car.x, b.y - car.y
            reach = car.bound + r
            if abs(dx) > reach or abs(dy) > reach:
                continue
            hl, hw = car.hl, car.hw
            c, s = math.cos(car.ang), math.sin(car.ang)
            lx = dx * c + dy * s
            ly = -dx * s + dy * c
            qx = hl if lx > hl else -hl if lx < -hl else lx
            qy = hw if ly > hw else -hw if ly < -hw else ly
            ex, ey = lx - qx, ly - qy
            d2 = ex * ex + ey * ey
            if d2 > 1e-12:
                if d2 >= r * r:
                    continue
                d = math.sqrt(d2)
                nlx, nly, pen = ex / d, ey / d, r - d
            else:
                # centre inside the car (it drove onto you): out the nearest side
                fx, fy = hl - abs(lx), hw - abs(ly)
                if fx < fy:
                    nlx, nly, pen = (1.0 if lx >= 0 else -1.0), 0.0, fx + r
                else:
                    nlx, nly, pen = 0.0, (1.0 if ly >= 0 else -1.0), fy + r
            nx, ny = nlx * c - nly * s, nlx * s + nly * c
            b.x += nx * pen
            b.y += ny * pen
            # the bodywork's own velocity where it touches you (spin included)
            wx, wy = qx * c - qy * s, qx * s + qy * c           # contact point, relative to the car
            pvx, pvy = car.vx - car.w * wy, car.vy + car.w * wx
            impact = max(0.0, pvx * nx + pvy * ny)
            vn = (b.vx - pvx) * nx + (b.vy - pvy) * ny
            if vn < 0:
                b.vx -= vn * nx
                b.vy -= vn * ny
            if result is None or impact > result[0]:
                result = (impact, pvx, pvy, nx, ny)
        return result




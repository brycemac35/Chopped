"""v0.8: the police get out of the car. Cuffs before bullets, tasers at high heat,
lethal force only once the crew starts shooting (and dying costs the crew its
share of the cash), the precinct lockup and the ways out of it, plus the
police-flavoured silly stuff: the K9 unit, the streaker, speed cameras, burnout
smoke screens and hydraulics."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import vehicles as V
from chopped.parts import Part, model_loadout
from chopped.predict import Predictor
from chopped.mapgen import CityMap

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def world():
    w = S.World(map_seed=4242, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    w.streaker_t = 1e9                       # (the streaker gets his own test)
    for cid in [c.id for c in w.cars.values() if c.kind != S.PERSONAL]:
        del w.cars[cid]
    for pid in [k for k, pk in w.pickups.items() if pk.fixed]:
        del w.pickups[pid]
    return w


def street(w):
    gx, gy, gw, gh = w.map.garage_rect
    return gx + gw / 2 + 30, gy + gh + 10.0


def inp(p, **kw):
    i = p.input
    d = dict(buttons=i.buttons, use_count=i.use_count, drop_count=i.drop_count, exit_count=i.exit_count, yaw=i.yaw,
             fire_count=i.fire_count, weapon=i.weapon)
    d.update(kw)
    p.input = S.InputState(**d)


def face(p, x, y):
    inp(p, yaw=math.atan2(y - p.y, x - p.x))
    p.ang = p.input.yaw


def click(p):
    inp(p, fire_count=p.input.fire_count + 1)


def officer(w, x, y):
    n = S.NPC(w.new_id(), S.OFFICER, x, y)
    w.npcs[n.id] = n
    return n


def hold_heat(w, secs, heat):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.heat = heat
        w.step(DT)


def lock_up(w, p):
    w.arrest(p)
    step(w, C.CUFFED_TIME + 0.1)


class TestOfficers(unittest.TestCase):
    def test_a_cop_car_lets_its_officer_out_to_cuff_you(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        cop = S.Car(w.new_id(), S.COP, p.x + 14, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        hold_heat(w, 0.3, 30)
        self.assertIsNotNone(cop.officer, "slow cop car + a crook on foot nearby = officer out")
        self.assertEqual(w.npcs[cop.officer].kind, S.OFFICER)
        for _ in range(int(6 / DT)):
            w.heat = 30
            w.step(DT)
            if p.state == S.CUFFED:
                break
        self.assertEqual(p.state, S.CUFFED, "stand there and you get cuffed")
        self.assertEqual(p.arrests, 1)
        step(w, C.CUFFED_TIME + 0.1)
        self.assertTrue(p.jailed)
        self.assertTrue(w.map.in_precinct(p.x, p.y))
        self.assertTrue(any(n.kind == S.KEYGUARD for n in w.npcs.values()), "the lockup is staffed")

    def test_the_officer_walks_back_to_his_car_when_you_escape(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        cop = S.Car(w.new_id(), S.COP, p.x + 14, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        hold_heat(w, 0.3, 30)
        oid = cop.officer
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw / 2, gy + gh / 2          # safe in the shop
        hold_heat(w, 8.0, 30)
        self.assertNotIn(oid, w.npcs, "back in the car")
        self.assertIsNone(cop.officer)

    def test_mash_space_to_wriggle_out_of_the_cuffs(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = officer(w, p.x + 1.0, p.y)
        hold_heat(w, 0.3, 30)
        self.assertEqual(n.mode, 3, "cuffs out")
        self.assertGreater(p.cuff_prog, 0)
        for _ in range(C.CUFF_BREAK_PRESSES):
            inp(p, buttons=S.B_JUMP)
            w.heat = 30
            w.step(DT)
            inp(p, buttons=0)
            w.heat = 30
            w.step(DT)
        self.assertEqual(p.cuff_prog, 0.0)
        self.assertNotEqual(p.state, S.CUFFED)
        self.assertGreater(n.tumble_t, 0, "the officer's on his backside")

    def test_punching_an_officer_knocks_him_down_and_is_noticed(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        n = officer(w, p.x + 1.0, p.y)
        face(p, n.x, n.y)
        w.heat = 20
        click(p)
        w.step(DT)
        self.assertGreater(n.tumble_t, 1.0)
        self.assertGreaterEqual(w.heat, 20 + C.ASSAULT_OFFICER_HEAT - 0.5)
        self.assertEqual(p.rap.get("cop"), 1, "it's on the charge sheet")

    def test_tasers_at_high_heat(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        officer(w, p.x + 6.0, p.y)
        acc = C.TASER_ACCURACY
        try:
            C.TASER_ACCURACY = 1.0
            for _ in range(int(1.0 / DT)):
                w.heat = C.TASER_HEAT + 10
                w.step(DT)
                if p.tased_t > 0:
                    break
        finally:
            C.TASER_ACCURACY = acc
        self.assertGreater(p.tased_t, 0)
        self.assertEqual(p.state, S.TUMBLE, "twitching on the pavement")
        self.assertEqual(p.banner, S.BN_TASED)


class TestLethalForce(unittest.TestCase):
    def test_a_gunshot_near_the_police_starts_the_lethal_clock(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        p.arms |= 1 << S.ARM_PISTOL
        p.ammo[S.ARM_PISTOL] = 5
        inp(p, weapon=S.ARM_PISTOL)
        p.weapon = S.ARM_PISTOL
        click(p)
        w.step(DT)
        self.assertEqual(w.lethal_t, 0.0, "no cops within earshot: nobody's shooting back")
        cop = S.Car(w.new_id(), S.COP, p.x + 30, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        step(w, C.PISTOL_COOLDOWN + 0.05)
        click(p)
        w.step(DT)
        self.assertGreater(w.lethal_t, 0, "a cop heard it")
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertTrue(snap.alert & P.AL_LETHAL)

    def test_death_costs_the_crew_its_share(self):
        w = world()
        a = w.add_player("ALICE")
        w.add_player("BOB")
        a.x, a.y = street(w)
        w.cash = 1000
        a.hands = [Part("whl_stock_alloy")]
        w._kill(a)
        self.assertEqual(a.state, S.DEAD)
        self.assertEqual(w.cash, 1000 - int(1000 * C.DEATH_LOSS / 2), "two of you: half the hit each")
        self.assertEqual(a.hands, [], "dropped where you fell")
        self.assertEqual(a.banner, S.BN_WASTED)
        step(w, C.DEATH_TIME + 0.1)
        self.assertEqual(a.state, S.FOOT)
        self.assertTrue(w.map.in_garage(a.x, a.y))

    def test_dying_broke_costs_nothing(self):
        w = world()
        a = w.add_player("ALICE")
        w.cash = -50
        w._kill(a)
        self.assertEqual(w.cash, -50)


class TestPrecinct(unittest.TestCase):
    def test_every_city_has_a_precinct_far_from_the_shop(self):
        for seed in (1, 99, 4242, 12345, 777):
            m = CityMap(seed)
            self.assertIsNotNone(m.precinct_outer)
            (sx, sy), (gx, gy) = m.garage_center, m.gate[:2]
            self.assertGreater(math.hypot(sx - gx, sy - gy), C.PITCH * C.TILE_M * 2.5)
            for x, y in m.jail_spawns:
                self.assertTrue(m.in_precinct(x, y))
                self.assertFalse(m.solid_at(x, y))

    def test_the_gate_is_solid_until_it_opens(self):
        w = world()
        g = w.gate()
        self.assertIn(g.rect(), w.extra_rects)
        w._open_gate(g, 2.0)
        self.assertNotIn(g.rect(), w.extra_rects)
        step(w, 2.1)
        self.assertIn(g.rect(), w.extra_rects, "and it shuts again")

    def test_knock_out_the_big_guard_take_his_keys_walk_out(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        kg = next(n for n in w.npcs.values() if n.kind == S.KEYGUARD)
        # flatten him (he's the big one: it takes a few)
        for _ in range(kg.grit + 1):
            w._knock_down_npc(kg, 0.0, 0.0, 1.0, p)
        self.assertGreater(kg.tumble_t, C.GUARD_DOWN_TIME)
        w._take_keys(p, kg)
        self.assertTrue(p.keys)
        self.assertEqual(kg.kind, S.GUARD, "he doesn't have them any more")
        # to the gate
        g = w.gate()
        p.x, p.y = g.x, g.y - 1.6
        face(p, g.x, g.y)
        for n in list(w.npcs.values()):
            if n.kind in (S.GUARD, S.KEYGUARD):
                n.tumble_t = 30.0                 # (the others are having a lie down too)
        inp(p, use_count=p.input.use_count + 1)
        w.step(DT)
        self.assertGreater(g.open_t, 0, "the gate clanks open")
        self.assertFalse(p.keys)
        heat0 = w.heat
        inp(p, buttons=S.B_UP, yaw=math.pi / 2)       # (forward, facing south: out of the door)
        p.ang = math.pi / 2
        for _ in range(int(4.0 / DT)):
            w.step(DT)
            if not p.jailed:
                break
        self.assertFalse(p.jailed, "out!")
        self.assertTrue(p.jumpsuit, "...in orange")
        self.assertGreater(w.heat, heat0, "a jailbreak is noticed")
        self.assertEqual(p.banner, S.BN_FREE)
        # home to change
        gx, gy, gw, gh = w.map.garage_rect
        p.x, p.y = gx + gw / 2, gy + gh / 2
        inp(p, buttons=0)
        w.step(DT)
        self.assertFalse(p.jumpsuit)

    def test_the_guards_come_for_you(self):
        """(v0.9) ...once you're out of your cell and they've noticed."""
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        k = w.map.cell_at(p.x, p.y)
        self.assertGreaterEqual(k, 0, "you wake up in a cell")
        step(w, 8.0)
        self.assertEqual(p.state, S.FOOT, "nobody can reach you in there")
        self.assertEqual(w.map.cell_at(p.x, p.y), k, "and you can't leave")
        # out into the hall, right up to a guard: noticed, then flattened
        w._open_cell(w.cell_traps[k], True)
        g = next(n for n in w.npcs.values() if n.kind == S.GUARD)
        p.x, p.y = g.x + 1.5, g.y
        hurt = False
        for _ in range(int(8 / DT)):
            w.step(DT)
            if p.state == S.TUMBLE:
                hurt = True
                break
        self.assertTrue(w.jail_alert)
        self.assertTrue(hurt, "stand about in the lockup and a guard flattens you")

    def test_bail(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        w.cash = 1000
        bail = w._bail(p)
        self.assertEqual(bail, C.BAIL_BASE)
        w._post_bail(p)
        self.assertFalse(p.jailed)
        self.assertFalse(p.jumpsuit, "bailed out: no jumpsuit, no heat")
        self.assertEqual(w.cash, 1000 - bail)
        self.assertGreater(w.gate().open_t, 0)
        p.arrests = 3
        self.assertEqual(w._bail(p), C.BAIL_BASE + 2 * C.BAIL_PER_ARREST, "it goes up")

    def test_a_crewmate_picks_the_lock_from_outside(self):
        w = world()
        a = w.add_player("ALICE")
        b = w.add_player("BOB")
        lock_up(w, a)
        g = w.gate()
        b.x, b.y = g.x, g.y + 1.8
        face(b, g.x, g.y)
        inp(b, buttons=S.B_USE)
        step(w, C.GATE_PICK_TIME + 0.2)
        self.assertGreater(g.open_t, 0, "the lock's picked")

    def test_ram_the_gate(self):
        w = world()
        g = w.gate()
        car = w.cars[w.personal_id]
        car.x, car.y, car.ang = g.x, g.y + 6.0, -math.pi / 2
        car.vx, car.vy = 0.0, -22.0
        for _ in range(int(1.0 / DT)):
            w.step(DT)
            if g.open_t > 0:
                break
        self.assertGreater(g.open_t, 0, "through it, at speed")

    def test_the_predictor_knows_about_the_gate(self):
        w = world()
        p = w.add_player("BRYCE")
        g = w.gate()
        p.x, p.y = g.x, g.y + 5.0
        pr = Predictor(CityMap(w.map_seed))
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]))
        self.assertIn(g.rect(), pr.extra_rects, "shut: solid for the predictor too")
        w._open_gate(g, 5.0)
        pr.reconcile(P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]))
        self.assertNotIn(g.rect(), pr.extra_rects)

    def test_mugshot_reads_the_rap_sheet(self):
        w = world()
        p = w.add_player("BRYCE")
        p.rap = {"gta": 3, "gnome": 1, "dance": 2}
        w.arrest(p)
        text = " ".join(e[3][1] for e in w.events if e[2] == 0)
        self.assertIn("3X GRAND THEFT AUTO", text)
        self.assertIn("GNOME THEFT", text)
        self.assertIn("2X UNLICENSED DANCING", text)
        self.assertEqual(p.banner, S.BN_BUSTED)


class TestCells(unittest.TestCase):
    """v0.9: "instead of just a big open hall in the precinct have a small jail cell
    you need to break out of first", and guards that are "harder to kill, but ...
    can't box you in the corner and spawn trap you"."""

    def test_the_cells_are_real(self):
        for seed in (1, 99, 4242, 12345, 777):
            m = CityMap(seed)
            self.assertEqual(len(m.cells), 2)
            self.assertEqual(len(m.cell_doors), 2)
            for k, (x, y, _a) in enumerate(m.cell_doors):
                self.assertTrue(m.in_precinct(x, y - 0.5))
            for x, y in m.jail_spawns:
                self.assertGreaterEqual(m.cell_at(x, y), 0, "you start in a cell")

    def test_the_door_is_solid_and_you_cant_jump_it(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        d = w.cell_traps[w.map.cell_at(p.x, p.y)]
        self.assertIn(d.rect(), w.tall_rects)
        p.x, p.y, p.z = d.x, d.y + 0.2, 2.5          # (mid-leap, straight through the bars)
        p.vx = p.vy = 0.0
        w._body_vs_world(p, C.PLAYER_RADIUS)
        self.assertGreater(abs(p.y - d.y), 0.2, "the bars go all the way up")

    def test_punch_it_open_loudly(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        d = w.cell_traps[w.map.cell_at(p.x, p.y)]
        p.x, p.y = d.x, d.y - 1.0
        for _ in range(C.CELL_DOOR_HP):
            face(p, d.x, d.y)
            self.assertTrue(w._punch_cell_door(p))
        self.assertEqual(d.uses, 0)
        self.assertNotIn(d.rect(), w.extra_rects)
        self.assertTrue(w.jail_alert, "the guards heard every one of those")

    def test_pick_it_quietly(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        d = w.cell_traps[w.map.cell_at(p.x, p.y)]
        p.x, p.y = d.x, d.y - 1.0
        face(p, d.x, d.y)
        inp(p, buttons=S.B_USE)
        step(w, C.CELL_PICK_TIME + 0.3)
        self.assertEqual(d.uses, 0, "click")
        self.assertFalse(w.jail_alert, "nobody noticed")

    def test_bail_from_the_cell_with_x(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        w.cash = 2000
        self.assertIn("X: BAIL", p.prompt)
        inp(p, buttons=S.B_HOP)
        w.step(DT)
        self.assertFalse(p.jailed)
        self.assertEqual(w.cell_traps[w.map.cell_at(p.x, p.y)].uses, 0, "and they open the door for you")

    def test_a_crewmate_lets_you_out(self):
        w = world()
        a = w.add_player("ALICE")
        b = w.add_player("BOB")
        lock_up(w, a)
        d = w.cell_traps[w.map.cell_at(a.x, a.y)]
        b.x, b.y = d.x, d.y + 1.3
        face(b, d.x, d.y)
        inp(b, buttons=S.B_USE)
        step(w, C.CELL_OPEN_TIME + 0.3)
        self.assertEqual(d.uses, 0)

    def test_two_prisoners_two_cells(self):
        w = world()
        a = w.add_player("ALICE")
        b = w.add_player("BOB")
        lock_up(w, a)
        lock_up(w, b)
        self.assertNotEqual(w.map.cell_at(a.x, a.y), w.map.cell_at(b.x, b.y), "one each: room to pace")

    def test_the_guards_are_harder_to_kill(self):
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        g = next(n for n in w.npcs.values() if n.kind == S.GUARD)
        kg = next(n for n in w.npcs.values() if n.kind == S.KEYGUARD)
        self.assertGreaterEqual(g.grit, 4)
        self.assertGreater(kg.grit, g.grit)

    def test_one_at_a_time_and_no_pinning(self):
        """Out in the hall, the guards take turns, back off after a hit, and never
        hit you again while you're getting up."""
        w = world()
        p = w.add_player("BRYCE")
        lock_up(w, p)
        w._open_cell(w.cell_traps[w.map.cell_at(p.x, p.y)], False)
        px, py, pw, ph = w.map.precinct_rect
        p.x, p.y = px + pw / 2, py + ph / 2 - 1.0
        w.jail_alert = True
        close_max = 0
        knocks, got_up = 0, None
        was = p.state
        for i in range(int(12 / DT)):
            p.vx = p.vy = 0.0
            w.step(DT)
            guards = [n for n in w.npcs.values() if n.kind in (S.GUARD, S.KEYGUARD) and n.tumble_t <= 0]
            if i > int(2.5 / DT):
                close = sum(1 for n in guards if math.hypot(n.x - p.x, n.y - p.y) < C.GUARD_RING - 1.0)
                close_max = max(close_max, close)
            if was == S.TUMBLE and p.state == S.FOOT:
                got_up = w.tick
            if was == S.FOOT and p.state == S.TUMBLE:
                knocks += 1
                if got_up is not None:
                    self.assertGreaterEqual((w.tick - got_up) * DT, C.GETUP_GRACE - DT,
                                            "you get a moment to find your feet")
            was = p.state
        self.assertGreaterEqual(knocks, 1, "they do fight")
        self.assertLessEqual(close_max, 1, "one guard at a time; the rest wait their turn")


class TestSillyPolice(unittest.TestCase):
    def test_the_k9_unit_takes_your_trousers(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        dog = S.NPC(w.new_id(), S.DOG, p.x + 8, p.y)
        w.npcs[dog.id] = dog
        mult = p.speed_mult()
        for _ in range(int(3 / DT)):
            w.heat = 30
            w.step(DT)
            if p.pants_t > 0:
                break
        self.assertGreater(p.pants_t, 0)
        self.assertEqual(p.banner, S.BN_PANTSED)
        self.assertAlmostEqual(p.speed_mult(), mult * C.PANTSED_SPEED_MULT)
        self.assertEqual(dog.mode, 4, "off it goes, trousers and all")
        snap = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertTrue(snap.players[p.id][17] & P.PF2_PANTSED)

    def test_the_streaker_distracts_the_police(self):
        w = world()
        p = w.add_player("BRYCE")
        p.x, p.y = street(w)
        cop = S.Car(w.new_id(), S.COP, p.x + 20, p.y, math.pi, S.cop_loadout(w.rng))
        w.cars[cop.id] = cop
        w.heat = 50
        w.targets = w._collect_targets()
        self.assertEqual(w._witness_scan()[0], S.W_COP)
        nude = S.NPC(w.new_id(), S.STREAKER, cop.x + 5, cop.y)
        nude.ttl = 30
        w.npcs[nude.id] = nude
        self.assertNotEqual(w._witness_scan()[0], S.W_COP, "a naked man is more interesting than you")
        # tackle him: citizen's arrest
        cash, heat = w.cash, w.heat
        p.x, p.y = nude.x - 1.0, nude.y
        face(p, nude.x, nude.y)
        click(p)
        w.step(DT)
        self.assertEqual(w.cash, cash + C.STREAKER_REWARD)
        self.assertLess(w.heat, heat)

    def test_streakers_turn_up(self):
        w = world()
        w.add_player("BRYCE")
        for _ in range(200):        # each roll only samples 30 candidate tiles; keep rolling
            if any(n.kind == S.STREAKER for n in w.npcs.values()):
                break
            w.streaker_t = 0.01
            w.step(DT)
        self.assertTrue(any(n.kind == S.STREAKER for n in w.npcs.values()))

    def test_speed_cameras_post_you_a_ticket(self):
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        w._enter_car(p, car, S.DRIVER)
        x, y = street(w)
        cx, cy = x + 5, y + 6
        w.map.cameras = [(cx, cy)]
        car.x, car.y, car.ang = x, y, 0.0
        car.vx = C.SPEEDCAM_SPEED + 5
        cash = w.cash
        w.step(DT)
        self.assertEqual(w.cash, cash - C.SPEEDCAM_FINE)
        self.assertEqual(p.banner, S.BN_SMILE)
        w.step(DT)
        self.assertEqual(w.cash, cash - C.SPEEDCAM_FINE, "one flash per pass")

    def test_burnout_smoke_hides_you(self):
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        x, y = street(w)
        car.x, car.y, car.ang = x, y, 0.0
        w._enter_car(p, car, S.DRIVER)
        inp(p, buttons=S.B_UP | S.B_DOWN)
        step(w, C.SMOKE_SCREEN_AT + 1.0)
        clouds = [t for t in w.traps.values() if t.kind == S.TRAP_SMOKE]
        self.assertTrue(clouds, "a proper cloud")
        c = clouds[0]
        self.assertTrue(w._smoky(c.x - 10, c.y, c.x + 10, c.y))
        self.assertFalse(w._smoky(c.x - 10, c.y + 20, c.x + 10, c.y + 20))
        step(w, C.SMOKE_SCREEN_LIFE + 1.0)
        inp(p, buttons=0)
        w.step(DT)
        self.assertLessEqual(len([t for t in w.traps.values() if t.kind == S.TRAP_SMOKE]), C.SMOKE_SCREEN_MAX)

    def test_hydraulics_draw_a_crowd(self):
        w = world()
        p = w.add_player("BRYCE")
        car = w.cars[w.personal_id]
        x, y = street(w)
        car.x, car.y = x, y
        w._enter_car(p, car, S.DRIVER)
        n = S.NPC(w.new_id(), S.PED, x + 5, y + 4)
        n.turn_t = 1e9
        w.npcs[n.id] = n
        inp(p, buttons=S.B_HOP)
        w.step(DT)
        self.assertEqual(car.hop_t, 0.0, "no hydraulics fitted: nothing happens")
        car.hydraulics = True
        inp(p, buttons=0)
        w.step(DT)
        inp(p, buttons=S.B_HOP)
        w.step(DT)
        self.assertGreater(car.hop_t, 0)
        self.assertGreater(n.laugh_t, 0, "the crowd enjoys the show")
        row = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]).cars[car.id]
        self.assertTrue(row[20] & P.DR_HOP and row[20] & P.DR_HYDRO)


if __name__ == "__main__":
    unittest.main()

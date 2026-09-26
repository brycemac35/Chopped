"""v0.13: the main story (ten REP-gated chapters with written scenes), motorbikes and the
precinct's impound, and the pause menu's INSTRUCTIONS window."""

import math
import os
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import savefile as SF
from chopped import story as ST
from chopped import vehicles as V
from chopped import garage as G
from chopped.parts import SLOTS, SLOT_INDEX, Part


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


def toasts(w, color=None):
    return [e[3][1] for e in w.events if e[2] == 0 and (color is None or e[3][0] == color)]


def at_chapter(w, key, active=True):
    w.story_ch = ST.CHAPTER_KEYS.index(key)
    w.story_points = max(w.story_points, ST.chapter(w.story_ch).rep)
    w.story_active = active
    w.story_n, w.story_flags = 0, {}


def talk_to(w, p, key):
    npc = next(n for n in w.map.story_npcs if n[0] == key)
    w.talk_cd.clear()
    w._talk(p, npc[0], npc[1])


class FakeCar:
    def __init__(self, cid, copcar=False):
        self.id, self.copcar = cid, copcar


class TestStoryFlow(unittest.TestCase):
    def test_the_first_chapter_opens_with_a_scene_and_closes_with_one(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.step(1 / 60)
        self.assertEqual(w.story_status(), ST.ST_TALK)
        self.assertTrue(any("TALK TO PAIGE" in t for t in toasts(w)))
        talk_to(w, p, "paige")
        self.assertEqual(w.story_status(), ST.ST_ACTIVE)
        self.assertIn("B:opening_hours.start", toasts(w, S.T_STORY))
        cash = w.cash
        w._story_event("deliver", FakeCar(1), 0.0)
        self.assertEqual(w.story_ch, 1)
        self.assertEqual(w.cash, cash + ST.CHAPTERS[0].cash)
        self.assertIn("B:opening_hours.end", toasts(w, S.T_STORY))

    def test_the_rep_guard_rail(self):
        """A chapter won't open without the REP; the giver says how much more is owed."""
        w = quiet_world()
        p = w.add_player("ALICE")
        w.story_ch = ST.CHAPTER_KEYS.index("feel_the_heat")
        w.story_points = 2
        self.assertEqual(w.story_status(), ST.ST_LOCKED)
        talk_to(w, p, "fixer")
        self.assertFalse(w.story_active)
        self.assertTrue(any("4 MORE REP" in t for t in toasts(w, S.T_SAY)))
        w.story_points = 6
        self.assertEqual(w.story_status(), ST.ST_TALK)
        talk_to(w, p, "fixer")
        self.assertTrue(w.story_active)

    def test_the_story_never_hands_out_rep(self):
        w = quiet_world()
        w.add_player("ALICE")
        at_chapter(w, "opening_hours")
        rep = w.story_points
        w._story_event("deliver", FakeCar(1), 0.0)
        self.assertEqual(w.story_points, rep)

    def test_the_wrong_giver_does_their_usual_small_talk(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        talk_to(w, p, "fixer")                     # chapter 1 is Paige's
        self.assertFalse(w.story_active)
        self.assertFalse(toasts(w, S.T_STORY))


class TestObjectives(unittest.TestCase):
    def setUp(self):
        self.w = quiet_world()
        self.p = self.w.add_player("ALICE")

    def test_install(self):
        at_chapter(self.w, "tools")
        car = self.w.cars[self.w.player_car[self.p.id]]
        self.w.stash = [Part("whl_tuned_light", 1.0)]
        self.w._ms_install(self.p, car, 0, SLOT_INDEX["WheelFL"])
        self.assertEqual(self.w.story_ch, ST.CHAPTER_KEYS.index("tools") + 1)

    def test_talk_to_tommy(self):
        at_chapter(self.w, "word_on_the_street")
        talk_to(self.w, self.p, "tommy")
        self.assertEqual(self.w.story_ch, ST.CHAPTER_KEYS.index("word_on_the_street") + 1)
        self.assertIn("B:word_on_the_street.end", toasts(self.w, S.T_STORY))

    def test_carjack_then_deliver_that_car(self):
        w = self.w
        at_chapter(w, "moving_target")
        w._story_event("carjack", FakeCar(7))
        self.assertEqual(w.story_n, 1)
        w._story_event("deliver", FakeCar(8), 0.0)          # a different car doesn't count
        self.assertTrue(w.story_active)
        w._story_event("deliver", FakeCar(7), 0.0)
        self.assertFalse(w.story_active)

    def test_heat_up_then_lose_them_without_the_cuffs(self):
        w = self.w
        at_chapter(w, "feel_the_heat")
        w.heat = 55.0
        w._story_tick(0.1)
        self.assertEqual(w.story_n, 1)
        w._story_event("arrest")                             # busted: back to square one
        self.assertEqual(w.story_n, 0)
        w.heat = 55.0
        w._story_tick(0.1)
        w.heat = 0.0
        w._story_tick(0.1)
        self.assertEqual(w.story_ch, ST.CHAPTER_KEYS.index("feel_the_heat") + 1)

    def test_already_owning_tommys_lot_finishes_the_takeover_on_the_spot(self):
        w = self.w
        at_chapter(w, "hostile_takeover", active=False)
        tier1 = next(i for i in range(1, len(w.shop_owned)) if w.map.fence_shops[i - 1]["tier"] == 1)
        w.shop_owned[tier1] = True
        talk_to(w, self.p, "fixer")
        self.assertEqual(w.story_ch, ST.CHAPTER_KEYS.index("hostile_takeover") + 1)

    def test_buying_the_lot(self):
        w = self.w
        at_chapter(w, "hostile_takeover")
        tier1 = next(i for i in range(1, len(w.shop_owned)) if w.map.fence_shops[i - 1]["tier"] == 1)
        w.cash = C.SHOP_PRICE[tier1] + 10
        w._buy_shop(tier1)
        self.assertEqual(w.story_ch, ST.CHAPTER_KEYS.index("hostile_takeover") + 1)

    def test_breakout_needs_an_arrest_and_no_bail(self):
        w = self.w
        at_chapter(w, "inside_job")
        w._story_event("breakout")                           # (not arrested yet: nothing to break out of)
        self.assertTrue(w.story_active)
        w._story_event("arrest")
        w._story_event("bail")
        self.assertEqual(w.story_n, 0)
        w._story_event("arrest")
        w._story_event("breakout")
        self.assertFalse(w.story_active)

    def test_a_real_jailbreak_counts(self):
        w = self.w
        at_chapter(w, "inside_job")
        w.arrest(self.p)
        for _ in range(int(60 * (C.CUFFED_TIME + 0.5))):
            w.step(1 / 60)
        self.assertTrue(self.p.jailed)
        x0, y0, x1, y1 = w.map.precinct_outer
        self.p.x, self.p.y = x1 + 3, (y0 + y1) / 2
        w.step(1 / 60)
        self.assertEqual(w.story_ch, ST.CHAPTER_KEYS.index("inside_job") + 1)

    def test_cop_car(self):
        w = self.w
        at_chapter(w, "blue_lights")
        w._story_event("steal", FakeCar(3, copcar=False))
        self.assertEqual(w.story_n, 0)
        w._story_event("steal", FakeCar(4, copcar=True))
        w._story_event("deliver", FakeCar(4), 0.0)
        self.assertFalse(w.story_active)

    def test_three_before_midnight(self):
        w = self.w
        at_chapter(w, "audition")
        w._story_event("deliver", FakeCar(1), 0.0)
        w._story_event("deliver", FakeCar(2), 0.0)
        w._rotate_quests()                                   # midnight
        self.assertEqual(w.story_n, 0)
        for cid in (3, 4, 5):
            w._story_event("deliver", FakeCar(cid), 0.0)
        self.assertFalse(w.story_active)

    def test_the_finale_wants_it_hot_and_then_the_story_is_over(self):
        w = self.w
        at_chapter(w, "the_big_one")
        w._story_event("deliver", FakeCar(1), 60.0)
        self.assertTrue(w.story_active)
        w._story_event("deliver", FakeCar(2), 80.0)
        self.assertEqual(w.story_status(), ST.ST_DONE)
        self.assertIn(ST.THE_END, toasts(w))
        talk_to(w, self.p, "kingpin")                        # small talk from here on, no crash
        self.assertEqual(w.story_status(), ST.ST_DONE)


class TestStoryData(unittest.TestCase):
    def test_every_chapter_has_both_scenes_and_a_real_giver(self):
        keys = {n[0] for n in quiet_world().map.story_npcs}
        for ch in ST.CHAPTERS:
            self.assertIn(ch.key + ".start", ST.BEATS)
            self.assertIn(ch.key + ".end", ST.BEATS)
            self.assertIn(ch.giver, keys)
        reps = [ch.rep for ch in ST.CHAPTERS]
        self.assertEqual(reps, sorted(reps), "the REP bars only go up")

    def test_every_line_can_be_drawn_and_every_toast_fits(self):
        import pygame                                        # (art needs it; this is a client check)
        from chopped.art import GLYPHS
        chars = set()
        for lines in ST.BEATS.values():
            for speaker, text in lines:
                chars |= set(speaker + text)
        missing = sorted(c for c in chars if c != " " and c.upper() not in GLYPHS)
        self.assertEqual(missing, [], "the pixel font has no glyph for these")
        for ch in ST.CHAPTERS:
            self.assertLessEqual(len("NEW STORY CHAPTER: %s. TALK TO %s." % (ch.title, ST.GIVERS[ch.giver])), 60)
            self.assertLessEqual(len("B:" + ch.key + ".start"), 60)


class TestStoryPersistence(unittest.TestCase):
    def test_wire(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        at_chapter(w, "feel_the_heat")
        w.story_n = 1
        s = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertEqual((s.story_ch, s.story_st, s.story_n),
                         (ST.CHAPTER_KEYS.index("feel_the_heat"), ST.ST_ACTIVE, 1))

    def test_save_keeps_the_chapter(self):
        w = quiet_world()
        w.add_player("ALICE")
        at_chapter(w, "blue_lights")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            SF.save_to(w, path)
            self.assertEqual(SF.peek(path)["story_ch"], ST.CHAPTER_KEYS.index("blue_lights"))
            w2 = quiet_world()
            self.assertTrue(SF.load_into(w2, path))
        self.assertEqual(w2.story_ch, ST.CHAPTER_KEYS.index("blue_lights"))
        self.assertTrue(w2.story_active)


class TestBikes(unittest.TestCase):
    def test_a_bike_has_two_wheels_and_none_missing(self):
        import random
        from chopped.parts import model_loadout, wheel_slots
        for mid in V.BIKES:
            parts = model_loadout(random.Random(3), mid)
            self.assertEqual(wheel_slots(mid), ("WheelFL", "WheelRL"))
            car = S.Car(1, S.CIV, 0, 0, 0.0, parts, model=mid)
            self.assertEqual(car.missing_wheels(), 0)
            self.assertIsNone(parts["DoorL"])
        self.assertGreater(V.model(V.SPORTBIKE).top, C.COP_TOP_SPEED, "the sports bike outruns cops")
        self.assertEqual(V.model(V.SPORTBIKE).traffic_weight, 0)

    def test_a_bike_is_quick_off_the_line(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        bike = next(c for c in w.cars.values() if c.special == "impound")
        w._enter_car(p, bike, S.DRIVER)
        for _ in range(60):
            w.set_input(p.id, S.InputState(S.B_UP, 0, 0, 0, 0.0, 0, 0))
            w.step(1 / 60)
        self.assertEqual(p.state, S.DRIVER)
        self.assertGreater(bike.speed(), 10.0)

    def test_you_come_off_a_bike_at_a_bump_a_car_shrugs_off(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        bike = next(c for c in w.cars.values() if c.special == "impound")
        w._enter_car(p, bike, S.DRIVER)
        w._crash(bike, (C.BIKE_EJECT_DV + C.CRASH_EJECT_DV) / 2, 1.0, 0.0)
        self.assertEqual(p.state, S.TUMBLE)
        self.assertTrue(any("HANDLEBARS" in t for t in toasts(w)))
        q = w.add_player("BOB")
        car = w.cars[w.player_car[q.id]]
        w._enter_car(q, car, S.DRIVER)
        w._crash(car, (C.BIKE_EJECT_DV + C.CRASH_EJECT_DV) / 2, 1.0, 0.0)
        self.assertEqual(q.state, S.DRIVER)

    def test_no_doors_on_a_bike(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        bike = next(c for c in w.cars.values() if c.special == "impound")
        w.stash = [Part("door_stock", 1.0)]
        w._ms_install(p, bike, 0, SLOT_INDEX["DoorL"])
        self.assertIsNone(bike.parts["DoorL"])
        self.assertEqual(len(w.stash), 1)


class TestImpound(unittest.TestCase):
    def test_bikes_wait_outside_the_precinct_with_the_keys_in(self):
        w = quiet_world()
        bikes = [c for c in w.cars.values() if c.special == "impound"]
        self.assertEqual(len(bikes), len(w.map.bike_spots))
        self.assertGreaterEqual(len(bikes), 3)
        for b in bikes:
            self.assertTrue(V.is_bike(b.model))
            self.assertEqual(b.state, S.RUNNING)
            self.assertFalse(b.stolen)
            self.assertFalse(w.map.in_precinct(b.x, b.y), "outside the walls, not in the lockup")

    def test_taking_one_is_a_theft_and_it_gets_restocked_out_of_sight(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        bike = next(c for c in w.cars.values() if c.special == "impound")
        spot = min(w.map.bike_spots, key=lambda s: math.hypot(s[0] - bike.x, s[1] - bike.y))
        heat = w.heat
        w._enter_car(p, bike, S.DRIVER)
        self.assertTrue(bike.stolen)
        self.assertGreaterEqual(w.heat, heat + C.HEAT_BREAKIN - 0.01)
        self.assertIsNone(bike.special)
        bike.x += 200.0                                      # ridden off
        p.x, p.y = spot[0] + 5, spot[1]                     # ...but somebody's standing right there
        w.impound_t = 0.0
        w._impound_bikes(0.1)
        near = [c for c in w.cars.values() if c.special == "impound" and
                math.hypot(c.x - spot[0], c.y - spot[1]) < 1.0]
        self.assertEqual(near, [], "never pops in while someone's watching")
        p.x, p.y = spot[0] + 200, spot[1]
        w.impound_t = 0.0
        w._impound_bikes(0.1)
        near = [c for c in w.cars.values() if c.special == "impound" and
                math.hypot(c.x - spot[0], c.y - spot[1]) < 1.0]
        self.assertEqual(len(near), 1)

    def test_far_off_impound_bikes_arent_sent(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        s = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        imp = {c.id for c in w.cars.values() if c.special == "impound"}
        self.assertFalse(imp & set(s.cars), "the shop is miles from the precinct")
        p.x, p.y = w.map.bike_spots[0][0], w.map.bike_spots[0][1] + 3
        s = P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:])
        self.assertTrue(imp & set(s.cars))


class TestPauseMenu(unittest.TestCase):
    def test_instructions_live_behind_a_button(self):
        import pygame
        pygame.init()
        pygame.display.set_mode((64, 64))
        from chopped.art import PixelFont
        from chopped.doomhud import DoomHud
        from chopped.mapgen import CityMap
        from chopped.render import Renderer
        r = Renderer(CityMap(4242))
        hud = DoomHud(PixelFont(), r.bank, r.minimap)
        low = pygame.Surface((C.LOW_W, C.LOW_H))
        hud.draw_pause(low, {"lines": [], "help": False, "mouse": None})
        self.assertEqual(set(hud.pause_rects), {"resume", "help", "leave"})
        centre = hud.pause_rects["help"].center
        self.assertEqual(hud.pause_hit(centre), "help")
        hud.draw_pause(low, {"lines": [], "help": True, "mouse": None})
        self.assertEqual(set(hud.pause_rects), {"back"})


if __name__ == "__main__":
    unittest.main()

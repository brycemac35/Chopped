"""v0.19 jobs/world half: impound wrecks, sporty + SLIM heat, SMOOTH's trim, Heat Run needs heat,
story part rewards, no two-player jobs for a solo crew, Engine Pull vs the dolly."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import vehicles as V
from chopped import story as ST
from chopped.characters import CHARACTERS, stat
from chopped.parts import Part
from chopped.quests import NEEDS_CREW, QUEST_ORDER
from tests.test_quests import quiet_world, only_quest, civ_cars, deliver, step

SLIM, SMOOTH = 2, 3


def model_car(w, mid):
    car = next(c for c in civ_cars(w))
    car.model = mid
    car.special = None
    return car


class TestImpound(unittest.TestCase):
    def test_restock_is_slow(self):
        self.assertEqual(C.IMPOUND_RESTOCK, 75.0)

    def test_impound_bikes_are_worn_but_run(self):
        w = quiet_world()
        bike = w._spawn_impound_bike(0, 10.0, 10.0, 0.0)
        for part in bike.parts.values():
            if part is not None:
                self.assertLessEqual(part.condition, C.IMPOUND_WEAR + 1e-9)
        self.assertEqual(bike.state, S.RUNNING)
        self.assertEqual(bike.special, "impound")


class TestSportyAndSlim(unittest.TestCase):
    def _heat_of_break_in(self, char, mid):
        w = quiet_world()
        p = w.add_player("X", char)
        car = model_car(w, mid)
        w.heat = 0.0
        w._break_in(p, car)
        return w.heat, car

    def test_sporty_costs_double(self):
        base, _ = self._heat_of_break_in(0, V.KEI)
        hot, _ = self._heat_of_break_in(0, V.COUPE)
        self.assertAlmostEqual(base, C.HEAT_BREAKIN)
        self.assertAlmostEqual(hot, C.HEAT_BREAKIN * C.SPORTY_HEAT_MULT)

    def test_slim_halves_and_is_silent_and_stacks(self):
        h, car = self._heat_of_break_in(SLIM, V.KEI)
        self.assertAlmostEqual(h, C.HEAT_BREAKIN * 0.5)
        self.assertFalse(car.alarm)
        h2, _ = self._heat_of_break_in(SLIM, V.COUPE)
        self.assertAlmostEqual(h2, C.HEAT_BREAKIN * C.SPORTY_HEAT_MULT * 0.5)

    def test_others_still_ring_the_alarm(self):
        _, car = self._heat_of_break_in(0, V.KEI)
        self.assertTrue(car.alarm)

    def test_carjack_heat_scales(self):
        w = quiet_world()
        p = w.add_player("X", SLIM)
        car = model_car(w, V.COUPE)
        self.assertAlmostEqual(w.theft_heat(p, car, C.CARJACK_HEAT), C.CARJACK_HEAT * C.SPORTY_HEAT_MULT * 0.5)

    def test_prompt_and_inspect_flag_hint_hot(self):
        w = quiet_world()
        self.assertIn("HOT", w._hot_hint(model_car(w, V.MUSCLE)))
        self.assertEqual(w._hot_hint(model_car(w, V.KEI)), "")
        self.assertTrue(w.appraise(model_car(w, V.RICE))[6] & S.INSP_HOT)

    def test_character_text_and_smooth(self):
        self.assertEqual(stat(SMOOTH, "sale_bonus"), 1.10)
        for c in CHARACTERS:
            self.assertLessEqual(len(c["perk"]), 40)
            self.assertLessEqual(len(c["blurb"]), 60)
            self.assertEqual(c["perk"], c["perk"].upper())


class TestHeatRunNeedsHeat(unittest.TestCase):
    def test_quiet_delivery_pays_nothing(self):
        w = quiet_world()
        only_quest(w, "heat_run")
        p = w.add_player("A")
        car = model_car(w, V.KEI)
        w._break_in(p, car)
        w.heat = 10.0
        step(w, 1.0)
        deliver(w, car)
        self.assertNotIn("heat_run", w.quest_done_today)

    def test_heat_then_delivery_pays_and_rotation_resets(self):
        w = quiet_world()
        only_quest(w, "heat_run")
        p = w.add_player("A")
        car = model_car(w, V.KEI)
        w._break_in(p, car)
        w.heat = C.HEAT_RUN_MIN_HEAT + 1
        step(w, 0.5)
        w.heat = 0.0
        step(w, 0.5)
        deliver(w, car)
        self.assertIn("heat_run", w.quest_done_today)
        from chopped.quests import QUESTS
        self.assertIn("40", QUESTS["heat_run"][1])


class TestStoryRewards(unittest.TestCase):
    def test_about_four_chapters_reward_locker_parts(self):
        rewarded = [c for c in ST.CHAPTERS if c.reward]
        self.assertGreaterEqual(len(rewarded), 4)
        from chopped.parts import PART_DEFS
        for c in rewarded:
            for tid in c.reward:
                self.assertIn(tid, PART_DEFS)

    def test_completing_a_rewarded_chapter_fills_the_locker_not_rep(self):
        w = quiet_world()
        w.story_ch = ST.CHAPTER_KEYS.index("moving_target")
        w.story_active = True
        rep, cash, n = w.story_points, w.cash, len(w.stash)
        w._story_complete()
        self.assertEqual(w.stash[-1].type_id, "ecu_tuned")
        self.assertEqual(len(w.stash), n + 1)
        self.assertEqual(w.story_points, rep)
        self.assertGreater(w.cash, cash)

    def test_full_locker_overflows_to_the_floor(self):
        w = quiet_world()
        w.stash = [Part("ecu_stock") for _ in range(C.STASH_MAX)]
        w.story_ch = ST.CHAPTER_KEYS.index("moving_target")
        w.story_active = True
        pickups = len(w.pickups)
        w._story_complete()
        self.assertEqual(len(w.stash), C.STASH_MAX)
        self.assertEqual(len(w.pickups), pickups + 1)


class TestSoloJobs(unittest.TestCase):
    def test_solo_never_gets_crew_jobs(self):
        w = quiet_world()
        w.story_points = 99
        for _ in range(60):
            w._rotate_quests()
            self.assertFalse(set(w.today_quests) & NEEDS_CREW)

    def test_two_players_can_get_them(self):
        w = quiet_world()
        w.story_points = 99
        w.add_player("A")
        w.add_player("B")
        seen = set()
        for _ in range(200):
            w._rotate_quests()
            seen |= set(w.today_quests)
        self.assertTrue(seen & NEEDS_CREW)
        self.assertTrue(NEEDS_CREW <= set(QUEST_ORDER))


class TestEnginePull(unittest.TestCase):
    def _delivered(self, engine_id):
        w = quiet_world()
        only_quest(w, "engine_pull")
        p = w.add_player("A")
        car = model_car(w, V.KEI)
        car.parts["Engine"] = Part(engine_id)
        w._break_in(p, car)
        toasts = []
        w.toast = lambda text, *a, **k: toasts.append(text)
        deliver(w, car)
        return w, toasts

    def test_v8_on_stock_dolly_isnt_accepted_and_says_so(self):
        w, toasts = self._delivered("eng_v8_5_7")
        self.assertNotIn("delivered_with_engine", w._q("engine_pull"))
        self.assertTrue(any("MO" in t for t in toasts))

    def test_liftable_engine_is_accepted(self):
        w, _ = self._delivered("eng_stock_1_6")
        self.assertIn("delivered_with_engine", w._q("engine_pull"))

    def test_refusal_names_the_dolly_and_mo(self):
        w = quiet_world()
        msg = w.dolly_refusal(Part("eng_v8_5_7"))
        self.assertIn("TOO SMALL", msg)
        self.assertIn("MO", msg)


if __name__ == "__main__":
    unittest.main()

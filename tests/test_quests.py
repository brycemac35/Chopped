"""Daily jobs and the story-point arc, ported from a Unity design doc onto
what Chopped actually has: no quest board, no "start" button -- all 3 of
today's jobs track passively off whatever you're already doing."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import protocol as P
from chopped import vehicles as V
from chopped.quests import QUESTS, QUEST_ORDER, ACT_THRESHOLDS
from chopped.parts import Part

DT = 1.0 / C.SIM_HZ


def step(w, secs):
    for _ in range(int(round(secs * C.SIM_HZ))):
        w.step(DT)


def quiet_world(seed=4242):
    w = S.World(map_seed=seed, rng_seed=1)
    w.npcs.clear()
    w.map.cameras = []
    w.traffic_target = 0
    w.patrol_target = 0
    return w


def only_quest(w, qid):
    """Pin today's jobs to just one, so a test's assertions can't be thrown
    off by whichever other two the daily RNG happened to pick."""
    w.today_quests = [qid]
    w.quest_progress = {qid: {}}
    w.quest_done_today = set()


def civ_cars(w):
    return [c for c in w.cars.values() if c.kind == S.CIV]


def road_point(w):
    bx, by, _ = w.map.bays[0]
    gx, gy, gw, gh = w.map.garage_rect
    return bx, gy + gh + 10.0


def deliver(w, car):
    gx, gy, gw, gh = w.map.garage_rect
    car.x, car.y = gx + gw / 2, gy + gh / 2
    car.vx = car.vy = car.w = 0.0
    step(w, 0.2)


class TestRotationAndActs(unittest.TestCase):
    def test_today_has_up_to_three_unlocked_jobs(self):
        w = quiet_world()
        self.assertLessEqual(len(w.today_quests), 3)
        for qid in w.today_quests:
            self.assertLessEqual(QUESTS[qid][5], w.story_points)

    def test_a_locked_job_never_turns_up_before_its_story_points(self):
        w = quiet_world()
        w.story_points = 0
        for _ in range(30):
            w._rotate_quests()
            for qid in w.today_quests:
                self.assertEqual(QUESTS[qid][5], 0, "only the 0-point jobs should show up yet")

    def test_story_points_move_you_through_the_acts(self):
        w = quiet_world()
        self.assertEqual(w.act, 1)
        w.story_points = ACT_THRESHOLDS[0]
        w._check_act_up()
        self.assertEqual(w.act, 2)
        w.story_points = ACT_THRESHOLDS[1]
        w._check_act_up()
        self.assertEqual(w.act, 3)
        self.assertFalse(w.campaign_won)
        w.story_points = ACT_THRESHOLDS[2]
        w._check_act_up()
        self.assertTrue(w.campaign_won)
        self.assertEqual(w.act, 3, "victory is inside act III, not a 4th act")

    def test_a_new_day_rotates_the_jobs(self):
        w = quiet_world()
        w.add_player("ALICE")
        before = list(w.today_quests)
        w.day_t = 0.1
        step(w, 0.2)
        self.assertEqual(w.day, 2)
        # (rotation is random -- what matters is it actually re-rolled, tracked fresh)
        self.assertEqual(w.quest_done_today, set())
        for qid in w.today_quests:
            # heat_run ticks its clock unconditionally (no specific car to wait for), so its
            # tracker isn't literally {} the instant a tick runs -- every other job's is,
            # since none of them have anything to track until you actually engage them.
            self.assertNotIn("car", w.quest_progress[qid])


class TestHotwireSpecial(unittest.TestCase):
    def test_steal_a_kei_deliver_clean_under_40_heat(self):
        w = quiet_world()
        only_quest(w, "hotwire_special")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.model = V.KEI
        car.special = None
        car.state = S.LOCKED
        w._break_in(p, car)
        self.assertIn("car", w.quest_progress["hotwire_special"])
        cash0 = w.cash
        deliver(w, car)
        self.assertIn("hotwire_special", w.quest_done_today)
        self.assertEqual(w.cash, cash0 + QUESTS["hotwire_special"][3])
        self.assertEqual(w.story_points, QUESTS["hotwire_special"][4])

    def test_fails_if_heat_reaches_40(self):
        w = quiet_world()
        only_quest(w, "hotwire_special")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.model = V.KEI
        car.special = None
        w._break_in(p, car)
        w.heat = 40.0
        step(w, 0.1)
        self.assertEqual(w.quest_progress["hotwire_special"], {})
        self.assertNotIn("hotwire_special", w.quest_done_today)

    def test_a_sedan_doesnt_count(self):
        w = quiet_world()
        only_quest(w, "hotwire_special")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.model = V.SEDAN
        car.special = None
        w._break_in(p, car)
        self.assertEqual(w.quest_progress["hotwire_special"], {}, "only a Kei should arm this job")


class TestPartCollector(unittest.TestCase):
    def test_three_one_handed_strips_completes_it(self):
        w = quiet_world()
        only_quest(w, "part_collector")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        for i, slot in enumerate(("WheelFL", "WheelFR", "WheelRL")):
            w._strip(p, car, slot)
            p.hands = []            # (one-handed parts: strip and drop each time)
            if i < 2:
                self.assertNotIn("part_collector", w.quest_done_today)
        self.assertIn("part_collector", w.quest_done_today)
        self.assertEqual(w.cash, C.START_CASH + QUESTS["part_collector"][3])

    def test_a_two_handed_part_doesnt_count(self):
        w = quiet_world()
        only_quest(w, "part_collector")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        w._strip(p, car, "Hood")            # two hands
        self.assertEqual(w.quest_progress["part_collector"], {})


class TestHeatRun(unittest.TestCase):
    def test_delivering_over_60_heat_for_too_long_doesnt_complete_it(self):
        w = quiet_world()
        only_quest(w, "heat_run")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.special = None
        w._break_in(p, car)
        w.heat = 61.0
        step(w, 20.5)                    # comfortably over the 20s grace
        deliver(w, car)
        self.assertNotIn("heat_run", w.quest_done_today, "too hot for too long should not pay out")

    def test_a_later_calmer_delivery_still_completes_it(self):
        """A blown attempt isn't a permanent lock -- once heat's back down, the next
        delivery gets an honest shot (this was a real bug: the first version tied the
        job to whichever car got delivered first, and never let go of it after)."""
        w = quiet_world()
        only_quest(w, "heat_run")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.special = None
        w._break_in(p, car)
        w.heat = 61.0
        step(w, 20.5)
        w.heat = 0.0
        step(w, 1.0)                     # over_t decays back to 0 once heat's down
        deliver(w, car)
        self.assertIn("heat_run", w.quest_done_today)


class TestArrestsFailJobs(unittest.TestCase):
    def test_getting_busted_fails_night_job(self):
        w = quiet_world()
        only_quest(w, "night_job")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.special = None
        w._break_in(p, car)
        self.assertIn("car", w.quest_progress["night_job"])
        w.arrest(p)
        self.assertEqual(w.quest_progress["night_job"], {})
        self.assertNotIn("night_job", w.quest_done_today)


class TestPerfectSteal(unittest.TestCase):
    def test_a_crash_ends_it(self):
        w = quiet_world()
        only_quest(w, "perfect_steal")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.special = None
        w._break_in(p, car)
        car.damage = 1
        step(w, 0.1)
        self.assertEqual(w.quest_progress["perfect_steal"], {})

    def test_undamaged_delivery_completes_it(self):
        w = quiet_world()
        only_quest(w, "perfect_steal")
        p = w.add_player("ALICE")
        car = civ_cars(w)[0]
        car.special = None
        w._break_in(p, car)
        deliver(w, car)
        self.assertIn("perfect_steal", w.quest_done_today)


class TestWireFormat(unittest.TestCase):
    def test_todays_quests_and_story_points_survive_the_wire(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        w.story_points = 7
        w.act = 2
        only_quest(w, "heat_run")
        w.quest_done_today = {"heat_run"}
        raw = P.encode_snapshot(w, p.id, 0, 0)
        s = P.decode_snapshot(raw[P.HDR.size:])
        self.assertEqual(s.story_points, 7)
        self.assertEqual(s.act, 2)
        self.assertEqual(QUEST_ORDER[s.today_quests[0]], "heat_run")
        self.assertEqual(s.quest_done, 1)

    def test_worst_case_snapshot_with_quests_still_fits(self):
        w = quiet_world()
        for i in range(4):
            w.add_player("P%d" % i)
        w.story_points = 25
        raw = P.encode_snapshot(w, 1, 0, 0)
        self.assertLessEqual(len(raw), C.MAX_PACKET)


class TestQuestsInSaveFile(unittest.TestCase):
    def test_reputation_and_completed_ever_persist_but_todays_rotation_doesnt(self):
        from chopped import savefile as SF
        w = quiet_world()
        w.story_points = 9
        w.act = 2
        w.completed_ever = {"hotwire_special", "part_collector"}
        old_today = list(w.today_quests)
        data = SF.dump(w)
        self.assertEqual(data["story_points"], 9)
        self.assertEqual(data["act"], 2)
        self.assertIn("hotwire_special", data["completed_ever"])
        self.assertNotIn("today_quests", data)

        w2 = quiet_world(seed=999)
        self.assertTrue(SF.apply(w2, data))
        self.assertEqual(w2.story_points, 9)
        self.assertEqual(w2.act, 2)
        self.assertIn("part_collector", w2.completed_ever)
        for qid in w2.today_quests:
            self.assertLessEqual(QUESTS[qid][5], 9, "rotation should reflect the loaded story points")


if __name__ == "__main__":
    unittest.main()

"""v0.18.2 server-side fixes: no saving the seized assets, the mod shop's stale locker index,
SWITCH CAR saying why not, story/Night Job chapters that survive their car being towed."""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chopped import config as C
from chopped import sim as S
from chopped import garage as G
from chopped import savefile as SF
from chopped import vehicles as V
from chopped.parts import Part, SLOTS, PART_INDEX
from tests.test_garage import quiet_world as garage_world, menu, in_shop
from tests.test_quests import quiet_world, only_quest, civ_cars
from tests.test_v013 import toasts, at_chapter


def seized_server(path):
    from chopped.net import Server
    srv = Server(port=0, bind_host="127.0.0.1", map_seed=31337, save_path=path)
    w = srv.world
    w.add_player("ALICE")
    w.cash = 777
    w.stash.append(Part("exh_tuned", 1.0))
    w.gameover_t = C.GAMEOVER_BANNER          # the SHOP SEIZED banner is up
    return srv


class TestNoSavingSeizedAssets(unittest.TestCase):
    def test_manual_save_mid_banner_is_skipped_with_a_toast(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            srv = seized_server(path)
            srv.save_now()
            srv.pump()
            self.assertFalse(os.path.exists(path))
            self.assertTrue(any("NO SAVING" in t for t in toasts(srv.world)))
            srv.sock.close()

    def test_autosave_mid_banner_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            srv = seized_server(path)
            srv.pump()
            srv._next_save = 0.0
            srv.pump()
            self.assertFalse(os.path.exists(path))
            srv.sock.close()

    def test_quitting_mid_banner_saves_the_new_run_not_the_assets(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            srv = seized_server(path)
            srv.stop()
            w2 = S.World(map_seed=31337)
            self.assertTrue(SF.load_into(w2, path))
            self.assertEqual(w2.cash, C.START_CASH)
            self.assertEqual(w2.stash, [])
            self.assertEqual(w2.day, 1)


class TestInstallStaleIndex(unittest.TestCase):
    def _setup(self):
        w = garage_world()
        p = w.add_player("BRYCE")
        in_shop(w, p)
        w.stash[:] = [Part("exh_stock", 1.0), Part("exh_tuned", 1.0)]
        return w, p, w.cars[w.player_car[p.id]]

    def test_pack_roundtrip_covers_every_part_and_slot(self):
        for tid, idx in PART_INDEX.items():
            for si in range(len(SLOTS)):
                a, b = G.pack_install(39, si, tid)
                self.assertTrue(0 <= a < 256 and 0 <= b < 256)
                self.assertEqual(G.unpack_install(a, b), (39, si, idx))

    def test_legacy_encoding_still_means_no_type_check(self):
        si = SLOTS.index("Exhaust")
        self.assertEqual(G.unpack_install(3, si), (3, si, None))

    def test_stale_index_fits_nothing(self):
        w, p, car = self._setup()
        si = SLOTS.index("Exhaust")
        # the player chose the tuned exhaust at index 1, then the locker shuffled: index 1 is
        # something else now (the old code fitted whatever sat there)
        a, b = G.pack_install(1, si, "exh_tuned")
        w.stash[:] = [Part("exh_tuned", 1.0), Part("exh_stock", 1.0)]
        before = car.parts[SLOTS[si]]
        menu(p, G.OP_INSTALL, a, b)
        w.step(1 / 60)
        self.assertIs(car.parts[SLOTS[si]], before)
        self.assertEqual(len(w.stash), 2)

    def test_the_part_you_chose_still_fits(self):
        w, p, car = self._setup()
        a, b = G.pack_install(1, SLOTS.index("Exhaust"), "exh_tuned")
        menu(p, G.OP_INSTALL, a, b)
        w.step(1 / 60)
        self.assertEqual(car.parts["Exhaust"].type_id, "exh_tuned")

    def test_double_enter_cannot_fit_a_second_part(self):
        w, p, car = self._setup()
        a, b = G.pack_install(0, SLOTS.index("Exhaust"), "exh_stock")
        menu(p, G.OP_INSTALL, a, b)
        w.step(1 / 60)
        menu(p, G.OP_INSTALL, a, b)      # the same stale command: index 0 is the tuned one now
        w.step(1 / 60)
        self.assertEqual(car.parts["Exhaust"].type_id, "exh_stock")
        self.assertIn("exh_tuned", [x.type_id for x in w.stash])    # never fitted, never lost


class TestSwitchSaysWhy(unittest.TestCase):
    def _cars(self):
        w = garage_world()
        p = w.add_player("ALICE")
        gx, gy, gw, gh = w.map.garage_rect
        new = S.Car(w.new_id(), S.CIV, gx + gw / 2, gy + gh / 2, 0.0, {s: None for s in SLOTS}, model=V.MUSCLE)
        new.state = S.DELIVERED
        w.cars[new.id] = new
        return w, p, w.cars[w.player_car[p.id]], new

    def _refused(self, w, p, old, new, needle):
        w.events.clear()
        w._ms_switch(p, old, new.id)
        self.assertIs(w.cars[w.player_car[p.id]], old)
        self.assertTrue(any(needle in t for t in toasts(w)), toasts(w))

    def test_under_the_hammer(self):
        w, p, old, new = self._cars()
        new.lot = True
        self._refused(w, p, old, new, "HAMMER")

    def test_sold(self):
        w, p, old, new = self._cars()
        new.sale = ("someone", 100, 100)
        self._refused(w, p, old, new, "SOLD")

    def test_not_fully_in_the_shop(self):
        w, p, old, new = self._cars()
        new.x, new.y = 5.0, 5.0
        self._refused(w, p, old, new, "NOT FULLY IN THE SHOP")

    def test_not_delivered(self):
        w, p, old, new = self._cars()
        new.state = S.RUNNING
        self._refused(w, p, old, new, "DELIVERED")


class TestStoryCarGone(unittest.TestCase):
    def _tracked(self, key, copcar=False):
        w = quiet_world()
        w.add_player("ALICE")
        at_chapter(w, key)
        car = civ_cars(w)[0]
        car.copcar = copcar
        w._story_event("steal" if copcar else "carjack", car)
        self.assertEqual(w.story_n, 1)
        return w, car

    def test_moving_target_resets_when_the_car_is_towed(self):
        w, car = self._tracked("moving_target")
        del w.cars[car.id]
        w.events.clear()
        w._story_tick(1 / 60)
        self.assertEqual(w.story_n, 0)
        self.assertTrue(w.story_active)
        self.assertTrue(any("GOT TOWED" in t for t in toasts(w)))

    def test_blue_lights_resets_when_the_cop_car_is_gone(self):
        w, car = self._tracked("blue_lights", copcar=True)
        del w.cars[car.id]
        w._story_tick(1 / 60)
        self.assertEqual(w.story_n, 0)

    def test_the_new_car_counts_after_a_reset(self):
        w, car = self._tracked("moving_target")
        del w.cars[car.id]
        w._story_tick(1 / 60)
        other = civ_cars(w)[0]
        w._story_event("carjack", other)
        self.assertEqual(w.story_flags["car"], other.id)

    def test_a_live_car_is_left_alone(self):
        w, car = self._tracked("moving_target")
        w._story_tick(1 / 60)
        self.assertEqual(w.story_n, 1)


class TestNightJobCarGone(unittest.TestCase):
    def test_a_lost_car_blows_the_job_and_the_next_steal_rearms_it(self):
        w = quiet_world()
        p = w.add_player("ALICE")
        only_quest(w, "night_job")
        a, b = civ_cars(w)[:2]
        w._quest_on_steal(p, a)
        self.assertEqual(w.quest_progress["night_job"]["car"], a.id)
        del w.cars[a.id]
        w.events.clear()
        w._quest_tick(1 / 60)
        self.assertEqual(w.quest_progress["night_job"], {})
        self.assertTrue(any("JOB BLOWN" in t for t in toasts(w)))
        w._quest_on_steal(p, b)
        self.assertEqual(w.quest_progress["night_job"]["car"], b.id)




class TestModShopCursorHoldsItsRow(unittest.TestCase):
    """(v0.18.2) buying an engine put the old one in the locker, a LOCKER row slid in above the
    highlight, and a second Enter swapped the new engine straight back out."""

    def test_highlight_follows_the_row_after_a_buy(self):
        from chopped import protocol as P
        from chopped import modshop as MS
        w = garage_world()
        p = w.add_player("BRYCE")
        w.cash = 5000
        in_shop(w, p)

        def snap():
            return P.decode_snapshot(P.encode_snapshot(w, p.id, 0, 0)[P.HDR.size:]).menu

        shop = MS.ModShop(None)
        shop.sync(snap())
        shop.cat = next(i for i, c in enumerate(MS.CATS) if c[2] == "Engine")
        shop.focus = 1
        items = shop.items()
        shop.item = next(i for i, it in enumerate(items) if it.op == G.OP_BUY)
        label = items[shop.item].label
        it = items[shop.item]
        menu(p, it.op, it.a, it.b)
        w.step(1.0 / C.SIM_HZ if hasattr(C, "SIM_HZ") else 1.0 / 60)
        shop.sync(snap())
        now = shop.items()
        self.assertTrue(any(x.label.startswith("LOCKER:") for x in now), "the old engine went in the locker")
        self.assertEqual(now[shop.item].label, label, "the highlight stayed on the row that was bought")


if __name__ == "__main__":
    unittest.main()

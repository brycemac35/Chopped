"""(v0.19) the main menu's fixed-position JOIN/NAME fields, stored servers, delete-a-save, WORLD DETAIL."""
import collections
import json
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from chopped import config as C
from chopped import savefile as SF
from chopped import settings as SET
from chopped import ui
from chopped.art import GLYPHS, PixelFont


def kd(key, uni="", mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=uni, mod=mod)


def write_slot(n, day=20, cash=4032, act=2):
    with open(SF.slot_path(n), "w") as f:
        json.dump({"save_version": SF.SAVE_VERSION, "day": day, "cash": cash, "act": act, "cars": {}}, f)


class Base(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.display.set_mode((64, 64))
        self.dir = tempfile.mkdtemp()
        self._old = os.environ.get("CHOPPED_SAVE_DIR")
        os.environ["CHOPPED_SAVE_DIR"] = self.dir
        self.font = PixelFont()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CHOPPED_SAVE_DIR", None)
        else:
            os.environ["CHOPPED_SAVE_DIR"] = self._old
        shutil.rmtree(self.dir, ignore_errors=True)

    def menu(self, servers=None):
        return ui.Menu(self.font, "BRYCE", servers=servers)

    def type_text(self, m, text):
        for ch in text:
            m.handle(kd(ord(ch), ch))


class TestFields(Base):
    def test_typing_moves_nothing(self):
        m = self.menu()
        before = m.layout()
        m.sel = m.ITEMS.index("JOIN GAME")
        m.handle(kd(pygame.K_RETURN, "\r"))
        self.assertEqual(m.editing, "join")
        self.type_text(m, "192.168.100.200:27015")
        self.assertEqual(m.join_addr, "192.168.100.200:27015")
        self.assertEqual(m.layout(), before)
        m.handle(kd(pygame.K_ESCAPE))
        m.sel = m.ITEMS.index("NAME")
        m.handle(kd(pygame.K_RETURN, "\r"))
        self.type_text(m, "abcdefghijklmnop")
        self.assertEqual(m.name, "BRYCEABCDEFG")                # 12 max
        self.assertEqual(m.layout(), before)

    def test_drawn_field_pixels_stay_inside_the_box_columns(self):
        """Render with short and very long text: the label and the box edges draw the same pixels."""
        m = self.menu()
        m.sel = m.ITEMS.index("JOIN GAME")
        m.editing = "join"
        shots = []
        for txt in ("1.2.3.4", "x" * 60):
            m.join_addr = txt
            low = pygame.Surface((C.LOW_W, C.LOW_H), pygame.SRCALPHA)
            m.draw(low, 0.0)                                      # cursor off (int(0*3)%2 == 0)
            shots.append(low)
        box = m.field_rect("JOIN GAME")
        strip = pygame.Rect(0, box.y, box.x - 1, box.h)           # the label side of the row
        a = pygame.image.tobytes(shots[0].subsurface(strip), "RGBA")
        b = pygame.image.tobytes(shots[1].subsurface(strip), "RGBA")
        self.assertEqual(a, b, "the label area changed while typing")
        right = pygame.Rect(box.right, box.y, C.LOW_W - box.right, box.h)
        self.assertEqual(pygame.image.tobytes(shots[0].subsurface(right), "RGBA"),
                         pygame.image.tobytes(shots[1].subsurface(right), "RGBA"),
                         "text spilled out of the box")

    def test_long_input_is_clipped_to_the_box(self):
        m = self.menu()
        fit = m._fit("9" * 60, m.FIELD_BOX_W - 16)
        self.assertLess(len(fit), 60)
        self.assertTrue("9" * 60 == "9" * 60 and fit == "9" * len(fit))
        self.assertLessEqual(PixelFont.width(fit) * 2, m.FIELD_BOX_W - 16)

    def test_default_prefill_and_first_key_replaces(self):
        m = self.menu()
        self.assertEqual(m.join_addr, "127.0.0.1")
        m.sel = m.ITEMS.index("JOIN GAME")
        m.handle(kd(pygame.K_RETURN, "\r"))
        self.type_text(m, "5")
        self.assertEqual(m.join_addr, "5")                        # the selected text was replaced

    def test_paste(self):
        m = self.menu()
        old = ui.clipboard_text
        try:
            ui.clipboard_text = lambda: "  my-host.example.com:2000 \nsecond line"
            m._start_edit("join")
            m.handle(kd(pygame.K_v, "\x16", pygame.KMOD_CTRL))
            self.assertEqual(m.join_addr, "my-host.example.com:2000")
            ui.clipboard_text = lambda: "bob smith!"
            m._start_edit("name")
            m.name = ""
            m.handle(kd(pygame.K_v, "\x16", pygame.KMOD_CTRL))
            self.assertEqual(m.name, "BOB SMITH")
        finally:
            ui.clipboard_text = old

    def test_clipboard_is_safe_without_a_clipboard(self):
        self.assertIsInstance(ui.clipboard_text(), str)

    def test_backspace_and_repeat(self):
        m = self.menu()
        m._start_edit("join")
        m.replace_next = False
        m.join_addr = "1234567890"
        m.handle(kd(pygame.K_BACKSPACE))
        self.assertEqual(m.join_addr, "123456789")
        keys = collections.defaultdict(bool, {pygame.K_BACKSPACE: True})
        m.tick(0.3, keys)
        self.assertEqual(m.join_addr, "123456789")                # still inside the delay
        m.tick(0.3, keys)
        self.assertLess(len(m.join_addr), 9)
        n = len(m.join_addr)
        m.tick(0.3, collections.defaultdict(bool))                # released: stops
        self.assertEqual(len(m.join_addr), n)
        m.handle(kd(pygame.K_BACKSPACE, "", pygame.KMOD_CTRL))
        self.assertEqual(m.join_addr, "")

    def test_validation_and_error_line(self):
        m = self.menu()
        m._start_edit("join")
        m.join_addr = "host:99999"
        self.assertIsNone(m.handle(kd(pygame.K_RETURN, "\r")))
        self.assertTrue(m.error)
        self.assertEqual(m.editing, "join")                       # stays open to fix it
        for good in ("", "1.2.3.4", "1.2.3.4:27015", "some-host.net"):
            self.assertEqual(ui.validate_addr(good), "")
        for bad in ("a:b", "a:0", ":5", "a:1:2"):
            self.assertTrue(ui.validate_addr(bad), bad)
        m.join_addr = "1.2.3.4:27015"
        self.assertEqual(m.handle(kd(pygame.K_RETURN, "\r")), "join")
        self.assertIsNone(m.editing)

    def test_glyphs(self):
        m = self.menu([{"addr": "a.b", "name": "BOB", "last": 1}])
        m.slots[1] = {"day": 20, "cash": 4032, "act": 2, "rep": 0, "crew": [], "map_seed": 1, "story_ch": 0, "age": 0}
        m._ask_delete()
        texts = [m.confirm.title, m.confirm.sub, m.confirm.yes, m.confirm.no, "[DEL] DELETE",
                 "RECENT HOSTS  (UP/DOWN PICK, DEL REMOVES)", "DEL AGAIN TO REMOVE", "JOIN:", "NAME:", "<",
                 "TYPE THE HOST'S IP (DEFAULT PORT 27015). CTRL+V PASTES. ENTER: CONNECT, ESC: CANCEL"]
        for t in texts:
            for ch in t:
                self.assertIn(ch.upper(), GLYPHS, repr(ch))
        low = pygame.Surface((C.LOW_W, C.LOW_H), pygame.SRCALPHA)
        for sel in range(len(m.ITEMS)):
            m.sel = sel
            m.draw(low, 1.0)


class TestStoredServers(Base):
    SV = [{"addr": "10.0.0.5", "name": "ALICE", "last": 30}, {"addr": "my.host:2000", "last": 20},
          {"addr": "10.0.0.9", "last": 10}]

    def fresh(self):
        return self.menu([dict(e) for e in self.SV])

    def test_prefills_with_most_recent(self):
        self.assertEqual(self.fresh().join_addr, "10.0.0.5")

    def test_arrow_pick_enter_joins(self):
        m = self.fresh()
        m.sel = m.ITEMS.index("JOIN GAME")
        m.handle(kd(pygame.K_RETURN, "\r"))
        self.assertEqual(m.pick, 0)
        m.handle(kd(pygame.K_DOWN))
        self.assertEqual((m.pick, m.join_addr), (1, "my.host:2000"))
        m.handle(kd(pygame.K_UP))
        m.handle(kd(pygame.K_UP))
        self.assertEqual((m.pick, m.join_addr), (2, "10.0.0.9"))         # wraps
        self.assertEqual(m.handle(kd(pygame.K_RETURN, "\r")), "join")

    def test_typing_drops_the_highlight(self):
        m = self.fresh()
        m._start_edit("join")
        self.type_text(m, "1")
        self.assertEqual(m.pick, -1)
        self.assertEqual(m.handle(kd(pygame.K_DELETE)), None)            # nothing picked: nothing armed
        self.assertEqual(len(m.servers), 3)

    def test_del_twice_removes(self):
        m = self.fresh()
        m._start_edit("join")
        m.handle(kd(pygame.K_DOWN))
        self.assertIsNone(m.handle(kd(pygame.K_DELETE)))
        self.assertEqual(m.del_armed, 1)
        self.assertEqual(len(m.servers), 3)
        self.assertEqual(m.handle(kd(pygame.K_DELETE)), "save")
        self.assertEqual([e["addr"] for e in m.servers], ["10.0.0.5", "10.0.0.9"])

    def test_other_key_disarms(self):
        m = self.fresh()
        m._start_edit("join")
        m.handle(kd(pygame.K_DELETE))
        m.handle(kd(pygame.K_DELETE))
        self.assertEqual(len(m.servers), 2)
        m.handle(kd(pygame.K_DOWN))
        m.handle(kd(pygame.K_DELETE))
        m.handle(kd(pygame.K_UP))
        m.handle(kd(pygame.K_DELETE))
        self.assertEqual(len(m.servers), 2)                              # (different entry: armed, not removed)

    def test_mouse_pick_and_x(self):
        m = self.fresh()
        m._start_edit("join")
        self.assertEqual(m.click(m.server_rect(1).center), "join")
        self.assertEqual(m.join_addr, "my.host:2000")
        m._start_edit("join")
        self.assertIsNone(m.click(m.server_x_rect(0).center))
        self.assertEqual(m.click(m.server_x_rect(0).center), "save")
        self.assertEqual(len(m.servers), 2)

    def test_list_fits_the_canvas(self):
        sv = [{"addr": "10.0.0.%d" % i, "last": i} for i in range(SET.SERVERS_MAX)]
        m = self.menu(sv)
        self.assertLessEqual(m.list_rect().bottom + 12, C.LOW_H - 24)    # room for the hint above the error line

    def test_click_field_starts_editing(self):
        m = self.fresh()
        m.click(m.field_rect("NAME").center)
        self.assertEqual(m.editing, "name")


class TestDeleteSave(Base):
    def test_confirm_flow(self):
        write_slot(2)
        m = self.menu()
        m.slot = 2
        m.refresh_slots()
        self.assertIsNotNone(m.del_rect())
        m.sel = m.ITEMS.index("SAVE SLOT")
        m.handle(kd(pygame.K_DELETE))
        self.assertIsNotNone(m.confirm)
        self.assertEqual(m.confirm.title, "DELETE SLOT 2? DAY 20, $4032, ACT 2.")
        m.handle(kd(pygame.K_ESCAPE))                                    # keep
        self.assertIsNone(m.confirm)
        self.assertTrue(os.path.exists(SF.slot_path(2)))
        m.handle(kd(pygame.K_DELETE))
        m.handle(kd(pygame.K_DELETE))                                    # a second Del is not a yes
        self.assertIsNotNone(m.confirm)
        self.assertTrue(os.path.exists(SF.slot_path(2)))
        self.assertIsNone(m.handle(kd(pygame.K_RETURN, "\r")))
        self.assertFalse(os.path.exists(SF.slot_path(2)))
        self.assertIsNone(m.confirm)
        self.assertIsNone(m.slots[2])
        self.assertIsNone(m.del_rect())

    def test_button_click_and_dialog_buttons(self):
        write_slot(1)
        m = self.menu()
        m.refresh_slots()
        m.click(m.del_rect().center)
        self.assertIsNotNone(m.confirm)
        m.click(m.confirm.NO.center)
        self.assertTrue(os.path.exists(SF.slot_path(1)))
        m.click(m.del_rect().center)
        m.click(m.confirm.YES.center)
        self.assertFalse(os.path.exists(SF.slot_path(1)))

    def test_empty_slot_has_nothing_to_delete(self):
        m = self.menu()
        self.assertIsNone(m.del_rect())
        m.sel = m.ITEMS.index("SAVE SLOT")
        m.handle(kd(pygame.K_DELETE))
        self.assertIsNone(m.confirm)

    def test_escape_in_dialog_does_not_quit(self):
        write_slot(1)
        m = self.menu()
        m.refresh_slots()
        m.sel = m.ITEMS.index("SAVE SLOT")
        m.handle(kd(pygame.K_DELETE))
        self.assertIsNone(m.handle(kd(pygame.K_ESCAPE)))

    def test_settings_save_files(self):
        write_slot(1)
        write_slot(3, day=7, cash=50, act=1)
        data = SET.defaults()
        changes = []
        p = ui.SettingsPanel(self.font, data, changes.append, locked_path=SF.slot_path(3))
        self.assertEqual(p.total, len(p.ROWS) + C.SAVE_SLOTS)
        self.assertTrue(p.BOX.contains(p.slot_rect(C.SAVE_SLOTS)))
        low = pygame.Surface((C.LOW_W, C.LOW_H))
        p.draw(low, (0, 0))
        # empty slot 2: nothing to delete
        p.sel = len(p.ROWS) + 1
        p.handle(kd(pygame.K_DELETE))
        self.assertIsNone(p.confirm)
        # locked slot 3: refuses
        p.sel = len(p.ROWS) + 2
        p.handle(kd(pygame.K_DELETE))
        self.assertIsNone(p.confirm)
        p.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p.slot_del_rect(3).center))
        self.assertIsNone(p.confirm)
        # slot 1: asks, keep, then delete by click
        p.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=p.slot_del_rect(1).center))
        self.assertIsNotNone(p.confirm)
        self.assertEqual(p.handle(kd(pygame.K_ESCAPE)), None)            # closes the dialog, not the screen
        self.assertIsNone(p.confirm)
        self.assertTrue(os.path.exists(SF.slot_path(1)))
        p.sel = len(p.ROWS)
        p.handle(kd(pygame.K_x))
        p.draw(low, (0, 0))
        self.assertEqual(p.handle(kd(pygame.K_RETURN, "\r")), None)
        self.assertFalse(os.path.exists(SF.slot_path(1)))
        self.assertTrue(os.path.exists(SF.slot_path(3)))
        self.assertIn("save_files", changes)
        self.assertEqual(p.handle(kd(pygame.K_ESCAPE)), "back")

    def test_settings_glyphs_and_fit(self):
        p = ui.SettingsPanel(self.font, SET.defaults())
        for t in list(p.HINTS.values()) + ["SAVE FILES", "IN USE", "[DEL] DELETE", "SLOT 1: DAY 20 $4032 ACT 2",
                                           "THIS SLOT IS THE GAME YOU'RE HOSTING. LEAVE TO THE MENU TO DELETE IT.",
                                           "DEL OR CLICK DELETE: WIPES THIS SLOT (IT ASKS FIRST).",
                                           "W/S: PICK   A/D OR DRAG: CHANGE   DEL: DELETE A SAVE   ESC: BACK (SAVES)"]:
            for ch in t:
                self.assertIn(ch, GLYPHS, repr(ch))
        for i in range(len(p.ROWS)):
            self.assertTrue(p.BOX.contains(p.row_rect(i)))
        self.assertTrue(pygame.Rect(0, 0, C.LOW_W, C.LOW_H).contains(p.BOX))


class TestWorldDetail(Base):
    def panel(self, **kw):
        data = SET.defaults()
        data.update(kw)
        self.changes = []
        return ui.SettingsPanel(self.font, data, self.changes.append), data

    def test_row_sits_under_render_scale(self):
        p, _ = self.panel()
        keys = [r[0] for r in p.ROWS]
        self.assertEqual(keys[keys.index("render_scale") + 1], "world_scale")
        self.assertIn("SHARPER WALLS AND STREETS", p.HINTS["world_scale"])

    def test_buttons_above_render_scale_are_greyed(self):
        p, data = self.panel(render_scale=2, world_scale=1)
        i = [r[0] for r in p.ROWS].index("world_scale")
        lo = p.ROWS[i][2]
        rects = p.scale_rects(i)
        p.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rects[2].center))   # 3X, greyed
        self.assertEqual(data["world_scale"], 1)
        p.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rects[1].center))
        self.assertEqual(data["world_scale"], lo + 1)
        self.assertIn("world_scale", self.changes)
        low = pygame.Surface((C.LOW_W, C.LOW_H))
        p.draw(low, rects[2].center)

    def test_keys_stop_at_the_cap(self):
        p, data = self.panel(render_scale=2, world_scale=1)
        p.sel = [r[0] for r in p.ROWS].index("world_scale")
        for _ in range(5):
            p.handle(kd(pygame.K_d))
        self.assertEqual(data["world_scale"], 2)

    def test_lowering_render_scale_reapplies_world(self):
        p, data = self.panel(render_scale=3, world_scale=3)
        p.sel = [r[0] for r in p.ROWS].index("render_scale")
        p.handle(kd(pygame.K_a))
        self.assertEqual(data["render_scale"], 2)
        self.assertIn("world_scale", self.changes)                         # the game re-applies min(world, render)
        self.assertEqual(p._value([r[0] for r in p.ROWS].index("world_scale")), 2)


if __name__ == "__main__":
    unittest.main()

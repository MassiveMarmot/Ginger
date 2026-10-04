import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd, RULE  # noqa: E402

import snapd_client  # noqa: E402
from snapd_client import PROMPTING_NOT_RUNNING  # noqa: E402

from gi.repository import Adw, Gtk  # noqa: E402


def window_content(win):
    return win.page_stack.get_visible_child()


class UISmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.socket_path = os.path.join(cls.tmpdir.name, "snapd.socket")
        cls.server = MockSnapd(cls.socket_path)
        os.environ["SNAPD_SOCKET"] = cls.socket_path
        cls.app = None
        cls.main = None

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmpdir.cleanup()

    def setUp(self):
        if self.main is None:
            import main
            self.__class__.main = main
        if self.app is None:
            app = self.main.App()
            app.connect("activate", lambda a: None)
            self.__class__.app = app
            app.register()
        self.server.rules = []
        self.server.responses = []

    def make_window(self):
        win = self.app.props.active_window
        if not win:
            win = self.main.Window(self.app)
            win.present()
        win.load()
        return win

    def find_labels(self, widget, out):
        if isinstance(widget, Gtk.Label):
            out.append(widget)
        child = widget.get_first_child()
        while child:
            self.find_labels(child, out)
            child = child.get_next_sibling()
        return out

    def row_label_texts(self, win):
        texts = []
        for i in range(100):
            row = win.rules_list.get_row_at_index(i)
            if row is None:
                break
            texts.append([l.get_text() for l in self.find_labels(row, [])])
        return texts

    def test_sidebar_pages(self):
        win = self.make_window()
        pages = [win.sidebar_rows.get_row_at_index(i).page_name
                 for i in range(2)]
        self.assertEqual(pages, ["Rules", "Add Rule"])

    def test_add_rule_page_is_placeholder(self):
        win = self.make_window()
        win.on_page_selected(win.sidebar_rows,
                             win.sidebar_rows.get_row_at_index(1))
        self.assertEqual(win.content_stack.get_visible_child_name(), "add")
        page = win.add_page
        self.assertIn("next milestone", page.get_description())

    def test_rules_one_row_per_rule(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        rows = self.row_label_texts(win)
        self.assertEqual(len(rows), 2)
        flat = [t for texts in rows for t in texts]
        self.assertIn("firefox", flat)
        self.assertIn("thunderbird", flat)
        self.assertIn("/home/user/docs/**", flat)

    def test_detail_updates_on_selection(self):
        self.server.rules = [dict(RULE)]
        win = self.make_window()
        win.on_rule_selected(win.rules_list,
                             win.rules_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("firefox", texts)
        self.assertIn("/home/user/docs/**", texts)
        self.assertIn("read", texts)
        self.assertIn("allow / forever", texts)

    def test_search_narrows_list(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        win.query = "thunderbird"
        win.refresh_list()
        texts = self.row_label_texts(win)
        self.assertEqual(len(texts), 1)
        self.assertIn("thunderbird", texts[0])
        win.query = "/home/user/docs"
        win.refresh_list()
        self.assertEqual(len(self.row_label_texts(win)), 2)

    def test_filter_by_snap_narrows_list(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        win.filter_snaps = {"firefox"}
        win.refresh_list()
        texts = self.row_label_texts(win)
        self.assertEqual(len(texts), 1)
        self.assertIn("firefox", texts[0])

    def test_filter_panel_entries(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        snaps = [win.filter_list.get_row_at_index(i).snap_name
                 for i in range(2)]
        self.assertEqual(snaps, ["firefox", "thunderbird"])

    def test_select_mode_toggle(self):
        self.server.rules = [dict(RULE)]
        win = self.make_window()
        self.select_button_flip(win)
        self.assertTrue(win.select_mode)
        self.assertEqual(win.list_title.get_text(), "0 Selected")
        row = win.rules_list.get_row_at_index(0)
        checks = [w for w in self.walk(row)
                  if isinstance(w, Gtk.CheckButton)]
        self.assertEqual(len(checks), 1)
        self.select_button_flip(win)
        self.assertFalse(win.select_mode)
        self.assertEqual(win.list_title.get_text(), "Rules")
        row = win.rules_list.get_row_at_index(0)
        checks = [w for w in self.walk(row)
                  if isinstance(w, Gtk.CheckButton)]
        self.assertEqual(len(checks), 0)

    def select_button_flip(self, win):
        win.select_button.set_active(not win.select_button.get_active())

    def walk(self, widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from self.walk(child)
            child = child.get_next_sibling()

    def test_select_count_updates(self):
        self.server.rules = [dict(RULE)]
        win = self.make_window()
        self.select_button_flip(win)
        row = win.rules_list.get_row_at_index(0)
        checks = [w for w in self.walk(row)
                  if isinstance(w, Gtk.CheckButton)]
        checks[0].set_active(True)
        self.assertEqual(win.selected_ids, {"1"})
        self.assertEqual(win.list_title.get_text(), "1 Selected")

    def test_error_then_recovery(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "<b>evil</b>&amp;", "kind": "some-kind"},
        }))
        win = self.make_window()
        self.assertEqual(win.page_stack.get_visible_child_name(), "error")
        self.assertEqual(win.error_page.get_title(),
                         "snapd returned an error")
        texts = [l.get_text() for l in
                 self.find_labels(win.error_page, [])]
        self.assertIn("<b>evil</b>&amp;", texts)
        self.server.rules = [dict(RULE)]
        win.activate_action("win.refresh", None)
        self.assertEqual(win.page_stack.get_visible_child_name(), "content")
        self.assertEqual(len(self.row_label_texts(win)), 1)

    def test_prompting_not_running_page(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "prompting not running",
                       "kind": PROMPTING_NOT_RUNNING},
        }))
        win = self.make_window()
        self.assertEqual(win.page_stack.get_visible_child_name(), "error")
        self.assertEqual(win.error_page.get_title(),
                         "AppArmor prompting is not enabled")

    def test_connection_error_page(self):
        sock_path = os.path.join(self.tmpdir.name, "missing.socket")
        client = snapd_client.Client(socket_path=sock_path)
        with self.assertRaises(snapd_client.SnapdError) as ctx:
            client.list_rules()
        self.assertEqual(ctx.exception.kind, "connection-failed")
        win = self.make_window()
        win.show_error("Could not reach snapd", ctx.exception.message,
                       "network-error-symbolic")
        self.assertEqual(win.page_stack.get_visible_child_name(), "error")
        self.assertEqual(win.error_page.get_title(), "Could not reach snapd")

    def test_rules_to_empty_clears(self):
        self.server.rules = [dict(RULE)]
        win = self.make_window()
        win.on_rule_selected(win.rules_list,
                             win.rules_list.get_row_at_index(0))
        self.server.rules = []
        win.activate_action("win.refresh", None)
        self.assertEqual(self.row_label_texts(win), [])
        self.assertEqual(win.selected_rule, None)

    def test_broad_pattern_warning_icon(self):
        broad = dict(RULE)
        broad["constraints"] = dict(RULE["constraints"],
                                    **{"path-pattern": "/**"})
        self.server.rules = [broad]
        win = self.make_window()
        row = win.rules_list.get_row_at_index(0)
        images = [w for w in self.walk(row) if isinstance(w, Gtk.Image)
                  if w.get_icon_name() == "dialog-warning-symbolic"]
        self.assertEqual(len(images), 1)

    def test_collapsed_sidebar_toggle_reopens(self):
        win = self.make_window()
        win.main_split.set_collapsed(True)
        win.main_split.set_show_sidebar(False)
        self.assertFalse(win.main_split.get_show_sidebar())
        self.assertFalse(win.sidebar_toggle.get_active())
        win.sidebar_toggle.set_active(True)
        self.assertTrue(win.main_split.get_show_sidebar())
        win.main_split.set_show_sidebar(False)
        self.assertFalse(win.sidebar_toggle.get_active())


if __name__ == "__main__":
    unittest.main()

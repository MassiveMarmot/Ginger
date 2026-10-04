import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd, RULE  # noqa: E402

import snapd_client  # noqa: E402
from snapd_client import PROMPTING_NOT_RUNNING  # noqa: E402

from gi.repository import Adw, Gtk  # noqa: E402


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
            app.connect("activate", self._on_activate)
            self.__class__.app = app
            app.register()
        self.server.rules = []
        self.server.responses = []

    @staticmethod
    def _on_activate(app):
        pass

    def make_window(self):
        win = self.app.props.active_window
        if not win:
            win = self.main.Window(self.app)
            win.present()
        win.load()
        return win

    def content_child(self, win):
        return win.content.get_child()

    def find_labels(self, widget, out):
        if isinstance(widget, Gtk.Label):
            out.append(widget)
        child = widget.get_first_child()
        while child:
            self.find_labels(child, out)
            child = child.get_next_sibling()
        return out

    def test_rules_listed_with_sidebar(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        self.assertIsInstance(win.get_content(), Adw.OverlaySplitView)
        rows = [win.sidebar_rows.get_row_at_index(i) for i in range(2)]
        self.assertEqual([r.snap_name for r in rows], ["firefox", "thunderbird"])
        self.assertIsInstance(self.content_child(win), Gtk.ScrolledWindow)
        texts = [l.get_text() for l in
                 self.find_labels(self.content_child(win), [])]
        self.assertIn("/home/user/docs/**", texts)
        self.assertIn("read: allow / forever", texts)

    def test_no_rules_page(self):
        win = self.make_window()
        page = self.content_child(win)
        self.assertEqual(type(page).__name__, "StatusPage")
        self.assertEqual(page.get_title(), "No rules")

    def test_snap_selection_shows_its_rules(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        win.on_snap_selected(win.sidebar_rows, win.row_for("thunderbird"))
        texts = [l.get_text() for l in
                 self.find_labels(self.content_child(win), [])]
        self.assertIn("thunderbird", texts)
        self.assertIn("/home/user/docs/**", texts)

    def test_prompting_not_running_page(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "prompting not running",
                       "kind": PROMPTING_NOT_RUNNING},
        }))
        win = self.make_window()
        page = win.get_content().get_child()
        self.assertEqual(page.get_title(), "AppArmor prompting is not enabled")

    def test_connection_error_page(self):
        sock_path = os.path.join(self.tmpdir.name, "missing.socket")
        client = snapd_client.Client(socket_path=sock_path)
        with self.assertRaises(snapd_client.SnapdError) as ctx:
            client.list_rules()
        self.assertEqual(ctx.exception.kind, "connection-failed")
        win = self.make_window()
        win.show_status_page("Could not reach snapd", ctx.exception.message,
                            "network-error-symbolic")
        page = win.get_content().get_child()
        self.assertEqual(page.get_title(), "Could not reach snapd")
        texts = [l.get_text() for l in self.find_labels(page, [])]
        self.assertIn(ctx.exception.message, texts)

    def test_markup_in_pattern_and_snap_not_parsed(self):
        nasty = dict(RULE, snap="<b>evil</b>&amp;", id="9")
        nasty["constraints"] = dict(RULE["constraints"],
                                    **{"path-pattern": "<b>x</b>&amp;"})
        self.server.rules = [nasty]
        win = self.make_window()
        texts = [l.get_text() for l in
                 self.find_labels(self.content_child(win), [])]
        self.assertIn("<b>x</b>&amp;", texts)
        texts = [l.get_text() for l in
                 self.find_labels(win.sidebar_rows, [])]
        self.assertIn("<b>evil</b>&amp;", texts)

    def test_markup_in_error_message_not_parsed(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "<b>evil</b>&amp;", "kind": "some-kind"},
        }))
        win = self.make_window()
        page = win.get_content().get_child()
        self.assertEqual(page.get_title(), "snapd returned an error")
        texts = [l.get_text() for l in self.find_labels(page, [])]
        self.assertIn("<b>evil</b>&amp;", texts)

    def test_refresh_action_reloads(self):
        self.server.rules = [dict(RULE)]
        win = self.make_window()
        self.server.rules = []
        win.activate_action("win.refresh", None)
        page = self.content_child(win)
        self.assertEqual(type(page).__name__, "StatusPage")
        self.assertEqual(page.get_title(), "No rules")

    def test_refresh_preserves_selection(self):
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        win.on_snap_selected(win.sidebar_rows, win.row_for("thunderbird"))
        win.activate_action("win.refresh", None)
        self.assertEqual(win.selected, "thunderbird")
        texts = [l.get_text() for l in
                 self.find_labels(self.content_child(win), [])]
        self.assertIn("thunderbird", texts)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest

if not os.environ.get("DISPLAY") and not os.environ.get("ALLOW_NO_DISPLAY"):
    os.environ["GDK_BACKEND"] = "broadway"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd, RULE  # noqa: E402

from snapd_client import PROMPTING_NOT_RUNNING  # noqa: E402


class UISmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.socket_path = os.path.join(cls.tmpdir.name, "snapd.socket")
        cls.server = MockSnapd(cls.socket_path)
        os.environ["SNAPD_SOCKET"] = cls.socket_path
        import snapd_client
        snapd_client.DEFAULT_SOCKET = cls.socket_path
        import main
        cls.main = main
        cls.app = main.App()
        cls.app_hold = cls.app.connect("activate", lambda a: a.quit())
        cls.app.run([])

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmpdir.cleanup()

    def make_window(self):
        win = self.main.Window(self.app)
        win.load()
        return win

    def child(self, win):
        return win.bin.get_child()

    def test_rules_listed_grouped(self):
        from gi.repository import Gtk
        self.server.rules = [dict(RULE), dict(RULE, snap="thunderbird", id="2")]
        win = self.make_window()
        self.assertIsInstance(self.child(win), Gtk.ScrolledWindow)
        self.assertEqual(win.get_title(), "Snap Path Permissions")

    def test_no_rules_page(self):
        self.server.rules = []
        win = self.make_window()
        from gi.repository import Adw
        self.assertEqual(type(self.child(win)).__name__, "StatusPage")
        self.assertEqual(self.child(win).get_title(), "No rules")

    def test_prompting_not_running_page(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "prompting not running",
                       "kind": PROMPTING_NOT_RUNNING},
        }))
        win = self.make_window()
        page = self.child(win)
        self.assertEqual(page.get_title(), "AppArmor prompting is not enabled")

    def test_connection_error_page(self):
        bad = self.main.Window.__new__(self.main.Window)
        import snapd_client
        bad.client = snapd_client.Client(
            socket_path=os.path.join(self.tmpdir.name, "missing.socket"))
        bad.bin = self.main.Adw.Bin()
        try:
            rules = bad.client.list_rules()
        except snapd_client.SnapdError as e:
            bad.show_status_page("Could not reach snapd", e.message,
                                 "network-error-symbolic")
        page = bad.bin.get_child()
        self.assertEqual(page.get_title(), "Could not reach snapd")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd  # noqa: E402

import snapd_client  # noqa: E402

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

SNAP_APP = {"name": "firefox", "type": "app", "version": "1.0",
            "summary": "Browse the web", "apps": [{"name": "firefox"}]}
SNAP_BASE = {"name": "core24", "type": "base", "version": "2"}

CONNECTIONS = {
    "established": [
        {"slot": {"snap": "snapd", "slot": "camera"},
         "plug": {"snap": "firefox", "plug": "camera"},
         "interface": "camera", "manual": True},
        {"slot": {"snap": "snapd", "slot": "network"},
         "plug": {"snap": "firefox", "plug": "network"},
         "interface": "network"},
        {"slot": {"snap": "snapd", "slot": "removable-media"},
         "plug": {"snap": "firefox", "plug": "removable-media"},
         "interface": "removable-media", "manual": True},
    ],
    "undesired": [
        {"slot": {"snap": "snapd", "slot": "audio-record"},
         "plug": {"snap": "firefox", "plug": "audio-record"},
         "interface": "audio-record", "manual": True},
    ],
    "plugs": [
        {"snap": "firefox", "plug": "camera", "interface": "camera",
         "apps": [], "connections": [{"snap": "snapd", "slot": "camera"}]},
        {"snap": "firefox", "plug": "network", "interface": "network",
         "apps": [], "connections": []},
        {"snap": "firefox", "plug": "removable-media",
         "interface": "removable-media", "apps": [], "connections": []},
        {"snap": "firefox", "plug": "audio-record",
         "interface": "audio-record", "apps": [], "connections": []},
        {"snap": "firefox", "plug": "docker-support",
         "interface": "docker-support", "apps": [], "connections": []},
        {"snap": "firefox", "plug": "orphan", "interface": "orphan-if",
         "apps": [], "connections": []},
        {"snap": "firefox", "plug": "gtk-3-themes", "interface": "content",
         "apps": [], "connections": []},
    ],
    "slots": [
        {"snap": "snapd", "slot": "camera", "interface": "camera",
         "connections": []},
        {"snap": "snapd", "slot": "network", "interface": "network",
         "connections": []},
        {"snap": "snapd", "slot": "removable-media",
         "interface": "removable-media", "connections": []},
        {"snap": "snapd", "slot": "audio-record",
         "interface": "audio-record", "connections": []},
    ],
}


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
        self.server.snaps = []
        self.server.posts = []
        self.server.responses = []
        self.server.default_connections = {
            "established": [], "undesired": [], "plugs": [], "slots": []}
        self.prev_data_dir = os.environ.get("GINGER_DATA_DIR")
        self.tmpdir_i = tempfile.TemporaryDirectory()
        os.environ["GINGER_DATA_DIR"] = self.tmpdir_i.name
        self.win = self.main.Window(self.app)
        self.win.present()

    def tearDown(self):
        self.win.destroy()
        self.tmpdir_i.cleanup()
        if self.prev_data_dir is None:
            del os.environ["GINGER_DATA_DIR"]
        else:
            os.environ["GINGER_DATA_DIR"] = self.prev_data_dir

    def tearDown(self):
        self.win.destroy()

    def make_window(self):
        self.win.load()
        return self.win

    def find_labels(self, widget, out):
        if isinstance(widget, Gtk.Label):
            out.append(widget)
        child = widget.get_first_child()
        while child:
            self.find_labels(child, out)
            child = child.get_next_sibling()
        return out

    def row_texts(self, win):
        texts = []
        for i in range(200):
            row = win.snaps_list.get_row_at_index(i)
            if row is None:
                break
            texts.append([l.get_text() for l in self.find_labels(row, [])])
        return texts

    def walk(self, widget):
        yield widget
        child = widget.get_first_child()
        while child:
            yield from self.walk(child)
            child = child.get_next_sibling()

    def run_until(self, condition, timeout_ms=2000):
        ctx = GLib.MainContext.default()
        end = GLib.get_monotonic_time() + timeout_ms * 1000
        while not condition() and GLib.get_monotonic_time() < end:
            ctx.iteration(True)

    def test_funnel_icon_loads(self):
        self.make_window()
        theme = Gtk.IconTheme.get_for_display(self.win.get_display())
        self.assertTrue(theme.has_icon("funnel-symbolic"))
        self.assertEqual(self.win.filter_button.get_icon_name(),
                         "funnel-symbolic")

    def test_summary_ellipsizes_at_end(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        summary = [l for l in self.find_labels(win.detail_bin.get_child(), [])
                   if l.get_text() == "Browse the web"][0]
        self.assertEqual(summary.get_ellipsize(), Pango.EllipsizeMode.END)

    def test_auto_select_does_not_reveal_content(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.detail_split.set_collapsed(True)
        win.detail_split.set_show_content(False)
        win.load()
        self.assertEqual(win.selected_snap, "firefox")
        self.assertFalse(win.detail_split.get_show_content())
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        self.assertTrue(win.detail_split.get_show_content())

    def test_info_rows_use_property_look(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        rows = [r for r in self.walk(win.detail_bin.get_child())
                if isinstance(r, Adw.ActionRow)]
        titles = [r.get_title() for r in rows]
        for title in ("Snap name", "Version"):
            row = rows[titles.index(title)]
            self.assertIn("property", row.get_css_classes(), title)
            self.assertTrue(row.get_subtitle(), title)

    def test_apps_empty_snap_hidden(self):
        lib = {"name": "gtk-common-themes", "type": "app", "apps": []}
        self.server.snaps = [dict(SNAP_APP), lib]
        win = self.make_window()
        names = [t[0] for t in self.row_texts(win)]
        self.assertNotIn("gtk-common-themes", names)
        win.lib_check.set_active(True)
        names = [t[0] for t in self.row_texts(win)]
        self.assertIn("gtk-common-themes", names)

    def test_no_apps_field_behaves_like_empty(self):
        lib = {"name": "gtk-common-themes", "type": "app"}
        self.server.snaps = [dict(SNAP_APP), lib]
        win = self.make_window()
        names = [t[0] for t in self.row_texts(win)]
        self.assertNotIn("gtk-common-themes", names)

    def test_markup_in_version_not_parsed(self):
        snap = dict(SNAP_APP, version="<b>evil</b>&amp;")
        self.server.snaps = [snap]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("<b>evil</b>&amp;", texts)

    def test_sidebar_single_entry(self):
        win = self.make_window()
        row = win.sidebar_rows.get_row_at_index(0)
        self.assertEqual(row.page_name, "Snaps")

    def test_list_includes_snaps(self):
        self.server.snaps = [dict(SNAP_APP), dict(SNAP_BASE),
                             {"name": "nicotine-plus", "type": "app",
                              "apps": [{"name": "nicotine-plus"}]}]
        win = self.make_window()
        names = [t[0] for t in self.row_texts(win)]
        self.assertIn("firefox", names)
        self.assertIn("nicotine-plus", names)
        self.assertNotIn("core24", names)

    def test_search_by_name(self):
        self.server.snaps = [dict(SNAP_APP),
                             {"name": "thunderbird", "type": "app",
                              "apps": [{"name": "thunderbird"}]}]
        win = self.make_window()
        win.query = "thunder"
        win.refresh_list()
        texts = self.row_texts(win)
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0][0], "thunderbird")

    def test_selecting_snap_closes_filter(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.filter_button.set_active(True)
        self.assertEqual(win.detail_page.get_child(), win.filter_panel)
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        self.assertFalse(win.filter_button.get_active())
        self.assertEqual(win.detail_page.get_child(), win.detail_pane)

    def test_funnel_reveals_content_when_collapsed(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.detail_split.set_collapsed(True)
        win.detail_split.set_show_content(False)
        win.filter_button.set_active(True)
        self.assertTrue(win.detail_split.get_show_content())
        self.assertEqual(win.detail_page.get_child(), win.filter_panel)

    def test_detail_pane_contents(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("firefox", texts)
        self.assertIn("Browse the web", texts)
        self.assertIn("1.0", texts)

    def test_selection_and_query_survive_refresh(self):
        self.server.snaps = [dict(SNAP_APP),
                             {"name": "thunderbird", "type": "app",
                              "apps": [{"name": "thunderbird"}]}]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(1))
        self.assertEqual(win.selected_snap, "thunderbird")
        win.query = "e"
        win.refresh_list()
        win.activate_action("win.refresh", None)
        self.assertEqual(win.selected_snap, "thunderbird")
        row = win.snaps_list.get_selected_row()
        self.assertEqual(row.snap_name, "thunderbird")

    def test_show_content_on_selection(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.detail_split.set_collapsed(True)
        win.detail_split.set_show_content(False)
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        self.assertTrue(win.detail_split.get_show_content())

    def test_error_then_recovery(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "<b>evil</b>&amp;", "kind": "some-kind"},
        }))
        win = self.make_window()
        self.assertEqual(win.page_stack.get_visible_child_name(), "error")
        self.assertEqual(win.error_page.get_title(), "snapd returned an error")
        texts = [l.get_text() for l in self.find_labels(win.error_page, [])]
        self.assertIn("<b>evil</b>&amp;", texts)
        self.server.snaps = [dict(SNAP_APP)]
        win.activate_action("win.refresh", None)
        self.assertEqual(win.page_stack.get_visible_child_name(), "snaps")
        self.assertEqual(len(self.row_texts(win)), 1)

    def test_connection_error_page(self):
        sock_path = os.path.join(self.tmpdir.name, "missing.socket")
        client = snapd_client.Client(socket_path=sock_path)
        with self.assertRaises(snapd_client.SnapdError) as ctx:
            client.list_snaps()
        self.assertEqual(ctx.exception.kind, "connection-failed")
        win = self.make_window()
        win.show_error("Could not reach snapd", ctx.exception.message,
                       "network-error-symbolic")
        self.assertEqual(win.error_page.get_title(), "Could not reach snapd")

    def test_markup_in_snap_name_not_parsed(self):
        self.server.snaps = [{"name": "<b>evil</b>&amp;", "type": "app",
                              "apps": [{"name": "x"}]}]
        win = self.make_window()
        texts = self.row_texts(win)
        self.assertEqual(texts[0][0], "<b>evil</b>&amp;")

    def test_snap_rows_are_activatable(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        self.assertTrue(win.snaps_list.get_row_at_index(0).get_activatable())

    def test_minimal_snap_object(self):
        self.server.snaps = [{"name": "x"}]
        win = self.make_window()
        self.assertEqual(self.row_texts(win), [])
        self.assertIsNone(win.selected_snap)

    def test_breakpoint_700px(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.set_default_size(700, 600)
        self.run_until(lambda: win.main_split.get_collapsed())
        self.assertTrue(win.main_split.get_collapsed())
        self.assertFalse(win.detail_split.get_collapsed())

    def test_breakpoint_500px(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.set_default_size(500, 600)
        self.run_until(lambda: win.main_split.get_collapsed()
                       and win.detail_split.get_collapsed())
        self.assertTrue(win.main_split.get_collapsed())
        self.assertTrue(win.detail_split.get_collapsed())

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

    def test_window_title(self):
        win = self.make_window()
        self.assertEqual(win.get_title(), "Ginger")

    def permission_rows(self, win):
        return [r for r in self.walk(win.detail_bin.get_child())
                if isinstance(r, Adw.SwitchRow)]

    def row_by_title(self, win, title):
        for row in self.permission_rows(win):
            if row.get_title() == title:
                return row
        return None

    def test_snap_counts_in_list(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        row = win.snaps_list.get_row_at_index(0)
        texts = [l.get_text() for l in self.find_labels(row, [])]
        self.assertTrue(any("3 connected" in t for t in texts), texts)
        self.assertTrue(any("1 available" in t for t in texts), texts)

    def test_permissions_group_states(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        camera = self.row_by_title(win, "camera")
        self.assertIsNotNone(camera)
        self.assertTrue(camera.get_active())
        self.assertIn("Manually connected", camera.get_subtitle())
        network = self.row_by_title(win, "network")
        self.assertTrue(network.get_active())
        self.assertIn("Connected", network.get_subtitle())
        self.assertNotIn("Manually", network.get_subtitle())
        audio = self.row_by_title(win, "audio-record")
        self.assertFalse(audio.get_active())
        self.assertIn("Manually disconnected", audio.get_subtitle())

    def test_no_slot_available(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        orphan = self.row_by_title(win, "orphan")
        self.assertIsNotNone(orphan)
        self.assertIn("No slot available", orphan.get_subtitle())
        self.assertFalse(orphan.get_sensitive())

    def test_switches_insensitive_in_milestone_3(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        for row in self.permission_rows(win):
            self.assertFalse(row.get_sensitive())

    def test_content_plug_hidden_by_default(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        self.assertIsNone(self.row_by_title(win, "gtk-3-themes"))
        win.all_check.set_active(True)
        self.assertIsNotNone(self.row_by_title(win, "gtk-3-themes"))

    def test_tier_sort_order(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        titles = [r.get_title() for r in self.permission_rows(win)]
        self.assertEqual(titles, ["audio-record", "camera", "network",
                                 "orphan", "removable-media",
                                 "docker-support"])

    def test_tier_3_connect_not_offered(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        docker = self.row_by_title(win, "docker-support")
        self.assertIn("Connect not offered", docker.get_subtitle())

    def test_markup_in_plug_name_not_parsed(self):
        snap = dict(SNAP_APP, name="<b>evil</b>&amp;")
        conns = dict(CONNECTIONS)
        conns["plugs"] = [dict(p) for p in CONNECTIONS["plugs"]]
        conns["plugs"][0] = {"snap": "<b>evil</b>&amp;", "plug": "camera",
                             "interface": "camera", "apps": [],
                             "connections": []}
        conns["established"] = [
            {"slot": {"snap": "snapd", "slot": "camera"},
             "plug": {"snap": "<b>evil</b>&amp;", "plug": "camera"},
             "interface": "camera", "manual": True}]
        self.server.snaps = [snap]
        self.server.default_connections = conns
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("<b>evil</b>&amp;", texts)

    def test_baseline_written_at_launch(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        self.make_window()
        path = os.path.join(os.environ["GINGER_DATA_DIR"],
                            "baseline.json")
        self.assertTrue(os.path.exists(path))
        import baseline
        loaded = baseline.load(path)
        self.assertIn("firefox", loaded)
        self.assertEqual(
            sorted(c["plug"] for c in loaded["firefox"]["connected"]),
            ["camera", "network", "removable-media"])

    def test_baseline_not_overwritten_across_loads(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        self.make_window()
        path = os.path.join(os.environ["GINGER_DATA_DIR"],
                            "baseline.json")
        with open(path) as f:
            first = f.read()
        self.server.default_connections = {
            "established": [], "undesired": [], "plugs": [], "slots": []}
        self.win.load()
        with open(path) as f:
            self.assertEqual(f.read(), first)

    def test_corrupt_baseline_shows_banner_not_blocked(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        os.makedirs(os.environ["GINGER_DATA_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["GINGER_DATA_DIR"],
                               "baseline.json"), "w") as f:
            f.write("not-json{")
        win = self.make_window()
        self.assertTrue(win.baseline_banner.get_revealed())
        self.assertEqual(win.page_stack.get_visible_child_name(), "snaps")
        self.assertEqual(len(self.row_texts(win)), 1)
        path = os.path.join(os.environ["GINGER_DATA_DIR"],
                            "baseline.json")
        self.assertEqual(open(path).read(), "not-json{")

    def test_baseline_save_failure_shows_banner(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        data_dir = os.environ["GINGER_DATA_DIR"]
        os.mkdir(data_dir)
        os.chmod(data_dir, 0o500)
        try:
            win = self.make_window()
            self.assertTrue(win.baseline_banner.get_revealed())
            self.assertEqual(win.page_stack.get_visible_child_name(),
                             "snaps")
            self.assertEqual(len(self.row_texts(win)), 1)
        finally:
            os.chmod(data_dir, 0o700)

    def test_forget_menu_item_clears_banner(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        os.makedirs(os.environ["GINGER_DATA_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["GINGER_DATA_DIR"],
                               "baseline.json"), "w") as f:
            f.write("not-json{")
        win = self.make_window()
        self.assertTrue(win.baseline_banner.get_revealed())
        win.activate_action("win.forget-baseline", None)
        ctx = GLib.MainContext.default()
        for _ in range(10):
            ctx.iteration(False)
        alert = [d for w in Gtk.Window.list_toplevels()
                 for d in self.walk(w)
                 if isinstance(d, Adw.AlertDialog)]
        self.assertTrue(alert)
        alert[0].emit("response", "forget")
        self.run_until(lambda: not win.baseline_banner.get_revealed())
        self.assertFalse(os.path.exists(os.path.join(
            os.environ["GINGER_DATA_DIR"], "baseline.json")))
        self.assertEqual(len(self.row_texts(win)), 1)

    def test_banner_hidden_when_baseline_ok(self):
        self.server.snaps = [dict(SNAP_APP)]
        self.server.default_connections = CONNECTIONS
        win = self.make_window()
        self.assertFalse(win.baseline_banner.get_revealed())


class PackagingTests(unittest.TestCase):
    def test_app_id_and_version_consistent(self):
        root = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(root, "main.py")) as f:
            main_src = f.read()
        self.assertIn('APP_ID = "io.github.massivemarmot.Ginger"', main_src)
        m = re.search(r'VERSION = "([0-9.]+)"', main_src)
        self.assertIsNotNone(m)
        version = m.group(1)
        with open(os.path.join(root,
                               "io.github.massivemarmot.Ginger.yml")) as f:
            manifest = f.read()
        self.assertIn("io.github.massivemarmot.Ginger", manifest)
        with open(os.path.join(
                root, "data/io.github.massivemarmot.Ginger.desktop")) as f:
            desktop = f.read()
        self.assertIn("Icon=io.github.massivemarmot.Ginger", desktop)
        with open(os.path.join(
                root,
                "data/io.github.massivemarmot.Ginger.metainfo.xml")) as f:
            metainfo = f.read()
        self.assertIn("<id>io.github.massivemarmot.Ginger</id>", metainfo)
        self.assertIn('version="%s"' % version, metainfo)
        self.assertIn(
            '<launchable type="desktop-id">'
            "io.github.massivemarmot.Ginger.desktop</launchable>", metainfo)


if __name__ == "__main__":
    unittest.main()

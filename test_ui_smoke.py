# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd, RULE  # noqa: E402

import snapd_client  # noqa: E402
from snapd_client import PROMPTING_NOT_RUNNING  # noqa: E402

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

SNAP_APP = {"name": "firefox", "type": "app", "version": "1.0",
            "summary": "Browse the web", "apps": [{"name": "firefox"}]}
SNAP_BASE = {"name": "core24", "type": "base", "version": "2"}


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
        self.server.snaps = []
        self.server.posts = []
        self.server.responses = []
        self.win = self.main.Window(self.app)
        self.win.present()

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
        self.server.rules = [dict(RULE)]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        rows = [r for r in self.walk(win.detail_bin.get_child())
                if isinstance(r, Adw.ActionRow)]
        titles = [r.get_title() for r in rows]
        for title in ("Snap name", "Version", "Rules"):
            row = rows[titles.index(title)]
            self.assertIn("property", row.get_css_classes(), title)
            self.assertTrue(row.get_subtitle(), title)

    def add_dialog(self, win):
        buttons = [b for b in self.walk(win.detail_bin.get_child())
                   if isinstance(b, Gtk.Button)]
        add = [b for b in buttons
               if any("Add Rule" in l.get_text()
                      for l in self.find_labels(b, []))][0]
        add.emit("clicked")
        ctx = GLib.MainContext.default()
        for _ in range(5):
            ctx.iteration(False)
        dialogs = []
        for w in Gtk.Window.list_toplevels():
            if w is win:
                continue
            dialogs += [d for d in self.walk(w) if isinstance(d, Adw.Dialog)]
        return add, dialogs[0] if dialogs else None

    def find_alert(self):
        ctx = GLib.MainContext.default()
        for _ in range(10):
            found = []
            for w in Gtk.Window.list_toplevels():
                found += [d for d in self.walk(w)
                          if isinstance(d, Adw.AlertDialog)]
            if found:
                return found[0]
            ctx.iteration(False)
        return None

    def test_add_rule_dialog_opens(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        self.assertIsInstance(dialog, Adw.Dialog)
        self.assertIn("firefox", dialog.get_title())
        self.assertFalse(dialog.add_button.get_sensitive())
        if dialog in [d for w in Gtk.Window.list_toplevels()
                      for d in self.walk(w)
                      if isinstance(d, Adw.Dialog)]:
            dialog.force_close()

    def test_add_rule_disabled_for_not_installed(self):
        self.server.rules = [dict(RULE, snap="gone")]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(1))
        buttons = [b for b in self.walk(win.detail_bin.get_child())
                   if isinstance(b, Gtk.Button)]
        add = [b for b in buttons
               if any("Add Rule" in l.get_text()
                      for l in self.find_labels(b, []))][0]
        self.assertFalse(add.get_sensitive())
        self.assertIn("not installed", add.get_tooltip_text())

    def test_add_rule_validation(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        for bad, message in [("", ""),
                             ("relative/path", "absolute"),
                             ("/a/../b", "'..'"),
                             ("/a\nb", "control")]:
            dialog.entry_row.set_text(bad)
            self.assertFalse(dialog.add_button.get_sensitive(), bad)
            if message:
                self.assertIn(message, dialog.error_label.get_text(), bad)
        home = os.path.expanduser("~")
        dialog.entry_row.set_text("~/docs/**")
        self.assertTrue(dialog.add_button.get_sensitive())
        self.assertEqual(dialog.preview_label.get_text(),
                         "Will add: %s/docs/**" % home)
        if dialog in [d for w in Gtk.Window.list_toplevels()
                      for d in self.walk(w)
                      if isinstance(d, Adw.Dialog)]:
            dialog.force_close()

    def test_add_rule_submits(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        dialog.entry_row.set_text("/home/user/docs/**")
        dialog.add_button.emit("clicked")
        self.run_until(lambda: self.server.posts)
        self.assertEqual(len(self.server.posts), 1)
        path, body = self.server.posts[0]
        self.assertEqual(path, "/v2/interfaces/requests/rules")
        self.assertEqual(body, {
            "action": "add",
            "rule": {
                "snap": "firefox",
                "interface": "home",
                "constraints": {
                    "path-pattern": "/home/user/docs/**",
                    "permissions": {
                        "read": {"outcome": "allow", "lifespan": "forever"},
                    },
                },
            },
        })
        self.run_until(lambda: win.selected_snap == "firefox"
                       and "1 rule" in [l.get_text() for l in
                                         self.find_labels(win.snaps_list
                                                          .get_row_at_index(0),
                                                          [])])
        self.assertEqual(win.selected_snap, "firefox")

    def test_add_rule_snapd_error_inline(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "<b>conflict</b>&amp;",
                       "kind": "interfaces-requests-rule-conflict"},
        }))
        dialog.entry_row.set_text("/home/user/docs/**")
        dialog.add_button.emit("clicked")
        self.run_until(lambda: dialog.error_label.get_text() != "")
        self.assertEqual(dialog.error_label.get_text(), "<b>conflict</b>&amp;")
        self.assertTrue(dialog.get_visible())
        self.assertTrue(dialog.add_button.get_sensitive())
        dialog.entry_row.set_text("/home/user/other/**")
        self.server.rules = [dict(RULE)]
        dialog.add_button.emit("clicked")
        self.run_until(lambda: self.server.posts)
        self.assertEqual(len(self.server.posts), 1)
        if dialog in [d for w in Gtk.Window.list_toplevels()
                      for d in self.walk(w)
                      if isinstance(d, Adw.Dialog)]:
            dialog.force_close()

    def test_add_rule_broad_confirm(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        dialog.entry_row.set_text("~/**")
        dialog.add_button.emit("clicked")
        alert = self.find_alert()
        self.assertIsNotNone(alert)
        self.assertEqual(self.server.posts, [])
        alert.emit("response", "add")
        self.run_until(lambda: self.server.posts)
        self.assertEqual(len(self.server.posts), 1)
        if dialog in [d for w in Gtk.Window.list_toplevels()
                      for d in self.walk(w)
                      if isinstance(d, Adw.Dialog)]:
            dialog.force_close()

    def test_add_rule_broad_cancel(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        _, dialog = self.add_dialog(win)
        dialog.entry_row.set_text("~/**")
        dialog.add_button.emit("clicked")
        alert = self.find_alert()
        self.assertIsNotNone(alert)
        alert.emit("response", "cancel")
        self.run_until(lambda: not alert.get_visible())
        self.assertEqual(self.server.posts, [])
        self.assertTrue(dialog.add_button.get_sensitive())
        if dialog in [d for w in Gtk.Window.list_toplevels()
                      for d in self.walk(w)
                      if isinstance(d, Adw.Dialog)]:
            dialog.force_close()

    def test_add_rule_button_is_compact_pill(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list, win.snaps_list.get_row_at_index(0))
        buttons = [b for b in self.walk(win.detail_bin.get_child())
                   if isinstance(b, Gtk.Button)]
        add = [b for b in buttons
               if any("Add Rule" in l.get_text()
                      for l in self.find_labels(b, []))][0]
        self.assertEqual(add.get_halign(), Gtk.Align.CENTER)
        self.assertTrue(add.get_sensitive())

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

    def test_snap_with_rule_never_hidden(self):
        lib = {"name": "gtk-common-themes", "type": "app", "apps": []}
        self.server.rules = [dict(RULE, snap="gtk-common-themes")]
        self.server.snaps = [dict(SNAP_APP), lib]
        win = self.make_window()
        names = [t[0] for t in self.row_texts(win)]
        self.assertIn("gtk-common-themes", names)

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

    def test_list_includes_snaps_without_rules(self):
        self.server.rules = [dict(RULE)]
        self.server.snaps = [dict(SNAP_APP), dict(SNAP_BASE),
                             {"name": "nicotine-plus", "type": "app", "apps": [{"name": "nicotine-plus"}]}]
        win = self.make_window()
        texts = self.row_texts(win)
        names = [t[0] for t in texts]
        self.assertIn("firefox", names)
        self.assertIn("nicotine-plus", names)
        self.assertNotIn("core24", names)

    def test_rule_count_subtitle(self):
        self.server.rules = [dict(RULE)]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        texts = self.row_texts(win)
        self.assertIn("1 rule", texts[0])
        self.server.rules = []
        win.activate_action("win.refresh", None)
        texts = self.row_texts(win)
        self.assertIn("No rules", texts[0])

    def test_not_installed_snap_listed(self):
        self.server.rules = [dict(RULE, snap="gone")]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        flat = [t for texts in self.row_texts(win) for t in texts]
        self.assertIn("gone", flat)
        self.assertTrue(any("Not installed" in t for t in flat))

    def test_broad_warning_icon(self):
        broad = dict(RULE)
        broad["constraints"] = dict(RULE["constraints"],
                                    **{"path-pattern": "/**"})
        self.server.rules = [broad]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        row = win.snaps_list.get_row_at_index(0)
        images = [w for w in self.walk(row) if isinstance(w, Gtk.Image)
                  and w.get_icon_name() == "dialog-warning-symbolic"]
        self.assertEqual(len(images), 1)

    def test_search_by_name(self):
        self.server.snaps = [dict(SNAP_APP),
                             {"name": "thunderbird", "type": "app", "apps": [{"name": "thunderbird"}]}]
        win = self.make_window()
        win.query = "thunder"
        win.refresh_list()
        texts = self.row_texts(win)
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0][0], "thunderbird")

    def test_filter_only_with_rules(self):
        self.server.rules = [dict(RULE)]
        self.server.snaps = [dict(SNAP_APP),
                             {"name": "thunderbird", "type": "app", "apps": [{"name": "thunderbird"}]}]
        win = self.make_window()
        win.filter_check.set_active(True)
        texts = self.row_texts(win)
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0][0], "firefox")
        win.filter_check.set_active(False)
        self.assertEqual(len(self.row_texts(win)), 2)

    def test_selecting_snap_closes_filter(self):
        self.server.rules = [dict(RULE)]
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
        self.server.rules = [dict(RULE)]
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("firefox", texts)
        self.assertIn("Browse the web", texts)
        self.assertIn("1.0", texts)
        self.assertIn("/home/user/docs/**", texts)
        self.assertIn("read: allow / forever", texts)
        buttons = [b for b in self.walk(win.detail_bin.get_child())
                   if isinstance(b, Gtk.Button)]
        self.assertTrue(any("Add Rule" in (b.get_child() and
                          "".join(l.get_text() for l in self.find_labels(b, [])))
                          for b in buttons))

    def test_no_rules_detail(self):
        self.server.snaps = [dict(SNAP_APP)]
        win = self.make_window()
        win.on_snap_selected(win.snaps_list,
                             win.snaps_list.get_row_at_index(0))
        texts = [l.get_text() for l in
                 self.find_labels(win.detail_bin.get_child(), [])]
        self.assertIn("No path permissions", texts)

    def test_selection_and_query_survive_refresh(self):
        self.server.snaps = [dict(SNAP_APP),
                             {"name": "thunderbird", "type": "app", "apps": [{"name": "thunderbird"}]}]
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
        self.assertEqual(win.error_page.get_title(), "Could not reach snapd")

    def test_markup_in_snap_name_not_parsed(self):
        self.server.snaps = [{"name": "<b>evil</b>&amp;", "type": "app", "apps": [{"name": "x"}]}]
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

    def run_until(self, condition, timeout_ms=2000):
        ctx = GLib.MainContext.default()
        end = GLib.get_monotonic_time() + timeout_ms * 1000
        while not condition() and GLib.get_monotonic_time() < end:
            ctx.iteration(True)

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


if __name__ == "__main__":
    unittest.main()

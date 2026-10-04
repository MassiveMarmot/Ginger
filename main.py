import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk

from snapd_client import PROMPTING_NOT_RUNNING, Client, SnapdError

NOT_RUNNING_TEXT = ("Install the prompting-client snap and enable the "
                    "toggle in Security Center (App permissions tab).")
BREAKPOINT_WIDTH = 865.0
SIDEBAR_WIDTH_COLLAPSED = 280.0
SIDEBAR_WIDTH_MIN = 250.0


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Snap Path Permissions",
                         default_width=921, default_height=450)
        self.client = Client()
        self.grouped = {}
        self.selected = None

        self.sidebar_rows = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar_rows.connect("row-activated", self.on_snap_selected)

        self.content = Adw.Bin()

        sidebar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar.add_top_bar(sidebar_header)
        sidebar_scroller = Gtk.ScrolledWindow()
        sidebar_scroller.set_child(self.sidebar_rows)
        sidebar.set_content(sidebar_scroller)

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *a: self.load())
        self.add_action(refresh)
        sidebar_header.pack_start(Gtk.Button(
            icon_name="view-refresh-symbolic", action_name="win.refresh",
            tooltip_text="Refresh"))

        content_view = Adw.ToolbarView()
        content_header = Adw.HeaderBar()
        content_view.add_top_bar(content_header)
        content_view.set_content(self.content)

        self.split = Adw.OverlaySplitView(
            collapsed=False, show_sidebar=True,
            min_sidebar_width=SIDEBAR_WIDTH_MIN)
        self.split.set_sidebar(sidebar)
        self.split.set_content(content_view)
        self.set_content(self.split)

        self.setup_breakpoint()

    def setup_breakpoint(self):
        condition = Adw.BreakpointCondition.parse(
            "max-width: %d" % int(BREAKPOINT_WIDTH))
        breakpoint = Adw.Breakpoint(condition=condition)
        breakpoint.add_setter(self.split, "collapsed", True)
        breakpoint.add_setter(self.split, "max-sidebar-width",
                              SIDEBAR_WIDTH_COLLAPSED)
        self.add_breakpoint(breakpoint)

    def on_snap_selected(self, box, row):
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)
        self.selected = row.snap_name
        self.show_snap_rules(row.snap_name)

    def show_status_page(self, title, description, icon):
        page = Adw.StatusPage(
            title=title,
            description=GLib.markup_escape_text(description),
            icon_name=icon)
        if self.get_content() is self.split:
            bin_ = Adw.Bin()
            bin_.set_child(page)
            self.set_content(bin_)
        else:
            self.get_content().set_child(page)

    def show_rules(self, rules):
        grouped = {}
        for rule in rules:
            if isinstance(rule, dict):
                grouped.setdefault(str(rule.get("snap") or "unknown"),
                                   []).append(rule)
        if not self.get_content() is self.split:
            self.set_content(self.split)
        self.grouped = grouped
        if not grouped:
            self.selected = None
            self.content.set_child(Adw.StatusPage(
                title="No rules",
                description="No path permissions have been created yet.",
                icon_name="document-open-symbolic"))
            return
        self.rebuild_sidebar()
        if self.selected not in grouped:
            self.selected = sorted(grouped)[0]
        self.sidebar_rows.select_row(self.row_for(self.selected))
        self.show_snap_rules(self.selected)

    def row_for(self, snap_name):
        row = self.sidebar_rows.get_row_at_index(
            sorted(self.grouped).index(snap_name))
        return row

    def rebuild_sidebar(self):
        self.sidebar_rows.remove_all()
        for snap in sorted(self.grouped):
            row = Gtk.ListBoxRow()
            row.snap_name = snap
            label = Gtk.Label(label=snap, xalign=0, hexpand=True,
                              use_markup=False)
            box = Gtk.Box(margin_top=12, margin_bottom=12,
                          margin_start=6, margin_end=6, spacing=12)
            box.append(label)
            row.set_child(box)
            self.sidebar_rows.append(row)

    def show_snap_rules(self, snap_name):
        rules = self.grouped.get(snap_name, [])
        group = Adw.PreferencesGroup(
            title=GLib.markup_escape_text(snap_name))
        for rule in rules:
            group.add(self.rule_row(rule))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(group)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(box)
        self.content.set_child(scroll)

    def rule_row(self, rule):
        constraints = rule.get("constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        perms = constraints.get("permissions")
        perms = perms if isinstance(perms, dict) else {}
        subtitle = "  ".join(
            "%s: %s / %s" % (name, spec.get("outcome"), spec.get("lifespan"))
            for name, spec in perms.items()
            if isinstance(spec, dict))
        return Adw.ActionRow(title=str(constraints.get("path-pattern") or "?"),
                             subtitle=subtitle or "no permissions",
                             use_markup=False)

    def load(self):
        try:
            rules = self.client.list_rules()
        except SnapdError as e:
            if e.kind == PROMPTING_NOT_RUNNING:
                self.show_status_page("AppArmor prompting is not enabled",
                                      NOT_RUNNING_TEXT,
                                      "security-low-symbolic")
            elif e.kind == "connection-failed":
                self.show_status_page("Could not reach snapd", e.message,
                                      "network-error-symbolic")
            else:
                self.show_status_page("snapd returned an error", e.message,
                                      "dialog-warning-symbolic")
            return
        self.show_rules(rules)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.massivemarmot.SnapPathPermissions")

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = Window(self)
        win.present()
        win.load()


def main():
    App().run(sys.argv)


if __name__ == "__main__":
    main()

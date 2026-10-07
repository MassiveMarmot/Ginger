# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

import baseline
import interfaces
from snapd_client import Client, SnapdError

APP_ID = "io.github.massivemarmot.Ginger"
VERSION = "0.1.0"
REPO_URL = "https://github.com/MassiveMarmot/Ginger"
FUNNEL_ICON = "funnel-symbolic"

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "icons")


def register_icon_search_path():
    if not os.path.isdir(ICONS_DIR):
        return
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    theme.add_search_path(ICONS_DIR)
    if not theme.has_icon(FUNNEL_ICON):
        print("Failed to load icon %s from %s" % (FUNNEL_ICON, ICONS_DIR),
              file=sys.stderr)


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Ginger",
                         default_width=921, default_height=450)
        self.client = Client()
        self.snaps = []
        self.selected_snap = None
        self.query = ""
        self.show_libraries = False
        self.show_all_interfaces = False
        self.connections = {}
        self.connections_by_snap = {}
        self.baselines = {}

        self.sidebar_rows = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar_rows.connect("row-activated", self.on_page_selected)

        sidebar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar.add_top_bar(sidebar_header)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(self.sidebar_rows)
        sidebar.set_content(scroller)

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *a: self.load())
        self.add_action(refresh)
        sidebar_header.pack_start(Gtk.Button(
            icon_name="view-refresh-symbolic", action_name="win.refresh",
            tooltip_text="Refresh"))

        menu = Gio.Menu()
        menu.append("About", "win.about")
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *a: self.show_about())
        self.add_action(about)
        sidebar_header.pack_end(Gtk.MenuButton(
            icon_name="open-menu-symbolic", menu_model=menu,
            tooltip_text="Main Menu"))

        self.main_split = Adw.OverlaySplitView(
            collapsed=False, show_sidebar=True, min_sidebar_width=250)

        self.snaps_page = self.build_snaps_page()
        self.error_page = Adw.StatusPage(icon_name="network-error-symbolic")
        self.error_wrapper = self.page_with_header(self.error_page)

        self.page_stack = Gtk.Stack(vhomogeneous=False)
        self.page_stack.add_named(self.snaps_page, "snaps")
        self.page_stack.add_named(self.error_wrapper, "error")

        self.build_sidebar()
        self.sidebar_rows.select_row(self.sidebar_rows.get_row_at_index(0))

        self.main_split.set_sidebar(sidebar)
        self.main_split.set_content(self.page_stack)
        self.set_content(self.main_split)

        self.setup_breakpoints()
        self.on_page_selected(self.sidebar_rows,
                              self.sidebar_rows.get_row_at_index(0))

    def page_with_header(self, page):
        header = Adw.HeaderBar()
        header.pack_start(self.make_sidebar_toggle())
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(page)
        view.set_content(scroller)
        return view

    def make_sidebar_toggle(self):
        button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text="Show Sidebar")
        self.main_split.bind_property(
            "show-sidebar", button, "active",
            GObject.BindingFlags.BIDIRECTIONAL
            | GObject.BindingFlags.SYNC_CREATE)
        self.main_split.bind_property(
            "collapsed", button, "visible",
            GObject.BindingFlags.SYNC_CREATE)
        return button

    def build_sidebar(self):
        self.sidebar_rows.remove_all()
        for name, icon in (("Snaps", "application-x-executable-symbolic"),):
            row = Gtk.ListBoxRow()
            row.page_name = name
            box = Gtk.Box(margin_top=12, margin_bottom=12,
                          margin_start=6, margin_end=6, spacing=12)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=name, xalign=0, hexpand=True,
                                 use_markup=False))
            row.set_child(box)
            self.sidebar_rows.append(row)

    def show_about(self):
        Adw.AboutDialog(application_name="Ginger",
                        application_icon=APP_ID, version=VERSION,
                        comments="Ginger for Snaps",
                        website=REPO_URL,
                        issue_url=REPO_URL + "/issues",
                        license_type=Gtk.License.GPL_3_0).present(self)

    def on_page_selected(self, box, row):
        if self.main_split.get_collapsed():
            self.main_split.set_show_sidebar(False)
        self.page_stack.set_visible_child_name("snaps")

    def snap_names(self):
        names = {}
        for s in self.snaps:
            if isinstance(s, dict) and s.get("type") in (None, "app"):
                snap = dict(s)
                snap["has_apps"] = bool(s.get("apps"))
                names[str(s.get("name") or "?")] = snap
        return names

    def visible_snaps(self):
        out = []
        for name in sorted(self.snap_map):
            snap = self.snap_map[name]
            if not self.show_libraries and not snap.get("has_apps"):
                continue
            if self.query and self.query.lower() not in name.lower():
                continue
            out.append(name)
        return out

    def build_snaps_page(self):
        self.list_header = Adw.HeaderBar()
        self.search_button = Gtk.ToggleButton(
            icon_name="system-search-symbolic", tooltip_text="Search")
        self.search_button.connect("toggled", self.on_search_toggled)
        self.sidebar_toggle = self.make_sidebar_toggle()
        self.list_header.pack_start(self.sidebar_toggle)
        self.list_header.pack_start(self.search_button)

        self.list_title = Gtk.Label(
            label="Snaps", css_classes=["heading"], hexpand=True)
        self.list_header.set_title_widget(self.list_title)

        self.filter_button = Gtk.ToggleButton(
            icon_name=FUNNEL_ICON, tooltip_text="Filter")
        self.filter_button.connect("toggled", self.on_filter_toggled)
        self.list_header.pack_end(self.filter_button)

        self.search_bar = Gtk.SearchBar(hexpand=True)
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_bar.set_child(self.search_entry)

        self.snaps_list = Gtk.ListBox(
            css_classes=["navigation-sidebar"], activate_on_single_click=True)
        self.snaps_list.connect("row-activated", self.on_snap_selected)

        self.filter_panel = self.build_filter_panel()

        list_view = Adw.ToolbarView()
        list_view.add_top_bar(self.list_header)
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_box.append(self.search_bar)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(self.snaps_list)
        list_box.append(scroller)
        list_view.set_content(list_box)

        self.detail_pane = Adw.ToolbarView()
        detail_header = Adw.HeaderBar(show_title=False)
        self.detail_pane.add_top_bar(detail_header)
        self.detail_bin = Adw.Bin()
        scroller2 = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller2.set_child(self.detail_bin)
        self.detail_pane.set_content(scroller2)

        list_page = Adw.NavigationPage(title="Snaps")
        list_page.set_child(list_view)
        self.detail_page = Adw.NavigationPage(title="Snap")
        self.detail_page.set_child(self.detail_pane)
        self.detail_split = Adw.NavigationSplitView(
            sidebar_width_fraction=0.5)
        self.detail_split.set_sidebar(list_page)
        self.detail_split.set_content(self.detail_page)
        return self.detail_split

    def build_filter_panel(self):
        lib_check = Gtk.CheckButton(css_classes=["selection-mode"])
        lib_check.connect("toggled", self.on_lib_check_toggled)
        lib_row = Adw.ActionRow(title="Show libraries and runtimes",
                                use_markup=False)
        lib_row.add_suffix(lib_check)
        lib_row.set_activatable_widget(lib_check)
        all_check = Gtk.CheckButton(css_classes=["selection-mode"])
        all_check.connect("toggled", self.on_all_check_toggled)
        all_row = Adw.ActionRow(title="Show all interfaces",
                                use_markup=False)
        all_row.add_suffix(all_check)
        all_row.set_activatable_widget(all_check)
        group = Adw.PreferencesGroup()
        group.add(lib_row)
        group.add(all_row)
        self.lib_check = lib_check
        self.all_check = all_check
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        view.add_top_bar(header)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(group)
        view.set_content(scroller)
        return view

    def on_lib_check_toggled(self, check):
        self.show_libraries = check.get_active()
        self.refresh_list()

    def on_all_check_toggled(self, check):
        self.show_all_interfaces = check.get_active()
        self.update_detail()

    def on_filter_toggled(self, button):
        active = button.get_active()
        self.detail_page.set_child(
            self.filter_panel if active else self.detail_pane)
        if active:
            self.detail_split.set_show_content(True)
        self.refresh_list()

    def on_search_toggled(self, button):
        self.search_bar.set_search_mode(button.get_active())

    def on_search_changed(self, entry):
        self.query = entry.get_text()
        self.refresh_list()

    def refresh_list(self):
        self.snap_map = self.snap_names()
        self.snaps_list.remove_all()
        self.rows_by_name = {}
        for name in self.visible_snaps():
            row = self.snap_row(name)
            self.rows_by_name[name] = row
            self.snaps_list.append(row)
        self.update_detail()
        self.highlight_selected_row()

    def snap_row(self, name):
        connections = self.connections_by_snap.get(name)
        subtitle = ""
        if connections is not None:
            connected, available = interfaces.counts(connections, name)
            subtitle = "%d connected, %d available" % (connected, available)
        row = Adw.ActionRow(title=name, subtitle=subtitle, use_markup=False)
        row.set_activatable(True)
        row.snap_name = name
        row.add_prefix(Gtk.Image(icon_name="application-x-executable-symbolic"))
        return row

    def highlight_selected_row(self):
        row = self.rows_by_name.get(self.selected_snap)
        if row is not None:
            self.snaps_list.select_row(row)

    def on_snap_selected(self, box, row, from_user=True):
        if row is None or not hasattr(row, "snap_name"):
            return
        self.selected_snap = row.snap_name
        if self.filter_button.get_active():
            self.filter_button.set_active(False)
        if from_user:
            self.detail_split.set_show_content(True)
        self.update_detail()
        self.highlight_selected_row()

    def update_detail(self):
        snap = self.snap_map.get(self.selected_snap)
        if snap is None:
            self.detail_bin.set_child(Adw.StatusPage(
                title="No snap selected",
                icon_name="document-open-symbolic"))
            return
        name = self.selected_snap
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=24, margin_bottom=24,
                      margin_start=12, margin_end=12,
                      valign=Gtk.Align.CENTER)
        box.append(Gtk.Image(
            icon_name="application-x-executable-symbolic",
            pixel_size=96, valign=Gtk.Align.START))
        title = Gtk.Label(css_classes=["title-2"], use_markup=False)
        title.set_text(name)
        box.append(title)
        if snap.get("summary"):
            summary = Gtk.Label(css_classes=["dim-label"],
                                ellipsize=Pango.EllipsizeMode.END,
                                use_markup=False)
            summary.set_text(str(snap.get("summary")))
            box.append(summary)
        card = Adw.PreferencesGroup()
        snap_name_row = Adw.ActionRow(title="Snap name", use_markup=False,
                                      css_classes=["property"])
        snap_name_row.set_subtitle(name)
        copy = Gtk.Button(icon_name="edit-copy-symbolic",
                          css_classes=["flat"])
        copy.connect("clicked", self.copy_text, name)
        snap_name_row.add_suffix(copy)
        snap_name_row.set_activatable_widget(copy)
        card.add(snap_name_row)
        if snap.get("version"):
            version_row = Adw.ActionRow(
                title="Version", use_markup=False,
                css_classes=["property"],
                subtitle=str(snap.get("version")))
            card.add(version_row)
        box.append(card)
        connections = self.connections_by_snap.get(name)
        if connections is not None:
            box.append(self.permissions_group(name, connections))
        self.detail_bin.set_child(box)

    def permissions_group(self, name, connections):
        group = Adw.PreferencesGroup(
            title=GLib.markup_escape_text("Permissions"))
        plugs = interfaces.derive_plugs(connections, name,
                                         show_all=self.show_all_interfaces)
        if not plugs:
            group.add(Adw.ActionRow(title="No interfaces", use_markup=False))
            return group
        for plug in plugs:
            row = Adw.SwitchRow(title=plug["name"],
                                subtitle=plug["interface"] + " \u00b7 "
                                + plug["state"],
                                use_markup=False)
            row.set_active(plug["connected"])
            if plug["connected"]:
                if plug["conn_slot"] is not None:
                    row.plug_slot = plug["conn_slot"]
            elif plug["n_slots"] == 0:
                row.set_subtitle(plug["interface"] + " \u00b7 No slot available")
            elif plug["n_slots"] > 1:
                row.set_subtitle(plug["interface"]
                                + " \u00b7 Several slots available")
            elif plug["slot"] is not None:
                row.plug_slot = plug["slot"]
            if plug["tier"] == 3 and not plug["connected"]:
                row.set_subtitle(plug["interface"]
                                + " \u00b7 " + plug["state"]
                                + " \u00b7 " + "Connect not offered")
            row.plug_info = plug
            row.set_sensitive(False)
            group.add(row)
        return group

    def copy_text(self, button, text):
        self.get_clipboard().set_text(text)

    def show_error(self, title, message, icon):
        self.error_page.set_title(title)
        self.error_page.set_description(GLib.markup_escape_text(message))
        self.error_page.set_icon_name(icon)
        self.page_stack.set_visible_child_name("error")

    def load(self):
        try:
            snaps = self.client.list_snaps()
            self.connections = self.client.list_connections()
        except SnapdError as e:
            if e.kind == "connection-failed":
                self.show_error("Could not reach snapd", e.message,
                                "network-error-symbolic")
            else:
                self.show_error("snapd returned an error", e.message,
                                "dialog-warning-symbolic")
            return
        try:
            self.baselines = baseline.load()
        except baseline.BaselineError as e:
            self.baselines = {}
            self.show_error("Could not read the saved original state",
                            str(e), "dialog-warning-symbolic")
            return
        self.snaps = [s for s in snaps if isinstance(s, dict)]
        self.connections_by_snap = {}
        for name in self.snap_names():
            self.connections_by_snap[name] = self.connections
        new = baseline.capture_new(self.baselines, self.connections_by_snap)
        if new:
            self.baselines.update(new)
            baseline.save_snaps(self.baselines)
        if self.selected_snap not in self.snap_names():
            self.selected_snap = None
        if self.search_entry.get_text() != self.query:
            self.search_entry.set_text(self.query)
        self.page_stack.set_visible_child_name("snaps")
        self.refresh_list()
        if self.selected_snap is None:
            first = self.snaps_list.get_row_at_index(0)
            if first is not None and hasattr(first, "snap_name"):
                self.on_snap_selected(self.snaps_list, first,
                                      from_user=False)

    def setup_breakpoints(self):
        b1 = Adw.Breakpoint(condition=Adw.BreakpointCondition.parse(
            "max-width: 865"))
        b1.add_setter(self.main_split, "collapsed", True)
        b1.add_setter(self.main_split, "max-sidebar-width", 280)
        self.add_breakpoint(b1)
        b2 = Adw.Breakpoint(condition=Adw.BreakpointCondition.parse(
            "max-width: 600"))
        b2.add_setter(self.detail_split, "collapsed", True)
        b2.add_setter(self.main_split, "collapsed", True)
        b2.add_setter(self.main_split, "max-sidebar-width", 280)
        self.add_breakpoint(b2)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        register_icon_search_path()

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

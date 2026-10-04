import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, GObject, Gtk

from path_validation import is_broad_pattern
from snapd_client import PROMPTING_NOT_RUNNING, Client, SnapdError

NOT_RUNNING_TEXT = ("Install the prompting-client snap and enable the "
                    "toggle in Security Center (App permissions tab).")
APP_ID = "io.github.massivemarmot.SnapPathPermissions"


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Snap Path Permissions",
                         default_width=921, default_height=450)
        self.client = Client()
        self.rules = []
        self.selected_rule = None
        self.query = ""
        self.filter_snaps = set()
        self.select_mode = False
        self.selected_ids = set()

        self.sidebar_rows = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar_rows.connect("row-activated", self.on_page_selected)

        sidebar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar.add_top_bar(sidebar_header)
        scroller = Gtk.ScrolledWindow()
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

        self.rules_page = self.build_rules_page()
        self.add_page = Adw.StatusPage(
            title="Add Rule",
            description="Coming in the next milestone.",
            icon_name="list-add-symbolic")

        self.content_stack = Gtk.Stack(vhomogeneous=False)
        self.content_stack.add_named(self.rules_page, "rules")
        self.content_stack.add_named(self.add_page, "add")
        self.error_page = Adw.StatusPage(icon_name="network-error-symbolic")

        self.page_stack = Gtk.Stack(vhomogeneous=False)
        self.page_stack.add_named(self.content_stack, "content")
        self.page_stack.add_named(self.error_page, "error")

        self.build_sidebar()

        self.main_split = Adw.OverlaySplitView(
            collapsed=False, show_sidebar=True, min_sidebar_width=250)
        self.main_split.set_sidebar(sidebar)
        self.main_split.set_content(self.page_stack)
        self.set_content(self.main_split)

        self.setup_breakpoints()
        self.on_page_selected(self.sidebar_rows, self.sidebar_rows.get_row_at_index(0))

    def build_sidebar(self):
        self.sidebar_rows.remove_all()
        for name, icon in (("Rules", "emblem-default-symbolic"),
                           ("Add Rule", "list-add-symbolic")):
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
        Adw.AboutDialog(application_name="Snap Path Permissions",
                        application_icon=APP_ID, version="0.1",
                        comments="View and manage snap path permissions.",
                        license_type=Gtk.License.GPL_3_0).present(self)

    def on_page_selected(self, box, row):
        if self.main_split.get_collapsed():
            self.main_split.set_show_sidebar(False)
        name = row.page_name if row else "Rules"
        self.page_stack.set_visible_child_name("content")
        self.content_stack.set_visible_child_name(
            "add" if name == "Add Rule" else "rules")

    def build_rules_page(self):
        self.sidebar_toggle = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic", tooltip_text="Show Sidebar",
            visible=False)
        self.sidebar_toggle.connect("toggled", lambda b: (
            self.main_split.set_show_sidebar(b.get_active())))
        self.list_header = Adw.HeaderBar()
        self.search_button = Gtk.ToggleButton(
            icon_name="system-search-symbolic", tooltip_text="Search")
        self.search_button.connect("toggled", self.on_search_toggled)
        self.list_header.pack_start(self.sidebar_toggle)
        self.list_header.pack_start(self.search_button)

        self.list_title = Gtk.Label(
            label="Rules", css_classes=["heading"], hexpand=True)
        self.list_header.set_title_widget(self.list_title)

        self.select_button = Gtk.ToggleButton(
            icon_name="object-select-symbolic", tooltip_text="Select")
        self.select_button.connect("toggled", self.on_select_toggled)
        self.filter_button = Gtk.ToggleButton(
            icon_name="funnel-symbolic", tooltip_text="Filter")
        self.filter_button.connect("toggled", self.on_filter_toggled)
        self.list_header.pack_end(self.filter_button)
        self.list_header.pack_end(self.select_button)

        self.search_bar = Gtk.SearchBar(hexpand=True)
        self.search_entry = Gtk.SearchEntry(hexpand=True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_bar.set_child(self.search_entry)

        self.rules_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.rules_list.connect("row-activated", self.on_rule_selected)

        self.filter_panel = self.build_filter_panel()

        list_view = Adw.ToolbarView()
        list_view.add_top_bar(self.list_header)
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_box.append(self.search_bar)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.rules_list)
        list_box.append(scroller)
        list_view.set_content(list_box)

        self.detail_pane = Adw.ToolbarView()
        detail_header = Adw.HeaderBar()
        self.detail_pane.add_top_bar(detail_header)
        self.detail_bin = Adw.Bin()
        scroller2 = Gtk.ScrolledWindow()
        scroller2.set_child(self.detail_bin)
        self.detail_pane.set_content(scroller2)

        self.detail_split = Adw.OverlaySplitView(
            collapsed=False, show_sidebar=True, min_sidebar_width=280)
        self.detail_split.set_sidebar(list_view)
        self.detail_split.set_content(self.detail_pane)

        rules_toolbar = Adw.ToolbarView()
        rules_toolbar.set_content(self.detail_split)
        return rules_toolbar

    def build_filter_panel(self):
        self.filter_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.filter_list.connect("row-activated", self.on_filter_row)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(Gtk.Label(label="Filter by snap", css_classes=["heading"]))
        box.append(self.filter_list)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(box)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        view.add_top_bar(header)
        view.set_content(scroller)
        return view

    def on_filter_row(self, box, row):
        if row.snap_name in self.filter_snaps:
            self.filter_snaps.discard(row.snap_name)
            row.check.set_active(False)
        else:
            self.filter_snaps.add(row.snap_name)
            row.check.set_active(True)
        self.refresh_list()

    def on_filter_toggled(self, button):
        active = button.get_active()
        if active:
            self.detail_split.set_content(self.filter_panel)
        else:
            self.detail_split.set_content(self.detail_pane)
        self.refresh_list()

    def on_search_toggled(self, button):
        self.search_bar.set_search_mode(button.get_active())

    def on_search_changed(self, entry):
        self.query = entry.get_text()
        self.refresh_list()

    def on_select_toggled(self, button):
        self.select_mode = button.get_active()
        self.refresh_list()

    def visible_rules(self):
        out = []
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            snap = str(rule.get("snap") or "")
            pattern = str((rule.get("constraints") or {}).get(
                "path-pattern") or "")
            if self.query and self.query.lower() not in snap.lower() \
                    and self.query.lower() not in pattern.lower():
                continue
            if self.filter_snaps and snap not in self.filter_snaps:
                continue
            out.append(rule)
        return out

    def refresh_list(self):
        self.rules_list.remove_all()
        visible = self.visible_rules()
        for rule in visible:
            self.rules_list.append(self.rule_row(rule))
        if self.select_mode:
            count = sum(1 for r in visible
                        if str(r.get("id")) in self.selected_ids)
            self.list_title.set_label("%d Selected" % count)
        else:
            self.list_title.set_label("Rules")
        self.update_detail()

    def rule_row(self, rule):
        constraints = rule.get("constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        perms = constraints.get("permissions")
        perms = perms if isinstance(perms, dict) else {}
        subtitle = "  ".join(
            "%s: %s / %s" % (name, spec.get("outcome"), spec.get("lifespan"))
            for name, spec in perms.items() if isinstance(spec, dict))
        row = Adw.ActionRow(title=str(rule.get("snap") or "?"),
                            subtitle=str(constraints.get("path-pattern")
                                         or "?"), use_markup=False)
        row.rule = rule
        row.add_prefix(Gtk.Image(icon_name="application-x-executable-symbolic"))
        if is_broad_pattern(str(constraints.get("path-pattern") or "")):
            row.add_suffix(Gtk.Image(
                icon_name="dialog-warning-symbolic",
                tooltip_text="Broad pattern"))
        info = Gtk.Label(label=subtitle or "no permissions",
                         css_classes=["caption"], use_markup=False)
        row.add_suffix(info)
        if self.select_mode:
            check = Gtk.CheckButton(css_classes=["circular"])
            check.connect("toggled", self.on_row_checked, str(rule.get("id")))
            check.set_active(str(rule.get("id")) in self.selected_ids)
            row.add_suffix(check)
        return row

    def on_row_checked(self, check, rule_id):
        if check.get_active():
            self.selected_ids.add(rule_id)
        else:
            self.selected_ids.discard(rule_id)
        self.refresh_list()

    def on_rule_selected(self, box, row):
        if row is None or not hasattr(row, "rule"):
            return
        self.selected_rule = row.rule
        self.update_detail()

    def update_detail(self):
        rule = self.selected_rule
        if not isinstance(rule, dict):
            self.detail_bin.set_child(Adw.StatusPage(
                title="No rule selected",
                icon_name="document-open-symbolic"))
            return
        constraints = rule.get("constraints")
        constraints = constraints if isinstance(constraints, dict) else {}
        pattern = str(constraints.get("path-pattern") or "?")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=24, margin_bottom=24,
                      margin_start=12, margin_end=12,
                      valign=Gtk.Align.CENTER)
        box.append(Gtk.Image(
            icon_name="application-x-executable-symbolic",
            pixel_size=96, valign=Gtk.Align.START))
        name = Gtk.Label(css_classes=["title-2"], use_markup=False)
        name.set_text(str(rule.get("snap") or "?"))
        box.append(name)
        box.append(Gtk.Label(label=pattern, css_classes=["dim-label"],
                             use_markup=False))
        card = Adw.PreferencesGroup()
        for label_text, value in (
                ("Rule id", str(rule.get("id") or "?")),
                ("Interface", str(rule.get("interface") or "?")),
                ("Path pattern", pattern)):
            row = Adw.ActionRow(title=label_text, subtitle=value,
                                use_markup=False)
            copy = Gtk.Button(icon_name="edit-copy-symbolic",
                              css_classes=["flat"])
            copy.connect("clicked", self.copy_text, value)
            row.add_suffix(copy)
            row.set_activatable_widget(copy)
            card.add(row)
        box.append(card)
        perms = constraints.get("permissions")
        perms = perms if isinstance(perms, dict) else {}
        for name_, spec in perms.items():
            spec = spec if isinstance(spec, dict) else {}
            expander = Adw.ExpanderRow(
                title=name_, subtitle="%s / %s" % (
                    spec.get("outcome"), spec.get("lifespan")),
                use_markup=False)
            for k in ("expiration", "session-id"):
                if spec.get(k):
                    expander.add_row(Adw.ActionRow(
                        title=k, subtitle=str(spec[k]), use_markup=False))
            card.add(expander)
        self.detail_bin.set_child(box)

    def copy_text(self, button, text):
        self.get_clipboard().set_text(text)

    def show_error(self, title, message, icon):
        self.error_page.set_title(title)
        self.error_page.set_description(GLib.markup_escape_text(message))
        self.error_page.set_icon_name(icon)
        self.page_stack.set_visible_child_name("error")

    def load(self):
        try:
            rules = self.client.list_rules()
        except SnapdError as e:
            if e.kind == PROMPTING_NOT_RUNNING:
                self.show_error("AppArmor prompting is not enabled",
                                NOT_RUNNING_TEXT, "security-low-symbolic")
            elif e.kind == "connection-failed":
                self.show_error("Could not reach snapd", e.message,
                                "network-error-symbolic")
            else:
                self.show_error("snapd returned an error", e.message,
                                "dialog-warning-symbolic")
            return
        self.rules = [r for r in rules if isinstance(r, dict)]
        self.selected_rule = None
        self.filter_snaps = set()
        self.select_mode = False
        self.selected_ids = set()
        self.select_button.set_active(False)
        self.rebuild_filter_panel()
        self.page_stack.set_visible_child_name("content")
        self.refresh_list()

    def rebuild_filter_panel(self):
        self.filter_list.remove_all()
        for snap in sorted({str(r.get("snap") or "unknown")
                            for r in self.rules}):
            row = Gtk.ListBoxRow()
            row.snap_name = snap
            check = Gtk.CheckButton(css_classes=["circular"])
            row.check = check
            box = Gtk.Box(margin_top=12, margin_bottom=12,
                          margin_start=6, margin_end=6, spacing=12)
            box.append(Gtk.Label(label=snap, xalign=0, hexpand=True,
                                 use_markup=False))
            box.append(check)
            row.set_child(box)
            self.filter_list.append(row)

    def setup_breakpoints(self):
        b1 = Adw.Breakpoint(condition=Adw.BreakpointCondition.parse(
            "max-width: 865"))
        b1.add_setter(self.main_split, "collapsed", True)
        b1.add_setter(self.main_split, "max-sidebar-width", 280)
        b1.add_setter(self.sidebar_toggle, "visible", True)
        self.add_breakpoint(b1)
        b2 = Adw.Breakpoint(condition=Adw.BreakpointCondition.parse(
            "max-width: 600"))
        b2.add_setter(self.detail_split, "collapsed", True)
        self.add_breakpoint(b2)
        self.main_split.bind_property(
            "show-sidebar", self.sidebar_toggle, "active",
            GObject.BindingFlags.BIDIRECTIONAL)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

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

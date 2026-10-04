import sys

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk

from snapd_client import PROMPTING_NOT_RUNNING, Client, SnapdError

NOT_RUNNING_TEXT = ("Install the prompting-client snap and enable the "
                    "toggle in Security Center (App permissions tab).")


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Snap Path Permissions",
                         default_width=700, default_height=500)
        self.client = Client()
        self.bin = Adw.Bin()
        header = Gtk.HeaderBar()
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.bin)
        self.set_content(view)

        refresh = Gio.SimpleAction.new("refresh", None)
        refresh.connect("activate", lambda *a: self.load())
        self.add_action(refresh)
        header.pack_start(Gtk.Button(
            icon_name="view-refresh-symbolic", action_name="win.refresh",
            tooltip_text="Refresh"))

    def show_status_page(self, title, description, icon):
        self.bin.set_child(Adw.StatusPage(
            title=title, description=GLib.markup_escape_text(description),
            icon_name=icon))

    def show_rules(self, rules):
        grouped = {}
        for rule in rules:
            if isinstance(rule, dict):
                grouped.setdefault(str(rule.get("snap") or "unknown"),
                                   []).append(rule)
        if not grouped:
            self.show_status_page(
                "No rules",
                "No path permissions have been created yet.",
                "document-open-symbolic")
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(box)
        for snap in sorted(grouped):
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(snap))
            for rule in grouped[snap]:
                group.add(self.rule_row(rule))
            box.append(group)
        self.bin.set_child(scroll)

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
                                      NOT_RUNNING_TEXT, "security-low-symbolic")
            else:
                self.show_status_page("Could not reach snapd", e.message,
                                      "network-error-symbolic")
            return
        self.show_rules(rules)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.massivemarmot.SnapPathPermissions")

    def do_activate(self):
        win = Window(self)
        win.present()
        win.load()


def main():
    App().run(sys.argv)


if __name__ == "__main__":
    main()

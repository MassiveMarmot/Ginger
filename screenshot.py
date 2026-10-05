# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_snapd_client import MockSnapd, RULE

import gi
gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib

SCHEMES = {"light": Adw.ColorScheme.FORCE_LIGHT,
           "dark": Adw.ColorScheme.FORCE_DARK}


def main():
    tmpdir = tempfile.mkdtemp()
    os.environ["SNAPD_SOCKET"] = os.path.join(tmpdir, "s.socket")
    server = MockSnapd(os.environ["SNAPD_SOCKET"])
    server.rules = [
        dict(RULE),
        dict(RULE, id="2", snap="thunderbird",
             constraints=dict(RULE["constraints"],
                               **{"path-pattern": "~/Documents/**"})),
        dict(RULE, id="3", snap="firefox",
             constraints=dict(RULE["constraints"],
                               **{"path-pattern": "/home/**"})),
    ]
    server.snaps = [
        {"name": "firefox", "type": "app", "version": "1.0",
         "summary": "Browse the web", "apps": [{"name": "firefox"}]},
        {"name": "thunderbird", "type": "app", "version": "1.0",
         "summary": "Email, newsfeed, chat and calendaring client",
         "apps": [{"name": "thunderbird"}]},
        {"name": "prompting-client", "type": "app", "version": "0.1",
         "summary": "AppArmor prompting client", "apps": [{"name": "x"}]},
    ]

    import main
    Adw.StyleManager.get_default().set_color_scheme(SCHEMES[sys.argv[1]])
    app = main.App()
    app.connect("activate", on_activate)
    app.run([])


def on_activate(app):
    win = app.props.active_window
    if not win:
        win = app.create_window() if hasattr(app, "create_window") else None
    if win is None:
        win = main_module.Window(app)
    win.present()
    win.load()


main_module = None


if __name__ == "__main__":
    import main as main_module
    main()

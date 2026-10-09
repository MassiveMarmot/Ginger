# Ginger for Snaps

Ginger is a GNOME app that lists the snaps installed on your system and lets
you review and change each snap's interface connections: the permissions
behind snap connect and snap disconnect.

## Installing the Flatpak bundle

```sh
flatpak install --user ginger-0.1.0.flatpak
flatpak run io.github.massivemarmot.Ginger
```

To build it yourself from the repository root:

```sh
flatpak-builder --user --install --force-clean build-dir io.github.massivemarmot.Ginger.yml
```

And to produce the bundle:

```sh
flatpak build-bundle ~/.local/share/flatpak ginger-0.1.0.flatpak io.github.massivemarmot.Ginger
```

## About the socket permission

Ginger's only privilege is read/write access to `/run/snapd.socket`, granted
with `--filesystem=/run/snapd.socket` in the Flatpak manifest. Through it,
Ginger lists installed snaps and their interface connections. It uses that
access for nothing else, and the app has no network permission at all.

You can inspect the permission at any time:

```sh
flatpak info --show-permissions io.github.massivemarmot.Ginger
```

And revoke it (Ginger will then report that it cannot reach snapd):

```sh
flatpak override --user --nofilesystem=/run/snapd.socket io.github.massivemarmot.Ginger
```

## Privacy

- No network access, no telemetry, no analytics.
- Nothing is logged; no files are written outside the app's own data dir.

## Review checklist

- Every overlay child has an explicit alignment.
- UI tests include at least one pointer-pick check.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

This project is developed with AI assistance.

Ginger is not affiliated with or endorsed by Canonical. Snap and Ubuntu are
trademarks of Canonical Ltd.

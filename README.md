# Steward - Manage your Snaps

Steward is a GNOME app that lists the snaps installed on your system and lets
you review and manage each snap's path permissions (AppArmor prompting
rules). Its main feature is adding a read permission for a specific path by
typing or pasting a path pattern.

## Requirements

- Ubuntu with AppArmor prompting enabled:
  - the `prompting-client` snap installed, and
  - the toggle turned on in Security Center (App permissions tab).

## Installing the Flatpak bundle

```sh
flatpak install --user steward-0.1.0.flatpak
flatpak run io.github.massivemarmot.Steward
```

To build it yourself from the repository root:

```sh
flatpak-builder --user --install --force-clean build-dir io.github.massivemarmot.Steward.yml
```

And to produce the bundle:

```sh
flatpak build-bundle ~/.local/share/flatpak steward-0.1.0.flatpak io.github.massivemarmot.Steward
```

## About the socket permission

Steward's only privilege is read/write access to `/run/snapd.socket`, granted
with `--filesystem=/run/snapd.socket` in the Flatpak manifest. That socket is
the administrative interface to snapd: through it, Steward lists installed
snaps and adds or removes path-permission rules. It uses that access for
nothing else, and the app has no network permission at all.

You can inspect the permission at any time:

```sh
flatpak info --show-permissions io.github.massivemarmot.Steward
```

And revoke it (Steward will then report that it cannot reach snapd):

```sh
flatpak override --user --nofilesystem=/run/snapd.socket io.github.massivemarmot.Steward
```

## Privacy

- No network access, no telemetry, no analytics.
- Nothing is logged; no files are written outside the app's own data dir.

## Current limits

- Rules are limited to read access, allow outcome, forever lifespan. Rules
  made elsewhere (for example in Security Center) are listed and can be
  removed, whatever their type.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

This project is developed with AI assistance.

Steward is not affiliated with or endorsed by Canonical. Snap and Ubuntu are
trademarks of Canonical Ltd.

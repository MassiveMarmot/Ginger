# Ginger for Snaps

Ginger is a GNOME app that lists the snaps installed on your system and lets
you review, connect and disconnect their interface permissions — the same
thing as `snap connections`, `snap connect` and `snap disconnect`.

## Status

Version 0.1.0. Working now: listing snaps, showing each plug and its
connection state, connecting and disconnecting with confirmation, an undo
toast after each change, and a saved original state of every snap's
connections. Restore (returning a snap to its saved state) is planned and
not yet available.

## Requirements

Ubuntu (or another distribution) with snapd and GNOME, and Flatpak to
install. Nothing else.

## Install

Build and install the Flatpak from the repository root:

```sh
flatpak-builder --user --install --force-clean build-dir io.github.massivemarmot.Ginger.yml
```

To produce a shareable bundle:

```sh
flatpak build-bundle ~/.local/share/flatpak ginger-0.1.0.flatpak io.github.massivemarmot.Ginger
```

Install a bundle with:

```sh
flatpak install --user ginger-0.1.0.flatpak
flatpak run io.github.massivemarmot.Ginger
```

These commands were not executed in the development sandbox (no Flatpak
there); they follow the manifest and the Flatpak command reference.

## How it works, and the permission it needs

Ginger talks to snapd over its local socket, `/run/snapd.socket`. The Flatpak
grants exactly one extra permission for this: `--filesystem=/run/snapd.socket`
(plus `--socket=wayland` for the window). Through the socket it lists snaps
and reads and changes interface connections; it uses the socket for nothing
else.

Inspect the permission at any time:

```sh
flatpak info --show-permissions io.github.massivemarmot.Ginger
```

Revoke it (Ginger will then report that it cannot reach snapd):

```sh
flatpak override --user --nofilesystem=/run/snapd.socket io.github.massivemarmot.Ginger
```

Reading connections needs no authorization. Every change — a connect or a
disconnect — triggers a polkit approval dialog shown by the system, once per
change. Ginger cannot bypass it.

Ginger makes no network connections, sends no telemetry, and logs nothing
about snap or plug names.

## Safety rules

- Every disconnect asks for confirmation before it is sent.
- Connecting sensitive interfaces (for example `removable-media` or
  `ssh-keys`) asks for confirmation.
- Unknown interfaces are treated as sensitive.
- Some interfaces (for example `docker-support` and `snapd-control`) are
  never connected by Ginger; they are shown and can be disconnected.
- Disconnecting some interfaces (`desktop`, `wayland`, `x11`, `opengl`,
  `network`, `audio-playback`) can stop an app from working or prevent it
  from starting; the confirmation says so.

## Saved original state

On first sight of each snap, Ginger saves which of that snap's plugs were
connected, in `baseline.json` in the app's own data directory, with a backup
copy `baseline.json.bak`. Ginger never deletes or overwrites an entry; the
files are rewritten only to add entries for snaps it sees for the first time.

If the main file becomes unreadable but the backup is valid, Ginger uses the
backup and says so. If both are unreadable, Ginger blocks all changes and
shows the file location; "Start a new saved state" moves the unreadable files
aside (nothing is deleted) and takes a fresh snapshot — but that new state is
then "before that restart", not the pre-Ginger state.

Limitation: anything changed outside Ginger (for example with
`snap connect`) before Ginger first saw a snap becomes part of that snap's
saved state. "Original" means "before Ginger", not snapd's own defaults.

## Current limits

- One connection per change and one polkit approval per change (snapd
  rejects several at once).
- Only connect and disconnect; no snap install, removal or refresh.
- Interface descriptions are not shown.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

## Development

This project is developed with AI assistance (Claude and Mistral Vibe).
Decisions and reviews are by the maintainer.

## Trademark note

Ginger is not affiliated with or endorsed by Canonical. Snap and Ubuntu are
trademarks of Canonical Ltd.

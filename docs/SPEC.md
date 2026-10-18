# Ginger Build Spec and Build Plan

Tagline: **Ginger for Snaps**. App ID: `io.github.massivemarmot.Ginger`. Repo: https://github.com/MassiveMarmot/Ginger. License: GPL-3.0-or-later. Current target: v0.2.0.

This file is the single source of truth for scope, decisions, API facts, tests and milestones. Update it in the same change as any behavior change.

## Instructions to the coding agent (read first)

- Be brief and to the point. Short replies, no preamble, no summaries of what you just did.
- Keep code simple. If something takes one line, write one line. Do not import a library for what the standard library does.
- Python standard library plus PyGObject (GTK4, libadwaita) only. Ask before adding any other dependency.
- No speculative abstraction, no unrequested features, no comments that restate the code.
- Use only the API shapes under "snapd API". Do not guess others. Anything marked UNVERIFIED: capture the real response, report it, and implement it behind a clearly named constant.
- If the spec is ambiguous or contradicts what you find, stop and ask. Do not improvise.
- Work milestone by milestone. After each one, stop for review. Do not start the next.
- Before each submission run `python3 -m py_compile` on every file and `grep` for leftover references to removed names. Run tests with stderr visible and report any Gtk-CRITICAL or traceback output. PyGObject prints exceptions from signal handlers instead of raising them, so green tests alone prove nothing.
- Never run a mutating snapd call (connect, disconnect, install, remove) against the maintainer's machine. Mutating calls are allowed only in a disposable sandbox that you control, and you must say which environment you are in. Tests use the mock server only.

## Purpose

Ginger is a GNOME/libadwaita app that lists installed snaps and lets the user review and change each snap's interface connections (the permissions behind `snap connect` / `snap disconnect`): for example `removable-media`, `camera`, `audio-record`, `network-bind`. It works on every Ubuntu with strict snaps. It needs no experimental features.

## Decisions

- **The AppArmor permission-prompt feature is removed.** Ginger does not use, list, mention or depend on the permission-prompt client snap, the rules feature built on it, or Security Center. The rules UI, its client methods, `path_validation.py` and their tests were deleted. No text tells users to install or enable any of them. Reason: enabling them caused kernel and upgrade problems on the maintainer's system, and Ginger must not invite that risk. The code stays in git history.
- Out of v0.2: snap install/remove/refresh, editing AppArmor profiles, the `/v2/interfaces/requests/*` endpoints, accessibility work, batch actions other than Restore, real snap icons.
- **Tier 3 reconnect (decided 2026-10-17, "middle option").** Ginger may connect a tier 3 plug only to put back a connection that the saved baseline records as connected, through Restore or Undo, with a strong-warning confirmation plus the polkit approval. The Permissions switch never connects tier 3. A tier 3 plug and slot that are not in the baseline's connected list are disconnect-only everywhere, including Undo. Reason: Restore and Undo must be able to return the user to the original state, and Ginger must never grant more than the original state had.
- **A snap whose only difference from its baseline is a tier 3 plug counts as changed (decided 2026-10-17).** Banner, modified icon, Restore page entry and Restore all dialog all appear. The user needs all relevant information to find and solve problems.

## Constraints

- FOSS, privacy-first, security-first. No telemetry, no analytics, no network access from Ginger itself.
- Ubuntu, GNOME, libadwaita 1.5 or newer, Wayland.
- Flatpak, self-published on GitHub releases. `finish-args`: `--socket=wayland` and `--filesystem=/run/snapd.socket` only. Add nothing else unless a test proves it is required, and report it.
- Stack: Python 3, PyGObject. Talk to snapd with `http.client` over the Unix socket (existing `snapd_client.py`). The `SNAPD_SOCKET` environment variable overrides the socket path; it and `GINGER_DATA_DIR` are test hooks, ignored inside the Flatpak (`/.flatpak-info` present). Parse JSON with `json` only. Tests: stdlib `unittest`.
- No files written outside the app's own data dir. No subprocess or shell calls. Log nothing about snap or plug names beyond error kinds.
- Treat all snapd text as untrusted. `Adw.ActionRow` and similar: `use_markup=False`. Where a widget always parses markup (`StatusPage` description, `PreferencesGroup` title), use `GLib.markup_escape_text`. Never put snapd text in a markup-parsed title; dialog headings that contain plug names are plain text.

## snapd API (socket `/run/snapd.socket`)

**VERIFIED** on the maintainer's machine, inside the Flatpak, as a normal user:

- **List connections (no authorization needed):** `GET /v2/connections?snap=NAME&select=all`. Without `snap`, all snaps. `select=all` includes unconnected plugs and slots. Response `result` has:
  - `established`: `[{"slot":{"snap","slot"},"plug":{"snap","plug"},"interface","manual"?}]`. `manual` is `true` once a user has connected it; auto-connected ones have no `manual` field.
  - `undesired`: same shape, connections a user disconnected that would otherwise auto-connect (carry `manual: true`).
  - `plugs`: `[{"snap","plug","interface","apps","connections":[{"snap","slot"}]}]`
  - `slots`: `[{"snap","slot","interface","connections":[{"snap","plug"}]}]`
- **Connect / disconnect:** `POST /v2/interfaces`, body `{"action":"connect"|"disconnect","plugs":[{"snap":P,"plug":N}],"slots":[{"snap":S,"slot":M}]}`
  - Without the header `X-Allow-Interaction: true`: **401** `{"kind":"login-required"}`.
  - With it: snapd shows a polkit dialog. Approved: **202** `{"type":"async","status-code":202,"change":"<id>"}`. Cancelled: **403** `{"kind":"auth-cancelled"}`.
  - The POST blocks while the dialog is open. Run it on a worker thread; never block the UI.
- **Poll a change:** `GET /v2/changes/<id>` returns 200 with `result.status` (`Done` verified), `result.ready`, `result.err` (present on failure), `result.summary`. `/v2/change/<id>` returns **404**; do not use it.
- Disconnect result verified: the connection moves from `established` to `undesired` with `manual: true`. Reconnect result verified: back in `established` with `manual: true`.
- **Connect** returns the same 202 shape as disconnect; its change has kind `connect-snap` and finished `Done`. A connect makes the connection `manual: true`.
- **Tier 3 round trip** (snapd 2.77.1, Ubuntu 26.04 VM, normal user, polkit approved each time): firmware-updater:shutdown disconnect accepted (change Done) and reconnect accepted (change Done, plug then shows manual). A `--dangerous` local snap's docker-support plug is not auto-connected; a manual connect was accepted (change Done). A tier 3 reconnect uses the same call and approval path as other interfaces. A snapd refusal of a connect could not be provoked with a `--dangerous` snap and remains UNVERIFIED.
- **One plug and one slot per request.** A request with several plugs and several slots, or several plugs and one slot, returns **501** `{"message":"many-to-many operations are not implemented"}` (after the polkit dialog). Never batch: N changes means N requests.
- **One polkit dialog per request.** polkit may cache an approval for a few minutes (observed: a Restore of 2 steps right after a manual change showed no further prompts); worst case is one approval per request. The dialog appears before snapd validates the request, so an invalid request also costs an approval.
- **Disconnect of a plug that is not connected** returns **400** with message `cannot disconnect firefox:alsa from snapd:alsa, it is not connected` and **no `kind`**. Never send one; diff first.
- **Disconnecting a manually connected plug that is not auto-connected** (`firefox:pcscd`) leaves it in neither `established` nor `undesired`. Disconnecting an auto-connected plug moves it to `undesired`. Compare states using `established` only.
- **List installed snaps:** `GET /v2/snaps`, fields seen: `name`, `summary`, `version`, `type`, `apps`, `icon`, `publisher`.
- Responses: `{"type":"sync"|"async","error","status-code","result"}`. Errors carry `result.message` and `result.kind`.
- **Connect to a nonexistent slot** (snapd 2.77.1, Ubuntu 26.04 VM, normal user): HTTP 400, no `kind`, message `snap "snapd" has no slot named "nonexistent"`. Ginger never sends this (slot names come from the last connections response); a client seeing it shows the message as plain text.
- Reported by the coding agent from its sandbox, to be confirmed on the maintainer's machine before they count as verified: a redundant connect returns 202 Done; an unknown snap in the query returns error kind `snap-not-found`.

Documented, not yet seen (handle generically): task statuses are `Do`, `Doing`, `Done`, `Error`, `Hold`, `Undo`, `Undoing`, `Abort` and `Wait`. The change `status` summarises its tasks, `ready` is true when finished, and `err` is present when it failed. Treat `Done` as success, `ready` with `err` or status `Error` as failure, and any other status as "still running" until the timeout.

Documented, **UNVERIFIED** (isolate in constants; capture real data and report):

- Error `kind` and HTTP status when snapd **refuses** a connect (for example snap-declaration rules), and when the plug has no compatible slot. This matters most for tier 3 interfaces such as `docker-support`, which snapd may refuse for snaps without the right declaration. Handle unknown errors generically: show snapd's `message`, revert the switch, stop a batch.
- Behaviour when a plug could connect to several slots (for example `content`). Until verified, offer a connect only when exactly one slot is compatible; otherwise show the plug as insensitive with "Several slots available".
- Whether `GET /v2/connections` without `snap` is fast enough on a machine with many snaps.
- Interface `summary` text via `GET /v2/interfaces?select=all&doc=true` (optional; do not rely on it).

## Features

1. **Snap list** (sidebar | list | detail layout, kept from v0.1): installed snaps with apps, plus the existing "Show libraries and runtimes" toggle. Each row shows the name and its connected/available counts (for example "5 connected, 3 available").
2. **Snap detail: Permissions.** For the selected snap, one `Adw.PreferencesGroup` listing each plug with an `Adw.SwitchRow`: title = plug name, subtitle = interface plus a short state text ("Connected", "Disconnected", "Manually disconnected", "Manually connected"). Plugs with no slot in `slots` show as insensitive with the subtitle "No slot available".
   - Hide `content` interface plugs by default (theme and runtime plumbing). The funnel panel has "Show all interfaces".
   - Sort: danger tier first, then name.
3. **Change flow.** Toggling a switch:
   - Show a confirmation dialog first for every action in tiers 2 and 3, and for every disconnect. Tier 1 connects need no confirmation.
   - Send the POST with `X-Allow-Interaction: true` on a worker thread. Mutations only; reads never send the header.
   - Disable that row and show a spinner while the request and the change run. Poll `GET /v2/changes/<id>` (start 0.5 s, back off to 2 s, give up with a visible error after 60 s).
   - On `Done`: reload connections. On `ready` with `err`, or an error response: revert the switch to the real state and show snapd's `message` as plain text.
   - On 403 `auth-cancelled`: revert the switch silently, no error alert.
   - A switch's state always comes from the last loaded connections, never from the switch's own toggled position. After any outcome, reload.
4. **Danger tiers** (constants, easy to edit):
   - **Tier 1, low:** `audio-playback`, `audio-record`, `camera`, `network`, `network-bind`, `home`, `desktop`, `wayland`, `x11`, `opengl`, `screen-inhibit-control`.
   - **Tier 2, sensitive (confirm connect and disconnect; warning text):** `removable-media` (whole of /media, /run/media and /mnt, including network shares mounted there), `password-manager-service`, `ssh-keys`, `personal-files`, `system-files`, `block-devices`, `raw-usb`, `hardware-observe`, `system-observe`, `process-control`, `network-control`, `network-manage`.
   - **Tier 3, privileged (confirm; strong warning):** `docker-support`, `snapd-control`, `shutdown`, `kernel-module-control`, `system-backup`, `dac-override`. The Permissions switch never connects tier 3; it shows them and allows disconnect. The only tier 3 connect Ginger ever sends is baseline-only reconnect (see Feature 7).
   - Disconnect warning for `desktop`, `wayland`, `x11`, `opengl`, `network` and `audio-playback`: "The app may stop working or fail to start."
   - Any interface not listed above defaults to tier 2 (confirm), so an unknown interface is never treated as harmless.
5. **Status and errors.** If snapd cannot be reached, show a status page in the content area; refresh recovers.
6. **Undo hint.** After a successful change, show an `Adw.Toast` "Connected X" / "Disconnected X" with an Undo button that sends the inverse action through the same flow (including confirmation if its tier requires it). For a tier 3 disconnect, Undo is shown only when the baseline authorizes the reconnect (Feature 7, tier 3 rule); otherwise there is no Undo button.
7. **Baseline backup and restore.** So users can return to the pre-Ginger state.
   - **What is saved:** only the snap's connected plugs, each with its slot and interface (`snap`, `plug`, `slot_snap`, `slot`, `interface`), never snap data and never the full list of plugs. Entries captured before the `interface` field existed load unchanged; they are never authorized for a tier 3 reconnect (fail closed). Restore's diff rule is designed for exactly this schema; do not change it. One baseline per snap, taken **before Ginger's first change to that snap**: at each launch, for every snap that has no baseline yet, record its current plugs, slots and connections from `GET /v2/connections?snap=NAME&select=all`. The baseline is written once and never overwritten by Ginger. Limitation (documented in the README): changes made with `snap connect` outside Ginger before a snap's first baseline are part of that baseline.
   - **Where:** one JSON file `baseline.json` in the app's own data dir (`GLib.get_user_data_dir()`), written atomically (temp file in the same dir, then `os.replace`), with a `version` field, plus its mirror `baseline.json.bak` rewritten together with it whenever new snaps are added. No other location, no network.
   - **Restore compares, then changes.** Fetch the current connections, diff against the baseline, and show the diff before doing anything: a list of "Connect `snap:plug`" and "Disconnect `snap:plug`" steps. If the diff is empty, say "Already matches the original state" and do nothing. Compare `established` only (a plug in `undesired` or in neither list counts as disconnected). Nothing is sent for plugs that already match. Never send a disconnect for a plug that is not connected, and never a connect for one that already is.
   - **Scope and placement.** (a) One snap: when a snap differs from its baseline, a banner row at the top of its Permissions group says "This snap differs from its original state" with a **Restore original** button; hidden when nothing differs. (b) The snap list marks changed snaps with a small "modified" icon, and the funnel panel has an "Only changed snaps" option. (c) Selected snaps and all snaps: a **Restore** page in the sidebar (second entry) listing every changed snap with a check button, plus "Restore selected" and "Restore all"; empty state "Nothing to restore". The hamburger menu has "Restore all…", which only opens the Restore page; it never restores by itself. This page is the only multi-select UI; the Snaps list has no select mode.
   - **Changed means:** the diff has at least one step, or at least one "Not restored by Ginger" entry. One shared check in `restore.py` decides this; the banner, modified icon, filter, Restore page and Restore all must all use it.
   - **Diff rule.** Per snap, compare the baseline's connected entries with the current `established` list, using `(plug, slot_snap, slot)`. Connect: in the baseline but not currently established. Disconnect: currently established, `manual` is true, and not in the baseline. Plugs that are established without `manual` (auto-connected, for example new after a snap refresh) are never disconnected by Restore. A plug connected to a different slot than in the baseline gets a disconnect step then a connect step.
   - **Execution:** reuse the change flow from feature 3 (header, worker thread, polling), one step at a time, in sequence. Each step may need its own polkit approval (polkit may cache an approval for a few minutes), so the confirmation dialog states it up front ("This may ask for approval once." for one step, "This may ask for approval up to N times." otherwise; polkit may cache an approval, so a step may not prompt) and says that Restore also reverts changes made outside Ginger since the baseline (for example with `snap connect`), and the progress shows step X of N. One confirmation dialog for the whole restore, showing the step count and the full diff, with the tier 2 and tier 3 steps called out. A 403 `auth-cancelled` stops the whole batch with no error alert, showing a plain toast "Restore cancelled" if no step finished, or "Restore cancelled after X of N steps" if some did. Any other error stops the batch, shows snapd's message as plain text, and reports how many steps succeeded. Always reload afterwards.
   - **Validation:** treat `baseline.json` as untrusted input. Parse with `json`, check the schema and `version`, and only act on a snap, plug and slot that exist in the **current** `GET /v2/connections` response. Skip anything else and say how many steps were skipped and why (snap removed, plug gone after a refresh).
   - **Tier 3 rule (baseline-only reconnect).** A tier 3 connect step is allowed only if the exact tuple (plug_snap, plug, slot_snap, slot) is in the baseline's connected list AND the plug and slot exist in the current connections response AND the baseline entry's stored `interface` equals the current plug's interface (an entry without a stored interface is never authorized: fail closed). One function (for example `restore.may_reconnect_tier3(...)`) makes that decision and every path (Restore, Undo, any future caller) must go through it. It is also enforced in the lowest layer that already refuses changes for a snap without a baseline, so a caller cannot forget it. Such steps count in the approval total and get a strong warning in the confirmation dialog. When the check fails (plug or slot gone, slot differs, not in the baseline), the step is shown as "Not restored by Ginger" with the equivalent `snap connect` command in a copyable label, and nothing is sent.
   - **The original state is never deleted by Ginger.** There is no "Forget" action and no code path that deletes or overwrites a baseline entry. To protect it: also keep a second copy `baseline.json.bak` (a mirror of `baseline.json`, rewritten together with it by the same atomic write whenever new snaps are added). On load, if `baseline.json` is unreadable or invalid and the `.bak` is valid, use the `.bak` and report it. If both are invalid, keep both files untouched (never delete or rename-over them), block all changes, and show a banner explaining that the saved original state cannot be read, with the file location and the option "Start a new saved state": it moves the unreadable files aside to `baseline.unreadable-<timestamp>.json` and `baseline.unreadable-<timestamp>.bak.json` (kept, never deleted or overwritten; a name already taken gets a numeric suffix) and takes a fresh baseline from the current state. Say plainly that the fresh baseline is no longer the pre-Ginger state. Baseline entries for snaps that are no longer installed are kept.

## UI

**Reference: Warehouse** (https://github.com/flattool/warehouse). Mirror its look and layout: a sidebar plus content area, a list on the left with a detail pane on the right, a header-bar search button and a funnel toggle that opens a filter panel, rounded row highlight, a centered icon and bold title in the detail pane, boxed cards of rows. Copy layout and interaction patterns only. Do NOT copy Warehouse source or UI files, its name, icon or artwork (it is GPL-3.0). If unsure whether something is a pattern or a copy, ask.

Keep the v0.1 layout (OverlaySplitView, sidebar with Snaps, NavigationSplitView list | detail, breakpoints 865px and 600px, header toggle bound to the sidebar). Lessons that still apply: connect signals after setting initial state; never rebuild a widget from inside its own handler; `NavigationSplitView.set_content` takes an `Adw.NavigationPage`; only the last matching breakpoint applies, so each repeats the earlier setters; search text and selection survive refresh.

## Security model

- Only privilege: read/write on `/run/snapd.socket`. Reads need no authorization. Every change needs the user to approve a polkit dialog, which snapd shows; Ginger cannot bypass it. State this in the README and the manifest comments. Do not call the socket "root-equivalent"; describe what is verified.
- Ginger never connects a tier 3 interface except baseline-only reconnect through `may_reconnect_tier3` (Restore and Undo). It never edits AppArmor profiles and never installs or removes snaps.
- Quote or escape every snap, plug and slot name placed in a request body or URL. Build request bodies with `json.dumps`, query strings with `urllib.parse.urlencode`.
- `baseline.json` holds snap, plug and slot names and nothing else. It stays in the app's data dir, is never logged or sent anywhere, and is mentioned in the README. A restore only acts on names confirmed against the current connections response.
- The client allows only these calls, checked before any connection is made: `GET /v2/snaps`, `GET /v2/connections`, `POST /v2/interfaces` (connect and disconnect only), `GET /v2/changes/<id>`. Anything else raises. Test it.
- Send only plug and slot names that came from the last `GET /v2/connections` response. Never send names typed by the user (there is no free-text input in v0.2).

## Tests

- Mock snapd server: `GET /v2/connections` (with `snap` and `select`), `POST /v2/interfaces` (checks the `X-Allow-Interaction` header; 401 without it for connect/disconnect, 202 with a change id, can return 403 `auth-cancelled` or an error `kind`), `GET /v2/changes/<id>` (statuses `Do`, `Doing`, `Done`, `Error` with `err`), and 404 for `/v2/change/<id>`.
- Cover: connections parsing (`established`, `undesired`, `manual`), plug state derivation, mutation sends the header and reads never do, 202 then polling to `Done`, change `Error`, 403 cancelled is silent, 401 and snapd errors shown as plain text, polling timeout, tier lookup (unknown interface defaults to tier 2), the switch never connects tier 3, confirmation required by tier, hidden `content` plugs and the toggle, state comes from reload not from the switch, markup characters in snap, plug and error text, selection and search survive refresh, collapsed-mode behaviour.
- Baseline and restore: baseline written once and never overwritten; new snaps get a baseline at the next launch; atomic write; corrupt, wrong-version and tampered `baseline.json` handled without a crash; diff for connect, disconnect, already-matching, plug gone, snap removed; restore runs steps in order with the header; auth-cancelled stops the batch with no error alert and a plain cancel toast; an error mid-batch reports partial progress; one, selected and all-snaps scopes; "Start a new saved state" keeps the unreadable files and never deletes a baseline; the `.bak` is used when the main file is corrupt; markup characters in names on the Restore page.
- Tier 3: a tier 3 plug that is in the baseline and now disconnected is reconnected by Restore with the header, after the strong-warning confirmation, and counts in the approval total; a tier 3 plug not in the baseline is never connected by Restore, the switch or Undo; the switch for a disconnected tier 3 plug stays insensitive; Undo after a tier 3 disconnect is shown only when the baseline authorizes it; a direct call to the client or changes layer with an unauthorized tier 3 connect raises and sends nothing; a tampered baseline naming a nonexistent tier 3 plug is skipped, counted, and nothing is sent; a slot mismatch is shown as "Not restored by Ginger" with the command; a snap whose only difference is a tier 3 plug shows the banner and modified icon, is listed on the Restore page, and its dialog shows no approval line.
- Drive the real widgets (click the real switches and dialog buttons). Each UI test builds and destroys its own window. Tests never depend on the machine's home directory or on each other.
- Test pitfalls learned: (1) `AlertDialog.choose` completes asynchronously. After `alert.emit("response", ...)`, wait for the callback (for example `run_until(lambda: not win.confirming)`) before asserting or waiting on later state; use one helper for this. (2) `Gtk.PickFlags.DEFAULT` skips insensitive widgets, so a pick test needs the target sensitive first. (3) `check.emit("toggled")` does not change state; use `set_active(True)`. (4) Fixtures: baseline = original state; the server serves the changed state; a fixture whose baseline equals the served state makes every restore test vacuous.

## Planned after v0.2 (not part of v0.2 milestones)

- **Show everything by default; group the desktop plumbing.** `desktop`, `desktop-legacy`, `wayland`, `mir`, `unity8` go in a collapsed "Desktop integration" group below Permissions, with a summary line ("5 interfaces, all connected"). `x11` and `unity7` stay in the main list. Searching for a plumbing interface expands the group. `content` plugs stay behind "Show all interfaces". That setting is sticky (stored in the app's settings file). Tiers and warnings apply as usual.
- **Per-row "changed from original" marker** (modelled on Flatseal's override icon): a small icon with tooltip on each permission row that differs from the baseline, later a restore button for that one row.
- **Plain-language labels** for interfaces ("Use your camera"), written by us or copied from GNOME Settings' snap panel with credit (GPL-3.0-or-later, Canonical copyright); to be decided. Fall back to the raw interface name.
- **Slot chooser** for plugs with several compatible slots: a drop-down with "none" plus each `snap:slot`, same confirmation rules.
- **Search box above Permissions:** case-insensitive, matches plug and interface name as plain text, keeps its text when switching snaps, hides rows with `set_visible` (never rebuild from the handler), "No matching permissions" when empty, Ctrl+F focuses it.
- **Startup warning dialog:** shown at every launch until the user ticks "Don't show this again". Continue is disabled for 3 seconds with a visible countdown; Esc or closing counts as Quit; the checkbox is honored only on Continue; stored in the settings file; hamburger item "Startup warning…" shows it again. Text: changes can stop apps from working, apply to everyone on the computer (unverified), each change needs approval, the original state is saved. The timer length is injectable for tests.
- **Spike: disconnect by plug only.** GNOME Settings sends empty strings for the slot; test whether snapd accepts it.
- **Open a specific snap from outside.** `ginger --snap NAME` and an `app.show-snap` action (string parameter) that selects the named snap. Rules: selection only, never connect, disconnect or restore; NAME is untrusted (check against the loaded snap list, "Snap not found" otherwise, plain text everywhere); must not bypass any safeguard (waits for the startup warning, deferred while a change or confirmation dialog is open, a baseline problem still blocks changes); single instance; no new Flatpak permission; tests for unknown name, empty name, markup characters, name arriving while busy or while the startup dialog is open.
- **Optional, opt-in support for the AppArmor permission-prompt client (later version).** Only for users who already have it installed and enabled; never prompts anyone to install or enable it; a passive, dismissible notice; a separate sidebar page with its own warning dialog and timer; a confirmation for every rule change showing the exact permission line; broad-pattern warnings; rules saved before the first change with "remove the rules Ginger added"; Ginger never turns the feature on or off. The v0.1 code is in git history.
- **Interface descriptions** from `GET /v2/interfaces?select=all&doc=true` (unverified).

## Milestones

1. **Rename and removal.** DONE (2026-10-07). App ID, manifest, desktop file, metainfo, icons, launcher, About, tagline, removal of the prompt-feature code, tests and text.
2. **Client and mock tests.** DONE. `list_connections`, `change_interface`, `get_change`, polling helper, mock tests, `spike_connect.py`.
3. **Read-only UI and baseline capture.** DONE. Baseline file, snap list counts, Permissions group, tiers, hidden `content`, funnel option, status pages.
4. **Change flow.** DONE. Live switches, worker thread, confirmation dialogs, polling, error and cancel handling, undo toast, no change without a baseline.
5. **Restore.** MERGED (2026-10-17), not yet signed off. Part A: client allowlist. Part B: baseline validation, diff, per-snap button, Restore page, batch execution, `.bak` fallback, "Start a new saved state". Open items: UI tests in `RestoreTests` still failing (fixture and test-timing fixes briefed); the tier 3 changes above (counts as changed; baseline-only reconnect); the real-machine Restore test.
6. **Packaging.** PENDING. Manifest, README (what it does; the socket permission and polkit approval; the baseline file and its limitation; how to inspect or revoke with `flatpak override`; privacy; AI-assisted development note; "Ginger is not affiliated with or endorsed by Canonical. Snap and Ubuntu are trademarks of Canonical Ltd."), metainfo validation, `VERSION` = `0.2.0` matching the metainfo release, dark-mode check, exact build commands for the maintainer's VM.
7. **Later:** real snap icons, interface summaries, install/remove, batch actions.

## Review checklist (done by the reviewer after each milestone)

- Privilege creep: any permission, call or dependency beyond this spec.
- Any mutating call sent without the polkit header, or any read sent with it.
- Any tier 3 connect that is not authorized by `may_reconnect_tier3` against the baseline, including in restore and undo.
- Any change sent for a snap that has no saved baseline.
- Any code path that deletes or overwrites a baseline entry or file.
- Restore acting on names that are not in the current connections response.
- Markup or injection from snapd strings.
- Unverified items implemented as if verified.
- Signal handlers that rebuild what they live in, or fire during setup; UI state taken from a switch instead of reloaded data.
- Leftover references to the old app name or the removed prompt feature.
- Needless complexity: could it be simpler or shorter?

## Status log

- 2026-10-17: UI test run on the maintainer's VM went from 17 to 8 failures in `RestoreTests` after the fixture fix; remaining causes are test timing (async dialog response), a toggled-signal misuse, an insensitive-pick test, and the tier-3-only "changed" case (now decided, see Decisions).
- 2026-10-17: tier 3 baseline-only reconnect decided; Stage 1 report (all current tier 3 blocking sites) received; Stage 2 (implementation) waits for the maintainer's go.
- Pending on the maintainer's machine: run `spike_connect.py` on a tier 3 plug that is safe to connect on the VM and report snapd's response (refusal kind and status are UNVERIFIED).

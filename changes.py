# SPDX-License-Identifier: GPL-3.0-or-later
"""Change flow: run one interface change on a worker and report back.

Pure logic here; the window supplies the client, callbacks, and the
main-thread invoker. Outcomes (per spec):
- done: reload
- auth_cancelled: revert silently
- request_timeout: reload, state unknown, no error
- error: snapd's message as plain text, reload

A tier 3 connect is authorized here from evidence (baseline entry and
current connections) via restore.may_reconnect_tier3; a caller cannot
assert authorization. Fail closed on anything unresolved.
"""

import interfaces
import restore


class Tier3NotAuthorized(Exception):
    """A connect not authorized: tier 3 without a matching baseline
    entry, or a plug whose interface cannot be resolved."""


class NoBaseline(Exception):
    """A mutation for a snap that has no saved baseline entry."""

OUTCOME_DONE = "done"
OUTCOME_CANCELLED = "auth_cancelled"
OUTCOME_TIMEOUT = "request_timeout"
OUTCOME_ERROR = "error"

TIER2_WARNING = {
    "removable-media": "Whole of /media, /run/media and /mnt, including "
                       "network shares mounted there.",
}

GENERIC_TIER2_WARNING = "This interface gives the app access to sensitive " \
                         "system areas or personal data."
TIER3_WARNING = "Privileged interface: grants broad system access."

DISCONNECT_HINT = "The app may stop working or fail to start."
DISCONNECT_HINT_INTERFACES = frozenset({
    "desktop", "wayland", "x11", "opengl", "network", "audio-playback",
})


def needs_confirmation(action, interface, tier):
    if action == "disconnect":
        return True
    if action == "connect":
        return tier >= 2
    return False


def confirmation_body(action, plug, interface, tier):
    parts = []
    if action == "disconnect":
        parts.append("Disconnect %s (%s)." % (plug, interface))
        if interface in DISCONNECT_HINT_INTERFACES:
            parts.append(DISCONNECT_HINT)
    else:
        parts.append("Connect %s (%s)." % (plug, interface))
        if tier == 3:
            parts.append(TIER3_WARNING)
        else:
            parts.append(TIER2_WARNING.get(interface,
                                           GENERIC_TIER2_WARNING))
    return " ".join(parts)


def run_change(client, action, plug_snap, plug, slot_snap, slot,
               timeout=None, baseline_entry=None, current_connections=None):
    """Runs on the worker thread. Returns (outcome, message).

    A transient error while polling the change (for example a read
    timeout) is reported as a timeout: the change may still have
    applied, so the caller reloads and shows the state as unknown.

    Fail closed on evidence, never on a caller's flag: the plug's
    interface is resolved here from current_connections. A connect
    with an unresolved interface is refused. A tier 3 connect is
    authorized only by restore.may_reconnect_tier3 against
    baseline_entry; nothing is sent otherwise. Any mutation without a
    baseline entry is refused: Ginger changes a snap only when the
    saved original state exists.
    """
    if baseline_entry is None:
        raise NoBaseline("no saved original state for %s" % plug_snap)
    if action == "connect":
        interface = restore._interface_of(current_connections or {},
                                          plug_snap, plug)
        if interface is None:
            raise Tier3NotAuthorized(
                "plug interface unknown; connect refused")
        if interfaces.tier_for(interface) == 3 \
                and not restore.may_reconnect_tier3(
                    baseline_entry, current_connections or {},
                    plug_snap, plug, slot_snap, slot):
            raise Tier3NotAuthorized(
                "tier 3 connect not authorized by the baseline")

    def classify(e, polling):
        kind = getattr(e, "kind", None)
        if kind == "auth-cancelled":
            return OUTCOME_CANCELLED, None
        if kind == "request-timeout" or kind == "change-timeout" \
                or (polling and kind == "connection-failed"):
            return OUTCOME_TIMEOUT, None
        return OUTCOME_ERROR, getattr(e, "message", str(e))

    try:
        if timeout is not None:
            change_id = client.change_interface(action, plug_snap, plug,
                                                 slot_snap, slot,
                                                 timeout=timeout)
        else:
            change_id = client.change_interface(action, plug_snap, plug,
                                                slot_snap, slot)
    except Exception as e:
        return classify(e, polling=False)
    try:
        client.wait_for_change(change_id)
        return OUTCOME_DONE, None
    except Exception as e:
        return classify(e, polling=True)

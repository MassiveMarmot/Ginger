# SPDX-License-Identifier: GPL-3.0-or-later
"""Change flow: run one interface change on a worker and report back.

Pure logic here; the window supplies the client, callbacks, and the
main-thread invoker. Outcomes (per spec):
- done: reload
- auth_cancelled: revert silently
- request_timeout: reload, state unknown, no error
- error: snapd's message as plain text, reload

A tier 3 connect is refused here unless the caller passes
tier3_authorized=True after restore.may_reconnect_tier3 said so;
nothing is sent. Fail closed: the authorization input is required.
"""

import interfaces


class Tier3NotAuthorized(Exception):
    """A tier 3 connect without baseline authorization."""

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
               timeout=None, interface=None, tier3_authorized=False):
    """Runs on the worker thread. Returns (outcome, message).

    A transient error while polling the change (for example a read
    timeout) is reported as a timeout: the change may still have
    applied, so the caller reloads and shows the state as unknown.

    A connect whose plug interface (from the last connections
    response) is tier 3 is refused unless tier3_authorized is True;
    nothing is sent. Fail closed: a missing or False authorization
    refuses the change.
    """
    if action == "connect" \
            and interfaces.tier_for(interface or "?") == 3 \
            and not tier3_authorized:
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

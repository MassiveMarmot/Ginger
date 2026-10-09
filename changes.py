# SPDX-License-Identifier: GPL-3.0-or-later
"""Change flow: run one interface change on a worker and report back.

Pure logic here; the window supplies the client, callbacks, and the
main-thread invoker. Outcomes (per spec):
- done: reload
- auth_cancelled: revert silently
- request_timeout: reload, state unknown, no error
- error: snapd's message as plain text, reload
"""

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
        warning = TIER2_WARNING.get(interface, GENERIC_TIER2_WARNING)
        parts.append(warning)
        if tier == 3:
            parts.append("Ginger never connects this interface.")
    return " ".join(parts)


def run_change(client, action, plug_snap, plug, slot_snap, slot,
               timeout=None):
    """Runs on the worker thread. Returns (outcome, message)."""
    try:
        change_id = client.change_interface(action, plug_snap, plug,
                                            slot_snap, slot,
                                            timeout=timeout) \
            if timeout is not None \
            else client.change_interface(action, plug_snap, plug,
                                          slot_snap, slot)
        client.wait_for_change(change_id)
        return OUTCOME_DONE, None
    except Exception as e:
        kind = getattr(e, "kind", None)
        if kind == "auth-cancelled":
            return OUTCOME_CANCELLED, None
        if kind == "request-timeout":
            return OUTCOME_TIMEOUT, None
        message = getattr(e, "message", str(e))
        return OUTCOME_ERROR, message

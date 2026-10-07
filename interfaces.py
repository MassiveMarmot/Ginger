# SPDX-License-Identifier: GPL-3.0-or-later
# Danger tiers, editable in one place. Unlisted interfaces default to
# tier 2 (confirm), so an unknown interface is never treated as harmless.

TIER_1_INTERFACES = frozenset({
    "audio-playback", "audio-record", "camera", "network", "network-bind",
    "home", "desktop", "wayland", "x11", "opengl", "screen-inhibit-control",
})
TIER_2_INTERFACES = frozenset({
    "removable-media", "password-manager-service", "ssh-keys",
    "personal-files", "system-files", "block-devices", "raw-usb",
    "hardware-observe", "system-observe", "process-control",
    "network-control", "network-manage",
})
TIER_3_INTERFACES = frozenset({
    "docker-support", "snapd-control", "shutdown", "kernel-module-control",
    "system-backup", "dac-override",
})
DEFAULT_TIER = 2

# Theme and runtime plumbing, hidden by default.
HIDDEN_INTERFACES = frozenset({"content"})


def tier_for(interface):
    if interface in TIER_3_INTERFACES:
        return 3
    if interface in TIER_2_INTERFACES:
        return 2
    if interface in TIER_1_INTERFACES:
        return 1
    return DEFAULT_TIER


def is_hidden(interface):
    return interface in HIDDEN_INTERFACES


def derive_plugs(connections, snap, show_all=False):
    """One entry per plug of `snap`, sorted by tier then name.

    Connected state comes from established only: a plug in undesired or
    in neither list counts as disconnected.
    """
    established = {}
    for c in connections.get("established") or []:
        plug = c.get("plug") if isinstance(c, dict) else None
        if isinstance(plug, dict) and plug.get("snap") == snap:
            established[str(plug.get("plug") or "?")] = c
    undesired = set()
    for c in connections.get("undesired") or []:
        plug = c.get("plug") if isinstance(c, dict) else None
        if isinstance(plug, dict) and plug.get("snap") == snap:
            undesired.add(str(plug.get("plug") or "?"))
    slots = [s for s in connections.get("slots") or []
             if isinstance(s, dict)]

    plugs = []
    for p in connections.get("plugs") or []:
        if not isinstance(p, dict) or p.get("snap") != snap:
            continue
        if not isinstance(p.get("plug"), str) \
                or not isinstance(p.get("interface"), str):
            continue
        name = p["plug"]
        interface = p["interface"]
        if not show_all and is_hidden(interface):
            continue
        compatible = [s for s in slots
                      if str(s.get("interface") or "") == interface]
        conn = established.get(name)
        if conn is not None:
            state = ("Manually connected" if conn.get("manual")
                     else "Connected")
        elif name in undesired:
            state = "Manually disconnected"
        else:
            state = "Disconnected"
        slot = None
        if len(compatible) == 1:
            slot = (str(compatible[0].get("snap") or "?"),
                    str(compatible[0].get("slot") or "?"))
        conn_slot = None
        if conn is not None and isinstance(conn.get("slot"), dict):
            conn_slot = (str(conn["slot"].get("snap") or "?"),
                         str(conn["slot"].get("slot") or "?"))
        plugs.append({
            "name": name,
            "interface": interface,
            "connected": conn is not None,
            "state": state,
            "tier": tier_for(interface),
            "slot": slot,
            "n_slots": len(compatible),
            "conn_slot": conn_slot,
        })
    plugs.sort(key=lambda p: (p["tier"], p["name"]))
    return plugs


def counts(connections, snap):
    """(connected, available) across all plugs, hidden ones included."""
    connected = available = 0
    for plug in derive_plugs(connections, snap, show_all=True):
        if plug["connected"]:
            connected += 1
        elif plug["n_slots"]:
            available += 1
    return connected, available

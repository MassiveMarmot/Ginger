# SPDX-License-Identifier: GPL-3.0-or-later
"""One baseline per snap: the connection state before Ginger's first
change to that snap. Written once, never overwritten by Ginger."""
import json
import os
import tempfile

BASELINE_VERSION = 1
BASELINE_FILENAME = "baseline.json"


class BaselineError(Exception):
    pass


def _baseline_path():
    return os.path.join(os.environ.get("GINGER_DATA_DIR",
                                       _default_data_dir()),
                        BASELINE_FILENAME)


def _default_data_dir():
    try:
        import gi
        gi.require_version("GLib", "2.0")
        from gi.repository import GLib
        return os.path.join(GLib.get_user_data_dir(), "ginger")
    except Exception:
        return os.path.join(os.path.expanduser("~"),
                            ".local", "share", "ginger")


def baseline_path():
    return _baseline_path()


def load(path=None):
    path = path or _baseline_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        raise BaselineError("unreadable baseline file: %s" % e)
    if not isinstance(data, dict) \
            or data.get("version") != BASELINE_VERSION \
            or not isinstance(data.get("snaps"), dict):
        raise BaselineError("unsupported baseline file")
    snaps = {}
    for name, entry in data["snaps"].items():
        if isinstance(name, str) and _valid_entry(entry):
            snaps[name] = entry
    return snaps


def _valid_entry(entry):
    if not isinstance(entry, dict):
        return False
    for key in ("connected", "plugs", "slots"):
        if not isinstance(entry.get(key), list):
            return False
    return True


def save_snaps(snaps):
    """Write all baselines atomically. One write per launch."""
    path = _baseline_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"version": BASELINE_VERSION, "snaps": snaps}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                               prefix=".baseline-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def entry_for(connections, snap):
    """Baseline entry: connected state only, derived from established."""
    established = []
    plugs = []
    slots = []
    for c in connections.get("established") or []:
        if not isinstance(c, dict) or not isinstance(c.get("plug"), dict):
            continue
        if c["plug"].get("snap") != snap:
            continue
        plug = str(c["plug"].get("plug") or "?")
        slot = c.get("slot") if isinstance(c.get("slot"), dict) else {}
        established.append(plug)
        plugs.append({"plug": plug,
                      "snap": snap,
                      "interface": str(c.get("interface") or "")})
        slots.append({"snap": str(slot.get("snap") or "?"),
                      "slot": str(slot.get("slot") or "?"),
                      "interface": str(c.get("interface") or "")})
    return {"connected": sorted(established),
            "plugs": plugs, "slots": slots}


def capture_new(existing, connections_by_snap):
    """Baseline entries for snaps that have none, keyed by snap name."""
    new = {}
    for snap, connections in connections_by_snap.items():
        if snap not in existing:
            new[snap] = entry_for(connections, snap)
    return new


def forget(path=None):
    path = path or _baseline_path()
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True

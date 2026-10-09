# SPDX-License-Identifier: GPL-3.0-or-later
"""One baseline per snap: the connection state before Ginger's first
change to that snap. Written once, never overwritten by Ginger."""
import json
import os
import tempfile

BASELINE_VERSION = 2
BASELINE_FILENAME = "baseline.json"
BACKUP_FILENAME = BASELINE_FILENAME + ".bak"


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


def _backup_path():
    return _baseline_path() + ".bak"


def backup_path():
    return _backup_path()


def _valid_entry(entry):
    if not isinstance(entry, dict) or set(entry) != {"connected"}:
        return False
    connected = entry.get("connected")
    if not isinstance(connected, list):
        return False
    for c in connected:
        if not isinstance(c, dict) or set(c) != {"plug", "slot_snap",
                                                 "slot"} \
                or not all(isinstance(c[k], str) for k in
                           ("plug", "slot_snap", "slot")):
            return False
    return True


def _parse(data):
    if not isinstance(data, dict) \
            or data.get("version") != BASELINE_VERSION \
            or not isinstance(data.get("snaps"), dict):
        raise BaselineError("unsupported baseline file")
    snaps = {}
    for name, entry in data["snaps"].items():
        if not isinstance(name, str) or not _valid_entry(entry):
            raise BaselineError("invalid data in the baseline file")
        snaps[name] = entry
    return snaps


def load(path=None):
    """Returns (snaps, used_backup). Falls back to the .bak copy when
    the main file is unreadable or invalid."""
    path = path or _baseline_path()
    try:
        with open(path, encoding="utf-8") as f:
            return _parse(json.load(f)), False
    except FileNotFoundError:
        try:
            with open(_backup_path(), encoding="utf-8") as f:
                return _parse(json.load(f)), True
        except FileNotFoundError:
            return {}, False
        except (OSError, json.JSONDecodeError, BaselineError) as e:
            raise BaselineError("unreadable baseline backup: %s" % e)
    except (OSError, json.JSONDecodeError, BaselineError) as e:
        try:
            with open(_backup_path(), encoding="utf-8") as f:
                return _parse(json.load(f)), True
        except FileNotFoundError:
            raise BaselineError("unreadable baseline file: %s" % e)
        except (OSError, json.JSONDecodeError, BaselineError):
            raise BaselineError("unreadable baseline file: %s" % e)


def _atomic_write(path, data):
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
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise


def save_snaps(snaps):
    """Write the main file, then the .bak copy. Both are written only
    when there is something new (first write or new snaps). Entries
    for snaps that are no longer installed are kept."""
    path = _baseline_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"version": BASELINE_VERSION, "snaps": snaps}
    _atomic_write(path, data)
    _atomic_write(_backup_path(), data)


def entry_for(connections, snap):
    """Baseline entry: connected plugs with their slots, from established."""
    connected = []
    for c in connections.get("established") or []:
        if not isinstance(c, dict) or not isinstance(c.get("plug"), dict):
            continue
        if c["plug"].get("snap") != snap:
            continue
        slot = c.get("slot") if isinstance(c.get("slot"), dict) else {}
        connected.append({
            "plug": str(c["plug"].get("plug") or "?"),
            "slot_snap": str(slot.get("snap") or "?"),
            "slot": str(slot.get("slot") or "?"),
        })
    connected.sort(key=lambda c: c["plug"])
    return {"connected": connected}


def capture_new(existing, connections_by_snap):
    """Baseline entries for snaps that have none, keyed by snap name."""
    new = {}
    for snap, connections in connections_by_snap.items():
        if snap not in existing:
            new[snap] = entry_for(connections, snap)
    return new


def quarantine_unreadable(timestamp):
    """Move an unreadable baseline and its backup out of the way;
    nothing is ever deleted."""
    moved = []
    for path in (_baseline_path(), _backup_path()):
        if os.path.exists(path):
            target = os.path.join(
                os.path.dirname(path),
                "baseline.unreadable-%s.json" % timestamp)
            os.replace(path, target)
            moved.append(target)
    return moved

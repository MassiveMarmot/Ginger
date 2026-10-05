# SPDX-License-Identifier: GPL-3.0-or-later
import os
import pwd
import re
import unicodedata


def _home():
    return pwd.getpwuid(os.getuid()).pw_dir


def expand_home(pattern, home=None):
    if home is None:
        home = _home()
    if pattern == "~":
        return home
    if pattern.startswith("~/"):
        return home + pattern[1:]
    return pattern


def normalize_pattern(pattern):
    """Return (expanded_pattern, error_message); exactly one is None."""
    pattern = expand_home(pattern)
    if not pattern:
        return None, "Path pattern is empty"
    if not pattern.startswith("/"):
        return None, "Path pattern must be absolute (start with /)"
    for c in pattern:
        if unicodedata.category(c) in ("Cc", "Cf"):
            return None, "Path pattern contains control or format characters"
    if ".." in pattern.split("/"):
        return None, "Path pattern must not contain '..'"
    return pattern, None


def _glob_regex(pattern):
    parts = []
    for i, c in enumerate(pattern):
        if pattern[i:i + 2] == "**":
            continue
        if pattern[i - 1:i + 1] == "**":
            parts.append(".*")
        elif c == "*":
            parts.append("[^/]*")
        elif c == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(c))
    return re.compile("^" + "".join(parts) + "$")


def is_broad_pattern(pattern, home=None):
    if home is None:
        home = _home()
    expanded = expand_home(pattern, home)
    if expanded.rstrip("*/") in ("/home", "/home/*"):
        return True
    regex = _glob_regex(expanded)
    return (regex.match(home) is not None
            or regex.match(home + "/x") is not None
            or regex.match(home + "/x/x") is not None)

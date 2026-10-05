# SPDX-License-Identifier: GPL-3.0-or-later
import os
import pwd
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


def is_broad_pattern(pattern, home=None):
    stem = expand_home(pattern, home).rstrip("*/")
    if home is None:
        home = _home()
    if home == stem or home.startswith(stem + "/"):
        return True
    return stem in ("/home", "/home/*")

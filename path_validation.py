import os
import pwd
import unicodedata


def _home():
    return pwd.getpwuid(os.getuid()).pw_dir


def expand_home(pattern):
    if pattern == "~":
        return _home()
    if pattern.startswith("~/"):
        return _home() + pattern[1:]
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


def is_broad_pattern(pattern):
    stem = expand_home(pattern).rstrip("*/")
    home = _home()
    return home == stem or home.startswith(stem + "/")

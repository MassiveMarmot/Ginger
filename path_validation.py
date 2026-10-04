import os
import pwd


def expand_home(pattern):
    if pattern.startswith("~/") or pattern == "~":
        home = pwd.getpwuid(os.getuid()).pw_dir
        return home + pattern[1:] if pattern != "~" else home
    return pattern


def validate_pattern(pattern):
    """Return an error message, or None if valid."""
    pattern = expand_home(pattern)
    if not pattern:
        return "Path pattern is empty"
    if not pattern.startswith("/"):
        return "Path pattern must be absolute (start with /)"
    if "\x00" in pattern:
        return "Path pattern contains a NUL character"
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in pattern):
        return "Path pattern contains control characters"
    segments = pattern.split("/")
    if ".." in segments:
        return "Path pattern must not contain '..'"
    return None


def is_broad_pattern(pattern):
    pattern = expand_home(pattern)
    home = pwd.getpwuid(os.getuid()).pw_dir
    return pattern in ("/**", "/home/**", home + "/**")

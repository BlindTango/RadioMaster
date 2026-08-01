"""Path resolution — portable by default (everything next to the
executable), but falls back to a per-user writable directory when it isn't
(e.g. the installer's "Full installation" option puts the exe in
Program Files, which a standard user cannot write to — every setting was
silently failing to save with no visible error before this fallback existed).
"""

import os
import sys


def app_dir() -> str:
    """Directory containing the running executable (frozen) or the project root (source).

    Read-only resources (bundled ffmpeg, etc.) always live here — this is
    NOT where writable state should go; use state_dir()/data_dir() for that.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # radiomaster/utils/paths.py -> project root is two levels up
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


_state_dir_cache: str | None = None


def state_dir() -> str:
    """Directory for writable app state: config.json, the JSON stores
    (favourites/custom stations/schedules/effects), stations.db, logs, and
    recordings. Prefers app_dir() (keeps the app fully portable, as
    documented), but falls back to a per-user directory under
    %LOCALAPPDATA% the first time app_dir() turns out not to be writable —
    otherwise a "Full installation" (which the installer puts in
    Program Files) can never persist anything.
    """
    global _state_dir_cache
    if _state_dir_cache is not None:
        return _state_dir_cache
    primary = app_dir()
    if _is_writable(primary):
        _state_dir_cache = primary
    else:
        fallback = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RadioMaster",
        )
        os.makedirs(fallback, exist_ok=True)
        _state_dir_cache = fallback
    return _state_dir_cache


def data_dir(*parts: str) -> str:
    """A writable directory under state_dir(), created on demand."""
    path = os.path.join(state_dir(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(state_dir(), "config.json")


def recordings_dir(*parts: str) -> str:
    return data_dir("recordings", *parts)


def resources_dir(*parts: str) -> str:
    return os.path.join(app_dir(), "radiomaster", "resources", *parts)


def cache_dir(*parts: str) -> str:
    return data_dir("cache", *parts)

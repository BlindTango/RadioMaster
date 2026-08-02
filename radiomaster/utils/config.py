"""Portable JSON configuration store — config.json lives next to the executable."""

import json
import logging
import os
import threading

from .paths import config_path

log = logging.getLogger(__name__)

_DEFAULTS = {
    "buffer_seconds": 30,
    "output_device": None,
    "vpn_proxy": None,
    "vpn_enabled": False,
    "metadata_deezer_enabled": True,
    "metadata_musicbrainz_enabled": True,
    "recording_format": "mp3",
    "theme": "default",
    "language": "en",
    "ffmpeg_path": None,
    "ffprobe_path": None,
    "window_size": [900, 600],
    "volume": 1.0,
    "acoustid_api_key": None,
    "min_track_seconds": 30,
    "station_update_frequency": "weekly",
    "log_level": "info",
    "auto_play_last_station": False,
    "last_station_uuid": None,
    "last_station_name": None,
    "last_station_url": None,
    "fade_enabled": False,
    "fade_ms": 800,
    "mute_playback_while_recording": False,
    "ad_detection_enabled": False,
    "ad_auto_mute_enabled": True,
    "podcastindex_api_key": None,
    "podcastindex_api_secret": None,
    "podcast_volume": 1.0,
    "podcast_rate": 1.0,
    "podcast_pan": 0.5,
    "check_for_updates_enabled": True,
    "skip_update_version": None,
    "last_seen_version": None,
    "hotkeys": {
        "play_pause": ["Ctrl+Alt+P"],
        "stop": ["Ctrl+Alt+S"],
        "record": ["Ctrl+Alt+R"],
        "volume_up": ["Ctrl+Alt+Up"],
        "volume_down": ["Ctrl+Alt+Down"],
    },
}


def _normalize_hotkeys(raw) -> dict[str, list[str]]:
    """Pre-1.9.0 configs stored one spec string per action; newer ones store a
    list (an action can now have several bindings, e.g. a letter shortcut and
    a multimedia key). Upgrades the old shape in place so callers never have
    to special-case it."""
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for action, value in raw.items():
        if isinstance(value, str):
            normalized[action] = [value] if value else []
        elif isinstance(value, list):
            normalized[action] = [v for v in value if isinstance(v, str) and v]
        else:
            normalized[action] = []
    return normalized


class Config:
    """Simple thread-safe JSON-backed settings object."""

    def __init__(self, path: str | None = None):
        self._path = path or config_path()
        self._lock = threading.Lock()
        self._data = dict(_DEFAULTS)
        self.load()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    self._data.update(loaded)
                except (json.JSONDecodeError, OSError):
                    pass
            self._data["hotkeys"] = _normalize_hotkeys(self._data.get("hotkeys"))

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, sort_keys=True)
                os.replace(tmp, self._path)
            except OSError:
                # Swallowed on purpose (callers don't check a return value
                # and a raise here would abort whatever cleanup/shutdown
                # code called us) but logged, since a silent failure here is
                # exactly what makes "my settings aren't saving" impossible
                # to diagnose otherwise.
                log.exception("Failed to save config to %s", self._path)

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
        if save:
            self.save()

    def as_dict(self) -> dict:
        with self._lock:
            return dict(self._data)


_instance: Config | None = None


def get_config() -> Config:
    global _instance
    if _instance is None:
        _instance = Config()
    return _instance

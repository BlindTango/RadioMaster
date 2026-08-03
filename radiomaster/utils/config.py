"""Portable JSON configuration store — config.json lives next to the executable."""

import json
import logging
import os
import threading

from .paths import config_path

log = logging.getLogger(__name__)

_DEFAULTS = {
    "buffer_seconds": 30,
    "connection_retries": 3,
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
    "volume": 0.4,
    "pan": 0.5,
    "acoustid_api_key": None,
    "min_track_seconds": 31,
    "station_update_frequency": "weekly",
    "log_level": "info",
    "auto_play_last_station": True,
    "last_station_uuid": None,
    "last_station_name": None,
    "last_station_url": None,
    "fade_enabled": True,
    "fade_ms": 500,
    "mute_playback_while_recording": False,
    "ad_detection_enabled": True,
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
        "play_pause": ["Shift+Alt+P"],
        "stop": ["Shift+Alt+S"],
        "record": ["Shift+Alt+R"],
        "volume_up": ["Shift+Alt+Up"],
        "volume_down": ["Shift+Alt+Down"],
        "pan_left": ["Shift+Alt+Home"],
        "pan_right": ["Shift+Alt+End"],
        "rate_up": ["Shift+Alt+Right"],
        "rate_down": ["Shift+Alt+Left"],
        "open_recording_folder": ["Shift+Alt+F"],
        "open_podcast_folder": ["Shift+Alt+J"],
        "open_settings": ["Shift+Alt+T"],
        "open_scheduler": ["Shift+Alt+C"],
        "help": ["Shift+Alt+H"],
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
            hotkeys = _normalize_hotkeys(self._data.get("hotkeys"))
            # update() above is a shallow merge, so an existing config.json's
            # "hotkeys" dict fully replaces the default one rather than being
            # merged key-by-key. That means an action added to _DEFAULTS
            # after a user's config.json already existed (e.g. Podcast Rate
            # Up/Down, Open Recording/Podcast Folder, Open Settings, Open
            # Recording Scheduler, Open Help) would otherwise stay permanently
            # unbound and invisible in the Hotkeys dialog's list, which only
            # shows actions that already have at least one binding. Fill in
            # any action missing from the loaded file with its default
            # binding(s) so newly introduced actions actually appear.
            for action, specs in _DEFAULTS["hotkeys"].items():
                hotkeys.setdefault(action, list(specs))
            self._data["hotkeys"] = hotkeys

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

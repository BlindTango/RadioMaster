"""Persistence for effect presets (CRUD) and the active enabled/preset selection per effect."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

from ..utils.paths import state_dir
from .effects import CHAIN_ORDER, EFFECT_SPECS

log = logging.getLogger(__name__)

DEFAULT_PRESET_NAME = "Default"


class EffectsPresetStore:
    """effects_presets.json: {effect_id: {preset_name: {param_key: value}}}"""

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(state_dir(), "effects_presets.json")
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict]] = {}
        self.load()
        self._seed_defaults()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp, self._path)
            except OSError:
                log.exception("Failed to save %s", self._path)

    def _seed_defaults(self) -> None:
        changed = False
        with self._lock:
            for effect_id, spec in EFFECT_SPECS.items():
                presets = self._data.setdefault(effect_id, {})
                if not presets:
                    presets[DEFAULT_PRESET_NAME] = spec.default_params()
                    changed = True
        if changed:
            self.save()

    def preset_names(self, effect_id: str) -> list[str]:
        with self._lock:
            return sorted(self._data.get(effect_id, {}).keys())

    def get_preset(self, effect_id: str, name: str) -> Optional[dict]:
        with self._lock:
            presets = self._data.get(effect_id, {})
            if name in presets:
                return dict(presets[name])
            return None

    def save_preset(self, effect_id: str, name: str, params: dict) -> None:
        if not name.strip():
            raise ValueError("Preset name cannot be empty.")
        with self._lock:
            self._data.setdefault(effect_id, {})[name] = dict(params)
        self.save()

    def rename_preset(self, effect_id: str, old_name: str, new_name: str) -> None:
        if not new_name.strip():
            raise ValueError("Preset name cannot be empty.")
        with self._lock:
            presets = self._data.setdefault(effect_id, {})
            if old_name not in presets:
                raise KeyError(f"No such preset: {old_name}")
            if new_name in presets and new_name != old_name:
                raise ValueError(f"A preset named '{new_name}' already exists.")
            presets[new_name] = presets.pop(old_name)
        self.save()

    def delete_preset(self, effect_id: str, name: str) -> None:
        with self._lock:
            presets = self._data.setdefault(effect_id, {})
            if len(presets) <= 1:
                raise ValueError("Cannot delete the last remaining preset for an effect.")
            presets.pop(name, None)
        self.save()


class EffectsStateStore:
    """effects_state.json: {effect_id: {"enabled": bool, "preset": str}}"""

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(state_dir(), "effects_state.json")
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self.load()
        self._seed_defaults()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._data = {}

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp, self._path)
            except OSError:
                log.exception("Failed to save %s", self._path)

    # Every effect defaults to off except loudness normalization, which
    # fixes a real "some stations are much softer than others" complaint —
    # defaulting it on means users get that fix immediately rather than
    # needing to discover a checkbox in the Effects settings page.
    _DEFAULT_ENABLED = {"loudness"}

    def _seed_defaults(self) -> None:
        changed = False
        with self._lock:
            for effect_id in EFFECT_SPECS:
                if effect_id not in self._data:
                    self._data[effect_id] = {
                        "enabled": effect_id in self._DEFAULT_ENABLED,
                        "preset": DEFAULT_PRESET_NAME,
                    }
                    changed = True
        if changed:
            self.save()

    def is_enabled(self, effect_id: str) -> bool:
        with self._lock:
            return bool(self._data.get(effect_id, {}).get("enabled", False))

    def selected_preset(self, effect_id: str) -> str:
        with self._lock:
            return self._data.get(effect_id, {}).get("preset", DEFAULT_PRESET_NAME)

    def set_enabled(self, effect_id: str, enabled: bool) -> None:
        with self._lock:
            self._data.setdefault(effect_id, {})["enabled"] = enabled
        self.save()

    def set_selected_preset(self, effect_id: str, name: str) -> None:
        with self._lock:
            self._data.setdefault(effect_id, {})["preset"] = name
        self.save()


def build_active_effect_chain(
    preset_store: EffectsPresetStore, state_store: EffectsStateStore,
) -> list[tuple[str, dict]]:
    """Build the ordered list of (effect_id, params) for every currently
    enabled effect -- fed to Player.apply_effects() to update the real-time
    DSP chain directly, with no decode restart involved."""
    stages = []
    for effect_id in CHAIN_ORDER:
        if not state_store.is_enabled(effect_id):
            continue
        preset_name = state_store.selected_preset(effect_id)
        params = preset_store.get_preset(effect_id, preset_name)
        if params is None:
            params = EFFECT_SPECS[effect_id].default_params()
        stages.append((effect_id, params))
    return stages


def build_preview_effect_chain(
    preset_store: EffectsPresetStore, state_store: EffectsStateStore,
    preview_effect_id: str, preview_params: dict,
) -> list[tuple[str, dict]]:
    """Like build_active_effect_chain(), but substitutes `preview_params` for
    `preview_effect_id`'s stage (using them regardless of that effect's saved
    preset) and includes that stage even if the effect isn't currently
    enabled — so the Effects page can preview live, unsaved parameter edits
    against the actual playing stream before the user decides to save them
    as a preset or turn the effect on. Since the DSP chain applies instantly
    with no decode restart, this preview is truly live -- no debounce is
    strictly required anymore, though the UI still applies one to avoid
    updating a dozen times per drag gesture."""
    stages = []
    for effect_id in CHAIN_ORDER:
        if effect_id == preview_effect_id:
            stages.append((effect_id, preview_params))
            continue
        if not state_store.is_enabled(effect_id):
            continue
        preset_name = state_store.selected_preset(effect_id)
        params = preset_store.get_preset(effect_id, preset_name)
        if params is None:
            params = EFFECT_SPECS[effect_id].default_params()
        stages.append((effect_id, params))
    return stages

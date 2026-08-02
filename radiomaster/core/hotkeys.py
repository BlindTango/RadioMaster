"""Global (system-wide) hotkeys via wx's native RegisterHotKey/EVT_HOTKEY support.

Works even when RadioMaster isn't the focused window — the whole point of a
"global" hotkey (play/pause/stop/record/volume from anywhere).

Each action may have zero, one, or several key combinations bound to it (see
HotkeysDialog's add/edit/remove list), so config stores "hotkeys" as
dict[str, list[str]] rather than a single spec per action.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import wx

log = logging.getLogger(__name__)

MODIFIERS: tuple[tuple[str, str], ...] = (
    ("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("win", "Windows"),
)
_MODIFIER_MAP = {"ctrl": wx.MOD_CONTROL, "alt": wx.MOD_ALT, "shift": wx.MOD_SHIFT, "win": wx.MOD_WIN}

# (spec token, display label) -- the token is what's stored in a hotkey spec
# string (e.g. "Ctrl+MediaPlayPause") and must uppercase-match a _SPECIAL_KEYS
# entry below; the label is what the Hotkeys dialog's key list shows.
AVAILABLE_KEYS: tuple[tuple[str, str], ...] = (
    tuple((chr(c), chr(c)) for c in range(ord("A"), ord("Z") + 1))
    + tuple((str(d), str(d)) for d in range(10))
    + tuple((f"F{i}", f"F{i}") for i in range(1, 13))
    + (
        ("UP", "Up Arrow"), ("DOWN", "Down Arrow"), ("LEFT", "Left Arrow"), ("RIGHT", "Right Arrow"),
        ("SPACE", "Space"), ("ENTER", "Enter"), ("ESCAPE", "Escape"), ("TAB", "Tab"),
        ("HOME", "Home"), ("END", "End"), ("PAGEUP", "Page Up"), ("PAGEDOWN", "Page Down"),
        ("INSERT", "Insert"), ("DELETE", "Delete"),
    )
    + (
        ("MediaPlayPause", "Multimedia: Play/Pause"), ("MediaStop", "Multimedia: Stop"),
        ("MediaNextTrack", "Multimedia: Next Track"), ("MediaPrevTrack", "Multimedia: Previous Track"),
        ("VolumeUp", "Multimedia: Volume Up"), ("VolumeDown", "Multimedia: Volume Down"),
        ("VolumeMute", "Multimedia: Volume Mute"),
    )
)

_SPECIAL_KEYS = {
    "UP": wx.WXK_UP, "DOWN": wx.WXK_DOWN, "LEFT": wx.WXK_LEFT, "RIGHT": wx.WXK_RIGHT,
    "SPACE": wx.WXK_SPACE, "ENTER": wx.WXK_RETURN, "RETURN": wx.WXK_RETURN, "ESC": wx.WXK_ESCAPE,
    "ESCAPE": wx.WXK_ESCAPE, "TAB": wx.WXK_TAB, "HOME": wx.WXK_HOME, "END": wx.WXK_END,
    "PAGEUP": wx.WXK_PAGEUP, "PAGEDOWN": wx.WXK_PAGEDOWN, "INSERT": wx.WXK_INSERT,
    "DELETE": wx.WXK_DELETE,
    **{f"F{i}": getattr(wx, f"WXK_F{i}") for i in range(1, 13)},
    # Multimedia/browser keyboard keys -- these carry no modifiers in practice
    # (a physical media key doesn't also hold Ctrl down) but are still valid
    # RegisterHotKey targets on their own or combined with modifiers.
    "MEDIAPLAYPAUSE": wx.WXK_MEDIA_PLAY_PAUSE, "MEDIASTOP": wx.WXK_MEDIA_STOP,
    "MEDIANEXTTRACK": wx.WXK_MEDIA_NEXT_TRACK, "MEDIAPREVTRACK": wx.WXK_MEDIA_PREV_TRACK,
    "VOLUMEUP": wx.WXK_VOLUME_UP, "VOLUMEDOWN": wx.WXK_VOLUME_DOWN, "VOLUMEMUTE": wx.WXK_VOLUME_MUTE,
}


def parse_hotkey(spec: str) -> Optional[tuple[int, int]]:
    """'Ctrl+Alt+P' -> (wx.MOD_CONTROL | wx.MOD_ALT, ord('P')). None if invalid/empty."""
    spec = (spec or "").strip()
    if not spec:
        return None
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        return None
    modifiers = 0
    key_part = None
    for part in parts:
        low = part.lower()
        if low in _MODIFIER_MAP:
            modifiers |= _MODIFIER_MAP[low]
        else:
            key_part = part
    if key_part is None:
        return None
    keycode = _keycode_for(key_part)
    if keycode is None:
        return None
    return modifiers, keycode


def split_hotkey_parts(spec: str) -> Optional[tuple[dict[str, bool], str]]:
    """'Ctrl+Alt+P' -> ({"ctrl": True, "alt": True, "shift": False, "win": False}, "P").
    Used by the Hotkeys dialog to pre-fill an existing binding's checkboxes/key
    list selection. None if invalid/empty."""
    spec = (spec or "").strip()
    if not spec:
        return None
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        return None
    mods = {name: False for name, _ in MODIFIERS}
    key_token = None
    for part in parts:
        low = part.lower()
        if low in mods:
            mods[low] = True
        else:
            key_token = part
    if key_token is None or _keycode_for(key_token) is None:
        return None
    # Normalize to the exact token AVAILABLE_KEYS uses (case can differ, e.g.
    # a hand-typed legacy "p" vs. the canonical "P").
    upper = key_token.upper()
    for token, _label in AVAILABLE_KEYS:
        if token.upper() == upper:
            return mods, token
    return mods, key_token


def build_hotkey_spec(mods: dict[str, bool], key_token: str) -> str:
    """({"ctrl": True, "win": False, ...}, "P") -> 'Ctrl+P'."""
    parts = [label for name, label in MODIFIERS if mods.get(name)]
    parts.append(key_token)
    return "+".join(parts)


def _keycode_for(key_part: str) -> Optional[int]:
    upper = key_part.upper()
    if upper in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[upper]
    if len(upper) == 1 and upper.isalnum():
        return ord(upper)
    return None


class GlobalHotkeyManager:
    """Registers/unregisters system-wide hotkeys against a top-level wx.Window."""

    def __init__(self, window: wx.Window):
        self.window = window
        self._registered_ids: list[int] = []
        self._next_id = 1

    def register_all(self, hotkeys: dict[str, list[str]], handlers: dict[str, Callable[[], None]]) -> list[str]:
        """Registers every (action -> key spec) pair with a matching handler --
        each action may list several specs. Returns a list of human-readable
        warnings for any bindings that failed (e.g. already claimed by another
        application, or duplicated across two actions)."""
        self.unregister_all()
        warnings = []
        for action, specs in hotkeys.items():
            handler = handlers.get(action)
            for spec in specs or []:
                if not spec:
                    continue
                parsed = parse_hotkey(spec)
                if parsed is None:
                    warnings.append(f"'{spec}' for {action} is not a valid hotkey.")
                    continue
                modifiers, keycode = parsed
                hotkey_id = self._next_id
                self._next_id += 1
                if self.window.RegisterHotKey(hotkey_id, modifiers, keycode):
                    self._registered_ids.append(hotkey_id)
                    if handler:
                        self.window.Bind(wx.EVT_HOTKEY, lambda evt, h=handler: h(), id=hotkey_id)
                else:
                    warnings.append(f"'{spec}' for {action} could not be registered "
                                     f"(likely already in use by another application or another action).")
        return warnings

    def unregister_all(self) -> None:
        for hotkey_id in self._registered_ids:
            try:
                self.window.UnregisterHotKey(hotkey_id)
            except Exception:
                pass
        self._registered_ids.clear()

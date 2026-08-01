"""Global (system-wide) hotkeys via wx's native RegisterHotKey/EVT_HOTKEY support.

Works even when RadioMaster isn't the focused window — the whole point of a
"global" hotkey (play/pause/stop/record/volume from anywhere).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import wx

log = logging.getLogger(__name__)

_MODIFIER_MAP = {"ctrl": wx.MOD_CONTROL, "alt": wx.MOD_ALT, "shift": wx.MOD_SHIFT, "win": wx.MOD_WIN}

_SPECIAL_KEYS = {
    "UP": wx.WXK_UP, "DOWN": wx.WXK_DOWN, "LEFT": wx.WXK_LEFT, "RIGHT": wx.WXK_RIGHT,
    "SPACE": wx.WXK_SPACE, "ENTER": wx.WXK_RETURN, "RETURN": wx.WXK_RETURN, "ESC": wx.WXK_ESCAPE,
    "ESCAPE": wx.WXK_ESCAPE, "TAB": wx.WXK_TAB, "HOME": wx.WXK_HOME, "END": wx.WXK_END,
    "PAGEUP": wx.WXK_PAGEUP, "PAGEDOWN": wx.WXK_PAGEDOWN, "INSERT": wx.WXK_INSERT,
    "DELETE": wx.WXK_DELETE,
    **{f"F{i}": getattr(wx, f"WXK_F{i}") for i in range(1, 13)},
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

    def register_all(self, hotkeys: dict[str, str], handlers: dict[str, Callable[[], None]]) -> list[str]:
        """Registers every (action -> key spec) pair with a matching handler.
        Returns a list of human-readable warnings for any bindings that failed
        (e.g. already claimed by another application)."""
        self.unregister_all()
        warnings = []
        for action, spec in hotkeys.items():
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
                handler = handlers.get(action)
                if handler:
                    self.window.Bind(wx.EVT_HOTKEY, lambda evt, h=handler: h(), id=hotkey_id)
            else:
                warnings.append(f"'{spec}' for {action} could not be registered "
                                 f"(likely already in use by another application).")
        return warnings

    def unregister_all(self) -> None:
        for hotkey_id in self._registered_ids:
            try:
                self.window.UnregisterHotKey(hotkey_id)
            except Exception:
                pass
        self._registered_ids.clear()

"""Settings dialog for customizing global hotkeys (Play/Pause, Stop, Record, Volume)."""

from __future__ import annotations

import wx

from ..core.hotkeys import parse_hotkey
from ..utils.config import Config

ACTIONS = [
    ("play_pause", "Play/Pause"),
    ("stop", "Stop"),
    ("record", "Record Selected Station"),
    ("volume_up", "Volume Up"),
    ("volume_down", "Volume Down"),
]


class HotkeysDialog(wx.Dialog):
    def __init__(self, parent, config: Config):
        super().__init__(parent, title="Global Hotkeys", size=(460, 320))
        self.config = config

        hotkeys = config.get("hotkeys", {})
        self.ctrls: dict[str, wx.TextCtrl] = {}

        grid = wx.FlexGridSizer(len(ACTIONS), 2, 8, 10)
        grid.AddGrowableCol(1, 1)
        for key, label in ACTIONS:
            static = wx.StaticText(self, label=f"{label}:")
            ctrl = wx.TextCtrl(self, value=hotkeys.get(key, ""))
            ctrl.SetHint("e.g. Ctrl+Alt+P — leave blank to disable")
            self.ctrls[key] = ctrl
            grid.Add(static, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        note = wx.StaticText(
            self,
            label="Format: combine Ctrl/Alt/Shift/Win with a letter, number, F-key, or arrow "
                  "(e.g. Ctrl+Alt+P). These work even when RadioMaster isn't the focused window.",
        )
        note.Wrap(420)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(note, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)

        self.FindWindowById(wx.ID_OK, self).Bind(wx.EVT_BUTTON, self._on_ok)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        new_hotkeys = {}
        for key, ctrl in self.ctrls.items():
            value = ctrl.GetValue().strip()
            if value and parse_hotkey(value) is None:
                wx.MessageBox(f"'{value}' is not a valid hotkey.", "Invalid Hotkey",
                              wx.OK | wx.ICON_ERROR)
                return
            new_hotkeys[key] = value
        self.config.set("hotkeys", new_hotkeys)
        event.Skip()

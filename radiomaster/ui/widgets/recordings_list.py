"""Active Recordings panel: shows every concurrently-recording station with elapsed time."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ...utils.accessibility import context_menu_pos


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class RecordingsList(wx.Panel):
    """Station | Elapsed list + a button to stop whichever row is selected."""

    def __init__(self, parent):
        super().__init__(parent)

        recordings_label = wx.StaticText(self, label="Active Recordings:")
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Station", width=260)
        self.list_ctrl.InsertColumn(1, "Elapsed", width=100)

        self.stop_btn = wx.Button(self, label="Stop &Selected Recording")

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(recordings_label, 0, wx.LEFT | wx.TOP, 4)
        outer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        outer.Add(self.stop_btn, 0, wx.LEFT | wx.BOTTOM, 4)
        self.SetSizer(outer)

        self.on_stop_requested: Optional[Callable[[str], None]] = None
        self.stop_btn.Bind(wx.EVT_BUTTON, self._on_stop_click)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_stop_click)
        self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)

        self._keys_by_row: list[str] = []

    def refresh(self, sessions: dict[str, tuple[str, float]]) -> None:
        """sessions: {key: (station_name, elapsed_seconds)}"""
        selected_key = self._selected_key()

        self.list_ctrl.DeleteAllItems()
        self._keys_by_row = list(sessions.keys())
        for row, key in enumerate(self._keys_by_row):
            name, elapsed = sessions[key]
            idx = self.list_ctrl.InsertItem(row, name)
            self.list_ctrl.SetItem(idx, 1, _format_elapsed(elapsed))
            if key == selected_key:
                self.list_ctrl.Select(idx)

    def _selected_key(self) -> Optional[str]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1 or idx >= len(self._keys_by_row):
            return None
        return self._keys_by_row[idx]

    def _on_context_menu(self, event: wx.ContextMenuEvent) -> None:
        if self._selected_key() is None:
            return
        menu = wx.Menu()
        stop_item = menu.Append(wx.ID_ANY, "Stop &Selected Recording")
        self.Bind(wx.EVT_MENU, self._on_stop_click, stop_item)
        self.list_ctrl.PopupMenu(menu, context_menu_pos(self.list_ctrl, event))
        menu.Destroy()

    def _on_stop_click(self, event) -> None:
        key = self._selected_key()
        if key is None:
            wx.MessageBox("Select a recording to stop first.", "No Recording Selected",
                          wx.OK | wx.ICON_INFORMATION)
            return
        if self.on_stop_requested:
            self.on_stop_requested(key)

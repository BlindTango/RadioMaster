"""Favourites page: saved stations, quick play, remove, reorder."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ..core.favourites import FavouritesStore
from ..core.station_api import Station
from ..utils.accessibility import accessible_label


class FavouritesPanel(wx.Panel):
    def __init__(self, parent, favourites: FavouritesStore, on_play: Callable[[Station], None]):
        super().__init__(parent)
        self.favourites = favourites
        self.on_play = on_play

        accessible_label(self, "Favourite Stations")
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Station", width=220)
        self.list_ctrl.InsertColumn(1, "Country", width=140)
        self.list_ctrl.InsertColumn(2, "Genre", width=160)

        self.play_btn = wx.Button(self, label="&Play")
        self.remove_btn = wx.Button(self, label="&Remove")
        self.up_btn = wx.Button(self, label="Move &Up")
        self.down_btn = wx.Button(self, label="Move &Down")

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.play_btn, self.remove_btn, self.up_btn, self.down_btn):
            btn_row.Add(b, 0, wx.RIGHT, 6)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 6)
        outer.Add(btn_row, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.play_btn.Bind(wx.EVT_BUTTON, self._on_play_click)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.up_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(-1))
        self.down_btn.Bind(wx.EVT_BUTTON, lambda e: self._move(1))

        self.refresh()

    def refresh(self) -> None:
        self.list_ctrl.DeleteAllItems()
        for station in self.favourites.all():
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), station.name)
            self.list_ctrl.SetItem(idx, 1, station.country)
            self.list_ctrl.SetItem(idx, 2, ", ".join(station.genres))
            self.list_ctrl.SetItemData(idx, idx)

    def _selected_station(self) -> Optional[Station]:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            return None
        all_stations = self.favourites.all()
        if idx >= len(all_stations):
            return None
        return all_stations[idx]

    def _on_activate(self, event: wx.ListEvent) -> None:
        station = self._selected_station()
        if station:
            self.on_play(station)

    def _on_play_click(self, event: wx.CommandEvent) -> None:
        station = self._selected_station()
        if station:
            self.on_play(station)
        else:
            wx.MessageBox("Select a favourite station first.", "No Selection", wx.OK | wx.ICON_INFORMATION)

    def _on_remove(self, event: wx.CommandEvent) -> None:
        station = self._selected_station()
        if station:
            self.favourites.remove(station.uuid)
            self.refresh()

    def _move(self, direction: int) -> None:
        idx = self.list_ctrl.GetFirstSelected()
        if idx == -1:
            return
        all_stations = self.favourites.all()
        if idx >= len(all_stations):
            return
        station = all_stations[idx]
        self.favourites.move(station.uuid, idx + direction)
        self.refresh()
        new_idx = max(0, min(idx + direction, self.list_ctrl.GetItemCount() - 1))
        self.list_ctrl.Select(new_idx)
        self.list_ctrl.Focus(new_idx)

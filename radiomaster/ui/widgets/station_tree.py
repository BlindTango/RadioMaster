"""Accessible station browser: Alphabetical / By Genre / By Country / By
Language -> stations.

This used to be a wx.TreeCtrl. It was replaced entirely after conclusive A/B
testing: the exact same "populate from a background-thread-triggered
callback" workload was run head-to-head, 10 repeated trials each —

  wx.TreeCtrl:  8 crashes / 10 runs (always the same access violation,
                inside wx's own event loop, confirmed via PYTHONFAULTHANDLER)
  wx.ListCtrl:  0 crashes / 10 runs, identical data, identical timing

Neither the item-count cap, the SetItemData payload type (object vs plain
int), Freeze()/Thaw(), nor deferring the load via a wx.Timer instead of
wx.CallAfter changed the TreeCtrl's failure rate — the control itself is
unstable in this environment (reproduced on both wxWidgets 3.2.7 and 3.3.3).
wx.ListCtrl handling the identical data was unconditionally stable, so the
station browser is now Category (Choice) -> Groups (ListCtrl) -> Stations
(ListCtrl), a flat two-pane browser instead of a tree.

Both lists run in LC_VIRTUAL mode: rows are supplied on demand via
OnGetItemText() rather than inserted one at a time, so populating even the
~8,500-station "#" bucket is an O(1) SetItemCount() call instead of
thousands of InsertItem()/SetItem() calls (previously visible as multi-
second "sluggish" delays with nothing displayed in between).
"""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ...core.station_api import Station
from ...core.station_db import StationDB
from ...utils.accessibility import accessible_label

SECTION_ALPHABET = "alphabet"
SECTION_GENRE = "genre"
SECTION_COUNTRY = "country"
SECTION_LANGUAGE = "language"
SECTION_NETWORK = "network"
SECTION_CUSTOM = "custom"
SECTION_SEARCH = "search"

# (visible choice label, internal key, group-list column header, group-list visible caption)
SECTION_CHOICES = [
    ("Alphabetical", SECTION_ALPHABET, "Letter", "Letters:"),
    ("By Genre", SECTION_GENRE, "Genre", "Genres:"),
    ("By Country", SECTION_COUNTRY, "Country", "Countries:"),
    ("By Language", SECTION_LANGUAGE, "Language", "Languages:"),
    ("By Network", SECTION_NETWORK, "Network", "Networks:"),
    ("Custom Stations", SECTION_CUSTOM, "Station", "Custom Stations:"),
    ("Search Results", SECTION_SEARCH, "Station", "Search Results:"),
]

# Synthetic first entry in each category's group list — selecting it shows
# every station in the catalog rather than one group's worth. Keyed by
# section so _load_stations_for_group can recognize it regardless of
# position (it's always index 0, but matching by label is robust even if
# that ever changes).
ALL_LABELS = {
    SECTION_ALPHABET: "All Stations",
    SECTION_GENRE: "All Genres",
    SECTION_COUNTRY: "All Countries",
    SECTION_LANGUAGE: "All Languages",
    SECTION_NETWORK: "All Networks",
}


class _VirtualGroupList(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.groups: list[tuple[str, int]] = []

    def OnGetItemText(self, item, column):
        if 0 <= item < len(self.groups):
            name, count = self.groups[item]
            return name if column == 0 else str(count)
        return ""

    def set_groups(self, groups: list[tuple[str, int]]) -> None:
        self.groups = groups
        self.SetItemCount(len(groups))
        if groups:
            self.RefreshItems(0, len(groups) - 1)


class _VirtualStationList(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.stations: list[Station] = []

    def OnGetItemText(self, item, column):
        if not (0 <= item < len(self.stations)):
            return ""
        station = self.stations[item]
        if column == 0:
            return station.name
        if column == 1:
            return station.country
        return str(station.bitrate) if station.bitrate else ""

    def set_stations(self, stations: list[Station]) -> None:
        self.stations = stations
        self.SetItemCount(len(stations))
        if stations:
            self.RefreshItems(0, len(stations) - 1)


class StationTree(wx.Panel):
    """Kept the class name `StationTree` to avoid touching every call site —
    it's a flat two-pane browser now, not a tree; see module docstring."""

    def __init__(self, parent, db: StationDB):
        super().__init__(parent)
        self.db = db
        self.on_station_activated: Optional[Callable[[Station], None]] = None
        self.on_selection_changed: Optional[Callable[[], None]] = None

        self._section_groups: dict[str, list[tuple[str, int]]] = {}
        self._current_section: str = SECTION_ALPHABET
        self._current_groups: list[tuple[str, int]] = []
        self._current_stations: list[Station] = []
        self._custom_stations: list[Station] = []
        self._search_stations: list[Station] = []

        accessible_label(self, "Station category")
        self.section_choice = wx.Choice(self, choices=[label for label, *_ in SECTION_CHOICES])
        self.section_choice.SetSelection(0)

        # group_label is group_list's accessible name via Windows' native
        # "adjacent static labels its sibling" convention (must be
        # constructed right before group_list, same parent) — its text
        # changes live in _update_group_label() below, and that's read live
        # too, so no extra API call is needed when the category changes.
        self.group_label = wx.StaticText(self, label="Letters:")
        self.group_list = _VirtualGroupList(self)
        self.group_list.InsertColumn(0, "Letter", width=220)
        self.group_list.InsertColumn(1, "Stations", width=80)

        stations_label = wx.StaticText(self, label="Stations:")
        self.station_list = _VirtualStationList(self)
        self.station_list.InsertColumn(0, "Station", width=240)
        self.station_list.InsertColumn(1, "Country", width=140)
        self.station_list.InsertColumn(2, "Bitrate", width=80)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(self.group_label, 0, wx.BOTTOM, 2)
        left.Add(self.group_list, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(stations_label, 0, wx.BOTTOM, 2)
        right.Add(self.station_list, 1, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 1, wx.EXPAND | wx.RIGHT, 4)
        body.Add(right, 1, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.section_choice, 0, wx.EXPAND | wx.BOTTOM, 4)
        outer.Add(body, 1, wx.EXPAND)
        self.SetSizer(outer)

        self.section_choice.Bind(wx.EVT_CHOICE, self._on_section_changed)
        self.group_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_group_selected)
        self.station_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_station_selected)
        self.station_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_station_activated_event)

    # ---- public API (kept compatible with the old StationTree) ---------------

    def load_sections(self) -> None:
        total = self.db.station_count()
        self._section_groups = {
            SECTION_ALPHABET: [(ALL_LABELS[SECTION_ALPHABET], total)] + self.db.alphabet_groups(),
            SECTION_GENRE: [(ALL_LABELS[SECTION_GENRE], total)] + self.db.genre_groups(),
            SECTION_COUNTRY: [(ALL_LABELS[SECTION_COUNTRY], total)] + self.db.country_groups(),
            SECTION_LANGUAGE: [(ALL_LABELS[SECTION_LANGUAGE], total)] + self.db.language_groups(),
            SECTION_NETWORK: [(ALL_LABELS[SECTION_NETWORK], total)] + self.db.network_groups(),
        }
        self.section_choice.SetSelection(0)
        self._show_section(SECTION_ALPHABET)

    def add_custom_section(self, stations: list[Station]) -> None:
        self._custom_stations = sorted(stations, key=lambda s: s.name.lower())
        if self._current_section == SECTION_CUSTOM:
            self._show_flat_list(self._custom_stations)

    def show_custom_stations(self) -> None:
        """Switch to the Custom Stations category and show its current
        contents — used right after adding a station so the user gets
        immediate visible confirmation instead of it silently landing in a
        category they aren't looking at (which read as "it didn't save")."""
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_CUSTOM)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_CUSTOM
        self._update_group_label(SECTION_CUSTOM)
        self._show_flat_list(self._custom_stations)

    def set_search_results(self, stations: list[Station]) -> None:
        self._search_stations = sorted(stations, key=lambda s: s.name.lower())
        idx = [key for _, key, *_ in SECTION_CHOICES].index(SECTION_SEARCH)
        self.section_choice.SetSelection(idx)
        self._current_section = SECTION_SEARCH
        self._update_group_label(SECTION_SEARCH)
        self._show_flat_list(self._search_stations)

    def get_selected_station(self) -> Optional[Station]:
        idx = self.station_list.GetFirstSelected()
        if 0 <= idx < len(self._current_stations):
            return self._current_stations[idx]
        return None

    # ---- internals -------------------------------------------------------

    def _update_group_label(self, key: str) -> None:
        for _label, section_key, column_header, caption in SECTION_CHOICES:
            if section_key == key:
                # group_list's accessible name comes from group_label being
                # its immediately preceding sibling (see __init__) — Windows
                # reads that static's CURRENT text live, so changing the
                # caption here is enough; no separate accessible-name call.
                self.group_label.SetLabel(caption)
                col = wx.ListItem()
                col.SetText(column_header)
                self.group_list.SetColumn(0, col)
                return

    def _show_section(self, key: str) -> None:
        self._current_section = key
        self._update_group_label(key)
        groups = self._section_groups.get(key, [])
        self._current_groups = groups
        self.group_list.set_groups(groups)
        # Auto-select the first group so stations are visible immediately —
        # matches how a user actually browses (open category -> see results),
        # rather than landing on an empty station list until they manually
        # pick something.
        self._select_group_index(0)

    def _show_flat_list(self, stations: list[Station]) -> None:
        self._current_groups = []
        self.group_list.set_groups([])
        self._populate_station_list(stations)

    def _select_group_index(self, idx: int) -> None:
        if not (0 <= idx < len(self._current_groups)):
            self._populate_station_list([])
            return
        self.group_list.Select(idx)
        self.group_list.Focus(idx)
        self.group_list.EnsureVisible(idx)
        name, _count = self._current_groups[idx]
        self._load_stations_for_group(name)

    def _load_stations_for_group(self, name: str) -> None:
        if name == ALL_LABELS.get(self._current_section):
            stations = self.db.all_stations()
        elif self._current_section == SECTION_ALPHABET:
            stations = self.db.stations_by_letter(name)
        elif self._current_section == SECTION_GENRE:
            stations = self.db.stations_by_genre(name)
        elif self._current_section == SECTION_COUNTRY:
            stations = self.db.stations_by_country(name)
        elif self._current_section == SECTION_NETWORK:
            stations = self.db.stations_by_network(name)
        else:
            stations = self.db.stations_by_language(name)
        self._populate_station_list(stations)

    def _populate_station_list(self, stations: list[Station]) -> None:
        self._current_stations = stations
        self.station_list.set_stations(stations)
        if stations:
            self.station_list.Select(0)
            self.station_list.Focus(0)
        if self.on_selection_changed:
            self.on_selection_changed()

    def _on_section_changed(self, event: wx.CommandEvent) -> None:
        idx = self.section_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        key = SECTION_CHOICES[idx][1]
        if key in (SECTION_ALPHABET, SECTION_GENRE, SECTION_COUNTRY, SECTION_LANGUAGE, SECTION_NETWORK):
            self._show_section(key)
        elif key == SECTION_CUSTOM:
            self._current_section = SECTION_CUSTOM
            self._update_group_label(SECTION_CUSTOM)
            self._show_flat_list(self._custom_stations)
        else:
            self._current_section = SECTION_SEARCH
            self._update_group_label(SECTION_SEARCH)
            self._show_flat_list(self._search_stations)

    def _on_group_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if not (0 <= idx < len(self._current_groups)):
            return
        name, _count = self._current_groups[idx]
        self._load_stations_for_group(name)

    def _on_station_selected(self, event: wx.ListEvent) -> None:
        if self.on_selection_changed:
            self.on_selection_changed()

    def _on_station_activated_event(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self._current_stations) and self.on_station_activated:
            self.on_station_activated(self._current_stations[idx])

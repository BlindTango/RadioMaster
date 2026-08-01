"""Scheduler page: schedule list + new/edit schedule form (PRD 6.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import wx
import wx.adv

from ..core.favourites import FavouritesStore
from ..core.custom_stations import CustomStationsStore
from ..core.scheduler import (
    Schedule, ScheduleStore, RecordingScheduler, WEEKDAY_NAMES, find_conflicts, new_schedule_id,
)
from ..core.station_api import Station
from ..utils.accessibility import accessible_label

SCHEDULE_TYPES = ["One-time", "Daily", "Weekly", "Nth weekday of month", "Custom interval"]
ORDINALS = ["1st", "2nd", "3rd", "4th", "Last"]
FORMATS = ["mp3", "aac", "flac", "ogg", "wav"]


class NewScheduleForm(wx.Panel):
    def __init__(self, parent, stations_provider):
        super().__init__(parent)
        self.stations_provider = stations_provider
        self._stations: list[Station] = []

        accessible_label(self, "Station")
        self.station_choice = wx.Choice(self)
        accessible_label(self, "Schedule type")
        self.type_choice = wx.Choice(self, choices=SCHEDULE_TYPES)
        self.type_choice.SetSelection(0)

        self.date_picker = wx.adv.DatePickerCtrl(self)
        self.time_picker = wx.adv.TimePickerCtrl(self)

        accessible_label(self, "Duration in minutes, 0 for until stop")
        self.duration_ctrl = wx.SpinCtrl(self, min=0, max=1440, initial=60)
        self.until_stop_check = wx.CheckBox(self, label="Record until stopped manually")

        self.weekday_checks = {d: wx.CheckBox(self, label=d.title()) for d in WEEKDAY_NAMES}
        weekday_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for cb in self.weekday_checks.values():
            weekday_sizer.Add(cb, 0, wx.RIGHT, 6)

        self.ordinal_choice = wx.Choice(self, choices=ORDINALS)
        self.ordinal_choice.SetSelection(0)
        self.nth_weekday_choice = wx.Choice(self, choices=[d.title() for d in WEEKDAY_NAMES])
        self.nth_weekday_choice.SetSelection(0)

        self.interval_days_ctrl = wx.SpinCtrl(self, min=1, max=365, initial=7)
        self.interval_start_picker = wx.adv.DatePickerCtrl(self)

        accessible_label(self, "Output format")
        self.format_choice = wx.Choice(self, choices=FORMATS)
        self.format_choice.SetSelection(0)

        self.save_btn = wx.Button(self, label="&Save Schedule")

        grid = wx.FlexGridSizer(2, 2, 6, 8)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(self, label="&Station:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.station_choice, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="&Type:"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.type_choice, 1, wx.EXPAND)

        date_row = wx.BoxSizer(wx.HORIZONTAL)
        date_row.Add(wx.StaticText(self, label="Start &date:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        date_row.Add(self.date_picker, 0, wx.RIGHT, 12)
        date_row.Add(wx.StaticText(self, label="&Time:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        date_row.Add(self.time_picker, 0)

        duration_row = wx.BoxSizer(wx.HORIZONTAL)
        duration_row.Add(wx.StaticText(self, label="&Duration (minutes):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        duration_row.Add(self.duration_ctrl, 0, wx.RIGHT, 12)
        duration_row.Add(self.until_stop_check, 0, wx.ALIGN_CENTER_VERTICAL)

        ordinal_row = wx.BoxSizer(wx.HORIZONTAL)
        ordinal_row.Add(wx.StaticText(self, label="&Ordinal:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        ordinal_row.Add(self.ordinal_choice, 0, wx.RIGHT, 12)
        ordinal_row.Add(wx.StaticText(self, label="&Weekday:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        ordinal_row.Add(self.nth_weekday_choice, 0)

        interval_row = wx.BoxSizer(wx.HORIZONTAL)
        interval_row.Add(wx.StaticText(self, label="&Every N days:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        interval_row.Add(self.interval_days_ctrl, 0, wx.RIGHT, 12)
        interval_row.Add(wx.StaticText(self, label="Starting:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        interval_row.Add(self.interval_start_picker, 0)

        format_row = wx.BoxSizer(wx.HORIZONTAL)
        format_row.Add(wx.StaticText(self, label="Output &format:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        format_row.Add(self.format_choice, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(date_row, 0, wx.ALL, 6)
        outer.Add(wx.StaticText(self, label="Weekdays (Weekly):"), 0, wx.LEFT | wx.TOP, 6)
        outer.Add(weekday_sizer, 0, wx.ALL, 6)
        outer.Add(ordinal_row, 0, wx.ALL, 6)
        outer.Add(interval_row, 0, wx.ALL, 6)
        outer.Add(duration_row, 0, wx.ALL, 6)
        outer.Add(format_row, 0, wx.ALL, 6)
        outer.Add(self.save_btn, 0, wx.ALL, 6)
        self.SetSizer(outer)

        self.type_choice.Bind(wx.EVT_CHOICE, lambda e: self._update_visibility())
        self.until_stop_check.Bind(wx.EVT_CHECKBOX, lambda e: self._update_visibility())
        self.refresh_stations()
        self._update_visibility()

    def refresh_stations(self) -> None:
        self._stations = self.stations_provider()
        self.station_choice.Clear()
        for s in self._stations:
            self.station_choice.Append(s.name)
        if self._stations:
            self.station_choice.SetSelection(0)

    def _update_visibility(self) -> None:
        idx = self.type_choice.GetSelection()
        self.date_picker.Show(idx == 0)
        self.time_picker.Show(idx in (1, 2, 3))
        for cb in self.weekday_checks.values():
            cb.Show(idx == 2)
        self.ordinal_choice.Show(idx == 3)
        self.nth_weekday_choice.Show(idx == 3)
        self.interval_days_ctrl.Show(idx == 4)
        self.interval_start_picker.Show(idx == 4)
        self.duration_ctrl.Enable(not self.until_stop_check.GetValue())
        self.Layout()

    def selected_station(self) -> Optional[Station]:
        idx = self.station_choice.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._stations):
            return None
        return self._stations[idx]

    def build_schedule(self) -> Optional[Schedule]:
        station = self.selected_station()
        if not station:
            wx.MessageBox("Save a favourite or custom station first, then pick it here.",
                           "No Station Available", wx.OK | wx.ICON_INFORMATION)
            return None

        idx = self.type_choice.GetSelection()
        duration = None if self.until_stop_check.GetValue() else self.duration_ctrl.GetValue()
        fmt = FORMATS[self.format_choice.GetSelection()]

        def wx_date_to_iso(date_ctrl, time_ctrl) -> str:
            d = date_ctrl.GetValue()
            hour, minute, _ = time_ctrl.GetTime()
            dt = datetime(d.GetYear(), d.GetMonth() + 1, d.GetDay(), hour, minute)
            return dt.isoformat()

        sched = Schedule(
            id=new_schedule_id(), station_uuid=station.uuid, station_name=station.name,
            station_url=station.url, schedule_type="", duration_minutes=duration, output_format=fmt,
        )

        if idx == 0:
            sched.schedule_type = "one_time"
            sched.start_datetime = wx_date_to_iso(self.date_picker, self.time_picker)
        elif idx == 1:
            sched.schedule_type = "daily"
            hour, minute, _ = self.time_picker.GetTime()
            sched.time_of_day = f"{hour:02d}:{minute:02d}"
        elif idx == 2:
            sched.schedule_type = "weekly"
            hour, minute, _ = self.time_picker.GetTime()
            sched.time_of_day = f"{hour:02d}:{minute:02d}"
            sched.weekdays = [d for d, cb in self.weekday_checks.items() if cb.GetValue()]
            if not sched.weekdays:
                wx.MessageBox("Pick at least one weekday.", "Missing Weekday", wx.OK | wx.ICON_WARNING)
                return None
        elif idx == 3:
            sched.schedule_type = "nth_weekday"
            hour, minute, _ = self.time_picker.GetTime()
            sched.time_of_day = f"{hour:02d}:{minute:02d}"
            ordinal_label = ORDINALS[self.ordinal_choice.GetSelection()]
            sched.ordinal = -1 if ordinal_label == "Last" else int(ordinal_label[0])
            sched.weekday = WEEKDAY_NAMES[self.nth_weekday_choice.GetSelection()]
        else:
            sched.schedule_type = "interval"
            sched.interval_days = self.interval_days_ctrl.GetValue()
            d = self.interval_start_picker.GetValue()
            sched.interval_start = datetime(d.GetYear(), d.GetMonth() + 1, d.GetDay()).isoformat()

        return sched


class SchedulerPanel(wx.Panel):
    def __init__(self, parent, favourites: FavouritesStore, custom_stations: CustomStationsStore,
                 store: ScheduleStore, scheduler: RecordingScheduler):
        super().__init__(parent)
        self.store = store
        self.scheduler = scheduler

        accessible_label(self, "Scheduled Recordings")
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Enabled", width=70)
        self.list_ctrl.InsertColumn(1, "Schedule", width=420)

        self.add_btn = wx.Button(self, label="&Add")
        self.delete_btn = wx.Button(self, label="&Delete")
        self.toggle_btn = wx.Button(self, label="&Enable/Disable")

        list_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        for b in (self.add_btn, self.delete_btn, self.toggle_btn):
            list_btn_row.Add(b, 0, wx.RIGHT, 6)

        def stations_provider() -> list[Station]:
            return favourites.all() + custom_stations.all()

        self.form = NewScheduleForm(self, stations_provider)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(self, label="Schedule List"), 0, wx.ALL, 4)
        left.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        left.Add(list_btn_row, 0, wx.EXPAND | wx.ALL, 4)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(wx.StaticText(self, label="New Schedule"), 0, wx.ALL, 4)
        right.Add(self.form, 1, wx.EXPAND | wx.ALL, 4)

        outer = wx.BoxSizer(wx.HORIZONTAL)
        outer.Add(left, 1, wx.EXPAND | wx.ALL, 6)
        outer.Add(right, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)

        self.add_btn.Bind(wx.EVT_BUTTON, lambda e: self.form.SetFocus())
        self.form.save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.toggle_btn.Bind(wx.EVT_BUTTON, self._on_toggle)

        self.refresh()

    def refresh(self) -> None:
        self.form.refresh_stations()
        self.list_ctrl.DeleteAllItems()
        for sched in self.store.all():
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), "Yes" if sched.enabled else "No")
            self.list_ctrl.SetItem(idx, 1, sched.describe())

    def _selected_schedule(self) -> Optional[Schedule]:
        idx = self.list_ctrl.GetFirstSelected()
        all_scheds = self.store.all()
        if idx == -1 or idx >= len(all_scheds):
            return None
        return all_scheds[idx]

    def _on_save(self, event: wx.CommandEvent) -> None:
        sched = self.form.build_schedule()
        if sched is None:
            return

        conflicts = find_conflicts(self.store.all() + [sched])
        relevant = [c for c in conflicts if sched in c]
        if relevant:
            other = relevant[0][0] if relevant[0][1] is sched else relevant[0][1]
            if wx.MessageBox(
                f"This overlaps with an existing schedule: {other.describe()}.\nSave anyway?",
                "Schedule Conflict", wx.YES_NO | wx.ICON_WARNING,
            ) != wx.YES:
                return

        self.store.add(sched)
        self.scheduler.reload()
        self.refresh()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        sched = self._selected_schedule()
        if sched:
            self.store.remove(sched.id)
            self.scheduler.reload()
            self.refresh()

    def _on_toggle(self, event: wx.CommandEvent) -> None:
        sched = self._selected_schedule()
        if sched:
            sched.enabled = not sched.enabled
            self.store.update(sched)
            self.scheduler.reload()
            self.refresh()

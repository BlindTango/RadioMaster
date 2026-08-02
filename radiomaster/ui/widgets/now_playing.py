"""Read-only station name / now-playing text fields and the status bar text."""

from __future__ import annotations

import wx


class ReadOnlyFocusableTextCtrl(wx.TextCtrl):
    """A TE_READONLY wx.TextCtrl is focusable via mouse/SetFocus() but wx
    excludes it from Tab-key navigation by default — AcceptsFocusFromKeyboard()
    returns False for it, confirmed directly (a plain TE_READONLY control was
    skipped by Tab in a live app, landing on the wrapping panel instead, while
    this override lets Tab reach it normally). Screen reader users still need
    to Tab to a read-only field and use arrow keys to read its content, so
    the default here is wrong for this app; override it back to True."""

    def AcceptsFocusFromKeyboard(self) -> bool:
        return True


class NowPlayingPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        station_label = wx.StaticText(self, label="Station:")
        self.station_field = ReadOnlyFocusableTextCtrl(self, style=wx.TE_READONLY)

        now_label = wx.StaticText(self, label="Now Playing:")
        self.now_playing_field = ReadOnlyFocusableTextCtrl(self, style=wx.TE_READONLY)

        grid = wx.FlexGridSizer(2, 2, 4, 8)
        grid.AddGrowableCol(1, 1)
        grid.Add(station_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.station_field, 1, wx.EXPAND)
        grid.Add(now_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.now_playing_field, 1, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 4)
        self.SetSizer(outer)

    def set_station(self, name: str) -> None:
        self.station_field.ChangeValue(name)

    def set_now_playing(self, text: str) -> None:
        self.now_playing_field.ChangeValue(text)


def format_status(state_label: str, bitrate_kbps: int = 0, codec: str = "",
                   sample_rate: int = 0, buffer_fill: float = 0.0,
                   ad_flagged: bool = False) -> str:
    parts = [f"Status: {state_label}"]
    if bitrate_kbps:
        parts.append(f"{bitrate_kbps} kbps")
    if codec:
        parts.append(codec)
    if sample_rate:
        parts.append(f"{sample_rate} Hz")
    # Rounded to the nearest 5% -- the raw percentage jitters by 1-2 points
    # essentially every tick, which would otherwise make this "stable" text
    # change (and re-announce to screen readers) almost continuously.
    rounded_fill = int(round(buffer_fill * 100 / 5) * 5)
    parts.append(f"Buffer: {rounded_fill}%")
    if ad_flagged:
        parts.append("Likely advertisement")
    return " | ".join(parts)

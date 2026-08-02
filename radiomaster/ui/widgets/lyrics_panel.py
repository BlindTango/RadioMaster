"""Read-only lyrics display for the currently playing track, with a status
line separate from the lyrics text itself (fetching/not-found/error states
shouldn't overwrite or be confused with actual lyrics content)."""

from __future__ import annotations

import wx

from .now_playing import ReadOnlyFocusableTextCtrl


class LyricsPanel(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        status_label = wx.StaticText(self, label="Lyrics status:")
        self.status_field = ReadOnlyFocusableTextCtrl(self, style=wx.TE_READONLY)
        self.status_field.ChangeValue("(No track playing)")

        lyrics_label = wx.StaticText(self, label="Lyrics:")
        self.lyrics_ctrl = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
        )
        self.lyrics_ctrl.SetMinSize((-1, 160))

        status_row = wx.BoxSizer(wx.HORIZONTAL)
        status_row.Add(status_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        status_row.Add(self.status_field, 1, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(status_row, 0, wx.EXPAND | wx.BOTTOM, 4)
        outer.Add(lyrics_label, 0, wx.BOTTOM, 2)
        outer.Add(self.lyrics_ctrl, 1, wx.EXPAND)
        self.SetSizer(outer)

    def set_status(self, text: str) -> None:
        self.status_field.ChangeValue(text)

    def set_lyrics(self, text: str) -> None:
        self.lyrics_ctrl.ChangeValue(text)

    def clear(self) -> None:
        self.status_field.ChangeValue("(No track playing)")
        self.lyrics_ctrl.ChangeValue("")

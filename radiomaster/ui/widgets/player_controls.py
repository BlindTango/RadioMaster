"""Play/Pause, Stop, Record, Mute, Volume row with accessible toggling labels."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ...utils.accessibility import accessible_label


class PlayerControls(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self.play_btn = wx.Button(self, label="▶ Play")
        self.play_btn.SetToolTip("Play or pause the selected station")
        self.stop_btn = wx.Button(self, label="⏹ Stop")
        self.stop_btn.SetToolTip("Stop playback")
        self.record_btn = wx.Button(self, label="● Record Off")
        self.record_btn.SetToolTip("Toggle recording of the current stream")
        self.mute_btn = wx.Button(self, label="\U0001F507 Mute Off")
        self.mute_btn.SetToolTip("Toggle mute")

        # wx.SL_LABELS is deliberately NOT used here: it makes wx continuously
        # overwrite the slider's own accessible Name with its current numeric
        # value, clobbering any descriptive name (see utils/accessibility.py).
        # accessible_label() gives the slider a stable "Volume"/"Pan" name
        # instead; the visible percent readout is a plain StaticText kept in
        # sync on EVT_SLIDER.
        self.volume_label = wx.StaticText(self, label="Volume:")
        accessible_label(self, "Volume")
        self.volume_slider = wx.Slider(self, value=100, minValue=0, maxValue=100,
                                        style=wx.SL_HORIZONTAL)
        self.volume_slider.SetToolTip("Playback volume")
        self.volume_value_label = wx.StaticText(self, label="100%")

        self.pan_label = wx.StaticText(self, label="Pan:")
        accessible_label(self, "Pan")
        self.pan_slider = wx.Slider(self, value=50, minValue=0, maxValue=100,
                                     style=wx.SL_HORIZONTAL)
        self.pan_slider.SetToolTip("Stereo pan — 0% full left, 50% centre, 100% full right")
        self.pan_value_label = wx.StaticText(self, label="50%")

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        for btn in (self.play_btn, self.stop_btn, self.record_btn, self.mute_btn):
            button_row.Add(btn, 0, wx.ALL, 4)

        volume_row = wx.BoxSizer(wx.HORIZONTAL)
        volume_row.Add(self.volume_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
        volume_row.Add(self.volume_slider, 1, wx.EXPAND | wx.RIGHT, 4)
        volume_row.Add(self.volume_value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        pan_row = wx.BoxSizer(wx.HORIZONTAL)
        pan_row.Add(self.pan_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
        pan_row.Add(self.pan_slider, 1, wx.EXPAND | wx.RIGHT, 4)
        pan_row.Add(self.pan_value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(button_row, 0, wx.EXPAND)
        outer.Add(volume_row, 0, wx.EXPAND)
        outer.Add(pan_row, 0, wx.EXPAND)
        self.SetSizer(outer)

        self.on_play: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_record: Optional[Callable[[], None]] = None
        self.on_mute: Optional[Callable[[], None]] = None
        self.on_volume_changed: Optional[Callable[[int], None]] = None
        self.on_pan_changed: Optional[Callable[[int], None]] = None

        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_play and self.on_play())
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_stop and self.on_stop())
        self.record_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_record and self.on_record())
        self.mute_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_mute and self.on_mute())
        self.volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_slider)
        self.pan_slider.Bind(wx.EVT_SLIDER, self._on_pan_slider)

    def _on_volume_slider(self, event: wx.Event) -> None:
        value = self.volume_slider.GetValue()
        self.volume_value_label.SetLabel(f"{value}%")
        if self.on_volume_changed:
            self.on_volume_changed(value)

    def _on_pan_slider(self, event: wx.Event) -> None:
        value = self.pan_slider.GetValue()
        self.pan_value_label.SetLabel(f"{value}%")
        if self.on_pan_changed:
            self.on_pan_changed(value)

    def set_playing(self, is_playing: bool) -> None:
        self.play_btn.SetLabel("⏸ Pause" if is_playing else "▶ Play")

    def set_recording(self, is_recording: bool) -> None:
        self.record_btn.SetLabel("● Recording On" if is_recording else "● Record Off")

    def set_muted(self, is_muted: bool) -> None:
        self.mute_btn.SetLabel("\U0001F507 Mute On" if is_muted else "\U0001F507 Mute Off")

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.volume_slider.SetValue(percent)
        self.volume_value_label.SetLabel(f"{percent}%")

    def set_pan(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.pan_slider.SetValue(percent)
        self.pan_value_label.SetLabel(f"{percent}%")


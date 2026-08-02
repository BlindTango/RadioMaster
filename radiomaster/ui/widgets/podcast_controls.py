"""Play/Pause, Stop, Previous, Next episode controls + Volume/Rate/Pan sliders.

Mirrors widgets/player_controls.py's accessible-slider pattern (see that
file and utils/accessibility.py for why SL_LABELS is avoided).
"""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ...utils.accessibility import accessible_label


class PodcastControls(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent)

        self.prev_btn = wx.Button(self, label="⏮ Previous")
        self.prev_btn.SetToolTip("Play the previous episode")
        self.play_btn = wx.Button(self, label="▶ Play")
        self.play_btn.SetToolTip("Play or pause the selected episode")
        self.stop_btn = wx.Button(self, label="⏹ Stop")
        self.stop_btn.SetToolTip("Stop playback")
        self.next_btn = wx.Button(self, label="⏭ Next")
        self.next_btn.SetToolTip("Play the next episode")

        self.volume_label = wx.StaticText(self, label="Volume:")
        accessible_label(self, "Volume")
        self.volume_slider = wx.Slider(self, value=100, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.volume_slider.SetToolTip("Playback volume")
        self.volume_value_label = wx.StaticText(self, label="100%")

        self.rate_label = wx.StaticText(self, label="Rate:")
        accessible_label(self, "Playback rate")
        # 50-300 maps to 0.5x-3.0x; ffmpeg's atempo filter applies this on
        # the podcast decode process (see core/player.py) -- it only takes
        # effect from the start of the next Play/Previous/Next, not live
        # mid-episode, since changing it would mean restarting the decode
        # and losing the current playback position.
        self.rate_slider = wx.Slider(self, value=100, minValue=50, maxValue=300, style=wx.SL_HORIZONTAL)
        self.rate_slider.SetToolTip(
            "Playback speed — applies the next time you press Play, Previous, or Next")
        self.rate_value_label = wx.StaticText(self, label="1.0x")

        self.pan_label = wx.StaticText(self, label="Pan:")
        accessible_label(self, "Pan")
        self.pan_slider = wx.Slider(self, value=50, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.pan_slider.SetToolTip("Stereo pan — 0% full left, 50% centre, 100% full right")
        self.pan_value_label = wx.StaticText(self, label="50%")

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        for btn in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            button_row.Add(btn, 0, wx.ALL, 4)

        def slider_row(label, slider, value_label):
            r = wx.BoxSizer(wx.HORIZONTAL)
            r.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 4)
            r.Add(slider, 1, wx.EXPAND | wx.RIGHT, 4)
            r.Add(value_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
            return r

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(button_row, 0, wx.EXPAND)
        outer.Add(slider_row(self.volume_label, self.volume_slider, self.volume_value_label), 0, wx.EXPAND)
        outer.Add(slider_row(self.rate_label, self.rate_slider, self.rate_value_label), 0, wx.EXPAND)
        outer.Add(slider_row(self.pan_label, self.pan_slider, self.pan_value_label), 0, wx.EXPAND)
        self.SetSizer(outer)

        self.on_play: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_previous: Optional[Callable[[], None]] = None
        self.on_next: Optional[Callable[[], None]] = None
        self.on_volume_changed: Optional[Callable[[int], None]] = None
        self.on_rate_changed: Optional[Callable[[float], None]] = None
        self.on_pan_changed: Optional[Callable[[int], None]] = None

        self.prev_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_previous and self.on_previous())
        self.play_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_play and self.on_play())
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_stop and self.on_stop())
        self.next_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_next and self.on_next())
        self.volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_slider)
        self.rate_slider.Bind(wx.EVT_SLIDER, self._on_rate_slider)
        self.pan_slider.Bind(wx.EVT_SLIDER, self._on_pan_slider)

    def _on_volume_slider(self, event: wx.Event) -> None:
        value = self.volume_slider.GetValue()
        self.volume_value_label.SetLabel(f"{value}%")
        if self.on_volume_changed:
            self.on_volume_changed(value)

    def _on_rate_slider(self, event: wx.Event) -> None:
        rate = self.rate_slider.GetValue() / 100.0
        self.rate_value_label.SetLabel(f"{rate:.2f}x")
        if self.on_rate_changed:
            self.on_rate_changed(rate)

    def _on_pan_slider(self, event: wx.Event) -> None:
        value = self.pan_slider.GetValue()
        self.pan_value_label.SetLabel(f"{value}%")
        if self.on_pan_changed:
            self.on_pan_changed(value)

    def set_playing(self, is_playing: bool) -> None:
        self.play_btn.SetLabel("⏸ Pause" if is_playing else "▶ Play")

    def set_volume(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.volume_slider.SetValue(percent)
        self.volume_value_label.SetLabel(f"{percent}%")

    def set_rate(self, rate: float) -> None:
        rate = max(0.5, min(3.0, rate))
        self.rate_slider.SetValue(int(round(rate * 100)))
        self.rate_value_label.SetLabel(f"{rate:.2f}x")

    def set_pan(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        self.pan_slider.SetValue(percent)
        self.pan_value_label.SetLabel(f"{percent}%")

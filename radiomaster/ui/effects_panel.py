"""Shared building blocks for effect parameter editing.

`ParamPanel` dynamically renders one control per DSP `Param` for a given
effect spec. It's used by `EffectPage` (see effects_dialog.py), which hosts
one full per-effect settings page -- preset CRUD + live-previewed
parameters -- inside the Effects menu's "<Effect> Settings..." notebook
dialog. This used to be a single "Effects" tab (an effect-picker list next
to one shared parameter panel); it's now reached via the menu bar instead,
with one notebook page built per effect up front."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ..core.effects import Param
from ..utils.accessibility import accessible_label


def _slider_scale(step: float) -> int:
    """Ticks-per-unit for representing a float Param on an integer wx.Slider."""
    step = step or 1
    return max(round(1 / step), 1)


def _decimals_for_step(step: float) -> int:
    text = repr(float(step or 1))
    if "." not in text:
        return 0
    return len(text.split(".")[1].rstrip("0"))


def _format_value(value: float, decimals: int, unit: str) -> str:
    text = f"{value:.{decimals}f}"
    return f"{text} {unit}" if unit else text


class ParamPanel(wx.Panel):
    """Dynamically builds one control per Param for a given effect spec."""

    def __init__(self, parent):
        super().__init__(parent)
        self.sizer = wx.FlexGridSizer(0, 2, 6, 10)
        self.sizer.AddGrowableCol(1, 1)
        self.SetSizer(self.sizer)
        self._controls: dict[str, wx.Window] = {}
        # (kind, scale) per param key, needed to convert a slider's integer
        # position back to the real int/float value in get_values().
        self._meta: dict[str, tuple[str, int]] = {}

    def build(self, params: list[Param], values: dict, on_change: Optional[Callable[[], None]] = None) -> None:
        self.sizer.Clear(delete_windows=True)
        self._controls.clear()
        self._meta.clear()

        for param in params:
            unit_suffix = f" ({param.unit})" if param.unit else ""
            accessible_name = f"{param.label}{unit_suffix}"
            # wx.SpinCtrl/wx.SpinCtrlDouble render as composite controls on
            # Windows (an outer Pane wrapping an inner Edit + Spinner), and
            # screen readers focus/announce the inner Edit — which stays
            # unnamed no matter what accessible name is set on the composite
            # (verified: NVDA never spoke it). A plain wx.Slider is a single
            # native control, so accessible_label()'s preceding-sibling
            # convention reaches it directly and NVDA announces it correctly.
            label = wx.StaticText(self, label=f"{accessible_name}:")
            value = values.get(param.key, param.default)

            if param.kind == "choice":
                ctrl = wx.Choice(self, choices=list(param.choices))
                if value in param.choices:
                    ctrl.SetSelection(list(param.choices).index(value))
                elif param.choices:
                    ctrl.SetSelection(0)
                if on_change:
                    ctrl.Bind(wx.EVT_CHOICE, lambda e: on_change())
                self._controls[param.key] = ctrl
                self.sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
                self.sizer.Add(ctrl, 1, wx.EXPAND)
                continue

            scale = 1 if param.kind == "int" else _slider_scale(param.step)
            decimals = 0 if param.kind == "int" else _decimals_for_step(param.step)
            slider_min = round(param.min * scale)
            slider_max = round(param.max * scale)
            slider_val = min(max(round(float(value) * scale), slider_min), slider_max)

            accessible_label(self, accessible_name)
            ctrl = wx.Slider(self, value=slider_val, minValue=slider_min, maxValue=slider_max,
                              style=wx.SL_HORIZONTAL)
            ctrl.SetLineSize(max(1, round(param.step * scale)))
            value_label = wx.StaticText(self, label=_format_value(slider_val / scale, decimals, param.unit))

            def _on_slide(event: wx.Event, ctrl=ctrl, value_label=value_label,
                          scale=scale, decimals=decimals, unit=param.unit) -> None:
                value_label.SetLabel(_format_value(ctrl.GetValue() / scale, decimals, unit))
                if on_change:
                    on_change()

            ctrl.Bind(wx.EVT_SLIDER, _on_slide)

            self._controls[param.key] = ctrl
            self._meta[param.key] = (param.kind, scale)

            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(ctrl, 1, wx.EXPAND | wx.RIGHT, 6)
            row.Add(value_label, 0, wx.ALIGN_CENTER_VERTICAL)
            self.sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            self.sizer.Add(row, 1, wx.EXPAND)

        self.Layout()
        parent_sizer = self.GetContainingSizer()
        if parent_sizer:
            self.GetParent().Layout()

    def get_values(self) -> dict:
        values = {}
        for key, ctrl in self._controls.items():
            if isinstance(ctrl, wx.Choice):
                idx = ctrl.GetSelection()
                values[key] = ctrl.GetString(idx) if idx != wx.NOT_FOUND else ""
            elif isinstance(ctrl, wx.Slider):
                kind, scale = self._meta[key]
                raw = ctrl.GetValue() / scale
                values[key] = int(raw) if kind == "int" else raw
        return values




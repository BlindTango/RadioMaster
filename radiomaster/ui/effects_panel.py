"""Effects page: full CRUD over presets for each effect, exposing every DSP parameter."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ..core.effects import DISPLAY_ORDER, EFFECT_SPECS, Param
from ..core.effects_store import (
    EffectsPresetStore, EffectsStateStore, build_active_effect_chain, build_preview_effect_chain,
)
from ..core.player import Player
from ..utils.accessibility import accessible_label


class ParamPanel(wx.Panel):
    """Dynamically builds one control per Param for a given effect spec."""

    def __init__(self, parent):
        super().__init__(parent)
        self.sizer = wx.FlexGridSizer(0, 2, 6, 10)
        self.sizer.AddGrowableCol(1, 1)
        self.SetSizer(self.sizer)
        self._controls: dict[str, wx.Window] = {}

    def build(self, params: list[Param], values: dict, on_change: Optional[Callable[[], None]] = None) -> None:
        self.sizer.Clear(delete_windows=True)
        self._controls.clear()

        for param in params:
            unit_suffix = f" ({param.unit})" if param.unit else ""
            accessible_name = f"{param.label}{unit_suffix}"
            # This wx.StaticText, immediately preceding ctrl in the same
            # sizer, gives ctrl its accessible name via Windows' native
            # "adjacent static labels its sibling" convention for SIMPLE
            # controls (wx.Choice, wx.ListBox). It does NOT work for
            # wx.SpinCtrl/wx.SpinCtrlDouble: those are composite controls
            # (an outer Pane wrapping an inner Edit + Spinner sub-window),
            # so the true adjacent sibling in Z-order is not this label and
            # screen readers announce nothing. For those we additionally
            # call ctrl.SetLabel() below, which sets the composite control's
            # accessible Name directly without touching its displayed value
            # (verified empirically: no crash, unlike wx.Accessible
            # subclassing — see utils/accessibility.py — and unlike
            # SetLabel() on a plain wx.TextCtrl, which asserts).
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
            elif param.kind == "int":
                ctrl = wx.SpinCtrl(self, min=int(param.min), max=int(param.max), initial=int(value))
                ctrl.SetLabel(accessible_name)
                if on_change:
                    ctrl.Bind(wx.EVT_SPINCTRL, lambda e: on_change())
                    ctrl.Bind(wx.EVT_TEXT, lambda e: on_change())
            else:  # float
                ctrl = wx.SpinCtrlDouble(
                    self, min=param.min, max=param.max, initial=float(value),
                    inc=param.step or 0.1,
                )
                ctrl.SetDigits(3)
                ctrl.SetLabel(accessible_name)
                if on_change:
                    ctrl.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e: on_change())
                    ctrl.Bind(wx.EVT_TEXT, lambda e: on_change())

            self._controls[param.key] = ctrl
            self.sizer.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            self.sizer.Add(ctrl, 1, wx.EXPAND)

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
            elif isinstance(ctrl, wx.SpinCtrlDouble):
                values[key] = ctrl.GetValue()
            elif isinstance(ctrl, wx.SpinCtrl):
                values[key] = ctrl.GetValue()
        return values


class EffectsPanel(wx.Panel):
    # How long to wait after the user stops dragging/typing a parameter
    # before previewing it. The DSP chain applies changes instantly with no
    # decode restart, so this is just a UI nicety now (avoids recomputing
    # filter coefficients on every single slider tick/keystroke) rather than
    # working around an audible ffmpeg-restart glitch.
    _PREVIEW_DEBOUNCE_MS = 400

    def __init__(self, parent, preset_store: EffectsPresetStore, state_store: EffectsStateStore,
                 player: Player, on_presets_changed: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.preset_store = preset_store
        self.state_store = state_store
        self.player = player
        self.on_presets_changed = on_presets_changed
        self._previewing = False

        accessible_label(self, "Effect")
        self.effect_list = wx.ListBox(self, choices=[EFFECT_SPECS[e].display_name for e in DISPLAY_ORDER])
        self.effect_list.SetSelection(0)

        accessible_label(self, "Preset")
        self.preset_choice = wx.Choice(self)

        self.new_btn = wx.Button(self, label="&New...")
        self.rename_btn = wx.Button(self, label="&Rename...")
        self.delete_btn = wx.Button(self, label="&Delete")
        self.save_btn = wx.Button(self, label="&Save Changes")

        self.note_label = wx.StaticText(self, label="")
        self.note_label.Wrap(400)

        self.param_panel = ParamPanel(self)

        self._preview_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_preview_timer, self._preview_timer)

        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        preset_row.Add(wx.StaticText(self, label="&Preset:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        preset_row.Add(self.preset_choice, 1, wx.EXPAND | wx.RIGHT, 6)
        preset_row.Add(self.new_btn, 0, wx.RIGHT, 4)
        preset_row.Add(self.rename_btn, 0, wx.RIGHT, 4)
        preset_row.Add(self.delete_btn, 0)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(preset_row, 0, wx.EXPAND | wx.ALL, 6)
        right.Add(self.note_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        right.Add(self.param_panel, 1, wx.EXPAND | wx.ALL, 10)
        right.Add(self.save_btn, 0, wx.ALL, 10)

        outer = wx.BoxSizer(wx.HORIZONTAL)
        outer.Add(self.effect_list, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(right, 1, wx.EXPAND)
        self.SetSizer(outer)

        self.effect_list.Bind(wx.EVT_LISTBOX, lambda e: self._load_effect())
        self.preset_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_preset())
        self.new_btn.Bind(wx.EVT_BUTTON, self._on_new)
        self.rename_btn.Bind(wx.EVT_BUTTON, self._on_rename)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self._load_effect()

    def _current_effect_id(self) -> str:
        return DISPLAY_ORDER[self.effect_list.GetSelection()]

    def _load_effect(self) -> None:
        effect_id = self._current_effect_id()
        spec = EFFECT_SPECS[effect_id]
        self.note_label.SetLabel(
            f"{spec.note} Adjust the parameters below to hear them live against "
            f"the current stream before saving.")

        names = self.preset_store.preset_names(effect_id)
        self.preset_choice.Clear()
        self.preset_choice.AppendItems(names)
        if names:
            self.preset_choice.SetSelection(0)
        self._load_preset()

    def _load_preset(self) -> None:
        effect_id = self._current_effect_id()
        spec = EFFECT_SPECS[effect_id]
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            self.param_panel.build(spec.params, spec.default_params(), on_change=self._on_param_changed)
        else:
            name = self.preset_choice.GetString(idx)
            values = self.preset_store.get_preset(effect_id, name) or spec.default_params()
            self.param_panel.build(spec.params, values, on_change=self._on_param_changed)
        # Preview the newly-loaded effect/preset immediately (not just on the
        # next edit) so switching the effect list or preset choice is itself
        # audible right away.
        self._apply_preview_now()

    # ---- live preview --------------------------------------------------------

    def _on_param_changed(self) -> None:
        # Restart (rather than just start) the one-shot timer so a burst of
        # changes (dragging a slider, typing a number) only actually applies
        # once things settle for _PREVIEW_DEBOUNCE_MS.
        self._preview_timer.Start(self._PREVIEW_DEBOUNCE_MS, wx.TIMER_ONE_SHOT)

    def _on_preview_timer(self, event: wx.TimerEvent) -> None:
        self._apply_preview_now()

    def _apply_preview_now(self) -> None:
        effect_id = self._current_effect_id()
        params = self.param_panel.get_values()
        if not params:
            return
        stages = build_preview_effect_chain(self.preset_store, self.state_store, effect_id, params)
        self._previewing = True
        self.player.apply_effects(stages)

    def stop_preview(self) -> None:
        """Restores playback to the real, saved, enabled-effects chain.
        Called when navigating away from this page so an unsaved preview
        tweak doesn't silently keep affecting playback afterwards."""
        self._preview_timer.Stop()
        if not self._previewing:
            return
        self._previewing = False
        self.player.apply_effects(build_active_effect_chain(self.preset_store, self.state_store))

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self.stop_preview()
        event.Skip()

    def _on_new(self, event: wx.CommandEvent) -> None:
        effect_id = self._current_effect_id()
        dlg = wx.TextEntryDialog(self, "New preset name:", "New Preset")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                params = self.param_panel.get_values() or EFFECT_SPECS[effect_id].default_params()
                try:
                    self.preset_store.save_preset(effect_id, name, params)
                except ValueError as exc:
                    wx.MessageBox(str(exc), "Cannot Save Preset", wx.OK | wx.ICON_ERROR)
                else:
                    self._load_effect()
                    self._select_preset_by_name(name)
                    self._notify_changed()
        dlg.Destroy()

    def _on_rename(self, event: wx.CommandEvent) -> None:
        effect_id = self._current_effect_id()
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        old_name = self.preset_choice.GetString(idx)
        dlg = wx.TextEntryDialog(self, "Rename preset to:", "Rename Preset", value=old_name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != old_name:
                try:
                    self.preset_store.rename_preset(effect_id, old_name, new_name)
                except (ValueError, KeyError) as exc:
                    wx.MessageBox(str(exc), "Cannot Rename Preset", wx.OK | wx.ICON_ERROR)
                else:
                    self._load_effect()
                    self._select_preset_by_name(new_name)
                    self._notify_changed()
        dlg.Destroy()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        effect_id = self._current_effect_id()
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self.preset_choice.GetString(idx)
        if wx.MessageBox(f"Delete preset '{name}'?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        try:
            self.preset_store.delete_preset(effect_id, name)
        except ValueError as exc:
            wx.MessageBox(str(exc), "Cannot Delete Preset", wx.OK | wx.ICON_ERROR)
        else:
            self._load_effect()
            self._notify_changed()

    def _on_save(self, event: wx.CommandEvent) -> None:
        effect_id = self._current_effect_id()
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Create a preset first.", "No Preset Selected", wx.OK | wx.ICON_INFORMATION)
            return
        name = self.preset_choice.GetString(idx)
        self.preset_store.save_preset(effect_id, name, self.param_panel.get_values())
        wx.MessageBox(f"Saved '{name}'.", "Preset Saved", wx.OK | wx.ICON_INFORMATION)
        self._notify_changed()

    def _select_preset_by_name(self, name: str) -> None:
        for i in range(self.preset_choice.GetCount()):
            if self.preset_choice.GetString(i) == name:
                self.preset_choice.SetSelection(i)
                self._load_preset()
                return

    def _notify_changed(self) -> None:
        if self.on_presets_changed:
            self.on_presets_changed()

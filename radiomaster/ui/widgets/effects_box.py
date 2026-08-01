"""Enable checkbox + preset combobox for each of the 8 audio effects."""

from __future__ import annotations

from typing import Callable

import wx

from ...core.effects import DISPLAY_ORDER, EFFECT_SPECS
from ...core.effects_store import EffectsPresetStore, EffectsStateStore, build_active_filter_chain
from ...utils.accessibility import accessible_label


class EffectsBox(wx.StaticBoxSizer):
    """A StaticBoxSizer of CheckBox+Choice rows, one per effect, inside `parent`."""

    def __init__(self, parent: wx.Window, preset_store: EffectsPresetStore,
                 state_store: EffectsStateStore, on_chain_changed: Callable[[str], None]):
        self.box = wx.StaticBox(parent, label="Audio Effects")
        super().__init__(self.box, wx.VERTICAL)
        self.preset_store = preset_store
        self.state_store = state_store
        self.on_chain_changed = on_chain_changed

        self.checkboxes: dict[str, wx.CheckBox] = {}
        self.combos: dict[str, wx.Choice] = {}

        grid = wx.FlexGridSizer(len(DISPLAY_ORDER), 2, 4, 8)
        grid.AddGrowableCol(1, 1)

        for effect_id in DISPLAY_ORDER:
            spec = EFFECT_SPECS[effect_id]
            check = wx.CheckBox(self.box, label=spec.display_name)
            check.SetValue(state_store.is_enabled(effect_id))
            check.Bind(wx.EVT_CHECKBOX, lambda e, eid=effect_id: self._on_toggle(eid))

            accessible_label(self.box, f"{spec.display_name} preset")
            combo = wx.Choice(self.box)
            self._refresh_presets(effect_id, combo)
            combo.Bind(wx.EVT_CHOICE, lambda e, eid=effect_id: self._on_preset_selected(eid))

            self.checkboxes[effect_id] = check
            self.combos[effect_id] = combo
            grid.Add(check, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(combo, 1, wx.EXPAND)

        self.Add(grid, 0, wx.EXPAND | wx.ALL, 4)

    def _refresh_presets(self, effect_id: str, combo: wx.Choice) -> None:
        names = self.preset_store.preset_names(effect_id)
        current = self.state_store.selected_preset(effect_id)
        combo.Clear()
        combo.AppendItems(names)
        if current in names:
            combo.SetSelection(names.index(current))
        elif names:
            combo.SetSelection(0)
            self.state_store.set_selected_preset(effect_id, names[0])

    def refresh_all_presets(self) -> None:
        """Call after presets are edited/added/removed elsewhere (the Effects settings page)."""
        for effect_id, combo in self.combos.items():
            self._refresh_presets(effect_id, combo)

    def _on_toggle(self, effect_id: str) -> None:
        self.state_store.set_enabled(effect_id, self.checkboxes[effect_id].GetValue())
        self._apply()

    def _on_preset_selected(self, effect_id: str) -> None:
        combo = self.combos[effect_id]
        idx = combo.GetSelection()
        if idx != wx.NOT_FOUND:
            self.state_store.set_selected_preset(effect_id, combo.GetString(idx))
            self._apply()

    def _apply(self) -> None:
        chain = build_active_filter_chain(self.preset_store, self.state_store)
        self.on_chain_changed(chain)

"""Effects Settings dialog: a notebook with one full preset-editing page per
effect, opened from the "<Effect> Settings..." item at the bottom of each
effect's Effects-menu submenu (see MainFrame._open_effects_settings). This
replaces the old single "Effects" tab, which showed one shared parameter
panel next to an effect-picker list -- here every effect gets its own
always-built page instead, matching how the Effects menu already lists
every effect up front."""

from __future__ import annotations

from typing import Callable, Optional

import wx

from ..core.effects import DISPLAY_ORDER, EFFECT_SPECS
from ..core.effects_store import (
    EffectsPresetStore, EffectsStateStore, build_active_effect_chain, build_preview_effect_chain,
)
from ..core.player import Player
from ..utils.accessibility import accessible_label
from .effects_panel import ParamPanel


class EffectPage(wx.Panel):
    """One effect's full preset CRUD + live-previewed parameters, fixed to a
    single effect_id (no effect-picker -- the containing notebook's tabs
    are the picker)."""

    # See the old EffectsPanel's identical constant: a UI nicety now that
    # the DSP chain applies changes instantly with no decode restart.
    _PREVIEW_DEBOUNCE_MS = 400

    def __init__(self, parent, effect_id: str, preset_store: EffectsPresetStore,
                 state_store: EffectsStateStore, player: Player,
                 on_presets_changed: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.effect_id = effect_id
        self.spec = EFFECT_SPECS[effect_id]
        self.preset_store = preset_store
        self.state_store = state_store
        self.player = player
        self.on_presets_changed = on_presets_changed
        self._previewing = False

        self.note_label = wx.StaticText(self, label=self.spec.note)
        self.note_label.Wrap(520)

        accessible_label(self, "Preset")
        self.preset_choice = wx.Choice(self)

        self.new_btn = wx.Button(self, label="&New...")
        self.rename_btn = wx.Button(self, label="&Rename...")
        self.delete_btn = wx.Button(self, label="&Delete")
        self.save_btn = wx.Button(self, label="&Save Changes")

        self.param_panel = ParamPanel(self)

        self._preview_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_preview_timer, self._preview_timer)

        preset_row = wx.BoxSizer(wx.HORIZONTAL)
        preset_row.Add(wx.StaticText(self, label="&Preset:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        preset_row.Add(self.preset_choice, 1, wx.EXPAND | wx.RIGHT, 6)
        preset_row.Add(self.new_btn, 0, wx.RIGHT, 4)
        preset_row.Add(self.rename_btn, 0, wx.RIGHT, 4)
        preset_row.Add(self.delete_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.note_label, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(preset_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.param_panel, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.save_btn, 0, wx.ALL, 10)
        self.SetSizer(outer)

        self.preset_choice.Bind(wx.EVT_CHOICE, lambda e: self._load_preset())
        self.new_btn.Bind(wx.EVT_BUTTON, self._on_new)
        self.rename_btn.Bind(wx.EVT_BUTTON, self._on_rename)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.save_btn.Bind(wx.EVT_BUTTON, self._on_save)

        self._load_presets()

    def _load_presets(self) -> None:
        names = self.preset_store.preset_names(self.effect_id)
        current = self.state_store.selected_preset(self.effect_id)
        self.preset_choice.Clear()
        self.preset_choice.AppendItems(names)
        if current in names:
            self.preset_choice.SetSelection(names.index(current))
        elif names:
            self.preset_choice.SetSelection(0)
        self._load_preset()

    def _load_preset(self) -> None:
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            self.param_panel.build(self.spec.params, self.spec.default_params(), on_change=self._on_param_changed)
        else:
            name = self.preset_choice.GetString(idx)
            values = self.preset_store.get_preset(self.effect_id, name) or self.spec.default_params()
            self.param_panel.build(self.spec.params, values, on_change=self._on_param_changed)
        # Preview the newly-loaded preset immediately (not just on the next
        # edit) so switching the preset choice is itself audible right away.
        self._apply_preview_now()

    # ---- live preview --------------------------------------------------------

    def _on_param_changed(self) -> None:
        self._preview_timer.Start(self._PREVIEW_DEBOUNCE_MS, wx.TIMER_ONE_SHOT)

    def _on_preview_timer(self, event: wx.TimerEvent) -> None:
        self._apply_preview_now()

    def _apply_preview_now(self) -> None:
        params = self.param_panel.get_values()
        if not params:
            return
        stages = build_preview_effect_chain(self.preset_store, self.state_store, self.effect_id, params)
        self._previewing = True
        self.player.apply_effects(stages)

    def stop_preview(self) -> None:
        """Restores playback to the real, saved, enabled-effects chain.
        Called when the owning dialog closes so an unsaved preview tweak
        doesn't silently keep affecting playback afterwards."""
        self._preview_timer.Stop()
        if not self._previewing:
            return
        self._previewing = False
        self.player.apply_effects(build_active_effect_chain(self.preset_store, self.state_store))

    def _on_new(self, event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(self, "New preset name:", "New Preset")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                params = self.param_panel.get_values() or self.spec.default_params()
                try:
                    self.preset_store.save_preset(self.effect_id, name, params)
                except ValueError as exc:
                    wx.MessageBox(str(exc), "Cannot Save Preset", wx.OK | wx.ICON_ERROR)
                else:
                    self._load_presets()
                    self._select_preset_by_name(name)
                    self._notify_changed()
        dlg.Destroy()

    def _on_rename(self, event: wx.CommandEvent) -> None:
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        old_name = self.preset_choice.GetString(idx)
        dlg = wx.TextEntryDialog(self, "Rename preset to:", "Rename Preset", value=old_name)
        if dlg.ShowModal() == wx.ID_OK:
            new_name = dlg.GetValue().strip()
            if new_name and new_name != old_name:
                try:
                    self.preset_store.rename_preset(self.effect_id, old_name, new_name)
                except (ValueError, KeyError) as exc:
                    wx.MessageBox(str(exc), "Cannot Rename Preset", wx.OK | wx.ICON_ERROR)
                else:
                    self._load_presets()
                    self._select_preset_by_name(new_name)
                    self._notify_changed()
        dlg.Destroy()

    def _on_delete(self, event: wx.CommandEvent) -> None:
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        name = self.preset_choice.GetString(idx)
        if wx.MessageBox(f"Delete preset '{name}'?", "Confirm Delete", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        try:
            self.preset_store.delete_preset(self.effect_id, name)
        except ValueError as exc:
            wx.MessageBox(str(exc), "Cannot Delete Preset", wx.OK | wx.ICON_ERROR)
        else:
            self._load_presets()
            self._notify_changed()

    def _on_save(self, event: wx.CommandEvent) -> None:
        idx = self.preset_choice.GetSelection()
        if idx == wx.NOT_FOUND:
            wx.MessageBox("Create a preset first.", "No Preset Selected", wx.OK | wx.ICON_INFORMATION)
            return
        name = self.preset_choice.GetString(idx)
        self.preset_store.save_preset(self.effect_id, name, self.param_panel.get_values())
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


class EffectsSettingsDialog(wx.Dialog):
    """A wx.Notebook (never wx.Listbook -- see main_frame.py's module
    docstring for the crash history) with one EffectPage per effect."""

    def __init__(self, parent, preset_store: EffectsPresetStore, state_store: EffectsStateStore,
                 player: Player, on_presets_changed: Optional[Callable[[], None]] = None,
                 initial_effect_id: Optional[str] = None):
        super().__init__(parent, title="Effects Settings", size=(760, 620),
                          style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.pages: dict[str, EffectPage] = {}

        self.notebook = wx.Notebook(self)
        for effect_id in DISPLAY_ORDER:
            page = EffectPage(
                self.notebook, effect_id, preset_store, state_store, player,
                on_presets_changed=on_presets_changed,
            )
            self.notebook.AddPage(page, EFFECT_SPECS[effect_id].display_name)
            self.pages[effect_id] = page

        if initial_effect_id and initial_effect_id in self.pages:
            self.notebook.SetSelection(DISPLAY_ORDER.index(initial_effect_id))

        close_btn = wx.Button(self, wx.ID_CLOSE, "&Close")

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(outer)

        close_btn.Bind(wx.EVT_BUTTON, self._on_close_request)
        self.Bind(wx.EVT_CLOSE, self._on_close_request)
        # wx focuses the dialog's default button once ShowModal() starts,
        # overriding a plain SetFocus() called here in __init__ -- binding
        # EVT_INIT_DIALOG (fired after that default-button focusing) is what
        # reliably lands focus on the first real control instead.
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.notebook.SetFocus()

    def _on_close_request(self, event: wx.Event) -> None:
        for page in self.pages.values():
            page.stop_preview()
        self.EndModal(wx.ID_CLOSE)

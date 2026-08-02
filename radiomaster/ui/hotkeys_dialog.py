"""Settings dialog for customizing global hotkeys (Play/Pause, Stop, Record, Volume).

Each action can have several bindings (e.g. a Ctrl+Alt+letter combo AND a
multimedia key), managed as a flat add/edit/remove list rather than one fixed
text field per action.
"""

from __future__ import annotations

from typing import Optional

import wx

from ..core.hotkeys import (
    AVAILABLE_KEYS, MODIFIERS, build_hotkey_spec, parse_hotkey, split_hotkey_parts,
)
from ..utils.accessibility import accessible_label
from ..utils.config import Config

ACTIONS = [
    ("play_pause", "Play/Pause"),
    ("stop", "Stop"),
    ("record", "Record Selected Station"),
    ("volume_up", "Volume Up"),
    ("volume_down", "Volume Down"),
]
_ACTION_LABELS = {key: label for key, label in ACTIONS}


class HotkeyEditDialog(wx.Dialog):
    """Add/edit a single (action, key combination) binding."""

    def __init__(self, parent, existing_bindings: list[tuple[str, str]],
                 initial_action: Optional[str] = None, initial_spec: Optional[str] = None):
        title = "Edit Hotkey" if initial_spec else "Add Hotkey"
        super().__init__(parent, title=title, size=(360, 460))
        # (action_label, spec) for every OTHER row already in the list, used
        # to reject a combination that's already claimed by a different entry.
        self._existing_bindings = existing_bindings
        self.action_key: Optional[str] = None
        self.spec: Optional[str] = None

        feature_label = accessible_label(self, "Feature")
        self.action_choice = wx.Choice(self, choices=[label for _key, label in ACTIONS])
        initial_index = 0
        if initial_action:
            for i, (key, _label) in enumerate(ACTIONS):
                if key == initial_action:
                    initial_index = i
                    break
        self.action_choice.SetSelection(initial_index)

        mod_box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Modifiers")
        self.mod_checks: dict[str, wx.CheckBox] = {}
        initial_mods: dict[str, bool] = {}
        initial_key_token: Optional[str] = None
        if initial_spec:
            parts = split_hotkey_parts(initial_spec)
            if parts:
                initial_mods, initial_key_token = parts
        for name, label in MODIFIERS:
            check = wx.CheckBox(mod_box.GetStaticBox(), label=f"&{label}")
            check.SetValue(bool(initial_mods.get(name)))
            self.mod_checks[name] = check
            mod_box.Add(check, 0, wx.ALL, 4)

        key_label = accessible_label(self, "Key")
        self.key_listbox = wx.ListBox(self, choices=[label for _token, label in AVAILABLE_KEYS],
                                       size=(-1, 220))
        initial_key_index = 0
        if initial_key_token:
            for i, (token, _label) in enumerate(AVAILABLE_KEYS):
                if token == initial_key_token:
                    initial_key_index = i
                    break
        self.key_listbox.SetSelection(initial_key_index)

        note = wx.StaticText(
            self, label="Multimedia keys work with or without modifiers held down.")
        note.Wrap(320)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(feature_label, 0, wx.LEFT | wx.TOP, 10)
        outer.Add(self.action_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        outer.Add(mod_box, 0, wx.EXPAND | wx.ALL, 10)
        outer.Add(key_label, 0, wx.LEFT, 10)
        outer.Add(self.key_listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)

        self.FindWindowById(wx.ID_OK, self).Bind(wx.EVT_BUTTON, self._on_ok)

    def _on_ok(self, event: wx.CommandEvent) -> None:
        key_index = self.key_listbox.GetSelection()
        if key_index == wx.NOT_FOUND:
            wx.MessageBox("Choose a key for this hotkey.", "No Key Selected", wx.OK | wx.ICON_ERROR)
            return
        key_token = AVAILABLE_KEYS[key_index][0]
        mods = {name: check.GetValue() for name, check in self.mod_checks.items()}
        spec = build_hotkey_spec(mods, key_token)
        parsed = parse_hotkey(spec)
        if parsed is None:
            wx.MessageBox(f"'{spec}' is not a valid hotkey.", "Invalid Hotkey", wx.OK | wx.ICON_ERROR)
            return
        for other_label, other_spec in self._existing_bindings:
            if parse_hotkey(other_spec) == parsed:
                wx.MessageBox(f"'{spec}' is already assigned to {other_label}.",
                              "Hotkey Already In Use", wx.OK | wx.ICON_ERROR)
                return
        action_index = self.action_choice.GetSelection()
        self.action_key = ACTIONS[action_index][0]
        self.spec = spec
        event.Skip()


class HotkeysDialog(wx.Dialog):
    def __init__(self, parent, config: Config):
        super().__init__(parent, title="Global Hotkeys", size=(480, 420))
        self.config = config
        # Deep-copied so Cancel discards in-progress edits untouched.
        raw = config.get("hotkeys", {})
        self._hotkeys: dict[str, list[str]] = {action: list(specs) for action, specs in raw.items()}

        list_label = wx.StaticText(self, label="Configured hotkeys:")
        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list_ctrl.InsertColumn(0, "Feature", width=220)
        self.list_ctrl.InsertColumn(1, "Keystroke", width=180)
        self._rows: list[tuple[str, str]] = []  # (action_key, spec), parallel to list_ctrl rows

        self.add_btn = wx.Button(self, label="&Add...")
        self.edit_btn = wx.Button(self, label="&Edit...")
        self.remove_btn = wx.Button(self, label="&Remove")

        note = wx.StaticText(
            self,
            label="These work even when RadioMaster isn't the focused window. A feature can "
                  "have more than one hotkey (e.g. a letter combo and a multimedia key).",
        )
        note.Wrap(440)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        btn_col = wx.BoxSizer(wx.VERTICAL)
        for btn in (self.add_btn, self.edit_btn, self.remove_btn):
            btn_col.Add(btn, 0, wx.EXPAND | wx.BOTTOM, 6)

        list_row = wx.BoxSizer(wx.HORIZONTAL)
        list_row.Add(self.list_ctrl, 1, wx.EXPAND | wx.RIGHT, 10)
        list_row.Add(btn_col, 0, wx.EXPAND)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(list_label, 0, wx.LEFT | wx.TOP, 10)
        outer.Add(list_row, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)

        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._update_button_states)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._update_button_states)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_edit)
        self.FindWindowById(wx.ID_OK, self).Bind(wx.EVT_BUTTON, self._on_ok)

        self._refresh_list()
        self._update_button_states(None)

    def _refresh_list(self, select_row: Optional[int] = None) -> None:
        self._rows = [
            (action, spec) for action, specs in self._hotkeys.items() for spec in specs
        ]
        self.list_ctrl.DeleteAllItems()
        for row, (action, spec) in enumerate(self._rows):
            idx = self.list_ctrl.InsertItem(row, _ACTION_LABELS.get(action, action))
            self.list_ctrl.SetItem(idx, 1, spec)
        if select_row is not None and 0 <= select_row < len(self._rows):
            self.list_ctrl.Select(select_row)
        self._update_button_states(None)

    def _selected_row(self) -> Optional[int]:
        idx = self.list_ctrl.GetFirstSelected()
        return idx if idx != -1 else None

    def _update_button_states(self, event) -> None:
        has_selection = self._selected_row() is not None
        self.edit_btn.Enable(has_selection)
        self.remove_btn.Enable(has_selection)
        if event is not None:
            event.Skip()

    def _existing_bindings(self, exclude_row: Optional[int]) -> list[tuple[str, str]]:
        return [
            (_ACTION_LABELS.get(action, action), spec)
            for row, (action, spec) in enumerate(self._rows) if row != exclude_row
        ]

    def _on_add(self, event: wx.CommandEvent) -> None:
        dlg = HotkeyEditDialog(self, self._existing_bindings(None))
        if dlg.ShowModal() == wx.ID_OK and dlg.action_key and dlg.spec:
            self._hotkeys.setdefault(dlg.action_key, []).append(dlg.spec)
            self._refresh_list(select_row=len(self._rows))
        dlg.Destroy()

    def _on_edit(self, event) -> None:
        row = self._selected_row()
        if row is None:
            return
        action, spec = self._rows[row]
        dlg = HotkeyEditDialog(self, self._existing_bindings(row), initial_action=action, initial_spec=spec)
        if dlg.ShowModal() == wx.ID_OK and dlg.action_key and dlg.spec:
            self._hotkeys[action].remove(spec)
            self._hotkeys.setdefault(dlg.action_key, []).append(dlg.spec)
            self._refresh_list()
        dlg.Destroy()

    def _on_remove(self, event: wx.CommandEvent) -> None:
        row = self._selected_row()
        if row is None:
            return
        action, spec = self._rows[row]
        self._hotkeys[action].remove(spec)
        self._refresh_list()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        self.config.set("hotkeys", self._hotkeys)
        event.Skip()


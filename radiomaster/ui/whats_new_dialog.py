"""Help > What's New / Release Notes — the changelog, browsable by version."""

from __future__ import annotations

import wx

from ..core.changelog import CHANGELOG, VERSIONS_NEWEST_FIRST


class WhatsNewDialog(wx.Dialog):
    def __init__(self, parent, current_version: str):
        super().__init__(parent, title="RadioMaster - What's New",
                          size=(640, 460), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self._versions = [v for v in VERSIONS_NEWEST_FIRST if v in CHANGELOG]

        versions_label = wx.StaticText(self, label="&Versions:")
        self.version_list = wx.ListBox(self, choices=[f"v{v}" for v in self._versions])

        content_label = wx.StaticText(self, label="Changes:")
        self.content = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
        )

        close_btn = wx.Button(self, wx.ID_OK, label="&Close")

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(versions_label, 0, wx.BOTTOM, 4)
        left.Add(self.version_list, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(content_label, 0, wx.BOTTOM, 4)
        right.Add(self.content, 1, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 0, wx.EXPAND | wx.ALL, 10)
        body.Add(right, 1, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 10)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(body, 1, wx.EXPAND)
        outer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.version_list.Bind(wx.EVT_LISTBOX, self._on_version_selected)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

        initial_index = self._versions.index(current_version) if current_version in self._versions else 0
        if self._versions:
            self.version_list.SetSelection(initial_index)
            self._show_version(initial_index)
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.version_list.SetFocus()

    def _on_version_selected(self, event: wx.CommandEvent) -> None:
        self._show_version(self.version_list.GetSelection())

    def _show_version(self, index: int) -> None:
        if 0 <= index < len(self._versions):
            version = self._versions[index]
            title = f"Version {version}"
            body = "\n".join(f"- {line}" for line in CHANGELOG.get(version, []))
            self.content.ChangeValue(f"{title}\n{'=' * len(title)}\n\n{body}")

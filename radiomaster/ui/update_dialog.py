"""Help > Check for Updates result dialog — shows release notes and offers to download/install."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import webbrowser
from typing import Callable, Optional

import wx

from ..core.updater import UpdateCheckError, UpdateChecker, UpdateInfo
from ..utils.wx_safe import call_after_safe

log = logging.getLogger(__name__)


class UpdateAvailableDialog(wx.Dialog):
    """Result codes: wx.ID_OK (install launched), wx.ID_NO (user chose to
    skip this version), wx.ID_CANCEL (remind later / closed)."""

    def __init__(self, parent, checker: UpdateChecker, info: UpdateInfo,
                 on_ready_to_install: Callable[[str], None]):
        super().__init__(parent, title="Update Available",
                          size=(560, 420), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.checker = checker
        self.info = info
        self.on_ready_to_install = on_ready_to_install
        self._cancelled = False
        self._download_thread: Optional[threading.Thread] = None

        heading = wx.StaticText(self, label=f"RadioMaster {info.version} is available")
        heading_font = wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        heading.SetFont(heading_font)

        notes_label = wx.StaticText(self, label="&Release notes:")
        self.notes = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
            value=info.notes or "(No release notes provided.)",
        )

        self.progress_label = wx.StaticText(self, label="")
        self.progress_gauge = wx.Gauge(self, wx.ID_ANY, 100)
        self.progress_gauge.Hide()

        self.download_btn = wx.Button(self, label="&Download && Install")
        self.download_btn.Enable(bool(info.download_url))
        view_btn = wx.Button(self, label="&View on GitHub")
        skip_btn = wx.Button(self, label="&Skip This Version")
        later_btn = wx.Button(self, wx.ID_CANCEL, label="Remind Me &Later")

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(heading, 0, wx.ALL, 12)
        outer.Add(notes_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.notes, 1, wx.EXPAND | wx.ALL, 12)
        outer.Add(self.progress_label, 0, wx.LEFT | wx.RIGHT, 12)
        outer.Add(self.progress_gauge, 0, wx.EXPAND | wx.ALL, 12)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self.download_btn, 0, wx.RIGHT, 6)
        btn_row.Add(view_btn, 0, wx.RIGHT, 6)
        btn_row.Add(skip_btn, 0, wx.RIGHT, 6)
        btn_row.Add(later_btn, 0)
        outer.Add(btn_row, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)
        self.SetSizer(outer)

        self.download_btn.Bind(wx.EVT_BUTTON, self._on_download)
        view_btn.Bind(wx.EVT_BUTTON, self._on_view_github)
        skip_btn.Bind(wx.EVT_BUTTON, self._on_skip)
        later_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.download_btn.SetFocus()

    def _on_view_github(self, event: wx.CommandEvent) -> None:
        webbrowser.open(self.info.html_url)

    def _on_skip(self, event: wx.CommandEvent) -> None:
        self._cancelled = True
        self.EndModal(wx.ID_NO)

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._cancelled = True
        self.EndModal(wx.ID_CANCEL)

    def _on_download(self, event: wx.CommandEvent) -> None:
        self.download_btn.Enable(False)
        self.progress_gauge.Show()
        self.progress_label.SetLabel("Starting download...")
        self.Layout()

        dest_path = os.path.join(tempfile.gettempdir(), self.info.asset_name or "RadioMaster-Setup.exe")

        def progress_cb(downloaded: int, total: int) -> None:
            call_after_safe(self, self._update_progress, downloaded, total)

        def worker():
            try:
                self.checker.download_installer(
                    self.info, dest_path, progress_cb=progress_cb,
                    cancel_check=lambda: self._cancelled,
                )
            except UpdateCheckError as exc:
                call_after_safe(self, self._download_failed, str(exc))
                return
            call_after_safe(self, self._download_complete, dest_path)

        self._download_thread = threading.Thread(target=worker, daemon=True)
        self._download_thread.start()

    def _update_progress(self, downloaded: int, total: int) -> None:
        if total:
            pct = int(downloaded * 100 / total)
            self.progress_gauge.SetValue(pct)
            self.progress_label.SetLabel(f"Downloading... {downloaded // 1024} KB of {total // 1024} KB ({pct}%)")
        else:
            self.progress_gauge.Pulse()
            self.progress_label.SetLabel(f"Downloading... {downloaded // 1024} KB")

    def _download_failed(self, message: str) -> None:
        self.progress_label.SetLabel("")
        self.progress_gauge.Hide()
        self.download_btn.Enable(True)
        self.Layout()
        wx.MessageBox(message, "Update Download Failed", wx.OK | wx.ICON_ERROR, self)

    def _download_complete(self, installer_path: str) -> None:
        self.progress_label.SetLabel("Download complete.")
        choice = wx.MessageBox(
            "The update has been downloaded. RadioMaster will now close and the "
            "installer will open — follow its prompts to finish updating.",
            "Ready to Install", wx.OK | wx.CANCEL | wx.ICON_INFORMATION, self,
        )
        if choice == wx.OK:
            self.on_ready_to_install(installer_path)
            self.EndModal(wx.ID_OK)
        else:
            self.download_btn.Enable(True)
            self.progress_gauge.Hide()
            self.progress_label.SetLabel("")
            self.Layout()

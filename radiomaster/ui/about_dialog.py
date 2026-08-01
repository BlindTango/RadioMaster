"""Help > About dialog."""

from __future__ import annotations

import wx

from .. import __app_name__, __copyright__, __version__
from ..utils.accessibility import accessible_label


class AboutDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=f"About {__app_name__}", size=(420, 260))

        title = wx.StaticText(self, label=__app_name__)
        title_font = wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)

        version_label = wx.StaticText(self, label=f"Version {__version__}")
        tagline = wx.StaticText(self, label="Accessible Portable Internet Radio Player")
        copyright_label = wx.StaticText(self, label=__copyright__)

        accessible_label(self, "About RadioMaster description")
        info_text = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
            value=(
                "RadioMaster streams stations from the Radio Browser database, "
                "records tracks with automatic ad-skipping and metadata tagging, "
                "and supports real-time audio effects — built for full screen-reader "
                "accessibility from the ground up."
            ),
        )

        close_btn = wx.Button(self, wx.ID_OK, label="&Close")

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(title, 0, wx.ALIGN_CENTER | wx.TOP, 16)
        outer.Add(version_label, 0, wx.ALIGN_CENTER | wx.TOP, 4)
        outer.Add(tagline, 0, wx.ALIGN_CENTER | wx.TOP, 4)
        outer.Add(info_text, 1, wx.EXPAND | wx.ALL, 12)
        outer.Add(copyright_label, 0, wx.ALIGN_CENTER | wx.BOTTOM, 4)
        outer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)
        self.SetSizer(outer)

        close_btn.SetFocus()
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

"""wx.App subclass for RadioMaster."""

from __future__ import annotations

import logging

import wx

from .ui.main_frame import MainFrame
from .ui.splash import show_splash
from .utils.config import get_config
from .utils.logging_setup import setup_logging

log = logging.getLogger(__name__)


class RadioMasterApp(wx.App):
    def OnInit(self) -> bool:
        setup_logging(get_config().get("log_level", "info"))
        log.info("RadioMaster starting")
        self.splash = show_splash()
        wx.Yield()
        self.frame = MainFrame()
        self.frame.Show()
        self.SetTopWindow(self.frame)
        return True

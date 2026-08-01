"""Startup splash screen — drawn at runtime, no bundled image asset needed."""

from __future__ import annotations

import wx
import wx.adv

from .. import __app_name__, __copyright__, __version__

SPLASH_SIZE = (420, 260)
SPLASH_MS = 1600


def _build_bitmap() -> wx.Bitmap:
    bitmap = wx.Bitmap(*SPLASH_SIZE)
    dc = wx.MemoryDC(bitmap)
    dc.SetBackground(wx.Brush(wx.Colour(24, 28, 38)))
    dc.Clear()

    dc.SetTextForeground(wx.Colour(255, 255, 255))
    title_font = wx.Font(28, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
    dc.SetFont(title_font)
    title = __app_name__
    tw, th = dc.GetTextExtent(title)
    dc.DrawText(title, (SPLASH_SIZE[0] - tw) // 2, 90)

    dc.SetTextForeground(wx.Colour(180, 190, 210))
    sub_font = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    dc.SetFont(sub_font)
    subtitle = "Accessible Portable Internet Radio Player"
    sw, sh = dc.GetTextExtent(subtitle)
    dc.DrawText(subtitle, (SPLASH_SIZE[0] - sw) // 2, 135)

    version_text = f"v{__version__}"
    vw, vh = dc.GetTextExtent(version_text)
    dc.DrawText(version_text, (SPLASH_SIZE[0] - vw) // 2, SPLASH_SIZE[1] - vh - 34)

    copy_font = wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    dc.SetFont(copy_font)
    dc.SetTextForeground(wx.Colour(130, 140, 160))
    cw, ch = dc.GetTextExtent(__copyright__)
    dc.DrawText(__copyright__, (SPLASH_SIZE[0] - cw) // 2, SPLASH_SIZE[1] - ch - 12)

    dc.SelectObject(wx.NullBitmap)
    return bitmap


def show_splash() -> wx.adv.SplashScreen:
    bitmap = _build_bitmap()
    return wx.adv.SplashScreen(
        bitmap,
        wx.adv.SPLASH_CENTRE_ON_SCREEN | wx.adv.SPLASH_TIMEOUT,
        SPLASH_MS, None,
        style=wx.BORDER_SIMPLE | wx.FRAME_NO_TASKBAR,
    )

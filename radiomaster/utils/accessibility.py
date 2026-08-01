"""Screen-reader-safe accessible naming for wx controls.

HISTORY / WHY THIS FILE LOOKS THE WAY IT DOES:

wx.Window.SetName() only sets the internal FindWindowByName identifier; it is
NOT exposed to UIA/MSAA, so NVDA/Narrator announce nothing (verified with the
uiautomation package: a SpinCtrl's Name stayed empty after SetName()).
wx.Window.SetLabel() does set the accessible Name for some control types, but
overwrites the visible VALUE/text for others (wx.CheckBox — verified; raises
a hard assertion on wx.TextCtrl in this wx version), and does nothing at all
for list/choice-style container controls (wx.ListBox, wx.Choice, wx.ListCtrl
— verified: their UIA Name stayed empty after SetLabel()).

An earlier version of this module used a custom wx.Accessible subclass
(overriding GetName()) to work around that, kept alive in a module-level
list so Python's GC couldn't collect it out from under a live COM reference
(Windows' UIA-to-MSAA bridge probes every top-level window's accessible tree
in the background, independent of whether a screen reader is running).

That mechanism turned out to be fundamentally broken: ANY Python subclass of
wx.Accessible — even one that only overrides GetName() and touches nothing
else — crashes the process with "Windows fatal exception: access violation"
as soon as UIA queries GetFocus() on it (its argument count/return-type
contract doesn't match what this wxPython build actually calls it with;
overriding GetFocus() directly with several different signatures/return
values still crashed, just with different symptoms). Reproduced down to a
15-line wx.Frame, on both wxWidgets 3.2.7 and 3.3.3 — so it's not a version
regression, it's inherent to subclassing wx.Accessible in Python at all in
this environment. Disabling it entirely (no-op) eliminated the crash in 5/5
repeated runs of a scenario that reproduced it ~80-100% of the time before.

THE FIX: Windows' native MSAA/UIA bridge has a long-standing convention for
plain win32 dialogs, with no custom accessibility code required at all — if
a wx.StaticText is the *immediately preceding sibling* of a control (same
parent, created right before it, in the same position in the sizer), that
control's accessible Name is taken from the static text automatically.
Verified directly: a zero-size (invisible, still Shown) wx.StaticText placed
right before a wx.ListBox/wx.Choice makes uiautomation report the exact
label text as that control's Name, with no visual change and no crash across
repeated Tab-focus stress tests. accessible_label() below wraps that pattern.

CAVEAT — wx.SpinCtrl / wx.SpinCtrlDouble: these render on Windows as a
composite control (an outer Pane wrapping an inner Edit + Spinner/UpDown
sub-window), so the preceding-sibling convention above does NOT reach the
inner Edit that a screen reader actually focuses (verified: its Name stays
empty either way). For these, call ctrl.SetLabel(name) directly on the
SpinCtrl/SpinCtrlDouble itself — verified this sets the outer composite's
accessible Name correctly, does NOT raise (SpinCtrl/SpinCtrlDouble aren't
wx.TextCtrl subclasses, so they don't hit the TextCtrl SetLabel assertion),
and does NOT alter the displayed numeric value.

CAVEAT — wx.Slider with wx.SL_LABELS: this style makes wx continuously
overwrite the Slider's own accessible Name with its current numeric value
on every change (so any name set via SetLabel()/SetName() is immediately
clobbered — verified). There is no known way to keep SL_LABELS' visible
min/max/value ticks AND have a stable descriptive Name at the same time.
The fix is to drop SL_LABELS and use accessible_label() before the slider
instead (verified this produces a correct, stable Name); replace any lost
visible value readout with a plain wx.StaticText updated on EVT_SLIDER.
"""

from __future__ import annotations

import wx


def accessible_label(parent: wx.Window, name: str) -> wx.StaticText:
    """Create the accessible name for the control that will be constructed
    immediately after this call, in the same parent.

    Usage — call this BEFORE constructing the control it names, with the
    same `parent`, and don't skip adding it to the sizer at the position
    immediately before the control (all three — Z-order, tab order, and
    sizer position — should agree; that's what makes Windows' native
    "preceding static labels its sibling" convention kick in reliably):

        accessible_label(panel, "Volume")
        slider = wx.Slider(panel, ...)
        sizer.Add(slider, ...)

    The label is zero-size (still Shown, so it participates in the
    accessibility tree, but takes up no layout space) unless the caller
    wants a real visible caption, in which case just use a normal
    wx.StaticText directly instead of this helper.
    """
    return wx.StaticText(parent, label=name, size=(0, 0))

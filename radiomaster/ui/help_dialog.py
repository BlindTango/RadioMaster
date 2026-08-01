"""Help > Help Contents dialog — a topic list plus a read-only content pane."""

from __future__ import annotations

import wx


TOPICS: list[tuple[str, str]] = [
    ("Getting Started", (
        "RadioMaster streams internet radio stations, records them automatically, "
        "and applies audio effects — all fully operable by keyboard and screen reader.\n\n"
        "The main window is a list of pages on the left: Radio, Favourites, Scheduler, "
        "Effects, and Settings. Use Tab/Shift+Tab or the arrow keys in that list to "
        "switch pages.\n\n"
        "On first launch, RadioMaster downloads the Radio Browser station catalog into "
        "a local database (a few seconds). After that, browsing is instant and works "
        "offline using the cached copy."
    )),
    ("Radio Page: Browsing & Searching", (
        "The station tree groups stations By Genre, By Country, and By Language. "
        "Expand a group to load its stations (loaded on demand, so the tree stays fast "
        "no matter how large the catalog is).\n\n"
        "Use the Search box to search Radio Browser directly by name, genre, country, "
        "or language; results replace the tree temporarily.\n\n"
        "Select a station and press Play, or press Enter/double-click a station to play "
        "it immediately. Add Custom Station lets you add a stream URL that isn't in the "
        "Radio Browser catalog. Save to Favourites bookmarks the selected station."
    )),
    ("Playback Controls", (
        "Play/Pause, Stop, Record, and Mute buttons sit below the station tree, along "
        "with a Volume slider.\n\n"
        "Stop only stops what you're listening to — it never interrupts any recording "
        "in progress, even of the same station.\n\n"
        "Record starts an independent recording of whichever station is currently "
        "SELECTED in the tree — not necessarily the one playing. This means you can "
        "listen to one station while recording several different ones at the same time; "
        "see 'Active Recordings' below."
    )),
    ("Recording & Active Recordings", (
        "Recording automatically splits into one file per track whenever the station's "
        "metadata changes, and discards any segment at or below the minimum track "
        "length (default 30 seconds, adjustable in Settings) — this is what filters "
        "out station IDs, jingles, and most ads.\n\n"
        "Each saved track is named 'Artist - Title' using metadata resolved from Deezer, "
        "then MusicBrainz, then (if configured) AcoustID audio fingerprinting, falling "
        "back to the station's raw text if all else fails.\n\n"
        "The Active Recordings list at the bottom of the Radio page shows every "
        "recording currently running, with elapsed time. Select one and press Stop "
        "Selected Recording to end it — or use the Record button again after selecting "
        "that same station in the tree."
    )),
    ("Favourites", (
        "The Favourites page lists your saved stations. Press Enter or Play to start "
        "one immediately, Remove to delete it, or Move Up/Move Down to reorder the list."
    )),
    ("Scheduler", (
        "Schedule automatic recordings: one-time, daily, weekly (specific weekdays), "
        "Nth weekday of the month (e.g. 'every 3rd Monday'), or a custom day interval. "
        "Pick a station from your Favourites or Custom Stations, a start time, a "
        "duration (or 'until stopped'), and an output format.\n\n"
        "The schedule list shows every configured recording with an enabled/disabled "
        "toggle. Overlapping schedules are flagged before saving."
    )),
    ("Audio Effects", (
        "The Effects box on the Radio page lists eight effects: Chorus, Compressor, "
        "Distortion, Echo, Flanger, Gargle, Reverb, and Equalizer. Check a box to enable "
        "an effect on the live playback stream, and use its dropdown to pick a preset.\n\n"
        "The separate Effects page is where presets are managed: pick an effect on the "
        "left, then New/Rename/Delete/Save presets on the right. Every parameter of the "
        "underlying audio filter is exposed as its own control, so presets can be tuned "
        "precisely.\n\n"
        "Reverb and Gargle are approximations (ffmpeg has no filter literally named "
        "either one) — Reverb uses layered echo taps, Gargle uses amplitude modulation "
        "(tremolo). Both are documented as such next to their controls."
    )),
    ("Settings", (
        "Settings covers: output soundcard, stream buffer size, VPN/proxy routing, "
        "FFmpeg path override, metadata sources (Deezer/MusicBrainz/AcoustID), default "
        "recording format, minimum track length, theme, station database update "
        "frequency, auto-play-last-station on startup, fade in/out between stations, "
        "muting live playback while recording, log level, and global hotkeys.\n\n"
        "Remember to press Apply after changing any Settings field."
    )),
    ("Global Hotkeys", (
        "Settings > Configure Global Hotkeys lets you assign system-wide key "
        "combinations for Play/Pause, Stop, Record Selected Station, Volume Up, and "
        "Volume Down — these work even when RadioMaster isn't the focused window. "
        "Type a combination like Ctrl+Alt+P into each field, or leave a field blank to "
        "disable that hotkey."
    )),
    ("Accessibility Notes", (
        "Every control has an explicit accessible name read by NVDA/Narrator, "
        "including the Station and Now Playing fields (read-only text boxes, not "
        "static labels, so screen readers can navigate directly to their content).\n\n"
        "The station tree, all buttons, and every settings control are fully keyboard "
        "operable. If you ever find something that a screen reader doesn't announce "
        "correctly, that's a bug — please report exactly what you heard (or didn't)."
    )),
]


class HelpDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="RadioMaster Help",
                          size=(720, 480), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        topics_label = wx.StaticText(self, label="&Topics:")
        self.topic_list = wx.ListBox(self, choices=[t for t, _ in TOPICS])

        content_label = wx.StaticText(self, label="Content:")
        self.content = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
        )

        close_btn = wx.Button(self, wx.ID_OK, label="&Close")

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(topics_label, 0, wx.BOTTOM, 4)
        left.Add(self.topic_list, 1, wx.EXPAND)

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

        self.topic_list.Bind(wx.EVT_LISTBOX, self._on_topic_selected)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

        self.topic_list.SetSelection(0)
        self._show_topic(0)
        self.topic_list.SetFocus()

    def _on_topic_selected(self, event: wx.CommandEvent) -> None:
        self._show_topic(self.topic_list.GetSelection())

    def _show_topic(self, index: int) -> None:
        if 0 <= index < len(TOPICS):
            title, body = TOPICS[index]
            self.content.ChangeValue(f"{title}\n{'=' * len(title)}\n\n{body}")

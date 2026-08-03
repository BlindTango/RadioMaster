"""Help > Help Contents dialog — a topic list plus a read-only content pane."""

from __future__ import annotations

import wx


TOPICS: list[tuple[str, str]] = [
    ("Getting Started", (
        "RadioMaster streams internet radio stations and podcasts, records them "
        "automatically, and applies audio effects — all fully operable by keyboard "
        "and screen reader.\n\n"
        "The main window has three tabs: Radio, Favourites, and Podcasts. Use "
        "Ctrl+Tab/Ctrl+Shift+Tab or click a tab to switch between them. Everything "
        "else — audio effects, recording scheduler, settings, and this help system — "
        "is reached from the menu bar rather than a tab, so the main window stays "
        "focused on whatever you're actually listening to.\n\n"
        "On first launch, RadioMaster downloads the Radio Browser station catalog into "
        "a local database (a few seconds). After that, browsing is instant and works "
        "offline using the cached copy."
    )),
    ("Menu Bar Overview", (
        "File: Podcasts submenu (Import/Export OPML, Add Feed by URL), Open Recording "
        "Folder, Open Podcast Folder, Exit.\n\n"
        "Effects: one submenu per audio effect (On/Off, presets, Settings...) — this "
        "replaces the old on-page Effects box.\n\n"
        "Tools: Settings..., Recording Scheduler....\n\n"
        "Help: Help Contents, What's New, Check for Updates, About RadioMaster."
    )),
    ("Radio Tab: Browsing & Searching", (
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
        "see 'Recording & Active Recordings' below."
    )),
    ("Lyrics", (
        "The Lyrics box below Now Playing automatically looks up lyrics for whatever "
        "track is currently playing, using the same 'Artist - Title' text the station "
        "sends. A status line above the lyrics text shows Fetching..., No lyrics found "
        "for this track, or an error if the lookup failed — the lyrics text itself only "
        "ever contains the song's actual words.\n\n"
        "Lyrics are reformatted for readability: line endings are normalized and long "
        "runs of blank lines are collapsed to one, so verses and choruses stay visually "
        "separated without walls of empty space. Instrumental tracks, jingles, and "
        "stations that don't announce track titles simply show no lyrics."
    )),
    ("Recording & Active Recordings", (
        "Recording automatically splits into one file per track whenever the station's "
        "metadata changes, and discards any segment at or below the minimum track "
        "length (default 30 seconds, adjustable in Settings) — this is what filters "
        "out station IDs, jingles, and most ads.\n\n"
        "Each saved track is named 'Artist - Title' using metadata resolved from Deezer, "
        "then MusicBrainz, then (if configured) AcoustID audio fingerprinting, falling "
        "back to the station's raw text if all else fails.\n\n"
        "The Active Recordings list at the bottom of the Radio tab shows every "
        "recording currently running, with elapsed time. Select one and press Stop "
        "Selected Recording to end it — or use the Record button again after selecting "
        "that same station in the tree.\n\n"
        "Use File > Open Recording Folder at any time to browse saved recordings "
        "directly in File Explorer."
    )),
    ("Favourites", (
        "The Favourites tab lists your saved stations. Press Enter or Play to start "
        "one immediately, Remove to delete it, or Move Up/Move Down to reorder the list."
    )),
    ("Podcasts & OPML", (
        "The Podcasts tab searches podcast directories (and PodcastIndex, if you've "
        "added an API key/secret in Settings) and lists your subscriptions with their "
        "episodes.\n\n"
        "File > Podcasts > Add Feed... subscribes directly by feed URL, useful for "
        "podcasts that don't show up in directory search. File > Podcasts > Import/"
        "Export OPML lets you move your subscription list to or from another podcast "
        "app.\n\n"
        "The Rate slider changes playback speed from 0.5x to 3.0x without changing "
        "pitch, and applies live to the currently playing episode — no restart needed. "
        "Rate Up/Rate Down can also be bound to global hotkeys in Tools > Settings... > "
        "Configure Global Hotkeys.\n\n"
        "Use File > Open Podcast Folder to browse downloaded podcast data directly in "
        "File Explorer."
    )),
    ("Audio Effects (Effects Menu)", (
        "The Effects menu has one submenu per effect: Chorus, Compressor, Distortion, "
        "Echo, Flanger, Gargle, Reverb, Equalizer, and Loudness. Each submenu has an "
        "On item to enable/disable that effect on the live playback stream, a list of "
        "presets (pick one to apply it immediately), and a Settings... item.\n\n"
        "An effect's Settings dialog is where presets are managed: New/Rename/Delete/"
        "Save presets, with every parameter of the underlying audio effect exposed as "
        "its own control, so presets can be tuned precisely.\n\n"
        "Reverb and Gargle are approximations — Reverb uses layered echo taps, Gargle "
        "uses amplitude modulation (tremolo). Both are documented as such next to their "
        "controls."
    )),
    ("Recording Scheduler", (
        "Tools > Recording Scheduler... schedules automatic recordings: one-time, "
        "daily, weekly (specific weekdays), Nth weekday of the month (e.g. 'every 3rd "
        "Monday'), or a custom day interval. Pick a station from your Favourites or "
        "Custom Stations, a start time, a duration (or 'until stopped'), and an output "
        "format.\n\n"
        "The schedule list shows every configured recording with an enabled/disabled "
        "toggle. Overlapping schedules are flagged before saving."
    )),
    ("Settings", (
        "Tools > Settings... covers: output soundcard, stream buffer size, connection "
        "retry attempts, VPN/proxy routing, FFmpeg path override, metadata sources "
        "(Deezer/MusicBrainz/AcoustID), PodcastIndex API key/secret, default recording "
        "format, minimum track length, theme, station database update frequency, "
        "auto-play-last-station on startup, fade in/out between stations, muting live "
        "playback while recording, ad detection, checking for updates automatically on "
        "startup, log level, and global hotkeys.\n\n"
        "Connection retry attempts controls how many extra times RadioMaster tries to "
        "open a station or podcast stream before reporting an error — useful on a slow "
        "or unreliable connection where the first attempt sometimes times out.\n\n"
        "Remember to press Apply after changing any Settings field."
    )),
    ("Global Hotkeys", (
        "Tools > Settings... > Configure Global Hotkeys lets you assign system-wide key "
        "combinations to: Play/Pause, Stop, Record Selected Station, Volume Up, Volume "
        "Down, Podcast Rate Up, Podcast Rate Down, Open Recording Folder, Open Podcast "
        "Folder, Open Settings, Open Recording Scheduler, and Open Help — these work "
        "even when RadioMaster isn't the focused window.\n\n"
        "Press Add..., choose a feature from the list, then the key combination you "
        "want — e.g. Ctrl+Alt+P. A feature can have more than one binding (say, a "
        "letter combo and a multimedia key); select an existing binding and press "
        "Edit... or Remove to change it."
    )),
    ("File Menu Shortcuts", (
        "File > Open Recording Folder and File > Open Podcast Folder jump straight to "
        "the relevant folder in File Explorer, without needing to know where RadioMaster "
        "stores its data on disk."
    )),
    ("Checking for Updates", (
        "Help > Check for Updates... checks GitHub for a newer release right away, and "
        "shows the release notes plus a Download & Install button if one is found.\n\n"
        "By default RadioMaster also checks automatically, silently, once at startup — "
        "this can be turned off in Tools > Settings.... If a check finds nothing new, "
        "or a silent check fails (e.g. no internet connection), RadioMaster stays "
        "quiet; only a manual Check for Updates reports 'you're up to date' or an "
        "error.\n\n"
        "Help > What's New... shows the changelog for the installed version and every "
        "earlier version, and pops up automatically the first time you start "
        "RadioMaster after an update."
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
        # A plain SetFocus() here gets overridden once ShowModal() gives the
        # default (Close) button initial focus -- EVT_INIT_DIALOG fires after
        # that, so setting focus there sticks. See AddCustomStationDialog.
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.topic_list.SetFocus()

    def _on_topic_selected(self, event: wx.CommandEvent) -> None:
        self._show_topic(self.topic_list.GetSelection())

    def _show_topic(self, index: int) -> None:
        if 0 <= index < len(TOPICS):
            title, body = TOPICS[index]
            self.content.ChangeValue(f"{title}\n{'=' * len(title)}\n\n{body}")

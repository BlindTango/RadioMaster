"""Radio page: station browsing, search, playback controls, custom stations, favourites."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

import wx
import wx.lib.scrolledpanel as scrolled

from ..core.custom_stations import CustomStationsStore
from ..core.effects_store import EffectsPresetStore, EffectsStateStore, build_active_effect_chain
from ..core.favourites import FavouritesStore
from ..core.lyrics import LyricsFetchError, LyricsResult, fetch_lyrics
from ..core.metadata import split_icy_title
from ..core.player import Player, PlayerState, StreamInfo
from ..core.recorder import StationRecordingSession
from ..core.station_api import Station, StationAPI, StationAPIError
from ..core.station_db import StationDB
from ..core.station_updater import StationUpdater
from ..utils.config import Config
from ..utils.wx_safe import call_after_safe
from .widgets.lyrics_panel import LyricsPanel
from .widgets.now_playing import NowPlayingPanel, format_status
from .widgets.player_controls import PlayerControls
from .widgets.recordings_list import RecordingsList
from .widgets.station_tree import StationTree

log = logging.getLogger(__name__)


class AddCustomStationDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Add Custom Station", size=(420, 360))

        grid = wx.FlexGridSizer(7, 2, 6, 8)
        grid.AddGrowableCol(1, 1)
        fields = [
            ("&Name:", "name_ctrl", wx.TextCtrl), ("&URL:", "url_ctrl", wx.TextCtrl),
            ("&Genre:", "genre_ctrl", wx.TextCtrl), ("&Country:", "country_ctrl", wx.TextCtrl),
            ("&Language:", "language_ctrl", wx.TextCtrl), ("Net&work:", "network_ctrl", wx.TextCtrl),
            ("&Bitrate (kbps):", "bitrate_ctrl", wx.SpinCtrl),
        ]
        for label_text, attr_name, ctrl_cls in fields:
            # The wx.StaticText MUST be constructed before ctrl (same parent,
            # same position) — Windows' native "adjacent static labels its
            # sibling" convention is what gives ctrl its accessible name; see
            # utils/accessibility.py for why a custom wx.Accessible override
            # isn't used here instead (it crashed).
            label = wx.StaticText(self, label=label_text)
            ctrl = ctrl_cls(self, min=0, max=1000, initial=0) if ctrl_cls is wx.SpinCtrl else ctrl_cls(self)
            setattr(self, attr_name, ctrl)
            grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        self.find_url_btn = wx.Button(self, label="&Find URL from Webpage...")

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 10)
        outer.Add(self.find_url_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizerAndFit(outer)

        self.FindWindowById(wx.ID_OK, self).Bind(wx.EVT_BUTTON, self._on_ok)
        self.find_url_btn.Bind(wx.EVT_BUTTON, self._on_find_url)
        # wx gives the dialog's default button (OK) initial focus once
        # ShowModal() actually starts, which overrides a plain SetFocus()
        # called here in __init__ — binding EVT_INIT_DIALOG (fired at the
        # start of ShowModal(), after that default-button focusing) is what
        # makes the Name field reliably end up focused instead.
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.name_ctrl.SetFocus()

    def _on_find_url(self, event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(
            self, "Paste the station's own webpage URL (e.g. its \"Listen Live\" page):",
            "Find Stream URL",
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        page_url = dlg.GetValue().strip()
        dlg.Destroy()
        if not page_url:
            return

        self.find_url_btn.Disable()
        self.find_url_btn.SetLabel("Searching...")

        def worker():
            from ..core.url_finder import find_stream_urls
            try:
                results = find_stream_urls(page_url)
            except Exception:
                results = []
            call_after_safe(self, self._on_find_url_done, results)

        threading.Thread(target=worker, daemon=True).start()

    def _on_find_url_done(self, results: list[str]) -> None:
        self.find_url_btn.Enable()
        self.find_url_btn.SetLabel("&Find URL from Webpage...")
        if not results:
            wx.MessageBox(
                "Couldn't find a stream URL on that page. Some stations load their "
                "player dynamically via JavaScript, which this can't see — you may "
                "need to find the URL manually (e.g. via your browser's network tab).",
                "No Stream URL Found", wx.OK | wx.ICON_INFORMATION,
            )
            return
        if len(results) == 1:
            self.url_ctrl.ChangeValue(results[0])
            return
        chooser = wx.SingleChoiceDialog(
            self, "Multiple possible stream URLs were found. Pick the right one:",
            "Choose Stream URL", results,
        )
        if chooser.ShowModal() == wx.ID_OK:
            self.url_ctrl.ChangeValue(chooser.GetStringSelection())
        chooser.Destroy()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if not self.name_ctrl.GetValue().strip() or not self.url_ctrl.GetValue().strip():
            wx.MessageBox("Name and URL are required.", "Missing Information", wx.OK | wx.ICON_WARNING)
            return
        event.Skip()

    def get_values(self) -> dict:
        return {
            "name": self.name_ctrl.GetValue().strip(),
            "url": self.url_ctrl.GetValue().strip(),
            "genre": self.genre_ctrl.GetValue().strip(),
            "country": self.country_ctrl.GetValue().strip(),
            "language": self.language_ctrl.GetValue().strip(),
            "network": self.network_ctrl.GetValue().strip(),
            "bitrate": self.bitrate_ctrl.GetValue(),
        }


class RadioPanel(scrolled.ScrolledPanel):
    """A ScrolledPanel, not a plain Panel: this page stacks a LOT of rows
    (search, station tree, action buttons, now-playing, player controls,
    active recordings) — on a window/screen too short to
    fit all of it, a plain Panel's sizer doesn't just look cramped, it
    forcibly compresses rows below their own declared MinSize, in the worst
    case straight to 0 and the control vanishes entirely (confirmed:
    reproduced by maximizing on a screen shorter than the frame's minimum
    height — several rows measured 0px tall). Scrolling means content that
    doesn't fit is still fully reachable instead of silently disappearing."""

    def __init__(self, parent, config: Config, station_api: StationAPI,
                 favourites: FavouritesStore, custom_stations: CustomStationsStore,
                 player: Player, set_status: Callable[[str], None],
                 effects_presets: EffectsPresetStore, effects_state: EffectsStateStore,
                 station_db: StationDB, station_updater: StationUpdater):
        super().__init__(parent)
        self.config = config
        self.station_api = station_api
        self.favourites = favourites
        self.custom_stations = custom_stations
        self.player = player
        self.set_status = set_status
        self.effects_presets = effects_presets
        self.effects_state = effects_state
        self.station_db = station_db
        self.station_updater = station_updater
        # Recording is independent of playback: any number of stations can
        # record concurrently (keyed by station uuid) while the Player plays
        # a completely different station through the speakers.
        self.active_recordings: dict[str, StationRecordingSession] = {}
        self._auto_muted_for_recording = False
        self._selected_station: Optional[Station] = None
        # Bumped on every search request so a slow/stale search (e.g. the
        # user edited the query and searched again before the first request
        # returned) can recognize it's no longer the latest one and discard
        # its results instead of overwriting a newer, correct set — this was
        # the cause of "search doesn't fire" needing to be run twice: the
        # first (now-stale) response was arriving AFTER the second and
        # winning the race.
        self._search_seq = 0
        # Set while a station switch is in flight so the 1s status tick
        # (which otherwise repaints over it with the generic state/bitrate
        # line) keeps showing "Connecting to X..." instead — gapless
        # switching keeps PlayerState.PLAYING the whole time (the OLD
        # station keeps audibly playing until the new one is ready), so
        # there was no player-state change at all for the status bar to
        # reflect; this tracks the switch independently of player state.
        # Cleared as soon as the new station's probe/metadata confirms it's
        # actually up, or after _CONNECT_TIMEOUT_SECONDS as a fallback so a
        # station that never sends usable probe/ICY data doesn't leave the
        # status bar stuck on "Connecting" forever.
        self._connecting_station_name: Optional[str] = None
        self._connecting_since = 0.0
        self._ad_flagged = False
        self._last_status_text = ""
        # Bumped on every track/station change so a lyrics fetch that's still
        # in flight when a newer one starts can recognize it's stale and
        # discard its result instead of overwriting the current track's
        # lyrics with an old track's — same race-guard pattern as _search_seq.
        self._lyrics_seq = 0

        search_label = wx.StaticText(self, label="&Search:")
        self.search_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Search by name, genre, country, or language")
        self.search_btn = wx.Button(self, label="&Search")

        self.tree = StationTree(self, station_db)
        # In a scrolled page, "proportion=1, EXPAND" no longer means "grow
        # into whatever extra room the window happens to have" — the page's
        # virtual/scrollable canvas IS the sizer's own computed minimum, so
        # a flexible item only ever gets exactly its declared MinSize,
        # never more, regardless of how big the actual window is. This
        # needs to directly be a comfortable browsing height, not just a
        # "don't vanish" floor (confirmed: 150 rendered as ~105px per list
        # after the group/station lists split it — technically present,
        # but not genuinely usable for browsing).
        self.tree.SetMinSize((-1, 320))
        self.now_playing = NowPlayingPanel(self)
        self.lyrics_panel = LyricsPanel(self)
        self.controls = PlayerControls(self)

        self.add_custom_btn = wx.Button(self, label="&Add Custom Station")
        self.favourite_btn = wx.Button(self, label="Save to &Favourites")

        self.recordings_list = RecordingsList(self)
        # 70px used to be this widget's whole budget, but that's the label
        # + the actual list + the Stop button all sharing it — confirmed
        # the list itself ended up squeezed to ~15px, unusable. It needs
        # genuine room of its own on top of the label/button overhead.
        self.recordings_list.SetMinSize((-1, 160))
        self.recordings_list.on_stop_requested = self._stop_recording_for

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)

        action_row = wx.BoxSizer(wx.HORIZONTAL)
        action_row.Add(self.add_custom_btn, 0, wx.RIGHT, 6)
        action_row.Add(self.favourite_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(search_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(action_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.now_playing, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(self.lyrics_panel, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.controls, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.recordings_list, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)
        # SetupScrolling() (not raw SetScrollRate()+FitInside()) is what
        # actually keeps every row at its natural/minimum size and scrolls
        # the overflow — a bare wx.ScrolledWindow with FitInside() still
        # laid the sizer out against the visible viewport size, compressing
        # every row into whatever fit (confirmed: lists stayed cramped at
        # ~105px instead of their natural ~223px, virtual size was correct
        # but rendering wasn't). ScrolledPanel's helper handles this
        # correctly out of the box.
        self.SetupScrolling(scroll_x=False, scroll_y=True)

        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.add_custom_btn.Bind(wx.EVT_BUTTON, self._on_add_custom)
        self.favourite_btn.Bind(wx.EVT_BUTTON, self._on_save_favourite)
        self.tree.on_station_activated = self._on_station_activated
        self.tree.on_selection_changed = self._on_tree_sel_changed

        self.controls.on_play = self._on_play_pause
        self.controls.on_stop = self._on_stop
        self.controls.on_record = self._on_record
        self.controls.on_mute = self._on_mute
        self.controls.on_volume_changed = self._on_volume_changed
        self.controls.on_pan_changed = self._on_pan_changed

        saved_volume = int(round(self.config.get("volume", 1.0) * 100))
        self.controls.set_volume(saved_volume)
        self.player.set_volume(saved_volume / 100)

        saved_pan = int(round(self.config.get("pan", 0.5) * 100))
        self.controls.set_pan(saved_pan)
        self.player.set_pan(saved_pan / 100)

        self.player.apply_effects(build_active_effect_chain(effects_presets, effects_state))

        self.bind_player_callbacks()

        self._status_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_status_tick, self._status_timer)
        self._status_timer.Start(1000)

        self._load_stations()

    def bind_player_callbacks(self) -> None:
        """(Re)claims the shared Player's single-slot event callbacks for
        this panel. The Podcast panel points them at itself while its tab is
        active (playing an on-demand episode instead of a live station) and
        MainFrame calls this again on switching back to the Radio tab so its
        own Play/Pause state and status text stay in sync — see
        MainFrame._on_page_changed."""
        self.player.on_state_changed = self._on_player_state
        self.player.on_now_playing = self._on_now_playing
        self.player.on_stream_info = self._on_stream_info
        self.player.on_error = self._on_player_error
        self.player.on_ad_detected = self._on_ad_detected
        # Switching stations while already playing (radio-to-radio, or a
        # gapless hand-off from the Podcast panel) never fires a NEW state-
        # change callback if the Player was already PLAYING throughout — sync
        # this panel's own Play/Pause button to reality right now instead of
        # waiting for an event that may never come.
        self._on_player_state(self.player.state)

    # Cap on what this page ever asks the frame to grow to, regardless of
    # how much content ends up stacked on it (currently ~850px worth) — a
    # screen shorter than this (or a window later resized/maximized
    # smaller, e.g. onto a smaller monitor) makes this page scroll instead
    # of demanding the frame be taller than the screen. Chosen to comfortably
    # fit inside a plain 1366x768 laptop screen after title bar/taskbar
    # chrome, the most common small-screen case.
    _MAX_REPORTED_HEIGHT = 640

    def GetBestSize(self) -> wx.Size:
        # wx.Notebook computes its own (and so the frame's) required size by
        # querying each page's GetBestSize(), which by default delegates
        # straight to the sizer's CalcMin() — the full stacked-content
        # height, ignoring SetMinSize entirely. Capping it here (rather than
        # letting it report the true ~850px content height) is what stops
        # the frame from feeling obligated to grow taller than a real screen
        # can accommodate; anything beyond this scrolls instead.
        natural = self.GetSizer().CalcMin() if self.GetSizer() else wx.Size(900, 500)
        return wx.Size(natural.width, min(natural.height, self._MAX_REPORTED_HEIGHT))

    # ---- data loading -------------------------------------------------------

    def _load_stations(self) -> None:
        """Populate the tree from the local SQLite DB (fast). If the DB is
        empty (first run, or a fresh portable copy), fetch it from Radio
        Browser once first."""
        if self.station_db.station_count() > 0:
            self._apply_sections()
            return

        self.set_status("Status: Fetching station list for the first time...")

        def progress_cb(bytes_read: int, total) -> None:
            if total:
                percent = min(100, int(bytes_read * 100 / total))
                text = f"Status: Fetching station list for the first time... {percent}%"
            else:
                text = f"Status: Fetching station list for the first time... ({bytes_read // 1024} KB)"
            call_after_safe(self, self.set_status, text)

        def worker():
            result = self.station_updater.update_now(progress_cb=progress_cb)
            if not result.ok:
                call_after_safe(self, self.set_status, f"Status: Could not load stations ({result.error})")
                return
            call_after_safe(self, self._apply_sections)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_sections(self) -> None:
        self.tree.load_sections()
        self.tree.add_custom_section(self.custom_stations.all())
        self.set_status("Status: Ready")

    def refresh_after_station_update(self) -> None:
        """Called after a manual or scheduled station DB update completes."""
        call_after_safe(self, self._apply_sections)

    def _on_search(self, event: wx.CommandEvent) -> None:
        query = self.search_ctrl.GetValue().strip()
        if not query:
            return
        self.set_status("Status: Searching...")
        self._search_seq += 1
        seq = self._search_seq

        def worker():
            # The local catalog (synced periodically, ~61,000 stations,
            # trigram-indexed — see StationDB.search_local) covers the vast
            # majority of searches and answers near-instantly, unlike the
            # network call below, which takes a few seconds every time.
            # Only fall through to Radio Browser itself when nothing local
            # matches, e.g. a station added since the last catalog sync.
            results = self.station_db.search_local(query)
            if not results:
                try:
                    results = self.station_api.search(query)
                except StationAPIError:
                    pass  # offline/unreachable and no local match either — empty result stands
            if seq != self._search_seq:
                return  # a newer search superseded this one; discard stale results
            call_after_safe(self, self.tree.set_search_results, results)
            call_after_safe(self, self.set_status, f"Status: {len(results)} result(s) for '{query}'")

        threading.Thread(target=worker, daemon=True).start()

    # ---- tree / selection -----------------------------------------------------

    def _on_tree_sel_changed(self) -> None:
        try:
            self._selected_station = self.tree.get_selected_station()
        except RuntimeError:
            pass  # control torn down mid-shutdown; a stale callback, safe to ignore
        self._refresh_record_button()

    def _refresh_record_button(self) -> None:
        recording = bool(self._selected_station and self._selected_station.uuid in self.active_recordings)
        self.controls.set_recording(recording)

    def _on_station_activated(self, station: Station) -> None:
        self._selected_station = station
        self._play_station(station)

    # ---- playback -----------------------------------------------------------

    def _play_station(self, station: Station) -> None:
        self.now_playing.set_station(station.name)
        self.now_playing.set_now_playing("")
        self._lyrics_seq += 1
        self.lyrics_panel.clear()
        # Immediate feedback rather than waiting for the next 1s status tick —
        # without this there's up to a second where the status bar still
        # shows the PREVIOUS station's state/bitrate with nothing indicating
        # a new connection is even in progress. _connecting_station_name
        # keeps this showing across subsequent ticks too (see _on_status_tick).
        self._connecting_station_name = station.name
        self._connecting_since = time.monotonic()
        self.set_status(f"Status: Connecting to {station.name}...")
        self.player.start(station.url, station_name=station.name)
        threading.Thread(target=self.station_api.click, args=(station.uuid,), daemon=True).start()
        self.config.set("last_station_uuid", station.uuid, save=False)
        self.config.set("last_station_name", station.name, save=False)
        self.config.set("last_station_url", station.url)

    def _on_play_pause(self) -> None:
        # ERROR is included alongside STOPPED here: once a stream drops for
        # good (ffmpeg's own reconnect attempts exhausted) _fail() leaves the
        # player in ERROR state, and without this the Play/Pause button (and
        # its hotkey) silently did nothing from then on — looked exactly like
        # "the stream stopped and won't play again" even with a fine network
        # connection, since re-selecting the station in the tree was the only
        # thing that actually worked.
        if self.player.state in (PlayerState.STOPPED, PlayerState.ERROR) and self._selected_station:
            self._play_station(self._selected_station)
        elif self.player.state == PlayerState.PAUSED:
            self.player.resume()
        elif self.player.state in (PlayerState.PLAYING, PlayerState.CONNECTING):
            self.player.pause()

    def _on_stop(self) -> None:
        # Stops playback only — recording runs independently and is
        # controlled from the Active Recordings list / Record button, so
        # stopping what you're listening to must never interrupt a recording
        # of a different (or even the same) station.
        self.player.stop()
        self._connecting_station_name = None
        self.now_playing.set_station("")
        self.now_playing.set_now_playing("")
        self._lyrics_seq += 1
        self.lyrics_panel.clear()

    def _on_mute(self) -> None:
        muted = self.player.toggle_mute()
        self.controls.set_muted(muted)

    def _on_volume_changed(self, percent: int) -> None:
        self.player.set_volume(percent / 100)
        self.config.set("volume", percent / 100)

    def _on_pan_changed(self, percent: int) -> None:
        self.player.set_pan(percent / 100)
        self.config.set("pan", percent / 100)

    # ---- global hotkey entry points -------------------------------------------

    def toggle_play_pause(self) -> None:
        self._on_play_pause()

    def stop_playback(self) -> None:
        self._on_stop()

    def toggle_record_selected(self) -> None:
        self._on_record()

    def volume_step(self, delta_percent: int) -> None:
        new_percent = max(0, min(100, self.controls.volume_slider.GetValue() + delta_percent))
        self.controls.set_volume(new_percent)
        self._on_volume_changed(new_percent)

    def _on_record(self) -> None:
        """Record button acts on the station currently SELECTED in the tree —
        not necessarily the one playing — so you can record a different
        station than you're listening to, or several at once."""
        station = self._selected_station
        if not station:
            wx.MessageBox("Select a station in the tree first.", "No Station Selected",
                          wx.OK | wx.ICON_INFORMATION)
            return
        if station.uuid in self.active_recordings:
            self._stop_recording_for(station.uuid)
        else:
            self._start_recording_for(station)

    def _start_recording_for(self, station: Station) -> None:
        session = StationRecordingSession(
            station_name=station.name, station_url=station.url,
            duration_minutes=None,  # runs until explicitly stopped
            fmt=self.config.get("recording_format", "mp3"),
            use_deezer=self.config.get("metadata_deezer_enabled", True),
            use_musicbrainz=self.config.get("metadata_musicbrainz_enabled", True),
            proxies=self._proxies(),
            min_track_seconds=self.config.get("min_track_seconds", 30),
            acoustid_api_key=self.config.get("acoustid_api_key"),
        )
        session.recorder.on_track_saved = lambda path: call_after_safe(
            self, self.set_status, f"Status: Saved track from {station.name}: {os.path.basename(path)}")
        session.recorder.on_track_discarded = lambda title, dur: call_after_safe(
            self, self.set_status, f"Status: Skipped short segment on {station.name} "
                                    f"({dur:.0f}s, likely an ad/jingle)")
        session.start()
        self.active_recordings[station.uuid] = session
        self._refresh_record_button()
        self.set_status(f"Status: Recording started: {station.name}")

        if (self.config.get("mute_playback_while_recording", False)
                and len(self.active_recordings) == 1 and not self.player.muted):
            self.player.set_mute(True)
            self.controls.set_muted(True)
            self._auto_muted_for_recording = True

    def _stop_recording_for(self, uuid: str) -> None:
        session = self.active_recordings.pop(uuid, None)
        if session is None:
            return
        name = session.station_name
        threading.Thread(target=session.stop, daemon=True).start()
        self._refresh_record_button()
        self.set_status(f"Status: Recording stopped: {name}")

        if not self.active_recordings and getattr(self, "_auto_muted_for_recording", False):
            self.player.set_mute(False)
            self.controls.set_muted(False)
            self._auto_muted_for_recording = False

    def _refresh_recordings_list(self) -> None:
        sessions = {
            uuid: (session.station_name, session.elapsed_seconds)
            for uuid, session in self.active_recordings.items()
        }
        self.recordings_list.refresh(sessions)

    def _proxies(self) -> Optional[dict]:
        if self.config.get("vpn_enabled") and self.config.get("vpn_proxy"):
            proxy = self.config.get("vpn_proxy")
            return {"http": proxy, "https": proxy}
        return None

    # ---- custom stations / favourites ----------------------------------------

    def _on_add_custom(self, event: wx.CommandEvent) -> None:
        dlg = AddCustomStationDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.get_values()
            self.custom_stations.add(**values)
            self.tree.add_custom_section(self.custom_stations.all())
            # Jump to the Custom Stations category so the new entry is
            # immediately visible — otherwise adding while browsing any
            # other category silently updates nothing on screen and looks
            # like the add failed (confirmed: this caused repeat re-adds).
            self.tree.show_custom_stations()
            self.set_status(f"Status: Added custom station '{values['name']}'")
        dlg.Destroy()

    def _on_save_favourite(self, event: wx.CommandEvent) -> None:
        station = self._selected_station
        if not station:
            wx.MessageBox("Select a station first.", "No Station Selected", wx.OK | wx.ICON_INFORMATION)
            return
        self.favourites.add(station)
        self.set_status(f"Status: '{station.name}' saved to Favourites")

    # ---- player event callbacks (invoked off the UI thread) -------------------

    def _on_player_state(self, state: PlayerState) -> None:
        call_after_safe(self, self.controls.set_playing, state in (PlayerState.PLAYING, PlayerState.CONNECTING))

    def _on_now_playing(self, title: str) -> None:
        self._connecting_station_name = None
        call_after_safe(self, self.now_playing.set_now_playing, title)
        call_after_safe(self, self._start_lyrics_fetch, title)

    def _start_lyrics_fetch(self, title: str) -> None:
        self._lyrics_seq += 1
        seq = self._lyrics_seq
        artist, song = split_icy_title(title.strip()) if title.strip() else ("Unknown", "")
        if not song or artist == "Unknown":
            self.lyrics_panel.clear()
            return

        self.lyrics_panel.set_status(f"Fetching lyrics for {artist} - {song}...")
        self.lyrics_panel.set_lyrics("")
        proxies = self._proxies()

        def worker():
            try:
                result = fetch_lyrics(artist, song, proxies=proxies)
            except LyricsFetchError as exc:
                call_after_safe(self, self._on_lyrics_result, seq, None, str(exc))
                return
            call_after_safe(self, self._on_lyrics_result, seq, result, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_lyrics_result(self, seq: int, result: Optional[LyricsResult], error: Optional[str]) -> None:
        if seq != self._lyrics_seq:
            return  # a newer track has since started; discard this stale result
        if error:
            self.lyrics_panel.set_status(f"Lyrics unavailable: {error}")
            return
        if result is None:
            self.lyrics_panel.set_status("No lyrics found for this track.")
            return
        self.lyrics_panel.set_status(f"Lyrics for {result.artist} - {result.title}:")
        self.lyrics_panel.set_lyrics(result.text)

    def _on_stream_info(self, info: StreamInfo) -> None:
        self._connecting_station_name = None

    def _on_ad_detected(self, flagged: bool) -> None:
        call_after_safe(self, self._set_ad_flagged, flagged)

    def _set_ad_flagged(self, flagged: bool) -> None:
        self._ad_flagged = flagged

    def _on_player_error(self, message: str) -> None:
        call_after_safe(self, self.set_status, f"Status: Error — {message}")
        call_after_safe(self, self.controls.set_playing, False)

    _CONNECT_TIMEOUT_SECONDS = 10.0

    def _on_status_tick(self, event: wx.TimerEvent) -> None:
        if self._connecting_station_name is not None:
            if time.monotonic() - self._connecting_since < self._CONNECT_TIMEOUT_SECONDS:
                self.set_status(f"Status: Connecting to {self._connecting_station_name}...")
                self._refresh_recordings_list()
                return
            self._connecting_station_name = None  # gave up waiting for confirmation; fall through
        state_label = self.player.state.value.title()
        info = self.player.stream_info
        text = format_status(
            state_label, info.bitrate_kbps, info.codec, info.sample_rate, self.player.buffer_fill,
            self._ad_flagged,
        )
        # SetStatusText() fires an accessible text-changed event NVDA speaks
        # automatically, so re-sending it every second (as buffer_fill's raw
        # percentage jitters up/down by 1) turns the status bar into constant
        # chatter that talks over itself -- and over the one-off "Likely
        # advertisement" flag this same line is meant to surface. Only push a
        # new announcement when the rounded, screen-reader-facing text
        # actually changed.
        if text != self._last_status_text:
            self._last_status_text = text
            self.set_status(text)
        self._refresh_recordings_list()

    def play_station_object(self, station: Station) -> None:
        """Entry point used by other panels (Favourites) to start playback here."""
        self._selected_station = station
        self._play_station(station)

    def stop_all_recordings(self) -> None:
        """Called on application shutdown so no ffmpeg subprocess is orphaned."""
        for session in self.active_recordings.values():
            try:
                session.stop()
            except Exception:
                pass
        self.active_recordings.clear()

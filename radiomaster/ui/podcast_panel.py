"""Podcasts page: search directories, subscribe/unsubscribe, list episodes,
play/pause/stop/next/previous with volume/rate/pan.

Reuses the app's single shared Player instance (same one Radio uses) since
there's only one audio output pipeline — playing a podcast episode naturally
interrupts whatever radio station was playing, and vice versa. Because
Player's event callbacks (on_state_changed etc.) are single-slot, not a
multi-subscriber list, this panel only owns them while its tab is actually
visible; see bind_player_callbacks() and MainFrame._on_page_changed.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import wx
import wx.lib.scrolledpanel as scrolled

from ..core.opml import OPMLError, parse_opml, write_opml
from ..core.player import Player, PlayerState
from ..core.podcast_api import (
    Episode, ITunesDirectory, PodcastAPIError, PodcastDirectory, PodcastIndexDirectory,
    PodcastResult, fetch_episodes, fetch_feed_metadata, search_all,
)
from ..core.podcast_subscriptions import PodcastSubscriptionsStore
from ..utils.accessibility import accessible_label
from ..utils.config import Config
from ..utils.wx_safe import call_after_safe
from .widgets.now_playing import NowPlayingPanel, ReadOnlyFocusableTextCtrl
from .widgets.podcast_controls import PodcastControls

log = logging.getLogger(__name__)


class PodcastPanel(scrolled.ScrolledPanel):
    # Same reasoning as RadioPanel/SettingsPanel's own caps — a screen
    # shorter than this page's true stacked-content height gets scrolling
    # instead of an over-tall frame.
    _MAX_REPORTED_HEIGHT = 640

    def __init__(self, parent, config: Config, subscriptions: PodcastSubscriptionsStore, player: Player):
        super().__init__(parent)
        self.config = config
        self.subscriptions = subscriptions
        self.player = player

        self.itunes_directory = ITunesDirectory()
        self.podcastindex_directory = PodcastIndexDirectory(
            config.get("podcastindex_api_key"), config.get("podcastindex_api_secret"))

        self._search_results: list[PodcastResult] = []
        self._episodes: list[Episode] = []
        self._selected_podcast: Optional[PodcastResult] = None
        # What's actually PLAYING (independent of whatever podcast/episode is
        # merely being browsed in the lists right now) — Next/Previous act on
        # this, not on the currently-displayed episode list.
        self._playing_podcast: Optional[PodcastResult] = None
        self._playing_episodes: list[Episode] = []
        self._playing_index: Optional[int] = None
        self._search_seq = 0
        self._episodes_seq = 0

        accessible_label(self, "Podcast directory")
        self.directory_choice = wx.Choice(
            self, choices=["All directories", "iTunes / Apple Podcasts", "Podcast Index"])
        self.directory_choice.SetSelection(0)

        search_label = wx.StaticText(self, label="&Search podcasts:")
        self.search_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Search by podcast name or topic")
        self.search_btn = wx.Button(self, label="&Search")

        accessible_label(self, "Search results")
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.results_list.InsertColumn(0, "Title", width=220)
        self.results_list.InsertColumn(1, "Author", width=150)
        self.results_list.InsertColumn(2, "Genre", width=140)
        self.results_list.InsertColumn(3, "Directory", width=140)
        self.results_list.SetMinSize((-1, 150))

        self.subscribe_btn = wx.Button(self, label="Su&bscribe")

        accessible_label(self, "Subscribed podcasts")
        self.subs_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.subs_list.InsertColumn(0, "Title", width=220)
        self.subs_list.InsertColumn(1, "Author", width=150)
        self.subs_list.SetMinSize((-1, 150))

        self.unsubscribe_btn = wx.Button(self, label="&Unsubscribe")

        accessible_label(self, "Episodes")
        self.episodes_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.episodes_list.InsertColumn(0, "Episode", width=280)
        self.episodes_list.InsertColumn(1, "Published", width=150)
        self.episodes_list.InsertColumn(2, "Duration", width=90)
        self.episodes_list.SetMinSize((-1, 200))

        description_label = wx.StaticText(self, label="Episode description:")
        self.description_ctrl = ReadOnlyFocusableTextCtrl(
            self, style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.description_ctrl.SetMinSize((-1, 80))

        self.now_playing = NowPlayingPanel(self)
        self.controls = PodcastControls(self)

        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_row.Add(self.directory_choice, 0, wx.RIGHT, 6)
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        search_row.Add(self.search_btn, 0)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(search_row, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.results_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(self.subscribe_btn, 0, wx.ALL, 6)
        outer.Add(self.subs_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(self.unsubscribe_btn, 0, wx.ALL, 6)
        outer.Add(self.episodes_list, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(description_label, 0, wx.LEFT | wx.TOP, 6)
        outer.Add(self.description_ctrl, 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.now_playing, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(self.controls, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)
        self.SetupScrolling(scroll_x=False, scroll_y=True)

        saved_volume = int(round(config.get("podcast_volume", 1.0) * 100))
        self.controls.set_volume(saved_volume)
        saved_rate = config.get("podcast_rate", 1.0)
        self.controls.set_rate(saved_rate)
        saved_pan = int(round(config.get("podcast_pan", 0.5) * 100))
        self.controls.set_pan(saved_pan)

        self.search_btn.Bind(wx.EVT_BUTTON, self._on_search)
        self.search_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_search)
        self.results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self._on_subscribe(e))
        self.subscribe_btn.Bind(wx.EVT_BUTTON, self._on_subscribe)
        self.subs_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_subs_sel_changed)
        self.unsubscribe_btn.Bind(wx.EVT_BUTTON, self._on_unsubscribe)
        self.episodes_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_episode_sel_changed)
        self.episodes_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_episode_activated)

        self.controls.on_play = self._on_play
        self.controls.on_stop = self._on_stop
        self.controls.on_previous = self._on_previous
        self.controls.on_next = self._on_next
        self.controls.on_volume_changed = self._on_volume_changed
        self.controls.on_rate_changed = self._on_rate_changed
        self.controls.on_rate_committed = self._on_rate_committed
        self.controls.on_pan_changed = self._on_pan_changed

        self._refresh_subscriptions()

    def GetBestSize(self) -> wx.Size:
        natural = self.GetSizer().CalcMin() if self.GetSizer() else wx.Size(400, 500)
        return wx.Size(natural.width, min(natural.height, self._MAX_REPORTED_HEIGHT))

    def bind_player_callbacks(self) -> None:
        """(Re)claims the shared Player's event callbacks for this panel —
        see RadioPanel.bind_player_callbacks(), the counterpart on the other
        side of this same hand-off."""
        self.player.on_state_changed = self._on_player_state
        self.player.on_now_playing = self._on_now_playing
        self.player.on_error = self._on_player_error
        self.player.on_finished = self._on_player_finished
        self.player.set_volume(self.controls.volume_slider.GetValue() / 100)
        self.player.set_pan(self.controls.pan_slider.GetValue() / 100)

    def set_proxies(self, proxies: Optional[dict]) -> None:
        self.itunes_directory.set_proxies(proxies)
        self.podcastindex_directory.set_proxies(proxies)
        self._proxies = proxies

    def set_podcastindex_credentials(self, api_key: Optional[str], api_secret: Optional[str]) -> None:
        self.podcastindex_directory.set_credentials(api_key, api_secret)

    _proxies: Optional[dict] = None

    def set_status(self, text: str) -> None:
        top = wx.GetTopLevelParent(self)
        if hasattr(top, "set_status"):
            top.set_status(text)

    # ---- search / subscribe -------------------------------------------------

    def _directories_for_selection(self) -> list[PodcastDirectory]:
        selection = self.directory_choice.GetSelection()
        if selection == 1:
            return [self.itunes_directory]
        if selection == 2:
            return [self.podcastindex_directory]
        return [self.itunes_directory, self.podcastindex_directory]

    def _on_search(self, event: wx.CommandEvent) -> None:
        term = self.search_ctrl.GetValue().strip()
        if not term:
            return
        self.set_status("Status: Searching podcasts...")
        self._search_seq += 1
        seq = self._search_seq
        directories = self._directories_for_selection()

        def worker():
            try:
                results = search_all(term, directories)
            except PodcastAPIError as exc:
                if seq != self._search_seq:
                    return
                call_after_safe(self, self.set_status, f"Status: Podcast search failed ({exc})")
                return
            if seq != self._search_seq:
                return  # a newer search superseded this one; discard stale results
            call_after_safe(self, self._apply_search_results, results, term)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_search_results(self, results: list[PodcastResult], term: str) -> None:
        self._search_results = results
        self.results_list.DeleteAllItems()
        for result in results:
            idx = self.results_list.InsertItem(self.results_list.GetItemCount(), result.title)
            self.results_list.SetItem(idx, 1, result.author)
            self.results_list.SetItem(idx, 2, result.genre)
            self.results_list.SetItem(idx, 3, result.directory)
        self.set_status(f"Status: {len(results)} result(s) for '{term}'")

    def _selected_result(self) -> Optional[PodcastResult]:
        idx = self.results_list.GetFirstSelected()
        if idx == -1 or idx >= len(self._search_results):
            return None
        return self._search_results[idx]

    def _on_subscribe(self, event: wx.CommandEvent) -> None:
        result = self._selected_result()
        if not result:
            wx.MessageBox("Select a podcast from the search results first.", "No Selection",
                          wx.OK | wx.ICON_INFORMATION)
            return
        self.subscriptions.subscribe(result)
        self._refresh_subscriptions()
        self.set_status(f"Status: Subscribed to '{result.title}'")

    # ---- subscriptions / episodes -------------------------------------------

    def _refresh_subscriptions(self) -> None:
        self.subs_list.DeleteAllItems()
        for podcast in self.subscriptions.all():
            idx = self.subs_list.InsertItem(self.subs_list.GetItemCount(), podcast.title)
            self.subs_list.SetItem(idx, 1, podcast.author)

    def _selected_subscription(self) -> Optional[PodcastResult]:
        idx = self.subs_list.GetFirstSelected()
        subs = self.subscriptions.all()
        if idx == -1 or idx >= len(subs):
            return None
        return subs[idx]

    def _on_unsubscribe(self, event: wx.CommandEvent) -> None:
        podcast = self._selected_subscription()
        if not podcast:
            wx.MessageBox("Select a subscribed podcast first.", "No Selection", wx.OK | wx.ICON_INFORMATION)
            return
        self.subscriptions.unsubscribe(podcast.feed_url)
        self._refresh_subscriptions()
        if self._selected_podcast and self._selected_podcast.feed_url == podcast.feed_url:
            self._selected_podcast = None
            self._episodes = []
            self.episodes_list.DeleteAllItems()
            self.description_ctrl.ChangeValue("")
        self.set_status(f"Status: Unsubscribed from '{podcast.title}'")

    # ---- add feed / OPML import-export --------------------------------------

    def add_feed_by_url(self, feed_url: str) -> None:
        """Subscribes to a feed the user already has the URL for, bypassing
        directory search entirely -- for feeds that don't show up (or
        shouldn't show up) in iTunes/Podcast Index search results."""
        feed_url = feed_url.strip()
        if not feed_url:
            return
        if self.subscriptions.contains(feed_url):
            wx.MessageBox("Already subscribed to that feed.", "Already Subscribed", wx.OK | wx.ICON_INFORMATION)
            return
        self.set_status("Status: Adding podcast feed...")

        def worker():
            try:
                result = fetch_feed_metadata(feed_url, proxies=self._proxies)
            except PodcastAPIError as exc:
                call_after_safe(self, wx.MessageBox, f"Could not add feed: {exc}", "Add Feed Failed",
                                 wx.OK | wx.ICON_ERROR)
                call_after_safe(self, self.set_status, "Status: Add feed failed")
                return
            call_after_safe(self, self._finish_add_feed, result)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_add_feed(self, result: PodcastResult) -> None:
        self.subscriptions.subscribe(result)
        self._refresh_subscriptions()
        self.set_status(f"Status: Subscribed to '{result.title}'")

    def import_opml(self, path: str) -> None:
        try:
            feeds = parse_opml(path)
        except OPMLError as exc:
            wx.MessageBox(str(exc), "Import Failed", wx.OK | wx.ICON_ERROR)
            return
        added = 0
        for title, feed_url in feeds:
            if self.subscriptions.contains(feed_url):
                continue
            self.subscriptions.subscribe(PodcastResult(feed_url=feed_url, title=title, directory="Imported"))
            added += 1
        self._refresh_subscriptions()
        skipped = len(feeds) - added
        message = f"Imported {added} podcast(s)."
        if skipped:
            message += f" Skipped {skipped} already-subscribed feed(s)."
        wx.MessageBox(message, "Import Complete", wx.OK | wx.ICON_INFORMATION)
        self.set_status(f"Status: {message}")

    def export_opml(self, path: str) -> None:
        podcasts = self.subscriptions.all()
        if not podcasts:
            wx.MessageBox("There are no podcast subscriptions to export.", "Nothing To Export",
                          wx.OK | wx.ICON_INFORMATION)
            return
        try:
            write_opml(path, podcasts)
        except OPMLError as exc:
            wx.MessageBox(str(exc), "Export Failed", wx.OK | wx.ICON_ERROR)
            return
        self.set_status(f"Status: Exported {len(podcasts)} podcast(s) to '{path}'")

    def _on_subs_sel_changed(self, event: wx.ListEvent) -> None:
        podcast = self._selected_subscription()
        if not podcast:
            return
        self._selected_podcast = podcast
        self._load_episodes(podcast)

    def _load_episodes(self, podcast: PodcastResult) -> None:
        self.set_status(f"Status: Loading episodes for '{podcast.title}'...")
        self._episodes_seq += 1
        seq = self._episodes_seq

        def worker():
            try:
                episodes = fetch_episodes(podcast.feed_url, proxies=self._proxies)
            except PodcastAPIError as exc:
                if seq != self._episodes_seq:
                    return
                call_after_safe(self, self.set_status, f"Status: Could not load episodes ({exc})")
                return
            if seq != self._episodes_seq:
                return  # a newer selection superseded this one; discard stale results
            call_after_safe(self, self._apply_episodes, episodes)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_episodes(self, episodes: list[Episode]) -> None:
        self._episodes = episodes
        self.episodes_list.DeleteAllItems()
        for episode in episodes:
            idx = self.episodes_list.InsertItem(self.episodes_list.GetItemCount(), episode.title)
            self.episodes_list.SetItem(idx, 1, episode.pub_date)
            self.episodes_list.SetItem(idx, 2, episode.duration)
        self.description_ctrl.ChangeValue("")
        self.set_status(f"Status: {len(episodes)} episode(s) loaded")

    def _selected_episode_index(self) -> Optional[int]:
        idx = self.episodes_list.GetFirstSelected()
        if idx == -1 or idx >= len(self._episodes):
            return None
        return idx

    def _on_episode_sel_changed(self, event: wx.ListEvent) -> None:
        idx = self._selected_episode_index()
        if idx is None:
            return
        self.description_ctrl.ChangeValue(self._episodes[idx].description)

    def _on_episode_activated(self, event: wx.ListEvent) -> None:
        idx = self._selected_episode_index()
        if idx is None:
            return
        self._start_playing(self._selected_podcast, self._episodes, idx)

    # ---- playback ------------------------------------------------------------

    def _start_playing(self, podcast: Optional[PodcastResult], episodes: list[Episode], index: int) -> None:
        self._playing_podcast = podcast
        self._playing_episodes = episodes
        self._playing_index = index
        self._play_current(seek_seconds=0.0)

    def _play_current(self, seek_seconds: float = 0.0) -> None:
        if self._playing_index is None or self._playing_index >= len(self._playing_episodes):
            return
        episode = self._playing_episodes[self._playing_index]
        rate = self.controls.rate_slider.GetValue() / 100.0
        podcast_title = self._playing_podcast.title if self._playing_podcast else ""
        self.player.start(episode.audio_url, station_name=podcast_title, expect_eof=True,
                           rate=rate, seek_seconds=seek_seconds)
        self.now_playing.set_station(podcast_title)
        self.now_playing.set_now_playing(episode.title)
        self.set_status(f"Status: Playing '{episode.title}'")

    def _on_play(self) -> None:
        if self.player.state == PlayerState.PLAYING:
            self.player.pause()
        elif self.player.state == PlayerState.PAUSED:
            self.player.resume()
        else:
            idx = self._selected_episode_index()
            if idx is not None:
                self._start_playing(self._selected_podcast, self._episodes, idx)
            elif self._playing_index is not None:
                self._play_current()
            else:
                wx.MessageBox("Select an episode first.", "No Selection", wx.OK | wx.ICON_INFORMATION)

    def _on_stop(self) -> None:
        self.player.stop()

    def _on_previous(self) -> None:
        if self._playing_index is None:
            self.set_status("Status: No episode is playing")
            return
        new_index = self._playing_index - 1
        if new_index < 0:
            self.set_status("Status: Already at the first episode")
            return
        self._playing_index = new_index
        self._play_current()

    def _on_next(self) -> None:
        if self._playing_index is None:
            self.set_status("Status: No episode is playing")
            return
        new_index = self._playing_index + 1
        if new_index >= len(self._playing_episodes):
            self.set_status("Status: Already at the last episode")
            return
        self._playing_index = new_index
        self._play_current()

    def _on_volume_changed(self, percent: int) -> None:
        self.player.set_volume(percent / 100)
        self.config.set("podcast_volume", percent / 100)

    def _on_rate_committed(self, rate: float) -> None:
        """The Rate slider settled on a new value (drag released, or a
        keyboard step) -- applied live to the already-running BASS_FX tempo
        stream (see Player.set_rate()). No restart, no reconnect, no
        position estimate needed -- the old ffmpeg-based player had no way
        to change atempo on an already-running process, so a brief restart
        used to be the only way to make a rate change take effect."""
        if self._playing_index is not None and self.player.state in (
                PlayerState.PLAYING, PlayerState.CONNECTING, PlayerState.PAUSED):
            self.player.set_rate(rate)

    def _on_rate_changed(self, rate: float) -> None:
        self.config.set("podcast_rate", rate)

    def _on_pan_changed(self, percent: int) -> None:
        self.player.set_pan(percent / 100)
        self.config.set("podcast_pan", percent / 100)

    # ---- player event callbacks (invoked off the UI thread) -------------------

    def _on_player_state(self, state: PlayerState) -> None:
        call_after_safe(self, self.controls.set_playing, state in (PlayerState.PLAYING, PlayerState.CONNECTING))

    def _on_now_playing(self, title: str) -> None:
        pass  # podcast episode titles come from the feed, not ICY metadata

    def _on_player_error(self, message: str) -> None:
        call_after_safe(self, self.set_status, f"Status: Error — {message}")
        call_after_safe(self, self.controls.set_playing, False)

    def _on_player_finished(self) -> None:
        """The current episode reached a clean end (Player.on_finished) —
        auto-advance to the next one, same as a real podcast app."""
        call_after_safe(self, self._auto_advance)

    def _auto_advance(self) -> None:
        if self._playing_index is None:
            return
        new_index = self._playing_index + 1
        if new_index < len(self._playing_episodes):
            self._playing_index = new_index
            self._play_current()
        else:
            self.set_status("Status: Finished the last episode")

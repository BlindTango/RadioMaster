"""Main window: wx.Notebook navigation (Radio / Favourites / Podcasts).

This used to be a wx.Listbook (LB_LEFT style). Root-caused and replaced after
isolating a reliable native crash: Tab-ing focus from the Listbook's internal
navigation list into a page's first control that has a custom accessible
name (utils.accessibility.set_accessible_name) hit "Windows fatal exception:
access violation" in wx's own accessibility/focus-notification code —
reproduced in a ~15-line minimal wx.Frame, on both wxWidgets 3.2.7 and 3.3.3,
independent of anything specific to this app. The same minimal repro with a
wx.Notebook instead of wx.Listbook survived 10/10 runs, so the instability is
specific to wx.Listbook's internal control, not to set_accessible_name()
itself (which many controls throughout the app still rely on). This applies
equally to the Effects Settings notebook dialog below (effects_dialog.py) —
never reintroduce wx.Listbook anywhere in this app.

Effects, Settings, and the Recording Scheduler used to be permanent tabs on
this notebook; they're now reached on demand instead, via new "Effects" and
"Tools" menus on the menu bar (see _build_menu_bar), to keep the main window
down to just the tabs someone actually watches while a station is playing."""

from __future__ import annotations

import logging
import os
from typing import Optional

import wx

from .. import __app_name__, __version__
from ..core.custom_stations import CustomStationsStore
from ..core.effects import DISPLAY_ORDER, EFFECT_SPECS
from ..core.effects_store import EffectsPresetStore, EffectsStateStore, build_active_effect_chain
from ..core.favourites import FavouritesStore
from ..core.hotkeys import GlobalHotkeyManager
from ..core.player import Player
from ..core.podcast_subscriptions import PodcastSubscriptionsStore
from ..core.recorder import StationRecordingSession
from ..core.scheduler import RecordingScheduler, Schedule, ScheduleStore, is_nth_weekday_match
from ..core.station_api import Station, StationAPI
from ..core.station_db import StationDB
from ..core.station_update_scheduler import StationUpdateScheduler
from ..core.station_updater import StationUpdater, UpdateResult
from ..utils.config import Config
from ..utils.wx_safe import call_after_safe
from .about_dialog import AboutDialog
from .effects_dialog import EffectsSettingsDialog
from .favourites_panel import FavouritesPanel
from .help_dialog import HelpDialog
from .podcast_panel import PodcastPanel
from .radio_panel import RadioPanel
from .scheduler_panel import SchedulerDialog
from .settings_panel import SettingsDialog

log = logging.getLogger(__name__)


class MainFrame(wx.Frame):
    def __init__(self):
        w, h = (900, 680)
        super().__init__(None, title=f"{__app_name__} v{__version__}", size=(w, h))
        self.SetName(__app_name__)

        self.config = Config()

        self.station_api = StationAPI()
        self.station_db = StationDB()
        self.station_updater = StationUpdater(self.station_api, self.station_db)
        self.station_update_scheduler = StationUpdateScheduler(
            self.station_updater, on_result=self._on_station_update_result,
        )
        self.favourites = FavouritesStore()
        self.custom_stations = CustomStationsStore()
        self.podcast_subscriptions = PodcastSubscriptionsStore()
        self.player = Player(
            buffer_seconds=self.config.get("buffer_seconds", 30),
            output_device=self.config.get("output_device"),
            proxies=self._proxies(),
            ad_detection_enabled=self.config.get("ad_detection_enabled", False),
            ad_auto_mute_enabled=self.config.get("ad_auto_mute_enabled", True),
        )
        self.effects_presets = EffectsPresetStore()
        self.effects_state = EffectsStateStore()
        self.schedule_store = ScheduleStore()
        self._active_scheduled_recordings: list[StationRecordingSession] = []
        self.scheduler = RecordingScheduler(self.schedule_store, self._on_schedule_trigger)

        self.status_bar = self.CreateStatusBar(1)
        # Deliberately no custom accessible name here: wx.StatusBar exposes its
        # live SetStatusText() content via a synthetic child TextControl using
        # its OWN default (non-overridden) accessible implementation. Attaching
        # a custom wx.Accessible to the StatusBar itself suppresses that child
        # (verified via uiautomation: the live text disappeared once overridden,
        # and came back once the override was removed), so status text would
        # stop being screen-reader-visible. Leave this control's accessibility
        # untouched.
        self.status_bar.SetStatusText("Status: Starting...")

        self.listbook = wx.Notebook(self)

        self.radio_panel = RadioPanel(
            self.listbook, self.config, self.station_api, self.favourites,
            self.custom_stations, self.player, self.set_status,
            self.effects_presets, self.effects_state,
            self.station_db, self.station_updater,
        )
        self.favourites_panel = FavouritesPanel(
            self.listbook, self.favourites, self.radio_panel.play_station_object,
        )
        self.podcast_panel = PodcastPanel(
            self.listbook, self.config, self.podcast_subscriptions, self.player,
        )
        self.podcast_panel.set_proxies(self._proxies())

        self.listbook.AddPage(self.radio_panel, "📻 Radio")
        self.listbook.AddPage(self.favourites_panel, "⭐ Favourites")
        self.listbook.AddPage(self.podcast_panel, "🎙 Podcasts")

        # Radio is the default first-shown tab, so it needs to be the one
        # actually holding the shared Player's (single-slot) callbacks
        # initially — PodcastPanel claims them for itself only while its own
        # tab is the active one (see _on_page_changed below).
        self.radio_panel.bind_player_callbacks()

        self.listbook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self._on_page_changed)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._build_menu_bar()

        # Must be computed here, not earlier: GetBestSize() reflects the
        # ACTUAL content of every page now that they're all built (station
        # tree, active-recordings list, the effects checkbox rows, etc.),
        # rather than a hardcoded guess that goes stale every time a row is
        # added to any page — confirmed stale exactly like this before:
        # adding the Loudness Normalization effect row grew the Radio page's
        # real minimum past a previously-adequate hardcoded constant, and
        # every list on it started getting clipped again. SetMinSize() also
        # does NOT retroactively enforce itself against a size already
        # applied via SetSize() — a saved small window_size must be clamped
        # up to at least this before calling SetSize, or it clips too.
        #
        # Deferred via CallAfter rather than done right here: GetBestSize()
        # measured here (before app.py's Show() call ever runs) came back
        # too small — wx.ListCtrl's size metrics aren't fully realized until
        # the window has actually been shown at least once — confirmed: the
        # window itself ended up correctly sized, but every list inside it
        # was still squeezed down to a few pixels tall. Running this after
        # Show() (CallAfter fires on the next event-loop pass, by which time
        # app.py has already called Show()) gives accurate real measurements.
        call_after_safe(self, self._apply_window_size, w, h)

        self.player.set_fade(self.config.get("fade_enabled", False), self.config.get("fade_ms", 800) / 1000)

        self.hotkeys = GlobalHotkeyManager(self)
        self._register_hotkeys()

        self.scheduler.start()
        self.station_update_scheduler.start(self.config.get("station_update_frequency", "weekly"))

        if self.config.get("auto_play_last_station", False):
            call_after_safe(self, self._auto_play_last_station)

    def _apply_window_size(self, default_w: int, default_h: int) -> None:
        self.Layout()
        # RadioPanel is a ScrolledWindow that caps its own reported
        # GetBestSize() well below its actual stacked-content height (see
        # RadioPanel.GetBestSize) — content that doesn't fit scrolls inside
        # that page instead of needing the whole frame inflated to show it
        # without scrolling. That's what makes it safe to use the plain
        # best size here as the floor: no extra padding hack needed, and
        # critically, no risk of the enforced minimum exceeding a real
        # screen's usable height (confirmed that WAS happening before —
        # maximizing on a shorter screen than the enforced minimum forced
        # Windows to shrink the window below it anyway, and the sizer
        # responded by crushing several controls to 0px instead of the
        # intended "just scroll" behaviour).
        best = self.GetBestSize()
        self.SetMinSize(best)
        saved_size = self.config.get("window_size") or [default_w, default_h]
        size = [max(saved_size[0], best.width), max(saved_size[1], best.height)]
        self.SetSize(size)
        self.Layout()

    def _build_menu_bar(self) -> None:
        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        podcasts_submenu = wx.Menu()
        import_opml_item = podcasts_submenu.Append(wx.ID_ANY, "&Import OPML...", "Import podcast subscriptions from an OPML file")
        self.Bind(wx.EVT_MENU, self._on_import_opml, import_opml_item)
        export_opml_item = podcasts_submenu.Append(wx.ID_ANY, "&Export OPML...", "Export podcast subscriptions to an OPML file")
        self.Bind(wx.EVT_MENU, self._on_export_opml, export_opml_item)
        podcasts_submenu.AppendSeparator()
        add_feed_item = podcasts_submenu.Append(wx.ID_ANY, "Add &Feed...", "Subscribe to a podcast feed by URL, even if it doesn't show up in directory search")
        self.Bind(wx.EVT_MENU, self._on_add_feed, add_feed_item)
        file_menu.AppendSubMenu(podcasts_submenu, "&Podcasts")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Close RadioMaster")
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        menu_bar.Append(file_menu, "&File")

        self.effects_menu = wx.Menu()
        self._populate_effects_menu(self.effects_menu)
        menu_bar.Append(self.effects_menu, "Eff&ects")

        tools_menu = wx.Menu()
        settings_item = tools_menu.Append(wx.ID_PREFERENCES, "&Settings...", "Configure RadioMaster")
        self.Bind(wx.EVT_MENU, self._on_open_settings, settings_item)
        scheduler_item = tools_menu.Append(wx.ID_ANY, "&Recording Scheduler...", "Manage scheduled recordings")
        self.Bind(wx.EVT_MENU, self._on_open_scheduler, scheduler_item)
        menu_bar.Append(tools_menu, "&Tools")

        help_menu = wx.Menu()
        help_item = help_menu.Append(wx.ID_HELP, "&Help Contents\tF1", "How to use RadioMaster")
        self.Bind(wx.EVT_MENU, self._on_help, help_item)
        about_item = help_menu.Append(wx.ID_ABOUT, "&About RadioMaster", "Version and copyright information")
        self.Bind(wx.EVT_MENU, self._on_about, about_item)
        menu_bar.Append(help_menu, "&Help")

        self.SetMenuBar(menu_bar)
        # Rebuilds the Effects menu's checked/selected state (and its list of
        # presets) right before it's actually displayed, so it can never show
        # stale state -- whether the last change came from this menu, from
        # the Radio tab's on/off+preset box, or from the Effects Settings
        # dialog's preset CRUD.
        self.Bind(wx.EVT_MENU_OPEN, self._on_menu_open)

    def _on_menu_open(self, event: wx.MenuEvent) -> None:
        if event.GetMenu() is self.effects_menu:
            self._rebuild_effects_menu()
        event.Skip()

    @staticmethod
    def _clear_menu(menu: wx.Menu) -> None:
        for item in list(menu.GetMenuItems()):
            menu.DestroyItem(item)

    def _rebuild_effects_menu(self) -> None:
        self._clear_menu(self.effects_menu)
        self._populate_effects_menu(self.effects_menu)

    def _populate_effects_menu(self, menu: wx.Menu) -> None:
        for effect_id in DISPLAY_ORDER:
            spec = EFFECT_SPECS[effect_id]
            submenu = wx.Menu()

            on_item = submenu.AppendCheckItem(wx.ID_ANY, "&On", f"Turn {spec.display_name} on or off")
            on_item.Check(self.effects_state.is_enabled(effect_id))
            self.Bind(
                wx.EVT_MENU,
                lambda e, eid=effect_id, item=on_item: self._on_effect_toggle(eid, item),
                on_item,
            )
            submenu.AppendSeparator()

            current_preset = self.effects_state.selected_preset(effect_id)
            for name in self.effects_presets.preset_names(effect_id):
                preset_item = submenu.AppendRadioItem(wx.ID_ANY, name)
                preset_item.Check(name == current_preset)
                self.Bind(
                    wx.EVT_MENU,
                    lambda e, eid=effect_id, n=name: self._on_effect_preset_selected(eid, n),
                    preset_item,
                )
            submenu.AppendSeparator()

            settings_item = submenu.Append(wx.ID_ANY, f"{spec.display_name} &Settings...")
            self.Bind(wx.EVT_MENU, lambda e, eid=effect_id: self._open_effects_settings(eid), settings_item)

            menu.AppendSubMenu(submenu, spec.display_name)

    def _on_effect_toggle(self, effect_id: str, item: wx.MenuItem) -> None:
        self.effects_state.set_enabled(effect_id, item.IsChecked())
        self._apply_effects_chain()

    def _on_effect_preset_selected(self, effect_id: str, name: str) -> None:
        self.effects_state.set_selected_preset(effect_id, name)
        self._apply_effects_chain()

    def _apply_effects_chain(self) -> None:
        chain = build_active_effect_chain(self.effects_presets, self.effects_state)
        self.player.apply_effects(chain)
        self.radio_panel.effects_box.sync_from_store()

    def _on_import_opml(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, "Import Podcast Subscriptions (OPML)",
            wildcard="OPML files (*.opml;*.xml)|*.opml;*.xml|All files|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.podcast_panel.import_opml(dlg.GetPath())

    def _on_export_opml(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, "Export Podcast Subscriptions (OPML)",
            wildcard="OPML files (*.opml)|*.opml|All files|*.*",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            dlg.SetFilename("podcasts.opml")
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                if not os.path.splitext(path)[1]:
                    path += ".opml"
                self.podcast_panel.export_opml(path)

    def _on_add_feed(self, event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(
            self,
            "Podcast feed URL (use this for a feed that doesn't show up in directory search):",
            "Add Feed",
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.podcast_panel.add_feed_by_url(dlg.GetValue())
        dlg.Destroy()

    def _open_effects_settings(self, effect_id: Optional[str] = None) -> None:
        dlg = EffectsSettingsDialog(
            self, self.effects_presets, self.effects_state, self.player,
            initial_effect_id=effect_id,
        )
        dlg.ShowModal()
        dlg.Destroy()
        self.radio_panel.effects_box.sync_from_store()

    def _on_open_settings(self, event) -> None:
        dlg = SettingsDialog(
            self, self.config, self._on_settings_applied,
            self.station_updater, self.station_update_scheduler, self.station_db,
            on_station_db_updated=self.radio_panel.refresh_after_station_update,
        )
        dlg.ShowModal()
        dlg.Destroy()

    def _on_open_scheduler(self, event) -> None:
        dlg = SchedulerDialog(
            self, self.favourites, self.custom_stations, self.schedule_store, self.scheduler,
        )
        dlg.panel.refresh()
        dlg.ShowModal()
        dlg.Destroy()

    def _on_help(self, event) -> None:
        dlg = HelpDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_about(self, event) -> None:
        dlg = AboutDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _register_hotkeys(self) -> None:
        hotkeys = self.config.get("hotkeys", {})
        handlers = {
            "play_pause": self.radio_panel.toggle_play_pause,
            "stop": self.radio_panel.stop_playback,
            "record": self.radio_panel.toggle_record_selected,
            "volume_up": lambda: self.radio_panel.volume_step(5),
            "volume_down": lambda: self.radio_panel.volume_step(-5),
        }
        warnings = self.hotkeys.register_all(hotkeys, handlers)
        for warning in warnings:
            log.warning("Hotkey registration: %s", warning)


    def _auto_play_last_station(self) -> None:
        uuid = self.config.get("last_station_uuid")
        name = self.config.get("last_station_name")
        url = self.config.get("last_station_url")
        if url and name:
            station = Station(uuid=uuid or "", name=name, url=url)
            self.radio_panel.play_station_object(station)

    def _on_station_update_result(self, result: UpdateResult) -> None:
        if result.ok:
            call_after_safe(self, self.set_status,
                             f"Status: Station list updated ({result.changed} changed, {result.unchanged} unchanged)")
            call_after_safe(self, self.radio_panel.refresh_after_station_update)
        else:
            call_after_safe(self, self.set_status, f"Status: Station list update failed ({result.error})")

    def _proxies(self):
        if self.config.get("vpn_enabled") and self.config.get("vpn_proxy"):
            proxy = self.config.get("vpn_proxy")
            return {"http": proxy, "https": proxy}
        return None

    def set_status(self, text: str) -> None:
        self.status_bar.SetStatusText(text)

    def _on_page_changed(self, event: wx.BookCtrlEvent) -> None:
        old_page = self.listbook.GetPage(event.GetOldSelection()) if event.GetOldSelection() != wx.NOT_FOUND else None
        new_page = self.listbook.GetPage(event.GetSelection())
        if new_page is self.favourites_panel:
            self.favourites_panel.refresh()
        elif new_page is self.podcast_panel and old_page is not self.podcast_panel:
            self.podcast_panel.bind_player_callbacks()
        elif old_page is self.podcast_panel and new_page is not self.podcast_panel:
            self.radio_panel.bind_player_callbacks()
        event.Skip()

    def _on_settings_applied(self) -> None:
        self.player.set_buffer_seconds(self.config.get("buffer_seconds", 30))
        self.player.output_device = self.config.get("output_device")
        self.player.proxies = self._proxies()
        self.station_api.set_proxies(self._proxies())
        self.podcast_panel.set_proxies(self._proxies())
        self.podcast_panel.set_podcastindex_credentials(
            self.config.get("podcastindex_api_key"), self.config.get("podcastindex_api_secret"))
        self.player.set_fade(self.config.get("fade_enabled", False), self.config.get("fade_ms", 800) / 1000)
        self.player.set_ad_detection_enabled(self.config.get("ad_detection_enabled", False))
        self.player.set_ad_auto_mute_enabled(self.config.get("ad_auto_mute_enabled", True))
        self._register_hotkeys()

    def _on_schedule_trigger(self, sched: Schedule) -> None:
        if sched.schedule_type == "nth_weekday" and not is_nth_weekday_match(sched):
            return

        def worker():
            runner = StationRecordingSession(
                station_name=sched.station_name, station_url=sched.station_url,
                duration_minutes=sched.duration_minutes, fmt=sched.output_format,
                use_deezer=self.config.get("metadata_deezer_enabled", True),
                use_musicbrainz=self.config.get("metadata_musicbrainz_enabled", True),
                proxies=self._proxies(),
                min_track_seconds=self.config.get("min_track_seconds", 30),
                acoustid_api_key=self.config.get("acoustid_api_key"),
            )
            self._active_scheduled_recordings.append(runner)
            runner.start()
            call_after_safe(self, self.set_status, f"Status: Recording scheduled: {sched.station_name}")

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self.config.set("window_size", list(self.GetSize()), save=False)
        try:
            self.config.save()
        except Exception:
            log.exception("Failed to save config on close")
        try:
            self.hotkeys.unregister_all()
        except Exception:
            pass
        try:
            self.scheduler.shutdown()
        except Exception:
            pass
        try:
            self.station_update_scheduler.shutdown()
        except Exception:
            pass
        for runner in self._active_scheduled_recordings:
            try:
                runner.stop()
            except Exception:
                pass
        try:
            self.radio_panel.stop_all_recordings()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        event.Skip()

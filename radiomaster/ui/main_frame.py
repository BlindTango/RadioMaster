"""Main window: wx.Notebook navigation (Radio / Favourites / Scheduler / Settings).

This used to be a wx.Listbook (LB_LEFT style). Root-caused and replaced after
isolating a reliable native crash: Tab-ing focus from the Listbook's internal
navigation list into a page's first control that has a custom accessible
name (utils.accessibility.set_accessible_name) hit "Windows fatal exception:
access violation" in wx's own accessibility/focus-notification code —
reproduced in a ~15-line minimal wx.Frame, on both wxWidgets 3.2.7 and 3.3.3,
independent of anything specific to this app. The same minimal repro with a
wx.Notebook instead of wx.Listbook survived 10/10 runs, so the instability is
specific to wx.Listbook's internal control, not to set_accessible_name()
itself (which many controls throughout the app still rely on)."""

from __future__ import annotations

import logging

import wx

from .. import __app_name__, __version__
from ..core.custom_stations import CustomStationsStore
from ..core.effects_store import EffectsPresetStore, EffectsStateStore
from ..core.favourites import FavouritesStore
from ..core.hotkeys import GlobalHotkeyManager
from ..core.player import Player
from ..core.recorder import StationRecordingSession
from ..core.scheduler import RecordingScheduler, Schedule, ScheduleStore, is_nth_weekday_match
from ..core.station_api import Station, StationAPI
from ..core.station_db import StationDB
from ..core.station_update_scheduler import StationUpdateScheduler
from ..core.station_updater import StationUpdater, UpdateResult
from ..utils.config import Config
from ..utils.wx_safe import call_after_safe
from .about_dialog import AboutDialog
from .effects_panel import EffectsPanel
from .favourites_panel import FavouritesPanel
from .help_dialog import HelpDialog
from .radio_panel import RadioPanel
from .scheduler_panel import SchedulerPanel
from .settings_panel import SettingsPanel

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
        self.player = Player(
            buffer_seconds=self.config.get("buffer_seconds", 30),
            output_device=self.config.get("output_device"),
            proxies=self._proxies(),
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
        self.scheduler_panel = SchedulerPanel(
            self.listbook, self.favourites, self.custom_stations, self.schedule_store, self.scheduler,
        )
        self.effects_panel = EffectsPanel(
            self.listbook, self.effects_presets, self.radio_panel.effects_box.refresh_all_presets,
        )
        self.settings_panel = SettingsPanel(
            self.listbook, self.config, self._on_settings_applied,
            self.station_updater, self.station_update_scheduler, self.station_db,
            on_station_db_updated=self.radio_panel.refresh_after_station_update,
        )

        self.listbook.AddPage(self.radio_panel, "📻 Radio")
        self.listbook.AddPage(self.favourites_panel, "⭐ Favourites")
        self.listbook.AddPage(self.scheduler_panel, "📅 Scheduler")
        self.listbook.AddPage(self.effects_panel, "🎚 Effects")
        self.listbook.AddPage(self.settings_panel, "⚙ Settings")

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
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4", "Close RadioMaster")
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), exit_item)
        menu_bar.Append(file_menu, "&File")

        help_menu = wx.Menu()
        help_item = help_menu.Append(wx.ID_HELP, "&Help Contents\tF1", "How to use RadioMaster")
        self.Bind(wx.EVT_MENU, self._on_help, help_item)
        about_item = help_menu.Append(wx.ID_ABOUT, "&About RadioMaster", "Version and copyright information")
        self.Bind(wx.EVT_MENU, self._on_about, about_item)
        menu_bar.Append(help_menu, "&Help")

        self.SetMenuBar(menu_bar)

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
        if self.listbook.GetPage(event.GetSelection()) is self.favourites_panel:
            self.favourites_panel.refresh()
        elif self.listbook.GetPage(event.GetSelection()) is self.scheduler_panel:
            self.scheduler_panel.refresh()
        event.Skip()

    def _on_settings_applied(self) -> None:
        self.player.set_buffer_seconds(self.config.get("buffer_seconds", 30))
        self.player.output_device = self.config.get("output_device")
        self.player.proxies = self._proxies()
        self.station_api.set_proxies(self._proxies())
        self.player.set_fade(self.config.get("fade_enabled", False), self.config.get("fade_ms", 800) / 1000)
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

"""Settings page: soundcard, buffer size, VPN, FFmpeg path, metadata sources, recording format, theme, language."""

from __future__ import annotations

import wx
import wx.lib.scrolledpanel as scrolled

from ..core.soundcard import list_output_devices
from ..core.station_db import StationDB
from ..core.station_update_scheduler import FREQUENCIES, FREQUENCY_LABELS, StationUpdateScheduler
from ..core.station_updater import StationUpdater
from ..utils.accessibility import accessible_label
from ..utils.config import Config
from ..utils.ffmpeg import find_ffmpeg
from ..utils.fingerprint import find_fpcalc
from ..utils.wx_safe import call_after_safe
from ..utils.logging_setup import LEVELS as LOG_LEVELS, set_level as set_log_level
from .hotkeys_dialog import HotkeysDialog
from .scheduler_panel import FORMATS


def _fpcalc_available() -> bool:
    return find_fpcalc() is not None

THEMES = ["default", "high-contrast", "large-text"]
LANGUAGES = ["en"]


class SettingsPanel(scrolled.ScrolledPanel):
    """A ScrolledPanel, not a plain Panel: ~20 stacked rows (soundcard,
    buffer, VPN, FFmpeg, metadata, recording, theme, station DB, playback,
    hotkeys, log level) with no flexible/proportion=1 items at all — a
    container forced shorter than the sum of every row's height doesn't
    just look cramped, it compresses ALL of them below their own declared
    minimums, several straight to 0px (confirmed: reproduced by maximizing
    onto a screen shorter than this page's natural ~700px content height —
    8 controls measured 0-5px tall). Scrolling makes anything that doesn't
    fit reachable instead of vanishing — same fix as RadioPanel."""

    # Same reasoning/target as RadioPanel._MAX_REPORTED_HEIGHT: caps what
    # this page asks the frame to grow to, so a real screen shorter than
    # the page's true content height gets scrolling instead of an
    # over-tall frame (or, without this cap, the frame would still be
    # forced taller than the screen to avoid scrolling here).
    _MAX_REPORTED_HEIGHT = 640

    def __init__(self, parent, config: Config, on_apply=None,
                 station_updater: StationUpdater = None,
                 station_update_scheduler: StationUpdateScheduler = None,
                 station_db: StationDB = None, on_station_db_updated=None):
        super().__init__(parent)
        self.config = config
        self.on_apply = on_apply
        self.station_updater = station_updater
        self.station_update_scheduler = station_update_scheduler
        self.station_db = station_db
        self.on_station_db_updated = on_station_db_updated

        self.devices = list_output_devices()
        device_names = ["(System Default)"] + [d.name for d in self.devices]
        accessible_label(self, "Soundcard")
        self.device_choice = wx.Choice(self, choices=device_names)

        accessible_label(self, "Stream buffer size in seconds")
        self.buffer_ctrl = wx.SpinCtrl(self, min=10, max=300, initial=config.get("buffer_seconds", 30))

        self.vpn_enabled_check = wx.CheckBox(self, label="Route traffic through a &proxy (VPN)")
        accessible_label(self, "Proxy URL")
        self.vpn_proxy_ctrl = wx.TextCtrl(self, value=config.get("vpn_proxy") or "")
        self.vpn_proxy_ctrl.SetHint("e.g. socks5://127.0.0.1:1080")

        accessible_label(self, "FFmpeg path override")
        self.ffmpeg_path_ctrl = wx.TextCtrl(self, value=config.get("ffmpeg_path") or "")
        self.ffmpeg_browse_btn = wx.Button(self, label="&Browse...")
        detected = find_ffmpeg() or "(not found)"
        self.ffmpeg_detected_label = wx.StaticText(self, label=f"Detected: {detected}")

        self.deezer_check = wx.CheckBox(self, label="&Deezer (primary)")
        self.deezer_check.SetValue(config.get("metadata_deezer_enabled", True))
        self.musicbrainz_check = wx.CheckBox(self, label="&MusicBrainz (secondary)")
        self.musicbrainz_check.SetValue(config.get("metadata_musicbrainz_enabled", True))

        accessible_label(self, "AcoustID API key")
        self.acoustid_key_ctrl = wx.TextCtrl(self, value=config.get("acoustid_api_key") or "")
        self.acoustid_key_ctrl.SetHint("Free key from acoustid.org — used only when Deezer/MusicBrainz text search fails")
        fpcalc_status = "found" if _fpcalc_available() else "not found (recording will skip fingerprint ID)"
        self.acoustid_status_label = wx.StaticText(self, label=f"fpcalc: {fpcalc_status}")

        accessible_label(self, "Podcast Index API key")
        self.podcastindex_key_ctrl = wx.TextCtrl(self, value=config.get("podcastindex_api_key") or "")
        self.podcastindex_key_ctrl.SetHint("Optional — free key from podcastindex.org, adds a second podcast search directory")
        accessible_label(self, "Podcast Index API secret")
        self.podcastindex_secret_ctrl = wx.TextCtrl(self, value=config.get("podcastindex_api_secret") or "", style=wx.TE_PASSWORD)

        accessible_label(self, "Default recording format")
        self.format_choice = wx.Choice(self, choices=FORMATS)
        current_fmt = config.get("recording_format", "mp3")
        self.format_choice.SetSelection(FORMATS.index(current_fmt) if current_fmt in FORMATS else 0)

        accessible_label(self, "Minimum track length to keep when recording, in seconds")
        self.min_track_seconds_ctrl = wx.SpinCtrl(self, min=0, max=600, initial=config.get("min_track_seconds", 30))

        accessible_label(self, "Theme")
        self.theme_choice = wx.Choice(self, choices=THEMES)
        theme = config.get("theme", "default")
        self.theme_choice.SetSelection(THEMES.index(theme) if theme in THEMES else 0)

        accessible_label(self, "UI language")
        self.language_choice = wx.Choice(self, choices=LANGUAGES)
        self.language_choice.SetSelection(0)

        accessible_label(self, "Station list update frequency")
        self.update_freq_choice = wx.Choice(self, choices=[FREQUENCY_LABELS[f] for f in FREQUENCIES])
        current_freq = config.get("station_update_frequency", "weekly")
        self.update_freq_choice.SetSelection(
            FREQUENCIES.index(current_freq) if current_freq in FREQUENCIES else FREQUENCIES.index("weekly"))

        self.update_now_btn = wx.Button(self, label="Update Station List &Now")
        self.update_progress = wx.Gauge(self, range=100)
        self.update_progress.Hide()
        self.station_db_status_label = wx.StaticText(self, label="")
        self._refresh_station_db_status()

        accessible_label(self, "Log level")
        self.log_level_choice = wx.Choice(self, choices=[l.title() for l in LOG_LEVELS])
        current_log_level = config.get("log_level", "info")
        self.log_level_choice.SetSelection(
            LOG_LEVELS.index(current_log_level) if current_log_level in LOG_LEVELS else LOG_LEVELS.index("info"))

        self.auto_play_check = wx.CheckBox(self, label="&Play the last station automatically on startup")
        self.auto_play_check.SetValue(config.get("auto_play_last_station", False))

        self.fade_check = wx.CheckBox(self, label="&Fade audio in/out when switching stations")
        self.fade_check.SetValue(config.get("fade_enabled", False))
        accessible_label(self, "Fade duration in milliseconds")
        self.fade_ms_ctrl = wx.SpinCtrl(self, min=100, max=5000, initial=config.get("fade_ms", 800))

        self.mute_while_recording_check = wx.CheckBox(
            self, label="&Mute live playback while recording (recording is unaffected)")
        self.mute_while_recording_check.SetValue(config.get("mute_playback_while_recording", False))

        self.ad_detection_check = wx.CheckBox(
            self, label="Detect and flag likely &advertisement breaks (experimental)")
        self.ad_detection_check.SetValue(config.get("ad_detection_enabled", False))
        self.ad_auto_mute_check = wx.CheckBox(
            self, label="Automatically m&ute audio during a detected ad break")
        self.ad_auto_mute_check.SetValue(config.get("ad_auto_mute_enabled", True))

        self.hotkeys_btn = wx.Button(self, label="Configure &Global Hotkeys...")

        self.apply_btn = wx.Button(self, label="&Apply")

        def row(label_text, ctrl, extra=None):
            r = wx.BoxSizer(wx.HORIZONTAL)
            r.Add(wx.StaticText(self, label=label_text), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            r.Add(ctrl, 1, wx.EXPAND | wx.RIGHT, 6)
            if extra:
                r.Add(extra, 0)
            return r

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(row("&Soundcard:", self.device_choice), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("&Buffer (seconds):", self.buffer_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.vpn_enabled_check, 0, wx.ALL, 6)
        outer.Add(row("Proxy &URL:", self.vpn_proxy_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("FF&mpeg path:", self.ffmpeg_path_ctrl, self.ffmpeg_browse_btn), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.ffmpeg_detected_label, 0, wx.LEFT, 10)
        outer.Add(wx.StaticText(self, label="Metadata sources:"), 0, wx.LEFT | wx.TOP, 6)
        outer.Add(self.deezer_check, 0, wx.LEFT, 10)
        outer.Add(self.musicbrainz_check, 0, wx.LEFT, 10)
        outer.Add(row("Ac&oustID API key:", self.acoustid_key_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.acoustid_status_label, 0, wx.LEFT, 10)
        outer.Add(row("Podcast &Index API key:", self.podcastindex_key_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("Podcast Index API &secret:", self.podcastindex_secret_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("Recording &format:", self.format_choice), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("&Min. track length (seconds):", self.min_track_seconds_ctrl), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("&Theme:", self.theme_choice), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(row("&Language:", self.language_choice), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(wx.StaticText(self, label="Station Database:"), 0, wx.LEFT | wx.TOP, 6)
        outer.Add(row("&Update frequency:", self.update_freq_choice, self.update_now_btn), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.update_progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.station_db_status_label, 0, wx.LEFT, 10)
        outer.Add(wx.StaticText(self, label="Playback:"), 0, wx.LEFT | wx.TOP, 6)
        outer.Add(self.auto_play_check, 0, wx.LEFT, 10)
        outer.Add(self.fade_check, 0, wx.LEFT, 10)
        outer.Add(row("Fade duration (&ms):", self.fade_ms_ctrl), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        outer.Add(self.mute_while_recording_check, 0, wx.LEFT, 10)
        outer.Add(self.ad_detection_check, 0, wx.LEFT, 10)
        outer.Add(self.ad_auto_mute_check, 0, wx.LEFT, 10)
        outer.Add(self.hotkeys_btn, 0, wx.ALL, 6)
        outer.Add(row("Log &level:", self.log_level_choice), 0, wx.EXPAND | wx.ALL, 6)
        outer.Add(self.apply_btn, 0, wx.ALL, 10)
        self.SetSizer(outer)
        self.SetupScrolling(scroll_x=False, scroll_y=True)

        saved_device = config.get("output_device")
        if saved_device is not None:
            for i, d in enumerate(self.devices):
                if d.index == saved_device:
                    self.device_choice.SetSelection(i + 1)
                    break
        else:
            self.device_choice.SetSelection(0)

        self.vpn_enabled_check.SetValue(config.get("vpn_enabled", False))

        self.apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)
        self.ffmpeg_browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_ffmpeg)
        self.update_now_btn.Bind(wx.EVT_BUTTON, self._on_update_now)
        self.hotkeys_btn.Bind(wx.EVT_BUTTON, self._on_configure_hotkeys)

    def GetBestSize(self) -> wx.Size:
        # See RadioPanel.GetBestSize for why this is capped rather than
        # reporting the true ~700px content height.
        natural = self.GetSizer().CalcMin() if self.GetSizer() else wx.Size(400, 500)
        return wx.Size(natural.width, min(natural.height, self._MAX_REPORTED_HEIGHT))

    def _on_configure_hotkeys(self, event: wx.CommandEvent) -> None:
        dlg = HotkeysDialog(self, self.config)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_browse_ffmpeg(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(self, "Select ffmpeg executable", wildcard="ffmpeg.exe|ffmpeg.exe|All files|*.*") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.ffmpeg_path_ctrl.SetValue(dlg.GetPath())

    def _refresh_station_db_status(self) -> None:
        if not self.station_db:
            return
        count = self.station_db.station_count()
        last = self.station_db.last_updated()
        last_text = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        self.station_db_status_label.SetLabel(f"{count} stations cached — last updated: {last_text}")

    def _on_update_now(self, event: wx.CommandEvent) -> None:
        if not self.station_updater:
            return
        self.update_now_btn.Disable()
        self.update_now_btn.SetLabel("Updating...")
        self.update_progress.SetValue(0)
        self.update_progress.Show()
        self.Layout()

        def progress_cb(bytes_read: int, total) -> None:
            call_after_safe(self, self._on_update_progress, bytes_read, total)

        def worker():
            result = self.station_updater.update_now(progress_cb=progress_cb)
            call_after_safe(self, self._on_update_done, result)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_progress(self, bytes_read: int, total) -> None:
        if total:
            self.update_progress.SetValue(min(100, int(bytes_read * 100 / total)))
        else:
            # No Content-Length from the server — can't show a real
            # percentage, so keep the bar moving to show it's still busy
            # rather than looking stuck at 0.
            self.update_progress.Pulse()

    def _on_update_done(self, result) -> None:
        self.update_now_btn.Enable()
        self.update_now_btn.SetLabel("Update Station List &Now")
        self.update_progress.Hide()
        self.Layout()
        self._refresh_station_db_status()
        if result.ok and self.on_station_db_updated:
            self.on_station_db_updated()
        if result.ok:
            wx.MessageBox(
                f"Station list updated: {result.changed} changed, {result.unchanged} unchanged "
                f"(of {result.total_fetched} fetched).",
                "Station List Updated", wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(f"Update failed: {result.error}", "Update Failed", wx.OK | wx.ICON_ERROR)

    def _on_apply(self, event: wx.CommandEvent) -> None:
        idx = self.device_choice.GetSelection()
        device_index = None if idx <= 0 else self.devices[idx - 1].index
        self.config.set("output_device", device_index, save=False)
        self.config.set("buffer_seconds", self.buffer_ctrl.GetValue(), save=False)
        self.config.set("vpn_enabled", self.vpn_enabled_check.GetValue(), save=False)
        self.config.set("vpn_proxy", self.vpn_proxy_ctrl.GetValue().strip() or None, save=False)
        self.config.set("ffmpeg_path", self.ffmpeg_path_ctrl.GetValue().strip() or None, save=False)
        self.config.set("metadata_deezer_enabled", self.deezer_check.GetValue(), save=False)
        self.config.set("metadata_musicbrainz_enabled", self.musicbrainz_check.GetValue(), save=False)
        self.config.set("acoustid_api_key", self.acoustid_key_ctrl.GetValue().strip() or None, save=False)
        self.config.set("podcastindex_api_key", self.podcastindex_key_ctrl.GetValue().strip() or None, save=False)
        self.config.set("podcastindex_api_secret", self.podcastindex_secret_ctrl.GetValue().strip() or None, save=False)
        self.config.set("recording_format", FORMATS[self.format_choice.GetSelection()], save=False)
        self.config.set("min_track_seconds", self.min_track_seconds_ctrl.GetValue(), save=False)
        self.config.set("theme", THEMES[self.theme_choice.GetSelection()], save=False)
        self.config.set("language", LANGUAGES[self.language_choice.GetSelection()], save=False)
        new_freq = FREQUENCIES[self.update_freq_choice.GetSelection()]
        self.config.set("station_update_frequency", new_freq)
        if self.station_update_scheduler:
            self.station_update_scheduler.set_frequency(new_freq)

        self.config.set("auto_play_last_station", self.auto_play_check.GetValue(), save=False)
        self.config.set("fade_enabled", self.fade_check.GetValue(), save=False)
        self.config.set("fade_ms", self.fade_ms_ctrl.GetValue(), save=False)
        self.config.set("mute_playback_while_recording", self.mute_while_recording_check.GetValue(), save=False)
        self.config.set("ad_detection_enabled", self.ad_detection_check.GetValue(), save=False)
        self.config.set("ad_auto_mute_enabled", self.ad_auto_mute_check.GetValue(), save=False)
        new_log_level = LOG_LEVELS[self.log_level_choice.GetSelection()]
        self.config.set("log_level", new_log_level, save=False)
        set_log_level(new_log_level)

        # Everything above this point used save=False to avoid writing to
        # disk once per field — flush once here. Without this, these settings
        # only reached disk when the app later closed cleanly via _on_close();
        # if it crashed first (confirmed happening — see CrashDumps) they were
        # silently lost even though "Apply" had already been clicked.
        self.config.save()

        if self.on_apply:
            self.on_apply()
        wx.MessageBox("Settings applied.", "Settings", wx.OK | wx.ICON_INFORMATION)

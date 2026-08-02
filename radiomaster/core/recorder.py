"""Stream recording with automatic per-track splitting.

A recording session runs from start() to stop(). Whenever the station's ICY
"now playing" title changes, the in-progress segment is finalized as its own
file and a new segment begins for the next track — so "Record" produces one
file per song, not one giant file per session. Segments shorter than
`min_track_seconds` (jingles/station IDs/ads are almost always <=30s) are
discarded rather than saved. Each finalized track is named and ID3-tagged
from resolved metadata (Deezer -> MusicBrainz -> AcoustID fingerprint ->
raw ICY text, in that order — see core.metadata.get_track_info).

Stations with no ICY metadata support never see a title change, so the whole
session is naturally recorded as a single segment (the pre-existing behaviour).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from ..utils.ffmpeg import find_ffmpeg
from ..utils.fingerprint import find_fpcalc
from ..utils.paths import recordings_dir
from .geo_check import log_if_geo_restricted
from .icy import icy_metadata_loop
from .metadata import TrackInfo, get_track_info
from .tagger import tag_file
from .player import SAMPLE_RATE, CHANNELS, CREATE_NO_WINDOW

log = logging.getLogger(__name__)

_ENCODER_ARGS = {
    "mp3": (["-acodec", "libmp3lame", "-q:a", "2"], "mp3"),
    "aac": (["-acodec", "aac", "-b:a", "192k"], "m4a"),
    "flac": (["-acodec", "flac"], "flac"),
    "ogg": (["-acodec", "libvorbis", "-q:a", "5"], "ogg"),
    "wav": (["-acodec", "pcm_s16le"], "wav"),
}

DEFAULT_MIN_TRACK_SECONDS = 30


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return name or "Unknown"


class StationRecordingSession:
    """Headless station -> ffmpeg decode -> Recorder pipeline, independent of playback.

    Used for both scheduler-triggered recordings and ad-hoc manual recordings
    started from the Radio page. Because it opens its own decode subprocess
    (no shared audio output device), any number of these can run concurrently
    for different stations while the user listens to a completely different
    station through the live Player — recording never taps or depends on
    what's currently playing. Runs its own ICY poller so every session gets
    the same per-track splitting and ad-skip as any other recording.
    """

    DEFAULT_UNTIL_STOP_MINUTES = 240

    def __init__(self, station_name: str, station_url: str, duration_minutes: Optional[int],
                 fmt: str = "mp3", use_deezer: bool = True, use_musicbrainz: bool = True,
                 proxies: Optional[dict] = None, ffmpeg_path: Optional[str] = None,
                 min_track_seconds: int = DEFAULT_MIN_TRACK_SECONDS,
                 acoustid_api_key: Optional[str] = None):
        self.station_name = station_name
        self.station_url = station_url
        self.duration_minutes = duration_minutes or self.DEFAULT_UNTIL_STOP_MINUTES
        self.recorder = Recorder(
            station_name, fmt=fmt, ffmpeg_path=ffmpeg_path,
            use_deezer=use_deezer, use_musicbrainz=use_musicbrainz, proxies=proxies,
            min_track_seconds=min_track_seconds, acoustid_api_key=acoustid_api_key,
        )
        self._ffmpeg = ffmpeg_path or find_ffmpeg()
        self._decode_proc: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._icy_thread: Optional[threading.Thread] = None
        self._proxies = proxies
        self.started_at: Optional[float] = None

    @property
    def is_active(self) -> bool:
        return self.recorder.is_recording

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at if self.started_at else 0.0

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.recorder.start()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._icy_thread = threading.Thread(
            target=icy_metadata_loop,
            args=(self.station_url, self._proxies, self._stop_event, self.recorder.update_now_playing),
            daemon=True,
        )
        self._icy_thread.start()

    def stop(self) -> str:
        self._stop_event.set()
        if self._decode_proc is not None:
            try:
                self._decode_proc.kill()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        return self.recorder.stop() if self.recorder.is_recording else ""

    def _run(self) -> None:
        if not self._ffmpeg:
            log.error("FFmpeg not found; scheduled recording of %s aborted", self.station_name)
            self.recorder.stop()
            return
        cmd = [
            self._ffmpeg, "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", self.station_url,
            "-vn", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
            "pipe:1",
        ]
        try:
            self._decode_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except OSError:
            log.exception("Failed to launch FFmpeg for scheduled recording")
            self.recorder.stop()
            return

        deadline = time.monotonic() + self.duration_minutes * 60
        ended_early = False
        try:
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                chunk = self._decode_proc.stdout.read(8192)
                if not chunk:
                    ended_early = not self._stop_event.is_set()
                    break
                self.recorder.feed(chunk)
        finally:
            try:
                self._decode_proc.kill()
            except Exception:
                pass
            self.recorder.stop()
            if ended_early:
                threading.Thread(
                    target=log_if_geo_restricted, args=(self.station_name, self.station_url, self._proxies),
                    daemon=True).start()


class Recorder:
    """Started/stopped independently of playback; fed raw PCM chunks by the Player's read loop.

    Automatically splits into one output file per track (see module docstring).
    """

    def __init__(self, station_name: str, fmt: str = "mp3",
                 ffmpeg_path: Optional[str] = None,
                 use_deezer: bool = True, use_musicbrainz: bool = True,
                 proxies: Optional[dict] = None,
                 min_track_seconds: int = DEFAULT_MIN_TRACK_SECONDS,
                 acoustid_api_key: Optional[str] = None, fpcalc_path: Optional[str] = None,
                 on_track_saved: Optional[Callable[[str], None]] = None,
                 on_track_discarded: Optional[Callable[[str, float], None]] = None):
        self.station_name = station_name
        self.fmt = fmt.lower() if fmt.lower() in _ENCODER_ARGS else "mp3"
        self._ffmpeg = ffmpeg_path or find_ffmpeg()
        self.use_deezer = use_deezer
        self.use_musicbrainz = use_musicbrainz
        self.proxies = proxies
        self.min_track_seconds = min_track_seconds
        self.acoustid_api_key = acoustid_api_key
        self.fpcalc_path = fpcalc_path or find_fpcalc()
        self.on_track_saved = on_track_saved
        self.on_track_discarded = on_track_discarded

        self._proc: Optional[subprocess.Popen] = None
        self._temp_path = ""
        self._lock = threading.Lock()
        self._segment_title = ""      # ICY title active when the current segment began
        self._pending_title = ""      # latest ICY title seen, may differ from _segment_title
        self._segment_started_at = 0.0
        self._last_final_path = ""
        self.is_recording = False
        self._split_timer: Optional[threading.Timer] = None

    # ---- session control -------------------------------------------------

    def start(self) -> None:
        if not self._ffmpeg:
            raise RuntimeError("FFmpeg not found; cannot record.")
        self.is_recording = True
        self._begin_segment(self._pending_title)

    def stop(self) -> str:
        """Finalize whatever segment is in progress and end the session."""
        if self._split_timer is not None:
            self._split_timer.cancel()
            self._split_timer = None
        if not self.is_recording:
            return self._last_final_path
        self.is_recording = False
        self._finalize_segment(self._segment_title)
        return self._last_final_path

    def feed(self, chunk: bytes) -> None:
        if not self.is_recording or self._proc is None or self._proc.stdin is None:
            return
        with self._lock:
            try:
                self._proc.stdin.write(chunk)
            except (BrokenPipeError, OSError):
                pass

    # FFmpeg's decode pipeline buffers/analyzes some audio before it starts
    # producing decoded output, so a title change is seen on the raw ICY
    # metadata connection a bit BEFORE the matching audio actually reaches
    # feed() — splitting immediately cut the boundary too early, gluing the
    # tail of the outgoing track (sometimes including part of an ad break
    # right after it) onto the start of the next file. Settling for a short
    # delay before actually acting on the change lets the decode pipeline
    # catch up first, so the split lands much closer to the true boundary.
    _SPLIT_SETTLE_SECONDS = 2.0

    def update_now_playing(self, text: str) -> None:
        """Call whenever the station's ICY title changes (splits into a new track)."""
        self._pending_title = text
        if not self.is_recording:
            return
        if text == self._segment_title:
            return
        if self._split_timer is not None:
            self._split_timer.cancel()
        self._split_timer = threading.Timer(self._SPLIT_SETTLE_SECONDS, self._apply_split, args=(text,))
        self._split_timer.daemon = True
        self._split_timer.start()

    def _apply_split(self, text: str) -> None:
        # Superseded by a later title change, or the session stopped, while
        # this was settling — either way, someone else has already handled
        # (or will handle) the actual split.
        if not self.is_recording or text != self._pending_title:
            return
        self._finalize_segment(self._segment_title)
        self._begin_segment(text)

    # ---- segment lifecycle -------------------------------------------------

    def _begin_segment(self, title: str) -> None:
        extra_args, ext = _ENCODER_ARGS[self.fmt]
        stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        out_dir = recordings_dir(_safe_filename(self.station_name))
        self._temp_path = os.path.join(out_dir, f"_recording_{stamp}.{ext}")

        cmd = [
            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS),
            "-i", "pipe:0",
            *extra_args,
            self._temp_path,
        ]
        with self._lock:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        self._segment_title = title
        self._segment_started_at = time.monotonic()

    def _finalize_segment(self, title_for_segment: str) -> None:
        duration = time.monotonic() - self._segment_started_at
        temp_path = self._temp_path

        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if duration <= self.min_track_seconds:
            # Almost certainly a station ID, jingle, or ad break — discard.
            try:
                os.remove(temp_path)
            except OSError:
                pass
            log.info("Discarded %.1fs segment (<=%ss threshold): %s",
                      duration, self.min_track_seconds, title_for_segment or "(untitled)")
            # A near-zero-length placeholder segment (before the first real ICY
            # title arrived) is bookkeeping noise, not a meaningful skip — don't
            # surface it to the UI.
            if self.on_track_discarded and duration >= 1.0:
                self.on_track_discarded(title_for_segment, duration)
            return

        info = get_track_info(
            title_for_segment, use_deezer=self.use_deezer, use_musicbrainz=self.use_musicbrainz,
            proxies=self.proxies, acoustid_filepath=temp_path,
            acoustid_api_key=self.acoustid_api_key, fpcalc_path=self.fpcalc_path,
        )

        ext = temp_path.rsplit(".", 1)[-1]
        out_dir = os.path.dirname(temp_path)
        if info.title:
            base = f"{_safe_filename(info.artist or 'Unknown')} - {_safe_filename(info.title)}"
        else:
            stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            base = f"{_safe_filename(self.station_name)} - {stamp}"

        final_path = os.path.join(out_dir, f"{base}.{ext}")
        counter = 1
        while os.path.exists(final_path) and final_path != temp_path:
            final_path = os.path.join(out_dir, f"{base} ({counter}).{ext}")
            counter += 1

        # ffmpeg.exe process exit (proc.wait() above) doesn't guarantee Windows
        # has released its handle on the output file yet -- antivirus/indexer
        # scans of a freshly-written media file are a common extra holder, too.
        # An immediate os.replace() can hit "file in use" (WinError 32) in that
        # window even though nothing is actually still writing to it, silently
        # leaving the file stuck under its temp "_recording_..." name forever.
        # Retry briefly before giving up.
        for attempt in range(5):
            try:
                os.replace(temp_path, final_path)
                break
            except OSError:
                if attempt == 4:
                    log.exception("Could not rename recording %s -> %s", temp_path, final_path)
                    final_path = temp_path
                else:
                    time.sleep(0.2 * (attempt + 1))

        if info.title:
            tag_file(final_path, info, self.station_name, self.fmt, proxies=self.proxies)

        self._last_final_path = final_path
        if self.on_track_saved:
            self.on_track_saved(final_path)

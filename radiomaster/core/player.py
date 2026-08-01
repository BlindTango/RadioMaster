"""Custom FFmpeg-based streaming audio player (no VLC dependency).

Pipeline: HTTP stream -> ffmpeg subprocess (decode to raw PCM) -> ring buffer
-> sounddevice output callback. A parallel ICY metadata poller extracts the
current track title.

Recording is entirely independent of this class — see
core.recorder.StationRecordingSession, which opens its own headless decode
pipeline per station. That means any number of stations can record
concurrently while this Player plays a completely different (or the same)
station through the speakers.
"""

from __future__ import annotations

import enum
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import sounddevice as sd

from ..utils.ffmpeg import find_ffmpeg, find_ffprobe
from .geo_check import log_if_geo_restricted
from .icy import icy_metadata_loop
from .stream_buffer import StreamBuffer

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2  # int16
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH

CREATE_NO_WINDOW = 0x08000000  # avoid flashing a console window on Windows


class PlayerState(enum.Enum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    PLAYING = "playing"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class StreamInfo:
    codec: str = ""
    bitrate_kbps: int = 0
    sample_rate: int = 0


class Player:
    """One station at a time; call stop() before start()-ing a new one."""

    def __init__(self, buffer_seconds: int = 30, output_device: Optional[int] = None,
                 proxies: Optional[dict] = None, ffmpeg_path: Optional[str] = None,
                 ffprobe_path: Optional[str] = None):
        self.buffer_seconds = buffer_seconds
        self.output_device = output_device
        self.proxies = proxies
        self._ffmpeg = ffmpeg_path
        self._ffprobe = ffprobe_path

        self.state = PlayerState.STOPPED
        self.muted = False
        self.volume = 1.0
        self.pan = 0.5  # 0.0 = full left, 0.5 = centre, 1.0 = full right
        self.stream_info = StreamInfo()
        self.now_playing_title = ""
        self.url = ""
        self.station_name = ""
        self.effects_chain = ""
        self.fade_enabled = False
        self.fade_seconds = 0.8
        self._fade_gain = 1.0

        self._buffer: Optional[StreamBuffer] = None
        self._proc: Optional[subprocess.Popen] = None
        self._out_stream: Optional[sd.OutputStream] = None
        # Guards every read/construct/start/stop/close/assign touching
        # _out_stream. Without it, stop() and the priming thread opening the
        # device can interleave mid-construction (sd.OutputStream() assigns
        # self._out_stream before .start() actually finishes) — confirmed via
        # tracing: stop() would see the half-constructed stream as "not
        # None", call .stop()/.close() on it while the other thread was still
        # calling .start(), and end up with a live, leaked device anyway.
        self._out_stream_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._icy_thread: Optional[threading.Thread] = None
        self._probe_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        # Bumped every time the decode subprocess is deliberately replaced
        # (see apply_effects()/_restart_decode_only()), so a reader thread
        # whose process was killed on purpose can tell the difference from a
        # genuine dropped connection and skip firing on_error/_fail().
        self._decode_generation = 0
        # Bumped only on an actual station change (cold start / gapless
        # switch) — deliberately NOT bumped by _restart_decode_only()
        # (effect toggles), which replaces the decode process but keeps
        # listening to the SAME station's metadata connection. Used to
        # detect stale ICY callbacks from a superseded station; using
        # _decode_generation for that instead would wrongly discard valid
        # metadata updates every time an effect was toggled.
        self._station_generation = 0
        # Signals the CURRENT icy_metadata_loop connection to unblock and
        # exit as soon as a station switch/stop supersedes it. Without this,
        # switching stations (gapless path) left the OLD station's metadata
        # connection running indefinitely — it kept calling on_now_playing()
        # with the PREVIOUS station's track titles, racing with the new
        # station's own connection and intermittently overwriting the
        # correct Now Playing text with stale info from a station no longer
        # even playing.
        self._icy_stop_event = threading.Event()

        self.on_state_changed: Optional[Callable[[PlayerState], None]] = None
        self.on_now_playing: Optional[Callable[[str], None]] = None
        self.on_stream_info: Optional[Callable[[StreamInfo], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ---- public controls ---------------------------------------------------

    def set_fade(self, enabled: bool, seconds: float) -> None:
        self.fade_enabled = enabled
        self.fade_seconds = max(0.05, seconds)

    def start(self, url: str, station_name: str = "") -> None:
        """Switching stations while one is actually PLAYING goes through the
        gapless path (old keeps playing until the new one is ready, then
        fades out — see _switch_gapless); anything else (nothing playing
        yet, still connecting, paused, errored) has no audible old station
        worth preserving, so it just does the original stop-then-start."""
        self.station_name = station_name
        if self.state == PlayerState.PLAYING and self._proc is not None and self._out_stream is not None:
            self._switch_gapless(url)
            return
        self._cold_start(url)

    def _switch_gapless(self, url: str) -> None:
        self.url = url
        self._decode_generation += 1
        generation = self._decode_generation

        new_proc = self._spawn_decode_process(url)
        if new_proc is None:
            return

        # Metadata/probe loops are independent of the audio path — safe (and
        # desirable) to point them at the new URL immediately rather than
        # waiting for the crossfade to finish.
        self._station_generation += 1
        self._start_icy_thread(url, self._station_generation)
        self._probe_thread = threading.Thread(target=self._probe_loop, args=(url,), daemon=True)
        self._probe_thread.start()

        threading.Thread(
            target=self._prebuffer_then_crossfade, args=(new_proc, generation), daemon=True).start()

    def _prebuffer_then_crossfade(self, new_proc: subprocess.Popen, generation: int,
                                   prime_seconds: float = 0.5, crossfade_seconds: float = 0.5,
                                   timeout_seconds: float = 8.0) -> None:
        """Connects and buffers the new station on a background thread while
        the old one keeps playing completely untouched — only once the new
        station has enough decoded audio ready does the old one fade out and
        get replaced. This is what turns "stop old, dead air, wait for new
        to connect" into "old keeps playing right up until new is ready"."""
        new_buffer = StreamBuffer(int(BYTES_PER_SECOND * self.buffer_seconds))
        target_bytes = int(BYTES_PER_SECOND * prime_seconds)
        deadline = time.monotonic() + timeout_seconds
        try:
            while new_buffer.size < target_bytes and time.monotonic() < deadline:
                if generation != self._decode_generation or self._stop_event.is_set():
                    self._kill_quietly(new_proc)
                    return
                chunk = new_proc.stdout.read(8192)
                if not chunk:
                    break  # new station EOF'd/died before buffering enough — cut over with whatever we have
                new_buffer.write(chunk)
        except (OSError, ValueError):
            pass

        if generation != self._decode_generation or self._stop_event.is_set():
            self._kill_quietly(new_proc)
            return

        # The new station is ready — fade the OLD one out now (audible,
        # blocking briefly) before cutting over.
        if self._out_stream is not None:
            self._ramp_gain(0.0, crossfade_seconds)

        if generation != self._decode_generation or self._stop_event.is_set():
            self._kill_quietly(new_proc)
            return

        old_proc = self._proc
        if old_proc is not None:
            try:
                old_proc.kill()
                old_proc.wait(timeout=2)
            except Exception:
                pass

        self._proc = new_proc
        self._buffer = new_buffer
        self._reader_thread = threading.Thread(
            target=self._read_loop, args=(new_proc, new_buffer, generation), daemon=True)
        self._reader_thread.start()

        if self.fade_enabled:
            self._fade_gain = 0.0
            threading.Thread(target=self._ramp_gain, args=(1.0, self.fade_seconds), daemon=True).start()
        else:
            self._fade_gain = 1.0

    @staticmethod
    def _kill_quietly(proc: subprocess.Popen) -> None:
        try:
            proc.kill()
        except Exception:
            pass

    def _cold_start(self, url: str) -> None:
        self.stop()
        self.url = url
        self._stop_event.clear()
        self._paused.clear()
        self._fade_gain = 0.0 if self.fade_enabled else 1.0
        self._set_state(PlayerState.CONNECTING)

        capacity = int(BYTES_PER_SECOND * self.buffer_seconds)
        self._buffer = StreamBuffer(capacity)

        self._decode_generation += 1
        generation = self._decode_generation
        proc = self._spawn_decode_process(url)
        if proc is None:
            return
        self._proc = proc

        self._reader_thread = threading.Thread(
            target=self._read_loop, args=(proc, self._buffer, generation), daemon=True)
        self._reader_thread.start()

        # Opening the output device immediately (as this used to) meant the
        # audio callback started pulling from an empty buffer before ffmpeg
        # had even connected — every callback for the first couple of
        # seconds got a mix of real and zero-padded silence as the buffer
        # raced to catch up to real-time playback, heard as stutter/jitter.
        # Pre-buffering a small cushion first (same fix as the effect-change
        # click/pause) means the device only opens once there's enough
        # ahead of it to absorb normal network/decode timing jitter.
        threading.Thread(
            target=self._prime_then_open_output, args=(generation,), daemon=True).start()

        if self.fade_enabled:
            threading.Thread(target=self._ramp_gain, args=(1.0, self.fade_seconds), daemon=True).start()

        self._station_generation += 1
        self._start_icy_thread(url, self._station_generation)

        self._probe_thread = threading.Thread(target=self._probe_loop, args=(url,), daemon=True)
        self._probe_thread.start()

    def _start_icy_thread(self, url: str, generation: int) -> None:
        """(Re)starts the ICY metadata connection for `url`, tagged with the
        station `generation` it belongs to. Signals any PREVIOUS connection to
        stop (unblocking its next read so it actually closes instead of
        lingering) and gives it a fresh stop event of its own so a later
        switch doesn't have to guess which connection is "current"."""
        self._icy_stop_event.set()
        stop_event = threading.Event()
        self._icy_stop_event = stop_event
        self._icy_thread = threading.Thread(
            target=self._icy_loop, args=(url, generation, stop_event), daemon=True)
        self._icy_thread.start()

    def _spawn_decode_process(self, url: str) -> Optional[subprocess.Popen]:
        """Builds and launches the ffmpeg decode subprocess for `url` using the
        current effects_chain. Shared by start() and _restart_decode_only()
        so an effect change re-launches exactly the same kind of process."""
        ffmpeg = self._ffmpeg or find_ffmpeg()
        if not ffmpeg:
            self._fail("FFmpeg was not found. Place ffmpeg.exe in resources/ffmpeg/ or install it on PATH.")
            return None

        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", url,
            "-vn",
        ]
        if self.effects_chain:
            cmd += ["-af", self.effects_chain]
        cmd += [
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
            "pipe:1",
        ]
        try:
            return subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except OSError as exc:
            self._fail(f"Failed to launch FFmpeg: {exc}")
            return None

    def _restart_decode_only(self) -> None:
        """Swaps out just the ffmpeg decode subprocess for one built with the
        current effects_chain, leaving the sounddevice output stream, the ICY
        thread, and the probe thread completely untouched. Used by
        apply_effects() so toggling an effect doesn't reopen the audio
        device (which caused an audible click and a drastic volume drop).

        The new process needs to reconnect to the stream over the network
        and warm up its decoder before it produces any audio — that alone
        can take anywhere from tens of milliseconds to well over a second,
        and killing the OLD process immediately (as this used to) meant the
        ring buffer ran dry for that whole window: an audible gap every
        single time an effect was toggled. Instead, the new process's
        output is pre-buffered on a background thread — with the OLD
        process still running and still feeding playback — and only
        swapped in once enough new-effect audio is ready, so the old effect
        keeps playing gap-free right up until the instant the new one is
        ready to take over.
        """
        if not self.url:
            return
        self._decode_generation += 1
        generation = self._decode_generation

        new_proc = self._spawn_decode_process(self.url)
        if new_proc is None:
            return

        threading.Thread(
            target=self._prebuffer_and_swap, args=(new_proc, generation), daemon=True).start()

    def _prebuffer_and_swap(self, new_proc: subprocess.Popen, generation: int,
                             prebuffer_seconds: float = 0.35, timeout_seconds: float = 5.0) -> None:
        prebuffer = bytearray()
        target_bytes = int(BYTES_PER_SECOND * prebuffer_seconds)
        deadline = time.monotonic() + timeout_seconds
        try:
            while len(prebuffer) < target_bytes and time.monotonic() < deadline:
                if generation != self._decode_generation:
                    return  # a newer effect change superseded this one — abandon, leave old_proc running
                chunk = new_proc.stdout.read(8192)
                if not chunk:
                    break  # new process died/EOF'd before producing enough — swap with whatever we have
                prebuffer.extend(chunk)
        except (OSError, ValueError):
            pass

        if generation != self._decode_generation:
            try:
                new_proc.kill()
            except Exception:
                pass
            return

        old_proc = self._proc
        if old_proc is not None:
            try:
                old_proc.kill()
                old_proc.wait(timeout=2)
            except Exception:
                pass
        # Kill the old process (and let its reader thread's loop condition
        # go false) BEFORE touching the buffer, or a last write from the old
        # reader thread could land after the prebuffered new-effect audio.
        self._proc = new_proc
        if self._buffer is not None:
            self._buffer.clear()
            self._buffer.write(bytes(prebuffer))

        self._reader_thread = threading.Thread(
            target=self._read_loop, args=(new_proc, self._buffer, generation), daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        if self.fade_enabled and self._out_stream is not None and self._fade_gain > 0.0:
            self._ramp_gain(0.0, self.fade_seconds)  # blocks briefly — a deliberate, audible fade-out

        self._stop_event.set()
        self._icy_stop_event.set()
        self._paused.clear()
        with self._out_stream_lock:
            if self._out_stream is not None:
                try:
                    self._out_stream.stop()
                    self._out_stream.close()
                except Exception:
                    pass
                self._out_stream = None
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer = None
        self.now_playing_title = ""
        self.stream_info = StreamInfo()
        self._set_state(PlayerState.STOPPED)

    def pause(self) -> None:
        if self.state == PlayerState.PLAYING:
            self._paused.set()
            self._set_state(PlayerState.PAUSED)

    def resume(self) -> None:
        if self.state == PlayerState.PAUSED:
            self._paused.clear()
            self._set_state(PlayerState.PLAYING)

    def toggle_pause(self) -> None:
        if self.state == PlayerState.PAUSED:
            self.resume()
        else:
            self.pause()

    def set_mute(self, muted: bool) -> None:
        self.muted = muted

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def set_pan(self, pan: float) -> None:
        """pan is 0.0 (full left) .. 1.0 (full right), 0.5 = centre."""
        self.pan = max(0.0, min(1.0, pan))

    def apply_effects(self, filter_chain: str) -> None:
        """Set the ffmpeg -af filter chain built from the enabled effects/presets.

        ffmpeg filters are graph-compiled at process start, so changing them
        mid-stream means restarting the decode subprocess. Only the decode
        subprocess is restarted (_restart_decode_only) — the sounddevice
        output stream, ICY thread, and probe thread are left running, so
        there's no device-reopen click and no drop in volume.
        """
        self.effects_chain = filter_chain
        if self.state in (PlayerState.PLAYING, PlayerState.PAUSED, PlayerState.CONNECTING) and self.url:
            self._restart_decode_only()

    def set_buffer_seconds(self, seconds: int) -> None:
        self.buffer_seconds = seconds
        if self._buffer is not None:
            self._buffer.resize(int(BYTES_PER_SECOND * seconds))

    @property
    def buffer_fill(self) -> float:
        return self._buffer.fill_level if self._buffer else 0.0

    def _ramp_gain(self, target: float, duration: float) -> None:
        """Linearly ramps _fade_gain toward target over duration seconds.
        Read directly by the audio callback each block, so the ramp is
        sample-accurate regardless of this thread's own scheduling jitter."""
        start_gain = self._fade_gain
        start_time = time.monotonic()
        step = 0.02
        while True:
            elapsed = time.monotonic() - start_time
            t = min(1.0, elapsed / duration)
            self._fade_gain = start_gain + (target - start_gain) * t
            if t >= 1.0:
                break
            time.sleep(step)

    # ---- internals -----------------------------------------------------------

    def _prime_then_open_output(self, generation: int, prime_seconds: float = 0.5,
                                 timeout_seconds: float = 8.0) -> None:
        """Waits for a small cushion of decoded audio to accumulate before
        opening the output device, so playback starts smooth instead of
        stuttering while the buffer races to catch up to real-time demand.
        On a very slow/bad connection this gives up after timeout_seconds
        and opens anyway with whatever's buffered — better than silence
        forever, and no worse than the old un-primed behaviour."""
        target_bytes = int(BYTES_PER_SECOND * prime_seconds)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if generation != self._decode_generation or self._stop_event.is_set():
                return  # stopped or superseded before we ever opened the device
            buf = self._buffer
            if buf is not None and buf.size >= target_bytes:
                break
            time.sleep(0.02)

        if self._open_output_stream(generation):
            self._set_state(PlayerState.PLAYING)

    def _open_output_stream(self, generation: Optional[int] = None) -> bool:
        """Constructs, starts, and assigns self._out_stream. When `generation`
        is given, the whole check-then-open sequence happens under
        _out_stream_lock so it can't interleave with stop() touching the
        same attribute mid-construction — confirmed via tracing that without
        this, stop() could see a half-constructed stream as "not None", call
        .stop()/.close() on it while another thread was still inside
        .start(), and still end up leaking a live device. Returns whether
        the stream was actually opened (False if stop()/a newer start() beat
        us to the lock)."""
        def callback(outdata, frames, time_info, status):
            if self._paused.is_set():
                outdata.fill(0)
                return
            n_bytes = frames * CHANNELS * SAMPLE_WIDTH
            data = self._buffer.read(n_bytes) if self._buffer else b"\x00" * n_bytes
            import numpy as np
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32).reshape(-1, CHANNELS)
            if self.muted:
                samples[:] = 0
            else:
                gain = self.volume * self._fade_gain
                # Balance law: both channels at unity when pan is centred
                # (0.5), tapering linearly to silence at the opposite
                # extreme — so 0%/100% isolates a channel without the
                # centre position attenuating either one.
                left_gain = gain * min(1.0, 2.0 * (1.0 - self.pan))
                right_gain = gain * min(1.0, 2.0 * self.pan)
                if CHANNELS == 2:
                    samples[:, 0] *= left_gain
                    samples[:, 1] *= right_gain
                elif gain != 1.0:
                    samples *= gain
            outdata[:] = samples.astype(np.int16)

        with self._out_stream_lock:
            if generation is not None and (generation != self._decode_generation or self._stop_event.is_set()):
                return False
            stream = sd.OutputStream(
                samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                device=self.output_device, callback=callback,
                blocksize=2048,
            )
            stream.start()
            self._out_stream = stream
            return True

    def _read_loop(self, proc: subprocess.Popen, buf: Optional[StreamBuffer], generation: int) -> None:
        try:
            while not self._stop_event.is_set() and proc.poll() is None:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                if buf is not None:
                    buf.write(chunk)
        except (OSError, ValueError):
            pass
        finally:
            # If _decode_generation has moved on, this process was killed on
            # purpose (effect change) rather than dropping unexpectedly —
            # don't report a false error for it.
            if (not self._stop_event.is_set() and self.state != PlayerState.ERROR
                    and generation == self._decode_generation):
                threading.Thread(
                    target=log_if_geo_restricted, args=(self.station_name, self.url, self.proxies),
                    daemon=True).start()
                self._fail("Stream connection lost.")

    def _icy_loop(self, url: str, generation: int, stop_event: threading.Event) -> None:
        def on_title_changed(title: str) -> None:
            if generation != self._station_generation:
                return  # a newer station has since taken over; discard stale metadata
            self.now_playing_title = title
            if self.on_now_playing:
                self.on_now_playing(title)
        icy_metadata_loop(url, self.proxies, stop_event, on_title_changed)

    def _probe_loop(self, url: str) -> None:
        ffprobe = self._ffprobe or find_ffprobe()
        if not ffprobe:
            return
        cmd = [
            ffprobe, "-hide_banner", "-loglevel", "error", "-of", "json",
            "-show_entries", "stream=codec_name,bit_rate,sample_rate",
            "-select_streams", "a:0", url,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=15,
                creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            data = json.loads(result.stdout or b"{}")
            streams = data.get("streams") or []
            if not streams:
                return
            s = streams[0]
            bitrate = s.get("bit_rate")
            info = StreamInfo(
                codec=(s.get("codec_name") or "").upper(),
                bitrate_kbps=int(int(bitrate) / 1000) if bitrate else 0,
                sample_rate=int(s.get("sample_rate") or 0),
            )
            self.stream_info = info
            if self.on_stream_info:
                self.on_stream_info(info)
        except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError):
            pass

    def _set_state(self, state: PlayerState) -> None:
        self.state = state
        if self.on_state_changed:
            self.on_state_changed(state)

    def _fail(self, message: str) -> None:
        log.error(message)
        self._set_state(PlayerState.ERROR)
        if self.on_error:
            self.on_error(message)

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
import numpy as np

from ..utils.ffmpeg import find_ffmpeg, find_ffprobe
from .ad_detection import AdFingerprintStore, SilenceGapDetector, compute_fingerprint, is_ad_title
from .dsp import EffectChain
from .effects import CHAIN_ORDER, EFFECT_SPECS
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
                 ffprobe_path: Optional[str] = None,
                 ad_detection_enabled: bool = False, ad_auto_mute_enabled: bool = True,
                 ad_fingerprint_store: Optional[AdFingerprintStore] = None):
        self.buffer_seconds = buffer_seconds
        self.output_device = output_device
        self.proxies = proxies
        self._ffmpeg = ffmpeg_path
        self._ffprobe = ffprobe_path

        self.ad_detection_enabled = ad_detection_enabled
        self.ad_auto_mute_enabled = ad_auto_mute_enabled
        self._ad_store = ad_fingerprint_store or AdFingerprintStore()
        self._silence_detector = SilenceGapDetector(SAMPLE_RATE, CHANNELS, SAMPLE_WIDTH)
        self._ad_flagged = False
        self._ad_muted = False
        self._ad_capture: Optional[bytearray] = None
        self._ad_capture_target = 0
        self._ad_capture_reason = ""
        self._ad_clear_timer: Optional[threading.Timer] = None
        self._AD_CLIP_SECONDS = 4.0

        self.state = PlayerState.STOPPED
        self.muted = False
        self.volume = 1.0
        self.pan = 0.5  # 0.0 = full left, 0.5 = centre, 1.0 = full right
        self.stream_info = StreamInfo()
        self.now_playing_title = ""
        self.url = ""
        self.station_name = ""
        # Real-time DSP effect chain, applied directly to decoded PCM in the
        # output audio callback (see _open_output_stream) -- see apply_effects()
        # for why this replaced the old ffmpeg `-af` filter-string approach.
        self._effect_chain = EffectChain(CHAIN_ORDER)
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
        # (station switches), so a reader thread whose process was killed on
        # purpose can tell the difference from a genuine dropped connection
        # and skip firing on_error/_fail(). Effect changes no longer touch
        # this at all -- they're applied directly to the DSP chain (see
        # apply_effects()) with no decode restart involved.
        self._decode_generation = 0
        # Bumped only on an actual station change (cold start / gapless
        # switch). Used to detect stale ICY callbacks from a superseded
        # station.
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
        self.on_ad_detected: Optional[Callable[[bool], None]] = None
        # Fired instead of on_error when a stream started with expect_eof=True
        # (an on-demand podcast episode, not a live station) reaches a clean
        # end-of-file -- live radio is never expected to end on its own, so
        # that path still treats any EOF as a dropped connection.
        self.on_finished: Optional[Callable[[], None]] = None
        self._expect_eof = False
        self._rate = 1.0
        self._seek_seconds = 0.0

    # ---- public controls ---------------------------------------------------

    def set_fade(self, enabled: bool, seconds: float) -> None:
        self.fade_enabled = enabled
        self.fade_seconds = max(0.05, seconds)

    def start(self, url: str, station_name: str = "", expect_eof: bool = False,
               rate: float = 1.0, seek_seconds: float = 0.0) -> None:
        """Switching stations while one is actually PLAYING goes through the
        gapless path (old keeps playing until the new one is ready, then
        fades out — see _switch_gapless); anything else (nothing playing
        yet, still connecting, paused, errored) has no audible old station
        worth preserving, so it just does the original stop-then-start.

        expect_eof=True is for on-demand media (a podcast episode) that is
        SUPPOSED to end on its own -- a clean EOF fires on_finished instead
        of being treated as a dropped connection (see _read_loop). rate is
        a pitch-preserving playback speed multiplier (1.0 = normal); changing
        it mid-episode means calling start() again on the same url, so
        seek_seconds lets the caller resume from roughly where the previous
        segment left off instead of restarting from 0 (there's no frame-
        accurate position tracking here -- callers estimate elapsed time
        themselves and pass their best guess; ffmpeg's -ss input seek is not
        perfectly sample-accurate on all formats, but close enough for a
        rate change to not feel like a restart)."""
        self.station_name = station_name
        self._expect_eof = expect_eof
        self._rate = max(0.5, min(3.0, rate))
        self._seek_seconds = max(0.0, seek_seconds)
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
        self._probe_thread = threading.Thread(
            target=self._probe_loop, args=(url, self._station_generation), daemon=True)
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

        self._probe_thread = threading.Thread(
            target=self._probe_loop, args=(url, self._station_generation), daemon=True)
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
        """Builds and launches the ffmpeg decode subprocess for `url`. This
        subprocess is a pure decoder now -- audio effects are applied
        afterwards, directly to the decoded PCM, by the DSP effect chain in
        _open_output_stream()'s callback (see apply_effects()), so this
        command never needs an `-af` chain and never needs restarting when
        an effect changes.

        The one exception is self._rate (podcast playback speed): that's a
        pitch-preserving time-stretch, which the numpy DSP chain has no way
        to do, so it's the sole thing still applied via an ffmpeg `-af`
        filter, built fresh for each decode -- ffmpeg's atempo filter is only
        valid over 0.5-2.0 per instance, so a larger factor is split across
        two chained atempo filters instead of one out-of-range value.

        self._seek_seconds (also podcast-only) is an input seek (-ss before
        -i, so ffmpeg can skip ahead cheaply rather than decoding and
        discarding everything before it)."""
        ffmpeg = self._ffmpeg or find_ffmpeg()
        if not ffmpeg:
            self._fail("FFmpeg was not found. Place ffmpeg.exe in resources/ffmpeg/ or install it on PATH.")
            return None

        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        if self._seek_seconds > 0:
            cmd += ["-ss", str(self._seek_seconds)]
        cmd += [
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", url,
            "-vn",
        ]
        if abs(self._rate - 1.0) > 1e-3:
            if self._rate > 2.0:
                cmd += ["-af", f"atempo=2.0,atempo={self._rate / 2.0}"]
            else:
                cmd += ["-af", f"atempo={self._rate}"]
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
        if self._ad_clear_timer is not None:
            self._ad_clear_timer.cancel()
            self._ad_clear_timer = None
        self._ad_capture = None
        was_ad_flagged = self._ad_flagged
        self._ad_flagged = False
        self._ad_muted = False
        if was_ad_flagged and self.on_ad_detected:
            self.on_ad_detected(False)
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

    def apply_effects(self, effect_stages: list) -> None:
        """Update the real-time DSP effect chain from an ordered list of
        (effect_id, params) tuples (see effects_store.build_active_effect_chain/
        build_preview_effect_chain) -- every effect_id not present is turned
        off. Applied directly to already-decoded PCM inside the output audio
        callback, so this never restarts ffmpeg, never reconnects to the
        stream, and never reopens the audio device: changes are instant and
        a bad parameter can't crash playback, unlike the old ffmpeg `-af`
        filtergraph approach this replaced.
        """
        active_ids = {effect_id for effect_id, _ in effect_stages}
        stages_by_id = dict(effect_stages)
        for effect_id, spec in EFFECT_SPECS.items():
            if effect_id in active_ids:
                self._effect_chain.set_stage(effect_id, True, stages_by_id[effect_id], spec)
            else:
                self._effect_chain.set_stage(effect_id, False, {}, spec)

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
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32).reshape(-1, CHANNELS)
            # DSP effect chain, applied to normalized [-1, 1] samples before
            # volume/pan/mute -- matches where ffmpeg's -af chain used to sit
            # in the pipeline (upstream of this player-side gain stage).
            processed = self._effect_chain.process(samples / 32768.0)
            samples = np.clip(processed, -1.0, 1.0) * 32768.0
            if self.muted or self._ad_muted:
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
            # +1.0 scaled by 32768.0 lands one past int16's actual max
            # (32767) -- left uncaught, that overshoot wraps around to
            # -32768 on cast, a full-scale polarity flip heard as a click.
            # Loudness-normalized audio (most podcasts) hits that peak
            # constantly, so this clip is what stands between "clean" and
            # "crackling".
            outdata[:] = np.clip(samples, -32768, 32767).astype(np.int16)

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
                    # A live radio stream is naturally paced near real-time by
                    # the network, but decoding an on-demand file (a podcast
                    # episode) has nothing to pace it -- ffmpeg can finish
                    # decoding an hour-long episode in seconds. Without this,
                    # the buffer fills to capacity almost instantly and its
                    # overflow policy (drop oldest, meant to keep a live
                    # stream at the live edge) starts continuously discarding
                    # audio nearly as fast as it's decoded, which is audible
                    # as constant fast-forwarding rather than normal playback.
                    while (buf.fill_level > 0.9 and not self._stop_event.is_set()
                           and generation == self._decode_generation and proc.poll() is None):
                        time.sleep(0.05)
                if self.ad_detection_enabled:
                    self._feed_ad_detection(chunk, generation)
        except (OSError, ValueError):
            pass
        finally:
            # If _decode_generation has moved on, this process was killed on
            # purpose (effect change) rather than dropping unexpectedly —
            # don't report a false error for it.
            if (not self._stop_event.is_set() and self.state != PlayerState.ERROR
                    and generation == self._decode_generation):
                if self._expect_eof:
                    try:
                        returncode = proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        returncode = None
                    if returncode in (0, None):
                        self._finish()
                        return
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
            if self.ad_detection_enabled:
                if is_ad_title(title):
                    # Cheap and instant: the station is telling us directly, no
                    # fingerprint match needed to decide — but we still capture
                    # and remember this clip so a LATER station that never
                    # announces its (possibly identical, syndicated) ad can
                    # still be recognized by the fingerprint layer alone.
                    self._set_ad_flag(True)
                    self._clear_ad_flag_after(30.0)
                    self._start_ad_capture("icy")
                elif self._ad_flagged:
                    self._set_ad_flag(False)
        icy_metadata_loop(url, self.proxies, stop_event, on_title_changed)

    def _start_ad_capture(self, reason: str) -> None:
        if self._ad_capture is not None:
            return  # already capturing another candidate clip -- let that finish first
        self._ad_capture = bytearray()
        self._ad_capture_target = int(BYTES_PER_SECOND * self._AD_CLIP_SECONDS)
        self._ad_capture_reason = reason

    def _feed_ad_detection(self, chunk: bytes, generation: int) -> None:
        """Reactive tap that runs alongside normal playback -- never delays
        audio reaching the buffer. Fires a fresh capture either when the ICY
        loop flags an announced ad break, or (for stations that never
        announce anything) when the silence-gap detector notices a
        candidate boundary worth checking against previously-seen ad clips.
        """
        if self._ad_capture is not None:
            self._ad_capture.extend(chunk)
            if len(self._ad_capture) >= self._ad_capture_target:
                captured, reason = bytes(self._ad_capture), self._ad_capture_reason
                self._ad_capture = None
                threading.Thread(
                    target=self._analyze_ad_capture, args=(captured, reason, generation), daemon=True).start()
            return
        if self._silence_detector.feed(chunk):
            self._start_ad_capture("repeat")

    def _analyze_ad_capture(self, pcm: bytes, reason: str, generation: int) -> None:
        if generation != self._decode_generation:
            return  # station/effects changed mid-capture -- stale, irrelevant now
        fingerprint = compute_fingerprint(pcm, SAMPLE_RATE, CHANNELS)
        if fingerprint is None:
            return
        match = self._ad_store.find_match(fingerprint)
        if reason == "icy":
            # Flag/timer were already set synchronously by the ICY handler;
            # this just grows (or reinforces) the known-ads library.
            if match is not None:
                self._ad_store.bump(match)
            else:
                self._ad_store.remember(fingerprint, self._AD_CLIP_SECONDS, self.station_name, "icy")
            return
        if match is not None:
            self._ad_store.bump(match)
            self._set_ad_flag(True)
            self._clear_ad_flag_after(match.get("duration", self._AD_CLIP_SECONDS))

    def _set_ad_flag(self, flagged: bool) -> None:
        if flagged == self._ad_flagged:
            return
        if self._ad_clear_timer is not None:
            self._ad_clear_timer.cancel()
            self._ad_clear_timer = None
        self._ad_flagged = flagged
        self._ad_muted = flagged and self.ad_auto_mute_enabled
        if self.on_ad_detected:
            self.on_ad_detected(flagged)

    def _clear_ad_flag_after(self, seconds: float) -> None:
        if self._ad_clear_timer is not None:
            self._ad_clear_timer.cancel()
        seconds = min(max(seconds, 1.0), 60.0)  # sane cap regardless of what a stored/estimated duration says
        self._ad_clear_timer = threading.Timer(seconds, lambda: self._set_ad_flag(False))
        self._ad_clear_timer.daemon = True
        self._ad_clear_timer.start()

    def set_ad_detection_enabled(self, enabled: bool) -> None:
        self.ad_detection_enabled = enabled
        if not enabled:
            self._ad_capture = None
            if self._ad_flagged:
                self._set_ad_flag(False)

    def set_ad_auto_mute_enabled(self, enabled: bool) -> None:
        self.ad_auto_mute_enabled = enabled
        self._ad_muted = self._ad_flagged and enabled

    def _probe_loop(self, url: str, generation: int) -> None:
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
            if generation != self._station_generation:
                return  # a newer station switch beat this (slow) probe back — discard
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

    def _finish(self) -> None:
        """A stream started with expect_eof=True (a podcast episode) reached
        a clean end -- distinct from _fail() so the caller can tell "the
        episode ended normally, play the next one" apart from a real error."""
        self._set_state(PlayerState.STOPPED)
        if self.on_finished:
            self.on_finished()

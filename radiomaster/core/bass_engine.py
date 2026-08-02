"""ctypes bindings for the bundled BASS / BASS_FX / BASSmix audio engine.

BASS handles network fetch + format decode + internal buffering for both
live radio and on-demand podcast streams -- replacing the ffmpeg subprocess
this player used to spawn for that job. Streams are opened in decode-only
mode (BASS_STREAM_DECODE): BASS never touches the sound card itself, it
only produces PCM bytes on demand via BASS_ChannelGetData, which player.py
pulls from exactly like it used to pull from ffmpeg's stdout pipe -- the
numpy EffectChain, gain/pan stage and int16 output conversion downstream of
that are all completely unchanged.

Every source stream is wrapped in a small per-source BASSmix mixer fixed at
a caller-chosen sample rate/channel count. Stations and podcast episodes
arrive at all kinds of native rates (32000, 44100, 48000...) and channel
counts (mono stations are common), but the DSP filter coefficients in
core.dsp are tuned assuming a single fixed format -- the mixer resamples/
remixes each source to that fixed format so nothing downstream has to care
what a given source actually streams at.

Podcast rate/seek uses BASS_FX's tempo stream (SoundTouch-based,
pitch-preserving) instead of restarting the whole decode from scratch the
way the old ffmpeg `-af atempo` + process-respawn approach did -- tempo
changes and seeks both apply live to the same running stream.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Optional

from ..utils.paths import resources_dir

log = logging.getLogger(__name__)

# -- BASS constants (see bass.h / bass_fx.h / bassmix.h) ---------------------
# Values confirmed against a known-working BASS integration already shipping
# elsewhere (an NVDA add-on using the same bundled DLLs) where marked
# "proven"; the rest are long-stable public constants from un4seen's SDK.
BASS_STREAM_DECODE = 0x200000
BASS_STREAM_BLOCK = 0x100000          # proven

BASS_POS_BYTE = 0

BASS_ATTRIB_VOL = 2                   # proven
BASS_ATTRIB_TEMPO = 0x10000

BASS_FX_FREESOURCE = 0x10000

BASS_MIXER_END = 0x10000

BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3

BASS_CONFIG_NET_TIMEOUT = 11          # proven
BASS_CONFIG_NET_PLAYLIST = 21         # proven
BASS_CONFIG_NET_PREBUF = 15           # proven
BASS_CONFIG_NET_READTIMEOUT = 37      # proven
BASS_CONFIG_NET_SSL = 73              # proven
BASS_CONFIG_NET_SSL_VERIFY = 74       # proven

BASS_ERROR_ALREADY = 8                # proven -- BASS_Init already called


class BassError(Exception):
    pass


_lock = threading.Lock()
_bass: Optional[ctypes.WinDLL] = None
_bass_fx: Optional[ctypes.WinDLL] = None
_bass_mix: Optional[ctypes.WinDLL] = None
_ready = False


def _configure_prototypes(bass: ctypes.WinDLL) -> None:
    """64-bit-safe argtypes/restype for every call that carries a pointer-
    sized or 64-bit value -- ctypes defaults an unconfigured function to a
    32-bit c_int return, which silently truncates byte positions/lengths on
    anything but a short-lived stream."""
    bass.BASS_StreamCreateURL.restype = ctypes.c_uint32
    bass.BASS_StreamCreateURL.argtypes = [
        ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    bass.BASS_ChannelGetData.restype = ctypes.c_int32
    bass.BASS_ChannelGetData.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    bass.BASS_ChannelIsActive.restype = ctypes.c_uint32
    bass.BASS_ChannelIsActive.argtypes = [ctypes.c_uint32]
    bass.BASS_ChannelGetPosition.restype = ctypes.c_int64
    bass.BASS_ChannelGetPosition.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    bass.BASS_ChannelSetPosition.restype = ctypes.c_int32
    bass.BASS_ChannelSetPosition.argtypes = [ctypes.c_uint32, ctypes.c_int64, ctypes.c_uint32]
    bass.BASS_ChannelBytes2Seconds.restype = ctypes.c_double
    bass.BASS_ChannelBytes2Seconds.argtypes = [ctypes.c_uint32, ctypes.c_int64]
    bass.BASS_ChannelSeconds2Bytes.restype = ctypes.c_int64
    bass.BASS_ChannelSeconds2Bytes.argtypes = [ctypes.c_uint32, ctypes.c_double]
    bass.BASS_ChannelSetAttribute.restype = ctypes.c_int32
    bass.BASS_ChannelSetAttribute.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_float]
    bass.BASS_StreamFree.restype = ctypes.c_int32
    bass.BASS_StreamFree.argtypes = [ctypes.c_uint32]
    bass.BASS_ErrorGetCode.restype = ctypes.c_int32


def ensure_initialized() -> bool:
    """Loads bass.dll/bass_fx.dll/bassmix.dll and calls BASS_Init once.

    device=0 ("no sound" device) is BASS's documented mode for decode-only
    use -- this process never asks BASS to touch a real output device at
    all, since sounddevice already owns that job."""
    global _bass, _bass_fx, _bass_mix, _ready
    with _lock:
        if _ready:
            return True
        bass_dir = resources_dir("bass")
        try:
            bass = ctypes.WinDLL(f"{bass_dir}\\bass.dll")
            _configure_prototypes(bass)
            bass_fx = ctypes.WinDLL(f"{bass_dir}\\bass_fx.dll")
            bass_mix = ctypes.WinDLL(f"{bass_dir}\\bassmix.dll")
        except OSError as exc:
            log.error("Failed to load BASS DLLs from %s: %s", bass_dir, exc)
            return False

        bass_mix.BASS_Mixer_StreamCreate.restype = ctypes.c_uint32
        bass_mix.BASS_Mixer_StreamCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        bass_mix.BASS_Mixer_StreamAddChannel.restype = ctypes.c_int32
        bass_mix.BASS_Mixer_StreamAddChannel.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        bass_mix.BASS_Mixer_ChannelRemove.restype = ctypes.c_int32
        bass_mix.BASS_Mixer_ChannelRemove.argtypes = [ctypes.c_uint32]

        bass_fx.BASS_FX_TempoCreate.restype = ctypes.c_uint32
        bass_fx.BASS_FX_TempoCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

        if not bass.BASS_Init(0, 44100, 0, None, None):
            err = bass.BASS_ErrorGetCode()
            if err != BASS_ERROR_ALREADY:
                log.error("BASS_Init failed (err=%d)", err)
                return False

        bass.BASS_SetConfig(BASS_CONFIG_NET_TIMEOUT, 12000)
        bass.BASS_SetConfig(BASS_CONFIG_NET_READTIMEOUT, 12000)
        bass.BASS_SetConfig(BASS_CONFIG_NET_PREBUF, 0)
        bass.BASS_SetConfig(BASS_CONFIG_NET_SSL, 1)
        bass.BASS_SetConfig(BASS_CONFIG_NET_SSL_VERIFY, 0)
        bass.BASS_SetConfig(BASS_CONFIG_NET_PLAYLIST, 1)

        _bass, _bass_fx, _bass_mix = bass, bass_fx, bass_mix
        _ready = True
        return True


def _error(bass: ctypes.WinDLL) -> int:
    return bass.BASS_ErrorGetCode()


class BassDecodeChannel:
    """One source (radio station or podcast episode URL) decoded via BASS
    and normalized to a fixed sample rate/channel count through a private
    BASSmix mixer. Call read() from a plain background thread exactly like
    the old ffmpeg stdout reads -- never from the real-time audio callback.
    """

    def __init__(self, url: str, samplerate: int, channels: int, enable_tempo: bool = False):
        if not ensure_initialized():
            raise BassError("BASS engine failed to initialize")
        assert _bass is not None and _bass_fx is not None and _bass_mix is not None
        self._bass = _bass
        self._bass_fx = _bass_fx
        self._bass_mix = _bass_mix
        self._enable_tempo = enable_tempo
        self._raw = 0
        self._source = 0
        self._mixer = 0

        raw = self._create_url_stream(url)
        if not raw:
            raise BassError(f"BASS_StreamCreateURL failed (err={_error(self._bass)})")
        self._raw = raw

        source = raw
        if enable_tempo:
            tempo = self._bass_fx.BASS_FX_TempoCreate(raw, BASS_FX_FREESOURCE | BASS_STREAM_DECODE)
            if not tempo:
                self._bass.BASS_StreamFree(raw)
                self._raw = 0
                raise BassError(f"BASS_FX_TempoCreate failed (err={_error(self._bass)})")
            source = tempo
        self._source = source

        mixer = self._bass_mix.BASS_Mixer_StreamCreate(samplerate, channels, BASS_STREAM_DECODE | BASS_MIXER_END)
        if not mixer:
            self._free_source()
            raise BassError(f"BASS_Mixer_StreamCreate failed (err={_error(self._bass)})")
        self._mixer = mixer

        if not self._bass_mix.BASS_Mixer_StreamAddChannel(mixer, source, 0):
            err = _error(self._bass)
            self._free_source()
            self._bass.BASS_StreamFree(mixer)
            self._mixer = 0
            raise BassError(f"BASS_Mixer_StreamAddChannel failed (err={err})")

    def _create_url_stream(self, url: str) -> int:
        """Mirrors the fallback chain a known-working BASS integration uses
        for the same station catalogue: try with BASS_STREAM_BLOCK first
        (buffers the whole file up front for on-demand content), fall back
        without it (needed for some live streams that never report a
        length), and as a last resort retry with SSL verification disabled
        for https:// sources whose certificate chains BASS itself can't
        validate even though a browser/ffmpeg would accept them."""
        encoded = url.encode("utf-8")
        flags = BASS_STREAM_DECODE | BASS_STREAM_BLOCK
        handle = self._bass.BASS_StreamCreateURL(encoded, 0, flags, None, None)
        if handle:
            return handle
        handle = self._bass.BASS_StreamCreateURL(encoded, 0, BASS_STREAM_DECODE, None, None)
        if handle:
            return handle
        if url.lower().startswith("https://"):
            saved = self._bass.BASS_GetConfig(BASS_CONFIG_NET_SSL_VERIFY) if hasattr(self._bass, "BASS_GetConfig") else None
            self._bass.BASS_SetConfig(BASS_CONFIG_NET_SSL_VERIFY, 0)
            handle = self._bass.BASS_StreamCreateURL(encoded, 0, BASS_STREAM_DECODE, None, None)
            if saved is not None:
                self._bass.BASS_SetConfig(BASS_CONFIG_NET_SSL_VERIFY, saved)
            if handle:
                return handle
        return 0

    def read(self, n_bytes: int) -> bytes:
        """Returns up to n_bytes of decoded PCM, b"" on a clean end/error.

        Non-blocking: BASS decode channels return whatever is already
        buffered internally, which is exactly the same "pull what's ready,
        don't wait" contract the old ffmpeg pipe read had."""
        buf = ctypes.create_string_buffer(n_bytes)
        n = self._bass.BASS_ChannelGetData(self._mixer, buf, n_bytes)
        if n <= 0:
            return b""
        return buf.raw[:n]

    def is_active(self) -> bool:
        return self._bass.BASS_ChannelIsActive(self._mixer) != BASS_ACTIVE_STOPPED

    def set_tempo(self, rate: float) -> None:
        """rate is a multiplier (1.0 = normal); only valid when this channel
        was created with enable_tempo=True."""
        if not self._enable_tempo:
            return
        percent = (max(0.5, min(3.0, rate)) - 1.0) * 100.0
        self._bass.BASS_ChannelSetAttribute(self._source, BASS_ATTRIB_TEMPO, ctypes.c_float(percent))

    def seek_seconds(self, seconds: float) -> None:
        """Live seek within the current source -- no restart, no new
        connection. Only meaningful for on-demand (podcast) sources."""
        pos = self._bass.BASS_ChannelSeconds2Bytes(self._source, max(0.0, seconds))
        self._bass.BASS_ChannelSetPosition(self._source, pos, BASS_POS_BYTE)

    def position_seconds(self) -> float:
        pos = self._bass.BASS_ChannelGetPosition(self._source, BASS_POS_BYTE)
        if pos < 0:
            return 0.0
        return self._bass.BASS_ChannelBytes2Seconds(self._source, pos)

    def _free_source(self) -> None:
        if self._source:
            self._bass_mix.BASS_Mixer_ChannelRemove(self._source)
            self._bass.BASS_StreamFree(self._source)
            self._source = 0
            self._raw = 0  # freed transitively via BASS_FX_FREESOURCE, or is the same handle

    def close(self) -> None:
        self._free_source()
        if self._mixer:
            self._bass.BASS_StreamFree(self._mixer)
            self._mixer = 0

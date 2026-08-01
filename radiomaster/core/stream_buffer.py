"""A fixed-capacity byte ring buffer used to decouple network/decode speed from playback."""

from __future__ import annotations

import threading
from collections import deque


class StreamBuffer:
    """Thread-safe ring buffer of PCM bytes.

    Producer (ffmpeg stdout reader thread) calls write(); consumer (audio
    output callback) calls read(). Capacity is expressed in bytes and derived
    from a target number of seconds of audio by the caller.
    """

    def __init__(self, capacity_bytes: int):
        self._capacity = max(capacity_bytes, 1)
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._lock = threading.Lock()
        self._closed = False

    def resize(self, capacity_bytes: int) -> None:
        with self._lock:
            self._capacity = max(capacity_bytes, 1)

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._chunks.append(data)
            self._size += len(data)
            # Drop oldest data if producer outruns capacity (favour "live" audio).
            while self._size > self._capacity and len(self._chunks) > 1:
                dropped = self._chunks.popleft()
                self._size -= len(dropped)

    def read(self, n: int) -> bytes:
        """Return up to n bytes immediately, zero-padding if starved.

        Called from the sounddevice output callback, which runs on a
        real-time audio thread — it MUST return within a few milliseconds
        or PortAudio has nothing to play and the whole device underruns
        audibly. This used to block (via a Condition.wait) for up to 500ms
        whenever the buffer ran dry, which turned every brief network hiccup
        into a guaranteed audible stutter far worse than a bit of silence;
        never blocking here (prebuffering before playback starts is what
        actually prevents starvation — see _prime_then_open_output) is what
        fixed it.
        """
        with self._lock:
            out = bytearray()
            while len(out) < n and self._chunks:
                chunk = self._chunks[0]
                needed = n - len(out)
                if len(chunk) <= needed:
                    out += chunk
                    self._chunks.popleft()
                    self._size -= len(chunk)
                else:
                    out += chunk[:needed]
                    self._chunks[0] = chunk[needed:]
                    self._size -= needed
            if len(out) < n:
                out += b"\x00" * (n - len(out))
            return bytes(out)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0

    def close(self) -> None:
        with self._lock:
            self._closed = True

    @property
    def fill_level(self) -> float:
        """Fraction (0..1) of capacity currently filled."""
        with self._lock:
            return min(1.0, self._size / self._capacity) if self._capacity else 0.0

    @property
    def size(self) -> int:
        with self._lock:
            return self._size

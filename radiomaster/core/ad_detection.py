"""Ad-break detection: ICY keyword matching (instant, free) plus a
self-contained spectral audio fingerprint for recognizing repeated ad
clips even on stations that never announce them.

Deliberately does NOT depend on fpcalc/pyacoustid (used elsewhere in this
app only for track *identification*, and not guaranteed to be installed —
see utils/fingerprint.py). This fingerprint is our own coarse spectral
hash, built entirely from numpy (already a hard dependency of the player),
so ad detection works out of the box with no extra binaries.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

import numpy as np

from ..utils.paths import state_dir

log = logging.getLogger(__name__)

AD_TITLE_KEYWORDS = (
    "advertisement", "advert", "commercial break", "commercial",
    "sponsor", "ad break", "station break",
)


def is_ad_title(title: str) -> bool:
    lowered = (title or "").lower()
    return any(keyword in lowered for keyword in AD_TITLE_KEYWORDS)


_FRAME_SIZE = 4096
_HOP_SIZE = 2048
_N_BANDS = 16
# Mean-abs-difference (log-energy units) below this counts as "the same
# clip" — deliberately conservative: a missed match just means one ad play
# goes unflagged, but a false one means muting a real song, so this errs
# toward under-triggering rather than over-triggering.
MATCH_THRESHOLD = 0.22


def compute_fingerprint(pcm: bytes, sample_rate: int, channels: int) -> Optional[list]:
    """Turns a raw PCM capture into a compact sequence of per-frame,
    per-band log-energy vectors — a coarse spectral signature that
    tolerates re-encoding/lossy-transcoding differences well enough to
    recognize the same ad clip played back-to-back or on another station,
    without needing any binary beyond numpy."""
    if not pcm:
        return None
    samples = np.frombuffer(pcm, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples = samples.astype(np.float32) / 32768.0
    if len(samples) < _FRAME_SIZE:
        return None

    band_edges = np.logspace(np.log10(50), np.log10(sample_rate / 2 - 1), _N_BANDS + 1)
    freqs = np.fft.rfftfreq(_FRAME_SIZE, d=1.0 / sample_rate)
    window = np.hanning(_FRAME_SIZE)
    frames = []
    for start in range(0, len(samples) - _FRAME_SIZE, _HOP_SIZE):
        mag = np.abs(np.fft.rfft(samples[start:start + _FRAME_SIZE] * window))
        band_energies = []
        for lo, hi in zip(band_edges[:-1], band_edges[1:]):
            mask = (freqs >= lo) & (freqs < hi)
            energy = mag[mask].mean() if mask.any() else 0.0
            band_energies.append(round(float(np.log10(energy + 1e-6)), 3))
        frames.append(band_energies)
    return frames or None


def fingerprint_distance(a: list, b: list) -> float:
    """Lowest mean-absolute-difference between a and b across every
    integer frame-offset alignment (the two clips rarely start at the
    exact same instant) — 0.0 is identical, larger is more different."""
    if not a or not b:
        return 999.0
    arr_a, arr_b = np.array(a), np.array(b)
    if len(arr_a) > len(arr_b):
        arr_a, arr_b = arr_b, arr_a
    n = len(arr_a)
    best = None
    for shift in range(len(arr_b) - n + 1):
        dist = float(np.abs(arr_a - arr_b[shift:shift + n]).mean())
        if best is None or dist < best:
            best = dist
    return best if best is not None else 999.0


class AdFingerprintStore:
    """ad_fingerprints.json: a small local library of recognized ad clips,
    grown automatically — ICY-labelled breaks are captured and remembered
    immediately; later, unlabelled repeats of the same audio (on this
    station or any other) are recognized purely by spectral match against
    this store, with no reliance on the station announcing itself."""

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(state_dir(), "ad_fingerprints.json")
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        self._records = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._records = []

    def save(self) -> None:
        with self._lock:
            records = list(self._records)
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(records, f)
            os.replace(tmp, self._path)
        except OSError:
            log.exception("Failed to save %s", self._path)

    def find_match(self, fingerprint: list) -> Optional[dict]:
        with self._lock:
            records = list(self._records)
        best_rec, best_dist = None, MATCH_THRESHOLD
        for rec in records:
            dist = fingerprint_distance(fingerprint, rec["fingerprint"])
            if dist < best_dist:
                best_dist = dist
                best_rec = rec
        return best_rec

    def remember(self, fingerprint: list, duration: float, station: str, confirmed_via: str) -> dict:
        now = time.time()
        rec = {
            "fingerprint": fingerprint, "duration": duration, "station": station,
            "confirmed_via": confirmed_via, "occurrences": 1,
            "first_seen": now, "last_seen": now,
        }
        with self._lock:
            self._records.append(rec)
        self.save()
        return rec

    def bump(self, rec: dict) -> None:
        with self._lock:
            rec["occurrences"] = rec.get("occurrences", 0) + 1
            rec["last_seen"] = time.time()
        self.save()


class SilenceGapDetector:
    """Cheap RMS-based trigger for 'something changed here, worth a
    fingerprint check' — deliberately NOT a verdict by itself. A quiet
    passage inside a normal song trips this exactly the same as a real
    ad/segment boundary; what keeps that harmless is that the fingerprint
    check which follows only ever *matches* a previously-seen ad clip — a
    musical pause has nothing to match against, so it's a wasted (but
    inaudible, inconsequential) check rather than a false mute.
    """

    _SILENCE_AMPLITUDE = 300.0  # int16 units, ~-38 dBFS: true dead air, not just a quiet passage
    _MIN_GAP_SECONDS = 0.35
    _COOLDOWN_SECONDS = 8.0

    def __init__(self, sample_rate: int, channels: int, sample_width: int = 2):
        self._bytes_per_second = sample_rate * channels * sample_width
        self._silence_seconds = 0.0
        self._last_trigger = 0.0

    def feed(self, chunk: bytes) -> bool:
        if not chunk or self._bytes_per_second <= 0:
            return False
        samples = np.frombuffer(chunk, dtype=np.int16)
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) else 0.0
        duration = len(chunk) / self._bytes_per_second
        if rms < self._SILENCE_AMPLITUDE:
            self._silence_seconds += duration
        else:
            self._silence_seconds = 0.0
        now = time.monotonic()
        if (self._silence_seconds >= self._MIN_GAP_SECONDS
                and now - self._last_trigger >= self._COOLDOWN_SECONDS):
            self._last_trigger = now
            self._silence_seconds = 0.0
            return True
        return False

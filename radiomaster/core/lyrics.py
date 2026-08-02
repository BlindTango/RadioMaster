"""Song lyrics lookup via the free lyrics.ovh API, using the artist/title
split out of the ICY 'now playing' text (core.metadata.split_icy_title) —
the same split already used to resolve track metadata for recordings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)

LYRICS_OVH_URL = "https://api.lyrics.ovh/v1"
USER_AGENT = "RadioMaster/1.0 (+https://github.com/)"


class LyricsFetchError(RuntimeError):
    pass


@dataclass
class LyricsResult:
    artist: str
    title: str
    text: str
    source: str = "lyrics.ovh"


def format_lyrics(raw: str) -> str:
    """Normalizes line endings and collapses runs of blank lines to a
    single blank line, so lyrics display with their original verse/chorus
    breaks instead of as one dense block or a wall of stray blank lines —
    lyrics.ovh's raw text mixes \\r\\n endings with runs of 3+ blank lines
    between some sections."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    normalized: list[str] = []
    blank_run = 0
    for line in text.split("\n"):
        line = line.rstrip()
        if line == "":
            blank_run += 1
            if blank_run <= 1:
                normalized.append(line)
        else:
            blank_run = 0
            normalized.append(line)
    return "\n".join(normalized).strip("\n")


def fetch_lyrics(artist: str, title: str, proxies: Optional[dict] = None,
                  timeout: float = 8.0) -> Optional[LyricsResult]:
    """Returns None (not an error) when the track simply has no lyrics on
    file — only network/parse failures raise LyricsFetchError."""
    artist = (artist or "").strip()
    title = (title or "").strip()
    if not artist or not title:
        return None

    url = f"{LYRICS_OVH_URL}/{quote(artist)}/{quote(title)}"
    try:
        resp = requests.get(url, timeout=timeout, proxies=proxies, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        raise LyricsFetchError(f"Could not reach the lyrics service: {exc}") from exc

    if resp.status_code == 404:
        return None
    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise LyricsFetchError(f"Could not read the lyrics response: {exc}") from exc

    raw = data.get("lyrics")
    if not raw or not raw.strip():
        return None
    return LyricsResult(artist=artist, title=title, text=format_lyrics(raw))

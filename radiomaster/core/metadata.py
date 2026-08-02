"""Track metadata resolution: Deezer (primary) -> MusicBrainz (secondary) ->
AcoustID audio fingerprint (last resort, when the ICY station gave no usable
title text) -> ICY passthrough."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

DEEZER_SEARCH_URL = "https://api.deezer.com/search"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/recording"
USER_AGENT = "RadioMaster/1.0 (+https://github.com/)"


@dataclass
class TrackInfo:
    artist: str = "Unknown"
    title: str = ""
    album: str = ""
    cover_art_url: str = ""
    source: str = ""


def split_icy_title(icy_text: str) -> tuple[str, str]:
    """ICY StreamTitle is usually 'Artist - Title'."""
    if " - " in icy_text:
        artist, title = icy_text.split(" - ", 1)
        return artist.strip(), title.strip()
    return "Unknown", icy_text.strip()


def deezer_search(query: str, proxies: Optional[dict] = None) -> Optional[TrackInfo]:
    if not query:
        return None
    try:
        resp = requests.get(
            DEEZER_SEARCH_URL, params={"q": query}, timeout=8, proxies=proxies,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    results = data.get("data") or []
    if not results:
        return None
    r = results[0]
    return TrackInfo(
        artist=(r.get("artist") or {}).get("name", "Unknown"),
        title=r.get("title", ""),
        album=(r.get("album") or {}).get("title", ""),
        cover_art_url=(r.get("album") or {}).get("cover_big", ""),
        source="deezer",
    )


def musicbrainz_search(query: str, proxies: Optional[dict] = None) -> Optional[TrackInfo]:
    if not query:
        return None
    try:
        resp = requests.get(
            MUSICBRAINZ_URL, params={"query": query, "fmt": "json", "limit": 1},
            timeout=8, proxies=proxies, headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None
    recordings = data.get("recordings") or []
    if not recordings:
        return None
    r = recordings[0]
    artist_credit = r.get("artist-credit") or [{}]
    releases = r.get("releases") or [{}]
    return TrackInfo(
        artist=artist_credit[0].get("name", "Unknown"),
        title=r.get("title", ""),
        album=releases[0].get("title", "") if releases else "",
        source="musicbrainz",
    )


def acoustid_lookup(filepath: str, api_key: str, fpcalc_path: Optional[str] = None) -> Optional[TrackInfo]:
    """Identify a recorded track from its audio alone via AcoustID/Chromaprint.

    Used only as a last resort when the ICY 'now playing' text is missing or
    didn't match anything on Deezer/MusicBrainz. Requires the `pyacoustid`
    package (installed), the `fpcalc` binary (NOT bundled by default — install
    Chromaprint or place fpcalc.exe in resources/fpcalc/), and a free AcoustID
    API key (configured in Settings). Any of those being unavailable is a
    normal, graceful no-op, matching every other optional dependency in this
    app (Pandoc/Tesseract-style sidecar pattern).
    """
    if not api_key:
        return None
    try:
        import acoustid
    except ImportError:
        log.info("pyacoustid not installed; skipping AcoustID fingerprint lookup")
        return None

    if fpcalc_path:
        os.environ[acoustid.FPCALC_ENVVAR] = fpcalc_path

    try:
        duration, fingerprint = acoustid.fingerprint_file(filepath)
        response = acoustid.lookup(api_key, fingerprint, duration, meta=["recordings"])
    except Exception:
        log.exception("AcoustID fingerprint/lookup failed for %s", filepath)
        return None

    try:
        best = None
        for score, _rid, title, artist in acoustid.parse_lookup_result(response):
            if title and (best is None or score > best[0]):
                best = (score, title, artist)
    except Exception:
        log.exception("Failed to parse AcoustID response for %s", filepath)
        return None

    if best is None:
        return None
    _score, title, artist = best
    return TrackInfo(artist=artist or "Unknown", title=title, source="acoustid")


def get_track_info(now_playing_text: str, use_deezer: bool = True,
                    use_musicbrainz: bool = True, proxies: Optional[dict] = None,
                    acoustid_filepath: Optional[str] = None, acoustid_api_key: Optional[str] = None,
                    fpcalc_path: Optional[str] = None) -> TrackInfo:
    """Resolve rich metadata for the raw ICY 'now playing' string, with graceful fallback.

    If the ICY text search comes up empty and `acoustid_filepath`/`acoustid_api_key`
    are supplied, falls back to audio-fingerprint recognition of that file.
    """
    query = now_playing_text.strip()

    if query:
        if use_deezer:
            result = deezer_search(query, proxies=proxies)
            if result:
                return result

        if use_musicbrainz:
            result = musicbrainz_search(query, proxies=proxies)
            if result:
                return result

    if acoustid_filepath and acoustid_api_key:
        result = acoustid_lookup(acoustid_filepath, acoustid_api_key, fpcalc_path=fpcalc_path)
        if result:
            return result

    if query:
        artist, title = split_icy_title(query)
        return TrackInfo(artist=artist, title=title, source="icy")

    return TrackInfo()

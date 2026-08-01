"""Best-effort scraper: given a station's own webpage, find the real
underlying audio stream URL — so adding a custom station doesn't require
manually digging through a page's source/network tab for the actual stream
link. This scans the STATION'S OWN public page for links it already
published; it does not touch or decode any third-party protected content.
"""

from __future__ import annotations

import re
from typing import Optional

import requests

from .. import __app_name__, __version__

USER_AGENT = f"{__app_name__}/{__version__}"

_TIMEOUT = 10

# Direct audio file / HLS manifest extensions — playable as-is.
_AUDIO_EXT_RE = re.compile(
    r'https?://[^\s"\'<>]+?\.(?:mp3|aac|ogg|opus|flac|m4a|m3u8)(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE,
)
# Playlist files that wrap a real stream URL inside — need a follow-up fetch.
_PLAYLIST_EXT_RE = re.compile(
    r'https?://[^\s"\'<>]+?\.(?:pls|m3u)(?:\?[^\s"\'<>]*)?(?<!m3u8)',
    re.IGNORECASE,
)
# Common radio-streaming hosts that don't always use a telltale extension.
_KNOWN_STREAM_HOST_RE = re.compile(
    r'https?://[^\s"\'<>]*(?:icecast|shoutcast|streamguys|radiojar|zeno\.fm|'
    r'streema|laut\.fm|radio\.co|centova|abacast)[^\s"\'<>]*',
    re.IGNORECASE,
)
_PLS_FILE_RE = re.compile(r'^\s*File\d*\s*=\s*(\S+)', re.IGNORECASE | re.MULTILINE)


def _fetch(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT},
                             allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def _resolve_playlist(playlist_url: str) -> list[str]:
    """.pls/.m3u files just list the real stream URL(s) inside — fetch and
    pull those out rather than returning the playlist file itself."""
    text = _fetch(playlist_url)
    if not text:
        return []
    if playlist_url.lower().split("?")[0].endswith(".pls"):
        return [m.strip() for m in _PLS_FILE_RE.findall(text) if m.strip()]
    # .m3u: plain-text list, one URL per non-comment line.
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def find_stream_urls(page_url: str) -> list[str]:
    """Scans `page_url`'s HTML for candidate audio stream URLs. Returns a
    deduplicated, ordered-by-confidence list (direct audio/HLS links first,
    then resolved playlist targets, then generic known-host matches) —
    empty if the page couldn't be fetched or nothing was found."""
    if not page_url.startswith(("http://", "https://")):
        page_url = f"https://{page_url}"

    html = _fetch(page_url)
    if html is None:
        return []

    found: dict[str, None] = {}  # insertion-ordered set

    for match in _AUDIO_EXT_RE.findall(html):
        found[match] = None

    for playlist_url in _PLAYLIST_EXT_RE.findall(html):
        for resolved in _resolve_playlist(playlist_url):
            found[resolved] = None

    for match in _KNOWN_STREAM_HOST_RE.findall(html):
        found[match] = None

    return list(found.keys())

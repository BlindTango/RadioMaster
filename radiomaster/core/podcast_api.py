"""Podcast directory search (iTunes/Apple Podcasts, Podcast Index) and RSS
episode feed parsing.

Unlike station_api.py's Radio Browser client (one canonical database),
podcasts have several independent public directories with no single
authority — search_all() below fans a query out to whichever directories
are configured/available and merges the results, tagging each with which
directory it came from.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Optional

import requests

from .. import __app_name__, __version__

log = logging.getLogger(__name__)

USER_AGENT = f"{__app_name__}/{__version__}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_text(text: Optional[str]) -> str:
    """Strips HTML tags/entities out of feed text (titles/descriptions often
    carry raw markup) -- read literally, tags like "<p>"/"<a href=...>"
    would otherwise be spoken aloud by a screen reader."""
    if not text:
        return ""
    text = html_mod.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


@dataclass
class PodcastResult:
    feed_url: str
    title: str
    author: str = ""
    artwork_url: str = ""
    description: str = ""
    genre: str = ""
    directory: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PodcastResult":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class Episode:
    guid: str
    title: str
    audio_url: str
    pub_date: str = ""
    duration: str = ""
    description: str = ""


class PodcastAPIError(RuntimeError):
    pass


class PodcastDirectory:
    name = "base"

    def search(self, term: str, limit: int = 25) -> list[PodcastResult]:
        raise NotImplementedError


class ITunesDirectory(PodcastDirectory):
    """Apple's free, keyless podcast search endpoint -- always available,
    used as the default directory."""

    name = "iTunes / Apple Podcasts"
    BASE_URL = "https://itunes.apple.com/search"

    def __init__(self, proxies: Optional[dict] = None):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self.proxies = proxies

    def set_proxies(self, proxies: Optional[dict]) -> None:
        self.proxies = proxies

    def search(self, term: str, limit: int = 25) -> list[PodcastResult]:
        try:
            resp = self._session.get(
                self.BASE_URL, params={"term": term, "media": "podcast", "limit": limit},
                timeout=10, proxies=self.proxies,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise PodcastAPIError(f"Could not search {self.name}: {exc}") from exc

        results = []
        for item in data.get("results", []):
            feed_url = item.get("feedUrl")
            if not feed_url:
                continue
            genres = item.get("genres") or ([item["primaryGenreName"]] if item.get("primaryGenreName") else [])
            results.append(PodcastResult(
                feed_url=feed_url,
                title=_clean_text(item.get("collectionName") or item.get("trackName")) or "Untitled Podcast",
                author=_clean_text(item.get("artistName")),
                artwork_url=item.get("artworkUrl600") or item.get("artworkUrl100", ""),
                genre=", ".join(genres),
                directory=self.name,
            ))
        return results


class PodcastIndexDirectory(PodcastDirectory):
    """Podcast Index (podcastindex.org) -- a second, independent directory.
    Needs a free API key+secret from the user (Settings page); every request
    is HMAC-signed per their published auth scheme. Silently contributes no
    results (rather than erroring) when not configured, so it's safe to
    always include in search_all() even for users who never set it up."""

    name = "Podcast Index"
    BASE_URL = "https://api.podcastindex.org/api/1.0"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 proxies: Optional[dict] = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self._session = requests.Session()
        self.proxies = proxies

    def set_proxies(self, proxies: Optional[dict]) -> None:
        self.proxies = proxies

    def set_credentials(self, api_key: Optional[str], api_secret: Optional[str]) -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _headers(self) -> dict:
        epoch = str(int(time.time()))
        auth_hash = hashlib.sha1(f"{self.api_key}{self.api_secret}{epoch}".encode("utf-8")).hexdigest()
        return {
            "User-Agent": USER_AGENT,
            "X-Auth-Key": self.api_key or "",
            "X-Auth-Date": epoch,
            "Authorization": auth_hash,
        }

    def search(self, term: str, limit: int = 25) -> list[PodcastResult]:
        if not self.available:
            return []
        try:
            resp = self._session.get(
                f"{self.BASE_URL}/search/byterm", params={"q": term, "max": limit},
                headers=self._headers(), timeout=10, proxies=self.proxies,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise PodcastAPIError(f"Could not search {self.name}: {exc}") from exc

        results = []
        for item in data.get("feeds", []):
            feed_url = item.get("url")
            if not feed_url:
                continue
            categories = item.get("categories")
            genre = ", ".join(categories.values()) if isinstance(categories, dict) else ""
            results.append(PodcastResult(
                feed_url=feed_url,
                title=_clean_text(item.get("title")) or "Untitled Podcast",
                author=_clean_text(item.get("author")),
                artwork_url=item.get("image") or item.get("artwork", ""),
                description=_clean_text(item.get("description")),
                genre=genre,
                directory=self.name,
            ))
        return results


def search_all(term: str, directories: list[PodcastDirectory], limit: int = 25) -> list[PodcastResult]:
    """Fans a search out to every given directory and merges the results.
    A directory that errors doesn't sink the whole search -- only raises if
    EVERY directory failed and none returned anything."""
    results: list[PodcastResult] = []
    errors: list[str] = []
    for directory in directories:
        try:
            results.extend(directory.search(term, limit=limit))
        except PodcastAPIError as exc:
            errors.append(str(exc))
    if errors and not results:
        raise PodcastAPIError("; ".join(errors))
    return results


_ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def fetch_episodes(feed_url: str, proxies: Optional[dict] = None, limit: int = 300) -> list[Episode]:
    """Downloads and parses a podcast's RSS feed into an ordered episode list
    (newest first, matching typical feed order)."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        resp = session.get(feed_url, timeout=15, proxies=proxies)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PodcastAPIError(f"Could not fetch podcast feed: {exc}") from exc
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise PodcastAPIError(f"Podcast feed is not valid XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        return []

    episodes = []
    for item in channel.findall("item")[:limit]:
        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else None
        if not audio_url:
            continue  # not a playable episode (e.g. a text-only post in the feed)
        guid_el = item.find("guid")
        title_el = item.find("title")
        pub_el = item.find("pubDate")
        duration_el = item.find(f"{_ITUNES_NS}duration")
        desc_el = item.find("description")
        if desc_el is None:
            desc_el = item.find(f"{_ITUNES_NS}summary")
        guid = (guid_el.text if guid_el is not None else None) or audio_url
        episodes.append(Episode(
            guid=guid,
            title=_clean_text(title_el.text if title_el is not None else None) or "Untitled Episode",
            audio_url=audio_url,
            pub_date=(pub_el.text or "").strip() if pub_el is not None else "",
            duration=(duration_el.text or "").strip() if duration_el is not None else "",
            description=_clean_text(desc_el.text if desc_el is not None else None),
        ))
    return episodes


def fetch_feed_metadata(feed_url: str, proxies: Optional[dict] = None) -> PodcastResult:
    """Downloads and parses a podcast's own RSS feed to build a PodcastResult
    directly from its <channel> tags -- used for "Add Feed" (a feed_url the
    user already has, e.g. from outside any of the searchable directories),
    which has no directory search result to draw title/author/artwork from."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        resp = session.get(feed_url, timeout=15, proxies=proxies)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise PodcastAPIError(f"Could not fetch podcast feed: {exc}") from exc
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise PodcastAPIError(f"Podcast feed is not valid XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise PodcastAPIError("Feed has no <channel> element -- not a valid podcast RSS feed.")

    title_el = channel.find("title")
    author_el = channel.find(f"{_ITUNES_NS}author")
    desc_el = channel.find("description") or channel.find(f"{_ITUNES_NS}summary")
    image_el = channel.find(f"{_ITUNES_NS}image")
    artwork_url = image_el.get("href") if image_el is not None else ""
    if not artwork_url:
        image_url_el = channel.find("image/url")
        artwork_url = image_url_el.text if image_url_el is not None else ""
    category_el = channel.find(f"{_ITUNES_NS}category")

    return PodcastResult(
        feed_url=feed_url,
        title=_clean_text(title_el.text if title_el is not None else None) or feed_url,
        author=_clean_text(author_el.text if author_el is not None else None),
        artwork_url=artwork_url or "",
        description=_clean_text(desc_el.text if desc_el is not None else None),
        genre=category_el.get("text", "") if category_el is not None else "",
        directory="Manual",
    )

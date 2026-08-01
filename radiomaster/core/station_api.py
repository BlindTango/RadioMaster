"""Client for the Radio Browser free station database (https://www.radio-browser.info/)."""

from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass, asdict
from typing import Callable, Optional

import requests

from .. import __app_name__, __version__
from ..utils.genres import resolve_genres
from ..utils.iso_languages import resolve_languages

log = logging.getLogger(__name__)

# Fallback only — Radio Browser mirror instances (de1/at1/etc.) come and go
# over time, so a hardcoded one can simply stop existing (confirmed: this is
# what a "getaddrinfo failed" / NameResolutionError for one specific mirror
# usually means, not necessarily a network outage). _discover_servers()
# below is tried first and adapts automatically; this list is only the
# last resort if that discovery itself can't reach DNS at all.
DEFAULT_BASE_URLS = [
    "https://de1.api.radio-browser.info",
    "https://all.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]


def _discover_servers() -> list[str]:
    """Radio Browser's own recommended discovery mechanism: resolve
    all.api.radio-browser.info to get every currently-live mirror's IP, then
    reverse-resolve each IP to its real hostname. This is what adapts to
    mirrors joining/leaving — a hardcoded subdomain list can't."""
    servers: list[str] = []
    try:
        infos = socket.getaddrinfo("all.api.radio-browser.info", 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return servers
    for ip in {info[4][0] for info in infos}:
        try:
            host, _, _ = socket.gethostbyaddr(ip)
        except OSError:
            continue
        servers.append(f"https://{host}")
    return servers

USER_AGENT = f"{__app_name__}/{__version__}"

# Radio Browser has no first-class "network"/broadcaster-group field, unlike
# genre/country/language. This is a best-effort recognition list of common
# broadcast networks/station groups, matched against tags or a station name
# prefix (e.g. "BBC Radio 1" -> "BBC"). Anything not recognized here just has
# no network (grouped under "" in the By Network browse category) — for
# custom stations, the user's own typed network name is used verbatim
# instead (see CustomStationsStore.add()).
KNOWN_NETWORKS = [
    "BBC", "NPR", "iHeartRadio", "iHeart", "ABC", "CBC", "RTE", "RTÉ", "NRJ", "RTL",
    "Capital", "Heart", "Smooth", "Kiss", "Absolute Radio", "Absolute", "talkSPORT",
    "Virgin Radio", "SiriusXM", "Univision", "Audacy", "Radio.com", "Cumulus", "RCS",
    "Bauer", "Global", "Antenne", "Sunrise", "Classic FM", "Radio X", "LBC", "Magic",
    "Jazz FM", "Planet Rock",
]


def _strip_leading_the(name: str) -> str:
    """Radio Browser's `country` field sometimes carries the English
    definite article ("The United Kingdom", "The Netherlands") — stripped
    so "By Country" browsing reads as plain country names."""
    stripped = name.strip()
    if stripped[:4].lower() == "the " and len(stripped) > 4:
        return stripped[4:].strip()
    return stripped


def _guess_network(tags: str, name: str) -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    for network in KNOWN_NETWORKS:
        network_lower = network.lower()
        if any(tag.lower() == network_lower for tag in tag_list):
            return network
        if name.lower().startswith(network_lower):
            return network
    return ""


@dataclass
class Station:
    uuid: str
    name: str
    url: str
    favicon: str = ""
    tags: str = ""
    country: str = ""
    language: str = ""
    codec: str = ""
    bitrate: int = 0
    votes: int = 0
    homepage: str = ""
    network: str = ""
    languagecodes: str = ""

    @property
    def genres(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def canonical_genres(self) -> list[str]:
        """Canonical genre(s) for this station — see utils/genres.py. Used
        for "By Genre" browsing instead of the raw tags property above,
        which is unfiltered free text and includes moods/decades/place names
        that aren't genres at all."""
        return resolve_genres(self.tags)

    @property
    def iso_languages(self) -> list[str]:
        """Canonical ISO 639 language name(s) for this station — see
        utils/iso_languages.py. A station can resolve to several (e.g. a
        bilingual station), which is exactly why "By Language" browsing
        groups through a station_languages junction table rather than by
        this raw, sometimes-multi-valued field directly."""
        return resolve_languages(self.language, self.languagecodes)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_api(cls, raw: dict) -> "Station":
        name = raw.get("name", "").strip() or "Unnamed Station"
        tags = raw.get("tags", "")
        return cls(
            uuid=raw.get("stationuuid", ""),
            name=name,
            url=raw.get("url_resolved") or raw.get("url", ""),
            favicon=raw.get("favicon", ""),
            tags=tags,
            country=_strip_leading_the(raw.get("country", "")),
            language=raw.get("language", ""),
            codec=raw.get("codec", ""),
            bitrate=int(raw.get("bitrate") or 0),
            votes=int(raw.get("votes") or 0),
            homepage=raw.get("homepage", ""),
            network=_guess_network(tags, name),
            languagecodes=raw.get("languagecodes", ""),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Station":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


class StationAPIError(RuntimeError):
    pass


class StationAPI:
    """Thin HTTP client for the Radio Browser API; StationDB handles local caching."""

    def __init__(self, base_urls: Optional[list[str]] = None, proxies: Optional[dict] = None):
        if base_urls:
            self._base_urls = base_urls
        else:
            discovered = _discover_servers()
            # Discovered servers first (current + adaptive), static list as
            # a last-resort fallback, no duplicates, order preserved.
            seen: dict[str, None] = {}
            for url in discovered + DEFAULT_BASE_URLS:
                seen.setdefault(url, None)
            self._base_urls = list(seen.keys())
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self.proxies = proxies

    def set_proxies(self, proxies: Optional[dict]) -> None:
        self.proxies = proxies

    def _get(self, path: str, params: Optional[dict] = None, timeout: int = 10,
             retries: int = 1, retry_delay: float = 5.0,
             progress_cb: Optional[Callable[[int, Optional[int]], None]] = None) -> list:
        """progress_cb, if given, is called after every chunk with
        (bytes_read_so_far, total_bytes_or_None) — None when the server
        doesn't send a Content-Length (common for chunked JSON responses),
        in which case the caller can only show an indeterminate/pulsing
        indicator rather than a real percentage."""
        last_error: Exception | None = None
        for attempt in range(retries):
            for base in self._base_urls:
                try:
                    with self._session.get(
                        f"{base}{path}", params=params, timeout=timeout,
                        proxies=self.proxies, stream=progress_cb is not None,
                    ) as resp:
                        resp.raise_for_status()
                        if progress_cb is None:
                            return resp.json()
                        total = resp.headers.get("Content-Length")
                        total = int(total) if total is not None else None
                        chunks = bytearray()
                        for chunk in resp.iter_content(chunk_size=65536):
                            chunks.extend(chunk)
                            progress_cb(len(chunks), total)
                        return json.loads(bytes(chunks))
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                    continue
            if attempt < retries - 1:
                log.warning("Radio Browser request failed on all servers (attempt %d/%d): %s — retrying",
                            attempt + 1, retries, last_error)
                time.sleep(retry_delay)
        # Full technical detail (exact host/DNS error) goes to the log above
        # on every retry — this final message is what a user actually sees,
        # so it stays actionable instead of a raw exception dump.
        log.warning("Radio Browser unreachable on every mirror after %d attempt(s): %s", retries, last_error)
        raise StationAPIError(
            "Could not reach the Radio Browser station database — check your internet "
            "connection, or firewall/VPN settings if one is active. Your existing "
            "station list hasn't been changed."
        )

    def search(self, name: str, limit: int = 100) -> list[Station]:
        raw = self._get("/json/stations/search", {"name": name, "limit": limit})
        return [Station.from_api(r) for r in raw]

    def bulk_stations(self, limit: int = 100000,
                       progress_cb: Optional[Callable[[int, Optional[int]], None]] = None) -> list[Station]:
        """One call for the whole database (currently ~61,000 stations).

        Far cheaper than issuing one HTTP request per genre/country/language:
        a single request for the full catalog takes well under a minute,
        versus dozens of sequential per-category requests for a much
        narrower result set. The limit is set generously above the current
        real count so catalog growth doesn't silently truncate results.

        Needs a much longer timeout than every other call here: downloading
        ~60k+ station records routinely takes 30-45+ seconds. The default
        10s timeout (fine for search/click) previously made this request
        fail on the fast/working mirror and silently fall through to broken
        ones, so it always failed end to end. Also retries a few times with
        a short backoff: the API occasionally returns a transient
        "503 no available server" under load that clears up on its own
        within seconds (reproduced directly — an identical retry succeeded).
        """
        raw = self._get(
            "/json/stations",
            {"limit": limit, "order": "name", "hidebroken": "true"},
            timeout=120, retries=3, retry_delay=8.0, progress_cb=progress_cb,
        )
        return [Station.from_api(r) for r in raw]

    def click(self, station_uuid: str) -> None:
        """Register a listen with Radio Browser (best-effort, non-fatal)."""
        try:
            self._session.get(
                f"{self._base_urls[0]}/json/url/{station_uuid}", timeout=5, proxies=self.proxies
            )
        except requests.RequestException:
            pass


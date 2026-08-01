"""ID3 tag writing for recorded audio files, via mutagen."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TDRC, APIC
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from mutagen.oggvorbis import OggVorbis

from .metadata import TrackInfo

log = logging.getLogger(__name__)


def _download_cover(url: str, proxies: Optional[dict] = None) -> Optional[bytes]:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=8, proxies=proxies)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        return None


def tag_mp3(filepath: str, info: TrackInfo, station_name: str, proxies: Optional[dict] = None) -> None:
    try:
        audio = ID3(filepath)
    except ID3NoHeaderError:
        audio = ID3()

    audio["TIT2"] = TIT2(encoding=3, text=info.title or "Unknown Track")
    audio["TPE1"] = TPE1(encoding=3, text=info.artist or "Unknown")
    audio["TALB"] = TALB(encoding=3, text=info.album or station_name)
    audio["TDRC"] = TDRC(encoding=3, text=str(datetime.now().year))

    cover = _download_cover(info.cover_art_url, proxies=proxies)
    if cover:
        audio["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover)

    audio.save(filepath)


def tag_flac(filepath: str, info: TrackInfo, station_name: str, proxies: Optional[dict] = None) -> None:
    audio = FLAC(filepath)
    audio["title"] = info.title or "Unknown Track"
    audio["artist"] = info.artist or "Unknown"
    audio["album"] = info.album or station_name
    audio["date"] = str(datetime.now().year)

    cover = _download_cover(info.cover_art_url, proxies=proxies)
    if cover:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.desc = "Cover"
        pic.data = cover
        audio.clear_pictures()
        audio.add_picture(pic)

    audio.save()


def tag_ogg(filepath: str, info: TrackInfo, station_name: str, proxies: Optional[dict] = None) -> None:
    audio = OggVorbis(filepath)
    audio["title"] = info.title or "Unknown Track"
    audio["artist"] = info.artist or "Unknown"
    audio["album"] = info.album or station_name
    audio["date"] = str(datetime.now().year)
    audio.save()


def tag_file(filepath: str, info: TrackInfo, station_name: str, fmt: str,
             proxies: Optional[dict] = None) -> None:
    """Best-effort tagging; unsupported/unknown formats (wav, aac) are skipped silently."""
    fmt = fmt.lower()
    try:
        if fmt == "mp3":
            tag_mp3(filepath, info, station_name, proxies=proxies)
        elif fmt == "flac":
            tag_flac(filepath, info, station_name, proxies=proxies)
        elif fmt == "ogg":
            tag_ogg(filepath, info, station_name, proxies=proxies)
        else:
            log.info("No tag writer for format '%s'; skipping ID3 tagging", fmt)
    except Exception:
        log.exception("Failed to write tags to %s", filepath)

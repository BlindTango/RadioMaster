"""Shared ICY ("now playing") metadata poller, used by both live playback and
headless/scheduled recording (both need independent title-change notifications)."""

from __future__ import annotations

import re
import threading
from typing import Callable, Optional

import requests

ICY_USER_AGENT = "RadioMaster/1.0"


def icy_metadata_loop(url: str, proxies: Optional[dict], stop_event: threading.Event,
                       on_title_changed: Callable[[str], None]) -> None:
    """Blocks until stop_event is set or the stream ends; calls on_title_changed()
    each time the station's StreamTitle actually changes. Silently returns if the
    stream has no ICY metadata support (most stations do; some don't)."""
    try:
        resp = requests.get(
            url, headers={"Icy-MetaData": "1", "User-Agent": ICY_USER_AGENT},
            stream=True, timeout=10, proxies=proxies,
        )
    except requests.RequestException:
        return
    metaint = resp.headers.get("icy-metaint")
    if not metaint:
        resp.close()
        return
    metaint = int(metaint)
    last_title = ""
    try:
        raw = resp.raw
        while not stop_event.is_set():
            audio = raw.read(metaint)
            if not audio:
                break
            length_byte = raw.read(1)
            if not length_byte:
                break
            meta_len = length_byte[0] * 16
            meta = raw.read(meta_len) if meta_len else b""
            if meta:
                text = meta.decode("utf-8", errors="ignore").rstrip("\x00")
                match = re.search(r"StreamTitle='([^']*)'", text)
                if match and match.group(1) != last_title:
                    last_title = match.group(1)
                    on_title_changed(last_title)
    except (OSError, ValueError):
        pass
    finally:
        resp.close()

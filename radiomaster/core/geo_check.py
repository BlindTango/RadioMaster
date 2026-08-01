"""Best-effort detection of geo/licence-restricted stream URLs.

Radio Browser stations are frequently blocked for listeners outside the
broadcaster's licensed region. Servers signal this in different ways, but
the two conventions that actually mean "blocked because of where you are"
(rather than "temporarily down") are HTTP 403 Forbidden and 451 Unavailable
For Legal Reasons. This is a single short-lived HTTP request purely for
diagnostics/logging — it never blocks or delays playback, which continues
to fail/report exactly as it did before.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

GEO_BLOCK_STATUS_CODES = {403, 451}
USER_AGENT = "RadioMaster/1.0"


def log_if_geo_restricted(station_name: str, url: str, proxies: Optional[dict] = None,
                           timeout: float = 5.0) -> None:
    """Fire-and-forget diagnostic check, safe to call from a daemon thread
    after a stream connection fails. Logs a warning if the server's response
    looks like a geographic/licensing block; does nothing otherwise (a
    timeout, DNS failure, or any other status is NOT assumed to be geo
    blocking — that's just "unreachable", already logged separately)."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=timeout,
            proxies=proxies, stream=True,
        )
        resp.close()
    except requests.RequestException:
        return
    if resp.status_code in GEO_BLOCK_STATUS_CODES:
        log.warning(
            "Station '%s' appears to be geo-restricted (HTTP %d from %s) — "
            "it is likely unavailable in your current region.",
            station_name, resp.status_code, url,
        )

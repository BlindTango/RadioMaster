"""Fetches the Radio Browser catalog and upserts it into the local SQLite station DB."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .station_api import StationAPI, StationAPIError
from .station_db import StationDB

log = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    ok: bool
    changed: int = 0
    unchanged: int = 0
    total_fetched: int = 0
    error: str = ""


class StationUpdater:
    def __init__(self, api: StationAPI, db: StationDB):
        self.api = api
        self.db = db

    def update_now(self, bulk_limit: int = 100000,
                    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None) -> UpdateResult:
        try:
            stations = self.api.bulk_stations(limit=bulk_limit, progress_cb=progress_cb)
        except StationAPIError as exc:
            log.warning("Station DB update failed: %s", exc)
            return UpdateResult(ok=False, error=str(exc))

        changed, unchanged = self.db.upsert_stations(stations)
        log.info("Station DB update: %d changed, %d unchanged (of %d fetched)",
                  changed, unchanged, len(stations))
        return UpdateResult(ok=True, changed=changed, unchanged=unchanged, total_fetched=len(stations))

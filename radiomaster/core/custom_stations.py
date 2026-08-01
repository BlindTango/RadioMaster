"""User-added custom stations — custom_stations.json, merged into the station tree."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid as uuid_mod

from ..utils.paths import state_dir
from .station_api import Station

log = logging.getLogger(__name__)

CUSTOM_PREFIX = "custom-"


class CustomStationsStore:
    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(state_dir(), "custom_stations.json")
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        self._items = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._items = []

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._items, f, indent=2)
                os.replace(tmp, self._path)
            except OSError:
                log.exception("Failed to save custom stations to %s", self._path)

    def all(self) -> list[Station]:
        with self._lock:
            return [Station.from_dict(d) for d in self._items]

    def add(self, name: str, url: str, genre: str = "", country: str = "",
             language: str = "", network: str = "", bitrate: int = 0) -> Station:
        station = Station(
            uuid=f"{CUSTOM_PREFIX}{uuid_mod.uuid4()}",
            name=f"★ {name}",
            url=url,
            tags=genre,
            country=country,
            language=language,
            network=network,
            bitrate=bitrate,
        )
        with self._lock:
            self._items.append(station.to_dict())
        self.save()
        return station

    def remove(self, uuid: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.get("uuid") != uuid]
        self.save()

    @staticmethod
    def is_custom(uuid: str) -> bool:
        return uuid.startswith(CUSTOM_PREFIX)

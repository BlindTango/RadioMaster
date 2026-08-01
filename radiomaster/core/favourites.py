"""Favourites storage — favourites.json in the portable app directory."""

from __future__ import annotations

import json
import os
import threading

from ..utils.paths import state_dir
from .station_api import Station


class FavouritesStore:
    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(state_dir(), "favourites.json")
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
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2)
            os.replace(tmp, self._path)

    def all(self) -> list[Station]:
        with self._lock:
            return [Station.from_dict(d) for d in self._items]

    def contains(self, uuid: str) -> bool:
        with self._lock:
            return any(item.get("uuid") == uuid for item in self._items)

    def add(self, station: Station) -> None:
        with self._lock:
            if any(item.get("uuid") == station.uuid for item in self._items):
                return
            self._items.append(station.to_dict())
        self.save()

    def remove(self, uuid: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.get("uuid") != uuid]
        self.save()

    def move(self, uuid: str, new_index: int) -> None:
        with self._lock:
            idx = next((i for i, item in enumerate(self._items) if item.get("uuid") == uuid), None)
            if idx is None:
                return
            item = self._items.pop(idx)
            new_index = max(0, min(new_index, len(self._items)))
            self._items.insert(new_index, item)
        self.save()

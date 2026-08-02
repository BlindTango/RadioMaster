"""Podcast subscriptions store — podcast_subscriptions.json in the portable app directory.

Mirrors favourites.py/custom_stations.py's load/save-on-write pattern.
"""

from __future__ import annotations

import json
import logging
import os
import threading

from ..utils.paths import state_dir
from .podcast_api import PodcastResult

log = logging.getLogger(__name__)


class PodcastSubscriptionsStore:
    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(state_dir(), "podcast_subscriptions.json")
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
                log.exception("Failed to save podcast subscriptions to %s", self._path)

    def all(self) -> list[PodcastResult]:
        with self._lock:
            return [PodcastResult.from_dict(d) for d in self._items]

    def contains(self, feed_url: str) -> bool:
        with self._lock:
            return any(item.get("feed_url") == feed_url for item in self._items)

    def subscribe(self, podcast: PodcastResult) -> None:
        with self._lock:
            if any(item.get("feed_url") == podcast.feed_url for item in self._items):
                return
            self._items.append(podcast.to_dict())
        self.save()

    def unsubscribe(self, feed_url: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.get("feed_url") != feed_url]
        self.save()

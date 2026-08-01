"""Flexible recording scheduler: one-time, daily, weekly, Nth-weekday-of-month, custom interval."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid as uuid_mod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..utils.paths import state_dir

log = logging.getLogger(__name__)

WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Schedule:
    id: str
    station_uuid: str
    station_name: str
    station_url: str
    schedule_type: str  # one_time | daily | weekly | nth_weekday | interval
    duration_minutes: Optional[int]  # None = "until stop"
    output_format: str = "mp3"
    enabled: bool = True

    # one_time
    start_datetime: Optional[str] = None  # ISO string

    # daily / weekly
    time_of_day: Optional[str] = None  # "HH:MM"
    weekdays: list[str] = field(default_factory=list)  # subset of WEEKDAY_NAMES, for weekly

    # nth_weekday (e.g. "every 3rd Monday")
    ordinal: Optional[int] = None  # 1-4, or -1 for "last"
    weekday: Optional[str] = None

    # custom interval
    interval_days: Optional[int] = None
    interval_start: Optional[str] = None  # ISO string, first run

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        known = {k: data.get(k) for k in cls.__dataclass_fields__}
        known["weekdays"] = known.get("weekdays") or []
        known["enabled"] = known.get("enabled", True)
        known["output_format"] = known.get("output_format") or "mp3"
        return cls(**known)

    def describe(self) -> str:
        dur = f"{self.duration_minutes}m" if self.duration_minutes else "until stop"
        if self.schedule_type == "one_time":
            return f"{self.start_datetime} — {self.station_name} ({dur})"
        if self.schedule_type == "daily":
            return f"Daily {self.time_of_day} — {self.station_name} ({dur})"
        if self.schedule_type == "weekly":
            days = ",".join(w.title() for w in self.weekdays)
            return f"{days} {self.time_of_day} — {self.station_name} ({dur})"
        if self.schedule_type == "nth_weekday":
            ord_name = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", -1: "Last"}.get(self.ordinal, "?")
            return f"{ord_name} {self.weekday.title()} {self.time_of_day} — {self.station_name} ({dur})"
        if self.schedule_type == "interval":
            return f"Every {self.interval_days}d from {self.interval_start} — {self.station_name} ({dur})"
        return f"{self.station_name} ({dur})"


class ScheduleStore:
    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(state_dir(), "schedules.json")
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

    def all(self) -> list[Schedule]:
        with self._lock:
            return [Schedule.from_dict(d) for d in self._items]

    def add(self, schedule: Schedule) -> None:
        with self._lock:
            self._items.append(schedule.to_dict())
        self.save()

    def update(self, schedule: Schedule) -> None:
        with self._lock:
            for i, item in enumerate(self._items):
                if item.get("id") == schedule.id:
                    self._items[i] = schedule.to_dict()
                    break
        self.save()

    def remove(self, schedule_id: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.get("id") != schedule_id]
        self.save()


def new_schedule_id() -> str:
    return str(uuid_mod.uuid4())


def _time_window(sched: Schedule) -> tuple[str, int]:
    """Return (HH:MM, duration_minutes) for overlap comparisons; duration None -> 1440 (worst case)."""
    return sched.time_of_day or "00:00", sched.duration_minutes or 24 * 60


def find_conflicts(schedules: list[Schedule]) -> list[tuple[Schedule, Schedule]]:
    """Best-effort conflict detection for recurring schedules sharing a day-of-week,
    and for one-time schedules whose windows overlap."""
    conflicts: list[tuple[Schedule, Schedule]] = []
    enabled = [s for s in schedules if s.enabled]

    def overlaps(t1: str, d1: int, t2: str, d2: int) -> bool:
        def to_minutes(t: str) -> int:
            h, m = t.split(":")
            return int(h) * 60 + int(m)
        start1, start2 = to_minutes(t1), to_minutes(t2)
        end1, end2 = start1 + d1, start2 + d2
        return start1 < end2 and start2 < end1

    def days_for(s: Schedule) -> set[str]:
        if s.schedule_type == "daily":
            return set(WEEKDAY_NAMES)
        if s.schedule_type == "weekly":
            return set(s.weekdays)
        if s.schedule_type == "nth_weekday" and s.weekday:
            return {s.weekday}
        return set()

    recurring = [s for s in enabled if s.schedule_type in ("daily", "weekly", "nth_weekday")]
    for i, a in enumerate(recurring):
        for b in recurring[i + 1:]:
            if days_for(a) & days_for(b):
                t1, d1 = _time_window(a)
                t2, d2 = _time_window(b)
                if overlaps(t1, d1, t2, d2):
                    conflicts.append((a, b))

    one_time = [s for s in enabled if s.schedule_type == "one_time" and s.start_datetime]
    for i, a in enumerate(one_time):
        for b in one_time[i + 1:]:
            a_start = datetime.fromisoformat(a.start_datetime)
            b_start = datetime.fromisoformat(b.start_datetime)
            a_end = a_start + timedelta(minutes=a.duration_minutes or 60)
            b_end = b_start + timedelta(minutes=b.duration_minutes or 60)
            if a_start < b_end and b_start < a_end:
                conflicts.append((a, b))

    return conflicts


class RecordingScheduler:
    """Wraps APScheduler to fire on_trigger(schedule) at the right times."""

    def __init__(self, store: ScheduleStore, on_trigger: Callable[[Schedule], None]):
        self.store = store
        self.on_trigger = on_trigger
        self._scheduler = BackgroundScheduler()
        self._job_ids: dict[str, str] = {}

    def start(self) -> None:
        self._scheduler.start()
        self.reload()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def reload(self) -> None:
        for job_id in list(self._job_ids.values()):
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        self._job_ids.clear()
        for sched in self.store.all():
            if sched.enabled:
                self._add_job(sched)

    def _add_job(self, sched: Schedule) -> None:
        trigger = self._build_trigger(sched)
        if trigger is None:
            return
        job = self._scheduler.add_job(self.on_trigger, trigger, args=[sched], id=sched.id, replace_existing=True)
        self._job_ids[sched.id] = job.id

    def _build_trigger(self, sched: Schedule):
        if sched.schedule_type == "one_time" and sched.start_datetime:
            return DateTrigger(run_date=datetime.fromisoformat(sched.start_datetime))

        if sched.schedule_type == "daily" and sched.time_of_day:
            h, m = sched.time_of_day.split(":")
            return CronTrigger(hour=int(h), minute=int(m))

        if sched.schedule_type == "weekly" and sched.time_of_day and sched.weekdays:
            h, m = sched.time_of_day.split(":")
            return CronTrigger(day_of_week=",".join(sched.weekdays), hour=int(h), minute=int(m))

        if sched.schedule_type == "nth_weekday" and sched.time_of_day and sched.weekday and sched.ordinal:
            h, m = sched.time_of_day.split(":")
            wd = f"{sched.weekday}"
            wd_expr = f"{wd} last" if sched.ordinal == -1 else f"{wd}/{sched.ordinal}"
            # APScheduler CronTrigger doesn't directly support "3rd Monday"; approximate with
            # a day_of_week filter plus a day-range guard evaluated at trigger time isn't native,
            # so fire every matching weekday and let the callback verify ordinal-of-month.
            return CronTrigger(day_of_week=wd, hour=int(h), minute=int(m))

        if sched.schedule_type == "interval" and sched.interval_days and sched.interval_start:
            return IntervalTrigger(
                days=sched.interval_days,
                start_date=datetime.fromisoformat(sched.interval_start),
            )

        log.warning("Could not build trigger for schedule %s (%s)", sched.id, sched.schedule_type)
        return None


def is_nth_weekday_match(sched: Schedule, when: Optional[datetime] = None) -> bool:
    """For nth_weekday schedules the cron fires every matching weekday; call this in the
    on_trigger callback to filter down to the configured ordinal occurrence."""
    when = when or datetime.now()
    if sched.ordinal == -1:
        next_week = when + timedelta(days=7)
        return next_week.month != when.month
    occurrence = (when.day - 1) // 7 + 1
    return occurrence == sched.ordinal

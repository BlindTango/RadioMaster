"""Background schedule for refreshing the local station database.

Runs the fetch on a daemon thread (network + SQLite writes) so it never
blocks the UI, at a fixed off-peak hour appropriate to the chosen frequency.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .station_updater import StationUpdater, UpdateResult

log = logging.getLogger(__name__)

UPDATE_OFF_HOUR = 3  # run at 3 AM local time — quiet, off-peak

FREQUENCIES = ["off", "daily", "weekly", "monthly", "quarterly", "six_monthly", "yearly"]

FREQUENCY_LABELS = {
    "off": "Off (manual only)",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "six_monthly": "Every 6 months",
    "yearly": "Yearly",
}


def _cron_kwargs(frequency: str) -> Optional[dict]:
    if frequency == "daily":
        return {"hour": UPDATE_OFF_HOUR, "minute": 0}
    if frequency == "weekly":
        return {"day_of_week": "sun", "hour": UPDATE_OFF_HOUR, "minute": 0}
    if frequency == "monthly":
        return {"day": 1, "hour": UPDATE_OFF_HOUR, "minute": 0}
    if frequency == "quarterly":
        return {"month": "1,4,7,10", "day": 1, "hour": UPDATE_OFF_HOUR, "minute": 0}
    if frequency == "six_monthly":
        return {"month": "1,7", "day": 1, "hour": UPDATE_OFF_HOUR, "minute": 0}
    if frequency == "yearly":
        return {"month": 1, "day": 1, "hour": UPDATE_OFF_HOUR, "minute": 0}
    return None  # "off"


class StationUpdateScheduler:
    JOB_ID = "station_db_update"

    def __init__(self, updater: StationUpdater, on_result: Optional[Callable[[UpdateResult], None]] = None):
        self.updater = updater
        self.on_result = on_result
        self._scheduler = BackgroundScheduler()
        self._started = False

    def start(self, frequency: str) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True
        self.set_frequency(frequency)

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    def set_frequency(self, frequency: str) -> None:
        try:
            self._scheduler.remove_job(self.JOB_ID)
        except Exception:
            pass
        kwargs = _cron_kwargs(frequency)
        if kwargs is None:
            return
        self._scheduler.add_job(
            self._run, CronTrigger(**kwargs), id=self.JOB_ID, replace_existing=True,
        )

    def update_now_async(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            result = self.updater.update_now()
        except Exception:
            log.exception("Scheduled station DB update failed")
            result = UpdateResult(ok=False, error="Unexpected error — see log")
        if self.on_result:
            self.on_result(result)

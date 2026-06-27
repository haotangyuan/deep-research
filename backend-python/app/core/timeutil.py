from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().app_time_zone)).replace(tzinfo=None)


def today_str() -> str:
    return now_local().date().isoformat()


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    zone = ZoneInfo(get_settings().app_time_zone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    else:
        value = value.astimezone(zone)
    return value.isoformat(timespec="seconds")

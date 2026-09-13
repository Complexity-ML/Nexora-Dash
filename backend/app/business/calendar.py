from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def business_today(zone: str, instant: datetime | None = None):
    return (instant or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone)).date()

from datetime import datetime, date
from app.business.calendar import business_today
from app.config import Settings
import pytest

def test_business_dates_follow_configured_zone_at_midnight():
    assert business_today('Europe/Paris',datetime.fromisoformat('2026-09-11T22:30:00+00:00')) == date(2026,9,12)
    assert business_today('America/Los_Angeles',datetime.fromisoformat('2026-09-12T02:30:00+00:00')) == date(2026,9,11)
    assert business_today('Europe/Paris',datetime.fromisoformat('2026-03-29T01:30:00+00:00')) == date(2026,3,29)
    with pytest.raises(ValueError):
        Settings(business_timezone='Not/AZone')

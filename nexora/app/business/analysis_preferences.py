"""Persisted analysis preferences, independent of the UI transport."""
from app.config import get_settings


def read_settings(store):
    with store.connect() as db:
        row = db.execute('SELECT threshold,buffer,version FROM analysis_settings WHERE id=1').fetchone()
    defaults = get_settings()
    return dict(row) if row else {'threshold':defaults.underutilization_threshold, 'buffer':defaults.recovery_buffer_rate, 'version':0}

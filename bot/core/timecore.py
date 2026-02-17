from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

def now_utc_ts():
    return int(datetime.now(timezone.utc).timestamp())

def day_key_from_utc_ts(utc_ts, tz_name, grace_hour):
    tz = ZoneInfo(tz_name)
    local = datetime.fromtimestamp(utc_ts, tz=timezone.utc).astimezone(tz)
    shifted = local - timedelta(hours=grace_hour)
    return shifted.date().toordinal()

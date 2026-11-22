import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_date(value, reference=None):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    raw = str(value).strip()
    now = reference or utcnow()
    relative = re.fullmatch(r"(\d+)\s+(minutes?|mins?|hours?|days?)\s+ago", raw, flags=re.I)
    if relative:
        from datetime import timedelta
        n = int(relative.group(1))
        unit = relative.group(2).lower()
        if unit.startswith("min"):
            return now - timedelta(minutes=n)
        if unit.startswith("hour"):
            return now - timedelta(hours=n)
        return now - timedelta(days=n)
    try:
        parsed = parser.parse(raw)
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, TypeError):
        return None


def fresh_within_24_hours(value, reference=None):
    from datetime import timedelta
    now = reference or utcnow()
    dt = parse_date(value, now)
    return dt is not None and now - timedelta(hours=24) <= dt <= now


def canonical_url(url):
    parts = urlsplit((url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))


def sha256(value):
    if not isinstance(value, (bytes, bytearray)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(value).hexdigest()

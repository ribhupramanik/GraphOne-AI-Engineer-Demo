import logging

from .entities import Resolver
from .utils import iso, utcnow

LOG = logging.getLogger(__name__)
YC_URLS = [
    "https://yc-oss.github.io/api/companies/all.json",
    "https://devasheeshg.github.io/yc-api/companies/all.json",
]


async def acquire_startups(fetcher, store, *, limit=1000, resolver=None):
    resolver = resolver or Resolver()
    data = None
    for url in YC_URLS:
        try:
            data = await fetcher.get_json(url)
            break
        except Exception as exc:
            LOG.warning("YC source unavailable %s (%s)", url, type(exc).__name__)
    if data is None:
        raise RuntimeError("All YC company dataset mirrors unavailable")
    if isinstance(data, dict):
        data = data.get("companies", data.get("data", []))
    if not isinstance(data, list):
        raise TypeError("YC source returned unexpected structure")
    accepted = 0
    seen = set()
    for item in data:
        raw = (item.get("name") or "").strip()
        slug = item.get("slug") or ""
        if not raw or not slug:
            continue
        key = slug.casefold()
        if key in seen:
            continue
        seen.add(key)
        canonical, method, score = resolver.resolve(raw)
        source_url = "https://www.ycombinator.com/companies/" + slug.strip("/")
        count = item.get("team_size") or item.get("employee_count")
        try:
            count = int(count) if count not in (None, "") else None
            if count is not None and count < 0:
                count = None
        except (TypeError, ValueError):
            count = None
        entity = {
            "schemaVersion": "1.0", "recordType": "STARTUP",
            "source": {"name": "Y Combinator company directory (community JSON mirror)", "url": source_url},
            "content": {
                "entityName": canonical,
                "data": {"employeeCount": count},
                "description": item.get("one_liner") or item.get("long_description") or None,
                "website": item.get("website") or None,
                "batch": item.get("batch") or None,
            },
            "collectedAt": iso(utcnow()),
        }
        store.upsert(entity, key, item)
        store.log_mapping(raw, canonical, method, score, source_url)
        accepted += 1
        if accepted >= limit:
            break
    LOG.info("startups inserted=%s requested=%s", accepted, limit)
    return accepted

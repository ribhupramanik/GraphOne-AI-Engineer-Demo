from .signals import JOB_SOURCES, NEWS_SOURCES
from .utils import canonical_url, fresh_within_24_hours, utcnow

MINIMUM_COUNTS = {"STARTUP": 1000, "PRODUCT": 1000, "RESEARCH_PAPER": 1000}
VALID_PRICING = {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}


def validate_submission(store, *, now=None):
    now = now or utcnow()
    counts = store.counts()
    issues = []
    for kind, minimum in MINIMUM_COUNTS.items():
        actual = counts.get(kind, 0)
        if actual < minimum:
            issues.append(f"{kind}: {actual}/{minimum} verified rows (minimum not met)")
    for record_type in ("STARTUP", "PRODUCT", "RESEARCH_PAPER", "JOB", "NEWS"):
        for entity in store.get_records(record_type):
            content = entity.get("content", {})
            url = entity.get("source", {}).get("url")
            if not canonical_url(url):
                issues.append(f"{record_type}: missing/invalid source URL")
            if record_type == "RESEARCH_PAPER":
                if not isinstance(content.get("github_stars"), int) or not canonical_url(content.get("github_url")):
                    issues.append(f"RESEARCH_PAPER: unverified GitHub metrics ({url})")
                if not content.get("title") or not content.get("authors") or not content.get("published_date"):
                    issues.append(f"RESEARCH_PAPER: incomplete metadata ({url})")
            if record_type == "PRODUCT" and content.get("pricingModel") not in VALID_PRICING | {None}:
                issues.append(f"PRODUCT: invalid pricing enum ({url})")
            if record_type in ("NEWS", "JOB"):
                published = content.get("published_date") if record_type == "NEWS" else content.get("date")
                if not fresh_within_24_hours(published, now):
                    issues.append(f"{record_type}: older than 24 hours at validation ({url})")
    checks = {(row["type"], row["name"]): row for row in store.source_checks()}
    for kind, sources in (("NEWS", NEWS_SOURCES), ("JOB", JOB_SOURCES)):
        for name in sources:
            row = checks.get((kind, name))
            if row is None:
                issues.append(f"{kind}: source not checked ({name})")
            elif row["status"] != "ok":
                issues.append(f"{kind}: source failed ({name})")
    return {"ready": not issues, "counts": counts, "checkedSources": len(checks),
            "issues": issues, "validatedAt": now.isoformat()}

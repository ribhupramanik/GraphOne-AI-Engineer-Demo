"""Reconcile existing stored entities against observed source evidence, without requests."""

from collections import Counter
import json

from .entities import Resolver, normalise_name


def _raw_name(record_type, row):
    evidence = json.loads(row["raw_payload"])
    content = json.loads(row["payload"]).get("content", {})
    if record_type == "STARTUP":
        return evidence.get("name") or content.get("entityName")
    if record_type == "JOB":
        return evidence.get("company") or content.get("company")
    return None


def reconcile_entities(store, *, dry_run=False):
    """Atomic/idempotent remapping of STARTUP, JOB and verified org Space ownership.

    It does NOT change record keys, invent publisher organizations, or discard evidence.
    """
    columns = ("record_type", "canonical_key", "payload", "raw_payload")
    rows = [dict(zip(columns, row)) for row in store.db.execute(
        "SELECT record_type, canonical_key, payload, raw_payload "
        "FROM records WHERE record_type IN ('STARTUP', 'JOB', 'PRODUCT')"
    )]
    directory_names = [_raw_name("STARTUP", r) for r in rows if r["record_type"] == "STARTUP"]
    job_names = [_raw_name("JOB", r) for r in rows if r["record_type"] == "JOB"]
    resolver = Resolver(directory_names=directory_names, observed_job_names=job_names)
    mappings = []
    updates = []
    methods = Counter()
    changed = Counter()

    for row in rows:
        kind = row["record_type"]
        data = json.loads(row["payload"])
        content = data.get("content", {})
        url = data.get("source", {}).get("url", "")
        if kind in ("STARTUP", "JOB"):
            raw = _raw_name(kind, row)
            canonical, method, score = resolver.resolve(
                raw, source="directory" if kind == "STARTUP" else "job"
            )
            if not raw or not canonical:
                continue
            field = "entityName" if kind == "STARTUP" else "company"
            if content.get(field) != canonical:
                content[field] = canonical
                updates.append((json.dumps(data, ensure_ascii=False, sort_keys=True), kind, row["canonical_key"]))
                changed[kind] += 1
            mappings.append((raw, canonical, method, score, url))
            methods[method] += 1
        elif kind == "PRODUCT":
            raw_payload = json.loads(row["raw_payload"])
            repo = raw_payload.get("id") or raw_payload.get("_id")
            if not isinstance(repo, str) or "/" not in repo:
                continue
            owner = repo.split("/", 1)[0]
            # A matching handle is only a name clue. Use the original curated seed
            # and never infer that unrecognized individual usernames are companies.
            key = normalise_name(owner)
            if key not in resolver.aliases:
                continue
            canonical = resolver.aliases[key]
            if content.get("startupName") != canonical:
                content["startupName"] = canonical
                updates.append((json.dumps(data, ensure_ascii=False, sort_keys=True), kind, row["canonical_key"]))
                changed[kind] += 1
            mappings.append((owner, canonical, "publisher_handle_seed_match", 0.75, url))
            methods["publisher_handle_seed_match"] += 1

    if dry_run:
        return {
            "dry_run": True,
            "records_examined": len(rows),
            "record_values_would_change": dict(changed),
            "mapping_rows": len(set((a, b, e) for a, b, _, _, e in mappings)),
            "methods": dict(sorted(methods.items())),
            "note": "Directory-observed labels are not proof of cross-source entity equivalence",
        }

    store.db.execute("BEGIN IMMEDIATE")
    try:
        store.db.executemany(
            "UPDATE records SET payload=? WHERE record_type=? AND canonical_key=?", updates
        )
        store.db.execute("DELETE FROM mapping_log")
        store.db.executemany(
            "INSERT OR IGNORE INTO mapping_log VALUES (?, ?, ?, ?, ?)", mappings
        )
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise

    return {
        "records_examined": len(rows),
        "record_values_changed": dict(changed),
        "mapping_rows": len(set((a, b, e) for a, b, _, _, e in mappings)),
        "methods": dict(sorted(methods.items())),
        "note": "Directory-observed labels are not proof of cross-source entity equivalence",
    }

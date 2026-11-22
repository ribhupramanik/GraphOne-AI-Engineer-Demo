"""Prepare provenance-preserving, currently fresh CSVs for the public Google Sheet."""

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHEETS = (
    ("Startups", "startups.csv", None),
    ("Products", "products.csv", None),
    ("Research Papers", "research_papers.csv", None),
    ("Jobs", "jobs.csv", "content.date"),
    ("News", "news.csv", "content.published_date"),
    ("Entity Mapping Log", "entity_mapping_log.csv", None),
)

GENERIC_DESCRIPTION_MARKERS = (
    "check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference",
    "check out the configuration reference at https://huggingface.co/docs/hub/spaces#reference",
)


def _parse_publication_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def _is_fresh(value, as_of):
    published = _parse_publication_date(value)
    return published is not None and as_of - timedelta(hours=24) <= published <= as_of


def _prepare_rows(sheet_name, fieldnames, rows, as_of):
    if sheet_name == "Products":
        if "content.description" not in fieldnames:
            raise ValueError("Products CSV is missing content.description")
        generic_cleared = 0
        for row in rows:
            description = (row.get("content.description") or "").casefold()
            if any(marker in description for marker in GENERIC_DESCRIPTION_MARKERS):
                row["content.description"] = ""
                generic_cleared += 1
        return rows, {"generic_descriptions_cleared": generic_cleared}

    if sheet_name in ("Jobs", "News"):
        field = "content.date" if sheet_name == "Jobs" else "content.published_date"
        if field not in fieldnames:
            raise ValueError("{} CSV is missing {}".format(sheet_name, field))
        fresh = [row for row in rows if _is_fresh(row.get(field), as_of)]
        return fresh, {"outside_24h_or_unverifiable": len(rows) - len(fresh)}

    return rows, {}


def prepare_submission(source_dir="output/csv", target_dir="output/submission", as_of=None):
    source = Path(source_dir)
    target = Path(target_dir)
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        raise ValueError("The reference timestamp must include a timezone")
    as_of = as_of.astimezone(timezone.utc)

    if source.resolve() == target.resolve():
        raise ValueError("Source and destination folders must be different")

    prepared = []
    for sheet_name, filename, _ in SHEETS:
        src = source / filename
        with src.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            if not fieldnames:
                raise ValueError("Missing CSV header in {}".format(src))
            rows = list(reader)

        if sheet_name != "Entity Mapping Log":
            if "source.url" not in fieldnames:
                raise ValueError("{} CSV is missing source.url".format(sheet_name))
            if any(not (row.get("source.url") or "").startswith(("https://", "http://")) for row in rows):
                raise ValueError("{} contains a missing/invalid source.url".format(sheet_name))
            urls = [row["source.url"] for row in rows]
            if len(urls) != len(set(urls)):
                raise ValueError("{} contains duplicate source URLs".format(sheet_name))

        transformed, notes = _prepare_rows(sheet_name, fieldnames, rows, as_of)
        prepared.append((sheet_name, filename, fieldnames, transformed, len(rows), notes))

    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at_utc": as_of.isoformat(),
        "freshness_window_hours": 24,
        "sheets": {},
    }
    for sheet_name, filename, fieldnames, rows, original_count, notes in prepared:
        with (target / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        manifest["sheets"][sheet_name] = {
            "file": filename,
            "source_rows": original_count,
            "submission_rows": len(rows),
            **notes,
        }

    (target / "submission_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Build six source-backed submission CSVs; filter jobs/news at current UTC time")
    parser.add_argument("--source", default="output/csv")
    parser.add_argument("--target", default="output/submission")
    args = parser.parse_args()
    manifest = prepare_submission(args.source, args.target)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

import csv
import json
from pathlib import Path

SHEETS = {
    "Startups": ("STARTUP", ["schemaVersion", "recordType", "source.name", "source.url", "content.entityName", "content.data.employeeCount", "content.description", "content.website", "collectedAt"]),
    "Products": ("PRODUCT", ["schemaVersion", "recordType", "source.name", "source.url", "content.productName", "content.startupName", "content.pricingModel", "content.description", "collectedAt"]),
    "Research Papers": ("RESEARCH_PAPER", ["schemaVersion", "recordType", "source.name", "source.url", "content.title", "content.authors", "content.paper_url", "content.github_url", "content.github_stars", "content.github_stars_collected_at", "content.published_date", "collectedAt"]),
    "Jobs": ("JOB", ["schemaVersion", "recordType", "source.name", "source.url", "content.company", "content.title", "content.date", "content.is_remote", "content.role_family", "content.fullText", "collectedAt"]),
    "News": ("NEWS", ["schemaVersion", "recordType", "source.name", "source.url", "content.title", "content.published_date", "content.fullText", "content.fullTextStatus", "content.summary", "content.llmExtraction", "content.llmExtractionStatus", "collectedAt"]),
    "Entity Mapping Log": (None, ["raw_name", "canonical_name", "method", "score", "source_url"]),
}


def nested_get(record, field):
    node = record
    for part in field.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return json.dumps(node, ensure_ascii=False) if isinstance(node, (list, dict)) else node


def export_csv(store, directory):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    counts = {}
    for sheet_name, (kind, columns) in SHEETS.items():
        path = target / (sheet_name.lower().replace(" ", "_") + ".csv")
        records = store.get_mappings() if kind is None else store.get_records(kind)
        with path.open("w", newline="", encoding="utf-8-sig") as out:
            writer = csv.writer(out)
            writer.writerow(columns)
            if kind is None:
                writer.writerows(records)
            else:
                writer.writerows([nested_get(record, col) for col in columns] for record in records)
        counts[sheet_name] = len(records)
    return counts

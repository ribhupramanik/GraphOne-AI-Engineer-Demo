"""Verify research-paper AI relevance using official arXiv subject metadata."""

import argparse
import csv
import json
import logging
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.papers import parse_arxiv_atom

LOG = logging.getLogger(__name__)
ARXIV_API = "https://export.arxiv.org/api/query"
AI_SUBJECTS = frozenset({"cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.NE", "cs.MA", "stat.ML"})


def paper_id_from_url(url):
    parsed = urlsplit(str(url or ""))
    if parsed.hostname != "arxiv.org" or not parsed.path.startswith("/abs/"):
        return None
    return parsed.path.split("/abs/", 1)[-1].split("v")[0]


def review_papers(rows, category_index):
    ai, other, unavailable = [], [], []
    for row in rows:
        paper_id = paper_id_from_url(row.get("content.paper_url") or row.get("source.url"))
        source = category_index.get(paper_id) if paper_id else None
        if not source:
            unavailable.append(row)
            continue
        categories = set(source.get("categories") or [])
        primary = source.get("primary_category")
        if primary:
            categories.add(primary)
        if not categories:
            unavailable.append(row)
        elif categories & AI_SUBJECTS:
            ai.append(row)
        else:
            other.append(row)
    return ai, other, unavailable


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fetch_categories(ids, user_agent, timeout, retries=3):
    address = ARXIV_API + "?" + urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    request = Request(address, headers={"User-Agent": user_agent, "Accept": "application/atom+xml"})
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                return parse_arxiv_atom(response.read())
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            status = getattr(exc, "code", None)
            if isinstance(exc, HTTPError) and status not in (429, 500, 502, 503, 504):
                LOG.warning("arxiv permanent error status=%s", status)
                break
            LOG.warning("arxiv category fetch failed status=%s attempt=%d", status, attempt + 1)
            if attempt + 1 < retries:
                time.sleep(4 * (2 ** attempt))
    return {}


def audit_file(source, cache_file, report_file, verified_output, min_ai_papers=1000, batch_size=40, interval=3.1, timeout=30):
    with Path(source).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or "content.paper_url" not in fields:
        raise ValueError("Expected research_papers.csv with content.paper_url column")
    cache = json.loads(Path(cache_file).read_text(encoding="utf-8")) if Path(cache_file).exists() else {}
    all_ids = list(dict.fromkeys(filter(None, (paper_id_from_url(row.get("content.paper_url")) for row in rows))))
    pending = [paper_id for paper_id in all_ids if paper_id not in cache]
    for index in range(0, len(pending), batch_size):
        if index:
            time.sleep(max(3.0, interval))
        batch = pending[index:index + batch_size]
        found = _fetch_categories(batch, os.getenv("USER_AGENT", "GraphOneAIResearchAudit/1.0 (contact: researcher@example.com)"), timeout)
        for paper_id, item in found.items():
            cache[paper_id] = {"primary_category": item.get("primary_category"), "categories": item.get("categories", [])}
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_file).write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
        LOG.info("arxiv subjects processed batch %d/%d; matched=%d", index // batch_size + 1, (len(pending) + batch_size - 1) // batch_size, len(found))
    ai, other, unavailable = review_papers(rows, cache)
    report = {
        "source_rows": len(rows),
        "arxiv_ai_subject_verified": len(ai),
        "other_subject": len(other),
        "unavailable_category_metadata": len(unavailable),
        "ai_subjects_accepted": sorted(AI_SUBJECTS),
        "minimum_required": min_ai_papers,
        "meets_minimum": len(ai) >= min_ai_papers,
        "verified_dataset_written": len(ai) >= min_ai_papers,
        "other_subject_examples": [{"title": row.get("content.title"), "url": row.get("source.url")} for row in other[:15]],
        "unavailable_examples": [{"title": row.get("content.title"), "url": row.get("source.url")} for row in unavailable[:15]],
    }
    Path(report_file).parent.mkdir(parents=True, exist_ok=True)
    Path(report_file).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if len(ai) >= min_ai_papers:
        _write_csv(Path(verified_output), fields, ai)
    return report


def main():
    parser = argparse.ArgumentParser(description="Audit arXiv AI subjects without modifying the submitted dataset")
    parser.add_argument("--source", default="output/submission/research_papers.csv")
    parser.add_argument("--cache", default="output/audit/arxiv_categories_cache.json")
    parser.add_argument("--report", default="output/audit/arxiv_subject_audit.json")
    parser.add_argument("--verified-output", default="output/audit/research_papers_ai_verified.csv")
    parser.add_argument("--min-ai-papers", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--interval", type=float, default=3.1)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if args.min_ai_papers < 1 or args.batch_size < 1 or args.batch_size > 40 or args.interval < 3:
        parser.error("Minimum >=1, batch size 1-40, and interval >=3 seconds are required")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(json.dumps(audit_file(args.source, args.cache, args.report, args.verified_output, args.min_ai_papers, args.batch_size, args.interval, args.timeout), indent=2))


if __name__ == "__main__":
    main()

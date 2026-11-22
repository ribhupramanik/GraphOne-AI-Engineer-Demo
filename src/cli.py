import argparse
import asyncio
import json
import logging
from pathlib import Path

from .config import Settings
from .export import export_csv
from .net import AsyncFetcher
from .reconcile import reconcile_entities
from .llm import MultiTierExtractor
from .papers import acquire_papers
from .products import acquire_huggingface_products, acquire_producthunt
from .product_enrichment import enrich_stored_products
from .signals import enrich_stored_news, fetch_jobs, fetch_news
from .startups import acquire_startups
from .store import Store
from .validate import validate_submission

LOG = logging.getLogger(__name__)


def parse_args(args=None):
    parser = argparse.ArgumentParser(description="GraphOne / FrontierAtlas source-verified intelligence demo")
    parser.add_argument("command", choices=["bulk", "signals", "enrich-news", "reconcile-entities", "enrich-products", "all", "export", "status", "validate"])
    parser.add_argument("--database", default="output/intelligence.db")
    parser.add_argument("--output", default="output/csv")
    parser.add_argument("--startups", type=int, default=1000)
    parser.add_argument("--products", type=int, default=1000)
    parser.add_argument("--papers", type=int, default=1000)
    parser.add_argument("--product-source", choices=["huggingface", "producthunt"], default="huggingface")
    parser.add_argument("--enrich-llm", action="store_true", help="Evidence-gated LLM enrichment for recent news")
    parser.add_argument("--llm-limit", type=int, default=20, help="Maximum news LLM calls per run")
    parser.add_argument("--product-limit", type=int, default=1000, help="Maximum existing products to enrich per run")
    parser.add_argument("--product-workers", type=int, default=4, help="Concurrent product metadata jobs")
    parser.add_argument("--product-force", action="store_true", help="Recheck previously enriched products")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Preview entity reconciliation without modifying SQLite")
    return parser.parse_args(args)


async def run(args, store):
    settings = Settings()
    async with AsyncFetcher(settings) as fetcher:
        if args.command == "enrich-products":
            result = await enrich_stored_products(fetcher, store, limit=args.product_limit, workers=args.product_workers, force=args.product_force)
            print(json.dumps({"product_enrichment": result}, indent=2))
        if args.command == "enrich-news":
            extractor = MultiTierExtractor(fetcher, settings)
            await enrich_stored_news(store, extractor, limit=args.llm_limit)
        if args.command in ("bulk", "all"):
            for label, task in [
                ("startups", lambda: acquire_startups(fetcher, store, limit=args.startups)),
                ("products", lambda: acquire_producthunt(fetcher, store, settings.product_hunt_token, limit=args.products) if args.product_source == "producthunt" else acquire_huggingface_products(fetcher, store, limit=args.products)),
                ("papers", lambda: acquire_papers(fetcher, store, limit=args.papers, github_token=settings.github_token)),
            ]:
                try:
                    result = await task()
                    LOG.info("completed source=%s count=%d", label, result)
                except Exception:
                    LOG.exception("source_failed source=%s; other sources continue", label)
        if args.command in ("signals", "all"):
            extractor = MultiTierExtractor(fetcher, settings) if args.enrich_llm else None
            await asyncio.gather(fetch_news(fetcher, store, extractor=extractor, llm_limit=args.llm_limit),
                                 fetch_jobs(fetcher, store))


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if min(args.startups, args.products, args.papers, args.product_limit) < 0 or args.product_workers < 1:
        raise SystemExit("Row limits must be nonnegative")
    if args.dry_run and args.command != "reconcile-entities":
        raise SystemExit("--dry-run is only supported for reconcile-entities")
    store = Store(args.database)
    try:
        if args.command == "reconcile-entities":
            print(json.dumps({"entity_reconciliation": reconcile_entities(store, dry_run=args.dry_run)}, indent=2))
        elif args.command not in ("export", "status", "validate"):
            asyncio.run(run(args, store))
        if args.command not in ("status", "validate") and not (args.command == "reconcile-entities" and args.dry_run):
            print(json.dumps({"exported": export_csv(store, args.output)}, indent=2))
        checks = store.source_checks()
        if args.command != "status":
            output_dir = Path(args.output).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "source_health.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print(json.dumps({"db_counts": store.counts(), "source_health": checks}, indent=2))
        if args.command == "validate":
            report = validate_submission(store)
            report_path = Path(args.output).parent / "validation_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            if not report["ready"]:
                raise SystemExit(2)
    finally:
        store.close()


if __name__ == "__main__":
    main()

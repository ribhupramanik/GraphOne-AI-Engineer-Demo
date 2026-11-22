# GraphOne / FrontierAtlas - AI Intelligence Graph Demo

An asynchronous, provenance-first intelligence ingestion pipeline for the November 2026 AI Engineer assessment. It collects startups, product/app listings, research papers linked to GitHub repositories, and verified last-24-hour AI news and AI/ML jobs. It **never fabricates missing fields or row counts**.

## Evaluation alignment

| Phase | Implementation |
|---|---|
| I. Bulk extraction | YC company JSON directory, Hugging Face Spaces / Product Hunt GraphQL, archived PWC paper-code links joined with live arXiv + GitHub API |
| II. Fresh signals | 5 publisher feeds, 5 job board APIs, timezone-aware published-at eligibility, article extraction, idempotent URL tracking |
| III. LLM | Gemini Flash -> Groq -> DeepSeek, per-provider fallback, 413 adaptive payload splitting, 429/backoff/jitter, evidence quote validation |
| IV. Entity resolution | 50+ seed companies, normalized exact resolution and conservative fuzzy mapping; raw/canonical audit log |
| V. Anti-bot | Async I/O, per-host pacing, error observability; permitted APIs/feeds, do not evade challenges or captchas |
| VI. Architecture | `architecture.pdf` (3 pages), scalable Postgres + S3 + queue + pgvector/Neo4j production design |

**Scope qualification:** Y Combinator entries are verified YC-backed startup/company directory entries, not *necessarily AI-specific*; Hugging Face Spaces are real AI demos/applications, not necessarily paid commercial products. `startupName` / `pricingModel` are null when their values cannot be verified. This distinction avoids incorrectly labeling a publisher as a startup or guessing pricing. For commercially marketed products use the optional Product Hunt API source with a real token.

## Requirements

- Python 3.11+ (3.12 recommended)
- Network connection to publisher/API endpoints
- **GITHUB_TOKEN strongly recommended** for 1,000 research papers with current stars (GitHub rate limits are substantially stricter without authentication)
- Product Hunt API token *only if* choosing `--product-source producthunt`
- One or more LLM keys *only for optional LLM-based enrichment*

## Installation and execution on macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Populate `.env` with **your own** GitHub personal access token and a real contact email in `USER_AGENT`. Never commit `.env` to GitHub. `GITHUB_TOKEN` needs public repo metadata access; avoid unnecessarily broad scopes.

```bash
pytest -q
python -m src.cli bulk --startups 1000 --products 1000 --papers 1000
python -m src.cli signals
python -m src.cli signals --enrich-llm --llm-limit 10
python -m src.cli status
python -m src.cli validate
python -m src.cli export
```

To run everything together:

```bash
python -m src.cli all --startups 1000 --products 1000 --papers 1000
```

The default persistent SQLite database is `output/intelligence.db`; CSVs are emitted in `output/csv/`. Repeat runs use deterministic keys (UPSERT) and don't duplicate articles. Run `signals` **immediately before submitting**: freshness is calculated against the current UTC time at collection, not a static assignment date. If a feed is blocked or a page lacks a trustworthy publication timestamp, it will be logged/excluded, not silently considered fresh.

If a 1,000-row minimum is not achieved, this program reports the actual count. Do not pad missing rows with fabricated data or manually copy current GitHub stars from an unverified old snapshot. The PWC linking dataset is historical; its paper/repository association is checked against live arXiv/GitHub metadata, and star values are fetched at runtime.

## Six Google Sheets tabs

CSV paths:

- `output/csv/startups.csv`
- `output/csv/products.csv`
- `output/csv/research_papers.csv`
- `output/csv/jobs.csv`
- `output/csv/news.csv`
- `output/csv/entity_mapping_log.csv`

For an **actual public Google Sheets URL**, run the optional OAuth publishing utility once the data is collected. Create a Google Cloud OAuth client credential JSON for a Desktop app, enable the **Google Sheets API** and **Google Drive API**, and place it locally as `credentials.json` (do not commit). Then:

```bash
pip install -r requirements-google.txt
python scripts/publish_to_sheets.py --credentials credentials.json --public
```

Your browser will request Google authorization. The tool creates a spreadsheet with exactly six tabs, uploads the actual CSV values, and gives it public read-only access only when `--public` was explicitly provided. It prints the spreadsheet URL for the employer's form. For an existing spreadsheet, use `--spreadsheet-id ID --public` to refresh without creating a new file. OAuth token is cached locally in `.google_token.json` (gitignored). Alternatively import each CSV in Google Sheets via File > Import and use Share > General access > Anyone with the link > Viewer.

**Do not submit the header-only workbook as actual collected data.** It is an import template only until the pipeline has successfully run against the public APIs.

## Data validity and row semantics

Every row has a `source.url` pointing to its actual entity/article/job record and a `collectedAt` timestamp. Publication dates must be timezone-aware and satisfy `now - 24h <= published <= now`. Relative timestamps are accepted only with an anchored capture time; ambiguous dates without timezones are not marked fresh. For all sources without a publication time, we track first seen but do **not** claim that the item was published in the last 24 hours.

Research-paper rows require: official or unspecified archive linkage, valid arXiv ID, arXiv title/authors/publication timestamp, a live GitHub repository, and an integer `stargazers_count` fetched from GitHub. A repo's current number of stars is not the same as the paper's historic popularity. GitHub timestamps are separately recorded.

News articles can have `fullTextStatus=article_html`, `feed_content`, or `unavailable`; absent full-text is explicitly labeled. JavaScript paywalls and access blocks are not circumvented.

Product pricing is null unless it can be verified. Most Hugging Face Spaces are app/demo listings, not proof of a commercial startup relationship. Entity resolution preserves unresolved names verbatim.

## Source dependencies and licenses

- YC company mirror (community-maintained JSON): https://github.com/yc-oss/api
- Hugging Face Hub public API: https://huggingface.co/docs/hub/api
- Product Hunt GraphQL (optional OAuth token): https://api.producthunt.com/v2/docs
- PWC archived paper-code relationship dataset: https://huggingface.co/datasets/pwc-archive/links-between-paper-and-code
- arXiv Atom metadata: https://info.arxiv.org/help/api/index.html
- GitHub REST repo metadata (stars): https://docs.github.com/en/rest/repos/repos
- Source-specific RSS feeds and official job board APIs are listed in `src/signals.py`.

Access restrictions, publisher usage terms, and API limits apply. No attempt is made to bypass Captcha, Cloudflare challenges, authentication, or robots directives. For protected sources, use licensed access, approved partners, public APIs, or lower-frequency RSS.

## Architecture and testing

See `architecture.pdf` and `docs/architecture.md` for the 500k+ scale plan. A single-machine SQLite demo is intentionally not presented as a distributed job orchestration stack. A production deployment would use source-specific distributed workers, a durable message queue, Postgres advisory/row locking and unique constraints, object storage snapshots, central metrics, and partitioned retry/dead-letter queues.

Test suite covers timestamp inclusivity, UTC handling, URL deduplication, paper/repo validation, source adapters, news/job freshness, source fidelity, 413 adaptive chunking, and LLM fallback. Tests use **explicitly synthetic fixtures only**, never imported into the production results.

## Known limitations / engineering decisions

1. The included archive is historical (pre-2026). Live GitHub stars and arXiv metadata are fetched at runtime; archive coverage may not include newer papers.
2. A valid public repository link does not prove a paper's implementation quality; this is a source-linked relationship, not an endorsement.
3. 1,000 results can require source quotas and authentication. If access is interrupted, partial output and logs reflect actual successful records.
4. Some publisher feeds may change URLs, block scraping, or omit full article bodies. RSS items are rejected on invalid published timestamps and inaccessible full-text is flagged.
5. `src.llm.MultiTierExtractor` is an enrichment component (opt in with `--enrich-llm`) and is independently testable. Baseline structured API ingestion does not consume LLM tokens; that avoids extra cost and prevents the LLM from inventing machine-exposed fields.
6. Workstation SQLite provides durable local deduplication, not coordination across distributed nodes; production upgrade path is documented.
7. To publish a Google Sheet, browser-mediated Google OAuth authorization is required. Credentials never belong in repository history.

## Readiness gate

`python -m src.cli validate` exits with status 2 and writes `output/validation_report.json` until the 1,000-row minima are met, all configured sources were successfully checked, and every exported news/job remains within the last 24 hours **at submission time**. The pipeline will not declare itself complete when input sources are inaccessible.

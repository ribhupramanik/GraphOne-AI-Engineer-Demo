# High-precision data quality update

The assessment prioritizes source fidelity, verifiable AI relevance, and freshness. This patch corrects a high-impact overclassification in job ingestion and adds an official arXiv subject audit.

## What changed

- The job crawler now requires **explicit AI/ML terms in the job title** rather than accepting any company description that happens to mention AI. This is deliberately conservative: relevant jobs with generic titles may be omitted, so it favors precision over recall.
- Job `content.role_family` now describes the **function** of the position (Engineering, Data Science, Product Management, Marketing, Sales, etc.), not the previously hardcoded `AI / Machine Learning` label.
- The reproducible submission exporter always corrects role-family labels in **copied** CSV rows. With `--strict-ai-jobs`, it keeps only explicit AI title matches and reports how many jobs were excluded.
- The arXiv parser captures **primary subject** and **cross-listed categories** where supplied. A separate audit uses official arXiv API subject metadata to identify papers in core AI/ML subjects. It never treats titles alone as proof of relevance.
- The paper audit **does not replace** any of the original paper records. It writes a filtered CSV only if it can verify at least 1,000 papers with accepted arXiv AI-related category tags. Otherwise it generates a report explaining the gap; additional harvesting would be necessary.

## Run the quality pass

```bash
python -m pytest -q
python -m src.cli signals --enrich-llm --llm-limit 10
python -m src.cli export
python scripts/prepare_submission.py --strict-ai-jobs
python scripts/audit_arxiv_subjects.py
```

The last script contacts arXiv in small batches, with a pause between requests. It writes `output/audit/arxiv_subject_audit.json` and caches retrieved metadata in `output/audit/arxiv_categories_cache.json` to support retries. It does not change the six submission CSVs. If the result confirms **at least 1,000** AI-subject papers, create the fully reviewed submission:

```bash
python scripts/prepare_submission.py --strict-ai-jobs --verified-papers output/audit/research_papers_ai_verified.csv
```

If the audit finds fewer than 1,000 eligible papers, **do not use** the verified-paper option or claim the existing 1,258 have all been subject-certified. You can continue collecting from relevant categories until the 1,000-record threshold is actually met.

Upload the six `output/submission/*.csv` files to the public six-tab Google Sheet and recheck sharing permissions. Always regenerate the submission CSVs immediately before publishing because 24-hour freshness expires continuously.

## Why the numbers change

A review of the November 22, 2026 workbook found 175 fresh jobs; all 175 had been assigned the same AI/ML role family. Only 28 job titles explicitly signaled AI/ML work under the conservative new rule. The other 147 are left in the historical database and excluded only from the optional high-precision submission view.

The 1,258 paper rows include some unmistakably non-AI titles (e.g., pure mathematics). arXiv tags must be fetched to establish an objective inclusion basis. The accepted category set is defined in `scripts/audit_arxiv_subjects.py`; cross-list membership is evidence of subject classification, not proof of paper quality.

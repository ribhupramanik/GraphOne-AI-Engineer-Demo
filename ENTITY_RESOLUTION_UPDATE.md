# GraphOne entity-resolution update (2026-11-22)

## Purpose

This patch adds **evidence-aware, deterministic reconciliation** for the existing SQLite dataset. It does not call external services, replace your database, or require new API keys. The output mapping log distinguishes:

- `exact_seed_alias`: exact normalized match against the curated 50-organization seed list (1.00).
- `directory_observed_name`: the company's own name as observed in the Y Combinator community directory dataset (0.80). This does **not** prove cross-source entity matching.
- `directory_name_match`: a job employer string matches a unique sufficiently long name observed in the startup directory (0.95). This is still a name-level match, not independent proof of company ownership.
- `observed_name_variants`: variant forms found in the actual job feed records normalize to one name, e.g. `grafanalabs` and `Grafana Labs` (0.90).
- `publisher_handle_seed_match`: a Hugging Face Space owner handle matches a known seed organization (0.75). Handle equality does not independently prove official ownership.
- `unresolved_preserved`: no supported identity match, so the original label is retained (0.00).

**Never count `directory_observed_name` as a resolved cross-source alias.** The point of the split is to avoid inflating a resolution metric by calling every known company name 'resolved'. Normalization handles HTML escapes and trailing legal suffixes, and there is no fuzzy-only merging.

## Apply safely

From `~/D Drive/AI Task`, with the virtual environment activated and no crawler currently running:

```bash
cp output/intelligence.db output/intelligence.before_entities.db
unzip -o "$HOME/Downloads/GraphOne_Entity_Resolution_Fix.zip" -d .
python -m pytest -q
python -m src.cli reconcile-entities --dry-run
python -m src.cli reconcile-entities
python -m src.cli status
```

`reconcile-entities` performs a single SQLite transaction for record value changes and rebuilding the mapping log. The `--dry-run` command produces proposed counts without modifying the database or CSVs. The live command exports all six CSVs automatically; you may also run `python -m src.cli export`.

It is safe to repeat `reconcile-entities`; the stored original `raw_payload` is never overwritten and all mapping results are derived from that payload plus the current local record set. The script does not change record identity keys or fabricate company/product relationships.

After collecting more news/jobs, run the reconciliation again to recognize additional legitimate job-company variants. The CLI export includes historical signals; prepare the **freshness-filtered** Jobs and News CSVs separately immediately before submission.

## Tests

Two new tests cover normalization/ambiguity safeguards, backfilling canonical names into stored jobs, safety of ambiguous Hugging Face publishers, raw-evidence preservation, and rerun idempotence. The full supplied suite passes: 28 tests.

## Mapping preview

The separate `GraphOne_Improved_Entity_Mapping_Preview.csv` was calculated from the previously uploaded Excel mapping log (1,339 rows) rather than from your local live SQLite database. Its method totals are:

| Method | Preview rows |
|---|---:|
| directory_observed_name | 999 |
| unresolved_preserved | 288 |
| exact_seed_alias | 16 |
| directory_name_match | 13 |
| observed_name_variants | 12 |
| publisher_handle_seed_match | 11 |

**These are not 1,051 independently verified identity matches**: 999 are merely directory-listed names. For the authoritative post-fix results, use `python -m src.cli reconcile-entities` on your local database and import its regenerated `output/csv/entity_mapping_log.csv` into Google Sheets.

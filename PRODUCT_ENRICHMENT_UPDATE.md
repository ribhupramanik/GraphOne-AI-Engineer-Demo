# Source-backed Product Metadata Enrichment

This update adds `enrich-products` to your GraphOne project while preserving all existing SQLite data, source URLs, and the reconciled Entity Mapping Log.

## Apply

From the directory containing `src/`, `tests/`, and `output/`:

```bash
cp output/intelligence.db output/intelligence.before_products.db
unzip -o "$HOME/Downloads/GraphOne_Product_Enrichment_Fix.zip" -d .
python -m pytest -q
```

## Start with a small run

```bash
python -m src.cli enrich-products --product-limit 20 2>&1 | tee product_enrichment_pilot.log
```

Inspect the JSON object named `product_enrichment`: `selected` = attempted records, `checked` = API detail responses verified, `descriptions_added` = actual product descriptions recovered, `owners_verified` = org-plus-directory matches, `failed` = unavailable API responses. `updated` counts changed records, including metadata-check timestamps. This will regenerate the CSV exports.

If that succeeds, enrich the rest:

```bash
python -m src.cli enrich-products --product-limit 1000 2>&1 | tee product_enrichment_full.log
python -m src.cli export
python -m pytest -q
```

Previously checked product IDs are skipped by default, so the full run processes the *remaining* records. To re-check already processed records, pass `--product-force`; to limit concurrent metadata tasks, pass `--product-workers 2`.

## Update only the products tab in your submission snapshot

```bash
cp output/csv/products.csv output/submission/products.csv
```

Update the **Products** tab in your Google Sheet from `output/submission/products.csv`. The full CSV export also includes historical news and jobs; **do not replace filtered News and Jobs tabs with it**.

## Data quality and limitations

- Descriptions are copied only from official Space-card `short_description` values or a descriptive paragraph of the Space's README. Each record's original raw source is preserved, and new metadata evidence is stored under `_metadata_enrichment` in `raw_payload`.
- Known publishers become `startupName` only after the public Hugging Face organization profile resolves and an exact normalized name matches a known startup-directory name or curated canonical seed. User handles are not presumed to be companies.
- `pricingModel` is **not** guessed from a demo Space being freely accessible. Keep it null unless a real pricing statement can be verified.
- Not all Hugging Face Spaces are commercial products. Do not present this dataset as a verified sample of commercial AI SaaS vendors.
- If Space metadata or README text is missing, the corresponding fields remain blank. This is intended and does not justify fabricated values.
- The 24-hour job/news requirement is separate. Refresh and filter those datasets immediately before final publishing.

## Evidence sources

Hugging Face Space metadata API: `https://huggingface.co/api/spaces/<owner>/<name>`

Hugging Face Space README: `https://huggingface.co/spaces/<owner>/<name>/raw/main/README.md`

Hugging Face organizational profile (when a name match exists): `https://huggingface.co/api/organizations/<owner>/overview`

Hugging Face documentation: https://huggingface.co/docs/hub/spaces-config-reference

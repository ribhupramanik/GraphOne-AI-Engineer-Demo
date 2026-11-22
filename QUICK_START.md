# Quick start — macOS

## 1. Extract, open Terminal in the project folder

```bash
cd ~/Downloads/graphone-ai-engineer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with a valid GitHub token in `GITHUB_TOKEN` and your actual contact email in `USER_AGENT`. Optional: add any Gemini/Groq/DeepSeek keys to demonstrate LLM enrichment.

## 2. Check tests

```bash
pytest -q
```

## 3. Collect verified data (network required)

```bash
python -m src.cli bulk --startups 1000 --products 1000 --papers 1000
```

This can generate many requests to arXiv and GitHub; let it reach completion and do not invent counts if sources are throttled. Monitor counts with:

```bash
python -m src.cli status
```

## 4. Run the 24-hour signal sweep near submission

```bash
python -m src.cli signals --enrich-llm --llm-limit 10
python -m src.cli export
python -m src.cli validate
```

If you did not configure any LLM credentials, use `python -m src.cli signals` without enrichment. The pipeline is designed to keep real structured data even when LLM keys are unavailable.

## 5. Publish the real output

Either import the six CSV files from `output/csv` as tabs in Google Sheets, or follow the OAuth instructions in `README.md` and run `scripts/publish_to_sheets.py --public`. Upload this source folder to GitHub, excluding `.env`, OAuth credentials, cache files and SQLite DB. Include `architecture.pdf`. Submit your real Sheets URL and GitHub repository URL at the employer's submission form.

**Status of downloaded starter package:** the included workbook and CSVs are deliberately header-only because this generation environment could not access the live APIs. The files become actual results only after a successful live data run on your Mac. Do not submit these empty outputs as completed extraction.

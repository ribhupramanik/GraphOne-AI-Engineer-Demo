import pytest

from src.llm import MultiTierExtractor
from src.signals import enrich_stored_news
from src.store import Store


class FakeGeminiFetcher:
    def __init__(self):
        self.url = None

    async def request(self, url, **kwargs):
        self.url = url
        return {"candidates": [{"content": {"parts": [{"text": '{"fields": {"company": {"value": "OpenAI", "evidence": "OpenAI launched a model"}}}'}]}}]}


async def test_gemini_model_is_configurable():
    settings = type("Settings", (), {"gemini_key": "fake", "gemini_model": "gemini-3.5-flash-lite", "groq_key": "", "deepseek_key": ""})()
    fetcher = FakeGeminiFetcher()
    extractor = MultiTierExtractor(fetcher, settings)
    assert await extractor.extract("OpenAI launched a model", ["company"]) == {"company": "OpenAI"}
    assert fetcher.url.endswith("/gemini-3.5-flash-lite:generateContent")


class FakeExtractor:
    def __init__(self):
        self.calls = 0

    async def extract(self, text, fields):
        self.calls += 1
        return {"company": "OpenAI"}


async def test_existing_news_can_be_enriched_without_duplicates(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    url = "https://example.org/real-news"
    record = {
        "schemaVersion": "1.0",
        "recordType": "NEWS",
        "source": {"name": "Example", "url": url},
        "content": {"title": "OpenAI launches", "fullText": "OpenAI launched a model", "llmExtraction": None, "llmExtractionStatus": "not_requested"},
        "collectedAt": "2026-11-21T00:00:00Z",
    }
    assert store.insert_verified_signal(record, url, {"title": "OpenAI launches"}, "2026-11-21T00:00:00Z")
    before = store.get_raw_evidence("NEWS", url)
    extractor = FakeExtractor()
    assert await enrich_stored_news(store, extractor, limit=3) == 1
    assert await enrich_stored_news(store, extractor, limit=3) == 0
    assert extractor.calls == 1
    assert store.counts()["NEWS"] == 1
    after = store.get_records("NEWS")[0]
    assert after["content"]["llmExtractionStatus"] == "evidence_validated"
    assert after["content"]["llmExtraction"] == {"company": "OpenAI"}
    assert store.get_raw_evidence("NEWS", url) == before
    assert after["collectedAt"] == "2026-11-21T00:00:00Z"
    store.close()


def test_enrichment_rejects_unverified_status(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    with pytest.raises(ValueError):
        store.update_news_enrichment("https://example.org", {}, "evidence_validated")
    store.close()

class FakeErrorResponse:
    status = 400
    headers = {"Content-Type": "application/json"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def text(self, **kwargs):
        return '{"error": {"message": "JSON mode validation failed"}}'


class FakeErrorSession:
    def request(self, *args, **kwargs):
        return FakeErrorResponse()


async def test_bad_request_includes_provider_error_detail():
    from src.net import AsyncFetcher, FetchError

    settings = type("Settings", (), {"concurrency": 1, "host_interval": 0.01})()
    async with AsyncFetcher(settings, transport=FakeErrorSession()) as fetcher:
        with pytest.raises(FetchError) as error:
            await fetcher.request("https://api.groq.com/openai/v1/chat/completions", method="POST")
    assert error.value.status == 400
    assert error.value.detail == "JSON mode validation failed"

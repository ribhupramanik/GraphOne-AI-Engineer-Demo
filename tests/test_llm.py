import pytest

from src.llm import MultiTierExtractor, NoProviderAvailable, dense_chunk, parse_evidence_json
from src.net import FetchError


def test_dense_chunk_never_exceeds_limit():
    text = "Lorem ipsum sentence. " * 2000 + "\n\nGitHub stars 1234 were recorded."
    output = dense_chunk(text, max_chars=1000)
    assert len(output) <= 1000


def test_ungrounded_fields_are_discarded():
    text = "OpenAI launched a research demo in 2026."
    result = parse_evidence_json({"fields": {"company": {"value": "OpenAI", "evidence": "OpenAI launched a research demo"}, "employees": {"value": 9999, "evidence": "The workforce has 9999 members"}}}, text)
    assert result == {"company": "OpenAI"}


class FakeAPI:
    def __init__(self):
        self.calls = []

    async def _complete(self, kind, key, payload):
        self.calls.append((kind, len(payload)))
        if kind == "gemini":
            raise FetchError(413, "https://example.com")
        return '{"fields": {"company": {"value": "OpenAI", "evidence": "OpenAI shipped a model"}}}'


async def test_413_shrinks_and_fallback_chain():
    api = FakeAPI()
    extractor = MultiTierExtractor(None, type("S", (), {"gemini_key": "x", "groq_key": "x", "deepseek_key": ""})())
    extractor._complete = api._complete
    result = await extractor.extract("OpenAI shipped a model. " * 1300, ["company"])
    assert result == {"company": "OpenAI"}
    assert [c[0] for c in api.calls] == ["gemini"] * 4 + ["groq"]
    assert api.calls[1][1] < api.calls[0][1]


async def test_no_provider_fails_closed():
    extractor = MultiTierExtractor(None, type("S", (), {"gemini_key": "", "groq_key": "", "deepseek_key": ""})())
    with pytest.raises(NoProviderAvailable):
        await extractor.extract("text", ["title"])

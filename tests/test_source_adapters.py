from src.products import acquire_huggingface_products
from src.startups import acquire_startups
from src.store import Store


class FixtureFetcher:
    async def get_json(self, url):
        if "companies" in url:
            return [{"name": "OpenAI, Inc.", "slug": "openai", "team_size": 100, "one_liner": "AI research"}]
        if "spaces" in url:
            return [{"id": "huggingface/demo-space", "cardData": {"title": "Demo Space", "short_description": "Demonstration"}}]
        raise ValueError(url)


async def test_startup_source_and_product_ownership_are_not_invented(tmp_path):
    store = Store(tmp_path / "adapters.db")
    fetch = FixtureFetcher()
    assert await acquire_startups(fetch, store, limit=1) == 1
    assert store.get_records("STARTUP")[0]["content"]["entityName"] == "OpenAI"
    assert await acquire_huggingface_products(fetch, store, limit=1) == 1
    product = store.get_records("PRODUCT")[0]
    assert product["content"]["pricingModel"] is None
    assert product["content"]["startupName"] == "Hugging Face"
    store.close()

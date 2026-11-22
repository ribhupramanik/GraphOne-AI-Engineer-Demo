import json

from src.product_enrichment import (
    description_from_metadata,
    description_from_readme,
    enrich_stored_products,
    repo_id_from_url,
)
from src.store import Store


class ProductFetcher:
    def __init__(self):
        self.calls = []

    async def get_json(self, url):
        self.calls.append(url)
        if url.endswith("/api/spaces/user/demo"):
            return {"id": "user/demo", "cardData": {"title": "Demo Space", "short_description": "An interactive demo for text translation"}}
        if url.endswith("/api/spaces/user/readme"):
            return {"id": "user/readme", "cardData": {}}
        if url.endswith("/api/spaces/openai/example"):
            return {"id": "openai/example", "cardData": {"short_description": "A verified org-owned app"}}
        if url.endswith("/api/organizations/openai/overview"):
            return {"name": "openai", "fullname": "OpenAI"}
        raise ValueError(url)

    async def request(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/spaces/user/readme/raw/main/README.md"):
            return "---\ntitle: Example\n---\n\n# App\n\nThis app uses a public model to translate user-provided text.\n"
        raise ValueError(url)


def insert(store, repo, desc=None):
    store.upsert({
        "schemaVersion": "1.0", "recordType": "PRODUCT",
        "source": {"name": "Hugging Face Spaces", "url": "https://huggingface.co/spaces/" + repo},
        "content": {"productName": repo.split("/")[1], "startupName": None,
                    "description": desc, "pricingModel": None},
        "collectedAt": "2026-11-22T00:00:00Z",
    }, repo.lower(), {"id": repo})


def test_url_is_strictly_bounded_to_hugging_face_spaces():
    assert repo_id_from_url("https://huggingface.co/spaces/owner/slug") == "owner/slug"
    assert repo_id_from_url("https://evil.com/spaces/owner/slug") is None
    assert repo_id_from_url("https://huggingface.co/spaces/owner/../slug") is None
    assert repo_id_from_url("https://huggingface.co/spaces/owner/slug/blob/main") is None


def test_descriptions_are_literal_source_text():
    assert description_from_metadata({"cardData": {"short_description": "Live image demo"}}) == ("Live image demo", "space_card")
    assert description_from_readme("---\nshort_description: Documented demo\n---\nanything") == ("Documented demo", "readme_frontmatter")
    assert description_from_readme("# Title\n\nExample tool for visualizing multiple machine learning experiments.\n") == (
        "Example tool for visualizing multiple machine learning experiments.", "readme_paragraph"
    )


async def test_product_enrichment_rest_card_preserves_raw_data_and_does_not_infer_pricing(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "user/demo")
    fetcher = ProductFetcher()
    result = await enrich_stored_products(fetcher, store, limit=10)
    assert result["selected"] == 1
    assert result["descriptions_added"] == 1
    row = store.get_records("PRODUCT")[0]
    assert row["content"]["description"] == "An interactive demo for text translation"
    assert row["content"]["startupName"] is None
    assert row["content"]["pricingModel"] is None
    assert row["content"]["productName"] == "Demo Space"
    raw = store.get_raw_evidence("PRODUCT", "user/demo")
    assert raw["id"] == "user/demo"
    assert raw["_metadata_enrichment"]["spaceApiUrl"].endswith("user/demo")
    second = await enrich_stored_products(fetcher, store, limit=10)
    assert second["selected"] == 0
    store.close()


async def test_readme_description_and_no_false_ownership(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "user/readme")
    fetcher = ProductFetcher()
    result = await enrich_stored_products(fetcher, store, limit=5)
    assert result["descriptions_added"] == 1
    content = store.get_records("PRODUCT")[0]["content"]
    assert content["description"] == "This app uses a public model to translate user-provided text."
    assert content["descriptionSource"] == "readme_paragraph"
    assert content["startupName"] is None
    store.close()


async def test_owner_requires_confirmed_org_and_matching_directory(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "openai/example")
    store.upsert({"schemaVersion": "1.0", "recordType": "STARTUP", "source": {"name": "directory", "url": "https://example.com/openai"},
                  "content": {"entityName": "OpenAI"}, "collectedAt": "2026-11-22T00:00:00Z"},
                 "openai", {"name": "OpenAI"})
    result = await enrich_stored_products(ProductFetcher(), store)
    assert result["owners_verified"] == 1
    assert store.get_records("PRODUCT")[0]["content"]["startupName"] == "OpenAI"
    store.close()


async def test_failed_metadata_request_does_not_mark_checked(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "user/missing")
    result = await enrich_stored_products(ProductFetcher(), store)
    assert result["failed"] == 1
    assert "metadataCheckedAt" not in store.get_records("PRODUCT")[0]["content"]
    store.close()


async def test_zero_limit_does_not_fetch_anything(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "user/demo")
    fetcher = ProductFetcher()
    assert await enrich_stored_products(fetcher, store, limit=0) == {"selected": 0}
    assert fetcher.calls == []
    store.close()


async def test_repeated_bulk_upsert_preserves_verified_enrichment(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    insert(store, "user/demo")
    await enrich_stored_products(ProductFetcher(), store)
    fresh_listing = {"id": "user/demo", "likes": 45}
    store.upsert({
        "schemaVersion": "1.0", "recordType": "PRODUCT",
        "source": {"name": "Hugging Face Spaces", "url": "https://huggingface.co/spaces/user/demo"},
        "content": {"productName": "demo", "startupName": None, "description": None, "pricingModel": None},
        "collectedAt": "2026-11-23T00:00:00Z",
    }, "user/demo", fresh_listing)
    record = store.get_records("PRODUCT")[0]
    assert record["content"]["description"] == "An interactive demo for text translation"
    assert record["content"]["productName"] == "Demo Space"
    assert record["content"]["metadataCheckedAt"]
    assert store.get_raw_evidence("PRODUCT", "user/demo")["_metadata_enrichment"]["spaceApiUrl"]
    store.close()

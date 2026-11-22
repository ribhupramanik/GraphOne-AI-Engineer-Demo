import logging
from urllib.parse import quote

from .entities import Resolver
from .utils import iso, utcnow

LOG = logging.getLogger(__name__)
PRODUCT_HUNT_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"


async def acquire_huggingface_products(fetcher, store, *, limit=1000, resolver=None):
    resolver = resolver or Resolver()
    accepted = 0
    ids = set()

    def ingest(item):
        nonlocal accepted
        repo = item.get("id") or item.get("_id")
        if not repo or "/" not in repo or repo in ids:
            return False
        author, product_slug = repo.split("/", 1)
        if not author or not product_slug:
            return False
        ids.add(repo)
        card = item.get("cardData") or item.get("card_data") or {}
        if not isinstance(card, dict):
            card = {}
        name = card.get("title") or product_slug.replace("-", " ").replace("_", " ")
        source_url = "https://huggingface.co/spaces/" + quote(repo, safe="/-_")
        canonical = resolver.aliases.get("".join(c for c in author.lower() if c.isalnum()))
        entity = {
            "schemaVersion": "1.0", "recordType": "PRODUCT",
            "source": {"name": "Hugging Face Spaces", "url": source_url},
            "content": {"productName": name, "startupName": canonical,
                        "pricingModel": None,
                        "description": card.get("short_description") or item.get("shortDescription"),
                        "category": "AI demo application (Space)", "publisher": author},
            "collectedAt": iso(utcnow()),
        }
        store.upsert(entity, repo.lower(), item)
        if canonical:
            store.log_mapping(author, canonical, "owner_exact_seed", 1.0, source_url)
        accepted += 1
        return True

    page = 0
    while accepted < limit and page < 20:
        batch_limit = min(1000, max(1, limit - accepted))
        url = "https://huggingface.co/api/spaces?limit=" + str(batch_limit)
        if page:
            url += "&skip=" + str(page * 1000)
        try:
            result = await fetcher.get_json(url)
        except Exception as exc:
            LOG.warning("Hugging Face REST page unavailable %s (%s)", page, type(exc).__name__)
            break
        if not isinstance(result, list):
            LOG.warning("Hugging Face returned non-list spaces response")
            break
        newly_added = sum(1 for item in result if ingest(item))
        LOG.info("huggingface rest page=%d accepted=%d", page, accepted)
        if len(result) < batch_limit or newly_added == 0:
            break
        page += 1

    if accepted < limit:
        try:
            import asyncio
            from dataclasses import asdict, is_dataclass
            from huggingface_hub import HfApi

            def fetch_with_official_sdk():
                return list(HfApi().list_spaces(limit=limit))

            for item in await asyncio.to_thread(fetch_with_official_sdk):
                obj = asdict(item) if is_dataclass(item) else vars(item)
                ingest(obj)
                if accepted >= limit:
                    break
        except Exception as exc:
            LOG.warning("Hugging Face official SDK fallback unavailable (%s)", type(exc).__name__)
    LOG.info("huggingface spaces acquired=%d requested=%d", accepted, limit)
    return accepted


async def acquire_producthunt(fetcher, store, token, *, limit=1000, resolver=None):
    if not token:
        raise ValueError("PRODUCT_HUNT_TOKEN is required")
    resolver = resolver or Resolver()
    query = '''query Products($after: String, $first: Int!) {
      posts(first: $first, after: $after) {
        edges { cursor node { id name tagline url website createdAt topics { edges { node { name } } } } }
        pageInfo { endCursor hasNextPage }
      }
    }'''
    accepted = 0
    cursor = None
    while accepted < limit:
        data = await fetcher.request(
            PRODUCT_HUNT_ENDPOINT, method="POST",
            json_body={"query": query, "variables": {"after": cursor, "first": min(50, limit - accepted)}},
            headers={"Authorization": "Bearer " + token},
        )
        if data.get("errors"):
            raise RuntimeError("Product Hunt GraphQL returned errors: " + str(data["errors"])[:300])
        posts = (data.get("data") or {}).get("posts") or {}
        edges = posts.get("edges") or []
        if not edges:
            break
        for edge in edges:
            item = edge["node"]
            page_url = item.get("url")
            if not page_url or not item.get("name"):
                continue
            entity = {
                "schemaVersion": "1.0", "recordType": "PRODUCT",
                "source": {"name": "Product Hunt API", "url": page_url},
                "content": {"productName": item["name"], "startupName": None,
                            "pricingModel": None, "description": item.get("tagline"),
                            "website": item.get("website")},
                "collectedAt": iso(utcnow()),
            }
            store.upsert(entity, "ph:" + item["id"], item)
            accepted += 1
        page_info = posts.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return accepted

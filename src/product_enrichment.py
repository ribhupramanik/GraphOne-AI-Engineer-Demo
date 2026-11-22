"""Evidence-preserving enrichment of existing Hugging Face Space product records."""

import asyncio
import logging
import re
from collections import Counter
from urllib.parse import quote, urlsplit

from .entities import Resolver, normalise_name
from .utils import iso, utcnow

LOG = logging.getLogger(__name__)
SPACE_PATH = re.compile(r"^/spaces/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/?$")
MAX_DESCRIPTION = 400


def repo_id_from_url(url):
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co":
        return None
    match = SPACE_PATH.fullmatch(parsed.path)
    if not match or any(segment in {".", ".."} for segment in match.groups()):
        return None
    return "/".join(match.groups())


def clean_field(value):
    if not isinstance(value, str):
        return None
    value = " ".join(value.replace("\x00", " ").split())
    if not value or value.lower() in {"none", "null", "n/a", "todo", "coming soon", "tbd"}:
        return None
    return value[:MAX_DESCRIPTION]


def description_from_readme(markdown):
    if not isinstance(markdown, str):
        return None, None
    text = markdown.lstrip("\ufeff")[:20000]
    header_description = None
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            header = text[4:end]
            for line in header.splitlines():
                match = re.match(r"^short_description:\s*(.*?)\s*$", line, flags=re.I)
                if match and match.group(1) not in {"|", ">", "|-", ">-"}:
                    header_description = clean_field(match.group(1).strip("\"'"))
                    break
            text = text[end + 5:]
    if header_description:
        return header_description, "readme_frontmatter"
    paragraphs = []
    in_code = False
    for line in text.splitlines():
        value = line.strip()
        if value.startswith("```") or value.startswith("~~~"):
            in_code = not in_code
            if paragraphs:
                break
            continue
        if in_code or value.startswith(("#", "<", "!", "[!", "|", "- ", "* ", "> ", "---")):
            if paragraphs:
                break
            continue
        if not value:
            if paragraphs:
                break
            continue
        if len(value) >= 15 and not value.startswith(("[", "!")):
            paragraphs.append(value)
        if sum(len(s) for s in paragraphs) >= MAX_DESCRIPTION:
            break
    desc = clean_field(" ".join(paragraphs))
    return (desc, "readme_paragraph") if desc and len(desc) >= 25 else (None, None)


def description_from_metadata(metadata):
    card = metadata.get("cardData") or metadata.get("card_data") or {}
    if not isinstance(card, dict):
        card = {}
    for item in (card.get("short_description"), card.get("shortDescription"), metadata.get("shortDescription")):
        value = clean_field(item)
        if value:
            return value, "space_card"
    return None, None


async def enrich_stored_products(fetcher, store, *, limit=1000, workers=4, force=False):
    if limit < 0 or workers < 1:
        raise ValueError("Product enrichment limit must be >= 0 and workers >= 1")
    if limit == 0:
        return {"selected": 0}
    rows = list(store.db.execute(
        "SELECT canonical_key, payload FROM records WHERE record_type='PRODUCT' ORDER BY canonical_key"
    ))
    import json
    selected = []
    for key, payload in rows:
        record = json.loads(payload)
        if record.get("source", {}).get("name") != "Hugging Face Spaces":
            continue
        if not force and record.get("content", {}).get("metadataCheckedAt"):
            continue
        if repo_id_from_url(record.get("source", {}).get("url")):
            selected.append((key, record))
        if len(selected) >= limit:
            break
    report = Counter()
    report["selected"] = len(selected)
    if not selected:
        return dict(report)

    names = [rec["content"].get("entityName") for rec in store.get_records("STARTUP")]
    resolver = Resolver(directory_names=names)
    verified_owners = {}
    owner_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(workers)

    async def verify_owner(owner):
        candidate, method, _ = resolver.resolve(owner)
        if method not in {"exact_seed_alias", "directory_name_match"}:
            return None
        async with owner_lock:
            if owner in verified_owners:
                return verified_owners[owner]
            url = "https://huggingface.co/api/organizations/" + quote(owner, safe="") + "/overview"
            try:
                details = await fetcher.get_json(url)
                valid = isinstance(details, dict) and details.get("name") == owner
                verified_owners[owner] = candidate if valid and normalise_name(owner) == normalise_name(candidate) else None
            except Exception:
                verified_owners[owner] = None
            return verified_owners[owner]

    async def process(key, record):
        async with semaphore:
            repo = repo_id_from_url(record["source"]["url"])
            api_url = "https://huggingface.co/api/spaces/" + quote(repo, safe="/")
            try:
                metadata = await fetcher.get_json(api_url)
                if not isinstance(metadata, dict) or not isinstance(metadata.get("id", repo), str) or metadata.get("id", repo).lower() != repo.lower():
                    report["missing"] += 1
                    return
            except Exception as exc:
                LOG.warning("space metadata unavailable repo=%s reason=%s", repo, type(exc).__name__)
                report["failed"] += 1
                return
            card = metadata.get("cardData") or metadata.get("card_data") or {}
            if not isinstance(card, dict):
                card = {}
            description, source = description_from_metadata(metadata)
            readme_url = None
            readme_excerpt = None
            if not description:
                readme_url = "https://huggingface.co/spaces/" + quote(repo, safe="/") + "/raw/main/README.md"
                try:
                    readme = await fetcher.request(readme_url)
                    description, source = description_from_readme(readme)
                    if description:
                        readme_excerpt = (readme or "")[:1000]
                except Exception as exc:
                    LOG.debug("README unavailable repo=%s reason=%s", repo, type(exc).__name__)
            updates = {"metadataCheckedAt": iso(utcnow())}
            if description and not record["content"].get("description"):
                updates["description"] = description
                updates["descriptionSource"] = source
            if not record["content"].get("startupName"):
                owner = repo.split("/", 1)[0]
                owner_name = await verify_owner(owner)
                if owner_name:
                    updates["startupName"] = owner_name
                    updates["ownerVerification"] = "hf_organization_profile_and_directory_name"
            title = clean_field(card.get("title"))
            if title and record["content"].get("productName") == repo.split("/", 1)[1].replace("-", " ").replace("_", " "):
                updates["productName"] = title
                updates["titleSource"] = "space_card"
            evidence = {"spaceApiUrl": api_url, "cardData": card, "readmeUrl": readme_url if readme_excerpt else None,
                        "readmeExcerpt": readme_excerpt, "descriptionSource": source}
            changed = store.update_product_enrichment(key, updates, evidence)
            report["checked"] += 1
            report["updated"] += int(changed)
            report["descriptions_added"] += int("description" in updates)
            report["owners_verified"] += int("startupName" in updates)
            if report["checked"] % 50 == 0:
                LOG.info("product enrichment processed=%d/%d descriptions_added=%d", report["checked"], len(selected), report["descriptions_added"])

    await asyncio.gather(*(process(key, record) for key, record in selected))
    return dict(report)

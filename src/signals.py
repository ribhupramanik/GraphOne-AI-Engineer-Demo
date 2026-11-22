import asyncio
import json
import logging
from datetime import timedelta
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from .entities import Resolver
from .job_quality import ai_title_indicated, role_family_from_title
from .net import FetchError
from .utils import canonical_url, fresh_within_24_hours, iso, parse_date, utcnow

LOG = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

NEWS_SOURCES = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "MIT Technology Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
}

JOB_SOURCES = {
    "Remote OK": "https://remoteok.com/api",
    "Remotive": "https://remotive.com/api/remote-jobs",
    "Arbeitnow": "https://www.arbeitnow.com/api/job-board-api",
    "Jobicy": "https://jobicy.com/api/v2/remote-jobs?count=50",
    "Himalayas": "https://himalayas.app/jobs/api?limit=100",
}


def _node_text(node, name):
    item = node.find(name)
    return "" if item is None else " ".join("".join(item.itertext()).split())


def parse_feed(xml):
    root = ET.fromstring(xml)
    entries = []
    for item in root.findall(".//item"):
        entries.append({
            "title": _node_text(item, "title"),
            "url": _node_text(item, "link"),
            "published": _node_text(item, "pubDate") or _node_text(item, DC + "date"),
            "summary": _node_text(item, "description"),
            "fullText": _node_text(item, CONTENT + "encoded"),
        })
    for entry in root.findall(".//" + ATOM + "entry"):
        link = next((e.get("href", "") for e in entry.findall(ATOM + "link") if e.get("rel", "alternate") == "alternate"), "")
        entries.append({
            "title": _node_text(entry, ATOM + "title"), "url": link,
            "published": _node_text(entry, ATOM + "published"),
            "summary": _node_text(entry, ATOM + "summary"),
            "fullText": _node_text(entry, ATOM + "content"),
        })
    return entries


def html_to_text(html):
    soup = BeautifulSoup(html or "", "html.parser")
    for element in soup.select("script, style, nav, footer, header, aside, noscript, iframe, form"):
        element.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    return " ".join(main.stripped_strings)[:150000]


def html_publication_date(html):
    soup = BeautifulSoup(html or "", "html.parser")
    for attrs in (
        {"property": "article:published_time"}, {"name": "date"},
        {"name": "pubdate"}, {"itemprop": "datePublished"},
        {"name": "article:published_time"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and parse_date(node.get("content")):
            return node.get("content")
    for node in soup.find_all("time", attrs={"datetime": True}):
        if parse_date(node["datetime"]):
            return node["datetime"]
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            parsed = json.loads(script.string or script.text)
            for entry in parsed if isinstance(parsed, list) else [parsed]:
                if isinstance(entry, dict) and parse_date(entry.get("datePublished")):
                    return entry["datePublished"]
        except (TypeError, ValueError):
            continue
    return None


def valid_external_url(url):
    return canonical_url(url) is not None and urlsplit(url).hostname not in {"localhost", "127.0.0.1"}


async def fetch_news(fetcher, store, *, reference=None, extractor=None, llm_limit=20):
    reference = reference or utcnow()
    total = 0
    llm_used = 0
    async def source_task(name, feed_url):
        try:
            feed = await fetcher.request(feed_url)
            entries = parse_feed(feed)
            store.mark_source_check("NEWS", name, "ok", len(entries))
            return name, entries
        except (FetchError, ET.ParseError) as exc:
            LOG.warning("news source failed %s (%s)", name, type(exc).__name__)
            store.mark_source_check("NEWS", name, "failed", error_type=type(exc).__name__)
            return name, []
    feed_results = await asyncio.gather(*(source_task(name, url) for name, url in NEWS_SOURCES.items()))
    for source_name, entries in feed_results:
        for entry in entries:
            page_url = canonical_url(entry["url"])
            if not page_url or not valid_external_url(page_url):
                continue
            if not fresh_within_24_hours(entry.get("published"), reference):
                store.signal_first_seen(page_url, entry, None, False)
                continue
            text = html_to_text(entry.get("fullText"))
            full_text_source = "feed_content" if len(text) >= 150 else None
            try:
                html = await fetcher.request(page_url)
                date_from_page = html_publication_date(html)
                if date_from_page and not fresh_within_24_hours(date_from_page, reference):
                    LOG.warning("page contradicts feed freshness url=%s", page_url)
                    continue
                article_text = html_to_text(html)
                if len(article_text) >= 150:
                    text = article_text
                    full_text_source = "article_html"
            except (FetchError, ValueError, TypeError) as exc:
                LOG.warning("news full text inaccessible %s (%s)", page_url, type(exc).__name__)
            verified_date = parse_date(entry["published"], reference)
            llm_fields = None
            llm_status = "not_requested"
            if extractor and full_text_source and llm_used < llm_limit:
                llm_used += 1
                try:
                    llm_fields = await extractor.extract(text, ["company", "product", "topic"])
                    llm_status = "evidence_validated"
                except Exception as exc:
                    LOG.warning("LLM enrichment failed url=%s reason=%s", page_url, type(exc).__name__)
                    llm_status = "failed"
            entity = {
                "schemaVersion": "1.0", "recordType": "NEWS",
                "source": {"name": source_name, "url": page_url},
                "content": {"title": entry["title"], "published_date": iso(verified_date),
                            "fullText": text if full_text_source else None,
                            "summary": html_to_text(entry.get("summary")),
                            "fullTextStatus": full_text_source or "unavailable",
                            "llmExtraction": llm_fields, "llmExtractionStatus": llm_status},
                "collectedAt": iso(reference),
            }
            if store.insert_verified_signal(entity, page_url, entry, iso(verified_date)):
                total += 1
    LOG.info("fresh news found=%s", total)
    return total


def job_items(source, payload):
    if source == "Remote OK":
        return [dict(title=x.get("position"), company=x.get("company"), date=x.get("date"),
                     url=x.get("url"), description=x.get("description"), remote=True)
                for x in payload if isinstance(x, dict) and x.get("position")]
    if source == "Remotive":
        return [dict(title=x.get("title"), company=x.get("company_name"), date=x.get("publication_date"),
                     url=x.get("url"), description=x.get("description"), remote=True)
                for x in payload.get("jobs", [])]
    if source == "Arbeitnow":
        return [dict(title=x.get("title"), company=x.get("company_name"), date=x.get("created_at"),
                     url=x.get("url"), description=x.get("description"), remote=x.get("remote"))
                for x in payload.get("data", [])]
    if source == "Jobicy":
        return [dict(title=x.get("jobTitle"), company=x.get("companyName"), date=x.get("pubDate"),
                     url=x.get("url"), description=x.get("jobDescription"), remote=True)
                for x in payload.get("jobs", [])]
    if source == "Himalayas":
        return [dict(title=x.get("title"), company=x.get("companyName"), date=x.get("pubDate") or x.get("publicationDate"),
                     url=x.get("url") or x.get("applicationLink"),
                     description=x.get("description"), remote=True)
                for x in payload.get("jobs", [])]
    return []


async def fetch_jobs(fetcher, store, *, reference=None, resolver=None):
    reference = reference or utcnow()
    resolver = resolver or Resolver()
    async def source_task(name, url):
        try:
            entries = job_items(name, await fetcher.get_json(url))
            store.mark_source_check("JOB", name, "ok", len(entries))
            return name, entries
        except (FetchError, ValueError, TypeError, AttributeError) as exc:
            LOG.warning("job source failed %s (%s)", name, type(exc).__name__)
            store.mark_source_check("JOB", name, "failed", error_type=type(exc).__name__)
            return name, []
    fetched = await asyncio.gather(*(source_task(name, url) for name, url in JOB_SOURCES.items()))
    total = 0
    for name, entries in fetched:
        for item in entries:
            page_url = canonical_url(item.get("url"))
            if not page_url:
                continue
            if not fresh_within_24_hours(item.get("date"), reference):
                store.signal_first_seen(page_url, item, None, False)
                continue
            title = item.get("title") or ""
            description = html_to_text(item.get("description") or "")
            if not ai_title_indicated(title):
                continue
            raw_name = (item.get("company") or "").strip()
            canonical, method, score = resolver.resolve(raw_name)
            entity = {
                "schemaVersion": "1.0", "recordType": "JOB",
                "source": {"name": name, "url": page_url},
                "content": {"company": canonical, "date": iso(parse_date(item["date"])),
                            "title": title, "is_remote": item.get("remote") if isinstance(item.get("remote"), bool) else None,
                            "role_family": role_family_from_title(title),
                            "fullText": description or None},
                "collectedAt": iso(reference),
            }
            if store.insert_verified_signal(entity, page_url, item, iso(parse_date(item["date"]))):
                if raw_name:
                    store.log_mapping(raw_name, canonical, method, score, page_url)
                total += 1
    LOG.info("fresh AI jobs found=%s", total)
    return total


async def enrich_stored_news(store, extractor, *, limit=20):
    if limit < 0:
        raise ValueError("LLM limit must not be negative")
    attempted = 0
    validated = 0
    for entity in store.get_records("NEWS"):
        if attempted >= limit:
            break
        content = entity.get("content", {})
        if content.get("llmExtractionStatus") == "evidence_validated" and content.get("llmExtraction"):
            continue
        full_text = content.get("fullText")
        if not isinstance(full_text, str) or not full_text.strip():
            continue
        attempted += 1
        url = entity["source"]["url"]
        try:
            fields = await extractor.extract(full_text, ["company", "product", "topic"])
            status = "evidence_validated" if fields else "empty"
            if fields:
                validated += 1
        except Exception as exc:
            LOG.warning("stored news LLM enrichment failed url=%s reason=%s", url, type(exc).__name__)
            fields, status = None, "failed"
        store.update_news_enrichment(url, fields, status)
    LOG.info("stored news enrichment attempted=%s evidence_validated=%s", attempted, validated)
    return attempted

from datetime import datetime, timezone
from src.signals import html_publication_date, html_to_text, job_items, parse_feed, fetch_news, fetch_jobs
from src.store import Store

NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def test_rss_parsing_and_unambiguous_published_timestamp():
    xml = '''<rss><channel><item><title>AI company launches a model</title>
      <link>https://example.org/news/a</link><pubDate>Sat, 21 Nov 2026 06:00:00 GMT</pubDate>
      <description>Launch announced</description></item></channel></rss>'''
    entries = parse_feed(xml)
    assert entries[0]["published"] == "Sat, 21 Nov 2026 06:00:00 GMT"
    assert entries[0]["url"] == "https://example.org/news/a"


def test_page_timestamp_and_text_extraction():
    html = '''<html><head><meta property="article:published_time" content="2026-11-21T04:00:00Z"></head>
    <body><nav>navigation</nav><article><h1>AI</h1><p>Model was released today.</p></article></body></html>'''
    assert html_publication_date(html) == "2026-11-21T04:00:00Z"
    assert "navigation" not in html_to_text(html)


def test_job_schema_adapter():
    entries = job_items("Arbeitnow", {"data": [{"title": "Machine Learning Engineer", "company_name": "OpenAI", "created_at": 1795251600, "url": "https://example.com/jobs/1", "description": "Remote ML", "remote": True}]})
    assert entries[0]["remote"]
    assert entries[0]["company"] == "OpenAI"


class FakeNewsFetcher:
    async def request(self, url):
        if url.endswith("/feed.xml") or "feed" in url or url.endswith("index.xml"):
            return '''<rss><channel><item><title>AI paper released</title>
              <link>https://example.org/article/1</link><pubDate>Sat, 21 Nov 2026 06:00:00 GMT</pubDate>
              <description>Published news</description></item></channel></rss>'''
        return '<html><article><p>' + "Actual research paper content. " * 40 + "</p></article></html>"


async def test_news_dedup_across_five_feeds(tmp_path):
    store = Store(tmp_path / "sig.db")
    assert await fetch_news(FakeNewsFetcher(), store, reference=NOW) == 1
    assert await fetch_news(FakeNewsFetcher(), store, reference=NOW) == 0
    assert store.counts()["NEWS"] == 1
    store.close()


class FakeJobsFetcher:
    async def get_json(self, url):
        if "remoteok" in url:
            return [{"position": "Machine Learning Engineer", "company": "Open AI", "date": "2026-11-21T06:00:00Z", "url": "https://remoteok.com/jobs/1", "description": "Training ML models"}]
        if "remotive" in url:
            return {"jobs": [{"title": "AI Engineer", "company_name": "Example", "publication_date": "2026-11-19T00:00:00Z", "url": "https://remotive.com/jobs/1"}]}
        return {"data": [], "jobs": []}


async def test_jobs_exclude_old_and_resolve_company(tmp_path):
    store = Store(tmp_path / "jobs.db")
    assert await fetch_jobs(FakeJobsFetcher(), store, reference=NOW) == 1
    job = store.get_records("JOB")[0]
    assert job["content"]["company"] == "OpenAI"
    assert len(store.get_mappings()) == 1
    store.close()

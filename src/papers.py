import asyncio
import logging
import re
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

from .net import FetchError
from .utils import iso, parse_date, utcnow

LOG = logging.getLogger(__name__)
DATASET = "pwc-archive/links-between-paper-and-code"
HF_ROWS = "https://datasets-server.huggingface.co/rows"
ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def github_repo_key(url):
    parsed = urlsplit(url or "")
    if parsed.hostname not in {"github.com", "www.github.com"} or parsed.scheme != "https":
        return None
    pieces = parsed.path.strip("/").removesuffix(".git").split("/")
    if len(pieces) < 2 or any(not re.fullmatch(r"[\w.-]+", x) for x in pieces[:2]):
        return None
    return pieces[0] + "/" + pieces[1]


def paper_candidate(row):
    repo = github_repo_key(row.get("repo_url"))
    paper_id = str(row.get("paper_arxiv_id") or "").strip()
    if not repo or not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", paper_id, re.I):
        return None
    if row.get("is_official") is False:
        return None
    return paper_id.split("v")[0], repo, row


def parse_arxiv_atom(xml):
    root = ET.fromstring(xml)
    result = {}
    for entry in root.findall(ATOM + "entry"):
        id_url = entry.findtext(ATOM + "id", default="")
        match = re.search(r"/abs/(.+)$", id_url)
        if not match:
            continue
        arxiv_id = match.group(1).split("v")[0]
        authors = [a.findtext(ATOM + "name") for a in entry.findall(ATOM + "author")]
        primary = entry.find(ARXIV + "primary_category")
        primary_category = primary.get("term") if primary is not None else None
        categories = sorted({node.get("term") for node in entry.findall(ATOM + "category") if node.get("term")})
        if primary_category and primary_category not in categories:
            categories.append(primary_category)
            categories.sort()
        result[arxiv_id] = {
            "title": " ".join((entry.findtext(ATOM + "title") or "").split()),
            "authors": [a for a in authors if a],
            "published": entry.findtext(ATOM + "published"),
            "url": "https://arxiv.org/abs/" + arxiv_id,
            "primary_category": primary_category,
            "categories": categories,
        }
    return result


async def fetch_arxiv_details(fetcher, ids):
    details = {}
    for index in range(0, len(ids), 40):
        subset = ids[index:index + 40]
        url = ARXIV_API + "?id_list=" + quote(",".join(subset), safe=",") + "&max_results=" + str(len(subset))
        try:
            parsed = parse_arxiv_atom(await fetcher.request(url))
            details.update(parsed)
        except (FetchError, ValueError, ET.ParseError) as exc:
            LOG.warning("arxiv batch failed %s (%s)", index, type(exc).__name__)
    return details


async def acquire_papers(fetcher, store, *, limit=1000, github_token="", max_pages=300, include_unverified=False):
    if not github_token and limit >= 1000:
        raise RuntimeError("GITHUB_TOKEN is required for large paper runs with current GitHub metrics")
    if not github_token:
        LOG.warning("GITHUB_TOKEN not set; small unauthenticated run may hit GitHub rate limits")
    selected = {}
    for page in range(max_pages):
        url = HF_ROWS + "?dataset=" + quote(DATASET, safe="") + "&config=default&split=train&offset=" + str(page * 100) + "&length=100"
        try:
            result = await fetcher.get_json(url)
        except FetchError as exc:
            LOG.warning("PWC dataset source unavailable at page=%d status=%s", page, exc.status)
            break
        rows = result.get("rows") or []
        if not rows:
            break
        for entry in rows:
            candidate = paper_candidate(entry.get("row") or entry)
            if candidate:
                paper_id, repo, original = candidate
                selected.setdefault(paper_id, (repo, original))
        if len(selected) >= max(limit * 2, limit + 300):
            break
    ids = list(selected)
    if not ids:
        return 0
    details = await fetch_arxiv_details(fetcher, ids)
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = "Bearer " + github_token
    cached = {}
    done = 0
    for index in range(0, len(ids), 20):
        batch = ids[index:index + 20]
        async def get_one(paper_id):
            repo, row = selected[paper_id]
            if repo in cached:
                return paper_id, cached[repo]
            try:
                repo_data = await fetcher.get_json("https://api.github.com/repos/" + repo, headers=headers)
                if not isinstance(repo_data.get("stargazers_count"), int):
                    return paper_id, None
                if repo_data.get("full_name", "").casefold() != repo.casefold():
                    LOG.info("GitHub redirect canonicalized %s => %s", repo, repo_data.get("full_name"))
                cached[repo] = repo_data
                return paper_id, repo_data
            except FetchError as exc:
                LOG.warning("GitHub metrics unavailable paper=%s status=%s", paper_id, exc.status)
                return paper_id, None
        results = await asyncio.gather(*(get_one(paper_id) for paper_id in batch))
        for paper_id, repo_data in results:
            if not repo_data:
                continue
            source = details.get(paper_id)
            if not source or not source["authors"] or not parse_date(source["published"]):
                continue
            original_repo, archive_row = selected[paper_id]
            canonical_repo = repo_data.get("html_url") or "https://github.com/" + original_repo
            entity = {
                "schemaVersion": "1.0", "recordType": "RESEARCH_PAPER",
                "source": {"name": "arXiv + Papers with Code archive + GitHub REST API", "url": source["url"]},
                "content": {"title": source["title"], "authors": source["authors"],
                            "paper_url": source["url"], "github_url": canonical_repo,
                            "github_stars": repo_data["stargazers_count"],
                            "github_stars_collected_at": iso(utcnow()),
                            "published_date": iso(parse_date(source["published"])),
                            "arxiv_primary_category": source.get("primary_category"),
                            "arxiv_categories": source.get("categories")},
                "collectedAt": iso(utcnow()),
            }
            store.upsert(entity, paper_id, {"archive": archive_row, "arxiv": source, "github": {"html_url": canonical_repo, "stargazers_count": repo_data["stargazers_count"]}})
            done += 1
            if done >= limit:
                LOG.info("research papers acquired=%s", done)
                return done
    LOG.warning("research papers acquired=%s requested=%s; do not fabricate missing rows", done, limit)
    return done

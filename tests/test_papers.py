from src.papers import github_repo_key, paper_candidate, parse_arxiv_atom


def test_paper_link_requires_real_arxiv_id_and_github_repo():
    fixture = {"paper_arxiv_id": "2106.12345", "repo_url": "https://github.com/org/real-project", "is_official": True}
    assert paper_candidate(fixture)[:2] == ("2106.12345", "org/real-project")
    assert paper_candidate({**fixture, "repo_url": "https://example.org/other"}) is None
    assert paper_candidate({**fixture, "paper_arxiv_id": "not-a-paper"}) is None
    assert paper_candidate({**fixture, "is_official": False}) is None
    assert github_repo_key("https://github.com/pytorch/pytorch.git") == "pytorch/pytorch"


def test_atom_paper_metadata_is_from_arxiv_fixture():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <id>https://arxiv.org/abs/2106.12345v2</id><title> Example Paper  </title>
      <published>2021-06-21T00:00:00Z</published>
      <author><name>Alice Doe</name></author><author><name>Bob Doe</name></author>
    </entry></feed>'''
    record = parse_arxiv_atom(xml)["2106.12345"]
    assert record["title"] == "Example Paper"
    assert record["authors"] == ["Alice Doe", "Bob Doe"]

async def test_arxiv_metadata_requests_entire_batch():
    from urllib.parse import parse_qs, urlsplit

    from src.papers import fetch_arxiv_details

    class FakeFetcher:
        def __init__(self):
            self.requested = []

        async def request(self, url):
            self.requested.append(url)
            query = parse_qs(urlsplit(url).query)
            ids = query["id_list"][0].split(",")
            batch_size = int(query.get("max_results", ["10"])[0])
            entries = "".join(
                f"<entry><id>https://arxiv.org/abs/{paper_id}</id>"
                f"<title>Paper {paper_id}</title>"
                "<published>2022-01-01T00:00:00Z</published>"
                "<author><name>Researcher</name></author></entry>"
                for paper_id in ids[:batch_size]
            )
            return f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'

    ids = [f"2201.{i:05d}" for i in range(41)]
    fetcher = FakeFetcher()
    details = await fetch_arxiv_details(fetcher, ids)

    assert len(details) == 41
    assert [parse_qs(urlsplit(url).query)["max_results"][0] for url in fetcher.requested] == ["40", "1"]

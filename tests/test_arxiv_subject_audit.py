from scripts.audit_arxiv_subjects import AI_SUBJECTS, paper_id_from_url, review_papers
from src.papers import parse_arxiv_atom


def test_arxiv_categories_are_derived_from_official_atom_terms():
    xml = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>https://arxiv.org/abs/2401.00001v2</id><title>Example</title>
      <arxiv:primary_category term="cs.LG"/><category term="cs.LG"/><category term="cs.AI"/>
      </entry></feed>'''
    item = parse_arxiv_atom(xml)["2401.00001"]
    assert item["primary_category"] == "cs.LG"
    assert item["categories"] == ["cs.AI", "cs.LG"]


def test_ai_subject_audit_preserves_uncertainty():
    rows = [
        {"source.url": "https://arxiv.org/abs/2401.00001", "content.paper_url": "https://arxiv.org/abs/2401.00001"},
        {"source.url": "https://arxiv.org/abs/2401.00002", "content.paper_url": "https://arxiv.org/abs/2401.00002"},
        {"source.url": "https://arxiv.org/abs/2401.00003", "content.paper_url": "https://arxiv.org/abs/2401.00003"},
    ]
    cache = {
        "2401.00001": {"primary_category": "cs.LG", "categories": ["cs.LG"]},
        "2401.00002": {"primary_category": "math.GT", "categories": ["math.GT"]},
    }
    ai, non_ai, missing = review_papers(rows, cache)
    assert len(ai) == len(non_ai) == len(missing) == 1
    assert paper_id_from_url("https://example.com/abs/2401.00001") is None
    assert "cs.LG" in AI_SUBJECTS
    assert "math.GT" not in AI_SUBJECTS


def test_arxiv_subject_missing_tags_are_not_mislabeled_non_ai():
    rows = [{"content.paper_url": "https://arxiv.org/abs/2401.00001"}]
    ai, other, unavailable = review_papers(rows, {"2401.00001": {"categories": [], "primary_category": None}})
    assert not ai and not other
    assert len(unavailable) == 1

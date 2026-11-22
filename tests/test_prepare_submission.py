import csv
from datetime import datetime, timezone

from scripts.prepare_submission import prepare_submission


HEADERS = {
    "startups.csv": ["source.url", "content.entityName"],
    "products.csv": ["source.url", "content.description"],
    "research_papers.csv": ["source.url", "content.github_stars"],
    "jobs.csv": ["source.url", "content.date"],
    "news.csv": ["source.url", "content.published_date"],
    "entity_mapping_log.csv": ["raw_name", "canonical_name"],
}


def _write(folder, name, rows):
    with (folder / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS[name])
        writer.writeheader()
        writer.writerows(rows)


def _read(folder, name):
    with (folder / name).open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _fixture(tmp_path):
    source = tmp_path / "csv"
    source.mkdir()
    _write(source, "startups.csv", [{"source.url": "https://example.com/s1", "content.entityName": "S1"}])
    _write(source, "products.csv", [
        {"source.url": "https://example.com/p1", "content.description": "Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference"},
        {"source.url": "https://example.com/p2", "content.description": "Real product summary"},
        {"source.url": "https://example.com/p3", "content.description": "Check out the configuration reference at https://huggingface.co/docs/hub/spaces#reference"},
    ])
    _write(source, "research_papers.csv", [{"source.url": "https://example.com/r1", "content.github_stars": "2"}])
    _write(source, "jobs.csv", [
        {"source.url": "https://example.com/j1", "content.date": "2026-11-21T12:00:00Z"},
        {"source.url": "https://example.com/j2", "content.date": "2026-11-20T11:59:59Z"},
        {"source.url": "https://example.com/j3", "content.date": "2026-11-22T12:00:01Z"},
        {"source.url": "https://example.com/j4", "content.date": "2026-11-21T15:00:00"},
    ])
    _write(source, "news.csv", [{"source.url": "https://example.com/n1", "content.published_date": "2026-11-22T11:59:59Z"}])
    _write(source, "entity_mapping_log.csv", [{"raw_name": "abc", "canonical_name": "ABC"}])
    return source


def test_builds_six_tabs_and_filters_freshness(tmp_path):
    source = _fixture(tmp_path)
    target = tmp_path / "submission"
    result = prepare_submission(source, target, as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
    assert result["sheets"]["Jobs"]["submission_rows"] == 1
    assert result["sheets"]["News"]["submission_rows"] == 1
    assert result["sheets"]["Products"]["generic_descriptions_cleared"] == 2
    assert len(_read(target, "jobs.csv")) == 1
    assert len(_read(target, "products.csv")) == 3
    assert len(_read(target, "entity_mapping_log.csv")) == 1
    assert (target / "submission_manifest.json").exists()


def test_does_not_modify_original_csvs(tmp_path):
    source = _fixture(tmp_path)
    original_text = (source / "products.csv").read_text()
    prepare_submission(source, tmp_path / "submission", as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
    assert (source / "products.csv").read_text() == original_text


def test_rejects_duplicate_source_urls(tmp_path):
    source = _fixture(tmp_path)
    _write(source, "startups.csv", [
        {"source.url": "https://example.com/s1", "content.entityName": "S1"},
        {"source.url": "https://example.com/s1", "content.entityName": "S1 again"},
    ])
    try:
        prepare_submission(source, tmp_path / "submission", as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
    except ValueError as error:
        assert "duplicate source URLs" in str(error)
    else:
        assert False, "Expected duplicate URL rejection"


def test_strict_inclusive_freshness_boundary(tmp_path):
    source = _fixture(tmp_path)
    _write(source, "jobs.csv", [
        {"source.url": "https://example.com/j1", "content.date": "2026-11-21T12:00:00Z"},
        {"source.url": "https://example.com/j2", "content.date": "2026-11-22T12:00:00Z"},
    ])
    target = tmp_path / "submission"
    prepare_submission(source, target, as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
    assert len(_read(target, "jobs.csv")) == 2


def test_strict_ai_jobs_filters_generic_roles_and_recategorizes(tmp_path):
    source = _fixture(tmp_path)
    HEADERS["jobs.csv"] = ["source.url", "content.date", "content.title", "content.role_family"]
    try:
        _write(source, "jobs.csv", [
            {"source.url": "https://example.com/j1", "content.date": "2026-11-22T11:00:00Z", "content.title": "Senior Customer Success Manager", "content.role_family": "AI / Machine Learning"},
            {"source.url": "https://example.com/j2", "content.date": "2026-11-22T11:00:00Z", "content.title": "Senior AI Engineer", "content.role_family": "AI / Machine Learning"},
        ])
        result = prepare_submission(source, tmp_path / "review", as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc), strict_ai_jobs=True)
        assert result["sheets"]["Jobs"]["submission_rows"] == 1
        assert result["sheets"]["Jobs"]["excluded_without_explicit_ai_title_evidence"] == 1
        output = _read(tmp_path / "review", "jobs.csv")
        assert output[0]["content.title"] == "Senior AI Engineer"
        assert output[0]["content.role_family"] == "Engineering"
    finally:
        HEADERS["jobs.csv"] = ["source.url", "content.date"]


def test_strict_ai_jobs_refuses_ambiguous_schema(tmp_path):
    source = _fixture(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="content.title"):
        prepare_submission(source, tmp_path / "review", as_of=datetime(2026, 11, 22, 12, tzinfo=timezone.utc), strict_ai_jobs=True)


def test_verified_ai_papers_must_have_thousand_entries(tmp_path):
    import pytest
    source = _fixture(tmp_path)
    reviewed = tmp_path / "verified.csv"
    with reviewed.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS["research_papers.csv"])
        writer.writeheader()
        writer.writerow({"source.url": "https://example.com/one", "content.github_stars": "1"})
    with pytest.raises(ValueError, match="fewer than 1,000"):
        prepare_submission(source, tmp_path / "submission", verified_papers=reviewed)
    assert not (tmp_path / "submission").exists()

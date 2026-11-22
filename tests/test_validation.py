from datetime import datetime, timezone

from src.store import Store
from src.validate import validate_submission


def test_minimums_and_source_checks_fail_closed(tmp_path):
    store = Store(tmp_path / "validate.db")
    outcome = validate_submission(store, now=datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert not outcome["ready"]
    assert len([item for item in outcome["issues"] if "minimum not met" in item]) == 3
    assert len([item for item in outcome["issues"] if "source not checked" in item]) == 10
    store.close()


def test_date_revalidated_at_submission_time(tmp_path):
    store = Store(tmp_path / "validate.db")
    for name in ("TechCrunch AI", "MIT Technology Review AI", "The Verge AI", "Google DeepMind", "Hugging Face Blog"):
        store.mark_source_check("NEWS", name, "ok", 0)
    for name in ("Remote OK", "Remotive", "Arbeitnow", "Jobicy", "Himalayas"):
        store.mark_source_check("JOB", name, "ok", 0)
    record = {"recordType": "NEWS", "source": {"url": "https://example.com/news/1", "name": "Test"},
              "content": {"title": "Verified", "published_date": "2026-11-20T23:00:00Z"}}
    store.insert_verified_signal(record, "https://example.com/news/1", {}, "2026-11-20T23:00:00Z")
    report = validate_submission(store, now=datetime(2026, 11, 22, 23, 0, 1, tzinfo=timezone.utc))
    assert any("older than 24 hours" in issue for issue in report["issues"])
    assert not any("source not checked" in issue for issue in report["issues"])
    store.close()

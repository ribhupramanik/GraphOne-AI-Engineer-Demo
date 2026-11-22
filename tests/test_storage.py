from src.store import Store
from src.export import export_csv


def test_sqlite_idempotency_and_provenance(tmp_path):
    store = Store(tmp_path / "intelligence.db")
    record = {"recordType": "STARTUP", "source": {"name": "YC", "url": "https://www.ycombinator.com/companies/a"}, "content": {"entityName": "A"}}
    store.upsert(record, "a", {"input": "fixture"})
    store.upsert(record, "a", {"input": "fixture"})
    assert store.counts() == {"STARTUP": 1}
    assert store.signal_first_seen("https://example.com/article?utm_source=ads", "raw", "2026-11-21T00:00:00Z", True)
    assert not store.signal_first_seen("https://example.com/article", "raw", "2026-11-21T00:00:00Z", True)
    store.log_mapping("A, Inc", "A", "exact", 1.0, "https://www.ycombinator.com/companies/a")
    assert export_csv(store, tmp_path / "csv")["Startups"] == 1
    assert export_csv(store, tmp_path / "csv")["Entity Mapping Log"] == 1
    assert len(list((tmp_path / "csv").glob("*.csv"))) == 6
    store.close()


def test_missing_provenance_rejected(tmp_path):
    import pytest
    store = Store(tmp_path / "test.db")
    with pytest.raises(ValueError):
        store.upsert({"recordType": "STARTUP", "source": {"url": ""}}, "a", "x")
    store.close()


def test_verified_signal_is_atomic_and_can_upgrade_from_uncertain(tmp_path):
    store = Store(tmp_path / "intelligence.db")
    url = "https://example.org/news/1"
    store.signal_first_seen(url, {"firstObserved": True}, None, False)
    record = {"recordType": "NEWS", "source": {"name": "Test", "url": url}, "content": {"title": "Real verified title"}}
    assert store.insert_verified_signal(record, url, {"published": "2026-11-21T01:00:00Z"}, "2026-11-21T01:00:00Z")
    assert not store.insert_verified_signal(record, url, "again", "2026-11-21T01:00:00Z")
    assert len(store.get_records("NEWS")) == 1
    store.close()

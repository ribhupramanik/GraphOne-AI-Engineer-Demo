import json

from src.entities import Resolver, normalise_name
from src.reconcile import reconcile_entities
from src.store import Store


def test_resolution_keeps_disconnected_entities_distinct():
    resolver = Resolver(
        directory_names=["OpenAI", "Grafana Labs", "Mistral AI", "42"],
        observed_job_names=["Grafana Labs", "grafanalabs", "Chainguard", "chainguard"],
    )
    assert normalise_name("OpenAI, Inc.") == normalise_name("Open AI")
    assert normalise_name("Mistral AI GmbH") == normalise_name("Mistral.ai")
    assert normalise_name("Zone &#038; Co") == normalise_name("Zone & Co")
    assert resolver.resolve("Open AI, Inc.")[0] == "OpenAI"
    assert resolver.resolve("grafanalabs")[0] == "Grafana Labs"
    assert resolver.resolve("chainguard")[0] == "Chainguard"
    assert resolver.resolve("GRAFANA lab")[1] == "unresolved_preserved"
    assert resolver.resolve("42")[1] == "unresolved_preserved"
    assert resolver.resolve("intercomreferrals")[0] == "intercomreferrals"
    assert resolver.resolve("A random company")[1] == "unresolved_preserved"
    assert resolver.resolve("Example Inc", source="directory") == ("Example Inc", "directory_observed_name", 0.8)


def test_reconcile_is_idempotent_and_raw_evidence_is_preserved(tmp_path):
    store = Store(tmp_path / "example.db")
    def insert(kind, key, content, raw, url):
        store.upsert({
            "schemaVersion": "1.0", "recordType": kind,
            "source": {"name": "test", "url": url},
            "content": content, "collectedAt": "2026-11-22T00:00:00Z",
        }, key, raw)

    insert("STARTUP", "grafana", {"entityName": "Grafana Labs"}, {"name": "Grafana Labs"}, "https://yc.test/grafana")
    insert("STARTUP", "other", {"entityName": "Acme Ltd"}, {"name": "Acme Ltd"}, "https://yc.test/acme")
    insert("JOB", "job1", {"company": "grafanalabs"}, {"company": "grafanalabs"}, "https://jobs.test/1")
    insert("JOB", "job2", {"company": "chainguard"}, {"company": "chainguard"}, "https://jobs.test/2")
    insert("JOB", "job3", {"company": "Chainguard"}, {"company": "Chainguard"}, "https://jobs.test/3")
    insert("JOB", "job4", {"company": "Open AI Inc."}, {"company": "Open AI Inc."}, "https://jobs.test/4")
    insert("PRODUCT", "p1", {"productName": "Demo", "startupName": None}, {"id": "huggingface/demo"}, "https://huggingface.co/spaces/huggingface/demo")
    insert("PRODUCT", "p2", {"productName": "Fake", "startupName": None}, {"id": "randomuser/ai-assistant"}, "https://huggingface.co/spaces/randomuser/ai-assistant")
    store.log_mapping("broken", "BadName", "bad_method", 0.0, "https://jobs.test/dead")

    original_raw = list(store.db.execute("SELECT raw_payload FROM records ORDER BY canonical_key"))
    preview = reconcile_entities(store, dry_run=True)
    assert preview["dry_run"]
    assert store.get_mappings()[0][0] == "broken"
    first = reconcile_entities(store)
    second = reconcile_entities(store)
    assert first["mapping_rows"] == second["mapping_rows"]
    assert first["record_values_changed"]["JOB"] == 3
    assert second["record_values_changed"] == {}
    assert first["methods"]["directory_observed_name"] == 2
    assert store.get_records("JOB")[0]["content"]["company"] == "Grafana Labs"
    assert [r["content"]["company"] for r in store.get_records("JOB")] == [
        "Grafana Labs", "Chainguard", "Chainguard", "OpenAI"
    ]
    assert store.get_records("PRODUCT")[0]["content"]["startupName"] == "Hugging Face"
    assert store.get_records("PRODUCT")[1]["content"]["startupName"] is None
    assert all(r[0] != "broken" for r in store.get_mappings())
    assert list(store.db.execute("SELECT raw_payload FROM records ORDER BY canonical_key")) == original_raw
    assert store.counts() == {"JOB": 4, "PRODUCT": 2, "STARTUP": 2}
    store.close()

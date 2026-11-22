from datetime import datetime, timezone

from src.entities import Resolver, normalise_name
from src.utils import canonical_url, fresh_within_24_hours, parse_date

NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def test_strict_freshness_inclusive_boundaries():
    assert fresh_within_24_hours("2026-11-20T08:00:00Z", NOW)
    assert fresh_within_24_hours("2026-11-21T08:00:00Z", NOW)
    assert not fresh_within_24_hours("2026-11-20T07:59:59Z", NOW)
    assert not fresh_within_24_hours("2026-11-21T08:00:01Z", NOW)


def test_relative_freshness_and_timezone_naivety():
    assert fresh_within_24_hours("2 hours ago", NOW)
    assert not fresh_within_24_hours("28 hours ago", NOW)
    assert parse_date("2026-11-21 08:00") is None
    assert not fresh_within_24_hours(None, NOW)


def test_url_normalization_removes_tracking_only():
    assert canonical_url("https://Example.com/AI/?utm_source=x&item=1#top") == "https://example.com/AI?item=1"
    assert canonical_url("javascript:alert(1)") is None


def test_entity_resolution_never_conflates_weak_matches():
    resolver = Resolver()
    assert resolver.resolve("OpenAI, Inc.")[0] == "OpenAI"
    assert resolver.resolve("Open AI")[0] == "OpenAI"
    assert resolver.resolve("Oceanic Software")[0] == "Oceanic Software"
    assert normalise_name("OpenAI Inc.") == "openai"

from datetime import datetime, timezone

from src.job_quality import ai_title_indicated, role_family_from_title
from src.signals import fetch_jobs
from src.store import Store

NOW = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)


def test_generic_ai_mention_in_company_description_is_not_an_ai_job():
    assert not ai_title_indicated("Senior Customer Success Manager")
    assert not ai_title_indicated("Salesforce Developer")
    assert not ai_title_indicated("Account Executive")
    assert not ai_title_indicated("Web Designer at AIOS")


def test_explicit_ai_roles_are_identified():
    for title in (
        "AI App Developer (ChatGPT integrations)",
        "Senior Data Scientist (Applied ML)",
        "Staff Product Manager (Machine Learning)",
        "Senior AI Platform Engineer",
    ):
        assert ai_title_indicated(title)


def test_role_family_reflects_function_not_generic_ai_label():
    assert role_family_from_title("AI Product Manager") == "Product Management"
    assert role_family_from_title("Applied AI Engineer") == "Engineering"
    assert role_family_from_title("Customer Success Manager") == "Customer Success & Support"
    assert role_family_from_title("AI Marketing Manager") == "Marketing & Growth"
    assert role_family_from_title("Data Scientist (Applied ML)") == "Data Science"


class FakeJobs:
    async def get_json(self, url):
        if "remoteok" in url:
            return [
                {"position": "Senior Customer Success Manager", "company": "ExampleAI", "date": "2026-11-22T09:00:00Z", "url": "https://example.org/jobs/non-ai", "description": "We use AI and large language models in our company."},
                {"position": "Applied AI Engineer", "company": "ExampleAI", "date": "2026-11-22T09:00:00Z", "url": "https://example.org/jobs/ai", "description": "Train foundation models."},
            ]
        return {"data": [], "jobs": []}


async def test_signal_ingestion_rejects_incidental_company_ai_mentions(tmp_path):
    store = Store(tmp_path / "jobs.db")
    assert await fetch_jobs(FakeJobs(), store, reference=NOW) == 1
    entry = store.get_records("JOB")[0]
    assert entry["content"]["role_family"] == "Engineering"
    assert entry["content"]["title"] == "Applied AI Engineer"
    store.close()

"""Quality-control helpers for government recruitment records.

Pure Python, no paid services. Used after discovery to classify records,
detect likely updates/corrigenda, and merge duplicates.
"""
from __future__ import annotations

import re
from datetime import date

UPDATE_TERMS = re.compile(
    r"\b(corrigendum|addendum|extension|revised|re-revised|modified|amendment|"
    r"extended|last date extended|notice for extension)\b", re.I
)
RECRUITMENT_TERMS = re.compile(
    r"\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|"
    r"apprentice|engagement|walk[- ]?in)\b", re.I
)

def normalized_key(job: dict) -> str:
    org = re.sub(r"\s+", " ", str(job.get("organization", ""))).lower()
    title = re.sub(r"\s+", " ", str(job.get("title", ""))).lower()
    # Remove common update words so a corrigendum can be linked to its base notice.
    title = UPDATE_TERMS.sub(" ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    org = re.sub(r"[^a-z0-9]+", " ", org).strip()
    return f"{org}|{title}"[:300]

def classify(job: dict) -> dict:
    text = " ".join(str(job.get(k, "")) for k in ("title", "qualification", "organization"))
    job["normalized_key"] = normalized_key(job)
    job["notice_type"] = "update" if UPDATE_TERMS.search(text) else "recruitment"
    job["is_recruitment"] = bool(RECRUITMENT_TERMS.search(text))
    return job

def merge_jobs(jobs: list[dict]) -> list[dict]:
    grouped = {}
    for raw in jobs:
        job = classify(dict(raw))
        key = job["normalized_key"]
        old = grouped.get(key)
        if old is None:
            grouped[key] = job
            continue

        # Preserve richer fields when two sources describe the same notice.
        for field in ("vacancies", "age_limit_years", "pay", "qualification", "deadline", "application_url"):
            if not old.get(field) and job.get(field):
                old[field] = job[field]

        # Keep the direct official source if available.
        if job.get("official_source") and not old.get("official_source"):
            grouped[key] = {**old, **job}

    return list(grouped.values())

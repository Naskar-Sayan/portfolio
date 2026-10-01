"""Production-grade validation and normalization for government recruitment records."""
from __future__ import annotations
import re
from urllib.parse import urlparse

UPDATE_RE = re.compile(r"\\b(corrigendum|addendum|extension|revised|re-revised|modified|amendment|extended|withdrawn|postponed|deferred|rescheduled)\\b", re.I)
STRONG_RE = re.compile(r"\\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|apprenticeship|apprentice|engagement|walk[- ]?in|selection process|posts?\\s+of|post\\s+of)\\b", re.I)
GENERIC_PAGE_RE = re.compile(r"^(ncsnewwebsite|home|homepage|jobs?|careers?|career|find domestic jobs|find international jobs|find career center|find skill provider|find candidates|post new jobs|ai resume builder|ncs dashboard|state-wise skill development portals|participate in a job fairs and events)$", re.I)
BAD_ORG_RE = re.compile(r"^(national career service|ncsnewwebsite|india\\.gov\\.in jobs|igod)$", re.I)


def clean(value: object, limit: int = 500) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\\s+", " ", str(value)).strip()
    return s[:limit] or None


def is_official_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower().rstrip(".")
    return host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".gov") or host.endswith(".ac.in") or host in {"ibps.in", "rrbapply.gov.in"}


def recruitment_evidence(job: dict) -> tuple[bool, list[str]]:
    evidence = []
    title = clean(job.get("title"), 300) or ""
    text = " ".join(clean(job.get(k), 1200) or "" for k in ("title", "organization", "qualification", "pay", "raw_text"))
    if STRONG_RE.search(text): evidence.append("strong_recruitment_term")
    if job.get("vacancies") is not None: evidence.append("vacancy_count")
    if job.get("deadline"): evidence.append("deadline")
    if job.get("application_url"): evidence.append("application_link")
    if job.get("document_url") or str(job.get("url", "")).lower().split("?")[0].endswith(".pdf"): evidence.append("recruitment_document")
    if title and not GENERIC_PAGE_RE.match(title): evidence.append("specific_title")
    return (len(evidence) >= 2 and "specific_title" in evidence) or ("recruitment_document" in evidence and "strong_recruitment_term" in evidence), evidence


def validate_record(job: dict) -> tuple[bool, list[str]]:
    reasons = []
    title = clean(job.get("title"), 300)
    org = clean(job.get("organization"), 300)
    url = clean(job.get("url"), 2000)
    if not title or GENERIC_PAGE_RE.match(title): reasons.append("generic_page_title")
    if not org or BAD_ORG_RE.match(org): reasons.append("generic_organization")
    if not url or not url.startswith(("http://", "https://")): reasons.append("invalid_url")
    ok, evidence = recruitment_evidence(job)
    if not ok: reasons.append("insufficient_recruitment_evidence")
    if job.get("official_source") is not True and not is_official_url(url): reasons.append("not_primary_source")
    return not reasons, reasons


def normalized_key(job: dict) -> str:
    def norm(v):
        s = re.sub(r"[^a-z0-9]+", " ", (str(v or "").lower())).strip()
        s = re.sub(r"\\b(corrigendum|addendum|extension|revised|amendment|extended)\\b", " ", s)
        return re.sub(r"\\s+", " ", s).strip()
    return f"{norm(job.get('organization'))}|{norm(job.get('title'))}"[:320]


def classify(job: dict) -> dict:
    job = dict(job)
    job["title"] = clean(job.get("title"), 300)
    job["organization"] = clean(job.get("organization"), 300)
    job["source"] = clean(job.get("source"), 300)
    job["normalized_key"] = normalized_key(job)
    text = " ".join(str(job.get(k, "")) for k in ("title", "organization", "raw_text"))
    job["is_update"] = bool(UPDATE_RE.search(text))
    job["notice_type"] = "update" if job["is_update"] else "recruitment"
    valid, reasons = validate_record(job)
    job["quality"] = {"valid": valid, "evidence": recruitment_evidence(job)[1], "rejection_reasons": reasons}
    return job


def merge_jobs(jobs: list[dict]) -> list[dict]:
    grouped = {}
    for raw in jobs:
        job = classify(raw)
        if not job["quality"]["valid"]:
            continue
        key = job["normalized_key"]
        old = grouped.get(key)
        if old is None:
            grouped[key] = job
            continue
        for field in ("vacancies", "age_limit_years", "pay", "qualification", "deadline", "application_url", "document_url"):
            if not old.get(field) and job.get(field): old[field] = job[field]
        if job.get("official_source") and not old.get("official_source"):
            grouped[key] = {**old, **job}
    return list(grouped.values())

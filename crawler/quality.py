"""Production-grade validation and normalization for government recruitment records."""
from __future__ import annotations
import re
from datetime import date
from urllib.parse import urlparse

UPDATE_RE = re.compile(r"\b(corrigendum|addendum|extension|revised|re-revised|modified|amendment|extended|withdrawn|postponed|deferred|rescheduled)\b", re.I)
STRONG_RE = re.compile(r"\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|apprenticeship|apprentice|engagement|walk[- ]?in|selection process|posts?\s+of|post\s+of|hiring|apply online)\b", re.I)
GENERIC_PAGE_RE = re.compile(
    r"^(ncsnewwebsite|home|homepage|jobs?|careers?|career|find domestic jobs|find international jobs|find career center|find skill provider|find candidates|post new jobs|ai resume builder|ncs dashboard|state-wise skill development portals|participate in a job fairs and events|current vacancies|service charges for recruitment|official website(?: of .*)?|official portal(?: of .*)?|district .*\|.*\| india|.* > home|.* - home)$",
    re.I,
)
BAD_ORG_RE = re.compile(r"^(national career service|ncsnewwebsite|india\.gov\.in jobs|igod|government portal|official portal of .* government)$", re.I)
CLOSED_RE = re.compile(r"\b(closed|expired|position filled|applications? closed|result declared|selected candidates|provisional merit list)\b", re.I)
NOISE_TITLE_RE = re.compile(r"\b(tender|procurement|e[- ]?tender|quotation|auction|expression of interest|rfp|meeting|seminar|workshop|training|scholarship|admission|syllabus|answer key|result|merit list|interview schedule|press release)\b", re.I)
OLD_DATE_RE = re.compile(r"\b(?:19|20)\d{2}\b")
GENERIC_TEXT_RE = re.compile(
    r"\b(search|site map|accessibility|skip to|screen reader|menu|contact us|about us|home|citizen services|notifications?|tenders?|events?|gallery|who'?s who)\b",
    re.I,
)

def clean(value: object, limit: int = 500) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s[:limit] or None

def is_official_url(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower().rstrip(".")
    if not host:
        return False
    return (
        host.endswith(".gov.in")
        or host.endswith(".nic.in")
        or host.endswith(".gov")
        or host.endswith(".ac.in")
        or host.endswith(".edu.in")
        or host in {"ibps.in", "rrbapply.gov.in"}
    )

def recruitment_evidence(job: dict) -> tuple[bool, list[str]]:
    evidence = []
    title = clean(job.get("title"), 300) or ""
    org = clean(job.get("organization"), 300) or ""
    raw = clean(job.get("raw_text"), 5000) or ""
    text = " ".join((title, org, clean(job.get("qualification"), 1200) or "", clean(job.get("pay"), 1200) or "", raw))

    if STRONG_RE.search(text):
        evidence.append("strong_recruitment_term")
    if job.get("vacancies") is not None:
        evidence.append("vacancy_count")
    if job.get("deadline"):
        evidence.append("deadline")
    if job.get("application_url"):
        evidence.append("application_link")
    if job.get("document_url") or str(job.get("url", "")).lower().split("?")[0].endswith(".pdf"):
        evidence.append("recruitment_document")
    if title and not GENERIC_PAGE_RE.match(title):
        evidence.append("specific_title")

    # A URL/application link alone is never sufficient. A concrete recruitment
    # record needs at least one substantive recruitment signal plus a specific
    # title, OR a real recruitment PDF plus a recruitment signal.
    substantive = any(x in evidence for x in ("vacancy_count", "deadline", "recruitment_document", "strong_recruitment_term"))
    strong_pair = "recruitment_document" in evidence and "strong_recruitment_term" in evidence
    ok = ("specific_title" in evidence and substantive and len(evidence) >= 2) or strong_pair
    return ok, evidence

def validate_record(job: dict) -> tuple[bool, list[str]]:
    reasons = []
    title = clean(job.get("title"), 300)
    org = clean(job.get("organization"), 300)
    url = clean(job.get("url"), 2000)
    raw = clean(job.get("raw_text"), 5000) or ""
    app = clean(job.get("application_url"), 2000)

    if not title or GENERIC_PAGE_RE.match(title):
        reasons.append("generic_page_title")
    if not org or BAD_ORG_RE.match(org):
        reasons.append("generic_organization")
    if not url or not url.startswith(("http://", "https://")):
        reasons.append("invalid_url")
    if not is_official_url(url):
        reasons.append("non_indian_or_unverified_domain")
    if CLOSED_RE.search(raw):
        reasons.append("closed_or_result_noise")
    if NOISE_TITLE_RE.search(title):
        reasons.append("non_recruitment_notice_type")

    # Reject old archive pages unless they contain a current deadline.
    years = [int(y) for y in OLD_DATE_RE.findall(raw)]
    if years and not job.get("deadline") and max(years) < date.today().year - 1:
        reasons.append("historical_archive")

    title_generic = bool(title and GENERIC_PAGE_RE.match(title))
    raw_has_only_navigation = bool(raw) and not STRONG_RE.search(title + " " + org) and not job.get("vacancies") and not job.get("deadline") and not job.get("document_url")
    if title_generic or raw_has_only_navigation:
        reasons.append("navigation_or_landing_page")

    if app and url and app.rstrip("/") == url.rstrip("/") and not any((job.get("deadline"), job.get("vacancies"), job.get("document_url"))):
        if not STRONG_RE.search(title + " " + org):
            reasons.append("self_link_without_recruitment_evidence")

    # Require at least two independent substantive recruitment signals.
    evidence = recruitment_evidence(job)[1]
    independent = sum(bool(x) for x in (
        job.get("vacancies") is not None,
        bool(job.get("deadline")),
        bool(job.get("document_url") or str(url or "").lower().split("?")[0].endswith(".pdf")),
        bool(job.get("qualification")),
        bool(job.get("pay")),
    ))
    if not recruitment_evidence(job)[0] or independent < 2:
        reasons.append("insufficient_independent_recruitment_evidence")

    return not reasons, reasons

def normalized_key(job: dict) -> str:
    def norm(v):
        s = re.sub(r"[^a-z0-9]+", " ", (str(v or "").lower())).strip()
        s = re.sub(r"\b(corrigendum|addendum|extension|revised|amendment|extended)\b", " ", s)
        return re.sub(r"\s+", " ", s).strip()
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
            if not old.get(field) and job.get(field):
                old[field] = job[field]
        if job.get("official_source") and not old.get("official_source"):
            grouped[key] = {**old, **job}
    return list(grouped.values())

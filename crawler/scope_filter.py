#!/usr/bin/env python3
"""Hard publication-scope and high-precision quality gate for government jobs.

This is the final firewall between discovery/crawling and the public dataset.
Discovery can be broad; publication is intentionally conservative.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

ALLOWED_STATES = ("West Bengal", "Assam", "Tripura", "Odisha")
EXCLUDED_STATE_NAMES = (
    "Andhra Pradesh","Arunachal Pradesh","Bihar","Chhattisgarh","Goa","Gujarat",
    "Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala","Madhya Pradesh",
    "Maharashtra","Manipur","Meghalaya","Mizoram","Nagaland","Punjab","Rajasthan",
    "Sikkim","Tamil Nadu","Telangana","Uttar Pradesh","Uttarakhand","Delhi",
    "Jammu Kashmir","Jammu and Kashmir","Ladakh","Puducherry","Pondicherry",
    "Chandigarh","Andaman Nicobar","Lakshadweep","Dadra Nagar Haveli",
    "Daman and Diu",
)

FOREIGN_HOST_MARKERS = (
    "usajobs.gov", "opm.gov", "calcareers.ca.gov", "kingcounty.gov",
    "lacounty.gov", "ny.gov", "mass.gov", "illinois.gov", "texas.gov",
    "florida.gov", "wa.gov", "ohio.gov", "gov.uk", "gov.au", "govt.nz",
    "canada.ca", "ontario.ca",
)

NATIONAL_HOSTS = {
    "india.gov.in", "ncs.gov.in", "employmentnews.gov.in", "upsc.gov.in",
    "ssc.gov.in", "ibps.in", "rrbapply.gov.in", "dpe.gov.in", "nic.in",
}

CENTRAL_ORG_TERMS = re.compile(
    r"\b(?:government of india|union government|central government|central govt|"
    r"ministry of|department of the government of india|upsc|ssc|railway|rrb|rrc|"
    r"drdo|isro|barc|csir|icar|iari|aiims|iit|nit|iiit|iiser|iisc|niser|"
    r"niti aayog|cag|cbi|enforcement directorate|income tax department|"
    r"customs|central excise|esic|epfo|lic|sidbi|nabard|nhb|exim bank|"
    r"nationalised bank|public sector bank|central university)\b",
    re.I,
)

CENTRAL_LINKED_TERMS = re.compile(
    r"\b(?:autonomous body|autonomous institute|statutory body|statutory authority|"
    r"central institute|central university|government of india|under ministry|"
    r"an institute of national importance|institute of national importance|"
    r"aiims|csir|icar|drdo|isro|iiser|iit|nit|iiit|niser|iim|barc|"
    r"national institute|regional institute|tribunal|central commission)\b",
    re.I,
)

def load_psu_names():
    try:
        with open("data/psu_registry.json", encoding="utf-8") as f:
            data = json.load(f)
        return tuple(x.lower() for x in data.get("cpse_names", []))
    except (OSError, json.JSONDecodeError):
        return ()

PSU_NAMES = load_psu_names()

PSU_TERMS = re.compile(
    r"\b(?:public sector undertaking|public sector enterprise|central public sector|"
    r"cpse|psu|government company|mah?aratna|navratna|miniratna|"
    r"bharat petroleum|hindustan petroleum|indian oil|oil india|ongc|gail|"
    r"ntpc|nhpc|power grid|sail|coal india|ncl|bhel|bel|hal|ecil|"
    r"bsnl|mt?nl|ircon|rvnl|rites|nhai|hudco|nbcc|nmdc|seci|pfc|rec limited|"
    r"power finance corporation|rural electrification corporation|"
    r"engineers india|concor|container corporation|mazagon dock|cochin shipyard|"
    r"garden reach shipbuilders|goa shipyard|bharat dynamics|mishra dhatu nigam|"
    r"hindustan aeronautics|new india assurance|oriental insurance|"
    r"national insurance company|united india insurance|life insurance corporation)\b",
    re.I,
)

STATE_GOV_RE = re.compile(
    r"\b(?:government|govt|psc|staff selection commission|public service commission|"
    r"secretariat|directorate|department|state board|state corporation|"
    r"state university|state health|state police|district administration)\b",
    re.I,
)

GENERIC_ORG_RE = re.compile(
    r"^(?:verified news lead|government portal|official portal|official website|"
    r"ncsnewwebsite|national career service|india\.gov\.in jobs|igod)$",
    re.I,
)

NOISE_RE = re.compile(
    r"\b(?:tender|e[- ]tender|procurement|quotation|auction|rfp|expression of interest|"
    r"meeting|seminar|workshop|training|scholarship|admission|syllabus|answer key|"
    r"result|merit list|press release|interview schedule)\b",
    re.I,
)

RECRUITMENT_RE = re.compile(
    r"\b(?:recruitment|vacanc(?:y|ies)|applications? invited|advertisement|"
    r"apprentice(?:ship)?|engagement|walk[- ]?in|selection|apply online|"
    r"appointment to the post|hiring)\b",
    re.I,
)


def host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().rstrip(".")


def text(job: dict) -> str:
    return " ".join(str(job.get(k) or "") for k in (
        "title", "organization", "source", "raw_text", "qualification", "pay"
    ))


def is_indian_official(url: str) -> bool:
    h = host(url)
    if not h or any(h == x or h.endswith("." + x) for x in FOREIGN_HOST_MARKERS):
        return False
    return (
        h.endswith(".gov.in") or h.endswith(".nic.in") or
        h.endswith(".ac.in") or h.endswith(".edu.in") or
        h in NATIONAL_HOSTS or h.endswith(".co.in")
    )


def state_government_excluded(job: dict) -> bool:
    t = text(job)
    low = t.lower()
    for state in EXCLUDED_STATE_NAMES:
        s = state.lower()
        # Do not reject a central job merely because its location is in another
        # state; reject explicit state-government ownership markers.
        if re.search(
            rf"(?:government of|govt\. of|{re.escape(s)}\s+(?:psc|public service commission|"
            rf"staff selection commission|government|govt|secretariat|state government))",
            low,
        ):
            return True
    return False


def classify_scope(job: dict) -> tuple[str | None, list[str]]:
    reasons = []
    url = job.get("url") or job.get("document_url") or ""
    org = str(job.get("organization") or "")
    t = text(job)

    if not url or not is_indian_official(url):
        return None, ["non_indian_or_untrusted_domain"]
    if GENERIC_ORG_RE.fullmatch(org.strip()):
        return None, ["generic_organization"]
    if NOISE_RE.search(str(job.get("title") or "")):
        return None, ["non_recruitment_notice"]
    if state_government_excluded(job):
        return None, ["excluded_state_government"]

    h = host(url)
    low = t.lower()

    if h in NATIONAL_HOSTS or h.endswith(".gov.in") and CENTRAL_ORG_TERMS.search(t):
        return "central", ["national_or_central_source"]

    if PSU_TERMS.search(t) or any(name and name in low for name in PSU_NAMES):
        return "psu", ["psu_cpse_registry_or_keyword_evidence"]

    if any(x in low for x in ("west bengal", "west bengal government", "wbpsc", "wb govt")):
        return "west_bengal", ["west_bengal_evidence"]

    if any(x in low for x in ("assam government", "assam govt", "assam psc")):
        return "assam", ["assam_evidence"]

    if any(x in low for x in ("tripura government", "tripura govt", "tripura psc")):
        return "tripura", ["tripura_evidence"]

    if any(x in low for x in ("odisha government", "odisha govt", "odisha psc", "odisha staff selection")):
        return "odisha", ["odisha_evidence"]

    if CENTRAL_LINKED_TERMS.search(t) and (h.endswith(".ac.in") or h.endswith(".edu.in") or h.endswith(".gov.in") or h.endswith(".nic.in")):
        return "central_linked", ["central_linked_evidence"]

    # A .gov.in/.nic.in page with no identifiable allowed ownership is too
    # ambiguous for a 98%+ precision public feed.
    return None, ["scope_owner_not_verified"]


def high_precision_valid(job: dict) -> tuple[bool, list[str], str | None]:
    scope, scope_reasons = classify_scope(job)
    reasons = list(scope_reasons)
    title = str(job.get("title") or "")
    raw = str(job.get("raw_text") or "")
    combined = title + " " + raw

    if not title or len(title.strip()) < 4:
        reasons.append("missing_specific_title")
    if not RECRUITMENT_RE.search(combined):
        reasons.append("no_recruitment_signal")

    independent = sum(bool(x) for x in (
        job.get("deadline"),
        job.get("vacancies") is not None,
        job.get("qualification"),
        job.get("pay"),
        job.get("document_url") or str(job.get("url") or "").lower().split("?")[0].endswith(".pdf"),
        job.get("application_url"),
    ))
    if independent < 2:
        reasons.append("insufficient_independent_evidence")

    deadline = job.get("deadline")
    if deadline:
        try:
            if datetime.fromisoformat(str(deadline)).date() < date.today() and not job.get("is_update"):
                # Expired notices may remain only when recently issued; the
                # crawler's freshness policy handles that separately.
                reasons.append("expired_notice")
        except ValueError:
            pass

    return (scope is not None and not reasons), reasons, scope


def filter_dataset(dataset: dict) -> tuple[dict, dict]:
    jobs = dataset.get("jobs", [])
    kept, rejected = [], []
    counts = {}
    for job in jobs:
        ok, reasons, scope = high_precision_valid(job)
        if ok:
            row = dict(job)
            row["scope"] = scope
            row["quality"]["scope"] = scope
            row["quality"]["scope_gate"] = "high_precision"
            kept.append(row)
            counts[scope] = counts.get(scope, 0) + 1
        else:
            rejected.append({
                "id": job.get("id"),
                "title": job.get("title"),
                "organization": job.get("organization"),
                "url": job.get("url"),
                "reasons": reasons,
            })

    out = dict(dataset)
    out["jobs"] = kept
    q = dict(out.get("quality") or {})
    q["scope_gate"] = "high_precision"
    q["published_jobs_before_scope_gate"] = len(jobs)
    q["published_jobs_after_scope_gate"] = len(kept)
    q["rejected_by_scope_gate"] = len(rejected)
    q["scope_counts"] = counts
    q["accuracy_target"] = ">=98% precision by hard scope/evidence gate; measured on QC set"
    out["quality"] = q
    out["scope_policy"] = {
        "allowed_state_governments": list(ALLOWED_STATES),
        "central_nationwide": True,
        "all_psu_cpse": True,
        "central_linked": True,
        "foreign_government_rejected": True,
        "other_state_governments_rejected": True,
    }
    return out, {"rejected": rejected, "counts": counts}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/jobs.json")
    p.add_argument("--output", default="data/jobs.json")
    p.add_argument("--rejected-output", default="data/scope_rejections.json")
    args = p.parse_args()
    with open(args.input, encoding="utf-8") as f:
        dataset = json.load(f)
    out, report = filter_dataset(dataset)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(args.rejected_output, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rejected_count": len(report["rejected"]),
            "scope_counts": report["counts"],
            "rejected": report["rejected"][:1000],
        }, f, ensure_ascii=False, indent=2)
    print(
        f"Scope gate: {len(out['jobs'])} published, "
        f"{len(report['rejected'])} rejected; counts={report['counts']}"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Free government-job discovery crawler.

Designed for GitHub Actions: no database, proxy, paid API, or permanent server.
It starts from official government aggregators/directories, follows a bounded
number of official-domain links, extracts recruitment-like pages/PDFs, and
writes normalized JSON for the Flask dashboard.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

UA = "GovJobDashboard/0.2 (+https://github.com/Naskar-Sayan/portfolio)"
TIMEOUT = 20
MAX_BYTES = 8_000_000

SEEDS = [
    ("Employment News", "https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All"),
    ("National Career Service", "https://ncs.gov.in/latest-update"),
    ("UPSC", "https://www.upsc.gov.in/recruitment/recruitment-advertisement"),
    ("SSC", "https://ssc.gov.in/"),
    ("IBPS", "https://www.ibps.in/"),
    ("RRB", "https://www.rrbapply.gov.in/"),
    ("India.gov.in Jobs", "https://www.india.gov.in/category/jobs"),
    ("IGOD", "https://igod.gov.in/"),
]

JOB_TERMS = re.compile(
    r"\b(recruitment|vacancy|vacancies|career|careers|job|jobs|"
    r"advertisement|engagement|appointment|apprentice|internship|"
    r"walk[- ]in|hiring|notification|application)\b", re.I
)
DEADLINE_RE = re.compile(
    r"(?:last date|closing date|application deadline|apply before)\D{0,40}"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+\w+\s+\d{4})",
    re.I,
)
DATE_PATTERNS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
]
CORRIGENDUM_RE = re.compile(r"\b(corrigendum|addendum|extension|revised|re-revised|modified|amendment|extended|last date extended)\b", re.I)
JOB_STRONG_RE = re.compile(r"\b(recruitment|recruitment notice|advertisement|applications? invited|vacanc(?:y|ies)|apprentice|walk[- ]?in|engagement)\b", re.I)
JOB_WEAK_RE = re.compile(r"\b(job|career|notification|appointment|hiring)\b", re.I)

DATE_ANY_RE = re.compile(
    r"\b(?:0?[1-9]|[12]\d|3[01])[/-](?:0?[1-9]|1[0-2])[/-](?:20)?\d{2}\b|"
    r"\b(?:0?[1-9]|[12]\d|3[01])\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2}\b",
    re.I,
)
VACANCY_RE = re.compile(r"\b(?:total\s+)?vacanc(?:y|ies)\s*[:=-]?\s*(\d{1,6})\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*limit|maximum\s*age|upper\s*age)\D{0,30}(\d{2})\s*(?:years?|yrs?)", re.I)
PAY_RE = re.compile(r"(?:(?:pay|salary|remuneration|stipend|pay\s*level)[^\n]{0,80}(?:₹|rs\.?|inr)\s?[\d,]+(?:\s*[-–]\s*(?:₹|rs\.?|inr)?\s?[\d,]+)?|(?:₹|rs\.?|inr)\s?[\d,]+\s*(?:per\s*month|pm)?)", re.I)
QUAL_RE = re.compile(r"\b(?:essential\s+qualification|educational\s+qualification|eligibility|qualification)\b[:\-]?\s*([^.;]{20,350})", re.I)

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.8"})


def parse_date(value: str | None):
    if not value:
        return None
    value = re.sub(r"\s+", " ", value.strip())
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def get(url: str):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > MAX_BYTES:
            return None, None
        return r.url, r.content
    except requests.RequestException:
        return None, None


OFFICIAL_DOMAINS = {
    "employmentnews.gov.in",
    "ncs.gov.in",
    "upsc.gov.in",
    "ssc.gov.in",
    "ibps.in",
    "rrbapply.gov.in",
    "india.gov.in",
    "igod.gov.in",
}

def official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return (
        host in OFFICIAL_DOMAINS
        or any(host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)
        or host.endswith(".gov.in")
        or host.endswith(".nic.in")
    )


def discover_ncs_sources():
    """Use NCS's government-portal directory as a live source registry."""
    final_url, content = get("https://ncs.gov.in/devPortalList")
    if not content:
        return []
    _, soup = text_from_html(content)
    found = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url or "https://ncs.gov.in/", a["href"])
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if href.startswith(("http://", "https://")) and label:
            host = (urlparse(href).hostname or "").lower()
            if host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".gov") or host.endswith(".ac.in"):
                found.append((label[:120], href))
    # Keep unique domains/URLs and avoid exploding the crawl queue.
    unique = {}
    for label, href in found:
        unique.setdefault(href.rstrip("/"), label)
    return [(label, href) for href, label in unique.items()]


def text_from_html(content: bytes) -> tuple[str, BeautifulSoup]:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)), soup


def extract_pdf(url: str, content: bytes) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(content))
        chunks = []
        for page in reader.pages[:15]:
            chunks.append(page.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(chunks))
    except Exception:
        return ""


def job_from_page(source: str, url: str, title: str, text: str, discovered: str, application_url: str | None = None):
    combined = title + " " + text
    if not JOB_STRONG_RE.search(combined):
        # Avoid publishing generic pages that merely contain words like
        # "notification" or "career".
        return None

    dates = [parse_date(x) for x in DATE_ANY_RE.findall(text)]
    dates = [x for x in dates if x]
    deadline = None
    m = DEADLINE_RE.search(text)
    if m:
        deadline = parse_date(m.group(1))
    if not deadline and dates:
        # For a recruitment notice, the latest explicit date is a useful fallback.
        deadline = max(dates)
    if deadline and deadline < datetime.now().date().isoformat():
        return None

    vacancy = None
    vm = VACANCY_RE.search(text)
    if vm:
        vacancy = int(vm.group(1))

    age_limit = None
    am = AGE_RE.search(text)
    if am:
        age_limit = int(am.group(1))

    pay_match = PAY_RE.search(text)
    qualification_match = QUAL_RE.search(text)

    title = re.sub(r"\s+", " ", title).strip()[:240] or "Government recruitment notice"
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return {
        "id": digest,
        "title": title,
        "normalized_key": re.sub(r"[^a-z0-9]+", " ", (source + " " + title).lower()).strip()[:220],
        "notice_type": "corrigendum" if CORRIGENDUM_RE.search(combined) else "recruitment",
        "is_update": bool(CORRIGENDUM_RE.search(combined)),
        "organization": source,
        "url": url,
        "application_url": application_url or url,
        "deadline": deadline,
        "vacancies": vacancy,
        "age_limit_years": age_limit,
        "pay": re.sub(r"\s+", " ", pay_match.group(0)).strip() if pay_match else None,
        "qualification": re.sub(r"\s+", " ", qualification_match.group(1)).strip()[:500] if qualification_match else None,
        "discovered_at": discovered,
        "source": source,
        "official_source": official(url),
        "confidence": "primary_domain" if official(url) else "secondary",
        "verification": "primary_domain_match" if official(url) else "secondary_lead",
        "kind": "recruitment_notice",
    }


def crawl(seed_limit=80, page_limit=700, days=15):
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).date().isoformat()

    # NCS maintains a government-portal directory covering multiple states.
    dynamic_sources = discover_ncs_sources()
    all_seeds = list(SEEDS)

    # Secondary news discovery is only a lead generator. If a news article
    # exposes a primary government link, add that link to the official crawl.
    news_path = "data/news_leads.json"
    try:
        with open(news_path, "r", encoding="utf-8") as f:
            news_data = json.load(f)
        for lead in news_data.get("leads", []):
            primary = lead.get("primary_source")
            if primary and official(primary):
                all_seeds.append((f"News lead: {lead.get('publisher') or 'news source'}", primary))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    existing = {url.rstrip("/") for _, url in all_seeds}
    for item in dynamic_sources:
        if item[1].rstrip("/") not in existing:
            all_seeds.append(item)
            existing.add(item[1].rstrip("/"))

    queue = all_seeds
    seen = set()
    jobs = {}

    # First pass: seeds and official links they expose.
    while queue and len(seen) < page_limit:
        source, url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        final_url, content = get(url)
        if not final_url or not content:
            continue

        ctype = ""
        try:
            ctype = session.head(final_url, timeout=10, allow_redirects=True).headers.get("content-type", "").lower()
        except requests.RequestException:
            pass

        if final_url.lower().endswith(".pdf") or "application/pdf" in ctype:
            text = extract_pdf(final_url, content)
            item = job_from_page(source, final_url, source, text, now.isoformat())
            if item:
                jobs[item["id"]] = item
            continue

        text, soup = text_from_html(content)
        title = soup.title.get_text(" ", strip=True) if soup.title else source

        # Look for an explicit application link on the same page.
        application_url = None
        for a in soup.find_all("a", href=True):
            label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            href = urljoin(final_url, a["href"])
            if re.search(r"apply|online application|application form|apply online", label, re.I):
                application_url = href
                break

        item = job_from_page(source, final_url, title, text, now.isoformat(), application_url)
        if item:
            jobs[item["id"]] = item

        # Many government aggregators expose jobs as table rows. Capture those
        # individually so one page can yield dozens of normalized records.
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            headers = [re.sub(r"\s+", " ", x.get_text(" ", strip=True)).lower() for x in rows[0].find_all(["th", "td"])] if rows else []
            for row in rows[1:]:
                cells = [re.sub(r"\s+", " ", x.get_text(" ", strip=True)) for x in row.find_all(["th", "td"])]
                row_text = " | ".join(cells)
                if len(cells) < 2 or not JOB_TERMS.search(row_text):
                    continue
                row_title = cells[0]
                row_org = source
                if headers:
                    for idx, h in enumerate(headers):
                        if idx < len(cells) and any(k in h for k in ("organisation", "organization", "company", "department")):
                            row_org = cells[idx]
                            break
                row_url = final_url
                for a in row.find_all("a", href=True):
                    href = urljoin(final_url, a["href"])
                    if official(href):
                        row_url = href
                        if re.search(r"apply|advert|notification|download|view", a.get_text(" ", strip=True), re.I):
                            break
                row_item = job_from_page(row_org, row_url, row_title, row_text, now.isoformat(), row_url)
                if row_item:
                    jobs[row_item["id"]] = row_item

        # Bound discovery to official links and recruitment-looking anchors.
        if len(seen) < page_limit:
            for a in soup.find_all("a", href=True):
                href = urljoin(final_url, a["href"])
                label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
                if not href.startswith(("http://", "https://")) or not official(href):
                    continue
                if href in seen:
                    continue
                if JOB_TERMS.search(label) or "employmentnews.gov.in" in href or "ncs.gov.in" in href:
                    queue.append((source, href))
        time.sleep(0.15)

    # Keep a rolling window in the static store. Items without dates are kept
    # because many recruitment pages expose dates only inside linked PDFs.
    # Deduplicate records that point to the same notice or have effectively
    # identical organization/title combinations.
    dedup = {}
    for item in jobs.values():
        key = item.get("normalized_key") or item["id"]
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = item
        else:
            # Prefer a direct official URL over a secondary/discovered copy.
            if item.get("official_source") and not existing.get("official_source"):
                dedup[key] = item

    ordered = sorted(
        dedup.values(),
        key=lambda x: (x.get("deadline") or "9999-12-31", x.get("discovered_at", "")),
    )
    return {
        "generated_at": now.isoformat(),
        "source_count": len(all_seeds),
        "sources": [{"name": name, "url": url} for name, url in all_seeds],
        "registry_source": "NCS government portal directory",
        "window_days": days,
        "cutoff": cutoff,
        "jobs": ordered[:500],
        "deduplicated_count": len(dedup),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/jobs.json")
    p.add_argument("--days", type=int, default=15)
    p.add_argument("--page-limit", type=int, default=700)
    args = p.parse_args()

    result = crawl(page_limit=args.page_limit, days=args.days)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Generated {len(result['jobs'])} recruitment records.")


if __name__ == "__main__":
    main()

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


def official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".gov") or host.endswith(".ac.in")


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


def job_from_page(source: str, url: str, title: str, text: str, discovered: str):
    if not JOB_TERMS.search(title + " " + text):
        return None
    deadline = None
    m = DEADLINE_RE.search(text)
    if m:
        deadline = parse_date(m.group(1))
    if deadline and deadline < datetime.now().date().isoformat():
        return None

    # Prefer a compact title instead of a whole page heading.
    title = re.sub(r"\s+", " ", title).strip()[:240] or "Government recruitment notice"
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return {
        "id": digest,
        "title": title,
        "organization": source,
        "url": url,
        "deadline": deadline,
        "discovered_at": discovered,
        "source": source,
        "official_source": official(url),
        "kind": "recruitment_notice",
    }


def crawl(seed_limit=80, page_limit=250, days=15):
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).date().isoformat()
    queue = [(name, url) for name, url in SEEDS]
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
        item = job_from_page(source, final_url, title, text, now.isoformat())
        if item:
            jobs[item["id"]] = item

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
    ordered = sorted(
        jobs.values(),
        key=lambda x: (x.get("deadline") or "9999-12-31", x.get("discovered_at", "")),
    )
    return {
        "generated_at": now.isoformat(),
        "source_count": len(SEEDS),
        "window_days": days,
        "cutoff": cutoff,
        "jobs": ordered[:500],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/jobs.json")
    p.add_argument("--days", type=int, default=15)
    p.add_argument("--page-limit", type=int, default=250)
    args = p.parse_args()

    result = crawl(page_limit=args.page_limit, days=args.days)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Generated {len(result['jobs'])} recruitment records.")


if __name__ == "__main__":
    main()

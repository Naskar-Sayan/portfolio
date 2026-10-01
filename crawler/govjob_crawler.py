#!/usr/bin/env python3
"""Bounded, production-oriented discovery of Indian government recruitment notices.

Design principles:
- Discovery sources/directories are never themselves published as jobs.
- A job must be backed by a concrete vacancy row or recruitment document.
- Official government/institutional URLs are required for publication.
- NCS/IGOD are live discovery seeds; no manually maintained nationwide registry.
- Secondary news is lead-only and must resolve to a primary source before publication.
"""
from __future__ import annotations

import argparse, hashlib, io, json, re, time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from quality import merge_jobs

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

UA = "GovJobDashboard/1.0 (+https://github.com/Naskar-Sayan/portfolio)"
TIMEOUT = 10
MAX_BYTES = 6_000_000
MAX_PAGES_PER_DOMAIN = 35
MAX_QUEUE_PER_DOMAIN = 60

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

OFFICIAL_EXACT = {"ibps.in", "rrbapply.gov.in"}
DISCOVERY_PATHS = re.compile(r"(recruit|vacanc|career|advert|notification|appointment|engag|apprent|intern|job|apply)", re.I)
STRONG_RE = re.compile(r"\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|apprenticeship|apprentice|engagement|walk[- ]?in|selection process)\b", re.I)
UPDATE_RE = re.compile(r"\b(corrigendum|addendum|extension|revised|re-revised|modified|amendment|extended|withdrawn|postponed|deferred|rescheduled)\b", re.I)
DEADLINE_RE = re.compile(r"(?:last date|closing date|application deadline|apply before|applications? .*? till|last date for (?:submission|application))\D{0,50}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})", re.I)
DATE_PATTERNS = ["%d/%m/%Y","%d-%m-%Y","%d/%m/%y","%d-%m-%y","%d %B %Y","%d %b %Y","%B %d, %Y","%b %d, %Y"]
VACANCY_RE = re.compile(r"\b(?:total\s+)?vacanc(?:y|ies)\s*[:=-]?\s*(\d{1,6})\b", re.I)
AGE_RE = re.compile(r"\b(?:age\s*limit|maximum\s*age|upper\s*age)\D{0,30}(\d{2})\s*(?:years?|yrs?)", re.I)
PAY_RE = re.compile(r"(?:(?:pay|salary|remuneration|stipend|pay\s*level)[^\n]{0,100}(?:₹|rs\.?|inr)\s?[\d,]+(?:\s*[-–]\s*(?:₹|rs\.?|inr)?\s?[\d,]+)?|(?:₹|rs\.?|inr)\s?[\d,]+\s*(?:per\s*month|pm)?)", re.I)
QUAL_RE = re.compile(r"\b(?:essential\s+qualification|educational\s+qualification|eligibility|qualification)\b[:\-]?\s*([^.;]{20,350})", re.I)

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.8"})

def official(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".gov") or host.endswith(".ac.in") or host in OFFICIAL_EXACT

def clean(v, limit=1000):
    if v is None: return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:limit] or None

def parse_date(v):
    if not v: return None
    v = clean(v, 80)
    for fmt in DATE_PATTERNS:
        try: return datetime.strptime(v, fmt).date().isoformat()
        except ValueError: pass
    m = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", v)
    if m:
        try:
            return datetime.strptime(
                f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}",
                "%Y-%m-%d",
            ).date().isoformat()
        except ValueError:
            pass
    return None

def get(url):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > MAX_BYTES: return None, None
        return r.url, r.content
    except requests.RequestException:
        return None, None

def html_text(content):
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script","style","noscript"]): tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)), soup

def pdf_text(content):
    if PdfReader is None: return ""
    try:
        reader = PdfReader(io.BytesIO(content))
        return re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in reader.pages[:20]))
    except Exception:
        return ""

def extract_portal_links(final_url, content):
    """Extract live government portal URLs even when buttons are JS-wrapped."""
    text, soup = html_text(content)
    found = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a["href"])
        label = clean(a.get_text(" ", strip=True), 160)
        if label and official(href):
            found.append((label, href))
    for raw in re.findall(r"https?://[^\s<>]+", content.decode("utf-8", "ignore")):
        raw = raw.rstrip(".,);]\"'")
        if official(raw): found.append(("Government portal", raw))
    unique = {}
    for label, href in found:
        unique.setdefault(href.rstrip("/"), label)
    return [(label, href) for href, label in unique.items()]

def discover_directory(url, max_pages=8):
    """Bounded recursive traversal of a government directory, without a registry."""
    start_host = (urlparse(url).hostname or "").lower()
    queue = [url]
    seen = set()
    external = {}
    while queue and len(seen) < max_pages:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        final, content = get(current)
        if not content:
            continue
        links = extract_portal_links(final, content)
        for label, href in links:
            host = (urlparse(href).hostname or "").lower()
            if host == start_host:
                if href not in seen and href not in queue:
                    # Directory navigation only; keep traversal shallow and bounded.
                    queue.append(href)
            elif official(href):
                external.setdefault(href.rstrip("/"), label)
    return [(label, href) for href, label in external.items()]

def discover_ncs_sources():
    return discover_directory("https://ncs.gov.in/devPortalList", max_pages=8)

def discover_igod_sources():
    return discover_directory("https://igod.gov.in/", max_pages=12)

def find_apply_link(soup, base):
    for a in soup.find_all("a", href=True):
        label = clean(a.get_text(" ", strip=True), 160) or ""
        href = urljoin(base, a["href"])
        if re.search(r"apply|online application|application form|apply online", label, re.I):
            return href
    return None

def extract_fields(text):
    deadline = None
    m = DEADLINE_RE.search(text or "")
    if m: deadline = parse_date(m.group(1))
    vm = VACANCY_RE.search(text or "")
    am = AGE_RE.search(text or "")
    pm = PAY_RE.search(text or "")
    qm = QUAL_RE.search(text or "")
    return {
        "deadline": deadline,
        "vacancies": int(vm.group(1)) if vm else None,
        "age_limit_years": int(am.group(1)) if am else None,
        "pay": clean(pm.group(0), 300) if pm else None,
        "qualification": clean(qm.group(1), 500) if qm else None,
    }

def make_record(org, title, url, text, discovered, application_url=None, document_url=None, source_kind="page"):
    title = clean(title, 300)
    text = clean(text, 5000) or ""
    if not title or not official(url): return None
    fields = extract_fields(text)
    strong = bool(STRONG_RE.search(title + " " + text))
    has_doc = bool(document_url or urlparse(url).path.lower().endswith(".pdf"))
    if not strong and not has_doc and not (source_kind == "table_row" and fields["vacancies"] is not None): return None
    # A generic landing page is not a vacancy record. It can still seed discovery.
    generic = re.fullmatch(r"(home|homepage|jobs?|careers?|career|ncsnewwebsite|find .*|.*dashboard.*)", title, re.I)
    if generic and source_kind != "table_row": return None
    if source_kind == "page" and not any((fields["deadline"], fields["vacancies"], fields["qualification"], fields["pay"], has_doc)):
        # Recruitment PDFs may have sparse extraction; otherwise require concrete fields.
        return None
    digest = hashlib.sha256((url + "|" + title).encode()).hexdigest()[:16]
    posting_date = None
    for candidate in re.findall(r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b", text):
        posting_date = parse_date(candidate)
        if posting_date:
            break
    return {
        "id": digest,
        "title": title,
        "organization": clean(org, 300),
        "url": url,
        "application_url": application_url or url,
        "document_url": document_url,
        **fields,
        "posting_date": posting_date,
        "discovered_at": discovered,
        "source": clean(org, 300),
        "official_source": True,
        "confidence": "primary_domain",
        "verification": "primary_domain_match",
        "notice_type": "update" if UPDATE_RE.search(title + " " + text) else "recruitment",
        "is_update": bool(UPDATE_RE.search(title + " " + text)),
        "kind": "recruitment_notice",
        "raw_text": text[:2500],
    }

def header_map(headers):
    return {i: h for i,h in enumerate(headers)}

def row_record(source, final_url, headers, cells, row, discovered):
    h = header_map(headers)
    def cell(*names):
        for i, name in h.items():
            if any(n in name for n in names) and i < len(cells):
                return cells[i]
        return None
    org = cell("organisation","organization","department","ministry","company","employer") or source
    title = cell("post","position","designation","vacancy","job","subject","advertisement") or (cells[0] if cells else None)
    issued = cell("issued","posting date","publish")
    deadline = cell("last date","closing date","deadline")
    method = cell("method of appointment","type","employment type")
    links = [(clean(a.get_text(" ", strip=True),120) or "", urljoin(final_url,a["href"])) for a in row.find_all("a", href=True)]
    official_links = [u for _,u in links if official(u)]
    base_host = (urlparse(final_url).hostname or "").lower()
    if base_host.endswith("ncs.gov.in"):
        external = [u for u in official_links if (urlparse(u).hostname or "").lower() != base_host]
        if not external:
            return None
        notice_url = external[0]
    else:
        notice_url = official_links[0] if official_links else final_url
    apply_url = next((u for label,u in links if re.search(r"apply|online application|application",label,re.I)), notice_url)
    text = " | ".join(cells)
    rec = make_record(org, title, notice_url, text + " " + (method or ""), discovered, apply_url, notice_url, "table_row")
    if rec and deadline:
        parsed_deadline = parse_date(deadline)
        if parsed_deadline:
            rec["deadline"] = parsed_deadline
    if rec and issued:
        parsed_issued = parse_date(issued)
        if parsed_issued:
            rec["posting_date"] = parsed_issued
    return rec

def extract_table_records(source, final_url, soup, discovered):
    out = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows: continue
        headers = []
        for x in rows[0].find_all(["th","td"]):
            value = clean(x.get_text(" ", strip=True), 120)
            headers.append((value or "").lower())
        if len(headers) < 2: continue
        header_text = " ".join(headers)
        # Only treat tables as vacancy tables when they expose recruitment semantics.
        if not (re.search(r"organisation|organization|post|position|vacancy|last date|advertisement|posting date", header_text, re.I)):
            continue
        for row in rows[1:]:
            cells = [clean(x.get_text(" ",strip=True),400) or "" for x in row.find_all(["th","td"])]
            if len(cells) >= 2 and (STRONG_RE.search(" | ".join(cells)) or re.search(r"last date|vacancy|advertisement", header_text, re.I)):
                rec = row_record(source, final_url, headers, cells, row, discovered)
                if rec: out.append(rec)
    return out

def crawl(page_limit=500, days=15):
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).date().isoformat()
    seeds = list(SEEDS)
    for label, url in discover_ncs_sources() + discover_igod_sources():
        seeds.append((label, url))
    # News is lead-only.
    try:
        with open("data/news_leads.json", encoding="utf-8") as f: news = json.load(f)
        for lead in news.get("leads", []):
            primary = lead.get("primary_source")
            if primary and official(primary): seeds.append(("Verified news lead", primary))
    except (OSError, json.JSONDecodeError): pass

    unique_seeds = []
    seen_seed = set()
    for name,url in seeds:
        key = url.rstrip("/")
        if key not in seen_seed:
            unique_seeds.append((name,url)); seen_seed.add(key)

    queue = list(unique_seeds)
    seen = set()
    counts = {}
    queued = {}
    raw_jobs = []
    discovery_sources = []
    while queue and len(seen) < page_limit:
        source, url = queue.pop(0)
        if url in seen: continue
        host = (urlparse(url).hostname or "").lower()
        if counts.get(host,0) >= MAX_PAGES_PER_DOMAIN: continue
        counts[host] = counts.get(host,0) + 1
        seen.add(url)
        final, content = get(url)
        if not final or not content: continue
        discovery_sources.append((source, final))
        discovered = now.isoformat()
        if final.lower().split("?",1)[0].endswith(".pdf"):
            text = pdf_text(content)
            # For PDFs, require explicit recruitment language; title comes from filename/first text.
            filename = urlparse(final).path.rsplit("/",1)[-1].rsplit(".",1)[0]
            title = clean(filename.replace("_"," ").replace("-"," "), 220) or source
            first = clean(text, 500) or ""
            if STRONG_RE.search(title + " " + text):
                rec = make_record(source, title, final, text, discovered, final, final, "page")
                if rec: raw_jobs.append(rec)
            continue

        text, soup = html_text(content)
        table_jobs = extract_table_records(source, final, soup, discovered)
        raw_jobs.extend(table_jobs)

        # Page-level publication is deliberately strict.
        page_title = soup.title.get_text(" ",strip=True) if soup.title else source
        rec = make_record(source, page_title, final, text, discovered, find_apply_link(soup,final), None, "page")
        if rec: raw_jobs.append(rec)

        # Follow only likely recruitment/discovery links on official domains.
        for a in soup.find_all("a", href=True):
            href = urljoin(final, a["href"])
            if href in seen or not href.startswith(("http://","https://")) or not official(href): continue
            label = clean(a.get_text(" ",strip=True),180) or ""
            target = href + " " + label
            thost = (urlparse(href).hostname or "").lower()
            if counts.get(thost,0) >= MAX_PAGES_PER_DOMAIN or queued.get(thost,0) >= MAX_QUEUE_PER_DOMAIN: continue
            if DISCOVERY_PATHS.search(target):
                queue.append((source,href)); queued[thost] = queued.get(thost,0) + 1
        time.sleep(0.05)

    jobs = merge_jobs(raw_jobs)
    today = now.date().isoformat()
    active = []
    for job in jobs:
        deadline = job.get("deadline")
        posting = job.get("posting_date")
        # Keep currently open notices, recently issued notices, and undated
        # primary PDFs whose parent source explicitly surfaced them.
        if deadline and deadline < today:
            if not posting or posting < cutoff:
                continue
        if posting and posting < cutoff and deadline and deadline < today:
            continue
        active.append(job)
    jobs = active
    jobs.sort(key=lambda x: (x.get("deadline") or "9999-12-31", x.get("discovered_at","")))
    source_stats = {}
    for name,url in unique_seeds:
        host = (urlparse(url).hostname or "").lower()
        source_stats.setdefault(host, {"host":host,"seed_count":0,"pages_crawled":0,"jobs_found":0})
        source_stats[host]["seed_count"] += 1
    for host,n in counts.items():
        source_stats.setdefault(host, {"host":host,"seed_count":0,"pages_crawled":0,"jobs_found":0})["pages_crawled"] = n
    for j in jobs:
        host = (urlparse(j["url"]).hostname or "").lower()
        source_stats.setdefault(host, {"host":host,"seed_count":0,"pages_crawled":0,"jobs_found":0})["jobs_found"] += 1

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "cutoff": cutoff,
        "discovery": {
            "seed_count": len(unique_seeds),
            "pages_crawled": len(seen),
            "domains_crawled": len(counts),
            "source_stats": sorted(source_stats.values(), key=lambda x:x["host"]),
        },
        "quality": {
            "raw_candidates": len(raw_jobs),
            "published_jobs": len(jobs),
            "rejected_or_deduplicated": max(0, len(raw_jobs)-len(jobs)),
            "primary_source_required": True,
        },
        "registry_source": "Live NCS + IGOD government directories",
        "jobs": jobs[:500],
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="data/jobs.json")
    p.add_argument("--days",type=int,default=15)
    p.add_argument("--page-limit",type=int,default=500)
    a=p.parse_args()
    result=crawl(a.page_limit,a.days)
    with open(a.output,"w",encoding="utf-8") as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(f"Published {len(result['jobs'])} verified recruitment records from {result['discovery']['pages_crawled']} crawled pages.")

if __name__=="__main__":
    main()

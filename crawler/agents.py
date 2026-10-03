#!/usr/bin/env python3
"""Multi-agent discovery and extraction layer for the government-job crawler.

Agents are lightweight Python workers. They discover leads; the existing
official crawler remains the publication/verification authority.

Agents:
- SearchAgent: broad web + job-site search
- StateAgent: State/UT recruitment discovery
- InstitutionAgent: universities, institutes, hospitals and autonomous bodies
- PSUAagent: PSUs/public-sector recruitment discovery
- JudiciaryAgent: courts, tribunals and judicial bodies
- DirectoryAgent: IGOD/India.gov/NCS directory expansion
- SitemapAgent: robots.txt/sitemap expansion
- JobSiteExtractorAgent: extracts structured recruitment leads from job portals
- UpdateAgent: searches for corrigenda/extensions/revised notices
- PDFAgent: prioritises recruitment PDF links

The design intentionally avoids a hand-maintained nationwide source registry.
All secondary leads are later resolved/verified by the official crawler.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

UA = "GovJobDashboard-MultiAgent/1.0 (+https://github.com/Naskar-Sayan/portfolio)"
TIMEOUT = 12
SEARCH_DELAY = 0.35
FETCH_DELAY = 0.08
MAX_RESULTS = 12
MAX_LEADS = 2500
MAX_REQUESTS = 1800

PRIMARY_SUFFIXES = (".gov.in", ".nic.in", ".ac.in", ".edu.in")
PRIMARY_EXACT = {
    "india.gov.in", "ncs.gov.in", "employmentnews.gov.in", "upsc.gov.in",
    "ssc.gov.in", "ibps.in", "rrbapply.gov.in",
}

FOREIGN_HOST_MARKERS = (
    "usajobs.gov", "opm.gov", "calcareers.ca.gov", "kingcounty.gov",
    "lacounty.gov", "ny.gov", "mass.gov", "illinois.gov", "texas.gov",
    "florida.gov", "wa.gov", "ohio.gov", "gov.uk", "gov.au", "govt.nz",
    "canada.ca", "ontario.ca",
)
RECRUITMENT_RE = re.compile(
    r"recruitment|vacanc(?:y|ies)|job|career|advertisement|notification|"
    r"appointment|engagement|apprentice|application|selection|walk[- ]?in",
    re.I,
)
UPDATE_RE = re.compile(
    r"corrigendum|addendum|extension|revised|amendment|extended|postponed|"
    r"deferred|rescheduled|withdrawn",
    re.I,
)
DEADLINE_RE = re.compile(
    r"(?:last date|closing date|deadline|apply before|applications?.{0,20}till)"
    r"[^\d]{0,50}(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
    re.I,
)
DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
)

STATES = [
    "West Bengal",
    "Assam",
    "Tripura",
    "Odisha",
]

AGENT_QUERIES = {
    # 3 PSU agents: deliberately disjoint discovery strategies.
    "PSURegistryAgent": [
        '"Department of Public Enterprises" CPSE list recruitment',
        '"Public Enterprises Survey" CPSE recruitment India',
        'site:dpe.gov.in CPSE recruitment career vacancy',
    ],
    "PSUCareerAgent": [
        'site:gov.in PSU "careers" recruitment vacancy',
        'site:co.in PSU "careers" "recruitment" India',
        '"public sector enterprise" "career" recruitment India',
    ],
    "PSUNoticeAgent": [
        '"CPSE" "recruitment notification" India',
        '"PSU" "recruitment advertisement" India',
        '"public sector" "vacancy" "apply online" India',
    ],

    # 2 central-government agents: disjoint ministry/exam and departmental searches.
    "CentralGovAgent": [
        '"central government" recruitment notification India ministry',
        'site:gov.in "recruitment" "Government of India" vacancy',
        '"Union Government" recruitment vacancy India',
    ],
    "CentralExamAgent": [
        'UPSC recruitment advertisement vacancy',
        'SSC recruitment notification vacancy India',
        'RRB RRC recruitment notification vacancy India',
        'central government banking insurance recruitment India',
    ],

    # 2 West Bengal agents: the highest-priority state layer.
    "WestBengalStateAgent": [
        '"West Bengal" government recruitment vacancy notification',
        'site:wb.gov.in recruitment vacancy',
        'site:wbpsc.gov.in recruitment advertisement',
        'site:westbengal.gov.in recruitment notification',
    ],
    "WestBengalInstitutionsAgent": [
        '"West Bengal" government hospital recruitment vacancy',
        '"West Bengal" state university recruitment vacancy',
        '"West Bengal" municipality recruitment notification',
        '"West Bengal" board corporation recruitment',
    ],

    # 2 central-linked agents: autonomous/statutory/central institutions.
    "CentralLinkedInstitutionAgent": [
        'site:ac.in "recruitment" "government of India" vacancy',
        'site:edu.in "recruitment" central institute India',
        'AIIMS CSIR ICAR recruitment notification India',
        'IIT NIT IIIT IISER recruitment India',
    ],
    "CentralLinkedBodyAgent": [
        '"autonomous body" recruitment India government',
        '"statutory body" recruitment India vacancy',
        'central commission authority board recruitment India',
        'tribunal court central government recruitment India',
    ],

    # 1 secondary-state agent: only Assam, Tripura and Odisha.
    "RegionalStateAgent": [
        '"Assam" government recruitment vacancy notification',
        '"Tripura" government recruitment vacancy notification',
        '"Odisha" government recruitment vacancy notification',
    ],
}

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.8"})


def host(url):
    return (urlparse(url).hostname or "").lower().rstrip(".")


def primary(url):
    h = host(url)
    if not h or any(h == x or h.endswith("." + x) for x in FOREIGN_HOST_MARKERS):
        return False
    return h in PRIMARY_EXACT or h.endswith(PRIMARY_SUFFIXES)


def resolve_search_url(url):
    if not url or host(url) not in {"bing.com", "www.bing.com"}:
        return url
    try:
        raw = parse_qs(urlparse(url).query).get("u", [""])[0]
        raw = unquote(raw)
        if raw.startswith("a1"):
            raw = raw[2:]
        raw += "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.urlsafe_b64decode(raw).decode("utf-8", "ignore")
        if decoded.startswith(("http://", "https://")):
            return clean_url(decoded)
    except Exception:
        pass
    return url


def cpse_context_matches(url, cpse_name):
    if not url or not cpse_name:
        return False
    final, content = fetch(url)
    if not content:
        return False
    soup = BeautifulSoup(content, "html.parser")
    title = clean(soup.title.get_text(" ", strip=True) if soup.title else "", 400).lower()
    body = clean(soup.get_text(" ", strip=True), 5000).lower()
    needle = re.sub(r"[^a-z0-9]+", " ", cpse_name.lower()).strip()
    hay = re.sub(r"[^a-z0-9]+", " ", title + " " + body)
    tokens = [x for x in needle.split() if len(x) > 2]
    return len(tokens) >= 2 and sum(t in hay for t in tokens) >= max(2, len(tokens) // 2)


def clean(value, limit=700):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def clean_url(url):
    return url.split("#", 1)[0].rstrip(".,);]>'\"")


def fetch(url):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 5_000_000:
            return r.url, b""
        return r.url, r.content
    except requests.RequestException:
        return None, b""


def parse_date(value):
    value = clean(value, 80)
    for fmt in DATE_FORMATS:
        try:
            from datetime import datetime
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", value)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def bing(query):
    url = "https://www.bing.com/search?q=" + quote(query) + "&count=50&setlang=en-IN"
    final, content = fetch(url)
    if not content:
        return []
    soup = BeautifulSoup(content, "html.parser")
    out = []
    for item in soup.select("li.b_algo"):
        a = item.select_one("h2 a[href]")
        if not a:
            continue
        href = resolve_search_url(clean_url(urljoin(final or url, a["href"])))
        title = clean(a.get_text(" ", strip=True), 300)
        p = item.select_one(".b_caption p")
        snippet = clean(p.get_text(" ", strip=True), 700) if p else ""
        if title and href:
            out.append({"url": href, "title": title, "snippet": snippet})
    return out[:MAX_RESULTS]


def candidate_from_result(agent, query, row):
    text = f"{row['title']} {row.get('snippet','')}"
    url = row["url"]
    official_url = url if primary(url) else None
    verification = "direct_official" if official_url else "secondary_lead"
    return {
        "agent": agent,
        "query": query,
        "url": url,
        "title": row["title"],
        "snippet": row.get("snippet", ""),
        "primary_source": official_url,
        "verification": verification,
        "is_update": bool(UPDATE_RE.search(text)),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def state_agent():
    out = []
    for state in STATES:
        for q in (
            f'"{state}" government recruitment vacancy notification',
            f'"{state}" govt jobs recruitment advertisement',
        ):
            for row in bing(q):
                out.append(candidate_from_result("StateAgent", q, row))
            time.sleep(SEARCH_DELAY)
    return out


def load_cpse_names():
    try:
        with open("data/psu_registry.json", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("cpse_names", [])
    except (OSError, json.JSONDecodeError):
        return []


PSU_AGENT_SHARDS = {"PSURegistryAgent": 0, "PSUCareerAgent": 1, "PSUNoticeAgent": 2}


def query_agent(name):
    out = []
    queries = list(AGENT_QUERIES.get(name, []))
    if name in PSU_AGENT_SHARDS:
        cpse = load_cpse_names()
        shard = PSU_AGENT_SHARDS[name]
        for i, organization in enumerate(cpse):
            if i % 3 != shard:
                continue
            if name == "PSURegistryAgent":
                q = f'"{organization}" recruitment careers'
            elif name == "PSUCareerAgent":
                q = f'"{organization}" current openings careers'
            else:
                q = f'"{organization}" recruitment notification advertisement'
            for row in bing(q):
                url = row["url"]
                trusted = primary(url) or cpse_context_matches(url, organization)
                if trusted:
                    item = candidate_from_result(name, q, row)
                    item["organization"] = organization
                    item["primary_source"] = url
                    item["verification"] = "direct_official_cpse" if primary(url) else "cpse_registry_name_verified"
                    out.append(item)
            time.sleep(SEARCH_DELAY)
        return out
    for q in queries:
        for row in bing(q):
            out.append(candidate_from_result(name, q, row))
        time.sleep(SEARCH_DELAY)
    return out
def directory_agent():
    # Reuses the live directories rather than maintaining a static registry.
    seeds = [
        "https://igod.gov.in/",
        "https://igod.gov.in/categories",
        "https://igod.gov.in/sg/states",
        "https://igod.gov.in/site_map",
        "https://ncs.gov.in/devPortalList",
        "https://www.india.gov.in/category/jobs",
    ]
    out = []
    seen = set()
    queue = list(seeds)
    while queue and len(seen) < 100:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        final, content = fetch(url)
        if not content:
            continue
        soup = BeautifulSoup(content, "html.parser")
        for a in soup.find_all("a", href=True):
            href = clean_url(urljoin(final or url, a["href"]))
            label = clean(a.get_text(" ", strip=True), 220)
            if not primary(href):
                continue
            row = {
                "url": href,
                "title": label or "Government directory source",
                "snippet": "",
            }
            out.append(candidate_from_result("DirectoryAgent", url, row))
            # Traverse directory navigation only on the same host.
            if host(href) == host(final or url) and href not in seen and len(queue) < 100:
                queue.append(href)
        time.sleep(FETCH_DELAY)
    return out


def sitemap_agent(urls):
    out = []
    seen = set()
    for base in list(dict.fromkeys(urls))[:250]:
        root = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
        candidates = [root + "/robots.txt", root + "/sitemap.xml", root + "/sitemap_index.xml"]
        sitemaps = []
        for candidate in candidates:
            final, content = fetch(candidate)
            if not content:
                continue
            if candidate.endswith("robots.txt"):
                sitemaps.extend(
                    line.split(":", 1)[1].strip()
                    for line in content.decode("utf-8", "ignore").splitlines()
                    if line.lower().startswith("sitemap:")
                )
            else:
                sitemaps.append(final or candidate)
        for sm in list(dict.fromkeys(sitemaps))[:5]:
            _, content = fetch(sm)
            if not content:
                continue
            try:
                root_xml = ET.fromstring(content)
            except ET.ParseError:
                continue
            for loc in root_xml.iter():
                if not loc.tag.lower().endswith("loc") or not loc.text:
                    continue
                u = clean_url(loc.text.strip())
                if primary(u) and RECRUITMENT_RE.search(u) and u not in seen:
                    seen.add(u)
                    out.append({
                        "agent": "SitemapAgent",
                        "query": "official sitemap",
                        "url": u,
                        "title": "Sitemap-discovered recruitment URL",
                        "snippet": "",
                        "primary_source": u,
                        "verification": "official_sitemap",
                        "is_update": bool(UPDATE_RE.search(u)),
                        "discovered_at": datetime.now(timezone.utc).isoformat(),
                    })
                if len(out) >= 900:
                    return out
    return out


def extract_job_site_page(url):
    """Extract recruitment-shaped rows from a secondary job site.

    This is deliberately a lead extractor, not an authority. It captures the
    job title, organisation, deadline, application/notice links and source
    page. The official crawler must resolve the employer's official notice
    before the item can appear on the public dashboard.
    """
    final, content = fetch(url)
    if not content:
        return []
    soup = BeautifulSoup(content, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True), 6000)
    out = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [clean(x.get_text(" ", strip=True), 120).lower()
                   for x in rows[0].find_all(["th", "td"])]
        if not any(re.search(r"post|job|vacancy|organization|department|last date|apply|notification", h, re.I) for h in headers):
            continue
        for row in rows[1:]:
            cells = [clean(x.get_text(" ", strip=True), 300) for x in row.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            text = " | ".join(cells)
            links = [urljoin(final or url, a["href"]) for a in row.find_all("a", href=True)]
            title = cells[0]
            for i, h in enumerate(headers):
                if re.search(r"post|job|designation|position|vacancy", h) and i < len(cells):
                    title = cells[i]
                    break
            deadline = None
            for i, h in enumerate(headers):
                if re.search(r"last date|deadline|closing", h) and i < len(cells):
                    deadline = parse_date(cells[i])
                    break
            out.append({
                "agent": "JobSiteExtractorAgent",
                "query": "job-site page extraction",
                "url": final or url,
                "title": clean(title, 300),
                "snippet": text[:700],
                "organization": next(
                    (cells[i] for i, h in enumerate(headers)
                     if re.search(r"organization|organisation|department|employer|company", h) and i < len(cells)),
                    "",
                ),
                "deadline": deadline,
                "application_url": next((u for u in links if re.search(r"apply|application", u, re.I)), links[0] if links else ""),
                "notice_url": next((u for u in links if re.search(r"notification|advert|notice|pdf", u, re.I)), ""),
                "primary_source": next((u for u in links if primary(u)), None),
                "verification": "secondary_job_site_extraction",
                "is_update": bool(UPDATE_RE.search(text)),
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            })
    # Some portals use cards rather than tables.
    if not out and RECRUITMENT_RE.search(page_text):
        for a in soup.find_all("a", href=True):
            label = clean(a.get_text(" ", strip=True), 300)
            if RECRUITMENT_RE.search(label):
                href = urljoin(final or url, a["href"])
                out.append({
                    "agent": "JobSiteExtractorAgent",
                    "query": "job-site card extraction",
                    "url": final or url,
                    "title": label,
                    "snippet": page_text[:700],
                    "organization": "",
                    "deadline": parse_date(DEADLINE_RE.search(page_text).group(1)) if DEADLINE_RE.search(page_text) else None,
                    "application_url": href,
                    "notice_url": "",
                    "primary_source": href if primary(href) else None,
                    "verification": "secondary_job_site_extraction",
                    "is_update": bool(UPDATE_RE.search(label + " " + page_text)),
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                })
    return out[:100]


def job_site_agent(search_rows):
    # Only fetch search results that look like secondary job portals. We do
    # not maintain a portal registry, and we never publish their data directly.
    secondary = []
    for row in search_rows:
        if primary(row["url"]):
            continue
        h = host(row["url"])
        if not h or any(x in h for x in ("youtube.", "facebook.", "instagram.", "linkedin.", "x.com")):
            continue
        if RECRUITMENT_RE.search(row["title"] + " " + row.get("snippet", "")):
            secondary.append(row["url"])
    secondary = list(dict.fromkeys(secondary))[:120]
    out = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(extract_job_site_page, u) for u in secondary]
        for f in as_completed(futures):
            try:
                out.extend(f.result())
            except Exception:
                pass
    return out


def update_agent():
    out = []
    for q in (
        '"corrigendum" recruitment India government',
        '"extension" recruitment last date government India',
        '"revised advertisement" recruitment India government',
        '"application deadline extended" government recruitment India',
    ):
        for row in bing(q):
            if UPDATE_RE.search(row["title"] + " " + row.get("snippet", "")):
                out.append(candidate_from_result("UpdateAgent", q, row))
        time.sleep(SEARCH_DELAY)
    return out


def run():
    # Exactly 10 isolated agents. Each agent owns a disjoint query namespace;
    # no generic Search/State/PDF/JobSite agent is allowed to cross scopes.
    agent_names = (
        "PSURegistryAgent", "PSUCareerAgent", "PSUNoticeAgent",
        "CentralGovAgent", "CentralExamAgent",
        "WestBengalStateAgent", "WestBengalInstitutionsAgent",
        "CentralLinkedInstitutionAgent", "CentralLinkedBodyAgent",
        "RegionalStateAgent",
    )

    all_rows = []
    stats = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(query_agent, name): name for name in agent_names}
        for f in as_completed(futures):
            name = futures[f]
            try:
                rows = f.result()
                stats[name] = len(rows)
                all_rows.extend(rows)
            except Exception:
                stats[name] = 0

    # RegionalStateAgent is the only state agent besides the two WB agents.
    # It is restricted by STATES to Assam, Tripura and Odisha.
    # No DirectoryAgent/StateAgent/JobSiteExtractorAgent/SitemapAgent is run
    # here because those generic agents could cross the ownership boundaries.

    dedup = {}
    for row in all_rows:
        key = (
            row.get("primary_source") or row.get("notice_url") or row.get("url") or "",
            clean(row.get("title", "")).lower(),
        )
        if key[0]:
            dedup[key] = row

    trusted_psu_domains = sorted({
        host(x.get("primary_source"))
        for x in dedup.values()
        if x.get("agent") in PSU_AGENT_SHARDS and x.get("primary_source")
    })
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agents": stats,
        "trusted_psu_domains": trusted_psu_domains,
        "agent_count": len(stats),
        "candidate_count": len(dedup),
        "official_candidate_count": sum(
            1 for x in dedup.values()
            if primary(x.get("primary_source") or x.get("notice_url") or x.get("url", ""))
        ),
        "method": "10 isolated scoped agents; disjoint query ownership; official verification remains mandatory",
        "scope_policy": {
            "psu_agents": 3,
            "central_agents": 2,
            "west_bengal_agents": 2,
            "central_linked_agents": 2,
            "secondary_state_agents": 1,
            "secondary_states": ["Assam", "Tripura", "Odisha"],
            "west_bengal_priority": "highest",
            "all_psus_required": True,
        },
        "candidates": list(dedup.values())[:MAX_LEADS],
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/agent_leads.json")
    args = parser.parse_args()
    result = run()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(
        f"Multi-agent discovery: {result['agent_count']} agents, "
        f"{result['candidate_count']} candidates, "
        f"{result['official_candidate_count']} with official sources."
    )


if __name__ == "__main__":
    main()

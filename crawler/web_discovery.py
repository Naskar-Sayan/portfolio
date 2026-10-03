#!/usr/bin/env python3
"""Open-web discovery layer for Indian government recruitment.

This module does not publish jobs. It expands discovery beyond a fixed source
registry by querying public web search results, resolving secondary pages to
official sources, and expanding discovered official domains through robots.txt
and sitemaps. The main crawler remains the authority for publication.

No paid search API is required.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

UA = "GovJobDashboard-WebDiscovery/1.0 (+https://github.com/Naskar-Sayan/portfolio)"
TIMEOUT = 15
SEARCH_DELAY = 0.8
FETCH_DELAY = 0.15
MAX_RESULTS_PER_QUERY = 25
MAX_OFFICIAL_DOMAINS = 250
MAX_OFFICIAL_URLS = 900

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
RECRUITMENT_TERMS = re.compile(
    r"\b(recruitment|recruit|vacancy|vacancies|career|careers|job|jobs|"
    r"advertisement|notification|appointment|engagement|apprentice|"
    r"apprenticeship|walk[- ]?in|application|hiring|selection)\b", re.I
)

SEARCH_QUERIES = [
    '"government recruitment" India vacancy notification',
    '"government jobs" India recruitment notification',
    '"recruitment notification" India government',
    '"vacancy" India government recruitment',
    '"applications are invited" India government',
    '"online application" government India recruitment',
    '"advertisement" "recruitment" India government',
    '"employment notification" India government',
    '"recruitment" PSU India vacancy',
    '"recruitment" university India government',
    '"recruitment" autonomous body India',
    '"recruitment" statutory body India',
    '"recruitment" board commission India',
    '"apprentice" government India notification',
    '"walk in interview" government India',
    '"সরকারি চাকরি" নিয়োগ বিজ্ঞপ্তি',
    '"सरकारी भर्ती" नौकरी अधिसूचना',
    '"सरकारी नोकरी" भरती जाहिरात',
    '"அரசு வேலை" ஆட்சேர்ப்பு அறிவிப்பு',
    '"ప్రభుత్వ ఉద్యోగం" నియామక నోటిఫికేషన్',
    '"ಸರ್ಕಾರಿ ಉದ್ಯೋಗ" ನೇಮಕಾತಿ ಅಧಿಸೂಚನೆ',
    '"സർക്കാർ ജോലി" നിയമന വിജ്ഞാപനം',
    '"સરકારી નોકરી" ભરતી જાહેરાત',
]

STATES = [
    "West Bengal",
    "Assam",
    "Tripura",
    "Odisha",
]
for state in STATES:
    SEARCH_QUERIES.extend([
        f'"{state}" government recruitment vacancy notification',
        f'"{state}" govt jobs recruitment advertisement',
        f'"{state}" government jobs application last date',
    ])

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.8"})


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def is_primary(url: str) -> bool:
    h = host(url)
    if not h or any(h == x or h.endswith("." + x) for x in FOREIGN_HOST_MARKERS):
        return False
    return h in PRIMARY_EXACT or h.endswith(PRIMARY_SUFFIXES)


def clean_url(url: str) -> str:
    return url.split("#", 1)[0].rstrip(".,);]>'\"")


def fetch(url: str):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 5_000_000:
            return r.url, b""
        return r.url, r.content
    except requests.RequestException:
        return None, b""


def bing_search(query: str):
    url = "https://www.bing.com/search?q=" + quote(query) + "&count=50&setlang=en-IN"
    final, content = fetch(url)
    if not content:
        return []
    soup = BeautifulSoup(content, "html.parser")
    results = []
    for item in soup.select("li.b_algo"):
        a = item.select_one("h2 a[href]")
        if not a:
            continue
        href = clean_url(urljoin(final or url, a["href"]))
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        snippet_node = item.select_one(".b_caption p")
        snippet = re.sub(r"\s+", " ", snippet_node.get_text(" ", strip=True)) if snippet_node else ""
        if href and title:
            results.append({"url": href, "title": title[:300], "snippet": snippet[:700]})
    return results[:MAX_RESULTS_PER_QUERY]


def google_news(query: str):
    url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-IN&gl=IN&ceid=IN:en"
    _, content = fetch(url)
    if not content:
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    rows = []
    for item in root.findall(".//item"):
        def val(name):
            node = item.find(name)
            return html.unescape(node.text or "").strip() if node is not None else ""
        rows.append({
            "url": clean_url(val("link")),
            "title": val("title")[:300],
            "snippet": BeautifulSoup(val("description"), "html.parser").get_text(" ", strip=True)[:700],
            "publisher": val("source")[:200],
            "published": val("pubDate"),
        })
    return rows


def primary_links(page_url: str):
    final, content = fetch(page_url)
    if not content:
        return []
    soup = BeautifulSoup(content, "html.parser")
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = clean_url(urljoin(final or page_url, a["href"]))
        if not is_primary(href) or href in seen:
            continue
        seen.add(href)
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        found.append((label[:200], href))
    for raw in re.findall(r'https?://[^"\'< >\s]+', content.decode("utf-8", "ignore")):
        raw = clean_url(raw)
        if is_primary(raw) and raw not in seen:
            seen.add(raw)
            found.append(("embedded official URL", raw))
    return found[:20]


def resolve_result(row):
    url = row["url"]
    if is_primary(url):
        return url, "direct_official_search_result"
    links = primary_links(url)
    for label, href in links:
        if RECRUITMENT_TERMS.search(label + " " + href):
            return href, "official_link_in_secondary_page"
    return (links[0][1], "official_link_found") if links else (None, "unverified")


def sitemap_urls(base_url: str):
    """Discover recruitment URLs from robots.txt and common sitemap locations."""
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        urljoin(root + "/", "robots.txt"),
        urljoin(root + "/", "sitemap.xml"),
        urljoin(root + "/", "sitemap_index.xml"),
    ]
    sitemaps = []
    for candidate in candidates:
        final, content = fetch(candidate)
        if not content:
            continue
        if candidate.endswith("robots.txt"):
            for line in content.decode("utf-8", "ignore").splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemaps.append(line.split(":", 1)[1].strip())
        else:
            sitemaps.append(final or candidate)

    urls, seen = [], set()
    for sm in list(dict.fromkeys(sitemaps))[:8]:
        _, content = fetch(sm)
        if not content:
            continue
        try:
            root_xml = ET.fromstring(content)
        except ET.ParseError:
            continue
        for loc in root_xml.iter():
            if loc.tag.lower().endswith("loc") and loc.text:
                u = clean_url(loc.text.strip())
                if u.startswith(("http://", "https://")) and u not in seen:
                    seen.add(u)
                    if RECRUITMENT_TERMS.search(u):
                        urls.append(u)
                if len(urls) >= 100:
                    return urls
    return urls


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/web_leads.json")
    p.add_argument("--per-query", type=int, default=8)
    args = p.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    leads, official_urls, domains = {}, {}, set()
    stats = {"queries": 0, "results": 0, "official_direct": 0,
             "resolved_from_secondary": 0, "unresolved": 0}

    for query in SEARCH_QUERIES:
        stats["queries"] += 1
        rows = bing_search(query)[:args.per_query]
        stats["results"] += len(rows)
        for row in rows:
            primary, verification = resolve_result(row)
            if primary:
                primary = clean_url(primary)
                key = primary.rstrip("/")
                official_urls.setdefault(key, {
                    "url": primary, "query": query, "title": row["title"],
                    "verification": verification,
                })
                domains.add(host(primary))
                if is_primary(row["url"]):
                    stats["official_direct"] += 1
                else:
                    stats["resolved_from_secondary"] += 1
            else:
                stats["unresolved"] += 1
            leads[row["url"]] = {
                **row, "query": query, "discovered_at": now,
                "primary_source": primary, "verification": verification,
            }
        time.sleep(SEARCH_DELAY)

    sitemap_found = 0
    for domain in list(domains)[:MAX_OFFICIAL_DOMAINS]:
        for u in sitemap_urls("https://" + domain + "/"):
            sitemap_found += 1
            official_urls.setdefault(u.rstrip("/"), {
                "url": u, "query": "official sitemap",
                "title": "Sitemap-discovered recruitment URL",
                "verification": "official_sitemap",
            })
        time.sleep(FETCH_DELAY)

    primary_list = list(official_urls.values())[:MAX_OFFICIAL_URLS]
    result = {
        "generated_at": now,
        "method": "open-web search + secondary-source resolution + official robots/sitemap expansion",
        "search_stats": stats,
        "official_domain_count": len(domains),
        "sitemap_recruitment_urls": sitemap_found,
        "lead_count": len(leads),
        "official_url_count": len(primary_list),
        "leads": list(leads.values()),
        "official_sources": primary_list,
    }

    merged = []
    try:
        with open("data/news_leads.json", encoding="utf-8") as f:
            merged.extend(json.load(f).get("leads", []))
    except (OSError, json.JSONDecodeError):
        pass
    merged.extend(result["leads"])
    dedup = {}
    for lead in merged:
        key = lead.get("url") or lead.get("primary_source") or json.dumps(lead, sort_keys=True)
        dedup[key] = lead

    with open("data/news_leads.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now,
            "method": "Google News + open-web search; official-source verification required",
            "lead_count": len(dedup),
            "web_discovery": result,
            "leads": list(dedup.values()),
        }, f, ensure_ascii=False, indent=2)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(
        f"Open-web discovery: {stats['queries']} queries, {stats['results']} results, "
        f"{len(domains)} official domains, {len(primary_list)} official URLs, "
        f"{sitemap_found} sitemap recruitment URLs."
    )


if __name__ == "__main__":
    main()

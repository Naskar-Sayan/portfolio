#!/usr/bin/env python3
"""Secondary discovery layer.

Uses free Google News RSS searches to discover possible Indian government
recruitment announcements. News is NEVER treated as authoritative: every
lead is stored separately and the verifier tries to trace it to a government
or institutional primary source.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET

UA = "GovJobDashboard-NewsDiscovery/0.3 (+https://github.com/Naskar-Sayan/portfolio)"
TIMEOUT = 20

QUERIES = [
    '"government recruitment" India vacancy notification',
    '"recruitment notification" India government jobs',
    '"vacancy" "government" India recruitment',
    '"applications are invited" India government recruitment',
    '"job notification" India government vacancy',
    '"recruitment" PSU India vacancy',
    '"recruitment" university India government vacancy',
    '"apprentice" government India notification',
]

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.8"})

PRIMARY_SUFFIXES = (".gov.in", ".nic.in", ".gov", ".ac.in", ".edu.in")
PRIMARY_EXACT = {"india.gov.in", "ncs.gov.in", "employmentnews.gov.in", "upsc.gov.in", "ssc.gov.in", "ibps.in"}

def is_primary(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in PRIMARY_EXACT or host.endswith(PRIMARY_SUFFIXES)

def fetch(url: str):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        return r.url, r.content
    except requests.RequestException:
        return None, None

def google_news_rss(query: str):
    url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-IN&gl=IN&ceid=IN:en"
    final, content = fetch(url)
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
            "query": query,
            "title": val("title"),
            "url": val("link"),
            "published": val("pubDate"),
            "publisher": val("source"),
            "description": re.sub(r"\s+", " ", BeautifulSoup(val("description"), "html.parser").get_text(" ", strip=True)),
        })
    return rows

def official_links(article_url: str):
    final, content = fetch(article_url)
    if not content:
        return []
    soup = BeautifulSoup(content, "html.parser")
    found = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(final or article_url, a["href"])
        if not href.startswith(("http://", "https://")) or not is_primary(href):
            continue
        href = href.split("#", 1)[0]
        if href not in seen:
            seen.add(href)
            label = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
            found.append({"url": href, "label": label[:200]})
    return found[:10]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/news_leads.json")
    p.add_argument("--per-query", type=int, default=10)
    args = p.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    leads = {}
    for query in QUERIES:
        for row in google_news_rss(query)[:args.per_query]:
            if not row["url"] or not row["title"]:
                continue
            key = row["url"].split("#", 1)[0]
            if key in leads:
                continue
            row["discovered_at"] = now
            row["official_links"] = official_links(row["url"])
            row["verification"] = "official_link_found" if row["official_links"] else "unverified_secondary_lead"
            row["primary_source"] = row["official_links"][0]["url"] if row["official_links"] else None
            leads[key] = row
            time.sleep(0.2)

    result = {
        "generated_at": now,
        "method": "Google News RSS secondary discovery; primary-source verification required",
        "lead_count": len(leads),
        "leads": list(leads.values()),
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Collected {len(leads)} secondary leads.")

if __name__ == "__main__":
    main()

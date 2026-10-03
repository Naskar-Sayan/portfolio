#!/usr/bin/env python3
"""Build a live CPSE/PSU organization registry from the latest DPE PE Survey."""
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
import requests

DPE_PDF = "https://www.dpe.gov.in/static/uploads/2026/01/1714f02a9605547f2b3846e46b3d2a4f.pdf"
DPE_PDF_ALT = "https://www.dpe.gov.in/static/uploads/2025/12/59f1e4e0304212412539aa93f4a91056.pdf"
DPE_MIRROR_PDF = "https://reports-pesurvey.dpe.gov.in/pesurveyreports/FY2024-25/APPENDIX-II.pdf"
JINA_PDF = "https://r.jina.ai/https://www.dpe.gov.in/static/uploads/2026/01/1714f02a9605547f2b3846e46b3d2a4f.pdf"
UA = "GovJobDashboard-PSURegistry/1.2 (+https://github.com/Naskar-Sayan/portfolio)"

def fetch_text():
    from pypdf import PdfReader
    import io
    sources = [
        ("pdf", DPE_PDF, True),
        ("pdf", DPE_PDF_ALT, True),
        ("pdf", DPE_MIRROR_PDF, False),
        ("text", JINA_PDF, True),
    ]
    errors = []
    for kind, url, verify in sources:
        try:
            r = requests.get(
                url,
                headers={"User-Agent": UA, "Accept": "application/pdf,text/plain,*/*"},
                timeout=90,
                verify=verify,
            )
            r.raise_for_status()
            if kind == "text":
                text = r.text
            else:
                reader = PdfReader(io.BytesIO(r.content))
                text = "\n".join(
                    (p.extract_text(extraction_mode="layout") or "")
                    for p in reader.pages
                )
            if len(text) < 1000:
                raise RuntimeError("DPE registry response contains unexpectedly little text")
            return text, url
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise RuntimeError("Unable to fetch DPE CPSE registry. " + " | ".join(errors))

def parse_names(text):
    # Appendix II is a numbered table; only numbered rows are CPSE entries.
    names = {}
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" |")
        m = re.match(r"^(\d{1,3})\s+(.+?)\s*$", line)
        if not m:
            continue
        number = int(m.group(1))
        name = m.group(2).strip(" |:-")
        if not (1 <= number <= 999 and 3 <= len(name) <= 180):
            continue
        if name.lower().startswith(("sector / cognate", "cpse", "s. no")):
            continue
        names[number] = name
    return [names[n] for n in sorted(names)]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/psu_registry.json")
    a = p.parse_args()
    text, source_url = fetch_text()
    names = parse_names(text)
    if len(names) < 100:
        raise RuntimeError(
            f"DPE CPSE registry extraction unexpectedly small: {len(names)}"
        )
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_url,
        "source_authority": "Department of Public Enterprises, Ministry of Finance, Government of India",
        "survey": "FY2024-25",
        "cpse_count": len(names),
        "cpse_names": names,
    }
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Loaded {len(names)} CPSE names from DPE.")

if __name__ == "__main__":
    main()

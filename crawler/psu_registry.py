#!/usr/bin/env python3
"""Build a live CPSE/PSU organization registry from the latest DPE PE Survey."""
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
import requests

DPE_PDF = "https://reports-pesurvey.dpe.gov.in/pesurveyreports/FY2024-25/APPENDIX-II.pdf"
UA = "GovJobDashboard-PSURegistry/1.0 (+https://github.com/Naskar-Sayan/portfolio)"

def fetch_text():
    r=requests.get(DPE_PDF,headers={"User-Agent":UA},timeout=45)
    r.raise_for_status()
    from pypdf import PdfReader
    import io
    reader=PdfReader(io.BytesIO(r.content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)

def parse_names(text):
    names=set()
    for line in text.splitlines():
        line=re.sub(r"\s+"," ",line).strip(" |")
        m=re.search(r"(?:S\.\s*No\.?\s*\d+\s*\|\s*.*?\|\s*CPSE\s+|\bCPSE\s+)(.+)$",line,re.I)
        if not m: continue
        name=m.group(1).strip(" |:-")
        if 3 <= len(name) <= 180 and not re.search(r"^(sector|cognate group|CPSE)$",name,re.I):
            names.add(name)
    # De-duplicate obvious headers and keep only enterprise-like entries.
    bad=("sector / cognate group","central public sector enterprises","appendix")
    return sorted(n for n in names if not any(x in n.lower() for x in bad))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="data/psu_registry.json")
    a=p.parse_args()
    text=fetch_text()
    names=parse_names(text)
    if len(names) < 100:
        raise RuntimeError(f"DPE CPSE registry extraction unexpectedly small: {len(names)}")
    out={
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "source":DPE_PDF,
      "source_authority":"Department of Public Enterprises, Ministry of Finance, Government of India",
      "survey":"FY2024-25",
      "cpse_count":len(names),
      "cpse_names":names,
    }
    with open(a.output,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"Loaded {len(names)} CPSE names from DPE.")

if __name__=="__main__": main()

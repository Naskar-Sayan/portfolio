#!/usr/bin/env python3
"""Independent QC with separate precision guarantees per publication tier."""
from __future__ import annotations
import argparse,json,re
from urllib.parse import urlparse
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from scope_filter import psu_context_official

FOREIGN=("usajobs.gov","opm.gov","calcareers.ca.gov","kingcounty.gov","lacounty.gov","gov.uk","gov.au","canada.ca","ontario.ca")
NOISE=re.compile(r"\b(tender|procurement|quotation|auction|rfp|meeting|seminar|workshop|scholarship|admission|syllabus|answer key|result|merit list|press release)\b",re.I)
RECRUIT=re.compile(r"\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|apprentice(?:ship)?|engagement|walk[- ]?in|selection|apply online|appointment to the post|hiring|post of|posts?)\b",re.I)
def h(url): return (urlparse(url or "").hostname or "").lower().rstrip(".")
def official(url,job=None):
    x=h(url)
    if x.endswith((".gov.in",".nic.in",".ac.in",".edu.in")) or x in {"ibps.in","rrbapply.gov.in","india.gov.in","ncs.gov.in","employmentnews.gov.in"}:
        return True
    if job and psu_context_official(job):
        return True
    try:
        with open("data/psu_domains.json",encoding="utf-8") as f:
            domains={str(v).lower().rstrip(".") for v in json.load(f).get("domains",[])}
        return x in domains and x.endswith((".co.in",".gov.in",".nic.in",".ac.in",".edu.in",".in"))
    except (OSError,ValueError,TypeError):
        return False
def audit(j):
    t=" ".join(str(j.get(k) or "") for k in ("title","organization","source","raw_text","qualification","pay")); low=t.lower(); reasons=[]
    if not official(j.get("url") or j.get("document_url"),j): reasons.append("untrusted_domain")
    if any(h(j.get("url") or j.get("document_url"))==f or h(j.get("url") or j.get("document_url")).endswith("."+f) for f in FOREIGN): reasons.append("foreign_domain")
    if NOISE.search(str(j.get("title") or "")): reasons.append("notice_noise")
    if not RECRUIT.search(t): reasons.append("no_recruitment_signal")
    if len(str(j.get("title") or "").strip())<4: reasons.append("weak_title")
    evidence=sum(bool(v) for v in (j.get("deadline"),j.get("vacancies") is not None,j.get("qualification"),j.get("pay"),j.get("document_url") or str(j.get("url") or "").lower().split("?")[0].endswith(".pdf"),j.get("application_url")))
    required={"verified":2,"high_confidence":1,"verify":0}.get(j.get("publication_tier","verified"),2)
    if evidence<required: reasons.append("insufficient_evidence")
    return reasons

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",default="data/jobs.json"); p.add_argument("--min-score",type=float,default=.98); a=p.parse_args()
    d=json.load(open(a.input,encoding="utf-8")); jobs=d.get("jobs",[])
    if not jobs: print("QC: zero published jobs; fail closed."); raise SystemExit(2)
    # Coverage checks remain mandatory.
    try:
        agents=json.load(open("data/agent_leads.json",encoding="utf-8")); registry=json.load(open("data/psu_registry.json",encoding="utf-8")); domains=json.load(open("data/psu_domains.json",encoding="utf-8"))
        required=("PSURegistryAgent","PSUCareerAgent","PSUNoticeAgent","CentralGovAgent","CentralExamAgent","WestBengalStateAgent","WestBengalInstitutionsAgent","CentralLinkedInstitutionAgent","CentralLinkedBodyAgent","RegionalStateAgent")
        missing=[x for x in required if not agents.get("agents",{}).get(x)]
        if agents.get("agent_count")!=10 or missing or int(registry.get("cpse_count",0))<250 or len(domains.get("domains",[]))<10:
            print(f"QC coverage failure: agents={agents.get('agent_count')}, missing={missing}, cpse={registry.get('cpse_count')}, domains={len(domains.get('domains',[]))}")
            raise SystemExit(2)
    except (OSError,ValueError,TypeError) as e: print(f"QC coverage failure: {e}"); raise SystemExit(2)
    tiers={}
    for j in jobs: tiers.setdefault(j.get("publication_tier","unknown"),[]).append(j)
    results={}
    for tier,rows in tiers.items():
        failures=[{"id":j.get("id"),"title":j.get("title"),"url":j.get("url"),"reasons":audit(j)} for j in rows]
        failures=[x for x in failures if x["reasons"]]
        score=1-len(failures)/len(rows)
        results[tier]={"rows":len(rows),"failed":len(failures),"score":score}
        print(f"QC {tier}: {score:.2%} ({len(rows)} rows, {len(failures)} failed)")
        if tier=="verified" and score<a.min_score:
            print(json.dumps(failures[:20],ensure_ascii=False,indent=2)); raise SystemExit(1)
        if tier=="high_confidence" and score<.90:
            print(json.dumps(failures[:20],ensure_ascii=False,indent=2)); raise SystemExit(1)
        if tier=="verify" and score<.75:
            print(json.dumps(failures[:20],ensure_ascii=False,indent=2)); raise SystemExit(1)
    d.setdefault("quality",{})["tier_qc"]=results
    with open(a.input,"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=2)
if __name__=="__main__": main()

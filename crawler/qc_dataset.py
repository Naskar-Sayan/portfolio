#!/usr/bin/env python3
"""Independent publication audit for the government-jobs dataset.

This is a rule-based precision gate. It is not a statistical proof of real-world
accuracy; it prevents publication when more than 2% of rows fail independent
scope/recruitment checks.
"""
from __future__ import annotations
import argparse, json, re
from urllib.parse import urlparse

FOREIGN = (
    "usajobs.gov","opm.gov","calcareers.ca.gov","kingcounty.gov","lacounty.gov",
    "gov.uk","gov.au","canada.ca","ontario.ca",
)
EXCLUDED = (
    "government of goa","goa psc","goa staff selection",
    "government of gujarat","gujarat psc","government of maharashtra",
    "maharashtra psc","government of karnataka","karnataka psc",
    "government of kerala","kerala psc","government of tamil nadu",
    "government of telangana","government of uttar pradesh","up psc",
    "government of bihar","bihar psc","government of jharkhand",
    "government of rajasthan","rajasthan psc","government of punjab",
    "government of haryana","haryana psc","government of sikkim",
    "sikkim psc","government of manipur","government of meghalaya",
    "government of mizoram","government of nagaland","government of chhattisgarh",
    "government of madhya pradesh","madhya pradesh psc","government of andhra",
    "government of arunachal","government of tripura", # tripura is allowed, handled below
    "government of assam","government of odisha","government of west bengal",
)
NOISE=re.compile(r"\b(tender|procurement|quotation|auction|rfp|meeting|seminar|workshop|scholarship|admission|syllabus|answer key|result|merit list|press release)\b",re.I)
RECRUIT=re.compile(r"\b(recruitment|vacanc(?:y|ies)|applications? invited|advertisement|apprentice(?:ship)?|engagement|walk[- ]?in|selection|apply online|appointment to the post|hiring)\b",re.I)

def h(url): return (urlparse(url or "").hostname or "").lower().rstrip(".")
def official(url):
    x=h(url)
    return (x.endswith(".gov.in") or x.endswith(".nic.in") or x.endswith(".ac.in") or
            x.endswith(".edu.in") or x.endswith(".co.in") or x in {"ibps.in","rrbapply.gov.in","india.gov.in","ncs.gov.in","employmentnews.gov.in"})
def allowed_state_text(t):
    low=t.lower()
    # Explicitly allowed state-government markers.
    allowed=("west bengal","wbpsc","assam government","assam psc","tripura government","tripura psc","odisha government","odisha psc","odisha staff selection")
    return any(x in low for x in allowed)
def audit(job):
    t=" ".join(str(job.get(k) or "") for k in ("title","organization","source","raw_text","qualification","pay"))
    low=t.lower()
    x=h(job.get("url") or job.get("document_url"))
    reasons=[]
    if not official(job.get("url") or job.get("document_url")): reasons.append("untrusted_domain")
    if any(x==f or x.endswith("."+f) for f in FOREIGN): reasons.append("foreign_domain")
    if NOISE.search(str(job.get("title") or "")): reasons.append("notice_noise")
    if not RECRUIT.search(t): reasons.append("no_recruitment_signal")
    if len(str(job.get("title") or "").strip())<4: reasons.append("weak_title")
    evidence=sum(bool(v) for v in (
        job.get("deadline"),job.get("vacancies") is not None,job.get("qualification"),
        job.get("pay"),job.get("document_url") or str(job.get("url") or "").lower().split("?")[0].endswith(".pdf"),
        job.get("application_url")))
    if evidence<2: reasons.append("insufficient_evidence")
    if any(s in low for s in EXCLUDED):
        # Allowed state government sources are exempt from this generic check.
        if not allowed_state_text(t):
            reasons.append("excluded_state")
    if job.get("scope") not in {"central","psu","central_linked","west_bengal","assam","tripura","odisha"}:
        reasons.append("missing_scope")
    return reasons

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="data/jobs.json")
    p.add_argument("--min-score",type=float,default=.98)
    a=p.parse_args()
    d=json.load(open(a.input,encoding="utf-8"))
    jobs=d.get("jobs",[])
    if not jobs:
        print("QC: zero published jobs; fail closed.")
        raise SystemExit(2)

    # Discovery coverage is part of the publication gate. A perfect row-level
    # score is meaningless if the required agents or CPSE registry did not run.
    try:
        agents=json.load(open("data/agent_leads.json",encoding="utf-8"))
        registry=json.load(open("data/psu_registry.json",encoding="utf-8"))
        domains=json.load(open("data/psu_domains.json",encoding="utf-8"))
        required_agents=(
            "PSURegistryAgent","PSUCareerAgent","PSUNoticeAgent",
            "CentralGovAgent","CentralExamAgent",
            "WestBengalStateAgent","WestBengalInstitutionsAgent",
            "CentralLinkedInstitutionAgent","CentralLinkedBodyAgent",
            "RegionalStateAgent",
        )
        stats=agents.get("agents",{})
        missing=[x for x in required_agents if not stats.get(x)]
        if agents.get("agent_count") != 10 or missing:
            print(f"QC coverage failure: agent_count={agents.get('agent_count')}, missing={missing}")
            raise SystemExit(2)
        if int(registry.get("cpse_count",0)) < 250:
            print(f"QC coverage failure: CPSE registry too small: {registry.get('cpse_count')}")
            raise SystemExit(2)
        if len(domains.get("domains",[])) < 10:
            print(f"QC coverage failure: trusted PSU domains too small: {len(domains.get('domains',[]))}")
            raise SystemExit(2)
    except (OSError, ValueError, TypeError) as exc:
        print(f"QC coverage failure: {exc}")
        raise SystemExit(2)

    failures=[{"id":j.get("id"),"title":j.get("title"),"url":j.get("url"),"reasons":audit(j)} for j in jobs]
    failures=[x for x in failures if x["reasons"]]
    score=1-len(failures)/len(jobs)
    print(f"QC score={score:.4%}; rows={len(jobs)}; failed={len(failures)}; required={a.min_score:.2%}")
    if failures:
        print(json.dumps(failures[:20],ensure_ascii=False,indent=2))
    if score < a.min_score:
        raise SystemExit(1)
if __name__=="__main__": main()

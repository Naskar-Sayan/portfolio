#!/usr/bin/env python3
"""Multi-stage publication gate for government-job discovery.

Architecture:
  0. hard safety exclusions (foreign/non-government/noise)
  1. provenance classification (official/recognized Indian source)
  2. ownership/scope classification (central/PSU/state/linked)
  3. recruitment evidence scoring
  4. publication tiering:
       verified       = strongest evidence; included in 98% precision QC
       high_confidence= strong government evidence; visible but separately labelled
       verify         = useful lead with provenance but incomplete evidence
  5. reject only when the record is unsafe, clearly irrelevant, duplicate, or
     lacks enough provenance to be useful.

The old single hard gate is intentionally replaced: recall is protected by
publication tiers while the verified tier retains the strict quality target.
"""
from __future__ import annotations
import argparse, json, re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

ALLOWED_STATES=("West Bengal","Assam","Tripura","Odisha")
FOREIGN_HOST_MARKERS=("usajobs.gov","opm.gov","calcareers.ca.gov","kingcounty.gov","lacounty.gov",
"ny.gov","mass.gov","illinois.gov","texas.gov","florida.gov","wa.gov","ohio.gov",
"gov.uk","gov.au","govt.nz","canada.ca","ontario.ca")
NATIONAL_HOSTS={"india.gov.in","ncs.gov.in","employmentnews.gov.in","upsc.gov.in","ssc.gov.in",
"ibps.in","rrbapply.gov.in","dpe.gov.in","nic.in"}
STATE_DOMAIN_MARKERS=("ap.gov.in","arunachal.gov.in","bihar.gov.in","cg.gov.in","chhattisgarh.gov.in",
"goa.gov.in","gujarat.gov.in","haryana.gov.in","himachal.gov.in","jharkhand.gov.in","karnataka.gov.in",
"kerala.gov.in","mp.gov.in","maharashtra.gov.in","manipur.gov.in","meghalaya.gov.in","mizoram.gov.in",
"nagaland.gov.in","punjab.gov.in","rajasthan.gov.in","sikkim.gov.in","tn.gov.in","telangana.gov.in",
"up.gov.in","uk.gov.in","delhi.gov.in","jk.gov.in","ladakh.gov.in","py.gov.in","chandigarh.gov.in",
"andaman.gov.in","lakshadweep.gov.in","dnh.gov.in","ddd.gov.in")
EXCLUDED_STATE_NAMES=("Andhra Pradesh","Arunachal Pradesh","Bihar","Chhattisgarh","Goa","Gujarat","Haryana",
"Jharkhand","Karnataka","Kerala","Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram",
"Nagaland","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana","Uttar Pradesh","Uttarakhand","Delhi",
"Jammu Kashmir","Jammu and Kashmir","Ladakh","Puducherry","Pondicherry","Chandigarh","Andaman Nicobar",
"Lakshadweep","Dadra Nagar Haveli","Daman and Diu")
CENTRAL_ORG_TERMS=re.compile(r"\b(?:government of india|union government|central government|central govt|ministry of|"
r"department of the government of india|upsc|ssc|railway|rrb|rrc|drdo|isro|barc|csir|icar|iari|aiims|"
r"iit|nit|iiit|iiser|iisc|niser|niti aayog|cag|cbi|enforcement directorate|income tax department|"
r"customs|central excise|esic|epfo|lic|sidbi|nabard|nhb|exim bank|nationalised bank|public sector bank|"
r"central university)\b",re.I)
CENTRAL_LINKED_TERMS=re.compile(r"\b(?:autonomous body|autonomous institute|statutory body|statutory authority|"
r"central institute|central university|government of india|under ministry|institute of national importance|"
r"aiims|csir|icar|drdo|isro|iiser|iit|nit|iiit|niser|iim|barc|national institute|regional institute|"
r"tribunal|central commission)\b",re.I)
PSU_TERMS=re.compile(r"\b(?:public sector undertaking|public sector enterprise|central public sector|cpse|psu|"
r"government company|maharatna|navratna|miniratna|bharat petroleum|hindustan petroleum|indian oil|oil india|"
r"ongc|gail|ntpc|nhpc|power grid|sail|coal india|ncl|bhel|bel|hal|ecil|bsnl|mtnl|ircon|rvnl|rites|nhai|"
r"hudco|nbcc|nmdc|seci|pfc|rec limited|engineers india|concor|mazagon dock|cochin shipyard|"
r"bharat dynamics|mishra dhatu nigam|hindustan aeronautics|new india assurance|oriental insurance|"
r"national insurance company|united india insurance|life insurance corporation)\b",re.I)
GENERIC_ORG_RE=re.compile(r"^(?:verified news lead|government portal|official portal|official website|"
r"ncsnewwebsite|national career service|india\.gov\.in jobs|igod|employment news)$",re.I)
GENERIC_TITLE_RE=re.compile(r"^(?:employment news|all jobs|latest jobs|current vacancies?|current openings?|"
r"recruitment|careers?|jobs? at .*)$",re.I)
NOISE_RE=re.compile(r"\b(?:tender|e[- ]tender|procurement|quotation|auction|rfp|expression of interest|"
r"meeting|seminar|workshop|training|scholarship|admission|syllabus|answer key|result|merit list|"
r"press release|interview schedule)\b",re.I)
RECRUITMENT_RE=re.compile(r"\b(?:recruitment|vacanc(?:y|ies)|applications? invited|advertisement|"
r"apprentice(?:ship)?|engagement|walk[- ]?in|selection|apply online|appointment to the post|hiring|"
r"post of|posts?)\b",re.I)

def load_json_names(path,key):
    try:
        with open(path,encoding="utf-8") as f: return tuple(str(x).lower() for x in json.load(f).get(key,[]))
    except (OSError,json.JSONDecodeError): return ()
PSU_NAMES=load_json_names("data/psu_registry.json","cpse_names")
TRUSTED_PSU_DOMAINS=load_json_names("data/psu_domains.json","domains")

def host(url): return (urlparse(url or "").hostname or "").lower().rstrip(".")
def text(job): return " ".join(str(job.get(k) or "") for k in
("title","organization","source","raw_text","qualification","pay"))

def is_indian_official(url,allow_trusted_psu=False):
    h=host(url)
    if not h or any(h==x or h.endswith("."+x) for x in FOREIGN_HOST_MARKERS): return False
    if allow_trusted_psu and h in TRUSTED_PSU_DOMAINS and h.endswith((".co.in",".gov.in",".nic.in",".ac.in",".edu.in",".in")): return True
    return h.endswith(".gov.in") or h.endswith(".nic.in") or h.endswith(".ac.in") or h.endswith(".edu.in") or h in NATIONAL_HOSTS

def psu_context_official(job):
    """Accept a PSU commercial domain only when the host is corroborated by the organization."""
    url=job.get("url") or job.get("document_url") or ""
    h=host(url)
    if not h or not h.endswith((".co.in",".in",".com",".org")):
        return False
    t=text(job).lower()
    if not PSU_TERMS.search(t) and not any(n and n in t for n in PSU_NAMES):
        return False
    labels=[x for x in h.split(".") if x not in {"www","co","in","com","org","net","gov","nic"}]
    org=str(job.get("organization") or "").lower()
    org_tokens={re.sub(r"[^a-z0-9]","",x) for x in re.findall(r"[a-z0-9]+",org)}
    return any(label in org_tokens and len(label)>=3 for label in labels)

def state_government_excluded(job):
    t=text(job).lower(); h=host(str(job.get("url") or job.get("document_url") or ""))
    return any(h==d or h.endswith("."+d) for d in STATE_DOMAIN_MARKERS) or any(
        re.search(rf"(?:government of|govt\. of|{re.escape(s.lower())}\s+(?:psc|public service commission|staff selection commission|government|govt|secretariat|state government))",t)
        for s in EXCLUDED_STATE_NAMES)

def classify_scope(job):
    t=text(job); low=t.lower(); h=host(job.get("url") or job.get("document_url") or "")
    if any(x in low for x in ("west bengal","wbpsc","wb govt")): return "west_bengal",["west_bengal_evidence"]
    if any(x in low for x in ("assam government","assam govt","assam psc")): return "assam",["assam_evidence"]
    if any(x in low for x in ("tripura government","tripura govt","tripura psc")): return "tripura",["tripura_evidence"]
    if any(x in low for x in ("odisha government","odisha govt","odisha psc","odisha staff selection")): return "odisha",["odisha_evidence"]
    if PSU_TERMS.search(t) or any(n and n in low for n in PSU_NAMES) or psu_context_official(job): return "psu",["psu_registry_or_keyword"]
    if h in NATIONAL_HOSTS or (h.endswith(".gov.in") and CENTRAL_ORG_TERMS.search(t)): return "central",["national_or_central_source"]
    if CENTRAL_LINKED_TERMS.search(t) and (h.endswith((".ac.in",".edu.in",".gov.in",".nic.in"))): return "central_linked",["central_linked_evidence"]
    # Other Indian official state sources are useful, but ownership is not strong enough
    # for verified publication.
    if state_government_excluded(job): return "state_other",["other_indian_state_government"]
    if h.endswith((".gov.in",".nic.in")): return "state_other",["indian_state_official_domain"]
    if h.endswith((".ac.in",".edu.in")): return "institutional_indian_source",["indian_institutional_domain"]
    return None,["scope_owner_not_verified"]

def hard_reject(job):
    url=job.get("url") or job.get("document_url") or ""; org=str(job.get("organization") or "")
    title=str(job.get("title") or "")
    if not url or not (is_indian_official(url,allow_trusted_psu=True) or psu_context_official(job)):
        return ["non_indian_or_untrusted_domain"]
    if GENERIC_ORG_RE.fullmatch(org.strip()): return ["generic_organization"]
    if GENERIC_TITLE_RE.fullmatch(title.strip()): return ["generic_page_title"]
    if NOISE_RE.search(title): return ["non_recruitment_notice"]
    if not title or len(title.strip())<4: return ["missing_specific_title"]
    if not RECRUITMENT_RE.search(title+" "+str(job.get("raw_text") or "")): return ["no_recruitment_signal"]
    return []

def evidence_score(job):
    fields=sum(bool(job.get(k)) for k in ("deadline","qualification","pay","application_url","document_url"))
    fields += int(job.get("vacancies") is not None)
    signal=int(bool(RECRUITMENT_RE.search(text(job))))
    specific=int(bool(job.get("title") and not GENERIC_TITLE_RE.fullmatch(str(job.get("title")).strip())))
    provenance=int(bool(job.get("official_source") or job.get("verification") or is_indian_official(job.get("url") or job.get("document_url"),True)))
    return min(100, signal*20+specific*15+provenance*20+min(fields,5)*9)

def tier_for(job,scope,score):
    has_core=score>=80
    if scope in {"central","psu","central_linked","west_bengal","assam","tripura","odisha"} and has_core:
        return "verified"
    if scope in {"state_other","institutional_indian_source","central","psu","central_linked","west_bengal","assam","tripura","odisha"} and score>=65:
        return "high_confidence"
    if scope and score>=50:
        return "verify"
    return None

def evaluate(job):
    reasons=hard_reject(job)
    if reasons: return None,reasons,None,0
    scope,scope_reasons=classify_scope(job)
    if scope is None: return None,scope_reasons,None,0
    score=evidence_score(job)
    tier=tier_for(job,scope,score)
    if tier is None: return None,["insufficient_evidence"],scope,score
    return tier,scope_reasons,scope,score

def high_precision_valid(job):
    """Backward-compatible view of the old gate: only VERIFIED records pass."""
    tier,reasons,scope,score=evaluate(job)
    return tier=="verified", reasons, scope

def filter_dataset(dataset):
    kept=[]; rejected=[]; counts={}; tier_counts={}
    for job in dataset.get("jobs",[]):
        tier,reasons,scope,score=evaluate(job)
        if tier:
            row=dict(job); q=dict(row.get("quality") or {})
            row["scope"]=scope; row["publication_tier"]=tier; row["publication_score"]=score
            q.update({"scope":scope,"publication_tier":tier,"publication_score":score,"scope_gate":"multi_stage_v2"})
            row["quality"]=q
            kept.append(row); counts[scope]=counts.get(scope,0)+1; tier_counts[tier]=tier_counts.get(tier,0)+1
        else:
            rejected.append({"id":job.get("id"),"title":job.get("title"),"organization":job.get("organization"),
                             "url":job.get("url"),"reasons":reasons,"scope":scope,"score":score})
    # Verified first, then confidence, then verification leads; within tier deadline first.
    rank={"verified":0,"high_confidence":1,"verify":2}
    kept.sort(key=lambda j:(rank.get(j.get("publication_tier"),9),j.get("deadline") or "9999-12-31",j.get("title") or ""))
    out=dict(dataset); out["jobs"]=kept
    q=dict(out.get("quality") or {})
    q.update({"scope_gate":"multi_stage_v2","published_jobs_before_gate":len(dataset.get("jobs",[])),
              "published_jobs_after_gate":len(kept),"rejected_by_scope_gate":len(rejected),
              "scope_counts":counts,"publication_tier_counts":tier_counts,
              "verified_precision_target":">=98%","gate_architecture":"hard exclusions -> provenance -> ownership -> evidence -> tier"})
    out["quality"]=q
    out["scope_policy"]={"verified_state_governments":list(ALLOWED_STATES),"all_other_indian_state_governments":"high_confidence_when_evidence_supports",
                         "central_nationwide":True,"all_psu_cpse":True,"central_linked":True,
                         "foreign_government_rejected":True,"obvious_non_recruitment_rejected":True}
    return out,{"rejected":rejected,"counts":counts,"tier_counts":tier_counts}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",default="data/jobs.json"); p.add_argument("--output",default="data/jobs.json"); p.add_argument("--rejected-output",default="data/scope_rejections.json"); a=p.parse_args()
    with open(a.input,encoding="utf-8") as f: dataset=json.load(f)
    out,report=filter_dataset(dataset)
    with open(a.output,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
    with open(a.rejected_output,"w",encoding="utf-8") as f: json.dump({"generated_at":datetime.now(timezone.utc).isoformat(),"rejected_count":len(report["rejected"]),"scope_counts":report["counts"],"tier_counts":report["tier_counts"],"rejected":report["rejected"][:2000]},f,ensure_ascii=False,indent=2)
    print(f"Multi-stage gate: {len(out['jobs'])} published; tiers={report['tier_counts']}; rejected={len(report['rejected'])}")

if __name__=="__main__": main()

from scope_filter import classify_scope, high_precision_valid, is_indian_official, evaluate

def job(**kw):
    base={"title":"Scientist B Recruitment","organization":"DRDO, Government of India","url":"https://drdo.gov.in/recruitment/notice.pdf",
    "application_url":"https://drdo.gov.in/recruitment/notice.pdf","document_url":"https://drdo.gov.in/recruitment/notice.pdf","deadline":"2099-10-30",
    "raw_text":"Advertisement for recruitment to Scientist B. Last date 30/10/2099. Qualification B.Tech.","quality":{"valid":True}}
    base.update(kw); return base

def test_foreign_domain_rejected(): assert not is_indian_official("https://www.usajobs.gov/job/1")
def test_goa_state_job_is_recoverable_as_high_confidence():
    tier,reasons,scope,score=evaluate(job(title="Recruitment of Clerk",organization="Government of Goa",url="https://www.goa.gov.in/recruitment/clerk.pdf",document_url="https://www.goa.gov.in/recruitment/clerk.pdf",raw_text="Government of Goa recruitment for Clerk. Last date 30/10/2099. Qualification degree."))
    assert tier=="high_confidence", (tier,reasons,scope,score)
def test_west_bengal_verified():
    tier,reasons,scope,score=evaluate(job(title="Assistant Engineer Recruitment",organization="West Bengal Public Service Commission",url="https://psc.wb.gov.in/recruitment/notice.pdf",document_url="https://psc.wb.gov.in/recruitment/notice.pdf",raw_text="West Bengal Public Service Commission recruitment. Last date 30/10/2099. Qualification B.E."))
    assert tier=="verified",(tier,reasons,scope,score)
def test_psu_verified():
    tier,reasons,scope,score=evaluate(job(title="Executive Trainee Recruitment",organization="NTPC Limited",url="https://careers.ntpc.co.in/recruitment/notice.pdf",document_url="https://careers.ntpc.co.in/recruitment/notice.pdf",raw_text="NTPC Limited public sector enterprise recruitment. Last date 30/10/2099. Qualification B.Tech."))
    assert tier=="verified",(tier,reasons,scope,score)
def test_foreign_gov_not_central():
    tier,_,_,_=evaluate(job(title="Recruitment Specialist",organization="US Office of Personnel Management",url="https://www.opm.gov/recruitment/notice.pdf",document_url="https://www.opm.gov/recruitment/notice.pdf",raw_text="Government recruitment. Last date 30/10/2099. Qualification degree."))
    assert tier is None
def test_employment_news_landing_record_is_rejected():
    tier,reasons,_,_=evaluate(job(title="Employment News",organization="Employment News",url="https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",application_url="https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",deadline="2099-10-30",pay="Rs.530",raw_text="Employment News All JOBS recruitment vacancy"))
    assert tier is None and ("generic_organization" in reasons or "generic_page_title" in reasons)

def test_iitd_generic_lead_recovers_institution():
    tier,reasons,scope,score=evaluate(job(title="Advertisement for the post of Director, IIT Delhi",organization="Verified news lead",url="https://home.iitd.ac.in/jobs-iitd/uploads/Advertisement.pdf",document_url="https://home.iitd.ac.in/jobs-iitd/uploads/Advertisement.pdf",raw_text="IIT Delhi recruitment advertisement for the post of Director."))
    assert tier=="verified",(tier,reasons,scope,score)
    assert scope=="central_linked"

def test_hmt_trusted_domain_recovers_psu():
    tier,reasons,scope,score=evaluate(job(title="Engagement of Young Professionals",organization="Verified news lead",url="https://www.hmtindia.com/wp-content/uploads/2026/09/YP-Engagement-Notifictaion-2026.pdf",document_url="https://www.hmtindia.com/wp-content/uploads/2026/09/YP-Engagement-Notifictaion-2026.pdf",raw_text="HMT Limited engagement of Young Professionals recruitment."))
    assert tier=="verified",(tier,reasons,scope,score)
    assert scope=="psu"

def test_nsic_historical_archive_rejected():
    tier,reasons,scope,score=evaluate(job(title="2026522202851",organization="Verified news lead",url="https://www.nsic.co.in/documents/PDFs/Careers/2026522202851.pdf",document_url="https://www.nsic.co.in/documents/PDFs/Careers/2026522202851.pdf",raw_text="National Small Industries Corporation recruitment for Young Professionals. Last date 08.06.2026."))
    assert tier is None
    assert "historical_recruitment" in reasons

from scope_filter import classify_scope, high_precision_valid, is_indian_official

def job(**kw):
    base={
      "title":"Scientist B Recruitment",
      "organization":"DRDO, Government of India",
      "url":"https://drdo.gov.in/recruitment/notice.pdf",
      "application_url":"https://drdo.gov.in/recruitment/notice.pdf",
      "document_url":"https://drdo.gov.in/recruitment/notice.pdf",
      "deadline":"2099-10-30",
      "raw_text":"Advertisement for recruitment to Scientist B. Last date 30/10/2099. Qualification B.Tech.",
      "quality":{"valid":True}
    }
    base.update(kw)
    return base

def test_foreign_domain_rejected():
    assert not is_indian_official("https://www.usajobs.gov/job/1")

def test_goa_state_job_rejected():
    ok, reasons, scope=high_precision_valid(job(
      title="Recruitment of Clerk",
      organization="Government of Goa",
      url="https://www.goa.gov.in/recruitment/clerk.pdf",
      document_url="https://www.goa.gov.in/recruitment/clerk.pdf",
      raw_text="Government of Goa recruitment for Clerk. Last date 30/10/2099."
    ))
    assert not ok
    assert "excluded_state_government" in reasons

def test_west_bengal_allowed():
    ok, reasons, scope=high_precision_valid(job(
      title="Assistant Engineer Recruitment",
      organization="West Bengal Public Service Commission",
      url="https://psc.wb.gov.in/recruitment/notice.pdf",
      document_url="https://psc.wb.gov.in/recruitment/notice.pdf",
      raw_text="West Bengal Public Service Commission recruitment. Last date 30/10/2099. Qualification B.E."
    ))
    assert ok, reasons
    assert scope=="west_bengal"

def test_psu_allowed():
    ok, reasons, scope=high_precision_valid(job(
      title="Executive Trainee Recruitment",
      organization="NTPC Limited",
      url="https://careers.ntpc.co.in/recruitment/notice.pdf",
      document_url="https://careers.ntpc.co.in/recruitment/notice.pdf",
      raw_text="NTPC Limited public sector enterprise recruitment. Last date 30/10/2099. Qualification B.Tech."
    ))
    assert ok, reasons
    assert scope=="psu"

def test_foreign_gov_not_central():
    ok, reasons, scope=high_precision_valid(job(
      title="Recruitment Specialist",
      organization="US Office of Personnel Management",
      url="https://www.opm.gov/recruitment/notice.pdf",
      document_url="https://www.opm.gov/recruitment/notice.pdf",
      raw_text="Government recruitment. Last date 30/10/2099. Qualification degree."
    ))
    assert not ok


def test_employment_news_landing_record_is_rejected():
    ok, reasons, scope = high_precision_valid(job(
        title="Employment News",
        organization="Employment News",
        url="https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",
        application_url="https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",
        deadline="2099-10-30",
        pay="Rs.530",
        raw_text="Employment News All JOBS recruitment vacancy"
    ))
    assert not ok
    assert "generic_organization" in reasons or "generic_page_title" in reasons

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "crawler"))

from quality import validate_record, merge_jobs
from govjob_crawler import extract_table_records, html_text

def test_generic_ncs_page_is_rejected():
    job = {
        "title": "NcsNewWebsite",
        "organization": "National Career Service",
        "url": "https://ncs.gov.in/latest-update",
        "official_source": True,
        "application_url": "https://ncs.gov.in/latest-update",
    }
    ok, reasons = validate_record(job)
    assert not ok
    assert "generic_page_title" in reasons

def test_concrete_recruitment_record_is_accepted():
    job = {
        "title": "Executive Director",
        "organization": "National Board of Examinations in Medical Sciences",
        "url": "https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",
        "official_source": True,
        "application_url": "https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",
        "deadline": "2026-10-30",
        "raw_text": "Recruitment Executive Director Last Date 30/10/2026",
    }
    ok, reasons = validate_record(job)
    assert ok, reasons

def test_employment_news_table_maps_columns_correctly():
    html = """
    <table>
      <tr><th>Issued Date</th><th>Organisation</th><th>Post</th><th>Method of Appointment</th><th>Last Date</th></tr>
      <tr><td>31/08/2026</td><td>Example Government Institute</td><td>Scientist B</td><td>Recruitment</td><td>30/10/2026</td></tr>
    </table>
    """
    _, soup = html_text(html.encode())
    records = extract_table_records("Employment News", "https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All", soup, "2026-10-01T00:00:00+00:00")
    assert len(records) == 1
    assert records[0]["organization"] == "Example Government Institute"
    assert records[0]["title"] == "Scientist B"
    assert records[0]["deadline"] == "2026-10-30"

def test_merge_keeps_richer_duplicate():
    base = {
        "title": "Scientist B", "organization": "Example Institute",
        "url": "https://example.gov.in/recruitment", "official_source": True,
        "application_url": "https://example.gov.in/recruitment",
        "deadline": "2026-10-30", "raw_text": "Recruitment Scientist B",
    }
    richer = dict(base, vacancies=12, qualification="B.Tech in relevant discipline")
    merged = merge_jobs([base, richer])
    assert len(merged) == 1
    assert merged[0]["vacancies"] == 12
    assert merged[0]["qualification"] == "B.Tech in relevant discipline"
def test_empty_table_header_does_not_crash():
    html = """
    <table>
      <tr><th></th><th>Organisation</th><th>Post</th><th>Last Date</th></tr>
      <tr><td></td><td>Example Government Institute</td><td>Clerk</td><td>30/10/2026</td></tr>
    </table>
    """
    _, soup = html_text(html.encode())
    records = extract_table_records(
        "Employment News",
        "https://employmentnews.gov.in/newemp/AllJobs.aspx?k=All",
        soup,
        "2026-10-01T00:00:00+00:00",
    )
    assert len(records) == 1

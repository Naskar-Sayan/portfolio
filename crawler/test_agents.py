from agents import clean_url, parse_date, primary


def test_primary_domains():
    assert primary("https://example.gov.in/recruitment")
    assert primary("https://university.ac.in/careers")
    assert not primary("https://example.com/jobs")


def test_dates():
    assert parse_date("01/10/2026") == "2026-10-01"
    assert parse_date("2026-10-01") == "2026-10-01"


def test_clean_url():
    assert clean_url("https://example.gov.in/a#section") == "https://example.gov.in/a"

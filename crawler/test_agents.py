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


def test_exact_ten_agent_partition():
    from agents import AGENT_QUERIES, STATES
    expected = {
        "PSURegistryAgent": 3,
        "PSUCareerAgent": 3,
        "PSUNoticeAgent": 3,
        "CentralGovAgent": 3,
        "CentralExamAgent": 4,
        "WestBengalStateAgent": 4,
        "WestBengalInstitutionsAgent": 4,
        "CentralLinkedInstitutionAgent": 4,
        "CentralLinkedBodyAgent": 4,
        "RegionalStateAgent": 3,
    }
    assert set(AGENT_QUERIES) == set(expected)
    assert {k: len(v) for k, v in AGENT_QUERIES.items()} == expected
    assert STATES == ["West Bengal", "Assam", "Tripura", "Odisha"]
    assert len(AGENT_QUERIES) == 10

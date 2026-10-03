from psu_registry import parse_names

def test_dpe_appendix_numbered_rows():
    text = """
    Appendix - II
    Operating Central Public Sector Enterprises
    18 Bharat Electronics Ltd.
    19 Garden Reach Shipbuilders & Engineers Ltd.
    20 Gliders India Limited
    21 Goa Shipyard Ltd.
    291 Visakhapatanam Port Logistics Park Ltd.
    NR- Not Running / Under Closure
    """
    names = parse_names(text)
    assert names == [
        "Bharat Electronics Ltd.",
        "Garden Reach Shipbuilders & Engineers Ltd.",
        "Gliders India Limited",
        "Goa Shipyard Ltd.",
        "Visakhapatanam Port Logistics Park Ltd.",
    ]

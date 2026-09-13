import pytest

from app.services.discovery.eligibility import EU_COUNTRIES, eligible_countries_from_text


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"candidate_required_location": "USA Only"}, ["US"]),
        ({"candidate_required_location": "Worldwide"}, None),
        ({"location_restrictions": ["United Kingdom", "Ireland"]}, ["GB", "IE"]),
        ({"location_restrictions": ["Nigeria"]}, ["NG"]),
        ({"region_text": "Anywhere in the World"}, None),
        ({"region_text": "Canada Only"}, ["CA"]),
        ({"description": "This role is US-only due to payroll."}, ["US"]),
        ({"description": "Must be located in the EU."}, sorted(EU_COUNTRIES)),
        ({"description": "You must be based in Europe."}, sorted(
            ("AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
             "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
             "GB", "CH", "NO", "IS", "UA", "RS", "TR"))),
        ({"description": "We hire across EMEA."}, None),
        ({"candidate_required_location": "EMEA"}, None),
        ({}, None),
    ],
)
def test_eligible_countries_from_text(kwargs, expected):
    assert eligible_countries_from_text(**kwargs) == expected


def test_eu_restriction_expands_to_member_states():
    result = eligible_countries_from_text(region_text="EU only")
    assert result == sorted(EU_COUNTRIES)
    assert "GB" not in result


def test_worldwide_wins_over_a_country_mention():
    assert eligible_countries_from_text(candidate_required_location="Worldwide, including USA") is None

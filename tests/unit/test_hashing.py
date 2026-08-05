from opportunity_radar.utilities.hashing import (
    content_hash,
    fuzzy_key_hash,
    identity_hash,
    url_hash,
)


def test_identity_hash_stable_and_distinct():
    a = identity_hash("greenhouse", "stripe", "123")
    assert a == identity_hash("greenhouse", "stripe", "123")
    assert a != identity_hash("greenhouse", "stripe", "124")
    assert a != identity_hash("lever", "stripe", "123")


def test_url_hash_ignores_tracking():
    a = url_hash("https://jobs.lever.co/x/1?lever-source=twitter")
    b = url_hash("https://jobs.lever.co/x/1")
    assert a == b


def test_fuzzy_key_ignores_location_order_and_case():
    a = fuzzy_key_hash("stripe", "Software Engineer Intern", ["NYC", "SF"])
    b = fuzzy_key_hash("stripe", "software engineer intern", ["sf", "nyc"])
    assert a == b


def test_content_hash_ignores_whitespace_and_html_noise():
    a = content_hash("SWE Intern", "Build   things.\n\nApply now!", ["Remote"])
    b = content_hash("SWE Intern", "Build things. Apply now!", ["Remote"])
    assert a == b


def test_content_hash_detects_real_change():
    a = content_hash("SWE Intern", "Summer 2027 program", ["Remote"])
    b = content_hash("SWE Intern", "Spring 2027 program", ["Remote"])
    assert a != b

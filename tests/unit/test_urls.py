from opportunity_radar.utilities.urls import absolutize, canonicalize_url, domain_of


def test_canonicalize_strips_tracking_params():
    url = "https://boards.greenhouse.io/stripe/jobs/123?utm_source=x&gh_src=abc&gh_jid=123"
    result = canonicalize_url(url)
    assert "utm_source" not in result
    assert "gh_src" not in result
    assert "gh_jid=123" in result


def test_canonicalize_normalizes_host_and_trailing_slash():
    assert canonicalize_url("HTTPS://WWW.Example.com/jobs/") == "https://example.com/jobs"
    assert canonicalize_url("https://example.com:443/jobs") == "https://example.com/jobs"


def test_canonicalize_sorts_query():
    a = canonicalize_url("https://example.com/j?b=2&a=1")
    b = canonicalize_url("https://example.com/j?a=1&b=2")
    assert a == b


def test_absolutize():
    assert absolutize("https://example.com/careers/", "/jobs/1") == "https://example.com/jobs/1"
    assert absolutize("https://example.com/careers/", "jobs/1") == (
        "https://example.com/careers/jobs/1"
    )
    assert absolutize("https://example.com/x", "https://other.com/y") == "https://other.com/y"


def test_domain_of():
    assert domain_of("https://www.Example.com:8443/x") == "example.com"

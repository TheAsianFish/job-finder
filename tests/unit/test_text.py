from opportunity_radar.utilities.text import (
    html_to_text,
    normalize_for_comparison,
    normalize_title,
    truncate,
)


def test_html_to_text_strips_tags_and_scripts():
    html = "<div><script>evil()</script><h1>SWE Intern</h1><p>Build &amp; ship</p></div>"
    text = html_to_text(html)
    assert "evil" not in text
    assert "SWE Intern" in text
    assert "Build & ship" in text


def test_html_to_text_plain_passthrough():
    assert html_to_text("plain text &amp; more") == "plain text & more"
    assert html_to_text(None) == ""


def test_normalize_title_collapses_separators():
    assert normalize_title("SWE Intern — Summer  2027") == "SWE Intern - Summer 2027"


def test_normalize_for_comparison():
    assert normalize_for_comparison("Café-Engineer!") == "cafe engineer"


def test_truncate():
    assert truncate("abcdef", 5) == "abcd…"
    assert truncate("abc", 5) == "abc"

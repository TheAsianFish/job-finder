import respx
from httpx import Response

from opportunity_radar.adapters.sitemap import SitemapAdapter, filter_job_urls, parse_sitemap
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture


def test_parse_sitemap_index():
    pages, children = parse_sitemap(load_fixture("sitemap_index.xml"))
    assert pages == []
    assert len(children) == 2


def test_parse_urlset():
    pages, children = parse_sitemap(load_fixture("sitemap_careers.xml"))
    assert len(pages) == 3
    assert children == []


def test_filter_job_urls():
    urls = [
        "https://example.com/careers/x",
        "https://example.com/blog/post",
        "https://example.com/jobs/y",
        "https://example.com/open-positions/z",
    ]
    filtered = filter_job_urls(urls)
    assert "https://example.com/blog/post" not in filtered
    assert len(filtered) == 3


@respx.mock
async def test_sitemap_end_to_end(ctx):
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://example.com/sitemap.xml").mock(
        return_value=Response(200, text=load_fixture("sitemap_index.xml"))
    )
    respx.get("https://example.com/sitemap-careers.xml").mock(
        return_value=Response(200, text=load_fixture("sitemap_careers.xml"))
    )
    respx.get("https://example.com/sitemap-blog.xml").mock(
        return_value=Response(
            200, text="<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'/>"
        )
    )
    respx.get("https://example.com/careers/ex-2027-001").mock(
        return_value=Response(200, text=load_fixture("jsonld_single.html"))
    )
    respx.get("https://example.com/jobs/platform-intern").mock(
        return_value=Response(200, text="<html><body>No structured data</body></html>")
    )
    company = CompanySource(
        id="exampleco",
        name="ExampleCo",
        domain="example.com",
        adapter="sitemap",
    )
    jobs = await SitemapAdapter().fetch_jobs(company, ctx)
    assert len(jobs) == 1
    assert jobs[0].source_adapter == "sitemap"
    assert jobs[0].title.startswith("Software Engineer Intern")

"""Workday adapter (spec §8.8: company-specific stable JSON, with tests).

Workday career sites all serve the same read-only JSON used by the site's own
job-list page:

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs
         {"appliedFacets": {...}, "limit": 20, "offset": 0, "searchText": ""}
    GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}

It is not a documented public API, so this adapter stays narrow and
defensive: it pulls only early-career postings, caps every loop, and fails
loudly (never with an empty list) when the response shape changes. Boards
run to thousands of postings and the list omits descriptions, so a posting
costs one detail GET — paced by the shared per-domain limiter.

Selection strategy, in order:
1. Facet-driven: the first list response advertises facets such as
   `workerSubType = Intern (Fixed Term) / New College Graduate` or
   `jobFamilyGroup = Univ Employment`. Their ids are tenant-specific but
   discoverable, so the adapter applies every early-career-looking facet
   value and pages through exactly that subset (deterministic, complete).
2. Search fallback: when a tenant exposes no such facet, run a few
   `searchText` queries ("intern", "new grad", ...) and keep titles that
   pass the shared early-career rules.

adapter_config:
  host: nvidia.wd5.myworkdayjobs.com   (required unless derivable from career_urls)
  tenant: nvidia                        (defaults to the host's first label)
  site: NVIDIAExternalCareerSite        (required)
  search_texts: [intern, new grad, ...] (fallback queries)
  max_pages: 10                         (per query / facet pass, 20 per page)
  detail_limit: 200                     (max detail GETs per scan)
  early_career_only: true
"""

from __future__ import annotations

import re
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.filters import (
    config_int,
    config_list,
    early_career_only,
    looks_early_career,
)
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

PAGE_SIZE = 20  # Workday rejects larger limits.
DEFAULT_SEARCH_TEXTS = ["intern", "internship", "new grad", "new college graduate", "university"]
_EARLY_FACET_RE = re.compile(
    r"intern|new (?:college )?grad|\buniv|student|early[\s\-]?career|campus|graduate program",
    re.IGNORECASE,
)
_LOCATION_FACETS = {
    "locations",
    "locationMainGroup",
    "locationCountry",
    "locationRegionStateProvince",
}
_HOST_RE = re.compile(
    r"https?://([\w-]+\.wd\d+\.myworkdayjobs\.com)(?:/[a-z]{2}-[A-Z]{2})?/([\w-]+)",
)


def extract_workday_config(company: CompanySource) -> dict[str, str] | None:
    """Resolve host/tenant/site from adapter_config or a Workday career URL."""
    cfg = company.adapter_config
    host = cfg.get("host")
    site = cfg.get("site")
    tenant = cfg.get("tenant")
    if not (host and site):
        for url in company.career_urls:
            match = _HOST_RE.search(url)
            if match:
                host = host or match.group(1)
                site = site or match.group(2)
                break
    if not host or not site:
        return None
    host = str(host).replace("https://", "").strip("/")
    tenant = str(tenant or host.split(".")[0])
    return {"host": host, "tenant": tenant, "site": str(site)}


class WorkdayAdapter(BaseAdapter):
    name = "workday"

    @staticmethod
    def list_url(cfg: dict[str, str]) -> str:
        return f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"

    @staticmethod
    def detail_url(cfg: dict[str, str], external_path: str) -> str:
        return f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}{external_path}"

    @staticmethod
    def public_url(cfg: dict[str, str], external_path: str) -> str:
        return f"https://{cfg['host']}/{cfg['site']}{external_path}"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        cfg = extract_workday_config(company)
        if cfg is None:
            raise AdapterError(
                f"no Workday host/site configured for {company.id} "
                "(adapter_config: host, site[, tenant] or a myworkdayjobs.com career_url)",
                category="config",
            )
        source = f"Workday '{cfg['tenant']}/{cfg['site']}'"
        await self.require_robots_allowed(ctx, self.list_url(cfg), source)
        max_pages = config_int(company, "max_pages", 10)
        filter_titles = early_career_only(company)

        first = await self._list_page(ctx, cfg, source, facets={}, search_text="", offset=0)
        total = int(first.get("total") or 0)
        postings: dict[str, dict[str, Any]] = {}

        facet_filter = self._early_career_facets(first.get("facets") or []) if filter_titles else {}
        if facet_filter:
            # Deterministic subset: page through the early-career facet values
            # only. Workday ORs values within one facet parameter but ANDs
            # across parameters, so each parameter gets its own pass and the
            # results are unioned (Intern sub-type plus "Univ Employment" family).
            # Facet passes get a larger page budget than search passes because
            # they are exact, not ranked.
            for parameter, ids in facet_filter.items():
                offset = 0
                pass_total = 0
                for _ in range(max(max_pages, 1) * 5):
                    data = await self._list_page(
                        ctx, cfg, source, facets={parameter: ids}, search_text="", offset=offset
                    )
                    items = data.get("jobPostings") or []
                    for item in items:
                        self._collect(postings, item)
                    # Workday reports `total` on the first page only; later
                    # pages answer 0, so the first value governs the loop.
                    if offset == 0:
                        pass_total = int(data.get("total") or 0)
                    offset += PAGE_SIZE
                    if not items or offset >= pass_total:
                        break
        else:
            queries = config_list(company, "search_texts", DEFAULT_SEARCH_TEXTS)
            if not filter_titles:
                queries = [""]
            for query in queries:
                offset = 0
                pass_total = total
                for _ in range(max(max_pages, 1)):
                    data = (
                        first
                        if query == "" and offset == 0
                        else await self._list_page(
                            ctx, cfg, source, facets={}, search_text=query, offset=offset
                        )
                    )
                    items = data.get("jobPostings") or []
                    for item in items:
                        if not filter_titles or looks_early_career(str(item.get("title") or "")):
                            self._collect(postings, item)
                    if offset == 0:
                        pass_total = int(data.get("total") or 0)
                    offset += PAGE_SIZE
                    if not items or offset >= pass_total:
                        break

        detail_limit = config_int(company, "detail_limit", 200)
        jobs: list[RawJob] = []
        fetched = 0
        for external_path, item in postings.items():
            detail: dict[str, Any] = {}
            if self._listing_id(item, external_path) not in ctx.known_job_ids and (
                fetched < detail_limit
            ):
                detail = await self._detail(ctx, cfg, source, external_path)
                fetched += 1
            jobs.append(self._to_raw(cfg, item, detail))
        return jobs

    @staticmethod
    def _listing_id(item: dict[str, Any], external_path: str) -> str:
        bullets = [str(b) for b in item.get("bulletFields") or [] if b]
        return bullets[0] if bullets else external_path

    async def _list_page(
        self,
        ctx: AdapterContext,
        cfg: dict[str, str],
        source: str,
        *,
        facets: dict[str, list[str]],
        search_text: str,
        offset: int,
    ) -> dict[str, Any]:
        payload = {
            "appliedFacets": facets,
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": search_text,
        }
        response = await ctx.post_json(
            self.list_url(cfg), payload, headers={"Accept": "application/json"}
        )
        if response.status_code in (404, 422):
            raise AdapterError(
                f"{source} returned HTTP {response.status_code} — tenant/site is likely wrong",
                category="config",
                http_status=response.status_code,
            )
        self.require_status_ok(response, source)
        data = self.parse_json(response, source)
        if not isinstance(data, dict) or "jobPostings" not in data:
            raise AdapterError(f"{source} response missing 'jobPostings'", category="parse")
        return data

    async def _detail(
        self, ctx: AdapterContext, cfg: dict[str, str], source: str, external_path: str
    ) -> dict[str, Any]:
        response = await ctx.get(
            self.detail_url(cfg, external_path), headers={"Accept": "application/json"}
        )
        if response.status_code >= 400:
            # A posting can close between list and detail; the list data is
            # still a valid (description-less) record — keep going.
            return {}
        data = self.parse_json(response, source)
        info = data.get("jobPostingInfo") if isinstance(data, dict) else None
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _early_career_facets(facets: list[dict[str, Any]]) -> dict[str, list[str]]:
        selected: dict[str, list[str]] = {}
        for facet in facets:
            parameter = str(facet.get("facetParameter") or "")
            if not parameter or parameter in _LOCATION_FACETS:
                continue
            ids = [
                str(value["id"])
                for value in facet.get("values") or []
                if isinstance(value, dict)
                and value.get("id")
                and _EARLY_FACET_RE.search(str(value.get("descriptor") or ""))
            ]
            if ids:
                selected[parameter] = ids
        return selected

    @staticmethod
    def _collect(postings: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
        external_path = str(item.get("externalPath") or "")
        if external_path and external_path not in postings:
            postings[external_path] = item

    def _to_raw(self, cfg: dict[str, str], item: dict[str, Any], detail: dict[str, Any]) -> RawJob:
        external_path = str(item.get("externalPath") or "")
        req_id = str(detail.get("jobReqId") or self._listing_id(item, external_path))
        locations: list[str] = []
        for candidate in (detail.get("location"), item.get("locationsText")):
            if candidate and str(candidate) not in locations:
                locations.append(str(candidate))
        for extra in detail.get("additionalLocations") or []:
            if extra and str(extra) not in locations:
                locations.append(str(extra))
        url = str(detail.get("externalUrl") or self.public_url(cfg, external_path))
        remote_hint = None
        remote_type = str(detail.get("remoteType") or item.get("remoteType") or "").lower()
        if "remote" in remote_type:
            remote_hint = "remote"
        elif "hybrid" in remote_type:
            remote_hint = "hybrid"
        return RawJob(
            source_adapter=self.name,
            source_job_id=req_id,
            title=str(detail.get("title") or item.get("title") or "").strip(),
            url=url,
            apply_url=url,
            locations=locations,
            employment_type=str(detail.get("timeType") or "") or None,
            description_html=detail.get("jobDescription") or None,
            # `startDate` on a Workday posting is the posting's publish date.
            posted_at=parse_datetime(detail.get("startDate")),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            raw={
                "tenant": cfg["tenant"],
                "site": cfg["site"],
                "external_path": external_path,
                "posted_on": item.get("postedOn"),
                "detail_fetched": bool(detail),
            },
        )

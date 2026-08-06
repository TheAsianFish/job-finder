"""Self-repair for failing sources.

When a company's source keeps failing (stale board token, ATS migration),
re-run ATS discovery against its domain and, if a concrete adapter+token is
found AND validates with real jobs, update config/companies.yaml in place.
Sources that cannot be repaired are reported, never silently disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
import yaml

from opportunity_radar.adapters.base import AdapterContext
from opportunity_radar.config import config_dir, get_settings, load_settings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.discovery.career_links import discover
from opportunity_radar.discovery.source_validator import validate_company

logger = structlog.get_logger(__name__)

_ADAPTER_CONFIG_KEYS = {
    "greenhouse": "board_token",
    "lever": "site",
    "ashby": "job_board_name",
}


@dataclass
class RepairResult:
    repaired: list[str] = field(default_factory=list)
    unrepairable: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


async def repair_failing_sources(
    ctx: AdapterContext,
    min_failures: int = 3,
    db_url: str | None = None,
) -> RepairResult:
    result = RepairResult()
    settings = get_settings()
    companies_by_id = {c.id: c for c in settings.companies}

    with session_scope(db_url) as session:
        failing_ids = [
            state.company_id
            for state in repo.list_source_states(session)
            if state.consecutive_failures >= min_failures
            and state.company_id in companies_by_id
            and companies_by_id[state.company_id].enabled
        ]

    if not failing_ids:
        return result

    for company_id in failing_ids:
        company = companies_by_id[company_id]
        if not company.domain:
            result.unrepairable.append(company_id)
            result.details.append(f"{company_id}: no domain configured, cannot rediscover")
            continue
        try:
            found = await discover(company.domain, ctx)
        except Exception as exc:
            result.unrepairable.append(company_id)
            result.details.append(f"{company_id}: discovery failed ({exc})")
            continue

        fingerprint = found.fingerprint
        config_key = _ADAPTER_CONFIG_KEYS.get(fingerprint.adapter) if fingerprint else None
        if not fingerprint or not config_key or config_key not in fingerprint.config:
            result.unrepairable.append(company_id)
            result.details.append(
                f"{company_id}: no usable ATS fingerprint found — needs manual adapter work"
            )
            continue

        # Trial-run the candidate before touching config.
        candidate = company.model_copy(deep=True)
        candidate.adapter = fingerprint.adapter
        candidate.adapter_config = dict(fingerprint.config)
        validation = await validate_company(candidate, ctx)
        if not validation.ok or not validation.job_count:
            result.unrepairable.append(company_id)
            result.details.append(
                f"{company_id}: candidate {fingerprint.adapter} config did not validate "
                f"({validation.detail})"
            )
            continue

        _patch_registry(company_id, fingerprint.adapter, dict(fingerprint.config))
        result.repaired.append(company_id)
        result.details.append(
            f"{company_id}: repointed to {fingerprint.adapter} "
            f"({fingerprint.config}) — {validation.job_count} jobs"
        )
        logger.info(
            "source_repaired",
            company_id=company_id,
            adapter=fingerprint.adapter,
            jobs=validation.job_count,
        )

    if result.repaired:
        load_settings(reload=True)
    return result


def _patch_registry(company_id: str, adapter: str, adapter_config: dict) -> None:
    path = config_dir() / "companies.yaml"
    if not path.exists():
        logger.warning("repair_no_registry_file", path=str(path))
        return
    content = path.read_text(encoding="utf-8")
    header_lines: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    header = "".join(header_lines)
    data = yaml.safe_load(content) or {}
    for entry in data.get("companies", []):
        if entry.get("id") == company_id:
            entry["adapter"] = adapter
            entry["adapter_config"] = adapter_config
    path.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

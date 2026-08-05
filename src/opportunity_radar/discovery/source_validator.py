"""Company source validation for `opportunity-radar companies validate`."""

from __future__ import annotations

from opportunity_radar.adapters.base import AdapterContext, AdapterError
from opportunity_radar.adapters.registry import resolve_adapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.scan import ValidationResult


async def validate_company(company: CompanySource, ctx: AdapterContext) -> ValidationResult:
    try:
        adapter = resolve_adapter(company)
    except AdapterError as exc:
        return ValidationResult(ok=False, adapter="unresolved", detail=str(exc))
    return await adapter.validate(company, ctx)

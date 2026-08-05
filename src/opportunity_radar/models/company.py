"""Company registry entry model."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CompanySource(BaseModel):
    """One target company as configured in companies.yaml."""

    id: str
    name: str
    domain: str | None = None
    tier: Literal["core", "strong", "broad", "exploratory"] = "broad"
    enabled: bool = True
    adapter: str = "auto"
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    career_urls: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    scan_interval_minutes: int | None = None
    notes: str | None = None

    @field_validator("id")
    @classmethod
    def _slug_id(cls, value: str) -> str:
        slug = value.strip().lower().replace(" ", "-")
        if not slug:
            raise ValueError("company id must not be empty")
        return slug

    def interval_minutes(self, tier_defaults: dict[str, int]) -> int:
        if self.scan_interval_minutes is not None:
            return self.scan_interval_minutes
        return tier_defaults.get(self.tier, 60)

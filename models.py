"""Structured output for the vendor desk agent (one result per vendor document)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VendorDecision(BaseModel):
    vendor: str | None = Field(description="Vendor company name as written in the document, or null if not stated.")
    sku: str | None = Field(description="Campus Customs SKU the quote is for (e.g. CC-HD-006), or null if not stated.")
    unit_price: float | None = Field(description="Quoted price per unit in USD, or null if not stated.")
    lead_time_days: int | None = Field(description="Quoted lead time in days, or null if not stated.")
    min_order: int | None = Field(description="Minimum order quantity in units, or null if not stated.")
    decision: Literal["recommend", "do_not_recommend"] = Field(
        description="recommend only if all four handbook purchasing checks pass, otherwise do_not_recommend."
    )
    reason: str = Field(description="One sentence naming the purchasing check that decided the outcome.")

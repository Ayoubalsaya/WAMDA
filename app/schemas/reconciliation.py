"""مخطّطات المطابقة (§٧-٩) — دفترك مقابل كشف المراسل."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class CreateStatementLineRequest(BaseModel):
    value_date: date
    description: Optional[str] = None
    amount: Decimal


class CreatePartnerStatementRequest(BaseModel):
    partner_id: int
    period_from: date
    period_to: date
    lines: list[CreateStatementLineRequest] = Field(min_length=1)


class StatementLineOut(BaseModel):
    id: int
    value_date: date
    description: Optional[str] = None
    amount: Decimal
    status: str  # OPEN · RESOLVED
    matched_entry_id: Optional[int] = None
    matched_entry_no: Optional[str] = None


class PartnerStatementSummary(BaseModel):
    id: int
    partner_id: int
    partner_name_ar: str
    period_from: date
    period_to: date
    imported_at: datetime
    total_lines: int
    open_lines: int


class PartnerStatementDetail(BaseModel):
    id: int
    partner_id: int
    partner_name_ar: str
    period_from: date
    period_to: date
    imported_at: datetime
    lines: list[StatementLineOut]


class AutoMatchResponse(BaseModel):
    matched_count: int
    statement: PartnerStatementDetail


class ManualMatchRequest(BaseModel):
    entry_id: int


class ResolveLineRequest(BaseModel):
    """تسوية يدوية بلا قيد مطابق — الفرق سُوِّي خارجياً (مثلاً بـADJUSTMENT
    مُرحَّل من دفتر اليومية مباشرة، مُشار إليه هنا بمعرّف القيد بعد ترحيله)."""

    matched_entry_id: Optional[int] = None

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


class YourLedgerEntryOut(BaseModel):
    """جانب "دفترك" في العرض جنباً إلى جنب — قيد يمسّ حساب هذا المراسل."""
    entry_id: int
    entry_no: str
    entry_date: date
    operation_type: str
    description: Optional[str] = None
    amount: Decimal  # صافي الأثر على حسابات المراسل (دائن − مدين)
    matched_line_id: Optional[int] = None  # None = سجّلتها ولم ينفّذوها (أخطر)


class PartnerStatementDetail(BaseModel):
    id: int
    partner_id: int
    partner_name_ar: str
    period_from: date
    period_to: date
    imported_at: datetime
    lines: list[StatementLineOut]
    your_entries: list[YourLedgerEntryOut] = []
    unmatched_line_count: int = 0      # سطور كشفهم بلا قيد — سجّلوها ولم تسجّلها
    unmatched_entry_count: int = 0     # قيودك بلا سطر — سجّلتها ولم ينفّذوها (أخطر)


class AutoMatchResponse(BaseModel):
    matched_count: int
    statement: PartnerStatementDetail


class ManualMatchRequest(BaseModel):
    entry_id: int


class ResolveLineRequest(BaseModel):
    """تسوية يدوية بلا قيد مطابق — الفرق سُوِّي خارجياً (مثلاً بـADJUSTMENT
    مُرحَّل من دفتر اليومية مباشرة, مُشار إليه هنا بمعرّف القيد بعد ترحيله)."""

    matched_entry_id: Optional[int] = None


class AdjustLineRequest(BaseModel):
    """تسوية فرق سطر كشف بقيد ADJUSTMENT يُرحَّل هنا مباشرة ويُربَط بالسطر.
    **السبب إلزامي** (§٥-١٢: لا تسوية بلا تفسير — الفرق الذي يُسوّى بلا
    سبب يتكرر بلا معرفة مصدره)."""
    account_code: str          # حساب المراسل المتأثّر (١٣١٠.x / ١٣٢٠.x)
    currency_code: str
    amount: Decimal = Field(gt=0)
    is_debit: bool             # True = زيادة رصيد الحساب · False = نقص
    reason: str = Field(min_length=3)

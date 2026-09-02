"""مخطّطات إقفال الفترات (§٩ المرحلة ١١)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PeriodRow(BaseModel):
    year: int
    month: int
    is_closed: bool
    closed_by_username: Optional[str] = None
    closed_at: Optional[datetime] = None


class ClosePeriodRequest(BaseModel):
    year: int
    month: int


class ReopenPeriodRequest(BaseModel):
    year: int
    month: int


class FoundingPeriodStatus(BaseModel):
    is_open: bool
    closed_at: Optional[datetime] = None
    closed_by_username: Optional[str] = None
    suspense_balance_by_currency: dict[str, str]


class CloseFoundingPeriodRequest(BaseModel):
    acknowledged_remaining_suspense: bool = False

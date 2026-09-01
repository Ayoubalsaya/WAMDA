"""مخطّطات الإعدادات (§٧-١٤)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    name_ar: str = "ومضة"
    logo_data_url: Optional[str] = None


class UserListRow(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: Optional[datetime] = None


class PartnerRow(BaseModel):
    id: int
    code: str
    name_ar: str
    name_en: Optional[str] = None
    country: str
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool


class CreatePartnerRequest(BaseModel):
    code: str
    name_ar: str
    name_en: Optional[str] = None
    country: str
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class AccountOut(BaseModel):
    id: int
    code: str
    name_ar: str
    currency_code: Optional[str] = None
    location_code: Optional[str] = None
    form: Optional[str] = None
    partner_id: Optional[int] = None


class CreatePartnerAccountRequest(BaseModel):
    parent_code: str  # "1310" مراسلو ليبيا · "1320" مراسلو تركيا
    currency_code: str
    location_code: str
    name_ar: Optional[str] = None


class CreateBankAccountRequest(BaseModel):
    currency_code: str
    location_code: str
    name_ar: Optional[str] = None

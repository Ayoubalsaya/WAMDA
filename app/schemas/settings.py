"""مخطّطات الإعدادات (§٧-١٤)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CompanyProfile(BaseModel):
    name_ar: str = "ومضة"
    logo_data_url: Optional[str] = None


class CurrencyRow(BaseModel):
    code: str
    name_ar: str
    symbol: str
    decimals: int
    is_pivot: bool
    is_active: bool
    sort_order: int


class CreateCurrencyRequest(BaseModel):
    code: str = Field(min_length=1, max_length=8)
    name_ar: str
    symbol: str
    decimals: int = Field(default=2, ge=0, le=6)
    sort_order: int = 0
    # لا is_pivot هنا عمداً — عملة محورية واحدة فقط (USD)، قرار معماري
    # لا تغييره شاشة الإعدادات (ux_currencies_single_pivot + كل محرك FX
    # مبني على "الدولار إلزامي في أحد الطرفين" حرفياً).


class UpdateCurrencyRequest(BaseModel):
    """لا `code` هنا إطلاقاً — مفتاح أساسي مرجعي من كل مكان، غير قابل
    للتعديل أبداً بصرف النظر عن الاستخدام. `decimals` يُرفَض بعد أول
    استخدام حقيقي (يفحصه الراوتر) — تغييره رجعياً يُفسد تقريب قيود قديمة."""
    name_ar: Optional[str] = None
    symbol: Optional[str] = None
    decimals: Optional[int] = Field(default=None, ge=0, le=6)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class LocationRow(BaseModel):
    code: str
    name_ar: str
    country: str
    is_active: bool


class CreateLocationRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name_ar: str
    country: str


class UpdateLocationRequest(BaseModel):
    name_ar: Optional[str] = None
    country: Optional[str] = None
    is_active: Optional[bool] = None


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

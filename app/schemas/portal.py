"""مخطّطات بوابة العميل (§٧-٦) — مشاهدة فقط، بلا `cost_rate` إطلاقاً في
أي مخطّط هنا (نفس قاعدة `app/schemas/clients.py`، لا استثناء)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PortalLoginRequest(BaseModel):
    code: str
    password: str


class PortalLoginResponse(BaseModel):
    status: str  # "ok" | "locked"
    must_change_password: Optional[bool] = None


class PortalChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class PortalRecoverStartRequest(BaseModel):
    code: str


class PortalRecoverStartResponse(BaseModel):
    security_question: Optional[str] = None


class PortalRecoverCompleteRequest(BaseModel):
    code: str
    security_answer: str
    new_password: str = Field(min_length=10)


class PortalMeResponse(BaseModel):
    code: str
    name_ar: str
    must_change_password: bool


class SetPortalCredentialsRequest(BaseModel):
    """طاقم الموظفين فقط (مدير) — يُنشئ/يُعيد ضبط دخول البوابة لعميل، نفس
    نمط `CreateUserRequest` (كلمة مرور أولية يحدِّدها المدير، لا تُولَّد
    عشوائياً)."""

    initial_password: str = Field(min_length=10)
    security_question: Optional[str] = None
    security_answer: Optional[str] = None

"""مخطّطات طلبات/ردود المصادقة — §٧-١."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None
    totp_secret_setup: Optional[str] = None  # يُعاد من رد "يتطلب تسجيل 2FA" السابق


class LoginResponse(BaseModel):
    status: str  # "totp_setup_required" | "totp_required" | "ok"
    totp_secret: Optional[str] = None
    provisioning_uri: Optional[str] = None
    must_change_password: Optional[bool] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class RecoverStartRequest(BaseModel):
    username: str


class RecoverStartResponse(BaseModel):
    security_question: Optional[str] = None


class RecoverCompleteRequest(BaseModel):
    username: str
    security_answer: str
    new_password: str = Field(min_length=10)


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str  # "ADMIN" | "ACCOUNTANT"
    initial_password: str = Field(min_length=10)
    security_question: Optional[str] = None
    security_answer: Optional[str] = None


class CreateUserResponse(BaseModel):
    id: int
    username: str
    role: str


class UpdateUserRequest(BaseModel):
    """§٩ المرحلة ١٢ — تعطيل/تفعيل و/أو تغيير الدور. كلاهما اختياري؛ حقل
    غير مُمرَّر = لا تغيير له."""
    is_active: Optional[bool] = None
    role: Optional[str] = None  # "ADMIN" | "ACCOUNTANT"

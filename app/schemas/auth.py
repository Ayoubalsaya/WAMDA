"""مخطّطات طلبات/ردود المصادقة — §٧-١."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None
    totp_secret_setup: Optional[str] = None  # يُعاد من رد "يتطلب تسجيل 2FA" السابق
    backup_code: Optional[str] = None  # رمز احتياطي لمرة واحدة بدل totp_code (كلمة المرور مطلوبة دائماً)


class LoginResponse(BaseModel):
    status: str  # "totp_setup_required" | "totp_required" | "ok"
    totp_secret: Optional[str] = None
    provisioning_uri: Optional[str] = None
    must_change_password: Optional[bool] = None
    # الرموز الاحتياطية — تُعاد **مرة واحدة** فقط عند إنشائها (أول إعداد لـ2FA)؛ الواجهة تعرضها إلزامياً قبل المتابعة
    backup_codes: Optional[list[str]] = None
    backup_codes_remaining: Optional[int] = None  # بعد الدخول برمز احتياطي


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    must_change_password: bool
    # الإجراءات المسموحة لدور المستخدم (من مصفوفة الصلاحيات) — الواجهة تخفي ما لا يملكه، والخادم يفرضه دائماً
    permissions: list[str] = []


class CreateUserRequest(BaseModel):
    username: str
    full_name: str
    role: str  # "ADMIN" | "ACCOUNTANT"
    initial_password: str = Field(min_length=10)


class CreateUserResponse(BaseModel):
    id: int
    username: str
    role: str


class UpdateUserRequest(BaseModel):
    """§٩ المرحلة ١٢ — تعطيل/تفعيل و/أو تغيير الدور. كلاهما اختياري؛ حقل
    غير مُمرَّر = لا تغيير له."""
    is_active: Optional[bool] = None
    role: Optional[str] = None  # "ADMIN" | "ACCOUNTANT"


class BackupCodesStatus(BaseModel):
    remaining: int
    total: int
    low: bool  # يبقى ٣ أو أقل (بما فيها ٠)


class RegenerateBackupCodesRequest(BaseModel):
    password: str  # إعادة الإنشاء تُبطل السابقة — تتطلب كلمة المرور الحالية


class BackupCodesResponse(BaseModel):
    codes: list[str]  # تُعرض هذه المرة فقط ولا يمكن استرجاعها لاحقاً
    remaining: int

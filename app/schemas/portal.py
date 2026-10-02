"""مخطّطات بوابة العميل (§٧-٦) — مشاهدة فقط، بلا `cost_rate` إطلاقاً في
أي مخطّط هنا (نفس قاعدة `app/schemas/clients.py`، لا استثناء). يشمل أيضاً
مخطّطات **إدارة** البوابة من طاقم الموظفين (`app/routers/clients.py`) —
نفس الملف كان يحمل `SetPortalCredentialsRequest` سابقاً (محذوف الآن)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PortalLoginRequest(BaseModel):
    code: str
    password: str


class PortalLoginResponse(BaseModel):
    status: str  # "ok" | "locked"


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


class PortalInviteVerifyRequest(BaseModel):
    token: str


class PortalInviteVerifyResponse(BaseModel):
    client_first_name: str


class PortalInviteAcceptRequest(BaseModel):
    token: str
    password: str = Field(min_length=10)


class ClientPortalStatusResponse(BaseModel):
    """`status` مُشتقّة دائماً — لا تُخزَّن (قرار مالك)، راجع
    `app/security/client_portal_management.compute_status`."""

    status: str  # ClientPortalStatus
    last_login_at: Optional[datetime] = None
    invite_expires_at: Optional[datetime] = None


class ClientPortalInviteCreatedResponse(BaseModel):
    """رابط الدعوة الخام — يُعرَض **مرة واحدة فقط** في رد الإنشاء، لا يُحفَظ
    ولا يُستعاد لاحقاً (الخادم لا يملك إلا بصمته)."""

    invite_url: str
    expires_at: datetime

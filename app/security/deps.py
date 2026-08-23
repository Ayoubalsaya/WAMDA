"""تبعيات FastAPI — الجلسة الحالية وفرض الصلاحيات على المسارات."""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine.clock import system_clock
from app.models import User
from app.models.enums import SessionSubjectType
from app.security import csrf, sessions
from app.security.permissions import Action, PermissionDeniedError, require_permission

SESSION_COOKIE_NAME = "wamda_session"


def get_current_user(
    request: Request,
    db: OrmSession = Depends(get_db),
    wamda_session: Optional[str] = Cookie(default=None),
) -> User:
    if not wamda_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "لا جلسة")
    now = system_clock()
    session_row = sessions.get_valid_session(db, wamda_session, now)
    if session_row is None or session_row.subject_type != SessionSubjectType.USER:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الجلسة غير صالحة أو منتهية")
    user = db.get(User, session_row.subject_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "المستخدم غير نشط")
    request.state.session_id = str(session_row.id)
    return user


def require_password_changed(current_user: User = Depends(get_current_user)) -> User:
    """§٧-١: إجبار تغيير كلمة المرور أول دخول — لا يرى/يفعل شيئاً قبله
    (باستثناء مسار تغيير كلمة المرور نفسه، الذي لا يستخدم هذه التبعية)."""
    if current_user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "يجب تغيير كلمة المرور أولاً")
    return current_user


def verify_csrf(
    wamda_csrf: Optional[str] = Cookie(default=None),
    x_csrf_token: Optional[str] = Header(default=None),
) -> None:
    """§٩: CSRF على كل طلب كتابة — يُستخدم كتبعية على كل مسار POST/PUT/PATCH/DELETE
    (باستثناء تسجيل الدخول نفسه — لا جلسة سابقة لحمايتها بعد)."""
    if not csrf.verify_csrf_token(wamda_csrf, x_csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "رمز CSRF مفقود أو غير مطابق")


def require_role(action: Action):
    """§٧-١٣: يُطبَّق فوق `require_password_changed` — الترتيب يضمن أن
    فرض تغيير كلمة المرور يسبق أي فحص صلاحية آخر."""

    def _dependency(current_user: User = Depends(require_password_changed)) -> User:
        try:
            require_permission(current_user.role, action)
        except PermissionDeniedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
        return current_user

    return _dependency

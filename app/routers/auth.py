"""مسارات المصادقة — §٧-١ / §٩.

كوكي الجلسة `Secure + HttpOnly + SameSite=Strict` مع انتهاء ٨ ساعات، مطابق
حرفياً لما تنص عليه الوثيقة — يتطلب HTTPS فعلياً ليصل المتصفح إليه
(`Secure`)، وهذا مقصود لا عيباً في بيئة التطوير المحلية.
"""

from __future__ import annotations

import ipaddress
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine.clock import system_clock
from app.models import User
from app.models.enums import SessionSubjectType
from app.schemas.auth import (
    BackupCodesResponse,
    BackupCodesStatus,
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RegenerateBackupCodesRequest,
)
from app.security import audit, auth_service, backup_codes, csrf, lockout, passwords, sessions
from app.security.permissions import Action, has_permission
from app.security.deps import SESSION_COOKIE_NAME, enforce_login_rate_limit, get_current_user, verify_csrf

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_MAX_AGE = int(sessions.SESSION_TTL.total_seconds())
_COOKIE_SECURE = True  # §٩: Secure إلزامي دائماً — لا استثناء بيئة تطوير


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME, raw_token, max_age=_SESSION_MAX_AGE, httponly=True,
        secure=_COOKIE_SECURE, samesite="strict", path="/",
    )


def _client_ip(request: Request) -> Optional[str]:
    """عمود `sessions.ip` من نوع `inet` — يرفض أي نص ليس عنوان IP صالحاً
    (مثل `"testclient"` في FastAPI TestClient، أو منفذاً بلا عميل حقيقي)."""
    if request.client is None:
        return None
    try:
        ipaddress.ip_address(request.client.host)
    except ValueError:
        return None
    return request.client.host


def _ensure_csrf_cookie(request: Request, response: Response) -> None:
    if request.cookies.get(csrf.CSRF_COOKIE_NAME) is None:
        response.set_cookie(
            csrf.CSRF_COOKIE_NAME, csrf.generate_csrf_token(), max_age=_SESSION_MAX_AGE,
            httponly=False, secure=_COOKIE_SECURE, samesite="strict", path="/",
        )


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(enforce_login_rate_limit)])
def login(
    payload: LoginRequest, request: Request, response: Response, db: OrmSession = Depends(get_db)
) -> LoginResponse:
    _ensure_csrf_cookie(request, response)
    now = system_clock()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")

    try:
        user = auth_service.login_step1(db, username=payload.username, password=payload.password, now=now)
    except auth_service.InvalidCredentialsError as exc:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except lockout.AccountLockedError as exc:
        # ٢٠٢٦-١٠-٠٣: كان يصل ٥٠٠ خاماً (الاستثناء غير مُعالَج في الموجّه) — حساب مقفل = ٤٢٣ برسالة عربية
        db.commit()
        raise HTTPException(status.HTTP_423_LOCKED, "الحساب مقفل مؤقتاً بعد محاولات فاشلة — حاول لاحقاً") from exc

    if user.totp_secret is None:
        # لا سرّ مُثبَّت بعد — إمّا أول ظهور لهذا الاستدعاء (نعرض التحدي)
        # أو استدعاء ثانٍ يحمل بيانات إكمال التسجيل (نُثبِّت السرّ فعلياً).
        if not payload.totp_secret_setup or not payload.totp_code:
            db.commit()
            challenge = auth_service.generate_totp_setup_challenge(user)
            return LoginResponse(
                status="totp_setup_required", totp_secret=challenge.candidate_secret,
                provisioning_uri=challenge.provisioning_uri,
            )
        try:
            result = auth_service.login_step2_setup(
                db, user=user, candidate_secret=payload.totp_secret_setup, totp_code=payload.totp_code,
                now=now, ip=ip, ua=ua,
            )
        except auth_service.InvalidTwoFactorCodeError as exc:
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    else:
        if not payload.totp_code and not payload.backup_code:
            db.commit()
            return LoginResponse(status="totp_required")
        try:
            if payload.totp_code:
                result = auth_service.login_step2_verify(
                    db, user=user, totp_code=payload.totp_code, now=now, ip=ip, ua=ua
                )
            else:  # رمز احتياطي — بعد التحقق من كلمة المرور أعلاه، وبنفس القفل/حدّ المعدل
                result = auth_service.login_step2_backup(db, user=user, code=payload.backup_code, now=now, ip=ip, ua=ua)
        except auth_service.InvalidTwoFactorCodeError as exc:
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    db.commit()
    _set_session_cookie(response, result.raw_token)
    return LoginResponse(
        status="ok", must_change_password=result.must_change_password,
        backup_codes=result.backup_codes, backup_codes_remaining=result.backup_codes_remaining,
    )


@router.get("/backup-codes", response_model=BackupCodesStatus)
def backup_codes_status(db: OrmSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> BackupCodesStatus:
    left = backup_codes.remaining(db, user_id=current_user.id)
    return BackupCodesStatus(remaining=left, total=backup_codes.CODE_COUNT, low=left <= backup_codes.LOW_THRESHOLD)


@router.post(
    "/backup-codes/regenerate", response_model=BackupCodesResponse,
    dependencies=[Depends(verify_csrf), Depends(enforce_login_rate_limit)],
)
def regenerate_backup_codes(
    payload: RegenerateBackupCodesRequest, request: Request, db: OrmSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BackupCodesResponse:
    """يُنشئ عشرة رموز جديدة **ويُبطل كل السابقة**. يتطلب كلمة المرور الحالية (جلسة مسروقة وحدها لا تكفي) وتخضع لحدّ المعدل نفسه؛
    الكلمة الخاطئة تُحتسب في عدّاد قفل الحساب."""
    now = system_clock()
    if current_user.totp_secret is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "أعدّ المصادقة الثنائية أولاً — لا رموز احتياطية بلا جهاز مصادقة")
    if not passwords.verify_password(payload.password, current_user.password_hash):
        lockout.record_failed_attempt(db, current_user, now)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "كلمة المرور غير صحيحة")
    codes = backup_codes.generate(db, user_id=current_user.id, now=now)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="BACKUP_CODES_GENERATED", entity="users",
        entity_id=current_user.id, after={"count": len(codes), "reason": "regenerate"}, ip=_client_ip(request),
    )
    db.commit()
    return BackupCodesResponse(codes=codes, remaining=len(codes))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(verify_csrf)])
def logout(
    request: Request, response: Response, db: OrmSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    now = system_clock()
    session_row = sessions.get_valid_session(db, request.cookies.get(SESSION_COOKIE_NAME, ""), now)
    if session_row is not None:
        sessions.revoke_session(db, session_row)
        audit.log_write(db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="LOGOUT", entity="users", entity_id=current_user.id)
        db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(verify_csrf)])
def change_password(
    payload: ChangePasswordRequest, request: Request, db: OrmSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if not passwords.verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "كلمة المرور الحالية غير صحيحة")
    now = system_clock()
    session_id = getattr(request.state, "session_id", None)
    auth_service.change_password(
        db, user=current_user, new_password=payload.new_password, now=now, keep_session_id=session_id
    )
    db.commit()


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=current_user.id, username=current_user.username, full_name=current_user.full_name,
        role=current_user.role, must_change_password=current_user.must_change_password,
        permissions=sorted(a.value for a in Action if has_permission(current_user.role, a)),
    )

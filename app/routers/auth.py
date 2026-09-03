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
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    RecoverCompleteRequest,
    RecoverStartRequest,
    RecoverStartResponse,
)
from app.security import auth_service, csrf, passwords, sessions
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
        if not payload.totp_code:
            db.commit()
            return LoginResponse(status="totp_required")
        try:
            result = auth_service.login_step2_verify(
                db, user=user, totp_code=payload.totp_code, now=now, ip=ip, ua=ua
            )
        except auth_service.InvalidTwoFactorCodeError as exc:
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    db.commit()
    _set_session_cookie(response, result.raw_token)
    return LoginResponse(status="ok", must_change_password=result.must_change_password)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(verify_csrf)])
def logout(
    request: Request, response: Response, db: OrmSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    now = system_clock()
    session_row = sessions.get_valid_session(db, request.cookies.get(SESSION_COOKIE_NAME, ""), now)
    if session_row is not None:
        sessions.revoke_session(db, session_row)
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


@router.post("/recover/start", response_model=RecoverStartResponse)
def recover_start(payload: RecoverStartRequest, db: OrmSession = Depends(get_db)) -> RecoverStartResponse:
    question = auth_service.recover_get_security_question(db, username=payload.username)
    # لا نكشف عدم وجود المستخدم صراحةً — نفس الرد شكلاً في الحالتين
    return RecoverStartResponse(security_question=question)


@router.post("/recover/complete", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def recover_complete(payload: RecoverCompleteRequest, db: OrmSession = Depends(get_db)) -> None:
    now = system_clock()
    try:
        auth_service.recover_reset_password(
            db, username=payload.username, security_answer=payload.security_answer,
            new_password=payload.new_password, now=now,
        )
    except auth_service.InvalidCredentialsError as exc:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    db.commit()


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=current_user.id, username=current_user.username, full_name=current_user.full_name,
        role=current_user.role, must_change_password=current_user.must_change_password,
    )

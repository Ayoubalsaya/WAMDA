"""بوابة العميل (§٧-٦) — مشاهدة فقط: أرصدته وكشفه. لا حقول إدخال، لا
`cost_rate` (محجوب على مستوى الـAPI هنا — لا مخطّط رد في `schemas/portal.py`
أو `schemas/clients.py` يحمله إطلاقاً، اختبار القبول ٤١). كل استعلام
يُشتق من `current_client.id` (هوية الجلسة) حصراً — **لا مسار هنا يقبل
معرّف عميل من الطلب إطلاقاً**، فعزل البوابة (اختبار القبول ٤٠) بنيوي لا
فحصاً وقت التشغيل فقط.
"""

from __future__ import annotations

import ipaddress
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session as OrmSession

from sqlalchemy import select

from app.database import get_db
from app.engine.clock import system_clock
from app.models import Client, Currency, Location
from app.routers.clients import _client_balances, compute_client_statement
from app.schemas.clients import ClientBalanceRow, StatementResponse
from app.schemas.reference import CurrencyOut, LocationOut
from app.schemas.portal import (
    PortalChangePasswordRequest,
    PortalLoginRequest,
    PortalLoginResponse,
    PortalMeResponse,
    PortalRecoverCompleteRequest,
    PortalRecoverStartRequest,
    PortalRecoverStartResponse,
)
from app.security import csrf, passwords, portal_auth_service, portal_lockout, sessions
from app.security.deps import PORTAL_SESSION_COOKIE_NAME, get_current_client, require_portal_password_changed, verify_csrf

router = APIRouter(prefix="/portal", tags=["portal"])

_SESSION_MAX_AGE = int(sessions.SESSION_TTL.total_seconds())
_COOKIE_SECURE = True  # §٩: Secure إلزامي دائماً — نفس قرار auth.py، لا استثناء


def _set_portal_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        PORTAL_SESSION_COOKIE_NAME, raw_token, max_age=_SESSION_MAX_AGE, httponly=True,
        secure=_COOKIE_SECURE, samesite="strict", path="/",
    )


def _client_ip(request: Request) -> Optional[str]:
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


@router.post("/login", response_model=PortalLoginResponse)
def portal_login(
    payload: PortalLoginRequest, request: Request, response: Response, db: OrmSession = Depends(get_db),
) -> PortalLoginResponse:
    _ensure_csrf_cookie(request, response)
    now = system_clock()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent")
    try:
        result = portal_auth_service.login(db, code=payload.code, password=payload.password, now=now, ip=ip, ua=ua)
    except portal_lockout.PortalAccountLockedError as exc:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except portal_auth_service.InvalidPortalCredentialsError as exc:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    db.commit()
    _set_portal_session_cookie(response, result.raw_token)
    return PortalLoginResponse(status="ok", must_change_password=result.must_change_password)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(verify_csrf)])
def portal_logout(
    request: Request, response: Response, db: OrmSession = Depends(get_db),
    current_client: Client = Depends(get_current_client),
) -> None:
    now = system_clock()
    session_row = sessions.get_valid_session(db, request.cookies.get(PORTAL_SESSION_COOKIE_NAME, ""), now)
    if session_row is not None:
        sessions.revoke_session(db, session_row)
        db.commit()
    response.delete_cookie(PORTAL_SESSION_COOKIE_NAME, path="/")


@router.post(
    "/change-password", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(verify_csrf)],
)
def portal_change_password(
    payload: PortalChangePasswordRequest, request: Request, db: OrmSession = Depends(get_db),
    current_client: Client = Depends(get_current_client),
) -> None:
    if not passwords.verify_password(payload.current_password, current_client.portal_password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "كلمة المرور الحالية غير صحيحة")
    now = system_clock()
    session_id = getattr(request.state, "portal_session_id", None)
    portal_auth_service.change_password(
        db, client=current_client, new_password=payload.new_password, now=now, keep_session_id=session_id,
    )
    db.commit()


@router.post("/recover/start", response_model=PortalRecoverStartResponse)
def portal_recover_start(payload: PortalRecoverStartRequest, db: OrmSession = Depends(get_db)) -> PortalRecoverStartResponse:
    question = portal_auth_service.recover_get_security_question(db, code=payload.code)
    # لا نكشف عدم وجود الكود صراحةً — نفس الرد شكلاً في الحالتين (يطابق auth.py)
    return PortalRecoverStartResponse(security_question=question)


@router.post("/recover/complete", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def portal_recover_complete(payload: PortalRecoverCompleteRequest, db: OrmSession = Depends(get_db)) -> None:
    now = system_clock()
    try:
        portal_auth_service.recover_reset_password(
            db, code=payload.code, security_answer=payload.security_answer,
            new_password=payload.new_password, now=now,
        )
    except portal_auth_service.InvalidPortalCredentialsError as exc:
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    db.commit()


@router.get("/me", response_model=PortalMeResponse)
def portal_me(current_client: Client = Depends(get_current_client)) -> PortalMeResponse:
    """بلا `require_portal_password_changed` عمداً — الواجهة تحتاج معرفة
    `must_change_password` نفسها لتقرر عرض شاشة تغيير كلمة المرور أولاً."""
    return PortalMeResponse(
        code=current_client.code, name_ar=current_client.name_ar, must_change_password=current_client.portal_must_change,
    )


@router.get("/currencies", response_model=list[CurrencyOut])
def portal_currencies(
    db: OrmSession = Depends(get_db), current_client: Client = Depends(require_portal_password_changed),
) -> list[CurrencyOut]:
    """بيانات مرجعية غير حسّاسة (رمز/اسم/منازل عشرية) — بلا `cost_rate`
    بالطبع، لازمة للواجهة كي تُنسِّق كل مبلغ بدقة عملته الفعلية بدل ست
    منازل خام دائماً (نفس مبدأ `formatAmount` في شاشات المرحلة ٨). لا
    يمكن للبوابة استدعاء `/reference/currencies` مباشرة — ذاك يتطلب جلسة
    موظف (`require_password_changed` هناك تعتمد `get_current_user`)."""
    rows = db.execute(select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)).scalars().all()
    return [CurrencyOut(code=r.code, name_ar=r.name_ar, symbol=r.symbol, decimals=r.decimals, is_pivot=r.is_pivot) for r in rows]


@router.get("/locations", response_model=list[LocationOut])
def portal_locations(
    db: OrmSession = Depends(get_db), current_client: Client = Depends(require_portal_password_changed),
) -> list[LocationOut]:
    rows = db.execute(select(Location).where(Location.is_active.is_(True)).order_by(Location.code)).scalars().all()
    return [LocationOut(code=r.code, name_ar=r.name_ar, country=r.country) for r in rows]


@router.get("/balances", response_model=list[ClientBalanceRow])
def portal_balances(
    db: OrmSession = Depends(get_db), current_client: Client = Depends(require_portal_password_changed),
) -> list[ClientBalanceRow]:
    return _client_balances(db, current_client.id)


@router.get("/statement", response_model=StatementResponse)
def portal_statement(
    currency: str = Query(...), location: str = Query(...),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    db: OrmSession = Depends(get_db), current_client: Client = Depends(require_portal_password_changed),
) -> StatementResponse:
    return compute_client_statement(
        db, client_id=current_client.id, currency=currency, location=location, date_from=date_from, date_to=date_to,
    )

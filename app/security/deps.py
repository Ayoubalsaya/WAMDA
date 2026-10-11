"""تبعيات FastAPI — الجلسة الحالية وفرض الصلاحيات على المسارات."""

from __future__ import annotations

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.database import get_db
from app.engine.clock import system_clock
from app.models import Client, User
from app.models.enums import SessionSubjectType
from app.security import csrf, sessions
from app.security.permissions import CLIENT_ROLE, Action, PermissionDeniedError, require_permission
from app.security.rate_limit import RateLimitedError, RateLimiter

SESSION_COOKIE_NAME = f"{csrf.COOKIE_PREFIX}_session"
PORTAL_SESSION_COOKIE_NAME = f"{csrf.COOKIE_PREFIX}_portal_session"

# §٩ المرحلة ١٢ — عدّادات تحديد المعدل، واحد لكل سطح دخول (حالة على مستوى
# الوحدة عمداً — تُصفَّر بين الاختبارات عبر تجهيزة conftest).
_login_rate_limiter = RateLimiter(
    max_hits=settings.login_rate_limit_max, window_seconds=settings.login_rate_limit_window_seconds
)
_portal_login_rate_limiter = RateLimiter(
    max_hits=settings.portal_login_rate_limit_max, window_seconds=settings.login_rate_limit_window_seconds
)
# نقطتا الدعوة العامتان (`/portal/invite/verify`/`/portal/invite/accept`) —
# دلو منفصل عن دخول البوابة نفسه (استنفاد أحدهما لا يحجب الآخر)، نفس حدّ
# العميل الأوسع (هاتف بشبكة متغيّرة).
_portal_invite_rate_limiter = RateLimiter(
    max_hits=settings.portal_login_rate_limit_max, window_seconds=settings.login_rate_limit_window_seconds
)


def _rate_limit_key(request: Request) -> str:
    """عنوان العميل الحقيقي لمفتاح تحديد المعدل.

    خلف nginx يكون `request.client.host` دائماً `127.0.0.1` — لو اعتُمد
    عليه لأصبح الحدّ عامّاً على كل المستخدمين من عنوان واحد. لذلك حين
    `TRUST_PROXY_HEADERS=true` (يُضبَط في `.env` على السيرفر فقط، خلف nginx
    يضبط الترويسات فعلاً) نقرأ العنوان من ترويسات الوكيل:
    - `X-Real-IP` (nginx: `proxy_set_header X-Real-IP $remote_addr;`) —
      قيمة واحدة، عنوان العميل المباشر كما رآه nginx.
    - وإلا آخر مُدخَل في `X-Forwarded-For` (`$proxy_add_x_forwarded_for`
      يُلحِق عنوان النظير المباشر في النهاية، فالأخير هو العميل الحقيقي
      حتى لو زوّر العميل مُدخَلات يسارية).
    **الافتراض `False`**: الثقة العمياء بهذه الترويسات تسمح لأي أحد بتزوير
    عنوانه وتجاوز الحدّ — تُفعَّل فقط حين يوجد وكيل موثوق يضبطها. بلا
    تفعيل: `request.client` مباشرةً. تفاصيل إعداد nginx في README."""
    if settings.trust_proxy_headers:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _enforce(limiter: RateLimiter, request: Request) -> None:
    try:
        limiter.hit(_rate_limit_key(request), now=system_clock().timestamp())
    except RateLimitedError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


def enforce_login_rate_limit(request: Request) -> None:
    """تبعية على `POST /auth/login` فقط."""
    _enforce(_login_rate_limiter, request)


def enforce_portal_login_rate_limit(request: Request) -> None:
    """تبعية على `POST /portal/login` فقط — حدّ أوسع (§٩)."""
    _enforce(_portal_login_rate_limiter, request)


def enforce_portal_invite_rate_limit(request: Request) -> None:
    """تبعية على `POST /portal/invite/verify` و`POST /portal/invite/accept`
    — نقطتان عامتان قبل أي جلسة، تحتاجان نفس حماية تحديد المعدل."""
    _enforce(_portal_invite_rate_limiter, request)


BACKGROUND_HEADER = "x-wamda-background"


def _touch_unless_background(request: Request, db: OrmSession, session_row, now) -> None:
    """النشاط الفعلي يجدّد مهلة الخمول؛ الاستعلام الآلي (جرس الإشعارات) يرسل `X-Wamda-Background` فلا يُبقي الجلسة حيّة بلا مستخدم."""
    if request.headers.get(BACKGROUND_HEADER):
        return
    if sessions.touch(db, session_row, now):
        db.commit()


def get_current_user(
    request: Request,
    db: OrmSession = Depends(get_db),
    wamda_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
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
    _touch_unless_background(request, db, session_row, now)
    request.state.session_id = str(session_row.id)
    return user


def require_password_changed(current_user: User = Depends(get_current_user)) -> User:
    """§٧-١: إجبار تغيير كلمة المرور أول دخول — لا يرى/يفعل شيئاً قبله
    (باستثناء مسار تغيير كلمة المرور نفسه، الذي لا يستخدم هذه التبعية)."""
    if current_user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "يجب تغيير كلمة المرور أولاً")
    return current_user


def get_current_client(
    request: Request,
    db: OrmSession = Depends(get_db),
    wamda_portal_session: Optional[str] = Cookie(default=None, alias=PORTAL_SESSION_COOKIE_NAME),
) -> Client:
    """مطابق لـ`get_current_user` لكن لجلسات `SessionSubjectType.CLIENT`
    حصراً — كوكي منفصل تماماً (`wamda_portal_session`) عن جلسة الموظف، فلا
    يمكن لأي منهما أن يُستخدَم مكان الآخر ولو بالخطأ (اختبار القبول ٤٠)."""
    if not wamda_portal_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "لا جلسة")
    now = system_clock()
    session_row = sessions.get_valid_session(db, wamda_portal_session, now)
    if session_row is None or session_row.subject_type != SessionSubjectType.CLIENT:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الجلسة غير صالحة أو منتهية")
    client = db.get(Client, session_row.subject_id)
    if client is None or not client.is_active or not client.portal_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الحساب غير نشط")
    _touch_unless_background(request, db, session_row, now)
    request.state.portal_session_id = str(session_row.id)
    return client


def require_portal_access(current_client: Client = Depends(get_current_client)) -> Client:
    """§٧-٦: يفحص `Action.VIEW_OWN_STATEMENT` عبر `PERMISSION_MATRIX` —
    تكرار بنيوي مقصود مع فحص `subject_type`/`portal_enabled` في
    `get_current_client`، لا اعتماد عليه وحده.

    ⚠ كانت تُدعى `require_portal_password_changed` وتفرض أيضاً
    `portal_must_change` (اختبار القبول ٤٢) — أُلغي ذلك الحقل والفحص
    (٢٠٢٦-١٠-٠٢، قرار مالك): العميل يختار كلمته بنفسه دوماً عبر قبول
    رابط الدعوة، فلا توجد حالة "جلسة بلا كلمة مرور مُختارة" بعد الآن
    — راجع PROGRESS.md قسم إدارة بوابة العميل."""
    try:
        require_permission(CLIENT_ROLE, Action.VIEW_OWN_STATEMENT)
    except PermissionDeniedError as exc:  # pragma: no cover — CLIENT_ROLE يملكها دائماً، دفاع بنيوي إضافي فقط
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return current_client


def verify_csrf(
    wamda_csrf: Optional[str] = Cookie(default=None, alias=csrf.CSRF_COOKIE_NAME),
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

    _dependency.required_action = action  # للفحص الآلي (test_permission_matrix)
    return _dependency

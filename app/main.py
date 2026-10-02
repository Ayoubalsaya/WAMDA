"""نقطة دخول FastAPI — §٩: HTTPS إلزامي، رؤوس أمان كاملة، CSRF على كل كتابة."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings as app_settings
from app.validation_errors import validation_exception_handler
from app.documents import render as doc_render
from app.routers import (
    audit, auth, clients, dashboard, documents, entry_actions, operations, partners, periods, portal, reconciliation,
    reference, reports, search, settings, users,
)
from app.security import csrf

_IS_PRODUCTION = app_settings.app_env == "production"

# §٩ — سياسة أمان المحتوى. صارمة على السكربت (`script-src 'self'` — لا inline،
# لا CDN؛ بناء Vite يُخرج وحدات خارجية مبصومة فقط، تحقَّق أدناه ببناء فعلي).
# `style-src 'unsafe-inline'` لازم: React يحقن أنماطاً سطرية. الخط مُستضاف
# محلياً منذ المرحلة ١٢ فـ`font-src 'self'` يكفي (لا googleapis/gstatic).
_CSP = "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "object-src 'none'",
    "img-src 'self' data:",
    "font-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self'",
    "connect-src 'self'",
])

# كل ميزة متصفح لا يستخدمها النظام — تُعطَّل صراحةً
_PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()" for feature in (
        "accelerometer", "autoplay", "camera", "display-capture", "encrypted-media",
        "fullscreen", "geolocation", "gyroscope", "magnetometer", "microphone",
        "midi", "payment", "usb", "xr-spatial-tracking",
    )
)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """محرك توليد المستندات (§٨) — متصفح Chromium واحد يُشغَّل هنا مرة عند
    الإقلاع ويُعاد استخدامه لكل طلبات PDF/PNG طوال عمر العملية، بدل
    تشغيل/إغلاق متصفح لكل مستند.

    **لا `doc_render.stop()` هنا عمداً** — `_lifespan` يُطلَق مرة واحدة على
    خادم uvicorn حقيقي، لكن كل ملف اختبار في `tests/` ينشئ `TestClient(app)`
    خاصاً به (`with TestClient(app) as c:`) فيُشغِّل دورة lifespan كاملة —
    استدعاء `stop()` هنا كان يُغلق المتصفح الحقيقي بعد كل ملف اختبار
    فيُعاد تشغيله من الصفر في التالي (`start()` نفسها idempotent، محمية
    بفحص `_thread is not None` أعلاها) — رفع وقت مجموعة `pytest` الكاملة
    من ~دقيقتين إلى **أكثر من ٣ ساعات** فعلياً (اكتُشف بتشغيل حقيقي، ليس
    افتراضاً). الخيط خلفية (`daemon=True`) وعملية Chromium الفرعية تُنهيان
    تلقائياً مع خروج عملية Python نفسها (خادم uvicorn الحقيقي أو جلسة
    pytest) — لا حاجة فعلية لإغلاق صريح، `render.stop()` تبقى موجودة
    لاستخدام مستقبلي مُتحكَّم به إن استُدعيت صراحة خارج هذا المسار."""
    doc_render.start()
    yield


app = FastAPI(
    title="ومضة",
    lifespan=_lifespan,
    # §٩: واجهات التوثيق التفاعلية تُعطَّل في الإنتاج (تحمّل أصول من CDN
    # خارجي وتكشف سطح الـAPI كاملاً) — `/openapi.json` يبقى للتحقق الآلي
    # (`curl /openapi.json` قبل أي اختبار حيّ، قرار المرحلة ٧).
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
)

# ٢٠٢٦-١٠-٠٢: كل ٤٢٢ تحقق يُترجَم إلى العربية باسم الحقل — لا قائمة Pydantic خام
# تصل المستخدم (انظر app/validation_errors.py).
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(operations.router)
app.include_router(entry_actions.router)
app.include_router(reference.router)
app.include_router(clients.router)
app.include_router(dashboard.router)
app.include_router(portal.router)
app.include_router(search.router)
app.include_router(reconciliation.router)
app.include_router(reports.router)
app.include_router(partners.router)
app.include_router(settings.router)
app.include_router(documents.router)
app.include_router(periods.router)
app.include_router(audit.router)

_FRONTEND_DIST = Path(__file__).parent / "static" / "app"
if _FRONTEND_DIST.is_dir():
    app.mount("/static/app", StaticFiles(directory=_FRONTEND_DIST), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        """واجهة React المبنية (`frontend/` → `npm run build`) — صفحة واحدة
        بلا توجيه عناوين من جهة العميل، فلا حاجة لمسار شامل (catch-all)."""
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/portal", include_in_schema=False)
    def portal_index() -> FileResponse:
        """بوابة العميل (§٧-٦) — حزمة React **مستقلة** تماماً عن واجهة
        الموظف (مدخل Vite ثانٍ `portal.html`، لا مشاركة شجرة React ولا
        حالة). صفحة واحدة أيضاً — لا شاشات فرعية تحتاج توجيهاً."""
        return FileResponse(_FRONTEND_DIST / "portal.html")


@app.middleware("http")
async def ensure_csrf_cookie(request: Request, call_next):
    """يضمن أن كل عميل يحمل كوكي CSRF حتى قبل تسجيل الدخول — بلا هذا لا
    توجد قيمة أصلاً ليُقارَن بها رمز الترويسة عند أول طلب كتابة."""
    response: Response = await call_next(request)
    if request.cookies.get(csrf.CSRF_COOKIE_NAME) is None:
        response.set_cookie(
            csrf.CSRF_COOKIE_NAME, csrf.generate_csrf_token(), max_age=8 * 3600,
            httponly=False, secure=True, samesite="strict", path="/",
        )
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """§٩: رؤوس أمان كاملة على كل رد.

    - `Strict-Transport-Security`: إنتاج فقط (HSTS فوق HTTP يُتجاهَل، وإرساله
      محلياً على http بلا معنى) — سنة كاملة + النطاقات الفرعية.
    - `Content-Security-Policy` · `Permissions-Policy` · `Referrer-Policy` ·
      `X-Content-Type-Options` · `X-Frame-Options` (مع `frame-ancestors 'none'`
      في CSP كطبقة ثانية).
    - إخفاء توقيع الخادم (`server_tokens off` نظيره): uvicorn يُشغَّل بـ
      `--no-server-header` وnginx بـ`server_tokens off` — كلاهما إعداد نشر
      (المرحلة ١٥، موثَّق في README)؛ لا يمكن حذف ترويسة يضيفها uvicorn
      **بعد** هذه الطبقة من داخل التطبيق.
    - `Cache-Control: no-store` على كل رد غير الأصول الثابتة — لا يُخزَّن
      رد يحمل بيانات مالية/جلسة في وسيط أو قرص المتصفح.
    """
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["Permissions-Policy"] = _PERMISSIONS_POLICY
    if _IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if not request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

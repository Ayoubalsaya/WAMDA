"""نقطة دخول FastAPI — §٩: HTTPS إلزامي، رؤوس أمان كاملة، CSRF على كل كتابة."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.documents import render as doc_render
from app.routers import (
    auth, clients, dashboard, documents, operations, partners, portal, reconciliation, reference, reports, search,
    settings, users,
)
from app.security import csrf


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


app = FastAPI(title="ومضة", lifespan=_lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(operations.router)
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
    """§٩: رؤوس أمان كاملة."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

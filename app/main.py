"""نقطة دخول FastAPI — §٩: HTTPS إلزامي، رؤوس أمان كاملة، CSRF على كل كتابة."""

from __future__ import annotations

from fastapi import FastAPI, Request, Response

from app.routers import auth, users
from app.security import csrf

app = FastAPI(title="ومضة")

app.include_router(auth.router)
app.include_router(users.router)


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

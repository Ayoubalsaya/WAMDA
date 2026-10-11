"""علامة البيئة والتحقق من الكود المُشغَّل (٢٠٢٦-١٠-١٢، قرار مالك):
· `/health` يُرجع `status` + رقم الالتزام المختصر **فقط** (بلا إصدارات ولا مسارات).
· `/environment` عام: البيئة + اسم كوكي CSRF (الواجهة تحتاجه قبل أول كتابة).
· الإنتاج: `/openapi.json` و`/docs` و`/redoc` معطَّلة، وأسماء الكوكيز بلاحقة `wamda_prod_` (لا تتصادم مع التطوير على 127.0.0.1)."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent


def test_health_returns_only_status_and_short_commit():
    body = TestClient(app).get("/health").json()
    assert set(body) == {"status", "commit"}
    assert body["status"] == "ok"
    assert re.fullmatch(r"[0-9a-f]{7,12}|unknown", body["commit"])
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head:  # التشغيل داخل مستودع git
        assert body["commit"] == head or body["commit"] == "unknown"


def test_environment_is_public_and_reports_local_defaults():
    resp = TestClient(app).get("/environment")
    assert resp.status_code == 200
    assert resp.json() == {"environment": "local", "csrf_cookie_name": "wamda_csrf"}


_PROD_PROBE = """
import json, warnings
warnings.filterwarnings("ignore")
from fastapi.testclient import TestClient
from app.main import app
from app.security import csrf, deps
c = TestClient(app)
print(json.dumps({
    "env": c.get("/environment").json(),
    "health": c.get("/health").json(),
    "openapi": c.get("/openapi.json").status_code,
    "docs": c.get("/docs").status_code,
    "redoc": c.get("/redoc").status_code,
    "names": [csrf.CSRF_COOKIE_NAME, deps.SESSION_COOKIE_NAME, deps.PORTAL_SESSION_COOKIE_NAME],
}))
"""


def test_production_disables_openapi_and_prefixes_cookie_names():
    env = {
        **os.environ,
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://x:x@127.0.0.1:5432/x",
        "TOTP_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"wamda-env-marker-test-key".ljust(32, b"_")).decode(),
        "LOGIN_RATE_LIMIT_MAX": "5", "PORTAL_LOGIN_RATE_LIMIT_MAX": "5", "LOGIN_RATE_LIMIT_WINDOW_SECONDS": "900",
        "PYTHONIOENCODING": "utf-8",
    }
    out = subprocess.run([sys.executable, "-c", _PROD_PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["env"] == {"environment": "production", "csrf_cookie_name": "wamda_prod_csrf"}
    assert got["names"] == ["wamda_prod_csrf", "wamda_prod_session", "wamda_prod_portal_session"]
    assert got["openapi"] == 404 and got["docs"] == 404 and got["redoc"] == 404
    assert got["health"]["status"] == "ok" and set(got["health"]) == {"status", "commit"}

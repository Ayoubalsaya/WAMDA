"""§٩ المرحلة ١٢ — رؤوس الأمان على كل رد + تعطيل واجهات التوثيق في الإنتاج.

كل رأس يَعِد بحماية يُختبَر أنه موجود فعلاً بالقيمة الصحيحة، لا أنه "مُفترَض".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_core_security_headers_present_on_every_response(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"
    assert "Content-Security-Policy" in r.headers
    assert "Permissions-Policy" in r.headers


def test_csp_is_strict_no_external_no_unsafe_script(client):
    csp = client.get("/health").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    # لا سكربت سطري، لا eval، لا CDN خطوط خارجي
    assert "'unsafe-eval'" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "googleapis" not in csp and "gstatic" not in csp
    assert "http:" not in csp and "https://" not in csp


def test_permissions_policy_disables_sensitive_features(client):
    pp = client.get("/health").headers["Permissions-Policy"]
    for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in pp


def test_hsts_absent_in_local_env(client):
    # الإعداد الافتراضي app_env=local — HSTS فوق http بلا معنى، لا يُرسَل
    assert main_mod._IS_PRODUCTION is False
    assert "Strict-Transport-Security" not in client.get("/health").headers


def test_hsts_present_when_production(client, monkeypatch):
    # الوسيط يقرأ `_IS_PRODUCTION` وقت الطلب — monkeypatch يكفي بلا إعادة استيراد
    monkeypatch.setattr(main_mod, "_IS_PRODUCTION", True)
    hsts = client.get("/health").headers.get("Strict-Transport-Security")
    assert hsts == "max-age=31536000; includeSubDomains"


def test_api_responses_are_not_cacheable(client):
    assert client.get("/health").headers["Cache-Control"] == "no-store"


def test_openapi_always_available_for_verification(client):
    # قرار المرحلة ٧: `curl /openapi.json` قبل أي اختبار حيّ — يبقى متاحاً
    assert client.get("/openapi.json").status_code == 200

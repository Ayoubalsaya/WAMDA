"""أخطاء التحقق (٤٢٢) بالعربية، لا JSON خام (٢٠٢٦-١٠-٠٢، ملاحظة مالك).

كانت رسالة Pydantic الخام تصل المستخدم حرفياً:
`[{"type":"greater_than","loc":["body","cost_rate"],...}]`. المعالج العام
(`app/validation_errors.py`) يترجمها لكل المسارات — هنا:
  1) الحالة الأصلية بعينها؛
  2) **كل** مسار كتابة له جسم يُستدعى بجسم فاسد ومعاملات مسار فاسدة، ويُثبَت أن
     كل ٤٢٢ يعيد `detail` نصاً عربياً بلا أي أثر لـ JSON/إنجليزية Pydantic؛
  3) كل حقل في أي مخطّط طلب له اسم عربي في القاموس (حقل جديد بلا اسم يكسر الاختبار)؛
  4) أنواع الأخطاء الشائعة تُترجم لنصوص محددة.
"""

from __future__ import annotations

import json
import re

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.security.passwords import hash_password
from app.validation_errors import FIELD_LABELS_AR, translate_validation_errors
from tests import factories as f

ARABIC = re.compile(r"[؀-ۿ]")
RAW_MARKERS = ('"type"', '"loc"', '"ctx"', "Input should", "Field required", "[{", "greater_than", "value_error", "string_type")


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client: TestClient):
    user = f.make_user(db, role="ADMIN")
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def _headers(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf"), "Idempotency-Key": f.uid()}


def _assert_arabic_no_raw(resp):
    body = resp.json()
    detail = body["detail"]
    assert isinstance(detail, str), f"detail ليس نصاً: {detail!r}"
    assert ARABIC.search(detail), f"detail بلا عربية: {detail!r}"
    assert not any(m in detail for m in RAW_MARKERS), f"أثر JSON/إنجليزية خام: {detail!r}"
    for err in body["errors"]:
        assert ARABIC.search(err["message"]), err
        assert err["label"] is None or ARABIC.search(err["label"]), err
        assert not any(m in err["message"] for m in RAW_MARKERS), err


def test_original_report_cost_rate_zero_is_arabic_and_names_the_field(db, client):
    _login(db, client)
    c = f.make_client(db)
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI",
              "from_currency": "LYD", "to_currency": "USD", "amount": "100", "cost_rate": "0", "client_rate": "9.05"},
        headers=_headers(client),
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "«سعر التكلفة»: يجب أن يكون أكبر من صفر"
    assert body["errors"] == [{
        "loc": ["cost_rate"], "field": "cost_rate", "label": "سعر التكلفة",
        "message": "يجب أن يكون أكبر من صفر", "type": "greater_than",
    }]


def _write_routes_with_body():
    spec = app.openapi()
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in ("post", "put", "patch") and isinstance(op, dict) and op.get("requestBody"):
                yield method.upper(), path


GARBAGE_BODIES = [{}, {"amount": "abc", "cost_rate": "0", "client_id": "x", "lines": "nope"}, [1, 2], "نص"]


def test_every_write_route_returns_arabic_422_never_raw_json(db, client):
    """كل مسار كتابة بجسم، بكل جسم فاسد ومسار فاسد: أي ٤٢٢ عربي بلا JSON خام."""
    _login(db, client)
    routes = list(_write_routes_with_body())
    assert len(routes) >= 40, "ينبغي أن يغطي الاختبار كل مسارات الكتابة بجسم"
    n_422 = 0
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", "abc", path)  # معاملات المسار فاسدة (int ← 'abc') فيتحقق ٤٢٢ المسار أيضاً
        for body in GARBAGE_BODIES:
            resp = client.request(method, url, json=body, headers=_headers(client))
            if resp.status_code == 422:
                n_422 += 1
                _assert_arabic_no_raw(resp)
            else:
                # أي ردّ آخر (٤٠٣ صلاحية، ٤٠٤…) لا يجوز أن يحمل JSON خاماً أيضاً
                text = resp.text
                assert not any(m in text for m in RAW_MARKERS), f"{method} {path} → {resp.status_code}: {text[:200]}"
    assert n_422 >= len(routes), "معظم الطلبات الفاسدة يجب أن تنتهي بـ٤٢٢"


def test_malformed_json_body_is_arabic(db, client):
    _login(db, client)
    resp = client.post(
        "/operations/receipt", content=b"{not json", headers={**_headers(client), "Content-Type": "application/json"}
    )
    assert resp.status_code == 422
    _assert_arabic_no_raw(resp)


def test_bad_query_param_is_arabic(db, client):
    _login(db, client)
    resp = client.get("/journal/entries?date=ليس-تاريخاً")
    assert resp.status_code == 422
    _assert_arabic_no_raw(resp)
    assert "«التاريخ»" in resp.json()["detail"]


def test_every_request_schema_field_has_an_arabic_label():
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    request_schemas: set[str] = set()

    def collect(name: str):
        if name in request_schemas:
            return
        request_schemas.add(name)
        for prop in schemas[name].get("properties", {}).values():
            for ref in re.findall(r'"\$ref": "#/components/schemas/([^"]+)"', json.dumps(prop)):
                collect(ref)

    for item in spec["paths"].values():
        for op in item.values():
            body = op.get("requestBody") if isinstance(op, dict) else None
            for content in (body or {}).get("content", {}).values():
                ref = content.get("schema", {}).get("$ref")
                if ref:
                    collect(ref.split("/")[-1])
    missing = sorted({
        field for name in request_schemas for field in schemas[name].get("properties", {})
        if field not in FIELD_LABELS_AR
    })
    assert not missing, f"حقول بلا اسم عربي في FIELD_LABELS_AR: {missing}"


@pytest.mark.parametrize(
    "err, expected",
    [
        ({"type": "missing", "loc": ("body", "amount")}, "هذا الحقل مطلوب"),
        ({"type": "greater_than", "loc": ("body", "amount"), "ctx": {"gt": 0}}, "يجب أن يكون أكبر من صفر"),
        ({"type": "greater_than_equal", "loc": ("body", "fee_amount"), "ctx": {"ge": 0}}, "يجب ألا يكون سالباً"),
        ({"type": "decimal_parsing", "loc": ("body", "amount")}, "يجب أن يكون رقماً صحيحاً (مثل 9.05)"),
        ({"type": "int_parsing", "loc": ("path", "client_id")}, "يجب أن يكون عدداً صحيحاً"),
        ({"type": "date_from_datetime_parsing", "loc": ("query", "date")}, "تاريخ غير صالح (الصيغة: السنة-الشهر-اليوم)"),
        ({"type": "enum", "loc": ("body", "role")}, "قيمة غير مسموحة"),
        ({"type": "value_error", "msg": "Value error, مرّر أحدهما فقط", "loc": ("body",)}, "مرّر أحدهما فقط"),
        ({"type": "value_error", "msg": "Value error, English only", "loc": ("body",)}, "قيمة غير صالحة"),
        ({"type": "something_new", "loc": ("body", "amount")}, "قيمة غير صالحة"),
    ],
)
def test_error_type_translations(err, expected):
    assert translate_validation_errors([err])[0]["message"] == expected


def test_root_loc_stripped_but_field_named_body_kept():
    out = translate_validation_errors([{"type": "missing", "loc": ("body", "body")}])[0]
    assert out["loc"] == ["body"] and out["field"] == "body" and out["label"] == "نص التعليق"

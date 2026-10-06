"""فحص تحقق (الوكيل ٥): هل يحتفظ التعديل بتاريخ القيد الأصلي؟ يعمل داخل معاملة تُلغى (fixtures الاختبارات)،
خارج tests/ — يُشغَّل بـ: pytest docs/audit/05_scripts/test_edit_backdate_probe.py -p tests.conftest --rootdir=. -c pytest.ini"""
from decimal import Decimal

from app.models import JournalEntry
from tests import factories as f
from tests.test_edit_prefill_api import _h, _login, client  # noqa: F401


def test_probe(db, client, now):  # noqa: F811
    user = _login(db, client)
    c = f.make_client(db)
    body = {"client_id": c.id, "currency_code": "LYD", "location_code": "TRIPOLI", "amount": "100.000",
            "receiving_account_code": "1101", "entry_date": "2026-03-10", "backdate_reason": "probe"}
    r = client.post("/operations/receipt", json=body, headers=_h(client))
    print("CREATE", r.status_code, r.text[:200])
    assert r.status_code == 201
    eid = r.json()["id"]
    orig = db.get(JournalEntry, eid)
    print("ORIGINAL entry_date =", orig.entry_date, "is_backdated =", getattr(orig, "is_backdated", None))
    saved = client.get(f"/operations/{eid}/source-request").json()["request"]
    print("SAVED has entry_date:", saved.get("entry_date"), "backdate_reason:", saved.get("backdate_reason"))
    edited = {k: v for k, v in saved.items() if v is not None}
    edited["amount"] = "101.000"
    e = client.post(f"/operations/{eid}/edit", json={"reason": "probe", "operation": edited},
                    headers={"X-CSRF-Token": client.cookies.get("wamda_csrf")})
    print("EDIT", e.status_code, e.text[:200])
    new = db.get(JournalEntry, e.json()["new_entry"]["id"])
    print("NEW entry_date =", new.entry_date, "is_backdated =", getattr(new, "is_backdated", None))
    print("RESULT: date preserved =", new.entry_date == orig.entry_date)

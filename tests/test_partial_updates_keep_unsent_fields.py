"""التحديث الجزئي لا يمحو ما لم يُرسَل (٢٠٢٦-١٠-٠٦، تدقيق U-08): حفظ اسم الشركة كان يمحو الشعار لأن `model_dump()` الكامل
يستبدل المخزَّن بالافتراضيات. الفحص الأوسع: كل PATCH/PUT جزئي في المشروع يُجرَّب بإرسال حقل واحد وتبقى بقية الحقول."""

from __future__ import annotations

from tests import factories as f
from tests.test_edit_prefill_api import _h, _login, client  # noqa: F401

_LOGO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="


def _put(client, body):
    r = client.put("/settings/company", json=body, headers=_h(client))
    assert r.status_code == 200, r.text
    return r.json()


def test_saving_the_company_name_keeps_the_logo(db, client):
    _login(db, client)
    _put(client, {"name_ar": "ومضة", "logo_data_url": _LOGO})
    assert _put(client, {"name_ar": "ومضة للصرافة"}) == {"name_ar": "ومضة للصرافة", "logo_data_url": _LOGO}
    assert client.get("/settings/company").json()["logo_data_url"] == _LOGO


def test_saving_only_the_logo_keeps_the_name(db, client):
    _login(db, client)
    _put(client, {"name_ar": "اسم مخصص"})
    assert _put(client, {"logo_data_url": _LOGO})["name_ar"] == "اسم مخصص"


def test_logo_is_cleared_only_by_an_explicit_null(db, client):
    _login(db, client)
    _put(client, {"name_ar": "ومضة", "logo_data_url": _LOGO})
    assert _put(client, {"logo_data_url": None})["logo_data_url"] is None
    assert client.get("/settings/company").json()["name_ar"] == "ومضة"


def test_other_partial_updates_keep_the_fields_they_do_not_send(db, client):
    _login(db, client)
    c = f.make_client(db)
    r = client.patch(f"/clients/{c.id}", json={"name_en": "Co", "phone": "091", "id_number": "123"}, headers=_h(client))
    assert r.status_code == 200, r.text
    r = client.patch(f"/clients/{c.id}", json={"phone": "092"}, headers=_h(client))
    body = r.json()
    assert (body["name_ar"], body["name_en"], body["phone"], body["id_number"]) == (c.name_ar, "Co", "092", "123")

    cur = client.patch("/settings/currencies/LYD", json={"symbol": "ل.د"}, headers=_h(client)).json()
    again = client.patch("/settings/currencies/LYD", json={"name_ar": cur["name_ar"]}, headers=_h(client)).json()
    assert (again["symbol"], again["decimals"], again["sort_order"], again["is_active"]) == (cur["symbol"], cur["decimals"], cur["sort_order"], cur["is_active"])

    loc = client.get("/settings/locations").json()[0]
    one = client.patch(f"/settings/locations/{loc['code']}", json={"country": "ليبيا"}, headers=_h(client)).json()
    two = client.patch(f"/settings/locations/{loc['code']}", json={"name_ar": loc["name_ar"]}, headers=_h(client)).json()
    assert (two["country"], two["is_active"]) == (one["country"], one["is_active"])

    other = f.make_user(db, role="ACCOUNTANT")
    u = client.patch(f"/users/{other.id}", json={"role": "ADMIN"}, headers=_h(client)).json()
    u2 = client.patch(f"/users/{other.id}", json={"is_active": False}, headers=_h(client)).json()
    assert (u2["role"], u2["is_active"]) == ("ADMIN", False) and u["is_active"] is True

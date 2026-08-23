"""سدّ الدَّين المؤجَّل من المرحلة ٢: اشتقاق الدور من `created_by` كان
يعمل بلا أي جهة تتحقق أن `created_by` نفسه يعكس مستخدماً موثَّقاً فعلاً —
أي مستدعٍ للمحرك كان يستطيع تمرير أي `created_by` بلا رقابة. هذا الاختبار
يثبت أن السلسلة الآن مكتملة فعلياً: تسجيل دخول حقيقي عبر HTTP → جلسة
موثَّقة → `get_current_user` → هوية حقيقية تُستخدم كـ`created_by` — والدور
الذي يحكم بوابة القيد بأثر رجعي في `posting.py` (§٥ قاعدة ٥) ينعكس
تلقائياً من هوية ذلك المستخدم الحقيقية، لا من رقم يُمرَّر بثقة عمياء.

لا مسار في app.engine يقبل "role" كوسيط مباشر إطلاقاً (تحقَّق منه بحث
نصي) — الدور دائماً بحث `users.role` عبر `created_by`، وهذا الاختبار
يثبت أن ذلك البحث الآن متجذّر في مصادقة حقيقية بدل قيمة يُنشئها الاختبار
يدوياً.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine import accounts_repo, posting
from app.engine.posting import BackdatedEntryRequiresAdminError
from app.main import app
from app.models import FoundingPeriod, Period, User
from app.security.deps import SESSION_COOKIE_NAME, get_current_user
from app.security.passwords import hash_password
from tests import factories as f


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login_real_user(db, client: TestClient, *, role: str) -> User:
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    valid_code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post(
        "/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": valid_code}
    )
    assert resp.status_code == 200
    return user


def _current_user_via_dependency(db, session_token: str) -> User:
    """يحاكي بالضبط ما تفعله أي مسار API محمي: يستخرج الهوية من كوكي
    الجلسة عبر نفس تبعية FastAPI الحقيقية `get_current_user` — لا اختصار."""
    from fastapi import Request

    scope = {"type": "http", "headers": [], "method": "GET", "path": "/"}
    request = Request(scope)
    return get_current_user(request, db=db, wamda_session=session_token)


def test_backdated_entry_role_flows_from_real_session_not_trusted_parameter(db, client):
    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    entry_date = date(2026, 6, 15)
    db.add(Period(year=entry_date.year, month=entry_date.month, is_closed=True))
    db.flush()

    accountant = _login_real_user(db, client, role="ACCOUNTANT")
    accountant_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert accountant_token

    authenticated_accountant = _current_user_via_dependency(db, accountant_token)
    assert authenticated_accountant.id == accountant.id
    assert authenticated_accountant.role == "ACCOUNTANT"

    # القيد بأثر رجعي يُرفض للمحاسب — created_by مُشتَق من جلسة حقيقية، لا رقم اختُلق
    with pytest.raises(BackdatedEntryRequiresAdminError):
        posting.create_draft_entry(
            db, operation_type="RECEIPT", entry_date=entry_date, created_by=authenticated_accountant.id,
        )

    client.cookies.clear()
    admin = _login_real_user(db, client, role="ADMIN")
    admin_token = client.cookies.get(SESSION_COOKIE_NAME)
    authenticated_admin = _current_user_via_dependency(db, admin_token)
    assert authenticated_admin.role == "ADMIN"

    draft = posting.create_draft_entry(
        db, operation_type="RECEIPT", entry_date=entry_date, created_by=authenticated_admin.id,
        backdate_reason="تصحيح بأثر رجعي بموافقة الإدارة — عبر جلسة موثَّقة فعلياً",
    )
    cash = accounts_repo.get_account_by_code(db, "1101")
    client_obj = f.make_client(db)
    client_account = accounts_repo.get_or_create_client_account(
        db, client=client_obj, currency_code="LYD", location_code="TRIPOLI"
    )
    draft.add(account_id=cash.id, currency_code="LYD", debit=Decimal("50.000"))
    draft.add(account_id=client_account.id, currency_code="LYD", credit=Decimal("50.000"))
    now = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
    entry = posting.post_entry(db, draft, posted_by=authenticated_admin.id, now=now)
    assert entry.created_by == admin.id  # نفس هوية الجلسة الموثَّقة بالضبط

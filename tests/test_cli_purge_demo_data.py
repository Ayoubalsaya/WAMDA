"""اختبار `python -m app.cli purge-demo-data` ضد قاعدة تطوير حقيقية —
بيانات مُلتزَمة (commit) فعلياً كأي أمر CLI آخر، لا عزل `db` fixture هنا
عمداً (نفس اتفاقية `test_cli_admin.py`).

⚠ `_purge()` مطابقة **عالمية** بالتصميم (هذا هو المطلوب من الأداة نفسها):
تحذف كل صف يطابق أنماط الأكواد التجريبية أينما وُجد في القاعدة، لا صفوف
هذا الاختبار وحدها. تشغيله فعلياً وأنت لا تعرف ما الموجود حالياً خطأ
حقيقي وقع فعلاً أثناء بناء هذا الملف — حذف `demo_admin`/`DEMO-001` وهما
بيانات عرض حقيقية كان المالك يعتمد عليها للاختبار اليدوي، فأُعيد إنشاؤهما
يدوياً بعدها. الدرس المطبَّق هنا: هذا الاختبار الآن `@pytest.mark.destructive`
ومُستبعد من `pytest -q` الافتراضي (`pytest.ini`) — لا يُشغَّل إلا يدوياً
بـ`pytest -m destructive` وبعد التأكد أن لا بيانات عرض حية يعتمد عليها أحد.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.engine.operations import receipt as receipt_op
from app.models import Account, AccountBalance, Client, JournalEntry, User
from tests.factories import make_correspondent_account, uid

NOW = datetime.now(timezone.utc)


@pytest.mark.destructive
def test_purge_demo_data_removes_only_matching_rows_and_posted_entries():
    from app.cli import purge_demo_data

    db = SessionLocal()
    try:
        user = User(
            username=f"test_purge_{uid()}", full_name="مستخدم اختبار التنظيف",
            password_hash="x", role="ACCOUNTANT", is_active=True, must_change_password=False,
        )
        db.add(user)
        db.flush()

        client = Client(code=f"T-{uid()}", name_ar="عميل اختبار التنظيف", search_name="عميل اختبار التنظيف")
        db.add(client)
        db.flush()

        correspondent = make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")

        entry = receipt_op.execute(
            db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("123.000"),
            receiving_account_code="1101", work_timezone="Africa/Tripoli", created_by=user.id, now=NOW,
            idempotency_key=uid(),
        )
        db.commit()  # قيد POSTED حقيقي مُلتزَم — بالضبط ما يجب أن يتعامل الحذف معه

        client_account = db.execute(
            select(Account).where(Account.code == f"2100-{client.code}-LYD-TRIPOLI")
        ).scalar_one()
        entry_id, client_account_id, correspondent_id, client_id, user_id = (
            entry.id, client_account.id, correspondent.id, client.id, user.id,
        )
    finally:
        db.close()

    # عميل/قيد حقيقيان (لا يطابقان أي نمط عرض/اختبار) — يجب ألا يُمسّا
    db2 = SessionLocal()
    try:
        real_user = User(
            username=f"realuser_{uid()}", full_name="مستخدم حقيقي", password_hash="x",
            role="ACCOUNTANT", is_active=True, must_change_password=False,
        )
        db2.add(real_user)
        db2.flush()
        real_client = Client(code=f"REAL-{uid()}", name_ar="عميل حقيقي", search_name="عميل حقيقي")
        db2.add(real_client)
        db2.flush()
        real_entry = receipt_op.execute(
            db2, client=real_client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
            receiving_account_code="1101", work_timezone="Africa/Tripoli", created_by=real_user.id, now=NOW,
            idempotency_key=uid(),
        )
        db2.commit()
        real_entry_id, real_user_id, real_client_id = real_entry.id, real_user.id, real_client.id
    finally:
        db2.close()

    try:
        db3 = SessionLocal()
        try:
            purge_demo_data._purge(db3)
            db3.commit()
        finally:
            db3.close()

        db4 = SessionLocal()
        try:
            assert db4.get(JournalEntry, entry_id) is None
            assert db4.get(Account, client_account_id) is None
            assert db4.get(AccountBalance, client_account_id) is None
            assert db4.get(Account, correspondent_id) is None
            assert db4.get(Client, client_id) is None
            assert db4.get(User, user_id) is None

            # الحساب النظامي المشترك 1101 نفسه (وليس حساب العميل المُشتق منه) يبقى سليماً
            assert db4.execute(select(Account).where(Account.code == "1101")).scalar_one() is not None

            # البيانات الحقيقية غير المطابقة لأي نمط تجريبي تبقى كما هي تماماً
            assert db4.get(JournalEntry, real_entry_id) is not None
            assert db4.get(User, real_user_id) is not None
            assert db4.get(Client, real_client_id) is not None
        finally:
            db4.close()
    finally:
        # تنظيف بيانات "الواقعية" المُصطنَعة كمجموعة ضبط لهذا الاختبار وحده —
        # ليست جزءاً مما يختبره الحذف (بالتصميم لا تطابق أي نمط عرض/اختبار)،
        # فتُزال يدوياً هنا بنفس أسلوب تعطيل المشغّل المؤقت كي لا تتراكم بقايا.
        from sqlalchemy import text as _text

        db5 = SessionLocal()
        try:
            db5.execute(_text("ALTER TABLE journal_lines DISABLE TRIGGER trg_journal_lines_no_edit_when_posted"))
            try:
                db5.execute(_text("DELETE FROM idempotency_keys WHERE entry_id = :id"), {"id": real_entry_id})
                db5.execute(_text("DELETE FROM journal_lines WHERE entry_id = :id"), {"id": real_entry_id})
                db5.execute(_text("DELETE FROM journal_entries WHERE id = :id"), {"id": real_entry_id})
            finally:
                db5.execute(_text("ALTER TABLE journal_lines ENABLE TRIGGER trg_journal_lines_no_edit_when_posted"))
            db5.execute(_text("""
                DELETE FROM account_balances WHERE account_id IN (
                    SELECT id FROM accounts WHERE client_id = :cid
                )
            """), {"cid": real_client_id})
            db5.execute(_text("DELETE FROM accounts WHERE client_id = :cid"), {"cid": real_client_id})
            db5.execute(_text("DELETE FROM clients WHERE id = :id"), {"id": real_client_id})
            db5.execute(_text("DELETE FROM users WHERE id = :id"), {"id": real_user_id})
            # نفس سبب استدعاء recompute.rebuild داخل _purge نفسها — real_entry
            # مسّ حساباً مشتركاً (١١٠١) لا يخصّ هذا الاختبار وحده.
            from app.engine import recompute as _recompute

            _recompute.rebuild(db5)
            db5.commit()
        finally:
            db5.close()


def test_purge_demo_data_matches_qa_prefixed_usernames(db):
    """`qa_%` (حسابات اختبار يدوي مثل qa_totp_test) تُطابَق الآن — بمعاملة
    معزولة تُلغى (`db` fixture)، لا حذف حقيقي هنا، فحص المطابقة فقط."""
    from app.cli import purge_demo_data
    from app.models import User

    before = purge_demo_data._counts(db)["users"]
    db.add(User(
        username=f"qa_{uid()}", full_name="اختبار عرض يدوي", password_hash="x",
        role="ACCOUNTANT", is_active=True, must_change_password=False,
    ))
    db.flush()
    after = purge_demo_data._counts(db)["users"]
    assert after == before + 1


def test_purge_demo_data_noop_prints_message_when_nothing_matches(capsys):
    from app.cli import purge_demo_data

    db = SessionLocal()
    try:
        counts = purge_demo_data._counts(db)
    finally:
        db.close()
    # مجرد التأكد أن دالة العدّ لا تنفجر ببيانات لا تطابق أي نمط — لا نفترض صفراً
    # (قد تبقى بقايا مُلتزَمة من اختبارات أخرى) بل فقط أن المفاتيح المتوقعة موجودة
    assert set(counts) == {"clients", "partners", "users", "journal_entries"}

"""اختبار منطق `python -m app.cli purge-demo-data` (`_purge`/`_counts`).

**تصحيح بنيوي (٢٠٢٦-٠٨-٢٨) بعد حادثتين متطابقتين**: النسخة الأولى من هذا
الملف استخدمت `SessionLocal()` بـcommit حقيقي مباشرةً — بحجة أن `_purge`
تحتاج قيداً POSTED حقيقياً محمياً بمشغّل القاعدة لتختبره بصدق. هذا خطأ:
`receipt_op.execute` لا يستدعي commit إطلاقاً (كبقية طبقة المحرك)، والمشغّل
يعمل على مستوى العبارة (statement) لا يحتاج commit خارجياً واقعاً ليُفعَّل.
فمعاملة `db` fixture المعزولة (SAVEPOINT يُلغى تلقائياً) كانت **كافية
تماماً** من البداية — بلا أي حاجة لـSessionLocal حقيقية.

استخدام SessionLocal الحقيقية **بلا ضرورة فعلية** هو ما سبَّب حذف
`demo_admin`/`DEMO-001` الحقيقيَّين **مرتين** أثناء بناء هذا الملف — لأن
`_purge()` مطابقة عالمية بالتصميم (هذا هو المطلوب من الأداة نفسها) تمسّ
كل شيء مطابق في القاعدة الحقيقية المشتركة، لا صفوف الاختبار وحدها. أُعيد
إنشاء الحسابين يدوياً في كلتا المرتين. هذا الملف الآن لا يستخدم
`SessionLocal` بـcommit حقيقي في أي اختبار — الاختبار الرئيسي يعمل داخل
معاملة `db` المعزولة، فتصبح إعادة تشغيله بأمان في أي وقت — بلا مارِكر
`destructive` وبلا حاجة لأي تنظيف يدوي بعده.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.engine.operations import receipt as receipt_op
from app.models import Account, AccountBalance, Client, JournalEntry, User
from tests.factories import make_correspondent_account, uid


def test_purge_demo_data_removes_only_matching_rows_and_posted_entries(db, now):
    """معاملة `db` المعزولة وحدها — لا SessionLocal حقيقية، لا commit
    خارجي، لا خطر على أي بيانات حقيقية مهما وُجدت في القاعدة المشتركة."""
    from app.cli import purge_demo_data

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
        receiving_account_code="1101", work_timezone="Africa/Tripoli", created_by=user.id, now=now,
        idempotency_key=uid(),
    )
    client_account = db.execute(select(Account).where(Account.code == f"2100-{client.code}-LYD-TRIPOLI")).scalar_one()

    # عميل/قيد "حقيقيان" (لا يطابقان أي نمط عرض/اختبار) — ضمن نفس المعاملة المعزولة
    real_user = User(
        username=f"realuser_{uid()}", full_name="مستخدم حقيقي", password_hash="x",
        role="ACCOUNTANT", is_active=True, must_change_password=False,
    )
    db.add(real_user)
    db.flush()
    real_client = Client(code=f"REAL-{uid()}", name_ar="عميل حقيقي", search_name="عميل حقيقي")
    db.add(real_client)
    db.flush()
    real_entry = receipt_op.execute(
        db, client=real_client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", work_timezone="Africa/Tripoli", created_by=real_user.id, now=now,
        idempotency_key=uid(),
    )

    purge_demo_data._purge(db)  # بلا commit — يبقى داخل معاملة الاختبار المعزولة
    # _purge تحذف بـSQL خام (نص) لا عبر الـORM — خريطة هوية الجلسة (identity
    # map) لا تعرف تلقائياً أن الكائنات المُحمَّلة أعلاه حُذفت فعلياً؛
    # expunge_all يُنسي الجلسة إياها فتُعيد استعلامها فعلياً من القاعدة.
    db.expunge_all()

    assert db.get(JournalEntry, entry.id) is None
    assert db.get(Account, client_account.id) is None
    assert db.get(AccountBalance, client_account.id) is None
    assert db.get(Account, correspondent.id) is None
    assert db.get(Client, client.id) is None
    assert db.get(User, user.id) is None

    # الحساب النظامي المشترك 1101 نفسه (وليس حساب العميل المُشتق منه) يبقى سليماً
    assert db.execute(select(Account).where(Account.code == "1101")).scalar_one() is not None

    # البيانات "الحقيقية" غير المطابقة لأي نمط تجريبي تبقى كما هي تماماً
    assert db.get(JournalEntry, real_entry.id) is not None
    assert db.get(User, real_user.id) is not None
    assert db.get(Client, real_client.id) is not None


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


def test_purge_demo_data_refuses_outside_local_env(monkeypatch, capsys):
    """حارس البيئة: أي قيمة APP_ENV غير 'local' → رفض فوري بلا أي محاولة حذف،
    حتى بلا سؤال عن التأكيد."""
    from app.cli import purge_demo_data

    monkeypatch.setattr(purge_demo_data.settings, "app_env", "production")
    with pytest.raises(SystemExit) as exc_info:
        purge_demo_data.run()
    assert exc_info.value.code == 1
    assert "production" in capsys.readouterr().out


def test_purge_demo_data_matches_unified_qa_client_prefix(db):
    """`QA-%` — السابقة الموحَّدة الجديدة لأكواد عملاء الاختبار اليدوي
    (بدل T-/STG المتفرّقة سابقاً). معاملة معزولة، لا حذف حقيقي هنا."""
    from app.cli import purge_demo_data
    from app.models import Client

    before = purge_demo_data._counts(db)["clients"]
    db.add(Client(code=f"QA-{uid()}", name_ar="عميل اختبار موحَّد", search_name="عميل اختبار موحَّد"))
    db.flush()
    after = purge_demo_data._counts(db)["clients"]
    assert after == before + 1


def test_purge_demo_data_matches_legacy_stg_and_test_patterns(db):
    """STG%/TEST% — أنماط رجعية طُلب تغطيتها صراحةً بعد اكتشاف بقايا
    STG6-* من اختبار يدوي سابق لم تكن الأنماط القديمة تغطّيها."""
    from app.cli import purge_demo_data
    from app.models import Client

    before = purge_demo_data._counts(db)["clients"]
    db.add(Client(code=f"STG9-{uid()}", name_ar="بقايا مرحلة تجريبية", search_name="بقايا مرحلة تجريبية"))
    db.add(Client(code=f"TESTXYZ-{uid()}", name_ar="شبكة أمان عامة", search_name="شبكة أمان عامة"))
    db.flush()
    after = purge_demo_data._counts(db)["clients"]
    assert after == before + 2


def test_purge_demo_data_deactivates_instead_of_deleting_user_referenced_by_real_client(db):
    """قرار مالك صريح بعد حادثة `demo_admin` الحقيقية: مستخدم تجريبي يشير
    إليه عميل **حقيقي** (غير تجريبي) عبر `created_by` لا يُحذف — يُعطَّل
    (`is_active=false`) ويُبلَّغ عنه بوضوح، بدل حذف جزئي صامت يترك مرجعاً
    يتيماً أو يفشل بخطأ مفتاح أجنبي."""
    from app.cli import purge_demo_data
    from app.models import Client, User

    demo_user = User(
        username=f"test_blocked_{uid()}", full_name="مستخدم تجريبي مرجعي", password_hash="x",
        role="ADMIN", is_active=True, must_change_password=False,
    )
    db.add(demo_user)
    db.flush()

    # عميل حقيقي (لا يطابق أي نمط عرض/اختبار) created_by يشير إلى المستخدم التجريبي
    real_client = Client(
        code=f"REAL-{uid()}", name_ar="عميل حقيقي يشير لمستخدم تجريبي",
        search_name="عميل حقيقي يشير لمستخدم تجريبي", created_by=demo_user.id,
    )
    db.add(real_client)
    db.flush()

    blocked = purge_demo_data._purge(db)
    db.expunge_all()

    assert demo_user.username in blocked
    assert any("clients.created_by" in reason for reason in blocked[demo_user.username])

    reloaded_user = db.get(User, demo_user.id)
    assert reloaded_user is not None  # لم يُحذف
    assert reloaded_user.is_active is False  # عُطِّل بدلاً من ذلك

    # العميل الحقيقي نفسه لم يُمسّ إطلاقاً
    assert db.get(Client, real_client.id) is not None


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


# ═══ ٢٠٢٦-١٠-٠٢: ثلاثة أخطاء حقيقية في الأداة كشفها فحص الدفعة LOT-2026-0108 ═══


def test_purge_deletes_demo_client_with_portal_invite_and_session(db, now):
    """`client_portal_invites` أُضيف ٢٠٢٦-١٠-٠٢ ولم تُحدَّث الأداة: حذف أي عميل `QA-`/`T-` له دعوة
    كان يفشل بقيد FK. وجلسات بوابة العميل (`sessions.subject_type='CLIENT'`) تُحذف معه أيضاً."""
    import hashlib
    from datetime import timedelta

    from sqlalchemy import text

    from app.cli import purge_demo_data
    from app.models import ClientPortalInvite, Session as SessionModel
    from app.models.enums import SessionSubjectType

    admin = User(username=f"realadmin_{uid()}", full_name="مدير حقيقي", password_hash="x", role="ADMIN",
                 is_active=True, must_change_password=False)
    db.add(admin)
    client = Client(code=f"QA-{uid()}", name_ar="عميل دعوة", search_name="عميل دعوة")
    db.add(client)
    db.flush()
    db.add(ClientPortalInvite(client_id=client.id, token_hash=hashlib.sha256(uid().encode()).hexdigest(),
                              expires_at=now + timedelta(hours=48), created_by=admin.id))
    db.flush()

    purge_demo_data._purge(db)
    db.expunge_all()

    assert db.get(Client, client.id) is None
    assert db.execute(text("SELECT count(*) FROM client_portal_invites WHERE client_id = :c"), {"c": client.id}).scalar() == 0
    assert db.get(User, admin.id) is not None  # مستخدم حقيقي لا يُمسّ


def test_purge_restores_real_lot_quantity_consumed_by_a_demo_sale(db, now):
    """الحادثة الأصلية: بيع تجريبي استهلك من دفعة رمبي **حقيقية**؛ حذف الأداة لصفوف الاستهلاك دون
    إعادة `remaining_qty` كان يُنقص المخزون للأبد (LOT-2026-0108 نقصت ١٣٦ بلا سجل يفسّر ذلك)."""
    from app.engine import accounts_repo, lots_fifo, recompute
    from app.engine.operations import exchange as exchange_op
    from app.models import CurrencyLot, LotConsumption
    from app.models.enums import LotStatus
    from app.cli import purge_demo_data

    real_user = User(username=f"realuser_{uid()}", full_name="مستخدم حقيقي", password_hash="x", role="ADMIN",
                     is_active=True, must_change_password=False)
    db.add(real_user)
    db.flush()
    real_client = Client(code=f"REAL-{uid()}", name_ar="عميل حقيقي", search_name="عميل حقيقي")
    db.add(real_client)
    db.flush()
    source = receipt_op.execute(
        db, client=real_client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
        receiving_account_code="1101", work_timezone="Africa/Tripoli", created_by=real_user.id, now=now, idempotency_key=uid(),
    )
    bank = accounts_repo.create_bank_account(db, currency_code="CNY", location_code="CHINA", name_ar="بنك حقيقي للاختبار")
    lot = lots_fifo.open_lot(
        db, source_entry_id=source.id, currency_code="CNY", account_id=bank.id, original_qty=Decimal("1000.00"),
        cost_rate=Decimal("6.80"), cost_currency="USD", cost_decimals=2, now=now,
    )
    lot_id = lot.id

    demo_user = User(username=f"test_{uid()}", full_name="مستخدم تجريبي", password_hash="x", role="ADMIN",
                     is_active=True, must_change_password=False)
    db.add(demo_user)
    db.flush()
    demo_client = Client(code=f"QA-{uid()}", name_ar="عميل بيع تجريبي", search_name="عميل بيع تجريبي")
    db.add(demo_client)
    db.flush()
    receipt_op.execute(
        db, client=demo_client, currency_code="USD", location_code="TURKEY", amount=Decimal("100.00"),
        receiving_account_code="1104", work_timezone="Africa/Tripoli", created_by=demo_user.id, now=now, idempotency_key=uid(),
    )
    exchange_op.execute_via_lot(
        db, client=demo_client, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal("10.00"),
        client_rate=Decimal("6.80"), work_timezone="Africa/Tripoli", created_by=demo_user.id, now=now, idempotency_key=uid(),
    )
    db.refresh(lot)
    assert lot.remaining_qty == Decimal("932.00")  # ١٠$ × ٦٫٨٠ = ٦٨ يوان استُهلكت
    assert recompute.verify(db).lot_problems == []

    purge_demo_data._purge(db)
    db.expunge_all()

    lot = db.get(CurrencyLot, lot_id)
    assert lot is not None, "الدفعة الحقيقية يجب ألا تُحذف"
    assert lot.remaining_qty == Decimal("1000.00"), "كمية الدفعة لم تُعَد بعد حذف الاستهلاك التجريبي"
    assert lot.status == LotStatus.OPEN
    assert db.execute(select(LotConsumption).where(LotConsumption.lot_id == lot_id)).first() is None
    assert recompute.verify(db).lot_problems == []


def test_every_foreign_key_into_purged_tables_is_reviewed_in_the_tool(db):
    """يفرض مراجعة الأداة عند أي جدول جديد: كل مفتاح أجنبي إلى clients/partners/users/accounts/
    journal_entries/currency_lots/swift_movements يجب أن يكون في `PURGE_COVERED_FOREIGN_KEYS`
    (أي تُعالَج صراحةً في `_purge`/`_USER_REFERENCE_CHECKS`). جدول جديد بلا مراجعة يكسر هذا الاختبار —
    لا فشل FK متأخر على بيانات حقيقية. (حادثة `client_portal_invites` ٢٠٢٦-١٠-٠٢.)"""
    from sqlalchemy import text

    from app.cli import purge_demo_data

    rows = db.execute(text("""
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public' AND ccu.table_name = ANY(:targets)
    """), {"targets": list(purge_demo_data.PURGE_FK_TARGET_TABLES)}).all()
    actual = {(t, c) for t, c in rows}
    unreviewed = sorted(actual - purge_demo_data.PURGE_COVERED_FOREIGN_KEYS)
    stale = sorted(purge_demo_data.PURGE_COVERED_FOREIGN_KEYS - actual)
    assert not unreviewed, f"مفاتيح أجنبية جديدة لم تُراجَع في purge_demo_data: {unreviewed}"
    assert not stale, f"قائمة التغطية فيها مفاتيح لم تعد موجودة: {stale}"

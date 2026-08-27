"""حذف بيانات العرض/الاختبار قبل إدخال أي بيانات حقيقية — تفاعلي، يطلب
تأكيداً صريحاً قبل أي حذف فعلي.

═══ السابقة الموحَّدة لأي بيانات اختبار يدوي/QA من الآن فصاعداً ═══
  · اسم مستخدم:   `qa_<شيء>`      مثال: qa_stage7
  · كود عميل:     `QA-<شيء>`      مثال: QA-STAGE7-001
  · كود شريك:     `QA-P-<شيء>`
  · كود حساب:     `QA-ACC-<شيء>` أو `QA-BANK-<شيء>`
هذه السابقة الوحيدة المطلوب تذكّرها لأي بيانات اختبار يدوي جديدة — أي
بيانات بها تُحذف بأمر واحد دائماً، بلا استثناء وبلا حاجة لتحديث هذا
الملف لاحقاً.

═══ أنماط قديمة مُغطاة رجعياً لأغراض التوافق (لا تُستخدَم لبيانات جديدة) ═══
  · `test_%`/`T-%`/`T-P-%`/`T-ACC-%`/`T-BANK-%` — اصطلاح `tests/factories.py`
    (اختبارات pytest المُلتزَمة فعلياً مثل test_concurrency.py/test_cli_admin.py)
  · `test-admin-%` — اصطلاح `tests/test_cli_admin.py`
  · `STG%` (أكواد عملاء) — بقايا اختبار يدوي من المرحلة ٦ قبل توحيد السابقة
  · `TEST%` (مستخدمون وعملاء) — شبكة أمان عامة لأي تسمية غير موحَّدة
  · `demo_admin` / `DEMO-%` — حساب/عميل العرض التأسيسي (§٩)

**النطاق حصراً** (لا يمسّ أي شيء آخر — لا currencies/locations/شجرة
الحسابات النظامية/client_currency_locations/founding_period):
  عملاء/شركاء/حسابات/مستخدمون مطابقون لما سبق + كل قيد يمسّ أياً منهم
  (كعميل/شريك/منشئ) + كل الجداول التابعة (أسطر القيد · دفعات الرمبي
  واستهلاكها · حركات السويفت · الأرصدة الافتتاحية · لقطات REMIT_OUT ·
  مفاتيح التفرّد · الجلسات).

**قيد POSTED لا يُحذف عادة (§٥ قاعدة ٢: "لا حذف أبداً")** — مشغّل
`trg_journal_lines_no_edit_when_posted` يرفض ذلك بتصميمه. هذا الأمر
استثناء واعٍ ومحدود النطاق: يُعطَّل المشغّل داخل نفس معاملة الحذف
لبيانات العرض/الاختبار **فقط قبل دخول أي بيانات حقيقية**، ويُعاد تفعيله
فوراً بعدها — بلا استثناء لأي صف حقيقي مهما كان.

`audit_log` **لا يُمسّ إطلاقاً** (append-only، §٥ قاعدة ١١) — صفوفه التي
تشير إلى كيانات مُحذوفة تبقى أثراً تاريخياً صادقاً، و`entity_id` فيها
بلا قيد مفتاح أجنبي أصلاً فلا يتعارض حذفها مع بقاء تلك الصفوف.

**حارس بيئة إلزامي**: يرفض العمل كلياً إن كان `settings.app_env` غير
`local` — أداة حذف شامل بهذا الاتساع لا يجوز أن تُشغَّل عن طريق الخطأ
على أي بيئة نشر حقيقية، مهما كانت الثقة بالأنماط أعلاه.
"""

from __future__ import annotations

import sys

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.engine import recompute


def _demo_client_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'DEMO-%' OR {col} LIKE 'QA-%' OR {col} LIKE 'T-%' OR {col} LIKE 'STG%' OR {col} LIKE 'TEST%')"


def _demo_partner_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'QA-P-%' OR {col} LIKE 'T-P-%')"


def _demo_account_codes(alias: str = "") -> str:
    col = f"{alias}.code" if alias else "code"
    return f"({col} LIKE 'QA-ACC-%' OR {col} LIKE 'QA-BANK-%' OR {col} LIKE 'T-ACC-%' OR {col} LIKE 'T-BANK-%')"


def _demo_usernames(alias: str = "") -> str:
    col = f"{alias}.username" if alias else "username"
    return (
        f"({col} = 'demo_admin' "
        rf"OR {col} LIKE 'qa\_%' ESCAPE '\' "
        rf"OR {col} LIKE 'test\_%' ESCAPE '\' "
        f"OR {col} LIKE 'test-admin-%' "
        f"OR {col} LIKE 'TEST%')"
    )


_DEMO_CLIENT_CODES = _demo_client_codes()
_DEMO_PARTNER_CODES = _demo_partner_codes()
_DEMO_ACCOUNT_CODES = _demo_account_codes()
_DEMO_USERNAMES = _demo_usernames()


def _counts(db: Session) -> dict[str, int]:
    rows = {
        "clients": db.execute(text(f"SELECT count(*) FROM clients WHERE {_DEMO_CLIENT_CODES}")).scalar(),
        "partners": db.execute(text(f"SELECT count(*) FROM partners WHERE {_DEMO_PARTNER_CODES}")).scalar(),
        "users": db.execute(text(f"SELECT count(*) FROM users WHERE {_DEMO_USERNAMES}")).scalar(),
        "journal_entries": db.execute(text(f"""
            SELECT count(*) FROM journal_entries e WHERE
                e.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                OR e.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                OR e.created_by IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
                OR e.id IN (
                    SELECT jl.entry_id FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
                    WHERE a.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                       OR a.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                       OR {_demo_account_codes("a")}
                )
        """)).scalar(),
    }
    return rows


def _demo_entry_ids_cte() -> str:
    """جزء SQL مشترك (subquery) لمعرّفات كل قيد يمسّ بيانات العرض/الاختبار."""
    return f"""(
        SELECT e.id FROM journal_entries e WHERE
            e.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
            OR e.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
            OR e.created_by IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
            OR e.id IN (
                SELECT jl.entry_id FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
                WHERE a.client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
                   OR a.partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
                   OR {_demo_account_codes("a")}
            )
    )"""


def _demo_account_ids_cte() -> str:
    return f"""(
        SELECT id FROM accounts WHERE
            client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})
            OR partner_id IN (SELECT id FROM partners WHERE {_DEMO_PARTNER_CODES})
            OR {_DEMO_ACCOUNT_CODES}
    )"""


def _purge(db: Session) -> None:
    entries = _demo_entry_ids_cte()
    accounts = _demo_account_ids_cte()

    # ١) فكّ أي إشارة عكس/معكوسية قبل الحذف (ذاتية الإشارة على journal_entries)
    db.execute(text(f"UPDATE journal_entries SET reversed_by_entry_id = NULL WHERE reversed_by_entry_id IN {entries}"))
    db.execute(text(f"UPDATE journal_entries SET reverses_entry_id = NULL WHERE reverses_entry_id IN {entries}"))

    # ٢) الجداول التابعة للقيود
    db.execute(text(f"DELETE FROM lot_consumptions WHERE entry_id IN {entries}"))
    db.execute(text(f"DELETE FROM remit_out_destinations WHERE entry_id IN {entries}"))
    db.execute(text(f"DELETE FROM idempotency_keys WHERE entry_id IN {entries}"))
    db.execute(text(f"""
        DELETE FROM lot_consumptions WHERE lot_id IN (SELECT id FROM currency_lots WHERE source_entry_id IN {entries})
    """))
    db.execute(text(f"DELETE FROM currency_lots WHERE source_entry_id IN {entries}"))
    db.execute(text(f"""
        DELETE FROM swift_movements
        WHERE out_entry_id IN {entries} OR in_entry_id IN {entries} OR return_entry_id IN {entries}
    """))
    db.execute(text(f"""
        UPDATE opening_reconciliation SET resolving_entry_id = NULL WHERE resolving_entry_id IN {entries}
    """))
    db.execute(text(f"DELETE FROM opening_balances WHERE account_id IN {accounts} OR contra_account_id IN {accounts}"))

    # ٣) أسطر القيد — تعطيل مؤقت لمشغّل عدم التعديل بعد الترحيل، نطاق هذه
    # المعاملة فقط، لبيانات العرض/الاختبار حصراً (انظر docstring أعلى الملف)
    db.execute(text("ALTER TABLE journal_lines DISABLE TRIGGER trg_journal_lines_no_edit_when_posted"))
    try:
        db.execute(text(f"DELETE FROM journal_lines WHERE entry_id IN {entries}"))
        db.execute(text(f"DELETE FROM journal_entries WHERE id IN {entries}"))
    finally:
        db.execute(text("ALTER TABLE journal_lines ENABLE TRIGGER trg_journal_lines_no_edit_when_posted"))

    # ٤) أرصدة/بيانات الحسابات التجريبية، ثم الحسابات نفسها
    db.execute(text(f"DELETE FROM account_balances WHERE account_id IN {accounts}"))
    db.execute(text(f"DELETE FROM client_credit_limits WHERE client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})"))
    db.execute(text(f"DELETE FROM beneficiaries WHERE client_id IN (SELECT id FROM clients WHERE {_DEMO_CLIENT_CODES})"))
    db.execute(text(f"DELETE FROM accounts WHERE id IN {accounts}"))

    # ٥) العملاء والشركاء أنفسهم
    db.execute(text(f"DELETE FROM clients WHERE {_DEMO_CLIENT_CODES}"))
    db.execute(text(f"DELETE FROM partners WHERE {_DEMO_PARTNER_CODES}"))

    # ٦) جلسات ثم المستخدمون التجريبيون (sessions.subject_id بلا FK صلب — تعدد أشكال)
    db.execute(text(f"""
        DELETE FROM sessions WHERE subject_type = 'USER' AND subject_id IN (SELECT id FROM users WHERE {_DEMO_USERNAMES})
    """))
    db.execute(text(f"DELETE FROM users WHERE {_DEMO_USERNAMES}"))

    # ٧) إعادة بناء account_balances بالكامل — إلزامي، لا اختياري: قيود
    # العرض/الاختبار المحذوفة قد تكون مسّت حسابات **مشتركة حقيقية** (١١٠١
    # مثلاً) لا تخصّها وحدها، فحذف أسطرها بلا إعادة بناء الرصيد المشتق
    # يترك account_balances.balance لتلك الحسابات المشتركة فاسداً بصمت.
    db.flush()
    recompute.rebuild(db)


def run() -> None:
    if settings.app_env != "local":
        print(
            f"مرفوض — APP_ENV=\"{settings.app_env}\" وليس \"local\". "
            "هذا الأمر لا يعمل إلا في بيئة تطوير محلية — لا يُشغَّل على أي بيئة نشر أبداً."
        )
        sys.exit(1)

    db = SessionLocal()
    try:
        counts = _counts(db)
        print("=== حذف بيانات العرض/الاختبار — معاينة قبل أي حذف فعلي ===")
        print(f"  عملاء تجريبيون:      {counts['clients']}")
        print(f"  شركاء تجريبيون:      {counts['partners']}")
        print(f"  مستخدمون تجريبيون:   {counts['users']}")
        print(f"  قيود مرتبطة بهم:     {counts['journal_entries']}")

        if sum(counts.values()) == 0:
            print("\nلا بيانات عرض/اختبار مطابقة — لا شيء ليُحذف.")
            db.rollback()
            return

        print(
            "\nهذا حذف فعلي بلا رجعة — بما في ذلك قيود مُرحّلة (استثناء واعٍ "
            "لبيانات العرض/الاختبار فقط، انظر رأس الملف). لا يمسّ العملات "
            "أو المواقع أو شجرة الحسابات أو audit_log."
        )
        confirmation = input("اكتب DELETE (بالإنجليزية) للتأكيد: ").strip()
        if confirmation != "DELETE":
            print("أُلغي — لم يُحذف شيء.")
            db.rollback()
            return

        _purge(db)
        db.commit()
        print("\nتم الحذف بنجاح.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()

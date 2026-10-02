"""مصانع كائنات مساعدة للاختبارات — تعمل ضمن معاملة `db` المحقونة (لا commit
هنا؛ الإلغاء نهاية الاختبار مسؤولية fixture `db` في conftest.py).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo
from app.engine.operations import receipt as receipt_op
from app.models import Account, Client, ClientCreditLimit, Partner, User
from app.models.enums import AccountForm, AccountType


def uid() -> str:
    return uuid.uuid4().hex[:10]


def make_user(db: Session, *, role: str = "ADMIN") -> User:
    user = User(
        username=f"test_{uid()}",
        full_name="مستخدم اختبار",
        password_hash="x",
        role=role,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    return user


def make_client(
    db: Session, *, credit_allowed: bool = False, name: str = "عميل اختبار"
) -> Client:
    code = f"T-{uid()}"
    client = Client(code=code, name_ar=name, search_name=name)
    db.add(client)
    db.flush()
    if credit_allowed:
        # السلوك القديم «مسموح، أي تجاوز يمر بمسار المدير» = حد رمزي موجب (٠٫٠١؛ حد صفر لم يعد ممكناً) في كل عملة فعّالة — الائتمان صار لكل عملة (٢٠٢٦-١٠-٠٣)
        from app.engine import credit

        for code_ in credit.active_currency_codes(db):
            credit.set_mode(db, client_id=client.id, currency_code=code_, mode=credit.LIMIT, limit_amount=Decimal("0.01"))
    return client


def set_credit_limit(db: Session, client: Client, currency_code: str, amount: Decimal) -> None:
    from app.engine import credit

    credit.set_mode(db, client_id=client.id, currency_code=currency_code, mode=credit.LIMIT, limit_amount=amount)


def set_credit_mode(db: Session, client: Client, currency_code: str, mode: str, amount: Decimal | None = None) -> None:
    from app.engine import credit

    credit.set_mode(db, client_id=client.id, currency_code=currency_code, mode=mode, limit_amount=amount)


def make_correspondent_account(
    db: Session,
    *,
    currency_code: str,
    location_code: str,
    parent_code: str,
    country: str = "XX",
) -> Account:
    """حساب مراسل تجريبي (نوع `CORRESPONDENT`) بكود فريد — لا يمسّ 1311/1321 الحقيقيين."""
    partner = Partner(code=f"T-P-{uid()}", name_ar="شريك اختبار", country=country)
    db.add(partner)
    db.flush()
    location = accounts_repo.get_location_by_code(db, location_code)
    parent = accounts_repo.get_account_by_code(db, parent_code)
    account = Account(
        code=f"T-ACC-{uid()}",
        name_ar="حساب مراسل اختبار",
        type=AccountType.ASSET,
        currency_code=currency_code,
        location_id=location.id,
        form=AccountForm.CORRESPONDENT,
        parent_id=parent.id,
        partner_id=partner.id,
    )
    db.add(account)
    db.flush()
    return account


def make_bank_account(
    db: Session, *, currency_code: str, location_code: str = "CHINA", parent_code: str = "1400"
) -> Account:
    location = accounts_repo.get_location_by_code(db, location_code)
    parent = accounts_repo.get_account_by_code(db, parent_code)
    account = Account(
        code=f"T-BANK-{uid()}",
        name_ar="حساب بنك اختبار",
        type=AccountType.ASSET,
        currency_code=currency_code,
        location_id=location.id,
        form=AccountForm.BANK,
        parent_id=parent.id,
    )
    db.add(account)
    db.flush()
    return account


def fund_client(
    db: Session,
    *,
    client: Client,
    currency_code: str,
    location_code: str,
    amount: Decimal,
    receiving_account_code: str,
    user: User,
    now,
    idempotency_key: Optional[str] = None,
):
    """RECEIPT حقيقية — تموّل الحساب المستقبِل (الشركة) ورصيد العميل معاً
    (طريقة تمويل واقعية بدل فتح رصيد مباشر — نفس اتفاقية scripts/demo_stage2.py).
    """
    return receipt_op.execute(
        db,
        client=client,
        currency_code=currency_code,
        location_code=location_code,
        amount=amount,
        receiving_account_code=receiving_account_code,
        work_timezone="Africa/Tripoli",
        created_by=user.id,
        now=now,
        idempotency_key=idempotency_key or uid(),
    )

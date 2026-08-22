"""فحص سريع: حد الائتمان يُطبَّق على مجموع العجز عبر كل مواقع العميل
لعملة واحدة، لا على كل حساب موقع بمعزل عن الآخر. تشغيل يدوي فقط.
"""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.engine import clock
from app.engine.operations import payment
from app.engine.posting import CreditLimitExceededError
from app.models import Client, ClientCreditLimit, User

WORK_TZ = settings.work_timezone


def _uuid():
    return str(uuid.uuid4())


def main():
    db = SessionLocal()
    now = clock.system_clock()
    user = db.execute(select(User).where(User.username == "demo_stage2")).scalar_one()

    client = Client(code="DEMO-CREDIT-01", name_ar="عميل فحص حد الائتمان", search_name="عميل فحص حد الائتمان", credit_allowed=True)
    db.add(client)
    db.flush()
    db.add(ClientCreditLimit(client_id=client.id, currency_code="USD", limit_amount=Decimal("3000.000000")))
    db.commit()

    print("── دفعة أولى: -2000 USD من TRIPOLI (ضمن الحد 3000) ──")
    payment.execute(
        db, client=client, currency_code="USD", location_code="TRIPOLI", amount=Decimal("2000.00"),
        paying_account_code="1104", work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=_uuid(), allow_negative=True, override_reason="فحص",
    )
    db.commit()
    print("  قُبلت (متوقع).")

    print("\n── دفعة ثانية: -2000 USD من TURKEY (وحدها ضمن الحد، لكن المجموع 4000 > 3000) ──")
    try:
        payment.execute(
            db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("2000.00"),
            paying_account_code="1321", work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=_uuid(),
        )
        print("  فشل الفحص: كان يجب أن تُرفض!")
    except CreditLimitExceededError as e:
        db.rollback()
        print(f"  رُفضت كما هو متوقع: {e}")

    db.close()


if __name__ == "__main__":
    main()

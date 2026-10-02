"""الائتمان لكل عميل × عملة (٢٠٢٦-١٠-٠٣، قرار مالك: ائتمان بلا سقف).

الوضع صريح: NONE (بلا ائتمان) · LIMIT (حد بمبلغ) · UNLIMITED (بلا سقف). غياب الصف = NONE، فعملة تُضاف لاحقاً لا تُفعَّل
تلقائياً وتجعل حالة العميل «جزئي». حالة العميل تُحسب من أوضاع عملاته الفعّالة ولا تُخزَّن.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClientCreditLimit, Currency

NONE = "NONE"
LIMIT = "LIMIT"
UNLIMITED = "UNLIMITED"
MODES = (NONE, LIMIT, UNLIMITED)

OPEN = "OPEN"        # ائتمان مفتوح — كل العملات بلا سقف
STOPPED = "STOPPED"  # متوقف — كل العملات بلا ائتمان
PARTIAL = "PARTIAL"  # جزئي — أوضاع مختلفة (حد مخصص أو عملة لم تُفعَّل)


@dataclass(frozen=True)
class CreditSetting:
    currency_code: str
    mode: str
    limit_amount: Optional[Decimal]


def active_currency_codes(db: Session) -> list[str]:
    return list(db.execute(select(Currency.code).where(Currency.is_active.is_(True)).order_by(Currency.sort_order, Currency.code)).scalars())


def settings_for(db: Session, client_id: int) -> dict[str, CreditSetting]:
    """وضع كل عملة فعّالة (غياب الصف ⇒ NONE) — الترتيب بترتيب العملات."""
    rows = {
        r.currency_code: r
        for r in db.execute(select(ClientCreditLimit).where(ClientCreditLimit.client_id == client_id)).scalars()
    }
    out: dict[str, CreditSetting] = {}
    for code in active_currency_codes(db):
        r = rows.get(code)
        out[code] = CreditSetting(code, r.mode, r.limit_amount) if r else CreditSetting(code, NONE, None)
    return out


def status_of(settings: dict[str, CreditSetting]) -> str:
    modes = {s.mode for s in settings.values()}
    if modes == {UNLIMITED}:
        return OPEN
    if modes == {NONE} or not modes:
        return STOPPED
    return PARTIAL


def client_status(db: Session, client_id: int) -> str:
    return status_of(settings_for(db, client_id))


def statuses_for(db: Session, client_ids: list[int]) -> dict[int, str]:
    """حالة عدة عملاء باستعلامين فقط (قوائم/بحث)."""
    codes = active_currency_codes(db)
    by_client: dict[int, dict[str, CreditSetting]] = {cid: {c: CreditSetting(c, NONE, None) for c in codes} for cid in client_ids}
    if client_ids:
        for r in db.execute(select(ClientCreditLimit).where(ClientCreditLimit.client_id.in_(client_ids))).scalars():
            if r.currency_code in by_client[r.client_id]:
                by_client[r.client_id][r.currency_code] = CreditSetting(r.currency_code, r.mode, r.limit_amount)
    return {cid: status_of(s) for cid, s in by_client.items()}


def set_mode(db: Session, *, client_id: int, currency_code: str, mode: str, limit_amount: Optional[Decimal] = None) -> None:
    """يكتب وضع (عميل، عملة). LIMIT يلزمه مبلغ ≥ 0؛ غيره يُصفّر المبلغ (لا NULL غامض: الوضع هو المرجع)."""
    if mode not in MODES:
        raise ValueError(f"وضع ائتمان غير معروف: {mode}")
    if mode == LIMIT and (limit_amount is None or limit_amount < 0):
        raise ValueError("وضع الحد يتطلب مبلغاً ≥ ٠")
    amount = limit_amount if mode == LIMIT else None
    row = db.get(ClientCreditLimit, (client_id, currency_code))
    if row is None:
        db.add(ClientCreditLimit(client_id=client_id, currency_code=currency_code, mode=mode, limit_amount=amount))
    else:
        row.mode, row.limit_amount = mode, amount
    db.flush()


def describe(s: CreditSetting) -> dict:
    return {"currency_code": s.currency_code, "mode": s.mode, "limit_amount": str(s.limit_amount) if s.limit_amount is not None else None}


def settings_for_many(db: Session, client_ids: list[int]) -> dict[int, dict[str, CreditSetting]]:
    codes = active_currency_codes(db)
    out: dict[int, dict[str, CreditSetting]] = {cid: {c: CreditSetting(c, NONE, None) for c in codes} for cid in client_ids}
    if client_ids:
        for r in db.execute(select(ClientCreditLimit).where(ClientCreditLimit.client_id.in_(client_ids))).scalars():
            if r.currency_code in out[r.client_id]:
                out[r.client_id][r.currency_code] = CreditSetting(r.currency_code, r.mode, r.limit_amount)
    return out

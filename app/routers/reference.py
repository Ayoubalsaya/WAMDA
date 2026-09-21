"""بيانات مرجعية للواجهة (قراءة فقط) — عملات · مواقع · حسابات قابلة
للترحيل · بحث عملاء · أرصدة عميل · مستفيدوه · دفتر اليومية اليوم.

بحث العملاء هنا مطابقة substring بسيطة (ILIKE) على name_ar/code/phone —
تبسيط مقصود لهذه المرحلة، لا يعيد تنفيذ منطق تطبيع search_name الكامل
لمشغّل القاعدة (§3-9)؛ يكفي للاستخدام اليومي، ديون تقنية إن ظهرت حاجة
لبحث ضبابي عربي أدق لاحقاً.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import account_filters
from app.engine.clock import system_clock, local_entry_date
from app.config import settings
from app.models import (
    Account,
    AccountBalance,
    Client,
    ClientCurrencyLocation,
    Currency,
    JournalEntry,
    JournalLine,
    Location,
    Partner,
    SwiftMovement,
    User,
)
from app.models.enums import EntryStatus, SwiftStatus
from app.schemas.reference import (
    AccountOut,
    ClientBalanceOut,
    ClientCurrencyLocationOut,
    ClientSearchResultOut,
    CurrencyOut,
    JournalEntryOut,
    JournalLineOut,
    LocationOut,
    PendingSwiftMovementOut,
)
from app.security.deps import require_password_changed, require_role
from app.security.permissions import Action

router = APIRouter(tags=["reference"], dependencies=[Depends(require_password_changed)])


@router.get("/reference/currencies", response_model=list[CurrencyOut])
def list_currencies(db: OrmSession = Depends(get_db)) -> list[CurrencyOut]:
    rows = db.execute(select(Currency).where(Currency.is_active.is_(True)).order_by(Currency.sort_order)).scalars().all()
    return [CurrencyOut(code=r.code, name_ar=r.name_ar, symbol=r.symbol, decimals=r.decimals, is_pivot=r.is_pivot) for r in rows]


@router.get("/reference/locations", response_model=list[LocationOut])
def list_locations(db: OrmSession = Depends(get_db)) -> list[LocationOut]:
    rows = db.execute(select(Location).where(Location.is_active.is_(True)).order_by(Location.code)).scalars().all()
    return [LocationOut(code=r.code, name_ar=r.name_ar, country=r.country) for r in rows]


@router.get("/reference/client-currency-locations", response_model=list[ClientCurrencyLocationOut])
def list_client_currency_locations(db: OrmSession = Depends(get_db)) -> list[ClientCurrencyLocationOut]:
    """§٢-٢: تركيبات عملة×موقع المسموح بها لحسابات العملاء — تُقيَّد بها
    قوائم الموقع في هـ-١ من مواصفة التصميم، لا يُدخل المستخدم موقعاً حراً."""
    rows = db.execute(
        select(ClientCurrencyLocation.currency_code, Location.code)
        .join(Location, Location.id == ClientCurrencyLocation.location_id)
        .order_by(ClientCurrencyLocation.currency_code, Location.code)
    ).all()
    return [ClientCurrencyLocationOut(currency_code=ccy, location_code=loc) for ccy, loc in rows]


@router.get("/reference/accounts", response_model=list[AccountOut])
def list_accounts(db: OrmSession = Depends(get_db)) -> list[AccountOut]:
    """حسابات قابلة للترحيل مباشرة لاختيار «الحساب المنفِّذ»/المصدر/التحصيل
    (هـ-١): أوراق الشجرة فقط، بلا حسابات عملاء (تُشتق آلياً، لا تُختار)."""
    all_accounts = db.execute(select(Account).where(Account.is_active.is_(True))).scalars().all()
    parent_ids = {a.parent_id for a in all_accounts if a.parent_id is not None}
    locations = {loc.id: loc.code for loc in db.execute(select(Location)).scalars().all()}
    leaves = [a for a in all_accounts if a.id not in parent_ids and a.client_id is None]
    return [
        AccountOut(
            code=a.code, name_ar=a.name_ar, type=a.type.value, currency_code=a.currency_code,
            location_code=locations.get(a.location_id) if a.location_id else None,
            form=a.form.value if a.form else None,
        )
        for a in sorted(leaves, key=lambda x: x.code)
    ]


@router.get("/clients/search", response_model=list[ClientSearchResultOut])
def search_clients(
    q: str = Query(min_length=1), limit: int = Query(default=20, le=50), db: OrmSession = Depends(get_db)
) -> list[ClientSearchResultOut]:
    pattern = f"%{q}%"
    rows = db.execute(
        select(Client)
        .where(
            Client.is_active.is_(True),
            (Client.name_ar.ilike(pattern)) | (Client.code.ilike(pattern)) | (Client.phone.ilike(pattern)),
        )
        .order_by(Client.name_ar)
        .limit(limit)
    ).scalars().all()
    return [
        ClientSearchResultOut(id=c.id, code=c.code, name_ar=c.name_ar, phone=c.phone, credit_allowed=c.credit_allowed)
        for c in rows
    ]


@router.get(
    "/clients/{client_id}/balances", response_model=list[ClientBalanceOut],
    dependencies=[Depends(require_role(Action.POST_ENTRY))],
)
def client_balances(client_id: int, db: OrmSession = Depends(get_db)) -> list[ClientBalanceOut]:
    """هـ-١: أرصدة العميل بمستوى **الموقع** — كل حساب 2100-{code}-{ccy}-{loc} سطر مستقل.

    §٩ المرحلة ١٢: بيانات مالية للعميل — نفس حاجز `POST_ENTRY` لكل مسارات
    بيانات العميل في `clients.py` (كان `require_password_changed` فقط —
    لا فرق فعلي اليوم إذ `POST_ENTRY`={مدير،محاسب}=كل أدوار الموظفين، لكن
    الاتساق يمنع تسرّباً لو أُضيف دور موظف للقراءة فقط لاحقاً)."""
    if db.get(Client, client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عميل بالمعرّف {client_id}")
    locations = {loc.id: loc.code for loc in db.execute(select(Location)).scalars().all()}
    rows = db.execute(
        select(Account, AccountBalance)
        .join(AccountBalance, AccountBalance.account_id == Account.id)
        .where(Account.client_id == client_id)
        .order_by(Account.currency_code, Account.code)
    ).all()
    return [
        ClientBalanceOut(
            account_code=acc.code, currency_code=acc.currency_code,
            location_code=locations.get(acc.location_id) if acc.location_id else None, balance=bal.balance,
        )
        for acc, bal in rows
    ]


@router.get("/reference/swift-movements/pending", response_model=list[PendingSwiftMovementOut])
def list_pending_swift_movements(db: OrmSession = Depends(get_db)) -> list[PendingSwiftMovementOut]:
    """حركات SENT لم تُستقبَل ولم تُرتجَع بعد — ما يحتاجه اختيار SWIFT_IN/
    SWIFT_RETURN في الواجهة. الشريك واسم قيد الخروج مُشتقّان عبر out_entry_id."""
    movements = db.execute(
        select(SwiftMovement).where(SwiftMovement.status == SwiftStatus.SENT).order_by(SwiftMovement.transfer_date)
    ).scalars().all()
    if not movements:
        return []
    out_entry_ids = {m.out_entry_id for m in movements if m.out_entry_id is not None}
    entries = {e.id: e for e in db.execute(select(JournalEntry).where(JournalEntry.id.in_(out_entry_ids))).scalars().all()}
    partner_ids = {e.partner_id for e in entries.values() if e.partner_id is not None}
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(partner_ids))).scalars().all()}

    # الحساب المراسل الأصلي = طرف قيد SWIFT_OUT غير "1501" — يُشتق هنا لا
    # يُختار في الواجهة (SWIFT_RETURN بلا حقل اختيار حساب إطلاقاً).
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id.in_(out_entry_ids))).scalars().all() if out_entry_ids else []
    line_account_ids = {ln.account_id for ln in lines}
    line_accounts = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(line_account_ids))).scalars().all()}
    lines_by_entry: dict[int, list[JournalLine]] = {}
    for ln in lines:
        lines_by_entry.setdefault(ln.entry_id, []).append(ln)
    partner_account_code_by_entry: dict[int, Optional[str]] = {}
    for entry_id, entry_lines in lines_by_entry.items():
        candidates = [
            line_accounts[ln.account_id].code
            for ln in entry_lines
            if line_accounts[ln.account_id].code != "1501"
        ]
        partner_account_code_by_entry[entry_id] = candidates[0] if len(candidates) == 1 else None

    result = []
    for m in movements:
        entry = entries.get(m.out_entry_id) if m.out_entry_id else None
        partner = partners.get(entry.partner_id) if entry and entry.partner_id else None
        result.append(
            PendingSwiftMovementOut(
                id=m.id, amount=m.amount, currency_code=m.currency_code, transfer_date=m.transfer_date,
                external_ref=m.external_ref, partner_name_ar=partner.name_ar if partner else None,
                out_entry_no=entry.entry_no if entry else None,
                partner_account_code=partner_account_code_by_entry.get(m.out_entry_id) if m.out_entry_id else None,
            )
        )
    return result


@router.get("/reference/accounts/for-operation", response_model=list[AccountOut])
def list_accounts_for_operation(
    operation_type: str = Query(...),
    field: str = Query(...),
    currency_code: str = Query(...),
    location_code: Optional[str] = Query(default=None),
    db: OrmSession = Depends(get_db),
) -> list[AccountOut]:
    """حسابات مُصفّاة بحسب (نوع العملية × دور الحقل × العملة × الموقع) —
    لا شجرة الحسابات كاملة. **استثناء مقصود**: OPENING/ADJUSTMENT لا يمرّان
    من هنا إطلاقاً — يستخدمان `/reference/accounts` غير المُصفّى (انظر
    التوثيق الكامل في `app/engine/account_filters.py`)."""
    try:
        accounts = account_filters.accounts_for_operation(
            db, operation_type=operation_type, field=field, currency_code=currency_code, location_code=location_code,
        )
    except account_filters.InvalidAccountFieldError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except account_filters.LocationRequiredError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    locations = {loc.id: loc.code for loc in db.execute(select(Location)).scalars().all()}
    return [
        AccountOut(
            code=a.code, name_ar=a.name_ar, type=a.type.value, currency_code=a.currency_code,
            location_code=locations.get(a.location_id) if a.location_id else None,
            form=a.form.value if a.form else None,
        )
        for a in accounts
    ]


@router.get("/journal/entries", response_model=list[JournalEntryOut])
def list_journal_entries(
    entry_date_filter: Optional[date] = Query(default=None, alias="date"),
    limit: int = Query(default=30, le=100),
    include_reversed: bool = Query(default=False, description="أظهر الملغاة (REVERSED) — مخفية افتراضياً"),
    db: OrmSession = Depends(get_db),
) -> list[JournalEntryOut]:
    """عمود دفتر اليومية اليسار (ح-٢): عمليات اليوم افتراضياً، أو تاريخ محدَّد.

    افتراضياً: لا قيود ملغاة (`REVERSED`) ولا قيود العكس الداخلية نفسها
    (`reverses_entry_id` غير فارغ) — كلاهما ضجيج محاسبي لا عملية يومية
    حقيقية. `include_reversed=true` يعيدهما لمن يحتاج الأرشيف الكامل.
    """
    target_date = entry_date_filter or local_entry_date(system_clock(), settings.work_timezone)
    query = select(JournalEntry).where(JournalEntry.entry_date == target_date)
    if not include_reversed:
        query = query.where(JournalEntry.status != EntryStatus.REVERSED, JournalEntry.reverses_entry_id.is_(None))
    entries = db.execute(query.order_by(JournalEntry.id.desc()).limit(limit)).scalars().all()
    if not entries:
        return []

    entry_ids = [e.id for e in entries]
    lines = db.execute(select(JournalLine).where(JournalLine.entry_id.in_(entry_ids))).scalars().all()
    account_ids = {ln.account_id for ln in lines}
    accounts = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()}
    lines_by_entry: dict[int, list[JournalLine]] = {}
    for ln in lines:
        lines_by_entry.setdefault(ln.entry_id, []).append(ln)

    client_ids = {e.client_id for e in entries if e.client_id is not None}
    clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()}

    result = []
    for e in entries:
        entry_lines = sorted(lines_by_entry.get(e.id, []), key=lambda ln: ln.line_no)
        result.append(
            JournalEntryOut(
                id=e.id, entry_no=e.entry_no, entry_date=e.entry_date, operation_type=e.operation_type.value,
                status=e.status.value, description=e.description, note=e.note, replaces_entry_id=e.replaces_entry_id,
                client_id=e.client_id,
                client_name_ar=clients[e.client_id].name_ar if e.client_id in clients else None,
                profit_amount=e.profit_amount, profit_currency=e.profit_currency, chain_ref=e.chain_ref,
                lines=[
                    JournalLineOut(
                        account_code=accounts[ln.account_id].code, account_name_ar=accounts[ln.account_id].name_ar,
                        currency_code=ln.currency_code, debit=ln.debit, credit=ln.credit, memo=ln.memo,
                    )
                    for ln in entry_lines
                ],
            )
        )
    return result

"""التقارير (§٧-١١) — قراءة فقط. ربحية الدفعات مُغطّاة أصلاً بـ`GET /lots`
(المرحلة ٨، كل دفعة = ربحية سويفت بعينه) فلا مسار مكرَّر لها هنا.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import accounts_repo, recompute
from app.models import (
    Account,
    AccountBalance,
    AuditLog,
    Client,
    JournalEntry,
    JournalLine,
    OpeningBalance,
    OpeningReconciliation,
    Partner,
    SwiftMovement,
    User,
)
from app.models.enums import AccountType, EntryStatus, OperationType, ReconciliationStatus
from app.routers.dashboard import (
    _TRANSFER_FEE_OPS,
    _group_currency_amounts,
    _is_client_facing_spread,
)
from app.schemas.reports import (
    ActivityRow,
    BalanceOverrideRow,
    ClientProfitabilityRow,
    CorrespondentActivityRow,
    CurrencyAmount,
    DebtsByCurrencyRow,
    EmergencyEntryRow,
    FoundingReconciliationResponse,
    IncomeStatementLine,
    IncomeStatementResponse,
    LossMakingEntryRow,
    ProfitByPeriodRow,
    SwiftHistoryRow,
    TrialBalanceResponse,
    TrialBalanceRow,
)
from app.security.deps import require_password_changed

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_password_changed)])


@router.get("/debts-by-currency", response_model=list[DebtsByCurrencyRow])
def debts_by_currency(db: OrmSession = Depends(get_db)) -> list[DebtsByCurrencyRow]:
    balances = {row.account_id: row.balance for row in db.execute(select(AccountBalance)).scalars()}
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=True)
    per_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    clients_per_currency: dict[str, set[int]] = defaultdict(set)
    for a in leaves:
        if a.type == AccountType.LIABILITY and a.client_id is not None and a.currency_code is not None:
            bal = balances.get(a.id, Decimal("0"))
            if bal > 0:
                per_currency[a.currency_code] += bal
                clients_per_currency[a.currency_code].add(a.client_id)
    return [
        DebtsByCurrencyRow(currency_code=ccy, total_owed=amount, client_count=len(clients_per_currency[ccy]))
        for ccy, amount in sorted(per_currency.items())
    ]


@router.get("/profit-by-period", response_model=list[ProfitByPeriodRow])
def profit_by_period(
    granularity: str = Query(default="monthly", pattern="^(weekly|monthly|yearly)$"),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    db: OrmSession = Depends(get_db),
) -> list[ProfitByPeriodRow]:
    query = select(JournalEntry).where(JournalEntry.status == EntryStatus.POSTED, JournalEntry.profit_amount.isnot(None))
    if date_from:
        query = query.where(JournalEntry.entry_date >= date_from)
    if date_to:
        query = query.where(JournalEntry.entry_date <= date_to)
    entries = db.execute(query).scalars().all()

    def period_key(d: date) -> str:
        if granularity == "yearly":
            return str(d.year)
        if granularity == "weekly":
            iso = d.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        return f"{d.year}-{d.month:02d}"

    by_period: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        by_period[period_key(e.entry_date)].append(e)

    rows = []
    for period, period_entries in sorted(by_period.items()):
        transfer_pairs = [(e.profit_currency, e.profit_amount) for e in period_entries if e.operation_type in _TRANSFER_FEE_OPS and e.profit_currency]
        exchange_pairs = [(e.profit_currency, e.profit_amount) for e in period_entries if _is_client_facing_spread(e) and e.profit_currency]
        transfer_totals = _group_currency_amounts(transfer_pairs)
        exchange_totals = _group_currency_amounts(exchange_pairs)
        net_pairs = (
            [(c.currency_code, c.amount) for c in transfer_totals]
            + [(c.currency_code, c.amount) for c in exchange_totals]
        )
        rows.append(ProfitByPeriodRow(
            period_label=period, transfer_fee=transfer_totals, exchange_spread=exchange_totals,
            net_by_currency=_group_currency_amounts(net_pairs),
        ))
    return rows


@router.get("/trial-balance", response_model=TrialBalanceResponse)
def trial_balance(db: OrmSession = Depends(get_db)) -> TrialBalanceResponse:
    """ميزان المراجعة — من `recompute.compute_true_balances` مباشرة (نفس
    مصدر الحقيقة المستخدَم في `python -m app.cli recompute-balances`)،
    لا من `account_balances` المخزَّن (قد يتأخر نظرياً، هذا يُعيد الحساب
    من `journal_lines` فعلياً في كل استدعاء)."""
    true_balances = recompute.compute_true_balances(db)
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=True)
    leaves_by_id = {a.id: a for a in leaves}

    rows = []
    debit_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    credit_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for account_id, signed_balance in true_balances.items():
        account = leaves_by_id.get(account_id)
        if account is None or signed_balance == 0:
            continue
        # signed_balance موجب = جهة الرصيد الطبيعية للحساب (دائن لالتزامات/
        # حقوق ملكية/إيرادات، مدين لغير ذلك) — سالب يعني الحساب انعكس عن
        # جهته الطبيعية (مسموح فعلياً، مثل رصيد سالب مُصرَّح به).
        is_credit_normal = account.type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE)
        if is_credit_normal:
            credit = signed_balance if signed_balance >= 0 else Decimal("0")
            debit = -signed_balance if signed_balance < 0 else Decimal("0")
        else:
            debit = signed_balance if signed_balance >= 0 else Decimal("0")
            credit = -signed_balance if signed_balance < 0 else Decimal("0")
        rows.append(TrialBalanceRow(
            account_code=account.code, account_name_ar=account.name_ar, account_type=account.type.value,
            currency_code=account.currency_code, debit=debit, credit=credit,
        ))
        if account.currency_code:
            debit_totals[account.currency_code] += debit
            credit_totals[account.currency_code] += credit

    balanced = all(debit_totals[c] == credit_totals[c] for c in set(debit_totals) | set(credit_totals))
    return TrialBalanceResponse(
        rows=sorted(rows, key=lambda r: r.account_code),
        total_debit_by_currency=[CurrencyAmount(currency_code=c, amount=a) for c, a in sorted(debit_totals.items())],
        total_credit_by_currency=[CurrencyAmount(currency_code=c, amount=a) for c, a in sorted(credit_totals.items())],
        balanced=balanced,
    )


@router.get("/income-statement", response_model=IncomeStatementResponse)
def income_statement(db: OrmSession = Depends(get_db)) -> IncomeStatementResponse:
    true_balances = recompute.compute_true_balances(db)
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=False)
    revenue, expense = [], []
    net: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for a in leaves:
        bal = true_balances.get(a.id, Decimal("0"))
        if bal == 0 or a.currency_code is None:
            continue
        if a.type == AccountType.REVENUE:
            revenue.append(IncomeStatementLine(account_code=a.code, account_name_ar=a.name_ar, currency_code=a.currency_code, amount=bal))
            net[a.currency_code] += bal
        elif a.type == AccountType.EXPENSE:
            expense.append(IncomeStatementLine(account_code=a.code, account_name_ar=a.name_ar, currency_code=a.currency_code, amount=bal))
            net[a.currency_code] -= bal
    return IncomeStatementResponse(
        revenue=sorted(revenue, key=lambda r: r.account_code), expense=sorted(expense, key=lambda r: r.account_code),
        net_by_currency=[CurrencyAmount(currency_code=c, amount=a) for c, a in sorted(net.items())],
    )


@router.get("/client-profitability", response_model=list[ClientProfitabilityRow])
def client_profitability(db: OrmSession = Depends(get_db)) -> list[ClientProfitabilityRow]:
    entries = db.execute(
        select(JournalEntry).where(
            JournalEntry.status == EntryStatus.POSTED, JournalEntry.profit_amount.isnot(None), JournalEntry.client_id.isnot(None),
        )
    ).scalars().all()
    per_client: dict[int, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        per_client[e.client_id].append(e)
    if not per_client:
        return []
    clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(per_client.keys()))).scalars().all()}
    rows = []
    for client_id, client_entries in per_client.items():
        client = clients.get(client_id)
        if client is None:
            continue
        pairs = [(e.profit_currency, e.profit_amount) for e in client_entries if e.profit_currency]
        rows.append(ClientProfitabilityRow(
            client_id=client_id, client_code=client.code, client_name_ar=client.name_ar,
            profit_by_currency=_group_currency_amounts(pairs), operation_count=len(client_entries),
        ))
    return sorted(rows, key=lambda r: r.client_name_ar)


@router.get("/activity-by-currency", response_model=list[ActivityRow])
def activity_by_currency(db: OrmSession = Depends(get_db)) -> list[ActivityRow]:
    rows = db.execute(
        select(JournalLine.currency_code, JournalLine.entry_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.status == EntryStatus.POSTED)
        .distinct()
    ).all()
    counts: dict[str, set[int]] = defaultdict(set)
    for ccy, entry_id in rows:
        counts[ccy].add(entry_id)
    return sorted(
        [ActivityRow(key=ccy, entry_count=len(ids)) for ccy, ids in counts.items()],
        key=lambda r: r.entry_count, reverse=True,
    )


@router.get("/activity-by-month", response_model=list[ActivityRow])
def activity_by_month(db: OrmSession = Depends(get_db)) -> list[ActivityRow]:
    entries = db.execute(select(JournalEntry.entry_date).where(JournalEntry.status == EntryStatus.POSTED)).scalars().all()
    counts: dict[str, int] = defaultdict(int)
    for d in entries:
        counts[f"{d.year}-{d.month:02d}"] += 1
    return sorted([ActivityRow(key=k, entry_count=v) for k, v in counts.items()], key=lambda r: r.key)


@router.get("/correspondent-activity", response_model=list[CorrespondentActivityRow])
def correspondent_activity(db: OrmSession = Depends(get_db)) -> list[CorrespondentActivityRow]:
    partner_accounts = db.execute(select(Account).where(Account.partner_id.isnot(None))).scalars().all()
    account_ids_by_partner: dict[int, list[int]] = defaultdict(list)
    for a in partner_accounts:
        account_ids_by_partner[a.partner_id].append(a.id)
    if not account_ids_by_partner:
        return []
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(account_ids_by_partner.keys()))).scalars().all()}

    rows = []
    for partner_id, account_ids in account_ids_by_partner.items():
        partner = partners.get(partner_id)
        if partner is None:
            continue
        lines = db.execute(
            select(JournalLine)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(JournalLine.account_id.in_(account_ids), JournalEntry.status == EntryStatus.POSTED)
        ).scalars().all()
        debit_pairs = [(ln.currency_code, ln.debit) for ln in lines if ln.debit > 0]
        credit_pairs = [(ln.currency_code, ln.credit) for ln in lines if ln.credit > 0]
        entry_ids = {ln.entry_id for ln in lines}
        rows.append(CorrespondentActivityRow(
            partner_id=partner_id, partner_name_ar=partner.name_ar, entry_count=len(entry_ids),
            total_debit_by_currency=_group_currency_amounts(debit_pairs), total_credit_by_currency=_group_currency_amounts(credit_pairs),
        ))
    return sorted(rows, key=lambda r: r.partner_name_ar)


@router.get("/swift-history", response_model=list[SwiftHistoryRow])
def swift_history(db: OrmSession = Depends(get_db)) -> list[SwiftHistoryRow]:
    """كل حركات السويفت بحالاتها كلها — بخلاف `/reference/swift-movements/pending`
    (المعلَّقة SENT فقط، لاختيار SWIFT_IN/SWIFT_RETURN)."""
    movements = db.execute(select(SwiftMovement).order_by(SwiftMovement.transfer_date.desc())).scalars().all()
    if not movements:
        return []
    out_entry_ids = {m.out_entry_id for m in movements if m.out_entry_id is not None}
    entries = {e.id: e for e in db.execute(select(JournalEntry).where(JournalEntry.id.in_(out_entry_ids))).scalars().all()} if out_entry_ids else {}
    partner_ids = {e.partner_id for e in entries.values() if e.partner_id is not None}
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(partner_ids))).scalars().all()} if partner_ids else {}
    result = []
    for m in movements:
        entry = entries.get(m.out_entry_id) if m.out_entry_id else None
        partner = partners.get(entry.partner_id) if entry and entry.partner_id else None
        result.append(SwiftHistoryRow(
            id=m.id, status=m.status.value, amount=m.amount, currency_code=m.currency_code,
            transfer_date=m.transfer_date, received_date=m.received_date, external_ref=m.external_ref,
            partner_name_ar=partner.name_ar if partner else None,
        ))
    return result


@router.get("/loss-making-operations", response_model=list[LossMakingEntryRow])
def loss_making_operations(db: OrmSession = Depends(get_db)) -> list[LossMakingEntryRow]:
    entries = db.execute(
        select(JournalEntry).where(
            JournalEntry.status == EntryStatus.POSTED, JournalEntry.profit_amount < 0,
        ).order_by(JournalEntry.entry_date.desc())
    ).scalars().all()
    if not entries:
        return []
    client_ids = {e.client_id for e in entries if e.client_id is not None}
    clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()} if client_ids else {}
    return [
        LossMakingEntryRow(
            entry_id=e.id, entry_no=e.entry_no, entry_date=e.entry_date, operation_type=e.operation_type.value,
            client_name_ar=clients[e.client_id].name_ar if e.client_id in clients else None,
            profit_amount=e.profit_amount, profit_currency=e.profit_currency or "?",
        )
        for e in entries
    ]


_OVERRIDE_ACTIONS = ("CREDIT_LIMIT_OVERRIDE", "NEGATIVE_BALANCE_OVERRIDE")


@router.get("/balance-overrides", response_model=list[BalanceOverrideRow])
def balance_overrides(db: OrmSession = Depends(get_db)) -> list[BalanceOverrideRow]:
    rows = db.execute(
        select(AuditLog).where(AuditLog.action.in_(_OVERRIDE_ACTIONS)).order_by(AuditLog.at.desc())
    ).scalars().all()
    if not rows:
        return []
    account_ids = {r.entity_id for r in rows if r.entity == "accounts" and r.entity_id is not None}
    accounts = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()} if account_ids else {}
    actor_ids = {r.actor_id for r in rows}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(actor_ids))).scalars().all()} if actor_ids else {}
    return [
        BalanceOverrideRow(
            id=r.id, created_at=r.at, action=r.action,
            account_code=accounts[r.entity_id].code if r.entity_id in accounts else None,
            entry_no=(r.after_json or {}).get("entry_no"), reason=(r.after_json or {}).get("reason"),
            actor_username=users[r.actor_id].username if r.actor_id in users else None,
        )
        for r in rows
    ]


@router.get("/emergency-entries", response_model=list[EmergencyEntryRow])
def emergency_entries(db: OrmSession = Depends(get_db)) -> list[EmergencyEntryRow]:
    entries = db.execute(
        select(JournalEntry).where(JournalEntry.outage_mode.is_(True)).order_by(JournalEntry.entry_date.desc())
    ).scalars().all()
    return [
        EmergencyEntryRow(
            entry_id=e.id, entry_no=e.entry_no, entry_date=e.entry_date, operation_type=e.operation_type.value,
            real_operation_time=e.real_operation_time, backdate_reason=e.backdate_reason,
        )
        for e in entries
    ]


@router.get("/founding-reconciliation", response_model=FoundingReconciliationResponse)
def founding_reconciliation(db: OrmSession = Depends(get_db)) -> FoundingReconciliationResponse:
    true_balances = recompute.compute_true_balances(db)
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=True)
    # حسابات ٣٩٠٠ الفرعية لكل عملة تُرقَّم تسلسلياً (٣٩٠١، ٣٩٠٢...) لا بادئة
    # نصية "3900" — المطابقة عبر parent_id لا startswith (نفس تصحيح لوحة التحكم).
    suspense_parent = db.execute(select(Account).where(Account.code == "3900")).scalar_one_or_none()
    suspense_pairs = [
        (a.currency_code, true_balances.get(a.id, Decimal("0")))
        for a in leaves
        if suspense_parent is not None and a.parent_id == suspense_parent.id
        and a.currency_code and true_balances.get(a.id, Decimal("0")) != 0
    ]
    opening_rows = db.execute(select(OpeningBalance)).scalars().all()
    opening_pairs = [(r.currency_code, r.amount) for r in opening_rows]
    open_items = db.execute(
        select(OpeningReconciliation).where(OpeningReconciliation.status == ReconciliationStatus.OPEN)
    ).scalars().all()
    return FoundingReconciliationResponse(
        suspense_balance_by_currency=_group_currency_amounts(suspense_pairs),
        opening_balances_total_by_currency=_group_currency_amounts(opening_pairs),
        opening_balances_count=len(opening_rows),
        open_reconciliation_items=len(open_items),
    )

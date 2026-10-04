"""لوحة التحكم · مركز السيولة · الحسابات · الدفعات (§٧-٢، ٧-٤، ٧-٧، ٧-٨) —
قراءة فقط، لا منطق محاسبي هنا.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Optional

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import accounts_repo
from app.engine.clock import local_entry_date, system_clock
from app.config import settings
from app.models import (
    Account,
    AccountBalance,
    AuditLog,
    Client,
    ClientCreditLimit,
    CurrencyLot,
    JournalEntry,
    LotConsumption,
    Location,
    Partner,
    Setting,
    SwiftMovement,
    User,
)
from app.models.enums import AccountForm, AccountType, EntryStatus, OperationType, SwiftStatus
from app.schemas.dashboard import (
    AccountBalanceRow,
    AlertRow,
    BanksResponse,
    BoxesResponse,
    CorrespondentGroup,
    CorrespondentsResponse,
    CurrencyAmount,
    DashboardKpis,
    DashboardSummary,
    LiquidityRow,
    LotConsumptionRow,
    LotDetail,
    LotRow,
    ProfitBreakdown,
    TopClientRow,
)
from app.schemas.reference import JournalEntryOut
from app.security import backup_codes
from app.security.deps import get_current_user, require_password_changed

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_password_changed)])

_TRANSFER_FEE_OPS = {OperationType.CASH_TRANSFER}
_EXCHANGE_SPREAD_OPS = {OperationType.EXCHANGE, OperationType.REMIT_OUT}
_LIBYA_BOX_PARENT_CODE = "1100"


# ٢٠٢٦-١٠-٠٢: صرافة الخزينة (EXCHANGE بلا client_id) بسعر واحد — لا ربح ولا خسارة
# فيها (قرار مالك)، فلا عمود/حقل «ربح الخزينة» في أي تقرير (حُذف `treasury_exchange`).
# قيودها بلا `profit_amount` فلا تدخل أي تجميع ربح أصلاً.
def _is_client_facing_spread(e: JournalEntry) -> bool:
    return e.operation_type in _EXCHANGE_SPREAD_OPS


def _commission_pairs(entries) -> list[tuple[str, Decimal]]:
    """عمولة الصرافة موقَّعة: نقبضها (IN) + · ندفعها (OUT) − ، بعملتها (٢٠٢٦-١٠-٠٤)."""
    return [
        (e.commission_currency, e.commission_amount if e.commission_direction == "IN" else -e.commission_amount)
        for e in entries if e.commission_amount is not None and e.commission_currency
    ]


def _balances_by_account(db: OrmSession) -> dict[int, Decimal]:
    return {row.account_id: row.balance for row in db.execute(select(AccountBalance)).scalars()}


def _group_currency_amounts(pairs: list[tuple[str, Decimal]]) -> list[CurrencyAmount]:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for ccy, amount in pairs:
        totals[ccy] += amount
    return [CurrencyAmount(currency_code=c, amount=a) for c, a in sorted(totals.items())]


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(db: OrmSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> DashboardSummary:
    balances = _balances_by_account(db)
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=True)

    funds_pairs: list[tuple[str, Decimal]] = []
    liabilities_pairs: list[tuple[str, Decimal]] = []
    debts_pairs: list[tuple[str, Decimal]] = []
    for a in leaves:
        if a.currency_code is None:
            continue
        bal = balances.get(a.id, Decimal("0"))
        if a.type == AccountType.ASSET and a.form in (AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT):
            funds_pairs.append((a.currency_code, bal))
        elif a.type == AccountType.LIABILITY and a.client_id is not None:
            liabilities_pairs.append((a.currency_code, bal))
            if bal < 0:
                debts_pairs.append((a.currency_code, -bal))
    kpis = DashboardKpis(
        funds=_group_currency_amounts(funds_pairs),
        client_liabilities=_group_currency_amounts(liabilities_pairs),
        client_debts=_group_currency_amounts(debts_pairs),
    )

    today = local_entry_date(system_clock(), settings.work_timezone)
    today_entries = db.execute(
        select(JournalEntry).where(
            JournalEntry.entry_date == today, JournalEntry.status == EntryStatus.POSTED,
            or_(JournalEntry.profit_amount.isnot(None), JournalEntry.commission_amount.isnot(None)),
        )
    ).scalars().all()
    transfer_pairs = [
        (e.profit_currency, e.profit_amount) for e in today_entries if e.operation_type in _TRANSFER_FEE_OPS and e.profit_currency
    ]
    exchange_pairs = [
        (e.profit_currency, e.profit_amount) for e in today_entries if _is_client_facing_spread(e) and e.profit_currency
    ]
    transfer_totals = _group_currency_amounts(transfer_pairs)
    exchange_totals = _group_currency_amounts(exchange_pairs)
    commission_pairs = _commission_pairs(today_entries)
    net_pairs = (
        [(c.currency_code, c.amount) for c in transfer_totals]
        + [(c.currency_code, c.amount) for c in exchange_totals]
        + commission_pairs  # العمولة تدخل الصافي لكل عملة وتبقى بنداً مستقلاً ظاهراً (٢٠٢٦-١٠-٠٤)
    )
    today_profit = ProfitBreakdown(
        transfer_fee=transfer_totals, exchange_spread=exchange_totals,
        net_by_currency=_group_currency_amounts(net_pairs),
        exchange_commission=_group_currency_amounts(commission_pairs),
    )

    # أفضل ٥ عملاء — معيار الترتيب: عدد القيود المُرحَّلة (POSTED) التي شارك
    # فيها العميل، لا رصيد. رصيد مطلق يجمع دينار مع دولار مع رمبي في رقم
    # واحد بلا سعر صرف موثوق (نفس المبدأ الموثَّق في app/schemas/dashboard.py).
    top_client_counts = db.execute(
        select(JournalEntry.client_id, func.count(JournalEntry.id).label("op_count"))
        .where(JournalEntry.client_id.isnot(None), JournalEntry.status == EntryStatus.POSTED)
        .group_by(JournalEntry.client_id)
        .order_by(func.count(JournalEntry.id).desc())
        .limit(5)
    ).all()
    top_client_ids = [row.client_id for row in top_client_counts]
    clients_by_id = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(top_client_ids))).scalars().all()} if top_client_ids else {}
    top_clients = [
        TopClientRow(client_id=cid, code=clients_by_id[cid].code, name_ar=clients_by_id[cid].name_ar, operation_count=op_count)
        for cid, op_count in top_client_counts
        if cid in clients_by_id
    ]

    recent = db.execute(select(JournalEntry).order_by(JournalEntry.id.desc()).limit(10)).scalars().all()
    recent_client_ids = {e.client_id for e in recent if e.client_id is not None}
    recent_clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(recent_client_ids))).scalars().all()} if recent_client_ids else {}
    recent_entries = [
        JournalEntryOut(
            id=e.id, entry_no=e.entry_no, entry_date=e.entry_date, operation_type=e.operation_type.value,
            status=e.status.value, description=e.description,
            client_id=e.client_id,
            client_name_ar=recent_clients[e.client_id].name_ar if e.client_id in recent_clients else None,
            profit_amount=e.profit_amount, profit_currency=e.profit_currency, chain_ref=e.chain_ref, lines=[],
        )
        for e in recent
    ]

    alerts = _compute_alerts(db, leaves=leaves, balances=balances)
    alerts.extend(_backup_code_alerts(db, current_user))

    return DashboardSummary(
        kpis=kpis, today_profit=today_profit, top_clients=top_clients, recent_entries=recent_entries, alerts=alerts,
    )


_BACKUP_LOGIN_ALERT_DAYS = 7


def _backup_code_alerts(db: OrmSession, user: User) -> list[AlertRow]:
    """تنبيهات الرموز الاحتياطية (٢٠٢٦-١٠-٠٣): (١) رصيدك ٣ أو أقل ← إنشاء رموز جديدة؛ (٢) كل دخول برمز احتياطي خلال آخر ٧ أيام
    «دخول برمز احتياطي — متبقٍّ X» — المدير يرى كل المستخدمين (باسم المستخدم)، وغيره يرى دخوله هو فقط."""
    alerts: list[AlertRow] = []
    if user.totp_secret is not None:
        left = backup_codes.remaining(db, user_id=user.id)
        if left <= backup_codes.LOW_THRESHOLD:
            alerts.append(AlertRow(
                severity="critical" if left == 0 else "warning", code="backup_codes_low",
                message_ar=f"رموزك الاحتياطية المتبقية: {left} — أنشئ رموزاً جديدة من الإعدادات ← الأمان",
            ))
    since = system_clock() - timedelta(days=_BACKUP_LOGIN_ALERT_DAYS)
    query = select(AuditLog).where(AuditLog.action == "BACKUP_CODE_LOGIN", AuditLog.at >= since)
    if user.role != "ADMIN":
        query = query.where(AuditLog.entity_id == user.id)
    rows = db.execute(query.order_by(AuditLog.id.desc()).limit(5)).scalars().all()
    names = {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_({r.entity_id for r in rows}))).scalars()} if rows else {}
    for r in rows:
        left = (r.after_json or {}).get("remaining", "—")
        who = "" if r.entity_id == user.id else f" — {names.get(r.entity_id, r.entity_id)}"
        alerts.append(AlertRow(severity="warning", code="backup_code_login", message_ar=f"دخول برمز احتياطي — متبقٍّ {left}{who}"))
    return alerts


def _compute_alerts(db: OrmSession, *, leaves: list[Account], balances: dict[int, Decimal]) -> list[AlertRow]:
    alerts: list[AlertRow] = []

    # ٠) فحص السلامة اليومي المجدول (§٩، أهم إنذار في النظام) — قراءة
    # رخيصة لآخر نتيجة محفوظة (`app.cli.integrity_check`، `Setting`
    # key="last_integrity_check") بدل إعادة `recompute.verify` الكاملة
    # (مسح journal_lines بالكامل) عند كل تحميل شاشة. أول عنصر في القائمة
    # عمداً — أعلى أولوية.
    integrity = db.execute(select(Setting).where(Setting.key == "last_integrity_check")).scalar_one_or_none()
    if integrity is not None and not integrity.value.get("ok", True):
        diffs = integrity.value.get("balance_diff_count", 0)
        swift = integrity.value.get("swift_problem_count", 0)
        lots = integrity.value.get("lot_problem_count", 0)
        checked_at = integrity.value.get("checked_at", "")
        alerts.append(AlertRow(
            severity="critical", code="integrity_check_failed",
            message_ar=(
                f"فحص السلامة اليومي ({checked_at[:16]}) وجد اختلافاً حقيقياً: "
                f"{diffs} فرق رصيد · {swift} مشكلة سويفت · {lots} مشكلة دفعة — يستحق فحصاً فورياً"
            ),
        ))

    # ٠-ب) وصول النسخة الاحتياطية لوجهتها الخارجية خلال ٤٨ ساعة (§٩ المرحلة
    # ١٢) — بجانب تنبيه فحص السلامة مباشرة، نفس الأولوية: نسخة لم تصل
    # الوجهة الحقيقية أخطر من نسخة لم تُنشأ إطلاقاً (قد تُظَنّ آمنة خطأً).
    freshness = db.execute(select(Setting).where(Setting.key == "last_backup_freshness_check")).scalar_one_or_none()
    if freshness is not None and freshness.value.get("stale", False):
        alerts.append(AlertRow(
            severity="critical", code="backup_not_arrived",
            message_ar=f"النسخة الاحتياطية: {freshness.value.get('reason', 'لم تصل الوجهة الخارجية خلال المهلة')} — يستحق فحصاً فورياً",
        ))

    # ١) أرصدة سالبة — أصول الشركة/الشركاء غير حسابات المقاصة (§٥ قاعدة ٨:
    # قد تُصبح سالبة فعلياً بتجاوز مُصرَّح مُسجَّل، ليست علّة بالضرورة لكن
    # تستحق تنبيهاً دائماً).
    for a in leaves:
        if a.type == AccountType.ASSET and a.form != AccountForm.CLEARING and a.client_id is None:
            bal = balances.get(a.id, Decimal("0"))
            if bal < 0:
                alerts.append(AlertRow(
                    severity="critical", code="negative_balance",
                    message_ar=f"الحساب {a.code} ({a.name_ar}) برصيد سالب {bal}",
                ))

    # ٢) تجاوز حد الائتمان — نفس منطق _client_currency_total_deficit في
    # posting.py لكن للعرض فقط، مُجمَّع هنا مباشرة من الأرصدة المحسوبة.
    client_currency_deficit: dict[tuple[int, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for a in leaves:
        if a.client_id is not None and a.currency_code is not None:
            bal = balances.get(a.id, Decimal("0"))
            if bal < 0:
                client_currency_deficit[(a.client_id, a.currency_code)] += -bal
    if client_currency_deficit:
        client_ids = {cid for cid, _ in client_currency_deficit}
        clients_by_id = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()}
        limits = {
            (row.client_id, row.currency_code): row
            for row in db.execute(select(ClientCreditLimit).where(ClientCreditLimit.client_id.in_(client_ids))).scalars().all()
        }
        for (cid, ccy), deficit in client_currency_deficit.items():
            row = limits.get((cid, ccy))
            if row is not None and row.mode == "UNLIMITED":
                continue  # بلا سقف: لا تنبيه تجاوز — الرقابة في تقرير «العملاء المدينون» وإجمالي الديون
            limit = row.limit_amount if row is not None and row.mode == "LIMIT" else Decimal("0")
            if deficit > limit:
                client = clients_by_id.get(cid)
                alerts.append(AlertRow(
                    severity="critical", code="credit_exceeded",
                    message_ar=f"العميل {client.code if client else cid} تجاوز حد ائتمانه بعملة {ccy} ({deficit} > {limit})",
                ))

    # ٣) سويفت لم يصل — حركات SENT معلَّقة (بلا عتبة أيام؛ القائمة الكاملة
    # تظهر في شاشة الحسابات § التحويلات في الطريق).
    pending_swift = db.execute(select(SwiftMovement).where(SwiftMovement.status == SwiftStatus.SENT)).scalars().all()
    if pending_swift:
        alerts.append(AlertRow(
            severity="warning", code="swift_pending",
            message_ar=f"{len(pending_swift)} حركة سويفت لم تصل بعد",
        ))

    # ٤) مسودات معلَّقة — DRAFT لا يُفترَض أن يبقى ملتزَماً أبداً (كل عملية
    # تُرحَّل أو تُلغى ضمن معاملة واحدة)؛ ظهورها إشارة عطل حقيقي يستحق فحصاً.
    draft_count = db.execute(select(JournalEntry).where(JournalEntry.status == EntryStatus.DRAFT)).scalars().all()
    if draft_count:
        alerts.append(AlertRow(
            severity="critical", code="draft_pending",
            message_ar=f"{len(draft_count)} قيد بحالة مسودة لم يُرحَّل — يستحق فحصاً فورياً",
        ))

    # ٤-ب) فروق مطابقة غير مسوّاة لدى مراسل (§٧-٩) — رصيدك لدى الشركات
    # التركية هو المال الوحيد الذي ليس في يدك؛ فرق يبقى في شاشة المطابقة
    # وحدها كأنه غير موجود. الاتجاهان: سطر كشفهم بلا قيدك · قيدك بلا
    # سطرهم (الأخير أخطر — مالٌ تظنّه خرج ولم يخرج).
    from app.engine import reconciliation as _recon
    from app.models import Partner as _Partner, PartnerStatement as _Stmt

    statements = db.execute(select(_Stmt)).scalars().all()
    if statements:
        partner_names = {
            p.id: p.name_ar
            for p in db.execute(select(_Partner).where(_Partner.id.in_({s.partner_id for s in statements}))).scalars().all()
        }
        diff_by_partner: dict[int, tuple[int, int]] = defaultdict(lambda: (0, 0))
        for s in statements:
            d = _recon.statement_diff(db, s)
            prev = diff_by_partner[s.partner_id]
            diff_by_partner[s.partner_id] = (prev[0] + d.unmatched_statement_lines, prev[1] + d.unmatched_ledger_entries)
        for pid, (their_side, your_side) in diff_by_partner.items():
            if their_side + your_side == 0:
                continue
            name = partner_names.get(pid, str(pid))
            parts = []
            if their_side:
                parts.append(f"{their_side} في كشفهم بلا قيد عندك")
            if your_side:
                parts.append(f"{your_side} قيد عندك بلا سطر في كشفهم")
            alerts.append(AlertRow(
                severity="warning", code="reconciliation_difference",
                message_ar=f"فروق مطابقة غير مسوّاة لدى {name}: " + " · ".join(parts),
            ))

    # ٥) رصيد ٣٩٠٠ غير صفري — فروق تأسيسية تحت المصالحة.
    # ملاحظة: حسابات ٣٩٠٠ الفرعية لكل عملة تُرقَّم تسلسلياً (٣٩٠١، ٣٩٠٢...)
    # لا بادئة نصية "3900" — المطابقة عبر parent_id لا startswith.
    suspense_parent = db.execute(select(Account).where(Account.code == "3900")).scalar_one_or_none()
    suspense_accounts = [a for a in leaves if suspense_parent is not None and a.parent_id == suspense_parent.id]
    suspense_total = sum((balances.get(a.id, Decimal("0")) for a in suspense_accounts), Decimal("0"))
    if suspense_total != 0:
        alerts.append(AlertRow(
            severity="info", code="suspense_nonzero",
            message_ar=f"رصيد فروق التأسيس (٣٩٠٠) غير صفري: {suspense_total}",
        ))

    return alerts


@router.get("/position/liquidity", response_model=list[LiquidityRow])
def liquidity_position(db: OrmSession = Depends(get_db)) -> list[LiquidityRow]:
    """§٧-٤ — أهم تقرير في النظام: أصولي مقابل التزاماتي في كل (عملة×موقع).
    حسابات بلا موقع (١٩٠٠ مقاصة، ١٥٠١ في الطريق، ١١٠٤ بلا موقع محدَّد بعد —
    انظر قرار المالك المعلَّق) مُستبعدة عمداً: لا تمثّل التزاماً تجاه عميل
    ينتظر تسليماً في موقع بعينه."""
    balances = _balances_by_account(db)
    leaves = accounts_repo.leaf_accounts(db, include_client_accounts=True)
    locations = {loc.id: loc for loc in db.execute(select(Location)).scalars().all()}

    agg: dict[tuple[str, int], dict[str, Decimal]] = defaultdict(lambda: {"assets": Decimal("0"), "liabilities": Decimal("0")})
    for a in leaves:
        if a.location_id is None or a.currency_code is None:
            continue
        if a.type not in (AccountType.ASSET, AccountType.LIABILITY):
            continue
        bal = balances.get(a.id, Decimal("0"))
        key = (a.currency_code, a.location_id)
        if a.type == AccountType.ASSET:
            agg[key]["assets"] += bal
        else:
            agg[key]["liabilities"] += bal

    rows = []
    for (ccy, loc_id), sums in agg.items():
        loc = locations.get(loc_id)
        net = sums["assets"] - sums["liabilities"]
        rows.append(LiquidityRow(
            currency_code=ccy, location_code=loc.code if loc else "?", location_name_ar=loc.name_ar if loc else "?",
            assets=sums["assets"], liabilities=sums["liabilities"], net=net,
        ))
    return sorted(rows, key=lambda r: (r.currency_code, r.location_code))


@router.get("/accounts/boxes", response_model=BoxesResponse)
def accounts_boxes(db: OrmSession = Depends(get_db)) -> BoxesResponse:
    """§٧-٧ صناديق ليبيا — كل أبناء ١١٠٠ مباشرة (نقدي/مصرفي محلي)."""
    balances = _balances_by_account(db)
    parent = db.execute(select(Account).where(Account.code == _LIBYA_BOX_PARENT_CODE)).scalar_one_or_none()
    if parent is None:
        return BoxesResponse(accounts=[], totals=[])
    children = db.execute(
        select(Account).where(Account.parent_id == parent.id, Account.is_active.is_(True))
    ).scalars().all()
    rows = [
        AccountBalanceRow(code=a.code, name_ar=a.name_ar, currency_code=a.currency_code or "?", balance=balances.get(a.id, Decimal("0")))
        for a in sorted(children, key=lambda x: x.code)
    ]
    totals = _group_currency_amounts([(r.currency_code, r.balance) for r in rows])
    return BoxesResponse(accounts=rows, totals=totals)


@router.get("/accounts/correspondents", response_model=CorrespondentsResponse)
def accounts_correspondents(db: OrmSession = Depends(get_db)) -> CorrespondentsResponse:
    """§٧-٧ مراسلو تركيا — الإجمالي وتحته كل شركة."""
    balances = _balances_by_account(db)
    turkey = db.execute(select(Location).where(Location.code == "TURKEY")).scalar_one_or_none()
    accounts = accounts_repo.leaf_accounts(db, include_client_accounts=False)
    correspondents = [
        a for a in accounts if a.form == AccountForm.CORRESPONDENT and (turkey is None or a.location_id == turkey.id)
    ]
    partner_ids = {a.partner_id for a in correspondents if a.partner_id is not None}
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(partner_ids))).scalars().all()} if partner_ids else {}

    by_partner: dict[Optional[int], list[Account]] = defaultdict(list)
    for a in correspondents:
        by_partner[a.partner_id].append(a)

    groups = []
    for partner_id, accts in by_partner.items():
        partner = partners.get(partner_id) if partner_id else None
        rows = [
            AccountBalanceRow(code=a.code, name_ar=a.name_ar, currency_code=a.currency_code or "?", balance=balances.get(a.id, Decimal("0")))
            for a in sorted(accts, key=lambda x: x.code)
        ]
        groups.append(CorrespondentGroup(
            partner_id=partner_id, partner_name_ar=partner.name_ar if partner else "بلا شريك مسجَّل", accounts=rows,
        ))
    groups.sort(key=lambda g: g.partner_name_ar)
    totals = _group_currency_amounts([(a.currency_code, a.balance) for g in groups for a in g.accounts])
    return CorrespondentsResponse(groups=groups, totals=totals)


@router.get("/accounts/banks", response_model=BanksResponse)
def accounts_banks(db: OrmSession = Depends(get_db)) -> BanksResponse:
    """§٧-٧ بنوك الصين."""
    balances = _balances_by_account(db)
    china = db.execute(select(Location).where(Location.code == "CHINA")).scalar_one_or_none()
    accounts = accounts_repo.leaf_accounts(db, include_client_accounts=False)
    banks = [a for a in accounts if a.form == AccountForm.BANK and (china is None or a.location_id == china.id)]
    rows = [
        AccountBalanceRow(code=a.code, name_ar=a.name_ar, currency_code=a.currency_code or "?", balance=balances.get(a.id, Decimal("0")))
        for a in sorted(banks, key=lambda x: x.code)
    ]
    totals = _group_currency_amounts([(r.currency_code, r.balance) for r in rows])
    return BanksResponse(accounts=rows, totals=totals)


def _live_only(rows: list[LotConsumption]) -> list[LotConsumption]:
    """الاستهلاكات الحيّة فقط: يُستثنى كل صف عكسي وكل أصل عُكس (٢٠٢٦-١٠-٠٢) — فلا يُحتسب بيع مُلغى في
    عدد المبيعات ولا متوسط السعر ولا الربح."""
    reversed_ids = {c.reverses_consumption_id for c in rows if c.reverses_consumption_id is not None}
    return [c for c in rows if c.reverses_consumption_id is None and c.id not in reversed_ids]


def _lot_row(lot: CurrencyLot, *, consumptions: list[LotConsumption], partner_name: Optional[str], external_ref: Optional[str]) -> LotRow:
    total_profit = sum((c.profit for c in consumptions), Decimal("0"))
    total_qty = sum((c.qty for c in consumptions), Decimal("0"))
    weighted_avg = None
    if total_qty > 0:
        weighted_avg = sum((c.qty * c.client_rate for c in consumptions), Decimal("0")) / total_qty
    return LotRow(
        id=lot.id, lot_no=lot.lot_no, swift_external_ref=external_ref, partner_name_ar=partner_name,
        arrival_date=lot.opened_at.date(), original_qty=lot.original_qty, cost_rate=lot.cost_rate,
        remaining_qty=lot.remaining_qty, num_sales=len(consumptions), weighted_avg_sale_rate=weighted_avg,
        total_profit=total_profit, profit_currency=consumptions[0].profit_currency if consumptions else None,
        status=lot.status.value,
    )


@router.get("/lots", response_model=list[LotRow])
def list_lots(db: OrmSession = Depends(get_db)) -> list[LotRow]:
    """§٧-٨ قائمة دفعات الرمبي — تُغطّي أيضاً «تقرير ربحية كل سويفت»:
    كل دفعة تُفتح بحركة SWIFT_IN واحدة بسعر تحويل (١:١)، فربحية الدفعة
    هي ربحية ذلك السويفت بعينه. `SwiftMovement.profit_amount/profit_currency`
    **غير مُستخدَمين هنا عمداً** — لا يُعبَّآن في أي مكان بالمحرك فعلياً (بقايا
    مخطّط غير مفعَّلة)؛ الربح الحقيقي يُحسَب من `lot_consumptions` مباشرة."""
    lots = db.execute(select(CurrencyLot).order_by(CurrencyLot.opened_at.desc())).scalars().all()
    if not lots:
        return []
    lot_ids = [l.id for l in lots]
    consumptions = db.execute(select(LotConsumption).where(LotConsumption.lot_id.in_(lot_ids))).scalars().all()
    by_lot: dict[int, list[LotConsumption]] = defaultdict(list)
    for c in _live_only(consumptions):
        by_lot[c.lot_id].append(c)

    source_entry_ids = [l.source_entry_id for l in lots]
    entries = {e.id: e for e in db.execute(select(JournalEntry).where(JournalEntry.id.in_(source_entry_ids))).scalars().all()}
    movements = db.execute(select(SwiftMovement).where(SwiftMovement.in_entry_id.in_(source_entry_ids))).scalars().all()
    movement_by_in_entry = {m.in_entry_id: m for m in movements}
    out_entry_ids = {m.out_entry_id for m in movements if m.out_entry_id is not None}
    out_entries = {e.id: e for e in db.execute(select(JournalEntry).where(JournalEntry.id.in_(out_entry_ids))).scalars().all()} if out_entry_ids else {}
    partner_ids = {e.partner_id for e in out_entries.values() if e.partner_id is not None}
    partners = {p.id: p for p in db.execute(select(Partner).where(Partner.id.in_(partner_ids))).scalars().all()} if partner_ids else {}

    rows = []
    for lot in lots:
        movement = movement_by_in_entry.get(lot.source_entry_id)
        external_ref = movement.external_ref if movement else None
        partner_name = None
        if movement and movement.out_entry_id in out_entries:
            out_entry = out_entries[movement.out_entry_id]
            if out_entry.partner_id in partners:
                partner_name = partners[out_entry.partner_id].name_ar
        rows.append(_lot_row(lot, consumptions=sorted(by_lot.get(lot.id, []), key=lambda c: c.consumed_at), partner_name=partner_name, external_ref=external_ref))
    return rows


@router.get("/lots/{lot_id}", response_model=LotDetail)
def lot_detail(lot_id: int, db: OrmSession = Depends(get_db)) -> LotDetail:
    lot = db.get(CurrencyLot, lot_id)
    if lot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا دفعة بالمعرّف {lot_id}")
    consumptions = _live_only(db.execute(
        select(LotConsumption).where(LotConsumption.lot_id == lot_id).order_by(LotConsumption.consumed_at)
    ).scalars().all())

    entry_ids = [c.entry_id for c in consumptions]
    entries = {e.id: e for e in db.execute(select(JournalEntry).where(JournalEntry.id.in_(entry_ids))).scalars().all()} if entry_ids else {}
    client_ids = {e.client_id for e in entries.values() if e.client_id is not None}
    clients = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()} if client_ids else {}

    movement = db.execute(select(SwiftMovement).where(SwiftMovement.in_entry_id == lot.source_entry_id)).scalar_one_or_none()
    external_ref = movement.external_ref if movement else None
    partner_name = None
    if movement and movement.out_entry_id:
        out_entry = db.get(JournalEntry, movement.out_entry_id)
        if out_entry and out_entry.partner_id:
            partner = db.get(Partner, out_entry.partner_id)
            partner_name = partner.name_ar if partner else None

    lot_row = _lot_row(lot, consumptions=list(consumptions), partner_name=partner_name, external_ref=external_ref)
    consumption_rows = [
        LotConsumptionRow(
            consumed_at=c.consumed_at,
            client_name_ar=clients[entries[c.entry_id].client_id].name_ar if c.entry_id in entries and entries[c.entry_id].client_id in clients else None,
            qty=c.qty, client_rate=c.client_rate, cost_share=c.cost_share, profit=c.profit, profit_currency=c.profit_currency,
        )
        for c in consumptions
    ]
    return LotDetail(lot=lot_row, consumptions=consumption_rows)

"""شاشات العملاء (§٧-٥): قائمة · صفحة عميل · كشف حساب برصيد متحرك ·
إنشاء/تعديل عميل وحدود ائتمانه.

لا منطق محاسبي هنا — كتابة القيود حصراً عبر `app/routers/operations.py`.
هذا الملف بيانات وصفية (عميل · مستفيد · حد ائتمان) وقراءة مُشتقّة من
`journal_lines`/`account_balances` الموجودة أصلاً.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.documents.formatting import format_rate
from app.engine.clock import system_clock
from app.models import (
    Account,
    AccountBalance,
    Client,
    ClientCreditLimit,
    Currency,
    JournalEntry,
    JournalLine,
    Location,
    User,
)
from app.models.enums import EntryStatus, SessionSubjectType
from app.schemas.clients import (
    ClientBalanceRow,
    ClientDetail,
    ClientListRow,
    CreateClientRequest,
    CreditLimitOut,
    SetCreditAllowedRequest,
    SetCreditLimitRequest,
    StatementResponse,
    StatementRow,
    UpdateClientRequest,
)
from app.schemas.portal import ClientPortalInviteCreatedResponse, ClientPortalStatusResponse
from app.security import audit, client_portal_invites, client_portal_management
from app.security.deps import require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(tags=["clients"])


def _get_client_or_404(db: OrmSession, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عميل بالمعرّف {client_id}")
    return client


def _client_balances(db: OrmSession, client_id: int) -> list[ClientBalanceRow]:
    locations = {loc.id: loc.code for loc in db.execute(select(Location)).scalars().all()}
    rows = db.execute(
        select(Account, AccountBalance)
        .join(AccountBalance, AccountBalance.account_id == Account.id)
        .where(Account.client_id == client_id)
        .order_by(Account.currency_code, Account.code)
    ).all()
    return [
        ClientBalanceRow(
            currency_code=acc.currency_code, account_code=acc.code,
            location_code=locations.get(acc.location_id) if acc.location_id else None, balance=bal.balance,
        )
        for acc, bal in rows
    ]


def _client_credit_limits(db: OrmSession, client_id: int) -> list[CreditLimitOut]:
    rows = db.execute(
        select(ClientCreditLimit).where(ClientCreditLimit.client_id == client_id).order_by(ClientCreditLimit.currency_code)
    ).scalars().all()
    return [CreditLimitOut(currency_code=r.currency_code, limit_amount=r.limit_amount) for r in rows]


@router.get("/clients", response_model=list[ClientListRow], dependencies=[Depends(require_role(Action.POST_ENTRY))])
def list_clients(
    q: Optional[str] = Query(default=None), limit: int = Query(default=50, le=200), db: OrmSession = Depends(get_db)
) -> list[ClientListRow]:
    stmt = select(Client).where(Client.is_active.is_(True))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where((Client.name_ar.ilike(pattern)) | (Client.code.ilike(pattern)) | (Client.phone.ilike(pattern)))
    clients = db.execute(stmt.order_by(Client.name_ar).limit(limit)).scalars().all()
    if not clients:
        return []
    client_ids = [c.id for c in clients]

    last_activity_rows = db.execute(
        select(JournalEntry.client_id, func.max(JournalEntry.entry_date))
        .where(JournalEntry.client_id.in_(client_ids))
        .group_by(JournalEntry.client_id)
    ).all()
    last_activity = dict(last_activity_rows)

    limits_rows = db.execute(
        select(ClientCreditLimit).where(ClientCreditLimit.client_id.in_(client_ids))
    ).scalars().all()
    limits_by_client: dict[int, list[CreditLimitOut]] = {}
    for r in limits_rows:
        limits_by_client.setdefault(r.client_id, []).append(CreditLimitOut(currency_code=r.currency_code, limit_amount=r.limit_amount))

    balance_rows = db.execute(
        select(Account.client_id, Account.currency_code, func.sum(AccountBalance.balance))
        .join(AccountBalance, AccountBalance.account_id == Account.id)
        .where(Account.client_id.in_(client_ids))
        .group_by(Account.client_id, Account.currency_code)
    ).all()
    balances_by_client: dict[int, list[ClientBalanceRow]] = {}
    for client_id, ccy, total in balance_rows:
        balances_by_client.setdefault(client_id, []).append(
            ClientBalanceRow(currency_code=ccy, account_code="*", location_code=None, balance=total)
        )

    return [
        ClientListRow(
            id=c.id, code=c.code, name_ar=c.name_ar, phone=c.phone, credit_allowed=c.credit_allowed,
            is_active=c.is_active, balances=balances_by_client.get(c.id, []),
            credit_limits=limits_by_client.get(c.id, []), last_activity=last_activity.get(c.id),
        )
        for c in clients
    ]


@router.get("/clients/{client_id}", response_model=ClientDetail, dependencies=[Depends(require_role(Action.POST_ENTRY))])
def get_client(client_id: int, db: OrmSession = Depends(get_db)) -> ClientDetail:
    client = _get_client_or_404(db, client_id)
    return ClientDetail(
        id=client.id, code=client.code, name_ar=client.name_ar, name_en=client.name_en, phone=client.phone,
        id_number=client.id_number, credit_allowed=client.credit_allowed, is_active=client.is_active,
        created_at=client.created_at, balances=_client_balances(db, client_id),
        credit_limits=_client_credit_limits(db, client_id),
    )


@router.post(
    "/clients", response_model=ClientDetail, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_client(
    payload: CreateClientRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.CREATE_CLIENT)),
) -> ClientDetail:
    if db.execute(select(Client).where(Client.code == payload.code)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"كود العميل {payload.code} مُستخدَم بالفعل")
    client = Client(
        code=payload.code, name_ar=payload.name_ar, name_en=payload.name_en, phone=payload.phone,
        id_number=payload.id_number, search_name=payload.name_ar, credit_allowed=False, created_by=current_user.id,
    )
    db.add(client)
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="CLIENT_CREATED",
        entity="clients", entity_id=client.id, after={"code": client.code, "name_ar": client.name_ar},
    )
    db.commit()
    return ClientDetail(
        id=client.id, code=client.code, name_ar=client.name_ar, name_en=client.name_en, phone=client.phone,
        id_number=client.id_number, credit_allowed=client.credit_allowed, is_active=client.is_active,
        created_at=client.created_at, balances=[], credit_limits=[],
    )


@router.patch(
    "/clients/{client_id}", response_model=ClientDetail,
    dependencies=[Depends(verify_csrf), Depends(require_role(Action.POST_ENTRY))],
)
def update_client(client_id: int, payload: UpdateClientRequest, db: OrmSession = Depends(get_db)) -> ClientDetail:
    client = _get_client_or_404(db, client_id)
    if payload.name_ar is not None:
        client.name_ar = payload.name_ar
        client.search_name = payload.name_ar  # المشغّل (§٣-٩) يعيد تطبيعه فعلياً عند UPDATE OF name_ar
    if payload.name_en is not None:
        client.name_en = payload.name_en
    if payload.phone is not None:
        client.phone = payload.phone
    if payload.id_number is not None:
        client.id_number = payload.id_number
    db.commit()
    return ClientDetail(
        id=client.id, code=client.code, name_ar=client.name_ar, name_en=client.name_en, phone=client.phone,
        id_number=client.id_number, credit_allowed=client.credit_allowed, is_active=client.is_active,
        created_at=client.created_at, balances=_client_balances(db, client_id),
        credit_limits=_client_credit_limits(db, client_id),
    )


@router.patch(
    "/clients/{client_id}/credit-allowed", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
    dependencies=[Depends(verify_csrf)],
)
def set_credit_allowed(
    client_id: int, payload: SetCreditAllowedRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OVERRIDE_CREDIT_OR_BALANCE)),
) -> None:
    """§٧-١٣: منح/سحب الثقة الائتمانية قرار مدير فقط — نفس بند تجاوز الائتمان."""
    client = _get_client_or_404(db, client_id)
    before = client.credit_allowed
    client.credit_allowed = payload.credit_allowed
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="CLIENT_CREDIT_ALLOWED_CHANGED",
        entity="clients", entity_id=client.id, before={"credit_allowed": before}, after={"credit_allowed": payload.credit_allowed},
    )
    db.commit()


@router.put(
    "/clients/{client_id}/credit-limits/{currency_code}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
    dependencies=[Depends(verify_csrf)],
)
def set_credit_limit(
    client_id: int, currency_code: str, payload: SetCreditLimitRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.OVERRIDE_CREDIT_OR_BALANCE)),
) -> None:
    client = _get_client_or_404(db, client_id)
    if db.get(Currency, currency_code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عملة بالكود {currency_code}")
    row = db.get(ClientCreditLimit, (client_id, currency_code))
    before = row.limit_amount if row else None
    if row is None:
        row = ClientCreditLimit(client_id=client_id, currency_code=currency_code, limit_amount=payload.limit_amount)
        db.add(row)
    else:
        row.limit_amount = payload.limit_amount
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=current_user.id, action="CLIENT_CREDIT_LIMIT_SET",
        entity="clients", entity_id=client.id,
        before={"currency_code": currency_code, "limit_amount": str(before) if before is not None else None},
        after={"currency_code": currency_code, "limit_amount": str(payload.limit_amount)},
    )
    db.commit()


def compute_client_statement(
    db: OrmSession, *, client_id: int, currency: str, location: str,
    date_from: Optional[date], date_to: Optional[date], include_reversed: bool = False,
) -> StatementResponse:
    """كشف حساب برصيد متحرك — حساب واحد محدَّد (عملة×موقع)، لا مزج بين
    مواقع مختلفة في نفس الرصيد المتحرك (القاعدة الفاصلة §٢-٢). دالة مشتركة
    يستدعيها مسار الموظف أدناه **وبوابة العميل** (`app/routers/portal.py`)
    بلا تكرار — العميل هناك يمرِّر `client_id` جلسته هو حصراً، لا مُدخَلاً
    من الطلب (اختبار القبول ٤٠)."""
    location_row = db.execute(select(Location).where(Location.code == location)).scalar_one_or_none()
    if location_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا موقع بالكود {location}")
    account = db.execute(
        select(Account).where(
            Account.client_id == client_id, Account.currency_code == currency, Account.location_id == location_row.id
        )
    ).scalar_one_or_none()
    if account is None:
        return StatementResponse(
            account_code="", currency_code=currency, location_code=location,
            opening_balance=Decimal("0"), closing_balance=Decimal("0"), rows=[],
        )

    if date_from is not None:
        opening_query = (
            select(func.coalesce(func.sum(JournalLine.credit - JournalLine.debit), 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.account_id == account.id,
                JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
                JournalEntry.entry_date < date_from,
            )
        )
        opening_balance = db.execute(opening_query).scalar_one()
    else:
        opening_balance = Decimal("0")

    rows_query = (
        select(JournalEntry, JournalLine)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id == account.id,
            JournalEntry.status.in_((EntryStatus.POSTED, EntryStatus.REVERSED)),
        )
        .order_by(JournalEntry.entry_date, JournalEntry.id)
    )
    if date_from is not None:
        rows_query = rows_query.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        rows_query = rows_query.where(JournalEntry.entry_date <= date_to)

    running = opening_balance
    statement_rows: list[StatementRow] = []
    for entry, line in db.execute(rows_query).all():
        # الرصيد المتحرك يشمل كل سطر حقيقي دائماً — القيد المعكوس وعكسه
        # كلاهما سطر حسابي فعلي وإلا فسد الرصيد لأي فترة تشمل إلغاءً.
        # `include_reversed` يتحكّم بعرض الصف فقط، لا بحسابه.
        running = running + line.credit - line.debit
        is_cancelled_pair = entry.status == EntryStatus.REVERSED or entry.reverses_entry_id is not None
        if is_cancelled_pair and not include_reversed:
            continue
        statement_rows.append(
            StatementRow(
                entry_id=entry.id, entry_no=entry.entry_no, entry_date=entry.entry_date,
                operation_type=entry.operation_type.value, description=entry.description,
                debit=line.debit, credit=line.credit, running_balance=running,
                status=entry.status.value, note=entry.note, replaces_entry_id=entry.replaces_entry_id,
                client_rate=format_rate(entry.client_rate) if entry.client_rate is not None else None,
                chain_ref=entry.chain_ref,
            )
        )

    return StatementResponse(
        account_code=account.code, currency_code=currency, location_code=location,
        opening_balance=opening_balance, closing_balance=running, rows=statement_rows,
    )


@router.get(
    "/clients/{client_id}/statement", response_model=StatementResponse,
    dependencies=[Depends(require_role(Action.POST_ENTRY))],
)
def client_statement(
    client_id: int, currency: str = Query(...), location: str = Query(...),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
    include_reversed: bool = Query(default=False),
    db: OrmSession = Depends(get_db),
) -> StatementResponse:
    _get_client_or_404(db, client_id)
    return compute_client_statement(
        db, client_id=client_id, currency=currency, location=location, date_from=date_from, date_to=date_to,
        include_reversed=include_reversed,
    )


@router.get(
    "/clients/{client_id}/portal", response_model=ClientPortalStatusResponse,
    dependencies=[Depends(require_role(Action.MANAGE_USERS))],
)
def get_client_portal_status(client_id: int, db: OrmSession = Depends(get_db)) -> ClientPortalStatusResponse:
    client = _get_client_or_404(db, client_id)
    now = system_clock()
    status_value, invite_expires_at = client_portal_management.compute_status(db, client=client, now=now)
    return ClientPortalStatusResponse(
        status=status_value.value, last_login_at=client.portal_last_login_at, invite_expires_at=invite_expires_at,
    )


@router.post(
    "/clients/{client_id}/portal/enable", response_model=ClientPortalInviteCreatedResponse,
    dependencies=[Depends(verify_csrf)],
)
def enable_client_portal(
    client_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> ClientPortalInviteCreatedResponse:
    """غير مفعّلة/معطّلة → مفعّلة + دعوة أولى. الرابط يُعرَض هنا **مرة واحدة
    فقط** — الخادم لا يحتفظ إلا ببصمته بعد هذا الرد."""
    now = system_clock()
    try:
        _client, raw, expires_at = client_portal_management.enable(
            db, actor_id=current_user.id, client_id=client_id, now=now,
        )
    except client_portal_management.ClientNotFoundError as exc:
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return ClientPortalInviteCreatedResponse(invite_url=client_portal_invites.invite_url(raw), expires_at=expires_at)


@router.post(
    "/clients/{client_id}/portal/invite", response_model=ClientPortalInviteCreatedResponse,
    dependencies=[Depends(verify_csrf)],
)
def invite_client_portal(
    client_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> ClientPortalInviteCreatedResponse:
    """دعوة معلّقة/منتهية → رابط جديد (يُبطل القديم تلقائياً)."""
    now = system_clock()
    try:
        _client, raw, expires_at = client_portal_management.invite(
            db, actor_id=current_user.id, client_id=client_id, now=now,
        )
    except client_portal_management.ClientNotFoundError as exc:
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except client_portal_management.PortalNotEnabledError as exc:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return ClientPortalInviteCreatedResponse(invite_url=client_portal_invites.invite_url(raw), expires_at=expires_at)


@router.post(
    "/clients/{client_id}/portal/reset", response_model=ClientPortalInviteCreatedResponse,
    dependencies=[Depends(verify_csrf)],
)
def reset_client_portal(
    client_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> ClientPortalInviteCreatedResponse:
    """مفعّلة/مقفلة → تُبطل كلمة المرور الحالية فوراً + تُنهي كل الجلسات +
    رابط دعوة جديد."""
    now = system_clock()
    try:
        _client, raw, expires_at = client_portal_management.reset(
            db, actor_id=current_user.id, client_id=client_id, now=now,
        )
    except client_portal_management.ClientNotFoundError as exc:
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except client_portal_management.PortalNotEnabledError as exc:
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return ClientPortalInviteCreatedResponse(invite_url=client_portal_invites.invite_url(raw), expires_at=expires_at)


@router.post(
    "/clients/{client_id}/portal/disable", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
    dependencies=[Depends(verify_csrf)],
)
def disable_client_portal(
    client_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> None:
    """يُنهي كل جلسات العميل النشطة فوراً + يُبطل كلمة المرور وأي دعوة حيّة."""
    now = system_clock()
    try:
        client_portal_management.disable(db, actor_id=current_user.id, client_id=client_id, now=now)
    except client_portal_management.ClientNotFoundError as exc:
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()


@router.post(
    "/clients/{client_id}/portal/unlock", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
    dependencies=[Depends(verify_csrf)],
)
def unlock_client_portal(
    client_id: int, db: OrmSession = Depends(get_db), current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> None:
    try:
        client_portal_management.unlock(db, actor_id=current_user.id, client_id=client_id)
    except client_portal_management.ClientNotFoundError as exc:
        db.commit()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()

"""شاشة الإعدادات (§٧-١٤) — ملف الشركة (اسم/شعار عبر `Setting` key-value)
+ حسابات البنوك المملوكة (تحت ١٤٠٠، بترقيم آلي — المرحلة ١٠)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import accounts_repo
from app.models import Account, AccountBalance, ClientCurrencyLocation, Currency, JournalLine, Location, Setting, User
from app.schemas.settings import (
    AccountOut,
    ClientCurrencyLocationRow,
    CompanyProfile,
    CreateBankAccountRequest,
    CreateClientCurrencyLocationRequest,
    CreateCurrencyRequest,
    CreateLocationRequest,
    CurrencyRow,
    LocationRow,
    UpdateCurrencyRequest,
    UpdateLocationRequest,
)
from app.security import audit
from app.security.deps import require_password_changed, require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_password_changed)])

_COMPANY_KEY = "company_profile"


def _account_out(db: OrmSession, account: Account) -> AccountOut:
    location_code = None
    if account.location_id is not None:
        location_code = db.get(Location, account.location_id).code
    return AccountOut(
        id=account.id, code=account.code, name_ar=account.name_ar, currency_code=account.currency_code,
        location_code=location_code, form=account.form.value if account.form else None, partner_id=account.partner_id,
    )


def _company_audit_view(value: dict) -> dict:
    """الشعار صورة base64 كبيرة — يُسجَّل وجوده/غيابه لا محتواه."""
    return {"name_ar": value.get("name_ar"), "has_logo": bool(value.get("logo_data_url"))}


@router.get("/company", response_model=CompanyProfile)
def get_company_profile(db: OrmSession = Depends(get_db)) -> CompanyProfile:
    row = db.execute(select(Setting).where(Setting.key == _COMPANY_KEY)).scalar_one_or_none()
    if row is None:
        return CompanyProfile()
    return CompanyProfile(**row.value)


@router.put("/company", response_model=CompanyProfile, dependencies=[Depends(verify_csrf)])
def set_company_profile(
    payload: CompanyProfile, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> CompanyProfile:
    row = db.execute(select(Setting).where(Setting.key == _COMPANY_KEY)).scalar_one_or_none()
    before = _company_audit_view(row.value if row else {})
    # دمج لا استبدال: الحقل غير المُرسَل يبقى كما هو (الواجهة ترسل الاسم وحده فكان الشعار يُمحى)؛ ومحوه صراحةً بإرسال null
    merged = CompanyProfile(**{**(row.value if row else {}), **payload.model_dump(exclude_unset=True)})
    if row is None:
        db.add(Setting(key=_COMPANY_KEY, value=merged.model_dump()))
    else:
        row.value = merged.model_dump()
    audit.log_user_write(db, current_user, action="COMPANY_PROFILE_UPDATED", entity="settings", before=before, after=_company_audit_view(merged.model_dump()))
    db.commit()
    return merged


@router.get("/bank-accounts", response_model=list[AccountOut])
def list_bank_accounts(db: OrmSession = Depends(get_db)) -> list[AccountOut]:
    parent = db.execute(select(Account).where(Account.code == "1400")).scalar_one_or_none()
    if parent is None:
        return []
    rows = db.execute(select(Account).where(Account.parent_id == parent.id).order_by(Account.code)).scalars().all()
    return [_account_out(db, a) for a in rows]


@router.post(
    "/bank-accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_bank_account(
    payload: CreateBankAccountRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> AccountOut:
    name_ar = payload.name_ar or f"بنك · {payload.currency_code} · {payload.location_code}"
    try:
        account = accounts_repo.create_bank_account(
            db, currency_code=payload.currency_code, location_code=payload.location_code, name_ar=name_ar,
        )
    except accounts_repo.AccountNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except accounts_repo.AccountNumberExhaustedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.log_user_write(
        db, current_user, action="BANK_ACCOUNT_CREATED", entity="accounts", entity_id=account.id,
        after={"code": account.code, "name_ar": account.name_ar, "currency_code": payload.currency_code, "location_code": payload.location_code},
    )
    db.commit()
    return _account_out(db, account)


# ═══ العملات (٢٠٢٦-٠٩-٢٥) — جدول · إضافة · تعديل محدود · تعطيل لا حذف ═══


def _currency_row(c: Currency) -> CurrencyRow:
    return CurrencyRow(
        code=c.code, name_ar=c.name_ar, symbol=c.symbol, decimals=c.decimals,
        is_pivot=c.is_pivot, is_active=c.is_active, sort_order=c.sort_order,
    )


def _currency_ever_used(db: OrmSession, code: str) -> bool:
    """أي سطر قيد حقيقي بهذه العملة، بصرف النظر عن حالة القيد — قيد
    مُلغى (REVERSED) لا يعني أن العملة لم تُستخدَم فعلياً وقتها."""
    return db.execute(select(JournalLine.id).where(JournalLine.currency_code == code).limit(1)).first() is not None


def _currency_has_nonzero_balance(db: OrmSession, code: str) -> bool:
    rows = db.execute(
        select(AccountBalance.balance)
        .join(Account, Account.id == AccountBalance.account_id)
        .where(Account.currency_code == code)
    ).scalars().all()
    return any(b != 0 for b in rows)


@router.get("/currencies", response_model=list[CurrencyRow])
def list_currencies_admin(db: OrmSession = Depends(get_db)) -> list[CurrencyRow]:
    rows = db.execute(select(Currency).order_by(Currency.sort_order)).scalars().all()
    return [_currency_row(c) for c in rows]


@router.post(
    "/currencies", response_model=CurrencyRow, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_currency(
    payload: CreateCurrencyRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> CurrencyRow:
    code = payload.code.strip().upper()
    if db.get(Currency, code) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"العملة {code} موجودة بالفعل")
    currency = Currency(
        code=code, name_ar=payload.name_ar, symbol=payload.symbol, decimals=payload.decimals,
        is_pivot=False, is_active=True, sort_order=payload.sort_order,
    )
    db.add(currency)
    db.flush()
    # ٢٠٢٦-٠٩-٢٥: كل الحسابات الفرعية المرجعية لهذه العملة دفعة واحدة —
    # بلا هذا، أول قبض/صرافة/مصروف بالعملة الجديدة يفشل بحساب ربح/تكلفة
    # مفقود (accounts_repo.AccountNotFoundError من get_currency_subaccount).
    accounts_repo.create_currency_chart_of_accounts(db, currency=currency)
    audit.log_user_write(
        db, current_user, action="CURRENCY_CREATED", entity="currencies",
        after={**_currency_row(currency).model_dump(), "accounts_created": "الشجرة الفرعية المرجعية للعملة"},
    )
    db.commit()
    return _currency_row(currency)


@router.patch("/currencies/{code}", response_model=CurrencyRow, dependencies=[Depends(verify_csrf)])
def update_currency(
    code: str, payload: UpdateCurrencyRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> CurrencyRow:
    currency = db.get(Currency, code.upper())
    if currency is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عملة بالكود {code}")
    before = _currency_row(currency).model_dump()
    if payload.decimals is not None and payload.decimals != currency.decimals:
        if _currency_ever_used(db, currency.code):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"لا يمكن تعديل منازل {currency.code} العشرية — استُخدمت في قيد حقيقي بالفعل",
            )
        currency.decimals = payload.decimals
    if payload.is_active is False and currency.is_active:
        if _currency_has_nonzero_balance(db, currency.code):
            raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن تعطيل {currency.code} — لها رصيد غير صفري في حساب واحد على الأقل")
        currency.is_active = False
    elif payload.is_active is True:
        currency.is_active = True
    if payload.name_ar is not None:
        currency.name_ar = payload.name_ar
    if payload.symbol is not None:
        currency.symbol = payload.symbol
    if payload.sort_order is not None:
        currency.sort_order = payload.sort_order
    audit.log_user_write(db, current_user, action="CURRENCY_UPDATED", entity="currencies", before=before, after=_currency_row(currency).model_dump())
    db.commit()
    return _currency_row(currency)


# ═══ المواقع (٢٠٢٦-٠٩-٢٥) — نفس منطق العملات (بلا حسابات فرعية تلقائية:
# لا تفريع بالموقع في شجرة الحسابات، خلافاً للعملة) ═══════════════════


def _location_row(l: Location) -> LocationRow:
    return LocationRow(code=l.code, name_ar=l.name_ar, country=l.country, is_active=l.is_active)


def _location_has_nonzero_balance(db: OrmSession, location_id: int) -> bool:
    rows = db.execute(
        select(AccountBalance.balance)
        .join(Account, Account.id == AccountBalance.account_id)
        .where(Account.location_id == location_id)
    ).scalars().all()
    return any(b != 0 for b in rows)


@router.get("/locations", response_model=list[LocationRow])
def list_locations_admin(db: OrmSession = Depends(get_db)) -> list[LocationRow]:
    rows = db.execute(select(Location).order_by(Location.code)).scalars().all()
    return [_location_row(l) for l in rows]


@router.post(
    "/locations", response_model=LocationRow, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_location(
    payload: CreateLocationRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> LocationRow:
    code = payload.code.strip().upper()
    existing = db.execute(select(Location).where(Location.code == code)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"الموقع {code} موجود بالفعل")
    location = Location(code=code, name_ar=payload.name_ar, country=payload.country, is_active=True)
    db.add(location)
    db.flush()
    audit.log_user_write(db, current_user, action="LOCATION_CREATED", entity="locations", entity_id=location.id, after=_location_row(location).model_dump())
    db.commit()
    return _location_row(location)


@router.patch("/locations/{code}", response_model=LocationRow, dependencies=[Depends(verify_csrf)])
def update_location(
    code: str, payload: UpdateLocationRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> LocationRow:
    location = db.execute(select(Location).where(Location.code == code.upper())).scalar_one_or_none()
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا موقع بالكود {code}")
    before = _location_row(location).model_dump()
    if payload.is_active is False and location.is_active:
        if _location_has_nonzero_balance(db, location.id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"لا يمكن تعطيل {location.code} — له رصيد غير صفري في حساب واحد على الأقل")
        location.is_active = False
    elif payload.is_active is True:
        location.is_active = True
    if payload.name_ar is not None:
        location.name_ar = payload.name_ar
    if payload.country is not None:
        location.country = payload.country
    audit.log_user_write(db, current_user, action="LOCATION_UPDATED", entity="locations", entity_id=location.id, before=before, after=_location_row(location).model_dump())
    db.commit()
    return _location_row(location)


# ═══ تركيبات عملة×موقع لحسابات العملاء (٢٠٢٦-٠٩-٢٥) — سدّ فجوة: عملة
# جديدة بلا هذا كانت تُرفَض عند أول قبض/صرافة لعميل بها (InvalidClientLocationError)
# رغم أن الحسابات المحاسبية للشركة نفسها (شجرة العملة الفرعية) تُبنى فوراً
# عند الإنشاء. لا حذف — نفس فلسفة `client_currency_locations` كجدول بيانات
# فقط يُضاف إليه، موثَّقة في `app/models/core.py::ClientCurrencyLocation`. ═══


@router.get("/client-currency-locations", response_model=list[ClientCurrencyLocationRow])
def list_client_currency_locations_admin(db: OrmSession = Depends(get_db)) -> list[ClientCurrencyLocationRow]:
    rows = db.execute(
        select(ClientCurrencyLocation.currency_code, Location.code)
        .join(Location, Location.id == ClientCurrencyLocation.location_id)
        .order_by(ClientCurrencyLocation.currency_code, Location.code)
    ).all()
    return [ClientCurrencyLocationRow(currency_code=ccy, location_code=loc) for ccy, loc in rows]


@router.post(
    "/client-currency-locations", response_model=ClientCurrencyLocationRow, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_client_currency_location(
    payload: CreateClientCurrencyLocationRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> ClientCurrencyLocationRow:
    currency_code = payload.currency_code.strip().upper()
    location_code = payload.location_code.strip().upper()
    currency = db.get(Currency, currency_code)
    if currency is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا عملة بالكود {currency_code}")
    location = db.execute(select(Location).where(Location.code == location_code)).scalar_one_or_none()
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا موقع بالكود {location_code}")
    if db.get(ClientCurrencyLocation, (currency_code, location.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"التركيبة {currency_code}·{location_code} مسموحة بالفعل")
    db.add(ClientCurrencyLocation(currency_code=currency_code, location_id=location.id))
    audit.log_user_write(
        db, current_user, action="CLIENT_CURRENCY_LOCATION_ADDED", entity="client_currency_locations",
        after={"currency_code": currency_code, "location_code": location_code},
    )
    db.commit()
    return ClientCurrencyLocationRow(currency_code=currency_code, location_code=location_code)

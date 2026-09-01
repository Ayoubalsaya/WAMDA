"""شاشة الإعدادات (§٧-١٤) — ملف الشركة (اسم/شعار عبر `Setting` key-value)
+ حسابات البنوك المملوكة (تحت ١٤٠٠، بترقيم آلي — المرحلة ١٠)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import accounts_repo
from app.models import Account, Location, Setting, User
from app.schemas.settings import AccountOut, CompanyProfile, CreateBankAccountRequest
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
    if row is None:
        row = Setting(key=_COMPANY_KEY, value=payload.model_dump())
        db.add(row)
    else:
        row.value = payload.model_dump()
    db.commit()
    return payload


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
    db.commit()
    return _account_out(db, account)

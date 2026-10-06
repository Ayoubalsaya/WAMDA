"""سجل الشركاء (مكاتب ليبيا/مراسلي تركيا) + إنشاء حساباتهم المالية الفعلية
(مراسل تحت ١٣١٠/١٣٢٠، بترقيم آلي صحيح — المرحلة ١٠ سدّت فجوة كانت هذه
الحسابات تُحقَن فيها يدوياً في الاختبارات فقط)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.engine import accounts_repo
from app.models import Account, Location, Partner, User
from app.schemas.settings import AccountOut, CreatePartnerAccountRequest, CreatePartnerRequest, PartnerRow
from app.security import audit
from app.security.deps import require_password_changed, require_role, verify_csrf
from app.security.permissions import Action

_PARTNER_ACCOUNT_NAME_LABELS = {"1310": "مراسل ليبيا", "1320": "مراسل تركيا"}

router = APIRouter(prefix="/partners", tags=["partners"], dependencies=[Depends(require_password_changed)])


def _get_partner_or_404(db: OrmSession, partner_id: int) -> Partner:
    partner = db.get(Partner, partner_id)
    if partner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"لا شريك بالمعرّف {partner_id}")
    return partner


def _account_out(db: OrmSession, account: Account) -> AccountOut:
    location_code = None
    if account.location_id is not None:
        location_code = db.get(Location, account.location_id).code
    return AccountOut(
        id=account.id, code=account.code, name_ar=account.name_ar, currency_code=account.currency_code,
        location_code=location_code, form=account.form.value if account.form else None, partner_id=account.partner_id,
    )


@router.get("", response_model=list[PartnerRow])
def list_partners(db: OrmSession = Depends(get_db)) -> list[PartnerRow]:
    rows = db.execute(select(Partner).order_by(Partner.name_ar)).scalars().all()
    return [PartnerRow(**{c: getattr(p, c) for c in PartnerRow.model_fields}) for p in rows]


@router.post("", response_model=PartnerRow, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_csrf)])
def create_partner(
    payload: CreatePartnerRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> PartnerRow:
    existing = db.execute(select(Partner).where(Partner.code == payload.code)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "كود الشريك مستخدَم بالفعل")
    partner = Partner(
        code=payload.code, name_ar=payload.name_ar, name_en=payload.name_en, country=payload.country,
        contact_phone=payload.contact_phone, notes=payload.notes,
    )
    db.add(partner)
    db.flush()
    audit.log_user_write(
        db, current_user, action="PARTNER_CREATED", entity="partners", entity_id=partner.id,
        after={"code": partner.code, "name_ar": partner.name_ar, "country": partner.country},
    )
    db.commit()
    db.refresh(partner)
    return PartnerRow(**{c: getattr(partner, c) for c in PartnerRow.model_fields})


@router.get("/{partner_id}/accounts", response_model=list[AccountOut])
def list_partner_accounts(partner_id: int, db: OrmSession = Depends(get_db)) -> list[AccountOut]:
    _get_partner_or_404(db, partner_id)
    rows = db.execute(select(Account).where(Account.partner_id == partner_id).order_by(Account.code)).scalars().all()
    return [_account_out(db, a) for a in rows]


@router.post(
    "/{partner_id}/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_csrf)],
)
def create_partner_account(
    partner_id: int, payload: CreatePartnerAccountRequest, db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.MANAGE_USERS)),
) -> AccountOut:
    partner = _get_partner_or_404(db, partner_id)
    name_ar = payload.name_ar or f"{partner.name_ar} · {_PARTNER_ACCOUNT_NAME_LABELS.get(payload.parent_code, payload.parent_code)} · {payload.currency_code}"
    try:
        account = accounts_repo.create_partner_account(
            db, partner_id=partner_id, parent_code=payload.parent_code, currency_code=payload.currency_code,
            location_code=payload.location_code, name_ar=name_ar,
        )
    except accounts_repo.AccountNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except accounts_repo.AccountNumberExhaustedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    audit.log_user_write(
        db, current_user, action="PARTNER_ACCOUNT_CREATED", entity="accounts", entity_id=account.id,
        after={"partner_id": partner_id, "code": account.code, "currency_code": payload.currency_code, "location_code": payload.location_code},
    )
    db.commit()
    return _account_out(db, account)

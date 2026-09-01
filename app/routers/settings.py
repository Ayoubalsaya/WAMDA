"""شاشة الإعدادات (§٧-١٤) — ملف الشركة (اسم/شعار عبر `Setting` key-value)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.models import Setting, User
from app.schemas.settings import CompanyProfile
from app.security.deps import require_password_changed, require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_password_changed)])

_COMPANY_KEY = "company_profile"


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

"""سجل الشركاء (مكاتب ليبيا/مراسلي تركيا) — عرض وإنشاء فقط. إنشاء الحسابات
المالية الفعلية للشريك (مراسل ١٣٢٠ أو بنك ١٤٠٠) خارج نطاق هذا المسار حتى
الآن — لا واجهة له بعد (فجوة موثَّقة في PROGRESS.md)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.models import Partner, User
from app.schemas.settings import CreatePartnerRequest, PartnerRow
from app.security.deps import require_password_changed, require_role, verify_csrf
from app.security.permissions import Action

router = APIRouter(prefix="/partners", tags=["partners"], dependencies=[Depends(require_password_changed)])


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
    db.commit()
    db.refresh(partner)
    return PartnerRow(**{c: getattr(partner, c) for c in PartnerRow.model_fields})

"""دعوة بوابة العميل لمرة واحدة (§٧-٦ — إدارة بوابة العميل، ٢٠٢٦-١٠-٠٢):
العميل يعيّن كلمة مروره بنفسه عبر هذا الرابط — لا مدير يحدِّدها نيابة
عنه بعد اليوم (`PUT /clients/{id}/portal-credentials` حُذف).

الرمز خام `secrets.token_urlsafe(32)` (`tokens.generate_raw_token`) —
يُخزَّن بصمته (SHA-256) فقط في `client_portal_invites.token_hash`، لا
يظهر في أي مسار/استعلام HTTP (جسم الطلب حصراً) ولا في `audit_log`.

كل دالة هنا تستقبل `now` صراحة — لا `datetime.now` مباشر (نفس قاعدة المحرك).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Client, ClientPortalInvite
from app.models.enums import SessionSubjectType
from app.security import audit, passwords, portal_lockout, tokens

INVITE_TTL = timedelta(hours=48)


class InvalidInviteError(Exception):
    pass


class PortalDisabledError(Exception):
    pass


def invite_url(raw_token: str) -> str:
    """`PUBLIC_BASE_URL` — يختلف بين المحلي والنطاق الفرعي في الإنتاج (طلب
    مالك صريح). الرمز بعد `#` (جزء العميل، لا يُرسَل للخادم في أي طلب GET
    للصفحة نفسها) لا في مسار قابل للتسجيل."""
    return f"{settings.public_base_url}/static/app/portal.html#invite={raw_token}"


def _live_invite_query(client_id: int):
    return (
        select(ClientPortalInvite)
        .where(
            ClientPortalInvite.client_id == client_id,
            ClientPortalInvite.used_at.is_(None),
            ClientPortalInvite.revoked_at.is_(None),
        )
        .order_by(ClientPortalInvite.created_at.desc())
    )


def get_live_invite(db: Session, *, client_id: int) -> Optional[ClientPortalInvite]:
    """الدعوة "الحيّة" الحالية (لا مُستخدَمة ولا مُبطَلة) — بصرف النظر عن
    انتهائها، يُفحَص ذلك على حدة (حالة «دعوة منتهية» منفصلة عن غيابها)."""
    return db.execute(_live_invite_query(client_id)).scalars().first()


def has_any_invite_ever(db: Session, *, client_id: int) -> bool:
    """هل أُنشئت دعوة لهذا العميل من قبل، ولو أُبطلت/استُخدمت لاحقاً —
    يميّز «معطّلة» (فُعِّلت ثم عُطِّلت) عن «غير مفعّلة» (لم تُلمَس إطلاقاً)
    بلا أي علم مخزَّن إضافي (لا حذف لصفوف الدعوات — سياسة المشروع)."""
    return (
        db.execute(select(ClientPortalInvite.id).where(ClientPortalInvite.client_id == client_id).limit(1)).first()
        is not None
    )


def revoke_live_invite(db: Session, *, client_id: int, now: datetime) -> None:
    live = get_live_invite(db, client_id=client_id)
    if live is not None:
        live.revoked_at = now
        db.flush()


def create_invite(db: Session, *, client_id: int, created_by: int, now: datetime) -> tuple[ClientPortalInvite, str]:
    """رابط جديد يُبطل أي دعوة حيّة سابقة لنفس العميل أولاً (دعوة واحدة
    حيّة فقط في أي لحظة)."""
    revoke_live_invite(db, client_id=client_id, now=now)
    raw = tokens.generate_raw_token()
    row = ClientPortalInvite(
        client_id=client_id, token_hash=tokens.hash_token(raw), expires_at=now + INVITE_TTL, created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row, raw


def verify_invite(db: Session, *, token: str, now: datetime) -> Optional[Client]:
    """قراءة فقط — لا تغيير حالة. `None` في كل حالات الرفض (غير موجود/
    مُستخدَم/مُبطَل/منتهٍ/بوابة معطّلة) بلا تمييز، نفس مبدأ عدم كشف وجود
    الكود في `recover/start`."""
    row = db.execute(
        select(ClientPortalInvite).where(ClientPortalInvite.token_hash == tokens.hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.revoked_at is not None or row.expires_at <= now:
        return None
    client = db.get(Client, row.client_id)
    if client is None or not client.portal_enabled:
        return None
    return client


def accept_invite(db: Session, *, token: str, new_password: str, now: datetime) -> Client:
    """ذرّي عبر تحديث مشروط `WHERE used_at IS NULL AND revoked_at IS NULL`
    — لا SELECT ثم UPDATE منفصلَين (لا فجوة زمنية للتسابق عليها). قبولان
    لنفس الرمز — متزامنان حقاً أو متتاليان — لا يمكن أن ينجح منهما إلا
    واحد: الـUPDATE الثاني يطابق صفر صفوف لأن `used_at` لم يعد NULL بعد
    الأول، بصرف النظر عن التوقيت الفعلي لوصول الطلبين."""
    result = db.execute(
        update(ClientPortalInvite)
        .where(
            ClientPortalInvite.token_hash == tokens.hash_token(token),
            ClientPortalInvite.used_at.is_(None),
            ClientPortalInvite.revoked_at.is_(None),
        )
        .values(used_at=now)
        .returning(ClientPortalInvite.id, ClientPortalInvite.client_id, ClientPortalInvite.expires_at)
    )
    claimed = result.first()
    db.flush()
    if claimed is None:
        raise InvalidInviteError("رابط الدعوة غير صالح أو مُستخدَم من قبل")
    if claimed.expires_at <= now:
        raise InvalidInviteError("رابط الدعوة منتهي")

    client = db.get(Client, claimed.client_id)
    if client is None or not client.portal_enabled:
        raise PortalDisabledError("بوابة العميل معطّلة")

    client.portal_password_hash = passwords.hash_password(new_password)
    portal_lockout.reset_failed_attempts(db, client)
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.CLIENT, actor_id=client.id, action="CLIENT_PORTAL_INVITE_ACCEPTED",
        entity="clients", entity_id=client.id,
    )
    return client

"""إدارة بوابة العميل من داخل النظام (§٧-٦ — مدير فقط، `MANAGE_USERS`،
يُفرَض في الموجّه). يستبدل `PUT /clients/{id}/portal-credentials` المحذوف
(«كلمة المرور الأولية = الكود») — العميل يعيّن كلمته بنفسه دوماً الآن عبر
`app.security.client_portal_invites`.

**الحالة تُشتق ولا تُخزَّن** (قرار مالك صريح، ٢٠٢٦-١٠-٠٢): `Client.portal_enabled`
هو القرار الإداري الوحيد المخزَّن مباشرة؛ الباقي (مقفلة/مفعّلة/دعوة
معلّقة/دعوة منتهية/غير مفعّلة) يُحسَب من حالة كلمة المرور/القفل/أحدث دعوة
كل مرة — فلا يمكن أن تتناقض الشاشة مع الواقع (مثال رفضه المالك صراحة: دعوة
انتهت لكن الشاشة ما زالت تقول «معلّقة»).

كل دالة هنا تستقبل `now` صراحة — لا `datetime.now` مباشر.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Client
from app.models.enums import SessionSubjectType
from app.security import audit, client_portal_invites, sessions


class ClientPortalStatus(str, enum.Enum):
    NOT_ENABLED = "NOT_ENABLED"
    INVITE_PENDING = "INVITE_PENDING"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


class ClientNotFoundError(Exception):
    pass


class PortalNotEnabledError(Exception):
    """`reset`/`invite` على عميل لم تُفعَّل بوابته بعد — الزر الصحيح هو
    «تفعيل»، لا هذان."""


def _get(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise ClientNotFoundError(f"لا عميل بالمعرّف {client_id}")
    return client


def compute_status(db: Session, *, client: Client, now: datetime) -> tuple[ClientPortalStatus, Optional[datetime]]:
    """يُعيد (الحالة، تاريخ انتهاء الدعوة الحيّة إن وُجدت) — أولوية الفحص
    بالترتيب أدناه حرفياً (قرار مالك). «معطّلة» و«غير مفعّلة» كلاهما
    `portal_enabled=False` — يُميَّزان بوجود أي دعوة سابقة إطلاقاً (ولو
    أُبطلت/استُخدمت، صفوفها لا تُحذَف أبداً): وجودها يعني أن البوابة
    فُعِّلت يوماً ثم عُطِّلت (معطّلة)، غيابها يعني أنها لم تُلمَس بعد
    (غير مفعّلة) — بلا أي علم مخزَّن إضافي."""
    if not client.portal_enabled:
        ever_engaged = client.portal_password_hash is not None or client_portal_invites.has_any_invite_ever(
            db, client_id=client.id
        )
        return (ClientPortalStatus.DISABLED if ever_engaged else ClientPortalStatus.NOT_ENABLED), None
    if client.portal_locked_until is not None and client.portal_locked_until > now:
        return ClientPortalStatus.LOCKED, None
    if client.portal_password_hash is not None:
        return ClientPortalStatus.ACTIVE, None
    live = client_portal_invites.get_live_invite(db, client_id=client.id)
    if live is not None:
        if live.expires_at > now:
            return ClientPortalStatus.INVITE_PENDING, live.expires_at
        return ClientPortalStatus.INVITE_EXPIRED, live.expires_at
    return ClientPortalStatus.NOT_ENABLED, None


def enable(db: Session, *, actor_id: int, client_id: int, now: datetime) -> tuple[Client, str, datetime]:
    """غير مفعّلة/معطّلة → مفعّلة + دعوة أولى. يُعيد (العميل، الرابط الخام،
    تاريخ الانتهاء) — الرابط لا يُستعاد بعد هذا الرد أبداً."""
    client = _get(db, client_id)
    client.portal_enabled = True
    db.flush()
    invite_row, raw = client_portal_invites.create_invite(db, client_id=client.id, created_by=actor_id, now=now)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=actor_id, action="CLIENT_PORTAL_ENABLED",
        entity="clients", entity_id=client.id,
    )
    return client, raw, invite_row.expires_at


def invite(db: Session, *, actor_id: int, client_id: int, now: datetime) -> tuple[Client, str, datetime]:
    """دعوة معلّقة/منتهية → رابط جديد (يُبطل القديم). يتطلب بوابة مفعّلة
    بالفعل — `enable` هو المسار الصحيح من غير مفعّلة/معطّلة."""
    client = _get(db, client_id)
    if not client.portal_enabled:
        raise PortalNotEnabledError("فعّل بوابة العميل أولاً")
    invite_row, raw = client_portal_invites.create_invite(db, client_id=client.id, created_by=actor_id, now=now)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=actor_id, action="CLIENT_PORTAL_INVITED",
        entity="clients", entity_id=client.id,
    )
    return client, raw, invite_row.expires_at


def reset(db: Session, *, actor_id: int, client_id: int, now: datetime) -> tuple[Client, str, datetime]:
    """مفعّلة/مقفلة → تبطل كلمة المرور الحالية + تنهي كل الجلسات + رابط
    دعوة جديد. لا تمسّ `portal_enabled` (يبقى مفعّلاً)."""
    client = _get(db, client_id)
    if not client.portal_enabled:
        raise PortalNotEnabledError("بوابة العميل معطّلة")
    client.portal_password_hash = None
    client.portal_failed_attempts = 0
    client.portal_locked_until = None
    db.flush()
    revoked = sessions.revoke_all_for_subject(db, subject_type=SessionSubjectType.CLIENT, subject_id=client.id)
    invite_row, raw = client_portal_invites.create_invite(db, client_id=client.id, created_by=actor_id, now=now)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=actor_id, action="CLIENT_PORTAL_RESET",
        entity="clients", entity_id=client.id, after={"sessions_revoked": revoked},
    )
    return client, raw, invite_row.expires_at


def disable(db: Session, *, actor_id: int, client_id: int, now: datetime) -> Client:
    """يُنهي كل جلسات العميل النشطة فوراً (طلب مالك صريح) + يُبطل كلمة
    المرور وأي دعوة حيّة — إعادة التفعيل تبدأ من الصفر دوماً عبر `enable`."""
    client = _get(db, client_id)
    client.portal_enabled = False
    client.portal_password_hash = None
    client.portal_failed_attempts = 0
    client.portal_locked_until = None
    db.flush()
    client_portal_invites.revoke_live_invite(db, client_id=client.id, now=now)
    revoked = sessions.revoke_all_for_subject(db, subject_type=SessionSubjectType.CLIENT, subject_id=client.id)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=actor_id, action="CLIENT_PORTAL_DISABLED",
        entity="clients", entity_id=client.id, after={"sessions_revoked": revoked},
    )
    return client


def unlock(db: Session, *, actor_id: int, client_id: int) -> Client:
    """يُصفِّر عدّاد المحاولات الفاشلة فقط — لا يمسّ كلمة المرور ولا الجلسات."""
    client = _get(db, client_id)
    client.portal_failed_attempts = 0
    client.portal_locked_until = None
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=actor_id, action="CLIENT_PORTAL_UNLOCKED",
        entity="clients", entity_id=client.id,
    )
    return client

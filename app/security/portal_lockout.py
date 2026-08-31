"""قفل حساب بوابة العميل بعد محاولات فاشلة — §٧-٦/٧-١: نفس سياسة قفل
الموظف (٥ محاولات، ١٥ دقيقة) لكن على حقول `Client.portal_*` المنفصلة —
`lockout.py` القائم مربوط بأسماء حقول `User` حرفياً (`failed_attempts`/
`locked_until`) فلا يصلح لإعادة استخدام مباشر هنا.

لا `datetime.now` هنا — `now` يُحقن دائماً من المستدعي (نفس قاعدة المحرك).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Client

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class PortalAccountLockedError(Exception):
    def __init__(self, locked_until: datetime):
        self.locked_until = locked_until
        super().__init__(f"الحساب مقفل حتى {locked_until.isoformat()}")


def check_not_locked(client: Client, now: datetime) -> None:
    if client.portal_locked_until is not None and client.portal_locked_until > now:
        raise PortalAccountLockedError(client.portal_locked_until)


def record_failed_attempt(db: Session, client: Client, now: datetime) -> None:
    client.portal_failed_attempts += 1
    if client.portal_failed_attempts >= MAX_FAILED_ATTEMPTS:
        client.portal_locked_until = now + LOCKOUT_DURATION
        client.portal_failed_attempts = 0
    db.flush()


def reset_failed_attempts(db: Session, client: Client) -> None:
    client.portal_failed_attempts = 0
    client.portal_locked_until = None
    db.flush()

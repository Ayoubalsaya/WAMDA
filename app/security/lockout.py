"""قفل الحساب بعد محاولات فاشلة — §٧-١: قفل ١٥ دقيقة بعد ٨ محاولات فاشلة (= حدّ معدل الدخول لكل عنوان، ٢٠٢٦-١٠-١٢).

لا `datetime.now` هنا — `now` يُحقن دائماً من المستدعي (نفس قاعدة المحرك).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import User

# يساوي `PRODUCTION_MAX_LOGIN_RATE_LIMIT`: الرقم المعروض للمستخدم «بقيت N محاولات» مصدره عدّاد العنوان، فلا يجوز أن يقفل
# الحساب قبل أن يبلغ العدّاد صفراً في نافذة واحدة (وإلا كذبت الرسالة).
MAX_FAILED_ATTEMPTS = 8
LOCKOUT_DURATION = timedelta(minutes=15)


class AccountLockedError(Exception):
    def __init__(self, locked_until: datetime):
        self.locked_until = locked_until
        super().__init__(f"الحساب مقفل حتى {locked_until.isoformat()}")


def check_not_locked(user: User, now: datetime) -> None:
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLockedError(user.locked_until)


def record_failed_attempt(db: Session, user: User, now: datetime) -> None:
    user.failed_attempts += 1
    if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = now + LOCKOUT_DURATION
        user.failed_attempts = 0
    db.flush()


def reset_failed_attempts(db: Session, user: User) -> None:
    user.failed_attempts = 0
    user.locked_until = None
    db.flush()

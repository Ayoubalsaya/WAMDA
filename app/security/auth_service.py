"""تدفّق الدخول بخطوتين — §٧-١: خطوة ١ (اسم مستخدم/كلمة مرور) ثم خطوة ٢
(TOTP، إلزامي للمدير والمحاسب دائماً). أول دخول بلا `totp_secret` مُسجَّل
يدخل مسار **تسجيل** (يُنشئ سرّاً مرشَّحاً، يُثبَّت فقط بعد تحقّق ناجح من
كوده — لا يُخزَّن سرّ لم يُؤكَّد أبداً).

كل دالة هنا تستقبل `now` صراحة — لا `datetime.now` مباشر (نفس قاعدة المحرك).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Session as SessionModel
from app.models import User
from app.models.enums import SessionSubjectType
from app.security import audit, backup_codes, lockout, passwords, sessions, totp

_ADMIN_ACCOUNTANT_ROLES = ("ADMIN", "ACCOUNTANT")


class InvalidCredentialsError(Exception):
    pass


class InvalidTwoFactorCodeError(Exception):
    pass


class TotpSetupRequiredError(Exception):
    """أول دخول لهذا المستخدم — لا `totp_secret` مُثبَّت بعد."""

    def __init__(self, candidate_secret: str, provisioning_uri: str):
        self.candidate_secret = candidate_secret
        self.provisioning_uri = provisioning_uri


@dataclass
class LoginResult:
    session: SessionModel
    raw_token: str
    must_change_password: bool
    backup_codes: Optional[list[str]] = None   # عند أول إعداد 2FA فقط
    backup_codes_remaining: Optional[int] = None  # عند الدخول برمز احتياطي


def login_step1(db: Session, *, username: str, password: str, now: datetime) -> User:
    """يتحقق من اسم المستخدم/كلمة المرور فقط — لا جلسة تُنشأ هنا، ولا قرار
    بشأن TOTP (`user.totp_secret is None` قرار المستدعي حصراً — راجع
    `generate_totp_setup_challenge` أدناه). كان القرار هنا سابقاً فيرفع
    `TotpSetupRequiredError` دائماً بصرف النظر عمّا إذا كان المستدعي
    يحمل بيانات إكمال التسجيل بالفعل، فيمنع أي إكمال فعلياً — علّة حقيقية
    اكتُشفت بواسطة `tests/test_auth_api.py`.
    """
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise InvalidCredentialsError("اسم المستخدم أو كلمة المرور غير صحيحة")

    lockout.check_not_locked(user, now)

    if not passwords.verify_password(password, user.password_hash):
        lockout.record_failed_attempt(db, user, now)
        raise InvalidCredentialsError("اسم المستخدم أو كلمة المرور غير صحيحة")

    return user


def generate_totp_setup_challenge(user: User) -> TotpSetupRequiredError:
    """يُستدعى من المستدعي (الموجّه) حين يقرر أن `user.totp_secret is None`
    يستوجب بدء تسجيل TOTP — لا يُخزَّن أي شيء، مجرد سرّ مرشَّح."""
    secret = totp.generate_totp_secret()
    return TotpSetupRequiredError(secret, totp.totp_provisioning_uri(secret, username=user.username))

    return user


def login_step2_verify(
    db: Session,
    *,
    user: User,
    totp_code: str,
    now: datetime,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
) -> LoginResult:
    """المسار العادي — `totp_secret` مُثبَّت مسبقاً."""
    if not totp.verify_totp_code(user.totp_secret, totp_code):
        lockout.record_failed_attempt(db, user, now)
        raise InvalidTwoFactorCodeError("رمز التحقق غير صحيح")
    return _finish_login(db, user=user, now=now, ip=ip, ua=ua)


def login_step2_setup(
    db: Session,
    *,
    user: User,
    candidate_secret: str,
    totp_code: str,
    now: datetime,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
) -> LoginResult:
    """تثبيت أول `totp_secret` — يُخزَّن فقط بعد تحقّق ناجح من الكود."""
    if not totp.verify_totp_code(candidate_secret, totp_code):
        lockout.record_failed_attempt(db, user, now)
        raise InvalidTwoFactorCodeError("رمز التحقق غير صحيح")
    user.totp_secret = candidate_secret
    result = _finish_login(db, user=user, now=now, ip=ip, ua=ua)
    # الرموز الاحتياطية تُنشأ وتُعرض **إلزامياً** مع أول إعداد للمصادقة (وبعد كل إعادة ضبط 2FA)
    result.backup_codes = backup_codes.generate(db, user_id=user.id, now=now)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="BACKUP_CODES_GENERATED", entity="users",
        entity_id=user.id, after={"count": len(result.backup_codes), "reason": "totp_setup"}, ip=ip,
    )
    return result


def login_step2_backup(
    db: Session, *, user: User, code: str, now: datetime, ip: Optional[str] = None, ua: Optional[str] = None,
) -> LoginResult:
    """دخول برمز احتياطي بدل رمز التطبيق. كلمة المرور تحقّقت في `login_step1` قبل هذه الدالة دائماً. الرمز الخاطئ/المستعمَل
    يُحتسب محاولة فاشلة في **نفس** عدّاد القفل. الاستعمال يُدقَّق بالعدد المتبقّي فقط (لا الرمز)."""
    if not backup_codes.consume(db, user_id=user.id, code=code, now=now):
        lockout.record_failed_attempt(db, user, now)
        raise InvalidTwoFactorCodeError("الرمز الاحتياطي غير صحيح أو سبق استعماله")
    result = _finish_login(db, user=user, now=now, ip=ip, ua=ua)
    left = backup_codes.remaining(db, user_id=user.id)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="BACKUP_CODE_LOGIN", entity="users",
        entity_id=user.id, after={"remaining": left}, ip=ip,
    )
    result.backup_codes_remaining = left
    return result


def _finish_login(
    db: Session, *, user: User, now: datetime, ip: Optional[str], ua: Optional[str]
) -> LoginResult:
    lockout.reset_failed_attempts(db, user)
    user.last_login_at = now
    db.flush()
    session_row, raw_token = sessions.create_session(
        db, subject_type=SessionSubjectType.USER, subject_id=user.id, now=now, ip=ip, ua=ua
    )
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="LOGIN_SUCCESS",
        entity="users", entity_id=user.id, ip=ip,
    )
    return LoginResult(session=session_row, raw_token=raw_token, must_change_password=user.must_change_password)


def change_password(
    db: Session, *, user: User, new_password: str, now: datetime, keep_session_id: Optional[str] = None
) -> None:
    user.password_hash = passwords.hash_password(new_password)
    user.must_change_password = False
    db.flush()
    # كل الجلسات الأخرى تُبطَل بتغيير كلمة المرور — أثر أمني قياسي
    rows = db.execute(
        select(SessionModel).where(
            SessionModel.subject_type == SessionSubjectType.USER, SessionModel.subject_id == user.id
        )
    ).scalars().all()
    for row in rows:
        if keep_session_id is not None and str(row.id) == str(keep_session_id):
            continue
        db.delete(row)
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="PASSWORD_CHANGED",
        entity="users", entity_id=user.id,
    )

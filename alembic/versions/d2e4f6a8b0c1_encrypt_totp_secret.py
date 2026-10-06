"""تشفير users.totp_secret (Fernet، TOTP_ENCRYPTION_KEY) للأسرار الموجودة

Revision ID: d2e4f6a8b0c1
Revises: c1d3e5f7a9b0
Create Date: 2026-10-06 12:05:00.000000

العمود نفسه (Text) — القيمة المشفَّرة تبدأ بـ`enc1:`. الترحيل يعمل بـSQL خام (لا بنوع العمود) ويشفّر فقط الصفوف التي بلا البادئة، فهو
قابل للإعادة بلا ضرر. بلا صفوف = لا يحتاج مفتاحاً. وجود أسرار صريحة بلا TOTP_ENCRYPTION_KEY = يتوقف بخطأ صريح ولا يمسّ شيئاً (يعمل داخل معاملة واحدة).
التراجع يفكّ التشفير (يحتاج المفتاح نفسه).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e4f6a8b0c1'
down_revision: Union[str, None] = 'c1d3e5f7a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREFIX = 'enc1:'


def _fernet(action: str):
    from cryptography.fernet import Fernet

    from app.config import settings

    if not settings.totp_encryption_key:
        raise RuntimeError(f"TOTP_ENCRYPTION_KEY غير مضبوط — لا يمكن {action} أسرار 2FA الموجودة. اضبطه في .env ثم أعد الترحيل.")
    return Fernet(settings.totp_encryption_key.encode())


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL AND totp_secret NOT LIKE :p"), {"p": PREFIX + '%'}).all()
    if not rows:
        return
    f = _fernet("تشفير")
    for uid, secret in rows:
        bind.execute(sa.text("UPDATE users SET totp_secret = :v WHERE id = :i"), {"v": PREFIX + f.encrypt(secret.encode()).decode(), "i": uid})


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, totp_secret FROM users WHERE totp_secret LIKE :p"), {"p": PREFIX + '%'}).all()
    if not rows:
        return
    f = _fernet("فكّ تشفير")
    for uid, secret in rows:
        bind.execute(sa.text("UPDATE users SET totp_secret = :v WHERE id = :i"), {"v": f.decrypt(secret[len(PREFIX):].encode()).decode(), "i": uid})

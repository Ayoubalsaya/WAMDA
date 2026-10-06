"""تجزئة كلمات المرور — bcrypt حصراً، لا نص صريح
يُخزَّن أبداً في أي عمود `*_hash`.
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("كلمة المرور لا يمكن أن تكون فارغة")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str | None) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False

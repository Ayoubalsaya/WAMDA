"""رقم الالتزام المختصر للكود **الذي حُمِّل فعلاً في هذه العملية** (٢٠٢٦-١٠-١٢).

يُحسَب مرة واحدة عند استيراد الوحدة (إقلاع الخادم) لا عند كل طلب: لو سُحب كود جديد (`git pull`) ولم تُعَد الخدمة بعد،
يبقى `/health` يُرجع الرقم القديم — وهذا هو المطلوب بالضبط للتحقق من أن الخادم يشغّل أحدث كود (قاعدة PROGRESS)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _read_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out if re.fullmatch(r"[0-9a-f]{7,12}", out) else "unknown"


COMMIT: str = _read_commit()

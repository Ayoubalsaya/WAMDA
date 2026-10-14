"""§٩ المرحلة ١٢ — حارس انحدار: لا سرّ يدخل المستودع.

فحص تاريخ Git الكامل جرى يدوياً مرة (المرحلة ١٢، نظيف). هذا الاختبار
يمنع **الانحدار**: `.env` يبقى غير متتبَّع ومحجوباً، ولا ملف متتبَّع
يحمل كلمة مرور/مفتاح فعلياً مكتوباً.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# ملفات يُسمح فيها بعناصر نائبة/بيانات اختبار
ALLOWLIST = {
    ".env.example",
    "alembic.ini",  # sqlalchemy.url = driver://user:pass@localhost/dbname (نائب)
}
ALLOWED_PREFIXES = ("tests/", "scripts/")

# استثناء ضيّق بنص السطر الكامل (لا بالملف): سطر رسالة تعليمات للمالك في سكربت تثبيت الشهادة يذكر ترويستَي PEM
# بين «» ليعرف أين يبدأ لصقه. ليس مفتاحاً ولا يحمل بايتاً منه. أي سطر آخر في الملف نفسه — ومنه سطر ترويسة مجرَّد
# أو مفتاح فعلي — يبقى مرفوضاً؛ وتغيّر نص هذا السطر يُسقط الاستثناء فيُراجَع.
ALLOWED_LINES = {
    (
        "docs/deploy/install_origin_cert.sh",
        "٢) الصق **المفتاح الخاص** (Private Key) كاملاً من «-----BEGIN PRIVATE KEY-----» إلى «-----END PRIVATE KEY-----»",
    ),
}

# أنماط سرّ حقيقي (لا عناصر نائبة)
_PATTERNS = [
    # سلسلة اتصال بكلمة مرور حرفية — يستثني الاستيفاء ({...}) والنوائب
    re.compile(r"postgresql\+psycopg://[^:\s{}]+:(?!CHANGE_ME|password|pass\b)[^@\s{}]{6,}@"),
    re.compile(r"BACKUP_ENCRYPTION_KEY\s*=\s*['\"]?[A-Za-z0-9+/=_-]{20,}"),
    re.compile(r"(?i)\b(secret|password|passwd|api[_-]?key)\s*=\s*['\"][A-Za-z0-9+/=_-]{12,}['\"]"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_env_is_gitignored_and_untracked():
    tracked = _tracked_files()
    assert ".env" not in tracked, ".env متتبَّع في Git — يجب ألا يكون"
    r = subprocess.run(["git", "check-ignore", ".env"], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ".env", ".env غير محجوب في .gitignore"


def test_no_real_secret_literal_in_tracked_files():
    offenders: list[str] = []
    for rel in _tracked_files():
        if rel in ALLOWLIST or rel.startswith(ALLOWED_PREFIXES):
            continue
        if not rel.endswith((".py", ".ini", ".cfg", ".toml", ".yml", ".yaml", ".env", ".sh", ".ts", ".tsx", ".json", ".md")):
            continue
        p = REPO / rel
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in _PATTERNS:
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                if (rel, text.splitlines()[line_no - 1].strip()) in ALLOWED_LINES:
                    continue
                offenders.append(f"{rel}:{line_no}: {m.group(0)[:60]}")
    assert not offenders, "سرّ محتمل مكتوب في ملف متتبَّع:\n" + "\n".join(offenders)


@pytest.mark.skipif(
    subprocess.run(["git", "rev-parse", "--git-dir"], cwd=REPO, capture_output=True).returncode != 0,
    reason="ليس مستودع Git",
)
def test_git_history_has_no_env_file_blob():
    """`.env` لم يُلتزَم قط في أي commit — لا حاجة لإعادة كتابة التاريخ."""
    out = subprocess.run(
        ["git", "log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout
    added = {line.strip() for line in out.splitlines() if line.strip()}
    assert ".env" not in added, ".env ظهر في تاريخ Git — يتطلب تنظيف تاريخ (أبلِغ المالك)"

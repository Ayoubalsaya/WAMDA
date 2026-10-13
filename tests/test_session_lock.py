"""قفل جلسة الاختبارات (٢٠٢٦-١٠-١٢): تشغيل ثانٍ لـpytest على قاعدة الاختبار نفسها يفشل فوراً برسالة واضحة بدل أن يتعارض ويعلق.

الجلسة الحالية تحمل القفل (conftest.pytest_sessionstart)، فأي `pytest` فرعي هنا هو «التشغيل الثاني» فعلاً."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from tests.conftest import TEST_DATABASE_URL
from tests.session_lock import SessionLock, database_name

ROOT = Path(__file__).resolve().parent.parent


def _pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )


def test_second_pytest_run_fails_fast_with_a_clear_message():
    started = time.monotonic()
    out = _pytest("tests/test_security_units.py", "-q")
    assert out.returncode == 3, (out.returncode, out.stdout[-1500:], out.stderr[-1500:])
    assert "تشغيل اختبارات آخر قيد العمل" in out.stdout + out.stderr
    assert database_name(TEST_DATABASE_URL) in out.stdout + out.stderr
    assert "wamda-tests pid=" in out.stdout + out.stderr, "يجب أن تُسمّي الرسالةَ صاحب القفل"
    assert time.monotonic() - started < 60, "الفشل يجب أن يكون فورياً لا بعد انتظار"
    assert "passed" not in out.stdout, "لا اختبار يجب أن يعمل"


def test_collect_only_is_not_blocked_by_a_running_session():
    out = _pytest("--collect-only", "-q", "tests/test_security_units.py")
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])


def test_lock_is_exclusive_and_released_on_release():
    url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/wamda_lock_selftest_test"  # مفتاح مستقل عن قفل الجلسة الحقيقي
    first, second, third = (SessionLock(url, label=f"selftest-{i}") for i in range(3))
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        assert "selftest-0" in (second.holder() or "")
        first.release()
        assert third.acquire() is True, "إغلاق صاحب القفل يحرّره فوراً"
    finally:
        for lock in (first, second, third):
            lock.release()


def test_different_test_databases_do_not_block_each_other():
    base = TEST_DATABASE_URL.rsplit("/", 1)[0]
    a, b = SessionLock(base + "/wamda_a_test", label="a"), SessionLock(base + "/wamda_b_test", label="b")
    try:
        assert a.acquire() and b.acquire()
    finally:
        a.release()
        b.release()

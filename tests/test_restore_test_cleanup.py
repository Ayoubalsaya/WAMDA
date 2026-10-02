"""`restore-test` لا تترك قاعدة مؤقتة أبداً (٢٠٢٦-١٠-٠٣): الأداة ستعمل أسبوعياً على السيرفر.

وُجدت `wamda_restore_test_…` يتيمة على الخادم. الأسباب الممكنة التي سُدَّت: (١) الحذف كان «بأفضل جهد» صامتاً — فشله لا
يُكتشف؛ (٢) تشغيلة ماتت قسراً (kill/انقطاع) لا يكنسها أحد؛ (٣) قطع SIGTERM لا يمرّ بـ`finally`.
الاختبارات تستعمل PostgreSQL حقيقياً (create/drop)، وتُهمَل إن لم تُضبَط أدوات Postgres."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(not settings.psql_path and not settings.pg_dump_path, reason="أدوات Postgres غير مضبوطة محلياً")

from app.cli import pg_tools, restore  # noqa: E402
from app.cli.pg_tools import PgToolError, create_database, database_exists, drop_database, list_databases  # noqa: E402


@pytest.fixture(autouse=True)
def _no_leftovers_after_test():
    yield
    for name in list_databases(restore.RESTORE_TEST_PREFIX):  # حتى لو فشل اختبار هنا فلا نترك أيتاماً
        drop_database(name)


@pytest.fixture()
def fake_pipeline(monkeypatch):
    """استعادة وفحص مُزيَّفان (لا pg_restore ولا نسخة حقيقية) — الاختبار هنا للتنظيف فقط، والقاعدة المؤقتة حقيقية."""
    created = []

    class _Report:
        ok = True
        balance_diffs = swift_problems = lot_problems = []

    monkeypatch.setattr(restore, "restore_into", lambda **kw: None)
    from app.engine import recompute

    monkeypatch.setattr(recompute, "verify", lambda db: _Report())
    orig_create = restore.create_database

    def tracking_create(name):
        created.append(name)
        orig_create(name)

    monkeypatch.setattr(restore, "create_database", tracking_create)
    return created


def _run():
    return restore.restore_test(backup_path=Path("unused.enc"))


def test_success_drops_the_temp_database(fake_pipeline):
    outcome = _run()
    assert outcome.ok
    assert len(fake_pipeline) == 1 and not database_exists(fake_pipeline[0])


def test_restore_failure_drops_and_original_error_wins(fake_pipeline, monkeypatch):
    monkeypatch.setattr(restore, "restore_into", lambda **kw: (_ for _ in ()).throw(PgToolError("فشل pg_restore مُصطنَع")))
    with pytest.raises(PgToolError, match="pg_restore مُصطنَع"):
        _run()
    assert not database_exists(fake_pipeline[0])


def test_verify_failure_drops(fake_pipeline, monkeypatch):
    from app.engine import recompute

    monkeypatch.setattr(recompute, "verify", lambda db: (_ for _ in ()).throw(RuntimeError("verify مُصطنَع")))
    with pytest.raises(RuntimeError, match="verify مُصطنَع"):
        _run()
    assert not database_exists(fake_pipeline[0])


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit])
def test_interrupt_and_sigterm_style_exits_still_drop(fake_pipeline, monkeypatch, exc):
    monkeypatch.setattr(restore, "restore_into", lambda **kw: (_ for _ in ()).throw(exc()))
    with pytest.raises(exc):
        _run()
    assert not database_exists(fake_pipeline[0])


def test_drop_retries_when_the_first_attempt_fails(fake_pipeline, monkeypatch):
    real_drop_once = pg_tools._drop_once
    calls = {"n": 0}

    def flaky(name):
        calls["n"] += 1
        if calls["n"] == 1:
            return  # الحذف الأول «ينجح» بلا أثر (اتصال متأخر الإغلاق) — القاعدة باقية
        real_drop_once(name)

    monkeypatch.setattr(pg_tools, "_drop_once", flaky)
    monkeypatch.setattr(pg_tools.time, "sleep", lambda s: None)
    _run()
    assert calls["n"] >= 2 and not database_exists(fake_pipeline[0])


def test_permanent_drop_failure_is_loud_not_silent(fake_pipeline, monkeypatch):
    monkeypatch.setattr(pg_tools, "_drop_once", lambda name: None)  # لا يحذف أبداً
    monkeypatch.setattr(pg_tools.time, "sleep", lambda s: None)
    with pytest.raises(PgToolError, match="تعذّر حذف قاعدة البيانات المؤقتة"):
        _run()
    assert database_exists(fake_pipeline[0])  # الواقع كما أُبلِغ — ينظّفه الـfixture أعلاه


def test_failure_plus_drop_failure_keeps_the_original_error_and_warns(fake_pipeline, monkeypatch, capsys):
    monkeypatch.setattr(restore, "restore_into", lambda **kw: (_ for _ in ()).throw(PgToolError("الأصلي")))
    monkeypatch.setattr(pg_tools, "_drop_once", lambda name: None)
    monkeypatch.setattr(pg_tools.time, "sleep", lambda s: None)
    with pytest.raises(PgToolError, match="الأصلي"):
        _run()
    assert "تعذّر حذف قاعدة البيانات المؤقتة" in capsys.readouterr().err


def test_stale_orphans_from_dead_runs_are_swept_before_starting(fake_pipeline):
    create_database(f"{restore.RESTORE_TEST_PREFIX}orphan_one")
    create_database(f"{restore.RESTORE_TEST_PREFIX}orphan_two")
    _run()
    assert list_databases(restore.RESTORE_TEST_PREFIX) == []


def test_sweep_only_touches_the_restore_test_prefix():
    create_database("wamda_restore_keepme_not_a_match")
    try:
        assert restore.sweep_stale_restore_databases() == []
        assert database_exists("wamda_restore_keepme_not_a_match")
    finally:
        drop_database("wamda_restore_keepme_not_a_match")


def test_real_cycle_with_a_real_backup_leaves_nothing(tmp_path):
    from app.cli import backup

    if not settings.backup_encryption_key:
        pytest.skip("BACKUP_ENCRYPTION_KEY غير مضبوط")
    d = tmp_path / "b"
    d.mkdir()
    result = backup.run(dest_dir=d)
    outcome = restore.restore_test(backup_path=Path(result["local_path"]))
    assert outcome.ok
    assert list_databases(restore.RESTORE_TEST_PREFIX) == []

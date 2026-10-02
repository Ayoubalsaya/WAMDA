"""`alembic downgrade base` ثم `upgrade head` يعملان على قاعدة مؤقتة (RUNBOOK.md الخطوة ١ تعتمد عليهما).

اكتُشف ٢٠٢٦-١٠-٠٢ عند تصفير قاعدة التطوير فعلياً: `downgrade` الترحيل `220e41749c52` كان يستدعي
`drop_constraint(None, …)` (قيد بلا اسم) فيفشل ويُلغي العملية كلها — لم يختبره أحد قبلها.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.config import settings
from tests import factories as f

ROOT = Path(__file__).resolve().parent.parent


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT)}
    proc = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, f"alembic {' '.join(args)} فشل:\n{proc.stderr[-1500:]}"


def test_downgrade_base_then_upgrade_head_roundtrip():
    name = f"wamda_migtest_{f.uid()[:8].lower()}"
    admin_url = re.sub(r"/[^/?]+(\?.*)?$", "/postgres", settings.database_url)
    scratch_url = re.sub(r"/[^/?]+(\?.*)?$", f"/{name}", settings.database_url)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        _alembic(scratch_url, "upgrade", "head")
        _alembic(scratch_url, "downgrade", "base")
        _alembic(scratch_url, "upgrade", "head")
        eng = create_engine(scratch_url)
        with eng.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('public.lot_consumptions')")).scalar() is not None
        eng.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()

"""مسارات الاستعادة بسؤال الأمان محذوفة بالكامل (٢٠٢٦-١٠-٠٦، تدقيق U-01): بلا حدّ معدل ولا عدّ فشل ولا إبطال جلسات — كانت
تتيح الاستيلاء على حساب عميل البوابة (كلمة مرور وحدها). البدائل: الدعوات (`/clients/{id}/portal/reset`) والرموز الاحتياطية
وأوامر الخادم (`reset-2fa`/`reset-admin-password`)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.main import app
from tests.test_edit_prefill_api import client  # noqa: F401


def test_no_recover_route_exists():
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert not [p for p in paths if "recover" in p], [p for p in paths if "recover" in p]


@pytest.mark.parametrize("path", ["/auth/recover/start", "/auth/recover/complete", "/portal/recover/start", "/portal/recover/complete"])
def test_recover_paths_are_gone(client, path):
    assert client.post(path, json={}).status_code in (404, 405)


def test_no_security_question_field_anywhere_in_the_api_schema():
    blob = str(app.openapi()).lower()
    assert "security_question" not in blob and "security_answer" not in blob and "recover" not in blob


def test_security_question_columns_are_dropped(db):
    cols = {r[0] for r in db.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name IN ('users','clients') AND column_name ILIKE '%security%'"))}
    assert not cols, cols

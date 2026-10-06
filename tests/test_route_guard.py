"""حارس: لا يجوز لأي اختبار عام يمرّ على المسارات أن ينجح فارغاً بعد ترقية FastAPI.
(1) المُعدِّد المشترك يفشل إن وجد أقل من MIN_ROUTES مساراً. (2) كل اختبار يعدّ المسارات يستخدمه ولا يقرأ `app.routes` مباشرة."""

import pathlib
import re

from app.main import app
from tests.route_utils import MIN_ROUTES, all_routes

TESTS = pathlib.Path(__file__).parent


def test_enumerator_sees_enough_routes():
    assert len(all_routes(app)) >= MIN_ROUTES


def test_enumerator_fails_when_too_few_routes():
    import pytest
    from fastapi import FastAPI

    tiny = FastAPI()

    @tiny.get("/x")
    def x():
        return 1

    with pytest.raises(AssertionError):
        all_routes(tiny)


def test_no_test_reads_app_routes_directly():
    bad = []
    for f in TESTS.glob("test_*.py"):
        if f.name == "test_route_guard.py":
            continue
        src = f.read_text(encoding="utf-8")
        if re.search(r"\bapp\.routes\b", src):
            bad.append(f.name)
    assert not bad, f"اختبارات تقرأ app.routes مباشرة بدل all_routes: {bad}"

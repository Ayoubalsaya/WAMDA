"""requirements.txt وحده يكفي لتشغيل التطبيق (٢٠٢٦-١٠-٠٦، تدقيق U-03): بيئة افتراضية جديدة، يُثبَّت فيها الملف كاملاً، ثم تُستورد
كل وحدات `app` **وكل حزمة خارجية** يستوردها أي سطر `import` في `app/` (بما فيها الاستيرادات الكسولة داخل الدوال — كـ`cryptography`
في `app/cli/backup.py` التي كانت تفشل على سيرفر نظيف دون أن يلاحظ استيراد الوحدات وحده)."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_CHECK = textwrap.dedent('''
    import ast, importlib, pkgutil, sys
    from pathlib import Path

    import app

    failures = []
    for m in pkgutil.walk_packages(app.__path__, "app."):
        if m.name.endswith("__main__"):
            continue
        try:
            importlib.import_module(m.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"import {m.name}: {type(exc).__name__}: {exc}")

    stdlib = set(sys.stdlib_module_names)
    third_party = set()
    for path in Path("app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                top = n.split(".")[0]
                if top not in stdlib and top != "app":
                    third_party.add(top)
    for top in sorted(third_party):
        try:
            importlib.import_module(top)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"third-party {top}: {type(exc).__name__}: {exc}")
    # سلوك لا استيراد فقط: QR كما يولّده التطبيق (يحتاج Pillow فعلياً)، وZoneInfo لمنطقة العمل
    try:
        from app.documents.qr import qr_data_uri
        uri = qr_data_uri("wamda-clean-install")
        if not uri.startswith("data:image/png;base64,") or len(uri) < 200:
            failures.append("qr_data_uri: ناتج غير متوقع")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"qr_data_uri: {type(exc).__name__}: {exc}")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Africa/Tripoli")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"ZoneInfo: {type(exc).__name__}: {exc}")
    print("THIRD_PARTY", sorted(third_party))
    if failures:
        print(chr(10).join(failures))
        sys.exit(1)
''')


@pytest.mark.timeout(1200)
def test_requirements_alone_install_and_import_every_app_module(tmp_path):
    env_dir = tmp_path / "clean"
    subprocess.run([sys.executable, "-m", "venv", str(env_dir)], check=True)
    py = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    install = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(ROOT / "requirements.txt")],
                             capture_output=True, text=True)
    assert install.returncode == 0, install.stdout[-2000:] + install.stderr[-2000:]
    import os

    env = {**os.environ, "DATABASE_URL": os.environ.get("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x_test")}
    check = subprocess.run([str(py), "-c", _CHECK], cwd=ROOT, capture_output=True, text=True, env=env)
    assert check.returncode == 0, check.stdout[-3000:] + check.stderr[-3000:]
    assert "cryptography" in check.stdout, "الفحص لم يرَ الاستيراد الكسول لـcryptography"

    # الإنتاج لا يحتاج أدوات الاختبار: لا شيء منها في البيئة النظيفة التي ثُبّت فيها requirements.txt وحده
    frozen = subprocess.run([str(py), "-m", "pip", "list", "--format=freeze", "--disable-pip-version-check"],
                            capture_output=True, text=True, check=True).stdout
    installed = {line.split("==")[0].lower().replace("_", "-") for line in frozen.splitlines() if "==" in line}
    leaked = sorted(_dev_only_names() & installed)
    assert not leaked, f"أدوات اختبار ثُبّتت مع requirements.txt وحده: {leaked}"


def _names(path: Path) -> set[str]:
    out = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        out.add(re.split(r"[=<>!~\[;\s]", line, maxsplit=1)[0].lower().replace("_", "-"))
    return out


def _dev_only_names() -> set[str]:
    return _names(ROOT / "requirements-dev.txt") - _names(ROOT / "requirements.txt")


def test_requirements_txt_is_runtime_only_and_exactly_pinned():
    lines = [raw.split("#", 1)[0].strip() for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    specs = [l for l in lines if l]
    assert specs, "requirements.txt فارغ"
    assert not [l for l in specs if l.startswith("-")], "requirements.txt لا يضمّ ملفاً آخر (لا -r)"
    loose = [l for l in specs if "==" not in l or re.search(r"[<>~!]=?|\*", l.split("==", 1)[1])]
    assert not loose, f"إصدارات غير مثبَّتة بدقة (==): {loose}"
    names = _names(ROOT / "requirements.txt")
    forbidden = {"pytest", "pytest-timeout", "httpx", "pypdf", "psutil", "pytest-asyncio", "coverage"}
    assert not (forbidden & names), f"أدوات اختبار داخل requirements.txt: {sorted(forbidden & names)}"


def test_requirements_dev_extends_runtime_and_adds_test_tools():
    first = [l.strip() for l in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")][0]
    assert first == "-r requirements.txt"
    assert {"pytest", "pytest-timeout", "httpx", "pypdf", "psutil"} <= _dev_only_names()

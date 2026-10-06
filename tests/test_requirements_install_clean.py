"""requirements.txt وحده يكفي لتشغيل التطبيق (٢٠٢٦-١٠-٠٦، تدقيق U-03): بيئة افتراضية جديدة، يُثبَّت فيها الملف كاملاً، ثم تُستورد
كل وحدات `app` **وكل حزمة خارجية** يستوردها أي سطر `import` في `app/` (بما فيها الاستيرادات الكسولة داخل الدوال — كـ`cryptography`
في `app/cli/backup.py` التي كانت تفشل على سيرفر نظيف دون أن يلاحظ استيراد الوحدات وحده)."""

from __future__ import annotations

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

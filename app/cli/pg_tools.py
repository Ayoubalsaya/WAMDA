"""أدوات مشتركة بين backup.py/restore.py — تحليل DATABASE_URL، تحديد
مسارات pg_dump/pg_restore، وإنشاء/حذف قاعدة بيانات مؤقتة (§٩)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from app.config import settings


class PgToolError(Exception):
    pass


@dataclass
class ConnectionParams:
    host: str
    port: str
    user: str
    password: str
    dbname: str


def connection_params(database_url: str) -> ConnectionParams:
    # postgresql(+psycopg)://user:pass@host:port/db
    parsed = urlsplit(database_url.replace("+psycopg", ""))
    return ConnectionParams(
        host=parsed.hostname or "localhost",
        port=str(parsed.port or 5432),
        user=parsed.username or "",
        password=parsed.password or "",
        dbname=parsed.path.lstrip("/"),
    )


def pg_dump_executable() -> str:
    if settings.pg_dump_path:
        return settings.pg_dump_path
    found = shutil.which("pg_dump")
    if not found:
        raise PgToolError("pg_dump غير موجود على PATH — اضبط PG_DUMP_PATH في .env")
    return found


def pg_restore_executable() -> str:
    if settings.pg_restore_path:
        return settings.pg_restore_path
    found = shutil.which("pg_restore")
    if not found:
        raise PgToolError("pg_restore غير موجود على PATH — اضبط PG_RESTORE_PATH في .env")
    return found


def psql_executable() -> str:
    if settings.psql_path:
        return settings.psql_path
    found = shutil.which("psql")
    if found:
        return found
    # آخر محاولة: نفس مجلد pg_restore المضبوط صراحة (توزيعات Postgres
    # الرسمية تضع الثلاثة في نفس bin/ دائماً)
    if settings.pg_restore_path:
        sibling = Path(settings.pg_restore_path).with_name("psql.exe")
        if sibling.exists():
            return str(sibling)
    raise PgToolError("psql غير موجود على PATH — اضبط PSQL_PATH في .env")


def _run(cmd: list[str], *, password: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PGPASSWORD": password}
    return subprocess.run(cmd, env=env, capture_output=True, text=True)


def run_pg_dump(*, params: ConnectionParams, output_path: Path) -> None:
    cmd = [
        pg_dump_executable(), "-Fc", "--no-password",
        "-h", params.host, "-p", params.port, "-U", params.user,
        "-f", str(output_path), params.dbname,
    ]
    result = _run(cmd, password=params.password)
    if result.returncode != 0:
        raise PgToolError(f"فشل pg_dump: {result.stderr.strip()}")


def run_pg_restore(*, params: ConnectionParams, input_path: Path) -> None:
    cmd = [
        pg_restore_executable(), "--no-password", "--clean", "--if-exists", "--no-owner",
        "-h", params.host, "-p", params.port, "-U", params.user,
        "-d", params.dbname, str(input_path),
    ]
    result = _run(cmd, password=params.password)
    # pg_restore يُعيد رمز غير صفري أحياناً حتى مع تحذيرات غير خطيرة
    # (مثل "role X does not exist" مع --no-owner) — الفحص الحقيقي هو
    # recompute-balances --verify بعدها، لا رمز الخروج وحده.
    if result.returncode != 0 and "ERROR" in result.stderr:
        raise PgToolError(f"فشل pg_restore: {result.stderr.strip()}")


def _admin_connection_params() -> ConnectionParams:
    url = settings.backup_admin_database_url or settings.database_url
    return connection_params(url)


def create_database(name: str) -> None:
    admin = _admin_connection_params()
    cmd = [
        psql_executable(), "--no-password", "-h", admin.host, "-p", admin.port, "-U", admin.user,
        "-d", "postgres", "-c", f'CREATE DATABASE "{name}"',
    ]
    result = _run(cmd, password=admin.password)
    if result.returncode != 0:
        raise PgToolError(f"فشل إنشاء قاعدة البيانات المؤقتة: {result.stderr.strip()}")


def drop_database(name: str) -> None:
    admin = _admin_connection_params()
    cmd = [
        psql_executable(), "--no-password", "-h", admin.host, "-p", admin.port, "-U", admin.user,
        "-d", "postgres", "-c", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
    ]
    _run(cmd, password=admin.password)  # تنظيف بأفضل جهد — لا يُوقِف التنفيذ عند فشله


def database_url_for(name: str) -> str:
    admin = _admin_connection_params()
    return f"postgresql+psycopg://{admin.user}:{admin.password}@{admin.host}:{admin.port}/{name}"

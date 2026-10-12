#!/usr/bin/env bash
# يُنشئ .env الإنتاج على السيرفر (بصفة wamda، لا root) — ٢٠٢٦-١٠-١٢.
#   ssh wamda@HOST 'bash -s' < docs/deploy/make_env.sh
#
# الضمانات:
#   · المفتاحان BACKUP_ENCRYPTION_KEY وTOTP_ENCRYPTION_KEY يُولَّدان هنا (Fernet) ويُكتبان في الملف مباشرة؛ لا يُطبعان
#     ولا يدخلان argv ولا أي مخرجات (printf مدمج في bash؛ المتغيّران يُمسحان بعد الكتابة).
#   · كلمتا مرور القاعدة تُقرأان من /srv/wamda/secrets/ إلى الملف مباشرة؛ لا تُطبعان.
#   · لا يستبدل .env موجوداً (يرفض). الملف 0600 ومالكه wamda.
#   · PUBLIC_BASE_URL فارغ عمداً حتى يُحدَّد النطاق (التطبيق يرفض توليد QR/روابط دعوة بدونه في الإنتاج).
#   · يتحقق في النهاية بتحميل الإعدادات في وضع الإنتاج (قيود الإقلاع: مفتاح 2FA وحدود الدخول) ويطبع قيماً غير سرّية فقط.
set -euo pipefail
set +x

APP=/srv/wamda/app
VENV=/srv/wamda/venv
ENVF=$APP/.env
SECRETS=/srv/wamda/secrets

[ ! -e "$ENVF" ] || { echo "خطأ: $ENVF موجود — لن أستبدله (احذفه يدوياً إن أردت إعادة التوليد)"; exit 1; }
[ -s "$SECRETS/db_password" ] && [ -s "$SECRETS/restore_password" ] || { echo "خطأ: ملفات كلمات المرور غير موجودة في $SECRETS"; exit 1; }
[ -x "$VENV/bin/python" ] || { echo "خطأ: لا venv"; exit 1; }

gen_key() { "$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'; }
BACKUP_KEY="$(gen_key)"
TOTP_KEY="$(gen_key)"
[ "${#BACKUP_KEY}" -eq 44 ] && [ "${#TOTP_KEY}" -eq 44 ] && [ "$BACKUP_KEY" != "$TOTP_KEY" ] || { echo "خطأ: توليد المفتاحين"; exit 1; }
DB_PW="$(cat "$SECRETS/db_password")"
RESTORE_PW="$(cat "$SECRETS/restore_password")"

umask 077
{
  printf '%s\n' '# ومضة — إنتاج. 0600 ملك wamda. لا يُرفع لأي مستودع. أُنشئ بـdocs/deploy/make_env.sh'
  printf '%s\n' ''
  printf '%s\n' 'APP_ENV=production'
  printf '%s\n' 'WORK_TIMEZONE=Africa/Tripoli'
  printf '%s\n' ''
  printf '%s\n' '# قاعدة التطبيق (wamda_app) واتصال restore-test المنفصل (wamda_restore، CREATEDB فقط، قاعدة postgres)'
  printf 'DATABASE_URL=postgresql+psycopg://wamda_app:%s@127.0.0.1:5432/wamda_db\n' "$DB_PW"
  printf 'BACKUP_ADMIN_DATABASE_URL=postgresql+psycopg://wamda_restore:%s@127.0.0.1:5432/postgres\n' "$RESTORE_PW"
  printf '%s\n' ''
  printf '%s\n' '# حدّ الدخول الصارم (الخادم يرفض الإقلاع بأضعف من هذا في الإنتاج)'
  printf '%s\n' 'LOGIN_RATE_LIMIT_MAX=8'
  printf '%s\n' 'PORTAL_LOGIN_RATE_LIMIT_MAX=5'
  printf '%s\n' 'LOGIN_RATE_LIMIT_WINDOW_SECONDS=300'
  printf '%s\n' '# صحيح فقط خلف nginx يضبط X-Real-IP/X-Forwarded-For. قبل nginx الخدمة على 127.0.0.1 ولا يصلها إلا نفق SSH.'
  printf '%s\n' 'TRUST_PROXY_HEADERS=true'
  printf '%s\n' ''
  printf '%s\n' 'STAFF_IDLE_TIMEOUT_MINUTES=30'
  printf '%s\n' 'PORTAL_IDLE_TIMEOUT_MINUTES=15'
  printf '%s\n' ''
  printf '%s\n' '# يحفظ المالك نسخة من المفتاحين بنفسه خارج السيرفر وخارج git والنسخ السحابية. فقدانهما = تعذّر فكّ النسخ/أسرار 2FA.'
  printf 'BACKUP_ENCRYPTION_KEY=%s\n' "$BACKUP_KEY"
  printf 'TOTP_ENCRYPTION_KEY=%s\n' "$TOTP_KEY"
  printf '%s\n' ''
  printf '%s\n' '# فارغ عمداً حتى يُحدَّد النطاق: بدونه يرفض التطبيق (503) توليد مستند بـQR أو رابط دعوة. لا عنوان IP.'
  printf '%s\n' 'PUBLIC_BASE_URL='
  printf '%s\n' ''
  printf '%s\n' '# وجهة النسخ خارج السيرفر: قرار المالك معلَّق (rclone). فارغة = `backup` يفشل (exit≠0) في الإنتاج عمداً — لا فشل صامت.'
  printf '%s\n' 'BACKUP_OFFSITE_DIR='
} > "$ENVF"
chmod 600 "$ENVF"
unset BACKUP_KEY TOTP_KEY DB_PW RESTORE_PW

echo "--- الملف"
stat -c '%a %U:%G %n  (%s بايت، %h سطر-رابط)' "$ENVF"
echo "عدد المفاتيح المضبوطة (غير فارغة): $(grep -cE '^[A-Z_]+=.+' "$ENVF") من $(grep -cE '^[A-Z_]+=' "$ENVF")"
echo "--- ignored by git؟"
( cd "$APP" && git check-ignore -v .env ) || echo "تحذير: .env غير مُتجاهَل في git!"
( cd "$APP" && git status --porcelain | head -5; echo "(git status أعلاه؛ فارغ = نظيف)" )

echo "--- تحميل الإعدادات في وضع الإنتاج (قيم غير سرّية فقط)"
cd "$APP"
"$VENV/bin/python" -W ignore - <<'PYEOF'
from urllib.parse import urlsplit
from app.config import settings
u = urlsplit(settings.database_url.replace("+psycopg", ""))
r = urlsplit((settings.backup_admin_database_url or "").replace("+psycopg", ""))
print("app_env                 :", settings.app_env)
print("DATABASE_URL            :", f"{u.username}@{u.hostname}:{u.port}{u.path}")
print("BACKUP_ADMIN_DATABASE   :", f"{r.username}@{r.hostname}:{r.port}{r.path}")
print("totp_encryption_key set :", bool(settings.totp_encryption_key), len(settings.totp_encryption_key or ""))
print("backup_encryption_key   :", bool(settings.backup_encryption_key), len(settings.backup_encryption_key or ""))
print("keys distinct           :", settings.totp_encryption_key != settings.backup_encryption_key)
print("login limits            :", settings.login_rate_limit_max, settings.portal_login_rate_limit_max, settings.login_rate_limit_window_seconds)
print("trust_proxy_headers     :", settings.trust_proxy_headers)
print("idle timeouts (min)     :", settings.staff_idle_timeout_minutes, settings.portal_idle_timeout_minutes)
print("work_timezone           :", settings.work_timezone)
print("public_base_url         :", repr(settings.public_base_url))
print("backup_offsite_dir      :", repr(settings.backup_offsite_dir))
PYEOF

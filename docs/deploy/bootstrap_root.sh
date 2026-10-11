#!/usr/bin/env bash
# تأسيس ومضة على السيرفر الجديد (DEPLOY_PLAN.md §١–§٢) — يُشغَّل كـ root.
# ⚠ لا يُشغَّل قبل مراجعة مستقلة. كل مرحلة أمر منفصل، تنتهي بتحقق يوقف السكربت عند أول فشل.
#
#   ١) packages        python3-venv · git · مكتبات نظام Chromium/Playwright (best-effort)
#   ٢) user            مستخدم wamda (بلا sudo، كلمة مروره مقفلة، بلا مفتاح SSH) و/srv/wamda بصلاحيات 750
#   ٣) postgres        PostgreSQL 18 من مستودع PGDG الرسمي · يستمع على localhost فقط
#   ٤) dbrole          الدور wamda_app (بلا أي صلاحية إدارية) + القاعدة wamda_db + كلمة مرور مولَّدة لا تُطبع
#   ٥) sudoers         wamda يتحكم بخدمته فقط: systemctl start|stop|restart|status wamda
#   ٦) deploykey       مفتاح deploy لـwamda — يطبع العام فقط + خطوات إضافته في GitHub (قراءة فقط)
#   ٧) verify-deploykey بعد إضافة المفتاح في GitHub: اتصال + ls-remote + التأكد أنه للقراءة فقط
#   ٨) report          عرض الحالة (قراءة فقط)
#
# لا nginx ولا certbot (النطاق الفرعي لم يُحدَّد). لا مساس بـsshd/ufw/fail2ban.
#
# التشغيل من جهازك (السكربت يصل عبر stdin، لا نسخ ملف للسيرفر):
#   ssh root@HOST 'bash -s -- packages'         < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- user'             < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- postgres'         < docs/deploy/bootstrap_root.sh   # PG_LOCALE=… اختياري
#   ssh root@HOST 'bash -s -- dbrole'           < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- sudoers'          < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- deploykey'        < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- verify-deploykey' < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- report'           < docs/deploy/bootstrap_root.sh
#
# الضمانات:
#   · كلمة مرور wamda_app تُولَّد على السيرفر (openssl)، تُحفظ في /srv/wamda/secrets/db_password (0600 wamda)،
#     ولا تُطبع ولا تدخل السجل ولا الـargv. لا تُعاد توليدها إن وُجد الدور (يتطلب قراراً صريحاً).
#   · المفتاح الخاص للـdeploy لا يُطبع أبداً؛ يُطبع العام فقط. بصمة github.com تُثبَّت من بصمتها المنشورة.
#   · الدور wamda_app لا يستطيع إنشاء أدوار/قواعد ولا الاتصال بـpostgres/template1 (يُختبَر فعلاً).
#   · السجل: /var/log/wamda-bootstrap.log (لا أسرار فيه).

set -euo pipefail

WAMDA_USER=wamda
WAMDA_HOME=/srv/wamda
SECRETS_DIR=$WAMDA_HOME/secrets
DB_PW_FILE=$SECRETS_DIR/db_password
PG_MAJOR=18
PG_LOCALE="${PG_LOCALE:-C.UTF-8}"      # يُحدَّد عند إنشاء العنقود ولا يتغيّر لاحقاً
DB_NAME=wamda_db
DB_ROLE=wamda_app
SUDOERS_FILE=/etc/sudoers.d/wamda-systemctl
DEPLOY_KEY=$WAMDA_HOME/.ssh/id_ed25519_deploy
REPO_PATH='Ayoubalsaya/WAMDA.git'
# بصمة ed25519 المنشورة لـgithub.com (docs.github.com ← GitHub's SSH key fingerprints) — راجعها عند المراجعة
GITHUB_ED25519_FP='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
LOG=/var/log/wamda-bootstrap.log

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\nخطأ: %s\n' "$*" >&2; exit 1; }
chk() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then printf '  ✔ %s\n' "$d"; else die "فشل التحقق: $d"; fi; }
chk_not() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then die "فشل التحقق (كان يجب أن يُرفض): $d"; else printf '  ✔ %s\n' "$d"; fi; }

apt_get() {
  apt-get -y -o DPkg::Lock::Timeout=300 \
    -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef "$@"
}

as_wamda() { runuser -u "$WAMDA_USER" -- env HOME="$WAMDA_HOME" "$@"; }
# SQL بصفة postgres عبر مقبس محلي (peer). الأمر عبر stdin أو -c.
pgq() { runuser -u postgres -- psql -X -q -At -v ON_ERROR_STOP=1 "$@"; }
# اتصال wamda_app عبر TCP؛ كلمة المرور تُقرأ من الملف لهذا الأمر وحده (لا تُطبع)
app_psql() { PGPASSWORD="$(cat "$DB_PW_FILE")" psql -X -q -At -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U "$DB_ROLE" "$@"; }

pg_scalar() { pgq -d postgres -c "$1"; }
# 5432 يستمع على loopback فقط (v4 أو v6) وبلا أي عنوان آخر
pg_loopback_only() {
  local a; a="$(ss -H -tln 'sport = :5432' | awk '{print $4}')"
  [ -n "$a" ] && ! grep -qvE '^(127\.0\.0\.1|\[::1\]):5432$' <<<"$a"
}

need_wamda() { id "$WAMDA_USER" >/dev/null 2>&1 || die "المستخدم $WAMDA_USER غير موجود — نفّذ مرحلة user أولاً"; }

# ───────────────────────── ١) packages ─────────────────────────
phase_packages() {
  say "apt update + الحزم الأساسية"
  apt_get update
  apt_get install ca-certificates curl gnupg openssl git python3 python3-venv

  # مكتبات Chromium (Ubuntu 24.04: أسماء t64). best-effort: الاسم الغائب يُتخطّى بتحذير.
  # المرجع النهائي: `playwright install-deps chromium` من الـvenv في مرحلة الكود.
  say "مكتبات نظام Chromium/Playwright"
  local want=(libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libdbus-1-3
              libxkbcommon0 libatspi2.0-0t64 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1
              libpango-1.0-0 libcairo2 libasound2t64 libx11-6 libxcb1 libxext6 fonts-liberation)
  local have=() p
  for p in "${want[@]}"; do
    if apt-cache show "$p" >/dev/null 2>&1; then have+=("$p"); else echo "  ⚠ غير موجودة في المستودع: $p (تُتخطّى)"; fi
  done
  apt_get install "${have[@]}"

  say "تحقق"
  chk "python3 ≥ 3.12" python3 -c 'import sys; assert sys.version_info >= (3,12)'
  local t; t="$(mktemp -d)"
  chk "python3 -m venv يعمل (ensurepip)" bash -c "python3 -m venv '$t/v' && '$t/v/bin/python' -c 'import ensurepip, venv'"
  rm -rf "$t"
  chk "git موجود" git --version
  chk "libnss3 مثبّتة" dpkg -s libnss3
  chk "libgbm1 مثبّتة" dpkg -s libgbm1
}

# ───────────────────────── ٢) user ─────────────────────────
phase_user() {
  if id "$WAMDA_USER" >/dev/null 2>&1; then
    say "المستخدم $WAMDA_USER موجود — لا إعادة إنشاء"
  else
    say "إنشاء المستخدم $WAMDA_USER (home=$WAMDA_HOME)"
    useradd --create-home --home-dir "$WAMDA_HOME" --shell /bin/bash --user-group "$WAMDA_USER"
  fi
  passwd -l "$WAMDA_USER" >/dev/null           # لا دخول بكلمة مرور؛ ولا مفتاح SSH مُضاف (لا دخول إطلاقاً حتى يقرر المالك)
  chown "$WAMDA_USER:$WAMDA_USER" "$WAMDA_HOME"
  chmod 750 "$WAMDA_HOME"
  install -d -o "$WAMDA_USER" -g "$WAMDA_USER" -m 0700 "$WAMDA_HOME/backups" "$SECRETS_DIR" "$WAMDA_HOME/.ssh"

  say "تحقق"
  chk "uid عادي (≥1000)" bash -c "[ \"\$(id -u $WAMDA_USER)\" -ge 1000 ]"
  chk "ليس في sudo/adm/lxd/docker/root" bash -c "! id -nG $WAMDA_USER | tr ' ' '\n' | grep -qxE 'sudo|adm|lxd|docker|root|admin'"
  chk "كلمة المرور مقفلة" bash -c "passwd -S $WAMDA_USER | awk '{print \$2}' | grep -qx L"
  chk "/srv/wamda بصلاحيات 750 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U:%G' $WAMDA_HOME)\" = '750 $WAMDA_USER:$WAMDA_USER' ]"
  chk "backups وsecrets و.ssh بصلاحيات 700" bash -c "[ \"\$(stat -c %a $WAMDA_HOME/backups $SECRETS_DIR $WAMDA_HOME/.ssh | sort -u)\" = 700 ]"
  chk "لا authorized_keys لـwamda (لا دخول SSH)" bash -c "[ ! -e $WAMDA_HOME/.ssh/authorized_keys ]"
  chk "لا sudo لـwamda بعد (قبل مرحلة sudoers)" bash -c "sudo -l -U $WAMDA_USER 2>&1 | grep -qiE 'not allowed|may not run'"
}

# ───────────────────────── ٣) postgres ─────────────────────────
phase_postgres() {
  say "مستودع PGDG الرسمي (سكربت postgresql-common)"
  apt_get install postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  apt-cache policy "postgresql-$PG_MAJOR" | grep -q 'apt.postgresql.org' \
    || die "postgresql-$PG_MAJOR غير متاحة من apt.postgresql.org"

  say "تثبيت postgresql-$PG_MAJOR"
  apt_get install "postgresql-$PG_MAJOR"

  # الخادم الافتراضي في Ubuntu (16) لا يجوز أن يُثبَّت عرَضاً
  if pg_lsclusters --no-header | awk '{print $1}' | grep -qvx "$PG_MAJOR"; then
    die "وُجد عنقود بإصدار آخر غير $PG_MAJOR — توقفت: $(pg_lsclusters --no-header | awk '{print $1"/"$2}' | paste -sd' ')"
  fi

  # لغة العنقود تُحدَّد عند الإنشاء: إن لم تطابق PG_LOCALE ولا قواعد مستخدم بعد ← يُعاد إنشاؤه
  local cur dbs
  cur="$(pgq -d postgres -c 'SHOW lc_collate')"
  if [ "$cur" != "$PG_LOCALE" ]; then
    dbs="$(pgq -d postgres -c "SELECT count(*) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')")"
    [ "$dbs" = 0 ] || die "لغة العنقود '$cur' لا تطابق '$PG_LOCALE' وفيه قواعد مستخدم — لن أعيد إنشاءه"
    say "إعادة إنشاء العنقود الفارغ بلغة $PG_LOCALE (كانت: $cur)"
    pg_dropcluster --stop "$PG_MAJOR" main
    pg_createcluster "$PG_MAJOR" main --locale="$PG_LOCALE" --encoding=UTF8 --start
  fi

  say "listen_addresses=localhost في ملف جديد"
  cat > "/etc/postgresql/$PG_MAJOR/main/conf.d/90-wamda.conf" <<'EOF'
# ومضة: استماع محلي فقط، وتجزئة كلمات المرور SCRAM.
listen_addresses = 'localhost'
password_encryption = 'scram-sha-256'
EOF
  systemctl enable "postgresql@$PG_MAJOR-main" >/dev/null 2>&1 || true
  systemctl restart "postgresql@$PG_MAJOR-main"
  sleep 3

  say "تحقق"
  chk "العنقود $PG_MAJOR/main online" bash -c "pg_lsclusters --no-header | awk '{print \$1,\$2,\$4}' | grep -qx '$PG_MAJOR main online'"
  chk "الإصدار الرئيسي = $PG_MAJOR" test "$(pg_scalar "SELECT current_setting('server_version_num')::int / 10000")" = "$PG_MAJOR"
  chk "pg_dump من الإصدار $PG_MAJOR" bash -c "pg_dump --version | grep -qE '\) $PG_MAJOR\.'"
  chk "الترميز UTF8" test "$(pg_scalar 'SHOW server_encoding')" = UTF8
  chk "listen_addresses = localhost" test "$(pg_scalar 'SHOW listen_addresses')" = localhost
  chk "المنفذ 5432 على loopback فقط" pg_loopback_only
  chk "pg_hba بلا host مفتوح للجميع" bash -c "! grep -E '^host.*(0\.0\.0\.0/0|::/0)' /etc/postgresql/$PG_MAJOR/main/pg_hba.conf"
  echo "  لغة العنقود: $(pgq -d postgres -c 'SHOW lc_collate') · المنطقة الزمنية: $(pgq -d postgres -c 'SHOW timezone')"
}

# ───────────────────────── ٤) dbrole ─────────────────────────
phase_dbrole() {
  need_wamda
  local role_exists db_exists pw
  role_exists="$(pgq -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname='$DB_ROLE'")"
  if [ -n "$role_exists" ]; then
    [ -s "$DB_PW_FILE" ] || die "الدور $DB_ROLE موجود ولا ملف كلمة مرور في $DB_PW_FILE — لن أعيد ضبطها بلا قرار صريح"
    say "الدور موجود وملف كلمة المرور موجود — لا تغيير"
  else
    say "توليد كلمة مرور (تُحفظ في $DB_PW_FILE، لا تُطبع)"
    pw="$(openssl rand -hex 24)"
    ( umask 077; printf '%s' "$pw" > "$DB_PW_FILE" )
    chown "$WAMDA_USER:$WAMDA_USER" "$DB_PW_FILE"; chmod 600 "$DB_PW_FILE"
    say "إنشاء الدور $DB_ROLE"
    # عبر stdin (لا argv ولا env)؛ hex فقط فلا حاجة لهروب
    printf "CREATE ROLE %s LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '%s';\n" \
      "$DB_ROLE" "$pw" | pgq -d postgres
    unset pw
  fi

  db_exists="$(pgq -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")"
  if [ -z "$db_exists" ]; then
    say "إنشاء القاعدة $DB_NAME"
    pgq -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_ROLE ENCODING 'UTF8'"
  fi
  say "سحب CONNECT من PUBLIC (لا اتصال بقواعد أخرى)"
  pgq -d postgres <<SQL
REVOKE ALL ON DATABASE $DB_NAME FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL

  say "تحقق"
  chk "ملف كلمة المرور 0600 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U' $DB_PW_FILE)\" = '600 $WAMDA_USER' ]"
  chk "الدور بلا أي صلاحية إدارية" test "$(pg_scalar "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls) FROM pg_roles WHERE rolname='$DB_ROLE'")" = t
  chk "الاتصال بـ$DB_NAME عبر TCP بكلمة المرور" app_psql -d "$DB_NAME" -c 'SELECT 1'
  chk "الاتصال بكلمة مرور خاطئة مرفوض" bash -c "! PGPASSWORD=wrong psql -X -At -h 127.0.0.1 -U $DB_ROLE -d $DB_NAME -c 'SELECT 1'"
  chk "يستطيع إنشاء/حذف جدول في $DB_NAME (لـalembic)" app_psql -d "$DB_NAME" -c 'CREATE TABLE _bootstrap_probe(i int); DROP TABLE _bootstrap_probe'
  chk_not "إنشاء دور مرفوض" app_psql -d "$DB_NAME" -c 'CREATE ROLE _zz_probe'
  chk_not "إنشاء قاعدة مرفوض" app_psql -d "$DB_NAME" -c 'CREATE DATABASE _zz_probe'
  chk_not "الاتصال بقاعدة postgres مرفوض" app_psql -d postgres -c 'SELECT 1'
  chk_not "الاتصال بقاعدة template1 مرفوض" app_psql -d template1 -c 'SELECT 1'
  echo "  DATABASE_URL (بلا كلمة المرور): postgresql+psycopg://$DB_ROLE:<من $DB_PW_FILE>@127.0.0.1:5432/$DB_NAME"
}

# ───────────────────────── ٥) sudoers ─────────────────────────
phase_sudoers() {
  need_wamda
  local sc tmp
  sc="$(readlink -f "$(command -v systemctl)")"
  tmp="$(mktemp)"
  cat > "$tmp" <<EOF
# ومضة: wamda يتحكم بخدمته فقط — لا sudo عام.
$WAMDA_USER ALL=(root) NOPASSWD: $sc start wamda, $sc stop wamda, $sc restart wamda, $sc status wamda
EOF
  visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "visudo رفض الملف المقترح"; }
  install -o root -g root -m 0440 "$tmp" "$SUDOERS_FILE"
  rm -f "$tmp"

  say "تحقق"
  chk "visudo -c للنظام كله" visudo -c
  chk "الأوامر المسموحة أربعة بالضبط" bash -c "[ \"\$(sudo -l -U $WAMDA_USER | grep -oE '$sc (start|stop|restart|status) wamda' | sort -u | wc -l)\" = 4 ]"
  chk "لا (ALL) ALL عامة" bash -c "! sudo -l -U $WAMDA_USER | grep -qE 'NOPASSWD: ALL|\\(ALL\\) ALL|\\(ALL : ALL\\) ALL'"
  chk_not "wamda لا يستطيع sudo عام" runuser -u "$WAMDA_USER" -- sudo -n /bin/true
  chk_not "wamda لا يستطيع systemctl لوحدة أخرى" runuser -u "$WAMDA_USER" -- sudo -n "$sc" status ssh
}

# ───────────────────────── ٦) deploykey ─────────────────────────
phase_deploykey() {
  need_wamda
  if [ -e "$DEPLOY_KEY" ]; then
    say "المفتاح موجود — لا أستبدله"
  else
    say "توليد مفتاح ed25519 لـ$WAMDA_USER (بلا passphrase — للقراءة الآلية)"
    as_wamda ssh-keygen -q -t ed25519 -N '' -C "wamda-deploy@$(hostname)" -f "$DEPLOY_KEY"
  fi

  say "تثبيت مفتاح مضيف github.com من بصمته المنشورة"
  local scan fp tmp
  scan="$(ssh-keyscan -t ed25519 github.com 2>/dev/null)"
  [ -n "$scan" ] || die "تعذّر جلب مفتاح github.com"
  tmp="$(mktemp)"; printf '%s\n' "$scan" > "$tmp"
  fp="$(ssh-keygen -lf "$tmp" | awk '{print $2}')"; rm -f "$tmp"
  [ "$fp" = "$GITHUB_ED25519_FP" ] || die "بصمة github.com ($fp) لا تطابق المنشورة ($GITHUB_ED25519_FP) — لن أثق بها"
  printf '%s\n' "$scan" > "$WAMDA_HOME/.ssh/known_hosts"
  cat > "$WAMDA_HOME/.ssh/config" <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile $DEPLOY_KEY
  IdentitiesOnly yes
  StrictHostKeyChecking yes
  UserKnownHostsFile $WAMDA_HOME/.ssh/known_hosts
EOF
  chown "$WAMDA_USER:$WAMDA_USER" "$WAMDA_HOME/.ssh/known_hosts" "$WAMDA_HOME/.ssh/config"
  chmod 600 "$WAMDA_HOME/.ssh/known_hosts" "$WAMDA_HOME/.ssh/config"

  say "تحقق"
  chk "المفتاح الخاص 0600 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U' $DEPLOY_KEY)\" = '600 $WAMDA_USER' ]"
  chk "المفتاح العام موجود وصالح" ssh-keygen -lf "$DEPLOY_KEY.pub"
  echo "  بصمة github.com مطابقة: $fp"

  cat <<EOF

════════ المفتاح العام (انسخ السطر التالي كاملاً) ════════
$(cat "$DEPLOY_KEY.pub")
══════════════════════════════════════════════════════════
بصمة المفتاح: $(ssh-keygen -lf "$DEPLOY_KEY.pub" | awk '{print $2}')

إضافته في GitHub كـ Deploy key للقراءة فقط:
  1) افتح: https://github.com/Ayoubalsaya/WAMDA/settings/keys
  2) Add deploy key
  3) Title: wamda-server (144.91.81.150)
  4) Key: الصق السطر أعلاه
  5) **اترك "Allow write access" غير مُعلَّمة** (قراءة فقط)
  6) Add key
ثم نفّذ مرحلة verify-deploykey للتأكد.
EOF
}

# ───────────────────────── ٧) verify-deploykey ─────────────────────────
phase_verify_deploykey() {
  need_wamda
  [ -e "$DEPLOY_KEY" ] || die "لا مفتاح — نفّذ مرحلة deploykey أولاً"
  local out
  say "المصادقة مع GitHub"
  out="$(as_wamda ssh -o BatchMode=yes -T git@github.com 2>&1 </dev/null || true)"
  grep -qi 'successfully authenticated' <<<"$out" || die "المصادقة فشلت (هل أُضيف المفتاح؟): $out"
  echo "  ✔ $out"

  say "قراءة المستودع"
  chk "git ls-remote يعمل" as_wamda git ls-remote "git@github.com:$REPO_PATH" HEAD

  say "المفتاح للقراءة فقط؟ (طلب receive-pack — لا يكتب شيئاً)"
  out="$(as_wamda ssh -o BatchMode=yes git@github.com "git-receive-pack '$REPO_PATH'" 2>&1 </dev/null || true)"
  if grep -qi 'read.only' <<<"$out"; then
    echo "  ✔ رفض GitHub الكتابة: مفتاح للقراءة فقط"
  else
    die "GitHub لم يرفض receive-pack — المفتاح قد يكون قابلاً للكتابة! احذفه من إعدادات المستودع وأعد إضافته بلا Allow write access"
  fi
}

# ───────────────────────── ٨) report ─────────────────────────
phase_report() {
  say "المستخدم والمجلدات"
  id "$WAMDA_USER" || true
  stat -c '%a %U:%G %n' "$WAMDA_HOME" "$WAMDA_HOME"/* "$WAMDA_HOME"/.ssh 2>&1 || true
  say "sudo لـ$WAMDA_USER"
  sudo -l -U "$WAMDA_USER" 2>&1 | sed -n '/may run/,$p' || true
  say "PostgreSQL"
  pg_lsclusters || true
  ss -tlnp 2>/dev/null | grep -E ':5432\b' || echo "(لا شيء على 5432)"
  pgq -d postgres -c "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname='$DB_ROLE'" || true
  pgq -d postgres -c "SELECT datname FROM pg_database WHERE datname NOT LIKE 'template%'" || true
  say "مفتاح deploy (بصمة فقط)"
  ssh-keygen -lf "$DEPLOY_KEY.pub" 2>&1 || true
  say "الجدار الناري (لم يُمسّ)"
  ufw status | head -10 || true
}

main() {
  exec </dev/null        # stdin هو السكربت نفسه
  trap '' HUP            # يُورَّث لـapt وtee
  [ "$(id -u)" -eq 0 ] || die "يجب التشغيل كـ root"
  local phase="${1:-}"
  [ "$#" -gt 0 ] && shift
  export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
  cd /
  exec > >(tee --output-error=warn-nopipe -a "$LOG") 2>&1
  say "bootstrap_root.sh :: $phase"
  case "$phase" in
    packages)         phase_packages ;;
    user)             phase_user ;;
    postgres)         phase_postgres ;;
    dbrole)           phase_dbrole ;;
    sudoers)          phase_sudoers ;;
    deploykey)        phase_deploykey ;;
    verify-deploykey) phase_verify_deploykey ;;
    report)           phase_report ;;
    *) die "مرحلة غير معروفة: '$phase' (packages|user|postgres|dbrole|sudoers|deploykey|verify-deploykey|report)" ;;
  esac
}

main "$@"   # آخر سطر عمداً: bash يقرأ الدالة كاملة قبل التنفيذ

#!/usr/bin/env bash
# تأسيس ومضة على السيرفر الجديد (DEPLOY_PLAN.md §١–§٢) — يُشغَّل كـ root.
# ⚠ لا يُشغَّل قبل مراجعة مستقلة. كل مرحلة أمر منفصل، تنتهي بتحقق يوقف السكربت عند أول فشل.
#
#   ١) packages        python3-venv · git · مكتبات نظام Chromium/Playwright (best-effort)
#   ٢) user            مستخدم wamda (بلا sudo، كلمة مروره مقفلة، دخول SSH بمفتاح المالك نفسه) و/srv/wamda بصلاحيات 750
#   ٣) postgres        PostgreSQL 18 من مستودع PGDG الرسمي · يستمع على localhost فقط
#   ٤) dbrole          الدوران wamda_app (بلا أي صلاحية إدارية) وwamda_restore (CREATEDB فقط، لـrestore-test وحده)
#                      + القاعدة wamda_db (ICU عربي، منطقة UTC) + كلمتا مرور مولَّدتان لا تُطبعان
#   ٥) sudoers         wamda يتحكم بخدمته فقط: systemctl start|stop|restart wamda و systemctl --no-pager status wamda
#                      + عضوية systemd-journal لقراءة السجلات (لا sudo لـjournalctl)
#   ٦) deploykey       مفتاح deploy لـwamda — يطبع العام فقط + خطوات إضافته في GitHub (قراءة فقط)
#   ٧) verify-deploykey بعد إضافة المفتاح في GitHub: اتصال + ls-remote + التأكد أنه للقراءة فقط
#   ٨) report          عرض الحالة (قراءة فقط)
#   ٩) chromium-plan   (بعد clone + venv) playwright install-deps --dry-run chromium: يعرض الحزم وبصمة القائمة ثم يتوقف
#  ١٠) chromium-install --list-sha256 <بصمة>  تثبيت القائمة المعتمدة + تنزيل Chromium + اختبار PDF/PNG فعلي
#
# لا nginx ولا certbot (النطاق الفرعي لم يُحدَّد). لا مساس بـsshd/ufw/fail2ban.
#
# التشغيل من جهازك (السكربت يصل عبر stdin، لا نسخ ملف للسيرفر):
#   ssh root@HOST 'bash -s -- packages'         < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- user'             < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- postgres'         < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- dbrole'           < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- sudoers'          < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- deploykey'        < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- verify-deploykey' < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- report'           < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- chromium-plan'    < docs/deploy/bootstrap_root.sh
#   ssh root@HOST 'bash -s -- chromium-install --list-sha256 <HASH>' < docs/deploy/bootstrap_root.sh
#
# الضمانات:
#   · كلمتا مرور wamda_app وwamda_restore تُولَّدان على السيرفر (openssl)، وتُحفظان في /srv/wamda/secrets/
#     (db_password · restore_password، 0600 wamda)، ولا تُطبعان ولا تدخلان السجل ولا الـargv ولا سجل PostgreSQL
#     (SET log_min_error_statement = panic في الجلسة نفسها قبل CREATE ROLE). لا تُعاد توليدهما إن وُجد الدور.
#   · المفتاح الخاص للـdeploy لا يُطبع أبداً؛ يُطبع العام فقط. بصمة github.com تُثبَّت من بصمتها المنشورة.
#   · الدور wamda_app لا يستطيع إنشاء أدوار/قواعد ولا الاتصال بـpostgres/template1 (يُختبَر فعلاً).
#   · الدور wamda_restore يستطيع إنشاء قاعدة مؤقتة وحذفها واستعادة نسخة فيها بالأعلام نفسها التي يستخدمها
#     restore-test، ولا يستطيع الاتصال بـwamda_db (يُختبَر فعلاً بما فيه جولة pg_dump ← pg_restore كاملة).
#   · السجل: /var/log/wamda-bootstrap.log (لا أسرار فيه).

set -euo pipefail

WAMDA_USER=wamda
WAMDA_HOME=/srv/wamda
SECRETS_DIR=$WAMDA_HOME/secrets
DB_PW_FILE=$SECRETS_DIR/db_password
PG_MAJOR=18
DB_NAME=wamda_db
DB_ROLE=wamda_app
RESTORE_ROLE=wamda_restore
RESTORE_PW_FILE=$SECRETS_DIR/restore_password
SUDOERS_FILE=/etc/sudoers.d/wamda-systemctl
DEPLOY_KEY=$WAMDA_HOME/.ssh/id_ed25519_deploy
REPO_PATH='Ayoubalsaya/WAMDA.git'
APP_DIR=$WAMDA_HOME/app
VENV=$WAMDA_HOME/venv
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

# اتصال wamda_restore (الدور الوحيد الذي يستخدمه restore-test عبر BACKUP_ADMIN_DATABASE_URL)
restore_psql() { PGPASSWORD="$(cat "$RESTORE_PW_FILE")" psql -X -q -At -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U "$RESTORE_ROLE" "$@"; }

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
  passwd -l "$WAMDA_USER" >/dev/null           # لا دخول بكلمة مرور؛ الدخول بمفتاح المالك فقط (قرار ٢٠٢٦-١٠-١١)
  chown "$WAMDA_USER:$WAMDA_USER" "$WAMDA_HOME"
  chmod 750 "$WAMDA_HOME"
  install -d -o "$WAMDA_USER" -g "$WAMDA_USER" -m 0700 "$WAMDA_HOME/backups" "$SECRETS_DIR" "$WAMDA_HOME/.ssh"

  # مفتاح جهاز المالك نفسه الذي يدخل به root — يُنسخ كما هو (بعد التأكد أنه صالح)
  local rk=/root/.ssh/authorized_keys
  [ -s "$rk" ] && ssh-keygen -lf "$rk" >/dev/null 2>&1 || die "$rk غير موجود أو لا يحوي مفتاحاً صالحاً"
  install -o "$WAMDA_USER" -g "$WAMDA_USER" -m 0600 "$rk" "$WAMDA_HOME/.ssh/authorized_keys"
  say "المفاتيح المنسوخة إلى wamda (بصمات فقط — راجع أنها مفتاحك وحده)"
  ssh-keygen -lf "$WAMDA_HOME/.ssh/authorized_keys"

  say "تحقق"
  chk "uid عادي (≥1000)" bash -c "[ \"\$(id -u $WAMDA_USER)\" -ge 1000 ]"
  chk "ليس في sudo/adm/lxd/docker/root" bash -c "! id -nG $WAMDA_USER | tr ' ' '\n' | grep -qxE 'sudo|adm|lxd|docker|root|admin'"
  chk "كلمة المرور مقفلة" bash -c "passwd -S $WAMDA_USER | awk '{print \$2}' | grep -qx L"
  chk "/srv/wamda بصلاحيات 750 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U:%G' $WAMDA_HOME)\" = '750 $WAMDA_USER:$WAMDA_USER' ]"
  chk "backups وsecrets و.ssh بصلاحيات 700" bash -c "[ \"\$(stat -c %a $WAMDA_HOME/backups $SECRETS_DIR $WAMDA_HOME/.ssh | sort -u)\" = 700 ]"
  chk "authorized_keys بصلاحيات 600 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U' $WAMDA_HOME/.ssh/authorized_keys)\" = '600 $WAMDA_USER' ]"
  chk "بصمات مفاتيح wamda = بصمات root" bash -c "[ \"\$(ssh-keygen -lf $WAMDA_HOME/.ssh/authorized_keys | awk '{print \$2}')\" = \"\$(ssh-keygen -lf /root/.ssh/authorized_keys | awk '{print \$2}')\" ]"
  chk "sshd يسمح لـwamda بالمفتاح (لا AllowUsers/AllowGroups تستثنيه)" bash -c "sshd -T -C user=$WAMDA_USER,host=localhost,addr=127.0.0.1 | grep -qi '^pubkeyauthentication yes' && ! sshd -T -C user=$WAMDA_USER,host=localhost,addr=127.0.0.1 | grep -qiE '^(allowusers|allowgroups) '"
  chk "لا sudo لـwamda بعد (قبل مرحلة sudoers)" bash -c "sudo -l -U $WAMDA_USER 2>&1 | grep -qiE 'not allowed|may not run'"
}

# ───────────────────────── ٣) postgres ─────────────────────────
phase_postgres() {
  say "مستودع PGDG الرسمي (سكربت postgresql-common)"
  apt_get install postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  # (يُحفظ الناتج أولاً: مع pipefail يُنهي grep -q الأنبوب مبكراً فيموت المنتِج بـSIGPIPE ويبدو الأنبوب فاشلاً)
  local pol; pol="$(apt-cache policy "postgresql-$PG_MAJOR")"
  grep -q 'apt.postgresql.org' <<<"$pol" || die "postgresql-$PG_MAJOR غير متاحة من apt.postgresql.org"

  say "تثبيت postgresql-$PG_MAJOR"
  apt_get install "postgresql-$PG_MAJOR"

  # الخادم الافتراضي في Ubuntu (16) لا يجوز أن يُثبَّت عرَضاً
  local majors; majors="$(pg_lsclusters --no-header | awk '{print $1}')"
  if [ -n "$majors" ] && grep -qvx "$PG_MAJOR" <<<"$majors"; then
    die "وُجد عنقود بإصدار آخر غير $PG_MAJOR — توقفت: $(pg_lsclusters --no-header | awk '{print $1"/"$2}' | paste -sd' ')"
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
  echo "  ترتيب قالب template1 (datcollate | provider | datlocale): $(pgq -d postgres -c "SELECT datcollate, datlocprovider, datlocale FROM pg_database WHERE datname='template1'")"
  echo "  المنطقة الزمنية للعنقود (لا تهم: wamda_db مضبوطة على UTC): $(pgq -d postgres -c 'SHOW timezone')"
}

# ───────────────────────── ٤) dbrole ─────────────────────────
# make_role <role> <pw-file> <attrs>  — يولّد كلمة مرور (hex) ويُنشئ الدور؛ لا يمسّ دوراً موجوداً.
make_role() {
  local role="$1" pwfile="$2" attrs="$3" exists pw
  exists="$(pgq -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname='$role'")"
  if [ -n "$exists" ]; then
    [ -s "$pwfile" ] || die "الدور $role موجود ولا ملف كلمة مرور في $pwfile — لن أعيد ضبطها بلا قرار صريح"
    say "الدور $role موجود وملف كلمة المرور موجود — لا تغيير"
    return 0
  fi
  say "توليد كلمة مرور لـ$role (تُحفظ في $pwfile، لا تُطبع)"
  pw="$(openssl rand -hex 24)"
  ( umask 077; printf '%s' "$pw" > "$pwfile" )
  chown "$WAMDA_USER:$WAMDA_USER" "$pwfile"; chmod 600 "$pwfile"
  say "إنشاء الدور $role"
  # عبر stdin (لا argv ولا env)؛ hex فقط فلا حاجة لهروب.
  # SET في الجلسة نفسها قبل CREATE ROLE: لو فشلت الجملة لا يُكتب نصها (وفيه كلمة المرور) في سجل PostgreSQL.
  {
    printf 'SET log_min_error_statement = panic;\n'
    printf "CREATE ROLE %s LOGIN %s PASSWORD '%s';\n" "$role" "$attrs" "$pw"
  } | pgq -d postgres
  unset pw
}

# جولة مصغَّرة تطابق restore-test: pg_dump بـwamda_app ← قاعدة مؤقتة بـwamda_restore ← pg_restore بالأعلام نفسها
# (--clean --if-exists --no-owner، ويُعدّ ظهور ERROR في stderr فشلاً كما في app/cli/pg_tools.py) ← حذفها.
restore_roundtrip_probe() {
  local dump tmpdb out rc=0
  dump="$(mktemp)"
  tmpdb="wamda_restore_test_bootstrap_probe"       # بادئة مكنوسة تلقائياً من restore-test إن بقيت
  PGPASSWORD="$(cat "$DB_PW_FILE")" pg_dump -Fc --no-password -h 127.0.0.1 -p 5432 -U "$DB_ROLE" -f "$dump" "$DB_NAME" || rc=$?
  if [ "$rc" -eq 0 ]; then restore_psql -d postgres -c "DROP DATABASE IF EXISTS \"$tmpdb\" WITH (FORCE)" || rc=$?; fi
  if [ "$rc" -eq 0 ]; then restore_psql -d postgres -c "CREATE DATABASE \"$tmpdb\"" || rc=$?; fi
  if [ "$rc" -eq 0 ]; then
    out="$(PGPASSWORD="$(cat "$RESTORE_PW_FILE")" pg_restore --no-password --clean --if-exists --no-owner \
            -h 127.0.0.1 -p 5432 -U "$RESTORE_ROLE" -d "$tmpdb" "$dump" 2>&1)" || true
    if grep -q 'ERROR' <<<"$out"; then echo "$out" | head -20 >&2; rc=1; fi
  fi
  restore_psql -d postgres -c "DROP DATABASE IF EXISTS \"$tmpdb\" WITH (FORCE)" >/dev/null 2>&1 || true
  rm -f "$dump"
  return "$rc"
}

# ينشئ قاعدة مؤقتة بـwamda_restore ثم يحذفها
restore_create_drop_probe() {
  restore_psql -d postgres -c 'CREATE DATABASE _zz_restore_probe' \
    && restore_psql -d postgres -c 'DROP DATABASE _zz_restore_probe WITH (FORCE)'
}

phase_dbrole() {
  need_wamda
  local db_exists
  make_role "$DB_ROLE"      "$DB_PW_FILE"      "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
  make_role "$RESTORE_ROLE" "$RESTORE_PW_FILE" "NOSUPERUSER CREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"

  db_exists="$(pgq -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")"
  if [ -z "$db_exists" ]; then
    say "إنشاء القاعدة $DB_NAME (ICU عربي)"
    pgq -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_ROLE ENCODING 'UTF8' TEMPLATE template0 LOCALE_PROVIDER icu ICU_LOCALE 'ar' LOCALE 'C.UTF-8'"
  fi
  say "المنطقة الزمنية UTC على مستوى القاعدة (تاريخ العمل من work_timezone في التطبيق وحده)"
  pgq -d postgres -c "ALTER DATABASE $DB_NAME SET timezone TO 'UTC'"

  say "الصلاحيات: لا اتصال عام بالقواعد"
  pgq -d postgres <<SQL
REVOKE ALL ON DATABASE $DB_NAME FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO $RESTORE_ROLE;
SQL
  # (GRANT على postgres لـwamda_restore: restore-test يتصل بقاعدة postgres ليُنشئ القاعدة المؤقتة ويسردها ويحذفها)

  say "تحقق — wamda_app"
  chk "ملف كلمة المرور 0600 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U' $DB_PW_FILE)\" = '600 $WAMDA_USER' ]"
  chk "الدور بلا أي صلاحية إدارية" test "$(pg_scalar "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls) FROM pg_roles WHERE rolname='$DB_ROLE'")" = t
  chk "الاتصال بـ$DB_NAME عبر TCP بكلمة المرور" app_psql -d "$DB_NAME" -c 'SELECT 1'
  chk "الاتصال بكلمة مرور خاطئة مرفوض" bash -c "! PGPASSWORD=wrong psql -X -At -h 127.0.0.1 -U $DB_ROLE -d $DB_NAME -c 'SELECT 1'"
  chk "يستطيع إنشاء/حذف جدول في $DB_NAME (لـalembic)" app_psql -d "$DB_NAME" -c 'CREATE TABLE _bootstrap_probe(i int); DROP TABLE _bootstrap_probe'
  chk_not "إنشاء دور مرفوض" app_psql -d "$DB_NAME" -c 'CREATE ROLE _zz_probe'
  chk_not "إنشاء قاعدة مرفوض" app_psql -d "$DB_NAME" -c 'CREATE DATABASE _zz_probe'
  chk_not "الاتصال بقاعدة postgres مرفوض" app_psql -d postgres -c 'SELECT 1'
  chk_not "الاتصال بقاعدة template1 مرفوض" app_psql -d template1 -c 'SELECT 1'

  say "تحقق — ترتيب عربي (ICU) ومنطقة زمنية"
  chk "مزوّد الترتيب icu واللغة ar" test "$(pg_scalar "SELECT datlocprovider::text || ':' || datlocale FROM pg_database WHERE datname='$DB_NAME'")" = "i:ar"
  chk "ORDER BY: إبراهيم، أحمد، احمد، باسم، ثامر (ترتيب أبجدي عربي)" \
      test "$(app_psql -d "$DB_NAME" -c "SELECT string_agg(n, ' ' ORDER BY n) FROM (VALUES ('إبراهيم'),('أحمد'),('احمد'),('باسم'),('ثامر')) v(n)")" = "إبراهيم أحمد احمد باسم ثامر"
  echo "  datcollate | provider | datlocale: $(pg_scalar "SELECT datcollate, datlocprovider, datlocale FROM pg_database WHERE datname='$DB_NAME'")"
  chk "منطقة الجلسة UTC" test "$(app_psql -d "$DB_NAME" -c 'SHOW timezone')" = UTC

  say "تحقق — wamda_restore (restore-test)"
  chk "ملف كلمة المرور 0600 ومالكه wamda" bash -c "[ \"\$(stat -c '%a %U' $RESTORE_PW_FILE)\" = '600 $WAMDA_USER' ]"
  chk "CREATEDB فقط، بلا أي صلاحية أخرى" test "$(pg_scalar "SELECT rolcreatedb AND NOT (rolsuper OR rolcreaterole OR rolreplication OR rolbypassrls) FROM pg_roles WHERE rolname='$RESTORE_ROLE'")" = t
  chk "يتصل بـpostgres (كما يفعل restore-test)" restore_psql -d postgres -c 'SELECT 1'
  chk "ينشئ قاعدة ويحذفها" restore_create_drop_probe
  chk_not "لا يتصل بـ$DB_NAME" restore_psql -d "$DB_NAME" -c 'SELECT 1'
  chk_not "لا ينشئ أدواراً" restore_psql -d postgres -c 'CREATE ROLE _zz_probe2'
  chk "جولة pg_dump ← pg_restore (أعلام restore-test) تنجح بلا ERROR" restore_roundtrip_probe
  chk "لا قواعد wamda_restore_test_* متبقية" test -z "$(pg_scalar "SELECT datname FROM pg_database WHERE datname LIKE 'wamda\_restore\_test\_%'")"

  cat <<EOF

  لملف .env (القيم السرّية تُقرأ من الملفات، لا تُنسخ هنا):
    DATABASE_URL=postgresql+psycopg://$DB_ROLE:<من $DB_PW_FILE>@127.0.0.1:5432/$DB_NAME
    BACKUP_ADMIN_DATABASE_URL=postgresql+psycopg://$RESTORE_ROLE:<من $RESTORE_PW_FILE>@127.0.0.1:5432/postgres
  تنبيه: restore --target-db (استعادة حقيقية يدوية إلى $DB_NAME) يستخدم BACKUP_ADMIN_DATABASE_URL أيضاً
  ولا يستطيع $RESTORE_ROLE الاتصال بـ$DB_NAME — تُنفَّذ بعد تفريغ هذا المتغيّر من بيئة الأمر.
EOF
}

# ───────────────────────── ٥) sudoers ─────────────────────────
phase_sudoers() {
  need_wamda
  local sc tmp
  sc="$(readlink -f "$(command -v systemctl)")"
  tmp="$(mktemp)"
  cat > "$tmp" <<EOF
# ومضة: wamda يتحكم بخدمته فقط — لا sudo عام.
# status بـ--no-pager حصراً: بدونه يفتح systemctl عارض صفحات (less) ومنه سطر أوامر root (GTFOBins).
# قراءة السجلات عبر عضوية systemd-journal لا sudo.
$WAMDA_USER ALL=(root) NOPASSWD: $sc start wamda, $sc stop wamda, $sc restart wamda, $sc --no-pager status wamda
EOF
  visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "visudo رفض الملف المقترح"; }
  install -o root -g root -m 0440 "$tmp" "$SUDOERS_FILE"
  rm -f "$tmp"
  usermod -aG systemd-journal "$WAMDA_USER"

  say "تحقق"
  chk "visudo -c للنظام كله" visudo -c
  chk "الأوامر المسموحة أربعة بالضبط" bash -c "[ \"\$(sudo -l -U $WAMDA_USER | grep -oE '$sc (start|stop|restart|--no-pager status) wamda' | sort -u | wc -l)\" = 4 ]"
  chk "لا (ALL) ALL عامة" bash -c "! sudo -l -U $WAMDA_USER | grep -qE 'NOPASSWD: ALL|\\(ALL\\) ALL|\\(ALL : ALL\\) ALL'"
  chk "المسموح: systemctl --no-pager status wamda" runuser -u "$WAMDA_USER" -- sudo -n -l "$sc" --no-pager status wamda
  chk "المسموح: systemctl restart wamda" runuser -u "$WAMDA_USER" -- sudo -n -l "$sc" restart wamda
  chk_not "الصيغة بلا --no-pager مرفوضة (عارض الصفحات)" runuser -u "$WAMDA_USER" -- sudo -n -l "$sc" status wamda
  chk_not "status لوحدة أخرى مرفوض" runuser -u "$WAMDA_USER" -- sudo -n -l "$sc" --no-pager status ssh
  chk_not "wamda لا يستطيع sudo عام" runuser -u "$WAMDA_USER" -- sudo -n /bin/true
  chk_not "wamda لا يستطيع sudo journalctl" runuser -u "$WAMDA_USER" -- sudo -n -l /usr/bin/journalctl
  chk "wamda عضو systemd-journal" bash -c "id -nG $WAMDA_USER | tr ' ' '\n' | grep -qx systemd-journal"
  chk "wamda يقرأ السجلات بلا sudo" runuser -u "$WAMDA_USER" -- journalctl -n 1 --no-pager
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
  pgq -d postgres -c "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname IN ('$DB_ROLE','$RESTORE_ROLE') ORDER BY 1" || true
  pgq -d postgres -c "SELECT datname, datcollate, datlocprovider, datlocale FROM pg_database WHERE datname IN ('template1','$DB_NAME') ORDER BY 1" || true
  pgq -d "$DB_NAME" -c "SHOW timezone" || true
  say "مفتاح deploy (بصمة فقط)"
  ssh-keygen -lf "$DEPLOY_KEY.pub" 2>&1 || true
  say "الجدار الناري (لم يُمسّ)"
  ufw status | head -10 || true
}

# ───────────────────────── ٩) chromium-plan ─────────────────────────
# `playwright install-deps --dry-run chromium` بصفة wamda: لا يغيّر شيئاً. على لينكس يحاكي apt-get ويخرج بـ1 إن نقصت حزم
# (ويطبع «Missing system dependencies (N):» ثم الأسماء، سطراً لكل حزمة)، وبـ0 إن لم ينقص شيء — فالرمز ≠0 ليس خطأً هنا.
# تتطلب venv فيه playwright (بعد clone + pip install). تطبع القائمة وبصمتها ثم تتوقف.
pw_dry_run() {
  PW_DRY_RC=0
  PW_DRY_OUT="$(as_wamda "$VENV/bin/playwright" install-deps --dry-run chromium 2>&1)" || PW_DRY_RC=$?
}

# يطبع أسماء الحزم الناقصة (واحدة بكل سطر، مرتَّبة؛ فارغ = لا نقص). يفشل إن كان الناتج غير مفهوم.
chromium_pkg_list() {
  pw_dry_run
  [ "$PW_DRY_RC" -ne 0 ] || return 0
  grep -q '^Missing system dependencies' <<<"$PW_DRY_OUT" || { printf '%s\n' "$PW_DRY_OUT" >&2; return 1; }
  awk '/^Missing system dependencies/ {on=1; next}
       on && /^[[:space:]]+[a-z0-9][a-z0-9+.:-]*[[:space:]]*$/ {gsub(/[[:space:]]/, ""); print}' <<<"$PW_DRY_OUT" | sort -u
}

phase_chromium_plan() {
  [ -x "$VENV/bin/playwright" ] || die "لا $VENV/bin/playwright — نفّذ clone + venv + pip install أولاً"
  say "playwright install-deps --dry-run chromium (الناتج الخام)"
  pw_dry_run
  printf '%s\n' "$PW_DRY_OUT"
  echo "(رمز الخروج: $PW_DRY_RC — 1 = حزم ناقصة، 0 = لا نقص)"
  local pkgs n new p declared
  pkgs="$(chromium_pkg_list)" || die "ناتج dry-run غير مفهوم (انظر أعلاه)"
  say "الحزم التي سيثبّتها التثبيت الفعلي"
  n=0; new=0
  if [ -n "$pkgs" ]; then
    while IFS= read -r p; do
      n=$((n + 1))
      if dpkg -s "$p" >/dev/null 2>&1; then printf '  = %s (مثبّتة)\n' "$p"; else printf '  + %s (جديدة)\n' "$p"; new=$((new + 1)); fi
    done <<<"$pkgs"
  else
    echo "  (لا حزم ناقصة)"
  fi
  declared="$(sed -n 's/^Missing system dependencies (\([0-9]*\)).*/\1/p' <<<"$PW_DRY_OUT")"
  [ -z "$declared" ] || [ "$declared" = "$n" ] || die "عدد الحزم المستخرَج ($n) لا يطابق المعلَن ($declared) — المحلّل لا يُوثَق به"
  echo
  echo "  المجموع: $n حزمة، الجديدة منها: $new"
  echo "  بصمة القائمة (sha256): $(printf '%s' "$pkgs" | sha256sum | awk '{print $1}')"
  cat <<EOF

توقّف هنا. إن وافقت على القائمة نفّذ (البصمة أعلاه تضمن تثبيت هذه القائمة بعينها لا غيرها):
  ssh root@HOST 'bash -s -- chromium-install --list-sha256 <البصمة>' < docs/deploy/bootstrap_root.sh
EOF
}

# ───────────────────────── ١٠) chromium-install ─────────────────────────
# يثبّت حزم القائمة المعتمدة (root، apt-get install --no-install-recommends — مطابق لما يفعله install-deps) ثم
# يُنزِّل Chromium بصفة wamda ثم يشغّل اختبار توليد PDF وPNG فعلياً عبر app.documents.render (المسار الإنتاجي نفسه).
phase_chromium_install() {
  [ "${1:-}" = "--list-sha256" ] && [ -n "${2:-}" ] || die "يتطلب: chromium-install --list-sha256 <بصمة من chromium-plan>"
  [ -x "$VENV/bin/playwright" ] || die "لا $VENV/bin/playwright"
  [ -d "$APP_DIR/app" ] || die "لا $APP_DIR/app — اختبار التوليد يحتاج الكود"
  local pkgs hash
  pkgs="$(chromium_pkg_list)" || die "ناتج dry-run غير مفهوم"
  hash="$(printf '%s' "$pkgs" | sha256sum | awk '{print $1}')"
  [ "$hash" = "$2" ] || die "القائمة تغيّرت منذ الموافقة (الحالية $hash ≠ المعتمدة $2) — أعد chromium-plan"

  if [ -n "$pkgs" ]; then
    say "تثبيت $(printf '%s\n' "$pkgs" | grep -c .) حزمة (apt)"
    # shellcheck disable=SC2086
    apt_get install --no-install-recommends $pkgs
    say "تحقق: لا حزم ناقصة بعد التثبيت"
    pw_dry_run
    [ "$PW_DRY_RC" -eq 0 ] || { printf '%s\n' "$PW_DRY_OUT" >&2; die "ما زالت حزم ناقصة بعد التثبيت"; }
  else
    say "لا حزم نظام ناقصة — يُتخطّى apt"
  fi

  say "تنزيل Chromium (بصفة $WAMDA_USER → $WAMDA_HOME/.cache/ms-playwright)"
  as_wamda "$VENV/bin/playwright" install chromium

  say "اختبار توليد PDF وPNG عبر app.documents.render"
  local code
  code='
import sys
from app.documents import render
html = ("<html dir=\"rtl\"><head><meta charset=\"utf-8\"><style>@page{size:A4}body{font-family:sans-serif}</style></head>"
        "<body><h1>ومضة — اختبار توليد المستند</h1><p>١٢٣٤٥ — 12345</p></body></html>")
render.start()
try:
    pdf = render.render_pdf(html)
    png = render.render_png(html, width=400)
finally:
    render.stop()
assert pdf[:5] == b"%PDF-" and len(pdf) > 1500, ("pdf", len(pdf))
assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1500, ("png", len(png))
print("RENDER_OK pdf=%d png=%d" % (len(pdf), len(png)))
'
  local out
  out="$(runuser -u "$WAMDA_USER" -- env HOME="$WAMDA_HOME" DATABASE_URL=postgresql+psycopg://x:x@127.0.0.1:5432/x \
      bash -c 'cd "$1" && exec "$2" -c "$3"' _ "$APP_DIR" "$VENV/bin/python" "$code" 2>&1)" \
    || { printf '%s\n' "$out" | tail -25 >&2; die "فشل اختبار التوليد (الناتج أعلاه)"; }
  echo "  ✔ $(printf '%s\n' "$out" | tail -1)"
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
    chromium-plan)    phase_chromium_plan ;;
    chromium-install) phase_chromium_install "$@" ;;
    *) die "مرحلة غير معروفة: '$phase' (packages|user|postgres|dbrole|sudoers|deploykey|verify-deploykey|report|chromium-plan|chromium-install)" ;;
  esac
}

main "$@"   # آخر سطر عمداً: bash يقرأ الدالة كاملة قبل التنفيذ

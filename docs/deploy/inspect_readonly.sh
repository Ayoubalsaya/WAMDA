#!/usr/bin/env bash
# فحص قراءة فقط للسيرفر — لا يكتب ولا يعدّل شيئاً.
#
# الضمانات:
#   · لا ملفات تُنشأ على السيرفر: كل المخرجات إلى stdout فقط (لا tee، لا mktemp، لا redirect إلى ملف).
#   · لا sudo داخل السكربت. ما يحتاج root يُتخطّى برسالة «غير متاح»؛ شغّله بـ sudo بنفسك إن أردت المزيد.
#   · لا systemctl start/stop/reload، لا nginx -t/-s، لا psql بأوامر غير SELECT/\l.
#   · لا طباعة لمحتوى .env ولا كلمات مرور ولا ملفات nginx كاملة (فقط server_name/listen).
#
# التشغيل من جهازك (بلا نسخ أي ملف للسيرفر):
#   ssh <المستخدم>@<السيرفر> 'bash -s' < docs/deploy/inspect_readonly.sh > inspect_YYYYMMDD.txt
# (الملف الناتج يُكتب على جهازك أنت لا على السيرفر)
#
# تنبيه: سطور cron قد تحوي أسماء ملفات/أوامر؛ الأسرار تُخفى بـ*** (دالة redact) لكن راجع الناتج قبل مشاركته.

set -uo pipefail   # بلا -e عمداً: فشل أمر فحص لا يوقف بقية الفحص
export LC_ALL=C

sec() { printf '\n===== %s =====\n' "$1"; }
try() { "$@" 2>&1 || echo "(غير متاح أو يحتاج صلاحية: $1)"; }
have() { command -v "$1" >/dev/null 2>&1; }

# إخفاء الأسرار من أي نص يُطبع (محتوى cron وproxy_pass): قيمة بعد password/passwd/pwd/
# PGPASSWORD/token/secret/key (بـ= أو : أو كوسيط بعد --flag)، وكلمة المرور في scheme://user:pass@host.
redact() {
  sed -E \
    -e 's#([A-Za-z][A-Za-z0-9+.-]*://[^:/@[:space:]]*):[^[:space:]/]+@#\1:***@#g' \
    -e 's#((password|passwd|pwd|token|secret|key)[A-Za-z0-9_]*[[:space:]]*(=|:)[[:space:]]*)("[^"]*"|\x27[^\x27]*\x27|[^[:space:];&|"]+)#\1***#Ig' \
    -e 's#(--?(password|passwd|pwd|token|secret|key)[[:space:]]+)[^[:space:]-][^[:space:]]*#\1***#Ig'
}

sec "الهوية الحالية (من أنا؟)"
try id
try hostname

sec "التوزيعة والنواة"
if [ -r /etc/os-release ]; then grep -E '^(PRETTY_NAME|VERSION_ID|ID)=' /etc/os-release; fi
try uname -srm

sec "المعالج"
if have nproc; then echo "nproc: $(nproc)"; fi
if have lscpu; then lscpu | grep -E '^(Model name|CPU\(s\)|Thread|Core)' ; fi

sec "الذاكرة"
try free -h

sec "القرص"
try df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay

sec "المنطقة الزمنية والوقت"
if have timedatectl; then timedatectl 2>&1 | grep -E 'Local time|Time zone|NTP|synchronized'; else try date; fi

sec "إصدارات البرامج"
for b in python3 python3.12 python3.11 pip3 node npm git curl; do
  if have "$b"; then printf '%s: ' "$b"; "$b" --version 2>&1 | head -1; else echo "$b: غير مثبّت"; fi
done
if have psql; then printf 'psql: '; psql --version; else echo "psql: غير مثبّت"; fi
if have pg_dump; then printf 'pg_dump: '; pg_dump --version; else echo "pg_dump: غير مثبّت"; fi
if have postgres; then printf 'postgres: '; postgres --version; fi
if have nginx; then printf 'nginx: '; nginx -v 2>&1; else echo "nginx: غير مثبّت أو خارج PATH"; fi
if have certbot; then printf 'certbot: '; certbot --version 2>&1; else echo "certbot: غير مثبّت"; fi
if have chromium || have chromium-browser || have google-chrome; then echo "chromium/chrome: موجود"; else echo "chromium/chrome: غير مثبّت"; fi
ls -d /usr/lib/postgresql/*/ 2>/dev/null | sed 's/^/إصدارات PostgreSQL المثبّتة: /'

sec "PostgreSQL — قوائم قواعد البيانات والأدوار (اتصال محلي بالمستخدم الحالي فقط)"
if have psql; then
  # \l و\du أوامر قراءة فقط. إن لم يكن للمستخدم الحالي دور PostgreSQL ستفشل وهذا متوقَّع.
  psql -X -w -d postgres -At -c '\l' 2>&1 | head -40 || true
  echo "--- الأدوار"
  psql -X -w -d postgres -At -c '\du' 2>&1 | head -40 || true
else
  echo "psql غير متاح"
fi
if have pg_lsclusters; then echo "--- العناقيد"; pg_lsclusters 2>&1; fi

sec "المنافذ المستمعة (ss -tlnp) — أسماء العمليات تظهر فقط لو شُغِّل كـ root"
if have ss; then ss -tlnp 2>&1; else try netstat -tlnp; fi

sec "الخدمات العاملة (systemd)"
if have systemctl; then
  systemctl list-units --type=service --state=running --no-pager --no-legend 2>&1
  echo "--- الخدمات الفاشلة"
  systemctl list-units --type=service --state=failed --no-pager --no-legend 2>&1
else
  echo "systemctl غير متاح"
fi

sec "مؤقّتات systemd"
if have systemctl; then systemctl list-timers --all --no-pager 2>&1; fi

sec "cron"
echo "--- crontab المستخدم الحالي"
crontab -l 2>&1 | redact
echo "--- /etc/crontab"
if [ -r /etc/crontab ]; then grep -vE '^\s*#|^\s*$' /etc/crontab | redact; else echo "(غير مقروء)"; fi
echo "--- /etc/cron.d"
for f in /etc/cron.d/*; do
  [ -r "$f" ] || continue
  echo "# $f"; grep -vE '^\s*#|^\s*$' "$f" | redact
done 2>/dev/null
echo "--- ملفات cron.daily/hourly/weekly (الأسماء فقط)"
ls /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /etc/cron.monthly 2>&1

sec "nginx — server_name / listen / root فقط (لا محتوى آخر)"
if [ -d /etc/nginx ]; then
  ls -la /etc/nginx/sites-enabled /etc/nginx/conf.d 2>&1
  echo "---"
  grep -RHnE '^\s*(server_name|listen|root|proxy_pass)\b' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>&1 | redact | head -80
else
  echo "/etc/nginx غير موجود"
fi

sec "جدار ناري (قراءة فقط، يحتاج root غالباً)"
if have ufw; then ufw status 2>&1 | head -30; else echo "ufw غير مثبّت"; fi

sec "المستخدمون المحليون (أسماء فقط، بلا shell تسجيل دخول مستبعَد)"
getent passwd 2>/dev/null | awk -F: '$3>=1000 && $3<65000 {print $1" uid="$3" home="$6" shell="$7}'
echo "--- وجود wamda؟"
getent passwd wamda >/dev/null 2>&1 && echo "wamda موجود" || echo "wamda غير موجود"
ls -ld /srv /srv/* 2>&1 | head -20

sec "انتهى — لم يُكتب أي شيء على السيرفر"

#!/usr/bin/env bash
# «لقطة صحة» لنظام السهم — قراءة فقط. تُشغَّل قبل أي مرحلة وبعدها ثم تُقارَن (diff).
#
#   ssh <المستخدم>@<السيرفر> 'SAHEM_URL=https://... SAHEM_SERVICE=<اسم الخدمة> bash -s' \
#       < docs/deploy/sahem_health_snapshot.sh > snapshots/sahem_before.txt
#   (يُكتب الناتج على جهازك لا على السيرفر)
#
# المتغيّرات (يحدّدها المالك — لا تخمين):
#   SAHEM_URL      عنوان موقع السهم العام (يجب أن يرد 200)
#   SAHEM_SERVICE  اسم وحدة systemd لخدمة السهم (يجب أن تكون active)
#   SAHEM_DIRS     (اختياري) مجلدات يُسجَّل مالكها وصلاحياتها فقط، مفصولة بمسافة
#
# لا يكتب شيئاً ولا يعدّل شيئاً. يقارن التغيّر عبر بصمات (sha256) لإعدادات nginx
# وقائمة الخدمات والمنافذ — لا يطبع محتوى أي ملف إعداد.

set -uo pipefail
export LC_ALL=C

: "${SAHEM_URL:?حدّد SAHEM_URL}"
: "${SAHEM_SERVICE:?حدّد SAHEM_SERVICE}"

echo "== موقع السهم =="
if command -v curl >/dev/null 2>&1; then
  curl -sS -o /dev/null -L --max-time 20 -w 'http_code=%{http_code}\n' "$SAHEM_URL" 2>&1 || echo "http_code=FAILED"
else
  echo "curl غير متاح"
fi

echo "== خدمة السهم =="
printf '%s: ' "$SAHEM_SERVICE"; systemctl is-active "$SAHEM_SERVICE" 2>&1 || true
printf 'enabled: '; systemctl is-enabled "$SAHEM_SERVICE" 2>&1 || true
systemctl show "$SAHEM_SERVICE" -p MainPID -p ActiveEnterTimestamp -p NRestarts 2>&1 || true

echo "== بصمات إعدادات nginx (ليست محتوى) =="
if [ -d /etc/nginx ]; then
  find /etc/nginx -type f -readable 2>/dev/null | sort | xargs -r sha256sum 2>/dev/null | awk '{print $1"  "$2}'
else
  echo "/etc/nginx غير موجود"
fi

echo "== بصمة قائمة الخدمات العاملة والمؤقّتات =="
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | sort
echo "-- timers"
systemctl list-timers --all --no-pager --no-legend 2>/dev/null | awk '{print $(NF-1)}' | sort

echo "== المنافذ المستمعة =="
ss -tln 2>/dev/null | awk 'NR>1{print $4}' | sort

echo "== بصمة cron =="
{ crontab -l 2>/dev/null; cat /etc/crontab 2>/dev/null; cat /etc/cron.d/* 2>/dev/null; } | sha256sum | awk '{print $1}'

if [ -n "${SAHEM_DIRS:-}" ]; then
  echo "== مالك/صلاحيات مجلدات السهم (بلا محتوى) =="
  for d in $SAHEM_DIRS; do stat -c '%A %U:%G %n' "$d" 2>&1; done
fi

echo "== نهاية اللقطة =="

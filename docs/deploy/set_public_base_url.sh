#!/usr/bin/env bash
# يضبط PUBLIC_BASE_URL في .env الإنتاج ويتحقق أن الإيصالات برمز QR ودعوات البوابة صارت مسموحة — بصفة wamda (لا root).
#   ssh wamda@144.91.81.150 'bash -s -- https://app.wamda.work' < docs/deploy/set_public_base_url.sh
#
# الضمانات: لا يطبع من .env إلا السطر المتغيّر؛ يحتفظ بنسخة سابقة في /srv/wamda/secrets/ (0600)؛ يرفض أي قيمة ليست
# https://نطاق بلا مسار؛ لا يعيد تشغيل الخدمة إن فشل التحقق من القيمة الجديدة (يعيد الملف كما كان).
set -euo pipefail
set +x

URL="${1:-}"
APP=/srv/wamda/app
VENV=/srv/wamda/venv
ENVF=$APP/.env
BAK=/srv/wamda/secrets/env.bak-publicurl

die() { printf '\nخطأ: %s\n' "$*" >&2; exit 1; }
[[ "$URL" =~ ^https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || die "الوسيط يجب أن يكون https://نطاق (بلا مسار ولا منفذ ولا IP): '$URL'"
[[ "$URL" =~ ^https://[0-9.]+$ ]] && die "IP غير مسموح"
[ -f "$ENVF" ] || die "لا .env"

cp -p "$ENVF" "$BAK"; chmod 600 "$BAK"
if grep -qE '^PUBLIC_BASE_URL=' "$ENVF"; then
  sed -i -E "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=$URL|" "$ENVF"
else
  printf 'PUBLIC_BASE_URL=%s\n' "$URL" >> "$ENVF"
fi
grep -E '^PUBLIC_BASE_URL=' "$ENVF"

cd "$APP"
# الحارس نفسه الذي يستخدمه التطبيق + توليد QR فعلي بالعنوان الجديد (المسار الإنتاجي نفسه)
if ! "$VENV/bin/python" - "$URL" <<'PY'
import sys
from app import public_url
from app.documents.qr import qr_data_uri
want = sys.argv[1]
got = public_url.base_url()          # يرفع PublicBaseUrlNotConfiguredError إن لم يصلح للإنتاج
assert got == want, (got, want)
uri = qr_data_uri(f"{got}/r/test-check")
assert uri.startswith("data:image/png;base64,") and len(uri) > 200
print("PUBLIC_URL_OK", got, "qr_bytes=%d" % len(uri))
PY
then
  cp -p "$BAK" "$ENVF"
  die "فشل التحقق — أُعيد .env كما كان"
fi

sudo systemctl restart wamda </dev/null
for _ in $(seq 1 20); do curl -fsS --max-time 2 http://127.0.0.1:8000/health </dev/null >/dev/null 2>&1 && break; sleep 1; done
curl -fsS --max-time 5 http://127.0.0.1:8000/health; echo
echo
echo "تم. تحقّق يدوياً من الواجهة عبر $URL: أنشئ إيصالاً واطبعه/نزّله (PDF) وامسح رمز QR — يجب أن يفتح $URL/..."
echo "وجرّب «دعوة بوابة» لعميل: يجب أن يكون الرابط $URL/portal/... (قبل هذا كانا يُرفضان بـ503)."

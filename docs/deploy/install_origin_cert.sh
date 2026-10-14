#!/usr/bin/env bash
# يثبّت شهادة Cloudflare Origin (الشهادة ثم المفتاح الخاص) على السيرفر — تفاعلي، يُشغَّله المالك بنفسه كـ root.
#
#   scp docs/deploy/install_origin_cert.sh root@144.91.81.150:/root/
#   ssh -t root@144.91.81.150 'bash /root/install_origin_cert.sh'
#   ssh root@144.91.81.150 'shred -u /root/install_origin_cert.sh'     # اختياري: لا أسرار فيه
#
# (الإضافة `--replace` لاستبدال شهادة موجودة؛ النسخة القديمة تُحفظ في /etc/ssl/wamda/old/.)
#
# الضمانات:
#   · الشهادة والمفتاح يُلصقان في **هذا الطرفي** مباشرةً: لا يمرّان بـClaude ولا بأي محادثة ولا argv ولا سجل.
#     المفتاح يُقرأ بلا صدى (read -s)، ولا يُطبع، و`set +x`/`HISTFILE=` مفروضان.
#   · يُكتبان في ملفات مؤقتة 0600 داخل /etc/ssl/wamda (0700) ثم يُتحقق منهما قبل أن يحلّا محل أي شيء:
#     (١) الشهادة تُحلَّل، (٢) المفتاح يُحلَّل، (٣) المفتاح يطابق الشهادة (بصمة المفتاح العام)،
#     (٤) الشهادة تغطي app.wamda.work، (٥) سارية ≥ 30 يوماً. أي فشل = حذف المؤقتات وخروج بلا تغيير.
#   · النتيجة: /etc/ssl/wamda/origin.pem (0644 root) و origin.key (0600 root). لا يمسّ nginx (edge_root.sh install يفعل).
#
# أين أحصل عليهما: لوحة Cloudflare ← SSL/TLS ← Origin Server ← Create Certificate (RUNBOOK §١٤، الخطوة ١).

set -euo pipefail
set +x
umask 077
export HISTFILE=/dev/null

DOMAIN=app.wamda.work
DIR=/etc/ssl/wamda
CERT=$DIR/origin.pem
KEY=$DIR/origin.key
REPLACE=0
[ "${1:-}" = "--replace" ] && REPLACE=1

die() { printf '\nخطأ: %s\n' "$*" >&2; exit 1; }
ok()  { printf '  ✔ %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "يجب التشغيل كـ root"
[ -t 0 ] || die "لا طرفي تفاعلي — شغّله عبر: ssh -t root@HOST 'bash /root/install_origin_cert.sh'"
command -v openssl >/dev/null || die "openssl غير موجود"

install -d -m 0700 "$DIR"
if [ -e "$CERT" ] || [ -e "$KEY" ]; then
  [ "$REPLACE" = 1 ] || die "الشهادة/المفتاح موجودان في $DIR — أعد التشغيل بـ --replace إن أردت الاستبدال"
fi

TMP_CERT="$(mktemp "$DIR/.cert.XXXXXX")"
TMP_KEY="$(mktemp "$DIR/.key.XXXXXX")"
cleanup() { rm -f "$TMP_CERT" "$TMP_KEY"; }
trap cleanup EXIT

# يقرأ كتلة PEM كاملة (من سطر BEGIN إلى END) إلى ملف. $1=الملف $2=نمط BEGIN $3=نمط END $4=صامت(0/1)
# الصمت بـ`stty -echo` **مرة واحدة حول الحلقة كلها** (لا `read -s` لكل سطر: بين الاستدعاءين يعود الصدى وقد يُطبَع سطر مفتاح).
read_pem() {
  local out="$1" begin="$2" end="$3" silent="$4" line n=0 started=0 rc=1
  : > "$out"
  if [ "$silent" = 1 ]; then stty -echo; trap 'stty echo 2>/dev/null; cleanup' EXIT; fi
  while IFS= read -r line; do
    line="${line%$'\r'}"                           # لصق من ويندوز
    [ -n "${line// /}" ] || continue
    if [ "$started" = 0 ]; then
      [[ "$line" =~ $begin ]] || { rc=2; break; }
      started=1
    fi
    printf '%s
' "$line" >> "$out"
    n=$((n + 1))
    if [ "$n" -gt 200 ]; then rc=3; break; fi
    if [[ "$line" =~ $end ]]; then rc=0; break; fi
  done
  if [ "$silent" = 1 ]; then stty echo; echo; trap cleanup EXIT; fi
  case "$rc" in
    0) return 0 ;;
    2) die "السطر الأول ليس بداية الكتلة المتوقعة — أُلغي" ;;
    3) die "كتلة أطول من المعقول — أُلغي" ;;
    *) die "انتهى الإدخال قبل نهاية الكتلة" ;;
  esac
}

cat <<EOF

══ تثبيت شهادة Cloudflare Origin لـ $DOMAIN ══
١) الصق **الشهادة** (Origin Certificate) كاملةً من «-----BEGIN CERTIFICATE-----» إلى «-----END CERTIFICATE-----»
   — ستُقبَل تلقائياً عند سطر END.
EOF
read_pem "$TMP_CERT" '^-----BEGIN CERTIFICATE-----$' '^-----END CERTIFICATE-----$' 0
ok "الشهادة استُلمت"

cat <<EOF

٢) الصق **المفتاح الخاص** (Private Key) كاملاً من «-----BEGIN PRIVATE KEY-----» إلى «-----END PRIVATE KEY-----»
   — لن يظهر شيء على الشاشة أثناء اللصق (هذا مقصود).
EOF
read_pem "$TMP_KEY" '^-----BEGIN ((RSA|EC) )?PRIVATE KEY-----$' '^-----END ((RSA|EC) )?PRIVATE KEY-----$' 1
ok "المفتاح استُلم (لم يُعرَض)"

echo
echo "التحقق:"
openssl x509 -in "$TMP_CERT" -noout >/dev/null 2>&1 || die "الشهادة لا تُحلَّل (PEM تالف؟)"
ok "الشهادة تُحلَّل"
openssl pkey -in "$TMP_KEY" -noout >/dev/null 2>&1 || die "المفتاح لا يُحلَّل (PEM تالف أو ناقص؟)"
ok "المفتاح يُحلَّل"
cert_fp="$(openssl x509 -in "$TMP_CERT" -noout -pubkey | openssl sha256 | awk '{print $NF}')"
key_fp="$(openssl pkey -in "$TMP_KEY" -pubout | openssl sha256 | awk '{print $NF}')"
[ -n "$cert_fp" ] && [ "$cert_fp" = "$key_fp" ] || die "المفتاح لا يطابق الشهادة — لصقتَ شهادة ومفتاحاً من زوجين مختلفين"
ok "المفتاح يطابق الشهادة"
openssl x509 -in "$TMP_CERT" -noout -checkhost "$DOMAIN" >/dev/null 2>&1 || die "الشهادة لا تغطي $DOMAIN (اسماء الشهادة: $(openssl x509 -in "$TMP_CERT" -noout -ext subjectAltName 2>/dev/null | tail -n +2 | tr -d ' '))"
ok "الشهادة تغطي $DOMAIN"
openssl x509 -in "$TMP_CERT" -noout -checkend $((30 * 86400)) >/dev/null 2>&1 || die "الشهادة منتهية أو تنتهي خلال 30 يوماً"
ok "الشهادة سارية ≥ 30 يوماً"

if [ -e "$CERT" ] || [ -e "$KEY" ]; then
  install -d -m 0700 "$DIR/old"
  stamp="$(date +%Y%m%d-%H%M%S)"
  [ -e "$CERT" ] && cp -p "$CERT" "$DIR/old/origin.pem.$stamp"
  [ -e "$KEY" ]  && cp -p "$KEY"  "$DIR/old/origin.key.$stamp"
fi
chmod 0600 "$TMP_KEY"; chmod 0644 "$TMP_CERT"
chown root:root "$TMP_KEY" "$TMP_CERT"
mv -f "$TMP_KEY" "$KEY"
mv -f "$TMP_CERT" "$CERT"
trap - EXIT

echo
echo "══ تم ══"
ls -l "$CERT" "$KEY"
echo "الموضوع/المنتهي/البصمة (غير سرّية):"
openssl x509 -in "$CERT" -noout -subject -issuer -startdate -enddate -fingerprint -sha256 | sed 's/^/    /'
echo
echo "التالي من جهازك:  ssh root@HOST 'bash -s -- install' < docs/deploy/edge_root.sh"
if [ -n "${SSH_CONNECTION:-}" ]; then
  echo "تنبيه: امسح ما لصقتَه من سجل الطرفي المحلي إن أمكن، وأغلق لوحة Cloudflare التي عرضت المفتاح (يُعرض مرة واحدة)."
fi

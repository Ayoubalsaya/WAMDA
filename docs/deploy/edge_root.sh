#!/usr/bin/env bash
# حافة ومضة: nginx + Cloudflare (DEPLOY_PLAN.md §٥، RUNBOOK §١٤) — يُشغَّل كـ root.
# ⚠ لا يُشغَّل قبل مراجعة مستقلة. كل مرحلة أمر منفصل، تنتهي بتحقق يوقف السكربت عند أول فشل.
# العنوان: https://app.wamda.work ← Cloudflare (Proxy، SSL = Full strict) ← nginx:443 ← uvicorn 127.0.0.1:8000
#
#   ١) plan       قراءة فقط: حالة nginx/ufw/الشهادة/الخدمة — لا يغيّر شيئاً
#   ٢) install    nginx + إعدادات الحافة + نطاقات Cloudflare (real_ip + ufw) — **يُبقي 80/443 المفتوحين للعموم**
#                 (تحتاج الشهادة موجودة: install_origin_cert.sh أولاً)
#   ٣) verify     تحقق شامل (آمن التكرار): الاستماع، الشهادة، حارس غير-Cloudflare، عنوان العميل الحقيقي من التطبيق
#                 فعلاً (مستمع مؤقت 127.0.0.1:18081)، ترويسات التخزين المؤقت
#   ٤) lockdown   بعد أن يعمل https://app.wamda.work عبر Cloudflare: حذف قواعد 80/443 المفتوحة للعموم
#                 (تبقى قواعد نطاقات Cloudflare و22 كما هو)
#   ٥) timer      يُفعِّل مؤقّتاً أسبوعياً لتحديث نطاقات Cloudflare (وحدة systemd مكتوبة في install)
#
# التشغيل من جهازك (السكربت يصل عبر stdin):
#   ssh root@144.91.81.150 'bash -s -- plan'     < docs/deploy/edge_root.sh
#   ssh root@144.91.81.150 'bash -s -- install'  < docs/deploy/edge_root.sh
#   ssh root@144.91.81.150 'bash -s -- verify'   < docs/deploy/edge_root.sh
#   ssh root@144.91.81.150 'bash -s -- lockdown' < docs/deploy/edge_root.sh
#   ssh root@144.91.81.150 'bash -s -- timer'    < docs/deploy/edge_root.sh
#
# الضمانات:
#   · لا يلمس sshd ولا قاعدة 22 ولا fail2ban. `lockdown` يرفض العمل إن لم يجد قواعد Cloudflare كاملة وقاعدة 22.
#   · لا يتصل بحساب Cloudflare ولا يطلب رمزاً: يقرأ القائمتين العامتين https://www.cloudflare.com/ips-v4 و ips-v6 فقط،
#     ويتحقق منهما صارماً (صيغة CIDR، حدود العدد، رفض النطاقات الواسعة) قبل أي تغيير؛ فشل التحقق = لا تغيير.
#   · المفتاح الخاص للشهادة لا يمرّ هنا إطلاقاً (install_origin_cert.sh يحفظه مباشرة على السيرفر).
#   · السجل: /var/log/wamda-edge.log (لا أسرار فيه).

set -euo pipefail

DOMAIN=app.wamda.work
APP_PORT=8000
TEST_PORT=18081
CERT_DIR=/etc/ssl/wamda
CERT=$CERT_DIR/origin.pem
KEY=$CERT_DIR/origin.key
UPDATER=/usr/local/sbin/wamda-update-cloudflare-ips
NGINX_CF=/etc/nginx/conf.d/00-wamda-cloudflare.conf
NGINX_HTTP=/etc/nginx/conf.d/01-wamda-http.conf
NGINX_PROXY=/etc/nginx/snippets/wamda-proxy.conf
NGINX_LOCS=/etc/nginx/snippets/wamda-locations.conf
NGINX_VHOST=/etc/nginx/sites-available/$DOMAIN.conf
NGINX_TEST=/etc/nginx/conf.d/99-wamda-edge-check.conf
ENV_FILE=/srv/wamda/app/.env
LOG=/var/log/wamda-edge.log

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\nخطأ: %s\n' "$*" >&2; exit 1; }
ok()  { printf '  ✔ %s\n' "$*"; }
chk() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else die "فشل التحقق: $d"; fi; }

# بلا `cmd | grep -q` (مع pipefail يُسقط SIGPIPE الأنبوب): الناتج إلى متغيّر أولاً
ufw_has_ssh_rule() {
  local o; o="$(ufw status)"
  grep -q '^Status: active' <<<"$o" && grep -qE '^22/tcp +ALLOW' <<<"$o"
}

# ═════════════════════ الملفات المُنزَّلة (heredocs بعلامات فريدة؛ يستخرجها tests/test_edge_config.py) ═════════════════════

write_updater() {
  install -d -m 0755 /usr/local/sbin
  cat > "$UPDATER.new" <<'WAMDA_UPDATER'
#!/usr/bin/env bash
# يجلب نطاقات IP الرسمية لـCloudflare ويحدّث: (١) nginx real_ip + حارس «من Cloudflare فقط»، (٢) قواعد ufw (80,443).
#   wamda-update-cloudflare-ips [--no-reload] [--no-firewall]
# فشل التحقق من القائمة = خروج ≠٠ بلا أي تغيير. فشل `nginx -t` = تراجع تلقائي إلى الملف السابق.
# حدود القبول: ≥١٢ نطاق IPv4 و≥٥ IPv6 (الفعلي ١٥/٧)، ولا تُسقط أكثر من ٣ نطاقات عمّا هو مطبَّق حالياً في nginx.
set -euo pipefail
NGINX_CF=/etc/nginx/conf.d/00-wamda-cloudflare.conf
NO_RELOAD=0; NO_FW=0
for a in "$@"; do
  case "$a" in --no-reload) NO_RELOAD=1 ;; --no-firewall) NO_FW=1 ;; *) echo "وسيط غير معروف: $a" >&2; exit 2 ;; esac
done
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fetch() { curl -fsS --proto '=https' --tlsv1.2 --max-time 30 --retry 2 "https://www.cloudflare.com/$1" -o "$TMP/$1"; }
fetch ips-v4
fetch ips-v6

# النطاقات المطبَّقة حالياً (للمقارنة): تُقرأ من ملف nginx الحالي؛ لا ملف = تثبيت أول = لا مقارنة
: > "$TMP/oldcidrs"
if [ -e "$NGINX_CF" ]; then
  grep -oE '^set_real_ip_from [^;]+' "$NGINX_CF" | awk '{print $2}' > "$TMP/oldcidrs" || true
fi

python3 - "$TMP/ips-v4" "$TMP/ips-v6" "$TMP/cf.conf" "$TMP/cidrs" "$TMP/oldcidrs" <<'WAMDA_PYGEN'
import ipaddress, sys, datetime

def load(path, ver, min_prefix, min_count, max_count):
    nets = []
    for raw in open(path, encoding="ascii").read().split():
        n = ipaddress.ip_network(raw, strict=True)           # صيغة CIDR صارمة (لا بتات مضيف)
        if n.version != ver:
            raise SystemExit(f"{raw}: ليس IPv{ver}")
        if n.prefixlen < min_prefix:                          # لا نثق بنطاق واسع (0.0.0.0/0 يعني الجميع)
            raise SystemExit(f"{raw}: نطاق أوسع من المسموح (/{min_prefix})")
        nets.append(n)
    nets = sorted(set(nets), key=lambda n: (int(n.network_address), n.prefixlen))
    if not (min_count <= len(nets) <= max_count):
        raise SystemExit(f"IPv{ver}: عدد النطاقات {len(nets)} خارج المتوقع [{min_count},{max_count}]")
    return nets

MAX_DROPPED = 3                      # أكثر من هذا مقارنةً بالمطبَّق = قائمة مبتورة مشبوهة → رفض

v4 = load(sys.argv[1], 4, 12, 12, 80)
v6 = load(sys.argv[2], 6, 20, 5, 40)
allnets = [str(n) for n in v4 + v6]
old = set(open(sys.argv[5], encoding="ascii").read().split()) if len(sys.argv) > 5 else set()
dropped = sorted(old - set(allnets))
if len(dropped) > MAX_DROPPED:
    raise SystemExit(f"القائمة الجديدة تُسقط {len(dropped)} نطاقاً مطبَّقاً حالياً (الأقصى {MAX_DROPPED}): {', '.join(dropped)} — رُفضت")
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
out = [f"# مولَّد بـwamda-update-cloudflare-ips ({stamp}) — لا يُعدَّل يدوياً. المصدر: https://www.cloudflare.com/ips-v4 و ips-v6",
       "# real_ip: عنوان العميل الحقيقي من CF-Connecting-IP **فقط** حين يكون النظير المباشر من نطاقات Cloudflare."]
out += [f"set_real_ip_from {c};" for c in allnets]
out += ["real_ip_header CF-Connecting-IP;", "real_ip_recursive off;", "",
        "# حارس: 1 = النظير المباشر الأصلي (قبل real_ip) من Cloudflare. غيره يُرفض في الـvhost (444).",
        "geo $realip_remote_addr $wamda_from_cloudflare {", "    default 0;"]
out += [f"    {c} 1;" for c in allnets]
out += ["}", ""]
open(sys.argv[3], "w", encoding="utf-8").write("\n".join(out))
open(sys.argv[4], "w", encoding="ascii").write("\n".join(allnets) + "\n")
WAMDA_PYGEN

NCIDR="$(wc -l < "$TMP/cidrs")"
echo "قائمة Cloudflare صالحة: $NCIDR نطاقاً (v4+v6)"

# ── nginx ──
HAD_OLD=0
if [ -e "$NGINX_CF" ]; then HAD_OLD=1; cp -p "$NGINX_CF" "$TMP/old.conf"; fi
if [ "$HAD_OLD" = 1 ] && cmp -s "$TMP/cf.conf" "$NGINX_CF"; then
  echo "nginx: القائمة لم تتغيّر"
else
  install -m 0644 "$TMP/cf.conf" "$NGINX_CF"
  if [ "$NO_RELOAD" = 0 ]; then
    if nginx -t >/dev/null 2>&1; then
      systemctl reload nginx
      echo "nginx: حُدِّث وأُعيد تحميله"
    else
      echo "nginx -t فشل — تراجع" >&2
      if [ "$HAD_OLD" = 1 ]; then install -m 0644 "$TMP/old.conf" "$NGINX_CF"; else rm -f "$NGINX_CF"; fi
      nginx -t >&2 || true
      exit 1
    fi
  else
    echo "nginx: كُتب الملف (بلا إعادة تحميل)"
  fi
fi

# ── ufw ──
if [ "$NO_FW" = 0 ]; then
  ipv6_on=0; grep -qE '^IPV6=yes' /etc/default/ufw && ipv6_on=1
  added=0
  while read -r c; do
    case "$c" in *:*) [ "$ipv6_on" = 1 ] || continue ;; esac
    ufw allow proto tcp from "$c" to any port 80,443 comment cloudflare >/dev/null
    added=$((added + 1))
  done < "$TMP/cidrs"
  ufw status numbered > "$TMP/ufw.txt"
  # قواعد cloudflare التي لم تعد في القائمة تُحذَف (تنازلياً: الترقيم يُعاد بعد كل حذف)
  python3 - "$TMP/ufw.txt" "$TMP/cidrs" > "$TMP/stale" <<'WAMDA_PYPRUNE'
import re, sys
keep = set(open(sys.argv[2]).read().split())
stale = []
for line in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"^\[\s*(\d+)\]\s+.*?ALLOW IN\s+(\S+)\s*#\s*cloudflare\s*$", line.rstrip())
    if m and m.group(2) not in keep:
        stale.append(int(m.group(1)))
print("\n".join(str(n) for n in sorted(stale, reverse=True)))
WAMDA_PYPRUNE
  removed=0
  while read -r n; do
    [ -n "$n" ] || continue
    ufw --force delete "$n" >/dev/null
    removed=$((removed + 1))
  done < "$TMP/stale"
  echo "ufw: قواعد Cloudflare مضافة/مؤكَّدة=$added · قديمة محذوفة=$removed"
fi
WAMDA_UPDATER
  chmod 0755 "$UPDATER.new"
  mv -f "$UPDATER.new" "$UPDATER"
}

write_nginx_confs() {
  install -d -m 0755 /etc/nginx/snippets /etc/nginx/conf.d /etc/nginx/sites-available /etc/nginx/sites-enabled

  cat > "$NGINX_HTTP" <<'WAMDA_NGINX_HTTP'
# ومضة — إعدادات http العامة للحافة (يكتبها edge_root.sh)
server_tokens off;

# السجل لا يحوي سلسلة الاستعلام (روابط دعوة/رموز) — المسار فقط. $remote_addr = عنوان العميل الحقيقي بعد real_ip؛
# $realip_remote_addr = نظير Cloudflare المباشر (للتشخيص).
log_format wamda '$remote_addr peer=$realip_remote_addr [$time_iso8601] $host "$request_method $uri" $status $body_bytes_sent '
                 'rt=$request_time cf_ray=$http_cf_ray';
WAMDA_NGINX_HTTP

  cat > "$NGINX_PROXY" <<'WAMDA_PROXY'
# ومضة — ترويسات الوكيل (مشتركة بين الـvhost الحقيقي ومستمع التحقق المؤقت)
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host              $host;
# بعد real_ip: $remote_addr = العميل الحقيقي (من CF-Connecting-IP) حين النظير من Cloudflare. nginx يُعيد كتابة الترويسة
# دائماً، فلا تصل قيمة مزوَّرة من العميل. التطبيق (TRUST_PROXY_HEADERS=true) يقرأ X-Real-IP.
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
# لا تُمرَّر ترويسات Cloudflare للتطبيق (لا يقرؤها ولا يجب أن يثق بها)
proxy_set_header CF-Connecting-IP  "";
proxy_set_header True-Client-IP    "";
proxy_connect_timeout 5s;
proxy_send_timeout    90s;
proxy_read_timeout    90s;     # توليد PDF/PNG (مهلة التطبيق 60ث)؛ Cloudflare نفسه يقطع عند 100ث
proxy_redirect off;
WAMDA_PROXY

  cat > "$NGINX_LOCS" <<'WAMDA_LOCATIONS'
# ومضة — مواقع الحافة (مشتركة بين الـvhost الحقيقي ومستمع التحقق المؤقت).
# سياسة التخزين المؤقت: **لا تخزين لأي شيء إلا الأصول المبنية ذات الأسماء المُجزَّأة** (/static/app/assets/*).
# كل شيء آخر (API، HTML، مستندات، أخطاء) `no-store` — يُفرَض هنا حتى لو نسيه التطبيق، ولا يعتمد على إعدادات Cloudflare.
location ^~ /static/app/assets/ {
    include snippets/wamda-proxy.conf;
    proxy_pass http://127.0.0.1:8000;
    proxy_hide_header Cache-Control;
    proxy_hide_header Expires;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
}

location / {
    include snippets/wamda-proxy.conf;
    proxy_pass http://127.0.0.1:8000;
    proxy_hide_header Cache-Control;
    proxy_hide_header Expires;
    proxy_hide_header Pragma;
    add_header Cache-Control "no-store" always;
}
WAMDA_LOCATIONS

  cat > "$NGINX_VHOST" <<'WAMDA_VHOST'
# ومضة — app.wamda.work (يكتبه edge_root.sh). TLS: شهادة Cloudflare Origin، ووضع Cloudflare = Full (strict).

# أي طلب لا يطابق الاسم (مثلاً بالـIP مباشرة) = إسقاط بلا رد.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 444;
}
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}

server {
    listen 80;
    listen [::]:80;
    server_name app.wamda.work;
    return 301 https://app.wamda.work$request_uri;     # النطاق ثابت (لا $host: حقن ترويسة Host)
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name app.wamda.work;

    ssl_certificate     /etc/ssl/wamda/origin.pem;
    ssl_certificate_key /etc/ssl/wamda/origin.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_session_cache   shared:wamda_ssl:5m;
    ssl_session_timeout 1h;
    ssl_session_tickets off;

    access_log /var/log/nginx/wamda-access.log wamda;
    error_log  /var/log/nginx/wamda-error.log warn;

    client_max_body_size 2m;           # لا رفع ملفات في التطبيق

    # طبقة دفاع ثانية فوق ufw: النظير المباشر ليس من نطاقات Cloudflare ⇒ إسقاط.
    if ($wamda_from_cloudflare = 0) { return 444; }

    include snippets/wamda-locations.conf;
}
WAMDA_VHOST

  rm -f "$NGINX_TEST"   # مستمع التحقق المؤقت يُنشأ فقط أثناء verify (write_test_vhost)

  ln -sfn "$NGINX_VHOST" "/etc/nginx/sites-enabled/$DOMAIN.conf"
  rm -f /etc/nginx/sites-enabled/default
}

write_test_vhost() {
  cat > "$NGINX_TEST" <<'WAMDA_TESTVHOST'
# مؤقت — يُنشئه edge_root.sh verify ويحذفه. يستخدم المواقع والترويسات نفسها، لكنه يثق بـ127.0.0.1 كنظير «Cloudflare»
# كي يُختبَر مسار real_ip كاملاً من حلقة محلية (طلبات الاختبار تحمل CF-Connecting-IP من نطاق التوثيق 192.0.2.0/24).
server {
    listen 127.0.0.1:18081;
    server_name wamda-edge-check;
    access_log off;
    set_real_ip_from 127.0.0.1;
    real_ip_header CF-Connecting-IP;
    include snippets/wamda-locations.conf;
}
WAMDA_TESTVHOST
}

write_timer_units() {
  cat > /etc/systemd/system/wamda-cloudflare-ips.service <<'WAMDA_CF_SERVICE'
[Unit]
Description=Wamda: refresh Cloudflare IP ranges (nginx real_ip + ufw)
After=network-online.target
Wants=network-online.target
# الفشل يظهر تنبيهاً critical في لوحة التحكم (job_failed_cloudflare-ips) كبقية المهام؛ الاسم = مثيل القالب (%i في wamda-job-failed@)
# لا `%n`: ذاك يعطي «wamda-cloudflare-ips.service» فيرفضه `job-status` (الاسم يجب أن يكون في JOB_LABELS_AR) ولا يظهر تنبيه.
OnFailure=wamda-job-failed@cloudflare-ips.service

[Service]
Type=oneshot
# يعمل كـroot (يعدّل ufw وnginx)؛ تسجيل النجاح (يمسح التنبيه) بصفة wamda كبقية المهام.
ExecStart=/usr/local/sbin/wamda-update-cloudflare-ips
ExecStartPost=/usr/sbin/runuser -u wamda -- /srv/wamda/venv/bin/python -m app.cli job-status cloudflare-ips --ok
WorkingDirectory=/srv/wamda/app
TimeoutStartSec=120
SyslogIdentifier=wamda-cloudflare-ips
WAMDA_CF_SERVICE
  cat > /etc/systemd/system/wamda-cloudflare-ips.timer <<'WAMDA_CF_TIMER'
[Unit]
Description=Wamda: weekly Cloudflare IP ranges refresh

[Timer]
OnCalendar=Mon *-*-* 05:00:00 Africa/Tripoli
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
WAMDA_CF_TIMER
  systemctl daemon-reload
}

# ───────────────────────── ١) plan (قراءة فقط) ─────────────────────────
phase_plan() {
  say "plan: حالة الحافة (قراءة فقط)"
  printf 'nginx: '; (command -v nginx >/dev/null && nginx -v 2>&1) || echo "غير مثبَّت"
  printf 'شهادة المصدر: '; [ -s "$CERT" ] && [ -s "$KEY" ] && echo "موجودة ($CERT)" || echo "غير موجودة — شغّل install_origin_cert.sh أولاً"
  [ -s "$CERT" ] && openssl x509 -in "$CERT" -noout -subject -enddate 2>/dev/null | sed 's/^/    /' || true
  printf 'خدمة التطبيق: '; curl -s --max-time 5 "http://127.0.0.1:$APP_PORT/health" || echo "لا تستجيب"; echo
  echo "ufw:"; ufw status numbered | sed 's/^/    /'
  echo "المنافذ المستمعة:"; ss -H -tlnp | awk '{print "    "$4"  "$6}'
  printf 'PUBLIC_BASE_URL في .env: '; grep -E '^PUBLIC_BASE_URL=' "$ENV_FILE" 2>/dev/null | sed 's/^PUBLIC_BASE_URL=//' | sed 's/^$/(فارغ)/' || echo "؟"
}

# ───────────────────────── ٢) install ─────────────────────────
phase_install() {
  say "install: nginx + إعدادات الحافة + نطاقات Cloudflare"
  [ -s "$CERT" ] && [ -s "$KEY" ] || die "شهادة المصدر غير موجودة ($CERT/$KEY) — شغّل install_origin_cert.sh أولاً"
  chk "الشهادة سارية ≥ 30 يوماً" openssl x509 -in "$CERT" -noout -checkend $((30 * 86400))
  chk "الشهادة تغطي $DOMAIN" openssl x509 -in "$CERT" -noout -checkhost "$DOMAIN"
  chk "التطبيق يستجيب على 127.0.0.1:$APP_PORT" curl -fsS --max-time 5 "http://127.0.0.1:$APP_PORT/health"
  ufw_has_ssh_rule || die "لا قاعدة 22/tcp في ufw (أو ufw غير مفعّل) — لن أمسّ الجدار الناري"

  if ! command -v nginx >/dev/null 2>&1; then
    say "تثبيت nginx"
    apt-get -y -o DPkg::Lock::Timeout=300 install --no-install-recommends nginx curl python3
  fi
  chk "python3 وcurl موجودان" bash -c 'command -v python3 && command -v curl'

  write_updater
  ok "المُحدِّث: $UPDATER"
  # ١) قائمة Cloudflare + real_ip (بلا إعادة تحميل بعد: الـvhost لم يُكتب)
  "$UPDATER" --no-reload --no-firewall
  # ٢) بقية الإعدادات
  write_nginx_confs
  chk "nginx -t" nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
  chk "nginx يعمل" systemctl is-active --quiet nginx
  # ٣) قواعد ufw لنطاقات Cloudflare (تُضاف إلى القاعدتين المفتوحتين الحاليتين، لا تستبدلهما)
  "$UPDATER" --no-reload
  write_timer_units
  ok "وحدتا المؤقّت مكتوبتان (غير مفعَّلتين — مرحلة timer)"

  say "ufw الآن"
  ufw status numbered
  cat <<EOF

التالي (بيدك في لوحة Cloudflare): SSL/TLS ← Overview ← Full (strict)، ثم افتح https://$DOMAIN
ثم:  ssh root@HOST 'bash -s -- verify' < docs/deploy/edge_root.sh
وبعد نجاحه وتجربة المتصفح:  ... lockdown
EOF
}

# ───────────────────────── ٣) verify ─────────────────────────
curl_loop() {   # curl_loop <ip> [extra curl args...] → يطبع رمز HTTP لطلب دخول فاشل من «عميل» بعنوان <ip>
  local ip="$1"; shift
  curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "http://127.0.0.1:$TEST_PORT/auth/login" \
    -H 'Content-Type: application/json' -H "CF-Connecting-IP: $ip" "$@" \
    -d '{"username":"__edge_check__","password":"x"}'
}

phase_verify() {
  say "verify: الحافة"
  [ -x "$UPDATER" ] && [ -e "$NGINX_VHOST" ] || die "لم يُنفَّذ install بعد"
  chk "nginx -t" nginx -t
  chk "nginx يعمل" systemctl is-active --quiet nginx
  grep -qE '^server_tokens off;' "$NGINX_HTTP" && ok "server_tokens off" || die "server_tokens off غائب"

  say "الاستماع"
  local listen; listen="$(ss -H -tln | awk '{print $4}' | sort -u)"
  grep -qE '^(0\.0\.0\.0|\*):443$' <<<"$listen" && ok "nginx يستمع على 443" || die "لا استماع على 443"
  grep -qE '^127\.0\.0\.1:8000$' <<<"$listen" && ok "التطبيق على 127.0.0.1:8000" || die "التطبيق لا يستمع على 127.0.0.1:8000"
  if grep -qE "^(0\.0\.0\.0|\*|\[::\]):${APP_PORT}$" <<<"$listen"; then die "التطبيق يستمع على عنوان عام"; fi
  ok "التطبيق غير مكشوف على عنوان عام"
  if grep -q ":${TEST_PORT}$" <<<"$listen"; then die "مستمع الاختبار $TEST_PORT موجود قبل البدء"; fi

  say "الشهادة المخدومة"
  # شهادة Cloudflare Origin: CN عام والنطاق في SAN، فالمطابقة بـ-checkhost لا بنص subject.
  local served; served="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMAIN" 2>/dev/null | openssl x509 2>/dev/null || true)"
  [ -n "$served" ] || die "لا شهادة على 127.0.0.1:443"
  printf '%s\n' "$served" | openssl x509 -noout -subject -enddate | sed 's/^/    /'
  printf '%s\n' "$served" | openssl x509 -noout -checkhost "$DOMAIN" 2>/dev/null | grep -q 'does match' \
    && ok "الشهادة للنطاق $DOMAIN" || die "الشهادة المخدومة لا تخص $DOMAIN"

  say "الحارس: نظير ليس من Cloudflare يُسقَط (444)"
  local rc=0
  curl -sk --max-time 8 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/health" -o /dev/null || rc=$?
  [ "$rc" = 52 ] && ok "طلب محلي بلا Cloudflare: لا رد (curl 52 = 444)" || die "كان يجب إسقاط الطلب (curl rc=$rc)"

  say "عنوان العميل الحقيقي يصل التطبيق (مستمع مؤقت 127.0.0.1:$TEST_PORT، المواقع والترويسات نفسها)"
  write_test_vhost
  trap 'rm -f "$NGINX_TEST"; nginx -t >/dev/null 2>&1 && systemctl reload nginx || true' EXIT
  nginx -t >/dev/null 2>&1 || die "nginx -t فشل مع مستمع الاختبار"
  systemctl reload nginx
  sleep 1
  local A B C n code got429=0
  A="192.0.2.$((RANDOM % 100 + 10))"; B="192.0.2.$((RANDOM % 100 + 120))"; C="198.51.100.$((RANDOM % 200 + 10))"
  for n in $(seq 1 14); do
    code="$(curl_loop "$A")"
    if [ "$code" = 429 ]; then got429=$n; break; fi
    [ "$code" = 401 ] || die "رد غير متوقع من الدخول: $code (الطلب $n)"
  done
  [ "$got429" -gt 0 ] && ok "العميل A ($A) بلغ الحد عند الطلب $got429 (حدّ .env + 1)" || die "العميل A لم يُحجَب بعد 14 طلباً — الحدّ لا يعمل"
  code="$(curl_loop "$B")"
  [ "$code" = 401 ] && ok "العميل B ($B) غير متأثر بحجب A (401 لا 429) ⇒ كل عميل بعنوانه لا بعنوان Cloudflare/127.0.0.1" \
                    || die "العميل B حُجب أو فشل ($code) — الحدّ مشترك: real_ip لا يعمل"
  code="$(curl_loop "$A" -H "X-Real-IP: $C" -H "X-Forwarded-For: $C")"
  [ "$code" = 429 ] && ok "تزوير X-Real-IP/X-Forwarded-For من العميل لا يفكّ حجب A" || die "التزوير نجح ($code)"

  say "ترويسات التخزين المؤقت (عبر المواقع نفسها)"
  local asset; asset="$(find /srv/wamda/app/app/static/app/assets -maxdepth 1 -name '*.js' -printf '%f\n' -quit 2>/dev/null || true)"
  hdr() { curl -s -D - -o /dev/null --max-time 10 "http://127.0.0.1:$TEST_PORT$1" | tr -d '\r'; }
  local h
  if [ -n "$asset" ]; then
    h="$(hdr "/static/app/assets/$asset")"
    grep -qi '^cache-control: public, max-age=31536000, immutable$' <<<"$h" && ok "الأصل المُجزَّأ: immutable قابل للتخزين" || { echo "$h"; die "ترويسة الأصل خاطئة"; }
  else
    echo "  ⚠ لا أصول مبنية على السيرفر (الواجهة لم تُشحن) — تُخطّى فحص الأصول"
  fi
  local p
  for p in /static/app/index.html /static/app/portal.html / /health /auth/me /api/__nope__ /docs; do
    h="$(hdr "$p")"
    grep -qi '^cache-control: no-store$' <<<"$h" && ok "$p ⇒ no-store" || { echo "$h"; die "$p بلا no-store"; }
    ! grep -qi '^cache-control:.*\(public\|max-age=[1-9]\)' <<<"$h" || die "$p يحمل ترويسة تخزين مؤقت"
  done
  h="$(hdr /health)"
  grep -qiE '^server: nginx *$' <<<"$h" && ok "Server: nginx بلا إصدار" || { echo "$h"; die "ترويسة Server تكشف إصداراً أو غائبة"; }

  rm -f "$NGINX_TEST"; nginx -t >/dev/null && systemctl reload nginx
  trap - EXIT
  # systemctl reload يعود قبل أن يغلق nginx المقبس القديم؛ نمهل حتى ١٠ ثوانٍ لا قراءة واحدة.
  local n
  for n in 1 2 3 4 5 6 7 8 9 10; do
    listen="$(ss -H -tln | awk '{print $4}')"
    grep -q ":${TEST_PORT}$" <<<"$listen" || break
    sleep 1
  done
  if grep -q ":${TEST_PORT}$" <<<"$listen"; then die "مستمع الاختبار ما زال قائماً"; fi
  ok "مستمع الاختبار أُزيل"

  say "ufw"
  ufw status verbose | sed 's/^/    /'
  local uo open; uo="$(ufw status)"; open="$(grep -E '^(80|443)(/tcp)?( +| \(v6\) +)ALLOW +Anywhere' <<<"$uo" || true)"
  if [ -n "$open" ]; then echo "  ⚠ 80/443 ما زالا مفتوحَين للعموم (متوقَّع قبل lockdown):"; echo "$open" | sed 's/^/    /'; else ok "لا قاعدة 80/443 مفتوحة للعموم"; fi
  say "verify: تم ✔"
  echo "من جهازك: curl -sI https://$DOMAIN/health   ← يجب 200 وترويسة cf-cache-status: DYNAMIC (أو BYPASS)"
}

# ───────────────────────── ٤) lockdown ─────────────────────────
phase_lockdown() {
  say "lockdown: 80/443 من Cloudflare فقط"
  [ -x "$UPDATER" ] || die "لم يُنفَّذ install"
  local cfo cf; cfo="$(ufw status)"; cf="$(grep -cE '# cloudflare *$' <<<"$cfo" || true)"
  [ "$cf" -ge 15 ] || die "قواعد Cloudflare في ufw ($cf) أقل من المتوقع — لن أحذف القواعد المفتوحة"
  ufw_has_ssh_rule || die "لا قاعدة 22/tcp (أو ufw غير مفعّل) — لن أمسّ الجدار الناري"
  # لا يُغلق شيء قبل إثبات المسار الكامل الذي سيبقى الوحيد: Cloudflare ← nginx ← التطبيق (من السيرفر نفسه، بالاسم العام).
  local direct_json direct_commit via_hdr via_json via_commit git_head
  direct_json="$(curl -fsS --max-time 5 "http://127.0.0.1:$APP_PORT/health")" || die "التطبيق لا يستجيب مباشرةً على 127.0.0.1:$APP_PORT"
  direct_commit="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("commit",""))' "$direct_json")"
  [ -n "$direct_commit" ] || die "/health المباشر لا يعيد رقم الالتزام: $direct_json"
  via_hdr="$(mktemp)"
  via_json="$(curl -fsS --max-time 20 -H 'Cache-Control: no-cache' -D "$via_hdr" "https://$DOMAIN/health?lockdown=$RANDOM")"     || { rm -f "$via_hdr"; die "فشل https://$DOMAIN/health من السيرفر (Cloudflare ← nginx ← التطبيق) — لن أغلق شيئاً"; }
  grep -qi '^cf-ray:' "$via_hdr" || { rm -f "$via_hdr"; die "الرد لم يمرّ عبر Cloudflare (لا ترويسة cf-ray) — السجل ليس Proxy؟ لن أغلق شيئاً"; }
  rm -f "$via_hdr"
  via_commit="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("commit",""))' "$via_json" 2>/dev/null || true)"
  [ -n "$via_commit" ] && [ "$via_commit" = "$direct_commit" ]     || die "رقم الالتزام عبر Cloudflare ('$via_commit') لا يطابق التطبيق المُشغَّل ('$direct_commit') — لن أغلق شيئاً"
  ok "https://$DOMAIN/health عبر Cloudflare ← nginx ← التطبيق يعيد الالتزام المُشغَّل ($via_commit)"
  git_head="$(git -C /srv/wamda/app rev-parse --short=7 HEAD 2>/dev/null || true)"
  [ -z "$git_head" ] || [ "$git_head" = "$via_commit" ] || echo "  ⚠ مجلد الكود على HEAD=$git_head والمُشغَّل $via_commit (سُحب كود جديد دون إعادة تشغيل؟) — الفحص يخصّ المُشغَّل فعلاً"
  ufw status numbered > /tmp/.wamda-ufw.$$
  local nums
  nums="$(python3 - /tmp/.wamda-ufw.$$ <<'WAMDA_PYOPEN'
import re, sys
nums = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.rstrip()
    if re.search(r"#\s*cloudflare\s*$", line):
        continue
    m = re.match(r"^\[\s*(\d+)\]\s+(\S+)(?:\s+\(v6\))?\s+ALLOW IN\s+Anywhere(?:\s+\(v6\))?\s*$", line)
    if m and re.match(r"^(80|443)(/tcp)?$", m.group(2)):
        nums.append(int(m.group(1)))
print("\n".join(str(n) for n in sorted(nums, reverse=True)))
WAMDA_PYOPEN
)"
  rm -f /tmp/.wamda-ufw.$$
  if [ -z "$nums" ]; then
    ok "لا قواعد 80/443 مفتوحة للعموم (منفَّذ سابقاً)"
  else
    local n; for n in $nums; do ufw --force delete "$n" >/dev/null; done
    ok "حُذفت قواعد 80/443 المفتوحة للعموم"
  fi
  ufw_has_ssh_rule || { ufw allow 22/tcp >/dev/null; die "قاعدة 22 اختفت — أُعيدت؛ راجع ufw status"; }
  ok "قاعدة 22/tcp باقية"
  ufw status numbered | sed 's/^/    /'
  echo
  echo "تحقّق من خارج السيرفر: https://$DOMAIN يعمل، و curl -sk --max-time 8 https://144.91.81.150/ يجب أن يتعلّق/يُرفض (لا رد)."
}

# ───────────────────────── ٥) timer ─────────────────────────
phase_timer() {
  say "timer: تحديث نطاقات Cloudflare أسبوعياً"
  [ -x "$UPDATER" ] || die "لم يُنفَّذ install"
  write_timer_units
  systemctl enable --now wamda-cloudflare-ips.timer
  systemctl list-timers wamda-cloudflare-ips.timer --no-pager
  say "تشغيل واحد الآن للتأكد"
  systemctl start wamda-cloudflare-ips.service
  systemctl --no-pager status wamda-cloudflare-ips.service | head -8 || true
}

main() {
  exec </dev/null        # stdin هو السكربت نفسه
  trap '' HUP
  [ "$(id -u)" -eq 0 ] || die "يجب التشغيل كـ root"
  local phase="${1:-}"
  export LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
  cd /
  exec > >(tee --output-error=warn-nopipe -a "$LOG") 2>&1
  say "edge_root.sh :: $phase"
  case "$phase" in
    plan)     phase_plan ;;
    install)  phase_install ;;
    verify)   phase_verify ;;
    lockdown) phase_lockdown ;;
    timer)    phase_timer ;;
    *) die "مرحلة غير معروفة: '$phase' (plan|install|verify|lockdown|timer)" ;;
  esac
}

main "$@"   # آخر سطر عمداً: bash يقرأ الدالة كاملة قبل التنفيذ

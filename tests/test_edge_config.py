"""حافة الإنتاج (٢٠٢٦-١٠-١٥): nginx + Cloudflare — `docs/deploy/edge_root.sh` وسكربتا الشهادة و`PUBLIC_BASE_URL`.

لا nginx ولا ufw على هذا الجهاز، فالاختبار يثبت ما يمكن إثباته محلياً:
  · مولِّد قائمة Cloudflare (nginx real_ip + الحارس) يعمل ويرفض القوائم المشبوهة قبل أي تغيير،
  · محلِّلات قواعد ufw (حذف القديم من Cloudflare / حذف المفتوح للعموم دون 22) على ناتج `ufw status numbered` حقيقي الشكل،
  · إعدادات nginx تفرض: عنوان العميل الحقيقي لا يُزوَّر، لا تخزين مؤقت إلا للأصول المُجزَّأة، لا إصدار في Server،
  · التطبيق يفرّد حدّ الدخول بـX-Real-IP (كما يضبطه nginx) ولا يقرأ CF-Connecting-IP بنفسه،
  · الاختبار الفعلي end-to-end على السيرفر هو `edge_root.sh verify` (مستمع مؤقت يستخدم المواقع نفسها).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app

DEPLOY = Path(__file__).resolve().parents[1] / "docs" / "deploy"
EDGE = (DEPLOY / "edge_root.sh").read_text(encoding="utf-8")

CF_V4 = """173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 190.93.240.0/20
188.114.96.0/20 197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 104.24.0.0/14 172.64.0.0/13 131.0.72.0/22"""
CF_V6 = "2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32"


def _working_bash() -> str | None:
    """bash يعمل فعلاً (على ويندوز قد يكون `bash` في PATH هو مُطلِق WSL المعطَّل) — Git Bash أولاً."""
    for cand in ("C:/Program Files/Git/bin/bash.exe", shutil.which("bash")):
        if not cand or not Path(cand).exists():
            continue
        try:
            r = subprocess.run([cand, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and r.stdout.strip() == "ok":
            return cand
    return None


BASH = _working_bash()


def heredoc(tag: str) -> str:
    m = re.search(r"<<'%s'\n(.*?)\n%s\n" % (tag, tag), EDGE, re.S)
    assert m, f"heredoc {tag} غير موجود في edge_root.sh"
    return m.group(1)


def run_py(code: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-c", code, *args], capture_output=True, text=True, input=stdin, timeout=30)


def gen(tmp_path: Path, v4: str, v6: str, old: str = ""):
    """`old`: النطاقات المطبَّقة حالياً (محتوى oldcidrs كما يستخرجه المحدِّث من ملف nginx الحالي)."""
    (tmp_path / "v4").write_text(v4, encoding="ascii")
    (tmp_path / "v6").write_text(v6, encoding="ascii")
    (tmp_path / "old").write_text(old, encoding="ascii")
    r = run_py(heredoc("WAMDA_PYGEN"), str(tmp_path / "v4"), str(tmp_path / "v6"), str(tmp_path / "cf.conf"), str(tmp_path / "cidrs"),
               str(tmp_path / "old"))
    return r


# ── المولِّد ─────────────────────────────────────────────────────────────


def test_generator_emits_real_ip_and_guard(tmp_path):
    r = gen(tmp_path, CF_V4, CF_V6)
    assert r.returncode == 0, r.stderr
    conf = (tmp_path / "cf.conf").read_text(encoding="utf-8")
    for cidr in CF_V4.split() + CF_V6.split():
        assert f"set_real_ip_from {cidr};" in conf
        assert f"    {cidr} 1;" in conf
    assert "real_ip_header CF-Connecting-IP;" in conf
    assert "real_ip_recursive off;" in conf
    assert "geo $realip_remote_addr $wamda_from_cloudflare {" in conf and "default 0;" in conf
    assert len((tmp_path / "cidrs").read_text().split()) == 22


@pytest.mark.parametrize("v4,v6,why", [
    ("0.0.0.0/0", CF_V6, "نطاق يعني الجميع"),
    (CF_V4 + " 8.8.0.0/8", CF_V6, "نطاق أوسع من /12"),
    (CF_V4 + " 1.2.3.4/20", CF_V6, "بتات مضيف"),
    (CF_V4 + " not-an-ip", CF_V6, "نص عشوائي"),
    ("173.245.48.0/20 103.21.244.0/22", CF_V6, "قائمة قصيرة مريبة (أخطأت الصفحة/صفحة خطأ)"),
    (" ".join(CF_V4.split()[:11]), CF_V6, "11 نطاق v4: أقل من الحد الأدنى 12"),
    (CF_V4, " ".join(CF_V6.split()[:4]), "4 نطاقات v6: أقل من الحد الأدنى 5"),
    ("", CF_V6, "قائمة v4 فارغة"),
    (CF_V4, "", "قائمة v6 فارغة"),
    (CF_V4, "::/0", "v6 يعني الجميع"),
    (CF_V4, "2400:cb00::/32", "v6 قليلة"),
    (CF_V4 + " 2400:cb00::/32", CF_V6, "v6 داخل ملف v4"),
    ("<html>Access denied</html>", CF_V6, "HTML بدل قائمة"),
])
def test_generator_rejects_suspicious_lists_without_writing(tmp_path, v4, v6, why):
    r = gen(tmp_path, v4, v6)
    assert r.returncode != 0, why
    assert not (tmp_path / "cf.conf").exists(), why


def test_generator_accepts_exact_minimums(tmp_path):
    r = gen(tmp_path, " ".join(CF_V4.split()[:12]), " ".join(CF_V6.split()[:5]))
    assert r.returncode == 0, r.stderr
    assert len((tmp_path / "cidrs").read_text().split()) == 17


EXTRA = "1.0.0.0/22 1.0.4.0/22 1.0.8.0/22 1.0.12.0/22"     # نطاقات «مطبَّقة سابقاً» ليست في القائمة الجديدة


def test_generator_allows_dropping_up_to_three_applied_ranges(tmp_path):
    old = " ".join(CF_V4.split() + CF_V6.split() + EXTRA.split()[:3])
    r = gen(tmp_path, CF_V4, CF_V6, old=old)
    assert r.returncode == 0, r.stderr
    conf = (tmp_path / "cf.conf").read_text(encoding="utf-8")
    assert "1.0.0.0/22" not in conf                      # المُسقَط يختفي فعلاً


def test_generator_rejects_dropping_more_than_three_applied_ranges_without_writing(tmp_path):
    old = " ".join(CF_V4.split() + CF_V6.split() + EXTRA.split())          # 4 مُسقَطة
    r = gen(tmp_path, CF_V4, CF_V6, old=old)
    assert r.returncode != 0
    assert "تُسقط 4" in r.stderr or "4" in r.stderr
    assert not (tmp_path / "cf.conf").exists() and not (tmp_path / "cidrs").exists()


def test_generator_first_install_has_no_comparison(tmp_path):
    assert gen(tmp_path, CF_V4, CF_V6, old="").returncode == 0


def test_updater_passes_applied_list_to_generator():
    upd = heredoc("WAMDA_UPDATER")
    assert "grep -oE '^set_real_ip_from [^;]+' \"$NGINX_CF\"" in upd
    assert '"$TMP/cidrs" "$TMP/oldcidrs"' in upd
    assert "MAX_DROPPED = 3" in upd
    assert "load(sys.argv[1], 4, 12, 12, 80)" in upd and "load(sys.argv[2], 6, 20, 5, 40)" in upd


# ── وحدة المحدِّث ← لوحة التحكم ──────────────────────────────────────────


def test_updater_service_failure_reaches_dashboard():
    from app.cli.job_status import JOB_LABELS_AR

    svc = heredoc("WAMDA_CF_SERVICE")
    m = re.search(r"^OnFailure=wamda-job-failed@([^.\s]+)\.service$", svc, re.M)
    assert m, "OnFailure غائب"
    job = m.group(1)
    assert job in JOB_LABELS_AR, f"{job} ليس اسم مهمة معروفاً لـjob-status — التنبيه لن يظهر"
    assert "%n" not in m.group(0)
    assert f"job-status {job} --ok" in svc                # نجاحٌ لاحق يمسح التنبيه
    assert "SyslogIdentifier=wamda-cloudflare-ips" in svc



# ── محلِّلات ufw ─────────────────────────────────────────────────────────

UFW = """Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     ALLOW IN    Anywhere
[ 2] 80/tcp                     ALLOW IN    Anywhere
[ 3] 443/tcp                    ALLOW IN    Anywhere
[ 4] 80,443/tcp                 ALLOW IN    173.245.48.0/20            # cloudflare
[ 5] 80,443/tcp                 ALLOW IN    10.9.9.0/24                # cloudflare
[ 6] 22/tcp (v6)                ALLOW IN    Anywhere (v6)
[ 7] 80/tcp (v6)                ALLOW IN    Anywhere (v6)
[ 8] 443/tcp (v6)               ALLOW IN    Anywhere (v6)
[ 9] 80,443/tcp                 ALLOW IN    2400:cb00::/32             # cloudflare
[10] 80,443/tcp                 ALLOW IN    2001:db8::/32              # cloudflare
[11] 8443/tcp                   ALLOW IN    Anywhere
"""


def test_ufw_prune_removes_only_stale_cloudflare_rules_descending(tmp_path):
    ufw = tmp_path / "ufw.txt"
    ufw.write_text(UFW, encoding="utf-8")
    keep = tmp_path / "cidrs"
    keep.write_text("173.245.48.0/20\n2400:cb00::/32\n", encoding="ascii")
    r = run_py(heredoc("WAMDA_PYPRUNE"), str(ufw), str(keep))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10", "5"]            # القديمتان فقط، تنازلياً (الترقيم يُعاد بعد كل حذف)


def test_lockdown_deletes_only_open_80_443_never_22_or_cloudflare(tmp_path):
    ufw = tmp_path / "ufw.txt"
    ufw.write_text(UFW, encoding="utf-8")
    r = run_py(heredoc("WAMDA_PYOPEN"), str(ufw))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["8", "7", "3", "2"]   # 80/443 (v4+v6) فقط؛ لا 22 (1،6) ولا cloudflare ولا 8443


# ── إعدادات nginx ────────────────────────────────────────────────────────

PROXY = heredoc("WAMDA_PROXY")
LOCS = heredoc("WAMDA_LOCATIONS")
VHOST = heredoc("WAMDA_VHOST")
HTTP = heredoc("WAMDA_NGINX_HTTP")


def test_proxy_sets_real_client_ip_from_realip_module_and_never_trusts_client_headers():
    assert "proxy_set_header X-Real-IP         $remote_addr;" in PROXY
    assert "proxy_set_header X-Forwarded-For   $remote_addr;" in PROXY       # لا $proxy_add_x_forwarded_for (يُلحِق ترويسة العميل)
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in PROXY
    assert 'proxy_set_header CF-Connecting-IP  "";' in PROXY
    assert "$http_x_real_ip" not in PROXY + LOCS + VHOST
    assert "$http_x_forwarded_for" not in PROXY + LOCS + VHOST
    assert "$proxy_add_x_forwarded_for" not in PROXY + LOCS + VHOST


def test_only_loopback_upstream_and_hidden_version():
    assert set(re.findall(r"proxy_pass\s+(\S+);", LOCS)) == {"http://127.0.0.1:8000"}
    assert re.search(r"^server_tokens off;", HTTP, re.M)


def test_cache_policy_only_hashed_assets_cacheable():
    asset = re.search(r"location \^~ /static/app/assets/ \{(.*?)\n\}", LOCS, re.S).group(1)
    assert 'add_header Cache-Control "public, max-age=31536000, immutable" always;' in asset
    root = re.search(r"location / \{(.*?)\n\}", LOCS, re.S).group(1)
    assert 'add_header Cache-Control "no-store" always;' in root
    for blk in (asset, root):
        assert "proxy_hide_header Cache-Control;" in blk           # الحافة هي صاحبة القرار لا التطبيق
    # لا موقع ثالث يفتح تخزين مسار آخر
    assert len(re.findall(r"^location ", LOCS, re.M)) == 2


def test_vhost_guard_default_server_and_fixed_redirect():
    assert "if ($wamda_from_cloudflare = 0) { return 444; }" in VHOST
    assert "ssl_reject_handshake on;" in VHOST
    assert "return 301 https://app.wamda.work$request_uri;" in VHOST          # لا $host
    assert "include snippets/wamda-locations.conf;" in VHOST
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in VHOST
    assert len(re.findall(r"return 444;", VHOST)) >= 2


def test_access_log_has_no_query_strings():
    fmt = re.search(r"log_format wamda (.*?);", HTTP, re.S).group(1)
    assert "$remote_addr" in fmt
    for banned in ("$request ", '$request"', "$args", "$query_string", "$request_uri", "$http_referer", "$http_cookie"):
        assert banned not in fmt, banned


# ── التطبيق ──────────────────────────────────────────────────────────────


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def test_app_buckets_by_x_real_ip_and_ignores_cloudflare_header(client, monkeypatch):
    """ما يضبطه nginx: X-Real-IP = العميل الحقيقي. التطبيق لا يقرأ CF-Connecting-IP ولا يخدعه تغيّره بين الطلبات."""
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    limit = settings.login_rate_limit_max
    body = {"username": "qa_edge", "password": "x"}
    for i in range(limit):
        r = client.post("/auth/login", json=body, headers={"X-Real-IP": "203.0.113.55", "CF-Connecting-IP": f"198.51.100.{i + 1}"})
        assert r.status_code == 401
    # نفس العميل الحقيقي ⇒ محجوب مهما كانت ترويسة Cloudflare
    r = client.post("/auth/login", json=body, headers={"X-Real-IP": "203.0.113.55", "CF-Connecting-IP": "198.51.100.200"})
    assert r.status_code == 429
    # عميل آخر حقيقي (عنوان Cloudflare القادم منه نفسه) غير متأثر
    r = client.post("/auth/login", json=body, headers={"X-Real-IP": "203.0.113.56", "CF-Connecting-IP": "198.51.100.200"})
    assert r.status_code == 401


# ── السكربتات ────────────────────────────────────────────────────────────


@pytest.mark.skipif(BASH is None, reason="bash غير متوفر/معطَّل")
@pytest.mark.parametrize("name", ["edge_root.sh", "install_origin_cert.sh", "set_public_base_url.sh"])
def test_shell_scripts_parse(name):
    r = subprocess.run([BASH, "-n", str(DEPLOY / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(BASH is None, reason="bash غير متوفر/معطَّل")
def test_embedded_updater_parses(tmp_path):
    p = tmp_path / "updater.sh"
    p.write_text(heredoc("WAMDA_UPDATER") + "\n", encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_cert_script_never_prints_or_traces_the_key():
    s = (DEPLOY / "install_origin_cert.sh").read_text(encoding="utf-8")
    code = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))
    assert "set +x" in s and "HISTFILE=/dev/null" in s
    assert "stty -echo" in code
    assert not re.search(r"set -[a-z]*x", code)
    assert not re.search(r'(echo|printf|cat)[^\n|>]*"?\$(TMP_)?KEY', code)          # لا طباعة مسار/محتوى المفتاح كمتغيّر
    assert 'openssl pkey -in "$TMP_KEY" -pubout' in code and "-noout" in code
    assert 'chmod 0600 "$TMP_KEY"' in code


def test_lockdown_proves_public_path_before_deleting_anything():
    body = re.search(r"^phase_lockdown\(\) \{\n(.*?)\n\}\n", EDGE, re.S | re.M).group(1)
    first_delete = body.index("ufw --force delete")
    check = body.index("https://$DOMAIN/health")
    assert check < first_delete, "فحص المسار العام يجب أن يسبق أي حذف"
    # الفحص يمرّ فعلاً عبر Cloudflare ويقارن الالتزام المُشغَّل
    assert "cf-ray" in body and '"$via_commit" = "$direct_commit"' in body
    # وصف الفحص القديم المضلِّل («عبر nginx» وهو يسأل التطبيق مباشرة) زال
    assert "عبر nginx يعمل محلياً" not in body
    # كل فشل قبل الحذف يوقف السكربت برسالة «لن أغلق شيئاً»
    pre = body[:first_delete]
    assert pre.count("لن أغلق شيئاً") >= 3



def test_edge_script_does_not_touch_ssh_rule_or_cloudflare_account():
    code = "\n".join(l for l in EDGE.splitlines() if not l.lstrip().startswith("#"))
    assert "api.cloudflare.com" not in code and "CF_API" not in code and "X-Auth" not in code
    assert not re.search(r"ufw (--force )?delete allow 22|ufw deny 22|ufw reset|ufw disable", code)
    assert "https://www.cloudflare.com/$1" in code or "https://www.cloudflare.com/ips-v4" in code

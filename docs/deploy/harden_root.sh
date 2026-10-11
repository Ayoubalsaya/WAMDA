#!/usr/bin/env bash
# تحصين سيرفر ومضة الجديد (DEPLOY_PLAN.md §٠) — يُشغَّل كـ root.
# ⚠ كل مرحلة أمر منفصل، وتُنفَّذ بهذا الترتيب (قرار المالك ٢٠٢٦-١٠-١١: التخمين قائم ≈١٤٥٠ محاولة/يوم):
#
#   ١) sshlock      إغلاق كلمة المرور — يتطلب --confirmed-second-session (جلسة ثانية بالمفتاح مفتوحة)
#   ٢) fail2ban     حمّام sshd في jail.d/ جديد (لا تعديل لملف موجود)
#   ٣) upgrade      apt full-upgrade. لا يعيد التشغيل أبداً؛ يطبع إن كان لازماً (reboot بموافقة المالك)
#   ٤) firewall     ufw: deny incoming · allow outgoing · allow SSH ثم 80 و443 ثم enable
#   ٥) autoupdate   تحديثات أمنية فقط، بلا إعادة تشغيل تلقائي
#   ٦) swap         ملف swap بحجم ٢GB كاحتياط لـChromium — ملفات جديدة فقط
#   ٧) report       عرض الحالة النهائية للتسجيل في PROGRESS.md (قراءة فقط)
#
# التشغيل من جهازك (السكربت يصل عبر stdin، لا نسخ ملف للسيرفر):
#   ssh root@HOST 'bash -s -- sshlock --confirmed-second-session' < docs/deploy/harden_root.sh
#   ssh root@HOST 'bash -s -- fail2ban'   < docs/deploy/harden_root.sh   # ADMIN_IP=x.x.x.x اختياري (يبقى فارغاً)
#   ssh root@HOST 'bash -s -- upgrade'    < docs/deploy/harden_root.sh
#   ssh root@HOST 'bash -s -- firewall'   < docs/deploy/harden_root.sh
#   ssh root@HOST 'bash -s -- autoupdate' < docs/deploy/harden_root.sh
#   ssh root@HOST 'bash -s -- swap'       < docs/deploy/harden_root.sh
#   ssh root@HOST 'bash -s -- report'     < docs/deploy/harden_root.sh
#
# الضمانات:
#   · لا reboot. لا restart لـsshd (reload فقط، بعد sshd -t، وتراجع تلقائي إن لم يظهر الأثر الفعلي).
#   · لا يُعدَّل أي ملف موجود: ملفات جديدة فقط (00-wamda-hardening.conf · wamda-sshd.conf · 52wamda-unattended).
#   · sshlock يرفض العمل إن لم يجد مفتاحاً صالحاً في /root/.ssh/authorized_keys.
#   · السجل الكامل يُحفظ أيضاً في /var/log/wamda-harden.log على السيرفر.

set -euo pipefail

SSHD_DROPIN=/etc/ssh/sshd_config.d/00-wamda-hardening.conf
F2B_JAIL=/etc/fail2ban/jail.d/wamda-sshd.conf
UU_CONF=/etc/apt/apt.conf.d/52wamda-unattended
LOG=/var/log/wamda-harden.log

say() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\nخطأ: %s\n' "$*" >&2; exit 1; }

apt_get() {
  apt-get -y -o DPkg::Lock::Timeout=300 \
    -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef "$@"
}

# منفذ/منافذ sshd الفعلية (من الإعداد الفعّال لا من الافتراض)
ssh_ports() { sshd -T | awk '$1=="port"{print $2}' | sort -un; }

require_root_key() {
  local f=/root/.ssh/authorized_keys
  [ -s "$f" ] || die "$f غير موجود أو فارغ — لن أُغلق كلمة المرور"
  ssh-keygen -l -f "$f" >/dev/null 2>&1 || die "$f لا يحوي مفتاحاً صالحاً"
}

phase_upgrade() {
  say "apt update"
  apt_get update
  say "apt full-upgrade (بلا reboot)"
  apt_get full-upgrade
  say "النتيجة"
  echo "النواة العاملة: $(uname -r)"
  if [ -f /var/run/reboot-required ]; then
    echo "⚠ إعادة التشغيل لازمة. أبلغ المالك ثم نفّذها بنفسك، وبعدها تأكد أن:"
    echo "    ssh -o BatchMode=yes root@HOST 'echo ok'   يعمل — قبل أي مرحلة تالية."
    cat /var/run/reboot-required.pkgs 2>/dev/null || true
  else
    echo "لا حاجة لإعادة تشغيل."
  fi
}

phase_firewall() {
  command -v ufw >/dev/null 2>&1 || apt_get install ufw
  local ports p cur
  ports="$(ssh_ports)"
  [ -n "$ports" ] || die "تعذّر تحديد منفذ sshd"
  # الجلسة الحالية يجب أن تكون على منفذ سيُسمح به (يمنع قطع نفسك)
  cur="$(awk '{print $4}' <<<"${SSH_CONNECTION:-}")"
  if [ -n "$cur" ] && ! grep -qxF "$cur" <<<"$ports"; then
    die "جلستك على المنفذ $cur وهو ليس بين منافذ sshd المعلنة ($ports) — توقّفت"
  fi
  if ! grep -qE '^IPV6=yes' /etc/default/ufw; then
    say "IPV6 غير مفعّل في ufw — يُفعَّل (sshd يستمع على [::] أيضاً)"
    sed -i 's/^IPV6=.*/IPV6=yes/' /etc/default/ufw
  fi
  say "ufw: القواعد (قبل enable)"
  ufw default deny incoming
  ufw default allow outgoing
  for p in $ports; do ufw allow "$p/tcp"; done      # SSH أولاً
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable                                # بعد القواعد لا قبلها
  ufw status verbose
}

phase_fail2ban() {
  apt_get install fail2ban
  local ignore="127.0.0.1/8 ::1"
  if [ -n "${ADMIN_IP:-}" ]; then
    [[ "$ADMIN_IP" =~ ^[0-9A-Fa-f:./]+$ ]] || die "ADMIN_IP غير صالح"
    ignore="$ignore $ADMIN_IP"
  fi
  say "كتابة $F2B_JAIL"
  cat > "$F2B_JAIL" <<EOF
[sshd]
enabled  = true
backend  = systemd
port     = $(ssh_ports | paste -sd, -)
maxretry = 5
findtime = 10m
bantime  = 1h
ignoreip = $ignore
EOF
  systemctl enable fail2ban
  systemctl restart fail2ban
  sleep 3
  fail2ban-client status sshd || die "حمّام sshd لم يعمل — راجع: journalctl -u fail2ban"
}

phase_autoupdate() {
  apt_get install unattended-upgrades
  say "كتابة $UU_CONF (الأمنية فقط، بلا إعادة تشغيل تلقائي)"
  cat > "$UU_CONF" <<'EOF'
// ومضة: تحديثات أمنية فقط، بلا إعادة تشغيل تلقائي. يُقرأ بعد 20auto-upgrades و50unattended-upgrades فيغلب.
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
#clear Unattended-Upgrade::Allowed-Origins;
Unattended-Upgrade::Allowed-Origins {
        "${distro_id}:${distro_codename}-security";
        "${distro_id}ESMApps:${distro_codename}-apps-security";
        "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
EOF
  systemctl enable --now apt-daily.timer apt-daily-upgrade.timer
  say "الإعداد الفعّال"
  apt-config dump | grep -E 'Unattended-Upgrade::(Allowed-Origins|Automatic-Reboot|Remove-Unused)' || true
  apt-config dump | grep -E 'Periodic::(Update-Package-Lists|Unattended-Upgrade)' || true
  say "تجربة جافة"
  unattended-upgrade --dry-run 2>&1 | tail -5 || true
}

phase_sshlock() {
  [ "${1:-}" = "--confirmed-second-session" ] || die "هذه المرحلة تتطلب --confirmed-second-session:
  افتح جلسة ثانية بالمفتاح (ssh -o BatchMode=yes root@HOST 'echo ok') وتأكد أنها تعمل، واترك الأولى مفتوحة، ثم أعد التشغيل بهذا الخيار."
  require_root_key
  grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config \
    || die "sshd_config لا يضم sshd_config.d/*.conf — الملف الجديد لن يُقرأ"
  [ ! -e "$SSHD_DROPIN" ] || say "ملاحظة: $SSHD_DROPIN موجود وسيُستبدل بالمحتوى نفسه"

  say "كتابة $SSHD_DROPIN"
  cat > "$SSHD_DROPIN" <<'EOF'
# ومضة: دخول بالمفتاح فقط. يبدأ بـ00- ليسبق 50-cloud-init.conf (القيمة الأولى هي النافذة).
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF
  chmod 644 "$SSHD_DROPIN"

  rollback() { rm -f "$SSHD_DROPIN"; systemctl reload ssh || true; die "$1 — تراجعتُ (حُذف $SSHD_DROPIN وأُعيد reload)"; }

  sshd -t || rollback "sshd -t فشل"
  systemctl reload ssh || rollback "reload فشل"

  # الأثر الفعلي لـroot (يشمل أي Match) لا الملف وحده
  local eff
  eff="$(sshd -T -C user=root,host=localhost,addr=127.0.0.1)"
  for want in "passwordauthentication no" "kbdinteractiveauthentication no" \
              "permitrootlogin without-password" "pubkeyauthentication yes"; do
    grep -qix "$want" <<<"$eff" || grep -qix "${want/without-password/prohibit-password}" <<<"$eff" \
      || rollback "الإعداد الفعّال لا يطابق: $want"
  done
  say "تم. الإعداد الفعّال:"
  grep -iE '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication) ' <<<"$eff"
  cat <<'EOF'

الخطوات التالية — من جهازك، والجلسة الأولى تبقى مفتوحة:
  1) جلسة ثالثة بالمفتاح:  ssh -o BatchMode=yes root@HOST 'echo ok'
  2) كلمة المرور مرفوضة:   ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password root@HOST
     (يجب أن يفشل بـ Permission denied)
التراجع:  rm /etc/ssh/sshd_config.d/00-wamda-hardening.conf && systemctl reload ssh
احتياطي: وحدة تحكم VNC في لوحة Contabo.
EOF
}

phase_swap() {
  local f=/swapfile unit=/etc/systemd/system/swapfile.swap size_mb=2048 avail_mb
  if swapon --show=NAME --noheadings | grep -q .; then
    say "swap موجود أصلاً — لا شيء يُفعل"; swapon --show; return 0
  fi
  [ ! -e "$f" ] || die "$f موجود مسبقاً — لن أستبدله"
  [ ! -e "$unit" ] || die "$unit موجود مسبقاً — لن أستبدله"
  avail_mb="$(df -BM --output=avail / | tail -1 | tr -dc '0-9')"
  [ "$avail_mb" -gt $((size_mb * 5)) ] || die "المساحة الحرة غير كافية (${avail_mb}MB)"
  say "إنشاء $f (${size_mb}MB)"
  fallocate -l "${size_mb}M" "$f"
  chmod 600 "$f"
  mkswap "$f"
  # وحدة systemd جديدة بدل تعديل /etc/fstab (لا مساس بملف موجود)
  cat > "$unit" <<'EOF'
[Unit]
Description=Swap file (احتياط ذاكرة لـChromium — ومضة)

[Swap]
What=/swapfile

[Install]
WantedBy=swap.target
EOF
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-wamda-swap.conf
  systemctl daemon-reload
  systemctl enable --now swapfile.swap
  sysctl -p /etc/sysctl.d/99-wamda-swap.conf
  swapon --show
  free -h
}

phase_report() {
  say "uname"; uname -r
  say "ufw status verbose"; ufw status verbose || true
  say "fail2ban-client status sshd"; fail2ban-client status sshd || true
  say "sshd -T"; sshd -T | grep -iE 'passwordauth|permitroot|pubkey|kbdinteractive' || true
  say "تحديثات تلقائية"; apt-config dump | grep -E 'Unattended-Upgrade::(Allowed-Origins|Automatic-Reboot)|Periodic::Unattended-Upgrade' || true
  say "reboot-required"; ls -l /var/run/reboot-required 2>&1 || true
}

main() {
  exec </dev/null        # stdin هو السكربت نفسه: لا تدع apt/ufw تستهلكه
  # SIGHUP المتجاهَل يُورَّث للعمليات الفرعية (apt وtee) — لذا يسبق أي تشغيل لها.
  # وtee بـ warn-nopipe لا يموت إن انقطع الأنبوب فلا يصل SIGPIPE إلى apt.
  trap '' HUP
  [ "$(id -u)" -eq 0 ] || die "يجب التشغيل كـ root"
  local phase="${1:-}"
  [ "$#" -gt 0 ] && shift
  export LC_ALL=C DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
  exec > >(tee --output-error=warn-nopipe -a "$LOG") 2>&1
  say "harden_root.sh :: $phase"
  case "$phase" in
    upgrade)    phase_upgrade ;;
    firewall)   phase_firewall ;;
    fail2ban)   phase_fail2ban ;;
    autoupdate) phase_autoupdate ;;
    sshlock)    phase_sshlock "$@" ;;
    swap)       phase_swap ;;
    report)     phase_report ;;
    *) die "مرحلة غير معروفة: '$phase' (upgrade|firewall|fail2ban|autoupdate|sshlock|swap|report)" ;;
  esac
}

main "$@"   # آخر سطر عمداً: bash يقرأ الدالة كاملة قبل التنفيذ

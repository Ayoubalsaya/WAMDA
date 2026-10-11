#!/usr/bin/env bash
# فحص قراءة فقط (ملحق للفحص الأول): لماذا فشل cloud-init / networkd-wait-online، وحالة المستخدم ubuntu.
# لا يكتب ولا يعدّل شيئاً؛ كل المخرجات إلى stdout. التشغيل:
#   ssh root@HOST 'bash -s' < docs/deploy/inspect_boot_ubuntu.sh > docs/deploy/out/inspect_boot_ubuntu.txt
set -uo pipefail
export LC_ALL=C

sec() { printf '\n===== %s =====\n' "$1"; }
# يُخفي بصمات كلمات المرور ($6$...) وأي قيمة بعد password/token/secret/key
mask() { sed -E -e 's#\$[0-9a-z]+\$[^[:space:]"]+#$HASH$***#g' \
                 -e 's#((password|passwd|token|secret|key)[A-Za-z0-9_]*[[:space:]]*[=:][[:space:]]*)[^[:space:]]+#\1***#Ig'; }
run() { "$@" 2>&1 | mask; }

sec "cloud-init.service — الحالة والسجل"
run systemctl status cloud-init.service --no-pager -l
echo "--- journalctl (آخر ٥٠)"
run journalctl -u cloud-init.service --no-pager | tail -50
echo "--- cloud-init status --long"
run cloud-init status --long

sec "systemd-networkd-wait-online.service"
run systemctl status systemd-networkd-wait-online.service --no-pager -l
echo "--- journalctl (آخر ٥٠)"
run journalctl -u systemd-networkd-wait-online.service --no-pager | tail -50

sec "الشبكة الحالية وإعدادها المحفوظ (هل ينجو من إعادة التشغيل؟)"
run ip -br addr
run ip route
echo "--- networkctl"
run networkctl list --no-pager
run networkctl status --no-pager
echo "--- netplan (الملفات)"
ls -l /etc/netplan/ 2>&1
for f in /etc/netplan/*.yaml; do [ -r "$f" ] && { echo "# $f"; mask < "$f"; }; done
echo "--- systemd-networkd: مفعّلة عند الإقلاع؟"
run systemctl is-enabled systemd-networkd systemd-networkd.socket systemd-resolved
echo "--- ملفات networkd المولَّدة"
ls -l /run/systemd/network/ /etc/systemd/network/ 2>&1
echo "--- cloud-init: إعدادات الشبكة والـssh"
ls -l /etc/cloud/cloud.cfg.d/ 2>&1
ls -l /etc/cloud/cloud-init.disabled 2>&1

sec "sshd_config.d (للتحقق من ترتيب القراءة قبل التحصين)"
ls -l /etc/ssh/sshd_config.d/ 2>&1
for f in /etc/ssh/sshd_config.d/*.conf; do [ -r "$f" ] && { echo "# $f"; grep -vE '^\s*$' "$f"; }; done
echo "--- الإعداد الفعّال"
sshd -T 2>&1 | grep -iE '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication|port|authenticationmethods|allowusers|allowgroups) '

sec "المستخدم ubuntu"
run id ubuntu
echo "--- مجموعة sudo/admin"
getent group sudo admin 2>&1
echo "--- sudoers.d"
ls -l /etc/sudoers.d/ 2>&1
for f in /etc/sudoers.d/*; do [ -r "$f" ] && { echo "# $f"; grep -vE '^\s*#|^\s*$' "$f"; }; done
echo "--- حالة كلمة المرور وانتهاؤها (بلا البصمة)"
run passwd -S ubuntu
run chage -l ubuntu
echo "--- authorized_keys (عدد وبصمات فقط، لا المفاتيح نفسها)"
ls -l /home/ubuntu/.ssh/ 2>&1
if [ -r /home/ubuntu/.ssh/authorized_keys ]; then
  wc -l < /home/ubuntu/.ssh/authorized_keys
  ssh-keygen -l -f /home/ubuntu/.ssh/authorized_keys 2>&1
else
  echo "(لا authorized_keys مقروء)"
fi
echo "--- عمليات تعمل باسمه"
ps -u ubuntu -o pid,etime,cmd 2>&1
echo "--- جلساتهم الحالية"
who 2>&1; loginctl list-sessions --no-pager 2>&1
echo "--- آخر دخول"
run lastlog -u ubuntu
run last -n 15 ubuntu
echo "--- محاولات دخول فاشلة حديثة (أعداد حسب المستخدم، بلا عناوين)"
journalctl -u ssh --no-pager --since "-24h" 2>/dev/null | grep -E 'Failed password|Invalid user' | sed -E 's/.*(Failed password for (invalid user )?|Invalid user )([^ ]+).*/\3/' | sort | uniq -c | sort -rn | head -10
echo "--- ملف ubuntu الشخصي"
ls -la /home/ubuntu 2>&1 | head -20

sec "انتهى — لم يُكتب أي شيء على السيرفر"

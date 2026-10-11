#!/usr/bin/env bash
# قراءة فقط: قسم bootcmd وحده من بيانات cloud-init (سبب فشل cloud-init.service).
# كل سطر فيه passwd أو password أو chpasswd أو بصمة $N$ يُحجَب بالكامل (***). لا يكتب شيئاً.
#   ssh root@HOST 'bash -s' < docs/deploy/inspect_bootcmd.sh > docs/deploy/out/inspect_bootcmd.txt
set -uo pipefail
export LC_ALL=C

mask() { sed -E '/passwd|password|chpasswd|\$[0-9a-z]+\$/I s/.*/  *** (سطر محجوب)/'; }

found=0
for f in /var/lib/cloud/instance/cloud-config.txt /var/lib/cloud/instance/user-data.txt \
         /var/lib/cloud/instance/vendor-cloud-config.txt /var/lib/cloud/seed/nocloud/user-data; do
  [ -r "$f" ] || continue
  found=1
  echo "===== $f (قسم bootcmd فقط) ====="
  # من سطر ^bootcmd: حتى أول مفتاح علوي آخر (سطر لا يبدأ بمسافة أو - أو #)
  awk '/^bootcmd:/ {b=1; print; next}
       b && /^[^[:space:]#-]/ {b=0}
       b {print}' "$f" | mask
done
[ "$found" -eq 1 ] || echo "(لا ملف user-data مقروء)"

echo "===== /etc/cloud/cloud.cfg.d/99-ssh.cfg ====="
mask < /etc/cloud/cloud.cfg.d/99-ssh.cfg 2>&1
echo "===== انتهى — لم يُكتب أي شيء على السيرفر ====="

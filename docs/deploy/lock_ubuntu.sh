#!/usr/bin/env bash
# قفل مستخدم ubuntu (قرار المالك ٢٠٢٦-١٠-١١): nologin + انتهاء الحساب + إزالته من sudo،
# وحذف sudoers.d/90-cloud-init-users إن كان لـubuntu وحده (بعد visudo -c، مع نسخة احتياطية في /root).
# لا يحذف المستخدم نفسه (cloud-init قد يعيد إنشاءه).
#   ssh root@HOST 'bash -s' < docs/deploy/lock_ubuntu.sh
set -euo pipefail
export LC_ALL=C
F=/etc/sudoers.d/90-cloud-init-users

echo "--- قبل"
id ubuntu
echo "--- محتوى $F"
cat "$F"

others="$(grep -vE '^[[:space:]]*(#|$)' "$F" | grep -vE '^ubuntu[[:space:]]' || true)"
if [ -n "$others" ]; then
  echo "الملف يحوي ما يخص غير ubuntu — توقفت دون تغيير:"; echo "$others"; exit 2
fi
visudo -c

usermod -s /usr/sbin/nologin ubuntu
usermod -e 1 ubuntu
if id -nG ubuntu | tr ' ' '\n' | grep -qx sudo; then gpasswd -d ubuntu sudo; fi

cp -a "$F" /root/90-cloud-init-users.bak
rm -f "$F"
if ! visudo -c; then
  cp -a /root/90-cloud-init-users.bak "$F"; echo "visudo فشل بعد الحذف — استُعيد الملف"; exit 3
fi

echo "--- بعد"
getent passwd ubuntu
chage -l ubuntu | head -2
id ubuntu
ls -l /etc/sudoers.d/

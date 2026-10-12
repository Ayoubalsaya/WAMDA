# خطة المرحلة ١٥ — النشر على سيرفر ومضة المستقل (تخطيط فقط)

> **الحالة (٢٠٢٦-١٠-٠٧): قرار جديد من المالك — اشترى سيرفراً مستقلاً لومضة (Contabo، Ubuntu 24.04). لن يُنشَر على سيرفر السهم إطلاقاً.**
> **السيرفر الجديد (وصل ٢٠٢٦-١٠-١١): `144.91.81.150`** — Ubuntu 24.04.5، قرص 192GB. أضاف المالك مفتاح جهازه لـ`root` بنفسه. لم يُنفَّذ عليه شيء بعد سوى الفحص (قراءة فقط).
> **سيرفر السهم (194.34.232.37) محظور تقنياً:** قاعدة `deny` في `.claude/settings.json` تمنع أي أمر Bash/PowerShell يحوي عنوانه (ssh/scp/rsync/sftp/curl/أي أداة)، حتى لو وافق المالك خطأً.
> وكل اتصال بالسيرفر الجديد يحتاج موافقة المالك الصريحة (قاعدة `ask` على `ssh`/`scp`/`rsync`/`sftp`).
> مصدر البنود: قسم «المراحل القادمة» في `PROGRESS.md` + ما أُحيل صراحةً للمرحلة ١٥ في
> `README.md` (الجدولة، nginx، `--no-server-header`) و`RUNBOOK.md` (بعد الإقفال، `.env` الإنتاج).
>
> **أُلغي بالقرار الجديد:** قيود المشاركة مع السهم (حدود الذاكرة المشتركة، اختبار العزل عن السهم، «لقطة صحة السهم» وسكربتها `sahem_health_snapshot.sh` — حُذف). **باقٍ كممارسة جيدة:** حدود systemd للخدمة.

## ٠. تحصين السيرفر الجديد (الخطوة الأولى — قبل تثبيت أي شيء)

> **الترتيب المعدَّل بقرار المالك (٢٠٢٦-١٠-١١):** الفحص أظهر ≈١٤٥٠ محاولة تخمين لـ`root` يومياً والدخول بكلمة المرور مفتوح، فصار **إغلاق كلمة المرور أول المراحل** (المفتاح مُختبَر فعلاً بـ`BatchMode`، وإعادة التشغيل لا تمسّ `authorized_keys`).
> `harden_root.sh` وُوفق عليه بعد المراجعة المستقلة. **كل مرحلة بموافقة صريحة على حدة**، والترتيب لا يُقدَّم فيه لاحق على سابق.

تُنفَّذ بسكربت واحد `docs/deploy/harden_root.sh` بمراحل:

١. **قبل أي تعديل (تم):** فحص قراءة فقط `inspect_readonly.sh` + `inspect_boot_ubuntu.sh` + التأكد أن دخول `root` **بالمفتاح** يعمل (`ssh -o BatchMode=yes … 'echo ok'`).
٢. **`sshlock` — إغلاق دخول `root` بكلمة المرور:** بعد **اختبار فعلي من جلسة ثانية** بالمفتاح (والجلسة الأولى تبقى مفتوحة طوال العملية، والسكربت يرفض بدون `--confirmed-second-session`):
   - ملف جديد `/etc/ssh/sshd_config.d/00-wamda-hardening.conf` بالمحتوى: `PasswordAuthentication no` · `KbdInteractiveAuthentication no` · `PermitRootLogin prohibit-password` (أي `root` بالمفتاح فقط) · `PubkeyAuthentication yes`.
     الاسم يبدأ بـ`00-` عمداً: في Ubuntu 24.04 تُقرأ ملفات `sshd_config.d/*.conf` بترتيب الاسم والقيمة **الأولى** هي النافذة؛ وقد وُجد فعلاً `50-cloud-init.conf` = `PasswordAuthentication yes` يسبق `60-cloudimg-settings.conf` = `no` — لا نعدّل ذلك الملف، نسبقه.
   - `sshd -t` (فحص الصياغة) قبل `systemctl reload ssh` (لا `restart`)، ثم يتحقق السكربت من الإعداد الفعّال لـ`root` (`sshd -T -C …`) ويتراجع تلقائياً إن لم يطابق، ثم **جلسة ثالثة بالمفتاح** و**اختبار أن كلمة المرور مرفوضة** (`ssh -o PubkeyAuthentication=no …` يجب أن يفشل).
   - شبكة أمان: لوحة Contabo (وحدة تحكم VNC) تبقى طريقة الدخول الاحتياطية إن حدث خطأ.
   - **التراجع:** حذف ملف `00-wamda-hardening.conf` ثم `reload ssh`.
٣. **`fail2ban`:** حمّام `sshd` (محاولات فاشلة ← حظر مؤقت)، بإعداد في `jail.d/` جديد لا بتعديل ملف موجود. `ADMIN_IP` يبقى فارغاً (اتصال المالك عبر وكيل متغيّر العنوان).
٤. **`upgrade` — تحديث النظام:** `apt update && apt full-upgrade` بلا إعادة تشغيل داخل السكربت؛ **إعادة التشغيل بموافقة المالك** (نواة جديدة)، ثم التأكد أن الدخول بالمفتاح ما زال يعمل. (فحص ما بعد الإقلاع: تأخير ≈دقيقتين متوقَّع من `networkd-wait-online`؛ الشبكة محفوظة في `/etc/netplan/50-cloud-init.yaml`.)
٥. **`firewall` — الجدار الناري (ufw):** `default deny incoming` · `default allow outgoing` · **`allow 22/tcp` أولاً** ثم `80/tcp` و`443/tcp` · **ثم** `ufw enable`. لا غير ذلك (PostgreSQL على localhost فقط، لا منفذ لـuvicorn).
٦. **`autoupdate`:** `unattended-upgrades` (الأمنية فقط، بلا إعادة تشغيل تلقائي، أو بإعادة تشغيل في نافذة يحدّدها المالك).
٧. **`swap`:** ملف ٢GB جديد (`/swapfile` + وحدة `swapfile.swap` + `vm.swappiness=10`) كاحتياط لـChromium، بلا لمس `fstab`.
٨. **`report`:** تسجيل الحالة النهائية (`ufw status verbose`، `fail2ban-client status sshd`، `sshd -T | grep -iE 'passwordauth|permitroot|pubkey'`) في `PROGRESS.md`.

**مستخدم `ubuntu` (من صورة المزوّد):** يُقفَل (`nologin` + انتهاء الحساب + إزالته من `sudo`) ويُحذف `sudoers.d/90-cloud-init-users` إن كان له وحده — لا حذف للمستخدم نفسه (cloud-init قد يعيد إنشاءه).

## ١. المستخدم والصلاحيات (بلا عزل عن نظام آخر — السيرفر مخصَّص لومضة)
| العنصر | الاسم |
|---|---|
| مستخدم لينكس | `wamda` (home = `/srv/wamda`، كلمة مروره مقفلة، **دخول SSH بمفتاح جهاز المالك نفسه** — مُنسَخ من `/root/.ssh/authorized_keys`، بلا sudo عام) — **الخدمة لا تعمل بـ`root` أبداً**. العمل اليومي بـ`wamda`؛ و`root` لسكربتات التأسيس المراجَعة فقط |
| قاعدة بيانات + أدوار | `wamda_db` / `wamda_app` (`NOSUPERUSER NOCREATEDB NOCREATEROLE` — بلا أي صلاحية إضافية) · `wamda_restore` (`CREATEDB` فقط، لـ`restore-test` وحده عبر `BACKUP_ADMIN_DATABASE_URL`؛ لا يتصل بـ`wamda_db`؛ كلمة مروره في `secrets/restore_password` بـ0600). PostgreSQL **18** من PGDG (مطابق للتطوير)، `localhost` فقط. القاعدة: ترتيب **ICU عربي** (`ar`) و`timezone=UTC` على مستوى القاعدة — تاريخ العمل من `work_timezone` في التطبيق وحده |
| خدمة systemd | `wamda.service` (+ مؤقّتات `wamda-*.timer`) |
| نطاق فرعي + nginx vhost | ملف `wamda.conf`، شهادة Let's Encrypt |
| منفذ uvicorn | `127.0.0.1:<منفذ>` (يُحدَّد بعد الفحص؛ لا يُفتح في الجدار الناري) |
| مجلد النسخ | `/srv/wamda/backups` (ملكية `wamda` فقط، 0700) |
| صلاحيات مجلدات ومضة | **750** (`wamda:wamda`) |
| حدود الموارد (ممارسة جيدة) | `MemoryMax` و`CPUQuota` في وحدة systemd، **تشمل Chromium** (عملية ابنة داخل الخدمة)؛ القيم تُحدَّد بعد فحص السيرفر (لم تعد مقيَّدة بالمشاركة) |
| sudoers | يسمح لـ`wamda` فقط بـ`systemctl start/stop/restart wamda` و`systemctl --no-pager status wamda` (بلا `--no-pager` يفتح عارض صفحات ومنه سطر أوامر root) — لا sudo عام. السجلات: عضوية `systemd-journal` بدل أي sudo لـ`journalctl` |
| الوصول للكود | deploy key **للقراءة فقط** على GitHub الخاص (لا مفتاح شخصي على السيرفر) |

**اختبارات بعد كل مرحلة (تُسجَّل في PROGRESS.md):** (أ) `wamda` ليس في مجموعة `sudo` ولا يستطيع `sudo` غير أوامر `systemctl … wamda` المسموحة · (ب) ملف `.env` بصلاحية 0600 ومالكه `wamda` ولا يقرؤه غيره ·
(ج) `wamda_app` لا يستطيع إنشاء أدوار ولا قواعد (ولا يتصل بقواعد أخرى) · (د) PostgreSQL يستمع على `127.0.0.1` فقط (`ss -tlnp`) · (هـ) المنفذان الوحيدان المفتوحان للخارج 22 و80/443 (`ufw status`).

## ٢. بنية التركيب
1. حزم النظام: Python (3.12 كما التطوير؛ Ubuntu 24.04 يأتي به)، PostgreSQL، nginx، `certbot`.
2. **Chromium لمحرك المستندات**: `app/documents/render.py` يشغّل Playwright/Chromium داخل عملية
   الخادم؛ على لينكس يلزم `playwright install --with-deps chromium` (اعتماديات نظام) — **بند خطر**،
   يُختبر بتوليد PDF وPNG فعلياً بعد التركيب.
3. الكود: `/srv/wamda/app` (git clone بمفتاح deploy، بالمستخدم `wamda`) + `/srv/wamda/venv` + `pip install -r requirements.txt`
   (مكتبات التشغيل فقط **بإصدارات مثبَّتة بدقة `==`**؛ أدوات الاختبار في `requirements-dev.txt` ولا تُثبَّت على السيرفر — فُصلا ٢٠٢٦-١٠-١١).
4. الواجهة: **قرار: تُبنى محلياً (`npm run build`) وتُشحن `app/static/app`** — لا Node ولا npm على السيرفر.
5. `.env` الإنتاج (0600): `APP_ENV=production`، `TRUST_PROXY_HEADERS=true`،
   `LOGIN_RATE_LIMIT_MAX<=8`، `PORTAL_LOGIN_RATE_LIMIT_MAX<=8`، `LOGIN_RATE_LIMIT_WINDOW_SECONDS>=300` (٨ محاولات/٥ دقائق، قرار ٢٠٢٦-١٠-١٢)
   (وإلا يرفض الإقلاع)، `BACKUP_OFFSITE_DIR`، `BACKUP_ENCRYPTION_KEY`، **`TOTP_ENCRYPTION_KEY` (إلزامي في الإنتاج — يرفض الإقلاع بدونه)**، `DATABASE_URL` (`wamda_app`)، **`BACKUP_ADMIN_DATABASE_URL` (`wamda_restore`، قاعدة `postgres`)** — وهو ما يستخدمه `restore-test` لإنشاء القاعدة المؤقتة؛ و`restore --target-db` اليدوي إلى `wamda_db` يتطلب تفريغه من بيئة الأمر (فيعود إلى `DATABASE_URL`)،
   ومهلتا الخمول (`STAFF_IDLE_TIMEOUT_MINUTES=30`، `PORTAL_IDLE_TIMEOUT_MINUTES=15` افتراضياً).
   المفتاحان `BACKUP_ENCRYPTION_KEY` و`TOTP_ENCRYPTION_KEY` **يحفظهما المالك بنفسه — لا في git ولا مع النسخ السحابية**.
6. قاعدة البيانات: إنشاء الدور والقاعدة → `alembic upgrade head` (قاعدة جديدة فلا أسرار قديمة لتشفيرها) → `seed` → `create-admin`
   (ثم المدير الاحتياطي عبر `POST /users`) → خطوات RUNBOOK ١–٨ للبيانات الحقيقية. (`seed.py` فُحص ٢٠٢٦-١٠-٠٧: مرجعيات فقط، بلا مستخدمين ولا كلمات مرور ثابتة.)

## ٣. وحدة الخدمة `wamda.service`
`ExecStart=/srv/wamda/venv/bin/uvicorn app.main:app --no-server-header --proxy-headers --forwarded-allow-ips=127.0.0.1 --host 127.0.0.1 --port <P>`
— **بلا `--reload` وبعامل واحد** (عدّاد معدل الدخول في الذاكرة). `User=wamda`، `EnvironmentFile`،
`Restart=on-failure`، تقوية (`NoNewPrivileges`، `ProtectSystem=strict`، `ReadWritePaths` للنسخ فقط،
`PrivateTmp`)، `MemoryMax`/`CPUQuota`. Chromium داخل الخدمة قد يتعارض مع `ProtectSystem`/`MemoryDenyWriteExecute` — يُجرَّب.

## ٤. المهام المجدولة (systemd timers، `Persistent=true`)
| الوحدة | الأمر | الموعد المقترَح |
|---|---|---|
| `wamda-backup` | `python -m app.cli backup` | يومياً 02:00 |
| `wamda-integrity` | `python -m app.cli daily-integrity-check` | يومياً 02:30 |
| `wamda-backup-fresh` | `python -m app.cli check-backup-freshness` | يومياً 03:00 (بعد `backup` ومهلة مزامنة) |
| `wamda-restore-test` | `python -m app.cli restore-test <أحدث نسخة>` | أسبوعياً، الجمعة 04:00 |

(المواعيد تُثبَّت بعد الفحص ومنطقة السيرفر الزمنية؛ لم تعد مقيَّدة بجدول السهم.)

**النسخ الاحتياطي (محدَّث ٢٠٢٦-١٠-٠٦):** `backup` صار يُرجع exit≠0 عند فشل الرفع الخارجي أو عند غياب الوجهة في الإنتاج، ويتحقق من وصول النسخة (الحجم + SHA-256) ويحذف النسخة الفاسدة
(التزام `c6baa8c`) — فالمؤقّت الفاشل يظهر فعلاً في `OnFailure=` (§٦)، ولا حاجة لمراقبة خارجية لتغطية هذه الفجوة.
**قرار المالك (باقٍ):** النسخ خارج السيرفر يعمل ويُختبَر **باستعادة حقيقية** (`restore-test` على النسخة التي وصلت للوجهة الخارجية) **قبل أي رصيد حقيقي** — شرط بوابة لا يُتجاوز.
التحقق اليدوي الشهري من وصول الملفات للسحابة يبقى إلزامياً (README). خيارات الوجهة (rclone) وكلفتها في `PROGRESS.md` («خيارات النسخ السحابي»).

## ٥. nginx + TLS
`server_tokens off;` · `proxy_pass http://127.0.0.1:<P>` · `proxy_set_header X-Real-IP $remote_addr;`
`X-Forwarded-For $proxy_add_x_forwarded_for;` · `Host`/`X-Forwarded-Proto` · إعادة توجيه 80→443 ·
شهادة Let's Encrypt بتجديد تلقائي · `client_max_body_size` معتدل · `proxy_read_timeout` ≥ 60ث
(مهلة توليد PDF في التطبيق 60ث) · لا تخزين مؤقت (التطبيق يرسل `no-store`). HSTS يرسله التطبيق.
خطوة nginx/HTTPS بسكربت `root` منفصل يُراجَع مستقلاً (تحتاج النطاق الفرعي — مؤجَّل).

## ٦. المراقبة والتشغيل
- فشل أي مؤقّت ⇒ `OnFailure=` يُنبّه — **قرار المالك: بريد إلكتروني + لوحة التحكم** (عنوان البريد وخادم الإرسال يُحدَّدان لاحقاً).
- تدوير السجلات (journald حدّ حجم/مدة).
- جدار ناري: 22/80/443 فقط (§٠)، PostgreSQL على localhost فقط.
- إجراء النشر/التحديث: نسخة احتياطية ← سحب الكود ← `pip install` ← `alembic upgrade head` ← إعادة تشغيل الخدمة
  ← `curl http://127.0.0.1:8000/health` يُرجع `commit` يساوي `git rev-parse --short HEAD` (قاعدة PROGRESS «تأكَّد أن الخادم يخدم
  الكود الحالي»؛ `/openapi.json` معطَّل في الإنتاج) ← فحص سلامة.
- خطة تراجع: نسخة ما قبل التحديث + الوسم السابق في git.

## ٧. ترتيب التنفيذ (بعد وصول السيرفر الجديد)
١ فحص قراءة فقط (`inspect_readonly.sh`) → **٢ تحصين (§٠: sshlock ← fail2ban ← تحديث (+reboot بموافقة) ← ufw ← تحديثات تلقائية ← swap ← report)** → ٣ مستخدم `wamda` + قاعدة/دور (`bootstrap_root.sh`) →
٤ كود + venv + Chromium + اختبار PDF → ٥ `.env` + ترحيل + seed → ٦ systemd + nginx + TLS →
٧ اختبارات §١ → ٨ المؤقّتات + تشغيل يدوي لكلٍّ منها + **استعادة حقيقية من الوجهة الخارجية** → ٩ بيانات RUNBOOK (بعد نجاح ٨ فقط) →
١٠ تسجيل كل شيء في PROGRESS.md.

## ٨. قرارات المالك

**محسومة (٢٠٢٦-١٠-٠٧) — تُلغي ما يخالفها من قرارات ٢٠٢٦-١٠-٠٦:**
١) **سيرفر مستقل لومضة** (Contabo، Ubuntu 24.04). **لا نشر على سيرفر السهم إطلاقاً**، وعنوانه محظور بقاعدة `deny` تقنية.
٢) **تبقى:** الخدمة بمستخدم `wamda` غير root · نسخ احتياطي خارج السيرفر يُختبَر **باستعادة حقيقية قبل أول رصيد** · deploy key **للقراءة فقط** من GitHub.
٣) **التحصين أولاً (§٠) — بالترتيب المعدَّل ٢٠٢٦-١٠-١١:** إغلاق دخول root بكلمة المرور **بعد** اختبار المفتاح من جلسة ثانية ← fail2ban ← تحديث النظام (+reboot بموافقة) ← ufw (22/80/443) ← تحديثات أمنية تلقائية ← swap.
٤) **`inspect_readonly.sh` يبقى كما هو** للسيرفر الجديد (مع إخفاء أسرار cron قبل أول تشغيل — طلب ٢٠٢٦-١٠-٠٦).

**محسومة سابقاً (٢٠٢٦-١٠-٠٦) وما زالت سارية:**
- Claude ينفّذ أوامر السيرفر **بموافقة المالك على كل اتصال** (`ask` على `ssh`/`scp`/`rsync`/`sftp`، تعمل حتى في الوضع التلقائي). `root` لسكربتات التأسيس/التحصين/nginx فقط، **كل سكربت يُعرض كاملاً ويُراجَع مستقلاً قبل تشغيله**؛ بعدها العمل اليومي بـ`wamda` عبر مفتاح جهاز المالك نفسه (قرار ٢٠٢٦-١٠-١١).
- **الواجهة** تُبنى محلياً وتُشحن `app/static/app`. **المفتاحان** `BACKUP_ENCRYPTION_KEY` و`TOTP_ENCRYPTION_KEY` يحفظهما المالك بنفسه، لا في git ولا مع النسخ السحابية. **التنبيه:** بريد + لوحة التحكم.
- حدود systemd (`MemoryMax`/`CPUQuota`) تشمل Chromium — كممارسة جيدة.

**مؤجَّلة (يحدّدها المالك لاحقاً):** **عنوان السيرفر الجديد** (يُعطى عند الوصول) · النطاق الفرعي والبريد (عنوان/خادم الإرسال) · أداة وحساب النسخ السحابي (خيارات rclone في `PROGRESS.md`).
**تُحدَّد بعد فحص السيرفر (قراءة فقط):** المنفذ الداخلي · مواعيد المؤقّتات · قيم `MemoryMax`/`CPUQuota`.

**قواعد التنفيذ على السيرفر:** (أ) اتصال واحد في كل مرة بموافقة صريحة؛ (ب) أي سكربت يُعرض كاملاً ويُراجَع قبل تشغيله؛ (ج) خطوة تحصين الدخول (§٠-٢) لا تُنفَّذ قبل اختبار الدخول بالمفتاح من جلسة ثانية؛
(د) اختبارات §١ بعد كل مرحلة وتُسجَّل نتائجها؛ (هـ) ملفات الفحص الناتجة تُكتب على جهاز المالك (`docs/deploy/out/`، خارج git) لا على السيرفر.

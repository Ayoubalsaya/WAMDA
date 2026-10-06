# خطة المرحلة ١٥ — النشر على سيرفر AL SAHEM (تخطيط فقط)

> **الحالة: مسودة بانتظار قرارات المالك. لم يُنفَّذ شيء ولا اتصال بأي سيرفر.**
> مصدر البنود: قسم «المراحل القادمة» في `PROGRESS.md` + ما أُحيل صراحةً للمرحلة ١٥ في
> `README.md` (الجدولة، nginx، `--no-server-header`) و`RUNBOOK.md` (بعد الإقفال، `.env` الإنتاج).

## ١. عزل تام عن نظام السهم
| العنصر | الاسم المقترَح |
|---|---|
| مستخدم لينكس | `wamda` (بلا shell تسجيل دخول، home = `/srv/wamda`) |
| قاعدة بيانات + دور | `wamda_db` / `wamda_app` (دور لا يملك صلاحية على أي قاعدة أخرى) |
| خدمة systemd | `wamda.service` (+ مؤقّتات `wamda-*.timer`) |
| نطاق فرعي + nginx vhost | ملف `wamda.conf` منفصل، شهادته منفصلة |
| منفذ uvicorn | `127.0.0.1:<منفذ حر غير مستعمل من السهم>` (يُفحَص قبل الاختيار) |
| مجلد النسخ | `/srv/wamda/backups` (ملكية `wamda` فقط، 0700) |

**اختبار العزل الموثَّق** (يُنفَّذ بعد التركيب ويُسجَّل ناتجه في PROGRESS.md):
١) `wamda` لا يقرأ مجلدات السهم ولا العكس · ٢) `wamda_app` يفشل في `\c` إلى قاعدة السهم ·
٣) إيقاف `wamda.service` لا يمسّ خدمات السهم والعكس · ٤) تعديل nginx يمرّ بـ`nginx -t` ولا يغيّر
vhosts السهم (مقارنة checksum قبل/بعد) · ٥) لا ملف `.env` مقروء عبر المستخدمين (0600).

## ٢. بنية التركيب
1. حزم النظام: Python (نفس إصدار التطوير 3.12)، PostgreSQL client، nginx، `certbot`.
2. **Chromium لمحرك المستندات**: `app/documents/render.py` يشغّل Playwright/Chromium داخل عملية
   الخادم؛ على لينكس يلزم `playwright install --with-deps chromium` (اعتماديات نظام) — **بند خطر
   جديد غير مذكور سابقاً**، يُختبر بتوليد PDF وPNG فعلياً بعد التركيب.
3. الكود: `/srv/wamda/app` + `venv` مخصّص + `pip install -r requirements.txt`
   (يشمل أدوات الاختبار؛ نقترح فصل `requirements-dev.txt` لاحقاً).
4. الواجهة: `app/static/app` مبنية (`npm run build`) — **قرار: بناء محلي وشحن المخرجات أم npm على السيرفر**.
5. `.env` الإنتاج (0600): `APP_ENV=production`، `TRUST_PROXY_HEADERS=true`،
   `LOGIN_RATE_LIMIT_MAX<=5`، `PORTAL_LOGIN_RATE_LIMIT_MAX<=5`، `LOGIN_RATE_LIMIT_WINDOW_SECONDS>=900`
   (وإلا يرفض الإقلاع)، `BACKUP_OFFSITE_DIR`، `BACKUP_ENCRYPTION_KEY`، `DATABASE_URL`.
6. قاعدة البيانات: إنشاء الدور والقاعدة → `alembic upgrade head` → `seed` → `create-admin`
   (ثم المدير الاحتياطي عبر `POST /users`) → خطوات RUNBOOK ١–٨ للبيانات الحقيقية.

## ٣. وحدة الخدمة `wamda.service`
`ExecStart=/srv/wamda/venv/bin/uvicorn app.main:app --no-server-header --proxy-headers --forwarded-allow-ips=127.0.0.1 --host 127.0.0.1 --port <P>`
— **بلا `--reload` وبعامل واحد** (عدّاد معدل الدخول في الذاكرة). `User=wamda`، `EnvironmentFile`،
`Restart=on-failure`، تقوية (`NoNewPrivileges`، `ProtectSystem=strict`، `ReadWritePaths` للنسخ فقط،
`PrivateTmp`). Chromium داخل الخدمة قد يتعارض مع `ProtectSystem`/`MemoryDenyWriteExecute` — يُجرَّب.

## ٤. المهام المجدولة (systemd timers، `Persistent=true`)
| الوحدة | الأمر | الموعد المقترَح |
|---|---|---|
| `wamda-backup` | `python -m app.cli backup` | يومياً 02:00 |
| `wamda-integrity` | `python -m app.cli daily-integrity-check` | يومياً 02:30 |
| `wamda-backup-fresh` | `python -m app.cli check-backup-freshness` | يومياً 03:00 (بعد `backup` ومهلة مزامنة) |
| `wamda-restore-test` | `python -m app.cli restore-test <أحدث نسخة>` | أسبوعياً، الجمعة 04:00 |

فجوة معروفة: `backup` لا يُرجع exit≠0 عند غياب الوجهة (يطبع تحذيراً) ⇒ **قرار: تنبيه خارجي** (§٦).
التحقق اليدوي الشهري من وصول الملفات للسحابة يبقى إلزامياً (README).

## ٥. nginx + TLS
`server_tokens off;` · `proxy_pass http://127.0.0.1:<P>` · `proxy_set_header X-Real-IP $remote_addr;`
`X-Forwarded-For $proxy_add_x_forwarded_for;` · `Host`/`X-Forwarded-Proto` · إعادة توجيه 80→443 ·
شهادة Let's Encrypt بتجديد تلقائي · `client_max_body_size` معتدل · `proxy_read_timeout` ≥ 60ث
(مهلة توليد PDF في التطبيق 60ث) · لا تخزين مؤقت (التطبيق يرسل `no-store`). HSTS يرسله التطبيق.

## ٦. المراقبة والتشغيل
- فشل أي مؤقّت ⇒ `OnFailure=` يُنبّه (قناة تنبيه — قرار).
- تدوير السجلات (journald حدّ حجم/مدة).
- جدار ناري: 80/443 فقط، PostgreSQL على localhost فقط.
- إجراء النشر/التحديث: نسخة احتياطية ← سحب الكود ← `pip install` ← `alembic upgrade head` ← إعادة تشغيل الخدمة
  ← `curl /openapi.json` يحتوي آخر مسار (قاعدة PROGRESS «تأكَّد أن الخادم يخدم الكود الحالي») ← فحص سلامة.
- خطة تراجع: نسخة ما قبل التحديث + الوسم السابق في git.

## ٧. ترتيب التنفيذ (بعد اعتماد القرارات)
١ تحضير بلا مساس (فحص السيرفر قراءةً فقط: توزيعة، منافذ، PG، nginx، المساحة) → ٢ مستخدم/قاعدة →
٣ كود + venv + Chromium + اختبار PDF → ٤ `.env` + ترحيل + seed → ٥ systemd + nginx + TLS →
٦ اختبار العزل (§١) → ٧ المؤقّتات + تشغيل يدوي لكلٍّ منها + استعادة تجريبية → ٨ بيانات RUNBOOK →
٩ تسجيل كل شيء في PROGRESS.md.

## ٨. القرارات المطلوبة من المالك
١) **طريقة الوصول للسيرفر** (SSH بمفتاح؟ من أي جهاز؟ أنا لن أتصل بدون إذنك الصريح ونطاقه).
٢) **النطاق الفرعي** (الاسم + من يتحكّم بـDNS؟).
٣) **أداة المزامنة السحابية** على السيرفر (Drive/OneDrive/غيره) ومسار `BACKUP_OFFSITE_DIR` — من يُثبّتها ويُوثّقها؟
٤) **حفظ `BACKUP_ENCRYPTION_KEY`**: نسخة مادية خارج السيرفر (فقدانه = نسخ غير قابلة للاستعادة).
٥) **قناة التنبيه** عند فشل المهام (بريد؟ واتساب؟ لا شيء ويُكتفى بلوحة التحكم؟).
٦) **بناء الواجهة**: محلياً وشحن `app/static/app` (مقترَح) أم على السيرفر.
٧) **مواعيد المؤقّتات** (§٤) مناسبة لتوقيت العمل/السيرفر؟ وتوزيعة لينكس وإصدار PostgreSQL فيه.
٨) **المنفذ الداخلي** وأسماء العزل (§١) — أقبلها كما هي أم تعدّلها؟
٩) هل يُسمح لي بفحص السيرفر قراءةً فقط (منافذ/خدمات/مساحة) قبل التركيب؟

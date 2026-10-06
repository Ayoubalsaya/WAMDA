# تقرير الوكيل ١ — الواجهات وترابطها الفعلي بالقاعدة

**التاريخ:** ٢٠٢٦-١٠-٠٦ · **النطاق:** `frontend/src` (الشاشات، المكوّنات، البوابة) ← `app/routers` ← `app/engine` ← الجداول ← `audit_log`.
**المنهج:** (أ) فحص ثابت بسكربتات في `docs/audit/01_scripts/` (تشتغل من جذر المشروع، ومخرجاتها في `out/`). (ب) فحص حي على **`wamda_test` حصراً**: خادم uvicorn مؤقت على منفذ حر + مستخدم `qa_aud_*` + عملاء/شريك `QA-*` عبر API الحقيقي، ثم متصفح Playwright (Edge) يقرأ ما تعرضه الشاشات ويقارنه بالقاعدة. (ج) تنظيف محصور بالسابقة وتحقق بالعدّ.
**التصنيف:** كل نتيجة موسومة **[تحققتُ منه]** (قرأتُ الكود أو شغّلتُه ورأيتُ المخرجات) أو **[استنتاج]** (تفسير لم أختبره). لم أعتمد على ادعاءات PROGRESS.md كدليل.

---

## ٠. معيار التقييم المئوي (مكتوب قبل النتائج)

المجموع ١٠٠ نقطة موزّعة على خمسة محاور. كل محور يُعطى كاملاً إذا لم يوجد أي بند من البنود المخصومة، ويُخصم بالأرقام أدناه فقط.

| المحور | الأعلى | ما يعطي الدرجة الكاملة | وحدة الخصم |
|---|---|---|---|
| أ. اكتمال الربط (واجهة ↔ مسارات) | ٢٠ | كل استدعاء واجهة له مسار موجود، وكل مسار إما يُستدعى من الواجهة أو له مبرر موثَّق بالدليل (صفحة/صحة/CLI) | −١ لكل قدرة خادمية بلا أي منفذ في الواجهة ولا دليل على أنها مقصودة |
| ب. سلامة الحقول | ١٥ | لا حقل يُرسَل ويُتجاهل بصمت، ولا حقل تعرضه الواجهة ولا يعيده الخادم، ولا حقل يُمحى بسبب دلالة الكتابة | −٣ لعيب فقد بيانات مُثبَت حياً؛ −١ لكل منطقة لم تُفحص ولا يوجد ما يغطيها |
| ج. التدقيق (`audit_log`) | ٢٠ | كل كتابة من الواجهة تترك سطر تدقيق (§٥ قاعدة ١١ كما يدّعيها `app/security/audit.py:2`) | −٠٫٧٥ لكل مسار كتابة **غير دفتري** بلا أي سطر تدقيق؛ −٠٫٢٥ لكل مسار ترحيل دفتري بلا سطر (مخفَّف لأن `journal_entries` نفسه يحمل `created_by/posted_by/created_at`) |
| د. مطابقة العرض للقاعدة | ٢٥ | كل رقم/إشارة/خانة/جانب (مدين/دائن) تعرضه الشاشة = القاعدة، وكل عنصر عرض يطابق ما تعرضه شاشة أخرى للمعطى نفسه | −٥ لتناقض بين رقمين على الشاشة نفسها؛ −٥ لرصيد حقيقي غائب عن شاشة تدّعي إظهاره؛ −٢ لتسمية خام غير مترجمة؛ −١ لعيب مفتاح/بنية |
| هـ. تغطية اختبارات المتصفح | ٢٠ | كل تدفّق/شاشة من ٢٠ تدفقاً مُعرَّفاً أدناه له اختبار متصفح وظيفي | ١ لكل تدفق بلا اختبار، ٠٫٥ إن كان الاختبار تخطيطياً (layout) فقط |

## ١. الدرجات

| المحور | الدرجة | الخصم (التفصيل في الأقسام) |
|---|---|---|
| أ. الربط | **١١ / ٢٠** | ٩ قدرات يتيمة (§٢): `PATCH /users`، `POST /portal/change-password`، `POST /portal/recover/*`، كشف حساب (حساب) PDF/Excel، زر PDF/Excel لتقرير `monthly-profit` و`debtors`، `balance-card.pdf`، `reports/{key}.png`، `exchange/from-lot` |
| ب. الحقول | **١٠ / ١٥** | −٣ محو الشعار (§٣-١)؛ −١ أجسام `...spread` لم تُتحقَّق ثابتاً؛ −١ سبعة أنواع TS بلا عيّنة حيّة (قوائم فارغة) |
| ج. التدقيق | **٥٫٥ / ٢٠** | ١٥ مسار كتابة غير دفتري بلا سطر (−١١٫٢٥)، و١٣ مسار ترحيل بلا سطر (−٣٫٢٥) (§٤) |
| د. مطابقة العرض | **١٢ / ٢٥** | −٥ رصيد الكشف المعروض ≠ الرصيد الفعلي؛ −٥ رصيد دولار الخزينة (١١٠٤) غائب عن مركز السيولة؛ −٢ `operation_type` خام؛ −١ مفتاح مكرر (§٥) |
| هـ. اختبارات المتصفح | **٩٫٥ / ٢٠** | §٧ |
| **الإجمالي** | **٤٨ / ١٠٠** | |

> هذه الدرجة تقيس **ترابط الواجهة بالقاعدة** بالمعيار أعلاه فقط، وليست حكماً على جودة المحرك المحاسبي: كل ما قارنتُه مباشرة بين `journal_lines` والشاشات (١٤ قيداً: الجانب والمبلغ وخانات العملة) كان مطابقاً.

---

## ٢. المسارات: واجهة ↔ خادم (بند ١ من الطلب)

**الأدلة:** `out/map_static.txt` (سكربت `map_static.py`)، `out/route_callers.json`.

- مواقع استدعاء `api.*` في الواجهة: **١٣٥**، مطابَقة بـ**١٣٥ مساراً** من `app.routes` (التطبيق الفعلي لا قراءة نصية للموجّهات). **استدعاءات لمسار غير موجود: ٠** — الحالة الوحيدة التي ظهرت `GET /clients${q ? …}` إيجابي كاذب (قالب شرطي، `ClientsListView.tsx:27`). **[تحققتُ منه]**
- ما فاتَ السكربت الآلي وتحققتُ منه يدوياً (قوالب ذات متغيّر): `POST /operations/{id}/edit` يُستدعى من `OperationForm.tsx:693`؛ `GET /documents/statement/client/*.pdf|xlsx` من `ClientDetailView.tsx:188,194`؛ `POST /portal/invite/verify` من `PortalAcceptInviteScreen.tsx:30-31`؛ `GET /portal/statement` و`/portal/balance-card.png` من `PortalHomeScreen.tsx:71,169`. **[تحققتُ منه]**

### مسارات بلا مستدعٍ من الواجهة

| المسار | الحكم | الدليل |
|---|---|---|
| `GET /` · `GET /health` · `GET /portal` | **مقصود** (صفحات/فحص حياة) | `app/main.py` (`health()` يرجع `{"status":"ok"}`) |
| `PATCH /users/{id}` (تعطيل مستخدم/تغيير دور) | **يتيم** — لا شاشة تعطيل أو تغيير دور؛ الواجهة تستعمل `GET/POST /users` فقط (`SettingsScreen.tsx:96,129`) | `grep '/users' frontend/src` → سطران فقط |
| `POST /portal/change-password` · `POST /portal/recover/start` · `POST /portal/recover/complete` | **يتيمة** — لا شيء في `frontend/src/portal/` يستدعيها؛ مستخدم البوابة بلا تغيير كلمة مرور ولا استعادة من الواجهة | `grep -rniE "recover|change-password|نسيت" frontend/src/portal` → لا نتيجة |
| `GET /documents/statement/account/{code}.pdf|xlsx` | **يتيمة** — لا زر كشف حساب لحساب شركة | `grep "statement/account" frontend/src` → لا نتيجة؛ ويؤكده فشل اختبار الفرع غير المدموج (§٨) |
| `GET /documents/reports/monthly-profit.pdf|xlsx` · `…/debtors.pdf` | **لا زر** رغم وجود المولِّد — `PDF_EXPORT_KEYS` يخلو منهما و`EXCEL_EXPORT_KEYS` يخلو من `monthly-profit` | `ReportsScreen.tsx:422-436`؛ المولِّدات `documents.py:37,42,49` |
| `GET /documents/balance-card/{id}.pdf` · `GET /documents/reports/{key}.png` | **يتيمة** (لا دليل على قصدٍ) | `grep` بلا نتيجة |
| `POST /operations/exchange/from-lot` | **يتيمة** — الواجهة تبني الصرافة بـ`/operations/exchange` و`exchange-chain` فقط | `grep "from-lot" frontend/src` → لا نتيجة. **[استنتاج]:** مسار قديم سبق الصرافة بالسلسلة |

---

## ٣. الحقول (بند ٢ من الطلب)

**الأدلة:** `out/fields_static.txt`، `out/fields_ops.txt`، `out/types_vs_models.txt`، والجزء الحي في `out/live_api.json → state.types_live`.

### ٣-١. ما يُرسَل ويتجاهله الخادم أو يمحوه
- **نماذج الجسم:** ١٤ نموذجاً (`extra="forbid"`: ١٣ عملية + `exchange-chain`، كلها `StrictModel`) ترفض أي حقل زائد بـ٤٢٢؛ **كل الباقي (٣٦ نموذجاً) `extra=ignore`** — أي مفتاح مكتوب خطأً في الواجهة يُتجاهل بصمت. **[تحققتُ منه]** (`fields_static.py` قسم أ).
- **مفاتيح الأجسام الحرفية في ٣١ موقع استدعاء + ١٢ بانياً لجسم عملية في `OperationForm`:** لا مفتاح مجهول عند الخادم ولا حقل مطلوب مفقود. **[تحققتُ منه]** (أجسام `...spread` في `local-move` و`exchange` لم تُفحص ثابتاً — يغطيها رفض الخادم `forbid`، وهو لم يُرفض في تشغيلاتي الحية لأني أرسلتُها يدوياً لا عبر الواجهة).
- **⚠ عيب فقد بيانات مُثبَت حياً — شعار الشركة يُمحى:** `PUT /settings/company` يستبدل القيمة كاملة (`app/routers/settings.py:59-62`: `row.value = payload.model_dump()`)، والواجهة ترسل `{ name_ar }` فقط (`SettingsScreen.tsx:52`). في الفحص الحي: بعد `PUT` بشعار ثم `PUT` كما تفعل الواجهة، أعاد `GET` الشعار فارغاً (`state.logo_survives_ui_put = false`). الشعار يُستهلك في المستندات (`app/documents/common.py:23`) ولا يوجد في الواجهة أي حقل لرفعه (`grep logo_data_url frontend/src` خارج `types.ts` → لا شيء)؛ فالمحو يطال أي شعار أُدخل خارج الواجهة. **[تحققتُ منه]**

### ٣-٢. ما تعرضه الواجهة ولا يعيده الخادم
- ٤٩ نقطة GET تستهلكها الواجهة، قارنتُ مفاتيح الاستجابة **الحيّة** (العنصر الأول) بحقول واجهة TypeScript المعلنة: **٠ حقل مفقود، ٠ حقل زائد** في كل ما أعاد عيّنة. ٧ أنواع أعادت قائمة فارغة فلم تُفحص (`CommentOut, DebtorRow, EmergencyEntryRow, LossMakingEntryRow, LotRow, PendingSwiftMovement, SimilarClient`) وطلب واحد رُفض بـ٤٢٢ لخطأ في معاملي (`ProfitByPeriodRow`). **[تحققتُ منه جزئياً]** — التغطية ٤١ من ٤٩.
- **حقل يُعاد ولا تعرضه الواجهة:** `StatementResponse.closing_balance` معرَّف في `types.ts:232` ولا يُستعمل في أي شاشة — وهو سبب عيب §٥-١. **[تحققتُ منه]** (`grep closing_balance frontend/src` → `types.ts` وحده).
- تنبيه منهجي: الفحص الثابت المبدئي (`types_vs_models.py`) أظهر تعارضاً في `AccountOut` بسبب **نموذجين خادميين بالاسم نفسه**؛ الفحص الحي حسم أنه لا تعارض فعلي. **[تحققتُ منه]**

---

## ٤. التدقيق: أين تُكتب البيانات بلا أثر (بند ٣ من الطلب)

**فُحص حياً**: لكل كتابة نفّذتُها عبر API، عددتُ صفوف كل جدول وصفوف `audit_log` قبل/بعد (`step()` في `live_api.py`). النتائج في `out/live_api.json` و`out/action_map.md`؛ الجدول الكامل لـ٥٨ مسار كتابة (٤٥ استدعاءً نُفِّذ حياً) في `out/action_map.md`. القيد: عدّ الصفوف يرصد الإدراج/الحذف فقط، فـ`UPDATE` الصرف يظهر «—» في عمود الجداول (لكن عمود التدقيق دقيق دائماً). **[تحققتُ منه]**

### كتابات بلا أي سطر تدقيق (حياً)
| الفئة | المسارات | سطر تدقيق |
|---|---|---|
| إعدادات (٧) | `PUT /settings/company` · `POST/PATCH /settings/currencies` (إنشاء عملة **يُنشئ ١٢ حساباً + ١٢ ترقيماً**) · `POST/PATCH /settings/locations` · `POST /settings/client-currency-locations` · `POST /settings/bank-accounts` | **لا** |
| شركاء (٢) | `POST /partners` · `POST /partners/{id}/accounts` | **لا** |
| عملاء (١) | `PATCH /clients/{id}` (الاسم والهاتف) | **لا** (بينما `POST /clients` يُسجَّل `CLIENT_CREATED`) |
| مطابقة (٥) | `POST /reconciliation/statements` · `auto-match` · `…/resolve` · `…/adjust` (ينشئ قيد ADJUSTMENT) · `…/match` (لم يُنفَّذ حياً — لا استدعاء `audit` في المعالج `reconciliation.py:200`) | **لا** |
| ترحيل دفتري (١٣) | `receipt` · `payment` · `exchange` · `exchange-chain` · `expense` · `local-move` · `remit-out` · `adjustment` · `cash-transfer` · `opening` · `swift-in` · `swift-out` (سطر `NEGATIVE_BALANCE_OVERRIDE` عند التجاوز فقط) · `swift-return` (ثابت) | **لا** — الأثر في `journal_entries.created_by/posted_by` (`app/models/journal.py:72`)؛ المصدر الوحيد لسطور التدقيق في المحرك هو `posting._log_override` (`posting.py:221-235`) و`engine/periods.py` |

### كتابات لها سطر تدقيق (حياً)
`POST /users` (`USER_CREATED`) · `PATCH /users` (`USER_UPDATED`) · `POST /clients` · `PUT credit-mode/credit-limits` · كل إجراءات بوابة العميل الخمسة · `comments` · `cancel` · `edit` (`ENTRY_EDITED`) · `periods/close|reopen` · `auth/backup-codes/regenerate`.

**لم يُنفَّذ حياً (ثابت فقط):** `POST /periods/founding/close` (لا رجعة فيه؛ المعالج يستدعي `audit.log_write`، `periods.py:146`)، و`auth/login|logout|change-password|recover/*` و`portal/*` (خدمات المصادقة تستدعي `audit.log_write` في `auth_service.py`/`portal_auth_service.py` — **[استنتاج]** من الكود لا من التنفيذ).

---

## ٥. مطابقة العرض للقاعدة (بند ٤ من الطلب)

**العيّنة الحية:** مستخدم `qa_aud_*` وعميلان وشريك بسابقة `QA-*`، و١٥ قيداً مُرحَّلاً عبر API (قبض ×٢، صرف، صرافة عميل، صرافة خزينة، مصروف، نقل داخلي بعمولة، إرسال خارجي، تسوية، تحويل بعمولة، سويفت خروج/وصول، رصيد افتتاحي، سلسلة صرافة LYD→USD→CNY) + تعليق + تعديل + إلغاء. النتائج **كلها من تشغيل فعلي** (`out/live_api_run9.txt`، `out/live_api.json`).

### ما طابق تماماً **[تحققتُ منه]**
- **دفتر اليومية (متصفح):** ١٢ قيداً معروضاً، لكل سطر منها قارنتُ (اسم الحساب، الجانب `data-side`، المبلغ بخانات عملته، رمز العملة) بـ`journal_lines` → **١٢/١٢ مطابق** (`ui.journal_entries_verified_equal`).
- **أرصدة العميل:** الإجمالي المعروض لـLYD وUSD = `account_balances` بخانات العملة (١٣٤٠٫٠٠٠ / ٣٩٥٫٠٠).
- **الإشارة:** رصيد حساب العميل التزام موجب = مجموع (دائن − مدين)؛ رصيد الأصول مدين موجب (مثلاً `1104`: ٤٤٩٫٠٠٠٠٠٠ مقابل مجموع −٤٤٩ بالمعيار نفسه). لا انعكاس.
- **الخانات العشرية:** الـAPI يعيد دائماً ٦ منازل خاماً (`'295.000000'`) والواجهة تقصّها بعدد منازل العملة (`formatAmount.ts`، `lineAmount.ts`) — المعروض في الشاشة مطابق (٣ للدينار، ٢ للدولار والرمبي). **ليس عيباً**، لكن أي مستهلك آخر للـAPI (تطبيق/تقرير) يجب أن ينسّق بنفسه.
- **توازن القيد لكل عملة** في ١٥ قيداً: صفر فرق. وكل صف كشف (مع `include_reversed=true`) = سطر القاعدة، والرصيد المتحرك = تراكم الأسطر، و`closing_balance` = `account_balances` (٢٢ فحصاً ناجحاً).
- **مركز السيولة:** ٦ صفوف (موقع×عملة) مطابقة للتجميع من القاعدة (أصول/التزامات) بخانات العملة.
- **الاختصارات:** `Alt+2/3/4` و`Ctrl+N` (فتح/إغلاق) و`/` (تركيز البحث) **كلها تعمل** فعلياً (`ui.shortcuts` كله `true`).

### ما لم يطابق **[تحققتُ منه]**
١. **كشف الحساب: الرصيد المتحرك الأخير المعروض ≠ الرصيد الفعلي (−٥).** بعد إلغاء قيد صرف ٢٠٠: الجدول يخفي القيد الملغى وقيد عكسه افتراضياً (`clients.py:305`)، لكن الرصيد المتحرك يحسبهما معاً (`:297-303`). فيقفز الرصيد من ١٠٠٠ إلى ١٢٩٠ مع سطر +٤٩٠ فقط، ويتوقف آخر صف ظاهر عند **١١٤٠٫٠٠٠** بينما الإجمالي في أعلى الصفحة نفسها **١٣٤٠٫٠٠٠** (فرق ٢٠٠ = المبلغ الملغى، لأن سطر العكس المتأخر مخفي). الدليل: `ui.statement_rows_shown.LYD` (٤ صفوف) و`ui.client_totals.LYD` و`compare.mismatches[0]`. `closing_balance` يعيده الخادم ولا تعرضه الواجهة (§٣-٢). **الحل المقترح:** عرض سطر «الرصيد الختامي» من `closing_balance`، أو إظهار الصفوف الملغاة مع تمييزها بدل إخفائها.
٢. **مركز السيولة يُسقط رصيداً حقيقياً (−٥):** الحساب `1104` («دولار · ليبيا · كاش») بلا موقع (`location_id` فارغ في `accounts`) فيُستبعد من تجميع (موقع × عملة) أصلاً. في العيّنة: رصيده **٤٤٩٫٠٠** دولاراً، بينما الشاشة تعرض «$ USD طرابلس — أصولي ٠٫٠٠». أي نقد دولار في هذا الصندوق غير ظاهر في أي صف سيولة. **[استنتاج جزئي]:** قد يكون قراراً مُرجَأً من المالك (يُذكر في PROGRESS) لكنه لا يُرى للمستخدم كاستثناء.
٣. **عمود «العملية» في كشف الحساب يعرض الرمز الخام (−٢):** `RECEIPT`، `EXCHANGE`، `REMIT_OUT`، `CASH_TRANSFER` (`ClientDetailView.tsx:220` يطبع `r.operation_type` مباشرة) بينما دفتر اليومية يترجمها (`OP_LABELS` في `OperationsList.tsx`). ظهرت في المتصفح: `ui.operation_type_cell_sample`.
٤. **مفتاح React مكرر (−١):** `key={r.entry_id}` (`ClientDetailView.tsx:217`) بينما قيد واحد قد ينتج صفين في الكشف (تحويل بعمولة `WMD-2026-004584`: صف ٥٫٠٠ وصف ١٠٠٫٠٠ في `ui.statement_rows_shown.USD`). **[تحققتُ منه]** من الكود ومن الـDOM؛ الأثر الفعلي (تحذير تطوير/إعادة رسم خاطئة) **[استنتاج]**.

### ملاحظات أخرى
- **أخطاء شبكة يرصدها المتصفح عند التحميل:** ٥ ردود ٤٠١ (`/auth/me` متوقع، و٤ طلبات `/reference/*` قبل الدخول) وردّان **٤٠٠** على `/reference/accounts/for-operation?…&currency_code=` (معامل فارغ) عند فتح نموذج العملية — `ui.http_errors_seen_by_browser`. السبب **[استنتاج]**: `AccountPicker.tsx:27` يطلب قبل اختيار العملة؛ لا أثر ظاهر على المستخدم.
- **قوائم دفتر اليومية:** أظهرت الشاشة ١٢ من ١٥ قيداً مُرحَّلاً؛ الثلاثة الباقية — **[استنتاج]** بقرينة `ui.posted_entries_not_in_day_list` — قيد الرصيد الافتتاحي (تاريخ ٢٠٢٦-٠١-٠١ خارج اليوم) وقيدا عكس (`reverses_entry_id` غير فارغ).
- **الإيصالات والـPDF/PNG** لم تُفحص قيمها (لا مولِّد بصري هنا)؛ فحصتُ وجود الأزرار فقط (§٢).

---

## ٦. خريطة الإجراءات (الزر ← api ← مسار ← محرك ← جداول ← تدقيق)

الجدول الكامل مولَّد آلياً: **`out/action_map.md`** (ومعه `action_map.json`). اقتباس لأهم الصفوف:

| الزر/الشاشة | استدعاء الواجهة | المسار (المعالج) | المحرك | الجداول المكتوبة (حياً) | التدقيق |
|---|---|---|---|---|---|
| «حفظ وترحيل» — قبض | `OperationForm.tsx:535` | `POST /operations/receipt` (`operations.py:152`) | `engine/operations/receipt.py` + `posting.py` | journal_entries+1، journal_lines+2، account_balances، accounts (إنشاء حساب العميل)، idempotency_keys | **لا** |
| «حفظ وترحيل» — تحويل بعمولة | `OperationForm.tsx:563` | `POST /operations/cash-transfer` (`:346`) | `cash_transfer.py` | journal_entries+1، journal_lines+8، account_balances+2 | **لا** |
| معالج الصرافة (خطوتان) | `ExchangeWizard.tsx:157` | `POST /operations/exchange-chain` (`:239`) | `chain.execute_two_step_chain` | journal_entries+2، journal_lines+10 | **لا** |
| «إلغاء» قيد | `EntryActions.tsx:27` | `POST /operations/{id}/cancel` (`entry_actions.py:354`) | `chain.reverse_chain` + `posting` | journal_entries+1، journal_lines+2 | `ENTRY_CANCELLED` |
| «تعديل» قيد | `OperationForm.tsx:693` | `POST /operations/{id}/edit` (`:387`) | `chain.py` | journal_entries+2، journal_lines+4 | `ENTRY_EDITED` |
| حفظ الاسم/الهاتف | `ClientDetailView.tsx:74` | `PATCH /clients/{id}` (`clients.py:171`) | — | (UPDATE) | **لا** |
| إنشاء عملة | `CurrenciesTab.tsx:20` | `POST /settings/currencies` (`settings.py:128`) | `accounts_repo.create_currency_chart_of_accounts` | currencies+1، accounts+12، account_number_assignments+12 | **لا** |
| حفظ اسم الشركة | `SettingsScreen.tsx:52` | `PUT /settings/company` (`:52`) | — | settings (UPDATE، يمحو الشعار) | **لا** |
| إنشاء مستخدم | `SettingsScreen.tsx:96` | `POST /users` (`users.py:30`) | `user_management.create_user` | users+1 | `USER_CREATED` |
| إنشاء كشف مراسل | `ReconciliationScreen.tsx:49` | `POST /reconciliation/statements` (`:92`) | — | partner_statements+1، partner_statement_lines+2 | **لا** |
| «تسوية فرق» سطر كشف | `ReconciliationScreen.tsx:136` | `POST …/lines/{id}/adjust` (`:241`) | `operations/adjustment.py` | journal_entries+1، journal_lines+2 | **لا** |
| إقفال فترة | `PeriodsTab.tsx:23` | `POST /periods/close` (`periods.py:46`) | `engine/periods.py` | periods+1 | `PERIOD_CLOSED` |

---

## ٧. الشاشات بلا اختبار متصفح (بند ٥ من الطلب)

**الدليل:** `grep` على `tests/test_ui_*.py` و`tests/ui_support.py` (١٥ ملفاً)، وبحث `keyboard.press|Alt+|Control+` في `tests/` كلها → **صفر نتيجة**.

| # | التدفق | الحالة | الدرجة |
|---|---|---|---|
| ١ | الدخول + 2FA | يمر عبر كل fixture (`ui_support.py`) | ١ |
| ٢ | رموز الاسترداد (إعداد/دخول) | `test_ui_backup_codes.py` | ١ |
| ٣ | دفتر اليومية: ١٢ نوع عملية وأخطاؤها وحقولها | ١٢ ملفاً | ١ |
| ٤ | تعديل/إلغاء/تعليق قيد | `test_ui_edit_prefill.py` للتعديل فقط؛ لا اختبار للإلغاء والتعليق **[استنتاج من الأسماء]** | ٠٫٥ |
| ٥ | قائمة العملاء/تفاصيل العميل/الكشف | `test_ui_credit.py` (ائتمان) لا الكشف | ٠٫٥ |
| ٦ | إنشاء عميل | `test_ui_quick_client.py` | ١ |
| ٧ | ضوابط الائتمان | `test_ui_credit.py` | ١ |
| ٨ | لوحة التحكم | `test_ui_layout_scale.py` (تخطيط فقط) | ٠٫٥ |
| ٩ | **مركز السيولة** | **لا شيء** | ٠ |
| ١٠ | الحسابات | تخطيط فقط | ٠٫٥ |
| ١١ | التقارير | تخطيط فقط (+ `test_ui_credit.py` يلمسها) | ٠٫٥ |
| ١٢ | المطابقة | رسالة خطأ واحدة (`test_ui_error_messages.py`) | ٠٫٥ |
| ١٣ | **إعدادات: المستخدمون** | **لا شيء** | ٠ |
| ١٤ | **إعدادات: الشركاء وحساباتهم** | **لا شيء** | ٠ |
| ١٥ | إعدادات: العملات/المواقع | رسائل خطأ فقط | ٠٫٥ |
| ١٦ | إعدادات: الفترات/الأرصدة الافتتاحية | رسالة خطأ للأرصدة؛ **الفترات لا شيء** | ٠٫٥ |
| ١٧ | إعدادات: سجل التدقيق | `test_ui_line_amounts.py` يزورها | ٠٫٥ |
| ١٨ | **استعادة/تغيير كلمة المرور (موظف)** | **لا شيء** (`LoginScreen` recover + `ChangePasswordScreen`) | ٠ |
| ١٩ | **بوابة العميل (٣ شاشات)** | **لا شيء** (لا `portal.html` في أي اختبار؛ يوجد `test_portal_api.py` لـAPI فقط) | ٠ |
| ٢٠ | **اختصارات لوحة المفاتيح** | **لا اختبار**، مع أنها تعمل (فحصتُها حياً، §٥) — القاعدة الثابتة المعلنة في PROGRESS تطلب ذلك صراحةً | ٠ |
| | **المجموع** | | **٩٫٥ / ٢٠** |

---

## ٨. الفرع غير المدموج `fix/document-buttons` (قراءة فقط، بلا checkout)

`git log main..fix/document-buttons` → **commit واحد** `829c5e7` (٢٠٢٦-٠٩-١٥): «كل مستند قابل للطباعة له زر حقيقي في الواجهة + مستند قائمة الدخل الجديد»؛ يمسّ `client.ts` (+٣٧)، `AccountsScreen`، `ReportsScreen`، `ClientDetailView`، `OperationsList` وملفي اختبار جديدين.

**شغّلتُ الاختبارين على `main` الحالي** (نسخة مؤقتة في `01_scripts/branch_tests/` بمسار واجهة مطلق، لا في `tests/`) — الناتج في `out/branch_tests_on_main.txt`:
- `test_frontend_routes_exist.py` → **ينجح (٢ اختبار)**: يوافق نتيجتي (٠ استدعاء لمسار غير موجود).
- `test_documents_have_buttons.py` → **يفشل بخمسة بنود**: كشف حساب (حساب) PDF وExcel بلا زر؛ `monthly-profit` بلا PDF ولا Excel؛ `debtors` بلا PDF. وهذه **بالضبط** فجوات §٢ التي وجدتُها مستقلاً.

**هل يسدّان فجوات نتائجي؟** جزئياً:
- يغطيان: «مستند بلا زر»، و«استدعاء مسار غير موجود». وقد يكون commit الإصلاح نفسه هو الذي يضيف الأزرار الناقصة (٤ أسطر في `ReportsScreen`) — **[استنتاج]**: لم أفحص diff الواجهة سطراً بسطر.
- لا يغطيان: الحقول المُرسَلة/المعادة، والتدقيق، ومطابقة العرض للقاعدة، والقدرات اليتيمة غير المستندات (`PATCH /users`، بوابة العميل)، ولا اختبار وظيفي للمتصفح.
- **توصية:** دمجه (أو إعادة تطبيقه) فالاختباران حارسان رخيصان، والثاني يفشل الآن على `main`.

---

## ٩. عمليات يتيمة ومخلّفات الفحص (تحقق نهاية الجلسة)

- **المتصفح والخادم:** كل متصفح Playwright وكل uvicorn أطلقتُه أُغلق في `finally`. أرقام عمليات الخادم المسجَّلة في `live_api.json → server_pids` (شجرة uvicorn كاملة): بعد الانتهاء `psutil.pid_exists` لكلٍّ منها → **لا حيّ**. `psutil.Process().children(recursive=True)` في آخر كل تشغيل → `[]` (`orphans check` في `out/live_api_run*.txt`). عدد عمليات `chrome-headless/msedge` في `tasklist` ثابت (٨) قبل التشغيلات وبعدها — سابقة لتشغيلاتي (متصفح المالك). الخادم على `127.0.0.1:8000` (PID ٤٤٦٨) لم ألمسه.
- **بيانات `wamda_test` بعد التنظيف:** `clients=0، users=0، journal_entries=0، journal_lines=0، accounts(client)=0`، لا `QAZ`/`QA-LOC`/حسابات `QA-ACC`، و`recompute-balances --verify` على `wamda_test` → «صفر اختلاف».
- **ما لا يمكن إزالته:** `audit_log` append-only بمشغّل (`trg_audit_log_append_only`) فصفوف التدقيق التي ولّدتُها باقية: **٥٩١ → ٧٤٠** (نحو ١٩ صفاً لكل تشغيل كامل). وصفوف `account_balances` لحسابات شركة أُنشئت كسولاً (قيمتها صفر): العدد الآن ٢٠.
- **مخلّفات سابقة نظّفتُها يدوياً:** حساب بنك `QA-ACC` (id 15532) وصفا عدّاد الترقيم (parent 9 و10) من تشغيل مبكر قبل إصلاح ترتيب التنظيف (`fix_leftover.py`، محصور بالمعرّف).

### ⚠ إفصاح عن زلّة
مرة واحدة شغّلتُ `python -m app.cli recompute-balances --verify` **بلا ضبط `DATABASE_URL`** فاتجه إلى قاعدة `.env` (`wamda_db`) بدل `wamda_test`. الأمر `--verify` فحص فقط بلا كتابة (حسب `--help`: «فحص فقط بلا كتابة») وخرج «صفر اختلاف»؛ لا أثر مُتوقَّع، لكنه خالف قاعدة «لا تلمس wamda_db». أعدتُ الفحص بعدها على `wamda_test` صراحةً (النتيجة نفسها).

---

## ١٠. حدود هذا التقرير

- الفحص الحي نُفِّذ بمستخدم ADMIN واحد؛ **صلاحيات المحاسب** لم تُمتحن (يغطيها الوكيل ٣).
- مقارنة الشاشات تمّت لدفتر اليومية وصفحة العميل ومركز السيولة فقط؛ **لوحة التحكم، الحسابات، التقارير، المطابقة** لم تُقارَن قيمها بالقاعدة (زُرتُها وسجّلتُ أنها تُحمَّل بلا خطأ: `ui.screens_visited_text_len`).
- ملفات PDF/Excel/PNG المولَّدة لم تُفتح.
- `swift-return` و`reconciliation …/match` و`founding/close` و`auth/change-password` ومسارات البوابة لم تُنفَّذ حياً.
- «قارنتُ ٤٩ استجابة» تعني مفاتيح المستوى الأول للعنصر الأول فقط، لا القيم المتداخلة.

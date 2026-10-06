# تدقيق ٠٤ — جودة الكود: لماذا ٦٨٪ وكيف نرفعها

> وكيل ٤ · فحص ثابت فقط (wc/grep/ast/git/oxlint للقراءة، و`pytest --collect-only` الذي لا يشغّل اختباراً).
> لم يُعدَّل أي ملف كود، ولا commit، ولا اتصال خارجي (لذلك لم أثبّت radon/ruff/mypy: يحتاج PyPI).
> التصنيف: **[ت]** تحققتُ منه بأمر/قراءة · **[س]** استنتاج. لم أعتمد على PROGRESS.md كدليل.

## ٠. معيار التقييم (يفسّر ٦٨٪)

الرقم ٦٨٪ جاء في طلبك؛ ما يلي معيار مكتوب أبنيه عليه كي يمكن مراجعته وتكراره. هو حكم مُوزَّن لا قياس آلي.
١٠٠٪ = كود يمرّ بـlinter + فحص أنواع + CI تلقائي، بلا تكرار منطق بين مسارات، بلا ملف/دالة تتجاوز عتبات الحجم،
ومنطق الأعمال خارج الموجّهات، واختبارات سريعة تغطي الواجهة والخلفية.

| المحور | الوزن | الدرجة | ما الذي أعطى الدرجة / ما خُصم (الدليل في §١–٧) |
|---|---|---|---|
| أ. بنية وتنظيم | 20 | **14** | المحرك `app/engine` نظيف ومقسّم لكل عملية (+). خُصم ٦: مكوّن واجهة من ١٤٥٣ سطراً بـ٥٠ `useState`؛ موجّهات بمنطق أعمال (dashboard/search/reports)؛ مجلدا `app/services/*` فارغان. |
| ب. تكرار واتّساق | 15 | **10** | خُصم ٥: ١٣ زوجاً متوازياً من دوال الإنشاء بين `operations.py` و`entry_actions.py` وقد انحرفا فعلاً (§٤)؛ ثلاث دوال مساعدة مكرَّرة الاسم؛ ٣٥٠ `style={{}}` مضمّنة؛ ٨١ نوعاً في `types.ts` مكتوبة يدوياً. |
| ج. أدوات جودة آلية | 20 | **8** | خُصم ١٢: لا ruff/mypy/flake8 (لا ملف إعداد ولا حزمة في venv)، لا CI (`.github` غير موجود)، oxlint بقاعدتين فقط وفيه ٤٦ تحذيراً، لا pre-commit. |
| د. الاختبارات | 25 | **22** | ٨٥٨ اختباراً، عزل بمعاملة، علامات قبول، اختبارات تزامن حقيقية (+). خُصم ٣: لا اختبار وحدة للواجهة؛ مجموعة بطيئة (~١٣ دقيقة)؛ فجوات محددة (§٣، §٤). |
| هـ. قابلية الصيانة | 10 | **8** | توثيق عربي غزير داخل الكود (+). خُصم ٢: صفر استعمال لـ`logging` في `app/` خارج `cli`؛ ٦ مواضع `except Exception`؛ بقايا فارغة. |
| و. تعقيد الدوال | 10 | **6** | خُصم ٤: ٢٢ دالة > ٦٠ سطراً، ٤ دوال > ١٠٠ سطر، ١٥ دالة بـ≥١٢ وسيطاً. |
| **المجموع** | **100** | **68** | |

## ١. أكبر ٢٠ ملفاً (أسطر، بلا اختبارات) **[ت]**
أمر: `find app frontend/src -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.css" \) ... | xargs wc -l | sort -rn`

| # | الملف | أسطر |
|---|---|---|
| 1 | frontend/src/screens/journal/OperationForm.tsx | 1453 |
| 2 | frontend/src/api/types.ts | 645 |
| 3 | app/routers/operations.py | 547 |
| 4 | app/routers/entry_actions.py | 542 |
| 5 | app/routers/dashboard.py | 535 |
| 6 | frontend/src/screens/ReportsScreen.tsx | 495 |
| 7 | app/engine/posting.py | 477 |
| 8 | app/routers/clients.py | 452 |
| 9 | frontend/src/screens/SettingsScreen.tsx | 417 |
| 10 | app/routers/reports.py | 415 |
| 11 | app/schemas/operations.py | 414 |
| 12 | frontend/src/screens/journal/ExchangeWizard.tsx | 411 |
| 13 | frontend/src/screens/ReconciliationScreen.tsx | 392 |
| 14 | app/cli/purge_demo_data.py | 363 |
| 15 | frontend/src/components/SegmentedTabs.tsx | 357 |
| 16 | app/routers/reference.py | 356 |
| 17 | app/engine/operations/exchange.py | 330 |
| 18 | frontend/src/screens/LoginScreen.tsx | 316 |
| 19 | frontend/src/screens/clients/ClientDetailView.tsx | 315 |
| 20 | frontend/src/screens/journal/journal-design.css | 309 |

الاختبارات الأكبر: test_operations_api.py (983)، test_entry_actions.py (440). ثمانية من أكبر ١٠ ملفات موجّهات/واجهة لا محرك: الثِّقل خارج الطبقة الأنظف.

## ٢. تعقيد المكوّنات (hooks) **[ت]** — `grep -o useState` لكل ملف

| الملف | أسطر | useState | useEffect | useMemo | useCallback |
|---|---|---|---|---|---|
| OperationForm.tsx | 1453 | **50** | 8 | 10 | 0 |
| ExchangeWizard.tsx | 411 | 29 | 0 | 6 | 0 |
| SettingsScreen.tsx | 417 | 28 | 6 | 0 | 0 |
| ReconciliationScreen.tsx | 392 | 23 | 4 | 0 | 0 |
| ReportsScreen.tsx | 495 | 16 | 14 | 0 | 0 |
| AccountsScreen.tsx | 244 | 9 | 6 | 0 | 0 |

٥٠ حالة منفصلة في مكوّن واحد = نموذج بلا `useReducer` ولا فصل لكل نوع عملية؛ أي تعديل (كحذف حقل الرسوم في هذه الجلسة) يلمس ملفاً من ١٤٥٣ سطراً. ReportsScreen فيها ١٤ `useEffect` لـ١٦ حالة: جلب بيانات يدوي في كل شاشة بلا طبقة موحّدة.

### oxlint **[ت]** (`frontend/node_modules/.bin/oxlint --format=json .`، الإعداد `frontend/.oxlintrc.json` بقاعدتين صريحتين فقط)
المجموع **٤٦ تحذيراً، صفر أخطاء**:
- `react(set-state-in-effect)`: **٣٣** (استدعاء setState داخل effect — نمط جلب البيانات اليدوي)
- `react-hooks(exhaustive-deps)`: ٧ (احتمال بيانات قديمة/حلقات)
- `react(only-export-components)`: ٥
- `react(refs)`: ١
أعلى الملفات: SettingsScreen (5)، FieldErrorPortals (3)، CommissionSection (3)، PortalHomeScreen (3)، OpeningBalancesTab (3).
لا قواعد `no-unused`/`a11y`/`correctness` مفعّلة صراحةً في الإعداد؛ مجموعة القواعد الافتراضية فقط **[ت]**.

## ٣. التغطية (تقدير ثابت، **[س]** — لم يُشغَّل `--cov`)

- ١٠٩ وحدة في `app/`، ٥٩ منها تُستورد مباشرة من اختبار **[ت]** (سكربت ast/regex). هذا مقياس **ضعيف**: الموجّهات تُختبر عبر HTTP لا بالاستيراد.
- مقياس أفضل: عدد ملفات الاختبار التي تضرب كل بادئة مسار **[ت]** (`grep -rl`): /clients 11 · /documents 10 · /portal 6 · /dashboard 5 · /settings 4 · /reference 4 · /periods 3 · /reports 3 · /partners 2 · /users 2 · /search 2 · **/reconciliation 1 · /audit 1**.
- وحدات محرك لا يستوردها أي اختبار مباشرة: `engine/account_filters` (190)، `engine/reconciliation` (114)، `engine/idempotency` (77)، `engine/numbering` (59)، `engine/periods` (50)، `engine/operations/local_move` (94)، `security/user_management` (155)، `security/client_portal_management` (152) **[ت]**. بعضها يُختبر بالمرور عبر API (**[س]**) لكن لا دليل على تغطية فروعها.
- المصالحة (٥ كتابات + شاشة ٣٩٢ سطراً + محرك ١١٤) لها ملف اختبار API واحد ولا اختبار متصفح **[ت]** (`ls tests/test_ui_*` لا يحوي reconciliation).
- لا اختبار مباشر يُمرّر `entry_date`/`backdate_reason` عبر مسار التعديل: `grep -n "entry_date\|backdate" tests/test_entry_actions.py tests/test_edit_prefill_api.py` ← لا نتائج **[ت]**.
- أمر التغطية الجاهز للمالك (لم أشغّله): `venv\Scripts\python.exe -m pip install pytest-cov` ثم
  `venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing:skip-covered -q`
  (ثقيل: ~١٣ دقيقة+؛ يُنصح بتشغيله وحده بلا وكلاء آخرين).

## ٤. التكرار بين `operations.py` و`entry_actions.py` **[ت]**

البنية: `operations.py` فيه ١٣ مسار `create_*` (أسطر 152–531)، و`entry_actions.py` فيه ١٣ دالة `_create_*` (أسطر 99–279) تستدعي **نفس** `*_op.execute(...)` بنفس الوسائط تقريباً، ثم `edit_entry` (387) يرسل إليها عبر `_CREATE_DISPATCH`. `entry_actions` يستورد `_entry_response, _get_client, _remember, _run` من `operations` (سطر 56): اقتران ثنائي الاتجاه.

مقارنة زوج (`local_move`): `operations.py:375-397` مقابل `entry_actions.py:159-171` — الأول يمرّر `entry_date=payload.entry_date, backdate_reason=payload.backdate_reason`، الثاني **لا**. الأمر نفسه في `swift_in` (`operations.py:443-461` يمرّرهما، `entry_actions.py:197-207` لا). `grep -n "entry_date\|backdate" app/routers/entry_actions.py` لا يُظهر أي تمرير في دوال `_create_*` **[ت]**.
**الأثر المحتمل (استنتاج [س] — لم أشغّل):** `edit_entry` يبني الطلب الجديد من `payload.operation` لكن `_create_*` يتجاهل `entry_date` فيأخذ القيد البديل تاريخ اليوم (`posting.py:52` `entry_date = entry_date or _today`) ويصبح `is_backdated=False`؛ أي تعديل قيد بأثر رجعي يعيد تأريخه صامتاً لليوم. يستحق اختباراً قبل أي حكم.
**فارق صلاحيات كامن [ت]:** مسار الإنشاء يستدعي `_require_override_permission` عند `allow_negative` (operations.py:180,354,383,407,430,491)؛ مسار التعديل لا يستدعيه (لا ظهور له في entry_actions). حالياً لا خطر لأن `EDIT_POSTED_ENTRY` و`OVERRIDE_CREDIT_OR_BALANCE` كلاهما ADMIN فقط (`permissions.py:55,58`) — لكن لو أُضيف دور ثالث يملك التعديل دون التجاوز، يصبح تجاوزاً للحدّ. عملياً: الحارس مكرَّر يدوياً ومنسيّ في أحد المسارين.

الدوال المساعدة المكرَّرة الاسم عبر الموجّهات **[ت]** (`sort | uniq -d`): `_account_out`, `_client_ip`, `_ensure_csrf_cookie`.

## ٥. منطق الأعمال داخل الموجّهات **[ت]**

لا طبقة خدمة: `app/services/{excel,pdf,png}` **فارغة** (`find app/services -type f` ← لا ملفات). حالات واضحة:

| الدالة | أسطر | تعقيد تقريبي | ما تفعله بدل أن تستدعي محرّكاً |
|---|---|---|---|
| `dashboard._compute_alerts` (dashboard.py:209) | 134 | 38 | تجمع أرصدة وحدود ائتمان وفروق مطابقة وتبني تنبيهات |
| `dashboard.dashboard_summary` (:92) | 88 | 23 | عمولات/أرباح اليوم، تجميع حسب عملة |
| `search.search` (search.py:29) | 98 | 27 | استعلامات وترتيب نتائج متعددة الكيانات |
| `operations.create_exchange_chain` (:240) | 104 | 10 | يشتق مبلغ الخطوة ٢ من أسطر الخطوة ١ (استعلام `JournalLine` داخل الموجّه، سطور ~290-312) ويفرّع خزينة/عميل |
| `reference.list_pending_swift_movements` (:215) | 43 | 20 | حساب حالات |
| `reports.py` (415 سطراً، ٤٣ مرجعاً لـ`select/func/join/sum/Decimal`) | — | — | تجميع مالي في الموجّه |

مقارنة: `portal.py` فيه مرجعان فقط (نظيف). النمط ينعكس: الكتابة منظَّمة في المحرك، القراءة/التقارير في الموجّهات — وهي بالضبط الأرقام التي تُعرض للمالك وتُصدَّر لـExcel/PDF.

## ٦. غياب الأدوات والـCI، ومدة المجموعة

**[ت]** `ls -a` : لا `.github`, `.gitlab-ci*`, `pyproject.toml`, `ruff.toml`, `mypy.ini`, `setup.cfg`, `tox.ini`, `.pre-commit-config.yaml`, `.editorconfig`, `.gitattributes`. `pip list | grep -iE "ruff|mypy|flake8|pylint|black|radon|coverage|pytest-cov"` ← لا شيء. Python: لا linter ولا types check. `git config core.autocrlf=true` + غياب `.gitattributes` ⇒ تحذيرات LF→CRLF متكررة في كل commit على ويندوز (مرئية في هذه الجلسة).
**[ت]** `except Exception` في `app/`: ٦ مواضع. `import logging` خارج `cli`: **٠ ملفات** ⇒ لا سجل تطبيقي لأخطاء الخادم/العمليات (يبقى سجل uvicorn فقط).
**[ت]** `grep -rho "style={{" frontend/src`: ٣٥٠ نمط مضمَّن. `frontend/src/api/types.ts`: ٨١ `interface/type` مكتوبة يدوياً بلا توليد من openapi (احتمال انجراف الحقول — يتقاطع مع وكيل ١).
**[ت]** دالة: `ast` على ٥٢٤ دالة: ٢٢ > ٦٠ سطراً، ٤ > ١٠٠ (`exchange.execute_via_rates` 163 سطراً/٢٧ وسيطاً، `_compute_alerts` 134، `create_exchange_chain` 104، `cash_transfer.execute` 103)؛ ١٥ دالة بـ≥١٢ وسيطاً. التعقيد التقريبي (عدّ فروع ast) الأعلى: `_compute_alerts` 38، `_message` 27، `search` 27.

### مدة المجموعة الكاملة (٧٧٨ث و٧٥٣ث لـ٨٥٨ اختباراً — قياسان من الجلسة)
تفصيل **[س]** مبنيّ على أدلة ثابتة وعلى تشغيلات جزئية في هذه الجلسة:
- عدد اختبارات المتصفح: **١٢٧** من ٨٥٨ (`pytest --collect-only | grep -c test_ui_`) في ١٥ وحدة، كلٌّ منها يشغّل `live_server` + `journal_page`/متصفح بنطاق `module` (ui_support.py:80,105,166 ⇒ ١٥ إقلاع uvicorn وتسجيل دخول TOTP).
- معدلات من تشغيلات جزئية هذه الجلسة: ١٩ اختبار واجهة (ملفان) ≈ ٦٠ث (~٣٫٢ث/اختبار)؛ ١١ اختباراً (documents_receipt + backup_codes) ≈ ٢٢ث؛ ٥٤ اختبار API ≈ ٣٢ث (~٠٫٦ث/اختبار).
- التقدير: ١٢٧×~٣٫٢ ≈ ٤٠٠ث + ٧٣١×~٠٫٦ ≈ ٤٤٠ث ≈ ٨٤٠ث — يطابق ٧٥٠–٧٨٠ بهامش معقول ⇒ **اختبارات المتصفح ≈ ٤٥–٥٥٪ من الزمن** وهي ١٥٪ من العدد.
- انتظارات ثابتة: ٤٥ موضع `wait_for_timeout/sleep` في `tests/` مجموع قيمها المكتوبة ≈ ٢٣٫٥ث للمرور الواحد (تتضاعف داخل الاختبارات المعلمة: `layout_scale` 18 حالة × ٩٠٠ms مثلاً)؛ `test_ui_error_messages.py` وحده ١٢ موضعاً. اختبارات التزامن ٤ فقط لكن بـ٢٠–٥٠ خيطاً (`test_concurrency.py:200,244,281`).
- غير ملحوظ بالقياس: أثر `alembic`/`pg_dump`/`restore` (٦ ملفات) — يحتاج `--durations=25` (أمر جاهز: `venv\Scripts\python.exe -m pytest --durations=25 -q`).

## ٧. فروع git **[ت]** (`git rev-list --count main..<branch>`)
`main` = ١١٧ commit. من ١٨ فرعاً محلياً: **١٧ مدموجة بالكامل (ahead=0)** — `stage-1…stage-14c` و`account-filtering-and-tech-debt` — ويمكن حذفها بلا فقد. **فرع واحد غير مدموج:**
`fix/document-buttons` — commit واحد `829c5e7` (2026-09-15) "كل مستند قابل للطباعة له زر حقيقي + مستند قائمة الدخل"، ١٠ ملفات (+٦٢٥/-١٣) تتضمن **`tests/test_frontend_routes_exist.py` (187 سطراً) و`tests/test_documents_have_buttons.py`** — اختباران يتحققان من وجود مسارات الواجهة والأزرار؛ ليسا في `main`. (ملاحظة لوكيل ١: قد يكونان أصلاً مطلوبين لتدقيق الأزرار/المسارات.) لم أفحص إن كان قد أُعيد تطبيق محتواه يدوياً في main؛ التحقق: `git diff main...fix/document-buttons`.

## ٨. خطة الرفع (الأثر وفق معيار §٠)

| # | الاقتراح | جهد | خطر | رفع النسبة | قبل التشغيل الموازي؟ ولماذا |
|---|---|---|---|---|---|
| ١ | اختبار يثبّت علّة `entry_date` عند التعديل + اختبار تكافؤ (parity) يتحقق أن كل `_create_*` يمرّر نفس وسائط مساره ومرشّح الصلاحية؛ ثم إصلاح الانحراف إن ثبت | ٣–٥ ساعات | منخفض (اختبار) / متوسط (الإصلاح مالي) | +٢ (ب) | **قبل** — العلّة تمس قيوداً حقيقية وتظهر عند أول تعديل بأثر رجعي أثناء التوازي |
| ٢ | إضافة ruff + mypy (تدريجياً، `--ignore-missing-imports`، على `app/engine` و`security` أولاً) + توسيع oxlint (`correctness`, `no-unused-vars`) | ٦–٨ ساعات | منخفض (لا تغيير سلوك) | +٥ (ج) | **قبل** — صفر أثر على السلوك ويمنع تراجعات أثناء التوازي |
| ٣ | CI بسيط (GitHub Actions أو سكربت محلي `make check`): `pytest -m "not ui"` + oxlint + ruff؛ شغّل UI ليلياً | ٣–٤ ساعات | منخفض | +٣ (ج) | **قبل** (يحمي من حادثة «التزام باختبار مكسور») |
| ٤ | `logging` منظَّم: ٥xx، ترحيل القيود، فشل الدخول، وتدوير | ٣ ساعات | منخفض | +١ (هـ) | **قبل** — بلا سجل تطبيق لا تشخيص أثناء التشغيل الحقيقي |
| ٥ | فصل علامة `ui` (`pytest -m "not ui"` ≈ ٧ دقائق) + `--durations` + تقليل `wait_for_timeout` بانتظار شروط | ٤–٦ ساعات | منخفض | +١ (د) | قبل (جزء العلامة) / بعد (إعادة كتابة الانتظارات) |
| ٦ | حذف الفروع الـ١٧ المدموجة، ودمج/إسقاط `fix/document-buttons` بعد فحص `git diff`، وحذف `app/services/*` الفارغة، و`.gitattributes` | ١ ساعة | منخفض | +١ (أ) | قبل |
| ٧ | توحيد مسار الإنشاء: دالة واحدة `build_kwargs(op, payload, ctx)` لكل نوع تستعملها `operations` و`entry_actions` (القضاء على الزوج الموازي) | ١٢–١٦ ساعة | **متوسط-عالٍ** (يمس ترحيل المال؛ شبكة الأمان: اختبارات الجلسة + parity من #١) | +٣ (ب) | **بعد** — أكبر من أن يُنفَّذ قبل التوازي؛ #١ يعالج الخطر الفوري |
| ٨ | نقل منطق dashboard/search/reports إلى `app/engine/queries/*` (الموجّه يستدعي فقط) | ١٠–١٤ ساعة | متوسط (أرقام معروضة للمالك؛ اختبارات dashboard/reports ٥ و٣ ملفات تحمي) | +٣ (أ، و) | بعد |
| ٩ | تفكيك `OperationForm.tsx` (مكوّن لكل نوع عملية + `useReducer` للحالة المشتركة) | ٢٠–٢٨ ساعة | **عالٍ** نسبياً (UI؛ يحميه ١٢٧ اختبار متصفح) | +٣ (أ) | بعد — لا يُلمس نموذج الإدخال الحيّ أثناء التوازي |
| ١٠ | طبقة جلب موحَّدة للواجهة (hook `useApi`) تعالج ٣٣ تحذير `set-state-in-effect` و٧ `exhaustive-deps` | ٨–١٢ ساعة | متوسط | +١٫٥ (أ، ج) | بعد |
| ١١ | توليد `types.ts` من `/openapi.json` | ٥–٧ ساعات | منخفض-متوسط | +١٫٥ (ب) | بعد (ويكشف أيضاً حقولاً تُرسل ولا يقرأها الخادم) |
| ١٢ | اختبارات إضافية: مصالحة (متصفح + API)، `account_filters`، `periods`، `local_move` فروع | ٨–١٠ ساعات | منخفض | +١ (د) | الجزء الخاص بالمصالحة قبل، والباقي بعد |

**الإجمالي المحتمل:** ٦٨ → ~٨٧–٨٩٪ إذا نُفِّذت كلها. تنفيذ بنود «قبل التوازي» وحدها (١–٦، ≈ ٢٠–٢٧ ساعة) يرفع إلى ~٨٠٪.

## ٩. حدود هذا التقرير
- لم أشغّل التغطية الفعلية ولا `--durations`، فأرقام §٣ و§٦ تقديرية **[س]**.
- لم أثبّت radon/ruff/mypy (يتطلب PyPI)؛ التعقيد بعدّ فروع `ast` تقريبي وليس McCabe الكامل.
- علّة `entry_date` عند التعديل مستنتجة من قراءة الكود لا من تشغيل؛ تحتاج اختباراً (#١) قبل اعتمادها.
- لم أقيّم الواجهة بصرياً ولا الأداء تحت الحمل (خارج نطاق هذا الوكيل).

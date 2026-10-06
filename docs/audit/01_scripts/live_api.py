"""الوكيل ١ — الفحص الحي (واجهة API) على wamda_test حصراً: خادم uvicorn مؤقت + مستخدم qa_aud_* + بيانات QA-*.
لكل كتابة: الجداول التي تغيّر عددها فعلاً + سطور audit_log الجديدة. ثم مقارنة قيود القاعدة بما تعيده الواجهات.
ثم تنظيف محصور بالسابقة وتحقق من العدّ، وإنهاء الخادم في finally.
تشغيل: venv/Scripts/python.exe docs/audit/01_scripts/live_api.py [--ui]
"""
import os, re, sys, json, time, uuid, socket, subprocess, urllib.request, traceback, datetime

sys.path.insert(0, '.')
from dotenv import dotenv_values

base = os.environ.get('DATABASE_URL') or dotenv_values('.env')['DATABASE_URL']
URL = re.sub(r"/([^/?]+)(\?.*)?$", lambda m: f"/{re.sub(r'(_db|_test)$', '', m.group(1))}_test{m.group(2) or ''}", base)
assert URL.rsplit('/', 1)[1].split('?')[0] == 'wamda_test', 'رفض: ليست قاعدة الاختبار'
os.environ['DATABASE_URL'] = URL
os.environ['LOGIN_RATE_LIMIT_MAX'] = '1000'
os.environ['PORTAL_LOGIN_RATE_LIMIT_MAX'] = '1000'

import httpx, pyotp, psutil
from sqlalchemy import text
from app.database import SessionLocal
from app.models import Client, User
from app.security.passwords import hash_password

OUT = 'docs/audit/01_scripts/out'
ROOT = os.getcwd()
UID = uuid.uuid4().hex[:6]
USERNAME = f'qa_aud_{UID}'
PASSWORD = 'QaAudit!Pass9x'
SECRET = pyotp.random_base32()
CODES = {'c1': f'QA-AUD-{UID.upper()}-1', 'c2': f'QA-AUD-{UID.upper()}-2', 'p1': f'QA-P-AUD-{UID.upper()}'}


def q(sql, **kw):
    s = SessionLocal()
    try:
        return s.execute(text(sql), kw).all()
    finally:
        s.close()


def scalar(sql, **kw):
    r = q(sql, **kw)
    return r[0][0] if r else None


TABLES = [r[0] for r in q("select tablename from pg_tables where schemaname='public' and tablename<>'alembic_version' order by 1")]


def counts():
    s = SessionLocal()
    try:
        return {t: s.execute(text(f'select count(*) from "{t}"')).scalar() for t in TABLES}
    finally:
        s.close()


def kill_tree(proc):
    try:
        parent = psutil.Process(proc.pid)
        procs = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return []
    pids = [p.pid for p in procs]
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=10)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    return pids


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


results = []
state = {}  # ids المُنشأة
cli = None


def hdr(idem=False):
    h = {'X-CSRF-Token': state['jar'].get('wamda_csrf', ''), 'Cookie': '; '.join(f'{k}={v}' for k, v in state['jar'].items())}
    if idem:
        h['Idempotency-Key'] = uuid.uuid4().hex
    return h


def step(label, method, path, body=None, idem=False):
    before = counts()
    a0 = scalar('select coalesce(max(id),0) from audit_log')
    r = cli.request(method, path, json=body, headers=hdr(idem))
    after = counts()
    delta = {t: after[t] - before[t] for t in TABLES if after[t] != before[t] and t != 'audit_log'}
    aud = q('select action, entity, entity_id from audit_log where id>:a order by id', a=a0)
    try:
        js = r.json() if r.content else None
    except Exception:
        js = r.text[:200]
    rec = dict(label=label, method=method, path=path, status=r.status_code, tables_written=delta,
               audit_rows=[f'{a}/{e}#{i}' for a, e, i in aud], audit_count=len(aud))
    if r.status_code >= 400:
        rec['error'] = (json.dumps(js, ensure_ascii=False)[:260] if js is not None else '')
    results.append(rec)
    print(f"[{r.status_code}] {method} {path} | tables={delta} | audit={rec['audit_rows']}" + (f" | ERR {rec.get('error')}" if 'error' in rec else ''))
    return r, js


def run():
    global cli
    port = free_port()
    env = {**os.environ}
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                            cwd=ROOT, env=env, stdout=open(f'{OUT}/server.log', 'w'), stderr=subprocess.STDOUT)
    state['server_pids'] = [proc.pid]
    baseurl = f'http://127.0.0.1:{port}'
    state['base'] = baseurl
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(baseurl + '/health', timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError('الخادم لم يبدأ')
        state['server_pids'] = [p.pid for p in [psutil.Process(proc.pid), *psutil.Process(proc.pid).children(recursive=True)]]
        # --- هوية QA مباشرة في القاعدة (كما tests/ui_support.py)
        s = SessionLocal()
        u = User(username=USERNAME, full_name='QA audit', role='ADMIN')
        u.password_hash = hash_password(PASSWORD)
        u.is_active, u.must_change_password = True, False
        u.totp_secret = SECRET
        s.add(u)
        for k in ('c1', 'c2'):
            s.add(Client(code=CODES[k], name_ar=f'عميل تدقيق {CODES[k]}', search_name=f'عميل تدقيق {CODES[k]}'))
        s.commit()
        s.close()
        cli = httpx.Client(base_url=baseurl, timeout=60, follow_redirects=False)
        r = cli.post('/auth/login', json={'username': USERNAME, 'password': PASSWORD, 'totp_code': pyotp.TOTP(SECRET).now()})
        state['jar'] = {c.name: c.value for c in r.cookies.jar}
        cli.cookies.clear()
        print('login', r.status_code, 'cookies:', sorted(state['jar']))
        assert r.status_code == 200, r.text
        scenario()
        if '--ui' in sys.argv:
            import live_ui
            live_ui.run(baseurl, USERNAME, PASSWORD, SECRET, state, results)
        compare_reads()
        import live_types
        live_types.run(cli, hdr, state, results)
    except Exception:
        traceback.print_exc()
        state['fatal'] = traceback.format_exc()[-800:]
    finally:
        try:
            cleanup()
        except Exception:
            traceback.print_exc()
            state['cleanup_error'] = traceback.format_exc()[-600:]
        state['killed_pids'] = kill_tree(proc)
        json.dump(dict(results=results, state=state), open(f'{OUT}/live_api.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


def scenario():
    # ---------- إعدادات
    r, js = step('GET company (قبل)', 'GET', '/settings/company')
    state['company_before'] = js
    tiny = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=='
    step('PUT company مع شعار', 'PUT', '/settings/company', {'name_ar': 'QA شركة', 'logo_data_url': tiny})
    step('PUT company كما تفعل الواجهة (name_ar فقط)', 'PUT', '/settings/company', {'name_ar': 'QA شركة 2'})
    r, js = step('GET company (بعد)', 'GET', '/settings/company')
    state['logo_survives_ui_put'] = bool(js and js.get('logo_data_url'))
    step('POST currency QAZ', 'POST', '/settings/currencies', {'code': 'QAZ', 'name_ar': 'QA عملة', 'symbol': 'Q', 'decimals': 2, 'sort_order': 99})
    step('PATCH currency QAZ', 'PATCH', '/settings/currencies/QAZ', {'name_ar': 'QA عملة 2'})
    step('POST location QA-LOC', 'POST', '/settings/locations', {'code': 'QA-LOC', 'name_ar': 'QA موقع', 'country': 'ليبيا'})
    step('PATCH location QA-LOC', 'PATCH', '/settings/locations/QA-LOC', {'country': 'تركيا'})
    step('POST client-currency-location', 'POST', '/settings/client-currency-locations', {'currency_code': 'QAZ', 'location_code': 'QA-LOC'})
    r, js = step('POST bank-account', 'POST', '/settings/bank-accounts', {'currency_code': 'USD', 'location_code': 'TRIPOLI', 'name_ar': 'QA-ACC بنك تدقيق'})
    state['bank_account'] = js
    # ---------- شركاء
    r, js = step('POST partner', 'POST', '/partners', {'code': CODES['p1'], 'name_ar': 'QA شريك تدقيق', 'country': 'تركيا', 'contact_phone': '000'})
    state['partner'] = js
    pid = js['id']
    r, js = step('POST partner account', 'POST', f'/partners/{pid}/accounts', {'parent_code': '1320', 'currency_code': 'USD', 'location_code': 'TURKEY', 'name_ar': 'QA-ACC حساب شريك'})
    state['partner_account'] = js
    # ---------- مستخدمون
    r, js = step('POST user', 'POST', '/users', {'username': f'qa_aud_u2_{UID}', 'full_name': 'QA u2', 'role': 'ACCOUNTANT', 'initial_password': 'QaAudit!Pass9y'})
    uid2 = js['id'] if js and 'id' in js else None
    state['user2'] = uid2
    if uid2:
        step('PATCH user (تعطيل)', 'PATCH', f'/users/{uid2}', {'is_active': False})
    # ---------- عملاء
    c1 = q('select id from clients where code=:c', c=CODES['c1'])[0][0]
    c2 = q('select id from clients where code=:c', c=CODES['c2'])[0][0]
    state['c1'], state['c2'] = c1, c2
    r, js = step('POST client', 'POST', '/clients', {'code': f'QA-AUD-{UID.upper()}-3', 'name_ar': 'QA عميل 3', 'phone': '091', 'id_number': '123'})
    step('PATCH client', 'PATCH', f'/clients/{c1}', {'name_ar': f'عميل تدقيق معدّل {CODES["c1"]}', 'phone': '092'})
    step('PUT credit-mode', 'PUT', f'/clients/{c1}/credit-mode', {'mode': 'UNLIMITED'})
    step('PUT credit-limit', 'PUT', f'/clients/{c1}/credit-limits/LYD', {'mode': 'LIMIT', 'limit_amount': '5000'})
    for act in ('enable', 'invite', 'unlock', 'reset', 'disable'):
        step(f'POST portal {act}', 'POST', f'/clients/{c1}/portal/{act}')
    # ---------- عمليات
    ids = state.setdefault('entries', {})

    def op(name, path, body, key=None):
        r, js = step(f'op {name}', 'POST', path, body, idem=True)
        if r.status_code in (200, 201) and js:
            ids[key or name] = js.get('id') or js.get('chain_ref')
        return r, js

    op('receipt LYD', '/operations/receipt', {'client_id': c1, 'currency_code': 'LYD', 'location_code': 'TRIPOLI', 'amount': '1000.000', 'receiving_account_code': '1101', 'note': 'QA قبض'}, 'receipt_lyd')
    op('receipt USD', '/operations/receipt', {'client_id': c1, 'currency_code': 'USD', 'location_code': 'TRIPOLI', 'amount': '500.00', 'receiving_account_code': '1104', 'note': 'QA قبض دولار'}, 'receipt_usd')
    op('payment LYD', '/operations/payment', {'client_id': c1, 'currency_code': 'LYD', 'location_code': 'TRIPOLI', 'amount': '200.000', 'paying_account_code': '1101', 'note': 'QA صرف'}, 'payment_lyd')
    op('exchange CLIENT', '/operations/exchange', {'client_id': c1, 'from_currency': 'USD', 'from_location_code': 'TRIPOLI', 'to_currency': 'LYD', 'to_location_code': 'TRIPOLI', 'amount': '100.00', 'cost_rate': '5.000000', 'client_rate': '4.900000', 'note': 'QA صرافة عميل'}, 'exchange_client')
    op('exchange TREASURY', '/operations/exchange', {'source_account_code': '1104', 'destination_account_code': '1101', 'from_currency': 'USD', 'to_currency': 'LYD', 'amount': '50.00', 'client_rate': '5.100000', 'note': 'QA صرافة خزينة'}, 'exchange_treasury')
    op('expense', '/operations/expense', {'expense_account_code': '5201', 'currency_code': 'LYD', 'paying_account_code': '1101', 'amount': '25.000', 'description': 'QA مصروف'}, 'expense')
    op('local-move + commission', '/operations/local-move', {'currency_code': 'LYD', 'from_account_code': '1101', 'to_account_code': '1102', 'amount': '100.000', 'note': 'QA نقل', 'commission_direction': 'OUT', 'commission_currency': 'LYD', 'commission_amount': '2.000', 'commission_account_code': '1101'}, 'local_move')
    op('remit-out', '/operations/remit-out', {'client_id': c1, 'from_location_code': 'TRIPOLI', 'sending_account_code': '1101', 'currency_code': 'LYD', 'amount': '50.000', 'note': 'QA إرسال خارجي'}, 'remit_out')
    op('adjustment', '/operations/adjustment', {'account_code': '1101', 'currency_code': 'LYD', 'amount': '10.000', 'is_debit': True, 'reason': 'QA تسوية', 'note': 'QA'}, 'adjustment')
    pacc = state['partner_account']['code']
    op('cash-transfer', '/operations/cash-transfer', {'client_id': c1, 'currency_code': 'USD', 'from_location_code': 'TRIPOLI', 'to_location_code': 'TURKEY', 'amount': '100.00', 'source_account_code': '1104', 'execution_account_code': pacc, 'commission_currency': 'USD', 'client_commission_amount': '5.00', 'cost_commission_amount': '2.00', 'cost_correspondent_account_code': pacc, 'note': 'QA تحويل بعمولة'}, 'cash_transfer')
    op('swift-out', '/operations/swift-out', {'partner_account_code': pacc, 'amount': '100.00', 'external_ref': f'QA-SW-{UID}', 'note': 'QA سويفت', 'allow_negative': True, 'override_reason': 'QA audit'}, 'swift_out')
    op('opening (client2)', '/operations/opening', {'client_id': c2, 'location_code': 'TRIPOLI', 'currency_code': 'LYD', 'amount': '300.000', 'is_debit': False, 'as_of_date': '2026-01-01', 'source_type': 'VERIFIED', 'confidence': 'HIGH', 'note': 'QA افتتاحي'}, 'opening')
    for (c1r, cl1, c2r, cl2) in (('5.000000', '5.100000', '7.000000', '6.900000'), ('5.000000', '4.900000', '7.000000', '6.900000'),
                                 ('5.000000', '5.100000', '7.000000', '7.100000'), ('5.000000', '4.900000', '7.000000', '7.100000')):
        r, js = op('exchange-chain', '/operations/exchange-chain', {'client_id': c1, 'step1': {'from_currency': 'LYD', 'to_currency': 'USD', 'amount': '100.000', 'cost_rate': c1r, 'client_rate': cl1, 'from_location_code': 'TRIPOLI', 'to_location_code': 'TRIPOLI'}, 'step2': {'to_currency': 'CNY', 'cost_rate': c2r, 'client_rate': cl2, 'to_location_code': 'CHINA'}, 'note': 'QA سلسلة'}, 'chain')
        if r.status_code in (200, 201):
            break
    # swift-in من المعلّق
    r, js = step('GET pending swift', 'GET', '/reference/swift-movements/pending')
    mov = next((m for m in (js or []) if str(m.get('external_ref', '')).startswith('QA-SW-')), None)
    if mov:
        op('swift-in', '/operations/swift-in', {'swift_movement_id': mov['id'], 'total_amount': '100.00', 'fee_amount': '1.00', 'receiving_account_code': '1104', 'note': 'QA وصول'}, 'swift_in')
    # تعليق/تعديل/إلغاء
    rid = ids.get('expense')
    if rid:
        step('POST comment', 'POST', f'/operations/{rid}/comments', {'body': 'QA تعليق'})
        r, js = step('GET source-request (للتعديل)', 'GET', f'/operations/{rid}/source-request')
        req = (js or {}).get('request') or {}
        req['amount'] = '30.000'
        r, js = step('POST edit receipt', 'POST', f'/operations/{rid}/edit', {'reason': 'QA تعديل', 'operation': req}, idem=True)
        state['edit_result'] = js
    pid_e = ids.get('payment_lyd')
    if pid_e:
        step('POST cancel payment', 'POST', f'/operations/{pid_e}/cancel', {'reason': 'QA إلغاء'})
    # ---------- مطابقة
    sid = None
    r, js = step('POST statement', 'POST', '/reconciliation/statements', {'partner_id': state['partner']['id'], 'period_from': '2026-01-01', 'period_to': '2026-12-31', 'lines': [{'value_date': '2026-06-01', 'description': 'QA سطر 1', 'amount': '100.00'}, {'value_date': '2026-06-02', 'description': 'QA سطر 2', 'amount': '37.50'}]})
    if js and 'id' in js:
        sid = js['id']
        state['statement'] = js
        r, aj = step('POST auto-match', 'POST', f'/reconciliation/statements/{sid}/auto-match')
        lines = (aj or {}).get('statement', {}).get('lines') or js['lines']
        open_lines = [l for l in lines if l['status'] == 'OPEN']
        if open_lines:
            step('PATCH resolve', 'PATCH', f'/reconciliation/statements/{sid}/lines/{open_lines[0]["id"]}/resolve', {})
        if len(open_lines) > 1:
            step('POST adjust line', 'POST', f'/reconciliation/statements/{sid}/lines/{open_lines[1]["id"]}/adjust', {'account_code': pacc, 'currency_code': 'USD', 'amount': '37.50', 'is_debit': True, 'reason': 'QA تسوية فرق'}, idem=True)
    # ---------- فترات (إقفال ثم إعادة فتح لشهر ماضٍ)
    step('POST period close 2019-01', 'POST', '/periods/close', {'year': 2019, 'month': 1})
    step('POST period reopen 2019-01', 'POST', '/periods/reopen', {'year': 2019, 'month': 1})
    # ---------- أمان
    step('POST backup-codes/regenerate', 'POST', '/auth/backup-codes/regenerate', {'password': PASSWORD})


# ---------- مقارنة القراءات بالقاعدة

def dec(s):
    from decimal import Decimal
    return Decimal(str(s))


def compare_reads():
    mism = []
    ok = 0
    checks = []
    c1 = state['c1']
    # 1) رصيد كل حساب عميل: API /clients/{id}/balances و /clients/{id} مقابل account_balances
    r = cli.get(f'/clients/{c1}/balances', headers=hdr())
    api_bal = {b['account_code']: b for b in r.json()} if r.status_code == 200 else {}
    rows = q('''select a.code, a.currency_code, ab.balance, c.decimals from accounts a join account_balances ab on ab.account_id=a.id
                join currencies c on c.code=a.currency_code where a.client_id=:c''', c=c1)
    for code, cur, bal, decs in rows:
        a = api_bal.get(code)
        if a is None:
            mism.append(('balances: حساب غائب من API', code)); continue
        if dec(a['balance']) != dec(bal):
            mism.append(('balances: قيمة', code, a['balance'], str(bal)))
        else:
            ok += 1
        places = len(str(a['balance']).split('.')[1]) if '.' in str(a['balance']) else 0
        if places != 6:
            mism.append(('balances: API لا يعيد ٦ منازل خام', code, a['balance']))
    # 2) كشف الحساب: (أ) مع include_reversed=true: كل صف مقابل سطر القاعدة (متعدد المجموعات داخل القيد) + الرصيد الجارٍ + الإغلاق
    #    (ب) العرض الافتراضي (الذي تعرضه الواجهة): آخر رصيد جارٍ ظاهر مقابل closing_balance وaccount_balances
    state['statement_dump'] = {}
    for cur, loc in (('LYD', 'TRIPOLI'), ('USD', 'TRIPOLI'), ('USD', 'TURKEY'), ('CNY', 'CHINA')):
        r = cli.get(f'/clients/{c1}/statement', params={'currency': cur, 'location': loc, 'include_reversed': 'true'}, headers=hdr())
        r2 = cli.get(f'/clients/{c1}/statement', params={'currency': cur, 'location': loc}, headers=hdr())
        if r.status_code != 200 or r2.status_code != 200:
            mism.append(('statement http', cur, loc, r.status_code, r2.status_code)); continue
        st, st2 = r.json(), r2.json()
        if not st['account_code']:
            continue
        dbl = q("""select e.entry_no, e.status, jl.debit, jl.credit from journal_lines jl join accounts a on a.id=jl.account_id
                   join journal_entries e on e.id=jl.entry_id where a.code=:code order by e.entry_date, e.id, jl.line_no""", code=st['account_code'])
        state['statement_dump'][f'{cur}-{loc}'] = dict(api_all=[(x['entry_no'], x['status'], x['debit'], x['credit'], x['running_balance']) for x in st['rows']],
                                                      api_default=[(x['entry_no'], x['status'], x['debit'], x['credit'], x['running_balance']) for x in st2['rows']],
                                                      db=[(n, stt, str(d), str(c)) for n, stt, d, c in dbl], closing=st['closing_balance'])
        from collections import Counter
        api_ms = Counter((x['entry_no'], str(dec(x['debit'])), str(dec(x['credit']))) for x in st['rows'])
        db_ms = Counter((n, str(d), str(c)) for n, stt, d, c in dbl)
        if api_ms != db_ms:
            mism.append(('statement(include_reversed): صفوف ≠ أسطر القاعدة', f'{cur}-{loc}', dict(api_ms - db_ms), dict(db_ms - api_ms)))
        else:
            ok += 1
        run = dec(st['opening_balance'])
        for row in st['rows']:
            run += dec(row['credit']) - dec(row['debit'])
            if dec(row['running_balance']) != run:
                mism.append(('statement: رصيد جارٍ ≠ تراكم الأسطر', f'{cur}-{loc}', row['entry_no'], row['running_balance'], str(run)))
        final = scalar("select ab.balance from account_balances ab join accounts a on a.id=ab.account_id where a.code=:code", code=st['account_code'])
        if dec(st['closing_balance']) != dec(final):
            mism.append(('statement: closing_balance ≠ account_balances', f'{cur}-{loc}', st['closing_balance'], str(final)))
        if st2['rows'] and dec(st2['rows'][-1]['running_balance']) != dec(final):
            mism.append(('statement(الافتراضي المعروض): آخر رصيد جارٍ ظاهر ≠ الرصيد الفعلي', f'{cur}-{loc}', st2['rows'][-1]['running_balance'], str(final), 'closing_balance غير معروض في الواجهة'))
        checks.append((cur, loc, len(st['rows']), len(st2['rows'])))
    # 3) /journal/entries: كل قيد → مجموع المدين = الدائن، والمبالغ المعروضة = journal_lines
    r = cli.get('/journal/entries', params={'limit': 200}, headers=hdr())
    entries = r.json() if r.status_code == 200 else []
    state['journal_entries_http'] = r.status_code
    for e in entries:
        if not str(e.get('entry_no', '')):
            continue
        db_lines = q('''select a.code, jl.currency_code, jl.debit, jl.credit from journal_lines jl join accounts a on a.id=jl.account_id
                        where jl.entry_id=:e order by jl.line_no''', e=e['id'])
        # الأسطر المعروضة
        api_lines = e.get('lines') or []
        got = sorted((l['account_code'], l['currency_code'], str(dec(l['debit'])), str(dec(l['credit']))) for l in api_lines)
        exp = sorted((c, cur, str(dec(d)), str(dec(cr))) for c, cur, d, cr in db_lines)
        if got != exp:
            mism.append(('journal/entries: أسطر مختلفة', e['entry_no'], got[:4], exp[:4]))
        else:
            ok += 1
        # توازن لكل عملة
        sums = {}
        for c, cur, d, cr in db_lines:
            sums[cur] = sums.get(cur, 0) + (d - cr)
        if any(v != 0 for v in sums.values()):
            mism.append(('قيد غير متوازن بالعملة', e['entry_no'], {k: str(v) for k, v in sums.items()}))
        # الخانات العشرية لكل عملة في الأسطر المعروضة
        for l in api_lines:
            decs = scalar('select decimals from currencies where code=:c', c=l['currency_code'])
            for k in ('debit', 'credit'):
                v = str(l[k])
                places = len(v.split('.')[1]) if '.' in v else 0
                if places != 6:
                    mism.append(('journal/entries: API لا يعيد ٦ منازل خام', e['entry_no'], k, v))
    # 4) account_balances مقابل مجموع الأسطر (كل حسابات الاختبار)
    drift = q('''select a.code, ab.balance, coalesce(sum(jl.credit-jl.debit),0) s, a.type
                 from accounts a left join account_balances ab on ab.account_id=a.id left join journal_lines jl on jl.account_id=a.id
                 where a.code in ('1101','1102','1104') or a.client_id in (:c1,:c2) group by a.code, ab.balance, a.type''', c1=state['c1'], c2=state['c2'])
    state['balance_sign_convention_sample'] = [(c, str(b), str(s), t) for c, b, s, t in drift]
    state['compare'] = dict(ok=ok, mismatches=mism, statement_checks=checks, entries_checked=len(entries))
    print('COMPARE ok=', ok, 'mismatches=', len(mism))
    for m in mism[:40]:
        print('  MISMATCH', m)


def cleanup():
    s = SessionLocal()
    try:
        s.execute(text("delete from periods where year=2019 and month=1"))  # أنشأته أنا؛ يمنع حذف مستخدمي qa_aud_*
        s.commit()
        from app.cli import purge_demo_data
        from app.config import settings
        assert settings.database_url.rsplit('/', 1)[1].split('?')[0] == 'wamda_test'
        state['purge_blocked'] = purge_demo_data._purge(s)
        s.commit()
    except Exception as e:
        s.rollback()
        state['purge_error'] = repr(e)[:300]
    finally:
        s.close()
    s = SessionLocal()
    try:
        # عناصر أنشأتُها بلا سابقة قابلة للتطهير: حذف مباشر محصور بالمُعرِّف/الرمز (كلها QAZ/QA-LOC/QA-ACC)
        qaz = "(select id from accounts where currency_code='QAZ')"
        s.execute(text(f"delete from account_balances where account_id in {qaz}"))
        s.execute(text("delete from account_number_assignments where currency_code='QAZ'"))
        s.execute(text("delete from accounts where currency_code='QAZ'"))
        s.execute(text("delete from client_currency_locations where currency_code='QAZ' or location_id in (select id from locations where code='QA-LOC')"))
        s.execute(text("delete from currencies where code='QAZ'"))
        s.execute(text("delete from locations where code='QA-LOC'"))
        s.execute(text("delete from settings where key='company_profile'"))
        for acc_id in [state.get('bank_account', {}).get('id')] if state.get('bank_account') else []:
            s.execute(text('delete from account_balances where account_id=:i'), {'i': acc_id})
            s.execute(text('delete from accounts where id=:i'), {'i': acc_id})
        # عدّادات الترقيم: أعِدها لقيمها قبل التشغيل (أنا من رفعها)
        for pid, nxt in state.get('counters_before', {}).items():
            s.execute(text('update account_number_counters set next_suffix=:n where parent_id=:p'), {'n': nxt, 'p': int(pid)})
        s.execute(text('delete from account_number_counters where parent_id not in (%s)' % (','.join(str(int(k)) for k in state.get('counters_before', {})) or '0')))
        s.execute(text("delete from sessions where subject_id in (select id from users where username like 'qa_aud_%')"))
        s.execute(text("delete from user_backup_codes where user_id in (select id from users where username like 'qa_aud_%')"))
        s.commit()
        for u in s.execute(text("select id,username from users where username like 'qa_aud_%'")).all():
            try:
                s.execute(text('delete from users where id=:i'), {'i': u[0]})
                s.commit()
            except Exception:
                s.rollback()
                s.execute(text('update users set is_active=false where id=:i'), {'i': u[0]})
                s.commit()
                state.setdefault('users_deactivated_not_deleted', []).append(u[1])
    except Exception as e:
        s.rollback()
        state['cleanup2_error'] = repr(e)[:400]
    finally:
        s.close()
    state['after_cleanup'] = dict(
        qa_clients=scalar("select count(*) from clients where code like 'QA-%'"),
        qa_partners=scalar("select count(*) from partners where code like 'QA-P-%'"),
        qa_users=scalar("select count(*) from users where username like 'qa_aud_%'"),
        entries=scalar('select count(*) from journal_entries'),
        lines=scalar('select count(*) from journal_lines'),
        qaz=scalar("select count(*) from currencies where code='QAZ'"),
        qaz_accounts=scalar("select count(*) from accounts where currency_code='QAZ'"),
        qa_loc=scalar("select count(*) from locations where code='QA-LOC'"),
        qa_accounts=scalar("select count(*) from accounts where name_ar like 'QA-ACC%'"),
        audit_rows=scalar('select count(*) from audit_log'))
    print('AFTER CLEANUP', state['after_cleanup'])


if __name__ == '__main__':
    sys.path.insert(0, 'docs/audit/01_scripts')
    before = counts()
    state['counts_before'] = {t: n for t, n in before.items() if n}
    state['counters_before'] = {str(a): b for a, b in q('select parent_id,next_suffix from account_number_counters')}
    run()
    after = counts()
    state['counts_after'] = {t: n for t, n in after.items() if n}
    state['count_diff_vs_before'] = {t: after[t] - before[t] for t in TABLES if after[t] != before[t]}
    json.dump(dict(results=results, state=state), open(f'{OUT}/live_api.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print('DIFF vs before:', state['count_diff_vs_before'])
    print('orphans check (psutil):', [(p.pid, p.name()) for p in psutil.Process().children(recursive=True)])

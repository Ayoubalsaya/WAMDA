"""الوكيل ١ — مفاتيح استجابة الخادم الحية لكل GET تستهلكه الواجهة مقابل حقول واجهة TypeScript المعلنة. يُستدعى من live_api.py."""
import re, json

ENDPOINTS = [
    ('AccountOut', '/settings/bank-accounts', 'list'),
    ('AccountOut', '/partners/{pid}/accounts', 'list'),
    ('AccountRef', '/reference/accounts', 'list'),
    ('AuditLogRow', '/audit-log?limit=5', 'list'),
    ('BackupCodesStatus', '/auth/backup-codes', 'obj'),
    ('BalanceOverrideRow', '/reports/balance-overrides', 'list'),
    ('BanksResponse', '/accounts/banks', 'obj'),
    ('BoxesResponse', '/accounts/boxes', 'obj'),
    ('ClientBalance', '/clients/{c1}/balances', 'list'),
    ('ClientCurrencyLocationPair', '/reference/client-currency-locations', 'list'),
    ('ClientCurrencyLocationRow', '/settings/client-currency-locations', 'list'),
    ('ClientDetail', '/clients/{c1}', 'obj'),
    ('ClientLiabilitiesRow', '/reports/client-liabilities', 'list'),
    ('ClientListRow', '/clients', 'list'),
    ('ClientPortalStatusResponse', '/clients/{c1}/portal', 'obj'),
    ('ClientProfitabilityRow', '/reports/client-profitability', 'list'),
    ('ClientSearchResult', '/clients/search?q=QA', 'list'),
    ('CommentOut', '/operations/{eid}/comments', 'list'),
    ('CompanyProfile', '/settings/company', 'obj'),
    ('CorrespondentActivityRow', '/reports/correspondent-activity', 'list'),
    ('CorrespondentsResponse', '/accounts/correspondents', 'obj'),
    ('CurrencyAdminRow', '/settings/currencies', 'list'),
    ('Currency', '/reference/currencies', 'list'),
    ('CurrentUser', '/auth/me', 'obj'),
    ('DashboardSummary', '/dashboard/summary', 'obj'),
    ('DebtorRow', '/reports/debtors', 'list'),
    ('EmergencyEntryRow', '/reports/emergency-entries', 'list'),
    ('FoundingPeriodStatus', '/periods/founding', 'obj'),
    ('FoundingReconciliationResponse', '/reports/founding-reconciliation', 'obj'),
    ('HistoryResponse', '/operations/{eid}/history', 'obj'),
    ('IncomeStatementResponse', '/reports/income-statement', 'obj'),
    ('JournalEntryOut', '/journal/entries?limit=5', 'list'),
    ('LiquidityRow', '/position/liquidity', 'list'),
    ('LocationAdminRow', '/settings/locations', 'list'),
    ('Location', '/reference/locations', 'list'),
    ('LossMakingEntryRow', '/reports/loss-making-operations', 'list'),
    ('LotRow', '/lots', 'list'),
    ('OpeningBalanceRow', '/periods/opening-balances', 'list'),
    ('PartnerRow', '/partners', 'list'),
    ('PartnerStatementSummary', '/reconciliation/statements', 'list'),
    ('PartnerStatementDetail', '/reconciliation/statements/{sid}', 'obj'),
    ('PendingSwiftMovement', '/reference/swift-movements/pending', 'list'),
    ('PeriodRow', '/periods', 'list'),
    ('ProfitByPeriodRow', '/reports/profit-by-period?granularity=month', 'list'),
    ('SimilarClient', '/clients/similar?name=QA', 'list'),
    ('StatementResponse', '/clients/{c1}/statement?currency=LYD&location=TRIPOLI', 'obj'),
    ('SwiftHistoryRow', '/reports/swift-history', 'list'),
    ('TrialBalanceResponse', '/reports/trial-balance', 'obj'),
    ('UserListRow', '/users', 'list'),
]


def parse_ts(path='frontend/src/api/types.ts'):
    ts = open(path, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'export interface (\w+)(?:<[^>]*>)?\s*(?:extends [^{]+)?\{', ts):
        j = m.end()
        d = 1
        while j < len(ts) and d:
            d += (ts[j] == '{') - (ts[j] == '}')
            j += 1
        body = ts[m.end():j - 1]
        fields, depth = {}, 0
        for line in body.split('\n'):
            s = line.strip()
            if depth == 0:
                mm = re.match(r'(?:readonly )?([A-Za-z_]\w*)(\?)?:', s)
                if mm:
                    fields[mm.group(1)] = bool(mm.group(2))
            depth += s.count('{') - s.count('}')
        out[m.group(1)] = fields
    return out


def run(cli, hdr, state, results):
    ifaces = parse_ts()
    subs = dict(pid=(state.get('partner') or {}).get('id'), c1=state.get('c1'), eid=(state.get('entries') or {}).get('receipt_lyd'),
                sid=(state.get('statement') or {}).get('id'))
    rows = []
    for tname, path, kind in ENDPOINTS:
        try:
            url = path.format(**subs)
        except Exception:
            rows.append(dict(type=tname, path=path, note='لا معرّف متاح'))
            continue
        r = cli.get(url, headers=hdr())
        rec = dict(type=tname, path=url, status=r.status_code)
        if r.status_code != 200:
            rec['note'] = r.text[:100]
            rows.append(rec)
            continue
        js = r.json()
        sample = js
        if kind == 'list':
            if not js:
                rec['note'] = 'قائمة فارغة — لا عيّنة'
                rows.append(rec)
                continue
            sample = js[0]
        if not isinstance(sample, dict):
            rec['note'] = f'شكل غير متوقع {type(sample).__name__}'
            rows.append(rec)
            continue
        ts_fields = ifaces.get(tname)
        if ts_fields is None:
            rec['note'] = 'واجهة TS غير موجودة بالاسم'
            rows.append(rec)
            continue
        srv = set(sample)
        rec['ts_expects_server_lacks'] = sorted(set(ts_fields) - srv)
        rec['server_sends_ts_lacks'] = sorted(srv - set(ts_fields))
        rows.append(rec)
    state['types_live'] = rows
    for rec in rows:
        if rec.get('ts_expects_server_lacks') or rec.get('server_sends_ts_lacks') or rec.get('note') or rec.get('status', 200) != 200:
            print('TYPES', json.dumps(rec, ensure_ascii=False)[:300])

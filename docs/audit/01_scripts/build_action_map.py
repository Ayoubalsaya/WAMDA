"""الوكيل ١ — يبني جدول «الإجراء ← استدعاء الواجهة ← المسار ← المحرك/الخدمة ← الجداول المكتوبة (حياً) ← سطر التدقيق (حياً)». قراءة فقط."""
import re, sys, json, inspect

sys.path.insert(0, '.')
from fastapi.routing import APIRoute
from app.main import app

callers = json.load(open('docs/audit/01_scripts/out/route_callers.json', encoding='utf-8'))
live = json.load(open('docs/audit/01_scripts/out/live_api.json', encoding='utf-8'))['results']
PH = chr(1)


def norm(p):
    p = re.sub(r'\{[^}/]*\}', PH, p)
    return p


def live_for(method, path):
    pat = '^' + re.escape(norm(path)).replace(re.escape(PH), '[^/]+') + '$'
    hits = [r for r in live if r['method'] == method and re.match(pat, r['path'].split('?')[0])]
    return hits


rows = []
for r in sorted((r for r in app.routes if isinstance(r, APIRoute)), key=lambda r: r.path):
    for m in sorted(r.methods - {'HEAD', 'OPTIONS'}):
        if m == 'GET':
            continue
        src = inspect.getsource(r.endpoint)
        eng = sorted(set(re.findall(r'\b((?:accounts_repo|posting|chain|recompute|numbering|swift_in|swift_out|swift_return|receipt|payment|exchange|expense|local_move|cash_transfer|remit_out|opening|adjustment|auth_service|portal_auth_service|user_management|client_portal_management|client_portal_invites|backup_codes|sessions|audit)\.\w+)', src)))
        line = inspect.getsourcelines(r.endpoint)[1]
        file = inspect.getsourcefile(r.endpoint).replace('\\', '/').split('/wamda/')[-1]
        static_audit = bool(re.search(r'audit\.log_write|log_write\(', src))
        key = f'{m} {r.path}'
        ui = callers.get(key) or callers.get(f'{m} {r.path}'.replace('{', '{'))
        lv = live_for(m, r.path)
        rows.append(dict(route=key, handler=f'{file}:{line}', engine=eng, ui=ui, static_audit_in_handler=static_audit,
                         live=[dict(status=x['status'], tables=x['tables_written'], audit=x['audit_rows']) for x in lv]))
json.dump(rows, open('docs/audit/01_scripts/out/action_map.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
out = ['| المسار | المعالج | استدعاء الواجهة | محرك/خدمة | الجداول المكتوبة (حياً) | سطر تدقيق (حياً) |', '|---|---|---|---|---|---|']
for x in rows:
    ui = ', '.join(u.split('/')[-1] for u in (x['ui'] or [])[:2]) or '—'
    eng = '، '.join(x['engine']) or '—'
    if x['live']:
        l = x['live'][-1]
        tables = ', '.join(f'{t}+{n}' for t, n in l['tables'].items()) or '—'
        aud = ', '.join(l['audit']) if l['audit'] else '**لا شيء**'
        if l['status'] >= 400:
            tables, aud = f'(فشل {l["status"]})', '—'
    else:
        tables, aud = 'لم يُنفَّذ حياً', ('نعم (ثابت)' if x['static_audit_in_handler'] else 'لا يظهر (ثابت)')
    out.append(f'| `{x["route"]}` | `{x["handler"]}` | {ui} | {eng} | {tables} | {aud} |')
open('docs/audit/01_scripts/out/action_map.md', 'w', encoding='utf-8').write('\n'.join(out))
print('\n'.join(out))

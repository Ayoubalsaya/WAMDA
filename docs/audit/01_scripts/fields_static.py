"""الوكيل ١ — (أ) سلوك extra لكل نموذج جسم طلب (ب) مفاتيح الجسم المُرسَل من الواجهة مقابل حقول المخطط. قراءة فقط."""
import re, glob, sys

sys.path.insert(0, '.')
from fastapi.routing import APIRoute
from app.main import app

PH = chr(1)
BS = chr(92)
QUOTES = '`' + "'" + '"'


def norm(p):
    p = re.sub(r'\$\{[^}]*\}', PH, p)
    p = re.sub(r'\{[^}/]*\}', PH, p)
    return p.split('?')[0].rstrip('/') or '/'


def rx(p):
    return re.compile('^' + re.escape(norm(p)).replace(re.escape(PH), '[^/]+?') + '$')


routes = [(m, r) for r in app.routes if isinstance(r, APIRoute) for m in r.methods - {'HEAD', 'OPTIONS'}]


def body_model(r):
    b = r.body_field
    return b.type_ if b is not None else None


print('== (أ) نماذج الجسم: extra ==')
for m, r in sorted(routes, key=lambda x: x[1].path):
    if m == 'GET':
        continue
    bm = body_model(r)
    if bm is None:
        continue
    print(f'{m:6} {r.path:58} {bm.__name__:34} extra={bm.model_config.get("extra", "ignore")}')


def skip_str(s, j):
    q = s[j]
    j += 1
    while j < len(s) and s[j] != q:
        if s[j] == BS:
            j += 1
        j += 1
    return j


def balanced(s, i):
    d = 0
    j = i
    while j < len(s):
        c = s[j]
        if c in '{[(':
            d += 1
        elif c in '}])':
            d -= 1
            if d == 0:
                return s[i:j + 1]
        elif c in QUOTES:
            j = skip_str(s, j)
        j += 1
    return s[i:]


def top_keys(obj):
    inner = obj[1:-1]
    parts, cur, d, j = [], [], 0, 0
    while j < len(inner):
        c = inner[j]
        if c in QUOTES:
            e = skip_str(inner, j)
            cur.append(inner[j:e + 1])
            j = e + 1
            continue
        if c in '{[(':
            d += 1
        elif c in '}])':
            d -= 1
        if c == ',' and d == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        j += 1
    parts.append(''.join(cur))
    keys = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p.startswith('...'):
            keys.append('...spread')
            continue
        mm = re.match(r'([A-Za-z_]\w*)\s*(:|$)', p)
        if mm:
            keys.append(mm.group(1))
    return keys


print('\n== (ب) مفاتيح الجسم المُرسَل (حرفياً في موقع الاستدعاء) مقابل حقول المخطط ==')
PAT = re.compile(r'api\s*\.(post|put|patch)(?:<[^()]*?>)?\(\s*([`\'"])((?:\\.|(?!\2).)*?)\2\s*,\s*(\{)', re.S)
for f in sorted(glob.glob('frontend/src/**/*.ts*', recursive=True)):
    f = f.replace(BS, '/')
    s = open(f, encoding='utf-8').read()
    for m in PAT.finditer(s):
        meth = m.group(1).upper()
        path = m.group(3)
        obj = balanced(s, m.start(4))
        keys = top_keys(obj)
        line = s[:m.start()].count('\n') + 1
        hit = [r for mm, r in routes if mm == meth and rx(r.path).match(norm(path).replace(PH, 'Z'))]
        if not hit:
            print(f'{f}:{line} {meth} {path} -> لا مسار')
            continue
        bm = body_model(hit[0])
        if bm is None:
            print(f'{f}:{line} {meth} {path} keys={keys} -> المسار بلا جسم')
            continue
        fields = set(bm.model_fields)
        unknown = [k for k in keys if k not in fields and k != '...spread']
        req = [n for n, fi in bm.model_fields.items() if fi.is_required() and n not in keys and '...spread' not in keys]
        flag = 'تُرسَل ولا يعرفها المخطط!' if unknown else 'ok'
        print(f'{f}:{line} {meth} {path} [{bm.__name__} extra={bm.model_config.get("extra", "ignore")}] sent={keys} unknown={unknown} required_not_sent={req} {flag}')

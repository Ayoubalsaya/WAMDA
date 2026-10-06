"""الوكيل ١ — مفاتيح جسم كل عملية يبنيها OperationForm/OpeningBalancesTab/ExchangeWizard مقابل مخطط الخادم (extra=forbid). قراءة فقط."""
import re, sys

sys.path.insert(0, '.')
sys.path.insert(0, 'docs/audit/01_scripts')
import importlib.util

spec = importlib.util.spec_from_file_location('fs', 'docs/audit/01_scripts/fields_static.py')
# نعيد استخدام الدوال دون تنفيذ الطباعة: ننسخ التعريفات الصغيرة هنا
BS = chr(92)
QUOTES = '`' + "'" + '"'


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


from app.schemas import operations as ops

MAP = {
    'receipt': ops.ReceiptRequest, 'payment': ops.PaymentRequest, 'exchange': ops.ExchangeRatesRequest,
    'local-move': ops.LocalMoveRequest, 'cash-transfer': ops.CashTransferRequest, 'remit-out': ops.RemitOutRequest,
    'expense': ops.ExpenseRequest, 'swift-out': ops.SwiftOutRequest, 'swift-in': ops.SwiftInRequest,
    'swift-return': ops.SwiftReturnRequest, 'opening': ops.OpeningRequest, 'adjustment': ops.AdjustmentRequest,
}
src = open('frontend/src/screens/journal/OperationForm.tsx', encoding='utf-8').read()
print('== OperationForm.tsx: مفاتيح كل payload مقابل المخطط ==')
for m in re.finditer(r"url:\s*'/operations/([a-z\-]+)',\s*payload:\s*(\{)", src):
    name = m.group(1)
    obj = balanced(src, m.start(2))
    keys = top_keys(obj)
    # الأجسام الشرطية (exchange: scope ? {..} : {..}) تُستخرج من الكتلة كاملة
    line = src[:m.start()].count('\n') + 1
    model = MAP[name]
    fields = set(model.model_fields)
    unknown = [k for k in keys if k not in fields and k != '...spread']
    req = [n for n, fi in model.model_fields.items() if fi.is_required() and n not in keys and '...spread' not in keys]
    print(f'OperationForm.tsx:{line} {name:14} [{model.__name__}] sent={keys} unknown={unknown} required_not_sent={req}')
# exchange له جسمان شرطيان: نفحص الكتلة بعد "exchangeScope === 'TREASURY' ?"
m = re.search(r"url:\s*'/operations/exchange',\s*payload:\s*exchangeScope === 'TREASURY' \? (\{)", src)
if m:
    a = balanced(src, m.start(1))
    rest = src[m.start(1) + len(a):]
    b_start = rest.index('{')
    b = balanced(rest, b_start)
    for lab, obj in (('TREASURY', a), ('CLIENT', b)):
        keys = top_keys(obj)
        fields = set(ops.ExchangeRatesRequest.model_fields)
        print(f'exchange/{lab}: sent={keys} unknown={[k for k in keys if k not in fields and k != "...spread"]}')
ob = open('frontend/src/screens/settings/OpeningBalancesTab.tsx', encoding='utf-8').read()
i = ob.index("api.post('/operations/opening'")
print('OpeningBalancesTab body ctx:', ob[max(0, i - 600):i].replace('\n', ' ')[-600:])

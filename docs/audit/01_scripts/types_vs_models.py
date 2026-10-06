"""الوكيل ١ — حقول واجهات types.ts مقابل حقول نماذج الرد في الخادم (المطابقة بالاسم). قراءة فقط."""
import re, sys, importlib, pkgutil, inspect

sys.path.insert(0, '.')
from pydantic import BaseModel
import app.schemas as schemas_pkg
from app.main import app  # يستورد كل الموجّهات

models = {}
for mod in list(sys.modules.values()):
    if mod is None or not getattr(mod, '__name__', '').startswith('app.'):
        continue
    for n, obj in vars(mod).items():
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            models.setdefault(obj.__name__, obj)

ts = open('frontend/src/api/types.ts', encoding='utf-8').read()
ifaces = {}
for m in re.finditer(r'export interface (\w+)(?:<[^>]*>)?\s*(?:extends [^{]+)?\{', ts):
    start = m.end()
    d = 1
    j = start
    while j < len(ts) and d:
        if ts[j] == '{':
            d += 1
        elif ts[j] == '}':
            d -= 1
        j += 1
    body = ts[start:j - 1]
    fields = {}
    depth = 0
    for line in body.split('\n'):
        s = line.strip()
        if depth == 0:
            mm = re.match(r'(?:readonly )?([A-Za-z_]\w*)(\?)?:', s)
            if mm:
                fields[mm.group(1)] = bool(mm.group(2))
        depth += s.count('{') - s.count('}')
    ifaces[m.group(1)] = fields

matched = unmatched = 0
ui_only = []
srv_only = []
no_model = []
for name, fields in sorted(ifaces.items()):
    mod = models.get(name)
    if mod is None:
        no_model.append(name)
        continue
    matched += 1
    pf = set(mod.model_fields)
    a = sorted(set(fields) - pf)
    b = sorted(pf - set(fields))
    # حقل مطلوب في الواجهة (غير اختياري) وهو اختياري/غائب في الخادم
    risky = []
    for f_, opt in fields.items():
        if f_ in mod.model_fields and not opt and not mod.model_fields[f_].is_required() and mod.model_fields[f_].default is None:
            risky.append(f_)
    if a or b or risky:
        print(f'{name}: واجهة-فقط(الخادم لا يعيدها)={a} خادم-فقط(الواجهة لا تعرّفها)={b} واجهة-تعدّها-مضمونة-والخادم-قد-يعيد-null={risky}')
print(f'\nواجهات TS={len(ifaces)} مطابَقة بالاسم لنموذج خادم={matched} بلا نموذج بالاسم={len(no_model)}')
print('بلا نموذج بالاسم (تُراجَع يدوياً):', no_model)

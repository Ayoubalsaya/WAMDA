"""الوكيل ١ — الخريطة الثابتة: استدعاءات api في الواجهة مقابل مسارات app.routes الفعلية. قراءة فقط."""
import re,glob,json,sys,os
sys.path.insert(0,'.')
from fastapi.routing import APIRoute
from app.main import app
EXP={'/clients/${clientId}/portal/${action}':[f'/clients//portal/{a}' for a in('enable','invite','reset','disable','unlock')],
     '/periods/${action}':['/periods/close','/periods/reopen']}
PH=""
def norm(p):
    p=re.sub(r'\$\{[^}]*\}',PH,p); p=re.sub(r'\{[^}/]*\}',PH,p); return p.split('?')[0].rstrip('/') or '/'
def rx(p): return re.compile('^'+re.escape(norm(p)).replace(re.escape(PH),'[^/]+?')+'$')
routes=[]
for r in app.routes:
    if isinstance(r,APIRoute):
        for m in sorted(r.methods-{'HEAD','OPTIONS'}): routes.append((m,r.path,r))
calls=[]
for f in glob.glob('frontend/src/**/*.ts*',recursive=True):
    f=f.replace(chr(92),'/'); s=open(f,encoding='utf-8').read()
    for m in re.finditer(r'api\s*\.(get|post|put|patch)(?:<[^()]*?>)?\(\s*([`\'"])((?:\.|(?!\2).|\$\{[^}]*\})*?)\2',s,re.S):
        calls.append((f,s[:m.start()].count('\n')+1,m.group(1).upper(),m.group(3)))
    for m in re.finditer(r'[`\'"](/(?:documents|reports|portal)[^`\'"\s]*)[`\'"]',s):
        if re.search(r'api\s*\.\w+(<[^()]*?>)?\(\s*$',s[max(0,m.start()-60):m.start()]): continue
        calls.append((f,s[:m.start()].count('\n')+1,'GET',m.group(1)))
    for m in re.finditer(r'(?:url|path):\s*[`\'"](/operations/[a-z\-]+)[`\'"]',s):
        calls.append((f,s[:m.start()].count('\n')+1,'POST',m.group(1)))
used={};missing=[]
for f,l,meth,p in calls:
    for pp in EXP.get(p,[p]):
        pp2=norm(pp)
        hit=[(m,rp) for m,rp,r in routes if m==meth and rx(rp).match(pp2.replace(PH,'Z'))]
        if hit:
            for h in hit: used.setdefault(h,set()).add(f'{f}:{l}')
        else: missing.append((f,l,meth,p))
print('CALL SITES',len(calls),'MISSING',len(missing));[print(' ',x) for x in missing]
orph=[(m,p) for m,p,_ in routes if (m,p) not in used]
print('ROUTES',len(routes),'with UI caller',len(used),'without',len(orph))
for m,p in sorted(orph,key=lambda x:x[1]):print(' ',m,p)
json.dump({f'{m} {p}':sorted(v) for (m,p),v in used.items()},open('docs/audit/01_scripts/out/route_callers.json','w'),ensure_ascii=False,indent=1)

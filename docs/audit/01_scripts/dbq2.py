import os,re,sys
sys.path.insert(0,'.')
from dotenv import dotenv_values
base=os.environ.get("DATABASE_URL") or dotenv_values('.env')['DATABASE_URL']
url=re.sub(r"/([^/?]+)(\?.*)?$",lambda m:f"/{re.sub(r'(_db|_test)$','',m.group(1))}_test{m.group(2) or ''}",base)
os.environ['DATABASE_URL']=url
assert url.split('/')[-1].split('?')[0]=='wamda_test'
from sqlalchemy import text
from app.database import SessionLocal
db=SessionLocal()
for t in sys.argv[1:]:
    cols=db.execute(text("select column_name,data_type from information_schema.columns where table_name=:t order by ordinal_position"),{"t":t}).all()
    print(t,[c[0] for c in cols])
print(db.execute(text("select code,name_ar,currency_code from accounts where code like '5%' and code not like '%0' order by code limit 12")).all())
print(db.execute(text("select code,name_ar,currency_code,location_id from accounts where code like '14%' or code like '13%' or code like '11%' order by code limit 20")).all())
print(db.execute(text("select * from settings")).all())
print(db.execute(text("select * from periods")).all())

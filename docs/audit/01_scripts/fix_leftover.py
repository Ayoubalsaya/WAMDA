"""تنظيف بقايا تشغيلي التجريبيين على wamda_test (حساب بنك QA-ACC 15532 + صفا عدّاد ترقيم أنشأتُهما). محصور بالمعرّف."""
import os,re,sys
sys.path.insert(0,'.')
from dotenv import dotenv_values
base=os.environ.get("DATABASE_URL") or dotenv_values('.env')['DATABASE_URL']
url=re.sub(r"/([^/?]+)(\?.*)?$",lambda m:f"/{re.sub(r'(_db|_test)$','',m.group(1))}_test{m.group(2) or ''}",base)
os.environ['DATABASE_URL']=url
assert url.rsplit('/',1)[1].split('?')[0]=='wamda_test'
from sqlalchemy import text
from app.database import SessionLocal
db=SessionLocal()
assert db.execute(text("select name_ar from accounts where id=15532")).scalar()=='QA-ACC بنك تدقيق'
db.execute(text("delete from account_balances where account_id=15532"))
db.execute(text("delete from accounts where id=15532"))
db.execute(text("delete from account_number_counters where parent_id in (9,10)"))
db.commit()
print(db.execute(text("select (select count(*) from accounts where name_ar like 'QA-ACC%'),(select count(*) from account_number_counters)")).all())

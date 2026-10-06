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
for sql in sys.argv[1:]:
    print(sql[:80],'=>',db.execute(text(sql)).all())

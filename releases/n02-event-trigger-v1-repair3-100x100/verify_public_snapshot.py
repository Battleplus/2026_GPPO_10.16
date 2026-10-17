import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
inv=json.loads((root/'PUBLIC_ARCHIVE_INVENTORY.json').read_text(encoding='utf-8'))
bad=[]
for rel,item in inv['files'].items():
 p=root/rel
 if not p.is_file(): bad.append({'path':rel,'reason':'missing'}); continue
 a=hashlib.sha256(p.read_bytes()).hexdigest()
 if a!=item['sha256']: bad.append({'path':rel,'reason':'sha256','expected':item['sha256'],'actual':a})
print(json.dumps({'files':len(inv['files']),'bad':bad,'status':'PASS' if not bad else 'FAIL'},indent=2))
raise SystemExit(0 if not bad else 1)

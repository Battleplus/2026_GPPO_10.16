#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path, PurePosixPath
root = Path(__file__).resolve().parent
inventory_path = root / 'PUBLIC_SOURCE_INVENTORY.json'
inventory_bytes = inventory_path.read_bytes()
sidecar = (root / 'PUBLIC_SOURCE_INVENTORY.sha256').read_text(encoding='ascii').split()[0]
bad = []
if hashlib.sha256(inventory_bytes).hexdigest() != sidecar: bad.append('inventory sidecar mismatch')
inventory = json.loads(inventory_bytes)
expected = set()
for item in inventory.get('files', []):
    rel = PurePosixPath(item['public_path'])
    if rel.is_absolute() or '..' in rel.parts: bad.append('unsafe public path'); continue
    name = rel.as_posix(); expected.add(name); path = root.joinpath(*rel.parts)
    if not path.is_file(): bad.append('missing: ' + name); continue
    data = path.read_bytes()
    if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['public_sha256']: bad.append('hash/size mismatch: ' + name)
    if item['source_sha256'] != item['public_sha256']: bad.append('copy differs from source commitment: ' + name)
actual = {p.relative_to(root).as_posix() for p in (root / 'source').rglob('*') if p.is_file()}
if actual != expected: bad.append('source file set differs from inventory')
print(json.dumps({'status': 'PASS' if not bad else 'FAIL', 'source_files': len(expected), 'inventory_sha256': hashlib.sha256(inventory_bytes).hexdigest(), 'findings': bad}, indent=2))
raise SystemExit(0 if not bad else 1)

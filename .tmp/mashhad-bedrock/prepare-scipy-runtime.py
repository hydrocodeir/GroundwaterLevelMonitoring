"""Download a pinned browser-only scientific Python runtime; no user data."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import requests

BASE='https://cdn.jsdelivr.net/pyodide/v0.28.0/full/'
OUT=Path(__file__).resolve().parent/'scipy-runtime'
OUT.mkdir(exist_ok=True)
r=requests.get(BASE+'pyodide-lock.json',timeout=60)
r.raise_for_status()
lock=r.json()
(OUT/'pyodide-lock.json').write_bytes(r.content)
items=[(x,None) for x in ['pyodide.mjs','pyodide.asm.js','pyodide.asm.wasm','python_stdlib.zip']]
todo=['numpy','scipy']
seen=set()
while todo:
    key=todo.pop()
    if key in seen: continue
    seen.add(key)
    package=lock['packages'][key]
    items.append((package['file_name'],package['sha256']))
    todo.extend(package['depends'])

def download(item):
    name,sha=item
    target=OUT/name
    if target.exists() and (sha is None or hashlib.sha256(target.read_bytes()).hexdigest()==sha):
        return name+' cached'
    response=requests.get(BASE+name,timeout=180)
    response.raise_for_status()
    if sha and hashlib.sha256(response.content).hexdigest()!=sha:
        raise ValueError('Checksum mismatch: '+name)
    target.write_bytes(response.content)
    return name+' '+str(len(response.content))+' bytes'

with ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(download,items): print(result,flush=True)
print('Pyodide '+lock['info']['version'],flush=True)

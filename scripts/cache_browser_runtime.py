"""Bundle locked scientific runtime packages. File transport only; no user data processing."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]


def main():
    lock=json.loads((ROOT/'frontend/assets/pyodide/pyodide-lock.json').read_text())
    packages=lock['packages'];wanted=set()
    def visit(name):
        if name in wanted:return
        wanted.add(name)
        for dependency in packages[name].get('depends',[]):visit(dependency)
    for name in ('numpy','pandas','scipy','shapely','pyproj'):visit(name)
    target=ROOT/'frontend/assets/pyodide/packages';target.mkdir(exist_ok=True)
    def copy(name):
        item=packages[name];filename=item['file_name'];expected=item['sha256']
        destination=target/filename
        for path in (destination,ROOT/'.cache/waterq-runtime'/filename):
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:
                payload=path.read_bytes();break
        else:
            payload=urlopen('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/'+filename,timeout=90).read()
            assert hashlib.sha256(payload).hexdigest()==expected,filename
        destination.write_bytes(payload)
        return {'name':name,'file':filename,'sha256':expected,'bytes':len(payload)}
    with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(copy,sorted(wanted)))
    (target/'manifest.json').write_text(json.dumps({'pyodide_version':'0.29.3','source':'https://cdn.jsdelivr.net/pyodide/v0.29.3/full/','packages':records},indent=2),encoding='utf-8')
    print(json.dumps({'packages':len(records),'bytes':sum(r['bytes'] for r in records)}))


if __name__=='__main__':main()

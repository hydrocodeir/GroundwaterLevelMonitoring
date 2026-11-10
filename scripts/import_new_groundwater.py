"""Run browser-side groundwater import/audit. Host performs file I/O only."""
import json
import sys
import argparse
from datetime import datetime,timezone
import hashlib
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote,urlparse
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.tmp/newdata-import'


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        allowed=(path in {'/Data/NewData.csv','/Data/DATA.csv','/Data/LOCATION.csv','/Data/LOCATION.geojson','/Data/AQUIFER.geojson','/Data/NEW_DATA_IMPORT_REPORT.json','/Data/NEW_DATA_IMPORT_AUDIT.csv','/scripts/newdata_import_compute.py'}
                 or path.startswith('/.tmp/newdata-import/') or path.startswith('/frontend/assets/pyodide/'))
        if not allowed or '..' in path:
            self.send_error(404)
            return
        super().do_GET()
    def log_message(self,*args): pass


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--policy',type=Path,default=WORK/'policy.json')
    args=parser.parse_args()
    if args.verify and args.apply: parser.error('Choose either --apply or --verify')
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            page.set_default_timeout(180000)
            page.goto(f'http://127.0.0.1:{server.server_port}/.tmp/newdata-import/runner.html')
            if args.verify:
                page.evaluate("()=>run({command:'load-for-verification'})")
                verification=page.evaluate("()=>run({command:'verify'})")
                (ROOT/'Data/NEW_DATA_IMPORT_VERIFICATION.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(json.dumps(verification,ensure_ascii=False),flush=True)
                browser.close()
                return
            result=page.evaluate("()=>run({command:'audit'})")
            report=result['report']
            (WORK/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            (WORK/'review-summary.json').write_text(json.dumps(result['summary'],ensure_ascii=False,indent=2),encoding='utf-8')
            (WORK/'identity-plan.json').write_text(json.dumps(result['identities'],ensure_ascii=False,indent=2),encoding='utf-8')
            (WORK/'well-mapping.csv').write_text(result['identities']['mapping_csv'],encoding='utf-8')
            (WORK/'identity-review-details.json').write_text(json.dumps(result['details'],ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'rows':report['input_rows'],'wells':report['input_wells'],
                'initial_statuses':report['status_counts'],'identity_statuses':result['identities']['summary']['status_counts']},ensure_ascii=False),flush=True)
            if args.apply:
                policy=json.loads(args.policy.read_text(encoding='utf-8'))
                merged=page.evaluate("policy=>run({command:'merge',policy})",policy)
                if merged['blocked']:
                    (WORK/'unresolved-identities.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding='utf-8')
                    print(json.dumps(merged,ensure_ascii=False),flush=True)
                    return
                # Concurrency/integrity checks only: all scientific work above
                # ran in the browser. Abort if the source files changed meanwhile.
                checks={'NewData.csv':merged['report']['source_sha256'],'DATA.csv':merged['report']['input_data_sha256'],
                        'LOCATION.csv':merged['report']['input_location_sha256'],'LOCATION.geojson':merged['input_geo_sha256']}
                for name,expected in checks.items():
                    text=(ROOT/'Data'/name).read_bytes().decode('utf-8-sig')
                    if hashlib.sha256(text.encode('utf-8')).hexdigest()!=expected:
                        raise RuntimeError('Input changed during import; no data written: '+name)
                staged=WORK/'staged'
                staged.mkdir(exist_ok=True)
                artifacts={'DATA.csv':merged['data_csv'],'LOCATION.csv':merged['location_csv'],
                    'LOCATION.geojson':json.dumps(merged['location_geojson'],ensure_ascii=False,indent=2)+'\n',
                    'NEW_DATA_IMPORT_REPORT.md':merged['report_markdown'],
                    'NEW_DATA_IMPORT_REPORT.json':json.dumps(merged['report'],ensure_ascii=False,indent=2)+'\n',
                    'NEW_DATA_IMPORT_AUDIT.csv':merged['audit_csv'],'NEW_DATA_IMPORT_PENDING.csv':merged['pending_csv'],
                    'NEW_DATA_IMPORT_LOCATIONS.json':json.dumps(merged['location_changes'],ensure_ascii=False,indent=2)+'\n'}
                for name,content in artifacts.items():
                    (staged/name).write_text(content,encoding='utf-8',newline='')
                backup=WORK/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                backup.mkdir(parents=True,exist_ok=False)
                for name in ['DATA.csv','LOCATION.csv','LOCATION.geojson']:
                    shutil.copy2(ROOT/'Data'/name,backup/name)
                (backup/'policy.json').write_text(json.dumps(policy,ensure_ascii=False,indent=2),encoding='utf-8')
                committed=[]
                try:
                    for name in artifacts:
                        (staged/name).replace(ROOT/'Data'/name)
                        committed.append(name)
                except Exception:
                    for name in ['DATA.csv','LOCATION.csv','LOCATION.geojson']:
                        if name in committed: shutil.copy2(backup/name,ROOT/'Data'/name)
                    raise
                (WORK/'applied-identity-plan.json').write_text(json.dumps(merged['plans'],ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'import_complete':True,'report':merged['report'],'backup':str(backup)},ensure_ascii=False),flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__=='__main__': main()

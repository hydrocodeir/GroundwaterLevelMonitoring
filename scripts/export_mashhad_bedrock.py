"""Export Mashhad bedrock MSL from BEDROC depths + GEE SRTM.

The CLI now runs the validated continuous-surface workflow. Pass
--legacy-nearest explicitly to reproduce the superseded nearest-contour model.

Run from the project root: python scripts/export_mashhad_bedrock.py
Scientific processing and CSV generation run only in a browser Pyodide worker.
The host handles credentials, DEM byte downloads, static serving and file I/O.
Never sends credentials to the browser, a page artifact, or the output files.
"""
import argparse
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import time
from urllib.parse import urlparse

import ee
import requests
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
DEM=ROOT/'.tmp/mashhad-gee-dem'


class StaticHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        name=urlparse(self.path).path
        allowed=(name in {'/.tmp/BedRock.geojson','/Data/AQUIFER.geojson','/scripts/mashhad_bedrock_compute.py','/scripts/mashhad_bedrock_surface.py','/frontend/assets/js/aquifer3d_compute.py'}
                 or name.startswith('/frontend/assets/pyodide/')
                 or name.startswith('/.tmp/mashhad-bedrock/')
                 or name.startswith('/.tmp/mashhad-gee-dem/'))
        if not allowed or '..' in name:
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self,*args):
        pass


def download_dem(plan, credentials_path, geotiff=True):
    config=json.loads(credentials_path.read_text(encoding='utf-8'))
    if config.get('type')!='service_account' or not all(config.get(k) for k in ('client_email','private_key','project_id')):
        raise ValueError('Service-account credentials are incomplete')
    ee.Initialize(credentials=ee.ServiceAccountCredentials(config['client_email'],str(credentials_path)),project=config['project_id'])
    image=ee.Image(plan['dataset']).select(plan['band'])
    DEM.mkdir(parents=True,exist_ok=True)
    manifest=DEM/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')).get('plan')!=plan:
        raise ValueError('DEM cache belongs to another grid. Choose a fresh output directory before replacing it.')
    existing=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
    retrieved=existing.get('retrieved_utc',datetime.now(timezone.utc).isoformat())
    for tile in plan['tiles']:
        formats=[('NPY','.npy')]+([('GEO_TIFF','.tif')] if geotiff else [])
        for fmt,suffix in formats:
            target=DEM/(tile['id']+suffix)
            if target.exists() and target.stat().st_size>1000:
                print('Cached DEM '+target.name,flush=True)
                continue
            params=dict(bands=[plan['band']],crs=tile['crs'],crs_transform=tile['transform'],
                        dimensions=[tile['width'],tile['height']],format=fmt,filePerBand=False)
            for attempt in range(3):
                try:
                    url=image.getDownloadURL(params)
                    response=requests.get(url,timeout=(30,240))
                    if response.status_code!=200:
                        raise RuntimeError('GEE DEM HTTP '+str(response.status_code))
                    temporary=target.with_suffix(target.suffix+'.part')
                    temporary.write_bytes(response.content)
                    temporary.replace(target)
                    print('Downloaded DEM '+target.name+' ('+str(target.stat().st_size)+' bytes)',flush=True)
                    break
                except Exception as error:
                    if attempt==2:
                        # Do not print signed URLs, access tokens, or credentials.
                        raise RuntimeError('DEM download failed for '+tile['id']+' '+fmt+' ('+type(error).__name__+')') from None
                    time.sleep(2)
    manifest.write_text(json.dumps(dict(plan=plan,retrieved_utc=retrieved,asset=plan['dataset'],
        grid_origin='pixel corners',formats=['NPY','GEO_TIFF'] if geotiff else ['NPY']),indent=2),encoding='utf-8')
    return retrieved


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials',type=Path,default=ROOT/'ee-hydrocode.json')
    parser.add_argument('--skip-geotiff',action='store_true')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(StaticHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            page.set_default_timeout(300000)
            page.goto(f'http://127.0.0.1:{server.server_port}/.tmp/mashhad-bedrock/msl-runner.html')
            prepared=page.evaluate("() => runStep({command:'prepare'})")
            print(json.dumps(prepared['summary'],ensure_ascii=True),flush=True)
            plan=prepared['plan']
            (ROOT/'.tmp/mashhad-bedrock/msl-plan.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2),encoding='utf-8')
            retrieved=download_dem(plan,args.credentials,not args.skip_geotiff)
            result=page.evaluate("args => runStep({command:'finish',...args})",dict(plan=plan,retrieved=retrieved))
            # These are already-completed file contents generated in the client.
            files={'MASHHAD_BEDROCK_MSL.csv':result['csv'],
                   'MASHHAD_BEDROCK_MSL.audit.csv':result['audit'],
                   'MASHHAD_BEDROCK_DEPTH_SOURCE.csv':result['source'],
                   'MASHHAD_BEDROCK_MSL.csv.metadata.json':json.dumps(result['metadata'],ensure_ascii=False,indent=2)+'\n',
                   'MASHHAD_BEDROCK_BOUNDARY.geojson':json.dumps(result['boundary'],ensure_ascii=False,indent=2)+'\n'}
            for name,content in files.items():
                (ROOT/'Data'/name).write_text(content,encoding='utf-8',newline='')
            (ROOT/'.tmp/mashhad-bedrock/msl-preview.json').write_text(json.dumps(result['preview'],ensure_ascii=False),encoding='utf-8')
            # Parse the exported CSV using the application's actual upload parser,
            # executed in a separate browser-side Python namespace.
            validation=page.evaluate("csv => runStep({command:'validate-upload',csv})",result['csv'])
            page.goto(f'http://127.0.0.1:{server.server_port}/.tmp/mashhad-bedrock/msl-report.html')
            page.wait_for_function('window.REPORT_READY',timeout=60000)
            report=page.evaluate('''async()=>{
              const [html,lib,code,data]=await Promise.all(['msl-report.html','plotly.min.js','msl-report.js','msl-preview.json'].map(async p=>(await fetch(p)).text()));
              const safe=s=>s.replace(/<\\/script/gi,'<\\\\/script');
              return html.replace('<script id="plotly-library" src="plotly.min.js"></script>',()=>'<script>'+safe(lib)+'</script>')
                .replace('<script id="report-code" src="msl-report.js"></script>',()=>'<script>window.MASHHAD_MSL='+safe(data)+';</script><script>'+safe(code)+'</script>');
            }''')
            report_path=ROOT/'.tmp/mashhad-bedrock-msl.html'
            report_path.write_text(report,encoding='utf-8')
            page.set_viewport_size({'width':1440,'height':1120})
            page.goto(report_path.as_uri())
            page.wait_for_function('window.REPORT_READY',timeout=60000)
            page.screenshot(path=str(ROOT/'.tmp/mashhad-bedrock-msl.png'),full_page=True)
            print('Saved offline map and 3D report',flush=True)
            print(json.dumps(dict(files=list(files),upload_validation=validation,metadata=result['metadata']),ensure_ascii=True),flush=True)
            browser.close()
    finally:
        server.shutdown()


if __name__=='__main__':
    import sys
    if '--legacy-nearest' in sys.argv:
        sys.argv.remove('--legacy-nearest')
        main()
    else:
        from export_mashhad_surface import main as continuous_main
        continuous_main()

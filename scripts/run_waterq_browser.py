"""Local file transport and static serving only; all analysis executes in Pyodide."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import zipfile
import io
from urllib.request import urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


class StaticHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/':
            content=b'<!doctype html><html><meta charset="utf-8"><title>Local water quality analysis</title></html>'
            self.send_response(200);self.end_headers();self.wfile.write(content);return
        if path=='/runtime/python-stdlib':
            target=ROOT/'frontend/assets/pyodide/python_stdlib.zip'
        elif path.startswith('/packages/'):
            target=(ROOT/'.cache/waterq-runtime'/Path(path).name).resolve()
        elif path.startswith('/frontend/assets/'):
            target=(ROOT/path.lstrip('/')).resolve()
            if not target.is_relative_to(ROOT/'frontend/assets'):
                self.send_error(404);return
        else:
            self.send_error(404);return
        if not target.is_file():
            self.send_error(404);return
        mime='text/javascript' if target.suffix in ('.js','.mjs') else 'application/wasm' if target.suffix=='.wasm' else 'application/octet-stream'
        data=target.read_bytes();self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):
        pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audit-only',action='store_true');parser.add_argument('--aquifer',default='مشهد');parser.add_argument('--drinking-ec',type=float,default=1500);parser.add_argument('--irrigation-ec',type=float,default=3000);parser.add_argument('--depth-ratio',type=float,default=1);args=parser.parse_args()
    output=ROOT/'outputs/water_quality';output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),StaticHandler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        lock=json.loads((ROOT/'frontend/assets/pyodide/pyodide-lock.json').read_text())
        cache=ROOT/'.cache/waterq-runtime';cache.mkdir(parents=True,exist_ok=True)
        for name in ('numpy','shapely','certifi','pyproj','libopenblas','scipy'):
            filename=lock['packages'][name]['file_name'];target=cache/filename
            expected=lock['packages'][name]['sha256']
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
                print('Caching package: '+name,flush=True)
                existing=ROOT/'.tmp/mashhad-bedrock/scipy-runtime'/filename
                if existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest()==expected:
                    target.write_bytes(existing.read_bytes());continue
                with urlopen('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/'+filename,timeout=90) as response:
                    target.write_bytes(response.read())
                if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise ValueError('Package hash mismatch: '+name)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page()
            page.on('console',lambda message:print(message.text[:220],flush=True))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate("""async()=>{
              const {loadBrowserPython}=await import('/frontend/assets/js/pyodide-runtime.js');
              window.py=await loadBrowserPython({packageBaseUrl:location.origin+'/packages/'});
              await py.loadPackage(['numpy','shapely','pyproj','scipy']);
            }""")
            print('Pyodide packages ready',flush=True)
            page.evaluate('code=>py.runPython(code)',(ROOT/'scripts/waterq_compute.py').read_text(encoding='utf-8'))
            page.evaluate('inputs=>{for(const [k,v] of Object.entries(inputs))py.globals.set(k,v)}',{
                '_quality_text':(ROOT/'Data/WaterQ.csv').read_text(encoding='utf-8-sig'),
                '_aquifers':(ROOT/'Data/AQUIFER.geojson').read_text(encoding='utf-8')})
            result=json.loads(page.evaluate("py.runPython('json.dumps(audit_quality(_quality_text,_aquifers),ensure_ascii=False,allow_nan=False)')"))
            (output/'WATERQ_AUDIT.json').write_text(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False,indent=2),encoding='utf-8')
            (output/'WATERQ_NORMALIZED.json').write_text(json.dumps(result['records'],ensure_ascii=False),encoding='utf-8')
            print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=True),flush=True)
            if not args.audit_only:
                print('Building aquifer and calibrating quality models in Pyodide',flush=True)
                page.evaluate('code=>py.runPython(code)',(ROOT/'frontend/assets/js/aquifer3d_compute.py').read_text(encoding='utf-8'))
                page.evaluate('inputs=>{for(const [k,v] of Object.entries(inputs))py.globals.set(k,v)}',{
                    '_locations_text':(ROOT/'Data/LOCATION.csv').read_text(encoding='utf-8'),
                    '_measurements_text':(ROOT/'Data/DATA.csv').read_text(encoding='utf-8'),
                    '_mashhad_floor':(ROOT/'Data/MASHHAD_BEDROCK_MSL.csv').read_text(encoding='utf-8'),
                    '_ney_floor':(ROOT/'Data/NEYSHABUR_BEDROCK_DEPTH.csv').read_text(encoding='utf-8'),
                    '_sy_map':(ROOT/'Data/MASHHAD_SY/MASHHAD_SY_PRIOR.csv').read_text(encoding='utf-8') if args.aquifer=='مشهد' else '',
                    '_geology_text':(ROOT/'Data/WaterQ_Sources/MASHHAD_GLIM.geojson').read_text(encoding='utf-8'),
                    '_raster_b64':base64.b64encode((ROOT/'Data/WaterQ_Sources/MASHHAD_GEE_COVARIATES.npy').read_bytes()).decode('ascii'),
                    '_aquifer_name':args.aquifer,
                    '_quality_options':json.dumps({'drinking_ec':args.drinking_ec,'irrigation_ec':args.irrigation_ec,'depth_ratio':args.depth_ratio})})
                page.evaluate('value=>py.globals.set("_source_metadata_json",value)',(ROOT/'Data/WaterQ_Sources/MASHHAD_WATERQ_SOURCE_METADATA.json').read_text(encoding='utf-8'))
                page.evaluate('source=>py.globals.set("_tiff_source",source)',(ROOT/'scripts/mashhad_sy_compute.py').read_text(encoding='utf-8'))
                encoded=page.evaluate("""()=>py.runPython(`
import base64
initialize(_aquifers,_locations_text,_measurements_text,_ney_floor,_mashhad_floor)
_fi=next(i for i,f in enumerate(_features) if f['properties']['AQUIFER']==_aquifer_name)
_summary=prepare(_fi)
_analysis=analyze(_fi,_summary['years'][0]['year'],.06,sy_text=_sy_map)
_records=audit_quality(_quality_text,_aquifers)['records']
_options=json.loads(_quality_options)
_options['source_metadata']=json.loads(_source_metadata_json)
_options['volume_input_files']={'bedrock':_analysis['grid']['bedrock_source'],'sy':'MASHHAD_SY_PRIOR.csv' if _sy_map else 'constant'}
_quality=estimate_quality(_analysis,_records,base64.b64decode(_raster_b64),_geology_text,_options)
_tiff_module={}
exec(_tiff_source,_tiff_module)
quality_archive(_quality,_tiff_module['geotiff'])
`)""")
                data=base64.b64decode(encoded)
                (output/'MASHHAD_WATERQ_ESTIMATE.zip').write_bytes(data)
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for item in archive.infolist():
                        destination=(output/item.filename).resolve()
                        if not destination.is_relative_to(output.resolve()):raise ValueError('Unsafe archive member')
                        destination.write_bytes(archive.read(item))
                summary=json.loads((output/'WATERQ_ESTIMATE.json').read_text(encoding='utf-8'))
                print(json.dumps(summary,ensure_ascii=True),flush=True)
            browser.close()
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':main()

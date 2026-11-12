"""Transport and save only: raster decoding, georeferencing and CSV conversion in Pyodide."""
import argparse
import hashlib
import json
from pathlib import Path
import threading
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
from run_waterq_browser import StaticHandler, ROOT
from http.server import ThreadingHTTPServer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',default='Data/Mashhad.tif')
    parser.add_argument('--output',default='Data/Subsidence/Mashhad_cumulative.csv')
    parser.add_argument('--start',type=int,required=True);parser.add_argument('--end',type=int,required=True)
    parser.add_argument('--duration',type=float,required=True)
    parser.add_argument('--unit',choices=['mm','cm','m'],required=True)
    parser.add_argument('--component',choices=['vertical','los'],required=True)
    parser.add_argument('--direction',choices=['up','down'],required=True)
    parser.add_argument('--calendar',choices=['persian','water_year'],default='persian')
    args=parser.parse_args();source=(ROOT/args.input).resolve();output=(ROOT/args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    class Handler(StaticHandler):
        def do_GET(self):
            if self.path=='/input.tif':
                data=source.read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            else:super().do_GET()
    lock=json.loads((ROOT/'frontend/assets/pyodide/pyodide-lock.json').read_text())['packages']
    cache=ROOT/'.cache/waterq-runtime';cache.mkdir(parents=True,exist_ok=True)
    for name in ('numpy','pillow','pyproj','certifi'):
        item=lock[name];target=cache/item['file_name']
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:
            with urlopen('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/'+item['file_name'],timeout=90) as response:target.write_bytes(response.read())
            if hashlib.sha256(target.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Runtime package hash mismatch.')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(accept_downloads=True)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate("""async()=>{const {loadBrowserPython}=await import('/frontend/assets/js/pyodide-runtime.js');window.py=await loadBrowserPython({packageBaseUrl:location.origin+'/packages/'});await py.loadPackage(['numpy','pillow','pyproj']);py.FS.writeFile('/input.tif',new Uint8Array(await(await fetch('/input.tif')).arrayBuffer()));}""")
            page.evaluate('code=>py.runPython(code)',(ROOT/'frontend/assets/js/subsidence-raster-convert.py').read_text(encoding='utf-8'))
            declaration={'unit':args.unit,'direction':args.direction,'component':args.component,'calendar_basis':args.calendar,'start_year':args.start,'end_year':args.end,'duration_years':args.duration}
            page.evaluate('d=>py.globals.set("_declaration",JSON.stringify(d))',declaration)
            metadata=json.loads(page.evaluate("py.runPython(\"json.dumps(convert_subsidence_tiff('/input.tif','/output.csv',json.loads(_declaration)),allow_nan=False)\")"))
            with page.expect_download() as dl:
                page.evaluate("""()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([py.FS.readFile('/output.csv')],{type:'text/csv'}));a.download='pixels.csv';a.click();}""")
            dl.value.save_as(output)
            metadata['source_file']=args.input;metadata['csv_file']=output.name
            output.with_suffix('.metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'csv':str(output.relative_to(ROOT)),'statistics':metadata['statistics'],'extent':metadata['extent_wgs84']},ensure_ascii=False))
            browser.close()
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()

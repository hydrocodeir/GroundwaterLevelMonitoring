"""Transport public sources; all GIS selection and reprojection execute in browser Pyodide."""
import hashlib
import json
from pathlib import Path
from http.server import ThreadingHTTPServer
import threading
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
from run_waterq_browser import ROOT, StaticHandler


def main():
    cache = ROOT/'.cache/waterq-runtime'
    cache.mkdir(parents=True, exist_ok=True)
    packages = json.loads((ROOT/'frontend/assets/pyodide/pyodide-lock.json').read_text())['packages']
    names = set()
    def add(name):
        if name in names:
            return
        names.add(name)
        item = packages[name]
        for dep in item.get('depends', []):
            add(dep)
        path = cache/item['file_name']
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            path.write_bytes(urlopen('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/'+item['file_name'], timeout=90).read())
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    for name in ('sqlite3', 'numpy', 'shapely', 'pyproj'):
        add(name)
    class Handler(StaticHandler):
        def do_GET(self):
            sources={'/cities.zip': ROOT/'.cache/GHS_UCDB_CENTRAL_SOUTHERN_ASIA_V1_2.zip',
                     '/provinces.geojson':ROOT/'Data/UrbanSources/geoBoundaries-IRN-ADM1.geojson',
                     '/osm.json':ROOT/'Data/UrbanSources/osm-cities-towns.json'}
            if self.path in sources:
                payload=sources[self.path].read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            else:
                super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(accept_downloads=True)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate("""async()=>{
              const {loadBrowserPython}=await import('/frontend/assets/js/pyodide-runtime.js');
              window.py=await loadBrowserPython({packageBaseUrl:location.origin+'/packages/'});
              await py.loadPackage(['sqlite3','numpy','shapely','pyproj']);
              for(const [url,path] of [['/cities.zip','/cities.zip'],['/provinces.geojson','/provinces.geojson'],['/osm.json','/osm.json']])py.FS.writeFile(path,new Uint8Array(await(await fetch(url)).arrayBuffer()));
            }""")
            page.evaluate('labels=>py.globals.set("_labels_json",JSON.stringify(labels))',json.loads((ROOT/'Data/UrbanSources/city-labels.fa.json').read_text(encoding='utf-8')))
            code=(ROOT/'scripts/urban_layer_prepare.py').read_text(encoding='utf-8')
            result=json.loads(page.evaluate('code=>py.runPython(code)',code))
            print(json.dumps(result,ensure_ascii=True),flush=True)
            for virtual,target in [('/cities.geojson',ROOT/'frontend/assets/data/khorasan-razavi-urban.geojson'),('/cities.metadata.json',ROOT/'Data/UrbanSources/khorasan-razavi-urban.metadata.json')]:
                if not page.evaluate('p=>py.FS.analyzePath(p).exists',virtual):
                    continue
                target.parent.mkdir(parents=True,exist_ok=True)
                with page.expect_download() as dl:
                    page.evaluate("p=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([py.FS.readFile(p)]));a.download='output.json';a.click();}",virtual)
                dl.value.save_as(target)
            browser.close()
    finally:
        server.shutdown();server.server_close()


if __name__=='__main__':main()

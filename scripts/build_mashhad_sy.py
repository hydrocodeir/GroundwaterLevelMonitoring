"""Fetch public source bytes; run numerical processing in a local Pyodide worker.

The HTTP service serves files only. No analysis or uploaded data endpoint exists.
"""
import base64
import functools
import http.server
import json
import threading
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'.cache/sy-research'
RUNNER = CACHE/'runner'
OUTPUT = ROOT/'Data/MASHHAD_SY'
SOURCES = ['soilgrids_sy_7_integrate.nc','GSDE_sy_2-integrate.nc']


def source_bytes(url, begin, end, destination):
    size = end-begin+1
    if destination.exists() and destination.stat().st_size == size:
        print('Reusing source range',destination.name,size,flush=True)
        return
    with requests.get(url,headers={'Range':f'bytes={begin}-{end}'},stream=True,timeout=180) as response:
        response.raise_for_status()
        if response.status_code != 206 or response.headers.get('Content-Range','').split('/')[0] != f'bytes {begin}-{end}':
            raise RuntimeError('Source server did not honour the requested byte range.')
        with destination.open('wb') as stream:
            for chunk in response.iter_content(1024*1024):
                stream.write(chunk)
    if destination.stat().st_size != size:
        raise RuntimeError('Incomplete source download.')


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self,path):
        clean = path.split('?')[0]
        if clean == '/runtime/python-stdlib':
            return str(ROOT/'frontend/assets/pyodide/python_stdlib.zip')
        if clean.startswith('/assets/'):
            return str(ROOT/'frontend'/clean.lstrip('/'))
        return super().translate_path(path)

    def log_message(self,*args):
        pass


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    RUNNER.mkdir(parents=True,exist_ok=True)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for source in SOURCES:
        url=f'https://zenodo.org/api/records/14216083/files/{source}/content'
        source_bytes(url,0,300000,CACHE/(source+'.header'))
    (RUNNER/'index.html').write_text('''<!doctype html><meta charset="utf-8"><title>Mashhad Sy scientific build</title><script>
    const worker=new Worker('worker.js',{type:'module'});
    window.step=(command,args={})=>new Promise((resolve,reject)=>{
      worker.onmessage=({data})=>{if(data.progress){console.log(data.progress);return;}data.error?reject(Error(data.error)):resolve(data.result)};
      worker.onerror=e=>reject(Error(e.message));worker.postMessage({command,...args});
    });</script>''',encoding='utf-8')
    (RUNNER/'worker.js').write_text('''import {loadBrowserPython,version} from '/assets/js/pyodide-runtime.js';
    let py;
    const progress=message=>self.postMessage({progress:message});
    self.onmessage=async({data})=>{try{
      let result;
      if(data.command==='plan'){
        py=await loadBrowserPython({packageBaseUrl:`https://cdn.jsdelivr.net/pyodide/v${version}/full/`});
        await py.loadPackage(['numpy','shapely']);
        await py.runPythonAsync(await (await fetch('/scripts/mashhad_sy_compute.py')).text());
        py.globals.set('_geo',await(await fetch('/Data/AQUIFER.geojson')).text());
        for(const name of data.sources){
          py.FS.writeFile('/'+name+'.header',new Uint8Array(await(await fetch('/.cache/sy-research/'+name+'.header')).arrayBuffer()));
        }
        py.globals.set('_source_names',JSON.stringify(data.sources));
        result=JSON.parse(await py.runPythonAsync(`
_feature=next(f for f in json.loads(_geo)['features'] if f['properties'].get('AQUIFER')=='مشهد')
_plans={name:source_plan(open('/'+name+'.header','rb').read(),_feature) for name in json.loads(_source_names)}
json.dumps({name:{k:p[k] for k in ['byte_begin','byte_end','block_shape','selected']} for name,p in _plans.items()})`));
      }else if(data.command==='build'){
        progress('Loading plotting library');await py.loadPackage('matplotlib');
        for(const name of data.sources){
          progress('Reading regional source slab '+name);
          py.FS.writeFile('/'+name+'.slab',new Uint8Array(await(await fetch('/.cache/sy-research/'+name+'.slab')).arrayBuffer()));
        }
        py.globals.set('_retrieved',data.retrieved);
        progress('Building native-resolution Sy products and area weights');
        result=JSON.parse(await py.runPythonAsync(`
_soil=decode_window(_plans['soilgrids_sy_7_integrate.nc'],open('/soilgrids_sy_7_integrate.nc.slab','rb').read())
_gsde=decode_window(_plans['GSDE_sy_2-integrate.nc'],open('/GSDE_sy_2-integrate.nc.slab','rb').read())
_metadata=build(_soil,_gsde,_feature,'/output')
_metadata['retrieved_utc']=_retrieved
_metadata['source_byte_ranges']={name:[p['byte_begin'],p['byte_end']] for name,p in _plans.items()}
_metadata['source_global_metadata']={name:p['metadata'] for name,p in _plans.items()}
open('/output/MASHHAD_SY_METADATA.json','w').write(json.dumps(_metadata,ensure_ascii=False,indent=2))
json.dumps(_metadata,ensure_ascii=False)`));
        progress('Validating dashboard Sy CSV and spatial coverage');
        py.globals.set('_app_src',await(await fetch('/frontend/assets/js/aquifer3d_compute.py')).text());
        const validation=JSON.parse(await py.runPythonAsync(`
_ns={};exec(_app_src,_ns)
_csv=open('/output/MASHHAD_SY_PRIOR.csv').read()
_points=_ns['_sy_points'](_csv)
_hull=_ns['_convex_hull'](_points)
_polys=_ns['_polygons'](_feature)
_w,_s,_e,_n=_ns['_extent'](_polys)
_inside=[(_w+(i+.5)*(_e-_w)/38,_s+(j+.5)*(_n-_s)/38) for j in range(38) for i in range(38)]
_inside=[p for p in _inside if _ns['_contains'](_polys,*p)]
_covered=sum(_ns['_ring_contains'](_hull,*p) for p in _inside)
assert _covered==len(_inside),'Dashboard Sy hull does not cover calculation cells'
json.dumps({'csv_accepted_points':len(_points),'dashboard_cells_inside':len(_inside),'cells_inside_csv_hull':_covered})`));
        result.dashboard_validation=validation;
        py.globals.set('_validation',JSON.stringify(validation));
        await py.runPythonAsync("_metadata['dashboard_validation']=json.loads(_validation)\\nopen('/output/MASHHAD_SY_METADATA.json','w').write(json.dumps(_metadata,ensure_ascii=False,indent=2))");
      }else if(data.command==='file'){
        const bytes=py.FS.readFile('/output/'+data.name);let text='';
        for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode(...bytes.subarray(i,i+32768));
        result=btoa(text);
      }
      self.postMessage({result});
    }catch(error){self.postMessage({error:String(error.stack||error)});}};''',encoding='utf-8')
    handler=functools.partial(Handler,directory=str(ROOT))
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as playwright:
            context=playwright.chromium.launch_persistent_context(str(CACHE/'browser-profile'),headless=True)
            page=context.pages[0]
            page.on('console',lambda message:print('BROWSER',message.text[:200],flush=True))
            page.goto(f'http://127.0.0.1:{server.server_port}/{RUNNER.relative_to(ROOT).as_posix()}/index.html')
            plans=page.evaluate('sources=>step("plan",{sources})',SOURCES)
            (CACHE/'source-range-plan.json').write_text(json.dumps(plans,indent=2))
            for name,plan in plans.items():
                print('Fetching regional range',name,plan['byte_end']-plan['byte_begin']+1,plan['block_shape'],flush=True)
                source_bytes(f'https://zenodo.org/api/records/14216083/files/{name}/content',plan['byte_begin'],plan['byte_end'],CACHE/(name+'.slab'))
            from datetime import datetime,timezone
            result=page.evaluate('args=>step("build",args)',{'sources':SOURCES,'retrieved':datetime.now(timezone.utc).isoformat()})
            (CACHE/'build-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            for name in ['MASHHAD_SY_PRIOR.tif','MASHHAD_SY_SOIL_REFERENCE.tif','MASHHAD_SY_PRIOR.csv','MASHHAD_SY_AUDIT.csv','MASHHAD_SY_METADATA.json','MASHHAD_SY_PREVIEW.png']:
                encoded=page.evaluate('name=>step("file",{name})',name)
                (OUTPUT/name).write_bytes(base64.b64decode(encoded))
                print('SAVED',name,(OUTPUT/name).stat().st_size,flush=True)
            print(json.dumps({k:result[k] for k in ['scenario_range','scenario_weighted_mean','raw_soil_range','valid_area_coverage_fraction','pixels_missing_both_sources','csv_record_count','dashboard_validation']},ensure_ascii=False),flush=True)
            context.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__=='__main__':
    main()

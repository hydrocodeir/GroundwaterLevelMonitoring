"""Fetch explicitly requested public GEE climate; build/validate CSV in Pyodide.

Credentials remain on the host. The local HTTP server serves only static files;
it has no analysis or uploaded-data endpoint. No piezometer/quality data is read.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread
import time
from urllib.parse import unquote, urlparse

import ee
from playwright.sync_api import sync_playwright
from export_monthly_ndvi import initialize_earth_engine

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.cache/mashhad-climate-gee'
OUTPUT=ROOT/'Data/MASHHAD_CLIMATE'
DATASETS={'precip':('UCSB-CHG/CHIRPS/DAILY','precipitation'),'temp':('ECMWF/ERA5_LAND/DAILY_AGGR','temperature_2m')}

WORKER="""import {loadBrowserPython} from '/assets/js/pyodide-runtime.js';
let py;
self.onmessage=async({data})=>{try{
  if(!py){
    py=await loadBrowserPython();
    for(const name of ['jdatetime','jalali_core']){
      py.FS.mkdir('/home/pyodide/'+name);
      py.FS.writeFile('/home/pyodide/'+name+'/__init__.py',await(await fetch('/deps/'+name+'.py')).text());
    }
    await py.runPythonAsync(await(await fetch('/compute.py')).text());
  }
  py.globals.set('_request_json',JSON.stringify(data));
  let result;
  if(data.command==='plan'){
    py.globals.set('_geojson',await(await fetch('/boundary.geojson')).text());
    result=JSON.parse(py.runPython("_a=json.loads(_request_json)\\n_plan=plan_climate(json.loads(_geojson),_a['catalog'],start_wy=_a.get('start_wy'),end_wy=_a.get('end_wy'))\\njson.dumps(_plan,ensure_ascii=False)"));
  }else if(data.command==='finish'){
    py.globals.set('_app_source',await(await fetch('/lifetime.py')).text());
    result=JSON.parse(py.runPython("_a=json.loads(_request_json)\\njson.dumps(build_climate(_plan,_a['raw'],_a['retrieved'],_app_source),ensure_ascii=False,allow_nan=False)"));
  }else throw Error('Unknown command');
  self.postMessage({result});
}catch(error){self.postMessage({error:error.message||String(error)});}};"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=='/':
            data=b'''<!doctype html><meta charset="utf-8"><title>Mashhad climate build</title><script>
            const worker=new Worker('/worker.js',{type:'module'});
            window.step=(command,args={})=>new Promise((resolve,reject)=>{
              worker.onmessage=({data})=>data.error?reject(Error(data.error)):resolve(data.result);
              worker.onerror=e=>reject(Error(e.message));worker.postMessage({command,...args});});</script>'''
            mime='text/html'
        elif path=='/worker.js':data=WORKER.encode();mime='text/javascript'
        else:
            targets={'/compute.py':ROOT/'scripts/climate_gee_compute.py','/lifetime.py':ROOT/'frontend/assets/js/aquifer-lifetime-compute.py',
                     '/boundary.geojson':ROOT/'Data/AQUIFER.geojson','/runtime/python-stdlib':ROOT/'frontend/assets/pyodide/python_stdlib.zip',
                     '/deps/jdatetime.py':CACHE/'jdatetime.py','/deps/jalali_core.py':CACHE/'jalali_core.py'}
            target=targets.get(path)
            if path.startswith('/assets/'):
                candidate=(ROOT/'frontend'/path.lstrip('/')).resolve()
                if candidate.is_relative_to(ROOT/'frontend/assets'):target=candidate
            if target is None or not target.is_file():self.send_error(404);return
            data=target.read_bytes()
            mime='text/javascript' if target.suffix in ('.mjs','.js') else 'application/wasm' if target.suffix=='.wasm' else 'application/octet-stream'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def log_message(self,*args):pass


def collection_catalog():
    result={}
    for key,(dataset,band) in DATASETS.items():
        collection=ee.ImageCollection(dataset).select(band)
        result[key]=ee.Dictionary({'first':ee.Date(collection.aggregate_min('system:time_start')).format('YYYY-MM-dd'),
                                  'last':ee.Date(collection.aggregate_max('system:time_start')).format('YYYY-MM-dd'),
                                  'projection':ee.Image(collection.first()).projection()}).getInfo()
        result[key].update(collection=dataset,band=band)
    return result


def source_record(period, region, catalog):
    props=dict(period)
    for key,(dataset,band) in DATASETS.items():
        collection=ee.ImageCollection(dataset).select(band)
        selected=collection.filterDate(period['start'],period['end_exclusive'])
        values=selected.sum() if key=='precip' else selected.mean()
        projection=catalog[key]['projection']
        area=ee.Image.pixelArea()
        stack=ee.Image.cat(values.multiply(area).rename('value_area'),area.updateMask(values.mask()).rename('valid_area'),
                           area.rename('total_area'),selected.count().rename('days'))
        stats=stack.reduceRegion(reducer=ee.Reducer.sum().combine(ee.Reducer.minMax(),sharedInputs=True),geometry=region,
                                 crs=projection['crs'],crsTransform=projection['transform'],maxPixels=1000000,tileScale=2)
        props.update({key+'_stats':stats,key+'_images':selected.size(),key+'_unique_days':selected.aggregate_count_distinct('system:time_start')})
    return ee.Feature(None,props)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials',type=Path,default=ROOT/'ee-hydrocode.json')
    parser.add_argument('--start-wy',type=int);parser.add_argument('--end-wy',type=int)
    parser.add_argument('--batch-years',type=int,default=3);parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    if not 1<=args.batch_years<=5:raise ValueError('Batch size must be 1..5 years.')
    CACHE.mkdir(parents=True,exist_ok=True);OUTPUT.mkdir(parents=True,exist_ok=True)
    # Pure-Python dependencies are transported locally into browser memory, never credentials.
    for name in ('jdatetime','jalali_core'):
        (CACHE/(name+'.py')).write_bytes(Path(importlib.util.find_spec(name).origin).read_bytes())
    initialize_earth_engine(args.credentials);ee.data.setDeadline(180000)
    catalog=collection_catalog()
    print(json.dumps({'source_availability':{k:[v['first'],v['last']] for k,v in catalog.items()}}),flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page()
            page.set_default_timeout(180000)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            plan=page.evaluate("args=>step('plan',args)",{'catalog':catalog,'start_wy':args.start_wy,'end_wy':args.end_wy})
            (OUTPUT/'GEE_PLAN.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf-8')
            signature=hashlib.sha256(json.dumps({k:plan[k] for k in ('boundary_sha256','periods','sources')},sort_keys=True).encode()).hexdigest()
            rawfile=CACHE/(signature+'.json')
            raw=json.loads(rawfile.read_text('utf-8')) if rawfile.is_file() and not args.refresh else []
            existing={r['water_year'] for r in raw}
            missing=[v for v in plan['periods'] if v['water_year'] not in existing]
            region=ee.Geometry(plan['feature']['geometry'])
            print(json.dumps({'planned_water_years':[plan['periods'][0]['water_year'],plan['periods'][-1]['water_year']],
                              'records':len(plan['periods']),'cached':len(raw),'boundary_sha256':plan['boundary_sha256']}),flush=True)
            for start in range(0,len(missing),args.batch_years):
                batch=missing[start:start+args.batch_years]
                for attempt in range(3):
                    try:
                        response=ee.FeatureCollection([source_record(period,region,catalog) for period in batch]).getInfo();break
                    except Exception:
                        if attempt==2:raise
                        time.sleep(2*(attempt+1))
                stamp=datetime.now(timezone.utc).isoformat()
                for feature in response['features']:
                    raw.append({**feature['properties'],'retrieved_utc':stamp})
                rawfile.write_text(json.dumps(raw,ensure_ascii=False),'utf-8')
                print(f"GEE complete: WY {batch[0]['water_year']}..{batch[-1]['water_year']} ({len(raw)}/{len(plan['periods'])})",flush=True)
            raw.sort(key=lambda r:r['water_year'])
            retrieved=datetime.now(timezone.utc).isoformat()
            result=page.evaluate("args=>step('finish',args)",{'raw':raw,'retrieved':retrieved})
            for name,text in result['files'].items():
                (OUTPUT/name).write_text(text,encoding='utf-8',newline='')
            (OUTPUT/'GEE_RAW.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),'utf-8')
            (OUTPUT/'BUILD_PROVENANCE.json').write_text(json.dumps({'plan_signature':signature,'retrieved_utc':retrieved,
                'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('scripts/export_mashhad_climate.py','scripts/climate_gee_compute.py')},
                'dependencies':{'jdatetime':hashlib.sha256((CACHE/'jdatetime.py').read_bytes()).hexdigest(),'jalali_core':hashlib.sha256((CACHE/'jalali_core.py').read_bytes()).hexdigest()},
                'files_sha256':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in result['files'].items()}},ensure_ascii=False,indent=2),'utf-8')
            print(json.dumps({'output':str(OUTPUT),'complete_water_years':result['metadata']['complete_water_years'],
                              'first':result['metadata']['start_water_year'],'last':result['metadata']['end_water_year'],
                              'excluded':result['metadata']['quality_control']['excluded_water_years'],'summary':result['metadata']['summary']},ensure_ascii=False),flush=True)
            browser.close()
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()

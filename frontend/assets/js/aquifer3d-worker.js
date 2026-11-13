import { loadBrowserPython, version } from "./pyodide-runtime.js";

let readyPromise;
let qualityPromise;
let managementPromise;
let lifetimePromise;
let spatialPromise,activeSpatial={method:'idw'};
let algebraRedirected=false;

function redirectAlgebra(){
  if(algebraRedirected)return;algebraRedirected=true;
  // Keep the auxiliary BLAS ZIP away from download-manager interception.
  const nativeFetch=self.fetch.bind(self);
  self.fetch=(resource,options)=>{
    const url=typeof resource==='string'?resource:resource?.url||String(resource);
    return nativeFetch(/\/libopenblas-[^/]+\.zip(?:\?|$)/.test(url)?'/runtime/quality-openblas':resource,options);
  };
}
async function loadQuality(pyodide){
  redirectAlgebra();await pyodide.loadPackage(['numpy','scipy','pyproj','shapely']);
  const response=await fetch('/water-quality/compute.py',{cache:'no-cache'});
  if(!response.ok)throw new Error('دریافت کد کیفیت ناموفق بود.');
  await pyodide.runPythonAsync(await response.text());

}

function progress(message) {
  self.postMessage({ type: "progress", message });
}

async function initialize() {
  progress("در حال راه‌اندازی پایتون در مرورگر…");
  const pyodide = await loadBrowserPython({
    packageBaseUrl: new URL('/assets/pyodide/packages/',self.location.href).href
  });
  progress("در حال خواندن مرز آبخوان و داده‌های پیزومتر…");
  const paths = [
    "/data/AQUIFER.geojson",
    "/data/LOCATION.csv",
    "/data/DATA.csv",
    "/assets/js/aquifer3d_compute.py"
  ];
  const assetVersion = new URL(self.location.href).searchParams.get('v') || 'storage-1';
  const responses = await Promise.all(paths.map((path) => fetch(
    path.endsWith('.py') ? `${path}?v=${encodeURIComponent(assetVersion)}` : path,
    { cache: 'no-cache' }
  )));
  for (let index = 0; index < responses.length; index += 1) {
    if (!responses[index].ok) {
      throw new Error(`دریافت ${paths[index]} ناموفق بود (${responses[index].status}).`);
    }
  }
  const [geojson, locations, measurements, python] = await Promise.all(
    responses.map((response) => response.text())
  );
  progress("در حال آماده‌سازی داده‌ها در Pyodide…");
  await pyodide.runPythonAsync(python);
  pyodide.globals.set("_geojson_text", geojson);
  pyodide.globals.set("_locations_text", locations);
  pyodide.globals.set("_measurements_text", measurements);
  pyodide.globals.set("_figure_depth_text", "");
  pyodide.globals.set("_mashhad_text", "");
  const catalogJson = pyodide.runPython(
    "import json\njson.dumps(initialize(_geojson_text, _locations_text, _measurements_text, _figure_depth_text, _mashhad_text), ensure_ascii=False)"
  );
  pyodide.runPython("del _geojson_text, _locations_text, _measurements_text, _figure_depth_text, _mashhad_text");
  progress("داده‌ها آماده شدند.");
  return { pyodide, catalog: JSON.parse(catalogJson) };
}

async function handleRequest(data) {
  const { id, command, arguments: args = {} } = data;
  try {
    readyPromise ||= initialize();
    const { pyodide, catalog } = await readyPromise;
    if(['management','quality','lifetime','lifetime_presets','lifetime_quantity_reference'].includes(command)){
      spatialPromise ||= (async()=>{const v=new URL(self.location.href).searchParams.get('v')||'1';const response=await fetch(`/assets/js/aquifer-spatial.py?v=${encodeURIComponent(v)}`,{cache:'no-cache'});if(!response.ok)throw Error('دریافت کد روش مکانی ناموفق بود.');await pyodide.runPythonAsync(await response.text());})().catch(error=>{spatialPromise=null;throw error;});
      await spatialPromise;
      if(activeSpatial.method==='spline'){redirectAlgebra();await pyodide.loadPackage(['numpy','scipy']);}
    }
    if (command === "catalog") {
      self.postMessage({ id, result: catalog });
      return;
    }
    if(command==='management'){
      managementPromise ||= (async()=>{
        const v=new URL(self.location.href).searchParams.get('v')||'1';
        const response=await fetch(`/assets/js/aquifer-management-compute.py?v=${encodeURIComponent(v)}`,{cache:'no-cache'});
        if(!response.ok)throw new Error('دریافت کد تحلیل مدیریتی ناموفق بود.');
        await pyodide.runPythonAsync(await response.text());
      })().catch(error=>{managementPromise=null;throw error;});
      await managementPromise;
      const gridCrs=args.options?.subsidence?.raster_grid?.crs;
      if(gridCrs&&gridCrs!=='EPSG:4326')await pyodide.loadPackage('pyproj');
      pyodide.globals.set('_management_args_json',JSON.stringify(args));
      const result=JSON.parse(pyodide.runPython("_mg_args=json.loads(_management_args_json)\n_lifetime_management=management_from_current(_mg_args['feature_index'],_mg_args.get('options',{}))\njson.dumps(_lifetime_management,ensure_ascii=False,allow_nan=False)"));
      self.postMessage({id,result});return;
    }
    if(command==='lifetime'||command==='lifetime_tiff'||command==='lifetime_quantity_reference'||command==='lifetime_presets'){
      lifetimePromise ||= (async()=>{
        const v=new URL(self.location.href).searchParams.get('v')||'1';
        const responses=await Promise.all(['aquifer-trend-options.py','aquifer-lifetime-compute.py'].map(name=>fetch(`/assets/js/${name}?v=${encodeURIComponent(v)}`,{cache:'no-cache'})));
        for(const response of responses){if(!response.ok)throw new Error('دریافت کد عمر سناریویی ناموفق بود.');await pyodide.runPythonAsync(await response.text());}
      })().catch(error=>{lifetimePromise=null;throw error;});
      await lifetimePromise;
      if(command==='lifetime'&&args.scenario?.spatial_method==='spline'){redirectAlgebra();await pyodide.loadPackage(['numpy','scipy']);}
      pyodide.globals.set('_lifetime_args_json',JSON.stringify(args));
      const code=command==='lifetime_presets'?`_lt_presets=json.loads(_lifetime_args_json)
json.dumps(lifetime_presets(_last_analysis,globals().get('_lifetime_management'),_lt_presets.get('quality')),ensure_ascii=False,allow_nan=False)`:command==='lifetime_quantity_reference'?`_lt_preview=json.loads(_lifetime_args_json)
json.dumps(lifetime_quantity_reference(_last_analysis,globals().get('_lifetime_management'),_lt_preview['scenario'],_lt_preview.get('zones_text','')),ensure_ascii=False,allow_nan=False)` :command==='lifetime'?`_lt_args=json.loads(_lifetime_args_json)
_lt_sources={'quality_records':globals().get('_quality_cached_records',[]),'subsidence_options':globals().get('_mg_args',{}).get('options',{}).get('subsidence',{})}
_lt_result=lifetime_analysis(_last_analysis,globals().get('_lifetime_management'),_lt_args.get('quality'),_lt_args['scenario'],_lt_args.get('climate_text',''),_lt_args.get('zones_text',''),source_context=_lt_sources)
_lt_result['report']['input_files']=_lt_args.get('input_files',{})
json.dumps(_lt_result,ensure_ascii=False,allow_nan=False)`:`import base64
_lt_export=json.loads(_lifetime_args_json)
base64.b64encode(lifetime_tiff(_lt_export['result'],_lt_export.get('field','life_years'))).decode()`;
      const answer=pyodide.runPython(code);
      self.postMessage({id,result:command==='lifetime_tiff'?answer:JSON.parse(answer)});return;
    }
    if(command==='quality'){
      if(!args.quality_text?.trim())throw new Error('فایل کیفیت را انتخاب کنید.');
      qualityPromise ||= loadQuality(pyodide).catch(error=>{qualityPromise=null;throw error;});
      await qualityPromise;
      pyodide.globals.set('_quality_options_json',JSON.stringify(args));
      const result=JSON.parse(pyodide.runPython(`
_qo=json.loads(_quality_options_json)
_qo['source_metadata']={}
_qt=_qo.pop('quality_text')
if globals().get('_quality_cached_text') != _qt:
    _quality_cached_records=audit_quality(_qt,json.dumps({'features':_features}))['records']
    _quality_cached_text=_qt
_qr=estimate_quality(_last_analysis,_quality_cached_records,b'','',_qo)
json.dumps(_qr,ensure_ascii=False,allow_nan=False)
`));
      self.postMessage({id,result});return;
    }
    if (command === "analyze") {
      progress("در حال آماده‌سازی حجم‌های سه‌بعدی…");
      await pyodide.loadPackage("shapely");
      pyodide.runPython("_lifetime_management=None");
    }
    pyodide.globals.set("_command", command);
    pyodide.globals.set("_arguments", JSON.stringify(args));
    const result = JSON.parse(pyodide.runPython("call_json(_command, _arguments)"));
    if(command==='analyze')activeSpatial=result.spatial||{method:'idw'};
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({ id, error: error?.message || String(error) });
  }
}

// Package loading and runPythonAsync must finish before another command enters Python.
let requestQueue=Promise.resolve();
self.onmessage=({data})=>{
  requestQueue=requestQueue.then(()=>handleRequest(data)).catch(error=>{
    self.postMessage({id:data.id,error:error?.message||String(error)});
  });
};

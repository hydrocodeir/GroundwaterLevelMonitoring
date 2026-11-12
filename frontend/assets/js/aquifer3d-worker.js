import { loadBrowserPython, version } from "./pyodide-runtime.js";

let readyPromise;
let qualityPromise;
let managementPromise;

async function loadQuality(pyodide){
  // Keep the auxiliary BLAS ZIP away from download-manager interception.
  const nativeFetch=self.fetch.bind(self);
  self.fetch=(resource,options)=>{
    const url=typeof resource==='string'?resource:resource?.url||String(resource);
    return nativeFetch(/\/libopenblas-[^/]+\.zip(?:\?|$)/.test(url)?'/runtime/quality-openblas':resource,options);
  };
  await pyodide.loadPackage(['numpy','scipy','pyproj','shapely']);
  const base='/water-quality/';
  const files=['compute.py','WaterQ.csv','covariates.npy','geology.geojson','sources.json'];
  const responses=await Promise.all(files.map(file=>fetch(base+file,{cache:'no-cache'})));
  for(let i=0;i<responses.length;i++)if(!responses[i].ok)throw new Error(`دریافت منبع کیفیت ${files[i]} ناموفق بود.`);
  const [code,quality,raster,geology,sources]=await Promise.all(responses.map((response,i)=>i===2?response.arrayBuffer():response.text()));
  await pyodide.runPythonAsync(code);
  pyodide.globals.set('_quality_default_text',quality);
  pyodide.globals.set('_quality_geology',geology);
  pyodide.globals.set('_quality_sources',sources);
  pyodide.FS.writeFile('/quality_covariates.npy',new Uint8Array(raster));
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
    "/data/NEYSHABUR_BEDROCK_DEPTH.csv",
    "/data/MASHHAD_BEDROCK_MSL.csv",
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
  const [geojson, locations, measurements, figureDepth, mashhadBedrock, python] = await Promise.all(
    responses.map((response) => response.text())
  );
  progress("در حال آماده‌سازی داده‌ها در Pyodide…");
  await pyodide.runPythonAsync(python);
  pyodide.globals.set("_geojson_text", geojson);
  pyodide.globals.set("_locations_text", locations);
  pyodide.globals.set("_measurements_text", measurements);
  pyodide.globals.set("_figure_depth_text", figureDepth);
  pyodide.globals.set("_mashhad_text", mashhadBedrock);
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
      const result=JSON.parse(pyodide.runPython("_mg_args=json.loads(_management_args_json)\njson.dumps(management_from_current(_mg_args['feature_index'],_mg_args.get('options',{})),ensure_ascii=False,allow_nan=False)"));
      self.postMessage({id,result});return;
    }
    if(command==='quality'){
      qualityPromise ||= loadQuality(pyodide).catch(error=>{qualityPromise=null;throw error;});
      await qualityPromise;
      pyodide.globals.set('_quality_options_json',JSON.stringify(args));
      const result=JSON.parse(pyodide.runPython(`
_qo=json.loads(_quality_options_json)
_qo['source_metadata']=json.loads(_quality_sources)
_qt=_qo.pop('quality_text','') or _quality_default_text
if globals().get('_quality_cached_text') != _qt:
    _quality_cached_records=audit_quality(_qt,json.dumps({'features':_features}))['records']
    _quality_cached_text=_qt
_qr=estimate_quality(_last_analysis,_quality_cached_records,open('/quality_covariates.npy','rb').read(),_quality_geology,_qo)
json.dumps(_qr,ensure_ascii=False,allow_nan=False)
`));
      self.postMessage({id,result});return;
    }
    if (command === "analyze") {
      progress("در حال آماده‌سازی حجم‌های سه‌بعدی…");
      await pyodide.loadPackage("shapely");
    }
    pyodide.globals.set("_command", command);
    pyodide.globals.set("_arguments", JSON.stringify(args));
    const result = JSON.parse(pyodide.runPython("call_json(_command, _arguments)"));
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

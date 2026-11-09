let py;
self.onmessage=async({data})=>{
 try{
  if(data.command==='assess'||data.command==='restore'){
   const base=data.base+'/.tmp/mashhad-bedrock/scipy-runtime/';
   const {loadPyodide}=await import(base+'pyodide.mjs');
   py=await loadPyodide({indexURL:base,stdout:msg=>self.postMessage({progress:msg})});
   await py.loadPackage(['numpy','scipy']);
   const paths=['/scripts/mashhad_bedrock_compute.py','/scripts/mashhad_bedrock_surface.py','/.tmp/BedRock.geojson','/Data/AQUIFER.geojson'];
   const texts=await Promise.all(paths.map(async path=>{const r=await fetch(data.base+path);if(!r.ok)throw Error(path+': '+r.status);return r.text()}));
   await py.runPythonAsync(texts[0]);await py.runPythonAsync(texts[1]);
   py.globals.set('_source',texts[2]);py.globals.set('_aquifers',texts[3]);
   py.globals.set('_assessment',JSON.stringify(data.assessment||{}));
   const code=data.command==='assess'?'assess_models(_source,_aquifers)':'restore_for_fit(_source,_aquifers,_assessment)';
   self.postMessage({result:JSON.parse(await py.runPythonAsync(code))});
  }else if(data.command==='fit'){
   self.postMessage({result:JSON.parse(await py.runPythonAsync('fit_continuous_surface()'))});
  }else if(data.command==='finish'){
   const files=[];
   for(const tile of data.plan.tiles){
    const r=await fetch(data.base+'/.tmp/mashhad-gee-dem/'+tile.id+'.npy');if(!r.ok)throw Error('DEM missing');
    const path='/'+tile.id+'.npy';py.FS.writeFile(path,new Uint8Array(await r.arrayBuffer()));files.push({path,tile});
   }
   py.globals.set('_files',JSON.stringify(files));py.globals.set('_retrieved',data.retrieved);
   self.postMessage({result:JSON.parse(await py.runPythonAsync('finish_continuous(_files,_retrieved)'))});
  }else if(data.command==='validate-upload'){
   const src=await(await fetch(data.base+'/frontend/assets/js/aquifer3d_compute.py')).text();
   py.globals.set('_upload_src',src);py.globals.set('_upload_csv',data.csv);
   const result=await py.runPythonAsync(`
_ns={}; exec(_upload_src,_ns)
_polys=_ns['_polygons'](state['feature'])
_accepted=_ns['_bedrock_points'](_upload_csv,_polys,_ns['_extent'](_polys))
assert len(_accepted)==len(state['rows'])
json.dumps({'accepted_points':len(_accepted)})
`);
   self.postMessage({result:JSON.parse(result)});
  }
 }catch(error){self.postMessage({error:String(error.stack||error)})}
};

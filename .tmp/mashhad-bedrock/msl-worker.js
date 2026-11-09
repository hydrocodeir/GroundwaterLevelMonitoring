let py;
self.onmessage=async({data})=>{
  try {
    if(data.command==='prepare'){
      const {loadPyodide}=await import(data.base+'/frontend/assets/pyodide/pyodide.mjs');
      py=await loadPyodide({indexURL:data.base+'/frontend/assets/pyodide/'});
      const paths=['/scripts/mashhad_bedrock_compute.py','/.tmp/BedRock.geojson','/Data/AQUIFER.geojson'];
      const texts=await Promise.all(paths.map(async p=>{const r=await fetch(data.base+p);if(!r.ok)throw Error(p+': '+r.status);return r.text()}));
      await py.runPythonAsync(texts[0]);
      py.globals.set('_source',texts[1]);py.globals.set('_aquifers',texts[2]);
      const result=JSON.parse(await py.runPythonAsync('prepare(_source,_aquifers)'));
      self.postMessage({result});
    }else if(data.command==='finish'){
      const files=[];
      for(const tile of data.plan.tiles){
        const r=await fetch(data.base+'/.tmp/mashhad-gee-dem/'+tile.id+'.npy');
        if(!r.ok)throw Error('DEM download missing: '+tile.id);
        const path='/'+tile.id+'.npy';
        py.FS.writeFile(path,new Uint8Array(await r.arrayBuffer()));
        files.push({path,tile});
      }
      py.globals.set('_files',JSON.stringify(files));py.globals.set('_retrieved',data.retrieved);
      const result=JSON.parse(await py.runPythonAsync('finish(_files,_retrieved)'));
      self.postMessage({result});
    }else if(data.command==='validate-upload'){
      const src=await (await fetch(data.base+'/frontend/assets/js/aquifer3d_compute.py')).text();
      py.globals.set('_upload_src',src);py.globals.set('_upload_csv',data.csv);
      await py.runPythonAsync("_upload_ns = {}; exec(_upload_src, _upload_ns)");
      const result=JSON.parse(await py.runPythonAsync(`
_upload_polygons = _upload_ns['_polygons'](state['feature'])
_upload_extent = _upload_ns['_extent'](_upload_polygons)
_upload_points = _upload_ns['_bedrock_points'](_upload_csv, _upload_polygons, _upload_extent)
assert len(_upload_points) == len(state['rows'])
json.dumps({'accepted_points':len(_upload_points),'parser':'aquifer3d_compute._bedrock_points'})
`));
      self.postMessage({result});
    }
  }catch(error){self.postMessage({error:String(error.stack||error)})}
};

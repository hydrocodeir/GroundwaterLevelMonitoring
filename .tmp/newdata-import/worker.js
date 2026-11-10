let py;
self.onmessage=async({data})=>{
 try{
  if(data.command==='audit'||data.command==='load-for-verification'){
   const {loadPyodide}=await import(data.base+'/frontend/assets/pyodide/pyodide.mjs');
   py=await loadPyodide({indexURL:data.base+'/frontend/assets/pyodide/'});
   py.FS.mkdirTree('/packages');
   for(const name of ['jdatetime','jalali_core']){
    py.FS.mkdirTree('/packages/'+name);
    const r=await fetch(data.base+'/.tmp/newdata-import/packages/'+name+'/__init__.py');
    py.FS.writeFile('/packages/'+name+'/__init__.py',await r.text());
   }
   await py.runPythonAsync("import sys; sys.path.insert(0,'/packages')");
   const files=['/scripts/newdata_import_compute.py','/Data/NewData.csv','/Data/DATA.csv','/Data/LOCATION.csv','/Data/AQUIFER.geojson'];
   const texts=await Promise.all(files.map(async p=>{const r=await fetch(data.base+p);if(!r.ok)throw Error(p+': '+r.status);return r.text()}));
   await py.runPythonAsync(texts[0]);
   for(let i=1;i<texts.length;i++)py.globals.set('_input'+i,texts[i]);
   if(data.command==='load-for-verification'){
    self.postMessage({result:JSON.parse(await py.runPythonAsync('load_for_verification(_input1,_input2,_input3)'))});
    return;
   }
   const report=JSON.parse(await py.runPythonAsync('analyse(_input1,_input2,_input3,_input4)'));
   const summary=JSON.parse(await py.runPythonAsync('review_summary()'));
   const identities=JSON.parse(await py.runPythonAsync('identity_plan()'));
   const details=JSON.parse(await py.runPythonAsync('identity_review_details()'));
   self.postMessage({result:{report,summary,identities,details}});
  }else if(data.command==='merge'){
   const r=await fetch(data.base+'/Data/LOCATION.geojson');if(!r.ok)throw Error('LOCATION.geojson missing');
   const geo=await r.text();
   py.globals.set('_geo',geo);py.globals.set('_policy',JSON.stringify(data.policy));
   const result=JSON.parse(await py.runPythonAsync('merge_records(_policy,_geo)'));
   result.input_geo_sha256=await py.runPythonAsync("hashlib.sha256(_geo.encode()).hexdigest()");
   self.postMessage({result});
  }else if(data.command==='verify'){
   const paths=['/Data/NEW_DATA_IMPORT_REPORT.json','/Data/NEW_DATA_IMPORT_AUDIT.csv','/Data/LOCATION.geojson'];
   const texts=await Promise.all(paths.map(async p=>{const r=await fetch(data.base+p);if(!r.ok)throw Error(p);return r.text()}));
   texts.forEach((text,i)=>py.globals.set('_verify'+i,text));
   self.postMessage({result:JSON.parse(await py.runPythonAsync('verify_saved_import(_verify0,_verify1,_verify2)'))});
  }
 }catch(error){self.postMessage({error:String(error.stack||error)})}
};

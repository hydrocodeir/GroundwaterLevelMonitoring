import json
from pathlib import Path
from playwright.sync_api import sync_playwright

AUDIT = r'''
raw, _ = _depth_points(_source_csv)
restored, rule = _depth_points(_corrected_csv)
assert sorted(raw) == sorted(restored)
feature = json.loads(_geojson)["features"][33]
polygons = _polygons(feature)
west, south, east, north = _extent(polygons)
center_lat = (south+north)/2
boundary = _boundary_index(polygons, center_lat)
rows = list(csv.DictReader(io.StringIO(_corrected_csv)))
boundary_rows = [r for r in rows if r["point_role"] == "boundary_assumption"]
assert all(float(r["bedrock_depth_m"]) == 5 for r in boundary_rows)
max_boundary_distance = max(_boundary_distance_m(boundary, float(r["lon"]), float(r["lat"])) for r in boundary_rows)
assert max_boundary_distance < .001
errors = []
for r in rows:
    if r["point_role"] == "digitized_outside":
        assert r["bedrock_depth_m"] == ""
    elif r["point_role"] != "boundary_assumption":
        distance = _boundary_distance_m(boundary, float(r["lon"]), float(r["lat"]))
        expected = _edge_depth(float(r["source_depth_m"]), distance, rule,
                               float(r["lon"]), float(r["lat"]), center_lat)
        errors.append(abs(expected-float(r["bedrock_depth_m"])))
        if distance >= rule["width_m"]:
            assert abs(float(r["source_depth_m"])-float(r["bedrock_depth_m"])) < .001
assert max(errors) < .0011
initialize(_geojson, _locations_csv, _measurements_csv, _source_csv)
old = analyze(33, 1381, .051)
initialize(_geojson, _locations_csv, _measurements_csv, _corrected_csv)
new = analyze(33, 1381, .051)
assert old["metrics"]["bedrock_coverage_pct"] == new["metrics"]["bedrock_coverage_pct"]
conflicts = []
for key, well in _prepared[33]["current"].items():
    distance = _boundary_distance_m(boundary, well["lon"], well["lat"])
    raw_depth = _contour_idw(raw, well["lon"], well["lat"], center_lat)
    depth = _edge_depth(raw_depth, distance, rule, well["lon"], well["lat"], center_lat)
    water = _readings[(key,CURRENT_YEAR,CURRENT_MONTH)]
    if water > depth:
        conflicts.append({"name":well["name"],"water_depth":water,"raw_depth":raw_depth,"bedrock_depth":depth,"distance":distance})
audit = {"rows":len(rows), "boundary_rows":len(boundary_rows),
         "max_boundary_distance_m":max_boundary_distance, "max_csv_formula_rounding_error_m":max(errors),
         "raw_controls_preserved":len(restored), "before_metrics":old["metrics"], "after_metrics":new["metrics"],
         "current_well_count":len(_prepared[33]["current"]), "well_conflicts":conflicts}
assert not conflicts
json.dumps(audit,ensure_ascii=True)
'''

with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8765/aquifer-3d')
    page.locator('#status3d[data-state="ready"]').wait_for(timeout=90000)
    output=page.evaluate('''async audit => {
      const code=`self.onmessage=async ({data})=>{try{
        const {loadPyodide}=await import('http://127.0.0.1:8765/assets/pyodide/pyodide.mjs');
        const py=await loadPyodide({indexURL:'http://127.0.0.1:8765/assets/pyodide/'});
        const paths=['/assets/js/aquifer3d_compute.py','/data/AQUIFER.geojson','/data/LOCATION.csv','/data/DATA.csv','/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv','/data/NEYSHABUR_BEDROCK_DEPTH.csv'];
        const texts=await Promise.all(paths.map(p=>fetch('http://127.0.0.1:8765'+p).then(r=>r.text())));
        await py.runPythonAsync(texts[0]);
        ['_geojson','_locations_csv','_measurements_csv','_source_csv','_corrected_csv'].forEach((name,i)=>py.globals.set(name,texts[i+1]));
        const output=await py.runPythonAsync(data);self.postMessage({output});
      }catch(error){self.postMessage({error:error.message||String(error)});}}`;
      const url=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
      const worker=new Worker(url,{type:'module'});
      return new Promise((resolve,reject)=>{worker.onmessage=({data})=>{worker.terminate();URL.revokeObjectURL(url);data.error?reject(new Error(data.error)):resolve(data.output);};worker.postMessage(audit);});
    }''',AUDIT)
    page.locator('.aquifer3d-scenes').screenshot(path='.tmp/neyshabur_boundary_model.png')
    print(output)
    print('page_errors',errors)
    Path('.tmp/neyshabur_boundary_audit.json').write_text(output,encoding='utf-8')
    browser.close()

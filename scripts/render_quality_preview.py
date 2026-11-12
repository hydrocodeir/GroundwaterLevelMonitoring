"""Render saved quality results with the dashboard's actual map component."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8767');args=parser.parse_args()
    out=ROOT/'outputs/water_quality'
    geo=json.loads((out/'WATERQ_ZONES.geojson').read_text(encoding='utf-8'))
    features=json.loads((ROOT/'Data/AQUIFER.geojson').read_text(encoding='utf-8'))['features']
    feature=next(f for f in features if f['properties']['AQUIFER']==geo['metadata']['aquifer']['name'])
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1100,'height':1250},accept_downloads=True)
        page.goto(args.url+'/water-quality/sources.json')
        page.evaluate("""async ({geo,feature})=>{
          document.body.replaceChildren();
          for(const path of ['/assets/css/app.css','/assets/css/aquifer3d.css']){const l=document.createElement('link');l.rel='stylesheet';l.href=path;document.head.append(l)}
          const root=document.createElement('div');root.style='width:1000px;margin:auto';document.body.append(root);
          const {mountMap}=await import('/assets/js/aquifer3d-maps.js');
          const polygons=feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.coordinates;
          const coordinates=polygons.flat(2),xs=coordinates.map(p=>p[0]),ys=coordinates.map(p=>p[1]);
          const cells=geo.features.map(f=>({...f.properties,polygons:f.geometry.coordinates}));
          const fields={};for(const key of ['quality_zone_code','quality_ec','quality_usable_pct']){const v=cells.map(c=>c[key]).filter(Number.isFinite);fields[key]={min:Math.min(...v),max:Math.max(...v),contours:[]};}
          const r=geo.metadata;
          mountMap(root,{aquifer:r.aquifer,dates:r.volume_dates,metrics:r.volume_model,grid:{bedrock_source:r.volume_model.bedrock_source},quality_report:r,input_files:{quality:r.quality_input_file},plan_maps:{cells,fields,polygons,extent:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)],side_m:Math.sqrt(Math.max(...cells.map(c=>c.area_m2))),percentage_reference:'quality_compatible_fraction_of_current_saturated_column'}},['quality_zone_code','quality_ec','quality_usable_pct'],'quality-preview');
          await document.fonts.ready;
        }""",{'geo':geo,'feature':feature})
        for key,name in [('quality_zone_code','MASHHAD_QUALITY_ZONES.png'),('quality_ec','MASHHAD_EC.png'),('quality_usable_pct','MASHHAD_IRRIGATION_FRACTION.png')]:
            page.locator('select').select_option(key)
            with page.expect_download() as download:page.locator('[data-export=png]').click()
            download.value.save_as(out/name)
        browser.close()
    print('Rendered saved quality zones, EC and compatible fraction.')


if __name__=='__main__':main()

"""Real Pyodide integration, changed horizons, local subsidence and another aquifer."""
import argparse
import csv
import io
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8767');args=parser.parse_args()
    out=Path('.tmp/management-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];posts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1100},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda request:posts.append(request.url) if request.method!='GET' else None)
        page.goto(args.url+'/aquifer-3d?name=%D9%85%D8%B4%D9%87%D8%AF',wait_until='domcontentloaded')
        def core_ready():
            page.wait_for_function("document.querySelector('#a3Workspace').dataset.ready==='true' || document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
            assert page.locator('#a3Workspace').get_attribute('data-ready')=='true',page.locator('#status3d').inner_text()
        core_ready();page.locator('#a3Nav-management').click()
        def ready():
            page.wait_for_function("document.querySelector('[data-m-results]') && !document.querySelector('[data-m-results]').hidden && !document.querySelector('[data-m-run]').disabled",timeout=60000)
        def report():return json.loads(page.locator('#managementTools metadata').text_content())['management']
        ready();initial=report()
        assert initial['eligible_wells']>=3,initial
        assert initial['settings']['horizons']==[3,5,10,25]
        assert 0<=initial['subsidence_supported_area_pct']<=100
        if initial['subsidence'].get('input_records'):
            assert initial['subsidence'].get('cumulative') is True
        assert initial['quality_supported_area_pct']==0
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=true')
        page.locator('[data-m-input=horizons]').fill('2,7,30')
        ready();changed=report();assert changed['settings']['horizons']==[2,7,30],changed
        page.locator('[data-m-input=threshold_type]').select_option('drawdown')
        page.locator('[data-m-input=threshold]').fill('5')
        ready();threshold=report();assert threshold['settings']['threshold']==5
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=false')
        page.locator('[data-m-tab=future]').click()
        page.locator('[data-m-horizon]').select_option('30')
        assert page.locator('[data-m-forecast-table] tbody tr').count()==3
        assert '30' in page.locator('#managementTools metadata').text_content()
        page.locator('#managementTools').screenshot(path=str(out/'future-desktop.png'))
        with page.expect_download() as dl:page.locator('[data-m-forecast-csv]').click()
        dl.value.save_as(out/'forecasts.csv')
        rows=list(csv.DictReader(io.StringIO((out/'forecasts.csv').read_text(encoding='utf-8-sig'))))
        assert [float(r['horizon']) for r in rows]==[2,7,30]
        with page.expect_download() as dl:page.locator('[data-m-json]').click()
        dl.value.save_as(out/'management.json');result=json.loads((out/'management.json').read_text(encoding='utf-8'))
        eligible=[w for w in result['wells'] if w['eligible']]
        source='longitude,latitude,rate_mm_year,start_water_year,end_water_year\n'+'\n'.join(f"{w['lon']},{w['lat']},12,{initial['trend_end_water_year']-2},{initial['trend_end_water_year']}" for w in eligible)
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=true')
        page.locator('[data-m-source-details]').evaluate('(n)=>n.open=true')
        page.locator('[data-m-sub=component]').select_option('vertical')
        page.locator('[data-m-source]').set_input_files({'name':'synthetic-QA-only.csv','mimeType':'text/csv','buffer':source.encode()})
        ready();subsidence=report();assert subsidence['subsidence_supported_area_pct']>0,subsidence
        page.locator('[data-m-tab=subsidence]').click()
        page.locator('[data-m-source-details]').evaluate('(n)=>n.open=false')
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=false')
        page.locator('#managementTools').screenshot(path=str(out/'subsidence-desktop.png'))
        with page.expect_download() as dl:page.locator('#managementTools [data-export=csv]').click()
        dl.value.save_as(out/'map.csv');header=next(csv.reader(io.StringIO((out/'map.csv').read_text(encoding='utf-8-sig'))))
        assert 'management_subsidence' in header and 'management_settings_json' in header
        # Quality integration is exercised without fabricating a measurement as real data:
        # send an explicitly synthetic UI event using this model's grid in the QA browser only.
        quality={'report':{'thresholds':{'drinking_ec_uScm':1500},'quality_water_year':initial['trend_end_water_year'],'quality_input_file':'synthetic-QA-only'},'plan_maps':{'cells':[{**{k:c[k] for k in ('lon','lat')},'quality_supported':True,'quality_ec':4000,'quality_zone_code':2} for c in result['plan_maps']['cells']]}}
        page.evaluate("q=>document.dispatchEvent(new CustomEvent('a3:quality-result',{detail:q}))",quality)
        ready();assert report()['quality_supported_area_pct']>0
        page.evaluate("()=>document.dispatchEvent(new CustomEvent('a3:quality-result',{detail:null}))")
        ready();assert report()['quality_supported_area_pct']==0
        # Generic behavior, with no aquifer name in the model or parameters.
        page.locator('#aquiferSelect3d').select_option(label=next(t for t in page.locator('#aquiferSelect3d option').all_text_contents() if t.endswith('/ نیشابور')))
        core_ready();page.locator('#a3Nav-management').click();ready()
        other=report();assert other['aquifer']['name']=='نیشابور'
        assert other['settings']['horizons']==[3,5,10,25]
        assert other['subsidence_supported_area_pct']==0
        assert other['subsidence']['outside_records']>0
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('#managementTools').screenshot(path=str(out/'mobile.png'))
        assert not errors,errors
        assert not posts,posts
        print(json.dumps({'status':'passed','mashhad_wells':initial['eligible_wells'],'other_wells':other['eligible_wells'],'posts':posts,'errors':errors}))
        browser.close()


if __name__=='__main__':main()

"""Verify the supplied raster-derived source with actual browser Pyodide."""
import argparse
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import open_section


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8767');args=parser.parse_args()
    out=Path('.tmp/cumulative-subsidence-qa');out.mkdir(parents=True,exist_ok=True)
    source_meta=json.loads(Path('Data/Subsidence/Mashhad_cumulative.metadata.json').read_text(encoding='utf-8'))
    errors=[];posts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1100},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method!='GET' else None)
        page.goto(args.url+'/aquifer-3d?name=%D9%85%D8%B4%D9%87%D8%AF',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#a3Workspace').dataset.ready==='true'",timeout=180000)
        open_section(page,'management')
        def ready():
            page.wait_for_function("document.querySelector('[data-m-results]') && !document.querySelector('[data-m-results]').hidden && !document.querySelector('[data-m-run]').disabled",timeout=180000)
        def report():return json.loads(page.locator('#managementTools metadata').text_content())['management']
        ready();first=report();sub=first['subsidence']
        assert sub['cumulative'] is True,sub
        assert sub['input_records']==source_meta['statistics']['valid_pixels']
        assert sub['calendar_basis']=='persian' and sub['source_years']==[1395,1404]
        assert sub['direction']=='down' and sub['component']=='vertical'
        assert sub['comparison_mode']=='observed_cumulative'
        assert sub['aligned_wells']>0,sub
        assert first['subsidence_supported_area_pct']>0
        page.locator('[data-m-tab=subsidence]').click()
        page.locator('#managementTools select[aria-label="متغیر نقشه"]').select_option('management_subsidence_cumulative')
        page.locator('#managementTools').screenshot(path=str(out/'cumulative-desktop.png'))
        with page.expect_download() as dl:page.locator('[data-m-json]').click()
        dl.value.save_as(out/'baseline.json');baseline=json.loads((out/'baseline.json').read_text(encoding='utf-8'))
        valid=[c for c in baseline['plan_maps']['cells'] if c['management_subsidence_cumulative'] is not None]
        assert valid and all(c['management_subsidence_cumulative']>=0 for c in valid)
        assert all(abs(c['management_subsidence']*sub['duration_years']-c['management_subsidence_cumulative'])<1e-8 for c in valid)
        assert any(c['management_subsidence_coverage_pct']<100 for c in baseline['plan_maps']['cells'])
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=true')
        page.locator('[data-m-source-details]').evaluate('(n)=>n.open=true')
        assert 'شمسی' in page.locator('[data-m-start-label]').inner_text()
        with page.expect_download() as dl:page.locator('[data-m-project-csv]').click()
        dl.value.save_as(out/'source.csv')
        assert hashlib.sha256((out/'source.csv').read_bytes()).hexdigest()==source_meta['csv_sha256']
        duration=page.locator('[data-m-sub=duration_years]');duration.fill(str(sub['duration_years']*2));duration.press('Tab')
        ready();changed=report();assert changed['subsidence']['duration_years']==sub['duration_years']*2
        with page.expect_download() as dl:page.locator('[data-m-json]').click()
        dl.value.save_as(out/'changed.json');modified=json.loads((out/'changed.json').read_text(encoding='utf-8'))
        for old,new in zip(baseline['plan_maps']['cells'],modified['plan_maps']['cells']):
            assert old['management_subsidence_cumulative']==new['management_subsidence_cumulative']
            if old['management_subsidence'] is not None:assert abs(old['management_subsidence']/2-new['management_subsidence'])<1e-8
        page.locator('[data-m-source-details]').evaluate('(n)=>n.open=false')
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=false')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('.a3-management-map').screenshot(path=str(out/'cumulative-mobile.png'))
        assert not errors,errors
        assert not posts,posts
        print(json.dumps({'status':'passed','valid_tiff_pixels':sub['input_records'],'aligned_wells':sub['aligned_wells'],
                          'subsidence_area_pct':first['subsidence_supported_area_pct'],'errors':errors,'posts':posts}))
        browser.close()


if __name__=='__main__':main()

"""Real Pyodide: shared aquifer method, quality, point/raster settlement and click-only help."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, open_section


def main():
    out=Path('.tmp/shared-spatial-qa');out.mkdir(parents=True,exist_ok=True);errors=[];uploads=[];results={}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:uploads.append(r.url) if r.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        def scenario():
            open_section(page,'lifetime');page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            root=page.locator('#lifetimeTools')
            if root.locator('.lt-editor').get_attribute('open') is None:root.locator('.lt-editor>summary').click()
            root.locator('[data-lt-run]').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            return json.loads(root.locator('[data-lt-metadata]').text_content())
        for method in ['idw','spline','thiessen']:
            if method!='idw':
                page.locator('[data-lt-spatial-edit]').click()
                assert page.locator('#spatialMethodInput').is_visible()
                page.locator('#spatialMethodInput').select_option(method)
                assert page.locator('#spatialSmoothingInput').is_visible()==(method=='spline')
                page.locator('#a3SettingsApply').click()
                page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
                assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
            initial=scenario()
            print(json.dumps({'method':method,'stage':'trend ready'}),flush=True)
            assert page.locator('select[data-lt=spatial_method]').count()==0
            assert initial['scenario']['spatial_method']==method and initial['scenario']['spatial_coverage']=='aquifer'
            assert initial['unknown_area_pct']<1e-8
            assert initial['spatial_coverage']['area_pct']['extrapolated']>0
            open_section(page,'quality');page.locator('[data-q-run]').click()
            page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
            assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
            metadata=json.loads(page.locator('.a3-quality-map metadata').text_content());quality=metadata['quality_model']
            print(json.dumps({'method':method,'stage':'quality ready'}),flush=True)
            assert quality['spatial']['method']==quality['validation']['selected']==method
            assert quality['validation']['full_aquifer'] and quality['validation']['spatially_estimated_cells']>0
            assert page.locator('.a3-quality-map [data-cell]').count()>100
            # Hover/focus must never open help; clicking and keyboard activation do.
            trigger=page.locator('#qualityTools h2 .hydro-info-trigger').first;tip=page.locator('#hydroTooltip')
            trigger.hover();assert not tip.is_visible();trigger.focus();assert not tip.is_visible()
            trigger.click();assert tip.is_visible();trigger.click();assert not tip.is_visible()
            trigger.focus();page.keyboard.press('Enter');assert tip.is_visible();page.keyboard.press('Escape');assert not tip.is_visible()
            open_section(page,'management');page.locator('[data-m-tab=subsidence]').click();page.locator('[data-m-open-source]').click()
            if method=='thiessen':
                page.locator('[data-m-source]').set_input_files('Data/Subsidence/Mashhad_cumulative.csv')
                page.locator('[data-m-sub=calendar_basis]').select_option('persian')
                page.locator('[data-m-sub=start_water_year]').fill('1395');page.locator('[data-m-sub=end_water_year]').fill('1404');page.locator('[data-m-sub=duration_years]').fill('10')
            else:
                # QA-only sparse point layer, not dashboard default data.
                wells=initial['base_model']['grid']['points'];points=[v for v in wells if v[5]][::70]
                text='longitude,latitude,rate_mm_year,start_water_year,end_water_year\n'+''.join(f'{v[0]},{v[1]},{20+i*3},1395,1404\n' for i,v in enumerate(points))
                page.locator('[data-m-source]').set_input_files({'name':'QA-sparse-settlement.csv','mimeType':'text/csv','buffer':text.encode()})
            page.locator('[data-m-sub=component]').select_option('vertical');page.locator('[data-m-sub=direction]').select_option('down')
            page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
            page.locator('[data-m-run]').click();page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
            parameter=json.loads(page.locator('.a3-management-map metadata').text_content());mg=parameter['management']
            assert mg['spatial']['method']==method
            assert mg['subsidence']['spatial']['method']==method
            assert mg['subsidence_supported_area_pct']>99.999
            assert mg['trend_supported_area_pct']>99.999
            if method=='thiessen':
                assert mg['subsidence']['raster_grid'] and mg['subsidence']['input_records']>100000
                page.locator('.a3-management-map .a3-plan-svg').screenshot(path=str(out/'thiessen-raster-map.png'))
            final=scenario();results[method]={'quality':quality['validation'],'management_spatial':mg['spatial'],'subsidence':mg['subsidence']['spatial'],'quality_unknown_pct':final['unknown_area_pct']}
            page.locator('#lifetimeTools [data-lt-edit]').click()
            page.locator('[data-lt=quality_on]').check();page.locator('[data-lt=subsidence_on]').check();page.locator('[data-lt=subsidence_limit]').fill('100')
            combined=scenario();assert combined['scenario']['spatial_method']==method and combined['unknown_area_pct']<1e-8
            print(json.dumps({'method':method,'passed':True,'quality_method':quality['validation']['selected'],'subsidence_coverage':mg['subsidence_supported_area_pct']}),flush=True)
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-lt-spatial-edit]').click();assert page.locator('#spatialMethodInput').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('#a3Settings').screenshot(path=str(out/'shared-settings-mobile.png'))
        assert not errors,errors
        assert not uploads,uploads
        (out/'summary.json').write_text(json.dumps({'passed':True,'methods':results,'page_errors':errors,'data_uploads':uploads},ensure_ascii=False,indent=2),'utf-8')
        browser.close()
    print(json.dumps({'passed':True,'methods':list(results),'page_errors':errors}))


if __name__=='__main__':main()

"""Explicit user-layer workflow, presets, structured help and real Mashhad audit."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import open_section, edit_selection


def main():
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1500,'height':1000},accept_downloads=True)
        page.add_init_script("for(let i=0;i<80;i++)localStorage.setItem('aquifer3d:v1:'+i,JSON.stringify({sy:'.9'}));")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append(r.url))
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#a3Workspace').dataset.settings==='open'&&!document.querySelector('#build3d').disabled",timeout=180000)
        assert page.locator('#syInput').input_value()==''
        for key in ['syFile','bedrockFile','qualityInputFile','climateInputFile','subsidenceInputFile']:
            assert page.locator('#'+key).input_value()==''
        page.screenshot(path=str(out/'user-layer-dialog.png'),full_page=True)
        # These local files are explicitly chosen for this test, never defaults.
        page.locator('#syInput').fill('.06')
        page.locator('#bedrockFile').evaluate('(n)=>n.closest("details").open=true')
        page.locator('#bedrockFile').set_input_files('Data/MASHHAD_BEDROCK_MSL.csv')
        page.locator('#qualityInputFile').set_input_files('Data/WaterQ.csv')
        page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        open_section(page,'lifetime');root=page.locator('#lifetimeTools')
        page.wait_for_function("document.querySelectorAll('[data-lt-preset] option').length>5&&!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        for key in ['quality','subsidence']:
            assert root.locator(f'[data-lt-prereq={key}]').get_attribute('data-ready')=='false'
            assert root.locator(f'[data-lt={key}_on]').is_disabled()
            assert not root.locator(f'[data-lt-prereq-guide={key}]').is_visible()
            root.locator(f'[data-lt-prereq={key}] .hydro-info-trigger').click()
            assert 'اجرا' in page.locator('#hydroTooltip').text_content()
            page.keyboard.press('Escape')
        root.locator('[data-lt-prepare=quality]').click()
        assert page.locator('#a3Workspace').get_attribute('data-section')=='quality'
        assert page.locator('[data-q-file]').is_visible()
        open_section(page,'lifetime')
        root.locator('[data-lt-prepare=subsidence]').click()
        assert page.locator('#a3Workspace').get_attribute('data-section')=='management'
        assert page.locator('[data-m-source]').is_visible()
        open_section(page,'lifetime')
        root.locator('[data-lt-preset]').select_option('q_base')
        assert not root.locator('[data-lt-preset-apply]').is_disabled()
        root.locator('[data-lt-preset]').select_option('all_base')
        assert root.locator('[data-lt-preset-apply]').is_disabled()
        assert 'نیازمند' in root.locator('[data-lt-preset-state]').text_content()
        root.locator('[data-lt-preset]').select_option('q_base');root.locator('[data-lt-preset-apply]').click()
        root.locator('[data-lt-run]').click();page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
        report=json.loads(root.locator('[data-lt-metadata]').text_content())
        assert report['unknown_diagnostics']['unknown_cells']==0
        assert report['spatial_coverage']['area_pct']['extrapolated']>0
        (out/'MASHHAD_UNKNOWN_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        assert not root.locator('[data-lt-diagnostics]').is_visible()
        root.locator('.lt-map [data-cell]').nth(100).click(force=True)
        page.wait_for_selector('#hydroTooltip:not([hidden])')
        tip=page.locator('#hydroTooltip')
        assert tip.locator('.hydro-tooltip-title').count()==1
        assert tip.locator('dl dt').count()>3
        page.screenshot(path=str(out/'structured-tooltip.png'),clip=tip.bounding_box())
        page.keyboard.press('Escape')
        page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'user-lifetime-diagnostics.png'),full_page=True)
        root.locator('.lt-editor>summary').click()
        assert root.locator('[data-lt=spatial_coverage]').input_value()=='aquifer'
        root.locator('[data-lt-run]').click()
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        full_report=json.loads(root.locator('[data-lt-metadata]').text_content())
        assert full_report['unknown_area_pct']==0,full_report['unknown_diagnostics']
        assert full_report['spatial_coverage']['area_pct']['extrapolated']>15
        assert full_report['base_model']['physical_grid_sha256']==report['base_model']['physical_grid_sha256']
        expected=full_report['spatial_coverage']['cells']['extrapolated']
        assert root.locator('[data-extrapolated-cell]').count()==expected
        extrapolated=root.locator('[data-extrapolated-cell]').first.get_attribute('data-extrapolated-cell')
        root.locator(f'.lt-map [data-cell="{extrapolated}"]').click(force=True)
        page.wait_for_selector('#hydroTooltip:not([hidden])')
        assert 'برون‌یابی مکانی IDW' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape')
        root.locator('[data-lt-view]').select_option('support')
        assert 'برون‌یابی مکانی' in root.locator('.lt-map').text_content()
        with page.expect_download(timeout=60000) as pending:root.locator('[data-lt-export=support]').click()
        pending.value.save_as(out/'mashhad-lifetime-support.tif')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(out/'lifetime-prerequisites-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1500,'height':1000})
        root.locator('[data-lt-view]').select_option('map')
        page.screenshot(path=str(out/'mashhad-lifetime-full-coverage.png'),full_page=True)
        (out/'MASHHAD_FULL_COVERAGE_AUDIT.json').write_text(json.dumps(full_report,ensure_ascii=False,indent=2),'utf-8')
        # Quality uses the chosen CSV; no GEE/geology/source CSV is fetched.
        open_section(page,'quality');page.locator('[data-q-run]').click()
        page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        open_section(page,'lifetime')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        assert root.locator('[data-lt-prereq=quality]').get_attribute('data-ready')=='true'
        assert root.locator('[data-lt=quality_on]').is_enabled()
        root.locator('[data-lt-preset]').select_option('ec_gradual')
        assert not root.locator('[data-lt-preset-apply]').is_disabled()
        # A selected subsidence file is usable only after its metadata are supplied.
        open_section(page,'management')
        page.locator('[data-m-source]').evaluate('(n)=>{n.closest("details").open=true;n.closest(".a3-module-settings").open=true}')
        page.locator('[data-m-source]').set_input_files('Data/Subsidence/Mashhad_cumulative.csv')
        page.locator('[data-m-sub=calendar_basis]').select_option('persian')
        page.locator('[data-m-sub=start_water_year]').fill('1395')
        page.locator('[data-m-sub=end_water_year]').fill('1404')
        page.locator('[data-m-sub=duration_years]').fill('10')
        page.locator('[data-m-sub=component]').select_option('vertical')
        page.locator('[data-m-sub=direction]').select_option('down')
        page.locator('[data-m-run]').click()
        page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
        open_section(page,'lifetime')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        root.locator('[data-lt-preset]').select_option('all_base')
        page.wait_for_function("!document.querySelector('[data-lt-preset-apply]').disabled",timeout=60000)
        root.locator('[data-lt-preset-apply]').click()
        assert root.locator('[data-lt=quantity_on]').is_checked()
        assert root.locator('[data-lt=quality_on]').is_checked()
        assert root.locator('[data-lt-prereq=subsidence]').get_attribute('data-ready')=='true'
        assert root.locator('[data-lt=subsidence_limit]').is_enabled()
        # Changing quality invalidates readiness, preventing a combined run until rerun.
        open_section(page,'quality')
        page.locator('[data-q-drink]').evaluate('(n)=>{for(let p=n.parentElement;p;p=p.parentElement)if(p.tagName==="DETAILS")p.open=true}')
        page.locator('[data-q-drink]').fill('1600')
        page.locator('[data-q-drink]').dispatch_event('change')
        open_section(page,'lifetime')
        assert root.locator('[data-lt-prereq=quality]').get_attribute('data-ready')=='false'
        assert root.locator('[data-lt-run]').is_disabled()
        assert root.locator('[data-lt=quality_limit]').is_disabled()
        assert 'آماده‌سازی' in root.locator('[data-lt-status]').text_content()
        root.locator('[data-lt=quality_on]').uncheck()
        assert root.locator('[data-lt=subsidence_on]').is_checked()
        assert float(root.locator('[data-lt=subsidence_limit]').input_value())>0
        # A different aquifer must start with empty user-layer selections.
        value=page.locator('#aquiferSelect3d option').filter(has_text='نیشابور / نیشابور').first.get_attribute('value')
        edit_selection(page)
        page.locator('#aquiferSelect3d').select_option(value)
        try:
            page.wait_for_function("document.querySelector('#a3Workspace').dataset.settings==='open'&&!document.querySelector('#build3d').disabled",timeout=30000)
        except Exception:
            print(json.dumps({'state':page.locator('#status3d').text_content(),'errors':errors,'aq':page.locator('#aquiferSelect3d').input_value()}));raise
        assert page.locator('#syInput').input_value()==''
        assert page.locator('#bedrockFile').input_value()==''
        assert page.locator('#qualityInputFile').input_value()==''
        page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        assert 'نیازمند' in page.locator('#volumeAfterMetric').text_content()
        assert 'سطح آب' in page.locator('#sceneGeology h3').text_content()
        open_section(page,'lifetime')
        page.wait_for_function("document.querySelector('[data-lt-status]').textContent.includes('داده‌های معیار کمّی')",timeout=120000)
        assert page.locator('[data-lt-run]').is_disabled()
        assert page.locator('[data-lt-quantity-missing]').is_visible()
        page.locator('[data-lt=quantity_type]').select_option('drawdown')
        page.locator('[data-lt=quantity_limit]').fill('10')
        assert page.locator('[data-lt-run]').is_enabled()
        forbidden=['/data/MASHHAD_BEDROCK','/data/NEYSHABUR_BEDROCK','/water-quality/WaterQ.csv','/water-quality/covariates','/water-quality/geology','/water-quality/sources.json','/subsidence/sources.json','/subsidence/Mashhad']
        fetched=[u for u in requests if any(part in u for part in forbidden)]
        assert not fetched,fetched
        assert not errors,errors
        browser.close()
    print(json.dumps({'passed':True,'audit':{k:v for k,v in report['unknown_diagnostics'].items() if k!='excluded_wells'},'full_coverage':full_report['spatial_coverage'],'full_unknown_pct':full_report['unknown_area_pct'],'forbidden_default_fetches':fetched},ensure_ascii=True))


if __name__=='__main__':main()


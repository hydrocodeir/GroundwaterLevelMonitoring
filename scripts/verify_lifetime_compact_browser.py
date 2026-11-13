"""Exercise compact scenario controls and downloadable quality templates in real Pyodide."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, open_section


def main():
    out=Path('.tmp/lifetime-compact');out.mkdir(parents=True,exist_ok=True)
    errors=[];leaks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:leaks.append(r.url) if r.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#a3Workspace').dataset.settings==='open'&&!document.querySelector('#build3d').disabled",timeout=180000)
        page.locator('[data-input-layer=quality]>summary').click()
        with page.expect_download() as pending:page.locator('[data-input-template=quality]').click()
        pending.value.save_as(out/'quality-template.csv')
        header=(out/'quality-template.csv').read_text('utf-8-sig').strip()
        assert header=='longitude,latitude,ec,sar,year_persian,month_persian'
        assert page.locator('#qualityInputFile').evaluate('(n)=>n.files.length')==0
        guide=page.request.get('http://127.0.0.1:8767/assets/templates/quality-guide.html')
        assert guide.ok and 'quality-example.csv' in guide.text() and '۱۰۰۰' in guide.text()
        choose_test_layers(page,quality=True)
        print('Model and template ready',flush=True)
        open_section(page,'lifetime');root=page.locator('#lifetimeTools')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        def editor():
            if root.locator('.lt-editor').get_attribute('open') is None:root.locator('.lt-editor>summary').click()
        def pane(key):
            editor();root.locator(f'[data-lt-criterion-open={key}]').click()
            assert root.locator(f'[data-lt-panel={key}]').is_visible()
            assert root.locator('[data-lt-panel]:visible').count()==1
        def run():
            root.locator('[data-lt-run]').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            return json.loads(root.locator('[data-lt-metadata]').text_content())
        assert root.locator('[data-lt-panel]:visible').count()==1
        assert root.locator('[data-lt=quantity_on]').is_visible()
        assert root.locator('[data-lt=quality_on]').is_visible()
        assert root.locator('[data-lt=subsidence_on]').is_visible()
        assert root.locator('[data-lt=climate_on]').is_visible()
        assert root.locator('[data-lt=quality_on]').is_disabled()
        assert root.locator('[data-lt-prereq=quality] [data-lt-prepare]').is_visible()
        for key in ['quality','subsidence']:
            root.locator(f'[data-lt-prereq={key}] .hydro-info-trigger').click()
            assert 'اجرا' in page.locator('#hydroTooltip').text_content()
            page.keyboard.press('Escape')
        pane('quantity');root.locator('[data-lt=quantity_type]').select_option('drawdown');root.locator('[data-lt=quantity_limit]').fill('10')
        initial=run()
        print('Initial scenario ready',flush=True)
        assert initial['unknown_area_pct']<100
        root.locator('[data-lt-edit]').click();assert root.locator('.lt-editor').get_attribute('open') is not None
        # Changing panes preserves fields and never turns a criterion on implicitly.
        pane('climate');assert not root.locator('[data-lt=climate_on]').is_checked()
        root.locator('[data-lt-enable=climate]').click()
        root.locator('[data-lt=climate_temp_c]').fill('1.5')
        root.locator('[data-lt=climate_on]').uncheck();pane('quantity')
        assert root.locator('[data-lt=quantity_limit]').input_value()=='10'
        pane('climate');root.locator('[data-lt-enable=climate]').click()
        assert root.locator('[data-lt=climate_temp_c]').input_value()=='1.5'
        root.locator('[data-lt=climate_on]').uncheck()
        open_section(page,'quality')
        if page.locator('[data-analysis-settings=quality]').get_attribute('open') is None:page.locator('[data-analysis-settings=quality]>summary').click()
        with page.expect_download() as pending:page.locator('[data-q-template]').click()
        pending.value.save_as(out/'quality-template-from-module.csv')
        assert (out/'quality-template-from-module.csv').read_bytes()==(out/'quality-template.csv').read_bytes()
        page.locator('[data-q-run]').click();page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        print('Quality and template download ready',flush=True)
        points=[v for v in initial['base_model']['grid']['points'] if v[5]]
        annual='longitude,latitude,water_year,rate_mm_year\n'+''.join(f'{lon},{lat},{year},30\n' for lon,lat,*_ in points for year in range(1401,1405))
        open_section(page,'management');page.locator('[data-m-tab=subsidence]').click();page.locator('[data-m-open-source]').click()
        page.locator('[data-m-source]').set_input_files({'name':'QA-annual.csv','mimeType':'text/csv','buffer':annual.encode()})
        page.locator('[data-m-sub=component]').select_option('vertical');page.locator('[data-m-sub=direction]').select_option('down')
        page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
        open_section(page,'lifetime');page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        editor();root.locator('[data-lt=quality_on]').check();assert root.locator('[data-lt-panel=quality]').is_visible()
        root.locator('[data-lt=ec_growth_pct]').fill('2')
        root.locator('[data-lt=subsidence_on]').check();assert root.locator('[data-lt-panel=subsidence]').is_visible()
        root.locator('[data-lt=subsidence_limit]').fill('120')
        root.locator('[data-lt=climate_on]').check();pane('quantity')
        assert root.locator('[data-lt-panel]:visible').count()==1
        assert root.locator('.lt-editor').bounding_box()['height']<570
        assert root.locator('[data-lt=quantity_limit]').evaluate('(n)=>n.getBoundingClientRect().height')<=40
        root.locator('.lt-editor').screenshot(path=str(out/'desktop-editor.png'))
        page.screenshot(path=str(out/'desktop.png'))
        root.locator('[data-lt=quantity_type]').select_option('storage_loss_pct');root.locator('[data-lt=quantity_limit]').fill('25')
        assert root.locator('.lt-editor').bounding_box()['height']<570
        root.locator('.lt-editor').screenshot(path=str(out/'desktop-storage-editor.png'))
        root.locator('[data-lt=quantity_type]').select_option('drawdown');root.locator('[data-lt=quantity_limit]').fill('10')
        # Navigation is available to keyboard users, independently of enable switches.
        root.locator('[data-lt-criterion-open=quantity]').focus();page.keyboard.press('ArrowLeft')
        assert root.locator('[data-lt-panel=quality]').is_visible()
        assert root.locator('[data-lt=ec_growth_pct]').input_value()=='2'
        for width in [1440,1024,768,390]:
            page.set_viewport_size({'width':width,'height':950})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            for key in ['quantity','quality','subsidence','climate']:
                pane(key)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,key)
                for field in root.locator(f'[data-lt-panel={key}] input:visible, [data-lt-panel={key}] select:visible').all():
                    bounds=field.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=width+1,(width,key,bounds)
            if width==390:
                root.locator('.lt-editor').screenshot(path=str(out/'mobile-editor.png'))
                assert root.locator('[data-lt=climate_temp_c]').evaluate('(n)=>n.getBoundingClientRect().height')>=44
        page.set_viewport_size({'width':1600,'height':1050});root.locator('[data-lt=climate_on]').uncheck()
        combined=run()
        assert combined['scenario']['quantity_on'] and combined['scenario']['quality_on'] and combined['scenario']['subsidence_on']
        assert combined['scenario']['quantity_limit']==10 and combined['scenario']['ec_growth_pct']==2 and combined['scenario']['subsidence_limit']==120
        assert not combined['scenario']['climate_on'] and combined['quality_model']['sites']>20
        assert not errors,errors
        assert not leaks,leaks
        (out/'summary.json').write_text(json.dumps({'passed':True,'template_columns':header.split(','),'criterion_panes':4,'desktop_editor_max_height_px':570,'viewports':[1440,1024,768,390],'page_errors':errors,'data_uploads':leaks},ensure_ascii=False,indent=2),'utf-8')
        browser.close()
    print(json.dumps({'passed':True,'artifacts':str(out),'page_errors':errors}))


if __name__=='__main__':main()

"""Real browser/Pyodide scenario workflow, exports, source invalidation and mobile."""
import json
import math
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, choose_test_subsidence, open_section

def main():
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];leaks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:leaks.append(r.url) if r.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        choose_test_subsidence(page)
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        open_section(page,'lifetime')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        root=page.locator('#lifetimeTools')
        assert root.is_visible()
        assert not root.locator('[data-lt-climate]').is_visible()
        assert not root.locator('.lt-advanced .lt-basics').first.is_visible()
        root.locator('[data-lt=quantity_type]').select_option('drawdown')
        root.locator('[data-lt=quantity_limit]').fill('10')
        root.locator('[data-lt=name]').fill('QA base')
        def run():
            root.locator('[data-lt-run]').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            return json.loads(root.locator('[data-lt-metadata]').text_content())
        first=run()
        assert first['unknown_area_pct']<100
        assert root.locator('.lt-map [data-cell]').count()>100
        assert root.locator('.lt-map [data-map-cities]').count()==1
        assert not root.locator('[data-help-copy]').first.is_visible()
        root.locator('.lt-map [data-cell]').nth(100).click(force=True)
        assert 'عمر' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape')
        page.screenshot(path=str(out/'desktop.png'),full_page=True)
        # A second scenario is kept alongside the base rather than overwriting it.
        root.locator('[data-lt-new]').click()
        root.locator('[data-lt=name]').fill('QA fast')
        root.locator('[data-lt=quantity_type]').select_option('drawdown')
        root.locator('[data-lt=quantity_limit]').fill('10')
        root.locator('[data-lt=drop_factor]').fill('2')
        second=run()
        assert second['area_target_years']<first['area_target_years']
        root.locator('[data-lt-view]').select_option('compare')
        other=root.locator('[data-lt-compare] option').nth(1).get_attribute('value')
        root.locator('[data-lt-compare]').select_option(other)
        assert root.locator('.lt-secondary-map .a3-plan-svg').is_visible()
        assert json.loads(root.locator('.lt-secondary-map metadata').text_content())['lifetime']['scenario']['name']=='QA base'
        # A changed draft must not corrupt a scenario exported from the last result.
        root.locator('.lt-editor>summary').click()
        root.locator('[data-lt=drop_factor]').fill('7')
        assert root.locator('[data-lt-stale]').is_visible()
        with page.expect_download() as pending:root.locator('[data-lt-export=scenario]').click()
        path=out/'scenario.json';pending.value.save_as(path)
        assert json.loads(path.read_text('utf-8'))['scenario']['drop_factor']==2
        root.locator('[data-lt=drop_factor]').fill('2')
        root.locator('[data-lt-view]').select_option('3d')
        assert root.locator('.lt-3d canvas:not(.aquifer3d-overlay)').is_visible()
        root.locator('[data-lt-zoom=in]').click()
        assert '۱۲۵' in root.locator('[data-lt-zoom-label]').text_content()
        root.locator('[data-lt-pan]').click()
        canvas=root.locator('.lt-3d canvas:not(.aquifer3d-overlay)');canvas.scroll_into_view_if_needed();box=canvas.bounding_box()
        x,y=box['x']+box['width']/2,box['y']+box['height']/2
        before=canvas.screenshot()
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+60,y+30,steps=5);page.mouse.up()
        assert canvas.screenshot()!=before
        root.locator('[data-lt-camera]').select_option('top')
        page.screenshot(path=str(out/'3d.png'),full_page=True)
        # GeoTIFF is produced by browser Python, never a backend export endpoint.
        with page.expect_download(timeout=90000) as pending:root.locator('[data-lt-export=tiff]').click()
        pending.value.save_as(out/'lifetime.tif')
        from PIL import Image
        with Image.open(out/'lifetime.tif') as im:
            assert im.mode=='F' and im.width>10 and im.height>10
            assert im.tag_v2[34735][-1]==4326
            assert any(v>=0 for v in list(im.getdata()))
        # Climate on without data must produce unknown, with an explicit off comparison.
        root.locator('[data-lt=climate_on]').check()
        climate=run()
        assert not climate['climate']['accepted'] and climate['unknown_area_pct']==100
        root.locator('[data-lt-view]').select_option('climate')
        assert root.locator('.lt-secondary-map .a3-plan-svg').is_visible()
        counter=json.loads(root.locator('.lt-secondary-map metadata').text_content())['lifetime']
        assert counter['unknown_area_pct']<100 and not counter['scenario']['climate_on']
        # Invalid climate CSV preserves the last successful display and reports error.
        root.locator('.lt-editor>summary').click()
        root.locator('[data-lt-climate-file]').set_input_files({'name':'bad.csv','mimeType':'text/csv','buffer':b'bad,columns\n1,2\n'})
        root.locator('[data-lt-run]').click();page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=60000)
        assert 'محاسبه و ذخیره' not in root.locator('[data-lt-status]').text_content()
        assert root.locator('[data-lt-stale]').is_visible()
        assert json.loads(root.locator('[data-lt-metadata]').text_content())==climate
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(out/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        # Exercise actual NumPy temporal fitting before the quality/BLAS loader.
        # Artificial climate is QA input only and is never a project default.
        climate_csv='water_year,precip_mm,temp_c\n'+''.join(f'{y},{250+50*math.sin(y*.7)},{15+math.cos(y*1.1)}\n' for y in range(1370,1405))
        root.locator('[data-lt-climate-file]').set_input_files({'name':'QA-artificial-climate.csv','mimeType':'text/csv','buffer':climate_csv.encode()})
        page.wait_for_function("document.querySelector('[data-lt-climate-name]').textContent==='QA-artificial-climate.csv'")
        fitted=run()
        assert 'mae_m_year' in fitted['climate'],fitted['climate']
        assert fitted['climate']['holdout_count']>=4
        # Real EC model and real cumulative settlement must reach the new engine.
        page.set_viewport_size({'width':1600,'height':1050})
        open_section(page,'quality')
        page.locator('[data-q-run]').click()
        page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        open_section(page,'lifetime')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        assert root.locator('[data-lt-stale]').is_visible()
        root.locator('[data-lt-saved]').select_option(label='QA base')
        with_quality=run()
        assert with_quality['quality_model']['sites']>20
        assert with_quality['curves'][0]['usable_mcm']>0
        root.locator('.lt-editor>summary').click()
        root.locator('[data-lt=quality_on]').check()
        root.locator('[data-lt=subsidence_on]').check()
        root.locator('[data-lt=subsidence_limit]').fill('100')
        root.locator('.lt-advanced').evaluate('(n)=>n.open=true')
        root.locator('[data-lt=sensitivity_on]').check()
        root.locator('[data-lt=sensitivity_floor_m]').fill('5')
        root.locator('[data-lt=sensitivity_sy_pct]').fill('20')
        combined=run()
        assert combined['subsidence_source']['input_records']>200000
        assert combined['quality_model']['aquifer']==combined['aquifer']
        assert combined['base_model']['physical_grid_sha256']
        assert len(combined['sensitivity']['summary'])==3
        root.locator('.lt-cards article .hydro-info-trigger').first.click()
        assert 'مرکزی' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape')
        assert not root.locator('.lt-editor').get_attribute('open')
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(out/'combined-desktop.png'),full_page=True)
        # Import restores the exported applied configuration, not a later draft.
        root.locator('[data-lt-import-file]').set_input_files(out/'scenario.json')
        page.wait_for_function("document.querySelector('[data-lt=drop_factor]').value==='2' && !document.querySelector('[data-lt=quality_on]').checked")
        assert root.locator('[data-lt=drop_factor]').input_value()=='2'
        assert not root.locator('[data-lt=climate_on]').is_checked()
        assert not root.locator('[data-lt=quality_on]').is_checked()
        # Loading a scenario keeps the user's current file, without restoring embedded data.
        assert root.locator('[data-lt-climate-file]').evaluate('(n)=>n.files[0]?.name')=='QA-artificial-climate.csv'
        assert not leaks,leaks
        assert not errors,errors
        (out/'summary.json').write_text(json.dumps({'first':first,'second':second,'climate':climate,'combined':combined,'page_errors':errors},ensure_ascii=False,indent=2),'utf-8')
        browser.close()
    print(json.dumps({'passed':True,'artifacts':str(out)}))

if __name__=='__main__':main()



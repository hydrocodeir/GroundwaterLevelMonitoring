"""Real worker grid configuration, display intervals, rollback and rectangular GeoTIFF."""
import json
import math
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, open_section


def main():
    out=Path('.tmp/grid-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];uploads=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:uploads.append(r.url) if r.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        assert page.locator('#pixelWidthInput').input_value()=='4000'
        assert page.locator('#pixelHeightInput').input_value()=='4000'
        def lifetime(horizon):
            open_section(page,'lifetime')
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
            root=page.locator('#lifetimeTools')
            if root.locator('.lt-editor').get_attribute('open') is None:root.locator('.lt-editor>summary').click()
            root.locator('[data-lt=quantity_type]').select_option('drawdown');root.locator('[data-lt=quantity_limit]').fill('10')
            root.locator('[data-lt=horizon]').fill(str(horizon));root.locator('[data-lt-run]').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            return root,json.loads(root.locator('[data-lt-metadata]').text_content())
        root,default=lifetime(150)
        assert default['base_model']['pixel_grid']['cell_width_m']==4000
        assert default['base_model']['pixel_grid']['cell_height_m']==4000
        assert default['bands']==[25,50,75,100,125,150]
        assert default['display_years']==[0,25,50,75,100,125,150]
        assert len(default['curves'])==151
        root.locator('.lt-curves>summary').click()
        assert root.locator('[data-lt-rows] tr').evaluate_all('(nodes)=>nodes.map(n=>Number(n.dataset.ltDisplayYear))')==default['display_years']
        assert root.locator('[data-lt-charts] svg').first.locator('[data-lt-axis-year]').evaluate_all('(nodes)=>nodes.map(n=>Number(n.dataset.ltAxisYear))')==default['display_years']
        root.locator('[data-lt-charts]').screenshot(path=str(out/'150-year-curves.png'))
        print('Default 4 km grid and 25-year display passed',flush=True)
        # Invalid dimensions preserve the last successful result; rollback restores both fields.
        root.locator('[data-lt-grid]').click();assert page.locator('#pixelWidthInput').is_visible()
        page.locator('#pixelWidthInput').fill('0');page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='error'")
        assert 'پیکسل' in page.locator('#a3SettingsFeedback').text_content()
        assert json.loads(root.locator('[data-lt-metadata]').text_content())==default
        page.locator('#pixelWidthInput').fill('2000');page.locator('#pixelHeightInput').fill('6000')
        page.locator('#closeA3Settings').click();page.locator('#a3DiscardDraft').click()
        assert page.locator('#pixelWidthInput').input_value()=='4000' and page.locator('#pixelHeightInput').input_value()=='4000'
        root.locator('[data-lt-grid]').click()
        page.locator('#pixelWidthInput').fill('2000');page.locator('#pixelHeightInput').fill('6000')
        page.locator('#a3SettingsApply').click()
        assert page.locator('#pixelWidthInput').is_disabled() and page.locator('#pixelHeightInput').is_disabled()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        root,rectangle=lifetime(137)
        grid=rectangle['base_model']['pixel_grid'];assert grid['cell_width_m']==2000 and grid['cell_height_m']==6000 and grid['side_m'] is None
        assert rectangle['base_model']['metrics']['drainable_after_mcm']==default['base_model']['metrics']['drainable_after_mcm']
        assert rectangle['display_years']==[0,25,50,75,100,125,137]
        assert len(rectangle['curves'])==138
        root.locator('.lt-curves>summary').click()
        axis=root.locator('[data-lt-charts] svg').first.locator('[data-lt-axis-year]').evaluate_all('(nodes)=>nodes.map(n=>Number(n.dataset.ltAxisYear))')
        assert axis==rectangle['display_years']
        metadata=json.loads(root.locator('.lt-map metadata').text_content())
        assert metadata['cell_width_m']==2000 and metadata['cell_height_m']==6000
        root.locator('.lt-map .a3-plan-svg').screenshot(path=str(out/'rectangular-pixel-map.png'))
        with page.expect_download(timeout=90000) as pending:root.locator('[data-lt-export=tiff]').click()
        pending.value.save_as(out/'rectangular-lifetime.tif')
        with Image.open(out/'rectangular-lifetime.tif') as image:
            dx,dy,_=image.tag_v2[33550]
            assert math.isclose(dx*111320*math.cos(math.radians(grid['reference_latitude'])),2000,rel_tol=1e-10)
            assert math.isclose(dy*111320,6000,rel_tol=1e-10)
            assert image.size==(grid['grid_cols'],grid['grid_rows'])
            assert json.loads(image.tag_v2[270])['pixel_grid']['cell_width_m']==2000
            assert any(v>=0 for v in image.getdata())
        # Quality receives the same rectangular grid, not an implicit square fallback.
        open_section(page,'quality');page.locator('[data-q-run]').click()
        page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        quality_grid=json.loads(page.locator('.a3-quality-map metadata').text_content())
        assert quality_grid['cell_width_m']==2000 and quality_grid['cell_height_m']==6000
        open_section(page,'lifetime')
        for width in [390,768,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            root.locator('[data-lt-grid]').click()
            assert page.locator('#pixelWidthInput').is_visible() and page.locator('#pixelHeightInput').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            page.locator('#closeA3Settings').click()
        assert not errors,errors
        assert not uploads,uploads
        (out/'summary.json').write_text(json.dumps({'passed':True,'default_grid':default['base_model']['pixel_grid'],'custom_grid':grid,'display_years':rectangle['display_years'],'page_errors':errors,'data_uploads':uploads},ensure_ascii=False,indent=2),'utf-8')
        browser.close()
    print(json.dumps({'passed':True,'artifacts':str(out),'page_errors':errors}))


if __name__=='__main__':main()

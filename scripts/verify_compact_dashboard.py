"""Real Pyodide models, mixed city/point data, uncluttered views and accessible tooltips."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, choose_test_subsidence, open_section


def main():
    out=Path('.tmp/compact-dashboard-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];backend=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:backend.append(r.url) if '/api/comparison' in r.url or '/api/aquifers/' in r.url else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        choose_test_subsidence(page)
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready' || document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        cities=page.evaluate('HydroCities.collection')
        assert len(cities['features'])==cities['metadata']['feature_count']
        assert cities['metadata']['point_count']>50
        assert {'شاندیز','طرقبه','چناران','گلبهار','فریمان','قدمگاه'}<={f['properties']['name'] for f in cities['features']}
        assert not page.locator('#comparisonIntro').is_visible()
        assert not page.locator('#saturatedCaption').is_visible()
        info=page.locator('#sceneGeology h3 .hydro-info-trigger')
        info.hover();assert not page.locator('#hydroTooltip').is_visible();info.click();page.wait_for_selector('#hydroTooltip:not([hidden])')
        assert 'اغراق قائم' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape');assert not page.locator('#hydroTooltip').is_visible()
        info.focus();assert page.locator('#hydroTooltip').is_visible()
        page.keyboard.press('Escape')
        page.screenshot(path=str(out/'3d-desktop.png'),full_page=True)
        page.locator('#sceneWaterTab').click()
        assert not page.locator('.a3-scene-context').is_visible()
        wrap=page.locator('#pixelCanvas').locator('..')
        first=wrap.screenshot()
        page.evaluate('HydroCities.setEnabled(false)')
        page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        second=wrap.screenshot()
        assert first==second,'City visibility changed the spatial water-column scene'
        page.evaluate('HydroCities.setEnabled(true)')
        page.locator('#waterMapTab').click()
        assert page.locator('#waterPercentMap [data-map-cities]').count()==0
        assert page.locator('#waterPercentMap [data-city-id]').count()==0
        assert json.loads(page.locator('#waterPercentMap metadata').text_content())['cities']['enabled'] is False
        open_section(page,'parameters')
        page.wait_for_function("document.querySelector('#parameterMaps metadata') && JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer?.input_records>0",timeout=60000)
        city=page.locator('#parameterMaps [data-city-id="osm-node-668711965"]')
        assert city.count()==1
        city.hover(force=True);assert 'شاندیز' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape')
        cell=page.locator('#parameterMaps [data-cell]').nth(100)
        cell.hover(force=True)
        assert not page.locator('#hydroTooltip').is_visible()
        cell.click(force=True)
        assert page.locator('#hydroTooltip').is_visible()
        assert 'طول' in page.locator('#hydroTooltip').text_content()
        page.keyboard.press('Escape')
        assert not page.locator('#parameterMaps .a3-map-note').is_visible()
        with page.expect_download() as dl:page.locator('#parameterMaps [data-export=svg]').click()
        path=out/'parameter-map.svg';dl.value.save_as(path)
        assert 'GHSL' in path.read_text(encoding='utf-8') and '<metadata>' in path.read_text(encoding='utf-8')
        page.set_viewport_size({'width':390,'height':844})
        open_section(page,'scenes')
        page.locator('#a3SceneSelect').select_option('geology')
        info=page.locator('#sceneGeology h3 .hydro-info-trigger');info.click()
        assert page.locator('#hydroTooltip').is_visible()
        bounds=page.locator('#hydroTooltip').bounding_box()
        assert bounds['x']>=0 and bounds['x']+bounds['width']<=390
        page.screenshot(path=str(out/'tooltip-mobile.png'))
        page.keyboard.press('Escape')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(out/'3d-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1600,'height':1050})
        page.goto('http://127.0.0.1:8767/',wait_until='domcontentloaded')
        page.locator('[data-selection-tab=map]').click()
        page.wait_for_selector('#aquiferSelectionMap [data-city-id="osm-node-668711965"]',timeout=60000)
        page.locator('#aquiferSelectionMap [data-city-id="osm-node-668711965"]').hover(force=True)
        page.wait_for_selector('.hydro-city-label',timeout=10000)
        assert 'شاندیز' in page.locator('.hydro-city-label').text_content()
        assert not page.locator('#aquiferSelectionMap .hydro-city-control small').is_visible()
        page.screenshot(path=str(out/'analysis.png'),full_page=True)
        page.goto('http://127.0.0.1:8767/comparison',wait_until='domcontentloaded')
        page.wait_for_selector('#comparisonMaps .hydro-city-control',timeout=120000)
        assert page.locator('#comparisonMaps [data-city-id]').count()==2*len(cities['features'])
        assert not page.locator('.comparison-page-heading>div>p').is_visible()
        page.screenshot(path=str(out/'comparison.png'),full_page=True)
        assert not errors,errors
        assert not backend,backend
        print(json.dumps({'status':'passed','city_count':len(cities['features']),'point_count':cities['metadata']['point_count'],'errors':errors,'backend_analysis':backend}))
        browser.close()


if __name__=='__main__':main()

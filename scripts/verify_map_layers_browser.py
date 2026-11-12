"""Real browser checks for public cities, dynamic subsidence and shared page styling."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    output=Path('.tmp/map-layers-qa');output.mkdir(parents=True,exist_ok=True)
    errors=[];backend_analysis=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        context=browser.new_context(viewport={'width':1600,'height':1050},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda r:backend_analysis.append(r.url) if '/api/comparison' in r.url or '/api/aquifers/' in r.url else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready' || document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').inner_text()
        assert '۰ مرکز' not in page.locator('#a3CitiesNote').inner_text(),page.locator('#a3CitiesNote').inner_text()
        city_count=page.evaluate('HydroCities.collection.features.length')
        assert city_count>=100
        assert page.locator('#a3CameraView option').all_text_contents()==['شمال','جنوب','شرق','غرب','بالا','مایل']
        # Exercise each camera and save the actual view for independent angle checks.
        expected={'north':3.141592653589793,'south':0,'east':-1.5707963267948966,'west':1.5707963267948966,'top':0,'oblique':.6}
        page.emulate_media(reduced_motion='reduce')
        for key,yaw in expected.items():
            page.locator('#a3CameraView').select_option(key)
            page.locator('#a3Nav-tools').click();page.locator('#a3Tab-views').click()
            page.locator('#a3ViewName').fill('QA '+key);page.locator('#a3SaveView').click()
            camera=page.evaluate("JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('aquifer3d:views:')))).at(-1).view.camera")
            assert abs(((camera['yaw']-yaw+3.141592653589793)%(2*3.141592653589793))-3.141592653589793)<1e-7,camera
            page.locator('#a3Nav-scenes').click()
        page.screenshot(path=str(output/'3d-cities-desktop.png'),full_page=True)
        page.locator('#a3Nav-parameters').click()
        page.wait_for_function("document.querySelector('#parameterMaps metadata') && JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer?.input_records>0",timeout=90000)
        parameter=page.locator('#parameterMaps')
        parameter.locator('select').select_option('management_subsidence_cumulative')
        assert '1395' in parameter.locator('.a3-plan-svg').text_content() and '1404' in parameter.locator('.a3-plan-svg').text_content()
        assert 'Mashhad_cumulative.csv' in parameter.locator('.a3-map-note').inner_text()
        assert parameter.locator('[data-city-id]').count()>=1
        before=parameter.locator('svg path[data-cell] title').all_text_contents()
        assert any('نامشخص' not in text for text in before)
        parameter.screenshot(path=str(output/'input-subsidence.png'))
        parameter.locator('[data-map-cities]').uncheck()
        assert parameter.locator('[data-city-overlay]').evaluate('(g)=>getComputedStyle(g).display')=='none'
        page.locator('#a3Nav-scenes').click();assert not page.locator('#a3CitiesToggle').is_checked()
        page.locator('#a3CitiesToggle').check()
        page.locator('#a3Nav-management').click()
        page.locator('[data-analysis-settings=management]').evaluate('(n)=>n.open=true')
        page.locator('[data-m-source-details]').evaluate('(n)=>n.open=true')
        duration=page.locator('[data-m-sub=duration_years]')
        duration.fill('20');duration.press('Tab')
        page.wait_for_function("document.querySelector('#parameterMaps metadata') && JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer?.duration_years===20",timeout=60000)
        page.locator('#a3Nav-parameters').click()
        assert parameter.locator('svg path[data-cell] title').all_text_contents()==before
        parameter.locator('select').select_option('management_subsidence')
        with page.expect_download() as dl:parameter.locator('[data-export=geojson]').click()
        target=output/'subsidence-layer.geojson';dl.value.save_as(target)
        exported=json.loads(target.read_text(encoding='utf-8'))
        assert exported['metadata']['subsidence_layer']['duration_years']==20
        for feature in exported['features']:
            c=feature['properties']
            if c['management_subsidence_cumulative'] is not None:
                assert abs(c['management_subsidence']-c['management_subsidence_cumulative']/20)<1e-8
        # Another aquifer must not retain the Mashhad layer or label.
        page.locator('#aquiferSelect3d').select_option(label=next(s for s in page.locator('#aquiferSelect3d option').all_text_contents() if s.endswith('/ نیشابور')))
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'",timeout=120000)
        page.locator('#a3Nav-parameters').click()
        page.wait_for_function("document.querySelector('#parameterMaps metadata') && JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer",timeout=60000)
        parameter.locator('select').select_option('management_subsidence_cumulative')
        assert all('نامشخص' in text for text in parameter.locator('svg path[data-cell] title').all_text_contents())
        assert 'نیشابور' in parameter.locator('[data-city-overlay]').text_content()
        # The same context layer is present on the analysis selection map.
        page.goto('http://127.0.0.1:8767/',wait_until='domcontentloaded')
        page.locator('[data-selection-tab=map]').click()
        page.wait_for_selector('#aquiferSelectionMap [data-city-id]',timeout=60000)
        assert page.locator('#aquiferSelectionMap [data-city-id]').count()==city_count
        assert page.locator('#aquiferSelectionMap .hydro-city-control input').is_checked()
        assert page.locator('#aquiferSelectionMap .leaflet-hydroCity-pane').evaluate('(n)=>getComputedStyle(n).pointerEvents')=='none'
        page.screenshot(path=str(output/'analysis-desktop.png'),full_page=True)
        for width in (1280,768,390):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('analysis',width)
        page.wait_for_timeout(600)  # Leaflet's resize settling, without any network dependency.
        page.screenshot(path=str(output/'analysis-mobile.png'),full_page=True)
        # Comparison maps share the same toggled layer and header/control theme.
        page.set_viewport_size({'width':1600,'height':1050})
        page.goto('http://127.0.0.1:8767/comparison',wait_until='domcontentloaded')
        page.wait_for_selector('#comparisonMaps [data-city-id]',timeout=180000)
        assert page.locator('#comparisonMaps .hydro-city-control input').count()==2
        page.locator('#comparisonMaps .hydro-city-control input').first.uncheck()
        assert not page.locator('#comparisonMaps .hydro-city-control input').last.is_checked()
        page.locator('#comparisonMaps .hydro-city-control input').last.check()
        page.screenshot(path=str(output/'comparison-desktop.png'),full_page=True)
        for width in (1280,768,390):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),('comparison',width)
        page.screenshot(path=str(output/'comparison-mobile.png'),full_page=True)
        assert not errors,errors
        assert not backend_analysis,backend_analysis
        print(json.dumps({'status':'passed','cities':city_count,'camera_presets':list(expected),'errors':errors,'screenshots':str(output)}))
        browser.close()


if __name__=='__main__':main()

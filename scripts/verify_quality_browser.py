"""End-to-end quality model verification with actual browser Pyodide and CSV exports."""
import csv
import io
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, choose_test_subsidence, open_section


def main():
    out=Path('.tmp/waterq-browser-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];posts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1100},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda request:posts.append(request.url) if request.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=%D9%85%D8%B4%D9%87%D8%AF',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        page.wait_for_function("document.querySelector('#status3d').textContent.includes('آماده است') || document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')!='error',repr(page.locator('#status3d').inner_text())
        open_section(page,'quality')
        root=page.locator('#qualityTools')
        def run():
            root.locator('[data-q-run]').click()
            page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
            assert root.locator('[data-q-results]').is_visible(),repr(root.locator('[data-q-status]').inner_text())
            assert not errors,errors
        run()
        meta=json.loads(root.locator('metadata').text_content())
        report=meta['quality_model'];volumes=report['volumes_mcm']
        assert report['sites']>=15
        assert volumes['drinking']<=report['total_remaining_mcm']-volumes['unknown']+1e-8
        assert volumes['irrigation']<=report['total_remaining_mcm']-volumes['irrigation_unknown']+1e-8
        assert root.locator('[data-cell]').count()>100
        open_section(page,'management')
        page.wait_for_function("document.querySelector('#managementTools metadata') && JSON.parse(document.querySelector('#managementTools metadata').textContent).management.quality_supported_area_pct>0",timeout=60000)
        management=json.loads(page.locator('#managementTools metadata').text_content())['management']
        assert management['quality']['quality_water_year']==report['quality_water_year']
        open_section(page,'quality')
        root.screenshot(path=str(out/'quality-desktop.png'))
        root.locator('select').select_option('quality_ec')
        with page.expect_download() as download:root.locator('[data-export=png]').click()
        download.value.save_as(out/'quality-ec.png')
        with page.expect_download() as download:root.locator('[data-export=csv]').click()
        path=out/'quality-grid.csv';download.value.save_as(path)
        rows=list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        assert rows and 'quality_supported' in rows[0] and 'quality_usable_pct' in rows[0]
        root.locator('[data-analysis-settings=quality]').evaluate('(n)=>n.open=true')
        root.locator('[data-q-drink]').fill('500');root.locator('[data-q-drink]').press('Tab')
        page.wait_for_function("document.querySelector('#managementTools metadata') && JSON.parse(document.querySelector('#managementTools metadata').textContent).management.quality_supported_area_pct===0",timeout=60000)
        run()
        new_report=json.loads(root.locator('metadata').text_content())['quality_model']
        assert new_report['thresholds']['drinking_ec_uScm']==500
        assert new_report['volumes_mcm']['drinking']<volumes['drinking']
        page.set_viewport_size({'width':390,'height':844})
        root.locator('select').select_option('quality_zone_code')
        root.locator('.a3-quality-map').screenshot(path=str(out/'quality-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not posts,posts
        assert not errors,errors
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':'passed','selected':report['validation']['selected'],'sites':report['sites'],'post_requests':posts,'errors':errors}))
        browser.close()


if __name__=='__main__':main()

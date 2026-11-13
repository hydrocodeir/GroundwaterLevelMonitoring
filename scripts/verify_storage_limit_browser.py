"""Relative storage threshold, live Python preview and legacy scenario compatibility."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, choose_test_subsidence, open_section


def main():
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[];posts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1500,'height':1050})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method!='GET' else None)
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        open_section(page,'lifetime');root=page.locator('#lifetimeTools')
        def reference(percent=25):
            page.wait_for_function("p=>{try {const r=JSON.parse(document.querySelector('[data-lt-quantity-meta]').textContent);return r.limit===p;}catch{return false}}",arg=percent,timeout=60000)
            return json.loads(root.locator('[data-lt-quantity-meta]').text_content())
        run_count=0
        def run():
            nonlocal run_count
            root.locator('[data-lt-run]').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            with page.expect_download() as pending:root.locator('[data-lt-export=json]').click()
            path=out/f'percent-run-{run_count}.json';run_count+=1;pending.value.save_as(path)
            return json.loads(path.read_text('utf-8'))
        assert root.locator('[data-lt=quantity_type]').input_value()=='storage_loss_pct'
        assert root.locator('[data-lt=quantity_limit]').input_value()=='25'
        base=reference()
        assert base['initial_storage_mcm']>0
        assert abs(base['equivalent_loss_mcm']/base['initial_storage_mcm']-.25)<1e-8
        assert root.locator('[data-lt-storage-choice="25"]').get_attribute('aria-pressed')=='true'
        assert not root.locator('.lt-quantity-guide [data-help-copy]').is_visible()
        root.locator('[data-lt-storage-choice="10"]').click();reference(10)
        r10=run()
        root.locator('.lt-editor').evaluate('(n)=>n.open=true')
        root.locator('[data-lt-storage-choice="25"]').click();reference(25)
        r25=run()
        ratios=[b['life_years']/a['life_years'] for a,b in zip(r10['plan_maps']['cells'],r25['plan_maps']['cells']) if a['life_years'] is not None and b['life_years'] is not None and a['life_years']>0]
        assert ratios and all(abs(x-2.5)<1e-7 for x in ratios)
        # Sy alters the reference volume; the prescribed head crossing stays fixed.
        root.locator('.lt-editor').evaluate('(n)=>n.open=true')
        root.locator('.lt-advanced').evaluate('(n)=>n.open=true')
        root.locator('[data-lt=sy_factor]').fill('1.5')
        page.wait_for_function("b=>{try{return Math.abs(JSON.parse(document.querySelector('[data-lt-quantity-meta]').textContent).initial_storage_mcm/b-1.5)<1e-8}catch{return false}}",arg=base['initial_storage_mcm'])
        assert root.locator('[data-lt-stale]').is_visible()
        assert page.locator('#status3d').get_attribute('data-state')=='ready'
        r_sy=run()
        assert [c['life_years'] for c in r_sy['plan_maps']['cells']]==[c['life_years'] for c in r25['plan_maps']['cells']]
        root.locator('.lt-editor').evaluate('(n)=>n.open=true')
        root.locator('[data-lt=sy_factor]').fill('1');reference()
        # A percentage never becomes a metre/MSL threshold when switching modes.
        root.locator('[data-lt=quantity_type]').select_option('head')
        assert root.locator('[data-lt=quantity_limit]').input_value()==''
        assert root.locator('[data-lt=quantity_limit]').get_attribute('min') is None
        assert root.locator('[data-lt=quantity_limit]').get_attribute('max') is None
        assert not root.locator('[data-lt-quantity-guide]').is_visible()
        root.locator('[data-lt=quantity_limit]').fill('-10')
        root.locator('[data-lt=quantity_type]').select_option('storage_loss_pct')
        assert root.locator('[data-lt=quantity_limit]').input_value()=='25'
        reference()
        root.locator('.lt-advanced').evaluate('(n)=>n.open=false')
        page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'relative-storage-desktop.png'),full_page=True)
        # Earlier exports retain their metric meaning and numerical threshold.
        legacy={'schema':'aquifer-lifetime-v1','aquifer':r25['report']['aquifer'],'scenario':{**r25['report']['scenario'],'name':'Legacy drawdown','quantity_type':'drawdown','quantity_limit':10}}
        root.locator('[data-lt-import-file]').set_input_files({'name':'legacy.json','mimeType':'application/json','buffer':json.dumps(legacy).encode()})
        page.wait_for_function("document.querySelector('[data-lt=quantity_type]').value==='drawdown'",timeout=10000)
        assert root.locator('[data-lt=quantity_limit]').input_value()=='10'
        old=run();assert old['report']['scenario']['quantity_type']=='drawdown'
        root.locator('[data-lt-new]').click();reference()
        page.set_viewport_size({'width':390,'height':844});page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(out/'relative-storage-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        assert not posts,posts
        browser.close()
    print(json.dumps({'passed':True,'preview':'dynamic','percentage_crossings':'local','legacy_scenarios':'preserved','errors':errors}))


if __name__=='__main__':main()

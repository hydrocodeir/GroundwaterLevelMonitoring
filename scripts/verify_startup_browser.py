"""Reproduce stale-module startup failure and verify visible errors/recovery."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8767');args=parser.parse_args()
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        context=browser.new_context(service_workers='block',viewport={'width':1500,'height':960})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        # Exactly the old-workspace failure: the newly added tab has no label.
        # The import completes, then mounting throws before worker startup.
        stale="export function mountWorkspace(){const sections={scenes:['view']};for(const tab of document.querySelectorAll('[data-workspace-tab]')){sections[tab.dataset.workspaceTab][0];}}"
        pattern='**/assets/js/aquifer3d-workspace.js?v=*'
        context.route(pattern,lambda route:route.fulfill(status=200,content_type='text/javascript',body=stale))
        page.goto(args.url+'/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='error'",timeout=15000)
        assert page.locator('#a3EmptyTitle').text_content()=='برنامه بارگذاری نشد'
        assert page.locator('#build3d').text_content()=='تلاش دوباره'
        assert "reading '0'" in page.locator('#status3d').get_attribute('title')
        page.screenshot(path=str(out/'startup-error.png'),full_page=True)
        # The retry gets current assets; no local storage or scenarios are cleared.
        page.evaluate("localStorage.setItem('startup-qa-preserved','keep')")
        context.unroute(pattern)
        page.locator('#build3d').click()
        choose_test_layers(page)
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||(document.querySelector('#status3d').dataset.state==='error'&&document.querySelector('#a3EmptyTitle').textContent!=='برنامه بارگذاری نشد')",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        assert page.evaluate("localStorage.getItem('startup-qa-preserved')")=='keep'
        assert not page.locator('#a3Nav-lifetime').is_disabled()
        page.screenshot(path=str(out/'startup-recovered.png'),full_page=True)
        assert not errors,errors
        # Missing module is also caught, instead of an endless initial spinner.
        broken=browser.new_context(service_workers='block')
        broken.route('**/assets/js/aquifer3d-lifetime.js?v=*',lambda route:route.fulfill(status=503,body='Temporarily unavailable'))
        missing=broken.new_page();missing.goto(args.url+'/aquifer-3d',wait_until='domcontentloaded')
        missing.wait_for_function("document.querySelector('#status3d').dataset.state==='error'",timeout=15000)
        assert not missing.locator('#a3EmptyAction').is_disabled()
        assert missing.locator('#a3EmptyAction').is_visible()
        browser.close()
    print(json.dumps({'passed':True,'stale_module':'caught','retry':'ready','missing_module':'caught','uncaught_errors':errors}))


if __name__=='__main__':main()

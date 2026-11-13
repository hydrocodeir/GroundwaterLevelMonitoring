"""Real manager journey: inputs, current status, scenario, export and dependency changes."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import open_section


def main():
    out=Path('.tmp/manager-flow');out.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#a3Workspace').dataset.settings==='open'&&!document.querySelector('#build3d').disabled",timeout=180000)
        assert page.locator('[data-flow-stage=inputs]').get_attribute('aria-current')=='step'
        assert page.locator('#a3Flow').evaluate('(n)=>n.inert')
        assert 'سطح آب' in page.locator('#a3InputScope').text_content()
        assert page.locator('#syInput').input_value()==''
        page.locator('#syInput').fill('.06')
        page.locator('#bedrockFile').set_input_files('Data/MASHHAD_BEDROCK_MSL.csv')
        assert 'برآورد ذخیره' in page.locator('#a3InputScope').text_content()
        page.locator('[data-clear-layer=bedrock]').click()
        assert page.locator('#bedrockFile').input_value()==''
        assert 'سنگ‌بستر' in page.locator('#a3InputScope').text_content()
        page.locator('#bedrockFile').set_input_files('Data/MASHHAD_BEDROCK_MSL.csv')
        page.locator('#qualityInputFile').set_input_files('Data/WaterQ.csv')
        page.screenshot(path=str(out/'inputs-desktop.png'))
        page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
        assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()
        assert page.locator('[data-flow-stage=status]').get_attribute('aria-current')=='step'
        assert page.locator('[data-workspace-tab]:visible').count()==3
        assert page.locator('#beforeCanvas').is_visible()
        assert not page.locator('#a3QuickControls').is_visible()
        page.locator('#a3EditSelection').click()
        assert page.locator('#aquiferSelect3d').is_visible()
        page.locator('#a3EditSelection').click()
        assert not page.locator('#a3QuickControls').is_visible()
        assert 'بررسی آستانه‌ها' in page.locator('[data-flow-analysis=quality]').text_content()
        page.screenshot(path=str(out/'status-desktop.png'),full_page=True)
        # Real keyboard navigation between the current stage's views.
        page.locator('#a3Nav-scenes').focus();page.keyboard.press('ArrowLeft')
        assert page.locator('#a3Nav-quality').get_attribute('aria-selected')=='true'
        assert page.locator('[data-q-file]').is_visible()
        page.locator('[data-flow-stage=decision]').click()
        assert page.locator('[data-workspace-tab]:visible').count()==2
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        page.locator('[data-lt=name]').fill('بررسی مدیریتی')
        page.locator('#a3FlowContinue').click()
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        report=json.loads(page.locator('[data-lt-metadata]').text_content())
        assert report['scenario']['name']=='بررسی مدیریتی'
        assert 'خروجی' in page.locator('#a3FlowContinue').text_content()
        page.locator('#a3FlowContinue').click()
        assert page.locator('[data-flow-stage=output]').get_attribute('aria-current')=='step'
        assert page.locator('#a3ExportPNG').is_visible()
        assert page.locator('#a3ExportHub').is_visible()
        with page.expect_download() as dl:
            page.locator('[data-flow-export=lifetime] button').filter(has_text='گزارش JSON').click()
        dl.value.save_as(out/'scenario-report.json')
        exported=json.loads((out/'scenario-report.json').read_text('utf-8'))
        assert exported['report']['scenario']['name']==report['scenario']['name']
        page.screenshot(path=str(out/'output-desktop.png'),full_page=True)
        page.locator('[data-flow-export=quality] button').filter(has_text='رفتن به تحلیل').click()
        assert page.locator('[data-q-file]').is_visible()
        page.locator('[data-q-run]').click()
        page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        page.locator('[data-flow-stage=output]').click()
        assert page.locator('[data-flow-export=quality] button').filter(has_text='گزارش JSON').is_enabled()
        assert page.locator('[data-flow-export=lifetime] button').filter(has_text='گزارش JSON').is_disabled()
        assert 'تغییر' in page.locator('[data-flow-export=lifetime]').text_content()
        for width in [390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':900})
            page.locator('[data-flow-stage=status]').click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            assert page.locator('[data-flow-stage=decision]').is_visible()
            assert page.locator('#a3Nav-scenes').is_visible()
            page.screenshot(path=str(out/f'status-{width}.png'),full_page=True)
            for stage in ['decision','output']:
                page.locator(f'[data-flow-stage={stage}]').click()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),(width,stage)
                if width==390:page.screenshot(path=str(out/f'{stage}-mobile.png'),full_page=True)
        # Mobile modal focus, trap, exit, and the primary journey remain usable.
        page.set_viewport_size({'width':390,'height':844})
        page.locator('[data-flow-stage=inputs]').click()
        page.keyboard.press('Shift+Tab')
        assert page.locator('#a3Settings').evaluate('(n)=>n.contains(document.activeElement)')
        page.screenshot(path=str(out/'inputs-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.keyboard.press('Escape')
        assert page.locator('[data-flow-stage=inputs]').evaluate('(n)=>n===document.activeElement')
        page.locator('[data-flow-stage=decision]').click()
        assert page.locator('#lifetimeTools').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()
    print(json.dumps({'passed':True,'page_errors':errors,'screenshots':str(out)},ensure_ascii=True))


if __name__=='__main__':main()

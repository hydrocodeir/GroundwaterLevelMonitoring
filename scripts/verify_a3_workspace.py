"""Exercise workspace navigation against the real browser model (no mocked results)."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, choose_test_subsidence, open_section


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8767')
    args = parser.parse_args()
    out = Path('.tmp/a3-redesign')
    out.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width':1600,'height':1100}, accept_downloads=True)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url+'/aquifer-3d?name=%D9%85%D8%B4%D9%87%D8%AF', wait_until='domcontentloaded')
        choose_test_layers(page,quality=True)
        def ready():
            page.wait_for_function("(document.querySelector('#a3Workspace').dataset.ready==='true' && document.querySelector('#status3d').dataset.state==='ready') || document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
            assert page.locator('#status3d').get_attribute('data-state')=='ready', page.locator('#status3d').inner_text()
            assert page.locator('#a3Workspace').get_attribute('data-ready')=='true', page.locator('#status3d').inner_text()
        ready()
        assert not errors, errors
        ids = page.locator('[id]').evaluate_all('(nodes)=>nodes.map(n=>n.id)')
        assert len(ids)==len(set(ids)), 'Duplicate DOM IDs'
        assert page.locator('#sceneGeology').is_visible()
        assert not page.locator('#sceneWater').is_visible()
        page.locator('#a3MoreMetrics').click()
        assert page.locator('#areaMetric').is_visible()
        page.locator('#a3MoreMetrics').click()
        assert not page.locator('#areaMetric').is_visible()
        page.screenshot(path=str(out/'desktop.png'), full_page=True)
        page.locator('#sceneWaterTab').click()
        assert page.locator('#sceneWater').is_visible()
        assert not page.locator('#sceneGeology').is_visible()
        page.locator('#waterMapTab').click()
        assert page.locator('#waterPercentMap .a3-plan-svg').is_visible()
        assert not page.locator('.aquifer3d-toolbar').is_visible()
        page.locator('#waterTotalTab').click()
        assert page.locator('#afterCanvas').is_visible()
        page.locator('#waterPixelTab').click()
        assert page.locator('.aquifer3d-toolbar').is_visible()
        page.locator('#sceneBothTab').click()
        assert page.locator('#sceneGeology').is_visible() and page.locator('#sceneWater').is_visible()
        open_section(page,'parameters')
        assert page.locator('#parameterMaps .a3-plan-svg').is_visible()
        open_section(page,'quality')
        assert page.locator('[data-q-run]').is_visible()
        open_section(page,'tools')
        page.locator('#a3Tab-section').click()
        assert page.locator('#a3SectionMap').is_visible()
        assert page.locator('#a3Tab-present').count()==0
        assert page.locator('#a3Present').count()==0
        assert page.locator('[data-open-tool=present]').count()==0
        page.locator('#a3Tab-compare').click()
        assert page.locator('#a3CompareA').is_visible()
        page.locator('#a3Tab-views').click()
        assert page.locator('#a3Presets button').all_text_contents()==['شمال','جنوب','شرق','غرب','بالا','مایل']
        page.locator('#a3Presets button').filter(has_text='شمال').click()
        assert page.locator('#a3Nav-scenes').get_attribute('aria-selected')=='true'
        assert page.locator('#a3CameraView').input_value()=='north'
        page.locator('#a3CameraView').select_option('oblique')
        open_section(page,'sources')
        assert not page.locator('#sourceNote').is_visible()
        page.locator('#a3Panel-sources .hydro-info-trigger').last.click()
        assert page.locator('#hydroTooltip').is_visible()
        page.keyboard.press('Escape')
        open_section(page,'scenes')
        page.locator('#sceneGeologyTab').click()
        old_volume=page.locator('#volumeAfterMetric').inner_text()
        initial_sy=page.locator('#syInput').input_value()
        page.locator('[data-flow-stage=inputs]').click()
        page.locator('#syInput').fill('0.07')
        assert page.locator('#a3Workspace').get_attribute('data-ready')=='true'
        assert not page.locator('#a3EmptyState').is_visible()
        assert not page.locator('#a3Nav-quality').is_disabled()
        assert page.locator('#volumeAfterMetric').inner_text()==old_volume
        page.keyboard.press('Escape')
        assert page.locator('#a3DraftNotice').is_visible()
        page.locator('#a3DiscardDraft').click()
        # A malformed uploaded dataset must leave the last successful model intact.
        page.locator('[data-flow-stage=inputs]').click()
        page.locator('#bedrockFile').evaluate('(n)=>n.closest("details").open=true')
        page.locator('#bedrockFile').set_input_files({'name':'invalid-qa.csv','mimeType':'text/csv','buffer':b'wrong,columns\n1,2\n'})
        page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='error'",timeout=60000)
        assert page.locator('#a3Workspace').get_attribute('data-ready')=='true'
        assert page.locator('#volumeAfterMetric').inner_text()==old_volume
        page.locator('#a3DiscardDraft').click()
        assert page.locator('#syInput').input_value()==initial_sy
        assert not page.locator('#a3DraftNotice').is_visible()
        page.locator('[data-flow-stage=inputs]').click()
        page.locator('#syInput').fill('0.07')
        busy=page.evaluate("""()=>{document.querySelector('#a3SettingsApply').click();return {
          state:document.querySelector('#status3d').dataset.state,
          discard:document.querySelector('#a3DiscardDraft').disabled,
          aquifer:document.querySelector('#aquiferSelect3d').disabled,
          baseline:document.querySelector('#baselineYear').disabled,
          sy:document.querySelector('#syInput').disabled,
          quality:document.querySelector('#a3Panel-quality').inert
        }}""")
        assert busy=={'state':'loading','discard':True,'aquifer':True,'baseline':True,'sy':True,'quality':True},busy
        ready()
        assert not page.locator('#a3Settings').is_visible()
        assert page.locator('#volumeAfterMetric').inner_text()!=old_volume
        applied_volume=page.locator('#volumeAfterMetric').inner_text()
        page.locator('[data-flow-stage=inputs]').click()
        page.locator('#syInput').fill('1.5')
        page.locator('#a3SettingsApply').click()
        page.wait_for_function("document.querySelector('#status3d').dataset.state==='error'")
        assert page.locator('#a3SettingsFeedback').is_visible()
        assert page.locator('#volumeAfterMetric').inner_text()==applied_volume
        page.keyboard.press('Escape')
        page.locator('#a3DiscardDraft').click()
        for width in (1920,1280,1024,768,390):
            page.set_viewport_size({'width':width,'height':950 if width>720 else 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), f'Overflow at {width}'
        page.screenshot(path=str(out/'mobile.png'), full_page=True)
        assert not page.locator('#volumeAfterMetric').is_visible()
        page.locator('#a3MobileSummary').click()
        assert page.locator('#volumeAfterMetric').is_visible()
        page.locator('#a3MobileSummary').click()
        page.locator('#a3SceneSelect').select_option('water')
        assert page.locator('#sceneWater').is_visible()
        page.locator('#a3SceneSelect').select_option('geology')
        page.locator('#a3CameraPresets > summary').click()
        assert page.locator('[data-camera=reset]').is_visible()
        page.locator('[data-camera=reset]').click()
        page.locator('#a3CameraPresets > summary').click()
        page.locator('[data-flow-stage=inputs]').click()
        assert page.locator('#a3Settings').is_visible()
        page.screenshot(path=str(out/'mobile-settings.png'))
        page.keyboard.press('Escape')
        assert not page.locator('#a3Settings').is_visible()
        assert page.locator('[data-flow-stage=inputs]').evaluate('(n)=>n===document.activeElement')
        open_section(page,'quality')
        assert page.locator('#a3Nav-quality').get_attribute('aria-selected')=='true'
        assert page.locator('[data-q-run]').is_visible()
        assert not errors, errors
        print(json.dumps({'status':'passed','errors':errors,'screenshots':str(out)}))
        browser.close()


if __name__=='__main__':
    main()

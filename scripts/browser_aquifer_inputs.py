"""QA-only explicit input choices; the app itself never loads these fixtures."""
def open_section(page,key):
    stage={'scenes':'status','quality':'status','parameters':'status','management':'decision','lifetime':'decision','tools':'output','sources':'output'}[key]
    if page.locator('#a3Workspace').get_attribute('data-stage')!=stage:
        page.locator(f'[data-flow-stage={stage}]').click()
    page.locator(f'#a3Nav-{key}').click()


def edit_selection(page):
    if not page.locator('#aquiferSelect3d').is_visible():page.locator('#a3EditSelection').click()


def choose_test_layers(page,quality=False):
    page.wait_for_function("document.querySelector('#a3Workspace').dataset.settings==='open'&&!document.querySelector('#build3d').disabled",timeout=180000)
    page.locator('#syInput').fill('.06')
    page.locator('#bedrockFile').evaluate('(n)=>n.closest("details").open=true')
    page.locator('#bedrockFile').set_input_files('Data/MASHHAD_BEDROCK_MSL.csv')
    if quality:page.locator('#qualityInputFile').set_input_files('Data/WaterQ.csv')
    page.locator('#a3SettingsApply').click()
    page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'||document.querySelector('#status3d').dataset.state==='error'",timeout=180000)
    assert page.locator('#status3d').get_attribute('data-state')=='ready',page.locator('#status3d').text_content()


def choose_test_subsidence(page):
    open_section(page,'management')
    page.locator('[data-m-source]').evaluate('(n)=>{n.closest("details").open=true;const p=n.closest(".a3-module-settings");if(p)p.open=true;}')
    page.locator('[data-m-source]').set_input_files('Data/Subsidence/Mashhad_cumulative.csv')
    page.locator('[data-m-sub=calendar_basis]').select_option('persian')
    page.locator('[data-m-sub=start_water_year]').fill('1395')
    page.locator('[data-m-sub=end_water_year]').fill('1404')
    page.locator('[data-m-sub=duration_years]').fill('10')
    page.locator('[data-m-sub=component]').select_option('vertical')
    page.locator('[data-m-sub=direction]').select_option('down')
    page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=120000)
    page.locator('[data-m-run]').click()
    page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
    open_section(page,'scenes')

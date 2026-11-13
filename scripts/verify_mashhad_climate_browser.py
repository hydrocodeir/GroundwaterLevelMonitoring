"""Validate the actual exported climate CSV in the real scenario worker."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers, open_section


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8228);args=parser.parse_args()
    output=Path('Data/MASHHAD_CLIMATE');errors=[];uploads=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1500,'height':1000})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:uploads.append(request.url) if request.method!='GET' else None)
        page.goto(f'http://127.0.0.1:{args.port}/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page)
        open_section(page,'lifetime');root=page.locator('#lifetimeTools')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        root.locator('[data-lt=horizon]').fill('4')
        root.locator('[data-lt=climate_on]').check()
        root.locator('[data-lt-climate-file]').set_input_files(str(output/'MASHHAD_CLIMATE_WY.csv'))
        page.wait_for_function("document.querySelector('[data-lt-climate-name]').textContent==='MASHHAD_CLIMATE_WY.csv'")
        root.locator('[data-lt=climate_window]').select_option('4')
        root.locator('[data-lt-run]').click()
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
        assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
        report=json.loads(root.locator('[data-lt-metadata]').text_content())
        assert report['scenario']['climate_on']
        assert report['rate_audit']['climate']['available']
        assert report['rate_audit']['climate']['end_water_year']==report['reference_water_year']
        assert report['rate_audit']['climate']['start_water_year']==report['reference_water_year']-3
        assert report['input_files']['climate']=='MASHHAD_CLIMATE_WY.csv'
        assert report['rate_audit']['climate']['effect_applied']==report['climate']['accepted']
        assert not errors,errors
        assert not uploads,uploads
        result={'passed':True,'scenario_context':'Input/worker QA only, not a climate projection: actual project Mashhad piezometers, explicitly selected existing bedrock CSV and constant Sy=0.06, four-year trend and four-year horizon; no automatic default.',
                'reference_water_year':report['reference_water_year'],'climate':report['climate'],
                'rate_audit':report['rate_audit']['climate'],'input_files':report['input_files'],
                'page_errors':errors,'user_data_uploads':uploads}
        (output/'DASHBOARD_VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
        browser.close()
    print(json.dumps({'passed':True,'calibration_accepted':result['climate']['accepted'],'reason':result['climate']['reason'],
                      'overlap_years':result['climate'].get('years'),'page_errors':errors}))


if __name__=='__main__':main()

"""Real Pyodide methods/windows plus full-width SVG interaction and click-only cells."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_aquifer_inputs import choose_test_layers,open_section


def main():
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1820,'height':1000},accept_downloads=True)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8767/aquifer-3d?name=مشهد',wait_until='domcontentloaded')
        choose_test_layers(page,quality=True);open_section(page,'lifetime');root=page.locator('#lifetimeTools')
        page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        assert root.locator('[data-lt-spatial-edit]').is_visible()
        assert root.locator('[data-lt-spatial-edit]').evaluate('(n)=>n.compareDocumentPosition(document.querySelector("[data-lt-preset]"))&Node.DOCUMENT_POSITION_FOLLOWING')
        root.locator('[data-lt=quantity_window]').select_option('4')
        assert root.locator('[data-lt=spatial_coverage]').input_value()=='aquifer'
        def run():
            page.locator('#a3FlowContinue').click()
            page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            assert 'محاسبه و ذخیره' in root.locator('[data-lt-status]').text_content(),root.locator('[data-lt-status]').text_content()
            return json.loads(root.locator('[data-lt-metadata]').text_content())
        first=run();assert first['rate_audit']['quantity']['start_water_year']==first['reference_water_year']-3
        root.locator('.lt-curves>summary').click()
        charts=root.locator('[data-lt-charts]')
        assert charts.locator('figcaption').count()==2
        assert charts.locator('svg').evaluate_all('(nodes)=>nodes.every(svg=>[...svg.querySelectorAll("text")].every(n=>{const b=n.getBBox();return b.x>=0&&b.x+b.width<=svg.viewBox.baseVal.width+1}))')
        charts.screenshot(path=str(out/'curves-readable.png'))
        page.evaluate('HydroCities.setEnabled(false)')
        svg=root.locator('.lt-map .a3-plan-svg');svg.scroll_into_view_if_needed()
        bounds=svg.bounding_box();viewbox=svg.evaluate('(n)=>({w:n.viewBox.baseVal.width,h:n.viewBox.baseVal.height,clip:n.querySelector("clipPath rect").getAttribute("width")})')
        assert bounds['width']>1400 and abs(viewbox['w']-bounds['width'])<4
        assert float(viewbox['clip'])>bounds['width']*.95
        assert svg.locator('[data-cell] title').count()==0
        cell=svg.locator('[data-cell]').nth(100)
        cell.hover(force=True);assert not page.locator('#hydroTooltip').is_visible()
        cell.click(force=True);assert page.locator('#hydroTooltip').is_visible()
        page.keyboard.press('Escape')
        start=svg.locator('g[clip-path]>g').get_attribute('transform')
        page.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+250);page.mouse.down();page.mouse.move(bounds['x']+bounds['width']/2+85,bounds['y']+290,steps=20);page.mouse.up()
        assert svg.locator('g[clip-path]>g').get_attribute('transform')!=start
        assert not page.locator('#hydroTooltip').is_visible()
        svg.locator('..').locator('[data-zoom=fit]').click()
        svg.screenshot(path=str(out/'lifetime-full-width-map.png'))
        results={'idw':first}
        for method in ['spline','thiessen']:
            root.locator('[data-lt-spatial-edit]').click();page.locator('#spatialMethodInput').select_option(method);page.locator('#a3SettingsApply').click()
            page.wait_for_function("document.querySelector('#status3d').dataset.state==='ready'",timeout=180000)
            open_section(page,'lifetime');page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=180000)
            root.locator('[data-lt=quantity_window]').select_option('4')
            result=run();results[method]=result
            assert result['spatial_coverage']['estimator']==method
            assert result['rate_audit']['quantity']['spatial']['method']==method
            assert result['unknown_area_pct']<100
        assert results['spline']['curves'][-1]['remaining_mcm']!=results['thiessen']['curves'][-1]['remaining_mcm']
        root.locator('.lt-editor>summary').click()
        root.locator('[data-lt=quantity_window]').select_option('all')
        whole=run();assert whole['rate_audit']['quantity']['start_water_year']<=first['rate_audit']['quantity']['start_water_year']
        root.locator('.lt-editor>summary').click();root.locator('[data-lt=quantity_window]').select_option('10')
        ten=run();assert ten['rate_audit']['quantity']['start_water_year']==first['reference_water_year']-9
        root.locator('.lt-editor>summary').click();root.locator('[data-lt=quantity_window]').select_option('custom');root.locator('[data-lt=quantity_window_years]').fill('6')
        custom=run();assert custom['rate_audit']['quantity']['start_water_year']==first['reference_water_year']-5
        open_section(page,'quality');page.locator('[data-q-run]').click()
        page.wait_for_function("!document.querySelector('[data-q-run]').disabled",timeout=180000)
        assert page.locator('[data-q-results]').is_visible(),page.locator('[data-q-status]').text_content()
        open_section(page,'lifetime');page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        root.locator('.lt-editor>summary').click()
        root.locator('[data-lt=quality_on]').check();root.locator('[data-lt=quality_window]').select_option('4')
        assert root.locator('[data-lt=ec_growth_pct]').is_disabled()
        quality=run();assert quality['rate_audit']['quality']['mode']=='4'
        # Synthetic annual rates are selected only as explicit QA input.
        points=[v for v in first['base_model']['grid']['points'] if v[5]]
        annual='longitude,latitude,water_year,rate_mm_year\n'+''.join(f'{lon},{lat},{year},{20+10*(year-1401)}\n' for lon,lat,*_ in points for year in range(1401,1405))
        open_section(page,'management');page.locator('[data-m-tab=subsidence]').click();page.locator('[data-m-open-source]').click()
        page.locator('[data-m-source]').set_input_files({'name':'QA-annual.csv','mimeType':'text/csv','buffer':annual.encode()})
        page.locator('[data-m-sub=component]').select_option('vertical');page.locator('[data-m-sub=direction]').select_option('down')
        page.locator('[data-m-run]').click();page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
        open_section(page,'lifetime');page.wait_for_function("!document.querySelector('[data-lt-run]').disabled",timeout=120000)
        root.locator('.lt-editor>summary').click();root.locator('[data-lt=quality_on]').uncheck();root.locator('[data-lt=quantity_on]').uncheck();root.locator('[data-lt=subsidence_on]').check()
        root.locator('[data-lt=subsidence_window]').select_option('4');root.locator('[data-lt=subsidence_limit]').fill('70')
        subsidence=run();assert subsidence['rate_audit']['subsidence']['selected_years']==[1401,1402,1403,1404]
        assert subsidence['area_target_years'] is not None
        assert abs(subsidence['area_target_years']-2)<1e-7
        # Climate period controls are independent of the longer calibration record.
        root.locator('.lt-editor>summary').click();root.locator('[data-lt=subsidence_on]').uncheck();root.locator('[data-lt=quantity_on]').check();root.locator('[data-lt=climate_on]').check()
        end=first['reference_water_year'];climate_csv='water_year,precip_mm,temp_c\n'+''.join(f'{y},{350+(y%7)*11},{14+(y%5)*.3}\n' for y in range(end-34,end+1))
        root.locator('[data-lt-climate-file]').set_input_files({'name':'QA-period-climate.csv','mimeType':'text/csv','buffer':climate_csv.encode()})
        page.wait_for_function("document.querySelector('[data-lt-climate-name]').textContent==='QA-period-climate.csv'")
        root.locator('[data-lt=climate_window]').select_option('4')
        assert root.locator('[data-lt=climate_precip_pct]').is_disabled()
        climate=run();assert climate['rate_audit']['climate']['start_water_year']==end-3
        assert climate['rate_audit']['climate']['effect_applied']==climate['climate']['accepted']
        for width in [390,768,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            b=svg.bounding_box();vb=svg.evaluate('(n)=>n.viewBox.baseVal.width')
            page.wait_for_function('Math.abs(document.querySelector(".lt-map svg").viewBox.baseVal.width-document.querySelector(".lt-map svg").getBoundingClientRect().width)<4')
        # A cumulative observation never unlocks artificial annual windows.
        cumulative='longitude,latitude,cumulative_mm\n'+''.join(f'{lon},{lat},140\n' for lon,lat,*_ in points)
        open_section(page,'management');page.locator('[data-m-tab=subsidence]').click();page.locator('[data-m-open-source]').click()
        page.locator('[data-m-source]').set_input_files({'name':'QA-cumulative.csv','mimeType':'text/csv','buffer':cumulative.encode()})
        page.locator('[data-m-sub=start_water_year]').fill(str(end-3));page.locator('[data-m-sub=end_water_year]').fill(str(end));page.locator('[data-m-sub=duration_years]').fill('4')
        page.locator('[data-m-run]').click();page.wait_for_function("!document.querySelector('[data-m-run]').disabled",timeout=180000)
        open_section(page,'lifetime')
        page.wait_for_function("JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer?.input_file==='QA-cumulative.csv'",timeout=60000)
        option=root.locator('[data-lt=subsidence_window] option[value="4"]')
        assert option.evaluate('(n)=>n.disabled'),page.evaluate("({option:document.querySelector(`[data-lt=subsidence_window] option[value='4']`).outerHTML,source:document.querySelector('[data-m-source-name]').textContent,kind:document.querySelector('[data-m-sub=value_kind]').value,report:JSON.parse(document.querySelector('#parameterMaps metadata').textContent).subsidence_layer})")
        # 3D columns also suppress hover; wells and help triggers keep their behaviour.
        open_section(page,'scenes');page.locator('#sceneWaterTab').click();canvas=page.locator('#pixelCanvas');canvas.scroll_into_view_if_needed();box=canvas.bounding_box()
        found=False
        for dy in [-60,-30,0,30,60]:
            for dx in range(-260,261,26):
                x=box['x']+box['width']/2+dx;y=box['y']+box['height']/2+dy
                page.mouse.move(x,y);assert not page.locator('#hydroTooltip').is_visible()
                page.mouse.click(x,y)
                if page.locator('#hydroTooltip').is_visible():found=True;break
            if found:break
        assert found,'No 3D column could be clicked'
        assert 'پیکسل' in page.locator('#hydroTooltip').text_content()
        assert not page.locator('.a3-detail-dialog').is_visible()
        page.keyboard.press('Escape');page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+40,y+20,steps=30);page.mouse.up()
        assert not page.locator('#hydroTooltip').is_visible()
        assert not errors,errors
        (out/'trend-options-summary.json').write_text(json.dumps({'methods':{k:v['spatial_coverage'] for k,v in results.items()},'quality':quality['rate_audit']['quality'],'subsidence':subsidence['rate_audit']['subsidence'],'climate':climate['rate_audit']['climate'],'page_errors':errors},ensure_ascii=False,indent=2),'utf-8')
        browser.close()
    print(json.dumps({'passed':True,'methods':list(results),'quality_eligible_sites':quality['rate_audit']['quality']['eligible_sites'],'subsidence_years':subsidence['rate_audit']['subsidence']['selected_years'],'page_errors':errors}))


if __name__=='__main__':main()

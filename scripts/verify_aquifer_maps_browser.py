"""Exercise the actual Pyodide/UI pipeline with alternate local data; server stays static.

Run against an owned development server: python scripts/verify_aquifer_maps_browser.py --url http://127.0.0.1:8767
"""
import argparse
import csv
import io
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8767')
    args=parser.parse_args()
    output=Path('tmp/aquifer-maps-qa');output.mkdir(parents=True,exist_ok=True)
    polygon=[[[0,0],[.02,0],[.02,.02],[0,.02],[0,0]],[[.008,.008],[.012,.008],[.012,.012],[.008,.012],[.008,.008]]]
    aquifer={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'AQUIFER':'نمونه پویا','MAHDOUDE':'نمونه'},'geometry':{'type':'Polygon','coordinates':polygon}}]}
    wells=[('الف',.002,.002),('ب',.018,.002),('پ',.018,.018),('ت',.002,.018)]
    locations='MAHDOUDE,AQUIFER,LOCATION,X,Y,LEVEL_MSL\n'+''.join(f'نمونه,نمونه پویا,{name},{x},{y},100\n' for name,x,y in wells)
    readings='MAHDOUDE,AQUIFER,LOCATION,WATER_TABLE,YEAR_PERSIAN,MONTH_PERSIAN\n'+''.join(f'نمونه,نمونه پویا,{name},{d},{year},6\n' for name,_,_ in wells for year,d in [(1381,10),(1407,20)])
    inputs={'/data/AQUIFER.geojson':json.dumps(aquifer),'/data/LOCATION.csv':locations,'/data/DATA.csv':readings}
    corners=[(-.001,-.001),(.021,-.001),(.021,.021),(-.001,.021)]
    floor=lambda value:'lon,lat,bedrock_msl\n'+''.join(f'{x},{y},{value}\n' for x,y in corners+[(.01,-.001),(.021,.01),(.01,.021),(-.001,.01)])
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.route('**/data/*',lambda route:route.fulfill(status=200,body=inputs[route.request.url.split(args.url)[-1]]) if route.request.url.split(args.url)[-1] in inputs else route.continue_())
        page.goto(args.url+'/aquifer-3d',wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#status3d').textContent.includes('آماده است')",timeout=180000)
        assert '۱۴۰۷' in page.locator('#comparisonEnd').inner_text()
        page.locator('#bedrockFile').set_input_files({'name':'floor-40.csv','mimeType':'text/csv','buffer':floor(40).encode()})
        page.locator('#syInput').fill('.1')
        def build():
            page.locator('#build3d').click()
            page.wait_for_function("document.querySelector('#status3d').textContent.includes('آماده است') || document.querySelector('#status3d').dataset.state==='error'",timeout=120000)
            assert page.locator('#status3d').get_attribute('data-state')!='error',repr(page.locator('#status3d').inner_text())
            assert not errors,errors
        build()
        page.locator('#waterMapTab').click()
        water=page.locator('#waterPercentMap')
        assert water.locator('svg [data-cell]').count()>100
        metadata=json.loads(water.locator('metadata').text_content())
        assert metadata['dates']['after']=='1407-06'
        assert metadata['input_files']['bedrock']=='floor-40.csv'
        # Values are exported from the worker, not derived from the colour ramp.
        with page.expect_download() as download:
            water.locator('[data-export=csv]').click()
        csv_path=output/'baseline.csv';download.value.save_as(csv_path)
        rows=list(csv.DictReader(io.StringIO(csv_path.read_text(encoding='utf-8-sig'))))
        assert rows and all(abs(float(r['lost_pct'])-20)<1e-8 for r in rows)
        assert all(abs(float(r['remaining_pct'])-80)<1e-8 for r in rows)
        water.locator('select').select_option('remaining_pct')
        water.locator('[data-map-labels]').check()
        with page.expect_download() as download:
            water.locator('[data-export=png]').click()
        png_path=output/'remaining.png';download.value.save_as(png_path)
        assert Image.open(png_path).size==(1520,1320)
        page.locator('#waterMapPanel').screenshot(path=str(output/'water-map-desktop.png'))
        # Pan with an ordinary mouse drag, a right drag and an actual pen pointer.
        page.locator('[data-interaction=pan]').click()
        canvas=page.locator('#beforeCanvas');canvas.scroll_into_view_if_needed();box=canvas.bounding_box()
        x,y=box['x']+box['width']/2,box['y']+box['height']/2
        page.mouse.move(x,y);page.mouse.wheel(0,-350)
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+80,y+30,steps=8);page.mouse.up()
        page.mouse.move(x,y);page.mouse.down(button='right');page.mouse.move(x-20,y,steps=4);page.mouse.up(button='right')
        client=context.new_cdp_session(page)
        for event,px,py,buttons in [('mousePressed',x,y,1),('mouseMoved',x+30,y-20,1),('mouseReleased',x+30,y-20,0)]:
            client.send('Input.dispatchMouseEvent',{'type':event,'x':px,'y':py,'button':'left' if event!='mouseMoved' else 'none','buttons':buttons,'pointerType':'pen','clickCount':1})
        page.locator('#a3Tab-views').click();page.locator('#a3ViewName').fill('mouse and pen pan');page.locator('#a3SaveView').click()
        camera=page.evaluate("JSON.parse(localStorage.getItem('aquifer3d:views:v1:0'))[0].view.camera")
        assert camera['panX']>0 and camera['zoom']>1
        assert abs(camera['yaw']-.6)<1e-9 and abs(camera['pitch']-.65)<1e-9,camera
        # Replacing the files must change outputs and labels immediately after recompute.
        page.locator('#bedrockFile').set_input_files({'name':'new-floor-30.csv','mimeType':'text/csv','buffer':floor(30).encode()})
        page.locator('#syMode').select_option('spatial')
        sy='longitude,latitude,Sy\n'+''.join(f'{x},{y},{v}\n' for (x,y),v in zip(corners,[.05,.1,.15,.2]))
        page.locator('#syFile').set_input_files({'name':'variable-Sy.csv','mimeType':'text/csv','buffer':sy.encode()})
        build()
        water=page.locator('#waterPercentMap')
        with page.expect_download() as download:water.locator('[data-export=geojson]').click()
        geo_path=output/'new-inputs.geojson';download.value.save_as(geo_path)
        geo=json.loads(geo_path.read_text(encoding='utf-8'))
        assert all(abs(f['properties']['lost_pct']-100/6)<1e-8 for f in geo['features'])
        assert geo['metadata']['inputs']['sy']=='variable-Sy.csv'
        parameter=page.locator('#parameterMaps');parameter.locator('select').select_option('sy')
        assert parameter.locator('svg path:not([data-cell])').count()>10
        assert 'variable-Sy.csv' in parameter.locator('.a3-map-note').inner_text()
        parameter.screenshot(path=str(output/'sy-map-desktop.png'))
        # Mobile layout, keyboard tabs, map panning and responsive overflow.
        page.set_viewport_size({'width':390,'height':844});page.locator('#waterMapTab').click()
        water.locator('svg').focus();page.keyboard.press('+');page.keyboard.press('ArrowLeft')
        page.locator('#waterMapPanel').screenshot(path=str(output/'water-map-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        # An exactly zero baseline must still render a usable grey map and exports.
        page.set_viewport_size({'width':1440,'height':1000})
        page.locator('#bedrockFile').set_input_files({'name':'zero-baseline-90.csv','mimeType':'text/csv','buffer':floor(90).encode()})
        build()
        with page.expect_download() as download:water.locator('[data-export=csv]').click()
        zero_path=output/'zero-baseline.csv';download.value.save_as(zero_path)
        zero_rows=list(csv.DictReader(io.StringIO(zero_path.read_text(encoding='utf-8-sig'))))
        assert zero_rows and all(r['remaining_pct']=='' and r['lost_pct']=='' for r in zero_rows)
        assert water.locator('svg [data-cell][fill="#d8dee2"]').count()==len(zero_rows)
        assert not errors,errors
        print(json.dumps({'status':'passed','exported_cells':len(rows),'camera':camera,'errors':errors,'qa':str(output)}))
        browser.close()


if __name__=='__main__':main()

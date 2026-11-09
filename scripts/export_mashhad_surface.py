"""Browser-only modelling and validation; host performs file I/O and static serving."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
from threading import Thread
from playwright.sync_api import sync_playwright
from export_mashhad_bedrock import StaticHandler

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.tmp/mashhad-bedrock'


def render_report(page,base):
    page.set_viewport_size({'width':1500,'height':1300})
    page.goto(base+'/.tmp/mashhad-bedrock/surface-report.html')
    page.wait_for_function('window.REPORT_READY',timeout=60000)
    html=page.evaluate('''async()=>{
      const [html,lib,code,data]=await Promise.all(['surface-report.html','plotly.min.js','surface-report.js','surface-preview.json'].map(async p=>(await fetch(p)).text()));
      const safe=s=>s.replace(/<\\/script/gi,'<\\\\/script');
      return html.replace('<script id="plotly-library" src="plotly.min.js"></script>',()=>'<script>'+safe(lib)+'</script>')
        .replace('<script id="report-code" src="surface-report.js"></script>',()=>'<script>window.MASHHAD_SURFACE='+safe(data)+';</script><script>'+safe(code)+'</script>');
    }''')
    target=ROOT/'.tmp/mashhad-bedrock-msl.html'
    target.write_text(html,encoding='utf-8')
    page.goto(target.as_uri())
    page.wait_for_function('window.REPORT_READY',timeout=60000)
    page.screenshot(path=str(ROOT/'.tmp/mashhad-bedrock-msl.png'),full_page=True)
    assert page.evaluate("document.getElementById('msl').data[0].type==='surface'")
    page.set_viewport_size({'width':430,'height':950})
    page.wait_for_timeout(500)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    print('Offline report rendered; desktop and mobile layout checked',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assess-only',action='store_true')
    parser.add_argument('--reassess',action='store_true')
    parser.add_argument('--render-only',action='store_true')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(StaticHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            page.on('console',lambda msg: print(msg.text,flush=True) if msg.type=='log' else None)
            page.set_default_timeout(900000)
            base=f'http://127.0.0.1:{server.server_port}'
            if args.render_only:
                render_report(page,base)
                browser.close()
                return
            page.goto(base+'/.tmp/mashhad-bedrock/surface-runner.html')
            saved=WORK/'surface-assessment.json'
            if saved.exists() and not args.reassess:
                assessment=json.loads(saved.read_text(encoding='utf-8'))
                prepared=page.evaluate("assessment=>runStep({command:'restore',assessment})",assessment)
            else:
                prepared=page.evaluate("()=>runStep({command:'assess'})")
                assessment=prepared['assessment']
                saved.write_text(json.dumps(assessment,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'selected':assessment['selected_method'],'controls':assessment['controls'],'scores':assessment['scores']}),flush=True)
            if args.assess_only:
                browser.close()
                return
            fit=page.evaluate("()=>runStep({command:'fit'})")
            (WORK/'surface-fit.json').write_text(json.dumps(fit,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in fit.items() if k!='assessment'}),flush=True)
            manifest=json.loads((ROOT/'.tmp/mashhad-gee-dem/manifest.json').read_text(encoding='utf-8'))
            # Compare the actual pixel grid, not old sample counts.
            for key in ['crs','transform','width','height','tiles']:
                assert manifest['plan'][key]==prepared['plan'][key],key
            result=page.evaluate("args=>runStep({command:'finish',...args})",dict(plan=prepared['plan'],retrieved=manifest['retrieved_utc']))
            accepted=page.evaluate("csv=>runStep({command:'validate-upload',csv})",result['csv'])
            # Preserve the previous nearest-contour results before replacement.
            archive=WORK/'previous-nearest'
            archive.mkdir(exist_ok=True)
            files={'MASHHAD_BEDROCK_MSL.csv':result['csv'],'MASHHAD_BEDROCK_MSL.audit.csv':result['audit'],
                'MASHHAD_BEDROCK_MSL.csv.metadata.json':json.dumps(result['metadata'],ensure_ascii=False,indent=2)+'\n',
                'MASHHAD_BEDROCK_BOUNDARY.geojson':json.dumps(result['boundary'],ensure_ascii=False,indent=2)+'\n'}
            for name,content in files.items():
                target=ROOT/'Data'/name
                if target.exists() and not (archive/name).exists(): shutil.copyfile(target,archive/name)
                target.write_text(content,encoding='utf-8',newline='')
            (ROOT/'Data/MASHHAD_BEDROCK_MODEL_VALIDATION.json').write_text(json.dumps(assessment,indent=2),encoding='utf-8')
            (WORK/'surface-preview.json').write_text(json.dumps(result['preview'],ensure_ascii=False),encoding='utf-8')
            print(json.dumps({'output':'Data/MASHHAD_BEDROCK_MSL.csv','validation':accepted,'bedrock_range':result['metadata']['bedrock_msl_range_m']}),flush=True)
            render_report(page,base)
            browser.close()
    finally:
        server.shutdown()


if __name__=='__main__': main()

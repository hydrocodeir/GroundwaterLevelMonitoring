"""Static file I/O + browser automation. All scientific processing is in Pyodide."""
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
import json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':1500,'height':1220},device_scale_factor=1)
        errors = []
        def on_error(error):
            errors.append(str(error))
            print('Browser error: '+str(error),flush=True)
        page.on('pageerror', on_error)
        page.goto(f'http://127.0.0.1:{server.server_port}/.tmp/mashhad-bedrock/index.html')
        page.wait_for_function("window.BEDROCK_READY || document.querySelector('#status').dataset.state === 'error'",timeout=240000)
        if not page.evaluate('!!window.BEDROCK_READY'):
            raise RuntimeError(page.locator('#status').inner_text())
        metadata = page.evaluate('bedrockModel.meta')
        (OUT/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        # Export generated in the client; host only persists the returned file text.
        html = page.evaluate('''async () => {
          const [template,lib,view] = await Promise.all(['index.html','plotly.min.js','view.js'].map(async path=>(await fetch(path)).text()));
          const safe=s=>s.replace(/<\\/script/gi,'<\\\\/script');
          return template.replace('<script id="plotly-library" src="plotly.min.js"></script>', () => '<script>'+safe(lib)+'</script>')
            .replace('<script id="view-code" src="view.js"></script>', () => '<script>window.PRECOMPUTED_BEDROCK='+safe(JSON.stringify(bedrockModel))+';</script><script>'+safe(view)+'</script>');
        }''')
        target = ROOT/'.tmp/mashhad-bedrock-3d.html'
        target.write_text(html,encoding='utf-8')
        # Validate actual offline deliverable and controls.
        page.goto(target.as_uri())
        page.wait_for_function('window.BEDROCK_READY',timeout=60000)
        page.locator('#mode').select_option('lines')
        assert page.evaluate("document.getElementById('plot').data[0].visible") is False
        page.locator('#mode').select_option('both')
        page.locator('#depth').check()
        assert page.evaluate("document.getElementById('plot').layout.scene.zaxis.autorange") == 'reversed'
        page.locator('#depth').uncheck()
        page.locator('#exag').fill('6')
        page.locator('#exag').dispatch_event('input')
        assert abs(page.evaluate("document.getElementById('plot').layout.scene.aspectratio.z")-.45)<1e-6
        page.locator('#exag').fill('4')
        page.locator('#exag').dispatch_event('input')
        page.wait_for_timeout(1000)
        page.screenshot(path=str(ROOT/'.tmp/mashhad-bedrock-3d.png'),full_page=True)
        with page.expect_download() as download_info:
            page.locator('#png').click()
        download_info.value.save_as(str(ROOT/'.tmp/mashhad-bedrock-3d-plot.png'))
        page.set_viewport_size({'width':430,'height':930})
        page.wait_for_timeout(700)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
        assert not errors,errors
        print(json.dumps({'metadata':metadata,'html':str(target),'browser_errors':errors,'checks':'offline HTML; trace switch; depth direction; vertical scale; PNG export; mobile overflow'},ensure_ascii=True))
        browser.close()
    server.shutdown()


if __name__ == '__main__':
    main()

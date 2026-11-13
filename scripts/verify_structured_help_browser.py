"""Help formatting, safe text, keyboard dismissal and mobile boundaries."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    out=Path('.tmp/lifetime-qa');out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':390,'height':844})
        page.set_content('<html dir="rtl"><body><button id="target" style="margin:90px">جزئیات</button><section class="a3-quality"><h2>تنظیم کیفیت</h2><p data-help-copy>حد EC: ۱۵۰۰ µS/cm؛ سناریوی قابل ویرایش است. سلامت آب بررسی نمی‌شود.</p></section></body></html>')
        page.add_style_tag(path='frontend/assets/css/workbench.css')
        page.add_script_tag(path='frontend/assets/js/dashboard-help.js')
        page.evaluate("HydroHelp.showFor(document.querySelector('#target'),{title:'جزئیات پیکسل',sections:[{title:'داده',rows:[['EC','۱۵۰۰ µS/cm'],['نام فایل','<img src=x onerror=alert(1)>']]},{title:'علت نامشخص',bullets:['بیرون پوشش معتبر روند']} ]},null,true)")
        tip=page.locator('#hydroTooltip')
        assert tip.is_visible() and tip.locator('dl dt').count()==2
        assert tip.locator('img').count()==0
        box=tip.bounding_box();assert box['x']>=0 and box['x']+box['width']<=391
        page.screenshot(path=str(out/'structured-help-mobile.png'))
        page.keyboard.press('Escape');assert not tip.is_visible()
        trigger=page.locator('.hydro-info-trigger');trigger.focus()
        assert not tip.is_visible()
        trigger.hover();assert not tip.is_visible()
        trigger.click()
        assert tip.is_visible() and tip.locator('dl').count()>0
        trigger.click();assert not tip.is_visible()
        trigger.focus();page.keyboard.press('Enter');assert tip.is_visible()
        page.keyboard.press('Escape');assert not tip.is_visible()
        browser.close()
    print(json.dumps({'passed':True,'mobile':'fits','markup':'escaped','keyboard':'passed'}))


if __name__=='__main__':main()

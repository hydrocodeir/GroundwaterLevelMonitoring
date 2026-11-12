"""Format and package already-computed browser outputs; no model fitting here."""
import base64
import hashlib
import json
from pathlib import Path
import zipfile
from build_hydrogeology_report import load_markdown

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'outputs/water_quality'
    source=output/'METHODS.fa.md'
    body=load_markdown().markdown(source.read_text(encoding='utf-8'),extensions=['markdown.extensions.tables','markdown.extensions.fenced_code'])
    fonts=[]
    for weight in (400,700):
        font=ROOT/f'frontend/assets/fonts/vazirmatn-arabic-{weight}.woff2'
        fonts.append(f"@font-face{{font-family:Vazir;src:url(data:font/woff2;base64,{base64.b64encode(font.read_bytes()).decode()});font-weight:{weight}}}")
    figures=[]
    for filename,caption in [('MASHHAD_QUALITY_ZONES.png','زون‌های محدودیت شوری و نفوذ؛ خاکستری نامشخص است.'),('MASHHAD_EC.png','EC برآوردی از مدل انتخاب‌شده.'),('MASHHAD_IRRIGATION_FRACTION.png','سهم سناریوییِ فاقد محدودیت شدید EC/SAR از ستون اشباع.')]:
        data=base64.b64encode((output/filename).read_bytes()).decode()
        figures.append(f'<figure><img src="data:image/png;base64,{data}" alt="{caption}"><figcaption>{caption}</figcaption></figure>')
    document=f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>برآورد حجم مشروط به شوری مشهد</title><style>{''.join(fonts)}body{{max-width:1100px;margin:25px auto;padding:24px;color:#203e4e;font:15px/1.95 Vazir,Tahoma,sans-serif}}h1,h2{{color:#194f61}}h2{{margin-top:32px;border-bottom:1px solid #b8cfd8;padding-bottom:8px}}table{{width:100%;border-collapse:collapse;font-size:13px;margin:18px 0}}td,th{{padding:9px;border:1px solid #d6e2e8;text-align:right}}th{{background:#edf5f7}}pre{{direction:ltr;text-align:left;padding:14px;background:#f0f5f7;white-space:pre-wrap}}code{{direction:ltr;unicode-bidi:isolate;font-size:12px}}a{{color:#06728b}}img{{width:100%;height:auto}}figure{{margin:30px 0}}figcaption{{color:#607b87;font-size:13px}}@media print{{body{{font-size:11px}}figure{{break-inside:avoid}}img{{max-height:200mm;object-fit:contain}}}}</style>{body}<h2>نقشه‌های همین اجرا</h2>{''.join(figures)}</html>'''
    (output/'REPORT.fa.html').write_text(document,encoding='utf-8')
    patterns=['Data/WaterQ.csv','Data/AQUIFER.geojson','Data/DATA.csv','Data/LOCATION.csv','Data/MASHHAD_BEDROCK_MSL.csv','Data/MASHHAD_SY/MASHHAD_SY_PRIOR.csv','Data/WaterQ_Sources/*','scripts/waterq_compute.py','scripts/run_waterq_browser.py','scripts/fetch_waterq_sources.py','scripts/render_quality_preview.py','scripts/package_quality_report.py','frontend/assets/js/aquifer3d-quality.js','frontend/assets/js/aquifer3d-worker.js','frontend/assets/js/aquifer3d-maps.js','frontend/assets/js/aquifer3d_compute.py']
    def record(path):
        return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    files=sorted({p for pattern in patterns for p in ROOT.glob(pattern) if p.is_file()})
    deliverables=[p for p in output.iterdir() if p.is_file() and p.suffix in ('.md','.html','.tif','.png','.csv','.geojson','.json') and p.name not in ('MANIFEST.json','WATERQ_NORMALIZED.json')]
    manifest={'snapshot_date':'2026-11-12','snapshot_date_persian':'1405-08-21','scientific_execution':'Browser Pyodide; package step only formats text and copies bytes','inputs_and_code':[record(p) for p in files],'outputs':[record(p) for p in sorted(deliverables)]}
    (output/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(output/'MASHHAD_WATERQ_ESTIMATE.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(deliverables+[output/'MANIFEST.json']):archive.write(path,path.name)
    print(json.dumps({'packaged_files':len(deliverables)+1,'input_hashes':len(files),'zip_bytes':(output/'MASHHAD_WATERQ_ESTIMATE.zip').stat().st_size}))


if __name__=='__main__':main()

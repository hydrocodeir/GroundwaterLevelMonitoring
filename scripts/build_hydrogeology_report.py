"""Build the Persian documentation PDF locally; no scientific inputs are recomputed.

Dependencies: Markdown, Playwright + Chromium; optional PyMuPDF/Pillow for --qa.
Run: python scripts/build_hydrogeology_report.py --qa
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import importlib.util
import json
import mimetypes
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs/reports"
SOURCE = REPORT_DIR / "HYDROGEOLOGY_METHODS_ASSUMPTIONS.fa.md"
HTML = SOURCE.with_suffix(".html")
PDF = ROOT / "output/pdf/HYDROGEOLOGY_METHODS_ASSUMPTIONS_FA.pdf"
MANIFEST = REPORT_DIR / "HYDROGEOLOGY_REPORT_MANIFEST.json"


def load_markdown():
    try:
        import markdown
        return markdown
    except ImportError:
        # Markdown is pure Python. Reuse the existing task environment without
        # adding its scientific packages to this interpreter's import path.
        package = ROOT / ".cache/task-venv/Lib/site-packages/markdown"
        if not package.exists():
            raise RuntimeError("Install Markdown: python -m pip install markdown")
        spec = importlib.util.spec_from_file_location(
            "markdown", package / "__init__.py",
            submodule_search_locations=[str(package)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["markdown"] = module
        spec.loader.exec_module(module)
        return module


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def build_html() -> None:
    markdown = load_markdown()
    source = SOURCE.read_text(encoding="utf-8")
    intro, chapters = source.split("\n## ", 1)
    md = markdown.Markdown(extensions=["markdown.extensions.tables", "markdown.extensions.fenced_code", "markdown.extensions.toc"],
                           extension_configs={"markdown.extensions.toc": {"toc_depth": "2-2"}})
    body = md.convert("## " + chapters)
    intro = markdown.markdown(intro)
    for match in list(re.finditer(r'<img\s+[^>]*src="([^"]+)"[^>]*>', body)):
        original = html.unescape(match.group(1))
        path = (REPORT_DIR / original).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError(f"Image is outside workspace: {original}")
        body = body.replace(f'src="{match.group(1)}"', f'src="{data_uri(path)}"')
    body = re.sub(r"<p>(<img[^>]+>)</p>\s*(<p><em>.*?</em></p>)?",
                  r'<figure>\1<figcaption>\2</figcaption></figure>', body, flags=re.S)
    # Latin bibliography text is easier to read with its natural base direction.
    body = re.sub(r'<p>(<strong>\[[^\]]+\] (?:Noor|Lv|USGS|NASA|Izady|SciPy|FAO|GFSAD|UNECE)[\s\S]*?</p>)',
                  r'<p class="reference" dir="auto">\1', body)
    body = re.sub(r"<table>(?:(?!</table>).)*A01(?:(?!</table>).)*</table>",
                  lambda m: m.group().replace("<table>", '<table class="assumptions">', 1),
                  body, flags=re.S)
    fonts = []
    for weight in (400, 500, 700):
        for subset, unicode_range in (("arabic", "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200F,U+FB50-FDFF,U+FE70-FEFF"),
                                       ("latin", "U+0000-00FF,U+0100-024F,U+1E00-1EFF,U+2000-200B,U+2010-206F,U+20A0-20CF,U+2100-214F")):
            uri = data_uri(ROOT / f"frontend/assets/fonts/vazirmatn-{subset}-{weight}.woff2")
            fonts.append(f"@font-face{{font-family:Report;src:url('{uri}') format('woff2');font-weight:{weight};unicode-range:{unicode_range};font-display:block;}}")
    css = """@page { size:A4; margin:18mm 17mm 18mm; }
* { box-sizing:border-box; }
html { direction:rtl; }
body { font-family:Report,Tahoma,sans-serif; color:#203441; font-size:13.2px;
       line-height:1.85; margin:0; -webkit-print-color-adjust:exact; print-color-adjust:exact; }
p { margin:0 0 10px; text-align:justify; orphans:3; widows:3; }
h1,h2,h3 { color:#163d50; line-height:1.65; break-after:avoid; }
h1 { font-size:30px; margin:0 0 24px; }
h2 { font-size:22px; padding:0 0 12px; margin:25px 0 22px; border-bottom:2px solid #4c9b9a; }
main > h2:first-child { margin-top:0; }
h3 { font-size:15.5px; margin:21px 0 9px; }
strong { font-weight:700; }
a { color:#076a86; text-decoration:none; overflow-wrap:anywhere; }
table { width:100%; border-collapse:collapse; margin:14px 0 17px;
        font-size:11.5px; line-height:1.8; table-layout:auto; break-inside:avoid; }
thead { display:table-header-group; }
th { background:#e8f1f4; color:#153e50; font-weight:700; }
td,th { border:1px solid #ccdbe1; padding:6px 7px; text-align:right;
        vertical-align:top; overflow-wrap:anywhere; }
tr { break-inside:avoid; }
tbody tr:nth-child(even) { background:#f7f9fa; }
pre { direction:ltr; text-align:left; white-space:pre-wrap; overflow-wrap:anywhere;
      background:#f0f5f7; border-left:3px solid #4c9b9a; padding:12px 14px;
      margin:15px 0; font:11.5px/1.8 Consolas,monospace; break-inside:avoid; }
code { direction:ltr; unicode-bidi:isolate; font:11.8px/1.8 Consolas,monospace;
       overflow-wrap:anywhere; color:#244a60; }
figure { margin:22px 0; break-inside:avoid; }
figure img { display:block; max-width:100%; max-height:190mm; object-fit:contain; margin:0 auto; }
figcaption p { font-size:11.8px; color:#55717b; line-height:1.8; margin:10px 0 0; }
ul,ol { padding-right:23px; margin:10px 0 15px; }
li { padding-bottom:5px; }
.cover { min-height:240mm; padding-top:31mm; position:relative; break-after:page; }
.cover:before { content:''; display:block; width:70px; height:6px; background:#348c92; margin-bottom:28px; }
.cover h1 { max-width:540px; }
.cover p { text-align:right; font-size:16px; line-height:2.1; }
.cover p:last-child { font-size:13px; margin-top:40px; padding-top:18px; border-top:1px solid #ccdbe1; }
.cover-label { color:#53727d; font-size:13px; margin-bottom:15px; }
.contents { break-after:page; }
.contents h2 { break-before:auto; }
.toc ul { list-style:none; padding:0; margin:0; }
.toc li { border-bottom:1px solid #e3eaee; padding:7px 0; }
.toc a { display:block; color:#244c60; }
.contents-note { font-size:12px; color:#657f89; margin-top:22px; }
.reference { unicode-bidi:plaintext; }
.assumptions { font-size:10.8px; line-height:1.7; }
.assumptions td,.assumptions th { padding:4px 6px; }
@media screen {
  body { background:#edf1f3; max-width:210mm; margin:25px auto; }
  main,.cover,.contents { background:white; padding:18mm 17mm; }
  .cover { padding-top:40mm; }
  .contents { margin-top:15px; }
}
"""
    document = f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>گزارش منابع، روش‌ها و فرضیات مدل آب زیرزمینی</title>
<meta name="description" content="مستند فنی Sy، سنگ‌کف، تغییر ذخیره و نمایش سه‌بعدی؛ نسخه ۱.۰">
<style>{''.join(fonts)}{css}</style></head><body>
<section class="cover"><div class="cover-label">مستند فنی و دفتر فرضیات</div>{intro}</section>
<nav class="contents" aria-label="فهرست مطالب"><h2>فهرست مطالب</h2>{md.toc}
<p class="contents-note">عنوان‌های فهرست و پیوند منابع قابل کلیک‌اند. اعداد، پارامترهای مدل و فرض‌های نمایشی در فصل‌های مربوط توضیح داده شده‌اند.</p></nav>
<main>{body}</main></body></html>"""
    HTML.write_text(document, encoding="utf-8")


def render_pdf() -> dict:
    from playwright.sync_api import sync_playwright
    PDF.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # The report is self-contained. Do not make network requests during export.
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(HTML.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            missing = page.locator("img").evaluate_all(
                "xs=>xs.filter(x=>!x.complete||x.naturalWidth===0).map(x=>x.alt)")
            if missing:
                raise RuntimeError(f"Missing report images: {missing}")
            counts = {"chapters": page.locator("main h2").count(),
                      "tables": page.locator("main table").count(),
                      "figures": page.locator("main figure").count()}
            page.pdf(path=str(PDF), format="A4", prefer_css_page_size=True,
                     print_background=True, display_header_footer=True,
                     header_template='<div style="width:100%;margin:0 17mm;font:9px Tahoma;color:#77909b;text-align:right">گزارش روش‌ها و فرضیات | Sy و سنگ‌کف</div>',
                     footer_template='<div style="width:100%;margin:0 17mm;display:flex;justify-content:space-between;font:9px Tahoma;color:#77909b"><span>نسخه ۱.۰ | ۲۱ آبان ۱۴۰۵</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
                     outline=True, tagged=True)
            return counts
        finally:
            browser.close()


def write_manifest(counts: dict) -> None:
    patterns = [
        "Data/AQUIFER.geojson", "Data/MAHDOUDE.geojson", "Data/LOCATION.csv", "Data/DATA.csv",
        "Data/MASHHAD_BEDROCK*", "Data/NEYSHABUR_BEDROCK*", "Data/MASHHAD_SY/*",
        ".tmp/BedRock.geojson", "Data/Monthly_*.csv*", "Data/Warm_Season_Irrigated_Area.csv*",
        "scripts/*mashhad*bedrock*.py", "scripts/*neyshabur*bedrock*.py",
        "scripts/build_mashhad_sy.py", "scripts/mashhad_sy_compute.py",
        "scripts/export_monthly_ndvi.py", "scripts/export_monthly_aet.py",
        "scripts/export_warm_season_irrigated_area.py",
        "app/data_service.py", "frontend/assets/js/aquifer3d*.js",
        "frontend/assets/js/aquifer3d_compute.py", "frontend/assets/js/dashboard-worker.js",
        "frontend/assets/fonts/vazirmatn-*.woff2", "docs/reports/assets/*",
        "scripts/build_hydrogeology_report.py",
    ]
    files = sorted({f for pattern in patterns for f in ROOT.glob(pattern) if f.is_file()})
    def record(path):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
                "sha256": digest}
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    manifest = {
        "report_version": "1.0", "snapshot_date": "2026-11-12",
        "snapshot_date_persian": "1405-08-21", "language": "fa-IR",
        "purpose": "Documentation snapshot; hashes identify local inputs and code, not field validation.",
        "hydrological_calendar": "Persian water year: Mehr through Shahrivar; named by starting year",
        "git_head": git("rev-parse", "HEAD"),
        "git_worktree_has_changes": bool(git("status", "--porcelain")),
        "render": {**counts, "engine": "Playwright Chromium", "network_requests": "blocked",
                   "html_has_embedded_fonts_and_figures": True},
        "referenced_files": [record(f) for f in files],
        "deliverables": [record(f) for f in (SOURCE, HTML, PDF)],
        "note": "No credentials, environment files or user-uploaded external data are included."
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_qa() -> None:
    import fitz
    from PIL import Image, ImageDraw
    target = ROOT / "tmp/pdfs/hydrogeology-qa"
    target.mkdir(parents=True, exist_ok=True)
    # Remove only this builder's generated page images, never a directory tree.
    for pattern in ("page-*.png", "contact-*.png"):
        for old in target.glob(pattern):
            old.unlink()
    doc = fitz.open(PDF)
    pages = []
    for number, page in enumerate(doc, 1):
        if len(page.get_text().strip()) < 35:
            raise RuntimeError(f"Unexpected empty page: {number}")
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        image.save(target / f"page-{number:02d}.png")
        thumbnail = image.copy()
        thumbnail.thumbnail((397, 562))
        pages.append(thumbnail)
    for start in range(0, len(pages), 6):
        sheet = Image.new("RGB", (3 * 417, 2 * 596), "#dce4e8")
        draw = ImageDraw.Draw(sheet)
        for offset, image in enumerate(pages[start:start + 6]):
            x, y = (offset % 3) * 417 + 10, (offset // 3) * 596 + 23
            sheet.paste(image, (x, y))
            draw.text((x, y - 18), f"Page {start + offset + 1}", fill="black")
        sheet.save(target / f"contact-{start // 6 + 1:02d}.png")
    print(json.dumps({"pages": len(doc), "qa_directory": str(target)}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa", action="store_true", help="Render every page plus contact sheets")
    args = parser.parse_args()
    build_html()
    counts = render_pdf()
    write_manifest(counts)
    if args.qa:
        render_qa()
    print(json.dumps({"pdf": str(PDF), "html": str(HTML), "manifest": str(MANIFEST),
                      **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()

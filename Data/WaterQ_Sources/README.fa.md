# منابع کمکی برآورد شوری مشهد

این بسته منابع عمومی توضیحی مدل را نگه می‌دارد؛ هیچ فایل آن، لاگ عمقی EC آب زیرزمینی نیست.

- `MASHHAD_GEE_COVARIATES.npy`: ارتفاع و شیب SRTM، شاخص‌های NDVI، NDWI، BSI و نسبت SWIR از Sentinel-2 و نمونه‌های پوشش کشت/ساخت‌وساز/زمین کم‌پوشش WorldCover. شبکهٔ خروجی حدود یک کیلومتر و پنجرهٔ مرجع WY ۱۴۰۱ تا ۱۴۰۳ است. بازتاب در ۲۵۰ متر نمونه‌برداری می‌شود؛ این خروجی کیفیت آب با تفکیک ۱۰ متر نیست. WorldCover مربوط به ۲۰۲۱ است.
- `MASHHAD_GLIM.geojson`: ۹۵ عارضهٔ سنگ‌شناسی منطقه‌ای برخوردکننده با قاب مرجع، از سرویس GLiM با انتساب Hartmann & Moosdorf (2012). بعضی عارضه‌ها از قاب فراتر می‌روند و در مرورگر بریده می‌شوند. این لایه جانشین نقشهٔ محلی ۱:۱۰۰هزار یا سنگ‌شناسی عمقی نیست.
- `GLIM_LAYER_METADATA.json`: مشخصات سرویس بردار، فیلدها و انتساب.
- `MASHHAD_WATERQ_SOURCE_METADATA.json`: شناسهٔ محصولات، تاریخ، روش نمونه‌برداری، قاب، تفکیک و هش SHA-256.

داده‌های `WaterQ.csv` به GEE ارسال نشده‌اند. آماده‌سازی ماهواره‌ای فقط از محدودهٔ عمومی آبخوان و تصاویر عمومی استفاده می‌کند. برازش، کنترل هندسه، اعتبارسنجی و حجم در Pyodide اجرا می‌شوند. وجود یک منبع در این بسته به معنای بهترشدن نتیجه یا استفاده از آن در مدل برتر نیست.

برای بازدریافت با حساب GEE پیکربندی‌شدهٔ محلی:

```powershell
.venv-win/Scripts/python.exe scripts/fetch_waterq_sources.py --end-water-year 1403
```

برای تغییر دوره، سال آبی و در صورت لزوم `--window` را تغییر دهید. محتوای فایل حساب سرویس در این بسته یا خروجی‌ها قرار نمی‌گیرد.

منابع: [GLiM، DOI:10.1029/2012GC004370](https://doi.org/10.1029/2012GC004370)، [ارائه‌دهندهٔ بردار](https://services8.arcgis.com/4KhTMTZ1x0f76DSg/arcgis/rest/services/GLiM_Niveau_I/FeatureServer/1)، [Sentinel-2](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED)، [WorldCover](https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200)، [SRTM](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003).

"""Calendar planning, quality control and climate CSV creation in browser Pyodide."""
import csv
import hashlib
import io
import json
import math
from datetime import date, timedelta
from statistics import mean
import jdatetime


SOURCES = {
    'precip': {'collection':'UCSB-CHG/CHIRPS/DAILY','band':'precipitation',
               'url':'https://developers.google.com/earth-engine/datasets/catalog/UCSB-CHG_CHIRPS_DAILY',
               'doi':'10.1038/sdata.2015.66','unit':'mm/day','nominal_resolution_degrees':0.05},
    'temp': {'collection':'ECMWF/ERA5_LAND/DAILY_AGGR','band':'temperature_2m',
             'url':'https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_DAILY_AGGR',
             'unit':'K; daily mean','nominal_resolution_degrees':0.1},
}


def plan_climate(geojson, catalog, name='مشهد', start_wy=None, end_wy=None):
    features=[f for f in geojson['features'] if f.get('properties',{}).get('AQUIFER')==name]
    if len(features)!=1:
        raise ValueError('Exactly one matching aquifer polygon is required.')
    feature=features[0]
    first=max(date.fromisoformat(catalog[k]['first']) for k in SOURCES)
    last=min(date.fromisoformat(catalog[k]['last']) for k in SOURCES)
    begin=jdatetime.date.fromgregorian(date=first).year
    while jdatetime.date(begin,7,1).togregorian()<first:begin+=1
    finish=jdatetime.date.fromgregorian(date=last).year
    while jdatetime.date(finish+1,7,1).togregorian()>last+timedelta(days=1):finish-=1
    if start_wy is not None:begin=max(begin,int(start_wy))
    if end_wy is not None:finish=min(finish,int(end_wy))
    if finish<begin:raise ValueError('No complete common Persian water year is available.')
    periods=[]
    for wy in range(begin,finish+1):
        start=jdatetime.date(wy,7,1).togregorian();end=jdatetime.date(wy+1,7,1).togregorian()
        periods.append({'water_year':wy,'start':start.isoformat(),'end_exclusive':end.isoformat(),'expected_days':(end-start).days})
    return {'aquifer':name,'feature':feature,'sources':SOURCES,'source_catalog':catalog,'periods':periods,
            'calendar':'Persian water year, 1 Mehr to end of Shahrivar; named for starting Persian year',
            'boundary_sha256':hashlib.sha256(json.dumps(feature,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}


def csv_text(columns, records):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=columns,lineterminator='\r\n')
    writer.writeheader();writer.writerows(records);return stream.getvalue()


def build_climate(plan, raw, retrieved, app_source):
    """Never fill missing days/years; use exact source area-weighted annual aggregates."""
    by_year={};audit=[];annual=[]
    for item in raw:
        wy=int(item['water_year'])
        if wy in by_year:raise ValueError('Duplicate source water year.')
        by_year[wy]=item
    for period in plan['periods']:
        wy=period['water_year'];item=by_year.get(wy);reasons=[]
        row={**period};values={}
        if item is None:
            reasons.append('missing source result')
        else:
            if any(item.get(k)!=period[k] for k in ('start','end_exclusive','expected_days')):
                raise ValueError('Source dates differ from the browser-generated Persian calendar plan.')
            for key in SOURCES:
                stats=item.get(key+'_stats') or {};count=item.get(key+'_images');unique=item.get(key+'_unique_days')
                valid=stats.get('valid_area_sum');total=stats.get('total_area_sum')
                minimum=stats.get('days_min');maximum=stats.get('days_max');numerator=stats.get('value_area_sum')
                coverage=valid/total if valid is not None and total is not None and total>0 else None
                row.update({key+'_images':count,key+'_unique_days':unique,key+'_min_days':minimum,key+'_max_days':maximum,
                            key+'_valid_area_m2':valid,key+'_total_area_m2':total,key+'_coverage_fraction':coverage})
                if count!=period['expected_days'] or unique!=period['expected_days'] or minimum!=period['expected_days'] or maximum!=period['expected_days']:
                    reasons.append(key+': incomplete or duplicate daily coverage')
                if coverage is None or not math.isfinite(coverage) or coverage<0.999:
                    reasons.append(key+': incomplete spatial coverage')
                if numerator is None or not math.isfinite(numerator) or valid is None or valid<=0:
                    reasons.append(key+': invalid source area-weighted sum')
                else:values[key]=numerator/valid
            if 'precip' in values and values['precip']<0:reasons.append('negative annual precipitation')
            if 'temp' in values and not -80<=values['temp']-273.15<=70:reasons.append('implausible annual temperature')
        row['included']=not reasons;row['exclusion_reason']='; '.join(reasons);audit.append(row)
        if not reasons:
            annual.append({'water_year':wy,'precip_mm':round(values['precip'],6),'temp_c':round(values['temp']-273.15,6)})
    if not annual:raise ValueError('No complete source water year passed validation.')
    text=csv_text(['water_year','precip_mm','temp_c'],annual)
    # Validate the deliverable with the actual dashboard CSV reader, inside this worker.
    namespace={};exec(app_source,namespace)
    parsed,parser_audit=namespace['lt_climate_rows'](text,max(r['water_year'] for r in annual))
    if len(parsed)!=len(annual):raise ValueError('Dashboard rejected climate records.')
    years=[r['water_year'] for r in annual]
    metadata={'aquifer':plan['aquifer'],'retrieved_utc':retrieved,'calendar':plan['calendar'],
              'start_water_year':min(years),'end_water_year':max(years),'complete_water_years':len(annual),
              'gregorian_start':plan['periods'][0]['start'],'gregorian_end_exclusive':plan['periods'][-1]['end_exclusive'],
              'sources':plan['sources'],'source_catalog':plan['source_catalog'],'boundary_sha256':plan['boundary_sha256'],
              'boundary_file':'MASHHAD_CLIMATE_BOUNDARY.geojson','boundary_buffer_m':0,
              'spatial_aggregation':'For each source separately, native projection and affine transform; sum(value * pixelArea) / sum(valid pixelArea), clipped to the aquifer. Earth Engine weighted reduction includes polygon-edge fractions; no bbox average, smoothing or upsampling.',
              'temporal_aggregation':{'precip_mm':'Sum of every daily precipitation image in exact Mehr-to-Mehr interval; spatial area mean of accumulated depth, mm.',
                                      'temp_c':'Mean of every daily mean temperature image in exact Mehr-to-Mehr interval; spatial area mean, then Kelvin minus 273.15. Leap days included; no unweighted mean of calendar months.'},
              'time_basis':'Source daily UTC calendar labels; Persian WY boundaries mapped to Gregorian dates. No hourly shift to local-midnight Iran.',
              'quality_control':{'required_daily_images':'exact expected day count, unique date count and min/max per-pixel observation count',
                                 'minimum_spatial_coverage_fraction':0.999,'missing_data':'No imputation; incomplete years excluded and listed in audit.',
                                 'excluded_water_years':[r['water_year'] for r in audit if not r['included']]},
              'summary':{key:{'min':min(r[key] for r in annual),'mean':mean(r[key] for r in annual),'max':max(r[key] for r in annual)} for key in ('precip_mm','temp_c')},
              'dashboard_validation':parser_audit,'csv_sha256':hashlib.sha256(text.encode()).hexdigest(),
              'execution':{'public_source_aggregation':'Explicitly requested Google Earth Engine processing.',
                           'calendar_planning_validation_conversion_and_csv':'Client-side Python in a Pyodide browser worker.',
                           'host':'Credentials, GEE transport, static files and output file I/O only.',
                           'private_piezometer_or_quality_records_sent_to_GEE':False},
              'limitations':['Gridded historical estimates, not local station observations or future climate projections.',
                             'No bias correction or validation against local rain gauges/temperature stations was performed.',
                             'CHIRPS blends satellite and station data; ERA5-Land is reanalysis, not a direct satellite thermometer.',
                             'Aquifer-average air temperature is not groundwater temperature or a recharge estimate.',
                             'A valid input CSV does not guarantee acceptance of the dashboard empirical climate-response model.']}
    audit_columns=list(dict.fromkeys(k for row in audit for k in row))
    report=f'''# اقلیم تاریخی آبخوان مشهد از GEE

فایل اصلی برای ورود به داشبورد: **MASHHAD_CLIMATE_WY.csv**.

این فایل {len(annual)} سال آبی کامل، از **{min(years)} تا {max(years)}** دارد. سال آبی از ۱ مهر تا پایان شهریور است و با سال آغاز نام‌گذاری می‌شود. بازهٔ میلادی از `{metadata['gregorian_start']}` تا پیش از `{metadata['gregorian_end_exclusive']}` است. تاریخ دریافت: `{retrieved}`.

| ستون | تعریف |
|---|---|
| water_year | سال آبی شمسی؛ نام سال شروع |
| precip_mm | مجموع بارش روزانهٔ سال آبی، به صورت میانگین مساحتی آبخوان، میلی‌متر |
| temp_c | میانگین روزانهٔ دمای هوای دو متری در سال آبی، میانگین مساحتی آبخوان، درجهٔ سانتی‌گراد |

## منابع و روش

- بارش: [CHIRPS v2 Final روزانه]({SOURCES['precip']['url']})، باند precipitation با تفکیک اصلی ۰٫۰۵ درجه؛ [Funk و همکاران، ۲۰۱۵](https://doi.org/10.1038/sdata.2015.66).
- دما: [ERA5-Land Daily Aggregated]({SOURCES['temp']['url']})، باند temperature_2m با تفکیک اصلی ۰٫۱ درجه. Copernicus Climate Change Service / ECMWF و تجمیع روزانهٔ Google. این منبع بازتحلیل است.
- محدوده: همان پلیگون «مشهد» از Data/AQUIFER.geojson، شامل حفره‌های مرز و بدون بافر. مرز استفاده‌شده و هش آن همراه فایل‌اند.
- هر منبع روی شبکه و تبدیل افاین اصلی خودش پردازش شده است. مقدار هر پیکسل در مساحت آن ضرب و در محدوده جمع شده، سپس بر مساحت معتبر تقسیم شده است؛ کادر پیرامونی جای پلیگون استفاده نشده است. سهم پیکسل‌های مرزی طبق وزن‌دهی ناحیه‌ای GEE محاسبه می‌شود.
- بارش روزانه در فاصلهٔ دقیق مهر تا مهر جمع می‌شود. دما میانگین تمام میانگین‌های روزانهٔ همان فاصله است، سپس ۲۷۳٫۱۵ از کلوین کم می‌شود. روز کبیسه حفظ می‌شود؛ میانگین سادهٔ ۱۲ ماه با طول‌های متفاوت استفاده نشده است.
- تاریخ روزانهٔ منابع بر پایهٔ UTC است؛ برچسب‌های روزانه به سال آبی تخصیص یافته‌اند و مرز ساعت به نیمه‌شب محلی ایران منتقل نشده است.
- تعداد تصاویر، تعداد تاریخ‌های یکتا، حداقل/حداکثر روزهای معتبر در پیکسل‌ها و پوشش مکانی کنترل شده‌اند. بازسازی، جایگزینی با صفر و پرکردن سال ناقص انجام نشده است. سال‌های حذف‌شده: {metadata['quality_control']['excluded_water_years']}.
- برنامه‌ریزی تقویم، کنترل کیفیت، تبدیل واحد دما، ساخت CSV و آزمون با خوانشگر واقعی داشبورد در Pyodide مرورگر انجام شده‌اند. GEE فقط آماده‌سازیِ صریح منابع عمومی را انجام داده است؛ دادهٔ پیزومتر یا کیفیت به آن ارسال نشده است.

## استفاده

در «نمای سه‌بعدی»، پس از انتخاب مشهد، فایل اصلی را در «داده‌ها ← بارش و دما» یا «عمر سناریویی ← اقلیم ← سابقهٔ بارش و دما» انتخاب کنید. فایل به‌صورت پیش‌فرض داخل داشبورد خوانده نمی‌شود. سال‌های پس از تاریخ پایان مدل طبق قواعد موجود داشبورد از برازش کنار گذاشته می‌شوند. معتبر بودن فایل به معنی تأیید مدل اثر اقلیم نیست؛ آن مدل باید شرط سابقهٔ مشترک و آزمون زمانی خودش را بگذراند.

## محدودیت

این داده‌ها اقلیم تاریخیِ شبکه‌ای هستند؛ مشاهدهٔ ایستگاهی محلی یا پیش‌بینی آینده نیستند. تصحیح سوگیری با ایستگاه‌های مشهد انجام نشده است. تفکیک اصلی منابع با شبکهٔ پیکسل‌های مدیریتی داشبورد فرق دارد؛ ریزترکردن شبکه، دقت اقلیم را بیشتر نمی‌کند. دمای هوا نمایندهٔ دمای آب زیرزمینی یا مقدار تغذیه نیست. از این سری به‌تنهایی نمی‌توان تغییرات برداشت و اثر اقلیم را تفکیک علّی کرد.

شناسنامهٔ کامل، مقادیر خام GEE و جدول ممیزی در همین پوشه نگهداری می‌شوند. اعداد فرضی یا سناریویی به سری اضافه نشده‌اند.
'''
    return {'metadata':metadata,'files':{'MASHHAD_CLIMATE_WY.csv':text,
            'MASHHAD_CLIMATE_AUDIT.csv':csv_text(audit_columns,audit),
            'MASHHAD_CLIMATE_METADATA.json':json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',
            'MASHHAD_CLIMATE_BOUNDARY.geojson':json.dumps({'type':'FeatureCollection','features':[plan['feature']]},ensure_ascii=False)+'\n',
            'README.fa.md':report}}

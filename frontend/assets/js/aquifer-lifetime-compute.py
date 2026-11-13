"""Conditional first-passage scenarios, executed exclusively in browser Pyodide.

No pumping-response, groundwater-age or geomechanical inversion is implied.
"""
import csv
import io
import json
import math
import hashlib
from copy import deepcopy


def lt_num(value, label, low=None, high=None):
    try:
        v=float(value)
    except (ValueError, TypeError):
        raise ValueError(label+': عدد معتبر لازم است.')
    if not math.isfinite(v) or low is not None and v<low or high is not None and v>high:
        raise ValueError(label+': مقدار خارج از دامنه است.')
    return v


def lt_climate_rows(text, end_wy):
    """One aquifer-average record/month or WY; never sum spatial duplicates."""
    rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    if not rows:
        raise ValueError('فایل اقلیم خالی است.')
    annual='water_year' in rows[0]
    periods={}
    for r in rows:
        if not any(str(v or '').strip() for v in r.values()):continue
        y=lt_num(r.get('water_year' if annual else 'year_persian'),'سال اقلیم',1200,1600)
        if y!=int(y):raise ValueError('سال اقلیم باید صحیح باشد.')
        y=int(y)
        if annual:key=(y,)
        else:
            m=lt_num(r.get('month_persian'),'ماه اقلیم',1,12)
            if m!=int(m):raise ValueError('ماه اقلیم باید صحیح باشد.')
            m=int(m);key=(y,m)
        if key in periods:raise ValueError('رکورد اقلیم تکراری است؛ فایل باید میانگین مکانی یک آبخوان باشد.')
        periods[key]=(lt_num(r.get('precip_mm'),'بارش',0,20000),lt_num(r.get('temp_c'),'دما',-80,70))
    out={}
    if annual:
        out={k[0]:v for k,v in periods.items() if k[0]<=end_wy}
    else:
        grouped={}
        for (y,m),v in periods.items():grouped.setdefault(y if m>=7 else y-1,[]).append(v)
        out={wy:(sum(v[0] for v in values),sum(v[1] for v in values)/12)
             for wy,values in grouped.items() if len(values)==12 and wy<=end_wy}
    return out,{'rows':len(periods),'complete_water_years':len(out),
                'calendar':'Persian water year: Mehr–Shahrivar; named starting year',
                'monthly_temperature_aggregation':'mean of 12 monthly means',
                'sha256':hashlib.sha256(text.encode()).hexdigest()}


def lt_fit_climate(management, text, end_wy):
    """Empirical regional dH response; expanding temporal holdout vs secular trend."""
    import numpy as np
    if not text.strip():return {'accepted':False,'reason':'سابقهٔ بارش و دما وارد نشده است.'}
    climate,audit=lt_climate_rows(text,end_wy)
    series={}
    for w in management.get('histories',[]):
        by={r['water_year']:r['level'] for r in w['records'] if r.get('month')==6}
        for y in by:
            if y-1 in by:series.setdefault(y,[]).append(by[y]-by[y-1])
    changes={y:sum(v)/len(v) for y,v in series.items() if len(v)>=3 and y<=end_wy}
    candidates=[]
    for lag in (0,1):
        pairs=sorted((y,changes[y],*climate[y-lag]) for y in changes if y-lag in climate)
        if len(pairs)<12:continue
        a=np.array(pairs,float)
        def fit(train):
            raw=train[:,[0,2,3]];mean=raw.mean(axis=0);sd=raw.std(axis=0)
            if np.any(sd<1e-8):return None
            x=np.column_stack((np.ones(len(train)),(raw-mean)/sd))
            if np.linalg.cond(x)>100:return None
            beta=np.linalg.lstsq(x,train[:,1],rcond=None)[0]
            return beta,mean,sd
        errors=[];baseline=[]
        for i in range(8,len(a)):
            fitted=fit(a[:i])
            if fitted is None:continue
            beta,mean,sd=fitted
            estimate=np.r_[1,(a[i,[0,2,3]]-mean)/sd]@beta
            x=np.column_stack((np.ones(i),a[:i,0]-a[0,0]))
            b=np.linalg.lstsq(x,a[:i,1],rcond=None)[0]
            errors.append(abs(float(estimate-a[i,1])))
            baseline.append(abs(float(b[0]+b[1]*(a[i,0]-a[0,0])-a[i,1])))
        fitted=fit(a)
        if fitted is None or len(errors)<4:continue
        beta,mean,sd=fitted;bp=float(beta[2]/sd[1]);bt=float(beta[3]/sd[2])
        mae=sum(errors)/len(errors);base=sum(baseline)/len(baseline)
        candidates.append({'accepted':base>0 and mae<=.9*base and bp>=0 and bt<=0,
            'lag_years':lag,'beta_precip_m_per_mm':bp,'beta_temp_m_per_c':bt,
            'baseline_precip_mm':float(mean[1]),'baseline_temp_c':float(mean[2]),
            'precip_range_mm':[float(a[:,2].min()),float(a[:,2].max())],
            'temp_range_c':[float(a[:,3].min()),float(a[:,3].max())],
            'start_water_year':int(a[0,0]),'end_water_year':int(a[-1,0]),'years':len(a),
            'holdout_count':len(errors),'mae_m_year':mae,'baseline_mae_m_year':base,
            'improvement_pct':100*(1-mae/base) if base>0 else None})
    accepted=[c for c in candidates if c['accepted']]
    result=min(accepted or candidates,key=lambda c:c['mae_m_year']) if candidates else {'accepted':False}
    result.update(audit)
    result['reason']='اثر تجربی منطقه‌ای پذیرفته شد.' if result['accepted'] else 'داده یا بهبود آزمون زمانی کافی نیست؛ اثر اقلیم اعمال نشد.'
    result['method']='Regional mean September-to-September dH, >=3 common observed wells/year; OLS with secular time trend, P and T; expanding 8-year training; >=12 pairs and 4 holdouts; >=10% MAE improvement; lag 0/1 selection uses same holdouts, not independent validation; sign guard P>=0 T<=0. Association, not causal recharge or pumping attribution.'
    return result


def lt_fraction(ec,limit,ratio):
    if ratio==1:return 1. if ec<=limit else 0.
    # Same geometric-mid-column reference as the quality module; no depth data invented.
    value=.5+math.log(limit/ec)/math.log(ratio)
    return max(0.,min(1.,value)) if ratio>1 else 1-max(0.,min(1.,value))


def lt_scenario(raw):
    s=deepcopy(raw)
    s['name']=str(s.get('name') or 'سناریو').strip()[:80]
    s['spatial_coverage']=s.get('spatial_coverage','supported')
    if s['spatial_coverage'] not in ('supported','aquifer'):
        raise ValueError('نوع پوشش مکانی روند معتبر نیست.')
    s['spatial_method']=s.get('spatial_method','idw')
    if s['spatial_method'] not in ('idw','spline','thiessen'):raise ValueError('روش مکانی روند معتبر نیست.')
    s['spline_smoothing']=lt_num(s.get('spline_smoothing',0),'هموارسازی Spline',0)
    for key,default in [('quantity','current'),('quality','manual'),('subsidence','source'),('climate','manual')]:
        s[key+'_window']=str(s.get(key+'_window',default))
        if s[key+'_window'] not in (default,'4','10','all','custom'):raise ValueError('دورهٔ روند '+key+' معتبر نیست.')
        s[key+'_window_years']=lt_num(s.get(key+'_window_years',10) if s[key+'_window']=='custom' else 10,'طول دورهٔ روند',3,200)
        if s[key+'_window_years']!=int(s[key+'_window_years']):raise ValueError('طول دوره باید صحیح باشد.')
    if s['quantity_window']!='current':s['manual_drop_m_year']=None
    if s['quality_window']!='manual':s['ec_growth_pct']=0
    if s['climate_window']!='manual':s.update(climate_precip_pct=0,climate_temp_c=0,climate_years=20)
    for k,label,default,low,high in [
        ('horizon','افق',50,1,200),('drop_factor','ضریب روند افت',1,0,10),
        ('transition_years','زمان تغییر مسیر',1,0,200),('floor_offset_m','تغییر تراز کف',0,-1000,1000),
        ('sy_factor','ضریب Sy',1,.01,10),('ec_growth_pct','رشد شوری',0,-50,100),
        ('sub_factor','ضریب نرخ نشست',1,0,10),('climate_precip_pct','تغییر بارش',0,-100,200),
        ('climate_temp_c','تغییر دما',0,-10,15),('climate_years','زمان تحقق اقلیم',20,1,200),
        ('sensitivity_floor_m','حساسیت کف',0,0,1000),('sensitivity_sy_pct','حساسیت Sy',0,0,90),
        ('sensitivity_ec_pct','حساسیت نرخ EC',0,0,100),('area_target_pct','سهم مساحت بحرانی',25,.1,100),
        ('min_usable_pct','حداقل سهم زیر آستانه شوری',50,0,100)]:
        s[k]=lt_num(s.get(k,default),label,low,high)
    if s['horizon']!=int(s['horizon']):raise ValueError('افق باید تعداد صحیح سال باشد.')
    s['horizon']=int(s['horizon'])
    for key,limit,label in [('quantity',None if s.get('quantity_type')=='head' else 0,'حد کمّی'),('quality',1,'حد EC شرب'),('crop',1,'حد EC کشاورزی'),('subsidence',0,'حد نشست')]:
        if key=='crop':
            if s.get('quality_on'):s['crop_limit']=lt_num(s.get('crop_limit'),label,limit)
        elif s.get(key+'_on'):s[key+'_limit']=lt_num(s.get(key+'_limit'),label,limit)
    # Existing quality may be present while only quantity is active. HTML values
    # still arrive as strings; normalize optional limits used by volume curves.
    for key in ('quality_limit','crop_limit'):
        s[key]=lt_num(s[key],'حد EC',1) if s.get(key) not in (None,'') else None
    if not any(s.get(k+'_on') for k in ('quantity','quality','subsidence')):raise ValueError('حداقل یک محدودیت را فعال کنید.')
    if s.get('quantity_type','saturated') not in ('saturated','head','drawdown','storage_loss_pct'):raise ValueError('تعریف آستانهٔ کمّی نامعتبر است.')
    if s.get('quantity_on') and s.get('quantity_type')=='storage_loss_pct' and not 0<s['quantity_limit']<=100:
        raise ValueError('درصد کاهش ذخیره باید بزرگ‌تر از صفر و حداکثر ۱۰۰ باشد.')
    if s.get('quality_mode','ec') not in ('ec','fraction'):raise ValueError('تعریف کیفیت نامعتبر است.')
    if s.get('use','crop') not in ('crop','drinking'):raise ValueError('مصرف نامعتبر است.')
    if s.get('manual_drop_m_year') not in (None,''):s['manual_drop_m_year']=lt_num(s['manual_drop_m_year'],'نرخ افت انتخابی',-50,50)
    else:s['manual_drop_m_year']=None
    if s.get('phase_year') not in (None,''):
        s['phase_year']=lt_num(s['phase_year'],'سال شروع مرحله دوم',0,s['horizon'])
        s['phase_factor']=lt_num(s.get('phase_factor',1),'ضریب مرحله دوم',0,10)
    else:s['phase_year']=None
    return s


def lt_zones(text):
    from shapely.geometry import shape
    if not text:return []
    obj=json.loads(text)
    if obj.get('type')!='FeatureCollection':raise ValueError('زون‌ها باید GeoJSON FeatureCollection باشند.')
    out=[]
    for feature in obj['features']:
        geom=shape(feature['geometry'])
        if geom.geom_type not in ('Polygon','MultiPolygon') or geom.is_empty or not geom.is_valid:raise ValueError('پلیگون زون معتبر نیست.')
        w,s,e,n=geom.bounds
        if w < -180 or e > 180 or s < -90 or n > 90:raise ValueError('مختصات زون باید طول و عرض جغرافیایی WGS84 باشد.')
        props=feature.get('properties',{})
        allowed={k:props[k] for k in ('drop_factor','ec_growth_pct','sub_factor','sy_factor','floor_offset_m') if k in props}
        if not allowed:raise ValueError('زون باید حداقل یک پارامتر سناریو داشته باشد.')
        out.append((geom,allowed))
    for i,(a,_) in enumerate(out):
        if any(a.intersection(b).area>1e-12 for b,_ in out[i+1:]):raise ValueError('زون‌های سناریو نباید همپوشانی داشته باشند.')
    return out


def lt_quantity_cutoff(current, floor, sy, kind, limit):
    """Convert a user criterion to a local head threshold; no display rim used."""
    if kind=='head':return limit
    if kind=='drawdown':return current-limit
    if floor is None:return None
    if kind=='storage_loss_pct':
        if sy is None:return None
        # Sy is fixed with time within a scenario, so the volume ratio equals
        # the thickness ratio. A known zero initial column is already depleted.
        return floor+max(current-floor,0)*(1-limit/100)
    return floor+limit


def lifetime_presets(data, management, quality=None):
    """Explicit comparison assumptions; never claim calibrated policy effects."""
    cells=(management or {}).get('plan_maps',{}).get('cells',[])
    quantity=any(c.get('bedrock_msl') is not None and c.get('sy') is not None for c in cells)
    quality_ready=bool(quality and quality.get('report',{}).get('sites',0))
    sub=(management or {}).get('report',{}).get('subsidence',{})
    rates=sorted((c['management_subsidence'],c['area_m2']) for c in cells if c.get('management_subsidence') is not None and c['management_subsidence']>0) if sub.get('component')=='vertical' else []
    rate=None
    if rates:
        half=sum(a for v,a in rates)/2;acc=0
        for v,a in rates:
            acc+=a
            if acc>=half:rate=v;break
    thresholds=(quality or {}).get('report',{}).get('thresholds',{})
    base={'horizon':50,'use':'crop','quantity_type':'storage_loss_pct','quantity_limit':25,'drop_factor':1,
          'transition_years':5,'manual_drop_m_year':None,'sy_factor':1,'floor_offset_m':0,'phase_year':None,
          'ec_growth_pct':0,'sub_factor':1,'subsidence_limit':rate*5 if rate is not None else None,
          'quality_limit':thresholds.get('drinking_ec_uScm',1500),'crop_limit':thresholds.get('irrigation_ec_uScm',3000),
          'area_target_pct':25,'quality_mode':'ec','min_usable_pct':50,'climate_on':False,'sensitivity_on':False}
    out=[]
    def add(key,group,name,active,overrides,assumption):
        missing=[]
        if 'quantity' in active and not quantity:missing.append('سنگ‌بستر و Sy')
        if 'quality' in active and not quality_ready:missing.append('محاسبهٔ کیفیت از فایل کاربر')
        if 'subsidence' in active and rate is None:missing.append('لایهٔ قائمِ نشست با نرخ مثبت و دورهٔ معتبر')
        config={**base,'quantity_on':'quantity' in active,'quality_on':'quality' in active,'subsidence_on':'subsidence' in active,**overrides,'name':name}
        out.append({'id':key,'group':group,'name':name,'ready':not missing,'missing':missing,'scenario':config,
                    'assumption':assumption,'subsidence_reference_rate_mm_year':rate,
                    'common_note':'فرض قابل‌ویرایش برای مقایسه؛ حد ایمنی یا پیش‌بینی قطعی نیست. ضریب روند معادل درصد تغییر برداشت نیست. حدود EC از تنظیم کیفیت جاری خوانده می‌شوند. آستانهٔ نشست معادل پنج سال نرخ میانهٔ مساحتیِ فایل شماست و حد مهندسی آسیب نیست.'})
    add('q_base','کمیت','کمیت · ادامهٔ روند',['quantity'],{},'کاهش ۲۵٪ ذخیرهٔ شروع هر پیکسل، با ادامهٔ روند مشاهده‌شده.')
    add('q_action','کمیت','کمیت · کاهش تدریجی افت',['quantity'],{'drop_factor':.7},'رسیدن ضریب روند به ۰٫۷ طی پنج سال؛ همان آستانهٔ کاهش ۲۵٪ ذخیره.')
    add('q_pressure','کمیت','کمیت · تشدید افت',['quantity'],{'drop_factor':1.3},'رسیدن ضریب روند به ۱٫۳ طی پنج سال؛ سنجش حساسیت به افت سریع‌تر.')
    for key,name,growth in [('ec_fixed','EC ثابت',0),('ec_gradual','رشد سالانهٔ ۱٪',1),('ec_pressure','رشد سالانهٔ ۳٪',3)]:
        add(key,'شوری','شوری · '+name,['quality'],{'ec_growth_pct':growth},f'تغییر مرکب EC به میزان {growth} درصد در سال؛ نرخ فرضی است و از دادهٔ تک‌مقطعی استخراج نشده.')
    for key,name,factor in [('sub_base','ادامهٔ نرخ',1),('sub_action','نرخ کمتر',.7),('sub_pressure','نرخ بیشتر',1.3)]:
        add(key,'فرونشست','فرونشست · '+name,['subsidence'],{'sub_factor':factor},f'ضریب نرخ نشست {factor}؛ آستانه از پنج برابر میانهٔ نرخ مثبت فایل کاربر ساخته می‌شود.')
    add('q_ec','ترکیبی','کمیت و شوری',['quantity','quality'],{'ec_growth_pct':1},'کاهش ۲۵٪ ذخیره یا عبور شوری با رشد فرضی یک درصد؛ هرکدام زودتر رخ دهد.')
    add('q_sub','ترکیبی','کمیت و فرونشست',['quantity','subsidence'],{},'کاهش ۲۵٪ ذخیره یا عبور از آستانه نشست؛ هرکدام زودتر رخ دهد.')
    add('ec_sub','ترکیبی','شوری و فرونشست',['quality','subsidence'],{'ec_growth_pct':1},'عبور شوری با رشد فرضی یک درصد یا آستانه نشست؛ مستقل از محدودیت کمّی و هرکدام زودتر رخ دهد.')
    for key,name,overrides in [('all_base','ادامهٔ وضعیت',{'ec_growth_pct':1}),('all_action','مهار فشار',{'drop_factor':.7,'ec_growth_pct':0,'sub_factor':.7}),('all_pressure','فشار بیشتر',{'drop_factor':1.3,'ec_growth_pct':3,'sub_factor':1.3})]:
        add(key,'ترکیبی','هر سه محدودیت · '+name,['quantity','quality','subsidence'],overrides,'اولین عبور از هر سه محدودیت؛ تغییر ضرایب، فرض مدیریتی برای مقایسه است و رابطهٔ علّی مشترک فرض نمی‌شود.')
    return out


def lifetime_quantity_reference(data, management, raw, zones_text=''):
    """Lightweight browser preview; the same cutoffs as the full scenario."""
    if not raw.get('quantity_on',True):return None
    if not management or management['report']['aquifer']!=data['aquifer']:
        raise ValueError('ابتدا روند آبخوان آماده شود.')
    s=lt_scenario({**{k:raw[k] for k in ('quantity_type','quantity_limit','sy_factor','floor_offset_m') if k in raw},'quantity_on':True})
    from shapely.geometry import Point
    zones=lt_zones(zones_text);variant=raw.get('_variant',{})
    area=sum(c['area_m2'] for c in management['plan_maps']['cells'])
    supported=0.;zero_area=0.;initial=0.;target=0.;drops=[]
    factor=management['report'].get('volume_factor',1)
    for c in management['plan_maps']['cells']:
        hits=[p for g,p in zones if g.covers(Point(c['lon'],c['lat']))]
        if len(hits)>1:raise ValueError('مرکز پیکسل روی مرز مشترک زون‌هاست؛ تعارض پارامتر را رفع کنید.')
        local=lt_scenario({**s,**(hits[0] if hits else {})})
        floor=c.get('bedrock_msl');sy=c.get('sy')
        if floor is None or sy is None:continue
        floor+=local['floor_offset_m']+variant.get('floor',0)
        sy*=local['sy_factor']*variant.get('sy',1)
        if not 0<sy<1:raise ValueError('Sy سناریو باید بین صفر و یک باشد.')
        current=c['after_msl'];cutoff=lt_quantity_cutoff(current,floor,sy,local.get('quantity_type','saturated'),local['quantity_limit'])
        thickness=max(current-floor,0);a=c['area_m2'];scale=sy*a/1e6*factor
        supported+=a;initial+=thickness*scale
        # Report the additional loss from the initial state, bounded by storage.
        target+=min(thickness,max(0,cutoff-floor))*scale
        if thickness>0:drops.append((max(0,current-cutoff),a))
        else:zero_area+=a
    median=None
    if drops:
        half=sum(a for _,a in drops)/2;acc=0.
        for value,a in sorted(drops):
            acc+=a
            if acc>=half:median=value;break
    return {'criterion':s.get('quantity_type','saturated'),'limit':s['quantity_limit'],
            'reference_date':data['dates']['after'],'reference_water_year':data['dates']['after_water_year'],
            'initial_storage_mcm':initial if supported else None,'target_storage_mcm':target if supported else None,
            'equivalent_loss_mcm':initial-target if supported else None,
            'remaining_pct':100-s['quantity_limit'] if s.get('quantity_type')=='storage_loss_pct' else None,
            'equivalent_drawdown_median_m':median,'equivalent_drawdown_min_m':min((v for v,a in drops),default=None),
            'equivalent_drawdown_max_m':max((v for v,a in drops),default=None),
            'storage_supported_area_pct':100*supported/area,'zero_initial_storage_area_pct':100*zero_area/area,
            'basis':'Each cell separately, initial scenario head/floor/Sy; original physical floor; scenario Sy fixed in time. Area-weighted median head drop uses positive initial columns. Volume sums include cells with floor/Sy regardless of trend coverage; they are reference equivalents, not a simultaneous aquifer-wide crossing.',
            'zero_initial_policy':'Known zero initial storage is an existing quantity limitation at t=0; no percentage of zero is inferred.'}


def lifetime_analysis(data, management, quality, raw, climate_text='', zones_text='', sensitivity=True, source_context=None):
    from shapely.geometry import Point
    if data.get('spatial'):
        raw={**raw,'spatial_method':data['spatial']['method'],'spline_smoothing':data['spatial']['spline_smoothing'],'spatial_coverage':'aquifer'}
    s=lt_scenario(raw);end_wy=data['dates']['after_water_year']
    if not management or management['report']['aquifer']!=data['aquifer']:raise ValueError('ابتدا روند آبخوان در «آینده و اقدام» آماده شود.')
    if management['report'].get('trend_end_water_year',end_wy)!=end_wy:raise ValueError('روند مربوط به تاریخ مدل فعال نیست.')
    if quality and quality['report']['volume_dates']!=data['dates']:raise ValueError('کیفیت مربوط به مدل فعال نیست.')
    if quality and quality['report'].get('aquifer',data['aquifer'])!=data['aquifer']:raise ValueError('کیفیت مربوط به آبخوان فعال نیست.')
    if data.get('spatial'):
        active_method=data['spatial']['method']
        if (management['report'].get('spatial') or {}).get('method')!=active_method:raise ValueError('روش مکانی روند با داده‌های آبخوان یکسان نیست؛ روند را دوباره محاسبه کنید.')
        if quality and (quality['report'].get('spatial') or {}).get('method')!=active_method:raise ValueError('روش مکانی کیفیت با داده‌های آبخوان یکسان نیست؛ کیفیت را دوباره محاسبه کنید.')
    source_context=source_context or {};rate_audit={}
    if s['quantity_window']!='current' or s['spatial_method']!='idw':
        management,rate_audit['quantity']=tr_quantity(management,s,mg_fit,mg_support)
    else:rate_audit['quantity']={'mode':'current','start_water_year':management['report'].get('trend_start_water_year'),'end_water_year':end_wy,'eligible_wells':management['report'].get('eligible_wells'),'spatial_method':'idw'}
    if s['manual_drop_m_year'] is not None:rate_audit['quantity']={'mode':'manual','drop_m_year':s['manual_drop_m_year'],'underlying_network':rate_audit['quantity']}
    if s['subsidence_window']!='source' and s.get('subsidence_on'):
        management=deepcopy(management);source=dict(source_context.get('subsidence_options') or {});text=source.pop('text','')
        headers=next(csv.reader(io.StringIO(text.lstrip('\ufeff'))),[]) if text and not text.lstrip().startswith('{') else []
        if 'water_year' in headers and 'rate_mm_year' in headers:
            query,audit=mg_subsidence(text,{**source,**({'spatial':data['spatial']} if data.get('spatial') else {}),'rate_window':s['subsidence_window'],'rate_window_years':s['subsidence_window_years']},management['plan_maps']['polygons'],management['report'].get('trend_start_water_year',end_wy),end_wy,management['plan_maps']['cells'])
            for c in management['plan_maps']['cells']:
                value=query(c['lon'],c['lat'],c['polygons']);c['management_subsidence']=value['rate'] if isinstance(value,dict) else value
            management['report']['subsidence']=audit
            rate_audit['subsidence']={'mode':s['subsidence_window'],'available':any(c.get('management_subsidence') is not None for c in management['plan_maps']['cells']),'start_water_year':audit.get('rate_period_start_water_year'),'end_water_year':end_wy,'selected_years':audit.get('selected_years',[]),'estimator':audit.get('rate_estimator')}
            if not rate_audit['subsidence']['available']:rate_audit['subsidence']['reason']='پوشش زمانی یا مکانی نرخ سالانه در دورهٔ انتخابی کافی نیست.'
        else:
            for c in management['plan_maps']['cells']:c['management_subsidence']=None
            rate_audit['subsidence']={'mode':s['subsidence_window'],'available':False,'reason':'این فایل یک دورهٔ تجمعی یا نرخ میانگین دارد؛ نرخ بازهٔ دیگر از آن قابل استخراج نیست. فایل نرخ سالانه با ستون water_year لازم است.'}
    else:
        audit=management['report']['subsidence'];rate_audit['subsidence']={'mode':'source' if s.get('subsidence_on') else 'off','periods':audit.get('periods'),'source_years':audit.get('source_years'),'duration_years':audit.get('duration_years'),'annual_rates':audit.get('annual_rates',False),'estimator':'declared-period mean' if audit.get('cumulative') else 'input annual/period rate'}
    quality_rates=None
    if s.get('quality_on') and s['quality_window']!='manual' and quality:
        quality_rates,rate_audit['quality']=tr_ec(source_context.get('quality_records',[]),management['plan_maps']['cells'],management['plan_maps']['polygons'],s,management['report']['settings'],quality['report']['quality_water_year'],mg_fit,mg_support)
    else:rate_audit['quality']={'mode':'manual' if s.get('quality_on') else 'off','growth_pct_year':s['ec_growth_pct'] if s.get('quality_on') else None}
    if s.get('climate_on'):
        climate=lt_fit_climate(management,climate_text,end_wy)
        if s['climate_window']!='manual':
            series,_=lt_climate_rows(climate_text,end_wy) if climate_text.strip() else ({},{})
            rate_audit['climate']=tr_climate(series,s,end_wy,mg_fit)
            climate['rate_trend']=rate_audit['climate']
            if not rate_audit['climate']['available']:
                climate['accepted']=False;climate['reason']=rate_audit['climate']['reason']
        if climate['accepted']:
            trend=climate.get('rate_trend')
            p=max(0,trend['reference_precip_mm']+trend['precip_slope_mm_year']*s['horizon']) if trend else climate['baseline_precip_mm']*(1+s['climate_precip_pct']/100)
            t=trend['reference_temp_c']+trend['temp_slope_c_year']*s['horizon'] if trend else climate['baseline_temp_c']+s['climate_temp_c']
            climate['scenario_precip_mm']=p;climate['scenario_temp_c']=t
            climate['outside_historical_range']=not(climate['precip_range_mm'][0]<=p<=climate['precip_range_mm'][1] and climate['temp_range_c'][0]<=t<=climate['temp_range_c'][1])
    else:climate={'accepted':False,'reason':'اثر اقلیم خاموش است.'}
    rate_audit.setdefault('climate',{'mode':'manual' if s.get('climate_on') else 'off'})
    rate_audit['climate']['effect_applied']=bool(s.get('climate_on') and climate['accepted'])
    if s.get('climate_on') and not climate['accepted']:rate_audit['climate']['reason']=climate['reason']
    zones=lt_zones(zones_text)
    qcells={(round(c['lon'],8),round(c['lat'],8)):c for c in (quality or {}).get('plan_maps',{}).get('cells',[])}
    cells=deepcopy(management['plan_maps']['cells']);curves=[{'year':i,'critical_area_m2':0.,'unknown_area_m2':0.,'remaining_mcm':0.,'volume_unknown_area_m2':0.,'usable_mcm':0.,'quality_unknown_mcm':0.} for i in range(math.ceil(s['horizon'])+1)]
    for cell in cells:
        extended=(s['spatial_coverage']=='aquifer' and cell.get('management_slope') is None
                  and cell.get('management_extended_slope') is not None)
        cell['life_trend_extrapolated']=(extended or cell.get('management_spatial_estimated',False)) and s['manual_drop_m_year'] is None
        cell['life_trend_support_reasons']=cell.get('management_support_reasons',[])
        cell['life_trend_nearest_km']=cell.get('management_nearest_well_km')
        if extended:
            for suffix in ('','_low','_high'):
                cell['management_slope'+suffix]=cell['management_extended_slope'+suffix]
            cell['management_decline']=-cell['management_slope']
        cell['life_support']=3 if s['manual_drop_m_year'] is not None else 1 if cell['life_trend_extrapolated'] else 0 if cell.get('management_slope') is not None else 2
        cell['life_trend_source']={0:'network_'+s['spatial_method'],1:'extended_'+s['spatial_method'],2:'unavailable',3:'manual'}[cell['life_support']]
        cell['life_spatial_method']=s['spatial_method'];cell['life_nearest_well_name']=cell.get('management_nearest_well_name');cell['life_spline_overshoot']=bool(cell.get('management_spline_overshoot',False) and cell.get('management_slope') is not None and s['manual_drop_m_year'] is None)
    # Quarterly integration includes all user phase boundaries; crossing interpolated within each segment.
    times=sorted({0.,s['horizon'],*[min(s['horizon'],i/4) for i in range(1,math.ceil(s['horizon']*4)+1)],
                  *([s['phase_year']] if s['phase_year'] is not None else []),min(s['transition_years'],s['horizon']),
                  *([min(climate['lag_years'],s['horizon']),min(climate['lag_years']+s['climate_years'],s['horizon'])] if climate['accepted'] else [])})
    subaudit=management['report']['subsidence'];ratio=(quality or {}).get('report',{}).get('vertical_model',{}).get('bottom_top_ec_ratio',1)
    total_area=sum(c['area_m2'] for c in cells);volume_factor=management['report'].get('volume_factor',1)
    variants=raw.get('_variant',{})
    for cell_index,cell in enumerate(cells):
        local=dict(s);hits=[props for geom,props in zones if geom.covers(Point(cell['lon'],cell['lat']))]
        if len(hits)>1:raise ValueError('مرکز پیکسل روی مرز مشترک زون‌هاست؛ تعارض پارامتر را رفع کنید.')
        if hits:local.update(hits[0]);local=lt_scenario(local)
        floor=cell.get('bedrock_msl');sy=cell.get('sy')
        if floor is not None:floor+=local['floor_offset_m']+variants.get('floor',0)
        if sy is not None:
            sy*=local['sy_factor']*variants.get('sy',1)
            if not 0<sy<1:raise ValueError('Sy سناریو باید بین صفر و یک باشد.')
        base_slope=cell.get('management_slope'+variants.get('slope',''))
        if local['manual_drop_m_year'] is not None:base_slope=-local['manual_drop_m_year']
        volume_projectable=floor is not None and sy is not None and base_slope is not None and (not local.get('climate_on') or climate['accepted'])
        current=cell['after_msl'];head=current
        cutoff=lt_quantity_cutoff(current,floor,sy,local.get('quantity_type','saturated'),local['quantity_limit']) if local.get('quantity_on') else None
        qc=qcells.get((round(cell['lon'],8),round(cell['lat'],8)),{})
        ec=qc.get('quality_ec') if qc.get('quality_supported') else None
        # Explicitly carry the chosen EC growth through the source-to-model year gap.
        historical_log=quality_rates[cell_index] if quality_rates is not None else None
        ec_rate=(math.expm1(historical_log)*100 if historical_log is not None else None) if local['quality_window']!='manual' else local['ec_growth_pct']
        if ec_rate is not None:ec_rate+=variants.get('ec',0)
        if ec_rate is not None and (not math.isfinite(ec_rate) or ec_rate<=-100):raise ValueError('نرخ شوری در دامنهٔ حساسیت نامعتبر است.')
        ec_log_rate=math.log1p(ec_rate/100) if ec_rate is not None else None
        gap=end_wy-(quality or {}).get('report',{}).get('quality_water_year',end_wy)
        if ec is not None and gap:
            ec=math.exp(min(690,max(-690,math.log(ec)+ec_log_rate*gap))) if ec_log_rate is not None else None
        subrate=cell.get('management_subsidence') if subaudit.get('component')=='vertical' else None
        crossed={k:None for k in ('quantity','drinking','crop','subsidence')}
        known={'quantity':not local.get('quantity_on') or cutoff is not None and (base_slope is not None or head<=cutoff),
               'drinking':ec is not None and ec_log_rate is not None,'crop':ec is not None and ec_log_rate is not None,'subsidence':subrate is not None}
        if ec is not None and local.get('quality_on'):
            for use,key in [('drinking','quality_limit'),('crop','crop_limit')]:
                if (lt_fraction(ec,local[key],ratio)*100<=local['min_usable_pct'] if local.get('quality_mode')=='fraction' else ec>=local[key]):known[use]=True
        if local.get('climate_on') and not climate['accepted'] and (cutoff is None or head>cutoff):known['quantity']=False
        previous_values={};active=['quantity'] if local.get('quantity_on') else []
        if local.get('quality_on'):active.append(local.get('use','crop'))
        if local.get('subsidence_on'):active.append('subsidence')
        tprev=0
        def ec_at(t):return None if ec is None or t>0 and ec_log_rate is None else ec if t==0 else math.exp(min(690,max(-690,math.log(ec)+ec_log_rate*t)))
        def combine():
            times_known=[(crossed[k],k) for k in active if crossed[k] is not None]
            if times_known and min(t for t,k in times_known)==0:return 0.,'already',[k for t,k in times_known if t==0]
            if any(not known[k] for k in active):return None,'unknown',[]
            if not times_known:return None,'beyond',[]
            first=min(t for t,k in times_known);return first,'crossing',[k for t,k in times_known if abs(t-first)<1e-7]
        for t in times:
            dt=t-tprev;mid=(t+tprev)/2
            factor=1+(local['drop_factor']-1)*min(1,mid/local['transition_years']) if local['transition_years']>0 else local['drop_factor']
            if local['phase_year'] is not None and mid>=local['phase_year']:factor=local['phase_factor']
            if base_slope is not None:
                change=base_slope*factor
                if local.get('climate_on') and climate['accepted']:
                    trend=climate.get('rate_trend')
                    if trend:
                        elapsed=max(0,mid-climate['lag_years']);delta_p=max(0,trend['reference_precip_mm']+trend['precip_slope_mm_year']*elapsed)-trend['reference_precip_mm']
                        change+=climate['beta_precip_m_per_mm']*delta_p+climate['beta_temp_m_per_c']*trend['temp_slope_c_year']*elapsed
                    else:
                        ramp=max(0,min(1,(mid-climate['lag_years'])/local['climate_years']))
                        change+=ramp*(climate['beta_precip_m_per_mm']*climate['baseline_precip_mm']*local['climate_precip_pct']/100+climate['beta_temp_m_per_c']*local['climate_temp_c'])
                head+=change*dt
            current_ec=ec_at(t)
            values={}
            if known['quantity'] and cutoff is not None:values['quantity']=head-cutoff
            for use,limit_key in [('drinking','quality_limit'),('crop','crop_limit')]:
                if current_ec is not None and local.get('quality_on'):
                    values[use]=(lt_fraction(current_ec,local[limit_key],ratio)*100-local['min_usable_pct']) if local.get('quality_mode')=='fraction' else local[limit_key]-current_ec
            if subrate is not None and local.get('subsidence_on'):values['subsidence']=local['subsidence_limit']-max(0,subrate)*local['sub_factor']*t
            for key,v in values.items():
                if crossed[key] is None and v<=0:
                    prev=previous_values.get(key)
                    crossed[key]=0. if t==0 else tprev+(dt*prev/(prev-v) if prev is not None and prev>0 else dt)
            previous_values=values;tprev=t
            if abs(t-round(t))<1e-9:
                curve=curves[int(round(t))];first,status,_=combine()
                if status=='unknown':curve['unknown_area_m2']+=cell['area_m2']
                elif first is not None and first<=t:curve['critical_area_m2']+=cell['area_m2']
                v=sy*max(head-floor,0)*cell['area_m2']/1e6*volume_factor if volume_projectable else None
                if v is None:curve['volume_unknown_area_m2']+=cell['area_m2']
                else:
                    curve['remaining_mcm']+=v
                    if current_ec is None:curve['quality_unknown_mcm']+=v
                    else:
                        limit=local.get('crop_limit') if local.get('use')=='crop' else local.get('quality_limit')
                        if limit is not None:curve['usable_mcm']+=v*lt_fraction(current_ec,limit,ratio)
        first,status,causes=combine()
        reasons=[]
        if status=='unknown':
            if local.get('quantity_on') and not known['quantity']:
                if base_slope is None:reasons.extend(cell.get('management_support_reasons') or ['trend_missing'])
                if local.get('quantity_type','saturated') in ('saturated','storage_loss_pct') and floor is None:reasons.append('bedrock_missing')
                if local.get('quantity_type')=='storage_loss_pct' and sy is None:reasons.append('sy_missing')
                if local.get('climate_on') and not climate['accepted']:reasons.append('climate_not_validated')
            if local.get('quality_on') and not known[local.get('use','crop')]:reasons.append('quality_trend_missing' if quality and local['quality_window']!='manual' and ec_rate is None else 'quality_outside_support' if quality else 'quality_missing')
            if local.get('subsidence_on') and not known['subsidence']:reasons.append('subsidence_period_unavailable' if rate_audit['subsidence'].get('available') is False else 'subsidence_not_vertical' if subaudit.get('component')=='los' else 'subsidence_missing_or_outside_support')
        cause=5 if status=='unknown' else 0 if not causes else 4 if len(causes)>1 else {'quantity':1,'drinking':2,'crop':2,'subsidence':3}[causes[0]]
        cell.update(life_years=first,life_status=status,life_cause=cause,life_causes=causes,
                    life_trend_m_year=base_slope,
                    life_ec_growth_pct_year=ec_rate,life_subsidence_rate_mm_year=subrate,
                    life_volume_projectable=volume_projectable,
                    life_unknown_reasons=sorted(set(reasons)),
                    life_quantity_years=crossed['quantity'] if local.get('quantity_on') else None,
                    life_drinking_years=crossed['drinking'] if local.get('quality_on') else None,
                    life_crop_years=crossed['crop'] if local.get('quality_on') else None,
                    life_subsidence_years=crossed['subsidence'] if local.get('subsidence_on') else None,
                    life_known_limit_upper_bound=min((crossed[k] for k in active if crossed[k] is not None),default=None) if status=='unknown' else None,
                    life_water_year=end_wy+math.ceil(first-1e-9) if first is not None else None,
                    life_quantity_cutoff_msl=cutoff,
                    life_quantity_allowed_drop_m=max(0,current-cutoff) if cutoff is not None else None,
                    life_quantity_initial_storage_mcm=max(current-floor,0)*sy*cell['area_m2']/1e6*volume_factor if floor is not None and sy is not None else None,
                    life_scenario_sy=sy,life_scenario_floor_msl=floor,life_climate_applied=bool(local.get('climate_on') and climate['accepted']))
    unknown=sum(c['area_m2'] for c in cells if c['life_status']=='unknown')
    display_step=25 if s['horizon']>=50 else 10 if s['horizon']>25 else 5 if s['horizon']>=10 else 1
    display_years=sorted({*range(0,s['horizon']+1,display_step),s['horizon']})
    default_bands=list(range(25,s['horizon']+1,25)) if s['horizon']>=50 else [5,10,25]
    bands=sorted(set(float(v) for v in raw.get('bands',default_bands) if 0<float(v)<=s['horizon']))
    if not bands or bands[-1]!=s['horizon']:bands.append(s['horizon'])
    for c in cells:
        c['life_band']=len(bands)+2 if c['life_status']=='unknown' else len(bands)+1 if c['life_status']=='beyond' else 0 if c['life_status']=='already' else next(i+1 for i,b in enumerate(bands) if c['life_years']<=b)
    for curve in curves:
        curve['critical_area_pct']=100*curve['critical_area_m2']/total_area
        curve['unknown_area_pct']=100*curve['unknown_area_m2']/total_area
        curve['volume_unknown_area_pct']=100*curve['volume_unknown_area_m2']/total_area
        if curve['volume_unknown_area_m2']>=total_area*(1-1e-10):
            curve['remaining_mcm']=None;curve['usable_mcm']=None
        elif curve['remaining_mcm']>0 and curve['quality_unknown_mcm']>=curve['remaining_mcm']*(1-1e-10):
            curve['usable_mcm']=None
        curve['water_year']=end_wy+curve['year']
    target=s['area_target_pct']/100*total_area
    events=sorted((c['life_years'],c['area_m2']) for c in cells if c['life_years'] is not None)
    area=0.;target_year=None
    for t,a in events:
        area+=a
        if area>=target:target_year=t;break
    report={'scenario':s,'reference_date':data['dates']['after'],'reference_water_year':end_wy,'aquifer':data['aquifer'],
        'quantity_reference':lifetime_quantity_reference(data,management,s,zones_text) if s.get('quantity_on') else None,
        'unknown_area_pct':100*unknown/total_area,'critical_at_horizon_pct':curves[-1]['critical_area_pct'],
        'area_target_years':target_year,'area_target_water_year':end_wy+math.ceil(target_year-1e-9) if target_year is not None else None,
        'area_target_status':'upper_bound' if target_year is not None and unknown else 'crossing' if target_year is not None else 'unknown' if unknown else 'beyond',
        'climate':climate,'quality_reference_water_year':(quality or {}).get('report',{}).get('quality_water_year'),
        'quality_year_gap':gap,'quality_model':(quality or {}).get('report'),'subsidence_source':subaudit,'input_files':data.get('input_files',{}),'management_settings':management['report']['settings'],
        'base_model':{'dates':data['dates'],'grid':data.get('grid'),'metrics':data['metrics'],
            'pixel_grid':{k:data['plan_maps'].get(k) for k in ('side_m','cell_width_m','cell_height_m','spacing_lon','spacing_lat','grid_cols','grid_rows','metric_basis','reference_latitude')},
            'physical_grid_sha256':hashlib.sha256(json.dumps(data['plan_maps'],sort_keys=True,separators=(',',':')).encode()).hexdigest()},
        'trend_support':{k:management['report'].get(k) for k in ('trend_start_water_year','trend_end_water_year','eligible_wells','well_count','backtest_mae_m','backtest_predictions')},
        'rate_audit':rate_audit,
        'volume_curve_reference':{'fixed_spatial_domain':True,'supported_area_pct':100*sum(c['area_m2'] for c in cells if c['life_volume_projectable'])/total_area,
            'projectable_initial_storage_mcm':curves[0]['remaining_mcm'],'physical_initial_storage_mcm':sum(c['life_quantity_initial_storage_mcm'] or 0 for c in cells),
            'note':'The same cells with floor, Sy and valid future head path are summed at every time including zero; losing spatial coverage must not create an apparent decline.'},
        'spatial_coverage':{'mode':s['spatial_coverage'],'estimator':s['spatial_method'],'method':{'idw':'IDW of observed well trends','spline':'Thin-plate Spline RBF, degree 1; possible overshoot retained','thiessen':'Thiessen / nearest eligible well trend'}[s['spatial_method']]+'; same support mask for all methods, full domain only by explicit selection',
            'spline_overshoot_cells':sum(c['life_spline_overshoot'] for c in cells),
            'neighbors':management['report']['settings'].get('neighbors',8),'power':management['report']['settings'].get('power',2),
            'support_radius_km':management['report'].get('support_radius_km'),
            'area_pct':{key:100*sum(c['area_m2'] for c in cells if c['life_support']==code)/total_area for code,key in enumerate(('within_support','extrapolated','unavailable','manual'))},
            'cells':{key:sum(c['life_support']==code for c in cells) for code,key in enumerate(('within_support','extrapolated','unavailable','manual'))},
            'note':'Spatial extension is conditional estimation, not new observations or reconstruction of dry wells. No extension of missing bedrock, Sy, quality or subsidence. Temporal sensitivity does not quantify spatial extrapolation error.'},
        'bands':bands,'curves':curves,'display_step_years':display_step,'display_years':display_years,
        'integration_step_years':.25,'zones_sha256':hashlib.sha256(zones_text.encode()).hexdigest() if zones_text else None,
        'notes':['Conditional first passage; not groundwater age, pumping permission or exhaustion date.',
                 'All active criteria must be known for composite lifetime, except proven failure at time zero. Unknown may fail earlier than known limits.',
                 'Prescription of head trajectory: Sy changes volume, not prescribed head decline. Physical original floor only.',
                 'EC-only salinity screening; not drinking safety or crop-specific suitability. Unknown depth; geometric-mid-column quality allocation is a scenario.',
                 'Cumulative subsidence / declared duration is an assumed future mean rate; no acceleration or mechanical loss of Sy inferred. Future criterion is additional settlement from model reference date, not past cumulative damage.',
                 'Climate is empirical association conditional on historical abstraction; no causal attribution or direct pumping-to-decline conversion. Unaccepted climate remains unknown, not zero effect.',
                 'Zonal parameters evaluated at clipped cell representative points; no sub-cell zoning. Cells are spatially linked, not independent groundwater reservoirs.',
                 'Observed surviving network only: missing or dried-well heads are not reconstructed. Sensitivity does not cover selection bias caused by real drying.',
                 'Quarterly integration and within-segment linear first crossing; displayed years not precise dates. Area curves and sums use actual clipped areas.'],
        'sources':['https://www.ipcc.ch/report/ar6/wg2/chapter/chapter-4/','https://www.fao.org/4/t0234e/t0234e01.htm','https://www.usgs.gov/centers/land-subsidence-in-california/science/aquifer-compaction-due-groundwater-pumping','https://pro.arcgis.com/en/pro-app/latest/help/analysis/geostatistical-analyst/how-inverse-distance-weighted-interpolation-works.htm']}
    reasons=sorted({r for c in cells for r in c['life_unknown_reasons']})
    report['unknown_diagnostics']={'unknown_cells':sum(c['life_status']=='unknown' for c in cells),'total_cells':len(cells),
        'reason_areas_pct':{r:100*sum(c['area_m2'] for c in cells if r in c['life_unknown_reasons'])/total_area for r in reasons},
        'overlapping_reasons':True,'support_radius_km':management['report'].get('support_radius_km'),
        'network_selection':management['report'].get('network_selection'),'eligible_wells':management['report'].get('eligible_wells'),'well_count':management['report'].get('well_count'),
        'excluded_wells':[{'name':w['name'],'reason':w.get('reason'),'observations':w.get('observations')} for w in management.get('wells',[]) if not w.get('eligible')]}
    report['sources'].extend(['https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html','https://doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/create-thiessen-polygons.html'])
    maps={**deepcopy(data['plan_maps']),'cells':cells}
    result={'report':report,'plan_maps':maps}
    if sensitivity and raw.get('sensitivity_on'):
        scenarios=[]
        for direction in (-1,1):
            variant={**s,'sensitivity_on':False,'_variant':{'slope':'_low' if direction<0 else '_high','floor':-direction*s['sensitivity_floor_m'],'sy':1+direction*s['sensitivity_sy_pct']/100,'ec':-direction*s['sensitivity_ec_pct']}}
            scenarios.append(lifetime_analysis(data,management,quality,variant,climate_text,zones_text,False,source_context))
        for i,c in enumerate(cells):
            values=[r['plan_maps']['cells'][i]['life_years'] for r in scenarios]+[c['life_years']]
            c['life_sensitivity_min']=min((v for v in values if v is not None),default=None)
            c['life_sensitivity_max']=max((v for v in values if v is not None),default=None)
            c['life_sensitivity_open']=any(v is None for v in values)
            c['life_sensitivity_unknown']=any(r['plan_maps']['cells'][i]['life_status']=='unknown' for r in scenarios) or c['life_status']=='unknown'
            c['life_sensitivity_beyond']=any(r['plan_maps']['cells'][i]['life_status']=='beyond' for r in scenarios) or c['life_status']=='beyond'
        summary=[]
        for label,r in zip(('central','faster','slower'),[result,*scenarios]):
            rr=r['report'];summary.append({'variant':label,**{k:rr[k] for k in ('area_target_years','area_target_status','critical_at_horizon_pct','unknown_area_pct')},'remaining_at_horizon_mcm':rr['curves'][-1]['remaining_mcm']})
        report['sensitivity']={'kind':'three parameter combinations; extrema of finite computed crossings only, not confidence interval or probability; unknown combinations may fail earlier, beyond-horizon combinations have no finite upper bound','variants':[r['report']['scenario'] for r in scenarios],'summary':summary}
    return result


def lifetime_tiff(result, field='life_years'):
    """Regular WGS84 grid from existing rectangular mesh; masked NoData, no interpolation."""
    import struct
    cells=result['plan_maps']['cells'];w,s,e,n=result['plan_maps']['extent']
    # Mesh cells originate on a regular longitude/latitude lattice.
    maps=result['plan_maps']
    dx=maps.get('spacing_lon') or maps.get('cell_width_m',maps.get('side_m'))/(111320*math.cos(math.radians((n+s)/2)))
    dy=maps.get('spacing_lat') or maps.get('cell_height_m',maps.get('side_m'))/111320
    from shapely.geometry import shape, Point
    cols=math.ceil((e-w)/dx);rows=math.ceil((n-s)/dy)
    # Source mesh is anchored at west/south. The north edge rounds outward.
    n=s+rows*dy
    values=[-9999.]*(cols*rows)
    for c in cells:
        value=c.get(field)
        if not isinstance(value,(int,float)) or not math.isfinite(value):continue
        geom=shape({'type':'MultiPolygon','coordinates':c['polygons']})
        lo,bot,hi,top=geom.bounds
        for col in range(max(0,int((lo-w)/dx)),min(cols,math.ceil((hi-w)/dx))):
            for row in range(max(0,int((n-top)/dy)),min(rows,math.ceil((n-bot)/dy))):
                if geom.covers(Point(w+(col+.5)*dx,n-(row+.5)*dy)):values[row*cols+col]=float(value)
    desc=json.dumps({'field':field,'scenario':result['report']['scenario'],'pixel_grid':result['report'].get('base_model',{}).get('pixel_grid'),'spatial_coverage':result['report'].get('spatial_coverage'),'support_codes':{'within_support':0,'extrapolated':1,'unavailable':2,'manual':3},'quantity_reference':result['report'].get('quantity_reference'),'reference_water_year':result['report']['reference_water_year'],'unknown':-9999,'bands':result['report']['bands'],'band_codes':{'already':0,'crossing':'1..len(bands), ordered upper bounds in years','beyond':len(result['report']['bands'])+1,'unknown':len(result['report']['bands'])+2},'status':'See companion category TIFF or JSON/GeoJSON for unknown vs beyond horizon; life_years NoData covers both. Support TIFF identifies spatial extrapolation separately.'},ensure_ascii=True).encode()+b'\0'
    specs=[(256,4,1,cols),(257,4,1,rows),(258,3,1,32),(259,3,1,1),(262,3,1,1),(270,2,len(desc),desc),(273,4,1,0),(277,3,1,1),(278,4,1,rows),(279,4,1,cols*rows*4),(284,3,1,1),(339,3,1,3),(33550,12,3,struct.pack('<3d',dx,dy,0)),(33922,12,6,struct.pack('<6d',0,0,0,w,n,0)),(34735,3,16,struct.pack('<16H',1,1,0,3,1024,0,1,2,1025,0,1,1,2048,0,1,4326)),(42113,2,6,b'-9999\0')]
    offset=8+2+12*len(specs)+4;extra=bytearray();entries=[]
    for tag,kind,count,value in specs:
        if isinstance(value,bytes):
            if len(value)<=4:encoded=value.ljust(4,b'\0')
            else:encoded=struct.pack('<I',offset+len(extra));extra.extend(value);extra.extend(b'\0'*(-len(extra)%2))
        else:encoded=struct.pack('<I',value)
        entries.append((tag,kind,count,encoded))
    pixel_offset=offset+len(extra)
    header=b'II'+struct.pack('<HIH',42,8,len(entries))
    header+=b''.join(struct.pack('<HHI',tag,kind,count)+(struct.pack('<I',pixel_offset) if tag==273 else encoded) for tag,kind,count,encoded in entries)+struct.pack('<I',0)
    return header+extra+struct.pack('<'+str(len(values))+'f',*values)

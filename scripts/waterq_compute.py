"""Water-quality audit and estimation. Scientific operations run in browser Pyodide."""
import csv
import io
import json
import math
from collections import Counter, defaultdict


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):
        return None


def audit_quality(text, aquifers):
    from pyproj import Transformer
    from shapely.geometry import shape, Point
    rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
    required={'utm_x','utm_y','zone','ec','سال','ماه'}
    if not rows or not required.issubset({k.strip() for k in rows[0] if k}):
        raise ValueError('CSV کیفیت باید مطابق WaterQ.csv شامل utm_x, utm_y, zone, ec، سال و ماه باشد.')
    raw_fields=list(rows[0])
    normalized=[]
    rejected=Counter()
    transforms={}
    for n,row in enumerate(rows,2):
        row={k.strip():str(v or '').strip() for k,v in row.items() if k}
        x,y,ec,zone=[number(row.get(k)) for k in ('utm_x','utm_y','ec','zone')]
        year,month=[number(row.get(k)) for k in ('سال','ماه')]
        if None in (x,y,ec,zone,year,month) or ec<=0 or not 1<=month<=12 or not 1<=zone<=60:
            rejected['invalid_required_values']+=1
            continue
        zone=int(zone)
        if zone not in transforms:
            transforms[zone]=Transformer.from_crs(32600+zone,4326,always_xy=True)
        lon,lat=transforms[zone].transform(x,y)
        item={'line':n,'lon':lon,'lat':lat,'x':x,'y':y,'zone':zone,'ec':ec,
              'year':int(year),'month':int(month),'water_year':int(year)-(month<7),
              'name':row.get('آبادی',''),'source_type':row.get('نوع عمق',''),
              'study_area':row.get('محدوده','')}
        item.update({k:number(row.get(k)) for k in ('sar','tds','ca','mg','na','k','cl','so4','hco3','co3','ph','th')})
        normalized.append(item)
    areas=[]
    for feature in json.loads(aquifers)['features']:
        geometry=shape(feature['geometry'])
        values=[r for r in normalized if geometry.covers(Point(r['lon'],r['lat']))]
        if not values:
            continue
        sites={(r['zone'],r['x'],r['y']) for r in values}
        by_year=Counter(r['water_year'] for r in values)
        newest=max(by_year)
        ratios=[r['tds']/r['ec'] for r in values if r['tds'] is not None]
        import numpy as np
        areas.append({'properties':feature['properties'],'records':len(values),'sites':len(sites),
                      'water_year_counts':dict(sorted(by_year.items())),
                      'source_types':dict(Counter(r['source_type'] for r in values)),
                      'ec_quantiles':dict(zip(['min','q10','median','q90','max'],np.quantile([r['ec'] for r in values],[0,.1,.5,.9,1]).tolist())),
                      'tds_ec_ratio_range':[min(ratios),max(ratios)] if ratios else None,
                      'sar_available':sum(r['sar'] is not None for r in values),
                      'newest_year_site_count':len({(r['zone'],r['x'],r['y']) for r in values if r['water_year']==newest})})
    return {'raw_rows':len(rows),'columns':raw_fields,'accepted_rows':len(normalized),'rejected':dict(rejected),
            'utm_assumption':'WGS84 northern hemisphere, EPSG:32600+zone; datum must be confirmed',
            'sampling_date_rule':'سال/ماه/روز; laboratory dates retained separately, not substituted',
            'aquifers':areas,'records':normalized}


class PublicCovariates:
    """Local sampling of public raster/lithology layers; quality never leaves browser."""
    def __init__(self, raster_bytes=b'', geology_text='', centre_lon=60, allowed_fields=None):
        import numpy as np
        from scipy.spatial import cKDTree
        from pyproj import Transformer
        from shapely.geometry import shape, box
        from shapely import make_valid
        from shapely.ops import transform, unary_union
        zone=max(1,min(60,int((centre_lon+180)/6)+1))
        self.project=Transformer.from_crs(4326,32600+zone,always_xy=True).transform
        self.names=[];self.tree=None;self.rocks={};self.repaired=0
        if raster_bytes:
            array=np.load(io.BytesIO(raster_bytes),allow_pickle=False).ravel()
            self.names=[n for n in array.dtype.names if n not in ('longitude','latitude')]
            if allowed_fields is not None:self.names=[n for n in self.names if n in allowed_fields]
            lon,lat=array['longitude'],array['latitude']
            good=(lon>-180)&(lat>-90)&(lon<180)&(lat<90)
            self.xy=np.array(self.project(lon[good],lat[good])).T
            self.values=np.array([array[n][good] for n in self.names]).T.astype(float)
            self.values[self.values < -9000]=np.nan
            self.tree=cKDTree(self.xy)
            self.bounds=(lon[good].min(),lat[good].min(),lon[good].max(),lat[good].max())
        if geology_text:
            groups=defaultdict(list)
            for feature in json.loads(geology_text).get('features',[]):
                g=shape(feature['geometry'])
                if not g.is_valid:
                    g=make_valid(g);self.repaired+=1
                if self.tree is not None:
                    w,s,e,n=self.bounds;g=g.intersection(box(w,s,e,n))
                if not g.is_empty:
                    groups[feature['properties'].get('xx','unknown')].append(transform(self.project,g))
            self.rocks={k:unary_union(v) for k,v in sorted(groups.items())}

    def sample(self, ll):
        import numpy as np
        from shapely.geometry import Point
        xy=np.array(self.project(np.array(ll)[:,0],np.array(ll)[:,1])).T
        raster=np.empty((len(ll),0))
        if self.tree is not None:
            distance,index=self.tree.query(xy)
            raster=self.values[index].copy()
            raster[distance>2500,:]=np.nan
        geology=np.array([[math.log1p(g.distance(Point(p))/1000) for g in self.rocks.values()] for p in xy])
        if not self.rocks:
            geology=np.empty((len(ll),0))
        return xy,raster,geology


def idw_predict(xy, y, target):
    import numpy as np
    from scipy.spatial import cKDTree
    distance,index=cKDTree(xy).query(target,k=min(8,len(y)))
    if distance.ndim==1:
        distance,index=distance[:,None],index[:,None]
    weights=1/np.maximum(distance,0.01)**2
    return np.sum(weights*y[index],axis=1)/weights.sum(axis=1)


def regression_residual(train_xy,y,test_xy,train_x,test_x):
    import numpy as np
    # All centring/imputation is fitted on the training fold, never the test fold.
    med=np.array([np.nanmedian(c) if np.any(np.isfinite(c)) else 0 for c in train_x.T])
    tx=np.where(np.isfinite(train_x),train_x,med)
    vx=np.where(np.isfinite(test_x),test_x,med)
    mean,scale=tx.mean(axis=0),tx.std(axis=0)
    scale=np.maximum(scale,1e-8)
    tx=np.column_stack([np.ones(len(tx)),(tx-mean)/scale])
    vx=np.column_stack([np.ones(len(vx)),(vx-mean)/scale])
    penalty=np.eye(tx.shape[1])*10;penalty[0,0]=0
    beta=np.linalg.solve(tx.T@tx+penalty,tx.T@y)
    return vx@beta+idw_predict(train_xy,y-tx@beta,test_xy)


def fraction_below(ec, threshold, ratio=1):
    """Depth scenario: EC(s)=EC_reference*ratio**(s-.5), 0<=s<=1.

    Reference EC is provisionally the geometric mid-depth value. Pumped samples
    do NOT measure this anchor; it is an explicit, uncalibrated volume assumption.
    """
    if ec<=0 or threshold<=0 or ratio<=0:
        raise ValueError('EC، آستانه و نسبت عمقی باید مثبت باشند.')
    if math.isclose(ratio,1,rel_tol=1e-12):
        return float(ec<=threshold)
    crossing=max(0,min(1,.5+math.log(threshold/ec)/math.log(ratio)))
    return crossing if ratio>1 else 1-crossing


def irrigation_lower_ec(sar):
    """FAO severe-infiltration boundary (ECw in uS/cm); >40 SAR outside table."""
    if sar is None or sar<0 or sar>40:
        return None
    for upper,lower in ((3,200),(6,300),(12,500),(20,1300),(40,2900)):
        if sar<=upper:return lower


def estimate_quality(analysis, records, raster_bytes=b'', geology_text='', options=None):
    import numpy as np
    from pyproj import Transformer
    from scipy.spatial import cKDTree, ConvexHull
    from shapely.geometry import Polygon, Point
    from shapely.ops import unary_union
    options=options or {}
    if not analysis.get('pixel_water'):
        raise ValueError('برای برآورد حجم کیفی ابتدا کف معتبر و Sy را وارد کنید.')
    shape=unary_union([Polygon(p[0],p[1:]) for p in analysis['display_grid']['polygons']])
    local=[r for r in records if shape.covers(Point(r['lon'],r['lat']))]
    if not local:
        raise ValueError('داخل مرز آبخوان انتخابی، دادهٔ کیفیت موجود نیست.')
    latest=max(r['water_year'] for r in local)
    volume_year=analysis['dates']['after_water_year']
    end=int(options.get('water_year',min(latest,volume_year)))
    if end>volume_year:raise ValueError('دورهٔ کیفیت نباید پس از تاریخ حجم مورد بررسی باشد.')
    window=int(options.get('window',3))
    if not 1<=window<=10:raise ValueError('پنجرهٔ داده باید بین ۱ تا ۱۰ سال آبی باشد.')
    recent=[r for r in local if end-window+1<=r['water_year']<=end]
    by_site=defaultdict(list)
    # 100m coordinate bins only resolve rounding/jitter; spatial CV holds out 10km blocks.
    for r in recent:by_site[(r['zone'],round(r['x']/100),round(r['y']/100))].append(r)
    sites=[]
    for group in by_site.values():
        last=max(r['year']*12+r['month'] for r in group)
        values=[r for r in group if r['year']*12+r['month']==last]
        site={k:float(np.mean([r[k] for r in values])) for k in ('lon','lat')}
        for k in ('ec','sar','cl'):
            valid=[r[k] for r in values if r[k] is not None and r[k]>=0]
            site[k]=float(np.median(valid)) if valid else None
        site.update({'year':values[0]['year'],'month':values[0]['month'],'name':values[0]['name'],'source_type':values[0]['source_type']})
        sites.append(site)
    if len(sites)<15:raise ValueError('برای اعتبارسنجی مکانی، دست‌کم ۱۵ موقعیت کیفیت در پنجرهٔ انتخابی لازم است.')
    ll=np.array([[r['lon'],r['lat']] for r in sites])
    if np.linalg.matrix_rank(ll-ll.mean(axis=0))<2:
        raise ValueError('موقعیت‌های کیفیت هم‌خط هستند؛ پوشش دوبعدی کافی نیست.')
    source_metadata=options.get('source_metadata',{})
    allowed_fields=(['elevation','slope'] if end<source_metadata.get('water_year_end',end) else None)
    cov=PublicCovariates(raster_bytes,geology_text,float(ll[:,0].mean()),allowed_fields)
    xy,raster,rocks=cov.sample(ll)
    raw_cells=analysis['plan_maps']['cells']
    cell_ll=np.array([[c['lon'],c['lat']] for c in raw_cells])
    cell_xy,cell_raster,cell_rocks=cov.sample(cell_ll)
    y=np.log([r['ec'] for r in sites])
    base_x=xy/10000
    sets={'idw':(None,None),'trend_idw':(base_x,cell_xy/10000)}
    if raster.shape[1]:sets['gee_idw']=(np.column_stack([base_x,raster]),np.column_stack([cell_xy/10000,cell_raster]))
    if rocks.shape[1]:sets['geology_gee_idw']=(np.column_stack([base_x,raster,rocks]),np.column_stack([cell_xy/10000,cell_raster,cell_rocks]))
    blocks=np.floor(xy/10000).astype(int)
    fold=(blocks[:,0]*73856093+blocks[:,1]*19349663)%5
    oof={k:np.full(len(y),np.nan) for k in sets}
    test_distances=[]
    for f in np.unique(fold):
        train,test=fold!=f,fold==f
        if train.sum()<8:raise ValueError('پراکندگی نقاط برای اعتبارسنجی بلوکی کافی نیست.')
        test_distances.extend(cKDTree(xy[train]).query(xy[test])[0].tolist())
        for key,(x,_) in sets.items():
            oof[key][test]=(idw_predict(xy[train],y[train],xy[test]) if x is None else
                            regression_residual(xy[train],y[train],xy[test],x[train],x[test]))
    scores={k:{'rmse_log':float(np.sqrt(np.mean((y-p)**2))),
               'mae_ec':float(np.mean(np.abs(np.exp(y)-np.exp(np.clip(p,-20,20))))),
               'rmse_ec':float(np.sqrt(np.mean((np.exp(y)-np.exp(np.clip(p,-20,20)))**2)))} for k,p in oof.items()}
    chosen=min(scores,key=lambda k:scores[k]['rmse_log'])
    x,target=sets[chosen]
    prediction=idw_predict(xy,y,cell_xy) if x is None else regression_residual(xy,y,cell_xy,x,target)
    residual=y-oof[chosen]
    error_low,error_high=np.quantile(residual,[.1,.9])
    radius=float(np.quantile(test_distances,.9))
    hull=Polygon(ll[ConvexHull(ll).vertices])
    nearest=cKDTree(xy).query(cell_xy)[0]
    supported=[hull.covers(Point(p)) and d<=radius for p,d in zip(cell_ll,nearest)]
    sar_values=np.array([r['sar'] if r['sar'] is not None else np.nan for r in sites])
    valid_sar=np.isfinite(sar_values)&(sar_values>=0)
    sar=(np.expm1(idw_predict(xy[valid_sar],np.log1p(sar_values[valid_sar]),cell_xy)) if valid_sar.sum()>=3 else np.full(len(raw_cells),np.nan))
    drinking=float(options.get('drinking_ec',1500))
    irrigation=float(options.get('irrigation_ec',3000))
    ratio=float(options.get('depth_ratio',1))
    if not all(math.isfinite(v) and v>0 for v in (drinking,irrigation,ratio)):
        raise ValueError('آستانه‌ها و نسبت EC عمقی باید مثبت و متناهی باشند.')
    total=float(analysis['metrics']['drainable_after_mcm'])
    pixel_total=sum(c['remaining_mcm'] for c in raw_cells)
    multiplier=total/pixel_total if pixel_total>0 else 0
    cells=[]
    totals={k:0. for k in ('drinking','irrigation','unknown','irrigation_unknown','drinking_low','drinking_high','irrigation_low','irrigation_high')}
    scenarios={str(r):{'drinking_mcm':0.,'irrigation_mcm':0.} for r in (.5,1,2,4)}
    for index,original in enumerate(raw_cells):
        cell=original.copy();v=cell['remaining_mcm']*multiplier
        ec=float(math.exp(max(-20,min(20,prediction[index]))))
        lower=irrigation_lower_ec(float(sar[index])) if np.isfinite(sar[index]) else None
        cell.update({'quality_supported':bool(supported[index]),'quality_nearest_m':float(nearest[index]),'quality_volume_mcm':v,
                     'quality_ec':ec if supported[index] else None,'quality_sar':float(sar[index]) if np.isfinite(sar[index]) and supported[index] else None})
        if not supported[index]:
            totals['unknown']+=v;totals['irrigation_unknown']+=v
            cell.update({'quality_usable_pct':None,'quality_drinking_pct':None,'quality_zone':'outside_validated_support'})
        else:
            def fractions(ec_value,r):
                drink=fraction_below(ec_value,drinking,r)
                crop=(max(0,fraction_below(ec_value,irrigation,r)-fraction_below(ec_value,math.nextafter(lower,-math.inf),r)) if lower is not None else None)
                return drink,crop
            drink,crop=fractions(ec,ratio)
            outcomes=[fractions(ec*math.exp(q),ratio) for q in np.linspace(error_low,error_high,9)]
            totals['drinking']+=v*drink
            totals['drinking_low']+=v*min(a for a,b in outcomes)
            totals['drinking_high']+=v*max(a for a,b in outcomes)
            if crop is None:totals['irrigation_unknown']+=v
            else:
                totals['irrigation']+=v*crop
                totals['irrigation_low']+=v*min(b for a,b in outcomes)
                totals['irrigation_high']+=v*max(b for a,b in outcomes)
            for r,values in scenarios.items():
                a,b=fractions(ec,float(r));values['drinking_mcm']+=v*a;values['irrigation_mcm']+=v*(b or 0)
            cell.update({'quality_drinking_pct':100*drink,'quality_usable_pct':100*crop if crop is not None else None,
                         'quality_zone':'sar_outside_guideline' if lower is None else 'severe_salinity' if ec>irrigation else 'infiltration_constraint' if ec<lower else 'moderate_salinity' if ec>700 else 'low_salinity',
                         'quality_ec_low':ec*math.exp(error_low),'quality_ec_high':ec*math.exp(error_high)})
        cells.append(cell)
        cell['quality_zone_code']={'low_salinity':0,'moderate_salinity':1,'severe_salinity':2,'infiltration_constraint':3,'outside_validated_support':4,'sar_outside_guideline':4}[cell['quality_zone']]
    totals['drinking_excluded']=max(0,total-totals['unknown']-totals['drinking'])
    totals['irrigation_excluded']=max(0,total-totals['irrigation_unknown']-totals['irrigation'])
    fields={}
    for key in ('quality_ec','quality_sar','quality_usable_pct','quality_drinking_pct','quality_zone_code'):
        values=[c[key] for c in cells if c.get(key) is not None]
        if values:fields[key]={'min':min(values),'max':max(values),'contours':[]}
    report={'aquifer':analysis['aquifer'],'volume_dates':analysis['dates'],'quality_water_year':end,'window_years':window,
            'volume_model':{'sy_mode':analysis['metrics']['sy_mode'],'sy':analysis['metrics']['sy'],
                            'sy_min':analysis['metrics']['sy_min'],'sy_max':analysis['metrics']['sy_max'],
                            'bedrock_source':analysis['grid']['bedrock_source'],'common_wells':analysis['wells']['common'],
                            'input_files':options.get('volume_input_files',{}),
                            'allocation':'Pixel storage weights normalized to analytical 38x38 total; Sy fixed with depth within a column'},
            'quality_input_file':options.get('quality_input_file','WaterQ.csv'),
            'newest_available_quality_water_year':latest,'quality_volume_year_gap':analysis['dates']['after_water_year']-end,
            'records_in_window':len(recent),'sites':len(sites),'thresholds':{'drinking_ec_uScm':drinking,'irrigation_ec_uScm':irrigation},
            'vertical_model':{'bottom_top_ec_ratio':ratio,'reference':'geometric_mid_depth_proxy','calibrated_from_depth_samples':False},
            'total_remaining_mcm':total,'volumes_mcm':totals,'depth_sensitivity':scenarios,
            'validation':{'method':str(len(np.unique(fold)))+' folds of 10km spatial blocks; all repeated site observations aggregated before split','fold_count':int(len(np.unique(fold))),'scores':scores,'selected':chosen,'residual_log_q10_q90':[float(error_low),float(error_high)],'support_radius_m':radius,'note':'Model-selection CV and EC sensitivity, not an independent 95% CI or validation of depth assumptions'},
            'covariates':{'raster_fields':cov.names,'lithology_codes':list(cov.rocks),'invalid_public_geology_geometries_repaired':cov.repaired,'geology_repair':'Shapely make_valid before clipping; original source retained unchanged'},
            'limitations':['EC-only drinking salinity screen; not potability certification','Agriculture: EC ceiling plus avoidance of FAO severe EC/SAR infiltration restriction; not crop-specific yield or full water suitability','Vertical allocation is a scenario; surface imagery does not measure deep EC','Volumes are potential drainable storage, not sustainable abstraction','Outside convex hull or validated-distance support remains unknown; unknown is never assigned fresh water','Depth-scenario and EC-error ranges are sensitivity ranges, not statistical confidence intervals'],
            'public_source_metadata':source_metadata,
            'units_assumed':{'ec':'uS/cm, treated as EC25; source temperature correction not documented','utm':'WGS84 north; original datum not documented'}}
    return {'report':report,'sites':sites,'plan_maps':{'cells':cells,'fields':fields,'extent':analysis['plan_maps']['extent'],
                'side_m':analysis['plan_maps']['side_m'],'polygons':analysis['plan_maps']['polygons'],
                'percentage_reference':'quality_compatible_fraction_of_current_saturated_column'}}


def quality_archive(result,tiff_writer):
    """Export all scientific layers in the browser, including explicit unknown zones."""
    import numpy as np
    import zipfile
    import base64
    report=result['report'];maps=result['plan_maps'];cells=maps['cells']
    fields=sorted({k for c in cells for k in c if k!='polygons'})
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
    writer.writerows({k:c.get(k) for k in fields} for c in cells)
    geojson={'type':'FeatureCollection','metadata':report,'features':[{'type':'Feature','properties':{k:v for k,v in c.items() if k!='polygons'},'geometry':{'type':'MultiPolygon','coordinates':c['polygons']}} for c in cells]}
    w,s,e,n=maps['extent'];side=maps['side_m']
    dx=side/(111320*math.cos(math.radians((s+n)/2)));dy=side/111320
    cols,rows=math.ceil((e-w)/dx),math.ceil((n-s)/dy)
    target=io.BytesIO()
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('METHODS.fa.md',quality_methods_report(result))
        archive.writestr('WATERQ_ESTIMATE.json',json.dumps(report,ensure_ascii=False,indent=2))
        archive.writestr('WATERQ_GRID.csv','\ufeff'+stream.getvalue())
        archive.writestr('WATERQ_ZONES.geojson',json.dumps(geojson,ensure_ascii=False))
        for key in ('quality_ec','quality_sar','quality_drinking_pct','quality_usable_pct','quality_zone'):
            image=np.full((rows,cols),-9999,dtype=np.float32)
            for cell in cells:
                value=cell.get(key)
                if key=='quality_zone':value=cell['quality_zone_code']
                if value is not None:image[rows-1-cell['row'],cell['column']]=value
            description={'variable':key,'report':report,'boundary_pixels':'All intersecting squares retained; use accompanying clipped GeoJSON for exact boundary','zone_codes':{'0':'low salinity','1':'moderate salinity','2':'severe salinity','3':'infiltration constraint','4':'unknown support'}}
            archive.writestr(key+'.tif',tiff_writer(image,w,s+rows*dy,dx,dy,description))
    return base64.b64encode(target.getvalue()).decode('ascii')


def quality_methods_report(result):
    """Persian methods and numerical snapshot, generated alongside layers in Pyodide."""
    r=result['report'];v=r['volumes_mcm'];validation=r['validation'];model=r['volume_model']
    rows='\n'.join(f"| {name} | {s['rmse_log']:.4f} | {s['mae_ec']:.0f} | {s['rmse_ec']:.0f} |" for name,s in validation['scores'].items())
    depth='\n'.join(f"| {ratio} | {s['drinking_mcm']:.0f} | {s['irrigation_mcm']:.0f} |" for ratio,s in r['depth_sensitivity'].items())
    return f'''# برآورد حجم با محدودیت شوری آبخوان {r['aquifer']['name']}

این سند همراه اجرای واقعی مدل در مرورگر تولید شده است. عددها خروجی سناریو هستند؛ دادهٔ اندازه‌گیری‌شده در همهٔ اعماق یا حجم برداشت پایدار نیستند.

## داده و دوره

کیفیت: سال آبی {r['quality_water_year']} و پنجرهٔ {r['window_years']} ساله، شامل {r['records_in_window']} رکورد و {r['sites']} موقعیت پس از تجمیع. تاریخ حجم: {r['volume_dates']['after']}، پایان WY {r['volume_dates']['after_water_year']}. فاصلهٔ کیفیت و حجم {r['quality_volume_year_gap']} سال آبی است؛ کیفیت در این فاصله ثابت فرض می‌شود. سال آبی از مهر تا شهریور و با سال آغاز نام‌گذاری می‌شود. تاریخ نمونه‌برداری از ستون‌های سال/ماه استفاده می‌شود؛ تاریخ آزمایش جای آن قرار نمی‌گیرد. دادهٔ کیفیت پس از تاریخ حجم در مدل استفاده نمی‌شود.

مختصات UTM به WGS84 شمالی تفسیر شده و از zone هر ردیف تبدیل می‌شود. مبنای اصلی نقشه‌برداری هنوز باید از شناسنامهٔ سازمان تأیید شود. EC بر حسب µS/cm و معادل EC در ۲۵ درجه فرض شده؛ وجود تصحیح دما در فایل مستند نیست. ستون نوع عمق، دستهٔ چاه عمیق/نیمه‌عمیق است و عمق عددی نمونه نیست. TDS فایل اصلی از EC ضربدر ۰٫۶۳ ساخته شده و شاهد مستقل اعتبار مدل محسوب نمی‌شود.

آخرین مشاهدهٔ هر موقعیت در پنجره نگه داشته می‌شود؛ چند مشاهدهٔ همان ماه با میانه تجمیع می‌شوند. شبکهٔ ۱۰۰ متری مختصات برای تجمیع تفاوت‌های گردکردن به کار می‌رود و ممکن است چاه‌های بسیار نزدیک را ادغام کند. دادهٔ اصلی تغییر نمی‌کند.

## نتیجهٔ سناریوی جاری

Sy: {model['sy_mode']}، دامنهٔ شبکه {model['sy_min']:.5f} تا {model['sy_max']:.5f}. منبع کف: {model['bedrock_source']}. دو سطح آب از {model['common_wells']} پیزومتر مشترک برآورد شده‌اند. جزئیات فرض‌های کف و Sy در گزارش هیدروژئولوژی اصلی و شناسنامهٔ ورودی‌ها آمده است.

حد شوری شرب: {r['thresholds']['drinking_ec_uScm']:.0f} µS/cm، یک آستانهٔ سناریویی قابل تغییر و بدون ادعای حد قانونی یا تأیید سلامت. حد شوری کشاورزی: {r['thresholds']['irrigation_ec_uScm']:.0f} µS/cm، همراه حذف محدودیت شدید نفوذ EC/SAR در دامنهٔ جدول FAO. SAR بیش از ۴۰ یا فاقد مقدار، خارج دامنهٔ همین قاعده است و برای کشاورزی نامشخص می‌ماند. محدودیت محصول، خاک، آبشویی، بور، کلر، پاتوژن، نیترات و آرسنیک در این حجم منظور نشده‌اند. حجم‌های دو مصرف همپوشان هستند و نباید با هم جمع شوند.

همهٔ حجم‌ها در جدول، میلیون مترمکعب‌اند.

| معیار | مقدار |
|---|---:|
| کل برآورد قابل زهکشی | {r['total_remaining_mcm']:.0f} |
| زیر حد انتخابی شوری شرب | {v['drinking']:.0f} |
| خارج حد انتخابی شوری شرب، در بخش دارای پوشش | {v['drinking_excluded']:.0f} |
| فاقد پوشش کیفیت برای EC | {v['unknown']:.0f} |
| بدون محدودیت شدید EC/SAR کشاورزی | {v['irrigation']:.0f} |
| خارج قاعدهٔ انتخابی EC/SAR، در بخش دارای پوشش | {v['irrigation_excluded']:.0f} |
| نامشخص برای قاعدهٔ کشاورزی | {v['irrigation_unknown']:.0f} |
| حساسیت خطای EC برای شوری شرب | {v['drinking_low']:.0f} تا {v['drinking_high']:.0f} |
| حساسیت خطای EC برای EC/SAR کشاورزی | {v['irrigation_low']:.0f} تا {v['irrigation_high']:.0f} |

## داده‌های کمکی واقعی و نقش آن‌ها

از GEE، ارتفاع و شیب SRTM، NDVI، NDWI، BSI و نسبت SWIR در Sentinel-2 و نمونه‌های پوشش زمین WorldCover دریافت شده‌اند. این‌ها شاخص‌های توضیحی سطح زمین هستند، نه اندازه‌گیری EC عمقی. بازهٔ منبع در MASHHAD_WATERQ_SOURCE_METADATA.json ثبت شده است. برای Sentinel-2 سه صحنهٔ کم‌ابرتر از هر کاشی MGRS در پنجره انتخاب شده؛ ماسک SCL کلاس‌های فاقد داده، اشباع، سایه ابر، ابر، سیروس و برف را حذف می‌کند. بازتاب ابتدا در ۲۵۰ متر نمونه‌برداری می‌شود، سپس شاخص‌ها و میانه و تجمیع حدود یک کیلومتر ساخته می‌شوند. این محصول میانگین سالانهٔ پوشش گیاهی یا نقشهٔ شوری خاک نیست. WorldCover مربوط به ۲۰۲۱ است؛ سهم پوشش‌ها تقریبِ نمونه‌برداری ۲۵۰ متری در سلول یک کیلومتری است، نه جمع دقیق تمام پیکسل‌های ۱۰ متری. متغیرهای طیفی و پوشش زمین، برای دوره‌های کیفیت پیش از انتهای بستهٔ مرجع، کنار گذاشته می‌شوند تا آینده وارد مدل تاریخی نشود.

زمین‌شناسی GLiM از سرویس برداری با مشخصات و انتساب محفوظ دریافت شده است. لایه سطحی/منطقه‌ای است؛ نقشهٔ ۱:۱۰۰هزار مشهد، لاگ حفاری یا سنگ‌شناسی عمقی نیست. ویژگی‌های مدل، لگاریتم فاصله تا کلاس‌های سنگ‌شناسی منطقه‌اند؛ این ویژگی‌ها انتقال یا مسیر جریان زیرزمینی را حل نمی‌کنند. {r['covariates']['invalid_public_geology_geometries_repaired']} هندسهٔ نامعتبر عمومی پیش از برش با make_valid اصلاح شده‌اند؛ نسخهٔ خام و شناسنامه باقی مانده‌اند. وجود تبخیری‌ها یا رس، به‌تنهایی اندازهٔ EC آب منفذی را تعیین نمی‌کند.

## مدل و اعتبارسنجی

EC با تبدیل لگاریتمی مدل می‌شود تا مقدار منفی تولید نشود. نامزدها: IDW با توان ۲ و حداکثر هشت همسایه؛ روند مختصات با IDW باقیمانده؛ رگرسیون Ridge با ویژگی‌های GEE و باقیماندهٔ مکانی؛ و همان مدل با فاصلهٔ سنگ‌شناسی. مقدار جریمهٔ Ridge برابر ۱۰ است و ضریب برداشت یا پارامتر کیفیت اندازه‌گیری‌شده نیست. مرکزدهی، مقیاس‌بندی و جایگزینی متغیر کمکیِ مفقود فقط روی بخش آموزش هر گروه انجام می‌شود. متغیرِ کمکیِ کاملاً مفقود، در مدل اثری ندارد.

اعتبارسنجی {validation['fold_count']} گروه از بلوک‌های مکانی ۱۰ کیلومتری دارد؛ نمونه‌های یک موقعیت پیش از تفکیک گروه‌ها تجمیع می‌شوند. مدل بر اساس کمترین RMSE لگاریتم EC انتخاب می‌شود: **{validation['selected']}**. مدل‌گزینی و گزارش خطا با همین داده انجام شده؛ این آزمون مستقل نهایی نیست. برتری بر اساس معیار لگاریتمی است و ممکن است رتبه‌بندی RMSE خام متفاوت باشد.

| مدل | RMSE لگاریتم EC | MAE (µS/cm) | RMSE (µS/cm) |
|---|---:|---:|---:|
{rows}

حدود خطای لگاریتمی از صدک‌های ۱۰ و ۹۰ باقیمانده‌های خارج گروه گرفته می‌شوند. تمام پیکسل‌ها با همین خطاها جابه‌جا می‌شوند؛ خطای پیکسل‌ها مستقل فرض و با جذر تعداد سلول‌ها کوچک نمی‌شود. بازهٔ حجم فقط حساسیت به این خطای EC است؛ عدم‌قطعیت کف، Sy، SAR، عمق، تاریخ، مرز، استخراج و انتخاب مدل را پوشش نمی‌دهد و فاصلهٔ اطمینان ۹۵٪ نیست.

پیش‌بینی بیرون پوش محدب نقاط کیفیت یا دورتر از {validation['support_radius_m']/1000:.2f} کیلومتر از نزدیک‌ترین نمونه، برای حجم و زون‌بندی نامشخص می‌ماند. شعاع، صدک ۹۰ فاصلهٔ نزدیک‌ترین آموزش تا نقاط آزمون بلوکی است؛ حد ایمنی فیزیکی یا شعاع اندازه‌گیری نیست.

## فرض عمقی و تبدیل کیفیت به حجم

مدل مکانی، EC آب نمونه‌برداری‌شده از چاه را تخمین می‌زند. برای تبدیل آن به سهمی از ستون اشباع، از سناریوی زیر استفاده می‌شود:

```text
s = normalized depth below the water table, 0 <= s <= 1
EC(s) = EC_reference * R ** (s - 0.5)
R = EC_at_bottom / EC_at_top
V_compatible = sum(V_pixel * compatible_depth_fraction)
```

مقدار R جاری {r['vertical_model']['bottom_top_ec_ratio']:.3f} است. R=1 یعنی کیفیت یکنواخت در عمق؛ در سایر حالات EC نمونه به‌صورت فرضی نمایندهٔ میانهٔ هندسی ستون است. این نقطهٔ مرجع از نمونهٔ عمقی یا دبی هر لایه اندازه‌گیری نشده است. نسبت معکوس ۰٫۵ و ۲، با همین مرجع و Sy ثابت با عمق، می‌تواند حجم یکسان ولی ترتیب عمقی متفاوت بسازد. چنین برابری، تأیید همسان‌بودن آرایش واقعی لایه‌ها نیست.

SAR و Sy در عمق هر ستون ثابت فرض می‌شوند. کسری از ستون که EC زیر آستانه است، به‌صورت تحلیلی محاسبه می‌شود. برای کشاورزی، حد پایین EC ناشی از محدودیت شدید نفوذ SAR نیز اعمال می‌شود. وزن حجمِ پیکسل‌های نمایشی، متناسب با ذخیرهٔ خود آن‌ها نرمال و با حجم اصلی شبکهٔ ۳۸×۳۸ هم‌جمع می‌شود؛ این بازتوزیع اطلاعات دقیق‌تر مکانی ایجاد نمی‌کند.

| نسبت عمقی R | زیر حد شوری شرب | EC/SAR کشاورزی |
|---|---:|---:|
{depth}

این چهار ردیف، سناریوهای حساسیت‌اند و توزیع احتمال کالیبره‌شدهٔ گرادیان عمقی نیستند. پژوهش‌های ارتباط افت سطح آب و افزایش EC، بدون اطلاعات عمقی نمونه، گرادیان قائم EC را تعیین نمی‌کنند؛ ضریب تجربی افزایش EC به ازای افت، به‌عنوان شیب قائم وارد مدل نشده است. ساخت مدل انتقال شوری و پیش‌بینی جابه‌جایی آب شور در حین پمپاژ، به اطلاعات جریان، غلظت، لایه‌بندی، برداشت و مرزها نیاز دارد و این ماژول آن مدل نیست.

## فایل‌ها و بازتولید

- WATERQ_ESTIMATE.json: مقدارها، دوره‌ها، فرض‌ها، امتیاز مدل‌ها و مشخصات منابع.
- WATERQ_GRID.csv: مقدار و سهم هر پیکسل؛ ستون quality_supported وضعیت پوشش را نگه می‌دارد.
- WATERQ_ZONES.geojson: پیکسل‌های بریده‌شده با پولیگون، شامل حفره‌ها و همهٔ متغیرها.
- quality_ec.tif و quality_sar.tif: میدان‌های کیفیت، EPSG:4326، Float32.
- quality_drinking_pct.tif و quality_usable_pct.tif: سهم سناریویی کیفیت، بر حسب درصد.
- quality_zone.tif: کدهای ۰ کم‌شور، ۱ شوری متوسط، ۲ بالاتر از حد EC، ۳ محدودیت نفوذ و ۴ نامشخص.

NoData رسترها -۹۹۹۹ است. سلول‌های مرزی به‌صورت all-touched نگه داشته می‌شوند؛ برای مرز دقیق، از GeoJSON بریده‌شده استفاده کنید. EC و سهم‌های نامشخص، صفر نیستند. دادهٔ خصوصی WaterQ به GEE یا سرور تحلیل ارسال نشده است. تنها آماده‌سازیِ صریح منابع عمومیِ ماهواره‌ای در GEE انجام شده؛ برازش، اعتبارسنجی، حجم و تولید این بسته در Pyodide مرورگر اجرا شده‌اند.

## منابع

1. [FAO، Water quality for agriculture، جدول شوری و EC/SAR](https://www.fao.org/4/t0234e/t0234e01.htm).
2. [USGS، Specific conductance، اندازه‌گیری و مرجع دمای ۲۵ درجه](https://pubs.usgs.gov/tm/09/a6.3/tm9-a6_3.pdf).
3. [USGS، محدودیت نمونه‌برداری چاه‌های با اسکرین بلند](https://pubs.usgs.gov/of/1995/ofr-95-398/of95-398.html).
4. Hartmann & Moosdorf (2012)، [GLiM، DOI:10.1029/2012GC004370](https://doi.org/10.1029/2012GC004370). انتساب و URL ارائه‌دهندهٔ بردار در شناسنامهٔ منابع ثبت شده است.
5. [Sentinel-2 SR Harmonized در GEE](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED).
6. [ESA WorldCover v200، سال ۲۰۲۱](https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200).
7. [SRTMGL1_003 در GEE](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003).
8. Maghrebi et al. (2021)، [Iran’s Groundwater Hydrochemistry، DOI:10.1029/2021EA001793](https://doi.org/10.1029/2021EA001793): پشتوانهٔ اهمیت زمین‌شناسی و رخسارهٔ هیدروشیمیایی؛ ضرایب عددی عمقی از این مقاله به مشهد منتقل نشده‌اند.

**تفسیر نهایی:** عدد گزارش‌شده یک برآورد شرطی از حجم قابل زهکشی در محدودهٔ کیفیت انتخابی است. از آن، سلامت شرب، قابل‌برداشت‌بودن همهٔ ذخیره، اقتصادی‌بودن استخراج یا عمر باقیماندهٔ آبخوان نتیجه نمی‌شود.
'''

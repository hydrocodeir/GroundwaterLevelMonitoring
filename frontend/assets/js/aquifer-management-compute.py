"""Generic management screening. Executed in the browser, never on the server.

Forecasts continue observed, same-month trends; they are not a pumping-response
or groundwater-flow model. Missing or discontinued observations stay missing.
"""
import csv
import io
import json
import math
import heapq
import hashlib
from statistics import median
_mg_subsidence_cache={}


def mg_number(value, name, low=None, high=None, optional=False):
    if value is None or str(value).strip() == '':
        if optional:
            return None
        raise ValueError(f'{name}: مقدار لازم است.')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{name}: عدد معتبر وارد کنید.')
    if not math.isfinite(value) or low is not None and value < low or high is not None and value > high:
        raise ValueError(f'{name}: مقدار خارج از دامنهٔ مجاز است.')
    return value


def mg_quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values)-1)*q
    i = int(pos)
    return values[i] + (values[min(i+1,len(values)-1)]-values[i])*(pos-i)


def mg_fit(points, method='sen'):
    """Pairwise-slope P10/P90 is sensitivity, not a confidence interval."""
    points = sorted(points)
    if len(points) < 3 or points[-1][0] <= points[0][0]:
        raise ValueError('برای روند، حداقل سه سال مشاهدهٔ متمایز لازم است.')
    pairs = [(b[1]-a[1])/(b[0]-a[0]) for i,a in enumerate(points) for b in points[i+1:] if b[0]>a[0]]
    if method == 'sen':
        slope = median(pairs)
    elif method == 'ols':
        mx = sum(p[0] for p in points)/len(points)
        my = sum(p[1] for p in points)/len(points)
        slope = sum((x-mx)*(y-my) for x,y in points)/sum((x-mx)**2 for x,y in points)
    else:
        raise ValueError('روش روند ناشناخته است.')
    intercept = median([y-slope*x for x,y in points]) if method=='sen' else my-slope*mx
    errors=[]
    for i in range(3,len(points)):
        # Temporal holdout, anchored to the last observed training value.
        training=points[:i]
        train_pairs=[(b[1]-a[1])/(b[0]-a[0]) for j,a in enumerate(training) for b in training[j+1:]]
        if method=='sen':
            beta=median(train_pairs)
        else:
            xx=sum(p[0] for p in training)/i; yy=sum(p[1] for p in training)/i
            beta=sum((x-xx)*(y-yy) for x,y in training)/sum((x-xx)**2 for x,y in training)
        predicted=training[-1][1]+beta*(points[i][0]-training[-1][0])
        errors.append(abs(points[i][1]-predicted))
    return {'slope':slope,'intercept':intercept,'low':min(slope,mg_quantile(pairs,.1)),
            'high':max(slope,mg_quantile(pairs,.9)),'n':len(points),
            'span':points[-1][0]-points[0][0],'start_water_year':points[0][0],
            'end_water_year':points[-1][0],'backtest_mae_m':sum(errors)/len(errors) if errors else None,
            'backtest_count':len(errors),'backtest_errors':errors}


def mg_crossing(current, threshold, slope):
    if current is None or threshold is None:
        return None, 'unknown'
    if current <= threshold:
        return 0., 'already'
    if slope is None:
        return None, 'unknown'
    if slope >= 0:
        return None, 'not_crossed'
    years=(current-threshold)/(-slope)
    # IDW roundoff must not move an exact anniversary into the following WY.
    if math.isclose(years,round(years),rel_tol=1e-12,abs_tol=1e-10):
        years=float(round(years))
    return years, 'crossing'


def mg_nearest_tree(xy):
    """Pure-Python k-d tree: avoid a quadratic all-pairs pass on imported layers."""
    def build(indices,depth=0):
        if not indices:return None
        axis=depth%2;indices.sort(key=lambda i:xy[i][axis]);middle=len(indices)//2
        return (indices[middle],axis,build(indices[:middle],depth+1),build(indices[middle+1:],depth+1))
    tree=build(list(range(len(xy))))
    def query(target,k,exclude=None):
        best=[]
        def visit(branch):
            if branch is None:return
            index,axis,left,right=branch;delta=target[axis]-xy[index][axis]
            near,far=(left,right) if delta<0 else (right,left)
            visit(near)
            distance=(target[0]-xy[index][0])**2+(target[1]-xy[index][1])**2
            if index!=exclude:
                candidate=(-distance,-index)
                if len(best)<k:heapq.heappush(best,candidate)
                elif candidate>best[0]:heapq.heapreplace(best,candidate)
            if len(best)<k or delta*delta<=-best[0][0]:visit(far)
        if k>0:visit(tree)
        return sorted((math.sqrt(-distance),-index) for distance,index in best)
    return query


def mg_support(points, radius_km=None, neighbors=8, power=2, extrapolate=False):
    from shapely.geometry import MultiPoint, Point
    if not points:
        empty=lambda lon,lat: None
        empty.reasons=lambda lon,lat:['no_eligible_wells']
        empty.distance_km=lambda lon,lat:None
        return empty, None
    latitude=sum(p['lat'] for p in points)/len(points)
    sx=111320*math.cos(math.radians(latitude))
    xy=[(p['lon']*sx,p['lat']*111320) for p in points]
    hull=MultiPoint(xy).convex_hull
    nearest_query=mg_nearest_tree(xy)
    nearest=[next((d for d,_ in nearest_query(a,1,exclude=i)),0) for i,a in enumerate(xy)]
    positive=[d for d in nearest if d>0]
    radius=radius_km*1000 if radius_km is not None else 2*median(positive) if positive else 0
    def sample(lon,lat):
        target=(lon*sx,lat*111320)
        distances=nearest_query(target,neighbors)
        if not distances or hull.geom_type!='Polygon' or (not extrapolate and (distances[0][0]>radius or not hull.covers(Point(target)))):
            return None
        if distances[0][0]<1e-6:
            return [(points[distances[0][1]],1.)]
        chosen=distances[:neighbors]
        weights=[(chosen[0][0]/d)**power for d,_ in chosen]
        total=sum(weights)
        return [(points[i],w/total) for (_,i),w in zip(chosen,weights)]
    def reasons(lon,lat):
        target=(lon*sx,lat*111320);near=nearest_query(target,1);out=[]
        if hull.geom_type!='Polygon':out.append('not_2d_support')
        elif not hull.covers(Point(target)):out.append('outside_trend_hull')
        if not near or near[0][0]>radius:out.append('beyond_trend_radius')
        return out
    sample.reasons=reasons
    sample.distance_km=lambda lon,lat:nearest_query((lon*sx,lat*111320),1)[0][0]/1000
    return sample,radius/1000


def mg_cumulative_or_raster(text,options,polygons,start_wy,end_wy):
    """Cumulative measurements stay cumulative; raster NoData is never interpolated."""
    from shapely.geometry import shape,Polygon,Point
    from shapely.ops import unary_union
    cumulative=options.get('value_kind',options.get('quantity','rate'))=='cumulative'
    audit={'input_records':0,'inside_records':0,'outside_records':0,'period_excluded':0,
           'component':options.get('component'),'direction':options.get('direction'),
           'input_file':options.get('file_name'),'periods':[],'cumulative':cumulative,
           'sha256_utf8':hashlib.sha256(text.encode()).hexdigest() if text else None,
           'calendar_basis':options.get('calendar_basis','water_year'),
           'period_precision':options.get('period_precision','year')}
    audit.update(source_statistics=options.get('source_statistics'),source_sha256=options.get('source_sha256'),
                 raster_sampling_note='میانگین پیکسل‌های معتبر با مرکز داخل خانه؛ NoData درون‌یابی نمی‌شود.')
    if options.get('csv_sha256') and audit['sha256_utf8']!=options['csv_sha256']:
        raise ValueError('محتوای CSV با شناسنامهٔ آن یکسان نیست؛ فایل و شناسنامه را با هم به‌روز کنید.')
    if not text.strip():return lambda lon,lat,*args:None,audit
    if options.get('component') not in ('vertical','los') or options.get('direction') not in ('down','up'):
        raise ValueError('مؤلفه و قرارداد علامت فرونشست را معرفی کنید.')
    unit=options.get('unit','mm')
    if unit not in ('mm','cm','m'):raise ValueError('واحد نشست باید mm، cm یا m باشد.')
    sign=1 if options['direction']=='down' else -1
    def period(row):
        first=mg_number(row.get('start_year') or row.get('start_water_year') or options.get('start_year') or options.get('start_water_year'),'سال شروع فرونشست',1,9999)
        last=mg_number(row.get('end_year') or row.get('end_water_year') or options.get('end_year') or options.get('end_water_year'),'سال پایان فرونشست',1,9999)
        if int(first)!=first or int(last)!=last or first>last:raise ValueError('سال‌های صحیح و مرتب برای دوره لازم است.')
        first,last=int(first),int(last)
        basis=audit['calendar_basis']
        if basis=='persian':start,end=first*12+1,last*12+12;water=(first-1,last)
        elif basis=='water_year':start,end=first*12+7,(last+1)*12+6;water=(first,last)
        else:raise ValueError('مبنای سال باید شمسی یا سال آبی باشد.')
        duration=mg_number(row.get('duration_years') or options.get('duration_years'),'مدت اعلامی دوره',.001,optional=True)
        return (first,last,start,end,water,duration)
    def value(row):
        column='cumulative_mm' if cumulative and row.get('cumulative_mm') is not None else 'cumulative_value' if cumulative else 'rate_mm_year'
        scale=1 if column in ('cumulative_mm','rate_mm_year') else {'mm':1,'cm':10,'m':1000}[unit]
        return mg_number(row.get(column),'نشست تجمعی' if cumulative else 'نرخ نشست')*sign*scale
    def attach_period(p):
        audit.update(periods=[list(p[4])],source_years=[p[0],p[1]],comparison_ordinals=[p[2],p[3]],duration_years=p[5])
    def in_time(p):return p[3]<=(end_wy+1)*12+6 and (cumulative or p[3]>=start_wy*12+7)
    boundary=unary_union([Polygon(p[0],p[1:]) for p in polygons])
    if text.lstrip().startswith('{'):
        src=json.loads(text)
        if src.get('type')!='FeatureCollection':raise ValueError('FeatureCollection لازم است.')
        records=[(r.get('properties') or {},r.get('geometry')) for r in src.get('features',[])]
        is_raster=False
    else:
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')));headers=set(reader.fieldnames or [])
        if not {'longitude','latitude'}.issubset(headers):raise ValueError('ستون‌های longitude,latitude لازم‌اند.')
        if cumulative and not headers.intersection({'cumulative_mm','cumulative_value'}):raise ValueError('ستون cumulative_mm یا cumulative_value برای نشست تجمعی لازم است.')
        if not cumulative and 'rate_mm_year' not in headers:raise ValueError('ستون rate_mm_year برای نرخ لازم است.')
        is_raster={'pixel_row','pixel_column'}.issubset(headers)
        records=reader if is_raster else [(r,{'type':'Point','coordinates':[mg_number(r['longitude'],'طول',-180,180),mg_number(r['latitude'],'عرض',-90,90)]}) for r in reader]
    if is_raster:
        import numpy as np
        from shapely import contains_xy
        rr=[];cc=[];ll=[];bb=[];vv=[];source_period=None
        for row in records:
            p=period(row)
            if source_period is not None and p!=source_period:raise ValueError('یک دورهٔ مشترک برای پیکسل‌ها لازم است.')
            source_period=p
            row_i=mg_number(row['pixel_row'],'شماره سطر',0);col_i=mg_number(row['pixel_column'],'شماره ستون',0)
            if int(row_i)!=row_i or int(col_i)!=col_i:raise ValueError('شماره سطر و ستون باید صحیح باشد.')
            rr.append(int(row_i));cc.append(int(col_i));ll.append(mg_number(row['longitude'],'طول',-180,180));bb.append(mg_number(row['latitude'],'عرض',-90,90));vv.append(value(row))
        audit['input_records']=len(vv)
        if not vv:return lambda lon,lat,*args:None,audit
        attach_period(source_period)
        inside=np.asarray(contains_xy(boundary,np.array(ll),np.array(bb)))
        audit['outside_records']=int(np.sum(~inside))
        if not in_time(source_period):
            audit['period_excluded']=int(np.sum(inside));audit['periods']=[];return lambda lon,lat,*args:None,audit
        audit['inside_records']=int(np.sum(inside))
        grid=options.get('raster_grid')
        if not grid:
            # CSV retains row/column indices. Infer only a verified affine geographic grid.
            groups={}
            for i,r in enumerate(rr):
                if r in groups and cc[groups[r]]!=cc[i]:pair=(groups[r],i);break
                groups[r]=i
            else:raise ValueError('شناسنامهٔ شبکهٔ TIFF برای این CSV لازم است.')
            i,j=pair;a=(ll[j]-ll[i])/(cc[j]-cc[i]);d=(bb[j]-bb[i])/(cc[j]-cc[i])
            k=next((k for k in range(len(rr)) if rr[k]!=rr[i]),None)
            if k is None:raise ValueError('شبکهٔ TIFF باید دوبعدی باشد.')
            b=(ll[k]-ll[i]-a*(cc[k]-cc[i]))/(rr[k]-rr[i]);e=(bb[k]-bb[i]-d*(cc[k]-cc[i]))/(rr[k]-rr[i])
            c=ll[i]-a*(cc[i]+.5)-b*(rr[i]+.5);f=bb[i]-d*(cc[i]+.5)-e*(rr[i]+.5)
            grid={'crs':'EPSG:4326','width':max(cc)+1,'height':max(rr)+1,'affine':[a,b,c,d,e,f],'inferred_from_csv':True}
        a,b,c,d,e,f=[float(v) for v in grid['affine']];det=a*e-b*d
        if abs(det)<1e-20:raise ValueError('شبکهٔ TIFF تبدیل معتبر ندارد.')
        width,height=int(grid['width']),int(grid['height'])
        if width<=max(cc) or height<=max(rr) or min(width,height)<=0:raise ValueError('ابعاد شناسنامه با CSV یکسان نیست.')
        crs=grid.get('crs','EPSG:4326');forward=backward=None
        if crs!='EPSG:4326':
            from pyproj import Transformer
            forward=Transformer.from_crs(crs,'EPSG:4326',always_xy=True);backward=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
        xa=a*(np.array(cc)+.5)+b*(np.array(rr)+.5)+c;ya=d*(np.array(cc)+.5)+e*(np.array(rr)+.5)+f
        if forward:xa,ya=forward.transform(xa,ya)
        if np.max(np.abs(xa-np.array(ll)))>1e-7 or np.max(np.abs(ya-np.array(bb)))>1e-7:raise ValueError('مختصات CSV با شبکه سازگار نیست؛ شناسنامهٔ اصلی را معرفی کنید.')
        raster=np.full((height,width),np.nan)
        for row_i,col_i,v in zip(rr,cc,vv):
            if math.isfinite(raster[row_i,col_i]) and raster[row_i,col_i]!=v:raise ValueError('پیکسل تکراری با مقدار متعارض وجود دارد.')
            raster[row_i,col_i]=v
        coverage_min=mg_number(options.get('min_pixel_coverage',.5),'حداقل پوشش معتبر TIFF',0,1)
        audit.update(raster_grid=grid,raster_sampling='mean_valid_pixel_centres',min_pixel_coverage=coverage_min,
                     point_count=len(vv),polygon_count=0)
        def query(lon,lat,cell_polygons=None):
            if not cell_polygons:
                x,y=backward.transform(lon,lat) if backward else (lon,lat)
                col_i=math.floor((e*(x-c)-b*(y-f))/det);row_i=math.floor((-d*(x-c)+a*(y-f))/det)
                v=raster[row_i,col_i] if 0<=row_i<height and 0<=col_i<width else float('nan')
                coverage=1. if math.isfinite(v) else 0.;mean=float(v) if coverage else None
            else:
                geom=unary_union([Polygon(p[0],p[1:]) for p in cell_polygons])
                xmin,ymin,xmax,ymax=geom.bounds
                xx=np.array([xmin,xmax,xmax,xmin]);yy=np.array([ymin,ymin,ymax,ymax])
                if backward:xx,yy=backward.transform(xx,yy)
                cols=(e*(xx-c)-b*(yy-f))/det;rows=(-d*(xx-c)+a*(yy-f))/det
                left,right=math.floor(float(cols.min()))-1,math.ceil(float(cols.max()))+1
                top,bottom=math.floor(float(rows.min()))-1,math.ceil(float(rows.max()))+1
                if (right-left)*(bottom-top)>5_000_000:raise ValueError('پیکسل محاسباتی برای این TIFF بسیار بزرگ است؛ شبکهٔ مناسب‌تری وارد کنید.')
                col_array,row_array=np.meshgrid(np.arange(left,right)+.5,np.arange(top,bottom)+.5)
                xx=a*col_array+b*row_array+c;yy=d*col_array+e*row_array+f
                if forward:xx,yy=forward.transform(xx,yy)
                mask=contains_xy(geom,xx,yy)
                window=np.full(mask.shape,np.nan)
                x0,x1=max(0,left),min(width,right);y0,y1=max(0,top),min(height,bottom)
                if x1>x0 and y1>y0:window[y0-top:y1-top,x0-left:x1-left]=raster[y0:y1,x0:x1]
                valid=mask & np.isfinite(window);count=int(np.sum(mask));coverage=float(np.sum(valid))/count if count else 0.
                mean=float(np.mean(window[valid])) if np.any(valid) and coverage>=coverage_min else None
            rate=mean/source_period[5] if cumulative and mean is not None and source_period[5] else mean if not cumulative else None
            return {'rate':rate,'cumulative':mean if cumulative else None,'coverage_pct':coverage*100}
        return query,audit
    points=[];zones=[];source_period=None
    for row,geometry in records:
        audit['input_records']+=1;p=period(row);v=value(row);geom=shape(geometry)
        if geom.is_empty or not geom.is_valid or geom.geom_type not in ('Point','Polygon','MultiPolygon'):raise ValueError('هندسهٔ فرونشست معتبر نیست.')
        if not boundary.intersects(geom):audit['outside_records']+=1;continue
        if not in_time(p):audit['period_excluded']+=1;continue
        if source_period is not None and p!=source_period:raise ValueError('یک دورهٔ مشترک لازم است.')
        source_period=p;audit['inside_records']+=1
        if geom.geom_type=='Point':points.append({'lon':geom.x,'lat':geom.y,'value':v})
        else:zones.append((geom,v))
    if source_period:attach_period(source_period)
    sample,radius=mg_support(points,options.get('support_km'),options.get('neighbors',8),options.get('power',2))
    spatial_sample,spatial_audit=sp_sampler(points+[{'lon':g.intersection(boundary).representative_point().x,'lat':g.intersection(boundary).representative_point().y,'value':v} for g,v in zones],['value'],options['spatial']) if options.get('spatial') else (None,None)
    if spatial_audit:audit['spatial']=spatial_audit
    audit.update(support_radius_km=radius,point_count=len(points),polygon_count=len(zones))
    def query(lon,lat,*args):
        found=[v for geom,v in zones if geom.covers(Point(lon,lat))]
        if found and max(found)-min(found)>1e-8:raise ValueError('پهنه‌های متعارض همپوشانی دارند.')
        weights=sample(lon,lat) if not found else None
        v=found[0] if found else sum(p['value']*w for p,w in weights) if weights else None
        estimate=spatial_sample(lon,lat) if spatial_sample and not found else None
        if estimate:v=estimate['values']['value'] if estimate['values'] else None
        return {'rate':v/source_period[5] if cumulative and v is not None and source_period and source_period[5] else v if not cumulative else None,
                'cumulative':v if cumulative else None,'coverage_pct':100 if found or weights else 0,
                'estimated':bool(estimate and (estimate['extrapolated'] or not weights)),'spatial_method':spatial_audit['method'] if spatial_audit else None}
    return query,audit


def mg_annual_subsidence(text,options,polygons,start_wy,end_wy):
    """Average observed annual rates; never partition a cumulative observation."""
    rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))));by_year={}
    for r in rows:
        y=mg_number(r.get('water_year'),'سال آبی نشست',1,9999)
        if y!=int(y):raise ValueError('سال آبی نشست باید صحیح باشد.')
        if y<=end_wy:by_year.setdefault(int(y),[]).append(r)
    mode=str(options.get('rate_window','source'))
    if mode in ('source','all'):first=min(by_year,default=end_wy)
    else:
        length=mg_number(options.get('rate_window_years') if mode=='custom' else mode,'دورهٔ نرخ نشست',3,200)
        if length!=int(length):raise ValueError('طول دورهٔ نرخ نشست باید صحیح باشد.')
        first=end_wy-int(length)+1
    chosen=sorted(y for y in by_year if first<=y<=end_wy);queries=[];audits=[]
    for y in chosen:
        fields=[k for k in rows[0] if k!='water_year'];fields=list(dict.fromkeys(fields+['start_water_year','end_water_year']))
        output=io.StringIO();writer=csv.DictWriter(output,fields);writer.writeheader()
        for r in by_year[y]:writer.writerow({**{k:v for k,v in r.items() if k!='water_year'},'start_water_year':y,'end_water_year':y})
        settings={**options,'value_kind':'rate','calendar_basis':'water_year','start_water_year':y,'end_water_year':y}
        settings.pop('rate_window',None);settings.pop('csv_sha256',None)
        query,audit=mg_cumulative_or_raster(output.getvalue(),settings,polygons,y,y) if {'row','column'}.issubset(fields) else mg_subsidence_uncached(output.getvalue(),settings,polygons,y,y)
        queries.append((y,query));audits.append(audit)
    required=1 if mode=='source' else max(3,math.ceil((end_wy-first+1)*.5))
    def query(lon,lat,*args):
        values=[];last=False
        for y,q in queries:
            value=q(lon,lat,*args);rate=value.get('rate') if isinstance(value,dict) else value
            if rate is not None:values.append(rate);last|=y==end_wy
        valid=len(values)>=required and (mode=='source' or last)
        return {'rate':sum(values)/len(values) if valid else None,'cumulative':None,'coverage_pct':100*len(values)/(end_wy-first+1) if end_wy>=first else 0}
    audit={**(audits[-1] if audits else {}),'input_records':len(rows),'inside_records':sum(a.get('inside_records',0) for a in audits),
           'component':options.get('component'),'direction':options.get('direction'),'input_file':options.get('file_name'),
           'periods':[[min(chosen),max(chosen)]] if chosen else [],'annual_years':sorted(by_year),'selected_years':chosen,'annual_rates':True,'cumulative':False,
           'rate_window':mode,'rate_period_start_water_year':first,'rate_period_end_water_year':end_wy,'minimum_years_per_cell':required,
           'sha256_utf8':hashlib.sha256(text.encode()).hexdigest(),'rate_estimator':'Mean observed annual rate, with temporal coverage and end-year guards for explicit historical windows; no cumulative splitting'}
    return query,audit


def mg_subsidence_uncached(text, options, polygons, start_wy, end_wy):
    if text.strip() and not text.lstrip().startswith('{'):
        headers=next(csv.reader(io.StringIO(text.lstrip('\ufeff'))),[])
        if 'water_year' in headers and 'rate_mm_year' in headers:
            if options.get('value_kind')=='cumulative':raise ValueError('برای فایل water_year و rate_mm_year، نوع مقادیر را «نرخ سالانه» انتخاب کنید.')
            return mg_annual_subsidence(text,options,polygons,start_wy,end_wy)
    if options.get('value_kind',options.get('quantity'))=='cumulative' or options.get('raster_grid'):
        return mg_cumulative_or_raster(text,options,polygons,start_wy,end_wy)
    from shapely.geometry import shape, Polygon, Point
    from shapely.ops import unary_union
    audit={'input_records':0,'inside_records':0,'outside_records':0,'period_excluded':0,
           'component':options.get('component'),'direction':options.get('direction'),
           'input_file':options.get('file_name'),'periods':[]}
    audit['sha256_utf8']=hashlib.sha256(text.encode('utf-8')).hexdigest() if text else None
    if not text.strip():
        return lambda lon,lat,*args: None, audit
    if options.get('component') not in ('vertical','los'):
        raise ValueError('نوع مؤلفهٔ فرونشست را مشخص کنید: قائم یا خط دید.')
    if options.get('direction') not in ('down','up'):
        raise ValueError('قرارداد علامت نرخ فرونشست را مشخص کنید.')
    sign=1 if options['direction']=='down' else -1
    boundary=unary_union([Polygon(p[0],p[1:]) for p in polygons])
    records=[]
    if text.lstrip().startswith('{'):
        source=json.loads(text)
        if source.get('type')!='FeatureCollection':
            raise ValueError('فایل فرونشست باید FeatureCollection باشد.')
        records=[(r.get('properties') or {},r.get('geometry')) for r in source.get('features',[])]
    else:
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
        if not {'longitude','latitude','rate_mm_year'}.issubset(set(reader.fieldnames or [])):
            raise ValueError('ستون‌های فرونشست: longitude,latitude,rate_mm_year؛ مختصات WGS84 و نرخ mm/year.')
        records=[(r,{'type':'Point','coordinates':[mg_number(r['longitude'],'طول',-180,180),mg_number(r['latitude'],'عرض',-90,90)]}) for r in reader]
    points=[]; zones=[]; periods=set()
    for row,geometry in records:
        audit['input_records']+=1
        if not geometry:
            raise ValueError('هندسهٔ یک ردیف فرونشست خالی است.')
        geom=shape(geometry)
        if geom.geom_type not in ('Point','Polygon','MultiPolygon') or not geom.is_valid or geom.is_empty:
            raise ValueError('هندسهٔ معتبر Point، Polygon یا MultiPolygon برای فرونشست لازم است.')
        if not (-180<=geom.bounds[0]<=geom.bounds[2]<=180 and -90<=geom.bounds[1]<=geom.bounds[3]<=90):
            raise ValueError('مختصات فرونشست باید جغرافیایی WGS84 باشد.')
        rate=mg_number(row.get('rate_mm_year'),'نرخ فرونشست')*sign
        first=mg_number(row.get('start_water_year') or options.get('start_water_year'),'سال آبی شروع فرونشست',1,9999)
        last=mg_number(row.get('end_water_year') or options.get('end_water_year'),'سال آبی پایان فرونشست',1,9999)
        if int(first)!=first or int(last)!=last or first>last:
            raise ValueError('دورهٔ فرونشست باید سال آبی صحیح و مرتب باشد.')
        if not boundary.intersects(geom):
            audit['outside_records']+=1
            continue
        if last>end_wy or last<start_wy or first>end_wy:
            audit['period_excluded']+=1
            continue
        audit['inside_records']+=1;periods.add((int(first),int(last)))
        if geom.geom_type=='Point':
            points.append({'lon':geom.x,'lat':geom.y,'rate':rate})
        else:
            zones.append((geom,rate))
    # Do not silently blend multiple periods or conflicting duplicate point estimates.
    if len(periods)>1:
        raise ValueError('برای مقایسه، یک دورهٔ مشترک فرونشست وارد کنید؛ دوره‌های متفاوت را ابتدا جدا کنید.')
    merged={}
    for point in points:
        key=(point['lon'],point['lat'])
        if key in merged and abs(merged[key]['rate']-point['rate'])>1e-8:
            raise ValueError('نقاط فرونشست تکراری با نرخ متفاوت وجود دارند.')
        merged[key]=point
    sample,radius=mg_support(list(merged.values()),options.get('support_km'),options.get('neighbors',8),options.get('power',2))
    spatial_sample,spatial_audit=sp_sampler(list(merged.values())+[{'lon':g.intersection(boundary).representative_point().x,'lat':g.intersection(boundary).representative_point().y,'rate':v} for g,v in zones],['rate'],options['spatial']) if options.get('spatial') else (None,None)
    if spatial_audit:audit['spatial']=spatial_audit
    audit['periods']=[list(p) for p in sorted(periods)];audit['support_radius_km']=radius
    audit['point_count']=len(merged);audit['polygon_count']=len(zones)
    def query(lon,lat,*args):
        point=Point(lon,lat)
        found=[rate for geom,rate in zones if geom.covers(point)]
        if found:
            if max(found)-min(found)>1e-8:
                raise ValueError('پهنه‌های فرونشست با نرخ متفاوت همپوشانی دارند.')
            return found[0]
        weights=sample(lon,lat)
        if spatial_sample:
            estimate=spatial_sample(lon,lat)
            return {'rate':estimate['values']['rate'] if estimate['values'] else None,'cumulative':None,'coverage_pct':100 if weights else 0,
                    'estimated':bool(estimate['extrapolated'] or not weights),'spatial_method':spatial_audit['method'],'spline_overshoot':estimate['overshoot']}
        return sum(p['rate']*w for p,w in weights) if weights else None
    return query,audit


def mg_subsidence(text,options,polygons,start_wy,end_wy,cells=None):
    from copy import deepcopy
    key=hashlib.sha256(text.encode()).hexdigest()+json.dumps([options,polygons,start_wy,end_wy,[(c['lon'],c['lat'],c['polygons']) for c in (cells or [])]] if options.get('spatial') else [options,polygons,start_wy,end_wy],sort_keys=True)
    if key not in _mg_subsidence_cache:
        _mg_subsidence_cache.clear()
        query,audit=mg_subsidence_uncached(text,options,polygons,start_wy,end_wy)
        if options.get('spatial') and cells and audit.get('raster_grid'):
            query,audit=sp_raster_surface(query,audit,cells,options['spatial'])
        _mg_subsidence_cache[key]=query,audit
    query,audit=_mg_subsidence_cache[key]
    return query,deepcopy(audit)


def management_analysis(data, histories, options):
    """Only data-dependent results. Defaults are editable methodological settings."""
    from copy import deepcopy
    spatial=sp_config(data['spatial']) if data.get('spatial') else None
    horizons=options.get('horizons',[3,5,10,25])
    if isinstance(horizons,str):
        horizons=horizons.replace('،',',').split(',')
    horizons=sorted(set(mg_number(h,'افق آینده',1,1000) for h in horizons))
    if not horizons or len(horizons)>60:
        raise ValueError('بین یک تا ۶۰ افق مثبت وارد کنید.')
    if any(int(h)!=h for h in horizons):
        raise ValueError('افق‌ها را به تعداد صحیح سال آبی وارد کنید.')
    horizons=[int(h) for h in horizons]
    lookback=mg_number(options.get('lookback',10),'طول دورهٔ روند',3,200)
    minimum=mg_number(options.get('min_observations',5),'حداقل سال مشاهده',3,200)
    if int(lookback)!=lookback or int(minimum)!=minimum or minimum>lookback:
        raise ValueError('تعداد سال‌ها باید صحیح باشد؛ حداقل مشاهدات نباید از طول دوره بیشتر باشد.')
    lookback=int(lookback);minimum=int(minimum)
    coverage=mg_number(options.get('coverage',.5),'حداقل پوشش زمانی',0,1)
    power=mg_number(options.get('power',2),'توان IDW',.1,10)
    neighbors=mg_number(options.get('neighbors',8),'تعداد همسایه',3,100)
    if int(neighbors)!=neighbors:
        raise ValueError('تعداد همسایه باید صحیح باشد.')
    neighbors=int(neighbors)
    radius=mg_number(options.get('support_km'),'فاصلهٔ پشتیبانی',.001,optional=True)
    method=options.get('method','sen')
    if method not in ('sen','ols'):
        raise ValueError('روش روند ناشناخته است.')
    end_wy=int(data['dates']['after_water_year']);start_wy=end_wy-lookback+1
    decline_limit=mg_number(options.get('decline_limit'),'معیار افت سالانه',0,optional=True)
    quantile=mg_number(options.get('priority_quantile',75),'صدک اولویت',0,100)/100
    subsidence_limit=mg_number(options.get('subsidence_limit'),'معیار فرونشست',0,optional=True)
    urgent=mg_number(options.get('urgent_years'),'افق اقدام',0,optional=True)
    if urgent is None:urgent=horizons[0]
    threshold=mg_number(options.get('threshold'),'آستانه بحرانی',optional=True)
    threshold_type=options.get('threshold_type','saturated')
    if threshold_type not in ('saturated','drawdown','head'):
        raise ValueError('نوع آستانه بحرانی ناشناخته است.')
    if threshold_type!='head' and threshold is not None and threshold<0:
        raise ValueError('ضخامت یا افت مجاز نباید منفی باشد.')
    quality_mode=options.get('quality_mode','crop')
    if quality_mode not in ('crop','drinking','either'):
        raise ValueError('معیار کیفیت ناشناخته است.')
    trends=[];well_report=[];backtest=[]
    for well in histories:
        points=sorted((r['water_year'],r['level']) for r in well['records'] if start_wy<=r['water_year']<=end_wy and r.get('month',6)==6)
        result={k:well[k] for k in ('name','lon','lat')}
        result.update({'observations':len(points),'eligible':False})
        if len(points)<minimum or not points or points[-1][0]!=end_wy or points[-1][0]-points[0][0]<minimum-1 or len(points)/lookback<coverage:
            result['reason']='مشاهدات یا پوشش زمانی کافی نیست؛ دادهٔ انتهای دوره لازم است.'
        else:
            fit=mg_fit(points,method)
            result.update(fit);result['eligible']=True
            trends.append(result);backtest.extend(fit['backtest_errors'])
        well_report.append(result)
    sample,actual_radius=mg_support(trends,radius,neighbors,power)
    # Candidate extension is kept separate: management maps/forecasts still use
    # strict support. Only an explicit lifetime scenario can select these values.
    extended_sample,_=mg_support(trends,radius,neighbors,power,extrapolate=True)
    maps=deepcopy(data['plan_maps']);cells=maps['cells']
    trend_sampler,trend_spatial=sp_sampler(trends,['slope','low','high'],{**spatial,'neighbors':neighbors,'power':power}) if spatial else (None,None)
    sub_options=dict(options.get('subsidence') or {})
    sub_options.update(support_km=radius,neighbors=neighbors,power=power)
    if spatial:sub_options['spatial']={**spatial,'neighbors':neighbors,'power':power}
    try:
        sub_query,sub_audit=mg_subsidence(sub_options.pop('text',''),sub_options,maps['polygons'],start_wy,end_wy,cells)
    except ValueError as error:
        if not options.get('allow_incomplete_subsidence'):raise
        # An optional incomplete layer must not discard an independently valid
        # piezometer trend. Its error stays explicit in the report and interface.
        sub_query,sub_audit=mg_subsidence('',sub_options,maps['polygons'],start_wy,end_wy)
        sub_audit['input_error']=str(error)
    sub_min=mg_number(options.get('subsidence_min_observations',3),'حداقل مشاهدهٔ هم‌دوره فرونشست',3,200)
    if int(sub_min)!=sub_min:
        raise ValueError('حداقل مشاهدهٔ هم‌دوره باید صحیح باشد.')
    aligned=[]
    cumulative=bool(sub_audit.get('cumulative'))
    endpoint_tolerance=mg_number(options.get('endpoint_tolerance_months',1),'فاصلهٔ مجاز مشاهده از مرز دوره',0,24)
    endpoint_report=[]
    if sub_audit['periods']:
        first,last=sub_audit['periods'][0]
        for well in histories:
            if cumulative:
                start_ord,end_ord=sub_audit['comparison_ordinals']
                records=sorted((r.get('ordinal',(r['water_year']+1)*12+6),r['level']) for r in well['records'])
                records=[r for r in records if start_ord<=r[0]<=end_ord]
                if (len(records)>=sub_min and records[0][0]-start_ord<=endpoint_tolerance and end_ord-records[-1][0]<=endpoint_tolerance
                    and len(records)/(end_ord-start_ord+1)>=coverage and records[-1][0]>records[0][0]):
                    span=(records[-1][0]-records[0][0])/12;drop=records[0][1]-records[-1][1]
                    aligned.append({'lon':well['lon'],'lat':well['lat'],'slope':-drop/span,'cumulative_drop':drop})
                    def date(ordinal):return f'{(ordinal-1)//12}-{(ordinal-1)%12+1:02}'
                    endpoint_report.append({'name':well['name'],'first':date(records[0][0]),'last':date(records[-1][0]),'months':len(records),'observed_span_years':span})
            else:
                points=sorted((r['water_year'],r['level']) for r in well['records'] if first<=r['water_year']<=last and r.get('month',6)==6)
                if len(points)>=sub_min and points[-1][0]==last and len(points)/(last-first+1)>=coverage:
                    aligned.append({'lon':well['lon'],'lat':well['lat'],**mg_fit(points,method)})
    aligned_sample,aligned_radius=mg_support(aligned,radius,neighbors,power)
    aligned_spatial,_=sp_sampler(aligned,['slope','cumulative_drop'] if cumulative else ['slope'],{**spatial,'neighbors':neighbors,'power':power}) if spatial else (None,None)
    sub_audit.update(aligned_wells=len(aligned),aligned_support_radius_km=aligned_radius,
                     groundwater_endpoints=endpoint_report,comparison_mode='observed_cumulative' if cumulative else 'annual_trend')
    q=options.get('quality') or {}
    if q and q.get('volume_end')!=data['dates']['after']:
        raise ValueError('دورهٔ کیفیت با مدل فعال یکسان نیست؛ کیفیت را دوباره محاسبه کنید.')
    quality_cells={(round(c['lon'],8),round(c['lat'],8)):c for c in q.get('cells',[])}
    total_pixels=sum(c['remaining_mcm'] or 0 for c in cells)
    analytic=data['metrics'].get('drainable_after_mcm')
    volume_factor=analytic/total_pixels if analytic is not None and total_pixels>0 else 1
    supported_area=0.;sub_area=0.;overlap_area=0.;quality_area=0.;total_area=sum(c['area_m2'] for c in cells)
    weighted_slope=0.;weighted_low=0.;weighted_high=0.;supported_volume=0.;supported_volume_area=0.
    for cell in cells:
        weights=sample(cell['lon'],cell['lat'])
        slope=sum(p['slope']*w for p,w in weights) if weights else None
        low=sum(p['low']*w for p,w in weights) if weights else None
        high=sum(p['high']*w for p,w in weights) if weights else None
        extended=weights or extended_sample(cell['lon'],cell['lat'])
        cell.update(management_slope=slope,management_decline=-slope if slope is not None else None,
                    management_slope_low=low,management_slope_high=high,
                    management_support_reasons=sample.reasons(cell['lon'],cell['lat']),
                    management_nearest_well_km=sample.distance_km(cell['lon'],cell['lat']),
                    management_extended_slope=sum(p['slope']*w for p,w in extended) if extended else None,
                    management_extended_slope_low=sum(p['low']*w for p,w in extended) if extended else None,
                    management_extended_slope_high=sum(p['high']*w for p,w in extended) if extended else None)
        if trend_sampler:
            estimate=trend_sampler(cell['lon'],cell['lat']);values=estimate['values'];weights=values is not None
            slope=values['slope'] if values else None;low=min(values.values()) if values else None;high=max(values.values()) if values else None
            cell.update(management_slope=slope,management_decline=-slope if slope is not None else None,management_slope_low=low,management_slope_high=high,
                        management_extended_slope=slope,management_extended_slope_low=low,management_extended_slope_high=high,
                        management_spatial_estimated=bool(estimate['extrapolated'] or cell['management_support_reasons']),
                        management_spatial_method=spatial['method'],management_spline_overshoot=estimate['overshoot'],management_nearest_well_name=estimate['nearest_name'])
        if weights:
            supported_area+=cell['area_m2'];weighted_slope+=slope*cell['area_m2']
            weighted_low+=low*cell['area_m2'];weighted_high+=high*cell['area_m2']
            if cell['remaining_mcm'] is not None:
                supported_volume+=cell['remaining_mcm']*volume_factor;supported_volume_area+=cell['area_m2']
        sub_value=sub_query(cell['lon'],cell['lat'],cell['polygons'])
        sub=sub_value.get('rate') if isinstance(sub_value,dict) else sub_value
        cumulative_sub=sub_value.get('cumulative') if isinstance(sub_value,dict) else None
        cell['management_subsidence']=sub
        cell['management_subsidence_cumulative']=cumulative_sub
        cell['management_subsidence_coverage_pct']=sub_value.get('coverage_pct') if isinstance(sub_value,dict) else 100 if sub is not None else 0
        cell['management_subsidence_estimated']=bool(sub_value.get('estimated')) if isinstance(sub_value,dict) else False
        cell['management_subsidence_method']=sub_value.get('spatial_method') if isinstance(sub_value,dict) else None
        aligned_weights=aligned_sample(cell['lon'],cell['lat'])
        aligned_decline=-sum(p['slope']*w for p,w in aligned_weights) if aligned_weights else None
        cell['management_subsidence_decline']=aligned_decline
        groundwater_cumulative=sum(p['cumulative_drop']*w for p,w in aligned_weights) if cumulative and aligned_weights else None
        if aligned_spatial:
            estimate=aligned_spatial(cell['lon'],cell['lat']);v=estimate['values']
            aligned_decline=-v['slope'] if v else None;cell['management_subsidence_decline']=aligned_decline
            groundwater_cumulative=v['cumulative_drop'] if cumulative and v else None
        cell['management_groundwater_cumulative']=groundwater_cumulative
        metric=cumulative_sub if cumulative else sub
        if metric is not None:sub_area+=cell['area_m2']
        if metric is not None and aligned_decline is not None:overlap_area+=cell['area_m2']
        quality=quality_cells.get((round(cell['lon'],8),round(cell['lat'],8))) or {}
        ec=quality.get('quality_ec');zone=quality.get('quality_zone_code')
        known=bool(quality.get('quality_supported')) and ec is not None
        crop=zone in (2,3) if known and zone in (0,1,2,3) else None
        drink=ec>q['thresholds']['drinking_ec_uScm'] if known else None
        qhigh=(crop if quality_mode=='crop' else drink if quality_mode=='drinking' else
               True if crop is True or drink is True else False if crop is False and drink is False else None)
        if qhigh is not None:quality_area+=cell['area_m2']
        cell.update(management_quality_problem=qhigh,management_ec=ec)
        current=cell['after_msl']
        cutoff=None
        if threshold is not None:
            if threshold_type=='head':cutoff=threshold
            elif threshold_type=='drawdown':cutoff=current-threshold
            elif cell['bedrock_msl'] is not None:cutoff=cell['bedrock_msl']+threshold
        crossing,status=mg_crossing(current,cutoff,slope)
        fast,_=mg_crossing(current,cutoff,low)
        slow,slow_status=mg_crossing(current,cutoff,high)
        cell.update(management_critical_years=crossing,management_critical_status=status,
                    management_critical_head=cutoff,management_critical_fast=fast,management_critical_slow=slow,
                    management_critical_slow_status=slow_status,
                    management_critical_water_year=end_wy+math.ceil(crossing) if crossing is not None else None)
        if status=='already':band=0
        elif crossing is not None:band=next((i+1 for i,h in enumerate(horizons) if crossing<=h),len(horizons)+1)
        elif status=='not_crossed':band=len(horizons)+2
        else:band=len(horizons)+3
        cell['management_critical_band']=band
        future={}
        for h in horizons:
            item={'horizon':h,'water_year':end_wy+h,'head_msl':None,'saturated_m':None,'remaining_mcm':None,
                  'remaining_low_mcm':None,'remaining_high_mcm':None}
            if slope is not None:
                head=current+slope*h;item['head_msl']=head
                if cell['bedrock_msl'] is not None:
                    item['saturated_m']=max(0,head-cell['bedrock_msl'])
                    item['below_floor']=head<cell['bedrock_msl']
                    if cell['sy'] is not None:
                        scale=cell['sy']*cell['area_m2']/1e6*volume_factor
                        item['remaining_mcm']=item['saturated_m']*scale
                        item['remaining_low_mcm']=max(0,current+low*h-cell['bedrock_msl'])*scale
                        item['remaining_high_mcm']=max(0,current+high*h-cell['bedrock_msl'])*scale
            future[str(h)]=item
        cell['management_horizons']=future
    positive=[c['management_decline'] for c in cells if c['management_decline'] is not None and c['management_decline']>0]
    sub_key='management_subsidence_cumulative' if cumulative else 'management_subsidence'
    decline_key='management_groundwater_cumulative' if cumulative else 'management_subsidence_decline'
    sub_positive=[c[sub_key] for c in cells if c[sub_key] is not None and c[sub_key]>0]
    # Relative screening is explicitly distinct from an externally established safety limit.
    used_decline=decline_limit if decline_limit is not None else mg_quantile(positive,quantile)
    cumulative_limit=mg_number(options.get('cumulative_subsidence_limit'),'معیار نشست تجمعی',0,optional=True)
    cumulative_decline_limit=mg_number(options.get('cumulative_decline_limit'),'معیار افت تجمعی',0,optional=True)
    selected_sub_limit=cumulative_limit if cumulative else subsidence_limit
    selected_decline_limit=cumulative_decline_limit if cumulative else decline_limit
    used_sub=selected_sub_limit if selected_sub_limit is not None else mg_quantile(sub_positive,quantile)
    aligned_positive=[c[decline_key] for c in cells if c[decline_key] is not None and c[decline_key]>0]
    used_aligned=selected_decline_limit if selected_decline_limit is not None else mg_quantile(aligned_positive,quantile)
    counts=[0]*9;areas=[0.]*9;overlap_counts=[0]*6
    for cell in cells:
        rate=cell['management_decline'];sub=cell[sub_key];t=cell['management_critical_years'];qual=cell['management_quality_problem']
        d=rate is not None and used_decline is not None and rate>0 and rate>=used_decline
        s=sub is not None and used_sub is not None and sub>0 and sub>=used_sub
        aligned_rate=cell[decline_key]
        aligned_high=aligned_rate is not None and used_aligned is not None and aligned_rate>0 and aligned_rate>=used_aligned
        if t is not None and t<=urgent:priority=4
        elif rate is None:priority=8 if qual is True else 5
        elif qual is None:priority=7 if d else 6
        elif d and qual:priority=3
        elif d:priority=1
        elif qual:priority=2
        else:priority=0
        overlap=4 if sub is None else 5 if aligned_rate is None else 3 if aligned_high and s else 1 if aligned_high else 2 if s else 0
        cell.update(management_priority=priority,management_overlap=overlap)
        counts[priority]+=1;areas[priority]+=cell['area_m2'];overlap_counts[overlap]+=1
    forecast=[]
    for h in horizons:
        items=[c['management_horizons'][str(h)] for c in cells]
        valid=[p for p in items if p['remaining_mcm'] is not None]
        critical_area=sum(c['area_m2'] for c in cells if c['management_critical_years'] is not None and c['management_critical_years']<=h)
        forecast.append({'horizon':h,'water_year':end_wy+h,
                         'mean_head_change_m':weighted_slope/supported_area*h if supported_area else None,
                         'mean_head_low_m':weighted_low/supported_area*h if supported_area else None,
                         'mean_head_high_m':weighted_high/supported_area*h if supported_area else None,
                         'remaining_supported_mcm':sum(p['remaining_mcm'] for p in valid) if valid else None,
                         'remaining_low_mcm':sum(p['remaining_low_mcm'] for p in valid) if valid else None,
                         'remaining_high_mcm':sum(p['remaining_high_mcm'] for p in valid) if valid else None,
                         'critical_area_km2':critical_area/1e6,'critical_area_pct':100*critical_area/total_area if total_area else 0,
                         'long_extrapolation':bool(trends) and h>min(t['span'] for t in trends)})
    report={'version':1,'aquifer':data['aquifer'],'dates':data['dates'],'computed_at_utc':options.get('computed_at_utc'),
            'volume_model':{'sy_mode':data['metrics'].get('sy_mode'),'sy':data['metrics'].get('sy'),
                            'bedrock_source':data.get('grid',{}).get('bedrock_source'),
                            'input_files':data.get('input_files',{})},
            'spatial':trend_spatial,
            'settings':{'spatial':spatial,'horizons':horizons,'lookback':lookback,'min_observations':minimum,'coverage':coverage,
                        'method':method,'neighbors':neighbors,'power':power,'support_km':radius,
                        'subsidence_min_observations':int(sub_min),
                        'endpoint_tolerance_months':endpoint_tolerance,'cumulative_subsidence_limit':cumulative_limit,
                        'cumulative_decline_limit':cumulative_decline_limit,
                        'priority_quantile':quantile*100,'decline_limit':decline_limit,'subsidence_limit':subsidence_limit,
                        'urgent_years':urgent,'threshold':threshold,'threshold_type':threshold_type,'quality_mode':quality_mode},
            'trend_start_water_year':start_wy,'trend_end_water_year':end_wy,'well_count':len(histories),'eligible_wells':len(trends),
            'observed_spans':[min(t['span'] for t in trends),max(t['span'] for t in trends)] if trends else None,
            'support_radius_km':actual_radius,'trend_supported_area_pct':100*supported_area/total_area if total_area else 0,
            'quality_supported_area_pct':100*quality_area/total_area if total_area else 0,
            'subsidence_supported_area_pct':100*sub_area/total_area if total_area else 0,
            'overlap_supported_area_pct':100*overlap_area/total_area if total_area else 0,
            'current_supported_mcm':supported_volume if supported_volume_area else None,
            'current_unknown_mcm':max(0,analytic-supported_volume) if analytic is not None else None,
            'volume_factor':volume_factor,'used_decline_limit_m_year':used_decline,'used_subsidence_limit_mm_year':used_sub if not cumulative else None,
            'used_aligned_decline_limit_m_year':used_aligned if not cumulative else None,
            'used_cumulative_subsidence_limit_mm':used_sub if cumulative else None,
            'used_cumulative_decline_limit_m':used_aligned if cumulative else None,
            'subsidence_comparison_units':{'groundwater':'m' if cumulative else 'm/year','land':'mm' if cumulative else 'mm/year'},
            'relative_decline_criterion':decline_limit is None,'relative_subsidence_criterion':selected_sub_limit is None,
            'priority_counts':counts,'priority_areas_km2':[v/1e6 for v in areas],'overlap_counts':overlap_counts,
            'backtest_mae_m':sum(backtest)/len(backtest) if backtest else None,'backtest_predictions':len(backtest),
            'subsidence':sub_audit,'quality':{k:v for k,v in q.items() if k!='cells'},'forecasts':forecast,
            'notes':['روند آیندهٔ هر پیزومتر فقط از شهریورهای مشاهده‌شده در پنجرهٔ انتخابی و با مشاهده در انتهای دوره ساخته می‌شود؛ دادهٔ گمشده یا خشکی بازسازی نمی‌شود.',
                     'مسیر آینده ادامهٔ روند با لنگر آخرین تراز است؛ اثر سیاست برداشت، اقلیم یا تغذیه را شبیه‌سازی نمی‌کند.',
                     'دامنهٔ حساسیت از صدک‌های ۱۰ و ۹۰ شیب‌های جفتی است؛ فاصلهٔ اطمینان ۹۵٪ یا احتمال عبور از آستانه نیست.',
                     'آزمون زمانی، پیش‌بینی مشاهدهٔ بعدی با داده‌های قبل از آن است؛ اعتبار افق ۲۵ ساله را تأیید نمی‌کند.',
                     ('پهنه‌بندی با روش منتخب داده‌های آبخوان تا مرز پلیگون ادامه دارد؛ بیرون پوش نقاط برآورد مکانی است، نه مشاهده یا مرز هیدرولیکی.' if spatial else 'پشتیبانی مکانی داخل پوش محدب و شعاع انتخابی یا دو برابر میانهٔ نزدیک‌ترین فاصلهٔ چاه‌هاست؛ مدل جریان و مرز هیدرولیکی نیست.'),
                     'حجم آینده فقط برای پیکسل‌های دارای روند، Sy و کف معتبر جمع می‌شود؛ آیندهٔ بخش فاقد پوشش نامشخص می‌ماند.',
                     'حجم روی شبکهٔ نمایشی با ضریب مشترک به حجم محاسبات اصلی در تاریخ پایان منطبق شده است؛ بالاآمدن نمایشی کف در محاسبه نیست.',
                     'تراز خطی ممکن است زیر کف برون‌یابی شود؛ ضخامت و حجم در صفر قطع می‌شوند و ادامهٔ خط، پیش‌بینی تراز فیزیکی نیست.',
                     'نقشهٔ اولویت، غربالگری با معیارهای قابل تغییر است؛ صدک نسبی به معنی حد ایمنی نیست. نبود کیفیت به معنی مناسب‌بودن نیست.',
                     'کیفیت، وضعیت دورهٔ نمونه‌برداری است و روند آیندهٔ شوری پیش‌بینی نمی‌شود.',
                     ('نشست تجمعی با اختلاف مشاهدات ابتدا و انتهای پنجرهٔ منبع مقایسه می‌شود؛ دقت زمانی سالانه است و ماه واقعی مشاهدات آب ثبت شده است.' if cumulative else 'فرونشست از فایل مستقل است؛ برای نقشهٔ هم‌مکانی، روند تراز جداگانه در همان دورهٔ سال آبی لایهٔ تغییرشکل برازش می‌شود.'),
                     'هم‌مکانی با افت، رابطهٔ علّی یا افت ظرفیت ذخیره را اثبات نمی‌کند. مؤلفهٔ خط دید به قائم تبدیل نمی‌شود.']}
    return {'report':report,'plan_maps':maps,'wells':well_report}


def management_from_current(feature_index, options):
    if not _last_analysis:
        raise ValueError('ابتدا مدل آبخوان را محاسبه کنید.')
    prepare(feature_index)
    prepared=_prepared[feature_index]
    if (_last_analysis['aquifer']['name']!=prepared['summary']['name'] or
        _last_analysis['aquifer']['mahdoude']!=prepared['summary']['mahdoude']):
        raise ValueError('مدل فعال با آبخوان انتخابی یکسان نیست.')
    selected={(w['name'],w['lon'],w['lat']) for w in _last_analysis['wells']['points']}
    current=[w for w in prepared['current'].values() if (w['name'],w['lon'],w['lat']) in selected]
    keys={w['key'] for w in current}
    series={key:[] for key in keys}
    for (key,year,month),depth in _readings.items():
        if key in series:
            series[key].append((year,month,depth))
    histories=[{'name':w['name'],'lon':w['lon'],'lat':w['lat'],
                'records':[{'water_year':year if month>=7 else year-1,'year':year,'month':month,
                            'ordinal':year*12+month,'level':w['ground']-depth} for year,month,depth in series[w['key']]]} for w in current]
    result=management_analysis(_last_analysis,histories,options)
    result['histories']=histories
    result['report']['network_selection']={'basis':'same_wells_as_base_volume_comparison','selected_wells':len(current),'all_current_wells':len(prepared['current'])}
    return result

"""Shared aquifer-domain IDW/Thiessen/thin-plate Spline, run only in Pyodide."""
import math
import heapq


def sp_config(raw=None):
    raw=raw or {};method=raw.get('method',raw.get('spatial_method','idw'))
    if method not in ('idw','spline','thiessen'):raise ValueError('روش مکانی باید IDW، Spline یا تیسن باشد.')
    smooth=float(raw.get('spline_smoothing',0));power=float(raw.get('power',2));neighbors=int(raw.get('neighbors',8))
    if not math.isfinite(smooth) or smooth<0:raise ValueError('هموارسازی Spline باید نامنفی باشد.')
    if not math.isfinite(power) or power<=0 or neighbors<1:raise ValueError('تنظیمات همسایه و توان IDW معتبر نیست.')
    return {'method':method,'spline_smoothing':smooth,'power':power,'neighbors':neighbors,'coverage':'aquifer'}


def sp_sampler(points,fields,raw=None):
    """Interpolate finite source values over the requested domain; never substitute methods."""
    from shapely.geometry import MultiPoint,Point
    config=sp_config(raw);merged={}
    for p in points:
        if all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) for k in ['lon','lat',*fields]):
            merged.setdefault((p['lon'],p['lat']),[]).append(p)
    points=[{'lon':x,'lat':y,'name':' / '.join(str(p.get('name','')) for p in group),
             **{k:sum(p[k] for p in group)/len(group) for k in fields}} for (x,y),group in sorted(merged.items())]
    audit={**config,'point_count':len(points),'kernel':'thin_plate_spline' if config['method']=='spline' else None,
           'coordinate_metric':'local kilometres at mean source latitude','spline_neighbors':min(64,len(points)) if len(points)>64 else None,
           'scope':'full selected aquifer polygon; queries are clipped by the caller','missing_source':'No invented source values; spatial estimates identified separately.'}
    if not points:
        audit['available']=False;audit['reason']='no_valid_source_points'
        return lambda x,y:{'values':None,'extrapolated':False,'nearest_km':None,'nearest_name':None,'overshoot':False},audit
    lat=sum(p['lat'] for p in points)/len(points);sx=111.32*math.cos(math.radians(lat));x0,y0=points[0]['lon'],points[0]['lat']
    xy=[((p['lon']-x0)*sx,(p['lat']-y0)*111.32) for p in points]
    hull=MultiPoint(xy).convex_hull
    def tree(indices,depth=0):
        if not indices:return None
        axis=depth%2;indices.sort(key=lambda i:xy[i][axis]);mid=len(indices)//2
        return indices[mid],axis,tree(indices[:mid],depth+1),tree(indices[mid+1:],depth+1)
    root=tree(list(range(len(points))));predict=None
    if config['method']=='spline':
        if len(points)<3 or hull.geom_type!='Polygon':
            audit.update(available=False,reason='spline_requires_three_noncollinear_points')
            return lambda x,y:{'values':None,'extrapolated':False,'nearest_km':None,'nearest_name':None,'overshoot':False},audit
        import numpy as np
        from scipy.interpolate import RBFInterpolator
        try:
            fit=RBFInterpolator(np.array(xy),np.array([[p[k] for k in fields] for p in points]),kernel='thin_plate_spline',degree=1,
                                smoothing=config['spline_smoothing'],neighbors=audit['spline_neighbors'])
            predict=lambda p:fit(np.array([p]))[0].tolist()
        except (ValueError,ArithmeticError,np.linalg.LinAlgError) as error:raise ValueError('برازش Spline ممکن نشد؛ پراکندگی نقاط یا هموارسازی را بررسی کنید.') from error
    bounds={k:(min(p[k] for p in points),max(p[k] for p in points)) for k in fields}
    audit.update(available=True,reference_latitude=lat)
    def sample(lon,lat):
        target=((lon-x0)*sx,(lat-y0)*111.32);heap=[];count=min(config['neighbors'],len(points))
        def visit(node):
            if node is None:return
            i,axis,left,right=node;delta=target[axis]-xy[i][axis];near,far=(left,right) if delta<0 else (right,left)
            visit(near);d=(target[0]-xy[i][0])**2+(target[1]-xy[i][1])**2
            candidate=(-d,-i)
            if len(heap)<count:heapq.heappush(heap,candidate)
            elif candidate>heap[0]:heapq.heapreplace(heap,candidate)
            if len(heap)<count or delta*delta<=-heap[0][0]:visit(far)
        visit(root);chosen=sorted((-d,-i) for d,i in heap);d,index=chosen[0]
        if config['method']=='spline':
            try:values=dict(zip(fields,predict(target)))
            except (ValueError,ArithmeticError) as error:raise ValueError('پراکندگی همسایه‌های Spline کافی نیست؛ بدون تغییر پنهانی روش، نقاط یا هموارسازی را اصلاح کنید.') from error
        elif config['method']=='thiessen' or d<1e-16:values={k:points[index][k] for k in fields}
        else:
            weights=[(d/max(dist,1e-16))**(config['power']/2) for dist,i in chosen];total=sum(weights)
            values={k:sum(points[i][k]*w for (dist,i),w in zip(chosen,weights))/total for k in fields}
        if not all(math.isfinite(v) for v in values.values()):values=None
        return {'values':values,'extrapolated':not hull.covers(Point(target)),'nearest_km':math.sqrt(d),
                'nearest_name':points[index].get('name'),
                'overshoot':bool(values and config['method']=='spline' and any(v<bounds[k][0]-1e-10 or v>bounds[k][1]+1e-10 for k,v in values.items()))}
    return sample,audit


def sp_raster_surface(query,audit,cells,raw):
    """Resample measured raster cell means, preserving source coverage as provenance."""
    original={};points=[];cumulative=bool(audit.get('cumulative'));key='cumulative' if cumulative else 'rate'
    for c in cells:
        result=query(c['lon'],c['lat'],c['polygons']);original[(c['lon'],c['lat'])]=result
        v=result.get(key) if isinstance(result,dict) else result
        if v is not None:points.append({'lon':c['lon'],'lat':c['lat'],'value':v})
    sampler,spatial=sp_sampler(points,['value'],raw)
    duration=audit.get('duration_years')
    def sampled(lon,lat,*args):
        result=sampler(lon,lat);values=result['values'];value=values['value'] if values else None
        src=original.get((lon,lat)) or {};rate=value/duration if cumulative and value is not None and duration else value if not cumulative else None
        return {'rate':rate,'cumulative':value if cumulative else None,'coverage_pct':src.get('coverage_pct',0),
                'estimated':src.get(key) is None or result['extrapolated'],'spatial_method':spatial['method'],'spline_overshoot':result['overshoot']}
    return sampled,{**audit,'spatial':spatial,'raster_sampling':'selected spatial method of valid clipped model-cell source means',
                    'raster_sampling_note':'Source NoData is not zero. Missing model cells are spatial estimates with the selected method; original source coverage is retained.'}

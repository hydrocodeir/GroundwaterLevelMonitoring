"""Selectable temporal windows and spatial methods, executed in browser Pyodide.

The host supplies the shared management fit/support functions. No files or
regional constants are read here; all inputs belong to the active user model.
"""
import math
from copy import deepcopy
from statistics import median


def tr_period(mode, custom, years, end):
    years=sorted(set(int(y) for y in years if y<=end))
    if mode=='all':start=years[0] if years else end
    else:
        value=custom if mode=='custom' else mode
        try:count=float(value)
        except (ValueError,TypeError):raise ValueError('طول دورهٔ روند باید عدد صحیح باشد.')
        if not math.isfinite(count) or count!=int(count) or not 3<=count<=200:
            raise ValueError('طول دورهٔ روند باید بین ۳ تا ۲۰۰ سال باشد.')
        start=end-int(count)+1
    return {'mode':mode,'start_water_year':start,'end_water_year':end,'requested_years':end-start+1}


def tr_surface(points,cells,fields,scenario,settings,support):
    """Same support mask for all methods; full domain is an explicit choice."""
    method=scenario.get('spatial_method','idw')
    if 'sp_sampler' in globals():
        sampler,audit=sp_sampler(points,fields,{'method':method,'spline_smoothing':scenario.get('spline_smoothing',0),'neighbors':settings.get('neighbors',8),'power':settings.get('power',2)})
        guard,radius=support(points,settings.get('support_km'),settings.get('neighbors',8),settings.get('power',2),extrapolate=True)
        values=[]
        for c in cells:
            v=sampler(c['lon'],c['lat']);reasons=guard.reasons(c['lon'],c['lat'])
            out=v['values']
            if out and 'slope' in fields and 'low' in fields:out['low'],out['high']=min(out.values()),max(out.values())
            values.append({'values':out,'reasons':reasons,'nearest_km':v['nearest_km'],'nearest_name':v['nearest_name'],'spline_overshoot':v['overshoot']})
        return values,{**audit,'support_radius_km':radius,'spline_overshoot_cells':sum(v['spline_overshoot'] for v in values)}
    if method not in ('idw','spline','thiessen'):raise ValueError('روش مکانی روند معتبر نیست.')
    merged={}
    for p in points:merged.setdefault((p['lon'],p['lat']),[]).append(p)
    points=[{'lon':x,'lat':y,'name':' / '.join(str(p.get('name','')) for p in group),**{k:sum(p[k] for p in group)/len(group) for k in fields}} for (x,y),group in sorted(merged.items())]
    radius=settings.get('support_km');neighbors=int(settings.get('neighbors',8));power=float(settings.get('power',2))
    sampler,actual_radius=support(points,radius,neighbors,power,extrapolate=True)
    predict=None;spline_reason=None
    if method=='spline' and len(points)>=3:
        import numpy as np
        from scipy.interpolate import RBFInterpolator
        from shapely.geometry import MultiPoint
        lat=sum(p['lat'] for p in points)/len(points);sx=111.32*math.cos(math.radians(lat))
        origin=(points[0]['lon'],points[0]['lat'])
        xy=np.array([[(p['lon']-origin[0])*sx,(p['lat']-origin[1])*111.32] for p in points])
        if MultiPoint(xy).convex_hull.geom_type=='Polygon':
            smooth=float(scenario.get('spline_smoothing',0))
            if not math.isfinite(smooth) or smooth<0:raise ValueError('هموارسازی Spline باید نامنفی باشد.')
            try:
                fitted=RBFInterpolator(xy,np.array([[p[k] for k in fields] for p in points]),kernel='thin_plate_spline',degree=1,smoothing=smooth)
                predict=lambda x,y:fitted(np.array([[(x-origin[0])*sx,(y-origin[1])*111.32]]))[0].tolist()
            except (ValueError,ArithmeticError,np.linalg.LinAlgError) as error:raise ValueError('برازش Spline ممکن نشد؛ نقاط هم‌مکان یا هموارسازی را بررسی کنید.') from error
        else:spline_reason='not_2d_support'
    out=[];metric_cos=math.cos(math.radians(sum(p['lat'] for p in points)/len(points))) if points else 1
    for c in cells:
        weights=sampler(c['lon'],c['lat']);reasons=sampler.reasons(c['lon'],c['lat'])
        nearest=min(points,key=lambda p:((p['lon']-c['lon'])*metric_cos)**2+(p['lat']-c['lat'])**2) if points else None
        values=None
        if weights:
            if method=='spline' and predict:values=dict(zip(fields,predict(c['lon'],c['lat'])))
            elif method=='thiessen':values={k:nearest[k] for k in fields}
            elif method=='idw':values={k:sum(p[k]*w for p,w in weights) for k in fields}
        if values and not all(math.isfinite(v) for v in values.values()):values=None
        overshoot=bool(values and method=='spline' and any(values[k]<min(p[k] for p in points)-1e-10 or values[k]>max(p[k] for p in points)+1e-10 for k in fields))
        if values and 'slope' in fields and 'low' in fields:
            values['low'],values['high']=min(values['low'],values['slope'],values['high']),max(values['low'],values['high'],values['slope'])
        out.append({'values':values,'reasons':reasons,'nearest_km':sampler.distance_km(c['lon'],c['lat']),
                    'nearest_name':nearest.get('name') if nearest else None,'spline_overshoot':overshoot})
    return out,{'method':method,'point_count':len(points),'support_radius_km':actual_radius,'spline_kernel':'thin_plate_spline' if method=='spline' else None,
                'spline_smoothing':float(scenario.get('spline_smoothing',0)) if method=='spline' else None,'spline_reason':spline_reason,'spline_scope':'all distinct eligible points' if method=='spline' else None,
                'spline_overshoot_cells':sum(v['spline_overshoot'] for v in out),'neighbors':neighbors,'power':power}


def tr_quantity(management,scenario,fit,support):
    mode=scenario.get('quantity_window','current');method=scenario.get('spatial_method','idw')
    if mode=='current' and (method=='idw' or (management['report'].get('spatial') or {}).get('method')==method):
        r=management['report']
        return management,{'mode':'current','start_water_year':r.get('trend_start_water_year'),'end_water_year':r.get('trend_end_water_year'),'eligible_wells':r.get('eligible_wells'),'spatial_method':method,'spatial':r.get('spatial')}
    out=deepcopy(management);settings=out['report']['settings'];end=out['report']['trend_end_water_year']
    if mode=='current':
        points=[w for w in out.get('wells',[]) if w.get('eligible')]
        audit={'mode':mode,'start_water_year':out['report'].get('trend_start_water_year'),'end_water_year':end}
    else:
        histories=out.get('histories',[]);years=[r['water_year'] for w in histories for r in w['records'] if r.get('month',6)==6]
        audit=tr_period(mode,scenario.get('quantity_window_years',10),years,end)
        minimum=max(3,min(int(settings.get('min_observations',5)),max(3,audit['requested_years']-1)))
        points=[];reports=[]
        for w in histories:
            annual={}
            for r in w['records']:
                if r.get('month',6)==6 and audit['start_water_year']<=r['water_year']<=end:annual.setdefault(r['water_year'],[]).append(r['level'])
            series=sorted((y,median(v)) for y,v in annual.items());report={k:w[k] for k in ('name','lon','lat')};report.update(observations=len(series),eligible=False)
            if len(series)>=minimum and series[-1][0]==end and series[-1][0]-series[0][0]>=minimum-1 and len(series)/audit['requested_years']>=settings.get('coverage',.5):
                report.update(fit(series,settings.get('method','sen')),eligible=True);points.append(report)
            else:report['reason']='سابقهٔ شهریور یا مشاهدهٔ انتهای دورهٔ انتخابی کافی نیست.'
            reports.append(report)
        out['wells']=reports;out['report'].update(trend_start_water_year=audit['start_water_year'],eligible_wells=len(points),well_count=len(histories))
        errors=[e for p in points for e in p['backtest_errors']];out['report'].update(backtest_mae_m=sum(errors)/len(errors) if errors else None,backtest_predictions=len(errors))
        audit.update(min_observations=minimum,temporal_coverage=settings.get('coverage',.5),well_count=len(histories))
    values,spatial=tr_surface(points,out['plan_maps']['cells'],['slope','low','high'],scenario,settings,support)
    for c,v in zip(out['plan_maps']['cells'],values):
        supported=not v['reasons'] and v['values'] is not None
        for suffix,key in (('','slope'),('_low','low'),('_high','high')):
            c['management_slope'+suffix]=v['values'][key] if supported else None
            c['management_extended_slope'+suffix]=v['values'][key] if v['values'] is not None else None
        c.update(management_decline=-c['management_slope'] if supported else None,management_support_reasons=v['reasons'],management_nearest_well_km=v['nearest_km'],
                 management_nearest_well_name=v['nearest_name'],management_spline_overshoot=v['spline_overshoot'],management_spatial_estimated=bool(v['reasons'] and v['values']))
    out['report']['support_radius_km']=spatial['support_radius_km'];audit.update(eligible_wells=len(points),spatial=spatial,spatial_method=method)
    return out,audit


def tr_ec(records,cells,polygons,scenario,settings,end,fit,support):
    from shapely.geometry import Point,Polygon
    from shapely.ops import unary_union
    boundary=unary_union([Polygon(p[0],p[1:]) for p in polygons]);local=[r for r in records if r['water_year']<=end and boundary.covers(Point(r['lon'],r['lat']))]
    period=tr_period(scenario['quality_window'],scenario.get('quality_window_years',10),[r['water_year'] for r in local],end)
    groups={}
    for r in local:
        if period['start_water_year']<=r['water_year']<=end:
            key=(r['zone'],round(r['x']/100),round(r['y']/100)) if all(k in r for k in ('zone','x','y')) else (round(r['lon'],4),round(r['lat'],4))
            groups.setdefault(key,[]).append(r)
    points=[]
    for group in groups.values():
        annual={}
        for r in group:annual.setdefault(r['water_year'],[]).append(r['ec'])
        series=sorted((y,math.log(median(v))) for y,v in annual.items())
        if len(series)<3 or series[-1][0]!=end or series[-1][0]-series[0][0]<2 or len(series)/period['requested_years']<.5:continue
        fitted=fit(series,'sen');points.append({'lon':sum(r['lon'] for r in group)/len(group),'lat':sum(r['lat'] for r in group)/len(group),'name':group[0].get('name',''),'growth_log':fitted['slope']})
    values,spatial=tr_surface(points,cells,['growth_log'],scenario,settings,support)
    selected=[v['values']['growth_log'] if v['values'] is not None and (not v['reasons'] or scenario.get('spatial_coverage')=='aquifer') else None for v in values]
    return selected,{**period,'eligible_sites':len(points),'sites_considered':len(groups),'spatial':spatial,'estimator':'Theil–Sen of log annual median EC at persistent 100m coordinate bins; >=3 WY, final-year observation and >=50% temporal coverage',
                    'available':any(v is not None for v in selected)}


def tr_climate(series,scenario,end,fit):
    period=tr_period(scenario['climate_window'],scenario.get('climate_window_years',10),list(series),end)
    selected=sorted((y,*v) for y,v in series.items() if period['start_water_year']<=y<=end)
    audit={**period,'observed_years':len(selected),'available':False}
    if len(selected)<3 or selected[-1][0]!=end or len(selected)/period['requested_years']<.5:
        audit['reason']='برای ادامهٔ اقلیم، حداقل سه سال کامل و مشاهدهٔ انتهای دوره با پوشش زمانی کافی لازم است.';return audit
    audit.update(available=True,precip_slope_mm_year=fit([(y,p) for y,p,t in selected],'sen')['slope'],temp_slope_c_year=fit([(y,t) for y,p,t in selected],'sen')['slope'],
                 reference_precip_mm=selected[-1][1],reference_temp_c=selected[-1][2],estimator='Theil–Sen of complete aquifer-mean Persian water years; slopes applied as changes from scenario start, not added to the historical mean')
    return audit

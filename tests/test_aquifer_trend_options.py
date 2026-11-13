"""Analytical temporal and spatial scenarios, independent of dashboard rendering."""
import copy
import importlib.util
import math
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
mg=module('mg_options','frontend/assets/js/aquifer-management-compute.py')
tr=module('tr_options','frontend/assets/js/aquifer-trend-options.py')
lt=module('lt_options','frontend/assets/js/aquifer-lifetime-compute.py')
fixtures=module('tr_fixtures','tests/test_aquifer_management.py')
for name in ('mg_fit','mg_support','mg_subsidence'):setattr(lt,name,getattr(mg,name))
for name in ('tr_quantity','tr_ec','tr_climate'):setattr(lt,name,getattr(tr,name))


def model():
    data,histories=fixtures.inputs()
    for w in histories:
        for r in w['records']:r['month']=6
    managed=mg.management_analysis(data,histories,{});managed['histories']=histories
    return data,managed,histories


def scenario(**extra):
    return {'quantity_on':True,'quantity_type':'drawdown','quantity_limit':10,'horizon':20,**extra}


def test_four_year_and_full_period_use_different_observed_slopes_and_keep_original():
    d,m,h=model()
    for w in h:
        for r in w['records']:
            y=r['water_year'];r['level']=100+(1404-y)*3 if y>=1401 else 109+(1401-y)*.5
    original=copy.deepcopy(m)
    recent=lt.lifetime_analysis(d,m,None,scenario(quantity_window='4'))
    whole=lt.lifetime_analysis(d,m,None,scenario(quantity_window='all'))
    assert all(c['life_trend_m_year']==pytest.approx(-3) for c in recent['plan_maps']['cells'])
    assert recent['report']['area_target_years']==pytest.approx(10/3)
    assert whole['report']['area_target_years']>recent['report']['area_target_years']
    assert recent['report']['rate_audit']['quantity']['start_water_year']==1401
    assert whole['report']['rate_audit']['quantity']['start_water_year']==1395
    assert m==original


@pytest.mark.parametrize('method',['idw','spline','thiessen'])
def test_spatial_methods_have_real_distinct_behaviour_and_preserve_support(method):
    d,m,h=model()
    for w in h:
        rate=1+100*w['lon']+50*w['lat']
        for r in w['records']:r['level']=100+(1404-r['water_year'])*rate
    # A point inside the aquifer but outside the monitoring hull.
    c=copy.deepcopy(d['plan_maps']['cells'][0]);c.update(lon=.019,lat=.019);d['plan_maps']['cells'].append(c)
    m=mg.management_analysis(d,h,{});m['histories']=h
    base=scenario(spatial_method=method)
    strict=lt.lifetime_analysis(d,m,None,base)
    assert strict['plan_maps']['cells'][-1]['life_status']=='unknown'
    full=lt.lifetime_analysis(d,m,None,{**base,'spatial_coverage':'aquifer'})
    last=full['plan_maps']['cells'][-1]
    assert last['life_trend_source']=='extended_'+method
    assert last['life_trend_extrapolated']
    assert full['report']['spatial_coverage']['estimator']==method
    if method=='thiessen':
        assert last['life_trend_m_year']==pytest.approx(-3.7)
        assert last['life_nearest_well_name']=='Well 2'
    elif method=='spline':
        assert last['life_trend_m_year']==pytest.approx(-3.85)
        assert last['life_spline_overshoot']
        assert full['plan_maps']['cells'][0]['life_trend_m_year']==pytest.approx(-1.75)
    else:assert -3.7<last['life_trend_m_year']<-1.3


def test_no_silent_spatial_fallback_and_custom_period_validation():
    d,m,h=model()
    for w in h:w['lat']=.01
    m=mg.management_analysis(d,h,{});m['histories']=h
    r=lt.lifetime_analysis(d,m,None,scenario(spatial_method='spline',spatial_coverage='aquifer'))
    assert r['report']['unknown_area_pct']==100
    assert r['report']['spatial_coverage']['estimator']=='spline'
    for extra in ({'spatial_method':'fake'},{'quantity_window':'custom','quantity_window_years':2},{'quantity_window':'custom','quantity_window_years':4.5}):
        with pytest.raises(ValueError):lt.lifetime_analysis(d,m,None,scenario(**extra))


def quality_inputs(d,m,years=range(1401,1405)):
    records=[]
    for w in m['wells']:
        for y in years:records.append({'lon':w['lon'],'lat':w['lat'],'water_year':y,'ec':1000*1.1**(y-1401),'name':w['name']})
    q={'report':{'volume_dates':d['dates'],'aquifer':d['aquifer'],'quality_water_year':1404},'plan_maps':{'cells':[{**c,'quality_supported':True,'quality_ec':1000*1.1**3} for c in m['plan_maps']['cells']]}}
    return records,q


def test_ec_growth_is_fitted_from_same_sites_not_spatial_changes_or_future_data():
    d,m,_=model();records,q=quality_inputs(d,m)
    records+=[{'lon':60,'lat':35,'water_year':1404,'ec':999999},{'lon':.002,'lat':.002,'water_year':1408,'ec':999999}]
    s=scenario(quantity_on=False,quality_on=True,quality_limit=1500,crop_limit=2000,quality_window='4')
    r=lt.lifetime_analysis(d,m,q,s,source_context={'quality_records':records})
    expected=math.log(2000/(1000*1.1**3))/math.log(1.1)
    assert all(c['life_ec_growth_pct_year']==pytest.approx(10) for c in r['plan_maps']['cells'])
    assert r['report']['area_target_years']==pytest.approx(expected,abs=.002)
    assert r['report']['rate_audit']['quality']['eligible_sites']==4
    manual=lt.lifetime_analysis(d,m,q,{**s,'quality_window':'manual','ec_growth_pct':0})
    assert all(c['life_status']=='beyond' for c in manual['plan_maps']['cells'])


def test_missing_ec_history_stays_unknown_but_current_breach_is_provable():
    d,m,_=model();records,q=quality_inputs(d,m,years=[1404])
    s=scenario(quantity_on=False,quality_on=True,quality_limit=1500,crop_limit=2000,quality_window='10')
    r=lt.lifetime_analysis(d,m,q,s,source_context={'quality_records':records})
    assert r['report']['unknown_area_pct']==100
    assert all('quality_trend_missing' in c['life_unknown_reasons'] for c in r['plan_maps']['cells'])
    for c in q['plan_maps']['cells']:c['quality_ec']=3000
    breached=lt.lifetime_analysis(d,m,q,s,source_context={'quality_records':records})
    assert all(c['life_status']=='already' for c in breached['plan_maps']['cells'])


def annual_source(histories):
    text='longitude,latitude,water_year,rate_mm_year\n'
    for w in histories:
        for y in range(1395,1405):text+=f"{w['lon']},{w['lat']},{y},{10*(y-1394)}\n"
    return {'text':text,'file_name':'QA-annual.csv','value_kind':'rate','component':'vertical','direction':'down'}


def test_annual_subsidence_windows_change_rate_and_first_passage():
    d,m,h=model();source=annual_source(h)
    m=mg.management_analysis(d,h,{'subsidence':source});m['histories']=h
    assert m['report']['subsidence']['annual_rates']
    assert m['plan_maps']['cells'][0]['management_subsidence']==pytest.approx(55)
    s=scenario(quantity_on=False,subsidence_on=True,subsidence_limit=170,subsidence_window='4')
    recent=lt.lifetime_analysis(d,m,None,s,source_context={'subsidence_options':source})
    whole=lt.lifetime_analysis(d,m,None,{**s,'subsidence_window':'all'},source_context={'subsidence_options':source})
    assert recent['report']['area_target_years']==pytest.approx(2)
    assert whole['report']['area_target_years']==pytest.approx(170/55)
    assert all(c['life_subsidence_rate_mm_year']==pytest.approx(85) for c in recent['plan_maps']['cells'])
    assert recent['report']['rate_audit']['subsidence']['selected_years']==[1401,1402,1403,1404]


def test_cumulative_subsidence_cannot_generate_recent_annual_rates():
    d,m,_=model();m['report']['subsidence']={'component':'vertical','cumulative':True,'periods':[[1395,1404]],'duration_years':10}
    for c in m['plan_maps']['cells']:c['management_subsidence']=50
    r=lt.lifetime_analysis(d,m,None,scenario(quantity_on=False,subsidence_on=True,subsidence_limit=100,subsidence_window='4'),source_context={'subsidence_options':{'text':'longitude,latitude,cumulative_mm\n.01,.01,500\n'}})
    assert r['report']['unknown_area_pct']==100
    assert r['report']['rate_audit']['subsidence']['available'] is False
    assert all('subsidence_period_unavailable' in c['life_unknown_reasons'] for c in r['plan_maps']['cells'])


def test_climate_recent_trend_uses_complete_years_and_zero_start_change(monkeypatch):
    d,m,_=model()
    monkeypatch.setattr(lt,'lt_fit_climate',lambda *args:{'accepted':True,'reason':'QA calibration','lag_years':0,'baseline_precip_mm':400,'baseline_temp_c':15,
        'precip_range_mm':[300,500],'temp_range_c':[10,20],'beta_precip_m_per_mm':.01,'beta_temp_m_per_c':-.2})
    csv='water_year,precip_mm,temp_c\n'+''.join(f'{y},{400-10*(y-1401)},{15+.2*(y-1401)}\n' for y in range(1401,1405))
    r=lt.lifetime_analysis(d,m,None,scenario(climate_on=True,climate_window='4',horizon=10),climate_text=csv)
    audit=r['report']['rate_audit']['climate']
    assert audit['precip_slope_mm_year']==pytest.approx(-10)
    assert audit['temp_slope_c_year']==pytest.approx(.2)
    assert r['report']['curves'][0]['remaining_mcm']==pytest.approx(16)
    # dH = -t - .07 t²; the 10-m crossing has an analytic solution.
    expected=(-1+math.sqrt(1+2.8))/.14
    assert r['report']['area_target_years']==pytest.approx(expected,abs=.002)
    missing=csv.rsplit('1404,',1)[0]
    unknown=lt.lifetime_analysis(d,m,None,scenario(climate_on=True,climate_window='4'),climate_text=missing)
    assert not unknown['report']['climate']['accepted']
    assert unknown['report']['unknown_area_pct']==100

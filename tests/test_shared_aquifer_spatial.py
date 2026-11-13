"""Shared method, full polygon estimates and preserved source provenance."""
import importlib.util
import json
from pathlib import Path
import pytest
from test_aquifer_management import inputs

ROOT=Path(__file__).resolve().parents[1]
SHARED=(ROOT/'frontend/assets/js/aquifer-spatial.py').read_text('utf-8')


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    exec(SHARED,mod.__dict__);return mod


@pytest.mark.parametrize('method',['idw','thiessen','spline'])
def test_trends_and_point_subsidence_cover_boundary_halo_with_selected_method(method):
    mg=module('shared_management','frontend/assets/js/aquifer-management-compute.py');data,histories=inputs()
    for w in histories:w['lon']=.008 if w['lon']<.01 else .012;w['lat']=.008 if w['lat']<.01 else .012
    data['spatial']={'method':method,'spline_smoothing':0}
    text='longitude,latitude,rate_mm_year,start_water_year,end_water_year\n'+''.join(f"{w['lon']},{w['lat']},{20+i*5},1395,1404\n" for i,w in enumerate(histories))
    result=mg.management_analysis(data,histories,{'subsidence':{'text':text,'file_name':'sample.csv','component':'vertical','direction':'down'}})
    assert result['report']['trend_supported_area_pct']==pytest.approx(100)
    assert result['report']['subsidence_supported_area_pct']==pytest.approx(100)
    assert result['report']['spatial']['method']==method
    assert result['report']['subsidence']['spatial']['method']==method
    for c in result['plan_maps']['cells']:
        assert c['management_slope']==pytest.approx(-1)
        assert c['management_spatial_estimated'] and c['management_subsidence_estimated']
        assert c['management_spatial_method']==c['management_subsidence_method']==method
        assert c['management_subsidence'] is not None


def test_thiessen_is_nearest_point_and_spline_has_no_silent_degenerate_fallback():
    shared={};exec(SHARED,shared)
    points=[{'lon':x,'lat':y,'v':v} for x,y,v in [(0,0,1),(1,0,2),(0,1,4)]]
    sample,audit=shared['sp_sampler'](points,['v'],{'method':'thiessen'})
    assert sample(2,0)['values']['v']==2 and sample(2,0)['extrapolated']
    spline,audit=shared['sp_sampler'](points[:2],['v'],{'method':'spline'})
    assert not audit['available'] and spline(2,0)['values'] is None
    for bad in [{'method':'other'},{'method':'spline','spline_smoothing':-1}]:
        with pytest.raises(ValueError):shared['sp_sampler'](points,['v'],bad)


@pytest.mark.parametrize('method',['idw','thiessen','spline'])
def test_quality_uses_selected_method_in_validation_and_entire_aquifer(method):
    q=module('shared_quality','scripts/waterq_compute.py')
    ring=[[60,35],[60.5,35],[60.5,35.5],[60,35.5],[60,35]]
    text='longitude,latitude,ec,sar,year_persian,month_persian\n'
    for i in range(4):
        for j in range(4):text+=f'{60.10+i*.08},{35.10+j*.08},{1000+100*i+10*j},{3+i*.1},1405,6\n'
    audit=q.audit_quality(text,json.dumps({'features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[ring]}}]}))
    cells=[{'lon':60.01,'lat':35.01,'remaining_mcm':None},{'lon':60.49,'lat':35.49,'remaining_mcm':None}]
    data={'spatial':{'method':method,'spline_smoothing':0},'aquifer':{'name':'Test'},'dates':{'after':'1405-06','after_water_year':1404},
          'display_grid':{'polygons':[[ring]]},'metrics':{'drainable_after_mcm':None,'sy_mode':'constant','sy':None,'sy_min':None,'sy_max':None},
          'grid':{'bedrock_source':'schematic'},'wells':{'common':16},'pixel_water':None,
          'plan_maps':{'cells':cells,'extent':[60,35,60.5,35.5],'side_m':1000,'polygons':[[ring]]}}
    result=q.estimate_quality(data,audit['records'])
    assert result['report']['validation']['selected']==method
    assert list(result['report']['validation']['scores'])==[method]
    assert result['report']['validation']['spatially_estimated_cells']==2
    assert result['report']['spatial']['method']==method
    for c in result['plan_maps']['cells']:
        assert c['quality_supported'] and c['quality_spatial_estimated'] and c['quality_ec']>0
        assert c['quality_spatial_method']==method and c['quality_sar'] is not None
    assert result['report']['total_remaining_mcm'] is None
    json.dumps(result,allow_nan=False)


@pytest.mark.parametrize('method',['idw','thiessen','spline'])
def test_raster_source_gap_is_estimated_with_retained_original_coverage(method):
    shared={};exec(SHARED,shared)
    cells=[{'lon':x,'lat':y,'polygons':[]} for x,y in [(0,0),(1,0),(0,1),(1,1)]]
    def source(x,y,*args):return {'rate':None if x==y==1 else 10+x+y,'cumulative':None,'coverage_pct':0 if x==y==1 else 100}
    query,audit=shared['sp_raster_surface'](source,{'cumulative':False},cells,{'method':method})
    assert query(1,1)['rate'] is not None
    assert query(1,1)['estimated'] and query(1,1)['coverage_pct']==0
    assert query(0,0)['rate']==pytest.approx(10)
    assert audit['spatial']['method']==method


def test_imported_scenario_cannot_override_active_aquifer_method():
    mg=module('shared_mgmt','frontend/assets/js/aquifer-management-compute.py');lt=module('shared_life','frontend/assets/js/aquifer-lifetime-compute.py')
    trend=module('shared_trend','frontend/assets/js/aquifer-trend-options.py')
    for name in ['tr_quantity','tr_surface','tr_ec']:lt.__dict__[name]=getattr(trend,name)
    lt.mg_fit=mg.mg_fit;lt.mg_support=mg.mg_support
    data,histories=inputs();data['spatial']={'method':'thiessen','spline_smoothing':0}
    managed=mg.management_analysis(data,histories,{});managed['histories']=histories
    answer=lt.lifetime_analysis(data,managed,None,{'quantity_on':True,'quantity_type':'drawdown','quantity_limit':5,'spatial_method':'idw','spatial_coverage':'supported'})
    assert answer['report']['scenario']['spatial_method']=='thiessen'
    assert answer['report']['scenario']['spatial_coverage']=='aquifer'
    assert answer['report']['rate_audit']['quantity']['spatial_method']=='thiessen'

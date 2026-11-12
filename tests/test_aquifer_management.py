import copy
import importlib.util
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location('management',Path(__file__).resolve().parents[1]/'frontend/assets/js/aquifer-management-compute.py')
mg=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mg)


def inputs(rate=1.,floor=60.,sy=.1):
    ring=[[0,0],[.02,0],[.02,.02],[0,.02],[0,0]]
    locations=[(.002,.002),(.018,.002),(.018,.018),(.002,.018)]
    cells=[]
    for i,(lon,lat) in enumerate([(.005,.005),(.015,.005),(.015,.015),(.005,.015)]):
        cells.append({'lon':lon,'lat':lat,'area_m2':1e6,'after_msl':100.,'before_msl':110.,
                      'bedrock_msl':floor,'sy':sy,'remaining_mcm':(100-floor)*sy if floor is not None and sy is not None else None,
                      'saturated_m':100-floor if floor is not None else None,'polygons':[[ring]],'column':i,'row':0})
    histories=[{'name':f'Well {i}','lon':lon,'lat':lat,'records':[{'water_year':wy,'level':100+(1404-wy)*rate} for wy in range(1395,1405)]} for i,(lon,lat) in enumerate(locations)]
    data={'aquifer':{'name':'Any aquifer','mahdoude':'Any district'},'dates':{'after':'1405-06','after_water_year':1404},
          'metrics':{'drainable_after_mcm':sum(c['remaining_mcm'] for c in cells) if floor is not None and sy is not None else None},
          'plan_maps':{'cells':cells,'polygons':[[ring]],'extent':[0,0,.02,.02],'side_m':1000,'fields':{}}}
    return data,histories


def test_robust_and_ols_affine_trends_and_temporal_holdout():
    points=[(wy,100-(wy-1395)*.8) for wy in range(1395,1405)]
    for method in ('sen','ols'):
        fitted=mg.mg_fit(points,method)
        assert fitted['slope']==pytest.approx(-.8)
        assert fitted['backtest_mae_m']==pytest.approx(0,abs=1e-10)
        altered=mg.mg_fit(points[:-1]+[(1404,300)],method)
        assert altered['backtest_errors'][:-1]==pytest.approx(fitted['backtest_errors'][:-1])
        assert altered['backtest_errors'][-1]>100


def test_spatial_tree_matches_brute_force_neighbors_and_excludes_self():
    import math
    points=[(i%9*.7,i//9*1.3) for i in range(80)]
    query=mg.mg_nearest_tree(points)
    for target in ((1.13,2.27),(-1,5),points[15]):
        expected=sorted((math.dist(target,p),i) for i,p in enumerate(points))[:8]
        actual=query(target,8)
        assert [i for _,i in actual]==[i for _,i in expected]
        assert [d for d,_ in actual]==pytest.approx([d for d,_ in expected])
    assert query(points[15],1,exclude=15)[0][1]!=15


def test_forecasts_respond_to_horizons_sy_floor_and_keep_balance():
    data,history=inputs()
    result=mg.management_analysis(data,history,{'horizons':[3,7,25,50]})
    report=result['report']
    assert [f['horizon'] for f in report['forecasts']]==[3,7,25,50]
    assert report['eligible_wells']==4
    assert report['current_supported_mcm']==pytest.approx(16)
    assert report['current_unknown_mcm']==pytest.approx(0)
    assert [f['remaining_supported_mcm'] for f in report['forecasts']]==pytest.approx([14.8,13.2,6,0])
    assert report['forecasts'][-1]['long_extrapolation']
    changed=mg.management_analysis(*inputs(floor=70,sy=.2),{'horizons':[7]})
    assert changed['report']['forecasts'][0]['remaining_supported_mcm']==pytest.approx(18.4)
    assert data['plan_maps']['cells'][0].get('management_slope') is None
    for bad in ([0],[3.5],[]):
        with pytest.raises(ValueError):mg.management_analysis(data,history,{'horizons':bad})


@pytest.mark.parametrize('kind,value,years',[('saturated',30,10),('head',95,5),('drawdown',7,7)])
def test_threshold_definitions_use_each_cells_current_level_and_physical_floor(kind,value,years):
    result=mg.management_analysis(*inputs(),{'threshold_type':kind,'threshold':value,'urgent_years':years})
    for c in result['plan_maps']['cells']:
        assert c['management_critical_years']==pytest.approx(years)
        assert c['management_critical_water_year']==1404+years
        assert c['management_priority']==4


def test_rising_missing_threshold_and_unknown_floor_are_distinct():
    assert mg.mg_crossing(100,90,1)==(None,'not_crossed')
    assert mg.mg_crossing(80,90,None)==(0,'already')
    result=mg.management_analysis(*inputs(floor=None),{'threshold_type':'drawdown','threshold':5})
    assert result['plan_maps']['cells'][0]['management_critical_years']==pytest.approx(5)
    assert result['report']['forecasts'][0]['remaining_supported_mcm'] is None
    missing=mg.management_analysis(*inputs(),{})
    assert missing['plan_maps']['cells'][0]['management_critical_status']=='unknown'


def test_discontinued_missing_years_and_spatial_extrapolation_are_not_filled():
    data,history=inputs()
    for w in history:w['records']=w['records'][:-1]
    result=mg.management_analysis(data,history,{})
    assert result['report']['eligible_wells']==0
    assert result['report']['trend_supported_area_pct']==0
    assert all(c['management_slope'] is None for c in result['plan_maps']['cells'])
    assert all(f['mean_head_change_m'] is None for f in result['report']['forecasts'])
    data,history=inputs()
    for w in history:w['records']=[r for r in w['records'] if r['water_year']%2==0]
    result=mg.management_analysis(data,history,{'min_observations':5})
    assert result['report']['eligible_wells']==4
    assert result['wells'][0]['observations']==5
    data['plan_maps']['cells'][0]['lon']=.0199
    result=mg.management_analysis(data,history,{'min_observations':5})
    assert result['plan_maps']['cells'][0]['management_slope'] is None


def quality_for(data):
    return {'volume_end':'1405-06','thresholds':{'drinking_ec_uScm':1500},
            'cells':[{'lon':c['lon'],'lat':c['lat'],'quality_supported':True,'quality_ec':4000,'quality_zone_code':2} for c in data['plan_maps']['cells']]}


def test_priority_exposes_unknown_quality_and_updates_with_criteria():
    data,history=inputs()
    result=mg.management_analysis(data,history,{'decline_limit':.5})
    assert all(c['management_priority']==7 for c in result['plan_maps']['cells'])
    q=quality_for(data)
    result=mg.management_analysis(data,history,{'decline_limit':.5,'quality':q})
    assert all(c['management_priority']==3 for c in result['plan_maps']['cells'])
    result=mg.management_analysis(data,history,{'decline_limit':2,'quality':q})
    assert all(c['management_priority']==2 for c in result['plan_maps']['cells'])
    for cell in q['cells']:cell['quality_zone_code']=4
    result=mg.management_analysis(data,history,{'quality_mode':'either','quality':q})
    assert all(c['management_quality_problem'] is True for c in result['plan_maps']['cells'])
    result=mg.management_analysis(data,history,{'quality_mode':'crop','quality':q})
    assert all(c['management_quality_problem'] is None for c in result['plan_maps']['cells'])
    no_trends=copy.deepcopy(history)
    for well in no_trends:well['records']=[]
    result=mg.management_analysis(data,no_trends,{'quality_mode':'either','quality':q})
    assert all(c['management_priority']==8 for c in result['plan_maps']['cells'])
    q['volume_end']='1404-06'
    with pytest.raises(ValueError):mg.management_analysis(data,history,{'quality':q})


def sub_csv(history,rate=-12,end=1404):
    return 'longitude,latitude,rate_mm_year,start_water_year,end_water_year\n'+'\n'.join(f"{w['lon']},{w['lat']},{rate},1402,{end}" for w in history)


def test_independent_subsidence_sign_period_and_bivariate_map():
    data,history=inputs()
    sub={'text':sub_csv(history),'component':'vertical','direction':'up','file_name':'independent.csv'}
    result=mg.management_analysis(data,history,{'decline_limit':.5,'subsidence_limit':10,'subsidence':sub})
    assert all(c['management_subsidence']==pytest.approx(12) for c in result['plan_maps']['cells'])
    assert all(c['management_overlap']==3 for c in result['plan_maps']['cells'])
    assert result['report']['overlap_supported_area_pct']==100
    sub['text']=sub_csv(history,end=1405)
    result=mg.management_analysis(data,history,{'subsidence':sub})
    assert result['report']['subsidence']['period_excluded']==4
    assert all(c['management_subsidence'] is None for c in result['plan_maps']['cells'])
    assert all(c['management_overlap']==4 for c in result['plan_maps']['cells'])
    sub['text']=sub_csv(history);sub['component']='los'
    result=mg.management_analysis(data,history,{'subsidence':sub})
    assert result['report']['subsidence']['component']=='los'
    assert result['plan_maps']['cells'][0]['management_subsidence']==pytest.approx(12)


def test_subsidence_requires_real_units_geometry_period_and_consistent_records():
    data,history=inputs()
    sub={'text':sub_csv(history),'component':'vertical','direction':'down'}
    sub['text']+='\n.002,.002,100,1402,1404'
    with pytest.raises(ValueError):mg.management_analysis(data,history,{'subsidence':sub})
    sub['text']='lon,lat,speed\n0,0,12'
    with pytest.raises(ValueError):mg.management_analysis(data,history,{'subsidence':sub})
    sub['text']='longitude,latitude,rate_mm_year\n0,0,12'
    with pytest.raises(ValueError):mg.management_analysis(data,history,{'subsidence':sub})


def test_overlap_refits_water_trend_to_the_actual_subsidence_period():
    data,history=inputs()
    for well in history:
        for row in well['records']:
            wy=row['water_year']
            row['level']=110-(wy-1395) if wy<1402 else 100+(wy-1402)*2
    source={'text':sub_csv(history,rate=12),'component':'vertical','direction':'down'}
    result=mg.management_analysis(data,history,{'subsidence':source,'decline_limit':.5,'subsidence_limit':10})
    for cell in result['plan_maps']['cells']:
        assert cell['management_decline']>0
        assert cell['management_subsidence_decline']==pytest.approx(-2)
        assert cell['management_overlap']==2


def test_browser_adapter_uses_september_and_start_named_persian_water_year(monkeypatch):
    data,history=inputs()
    data['wells']={'points':[{k:w[k] for k in ('name','lon','lat')} for w in history]}
    current={str(i):{**w,'ground':120,'key':str(i)} for i,w in enumerate(history)}
    readings={(key,wy+1,6):120-(100+(1404-wy)) for key in current for wy in range(1395,1405)}
    readings.update({(key,1405,7):500 for key in current})
    monkeypatch.setattr(mg,'_last_analysis',data,raising=False)
    monkeypatch.setattr(mg,'prepare',lambda _:None,raising=False)
    monkeypatch.setattr(mg,'_prepared',{0:{'summary':{'name':'Any aquifer','mahdoude':'Any district'},'current':current}},raising=False)
    monkeypatch.setattr(mg,'_readings',readings,raising=False)
    monkeypatch.setattr(mg,'CURRENT_MONTH',6,raising=False)
    result=mg.management_from_current(0,{})
    assert result['report']['trend_end_water_year']==1404
    assert result['wells'][0]['slope']==pytest.approx(-1)

"""Calendar and missing-data checks for the browser-side GEE climate builder."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('climate_gee',ROOT/'scripts/climate_gee_compute.py')
climate=importlib.util.module_from_spec(spec);spec.loader.exec_module(climate)
GEO={'features':[{'type':'Feature','properties':{'AQUIFER':'مشهد'},'geometry':{'type':'Polygon','coordinates':[[[59,36],[60,36],[60,37],[59,37],[59,36]]]}}]}
CATALOG={'precip':{'first':'1981-01-01','last':'2026-09-30'},'temp':{'first':'1950-01-02','last':'2026-11-05'}}
APP=(ROOT/'frontend/assets/js/aquifer-lifetime-compute.py').read_text('utf-8')


def records(plan):
    return [{**p,**{k+'_images':p['expected_days'] for k in climate.SOURCES},
             **{k+'_unique_days':p['expected_days'] for k in climate.SOURCES},
             'precip_stats':{'days_min':p['expected_days'],'days_max':p['expected_days'],'valid_area_sum':400.,'total_area_sum':400.,'value_area_sum':100000.},
             'temp_stats':{'days_min':p['expected_days'],'days_max':p['expected_days'],'valid_area_sum':200.,'total_area_sum':200.,'value_area_sum':57230.}}
            for p in plan['periods']]


def test_plan_uses_complete_common_persian_water_years_and_retains_boundary():
    plan=climate.plan_climate(GEO,CATALOG)
    assert len(plan['periods'])==45
    assert plan['periods'][0]=={'water_year':1360,'start':'1981-09-23','end_exclusive':'1982-09-23','expected_days':365}
    assert plan['periods'][-1]['water_year']==1404
    assert plan['periods'][-1]['end_exclusive']=='2026-09-23'
    assert {p['expected_days'] for p in plan['periods']}=={365,366}
    assert plan['feature']==GEO['features'][0]


def test_temporal_and_spatial_completeness_rejects_missing_not_zero():
    plan=climate.plan_climate(GEO,CATALOG,start_wy=1400,end_wy=1404);raw=records(plan)
    raw[1]['precip_images']-=1
    raw[2]['temp_stats']['days_min']-=1
    raw[3]['precip_stats']['valid_area_sum']=390.
    built=climate.build_climate(plan,raw,'QA',APP)
    result=json.loads(built['files']['MASHHAD_CLIMATE_METADATA.json'])
    assert result['quality_control']['excluded_water_years']==[1401,1402,1403]
    assert result['complete_water_years']==2
    lines=built['files']['MASHHAD_CLIMATE_WY.csv'].splitlines()
    assert lines==['water_year,precip_mm,temp_c','1400,250.0,13.0','1404,250.0,13.0']
    assert result['dashboard_validation']['complete_water_years']==2


def test_leap_year_calendar_includes_the_extra_day():
    plan=climate.plan_climate(GEO,CATALOG,start_wy=1399,end_wy=1399)
    assert plan['periods'][0]['expected_days']==366
    assert plan['periods'][0]['start']=='2020-09-22'
    assert plan['periods'][0]['end_exclusive']=='2021-09-23'
    raw=records(plan)
    assert climate.build_climate(plan,raw,'QA',APP)['metadata']['complete_water_years']==1


def test_duplicate_or_wrong_period_records_are_rejected():
    plan=climate.plan_climate(GEO,CATALOG,start_wy=1400,end_wy=1400);raw=records(plan)
    with pytest.raises(ValueError,match='Duplicate'):climate.build_climate(plan,raw+raw,'QA',APP)
    invalid=copy.deepcopy(raw);invalid[0]['start']='2020-01-01'
    with pytest.raises(ValueError,match='dates differ'):climate.build_climate(plan,invalid,'QA',APP)


@pytest.mark.parametrize('bad',[None,float('nan'),float('inf')])
def test_nonfinite_source_sum_does_not_create_a_numeric_temperature(bad):
    plan=climate.plan_climate(GEO,CATALOG,start_wy=1400,end_wy=1400);raw=records(plan)
    raw[0]['temp_stats']['value_area_sum']=bad
    with pytest.raises(ValueError,match='No complete'):climate.build_climate(plan,raw,'QA',APP)

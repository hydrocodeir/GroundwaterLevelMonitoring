"""Analytical crossings and failure modes of the browser-only scenario engine."""
import copy
import importlib.util
import io
from pathlib import Path
import struct

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
lt=module('lifetime','frontend/assets/js/aquifer-lifetime-compute.py')
mg=module('management','frontend/assets/js/aquifer-management-compute.py')
fixtures=module('fixtures','tests/test_aquifer_management.py')

def model(**kwargs):
    data,histories=fixtures.inputs(**kwargs)
    managed=mg.management_analysis(data,histories,{})
    managed['histories']=histories
    for w in histories:
        for r in w['records']:r['month']=6
    return data,managed

def scenario(**kwargs):
    return dict(quantity_on=True,quantity_type='saturated',quantity_limit=30,horizon=50,**kwargs)

def test_crossings_conserve_inputs_and_sy_only_changes_prescribed_volume():
    d,m=model();before=copy.deepcopy(m)
    result=lt.lifetime_analysis(d,m,None,scenario())
    assert [c['life_years'] for c in result['plan_maps']['cells']]==pytest.approx([10]*4)
    assert result['report']['area_target_years']==pytest.approx(10)
    assert result['report']['curves'][10]['remaining_mcm']==pytest.approx(12)
    changed=lt.lifetime_analysis(d,m,None,scenario(sy_factor=2))
    assert changed['report']['area_target_years']==pytest.approx(10)
    assert changed['report']['curves'][10]['remaining_mcm']==pytest.approx(24)
    assert m==before

def storage_scenario(percent=25,**kwargs):
    return {**scenario(),'quantity_type':'storage_loss_pct','quantity_limit':percent,**kwargs}


def coverage_model():
    data,histories=fixtures.inputs()
    for i,w in enumerate(histories):
        for r in w['records']:r['level']=100+(1404-r['water_year'])*(.5+i*.5)
    # Both points are inside the aquifer; one is outside the well hull and the
    # other is inside it but beyond the explicitly selected one-km radius.
    for lon,lat in ((.0005,.01),(.01,.01)):
        c=copy.deepcopy(data['plan_maps']['cells'][0]);c.update(lon=lon,lat=lat,area_m2=2e6)
        data['plan_maps']['cells'].append(c)
    managed=mg.management_analysis(data,histories,{'support_km':1})
    return data,managed


def test_full_aquifer_extension_retains_supported_values_and_labels_extrapolation():
    d,m=coverage_model();original=copy.deepcopy(m)
    strict=lt.lifetime_analysis(d,m,None,storage_scenario())
    full=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer',sensitivity_on=True))
    assert strict['report']['unknown_area_pct']==50
    assert full['report']['unknown_area_pct']==0
    assert full['report']['spatial_coverage']['area_pct']=={'within_support':50,'extrapolated':50,'unavailable':0,'manual':0}
    assert full['report']['spatial_coverage']['cells']['extrapolated']==2
    for a,b in zip(strict['plan_maps']['cells'][:4],full['plan_maps']['cells'][:4]):
        assert a['life_years']==b['life_years']
        assert a['management_slope']==b['management_slope']
        assert not b['life_trend_extrapolated']
    outside,beyond=full['plan_maps']['cells'][-2:]
    assert outside['life_trend_support_reasons']==['outside_trend_hull']
    assert beyond['life_trend_support_reasons']==['beyond_trend_radius']
    for c in (outside,beyond):
        assert c['life_support']==1 and c['life_trend_source']=='extended_idw'
        assert -2<=c['management_slope']<=-.5
        assert c['management_slope_low']<=c['management_slope']<=c['management_slope_high']
        assert c['life_trend_nearest_km']>0
        assert c['life_unknown_reasons']==[]
        assert c['life_sensitivity_unknown'] is False
    assert m==original  # Other management views and subsequent strict runs stay strict.


def test_extension_does_not_fill_floor_sy_quality_or_subsidence():
    d,m=coverage_model();m['plan_maps']['cells'][-1]['sy']=None
    m['plan_maps']['cells'][-2]['bedrock_msl']=None
    r=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer'))
    assert r['report']['unknown_area_pct']==50
    assert r['plan_maps']['cells'][-1]['life_unknown_reasons']==['sy_missing']
    assert r['plan_maps']['cells'][-2]['life_unknown_reasons']==['bedrock_missing']
    q=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer',quality_on=True,quality_limit=1500,crop_limit=3000))
    assert q['report']['unknown_area_pct']==100
    assert all('quality_missing' in c['life_unknown_reasons'] for c in q['plan_maps']['cells'])
    sub=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer',subsidence_on=True,subsidence_limit=100))
    assert sub['report']['unknown_area_pct']==100


@pytest.mark.parametrize('network',['empty','collinear'])
def test_extension_requires_noncollinear_eligible_network(network):
    d,h=fixtures.inputs()
    for w in h:
        if network=='empty':w['records']=[]
        else:w['lat']=.01
    m=mg.management_analysis(d,h,{})
    r=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer'))
    assert r['report']['unknown_area_pct']==100
    assert r['report']['spatial_coverage']['area_pct']['unavailable']==100
    assert not any(c['life_trend_extrapolated'] for c in r['plan_maps']['cells'])


def test_manual_rate_is_separate_from_spatial_extension_and_support_tiff_is_auditable():
    import json
    from PIL import Image
    d,m=coverage_model()
    r=lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='aquifer',manual_drop_m_year=2))
    assert r['report']['spatial_coverage']['area_pct']['manual']==100
    assert all(c['life_support']==3 and not c['life_trend_extrapolated'] and c['life_trend_m_year']==-2 for c in r['plan_maps']['cells'])
    with Image.open(io.BytesIO(lt.lifetime_tiff(r,'life_support'))) as image:
        metadata=json.loads(image.tag_v2[270])
        assert metadata['field']=='life_support'
        assert metadata['support_codes']['extrapolated']==1
        assert metadata['spatial_coverage']['area_pct']['manual']==100
    with pytest.raises(ValueError,match='پوشش مکانی'):
        lt.lifetime_analysis(d,m,None,storage_scenario(spatial_coverage='unknown'))


def test_relative_storage_limit_and_preview_match_actual_crossing():
    d,m=model()  # initial column 40 m, Sy=.1, area 1 km2 per cell, slope -1.
    r=lt.lifetime_analysis(d,m,None,storage_scenario())
    ref=r['report']['quantity_reference']
    assert ref==lt.lifetime_quantity_reference(d,m,storage_scenario())
    assert ref['initial_storage_mcm']==pytest.approx(16)
    assert ref['target_storage_mcm']==pytest.approx(12)
    assert ref['equivalent_loss_mcm']==pytest.approx(4)
    assert ref['remaining_pct']==75
    assert ref['equivalent_drawdown_median_m']==pytest.approx(10)
    assert r['report']['area_target_years']==pytest.approx(10)
    assert all(c['life_quantity_cutoff_msl']==pytest.approx(90) for c in r['plan_maps']['cells'])


def test_storage_curve_uses_one_spatial_domain_even_at_zero():
    d,m=model();m['plan_maps']['cells'][0]['management_slope']=None
    r=lt.lifetime_analysis(d,m,None,storage_scenario())
    assert r['report']['curves'][0]['remaining_mcm']==pytest.approx(12)
    assert r['report']['curves'][1]['remaining_mcm']==pytest.approx(11.7)
    assert r['report']['volume_curve_reference']['physical_initial_storage_mcm']==pytest.approx(16)
    assert r['report']['volume_curve_reference']['supported_area_pct']==75


def test_storage_percentage_has_local_thresholds_and_respects_spatial_sy():
    d,m=model()
    for i,c in enumerate(m['plan_maps']['cells']):
        c['bedrock_msl']=60-20*i;c['sy']=.05*(i+1)
    r=lt.lifetime_analysis(d,m,None,storage_scenario())
    assert [c['life_years'] for c in r['plan_maps']['cells']]==pytest.approx([10,15,20,25])
    ref=r['report']['quantity_reference']
    assert ref['initial_storage_mcm']==pytest.approx(40)
    assert ref['equivalent_loss_mcm']==pytest.approx(10)
    assert ref['equivalent_drawdown_min_m']==10
    assert ref['equivalent_drawdown_max_m']==25
    doubled=lt.lifetime_analysis(d,m,None,storage_scenario(sy_factor=2))
    assert doubled['report']['quantity_reference']['equivalent_loss_mcm']==pytest.approx(20)
    assert [c['life_years'] for c in doubled['plan_maps']['cells']]==pytest.approx([10,15,20,25])


def test_storage_reference_changes_with_floor_and_keeps_missing_data_unknown():
    d,m=model()
    r=lt.lifetime_analysis(d,m,None,storage_scenario(floor_offset_m=20))
    assert r['report']['area_target_years']==pytest.approx(5)
    assert r['report']['quantity_reference']['initial_storage_mcm']==pytest.approx(8)
    m['plan_maps']['cells'][0]['sy']=None
    m['plan_maps']['cells'][1]['bedrock_msl']=None
    r=lt.lifetime_analysis(d,m,None,storage_scenario())
    assert r['report']['unknown_area_pct']==50
    assert r['report']['quantity_reference']['storage_supported_area_pct']==50
    assert r['report']['quantity_reference']['initial_storage_mcm']==pytest.approx(8)
    assert r['plan_maps']['cells'][0]['life_quantity_cutoff_msl'] is None


def test_zero_initial_storage_is_already_limited_without_inventing_percentage():
    d,m=model(floor=100)
    r=lt.lifetime_analysis(d,m,None,storage_scenario())
    assert all(c['life_status']=='already' and c['life_years']==0 for c in r['plan_maps']['cells'])
    assert r['report']['quantity_reference']['zero_initial_storage_area_pct']==100
    assert r['report']['quantity_reference']['equivalent_drawdown_median_m'] is None


def test_percentage_preview_respects_zone_parameters_and_scenario_scaling():
    import json
    d,m=model();m['report']['volume_factor']=2
    geo={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'sy_factor':2,'floor_offset_m':20},'geometry':{'type':'Polygon','coordinates':[[[0,0],[.01,0],[.01,.02],[0,.02],[0,0]]]}}]}
    text=json.dumps(geo)
    r=lt.lifetime_analysis(d,m,None,storage_scenario(),zones_text=text)
    assert r['report']['quantity_reference']['initial_storage_mcm']==pytest.approx(32)
    assert r['report']['quantity_reference']['equivalent_loss_mcm']==pytest.approx(8)
    assert [c['life_years'] for c in r['plan_maps']['cells']]==pytest.approx([5,10,10,5])


@pytest.mark.parametrize('percent',[0,-1,100.01])
def test_storage_percentage_range_is_validated(percent):
    d,m=model()
    with pytest.raises(ValueError):lt.lifetime_analysis(d,m,None,storage_scenario(percent))


def test_full_storage_loss_threshold_stops_at_physical_floor():
    d,m=model()
    r=lt.lifetime_analysis(d,m,None,storage_scenario(100))
    assert r['report']['area_target_years']==pytest.approx(40)
    assert r['report']['quantity_reference']['target_storage_mcm']==0


def test_inactive_quantity_does_not_parse_stale_html_threshold():
    d,m=model()
    cfg={**scenario(),'quantity_on':False,'quantity_type':'drawdown','quantity_limit':'','subsidence_on':True,'subsidence_limit':100}
    r=lt.lifetime_analysis(d,m,None,cfg)
    assert r['report']['quantity_reference'] is None


def test_phase_and_zero_transition_have_analytical_crossings():
    d,m=model()
    r=lt.lifetime_analysis(d,m,None,scenario(drop_factor=2,transition_years=0))
    assert r['report']['area_target_years']==pytest.approx(5)
    r=lt.lifetime_analysis(d,m,None,scenario(phase_year=4,phase_factor=2))
    assert r['report']['area_target_years']==pytest.approx(7)
    r=lt.lifetime_analysis(d,m,None,scenario(drop_factor=3,transition_years=4))
    # First four years lose 8 m; remaining 2 m at 3 m/year.
    assert r['report']['area_target_years']==pytest.approx(4+2/3)

def test_unknown_is_separate_from_beyond_and_existing_failure_is_proven():
    d,m=model();m['plan_maps']['cells'][0]['management_slope']=None
    r=lt.lifetime_analysis(d,m,None,scenario(drop_factor=0,transition_years=0))
    assert [c['life_status'] for c in r['plan_maps']['cells']]==['unknown','beyond','beyond','beyond']
    r=lt.lifetime_analysis(d,m,None,scenario(quality_on=True,quality_limit=1500,crop_limit=3000))
    assert r['report']['unknown_area_pct']==100
    assert r['plan_maps']['cells'][1]['life_known_limit_upper_bound']==pytest.approx(10)
    r=lt.lifetime_analysis(d,m,None,{**scenario(),'quantity_limit':45,'quality_on':True,'quality_limit':1500,'crop_limit':3000})
    assert all(c['life_status']=='already' for c in r['plan_maps']['cells'])

def test_known_area_target_is_upper_bound_when_unknown_area_exists():
    d,m=model();m['plan_maps']['cells'][0]['management_slope']=None
    r=lt.lifetime_analysis(d,m,None,scenario())
    assert r['report']['area_target_status']=='upper_bound'
    assert r['report']['area_target_years']==pytest.approx(10)

def test_climate_switch_missing_data_does_not_silently_mean_zero():
    d,m=model()
    off=lt.lifetime_analysis(d,m,None,scenario(climate_on=False,climate_temp_c=4))
    on=lt.lifetime_analysis(d,m,None,scenario(climate_on=True,climate_temp_c=4))
    assert off['report']['unknown_area_pct']==0
    assert on['report']['unknown_area_pct']==100
    assert on['report']['curves'][1]['remaining_mcm'] is None
    assert on['report']['curves'][1]['volume_unknown_area_pct']==100
    assert not on['report']['climate']['accepted']

def test_quality_reference_year_and_distinct_uses():
    d,m=model();q={'report':{'volume_dates':d['dates'],'quality_water_year':1402,'vertical_model':{'bottom_top_ec_ratio':1}},'plan_maps':{'cells':[{**c,'quality_supported':True,'quality_ec':1000} for c in d['plan_maps']['cells']]}}
    config={**scenario(),'quantity_on':False,'quality_on':True,'quality_limit':1500,'crop_limit':3000,'ec_growth_pct':10,'use':'drinking'}
    r=lt.lifetime_analysis(d,m,q,config);c=r['plan_maps']['cells'][0]
    # EC is transported through two historical years, then first passage.
    assert c['life_drinking_years']==pytest.approx(np.log(1.5)/np.log(1.1)-2,abs=.002)
    assert c['life_crop_years']>c['life_drinking_years']
    assert c['life_cause']==2
    assert lt.lt_fraction(1000,1000,2)==pytest.approx(.5)
    assert lt.lt_fraction(1000,1200,.5)==pytest.approx(lt.lt_fraction(1000,1200,2))
    inactive=lt.lifetime_analysis(d,m,q,{**scenario(),'quality_limit':'1500','crop_limit':'3000','quality_on':False})
    assert inactive['report']['area_target_years']==pytest.approx(10)
    assert inactive['report']['curves'][0]['usable_mcm']>0


def test_head_threshold_accepts_negative_msl_and_does_not_require_sy_or_floor():
    d,m=model(floor=None,sy=None)
    for c in m['plan_maps']['cells']:c['after_msl']=-150
    r=lt.lifetime_analysis(d,m,None,{**scenario(),'quantity_type':'head','quantity_limit':-175})
    assert r['report']['area_target_years']==pytest.approx(25)
    assert r['report']['curves'][1]['volume_unknown_area_m2']==4e6

def test_additional_subsidence_does_not_remove_storage_and_los_unknown():
    d,m=model()
    for c in m['plan_maps']['cells']:c['management_subsidence']=20
    m['report']['subsidence']['component']='vertical'
    cfg={**scenario(),'quantity_on':False,'subsidence_on':True,'subsidence_limit':100}
    r=lt.lifetime_analysis(d,m,None,cfg)
    assert r['report']['area_target_years']==pytest.approx(5)
    assert r['report']['curves'][5]['remaining_mcm']==pytest.approx(14)
    m['report']['subsidence']['component']='los'
    assert lt.lifetime_analysis(d,m,None,cfg)['report']['unknown_area_pct']==100

def test_calendar_incomplete_and_duplicate_rejection():
    text='year_persian,month_persian,precip_mm,temp_c\n'
    text+=''.join(f'{1400 if m>=7 else 1401},{m},10,20\n' for m in range(1,13))
    years,audit=lt.lt_climate_rows(text,1400)
    assert years=={1400:(120,20)}
    assert not lt.lt_climate_rows(text.rsplit('\n',2)[0]+'\n',1400)[0]
    with pytest.raises(ValueError):lt.lt_climate_rows(text+'1400,7,10,20\n',1400)
    assert not lt.lt_climate_rows('water_year,precip_mm,temp_c\n1401,100,20\n',1400)[0]

def climate_example():
    rng=np.random.default_rng(1364);years=range(1370,1405);level=100.;records=[];text='water_year,precip_mm,temp_c\n'
    for y in years:
        p=250+rng.normal(0,70);t=15+rng.normal(0,1)
        level+=-1+.008*(p-250)-.4*(t-15)
        records.append({'water_year':y,'month':6,'level':level})
        text+=f'{y},{p},{t}\n'
    return {'histories':[{'records':copy.deepcopy(records)} for _ in range(4)]},text

def test_climate_temporal_validation_recovers_signal_and_constant_rejects():
    m,text=climate_example();fit=lt.lt_fit_climate(m,text,1404)
    assert fit['accepted'] and fit['lag_years']==0
    assert fit['beta_precip_m_per_mm']==pytest.approx(.008)
    assert fit['beta_temp_m_per_c']==pytest.approx(-.4)
    assert fit['holdout_count']>=4
    assert fit['end_water_year']==1404
    fit=lt.lt_fit_climate(m,'water_year,precip_mm,temp_c\n'+''.join(f'{y},250,15\n' for y in range(1370,1405)),1404)
    assert not fit['accepted']

def test_climate_only_adds_scenario_anomaly_not_historic_baseline():
    d,m=model();cm,text=climate_example();m['histories']=cm['histories']
    base=lt.lifetime_analysis(d,m,None,scenario())
    zero=lt.lifetime_analysis(d,m,None,scenario(climate_on=True),text)
    dry=lt.lifetime_analysis(d,m,None,scenario(climate_on=True,climate_precip_pct=-20,climate_temp_c=2,climate_years=5),text)
    assert zero['report']['area_target_years']==pytest.approx(base['report']['area_target_years'])
    assert dry['report']['area_target_years']<zero['report']['area_target_years']

def test_zones_change_only_covered_cells_and_overlap_rejects():
    import json
    d,m=model();zone={'type':'Feature','properties':{'drop_factor':2},'geometry':{'type':'Polygon','coordinates':[[[0,0],[.01,0],[.01,.02],[0,.02],[0,0]]]}}
    text=json.dumps({'type':'FeatureCollection','features':[zone]})
    r=lt.lifetime_analysis(d,m,None,scenario(transition_years=0),zones_text=text)
    assert [c['life_years'] for c in r['plan_maps']['cells']]==pytest.approx([5,10,10,5])
    with pytest.raises(ValueError):lt.lt_zones(json.dumps({'type':'FeatureCollection','features':[zone,zone]}))

def test_sensitivity_is_not_confidence_and_has_open_end():
    d,m=model()
    for c in m['plan_maps']['cells']:c['management_slope_high']=0
    r=lt.lifetime_analysis(d,m,None,scenario(sensitivity_on=True,sensitivity_floor_m=2))
    assert r['plan_maps']['cells'][0]['life_sensitivity_open']
    assert r['plan_maps']['cells'][0]['life_sensitivity_beyond']
    assert len(r['report']['sensitivity']['summary'])==3
    assert 'not confidence' in r['report']['sensitivity']['kind']

@pytest.mark.parametrize('cfg',[{'horizon':3.5},{'horizon':0},{'sy_factor':20},{'quantity_on':False}])
def test_invalid_inputs(cfg):
    d,m=model()
    with pytest.raises(ValueError):lt.lifetime_analysis(d,m,None,{**scenario(),**cfg})

def test_geotiff_georeferencing_mask_and_status_no_filled_unknowns():
    # A two-row mesh whose north bound is not a full grid multiple.
    d,m=model();dx=1000/(111320*np.cos(np.radians(.01)));dy=1000/111320
    for i,c in enumerate(m['plan_maps']['cells']):
        x=(i%2)*dx;y=(i//2)*dy
        c['polygons']=[[[[x,y],[x+dx,y],[x+dx,y+dy],[x,y+dy],[x,y]]]]
    d['plan_maps']['extent']=[0,0,2*dx,1.8*dy]
    m['plan_maps']['cells'][0]['management_slope']=None
    r=lt.lifetime_analysis(d,m,None,scenario())
    raw=lt.lifetime_tiff(r)
    assert raw[:4]==b'II*\0'
    count=struct.unpack_from('<H',raw,8)[0];tags={}
    for i in range(count):
        tag,kind,n,value=struct.unpack_from('<HHII',raw,10+12*i);tags[tag]=(kind,n,value)
    tie=struct.unpack_from('<6d',raw,tags[33922][2]);scale=struct.unpack_from('<3d',raw,tags[33550][2])
    assert tie[4]==pytest.approx(2*scale[1])
    width,height=tags[256][2],tags[257][2]
    values=struct.unpack_from('<'+str(width*height)+'f',raw,tags[273][2])
    assert values.count(-9999)==width*height-3
    assert sum(v==pytest.approx(10) for v in values)==3


@pytest.mark.parametrize('horizon,years',[(50,[0,25,50]),(125,list(range(0,126,25))),(137,[0,25,50,75,100,125,137]),(200,list(range(0,201,25)))])
def test_long_horizon_display_does_not_coarsen_actual_crossings_or_curves(horizon,years):
    d,m=model()
    r=lt.lifetime_analysis(d,m,None,{**scenario(),'horizon':horizon})
    assert r['report']['display_step_years']==25
    assert r['report']['display_years']==years
    assert r['report']['bands']==years[1:]
    assert len(r['report']['curves'])==horizon+1
    assert r['report']['integration_step_years']==.25
    assert all(c['life_years']==pytest.approx(10) for c in r['plan_maps']['cells'])


def test_rectangular_geotiff_has_independent_axis_sizes_and_preserves_nodata():
    from PIL import Image
    d,m=model();sx=111320*np.cos(np.radians(.01));dx=500/sx;dy=800/111320
    for i,c in enumerate(m['plan_maps']['cells']):
        x=(i%2)*dx;y=(i//2)*dy
        c['polygons']=[[[[x,y],[x+dx,y],[x+dx,y+dy],[x,y+dy],[x,y]]]]
    for maps in [d['plan_maps'],m['plan_maps']]:
        maps.update(extent=[0,0,2*dx,2*dy],cell_width_m=500,cell_height_m=800,spacing_lon=dx,spacing_lat=dy,side_m=None)
    m['plan_maps']['cells'][0]['management_slope']=None
    result=lt.lifetime_analysis(d,m,None,scenario())
    with Image.open(io.BytesIO(lt.lifetime_tiff(result))) as image:
        assert image.size==(2,2)
        assert image.tag_v2[33550][:2]==pytest.approx([dx,dy])
        values=list(image.getdata())
        assert values.count(-9999)==1 and sum(v==pytest.approx(10) for v in values)==3
        import json
        assert json.loads(image.tag_v2[270])['pixel_grid']['cell_height_m']==800

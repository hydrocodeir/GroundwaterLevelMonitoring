import copy
import json
import pytest
from test_aquifer3d_compute import _model
from test_aquifer3d_storage import BEDROCK, COORDS
from test_aquifer_lifetime import lt, mg, model


@pytest.mark.parametrize('name',['مشهد','نیشابور','کرات'])
def test_default_model_ignores_internal_bedrock_even_if_previously_initialized(name):
    figure='lon,lat,bedrock_depth_m\n'+''.join(f'{x},{y},60\n' for x,y in COORDS)
    engine=_model(name,figure)
    engine._mashhad_bedrock_text=BEDROCK
    result=engine.analyze(0,1381,None)
    assert result['metrics']['drainable_after_mcm'] is None
    assert result['grid']['bedrock_real'] is False
    assert result['volume_mesh']['heads_only']
    assert not result['volume_mesh']['geology']['floor']
    assert all(c['bedrock_msl'] is None and c['sy'] is None for c in result['plan_maps']['cells'])
    chosen=engine.analyze(0,1381,.06,BEDROCK)
    assert chosen['grid']['bedrock_source']=='uploaded'
    assert chosen['metrics']['drainable_after_mcm']>0


def test_templates_are_separate_and_mixed_and_require_actual_source_layers():
    data,managed=model()
    options=lt.lifetime_presets(data,managed)
    assert len(options)==15
    assert {p['group'] for p in options}=={'کمیت','شوری','فرونشست','ترکیبی'}
    assert all(p['ready'] for p in options if p['group']=='کمیت')
    assert not any(p['ready'] for p in options if p['group']!='کمیت')
    quality={'report':{'sites':20,'thresholds':{'drinking_ec_uScm':1234,'irrigation_ec_uScm':2345}}}
    for i,c in enumerate(managed['plan_maps']['cells']):c['management_subsidence']=10*(i+1)
    managed['report']['subsidence']['component']='vertical'
    choices=lt.lifetime_presets(data,managed,quality)
    assert all(p['ready'] for p in choices)
    combined=next(p for p in choices if p['id']=='all_action')
    assert combined['scenario']['quantity_on'] and combined['scenario']['quality_on'] and combined['scenario']['subsidence_on']
    assert combined['scenario']['quality_limit']==1234
    assert combined['scenario']['crop_limit']==2345
    assert combined['scenario']['subsidence_limit']==100  # five times area-weighted median 20 mm/year.
    assert combined['scenario']['drop_factor']==.7
    no_floor=copy.deepcopy(managed)
    for c in no_floor['plan_maps']['cells']:c['bedrock_msl']=None;c['sy']=None
    ec_sub=next(p for p in lt.lifetime_presets(data,no_floor,quality) if p['id']=='ec_sub')
    assert ec_sub['ready'] and not ec_sub['scenario']['quantity_on']
    managed['report']['subsidence']['component']='los'
    assert not next(p for p in lt.lifetime_presets(data,managed,quality) if p['id']=='all_action')['ready']


def test_unknown_diagnostics_keep_convex_hull_and_radius_distinct():
    data,managed=model()
    cell=managed['plan_maps']['cells'][0]
    cell['management_slope']=None;cell['management_support_reasons']=['outside_trend_hull','beyond_trend_radius']
    config={'quantity_on':True,'quantity_type':'drawdown','quantity_limit':10}
    result=lt.lifetime_analysis(data,managed,None,config)
    diag=result['report']['unknown_diagnostics']
    assert diag['unknown_cells']==1
    assert diag['reason_areas_pct']=={'beyond_trend_radius':25,'outside_trend_hull':25}
    assert result['plan_maps']['cells'][0]['life_unknown_reasons']==['beyond_trend_radius','outside_trend_hull']


def test_optional_invalid_subsidence_is_explicit_and_does_not_erase_trends():
    from test_aquifer_management import inputs
    data,history=inputs()
    result=mg.management_analysis(data,history,{'allow_incomplete_subsidence':True,'subsidence':{'text':'bad,columns\n1,2'}})
    assert result['report']['subsidence']['input_error']
    assert result['report']['eligible_wells']==4
    assert all(c['management_subsidence'] is None for c in result['plan_maps']['cells'])


def test_quality_accepts_user_geographic_csv_and_does_not_invent_volume():
    from test_waterq_compute import quality
    from pyproj import Transformer
    ring=[[60,35],[60.5,35],[60.5,35.5],[60,35.5],[60,35]]
    csv='longitude,latitude,ec,year_persian,month_persian\n'
    for i in range(4):
        for j in range(4):csv+=f'{60.05+i*.12},{35.05+j*.12},{1000+100*i+10*j},1405,6\n'
    audit=quality.audit_quality(csv,json.dumps({'features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[ring]}}]}))
    assert audit['accepted_rows']==16
    cells=[{'lon':r['lon'],'lat':r['lat'],'remaining_mcm':None} for r in audit['records']]
    data={'aquifer':{'name':'User aquifer'},'dates':{'after':'1405-06','after_water_year':1404},'display_grid':{'polygons':[[ring]]},
          'metrics':{'drainable_after_mcm':None,'sy_mode':'constant','sy':None,'sy_min':None,'sy_max':None},
          'grid':{'bedrock_source':'schematic'},'wells':{'common':16},'pixel_water':None,
          'plan_maps':{'cells':cells,'extent':[60,35,60.5,35.5],'side_m':1000,'polygons':[[ring]]}}
    result=quality.estimate_quality(data,audit['records'])
    assert result['report']['volume_available'] is False
    assert result['report']['total_remaining_mcm'] is None
    assert all(v is None for v in result['report']['volumes_mcm'].values())
    assert any(c['quality_supported'] and c['quality_ec']>0 for c in result['plan_maps']['cells'])
    assert result['report']['covariates']['raster_fields']==[]

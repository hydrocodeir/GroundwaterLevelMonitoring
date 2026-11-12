import json
import pytest
from test_aquifer3d_compute import _model
from test_aquifer3d_storage import BEDROCK


def test_section_uses_original_floor_and_breaks_at_holes():
    model=_model()
    model._features[0]['geometry']['coordinates'].append([[.008,.008],[.012,.008],[.012,.012],[.008,.012],[.008,.008]])
    model._prepared={}
    model.call_json('analyze',json.dumps({'feature_index':0,'baseline_year':1381,'sy':.1,'bedrock_text':BEDROCK}))
    section=json.loads(model.call_json('cross_section',json.dumps({'start':[.001,.01],'end':[.019,.01]})))
    assert section['length_m'] == pytest.approx(.018*111320,rel=1e-6)
    inside=[p for p in section['samples'] if p['levels']]
    assert len(inside) < len(section['samples'])
    assert all(p['levels']==pytest.approx([90,80,40]) for p in inside)
    assert section['samples'][0]['distance_m']==0
    coarse=model.cross_section([.001,.01],[.019,.01],count=2)
    assert any(p['levels'] is None for p in coarse['samples'])
    with pytest.raises(ValueError):model.cross_section([0,0],[0,0])
    with pytest.raises(ValueError):model.cross_section([1,1],[2,2])


def test_well_details_use_persian_water_year_and_keep_missing_months_missing():
    model=_model()
    key=next(iter(model._prepared[0]['current']))
    model._readings[(key,1381,7)]=15
    result=model.well_details(0,'الف',.002,.002)
    assert [r['water_year'] for r in result['records']]==[1380,1381,1403]
    assert [r['month'] for r in result['records']]==[6,7,6]
    assert all(row['observed_decline_m'] is None for row in result['annual'])
    assert result['records'][0]['level']==90


def test_decline_display_anchors_do_not_change_real_levels_or_storage():
    model=_model()
    result=model.analyze(0,1381,.1,BEDROCK)
    assert result['metrics']['equivalent_water']['remaining_m']==pytest.approx(4)
    assert all(p[3] == pytest.approx(4) for tri in result['pixel_water']['shell']['red'] for p in tri)
    assert all(p[2] >= p[3]-1e-9 and p[2]-p[3] <= 10+1e-9
               for tri in result['volume_mesh']['geology']['red'] for p in tri)
    assert result['wells']['points'][0]['after']==80

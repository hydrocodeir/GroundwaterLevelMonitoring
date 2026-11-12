"""Cartographic layers must clip holes and leave hydrological results unchanged."""
from copy import deepcopy
import json
import pytest
from shapely.geometry import Polygon, Point, LineString
from test_aquifer3d_compute import _model
from test_aquifer3d_storage import BEDROCK


def test_city_footprints_clip_to_aquifer_preserve_holes_and_never_modify_storage():
    model=_model()
    data=json.loads(model.call_json('analyze',json.dumps({'feature_index':0,'baseline_year':1381,'sy':.1,'bedrock_text':BEDROCK})))
    # A hole is also excluded from city display, regardless of the source polygon.
    shell=data['display_grid']['polygons'][0][0]
    hole=[(.008,.008),(.012,.008),(.012,.012),(.008,.012),(.008,.008)]
    model._last_analysis['display_grid']['polygons']=[[shell,hole]]
    before=deepcopy(model._last_analysis)
    geometry={'type':'Polygon','coordinates':[[[-.01,-.01],[.03,-.01],[.03,.03],[-.01,.03],[-.01,-.01]]]}
    result=json.loads(model.call_json('urban_overlay',json.dumps({'features':[{'properties':{'id':'test','name':'شهر آزمایشی'},'geometry':geometry}]})))
    assert len(result)==1
    assert len(result[0]['paths'])==2
    boundary=Polygon(shell,[hole])
    for path in result[0]['paths']:
        assert boundary.covers(LineString([p[:2] for p in path]))
        for p in path:
            assert p[2]==pytest.approx(90)
            assert p[3]==pytest.approx(5)
    assert boundary.covers(Point(result[0]['label'][:2]))
    assert model._last_analysis==before


def test_empty_or_outside_city_layer_returns_no_synthetic_city():
    model=_model()
    assert model.urban_overlay([])==[]
    model.call_json('analyze',json.dumps({'feature_index':0,'baseline_year':1381,'sy':.1,'bedrock_text':BEDROCK}))
    assert model.urban_overlay([{'properties':{'id':'outside','name':'خارج'},'geometry':{'type':'Polygon','coordinates':[[[1,1],[2,1],[2,2],[1,2],[1,1]]]}}])==[]


def test_smaller_town_points_remain_points_and_follow_selected_aquifer():
    model=_model()
    model.call_json('analyze',json.dumps({'feature_index':0,'baseline_year':1381,'sy':.1,'bedrock_text':BEDROCK}))
    before=deepcopy(model._last_analysis)
    points=[{'properties':{'id':'town','name':'شهر کوچک','source':'OpenStreetMap'},'geometry':{'type':'Point','coordinates':[.01,.01]}},
            {'properties':{'id':'outside','name':'خارج'},'geometry':{'type':'Point','coordinates':[1,1]}}]
    result=model.urban_overlay(points)
    assert len(result)==1
    assert result[0]['paths']==[]
    assert result[0]['label'][:2]==[.01,.01]
    assert result[0]['label'][2]==pytest.approx(90)
    assert result[0]['source']=='OpenStreetMap'
    assert model._last_analysis==before

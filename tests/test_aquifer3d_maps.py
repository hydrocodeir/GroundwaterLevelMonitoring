"""Independent checks of baseline percentages, physical floor and contour geometry."""
import json
import pytest
from shapely.geometry import Polygon, LineString
from test_aquifer3d_compute import _model
from test_aquifer3d_storage import BEDROCK, COORDS


def test_percentage_cells_share_3d_storage_and_respond_to_uploaded_floor_and_sy():
    model = _model()
    first = model.analyze(0, 1381, .1, BEDROCK)
    cells = first['plan_maps']['cells']
    assert cells == first['pixel_water']['cells']
    for cell in cells:
        assert cell['before_m'] == pytest.approx(5)
        assert cell['remaining_pct'] == pytest.approx(80)
        assert cell['lost_pct'] == pytest.approx(20)
        # The raised display rim must never replace the physical 40m floor.
        assert cell['bedrock_msl'] == pytest.approx(40)
    lower = BEDROCK.replace(',40', ',30')
    other = model.analyze(0, 1381, .2, lower)
    assert other['plan_maps']['cells'][0]['before_m'] == pytest.approx(12)
    assert other['plan_maps']['cells'][0]['remaining_pct'] == pytest.approx(100*50/60)
    spatial = 'longitude,latitude,Sy\n' + ''.join(f'{x},{y},0.25\n' for x,y in COORDS)
    result = model.analyze(0, 1381, None, BEDROCK, sy_text=spatial)
    assert result['plan_maps']['fields']['sy']['min'] == pytest.approx(.25)
    assert result['plan_maps']['cells'][0]['remaining_m'] == pytest.approx(10)
    json.dumps(result, allow_nan=False)


def test_percentages_allow_gains_and_never_invent_a_zero_baseline_ratio():
    model = _model()
    for key in list(model._readings):
        if key[1] == 1404:
            model._readings[key] = 0
    result = model.analyze(0, 1381, .1, BEDROCK)
    assert all(c['remaining_pct'] == pytest.approx(120) and c['lost_pct'] == 0
               for c in result['plan_maps']['cells'])
    result = model.analyze(0, 1381, .1, BEDROCK.replace(',40', ',90'))
    assert all(c['remaining_pct'] is None and c['lost_pct'] is None
               for c in result['plan_maps']['cells'])
    assert all(c['remaining_m'] > 0 for c in result['plan_maps']['cells'])


def test_contours_follow_an_analytic_plane_and_respect_polygon_holes():
    model = _model()
    shape = Polygon([(0,0),(1,0),(1,1),(0,1)], [[(.3,.3),(.7,.3),(.7,.7),(.3,.7)]])
    points = [[x/4,y/4] for y in range(5) for x in range(5)]
    contours = model._surface_contours(points,5,5,[x+y for x,y in points],shape)
    assert len(contours) >= 3
    for contour in contours:
        for path in contour['paths']:
            assert shape.covers(LineString(path))
            assert all(x+y == pytest.approx(contour['value']) for x,y in path)
    assert model._surface_contours(points,5,5,[.06]*25,shape) == []


def test_latest_supported_september_is_data_driven_and_has_correct_water_year():
    model = _model()
    for key,value in list(model._readings.items()):
        if key[1] == 1404:
            del model._readings[key]
            model._readings[(key[0],1407,key[2])] = value
    model._prepared = {}
    # A lone late observation must not redefine the end date of the whole aquifer.
    key = next(iter(model._readings))[0]
    model._readings[(key,1410,6)] = 22
    result = model.analyze(0,1381,.1,BEDROCK)
    assert result['dates']['after'] == '1407-06'
    assert result['dates']['after_water_year'] == 1406
    assert result['wells']['points'][0]['after'] == 80

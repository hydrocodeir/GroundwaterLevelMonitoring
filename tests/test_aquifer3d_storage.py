"""Storage accounting, spatial Sy input and fixed bedrock reference regressions."""
import json
import pytest
from test_aquifer3d_compute import _model

COORDS = [(-.001, -.001), (.021, -.001), (.021, .021), (-.001, .021),
          (.01, -.001), (.021, .01), (.01, .021), (-.001, .01)]
BEDROCK = 'lon,lat,bedrock_msl\n' + ''.join(f'{x},{y},40\n' for x, y in COORDS)


def test_spatial_sy_integrates_locally_and_matches_constant_when_uniform():
    model = _model()
    uniform = 'longitude,latitude,Sy\n' + ''.join(f'{x},{y},0.1\n' for x, y in COORDS)
    constant = model.analyze(0, 1381, .1, BEDROCK)
    spatial = model.analyze(0, 1381, None, BEDROCK, sy_text=uniform)
    for field in ['storage_change_mcm', 'drainable_before_mcm', 'drainable_after_mcm']:
        assert spatial['metrics'][field] == pytest.approx(constant['metrics'][field])
    assert spatial['metrics']['equivalent_water'] == pytest.approx({
        'remaining_m': 4, 'lost_m': 1, 'gained_m': 0})
    variable = 'lon,lat,Sy\n' + ''.join(f'{x},{y},{.05 if x < .01 else .2}\n' for x, y in COORDS)
    result = model.analyze(0, 1381, .9, BEDROCK, sy_text=variable)
    cells = [p for p in result['water_grid']['points'] if p[5]]
    assert max(p[3] for p in cells) > min(p[3] for p in cells)
    expected = sum(p[3] for p in cells) / len(cells) * result['aquifer']['area_km2']
    assert result['metrics']['drainable_after_mcm'] == pytest.approx(expected)


@pytest.mark.parametrize('text', [
    'lon,lat,Sy\n0,0,6\n0,1,.1\n1,0,.1',
    'lon,lat,Sy\n0,0,.1\n0,0,.2\n0,1,.1\n1,0,.1',
    'lon,lat,Sy\n0,0,.1\n1,1,.1\n2,2,.1',
    'lon,lat,Sy\n0,0,.1\n0,1,NaN\n1,0,.1',
    'lon,lat,Sy\n.009,.009,.1\n.011,.009,.1\n.01,.011,.1',
])
def test_invalid_or_incomplete_spatial_sy_is_not_silently_used(text):
    with pytest.raises(ValueError):
        _model().analyze(0, 1381, None, BEDROCK, sy_text=text)


def test_dry_columns_never_produce_negative_remaining_water():
    model = _model()
    result = model.analyze(0, 1381, .1, BEDROCK.replace(',40\n', ',85\n'))
    assert result['metrics']['equivalent_water'] == pytest.approx({
        'remaining_m': 0, 'lost_m': .5, 'gained_m': 0})
    assert result['metrics']['storage_change_mcm'] == pytest.approx(-.5 * result['aquifer']['area_km2'])


def test_rising_columns_report_gain_separately():
    model = _model()
    for key in model._readings:
        if key[1] == 1404:
            model._readings[key] = 5
    result = model.analyze(0, 1381, .1, BEDROCK)
    assert result['metrics']['equivalent_water'] == pytest.approx({
        'remaining_m': 5.5, 'lost_m': 0, 'gained_m': .5})


def test_builtin_mashhad_and_explicit_override():
    model = _model('مشهد')
    model._mashhad_bedrock_text = BEDROCK
    result = model.analyze(0, 1381, .06)
    assert result['grid']['bedrock_source'] == 'mashhad_msl'
    assert result['metrics']['equivalent_water']['remaining_m'] == pytest.approx(2.4)
    overridden = model.analyze(0, 1381, .06, BEDROCK.replace(',40\n', ',30\n'))
    assert overridden['grid']['bedrock_source'] == 'uploaded'
    assert overridden['metrics']['drainable_after_mcm'] > result['metrics']['drainable_after_mcm']


def test_neyshabur_floor_does_not_move_with_baseline_selection():
    figure = 'lon,lat,bedrock_depth_m\n' + ''.join(f'{x},{y},60\n' for x, y in COORDS)
    model = _model('نیشابور', figure, [80, 100, 120, 140, 180], fifth_current_only=True)
    early = model.analyze(0, 1381, .1)
    later = model.analyze(0, 1389, .1)
    assert early['wells']['common'] != later['wells']['common']
    assert [p[4] for p in early['grid']['points']] == [p[4] for p in later['grid']['points']]


def test_missing_sy_or_floor_does_not_invent_absolute_storage():
    for sy, floor in [(None, BEDROCK), (.1, '')]:
        result = _model().analyze(0, 1381, sy, floor)
        assert result['metrics']['equivalent_water'] is None
        assert not any(p[5] for p in result['water_grid']['points'])
        json.dumps(result, allow_nan=False)


def test_balance_columns_conserve_volume_with_mixed_local_gains_and_losses():
    model = _model()
    for index, key in enumerate(list(model._readings)):
        if key[1] == 1404:
            model._readings[key] = 3 if index < 4 else 25
    result = model.analyze(0, 1381, .1, BEDROCK)
    balance = result['metrics']['water_balance']
    assert balance['lost_m'] > 0 and balance['gained_m'] > 0
    assert balance['before_m'] == pytest.approx(balance['retained_m'] + balance['lost_m'])
    assert balance['after_m'] == pytest.approx(balance['retained_m'] + balance['gained_m'])
    assert result['metrics']['storage_change_mcm'] == pytest.approx(balance['gained_mcm'] - balance['lost_mcm'])


def test_display_padding_preserves_original_samples_and_keeps_polygon_holes():
    model = _model()
    hole = [[.008,.008],[.012,.008],[.012,.012],[.008,.012],[.008,.008]]
    model._features[0]['geometry']['coordinates'].append(hole)
    model._prepared = {}
    result = model.analyze(0, 1381, .1, BEDROCK)
    display = result['display_grid']
    assert display['polygons'][0][1] == hole
    assert len(display['points']) == (model.GRID_SIZE + 2) ** 2
    for index, point in enumerate(result['grid']['points']):
        if point[5]:
            row, col = divmod(index, model.GRID_SIZE)
            assert display['points'][(row+1)*display['cols']+col+1] == point[:5]
    assert result['metrics']['equivalent_water']['remaining_m'] == pytest.approx(4)
    assert len(result['wells']['points']) == result['wells']['common']


def test_volume_rim_meets_baseline_without_changing_storage_or_water_equivalent():
    model = _model()
    result = model.analyze(0, 1381, .1, BEDROCK)
    mesh = result['volume_mesh']
    for edge in mesh['boundary']:
        for index in edge:
            v = mesh['vertices'][index]
            assert v[4] == pytest.approx(v[2], abs=1e-6)
            assert v[5:7] == pytest.approx([5, 4])
    assert result['metrics']['equivalent_water']['remaining_m'] == pytest.approx(4)
    assert mesh['geology']['blue'] and mesh['geology']['red']
    assert not mesh['geology']['green']
    assert mesh['water']['blue'] and mesh['water']['red']
    assert all(p[2] >= 0 for tri in mesh['water']['blue'] for p in tri)


def test_shells_split_mixed_gain_and_loss_instead_of_overlapping():
    model = _model()
    vertices = [[0,0,10,5,0,1,.5], [1,0,10,15,0,1,1.5], [0,1,10,5,0,1,.5]]
    shells = model._volume_shells(vertices, [[0,1,2]], [[0,1],[1,2],[2,0]], True)
    assert shells['red'] and shells['green'] and shells['blue']
    assert all(p[0] <= .5 + 1e-9 for tri in shells['red'] for p in tri)
    assert all(p[0] >= .5 - 1e-9 for tri in shells['green'] for p in tri)


def test_missing_sy_produces_no_equivalent_volume_shell():
    result = _model().analyze(0, 1381, None, BEDROCK)
    assert result['volume_mesh']['water'] is None
    assert result['volume_mesh']['geology']['blue']


def test_pixel_columns_stack_loss_above_remaining_and_clip_polygon_holes():
    import math
    from shapely.geometry import Polygon
    model = _model()
    outer = [[58,36],[58.02,36],[58.02,36.02],[58,36.02],[58,36]]
    hole = [[58.008,36.008],[58.012,36.008],[58.012,36.012],[58.008,36.012],[58.008,36.008]]
    display = {'cols':2, 'rows':2, 'polygons':[[outer,hole]],
               'points':[[x,y,100,80,0] for y in [36,36.02] for x in [58,58.02]]}
    result = model._pixel_water_mesh(display, [], .1, True)
    cells = result['cells']
    assert cells and result['side_m'] > 0
    assert all(c['remaining_m'] == pytest.approx(8) and c['lost_m'] == pytest.approx(2) for c in cells)
    assert all(c['remaining_mcm'] == pytest.approx(8*c['area_m2']/1e6) for c in cells)
    shape = Polygon(outer,[hole])
    sx = 111320*math.cos(math.radians(36.01))
    assert sum(c['area_m2'] for c in cells) == pytest.approx(shape.area*sx*111320)
    full = [c for c in cells if math.isclose(c['area_m2'],result['side_m']**2,rel_tol=1e-7)]
    assert full
    for color, low, high in [('blue',0,8),('red',8,10)]:
        triangles=result['shell'][color]
        assert min(p[2] for tri in triangles for p in tri) == pytest.approx(low)
        assert max(p[2] for tri in triangles for p in tri) == pytest.approx(high)
        assert all(shape.buffer(1e-10).covers(Polygon([p[:2] for p in tri]))
                   for tri in triangles if len(set(tuple(p[:2]) for p in tri)) == 3)


def test_pixel_columns_do_not_draw_loss_for_rises_or_invent_missing_storage():
    model = _model()
    display = {'cols':2,'rows':2,'polygons':[[[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]]],
               'points':[[x,y,80,100,0] for y in [0,.01] for x in [0,.01]]}
    assert model._pixel_water_mesh(display, [], None, True) is None
    assert model._pixel_water_mesh(display, [], .1, False) is None
    result = model._pixel_water_mesh(display, [], .1, True)
    assert not result['shell']['red']
    assert all(c['remaining_m'] == pytest.approx(10) and c['lost_m'] == 0 for c in result['cells'])

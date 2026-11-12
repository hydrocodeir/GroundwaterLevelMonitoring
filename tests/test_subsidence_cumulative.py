import copy
import csv
import io
import math
import pytest
from test_aquifer_management import mg, inputs


def raster_csv(values):
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['longitude','latitude','cumulative_mm','pixel_row','pixel_column'])
    for row,items in enumerate(values):
        for col,value in enumerate(items):
            if value is not None:writer.writerow([col+.5,2-row-.5,value,row,col])
    return stream.getvalue()


def options(text,**updates):
    return {'text':text,'value_kind':'cumulative','component':'vertical','direction':'down','unit':'mm',
            'calendar_basis':'persian','start_water_year':1395,'end_water_year':1404,'duration_years':10,
            'raster_grid':{'width':2,'height':2,'crs':'EPSG:4326','affine':[1,0,0,0,-1,2]},**updates}


POLYGONS=[[[[0,0],[2,0],[2,2],[0,2],[0,0]]]]


def test_raster_preserves_nodata_zero_and_period_average_is_not_cumulative():
    opts=options(raster_csv([[0,100],[None,300]]))
    text=opts.pop('text');sample,audit=mg.mg_subsidence(text,opts,POLYGONS,1395,1404)
    assert audit['cumulative'] is True
    assert audit['periods']==[[1394,1404]]  # Full Persian years cross different water years.
    assert sample(.5,1.5)['cumulative']==0
    assert sample(.5,.5)['cumulative'] is None
    assert sample(1.5,.5)['cumulative']==300
    assert sample(1.5,.5)['rate']==30
    averaged=sample(1,1,POLYGONS)
    assert averaged['cumulative']==pytest.approx(400/3)
    assert averaged['rate']==pytest.approx(40/3)
    assert averaged['coverage_pct']==75
    opts['min_pixel_coverage']=.9
    masked,_=mg.mg_subsidence(text,opts,POLYGONS,1395,1404)
    assert masked(1,1,POLYGONS)['cumulative'] is None
    assert masked(1,1,POLYGONS)['coverage_pct']==75


def test_csv_indices_infer_grid_without_filling_a_missing_pixel():
    opts=options(raster_csv([[0,100],[None,300]]));opts.pop('raster_grid');text=opts.pop('text')
    sample,audit=mg.mg_subsidence(text,opts,POLYGONS,1395,1404)
    assert audit['raster_grid']['inferred_from_csv']
    assert sample(.5,.5)['cumulative'] is None
    assert sample(1.5,.5)['cumulative']==pytest.approx(300)
    # Half the coarse cell is beyond the original raster; it must count as uncovered.
    bigger=[[[[0,0],[4,0],[4,2],[0,2],[0,0]]]]
    assert sample(1,1,bigger)['coverage_pct']==pytest.approx(37.5)
    assert sample(1,1,bigger)['cumulative'] is None


def test_historical_cumulative_source_is_independent_of_future_trend_window_but_not_future_data():
    opts=options(raster_csv([[0,100],[None,300]]));text=opts.pop('text')
    historical,audit=mg.mg_subsidence(text,opts,POLYGONS,1410,1419)
    assert historical(1.5,.5)['cumulative']==300
    future,audit=mg.mg_subsidence(text,opts,POLYGONS,1390,1399)
    assert future(1.5,.5) is None
    assert audit['periods']==[]


def test_cumulative_sign_conversion_and_no_fabricated_average_without_duration():
    opts=options(raster_csv([[0,-100],[None,-300]]),direction='up',duration_years='')
    text=opts.pop('text');sample,_=mg.mg_subsidence(text,opts,POLYGONS,1395,1404)
    assert sample(1.5,.5)['cumulative']==300
    assert sample(1.5,.5)['rate'] is None


def test_source_checksum_and_incompatible_georeferencing_are_rejected():
    opts=options(raster_csv([[0,100],[None,300]]),csv_sha256='wrong');text=opts.pop('text')
    with pytest.raises(ValueError):mg.mg_subsidence(text,opts,POLYGONS,1395,1404)
    opts.pop('csv_sha256');opts['raster_grid']['affine'][2]=2
    with pytest.raises(ValueError):mg.mg_subsidence(text,opts,POLYGONS,1395,1404)


def monthly_histories():
    data,histories=inputs()
    for well in histories:
        well['records']=[{'year':year,'month':month,'ordinal':year*12+month,
                          'water_year':year if month>=7 else year-1,
                          'level':110-(year-1395+(month-1)/12)}
                         for year in range(1395,1406) for month in range(1,13)]
    return data,histories


def test_cumulative_comparison_uses_observed_months_and_separate_total_thresholds():
    data,history=monthly_histories()
    source='longitude,latitude,cumulative_mm\n'+ '\n'.join(f"{w['lon']},{w['lat']},100" for w in history)
    sub=options(source);sub.pop('raster_grid')
    result=mg.management_analysis(data,history,{'subsidence':sub,'cumulative_subsidence_limit':50,'cumulative_decline_limit':5})
    report=result['report']
    assert report['subsidence']['comparison_mode']=='observed_cumulative'
    assert report['subsidence']['groundwater_endpoints'][0]['first']=='1395-01'
    assert report['subsidence']['groundwater_endpoints'][0]['last']=='1404-12'
    assert report['used_subsidence_limit_mm_year'] is None
    assert report['used_cumulative_subsidence_limit_mm']==50
    for c in result['plan_maps']['cells']:
        assert c['management_groundwater_cumulative']==pytest.approx(119/12)
        assert c['management_subsidence_cumulative']==pytest.approx(100)
        assert c['management_subsidence']==pytest.approx(10)
        assert c['management_overlap']==3
    # A discontinued endpoint must not be extrapolated to the source endpoint.
    for well in history:well['records']=[r for r in well['records'] if r['year']<1404]
    missing=mg.management_analysis(data,history,{'subsidence':sub})
    assert missing['report']['subsidence']['aligned_wells']==0
    assert all(c['management_groundwater_cumulative'] is None for c in missing['plan_maps']['cells'])

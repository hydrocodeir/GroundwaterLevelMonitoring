"""Fetch public explanatory layers only. No WaterQ rows/values are sent to GEE.

Earth Engine performs the explicitly requested public satellite preparation.
Model fitting, validation, clipping and volume calculations run in browser Python.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import requests
import jdatetime
import ee

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--end-water-year',type=int,required=True)
    parser.add_argument('--window',type=int,default=3)
    parser.add_argument('--scale',type=int,default=1000)
    args=parser.parse_args()
    output=ROOT/'Data/WaterQ_Sources';output.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('ndvi_export',ROOT/'scripts/export_monthly_ndvi.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.initialize_earth_engine(ROOT/'ee-hydrocode.json')
    features=json.loads((ROOT/'Data/AQUIFER.geojson').read_text(encoding='utf-8'))['features']
    feature=next(f for f in features if f['properties']['AQUIFER']=='مشهد')
    region=ee.Geometry(feature['geometry']).buffer(10000).bounds()
    bbox=region.coordinates().getInfo()[0]
    envelope=','.join(map(str,[bbox[0][0],bbox[0][1],bbox[2][0],bbox[2][1]]))
    geology='https://services8.arcgis.com/4KhTMTZ1x0f76DSg/arcgis/rest/services/GLiM_Niveau_I/FeatureServer/1'
    metadata=requests.get(geology,params={'f':'json'},timeout=40).json()
    (output/'GLIM_LAYER_METADATA.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    response=requests.get(geology+'/query',params={'f':'geojson','where':'1=1','outFields':'*','geometry':envelope,'geometryType':'esriGeometryEnvelope','inSR':4326,'outSR':4326,'spatialRel':'esriSpatialRelIntersects','returnGeometry':'true','resultRecordCount':2000},timeout=90)
    response.raise_for_status();raw=response.json()
    if 'features' not in raw or raw.get('exceededTransferLimit'):
        raise ValueError('Incomplete or invalid geology response')
    (output/'MASHHAD_GLIM.geojson').write_bytes(response.content)
    print('Geology polygons fetched: '+str(len(raw['features'])),flush=True)
    start=jdatetime.date(args.end_water_year-args.window+1,7,1).togregorian().isoformat()
    end=jdatetime.date(args.end_water_year+1,7,1).togregorian().isoformat()
    def indices(image):
        scl=image.select('SCL')
        mask=scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        sr=image.select(['B2','B3','B4','B8','B11','B12']).multiply(.0001).resample('bilinear').reproject('EPSG:32640',None,250).updateMask(mask.reproject('EPSG:32640',None,250))
        ndvi=sr.normalizedDifference(['B8','B4']).rename('ndvi')
        ndwi=sr.normalizedDifference(['B3','B8']).rename('ndwi')
        bsi=sr.expression('((s+r)-(n+b))/((s+r)+(n+b))',{'s':sr.select('B11'),'r':sr.select('B4'),'n':sr.select('B8'),'b':sr.select('B2')}).rename('bsi')
        swir=sr.select('B11').divide(sr.select('B12').max(.0001)).rename('swir_ratio')
        return ee.Image.cat(ndvi,ndwi,bsi,swir).copyProperties(image,['system:time_start'])
    s2=ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(region).filterDate(start,end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',60))
    tiles=s2.aggregate_array('MGRS_TILE').distinct()
    selected=tiles.map(lambda tile:s2.filter(ee.Filter.eq('MGRS_TILE',tile)).sort('CLOUDY_PIXEL_PERCENTAGE').limit(3).toList(3)).flatten()
    s2=ee.ImageCollection.fromImages(selected)
    # Regional explanatory covariates: sample composites at 250m, then average
    # to 1km. These are not a 10m groundwater-quality product.
    satellite=s2.map(indices).median().clip(region).setDefaultProjection('EPSG:32640',None,250).reduceResolution(ee.Reducer.mean(),maxPixels=256,bestEffort=True).reproject('EPSG:32640',None,args.scale)
    land=ee.ImageCollection('ESA/WorldCover/v200').first().select('Map')
    dw=ee.Image.cat(land.eq(40).rename('crops'),land.eq(50).rename('built'),land.eq(60).rename('bare')).reproject('EPSG:32640',None,250).reduceResolution(ee.Reducer.mean(),maxPixels=256,bestEffort=True).reproject('EPSG:32640',None,args.scale)
    dem=ee.Image('USGS/SRTMGL1_003')
    terrain=ee.Image.cat(dem.rename('elevation'),ee.Terrain.slope(dem).rename('slope')).reduceResolution(ee.Reducer.mean(),maxPixels=65535).reproject('EPSG:32640',None,args.scale)
    stack=ee.Image.cat(terrain,satellite,dw,ee.Image.pixelLonLat()).toFloat().unmask(-9999).clip(region)
    print('Downloading GEE public covariates: '+start+' / '+end,flush=True)
    url=stack.getDownloadURL({'region':region,'scale':args.scale,'crs':'EPSG:32640','format':'NPY'})
    result=requests.get(url,timeout=240)
    if not result.ok:
        raise RuntimeError('GEE export failed: '+result.text[:1800])
    path=output/'MASHHAD_GEE_COVARIATES.npy';path.write_bytes(result.content)
    manifest={'aquifer':'مشهد','water_year_start':args.end_water_year-args.window+1,'water_year_end':args.end_water_year,'gregorian_start':start,'gregorian_end_exclusive':end,'scale_m':args.scale,'region_bbox':bbox,'gee_datasets':['USGS/SRTMGL1_003','COPERNICUS/S2_SR_HARMONIZED','ESA/WorldCover/v200'],'s2_sampling':'Three least-cloudy scenes per MGRS tile in the reference window; reflectance resampled to 250m before indices, median then 1km averaging; NOT an annual vegetation mean','landcover_epoch':2021,'variables':['elevation','slope','ndvi','ndwi','bsi','swir_ratio','crops','built','bare'],'interpretation':'Explanatory surface covariates, NOT measured groundwater EC or a vertical salinity profile','private_quality_rows_sent_to_cloud':False,'geology':{'url':geology,'primary_doi':'10.1029/2012GC004370','version':'GLiM v1.1 level I','scale_note':'Regional lithology assembled at target 1:1M; not local borehole geology'},'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file() and p.suffix in ('.npy','.geojson')}}
    (output/'MASHHAD_WATERQ_SOURCE_METADATA.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Public source package saved',flush=True)


if __name__=='__main__':main()

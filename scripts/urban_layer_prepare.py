"""Executed by prepare_urban_layer_browser.py inside browser Pyodide, never the server."""
import zipfile
import sqlite3
import json
import hashlib
import re
from datetime import datetime, timezone
from shapely.geometry import shape, mapping, Point
from shapely import wkb
from shapely.ops import transform
from pyproj import Transformer

archive=zipfile.ZipFile('/cities.zip')
names=archive.namelist()
gpkg=[name for name in names if name.endswith('.gpkg')][0]
open('/cities.gpkg','wb').write(archive.read(gpkg))
connection=sqlite3.connect('/cities.gpkg')
tables=connection.execute('select table_name,column_name,geometry_type_name,srs_id from gpkg_geometry_columns').fetchall()
schema={table:[row[1] for row in connection.execute('pragma table_info("'+table+'")')] for table,*_ in tables}
provinces=json.load(open('/provinces.geojson'))
province=shape(next(f['geometry'] for f in provinces['features'] if f['properties']['shapeName']=='Razavi Khorasan'))
table='GHSL_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A'
rows=connection.execute('select ID_UC_G0,GC_UCN_MAI_2025,GC_UCN_LIS_2025,GC_CNT_GAD_2025,GC_UCA_KM2_2025,GC_POP_TOT_2025,geom from "'+table+'" where GC_CNT_GAD_2025 like ?', ('%Iran%',)).fetchall()
if not rows:
    raise ValueError('Iran records were not found in the declared country field.')
to_wgs84=Transformer.from_crs('ESRI:54009','EPSG:4326',always_xy=True).transform
features=[]
labels=json.loads(_labels_json)
for identifier,name,names_list,country,area,population,blob in rows:
    # OGC GeoPackage binary header: magic, version, flags, SRS and optional envelope.
    assert blob[:2]==b'GP'
    envelope=(blob[3]>>1)&7
    offset=8+{0:0,1:32,2:48,3:48,4:64}[envelope]
    original=wkb.loads(blob[offset:])
    geometry=transform(to_wgs84,original.simplify(50,preserve_topology=True))
    if not province.intersects(geometry):
        continue
    assert geometry.is_valid and not geometry.is_empty
    label=geometry.representative_point()
    features.append({'type':'Feature','bbox':list(geometry.bounds),'properties':{
        'id':str(identifier),'name':labels.get(str(identifier),name),'name_original':name,'names_original':names_list,'country':country,
        'population_2025':population,'area_source_km2':area,'label':[label.x,label.y],
        'source':'GHSL / JRC UCDB R2024A V1.2','epoch':2025},'geometry':mapping(geometry)})
# Keep OSM town/city positions as points; never fabricate a boundary from a point.
osm=json.load(open('/osm.json'))
def canonical(value):
    return re.sub(r'[\s\u200c\u200d_-]+','',str(value).translate(str.maketrans({'ي':'ی','ك':'ک'}))).casefold()
major={canonical(value):f for f in features for value in [f['properties']['name'],f['properties']['name_original']]}
seen={}
for element in osm.get('elements',[]):
    tags=element.get('tags',{})
    if tags.get('place') not in ('city','town') or 'lon' not in element:
        continue
    point=Point(float(element['lon']),float(element['lat']))
    if not province.covers(point):
        continue
    name=tags.get('name:fa') or tags.get('name') or tags.get('name:en')
    if not name:
        continue
    match=next((major[canonical(v)] for v in [name,tags.get('name'),tags.get('name:en')] if canonical(v) in major),None)
    if match is not None and shape(match['geometry']).distance(point)<.2:
        match['properties']['osm_id']=element['id']
        match['properties']['label']=[point.x,point.y]
        match['properties']['label_source']='OpenStreetMap contributors'
        continue
    key=canonical(name)
    if key in seen and point.distance(seen[key])<.01:
        continue
    seen[key]=point
    features.append({'type':'Feature','bbox':[point.x,point.y,point.x,point.y],
        'geometry':mapping(point),'properties':{'id':'osm-node-'+str(element['id']),'name':name,
        'name_original':tags.get('name:en') or name,'place':tags['place'],'label':[point.x,point.y],
        'source':'OpenStreetMap contributors','source_url':'https://www.openstreetmap.org/node/'+str(element['id']),
        'geometry_role':'place_point','osm_id':element['id']}})
metadata={'dataset':'GHSL UCDB R2024A V1.2 + OpenStreetMap cities/towns','epoch':2025,'source_url':'https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/GHS_UCDB_REGION_GLOBE_R2024A/GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A/V1-2/GHS_UCDB_REGION_CENTRAL_AND_SOUTHERN_ASIA_R2024A_V1_2.zip',
          'source_page':'https://human-settlement.emergency.copernicus.eu/ghs_ucdb_2024.php',
          'source_sha256':hashlib.sha256(open('/cities.zip','rb').read()).hexdigest(),
          'province_source':'geoBoundaries gbOpen IRN ADM1, commit 9469f09; OpenStreetMap/Wambacher, boundary year 2017, ODbL 1.0',
          'province_source_sha256':hashlib.sha256(open('/provinces.geojson','rb').read()).hexdigest(),
          'province':'Razavi Khorasan','feature_count':len(features),
          'method':'Select Iran records; read OGC GeoPackage geometry in Pyodide; simplify 50 m preserving topology in source Mollweide CRS; transform ESRI:54009 to EPSG:4326; retain city polygons intersecting province polygon; retain complete city footprints and holes; representative points are label anchors.',
          'interpretation':'GHSL urban footprints (2025) plus OSM city/town points. Point positions are not municipal polygons. Province filtering uses geoBoundaries; source snapshot is not a hydrological date.',
          'processing':'Browser Pyodide (sqlite3, Shapely, pyproj); no backend GIS processing',
          'labels':'Persian display names keyed by original GHSL identifier; original names retained; geometry never edited to match a label.',
          'license':'European Commission GHSL reuse with acknowledgement; province selection source ODbL 1.0',
          'downloaded_utc':datetime.now(timezone.utc).date().isoformat()}
metadata.update({'osm_source':'https://overpass-api.de/api/interpreter','osm_timestamp':osm.get('osm3s',{}).get('timestamp_osm_base'),'osm_sha256':hashlib.sha256(open('/osm.json','rb').read()).hexdigest(),'polygon_count':sum(f['geometry']['type']!='Point' for f in features),'point_count':sum(f['geometry']['type']=='Point' for f in features),'osm_method':'OSM place=city/town nodes in retrieval envelope; exact province covers filter in Pyodide; same-name major city deduplicated; original point geometry retained.','license':'GHSL acknowledgement; OSM points ODbL 1.0; geoBoundaries province source ODbL 1.0'})
output={'type':'FeatureCollection','name':'Khorasan Razavi cities and towns','metadata':metadata,'features':features}
text=json.dumps(output,ensure_ascii=False,separators=(',',':'))
open('/cities.geojson','w').write(text)
metadata['geojson_sha256']=hashlib.sha256(text.encode()).hexdigest()
open('/cities.metadata.json','w').write(json.dumps(metadata,ensure_ascii=False,indent=2))
json.dumps({'metadata':metadata,'cities':[{k:f['properties'][k] for k in ('id','name')} for f in features]})

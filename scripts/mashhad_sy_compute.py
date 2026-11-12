"""Reproducible soil-informed Sy prior; execute scientific steps in Pyodide.

This is not an observation or a calibrated deep-aquifer parameter map.
The original GASY soil estimates and the regional-mean scenario are kept separate.
"""
import csv
import hashlib
import io
import json
import math
import struct
import numpy as np

RECORD_URL = 'https://zenodo.org/records/14216083'
DATA_DOI = '10.5281/zenodo.14216083'
PAPER_DOI = '10.1038/s41597-025-04742-1'
REGIONAL_DOI = '10.2166/ws.2025.078'
REGIONAL_MEAN = 0.06
NODATA = -9999.0


def nc_header(data):
    """Read NetCDF classic/CDF2 metadata without allocating the global array."""
    data = bytes(data)
    if data[:3] != b'CDF' or data[3] not in (1, 2):
        raise ValueError('Only uncompressed NetCDF classic or CDF2 is supported.')
    version, cursor = data[3], 4

    def integer():
        nonlocal cursor
        value = struct.unpack_from('>I', data, cursor)[0]
        cursor += 4
        return value

    def string():
        nonlocal cursor
        size = integer()
        result = data[cursor:cursor+size].decode('utf-8')
        cursor += (size+3)//4*4
        return result

    def attributes():
        nonlocal cursor
        tag, count = integer(), integer()
        result = {}
        for _ in range(count):
            name, kind, size = string(), integer(), integer()
            code = {1:'b', 2:'c', 3:'h', 4:'i', 5:'f', 6:'d'}[kind]
            byte_count = size*struct.calcsize(code)
            raw = data[cursor:cursor+byte_count]
            cursor += (byte_count+3)//4*4
            result[name] = raw.decode('utf-8') if kind == 2 else list(struct.unpack('>'+str(size)+code, raw))
        return result

    records = integer()
    _, count = integer(), integer()
    dims = [(string(), integer()) for _ in range(count)]
    global_attributes = attributes()
    _, count = integer(), integer()
    variables = {}
    for _ in range(count):
        name = string()
        ids = [integer() for _ in range(integer())]
        attrs = attributes()
        kind, size = integer(), integer()
        offset = integer() if version == 1 else (integer()<<32)+integer()
        variables[name] = {'dims':[dims[i][0] for i in ids],
                           'shape':[dims[i][1] for i in ids], 'attrs':attrs,
                           'type':kind, 'size':size, 'offset':offset}
    if records:
        raise ValueError('Unexpected record dimension in static GASY file.')
    return {'version':version, 'dims':dict(dims), 'variables':variables,
            'attributes':global_attributes}


def source_plan(header_bytes, feature):
    metadata = nc_header(header_bytes)
    variables = metadata['variables']
    axes = {}
    for name in ('lat', 'lon'):
        variable = variables[name]
        dtype = {5:'>f4', 6:'>f8'}[variable['type']]
        axes[name] = np.frombuffer(header_bytes, dtype=dtype,
                                  count=variable['shape'][0], offset=variable['offset']).astype(float)
    coords = [p for poly in _polygons(feature) for ring in poly for p in ring]
    bounds = [min(p[0] for p in coords), min(p[1] for p in coords),
              max(p[0] for p in coords), max(p[1] for p in coords)]
    selected = {}
    for name, low, high in [('lon',bounds[0],bounds[2]), ('lat',bounds[1],bounds[3])]:
        axis = axes[name]
        step = abs(float((axis[-1]-axis[0])/(len(axis)-1)))
        indices = np.flatnonzero((axis>=low-step*2)&(axis<=high+step*2))
        if not len(indices):
            raise ValueError('Aquifer outside source grid.')
        selected[name] = [int(indices.min()), int(indices.max())+1]
    var = variables['sy']
    dims, shape = var['dims'], var['shape']
    first_spatial = min(dims.index('lat'), dims.index('lon'))
    prefix = 0
    # The GSDE second file contains layers 5-8; use its last (2.296 m) layer.
    for axis in range(first_spatial):
        prefix += (shape[axis]-1)*math.prod(shape[axis+1:])
    major = dims[first_spatial]
    begin, end = selected[major]
    stride = math.prod(shape[first_spatial+1:])
    flat_begin, flat_end = prefix+begin*stride, prefix+end*stride
    if var['type'] != 5:
        raise ValueError('Unexpected Sy encoding; inspect rather than guess units.')
    return {'metadata':metadata, 'selected':selected, 'bounds':bounds,
            'byte_begin':var['offset']+flat_begin*4,
            'byte_end':var['offset']+flat_end*4-1,
            'first_spatial':first_spatial,
            'block_shape':[end-begin]+shape[first_spatial+1:],
            'axes':{k:v.tolist() for k,v in axes.items()}}


def decode_window(plan, raw):
    expected = plan['byte_end']-plan['byte_begin']+1
    if len(raw) != expected:
        raise ValueError(f'Byte-range mismatch: {len(raw)} != {expected}')
    source = plan['metadata']['variables']['sy']
    dims = source['dims'][plan['first_spatial']:]
    values = np.frombuffer(raw, dtype='>f4').reshape(plan['block_shape'])
    for index in range(len(dims)-1,-1,-1):
        if dims[index] not in ('lat','lon'):
            values = np.take(values,-1,axis=index)
            dims = dims[:index]+dims[index+1:]
    if dims != ['lat','lon']:
        values = values.T
    lat0,lat1 = plan['selected']['lat']
    lon0,lon1 = plan['selected']['lon']
    if source['dims'][plan['first_spatial']] == 'lat':
        values = values[:,lon0:lon1]
    else:
        values = values[lat0:lat1,:]
    lat = np.array(plan['axes']['lat'][lat0:lat1])
    lon = np.array(plan['axes']['lon'][lon0:lon1])
    if lat[0] < lat[-1]:
        values, lat = values[::-1,:], lat[::-1]
    if lon[0] > lon[-1]:
        values, lon = values[:,::-1], lon[::-1]
    result = values.astype(np.float64)
    fill = source['attrs'].get('_FillValue',[-999])[0]
    result[(result==fill)|~np.isfinite(result)] = np.nan
    if np.any(np.isfinite(result)&((result<=0)|(result>=1))):
        raise ValueError('Source values not dimensionless fractions strictly between 0 and 1.')
    return {'values':result, 'lat':lat, 'lon':lon,
            'metadata':plan['metadata'], 'raw_sha256':hashlib.sha256(raw).hexdigest()}


def _polygons(feature):
    geometry = feature['geometry']
    return [geometry['coordinates']] if geometry['type']=='Polygon' else geometry['coordinates']


def _area(geometry):
    if geometry.is_empty:
        return 0.0
    if geometry.geom_type != 'Polygon':
        return sum(_area(part) for part in getattr(geometry,'geoms',[]))
    def ring_area(ring):
        coords = list(ring.coords)
        value = sum(math.radians(b[0]-a[0])*(math.sin(math.radians(a[1]))+math.sin(math.radians(b[1])))
                    for a,b in zip(coords,coords[1:]))
        return abs(value)*6371008.8**2/2
    return max(0,ring_area(geometry.exterior)-sum(ring_area(r) for r in geometry.interiors))


def geotiff(values, west, north, dx, dy, description):
    """Single-band Float32 GeoTIFF, PixelIsArea, EPSG:4326; no resampling."""
    values = np.ascontiguousarray(values,dtype='<f4')
    height,width = values.shape
    entries = {
        256:(4,[width]),257:(4,[height]),258:(3,[32]),259:(3,[1]),262:(3,[1]),
        270:(2,json.dumps(description,ensure_ascii=True,separators=(',',':'))+'\0'),
        273:(4,[0]),277:(3,[1]),278:(4,[height]),279:(4,[values.nbytes]),
        284:(3,[1]),305:(2,'GroundwaterLevelMonitoring / Pyodide\0'),339:(3,[3]),
        33550:(12,[dx,dy,0]),33922:(12,[0,0,0,west,north,0]),
        34735:(3,[1,1,0,4,1024,0,1,2,1025,0,1,1,2048,0,1,4326,2054,0,1,9102]),
        42113:(2,str(int(NODATA))+'\0')}
    start = 8+2+len(entries)*12+4
    extra = bytearray()
    packed = []
    for tag,(kind,items) in sorted(entries.items()):
        if kind == 2:
            raw = items.encode('ascii')
            count = len(raw)
        else:
            count = len(items)
            raw = struct.pack('<'+str(count)+{3:'H',4:'I',12:'d'}[kind],*items)
        if len(raw)<=4:
            field = raw.ljust(4,b'\0')
        else:
            while (start+len(extra))%8:
                extra.append(0)
            field = struct.pack('<I',start+len(extra))
            extra.extend(raw)
        packed.append([tag,kind,count,field])
    while (start+len(extra))%8:
        extra.append(0)
    pixel_offset = start+len(extra)
    for entry in packed:
        if entry[0] == 273:
            entry[3] = struct.pack('<I',pixel_offset)
    directory = b''.join(struct.pack('<HHI',tag,kind,count)+field for tag,kind,count,field in packed)
    return b'II'+struct.pack('<HIH',42,8,len(entries))+directory+b'\0'*4+bytes(extra)+values.tobytes()


def build(soil, gsde, feature, output_dir):
    from pathlib import Path
    from shapely.geometry import Polygon, Point, box
    from shapely.ops import unary_union
    from shapely.prepared import prep
    output = Path(output_dir)
    output.mkdir(parents=True,exist_ok=True)
    polygons = _polygons(feature)
    shape = unary_union([Polygon(p[0],p[1:]) for p in polygons])
    if not shape.is_valid:
        raise ValueError('Invalid aquifer polygon; do not silently repair input.')
    lat,lon = soil['lat'],soil['lon']
    # Recover exact nominal increments from the full coordinate span; float32
    # coordinate quantisation is substantially smaller than this ~1 km grid.
    dx = abs((lon[-1]-lon[0])/(len(lon)-1))
    dy = abs((lat[-1]-lat[0])/(len(lat)-1))
    if abs(dx-1/120)<1e-6: dx=1/120
    if abs(dy-1/120)<1e-6: dy=1/120
    lon = lon[0]+np.arange(len(lon))*dx
    lat = lat[0]-np.arange(len(lat))*dy
    west,north = float(lon[0]-dx/2),float(lat[0]+dy/2)
    # Nearest-neighbour registration of GSDE to the native SoilGrids lattice.
    iy = np.abs(gsde['lat'][:,None]-lat[None,:]).argmin(axis=0)
    ix = np.abs(gsde['lon'][:,None]-lon[None,:]).argmin(axis=0)
    raw_soil = soil['values']
    raw_gsde = gsde['values'][np.ix_(iy,ix)]
    two = np.isfinite(raw_soil)&np.isfinite(raw_gsde)
    raw_mean = np.where(two,(raw_soil+raw_gsde)/2,np.where(np.isfinite(raw_soil),raw_soil,raw_gsde))
    weights = np.zeros(raw_mean.shape)
    prepared = prep(shape)
    for row,y in enumerate(lat):
        for col,x in enumerate(lon):
            pixel = box(x-dx/2,y-dy/2,x+dx/2,y+dy/2)
            if prepared.intersects(pixel):
                weights[row,col] = _area(shape.intersection(pixel))
    mask = weights>0
    valid = mask&np.isfinite(raw_mean)
    if not valid.any():
        raise ValueError('No valid soil Sy over the aquifer.')
    mean = float(np.sum(raw_mean[valid]*weights[valid])/weights[valid].sum())
    factor = REGIONAL_MEAN/mean
    scenario = np.where(np.isfinite(raw_mean),raw_mean*factor,REGIONAL_MEAN)
    if np.any(mask&((scenario<=0)|(scenario>=1))):
        raise ValueError('Scenario outside physical fractional bounds; no silent clipping.')
    coverage = float(weights[valid].sum()/weights[mask].sum())
    if not math.isclose(weights.sum(),_area(shape),rel_tol=1e-5):
        raise ValueError('Pixel intersections do not cover the polygon area.')
    main = np.where(mask,scenario,NODATA).astype(np.float32)
    raw = np.where(mask&np.isfinite(raw_mean),raw_mean,NODATA).astype(np.float32)
    metadata = {
        'aquifer':'مشهد','product_type':'UNVALIDATED_SOIL_INFORMED_AQUIFER_SY_PRIOR',
        'is_measured_aquifer_sy':False,'is_pumping_test_calibrated':False,
        'crs':'EPSG:4326','raster_type':'PixelIsArea','nodata':NODATA,
        'unit':'dimensionless fraction, not percent','nominal_source_resolution':'1 km; native 30 arcsecond grid preserved',
        'pixel_size_degrees':[dx,dy],'shape_rows_cols':list(main.shape),
        'geotransform':[west,dx,0,north,0,-dy],
        'mask_rule':'all touched pixels with positive aquifer intersection area; no values elsewhere',
        'polygon_area_km2':_area(shape)/1e6,'valid_area_coverage_fraction':coverage,
        'soil_product_depths_m':{'SoilGrids_GASY_layer7':2.0,'GSDE_GASY_layer8':2.296},
        'source_doi':DATA_DOI,'paper_doi':PAPER_DOI,'regional_mean_reference_doi':REGIONAL_DOI,
        'license':'CC BY 4.0; derived products retain attribution',
        'raw_method':'Arithmetic mean of two deepest soil GASY products; one available source if the other is missing.',
        'aquifer_scenario_method':'raw_soil_mean * (0.06 / clipped_area_weighted_mean_raw_soil); no local pumping-test fit.',
        'regional_mean_target':REGIONAL_MEAN,'raw_soil_weighted_mean':mean,'scale_factor':factor,
        'scenario_weighted_mean':float(np.sum(scenario[mask]*weights[mask])/weights[mask].sum()),
        'scenario_range':[float(scenario[mask].min()),float(scenario[mask].max())],
        'raw_soil_range':[float(raw_mean[valid].min()),float(raw_mean[valid].max())],
        'pixels_intersecting_aquifer':int(mask.sum()),'pixels_missing_both_sources':int((mask&~np.isfinite(raw_mean)).sum()),
        'source_only_one_count':int((mask&(np.isfinite(raw_soil)^np.isfinite(raw_gsde))).sum()),
        'mean_absolute_source_difference':float(np.sum(np.abs(raw_soil[two&mask]-raw_gsde[two&mask])*weights[two&mask])/weights[two&mask].sum()),
        'source_registration_max_offset_degrees':[float(np.max(np.abs(gsde['lon'][ix]-lon))),float(np.max(np.abs(gsde['lat'][iy]-lat)))],
        'source_slab_sha256':{'SoilGrids':soil['raw_sha256'],'GSDE':gsde['raw_sha256']},
        'aquifer_geometry_sha256':hashlib.sha256(json.dumps(feature['geometry'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'limitations':[
            'Soil texture at 2–2.296 m does not establish the texture of deep water-bearing sediments.',
            'The 0.06 mean is a regional literature anchor, not a cell-scale validation or calibration.',
            'Within-pixel variability is unresolved; the grid must not be described as 30 m or borehole-resolved.',
            'Source differences describe sensitivity to soil datasets, not a 95% confidence interval.',
            'Parameters are static; no observed temporal evolution of Sy is inferred.'],
    }
    (output/'MASHHAD_SY_PRIOR.tif').write_bytes(geotiff(main,west,north,dx,dy,metadata))
    (output/'MASHHAD_SY_SOIL_REFERENCE.tif').write_bytes(geotiff(raw,west,north,dx,dy,{**metadata,'product_type':'RAW_DEEP_SOIL_GASY_MEAN_NOT_AQUIFER_SY'}))
    # CSV centres inside the aquifer plus explicit boundary support points keep
    # the complete aquifer within the convex hull required by the dashboard.
    rows,seen = [],set()
    def sample(x,y,role):
        key=(round(x,9),round(y,9))
        if key in seen:return
        col=int(np.clip(math.floor((x-west)/dx),0,len(lon)-1))
        row=int(np.clip(math.floor((north-y)/dy),0,len(lat)-1))
        if not mask[row,col]:
            candidates=np.argwhere(mask)
            row,col=min(candidates,key=lambda rc:(lon[rc[1]]-x)**2*math.cos(math.radians(y))**2+(lat[rc[0]]-y)**2)
            role += '_nearest_intersecting_pixel'
        seen.add(key)
        rows.append([x,y,float(scenario[row,col]),role,int(row),int(col)])
    for row,col in np.argwhere(mask):
        if prepared.covers(Point(lon[col],lat[row])):
            sample(float(lon[col]),float(lat[row]),'interior_pixel_center')
    for poly in polygons:
        for ring in poly:
            for x,y,*_ in ring:
                sample(x,y,'boundary_support')
    with (output/'MASHHAD_SY_PRIOR.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['longitude','latitude','Sy'])
        writer.writerows([[f'{x:.9f}',f'{y:.9f}',f'{value:.8f}'] for x,y,value,*_ in rows])
    with (output/'MASHHAD_SY_AUDIT.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream);writer.writerow(['longitude','latitude','Sy','role','row','col','GASY_SoilGrids_2m','GASY_GSDE_2_296m','GASY_raw_mean','scale_factor','source_count','cell_aquifer_area_m2'])
        for x,y,value,role,row,col in rows:
            a,b=raw_soil[row,col],raw_gsde[row,col]
            writer.writerow([x,y,value,role,row,col,a if np.isfinite(a) else '',b if np.isfinite(b) else '',raw_mean[row,col] if np.isfinite(raw_mean[row,col]) else '',factor,int(np.isfinite(a))+int(np.isfinite(b)),weights[row,col]])
    metadata['csv_record_count']=len(rows)
    metadata['csv_boundary_support_count']=sum(r[3].startswith('boundary') for r in rows)
    metadata['csv_sampling']='Raster lookup at interior centres and original boundary vertices; boundary points are not measurements.'
    metadata['csv_min_max']=[min(r[2] for r in rows),max(r[2] for r in rows)]
    (output/'MASHHAD_SY_METADATA.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    # Preview uses the same native grid and a fixed, labelled parameter range.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    fig,axes=plt.subplots(1,2,figsize=(14,7),layout='constrained')
    extent=[west,west+len(lon)*dx,north-len(lat)*dy,north]
    for ax,array,title in [(axes[0],main,'Aquifer Sy PRIOR (mean anchored to 0.06)'),(axes[1],raw,'Raw soil GASY reference (2–2.296 m)')]:
        shown=np.ma.masked_where(array==NODATA,array)
        image=ax.imshow(shown,extent=extent,origin='upper',cmap='viridis',interpolation='nearest')
        for poly in polygons:
            for ring in poly:
                ax.plot([p[0] for p in ring],[p[1] for p in ring],color='#263746',linewidth=.5)
        ax.set_aspect(1/math.cos(math.radians(float(lat.mean()))))
        ax.set_title(title,fontsize=11);ax.set_xlabel('Longitude (WGS84)');ax.set_ylabel('Latitude (WGS84)')
        fig.colorbar(image,ax=ax,shrink=.65,label='Sy (fraction, not %)')
    fig.suptitle('Mashhad aquifer | Soil-informed spatial prior, NOT measured deep-aquifer Sy',fontsize=13)
    fig.text(.5,.002,'GASY: Lv et al. (2025), doi:10.1038/s41597-025-04742-1 | native ~1 km grid | no finer-scale information created',ha='center',fontsize=8)
    fig.savefig(output/'MASHHAD_SY_PREVIEW.png',dpi=180)
    plt.close(fig)
    return metadata

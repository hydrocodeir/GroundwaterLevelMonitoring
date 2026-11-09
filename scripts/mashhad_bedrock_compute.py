"""Mashhad bedrock export. Run ONLY in the browser's Pyodide worker.

Standard-library implementation: no server-side hydrological processing.
BEDROC is depth below local ground in metres, confirmed by the user.
"""
import ast
import csv
import hashlib
import heapq
import io
import json
import math
import struct
from collections import Counter, defaultdict


A = 6378137.0
E2 = 0.0066943799901413165
K0 = 0.9996
LON0 = math.radians(57.0)
SPACING = 500.0
state = None


def normal(text):
    return str(text).replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '').replace(' ', '')


def utm(lon, lat):
    """WGS84 -> UTM 40N; Snyder transverse-Mercator series."""
    phi, lam = math.radians(lat), math.radians(lon)
    ep2 = E2/(1-E2)
    n = A/math.sqrt(1-E2*math.sin(phi)**2)
    t, c = math.tan(phi)**2, ep2*math.cos(phi)**2
    a = math.cos(phi)*(lam-LON0)
    m = A*((1-E2/4-3*E2**2/64-5*E2**3/256)*phi
           -(3*E2/8+3*E2**2/32+45*E2**3/1024)*math.sin(2*phi)
           +(15*E2**2/256+45*E2**3/1024)*math.sin(4*phi)
           -35*E2**3/3072*math.sin(6*phi))
    x = 500000+K0*n*(a+(1-t+c)*a**3/6+(5-18*t+t*t+72*c-58*ep2)*a**5/120)
    y = K0*(m+n*math.tan(phi)*(a*a/2+(5-t+9*c+4*c*c)*a**4/24
                              +(61-58*t+t*t+600*c-330*ep2)*a**6/720))
    return x, y


def lonlat(x, y):
    ep2 = E2/(1-E2)
    m = y/K0
    mu = m/(A*(1-E2/4-3*E2**2/64-5*E2**3/256))
    e1 = (1-math.sqrt(1-E2))/(1+math.sqrt(1-E2))
    p = (mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)
         +(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)
         +151*e1**3/96*math.sin(6*mu)+1097*e1**4/512*math.sin(8*mu))
    n = A/math.sqrt(1-E2*math.sin(p)**2)
    r = A*(1-E2)/(1-E2*math.sin(p)**2)**1.5
    t, c = math.tan(p)**2, ep2*math.cos(p)**2
    d = (x-500000)/(n*K0)
    lat = p-n*math.tan(p)/r*(d*d/2-(5+3*t+10*c-4*c*c-9*ep2)*d**4/24
                               +(61+90*t+298*c+45*t*t-252*ep2-3*c*c)*d**6/720)
    lon = LON0+(d-(1+2*t+c)*d**3/6+(5-2*c+28*t-3*c*c+8*ep2+24*t*t)*d**5/120)/math.cos(p)
    return math.degrees(lon), math.degrees(lat)


def point_in_ring(ring, x, y):
    inside = False
    ax, ay = ring[-1]
    for bx, by in ring:
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
        ax, ay = bx, by
    return inside


def contains(polygons, x, y):
    return any(point_in_ring(p[0], x, y) and not any(point_in_ring(r, x, y) for r in p[1:]) for p in polygons)


def sample_ring(ring, spacing):
    for a, b in zip(ring, ring[1:]+ring[:1]):
        length = math.hypot(b[0]-a[0], b[1]-a[1])
        for i in range(max(1, math.ceil(length/spacing))):
            t = i/max(1, math.ceil(length/spacing))
            yield a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])


class Contours:
    def __init__(self, lines):
        self.segments, self.bins = [], defaultdict(list)
        self.bin_size = 5000.0
        self.levels = set()
        for line in lines:
            for a, b in zip(line, line[1:]):
                dx, dy = b[0]-a[0], b[1]-a[1]
                l2 = dx*dx+dy*dy
                if l2 == 0:
                    continue
                idx = len(self.segments)
                self.segments.append((a[0], a[1], dx, dy, l2, a[2]))
                self.levels.add(a[2])
                for ix in range(math.floor(min(a[0],b[0])/self.bin_size), math.floor(max(a[0],b[0])/self.bin_size)+1):
                    for iy in range(math.floor(min(a[1],b[1])/self.bin_size), math.floor(max(a[1],b[1])/self.bin_size)+1):
                        self.bins[ix,iy].append(idx)
        if not self.segments:
            raise ValueError('No valid contour segments')

    def nearest(self, x, y, count=4):
        """Exact distance to segments; one closest segment per distinct depth.

        Spatial search stops only when unvisited cells cannot contain a
        closer segment than the kth selected depth group.
        """
        size = self.bin_size
        bx, by = math.floor(x/size), math.floor(y/size)
        seen, distances = set(), {}
        count = min(count,len(self.levels))
        for radius in range(300):
            for ix in range(bx-radius,bx+radius+1):
                for iy in range(by-radius,by+radius+1):
                    if radius and abs(ix-bx)<radius and abs(iy-by)<radius:
                        continue
                    for idx in self.bins.get((ix,iy),()):
                        if idx in seen:
                            continue
                        seen.add(idx)
                        ax,ay,dx,dy,l2,z = self.segments[idx]
                        t = max(0.0,min(1.0,((x-ax)*dx+(y-ay)*dy)/l2))
                        d2 = (x-ax-t*dx)**2+(y-ay-t*dy)**2
                        prior = distances.get(z)
                        if prior is None or (d2,idx)<prior:
                            distances[z]=(d2,idx)
            candidates = heapq.nsmallest(count,((d2,idx,z) for z,(d2,idx) in distances.items()))
            unseen_distance = min(x-(bx-radius)*size,(bx+radius+1)*size-x,
                                  y-(by-radius)*size,(by+radius+1)*size-y)
            if len(seen)==len(self.segments) or (len(candidates)>=count and candidates[-1][0]<=unseen_distance**2):
                return candidates
        raise ValueError('Spatial search did not converge')

    def estimate(self, x, y, boundary=False):
        nearest = self.nearest(x,y,1 if boundary else 4)
        d2,idx,z = nearest[0]
        if boundary or d2<1e-10:
            return z,math.sqrt(d2),z,idx
        weights = [(1/max(d,1e-10),value) for d,_,value in nearest]
        depth = sum(w*value for w,value in weights)/sum(w for w,_ in weights)
        return depth,math.sqrt(d2),z,idx


def prepare(source_text, aquifers_text):
    global state
    source = json.loads(source_text)
    if '32640' not in str(source.get('crs',{})):
        raise ValueError('BedRock must be EPSG:32640')
    aquifers = json.loads(aquifers_text)
    features = [f for f in aquifers['features'] if normal(f['properties'].get('AQUIFER')) == normal('مشهد')]
    if len(features)!=1:
        raise ValueError('Expected exactly one Mashhad aquifer, found '+str(len(features)))
    feature = features[0]
    geom = feature['geometry']
    rings_ll = [geom['coordinates']] if geom['type']=='Polygon' else geom['coordinates']
    polygons = [[list(map(lambda p:utm(p[0],p[1]),ring)) for ring in polygon] for polygon in rings_ll]
    lines = []
    for f in source['features']:
        depth = float(f['properties']['BEDROC'])
        if not math.isfinite(depth) or depth<0:
            raise ValueError('Invalid source depth')
        geometry = f['geometry']
        if geometry['type'] not in ('LineString','MultiLineString'):
            raise ValueError('Unexpected source geometry')
        parts = [geometry['coordinates']] if geometry['type']=='LineString' else geometry['coordinates']
        for part in parts:
            lines.append([(float(p[0]),float(p[1]),depth) for p in part])
    contours = Contours(lines)
    rows, occupied = [],set()
    def append(x,y,depth,role,nearest_distance,nearest_depth,segment):
        key = round(x,3),round(y,3)
        if key in occupied:
            return
        occupied.add(key)
        lon,lat = lonlat(x,y)
        rows.append(dict(x=x,y=y,lon=lon,lat=lat,depth=depth,role=role,
                         nearest_distance=nearest_distance,nearest_depth=nearest_depth,segment=segment))
    # Prioritize boundary samples; retain EVERY supplied vertex, including holes.
    boundary_xy = []
    for polygon in polygons:
        for ring in polygon:
            for x,y in sample_ring(ring,SPACING):
                d,dist,near,segment = contours.estimate(x,y,boundary=True)
                append(x,y,d,'boundary_nearest_contour',dist,near,segment)
                boundary_xy.append((x,y))
    source_total,source_inside = 0,0
    for line in lines:
        for x,y,depth in line:
            source_total+=1
            if contains(polygons,x,y):
                append(x,y,depth,'source_contour_vertex',0.0,depth,-1)
                source_inside+=1
        for a,b in zip(line,line[1:]):
            steps = max(1,math.ceil(math.hypot(b[0]-a[0],b[1]-a[1])/SPACING))
            for i in range(1,steps):
                x,y = a[0]+i*(b[0]-a[0])/steps,a[1]+i*(b[1]-a[1])/steps
                if contains(polygons,x,y):
                    append(x,y,a[2],'source_contour_densified',0.0,a[2],-1)
    coords = [p for polygon in polygons for ring in polygon for p in ring]
    xmin,xmax = min(p[0] for p in coords),max(p[0] for p in coords)
    ymin,ymax = min(p[1] for p in coords),max(p[1] for p in coords)
    nx,ny = math.ceil((xmax-xmin)/SPACING),math.ceil((ymax-ymin)/SPACING)
    for j in range(ny):
        y = ymin+(j+.5)*SPACING
        for i in range(nx):
            x = xmin+(i+.5)*SPACING
            if contains(polygons,x,y):
                d,dist,near,segment = contours.estimate(x,y)
                append(x,y,d,'interpolated_interior',dist,near,segment)
    # Independent, brute-force verification of indexed nearest-segment search.
    max_nearest_error = 0.0
    for row in rows[::max(1,len(rows)//25)]:
        x,y = row['x'],row['y']
        brute = []
        for idx,(ax,ay,dx,dy,l2,z) in enumerate(contours.segments):
            t=max(0.,min(1.,((x-ax)*dx+(y-ay)*dy)/l2))
            brute.append(((x-ax-t*dx)**2+(y-ay-t*dy)**2,idx,z))
        expected = min(brute)
        actual = contours.nearest(x,y,1)[0]
        max_nearest_error = max(max_nearest_error,abs(math.sqrt(expected[0])-math.sqrt(actual[0])))
        assert expected[1:] == actual[1:]
    assert max_nearest_error < 1e-6
    projection_error = max(math.hypot(utm(*lonlat(row['x'],row['y']))[0]-row['x'],
                                     utm(*lonlat(row['x'],row['y']))[1]-row['y'])
                           for row in rows[::max(1,len(rows)//50)])
    assert projection_error<0.02
    assert all(row['depth']==row['nearest_depth'] for row in rows if row['role']=='boundary_nearest_contour')
    # Thirty-metre DEM grid: padded so bilinear interpolation is defined at edges.
    left = math.floor((xmin-90)/30)*30
    top = math.ceil((ymax+90)/30)*30
    width = math.ceil((xmax+90-left)/30)
    height = math.ceil((top-ymin+90)/30)
    tiles = []
    for row in range(0,height,2048):
        for col in range(0,width,4096):
            w,h = min(4096,width-col),min(2048,height-row)
            tiles.append(dict(id=f'c{col}_r{row}',col=col,row=row,width=w,height=h,
                              crs='EPSG:32640',transform=[30,0,left+col*30,0,-30,top-row*30]))
    plan = dict(dataset='USGS/SRTMGL1_003',band='elevation',crs='EPSG:32640',
                transform=[30,0,left,0,-30,top],width=width,height=height,tiles=tiles,
                row_count=len(rows),boundary_count=len(boundary_xy))
    state = dict(rows=rows,lines=lines,polygons=polygons,feature=feature,contours=contours,
                 plan=plan,source_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
                 boundary_sha256=hashlib.sha256(json.dumps(geom,sort_keys=True).encode()).hexdigest(),
                 source_total=source_total,source_inside=source_inside,grid=dict(xmin=xmin,ymin=ymin,nx=nx,ny=ny),
                 projection_error=projection_error,nearest_error=max_nearest_error)
    return json.dumps(dict(plan=plan,summary=dict(rows=len(rows),roles=dict(Counter(r['role'] for r in rows)),
                       source_vertices=source_total,source_vertices_inside=source_inside,
                       aquifer_properties=feature['properties'],projection_roundtrip_error_m=projection_error)))


class NpyRaster:
    def __init__(self, filename, tile):
        self.raw = open(filename,'rb').read()
        raw = self.raw
        if raw[:6]!=b'\x93NUMPY':
            raise ValueError('Not an NPY raster')
        major = raw[6]
        length_bytes = 2 if major==1 else 4
        n = int.from_bytes(raw[8:8+length_bytes],'little')
        header = ast.literal_eval(raw[8+length_bytes:8+length_bytes+n].decode('latin1'))
        if header['fortran_order']:
            raise ValueError('Fortran NPY is not supported')
        if tuple(header['shape'])!=(tile['height'],tile['width']):
            raise ValueError('Unexpected DEM raster shape: '+str(header['shape']))
        descr = header['descr']
        fields = descr if isinstance(descr,list) else [('elevation',descr)]
        stride,offset,reader = 0,None,None
        codes={'i1':'b','u1':'B','i2':'h','u2':'H','i4':'i','u4':'I','i8':'q','u8':'Q','f4':'f','f8':'d'}
        for field in fields:
            name,dtype = field[:2]
            if len(field)>2:
                raise ValueError('Unexpected subarray in DEM dtype')
            endian = dtype[0] if dtype[0] in '<>|=' else '='
            kind = dtype[1:] if dtype[0] in '<>|=' else dtype
            code = codes.get(kind)
            if code is None:
                raise ValueError('Unsupported DEM dtype: '+dtype)
            fmt=struct.Struct(('<' if endian in '|=' else endian)+code)
            if name=='elevation':
                offset,reader = stride,fmt
            stride+=fmt.size
        if reader is None:
            raise ValueError('Missing elevation field')
        self.offset=8+length_bytes+n+offset
        self.stride,self.reader,self.tile=stride,reader,tile
        assert len(raw)>=8+length_bytes+n+stride*tile['width']*tile['height']

    def pixel(self, col, row):
        t=self.tile
        return self.reader.unpack_from(self.raw,self.offset+((row-t['row'])*t['width']+col-t['col'])*self.stride)[0]


def finish(dem_files_text, retrieved_utc):
    s=state
    if s is None:
        raise ValueError('prepare() must be called first')
    dem_files=json.loads(dem_files_text)
    rasters=[NpyRaster(item['path'],item['tile']) for item in dem_files]
    left,top=s['plan']['transform'][2],s['plan']['transform'][5]
    def pixel(c,r):
        for raster in rasters:
            t=raster.tile
            if t['col']<=c<t['col']+t['width'] and t['row']<=r<t['row']+t['height']:
                value=float(raster.pixel(c,r))
                if not math.isfinite(value) or value<=0 or value>6000:
                    raise ValueError(f'Missing or implausible SRTM value at pixel {c},{r}: {value}')
                return value
        raise ValueError('DEM tile coverage missing')
    def ground(x,y):
        # GEE affine transforms address pixel corners, sample at cell centres.
        c,r=(x-left)/30-.5,(top-y)/30-.5
        c0,r0=math.floor(c),math.floor(r)
        fx,fy=c-c0,r-r0
        return ((1-fy)*((1-fx)*pixel(c0,r0)+fx*pixel(c0+1,r0))
                +fy*((1-fx)*pixel(c0,r0+1)+fx*pixel(c0+1,r0+1)))
    output,audit=io.StringIO(newline=''),io.StringIO(newline='')
    writer,aw=csv.writer(output,lineterminator='\n'),csv.writer(audit,lineterminator='\n')
    writer.writerow(['lon','lat','bedrock_msl'])
    aw.writerow(['lon','lat','bedrock_msl','ground_msl','bedrock_depth_m','point_role',
                 'nearest_contour_depth_m','distance_to_nearest_contour_m','source_segment_index'])
    preview=[]
    for row in s['rows']:
        elevation=ground(row['x'],row['y'])
        bottom=elevation-row['depth']
        assert bottom<=elevation and math.isfinite(bottom)
        row.update(ground=elevation,bedrock=bottom)
        xyz=[f"{row['lon']:.9f}",f"{row['lat']:.9f}",f'{bottom:.3f}']
        writer.writerow(xyz)
        aw.writerow(xyz+[f'{elevation:.3f}',f"{row['depth']:.6f}",row['role'],
                         f"{row['nearest_depth']:.3f}",f"{row['nearest_distance']:.3f}",row['segment']])
        preview.append([row['lon'],row['lat'],bottom,elevation,row['depth'],row['role'],row['nearest_distance'],row['x'],row['y']])
    parsed=list(csv.DictReader(io.StringIO(output.getvalue())))
    assert len(parsed)==len(s['rows'])
    assert len({(r['lon'],r['lat']) for r in parsed})==len(parsed)
    assert all(-180<float(r['lon'])<180 and -90<float(r['lat'])<90 and math.isfinite(float(r['bedrock_msl'])) for r in parsed)
    bnd=[r for r in s['rows'] if r['role'].startswith('boundary_')]
    if 'continuous_model' not in s:
        assert all(r['depth']==r['nearest_depth'] and r['depth']>0 for r in bnd)
    # Preserve the supplied geometry exactly in the output boundary GeoJSON.
    boundary_feature=dict(type='Feature',geometry=s['feature']['geometry'],properties=dict(s['feature']['properties'],
        bedrock_boundary_method='nearest original BEDROC segment; depth is not forced to zero',
        geometry_source='Data/AQUIFER.geojson; unchanged'))
    roles=dict(Counter(r['role'] for r in s['rows']))
    metadata=dict(aquifer='مشهد',csv_columns=['lon','lat','bedrock_msl'],record_count=len(parsed),records_by_role=roles,
        source_file='.tmp/BedRock.geojson',source_sha256=s['source_sha256'],source_crs='EPSG:32640',output_crs='EPSG:4326',
        source_depth_definition='BEDROC = depth below local ground, metres; explicitly confirmed by user on 2026-11-09',
        source_depth_range_m=[min(s['contours'].levels),max(s['contours'].levels)],
        original_source_vertices=s['source_total'],original_source_vertices_inside_aquifer=s['source_inside'],
        original_source_vertices_outside_aquifer=s['source_total']-s['source_inside'],
        boundary_geometry_source='Data/AQUIFER.geojson, feature AQUIFER=مشهد, unchanged',boundary_geometry_sha256=s['boundary_sha256'],
        boundary_method='Depth equals BEDROC of the nearest original line segment in EPSG:32640. Preserve all ring vertices; densify to <=500m. No zero/shallow boundary assumption and no boundary taper.',
        interior_method='IDW p=2 of four nearest distinct BEDROC depth groups; distance is to the closest original segment in each group. Exact source depths preserved on source controls.',
        interior_grid_spacing_m=SPACING,boundary_max_spacing_m=SPACING,contour_max_spacing_m=SPACING,
        dem=dict(gee_asset='USGS/SRTMGL1_003',band='elevation',nominal_native_resolution='1 arc-second (~30m)',
                 downloaded_grid_resolution_m=30,download_crs='EPSG:32640',gee_resampling='nearest/default to UTM grid',
                 client_sampling='bilinear interpolation between four downloaded DEM cell centres',
                 vertical_datum='EGM96 orthometric height (approximate MSL), metres',epoch='SRTM February 2000',retrieved_utc=retrieved_utc,
                 catalog='https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003',
                 datum_reference='https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-shuttle-radar-topography-mission-srtm'),
        formula='bedrock_msl = SRTM ground orthometric elevation - BEDROC depth (m)',
        bedrock_msl_range_m=[min(r['bedrock'] for r in s['rows']),max(r['bedrock'] for r in s['rows'])],
        ground_msl_range_m=[min(r['ground'] for r in s['rows']),max(r['ground'] for r in s['rows'])],
        boundary_nearest_distance_range_m=[min(r['nearest_distance'] for r in bnd),max(r['nearest_distance'] for r in bnd)],
        boundary_samples_over_5km_from_contours=sum(r['nearest_distance']>5000 for r in bnd),
        validation=dict(projection_roundtrip_max_error_m=s['projection_error'],nearest_search_vs_bruteforce_max_error_m=s['nearest_error'],
                        boundary_nearest_value_exact=True,no_zero_boundary_depth=True,missing_dem_samples=0,unique_coordinates=True,
                        all_bedrock_below_local_dem=True,csv_three_column_schema=True),
        execution='All coordinate transforms, spatial queries, depth interpolation, DEM sampling, subtraction, validation and CSV generation ran client-side in a Pyodide web worker. Host only authenticated, downloaded GEE DEM bytes, served static files, and saved browser outputs.',
        known_limitations=[
            'Derived bedrock estimates, not measured bedrock elevations or a newly surveyed aquifer boundary.',
            'Nearest-contour assignment on the existing aquifer boundary is a user-requested extrapolation; accuracy decreases with distance to source lines.',
            'All source contours, including ones outside the project aquifer polygon, support interior and boundary estimation. Outside source controls are not exported as aquifer points.',
            'Depth below ground is referenced to SRTM epoch and terrain/surface representation; buildings, vegetation and changes since 2000 can bias the inferred bedrock height.',
            'EGM96 heights are approximate mean-sea-level heights; verify compatibility or apply a datum transformation before combining with local LEVEL_MSL surveys.',
            'Synthetic grid and boundary samples are not independent observations. IDW and decimal precision do not imply measured resolution or accuracy.',
            'Boundary uses nearest contour exactly; no additional transition band is imposed. Interior IDW and boundary extrapolation may differ close to the boundary.',
        ])
    # Export original contour vertices separately, including outside controls.
    source_out=io.StringIO(newline='')
    sw=csv.writer(source_out,lineterminator='\n')
    sw.writerow(['lon','lat','bedrock_depth_m','inside_aquifer','source_line_index','source_vertex_index'])
    for li,line in enumerate(s['lines']):
        for vi,(x,y,depth) in enumerate(line):
            lon,lat=lonlat(x,y)
            sw.writerow([f'{lon:.9f}',f'{lat:.9f}',f'{depth:.3f}',int(contains(s['polygons'],x,y)),li,vi])
    rings_preview=[[[[x/1000,y/1000] for x,y in ring] for ring in polygon] for polygon in s['polygons']]
    source_preview=[[[x/1000,y/1000,depth] for x,y,depth in line] for line in s['lines']]
    grid=s['grid']
    surface=[[None for _ in range(grid['nx'])] for _ in range(grid['ny'])]
    for row in s['rows']:
        if row['role']=='interpolated_interior':
            i=round((row['x']-grid['xmin'])/SPACING-.5)
            j=round((row['y']-grid['ymin'])/SPACING-.5)
            surface[j][i]=row['bedrock']
    preview_surface=dict(x=[(grid['xmin']+(i+.5)*SPACING)/1000 for i in range(grid['nx'])],
                         y=[(grid['ymin']+(j+.5)*SPACING)/1000 for j in range(grid['ny'])],z=surface)
    return json.dumps(dict(csv=output.getvalue(),audit=audit.getvalue(),source=source_out.getvalue(),metadata=metadata,
                           boundary=dict(type='FeatureCollection',features=[boundary_feature]),
                           preview=dict(points=preview,rings=rings_preview,source=source_preview,surface=preview_surface,metadata=metadata)),ensure_ascii=False,allow_nan=False)

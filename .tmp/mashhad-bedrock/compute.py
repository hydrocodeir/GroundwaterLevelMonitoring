"""Executed exclusively in a browser Pyodide worker (Python standard library)."""
import json
import math
import heapq


def build(text):
    source = json.loads(text)
    if '32640' not in str(source.get('crs', {})):
        raise ValueError('Expected EPSG:32640 (UTM zone 40N).')
    lines, segments, points, levels = [], [], [], set()
    for feature in source['features']:
        value = feature.get('properties', {}).get('BEDROC')
        if value is None:
            continue
        z = float(value)
        if not math.isfinite(z):
            continue
        geom = feature['geometry']
        if geom['type'] == 'MultiLineString':
            parts = geom['coordinates']
        elif geom['type'] == 'LineString':
            parts = [geom['coordinates']]
        else:
            raise ValueError('Unexpected geometry: ' + geom['type'])
        for part in parts:
            line = [[float(p[0]), float(p[1]), z] for p in part]
            if not all(math.isfinite(v) for p in line for v in p):
                raise ValueError('Nonfinite coordinate')
            if len(line) < 2:
                continue
            lines.append(line)
            points.extend((p[0], p[1]) for p in line)
            levels.add(z)
            for a, b in zip(line, line[1:]):
                dx, dy = b[0]-a[0], b[1]-a[1]
                length2 = dx*dx+dy*dy
                if length2:
                    segments.append((a[0], a[1], dx, dy, length2, z))
    if not segments:
        raise ValueError('No usable BEDROC contours.')
    pts = sorted(set(points))
    def cross(o,a,b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower)>1 and cross(lower[-2],lower[-1],p)<=0: lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper)>1 and cross(upper[-2],upper[-1],p)<=0: upper.pop()
        upper.append(p)
    hull = lower[:-1]+upper[:-1]
    edges = list(zip(hull,hull[1:]+hull[:1]))
    xmin,xmax = min(p[0] for p in pts),max(p[0] for p in pts)
    ymin,ymax = min(p[1] for p in pts),max(p[1] for p in pts)
    scale = max(xmax-xmin,ymax-ymin)
    step = scale/130
    nx,ny = math.ceil((xmax-xmin)/step)+1,math.ceil((ymax-ymin)/step)+1
    xs = [xmin+i*(xmax-xmin)/(nx-1) for i in range(nx)]
    ys = [ymin+i*(ymax-ymin)/(ny-1) for i in range(ny)]
    # A spatial bin indexes exact line segments, including long segments.
    # Query a 5 km neighbourhood and mask cells without a nearby source line.
    radius, bin_size = 5000.0, 5000.0
    bins = {}
    for s in segments:
        ax,ay,dx,dy,_,_ = s
        for ix in range(math.floor(min(ax,ax+dx)/bin_size),math.floor(max(ax,ax+dx)/bin_size)+1):
            for iy in range(math.floor(min(ay,ay+dy)/bin_size),math.floor(max(ay,ay+dy)/bin_size)+1):
                bins.setdefault((ix,iy),[]).append(s)
    grid,valid = [],0
    for y in ys:
        row = []
        for x in xs:
            if any(cross(a,b,(x,y)) < -1e-6 for a,b in edges):
                row.append(None)
                continue
            bx,by = math.floor(x/bin_size),math.floor(y/bin_size)
            distances = {}
            for ix in range(bx-1,bx+2):
                for iy in range(by-1,by+2):
                    for ax,ay,dx,dy,l2,z in bins.get((ix,iy),()):
                        t = max(0.,min(1.,((x-ax)*dx+(y-ay)*dy)/l2))
                        d2 = (x-ax-t*dx)**2+(y-ay-t*dy)**2
                        if d2 < distances.get(z,float('inf')): distances[z] = d2
            nearest = heapq.nsmallest(4,((d,z) for z,d in distances.items()))
            if not nearest or nearest[0][0] > radius**2:
                row.append(None)
                continue
            if nearest[0][0] < 1e-8:
                value = nearest[0][1]
            else:
                # IDW p=2 to nearest distinct contour values, using exact
                # point-to-segment distances rather than vertex density.
                weights = [(1/max(d,1e-8),z) for d,z in nearest]
                value = sum(w*z for w,z in weights)/sum(w for w,z in weights)
            row.append(round(value,4))
            valid += 1
        grid.append(row)
    assert valid > 0
    assert all(min(levels)-1e-8 <= z <= max(levels)+1e-8 for row in grid for z in row if z is not None)
    return json.dumps(dict(lines=lines,x=xs,y=ys,z=grid,meta=dict(
        features=len(source['features']),lines=len(lines),vertices=len(points),
        segments=len(segments),levels=sorted(levels),minimum=min(levels),maximum=max(levels),
        bounds=[xmin,ymin,xmax,ymax],nx=nx,ny=ny,valid=valid,
        crs='EPSG:32640',unit='unspecified',method='IDW p=2; nearest four distinct contour values; point-to-segment distances',
        mask='convex hull; maximum nearest-contour distance 5000 m; not the aquifer boundary',
        grid_spacing_m=step)),allow_nan=False)

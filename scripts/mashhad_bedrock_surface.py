"""Continuous contour surface and spatial validation; browser Pyodide only.

Execute mashhad_bedrock_compute.py first. No boundary depths are observations.
"""
import numpy as np
from scipy.interpolate import RBFInterpolator
from scipy.spatial import ConvexHull, Delaunay, cKDTree

SURFACE_VERSION = '2.0-contour-extension'
CANDIDATES = ['nearest_baseline', 'idw_baseline', 'linear_rbf', 'thin_plate',
              'thin_plate_damped_5km', 'thin_plate_damped_10km']


def uniform_controls(lines, spacing=1000.0):
    """Equal arc-length sampling avoids overweighting densely digitized vertices."""
    values = {}
    for line in lines:
        arr=np.asarray(line,dtype=float)
        distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(arr[:,:2],axis=0),axis=1))]
        if distance[-1]==0:
            continue
        positions=np.linspace(0,distance[-1],max(2,math.ceil(distance[-1]/spacing)+1))
        xy=np.c_[np.interp(positions,distance,arr[:,0]),np.interp(positions,distance,arr[:,1])]
        for p in xy:
            key=tuple(np.round(p,3))
            z=float(arr[0,2])
            if key in values and abs(values[key][2]-z)>1e-8:
                raise ValueError('Conflicting depths at the same contour coordinate')
            values[key]=[float(p[0]),float(p[1]),z]
    controls=np.array(list(values.values()))
    return controls[:,:2]/1000.0,controls[:,2]


def fit_rbf(xy,z,kernel):
    return RBFInterpolator(xy,z,kernel=kernel,degree=1,smoothing=0)


def damped_extension(model,train,query,length):
    """Inside the hull: TPS. Outside: hull tangent, gradually flattening.

    L is selected by edge holdouts, not an asserted geological boundary depth.
    This keeps value and first normal derivative continuous at the data hull.
    """
    hull=ConvexHull(train)
    ring=train[hull.vertices]
    inside=Delaunay(ring).find_simplex(query)>=0
    out=model(query)
    idx=np.flatnonzero(~inside)
    if not len(idx):
        return out
    q=query[idx]
    best=np.full(len(q),np.inf)
    nearest=np.zeros_like(q)
    for a,b in zip(ring,np.roll(ring,-1,axis=0)):
        v=b-a
        t=np.clip(((q-a)@v)/(v@v),0,1)
        foot=a+t[:,None]*v
        distance=np.sum((q-foot)**2,axis=1)
        improve=distance<best
        best[improve]=distance[improve]
        nearest[improve]=foot[improve]
    base=model(nearest)
    h=.05
    gx=(model(nearest+[h,0])-model(nearest-[h,0]))/(2*h)
    gy=(model(nearest+[0,h])-model(nearest-[0,h]))/(2*h)
    delta=q-nearest
    r=np.sqrt(best)
    factor=np.divide(length*(-np.expm1(-r/length)),r,out=np.ones_like(r),where=r>1e-10)
    out[idx]=base+(gx*delta[:,0]+gy*delta[:,1])*factor
    return out


def predict_candidates(train,z,query,names=CANDIDATES):
    result={}
    if 'nearest_baseline' in names:
        _,indices=cKDTree(train).query(query)
        result['nearest_baseline']=z[indices]
    if 'idw_baseline' in names:
        levels=np.unique(z)
        distances=np.array([cKDTree(train[z==level]).query(query)[0] for level in levels]).T
        order=np.argsort(distances,axis=1)[:,:min(4,len(levels))]
        ds=np.take_along_axis(distances,order,axis=1)
        zs=levels[order]
        weights=1/np.maximum(ds,1e-9)**2
        result['idw_baseline']=np.sum(weights*zs,axis=1)/weights.sum(axis=1)
    if 'linear_rbf' in names:
        result['linear_rbf']=fit_rbf(train,z,'linear')(query)
    if any(name.startswith('thin_plate') for name in names):
        model=fit_rbf(train,z,'thin_plate_spline')
        if 'thin_plate' in names:
            result['thin_plate']=model(query)
        for length in (5,10):
            name=f'thin_plate_damped_{length}km'
            if name in names:
                result[name]=damped_extension(model,train,query,length)
    return result


def assess_models(source_text,aquifers_text):
    prepared=json.loads(prepare(source_text,aquifers_text))
    xy,z=uniform_controls(state['lines'],1000.0)
    folds=[]
    # Entire contour levels are withheld, never random adjacent vertices.
    for level in np.unique(z):
        test=z==level
        folds.append((f'depth_{level:g}','whole_depth_level',~test,test))
    centered=xy-xy.mean(axis=0)
    _,_,axes=np.linalg.svd(centered,full_matrices=False)
    projected=centered@axes.T
    # Strip edge data and a 2km spatial buffer to mimic extrapolation.
    for axis in (0,1):
        for side in ('low','high'):
            threshold=np.quantile(projected[:,axis],.15 if side=='low' else .85)
            if side=='low':
                test=projected[:,axis]<=threshold
                train=projected[:,axis]>threshold+2.0
            else:
                test=projected[:,axis]>=threshold
                train=projected[:,axis]<threshold-2.0
            if train.sum()<20:
                raise ValueError('Insufficient controls after spatial buffer')
            folds.append((f'axis_{axis}_{side}','buffered_edge',train,test))
    evaluations=[]
    for name,kind,train,test in folds:
        predictions=predict_candidates(xy[train],z[train],xy[test])
        for method,raw in predictions.items():
            pred=np.maximum(0,raw)
            error=pred-z[test]
            evaluations.append(dict(fold=name,kind=kind,method=method,train_count=int(train.sum()),test_count=int(test.sum()),
                rmse_m=float(np.sqrt(np.mean(error**2))),mae_m=float(np.mean(abs(error))),bias_m=float(np.mean(error)),
                max_abs_error_m=float(np.max(abs(error))),negative_raw_predictions=int(np.sum(raw<0))))
        print('Validated '+name,flush=True)
    scores=[]
    for method in CANDIDATES:
        items=[r for r in evaluations if r['method']==method]
        level=float(np.mean([r['rmse_m'] for r in items if r['kind']=='whole_depth_level']))
        edge=float(np.mean([r['rmse_m'] for r in items if r['kind']=='buffered_edge']))
        scores.append(dict(method=method,mean_depth_level_rmse_m=level,mean_edge_rmse_m=edge,
                           selection_score_m=.5*(level+edge)))
    eligible=[r for r in scores if not r['method'].endswith('_baseline')]
    selected=min(eligible,key=lambda r:r['selection_score_m'])['method']
    assessment=dict(version=SURFACE_VERSION,source_sha256=state['source_sha256'],controls=len(z),
        control_spacing_m=1000,selected_method=selected,scores=scores,folds=evaluations,
        selection='Lowest equally weighted mean of whole-depth-level RMSE and buffered-edge RMSE among continuous RBF models. Baselines are reported, not eligible because a continuous boundary extension is requested.',
        note='These are internal pseudo-extrapolation tests. No measured boundary depths exist; cross-validation errors do not establish boundary accuracy or statistical confidence intervals.')
    state['assessment']=assessment
    return json.dumps(dict(summary=prepared['summary'],assessment=assessment,plan=prepared['plan']),allow_nan=False)


def restore_for_fit(source_text,aquifers_text,assessment_text):
    prepared=json.loads(prepare(source_text,aquifers_text))
    assessment=json.loads(assessment_text)
    if assessment['version']!=SURFACE_VERSION or assessment['source_sha256']!=state['source_sha256']:
        raise ValueError('Assessment does not match current source/version')
    state['assessment']=assessment
    return json.dumps(prepared)


def fit_continuous_surface():
    s=state
    assessment=s['assessment']
    selected=assessment['selected_method']
    # Every original vertex plus equal-arc-length samples anchors the final fit.
    xy,z=uniform_controls(s['lines'],500.0)
    controls={tuple(np.round(p*1000,3)):[p[0],p[1],depth] for p,depth in zip(xy,z)}
    for line in s['lines']:
        for x,y,depth in line:
            key=(round(x,3),round(y,3))
            if key in controls and abs(controls[key][2]-depth)>1e-8:
                raise ValueError('Conflicting original contour vertex depths')
            controls[key]=[x/1000,y/1000,depth]
    arr=np.array(list(controls.values()))
    xy,z=arr[:,:2],arr[:,2]
    query=np.array([[r['x']/1000,r['y']/1000] for r in s['rows']])
    names=list(dict.fromkeys([selected,'thin_plate','linear_rbf']))
    predictions=predict_candidates(xy,z,query,names)
    raw=predictions[selected]
    primary=np.maximum(0,raw)
    ensemble=np.array([np.maximum(0,predictions[k]) for k in names])
    spread=ensemble.max(axis=0)-ensemble.min(axis=0)
    outside=Delaunay(xy).find_simplex(query)<0
    kernel='linear' if selected=='linear_rbf' else 'thin_plate_spline'
    # Verify the fitted function itself against input lines, including points
    # between all original vertices; merely resetting exported source rows
    # must not be mistaken for contour fidelity.
    model=fit_rbf(xy,z,kernel)
    check_xy,check_z=uniform_controls(s['lines'],125.0)
    residual=model(check_xy)-check_z
    at_controls=model(xy)-z
    if np.max(abs(at_controls))>1e-4:
        raise ValueError('Final model fails interpolation constraints')
    if not np.all(np.isfinite(primary)):
        raise ValueError('Nonfinite extrapolated depths')
    source_errors=[]
    for i,row in enumerate(s['rows']):
        original=row['depth']
        if row['role'].startswith('source_contour'):
            source_errors.append(float(primary[i]-original))
            # Measured/source depths remain exact in the deliverable.
            depth=original
        else:
            depth=float(primary[i])
        if row['role']=='boundary_nearest_contour':
            row['role']='boundary_continuous_extension'
        row.update(depth=depth,unconstrained_depth=float(raw[i]),outside_hull=bool(outside[i]),
                   sensitivity_spread=float(spread[i]),depth_floor=bool(raw[i]<0))
    bidx=np.array([i for i,r in enumerate(s['rows']) if r['role'].startswith('boundary_')])
    s['continuous_model']=dict(method=selected,training_controls=len(z),training_spacing_m=500,
        exact_source_vertex_max_error_m=float(np.max(abs(at_controls))),
        contour_check_spacing_m=125,contour_check_rmse_m=float(np.sqrt(np.mean(residual**2))),
        contour_check_max_abs_error_m=float(np.max(abs(residual))),
        boundary_depth_range_m=[float(primary[bidx].min()),float(primary[bidx].max())],
        model_depth_range_m=[float(primary.min()),float(primary.max())],
        raw_boundary_depth_range_m=[float(raw[bidx].min()),float(raw[bidx].max())],
        boundary_depth_floor_count=int(np.sum(raw[bidx]<0)),outside_hull_count=int(outside.sum()),
        boundary_outside_hull_count=int(outside[bidx].sum()),
        sensitivity_models=names,sensitivity_spread_max_m=float(spread.max()),
        boundary_sensitivity_spread_max_m=float(spread[bidx].max()),
        physical_constraint='depth=max(0, model_depth), so inferred bedrock cannot exceed DEM. Zero is never imposed along the aquifer boundary.',
        extension=('TPS inside the convex hull; tangent continuation outside, with slope damped exponentially over '+('5' if '5km' in selected else '10')+' km.' if 'damped' in selected else 'One global RBF surface is evaluated continuously both inside and beyond the source contours.'),
        assessment=assessment)
    return json.dumps(s['continuous_model'],allow_nan=False)


def finish_continuous(dem_files_text,retrieved_utc):
    result=json.loads(finish(dem_files_text,retrieved_utc))
    s=state
    info=s['continuous_model']
    metadata=result['metadata']
    metadata.update(version=SURFACE_VERSION,continuous_surface=info,
        boundary_method='Evaluate the same validated continuous depth surface on the existing aquifer boundary. No nearest-contour or fixed-depth boundary assignment.',
        interior_method='Global interpolating RBF constrained by all original contour vertices and samples at <=500m arc length. Method selected by whole-contour-level and buffered-edge withholding tests.',
        processing_references=['https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html',
            'https://docs.scipy.org/doc/scipy/tutorial/interpolate/extrapolation_examples.html'])
    metadata['validation'].pop('boundary_nearest_value_exact',None)
    metadata['validation'].pop('no_zero_boundary_depth',None)
    metadata['validation'].pop('all_bedrock_below_local_dem',None)
    metadata['validation'].update(source_vertex_max_error_m=info['exact_source_vertex_max_error_m'],
        contour_125m_check_rmse_m=info['contour_check_rmse_m'],
        all_bedrock_at_or_below_local_dem=True)
    metadata['known_limitations']=[
        'Interior depth contours do not uniquely determine depth at the aquifer boundary. The output is a modelled extension, not measured bedrock.',
        'Spatial withholding tests support method selection only in geometries represented by the available contours; they do not validate remote boundary values.',
        'Depth is constrained to be nonnegative. Any zero inferred from a negative prediction indicates a model-limit condition, not confirmed bedrock outcrop.',
        'The audit sensitivity spread is disagreement between model variants, not a confidence interval.',
        'Some existing aquifer boundary locations are over 20km from the closest original contour. These are weakly constrained and should be checked using geological maps, geophysics or boreholes.',
        'SRTM is a February 2000 surface/terrain model on EGM96. Surface change, vegetation/buildings and datum differences can bias bedrock_msl.',
        'Synthetic samples and output decimal precision do not establish survey accuracy.']
    result['boundary']['features'][0]['properties']['bedrock_boundary_method']=metadata['boundary_method']
    # Add explicit modelling diagnostics without changing the three-column CSV.
    table=list(csv.reader(io.StringIO(result['audit'])))
    out=io.StringIO(newline='')
    writer=csv.writer(out,lineterminator='\n')
    writer.writerow(table[0]+['model_raw_depth_m','outside_contour_convex_hull','model_sensitivity_spread_m','nonnegative_depth_floor_applied'])
    for vals,row in zip(table[1:],s['rows']):
        writer.writerow(vals+[f"{row['unconstrained_depth']:.6f}",int(row['outside_hull']),f"{row['sensitivity_spread']:.3f}",int(row['depth_floor'])])
    result['audit']=out.getvalue()
    result['preview']['metadata']=metadata
    result['preview']['depth_surface']=[[None if v is None else 0 for v in line] for line in result['preview']['surface']['z']]
    grid=s['grid']
    for row in s['rows']:
        if row['role']=='interpolated_interior':
            i=round((row['x']-grid['xmin'])/SPACING-.5)
            j=round((row['y']-grid['ymin'])/SPACING-.5)
            result['preview']['depth_surface'][j][i]=row['depth']
    result['preview']['support']=[[r['lon'],r['lat'],r['nearest_distance'],r['sensitivity_spread'],r['outside_hull']] for r in s['rows']]
    return json.dumps(result,ensure_ascii=False,allow_nan=False)

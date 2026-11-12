"""Lossless-value GeoTIFF -> pixel-centre CSV, executed by browser Pyodide."""
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image


def convert_subsidence_tiff(source_path,csv_path,declaration):
    image=Image.open(source_path)
    if getattr(image,'n_frames',1)!=1 or len(image.getbands())!=1:
        raise ValueError('یک TIFF تک‌باند تک‌زمانه لازم است.')
    tags=image.tag_v2
    directory=tags.get(34735,())
    keys={int(directory[i]):tuple(directory[i+1:i+4]) for i in range(4,len(directory),4)}
    crs_key=keys.get(3072) or keys.get(2048)
    if not crs_key or crs_key[0]!=0 or crs_key[2]==32767:
        raise ValueError('کد EPSG معتبر در TIFF لازم است.')
    crs=f'EPSG:{crs_key[2]}'
    pixel_is_point=keys.get(1025,(0,1,1))[2]==2
    matrix=tags.get(34264)
    if matrix:
        a,b,c,d,e,f=matrix[0],matrix[1],matrix[3],matrix[4],matrix[5],matrix[7]
    else:
        scale=tags.get(33550);tie=tags.get(33922)
        if not scale or not tie:raise ValueError('تبدیل مختصات پیکسل در TIFF موجود نیست.')
        a,b,d,e=float(scale[0]),0.,0.,-float(scale[1])
        c=float(tie[3])-a*tie[0];f=float(tie[4])-e*tie[1]
    if pixel_is_point:c-=(a+b)/2;f-=(d+e)/2
    affine=[a,b,c,d,e,f]
    if abs(a*e-b*d)<1e-20:raise ValueError('تبدیل مکانی TIFF تکین است.')
    raw=np.asarray(image,dtype=np.float32)
    nodata=tags.get(42113)
    valid=np.isfinite(raw)
    if nodata is not None:
        try:
            sentinel=float(str(nodata).strip('\x00'))
            if math.isfinite(sentinel):valid &= raw!=sentinel
        except ValueError:raise ValueError('NoData در TIFF قابل خواندن نیست.')
    rows,cols=np.nonzero(valid)
    if not len(rows):raise ValueError('TIFF مقدار معتبر ندارد.')
    x=a*(cols+.5)+b*(rows+.5)+c;y=d*(cols+.5)+e*(rows+.5)+f
    if crs=='EPSG:4326':lon,lat=x,y
    else:
        from pyproj import Transformer
        lon,lat=Transformer.from_crs(crs,'EPSG:4326',always_xy=True).transform(x,y)
    unit=declaration['unit']
    if unit not in ('mm','cm','m'):raise ValueError('واحد منبع باید مشخص شود.')
    factor={'mm':1.,'cm':10.,'m':1000.}[unit]
    values=raw[rows,cols]
    with open(csv_path,'w',newline='',encoding='utf-8') as stream:
        writer=csv.writer(stream)
        writer.writerow(['longitude','latitude','cumulative_mm','pixel_row','pixel_column'])
        writer.writerows((format(float(xx),'.15g'),format(float(yy),'.15g'),format(float(value)*factor,'.9g'),int(row),int(col))
                         for xx,yy,value,row,col in zip(lon,lat,values,rows,cols))
    width,height=image.size
    # Densify the perimeter for a useful geographic registry extent in projected CRSs.
    t=np.linspace(0,1,129)
    edge_col=np.concatenate([t*width,np.full_like(t,width),(1-t)*width,np.zeros_like(t)])
    edge_row=np.concatenate([np.zeros_like(t),t*height,np.full_like(t,height),(1-t)*height])
    ex=a*edge_col+b*edge_row+c;ey=d*edge_col+e*edge_row+f
    if crs!='EPSG:4326':ex,ey=Transformer.from_crs(crs,'EPSG:4326',always_xy=True).transform(ex,ey)
    metadata={'format_version':1,'source_file':Path(source_path).name,
              'source_sha256':hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
              'csv_sha256':hashlib.sha256(Path(csv_path).read_bytes()).hexdigest(),
              'csv_columns':['longitude','latitude','cumulative_mm','pixel_row','pixel_column'],
              'quantity':'cumulative','unit':'mm','source_unit':unit,
              'component':declaration['component'],'direction':declaration['direction'],
              'calendar_basis':declaration['calendar_basis'],'start_year':declaration['start_year'],
              'end_year':declaration['end_year'],'duration_years':declaration['duration_years'],
              'period_precision':'year','provenance':'Unit, sign, vertical component and year range supplied by user; absent from TIFF tags.',
              'raster_grid':{'crs':crs,'width':width,'height':height,'affine':affine,
                             'pixel_reference':'area_corner','source_pixel_is_point':pixel_is_point},
              'extent_wgs84':[float(np.min(ex)),float(np.min(ey)),float(np.max(ex)),float(np.max(ey))],
              'statistics':{'total_pixels':int(raw.size),'valid_pixels':int(len(values)),
                            'nodata_pixels':int(raw.size-len(values)),
                            'minimum_signed_mm':float(values.min())*factor,'maximum_signed_mm':float(values.max())*factor,
                            'negative_pixels':int(np.sum(values<0)),'zero_pixels':int(np.sum(values==0)),
                            'positive_pixels':int(np.sum(values>0))},
              'notes':['Every finite valid pixel is exported once at its centre; zero values are retained; NaN/NoData/Inf are excluded.',
                       f"Signed source displacements are preserved. {'Positive' if declaration['direction']=='down' else 'Negative'} means subsidence for the supplied declaration.",
                       'No annual time series is reconstructed. Division by declared duration only yields a period-average rate.',
                       'Start/end days and months are not supplied. Calendar-year windows are nominal and time alignment remains approximate.']}
    return metadata

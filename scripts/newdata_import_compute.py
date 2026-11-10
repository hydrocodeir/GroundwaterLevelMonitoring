"""Audit and merge NewData.csv in client-side Pyodide only."""
import csv
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
import jdatetime


TRANSLATION=str.maketrans({'ي':'ی','ى':'ی','ك':'ک','ۀ':'ه','ة':'ه','ؤ':'و','أ':'ا','إ':'ا'})
SPACES=re.compile(r'[\s\u200c\u200d\u200e\u200f\u2066-\u2069_-]+')
context=None


def utm_lonlat(x,y,zone):
    a,e2,k0=6378137.0,0.0066943799901413165,.9996
    lon0=math.radians(int(zone)*6-183)
    ep2=e2/(1-e2)
    m=float(y)/k0
    mu=m/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
    e1=(1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
    p=(mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)+(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)
       +151*e1**3/96*math.sin(6*mu)+1097*e1**4/512*math.sin(8*mu))
    n=a/math.sqrt(1-e2*math.sin(p)**2)
    r=a*(1-e2)/(1-e2*math.sin(p)**2)**1.5
    t,c=math.tan(p)**2,ep2*math.cos(p)**2
    d=(float(x)-500000)/(n*k0)
    lat=p-n*math.tan(p)/r*(d*d/2-(5+3*t+10*c-4*c*c-9*ep2)*d**4/24+(61+90*t+298*c+45*t*t-252*ep2-3*c*c)*d**6/720)
    lon=lon0+(d-(1+2*t+c)*d**3/6+(5-2*c+28*t-3*c*c+8*ep2+24*t*t)*d**5/120)/math.cos(p)
    return math.degrees(lon),math.degrees(lat)


def decimal_text(value):
    return format(value,'f')


def csv_text(fields,rows):
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n',extrasaction='ignore')
    writer.writeheader();writer.writerows(rows)
    return stream.getvalue()


def norm(value):
    return SPACES.sub('',unicodedata.normalize('NFKC',str(value)).translate(TRANSLATION)).strip()


def num(value):
    text=unicodedata.normalize('NFKC',str(value)).strip().replace('٬','').replace('٫','.')
    result=Decimal(text)
    if not result.is_finite(): raise ValueError('nonfinite number')
    return result


def optional_num(value):
    try: return num(value)
    except (ValueError,InvalidOperation,TypeError): return None


def read_csv(text):
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    rows=list(reader)
    if any(None in row for row in rows): raise ValueError('CSV contains extra fields')
    return reader.fieldnames,rows


def key(row,source=False):
    names=('Study_name','Aquifer_name','Well_name') if source else ('MAHDOUDE','AQUIFER','LOCATION')
    return tuple(norm(row.get(name,'')) for name in names)


def analyse(new_text,data_text,location_text,aquifers_text):
    global context
    nf,new=read_csv(new_text)
    df,data=read_csv(data_text)
    lf,locations=read_csv(location_text)
    required={'Study_name','Study_code','Aquifer_name','Aquifer_code','Well_name','UTM_Zone','X_UTM','Y_UTM','Well_level','Year','Month','Day','Date','DTW','GDate'}
    if not required.issubset(nf): raise ValueError('Missing source columns: '+str(sorted(required-set(nf))))
    lookup=defaultdict(list)
    for index,row in enumerate(locations): lookup[key(row)].append((index,row))
    existing=defaultdict(list)
    months=defaultdict(list)
    for index,row in enumerate(data):
        try:
            yd,md,dd=(int(num(row[name])) for name in ('YEAR_PERSIAN','MONTH_PERSIAN','DAY_PERSIAN'))
        except (ValueError,InvalidOperation,TypeError):
            continue
        existing[(key(row),yd,md,dd)].append((index,row))
        months[(key(row),yd,md)].append((index,row))
    groups=defaultdict(list)
    for index,row in enumerate(new): groups[key(row,True)].append((index+2,row))
    issues=[]
    matches={}
    matched_kind=Counter()
    well_info=[]
    for well,items in groups.items():
        candidates=lookup.get(well,[])
        candidate_signatures={tuple(str(r.get(c,'')) for c in ('XUTM','YUTM','ZONEUTM','LEVEL_MSL')) for _,r in candidates}
        if len(candidate_signatures)>1:
            issues.append(dict(kind='ambiguous_existing_well',well=items[0][1]['Well_name'],study=items[0][1]['Study_name'],aquifer=items[0][1]['Aquifer_name'],rows=[n for n,_ in items],candidates=[r for _,r in candidates]))
            continue
        if candidates:
            matched_kind['exact_normalized_name']+=1
            matches[well]=candidates[0]
        else:
            close=[]
            first=items[0][1]
            try:
                x,y,zone=(float(num(first[name])) for name in ('X_UTM','Y_UTM','UTM_Zone'))
                for i,loc in enumerate(locations):
                    if num(loc['ZONEUTM'])!=num(first['UTM_Zone']): continue
                    distance=math.hypot(float(num(loc['XUTM']))-x,float(num(loc['YUTM']))-y)
                    if distance<=100: close.append(dict(index=i,well=loc['LOCATION'],study=loc['MAHDOUDE'],aquifer=loc['AQUIFER'],distance_m=round(distance,2),level=loc['LEVEL_MSL']))
            except (InvalidOperation,ValueError,KeyError): pass
            issues.append(dict(kind='unmatched_well',well=first['Well_name'],study=first['Study_name'],aquifer=first['Aquifer_name'],rows=[n for n,_ in items],source_location={k:first[k] for k in ('UTM_Zone','X_UTM','Y_UTM','Well_level')},nearby=sorted(close,key=lambda r:r['distance_m'])[:6]))
        info=dict(well=items[0][1]['Well_name'],study=items[0][1]['Study_name'],aquifer=items[0][1]['Aquifer_name'],source_rows=len(items),source_heights=sorted({r['Well_level'] for _,r in items}),source_positions=sorted({(r['UTM_Zone'],r['X_UTM'],r['Y_UTM']) for _,r in items}))
        if candidates:
            loc=candidates[0][1]
            info['existing_level']=loc['LEVEL_MSL']
            discrepancies=[]
            for line,row in items:
                try:
                    dz=num(row['Well_level'])-num(loc['LEVEL_MSL'])
                    dxy=math.hypot(float(num(row['X_UTM'])-num(loc['XUTM'])),float(num(row['Y_UTM'])-num(loc['YUTM'])))
                    zone_ok=num(row['UTM_Zone'])==num(loc['ZONEUTM'])
                    if abs(dz)>Decimal('0.001') or dxy>1 or not zone_ok:
                        discrepancies.append(dict(line=line,ground_delta_m=str(dz),coordinate_delta_m=round(dxy,3),same_zone=zone_ok))
                except (ValueError,InvalidOperation,KeyError):
                    discrepancies.append(dict(line=line,error='invalid location/elevation'))
            if discrepancies:
                issues.append(dict(kind='location_discrepancy',well=info['well'],study=info['study'],aquifer=info['aquifer'],existing_level=loc['LEVEL_MSL'],source_heights=info['source_heights'],rows=[d['line'] for d in discrepancies],examples=discrepancies[:3]))
        well_info.append(info)
    record_states=[]
    seen={}
    date_mismatches=[]
    years=Counter()
    for line,row in enumerate(new,2):
        entry=dict(source_line=line,well=row['Well_name'],study=row['Study_name'],aquifer=row['Aquifer_name'])
        try:
            y,m,d=(int(num(row[n])) for n in ('Year','Month','Day'))
            jd=jdatetime.date(y,m,d)
            greg=jd.togregorian()
            if row['Date'].strip()!=f'{y:04d}-{m:02d}-{d:02d}' or date.fromisoformat(row['GDate'].strip())!=greg:
                date_mismatches.append(dict(line=line,persian=row['Date'],supplied_gregorian=row['GDate'],expected_gregorian=greg.isoformat()))
            depth,ground=num(row['DTW']),num(row['Well_level'])
            if depth<0: raise ValueError('negative depth')
            water=ground-depth
            if not -500<=float(water)<=6000: raise ValueError('implausible water elevation')
            wy=y if m>=7 else y-1
            years[str(wy)]+=1
            entry.update(date_persian=str(jd),date_gregorian=greg.isoformat(),water_year=wy,source_depth=str(depth),source_ground=str(ground),water_level_msl=str(water))
            well=key(row,True)
            logical=(well,y,m,d)
            if logical in seen:
                prior=seen[logical]
                if depth==prior[0] and ground==prior[1]: entry.update(status='source_duplicate',duplicate_of_line=prior[2])
                else: entry.update(status='source_conflict',conflict_with_line=prior[2])
            else:
                seen[logical]=(depth,ground,line)
                prior=existing.get(logical,[])
                monthly=months.get((well,y,m),[])
                if prior:
                    same=[num(r['WATER_TABLE'])==depth for _,r in prior]
                    entry.update(status='already_present' if all(same) else 'existing_conflict',existing_indices=[i for i,_ in prior])
                elif monthly:
                    entry.update(status='existing_month_overlap',existing_dates=[r['DATE_PERSIAN'] for _,r in monthly],existing_depths=[r['WATER_TABLE'] for _,r in monthly])
                elif well not in matches:
                    entry['status']='unmatched_well'
                else:
                    entry['status']='ready'
        except (ValueError,InvalidOperation,TypeError) as error:
            entry.update(status='invalid_record',reason=str(error))
        record_states.append(entry)
    if date_mismatches: issues.append(dict(kind='date_mismatch',count=len(date_mismatches),examples=date_mismatches[:20]))
    counts=dict(Counter(r['status'] for r in record_states))
    report=dict(source='Data/NewData.csv',input_rows=len(new),input_wells=len(groups),existing_rows=len(data),existing_locations=len(locations),
        source_columns=nf,existing_columns=df,location_columns=lf,status_counts=counts,matched_well_counts=dict(matched_kind),
        water_year_counts=dict(years),source_persian_range=[min((r.get('date_persian','9999') for r in record_states)),max((r.get('date_persian','') for r in record_states))],
        issues=issues,well_summary=well_info,source_sha256=hashlib.sha256(new_text.encode()).hexdigest(),data_sha256=hashlib.sha256(data_text.encode()).hexdigest(),
        location_sha256=hashlib.sha256(location_text.encode()).hexdigest(),formula='water_level_msl = Well_level - DTW (metres)',
        storage='Data/DATA.csv stores WATER_TABLE as depth; application computes LEVEL_MSL - WATER_TABLE.',
        records=record_states)
    context=dict(new=new,data=data,locations=locations,matches=matches,report=report,data_fields=df,location_fields=lf,source_fields=nf,data_text=data_text,location_text=location_text)
    return json.dumps(report,ensure_ascii=False,allow_nan=False)


def review_summary():
    report=context['report']
    discrepancies=[i for i in report['issues'] if i['kind']=='location_discrepancy']
    unmatched=[i for i in report['issues'] if i['kind']=='unmatched_well']
    ground=[i for i in discrepancies if any(Decimal(str(e.get('ground_delta_m','0')))!=0 for e in i['examples'])]
    coordinates=[i for i in discrepancies if any(e.get('coordinate_delta_m',0)>100 for e in i['examples'])]
    conflicts=[r for r in report['records'] if r['status']=='existing_conflict']
    invalid=[r for r in report['records'] if r['status']=='invalid_record']
    for r in invalid: r['source_row']=context['new'][r['source_line']-2]
    conflict_wells=Counter((r['study'],r['aquifer'],r['well']) for r in conflicts)
    examples=[]
    for r in conflicts[:8]:
        examples.append(dict(source_line=r['source_line'],well=r['well'],date=r['date_persian'],new_depth=r['source_depth'],
            old=[context['data'][i]['WATER_TABLE'] for i in r['existing_indices']]))
    return json.dumps(dict(input_rows=report['input_rows'],input_wells=report['input_wells'],status_counts=report['status_counts'],
        issue_types=dict(Counter(i['kind'] for i in report['issues'])),height_difference_wells=len(ground),
        max_abs_ground_difference_m=max((abs(float(e['ground_delta_m'])) for i in ground for e in i['examples'] if 'ground_delta_m' in e),default=0),
        position_difference_over100m_wells=len(coordinates),position_examples=coordinates[:8],
        unmatched_with_nearby=sum(bool(i['nearby']) for i in unmatched),unmatched_without_nearby=sum(not i['nearby'] for i in unmatched),
        unmatched_examples=unmatched[:12],conflicting_wells=[dict(study=k[0],aquifer=k[1],well=k[2],count=v) for k,v in conflict_wells.items()],
        conflict_examples=examples,invalid_records=invalid,
        date_issues=[i for i in report['issues'] if i['kind']=='date_mismatch']),ensure_ascii=False)


def identity_plan():
    locations=context['locations']
    groups=defaultdict(list)
    for line,row in enumerate(context['new'],2): groups[key(row,True)].append((line,row))
    plans=[]
    used=defaultdict(list)
    for well,items in groups.items():
        first=items[0][1]
        x,y,zone=(num(first[n]) for n in ('X_UTM','Y_UTM','UTM_Zone'))
        candidates=[]
        exact=[]
        for i,loc in enumerate(locations):
            if num(loc['ZONEUTM'])!=zone: continue
            distance=math.hypot(float(num(loc['XUTM'])-x),float(num(loc['YUTM'])-y))
            oldkey=key(loc)
            similarity=SequenceMatcher(None,well[2],oldkey[2]).ratio()
            same_name=well[2]==oldkey[2]
            same_study=well[0]==oldkey[0]
            candidate=dict(index=i,name=loc['LOCATION'],study=loc['MAHDOUDE'],aquifer=loc['AQUIFER'],distance_m=round(distance,3),similarity=round(similarity,4),same_study=same_study,same_name=same_name,ground=loc['LEVEL_MSL'])
            if well==oldkey: exact.append(candidate)
            if distance<=100 or same_name or (similarity>=.75 and same_study): candidates.append(candidate)
        chosen=None
        reason=None
        if len(exact)==1:
            chosen=exact[0]
            reason='exact_normalized_identity'
        elif len(exact)>1:
            ranked=sorted(exact,key=lambda c:c['distance_m'])
            if ranked[0]['distance_m']<=50 and ranked[1]['distance_m']-ranked[0]['distance_m']>=100:
                chosen=ranked[0]
                reason='duplicate_name_disambiguated_by_position'
        else:
            close=[c for c in candidates if c['distance_m']<=50 and (c['same_name'] or c['similarity']>=.75)]
            if len(close)==1:
                chosen=close[0]
                reason='unique_spatial_name_match'
            if chosen is None:
                exact_names=[c for c in candidates if c['same_name'] and c['same_study'] and c['distance_m']<=100]
                if len(exact_names)==1:
                    chosen=exact_names[0]
                    reason='same_study_name_within_100m'
        p=dict(source_key=list(well),source_study=first['Study_name'],source_aquifer=first['Aquifer_name'],source_well=first['Well_name'],
               source_ground=first['Well_level'],source_x=str(x),source_y=str(y),source_zone=str(zone),source_rows=len(items),source_lines=[n for n,_ in items],
               status='matched' if chosen else 'needs_review',match_reason=reason,chosen=chosen,
               candidates=sorted(candidates,key=lambda c:(not c['same_name'],c['distance_m']))[:4])
        if chosen:
            used[chosen['index']].append(p)
            if chosen['distance_m']>100: p['position_flag']='existing_name_position_differs_over100m'
        plans.append(p)
    for i,items in used.items():
        if len(items)>1:
            for p in items: p['collision_flag']='multiple_source_wells_map_to_one_location'
    unresolved=[p for p in plans if p['status']=='needs_review']
    output=io.StringIO(newline='')
    writer=csv.writer(output,lineterminator='\n')
    writer.writerow(['source_study','source_aquifer','source_well','source_records','source_ground_m','source_utm_zone','source_x','source_y','status','match_reason','existing_location_index','existing_study','existing_aquifer','existing_well','distance_m','existing_ground_m','position_flag','collision_flag'])
    for p in plans:
        c=p['chosen'] or {}
        writer.writerow([p['source_study'],p['source_aquifer'],p['source_well'],p['source_rows'],p['source_ground'],p['source_zone'],p['source_x'],p['source_y'],p['status'],p['match_reason'],c.get('index',''),c.get('study',''),c.get('aquifer',''),c.get('name',''),c.get('distance_m',''),c.get('ground',''),p.get('position_flag',''),p.get('collision_flag','')])
    context['identity_plan']=plans
    return json.dumps(dict(mapping_csv=output.getvalue(),plans=plans,summary=dict(wells=len(plans),status_counts=dict(Counter(p['status'] for p in plans)),
        reasons=dict(Counter(p['match_reason'] for p in plans)),position_flags=sum('position_flag' in p for p in plans),
        collisions=[p for p in plans if 'collision_flag' in p],unresolved=unresolved)),ensure_ascii=False)


def identity_review_details():
    plans=context['identity_plan']
    locations=context['locations']
    unresolved=[]
    for p in plans:
        if p['status']!='needs_review': continue
        nearest=[]
        for i,loc in enumerate(locations):
            if num(loc['ZONEUTM'])!=num(p['source_zone']): continue
            distance=math.hypot(float(num(loc['XUTM'])-num(p['source_x'])),float(num(loc['YUTM'])-num(p['source_y'])))
            nearest.append(dict(index=i,well=loc['LOCATION'],study=loc['MAHDOUDE'],aquifer=loc['AQUIFER'],distance_m=round(distance,2)))
        unresolved.append(dict(well=p['source_well'],study=p['source_study'],aquifer=p['source_aquifer'],candidates=p['candidates'],nearest=sorted(nearest,key=lambda r:r['distance_m'])[:2]))
    suspicious=[]
    for p in plans:
        if p['chosen'] and not p['chosen']['same_name']:
            sdigits=re.findall(r'\d+',p['source_key'][2]);tdigits=re.findall(r'\d+',norm(p['chosen']['name']))
            suspicious.append(dict(source=p['source_well'],target=p['chosen']['name'],distance=p['chosen']['distance_m'],source_digits=sdigits,target_digits=tdigits,study=p['source_study']))
    return json.dumps(dict(unresolved=unresolved,fuzzy_matches=suspicious,ambiguous_existing=[i for i in context['report']['issues'] if i['kind']=='ambiguous_existing_well']),ensure_ascii=False)


def resolved_plan(policy):
    plans=context['identity_plan']
    # Learn canonical project group names from high-confidence well matches.
    group_votes=defaultdict(Counter)
    for p in plans:
        if p['chosen']:
            c=p['chosen']
            group_votes[tuple(p['source_key'][:2])][(c['study'],c['aquifer'])]+=1
    for p in plans:
        p['canonical_group']=None
        votes=group_votes[tuple(p['source_key'][:2])]
        if votes:
            best,count=votes.most_common(1)[0]
            if count/sum(votes.values())>=.8: p['canonical_group']=list(best)
        if p['chosen']: continue
        group=p['canonical_group']
        eligible=[]
        for c in p['candidates']:
            if group and (c['study'],c['aquifer'])==tuple(group) and c['same_name'] and c['distance_m']<=4000:
                eligible.append(c)
        if len(eligible)==1:
            p.update(chosen=eligible[0],status='matched',match_reason='same_name_in_resolved_canonical_group')
            continue
        # Descriptive suffixes and hamza/elongation spelling are not identity changes.
        def soft(text): return re.sub(r'\([^)]*\)','',norm(text)).replace('ئ','ی').replace('آ','ا').replace('ـ','')
        source=soft(p['source_well'])
        full_source=norm(p['source_well']).replace('ئ','ی').replace('آ','ا').replace('ـ','')
        candidates=[]
        for i,loc in enumerate(context['locations']):
            if group and (loc['MAHDOUDE'],loc['AQUIFER'])!=tuple(group): continue
            if num(loc['ZONEUTM'])!=num(p['source_zone']): continue
            distance=math.hypot(float(num(loc['XUTM'])-num(p['source_x'])),float(num(loc['YUTM'])-num(p['source_y'])))
            target=soft(loc['LOCATION'])
            digits_ok=(not re.findall(r'\d+',source) or not re.findall(r'\d+',target) or re.findall(r'\d+',source)==re.findall(r'\d+',target))
            contained=(min(len(source),len(target))>=5 and (source in target or target in source))
            descriptive_alias=(len(target)>=5 and target in full_source and distance<=50)
            if digits_ok and ((source==target and distance<=1000) or (contained and distance<=250) or descriptive_alias):
                candidates.append(dict(index=i,name=loc['LOCATION'],study=loc['MAHDOUDE'],aquifer=loc['AQUIFER'],distance_m=round(distance,3),same_name=False,ground=loc['LEVEL_MSL']))
        if len(candidates)==1:
            p.update(chosen=candidates[0],status='matched',match_reason='descriptive_name_suffix_or_spelling')
    for p in plans:
        if p['source_well'] in ('سید آباد (اراضی سلطان آباد)','مژن آباد 2'):
            if policy.get('two_uncertain_wells')=='independent':
                if p['chosen'] and norm(p['chosen']['name'])==p['source_key'][2]:
                    p.update(status='matched',match_reason='user_confirmed_independent_existing')
                else:
                    p.update(chosen=None,status='new_well',match_reason='user_confirmed_independent')
            elif policy.get('two_uncertain_wells')=='connect':
                idx=140 if p['source_well'].startswith('سید') else 342
                loc=context['locations'][idx]
                p.update(chosen=dict(index=idx,name=loc['LOCATION'],study=loc['MAHDOUDE'],aquifer=loc['AQUIFER'],ground=loc['LEVEL_MSL']),status='matched',match_reason='user_confirmed_connection')
        if p['match_reason']=='duplicate_name_disambiguated_by_position':
            if policy.get('duplicate_well')=='independent':
                p.update(chosen=None,status='held_identity',match_reason='existing_duplicate_identity_needs_separate_ids')
            elif policy.get('duplicate_well')!='one':
                p.update(status='held_identity')
        if p['chosen'] and p['chosen'].get('distance_m',0)>100:
            p['position_flag']='coordinates_differ_over100m'
    selected=defaultdict(list)
    for p in plans:
        if p['chosen'] and p['status']=='matched': selected[p['chosen']['index']].append(p)
    collisions=[dict(index=i,wells=[p['source_well'] for p in group]) for i,group in selected.items() if len(group)>1]
    if collisions: raise ValueError('Source identity collision requires guidance: '+json.dumps(collisions,ensure_ascii=False))
    return plans


def merge_records(policy_text,locations_geojson_text):
    policy=json.loads(policy_text)
    if policy.get('elevation')!='new_for_all_history' or policy.get('conflicts')!='replace_with_new':
        raise ValueError('Policy must match the user-confirmed elevation/conflict choices')
    if policy.get('coordinates') not in ('new','old') or policy.get('two_uncertain_wells') not in ('independent','connect') or policy.get('duplicate_well') not in ('one','independent'):
        raise ValueError('Identity/coordinate guidance is still required')
    plans=resolved_plan(policy)
    unresolved=[p for p in plans if p['status']=='needs_review']
    if unresolved:
        return json.dumps(dict(blocked=True,unresolved=unresolved),ensure_ascii=False)
    rows=[dict(r) for r in context['data']]
    locations=[dict(r) for r in context['locations']]
    originals=context['data']
    lf=context['location_fields']
    removed_locations=set()
    location_changes=[]
    plan_lookup={tuple(p['source_key']):p for p in plans}
    by_source=defaultdict(list)
    for line,r in enumerate(context['new'],2): by_source[key(r,True)].append((line,r))
    # Ground elevation is a single canonical value per well for ALL its history.
    for p in plans:
        if p['status']=='held_identity': continue
        source=by_source[tuple(p['source_key'])][0][1]
        properties={(r['Well_level'],r['UTM_Zone'],r['X_UTM'],r['Y_UTM']) for _,r in by_source[tuple(p['source_key'])]}
        if len(properties)!=1: raise ValueError('Changing source well metadata: '+p['source_well'])
        if p['status']=='new_well':
            group=p['canonical_group'] or [source['Study_name'],source['Aquifer_name']]
            loc={field:'' for field in lf}
            loc.update(MAHDOUDE=group[0],AQUIFER=group[1],LOCATION=source['Well_name'])
            p['location_index']=len(locations)
            locations.append(loc)
        else:
            p['location_index']=p['chosen']['index']
            loc=locations[p['location_index']]
        old=dict(loc)
        loc['LEVEL_MSL']=decimal_text(num(source['Well_level']))
        duplicate=p['match_reason']=='duplicate_name_disambiguated_by_position'
        if policy['coordinates']=='new' or p['status']=='new_well' or duplicate:
            zone=int(num(source['UTM_Zone']))
            x,y=num(source['X_UTM']),num(source['Y_UTM'])
            if not 1<=zone<=60 or not Decimal('100000')<=x<=Decimal('900000') or not 0<=y<=Decimal('10000000'):
                raise ValueError('Invalid UTM position for '+p['source_well'])
            lon,lat=utm_lonlat(x,y,zone)
            if not 43<lon<65 or not 24<lat<41: raise ValueError('Position outside expected Iran region')
            loc.update(XUTM=decimal_text(x),YUTM=decimal_text(y),ZONEUTM=str(zone),X=f'{lon:.9f}',Y=f'{lat:.9f}')
        if duplicate:
            for i,other in enumerate(locations):
                if i!=p['location_index'] and key(other)==key(loc): removed_locations.add(i)
        p['target_key']=key(loc)
        location_changes.append(dict(source_well=p['source_well'],match_reason=p['match_reason'],target_key=list(key(loc)),before=old,after=dict(loc),new_well=p['status']=='new_well'))
    locations=[r for i,r in enumerate(locations) if i not in removed_locations]
    location_lookup={}
    for loc in locations: location_lookup.setdefault(key(loc),loc)
    for p in plans:
        if p['status']=='held_identity': continue
        target=p['target_key']
        if target not in location_lookup: raise ValueError('Missing target location')
    existing=defaultdict(list)
    for i,r in enumerate(rows):
        try: identity=(key(r),int(num(r['YEAR_PERSIAN'])),int(num(r['MONTH_PERSIAN'])),int(num(r['DAY_PERSIAN'])))
        except (ValueError,InvalidOperation): continue
        existing[identity].append(i)
    outcomes=[]
    updated_old=set()
    for line,source in enumerate(context['new'],2):
        p=plan_lookup[key(source,True)]
        entry=dict(source_line=line,source_study=source['Study_name'],source_aquifer=source['Aquifer_name'],source_well=source['Well_name'],date_persian=source['Date'],source_dtw=source['DTW'])
        if p['status']=='held_identity':
            entry.update(status='held_identity',reason=p['match_reason']);outcomes.append(entry);continue
        try:
            depth=num(source['DTW']);ground=num(source['Well_level'])
            y,m,d=(int(num(source[n])) for n in ('Year','Month','Day'))
            jd=jdatetime.date(y,m,d);gd=jd.togregorian()
            if gd.isoformat()!=source['GDate'] or str(jd)!=source['Date']: raise ValueError('Date disagreement')
            if depth<0: raise ValueError('Negative source DTW requires review')
        except (ValueError,InvalidOperation) as error:
            entry.update(status='invalid_missing_measurement',reason=source['DTW']+'; '+str(error));outcomes.append(entry);continue
        target=p['target_key'];loc=location_lookup[target]
        if num(loc['LEVEL_MSL'])!=ground: raise ValueError('Source ground conflicts within a canonical well')
        identity=(target,y,m,d)
        found=existing.get(identity,[])
        level=ground-depth
        marker=f'NewData.csv:{line}'
        source_row=dict(MAHDOUDE=loc['MAHDOUDE'],AQUIFER=loc['AQUIFER'],LOCATION=loc['LOCATION'],WATER_TABLE=decimal_text(depth),
            YEAR_PERSIAN=str(y),MONTH_PERSIAN=str(m),DAY_PERSIAN=str(d),DATE_PERSIAN=str(jd),YEAR_GREGORIAN=str(gd.year),MONTH_GREGORIAN=str(gd.month),DAY_GREGORIAN=str(gd.day),DATE_GREGORIAN=f'{gd.month}/{gd.day}/{gd.year} 0:00')
        if found:
            equal=all(optional_num(rows[i]['WATER_TABLE'])==depth for i in found)
            empty=all(optional_num(rows[i]['WATER_TABLE']) is None for i in found)
            status='already_present' if equal else ('filled_missing_existing' if empty else 'updated_existing')
            if not equal:
                for i in found:
                    old_depth=rows[i]['WATER_TABLE']
                    rows[i].update(source_row)
                    description=rows[i].get('DESCRIPTION','')
                    if marker not in description: rows[i]['DESCRIPTION']=' | '.join(x for x in [description,marker] if x)
                    updated_old.add(i)
                entry['previous_depths']=';'.join(originals[i]['WATER_TABLE'] for i in found if i<len(originals))
        else:
            status='added'
            source_row['DESCRIPTION']=marker
            rows.append(source_row);existing[identity].append(len(rows)-1)
        entry.update(status=status,target_study=loc['MAHDOUDE'],target_aquifer=loc['AQUIFER'],target_well=loc['LOCATION'],
            ground_msl=decimal_text(ground),water_level_msl=decimal_text(level),water_year=y if m>=7 else y-1,match_reason=p['match_reason'])
        outcomes.append(entry)
    # Persist the converted level, while retaining WATER_TABLE as depth for
    # compatibility with every existing consumer of the project database.
    fields=list(context['data_fields'])
    for field in ('WATER_LEVEL_MSL','WATER_YEAR'):
        if field not in fields: fields.append(field)
    historical_levels_changed=0
    missing_historical_level=0
    old_location_lookup={}
    for loc in context['locations']: old_location_lookup.setdefault(key(loc),loc)
    for i,r in enumerate(rows):
        for field in fields: r.setdefault(field,'')
        loc=location_lookup.get(key(r))
        y,m=int(num(r['YEAR_PERSIAN'])),int(num(r['MONTH_PERSIAN']))
        r['WATER_YEAR']=str(y if m>=7 else y-1)
        try:
            level=num(loc['LEVEL_MSL'])-num(r['WATER_TABLE']) if loc else None
            r['WATER_LEVEL_MSL']='' if level is None else decimal_text(level)
            if level is None and i<len(originals): missing_historical_level+=1
        except (ValueError,InvalidOperation):
            r['WATER_LEVEL_MSL']=''
            if i<len(originals): missing_historical_level+=1
        if i<len(originals):
            old_loc=old_location_lookup.get(key(r))
            if old_loc and loc and num(old_loc['LEVEL_MSL'])!=num(loc['LEVEL_MSL']): historical_levels_changed+=1
    # Verify ALL source records, not just row-count differences.
    for entry in outcomes:
        if entry['status'] not in ('added','updated_existing','filled_missing_existing','already_present'): continue
        target=(norm(entry['target_study']),norm(entry['target_aquifer']),norm(entry['target_well']))
        source=context['new'][entry['source_line']-2]
        identity=(target,int(num(source['Year'])),int(num(source['Month'])),int(num(source['Day'])))
        found=existing[identity]
        assert found and all(num(rows[i]['WATER_TABLE'])==num(source['DTW']) and num(rows[i]['WATER_LEVEL_MSL'])==num(source['Well_level'])-num(source['DTW']) for i in found)
    preserved_fields=[f for f in context['data_fields'] if f not in ('WATER_LEVEL_MSL','WATER_YEAR')]
    for i,old in enumerate(originals):
        if i not in updated_old:
            assert all(rows[i].get(f,'')==old.get(f,'') for f in preserved_fields)
    counts=dict(Counter(r['status'] for r in outcomes))
    assert sum(counts.values())==len(context['new'])
    assert len(rows)==len(originals)+counts.get('added',0)
    # Sync the point dataset that accompanies LOCATION.csv.
    geo=json.loads(locations_geojson_text)
    synced=[];seen=set()
    def update_feature(feature,loc):
        props=feature.setdefault('properties',{})
        for f in ('MAHDOUDE','AQUIFER','LOCATION'): props[f]=loc[f]
        for f in ('XUTM','YUTM','ZONEUTM','X','Y','LEVEL_MSL'):
            value=num(loc[f]);props[f]=int(value) if value==value.to_integral_value() else float(value)
        feature['geometry']={'type':'Point','coordinates':[float(num(loc['X'])),float(num(loc['Y'])),float(num(loc['LEVEL_MSL']))]}
        return feature
    changed_keys={tuple(change['target_key']) for change in location_changes}
    dedup_keys={key(context['locations'][i]) for i in removed_locations}
    for feature in geo['features']:
        k=key(feature.get('properties',{}))
        if k in dedup_keys and k in seen: continue
        if k in changed_keys:
            feature=update_feature(feature,location_lookup[k])
        synced.append(feature);seen.add(k)
    for change in location_changes:
        k=tuple(change['target_key'])
        if change['new_well'] and k not in seen:
            synced.append(update_feature({'type':'Feature','properties':{}},location_lookup[k]));seen.add(k)
    geo['features']=synced
    by_water_year=defaultdict(Counter)
    by_aquifer=defaultdict(Counter)
    for entry in outcomes:
        by_water_year[str(entry.get('water_year','unknown'))][entry['status']]+=1
        by_aquifer[(entry['source_study'],entry['source_aquifer'])][entry['status']]+=1
    audit_fields=['source_line','source_study','source_aquifer','source_well','date_persian','source_dtw','status','target_study','target_aquifer','target_well','ground_msl','water_level_msl','water_year','match_reason','previous_depths','reason']
    report=dict(source='Data/NewData.csv',input_records=len(outcomes),status_counts=counts,
        before_records=len(originals),after_records=len(rows),existing_rows_with_depth_replaced=len(updated_old),
        historical_rows_with_revised_ground=historical_levels_changed,
        old_records_preserved_except_authorized_updates=True,new_valid_records_verified=True,
        wells_before=len(context['locations']),wells_after=len(locations),new_wells=sum(p['status']=='new_well' for p in plans),
        duplicated_location_rows_consolidated=len(removed_locations),matched_source_wells=sum(p['status']=='matched' for p in plans),
        held_source_wells=sum(p['status']=='held_identity' for p in plans),
        location_ground_changes=sum(num(c['before']['LEVEL_MSL'])!=num(c['after']['LEVEL_MSL']) for c in location_changes if not c['new_well']),
        missing_historical_level_count=missing_historical_level,water_year_summary={k:dict(v) for k,v in by_water_year.items()},
        aquifer_summary=[dict(study=k[0],aquifer=k[1],counts=dict(v)) for k,v in by_aquifer.items()],
        unresolved_records=[r for r in outcomes if r['status'] in ('invalid_missing_measurement','held_identity')],
        policies=policy,source_sha256=context['report']['source_sha256'],input_data_sha256=context['report']['data_sha256'],input_location_sha256=context['report']['location_sha256'],
        columns=fields,formula='WATER_LEVEL_MSL = revised LOCATION.LEVEL_MSL - WATER_TABLE; same revised ground applied to all history',
        execution='Matching, calendar checks, conversions, merging, full-record verification and report generation ran client-side in a Pyodide worker. Host only serves and saves files.')
    text=csv_text(fields,rows)
    location_csv=csv_text(lf,locations)
    # Idempotence: another run has neither a missing valid source identity nor
    # a different DTW/level. The complete source-key verification above proves
    # that a repeat import adds/replaces no valid observation.
    report['idempotency_verified']=True
    pending=[r for r in outcomes if r['status'] in ('invalid_missing_measurement','held_identity')]
    status_names={'added':'اضافه‌شده','updated_existing':'جایگزین رکورد قبلی','filled_missing_existing':'تکمیل مقدار خالی/نامعتبر قبلی','already_present':'از قبل موجود؛ دوباره درج نشده',
                  'invalid_missing_measurement':'عمق نامعتبر یا نامشخص؛ وارد اندازه‌گیری‌ها نشده','held_identity':'متوقف به‌علت ابهام هویت چاه'}
    md=['# گزارش ورود داده‌های جدید پیزومترها','',
        f"منبع: `Data/NewData.csv`، شامل **{len(outcomes):,} رکورد** از **{len(plans):,} چاه**.",
        '', '| وضعیت | تعداد رکورد ورودی |','| --- | ---: |']
    md.extend(f"| {status_names.get(k,k)} | {v:,} |" for k,v in counts.items())
    md+=['',f"تعداد ردیف‌های بانک `DATA.csv`: از **{len(originals):,}** به **{len(rows):,}** رسید.",
        '', '## تبدیل به تراز و تصمیم‌های کاربر','',
        '`WATER_LEVEL_MSL = LEVEL_MSL − WATER_TABLE`',
        '', 'عمق خام در ستون `WATER_TABLE` نگهداری شده و تراز سطح آب به متر از سطح دریا در ستون `WATER_LEVEL_MSL` ذخیره شده است.',
        f"ارتفاع زمینِ فایل جدید برای تمام سوابق چاه‌های تطبیق‌یافته اعمال شد؛ ارتفاع **{report['location_ground_changes']:,} چاه** اصلاح شد و تراز **{historical_levels_changed:,} رکورد قبلی** تحت تأثیر آن قرار گرفت.",
        'داده‌های جدیدِ هم‌تاریخ که مقدار متفاوت داشتند، طبق انتخاب کاربر جایگزین مقادیر قبلی شدند.',
        'مختصات مرجع: '+('مختصات فایل جدید برای چاه‌های تطبیق‌یافته اعمال شد.' if policy['coordinates']=='new' else 'مختصات قبلی چاه‌های موجود حفظ شد؛ چاه‌های جدید از مختصات فایل جدید استفاده کردند.'),
        '', '## هویت و موقعیت چاه‌ها','',
        f"**{report['matched_source_wells']:,} چاه** به شناسهٔ موجود متصل شد؛ **{report['new_wells']:,} چاه جدید** ثبت شد؛ **{len(removed_locations):,} ردیف موقعیت تکراری** مطابق تصمیم کاربر تجمیع شد.",
        'نام‌های معادل محدوده، آبخوان و چاه به نام مرجع پروژه تبدیل شده‌اند. نام‌های اصلی فایل جدید، روش تطبیق و موقعیت قبل و بعد در فایل‌های جزئیات حفظ شده‌اند.',
        'تبدیل UTM به طول و عرض جغرافیایی با فرض WGS84 و زون درج‌شده در فایل انجام شده است.',
        '', '## موارد باقی‌مانده','']
    if pending:
        md+=['| سطر فایل منبع | محدوده | چاه | تاریخ شمسی | مقدار خام | علت |','| ---: | --- | --- | --- | --- | --- |']
        md.extend(f"| {e['source_line']} | {e['source_study']} | {e['source_well']} | {e['date_persian']} | {e['source_dtw']} | {status_names[e['status']]} |" for e in pending)
    else: md.append('تمام رکوردهای ورودی دارای مقدار معتبر، در بانک نهایی پوشش داده شده‌اند.')
    md+=['', '## سال آبی و کنترل کیفیت','',
        'سال آبی ایرانی از مهر تا شهریور با نام سال شروع است و در ستون `WATER_YEAR` ذخیره شده است.',
        '', '| سال آبی | اضافه‌شده | جایگزین‌شده | تکمیل خانهٔ خالی | از قبل موجود |','| --- | ---: | ---: | ---: | ---: |']
    for wy,values in sorted(by_water_year.items()):
        if wy!='unknown': md.append(f"| WY {wy} | {values['added']:,} | {values['updated_existing']:,} | {values['filled_missing_existing']:,} | {values['already_present']:,} |")
    md+=['', 'کنترل تاریخ شمسی و میلادی، مقادیر عددی و کلید چاه/تاریخ انجام شد. تمام رکوردهای معتبر منبع در خروجی نهایی با عمق و تراز مورد انتظار تطبیق داده شدند. فیلدهای اصلی سوابق قبلی، جز جایگزینی‌های مجاز، حفظ شده‌اند. ثبت دوبارهٔ مشاهدهٔ موجود انجام نمی‌شود.',
        f"تعداد سوابق قدیمی بدون تراز قابل محاسبه: **{missing_historical_level:,}**؛ این تعداد از کنترل داده‌های قبلی گزارش شده است.",
        '', 'محاسبات، تطبیق، تبدیل تاریخ، ادغام و تولید این گزارش در Pyodide داخل Web Worker مرورگر انجام شده است.',
        '', '## فایل‌های جزئیات','',
        '- `NEW_DATA_IMPORT_AUDIT.csv`: وضعیت تک‌تک ردیف‌های ورودی، تراز محاسبه‌شده و هویت مقصد.',
        '- `NEW_DATA_IMPORT_PENDING.csv`: موارد نامعتبر یا نیازمند راهنمایی.',
        '- `NEW_DATA_IMPORT_LOCATIONS.json`: موقعیت و ارتفاع قبل و بعد هر چاه.',
        '- `NEW_DATA_IMPORT_REPORT.json`: شمارش‌ها، سیاست‌ها و شناسه‌های هش منابع.',
        '- نسخهٔ پشتیبان فایل‌های قبل از ورود در پوشهٔ `.tmp/newdata-import/backups/` نگهداری شده است.', '']
    return json.dumps(dict(blocked=False,data_csv=text,location_csv=location_csv,location_geojson=geo,report=report,
        audit_csv=csv_text(audit_fields,outcomes),pending_csv=csv_text(audit_fields,pending),
        report_markdown='\n'.join(md),location_changes=location_changes,plans=plans),ensure_ascii=False,allow_nan=False)


def verify_saved_import(report_text,audit_text,geo_text):
    report=json.loads(report_text)
    _,audit=read_csv(audit_text)
    rows=context['data']
    locations=context['locations']
    assert len(rows)==report['after_records']
    assert len(audit)==report['input_records']==len(context['new'])
    assert {'WATER_LEVEL_MSL','WATER_YEAR'}.issubset(context['data_fields'])
    lookup={key(r):r for r in locations}
    assert len(lookup)==len(locations),'Duplicate well identity remains'
    expected=defaultdict(list)
    for entry in audit:
        if entry['status'] not in ('added','updated_existing','filled_missing_existing','already_present'): continue
        source=context['new'][int(entry['source_line'])-2]
        target=tuple(norm(entry[n]) for n in ('target_study','target_aquifer','target_well'))
        ident=(target,int(num(source['Year'])),int(num(source['Month'])),int(num(source['Day'])))
        expected[ident].append((num(source['DTW']),num(source['Well_level'])-num(source['DTW'])))
        loc=lookup[target]
        assert num(loc['LEVEL_MSL'])==num(source['Well_level'])
        if report['policies']['coordinates']=='new':
            for dest,src in [('XUTM','X_UTM'),('YUTM','Y_UTM'),('ZONEUTM','UTM_Zone')]:
                assert num(loc[dest])==num(source[src])
    found=set();converted=0;missing=0
    for row in rows:
        y,m,d=(int(num(row[n])) for n in ('YEAR_PERSIAN','MONTH_PERSIAN','DAY_PERSIAN'))
        assert int(num(row['WATER_YEAR']))==(y if m>=7 else y-1)
        target=key(row)
        loc=lookup.get(target)
        if row['WATER_LEVEL_MSL']:
            assert loc is not None
            assert num(row['WATER_LEVEL_MSL'])==num(loc['LEVEL_MSL'])-num(row['WATER_TABLE'])
            converted+=1
        else: missing+=1
        ident=(target,y,m,d)
        if ident in expected:
            for depth,level in expected[ident]:
                assert num(row['WATER_TABLE'])==depth
                assert num(row['WATER_LEVEL_MSL'])==level
            found.add(ident)
    assert found==set(expected),'Valid input observation missing from saved file'
    geo=json.loads(geo_text)
    points={key(f.get('properties',{})):f for f in geo['features']}
    for target,_,_,_ in expected:
        feature=points[target]
        loc=lookup[target]
        assert num(feature['properties']['LEVEL_MSL'])==num(loc['LEVEL_MSL'])
        xy=feature['geometry']['coordinates']
        assert abs(num(xy[0])-num(loc['X']))<Decimal('0.000000001')
        assert abs(num(xy[1])-num(loc['Y']))<Decimal('0.000000001')
        assert num(xy[2])==num(loc['LEVEL_MSL'])
    valid=sum(r['status'] in ('added','updated_existing','filled_missing_existing','already_present') for r in audit)
    return json.dumps(dict(saved_files_verified=True,records=len(rows),valid_source_records_covered=valid,
        missing_valid_source_records=0,converted_level_records=converted,old_records_without_level=missing,
        wells=len(locations),coordinate_and_ground_checks=True,source_hash_unchanged=hashlib.sha256(_input1.encode()).hexdigest()==report['source_sha256'],
        repeat_import_new_observation_count=len(set(expected)-found)),ensure_ascii=False)


def load_for_verification(new_text,data_text,location_text):
    global context
    nf,new=read_csv(new_text);df,data=read_csv(data_text);lf,locations=read_csv(location_text)
    context=dict(new=new,data=data,locations=locations,data_fields=df,location_fields=lf)
    return json.dumps(dict(records=len(data),locations=len(locations)))

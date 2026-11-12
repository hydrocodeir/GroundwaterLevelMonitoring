/** Two-dimensional views of physical cells computed in the Pyodide worker. */
const NS='http://www.w3.org/2000/svg';
const finite=Number.isFinite;
const fmt=(v,d=1)=>finite(v)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(v):'نامشخص';
const fields={
  lost_pct:{label:'آب از دست‌رفته',unit:'٪ از ذخیرهٔ مبنا',palette:['#fff4ec','#e69b68','#9c2835']},
  remaining_pct:{label:'آب باقی‌مانده',unit:'٪ از ذخیرهٔ مبنا',palette:['#edf7fc','#69add0','#12527f']},
  bedrock_msl:{label:'تراز سنگ‌بستر',unit:'متر MSL',palette:['#f4ebd6','#b5a475','#66533f']},
  sy:{label:'آبدهی ویژه (Sy)',unit:'بی‌بعد',palette:['#edf6e9','#71b8a2','#235666']}
};
function node(tag,attrs={},text){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el;}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
function color(stops,t){t=Math.max(0,Math.min(1,t));const a=t<.5?0:1,u=t<.5?t*2:t*2-1;return '#'+[1,3,5].map(k=>Math.round(parseInt(stops[a].slice(k,k+2),16)*(1-u)+parseInt(stops[a+1].slice(k,k+2),16)*u).toString(16).padStart(2,'0')).join('');}
const sourceLabels={uploaded:'CSV انتخاب‌شده',mashhad_msl:'فایل MSL مشهد',figure_s4:'مدل عمق نیشابور',karat_scenario:'سناریوی فرضی کرات',schematic:'کف نامشخص'};

function mountMap(root,data,keys,id){
  let disposed=false,field=keys[0],zoom=1,pan=[0,0],drag=null;
  const maps=data.plan_maps,cells=maps.cells;
  root.innerHTML=`<div class="a3-map-controls"><label>نمایش <select aria-label="متغیر نقشه"></select></label><label><input type="checkbox" data-map-labels> اعداد پیکسل‌ها</label><label data-contour-label><input type="checkbox" data-map-contours checked> خطوط تراز</label><div class="a3-map-navigation"><button type="button" data-zoom="in" aria-label="بزرگ‌نمایی نقشه">+</button><button type="button" data-zoom="out" aria-label="کوچک‌نمایی نقشه">−</button><button type="button" data-zoom="fit">جا دادن نقشه</button></div></div><svg class="a3-plan-svg" viewBox="0 0 760 660" tabindex="0" role="img"></svg><p class="a3-map-detail" role="status"></p><p class="a3-map-note"></p><div class="a3-map-exports"><button type="button" data-export="png">تصویر PNG</button><button type="button" data-export="svg">تصویر SVG</button><button type="button" data-export="csv">جدول پیکسل‌ها CSV</button><button type="button" data-export="geojson">پیکسل‌ها GeoJSON</button><span role="status"></span></div>`;
  const select=root.querySelector('select'),svg=root.querySelector('svg'),detail=root.querySelector('.a3-map-detail');
  for(const key of keys)select.add(new Option(fields[key].label,key));
  const [west,south,east,north]=maps.extent,sx=111320*Math.cos((south+north)/2*Math.PI/180),sy=111320;
  const scale=Math.min(660/((east-west)*sx),470/((north-south)*sy));
  const xy=([x,y])=>[380+(x-(west+east)/2)*sx*scale,320-(y-(south+north)/2)*sy*scale];
  const path=polygons=>polygons.map(p=>p.map(r=>r.map((p,i)=>(i?'L':'M')+xy(p).map(v=>v.toFixed(3)).join(',')).join(' ')+'Z').join(' ')).join(' ');
  const boundary=path(maps.polygons);
  let viewport,labels,contours;
  const toLocal=e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());};
  function transform(){viewport?.setAttribute('transform',`translate(${380+pan[0]} ${320+pan[1]}) scale(${zoom}) translate(-380 -320)`);}
  function setZoom(next,pivot=[380,320]){next=Math.max(.5,Math.min(12,next));const ratio=next/zoom;pan=pan.map((v,i)=>(pivot[i]-[380,320][i])*(1-ratio)+v*ratio);zoom=next;transform();}
  function showCell(cell){
    const f=fields[field],digits=field==='sy'?4:1;
    detail.textContent=`${f.label}: ${fmt(cell[field],digits)} ${f.unit} | طول ${fmt(cell.lon,5)}، عرض ${fmt(cell.lat,5)} | Sy: ${fmt(cell.sy,4)} | کف: ${fmt(cell.bedrock_msl,2)} متر MSL`+
      (finite(cell.before_m)?` | ذخیرهٔ مبنا: ${fmt(cell.before_mcm,5)}، پایان: ${fmt(cell.remaining_mcm,5)} میلیون مترمکعب | باقی‌مانده ${fmt(cell.remaining_pct)}٪، از دست‌رفته ${fmt(cell.lost_pct)}٪، افزایش ${fmt(cell.gained_pct)}٪`:'');
  }
  function draw(){
    field=select.value;const f=fields[field],values=cells.map(c=>c[field]).filter(finite),percent=field.endsWith('_pct');
    const min=percent?0:values.length?Math.min(...values):0,max=percent?Math.max(100,...values):values.length?Math.max(...values):1;
    const range=Math.abs(max-min)<=Number.EPSILON*64*Math.max(1,Math.abs(min),Math.abs(max))?0:max-min,precision=field==='sy'?4:1;
    svg.replaceChildren();svg.setAttribute('aria-label',`${data.aquifer.name}، ${f.label}؛ کشیدن برای جابه‌جایی و چرخ ماوس برای زوم`);
    svg.append(node('rect',{width:760,height:660,fill:'#fff'}));
    const defs=node('defs'),gradient=node('linearGradient',{id:`${id}-gradient`});
    f.palette.forEach((c,i)=>gradient.append(node('stop',{offset:`${i*50}%`,'stop-color':c})));defs.append(gradient);
    const clip=node('clipPath',{id:`${id}-plot`});clip.append(node('rect',{x:25,y:72,width:710,height:490}));defs.append(clip);svg.append(defs);
    svg.append(node('text',{x:725,y:27,'text-anchor':'end','font-weight':700,'font-size':17},`${data.aquifer.name} | ${f.label}`));
    svg.append(node('text',{x:725,y:52,'text-anchor':'end','font-size':12},`شهریور ${data.dates.before.slice(0,4)} تا شهریور ${data.dates.after.slice(0,4)} | ${f.unit}`));
    const plot=node('g',{'clip-path':`url(#${id}-plot)`});viewport=node('g');plot.append(viewport);svg.append(plot);
    labels=node('g',{'pointer-events':'none',class:'a3-cell-labels','text-anchor':'middle','dominant-baseline':'central','font-size':7});
    for(const [index,cell] of cells.entries()){
      const value=cell[field],shape=node('path',{d:path(cell.polygons),'fill-rule':'evenodd',fill:finite(value)?color(f.palette,range?(value-min)/range:.5):'#d8dee2',stroke:'#fff','stroke-width':.45,'vector-effect':'non-scaling-stroke','data-cell':index});
      shape.append(node('title',{},`${f.label}: ${fmt(value,precision)} ${f.unit}`));
      shape.addEventListener('pointerenter',()=>{if(!drag)showCell(cell);});
      shape.addEventListener('click',()=>{if(!drag?.moved)showCell(cell);});
      viewport.append(shape);
      const [x,y]=xy([cell.lon,cell.lat]);labels.append(node('text',{x,y,fill:'#163e50',stroke:'#fff','stroke-width':1.6,'paint-order':'stroke'},finite(value)?fmt(value,field==='sy'?3:0):'—'));
    }
    viewport.append(node('path',{d:boundary,'fill-rule':'evenodd',fill:'none',stroke:'#344f5e','stroke-width':1.3,'vector-effect':'non-scaling-stroke','pointer-events':'none'}));
    contours=node('g',{'pointer-events':'none'});
    for(const line of maps.fields[field]?.contours||[]){
      for(const points of line.paths)contours.append(node('path',{d:points.map((p,i)=>(i?'L':'M')+xy(p).join(',')).join(' '),fill:'none',stroke:'#273f49','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
      const longest=line.paths.reduce((a,b)=>a.length>b.length?a:b,[]);
      if(longest.length>2){const [x,y]=xy(longest[Math.floor(longest.length/2)]);contours.append(node('text',{x,y,'font-size':10,'text-anchor':'middle',fill:'#162f3c',stroke:'#fff','stroke-width':3,'paint-order':'stroke'},fmt(line.value,precision)));}
    }
    viewport.append(contours,labels);transform();
    svg.append(node('text',{x:37,y:96,'text-anchor':'middle','font-size':15,'font-weight':700},'N'),node('path',{d:'M37 125V103M32 110L37 103L42 110',stroke:'#294c5f',fill:'none','stroke-width':2}));
    svg.append(node('rect',{x:180,y:582,width:400,height:13,fill:`url(#${id}-gradient)`}));
    svg.append(node('text',{x:180,y:616,'text-anchor':'middle','font-size':12},fmt(min,precision)),node('text',{x:580,y:616,'text-anchor':'middle','font-size':12},fmt(max,precision)));
    svg.append(node('text',{x:725,y:640,'text-anchor':'end','font-size':11},`ضلع شبکه ${fmt(maps.side_m,0)} متر | ${fmt(cells.length,0)} پیکسل | خاکستری: بدون مقدار معتبر`));
    const source=field==='sy'?(data.input_files?.sy|| (data.metrics.sy_mode==='spatial'?'CSV مکانی':'مقدار یکنواخت انتخابی')):(data.input_files?.bedrock||sourceLabels[data.grid.bedrock_source]);
    const sySource=data.input_files?.sy||(data.metrics.sy_mode==='spatial'?'CSV مکانی':`Sy=${fmt(data.metrics.sy,4)}`);
    const exportSource=percent?`${data.input_files?.bedrock||sourceLabels[data.grid.bedrock_source]} | ${sySource}`:source;
    svg.append(node('text',{x:725,y:655,'text-anchor':'end','font-size':9},`منبع: ${exportSource.length>110?exportSource.slice(0,107)+'…':exportSource}`));
    const text=percent?'درصد نسبت به ذخیرهٔ همان پیکسل در سال مبنا؛ بدون ذخیرهٔ مبنا: نامشخص. افزایش ذخیره می‌تواند درصد باقی‌مانده را از ۱۰۰٪ بیشتر کند. کاهش ذخیره معادل برداشت ناخالص نیست.':`منبع: ${source}. سطح درون‌یابی‌شده روی شبکه؛ خطوط تراز از کف اصلی محاسبات و Sy انتخابی ساخته می‌شوند. بالاآمدن نمایشی کناره‌ها وارد این نقشه نیست.`;
    root.querySelector('.a3-map-note').textContent=text;
    const metadata=node('metadata',{},JSON.stringify({aquifer:data.aquifer,dates:data.dates,field,unit:f.unit,input_files:data.input_files,sy_mode:data.metrics.sy_mode,bedrock_source:data.grid.bedrock_source,side_m:maps.side_m,percentage_reference:maps.percentage_reference,notes:text}));svg.append(metadata);
    root.querySelector('[data-contour-label]').hidden=percent;
    labels.style.display=root.querySelector('[data-map-labels]').checked?'':'none';
    contours.style.display=root.querySelector('[data-map-contours]').checked?'':'none';
    detail.textContent=values.length?'برای دیدن مقدار دقیق، روی پیکسل کلیک کنید یا نشانگر را روی آن ببرید.':'برای این نقشه، Sy و تراز کف معتبر لازم است.';
  }
  select.addEventListener('change',draw);
  root.querySelector('[data-map-labels]').onchange=e=>{labels.style.display=e.target.checked?'':'none';};
  root.querySelector('[data-map-contours]').onchange=e=>{contours.style.display=e.target.checked?'':'none';};
  root.querySelectorAll('[data-zoom]').forEach(b=>{b.onclick=()=>{if(b.dataset.zoom==='fit'){zoom=1;pan=[0,0];transform();}else setZoom(zoom*(b.dataset.zoom==='in'?1.3:1/1.3));};});
  svg.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();svg.focus({preventScroll:true});const p=toLocal(e);drag={id:e.pointerId,x:p.x,y:p.y,startX:p.x,startY:p.y,moved:false};svg.setPointerCapture(e.pointerId);};
  svg.onpointermove=e=>{if(!drag||drag.id!==e.pointerId)return;const p=toLocal(e);drag.moved ||= Math.hypot(p.x-drag.startX,p.y-drag.startY)>4;pan[0]+=p.x-drag.x;pan[1]+=p.y-drag.y;drag.x=p.x;drag.y=p.y;transform();};
  svg.onpointerup=e=>{if(drag?.id===e.pointerId&&!drag.moved){const bounds=svg.getBoundingClientRect();const hit=document.elementFromPoint(Math.max(bounds.left,Math.min(bounds.right-1,e.clientX)),Math.max(bounds.top,Math.min(bounds.bottom-1,e.clientY)))?.closest('[data-cell]');if(hit&&svg.contains(hit))showCell(cells[Number(hit.dataset.cell)]);}drag=null;};
  svg.onpointercancel=()=>{drag=null;};
  const wheel=e=>{e.preventDefault();const p=toLocal(e);setZoom(zoom*Math.exp(-e.deltaY*.0015),[p.x,p.y]);};svg.addEventListener('wheel',wheel,{passive:false});
  svg.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','0'].includes(e.key))return;e.preventDefault();if(e.key==='0'){zoom=1;pan=[0,0];}else if(['+','=','-'].includes(e.key))setZoom(zoom*(e.key==='-'?1/1.3:1.3));else {if(e.key==='ArrowLeft')pan[0]-=25;if(e.key==='ArrowRight')pan[0]+=25;if(e.key==='ArrowUp')pan[1]-=25;if(e.key==='ArrowDown')pan[1]+=25;}transform();};
  async function exportMap(button){
    const kind=button.dataset.export,name=`${data.aquifer.name}-${field}-${data.dates.before}-${data.dates.after}`,status=root.querySelector('.a3-map-exports span');button.disabled=true;
    try{
      if(kind==='csv'){
        const columns=['lon','lat','area_m2','sy','bedrock_msl','before_msl','after_msl','before_m','remaining_m','lost_m','gained_m','before_mcm','remaining_mcm','lost_mcm','remaining_pct','lost_pct','gained_pct'];
        const context=['aquifer','baseline','end','baseline_water_year','end_water_year','percentage_reference','sy_mode','bedrock_source','sy_file','bedrock_file'];
        const rows=[[...context,...columns],...cells.map(c=>[data.aquifer.name,data.dates.before,data.dates.after,data.dates.before_water_year,data.dates.after_water_year,maps.percentage_reference,data.metrics.sy_mode,data.grid.bedrock_source,data.input_files?.sy||'',data.input_files?.bedrock||'',...columns.map(k=>c[k]??'')])];
        const csv=rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');download(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}),name+'.csv');
      }else if(kind==='geojson'){
        const geojson={type:'FeatureCollection',name,metadata:{dates:data.dates,inputs:data.input_files,percentage_reference:maps.percentage_reference},features:cells.map(({polygons,...properties})=>({type:'Feature',properties,geometry:{type:'MultiPolygon',coordinates:polygons}}))};
        download(new Blob([JSON.stringify(geojson)],{type:'application/geo+json'}),name+'.geojson');
      }else{
        const copy=svg.cloneNode(true);copy.setAttribute('xmlns',NS);copy.setAttribute('width',1520);copy.setAttribute('height',1320);copy.setAttribute('style','font-family:Tahoma, sans-serif;direction:ltr');
        // Export the complete aquifer, independent of on-screen panning/zoom.
        copy.querySelector('[clip-path] > g')?.removeAttribute('transform');
        const xml=new XMLSerializer().serializeToString(copy),blob=new Blob([xml],{type:'image/svg+xml;charset=utf-8'});
        if(kind==='svg')download(blob,name+'.svg');else{
          const url=URL.createObjectURL(blob);
          try{const image=new Image();image.src=url;await image.decode();if(disposed)return;const canvas=document.createElement('canvas');canvas.width=1520;canvas.height=1320;canvas.getContext('2d').drawImage(image,0,0);const png=await new Promise(resolve=>canvas.toBlob(resolve));if(!png)throw new Error('ساخت تصویر ناموفق بود.');download(png,name+'.png');}finally{URL.revokeObjectURL(url);}
        }
      }status.textContent='خروجی نقشهٔ انتخابی آماده شد.';
    }catch(error){if(!disposed)status.textContent=error.message;}finally{if(!disposed)button.disabled=false;}
  }
  root.querySelectorAll('[data-export]').forEach(b=>{b.onclick=()=>exportMap(b);});
  draw();
  return ()=>{disposed=true;svg.removeEventListener('wheel',wheel);root.replaceChildren();};
}

export function mountPlanMaps({data,waterRoot,parameterRoot}){
  const maps=data.plan_maps;if(!maps)return ()=>{};
  const cleanups=[];
  if(data.pixel_water)cleanups.push(mountMap(waterRoot,data,['lost_pct','remaining_pct'],'water-plan'));
  else waterRoot.textContent='برای محاسبهٔ درصدها، Sy و تراز کف معتبر را وارد و دوباره محاسبه کنید.';
  const keys=['bedrock_msl','sy'].filter(k=>maps.fields[k]);
  parameterRoot.hidden=!keys.length;
  if(keys.length)cleanups.push(mountMap(parameterRoot.querySelector('.a3-parameter-map'),data,keys,'parameter-plan'));
  return ()=>{cleanups.forEach(fn=>fn());waterRoot.replaceChildren();parameterRoot.hidden=true;};
}

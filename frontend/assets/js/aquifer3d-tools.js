const viewVersion=new URL(import.meta.url).searchParams.get('v')||'1';
const {standardViews,presetCamera}=await import(`./aquifer3d-views.js?v=${encodeURIComponent(viewVersion)}`);
/** Analysis and export controls. Hydrological calculations stay in the worker. */
const $=id=>document.getElementById(id);
const fmt=(v,d=1)=>Number.isFinite(v)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(v):'—';
const NS='http://www.w3.org/2000/svg';
function svgNode(tag,attributes={},text){const node=document.createElementNS(NS,tag);Object.entries(attributes).forEach(([k,v])=>node.setAttribute(k,v));if(text!==undefined)node.textContent=text;return node;}
function chart(svg,series,xLabel='فاصله (کیلومتر)',yLabel='تراز (متر MSL)'){
  svg.replaceChildren();svg.setAttribute('viewBox','0 0 760 300');
  const points=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p.y));
  if(!points.length){svg.append(svgNode('text',{x:380,y:150,'text-anchor':'middle'},'داده‌ای در این مسیر وجود ندارد.'));return;}
  let low=Math.min(...points.map(p=>p.y)),high=Math.max(...points.map(p=>p.y));
  const pad=Math.max(1,(high-low)*.1);low-=pad;high+=pad;
  const minX=Math.min(...series.flatMap(s=>s.points).map(p=>p.x)),maxX=Math.max(...series.flatMap(s=>s.points).map(p=>p.x));
  const x=v=>65+(v-minX)/Math.max(1e-8,maxX-minX)*665,y=v=>250-(v-low)/(high-low)*210;
  for(let i=0;i<=4;i++){
    const value=low+(high-low)*i/4,yy=y(value);
    svg.append(svgNode('line',{x1:65,x2:730,y1:yy,y2:yy,stroke:'#e1e9ef'}),svgNode('text',{x:57,y:yy+4,'text-anchor':'end'},fmt(value)));
    const vx=minX+(maxX-minX)*i/4;
    svg.append(svgNode('text',{x:x(vx),y:272,'text-anchor':'middle'},fmt(vx)));
  }
  series.forEach(s=>{
    let path='',open=false;
    s.points.forEach(p=>{if(!Number.isFinite(p.y)){open=false;return;}path+=`${open?'L':'M'}${x(p.x)},${y(p.y)} `;open=true;});
    svg.append(svgNode('path',{d:path,fill:'none',stroke:s.color,'stroke-width':2.5}));
    if(s.markers)s.points.filter(p=>Number.isFinite(p.y)).forEach(p=>{const dot=svgNode('circle',{cx:x(p.x),cy:y(p.y),r:2.5,fill:s.color});dot.append(svgNode('title',{},p.label||fmt(p.y,2)));svg.append(dot);});
    const offset=series.indexOf(s)*205;
    svg.append(svgNode('text',{x:730-offset,y:21,fill:s.color,'text-anchor':'end'},s.label));
  });
  svg.append(svgNode('text',{x:400,y:296,'text-anchor':'middle'},xLabel),svgNode('text',{x:65,y:21},yLabel));
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
async function svgImage(svg){const copy=svg.cloneNode(true);copy.setAttribute('xmlns',NS);copy.setAttribute('width','1520');copy.setAttribute('height','600');copy.style.font='12px Tahoma, sans-serif';const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'}));try{const image=new Image();image.src=url;await image.decode();return image;}finally{URL.revokeObjectURL(url);}}

export function mountProfessionalTools({data,scene,request,featureIndex}){
  const root=$('professionalTools');root.hidden=false;
  root.innerHTML=`<div class="a3-tool-heading"><h2>ابزارهای تحلیل و خروجی</h2><span id="a3ToolStatus" role="status"></span></div><nav class="a3-tool-tabs" role="tablist" aria-label="ابزارهای سه‌بعدی"></nav><div class="a3-tool-panels"></div>`;
  let disposed=false;const disposers=[];
  const status=message=>{if(!disposed)$('a3ToolStatus').textContent=message;};
  function panel(key,label,html){
    const button=document.createElement('button');button.type='button';button.id=`a3Tab-${key}`;button.role='tab';button.textContent=label;button.setAttribute('aria-controls',`a3Panel-${key}`);
    const body=document.createElement('div');body.id=`a3Panel-${key}`;body.className='a3-tool-panel';body.role='tabpanel';body.setAttribute('aria-labelledby',button.id);body.innerHTML=html;
    root.querySelector('nav').append(button);root.querySelector('.a3-tool-panels').append(body);
    button.onclick=()=>activate(key);
    button.onkeydown=e=>{const buttons=[...root.querySelectorAll('[role=tab]')];let i=buttons.indexOf(button);if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();i=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowLeft'?1:-1)+buttons.length)%buttons.length;buttons[i].click();buttons[i].focus();};
    return body;
  }
  function activate(key){root.querySelectorAll('[role=tab]').forEach(b=>{const active=b.id===`a3Tab-${key}`;b.setAttribute('aria-selected',active);b.tabIndex=active?0:-1;});root.querySelectorAll('[role=tabpanel]').forEach(p=>{p.hidden=p.id!==`a3Panel-${key}`;});}
  // 1. Section endpoints are editable on the polygon, including with the keyboard.
  panel('section','برش مقطعی',`<p>دو سر خط را روی نقشه بکشید؛ کلیدهای جهت نیز نقطهٔ انتخاب‌شده را جابه‌جا می‌کنند. مقطع از کف اصلی ورودی محاسبه می‌شود.</p><div class="a3-section-layout"><div><svg id="a3SectionMap" viewBox="0 0 600 360" role="img" aria-label="نقشهٔ انتخاب مسیر برش"></svg><div class="a3-actions"><label class="hydro-city-toggle"><input type="checkbox" id="a3SectionCities" checked>محدودهٔ شهرها</label><button type="button" id="a3SectionEW">برش غربی–شرقی</button><button type="button" id="a3SectionNS">برش شمالی–جنوبی</button></div></div><div><div class="a3-chart-scroll"><svg id="a3SectionChart" role="img" aria-label="مقطع سطح آب و سنگ‌بستر"></svg></div><p class="a3-scroll-hint">برای دیدن تمام نمودار، آن را افقی جابه‌جا کنید.</p><p id="a3SectionInfo" role="status"></p></div></div>`);
  const polygons=data.display_grid.polygons,coords=polygons.flat(2);
  const west=Math.min(...coords.map(p=>p[0])),east=Math.max(...coords.map(p=>p[0])),south=Math.min(...coords.map(p=>p[1])),north=Math.max(...coords.map(p=>p[1]));
  const sx=111320*Math.cos((south+north)/2*Math.PI/180),scale=Math.min(550/((east-west)*sx),310/((north-south)*111320));
  const xy=p=>[300+(p[0]-(west+east)/2)*sx*scale,180-(p[1]-(south+north)/2)*111320*scale];
  const ll=p=>[Math.max(west,Math.min(east,(p[0]-300)/sx/scale+(west+east)/2)),Math.max(south,Math.min(north,(180-p[1])/111320/scale+(south+north)/2))];
  const map=$('a3SectionMap');
  polygons.forEach(p=>map.append(svgNode('path',{d:p.map(r=>r.map((point,i)=>`${i?'L':'M'}${xy(point).join(',')}`).join(' ')+'Z').join(' '),'fill-rule':'evenodd',fill:'#e3eff4',stroke:'#668496','stroke-width':1})));
  const cities=svgNode('g');map.append(cities);
  const paintCities=()=>{if(!disposed){window.HydroCities?.paintSvg(cities,xy,[west,south,east,north]);$('a3SectionCities').checked=window.HydroCities?.enabled??false;}};
  $('a3SectionCities').onchange=()=>window.HydroCities?.setEnabled($('a3SectionCities').checked);
  const unsubscribeCities=window.HydroCities?.subscribe(paintCities);disposers.push(()=>unsubscribeCities?.());
  window.HydroCities?.ready().then(paintCities).catch(()=>{});
  const line=svgNode('line',{stroke:'#b63d49','stroke-width':2});map.append(line);
  let endpoints=[[west,(south+north)/2],[east,(south+north)/2]],timer,sectionSequence=0,sectionResult;
  const handles=[0,1].map(i=>{const node=svgNode('circle',{r:8,fill:i?'#b63d49':'#14637b',tabindex:0,role:'button','aria-label':i?'انتهای مقطع؛ حرکت با کلیدهای جهت':'ابتدای مقطع؛ حرکت با کلیدهای جهت'});map.append(node);return node;});
  function paintLine(){const [a,b]=endpoints.map(xy);line.setAttribute('x1',a[0]);line.setAttribute('y1',a[1]);line.setAttribute('x2',b[0]);line.setAttribute('y2',b[1]);handles.forEach((h,i)=>{h.setAttribute('cx',[a,b][i][0]);h.setAttribute('cy',[a,b][i][1]);});}
  async function updateSection(){
    const sequence=++sectionSequence;status('در حال محاسبهٔ مقطع…');
    try{const result=await request('cross_section',{start:endpoints[0],end:endpoints[1]});if(disposed||sequence!==sectionSequence)return;
      sectionResult=result;
      chart($('a3SectionChart'),[{label:'سنگ‌بستر',color:'#94754b',k:2},{label:'آب مبنا',color:'#bd7136',k:0},{label:'آب پایان',color:'#287bb8',k:1}].map(s=>({...s,points:result.samples.map(p=>({x:p.distance_m/1000,y:p.levels?.[s.k]??null}))})));
      $('a3SectionInfo').textContent=`طول مسیر ${fmt(result.length_m/1000,2)} کیلومتر؛ شکست خطوط، بیرون محدوده یا حفرهٔ پولیگون است.${result.bedrock_source==='schematic'?' کف این مدل شماتیک است.':''}`;status('مقطع به‌روز شد.');
    }catch(error){if(!disposed&&sequence===sectionSequence)status(error.message);}
  }
  function schedule(){paintLine();clearTimeout(timer);timer=setTimeout(updateSection,180);}
  handles.forEach((handle,i)=>{
    handle.onpointerdown=e=>{handle.setPointerCapture(e.pointerId);handle.dataset.drag='yes';};
    handle.onpointermove=e=>{if(!handle.dataset.drag)return;const point=map.createSVGPoint();point.x=e.clientX;point.y=e.clientY;const local=point.matrixTransform(map.getScreenCTM().inverse());endpoints[i]=ll([local.x,local.y]);schedule();};
    handle.onpointerup=handle.onpointercancel=()=>{delete handle.dataset.drag;};
    handle.onkeydown=e=>{if(!e.key.startsWith('Arrow'))return;e.preventDefault();const p=xy(endpoints[i]);if(e.key==='ArrowLeft')p[0]-=4;if(e.key==='ArrowRight')p[0]+=4;if(e.key==='ArrowUp')p[1]-=4;if(e.key==='ArrowDown')p[1]+=4;endpoints[i]=ll(p);schedule();};
  });
  $('a3SectionEW').onclick=()=>{endpoints=[[west,(south+north)/2],[east,(south+north)/2]];schedule();};
  $('a3SectionNS').onclick=()=>{endpoints=[[(west+east)/2,north],[(west+east)/2,south]];schedule();};
  paintLine();updateSection();activate('section');
  disposers.push(()=>{clearTimeout(timer);sectionSequence++;});
  // 3. Both comparison canvases use the same live camera.
  panel('compare','مقایسهٔ هم‌زمان',`<div class="a3-actions"><label>نوع مقایسه <select id="a3CompareMode"><option value="decline">افت روشن / افت خاموش</option><option value="storage">سنگ‌بستر / ستون‌های معادل آب</option></select></label><label>زاویهٔ دید<select id="a3CompareCamera">${standardViews.map(v=>`<option value="${v.key}"${v.key==='oblique'?' selected':''}>${v.label}</option>`).join('')}</select></label></div><p>چرخاندن، جابه‌جایی و زوم در هر نما، نمای دیگر را هم تغییر می‌دهد.</p><div class="a3-compare-grid"><div><h3>افت روشن</h3><div class="aquifer3d-canvas-wrap"><canvas id="a3CompareA" tabindex="0" aria-label="نمای اول مقایسهٔ سه‌بعدی"></canvas></div></div><div><h3 id="a3CompareTitle">افت خاموش</h3><div class="aquifer3d-canvas-wrap"><canvas id="a3CompareB" tabindex="0" aria-label="نمای دوم مقایسهٔ سه‌بعدی"></canvas></div></div></div>`);
  let compareCleanup=scene.addComparison($('a3CompareA'),$('a3CompareB'));
  $('a3CompareMode').onchange=()=>{compareCleanup();compareCleanup=scene.addComparison($('a3CompareA'),$('a3CompareB'),$('a3CompareMode').value);$('a3CompareTitle').textContent=$('a3CompareMode').value==='storage'?'ستون‌های معادل آب':'افت خاموش';};
  disposers.push(()=>compareCleanup());
  // 4. Camera and layer bookmarks are scoped to the aquifer and stored locally.
  panel('views','نماهای ذخیره‌شده',`<p>نما شامل زاویه، زوم، جابه‌جایی و لایه‌های روشن است. نماهای ذخیره‌شده فقط در همین مرورگر نگهداری می‌شوند.</p><div class="a3-actions" id="a3Presets"></div><div class="a3-actions"><label>نام نما <input id="a3ViewName" maxlength="80" placeholder="مثلاً بخش شرقی با افت روشن"></label><button type="button" id="a3SaveView">ذخیرهٔ نمای فعلی</button></div><div id="a3SavedViews" class="a3-saved-list"></div>`);
  const cameraSelect=$('a3CameraView');
  function applyCameraChoice(value,showScene=false){
    const view=value.startsWith('saved:')?savedViews[Number(value.slice(6))]?.view:{camera:presetCamera(value)};
    if(!view?.camera)return;
    scene.applyView(view);syncLayers();cameraSelect.value=value;
    if(showScene)$('a3Nav-scenes').click();
  }
  cameraSelect.onchange=()=>applyCameraChoice(cameraSelect.value);
  $('a3CompareCamera').onchange=()=>applyCameraChoice($('a3CompareCamera').value);
  standardViews.forEach(({key,label})=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>applyCameraChoice(key,true);$('a3Presets').append(b);});
  const viewsKey=`aquifer3d:views:v1:${featureIndex}`;
  let savedViews=[];
  try{const list=JSON.parse(localStorage.getItem(viewsKey)||'[]');if(Array.isArray(list))savedViews=list.filter(v=>v&&typeof v.name==='string'&&v.view?.camera).slice(0,20);}catch{/* Storage is optional. */}
  function syncLayers(){const view=scene.getView();document.querySelectorAll('[data-scene-layer]').forEach(input=>{input.checked=!!view.layers[input.dataset.sceneLayer];});if($('a3DeclineScale')){$('a3DeclineScale').value=view.declineScale;$('a3DeclineScaleValue').textContent=`×${fmt(view.declineScale,0)}`;}}
  function saveViews(){try{localStorage.setItem(viewsKey,JSON.stringify(savedViews));return true;}catch{status('ذخیرهٔ نما در مرورگر ممکن نیست.');return false;}}
  function listViews(){
    $('a3SavedViews').replaceChildren();
    const previous=cameraSelect.value;cameraSelect.replaceChildren();
    const fixed=document.createElement('optgroup');fixed.label='نماهای اصلی';
    standardViews.forEach(({key,label})=>fixed.append(new Option(label,key)));cameraSelect.append(fixed);
    if(savedViews.length){const custom=document.createElement('optgroup');custom.label='نماهای من';savedViews.forEach((v,i)=>custom.append(new Option(v.name,`saved:${i}`)));cameraSelect.append(custom);}
    cameraSelect.value=[...cameraSelect.options].some(o=>o.value===previous)?previous:'oblique';cameraSelect.disabled=false;
    if(!savedViews.length){const p=document.createElement('p');p.textContent='هنوز نمایی ذخیره نشده است.';$('a3SavedViews').append(p);}
    savedViews.forEach((v,i)=>{const row=document.createElement('div'),open=document.createElement('button'),remove=document.createElement('button');
      row.className='a3-saved-row';open.type=remove.type='button';open.textContent=v.name;remove.textContent='حذف';remove.setAttribute('aria-label',`حذف نمای ${v.name}`);
      open.onclick=()=>{applyCameraChoice(`saved:${i}`,true);status(`نمای «${v.name}» بازیابی شد.`);};remove.onclick=()=>{savedViews.splice(i,1);if($('a3FilmSteps'))filmSteps.forEach(s=>{if(Number(s.viewIndex)===i)s.viewIndex='';else if(Number(s.viewIndex)>i)s.viewIndex=String(Number(s.viewIndex)-1);});saveViews();listViews();};row.append(open,remove);$('a3SavedViews').append(row);
    });
    if($('a3FilmSteps'))filmRows();
  }
  $('a3SaveView').onclick=()=>{const name=$('a3ViewName').value.trim();if(!name){status('نام نما را وارد کنید.');$('a3ViewName').focus();return;}if(savedViews.length>=20){status('حداکثر ۲۰ نما؛ یکی را حذف کنید.');return;}savedViews.push({name,view:scene.getView()});if(saveViews())status('نما ذخیره شد.');$('a3ViewName').value='';listViews();};
  listViews();
  // 5. An editable, ordered film script; all recording is local to the browser.
  panel('film','سناریوی فیلم',`<p>مرحله‌ها را به ترتیب بچینید؛ هر مرحله ۲ تا ۶۰ ثانیه و کل فیلم حداکثر ۵ دقیقه است. حرکت به نما از نماهای ذخیره‌شده استفاده می‌کند.</p><label>عنوان فیلم <input id="a3FilmTitle" maxlength="70" placeholder="عنوان اختیاری"></label><div id="a3FilmSteps" class="a3-film-steps"></div><div class="a3-actions"><button type="button" id="a3AddFilmStep">افزودن مرحله</button><button type="button" id="a3RecordFilm">ساخت و دانلود فیلم</button><button type="button" id="a3CancelFilm" hidden>لغو ساخت</button><output id="a3FilmProgress" aria-live="polite"></output></div>`);
  let filmController=null;
  const filmSteps=[{type:'orbit',kind:'geology',seconds:24,red:true,caption:'افت روشن'},{type:'orbit',kind:'geology',seconds:24,red:false,caption:'افت خاموش'},{type:'orbit',kind:'pixels',seconds:16,red:true,caption:'آب باقی‌مانده و از دست‌رفته'}].filter(s=>s.kind!=='pixels'||data.pixel_water);
  const types=[['orbit','چرخش کامل'],['hold','مکث'],['view','حرکت به نمای ذخیره‌شده'],['section','نمایش مقطع']];
  function filmRows(){
    $('a3FilmSteps').replaceChildren();
    filmSteps.forEach((s,i)=>{
      const row=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=`مرحلهٔ ${fmt(i+1)}`;row.append(legend);
      function select(label,items,key){const wrapper=document.createElement('label'),input=document.createElement('select');wrapper.append(document.createTextNode(label));items.forEach(([value,text])=>input.add(new Option(text,value)));input.value=String(s[key]??'');input.onchange=()=>{s[key]=input.value;};wrapper.append(input);row.append(wrapper);return input;}
      select('حرکت',types,'type');select('نما',[['geology','سنگ‌بستر'],['pixels','ستون‌های آب']],'kind');
      const duration=document.createElement('label'),seconds=document.createElement('input');seconds.type='number';seconds.min='2';seconds.max='60';seconds.value=s.seconds;seconds.setAttribute('aria-label',`مدت مرحلهٔ ${i+1} بر حسب ثانیه`);seconds.oninput=()=>{s.seconds=Number(seconds.value);};duration.append('ثانیه',seconds);row.append(duration);
      const caption=document.createElement('input');caption.value=s.caption;caption.maxLength=100;caption.setAttribute('aria-label',`توضیح مرحلهٔ ${i+1}`);caption.placeholder='توضیح روی فیلم';caption.oninput=()=>{s.caption=caption.value;};row.append(caption);
      const red=document.createElement('input'),redLabel=document.createElement('label');red.type='checkbox';red.checked=s.red;red.onchange=()=>{s.red=red.checked;};redLabel.append(red,'افت روشن');row.append(redLabel);
      const views=select('نمای مقصد',[['','انتخاب نما'],...savedViews.map((v,index)=>[String(index),v.name])],'viewIndex');views.onfocus=()=>{const old=views.value;views.replaceChildren(new Option('انتخاب نما',''));savedViews.forEach((v,index)=>views.add(new Option(v.name,String(index))));views.value=old;};
      [['بالا',-1],['پایین',1],['حذف',0]].forEach(([text,offset])=>{const b=document.createElement('button');b.type='button';b.textContent=text;b.setAttribute('aria-label',`${text} مرحلهٔ ${i+1}`);b.disabled=offset<0&&i===0||offset>0&&i===filmSteps.length-1;b.onclick=()=>{if(offset===0)filmSteps.splice(i,1);else[filmSteps[i],filmSteps[i+offset]]=[filmSteps[i+offset],filmSteps[i]];filmRows();};row.append(b);});
      $('a3FilmSteps').append(row);
    });
  }
  filmRows();$('a3AddFilmStep').onclick=()=>{if(filmSteps.length>=12){status('حداکثر ۱۲ مرحله مجاز است.');return;}filmSteps.push({type:'hold',kind:'geology',seconds:4,red:true,caption:''});filmRows();};
  $('a3CancelFilm').onclick=()=>filmController?.abort();
  $('a3RecordFilm').onclick=async()=>{
    if(filmController)return;
    const controller=new AbortController();filmController=controller;
    $('a3RecordFilm').disabled=true;$('a3CancelFilm').hidden=false;
    try{
      const scenario=filmSteps.map(s=>({...s,view:s.type==='view'&&s.viewIndex!==''&&s.viewIndex!==undefined?savedViews[Number(s.viewIndex)]?.view:undefined}));
      if(scenario.some(s=>s.type==='view'&&!s.view))throw new Error('برای مرحلهٔ حرکت، نمای مقصد را انتخاب کنید.');
      const sectionImage=scenario.some(s=>s.type==='section')?await svgImage($('a3SectionChart')):undefined;
      if(scenario.some(s=>s.type==='section')&&!sectionResult)throw new Error('ابتدا محاسبهٔ مقطع را کامل کنید.');
      const result=await scene.exportVideo({scenario,sectionImage,title:$('a3FilmTitle').value.trim(),signal:controller.signal,onProgress:percent=>{if(!disposed)$('a3FilmProgress').textContent=`${fmt(percent,0)}٪`;}});
      if(!disposed){download(result.blob,`${data.aquifer.name}-scenario.${result.extension}`);status(`فیلم ${result.extension.toUpperCase()} آماده شد.`);}
    }catch(error){if(!disposed)status(error.name==='AbortError'?'ساخت فیلم لغو شد.':error.message);}
    finally{filmController=null;if(!disposed){$('a3RecordFilm').disabled=false;$('a3CancelFilm').hidden=true;}}
  };
  disposers.push(()=>filmController?.abort());
  // 6. Real observations and local cell accounting, with optional pinned cards.
  panel('details','جزئیات و مقایسه',`<p>روی پیزومتر یا ستون سه‌بعدی کلیک کنید، یا از فهرست زیر انتخاب کنید. تا چهار کارت را برای مقایسه ثابت نگه دارید.</p><div class="a3-actions"><label>پیزومتر <select id="a3WellSelect"></select></label><button type="button" id="a3OpenWell">جزئیات پیزومتر</button><label>سلول <select id="a3CellSelect"></select></label><button type="button" id="a3OpenCell">جزئیات سلول</button></div><div id="a3PinnedCards" class="a3-pinned-grid"></div>`);
  data.wells.points.forEach((w,i)=>$('a3WellSelect').add(new Option(w.name,String(i))));
  (data.pixel_water?.cells||[]).forEach((c,i)=>$('a3CellSelect').add(new Option(`${fmt(i+1,0)} · ${fmt(c.lon,4)}, ${fmt(c.lat,4)}`,String(i))));
  $('a3OpenCell').disabled=!data.pixel_water;
  const dialog=document.createElement('dialog');dialog.className='a3-detail-dialog';dialog.setAttribute('aria-label','جزئیات پیزومتر و سلول');
  dialog.innerHTML=`<div class="a3-actions"><button type="button" data-detail-close>بستن</button><button type="button" data-detail-pin disabled>ثابت‌کردن کارت</button></div><div data-detail-body></div>`;document.body.append(dialog);
  const detailBody=dialog.querySelector('[data-detail-body]'),pin=dialog.querySelector('[data-detail-pin]');
  dialog.querySelector('[data-detail-close]').onclick=()=>dialog.close();let detailSequence=0,pinned=0;
  function heading(text){const h=document.createElement('h3');h.textContent=text;detailBody.append(h);}
  function facts(entries){const dl=document.createElement('dl');dl.className='a3-facts';entries.forEach(([name,value])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;dl.append(dt,dd);});detailBody.append(dl);}
  async function showDetail(item){
    const sequence=++detailSequence;pin.disabled=true;detailBody.replaceChildren();heading('در حال دریافت جزئیات…');if(!dialog.open)dialog.showModal();
    try{
      if(item.kind==='cell'){
        const c=item.value;detailBody.replaceChildren();heading(`سلول ${fmt(c.lon,4)}، ${fmt(c.lat,4)}`);
        facts([['مساحت',`${fmt(c.area_m2/1e6,3)} کیلومتر مربع`],['آبدهی ویژه Sy',fmt(c.sy,4)],['کف اصلی',`${fmt(c.bedrock_msl)} متر MSL`],['سطح آب مبنا',`${fmt(c.before_msl)} متر MSL`],['سطح آب پایان',`${fmt(c.after_msl)} متر MSL`],['ضخامت اشباع پایان',`${fmt(c.saturated_m)} متر`],['آب باقی‌مانده',`${fmt(c.remaining_mcm,4)} میلیون مترمکعب`],['آب از دست‌رفته',`${fmt(c.lost_mcm,4)} میلیون مترمکعب`]]);
      }else{
        const w=item.value,result=await request('well_details',{feature_index:featureIndex,name:w.name,lon:w.lon,lat:w.lat});if(disposed||sequence!==detailSequence)return;
        detailBody.replaceChildren();heading(result.name);
        facts([['تراز زمین',`${fmt(result.ground_msl)} متر MSL`],['تراز مبنا',`${fmt(w.before)} متر MSL`],['تراز پایان',`${fmt(w.after)} متر MSL`],['افت دو دوره',`${fmt(w.before-w.after,2)} متر`]]);
        const svg=svgNode('svg',{role:'img','aria-label':`مشاهدات تراز پیزومتر ${result.name}`}),points=[];
        result.records.forEach((r,i)=>{if(i&&r.ordinal-result.records[i-1].ordinal>1)points.push({x:r.ordinal/12,y:null});points.push({x:r.ordinal/12,y:r.level,label:`${r.year}/${r.month} · ${fmt(r.level,2)} متر MSL`});});
        chart(svg,[{label:'تراز مشاهده‌شده',color:'#287bb8',points,markers:true}],'سال شمسی');const chartWrap=document.createElement('div');chartWrap.className='a3-chart-scroll';chartWrap.append(svg);detailBody.append(chartWrap);
        const note=document.createElement('p');note.textContent='فاصلهٔ خطوط نشان‌دهندهٔ ماه فاقد مشاهده است. افت جدول، اختلاف اولین و آخرین مشاهده در همان سال آبی است؛ برای سال ناقص، افت کل سال نیست.';detailBody.append(note);
        const wrap=document.createElement('div');wrap.className='a3-table-wrap';const table=document.createElement('table');table.innerHTML='<thead><tr><th>سال آبی WY</th><th>ماه مشاهده‌شده</th><th>میانگین تراز MSL</th><th>افت بین مشاهدات (متر)</th></tr></thead><tbody></tbody>';
        result.annual.forEach(row=>{const tr=document.createElement('tr');[fmt(row.water_year,0),`${fmt(row.months,0)} از ۱۲`,fmt(row.mean_msl,2),fmt(row.observed_decline_m,2)].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.append(td);});table.querySelector('tbody').append(tr);});wrap.append(table);detailBody.append(wrap);
      }
      if(!disposed&&sequence===detailSequence)pin.disabled=false;
    }catch(error){if(!disposed&&sequence===detailSequence){detailBody.replaceChildren();heading(error.message);}}
  }
  pin.onclick=()=>{if(pinned>=4){status('حداکثر چهار کارت؛ یک کارت را ببندید.');dialog.close();return;}const card=document.createElement('article'),close=document.createElement('button'),content=detailBody.cloneNode(true);content.removeAttribute('data-detail-body');card.className='a3-pinned-card';close.type='button';close.textContent='حذف کارت';close.onclick=()=>{card.remove();pinned--;};content.querySelectorAll('[id]').forEach(n=>n.removeAttribute('id'));card.append(close,content);$('a3PinnedCards').append(card);pinned++;dialog.close();activate('details');};
  $('a3OpenWell').onclick=()=>showDetail({kind:'well',value:data.wells.points[Number($('a3WellSelect').value)]});
  $('a3OpenCell').onclick=()=>showDetail({kind:'cell',value:data.pixel_water.cells[Number($('a3CellSelect').value)]});
  scene.setPickHandler(showDetail);
  disposers.push(()=>{detailSequence++;scene.setPickHandler(null);dialog.close();dialog.remove();});
  // 7. A display-only multiplier; numerical storage accounting is untouched.
  panel('scale','بزرگ‌نمایی افت',`<p>فقط ضخامت بخش قرمز بزرگ‌تر نمایش داده می‌شود. ترازها و اعداد حجم بر اساس دادهٔ اصلی هستند. ضریب روی نما، فیلم و تصویر خروجی درج می‌شود.</p><div class="a3-actions"><label>ضریب نمایش افت <input type="range" id="a3DeclineScale" min="1" max="10" step="1" value="1"><output id="a3DeclineScaleValue">×۱</output></label><button type="button" id="a3ResetScale">بازگشت به ضخامت واقعی</button></div>`);
  let scaleTimer;
  function changeScale(){const value=Number($('a3DeclineScale').value);$('a3DeclineScaleValue').textContent=`×${fmt(value,0)}`;clearTimeout(scaleTimer);scaleTimer=setTimeout(()=>{if(!disposed)scene.setDeclineScale(value);},120);}
  $('a3DeclineScale').oninput=changeScale;$('a3DeclineScale').onchange=changeScale;$('a3ResetScale').onclick=()=>{$('a3DeclineScale').value=1;changeScale();};disposers.push(()=>clearTimeout(scaleTimer));
  // 10. Self-contained PNG and printable report; no data leaves the browser.
  panel('export','خروجی و گزارش',`<p>تصویر ۱۶:۹ با عنوان، دوره، واحدها، منبع کف، Sy و ضریب نمایش ساخته می‌شود. گزارش، فایل مستقل HTML با تصاویر و مقطع است و از مرورگر به PDF چاپ می‌شود.</p><div class="a3-actions"><label>نما <select id="a3ExportLayout"><option value="pair">دو نما کنار هم</option><option value="geology">سنگ‌بستر</option><option value="pixels">ستون‌های آب</option></select></label><label>وضوح <select id="a3ExportSize"><option value="1920">۱۹۲۰ × ۱۰۸۰</option><option value="3840">۳۸۴۰ × ۲۱۶۰</option></select></label><label>زمینه <select id="a3ExportBackground"><option value="light">روشن</option><option value="transparent">شفاف (PNG)</option></select></label><label>عنوان <input id="a3ExportTitle" maxlength="90" placeholder="عنوان اختیاری"></label></div><div class="a3-actions"><button type="button" id="a3ExportPNG">دانلود تصویر PNG</button><button type="button" id="a3ExportSection">دانلود تصویر مقطع</button><button type="button" id="a3ExportReport">گزارش قابل چاپ / PDF</button></div>`);
  let exporting=false;
  async function exportTask(type){
    if(exporting)return;exporting=true;const buttons=[$('a3ExportPNG'),$('a3ExportReport'),$('a3ExportSection')];buttons.forEach(b=>{b.disabled=true;});status('در حال آماده‌سازی خروجی…');
    try{
      if(type==='section'){
        if(!sectionResult)throw new Error('ابتدا مقطع را محاسبه کنید.');
        const image=await svgImage($('a3SectionChart')),canvas=document.createElement('canvas');canvas.width=1920;canvas.height=900;const ctx=canvas.getContext('2d');ctx.fillStyle='white';ctx.fillRect(0,0,1920,900);ctx.fillStyle='#173e56';ctx.textAlign='right';ctx.font='bold 28px Tahoma';ctx.fillText(`${data.aquifer.name} · مقطع سطح آب و سنگ‌بستر`,1850,60);ctx.drawImage(image,50,130,1820,720);ctx.font='18px Tahoma';ctx.fillText(`طول ${fmt(sectionResult.length_m/1000,2)} کیلومتر · شهریور ${data.dates.before.slice(0,4)} تا ${data.dates.after.slice(0,4)}`,1850,105);const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(blob&&!disposed)download(blob,`${data.aquifer.name}-section.png`);
      }else{
        const image=await scene.exportImage({layout:$('a3ExportLayout').value,width:Number($('a3ExportSize').value),transparent:type==='png'&&$('a3ExportBackground').value==='transparent',title:$('a3ExportTitle').value.trim()});
        if(disposed)return;
        if(type==='png')download(image.blob,`${data.aquifer.name}-3d.png`);
        else{
          const doc=document.implementation.createHTMLDocument('گزارش آبخوان');doc.documentElement.lang='fa';doc.documentElement.dir='rtl';const meta=doc.createElement('meta');meta.setAttribute('charset','utf-8');doc.head.prepend(meta);
          const style=doc.createElement('style');style.textContent='body{font:15px Tahoma,sans-serif;color:#173e56;max-width:1200px;margin:24px auto;padding:20px;line-height:1.9}img{width:100%;height:auto}h1{font-size:24px}p{white-space:pre-wrap}button{padding:12px;font:inherit}@page{size:A4 landscape;margin:12mm}@media print{button{display:none}body{padding:0;margin:0;font-size:11px}img{max-height:155mm;object-fit:contain}h2{break-before:page}}';doc.head.append(style);
          const title=doc.createElement('h1');title.textContent=$('a3ExportTitle').value.trim()||`گزارش آبخوان ${data.aquifer.name}`;
          const print=doc.createElement('button');print.textContent='چاپ / ذخیره به PDF';print.setAttribute('onclick','window.print()');const img=doc.createElement('img');img.src=image.dataUrl;img.alt='نماهای سه‌بعدی آبخوان';doc.body.append(title,print,img);
          for(const text of [data.method,$('sourceNote').textContent,$('coverageNote').textContent,`افت میانگین ${fmt(data.metrics.mean_head_decline_m,2)} متر؛ ذخیرهٔ مبنا ${fmt(data.metrics.drainable_before_mcm)} و ذخیرهٔ پایان ${fmt(data.metrics.drainable_after_mcm)} میلیون مترمکعب. سال آبی از مهر تا شهریور است. ضریب نمایش افت ×${fmt(scene.getView().declineScale)}؛ حجم‌ها با ضخامت واقعی محاسبه شده‌اند.`]){const p=doc.createElement('p');p.textContent=text;doc.body.append(p);}
          if(sectionResult){const h=doc.createElement('h2');h.textContent='برش مقطعی';const section=await svgImage($('a3SectionChart')),canvas=document.createElement('canvas');canvas.width=1520;canvas.height=600;canvas.getContext('2d').drawImage(section,0,0);const image=doc.createElement('img');image.src=canvas.toDataURL();image.alt='مقطع تراز آب مبنا، پایان و کف اصلی';const p=doc.createElement('p');p.textContent=`ابتدا ${endpoints[0].join(', ')}؛ انتها ${endpoints[1].join(', ')}؛ طول ${fmt(sectionResult.length_m/1000,2)} کیلومتر. کف اصلی ورودی استفاده شده است.`;doc.body.append(h,p,image);}
          if(!disposed)download(new Blob(['<!doctype html>\n'+doc.documentElement.outerHTML],{type:'text/html;charset=utf-8'}),`${data.aquifer.name}-report.html`);
        }
      }
      if(!disposed)status('خروجی آماده شد.');
    }catch(error){if(!disposed)status(error.message);}finally{exporting=false;if(!disposed)buttons.forEach(b=>{b.disabled=false;});}
  }
  $('a3ExportPNG').onclick=()=>exportTask('png');$('a3ExportReport').onclick=()=>exportTask('report');$('a3ExportSection').onclick=()=>exportTask('section');
  activate('section');
  return ()=>{cameraSelect.onchange=null;cameraSelect.disabled=true;disposed=true;disposers.reverse().forEach(fn=>fn());root.hidden=true;root.replaceChildren();};
}

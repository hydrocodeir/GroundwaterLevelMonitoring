/** Management UI. Trends, spatial screening and all projections run in Pyodide. */
const version=new URL(import.meta.url).searchParams.get('v')||'management-1';
const {mountMap}=await import(`./aquifer3d-maps.js?v=${encodeURIComponent(version)}`);
const {foldSettings,foldExplanation,managementStage}=await import(`./aquifer3d-layout.js?v=${encodeURIComponent(version)}`);
const fmt=(v,d=1)=>Number.isFinite(v)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(v):'نامشخص';
const year=v=>new Intl.NumberFormat('fa-IR',{useGrouping:false}).format(v);
const NS='http://www.w3.org/2000/svg';
const categories=(labels,colors)=>labels.map((label,i)=>({label,short:label,color:colors[i]}));
const priorityLabels=['معیارها عبور نشده','افت بالا','محدودیت کیفیت','افت و کیفیت','نزدیک آستانه','روند نامشخص','کیفیت نامشخص','افت؛ کیفیت نامشخص','کیفیت؛ روند نامشخص'];
const priorityColors=['#d9e7d6','#e8b376','#c5a5cf','#be6970','#9a343b','#d6dce0','#e5e1d6','#dfbd8d','#c9b4ca'];
const statusLabels={already:'اکنون زیر آستانه',crossing:'عبور در ادامهٔ روند',not_crossed:'عدم عبور با این روند',unknown:'آستانه یا روند نامشخص'};
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
function node(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
async function sourceStorage(value,remove=false){
  return new Promise((resolve,reject)=>{
    const open=indexedDB.open('aquifer-management-v1',1);
    open.onupgradeneeded=()=>open.result.createObjectStore('sources');
    open.onerror=()=>reject(open.error);
    open.onsuccess=()=>{const db=open.result,write=value!==undefined||remove,tx=db.transaction('sources',write?'readwrite':'readonly'),store=tx.objectStore('sources');
      const job=remove?store.delete('subsidence'):write?store.put(value,'subsidence'):store.get('subsidence');
      let result;job.onsuccess=()=>{result=job.result;};tx.oncomplete=()=>{db.close();resolve(result);};tx.onerror=()=>{db.close();reject(tx.error);};};
  });
}
function plot(root,forecasts,report,volume=false){
  root.replaceChildren();const width=Math.max(320,root.clientWidth||640),height=250;
  const svg=node('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':volume?'مسیر حجم در محدودهٔ دارای روند':'مسیر تغییر تراز در محدودهٔ دارای روند'});root.append(svg);
  const central=volume?'remaining_supported_mcm':'mean_head_change_m',low=volume?'remaining_low_mcm':'mean_head_low_m',high=volume?'remaining_high_mcm':'mean_head_high_m';
  const baseline=volume?report.current_supported_mcm:0;
  const points=[{horizon:0,[central]:baseline,[low]:baseline,[high]:baseline},...forecasts].filter(p=>Number.isFinite(p[central]));
  if(points.length<2){svg.append(node('text',{x:width/2,y:height/2,'text-anchor':'middle','font-size':12},'پوشش داده کافی نیست.'));return;}
  const values=points.flatMap(p=>[p[low],p[high],p[central]]).filter(Number.isFinite),lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.12,volume?1:.2),maxH=Math.max(...points.map(p=>p.horizon));
  const x=h=>68+h/maxH*(width-90),y=v=>193-(v-(lo-pad))/(hi-lo+2*pad)*132;
  for(let i=0;i<=4;i++){const value=lo-pad+(hi-lo+2*pad)*i/4;svg.append(node('line',{x1:68,x2:width-22,y1:y(value),y2:y(value),stroke:'#dce6ec'}),node('text',{x:60,y:y(value)+4,'text-anchor':'end','font-size':11},fmt(value,volume?0:1)));}
  const path=points.map((p,i)=>`${i?'L':'M'}${x(p.horizon)},${y(p[high])}`).join(' ')+points.toReversed().map(p=>`L${x(p.horizon)},${y(p[low])}`).join(' ')+'Z';
  svg.append(node('path',{d:path,fill:'#d9e9f0'}),node('path',{d:points.map((p,i)=>`${i?'L':'M'}${x(p.horizon)},${y(p[central])}`).join(' '),stroke:'#14647a','stroke-width':2.5,fill:'none'}));
  for(const p of points){const dot=node('circle',{cx:x(p.horizon),cy:y(p[central]),r:3.5,fill:'#14647a'});dot.append(node('title',{},`افق ${fmt(p.horizon,0)} سال: ${fmt(p[central],2)}`));svg.append(dot);}
  for(let i=0;i<=4;i++){const h=maxH*i/4;svg.append(node('text',{x:x(h),y:215,'text-anchor':'middle','font-size':11},fmt(h)));}
  svg.append(node('text',{x:width-20,y:23,'text-anchor':'end','font-size':13,'font-weight':600},volume?'حجم بخش دارای روند':'تغییر تراز نسبت به زمان پایان'),node('text',{x:width-20,y:43,'text-anchor':'end','font-size':11},volume?'میلیون مترمکعب':'متر'),node('text',{x:width/2,y:242,'text-anchor':'middle','font-size':11},'افق آینده (سال آبی)'));
}

export function mountManagementTools({data,request,featureIndex}){
  const root=document.getElementById('managementTools');root.hidden=false;
  root.innerHTML=`<div class="aquifer3d-section-heading"><div><h2>اولویت اقدام و آیندهٔ آبخوان</h2><p>غربالگری مکانی، ادامهٔ روند مشاهداتی و زمان رسیدن به آستانهٔ انتخابی</p></div></div>
  <div class="a3-management-inputs">
    <label>افق‌های آینده (سال)<input data-m-input="horizons" value="3,5,10,25" dir="ltr"><small>با ویرگول جدا کنید؛ افق‌های دلخواه مثل ۱۵ یا ۵۰ قابل اضافه‌شدن‌اند.</small></label>
    <label>دورهٔ روند (سال آبی)<input data-m-input="lookback" type="number" min="3" max="200" value="10"></label>
    <label>روش روند<select data-m-input="method"><option value="sen">شیب مقاوم Theil–Sen</option><option value="ols">رگرسیون خطی OLS</option></select></label>
    <label>تعریف آستانه بحرانی<select data-m-input="threshold_type"><option value="saturated">حداقل ضخامت اشباع (متر)</option><option value="drawdown">افت مجاز از تراز فعلی (متر)</option><option value="head">حداقل تراز آب (متر MSL)</option></select></label>
    <label>مقدار آستانه<input data-m-input="threshold" type="number" step="any" placeholder="توسط شما تعیین شود"><small>خالی: زمان بحرانی محاسبه نمی‌شود؛ عدد فرضی جایگزین نمی‌شود.</small></label>
    <label>افق اقدام (سال)<input data-m-input="urgent_years" type="number" min="0" step="any" placeholder="کوچک‌ترین افق انتخابی"><small>عبور از آستانه در این مدت، اولویت اقدام می‌گیرد.</small></label>
  </div>
  <details class="a3-management-settings"><summary>معیارهای اولویت و کنترل پوشش داده</summary><div class="a3-management-inputs">
    <label>معیار افت سالانه (متر/سال)<input data-m-input="decline_limit" type="number" min="0" step="any" placeholder="خودکار از توزیع نرخ افت"><small>مقدار خالی: صدک نسبی نرخ‌های مثبت؛ حد ایمنی نیست.</small></label>
    <label>صدک اولویت نسبی<input data-m-input="priority_quantile" type="number" min="0" max="100" value="75"></label>
    <label>معیار کیفیت<select data-m-input="quality_mode"><option value="crop">محدودیت شدید کشاورزی EC/SAR</option><option value="drinking">آستانه شوری شرب</option><option value="either">هر یک از دو محدودیت</option></select></label>
    <label>حداقل شهریور مشاهده‌شده<input data-m-input="min_observations" type="number" min="3" value="5"></label>
    <label>حداقل سهم سال‌های دارای مشاهده (۰ تا ۱)<input data-m-input="coverage" type="number" min="0" max="1" step="0.05" value="0.5"></label>
    <label>حداقل شهریور هم‌دورهٔ فرونشست<input data-m-input="subsidence_min_observations" type="number" min="3" value="3"><small>روند این نقشه جداگانه در دورهٔ همان لایه برازش می‌شود.</small></label>
    <label>شعاع پشتیبانی مکانی (کیلومتر)<input data-m-input="support_km" type="number" min="0.001" step="any" placeholder="خودکار از فاصلهٔ نقاط"><small>خالی: دو برابر میانهٔ فاصله تا نزدیک‌ترین نقطه؛ درون پوش محدب.</small></label>
    <label>همسایه‌های IDW<input data-m-input="neighbors" type="number" min="3" max="100" value="8"></label>
    <label>توان IDW<input data-m-input="power" type="number" min="0.1" max="10" step="0.1" value="2"></label>
    <label>معیار تغییرشکل (mm/year)<input data-m-input="subsidence_limit" type="number" min="0" step="any" placeholder="خودکار از توزیع نرخ مثبت"><small>خالی: همان صدک نسبی؛ حد آسیب سازه نیست.</small></label>
    <label>معیار نشست تجمعی (میلی‌متر)<input data-m-input="cumulative_subsidence_limit" type="number" min="0" step="any" placeholder="صدک نسبی نشست تجمعی"></label>
    <label>معیار افت تجمعی آب (متر)<input data-m-input="cumulative_decline_limit" type="number" min="0" step="any" placeholder="صدک نسبی افت هم‌دوره"></label>
    <label>فاصلهٔ مجاز مشاهدات آب از مرز دوره (ماه)<input data-m-input="endpoint_tolerance_months" type="number" min="0" max="24" value="1"><small>برای مقایسهٔ تجمعی؛ نبود مشاهدهٔ کافی، نامشخص می‌ماند.</small></label>
  </div></details>
  <details class="a3-management-settings" data-m-source-details><summary>لایهٔ مستقل فرونشست / تغییرشکل زمین <span data-m-source-name>وارد نشده</span></summary>
    <p>برای نشست تجمعی، ستون <code>cumulative_mm</code> و برای نرخ، <code>rate_mm_year</code> استفاده می‌شود. نوع داده و مبنای سال را مشخص کنید. CSV تبدیل‌شده از TIFF، شمارهٔ سطر و ستون را نگه می‌دارد تا NoData با درون‌یابی پر نشود. لایهٔ پروژه بر اساس موقعیت آبخوان خودکار انتخاب می‌شود؛ فایل انتخابی شما جایگزین آن است.</p>
    <div class="a3-management-inputs"><label>فایل فرونشست<input type="file" accept=".csv,.geojson,.json,text/csv,application/json" data-m-source></label>
    <label>نوع مقادیر<select data-m-sub="value_kind"><option value="rate">نرخ سالانه</option><option value="cumulative">نشست تجمعی دوره</option></select></label>
    <label>مبنای سال دوره<select data-m-sub="calendar_basis"><option value="water_year">سال آبی (مهر تا شهریور)</option><option value="persian">سال شمسی (فروردین تا اسفند)</option></select></label>
    <label>مدت اعلامی دوره (سال)<input data-m-sub="duration_years" type="number" min="0.001" step="any" placeholder="برای میانگین سالانهٔ تجمعی"><small>تقسیم مقدار تجمعی بر مدت؛ سری زمانی سالانه تولید نمی‌کند.</small></label>
    <label>واحد ستون عمومی تجمعی<select data-m-sub="unit"><option value="mm">میلی‌متر</option><option value="cm">سانتی‌متر</option><option value="m">متر</option></select><small>ستون cumulative_mm همواره میلی‌متر است؛ این انتخاب برای cumulative_value است.</small></label>
    <label>حداقل پوشش معتبر TIFF (۰ تا ۱)<input data-m-sub="min_pixel_coverage" type="number" min="0" max="1" step="0.05" value="0.5"></label>
    <label>مؤلفهٔ اندازه‌گیری<select data-m-sub="component"><option value="">انتخاب کنید</option><option value="vertical">قائم</option><option value="los">خط دید ماهواره (LOS)</option></select></label>
    <label>قرارداد علامت<select data-m-sub="direction"><option value="down">مثبت = نشست / دورشدن در LOS</option><option value="up">منفی = نشست / دورشدن در LOS</option></select></label>
    <label><span data-m-start-label>سال آبی شروع</span><input data-m-sub="start_water_year" type="number" placeholder="یا ستون تاریخ در فایل"></label>
    <label><span data-m-end-label>سال آبی پایان</span><input data-m-sub="end_water_year" type="number" placeholder="یا ستون تاریخ در فایل"></label></div>
    <div class="a3-actions"><button type="button" data-m-template>الگوی CSV</button><button type="button" data-m-project hidden>استفاده از لایهٔ پروژه</button><button type="button" data-m-project-csv hidden>دریافت CSV پروژه</button><button type="button" data-m-remove>حذف لایه از تحلیل</button></div><p data-m-source-status role="status"></p>
  </details>
  <div class="a3-actions"><button type="button" data-m-run>محاسبه و به‌روزرسانی</button><span data-m-status role="status" aria-live="polite">در حال آماده‌سازی تحلیل مدیریتی…</span></div>
  <div data-m-results hidden><div class="a3-management-cards"></div><p class="a3-management-caution">مسیر آینده، ادامهٔ روند گذشته است؛ اثر کاهش برداشت یا تغییر اقلیم در آن شبیه‌سازی نشده است. دامنهٔ رنگی حساسیت شیب است و احتمال یا فاصلهٔ اطمینان ۹۵٪ نیست.</p>
    <nav class="a3-management-tabs" role="tablist" aria-label="تحلیل مدیریتی"><button type="button" role="tab" aria-selected="true" id="mgTab-priority" aria-controls="mgView-priority" data-m-tab="priority">اولویت مداخله</button><button type="button" role="tab" aria-selected="false" tabindex="-1" id="mgTab-future" aria-controls="mgView-future" data-m-tab="future">مسیر آینده</button><button type="button" role="tab" aria-selected="false" tabindex="-1" id="mgTab-critical" aria-controls="mgView-critical" data-m-tab="critical">آستانه بحرانی</button><button type="button" role="tab" aria-selected="false" tabindex="-1" id="mgTab-subsidence" aria-controls="mgView-subsidence" data-m-tab="subsidence">افت و فرونشست</button></nav>
    <div data-m-view="priority" id="mgView-priority" role="tabpanel" aria-labelledby="mgTab-priority"><p data-m-priority-note></p><div class="a3-management-zones"></div><button type="button" data-m-quality>رفتن به محاسبهٔ کیفیت آب</button></div>
    <div data-m-view="future" id="mgView-future" role="tabpanel" aria-labelledby="mgTab-future" hidden><p data-m-future-note></p><div class="a3-management-chart" data-m-head-chart></div><div class="a3-management-chart" data-m-volume-chart></div><div class="a3-table-wrap" data-m-forecast-table></div></div>
    <div data-m-view="critical" id="mgView-critical" role="tabpanel" aria-labelledby="mgTab-critical" hidden><p data-m-critical-note></p><div class="a3-table-wrap" data-m-critical-table></div></div>
    <div data-m-view="subsidence" id="mgView-subsidence" role="tabpanel" aria-labelledby="mgTab-subsidence" hidden><p data-m-subsidence-note></p><button type="button" data-m-open-source>تنظیم لایهٔ فرونشست</button></div>
    <label class="a3-management-horizon">افق نقشه<select data-m-horizon></select></label><div class="a3-management-map a3-map"></div>
    <details class="a3-management-settings"><summary>پوشش، اعتبارسنجی و فرض‌های محاسبه</summary><div data-m-method></div></details>
    <div class="a3-actions"><button type="button" data-m-json>دریافت نتایج و شناسنامه JSON</button><button type="button" data-m-forecast-csv>جدول افق‌ها CSV</button></div>
  </div>`;
  const $=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
  const settingsLayout=foldSettings(root,{key:'management',title:'تنظیم افق‌ها، آستانه و داده‌های تحلیل',nodes:all(':scope > .a3-management-inputs, :scope > .a3-management-settings')});
  foldExplanation($('[data-m-future-note]'),'پوشش داده و تفسیر مسیر آینده');
  foldExplanation($('[data-m-forecast-table]'),'جدول افق‌های آینده');
  foldExplanation($('[data-m-critical-table]'),'جدول زمان عبور برای پیکسل‌ها');
  foldExplanation($('[data-m-subsidence-note]'),'دوره، پوشش و روش مقایسه');
  const stageLayout=managementStage(root);
  const thresholdButton=document.createElement('button');thresholdButton.type='button';thresholdButton.textContent='تعیین یا تغییر آستانه';thresholdButton.onclick=()=>{settingsLayout.details.open=true;$('[data-m-input=threshold]').focus();};$('[data-m-view=critical]').append(thresholdButton);
  const storageKey=`aquifer-management:${JSON.stringify([data.aquifer.mahdoude,data.aquifer.name,data.plan_maps.extent])}`;
  let disposed=false,sequence=0,timer,result=null,mapCleanup=null,quality=null,active='priority',subsidence={text:'',file_name:''},projectSource=null;
  try{const saved=JSON.parse(localStorage.getItem(storageKey)||'{}');all('[data-m-input]').forEach(input=>{if(saved[input.dataset.mInput]!==undefined)input.value=saved[input.dataset.mInput];});}catch{/* Defaults remain visible. */}
  function settings(){return Object.fromEntries(all('[data-m-input]').map(input=>[input.dataset.mInput,input.value]));}
  function subSettings(){return Object.fromEntries(all('[data-m-sub]').map(input=>[input.dataset.mSub,input.value]));}
  function periodLabels(){const persian=$('[data-m-sub=calendar_basis]').value==='persian';$('[data-m-start-label]').textContent=persian?'سال شمسی شروع':'سال آبی شروع';$('[data-m-end-label]').textContent=persian?'سال شمسی پایان':'سال آبی پایان';}
  function applySource(saved,origin){
    subsidence={...saved,origin};
    all('[data-m-sub]').forEach(input=>{if(saved[input.dataset.mSub]!==undefined&&saved[input.dataset.mSub]!==null)input.value=saved[input.dataset.mSub];});
    $('[data-m-source-name]').textContent=saved.file_name;periodLabels();
  }
  async function loadProject(){
    const response=await fetch('/subsidence/sources.json',{cache:'no-cache'});if(!response.ok)return;
    const registry=await response.json(),extent=data.plan_maps.extent;
    const entry=registry.sources?.find(s=>s.extent_wgs84?.length===4&&s.extent_wgs84[0]<=extent[2]&&s.extent_wgs84[2]>=extent[0]&&s.extent_wgs84[1]<=extent[3]&&s.extent_wgs84[3]>=extent[1]);
    if(!entry)return;
    for(const path of [entry.csv_url,entry.metadata_url])if(new URL(path,location.origin).origin!==location.origin)throw new Error('منبع پروژه باید محلی باشد.');
    const [csv,meta]=await Promise.all([fetch(entry.csv_url),fetch(entry.metadata_url)]);if(!csv.ok||!meta.ok)throw new Error('دریافت لایهٔ پروژه ناموفق بود.');
    const [text,m]=await Promise.all([csv.text(),meta.json()]);
    if(disposed)return;
    projectSource={text,file_name:m.csv_file,source_id:entry.id,value_kind:m.quantity,component:m.component,direction:m.direction,
      calendar_basis:m.calendar_basis,start_water_year:m.start_year,end_water_year:m.end_year,duration_years:m.duration_years,
      unit:m.unit,period_precision:m.period_precision,raster_grid:m.raster_grid,csv_sha256:m.csv_sha256,
      source_sha256:m.source_sha256,source_statistics:m.statistics};
    $('[data-m-project]').hidden=false;$('[data-m-project-csv]').hidden=false;
  }
  function table(target,headers,rows){const table=document.createElement('table'),head=document.createElement('thead'),line=document.createElement('tr');headers.forEach(text=>{const th=document.createElement('th');th.textContent=text;line.append(th);});head.append(line);table.append(head);const body=document.createElement('tbody');for(const values of rows){const tr=document.createElement('tr');values.forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.append(td);});body.append(tr);}table.append(body);target.replaceChildren(table);}
  function drawMap(){
    if(!result)return;mapCleanup?.();
    const report=result.report,h=Number($('[data-m-horizon]').value),cumulative=report.subsidence.cumulative,cells=result.plan_maps.cells.map(c=>{
      const future=c.management_horizons[String(h)];
      return {...c,management_critical_status_label:statusLabels[c.management_critical_status],management_future_saturated:future.saturated_m,management_future_head:future.head_msl,management_future_volume:future.remaining_mcm};
    });
    const criticalCategories=categories(['اکنون',...report.settings.horizons.map(h=>`تا ${fmt(h,0)} سال`),'بیرون افق','عدم عبور با روند','نامشخص'],['#9a343b',...report.settings.horizons.map((_,i)=>['#cb7770','#e1a479','#e9cda0','#d5ddc6'][Math.min(i,3)]),'#a6c2bd','#b9cfd7','#d6dce0']);
    const fields={
      management_priority:{label:'اولویت مداخله',unit:'معیارهای همین تحلیل',palette:priorityColors,categories:categories(priorityLabels,priorityColors)},
      management_decline:{label:'نرخ افت تراز',unit:'متر/سال؛ منفی = افزایش',palette:['#73b7ad','#f4e9cd','#a54443']},
      management_ec:{label:'EC دورهٔ کیفیت',unit:'µS/cm؛ وضعیت مشاهده‌ای تعمیم‌یافته',palette:['#cde2b5','#edb974','#ae4347']},
      management_critical_band:{label:'زمان رسیدن به آستانه',unit:'سال از تاریخ پایان مدل',palette:['#b15e59','#e9cda0','#b9cfd7'],categories:criticalCategories},
      management_subsidence:{label:cumulative?'میانگین سالانهٔ نشست تجمعی':report.subsidence.component==='los'?'نرخ تغییرشکل خط دید':'نرخ نشست قائم',unit:'mm/year؛ میانگین دوره، مثبت = نشست / دورشدن',palette:['#73b7ad','#f4e9cd','#a54443']},
      management_subsidence_cumulative:{label:report.subsidence.component==='los'?'تغییرشکل تجمعی خط دید':'نشست تجمعی قائم',unit:report.subsidence.component==='los'?'میلی‌متر؛ مثبت = دورشدن':'میلی‌متر؛ مثبت = نشست',palette:['#73b7ad','#f4e9cd','#a54443']},
      management_groundwater_cumulative:{label:'افت تجمعی آب در دورهٔ منبع',unit:'متر؛ اختلاف مشاهدات ابتدا و انتها',palette:['#73b7ad','#f4e9cd','#a54443']},
      management_subsidence_coverage_pct:{label:'پوشش پیکسل‌های معتبر نشست',unit:'٪ از مراکز پیکسل‌های خانه',palette:['#ece8dd','#a7c2c5','#286878']},
      management_subsidence_decline:{label:'نرخ افت هم‌دورهٔ تغییرشکل',unit:'متر/سال؛ منفی = افزایش',palette:['#73b7ad','#f4e9cd','#a54443']},
      management_overlap:{label:cumulative?'هم‌مکانی افت و نشست تجمعی':'هم‌مکانی افت و تغییرشکل زمین',unit:'معیارهای همین تحلیل',palette:['#d9e7d6','#e8b376','#be6970'],categories:categories(['بدون عبور از معیار','افت بالا','تغییرشکل بالا','هر دو بالا','تغییرشکل نامشخص','آب نامشخص'],['#d9e7d6','#e8b376','#afa1cd','#b45864','#e4e1d8','#d6dce0'])},
      management_future_saturated:{label:`ضخامت اشباع در افق ${fmt(h,0)} سال`,unit:'متر؛ ادامهٔ روند',palette:['#f2dfcf','#9fc9d3','#1d6888']},
      management_future_head:{label:`تراز خطی در افق ${fmt(h,0)} سال`,unit:'متر MSL؛ برون‌یابی ریاضی',palette:['#f2dfcf','#9fc9d3','#1d6888']},
      management_future_volume:{label:`حجم در افق ${fmt(h,0)} سال`,unit:'میلیون مترمکعب در پیکسل',palette:['#f2dfcf','#9fc9d3','#1d6888']}
    };
    const keys=active==='priority'?['management_priority','management_decline','management_ec']:active==='critical'?['management_critical_band','management_decline']:active==='subsidence'?(cumulative?['management_overlap','management_subsidence_cumulative','management_groundwater_cumulative','management_subsidence','management_subsidence_coverage_pct']:['management_overlap','management_subsidence','management_subsidence_decline']):['management_future_saturated','management_future_head','management_future_volume'];
    const note=active==='subsidence'?'هم‌مکانی، علت فرونشست را اثبات نمی‌کند. دادهٔ تغییرشکل باید مستقل و هم‌دوره باشد؛ بیرون پشتیبانی نامشخص است.':active==='critical'?'آستانه از انتخاب شما می‌آید؛ عدم عبور با این روند به معنی ایمن‌بودن همیشگی نیست. زمان‌ها سناریویی‌اند.':active==='future'?'کف اصلی و Sy مدل فعال ثابت نگه داشته شده‌اند. حجم فقط برای بخش دارای روند گزارش می‌شود؛ برون‌یابی زیر کف، تراز فیزیکی معتبر نیست.':'این نقشه غربالگری اولویت است؛ معیار نسبی، حد ایمنی نیست و فقدان کیفیت به معنی مناسب‌بودن آب نیست.';
    const period=report.subsidence.periods[0];
    const calendarPeriod=report.subsidence.source_years;
    const caption=active==='subsidence'?(cumulative&&calendarPeriod?`دورهٔ ${report.subsidence.calendar_basis==='persian'?'شمسی':'سال آبی'} ${year(calendarPeriod[0])} تا ${year(calendarPeriod[1])}؛ دقت منبع: سال`:period?`دورهٔ مشترک سال آبی ${year(period[0])} تا ${year(period[1])}`:'لایهٔ مستقل تغییرشکل وارد نشده یا فاقد پوشش است'):`دورهٔ روند: سال آبی ${year(report.trend_start_water_year)} تا ${year(report.trend_end_water_year)}${active==='future'?` | افق ${fmt(h,0)} سال`:''}`;
    stageLayout.context.textContent=caption;
    mapCleanup=mountMap($('.a3-management-map'),{...data,plan_maps:{...result.plan_maps,cells},management_report:report,management_horizon:h,management_note:note,management_caption:caption},keys,'management-plan',fields);
  }
  function paintCharts(){if(disposed||!result||active!=='future')return;requestAnimationFrame(()=>{if(disposed||!result||active!=='future')return;plot($('[data-m-head-chart]'),result.report.forecasts,result.report);plot($('[data-m-volume-chart]'),result.report.forecasts,result.report,true);});}
  function activate(key,focus=false){active=key;root.dataset.managementView=key;all('[data-m-tab]').forEach(button=>{const selected=button.dataset.mTab===key;button.setAttribute('aria-selected',selected);button.tabIndex=selected?0:-1;if(selected&&focus)button.focus();});all('[data-m-view]').forEach(panel=>{panel.hidden=panel.dataset.mView!==key;});$('.a3-management-horizon').hidden=key!=='future';$('.a3-management-caution').hidden=key!=='future';drawMap();paintCharts();}
  function render(){
    const r=result.report;
    document.dispatchEvent(new CustomEvent('a3:subsidence-result',{detail:result}));
    settingsLayout.context.textContent=`افق ${r.settings.horizons.map(h=>fmt(h,0)).join('، ')} سال · دورهٔ روند ${fmt(r.settings.lookback,0)} سال`;
    $('.a3-management-cards').replaceChildren();
    for(const [label,value,note]of [['پیزومترهای دارای روند',`${fmt(r.eligible_wells,0)} از ${fmt(r.well_count,0)}`,`شهریورهای سال آبی ${year(r.trend_start_water_year)} تا ${year(r.trend_end_water_year)}`],['پوشش مکانی روند',`${fmt(r.trend_supported_area_pct)}٪`,'آیندهٔ بخش بیرون پوشش، نامشخص می‌ماند.'],['خطای آزمون زمانی',r.backtest_mae_m===null?'آزمون کافی نیست':`${fmt(r.backtest_mae_m,2)} متر`,`${fmt(r.backtest_predictions,0)} پیش‌بینی مشاهدهٔ بعدی؛ تأیید افق بلندمدت نیست.`],['پوشش مشترک افت و تغییرشکل',`${fmt(r.overlap_supported_area_pct)}٪`,r.subsidence.input_records?'از لایهٔ ورودی مستقل':'لایهٔ فرونشست وارد نشده است.']]){const card=document.createElement('article');for(const[tag,text]of [['span',label],['strong',value],['small',note]]){const node=document.createElement(tag);node.textContent=text;card.append(node);}$('.a3-management-cards').append(card);}
    $('[data-m-priority-note]').textContent=`معیار افت: ${fmt(r.used_decline_limit_m_year,3)} متر/سال (${r.relative_decline_criterion?`صدک نسبی ${fmt(r.settings.priority_quantile,0)}`:'تعیین‌شده توسط شما'}). پوشش کیفیت ${fmt(r.quality_supported_area_pct)}٪؛ نزدیکی به آستانه در افق ${fmt(r.settings.urgent_years)} سال سنجیده شده است. با محاسبه یا تغییر کیفیت، این نقشه خودکار به‌روز می‌شود.`;
    $('.a3-management-zones').replaceChildren();priorityLabels.forEach((label,i)=>{if(!r.priority_counts[i])return;const item=document.createElement('span'),dot=document.createElement('i');dot.style.background=priorityColors[i];item.append(dot,document.createTextNode(`${label}: ${fmt(r.priority_areas_km2[i])} کیلومتر مربع`));$('.a3-management-zones').append(item);});
    const long=r.forecasts.filter(p=>p.long_extrapolation).map(p=>fmt(p.horizon,0));
    $('[data-m-future-note]').textContent=`مبدأ: شهریور ${year(Number(data.dates.after.slice(0,4)))}، پایان سال آبی ${year(r.trend_end_water_year)}. حجم فعلی در بخش دارای روند ${fmt(r.current_supported_mcm)} و حجم فعلی خارج پوشش روند ${fmt(r.current_unknown_mcm)} میلیون مترمکعب است. ${long.length?`افق‌های ${long.join('، ')} سال از طول حداقل سابقهٔ برازش بلندترند؛ تفسیر سناریویی لازم است.`:''} خطوط بین افق‌ها راهنمای دیداری‌اند.`;
    plot($('[data-m-head-chart]'),r.forecasts,r);plot($('[data-m-volume-chart]'),r.forecasts,r,true);
    table($('[data-m-forecast-table]'),['افق (سال)','سال آبی','تغییر تراز (متر)','حجم بخش دارای روند (میلیون m³)','دامنه حساسیت حجم','مساحت رسیده به آستانه (km²)'],r.forecasts.map(p=>[fmt(p.horizon,0),year(p.water_year),fmt(p.mean_head_change_m,2),fmt(p.remaining_supported_mcm),`${fmt(p.remaining_low_mcm)} تا ${fmt(p.remaining_high_mcm)}`,fmt(p.critical_area_km2)]));
    $('[data-m-critical-note]').textContent=r.settings.threshold===null?'مقدار آستانه را تعیین کنید. ضخامت اشباع به کف معتبر نیاز دارد؛ افت مجاز و تراز آب از کف مستقل‌اند.':`آستانه ${fmt(r.settings.threshold,2)} با تعریف انتخابی شما اعمال شده است. تاریخ، نخستین سال آبی شامل عبور است؛ سناریوی شیب کند ممکن است اصلاً عبور نکند. این تاریخ، زمان اتمام کل آبخوان نیست.`;
    const sorted=[...result.plan_maps.cells].sort((a,b)=>(a.management_critical_years??Infinity)-(b.management_critical_years??Infinity));
    table($('[data-m-critical-table]'),['طول / عرض','وضعیت','سال تا آستانه','سال آبی عبور','شیب سریع / کند (سال)'],sorted.map(c=>[`${fmt(c.lon,4)} / ${fmt(c.lat,4)}`,statusLabels[c.management_critical_status],fmt(c.management_critical_years,2),c.management_critical_water_year===null?'—':year(c.management_critical_water_year),`${fmt(c.management_critical_fast,2)} / ${c.management_critical_slow_status==='not_crossed'?'عدم عبور':fmt(c.management_critical_slow,2)}`]));
    const sub=r.subsidence,cumulative=Boolean(sub.cumulative);
    const subLimit=cumulative?r.used_cumulative_subsidence_limit_mm:r.used_subsidence_limit_mm_year;
    $('[data-m-subsidence-note]').textContent=sub.input_records?`منبع: ${sub.input_file}. ${fmt(sub.inside_records,0)} پیکسل/رکورد داخل آبخوان؛ پوشش معتبر ${fmt(r.subsidence_supported_area_pct)}٪ و ${fmt(sub.aligned_wells,0)} پیزومتر هم‌دوره. معیار ${cumulative?'نشست تجمعی':'نرخ'} ${fmt(subLimit,2)} ${cumulative?'میلی‌متر':'mm/year'} ${r.relative_subsidence_criterion?'نسبی است.':'توسط شما تعیین شده است.'} ${cumulative?`افت آب از اختلاف مشاهدات ابتدا و انتهای پنجرهٔ همان سال‌ها به دست می‌آید؛ تاریخ روز و ماه منبع معلوم نیست و تطبیق تقریبی است. میانگین سالانه فقط تقسیم بر مدت اعلامی ${fmt(sub.duration_years)} سال است.`:''} ${sub.raster_grid?`خانه‌ها میانگین پیکسل‌های معتبر TIFF را نمایش می‌دهند؛ NoData پر نمی‌شود. بیشینهٔ پیکسل اصلی ${fmt(sub.source_statistics?.maximum_signed_mm,1)} میلی‌متر است.`:''} ${sub.component==='los'?'مؤلفهٔ خط دید است؛ قائم تفسیر نکنید.':'مؤلفهٔ قائم معرفی شده است.'}`:'لایهٔ مستقلی برای فرونشست موجود نیست. نشست از افت آب تولید نمی‌شود؛ لایهٔ معتبر را معرفی کنید.';
    $('[data-m-method]').replaceChildren();for(const text of [`شعاع پشتیبانی: ${fmt(r.support_radius_km,2)} کیلومتر. روش ${r.settings.method}، تعداد همسایه ${fmt(r.settings.neighbors,0)} و توان ${fmt(r.settings.power,1)}.`,...r.notes]){const p=document.createElement('p');p.textContent=text;$('[data-m-method]').append(p);}
    const previous=$('[data-m-horizon]').value;$('[data-m-horizon]').replaceChildren();r.settings.horizons.forEach(h=>$('[data-m-horizon]').add(new Option(`${fmt(h,0)} سال · سال آبی ${year(r.trend_end_water_year+h)}`,String(h))));if(r.settings.horizons.includes(Number(previous)))$('[data-m-horizon]').value=previous;
    $('[data-m-results]').hidden=false;activate(active);
  }
  async function calculate(){
    clearTimeout(timer);const token=++sequence;$('[data-m-run]').disabled=true;$('[data-m-status]').textContent='در حال محاسبهٔ روند، افق‌ها و اولویت مکانی…';
    try{const options={...settings(),subsidence:{...subsidence,...subSettings()},quality,computed_at_utc:new Date().toISOString()};
      try{localStorage.setItem(storageKey,JSON.stringify(settings()));}catch{/* Computation remains available. */}
      const answer=await request('management',{feature_index:featureIndex,options});if(disposed||token!==sequence)return;result=answer;render();$('[data-m-status]').textContent='تحلیل مدیریتی با ورودی‌های فعلی به‌روز شد.';
    }catch(error){if(!disposed&&token===sequence){result=null;document.dispatchEvent(new CustomEvent('a3:subsidence-result',{detail:null}));$('[data-m-results]').hidden=true;$('[data-m-status]').textContent=error.message;}}
    finally{if(!disposed&&token===sequence)$('[data-m-run]').disabled=false;}
  }
  function invalidate(){sequence++;result=null;document.dispatchEvent(new CustomEvent('a3:subsidence-result',{detail:null}));mapCleanup?.();mapCleanup=null;$('[data-m-results]').hidden=true;$('[data-m-status]').textContent='ورودی تغییر کرد؛ در حال به‌روزرسانی…';clearTimeout(timer);timer=setTimeout(calculate,450);}
  function projectSettingsKey(){return storageKey+':project:'+JSON.stringify([projectSource?.csv_sha256,projectSource?.value_kind,projectSource?.component,projectSource?.direction,projectSource?.calendar_basis,projectSource?.start_water_year,projectSource?.end_water_year,projectSource?.duration_years]);}
  async function saveSource(){try{if(subsidence.text){if(subsidence.origin==='project')localStorage.setItem(projectSettingsKey(),JSON.stringify(subSettings()));else await sourceStorage({...subsidence,...subSettings()});}}catch{if(!disposed)$('[data-m-source-status]').textContent='ذخیرهٔ پایدار لایه ممکن نشد؛ در این نشست قابل استفاده است.';}}
  all('[data-m-input]').forEach(input=>input.addEventListener(input.tagName==='SELECT'?'change':'input',invalidate));
  all('[data-m-sub]').forEach(input=>input.addEventListener('change',()=>{periodLabels();saveSource();invalidate();}));
  $('[data-m-run]').onclick=calculate;$('[data-m-horizon]').onchange=drawMap;
  all('[data-m-tab]').forEach(button=>{button.onclick=()=>activate(button.dataset.mTab);button.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=all('[data-m-tab]'),i=tabs.indexOf(button),next=e.key==='Home'?tabs[0]:e.key==='End'?tabs.at(-1):tabs[(i+(e.key==='ArrowLeft'?1:tabs.length-1))%tabs.length];activate(next.dataset.mTab,true);};});
  $('[data-m-quality]').onclick=()=>document.getElementById('a3Nav-quality').click();
  $('[data-m-open-source]').onclick=()=>{settingsLayout.details.open=true;const details=$('[data-m-source-details]');details.open=true;details.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});$('[data-m-source]').focus();};
  $('[data-m-source]').onchange=async()=>{const file=$('[data-m-source]').files[0];if(!file)return;const text=await file.text();if(disposed)return;subsidence={text,file_name:file.name,origin:'upload'};try{localStorage.setItem(storageKey+':source-mode','upload');localStorage.removeItem(storageKey+':source-disabled');}catch{}const header=text.slice(0,500);if(header.includes('cumulative_mm')||header.includes('cumulative_value'))$('[data-m-sub=value_kind]').value='cumulative';else if(header.includes('rate_mm_year')){$('[data-m-sub=value_kind]').value='rate';$('[data-m-sub=calendar_basis]').value='water_year';}periodLabels();$('[data-m-source-name]').textContent=file.name;$('[data-m-source-status]').textContent='مشخصات دوره، علامت و مؤلفهٔ فایل جدید را در همین فرم کنترل کنید.';await saveSource();if(!disposed)invalidate();};
  $('[data-m-remove]').onclick=async()=>{subsidence={text:'',file_name:''};$('[data-m-source]').value='';$('[data-m-source-name]').textContent='وارد نشده';try{localStorage.setItem(storageKey+':source-disabled','true');await sourceStorage(undefined,true);}catch{/* Current layer is still removed. */}if(!disposed)invalidate();};
  $('[data-m-project]').onclick=()=>{if(!projectSource)return;applySource(projectSource,'project');try{localStorage.removeItem(storageKey+':source-disabled');localStorage.setItem(storageKey+':source-mode','project');}catch{}invalidate();};
  $('[data-m-project-csv]').onclick=()=>{if(projectSource)download(new Blob([projectSource.text],{type:'text/csv;charset=utf-8'}),projectSource.file_name);};
  $('[data-m-template]').onclick=()=>{const cumulative=$('[data-m-sub=value_kind]').value==='cumulative';download(new Blob([cumulative?'longitude,latitude,cumulative_mm,start_year,end_year\r\n':'longitude,latitude,rate_mm_year,start_water_year,end_water_year\r\n'],{type:'text/csv;charset=utf-8'}),'subsidence-template.csv');};
  $('[data-m-json]').onclick=()=>{if(result)download(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}),`${data.aquifer.name}-management-WY${result.report.trend_end_water_year}.json`);};
  $('[data-m-forecast-csv]').onclick=()=>{if(!result)return;const columns=Object.keys(result.report.forecasts[0]),rows=[['aquifer','reference_water_year','trend_area_pct',...columns],...result.report.forecasts.map(p=>[data.aquifer.name,result.report.trend_end_water_year,result.report.trend_supported_area_pct,...columns.map(k=>p[k]??'')])];download(new Blob(['\ufeff'+rows.map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),`${data.aquifer.name}-future-WY${result.report.trend_end_water_year}.csv`);};
  function qualityChanged(event){const q=event.detail;quality=q?{volume_end:data.dates.after,thresholds:q.report.thresholds,quality_water_year:q.report.quality_water_year,input_file:q.report.quality_input_file,cells:q.plan_maps.cells.map(c=>Object.fromEntries(['lon','lat','quality_ec','quality_supported','quality_zone_code'].map(k=>[k,c[k]])))}:null;invalidate();}
  document.addEventListener('a3:quality-result',qualityChanged);
  (async()=>{let saved;try{saved=await sourceStorage();}catch{}if(disposed)return;try{await loadProject();}catch(error){if(!disposed)$('[data-m-source-status]').textContent=error.message;}if(disposed)return;let preferProject=false;try{preferProject=localStorage.getItem(storageKey+':source-mode')==='project';}catch{}if(saved&&!preferProject)applySource(saved,'upload');else if(projectSource){let disabled=false,overrides={};try{disabled=localStorage.getItem(storageKey+':source-disabled')==='true';overrides=JSON.parse(localStorage.getItem(projectSettingsKey())||'{}');}catch{}if(!disabled)applySource({...projectSource,...overrides},'project');}periodLabels();calculate();})();
  let lastPlotWidth=0;const chartResize=new ResizeObserver(entries=>{const w=entries[0].contentRect.width;if(Math.abs(w-lastPlotWidth)>.5){lastPlotWidth=w;paintCharts();}});chartResize.observe(stageLayout.analysis);
  return ()=>{disposed=true;sequence++;clearTimeout(timer);chartResize.disconnect();mapCleanup?.();document.removeEventListener('a3:quality-result',qualityChanged);root.replaceChildren();root.hidden=true;};
}

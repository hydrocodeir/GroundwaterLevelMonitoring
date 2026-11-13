/** Scenario editor. All physical calculations and exports execute in Pyodide. */
const version=new URL(import.meta.url).searchParams.get('v')||'1';
const {mountMap}=await import(`./aquifer3d-maps.js?v=${encodeURIComponent(version)}`);
const {mountLifetimeScene}=await import(`./aquifer3d-render.js?v=${encodeURIComponent(version)}`);
const {standardViews}=await import(`./aquifer3d-views.js?v=${encodeURIComponent(version)}`);
const errorText=e=>String(e?.message||e).trim().split('\n').filter(Boolean).at(-1).replace(/^ValueError: /,'');
const fmt=(v,d=1)=>Number.isFinite(v)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(v):'نامشخص';
const colors=['#963f48','#cf785e','#dda96f','#d8c89c','#aac6bc','#5d99a2','#3d7484'];
function bandColor(index,count){const t=(index+1)/Math.max(1,count)*(colors.length-1),a=Math.min(colors.length-2,Math.floor(t)),u=t-a;return '#'+[1,3,5].map(k=>Math.round(parseInt(colors[a].slice(k,k+2),16)*(1-u)+parseInt(colors[a+1].slice(k,k+2),16)*u).toString(16).padStart(2,'0')).join('');}
const causeLabels=['عبور تا پایان افق رخ نمی‌دهد','کمیت','شوری','فرونشست','هم‌زمان','نامشخص'];
const causeColors=['#649d92','#cc885b','#aa78ab','#8b566d','#9b3944','#d8dee2'];
function download(blob,name){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),60000);}
const input=(key,label,value='',attrs='')=>`<label>${label}<input data-lt="${key}" value="${value}" ${attrs}></label>`;
const rateWindow=(key,label,initial,first)=>`<label>${label}<select data-lt="${key}_window"><option value="${initial}">${first}</option><option value="4">ادامهٔ روند ۴ سال اخیر</option><option value="10">ادامهٔ روند ۱۰ سال اخیر</option><option value="all">ادامهٔ روند کل دورهٔ موجود</option><option value="custom">دورهٔ دلخواه</option></select></label><label data-lt-window-custom="${key}" hidden>طول دوره (سال آبی)<input data-lt="${key}_window_years" type="number" min="3" max="200" step="1" value="10"></label><p class="lt-rate-note" data-lt-window-note="${key}" role="status"></p>`;

export function mountLifetimeTools({data,request,climateFile=null}){
  const root=document.getElementById('lifetimeTools');root.hidden=false;
  root.innerHTML=`<header class="lt-heading"><h2>عمر سناریویی</h2><div class="lt-actions"><select data-lt-saved aria-label="سناریوهای ذخیره‌شده"><option value="">سناریوهای من</option></select><button type="button" data-lt-new>سناریوی جدید</button><button type="button" data-lt-import>ورود سناریو</button><input type="file" data-lt-import-file accept=".json" hidden></div></header>
  <p data-help-copy>عمر سناریویی، زمان رسیدن به محدودیت انتخابی است؛ سن آب، برداشت مجاز یا تاریخ خالی‌شدن آبخوان نیست. زون‌های فاقد داده خاکستری می‌مانند. همهٔ سال‌ها بر مبنای سال آبی مهر–شهریور هستند.</p>
  <div class="lt-prerequisites" aria-label="آمادگی داده‌های سناریو">${[['quality','شوری','کیفیت آب'],['subsidence','فرونشست','آینده و اقدام']].map(([key,label,destination])=>`<article data-lt-prereq="${key}"><div><strong>${label}</strong><span data-lt-prereq-state="${key}" role="status">اجرا نشده</span></div><p data-lt-prereq-guide="${key}"></p><button type="button" data-lt-prepare="${key}">رفتن به ${destination}</button></article>`).join('')}</div>
  <div class="lt-presets"><label><span data-lt-preset-label>سناریوی آماده</span><select data-lt-preset><option value="">انتخاب قالب…</option></select></label><button type="button" data-lt-preset-apply disabled>استفاده از قالب</button><span data-lt-preset-state role="status"></span><p data-help-copy data-lt-preset-help></p></div><details class="lt-editor" open><summary>تعریف سناریو</summary><form data-lt-form novalidate>
    <div class="lt-basics">${input('name','نام سناریو','سناریوی پایه','maxlength="80" required')}${input('horizon','افق بررسی (سال)',50,'type="number" min="1" max="200" step="1"')}<label>مصرف<select data-lt="use"><option value="crop">کشاورزی · شوری</option><option value="drinking">شرب · فقط شوری</option></select></label></div>
    <div class="lt-spatial"><input type="hidden" data-lt="spatial_method"><input type="hidden" data-lt="spatial_coverage" value="aquifer"><input type="hidden" data-lt="spline_smoothing"><label data-lt-spline hidden></label><button type="button" data-lt-spatial-edit></button></div>
    <div class="a3-quantity-prerequisite" data-lt-quantity-missing hidden><span>این معیار به سنگ‌بستر و Sy نیاز دارد.</span><button type="button" data-lt-quantity-inputs>تکمیل داده‌های کمّی</button></div>
    <div class="lt-criteria">
      <section><label class="lt-toggle"><input type="checkbox" data-lt="quantity_on" checked>محدودیت کمّی</label><div data-lt-body="quantity"><label>معیار<select data-lt="quantity_type"><option value="storage_loss_pct" selected>کاهش ذخیره از شروع سناریو (%)</option><option value="saturated">حداقل ضخامت اشباع (متر)</option><option value="drawdown">افت مجاز از امروز (متر)</option><option value="head">حداقل تراز (متر MSL)</option></select></label><label><span data-lt-quantity-label>کاهش ذخیره (%)</span><input data-lt="quantity_limit" value="25" type="number" min="0.1" max="100" step="any" placeholder="تعیین کنید"></label>${input('drop_factor','ضریب روند افت',1,'type="number" min="0" max="10" step="any"')}<div class="lt-quantity-guide" data-lt-quantity-guide><div class="lt-quantity-choices" role="group" aria-label="انتخاب درصد کاهش ذخیره">${[10,25,50].map(v=>`<button type="button" data-lt-storage-choice="${v}" aria-pressed="${v===25}">کاهش ${fmt(v,0)}٪</button>`).join('')}</div><output data-lt-quantity-preview role="status">در انتظار مدل…</output><metadata data-lt-quantity-meta></metadata><p data-help-copy>درصد نسبت به ذخیرهٔ شروع سناریو و برای هر پیکسل جداست. مقادیر سریع، فرض‌های قابل‌ویرایش‌اند و حد استاندارد یا ایمنی نیستند. معادل حجمی، جمع بخش دارای کف و Sy است؛ زمان عبور همهٔ پیکسل‌ها یکسان نیست. میانهٔ افت معادل با وزن مساحتِ ستون‌های دارای ذخیرهٔ مثبت محاسبه می‌شود. نبود روند همچنان عمر را نامشخص می‌کند؛ ستونِ دارای ذخیرهٔ آغازین صفر، از ابتدا محدودیت کمّی دارد. با تغییر Sy یا کف، حجم مرجع از نو محاسبه می‌شود.</p></div><p data-help-copy>ضریب ۱ یعنی ادامهٔ روند مشاهده‌شده؛ صفر یعنی تثبیت مسیر تراز. تغییر درصد برداشت به همین درصد افت تبدیل نمی‌شود. آستانه باید توسط شما تعیین شود.</p></div></section>
      <section><label class="lt-toggle"><input type="checkbox" data-lt="quality_on">محدودیت شوری</label><div data-lt-body="quality" hidden>${input('quality_limit','حد EC شرب (µS/cm)',1500,'type="number" min="1"')}${input('crop_limit','حد EC کشاورزی (µS/cm)',3000,'type="number" min="1"')}${input('ec_growth_pct','تغییر EC در سال (%)',0,'type="number" min="-50" max="100" step="any"')}<button type="button" data-lt-quality>محاسبه / تغییر کیفیت</button><p data-help-copy>EC نماینده از نتیجهٔ معتبر «کیفیت آب» خوانده می‌شود. نرخ، فرض شماست؛ سابقهٔ ناکافی بازسازی نمی‌شود. حدود آغازین سناریویی‌اند و تأیید سلامت شرب یا سازگاری محصول نیستند. EC نسبت به سال نمونه‌برداری تا تاریخ مدل هم با همین فرض منتقل می‌شود. SAR و سایر آلاینده‌ها در عمر شوری محاسبه نمی‌شوند.</p></div></section>
      <section><label class="lt-toggle"><input type="checkbox" data-lt="subsidence_on">محدودیت فرونشست</label><div data-lt-body="subsidence" hidden>${input('subsidence_limit','نشست اضافی مجاز (میلی‌متر)','','type="number" min="0" step="any" placeholder="تعیین کنید"')}${input('sub_factor','ضریب نرخ نشست',1,'type="number" min="0" max="10" step="any"')}<button type="button" data-lt-source>لایهٔ فرونشست</button><p data-help-copy>نرخ از لایهٔ مستقل مدیریت خوانده می‌شود. برای TIFF تجمعی، میانگین مقدار بر مدت اعلامی مبناست؛ فرض ادامهٔ آینده است و شتاب را نشان نمی‌دهد. آستانه، نشست اضافی از تاریخ مدل است. LOS به قائم تبدیل نمی‌شود. نشست از Sy یا ضخامت کم نمی‌شود.</p></div></section>
    </div>
    <section class="lt-climate"><label class="lt-toggle"><input type="checkbox" data-lt="climate_on">اثر اقلیم</label><div data-lt-climate hidden><div class="lt-basics">${input('climate_precip_pct','تغییر بارش (%)',0,'type="number" min="-100" max="200" step="any"')}${input('climate_temp_c','تغییر دما (°C)',0,'type="number" min="-10" max="15" step="any"')}${input('climate_years','زمان تحقق (سال)',20,'type="number" min="1" max="200"')}</div><label>سابقهٔ بارش و دما<input type="file" data-lt-climate-file accept=".csv,text/csv"><small data-lt-climate-name>وارد نشده</small></label><button type="button" data-lt-climate-template>الگوی CSV اقلیم</button><p data-help-copy>تغییر بارش و دما نسبت به میانگین دورهٔ هم‌پوشانی‌اند. فایل میانگین مکانی همان آبخوان: water_year,precip_mm,temp_c؛ یا year_persian,month_persian,precip_mm,temp_c. بارش مجموع، دما میانگین ماهانه است. سال ناقص کنار گذاشته می‌شود؛ رکورد تکراری پذیرفته نمی‌شود. حداقل ۱۲ سال هم‌دوره و ۴ آزمون آینده‌نگر لازم است. اثر اقلیم فقط با بهبود خطای آزمون حداقل ۱۰٪ و علامت سازگار اعمال می‌شود. اثر تجربی است؛ تفکیک علّی اقلیم از برداشت نیست.</p></div></section>
    <details class="lt-advanced"><summary>تنظیمات بیشتر</summary><div class="lt-basics">${input('transition_years','زمان رسیدن به ضریب افت (سال)',1,'type="number" min="0" max="200" step="any"')}${input('manual_drop_m_year','افت جایگزین (متر/سال)','','type="number" step="any" placeholder="خالی: روند مشاهده‌شده"')}${input('sy_factor','ضریب Sy ورودی',1,'type="number" min="0.01" max="10" step="any"')}${input('floor_offset_m','تغییر تراز کف (متر)',0,'type="number" min="-1000" max="1000" step="any"')}${input('phase_year','شروع مرحلهٔ دوم (سال)','','type="number" min="0" max="200" placeholder="اختیاری"')}${input('phase_factor','ضریب افت در مرحلهٔ دوم',1,'type="number" min="0" max="10" step="any"')}${input('area_target_pct','سهم مساحت بحرانی (%)',25,'type="number" min="0.1" max="100" step="any"')}<label>معیار شوری<select data-lt="quality_mode"><option value="ec">عبور EC نماینده از حد</option><option value="fraction">سهم ستون زیر حد شوری</option></select></label>${input('min_usable_pct','حداقل سهم زیر حد (%)',50,'type="number" min="0" max="100" step="any"')}</div><label>زون‌های سناریو (GeoJSON)<input type="file" data-lt-zones accept=".geojson,.json"><small data-lt-zone-name>کل آبخوان</small></label><button type="button" data-lt-zones-clear>پاک‌کردن زون‌ها</button><button type="button" data-lt-zone-template>الگوی زون</button><p data-help-copy>پارامترهای مجاز هر زون: drop_factor,ec_growth_pct,sub_factor,sy_factor,floor_offset_m. مرکز پیکسل تعیین‌کننده است؛ همپوشانی پذیرفته نمی‌شود. فایل جایگزین کف یا Sy در «تنظیمات مدل» وارد می‌شود. تغییر Sy حجم را عوض می‌کند، ولی با مسیر تراز تجویزی زمان عبور کمّی را عوض نمی‌کند.</p>
    <label class="lt-toggle"><input type="checkbox" data-lt="sensitivity_on">دامنهٔ حساسیت</label><div class="lt-basics" data-lt-sensitivity hidden>${input('sensitivity_floor_m','دامنهٔ تغییر کف (± متر)',0,'type="number" min="0" max="1000" step="any"')}${input('sensitivity_sy_pct','دامنهٔ Sy (± درصد)',0,'type="number" min="0" max="90" step="any"')}${input('sensitivity_ec_pct','دامنهٔ نرخ EC (± واحد درصد)',0,'type="number" min="0" max="100" step="any"')}</div><p data-help-copy>سه ترکیب مرکزی، افت سریع و افت کند با دامنه‌های انتخابی اجرا می‌شود. دامنه، فاصلهٔ اطمینان یا احتمال نیست. عبورِ بیرون افق یا ترکیب نامشخص جدا گزارش می‌شود؛ دامنهٔ کل لزوماً تعیین‌پذیر نیست.</p></details>
    <footer class="lt-runbar"><button type="submit" data-lt-run disabled>محاسبهٔ سناریو</button><button type="button" data-lt-delete>حذف سناریوی ذخیره‌شده</button></footer>
  </form></details><p class="lt-status" data-lt-status role="status">در انتظار روند آبخوان…</p><div class="lt-stale" data-lt-stale hidden role="status">تنظیمات تغییر کرده‌اند؛ نمایش مربوط به آخرین محاسبه است.</div>
  <div data-lt-results hidden><div class="lt-cards"></div><p class="lt-spatial-status" data-lt-spatial-status role="status"></p><details class="lt-diagnostics" data-lt-diagnostics hidden><summary>علت پیکسل‌های نامشخص</summary><div data-lt-diagnostics-body></div></details><div class="lt-result-bar"><strong data-lt-result-name></strong><span data-lt-climate-status></span><label>نمایش<select data-lt-view><option value="map">نقشهٔ عمر</option><option value="cause">عامل محدودکننده</option><option value="support">پوشش مکانی روند</option><option value="climate">مقایسهٔ اقلیم</option><option value="compare">مقایسهٔ سناریوها</option><option value="3d">نمای سه‌بعدی</option></select></label></div><p data-help-copy data-lt-result-note></p>
  <div class="lt-comparison-controls" hidden><label>مقایسه با<select data-lt-compare></select></label></div><div class="lt-map"></div><div class="lt-secondary-map" hidden></div>
  <div class="lt-3d" hidden><div class="lt-actions"><label>زاویه<select data-lt-camera>${standardViews.map(v=>`<option value="${v.key}"${v.key==='oblique'?' selected':''}>${v.label}</option>`).join('')}</select></label><button type="button" data-lt-zoom="in" aria-label="بزرگ‌نمایی">+</button><button type="button" data-lt-zoom="out" aria-label="کوچک‌نمایی">−</button><button type="button" data-lt-pan aria-pressed="false">جابه‌جایی</button><button type="button" data-lt-zoom="reset">بازنشانی</button><output data-lt-zoom-label>۱۰۰٪</output></div><div class="lt-scene-wrap"><canvas tabindex="0" aria-label="رنگ‌بندی عمر سناریویی روی ستون‌های ذخیرهٔ فعلی آبخوان"></canvas></div><div class="lt-legend"></div></div>
  <details class="lt-curves"><summary>مساحت و حجم در طول زمان</summary><div data-lt-charts></div><div class="lt-table-wrap"><table><thead><tr><th>افق</th><th>مساحت بحرانی</th><th>مساحت نامشخص</th><th>ذخیرهٔ بخش قابل محاسبه</th></tr></thead><tbody data-lt-rows></tbody></table></div></details>
  <div class="lt-actions lt-exports"><button type="button" data-lt-export="scenario">فایل سناریو</button><button type="button" data-lt-export="json">گزارش JSON</button><button type="button" data-lt-export="csv">جدول CSV</button><button type="button" data-lt-export="tiff">نقشه TIFF</button><button type="button" data-lt-export="status">دسته‌بندی TIFF</button><button type="button" data-lt-export="support">پوشش مکانی TIFF</button></div><metadata data-lt-metadata></metadata></div>`;
  const $=s=>root.querySelector(s),all=s=>[...root.querySelectorAll(s)];
  const sharedSpatial=data.spatial||{method:'idw',spline_smoothing:0,coverage:'aquifer'};
  function sharedControls(){$('[data-lt=spatial_method]').value=sharedSpatial.method;$('[data-lt=spatial_coverage]').value='aquifer';$('[data-lt=spline_smoothing]').value=sharedSpatial.spline_smoothing;}
  sharedControls();$('[data-lt-spatial-edit]').textContent='روش مکانی: '+({idw:'IDW',spline:'Spline',thiessen:'تیسن'}[sharedSpatial.method])+' · کل آبخوان · تغییر';
  $('[data-lt-spatial-edit]').onclick=()=>document.dispatchEvent(new CustomEvent('a3:open-input-layer',{detail:'spatial'}));

  root.insertBefore($('.lt-spatial'),$('.lt-prerequisites'));
  const gridButton=document.createElement('button');gridButton.type='button';gridButton.dataset.ltGrid='';gridButton.textContent=`پیکسل: ${fmt(data.plan_maps.cell_width_m??data.plan_maps.side_m,0)} × ${fmt(data.plan_maps.cell_height_m??data.plan_maps.side_m,0)} متر`;
  gridButton.onclick=()=>document.dispatchEvent(new CustomEvent('a3:open-input-layer',{detail:'grid'}));$('.lt-spatial').append(gridButton);
  const rateDetails=document.createElement('details');rateDetails.className='lt-diagnostics';rateDetails.dataset.ltRates='';rateDetails.innerHTML='<summary>دوره‌ها و نرخ‌های به‌کاررفته</summary><div data-lt-rates-body></div>';$('[data-lt-spatial-status]').after(rateDetails);
  for(const [key,label,mode,first]of [['quantity','دورهٔ نرخ تغییر تراز','current','روند فعلی «آینده و اقدام»'],['quality','مبنای تغییر شوری','manual','نرخ دستی سناریو'],['subsidence','دورهٔ نرخ نشست','source','نرخ / میانگین دورهٔ فایل'],['climate','مبنای تغییر بارش و دما','manual','تغییر دستی بارش و دما']]){
    const host=document.createElement('div');host.className='lt-rate-window';host.innerHTML=rateWindow(key,label,mode,first);(key==='climate'?$('[data-lt-climate]'):$(`[data-lt-body=${key}]`)).prepend(host);
  }
  // One editor at a time; every criterion's independent enable switch stays visible.
  const criterionKeys=['quantity','quality','subsidence','climate'],criterionNames={quantity:'کمیت',quality:'شوری',subsidence:'نشست',climate:'اقلیم'};
  let activeCriterion='quantity';
  const criterionNav=document.createElement('div');criterionNav.className='lt-criterion-nav';criterionNav.setAttribute('role','group');criterionNav.setAttribute('aria-label','محدودیت‌های سناریو');
  $('.lt-criteria').before(criterionNav);
  for(const key of criterionKeys){
    const toggle=$(`[data-lt=${key}_on]`),label=toggle.closest('label'),panel=label.closest('section');
    const tile=document.createElement('div');tile.className='lt-criterion-choice';tile.dataset.ltCriterion=key;
    label.childNodes.forEach(n=>{if(n.nodeType===3)n.textContent=criterionNames[key];});
    const button=document.createElement('button');button.type='button';button.dataset.ltCriterionOpen=key;button.textContent='تنظیمات';button.setAttribute('aria-label','تنظیمات '+criterionNames[key]);button.setAttribute('aria-controls','lt-criterion-'+key);
    tile.append(label,button);criterionNav.append(tile);panel.dataset.ltPanel=key;panel.id='lt-criterion-'+key;panel.setAttribute('aria-label','تنظیمات '+criterionNames[key]);
    const enable=document.createElement('button');enable.type='button';enable.className='lt-enable-criterion';enable.dataset.ltEnable=key;enable.textContent='افزودن '+criterionNames[key]+' به سناریو';panel.append(enable);
    if(key==='climate')$('.lt-criteria').append(panel);
    button.onclick=()=>activateCriterion(key);
    enable.onclick=()=>{toggle.checked=true;toggle.dispatchEvent(new Event('change',{bubbles:true}));};
    button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const i=criterionKeys.indexOf(key),next=event.key==='Home'?criterionKeys[0]:event.key==='End'?criterionKeys.at(-1):criterionKeys[(i+(event.key==='ArrowLeft'?1:criterionKeys.length-1))%criterionKeys.length];activateCriterion(next,true);};
  }
  function activateCriterion(key,focus=false){
    if(!criterionKeys.includes(key))return;activeCriterion=key;
    for(const name of criterionKeys){const selected=name===key;$(`[data-lt-panel=${name}]`).hidden=!selected;$(`[data-lt-criterion=${name}]`).dataset.active=String(selected);$(`[data-lt-criterion-open=${name}]`).setAttribute('aria-expanded',String(selected));}
    if(focus)$(`[data-lt-criterion-open=${key}]`).focus();
  }
  activateCriterion('quantity');
  all('[data-lt-prereq-guide]').forEach(n=>n.setAttribute('data-help-copy',''));
  const editResult=document.createElement('button');editResult.type='button';editResult.dataset.ltEdit='';editResult.textContent='ویرایش سناریو';$('.lt-result-bar').prepend(editResult);
  editResult.onclick=()=>{$('.lt-editor').open=true;$('.lt-editor').scrollIntoView({block:'start'});$(`[data-lt-criterion-open=${activeCriterion}]`).focus({preventScroll:true});};
  const storageKey='aquifer-lifetime:v1:'+JSON.stringify([data.aquifer,data.plan_maps.extent]);
  let management=null,quality=null,disposed=false,sequence=0,result=null,withoutClimate=null,mapCleanup=null,secondCleanup=null,sceneCleanup=null,climateText='',zonesText='',saved=[],records=new Map(),selectedId='',displayedId='',appliedEnvelope=null,dirty=false;
  let referenceSequence=0,referenceTimer,referenceKey='',referenceGeneration=0,presetSequence=0,presets=[],appliedPreset=null,running=false,climateFileSequence=0,climateReading=false;
  let quantityKind=$('[data-lt=quantity_type]').value;const quantityValues=new Map([[quantityKind,$('[data-lt=quantity_limit]').value]]);
  try{saved=JSON.parse(localStorage.getItem(storageKey)||'[]');if(!Array.isArray(saved))saved=[];}catch{}
  const defaults=Object.fromEntries(all('[data-lt]').map(n=>[n.dataset.lt,n.type==='checkbox'?n.checked:n.value]));
  function config(){return {...Object.fromEntries(all('[data-lt]').map(n=>[n.dataset.lt,n.type==='checkbox'?n.checked:n.value])),...(appliedPreset?{preset_id:appliedPreset.id,preset_assumption:appliedPreset.assumption}:{})};}
  function apply(c){all('[data-lt]').forEach(n=>{if(c[n.dataset.lt]!==undefined){if(n.type==='checkbox')n.checked=Boolean(c[n.dataset.lt]);else n.value=c[n.dataset.lt];}});sharedControls();quantityKind=$('[data-lt=quantity_type]').value;quantityValues.set(quantityKind,$('[data-lt=quantity_limit]').value);toggles();activateCriterion(criterionKeys.find(key=>$(`[data-lt=${key}_on]`).checked)||'quantity');}
  function describePreset(){
    const p=presets.find(p=>p.id===$('[data-lt-preset]').value);
    $('[data-lt-preset-apply]').disabled=!p?.ready;
    $('[data-lt-preset-state]').textContent=p?(p.ready?'قابل ویرایش پس از انتخاب':'نیازمند: '+p.missing.join('، ')):'';
    $('[data-lt-preset-help]').textContent=p?p.assumption+'\n'+p.common_note:'قالب‌ها فرض‌های قابل‌ویرایش برای مقایسه‌اند. هر قالب دادهٔ لازم خود را مشخص می‌کند؛ لایه‌ها از داخل برنامه بارگذاری نمی‌شوند.';
  }
  async function refreshPresets(){
    const token=++presetSequence;
    if(!management){$('[data-lt-preset-apply]').disabled=true;return;}
    try{const choices=await request('lifetime_presets',{quality});if(disposed||token!==presetSequence)return;
      const select=$('[data-lt-preset]'),chosen=select.value;presets=choices;select.replaceChildren(new Option('انتخاب قالب…',''));
      for(const group of [...new Set(presets.map(p=>p.group))]){const node=document.createElement('optgroup');node.label=group;for(const p of presets.filter(p=>p.group===group))node.append(new Option(p.name+(p.ready?'':' · داده لازم است'),p.id));select.append(node);}
      select.value=chosen;describePreset();
    }catch(e){if(!disposed)$('[data-lt-preset-state]').textContent=errorText(e);}
  }
  $('[data-lt-preset]').onchange=describePreset;
  $('[data-lt-preset-apply]').onclick=()=>{const p=presets.find(p=>p.id===$('[data-lt-preset]').value);if(!p?.ready)return;
    const use=$('[data-lt=use]').value,horizon=$('[data-lt=horizon]').value,spatial_coverage=$('[data-lt=spatial_coverage]').value,spatial_method=$('[data-lt=spatial_method]').value,spline_smoothing=$('[data-lt=spline_smoothing]').value;selectedId='';appliedPreset=p;quantityValues.clear();apply({...defaults,...p.scenario,use,horizon,spatial_coverage,spatial_method,spline_smoothing});zonesText='';$('[data-lt-zones]').value='';$('[data-lt-zone-name]').textContent='کل آبخوان';$('.lt-editor').open=true;$('.lt-editor>summary').textContent='ویرایش قالب · '+p.name;lists();invalidate('قالب آماده شد؛ فرض‌ها را بررسی و محاسبه کنید.');};
  function quantityControls(){
    const kind=$('[data-lt=quantity_type]').value,field=$('[data-lt=quantity_limit]'),percent=kind==='storage_loss_pct';
    $('[data-lt-quantity-label]').textContent=percent?'کاهش ذخیره (%)':kind==='saturated'?'حداقل ضخامت اشباع (متر)':kind==='drawdown'?'افت مجاز (متر)':'حداقل تراز (متر MSL)';
    if(kind==='head')field.removeAttribute('min');else field.min=percent?'0.1':'0';
    if(percent)field.max='100';else field.removeAttribute('max');
    $('[data-lt-quantity-guide]').hidden=!percent||!$('[data-lt=quantity_on]').checked;
    all('[data-lt-storage-choice]').forEach(b=>b.setAttribute('aria-pressed',String(Number(field.value)===Number(b.dataset.ltStorageChoice))));
  }
  function paintReference(r){
    const host=$('[data-lt-quantity-preview]');host.replaceChildren();
    $('[data-lt-quantity-meta]').textContent=JSON.stringify(r);
    if(!Number.isFinite(r.initial_storage_mcm)){host.textContent='کف یا Sy کافی برای محاسبهٔ ذخیره وجود ندارد.';return;}
    for(const text of [`حفظ ${fmt(r.remaining_pct)}٪ ذخیرهٔ هر پیکسل`,`حجم مرجع: ${fmt(r.initial_storage_mcm)} میلیون m³`,`کاهش معادل: ${fmt(r.equivalent_loss_mcm)} میلیون m³`,...(Number.isFinite(r.equivalent_drawdown_median_m)?[`میانهٔ افت معادل: ${fmt(r.equivalent_drawdown_median_m)} متر`]:[]),`پوشش کف و Sy: ${fmt(r.storage_supported_area_pct)}٪`]){const span=document.createElement('span');span.textContent=text;host.append(span);}
  }
  function queueReference(){
    quantityControls();
    if($('[data-lt-quantity-guide]').hidden||!management){clearTimeout(referenceTimer);referenceSequence++;referenceKey='';$('[data-lt-quantity-meta]').textContent='';$('[data-lt-quantity-preview]').textContent='در انتظار آماده‌شدن مدل…';return;}
    const scenario=config(),key=JSON.stringify([referenceGeneration,...['quantity_type','quantity_limit','floor_offset_m','sy_factor'].map(k=>scenario[k]),zonesText]);
    if(referenceKey===key)return;referenceKey=key;
    clearTimeout(referenceTimer);const token=++referenceSequence;
    $('[data-lt-quantity-preview]').textContent='در حال محاسبهٔ معادل…';$('[data-lt-quantity-meta]').textContent='';
    referenceTimer=setTimeout(async()=>{try{const answer=await request('lifetime_quantity_reference',{scenario,zones_text:zonesText});if(!disposed&&token===referenceSequence)paintReference(answer);}catch(e){if(!disposed&&token===referenceSequence){referenceKey='';$('[data-lt-quantity-preview]').textContent=errorText(e);}}},200);
  }
  function prerequisites(){
    const sub=management?.report?.subsidence;
    return {quality:!!(quality?.report?.sites&&quality.plan_maps?.cells.some(c=>c.quality_supported&&Number.isFinite(c.quality_ec))),subsidence:!!(sub?.input_records&&!sub.input_error&&sub.component==='vertical'&&management.plan_maps.cells.some(c=>Number.isFinite(c.management_subsidence)))};
  }
  function readiness(){
    const ready=prerequisites();
    for(const key of ['quality','subsidence']){
      const card=$(`[data-lt-prereq=${key}]`),toggle=$(`[data-lt=${key}_on]`),guide=$(`[data-lt-prereq-guide=${key}]`);
      card.dataset.ready=String(ready[key]);$(`[data-lt-prereq-state=${key}]`).textContent=ready[key]?'آماده برای سناریو':key==='subsidence'&&management?.report?.subsidence?.component==='los'?'نیاز به مؤلفهٔ قائم':'نیاز به اجرا';
      guide.hidden=ready[key];guide.textContent=key==='quality'?'در «کیفیت آب»، فایل و آستانه‌ها را بررسی و «محاسبه کیفیت» را اجرا کنید.':'در «آینده و اقدام»، دوره، واحد و مؤلفهٔ قائم لایه را تأیید و «محاسبه و به‌روزرسانی» را اجرا کنید.';
      toggle.disabled=running||(!ready[key]&&!toggle.checked);
      $(`[data-lt-enable=${key}]`).disabled=toggle.disabled;
      all(`[data-lt-body=${key}] input,[data-lt-body=${key}] select`).forEach(n=>n.disabled=running||!ready[key]);
    }
    for(const key of ['quality_mode','min_usable_pct'])$(`[data-lt=${key}]`).disabled=running||!ready.quality;
    const blocked=['quality','subsidence'].filter(k=>$(`[data-lt=${k}_on]`).checked&&!ready[k]);
    const kind=$('[data-lt=quantity_type]').value,cells=data.plan_maps.cells;
    const missingQuantity=$('[data-lt=quantity_on]').checked&&((kind==='storage_loss_pct'&&!cells.some(c=>Number.isFinite(c.bedrock_msl)&&Number.isFinite(c.sy)))||(kind==='saturated'&&!cells.some(c=>Number.isFinite(c.bedrock_msl))));
    $('[data-lt-quantity-missing]').hidden=!missingQuantity;
    $('[data-lt-quantity-missing] span').textContent=kind==='storage_loss_pct'?'برای معیار درصد کاهش ذخیره، سنگ‌بستر و Sy را وارد کنید.':'برای معیار ضخامت اشباع، سنگ‌بستر را وارد کنید.';
    if(missingQuantity)blocked.push('quantity');
    if($('[data-lt=subsidence_on]').checked&&$('[data-lt=subsidence_window]').value!=='source'&&!management?.report?.subsidence?.annual_rates&&!blocked.includes('subsidence'))blocked.push('subsidence');
    $('[data-lt-run]').disabled=running||climateReading||!management||blocked.length>0;
    rateControls();
    return blocked;
  }
  function rateControls(){
    const annual=!!management?.report?.subsidence?.annual_rates,ready=prerequisites();
    for(const key of ['quantity','quality','subsidence','climate']){
      const mode=$(`[data-lt=${key}_window]`).value;$(`[data-lt-window-custom=${key}]`).hidden=mode!=='custom';
      const note=$(`[data-lt-window-note=${key}]`);note.textContent=key==='subsidence'&&!annual?'این منبع فقط نرخ یا میانگین دورهٔ فایل را دارد؛ بازه‌های دیگر به فایل نرخ سالانه نیاز دارند.':key==='quality'&&mode!=='manual'?'نرخ از سابقهٔ همان موقعیت‌های نمونه‌برداری محاسبه می‌شود؛ حداقل سه سال مشاهده لازم است.':key==='climate'&&mode!=='manual'?'روند دورهٔ انتخابی برای بارش و دما؛ برازش اثر اقلیم همچنان به حداقل ۱۲ سال هم‌دوره نیاز دارد.':'';note.hidden=!note.textContent;
    }
    for(const option of $('[data-lt=subsidence_window]').options)option.disabled=option.value!=='source'&&!annual;
    $('[data-lt=ec_growth_pct]').disabled=running||!ready.quality||$('[data-lt=quality_window]').value!=='manual';
    $('[data-lt=manual_drop_m_year]').disabled=running||$('[data-lt=quantity_window]').value!=='current';
    for(const key of ['climate_precip_pct','climate_temp_c','climate_years'])$(`[data-lt=${key}]`).disabled=running||$('[data-lt=climate_window]').value!=='manual';
    sharedControls();$('[data-lt-spline]').hidden=true;
  }
  function prepareLayer(key){
    document.getElementById(key==='quality'?'a3Nav-quality':'a3Nav-management').click();
    if(key==='subsidence')document.querySelector('[data-m-open-source]')?.click();
    else{const file=document.querySelector('[data-q-file]');if(file){for(let p=file.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;file.focus();file.scrollIntoView({block:'center'});}}
  }
  all('[data-lt-prepare]').forEach(b=>b.onclick=()=>prepareLayer(b.dataset.ltPrepare));
  $('[data-lt-quantity-inputs]').onclick=()=>document.dispatchEvent(new CustomEvent('a3:open-input-layer',{detail:data.plan_maps.cells.some(c=>Number.isFinite(c.bedrock_msl))?'sy':'bedrock'}));
  function toggles(){for(const key of criterionKeys){const enabled=$(`[data-lt=${key}_on]`).checked;(key==='climate'?$('[data-lt-climate]'):$(`[data-lt-body=${key}]`)).hidden=!enabled;$(`[data-lt-enable=${key}]`).hidden=enabled;$(`[data-lt-criterion=${key}]`).dataset.enabled=String(enabled);$(`[data-lt-enable=${key}]`).disabled=$(`[data-lt=${key}_on]`).disabled;}$('[data-lt-sensitivity]').hidden=!$('[data-lt=sensitivity_on]').checked;quantityControls();readiness();}
  function lists(){
    const picked=$('[data-lt-compare]').value;
    $('[data-lt-delete]').hidden=!selectedId;
    $('[data-lt-saved]').replaceChildren(new Option('سناریوهای من',''));
    $('[data-lt-compare]').replaceChildren(new Option('انتخاب سناریوی محاسبه‌شده',''));
    saved.forEach(s=>$('[data-lt-saved]').add(new Option(s.scenario.name,s.id)));
    records.forEach((r,id)=>{if(id!==displayedId)$('[data-lt-compare]').add(new Option(r.report.scenario.name,id));});
    $('[data-lt-saved]').value=selectedId;$('[data-lt-compare]').value=picked;
  }
  function persist(){try{localStorage.setItem(storageKey,JSON.stringify(saved));return true;}catch{$('[data-lt-status]').textContent='ذخیره در مرورگر ممکن نشد؛ فایل سناریو را دریافت کنید.';return false;}}
  function invalidate(message='تنظیمات تغییر کرده‌اند؛ محاسبه کنید.'){
    sequence++;dirty=true;$('[data-lt-stale]').hidden=!result;const blocked=readiness();$('[data-lt-status]').textContent=blocked.length?'نیاز به آماده‌سازی: '+blocked.map(k=>k==='quantity'?'داده‌های معیار کمّی':k==='quality'?'کیفیت آب':'فرونشست در «آینده و اقدام»').join(' و '):message;document.dispatchEvent(new CustomEvent('a3:lifetime-state',{detail:{state:result?'stale':'empty'}}));queueReference();
  }
  function managed(event){management=event.detail;referenceGeneration++;refreshPresets();invalidate(management?'روند آماده است؛ آستانه و سناریو را محاسبه کنید.':'روند در حال به‌روزرسانی است.');}
  function qualified(event){quality=event.detail;refreshPresets();invalidate('کیفیت تغییر کرد؛ سناریو را دوباره محاسبه کنید.');}
  document.addEventListener('a3:subsidence-result',managed);document.addEventListener('a3:quality-result',qualified);
  all('[data-lt]').forEach(n=>n.addEventListener(n.tagName==='SELECT'||n.type==='checkbox'?'change':'input',()=>{const key=n.dataset.lt.replace(/_on$/,'');if(n.type==='checkbox'&&n.checked&&criterionKeys.includes(key))activateCriterion(key);if(n.dataset.lt==='quantity_window'&&n.value!=='current')$('[data-lt=manual_drop_m_year]').value='';if(n.dataset.lt==='quantity_type'){quantityValues.set(quantityKind,$('[data-lt=quantity_limit]').value);quantityKind=n.value;$('[data-lt=quantity_limit]').value=quantityValues.get(quantityKind)??(quantityKind==='storage_loss_pct'?'25':'');}toggles();invalidate();}));
  all('[data-lt-storage-choice]').forEach(b=>b.onclick=()=>{const field=$('[data-lt=quantity_limit]');field.value=b.dataset.ltStorageChoice;field.dispatchEvent(new Event('input',{bubbles:true}));});
  $('[data-lt-quality]').onclick=()=>prepareLayer('quality');$('[data-lt-source]').onclick=()=>prepareLayer('subsidence');
  async function readClimate(file){
    const token=++climateFileSequence;climateReading=!!file;climateText='';data.input_files.climate=file?.name||null;
    document.dispatchEvent(new CustomEvent('a3:user-layer-file',{detail:{kind:'climate',file:file||null,aquifer:data.aquifer}}));
    $('[data-lt-climate-name]').textContent=file?'در حال خواندن…':'وارد نشده';invalidate();
    try{const text=file?await file.text():'';if(disposed||token!==climateFileSequence)return;climateText=text;climateReading=false;$('[data-lt-climate-name]').textContent=file?.name||'وارد نشده';invalidate();}
    catch(error){if(!disposed&&token===climateFileSequence){climateReading=false;invalidate('خواندن فایل اقلیم ممکن نشد: '+errorText(error));}}
  }
  $('[data-lt-climate-file]').onchange=()=>readClimate($('[data-lt-climate-file]').files[0]);
  $('[data-lt-zones]').onchange=async()=>{const file=$('[data-lt-zones]').files[0];if(!file)return;zonesText=await file.text();if(disposed)return;$('[data-lt-zone-name]').textContent=file.name;invalidate();};
  $('[data-lt-zones-clear]').onclick=()=>{zonesText='';$('[data-lt-zones]').value='';$('[data-lt-zone-name]').textContent='کل آبخوان';invalidate();};
  $('[data-lt-climate-template]').onclick=()=>download(new Blob(['water_year,precip_mm,temp_c\r\n'],{type:'text/csv;charset=utf-8'}),'aquifer-climate-template.csv');
  $('[data-lt-zone-template]').onclick=()=>download(new Blob([JSON.stringify({type:'FeatureCollection',features:[],allowed_properties:['drop_factor','ec_growth_pct','sub_factor','sy_factor','floor_offset_m'],crs_note:'WGS84 polygons; no overlap'},null,2)],{type:'application/geo+json'}),'scenario-zones-template.geojson');
  $('[data-lt-new]').onclick=()=>{appliedPreset=null;quantityValues.clear();$('.lt-editor').open=true;$('.lt-editor>summary').textContent='تعریف سناریو';selectedId='';apply({...defaults,name:'سناریوی جدید'});zonesText='';$('[data-lt-zones]').value='';$('[data-lt-zone-name]').textContent='کل آبخوان';lists();invalidate();};
  function load(s){appliedPreset=s.scenario?.preset_id?{id:s.scenario.preset_id,assumption:s.scenario.preset_assumption||''}:null;$('[data-lt-zones]').value='';$('.lt-editor').open=true;$('.lt-editor>summary').textContent='تعریف سناریو';selectedId=s.id||'';apply({...defaults,...s.scenario});zonesText=s.zones_text||'';if(!climateText)$('[data-lt-climate-name]').textContent='وارد نشده';$('[data-lt-zone-name]').textContent=s.zones_file||'کل آبخوان';lists();invalidate();}
  $('[data-lt-saved]').onchange=()=>{const s=saved.find(s=>s.id===$('[data-lt-saved]').value);if(s)load(s);};
  $('[data-lt-delete]').onclick=()=>{if(!selectedId)return;saved=saved.filter(s=>s.id!==selectedId);records.delete(selectedId);selectedId='';persist();lists();invalidate('سناریوی ذخیره‌شده حذف شد.');};
  $('[data-lt-import]').onclick=()=>$('[data-lt-import-file]').click();
  $('[data-lt-import-file]').onchange=async()=>{try{const file=$('[data-lt-import-file]').files[0];if(!file)return;const s=JSON.parse(await file.text());if(s.schema!=='aquifer-lifetime-v1'||!s.scenario||!s.aquifer)throw Error('فایل سناریو معتبر نیست.');if(JSON.stringify(s.aquifer)!==JSON.stringify(data.aquifer))throw Error('سناریو متعلق به آبخوان دیگری است.');load({...s,id:''});}catch(e){$('[data-lt-status]').textContent=errorText(e);}};
  const draftEnvelope=()=>({schema:'aquifer-lifetime-v1',aquifer:data.aquifer,reference_date:data.dates.after,scenario:config(),climate_text:climateText,zones_text:zonesText,climate_file:$('[data-lt-climate-name]').textContent,zones_file:$('[data-lt-zone-name]').textContent});
  function mapData(r){return {...data,plan_maps:r.plan_maps,lifetime_report:r.report,lifetime_caption:`${r.report.scenario.name} · افق ${fmt(r.report.scenario.horizon,0)} سال`,hide_cities:false};}
  function definitions(r){const bands=r.report.bands;return {
    life_band:{label:'سال‌های باقی‌مانده',unit:'سال تا نخستین محدودیت',palette:colors.slice(0,3),categories:[{label:'اکنون',short:'۰',color:colors[0]},...bands.map((b,i)=>({label:`${i?fmt(bands[i-1],0)+' تا ':'تا '}${fmt(b,0)} سال`,short:fmt(b,0),color:bandColor(i,bands.length)})),{label:`بیش از ${fmt(r.report.scenario.horizon,0)} سال`,short:'بیش از افق',color:'#6e9d92'},{label:'نامشخص',short:'؟',color:'#d8dee2'}]},
    life_cause:{label:'عامل محدودکننده',unit:'نخستین محدودیت فعال',palette:causeColors.slice(0,3),categories:causeLabels.map((label,i)=>({label,short:label,color:causeColors[i]}))},
    life_support:{label:'پوشش مکانی روند',unit:'منشأ روند تراز',palette:['#5d99a2','#dcab68','#d8dee2'],categories:[{label:'داخل پوشش شبکه',short:'شبکه',color:'#5d99a2'},{label:'برون‌یابی مکانی',short:'برآورد',color:'#dcab68'},{label:'بدون روند',short:'؟',color:'#d8dee2'},{label:'نرخ دستی سناریو',short:'دستی',color:'#a388b2'}]},
    life_delta:{label:'تفاوت عمر دو سناریو',unit:'سال؛ مثبت = عمر بیشتر در سناریوی جاری',palette:['#a6474b','#f4f3ed','#428d83']}
  };}
  function paint(){
    if(!result)return;mapCleanup?.();secondCleanup?.();sceneCleanup?.();mapCleanup=secondCleanup=sceneCleanup=null;
    const choose=$('[data-lt-view]');choose.querySelector('[value=compare]').disabled=records.size<2;choose.querySelector('[value=climate]').disabled=!withoutClimate;if(choose.selectedOptions[0].disabled)choose.value='map';
    const view=choose.value;
    $('.lt-map').hidden=view==='3d';$('.lt-3d').hidden=view!=='3d';$('.lt-secondary-map').hidden=true;$('.lt-comparison-controls').hidden=view!=='compare';
    if(view==='3d'){
      if(!data.pixel_water){$('[data-lt-status]').textContent='نمای سه‌بعدی عمر به Sy و کف معتبر نیاز دارد.';return;}
      $('[data-lt-camera]').value='oblique';$('[data-lt-pan]').setAttribute('aria-pressed','false');
      const defs=definitions(result);$('.lt-legend').replaceChildren();defs.life_band.categories.forEach(c=>{const item=document.createElement('span'),dot=document.createElement('i');dot.style.background=c.color;item.append(dot,document.createTextNode(c.label));$('.lt-legend').append(item);});
      sceneCleanup=mountLifetimeScene($('.lt-3d canvas'),data,result.plan_maps.cells,defs.life_band.categories.map(c=>c.color),zoom=>$('[data-lt-zoom-label]').textContent=fmt(zoom*100,0)+'٪');return;
    }
    let plotted=result;
    if(view==='compare'){
      const other=records.get($('[data-lt-compare]').value);
      if(other){
        const index=new Map(other.plan_maps.cells.map(c=>[[c.lon,c.lat].join(','),c]));
        plotted={...result,plan_maps:{...result.plan_maps,cells:result.plan_maps.cells.map(c=>{const b=index.get([c.lon,c.lat].join(','));return {...c,life_delta:c.life_years!==null&&b?.life_years!==null&&b?c.life_years-b.life_years:null};})}};
        $('.lt-secondary-map').hidden=false;secondCleanup=mountMap($('.lt-secondary-map'),mapData(other),['life_band'],'lt-compare',definitions(other));
      }
    }
    mapCleanup=mountMap($('.lt-map'),mapData(plotted),view==='support'?['life_support']:view==='cause'?['life_cause']:view==='compare'?['life_delta','life_band']:['life_band','life_cause'],'lt-main',definitions(plotted));
    if(view==='climate'&&withoutClimate){$('.lt-secondary-map').hidden=false;secondCleanup=mountMap($('.lt-secondary-map'),mapData(withoutClimate),['life_band'],'lt-no-climate',definitions(withoutClimate));}
  }
  function charts(){const rows=$('[data-lt-rows]');rows.replaceChildren();const curves=result.report.curves,displayYears=result.report.display_years||curves.filter((_,i)=>i%Math.max(1,Math.ceil(curves.length/12))===0||i===curves.length-1).map(r=>r.year);for(const r of curves.filter(r=>displayYears.includes(r.year))){const tr=document.createElement('tr');tr.dataset.ltDisplayYear=r.year;for(const v of [fmt(r.year,0),fmt(r.critical_area_pct)+'٪',fmt(r.unknown_area_pct)+'٪',Number.isFinite(r.remaining_mcm)?fmt(r.remaining_mcm)+' میلیون m³':'نامشخص']){const td=document.createElement('td');td.textContent=v;tr.append(td);}rows.append(tr);}
    const host=$('[data-lt-charts]');host.replaceChildren();const ns='http://www.w3.org/2000/svg';
    for(const [key,label,unit,color] of [['critical_area_pct','مساحت بحرانی','درصد','#ad4d53'],['remaining_mcm','ذخیرهٔ بخش قابل محاسبه','میلیون مترمکعب','#176b7b']]){
      const figure=document.createElement('figure'),heading=document.createElement('figcaption'),title=document.createElement('strong'),units=document.createElement('span');title.textContent=label;units.textContent=unit;heading.append(title,units);figure.append(heading);
      if(key==='remaining_mcm'){const help=document.createElement('p');help.dataset.helpCopy='';help.dataset.ltCurveHelp='';const ref=result.report.volume_curve_reference;help.textContent=`منحنی از ابتدا تا انتها روی یک محدودهٔ ثابت دارای کف، Sy و مسیر معتبر تراز محاسبه می‌شود. پوشش: ${fmt(ref?.supported_area_pct)}٪ مساحت. حجم آغاز منحنی: ${fmt(ref?.projectable_initial_storage_mcm)} میلیون مترمکعب؛ برآورد فیزیکیِ آغاز با ورودی‌های سناریو، بدون الزام روند: ${fmt(ref?.physical_initial_storage_mcm)} میلیون مترمکعب. حذف پوشش مکانی به افت آب تبدیل نشده است.`;figure.append(help);}
      if(!curves.some(r=>Number.isFinite(r[key]))){const empty=document.createElement('p');empty.className='lt-curve-empty';empty.textContent='دادهٔ کافی برای محاسبهٔ این منحنی وجود ندارد.';figure.append(empty);host.append(figure);continue;}
      const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 640 260');svg.setAttribute('direction','ltr');svg.setAttribute('role','img');svg.setAttribute('aria-label',label+' ('+unit+')');
      const node=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
      const maximum=Math.max(1,...curves.map(r=>r[key]).filter(Number.isFinite)),x=v=>80+v/result.report.scenario.horizon*535,y=v=>205-v/maximum*175;
      for(let i=0;i<=4;i++){const value=maximum*i/4;svg.append(node('line',{x1:80,x2:615,y1:y(value),y2:y(value),stroke:'#e0e8ec'}),node('text',{x:70,y:y(value)+4,'text-anchor':'end','font-size':11},fmt(value)));}
      for(const year of displayYears.filter(t=>t===0||t===result.report.scenario.horizon||result.report.scenario.horizon-t>=result.report.scenario.horizon*.07))svg.append(node('text',{x:x(year),y:226,'text-anchor':'middle','font-size':11,'data-lt-axis-year':year},fmt(year,0)));
      svg.append(node('path',{d:'M80 30V205H615',fill:'none',stroke:'#9bb1bd'}));let connected=false;svg.append(node('path',{d:curves.map(r=>{if(!Number.isFinite(r[key])){connected=false;return '';}const point=`${connected?'L':'M'}${x(r.year)},${y(r[key])}`;connected=true;return point;}).join(' '),fill:'none',stroke:color,'stroke-width':3}));
      svg.append(node('text',{x:347,y:251,'text-anchor':'middle','font-size':11},'افق آینده (سال)'));const scroll=document.createElement('div');scroll.className='lt-curve-plot';scroll.append(svg);figure.append(scroll);host.append(figure);
    }
  }
  async function run(event){event?.preventDefault();const token=++sequence;if(!management||climateReading||readiness().length)return;
    const scenario=config(),inputs={scenario,quality,climate_text:climateText,zones_text:zonesText,input_files:data.input_files};
    const frozen=all('input,select,button').map(n=>[n,n.disabled]);running=true;frozen.forEach(([n])=>n.disabled=true);$('[data-lt-status]').textContent='در حال محاسبهٔ سناریو…';document.dispatchEvent(new CustomEvent('a3:lifetime-state',{detail:{state:'running'}}));
    try{
      const answer=await request('lifetime',inputs);if(disposed||token!==sequence)return;
      let counterfactual=null;if(scenario.climate_on)counterfactual=await request('lifetime',{...inputs,scenario:{...scenario,climate_on:false,sensitivity_on:false,name:scenario.name+' · بدون اقلیم'}});
      if(disposed||token!==sequence)return;result=answer;withoutClimate=counterfactual;dirty=false;
      selectedId=selectedId||crypto.randomUUID();displayedId=selectedId;appliedEnvelope={...draftEnvelope(),scenario:answer.report.scenario,climate_text:inputs.climate_text,zones_text:inputs.zones_text};records.set(selectedId,result);
      const entry={...appliedEnvelope,id:selectedId};saved=saved.filter(s=>s.id!==selectedId);saved.push(entry);saved=saved.slice(-12);const stored=persist();lists();
      $('.lt-cards').replaceChildren();const r=result.report;
      for(const [label,value]of [[`زمان رسیدن ${fmt(r.scenario.area_target_pct,0)}٪ مساحت به محدودیت`,r.area_target_years!==null?(r.area_target_status==='upper_bound'?'حداکثر ':'')+fmt(r.area_target_years)+' سال':r.area_target_status==='unknown'?'نامشخص':'بیش از افق'],['مساحت بحرانی در پایان افق',fmt(r.critical_at_horizon_pct)+'٪'],['مساحت با عمر نامشخص',fmt(r.unknown_area_pct)+'٪']]){const card=document.createElement('article'),span=document.createElement('span'),strong=document.createElement('strong');span.textContent=label;strong.textContent=value;card.append(span,strong);$('.lt-cards').append(card);}
      const diagnostics=$('[data-lt-diagnostics]'),diag=r.unknown_diagnostics;diagnostics.hidden=!diag?.unknown_cells;
      const body=$('[data-lt-diagnostics-body]');body.replaceChildren();
      if(diag?.unknown_cells){const table=document.createElement('table');for(const [reason,area]of Object.entries(diag.reason_areas_pct)){const tr=document.createElement('tr'),label=document.createElement('td'),value=document.createElement('td');label.textContent=window.HydroHelp.reasonLabel(reason);value.textContent=fmt(area)+'٪ از مساحت';tr.append(label,value);table.append(tr);}body.append(table);const p=document.createElement('p');p.dataset.helpCopy='';p.textContent=`پیزومترهای دارای روند معتبر: ${fmt(diag.eligible_wells,0)} از ${fmt(diag.well_count,0)}. شعاع پشتیبانی ${fmt(diag.support_radius_km)} کیلومتر. علت‌ها ممکن است همپوشان باشند. ${r.scenario.spatial_coverage==='aquifer'?'برون‌یابی فقط برای روند انجام شده؛ علت‌های دیگر همچنان نامشخص می‌مانند.':'برای تعمیم روند به حاشیه‌ها، پوشش «کل محدوده با برآورد مکانی» را انتخاب کنید.'}`;body.append(p);}
      const coverage=r.spatial_coverage;$('[data-lt-spatial-status]').textContent=coverage?`روند: ${fmt(coverage.area_pct.within_support)}٪ داخل پوشش شبکه · ${fmt(coverage.area_pct.extrapolated)}٪ برون‌یابی مکانی · ${fmt(coverage.area_pct.unavailable)}٪ بدون روند`+(coverage.area_pct.manual?` · ${fmt(coverage.area_pct.manual)}٪ نرخ دستی`:''):'';
      const rates=$('[data-lt-rates-body]');rates.replaceChildren();const table=document.createElement('table');
      for(const [key,label]of [['quantity','کمیت'],['quality','شوری'],['subsidence','نشست'],['climate','اقلیم']]){
        const audit=r.rate_audit?.[key];if(!audit)continue;
        const row=document.createElement('tr'),name=document.createElement('td'),value=document.createElement('td');name.textContent=label;
        const period=audit.start_water_year!==undefined?'سال آبی '+audit.start_water_year+' تا '+audit.end_water_year:audit.source_years?'دورهٔ منبع '+audit.source_years.join(' تا '):audit.periods?.length?'سال آبی '+audit.periods[0].join(' تا '):'';
        value.textContent=audit.reason||({current:'روند فعلی',manual:'مقدار دستی',source:'دورهٔ فایل',all:'کل دوره',off:'خاموش','4':'۴ سال اخیر','10':'۱۰ سال اخیر',custom:'دورهٔ دلخواه'}[audit.mode]||'')+(period?' · '+period:'')+(Number.isFinite(audit.eligible_wells)?' · '+fmt(audit.eligible_wells,0)+' پیزومتر':'')+(Number.isFinite(audit.eligible_sites)?' · '+fmt(audit.eligible_sites,0)+' موقعیت دارای سابقه':'')+(Number.isFinite(audit.growth_pct_year)?' · '+fmt(audit.growth_pct_year)+'٪ در سال':'');
        row.append(name,value);table.append(row);
      }rates.append(table);
      if(r.sensitivity){const note=document.createElement('small');note.dataset.helpCopy='';note.textContent=r.sensitivity.summary.map(v=>({central:'مرکزی',faster:'افت سریع‌تر',slower:'افت کندتر'}[v.variant])+': '+(v.area_target_years!==null?(v.area_target_status==='upper_bound'?'حداکثر ':'')+fmt(v.area_target_years)+' سال':v.area_target_status==='unknown'?'نامشخص':'بیش از افق')).join('\n')+'\nحساسیت به سه ترکیب؛ فاصلهٔ اطمینان نیست.';$('.lt-cards article').append(note);}
      $('[data-lt-result-name]').textContent=r.scenario.name+' · شهریور '+new Intl.NumberFormat('fa-IR',{useGrouping:false}).format(Number(r.reference_date.slice(0,4)));
      $('[data-lt-climate-status]').textContent=!r.scenario.climate_on?'اقلیم خاموش':r.climate.accepted?'اقلیم اعمال شد':'اقلیم قابل محاسبه نیست';
      $('[data-lt-result-note]').textContent='زمان تا نخستین محدودیت فعال؛ سناریویی و وابسته به آستانه‌ها. خاکستری: دادهٔ ناکافی. بیش از افق: تا پایان بازه عبور مشاهده نمی‌شود. در حضور مساحت نامشخص، زمان سهم بحرانی حد بالاست؛ عبور ممکن است زودتر رخ دهد. ارتفاع ستون سه‌بعدی ذخیرهٔ فعلی را نشان می‌دهد و رنگ آن زمان عبور است. روند از بخش قابل‌اندازه‌گیری شبکه است؛ سوگیری خشکی واقعی در دامنهٔ حساسیت پوشش داده نمی‌شود. EC به‌تنهایی سلامت شرب یا تناسب محصول را تأیید نمی‌کند.\n'+r.climate.reason+(r.climate.accepted?`\n${r.climate.outside_historical_range?'سناریوی اقلیم از دامنهٔ مشاهدات تاریخی فراتر می‌رود. ':''}خطای آزمون ${fmt(r.climate.mae_m_year,3)} متر/سال؛ بهبود ${fmt(r.climate.improvement_pct)}٪؛ ${fmt(r.climate.years,0)} سال داده.`:'');
      $('[data-lt-metadata]').textContent=JSON.stringify(r);$('[data-lt-results]').hidden=false;$('[data-lt-stale]').hidden=true;$('.lt-editor').open=false;$('.lt-editor>summary').textContent='ویرایش سناریو · '+r.scenario.name;charts();paint();if(stored)$('[data-lt-status]').textContent='سناریو محاسبه و ذخیره شد.';
      document.dispatchEvent(new CustomEvent('a3:lifetime-state',{detail:{state:'ready',result}}));
    }catch(e){if(!disposed&&token===sequence){$('[data-lt-status]').textContent=errorText(e);document.dispatchEvent(new CustomEvent('a3:lifetime-state',{detail:{state:result?'stale':'empty'}}));}}
    finally{if(!disposed){running=false;frozen.forEach(([n,disabled])=>n.disabled=disabled);readiness();}}
  }
  $('[data-lt-form]').onsubmit=run;$('[data-lt-view]').onchange=paint;$('[data-lt-compare]').onchange=paint;
  $('[data-lt-camera]').onchange=()=>sceneCleanup?.preset($('[data-lt-camera]').value);
  all('[data-lt-zoom]').forEach(b=>b.onclick=()=>sceneCleanup?.control(b.dataset.ltZoom));$('[data-lt-pan]').onclick=()=>{const b=$('[data-lt-pan]'),on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on);sceneCleanup?.pan(on);};
  all('[data-lt-export]').forEach(b=>b.onclick=async()=>{
    if(!result)return;const kind=b.dataset.ltExport,name=data.aquifer.name+'-'+result.report.scenario.name;
    try{b.disabled=true;
      if(kind==='scenario')download(new Blob([JSON.stringify(appliedEnvelope,null,2)],{type:'application/json'}),name+'-scenario.json');
      else if(kind==='json')download(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}),name+'-report.json');
      else if(kind==='csv'){const cols=['lon','lat','area_m2',...Object.keys(result.plan_maps.cells[0]).filter(k=>k.startsWith('life_'))];const rows=[['scenario_json',...cols],...result.plan_maps.cells.map(c=>[JSON.stringify(result.report.scenario),...cols.map(k=>typeof c[k]==='object'?JSON.stringify(c[k]):c[k]??'')])];download(new Blob(['\ufeff'+rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}),name+'.csv');}
      else{const encoded=await request('lifetime_tiff',{result,field:kind==='support'?'life_support':kind==='status'?'life_band':'life_years'}),bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));download(new Blob([bytes],{type:'image/tiff'}),name+'-'+kind+'.tif');}
    }catch(e){$('[data-lt-status]').textContent=errorText(e);}finally{if(!disposed)b.disabled=false;}
  });
  if(climateFile){const transfer=new DataTransfer();transfer.items.add(climateFile);$('[data-lt-climate-file]').files=transfer.files;}
  if(climateFile)readClimate(climateFile);
  lists();toggles();queueReference();
  return ()=>{disposed=true;sequence++;climateFileSequence++;presetSequence++;referenceSequence++;clearTimeout(referenceTimer);mapCleanup?.();secondCleanup?.();sceneCleanup?.();document.removeEventListener('a3:subsidence-result',managed);document.removeEventListener('a3:quality-result',qualified);root.replaceChildren();root.hidden=true;};
}

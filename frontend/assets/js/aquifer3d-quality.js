/** Quality-conditioned storage scenarios; fitting and volumes stay in Pyodide. */
const assetVersion=new URL(import.meta.url).searchParams.get('v')||'quality-1';
const {mountMap}=await import(`./aquifer3d-maps.js?v=${encodeURIComponent(assetVersion)}`);
const {foldSettings}=await import(`./aquifer3d-layout.js?v=${encodeURIComponent(assetVersion)}`);
const fmt=(x,d=1)=>Number.isFinite(x)?new Intl.NumberFormat('fa-IR',{maximumFractionDigits:d}).format(x):'نامشخص';
const year=x=>new Intl.NumberFormat('fa-IR',{useGrouping:false}).format(x);
const models={idw:'IDW مکانی',trend_idw:'روند مکانی + IDW باقیمانده',gee_idw:'GEE + IDW باقیمانده',geology_gee_idw:'زمین‌شناسی + GEE + IDW باقیمانده'};

export function mountQualityTools({data,request}){
  const root=document.getElementById('qualityTools');root.hidden=false;
  root.innerHTML=`<div class="aquifer3d-section-heading"><div><h2>حجم باقی‌مانده با محدودیت شوری</h2><p>برآورد شرطی از کیفیت چاه‌ها، داده‌های کمکی و فرض توزیع کیفیت در عمق</p></div></div>
  <div class="a3-quality-inputs"><label>دادهٔ کیفیت <input type="file" accept=".csv,text/csv" data-q-file><small>پیش‌فرض: WaterQ.csv؛ فایل محلی جایگزین می‌شود.</small></label><label>پنجرهٔ کیفیت (سال آبی)<input type="number" min="1" max="10" value="3" data-q-window></label><label>حد EC برای غربالگری شوری شرب<input type="number" min="1" step="50" value="1500" data-q-drink><small>µS/cm؛ آستانهٔ سناریو، نه تأیید سلامت آب</small></label><label>حد EC کشاورزی<input type="number" min="1" step="50" value="3000" data-q-crop><small>µS/cm؛ همراه بررسی محدودیت شدید EC/SAR</small></label><label>نسبت EC کف به بالای لایه<input type="number" min="0.125" max="8" step="0.125" value="1" data-q-ratio><small>فرض عمقی؛ ۱ یعنی کیفیت یکنواخت</small></label></div>
  <p class="a3-quality-assumption">نمونه‌ها عمق مشخص ندارند. تعمیم EC به ستون اشباع، فرض این برآورد است؛ نسبت عمقی از GEE یا لاگ اندازه‌گیری نشده است. حجم شرب و کشاورزی همپوشانی دارند و نباید با هم جمع شوند.</p>
  <div class="a3-actions"><button type="button" data-q-run>محاسبهٔ برآورد کیفی و زون‌ها</button><span data-q-status role="status">پس از ساخت مدل آبخوان، این محاسبه را اجرا کنید.</span></div>
  <div data-q-results hidden><div class="a3-quality-cards"></div><p data-q-context></p><div class="a3-quality-map a3-map"></div><details><summary>اعتبارسنجی، فرض‌ها و حساسیت عمقی</summary><div data-q-validation></div><p>کف، Sy و پوشش کیفیت بر حجم اثر دارند. بازه‌ها حساسیت به خطای EC هستند و فاصلهٔ اطمینان ۹۵٪ یا حجم برداشت پایدار نیستند. SAR نیز در عمق ثابت فرض می‌شود؛ سایر آلاینده‌ها، نیاز آبشویی، محدودیت محصول و هزینهٔ تصفیه در این حجم منظور نشده‌اند.</p><p><a href="https://www.fao.org/4/t0234e/t0234e01.htm" target="_blank" rel="noopener">راهنمای FAO برای شوری و EC/SAR</a> · <a href="https://doi.org/10.1029/2012GC004370" target="_blank" rel="noopener">منبع GLiM</a></p></details><div class="a3-actions"><button type="button" data-q-report>شناسنامهٔ مدل JSON</button></div></div>`;
  const $=selector=>root.querySelector(selector),run=$('[data-q-run]'),status=$('[data-q-status]');
  const settingsLayout=foldSettings(root,{key:'quality',title:'تنظیم آستانه‌ها و دادهٔ کیفیت',nodes:[$('.a3-quality-inputs')]});
  const empty=document.createElement('div');empty.className='a3-analysis-empty';
  const emptyTitle=document.createElement('strong'),emptyText=document.createElement('p');emptyTitle.textContent='کیفیت آب هنوز محاسبه نشده';emptyText.textContent='آستانه‌ها را بررسی کنید و «محاسبه کیفیت» را بزنید تا زون‌های شوری و حجم زیر آستانه نمایش داده شوند.';empty.append(emptyTitle,emptyText);$('[data-q-results]').before(empty);
  run.textContent='محاسبه کیفیت';
  function settingsSummary(){settingsLayout.context.textContent=`شرب ${fmt(Number($('[data-q-drink]').value),0)} / کشاورزی ${fmt(Number($('[data-q-crop]').value),0)} µS/cm`;}
  settingsSummary();
  let disposed=false,mapCleanup=null,report=null,sequence=0;
  function card(label,value,note){const article=document.createElement('article'),title=document.createElement('span'),number=document.createElement('strong'),help=document.createElement('small');title.textContent=label;number.textContent=fmt(value,0)+' میلیون مترمکعب';help.textContent=note;article.append(title,number,help);$('.a3-quality-cards').append(article);}
  async function calculate(){
    const token=++sequence;run.disabled=true;status.textContent='در حال بارگذاری مدل کیفیت و اعتبارسنجی مکانی…';
    $('[data-q-results]').hidden=true;mapCleanup?.();mapCleanup=null;
    try{
      const file=$('[data-q-file]').files[0];
      const quality_text=file?await file.text():'';
      const options={window:Number($('[data-q-window]').value),drinking_ec:Number($('[data-q-drink]').value),irrigation_ec:Number($('[data-q-crop]').value),depth_ratio:Number($('[data-q-ratio]').value),quality_text,quality_input_file:file?.name||'WaterQ.csv',volume_input_files:data.input_files};
      const result=await request('quality',options);if(disposed||token!==sequence)return;
      report=result.report;
      const t=report.volumes_mcm;$('.a3-quality-cards').replaceChildren();
      card('کل ذخیرهٔ قابل زهکشی برآوردی',report.total_remaining_mcm,'حجم سناریویی با کف و Sy انتخابی');
      card('زیر حد شوریِ انتخابی شرب',t.drinking,`حساسیت EC: ${fmt(t.drinking_low,0)} تا ${fmt(t.drinking_high,0)}؛ سلامت آب بررسی نشده`);
      card('کشاورزی بدون محدودیت شدید EC/SAR',t.irrigation,`حساسیت EC: ${fmt(t.irrigation_low,0)} تا ${fmt(t.irrigation_high,0)}؛ محدودیت محصول بررسی نشده`);
      card('حجم فاقد پوشش معتبر کیفیت',t.unknown,`برای EC/SAR کشاورزی: ${fmt(t.irrigation_unknown,0)} میلیون مترمکعب نامشخص`);
      $('[data-q-context]').textContent=`کیفیت WY ${year(report.quality_water_year)}، پنجرهٔ ${fmt(report.window_years,0)} سال و ${fmt(report.sites,0)} موقعیت؛ حجم شهریور ${data.dates.after.slice(0,4)}. فاصلهٔ دورهٔ کیفیت و حجم: ${fmt(report.quality_volume_year_gap,0)} سال آبی؛ کیفیت در این فاصله ثابت فرض شده است. مدل برتر: ${models[report.validation.selected]}. نسبت EC کف به بالا: ${fmt(report.vertical_model.bottom_top_ec_ratio,3)}.`;
      const mapData={...data,plan_maps:result.plan_maps,quality_report:report,quality_sites:result.sites,
        input_files:{...data.input_files,quality:file?.name||'WaterQ.csv'}};
      mapCleanup=mountMap($('.a3-quality-map'),mapData,['quality_zone_code','quality_ec','quality_sar','quality_drinking_pct','quality_usable_pct'],'quality-plan');
      const validation=$('[data-q-validation]');validation.replaceChildren();
      for(const [name,score] of Object.entries(report.validation.scores)){const p=document.createElement('p');p.textContent=`${models[name]}: RMSE لگاریتم EC = ${fmt(score.rmse_log,3)}؛ MAE = ${fmt(score.mae_ec,0)} µS/cm`;validation.append(p);}
      for(const [ratio,value] of Object.entries(report.depth_sensitivity)){const p=document.createElement('p');p.textContent=`سناریوی نسبت عمقی ${ratio}: زیر حد شوری شرب ${fmt(value.drinking_mcm,0)} و EC/SAR کشاورزی ${fmt(value.irrigation_mcm,0)} میلیون مترمکعب`;validation.append(p);}
      const note=document.createElement('p');note.textContent=`اعتبارسنجی: ${fmt(report.validation.fold_count,0)} گروه بلوک مکانی ۱۰ کیلومتری؛ انتخاب مدل با همین اعتبارسنجی انجام شده و آزمون مستقل نهایی نیست. شعاع پشتیبانیِ مشتق از فاصله‌های آزمون ${fmt(report.validation.support_radius_m/1000,1)} کیلومتر است؛ بیرون پوش محدب یا شعاع پشتیبانی، نامشخص می‌ماند. EC ورودی µS/cm و تصحیح‌شده به ۲۵ درجه فرض شده؛ مبنای UTM نیز WGS84 شمالی فرض شده است. در سناریوی عمقی، EC نمونه به‌صورت فرضی نمایندهٔ میانهٔ هندسی ستون است و لاگ عمقی اندازه‌گیری‌شده نیست.`;validation.append(note);
      $('[data-q-results]').hidden=false;status.textContent='برآورد و زون‌های کیفی به‌روز شدند.';
      empty.hidden=true;settingsLayout.details.open=false;run.textContent='به‌روزرسانی کیفیت';settingsSummary();
      document.dispatchEvent(new CustomEvent('a3:quality-result',{detail:result}));
    }catch(error){if(!disposed&&token===sequence)status.textContent=error.message;}
    finally{if(!disposed&&token===sequence)run.disabled=false;}
  }
  run.onclick=calculate;
  root.querySelectorAll('input').forEach(input=>input.addEventListener('change',()=>{sequence++;mapCleanup?.();mapCleanup=null;report=null;$('[data-q-results]').hidden=true;empty.hidden=false;run.disabled=false;settingsSummary();status.textContent='تنظیمات کیفیت تغییر کرده؛ برای اعمال آن، کیفیت را دوباره محاسبه کنید.';document.dispatchEvent(new CustomEvent('a3:quality-result',{detail:null}));}));
  $('[data-q-report]').onclick=()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=`${data.aquifer.name}-quality-WY${report.quality_water_year}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);};
  return ()=>{disposed=true;sequence++;mapCleanup?.();root.replaceChildren();root.hidden=true;};
}

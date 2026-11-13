/** Manager workflow. Displays existing results; never computes scientific values. */
export const workflowStage={scenes:'status',quality:'status',parameters:'status',lifetime:'decision',management:'decision',tools:'output',sources:'output'};

export function mountManagementFlow({navigate,settings}){
  const $=id=>document.getElementById(id),workspace=$('a3Workspace');
  const steps=[...document.querySelectorAll('[data-flow-stage]')];
  let model=null,quality=null,management=null,lifetime=null,lifetimeState='empty',section='scenes',settingsOpen=false;
  const labels={quality:'شوری',subsidence:'فرونشست',lifetime:'سناریوی عمر'};
  function openLayer(kind){
    settings(true);
    const field={spatial:'spatialMethodInput',grid:'pixelWidthInput',sy:'syInput',bedrock:'bedrockFile',quality:'qualityInputFile',subsidence:'subsidenceInputFile',climate:'climateInputFile'}[kind];
    const input=$(field);if(!input)return;
    input.closest('details').open=true;input.focus();input.scrollIntoView({block:'center'});
  }
  function openAnalysis(kind){
    if(kind==='quality'){
      navigate('quality',true);const form=document.querySelector('[data-analysis-settings=quality]');if(form)form.open=true;
      document.querySelector('[data-q-file]')?.focus();
    }else if(kind==='subsidence'){
      navigate('management',true);document.querySelector('[data-m-open-source]')?.click();
    }else navigate('lifetime',true);
  }
  function output(){navigate('tools',true);$('a3Tab-export')?.click();}
  function selection(open){$('a3QuickControls').hidden=!open;$('a3EditSelection').setAttribute('aria-expanded',String(open));}
  $('a3EditSelection').onclick=()=>{const open=$('a3QuickControls').hidden;selection(open);if(open){$('aquiferSelect3d').focus();$('a3QuickControls').scrollIntoView({block:'center'});}};
  function go(stage){
    if(stage==='inputs'){settings(true);return;}
    if(!model)return;
    if(stage==='output')output();else navigate(stage==='decision'?'lifetime':'scenes',true);
  }
  steps.forEach(button=>{
    button.onclick=()=>go(button.dataset.flowStage);
    button.onkeydown=event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();const enabled=steps.filter(b=>!b.disabled),i=enabled.indexOf(button);
      const next=event.key==='Home'?enabled[0]:event.key==='End'?enabled.at(-1):enabled[(i+(event.key==='ArrowLeft'?1:enabled.length-1))%enabled.length];next?.focus();
    };
  });
  function readiness(){
    const sub=management?.report?.subsidence;
    return {quality:!!(quality?.report?.sites&&quality.plan_maps?.cells.some(c=>c.quality_supported&&Number.isFinite(c.quality_ec))),
      subsidence:!!(sub?.input_records&&!sub.input_error&&sub.component==='vertical'&&management.plan_maps.cells.some(c=>Number.isFinite(c.management_subsidence))),
      lifetime:lifetimeState==='ready'};
  }
  function drawReadiness(){
    const host=$('a3FlowReadiness'),ready=readiness();host.hidden=!model||workflowStage[section]!=='status';
    for(const kind of ['quality','subsidence','lifetime']){
      let button=host.querySelector(`[data-flow-analysis=${kind}]`);
      if(!button){button=document.createElement('button');button.type='button';button.dataset.flowAnalysis=kind;button.append(document.createElement('strong'),document.createElement('span'));button.onclick=()=>openAnalysis(kind);host.append(button);}
      button.dataset.ready=String(ready[kind]);button.disabled=!model||workspace.dataset.state==='loading';
      button.querySelector('strong').textContent=labels[kind];
      button.querySelector('span').textContent=ready[kind]?'محاسبه شده':kind==='lifetime'&&lifetimeState==='stale'?'نیاز به اجرای مجدد':kind==='lifetime'?'تعریف سناریو':kind==='quality'?(model?.input_files?.quality?'بررسی آستانه‌ها و اجرا':'انتخاب فایل و اجرا'):(model?.input_files?.subsidence?'تأیید دوره و اجرا':'افزودن لایه');
    }
  }
  function inventory(){
    const present={sy:$('syMode').value==='spatial'?!!$('syFile').files[0]:$('syInput').value.trim()!==''};
    for(const [kind,id]of Object.entries({bedrock:'bedrockFile',quality:'qualityInputFile',subsidence:'subsidenceInputFile',climate:'climateInputFile'}))present[kind]=!!$(id).files[0];
    for(const [kind,chosen]of Object.entries(present)){
      const state=document.querySelector(`[data-layer-state=${kind}]`);state.textContent=chosen?(kind==='sy'&&$('syMode').value==='constant'?'مقدار وارد شده':'فایل انتخاب شده'):['sy','bedrock'].includes(kind)?'برای محاسبهٔ ذخیره':'اختیاری';
      state.closest('details').dataset.selected=String(chosen);
      const grid=state.closest('details').querySelector('.aquifer3d-form-grid');let clear=grid.querySelector('[data-clear-layer]');
      if(!clear){clear=document.createElement('button');clear.type='button';clear.className='a3-clear-layer';clear.dataset.clearLayer=kind;clear.textContent=kind==='sy'?'پاک‌کردن مقدار / فایل':'حذف فایل';clear.onclick=()=>{const node=kind==='sy'?($('syMode').value==='spatial'?$('syFile'):$('syInput')):$( {bedrock:'bedrockFile',quality:'qualityInputFile',subsidence:'subsidenceInputFile',climate:'climateInputFile'}[kind]);node.value='';node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));inventory();};grid.append(clear);}
      clear.hidden=!chosen;
    }
    $('a3InputScope').textContent=present.sy&&present.bedrock?'سطح آب + برآورد ذخیره':present.sy||present.bedrock?'سطح آب · برای ذخیره، '+(present.sy?'سنگ‌بستر':'Sy')+' را هم وارد کنید':'بدون فایل اضافی: نمایش سطح آب';
  }
  function exportHub(){
    const host=$('a3ExportHub'),ready=readiness();
    host.hidden=$('a3Tab-export')?.getAttribute('aria-selected')!=='true';
    const exports=[
      {kind:'lifetime',title:'سناریوی عمر',ready:ready.lifetime,note:ready.lifetime?lifetime?.report?.scenario?.name:lifetimeState==='stale'?'تنظیمات تغییر کرده؛ سناریو را دوباره اجرا کنید.':'هنوز محاسبه نشده',actions:[['گزارش JSON','[data-lt-export=json]'],['نقشه TIFF','[data-lt-export=tiff]']]},
      {kind:'quality',title:'شوری و کیفیت',ready:ready.quality,note:ready.quality?'نتیجهٔ محاسبهٔ جاری':'هنوز محاسبه نشده',actions:[['گزارش JSON','[data-q-report]']]},
      {kind:'management',title:'اولویت و آینده',ready:!!management,note:management?'نتیجهٔ محاسبهٔ جاری':'روند آماده نیست',actions:[['گزارش JSON','[data-m-json]'],['جدول افق‌ها CSV','[data-m-forecast-csv]']]}
    ];
    host.replaceChildren();
    for(const item of exports){
      const card=document.createElement('article'),title=document.createElement('strong'),note=document.createElement('span'),buttons=document.createElement('div');
      card.dataset.flowExport=item.kind;title.textContent=item.title;note.textContent=item.note;
      for(const [label,selector]of item.actions){const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=!item.ready;b.onclick=()=>document.querySelector(selector)?.click();buttons.append(b);}
      if(!item.ready){const b=document.createElement('button');b.type='button';b.textContent='رفتن به تحلیل';b.onclick=()=>item.kind==='management'?navigate('management',true):openAnalysis(item.kind);buttons.append(b);}
      card.append(title,note,buttons);host.append(card);
    }
  }
  function next(){
    const stage=workflowStage[section],host=$('a3FlowNext'),button=$('a3FlowContinue'),back=$('a3FlowBack');host.hidden=!model;
    const ready=readiness();back.hidden=stage==='status';back.onclick=()=>go(stage==='output'?'decision':'status');
    $('a3FlowNextLabel').textContent='گام بعد';
    let title,action;
    if(workspace.dataset.draft==='true'){title='ورودی‌های جدید را اعمال کنید';button.textContent='اعمال تغییرات';action=()=>$('a3ApplyDraft').click();}
    else if(section==='quality'&&!ready.quality){title='آستانه‌های شوری را بررسی و کیفیت را محاسبه کنید';button.textContent='بررسی تنظیمات کیفیت';action=()=>openAnalysis('quality');}
    else if(stage==='status'){title='محدودیت‌ها را در یک سناریو بررسی کنید';button.textContent='سناریو و اقدام';action=()=>go('decision');}
    else if(stage==='decision'&&!ready.lifetime&&section==='lifetime'){
      const run=document.querySelector('[data-lt-run]');title=lifetimeState==='stale'?'تنظیمات تغییر کرده؛ سناریو را دوباره اجرا کنید':'فرض‌ها و محدودیت‌های سناریو را بررسی کنید';button.textContent=run&&!run.disabled?'محاسبهٔ سناریو':'تکمیل تنظیمات سناریو';
      action=()=>{if(run&&!run.disabled){run.click();return;}const editor=document.querySelector('.lt-editor');if(editor){editor.open=true;editor.scrollIntoView({block:'start'});editor.querySelector('input')?.focus();}};
    }
    else if(stage==='decision'){title='نتیجه را برای گزارش دریافت کنید';button.textContent='خروجی و گزارش';action=output;}
    else{title='بازبینی سناریو و نتایج';button.textContent='بازگشت به سناریو';action=()=>go('decision');}
    $('a3FlowNextTitle').textContent=title;button.onclick=action;button.disabled=workspace.dataset.state==='loading'||lifetimeState==='running';
  }
  function sync(key=section,open=settingsOpen){
    section=key;settingsOpen=open;const stage=open?'inputs':workflowStage[key],busy=workspace.dataset.state==='loading';
    $('a3EditSelection').hidden=!model;$('a3EditSelection').disabled=busy;
    workspace.dataset.stage=workflowStage[key];
    for(const button of steps){
      const k=button.dataset.flowStage;button.disabled=k==='inputs'?$('build3d').disabled:!model||busy;
      if(k===stage)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');
      button.dataset.complete=String(k==='inputs'?!!model:k==='status'?!!model:k==='decision'?lifetimeState==='ready':false);
    }
    $('a3Flow').querySelector('[data-flow-state=inputs]').textContent=model?'ویرایش ورودی‌ها':'انتخاب آبخوان و فایل‌ها';
    $('a3Flow').querySelector('[data-flow-state=decision]').textContent=lifetimeState==='ready'?'سناریو محاسبه شده':lifetimeState==='stale'?'سناریو نیاز به اجرا دارد':'عمر و اولویت مداخله';
    drawReadiness();next();inventory();
  }
  document.addEventListener('a3:open-input-layer',event=>openLayer(event.detail));
  document.addEventListener('a3:quality-result',event=>{quality=event.detail;sync();exportHub();});
  document.addEventListener('a3:subsidence-result',event=>{management=event.detail;sync();exportHub();});
  document.addEventListener('a3:lifetime-state',event=>{lifetimeState=event.detail.state;if(event.detail.result)lifetime=event.detail.result;sync();exportHub();});
  $('professionalTools').addEventListener('click',()=>{$('a3ExportHub').hidden=$('a3Tab-export')?.getAttribute('aria-selected')!=='true';});
  $('a3Settings').addEventListener('input',inventory);$('a3Settings').addEventListener('change',inventory);
  document.addEventListener('a3:user-layer-file',()=>queueMicrotask(inventory));
  const controlsObserver=new MutationObserver(()=>sync());controlsObserver.observe($('build3d'),{attributes:true,attributeFilter:['disabled']});
  return {sync,clear(){model=quality=management=lifetime=null;lifetimeState='empty';selection(true);sync();exportHub();},result(data){model=data;selection(false);sync();exportHub();}};
}

/** Navigation, drafts and layout. Scientific state stays in the Pyodide worker. */
export function mountWorkspace() {
  const $=id=>document.getElementById(id),root=$('a3Workspace');
  const mobile=matchMedia('(max-width: 850px)');
  const tabs=[...document.querySelectorAll('[data-workspace-tab]')];
  const sceneTabs=[...document.querySelectorAll('[data-scene-view]')];
  const sectionSelect=$('a3SectionSelect');
  const sections={scenes:['نمای آبخوان','سطح آب، سنگ‌بستر و تغییر ذخیره'],quality:['کیفیت آب','شوری و سهم حجم زیر آستانهٔ انتخابی'],management:['آینده و اقدام','اولویت مداخله، مسیر آینده و فرونشست'],parameters:['لایه‌های ورودی','نقشهٔ Sy، سنگ‌بستر و لایهٔ فرونشست'],tools:['تحلیل و خروجی','برش مقطعی، مقایسه، تصویر و فیلم'],sources:['منابع و فرض‌ها','منشأ داده‌ها و محدودیت تفسیر نتایج']};
  let currentTab='scenes',sceneView='geology',waterView='pixels',ready=false,settingsOpen=false,dialogFocus=null;
  const help=document.querySelector('.a3-canvas-help'),originalHelp=help.textContent;
  const background=[document.querySelector('.site-header'),document.querySelector('.a3-workspace-heading'),document.querySelector('.a3-quick-controls'),document.querySelector('.a3-section-rail'),$('a3WorkspaceMain')];
  function resize(){requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')));}
  function settings(open,focus=false){
    if(open&&!settingsOpen)dialogFocus=document.activeElement;
    settingsOpen=open;root.dataset.settings=open?'open':'closed';
    $('toggleA3Settings').setAttribute('aria-expanded',String(open));
    $('a3Settings').inert=!open;$('a3Settings').setAttribute('role','dialog');
    if(open)$('a3Settings').setAttribute('aria-modal','true');else $('a3Settings').removeAttribute('aria-modal');
    $('a3SettingsBackdrop').hidden=!open;
    document.body.classList.toggle('a3-settings-modal',open);
    background.forEach(node=>{if(node)node.inert=open;});
    if(focus){if(open)$('closeA3Settings').focus();else (dialogFocus?.isConnected&&dialogFocus.getClientRects().length?dialogFocus:$('toggleA3Settings')).focus();}
    resize();
  }
  function apply(){document.dispatchEvent(new CustomEvent('a3:apply-inputs'));if(settingsOpen&&root.dataset.state==='loading')settings(false,true);}
  $('toggleA3Settings').onclick=()=>settings(!settingsOpen,true);
  $('closeA3Settings').onclick=() =>settings(false,true);
  $('a3SettingsBackdrop').onclick=()=>settings(false,true);
  $('a3EmptyAction').onclick=()=>settings(true,true);
  $('a3SettingsApply').onclick=apply;$('a3ApplyDraft').onclick=apply;
  $('a3DiscardDraft').onclick=()=>document.dispatchEvent(new CustomEvent('a3:discard-inputs'));
  const syncApply=()=>{ $('a3SettingsApply').disabled=$('build3d').disabled; $('a3ApplyDraft').disabled=$('build3d').disabled; };
  new MutationObserver(syncApply).observe($('build3d'),{attributes:true,attributeFilter:['disabled']});syncApply();
  $('a3MoreMetrics').onclick=()=>{const expanded=$('a3MoreMetrics').getAttribute('aria-expanded')!=='true';$('a3MoreMetrics').setAttribute('aria-expanded',expanded);document.querySelector('.aquifer3d-summary').dataset.metricsExpanded=expanded;};
  $('a3MobileSummary').onclick=()=>{const expanded=$('a3MobileSummary').getAttribute('aria-expanded')!=='true';$('a3MobileSummary').setAttribute('aria-expanded',expanded);root.dataset.mobileSummary=expanded;};
  const compactScreen=matchMedia('(max-width:600px)');
  function cameraMenu(){ $('a3CameraPresets').open=!compactScreen.matches; }
  compactScreen.addEventListener('change',cameraMenu);cameraMenu();
  document.addEventListener('keydown',event=>{
    if(!settingsOpen)return;
    if(event.key==='Escape'){event.preventDefault();settings(false,true);return;}
    if(event.key!=='Tab')return;
    const nodes=[...$('a3Settings').querySelectorAll('button:not(:disabled),select:not(:disabled),input:not(:disabled),summary')].filter(n=>n.getClientRects().length);
    const first=nodes[0],last=nodes.at(-1);
    if(!nodes.includes(document.activeElement)){event.preventDefault();first?.focus();}
    else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  });
  for(const tab of tabs)sectionSelect.add(new Option(sections[tab.dataset.workspaceTab][0],tab.dataset.workspaceTab));
  function syncNavigation(){for(const option of sectionSelect.options)option.disabled=tabs.find(t=>t.dataset.workspaceTab===option.value).disabled;sectionSelect.value=currentTab;document.querySelectorAll('[data-open-tool]').forEach(button=>{button.disabled=!ready;});}
  function navigate(key,focus=false){
    const selected=tabs.find(t=>t.dataset.workspaceTab===key);if(!selected||selected.disabled)return;
    currentTab=key;root.dataset.section=key;
    tabs.forEach(tab=>{const active=tab===selected;tab.setAttribute('aria-selected',active);tab.tabIndex=active?0:-1;});
    document.querySelectorAll('[data-workspace-panel]').forEach(panel=>{panel.hidden=panel.dataset.workspacePanel!==key;});
    $('a3SectionTitle').textContent=sections[key][0];$('a3SectionDescription').textContent=sections[key][1];syncNavigation();
    if(focus){if(mobile.matches)sectionSelect.focus();else selected.focus();}
    document.dispatchEvent(new CustomEvent('a3:section-changed',{detail:key}));resize();
  }
  sectionSelect.onchange=()=>navigate(sectionSelect.value);
  document.querySelectorAll('[data-open-tool]').forEach(button=>{button.onclick=()=>{if(!ready)return;navigate('tools');$(`a3Tab-${button.dataset.openTool}`)?.click();document.querySelector(`#a3Panel-${button.dataset.openTool} button`)?.focus();};});
  function viewControls(){document.querySelector('.a3-scene-context').hidden=sceneView==='water';const three=sceneView!=='water'||waterView==='pixels';document.querySelector('.aquifer3d-toolbar').hidden=!three;help.textContent=three?originalHelp:waterView==='percent'?'برای زوم از چرخ ماوس یا دکمه‌های نقشه و برای جابه‌جایی از کشیدن نقشه استفاده کنید. روی هر سلول کلیک کنید تا درصد و حجم آن نمایش داده شود.':'این نما حجم کل آبخوان را با مقیاس یکسان مقایسه می‌کند؛ تفاوت‌های مکانی در ستون‌ها و نقشهٔ درصدها در دسترس‌اند.';}
  document.addEventListener('a3:water-view',event=>{waterView=event.detail;viewControls();});
  function scene(key,focus=false){
    $('a3SceneSelect').value=key;
    sceneView=key;root.dataset.scene=key;$('sceneGeology').hidden=key==='water';$('sceneWater').hidden=key==='geology';
    $('sceneGeology').setAttribute('aria-labelledby',key==='both'?'sceneBothTab':'sceneGeologyTab');$('sceneWater').setAttribute('aria-labelledby',key==='both'?'sceneBothTab':'sceneWaterTab');
    sceneTabs.forEach(button=>{const active=button.dataset.sceneView===key;button.setAttribute('aria-selected',active);button.tabIndex=active?0:-1;if(active&&focus)button.focus();});viewControls();resize();
  }
  function keyboard(event,buttons,select){
    if(!['ArrowLeft','ArrowRight','ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    event.preventDefault();const enabled=buttons.filter(b=>!b.disabled),index=enabled.indexOf(event.currentTarget);
    const target=event.key==='Home'?enabled[0]:event.key==='End'?enabled.at(-1):enabled[(index+(['ArrowLeft','ArrowDown'].includes(event.key)?1:enabled.length-1))%enabled.length];select(target,true);
  }
  tabs.forEach(button=>{button.onclick=()=>navigate(button.dataset.workspaceTab);button.onkeydown=e=>keyboard(e,tabs,(b,focus)=>navigate(b.dataset.workspaceTab,focus));});
  sceneTabs.forEach(button=>{button.onclick=()=>scene(button.dataset.sceneView);button.onkeydown=e=>keyboard(e,sceneTabs,(b,focus)=>scene(b.dataset.sceneView,focus));});
  $('a3SceneSelect').onchange=()=>scene($('a3SceneSelect').value);
  $('a3OpenQuality').onclick=()=>navigate('quality',true);

  function state(value,message){
    root.dataset.state=value;
    if(value==='dirty'&&ready)root.dataset.draft='true';
    if(value==='ready')root.dataset.draft='false';
    $('a3DraftNotice').hidden=!(ready&&root.dataset.draft==='true');
    $('a3DiscardDraft').disabled=value==='loading';
    $('a3ResultState').dataset.state=value;$('a3ResultState').textContent=({loading:'در حال محاسبه',ready:ready?'نتایج به‌روز':'نیاز به محاسبه',dirty:ready?'تغییرات اعمال نشده':'نیاز به محاسبه',error:'نیاز به بررسی'})[value];
    $('build3d').textContent=value==='loading'?'در حال محاسبه…':value==='dirty'?'اعمال تغییرات':ready?'محاسبه مجدد':'محاسبه و نمایش';
    $('a3WorkspaceMain').setAttribute('aria-busy',value==='loading');
    for(const key of ['quality','management','tools'])$(`a3Panel-${key}`).inert=value==='loading';
    $('a3SettingsFeedback').hidden=value!=='error';$('a3SettingsFeedback').textContent=value==='error'?message:'';
    if(!ready){$('a3EmptyTitle').textContent=value==='error'?'مدل آماده نشد':value==='dirty'||value==='ready'?'ورودی‌ها را انتخاب و محاسبه کنید':'در حال آماده‌سازی نمای آبخوان';$('a3EmptyText').textContent=value==='error'?message:value==='dirty'||value==='ready'?'آبخوان و زمان مبنا را از نوار بالا انتخاب کنید.':'داده‌های محدوده و پیزومترها بارگذاری می‌شوند. اجرای نخست ممکن است کمی زمان ببرد.';$('a3EmptyAction').hidden=value==='loading';}
  }
  function clear(){ready=false;root.dataset.ready='false';root.dataset.draft='false';$('a3DraftNotice').hidden=true;tabs.filter(b=>['quality','parameters','tools','management'].includes(b.dataset.workspaceTab)).forEach(b=>{b.disabled=true;});if(!['scenes','sources'].includes(currentTab))navigate('scenes');syncNavigation();}
  function compactMetrics(){document.querySelectorAll('.aquifer3d-metric strong').forEach(strong=>{const text=strong.textContent,match=text.match(/^(.*?)\s*(میلیون مترمکعب|کیلومتر مربع|چاه مشترک|متر)$/);if(!match)return;const number=document.createElement('span'),unit=document.createElement('span');number.className='a3-stat-number';number.textContent=match[1];unit.className='a3-stat-unit';unit.textContent=match[2];strong.replaceChildren(number,document.createTextNode(' '),unit);});}
  function result(data){
    ready=true;root.dataset.ready='true';root.dataset.draft='false';tabs.forEach(b=>{b.disabled=false;});syncNavigation();$('a3NoParameters').hidden=!$('parameterMaps').hidden;$('a3ActiveAquifer').textContent=data.aquifer.name;
    const y=x=>new Intl.NumberFormat('fa-IR',{useGrouping:false}).format(Number(x.slice(0,4)));
    $('comparisonEnd').textContent=`شهریور ${y(data.dates.before)} تا ${y(data.dates.after)}`;
    compactMetrics();state('ready');if(settingsOpen){settings(false);$('build3d').focus({preventScroll:true});}resize();
    $('a3MobileMetricValue').textContent=$('declineMetric').textContent;
    $('declineMetric').closest('article').dataset.trend=data.metrics.mean_head_decline_m<0?'rise':'decline';
  }
  settings(false);scene('geology');clear();navigate('scenes');
  return {state,clear,result,context:name=>{$('a3ActiveAquifer').textContent=name;}};
}

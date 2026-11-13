/** Accessible information opened by click or keyboard activation only. */
(() => {
  const sources=new WeakMap(),groups=new WeakMap(),bindings=new WeakMap();let active=null,anchor=null,pinned=false,timer;
  const popup=document.createElement('div');popup.id='hydroTooltip';popup.className='hydro-tooltip';popup.role='tooltip';popup.hidden=true;
  function mount(){if(!popup.isConnected)document.body.append(popup);}
  function place(event){
    if(!anchor||popup.hidden)return;
    const r=anchor.getBoundingClientRect(),width=popup.offsetWidth,height=popup.offsetHeight;
    const x=event?.clientX??r.left+r.width/2,y=event?.clientY??r.bottom;
    popup.style.left=Math.max(10,Math.min(innerWidth-width-10,x-width/2))+'px';
    popup.style.top=Math.max(10,Math.min(innerHeight-height-10,y+12+height<innerHeight?y+12:r.top-height-10))+'px';
  }
  function hide(){clearTimeout(timer);popup.hidden=true;anchor?.removeAttribute('aria-describedby');anchor=null;active=null;pinned=false;}
  const reasonLabels={outside_trend_hull:'بیرون پوش محدب پیزومترهای دارای روند معتبر',beyond_trend_radius:'فاصله از نزدیک‌ترین پیزومتر بیش از شعاع پشتیبانی',no_eligible_wells:'پیزومتر دارای سابقهٔ زمانی کافی وجود ندارد',not_2d_support:'پراکندگی دوبعدی نقاط برای درون‌یابی کافی نیست',trend_missing:'روند معتبر سطح آب موجود نیست',bedrock_missing:'سنگ‌بستر وارد نشده یا پوشش کافی ندارد',sy_missing:'Sy وارد نشده یا پوشش کافی ندارد',climate_not_validated:'مدل اثر اقلیم داده یا اعتبارسنجی کافی ندارد',quality_missing:'کیفیت هنوز محاسبه نشده',quality_outside_support:'بیرون پوشش معتبر کیفیت آب',subsidence_not_vertical:'مؤلفهٔ دادهٔ نشست قائم نیست',subsidence_missing_or_outside_support:'دادهٔ نشست وارد نشده یا خارج پوشش است'};
  function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
  Object.assign(reasonLabels,{quality_trend_missing:'سابقهٔ زمانی یا پوشش مکانی کافی برای روند EC وجود ندارد',subsidence_period_unavailable:'دورهٔ نرخ نشست از فایل موجود قابل استخراج نیست'});
  function render(payload,target){
    popup.replaceChildren();
    const structured=payload&&typeof payload==='object';
    const title=structured?payload.title:(target.getAttribute('aria-label')||target.closest('label')?.querySelector('.hydro-label-title')?.textContent||'جزئیات').replace(/^توضیحات /,'').slice(0,100);
    popup.append(el('div','hydro-tooltip-title',title));
    let sections=structured?payload.sections:null;
    if(!sections){sections=String(payload||'').split(/\n\s*\n/).filter(Boolean).map(block=>{
      const rows=[],paragraphs=[];
      for(const line of block.split(/[|؛\n]+/).map(x=>x.trim()).filter(Boolean)){
        const match=line.match(/^([^:：]{1,65})[:：]\s*(.+)$/);
        if(match&&!/https?/.test(match[1]))rows.push([match[1],match[2]]);
        else paragraphs.push(...line.split(/(?<=[.؟!])\s+(?=[اآ-یA-Z])/).filter(Boolean));
      }
      return {rows,paragraphs};
    });}
    for(const section of sections||[]){
      const body=el('section','hydro-tooltip-section');
      if(section.title)body.append(el('div','hydro-tooltip-subtitle',section.title));
      if(section.rows?.length){const dl=el('dl','hydro-tooltip-values');for(const [k,v] of section.rows){dl.append(el('dt','',k));const dd=el('dd','',v??'نامشخص');dd.dir='auto';dl.append(dd);}body.append(dl);}
      for(const text of section.paragraphs||[])body.append(el('p','',text));
      if(section.bullets?.length){const ul=el('ul');for(const text of section.bullets)ul.append(el('li','',text));body.append(ul);}
      if(body.childNodes.length)popup.append(body);
    }
  }
  function showFor(target,text,event,sticky=false){
    if(!text||(typeof text==='string'&&!text.trim())||(pinned&&!sticky))return;
    mount();clearTimeout(timer);anchor?.removeAttribute('aria-describedby');anchor=target;active=target;pinned=sticky;
    render(text,target);popup.hidden=false;target.setAttribute('aria-describedby',popup.id);place(event);
  }
  function content(trigger){return (sources.get(trigger)||[]).filter(n=>n.isConnected).map(n=>n.textContent.trim()).filter(Boolean).join('\n\n');}
  function sourceAnchor(source){
    if(source.matches('[data-lt-curve-help]'))return source.closest('figure').querySelector('figcaption strong');
    if(source.matches('.a3-settings-body>[data-help-copy]'))return document.getElementById('aquifer3d-config-title');
    if(source.matches('.a3-canvas-help'))return document.querySelector('.aquifer3d-toolbar');
    if(source.id==='analysisReadiness')return source.closest('footer')?.querySelector('strong')||source.parentElement;
    if(source.matches('.a3-volume-caution'))return document.querySelector('.aquifer3d-metric-warn .aquifer3d-metric-label');
    if(source.matches('[data-lt-preset-help]'))return source.parentElement.querySelector('[data-lt-preset-label]');
    if(source.matches('[data-lt-prereq-guide]'))return source.closest('article').querySelector('strong');
    const criterion=source.closest('.lt-criteria section,.lt-climate');if(criterion)return document.querySelector(`[data-lt-criterion="${criterion.dataset.ltPanel}"] .lt-toggle`)||criterion.querySelector('.lt-toggle');
    const label=source.closest('label');if(label){
      let title=label.querySelector('.aquifer3d-field-label,.hydro-label-title,b');
      if(!title){const words=[...label.childNodes].filter(n=>n.nodeType===3&&n.textContent.trim());if(words.length){title=document.createElement('span');title.className='hydro-label-title';label.prepend(title);words.forEach(n=>title.append(n));}}
      return title||label;
    }
    const card=source.closest('.aquifer3d-metric,.a3-quality-cards article,.a3-management-cards article,.lt-cards article,.result-stat');
    if(card)return card.querySelector('.aquifer3d-metric-label,span:not(.aquifer3d-metric-icon)')||card;
    const section=source.closest('.aquifer3d-scene,.aquifer3d-note,.a3-map,.a3-tool-panel,.options-section,.well-selector,.analysis-setup,.aquifer-picker,.spatial-map-card,.panel,.a3-quality,.a3-management,.a3-lifetime,.lt-criteria section,.lt-climate,.lt-advanced,.lt-map,.lt-secondary-map,.aquifer3d-notes,.a3-workspace-heading,.a3-panel-heading,.comparison-page-heading');
    if(section)return section.querySelector('h1,h2,h3,h4,summary,.a3-map-controls')||section;
    return source.parentElement;
  }
  function attach(source){
    if((source.dataset.hydroHelp==='attached'&&source.matches('.a3-workspace-tabs small'))||bindings.get(source)?.isConnected||source.closest('#hydroTooltip,.well-modal,.aquifer-chat-panel'))return;
    const target=sourceAnchor(source);if(!target||source===target||source.contains(target))return;
    source.dataset.hydroHelp='attached';source.classList.add('hydro-help-source');
    if(source.matches('.a3-workspace-tabs small')){source.closest('button').title=source.textContent.trim();return;}
    let trigger=groups.get(target);
    if(!trigger?.isConnected){
      trigger=document.createElement('button');trigger.type='button';trigger.className='hydro-info-trigger';
      trigger.setAttribute('aria-label','توضیحات '+(target.getAttribute('aria-label')||target.querySelector('span,b,strong')?.textContent||target.textContent||'نقشه').trim().slice(0,65));
      trigger.innerHTML='<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8"/><path d="M10 9v5M10 6v.4"/></svg>';
      target.append(trigger);groups.set(target,trigger);sources.set(trigger,[]);
    }
    sources.get(trigger).push(source);bindings.set(source,trigger);
  }
  const selectors=[
    '.a3-workspace-tabs small','.a3-analysis-empty p','#comparisonIntro','#a3SectionDescription','#a3CitiesNote','.aquifer3d-field>small','.aquifer3d-scene-heading>p','.aquifer3d-scene-caption','.a3-canvas-help','.aquifer3d-method','.aquifer3d-note p:not(:has(a))','.a3-source-summary','.a3-volume-caution','.aquifer3d-action-row>p:not([role])',
    '.aquifer3d-metric small','.a3-quality .aquifer3d-section-heading p','.a3-quality-inputs small','.a3-quality details p','.a3-quality-assumption','[data-q-context]','.a3-quality-cards small',
    '.a3-management .aquifer3d-section-heading p','.a3-management-inputs small','.a3-management-settings small','.a3-management details p','.a3-management-caution','[data-m-priority-note]','[data-m-future-note]','[data-m-critical-note]','[data-m-subsidence-note]','.a3-measurement-context','.a3-management-cards small','[data-m-method] p',
    '.a3-map-note','.a3-professional .a3-tool-panel>p','.a3-scroll-hint','#a3SectionInfo','.a3-plan-section .aquifer3d-section-heading p',
    '#analysisReadiness','.setup-heading p','.method-options small','.option-hint','.selection-help','.section-description','.spatial-source-note','.picker-map>p','.well-coverage-legend>span:first-child','.well-coverage-legend>span:nth-last-child(-n+2)',
    '.comparison-page-heading p','#comparisonFilters p','#comparisonFilters [data-help-copy]','#comparisonMaps>[data-help-copy]',
    '[data-help-copy]'
  ].join(',');
  let scheduled=false;
  function scan(){scheduled=false;if(active&&(!active.isConnected||!active.getClientRects().length))hide();document.querySelectorAll(selectors).forEach(attach);if(active?.classList.contains('hydro-info-trigger')&&!popup.hidden){render(content(active),active);place();}}
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(scan);}}
  function start(){mount();scan();new MutationObserver(records=>{if(records.some(r=>!popup.contains(r.target)))schedule();}).observe(document.body,{childList:true,subtree:true,characterData:true});}
  document.addEventListener('click',e=>{const trigger=e.target.closest('.hydro-info-trigger');if(trigger){e.preventDefault();e.stopPropagation();if(active===trigger&&pinned)hide();else showFor(trigger,content(trigger),null,true);}else if(!popup.contains(e.target)&&!e.target.closest('canvas,.a3-plan-svg,[data-cell],[data-city-id]'))hide();},true);
  popup.addEventListener('pointerenter',()=>clearTimeout(timer));popup.addEventListener('pointerleave',()=>{if(!pinned)hide();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!popup.hidden){e.preventDefault();e.stopImmediatePropagation();hide();}},true);window.addEventListener('resize',hide);document.addEventListener('scroll',e=>{if(e.target===popup)return;if(pinned&&anchor?.isConnected){const r=anchor.getBoundingClientRect();if(r.bottom>=0&&r.top<=innerHeight){place();return;}}hide();},true);
  document.addEventListener('a3:section-changed',hide);
  window.HydroHelp={showFor,reasonLabel:key=>reasonLabels[key]||key,hide,hideTransient:()=>{if(!pinned)hide();},scan:schedule};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

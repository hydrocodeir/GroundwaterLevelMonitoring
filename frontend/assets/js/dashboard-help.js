/** Compact, accessible information on hover, keyboard focus or touch. */
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
  function showFor(target,text,event,sticky=false){
    if(!String(text||'').trim())return;
    mount();clearTimeout(timer);anchor?.removeAttribute('aria-describedby');anchor=target;active=target;pinned=sticky;
    popup.textContent=String(text).trim();popup.hidden=false;target.setAttribute('aria-describedby',popup.id);place(event);
  }
  function content(trigger){return (sources.get(trigger)||[]).filter(n=>n.isConnected).map(n=>n.textContent.trim()).filter(Boolean).join('\n\n');}
  function sourceAnchor(source){
    if(source.matches('.a3-canvas-help'))return document.querySelector('.aquifer3d-toolbar');
    if(source.id==='analysisReadiness')return source.closest('footer')?.querySelector('strong')||source.parentElement;
    if(source.matches('.a3-volume-caution'))return document.querySelector('.aquifer3d-metric-warn .aquifer3d-metric-label');
    const label=source.closest('label');if(label){
      let title=label.querySelector('.aquifer3d-field-label,.hydro-label-title,b');
      if(!title){const words=[...label.childNodes].filter(n=>n.nodeType===3&&n.textContent.trim());if(words.length){title=document.createElement('span');title.className='hydro-label-title';label.prepend(title);words.forEach(n=>title.append(n));}}
      return title||label;
    }
    const card=source.closest('.aquifer3d-metric,.a3-quality-cards article,.a3-management-cards article,.result-stat');
    if(card)return card.querySelector('.aquifer3d-metric-label,span:not(.aquifer3d-metric-icon)')||card;
    const section=source.closest('.aquifer3d-scene,.aquifer3d-note,.a3-map,.a3-tool-panel,.options-section,.well-selector,.analysis-setup,.aquifer-picker,.spatial-map-card,.panel,.a3-quality,.a3-management,.aquifer3d-notes,.a3-workspace-heading,.a3-panel-heading,.comparison-page-heading');
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
  function scan(){scheduled=false;if(active&&(!active.isConnected||!active.getClientRects().length))hide();document.querySelectorAll(selectors).forEach(attach);if(active?.classList.contains('hydro-info-trigger')&&!popup.hidden){popup.textContent=content(active);place();}}
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(scan);}}
  function start(){mount();scan();new MutationObserver(records=>{if(records.some(r=>!popup.contains(r.target)))schedule();}).observe(document.body,{childList:true,subtree:true,characterData:true});}
  document.addEventListener('pointerover',e=>{const trigger=e.target.closest('.hydro-info-trigger');if(trigger&&!pinned)showFor(trigger,content(trigger),e);});
  document.addEventListener('focusin',e=>{if(e.target.matches('.hydro-info-trigger'))showFor(e.target,content(e.target));});
  document.addEventListener('pointerout',e=>{if(!pinned&&active?.classList.contains('hydro-info-trigger')&&!active.contains(e.relatedTarget)&&!popup.contains(e.relatedTarget))timer=setTimeout(hide,160);});
  document.addEventListener('focusout',e=>{if(e.target===active&&!pinned)hide();});
  document.addEventListener('click',e=>{const trigger=e.target.closest('.hydro-info-trigger');if(trigger){e.preventDefault();e.stopPropagation();if(active===trigger&&pinned)hide();else showFor(trigger,content(trigger),null,true);}else if(!popup.contains(e.target)&&!e.target.closest('canvas,[data-cell],[data-city-id]'))hide();},true);
  popup.addEventListener('pointerenter',()=>clearTimeout(timer));popup.addEventListener('pointerleave',()=>{if(!pinned)hide();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!popup.hidden){e.preventDefault();e.stopImmediatePropagation();hide();}},true);window.addEventListener('resize',hide);document.addEventListener('scroll',e=>{if(e.target!==popup)hide();},true);
  document.addEventListener('a3:section-changed',hide);
  window.HydroHelp={showFor,hide,hideTransient:()=>{if(!pinned)hide();},scan:schedule};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

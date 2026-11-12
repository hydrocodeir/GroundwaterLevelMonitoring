/** Public cartographic context only. No city geometry enters groundwater calculations. */
(() => {
  const sourceUrl='/assets/data/khorasan-razavi-urban.geojson';
  const attribution='شهرها: GHSL / JRC و OpenStreetMap';
  const citation='https://human-settlement.emergency.copernicus.eu/ghs_ucdb_2024.php';
  const listeners=new Set();let promise,collection,enabled=true;
  try{enabled=localStorage.getItem('hydro:cities:visible')!=='false';}catch{}
  function subscribe(listener){listeners.add(listener);return()=>listeners.delete(listener);}
  function setEnabled(value){enabled=Boolean(value);try{localStorage.setItem('hydro:cities:visible',enabled);}catch{}listeners.forEach(fn=>fn());}
  async function ready(){
    if(collection)return collection;
    promise ||= fetch(sourceUrl).then(r=>{if(!r.ok)throw new Error('دریافت لایهٔ شهرها ناموفق بود.');return r.json();}).then(data=>{
      if(data.type!=='FeatureCollection'||!Array.isArray(data.features))throw new Error('لایهٔ شهرها معتبر نیست.');collection=data;listeners.forEach(fn=>fn());return data;
    }).catch(error=>{promise=null;throw error;});return promise;
  }
  const polygons=feature=>feature.geometry.type==='Polygon'?[feature.geometry.coordinates]:feature.geometry.type==='MultiPolygon'?feature.geometry.coordinates:[];
  function inExtent(feature,extent){const b=feature.bbox;return !extent||!b||(b[0]<=extent[2]&&b[2]>=extent[0]&&b[1]<=extent[3]&&b[3]>=extent[1]);}
  function description(feature){
    const p=feature.properties,point=p.label||feature.geometry.coordinates;
    return `${p.name}\n${p.source||'GHSL / JRC'}\n${feature.geometry.type==='Point'?'موقعیت شهر':'پهنهٔ بافت شهری'}\nطول ${Number(point[0]).toFixed(5)} · عرض ${Number(point[1]).toFixed(5)}`;
  }
  function paintSvg(group,project,extent){
    group.replaceChildren();group.style.display=enabled?'':'none';group.setAttribute('pointer-events','none');group.setAttribute('data-city-overlay','');
    if(!collection)return;
    const node=(tag,attrs,text)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text)n.textContent=text;return n;};
    for(const feature of collection.features.filter(f=>inExtent(f,extent))){
      if(feature.geometry.type!=='Point'){
        const path=polygons(feature).map(p=>p.map(r=>r.map((v,i)=>(i?'L':'M')+project(v).join(',')).join(' ')+'Z').join(' ')).join(' ');
        group.append(node('path',{d:path,fill:'#b99ac0','fill-opacity':'.08',stroke:'#80558b','stroke-width':'1.3','stroke-dasharray':'4 2','fill-rule':'evenodd','vector-effect':'non-scaling-stroke'}));
      }
      const point=feature.properties.label||feature.geometry.coordinates,[x,y]=project(point);
      group.append(node('circle',{cx:x,cy:y,r:3,fill:'#80558b',stroke:'#fff','stroke-width':1,'vector-effect':'non-scaling-stroke'}));
      const hit=node('circle',{cx:x,cy:y,r:8,fill:'transparent','pointer-events':'all',tabindex:0,role:'img','aria-label':feature.properties.name,'data-city-id':feature.properties.id,'data-city-point':''});
      hit.append(node('title',{},description(feature)));
      hit.onpointerenter=e=>window.HydroHelp?.showFor(hit,description(feature),e);
      hit.onpointerleave=()=>window.HydroHelp?.hideTransient();
      hit.onfocus=()=>window.HydroHelp?.showFor(hit,description(feature));
      hit.onblur=()=>window.HydroHelp?.hideTransient();
      hit.onclick=e=>{e.stopPropagation();window.HydroHelp?.showFor(hit,description(feature),e,true);};group.append(hit);
    }
  }
  function attachLeaflet(map){
    if(map._hydroCitiesAttached||!window.L)return;map._hydroCitiesAttached=true;
    for(const [pane,z,events] of [['hydroCityPane',610,'none'],['hydroCityPointPane',620,'auto']]){
      if(!map.getPane(pane))map.createPane(pane);map.getPane(pane).style.zIndex=String(z);map.getPane(pane).style.pointerEvents=events;
    }
    const control=L.control({position:'topright'});let layer,disposed=false,unsubscribe;
    control.onAdd=()=>{
      const div=L.DomUtil.create('div','hydro-city-control'),label=document.createElement('label'),input=document.createElement('input'),key=document.createElement('i'),text=document.createElement('span'),note=document.createElement('small');
      input.type='checkbox';input.checked=enabled;input.setAttribute('aria-label','نمایش شهرها');key.className='hydro-city-key';text.textContent='شهرها';note.dataset.helpCopy='';note.textContent='در حال دریافت لایه…';label.append(input,key,text);div.append(label,note);
      L.DomEvent.disableClickPropagation(div);L.DomEvent.disableScrollPropagation(div);input.onchange=()=>setEnabled(input.checked);
      const update=()=>{if(disposed)return;input.checked=enabled;if(layer){if(enabled&&!map.hasLayer(layer))layer.addTo(map);else if(!enabled&&map.hasLayer(layer))map.removeLayer(layer);}};
      unsubscribe=subscribe(update);
      ready().then(data=>{
        if(disposed)return;
        const markerRenderer=L.svg({pane:'hydroCityPointPane'});
        const footprints=L.geoJSON({...data,features:data.features.filter(f=>f.geometry.type!=='Point')},{pane:'hydroCityPane',renderer:L.svg({pane:'hydroCityPane'}),interactive:false,style:{color:'#80558b',weight:1.4,dashArray:'4 2',fillColor:'#b99ac0',fillOpacity:.08}});
        const points=L.featureGroup(data.features.map(feature=>{
          const point=feature.properties.label||feature.geometry.coordinates;
          const marker=L.circleMarker([point[1],point[0]],{pane:'hydroCityPointPane',renderer:markerRenderer,bubblingMouseEvents:false,radius:4,color:'#fff',weight:1,fillColor:'#80558b',fillOpacity:1});
          const label=document.createElement('span');label.textContent=description(feature);
          marker.bindTooltip(label,{direction:'top',className:'hydro-city-label'});marker.on('click',()=>marker.openTooltip());
          marker.on('add',()=>{const path=marker.getElement();if(path){path.dataset.cityId=feature.properties.id;path.setAttribute('tabindex','0');path.setAttribute('aria-label',feature.properties.name);path.onfocus=()=>marker.openTooltip();path.onblur=()=>marker.closeTooltip();}});
          return marker;
        }));
        map.on('click',()=>points.eachLayer(marker=>marker.closeTooltip()));
        layer=L.featureGroup([footprints,points]);note.textContent=`${data.features.length} شهر · GHSL / JRC و OpenStreetMap · پهنه‌ها: بافت شهری؛ نقاط: موقعیت شهر`;
        map.attributionControl?.addAttribution(`<a href="${citation}" target="_blank" rel="noopener">شهرها: GHSL/JRC</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a>`);update();
      }).catch(error=>{note.textContent=error.message;const retry=document.createElement('button');retry.textContent='تلاش دوباره';retry.type='button';retry.onclick=()=>{disposed=true;unsubscribe?.();map.removeControl(control);map._hydroCitiesAttached=false;attachLeaflet(map);};div.append(retry);});
      return div;
    };
    control.addTo(map);map.once('unload',()=>{disposed=true;unsubscribe?.();});
  }
  window.HydroCities={ready,subscribe,setEnabled,paintSvg,attachLeaflet,get enabled(){return enabled;},get collection(){return collection;},citation,attribution};
})();

let bedrockModel;
const $ = id => document.getElementById(id);
const fa = n => new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1}).format(n);
const camera = {eye:{x:1.1,y:1.25,z:1.05},up:{x:0,y:0,z:1}};
const colors = [[0,'#352a87'],[.2,'#1764ab'],[.4,'#169fb0'],[.6,'#68c2a3'],[.8,'#d8e485'],[1,'#f6d746']];
function traces(m){
  const lx=[],ly=[],lz=[];
  m.lines.forEach(line=>{line.forEach(p=>{lx.push(p[0]);ly.push(p[1]);lz.push(p[2])});lx.push(null);ly.push(null);lz.push(null)});
  return [
    {type:'surface',x:m.x,y:m.y,z:m.z,colorscale:colors,cmin:m.meta.minimum,cmax:m.meta.maximum,connectgaps:false,opacity:.94,name:'سطح برآوردی',colorbar:{title:{text:'BEDROC'},thickness:18,len:.7},hovertemplate:'E: %{x:.0f} m<br>N: %{y:.0f} m<br>BEDROC: %{z:.1f}<extra>Interpolated</extra>',lighting:{ambient:.7,diffuse:.8,specular:.12,roughness:.9},showlegend:false},
    {type:'scatter3d',mode:'lines',x:lx,y:ly,z:lz,line:{color:'#1b2536',width:3},name:'خطوط اصلی',hovertemplate:'E: %{x:.0f} m<br>N: %{y:.0f} m<br>BEDROC: %{z:.1f}<extra>Source contour</extra>',showlegend:false}
  ];
}
function scene(m){
  const b=m.meta.bounds,span=Math.max(b[2]-b[0],b[3]-b[1]);
  return {xaxis:{title:{text:'Easting (m) · UTM 40N'},tickformat:'.0f',nticks:5,backgroundcolor:'#f1f5f9',gridcolor:'#d5dfe8',showbackground:true},yaxis:{title:{text:'Northing (m)'},tickformat:'.0f',nticks:5,backgroundcolor:'#f1f5f9',gridcolor:'#d5dfe8',showbackground:true},zaxis:{title:{text:'BEDROC · raw value'},nticks:6,backgroundcolor:'#f1f5f9',gridcolor:'#d5dfe8',showbackground:true,autorange:$('depth').checked?'reversed':true},aspectmode:'manual',aspectratio:{x:(b[2]-b[0])/span,y:(b[3]-b[1])/span,z:.075*Number($('exag').value)},camera};
}
async function start(m){
  bedrockModel=m;
  const a=m.meta;
  $('summary').innerHTML=`<span>تعداد خطوط: <b>${fa(a.lines)}</b></span><span>رأس‌ها: <b>${fa(a.vertices)}</b></span><span>بازهٔ BEDROC: <b>${fa(a.minimum)} تا ${fa(a.maximum)}</b></span><span>فاصلهٔ شبکه: حدود <b>${fa(a.grid_spacing_m)} متر</b></span>`;
  await Plotly.newPlot('plot',traces(m),{paper_bgcolor:'#fff',font:{family:'Tahoma,Arial',color:'#17324b'},margin:{l:12,r:45,t:12,b:8},scene:scene(m),uirevision:'bedrock',hoverlabel:{font:{family:'Arial'}},annotations:[{text:'MASHHAD · BEDROCK CONTOURS',xref:'paper',yref:'paper',x:.02,y:.98,showarrow:false,font:{size:13,color:'#597488'}}]}, {responsive:true,displaylogo:false,scrollZoom:true,toImageButtonOptions:{format:'png',filename:'mashhad-bedrock-3d',width:1800,height:1200,scale:1.5}});
  $('status').textContent='آماده • برای مشاهدهٔ شکل سه‌بعدی، نمودار را بچرخانید.';
  $('status').dataset.state='ready';
  $('mode').onchange=()=>Plotly.restyle('plot',{visible:[$('mode').value!=='lines',$('mode').value!=='surface']});
  $('depth').onchange=()=>Plotly.relayout('plot',{'scene.zaxis.autorange':$('depth').checked?'reversed':true,'scene.zaxis.title.text':$('depth').checked?'BEDROC · positive downward':'BEDROC · raw value'});
  $('exag').oninput=()=>{$('factor').textContent=fa(Number($('exag').value));Plotly.relayout('plot',{'scene.aspectratio.z':.075*Number($('exag').value)})};
  $('reset').onclick=()=>Plotly.relayout('plot',{'scene.camera':camera});
  $('png').onclick=()=>Plotly.downloadImage('plot',{format:'png',filename:'mashhad-bedrock-3d',width:1800,height:1200,scale:1.5});
  window.BEDROCK_READY=true;
}
async function boot(){
  try{
    if(window.PRECOMPUTED_BEDROCK){await start(window.PRECOMPUTED_BEDROCK);return}
    const response=await fetch('../BedRock.geojson');
    if(!response.ok)throw Error('GeoJSON '+response.status);
    const text=await response.text();
    const worker=new Worker('worker.js',{type:'module'});
    worker.onmessage=async({data})=>{worker.terminate();if(data.error){$('status').textContent=data.error;$('status').dataset.state='error';return}await start(data.model)};
    worker.onerror=e=>{$('status').textContent=e.message;$('status').dataset.state='error'};
    worker.postMessage({base:location.origin,text});
  }catch(e){$('status').textContent=String(e);$('status').dataset.state='error'}
}
boot();

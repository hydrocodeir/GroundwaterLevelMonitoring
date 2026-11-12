/** Closed volume shells calculated by Pyodide, displayed with a shared camera.
 * Triangle edges are intentionally invisible. Only real polygon rims are drawn.
 */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const fmt = (v, d = 1) => Number.isFinite(v)?new Intl.NumberFormat('fa-IR', { maximumFractionDigits: d }).format(v):'—';
const yearFmt=v=>new Intl.NumberFormat('fa-IR',{useGrouping:false,maximumFractionDigits:0}).format(v);
function syReference(data){const m=data.metrics;return m.sy_mode==='spatial'?'CSV مکانی انتخاب‌شده':data.aquifer.name.includes('مشهد')&&Math.abs(m.sy-.06)<1e-8?'Water Supply (2025)':data.aquifer.name.includes('نیشابور')&&Math.abs(m.sy-.051)<1e-8?'ضریب ذخیرهٔ یزدانی و منصوریان؛ استفاده به‌جای Sy فرض مدل است':'مقدار انتخابی کاربر';}
const COLORS = { blue: [.06, .43, .78, .30], red: [.95, .25, .31, .19], green: [.10, .68, .36, .30] };

function createScene(canvas, data, equivalent, camera, layers, pixel = false, options = {}) {
  const gl = canvas.getContext('webgl', { antialias: true, alpha: !!options.transparent, preserveDrawingBuffer: true });
  if (!gl) throw new Error('نمای سه‌بعدی به WebGL نیاز دارد؛ شتاب‌دهی گرافیکی مرورگر را فعال کنید.');
  const overlay = document.createElement('canvas');
  overlay.className = 'aquifer3d-overlay'; overlay.setAttribute('aria-hidden', 'true');
  canvas.parentElement.append(overlay);
  const hud = overlay.getContext('2d');
  const mesh = data.volume_mesh;
  const shell = pixel ? data.pixel_water?.shell : equivalent ? mesh.water : mesh.geology;
  const coords = pixel && data.pixel_water ? data.pixel_water.vertices : mesh.vertices;
  const west = Math.min(...coords.map(p => p[0])), east = Math.max(...coords.map(p => p[0]));
  const south = Math.min(...coords.map(p => p[1])), north = Math.max(...coords.map(p => p[1]));
  const sx = 111320 * Math.cos((north + south) / 2 * Math.PI / 180);
  const span = Math.max((east - west) * sx, (north - south) * 111320);
  const elevations = coords.flatMap(p => equivalent ? [0, p[5] ?? 0, p[6] ?? 0] : p.slice(2, 5));
  const declineScale=clamp(Number(options.declineScale)||1,1,10);
  const displayPoint=(p,kind)=>kind==='red'&&Number.isFinite(p[3])?[p[0],p[1],p[3]+(p[2]-p[3])*declineScale]:p;
  if(declineScale>1)(shell?.red||[]).forEach(tri=>tri.forEach(p=>elevations.push(displayPoint(p,'red')[2])));
  const minZ = Math.min(...elevations), maxZ = Math.max(...elevations);
  const verticalScale = (equivalent ? .48 : .40) / Math.max(1, maxZ - minZ);
  const normal = ([lon, lat, z]) => [(lon - (west + east) / 2) * sx / span,
    (lat - (north + south) / 2) * 111320 / span, (z - (minZ + maxZ) / 2) * verticalScale];
  let width = 1, height = 1, ratio = 1, selected = null, projectedWells = [], lostContext = false;
  const buffers = [];
  const vertex = `attribute vec3 aPosition; attribute vec4 aColor;
    uniform vec3 uCamera; uniform vec2 uPan; uniform float uAspect; uniform float uPointSize;
    varying vec4 vColor;
    void main(){float c=cos(uCamera.x),s=sin(uCamera.x),p=uCamera.y;
      float x=aPosition.x*c-aPosition.y*s,d=aPosition.x*s+aPosition.y*c;
      float y=d*sin(p)+aPosition.z*cos(p),nearD=-d*cos(p)+aPosition.z*sin(p);
      gl_Position=vec4(x*uCamera.z/uAspect+uPan.x,y*uCamera.z+uPan.y,-nearD*.3,1.);
      gl_PointSize=uPointSize;vColor=aColor;}`;
  const fragment = `precision mediump float; varying vec4 vColor; uniform float uPoints;
    void main(){if(uPoints>.5&&distance(gl_PointCoord,vec2(.5))>.5)discard;gl_FragColor=vColor;}`;
  function shader(type, source) {
    const s = gl.createShader(type); gl.shaderSource(s, source); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  const program = gl.createProgram(), shaders = [shader(gl.VERTEX_SHADER, vertex), shader(gl.FRAGMENT_SHADER, fragment)];
  shaders.forEach(s => gl.attachShader(program, s)); gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
  const uniforms = Object.fromEntries(['uCamera', 'uPan', 'uAspect', 'uPointSize', 'uPoints'].map(k => [k, gl.getUniformLocation(program, k)]));
  const attributes = ['aPosition', 'aColor'].map(k => gl.getAttribLocation(program, k));
  function buffer(values, mode = gl.TRIANGLES) {
    const object = gl.createBuffer(); buffers.push(object); gl.bindBuffer(gl.ARRAY_BUFFER, object);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(values), gl.STATIC_DRAW);
    return { object, count: values.length / 7, mode };
  }
  const pack = (points, color) => points.flatMap(p => [...normal(p), ...color]);
  const floor = buffer((shell?.floor || []).flatMap(tri => pack(tri, equivalent ? [.55,.63,.70,.25] : [.60,.48,.32,.62])));
  const rim = buffer(pack(shell?.outlines || [], [.18,.32,.43,.42]), gl.LINES);
  const transparent = buffer([]);
  const faces = [];
  for (const kind of ['blue', 'red', 'green']) {
    for (const tri of shell?.[kind] || []) {
      const vertices = tri.map(p=>normal(displayPoint(p,kind)));
      const [a,b,c] = vertices;
      const u = b.map((v,i) => v-a[i]), v = c.map((w,i) => w-a[i]);
      const n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
      const shade = pixel ? .7 + .3*Math.abs(n[2])/(Math.hypot(...n)||1) : .9 + .1 * Math.abs(n[2]) / (Math.hypot(...n) || 1);
      const baseColor = pixel ? (kind==='blue'?[.13,.48,.74,1]:[.87,.37,.41,1]) : COLORS[kind];
      const color = baseColor.map((value,i) => i < 3 ? value * shade : value);
      faces.push({ kind, center: [0,1,2].map(i => (a[i]+b[i]+c[i])/3), values: vertices.flatMap(p => [...p,...color]) });
    }
  }
  const wells = equivalent ? [] : data.wells.points || [];
  const markers = buffer(pack(wells.map(w => [w.lon,w.lat,w.after]), [.08,.20,.28,1]), gl.POINTS);
  const wellLines = buffer(pack(wells.flatMap(w => [[w.lon,w.lat,w.before],[w.lon,w.lat,w.after]]), [.12,.22,.30,.7]), gl.LINES);
  function scale() { return 1.7 * Math.min(1, width / height) * camera.zoom; }
  function project(p) {
    const c = Math.cos(camera.yaw), s = Math.sin(camera.yaw), d = p[0]*s+p[1]*c, k = scale();
    return [width/2+(p[0]*c-p[1]*s)*k*height/2+camera.panX*width,
      height/2-(d*Math.sin(camera.pitch)+p[2]*Math.cos(camera.pitch))*k*height/2+camera.panY*height];
  }
  function draw(object, point = false) {
    gl.bindBuffer(gl.ARRAY_BUFFER, object.object);
    [3,4].forEach((size,i) => {
      gl.enableVertexAttribArray(attributes[i]); gl.vertexAttribPointer(attributes[i], size, gl.FLOAT, false, 28, i ? 12 : 0);
    });
    gl.uniform1f(uniforms.uPoints, point ? 1 : 0); gl.drawArrays(object.mode, 0, object.count);
  }
  function render() {
    hud.clearRect(0,0,width,height);
    hud.fillStyle = '#27465c'; hud.font = '12px Vazirmatn, Tahoma, sans-serif'; hud.textAlign = 'left';
    if (lostContext) { hud.fillText('نمای گرافیکی قطع شد؛ دوباره محاسبه کنید.',16,40); return; }
    gl.useProgram(program); gl.viewport(0,0,canvas.width,canvas.height);
    if(options.transparent)gl.clearColor(0,0,0,0);else gl.clearColor(.945,.962,.976,1);
    gl.depthMask(true); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!shell) { hud.fillText('Sy و کف معتبر برای ساخت حجم معادل آب لازم است.',16,48); return; }
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA,gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform3f(uniforms.uCamera,camera.yaw,camera.pitch,scale());
    gl.uniform2f(uniforms.uPan,camera.panX*2,-camera.panY*2); gl.uniform1f(uniforms.uAspect,width/height);
    gl.uniform1f(uniforms.uPointSize,6*ratio);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1,1);
    if (layers.bedrock) draw(floor);
    gl.disable(gl.POLYGON_OFFSET_FILL);
    // Sort all transparent triangles together, including actual boundary walls.
    // No walls are generated for internal mesh edges.
    const c = Math.cos(camera.yaw), s = Math.sin(camera.yaw), cp = Math.cos(camera.pitch), sp = Math.sin(camera.pitch);
    const depth = face => -(face.center[0]*s+face.center[1]*c)*cp+face.center[2]*sp;
    const visible = faces.filter(face => pixel?layers[face.kind]!==false:layers[face.kind]).sort((a,b) => depth(a)-depth(b));
    const packed = new Float32Array(visible.length * 21);
    visible.forEach((face,i) => packed.set(face.values,i*21));
    gl.bindBuffer(gl.ARRAY_BUFFER,transparent.object); gl.bufferData(gl.ARRAY_BUFFER,packed,gl.DYNAMIC_DRAW);
    transparent.count = packed.length / 7;
    gl.depthMask(pixel); draw(transparent); draw(rim);
    if (layers.wells && !equivalent) { gl.disable(gl.DEPTH_TEST); draw(wellLines); draw(markers,true); }
    gl.depthMask(true);
    hud.fillText(equivalent ? `ارتفاع معادل آب: ۰ تا ${fmt(maxZ)} متر` : `تراز: ${fmt(minZ)} تا ${fmt(maxZ)} متر MSL`,16,height-33);
    hud.fillText(`اغراق قائم: ${fmt(span*verticalScale)}×`,16,height-13);
    if(declineScale>1){hud.fillStyle='#b43e48';hud.fillText(`بزرگ‌نمایی ضخامت افت: ×${fmt(declineScale)} · حجم‌ها واقعی‌اند`,16,height-55);hud.fillStyle='#27465c';}
    if (pixel) hud.fillText(`ضلع سلول: ${fmt(data.pixel_water.side_m)} متر · برای جزئیات روی ستون کلیک کنید`,16,58,Math.max(100,width-30));
    if (!equivalent) {
      const change = data.metrics.mean_head_decline_m;
      hud.fillText(`میانگین ${change>=0?'افت':'افزایش'}: ${fmt(Math.abs(change),2)} متر`,16,58);
    }
    const origin = project([0,0,0]);
    for (const [name,p] of [['N',[0,1,0]],['E',[1,0,0]]]) {
      const q=project(p),dx=q[0]-origin[0],dy=q[1]-origin[1],n=Math.hypot(dx,dy)||1,x=width-52,y=48;
      hud.strokeStyle='#46677b';hud.beginPath();hud.moveTo(x,y);hud.lineTo(x+dx/n*25,y+dy/n*25);hud.stroke();hud.fillText(name,x+dx/n*34-4,y+dy/n*34+4);
    }
    projectedWells = wells.map(well => ({well,p:project(normal([well.lon,well.lat,well.after]))}));
    if (selected && layers.wells) {
      const text = pixel ? `باقی‌مانده ${fmt(selected.remaining_mcm,3)}؛ از دست‌رفته ${fmt(selected.lost_mcm,3)} میلیون مترمکعب`
        : `${selected.name} | مبنا ${fmt(selected.before)}، پایان ${fmt(selected.after)} | ${selected.before>=selected.after?'افت':'افزایش'} ${fmt(Math.abs(selected.before-selected.after))} متر`;
      const box=Math.min(width-20,hud.measureText(text).width+20);
      hud.fillStyle='rgba(255,255,255,.95)';hud.fillRect(10,10,box,31);hud.fillStyle='#183e56';hud.fillText(text,20,31,box-20);
    }
  }
  function resize() {
    const r=canvas.getBoundingClientRect();width=Math.max(1,r.width);height=Math.max(1,r.height);ratio=options.pixelRatio||Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);
    overlay.width=canvas.width;overlay.height=canvas.height;hud.setTransform(ratio,0,0,ratio,0,0);
  }
  function pick(event) {
    const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;
    const candidates = pixel ? (data.pixel_water?.cells || []).map(cell=>({well:cell,p:project(normal([cell.lon,cell.lat,cell.remaining_m+cell.lost_m*declineScale]))})) : projectedWells;
    const near=candidates.map(w=>({...w,d:Math.hypot(w.p[0]-x,w.p[1]-y)})).sort((a,b)=>a.d-b.d)[0];
    selected=near?.d<18?near.well:null;
    if(selected)options.onPick?.({kind:pixel?'cell':'well',value:selected});
  }
  function contextLost(e){e.preventDefault();lostContext=true;render();}
  canvas.addEventListener('webglcontextlost',contextLost);
  return { canvas, resize, render, pick, verticalExaggeration:span*verticalScale, recreate:scale=>createScene(canvas,data,equivalent,camera,layers,pixel,{...options,declineScale:scale}),
    dispose(release=false){
      canvas.removeEventListener('webglcontextlost',contextLost);
      buffers.forEach(b=>gl.deleteBuffer(b));shaders.forEach(s=>gl.deleteShader(s));gl.deleteProgram(program);
      gl.depthMask(true);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);overlay.remove();
      if(release)gl.getExtension('WEBGL_lose_context')?.loseContext();
    }
  };
}

/** Whole-aquifer totals. Equal footprints and a shared, linear volume scale. */
function createAggregateScene(canvas, data) {
  const ctx = canvas.getContext('2d');
  let width = 1, height = 1;
  const metrics = data.metrics;
  const totals = [
    { label: 'آب باقی‌مانده', value: metrics.drainable_after_mcm, colors: ['#287bb8','#206598','#589ccc'] },
    { label: 'آب از دست‌رفته', value: metrics.water_balance?.lost_mcm, colors: ['#ce5962','#ad434d','#e58d94'] },
  ];
  const valid = totals.every(item => Number.isFinite(item.value) && item.value >= 0);
  function resize() {
    const r = canvas.getBoundingClientRect(), ratio = Math.min(devicePixelRatio || 1, 2);
    width = Math.max(1,r.width); height = Math.max(1,r.height);
    canvas.width = Math.round(width*ratio); canvas.height = Math.round(height*ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0);
  }
  function render() {
    ctx.clearRect(0,0,width,height); ctx.fillStyle = '#fff'; ctx.fillRect(0,0,width,height);
    ctx.textAlign = 'center'; ctx.fillStyle = '#536b7b'; ctx.font = '12px Vazirmatn, Tahoma, sans-serif';
    if (!valid) { ctx.fillText('Sy و کف معتبر برای محاسبهٔ حجم لازم است.',width/2,height/2); return; }
    const left = width < 420 ? 64 : 72, right = width-25, base = height-72, top = 72;
    const plotHeight = Math.max(80,base-top), maximum = Math.max(...totals.map(item=>item.value),1);
    const step = 10 ** Math.floor(Math.log10(maximum));
    const limit = Math.ceil(maximum/step)*step;
    ctx.textAlign = 'left'; ctx.fillText('میلیون مترمکعب',16,26);
    for (let i=0;i<=4;i++) {
      const y=base-plotHeight*i/4;
      ctx.strokeStyle = i===0 ? '#a8bac7' : '#e9eff3'; ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
      ctx.textAlign='right';ctx.fillStyle='#627987';ctx.font='11px Vazirmatn, Tahoma, sans-serif';
      ctx.fillText(fmt(limit*i/4,limit<10?2:0),left-9,y+4);
    }
    function face(points,color) {
      ctx.fillStyle=color;ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();
    }
    const slot=(right-left)/2, bar=Math.min(100,slot*.57), depth=Math.min(18,bar*.2);
    totals.forEach((item,i)=>{
      // Remaining water appears on the right in the RTL layout.
      const x=left+slot*(1-i+.5)-bar/2-depth/2, h=plotHeight*item.value/limit, y=base-h;
      if(item.value>0) {
        face([[x,y],[x+bar,y],[x+bar,base],[x,base]],item.colors[0]);
        face([[x+bar,y],[x+bar+depth,y-depth],[x+bar+depth,base-depth],[x+bar,base]],item.colors[1]);
        face([[x,y],[x+depth,y-depth],[x+bar+depth,y-depth],[x+bar,y]],item.colors[2]);
      }
      ctx.textAlign='center';ctx.fillStyle=item.colors[1];ctx.font='bold 16px Vazirmatn, Tahoma, sans-serif';
      ctx.fillText(fmt(item.value,2),x+bar/2+depth/2,y-depth-13);
      ctx.font='12px Vazirmatn, Tahoma, sans-serif';ctx.fillStyle='#27465c';
      ctx.fillText(item.label,x+bar/2+depth/2,base+29);
    });
    ctx.fillStyle='#627987';ctx.font='11px Vazirmatn, Tahoma, sans-serif';ctx.textAlign='center';
    ctx.fillText('حجم کل آبخوان · مقیاس یکسان برای هر دو حجم',width/2,height-15);
  }
  return {canvas,resize,render,dispose(){ctx.clearRect(0,0,width,height);}};
}

/** Record an independent camera so exporting never moves the working view. */
export async function exportOrbitVideo({data,kind='geology',onProgress=()=>{},signal,scenario,sectionImage,title:customTitle='',declineScale=1}) {
  if (!globalThis.MediaRecorder || !HTMLCanvasElement.prototype.captureStream)
    throw new Error('این مرورگر خروجی ویدئو را پشتیبانی نمی‌کند؛ از نسخهٔ جدید Chrome یا Edge استفاده کنید.');
  if (kind==='pixels' && !data.pixel_water) throw new Error('برای فیلم ستون‌های آب، ابتدا Sy و کف معتبر وارد کنید.');
  const mimeType=['video/mp4;codecs=avc1.42001E','video/mp4','video/webm;codecs=vp8','video/webm'].find(type=>MediaRecorder.isTypeSupported(type));
  if (!mimeType) throw new Error('قالب ویدئویی سازگار در مرورگر پیدا نشد.');
  const stage=document.createElement('div');
  stage.style.cssText='position:fixed;left:-10000px;top:0;width:1280px;height:600px;pointer-events:none';
  const canvas=document.createElement('canvas');
  canvas.style.cssText='width:1280px;height:600px';stage.append(canvas);
  const output=document.createElement('canvas');output.width=1280;output.height=720;
  const ctx=output.getContext('2d'),camera={yaw:.6,pitch:.65,zoom:1.3,panX:0,panY:0};
  let scene,stream,recorder,stopped,recordError;
  const chunks=[];
  const stages=scenario|| (kind==='geology'?[{type:'orbit',kind,seconds:24,red:true,caption:'دور اول · افت روشن'},{type:'orbit',kind,seconds:24,red:false,caption:'دور دوم · افت خاموش'}]:[{type:'orbit',kind,seconds:24,red:true,caption:'چرخش ۳۶۰ درجه'}]);
  if(!stages.length||stages.length>12||stages.some(s=>!['orbit','hold','view','section'].includes(s.type)||!Number.isFinite(s.seconds)||s.seconds<2||s.seconds>60))throw new Error('سناریو باید ۱ تا ۱۲ مرحله، هر مرحله ۲ تا ۶۰ ثانیه داشته باشد.');
  if(stages.some(s=>s.kind==='pixels')&&!data.pixel_water)throw new Error('مدل معادل آب برای این سناریو موجود نیست.');
  if(stages.some(s=>s.type==='section')&&!sectionImage)throw new Error('ابتدا مقطع را محاسبه کنید.');
  const totalSeconds=stages.reduce((sum,s)=>sum+s.seconds,0);
  if(totalSeconds>300)throw new Error('مدت کل سناریو حداکثر ۵ دقیقه است.');
  function check(){if(signal?.aborted)throw new DOMException('ساخت ویدئو لغو شد.','AbortError');if(recordError)throw recordError;}
  try {
    document.body.append(stage);
    check();await document.fonts.ready;check();
    const videoLayers={bedrock:true,wells:true,blue:true,red:true,green:true};
    let stageIndex=-1,startView={...camera},activeKind=kind;
    const draw=t=>{
      let elapsed=t*totalSeconds,index=0;
      while(index<stages.length-1&&elapsed>=stages[index].seconds){elapsed-=stages[index].seconds;index++;}
      const step=stages[index],phase=Math.min(1,elapsed/step.seconds);
      if(index!==stageIndex){
        stageIndex=index;startView={...camera};activeKind=step.kind==='pixels'?'pixels':'geology';
        if(step.view?.layers)Object.keys(videoLayers).forEach(k=>{if(typeof step.view.layers[k]==='boolean')videoLayers[k]=step.view.layers[k];});
        scene?.dispose();scene=createScene(canvas,data,activeKind==='pixels',camera,videoLayers,activeKind==='pixels',{declineScale:step.view?.declineScale||declineScale});scene.resize();
      }
      const eased=phase*phase*(3-2*phase);
      videoLayers.red=step.red!==false;
      if(step.type==='orbit'){camera.yaw=startView.yaw+Math.PI*2*eased;camera.pitch=startView.pitch+.18*Math.sin(Math.PI*2*eased);}
      if(step.type==='view'&&step.view?.camera){Object.keys(camera).forEach(k=>{const value=step.view.camera[k];if(Number.isFinite(value)){const delta=k==='yaw'?((value-startView[k]+Math.PI)%(Math.PI*2)+Math.PI*2)%(Math.PI*2)-Math.PI:value-startView[k];camera[k]=startView[k]+delta*eased;}});camera.zoom=clamp(camera.zoom,.4,5);camera.pitch=clamp(camera.pitch,.1,Math.PI/2);}
      scene.render();ctx.fillStyle='#f1f6fa';ctx.fillRect(0,0,1280,720);
      if(step.type==='section'){ctx.drawImage(sectionImage,40,160,1200,480);}else{
        ctx.drawImage(canvas,0,82,1280,600);
        const hud=stage.querySelector('.aquifer3d-overlay');if(hud)ctx.drawImage(hud,0,82,1280,600);
      }
      const title=customTitle||(step.type==='section'?'برش مقطعی':activeKind==='pixels'?'آب باقی‌مانده و از دست‌رفته':'افت سطح آب نسبت به سنگ‌بستر');
      ctx.textAlign='right';ctx.fillStyle='#173e56';ctx.font='bold 25px Vazirmatn, Tahoma, sans-serif';
      ctx.fillText(`${data.aquifer.name} | ${title}`,1240,37,660);
      ctx.font='15px Vazirmatn, Tahoma, sans-serif';ctx.fillStyle='#536b7b';
      ctx.fillText(`شهریور ${yearFmt(Number(data.dates.before.slice(0,4)))} تا شهریور ${yearFmt(Number(data.dates.after.slice(0,4)))}`,1240,66);
      ctx.textAlign='left';ctx.fillText(String(step.caption||`مرحلهٔ ${fmt(index+1)}`).slice(0,100),35,66,500);
      ctx.fillText(`Sy ${data.metrics.sy_mode==='spatial'?'مکانی':fmt(data.metrics.sy,3)} · ${syReference(data)}`,35,38,470);
      const legend=step.type==='section'?[['#94754b','سنگ‌بستر'],['#bd7136','آب مبنا'],['#287bb8','آب پایان']]:activeKind==='pixels'?[['#287bb8','آب باقی‌مانده'],[videoLayers.red?'#ce5962':'#8295a0',videoLayers.red?'آب از دست‌رفته':'آب از دست‌رفته (خاموش)']]
        :[['#287bb8','باقی‌مانده از مبنا'],[videoLayers.red?'#ce5962':'#8295a0',videoLayers.red?'افت':'افت (خاموش)'],['#168044','افزایش']];
      legend.forEach(([color,label],i)=>{
        const x=1240-i*265;ctx.fillStyle=color;ctx.fillRect(x-15,695,13,13);
        ctx.textAlign='right';ctx.font='15px Vazirmatn, Tahoma, sans-serif';ctx.fillText(label,x-25,707);
      });
    };
    draw(0);stream=output.captureStream(30);
    recorder=new MediaRecorder(stream,{mimeType,videoBitsPerSecond:2200000});
    stopped=new Promise(resolve=>recorder.addEventListener('stop',resolve,{once:true}));
    recorder.addEventListener('dataavailable',event=>{if(event.data.size)chunks.push(event.data);});
    recorder.addEventListener('error',event=>{recordError=event.error||new Error('ذخیرهٔ ویدئو ناموفق بود.');});
    recorder.start(1000);
    const start=performance.now(),duration=totalSeconds*1000;let last=-1;
    while(true){
      await new Promise(requestAnimationFrame);check();
      const t=Math.min(1,(performance.now()-start)/duration);draw(t);
      const percent=Math.floor(t*100);if(percent!==last){onProgress(percent);last=percent;}
      if(t>=1)break;
    }
    recorder.stop();await stopped;check();
    // Flatten recorder chunks before download; avoid a long chain of blob parts.
    const bytes=await new Blob(chunks,{type:recorder.mimeType}).arrayBuffer();check();
    const blob=new Blob([bytes],{type:recorder.mimeType});
    if(!blob.size)throw new Error('فایل ویدئو خالی است؛ دوباره تلاش کنید.');
    return {blob,extension:recorder.mimeType.includes('mp4')?'mp4':'webm'};
  } finally {
    if(recorder && recorder.state!=='inactive'){recorder.stop();await stopped;}
    stream?.getTracks().forEach(track=>track.stop());scene?.dispose(true);stage.remove();
  }
}

export async function exportAquiferImage({data,view,layout='pair',width=1920,transparent=false,title=''}){
  if(!['geology','pixels','pair'].includes(layout)||![1920,3840].includes(width))throw new Error('تنظیمات تصویر معتبر نیست.');
  if(layout!=='geology'&&!data.pixel_water)throw new Error('برای خروجی آب، Sy و کف معتبر لازم است.');
  await document.fonts.ready;
  const height=width*9/16,output=document.createElement('canvas');output.width=width;output.height=height;
  const ctx=output.getContext('2d'),unit=width/1920;
  if(!transparent){ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);}
  ctx.save();ctx.scale(unit,unit);ctx.textAlign='right';ctx.fillStyle='#173e56';ctx.font='bold 32px Vazirmatn, Tahoma, sans-serif';
  ctx.fillText(title||`${data.aquifer.name} · سطح آب و تغییر ذخیره`,1875,48,1810);
  ctx.font='19px Vazirmatn, Tahoma, sans-serif';ctx.fillStyle='#536b7b';
  ctx.fillText(`شهریور ${yearFmt(Number(data.dates.before.slice(0,4)))} تا شهریور ${yearFmt(Number(data.dates.after.slice(0,4)))} · WY ${yearFmt(data.dates.before_water_year)} تا WY ${yearFmt(data.dates.after_water_year)}`,1875,80);ctx.restore();
  const kinds=layout==='pair'?['geology','pixels']:[layout],count=kinds.length;
  for(let i=0;i<count;i++){
    const stage=document.createElement('div'),canvas=document.createElement('canvas'),w=(width-60*unit)/count,h=height-240*unit;
    stage.style.cssText=`position:fixed;left:-10000px;top:0;width:${w}px;height:${h}px;pointer-events:none`;
    canvas.style.cssText=`width:${w}px;height:${h}px`;stage.append(canvas);document.body.append(stage);
    let scene;
    try{
      const pixel=kinds[i]==='pixels';
      scene=createScene(canvas,data,pixel,{...view.camera},{...view.layers,...(pixel?{blue:true,red:true,bedrock:true}:{})},pixel,{declineScale:view.declineScale||1,transparent,pixelRatio:1});scene.resize();scene.render();
      const x=30*unit+(count-1-i)*w,y=130*unit;ctx.drawImage(canvas,x,y,w,h);
      ctx.drawImage(stage.querySelector('.aquifer3d-overlay'),x,y,w,h);
      ctx.fillStyle='#173e56';ctx.font=`${22*unit}px Vazirmatn, Tahoma, sans-serif`;ctx.textAlign='center';ctx.fillText(pixel?'آب باقی‌مانده و از دست‌رفته':'افت سطح آب نسبت به سنگ‌بستر',x+w/2,118*unit);
    }finally{scene?.dispose(true);stage.remove();}
  }
  const metrics=data.metrics,sy=metrics.sy_mode==='spatial'?`Sy مکانی ${fmt(metrics.sy_min,3)}–${fmt(metrics.sy_max,3)}`:`Sy ثابت ${fmt(metrics.sy,3)}`;
  const sySource=syReference(data);
  const source={mashhad_msl:'MASHHAD_BEDROCK_MSL.csv',figure_s4:'عمق برآوردی شکل S4 و تراز زمین مرجع',uploaded:'فایل کف انتخاب‌شده',karat_scenario:'کف سناریویی کرات',schematic:'کف شماتیک'}[data.grid.bedrock_source]||data.grid.bedrock_source;
  ctx.save();ctx.scale(unit,unit);ctx.font='18px Vazirmatn, Tahoma, sans-serif';ctx.fillStyle='#536b7b';ctx.textAlign='right';
  ctx.fillText(`کف: ${source} · ${sy} · ضریب نمایش افت ×${fmt(view.declineScale||1)} · اعداد ذخیره با ضخامت واقعی`,1875,1020,1810);
  ctx.fillText(layout==='geology'?'آبی: باقی‌مانده از مبنا · قرمز: افت · سبز: افزایش':'ستون‌ها: آبی، آب باقی‌ماندهٔ پایان؛ قرمز، کاهش ذخیره در همان سلول',1875,1054,1810);ctx.restore();
  ctx.font=`${15*unit}px Vazirmatn, Tahoma, sans-serif`;ctx.textAlign='right';ctx.fillStyle='#536b7b';ctx.fillText(`منبع Sy: ${sySource}`,1875*unit,990*unit,1810*unit);
  const blob=await new Promise(resolve=>output.toBlob(resolve,'image/png'));
  if(!blob)throw new Error('ساخت تصویر ناموفق بود.');
  return {blob,dataUrl:output.toDataURL('image/png'),width,height};
}

export function mountAquiferScenes({beforeCanvas,afterCanvas,pixelCanvas,data,onCameraChange=()=>{}}) {
  if (!data.volume_mesh) throw new Error('دادهٔ حجم سه‌بعدی موجود نیست؛ صفحه را تازه کنید.');
  const initial={yaw:.6,pitch:.65,zoom:1,panX:0,panY:0},camera={...initial};
  const layers={bedrock:true,wells:true,blue:true,red:true,green:true};
  let pickHandler=()=>{};
  let declineScale=1;
  const pickOptions={onPick:item=>pickHandler(item)};
  const scenes=[];
  try { scenes.push(createScene(beforeCanvas,data,false,camera,layers,false,pickOptions)); scenes.push(createAggregateScene(afterCanvas,data)); }
  catch(error){scenes.forEach(scene=>scene.dispose());throw error;}
  if(pixelCanvas) {
    try { scenes.push(createScene(pixelCanvas,data,true,camera,{bedrock:true,wells:true},true,pickOptions)); }
    catch(error){scenes.forEach(scene=>scene.dispose());throw error;}
  }
  const interactive = [beforeCanvas,pixelCanvas].filter(Boolean);
  let frame=0,disposed=false,dragging=null,pinch=null,centroid=null,interactionMode='rotate';
  const touches=new Map();
  function requestPaint(){if(!disposed&&!frame)frame=requestAnimationFrame(()=>{frame=0;scenes.forEach(s=>{if(s.canvas.getClientRects().length)s.render();});});onCameraChange({...camera});}
  function down(e){
    if(![0,1,2].includes(e.button))return;
    e.preventDefault();
    e.currentTarget.focus({preventScroll:true});
    cancelAnimationFrame(transition);
    e.currentTarget.setPointerCapture?.(e.pointerId);touches.set(e.pointerId,[e.clientX,e.clientY]);
    if(touches.size===2){const [a,b]=[...touches.values()];pinch=Math.hypot(a[0]-b[0],a[1]-b[1]);centroid=[(a[0]+b[0])/2,(a[1]+b[1])/2];dragging=null;return;}
    dragging={id:e.pointerId,canvas:e.currentTarget,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,
      pan:interactionMode==='pan'||e.shiftKey||e.button!==0,pickable:e.button===0,moved:false};
  }
  function move(e){
    if(touches.has(e.pointerId))touches.set(e.pointerId,[e.clientX,e.clientY]);
    if(touches.size===2){const [a,b]=[...touches.values()],d=Math.hypot(a[0]-b[0],a[1]-b[1]),mid=[(a[0]+b[0])/2,(a[1]+b[1])/2],r=e.currentTarget.getBoundingClientRect();if(pinch>0)camera.zoom=clamp(camera.zoom*d/pinch,.4,5);if(centroid){camera.panX+=(mid[0]-centroid[0])/r.width;camera.panY+=(mid[1]-centroid[1])/r.height;}centroid=mid;pinch=d;requestPaint();return;}
    if(!dragging||dragging.id!==e.pointerId)return;
    const dx=e.clientX-dragging.x,dy=e.clientY-dragging.y;if(Math.hypot(e.clientX-dragging.startX,e.clientY-dragging.startY)>4)dragging.moved=true;
    if(dragging.pan){const r=e.currentTarget.getBoundingClientRect();camera.panX+=dx/r.width;camera.panY+=dy/r.height;}
    else{camera.yaw+=dx*.008;camera.pitch=clamp(camera.pitch+dy*.006,.1,Math.PI/2);}
    dragging.x=e.clientX;dragging.y=e.clientY;requestPaint();
  }
  function up(e){
    if(e.type==='pointerup'&&dragging?.id===e.pointerId&&dragging.pickable&&!dragging.moved)scenes.find(s=>s.canvas===e.currentTarget)?.pick(e);
    touches.delete(e.pointerId);pinch=null;centroid=null;dragging=null;requestPaint();
  }
  function wheel(e){cancelAnimationFrame(transition);e.preventDefault();camera.zoom=clamp(camera.zoom*Math.exp(-e.deltaY*.0012),.4,5);requestPaint();}
  function reset(e){cancelAnimationFrame(transition);e?.preventDefault();Object.assign(camera,initial);requestPaint();}
  function key(e){
    if(!['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();
    cancelAnimationFrame(transition);
    if(e.key==='0')return reset();if(['+','='].includes(e.key))camera.zoom=clamp(camera.zoom*1.2,.4,5);if(e.key==='-')camera.zoom=clamp(camera.zoom/1.2,.4,5);
    if(interactionMode==='pan'||e.shiftKey){if(e.key==='ArrowLeft')camera.panX-=.05;if(e.key==='ArrowRight')camera.panX+=.05;if(e.key==='ArrowUp')camera.panY-=.05;if(e.key==='ArrowDown')camera.panY+=.05;}
    else{if(e.key==='ArrowLeft')camera.yaw-=.12;if(e.key==='ArrowRight')camera.yaw+=.12;
    if(e.key==='ArrowUp')camera.pitch=clamp(camera.pitch+.12,.1,Math.PI/2);if(e.key==='ArrowDown')camera.pitch=clamp(camera.pitch-.12,.1,Math.PI/2);}requestPaint();
  }
  const events={pointerdown:down,pointermove:move,pointerup:up,pointercancel:up,lostpointercapture:up,wheel,dblclick:reset,keydown:key,contextmenu:e=>e.preventDefault()};
  interactive.forEach(canvas=>Object.entries(events).forEach(([name,fn])=>canvas.addEventListener(name,fn,{passive:false})));
  const observer=new ResizeObserver(()=>{scenes.forEach(s=>s.resize());requestPaint();});
  scenes.forEach(s=>{observer.observe(s.canvas);s.resize();});requestPaint();
  function cleanup(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();
    cancelAnimationFrame(transition);
    interactive.forEach(canvas=>Object.entries(events).forEach(([name,fn])=>canvas.removeEventListener(name,fn)));scenes.forEach(s=>s.dispose());}
  cleanup.verticalExaggeration=scenes[0].verticalExaggeration;cleanup.bedrockReal=data.grid.bedrock_real;
  cleanup.setLayer=(name,value)=>{if(name in layers)layers[name]=!!value;requestPaint();};
  cleanup.setInteractionMode=mode=>{interactionMode=mode==='pan'?'pan':'rotate';interactive.forEach(canvas=>{canvas.dataset.dragMode=interactionMode;});};
  cleanup.control=action=>{cancelAnimationFrame(transition);if(action==='reset')return reset();if(action==='in')camera.zoom=clamp(camera.zoom*1.2,.4,5);if(action==='out')camera.zoom=clamp(camera.zoom/1.2,.4,5);
    if(action==='top'){camera.yaw=0;camera.pitch=Math.PI/2;}requestPaint();};
  let recording=false;
  cleanup.exportVideo=async options=>{if(recording)throw new Error('یک فیلم در حال ساخت است؛ ابتدا آن را تمام یا لغو کنید.');recording=true;try{return await exportOrbitVideo({data,declineScale,...options});}finally{recording=false;}};
  cleanup.setPickHandler=handler=>{pickHandler=handler||(()=>{});};
  cleanup.setDeclineScale=value=>{declineScale=clamp(Number(value)||1,1,10);scenes.forEach((s,i)=>{if(s.recreate){s.dispose();scenes[i]=s.recreate(declineScale);scenes[i].resize();}});requestPaint();};
  cleanup.getView=()=>({camera:{...camera},layers:{...layers},declineScale});
  cleanup.exportImage=options=>exportAquiferImage({data,view:cleanup.getView(),...options});
  let transition=0;
  cleanup.applyView=(view,animate=true)=>{
    if(Number.isFinite(view.declineScale)&&view.declineScale!==declineScale)cleanup.setDeclineScale(view.declineScale);
    cancelAnimationFrame(transition);
    if(view.layers)Object.keys(layers).forEach(k=>{if(typeof view.layers[k]==='boolean')layers[k]=view.layers[k];});
    const from={...camera},target={...camera};
    Object.entries(view.camera||{}).forEach(([k,v])=>{if(k in camera&&Number.isFinite(v))target[k]=v;});
    target.zoom=clamp(target.zoom,.4,5);target.pitch=clamp(target.pitch,.1,Math.PI/2);
    target.yaw=from.yaw+((target.yaw-from.yaw+Math.PI)%(Math.PI*2)+Math.PI*2)%(Math.PI*2)-Math.PI;
    if(!animate||matchMedia('(prefers-reduced-motion: reduce)').matches){Object.assign(camera,target);requestPaint();return;}
    const start=performance.now();
    function step(now){if(disposed)return;const t=Math.min(1,(now-start)/700),u=t*t*(3-2*t);Object.keys(camera).forEach(k=>camera[k]=from[k]+(target[k]-from[k])*u);requestPaint();if(t<1)transition=requestAnimationFrame(step);}
    transition=requestAnimationFrame(step);
  };
  cleanup.addComparison=(a,b,mode='decline')=>{
    const added=[createScene(a,data,false,camera,{bedrock:true,wells:true,blue:true,red:true,green:true},false,pickOptions),createScene(b,data,mode==='storage',camera,{bedrock:true,wells:true,blue:true,red:mode==='storage',green:true},mode==='storage',pickOptions)];
    scenes.push(...added);interactive.push(a,b);
    [a,b].forEach(canvas=>{Object.entries(events).forEach(([name,fn])=>canvas.addEventListener(name,fn,{passive:false}));observer.observe(canvas);});
    cleanup.setInteractionMode(interactionMode);
    added.forEach(s=>s.resize());requestPaint();
    if(declineScale!==1)cleanup.setDeclineScale(declineScale);
    return ()=>{[a,b].forEach(canvas=>{observer.unobserve(canvas);Object.entries(events).forEach(([name,fn])=>canvas.removeEventListener(name,fn));interactive.splice(interactive.indexOf(canvas),1);const index=scenes.findIndex(s=>s.canvas===canvas);if(index>=0){scenes[index].dispose();scenes.splice(index,1);}});};
  };
  return cleanup;
}

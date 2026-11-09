(async()=>{
const d=window.MASHHAD_SURFACE||await(await fetch('surface-preview.json')).json();
const m=d.metadata,model=m.continuous_surface,fa=n=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1}).format(n);
document.getElementById('stats').innerHTML=`<span>نقاط خروجی: <b>${fa(m.record_count)}</b></span><span>عمق مرز: <b>${fa(model.boundary_depth_range_m[0])} تا ${fa(model.boundary_depth_range_m[1])} متر</b></span><span>بیشترین اختلاف با خطوط: <b>${fa(model.contour_check_max_abs_error_m)} متر</b></span><span>شبکهٔ خروجی: <b>۵۰۰ متر</b></span>`;
const names={nearest_baseline:'نزدیک‌ترین نمونه',idw_baseline:'IDW',linear_rbf:'RBF خطی',thin_plate:'اسپلاین صفحه‌نازک',thin_plate_damped_5km:'اسپلاین با کاهش تدریجی شیب، ۵ کیلومتر',thin_plate_damped_10km:'اسپلاین با کاهش تدریجی شیب، ۱۰ کیلومتر'};
document.getElementById('evaluation').innerHTML='<table><caption>مقایسهٔ خطای عمق بر حسب متر</caption><thead><tr><th>روش</th><th>حذف یک تراز (RMSE)</th><th>حذف حاشیه‌ها (RMSE)</th><th>میانگین دو معیار</th></tr></thead><tbody>'+model.assessment.scores.map(r=>`<tr${r.method===model.method?' style="font-weight:bold;background:#e8f5ef"':''}><td>${names[r.method]}${r.method===model.method?' — انتخاب‌شده':''}</td><td>${fa(r.mean_depth_level_rmse_m)}</td><td>${fa(r.mean_edge_rmse_m)}</td><td>${fa(r.selection_score_m)}</td></tr>`).join('')+'</tbody></table>';
const lx=[],ly=[],lz=[],bx=[],by=[];
d.source.forEach(line=>{line.forEach(p=>{lx.push(p[0]);ly.push(p[1]);lz.push(p[2])});lx.push(null);ly.push(null);lz.push(null)});
d.rings.forEach(poly=>poly.forEach(ring=>{ring.forEach(p=>{bx.push(p[0]);by.push(p[1])});bx.push(null);by.push(null)}));
const boundary=d.points.filter(p=>p[5].startsWith('boundary_')),palette='Viridis';
const common={paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Tahoma,Arial',color:'#16324a'}};
const config={responsive:true,displaylogo:false,toImageButtonOptions:{width:1500,height:1300,scale:1.5,filename:'mashhad-continuous-bedrock'}};
await Plotly.newPlot('depth',[
{type:'heatmap',x:d.surface.x,y:d.surface.y,z:d.depth_surface,colorscale:palette,zmin:0,zmax:Math.ceil(model.model_depth_range_m[1]/25)*25,zsmooth:false,hoverongaps:false,colorbar:{title:{text:'Depth<br>(m)',side:'top'},thickness:13,len:.74},hovertemplate:'Depth: %{z:.1f} m<extra>Continuous model</extra>'},
{type:'scattergl',mode:'lines',x:lx,y:ly,line:{color:'#355268',width:2.5},showlegend:false,hoverinfo:'skip'},
{type:'scattergl',mode:'lines',x:lx,y:ly,line:{color:'#ffffff',width:1.25},customdata:lz,name:'Source contours',hovertemplate:'Source depth: %{customdata} m<extra>BEDROC</extra>'},
{type:'scatter',mode:'lines',x:bx,y:by,line:{color:'#172c3f',width:2},name:'Aquifer boundary',hoverinfo:'skip'}
],{...common,title:{text:'Continuous bedrock depth · source contours',font:{size:15}},margin:{l:65,r:80,t:60,b:100},xaxis:{title:'Easting (km) · UTM 40N',constrain:'domain'},yaxis:{title:'Northing (km)',scaleanchor:'x',scaleratio:1},legend:{orientation:'h',y:-.18,font:{size:11}}},config);
await Plotly.newPlot('msl',[
{type:'surface',x:d.surface.x,y:d.surface.y,z:d.surface.z,colorscale:palette,cmin:m.bedrock_msl_range_m[0],cmax:m.bedrock_msl_range_m[1],connectgaps:false,colorbar:{title:{text:'Bedrock<br>MSL (m)',side:'top'},thickness:13,len:.74},showlegend:false,hovertemplate:'Bedrock: %{z:.1f} m<extra>EGM96</extra>'},
{type:'scatter3d',mode:'markers',x:boundary.map(p=>p[7]/1000),y:boundary.map(p=>p[8]/1000),z:boundary.map(p=>p[2]),marker:{size:2,color:boundary.map(p=>p[2]),colorscale:palette,cmin:m.bedrock_msl_range_m[0],cmax:m.bedrock_msl_range_m[1]},customdata:boundary.map(p=>[p[4],p[6]]),showlegend:false,hovertemplate:'Bedrock: %{z:.1f} m<br>Depth: %{customdata[0]:.1f} m<br>Distance to source: %{customdata[1]:.0f} m<extra>Boundary model</extra>'}
],{...common,title:{text:'Estimated bedrock elevation · EGM96',font:{size:15}},margin:{l:65,r:90,t:60,b:20},annotations:[{xref:'paper',yref:'paper',x:-.08,y:.5,text:'Bedrock MSL (m)',textangle:-90,showarrow:false,font:{size:12}}],scene:{xaxis:{title:'Easting (km)'},yaxis:{title:'Northing (km)'},zaxis:{title:{text:''}},aspectmode:'manual',aspectratio:{x:1,y:.86,z:.36},camera:{eye:{x:1.15,y:1.35,z:1.1}}}},config);
window.REPORT_READY=true;
})();

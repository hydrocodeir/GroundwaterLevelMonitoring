(async()=>{
const data=window.MASHHAD_MSL || await (await fetch('msl-preview.json')).json();
const m=data.metadata,fa=n=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:1}).format(n);
document.getElementById('stats').textContent=`${fa(m.record_count)} نقطه • ${fa(m.records_by_role.boundary_nearest_contour)} نقطهٔ مرزی • عمق منبع: ${fa(m.source_depth_range_m[0])} تا ${fa(m.source_depth_range_m[1])} متر • بیشترین فاصلهٔ مرز از خط: ${fa(m.boundary_nearest_distance_range_m[1]/1000)} کیلومتر`;
const colors='Viridis',boundary=data.points.filter(p=>p[5]==='boundary_nearest_contour');
const lx=[],ly=[],ld=[],bx=[],by=[];
data.source.forEach(line=>{line.forEach(p=>{lx.push(p[0]);ly.push(p[1]);ld.push(p[2])});lx.push(null);ly.push(null);ld.push(null)});
data.rings.forEach(poly=>poly.forEach(ring=>{ring.forEach(p=>{bx.push(p[0]);by.push(p[1])});bx.push(null);by.push(null)}));
const common={paper_bgcolor:'white',plot_bgcolor:'white',font:{family:'Tahoma,Arial',color:'#19354b'},margin:{l:65,r:40,t:60,b:65}};
const config={responsive:true,displaylogo:false,toImageButtonOptions:{width:1400,height:1400,scale:1.5,filename:'mashhad-bedrock-msl'}};
await Plotly.newPlot('map',[
{type:'scattergl',mode:'lines',x:lx,y:ly,line:{color:'#668da1',width:1.5},name:'Source contours',hoverinfo:'skip'},
{type:'scattergl',mode:'markers',x:lx,y:ly,marker:{size:3,color:ld,colorscale:colors,cmin:75,cmax:225,showscale:false},customdata:ld,hovertemplate:'Depth: %{customdata:.0f} m<extra>Source BEDROC</extra>',showlegend:false},
{type:'scatter',mode:'lines',x:bx,y:by,line:{color:'#182d3f',width:2},name:'Existing aquifer boundary',hoverinfo:'skip'},
{type:'scattergl',mode:'markers',x:boundary.map(p=>p[7]/1000),y:boundary.map(p=>p[8]/1000),customdata:boundary.map(p=>[p[4],p[6]]),marker:{size:4,color:boundary.map(p=>p[4]),colorscale:colors,cmin:75,cmax:225,colorbar:{title:{text:'Depth<br>(m)',side:'top'},thickness:12,len:.7}},name:'Nearest contour at boundary',hovertemplate:'Depth: %{customdata[0]:.0f} m<br>Distance to contour: %{customdata[1]:.0f} m<extra>Boundary estimate</extra>'}
],{...common,title:{text:'Boundary depths · nearest original contour',font:{size:15}},xaxis:{title:'Easting (km) · UTM 40N',constrain:'domain'},yaxis:{title:'Northing (km)',scaleanchor:'x',scaleratio:1},legend:{orientation:'h',y:-.2,font:{size:10}},margin:{l:65,r:80,t:70,b:110}},config);
const surface=data.surface;
await Plotly.newPlot('bedrock',[
{type:'surface',x:surface.x,y:surface.y,z:surface.z,colorscale:colors,cmin:m.bedrock_msl_range_m[0],cmax:m.bedrock_msl_range_m[1],connectgaps:false,colorbar:{title:{text:'Bedrock<br>MSL (m)',side:'top'},thickness:13,len:.72},name:'Estimated bedrock',hovertemplate:'E: %{x:.3f} km<br>N: %{y:.3f} km<br>Bedrock: %{z:.1f} m<extra>EGM96</extra>',showlegend:false},
{type:'scatter3d',mode:'markers',x:boundary.map(p=>p[7]/1000),y:boundary.map(p=>p[8]/1000),z:boundary.map(p=>p[2]),marker:{size:2,color:boundary.map(p=>p[2]),colorscale:colors,cmin:m.bedrock_msl_range_m[0],cmax:m.bedrock_msl_range_m[1],opacity:.9},name:'Boundary estimates',showlegend:false,hovertemplate:'Bedrock: %{z:.1f} m<extra>Nearest contour boundary</extra>'}
],{...common,title:{text:'Estimated bedrock elevation · EGM96',font:{size:15}},margin:{l:10,r:90,t:65,b:0},scene:{xaxis:{title:'Easting (km)'},yaxis:{title:'Northing (km)'},zaxis:{title:'Bedrock MSL (m)'},aspectmode:'manual',aspectratio:{x:1,y:.86,z:.36},camera:{eye:{x:1.1,y:1.3,z:1.05}}}},config);
window.REPORT_READY=true;
})();

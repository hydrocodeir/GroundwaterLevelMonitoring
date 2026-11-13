/** Keep failed imports from leaving the dashboard at its initial spinner. */
const version=new URL(import.meta.url).searchParams.get('v')||'1';
let finished=false,delayed=false;
function showFailure(error){
  const $=id=>document.getElementById(id);
  $('status3d').textContent='بارگذاری برنامه کامل نشد. دوباره تلاش کنید.';
  $('status3d').dataset.state='error';
  $('status3d').title=String(error?.message||error);
  $('a3Workspace').dataset.state='error';
  $('a3ResultState').dataset.state='error';
  $('a3ResultState').textContent='بارگذاری ناموفق';
  $('a3EmptyState').hidden=false;
  $('a3EmptyTitle').textContent='برنامه بارگذاری نشد';
  $('a3EmptyText').textContent='فایل‌های برنامه دریافت نشدند یا نسخه‌های آن‌ها با هم سازگار نیستند.';
  const retry=()=>location.reload();
  for(const id of ['build3d','a3EmptyAction']){const button=$(id);button.disabled=false;button.hidden=false;button.textContent='تلاش دوباره';button.onclick=retry;}
  console.error('Aquifer startup failed:',error);
}
const watchdog=setTimeout(()=>{if(!finished){delayed=true;showFailure(new Error('مهلت دریافت فایل‌های برنامه به پایان رسید.'));}},45000);
try{
  await import(`./aquifer3d.js?v=${encodeURIComponent(version)}`);
  if(delayed)document.getElementById('build3d').onclick=null;
  finished=true;clearTimeout(watchdog);
}catch(error){finished=true;clearTimeout(watchdog);showFailure(error);}

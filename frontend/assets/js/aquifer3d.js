const assetVersion = new URL(import.meta.url).searchParams.get('v') || 'storage-1';
const { mountAquiferScenes } = await import(`./aquifer3d-render.js?v=${encodeURIComponent(assetVersion)}`);
const { mountProfessionalTools } = await import(`./aquifer3d-tools.js?v=${encodeURIComponent(assetVersion)}`);
const { mountPlanMaps } = await import(`./aquifer3d-maps.js?v=${encodeURIComponent(assetVersion)}`);
const { mountQualityTools } = await import(`./aquifer3d-quality.js?v=${encodeURIComponent(assetVersion)}`);
const { mountWorkspace } = await import(`./aquifer3d-workspace.js?v=${encodeURIComponent(assetVersion)}`);
const { mountLifetimeTools } = await import(`./aquifer3d-lifetime.js?v=${encodeURIComponent(assetVersion)}`);
const { mountManagementTools } = await import(`./aquifer3d-management.js?v=${encodeURIComponent(assetVersion)}`);
const workspace = mountWorkspace();

const $ = (id) => document.getElementById(id);
const aquiferSelect = $("aquiferSelect3d");
const baselineSelect = $("baselineYear");
const syInput = $("syInput");
const syMode = $("syMode");
const syFile = $("syFile");
const karatThicknessInput = $("karatThicknessInput");
const karatThicknessField = $("karatThicknessField");
const bedrockInput = $("bedrockFile");
const pixelWidthInput = $('pixelWidthInput'),pixelHeightInput = $('pixelHeightInput');
const spatialMethodInput=$('spatialMethodInput'),spatialSmoothingInput=$('spatialSmoothingInput');
const buildButton = $("build3d");
const worker = new Worker(`/assets/js/aquifer3d-worker.js?v=${encodeURIComponent(assetVersion)}`, { type: "module" });
const pending = new Map();
const formatter = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const approximateFormatter = new Intl.NumberFormat("fa-IR", { maximumSignificantDigits: 2 });
let requestId = 0;
let sceneCleanup = null;
let toolsCleanup = null;
let mapsCleanup = null;
let qualityCleanup = null;
let managementCleanup = null;
let lifetimeCleanup = null;
let videoController = null;
let selectedSummary = null;
let selectionSequence = 0;
let catalog = [];
let appliedInputs = null;
let modelUpdating = false;

function captureInputs() {
  return {baselineYear:baselineSelect.value,syMode:syMode.value,sy:syInput.value,
    pixelWidth:pixelWidthInput.value,pixelHeight:pixelHeightInput.value,
    spatialMethod:spatialMethodInput.value,splineSmoothing:spatialSmoothingInput.value,
    qualityFile:$('qualityInputFile').files[0]||null,climateFile:$('climateInputFile').files[0]||null,subsidenceFile:$('subsidenceInputFile').files[0]||null,karatThickness:karatThicknessInput.value,bedrockFile:bedrockInput.files?.[0]||null,syFile:syFile.files?.[0]||null};
}

function discardInputs() {
  if (!appliedInputs || !sceneCleanup || modelUpdating || buildButton.disabled) return;
  selectionSequence++;
  baselineSelect.value=appliedInputs.baselineYear;syMode.value=appliedInputs.syMode;
  syInput.value=appliedInputs.sy;karatThicknessInput.value=appliedInputs.karatThickness;
  pixelWidthInput.value=appliedInputs.pixelWidth;pixelHeightInput.value=appliedInputs.pixelHeight;updateGridSummary();
  spatialMethodInput.value=appliedInputs.spatialMethod;spatialSmoothingInput.value=appliedInputs.splineSmoothing;updateSpatialControls();
  for (const [input,file] of [[bedrockInput,appliedInputs.bedrockFile],[syFile,appliedInputs.syFile],[$('qualityInputFile'),appliedInputs.qualityFile],[$('climateInputFile'),appliedInputs.climateFile],[$('subsidenceInputFile'),appliedInputs.subsidenceFile]]) {
    const transfer=new DataTransfer();if(file)transfer.items.add(file);input.files=transfer.files;
  }
  updateSyMode();updateKaratControls();saveInputs();
  setStatus('تنظیمات آخرین محاسبه برگردانده شد.','ready');
}

function format(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "نامشخص";
  return new Intl.NumberFormat("fa-IR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  }).format(Number(value));
}

function formatVolume(value, approximate) {
  return approximate ? approximateFormatter.format(value) : format(value, 1);
}

function setStatus(message, state = "loading") {
  const element = $("status3d");
  element.textContent = message;
  element.dataset.state = state;
  workspace.state(state, message);
}

function request(command, args = {}) {
  if (modelUpdating && !['analyze','prepare','catalog','urban_overlay'].includes(command)) {
    return Promise.reject(new Error('مدل در حال به‌روزرسانی است؛ پس از پایان محاسبه دوباره اجرا کنید.'));
  }
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, command, arguments: args });
  });
}

worker.onmessage = ({ data }) => {
  if (data.type === "progress") {
    setStatus(data.message);
    return;
  }
  const job = pending.get(data.id);
  if (!job) return;
  pending.delete(data.id);
  if (data.error) job.reject(new Error(data.error));
  else job.resolve(data.result);
};

worker.onerror = (event) => {
  const message = event.message || "اجرای محاسبات در مرورگر ناموفق بود.";
  for (const job of pending.values()) job.reject(new Error(message));
  pending.clear();
  setStatus(message, "error");
};

function storageKey(index) {
  return `aquifer3d:v1:${index}`;
}

function getSaved(index) {
  try { return JSON.parse(localStorage.getItem(storageKey(index)) || "{}"); }
  catch { return {}; }
}

function saveInputs() {
  const index = Number(aquiferSelect.value);
  if (!Number.isInteger(index)) return;
  try {
    localStorage.setItem(storageKey(index), JSON.stringify({
      baselineYear: baselineSelect.value,
      pixelWidth:pixelWidthInput.value,pixelHeight:pixelHeightInput.value,
      spatialMethod:spatialMethodInput.value,splineSmoothing:spatialSmoothingInput.value,
      sy: syInput.value,
      karatThickness: karatThicknessInput.value
    }));
  } catch { /* Browser storage may be disabled. */ }
}

function resetMetrics() {
  for (const id of ["areaMetric", "wellMetric", "declineMetric", "storageMetric",
                    "volumeBeforeMetric", "volumeAfterMetric"]) {
    $(id).textContent = "—";
  }
  $("volumeBeforeHelp").textContent = "برآورد سناریویی؛ نیازمند سنگ‌بستر";
  $("volumeAfterHelp").textContent = "برآورد سناریویی؛ نیازمند سنگ‌بستر";
  $("bedrockLegendLabel").textContent = "سنگ‌بستر وارد نشده";
  $("sourceNote").textContent = "مرز GeoJSON آبخوان و سطح آب از داده‌های همین سامانه گرفته می‌شوند. آبدهی ویژه و سنگ‌بستر باید برای آبخوان انتخابی با منبع محلی بررسی شوند.";
  for (const id of ["remainingHeight", "lostHeight", "gainedHeight"]) $(id).textContent = "—";
  $("saturatedCaption").textContent = "پس از محاسبه نمایش داده می‌شود.";
  $("waterCaption").textContent = "برای نمایش، ورودی‌ها را تنظیم و محاسبه کنید.";
  document.querySelectorAll('[data-camera]').forEach(button => { button.disabled = true; });
}

function clearScenes() {
  workspace.clear();
  lifetimeCleanup?.();lifetimeCleanup=null;
  managementCleanup?.();managementCleanup=null;
  qualityCleanup?.();qualityCleanup=null;
  mapsCleanup?.();mapsCleanup=null;
  toolsCleanup?.();toolsCleanup=null;
  videoController?.abort();
  document.querySelectorAll('[data-video-kind]').forEach(button=>{button.disabled=true;});
  if (sceneCleanup) { sceneCleanup(); sceneCleanup = null; }
  resetMetrics();
}

function updateSyMode() {
  const spatial = syMode.value === 'spatial';
  $('syConstantField').hidden = spatial;
  $('syFileField').hidden = !spatial;
  syInput.disabled = spatial;
}

function updateGridSummary(){
  $('pixelGridSummary').textContent=`${format(Number(pixelWidthInput.value),0)} × ${format(Number(pixelHeightInput.value),0)} متر`;
}
function updateSpatialControls(){
  $('spatialSmoothingField').hidden=spatialMethodInput.value!=='spline';
  $('spatialMethodSummary').textContent=({idw:'IDW',spline:'Spline',thiessen:'تیسن'}[spatialMethodInput.value]||'IDW')+' · کل آبخوان';
}

function invalidateResult() {
  selectionSequence++;
  buildButton.disabled = !selectedSummary?.years?.length;
  const draft=captureInputs();
  const unchanged=appliedInputs && Object.keys(draft).every(key=>draft[key]===appliedInputs[key]);
  setStatus(unchanged&&sceneCleanup?'ورودی‌ها با آخرین محاسبه یکسان‌اند.':'تنظیمات جدید هنوز اعمال نشده‌اند؛ نمودارها مربوط به آخرین محاسبه‌اند.',unchanged&&sceneCleanup?'ready':'dirty');
}

function isNeyshabur(item) {
  return item?.name?.replace(/\s/g, "") === "نیشابور";
}

function normalizedName(value) {
  return String(value || "").replace(/[\s_\-\u200c]/g, "");
}

function isKarat(item) {
  return normalizedName(item?.name) === "کرات";
}

function isMashhad(item) { return normalizedName(item?.name) === 'مشهد'; }

function updateKaratControls() {
  karatThicknessField.hidden = true;
}

async function selectAquifer() {
  const sequence = ++selectionSequence;
  if(aquiferSelect.value==='')return;
  const index = Number(aquiferSelect.value);
  if (!Number.isInteger(index)) return;
  selectedSummary = null;
  appliedInputs = null;
  bedrockInput.value = "";
  syFile.value = "";
  syInput.value='';for(const id of ['qualityInputFile','climateInputFile','subsidenceInputFile'])$(id).value='';
  syMode.value = 'constant';
  pixelWidthInput.value='4000';pixelHeightInput.value='4000';updateGridSummary();
  spatialMethodInput.value='idw';spatialSmoothingInput.value='0';updateSpatialControls();
  updateSyMode();
  updateKaratControls();
  buildButton.disabled = true;
  clearScenes();
  baselineSelect.replaceChildren(new Option("در حال بررسی سال‌های موجود…", ""));
  if (sceneCleanup) { sceneCleanup(); sceneCleanup = null; }
  setStatus("در حال بررسی داده‌های آبخوان…");
  try {
    const summary = await request("prepare", { feature_index: index });
    if (sequence !== selectionSequence) return;
    selectedSummary = summary;
    workspace.context(summary.name);
    const saved = getSaved(index);
    const endYear=new Intl.NumberFormat('fa-IR',{useGrouping:false}).format(summary.current_year);
    $('comparisonEnd').textContent=`انتهای مقایسه: شهریور ${endYear}`;
    $('comparisonIntro').textContent=`مقایسهٔ سطح آب و تغییر ذخیره بین شهریور مبنا و آخرین شهریور دارای حداقل سه پیزومتر: ${endYear}`;
    $('volumeAfterLabel').textContent=`حجم آب قابل زهکشی در شهریور ${endYear}`;
    $('karatThicknessLabel').textContent=`ضخامت اشباع فرضی کرات در شهریور ${endYear}`;
    $('aquifer3d-karat-thickness-help').textContent=`کف سناریویی از تمام ${format(summary.current_count,0)} چاه دارای داده در شهریور ${endYear} ساخته می‌شود. ضخامت و سقف عمق، فرض سناریو هستند.`;
    baselineSelect.replaceChildren();
    for (const item of summary.years) {
      const option = new Option(
        `شهریور ${item.year} · WY ${item.water_year} · ${item.common_wells} چاه مشترک`,
        String(item.year)
      );
      baselineSelect.add(option);
    }
    if (summary.years.some((item) => String(item.year) === saved.baselineYear)) {
      baselineSelect.value = saved.baselineYear;

    }
    for(const [field,key] of [[pixelWidthInput,'pixelWidth'],[pixelHeightInput,'pixelHeight']]){const v=Number(saved[key]);field.value=Number.isFinite(v)&&v>=1&&v<=1e6?String(v):'4000';}updateGridSummary();
    spatialMethodInput.value=['idw','spline','thiessen'].includes(saved.spatialMethod)?saved.spatialMethod:'idw';spatialSmoothingInput.value=Number.isFinite(Number(saved.splineSmoothing))&&Number(saved.splineSmoothing)>=0?String(saved.splineSmoothing):'0';updateSpatialControls();
    syInput.value='';karatThicknessInput.value='';updateKaratControls();
    $('aquifer3d-sy-help').textContent='مقدار دارای منبع خودتان یا فایل Sy مکانی را وارد کنید.';
    $('aquifer3d-bedrock-help').textContent='CSV با ستون‌های lon,lat,bedrock_msl؛ متر از سطح دریا. بدون فایل، فقط سطح آب نمایش داده می‌شود.';
    $("areaMetric").textContent = `${format(summary.area_km2, 0)} کیلومتر مربع`;
    $("coverageNote").textContent =
      `${formatter.format(summary.current_count)} پیزومتر در شهریور ${endYear} داده دارند. ` +
      `سال‌های مبنا فقط زمانی در فهرست هستند که دست‌کم سه پیزومتر مشترک با شهریور ${endYear} داشته باشند. ` +
      "سطح آب درون محدوده از همین پیزومترهای مشترک درون‌یابی می‌شود.";
    if (!summary.years.length) {
      setStatus("برای این آبخوان، آخرین شهریور و سال‌های پیشین پیزومتر مشترک کافی ندارند.", "error");
      return;
    }
    buildButton.disabled = false;
    setStatus('داده‌های تکمیلی را انتخاب کنید یا فقط با پیزومترها ادامه دهید.','dirty');
    workspace.settings(true);
  } catch (error) {
    if (sequence === selectionSequence) setStatus(error.message, "error");
  }
}

function updateSourceNote(data){
  $('sourceNote').textContent='مرز موجود آبخوان و مشاهدات پیزومترها مبنا هستند. '+
    (data.input_files?.bedrock?'سنگ‌بستر: '+data.input_files.bedrock+'. ':'سنگ‌بستر وارد نشده؛ شکل فقط سطوح آب را نشان می‌دهد. ')+
    (data.metrics.sy_mode==='spatial'?'Sy: '+data.input_files.sy+'. ':data.metrics.sy!==null?'Sy واردشده: '+format(data.metrics.sy,3)+'. ':'Sy وارد نشده. ')+
    'کیفیت، اقلیم و فرونشست فقط از فایل انتخابی شما خوانده می‌شوند.';
}

function updateMetrics(data) {
  const { aquifer, wells, metrics } = data;
  $("areaMetric").textContent = `${format(aquifer.area_km2, 0)} کیلومتر مربع`;
  $("wellMetric").textContent = `${formatter.format(wells.common)} چاه مشترک`;
  const decline = metrics.mean_head_decline_m;
  $("declineMetric").textContent = `${decline >= 0 ? "افت" : "افزایش"} ${format(Math.abs(decline), 1)} متر`;
  const figureEstimate = data.grid.bedrock_source === "figure_s4";
  const karatScenario = data.grid.bedrock_source === "karat_scenario";
  const approximate = figureEstimate || karatScenario;
  $("storageMetric").textContent = metrics.storage_change_mcm === null
    ? "نیازمند Sy"
    : `${metrics.storage_change_mcm < 0 ? "کاهش" : "افزایش"} ${approximate ? "حدود " : ""}${formatVolume(Math.abs(metrics.storage_change_mcm), approximate)} میلیون مترمکعب`;
  $("volumeBeforeMetric").textContent = metrics.drainable_before_mcm === null
    ? (metrics.sy_mode === 'constant' && metrics.sy === null ? "نیازمند Sy" : "سنگ‌بستر نامشخص")
    : `${approximate ? "حدود " : ""}${formatVolume(metrics.drainable_before_mcm, approximate)} میلیون مترمکعب`;
  $("volumeAfterMetric").textContent = metrics.drainable_after_mcm === null
    ? (metrics.sy_mode === 'constant' && metrics.sy === null ? "نیازمند Sy" : "سنگ‌بستر نامشخص")
    : `${approximate ? "حدود " : ""}${formatVolume(metrics.drainable_after_mcm, approximate)} میلیون مترمکعب`;
  $("volumeBeforeHelp").textContent = figureEstimate
      ? "برآورد شکل S4 با کف کم‌عمقِ فرضی در مرز و Sy فرضی"
      : karatScenario
      ? "فقط سناریو: کف فرضی با سقف عمق ۳۰۰ متر و Sy انتخابی"
      : ["uploaded", "mashhad_msl"].includes(data.grid.bedrock_source)
        ? "برآورد سناریویی از CSV و Sy انتخابی"
        : "برآورد سناریویی؛ نیازمند سنگ‌بستر";
  $("volumeAfterHelp").textContent = $("volumeBeforeHelp").textContent;
  $("bedrockLegendLabel").textContent = figureEstimate
    ? "کف برآوردی S4 با مرز کم‌عمقِ فرضی"
    : karatScenario
      ? "کف فرضی کرات؛ حداکثر ۳۰۰ متر زیر زمین"
      : data.grid.bedrock_source === "mashhad_msl" ? "کف مشهد از فایل MSL" : data.grid.bedrock_source === "uploaded" ? "سنگ‌بستر دادهٔ بارگذاری‌شده" : "سنگ‌بستر وارد نشده";
  const sensitivity = metrics.sensitivity_20m;
  const sensitivityNote = approximate && sensitivity
    ? `سناریوی حساسیت با ۲۰ متر کاهش یا افزایش ${karatScenario ? "ضخامت اشباع فرضی، با حفظ سقف ۳۰۰ متری عمق کف" : "عمق اولیهٔ شکل، با اعمال دوبارهٔ گذار هموار و ثابت‌ماندن عمق ۵ متری مرز و حداقل عمق‌های مبتنی بر چاه‌ها"}: حجم سال مبنا حدود ${formatVolume(sensitivity.before_minus_mcm, true)} تا ${formatVolume(sensitivity.before_plus_mcm, true)} و حجم شهریور ${data.dates.after.slice(0,4)} حدود ${formatVolume(sensitivity.after_minus_mcm, true)} تا ${formatVolume(sensitivity.after_plus_mcm, true)} میلیون مترمکعب می‌شود. این بازهٔ اطمینان آماری نیست. `
    : "";
  const karatCapNote = karatScenario && Number.isFinite(metrics.karat_actual_max_bedrock_depth_m)
    ? `بیشترین عمق کف در سلول‌های ترسیم‌شده ${format(metrics.karat_actual_max_bedrock_depth_m, 1)} متر زیر زمین است` +
      (Number.isFinite(metrics.karat_capped_cell_count)
        ? ` و سقف ۳۰۰ متر در ${formatter.format(metrics.karat_capped_cell_count)} سلول${Number.isFinite(metrics.karat_capped_cell_pct) ? ` (${format(metrics.karat_capped_cell_pct, 1)}٪)` : ""} اعمال شده است. `
        : ". ")
    : "";
  const coverage = $("coverageNote");
  const neyshaburBoundaryNote = figureEstimate && metrics.neyshabur_boundary_assumption
    ? `عمق فرضی کف در مرز ${format(metrics.neyshabur_boundary_depth_m, 0)} متر است و نوار گذار حداکثر ${format(metrics.neyshabur_taper_width_m / 1000, 0)} کیلومتر عرض دارد. ` +
      (Number.isFinite(metrics.neyshabur_boundary_adjusted_cell_pct)
        ? `${format(metrics.neyshabur_boundary_adjusted_cell_pct, 0)}٪ سلول‌ها در این نوار اصلاح قرار دارند. ` : "") +
      (Number.isFinite(metrics.neyshabur_well_constraint_count)
        ? `برای ${formatter.format(metrics.neyshabur_well_constraint_count)} چاه در این نوار، کف در محل چاه دست‌کم ۵ متر پایین‌تر از عمیق‌ترین سطح آب ثبت‌شده در دورهٔ داده قرار داده شده است؛ اثر این شرط محلی است و فاصلهٔ اضافی ۵ متر فرض مدل است. ` : "")
    : "";
  coverage.textContent =
    `${formatter.format(wells.common)} چاه در هر دو شهریور داده دارند و ${formatter.format(wells.declined)} چاه افت نشان می‌دهند. ` +
    `${data.method}. میانگین عمق آب چاه‌های مشترک از ${format(wells.before_mean_depth_m, 1)} به ` +
    `${format(wells.after_mean_depth_m, 1)} متر رسیده است. ` +
    (figureEstimate
      ? neyshaburBoundaryNote + `${format(metrics.bedrock_coverage_pct, 0)}٪ سلول‌های مدل داخل پوش محدب نقاط اولیهٔ رقومی‌شده‌اند؛ بیرون آن عمق اولیه برون‌یابی شده است. نقاط مصنوعی مرز و سطح اصلاح‌شده در محاسبهٔ این پوشش وارد نشده‌اند. این درصد پوشش مستقیم اندازه‌گیری را نشان نمی‌دهد. حجم‌ها برآوردی، با دو رقم معنادار نمایش داده شده و به زمین‌مرجع‌سازی شکل و فرض مرزی حساس‌اند. ` +
        (metrics.dry_cell_count
          ? `در ${formatter.format(metrics.dry_cell_count)} سلول، سطح آب درون‌یابی‌شده پایین‌تر از کف برآوردی قرار گرفته و برای محاسبهٔ حجم، ضخامت اشباع صفر گرفته شده است؛ این نتیجه به فرض مرزی نیز وابسته است و مساحت خشک‌شدهٔ اندازه‌گیری‌شده را نشان نمی‌دهد. `
          : "") + sensitivityNote
      : karatScenario
        ? `کفِ فرضی از سطح آب درون‌یابی‌شده از همهٔ ${format(metrics.karat_current_wells, 0)} چاه شهریور ${data.dates.after.slice(0,4)} و ضخامت انتخابی ${format(metrics.karat_thickness_m, 0)} متر ساخته شده و در عمق ۳۰۰ متر زیر سطح زمین محلی محدود می‌شود. عدد ۶۵ متر گزارش UNECE ضخامت میانگین آبخوان است؛ به‌کاربردن آن برای پیش‌فرض ضخامت اشباع کنونی یک فرض سناریویی است. برای سال مبنا ممکن است چاه‌های مشترک کمتری وجود داشته باشند؛ حجم‌های مقایسه به همان چاه‌ها وابسته‌اند. ` + karatCapNote +
          (Number.isFinite(metrics.well_coverage_pct)
            ? `${format(metrics.well_coverage_pct, 0)}٪ سلول‌های مدل در پوش محدب چاه‌های مشترک‌اند؛ بیرون آن سطح آب برون‌یابی شده است. `
            : "") +
          `حجم‌ها با دو رقم معنادار فقط برای این فرض نمایش داده شده‌اند. ` + sensitivityNote
      : ["uploaded", "mashhad_msl"].includes(data.grid.bedrock_source)
        ? `پوشش محدب نقاط سنگ‌بستر ${format(metrics.bedrock_coverage_pct, 1)}٪ سلول‌های مدل است. `
        : "کف نمایش شماتیک است و حجم مطلق گزارش نمی‌شود. ") +
    `اغراق قائم برای خوانایی شکل: ${format(sceneCleanup?.verticalExaggeration, 1)} برابر.`;
  updateSourceNote(data);
  $('saturatedCaption').textContent = `کفِ نمایشی در مرز به سطح مبنا می‌رسد؛ این تغییر در نوار حدود ${format(data.volume_mesh.transition_m,0)} متری محو می‌شود و در اعداد ذخیره اعمال نشده است. آبی: باقی‌مانده از مبنا؛ قرمز: افت؛ سبز: افزایش. آبِ پایان = آبی + سبز. روی پیزومتر کلیک کنید تا تراز واقعی و افت آن را ببینید.`;
  if(data.volume_mesh.heads_only){$('saturatedCaption').textContent='سطح آب مبنا و پایان؛ سنگ‌بستر و حجم اشباع نمایش داده نمی‌شود.';}
  const heights = metrics.equivalent_water;
  if (heights) {
    $('remainingHeight').textContent = `${format(metrics.drainable_after_mcm, 2)} میلیون مترمکعب`;
    $('lostHeight').textContent = `${format(metrics.water_balance.lost_mcm, 2)} میلیون مترمکعب`;
    $('gainedHeight').textContent = `${format(metrics.water_balance.gained_mcm, 2)} میلیون مترمکعب`;
  }
  $('waterCaption').dataset.totals = heights
    ? 'آبی: کل ذخیرهٔ قابل زهکشی در پایان دوره، شامل افزایش‌های موضعی. قرمز: مجموع کاهش ذخیره در بخش‌های دارای افت نسبت به مبنا؛ این مقدار، مصرف یا برداشت ناخالص نیست. حجم‌ها با کف اصلی و Sy ثابت یا مکانی محاسبه شده‌اند. ارتفاع دو ستون متناسب با حجم است.'
    : 'برای نمایش حجم کل آب، Sy معتبر و تراز کف آبخوان لازم است.';
  showWaterView(document.querySelector('[data-water-view][aria-selected="true"]').dataset.waterView);
  document.querySelectorAll('[data-video-kind]').forEach(button=>{button.disabled=button.dataset.videoKind==='pixels'&&!data.pixel_water;});
  document.querySelectorAll('[data-camera]').forEach(button => { button.disabled = false; });
}

async function buildScene() {
  if (!selectedSummary || !baselineSelect.value || modelUpdating) return;
  const sequence = selectionSequence;
  const featureIndex = Number(aquiferSelect.value);
  const inputs=captureInputs();
  const frozenInputs=[aquiferSelect,baselineSelect,syMode,syInput,syFile,bedrockInput,karatThicknessInput,pixelWidthInput,pixelHeightInput,spatialMethodInput,spatialSmoothingInput,$('qualityInputFile'),$('climateInputFile'),$('subsidenceInputFile'),...document.querySelectorAll('[data-clear-layer]')].map(input=>[input,input.disabled]);
  modelUpdating=true;
  frozenInputs.forEach(([input])=>{input.disabled=true;});
  buildButton.disabled = true;
  setStatus("در حال درون‌یابی سطح آب و ساخت شکل سه‌بعدی…");
  try {
    const cellWidth=Number(inputs.pixelWidth),cellHeight=Number(inputs.pixelHeight);
    const splineSmoothing=Number(inputs.splineSmoothing);if(!Number.isFinite(splineSmoothing)||splineSmoothing<0)throw Error('هموارسازی Spline باید نامنفی باشد.');
    if(!Number.isFinite(cellWidth)||!Number.isFinite(cellHeight)||cellWidth<1||cellHeight<1||cellWidth>1e6||cellHeight>1e6)throw Error('طول و عرض پیکسل را بین ۱ و ۱٬۰۰۰٬۰۰۰ متر وارد کنید.');
    const spatial = inputs.syMode === 'spatial';
    const sy = spatial || inputs.sy.trim() === "" ? null : Number(inputs.sy);
    if (sy !== null && (!Number.isFinite(sy) || sy <= 0 || sy >= 1)) {
      throw new Error("آبدهی ویژه باید عددی بزرگ‌تر از صفر و کوچک‌تر از یک باشد.");
    }
    const file = inputs.bedrockFile;
    const bedrockText = file ? await file.text() : "";
    if (spatial && !inputs.syFile) throw new Error('فایل CSV آبدهی ویژه را انتخاب کنید.');
    const syText = spatial ? await inputs.syFile.text() : '';
    const karatThickness=null;
    if(sequence!==selectionSequence)return;
    const data = await request("analyze", {
      feature_index: featureIndex,
      baseline_year: Number(inputs.baselineYear),
      sy,
      cell_width_m:cellWidth,cell_height_m:cellHeight,
      spatial_method:inputs.spatialMethod,spline_smoothing:splineSmoothing,
      sy_text: syText,
      karat_thickness_m: karatThickness,
      bedrock_text: bedrockText
    });
    if (sequence !== selectionSequence || featureIndex !== Number(aquiferSelect.value)) return;
    try {
      const cities=await window.HydroCities.ready();
      data.urban_overlay=await request('urban_overlay',{features:cities.features});
      $('a3CitiesNote').textContent=`GHSL / JRC و OpenStreetMap · ${formatter.format(data.urban_overlay.length)} شهر در محدوده؛ پهنهٔ بافت شهری یا موقعیت نقطه‌ای، مطابق منبع`;
    } catch(error) {data.urban_overlay=[];$('a3CitiesNote').textContent=error.message;}
    if (sequence !== selectionSequence) return;
    modelUpdating=false;
    clearScenes();
    document.querySelector('#sceneGeology h3').firstChild.textContent=data.volume_mesh.heads_only?'سطح آب در دو زمان':'افت سطح آب نسبت به سنگ‌بستر';
    $('sceneGeologyTab').textContent=data.volume_mesh.heads_only?'سطح آب':'افت نسبت به سنگ‌بستر';
    data.input_files={bedrock:file?.name||null,sy:spatial?inputs.syFile.name:null,quality:inputs.qualityFile?.name||null,climate:inputs.climateFile?.name||null,subsidence:inputs.subsidenceFile?.name||null};
    if (sceneCleanup) sceneCleanup();
    sceneCleanup = mountAquiferScenes({
      beforeCanvas: $("beforeCanvas"), afterCanvas: $("afterCanvas"), pixelCanvas: $("pixelCanvas"), data,
      onCameraChange: camera => { $('zoomLabel').textContent = `${format(camera.zoom * 100, 0)}٪`; }
    });
    sceneCleanup.setInteractionMode(document.querySelector('[data-interaction][aria-pressed="true"]')?.dataset.interaction);
    mapsCleanup=mountPlanMaps({data,waterRoot:$('waterPercentMap'),parameterRoot:$('parameterMaps')});
    qualityCleanup=mountQualityTools({data,request,sourceFile:inputs.qualityFile});
    lifetimeCleanup=mountLifetimeTools({data,request,climateFile:inputs.climateFile});
    managementCleanup=mountManagementTools({data,request,featureIndex,sourceFile:inputs.subsidenceFile});
    document.querySelectorAll('[data-scene-layer]').forEach(input => sceneCleanup.setLayer(input.dataset.sceneLayer, input.checked));
    updateMetrics(data);
    toolsCleanup=mountProfessionalTools({data,scene:sceneCleanup,request,featureIndex});
    appliedInputs=inputs;
    workspace.result(data);
    saveInputs();
    setStatus(`مدل ${data.aquifer.name} برای ${data.dates.before} و ${data.dates.after} آماده است.${data.grid.bedrock_source === "figure_s4" ? " کف از برآورد شکل S4 با عمق مرزیِ فرضی ساخته شده است." : data.grid.bedrock_source === "karat_scenario" ? " کف کرات فقط یک سناریوی فرضی است." : ""}`, "ready");
  } catch (error) {
    if (sequence === selectionSequence) setStatus(error.message, "error");
  } finally {
    modelUpdating=false;
    frozenInputs.forEach(([input,disabled])=>{input.disabled=disabled;});
    if (sequence === selectionSequence) buildButton.disabled = false;
  }
}

async function start() {
  buildButton.disabled = true;
  setStatus("در حال راه‌اندازی تحلیل محلی…");
  try {
    catalog = await request("catalog");
    aquiferSelect.replaceChildren();
    for (const item of catalog) {
      const option = new Option(
        `${item.mahdoude} / ${item.name}${item.can_compare ? "" : " · دادهٔ ناکافی"}`,
        String(item.index)
      );
      option.disabled = !item.can_compare;
      aquiferSelect.add(option);
    }
    const query = new URLSearchParams(location.search);
    const requestedName = query.get("name");
    const requestedMahdoude = query.get("mahdoude");
    if(!requestedName){aquiferSelect.prepend(new Option('انتخاب آبخوان','',true,true));buildButton.disabled=true;setStatus('آبخوان را انتخاب کنید.','dirty');return;}
    const initial = catalog.find((item) => item.can_compare && item.name === requestedName &&
      (!requestedMahdoude || item.mahdoude === requestedMahdoude)) ||
      catalog.find((item) => item.can_compare && item.name === requestedName && requestedMahdoude &&
        (normalizedName(requestedMahdoude).includes(normalizedName(item.mahdoude)) ||
         normalizedName(item.mahdoude).includes(normalizedName(requestedMahdoude)))) ||
      catalog.find((item) => item.can_compare && item.name === requestedName) ||
      catalog.find((item) => item.can_compare && isNeyshabur(item)) ||
      catalog.find((item) => item.can_compare);
    if (!initial) throw new Error("فایل مرز آبخوان خالی است.");
    aquiferSelect.value = String(initial.index);
    await selectAquifer();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

aquiferSelect.addEventListener("change", selectAquifer);
buildButton.addEventListener("click", buildScene);
document.addEventListener('a3:user-layer-file',({detail})=>{
  if(!selectedSummary||detail.aquifer?.name!==selectedSummary.name||detail.aquifer?.mahdoude!==selectedSummary.mahdoude)return;
  const fields={quality:['qualityInputFile','qualityFile'],climate:['climateInputFile','climateFile'],subsidence:['subsidenceInputFile','subsidenceFile']},entry=fields[detail.kind];if(!entry)return;
  const transfer=new DataTransfer();if(detail.file)transfer.items.add(detail.file);$(entry[0]).files=transfer.files;
  if(appliedInputs)appliedInputs[entry[1]]=detail.file||null;
});
for(const id of ['qualityInputFile','climateInputFile','subsidenceInputFile'])$(id).addEventListener('change',invalidateResult);
document.addEventListener('a3:apply-inputs',()=>{if(!buildButton.disabled)buildScene();});
document.addEventListener('a3:discard-inputs',discardInputs);
baselineSelect.addEventListener("change", invalidateResult);
syInput.addEventListener("input", invalidateResult);
for(const input of [pixelWidthInput,pixelHeightInput])input.addEventListener('input',()=>{updateGridSummary();invalidateResult();});
spatialMethodInput.addEventListener('change',()=>{updateSpatialControls();invalidateResult();});spatialSmoothingInput.addEventListener('input',invalidateResult);
karatThicknessInput.addEventListener("input", invalidateResult);
bedrockInput.addEventListener("change", () => { updateKaratControls(); invalidateResult(); });
syMode.addEventListener('change', () => { updateSyMode(); invalidateResult(); });
syFile.addEventListener('change', invalidateResult);
function showWaterView(view) {
  const pixels = view === 'pixels';
  $('waterPixelPanel').hidden = !pixels;
  $('waterTotalPanel').hidden = view !== 'totals';
  $('waterMapPanel').hidden = view !== 'percent';
  document.querySelectorAll('[data-water-view]').forEach(button=>{
    const active=button.dataset.waterView===view;
    button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;
  });
  $('waterViewSubtitle').textContent = pixels
    ? 'ستون‌های مربعی روی محدودهٔ آبخوان؛ آبی در پایین، قرمز روی آن'
    : view==='percent'?'نقشهٔ درصد آب هر پیکسل نسبت به سال مبنا':'مجموع حجم در کل آبخوان، بر حسب میلیون مترمکعب';
  $('waterCaption').textContent = pixels
    ? 'هر ستون یک سلول مکانی است: آبی از صفر تا ضخامت معادل آب باقی‌مانده و قرمز بالای آن، معادل آب از دست‌رفتهٔ همان سلول. ارتفاع = ضخامت اشباع × Sy محل؛ حجم = ارتفاع × مساحت سلول. سلول‌های مرزی با پولیگون بریده می‌شوند. آب باقی‌مانده شامل افزایش‌های موضعی است؛ کاهش ذخیره معادل برداشت ناخالص نیست. برای چرخش بکشید، برای زوم از چرخ موس و برای جزئیات از کلیک استفاده کنید.'
    : view==='percent'?'درصدها از کف اصلی و Sy همین محاسبه ساخته می‌شوند؛ چرخ ماوس برای زوم، کشیدن نقشه برای جابجایی و کلیک برای مقدار دقیق.':$('waterCaption').dataset.totals || 'برای محاسبهٔ حجم، Sy و کف معتبر لازم است.';
  document.querySelector('.aquifer3d-scene-after [data-fullscreen]').dataset.fullscreen = pixels?'pixelCanvas':'afterCanvas';
  document.querySelector('[data-video-kind="pixels"]').hidden = !pixels;
  document.dispatchEvent(new CustomEvent('a3:water-view', { detail: view }));
}
document.querySelectorAll('[data-water-view]').forEach(button=>{
  button.addEventListener('click',()=>showWaterView(button.dataset.waterView));
  button.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const views=[...document.querySelectorAll('[data-water-view]')].map(b=>b.dataset.waterView),index=views.indexOf(button.dataset.waterView);
    const view=event.key==='Home'?views[0]:event.key==='End'?views.at(-1):views[(index+(event.key==='ArrowLeft'?1:views.length-1))%views.length];
    showWaterView(view);document.querySelector(`[data-water-view="${view}"]`).focus();
  });
});
document.querySelectorAll('[data-scene-layer]').forEach(input => input.addEventListener('change', () => sceneCleanup?.setLayer(input.dataset.sceneLayer, input.checked)));
document.querySelectorAll('[data-video-kind]').forEach(button=>button.addEventListener('click',async()=>{
  if(videoController){videoController.abort();return;}
  if(!sceneCleanup)return;
  const controller=new AbortController(),currentScene=sceneCleanup;
  videoController=controller;
  const original=button.textContent;
  const buttons=[...document.querySelectorAll('[data-video-kind]')];
  const previous=buttons.map(item=>item.disabled);
  buttons.forEach(item=>{item.disabled=item!==button;});
  try {
    const result=await currentScene.exportVideo({kind:button.dataset.videoKind,signal:controller.signal,
      onProgress:percent=>{button.textContent=`لغو ساخت فیلم · ${format(percent,0)}٪`;}});
    const url=URL.createObjectURL(result.blob),link=document.createElement('a');
    link.href=url;link.download=`${selectedSummary.name}-${button.dataset.videoKind}-360.${result.extension}`;
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  } catch(error){
    if(error.name!=='AbortError')setStatus(error.message,'error');
  } finally {
    videoController=null;button.textContent=original;
    if(sceneCleanup===currentScene)buttons.forEach((item,i)=>{item.disabled=previous[i];});
  }
}));
document.querySelectorAll('[data-camera]').forEach(button => {
  button.addEventListener('click', () => sceneCleanup?.control(button.dataset.camera));
});
document.querySelectorAll('[data-interaction]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('[data-interaction]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
  sceneCleanup?.setInteractionMode(button.dataset.interaction);
}));
document.querySelectorAll('[data-fullscreen]').forEach(button => {
  button.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await $(button.dataset.fullscreen).closest('article').requestFullscreen();
    } catch { setStatus('مرورگر امکان تمام‌صفحه را فراهم نکرد؛ می‌توانید از زوم استفاده کنید.', 'error'); }
  });
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/aquifer3d-sw.js", { updateViaCache: 'none' }).catch(() => {});
}

const inputTemplates={sy:'longitude,latitude,Sy',bedrock:'lon,lat,bedrock_msl',quality:'longitude,latitude,ec,sar,year_persian,month_persian',climate:'water_year,precip_mm,temp_c',subsidence:'longitude,latitude,cumulative_mm,start_year,end_year'};
document.querySelectorAll('[data-input-template]').forEach(button=>button.onclick=event=>{event.preventDefault();event.stopPropagation();const key=button.dataset.inputTemplate,link=document.createElement('a');if(key==='quality'){link.href='/assets/templates/quality-template.csv';link.download='quality-template.csv';link.click();return;}const url=URL.createObjectURL(new Blob([inputTemplates[key]+'\r\n'],{type:'text/csv;charset=utf-8'}));link.href=url;link.download=key+'-template.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);});
const cityToggle=$('a3CitiesToggle');
cityToggle.checked=window.HydroCities.enabled;
cityToggle.onchange=()=>window.HydroCities.setEnabled(cityToggle.checked);
window.HydroCities.subscribe(()=>{cityToggle.checked=window.HydroCities.enabled;});
start();

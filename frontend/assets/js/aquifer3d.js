import { mountAquiferScenes } from "./aquifer3d-render.js";

const $ = (id) => document.getElementById(id);
const aquiferSelect = $("aquiferSelect3d");
const baselineSelect = $("baselineYear");
const syInput = $("syInput");
const karatThicknessInput = $("karatThicknessInput");
const karatThicknessField = $("karatThicknessField");
const bedrockInput = $("bedrockFile");
const buildButton = $("build3d");
const worker = new Worker("/assets/js/aquifer3d-worker.js", { type: "module" });
const pending = new Map();
const formatter = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const approximateFormatter = new Intl.NumberFormat("fa-IR", { maximumSignificantDigits: 2 });
let requestId = 0;
let sceneCleanup = null;
let selectedSummary = null;
let selectionSequence = 0;
let catalog = [];

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
}

function request(command, args = {}) {
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
  $("bedrockLegendLabel").textContent = "سنگ‌بستر / بستر شماتیک";
  $("sourceNote").textContent = "مرز GeoJSON آبخوان و سطح آب از داده‌های همین سامانه گرفته می‌شوند. آبدهی ویژه و سنگ‌بستر باید برای آبخوان انتخابی با منبع محلی بررسی شوند.";
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

function updateKaratControls() {
  karatThicknessField.hidden = !isKarat(selectedSummary) || Boolean(bedrockInput.files?.length);
}

async function selectAquifer() {
  const sequence = ++selectionSequence;
  const index = Number(aquiferSelect.value);
  if (!Number.isInteger(index)) return;
  selectedSummary = null;
  bedrockInput.value = "";
  updateKaratControls();
  buildButton.disabled = true;
  resetMetrics();
  baselineSelect.replaceChildren(new Option("در حال بررسی سال‌های موجود…", ""));
  if (sceneCleanup) { sceneCleanup(); sceneCleanup = null; }
  setStatus("در حال بررسی داده‌های آبخوان…");
  try {
    const summary = await request("prepare", { feature_index: index });
    if (sequence !== selectionSequence) return;
    selectedSummary = summary;
    const saved = getSaved(index);
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
    } else if (isKarat(summary) && summary.years.some((item) => String(item.year) === "1389")) {
      baselineSelect.value = "1389";
    }
    syInput.value = saved.sy || (isNeyshabur(summary) ? "0.051" : isKarat(summary) ? "0.12" : "");
    const savedThickness = Number(saved.karatThickness);
    karatThicknessInput.value = saved.karatThickness && Number.isFinite(savedThickness) && savedThickness >= 20
      ? String(Math.min(savedThickness, 300)) : "65";
    updateKaratControls();
    $("aquifer3d-sy-help").textContent = isKarat(summary)
      ? "پیش‌فرض سناریویی ۰٫۱۲، میانهٔ دامنهٔ ۰٫۰۵ تا ۰٫۱۹ آبدهی ویژه در شکل ۷b مقالهٔ کرات است؛ قابل تغییر است."
      : isNeyshabur(summary)
        ? "۰٫۰۵۱ میانگین ضریب ذخیرهٔ گزارش‌شده برای نیشابور است؛ استفاده از آن به‌جای آبدهی ویژه فرض مدل است."
        : "مقدار باید ویژهٔ همین آبخوان و دارای منبع باشد.";
    $("aquifer3d-bedrock-help").textContent = isNeyshabur(summary)
      ? "برای نیشابور، عمق برآوردی شکل S4 با فرض کف کم‌عمق در مرز استفاده می‌شود. CSV شما با ستون‌های lon,lat,bedrock_msl جایگزین آن می‌شود."
      : isKarat(summary)
        ? "برای کرات، کف فرضی سناریو خودکار ترسیم می‌شود؛ دادهٔ اندازه‌گیری‌شدهٔ سنگ‌کف نیست. CSV شما با ستون‌های lon,lat,bedrock_msl جایگزین آن می‌شود."
        : "CSV با ستون‌های lon,lat,bedrock_msl؛ ارتفاع سنگ‌بستر به متر از سطح دریا.";
    $("areaMetric").textContent = `${format(summary.area_km2, 0)} کیلومتر مربع`;
    $("coverageNote").textContent =
      `${formatter.format(summary.current_count)} پیزومتر در شهریور ۱۴۰۴ داده دارند. ` +
      `سال‌های مبنا فقط زمانی در فهرست هستند که دست‌کم سه پیزومتر مشترک با شهریور ۱۴۰۴ داشته باشند. ` +
      "سطح آب درون محدوده از همین پیزومترهای مشترک درون‌یابی می‌شود.";
    if (!summary.years.length) {
      setStatus("برای این آبخوان، شهریور ۱۴۰۴ و سال‌های پیشین پیزومتر مشترک کافی ندارند.", "error");
      return;
    }
    buildButton.disabled = false;
    await buildScene();
  } catch (error) {
    if (sequence === selectionSequence) setStatus(error.message, "error");
  }
}

function updateSourceNote(data) {
  const note = $("sourceNote");
  note.replaceChildren();
  const intro = document.createTextNode(
    "مرز از Data/AQUIFER.geojson، عمق آب از Data/DATA.csv و تراز زمین چاه‌ها از Data/LOCATION.csv گرفته شده است. " +
    "تراز آب هر چاه = ارتفاع زمین − عمق اندازه‌گیری‌شده. "
  );
  note.append(intro);
  if (isNeyshabur(data.aquifer)) {
    note.append(document.createTextNode(
      "مقدار ۰٫۰۵۱ به‌عنوان میانگین ضریب ذخیرهٔ دشت نیشابور در یک پژوهش مبتنی بر آزمایش پمپاژ گزارش شده است؛ " +
      "به‌کاربردن آن به‌جای آبدهی ویژه (Sy) و یکنواخت فرض‌کردنش در تمام سلول‌ها دو فرض سناریویی این مدل هستند. "
    ));
    const source = document.createElement("a");
    source.href = "https://www.waterjournal.ir/article_70951.html";
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = "مقالهٔ اصلی ضریب ذخیرهٔ نیشابور ↗";
    note.append(source);
    note.append(document.createTextNode(
      " پژوهشی دیگر رسوبات آبرفتی آبخوان و سنگ‌بستر کم‌تراوای مارن، شیل و سنگ‌آهک را توصیف می‌کند؛ " +
      "این توصیف دربارهٔ جنس کف است. "
    ));
    const geology = document.createElement("a");
    geology.href = "https://link.springer.com/article/10.1186/s40068-025-00412-8";
    geology.target = "_blank";
    geology.rel = "noopener noreferrer";
    geology.textContent = "پژوهش زمین‌شناسی نیشابور ↗";
    note.append(geology);
  } else if (isKarat(data.aquifer)) {
    note.append(document.createTextNode(
      " برای کرات، ۰٫۱۲ فقط پیش‌فرض قابل‌تغییر سناریو است؛ از میانهٔ دامنهٔ آبدهی ویژهٔ ۰٫۰۵ تا ۰٫۱۹ در شکل ۷b پژوهش مدل‌سازی کرات انتخاب شده و به معنی Sy اندازه‌گیری‌شدهٔ یکنواخت در کل دشت نیست. "
    ));
    const syPaper = document.createElement("a");
    syPaper.href = "https://gnf.khu.ac.ir/article_4083_e1b90346c92331860b1391257a106bb1.pdf";
    syPaper.target = "_blank";
    syPaper.rel = "noopener noreferrer";
    syPaper.textContent = "پژوهش مدل‌سازی کرات، شکل ۷b ↗";
    note.append(syPaper);
  } else {
    note.append(document.createTextNode(
      "برای برآورد تغییر ذخیره باید آبدهی ویژهٔ مستند همین آبخوان وارد شود."
    ));
  }
  if (data.grid.bedrock_source === "figure_s4") {
    note.append(document.createTextNode(
      " عمق سنگ کف از خطوط هم‌عمق شکل S4 مقالهٔ Izady و همکاران به‌طور تقریبی رقومی‌سازی و با مرز آبخوان زمین‌مرجع شده است. " +
      "این نقاط، داده‌های اصلی ژئوالکتریک یا حفاری نیستند. برای فرض نزدیک‌بودن کف به سطح زمین در مرز آبخوان، عمق در همهٔ مرزهای بیرونی و داخلی ۵ متر فرض شده و حداکثر طی نوار ۵ کیلومتری با تابع هموار به عمق درون‌یابی‌شده از شکل می‌رسد. در موقعیت چاه‌های این نوار، حداقل عمق کف برابر بیشترین عمق آب ثبت‌شده در کل دورهٔ دادهٔ همان چاه به‌علاوهٔ ۵ متر فرض شده و اثر آن به‌صورت محلی کاهش می‌یابد؛ بنابراین گذار نزدیک بعضی چاه‌ها تندتر است. این ۵ متر فاصلهٔ اضافی، فرض حداقل ضخامت اشباع است و عمق سنگ‌کف اندازه‌گیری‌شده نیست. در فاصلهٔ ۵ کیلومتر و بیشتر، عمق برآوردی شکل حفظ می‌شود. عمق مرزی و عرض نوار گذار نیز فرض مدل‌اند و از مقاله یا اندازه‌گیری به دست نیامده‌اند. " +
      "تراز کف = ارتفاع زمین درون‌یابی‌شده از چاه‌های مشترک دو دوره − عمق اصلاح‌شده؛ " +
      "در محاسبهٔ ضخامت اشباع، ارتفاع زمین حذف می‌شود و حجم به عمق سنگ کف، عمق آب و Sy وابسته است. " +
      "نقشه شبکهٔ مختصات ندارد و مرز آن در بعضی قسمت‌ها با پلیگون سامانه چند کیلومتر اختلاف دارد. درون‌یابی و تطبیق تقریبی شکل، عدم‌قطعیت قابل‌توجهی به حجم‌ها اضافه می‌کند. "
    ));
    const figure = document.createElement("a");
    figure.href = "https://static-content.springer.com/esm/art%3A10.1007%2Fs10040-014-1219-9/MediaObjects/10040_2014_1219_MOESM1_ESM.pdf";
    figure.target = "_blank";
    figure.rel = "noopener noreferrer";
    figure.textContent = "شکل S4 در پیوست مقاله ↗";
    note.append(figure);
    note.append(document.createTextNode(" "));
    const download = document.createElement("a");
    download.href = "/data/NEYSHABUR_BEDROCK_DEPTH.csv";
    download.download = "NEYSHABUR_BEDROCK_DEPTH.csv";
    download.textContent = "دریافت CSV با اصلاح مرزی ↗";
    note.append(download);
    note.append(document.createTextNode(" "));
    const original = document.createElement("a");
    original.href = "/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv";
    original.download = "NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv";
    original.textContent = "نقاط اولیهٔ رقومی‌شده ↗";
    note.append(original);
    note.append(document.createTextNode(" "));
    const metadata = document.createElement("a");
    metadata.href = "/data/NEYSHABUR_BEDROCK_DEPTH.csv.metadata.json";
    metadata.target = "_blank";
    metadata.rel = "noopener noreferrer";
    metadata.textContent = "روش رقومی‌سازی و محدودیت‌ها ↗";
    note.append(metadata);
  } else if (data.grid.bedrock_source === "karat_scenario") {
    note.append(document.createTextNode(
      ` کف فرضی هر سلول، مقدار بالاتر از «تراز آب شهریور ۱۴۰۴ − ${format(data.metrics.karat_thickness_m, 0)} متر» و «تراز زمین محلی − ۳۰۰ متر» است. تراز آب و زمین از همهٔ ${format(data.metrics.karat_current_wells ?? 5, 0)} چاه دارای دادهٔ شهریور ۱۴۰۴ درون‌یابی می‌شوند. بنابراین عمق کف از سطح زمین در هیچ سلولی بیش از ۳۰۰ متر نیست و ضخامت نسبت به سطح آب پنج‌چاهیِ مرجع ممکن است کمتر از مقدار انتخابی شود. با تغییر سال مبنا این کف جابه‌جا نمی‌شود. این اعداد فرض سناریویی‌اند و از نقشه یا اندازه‌گیری مستقیم سنگ‌کف به دست نیامده‌اند. ` +
      "مقالهٔ مدل‌سازی کرات می‌گوید کف مدل آن‌ها با چاه‌های اکتشافی و لاگ حفاری ساخته شده، ولی نقشه یا نقاط کف را منتشر نکرده است. " +
      "گزارش UNECE میانگین ضخامت آبخوان را ۶۵ متر ذکر می‌کند؛ استفاده از آن برای پیش‌فرض ضخامت اشباع کنونی، تصمیم مدل است و از گزارش نتیجه نمی‌شود. " +
      "نمایش و حجم آب قابل زهکشی حاصل، صرفاً سناریوی قابل بررسی‌اند و نباید به‌عنوان بازسازی سنگ‌کف واقعی استفاده شوند. "
    ));
    const modelPaper = document.createElement("a");
    modelPaper.href = "https://gnf.khu.ac.ir/article_4083_e1b90346c92331860b1391257a106bb1.pdf";
    modelPaper.target = "_blank";
    modelPaper.rel = "noopener noreferrer";
    modelPaper.textContent = "مقالهٔ مدل‌سازی کرات ↗";
    note.append(modelPaper);
    note.append(document.createTextNode(" "));
    const assessment = document.createElement("a");
    assessment.href = "https://unece.org/fileadmin/DAM/env/water/publications/assessment/English/G_PartIV_Chapter3_En.pdf";
    assessment.target = "_blank";
    assessment.rel = "noopener noreferrer";
    assessment.textContent = "ارزیابی UNECE ↗";
    note.append(assessment);
  } else if (data.grid.bedrock_source === "uploaded") {
    note.append(document.createTextNode(
      " فایل ارتفاع سنگ‌بستر انتخابی شما فقط در مرورگر خوانده و با روش IDW درون‌یابی شده است."
    ));
  } else {
    note.append(document.createTextNode(
      " چون سطح سنگ‌بستر در داده‌های این آبخوان نیست، کف شکل صرفاً مرجع شماتیک است."
    ));
    if (normalizedName(data.aquifer.name) === "کرات") {
      note.append(document.createTextNode(
        " مقالهٔ مدل‌سازی کرات از دادهٔ چاه‌های اکتشافی و لاگ حفاری برای ساخت سنگ‌کف استفاده کرده، اما نقشه یا نقاط کف را منتشر نکرده است. " +
        "گزارش UNECE میانگین ضخامت آبخوان را ۶۵ متر ثبت کرده؛ این عدد عمق سنگ‌کف در هر نقطه را تعیین نمی‌کند و برای محاسبهٔ حجم مطلق به کار نرفته است. "
      ));
      const modelPaper = document.createElement("a");
      modelPaper.href = "https://gnf.khu.ac.ir/article_4083_e1b90346c92331860b1391257a106bb1.pdf";
      modelPaper.target = "_blank";
      modelPaper.rel = "noopener noreferrer";
      modelPaper.textContent = "مقالهٔ مدل‌سازی کرات ↗";
      note.append(modelPaper);
      note.append(document.createTextNode(" "));
      const assessment = document.createElement("a");
      assessment.href = "https://unece.org/fileadmin/DAM/env/water/publications/assessment/English/G_PartIV_Chapter3_En.pdf";
      assessment.target = "_blank";
      assessment.rel = "noopener noreferrer";
      assessment.textContent = "ارزیابی UNECE ↗";
      note.append(assessment);
    }
  }
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
    ? "سنگ‌بستر نامشخص"
    : `${approximate ? "حدود " : ""}${formatVolume(metrics.drainable_before_mcm, approximate)} میلیون مترمکعب`;
  $("volumeAfterMetric").textContent = metrics.drainable_after_mcm === null
    ? "سنگ‌بستر نامشخص"
    : `${approximate ? "حدود " : ""}${formatVolume(metrics.drainable_after_mcm, approximate)} میلیون مترمکعب`;
  $("volumeBeforeHelp").textContent = figureEstimate
      ? "برآورد شکل S4 با کف کم‌عمقِ فرضی در مرز و Sy فرضی"
      : karatScenario
      ? "فقط سناریو: کف فرضی با سقف عمق ۳۰۰ متر و Sy انتخابی"
      : data.grid.bedrock_source === "uploaded"
        ? "برآورد سناریویی از CSV و Sy انتخابی"
        : "برآورد سناریویی؛ نیازمند سنگ‌بستر";
  $("volumeAfterHelp").textContent = $("volumeBeforeHelp").textContent;
  $("bedrockLegendLabel").textContent = figureEstimate
    ? "کف برآوردی S4 با مرز کم‌عمقِ فرضی"
    : karatScenario
      ? "کف فرضی کرات؛ حداکثر ۳۰۰ متر زیر زمین"
      : data.grid.bedrock_source === "uploaded" ? "سنگ‌بستر دادهٔ بارگذاری‌شده" : "بستر شماتیک";
  const sensitivity = metrics.sensitivity_20m;
  const sensitivityNote = approximate && sensitivity
    ? `سناریوی حساسیت با ۲۰ متر کاهش یا افزایش ${karatScenario ? "ضخامت اشباع فرضی، با حفظ سقف ۳۰۰ متری عمق کف" : "عمق اولیهٔ شکل، با اعمال دوبارهٔ گذار هموار و ثابت‌ماندن عمق ۵ متری مرز و حداقل عمق‌های مبتنی بر چاه‌ها"}: حجم سال مبنا حدود ${formatVolume(sensitivity.before_minus_mcm, true)} تا ${formatVolume(sensitivity.before_plus_mcm, true)} و حجم شهریور ۱۴۰۴ حدود ${formatVolume(sensitivity.after_minus_mcm, true)} تا ${formatVolume(sensitivity.after_plus_mcm, true)} میلیون مترمکعب می‌شود. این بازهٔ اطمینان آماری نیست. `
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
        ? `کفِ فرضی از سطح آب درون‌یابی‌شده از همهٔ ${format(metrics.karat_current_wells ?? 5, 0)} چاه شهریور ۱۴۰۴ و ضخامت انتخابی ${format(metrics.karat_thickness_m, 0)} متر ساخته شده و در عمق ۳۰۰ متر زیر سطح زمین محلی محدود می‌شود. عدد ۶۵ متر گزارش UNECE ضخامت میانگین آبخوان است؛ به‌کاربردن آن برای پیش‌فرض ضخامت اشباع کنونی یک فرض سناریویی است. برای سال مبنا ممکن است چاه‌های مشترک کمتری وجود داشته باشند؛ حجم‌های مقایسه به همان چاه‌ها وابسته‌اند. ` + karatCapNote +
          (Number.isFinite(metrics.well_coverage_pct)
            ? `${format(metrics.well_coverage_pct, 0)}٪ سلول‌های مدل در پوش محدب چاه‌های مشترک‌اند؛ بیرون آن سطح آب برون‌یابی شده است. `
            : "") +
          `حجم‌ها با دو رقم معنادار فقط برای این فرض نمایش داده شده‌اند. ` + sensitivityNote
      : data.grid.bedrock_source === "uploaded"
        ? `پوشش محدب نقاط سنگ‌بستر ${format(metrics.bedrock_coverage_pct, 1)}٪ سلول‌های مدل است. `
        : "کف نمایش شماتیک است و حجم مطلق گزارش نمی‌شود. ") +
    `اغراق قائم برای خوانایی شکل: ${format(sceneCleanup?.verticalExaggeration, 1)} برابر.`;
  updateSourceNote(data);
  document.querySelector(".aquifer3d-scene-before h3").textContent = `شهریور ${data.dates.before.slice(0, 4)}`;
}

async function buildScene() {
  if (!selectedSummary || !baselineSelect.value) return;
  const sequence = selectionSequence;
  const featureIndex = Number(aquiferSelect.value);
  buildButton.disabled = true;
  setStatus("در حال درون‌یابی سطح آب و ساخت شکل سه‌بعدی…");
  try {
    const sy = syInput.value.trim() === "" ? null : Number(syInput.value);
    if (sy !== null && (!Number.isFinite(sy) || sy <= 0 || sy >= 1)) {
      throw new Error("آبدهی ویژه باید عددی بزرگ‌تر از صفر و کوچک‌تر از یک باشد.");
    }
    const file = bedrockInput.files?.[0];
    const bedrockText = file ? await file.text() : "";
    const karatThickness = isKarat(selectedSummary) && !file ? Number(karatThicknessInput.value) : null;
    if (karatThickness !== null &&
        (!Number.isFinite(karatThickness) || karatThicknessInput.value.trim() === "" ||
         karatThickness < 20 || karatThickness > 300)) {
      throw new Error("ضخامت اشباع فرضی کرات باید بین ۲۰ تا ۳۰۰ متر باشد. عمق کف از سطح زمین حداکثر ۳۰۰ متر است.");
    }
    const data = await request("analyze", {
      feature_index: featureIndex,
      baseline_year: Number(baselineSelect.value),
      sy,
      karat_thickness_m: karatThickness,
      bedrock_text: bedrockText
    });
    if (sequence !== selectionSequence || featureIndex !== Number(aquiferSelect.value)) return;
    if (sceneCleanup) sceneCleanup();
    sceneCleanup = mountAquiferScenes({
      beforeCanvas: $("beforeCanvas"), afterCanvas: $("afterCanvas"), data
    });
    updateMetrics(data);
    saveInputs();
    setStatus(`مدل ${data.aquifer.name} برای ${data.dates.before} و ${data.dates.after} آماده است.${data.grid.bedrock_source === "figure_s4" ? " کف از برآورد شکل S4 با عمق مرزیِ فرضی ساخته شده است." : data.grid.bedrock_source === "karat_scenario" ? " کف کرات فقط یک سناریوی فرضی است." : ""}`, "ready");
  } catch (error) {
    if (sequence === selectionSequence) setStatus(error.message, "error");
  } finally {
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
baselineSelect.addEventListener("change", saveInputs);
syInput.addEventListener("change", saveInputs);
karatThicknessInput.addEventListener("change", saveInputs);
bedrockInput.addEventListener("change", updateKaratControls);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/aquifer3d-sw.js").catch(() => {});
}

start();

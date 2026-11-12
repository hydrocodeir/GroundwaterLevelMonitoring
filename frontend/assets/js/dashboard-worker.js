import { loadBrowserPython, version } from "./pyodide-runtime.js";

let ready;
let analysisReady;
let queue = Promise.resolve();
const progress = message => self.postMessage({ type: "progress", message });

async function initialize() {
  progress("در حال آماده‌سازی…");
  const pyodide = await loadBrowserPython({
    packageBaseUrl: new URL('/assets/pyodide/packages/',self.location.href).href
  });
  pyodide.FS.mkdirTree("/app");
  pyodide.FS.mkdirTree("/Data");
  pyodide.FS.writeFile("/app/__init__.py", "");
  progress("در حال خواندن فهرست و سابقه پیزومترها…");
  await fetchFiles(pyodide, [
    ["/data/LOCATION.csv", "/Data/LOCATION.csv"],
    ["/data/DATA.csv", "/Data/DATA.csv"],
    ["/assets/js/dashboard_catalog.py", "/dashboard_catalog.py"]
  ]);
  await pyodide.runPythonAsync(`
import sys, json
sys.path.insert(0, "/")
from dashboard_catalog import DashboardCatalog
dashboard_catalog = DashboardCatalog()
`);
  return pyodide;
}

async function fetchFiles(pyodide, paths) {
  await Promise.all(paths.map(async ([url, destination]) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`دریافت داده ناموفق بود: ${url}`);
    pyodide.FS.writeFile(destination, new Uint8Array(await response.arrayBuffer()));
  }));
}

async function initializeAnalysis(pyodide) {
  progress("در حال دریافت ابزارهای محاسبه؛ این دریافت فقط بار اول لازم است…");
  const nativeFetch=self.fetch.bind(self);
  self.fetch=(resource,options)=>{
    const url=typeof resource==='string'?resource:resource?.url||String(resource);
    return nativeFetch(/\/libopenblas-[^/]+\.zip(?:\?|$)/.test(url)?'/runtime/quality-openblas':resource,options);
  };
  await pyodide.loadPackage(["numpy", "pandas", "scipy", "shapely", "pyproj"]);
  progress("در حال آماده‌سازی داده‌های تحلیل…");
  const paths = [
    ["/dashboard-compute.py", "/app/data_service.py"],
    ...["AQUIFER.geojson", "MAHDOUDE.geojson",
      "Monthly_Precipitation.csv", "Monthly_NDVI.csv", "Monthly_AET.csv",
      "Warm_Season_Irrigated_Area.csv"].map(name => [`/data/${name}`, `/Data/${name}`])
  ];
  await fetchFiles(pyodide, paths);
  await pyodide.runPythonAsync(`
import sys, json
sys.path.insert(0, "/")
from app.data_service import GroundwaterData
dashboard_service = GroundwaterData()
`);
}

self.onmessage = ({ data }) => {
  // A single interpreter must never receive overlapping calculations.
  queue = queue.then(async () => {
    try {
      ready ||= initialize().catch(error => { ready = null; throw error; });
      const pyodide = await ready;
      if (data.command === "preview") {
        pyodide.globals.set("catalog_group_id", data.arguments.group_id);
        const result = await pyodide.runPythonAsync(
          "json.dumps(dashboard_catalog.preview(catalog_group_id), ensure_ascii=False, allow_nan=False)"
        );
        self.postMessage({ id: data.id, result: JSON.parse(result) });
        return;
      }
      analysisReady ||= initializeAnalysis(pyodide).catch(error => { analysisReady = null; throw error; });
      await analysisReady;
      progress("در حال محاسبه روش‌های انتخاب‌شده…");
      pyodide.globals.set("dashboard_arguments", JSON.stringify(data.arguments));
      const operation=data.command==='comparison'?'comparison':'dashboard';
      const result = await pyodide.runPythonAsync(
        `json.dumps(dashboard_service.${operation}(**json.loads(dashboard_arguments)), ensure_ascii=False, allow_nan=False)`
      );
      self.postMessage({ id: data.id, result: JSON.parse(result) });
    } catch (error) {
      self.postMessage({ id: data.id, error: error?.message || String(error) });
    }
  });
};

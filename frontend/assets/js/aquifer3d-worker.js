import { loadBrowserPython, version } from "./pyodide-runtime.js";

let readyPromise;

function progress(message) {
  self.postMessage({ type: "progress", message });
}

async function initialize() {
  progress("در حال راه‌اندازی پایتون در مرورگر…");
  const pyodide = await loadBrowserPython({
    packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${version}/full/`
  });
  progress("در حال خواندن مرز آبخوان و داده‌های پیزومتر…");
  const paths = [
    "/data/AQUIFER.geojson",
    "/data/LOCATION.csv",
    "/data/DATA.csv",
    "/data/NEYSHABUR_BEDROCK_DEPTH.csv",
    "/data/MASHHAD_BEDROCK_MSL.csv",
    "/assets/js/aquifer3d_compute.py"
  ];
  const assetVersion = new URL(self.location.href).searchParams.get('v') || 'storage-1';
  const responses = await Promise.all(paths.map((path) => fetch(
    path.endsWith('.py') ? `${path}?v=${encodeURIComponent(assetVersion)}` : path,
    { cache: 'no-cache' }
  )));
  for (let index = 0; index < responses.length; index += 1) {
    if (!responses[index].ok) {
      throw new Error(`دریافت ${paths[index]} ناموفق بود (${responses[index].status}).`);
    }
  }
  const [geojson, locations, measurements, figureDepth, mashhadBedrock, python] = await Promise.all(
    responses.map((response) => response.text())
  );
  progress("در حال آماده‌سازی داده‌ها در Pyodide…");
  await pyodide.runPythonAsync(python);
  pyodide.globals.set("_geojson_text", geojson);
  pyodide.globals.set("_locations_text", locations);
  pyodide.globals.set("_measurements_text", measurements);
  pyodide.globals.set("_figure_depth_text", figureDepth);
  pyodide.globals.set("_mashhad_text", mashhadBedrock);
  const catalogJson = pyodide.runPython(
    "import json\njson.dumps(initialize(_geojson_text, _locations_text, _measurements_text, _figure_depth_text, _mashhad_text), ensure_ascii=False)"
  );
  pyodide.runPython("del _geojson_text, _locations_text, _measurements_text, _figure_depth_text, _mashhad_text");
  progress("داده‌ها آماده شدند.");
  return { pyodide, catalog: JSON.parse(catalogJson) };
}

self.onmessage = async ({ data }) => {
  const { id, command, arguments: args = {} } = data;
  try {
    readyPromise ||= initialize();
    const { pyodide, catalog } = await readyPromise;
    if (command === "catalog") {
      self.postMessage({ id, result: catalog });
      return;
    }
    if (command === "analyze") {
      progress("در حال آماده‌سازی حجم‌های سه‌بعدی…");
      await pyodide.loadPackage("shapely");
    }
    pyodide.globals.set("_command", command);
    pyodide.globals.set("_arguments", JSON.stringify(args));
    const result = JSON.parse(pyodide.runPython("call_json(_command, _arguments)"));
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({ id, error: error?.message || String(error) });
  }
};

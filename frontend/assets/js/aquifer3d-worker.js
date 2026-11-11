import { loadBrowserPython } from "./pyodide-runtime.js";

let readyPromise;

function progress(message) {
  self.postMessage({ type: "progress", message });
}

async function initialize() {
  progress("در حال راه‌اندازی پایتون در مرورگر…");
  const pyodide = await loadBrowserPython();
  progress("در حال خواندن مرز آبخوان و داده‌های پیزومتر…");
  const paths = [
    "/data/AQUIFER.geojson",
    "/data/LOCATION.csv",
    "/data/DATA.csv",
    "/data/NEYSHABUR_BEDROCK_DEPTH.csv",
    "/assets/js/aquifer3d_compute.py"
  ];
  const responses = await Promise.all(paths.map((path) => fetch(path)));
  for (let index = 0; index < responses.length; index += 1) {
    if (!responses[index].ok) {
      throw new Error(`دریافت ${paths[index]} ناموفق بود (${responses[index].status}).`);
    }
  }
  const [geojson, locations, measurements, figureDepth, python] = await Promise.all(
    responses.map((response) => response.text())
  );
  progress("در حال آماده‌سازی داده‌ها در Pyodide…");
  await pyodide.runPythonAsync(python);
  pyodide.globals.set("_geojson_text", geojson);
  pyodide.globals.set("_locations_text", locations);
  pyodide.globals.set("_measurements_text", measurements);
  pyodide.globals.set("_figure_depth_text", figureDepth);
  const catalogJson = pyodide.runPython(
    "import json\njson.dumps(initialize(_geojson_text, _locations_text, _measurements_text, _figure_depth_text), ensure_ascii=False)"
  );
  pyodide.runPython("del _geojson_text, _locations_text, _measurements_text, _figure_depth_text");
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
    pyodide.globals.set("_command", command);
    pyodide.globals.set("_arguments", JSON.stringify(args));
    const result = JSON.parse(pyodide.runPython("call_json(_command, _arguments)"));
    self.postMessage({ id, result });
  } catch (error) {
    self.postMessage({ id, error: error?.message || String(error) });
  }
};

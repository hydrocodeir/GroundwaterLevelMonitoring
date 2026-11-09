"""Save a CSV correction computed entirely by a local browser Pyodide worker.

Start the application's static server, then run this driver with a Python
environment containing Playwright and an installed Chrome browser.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    correction = (ROOT / "scripts/correct_neyshabur_bedrock.py").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.goto(args.url + "/aquifer-3d")
        page.locator('#status3d[data-state="ready"]').wait_for(timeout=90000)
        result = page.evaluate("""async ({base, correction}) => {
          const source = `self.onmessage = async ({data}) => {
            try {
              const {loadPyodide} = await import(data.base + '/assets/pyodide/pyodide.mjs');
              const py = await loadPyodide({indexURL: data.base + '/assets/pyodide/'});
              const paths = ['/assets/js/aquifer3d_compute.py', '/data/AQUIFER.geojson',
                '/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv',
                '/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv.metadata.json',
                '/data/LOCATION.csv', '/data/DATA.csv'];
              const texts = await Promise.all(paths.map(async path => {
                const response = await fetch(data.base + path);
                if (!response.ok) throw new Error(path + ': ' + response.status);
                return response.text();
              }));
              await py.runPythonAsync(texts[0]);
              await py.runPythonAsync(data.correction);
              py.globals.set('_boundary_geojson', texts[1]);
              py.globals.set('_boundary_source', texts[2]);
              py.globals.set('_boundary_source_metadata', texts[3]);
              py.globals.set('_boundary_locations', texts[4]);
              py.globals.set('_boundary_measurements', texts[5]);
              const output = await py.runPythonAsync(
                'json.dumps(correct_neyshabur_bedrock(_boundary_source, _boundary_geojson, _boundary_source_metadata, _boundary_locations, _boundary_measurements), ensure_ascii=False)');
              self.postMessage({output});
            } catch (error) { self.postMessage({error: error?.message || JSON.stringify(error, Object.getOwnPropertyNames(error))}); }
          };`;
          const url = URL.createObjectURL(new Blob([source], {type:'text/javascript'}));
          const worker = new Worker(url, {type:'module'});
          return await new Promise((resolve, reject) => {
            worker.onmessage = ({data}) => {
              worker.terminate(); URL.revokeObjectURL(url);
              if (data.error) reject(new Error(data.error));
              else resolve(JSON.parse(data.output));
            };
            worker.onerror = error => reject(new Error(error.message));
            worker.postMessage({base, correction});
          });
        }""", {"base": args.url.rstrip("/"), "correction": correction})
        browser.close()
    # Host-side operations are file I/O only; all geometry/data calculations
    # above run inside the browser's Pyodide worker.
    output = ROOT / "Data/NEYSHABUR_BEDROCK_DEPTH.csv"
    output.write_text(result["csv"], encoding="utf-8", newline="")
    output.with_suffix(output.suffix + ".metadata.json").write_text(
        json.dumps(result["metadata"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result["metadata"][key] for key in (
        "record_count", "records_by_role", "well_minimum_constraint_count", "inside_source_controls_adjusted",
        "inside_source_controls_unchanged", "depth_min_m", "depth_max_m")}, ensure_ascii=True))


if __name__ == "__main__":
    main()

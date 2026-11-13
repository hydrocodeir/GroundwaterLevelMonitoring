const CACHE_NAME = "aquifer3d-offline-v40";
const CORE_FILES = [
  "/assets/js/aquifer-spatial.py",
  "/assets/templates/quality-template.csv",
  "/assets/templates/quality-template-utm.csv",
  "/assets/templates/quality-example.csv",
  "/assets/templates/quality-guide.html",
  "/assets/js/aquifer-trend-options.py",
  "/assets/js/aquifer3d-flow.js",
  "/assets/css/aquifer3d-flow.css",
  "/assets/js/aquifer3d-bootstrap.js",
  "/assets/js/aquifer3d-lifetime.js",
  "/assets/js/aquifer-lifetime-compute.py",
  "/assets/css/aquifer3d-lifetime.css",
  "/",
  "/dashboard-compute.py",
  "/comparison",
  "/assets/js/comparison.js",
  "/assets/js/app.js",
  "/assets/js/dashboard-worker.js",
  "/assets/js/dashboard_catalog.py",
  "/assets/js/pyodide-runtime.js",
  "/runtime/python-stdlib",
  "/api/navigation-map",
  "/assets/js/htmx.min.js",
  "/assets/js/leaflet.js",
  "/assets/js/echarts.min.js",
  "/assets/js/echarts-extension-leaflet.js",
  "/assets/css/leaflet.css",
  "/data/MAHDOUDE.geojson",
  "/aquifer-3d",
  "/assets/css/app.css",
  "/assets/css/aquifer3d.css",
  "/assets/css/aquifer3d-workspace.css",
  "/assets/js/aquifer3d-workspace.js",
  "/assets/js/aquifer3d-layout.js",
  "/assets/js/aquifer3d-views.js",
  "/assets/js/map-cities.js",
  "/assets/js/dashboard-help.js",
  "/assets/css/workbench.css",
  "/assets/data/khorasan-razavi-urban.geojson",
  "/assets/js/aquifer3d-management.js",
  "/assets/js/aquifer-management-compute.py",
  "/assets/css/aquifer3d-management.css",
  "/assets/js/aquifer3d.js",
  "/assets/js/aquifer3d-render.js",
  "/assets/js/aquifer3d-tools.js",
  "/assets/js/aquifer3d-maps.js",
  "/assets/js/aquifer3d-quality.js",
  "/water-quality/compute.py",
  "/runtime/quality-openblas",
  "/assets/js/aquifer3d-worker.js",
  "/assets/js/aquifer3d_compute.py",
  "/assets/pyodide/pyodide.mjs",
  "/assets/pyodide/pyodide.asm.js",
  "/assets/pyodide/pyodide.asm.wasm",
  "/assets/pyodide/pyodide-lock.json",
  "/assets/fonts/vazirmatn-arabic-400.woff2",
  "/assets/fonts/vazirmatn-arabic-500.woff2",
  "/assets/fonts/vazirmatn-arabic-700.woff2",
  "/assets/fonts/vazirmatn-latin-400.woff2",
  "/assets/fonts/vazirmatn-latin-500.woff2",
  "/assets/fonts/vazirmatn-latin-700.woff2",
  "/assets/img/HydroCode.png",
  "/assets/img/favicon-32.png",
  "/assets/img/favicon-192.png",
  "/data/AQUIFER.geojson",
  "/data/LOCATION.csv",
  "/data/DATA.csv",
];

const LAZY_DATA_FILES=["/data/Monthly_Precipitation.csv", "/data/Monthly_NDVI.csv", "/data/Monthly_AET.csv", "/data/Warm_Season_Irrigated_Area.csv", "/subsidence/sources.json", "/water-quality/WaterQ.csv", "/water-quality/covariates.npy", "/water-quality/geology.geojson", "/water-quality/sources.json", "/data/NEYSHABUR_BEDROCK_DEPTH.csv", "/data/MASHHAD_BEDROCK_MSL.csv", "/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv", "/data/NEYSHABUR_BEDROCK_DEPTH.csv.metadata.json"];

function isPythonPackage(url) {
  return (url.origin === "https://cdn.jsdelivr.net"
    && /^\/pyodide\/v0\.29\.3\/full\/[^/]+\.whl$/.test(url.pathname))
    ||(url.origin===self.location.origin&&url.pathname.startsWith('/assets/pyodide/packages/')&&/\.(whl|zip)$/.test(url.pathname));
}

function isDashboardPartial(url) {
  return url.origin === self.location.origin
    && ["/partials/dashboard", "/partials/aquifers", "/api/navigation-map"].includes(url.pathname);
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.allSettled(CORE_FILES.map((path) => cache.add(path)));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    const current = await caches.open(CACHE_NAME);
    for (const name of names.filter(name => name.startsWith("aquifer3d-offline-") && name !== CACHE_NAME)) {
      const previous = await caches.open(name);
      for (const request of await previous.keys()) {
        const url = new URL(request.url);
        // Preserve visited dashboards and immutable scientific packages on upgrade.
        // Scripts come from the new precache; the old ZIP must never be requested.
        if (!isPythonPackage(url) && !isDashboardPartial(url)) continue;
        if (await current.match(request)) continue;
        const response = await previous.match(request);
        if (response?.ok) await current.put(request, response);
      }
      await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;
  const pythonPackage = isPythonPackage(url);
  const partial = isDashboardPartial(url);
  const subsidenceAsset=url.origin===self.location.origin&&url.pathname.startsWith('/subsidence/');
  if (!pythonPackage && !partial && !subsidenceAsset
      && (url.origin !== self.location.origin || !CORE_FILES.includes(url.pathname)&&!LAZY_DATA_FILES.includes(url.pathname))) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const key = partial ? event.request : new Request(url.origin + url.pathname);
    try {
      const response = await fetch(event.request);
      if (response.ok) event.waitUntil(cache.put(key, response.clone()));
      return response;
    } catch (error) {
      const cached = await cache.match(key);
      if (cached) return cached;
      throw error;
    }
  })());
});

const CACHE_NAME = "aquifer3d-offline-v13";
const CORE_FILES = [
  "/",
  "/dashboard-compute.py",
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
  "/data/Monthly_Precipitation.csv",
  "/data/Monthly_NDVI.csv",
  "/data/Monthly_AET.csv",
  "/data/Warm_Season_Irrigated_Area.csv",
  "/aquifer-3d",
  "/assets/css/app.css",
  "/assets/css/aquifer3d.css",
  "/assets/js/aquifer3d.js",
  "/assets/js/aquifer3d-render.js",
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
  "/data/NEYSHABUR_BEDROCK_DEPTH.csv",
  "/data/NEYSHABUR_BEDROCK_DEPTH_SOURCE.csv",
  "/data/NEYSHABUR_BEDROCK_DEPTH.csv.metadata.json"
];

function isPythonPackage(url) {
  return url.origin === "https://cdn.jsdelivr.net"
    && /^\/pyodide\/v0\.29\.3\/full\/[^/]+\.whl$/.test(url.pathname);
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
  if (!pythonPackage && !partial
      && (url.origin !== self.location.origin || !CORE_FILES.includes(url.pathname))) return;
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

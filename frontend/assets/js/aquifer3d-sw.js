const CACHE_NAME = "aquifer3d-offline-v6";
const CORE_FILES = [
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
  "/assets/pyodide/python_stdlib.zip",
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
    await Promise.all(names.filter((name) => name.startsWith("aquifer3d-offline-") &&
      name !== CACHE_NAME).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (!CORE_FILES.includes(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const key = new Request(url.origin + url.pathname);
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

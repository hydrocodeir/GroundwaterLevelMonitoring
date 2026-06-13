import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";

const copies = [
  ["node_modules/htmx.org/dist/htmx.min.js", "frontend/assets/js/htmx.min.js"],
  ["node_modules/echarts/dist/echarts.min.js", "frontend/assets/js/echarts.min.js"],
  ["node_modules/leaflet/dist/leaflet.js", "frontend/assets/js/leaflet.js"],
  ["node_modules/leaflet/dist/leaflet.css", "frontend/assets/css/leaflet.css"],
  ["node_modules/leaflet/dist/images/marker-icon.png", "frontend/assets/css/images/marker-icon.png"],
  ["node_modules/leaflet/dist/images/marker-icon-2x.png", "frontend/assets/css/images/marker-icon-2x.png"],
  ["node_modules/leaflet/dist/images/marker-shadow.png", "frontend/assets/css/images/marker-shadow.png"],
  ["node_modules/leaflet/dist/images/layers.png", "frontend/assets/css/images/layers.png"],
  ["node_modules/leaflet/dist/images/layers-2x.png", "frontend/assets/css/images/layers-2x.png"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-arabic-400-normal.woff2", "frontend/assets/fonts/vazirmatn-arabic-400.woff2"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-latin-400-normal.woff2", "frontend/assets/fonts/vazirmatn-latin-400.woff2"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-arabic-500-normal.woff2", "frontend/assets/fonts/vazirmatn-arabic-500.woff2"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-latin-500-normal.woff2", "frontend/assets/fonts/vazirmatn-latin-500.woff2"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-arabic-700-normal.woff2", "frontend/assets/fonts/vazirmatn-arabic-700.woff2"],
  ["node_modules/@fontsource/vazirmatn/files/vazirmatn-latin-700-normal.woff2", "frontend/assets/fonts/vazirmatn-latin-700.woff2"]
];

for (const [source, target] of copies) {
  await mkdir(path.dirname(target), { recursive: true });
  await copyFile(source, target);
}

console.log("Offline assets copied.");

import { loadPyodide, version } from "../pyodide/pyodide.mjs";

export { version };

export async function loadBrowserPython(options = {}) {
  // Download managers can intercept .zip URLs even when fetched by a worker.
  // Fetch through an inline, extensionless endpoint, then bootstrap from memory.
  const response = await fetch(new URL("/runtime/python-stdlib", import.meta.url));
  if (!response.ok) {
    throw new Error(`دریافت کتابخانه داخلی پایتون ناموفق بود (${response.status}). برنامه را دوباره اجرا و صفحه را نوسازی کنید.`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length < 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b
      || bytes[2] !== 0x03 || bytes[3] !== 0x04) {
    throw new Error("فایل کتابخانه داخلی پایتون ناقص یا نامعتبر دریافت شد. صفحه را دوباره بارگذاری کنید.");
  }
  const stdLibURL = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
  try {
    return await loadPyodide({
      indexURL: new URL("../pyodide/", import.meta.url).href,
      ...options,
      stdLibURL
    });
  } finally {
    URL.revokeObjectURL(stdLibURL);
  }
}

const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const source = readFileSync(path.join(__dirname, "../frontend/assets/js/aquifer3d-sw.js"), "utf8");
const origin = "https://groundwater.test";

function harness() {
  const stores = new Map();
  const listeners = new Map();
  const added = [];
  const key = value => typeof value === "string" ? value : value.url;
  const caches = {
    keys: async () => [...stores.keys()],
    delete: async name => stores.delete(name),
    open: async name => {
      if (!stores.has(name)) stores.set(name, new Map());
      const store = stores.get(name);
      return {
        keys: async () => [...store.keys()].map(url => new Request(url)),
        match: async request => store.get(key(request))?.clone(),
        put: async (request, response) => store.set(key(request), response.clone()),
        add: async url => added.push(url)
      };
    }
  };
  const self = {
    location: { origin },
    addEventListener: (name, listener) => listeners.set(name, listener),
    skipWaiting: async () => {},
    clients: { claim: async () => {} }
  };
  vm.runInNewContext(source, { caches, self, URL, Request });
  return {
    caches, added, stores,
    dispatch: async name => {
      let pending;
      listeners.get(name)({ waitUntil: promise => { pending = promise; } });
      await pending;
    }
  };
}

test("runtime precaching never fetches ZIP downloads", async () => {
  const runtime = harness();
  await runtime.dispatch("install");
  assert(runtime.added.includes("/runtime/python-stdlib"));
  assert(runtime.added.includes("/assets/js/pyodide-runtime.js"));
  assert(runtime.added.every(url => !url.endsWith(".zip")));
});

test("upgrades retain scientific packages and visited dashboards without old scripts", async () => {
  const runtime = harness();
  const old = await runtime.caches.open("aquifer3d-offline-v7");
  const wheel = "https://cdn.jsdelivr.net/pyodide/v0.29.3/full/numpy.whl";
  const partial = `${origin}/partials/dashboard?aquifer_id=example`;
  const script = `${origin}/assets/js/dashboard-worker.js`;
  const archive = `${origin}/assets/pyodide/python_stdlib.zip`;
  for (const url of [wheel, partial, script, archive]) await old.put(url, new Response("previous"));
  await runtime.dispatch("install");
  const currentName = (await runtime.caches.keys()).find(name => name !== "aquifer3d-offline-v7");
  const current = await runtime.caches.open(currentName);
  await current.put(script, new Response("updated"));
  await runtime.dispatch("activate");
  assert.equal(await (await current.match(wheel)).text(), "previous");
  assert.equal(await (await current.match(partial)).text(), "previous");
  assert.equal(await (await current.match(script)).text(), "updated");
  assert.equal(await current.match(archive), undefined);
  assert.deepEqual(await runtime.caches.keys(), [currentName]);
});

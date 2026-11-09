self.onmessage = async ({data}) => {
  try {
    const {loadPyodide} = await import(data.base + '/frontend/assets/pyodide/pyodide.mjs');
    const py = await loadPyodide({indexURL:data.base + '/frontend/assets/pyodide/'});
    const code = await (await fetch(data.base+'/.tmp/mashhad-bedrock/compute.py')).text();
    await py.runPythonAsync(code);
    py.globals.set('source_text',data.text);
    const model = await py.runPythonAsync('build(source_text)');
    self.postMessage({model:JSON.parse(model)});
  } catch(error) { self.postMessage({error:String(error.stack || error)}); }
};

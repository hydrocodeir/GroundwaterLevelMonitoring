/** Presentation helpers: move existing controls without duplicating their state. */
export function foldSettings(root,{key,title,nodes}){
  const details=document.createElement('details');details.className='a3-module-settings';details.dataset.analysisSettings=key;
  const summary=document.createElement('summary'),label=document.createElement('span'),context=document.createElement('small'),body=document.createElement('div');
  label.textContent=title;summary.append(label,context);body.className='a3-module-settings-body';details.append(summary,body);
  nodes[0].before(details);nodes.forEach(node=>body.append(node));
  return {details,context,open(){details.open=true;summary.focus();}};
}

export function foldExplanation(node,title){
  const details=document.createElement('details'),summary=document.createElement('summary');details.className='a3-view-explainer';summary.textContent=title;node.before(details);details.append(summary,node);return details;
}

export function managementStage(root){
  const stage=document.createElement('div'),map=document.createElement('div'),analysis=document.createElement('div');
  stage.className='a3-management-stage';map.className='a3-management-map-column';analysis.className='a3-management-analysis-column';
  const panels=[...root.querySelectorAll('[data-m-view]')];panels[0].before(stage);
  const context=document.createElement('p');context.className='a3-measurement-context';
  map.append(context,root.querySelector('.a3-management-horizon'),root.querySelector('.a3-management-map'));
  panels.forEach(panel=>analysis.append(panel));stage.append(map,analysis);
  return {stage,map,analysis,context};
}

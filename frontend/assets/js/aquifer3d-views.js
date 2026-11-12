/** Camera angles are display controls; they do not alter the analytical model. */
export const standardViews = [
  {key:'north',label:'شمال',yaw:Math.PI,pitch:.55},
  {key:'south',label:'جنوب',yaw:0,pitch:.55},
  {key:'east',label:'شرق',yaw:-Math.PI/2,pitch:.55},
  {key:'west',label:'غرب',yaw:Math.PI/2,pitch:.55},
  {key:'top',label:'بالا',yaw:0,pitch:Math.PI/2},
  {key:'oblique',label:'مایل',yaw:.6,pitch:.65}
];
export const presetCamera = key => {
  const preset=standardViews.find(view=>view.key===key);
  return preset?{yaw:preset.yaw,pitch:preset.pitch,zoom:1,panX:0,panY:0}:null;
};

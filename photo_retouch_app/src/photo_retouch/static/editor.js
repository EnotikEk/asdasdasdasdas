const $=id=>document.getElementById(id);
const specs={brightness:['Яркость',-100,100],contrast:['Контраст',-100,100],sharpness:['Резкость',0,100],saturation:['Насыщенность',-100,100],temperature:['Температура',-100,100],vignette:['Виньетка',0,100]};
const names={background:'Фон',photo:'Фотография',costume:'Костюм',frame:'Рамка',text:'Текст'};
const fields={initial_photo:'initialPhoto',restored_photo:'restoredPhoto',backgrounds:'background',frames:'frame',costumes:'costume',fonts:'font'};
const blank=()=>({initialPhoto:'',restoredPhoto:'',background:'',frame:'',font:'',costume:'',adjustments:Object.fromEntries(Object.keys(specs).map(k=>[k,0])),costumeTransform:{position:{x:200,y:200},scale:1,rotation:0},costumeOpacity:1,textOverlay:{content:'',position:{x:200,y:200},style:{fontSize:48,color:'#ffffff'}},layerVisibility:Object.fromEntries(Object.keys(names).map(k=>[k,true])),layerOrder:Object.keys(names)});
let state=blank(),history=[],index=-1,assets={},timer,controller,previewUrl,zoom=1,sequence=0;
function status(text){$('status').textContent=text}
async function api(url,options={}){const response=await fetch(url,options);if(!response.ok){let message;try{message=(await response.json()).error}catch{message=response.statusText}throw Error(message)}return response}
function json(body){return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}}
function fail(error){if(error.name!=='AbortError')status('Ошибка: '+error.message)}
function record(){history=history.slice(0,index+1);history.push(JSON.stringify(state));if(history.length>50)history.shift();index=history.length-1;buttons()}
function buttons(){$('undo').disabled=index<=0;$('redo').disabled=index>=history.length-1}
function changed(){record();schedule()}
function schedule(){clearTimeout(timer);timer=setTimeout(preview,180)}
async function preview(){const version=++sequence;controller?.abort();controller=new AbortController();status('Обработка…');try{const response=await api('/api/render',{...json(state),signal:controller.signal});const blob=await response.blob();if(version!==sequence)return;const old=previewUrl;previewUrl=URL.createObjectURL(blob);$('preview').src=previewUrl;$('preview').hidden=!(state.initialPhoto||state.restoredPhoto||state.background||state.frame||state.costume||state.textOverlay.content);$('empty').hidden=!$('preview').hidden;$('canvasWrap').hidden=$('preview').hidden;if(old)URL.revokeObjectURL(old);status('Изменения применены')}catch(e){fail(e)}}
function sync(){$('wearSuit').textContent=state.costume?'Подогнать костюм':'Надеть костюм';for(const k in specs){$(k).value=state.adjustments[k]??0;$(k+'Value').value=$(k).value}const t=state.textOverlay;for(const [id,value] of Object.entries({text:t.content,fontSize:t.style.fontSize??48,color:t.style.color??'#ffffff',textX:t.position.x,textY:t.position.y,costumeX:state.costumeTransform.position.x,costumeY:state.costumeTransform.position.y,scale:state.costumeTransform.scale*100,rotation:state.costumeTransform.rotation,opacity:state.costumeOpacity*100}))$(id).value=value;layers();buttons();schedule()}
function layers(){const list=$('layers');list.replaceChildren();[...state.layerOrder].reverse().forEach((name,i)=>{const row=document.createElement('div'),check=document.createElement('input'),label=document.createElement('span');check.type='checkbox';check.checked=state.layerVisibility[name]!==false;check.setAttribute('aria-label',names[name]);check.onchange=()=>{state.layerVisibility[name]=check.checked;changed()};label.textContent=names[name];row.append(check,label);for(const [sign,delta] of [['↑',1],['↓',-1]]){const button=document.createElement('button');button.textContent=sign;button.onclick=()=>{const a=state.layerOrder.indexOf(name),b=a+delta;if(b<0||b>=state.layerOrder.length)return;[state.layerOrder[a],state.layerOrder[b]]=[state.layerOrder[b],state.layerOrder[a]];layers();changed()};row.append(button)}list.append(row)})}
async function library(){assets=await(await api('/api/assets')).json();gallery()}
function gallery(){$('assets').replaceChildren();for(const path of assets[$('category').value]||[]){const button=document.createElement('button');button.textContent=path.split('/').pop();button.title=button.textContent;button.onclick=()=>selectAsset(path);$('assets').append(button)}}
function selectAsset(path){const category=$('category').value;state[fields[category]]=path;if(category==='initial_photo')state.restoredPhoto='';changed()}
for(const [key,[name,min,max]] of Object.entries(specs)){const label=document.createElement('label');label.innerHTML=`${name}<output id="${key}Value">0</output><input id="${key}" type="range" min="${min}" max="${max}" value="0">`;$('adjustments').append(label);$(key).oninput=()=>{state.adjustments[key]=+$(key).value;$(key+'Value').value=$(key).value;schedule()};$(key).onchange=record}
$('category').onchange=gallery;
$('upload').onchange=async()=>{const file=$('upload').files[0];if(!file)return;const data=new FormData();data.append('file',file);try{status('Загрузка…');const result=await(await api('/api/upload/'+$('category').value,{method:'POST',body:data})).json();selectAsset(result.path);await library()}catch(e){fail(e)}finally{$('upload').value=''}};
$('clearAsset').onclick=()=>{state[fields[$('category').value]]='';changed()};
$('reset').onclick=()=>{state.adjustments=blank().adjustments;record();sync()};
for(const id of ['text','fontSize','color','textX','textY','costumeX','costumeY','scale','rotation','opacity']){$(id).oninput=()=>{state.textOverlay.content=$('text').value;state.textOverlay.style.fontSize=Math.max(8,Math.min(500,+$('fontSize').value||48));state.textOverlay.style.color=$('color').value;state.textOverlay.position={x:+$('textX').value,y:+$('textY').value};state.costumeTransform={position:{x:+$('costumeX').value,y:+$('costumeY').value},scale:Math.max(.01,Math.min(5,+$('scale').value/100)),rotation:+$('rotation').value};state.costumeOpacity=+$('opacity').value/100;schedule()};$(id).onchange=record}
function travel(delta){if(index+delta<0||index+delta>=history.length)return;index+=delta;state=JSON.parse(history[index]);sync()}
$('undo').onclick=()=>travel(-1);$('redo').onclick=()=>travel(1);
$('new').onclick=()=>{state=blank();record();sync()};
$('save').onclick=async()=>{try{await api('/api/project',json(state));status('Проект сохранён на сервере')}catch(e){fail(e)}};
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('download').onclick=()=>download(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}),'project.proj');
$('open').onclick=()=>$('projectFile').click();
$('projectFile').onchange=async()=>{try{const loaded=JSON.parse(await $('projectFile').files[0].text());const defaults=blank();state={...defaults,...loaded,adjustments:{...defaults.adjustments,...loaded.adjustments},costumeOpacity:loaded.costumeOpacity??1,layerOrder:loaded.layerOrder??defaults.layerOrder};if(!state.textOverlay?.style||!state.costumeTransform?.position)throw Error('Неверный файл проекта');record();sync()}catch(e){fail(e)}finally{$('projectFile').value=''}};
$('export').onclick=async()=>{try{status('Подготовка экспорта…');const fmt=$('format').value;const response=await api('/api/export/'+fmt,json(state));download(await response.blob(),'retouch.'+fmt);status('Экспорт готов')}catch(e){fail(e)}};
async function transform(action,box){
  const path=state.restoredPhoto||state.initialPhoto,originalState=state;
  if(!path){status('Сначала загрузите фотографию');return}
  try{
    document.querySelectorAll('[data-action]').forEach(button=>button.disabled=true);
    const message=action==='redraw'?'Полная перерисовка в OpenAI… Это может занять несколько минут.':action==='remove_background'?'Удаление фона… Подождите':'Обработка…';
    status(message);if(action==='redraw')$('repairStatus').textContent=message;
    const data=await(await api('/api/transform',json({path,action,box,photoEdits:state.photoEdits||{},repairMarks:state.repairMarks||{},strength:+$('repairStrength').value}))).json();
    if(state!==originalState||path!==(state.restoredPhoto||state.initialPhoto)){await library();status('Результат сохранён в обработанных фотографиях');return}
    state.restoredPhoto=data.path;
    if(action==='redraw')$('repairStatus').textContent='Полная перерисовка завершена. Сравните лицо с оригиналом. Результат можно отменить.';
    if(action==='restore_old')$('repairStatus').textContent=data.repairedPercent>0?'Реставрация завершена. Обработано '+data.repairedPercent+'% изображения.':'Царапины не найдены автоматически. Отметьте их кистью и повторите.';
    changed();await library();
  }catch(e){fail(e);if(action==='redraw')$('repairStatus').textContent=e.message}
  finally{document.querySelectorAll('[data-action]').forEach(button=>button.disabled=false)}
}
document.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>transform(button.dataset.action));
$('crop').onclick=()=>{const value=prompt('Область в пикселях: слева, сверху, справа, снизу','0,0,500,500');if(value)transform('crop',value.split(',').map(Number))};
function setZoom(value){zoom=Math.max(.1,Math.min(4,value));$('preview').style.maxWidth='none';$('preview').style.width=(zoom*100)+'%';$('zoomLabel').textContent=Math.round(zoom*100)+'%'}
$('zoomIn').onclick=()=>setZoom(zoom*1.2);$('zoomOut').onclick=()=>setZoom(zoom/1.2);
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&!['INPUT','TEXTAREA'].includes(event.target.tagName)){if(event.key==='z'){event.preventDefault();travel(-1)}if(event.key==='y'){event.preventDefault();travel(1)}if(event.key==='s'){event.preventDefault();$('save').click()}}});
(async()=>{try{state={...blank(),...await(await api('/api/project')).json()};await library();record();sync()}catch(e){fail(e)}})();



$('memorial').onclick=()=>{
  if(!(state.restoredPhoto||state.initialPhoto)){status('Сначала загрузите фотографию');return}
  state.adjustments={brightness:8,contrast:25,sharpness:35,saturation:-100,temperature:0,vignette:0};
  record();sync();
};
$('wearSuit').onclick=async()=>{
  const path=state.restoredPhoto||state.initialPhoto;
  if(!path){status('Сначала загрузите фотографию');return}
  $('wearSuit').disabled=true;
  try{
    status('Подбор положения костюма…');
    const data=await(await api('/api/costume',json({path}))).json();
    if(path!==(state.restoredPhoto||state.initialPhoto))return;
    state.costume=data.path;state.costumeTransform=data.transform;state.costumeOpacity=1;
    state.layerVisibility.costume=true;
    state.layerOrder=state.layerOrder.filter(name=>name!=='costume');
    state.layerOrder.splice(state.layerOrder.indexOf('photo')+1,0,'costume');
    record();sync();
    $('costumeSettings').open=true;
    $('suitStatus').textContent=data.fitMethod==='shoulders'?'Костюм подогнан по ширине и наклону плеч.':data.faceDetected?'Плечи не определены: выполнена подгонка по лицу.':'Человек не распознан. Подстройте X, Y и масштаб вручную.';
    await library();
  }catch(e){fail(e)}finally{$('wearSuit').disabled=false}
};
$('removeSuit').onclick=()=>{if(!state.costume)return;state.costume='';record();sync();$('suitStatus').textContent='Костюм снят'};




// Brush edits remain separate from the source image and belong to its asset path.
let brushMode=null, activeStroke=null, brushPointer=null, lastBrushPreview=0;
const brushCanvas=$('brushCanvas'), brushContext=brushCanvas.getContext('2d');
function photoPath(){return state.restoredPhoto||state.initialPhoto}
function brushTool(mode){
  if(mode&&!photoPath()){status('Сначала загрузите фотографию');return}
  brushMode=mode;
  brushCanvas.classList.toggle('active',!!mode);
  $('eraser').setAttribute('aria-pressed',String(mode==='erase'));
  $('restoreBrush').setAttribute('aria-pressed',String(mode==='restore'));$('repairBrush').setAttribute('aria-pressed',String(mode==='repair'));
  brushContext.clearRect(0,0,brushCanvas.width,brushCanvas.height);
  status(mode==='repair'?'Отметьте повреждения и нажмите «Убрать царапины»':mode==='erase'?'Ластик: проведите по фотографии':mode==='restore'?'Восстановление: проведите по стёртому участку':'Ручная правка завершена');
}
$('eraser').onclick=()=>brushTool(brushMode==='erase'?null:'erase');
$('restoreBrush').onclick=()=>brushTool(brushMode==='restore'?null:'restore');
$('brushOff').onclick=()=>brushTool(null);
$('brushSize').oninput=()=>$('brushSizeValue').value=$('brushSize').value+' px';
function brushPoint(event){const rect=brushCanvas.getBoundingClientRect();return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))]}
function brushCursor(point){
  const rect=brushCanvas.getBoundingClientRect();
  brushCanvas.width=Math.max(1,Math.round(rect.width*devicePixelRatio));
  brushCanvas.height=Math.max(1,Math.round(rect.height*devicePixelRatio));
  const factor=Math.min(rect.width/$('preview').naturalWidth,rect.height/$('preview').naturalHeight);
  const radius=Math.max(2,+$('brushSize').value*factor/2)*devicePixelRatio;
  drawRepairMarks();brushContext.beginPath();brushContext.arc(point[0]*brushCanvas.width,point[1]*brushCanvas.height,radius,0,Math.PI*2);
  brushContext.strokeStyle='black';brushContext.lineWidth=3*devicePixelRatio;brushContext.stroke();
  brushContext.strokeStyle=brushMode==='restore'?'#9af5be':'white';brushContext.lineWidth=devicePixelRatio;brushContext.stroke();
}
brushCanvas.addEventListener('pointerdown',event=>{
  if(!brushMode||!photoPath()||event.button!==0||activeStroke)return;
  if(state.layerVisibility.photo===false){status('Включите видимость слоя «Фотография» для правки');return}
  event.preventDefault();
  const point=brushPoint(event),path=photoPath();
  const field=brushMode==='repair'?'repairMarks':'photoEdits';state[field]??={};state[field][path]??=[];
  if(state[field][path].length>=1000){status('Достигнут предел 1000 мазков для этой фотографии');return}
  const stroke={mode:brushMode==='repair'?'erase':brushMode,size:+$('brushSize').value/Math.min($('preview').naturalWidth,$('preview').naturalHeight),points:[point]};
  stroke.size=Math.min(2,stroke.size);
  state[field][path].push(stroke);activeStroke=stroke;brushPointer=event.pointerId;
  brushCanvas.setPointerCapture(event.pointerId);brushCursor(point);schedule();
});
brushCanvas.addEventListener('pointermove',event=>{
  if(!brushMode)return;
  const point=brushPoint(event);brushCursor(point);
  if(!activeStroke||event.pointerId!==brushPointer)return;
  event.preventDefault();
  if(activeStroke.points.length<10000)activeStroke.points.push(point);
  if(performance.now()-lastBrushPreview>200){lastBrushPreview=performance.now();schedule()}
});
function finishStroke(event){
  if(!activeStroke||event.pointerId!==brushPointer)return;
  const pointer=brushPointer;activeStroke=null;brushPointer=null;
  if(brushCanvas.hasPointerCapture(pointer))brushCanvas.releasePointerCapture(pointer);
  record();schedule();
}
brushCanvas.addEventListener('pointerup',finishStroke);
brushCanvas.addEventListener('pointercancel',finishStroke);
brushCanvas.addEventListener('lostpointercapture',finishStroke);
brushCanvas.addEventListener('pointerleave',()=>{if(!activeStroke){brushContext.clearRect(0,0,brushCanvas.width,brushCanvas.height);drawRepairMarks()}});
document.addEventListener('keydown',event=>{if(event.key==='Escape')brushTool(null)});


$('repairBrush').onclick=()=>brushTool(brushMode==='repair'?null:'repair');
$('repairStrength').oninput=()=>$('repairStrengthValue').value=$('repairStrength').value+'%';
$('clearRepair').onclick=()=>{if(!photoPath())return;state.repairMarks??={};state.repairMarks[photoPath()]=[];record();brushContext.clearRect(0,0,brushCanvas.width,brushCanvas.height);status('Отметки повреждений очищены')};
function drawRepairMarks(){
  const strokes=state.repairMarks?.[photoPath()]||[];
  brushContext.save();brushContext.strokeStyle='rgba(255,80,90,.55)';brushContext.fillStyle='rgba(255,80,90,.55)';brushContext.lineCap='round';brushContext.lineJoin='round';
  for(const stroke of strokes){
    brushContext.lineWidth=stroke.size*Math.min(brushCanvas.width,brushCanvas.height);
    brushContext.beginPath();stroke.points.forEach(([x,y],i)=>{if(i===0)brushContext.moveTo(x*brushCanvas.width,y*brushCanvas.height);else brushContext.lineTo(x*brushCanvas.width,y*brushCanvas.height)});brushContext.stroke();
    const [x,y]=stroke.points[0];brushContext.beginPath();brushContext.arc(x*brushCanvas.width,y*brushCanvas.height,brushContext.lineWidth/2,0,Math.PI*2);brushContext.fill();
  }
  brushContext.restore();
}
$('preview').addEventListener('load',()=>{const rect=brushCanvas.getBoundingClientRect();brushCanvas.width=Math.max(1,Math.round(rect.width*devicePixelRatio));brushCanvas.height=Math.max(1,Math.round(rect.height*devicePixelRatio));drawRepairMarks()});


(async()=>{try{const info=await(await api('/api/ai-status')).json();if(!info.configured)$('aiStatus').textContent='Полная AI-перерисовка: требуется API-ключ OpenAI на сервере. После настройки фотография отправляется в OpenAI; запрос оплачивается отдельно.'}catch(e){fail(e)}})();


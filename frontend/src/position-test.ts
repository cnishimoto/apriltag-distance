import { nativeFrame } from './native-camera';
// Independent still-frame position error workflow; preserves the existing live streaming code.
const get = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const video = get<HTMLVideoElement>('video');
const importInput = get<HTMLInputElement>('positionImport');
const captureButton = get<HTMLButtonElement>('captureMeasurement');
const analyzeButton = get<HTMLButtonElement>('analyzeImport');
const saveButton = get<HTMLButtonElement>('recordMeasurement');
let selected: Blob | null = null;
let imageName = '';
let estimateOk = false;
let busy = false;
let profileHash = '';
let estimatedTag: number | null = null;
const setPositionStatus = (text: string) => {
  get('positionStatus').textContent = text;
};
const invalidate = () => {estimateOk=false;saveButton.disabled=true;estimatedTag=null;};
const tagId = () => {const v=get<HTMLInputElement>('positionTagId').value.trim();return v===''?null:Number(v);};
async function headers(): Promise<Record<string,string>> {
  const h:Record<string,string>={'Content-Type':selected?.type||'application/octet-stream'};
  const file=get<HTMLInputElement>('positionConfig').files?.[0];
  if(file) h['X-Camera-Config']=JSON.stringify(JSON.parse(await file.text()));
  return h;
}
function query():URLSearchParams { const p=new URLSearchParams();const id=tagId();if(id!==null)p.set('tag_id',String(id));return p; }
async function call(url:string, params?:URLSearchParams) {
  if(!selected)throw Error('Select or capture an image first.');
  const target=params?url+'?'+params:url+'?'+query();
  const response=await fetch(target,{method:'POST',headers:await headers(),body:selected});
  const data=await response.json();if(!response.ok)throw Error(data.detail||data.error||'Request failed');return data;
}
async function estimate(){
  if(!selected||busy)return;busy=true;invalidate();setPositionStatus('Estimating position...');
  try {
    const result=await call('/api/image-position');
    estimatedTag=result.id;
    profileHash=await get<HTMLInputElement>('positionConfig').files?.[0]?.text()||'default';
    get('positionResult').textContent=`Tag ${result.id} · ${result.image_width} × ${result.image_height}\nX: ${result.x_m.toFixed(6)} m\nY: ${result.y_m.toFixed(6)} m\nZ: ${result.z_m.toFixed(6)} m\nRange: ${result.distance_m.toFixed(6)} m\nReprojection RMS: ${result.reprojection_rms_px.toFixed(3)} px`;
    estimateOk=true;saveButton.disabled=false;setPositionStatus(`Estimated ${imageName}. Enter ground truth to save a CSV row.`);
  }catch(e){get('positionResult').textContent='';setPositionStatus(String(e));}
  finally{busy=false;}
}
async function pngFrame():Promise<Blob>{
  if(document.body.dataset.nativeActive==='true')return nativeFrame('png');
  if(!video.srcObject||!video.videoWidth)throw Error('Start camera first.');
  const canvas=document.createElement('canvas');canvas.width=video.videoWidth;canvas.height=video.videoHeight;
  canvas.getContext('2d')!.drawImage(video,0,0);
  const file=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/png'));
  if(!file)throw Error('Could not encode PNG');return file;
}
async function capture(){
  if(busy)return;busy=true;invalidate();captureButton.disabled=true;
  try{
    const frame=await pngFrame();setPositionStatus('Saving original-resolution PNG...');
    const response=await fetch('/api/image-position/capture',{method:'POST',headers:{'Content-Type':'image/png'},body:frame});
    const result=await response.json();if(!response.ok)throw Error(result.detail||'Capture failed');
    selected=frame;imageName=result.image_name;get<HTMLSelectElement>('measurementSource').value='real';
    setPositionStatus(`Saved pictures/${imageName} (${result.width} × ${result.height}).`);
  }catch(e){setPositionStatus(String(e));selected=null;}
  finally{busy=false;}
  if(selected)await estimate();
}
async function save(){
  if(!estimateOk||!selected||busy)return;
  const field=get<HTMLInputElement>('groundTruth');const truth=Number(field.value);
  if(!field.value||!Number.isFinite(truth)||truth<=0){setPositionStatus('Enter a positive ground-truth distance.');return;}
  const currentProfile=await get<HTMLInputElement>('positionConfig').files?.[0]?.text()||'default';
  if(currentProfile!==profileHash){invalidate();setPositionStatus('Calibration changed; estimate again.');return;}
  busy=true;saveButton.disabled=true;
  try{
    const q=new URLSearchParams({true_distance_m:String(truth),reference_type:get<HTMLSelectElement>('distanceType').value,source:get<HTMLSelectElement>('measurementSource').value,image_name:imageName});
    if(estimatedTag!==null)q.set('tag_id',String(estimatedTag));
    const r=await call('/api/image-position/save',q);
    setPositionStatus(`Saved CSV row for ${imageName}. Signed error: ${(r.measurement.signed_error_m*100).toFixed(2)} cm.`);invalidate();
  }catch(e){setPositionStatus(String(e));saveButton.disabled=false;}finally{busy=false;}
}
setInterval(()=>{const native=document.body.dataset.nativeActive==='true';captureButton.disabled=busy||(!native&&(!video.srcObject||!video.videoWidth));},500);
captureButton.addEventListener('click',capture);
importInput.addEventListener('change',()=>{const file=importInput.files?.[0];if(!file)return;selected=file;imageName=file.name;invalidate();analyzeButton.disabled=false;setPositionStatus(`Selected ${imageName}`);});
analyzeButton.addEventListener('click',estimate);
saveButton.addEventListener('click',save);
get<HTMLInputElement>('positionConfig').addEventListener('change',invalidate);
get<HTMLInputElement>('positionTagId').addEventListener('input',invalidate);

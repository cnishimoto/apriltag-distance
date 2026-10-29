import { loadImage, png } from './image-files';
import './style.css';
import { ResolutionControl, videoConstraints, captureError } from './camera-settings';
type Settings = {width:number;height:number;columns:number;rows:number;square_mm:number;token:string;count:number};
type Result = {rms_px:number;per_view_rms_px:number[];views:number};
const element = <T extends HTMLElement>(id:string):T => { const e=document.getElementById(id); if(!e) throw new Error(id); return e as T; };
const video=element<HTMLVideoElement>('cameraVideo'), select=element<HTMLSelectElement>('cameraSelect');
const snapshot=element<HTMLCanvasElement>('snapshot'), accepted=element<HTMLCanvasElement>('accepted');
const button=(id:string)=>element<HTMLButtonElement>(id);
const message=(s:string)=>{element('status').textContent=s;};
const errorText=captureError;
const imageUpload=element<HTMLInputElement>('imageUpload');
let settings:Settings, stream:MediaStream|null=null, busy=false, count=0, solved=false, generation=0;
const resolutionControl=new ResolutionControl(()=>{stop();message('Resolution changed. Start the camera to apply it.');});
select.onchange=()=>{stop();message('Camera changed. Start the camera to use it.');};
function showResolution(){
 if(!settings)return;
 const resolution=stream&&video.videoWidth ? `${video.videoWidth} × ${video.videoHeight}` : 'Automatic resolution';
 element('activeResolution').textContent=stream&&video.videoWidth ? `Active · ${video.videoWidth} × ${video.videoHeight}` : 'No active stream';
 element('cameraPlaceholder').hidden=!!stream;
 element('setup').textContent=`${settings.columns} × ${settings.rows} internal corners · ${settings.square_mm} mm squares · ${resolution}. Use one calibration tab.`;
}
video.addEventListener('resize',showResolution);
function controls(){
 imageUpload.disabled=busy||!settings||count>=60;
 button('start').disabled=busy||!!stream||!settings; button('stop').disabled=busy||!stream;
 button('capture').disabled=busy||!stream||count>=60; select.disabled=busy||count>0;
 resolutionControl.disable(busy||count>0||!settings);
 for(const id of ['undo','reset']) button(id).disabled=busy||count===0;
 button('calculate').disabled=busy||count<12; button('save').disabled=busy||!solved;
 element('count').textContent=`${count} VIEWS`;
 element<HTMLProgressElement>('progress').value=Math.min(count,20);
 element('progressText').textContent=`${count} / 20 recommended`;
 button('calculate').textContent=solved ? 'Recalculate' : 'Calculate calibration';
}
async function post<T>(action:string,body?:Blob):Promise<T>{
 const response=await fetch(`/api/calibration/${action}`,{method:'POST',headers:{'x-calibration-token':settings.token},body});
 const data=await response.json(); if(!response.ok) throw new Error(data.detail||'Request failed'); return data as T;
}
async function task(work:()=>Promise<void>){busy=true;controls();element('main').setAttribute('aria-busy','true');element('status').dataset.tone='info';try{await work();}catch(e){message(errorText(e));element('status').dataset.tone='error';}finally{busy=false;controls();element('main').setAttribute('aria-busy','false');}}
function stop(){generation++;stream?.getTracks().forEach(t=>t.stop());stream=null;video.srcObject=null;showResolution();controls();}
button('start').onclick=()=>task(async()=>{
 const token=++generation;
 if(!navigator.mediaDevices?.getUserMedia)throw new Error('Camera access requires localhost or HTTPS.');
 const acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:videoConstraints(select.value,resolutionControl.value())});
 if(token!==generation){acquired.getTracks().forEach(t=>t.stop());return;}
 stream=acquired;video.srcObject=stream;
 try{await video.play();}catch(e){stop();throw e;}
 showResolution();
 stream.getVideoTracks()[0].onended=()=>{stop();message('Camera disconnected.');};
 const selected=stream.getVideoTracks()[0].getSettings().deviceId;
 select.replaceChildren(...(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput').map((d,i)=>new Option(d.label||`Camera ${i+1}`,d.deviceId)));
 if(selected)select.value=selected;
 message('Hold the board still, then Capture view. Change position and tilt between views.');
});
button('stop').onclick=()=>{stop();message('Camera released.');};
button('capture').onclick=()=>task(async()=>{
 if(video.readyState<2)throw new Error('Wait for the camera preview.');
 snapshot.width=video.videoWidth;snapshot.height=video.videoHeight;
 const context=snapshot.getContext('2d');if(!context)throw new Error('Canvas unavailable');context.drawImage(video,0,0);
 const blob=await new Promise<Blob|null>(r=>snapshot.toBlob(r,'image/png'));if(!blob)throw new Error('Capture failed');
 message('Looking for checkerboard corners…');
 await submitCapture(blob);
});
async function submitCapture(blob:Blob, source?:File){
 const response=await post<{count:number;corners:[number,number][]}>(source ? `capture?source_name=${encodeURIComponent(source.name)}&source_modified=${encodeURIComponent(new Date(source.lastModified).toISOString())}` : 'capture',blob);
 count=response.count;solved=false;element('result').textContent='Capture accepted. Calculate after collecting varied views.';element('errors').textContent='';
 accepted.hidden=false;element('reviewEmpty').hidden=true;element('errorDetails').hidden=true;
 accepted.width=snapshot.width;accepted.height=snapshot.height;
 const ctx=accepted.getContext('2d');if(ctx){ctx.drawImage(snapshot,0,0);ctx.fillStyle='#e93d73';for(const [x,y]of response.corners){ctx.beginPath();ctx.arc(x,y,4,0,2*Math.PI);ctx.fill();}}
 message(`Accepted view ${count}. Move or tilt the board before the next capture.`);
}
for(const action of ['undo','reset']) button(action).onclick=()=>task(async()=>{
 if(action==='reset'&&!window.confirm('Remove all captured views? Your saved calibration will not change.'))return;
 count=(await post<{count:number}>(action)).count;solved=false;accepted.width=0;accepted.hidden=true;element('reviewEmpty').hidden=false;element('errorDetails').hidden=true;element('errors').textContent='';element('result').textContent='Capture set changed. Calculate again before saving.';message(`${count} views retained.`);
});
button('calculate').onclick=()=>task(async()=>{
 message('Calculating calibration…');const result=await post<Result>('calculate');solved=true;
 element('result').textContent=`RMS reprojection error: ${result.rms_px.toFixed(3)} px across ${result.views} views. ${result.rms_px>1?'Error exceeds 1 px: inspect captures and consider recapturing before saving.':'Review your images and validate distances after saving.'}`;
 element('errorDetails').hidden=false;
 element('errors').textContent='Per-view RMS (pixels): '+result.per_view_rms_px.map((e,i)=>`${i+1}: ${e.toFixed(3)}`).join(' · ');
 message('Calculation complete. Save when you are satisfied with the captures and error.');
});
button('save').onclick=()=>task(async()=>{
 const result=await post<{config:string;output_directory:string}>('save');
 stop();solved=false;message(`Saved config: ${result.config}. Backup, captured images, NPZ and report: ${result.output_directory}. Restart the distance app to load the calibration.`);
});
window.addEventListener('beforeunload',stop);
navigator.mediaDevices?.enumerateDevices().then(devices=>{for(const [i,d]of devices.filter(d=>d.kind==='videoinput').entries())select.add(new Option(d.label||`Camera ${i+1}`,d.deviceId));}).catch(()=>{});
fetch('/api/calibration').then(async r=>{if(!r.ok)throw new Error('Could not load calibration settings');settings=await r.json() as Settings;count=settings.count;showResolution();controls();}).catch(e=>{message(`${errorText(e)}. Start the AprilTag Studio server on port 8000, then refresh.`);element('status').dataset.tone='error';element('setup').textContent='Calibration API unavailable.';controls();});

imageUpload.onchange=()=>task(async()=>{
 const files=Array.from(imageUpload.files||[]);if(!files.length)return;
 stop(); const results:string[]=[];
 try{
  for(const file of files){
   try{
    message(`Checking ${file.name}…`);
    const image=await loadImage(file);snapshot.width=image.width;snapshot.height=image.height;
    snapshot.getContext('2d')!.drawImage(image,0,0);
    await submitCapture(await png(snapshot),file);results.push(`${file.name}: accepted`);
   }catch(e){results.push(`${file.name}: ${errorText(e)}`);}
   element('importResults').textContent=results.join('\n');
  }
  message(`Import complete: ${count} total accepted views. Review individual results below the upload field.`);
 }finally{imageUpload.value='';}
});

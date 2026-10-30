import { newRecordId } from './trial-statistics';
import { MeasurementLogging } from './measurement-logging';
import { loadImage, png, copyCanvas, downloadArchive } from './image-files';
import './style.css';
import { ResolutionControl, videoConstraints, captureError } from './camera-settings';
import type { AppConfig, DetectorResponse, FrameResult } from './types';

type SpecificElements = {
  video: HTMLVideoElement;
  capture: HTMLCanvasElement;
  display: HTMLCanvasElement;
  camera: HTMLSelectElement;
  selected: HTMLSelectElement;
  start: HTMLButtonElement;
  stop: HTMLButtonElement;
};
function $<K extends string>(id: K): K extends keyof SpecificElements ? SpecificElements[K] : HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing interface element: ${id}`);
  return element as K extends keyof SpecificElements ? SpecificElements[K] : HTMLElement;
}
function context2d(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext('2d');
  if (!context) throw new Error('This browser does not support a 2D canvas.');
  return context;
}
const errorMessage = (error: unknown): string => error instanceof Error ? error.message : String(error);
const video = $('video'), capture = $('capture'), display = $('display');
const captureCtx = context2d(capture), ctx = context2d(display);
let config: AppConfig | null = null;
let stream: MediaStream | null = null;
let socket: WebSocket | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let watchdog: ReturnType<typeof setTimeout> | undefined;
let generation = 0, running = false;
let lastResult: FrameResult | null = null;
const imageUpload = document.getElementById('imageUpload') as HTMLInputElement;
imageUpload.disabled = true;
const saveFrame = document.getElementById('saveFrame') as HTMLButtonElement;
let originalFile: File | null = null;
let frameSource: Record<string, unknown> = {};
let capturedAt = '';
let logFrame: { frameId: string; result: FrameResult; raw: HTMLCanvasElement; metadata: Record<string, unknown>; original: File | null } | null = null;
const logging = new MeasurementLogging();
let exporting = false;
let lastCompleted = 0, fps = 0, sentAt = 0, lastMediaTime = -1;
const status = (text: string, tone = 'info'): void => {
  // Avoid announcing an identical per-frame status repeatedly to screen readers.
  if ($('status').textContent !== text) $('status').textContent = text;
  $('status').dataset.tone = tone;
};
const resolutionControl = new ResolutionControl(() => stop('Resolution changed. Start the camera to apply it.'));
function calibrationStatus(width?: number, height?: number): void {
  const card = $('calibration').parentElement!;
  if (!config) {
    card.dataset.state = 'warning'; $('calibration').textContent = 'Connect to the local detector to load your calibration settings.';
  } else if (!config.calibrated) {
    card.dataset.state = 'warning';
    $('calibration').textContent = 'Calibration needed. Preview and detection work; calibrate this camera to enable distance measurements.';
  } else if (width && height && (width !== config.calibration_width || height !== config.calibration_height)) {
    card.dataset.state = 'warning';
    $('calibration').textContent = `Resolution mismatch. Stream: ${width} × ${height}; calibration: ${config.calibration_width} × ${config.calibration_height}. Select the saved calibration resolution or recalibrate. Distances are disabled.`;
  } else {
    card.dataset.state = width ? 'ready' : 'loaded';
    $('calibration').textContent = `${width ? 'Resolution matches' : 'Calibration loaded'} · ${config.calibration_width} × ${config.calibration_height}. Use the same physical camera, zoom and focus settings.`;
  }
}
function clearMetrics() {
  $('distance').innerHTML = '—<small> m</small>';
  $('depth').textContent = '— m';
  for (const id of ['fps','latency']) $(id).textContent = '—';
  $('processing').textContent = '— ms'; $('error').textContent = '— px';
  $('tagcount').textContent = '0 TAGS';
  $('selected').replaceChildren(new Option('No tags detected', ''));
  lastResult = null; logFrame = null; saveFrame.disabled = true; logging.clear();
}
function stop(message = 'Session stopped. Camera released.') {
  generation++; running = false; imageUpload.disabled = !config;
  clearTimeout(timer); clearTimeout(watchdog);
  if (socket) { socket.onclose = null; socket.close(); socket = null; }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  video.srcObject = null;
  $('start').disabled = !config; $('stop').disabled = true; $('camera').disabled = false;
  $('connection').textContent = config ? 'Ready' : 'Server offline'; $('connection').dataset.state = config ? 'ready' : 'error';
  resolutionControl.disable(false); calibrationStatus();
  $('resolution').textContent = 'No active stream';
  display.style.display = 'none'; $('empty').hidden = false;
  clearMetrics(); status(config ? message : 'Local detector is offline. Start uv run python apriltag_distance.py, then refresh.', config ? 'info' : 'error');
}
async function cameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = $('camera').value;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
  $('camera').replaceChildren(new Option('Default camera', ''));
  devices.forEach((d,i) => $('camera').add(new Option(d.label || `Camera ${i+1}`, d.deviceId)));
  if ([...$('camera').options].some(o => o.value === selected)) $('camera').value = selected;
}
function updateMeasurement() {
  const tag = lastResult?.tags.find(t => String(t.id) === $('selected').value);
  $('distance').innerHTML = tag?.distance_m != null ? `${tag.distance_m.toFixed(3)}<small> m</small>` : '—<small> m</small>';
  $('depth').textContent = tag?.depth_m != null ? `${tag.depth_m.toFixed(3)} m` : '— m';
  $('error').textContent = tag?.reprojection_error_px != null ? `${tag.reprojection_error_px.toFixed(2)} px` : '— px';
  if (logFrame) logging.observe(logFrame.frameId, logFrame.result, $('selected').value, logFrame.metadata);
}
function render(result: FrameResult): void {
  const {log_token: _logToken, ...exportConfig} = config!;
  logFrame = {frameId: newRecordId(), result, raw: copyCanvas(capture), original: originalFile, metadata: {
    schema_version: 1, captured_at_utc: capturedAt, processed_at_utc: new Date().toISOString(),
    timestamp_note: 'Browser capture/import time, not camera shutter time.',
    source: frameSource, config: exportConfig, result, units: {distance:'meters', corners:'pixels'},
    smoothing: originalFile ? 'Independent image; distance equals raw distance.' : 'Exponential temporal smoothing; raw distance also included.',
    analysis_fps: originalFile ? null : fps, orientation: 'Browser-decoded orientation; no resizing or cropping.'
  }};
  saveFrame.disabled = exporting;
  const previous = $('selected').value;
  const ids = [...new Set(result.tags.map(t => t.id))];
  $('selected').replaceChildren(...(ids.length ? ids.map(id => new Option(`Tag ${id}`, String(id))) : [new Option('No tags detected', '')]));
  if (ids.includes(Number(previous)) && previous !== '') $('selected').value = previous;
  lastResult = result; updateMeasurement();
  $('tagcount').textContent = `${result.tags.length} TAG${result.tags.length === 1 ? '' : 'S'}`;
  $('resolution').textContent = `Active · ${result.width} × ${result.height}`;
  calibrationStatus(result.width, result.height);
  $('processing').textContent = `${result.processing_ms.toFixed(1)} ms`;
  // Draw the exact frame that produced these corners; never overlay stale corners on a newer frame.
  display.width = capture.width; display.height = capture.height;
  ctx.drawImage(capture, 0, 0); ctx.lineWidth = Math.max(2, display.width / 450);
  ctx.font = `${Math.max(16, display.width / 55)}px monospace`;
  for (const tag of result.tags) {
    ctx.strokeStyle = tag.distance_m == null ? '#ffd074' : '#b6ff9c';
    ctx.beginPath(); tag.corners.forEach(([x,y],i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y)); ctx.closePath(); ctx.stroke();
    const label = `ID ${tag.id}${tag.distance_m != null ? `  ${tag.distance_m.toFixed(3)} m` : ''}`;
    const x = Math.max(0, Math.min(tag.corners[0][0], display.width - ctx.measureText(label).width - 12));
    const y = Math.max(26, tag.corners[0][1]);
    ctx.fillStyle = '#10181bdc'; ctx.fillRect(x,y-26,ctx.measureText(label).width+12,28);
    ctx.fillStyle = '#d7f4cb'; ctx.fillText(label,x+6,y-5);
  }
  display.style.display = 'block'; $('empty').hidden = true;
  const note = result.tags.find(t => t.note)?.note;
  status(result.warning || note || (result.tags.length ? 'Tracking live. Measurements use your saved calibration and physical tag size.' : `Camera live. Point it at a ${config?.tag.dictionary.replace('DICT_APRILTAG_', '')} AprilTag.`), result.warning || note ? 'warning' : 'info');
}
async function sendFrame(token: number): Promise<void> {
  if (!running || token !== generation || socket?.readyState !== WebSocket.OPEN) return;
  if (video.readyState < 2 || video.currentTime === lastMediaTime) {
    timer = setTimeout(() => sendFrame(token), 10); return;
  }
  lastMediaTime = video.currentTime;
  originalFile = null; capturedAt = new Date().toISOString();
  const track = stream?.getVideoTracks()[0];
  frameSource = {kind:'camera', label:track?.label, settings:track?.getSettings()};
  capture.width = video.videoWidth; capture.height = video.videoHeight;
  captureCtx.drawImage(video, 0, 0);
  sentAt = performance.now();
  try {
    const blob = await new Promise<Blob | null>(resolve => capture.toBlob(resolve, 'image/jpeg', 0.95));
    if (!running || token !== generation || !socket) return;
    if (!blob) throw new Error('Could not encode the camera frame.');
    socket.send(blob);
    // At most one frame in flight: the next capture happens only after a reply.
    watchdog = setTimeout(() => stop('Detector timed out. Check the Python terminal and start again.'), 5000);
  } catch (error) { if (token === generation) stop(errorMessage(error)); }
}
async function start() {
  if (!config || running) return;
  clearMetrics();
  const token = ++generation; running = true; imageUpload.disabled = true;
  $('start').disabled = true; $('stop').disabled = false; $('camera').disabled = true;
  resolutionControl.disable(true);
  $('connection').textContent = 'Connecting'; $('connection').dataset.state = 'connecting';
  status('Opening your camera…');
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access requires localhost or HTTPS. Open http://localhost:8000.');
    const deviceId = $('camera').value;
    const acquired = await navigator.mediaDevices.getUserMedia({audio:false, video:videoConstraints(deviceId, resolutionControl.value())});
    if (token !== generation) { acquired.getTracks().forEach(t => t.stop()); return; }
    stream = acquired; video.srcObject = stream; await video.play();
    if (token !== generation) return;
    $('resolution').textContent = `Active · ${video.videoWidth} × ${video.videoHeight}`;
    calibrationStatus(video.videoWidth, video.videoHeight);
    stream.getVideoTracks()[0].onended = () => stop('Camera disconnected or permission revoked.');
    await cameras();
    if (token !== generation) return;
    status('Connecting detector…');
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
    watchdog = setTimeout(() => stop('Could not connect to detector. Check that Python is running.'), 5000);
    socket.onopen = () => {
      if (token !== generation) return;
      clearTimeout(watchdog); lastCompleted = 0; fps = 0; lastMediaTime = -1;
      $('connection').textContent = '● Live'; $('connection').dataset.state = 'live';
      resolutionControl.disable(false); $('camera').disabled = false; imageUpload.disabled = false; sendFrame(token);
    };
    socket.onmessage = event => {
      if (token !== generation) return;
      clearTimeout(watchdog);
      try {
        const result = JSON.parse(event.data as string) as DetectorResponse;
        if ('error' in result) throw new Error(result.error);
        const now = performance.now();
        if (lastCompleted) { const instant = 1000/(now-lastCompleted); fps = fps ? 0.2*instant+0.8*fps : instant; }
        lastCompleted = now;
        $('fps').textContent = fps ? fps.toFixed(1) : '—';
        $('latency').textContent = (now-sentAt).toFixed(0);
        render(result);
        timer = setTimeout(() => sendFrame(token), 0);
      } catch (error) { stop(`Processing failed: ${errorMessage(error)}`); }
    };
    socket.onerror = () => { if (token === generation) stop('Detector connection failed. Check the Python server.'); };
    socket.onclose = () => { if (token === generation) stop('Detector disconnected. Start again to reconnect.'); };
  } catch (error) {
    if (token !== generation) return;
    stop(captureError(error));
    $('connection').textContent = 'Camera unavailable'; $('connection').dataset.state = 'error';
    $('status').dataset.tone = 'error';
  }
}
$('camera').onchange = () => stop('Camera changed. Start a new session to use it.');
$('start').onclick = start; $('stop').onclick = () => stop(); $('selected').onchange = updateMeasurement;
window.addEventListener('beforeunload', () => stop());
document.addEventListener('visibilitychange', () => { if (document.hidden && running) stop('Paused because this tab was hidden. Start again to resume.'); });
async function init() {
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error(`Server returned ${response.status}`);
    const loaded: AppConfig = await response.json();
    config = loaded; imageUpload.disabled = false;
    logging.initialize(config.log_token).catch(e => { $('loggingStatus').textContent = `Spreadsheet logging unavailable: ${errorMessage(e)}`; });
    $('family').textContent = config.tag.dictionary.replace('DICT_APRILTAG_', '');
    $('size').textContent = `${config.tag.tag_size_m.toFixed(3)} m`;
    if (config.calibrated && config.calibration_width && config.calibration_height) resolutionControl.addCalibration(config.calibration_width, config.calibration_height);
    calibrationStatus();
    $('connection').textContent = 'Ready'; $('start').disabled = false;
    status('Ready. Start the camera when you want to begin.');
    try { await cameras(); } catch { /* Camera permissions may hide the device list until Start. */ }
  } catch (error) { config = null; calibrationStatus(); status(`Local detector unavailable: ${errorMessage(error)}. Start uv run python apriltag_distance.py, then refresh.`, 'error'); $('connection').textContent = 'Server offline'; $('connection').dataset.state = 'error'; }
}
init();

imageUpload.onchange = async () => {
  const file=imageUpload.files?.[0]; if(!file)return;
  stop('Loading image…'); const token=generation; imageUpload.disabled=true; $('start').disabled=true;
  try {
    const image=await loadImage(file); const blob=await png(image);
    const response=await fetch('/api/image',{method:'POST',body:blob});
    const result=await response.json(); if(!response.ok)throw new Error(result.detail || 'Image processing failed');
    if(token!==generation)return;
    capture.width=image.width;capture.height=image.height;captureCtx.drawImage(image,0,0);
    originalFile=file;capturedAt=new Date().toISOString();
    frameSource={kind:'uploaded_image',filename:file.name,bytes:file.size,last_modified_utc:new Date(file.lastModified).toISOString()};
    fps=0; render(result as FrameResult);$('connection').textContent='Image';
  }catch(e){if(token===generation)status(captureError(e),'error');}
  finally{if(token===generation){imageUpload.disabled=false;$('start').disabled=!config;}imageUpload.value='';}
};
saveFrame.onclick = async () => {
  if(!logFrame || exporting)return;
  // Capture the displayed frame, selected tag, ground truth and trial statistics together.
  exporting=true; saveFrame.disabled=true;
  try{
    const log=logFrame, annotated=copyCanvas(display);
    const archive=`apriltag-${new Date().toISOString().replace(/[:.]/g,'-')}.zip`;
    const target=logging.targetForFrameDownload();
    const record=logging.buildRecord(archive);
    if(target && !record.row) throw new Error('No valid selected-tag distance to log. Turn off spreadsheet logging to download this frame alone.');
    const files=[{name:'annotated.png',blob:await png(annotated)}, {name:'frame.png',blob:await png(log.raw)},
      {name:'metadata.json',blob:new Blob([JSON.stringify(record.metadata,null,2)],{type:'application/json'})}];
    if(log.original)files.push({name:'source/'+log.original.name.replace(/[^a-zA-Z0-9._-]/g,'_'),blob:log.original});
    await downloadArchive(files,archive);
    if(target) await logging.append(record,target);
  }catch(e){status(captureError(e),'error');}finally{exporting=false;saveFrame.disabled=!logFrame;}
};

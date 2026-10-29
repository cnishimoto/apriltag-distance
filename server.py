"""Local webcam processing service. Run: python server.py"""
import argparse
import asyncio
import csv
import math
import uuid
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apriltag_position import estimate_position
from calibration import validate_calibration

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / 'measurements' / 'position_errors.csv'
PICTURES_DIR = ROOT / 'pictures'
MEASUREMENT_COLUMNS = ['timestamp_utc', 'image_name', 'source', 'tag_id', 'image_width', 'image_height', 'tag_size_m', 'reference_type', 'true_distance_m', 'estimated_distance_m', 'signed_error_m', 'absolute_error_m', 'relative_error_percent', 'x_m', 'y_m', 'z_m', 'estimated_range_m', 'estimated_depth_m', 'reprojection_rms_px', 'camera_profile']



def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    camera, tag = config['camera'], config['apriltag']
    for key in ('width', 'height'):
        if type(camera[key]) is not int or not 1 <= camera[key] <= 12000:
            raise ValueError(f'camera.{key} must be an integer from 1 to 12000')
    size, alpha = float(tag['tag_size_m']), float(tag['smoothing_alpha'])
    if not np.isfinite(size) or size <= 0 or not 0 < alpha <= 1:
        raise ValueError('Tag size must be positive; smoothing alpha must be in (0, 1].')
    if not tag['dictionary'].startswith('DICT_APRILTAG_') or not hasattr(cv2.aruco, tag['dictionary']):
        raise ValueError('Unknown AprilTag dictionary')
    if tag['corner_refinement'] not in ('CORNER_REFINE_NONE', 'CORNER_REFINE_SUBPIX', 'CORNER_REFINE_CONTOUR', 'CORNER_REFINE_APRILTAG'):
        raise ValueError('Unknown corner refinement')
    if camera['K'] is not None and camera['dist'] is not None:
        validate_calibration(np.array(camera['K'], dtype=float), np.array(camera['dist'], dtype=float))
        for key in ('calibration_width', 'calibration_height'):
            if type(camera[key]) is not int or camera[key] <= 0:
                raise ValueError(f'{key} must be a positive integer')
    return config


class Processor:
    def __init__(self, config):
        self.camera, self.tag = config['camera'], config['apriltag']
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = getattr(cv2.aruco, self.tag['corner_refinement'])
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, self.tag['dictionary']))
        self.detector = cv2.aruco.ArucoDetector(dictionary, params)
        s = self.tag['tag_size_m'] / 2
        self.points = np.array([[-s,s,0],[s,s,0],[s,-s,0],[-s,-s,0]], dtype=np.float32)
        self.calibrated = self.camera['K'] is not None and self.camera['dist'] is not None
        self.K = np.array(self.camera['K'], dtype=np.float64) if self.calibrated else None
        self.dist = np.array(self.camera['dist'], dtype=np.float64) if self.calibrated else None
        self.filtered = {}

    def process(self, data, photo=False):
        start = time.perf_counter()
        if not data or len(data) > (100_000_000 if photo else 8_000_000):
            raise ValueError('Image is empty or exceeds the input size limit.')
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Frame is not a valid encoded image.')
        height, width = frame.shape[:2]
        if max(width, height) > (12000 if photo else 4096) or width*height > 60_000_000:
            raise ValueError('Image exceeds the supported dimensions (live: 4096; photos: 12000 pixels / 60 MP).')
        can_measure = self.calibrated and (width, height) == (self.camera['calibration_width'], self.camera['calibration_height'])
        warning = None
        if not self.calibrated:
            warning = 'Calibration missing — detecting tags only. Import calibration to enable distances.'
        elif not can_measure:
            warning = f'Resolution mismatch: received {width}×{height}; calibration is {self.camera["calibration_width"]}×{self.camera["calibration_height"]}. Distances disabled.'
        corners, ids, _ = self.detector.detectMarkers(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        tags, valid = [], set()
        if ids is not None:
            unique, counts = np.unique(ids, return_counts=True)
            duplicates = set(unique[counts > 1].tolist())
            for corner, tag_id in zip(corners, ids.flatten()):
                tag_id = int(tag_id)
                pixels = corner.reshape(4, 2).astype(np.float32)
                result = dict(id=tag_id, corners=pixels.tolist(), distance_m=None, raw_distance_m=None,
                              depth_m=None, reprojection_error_px=None, note=None)
                if tag_id in duplicates:
                    result['note'] = 'Duplicate ID: use unique IDs for independent measurements.'
                elif can_measure:
                    success, rvec, tvec = cv2.solvePnP(self.points, pixels, self.K, self.dist, flags=cv2.SOLVEPNP_IPPE_SQUARE)
                    if success and np.isfinite(rvec).all() and np.isfinite(tvec).all() and tvec[2, 0] > 0:
                        raw = float(np.linalg.norm(tvec))
                        alpha = self.tag['smoothing_alpha']
                        smooth = alpha * raw + (1-alpha) * self.filtered.get(tag_id, raw)
                        self.filtered[tag_id] = smooth
                        valid.add(tag_id)
                        projected, _ = cv2.projectPoints(self.points, rvec, tvec, self.K, self.dist)
                        error = float(np.sqrt(np.mean(np.sum((projected.reshape(4,2)-pixels)**2, axis=1))))
                        result.update(distance_m=smooth, raw_distance_m=raw, depth_m=float(tvec[2,0]), reprojection_error_px=error)
                    else:
                        result['note'] = 'Pose estimate invalid.'
                tags.append(result)
        self.filtered = {k:v for k,v in self.filtered.items() if k in valid}
        return dict(tags=tags, width=width, height=height, warning=warning,
                    processing_ms=(time.perf_counter()-start)*1000)


def create_app(config_path=ROOT / 'apriltag_config.json'):
    config = load_config(config_path)
    app = FastAPI(title='AprilTag Live')

    @app.get('/api/config')
    async def settings():
        c, t = config['camera'], config['apriltag']
        return dict(width=c['width'], height=c['height'], tag=t,
                    calibrated=c['K'] is not None and c['dist'] is not None,
                    calibration_width=c['calibration_width'], calibration_height=c['calibration_height'], calibration={'K':c['K'], 'dist':c['dist']})

    @app.post('/api/image')
    async def image(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 100_000_000:
                raise HTTPException(413, 'Image exceeds 100 MB.')
        try:
            # Independent stills must never inherit temporal smoothing history.
            return await asyncio.to_thread(Processor(config).process, bytes(data), True)
        except (ValueError, cv2.error) as exc:
            raise HTTPException(400, str(exc)) from exc

    async def run_image_estimate(request: Request, tag_id: int | None):
        # Alternate camera calibrations come from the selected local JSON file.
        raw_config = request.headers.get('x-camera-config')
        if raw_config and len(raw_config) > 12000:
            raise HTTPException(413, 'Calibration config is too large.')
        try:
            profile = json.loads(raw_config) if raw_config else load_config(config_path)
            raw = await request.body()
            if not raw or len(raw) > 100_000_000:
                raise ValueError('Image must be 1–16 MB.')
            frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError('Invalid image; import PNG or JPEG.')
            if max(frame.shape[:2]) > 12000 or frame.shape[0]*frame.shape[1] > 60_000_000:
                raise ValueError('Image dimension exceeds 12000 pixels.')
            result = await asyncio.to_thread(estimate_position, frame, profile, tag_id)
            return profile, result
        except (ValueError, TypeError, KeyError, cv2.error) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/image-position/capture')
    async def capture_image(request: Request):
        """Persist one browser webcam frame to the server's local pictures/ folder."""
        raw = await request.body()
        if not raw or len(raw) > 100_000_000:
            raise HTTPException(400, 'Captured frame must be 1–16 MB.')
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or max(frame.shape[:2]) > 12000 or frame.shape[0]*frame.shape[1] > 60_000_000:
            raise HTTPException(400, 'Invalid or oversized captured frame.')
        # Re-encode as PNG, rather than trusting arbitrary user-supplied bytes.
        ok, encoded = cv2.imencode('.png', frame)
        if not ok:
            raise HTTPException(500, 'Unable to encode captured frame.')
        name = (datetime.now(timezone.utc).strftime('image_%Y%m%d_%H%M%S_%f_')
                + uuid.uuid4().hex[:8] + '.png')
        PICTURES_DIR.mkdir(parents=True, exist_ok=True)
        path = PICTURES_DIR / name
        await asyncio.to_thread(path.write_bytes, encoded.tobytes())
        return {'saved': True, 'image_name': name, 'path': 'pictures/' + name,
                'width': frame.shape[1], 'height': frame.shape[0]}

    @app.post('/api/image-position')
    async def image_position(request: Request, tag_id: int | None = None):
        _, result = await run_image_estimate(request, tag_id)
        return result

    save_lock = asyncio.Lock()

    @app.post('/api/image-position/save')
    async def save_measurement(request: Request, true_distance_m: float,
                               reference_type: str = 'range', source: str = 'real',
                               image_name: str = 'captured_image.png',
                               tag_id: int | None = None):
        if not math.isfinite(true_distance_m) or true_distance_m <= 0:
            raise HTTPException(400, 'Measured ground-truth distance must be a positive finite number in meters.')
        if reference_type not in ('range', 'depth'):
            raise HTTPException(400, 'Reference type must be range or depth.')
        if source not in ('real', 'simulated'):
            raise HTTPException(400, 'Source must be real or simulated.')
        # Do not allow control characters / spreadsheet formula injection in exported CSV.
        image_name = Path(image_name.replace('\\', '/')).name[:180]
        if image_name.startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
            image_name = '_' + image_name
        if not image_name or any(ord(c) < 32 for c in image_name):
            raise HTTPException(400, 'Invalid image filename.')
        profile, result = await run_image_estimate(request, tag_id)
        estimate = result['distance_m'] if reference_type == 'range' else result['z_m']
        error = estimate - true_distance_m
        record = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                      image_name=image_name, source=source, tag_id=result['id'],
                      image_width=result['image_width'], image_height=result['image_height'],
                      tag_size_m=profile['apriltag']['tag_size_m'],
                      reference_type=reference_type, true_distance_m=true_distance_m,
                      estimated_distance_m=estimate, signed_error_m=error,
                      absolute_error_m=abs(error), relative_error_percent=100*error/true_distance_m,
                      x_m=result['x_m'], y_m=result['y_m'], z_m=result['z_m'],
                      estimated_range_m=result['distance_m'], estimated_depth_m=result['z_m'],
                      reprojection_rms_px=result['reprojection_rms_px'],
                      camera_profile='uploaded' if request.headers.get('x-camera-config') else 'default')
        async with save_lock:
            DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            if DATA_PATH.exists():
                with DATA_PATH.open('r', newline='', encoding='utf-8') as file:
                    if next(csv.reader(file), []) != MEASUREMENT_COLUMNS:
                        raise HTTPException(409, 'CSV column layout differs from expected format; rename or move the existing file before saving.')
            with DATA_PATH.open('a', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=MEASUREMENT_COLUMNS)
                if file.tell() == 0:
                    writer.writeheader()
                writer.writerow(record)
        return {'saved': True, 'csv': 'measurements/position_errors.csv', 'measurement': record}

    @app.get('/api/image-position/measurements.csv')
    async def download_measurements():
        if not DATA_PATH.exists():
            raise HTTPException(404, 'No measurements saved yet.')
        return FileResponse(DATA_PATH, media_type='text/csv', filename='position_errors.csv')

    @app.websocket('/ws')
    async def frames(ws: WebSocket):
        # Same-origin production, plus the local Vite development server.
        origin = ws.headers.get('origin', '')
        allowed = {f'http://{ws.headers.get("host")}', f'https://{ws.headers.get("host")}',
                   'http://localhost:5173', 'http://127.0.0.1:5173'}
        if origin not in allowed:
            await ws.close(code=1008)
            return
        await ws.accept()
        processor = Processor(config)
        try:
            while True:
                data = await ws.receive_bytes()
                try:
                    result = await asyncio.to_thread(processor.process, data)
                    await ws.send_json(result)
                except (ValueError, cv2.error) as exc:
                    await ws.send_json({'error': str(exc)})
        except WebSocketDisconnect:
            pass

    # Reuse update-1's existing calibration handlers in the main app, on port 8000.
    # Only register API routes: the standalone calibration app's '/' static mount
    # must not shadow the AprilTag Studio homepage.
    from calibrate_camera import create_app as create_calibration_app
    calibration_app = create_calibration_app(
        Path(config_path).resolve(), ROOT / 'calibration_runs')
    for route in calibration_app.router.routes:
        if getattr(route, 'path', '').startswith('/api/calibration'):
            app.router.routes.append(route)

    @app.get('/calibration')
    async def calibration_page():
        page = ROOT / 'frontend' / 'dist' / 'calibration.html'
        if not page.exists():
            raise HTTPException(404, 'Run npm run build in frontend first.')
        return FileResponse(page)

    dist = ROOT / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='ui')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'apriltag_config.json')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    print(f'Open http://localhost:{args.port}. Camera frames stay on this computer.')
    uvicorn.run(create_app(args.config), host='127.0.0.1', port=args.port, ws_max_size=8_000_000)

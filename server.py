"""Local webcam processing service. Run: python server.py"""
import argparse
import asyncio
import json
from pathlib import Path
import time

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from calibration import validate_calibration

ROOT = Path(__file__).resolve().parent


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    camera, tag = config['camera'], config['apriltag']
    for key in ('width', 'height'):
        if type(camera[key]) is not int or not 1 <= camera[key] <= 4096:
            raise ValueError(f'camera.{key} must be an integer from 1 to 4096')
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

    def process(self, data):
        start = time.perf_counter()
        if len(data) > 8_000_000:
            raise ValueError('Frame exceeds 8 MB limit.')
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Frame is not a valid encoded image.')
        height, width = frame.shape[:2]
        if max(width, height) > 4096:
            raise ValueError('Frame dimensions exceed 4096 pixels.')
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
                    calibration_width=c['calibration_width'], calibration_height=c['calibration_height'])

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

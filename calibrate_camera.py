"""Browser checkerboard calibration. Run: uv run python calibrate_camera.py"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shutil

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from calibration import validate_calibration

ROOT = Path(__file__).resolve().parent


class CalibrationSession:
    def __init__(self, width, height, columns=9, rows=6, square_mm=20, auto_resolution=False):
        if min(width, height) <= 0 or max(width, height) > 4096:
            raise ValueError('Capture dimensions must be between 1 and 4096.')
        if min(columns, rows) < 3 or not np.isfinite(square_mm) or square_mm <= 0:
            raise ValueError('Use at least 3x3 internal corners and a positive square size.')
        self.size = (width, height)
        self.auto_resolution = auto_resolution
        self.pattern = (columns, rows)
        self.square_mm = square_mm
        self.corners = []
        self.images = []
        self.result = None

    def capture(self, data):
        if len(self.images) >= 60:
            raise ValueError('60-view limit reached. Calculate or reset the session.')
        if not data or len(data) > 12_000_000:
            raise ValueError('Image is empty or exceeds 12 MB.')
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Invalid image.')
        actual_size = (frame.shape[1], frame.shape[0])
        if max(actual_size) > 4096:
            raise ValueError('Frame dimensions exceed 4096 pixels.')
        if (self.corners or not self.auto_resolution) and actual_size != self.size:
            raise ValueError(f'Capture must be exactly {self.size[0]}x{self.size[1]}. Resolution changed; reset captures before using the new mode.')
        found, corners = cv2.findChessboardCornersSB(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), self.pattern)
        if not found:
            raise ValueError(f'Board not found. Show all {self.pattern[0]}x{self.pattern[1]} internal corners, improve lighting, and hold still.')
        if any(float(np.sqrt(np.mean((corners-old)**2))) < 5 for old in self.corners):
            raise ValueError('This view is too similar to an existing capture. Move or tilt the board.')
        self.size = actual_size
        self.corners.append(corners.astype(np.float32))
        self.images.append(data)
        self.result = None
        return {'count': len(self.corners), 'corners': corners.reshape(-1,2).tolist()}

    def solve(self):
        if len(self.corners) < 12:
            raise ValueError('Capture at least 12 different views; 20–30 varied views are recommended.')
        points = np.zeros((self.pattern[0]*self.pattern[1],3), np.float32)
        points[:,:2] = np.mgrid[0:self.pattern[0],0:self.pattern[1]].T.reshape(-1,2) * (self.square_mm/1000)
        rms, K, dist, rotations, translations = cv2.calibrateCamera(
            [points]*len(self.corners), self.corners, self.size, None, None)
        validate_calibration(K, dist)
        if not np.isfinite(rms):
            raise ValueError('Calibration failed. Recapture varied, sharp views.')
        per_view = []
        for detected, r, t in zip(self.corners, rotations, translations):
            projected, _ = cv2.projectPoints(points, r, t, K, dist)
            per_view.append(float(np.sqrt(np.mean(np.sum((projected-detected)**2, axis=2)))))
        self.result = {'K':K.tolist(), 'dist':dist.reshape(-1).tolist(), 'rms_px':float(rms),
                       'per_view_rms_px':per_view, 'image_width':self.size[0], 'image_height':self.size[1],
                       'internal_corners':list(self.pattern), 'square_size_mm':self.square_mm,
                       'views':len(self.corners)}
        return self.result


def save_result(session, config_path, output_root):
    if session.result is None:
        raise ValueError('Calculate a calibration before saving.')
    result = session.result
    # Read at save time, preserving unrelated user edits and all tag settings.
    config = json.loads(config_path.read_text(encoding='utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    output = output_root / stamp
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(config_path, output/'apriltag_config.before.json')
    np.savez(output/'camera_calibration.npz', K=np.array(result['K']), dist=np.array(result['dist']),
             image_size=np.array(session.size))
    (output/'calibration_report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for i, data in enumerate(session.images, 1):
        (output/f'view_{i:02d}.png').write_bytes(data)
    config['camera'].update(width=session.size[0], height=session.size[1],
        calibration_width=session.size[0], calibration_height=session.size[1], K=result['K'], dist=result['dist'])
    temporary = config_path.with_name(config_path.name+'.calibration.tmp')
    temporary.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    temporary.replace(config_path)
    return {'config':str(config_path), 'output_directory':str(output), 'rms_px':result['rms_px']}


def create_app(config_path, output_root, columns=9, rows=6, square_mm=20):
    config = json.loads(config_path.read_text(encoding='utf-8'))
    session = CalibrationSession(config['camera']['width'], config['camera']['height'], columns, rows, square_mm, auto_resolution=True)
    token = secrets.token_urlsafe(32)
    lock = asyncio.Lock()
    app = FastAPI(title='Camera Calibration')

    @app.get('/')
    async def page():
        return FileResponse(ROOT/'frontend/dist/calibration.html')

    @app.get('/api/calibration')
    async def settings():
        return {'width':session.size[0], 'height':session.size[1], 'columns':columns, 'rows':rows,
                'square_mm':square_mm, 'token':token, 'count':len(session.corners)}

    @app.post('/api/calibration/{action}')
    async def action(action: str, request: Request):
        if request.headers.get('x-calibration-token') != token:
            raise HTTPException(403, 'Invalid calibration session token.')
        async with lock:
            try:
                if action == 'capture':
                    return await asyncio.to_thread(session.capture, await request.body())
                if action == 'calculate':
                    return await asyncio.to_thread(session.solve)
                if action == 'undo':
                    if session.corners:
                        session.corners.pop(); session.images.pop()
                    session.result = None
                    return {'count':len(session.corners)}
                if action == 'reset':
                    session.corners.clear(); session.images.clear(); session.result = None
                    return {'count':0}
                if action == 'save':
                    return await asyncio.to_thread(save_result, session, config_path, output_root)
                raise HTTPException(404, 'Unknown action')
            except (ValueError, cv2.error) as exc:
                raise HTTPException(400, str(exc)) from exc
    app.mount('/', StaticFiles(directory=ROOT/'frontend/dist'), name='assets')
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'apriltag_config.json')
    parser.add_argument('--output',type=Path,default=ROOT/'calibration_runs')
    parser.add_argument('--columns',type=int,default=9,help='Internal corner columns, not squares')
    parser.add_argument('--rows',type=int,default=6,help='Internal corner rows, not squares')
    parser.add_argument('--square-size-mm',type=float,default=20,help='Measured printed square edge in mm')
    parser.add_argument('--port',type=int,default=8001)
    args = parser.parse_args()
    print(f'Open http://localhost:{args.port}. Stop the distance camera first. Use one calibration tab.')
    uvicorn.run(create_app(args.config.resolve(),args.output.resolve(),args.columns,args.rows,args.square_size_mm),
                host='127.0.0.1',port=args.port)

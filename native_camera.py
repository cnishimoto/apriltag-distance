"""Native OpenCV camera capture for modes browsers cannot reliably negotiate.

On Windows this deliberately uses DirectShow and requests MJPG before setting the
resolution, matching the known-working 4K X-T5 test path.
"""
from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


@dataclass(frozen=True)
class CameraSettings:
    index: int
    width: int
    height: int
    fps: float
    fourcc: str
    backend: str


class NativeCamera:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cap: cv2.VideoCapture | None = None
        self._settings: CameraSettings | None = None

    @staticmethod
    def _fourcc_text(value: float) -> str:
        code = int(value)
        return ''.join(chr((code >> (8 * i)) & 0xFF) for i in range(4)).strip('\x00 ')

    def stop(self) -> None:
        with self._lock:
            if self._cap is not None:
                self._cap.release()
            self._cap = None
            self._settings = None

    def start(self, index: int, width: int | None, height: int | None,
              fps: float = 30.0) -> CameraSettings:
        if index < 0 or index > 32:
            raise ValueError('Camera index must be between 0 and 32.')
        if (width is None) != (height is None):
            raise ValueError('Width and height must both be supplied, or both omitted.')
        if width is not None and (width < 1 or height is None or height < 1 or width > 12000 or height > 12000):
            raise ValueError('Camera dimensions must be between 1 and 12000 pixels.')
        if not (1 <= fps <= 120):
            raise ValueError('FPS must be between 1 and 120.')

        with self._lock:
            self.stop()
            backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(f'Could not open native camera index {index}. Close other camera apps and check the index.')

            # IMPORTANT: set MJPG before dimensions. This is the same ordering as
            # the user's working 3840x2160 DirectShow test and avoids uncompressed
            # bandwidth limits on cameras that expose 4K through MJPEG.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            if width is not None and height is not None:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            frame = None
            for _ in range(5):
                ok, candidate = cap.read()
                if ok and candidate is not None:
                    frame = candidate
            if frame is None:
                cap.release()
                raise RuntimeError('Camera opened but did not return a frame.')

            actual_h, actual_w = frame.shape[:2]
            if width is not None and height is not None and (actual_w, actual_h) != (width, height):
                cap.release()
                raise RuntimeError(
                    f'Native camera returned {actual_w}x{actual_h}, not requested {width}x{height}. '
                    'Try another camera index or mode.'
                )

            actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
            fourcc = self._fourcc_text(cap.get(cv2.CAP_PROP_FOURCC)) or 'unknown'
            backend_name = 'DirectShow' if backend == cv2.CAP_DSHOW else 'OpenCV default'
            self._cap = cap
            self._settings = CameraSettings(index, actual_w, actual_h, actual_fps, fourcc, backend_name)
            return self._settings

    def settings(self) -> CameraSettings | None:
        with self._lock:
            return self._settings

    def frame(self, image_format: str = 'jpeg', quality: int = 95) -> tuple[bytes, str, int, int]:
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                raise RuntimeError('Native camera is not running.')
            ok, frame = self._cap.read()
            if not ok or frame is None:
                raise RuntimeError('Failed to read a frame from the native camera.')
            height, width = frame.shape[:2]
            if image_format == 'png':
                ok, encoded = cv2.imencode('.png', frame)
                media_type = 'image/png'
            else:
                quality = max(50, min(int(quality), 100))
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                media_type = 'image/jpeg'
            if not ok:
                raise RuntimeError('Failed to encode native camera frame.')
            return encoded.tobytes(), media_type, width, height


def register_native_camera_routes(app: FastAPI, manager: NativeCamera) -> None:
    @app.post('/api/native-camera/start')
    async def native_start(request: Request):
        try:
            body = await request.json()
            index = int(body.get('index', 0))
            width = body.get('width')
            height = body.get('height')
            width = None if width is None else int(width)
            height = None if height is None else int(height)
            fps = float(body.get('fps', 30))
            settings = await asyncio.to_thread(manager.start, index, width, height, fps)
            return settings.__dict__
        except (ValueError, TypeError, RuntimeError, cv2.error) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/native-camera/stop')
    async def native_stop():
        await asyncio.to_thread(manager.stop)
        return {'stopped': True}

    @app.get('/api/native-camera/status')
    async def native_status():
        settings = manager.settings()
        return {'running': settings is not None, 'settings': None if settings is None else settings.__dict__}

    @app.get('/api/native-camera/frame')
    async def native_frame(format: str = 'jpeg', quality: int = 95):
        if format not in ('jpeg', 'png'):
            raise HTTPException(400, 'format must be jpeg or png')
        try:
            data, media_type, width, height = await asyncio.to_thread(manager.frame, format, quality)
        except (RuntimeError, cv2.error) as exc:
            raise HTTPException(409, str(exc)) from exc
        return Response(data, media_type=media_type, headers={
            'Cache-Control': 'no-store',
            'X-Frame-Width': str(width),
            'X-Frame-Height': str(height),
        })

import numpy as np
import cv2
import native_camera


def test_native_camera_requests_mjpg_before_4k(monkeypatch):
    calls = []
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')

    class FakeCapture:
        def __init__(self, index, backend):
            self.index = index
            self.backend = backend
            self.opened = True
            self.props = {
                cv2.CAP_PROP_FRAME_WIDTH: 3840,
                cv2.CAP_PROP_FRAME_HEIGHT: 2160,
                cv2.CAP_PROP_FPS: 30.0,
                cv2.CAP_PROP_FOURCC: float(fourcc),
            }

        def isOpened(self): return self.opened
        def set(self, prop, value):
            calls.append((prop, value))
            self.props[prop] = value
            return True
        def get(self, prop): return self.props.get(prop, 0)
        def read(self): return True, np.zeros((2160, 3840, 3), np.uint8)
        def release(self): self.opened = False

    monkeypatch.setattr(native_camera.cv2, 'VideoCapture', FakeCapture)
    camera = native_camera.NativeCamera()
    settings = camera.start(0, 3840, 2160, 30)

    assert settings.width == 3840 and settings.height == 2160
    assert settings.fourcc == 'MJPG'
    assert calls[0][0] == cv2.CAP_PROP_FOURCC
    assert next(i for i, call in enumerate(calls) if call[0] == cv2.CAP_PROP_FRAME_WIDTH) > 0
    assert next(i for i, call in enumerate(calls) if call[0] == cv2.CAP_PROP_FRAME_HEIGHT) > 0

import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from server import Processor, create_app, load_config


def configuration():
    c = json.loads((Path(__file__).resolve().parents[1] / 'apriltag_config.json').read_text())
    c['camera'].update(width=640, height=480, calibration_width=640, calibration_height=480,
                       K=[[800,0,320],[0,800,240],[0,0,1]], dist=[0,0,0,0,0])
    return c


def image(tag=True, width=640):
    frame = np.full((480,width), 255, dtype=np.uint8)
    if tag:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        marker = cv2.aruco.generateImageMarker(dictionary, 7, 160)
        frame[160:320,240:400] = marker
    return cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_known_distance_and_loss():
    processor = Processor(configuration())
    result = processor.process(image())
    assert len(result['tags']) == 1
    tag = result['tags'][0]
    assert tag['id'] == 7
    assert tag['distance_m'] == pytest.approx(0.8, abs=0.025)
    assert tag['depth_m'] == pytest.approx(0.8, abs=0.025)
    assert tag['reprojection_error_px'] < 1
    assert processor.process(image(False))['tags'] == []
    assert processor.filtered == {}


def test_missing_calibration_detects_without_fake_range():
    c = configuration(); c['camera']['K'] = None
    result = Processor(c).process(image())
    assert result['tags'][0]['distance_m'] is None
    assert 'Calibration missing' in result['warning']


def test_wrong_resolution_disables_range():
    result = Processor(configuration()).process(image(width=800))
    assert result['tags'][0]['distance_m'] is None
    assert 'Resolution mismatch' in result['warning']


def test_invalid_frame():
    with pytest.raises(ValueError): Processor(configuration()).process(b'not an image')


def test_websocket_round_trip_and_recovery(tmp_path):
    path = tmp_path / 'config.json'; path.write_text(json.dumps(configuration()))
    with TestClient(create_app(path)) as client:
        assert client.get('/api/config').json()['calibrated']
        with client.websocket_connect('/ws', headers={'origin':'http://testserver'}) as ws:
            ws.send_bytes(b'invalid'); assert 'error' in ws.receive_json()
            ws.send_bytes(image()); result = ws.receive_json()
            assert result['tags'][0]['distance_m'] == pytest.approx(0.8, abs=0.025)
        assert client.get('/').status_code == 200


def test_config_validation(tmp_path):
    c = configuration(); c['apriltag']['tag_size_m'] = -1
    path = tmp_path/'bad.json'; path.write_text(json.dumps(c))
    with pytest.raises(ValueError): load_config(path)

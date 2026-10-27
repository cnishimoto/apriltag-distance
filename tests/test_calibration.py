import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from calibrate_camera import CalibrationSession, save_result, create_app
from fastapi.testclient import TestClient


def test_board_detection_and_invalid_captures():
    image=np.full((720,1280,3),255,np.uint8)
    for row in range(7):
        for col in range(10):
            if (row+col)%2==0: image[150+row*50:200+row*50,300+col*50:350+col*50]=0
    data=cv2.imencode('.png',image)[1].tobytes();session=CalibrationSession(1280,720)
    assert session.capture(data)['count']==1
    assert len(session.corners[0])==54
    with pytest.raises(ValueError,match='similar'):session.capture(data)
    with pytest.raises(ValueError,match='at least 12'):session.solve()
    with pytest.raises(ValueError,match='exactly'):CalibrationSession(640,480).capture(data)


def test_intrinsics_recovery_and_backup(tmp_path):
    session=CalibrationSession(1280,720)
    K=np.array([[900.,0,640],[0,910.,360],[0,0,1]]);dist=np.array([-.08,.01,.001,-.001,0.])
    points=np.zeros((54,3),np.float32);points[:,:2]=np.mgrid[0:9,0:6].T.reshape(-1,2)*.02
    rng=np.random.default_rng(12)
    for _ in range(24):
        r=rng.uniform(-.5,.5,3);t=np.array([rng.uniform(-.2,.1),rng.uniform(-.15,.05),rng.uniform(.45,.9)])
        corners,_=cv2.projectPoints(points,r,t,K,dist);session.corners.append(corners)
    result=session.solve()
    assert result['rms_px']<.001
    assert np.allclose(result['K'],K,atol=.1)
    config={'camera':{'id':0,'K':None},'apriltag':{'tag_size_m':.16}}
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    saved=save_result(session,path,tmp_path/'runs')
    assert json.loads(path.read_text())['apriltag']==config['apriltag']
    assert json.loads(path.read_text())['camera']['calibration_width']==1280
    assert json.loads((Path(saved['output_directory'])/'apriltag_config.before.json').read_text())==config
    with np.load(Path(saved['output_directory'])/'camera_calibration.npz') as data:assert np.allclose(data['K'],K,atol=.1)


def test_routes(tmp_path):
    path=tmp_path/'config.json';path.write_text(json.dumps({'camera':{'width':1280,'height':720}}))
    with TestClient(create_app(path,tmp_path/'runs')) as client:
        assert client.get('/').status_code==200
        token=client.get('/api/calibration').json()['token']
        assert client.post('/api/calibration/reset').status_code==403
        assert client.post('/api/calibration/reset',headers={'x-calibration-token':token}).json()=={'count':0}
        assert client.post('/api/calibration/save',headers={'x-calibration-token':token}).status_code==400


def test_auto_resolution_locks_only_accepted_views_and_reset_unlocks():
    def board(width,height,square):
        image=np.full((height,width,3),255,np.uint8)
        for row in range(7):
            for col in range(10):
                if (row+col)%2==0:
                    image[30+row*square:30+(row+1)*square,40+col*square:40+(col+1)*square]=0
        return cv2.imencode('.png',image)[1].tobytes()
    session=CalibrationSession(1280,720,auto_resolution=True)
    blank=cv2.imencode('.png',np.full((480,640,3),255,np.uint8))[1].tobytes()
    with pytest.raises(ValueError,match='Board not found'):session.capture(blank)
    assert session.size==(1280,720)
    session.capture(board(640,480,35))
    assert session.size==(640,480)
    with pytest.raises(ValueError,match='Resolution changed'):session.capture(board(800,600,45))
    session.corners.clear();session.images.clear();session.result=None
    session.capture(board(800,600,45))
    assert session.size==(800,600)

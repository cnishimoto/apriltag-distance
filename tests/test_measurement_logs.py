import csv
import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from measurement_logs import COLUMNS, MeasurementLogs
from server import create_app
from test_server import configuration


def row(truth=2.0):
    result = dict.fromkeys(COLUMNS, None)
    result.update(schema_version=1, record_id=str(uuid4()), frame_id=str(uuid4()), trial_id=str(uuid4()),
                  logged_at_utc='2026-10-30T00:00:00Z', captured_at_utc='2026-10-30T00:00:00Z',
                  trial_label='trial one', tag_id=7, ground_truth_m=truth, distance_m=2.1,
                  raw_distance_m=2.2, error_m=.1 if truth else None,
                  absolute_error_m=.1 if truth else None, sample_count=3,
                  mean_raw_distance_m=2, total_stdev_m=1, min_raw_distance_m=1, max_raw_distance_m=3,
                  mean_error_m=0 if truth else None, mean_absolute_error_m=2/3 if truth else None,
                  rmse_m=(2/3)**.5 if truth else None, image_width=640, image_height=480,
                  source_kind='camera', source_name='Brio', dictionary='DICT_APRILTAG_36h11',
                  tag_size_m=.16, smoothing_alpha=.35)
    result['metadata_json']=json.dumps({'record_id': result['record_id'], 'ground_truth_m': truth})
    return result


def test_csv_append_roundtrip_idempotency_and_import(tmp_path):
    logs=MeasurementLogs(tmp_path)
    logs.create('trial.csv')
    first=row();second=row(None)
    assert logs.append('trial.csv',first)['rows']==1
    assert logs.append('trial.csv',first)['duplicate']
    assert logs.append('trial.csv',second)['rows']==2
    saved=logs.read(tmp_path/'trial.csv')
    assert saved[1]['ground_truth_m']=='' and saved[1]['error_m']==''
    assert float(saved[0]['total_stdev_m'])==1
    logs.create('imported.csv',saved)
    assert logs.read(tmp_path/'imported.csv')==saved
    with pytest.raises(ValueError, match='already exists'):logs.create('trial.csv')
    assert logs.read(tmp_path/'trial.csv')==saved
    changed=dict(first, distance_m=3)
    with pytest.raises(ValueError, match='different data'):logs.append('trial.csv',changed)


def test_validation_and_formula_text(tmp_path):
    logs=MeasurementLogs(tmp_path);logs.create('trial.csv')
    for name in ['../outside.csv','a/b.csv','..csv','/tmp/test.csv','test.xlsx']:
        with pytest.raises(ValueError):logs.create(name)
    for changes in [{'distance_m':float('nan')},{'ground_truth_m':-1},{'sample_count':1}, {'distance_m':None}, {'sample_count':1.5}]:
        with pytest.raises(ValueError):logs.append('trial.csv',dict(row(),**changes))
    data=row();data['trial_label']='=HYPERLINK("bad")';data['source_name']='@SUM(1)'
    logs.append('trial.csv',data)
    saved=logs.read(tmp_path/'trial.csv')[0]
    assert saved['trial_label'].startswith("'=") and saved['source_name'].startswith("'@")
    assert logs.append('trial.csv',data)['duplicate']
    with pytest.raises(ValueError,match='not an app'):logs.parse(io.StringIO('name,value\na,1\n'))


def test_http_create_append_download_import_and_token(tmp_path):
    config=tmp_path/'config.json';config.write_text(json.dumps(configuration()))
    with TestClient(create_app(config, tmp_path/'logs')) as client:
        headers={'x-log-token':client.get('/api/config').json()['log_token']}
        assert client.post('/api/logs',json={'name':'test.csv'}).status_code==403
        assert client.post('/api/logs',json={'name':'test.csv'},headers=headers).status_code==200
        assert client.post('/api/logs/test.csv/rows',json=row(),headers=headers).json()['rows']==1
        data=client.get('/api/logs/test.csv')
        assert data.status_code==200
        assert list(csv.DictReader(io.StringIO(data.content.decode('utf-8-sig'))))[0]['tag_id']=='7'
        assert client.post('/api/logs/import?name=copy.csv',content=data.content,headers=headers).json()['rows']==1
        assert client.get('/api/logs').json()['logs']==['copy.csv','test.csv']
        assert client.post('/api/logs/import?name=copy.csv',content=data.content,headers=headers).status_code==400
        assert client.post('/api/logs',content=b'broken',headers=headers).status_code==400
        assert client.post('/api/logs/missing.csv/rows',json=row(),headers=headers).status_code==404
        assert client.post('/api/logs/test.csv/rows',content=b'{}',headers=headers).status_code==400

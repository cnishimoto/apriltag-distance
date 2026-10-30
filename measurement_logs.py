"""Local, append-only CSV measurement logs. No spreadsheet dependencies required."""
import asyncio
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

COLUMNS = [
    'schema_version', 'record_id', 'frame_id', 'trial_id', 'logged_at_utc', 'captured_at_utc',
    'trial_label', 'tag_id', 'ground_truth_m', 'distance_m', 'raw_distance_m',
    'error_m', 'absolute_error_m', 'percent_error', 'raw_error_m', 'depth_m',
    'sample_count', 'mean_raw_distance_m', 'total_stdev_m', 'min_raw_distance_m',
    'max_raw_distance_m', 'mean_error_m', 'mean_absolute_error_m', 'rmse_m',
    'reprojection_error_px', 'processing_ms', 'analysis_fps', 'image_width', 'image_height',
    'source_kind', 'source_name', 'tag_size_m', 'dictionary', 'smoothing_alpha',
    'warning', 'frame_archive', 'metadata_json',
]
TEXT_COLUMNS = {'schema_version', 'record_id', 'frame_id', 'trial_id', 'logged_at_utc',
                'captured_at_utc', 'trial_label', 'source_kind', 'source_name', 'dictionary',
                'warning', 'frame_archive', 'metadata_json'}
MAX_BYTES = 25_000_000


def safe_text(value):
    text = str(value)
    # Prevent text from becoming a formula when opened by Excel/Sheets.
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text


def validate_row(row):
    if set(row) != set(COLUMNS):
        raise ValueError('CSV columns do not match this app’s measurement log format. Create a new log first.')
    if str(row['schema_version']) != '1':
        raise ValueError('Unsupported measurement log version.')
    for name in ('record_id', 'frame_id', 'trial_id'):
        try:
            UUID(str(row[name]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f'Invalid {name}.') from exc
    for name in set(COLUMNS) - TEXT_COLUMNS:
        value = row[name]
        if value is None or value == '':
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{name} must be a number or blank.') from exc
        if isinstance(value, bool) or not math.isfinite(number):
            raise ValueError(f'{name} must be finite.')
    for name in ('tag_id', 'image_width', 'image_height', 'sample_count'):
        value = float(row[name]) if row[name] not in ('', None) else -1
        minimum = 0 if name == 'tag_id' else 1
        if value < minimum or not value.is_integer():
            raise ValueError(f'Invalid {name}.')
    for name in ('distance_m', 'raw_distance_m', 'mean_raw_distance_m'):
        if row[name] in ('', None) or float(row[name]) < 0:
            raise ValueError('A valid distance measurement is required to append a row.')
    if row['ground_truth_m'] not in ('', None) and float(row['ground_truth_m']) <= 0:
        raise ValueError('Ground truth must be positive or blank.')
    if float(row['sample_count']) < 2 and row['total_stdev_m'] not in ('', None):
        raise ValueError('Standard deviation requires at least two samples.')
    metadata = json.loads(str(row['metadata_json']))
    if not isinstance(metadata, dict) or metadata.get('record_id') != str(row['record_id']):
        raise ValueError('Metadata must match the row record ID.')
    return {key: ('' if row[key] is None else safe_text(row[key]) if key in TEXT_COLUMNS else row[key]) for key in COLUMNS}


class MeasurementLogs:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,95}\.csv', name) or '..' in name:
            raise ValueError('Use a CSV name with letters, numbers, spaces, hyphens or underscores (up to 100 characters).')
        path = self.root / name
        if path.is_symlink():
            raise ValueError('Symbolic links cannot be used as logs.')
        return path

    def read(self, path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Log exceeds 25 MB. Create a new log.')
        with path.open(encoding='utf-8-sig', newline='') as file:
            return self.parse(file)

    def parse(self, file):
        # Metadata can include complete intrinsics and detection results.
        csv.field_size_limit(MAX_BYTES)
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise ValueError('This CSV is not an app measurement log. Import a CSV previously created by this app, or create a new one.')
        rows = [validate_row(row) for row in reader]
        ids = [row['record_id'] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError('The CSV contains duplicate record IDs.')
        return rows

    def write(self, path, rows):
        self.root.mkdir(parents=True, exist_ok=True)
        buffer = io.StringIO(newline=''); writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
        writer.writeheader(); writer.writerows(rows)
        data = buffer.getvalue().encode('utf-8-sig')
        if len(data) > MAX_BYTES:
            raise ValueError('Log would exceed 25 MB. Create a new log.')
        fd, temporary = tempfile.mkstemp(dir=self.root, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data); file.flush(); os.fsync(file.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def create(self, name, rows=None):
        path = self.path(name)
        if path.exists():
            raise ValueError('A log with this name already exists. Select it to append, or choose a new name.')
        self.write(path, rows or [])
        return {'name': name, 'rows': len(rows or [])}

    def append(self, name, row):
        row = validate_row(row); path = self.path(name)
        rows = self.read(path)
        for old in rows:
            if old['record_id'] == row['record_id']:
                # A retry must not duplicate a measurement or silently change it.
                if any(str(old[key]) != str(row[key]) for key in COLUMNS):
                    raise ValueError('This record ID already exists with different data.')
                return {'name': name, 'rows': len(rows), 'duplicate': True}
        rows.append(row); self.write(path, rows)
        return {'name': name, 'rows': len(rows), 'duplicate': False}


def log_router(root, token):
    router = APIRouter(prefix='/api/logs'); logs = MeasurementLogs(root); lock = asyncio.Lock()

    async def body(request, limit=1_000_000):
        if request.headers.get('x-log-token') != token:
            raise HTTPException(403, 'Refresh the page to renew the logging session.')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit: raise HTTPException(413, 'Request exceeds the size limit.')
        return bytes(data)

    async def run(operation):
        async with lock:
            try:
                return await asyncio.to_thread(operation)
            except FileNotFoundError as exc:
                raise HTTPException(404, 'Log not found. Refresh the list.') from exc
            except PermissionError as exc:
                raise HTTPException(409, 'Cannot write the log. Close it in Excel and check folder permissions.') from exc
            except (ValueError, TypeError, KeyError, csv.Error, UnicodeError) as exc:
                raise HTTPException(400, str(exc)) from exc

    @router.get('')
    async def listing():
        return {'logs': sorted(p.name for p in logs.root.glob('*.csv') if not p.is_symlink()),
                'folder': str(logs.root.resolve())}

    @router.post('')
    async def create(request: Request):
        data = await body(request)
        return await run(lambda: logs.create(json.loads(data)['name']))

    @router.post('/import')
    async def import_log(request: Request):
        data = await body(request, MAX_BYTES)
        return await run(lambda: logs.create(request.query_params.get('name', ''), logs.parse(io.StringIO(data.decode('utf-8-sig'), newline=''))))

    @router.post('/{name}/rows')
    async def append(name: str, request: Request):
        data = await body(request)
        return await run(lambda: logs.append(name, json.loads(data)))

    @router.get('/{name}')
    async def download(name: str):
        path = await run(lambda: logs.path(name))
        if not path.is_file(): raise HTTPException(404, 'Log not found.')
        return FileResponse(path, media_type='text/csv', filename=name)

    return router

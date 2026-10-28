"""Single-image AprilTag pose estimation. Callable from CLI or web API.

Examples:
    python apriltag_position.py photo.png
    python apriltag_position.py sim.png --config sim_config.json --id 0
"""
import argparse
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from calibration import validate_calibration


def estimate_position(image, config, tag_id=None):
    """Return one raw tag pose in meters, raising ValueError on ambiguous inputs.

    image: BGR ndarray; config: dict with camera K/dist and AprilTag size.
    Coordinates: +x right, +y down, +z forward, relative to camera.
    """
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Expected a decoded color image.')
    camera, tag = config['camera'], config['apriltag']
    if camera.get('K') is None or camera.get('dist') is None:
        raise ValueError('Camera calibration K and dist are required.')
    width, height = image.shape[1], image.shape[0]
    calibrated = (camera['calibration_width'], camera['calibration_height'])
    if (width, height) != calibrated:
        raise ValueError(f'Image resolution {width}x{height} differs from calibration '
                         f'{calibrated[0]}x{calibrated[1]}. Use a matching '
                         'camera calibration; do not resize/crop to hide mismatch.')
    K = np.asarray(camera['K'], np.float64)
    dist = np.asarray(camera['dist'], np.float64).reshape(-1)
    validate_calibration(K, dist)
    size = float(tag['tag_size_m'])
    if not np.isfinite(size) or size <= 0:
        raise ValueError('tag_size_m must be positive.')
    name = tag.get('dictionary', 'DICT_APRILTAG_36h11')
    if not name.startswith('DICT_APRILTAG_') or not hasattr(cv2.aruco, name):
        raise ValueError('Invalid AprilTag dictionary.')
    refinement = tag.get('corner_refinement', 'CORNER_REFINE_SUBPIX')
    if refinement not in ('CORNER_REFINE_NONE', 'CORNER_REFINE_SUBPIX',
                          'CORNER_REFINE_CONTOUR', 'CORNER_REFINE_APRILTAG'):
        raise ValueError('Invalid corner refinement setting.')
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = getattr(cv2.aruco, refinement)
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name)), parameters)
    corners, ids, _ = detector.detectMarkers(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    if ids is None:
        raise ValueError('No AprilTag detected.')
    matches = [(int(i), c.reshape(4, 2).astype(np.float32)) for i, c in zip(ids.flatten(), corners)]
    if tag_id is not None:
        matches = [(i, c) for i, c in matches if i == tag_id]
        if not matches:
            raise ValueError(f'Tag ID {tag_id} not detected.')
    if len(matches) != 1:
        raise ValueError('Expected exactly one AprilTag; select a tag ID if multiple are visible.')
    detected_id, pixels = matches[0]
    s = size / 2
    model = np.array([[-s,s,0],[s,s,0],[s,-s,0],[-s,-s,0]], dtype=np.float32)
    ok, rvec, tvec = cv2.solvePnP(model, pixels, K, dist, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok or not np.isfinite(tvec).all() or not np.isfinite(rvec).all() or tvec[2,0] <= 0:
        raise ValueError('Could not estimate a valid pose.')
    projected, _ = cv2.projectPoints(model, rvec, tvec, K, dist)
    residual = projected.reshape(4,2) - pixels
    x,y,z = [float(v) for v in tvec.reshape(3)]
    return {'id':detected_id, 'x_m':x, 'y_m':y, 'z_m':z,
            'distance_m':float(np.linalg.norm(tvec)),
            'reprojection_rms_px':float(np.sqrt(np.mean(np.sum(residual**2,axis=1)))),
            'corners_px':pixels.tolist(), 'image_width':width, 'image_height':height}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('apriltag_config.json'))
    parser.add_argument('--id', type=int)
    parser.add_argument('--json', action='store_true', help='Print machine-readable JSON')
    args = parser.parse_args()
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        parser.error(f'Cannot open image: {args.image}')
    result = estimate_position(image, json.loads(args.config.read_text(encoding='utf-8')), args.id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"X: {result['x_m']:+.6f} m\nY: {result['y_m']:+.6f} m\nZ: {result['z_m']:+.6f} m")


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, ValueError, cv2.error) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)

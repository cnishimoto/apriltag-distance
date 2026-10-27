"""Start the local web app, or import an existing NPZ calibration into JSON."""
import argparse
import json
from pathlib import Path
import numpy as np
from calibration import validate_calibration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('apriltag_config.json'))
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--import-calibration', type=Path)
    parser.add_argument('--calibration-size', type=int, nargs=2, metavar=('WIDTH','HEIGHT'))
    args = parser.parse_args()
    if args.import_calibration:
        if not args.calibration_size or min(args.calibration_size) <= 0:
            parser.error('--import-calibration requires --calibration-size WIDTH HEIGHT.')
        with np.load(args.import_calibration, allow_pickle=False) as data:
            K = np.asarray(data['K'], dtype=float)
            dist = np.asarray(data['dist'], dtype=float).reshape(-1)
        validate_calibration(K, dist)
        config = json.loads(args.config.read_text(encoding='utf-8'))
        config['camera'].update(K=K.tolist(), dist=dist.tolist(),
                                calibration_width=args.calibration_size[0],
                                calibration_height=args.calibration_size[1])
        args.config.write_text(json.dumps(config, indent=2)+'\n', encoding='utf-8')
        print(f'Imported calibration into {args.config}. Set camera.width/height to this calibration resolution.')
        return
    import uvicorn
    from server import create_app
    print(f'Open http://localhost:{args.port}. Press Ctrl+C here to stop the server.')
    uvicorn.run(create_app(args.config), host='127.0.0.1', port=args.port, ws_max_size=8_000_000)


if __name__ == '__main__':
    main()

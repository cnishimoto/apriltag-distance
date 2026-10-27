# AprilTag Live

A local web GUI for the AprilTag distance script: browser webcam capture, tag outlines, per-tag smoothed range, raw forward depth, completed-analysis FPS, round-trip latency, and reprojection error. Vite + TypeScript build the UI; FastAPI + OpenCV run the detector. No SQL/database is needed. Frames are processed in memory and not recorded.

## Run (Windows, macOS, Linux)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed. Extract this entire folder, then open a terminal inside it. The project supports Python 3.10 or newer.

```bash
uv sync --locked
uv run --locked python apriltag_distance.py
```

`uv sync` creates the project's `.venv` and installs the versions in `uv.lock`. No manual environment activation or pip commands are needed. `pyproject.toml` declares dependencies; `uv.lock` records the resolved versions. `--locked` prevents an unexpected lockfile update. Plain `uv sync` also works.

Open **http://localhost:8000** in your browser. Click **Start camera**, allow camera access, and select the intended webcam. Stop before switching cameras. The browser opens your computer's camera; Python does not use `VideoCapture` for this app. Stop releases the camera, and hiding the tab pauses the session. Stop the server with Ctrl+C.

The refreshed interface includes labeled setup controls, a responsive preview/measurement layout, keyboard focus states, explicit status/error messages, expandable diagnostics, and calibration progress and review panels. The distance page offers a Saved calibration resolution option when calibration exists.

The built frontend is included in `frontend/dist`, so Node.js is NOT required to run this download. `uv run --locked python server.py` is an alternative launch command. Do not open index.html directly.

## Calibrate your camera from scratch

1. Print `checkerboard_9x6_20mm.pdf` in landscape at **Actual size / 100%**, with Fit to page disabled. It has 10x7 squares, 9x6 internal corners, and 20 mm square edges. Measure the 100 mm scale line; attach the print to a rigid, flat board. Do not use a bent sheet. Keep the white margin.
2. If replacing an older download, copy your existing `apriltag_config.json` into this folder first so your tag settings are retained. Choose Auto or a manual resolution in the web page; you do not need to edit width/height in JSON. Stop the distance app's camera so the calibration page can use it.
3. Run:

```bash
uv sync --locked
uv run --locked python calibrate_camera.py
```

4. Open **http://localhost:8001**. Start the camera, choose the Brio 101 (stop before switching), and capture 20–30 sharp, varied views. Move the board around the image, tilt it about both axes, and vary distance. Keep the full board visible and hold still during each capture. Captures are lossless PNGs; exact duplicates/very similar views are rejected. Use one calibration tab. Camera selection is locked once views exist; reset captures to change cameras.
5. Click **Calculate calibration** (minimum 12 views), review RMS and per-view reprojection errors, then click **Save to app config**. The page warns above 1 pixel RMS as a practical review cue, not an accuracy guarantee. This solver does not automatically remove outliers or prove adequate pose diversity. Use Remove last capture or Reset to discard poor views.
6. Saving updates `K`, `dist`, calibration dimensions and capture dimensions in your JSON, preserving other settings. A timestamped `calibration_runs` folder contains the prior JSON backup, captured PNGs, `camera_calibration.npz`, and `calibration_report.json`. No separate import is required. Unsaved captures are held in memory and lost when the calibration server stops.
7. Stop the calibration server with Ctrl+C, restart `uv run --locked python apriltag_distance.py`, and validate AprilTag readings at measured distances and angles. Use the same physical camera, image mode/crop and focus settings.

If the measured printed square size differs, pass the measured value, for example `--square-size-mm 19.8`. Nonuniform printer stretching cannot be fixed with one square-size setting: reprint. `--columns 9 --rows 6` are internal corner counts, not square counts. These are calibration CLI inputs; resulting pattern settings and errors are recorded in the report. No new Python dependencies or npm installation are needed for calibration; its TypeScript frontend is already built.

## Calibration and tag parameters: one JSON file

`apriltag_config.json` stores camera resolution, intrinsics K, distortion coefficients, calibration resolution, AprilTag dictionary, physical tag size, refinement method, and smoothing alpha. Calibration values start as null; no calibration is invented.

Import your existing calibration once:

```bash
uv run --locked python apriltag_distance.py --import-calibration camera_calibration.npz --calibration-size 1280 720
```

Use the ACTUAL calibration image width and height. The imported calibration dimensions must match the actual stream dimensions displayed in the page. The NPZ must contain `K` and `dist` for the standard OpenCV pinhole model; fisheye calibration requires a different implementation. After import the NPZ is not needed. Restart the server and refresh the browser after any JSON edit. An alternate JSON can be loaded with `--config path/to/config.json`.

- Use the same physical camera, image mode/crop, and focus setting used for calibration. A matching resolution alone does not prove calibration compatibility.
- `tag_size_m` is the side length between the outer black-border corners, excluding the surrounding white margin. Default: 0.16 meters.
- All visible tags must have this size. Use unique tag IDs; duplicate IDs are detected but their range estimates are disabled.
- Browser camera selection replaces `camera.id`; `camera.id` and `buffer_size` are retained for compatibility but unused by this web app. `width`/`height` no longer constrain browser capture; saving calibration updates them to the measured frame size. Starting a preview does not overwrite the JSON or its calibration.
- Without calibration, preview and tag detection work, but distance/depth stay blank.
- Both pages offer Auto, common resolution presets, and custom width/height (1–4096 pixels per dimension). Auto requests the camera without forced dimensions; manual selections request exact dimensions. The page always displays the actual delivered frame size. Presets are not a list of verified camera capabilities. Unsupported requests show an error; choose Auto or another size. Changing settings stops the current stream; press Start camera to apply. Calibration locks camera/resolution controls after the first capture until all captures are reset or undone. The browser chooses a supported default; this is not a promise of maximum/native sensor resolution. If the active dimensions differ from calibration, preview and detection still work but range is disabled. Recalibrate in the active mode. Calibration locks dimensions on its first accepted view and rejects mixed-resolution captures; reset to start a new set.

## Readouts and timing

- **Distance:** camera optical center to tag center, sqrt(x²+y²+z²), smoothed independently per ID.
- **Depth:** raw z along the forward camera axis, not perpendicular distance to the tag plane.
- **Processing rate:** completed frame analyses per second, smoothed for readability; not advertised webcam FPS.
- **Round trip:** time from frame encoding start to result reception, including local encoding, transmission, processing and scheduling. This is not sensor-to-screen latency.
- **Detector time:** backend decode, detection and pose processing duration.
- **Reprojection error:** RMS distance in pixels between detected and projected corners. Diagnostic only; not a guarantee of accurate range.

Only one JPEG frame is in flight at a time. The next frame is captured after the prior result arrives. The displayed image is the exact processed frame, so tag outlines match it; the visible feed updates at analysis rate. JPEG quality is 0.95. Missing tags immediately clear readouts and reset their filters. A detector timeout stops capture and clears the interface. Network/processing errors are shown in the page.

Distance precision depends on calibration, print scale, tag pixel size, blur, and viewing angle. Validate against known ranges before using measurements in experiments. Planar pose ambiguity and corner noise can still cause jumps; this is a prototype, not a calibrated metrology instrument.

## Edit the Vite interface (optional)

Install a Node.js version supported by Vite 7 (20.19+ or 22.12+), then:

```bash
cd frontend
npm ci
npm run build
```

The frontend source is `frontend/src/main.ts`; API types are in `frontend/src/types.ts` and Vite configuration is in `frontend/vite.config.ts`. Strict mode is enabled in `frontend/tsconfig.json`. `npm run build` runs `tsc --noEmit` before building; you can also run `npm run typecheck` separately. The browser still executes the compiled JavaScript in `frontend/dist`.

Restart Python and refresh the page. For live frontend development, run the Python backend on port 8000 in one terminal and `npm run dev` inside `frontend` in another; open the Vite localhost URL (normally port 5173). `/api` and `/ws` are proxied to the distance server on port 8000. For calibration development, also start `uv run python calibrate_camera.py`, then open `/calibration.html` on the Vite URL; `/api/calibration` proxies to port 8001. The default WebSocket origin allowlist includes localhost/127.0.0.1 port 5173; if Vite chooses another port, free 5173 first.

Camera APIs require browser permission and localhost or HTTPS. This package is designed for a local single-user workstation. Python binds to 127.0.0.1. A hosted page alone cannot run this OpenCV backend, so this is delivered as a local application, not a cloud-hosted detector.

## Validation

```bash
uv sync --locked
uv run --locked python -m pytest tests -q
```

The default dev dependency group includes pytest and httpx. To install only runtime dependencies, use `uv sync --locked --no-dev` and launch with `uv run --locked --no-dev python apriltag_distance.py`. Add Python packages with `uv add PACKAGE`; add test/development packages with `uv add --dev PACKAGE`. uv manages Python dependencies; npm still manages optional frontend development.

Ten tests cover automatic resolution adoption/mismatch rejection, calibration corner detection, synthetic intrinsic recovery, config backup/preservation, session protection, and the original checks for synthetic known range, tag loss/filter clearing, missing calibration, resolution mismatch, malformed image handling, config validation, and WebSocket round-trip/recovery. Strict TypeScript checking, production frontend build and Python syntax checks passed. Actual webcam permissions, performance and accuracy must be checked on your own computer. Both redesigned pages and custom resolution controls were inspected in the browser. End-to-end webcam QA remains unavailable because the preview service cannot execute the Python backend or access your physical camera.

References:
- https://fastapi.tiangolo.com/advanced/websockets/
- https://vite.dev/guide/backend-integration.html
- https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia

The uv migration was verified with a fresh project environment, locked sync, and all six backend tests.

Frontend resolution tests: run `npm test` in `frontend`. Four tests cover Auto, exact manual requests, invalid dimensions, and actionable unsupported-mode errors. Ten Python tests also pass.

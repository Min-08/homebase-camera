# Raspberry Pi Simulation and Reliability Report

Date: 2026-07-07

Repository: `https://github.com/Min-08/homebase-camera/tree/main`

Environment used for simulation:

- Windows workstation, Python 3.13.8
- Standard CPython 3.13.8 for final PC setup verification
- A free-threaded CPython 3.13 interpreter was also present through `py -3` and was used to simulate dependency setup failure
- No Raspberry Pi 4 Model B hardware available
- No OV5647 camera module available
- No Picamera2 package available on this workstation
- No Ultralytics YOLO package or model installed

The real Raspberry Pi camera path could not be physically verified. This pass used static review, unit tests, mock capture, demo mode assets, synthetic baseline scenarios, missing dependency simulation, launcher review, and command execution where practical.

## Summary

The app already had defensive behavior for many missing hardware paths: Picamera2 absence returns a placeholder frame and warning, YOLO absence keeps the app in diff-only mode, SQLite enables WAL/busy timeout, and demo mode can exercise statuses `0`, `1`, and `2`.

The main confirmed defect was demo asset generation safety. `tools/generate_demo_assets.py` overwrote `demo/demo_seats.json`, `demo/demo_timeline.json`, and frames on every run, which could erase user-edited mapping files. This is now fixed: default generation only creates missing assets, and `--force` is required for intentional reset.

Additional hardening improved baseline diagnostics, camera handle reset after capture failure, Windows venv validation, dependency compatibility on Python 3.13, SQLite startup concurrency, Raspberry Pi setup guidance, and missing-zone-file messages.

## Simulation Matrix

| Area | Scenario | Method | Result | Fix Applied | Remaining Risk |
|---|---|---|---|---|---|
| Repo setup | clone/update latest main | `git clone ... .`, `git pull origin main` | Repository cloned into empty workspace and was up to date on `main` | None | None |
| Pi setup | fresh setup script flow | static review and `bash -n setup_raspberry_pi.sh` | Script creates venv, config, data dirs, and keeps existing config files | Added `--install-system-packages` for guided apt install of Python venv, Picamera2, and OpenCV packages | Actual apt install not run on Raspberry Pi hardware |
| Pi run | `run_app.sh` from project root or other cwd | static review and `bash -n` | Script cd's to its own directory, validates Linux venv, creates missing config files | None | Port conflict behavior still depends on Streamlit error output |
| Camera | Picamera2 missing | `python -c` with default config on Windows | Returned `ok=False` and message telling user to install `python3-picamera2` or use `run_mock.sh` | Reset cached camera handle after capture exceptions | Real camera unavailable and not physically verified |
| Camera | capture exception / broken handle | code review | A failed capture could keep a partially initialized cached object | Clear Picamera2/OpenCV cached handles after capture/read failure so reruns can retry | Needs real camera stress test |
| Baseline | missing baseline | unit tests and code review | App initializes a temporary baseline and warns | Existing behavior retained | Temporary baseline is still sensitive to first-frame occupancy |
| Baseline | corrupted baseline | synthetic invalid image test | Previous warning could be replaced by generic missing-baseline text | Preserve corrupted-baseline warning and explain temporary fallback | Real corrupted SD-card scenarios not physically tested |
| Baseline | resolution mismatch | synthetic image test | Baseline was resized silently | Added warning explaining old/new resolution and recommending recapture | Diff quality still depends on camera stability |
| YOLO | ultralytics/model missing | `python -c` `YoloDetector(enabled=True, ...)` | App reported unavailable YOLO and continued diff-only | Existing behavior verified | No real YOLO model inference tested |
| Demo | PC demo statuses `0`, `1`, `2` | `python -m pytest tests/test_demo.py`, Playwright smoke test | Timeline and injected evidence produce all required statuses without YOLO; browser observed statuses `0`, `1`, and `2` on Monitor | Existing tests retained | Real camera mode statuses still need hardware verification |
| Demo assets | generator default run | `python tools/generate_demo_assets.py` | Before fix it overwrote assets. After fix it skipped 7 existing assets. | Default now preserves existing seats, timeline, and frames | Users must use `--force` when they intentionally want reset |
| Demo assets | intentional reset | `python tools/generate_demo_assets.py --force` | Regenerated 7 demo assets | Added CLI flag and README reset instructions | Force still overwrites by design |
| Scheduling | diff/yolo interval gate | `tests/test_scheduler.py` and app code review | First run executes, then waits until interval; app updates smoothing only when detector/demo changes are due | Existing behavior retained | Multi-session Streamlit timing should be checked on the actual Pi |
| State smoothing | status `0`, `1`, `2`; object disabled; conservativeness | `tests/test_state_engine.py` | Person, object, empty transition, object-disabled, and conservativeness paths pass | Existing behavior retained | Restart counters remain approximate, as documented |
| SQLite | writes, duplicate status, WAL/busy timeout | `tests/test_storage.py`, timed Streamlit startup | Current status upserts, logs only status changes, WAL and busy timeout are set. Initial demo startup exposed a `database is locked` error when WAL was applied on every connection. | Configure WAL during initialization with retry, not on every connection; added regression test | Heavy multi-process write contention not fully reproduced |
| Zone editor | invalid/small/out-of-bounds/overlap logic | `tests/test_validation.py`, static review | Validation warns for small and out-of-bounds polygons; overlap logic present | Improved missing zone-file path messages | Interactive canvas drawing not fully browser-tested on Raspberry Pi |
| Scripts | Windows launchers | static review, `cmd /c setup_pc.bat`, timed `run_demo.bat`/`run_mock.bat` startup checks | Batch files cd to project root and use non-force demo generation; Streamlit starts on port 8501 | Added wrong-OS `.venv` checks, Python launcher fallback, and free-threaded CPython rejection in setup | `run_demo.bat` and `run_mock.bat` are long-running commands, so verification stopped them after startup |
| Dependencies | Windows Python 3.13 setup | `cmd /c setup_pc.bat`, pip resolver output | Loose NumPy constraint selected a source build on one interpreter; free-threaded CPython lacked wheels for Pillow/rpds-py | Pinned NumPy below 2.4 with Python-version markers and added free-threaded preflight checks | Future dependency releases may require constraint refresh |
| Scripts | macOS/Linux launchers | `bash -n setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh` | Syntax checks pass | None beyond Pi setup flag | File executable bits verified in git index, not on all filesystems |

## Defects Found

1. Demo asset generator overwrote existing user-edited demo mapping and timeline files by default.
2. Demo frame generation also overwrote existing files under `demo/frames/` by default.
3. Corrupted baseline image errors were replaced by a generic "No baseline image found" warning.
4. Baseline/current frame resolution mismatch was silently resized without telling the operator to recapture a baseline.
5. Picamera2/OpenCV capture failures could leave cached broken capture objects in memory for later reruns.
6. Windows batch launchers did not clearly detect a `.venv` directory created by macOS/Linux setup.
7. Windows setup assumed the `py` launcher and did not fall back to `python`.
8. Missing zone-file messages were hardcoded around `config/seats.json`, which was misleading in demo mode.
9. Raspberry Pi setup required the user to discover apt package commands from README/troubleshooting instead of offering an explicit setup option.
10. `requirements.txt` allowed latest NumPy to resolve to a source build in a Python 3.13 Windows setup.
11. `setup_pc.bat` selected a free-threaded CPython 3.13 interpreter through `py -3`, which caused native dependency builds and wheel failures.
12. Streamlit demo startup could hit `sqlite3.OperationalError: database is locked` because WAL mode was applied on regular connections.

## Fixes Applied

- Added `--force` to `tools/generate_demo_assets.py`.
- Changed default demo generation to create only missing assets and preserve existing `demo/demo_seats.json`, `demo/demo_timeline.json`, and demo frames.
- Added tests for default non-overwrite behavior and force-overwrite behavior.
- Preserved corrupted-baseline diagnostics when falling back to a temporary baseline.
- Added baseline resolution mismatch warnings.
- Added tests for corrupted baseline and resolution mismatch paths.
- Cleared cached Picamera2/OpenCV handles after capture failures so later reruns can retry cleanly.
- Added Windows `.venv\Scripts\activate.bat` validation to setup, demo, and mock batch files.
- Added Python command fallback in `setup_pc.bat`.
- Added free-threaded CPython detection to PC setup scripts.
- Added NumPy version markers to keep Windows Python 3.13 setup on a compatible wheel-backed line.
- Moved SQLite WAL configuration to initialization with retry instead of every connection.
- Added storage regression coverage that regular connections do not reapply WAL.
- Added `./setup_raspberry_pi.sh --install-system-packages` for Raspberry Pi OS system package installation.
- Improved zone-file missing-path error messages and added test coverage.
- Updated README with demo reset instructions and the Raspberry Pi package-install setup flag.

## Commands Executed

```bash
git clone https://github.com/Min-08/homebase-camera.git .
git pull origin main
python --version
python -m pytest
python -m compileall app.py homebase_camera tools tests
bash -n setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh
python tools/generate_demo_assets.py
python tools/generate_demo_assets.py --force
python tools/capture_baseline.py --mock --out data/snapshots/baseline.mock-test.jpg
python -c "from homebase_camera.config import load_settings; from homebase_camera.capture import CaptureManager; c=load_settings(); r=CaptureManager(c).read_frame(); print(r.ok); print(r.message[:240])"
python -c "from homebase_camera.yolo_detector import YoloDetector; y=YoloDetector(enabled=True, model_name='definitely_missing_model.pt'); print(y.status.available); print(y.status.message[:240])"
python -m pytest tests\test_generate_demo_assets.py tests\test_diff_detector.py tests\test_zones.py
python -m compileall tools\generate_demo_assets.py homebase_camera\diff_detector.py homebase_camera\capture.py homebase_camera\zones.py tests\test_generate_demo_assets.py tests\test_diff_detector.py
cmd /c setup_pc.bat
.venv\Scripts\python.exe -m pytest
cmd /c run_demo.bat
cmd /c run_mock.bat
npx --yes --package @playwright/cli playwright-cli open http://localhost:8501
npx --yes --package @playwright/cli playwright-cli snapshot
npx --yes --package @playwright/cli playwright-cli click <Zone Editor tab>
npx --yes --package @playwright/cli playwright-cli click <Logs tab>
npx --yes --package @playwright/cli playwright-cli click <Settings tab>
```

## Verification Results

| Command | Result |
|---|---|
| `python -m pytest` | Passed, 23 tests |
| `.venv\Scripts\python.exe -m pytest` | Passed, 23 tests |
| `python -m compileall app.py homebase_camera tools tests` | Passed |
| `bash -n setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh` | Passed |
| `python tools/generate_demo_assets.py` | Passed after fix, skipped 7 existing assets |
| `python tools/generate_demo_assets.py --force` | Passed after fix, generated 7 assets |
| Picamera2 missing simulation | Passed, returned actionable warning and placeholder path |
| YOLO missing simulation | Passed, stayed unavailable with diff-only warning |
| Mock baseline capture | Passed, saved mock baseline |
| Windows `setup_pc.bat` | Passed after dependency/free-threaded preflight fixes |
| Windows `run_demo.bat` | Passed timed startup check; Streamlit served on `http://localhost:8501`; stopped after verification |
| Windows `run_mock.bat` | Passed timed startup check; Streamlit served on `http://localhost:8501`; stopped after verification |
| Streamlit browser smoke test | Passed PC demo Monitor, Zone Editor, Logs, and Settings tab checks with 0 console errors |
| Raspberry Pi hardware | Not available |

## Recommended Real Raspberry Pi Test Checklist

Run this checklist on a Raspberry Pi 4 Model B with Raspberry Pi OS and one OV5647 camera module:

1. Fresh clone, then `./setup_raspberry_pi.sh --install-system-packages`.
2. Confirm `.venv` uses system site packages and can import Picamera2.
3. Run `python tools/capture_baseline.py` with an empty scene.
4. Run `./run_app.sh` and open `http://localhost:8501`.
5. Confirm a live camera frame appears and latest snapshot throttling behaves as configured.
6. Confirm missing/invalid `config/seats.json` messages are understandable.
7. Draw, save, rename, disable, duplicate, and delete a zone in the Streamlit zone editor.
8. Check a missing baseline, corrupted baseline, and changed camera resolution produce clear warnings.
9. Test a person sitting, leaving an object, and leaving the seat empty across several refresh intervals.
10. Enable YOLO only if installed, then confirm missing model/package does not crash the app.
11. Open a second browser session and confirm one-operator camera guidance remains acceptable.
12. Reboot the Pi and confirm SQLite current status restoration and log display.
13. Run `./run_mock.sh` as a fallback with the camera disconnected.
14. Run `python -m pytest` and `python -m compileall app.py homebase_camera tools tests` on the Pi if performance allows.

## Remaining Limitations

- Raspberry Pi hardware, OV5647 camera capture, camera ribbon/permission issues, and actual Picamera2 frame acquisition were not physically tested.
- YOLO model loading and inference were not tested because Ultralytics and a model file were intentionally absent in this workstation simulation.
- SQLite heavy lock contention was covered by retry/WAL tests and review, but not by a high-load multi-process stress test.
- Streamlit multi-session camera behavior still needs real Raspberry Pi validation because camera resource behavior can differ from PC mock/demo mode.
- Pixel-difference quality remains sensitive to lighting changes, camera movement, baseline quality, and camera field of view.

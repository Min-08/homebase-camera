# Raspberry Pi Simulation and Reliability Report

Date: 2026-07-15

Repository: `https://github.com/Min-08/homebase-camera/tree/main`

## Environments

- Windows workstation: Python 3.13.8, PowerShell, browser automation
- Raspberry Pi 4 Model B: 8 GB RAM, Raspbian GNU/Linux 13 (trixie), Python 3.13.5
- Camera: OV5647 detected by libcamera at `/base/soc/i2c0mux/i2c@1/ov5647@36`
- Camera stream under test: 1280x720 RGB888, 10 FPS target, JPEG quality 75
- Raspberry Pi service: `homebase-camera.service`, Streamlit on ports 8501 and 8502
- YOLO: disabled on the Pi; Ultralytics missing/failure paths were simulated

This pass combined code review, unit/integration tests, synthetic images, SQLite retry tests, shell checks, actual Raspberry Pi execution, live camera measurements, four-client streaming load, and browser interaction with the deployed dashboard and zone editor.

## Outcome

The camera, analysis worker, database, dashboard, live status panel, and zone editor are operational on the real Raspberry Pi. The main live-video defect was per-client work: every MJPEG connection independently loaded zones, read SQLite, drew overlays, and encoded JPEG. With several old dashboard/editor tabs open, the Pi used about 186 percent of one CPU core and delivered about 3 FPS despite a 10 FPS setting.

The live path now captures once, analyzes once, renders/encodes once, and distributes the cached JPEG to every client. Real mode no longer reruns Streamlit for each camera/status refresh. A later frame-sequence defect found during deployment testing was fixed before final verification.

An empty 1280x720 baseline was captured from the deployed zone editor. Pi-specific detection settings were tuned to a 1-second diff interval, one required object hit, one required empty hit, and a 0.015 changed-pixel threshold.

## Live Performance

| Measurement | Before | Final single probe | Four concurrent clients |
|---|---:|---:|---:|
| Delivered MJPEG FPS | 3.03 | 9.61 | 8.78 each |
| Process CPU, one core = 100% | 186.2% | 101.5% | 96.7% |
| Snapshot latency average | 253.0 ms | 26.3 ms | Not separately measured |
| MJPEG p95 frame gap | 382.0 ms | 117.9 ms | Clients stayed synchronized |
| MJPEG maximum frame gap | 399.7 ms | 207.6 ms | No disconnects |
| Camera frame age | 0.078 s average | 0.070 s at final health sample | Healthy |

The final health sample reported zero capture failures, no stream error, no analysis error, a saved baseline with no warning, and no Pi thermal throttling. Temperature during checks was approximately 54.5 C to 60.8 C.

## Simulation Matrix

| Area | Scenario | Method | Result | Fix Applied | Remaining Risk |
|---|---|---|---|---|---|
| Repository | latest `main`, dirty files | git status/pull review | Local and Pi source matched; runtime WAL files were untracked | Ignore `data/*.db-*` | Runtime config/data remain intentionally untracked |
| Pi setup | launcher syntax and paths | `bash -n`, static review | All shell launchers pass syntax and change to project root | Existing preflight retained | Fresh apt install was not repeated on the configured Pi |
| Camera | real OV5647 capture | Picamera2/service/health/libcamera | 1280x720 frames captured continuously | Background diagnostics and recovery added | A kernel/driver call that never returns can still need service restart |
| Camera | unexpected capture exception | deterministic unit test | Capture thread recovers and continues | Exception containment, counters, error state, retry backoff | Physical ribbon disconnect during streaming was not performed |
| Streaming | several open browser tabs | live measurement | 3.03 FPS and 186.2% CPU before fix | Shared JPEG producer and in-memory status/zones | 1280x720 JPEG remains about one CPU core at 10 FPS |
| Streaming | four concurrent clients | four simultaneous MJPEG readers | All four received 8.78 FPS with 96.7% CPU | One encoded frame is broadcast to all clients | Wi-Fi quality outside this LAN was not tested |
| Streaming | cached frame sequence | deploy-time live probe | First implementation stopped after two frames | Background capture now advances shared sequence; regression test added | Covered by health sequence/frame-age fields |
| Baseline | missing/corrupted/mismatched | unit tests and live startup | Temporary fallback worked but warning disappeared after first analysis | Persistent warning and live `Set empty baseline` action | Recapture after camera movement or lighting change |
| Baseline | real empty scene | visual snapshot review and API action | Saved `data/snapshots/baseline.jpg`, warning cleared | Baseline endpoint serializes with analysis | Operator must ensure seats are empty before reset |
| Diff/state | actual zones plus synthetic changed frame | Pi-side synthetic image mutation | All 3 zones produced status 2; status 1/0 transitions also passed | Pi tuned to one object hit for 1-second response | A hand is status 2 in diff-only mode, not status 1 |
| YOLO | missing package and inference exception | monkeypatched tests | App remains available in diff-only mode | Background analysis now includes optional interval-gated YOLO | No real YOLO model was installed or benchmarked |
| SQLite | integrity, WAL, timeout, repeated status | Pi PRAGMAs and tests | `integrity_check=ok`, WAL, 5000 ms timeout, 3 current rows | Retry regression test and single analysis writer | Multi-process writers outside this service are unsupported |
| Multi-session | several Streamlit/editor tabs | Chrome and Pi CPU checks | Camera remained single-owner; clients shared stream work | Real mode has one background analysis writer | Running a second app process still conflicts for camera ownership |
| Zone editor | load, draw, save, delete | deployed browser interaction | Demo target selected, polygon drawn, saved, observed, deleted, and file restored | Live editor, strict JSON validation, atomic writes, write lock | Touch UX on a small phone was not tested |
| Zone validation | malformed/small/out-of-bounds/overlap | unit/API tests and review | Invalid points rejected; warnings returned for risky geometry | Strict polygon parser and atomic zone writes | Warnings do not block intentional unusual zones |
| Dashboard | Monitor/Zone Editor/Logs/Settings | deployed Chrome DOM and console checks | All views rendered; no browser console errors | Live status iframe; live mode avoids missing auto-refresh dependency | Logs/settings still need manual refresh in real mode |
| Demo assets | default and force generation | generator commands and tests | Default preserved all 7 assets; force regenerated intentionally | Existing non-overwrite protection retained | `--force` overwrites by design |
| Config | malformed numeric/camera dimensions | TOML mutation tests | Previously could leak `TypeError` | All numeric fields produce `ConfigError`; camera dimensions validated | Boolean/path type validation remains conservative |

## Defects Found in This Pass

1. Every MJPEG client repeated overlay drawing, zone file reads, SQLite reads, and JPEG encoding.
2. The real dashboard depended on a missing `streamlit_autorefresh` component even though live video already had its own transport.
3. Multiple Streamlit sessions ran independent diff/state engines and could write competing status decisions.
4. The background live analysis path did not run optional YOLO even when configured.
5. The capture thread could die on an unexpected exception without a health-visible reason.
6. The first shared-frame implementation did not increment the sequence in the background refresh path and froze after two frames.
7. A missing baseline warning disappeared after the first temporary-baseline analysis.
8. There was no live UI action to replace the temporary baseline.
9. Zone save/delete operations were non-atomic and could lose updates under concurrent requests.
10. Invalid JSON and partially malformed polygons could close a request or silently discard bad points.
11. Snapshot requests repeated expensive encoding instead of returning the latest shared frame.
12. Full-frame RGBA overlay composition consumed about 53.5 ms per frame on the Pi.
13. Live-mode sidebar controls appeared editable but did not control the background worker.
14. SQLite WAL sidecar files appeared as untracked git files on the Pi.
15. Malformed numeric TOML could raise a raw `TypeError` instead of `ConfigError`.
16. Storage lock retries and YOLO inference failure behavior lacked direct regression tests.

## Fixes Applied

- Added one background capture pipeline with frame sequence, age, counters, failure state, and exception recovery.
- Added one live analysis worker as the real-mode status writer, including optional interval-gated YOLO.
- Added one overlay/JPEG producer shared by MJPEG clients and snapshots.
- Replaced full-frame alpha compositing with direct RGBA drawing onto the RGB frame.
- Added `/health`, `/api/status`, `/snapshot.jpg`, `/status-panel`, and baseline diagnostics to the shared service.
- Added live baseline capture through `POST /api/baseline` and the zone editor button.
- Kept temporary-baseline warnings active until a saved baseline is set.
- Disabled misleading Streamlit runtime controls in real mode and moved real-time status to a polling iframe.
- Made zone writes atomic and serialized; added strict request/point validation and actionable HTTP 400 errors.
- Added zone save warnings and delete confirmation.
- Added numeric configuration coercion/validation and camera source/dimension validation.
- Added tests for capture recovery, shared JPEG caching, live HTTP endpoints, malformed polygons, baseline persistence, overlay output, SQLite retry, malformed config, missing YOLO, and inference failure.

## Commands Executed

```bash
git pull --ff-only origin main
python -m pytest -q
python -m compileall -q app.py homebase_camera tools tests
bash -n setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh
python tools/generate_demo_assets.py
python tools/generate_demo_assets.py --force
node --check -
systemctl is-enabled homebase-camera.service
systemctl is-active homebase-camera.service
systemctl show homebase-camera.service -p MainPID -p NRestarts -p CPUUsageNSec
journalctl -u homebase-camera.service --since "30 minutes ago"
rpicam-hello --list-cameras
curl http://127.0.0.1:8502/health
curl http://127.0.0.1:8502/api/status
curl http://127.0.0.1:8502/snapshot.jpg
```

Additional Python probes measured snapshot latency, MJPEG frame timing, four concurrent readers, process CPU, synthetic diff/state transitions, and SQLite PRAGMAs. Browser automation exercised all dashboard tabs and the deployed canvas workflow.

## Verification Results

| Check | Result |
|---|---|
| Local `python -m pytest -q` | 34 passed |
| Pi `python -m pytest -q` before final documentation/config hardening | 29 passed |
| Python compileall | Passed |
| Shell syntax | Passed |
| Zone editor/status page JavaScript syntax | Passed |
| Demo generator default | Passed, 0 generated and 7 preserved |
| Demo generator `--force` | Passed, intentional regeneration only |
| Real OV5647 detection | Camera listed and Picamera2 captured continuously |
| Pi service | enabled, active/running, `NRestarts=0` after intentional restart |
| SQLite | integrity ok, WAL, busy timeout 5000 ms |
| Browser | Monitor, Zone Editor, Logs, Settings, canvas save/delete, 0 console errors |
| Final health | frame/capture/stream/analysis running, no errors or warnings |

## Remaining Limitations

- A real hand/person placement test was not physically performed by the operator during this automated pass. The exact baseline, camera frame, and zones passed synthetic end-to-end detection on the Pi.
- Diff-only mode cannot classify a person. A hand or other changed region publishes status 2; status 1 requires YOLO person evidence.
- Ultralytics/model loading and inference performance were not tested on the Pi.
- Pixel difference remains sensitive to sunlight, lighting transitions, camera movement, and an incorrect occupied baseline.
- A camera driver call that hangs inside native code may need `systemctl restart homebase-camera.service`.
- 1280x720 overlay/JPEG generation at about 10 FPS still consumes approximately one Pi CPU core.

## Recommended Field Checklist

1. Confirm the live health page shows frame age below 0.5 seconds and no errors.
2. Keep all three zones empty and press `Set empty baseline` after any camera movement.
3. Put a hand or object in each zone; with the deployed Pi tuning it should reach status 2 on the next 1-second analysis.
4. Remove it; status should return to 0 on the next analysis.
5. If YOLO is installed later, verify a seated person reaches status 1 and measure CPU/temperature again.
6. Test morning/evening lighting and recapture the baseline if false positives appear.
7. Reboot and verify ports 8501/8502, current status restoration, and service logs.
8. Disconnect/reconnect the camera only during a controlled maintenance test, then confirm recovery or systemd restart behavior.

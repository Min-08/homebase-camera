# Homebase Camera

Raspberry Pi 4B prototype for local, camera-based homebase seat occupancy detection. It uses one normal OV5647-style camera, polygon seat zones, pixel-difference detection, optional periodic YOLO correction, SQLite status logging, and a Streamlit dashboard.

The project also includes a first-class PC demo mode. Demo mode uses generated frames and synthetic ground-truth evidence so the full `0/1/2` workflow can be shown without Raspberry Pi hardware, a physical camera, Picamera2, or YOLO.

Status codes:

```text
0 = empty / available
1 = occupied by a person
2 = temporarily left / object occupancy
```

This system does not perform face recognition or personal identification.

## Raspberry Pi Real Camera Quick Start

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_raspberry_pi.sh run_app.sh run_mock.sh
./setup_raspberry_pi.sh
./run_app.sh
```

Open the dashboard on the Raspberry Pi at `http://localhost:8501`. From another device on the same network, open `http://<raspberry-pi-ip>:8501`.

If you copied the folder manually instead of using `git clone`, open a terminal in the copied `homebase-camera` folder and run the same commands.

To also install Raspberry Pi OS camera/system packages during setup, run:

```bash
./setup_raspberry_pi.sh --install-system-packages
```

## PC Demo Quick Start

PC demo mode is for presentation, development, and mapping practice. It is not a claim of real detection accuracy. It uses generated demo frames and demo evidence.

Use a standard CPython 3 installation. Experimental free-threaded CPython builds are rejected by the setup scripts because some required packages may not publish compatible wheels.

### Windows PC

```bat
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
setup_pc.bat
run_demo.bat
```

### macOS / Linux PC

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_pc.sh run_demo.sh run_mock.sh
./setup_pc.sh
./run_demo.sh
```

PC demo mode does not require Picamera2, Raspberry Pi hardware, a camera, or Ultralytics YOLO.

## Running Modes

Real Raspberry Pi mode:

```bash
./run_app.sh
```

PC demo mode:

```bash
./run_demo.sh
```

Windows PC demo:

```bat
run_demo.bat
```

Mock mode without camera hardware:

```bash
./run_mock.sh
```

Windows mock mode:

```bat
run_mock.bat
```

Advanced manual launch after dependencies are installed:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Architecture

```text
[OV5647 camera / generated demo frame / mock image]
        |
[Picamera2, OpenCV, or demo capture]
        |
[Dynamic polygon zones from seats JSON]
        |
[Interval-gated pixel difference detector]
        |
[Optional interval-gated YOLO correction]
        |
[Demo evidence injection in PC demo mode]
        |
[State smoothing and conservative decision logic]
        |
[SQLite current_status + status_log]
        |
[Streamlit dashboard + zone editor]
```

## Auto-Refresh and Intervals

The sidebar has:

- Auto-refresh toggle
- Refresh interval slider
- Manual refresh button
- YOLO enabled/disabled
- Object occupancy enabled/disabled
- Object conservativeness slider

Config defaults:

```toml
[app]
auto_refresh_enabled = true
refresh_interval_seconds = 3

[detection]
diff_interval_seconds = 3
yolo_interval_seconds = 20
```

The dashboard reruns at the refresh interval, but detector work is separately gated:

- `diff_interval_seconds` controls when pixel-diff analysis runs.
- `yolo_interval_seconds` controls when YOLO analysis runs.
- If a detector is not due yet, the app reuses the last evidence/status instead of advancing smoothing on every rerun.
- The monitor shows last diff run time and last YOLO run time.

## PC Mapping Demo

Use PC demo mode and open the `Zone Editor` tab:

```bash
./run_demo.sh
```

or on Windows:

```bat
run_demo.bat
```

In the editor you can:

- Draw a polygon over the demo frame
- Save to the demo seats file or normal `config/seats.json`
- Rename existing zones
- Enable/disable zones
- Delete zones
- Duplicate zones
- View the coordinate list
- View polygon area
- Preview the zone JSON

The app warns about missing zones, polygons with fewer than 3 points, very small polygons, out-of-bounds coordinates, and heavy zone overlap.

## Zone Files

Real mode uses:

```text
config/seats.json
```

PC demo mode uses:

```text
demo/demo_seats.json
```

Example structure:

```json
{
  "zones": [
    {
      "seat_id": "seat_001",
      "seat_name": "Seat 1",
      "polygon": [[120, 220], [260, 220], [270, 390], [110, 390]],
      "enabled": true
    }
  ]
}
```

You can regenerate demo frames, demo seats, and the demo timeline:

```bash
python tools/generate_demo_assets.py
```

By default this creates only missing demo assets and preserves user-edited `demo/demo_seats.json`, `demo/demo_timeline.json`, and existing files under `demo/frames/`.
To intentionally reset the demo assets to the built-in defaults:

```bash
python tools/generate_demo_assets.py --force
```

## Baseline Image

The pixel-difference detector compares the current frame with a baseline/reference image.

Capture a baseline from the configured camera:

```bash
python tools/capture_baseline.py
```

Capture a mock baseline:

```bash
python tools/capture_baseline.py --mock
```

If no baseline exists, the app uses the first frame as a temporary baseline and shows a warning.

## Raspberry Pi Camera Troubleshooting

Install camera dependencies on Raspberry Pi OS:

```bash
sudo apt update
sudo apt install python3-picamera2 python3-opencv
./setup_raspberry_pi.sh
```

If the camera is not detected:

- Check the ribbon cable orientation and connector latch.
- Reboot after connecting the camera.
- Confirm the camera works with Raspberry Pi OS camera tools.
- Use `./run_mock.sh` or `./run_demo.sh` to verify the app without hardware.

Multi-session note: capture resources are cached to reduce duplicate camera opens, but one dashboard operator is still recommended on Raspberry Pi.

## YOLO Notes and License Caution

YOLO correction is optional. If `ultralytics` or the model is missing, the app continues in diff-only mode and shows a warning.

Install YOLO only if you want object/person correction:

```bash
source .venv/bin/activate
pip install ultralytics
```

Increase `yolo_interval_seconds` if Raspberry Pi performance is slow.

License note: the Ultralytics Python package and common YOLOv8 models have AGPL-related licensing considerations. Check the license before closed or commercial use.

## SQLite and Snapshot Robustness

SQLite uses a timeout, `busy_timeout`, and WAL mode by default:

```toml
[storage]
db_path = "data/status.db"
timeout_seconds = 10
busy_timeout_ms = 5000
wal_enabled = true
```

Latest snapshot writes are throttled to reduce SD card writes:

```toml
[privacy]
save_snapshots = true
snapshot_interval_seconds = 30
```

Set `save_snapshots = false` to avoid snapshot writes.

## Privacy and Safety

- No face recognition
- No personal identification
- No raw video recording by default
- Local SQLite status data
- Optional snapshots can be disabled

For real shared spaces, use high-angle/top-view placement where possible and post a clear camera notice.

## Known Limitations

- Demo mode uses generated frames and synthetic evidence; it is for presentation and mapping practice.
- Pixel difference is sensitive to lighting and camera movement.
- YOLO on Raspberry Pi 4B can be slow; use long intervals.
- State smoothing history is restored from the latest SQLite status, but hit counters are still approximate after restart.
- Multi-session camera safety is improved with a cached resource, but Raspberry Pi camera hardware is still best used from one dashboard session at a time.

## Development

Run tests without Raspberry Pi hardware or YOLO:

```bash
python -m pytest
python -m compileall app.py homebase_camera tools tests
bash -n setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh
python tools/generate_demo_assets.py
python tools/generate_demo_assets.py --force
```

Windows batch files are provided for users, but should be tested on Windows before relying on a classroom presentation machine.

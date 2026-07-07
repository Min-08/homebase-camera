# Homebase Camera

Raspberry Pi 4B prototype for local, camera-based homebase seat occupancy detection. It uses one OV5647-style normal field-of-view camera, polygon seat zones, pixel-difference detection, optional periodic YOLO correction, SQLite status logging, and a Streamlit dashboard.

The system does not perform face recognition or personal identification. It only publishes seat state:

```text
0 = empty / available
1 = occupied by a person
2 = temporarily left / object occupancy
```

## Raspberry Pi Quick Start

Clone the repository on the Raspberry Pi, then run the setup script once and the launcher whenever you want to start the dashboard:

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_raspberry_pi.sh run_app.sh run_mock.sh
./setup_raspberry_pi.sh
./run_app.sh
```

Open the dashboard on the Raspberry Pi at `http://localhost:8501`. From another device on the same network, open `http://<raspberry-pi-ip>:8501`.

If you copied the folder manually instead of using `git clone`, open a terminal in the copied `homebase-camera` folder and run the same commands.

No camera hardware available yet:

```bash
./run_mock.sh
```

## Target Hardware

- Raspberry Pi 4 Model B, 8 GB RAM recommended
- One OV5647 camera module
- Normal camera field of view, approximately 60 +/- 5 degrees
- Raspberry Pi OS with Python 3.10 or newer

The prototype supports any number of configured zones, but the physical number of seats covered depends on camera placement, height, and lens field of view.

## Architecture

```text
[OV5647 camera / mock image]
        |
[Picamera2 or fallback capture]
        |
[Dynamic polygon zones from config/seats.json]
        |
[Pixel difference detector]
        |
[Optional periodic YOLO correction]
        |
[State smoothing and conservative decision logic]
        |
[SQLite current_status + status_log]
        |
[Streamlit dashboard + zone editor]
```

Pixel difference is the primary lightweight detector. YOLO is optional and runs only periodically by default, because Raspberry Pi 4B is not a good target for continuous real-time YOLO inference.

## Installation Details

The setup script creates `.venv`, installs Python dependencies, creates `data/`, `data/snapshots/`, and `config/`, and copies examples to user-editable files if missing:

- `config/settings.example.toml` -> `config/settings.toml`
- `config/seats.example.json` -> `config/seats.json`

It is safe to run repeatedly. It does not overwrite existing settings, zones, snapshots, or logs.

Picamera2 is usually installed through Raspberry Pi OS packages, not pip:

```bash
sudo apt update
sudo apt install python3-picamera2 python3-opencv
```

Then rerun:

```bash
./setup_raspberry_pi.sh
```

## Running

Normal Raspberry Pi launch:

```bash
./run_app.sh
```

Development/mock launch without camera hardware:

```bash
./run_mock.sh
```

Advanced manual launch after dependencies are installed:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Baseline Image

The pixel-difference detector compares the current frame with a baseline/reference image.

Capture a baseline from the configured camera:

```bash
python tools/capture_baseline.py
```

Capture a mock baseline for development:

```bash
python tools/capture_baseline.py --mock
```

The default baseline path is `data/snapshots/baseline.jpg`. If no baseline exists, the app uses the first frame as a temporary baseline and shows a warning.

## Configuring Seat Zones

Zones are polygons loaded from `config/seats.json`. Disabled zones are ignored. Example:

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

Use the dashboard `Zone Editor` tab to draw and save zones. If the browser canvas component is unavailable, use the fallback OpenCV editor:

```bash
python tools/zone_editor_cv.py
```

Mock editor mode:

```bash
python tools/zone_editor_cv.py --mock
```

In the OpenCV editor, click polygon points around a seat, press `f` to finish/save, `u` to undo a point, `r` to reset points, and `q` to quit.

## Detection Settings

Edit `config/settings.toml` after setup. Important defaults:

```toml
[detection]
diff_interval_seconds = 3
yolo_enabled = true
yolo_interval_seconds = 20
yolo_model = "yolov8n.pt"
object_occupancy_enabled = true
object_conservativeness = 5
empty_required_hits = 2
person_required_hits = 1
```

`object_occupancy_enabled` controls whether the public dashboard can output status `2`. If false, object-only evidence never publishes status `2`.

`object_conservativeness` is an integer from 0 to 10:

- `0`: status `2` can trigger quickly
- `5`: balanced default
- `10`: requires persistent, high-confidence object evidence

Internally, higher conservativeness increases both the required repeated object hits and the object confidence threshold.

## YOLO Notes

YOLO correction is optional. If `ultralytics` or the model is missing, the app continues in diff-only mode and shows a warning.

Install YOLO only if you want object/person correction:

```bash
source .venv/bin/activate
pip install ultralytics
```

The default interval is 20 seconds. Increase `yolo_interval_seconds` on Raspberry Pi if the dashboard becomes slow.

License note: the Ultralytics Python package and common YOLOv8 models have AGPL-related licensing considerations. For school prototypes this may be acceptable, but check the license before using it in a closed or commercial deployment.

## SQLite Storage

The local database path is `data/status.db`. Tables:

- `current_status`: latest status per seat
- `status_log`: appended status changes

The dashboard `Logs` tab displays both tables and can clear the log. The app avoids logging every frame when the status did not change.

## Privacy and Safety

- No face recognition
- No personal identification
- No raw video recording by default
- Local-only SQLite status data by default
- Optional snapshots can be disabled with `save_snapshots = false`

For real shared spaces, use high-angle/top-view placement where possible and post a clear camera notice.

## Troubleshooting

Missing Picamera2:

```bash
sudo apt install python3-picamera2
./setup_raspberry_pi.sh
```

Camera not detected:

- Check the ribbon cable orientation and connector latch.
- Reboot after connecting the camera.
- Confirm the camera works with Raspberry Pi OS camera tools.
- Run `./run_mock.sh` to verify the app without hardware.

OpenCV fallback/editor missing:

```bash
sudo apt install python3-opencv
```

YOLO model missing or slow:

- The app still runs in diff-only mode.
- Install with `pip install ultralytics` only if needed.
- Increase `yolo_interval_seconds` in `config/settings.toml`.

Streamlit port already in use:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8502
```

Bad zone JSON:

- Open the dashboard and check the error message.
- Restore from `config/seats.example.json`.
- Use `python tools/zone_editor_cv.py --mock` to create a fresh zone file.

## Development

Run tests without Raspberry Pi hardware or YOLO:

```bash
python -m pytest
```

The tests cover zone loading/validation, polygon masks, state smoothing and object conservativeness, and SQLite insert/update behavior.

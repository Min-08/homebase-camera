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

## Raspberry Pi 원클릭 실행 (한국어)

Raspberry Pi OS에서는 Windows의 `.exe` 대신 더블클릭 가능한 `.desktop` 실행 아이콘을 사용합니다. 이 프로젝트는 전체 시스템 실행과 주요 기능별 실행 아이콘을 함께 설치합니다.

처음 설치하는 Raspberry Pi에서는 터미널을 열고 다음 명령을 한 번 실행합니다.

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_raspberry_pi.sh homebase scripts/*.sh
./setup_raspberry_pi.sh --install-system-packages --install-launchers
```

이미 설치와 카메라 설정이 끝난 Raspberry Pi라면 실행 아이콘만 설치하거나 갱신하면 됩니다.

```bash
cd ~/homebase-camera
git pull
chmod +x homebase scripts/pi_control.sh scripts/install_desktop_launcher.sh
./scripts/install_desktop_launcher.sh
```

설치 후 바탕화면과 애플리케이션 메뉴에 다음 아이콘이 생깁니다.

- **Homebase 전체 실행**: 기존 systemd 서비스를 시작하고 대시보드를 엽니다. 서비스가 없는 설치에서는 백그라운드 직접 실행으로 대체합니다.
- **Homebase 라이브 조닝**: 카메라 공유 서비스를 확인한 뒤 실시간 조닝 편집기를 엽니다.
- **Homebase 상태 점검**: 서비스, 대시보드, 카메라 프레임, 분석 시간, 좌석 상태 API를 한 번에 확인합니다.
- **Homebase 빈 기준 저장**: 모든 좌석이 비어 있는지 확인한 뒤 현재 프레임을 변화 감지 기준으로 저장합니다.
- **Homebase 실시간 로그**: 최근 서비스 로그를 표시하고 새 로그를 계속 출력합니다. 종료할 때는 `Ctrl+C`를 누릅니다.
- **Homebase 전체 재시작**: 카메라가 멈췄거나 프레임 갱신이 지연될 때 서비스를 재시작하고 대시보드를 엽니다.
- **Homebase 전체 종료**: 카메라와 대시보드 서비스를 종료합니다.
- **Homebase 실행 메뉴**: 위 기능을 번호로 선택해서 실행합니다.

처음 아이콘을 더블클릭했을 때 Raspberry Pi OS가 확인하면 **실행** 또는 **실행 허용**을 선택합니다. 설치 스크립트가 실행 권한과 신뢰 메타데이터를 자동으로 설정하지만, 데스크톱 환경에 따라 이 확인이 한 번 표시될 수 있습니다.

아이콘과 같은 기능을 터미널에서도 모듈별로 실행할 수 있습니다.

```bash
./homebase             # 전체 실행
./homebase zones       # 라이브 조닝
./homebase health      # 전체 상태 점검
./homebase baseline    # 빈 좌석 기준 이미지 저장
./homebase logs        # 실시간 로그
./homebase restart     # 전체 재시작
./homebase stop        # 전체 종료
./homebase menu        # 실행 메뉴
```

카메라는 한 프로세스만 소유할 수 있으므로 `./run_app.sh`를 여러 터미널에서 동시에 실행하지 마세요. `./homebase`는 이미 실행 중인 systemd 서비스를 먼저 확인하므로 일상 실행에는 이 명령이나 바탕화면 아이콘을 사용하면 됩니다.

같은 네트워크의 다른 기기에서 접속할 주소는 다음과 같습니다. `<라즈베리파이-IP>` 부분을 실제 IP로 바꿉니다.

```text
대시보드:       http://<라즈베리파이-IP>:8501/
라이브 조닝:    http://<라즈베리파이-IP>:8502/zone-editor
카메라 상태:    http://<라즈베리파이-IP>:8502/health
MJPEG 스트림:   http://<라즈베리파이-IP>:8502/stream.mjpg
```

프레임이 멈추거나 업데이트가 느리면 먼저 `./homebase health`를 실행합니다. 카메라 상태가 응답하지 않으면 `./homebase restart`로 재시작하고, 계속 실패하면 `./homebase logs`에서 오류를 확인합니다.

## Raspberry Pi Real Camera Quick Start

```bash
git clone https://github.com/Min-08/homebase-camera.git
cd homebase-camera
chmod +x setup_raspberry_pi.sh run_app.sh run_mock.sh homebase scripts/*.sh
./setup_raspberry_pi.sh --install-launchers
./homebase
```

Open the dashboard on the Raspberry Pi at `http://localhost:8501`. From another device on the same network, open `http://<raspberry-pi-ip>:8501`.

Real mode also exposes a shared live service on port `8502`:

```text
http://<raspberry-pi-ip>:8502/stream.mjpg
http://<raspberry-pi-ip>:8502/zone-editor
http://<raspberry-pi-ip>:8502/health
```

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
[Single background capture manager]
        |
[Interval-gated diff + optional YOLO analysis worker]
        |
[SQLite current status + change log]
        |
[One shared overlay/JPEG producer]
        |
[MJPEG stream + live status + zone editor + Streamlit dashboard]
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

In Raspberry Pi live mode, camera video and seat status update independently without rerunning the whole Streamlit dashboard. Detection settings come from `config/settings.toml`; restart the service or app after editing them. This keeps multiple browser tabs from duplicating camera analysis and JPEG encoding.

In demo/mock mode, the dashboard reruns at the refresh interval, but detector work is separately gated:

- `diff_interval_seconds` controls when pixel-diff analysis runs.
- `yolo_interval_seconds` controls when YOLO analysis runs.
- If a detector is not due yet, the app reuses the last evidence/status instead of advancing smoothing on every rerun.
- The monitor shows last diff run time and last YOLO run time.

The real-mode live status panel shows current analysis time, frame age, warnings, and seat states.

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

In real mode, open `http://<raspberry-pi-ip>:8502/zone-editor` and press **Set empty baseline** while every seat zone is empty. This saves `data/snapshots/baseline.jpg` without stopping the stream.

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

Multiple browser clients share one capture, analysis, overlay, and JPEG pipeline. Do not run two separate Homebase Camera processes at the same time because only one process can own the Picamera2 device.

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
- A hard hang inside a camera driver call may still require a systemd service restart.
- Diff-only mode reports a changed hand/object as status `2`; status `1` requires YOLO person evidence or demo evidence.

## Development

Run tests without Raspberry Pi hardware or YOLO:

```bash
python -m pytest
python -m compileall app.py homebase_camera tools tests
bash -n homebase setup_raspberry_pi.sh run_app.sh run_mock.sh setup_pc.sh run_demo.sh scripts/pi_control.sh scripts/install_desktop_launcher.sh
python tools/generate_demo_assets.py
python tools/generate_demo_assets.py --force
```

Windows batch files are provided for users, but should be tested on Windows before relying on a classroom presentation machine.
